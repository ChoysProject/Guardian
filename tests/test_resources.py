import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.ai.gateway import _parse_review, review_resources
from app.main import app
from app.models import SessionLocal, Server
from app.plugins import editor as plugin_editor
from app.resource_collect import plugin_for_server
from app.secrets_store import decrypt
from app.resources import (
    analyze_server,
    parse_payload,
    render_resource_report,
    resource_payload,
    save_snapshot,
)


def test_parse_snapshot_variants():
    rows = parse_payload(
        json.dumps(
            {
                "server": "eai-01",
                "date": "2026-09-01",
                "cpu": 23.5,
                "mem": {"used_pct": 61.2},
                "disk": {"/": 72, "/data": 40},
                "instances": {"was": "ok", "mq": "down"},
            }
        )
    )
    item = rows[0]
    assert item["cpu"]["usage_pct"] == 23.5
    assert item["mem"]["used_pct"] == 61.2
    mounts = {disk["mount"]: disk["used_pct"] for disk in item["disk"]}
    assert mounts["/"] == 72
    assert mounts["/data"] == 40
    names = {inst["name"]: inst["ok"] for inst in item["instances"]}
    assert names["was"] is True
    assert names["mq"] is False


def _rich_snapshot(server: str, day: str, age: int) -> dict:
    used_pct = 70.0 + 2.0 * age
    return {
        "server": server,
        "date": day,
        "cpu": {
            "cores": 4,
            "samples": [
                {"hour": "03", "cpu_pct": 10 + age, "mem_pct": 40 + age},
                {"hour": "14", "cpu_pct": 60 + age, "mem_pct": 55 + age},
            ],
        },
        "mem": {"used_pct": 50 + age, "swap_used_pct": 4 + age},
        "disk": [
            {"mount": "/data", "used_pct": used_pct, "total_gb": 200, "used_gb": 2 * used_pct}
        ],
        "instances": [
            {"name": "was", "ok": age != 2, "cpu_pct": 20 + age, "mem_mb": 1000 + 100 * age, "restarts": 1 if age == 2 else 0}
        ],
        "top": [{"name": "java", "cpu_pct": 20 + age, "mem_pct": 30}],
    }


def test_rich_snapshot_analysis():
    end = datetime(2026, 7, 7)
    for age in range(5):
        day = (end - timedelta(days=4 - age)).strftime("%Y-%m-%d")
        rows = parse_payload(json.dumps(_rich_snapshot("rich-01", day, age)))
        save_snapshot(rows[0])

    analysis = analyze_server("rich-01", days=5, end="2026-07-07")
    assert analysis["count"] == 5
    # 시간대별 표본에서 하루 평균과 최고치를 만든다
    assert analysis["cpu"]["avg"] is not None
    assert analysis["cpu"]["peak_max"] == 64
    assert analysis["busy_hours"][0]["hour"] == "14"
    # 하루 2%p 씩 올라 마지막이 78%, 남은 22%p → 11일
    disk = analysis["disks"][0]
    assert disk["growth_per_day"] == 2.0
    assert disk["days_to_full"] == 11
    assert disk["free_gb"] is not None
    inst = analysis["instances_detail"][0]
    assert inst["name"] == "was"
    assert inst["restarts"] == 1
    assert inst["fail_days"] == 1
    assert analysis["top_processes"][0]["name"] == "java"

    payload = resource_payload(analysis)
    assert payload["disks"][0]["days_to_full"] == 11
    assert "items" not in payload

    report = render_resource_report(
        analysis,
        start="2026-07-03",
        end="2026-07-07",
        ai={"summary": "디스크가 빠르게 찹니다.", "risks": ["/data 11일"], "actions": ["로그 정리"]},
    )
    assert "AI 총평" in report["markdown"]
    assert "디스크가 빠르게 찹니다." in report["markdown"]
    assert "로그 정리" in report["html"]
    assert "11일 뒤 가득 참" in report["markdown"]
    assert "14시" in report["markdown"]


def test_ai_review_disabled_and_parsing():
    assert review_resources({"server": "x"}) == {}
    parsed = _parse_review('```json\n{"summary": "요약", "risks": ["a", "b"], "actions": []}\n```')
    assert parsed["summary"] == "요약"
    assert parsed["risks"] == ["a", "b"]
    assert parsed["actions"] == []
    assert _parse_review("그냥 문장")["summary"] == "그냥 문장"


def test_resource_report_keeps_going_when_ai_fails(monkeypatch):
    def boom(_payload):
        raise RuntimeError("openai down")

    monkeypatch.setattr("app.ai.gateway.settings.openai.enabled", True)
    monkeypatch.setattr("app.ai.gateway.settings.openai.api_key", "sk-test")
    monkeypatch.setattr("app.ai.gateway._call_openai_resources", boom)
    assert review_resources({"server": "x"}) == {}


