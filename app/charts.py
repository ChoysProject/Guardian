from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.metrics import LEVELS, timeline_from_hourly, wall_now
from app.models import Finding, Server


def chart_summary(db: Session, granularity: str = "hour") -> dict:
    mode = "day" if granularity == "day" else "hour"
    timeline = timeline_from_hourly(mode)
    servers = {item.id: item.name for item in db.query(Server).all()}
    findings = db.query(Finding).all()

    severity_totals: dict[str, int] = defaultdict(int)
    server_totals: dict[str, int] = defaultdict(int)
    for item in findings:
        level = item.severity or "info"
        severity_totals[level] += int(item.count or 1)
        name = servers.get(item.server_id) or item.host or str(item.server_id)
        server_totals[name] += int(item.count or 1)

    if not any(sum(timeline[level]) for level in LEVELS):
        timeline = _timeline_from_findings(findings, mode)

    window_severity = {level: sum(timeline[level]) for level in LEVELS}
    if any(window_severity.values()):
        severity_labels = list(LEVELS)
        severity_values = [window_severity[level] for level in LEVELS]
    else:
        severity_labels = list(LEVELS)
        severity_values = [severity_totals.get(level, 0) for level in LEVELS]

    return {
        "granularity": mode,
        "timeline": {
            "labels": timeline["labels"],
            "error": timeline["error"],
            "warn": timeline["warn"],
            "info": timeline["info"],
            "debug": timeline["debug"],
        },
        "severity": {
            "labels": severity_labels,
            "values": severity_values,
        },
        "servers": {
            "labels": list(server_totals.keys()) or ["없음"],
            "values": list(server_totals.values()) or [0],
        },
    }


def _timeline_from_findings(findings, granularity: str) -> dict:
    from datetime import datetime, timedelta

    now = wall_now().replace(minute=0, second=0, microsecond=0)
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {level: 0 for level in LEVELS})
    for item in findings:
        when = item.occurred_at or item.created_at or now
        if granularity == "day":
            key = when.strftime("%Y-%m-%d")
        else:
            key = when.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:00")
        level = item.severity if item.severity in LEVELS else "info"
        buckets[key][level] += int(item.count or 1)

    if granularity == "day":
        labels = [(now - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(6, -1, -1)]
    else:
        labels = [(now - timedelta(hours=offset)).strftime("%Y-%m-%d %H:00") for offset in range(23, -1, -1)]
        extra = sorted(buckets)
        if extra and not any(label in extra for label in labels):
            labels = extra[-24:]

    return {
        "labels": labels,
        **{level: [buckets[label][level] for label in labels] for level in LEVELS},
    }
