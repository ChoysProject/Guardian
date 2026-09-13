from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

from app.collectors.base import CollectedChunk, Collector
from app.models import Server


class SshTailCollector(Collector):
    name = "ssh"

    def __init__(self, server: Server, timeout: int = 20) -> None:
        self.server = server
        self.timeout = timeout
        self._client = None
        self._sftp = None

    def open(self) -> None:
        if self._sftp is not None:
            return
        from app.resource_collect import _connect

        self._client = _connect(self.server)
        self._sftp = self._client.open_sftp()

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
