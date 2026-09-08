"""서버가 로그를 볼지 리소스를 볼지, 그리고 지켜볼 인스턴스 목록.

예전에는 data/server_modes.json 에 두었지만 지금은 servers 표에 함께 둔다.
이름만 알고 있는 자리(수집기·보고서)에서 쓰라고 얇은 함수로 감싼다.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import settings

DEFAULT = {"logs": True, "resources": False, "instances": []}


def clean_instances(names: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    for raw in names or []:
        for part in str(raw or "").replace(",", "\n").splitlines():
            name = part.strip()
            if name and name not in cleaned:
                cleaned.append(name)
    return cleaned


def parse_list(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item).strip()]


def _session():
    from app.models import SessionLocal

    return SessionLocal()


def _fetch(server_name: str):
    from sqlalchemy.exc import OperationalError

    from app.models import Server

    name = (server_name or "").strip()
    if not name:
        return None
    try:
        with _session() as db:
            server = db.query(Server).filter(Server.name == name).one_or_none()
            if not server:
                return None
            return {
                "logs": bool(server.collect_logs),
                "resources": bool(server.collect_resources),
                "instances": parse_list(server.instances),
            }
    except OperationalError:
        return None


def get_modes(server_name: str) -> dict:
    current = _fetch(server_name)
    if not current:
        return {"logs": True, "resources": False, "instances": []}
    return current


def set_modes(
    server_name: str,
    *,
    logs: bool,
    resources: bool,
    instances: list[str] | None = None,
) -> dict:
    from app.models import Server

    name = (server_name or "").strip()
    if not name:
        raise ValueError("서버 이름이 없습니다.")
    if not logs and not resources:
        raise ValueError("로그 분석 또는 리소스 분석 중 하나는 선택해야 합니다.")
    cleaned = clean_instances(instances)
    with _session() as db:
        server = db.query(Server).filter(Server.name == name).one_or_none()
        if server is None:
            raise ValueError(f"등록되지 않은 서버입니다: {name}")
        server.collect_logs = bool(logs)
        server.collect_resources = bool(resources)
        server.instances = json.dumps(cleaned, ensure_ascii=False)
        db.commit()
    return {"logs": bool(logs), "resources": bool(resources), "instances": cleaned}


def set_instances(server_name: str, instances: list[str] | None) -> list[str]:
    from app.models import Server

    name = (server_name or "").strip()
    if not name:
        raise ValueError("서버 이름이 없습니다.")
    cleaned = clean_instances(instances)
    with _session() as db:
        server = db.query(Server).filter(Server.name == name).one_or_none()
        if server is None:
            raise ValueError(f"등록되지 않은 서버입니다: {name}")
        server.instances = json.dumps(cleaned, ensure_ascii=False)
        db.commit()
    return cleaned


def get_instances(server_name: str) -> list[str]:
    return get_modes(server_name)["instances"]


def analyzes_logs(server_name: str) -> bool:
    return bool(get_modes(server_name)["logs"])


def analyzes_resources(server_name: str) -> bool:
    return bool(get_modes(server_name)["resources"])


def modes_path() -> Path:
    return settings.data_path / "server_modes.json"


def migrate_from_file() -> int:
    """예전 server_modes.json 을 한 번만 servers 표로 옮긴다."""
    from app.models import Server

    path = modes_path()
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    moved = 0
    if isinstance(data, dict):
        with _session() as db:
            for name, value in data.items():
                if not isinstance(value, dict):
                    continue
                server = db.query(Server).filter(Server.name == str(name)).one_or_none()
                if server is None:
                    continue
                server.collect_logs = bool(value.get("logs", True))
                server.collect_resources = bool(value.get("resources", False))
                server.instances = json.dumps(
                    clean_instances(value.get("instances")), ensure_ascii=False
                )
                moved += 1
            db.commit()
    path.rename(path.with_suffix(".json.migrated"))
    return moved
