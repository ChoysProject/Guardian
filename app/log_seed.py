from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import settings
from app.db import dump_json, parse_json_list
from app.demo_logs import extra_lines_for
from app.models import Server

TEST_DIR_NAME = "GuardianTestLogs"
TEST_FILE_NAME = "guardian-test.log"


def test_log_relative_path(server_name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in (server_name or "server"))
    return str(Path(TEST_DIR_NAME) / safe / TEST_FILE_NAME)


def sample_log_text(server_name: str, when: datetime | None = None, systems: list[str] | None = None) -> str:
    """공통 규칙이 잡을 시험 로그."""
    tz = ZoneInfo(settings.app.timezone)
    now = when or datetime.now(tz)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    syslog = f"{months[now.month - 1]} {now.day:2d} {now.strftime('%H:%M:%S')}"
    host = server_name or "guardian-test"
    lines = [
        f"{stamp} INFO [api] Guardian test log seed started",
        f"{stamp} INFO [api] health check ok",
    ]
    for idx in range(8):
        lines.append(f"{stamp} ERROR [worker] Connection refused to 10.0.0.12:5432 try={idx}")
    lines.extend(extra_lines_for("auth_failures", stamp, syslog, host))
    lines.extend(extra_lines_for("disk_full", stamp, syslog, host))
    for name in systems or []:
        lines.extend(extra_lines_for(name, stamp, syslog, host))
    lines.append(f"{stamp} INFO [batch] guardian test log seed finished")
    return "\n".join(lines) + "\n"


def attach_log_path(server: Server, path: str) -> bool:
    """로그 경로에 시험 파일을 넣고, 새로 넣었으면 True."""
    current = parse_json_list(server.log_paths)
    if path in current:
        return False
    current.append(path)
    server.log_paths = dump_json(current)
    return True


def write_local_test_log(server: Server, text: str) -> str:
    relative = test_log_relative_path(server.name)
    path = settings.data_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)
    stored = str(path)
    attach_log_path(server, stored)
    return stored


def write_remote_test_log(server: Server, text: str) -> str:
    from app.resource_collect import _connect

    client = _connect(server)
    try:
        _stdin, stdout, _stderr = client.exec_command('printf %s "$HOME"')
        home = stdout.read().decode("utf-8", errors="replace").strip() or "/tmp"
        remote_dir = f"{home}/{TEST_DIR_NAME}"
        remote_path = f"{remote_dir}/{TEST_FILE_NAME}"
        stdin, stdout, stderr = client.exec_command(f'mkdir -p "{remote_dir}" && cat >> "{remote_path}"')
        stdin.write(text)
        stdin.channel.shutdown_write()
        code = stdout.channel.recv_exit_status()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if code != 0:
            raise ValueError(err or f"시험 로그를 쓰지 못했습니다 (exit {code})")
    finally:
        client.close()
    attach_log_path(server, remote_path)
    return remote_path


def seed_test_logs(server: Server, when: datetime | None = None) -> str:
    text = sample_log_text(
        server.name,
        when=when,
        systems=parse_json_list(getattr(server, "log_plugins", "") or ""),
    )
    if (server.collector_type or "ssh") == "local":
        return write_local_test_log(server, text)
    return write_remote_test_log(server, text)
