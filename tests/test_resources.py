import io
import json
import re
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.gateway import _parse_review, review_resources
from app.main import app
from app.models import Report, SessionLocal, Server
from app.plugins import editor as plugin_editor
from app.resource_collect import plugin_for_server
from app.secrets_store import decrypt
from app.resource_script import build_script
from app.resources import (
    analyze_server,
    import_snapshots_from_path,
    parse_payload,
    render_resource_report,
    resource_payload,
    save_snapshot,
    snapshot_server_names,
    write_sample_snapshots,
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


def test_parse_instance_start_and_problem():
    rows = parse_payload(
        json.dumps(
            {
                "server": "eai-01",
                "date": "2026-09-08",
                "cpu": {"usage_pct": 1},
                "mem": {"used_pct": 2},
                "disk": [],
                "instances": [
                    {
                        "name": "was",
                        "ok": True,
                        "started_at": "2026-09-08 09:00:00",
                        "uptime_sec": 3600,
                        "restarts": 1,
                        "problem": "",
                    },
                    {"name": "mq", "ok": False, "problem": "failed"},
                ],
                "extra": {
                    "net_connections": {
                        "established": 12,
                        "time_wait": 3,
                        "close_wait": 0,
                        "peers": [{"state": "ESTAB", "local": "10.0.0.1:8080", "remote": "10.0.0.5:443", "count": 2}],
                    }
                },
            }
        )
    )
    by_name = {item["name"]: item for item in rows[0]["instances"]}
    assert by_name["was"]["started_at"] == "2026-09-08 09:00:00"
    assert by_name["was"]["uptime_sec"] == 3600
    assert by_name["mq"]["problem"] == "failed"
    assert rows[0]["extra"]["net_connections"]["time_wait"] == 3
    assert rows[0]["extra"]["net_connections"]["peers"][0]["remote"] == "10.0.0.5:443"


def test_parse_payload_repairs_empty_json_values():
    rows = parse_payload(
        '{"server":"eai-01","date":"2026-09-07","cpu":{"usage_pct":1},"mem":{"used_pct":2},"disk":[],'
        '"extra":{"sec_failed_login":{"count": },"ok":{"hits": 3}}}'
    )
    extra = rows[0]["extra"]
    assert extra["sec_failed_login"]["count"] is None
    assert extra["ok"]["hits"] == 3


def test_parse_payload_repairs_df_dash_inode():
    rows = parse_payload(
        '{"server":"wsl-01","date":"2026-09-08","cpu":{"usage_pct":1},"mem":{"used_pct":2},"disk":[],'
        '"extra":{"disk_inode":[{"mount":"/mnt/c","inode_pct": -},{"mount":"/","inode_pct":4}]}}'
    )
    inodes = rows[0]["extra"]["disk_inode"]
    assert inodes[0]["inode_pct"] is None
    assert inodes[1]["inode_pct"] == 4


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
    assert "class='ai-review'" in report["html"] or 'class="ai-review"' in report["html"]


def test_ai_summary_markdown_becomes_html_blocks():
    rows = parse_payload(
        json.dumps(
            {
                "server": "ai-fmt-01",
                "date": "2026-09-08",
                "cpu": {"usage_pct": 0.8},
                "mem": {"used_pct": 30.4},
                "disk": [{"mount": "/", "used_pct": 34, "total_gb": 71, "free_gb": 47}],
            }
        )
    )
    save_snapshot(rows[0])
    analysis = analyze_server("ai-fmt-01", days=1, end="2026-09-08")
    report = render_resource_report(
        analysis,
        start="2026-09-08",
        end="2026-09-08",
        ai={
            "summary": "Certainly. ### CPU 사용률 **0.8%** ### 메모리 **30.4%**",
        },
    )
    assert "<h4>" in report["html"]
    assert "<strong>0.8%</strong>" in report["html"]
    assert "###" not in report["html"]
    assert "Certainly" not in report["html"]


def test_resource_report_includes_json_extras():
    extra = {
        "cpu_usage": {"usage_pct": 12},
        "cpu_load": {"load1": 0.4, "load5": 0.5, "load15": 0.6},
        "disk_inode": [{"mount": "/", "inode_pct": 41}],
        "sec_failed_login": {"count": 12},
        "os_info": {"distro": "Ubuntu 20.04.6 LTS", "kernel": "5.15"},
        "mem_oom": {"hits": 2},
        "os_ntp_sync": {"ntp_synchronized": False},
    }
    rows = parse_payload(
        json.dumps(
            {
                "server": "extra-01",
                "date": "2026-09-07",
                "cpu": {"usage_pct": 88, "load1": 0.4, "cores": 8},
                "mem": {"used_pct": 40},
                "disk": [{"mount": "/", "used_pct": 91, "free_gb": 3, "total_gb": 40}],
                "extra": extra,
            }
        )
    )
    save_snapshot(rows[0])
    analysis = analyze_server("extra-01", days=1, end="2026-09-07")
    titles = {row["title"] for row in analysis["extras"]}
    assert "Load Average" in titles
    assert "로그인 실패 이력" in titles
    assert "OOM Killer 이력" in titles
    assert "CPU 사용률" not in titles
    report = render_resource_report(analysis, start="2026-09-07", end="2026-09-07")
    assert "Load Average" in report["markdown"]
    assert "inode" in report["markdown"]
    assert "로그인 실패" in report["markdown"]
    assert "Ubuntu 20.04.6 LTS" in report["markdown"]
    assert "OOM" in report["markdown"]
    assert "class=\"kpis\"" in report["html"]
    assert "danger" in report["html"]


def test_report_hides_noise_mounts_and_reads_like_a_status_page():
    rows = parse_payload(
        json.dumps(
            {
                "server": "wsl-01",
                "date": "2026-09-08",
                "cpu": {"usage_pct": 4.2, "cores": 16},
                "mem": {"used_pct": 18.0},
                "disk": [
                    {"mount": "/", "used_pct": 42, "total_gb": 250, "free_gb": 145},
                    {"mount": "/snap/core22/1", "used_pct": 100, "total_gb": 0.1, "free_gb": 0},
                    {"mount": "/mnt/wslg", "used_pct": 99, "total_gb": 0.4, "free_gb": 0},
                    {"mount": "/run", "used_pct": 1, "total_gb": 1.6, "free_gb": 1.5},
                ],
                "instances": [{"name": "nginx", "ok": True, "cpu_pct": 0.4}],
                "extra": {"disk_inode": [
                    {"mount": "/", "inode_pct": 12},
                    {"mount": "/snap/core22/1", "inode_pct": 99},
                ]},
            }
        )
    )
    save_snapshot(rows[0])
    analysis = analyze_server("wsl-01", days=1, end="2026-09-08")
    mounts = [disk["mount"] for disk in analysis["disks"]]
    assert mounts == ["/"]
    report = render_resource_report(analysis, start="2026-09-08", end="2026-09-08")
    assert "지금은 여유 있습니다" in report["html"]
    assert "시스템 디스크" in report["html"]
    assert "/snap" not in report["html"]
    assert "/mnt/wslg" not in report["html"]
    assert "nginx" in report["html"]
    assert "16코어" in report["html"]
    assert "/snap" not in report["markdown"]


def test_report_shows_swap_like_top_memory():
    rows = parse_payload(
        json.dumps(
            {
                "server": "mem-01",
                "date": "2026-09-08",
                "cpu": {"usage_pct": 5},
                "mem": {"used_pct": 40, "used_mb": 3200, "total_mb": 8000},
                "disk": [{"mount": "/", "used_pct": 20, "total_gb": 50, "free_gb": 40}],
                "instances": [{"name": "was", "ok": True}],
                "extra": {"mem_swap": {"used_pct": 12, "used_mb": 240, "total_mb": 2000}, "mem_oom": {"hits": 1}},
            }
        )
    )
    assert rows[0]["mem"]["swap_used_pct"] == 12.0
    save_snapshot(rows[0])
    analysis = analyze_server("mem-01", days=1, end="2026-09-08")
    assert analysis["mem"]["swap_last"] == 12.0
    report = render_resource_report(analysis, start="2026-09-08", end="2026-09-08")
    assert "스왑" in report["html"]
    assert "240MB" in report["html"] or "240" in report["html"]
    assert "OOM" in report["html"]
    assert "인스턴스" in report["html"]


def test_ai_review_disabled_and_parsing():
    assert review_resources({"server": "x"}) == {}
    parsed = _parse_review('```json\n{"summary": "요약", "risks": ["a", "b"], "actions": []}\n```')
    assert parsed["summary"] == "요약"
    assert parsed["risks"] == ["a", "b"]
    assert parsed["actions"] == []
    assert _parse_review("그냥 문장")["summary"] == "그냥 문장"
    markdown = _parse_review("Certainly. ### CPU 사용률 **75%** ### 메모리 **82%**")
    assert "### CPU" in markdown["summary"]
    assert "\n" in markdown["summary"]
    assert not markdown["summary"].lower().startswith("certainly")


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
            assert plugin_for_server(server).name == "resource_basic"

        page = client.get(f"/servers/resources/{server_id}/edit")
        assert page.status_code == 200
        assert "접속 확인" in page.text
        assert "야간 재기동 금지" in page.text

        # "하는 일" 체크박스는 없앴다 — 리소스 대상 서버는 늘 리소스만 본다.
        assert "하는 일" not in page.text
        assert "수집 경로" in page.text
        assert "인스턴스 추가" not in page.text

        saved = client.post(
            f"/servers/resources/{server_id}/edit",
            data={
                "host": "10.0.0.22",
                "port": "2222",
                "username": "guardian",
                "collector_type": "ssh",
                "auth_type": "password",
                "password": "",
                "plugins": "resource_basic",
                "note": "수정함",
                "collect_path": "",
            },
            follow_redirects=True,
        )
        assert saved.status_code == 200
        with SessionLocal() as db:
            server = db.get(Server, server_id)
            assert server.host == "10.0.0.22"
            assert server.port == 2222
            assert server.collect_resources is True
            # 빈 칸으로 저장하면 예전 비밀번호를 지우지 않는다
            assert decrypt(server.password_enc) == "s3cret"

        # 붙을 수 없는 주소라 수집은 실패하고 사유가 남는다
        failed = client.post(f"/servers/resources/{server_id}/collect", follow_redirects=True)
        assert failed.status_code == 200
        assert "수집 실패" in failed.text
        assert 'id="guardian-flash"' in failed.text
        assert "alert-danger" not in failed.text
        assert 'id="server-add"' in failed.text
        assert 'id="server-add" class="collapse show"' not in failed.text
        with SessionLocal() as db:
            assert db.get(Server, server_id).last_resource_error

        # 목록에는 더 이상 오류를 보여 주지 않고, 수정 화면에만 나온다
        listed = client.get("/servers/resources")
        assert "마지막 수집 오류" not in listed.text
        edited = client.get(f"/servers/resources/{server_id}/edit")
        assert "마지막 수집 오류" in edited.text
        assert "오류 지우기" in edited.text
        assert "js-copy" in edited.text

        # 남은 오류는 버튼으로 지운다 (back 필드 없이도 수정 화면으로 돌아간다)
        cleared = client.post(f"/servers/resources/{server_id}/clear-error", follow_redirects=True)
        assert cleared.status_code == 200
        assert f"/servers/resources/{server_id}/edit" in str(cleared.url)
        with SessionLocal() as db:
            assert db.get(Server, server_id).last_resource_error == ""

        removed = client.post(f"/servers/resources/{server_id}/delete", follow_redirects=True)
        assert removed.status_code == 200
        with SessionLocal() as db:
            assert db.query(Server).filter(Server.name == "ssh-01").one_or_none() is None


def test_resource_plugin_menu():
    with TestClient(app) as client:
        page = client.get("/plugins", follow_redirects=True)
        assert page.status_code == 200
        assert "리소스 및 성능 쉘 스크립트" in page.text
        assert "resource_basic" in page.text
        assert "plugin-add" in page.text
        assert "cpu_usage" in page.text
        assert "mem_usage" in page.text
        assert "인스턴스 검색" in page.text
        assert "placeholder=\"프로세스 이름\"" in page.text
        assert "qry-api" not in page.text
        assert "금지 명령어" not in page.text
        assert "모든 서버" not in page.text
        empty = client.get("/plugins/resource-plugins")
        assert empty.status_code == 200
        assert "아직 비어 있습니다" in empty.text

        form = client.get("/plugins/new?stage=4")
        assert form.status_code == 200
        assert "수집 스크립트" in form.text

        made = client.post(
            "/plugins/new",
            data={
                "stage": "4",
                "name": "tmp_eai_resource",
                "description": "EAI 전용 수집",
                "all_servers": "1",
                "script": 'echo \'{"cpu": {"usage_pct": 1}}\'',
            },
            follow_redirects=True,
        )
        assert made.status_code == 200
        assert "tmp_eai_resource" in made.text
        try:
            edit = client.get("/plugins/4/tmp_eai_resource")
            assert edit.status_code == 200
            assert "usage_pct" in edit.text
        finally:
            plugin_editor.delete_plugin(4, "tmp_eai_resource")


def test_resource_upload_and_weekly_report(monkeypatch):
    monkeypatch.setattr("app.resources.today_stamp", lambda when=None: "2026-09-01")
    with TestClient(app) as client:
        nav = client.get("/servers", follow_redirects=True)
        assert nav.status_code == 200
        assert "리소스 및 성능 수집 대상 서버" in nav.text
        assert "로그 수집 대상 서버" in nav.text
        assert "리소스 및 성능 보고서" in nav.text
        assert "로그 분석 플러그인" in nav.text

        page = client.get("/servers/resources")
        assert page.status_code == 200
        assert "데이터 넣기" in page.text
        assert "서버 등록하기" in page.text
        assert "server-search" in page.text
        assert "JSON 형식" not in page.text
        assert "JSON 붙여넣기" not in page.text
        assert "upload-file-list" in page.text
        assert "resourceUploadModal" in page.text
        assert "snapshotViewModal" in page.text
        assert "인스턴스 추가" not in page.text
        assert "instancesModal" not in page.text
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
            assert '"saved": 1' in posted.text

        listed = client.get("/servers/resources")
        assert "demo-local" in listed.text

        analysis = analyze_server("demo-local", days=7, end="2026-09-01")
        assert analysis["count"] == 7
        assert analysis["cpu"]["direction"] == "하락"
        assert "was" in analysis["instance_fail"]

        reports = client.get("/reports/resources")
        assert reports.status_code == 200
        assert 'id="reportFidget"' in reports.text
        assert "js-report-generate" in reports.text
        assert "guardian-report-fidget.js" in reports.text
        generated = client.post(
            "/reports/resources/generate",
            data={"selecting": "1", "servers": "demo-local"},
            follow_redirects=True,
        )
        assert generated.status_code == 200
        assert "demo-local" in generated.text
        assert "리소스 추이" in generated.text
        assert "report-summary" in generated.text
        assert "report-actions" in generated.text
        assert "server-report-grid" in generated.text
        assert "resourceReportModal" in generated.text
        assert "resourceReportList" in generated.text
        assert "resourceReportExport" in generated.text
        assert "이미지 복사" in generated.text
        assert "이미지 저장" in generated.text
        assert "MD 복사" in generated.text
        assert "MD 저장" in generated.text
        assert "resourceDeleteModal" in generated.text
        assert "js-report-delete" in generated.text
        assert "guardian-ui.js" in generated.text
        assert "data-reports=" in generated.text
        assert "CPU" in generated.text
        assert "다시 만들기" in generated.text
        assert "추이 보고서 생성" not in generated.text
        with SessionLocal() as db:
            stored = db.query(Report).filter(Report.plugin == "resource_report:demo-local").first()
        assert stored is not None
        embedded = client.get(f"/reports/{stored.id}/embed")
        assert embedded.status_code == 200
        assert "demo-local 상태" in embedded.text or "CPU" in embedded.text
        markdown = client.get(f"/reports/{stored.id}/markdown")
        assert markdown.status_code == 200
        assert "text/markdown" in markdown.headers.get("content-type", "")
        assert "디스크" in markdown.text
        assert "attachment" in markdown.headers.get("content-disposition", "")

        removed = client.post(
            "/reports/delete",
            data={"report_ids": stored.id},
            follow_redirects=False,
        )
        assert removed.status_code == 303
        assert "toast=deleted" in removed.headers.get("location", "")
        with SessionLocal() as db:
            assert db.get(Report, stored.id) is None

        log_reports = client.get("/reports")
        assert "resource_report:demo-local" not in log_reports.text


def test_server_script_edit_and_download():
    plugin_editor.create_resource_plugin(
        "script_test",
        description="스크립트 손보기 확인",
        targets=["script-01"],
        script="echo hello",
    )
    try:
        with TestClient(app) as client:
            client.post(
                "/servers/resources/new",
                data={
                    "name": "script-01",
                    "collector_type": "ssh",
                    "host": "10.0.0.31",
                    "username": "guardian",
                    "auth_type": "agent",
                    "plugins": "script_test",
                },
                follow_redirects=True,
            )
            with SessionLocal() as db:
                server_id = db.query(Server).filter(Server.name == "script-01").one().id

            page = client.get(f"/servers/resources/{server_id}/edit")
            assert page.status_code == 200
            assert "스크립트 저장" not in page.text
            assert "스크립트에서 고치기" in page.text
            assert "스크립트 받기" not in page.text
            assert "모든 서버" not in page.text

            listing = client.get("/plugins/resources")
            assert listing.status_code == 200
            assert "스크립트 받기" in listing.text
            assert "module-help" in listing.text
            assert "지금 CPU가 얼마나 바쁜지" in listing.text

            plugin_page = client.get("/plugins/4/script_test")
            assert plugin_page.status_code == 200
            assert "스크립트 받기" in plugin_page.text

            saved = client.post(
                "/plugins/4/script_test",
                data={
                    "description": "스크립트 손보기 확인",
                    "script": "echo '{{server}} 에서 수집'",
                },
                follow_redirects=True,
            )
            assert saved.status_code == 200
            assert plugin_editor.read_script(4, "script_test").startswith("#!/bin/bash")

            # 다운로드는 스크립트이름/collect.sh zip 이고, 서버 값이 채워진다
            packed = client.get(f"/servers/resources/{server_id}/script.sh")
            assert packed.status_code == 200
            assert packed.headers["content-type"].startswith("application/zip")
            with zipfile.ZipFile(io.BytesIO(packed.content)) as zf:
                names = zf.namelist()
                assert "script_test/collect.sh" in names
                assert "script_test/DailyData/.keep" in names
                body = zf.read("script_test/collect.sh").decode("utf-8")
            assert "script-01 에서 수집" in body
            assert "{{server}}" not in body

            plugin_zip = client.get("/plugins/4/script_test/script.zip")
            assert plugin_zip.status_code == 200
            with zipfile.ZipFile(io.BytesIO(plugin_zip.content)) as zf:
                assert "script_test/collect.sh" in zf.namelist()
                assert "script_test/DailyData/.keep" in zf.namelist()

            client.post(f"/servers/resources/{server_id}/delete", follow_redirects=True)
    finally:
        plugin_editor.delete_plugin(4, "script_test")


def test_import_snapshots_from_path():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / "2026-08-01.json").write_text(
            json.dumps({"date": "2026-08-01", "cpu": {"usage_pct": 11}}), encoding="utf-8"
        )
        (folder / "2026-08-02.json").write_text(
            json.dumps({"date": "2026-08-02", "cpu": {"usage_pct": 12}}), encoding="utf-8"
        )
        (folder / "broken.json").write_text("이건 json이 아님", encoding="utf-8")

        saved, errors = import_snapshots_from_path("path-01", str(folder))
        assert saved == 2
        assert len(errors) == 1
        assert "broken.json" in errors[0]

        daily = folder / "DailyData"
        daily.mkdir()
        (daily / "2026-08-03.json").write_text(
            json.dumps({"date": "2026-08-03", "cpu": {"usage_pct": 13}}), encoding="utf-8"
        )
        saved_daily, _ = import_snapshots_from_path("path-01", str(folder))
        assert saved_daily == 3

    with pytest.raises(ValueError):
        import_snapshots_from_path("path-01", str(folder / "missing"))


