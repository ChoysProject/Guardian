from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    collector_type: Mapped[str] = mapped_column(String(32), default="ssh")
    host: Mapped[str] = mapped_column(String(256), default="")
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(128), default="")
    key_path: Mapped[str] = mapped_column(String(512), default="")
    log_paths: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_collect_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CollectCursor(Base):
    __tablename__ = "collect_cursors"
    __table_args__ = (UniqueConstraint("server_id", "log_path", name="uq_cursor"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    log_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    offset: Mapped[int] = mapped_column(Integer, default=0)
    size: Mapped[int] = mapped_column(Integer, default=0)
    inode: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LogEvent(Base):
    __tablename__ = "log_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[int] = mapped_column(Integer, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    host: Mapped[str] = mapped_column(String(256), default="")
    level: Mapped[str] = mapped_column(String(16), default="info", index=True)
    process_name: Mapped[str] = mapped_column(String(128), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    raw: Mapped[str] = mapped_column(Text, default="")
    signature: Mapped[str] = mapped_column(String(512), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint(
            "server_id", "plugin", "signature", "severity", "bucket",
            name="uq_finding_bucket",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[int] = mapped_column(Integer, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    host: Mapped[str] = mapped_column(String(256), default="")
    severity: Mapped[str] = mapped_column(String(16), default="error", index=True)
    signature: Mapped[str] = mapped_column(String(512), default="")
    sample_lines: Mapped[str] = mapped_column(Text, default="[]")
    count: Mapped[int] = mapped_column(Integer, default=1)
    plugin: Mapped[str] = mapped_column(String(128), default="stage1.common")
    ai_comment: Mapped[str] = mapped_column(Text, default="")
    bucket: Mapped[str] = mapped_column(String(16), default="")  # YYYY-MM-DD
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plugin: Mapped[str] = mapped_column(String(128), default="daily_report")
    title: Mapped[str] = mapped_column(String(256), default="")
    period_start: Mapped[datetime] = mapped_column(DateTime)
    period_end: Mapped[datetime] = mapped_column(DateTime)
    markdown_path: Mapped[str] = mapped_column(String(1024), default="")
    html_path: Mapped[str] = mapped_column(String(1024), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CollectRun(Base):
    __tablename__ = "collect_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    servers: Mapped[int] = mapped_column(Integer, default=0)
    lines: Mapped[int] = mapped_column(Integer, default=0)
    findings: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")


def _sqlite_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def make_engine(url: str | None = None):
    db_url = url or settings.database.url
    return create_engine(db_url, future=True, connect_args=_sqlite_connect_args(db_url))


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    from sqlalchemy import inspect, text

    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.reports_path.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    if inspector.has_table("collect_cursors"):
        columns = {col["name"] for col in inspector.get_columns("collect_cursors")}
        if "inode" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE collect_cursors ADD COLUMN inode INTEGER DEFAULT 0"))
