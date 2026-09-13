import re

from app.config import settings
from app.pipeline.normalize import parse_text
from app.plugins import editor
from app.plugins.loader import load_manifests, targets_match
from app.plugins.runtime import run_stage2


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
        label="쇼핑몰 결제",
    )
    names = {item.name for item in load_manifests()}
    assert "shop" in names
    events = parse_text("2026-08-26 11:00:00 ERROR PAY FAIL order=1\n", default_host="shop-01")
    hit = run_stage2("shop-01", "shop-01", events)
    miss = run_stage2("demo-local", "demo-local", events)
    assert any(item["signature"] == "shop.pay_fail" for item in hit)
    assert not any(item["signature"] == "shop.pay_fail" for item in miss)
    plugin = [item for item in load_manifests() if item.name == "shop"][0]
    assert plugin.system == "custom"
    assert plugin.system_label == "세부 에러"
    assert plugin.label == "쇼핑몰 결제"
    assert targets_match(plugin, "shop-01")
    assert not targets_match(plugin, "mci-01")
    selected = run_stage2("other-01", "other-01", events, selected=["shop"])
    skipped = run_stage2("other-01", "other-01", events, selected=["nginx"])
    assert any(item["signature"] == "shop.pay_fail" for item in selected)
    assert not any(item["signature"] == "shop.pay_fail" for item in skipped)


def test_phrases_and_sample_logs_become_rules():
    phrase_rules = editor.literal_rules(["주문 타임아웃", "PAY-401"], "order_app")
    assert re.search(phrase_rules[0]["pattern"], "주문 타임아웃")
    assert re.search(phrase_rules[1]["pattern"], "PAY-401")
    sample = editor.rules_from_sample_logs(
        "2026-09-13 10:00:00 ERROR [OrderService] 재고 부족\n"
        "2026-09-13 10:00:01 ERROR PAY-401 결제 한도\n",
        "order_app",
    )
    texts = [item["pattern"] for item in sample]
    assert any(re.search(item, "재고 부족") for item in texts)
    assert any(re.search(item, "PAY-401 결제 한도") for item in texts)
    merged = editor.merge_rules(phrase_rules, sample)
    assert len(merged) == 4


def test_reject_bad_plugin_name():
    try:
        editor.plugin_folder(2, "../etc")
    except ValueError:
        return
    raise AssertionError("경로 탈출이 막혀야 합니다")