def test_resource_server_collect_path_reload():
    with TestClient(app) as client:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "2026-08-10.json").write_text(
                json.dumps({"date": "2026-08-10", "cpu": {"usage_pct": 33}}), encoding="utf-8"
            )
            client.post(
                "/servers/resources/new",
                data={
                    "name": "path-srv",
                    "collector_type": "local",
                    "auth_type": "agent",
                    "collect_path": str(folder),
                },
                follow_redirects=True,
            )
            with SessionLocal() as db:
                server_id = db.query(Server).filter(Server.name == "path-srv").one().id

            page = client.get(f"/servers/resources/{server_id}/edit")
            assert "수집 경로에서 다시 가져오기" in page.text

            reloaded = client.post(
                f"/servers/resources/{server_id}/reload-path",
                headers={"referer": f"http://testserver/servers/resources/{server_id}/edit"},
                follow_redirects=True,
            )
            assert reloaded.status_code == 200
            assert "1건을 다시 가져왔습니다" in reloaded.text
            assert "2026-08-10" in reloaded.text

            with SessionLocal() as db:
                server = db.get(Server, server_id)
                assert server.last_resource_error == ""

            client.post(f"/servers/resources/{server_id}/delete", follow_redirects=True)


def test_resource_server_list_has_no_instances():
    with TestClient(app) as client:
        page = client.get("/servers/resources")
        assert page.status_code == 200
        assert "인스턴스 추가" not in page.text
        assert "instancesModal" not in page.text
        assert ">인스턴스<" not in page.text
        assert "화면에서 구분할 이름" in page.text
        assert "접속할 IP 또는 호스트명" in page.text
        assert "eai-01" not in page.text


