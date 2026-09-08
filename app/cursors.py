from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.config import settings

PAGE_SIZE = 50


def cursors_path() -> Path:
    path = settings.data_path / "cursors.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_all() -> list[dict]:
    path = cursors_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def save_all(items: list[dict]) -> None:
    cursors_path().write_text(
        json.dumps({"items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_cursor(server_id: int, log_path: str) -> dict | None:
    for item in load_all():
        if int(item.get("server_id") or 0) == int(server_id) and item.get("log_path") == log_path:
            return item
    return None


def upsert_cursor(
    server_id: int,
    server_name: str,
    log_path: str,
    offset: int,
    size: int,
    inode: int = 0,
    updated_at: datetime | None = None,
) -> None:
    stamp = (updated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S")
    items = load_all()
    found = False
    for item in items:
        if int(item.get("server_id") or 0) == int(server_id) and item.get("log_path") == log_path:
            item.update(
                {
                    "server_name": server_name,
                    "offset": int(offset),
                    "size": int(size),
                    "inode": int(inode or 0),
                    "updated_at": stamp,
                }
            )
            found = True
            break
    if not found:
        items.append(
            {
                "server_id": int(server_id),
                "server_name": server_name,
                "log_path": log_path,
                "offset": int(offset),
                "size": int(size),
                "inode": int(inode or 0),
                "updated_at": stamp,
            }
        )
    save_all(items)


def delete_for_servers(server_ids: list[int]) -> None:
    wanted = {int(item) for item in server_ids}
    if not wanted:
        return
    kept = [item for item in load_all() if int(item.get("server_id") or 0) not in wanted]
    save_all(kept)


def page_cursors(offset: int = 0, limit: int = PAGE_SIZE, server_id: int | None = None) -> dict:
    start = max(int(offset or 0), 0)
    size = max(min(int(limit or PAGE_SIZE), 200), 1)
    items = load_all()
    if server_id is not None:
        wanted = int(server_id)
        items = [item for item in items if int(item.get("server_id") or 0) == wanted]
    items = sorted(
        items,
        key=lambda item: (str(item.get("server_name") or ""), str(item.get("log_path") or "")),
    )
    total = len(items)
    sliced = items[start : start + size]
    return {
        "items": sliced,
        "offset": start,
        "limit": size,
        "total": total,
        "has_more": start + len(sliced) < total,
    }


def migrate_from_db(db) -> None:
    if load_all():
        return
    from app.models import CollectCursor, Server

    names = {item.id: item.name for item in db.query(Server).all()}
    rows = db.query(CollectCursor).all()
    if not rows:
        return
    items = []
    for row in rows:
        when = row.updated_at
        stamp = when.strftime("%Y-%m-%d %H:%M:%S") if hasattr(when, "strftime") else str(when or "")[:19]
        items.append(
            {
                "server_id": row.server_id,
                "server_name": names.get(row.server_id, str(row.server_id)),
                "log_path": row.log_path,
                "offset": int(row.offset or 0),
                "size": int(row.size or 0),
                "inode": int(getattr(row, "inode", 0) or 0),
                "updated_at": stamp,
            }
        )
    save_all(items)
