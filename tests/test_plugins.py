from app.config import ROOT
from app.pipeline.normalize import parse_text
from app.plugins.loader import load_manifests, targets_match
from app.plugins.runtime import assigned_plugins, run_stage1, run_stage2
from app.plugins.types import PluginManifest


def test_loads_bundled_plugins():
    names = {item.name for item in load_manifests()}
    assert "common" in names
    assert "auth_failures" in names
    assert "disk_full" in names
    assert "eai" in names
    assert "mci" in names
    assert "daily_report" in names
    assert "server_report" in names
    assert "eai_report" in names


def test_auth_and_disk_plugins_on_demo_log():
    text = (ROOT / "sample_logs" / "demo.log").read_text(encoding="utf-8")
    events = parse_text(text, default_host="demo-local")
    findings = run_stage2("demo-local", "demo-local", events)
    plugins = {item["plugin"] for item in findings}
    assert "stage2.auth_failures" in plugins
    assert "stage2.disk_full" in plugins
    assert any(str(item["signature"]).startswith("auth.") for item in findings)
    assert any(item["signature"] == "disk.full" for item in findings)


def test_targets_match_wildcard():
    manifest = PluginManifest(name="x", stage=2, targets=["*"])
    assert targets_match(manifest, "anything")
    manifest.targets = ["db-.*"]
    assert targets_match(manifest, "db-01")
    assert not targets_match(manifest, "web-01")
    manifest.targets = ["eai-.*"]
    assert targets_match(manifest, "eai-01")
    assert not targets_match(manifest, "demo-local")


def test_stage1_plugin_and_eai_isolation():
    text = (ROOT / "sample_logs" / "demo.log").read_text(encoding="utf-8")
    events = parse_text(text, default_host="demo-local")
    stage1 = run_stage1("demo-local", "demo-local", events)
    assert any(str(item.get("plugin", "")).startswith("stage1.") for item in stage1)
    eai_events = parse_text(
        "2026-08-26 10:00:00 ERROR Adapter inbound failed for channel FOO\n",
        default_host="eai-01",
    )
    eai = run_stage2("eai-01", "eai-01", eai_events)
    demo = run_stage2("demo-local", "demo-local", eai_events)
    assert any(item["signature"] == "eai.adapter_failed" for item in eai)
    assert not any(item["signature"] == "eai.adapter_failed" for item in demo)


def test_assigned_plugins_skip_global_and_match_server():
    demo = {item.name for item in assigned_plugins("demo-local")}
    assert "auth_failures" not in demo
    assert "disk_full" not in demo
    assert "daily_report" not in demo
    assert "server_report" not in demo
    eai = {item.name for item in assigned_plugins("eai-01")}
    assert "eai" in eai
    assert "eai_report" in eai
    assert "mci" not in eai
