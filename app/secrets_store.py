"""서버 접속 정보 보관. 비밀번호는 암호화해서, 개인키는 권한 제한한 파일로 둔다."""
from __future__ import annotations

import os
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _key_file() -> Path:
    path = settings.data_path / "secret.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _fernet() -> Fernet:
    path = _key_file()
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        _restrict(path)
    return Fernet(path.read_bytes().strip())


def _restrict(path: Path) -> None:
    """소유자만 읽게 한다. 윈도우에서는 되는 만큼만 적용된다."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def encrypt(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    value = (token or "").strip()
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def keys_dir() -> Path:
    path = settings.data_path / "keys"
    path.mkdir(parents=True, exist_ok=True)
    _restrict(path)
    return path


def save_key(server_name: str, data: bytes) -> str:
    """올린 개인키를 data/keys 아래 두고 경로를 돌려준다."""
    body = (data or b"").strip()
    if not body:
        raise ValueError("키 파일이 비어 있습니다.")
    if b"PRIVATE KEY" not in body:
        raise ValueError("개인키 파일이 아닙니다. id_rsa 같은 PEM 파일을 올려 주세요.")
    safe = SAFE_NAME.sub("_", (server_name or "server").strip()) or "server"
    path = keys_dir() / f"{safe}.key"
    path.write_bytes(body + b"\n")
    _restrict(path)
    return str(path)


def delete_key(key_path: str) -> None:
    path = Path(key_path or "")
    if not path.name:
        return
    try:
        if path.exists() and path.parent.resolve() == keys_dir().resolve():
            path.unlink()
    except OSError:
        pass


def key_label(key_path: str) -> str:
    path = Path(key_path or "")
    if not key_path:
        return ""
    if path.parent.resolve(strict=False) == keys_dir().resolve():
        return f"{path.name} (등록됨)"
    return str(key_path)