def test_script_writes_json_under_plugin_folder():
    script, _ = build_script(["cpu_usage", "mem_usage", "disk_usage"], plugin_name="local_collect")
    assert "set +e" in script
    assert "pipefail" not in script
    assert "set -e" not in script
    assert "run_check" in script
    assert "mktemp" not in script
    assert "chmod" not in script
    assert "chown" not in script
    assert "RESULT_BUF" in script
    assert "printf '%s' \"$RESULT_BUF\"" in script
    assert 'PLUGIN_NAME="local_collect"' in script
    assert 'OUT_DIR="__GUARDIAN_COLLECT_PATH__"' in script
    assert 'mkdir -p "$OUT_DIR"' in script
    assert '"$OUT_DIR/${DATE}.json"' in script
    assert 'OUT_DIR="$SCRIPT_DIR/DailyData"' in script
    assert "JSON 한 줄은 무조건 찍는다" in script or "무조건" in script
    assert "check_cpu_usage" in script
    assert "hostname -s" in script
    assert "json.dumps" in script
    assert "python3" in script
    assert "json_join" in script
    assert "{{server}}" in script
    assert "BASH_VERSION" in script
    assert "export LC_ALL=C" in script
    assert "sed -i" in script


def test_build_script_from_modules_and_instances():
    script, skipped = build_script(["cpu_usage", "mem_usage"], instances=["qry-api"])
    assert "check_cpu_usage" in script
    assert "check_mem_usage" in script
    assert "check_instance_search" in script
    assert "probe_service" in script
    assert "started_at" in script
    script_net, _ = build_script(["net_connections"])
    assert "check_net_connections" in script_net
    assert "time_wait" in script_net
    assert "peers" in script_net
    assert "SEARCH_NAMES=\"qry-api\"" in script
    assert '[ "$SEARCH_NAMES" = "{{searches}}" ]' in script
    assert '[ "$SEARCH_NAMES" = "qry-api" ]' not in script
    assert "find_proc_pid" in script
    assert "pgrep -x --" in script
    assert "grep -F -- \"$name\"" not in script
    assert "HEADER" in script or "have_cmd()" in script
    assert "add_result" in script
    with TestClient(app) as client:
        preview = client.get(
            "/plugins/resources/preview",
            params=[("modules", "cpu_load"), ("modules", "disk_usage"), ("instances", "qry-api")],
        )
        assert preview.status_code == 200
        body = preview.json()["script"]
        assert "check_cpu_load" in body
        assert "check_disk_usage" in body
        assert "check_instance_search" in body
        assert "qry-api" in body
        assert preview.json()["instances"] == ["qry-api"]
        named = client.get(
            "/plugins/resources/preview",
            params=[("modules", "cpu_usage"), ("name", "local_collect")],
        )
        assert named.status_code == 200
        assert 'PLUGIN_NAME="local_collect"' in named.json()["script"]
        packed = client.get(
            "/plugins/resources/preview.zip",
            params=[("modules", "cpu_usage"), ("name", "local_collect")],
        )
        assert packed.status_code == 200
        with zipfile.ZipFile(io.BytesIO(packed.content)) as zf:
            assert "local_collect/collect.sh" in zf.namelist()
            assert "local_collect/DailyData/.keep" in zf.namelist()
            assert 'PLUGIN_NAME="local_collect"' in zf.read("local_collect/collect.sh").decode("utf-8")


