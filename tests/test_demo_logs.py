from datetime import datetime

from app.demo_logs import CATALOG, write_demo_logs
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
