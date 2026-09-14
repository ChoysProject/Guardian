from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.metrics import record_events, reset_metrics, server_day_counts, wall_now
from app.models import Finding, Server, SessionLocal
from app.pipeline.normalize import parse_text
from app.pipeline.reports import generate_reports
from app.plugins.report_common import render_standard_report
from app.plugins.types import PluginContext


def test_report_includes_volume_without_findings():
    ctx = PluginContext(
        server_name="app-1",
        host="app-1",
        events=[],
        config={
            "mode": "per_server",
            "server_name": "app-1",
            "title": "app-1 일일 보고서",
            "stats": {
                "lines": 12340,
                "error": 0,
                "warn": 0,
                "info": 12340,
                "files": 2,
                "last_collect": "2026-09-14 18:00",
            },
        },
        period_start=datetime(2026, 9, 14, 0, 0, 0),
        period_end=datetime(2026, 9, 15, 0, 0, 0),
        findings=[],
    )
    result = render_standard_report(ctx)
    assert "처리 로그 12,340줄" in result["summary"]
    assert "오늘 로그 12,340줄을 처리했고" in result["markdown"]
    assert "처리 로그" in result["html"]
    assert "아직 징후가 없습니다" not in result["html"]
    assert "app-1 일일 보고서 · app-1" not in result["title"]


def test_report_keeps_today_bucket_and_shows_volume():
    reset_metrics()
    events = parse_text(
        "2026-09-14 10:00:00 INFO started\n"
        "2026-09-14 10:00:01 ERROR boom 1\n"
        "2026-09-14 10:00:02 WARN slow\n",
        default_host="demo-local",
    )
    record_events(events, server="demo-local", files=1)
    counts = server_day_counts("demo-local", wall_now().strftime("%Y-%m-%d"))
    assert counts["lines"] == 3
    assert counts["error"] == 1
    assert counts["warn"] == 1

    with TestClient(app):
        with SessionLocal() as db:
            demo = db.query(Server).filter(Server.name == "demo-local").one()
            old = datetime.utcnow() - timedelta(days=2)
            db.add(
                Finding(
                    server_id=demo.id,
                    occurred_at=old,
                    host="demo-local",
                    severity="error",
                    signature="stale.yesterday",
                    sample_lines="[]",
                    count=4,
                    plugin="stage1.common",
                    bucket="2026-09-12",
                    created_at=old,
                    updated_at=old,
                )
            )
            db.add(
                Finding(
                    server_id=demo.id,
                    occurred_at=datetime.utcnow(),
                    host="demo-local",
                    severity="error",
                    signature="today.boom",
                    sample_lines='["ERROR boom"]',
                    count=2,
                    plugin="stage1.common",
                    bucket=wall_now().strftime("%Y-%m-%d"),
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=20),
                    updated_at=datetime.utcnow(),
                )
            )
            db.commit()
            reports = generate_reports(db, server_names=["demo-local"])
        assert reports
        body = open(reports[0].html_path, encoding="utf-8").read()
        md = open(reports[0].markdown_path, encoding="utf-8").read()
        assert "today.boom" in body
        assert "stale.yesterday" not in body
        assert "이전 날짜 징후" in md
        assert "처리 로그" in body
        assert "ERROR 줄" in body