def test_resource_server_register_edit_delete():
    with TestClient(app) as client:
        created = client.post(
            "/servers/resources/new",
            data={
                "name": "ssh-01",
                "collector_type": "ssh",
                "host": "10.0.0.21",
                "port": "22",
                "username": "guardian",
                "auth_type": "password",
                "password": "s3cret",
                "instances": ["was", "mq", "was"],
                "plugins": "resource_basic",
                "note": "야간 재기동 금지",
            },
            follow_redirects=True,
        )
        assert created.status_code == 200
        assert "ssh-01" in created.text
        assert "guardian@10.0.0.21:22" in created.text
        # 비밀번호는 화면에 다시 나오지 않는다
        assert "s3cret" not in created.text

        with SessionLocal() as db:
            server = db.query(Server).filter(Server.name == "ssh-01").one()
            server_id = server.id
            assert server.collect_resources is True
            assert server.collect_logs is False
            assert server.password_enc and server.password_enc != "s3cret"
            assert decrypt(server.password_enc) == "s3cret"
            assert json.loads(server.instances) == ["was", "mq"]
            assert plugin_for_server(server).name == "resource_basic"

        page = client.get(f"/servers/resources/{server_id}/edit")
        assert page.status_code == 200
        assert "접속 확인" in page.text
        assert "야간 재기동 금지" in page.text

        saved = client.post(
            f"/servers/resources/{server_id}/edit",
            data={
                "host": "10.0.0.22",
                "port": "2222",
                "username": "guardian",
                "collector_type": "ssh",
                "auth_type": "password",
                "password": "",
                "collect_resources": "1",
                "instances": ["was"],
                "plugins": "resource_basic",
                "note": "수정함",
            },
            follow_redirects=True,
        )
        assert saved.status_code == 200
        with SessionLocal() as db:
            server = db.get(Server, server_id)
            assert server.host == "10.0.0.22"
            assert server.port == 2222
            # 빈 칸으로 저장하면 예전 비밀번호를 지우지 않는다
            assert decrypt(server.password_enc) == "s3cret"
            assert json.loads(server.instances) == ["was"]

        # 붙을 수 없는 주소라 수집은 실패하고 사유가 남는다
        failed = client.post(f"/servers/resources/{server_id}/collect")
        assert failed.status_code == 400
        assert "수집 실패" in failed.text
        with SessionLocal() as db:
            assert db.get(Server, server_id).last_resource_error

        removed = client.post(f"/servers/resources/{server_id}/delete", follow_redirects=True)
        assert removed.status_code == 200
        with SessionLocal() as db:
            assert db.query(Server).filter(Server.name == "ssh-01").one_or_none() is None


def test_resource_plugin_menu():
    with TestClient(app) as client:
        page = client.get("/plugins")
        assert page.status_code == 200
        assert "리소스 수집" in page.text
        assert "resource_basic" in page.text

        form = client.get("/plugins/new?stage=4")
        assert form.status_code == 200
        assert "수집 스크립트" in form.text

        made = client.post(
            "/plugins/new",
            data={
                "stage": "4",
                "name": "eai_resource",
                "description": "EAI 전용 수집",
                "all_servers": "1",
                "script": 'echo \'{"cpu": {"usage_pct": 1}}\'',
            },
            follow_redirects=True,
        )
        assert made.status_code == 200
        assert "eai_resource" in made.text
        try:
            edit = client.get("/plugins/4/eai_resource")
            assert edit.status_code == 200
            assert "usage_pct" in edit.text
        finally:
            plugin_editor.delete_plugin(4, "eai_resource")


def test_resource_upload_and_weekly_report(monkeypatch):
    monkeypatch.setattr("app.resources.today_stamp", lambda when=None: "2026-09-01")
    with TestClient(app) as client:
        nav = client.get("/servers", follow_redirects=True)
        assert nav.status_code == 200
        assert "리소스 수집 대상 서버" in nav.text
        assert "로그 수집 대상 서버" in nav.text
        assert "리소스 분석 보고서" in nav.text

        page = client.get("/servers/resources")
        assert page.status_code == 200
        assert "자료 넣기" in page.text
        assert "샘플 7일 넣기" in page.text
        assert "resourceUploadModal" in page.text
        assert "인증 방식" in page.text

        end = datetime(2026, 9, 1)
        for offset in range(7):
            day = (end - timedelta(days=offset)).strftime("%Y-%m-%d")
            payload = {
                "server": "demo-local",
                "date": day,
                "cpu": {"usage_pct": 20 + offset},
                "mem": {"used_pct": 50 + offset},
                "disk": [{"mount": "/", "used_pct": 60 + offset}],
                "instances": [{"name": "was", "ok": offset != 1}],
            }
            posted = client.post(
                "/servers/resources",
                data={"payload": json.dumps(payload)},
                follow_redirects=True,
            )
            assert posted.status_code == 200
            assert "넣었습니다" in posted.text

        listed = client.get("/servers/resources")
        assert "demo-local" in listed.text

        analysis = analyze_server("demo-local", days=7, end="2026-09-01")
        assert analysis["count"] == 7
        assert analysis["cpu"]["direction"] == "하락"
        assert "was" in analysis["instance_fail"]

        reports = client.get("/reports/resources")
        assert reports.status_code == 200
        generated = client.post(
            "/reports/resources/generate",
            data={"selecting": "1", "servers": "demo-local"},
            follow_redirects=True,
        )
        assert generated.status_code == 200
        assert "resource_report:demo-local" in generated.text
        assert "리소스 추이" in generated.text

        log_reports = client.get("/reports")
        assert "resource_report:demo-local" not in log_reports.text


def test_sample_script_and_seeded_weekly_report():
    with TestClient(app) as client:
        script = client.get("/servers/resources/sample.sh")
        assert script.status_code == 200
        body = script.content.decode("utf-8")
        assert "SERVER_NAME" in body
        assert "instances" in body
        page = client.get("/servers/resources")
        assert "샘플 7일 넣기" in page.text
        assert "sample_resource.sh" in page.text
        seeded = client.post("/servers/resources/sample", follow_redirects=True)
        assert seeded.status_code == 200
        assert "demo-web" in seeded.text
        assert "demo-db" in seeded.text
        generated = client.post(
            "/reports/resources/generate",
            data={"selecting": "1", "servers": "demo-web"},
            follow_redirects=True,
        )
        assert generated.status_code == 200
        assert "resource_report:demo-web" in generated.text
