import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.resources import analyze_server, parse_payload


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


def test_resource_upload_and_weekly_report(monkeypatch):
    monkeypatch.setattr("app.resources.today_stamp", lambda when=None: "2026-09-01")
    with TestClient(app) as client:
        nav = client.get("/servers")
        assert nav.status_code == 200
        assert "수집 대상 서버" in nav.text
        assert "서버 리소스 분석" in nav.text
        assert "리소스 분석 보고서" in nav.text

        page = client.get("/servers/resources")
        assert page.status_code == 200
        assert "자료 넣기" in page.text

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
        assert "2026-09-01" in listed.text

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
