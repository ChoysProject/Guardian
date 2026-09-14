from app.config import ROOT
from app.pipeline.normalize import parse_text
from app.plugins.loader import load_manifests, targets_match
from app.plugins.runtime import assigned_plugins, catalog_plugins, custom_plugins, run_stage1
from app.plugins.types import PluginManifest


def test_loads_bundled_plugins():
    names = {item.name for item in load_manifests()}
    assert "common" in names
    assert "auth_failures" in names
    assert "disk_full" in names
    assert "java" in names
    assert "python" in names
    assert "daily_report" in names
    assert "server_report" in names
    assert "nginx" in names
    assert "oracle" in names
    assert "jeus" in names
    assert "kafka" in names
    assert "springboot" in names
    assert "eai_report" in names
    assert "eai" not in names
    assert "mci" not in names
    stages = {item.name: item.stage for item in load_manifests()}
    assert stages["nginx"] == 1
    assert stages["oracle"] == 1
    assert stages["java"] == 1
    assert stages["python"] == 1
    assert stages["common"] == 1


def test_auth_and_disk_plugins_on_demo_log():
    text = (ROOT / "sample_logs" / "demo.log").read_text(encoding="utf-8")
    events = parse_text(text, default_host="demo-local")
    findings = run_stage1("demo-local", "demo-local", events)
    plugins = {item["plugin"] for item in findings}
    assert "stage1.auth_failures" in plugins
    assert "stage1.disk_full" in plugins
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


def test_catalog_is_common_runtimes_not_eai_mci():
    catalog = {item.name for item in catalog_plugins()}
    custom = {item.name for item in custom_plugins()}
    assert "java" in catalog
    assert "python" in catalog
    assert "springboot" in catalog
    assert "nginx" in catalog
    assert "oracle" in catalog
    assert "eai" not in catalog
    assert "mci" not in catalog
    assert "eai" not in custom
    assert "mci" not in custom


def test_java_and_python_plugins():
    events = parse_text(
        "2026-08-26 10:00:00 ERROR java.lang.NullPointerException at com.example.App\n"
        "2026-08-26 10:00:01 ERROR java.lang.OutOfMemoryError: Java heap space\n"
        "2026-08-26 10:00:02 ERROR Traceback (most recent call last):\n"
        "2026-08-26 10:00:03 ERROR ModuleNotFoundError: No module named 'psycopg2'\n",
        default_host="app-01",
    )
    none = run_stage1("prod-01", "prod-01", events)
    assert not any(item.get("plugin") == "stage1.java" for item in none)
    assert not any(item.get("plugin") == "stage1.python" for item in none)
    jvm = run_stage1("prod-01", "prod-01", events, selected=["java"])
    assert any(item["signature"] == "java.npe" for item in jvm)
    assert any(item["signature"] == "java.oom" for item in jvm)
    assert not any(item.get("plugin") == "stage1.python" for item in jvm)
    py = run_stage1("prod-01", "prod-01", events, selected=["python"])
    assert any(item["signature"] == "python.traceback" for item in py)
    assert any(item["signature"] == "python.missing" for item in py)
    assert not any(item.get("plugin") == "stage1.java" for item in py)


def test_catalog_plugins_run_only_when_selected():
    events = parse_text(
        "2026-08-26 10:00:00 ERROR ORA-00600 internal error\n"
        "2026-08-26 10:00:01 ERROR upstream timed out (127.0.0.1:8080)\n"
        "2026-08-26 10:00:02 ERROR Failed to start tomcat.service\n",
        default_host="prod-01",
    )
    none = run_stage1("prod-01", "prod-01", events)
    assert not any(str(item.get("signature", "")).startswith("oracle.") for item in none)
    assert not any(str(item.get("signature", "")).startswith("nginx.") for item in none)
    assert not any(str(item.get("signature", "")).startswith("systemd.") for item in none)

    ora = run_stage1("prod-01", "prod-01", events, selected=["oracle"])
    assert any(item["signature"] == "oracle.ora_code" for item in ora)
    assert not any(str(item.get("signature", "")).startswith("nginx.") for item in ora)

    web = run_stage1("prod-01", "prod-01", events, selected=["nginx"])
    assert any(item["signature"] == "nginx.upstream_timeout" for item in web)


def test_targets_empty_does_not_match_all():
    manifest = PluginManifest(name="custom", stage=2, targets=[])
    assert not targets_match(manifest, "anything")
    assert not targets_match(manifest, "custom-01")


def test_assigned_plugins_skip_global_and_match_server():
    demo = {item.name for item in assigned_plugins("demo-local")}
    assert "auth_failures" not in demo
    assert "disk_full" not in demo
    assert "daily_report" not in demo
    assert "server_report" not in demo
    eai = {item.name for item in assigned_plugins("eai-01")}
    assert "eai" not in eai
    assert "mci" not in eai
    assert "eai_report" in eai
