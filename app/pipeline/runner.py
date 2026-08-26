from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.ai.gateway import annotate_findings
from app.collectors.factory import collector_for
from app.collectors.paths import expand_log_patterns
from app.config import settings
from app.cursors import get_cursor, migrate_from_db, upsert_cursor
from app.metrics import record_events
from app.db import dump_json, parse_json_list
from app.models import CollectRun, Finding, LogEvent, Server
from app.pipeline.normalize import parse_text
from app.plugins.runtime import run_stage1, run_stage2


def collect_and_analyze(db: Session, server_ids: list[int] | None = None) -> CollectRun:
    migrate_from_db(db)
    run = CollectRun(started_at=datetime.utcnow())
    db.add(run)
    db.flush()

    query = db.query(Server).filter(Server.enabled.is_(True))
    if server_ids:
        query = query.filter(Server.id.in_(server_ids))
    servers = query.all()

    total_lines = 0
    total_findings = 0
    errors: list[str] = []

    for server in servers:
        nested = db.begin_nested()
        try:
            collector = collector_for(server, ssh_timeout=settings.collect.ssh_timeout_seconds)
            with collector:
                events = _collect_server(db, server, collector)
            record_events(events)
            total_lines += len(events)
            created = _analyze_server(db, server, events)
            total_findings += created
            server.last_collect_at = datetime.utcnow()
            server.last_error = ""
            nested.commit()
        except Exception as exc:  # noqa: BLE001
            nested.rollback()
            server.last_error = str(exc)
            errors.append(f"{server.name}: {exc}")

    _prune_events(db)
    run.finished_at = datetime.utcnow()
    run.servers = len(servers)
    run.lines = total_lines
    run.findings = total_findings
    run.error = "\n".join(errors)
    db.commit()
    db.refresh(run)
    return run


def _collect_server(db: Session, server: Server, collector) -> list:
    patterns = parse_json_list(server.log_paths)
    expanded = expand_log_patterns(
        patterns,
        timezone=settings.app.timezone,
        lookback_hours=settings.collect.lookback_hours,
    )
    resolved: list[str] = []
    seen: set[str] = set()
    for pattern in expanded:
        for path in collector.resolve_paths(pattern):
            if path not in seen:
                seen.add(path)
                resolved.append(path)

    events = []
    bytes_used = 0
    budget = max(settings.collect.max_bytes_per_server, settings.collect.max_bytes_per_file)
    for path in resolved:
        if bytes_used >= budget:
            break
        cursor = get_cursor(server.id, path)
        offset = int(cursor.get("offset") or 0) if cursor else 0
        inode = int(cursor.get("inode") or 0) if cursor else 0
        remain = budget - bytes_used
        chunk = collector.read_incremental(
            path,
            offset,
            min(settings.collect.max_bytes_per_file, remain),
            inode=inode,
        )
        if chunk.missing:
            continue
        parsed = parse_text(chunk.text, default_host=server.host or server.name)
        events.extend(parsed)
        bytes_used += chunk.bytes_read
        now = datetime.utcnow()
        upsert_cursor(
            server_id=server.id,
            server_name=server.name,
            log_path=path,
            offset=chunk.new_offset,
            size=chunk.size,
            inode=chunk.inode,
            updated_at=now,
        )
        if settings.collect.persist_raw_events:
            for event in parsed:
                db.add(
                    LogEvent(
                        server_id=server.id,
                        occurred_at=event.occurred_at or now,
                        host=event.host or server.host or server.name,
                        level=event.level,
                        process_name=event.process_name,
                        message=event.message,
                        raw=event.raw,
                        signature=event.signature,
                        created_at=now,
                    )
                )
    db.flush()
    return events


def _analyze_server(db: Session, server: Server, events: list) -> int:
    if not events:
        return 0
    host = server.host or server.name
    drafts = run_stage1(server.name, host, events)
    drafts.extend(run_stage2(server.name, host, events))
    drafts = _merge_drafts(drafts)
    comments = annotate_findings(drafts)
    created = 0
    for draft, comment in zip(drafts, comments):
        if _upsert_finding(db, server, draft, comment):
            created += 1
    db.flush()
    return created


def _merge_drafts(drafts: list[dict]) -> list[dict]:
    grouped: dict[tuple, dict] = {}
    for draft in drafts:
        occurred = draft.get("occurred_at") or datetime.utcnow()
        if getattr(occurred, "tzinfo", None) is not None:
            occurred = occurred.replace(tzinfo=None)
        bucket = occurred.strftime("%Y-%m-%d")
        key = (
            draft.get("plugin") or "stage1.common",
            (draft.get("signature") or "")[:480],
            draft.get("severity") or "error",
            bucket,
        )
        current = grouped.get(key)
        if current is None:
            grouped[key] = {
                **draft,
                "occurred_at": occurred,
                "count": int(draft.get("count") or 1),
                "sample_lines": list(draft.get("sample_lines") or [])[:5],
                "plugin": key[0],
                "signature": key[1],
                "severity": key[2],
            }
            continue
        current["count"] += int(draft.get("count") or 1)
        samples = current["sample_lines"]
        for line in draft.get("sample_lines") or []:
            if line not in samples and len(samples) < 5:
                samples.append(line)
        if occurred < current["occurred_at"]:
            current["occurred_at"] = occurred
    return list(grouped.values())


def _upsert_finding(db: Session, server: Server, draft: dict, ai_comment: str) -> bool:
    occurred = draft.get("occurred_at") or datetime.utcnow()
    if occurred.tzinfo is not None:
        occurred = occurred.replace(tzinfo=None)
    bucket = occurred.strftime("%Y-%m-%d")
    plugin = draft.get("plugin") or "stage1.common"
    signature = (draft.get("signature") or "")[:480]
    existing = (
        db.query(Finding)
        .filter(
            Finding.server_id == server.id,
            Finding.plugin == plugin,
            Finding.signature == signature,
            Finding.severity == (draft.get("severity") or "error"),
            Finding.bucket == bucket,
        )
        .one_or_none()
    )
    samples = list(draft.get("sample_lines") or [])[:5]
    if existing:
        existing.count += int(draft.get("count") or 1)
        merged = parse_json_list(existing.sample_lines)
        for line in samples:
            if line not in merged and len(merged) < 5:
                merged.append(line)
        existing.sample_lines = dump_json(merged)
        existing.updated_at = datetime.utcnow()
        if ai_comment and not existing.ai_comment:
            existing.ai_comment = ai_comment
        return False

    db.add(
        Finding(
            server_id=server.id,
            occurred_at=occurred,
            host=draft.get("host") or server.host or server.name,
            severity=draft.get("severity") or "error",
            signature=signature,
            sample_lines=dump_json(samples),
            count=int(draft.get("count") or 1),
            plugin=plugin,
            ai_comment=ai_comment or "",
            bucket=bucket,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    return True


def _prune_events(db: Session) -> None:
    cutoff = datetime.utcnow() - timedelta(days=settings.retention.log_event_days)
    db.query(LogEvent).filter(LogEvent.created_at < cutoff).delete()
