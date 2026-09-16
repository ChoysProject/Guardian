"""서버 접속 정보 보관. 비밀번호는 암호화해서, 개인키는 권한 제한한 파일로 둔다."""
from __future__ import annotations

import os
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
SHARED_KEY_NAME = "guardian"


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
    """소유자만 읽게 한다. 폴더는 들어가려면 실행 비트가 필요하다."""
    try:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
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


def shared_key_path() -> Path:
    return keys_dir() / f"{SHARED_KEY_NAME}.key"


def is_shared_key(key_path: str) -> bool:
    path = Path(key_path or "")
    if not key_path:
        return False
    try:
        return path.expanduser().resolve() == shared_key_path().resolve()
    except OSError:
        return path.name == f"{SHARED_KEY_NAME}.key"


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
    """서버 전용으로 올린 키만 지운다. 이 PC 공용 키는 남겨 둔다."""
    if is_shared_key(key_path):
        return
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
    if is_shared_key(key_path):
        return f"{path.name} (이 PC 공용)"
    if path.parent.resolve(strict=False) == keys_dir().resolve():
        return f"{path.name} (등록됨)"
    return str(key_path)


def generate_ssh_key() -> str:
    """이 PC용 Ed25519 개인키 하나를 만들어 data/keys/guardian.key 에 둔다."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return save_key(SHARED_KEY_NAME, pem)


def ensure_ssh_key() -> tuple[str, bool]:
    """공용 키가 있으면 그대로 쓰고, 없으면 만든다. (경로, 새로 만들었는지)."""
    path = shared_key_path()
    if path.exists():
        return str(path), False
    return generate_ssh_key(), True


def public_key_from_path(key_path: str, comment: str = "") -> str:
    """authorized_keys 에 넣을 공개키 한 줄을 개인키에서 만든다."""
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
        load_pem_private_key,
        load_ssh_private_key,
    )

    path = Path(key_path or "").expanduser()
    if not key_path or not path.exists():
        return ""
    data = path.read_bytes()
    loaded = None
    for loader in (
        lambda body: load_ssh_private_key(body, password=None),
        lambda body: load_pem_private_key(body, password=None),
    ):
        try:
            loaded = loader(data)
            break
        except Exception:  # noqa: BLE001 — 키 형식을 차례로 시도
            continue
    if loaded is None:
        return ""
    line = loaded.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode("ascii").strip()
    extra = (comment or "").strip()
    if extra:
        return f"{line} {extra}"
    return line
