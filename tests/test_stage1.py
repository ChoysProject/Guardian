from datetime import datetime, timedelta

from app.pipeline.normalize import parse_text
from app.pipeline.stage1 import analyze_common


def test_stage1_groups_errors_and_skips_sparse_info():
    lines = [
        "2026-08-25 10:00:00 INFO started",
        "2026-08-25 10:00:01 ERROR boom 1",
        "2026-08-25 10:00:02 ERROR boom 2",
        "2026-08-25 10:00:03 ERROR boom 3",
    ]
    findings = analyze_common(parse_text("\n".join(lines)), host="app-1")
    signatures = {item["signature"] for item in findings}
    assert any("boom" in sig for sig in signatures)
    assert not any(item["severity"] == "info" for item in findings)


def test_stage1_detects_burst():
    start = datetime(2026, 8, 25, 10, 0, 0)
    lines = []
    for i in range(8):
        ts = start + timedelta(seconds=i * 2)
        lines.append(f"{ts:%Y-%m-%d %H:%M:%S} ERROR fail {i}")
    findings = analyze_common(parse_text("\n".join(lines)), host="app-1")
    assert any(item["plugin"] == "stage1.burst" for item in findings)
