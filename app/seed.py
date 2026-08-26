from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import ROOT, settings
from app.db import dump_json
from app.metrics import wall_now
from app.cursors import delete_for_servers
from app.models import Server

DEMO_LOG = ROOT / "sample_logs" / "demo.log"
LAYOUT_STAMP = ROOT / "sample_logs" / ".layout_v2"


def seed_demo(db: Session) -> None:
    if not settings.app.seed_demo:
        return
    DEMO_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not DEMO_LOG.exists():
        DEMO_LOG.write_text(_demo_log_text(), encoding="utf-8")
    _ensure_server(
        db,
        name="demo-local",
        host="demo-local",
        log_paths=["sample_logs/demo.log"],
    )
    if os.environ.get("GUARDIAN_TESTING") == "1":
        return
    refresh = not LAYOUT_STAMP.exists()
    _write_dummy_logs(force=refresh)
    extra = [
        ("demo-web", "demo-web", ["sample_logs/web/%Y-%m-%d.log", "sample_logs/web/hourly/%Y-%m-%d/%H.log"]),
        ("demo-db", "demo-db", ["sample_logs/db/%Y-%m-%d.log"]),
        ("demo-auth", "demo-auth", ["sample_logs/auth/%Y-%m-%d.log"]),
    ]
    names = ["demo-local"]
    for name, host, paths in extra:
        _ensure_server(db, name=name, host=host, log_paths=paths)
        names.append(name)
    if refresh:
        _reset_cursors(db, names)
        LAYOUT_STAMP.write_text("v2\n", encoding="utf-8")


def _ensure_server(db: Session, name: str, host: str, log_paths: list[str]) -> Server:
    server = db.query(Server).filter(Server.name == name).one_or_none()
    payload = dump_json(log_paths)
    if server is None:
        server = Server(
            name=name,
            collector_type="local",
            host=host,
            port=0,
            username="",
            key_path="",
            log_paths=payload,
            enabled=True,
        )
        db.add(server)
        db.commit()
        return server
    if server.log_paths != payload:
        server.log_paths = payload
        db.commit()
    return server


def _reset_cursors(db: Session, names: list[str]) -> None:
    ids = [item.id for item in db.query(Server).filter(Server.name.in_(names)).all()]
    if ids:
        delete_for_servers(ids)


def _write_dummy_logs(force: bool = False) -> None:
    now = wall_now().replace(minute=0, second=0, microsecond=0)
    writers = {
        "web": _web_lines,
        "db": _db_lines,
        "auth": _auth_lines,
    }
    for name, writer in writers.items():
        folder = ROOT / "sample_logs" / name
        folder.mkdir(parents=True, exist_ok=True)
        for day_offset in range(6, -1, -1):
            day = (now - timedelta(days=day_offset)).date()
            path = folder / f"{day.isoformat()}.log"
            if path.exists() and not force:
                continue
            lines: list[str] = []
            last_hour = now.hour if day_offset == 0 else 23
            for hour in range(last_hour + 1):
                stamp = datetime(day.year, day.month, day.day, hour)
                lines.extend(writer(stamp, day_offset, hour))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_hourly_web_logs(now, force=force)


def _write_hourly_web_logs(now: datetime, force: bool = False) -> None:
    for hour_offset in range(47, -1, -1):
        stamp = now - timedelta(hours=hour_offset)
        folder = ROOT / "sample_logs" / "web" / "hourly" / stamp.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{stamp.strftime('%H')}.log"
        if path.exists() and not force:
            continue
        path.write_text("\n".join(_web_lines(stamp, 0, stamp.hour)) + "\n", encoding="utf-8")


