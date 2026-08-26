from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from app.pipeline.normalize import NormalizedEvent


def analyze_common(events: list[NormalizedEvent], host: str = "", config: dict | None = None) -> list[dict]:
    """Stage 1: ERROR/WARN/INFO/DEBUG 공통 집계와 버스트 탐지."""
    cfg = config or {}
    info_min = int(cfg.get("info_min_count", 20))
    debug_min = int(cfg.get("debug_min_count", 50))
    burst_window = int(cfg.get("burst_window_seconds", 60))
    burst_threshold = int(cfg.get("burst_threshold", 8))
    buckets: dict[tuple[str, str], dict] = {}
    timestamps: dict[str, list[datetime]] = defaultdict(list)

    for event in events:
        if event.level not in {"error", "warn", "info", "debug"}:
            continue
        key = (event.level, event.signature or event.message[:480])
        item = buckets.get(key)
        sample = event.raw
        when = event.occurred_at or datetime.utcnow()
        if item is None:
            buckets[key] = {
                "severity": event.level if event.level != "info" else "info",
                "signature": key[1],
                "count": 1,
                "sample_lines": [sample],
                "host": event.host or host,
                "occurred_at": when,
                "plugin": "stage1.common",
            }
        else:
            item["count"] += 1
            if sample not in item["sample_lines"] and len(item["sample_lines"]) < 5:
                item["sample_lines"].append(sample)
            if when < item["occurred_at"]:
                item["occurred_at"] = when
        if event.level in {"error", "warn"} and event.occurred_at:
            timestamps[key[1]].append(event.occurred_at)

    findings = []
    for item in buckets.values():
        if item["severity"] == "info" and item["count"] < info_min:
            continue
        if item["severity"] == "debug" and item["count"] < debug_min:
            continue
        findings.append(item)

    for signature, times in timestamps.items():
        if _is_burst(times, window_seconds=burst_window, threshold=burst_threshold):
            findings.append(
                {
                    "severity": "error",
                    "signature": f"burst:{signature}",
                    "count": len(times),
                    "sample_lines": [f"{len(times)} events in 60s window: {signature}"],
                    "host": host,
                    "occurred_at": max(times),
                    "plugin": "stage1.burst",
                }
            )
    return findings


def _is_burst(times: list[datetime], window_seconds: int = 60, threshold: int = 8) -> bool:
    if len(times) < threshold:
        return False
    ordered = sorted(times)
    left = 0
    for right, moment in enumerate(ordered):
        while moment - ordered[left] > timedelta(seconds=window_seconds):
            left += 1
        if right - left + 1 >= threshold:
            return True
    return False
