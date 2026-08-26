from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath

import paramiko

from app.collectors.base import CollectedChunk, Collector


def _load_private_key(key_file: Path):
    errors: list[str] = []
    for loader in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return loader.from_private_key_file(str(key_file))
        except Exception as exc:  # noqa: BLE001 — 키 종류를 순차로 시도
            errors.append(f"{loader.__name__}: {exc}")
    raise ValueError("SSH 개인키를 읽지 못했습니다. " + " | ".join(errors))


class SshTailCollector(Collector):
    name = "ssh"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        key_path: str,
        timeout: int = 20,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.key_path = key_path
        self.timeout = timeout
        self._client = None
        self._sftp = None

    def open(self) -> None:
        if self._sftp is not None:
            return
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        pkey = None
        if self.key_path:
            pkey = _load_private_key(Path(self.key_path).expanduser())
        client.connect(
            hostname=self.host,
            port=self.port,
            username=self.username,
            pkey=pkey,
            timeout=self.timeout,
            allow_agent=True,
            look_for_keys=not bool(pkey),
        )
        self._client = client
        self._sftp = client.open_sftp()

    def close(self) -> None:
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._client is not None:
            self._client.close()
            self._client = None

    def resolve_paths(self, pattern: str) -> list[str]:
        self.open()
        posix = PurePosixPath(pattern.replace("\\", "/"))
        if not any(ch in posix.name for ch in "*?[]"):
            return [str(posix)]
        parent = str(posix.parent)
        try:
            names = self._sftp.listdir(parent)
        except (FileNotFoundError, OSError, IOError):
            return []
        matched = [f"{parent}/{name}" for name in sorted(names) if fnmatch.fnmatch(name, posix.name)]
        return matched

    def read_incremental(
        self,
        path: str,
        offset: int,
        max_bytes: int,
        inode: int = 0,
    ) -> CollectedChunk:
        self.open()
        try:
            stat = self._sftp.stat(path)
        except (FileNotFoundError, OSError, IOError):
            return CollectedChunk(path=path, text="", new_offset=offset, size=0, inode=inode, missing=True)
        size = int(stat.st_size or 0)
        current_inode = int(getattr(stat, "st_ino", 0) or 0)
        rotated = (inode and current_inode and inode != current_inode) or size < offset
        start = 0 if rotated else offset
        to_read = min(max(size - start, 0), max_bytes)
        text = ""
        if to_read:
            with self._sftp.open(path, "rb") as fh:
                fh.seek(start)
                raw = fh.read(to_read)
            text = raw.decode("utf-8", errors="replace")
        return CollectedChunk(
            path=path,
            text=text,
            new_offset=start + to_read,
            size=size,
            inode=current_inode,
            bytes_read=to_read,
        )