def _web_lines(stamp: datetime, day_offset: int, hour: int) -> list[str]:
    ts = stamp.strftime("%Y-%m-%d %H:%M:%S")
    business = 9 <= hour <= 18
    info_n = 10 if business else 4
    warn_n = 3 if business else 1
    error_n = (6 + (hour % 3)) if business else (1 + (hour % 2))
    debug_n = 2
    if day_offset == 0 and 10 <= hour <= 12:
        error_n += 8
    lines = [f"{ts} INFO [api] request accepted path=/health"] * info_n
    lines += [f"{ts} WARN [api] slow response 1200ms path=/orders"] * warn_n
    lines += [f"{ts} ERROR [api] Connection refused to 10.0.0.12:8080"] * error_n
    lines += [f"{ts} DEBUG [cache] miss key=session:{hour}"] * debug_n
    return lines


def _db_lines(stamp: datetime, day_offset: int, hour: int) -> list[str]:
    ts = stamp.strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"{ts} INFO [postgres] checkpoint complete",
        f"{ts} DEBUG [postgres] autovacuum skipped",
    ]
    if 9 <= hour <= 11 or hour == 15:
        lines += [f"{ts} ERROR [postgres] Connection refused to 10.0.0.12:5432"] * (4 + hour % 5)
        lines += [f"{ts} WARN [postgres] retrying replica 10.0.0.13"] * 2
    if hour == 12:
        lines += [
            f"{ts} WARN [disk] No space left on device /var",
            f"{ts} ERROR [disk] No space left on device /var",
        ]
    return lines


def _auth_lines(stamp: datetime, day_offset: int, hour: int) -> list[str]:
    ts = stamp.strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"{ts} INFO [sshd] Accepted publickey for deploy from 10.0.1.8"]
    if hour in (2, 3, 11, 22):
        lines += [
            f"{ts} ERROR [sshd] Failed password for root from 192.168.10.5 port 55122 ssh2",
            f"{ts} ERROR [sshd] Failed password for root from 192.168.10.5 port 55123 ssh2",
            f"{ts} ERROR [sshd] Failed password for invalid user oracle from 192.168.10.5 port 55124 ssh2",
            f"{ts} ERROR [sshd] Failed password for admin from 192.168.10.5 port 55126 ssh2",
        ]
    return lines


def _demo_log_text() -> str:
    return """\
2026-08-25 09:01:02 INFO [api] Guardian demo server started
2026-08-25 09:12:11 INFO [api] health check ok
2026-08-25 10:03:44 ERROR [worker] Connection refused to 10.0.0.12:5432
2026-08-25 10:03:45 ERROR [worker] Connection refused to 10.0.0.12:5432
2026-08-25 10:03:46 ERROR [worker] Connection refused to 10.0.0.12:5432
2026-08-25 10:03:50 ERROR [worker] Connection refused to 10.0.0.12:5432
2026-08-25 10:04:01 ERROR [worker] Connection refused to 10.0.0.12:5432
2026-08-25 10:04:08 ERROR [worker] Connection refused to 10.0.0.12:5432
2026-08-25 10:04:15 ERROR [worker] Connection refused to 10.0.0.12:5432
2026-08-25 10:04:22 ERROR [worker] Connection refused to 10.0.0.12:5432
2026-08-25 10:04:30 ERROR [worker] Connection refused to 10.0.0.12:5432
Aug 25 11:15:03 demo-local sshd[4412]: Failed password for root from 192.168.10.5 port 55122 ssh2
Aug 25 11:15:08 demo-local sshd[4413]: Failed password for root from 192.168.10.5 port 55123 ssh2
Aug 25 11:15:14 demo-local sshd[4414]: Failed password for invalid user oracle from 192.168.10.5 port 55124 ssh2
Aug 25 11:15:20 demo-local sshd[4415]: Failed password for invalid user oracle from 192.168.10.5 port 55125 ssh2
Aug 25 11:15:26 demo-local sshd[4416]: Failed password for admin from 192.168.10.5 port 55126 ssh2
2026-08-25 12:40:00 WARN [disk] No space left on device /var
2026-08-25 12:40:05 ERROR [disk] No space left on device /var
2026-08-25 13:10:00 DEBUG [cache] miss key=user:42
2026-08-25 18:22:10 INFO [batch] daily job finished
"""
