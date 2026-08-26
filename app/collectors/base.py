from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CollectedChunk:
    path: str
    text: str
    new_offset: int
    size: int
    inode: int = 0
    missing: bool = False
    bytes_read: int = 0


class Collector(ABC):
    """수집 방법(SSH, 로컬 파일 등)을 갈아끼우기 위한 인터페이스."""

    name: str

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def resolve_paths(self, pattern: str) -> list[str]:
        return [pattern]

    @abstractmethod
    def read_incremental(
        self,
        path: str,
        offset: int,
        max_bytes: int,
        inode: int = 0,
    ) -> CollectedChunk:
        raise NotImplementedError
