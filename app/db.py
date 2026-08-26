from __future__ import annotations

import json
from collections.abc import Generator

from sqlalchemy.orm import Session

from app.models import SessionLocal, init_db


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def parse_json_list(raw: str) -> list:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def dump_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def ensure_db() -> None:
    init_db()
