from __future__ import annotations

from glob import glob
from pathlib import Path

from app.collectors.base import CollectedChunk, Collector
from app.config import ROOT


class LocalTailCollector(Collector):
    """로컬(또는 마운트된 공유폴더) 파일 증분 읽기."""

    name = "local"

    def resolve_paths(self, pattern: str) -> list[str]:
        raw = Path(pattern)
        target = raw if raw.is_absolute() else ROOT / raw
        text = str(target)
        if any(ch in text for ch in "*?[]"):
            return [str(Path(item)) for item in sorted(glob(text))]
        return [str(target)]

    def read_incremental(
        self,
        path: str,
        offset: int,
        max_bytes: int,
        inode: int = 0,
    ) -> CollectedChunk:
        file_path = Path(path)
        if not file_path.exists():
            return CollectedChunk(path=path, text="", new_offset=offset, size=0, inode=inode, missing=True)
        stat = file_path.stat()
        size = stat.st_size
        current_inode = int(getattr(stat, "st_ino", 0) or 0)
        rotated = (inode and current_inode and inode != current_inode) or size < offset
        start = 0 if rotated else offset
        to_read = min(max(size - start, 0), max_bytes)
        text = ""
        if to_read:
            with file_path.open("rb") as fh:
                fh.seek(start)
                raw = fh.read(to_read)
            text = raw.decode("utf-8", errors="replace")
        return CollectedChunk(
            path=str(file_path),
            text=text,
            new_offset=start + to_read,
            size=size,
            inode=current_inode,
            bytes_read=to_read,
        )
