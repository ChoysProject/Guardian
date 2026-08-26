from app.config import settings
from app.plugins import editor
from app.plugins.loader import load_manifests, targets_match
from app.plugins.runtime import run_stage2
from app.pipeline.normalize import parse_text


def test_create_rules_plugin_and_match(tmp_path, monkeypatch):
    monkeypatch.setattr(settings.plugins, "dir", str(tmp_path))
    editor.create_rules_plugin(
        "shop",
        description="쇼핑몰 결제",
        targets=["shop-01"],
        rules=[
            {
                "pattern": "PAY FAIL",
                "severity": "error",
                "signature": "shop.pay_fail",
                "min_count": 1,
            }
        ],
    )
    names = {item.name for item in load_manifests()}
    assert "shop" in names
    events = parse_text("2026-08-26 11:00:00 ERROR PAY FAIL order=1\n", default_host="shop-01")
    hit = run_stage2("shop-01", "shop-01", events)
    miss = run_stage2("demo-local", "demo-local", events)
    assert any(item["signature"] == "shop.pay_fail" for item in hit)
    assert not any(item["signature"] == "shop.pay_fail" for item in miss)
    plugin = [item for item in load_manifests() if item.name == "shop"][0]
    assert targets_match(plugin, "shop-01")
    assert not targets_match(plugin, "mci-01")


def test_reject_bad_plugin_name():
    try:
        editor.plugin_folder(2, "../etc")
    except ValueError:
        return
    raise AssertionError("경로 탈출이 막혀야 합니다")
