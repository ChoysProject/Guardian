from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.metrics import record_events, reset_metrics, server_day_counts, timeline_from_hourly, wall_now
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
    assert "AI 총평" not in result["html"]
    assert "table-layout: fixed" in result["html"]
    assert 'class="kpis"' in result["html"]
    assert "<th>AI</th>" not in result["html"]


def test_default_log_report_title_is_guardian():
    ctx = PluginContext(
        server_name="app-1",
        host="app-1",
        events=[],
        config={"stats": {"lines": 3, "error": 0, "warn": 0}},
        period_start=datetime(2026, 9, 14, 0, 0, 0),
        period_end=datetime(2026, 9, 15, 0, 0, 0),
        findings=[],
    )
    result = render_standard_report(ctx)
    assert "Guardian 로그 분석 보고서" in result["title"]
    assert "Goodmorning" not in result["title"]
    assert "Goodmorning" not in result["html"]


def test_log_report_includes_ai_review():
    ctx = PluginContext(
        server_name="app-1",
        host="app-1",
        events=[],
        config={
            "mode": "per_server",
            "server_name": "app-1",
            "title": "app-1 일일 보고서",
            "stats": {"lines": 10, "error": 2, "warn": 0},
            "ai": {
                "summary": "ERROR 2건이 있어 기동 로그를 먼저 봐야 합니다.",
                "risks": ["부팅 실패 반복"],
                "actions": ["오늘 기동 로그를 확인"],
            },
        },
        period_start=datetime(2026, 9, 14, 0, 0, 0),
        period_end=datetime(2026, 9, 15, 0, 0, 0),
        findings=[{"severity": "error", "signature": "spring.boot_failed", "count": 2, "plugin": "stage1.springboot", "host": "app-1"}],
    )
    result = render_standard_report(ctx)
    assert "## AI 총평" in result["markdown"]
    assert "기동 로그를 먼저 봐야" in result["html"]
    assert "해볼 조치" in result["html"]
    assert "spring.boot_failed" in result["html"]
    assert "<th>AI</th>" not in result["html"]


def test_report_keeps_today_bucket_and_shows_volume():
    reset_metrics()
    day = wall_now().strftime("%Y-%m-%d")
    events = parse_text(
        f"{day} 10:00:00 INFO started\n"
        f"{day} 10:00:01 ERROR boom 1\n"
        f"{day} 10:00:02 WARN slow\n",
        default_host="demo-local",
    )
    record_events(events, server="demo-local", files=1)
    counts = server_day_counts("demo-local", day)
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


def test_log_card_shows_missing_log_files():
    server = Server(
        name="EAI_LOG",
        last_collect_at=datetime.utcnow(),
        last_error="로그 파일을 찾지 못했습니다: ~/DailyData/logs/springboot*",
    )
    from app.pipeline.reports import _log_card_metrics

    metrics = _log_card_metrics(server, [])
    assert metrics["status"] == "수집 문제"
    assert "찾지 못" in metrics["verdict"]
    assert "springboot" in metrics["problem_text"]


def test_log_card_metrics_ok_shows_info_traffic():
    server = Server(name="pg-ok-01", last_collect_at=datetime.utcnow())
    findings = [
        Finding(severity="info", count=84, signature="checkpoint complete"),
        Finding(severity="debug", count=40, signature="connection authorized"),
    ]
    from app.pipeline.reports import _log_card_metrics

    metrics = _log_card_metrics(server, findings)
    assert metrics["status"] == "여유"
    assert metrics["level"] == "ok"
    assert "정상 로그 124건" in metrics["verdict"]
    assert "정상 트래픽 124건" in metrics["problem_text"]
    labels = {cell["label"]: cell["value"] for cell in metrics["cells"]}
    assert labels["ERROR"] == "0"
    assert labels["WARN"] == "0"
    assert labels["INFO"] == "124"


def test_cursor_files_ignore_leftover_names():
    from app.cursors import load_all, save_all
    from app.pipeline.reports import _cursor_files

    previous = load_all()
    try:
        save_all(
            [
                {"server_id": 2, "server_name": "demo-web", "log_path": "/old.log"},
                {"server_id": 2, "server_name": "EAI_LOG", "log_path": "/home/choys/app.log"},
            ]
        )
        assert _cursor_files(Server(id=2, name="EAI_LOG")) == 1
        assert _cursor_files(Server(id=2, name="demo-web")) == 1
        assert _cursor_files(Server(id=2, name="other")) == 0
    finally:
        save_all(previous)


def test_hourly_timeline_includes_recent_info():
    reset_metrics()
    stamp = wall_now().strftime("%Y-%m-%d %H:%M:%S")
    events = parse_text(f"{stamp} INFO started\n{stamp} INFO health ok\n", default_host="EAI_LOG")
    record_events(events, server="EAI_LOG", files=1)
    data = timeline_from_hourly("hour")
    assert sum(data["info"]) == 2
    assert sum(data["error"]) == 0

