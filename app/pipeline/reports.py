from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.ai.gateway import review_logs
from app.config import settings
from app.cursors import load_all
from app.db import parse_json_list
from app.metrics import server_day_counts
from app.models import Finding, Report, Server
from app.plugins.report_common import render_standard_report
from app.plugins.runtime import assigned_plugins, _run_reporter
from app.plugins.types import PluginContext
from app.server_modes import analyzes_logs


def day_window(when: datetime | None = None) -> tuple[datetime, datetime]:
    start_local, end_local, _stamp, _start_utc, _end_utc = report_period(when)
    return start_local, end_local


def report_period(when: datetime | None = None) -> tuple[datetime, datetime, str, datetime, datetime]:
    tz = ZoneInfo(settings.app.timezone)
    now = when or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    start_local = datetime.combine(now.date(), time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    stamp = now.date().isoformat()
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_local.replace(tzinfo=None), end_local.replace(tzinfo=None), stamp, start_utc, end_utc


def generate_reports(
    db: Session,
    when: datetime | None = None,
    plugin_names: list[str] | None = None,
    server_names: list[str] | None = None,
) -> list[Report]:
    start, end, stamp, start_utc, end_utc = report_period(when)
    servers = {server.id: server for server in db.query(Server).all()}
    enabled = [item for item in servers.values() if item.enabled and analyzes_logs(item.name)]
    if server_names is not None:
        wanted = {item for item in server_names if item}
        selected = [item for item in enabled if item.name in wanted]
    else:
        selected = enabled
    findings = db.query(Finding).order_by(Finding.severity.asc(), Finding.count.desc()).all()
    created: list[Report] = []
    settings.reports_path.mkdir(parents=True, exist_ok=True)
    for server in selected:
        items = [
            _finding_to_dict(item, servers.get(item.server_id))
            for item in findings
            if item.server_id == server.id and _finding_in_period(item, stamp, start_utc, end_utc)
        ]
        older = sum(1 for item in findings if item.server_id == server.id) - len(items)
        stats = _server_report_stats(server, stamp, files=_cursor_files(server), older_findings=max(older, 0))
        ai = review_logs(_log_review_payload(server.name, stats, items))
        base_cfg = {"mode": "per_server", "server_name": server.name, "stats": stats, "ai": ai}
        dedicated = assigned_plugins(server.name, stage=3)
        if plugin_names:
            dedicated = [item for item in dedicated if item.name in plugin_names]
        rendered = []
        if dedicated:
            ctx = PluginContext(
                server_name=server.name,
                host=server.host or server.name,
                events=[],
                config=base_cfg,
                period_start=start,
                period_end=end,
                findings=items,
            )
            for manifest in dedicated:
                result = _run_reporter(manifest, ctx)
                if result:
                    result["plugin"] = f"{manifest.name}:{server.name}"
                    rendered.append(result)
        if not rendered:
            ctx = PluginContext(
                server_name=server.name,
                host=server.host or server.name,
                events=[],
                config={**base_cfg, "title": f"{server.name} 일일 보고서"},
                period_start=start,
                period_end=end,
                findings=items,
            )
            result = render_standard_report(ctx)
            result["plugin"] = f"server_report:{server.name}"
            rendered.append(result)
        for item in rendered:
            created.append(_store_report(db, item, start, end, stamp))
    db.commit()
    for report in created:
        db.refresh(report)
    return created


def _finding_in_period(item: Finding, stamp: str, start_utc: datetime, end_utc: datetime) -> bool:
    if (item.bucket or "") == stamp:
        return True
    if item.occurred_at and item.occurred_at.strftime("%Y-%m-%d") == stamp:
        return True
    for when in (item.updated_at, item.created_at):
        if when is not None and start_utc <= when < end_utc:
            return True
    return False


def _cursor_files(server: Server) -> int:
    return sum(
        1
        for item in load_all()
        if int(item.get("server_id") or 0) == int(server.id)
        and str(item.get("server_name") or "") == server.name
    )


def _server_report_stats(server: Server, stamp: str, files: int = 0, older_findings: int = 0) -> dict:
    counts = server_day_counts(server.name, stamp)
    last = ""
    if server.last_collect_at:
        last = server.last_collect_at.strftime("%Y-%m-%d %H:%M")
    return {
        "lines": int(counts.get("lines") or 0),
        "error": int(counts.get("error") or 0),
        "warn": int(counts.get("warn") or 0),
        "info": int(counts.get("info") or 0),
        "debug": int(counts.get("debug") or 0),
        "files": int(counts.get("files") or files or 0),
        "last_collect": last,
        "older_findings": int(older_findings or 0),
    }


def _log_review_payload(server_name: str, stats: dict, items: list[dict]) -> dict:
    return {
        "server": server_name,
        "stats": {
            "lines": int(stats.get("lines") or 0),
            "error": int(stats.get("error") or 0),
            "warn": int(stats.get("warn") or 0),
            "files": int(stats.get("files") or 0),
        },
        "findings": [
            {
                "severity": item.get("severity"),
                "signature": item.get("signature"),
                "count": item.get("count"),
                "plugin": item.get("plugin"),
            }
            for item in items[:20]
        ],
    }


def _store_report(db: Session, item: dict, start: datetime, end: datetime, stamp: str) -> Report:
    plugin = item.get("plugin") or "server_report"
    markdown = item.get("markdown") or ""
    html = item.get("html") or ""
    md_path = settings.reports_path / f"{stamp}-{_safe_name(plugin)}.md"
    html_path = settings.reports_path / f"{stamp}-{_safe_name(plugin)}.html"
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    report = Report(
        plugin=plugin,
        title=item.get("title") or f"{stamp} 일일 보고서",
        period_start=start,
        period_end=end,
        markdown_path=str(md_path),
        html_path=str(html_path),
        summary=item.get("summary") or "",
        created_at=datetime.utcnow(),
    )
    db.add(report)
    return report


def _safe_name(value: str) -> str:
    text = re.sub(r"[^\w.-]+", "_", value or "report").strip("._")
    return text or "report"


def report_server_name(plugin: str) -> str:
    text = plugin or ""
    if ":" in text:
        return text.rsplit(":", 1)[-1]
    return ""


def group_log_report_rows(
    reports: list[Report],
    servers: list[Server],
    findings: list[Finding],
) -> list[dict]:
    reports_by_server: dict[str, list[Report]] = {}
    for item in reports:
        name = report_server_name(item.plugin)
        if not name:
            continue
        reports_by_server.setdefault(name, []).append(item)
    findings_by_id: dict[int, list[Finding]] = {}
    for item in findings:
        findings_by_id.setdefault(item.server_id, []).append(item)
    groups: list[dict] = []
    for server in servers:
        server_reports = reports_by_server.get(server.name, [])
        server_findings = findings_by_id.get(server.id, [])
        metrics = _log_card_metrics(server, server_findings)
        report_items = []
        for item in server_reports:
            created = item.created_at.strftime("%Y-%m-%d %H:%M") if item.created_at else ""
            report_items.append(
                {
                    "id": item.id,
                    "title": item.title or "",
                    "period": created,
                    "summary": (item.summary or "").split(" · ")[0],
                    "plugin": item.plugin or "",
                }
            )
        groups.append(
            {
                "name": server.name,
                "server_id": server.id,
                "reports": server_reports,
                "report_items": report_items,
                "reports_json": json.dumps(report_items, ensure_ascii=False),
                "latest": server_reports[0] if server_reports else None,
                "metrics": metrics,
                "verdict": (metrics.get("verdict") if metrics else "") or "",
                "has_data": bool(server.last_collect_at or server_findings),
            }
        )
    return groups


def _log_card_metrics(server: Server, findings: list[Finding]) -> dict:
    if not findings and not server.last_collect_at:
        return {}
    error_count = 0
    warn_count = 0
    for item in findings:
        amount = item.count if item.count and item.count > 0 else 1
        if item.severity == "error":
            error_count += amount
        elif item.severity == "warn":
            warn_count += amount
    if error_count:
        level, status = "danger", "위험"
    elif warn_count:
        level, status = "warn", "주의"
    elif server.last_error:
        level, status = "warn", "수집 문제"
    else:
        level, status = "ok", "여유"
    stamp = "-"
    if server.last_collect_at:
        stamp = server.last_collect_at.strftime("%Y-%m-%d")
    else:
        stamps = [
            item.updated_at or item.occurred_at
            for item in findings
            if item.updated_at or item.occurred_at
        ]
        if stamps:
            stamp = max(stamps).strftime("%Y-%m-%d")
    ranked = sorted(
        [item for item in findings if item.severity in {"error", "warn"}],
        key=lambda item: (0 if item.severity == "error" else 1, -(item.count or 1)),
    )
    problems = [str(item.signature or item.plugin or "징후") for item in ranked[:3]]
    extra = max(0, len(ranked) - 3)
    problem_text = " · ".join(problems)
    if extra:
        problem_text = f"{problem_text} 외 {extra}건" if problem_text else f"징후 {extra}건"
    if server.last_error:
        problem_text = server.last_error if not problem_text else f"{problem_text} · {server.last_error}"
    verdict = _log_verdict(error_count, warn_count, len(findings))
    if server.last_error and not error_count and not warn_count:
        verdict = server.last_error
    return {
        "date": stamp,
        "level": level,
        "status": status,
        "verdict": verdict,
        "problem_text": problem_text,
        "cells": [
            {"label": "ERROR", "value": str(error_count)},
            {"label": "WARN", "value": str(warn_count)},
            {"label": "징후", "value": f"{len(findings)}건"},
        ],
    }


def _log_verdict(error_count: int, warn_count: int, finding_count: int) -> str:
    if error_count:
        return f"ERROR {error_count}건이 있어 바로 확인이 필요합니다."
    if warn_count:
        return f"WARN {warn_count}건이 있어 추이를 봐야 합니다."
    if finding_count:
        return "징후는 있으나 ERROR·WARN은 없습니다."
    return "아직 징후가 없습니다."


def _finding_to_dict(finding: Finding, server: Server | None) -> dict:
    return {
        "id": finding.id,
        "server": server.name if server else str(finding.server_id),
        "host": finding.host,
        "severity": finding.severity,
        "signature": finding.signature,
        "count": finding.count,
        "plugin": finding.plugin,
        "ai_comment": finding.ai_comment,
        "sample_lines": parse_json_list(finding.sample_lines),
        "occurred_at": finding.occurred_at.isoformat() if finding.occurred_at else "",
    }