def test_create_resource_plugin_from_checked_modules():
    with TestClient(app) as client:
        made = client.post(
            "/plugins/new",
            data={
                "stage": "4",
                "name": "mod_resource",
                "description": "모듈로 만든 수집",
                "modules": ["cpu_usage", "disk_usage"],
                "plugin_instances": ["qry-api"],
            },
            follow_redirects=True,
        )
        assert made.status_code == 200
        assert "mod_resource" in made.text
        try:
            body = plugin_editor.read_script(4, "mod_resource")
            assert "check_cpu_usage" in body
            assert "check_disk_usage" in body
            assert "check_mem_oom" not in body
            assert "check_instance_search" in body
            assert "qry-api" in body
            assert 'PLUGIN_NAME="mod_resource"' in body
            assert 'OUT_DIR="__GUARDIAN_COLLECT_PATH__"' in body
            assert '"$OUT_DIR/${DATE}.json"' in body
        finally:
            plugin_editor.delete_plugin(4, "mod_resource")


def test_download_zip_uses_collect_path():
    script, _ = build_script(["cpu_usage"], plugin_name="path_resource")
    plugin_editor.create_resource_plugin(
        "path_resource",
        description="수집 경로 확인",
        targets=["path-zip"],
        script=script,
        config={"modules": ["cpu_usage"]},
    )
    try:
        with TestClient(app) as client:
            client.post(
                "/servers/resources/new",
                data={
                    "name": "path-zip",
                    "collector_type": "local",
                    "auth_type": "agent",
                    "collect_path": "/tmp/guardian-out",
                    "plugins": "path_resource",
                },
                follow_redirects=True,
            )
            with SessionLocal() as db:
                server_id = db.query(Server).filter(Server.name == "path-zip").one().id
            packed = client.get(f"/servers/resources/{server_id}/script.sh")
            assert packed.status_code == 200
            with zipfile.ZipFile(io.BytesIO(packed.content)) as zf:
                names = zf.namelist()
                assert "path_resource/collect.sh" in names
                assert "path_resource/DailyData/.keep" in names
                body = zf.read("path_resource/collect.sh").decode("utf-8")
            assert 'OUT_DIR="/tmp/guardian-out"' in body
            assert '[ "$OUT_DIR" = "__GUARDIAN_COLLECT_PATH__" ]' in body
            assert '"$OUT_DIR/${DATE}.json"' in body
            client.post(f"/servers/resources/{server_id}/delete", follow_redirects=True)
    finally:
        plugin_editor.delete_plugin(4, "path_resource")


def test_seeded_weekly_report():
    with TestClient(app) as client:
        write_sample_snapshots(days=7, force=True)
        names = snapshot_server_names()
        assert "demo-web" in names
        assert "demo-db" in names
        generated = client.post(
            "/reports/resources/generate",
            data={"selecting": "1", "servers": "demo-web"},
            follow_redirects=True,
        )
        assert generated.status_code == 200
        assert "demo-web" in generated.text
        assert "server-report-card" in generated.text
