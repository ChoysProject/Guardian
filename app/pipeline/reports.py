from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.db import parse_json_list
from app.models import Finding, Report, Server
from app.plugins.report_common import render_standard_report
from app.plugins.runtime import assigned_plugins, _run_reporter
from app.plugins.types import PluginContext


def day_window(when: datetime | None = None) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.app.timezone)
    now = when or datetime.now(tz)
    start = datetime.combine(now.date(), time.min, tzinfo=tz).astimezone().replace(tzinfo=None)
    end = start + timedelta(days=1)
    return start, end


def generate_reports(
    db: Session,
    when: datetime | None = None,
    plugin_names: list[str] | None = None,
    server_names: list[str] | None = None,
) -> list[Report]:
    start, end = day_window(when)
    servers = {server.id: server for server in db.query(Server).all()}
    enabled = [item for item in servers.values() if item.enabled]
    if server_names is not None:
        wanted = {item for item in server_names if item}
        selected = [item for item in enabled if item.name in wanted]
    else:
        selected = enabled
    findings = (
        db.query(Finding)
        .filter(Finding.created_at >= start, Finding.created_at < end)
        .order_by(Finding.severity.asc(), Finding.count.desc())
        .all()
    )
    payload = [_finding_to_dict(item, servers.get(item.server_id)) for item in findings]
    created: list[Report] = []
    settings.reports_path.mkdir(parents=True, exist_ok=True)
    stamp = start.strftime("%Y-%m-%d")
    for server in selected:
        items = [row for row in payload if row.get("server") == server.name]
        base_cfg = {"mode": "per_server", "server_name": server.name}
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
