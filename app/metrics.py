from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from app.config import settings

LEVELS = ("error", "warn", "info", "debug")


def wall_now() -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.app.timezone)).replace(tzinfo=None)
    except Exception:
        return datetime.now().replace(microsecond=0)


def metrics_path() -> Path:
    path = settings.data_path / "metrics" / "levels.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _empty_counts() -> dict[str, int]:
    return {level: 0 for level in LEVELS}


def _load_metrics() -> dict:
    path = metrics_path()
    if not path.exists():
        return {"hourly": {}, "servers": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"hourly": {}, "servers": {}}
    if not isinstance(data, dict):
        return {"hourly": {}, "servers": {}}
    return data


def load_hourly() -> dict[str, dict[str, int]]:
    hourly = _load_metrics().get("hourly") or {}
    if not isinstance(hourly, dict):
        return {}
    cleaned: dict[str, dict[str, int]] = {}
    for key, counts in hourly.items():
        if not isinstance(counts, dict):
            continue
        cleaned[str(key)] = {
            level: int(counts.get(level) or 0) for level in LEVELS
        }
    return cleaned


def save_hourly(hourly: dict[str, dict[str, int]], servers: dict | None = None) -> None:
    cutoff = (wall_now() - timedelta(days=14)).strftime("%Y-%m-%d %H:00")
    kept = {key: value for key, value in hourly.items() if key >= cutoff}
    payload = _load_metrics()
    payload["hourly"] = kept
    if servers is not None:
        payload["servers"] = _prune_server_days(servers)
    metrics_path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _prune_server_days(servers: dict) -> dict:
    cutoff = (wall_now() - timedelta(days=14)).strftime("%Y-%m-%d")
    cleaned: dict = {}
    for name, days in (servers or {}).items():
        if not isinstance(days, dict):
            continue
        kept = {day: value for day, value in days.items() if str(day) >= cutoff}
        if kept:
            cleaned[str(name)] = kept
    return cleaned


def server_day_counts(server: str, day: str) -> dict[str, int]:
    raw = (_load_metrics().get("servers") or {}).get(server) or {}
    if not isinstance(raw, dict):
        return {}
    row = raw.get(day) or {}
    if not isinstance(row, dict):
        return {}
    counts = {level: int(row.get(level) or 0) for level in LEVELS}
    counts["lines"] = int(row.get("lines") or sum(counts.values()))
    counts["files"] = int(row.get("files") or 0)
    return counts


def record_events(events: Iterable, server: str = "", files: int = 0) -> None:
    hourly = load_hourly()
    payload = _load_metrics()
    servers = payload.get("servers") if isinstance(payload.get("servers"), dict) else {}
    changed = False
    for event in events:
        when = getattr(event, "occurred_at", None) or wall_now()
        if getattr(when, "tzinfo", None) is not None:
            when = when.replace(tzinfo=None)
        key = when.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:00")
        level = getattr(event, "level", None) or "info"
        if level not in LEVELS:
            level = "info"
        bucket = hourly.setdefault(key, _empty_counts())
        bucket[level] = int(bucket.get(level) or 0) + 1
        if server:
            day = when.strftime("%Y-%m-%d")
            per_server = servers.setdefault(server, {})
            row = per_server.setdefault(day, {**_empty_counts(), "lines": 0, "files": 0})
            row[level] = int(row.get(level) or 0) + 1
            row["lines"] = int(row.get("lines") or 0) + 1
        changed = True
    if server and files:
        day = wall_now().strftime("%Y-%m-%d")
        per_server = servers.setdefault(server, {})
        row = per_server.setdefault(day, {**_empty_counts(), "lines": 0, "files": 0})
        row["files"] = max(int(row.get("files") or 0), int(files))
        changed = True
    if changed:
        save_hourly(hourly, servers=servers)


def timeline_from_hourly(granularity: str = "hour") -> dict:
    hourly = load_hourly()
    now = wall_now().replace(minute=0, second=0, microsecond=0)
    if granularity == "day":
        labels = []
        keys = []
        for offset in range(6, -1, -1):
            day = (now - timedelta(days=offset)).strftime("%Y-%m-%d")
            labels.append(day)
            keys.append(day)
        totals: dict[str, dict[str, int]] = defaultdict(_empty_counts)
        for stamp, counts in hourly.items():
            day = stamp[:10]
            for level in LEVELS:
                totals[day][level] += int(counts.get(level) or 0)
        series = {level: [totals[day][level] for day in keys] for level in LEVELS}
        return {"labels": labels, **series}

    labels = []
    for offset in range(23, -1, -1):
        labels.append((now - timedelta(hours=offset)).strftime("%Y-%m-%d %H:00"))
    series = {
        level: [int((hourly.get(label) or {}).get(level) or 0) for label in labels]
        for level in LEVELS
    }
    if any(sum(series[level]) for level in LEVELS):
        return {"labels": labels, **series}

    extra = sorted(hourly)
    if extra:
        labels = extra[-24:]
        series = {
            level: [int((hourly.get(label) or {}).get(level) or 0) for label in labels]
            for level in LEVELS
        }
    return {"labels": labels, **series}


def reset_metrics() -> None:
    path = metrics_path()
    if path.exists():
        path.unlink()
