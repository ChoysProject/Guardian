from datetime import datetime

from app.demo_logs import CATALOG, write_demo_logs, write_healthy_dated_logs
from app.pipeline.normalize import parse_text
from app.plugins.runtime import run_stage1


def test_write_demo_logs_hits_every_catalog_plugin(tmp_path):
    write_demo_logs(tmp_path, when=datetime(2026, 9, 16, 15, 30, 0))
    text = (tmp_path / "all-plugins.log").read_text(encoding="utf-8")
    events = parse_text(text, default_host="demo")
    findings = run_stage1("demo", "demo", events, selected=list(CATALOG))
    plugins = {item["plugin"] for item in findings}
    for name in CATALOG:
        assert f"stage1.{name}" in plugins, name
    assert "stage1.auth_failures" in plugins
    assert "stage1.disk_full" in plugins
    assert (tmp_path / "catalog" / "java.log").exists()
    assert (tmp_path / "demo.log").exists()
    assert "2026-09-16" in text
    catalog = (tmp_path / "catalog" / "springboot.log").read_text(encoding="utf-8")
    assert "Started DemoApplication" in catalog
    assert "APPLICATION FAILED TO START" in catalog


def test_healthy_sample_logs_do_not_raise_error_findings(tmp_path):
    write_demo_logs(tmp_path, when=datetime(2026, 9, 16, 15, 30, 0))
    text = (tmp_path / "healthy.log").read_text(encoding="utf-8")
    events = parse_text(text, default_host="healthy")
    findings = run_stage1("healthy", "healthy", events, selected=list(CATALOG))
    bad = [item for item in findings if item.get("severity") in {"error", "warn"}]
    assert bad == []
    spring = (tmp_path / "healthy" / "springboot.log").read_text(encoding="utf-8")
    spring_events = parse_text(spring, default_host="spring-ok-01")
    spring_findings = run_stage1("spring-ok-01", "10.20.0.61", spring_events, selected=["springboot"])
    assert not [item for item in spring_findings if item.get("severity") in {"error", "warn"}]
    assert "Started DemoApplication" in spring
    assert "APPLICATION FAILED TO START" not in spring


def test_healthy_dated_logs_have_volume_without_errors(tmp_path):
    written = write_healthy_dated_logs(tmp_path, days=2, when=datetime(2026, 9, 20, 11, 0, 0))
    assert written
    spring = tmp_path / "springboot" / "2026-09-20.log"
    assert spring.exists()
    text = spring.read_text(encoding="utf-8")
    assert text.count("INFO") >= 20
    events = parse_text(text, default_host="spring-ok-01")
    findings = run_stage1("spring-ok-01", "10.20.0.61", events, selected=["springboot"])
    assert not [item for item in findings if item.get("severity") in {"error", "warn"}]
    assert any(item.get("severity") == "info" and item.get("count", 0) >= 20 for item in findings)
