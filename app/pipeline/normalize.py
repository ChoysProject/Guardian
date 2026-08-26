from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

LEVEL_ALIASES = {
    "ERR": "error",
    "ERROR": "error",
    "FATAL": "error",
    "CRIT": "error",
    "CRITICAL": "error",
    "WARN": "warn",
    "WARNING": "warn",
    "INFO": "info",
    "DEBUG": "debug",
    "TRACE": "debug",
}

LEVEL_RE = re.compile(
    r"\b(ERROR|ERR|FATAL|CRITICAL|CRIT|WARN|WARNING|INFO|DEBUG|TRACE)\b",
    re.IGNORECASE,
)
ISO_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
    r"(?:\s+(?P<level>[A-Z]+))?"
    r"(?:\s+\[(?P<proc>[^\]]+)\])?"
    r"\s+(?P<msg>.*)$"
)
SYSLOG_RE = re.compile(
    r"^(?P<ts>\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<proc>\S+?)(?:\[(?P<pid>\d+)\])?:\s+"
    r"(?P<msg>.*)$"
)
BRACKET_LEVEL_RE = re.compile(r"^\[(?P<level>[A-Za-z]+)\]\s*(?P<msg>.*)$")

IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
NUM_RE = re.compile(r"\b\d+\b")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")


@dataclass
class NormalizedEvent:
    raw: str
    message: str
    level: str = "info"
    host: str = ""
    process_name: str = ""
    occurred_at: datetime | None = None
    signature: str = ""
    extra: dict = field(default_factory=dict)


def canonicalize_level(value: str | None) -> str | None:
    if not value:
        return None
    return LEVEL_ALIASES.get(value.upper())


def make_signature(message: str) -> str:
    text = UUID_RE.sub("<uuid>", message)
    text = HEX_RE.sub("<hex>", text)
    text = IP_RE.sub("<ip>", text)
    text = NUM_RE.sub("<n>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:480]


def _parse_iso(ts: str) -> datetime | None:
    raw = ts.replace("Z", "+00:00")
    if re.match(r".*[+-]\d{4}$", raw):
        raw = raw[:-5] + raw[-5:-2] + ":" + raw[-2:]
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_syslog_ts(ts: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.utcnow()
    try:
        parsed = datetime.strptime(f"{now.year} {ts}", "%Y %b %d %H:%M:%S")
    except ValueError:
        return None
    return parsed


def parse_line(line: str, default_host: str = "") -> NormalizedEvent | None:
    raw = line.rstrip("\r\n")
    if not raw.strip():
        return None

    host = default_host
    process_name = ""
    message = raw
    occurred_at = None
    level = None

    iso = ISO_RE.match(raw)
    syslog = SYSLOG_RE.match(raw)
    if iso:
        occurred_at = _parse_iso(iso.group("ts"))
        level = canonicalize_level(iso.group("level"))
        process_name = iso.group("proc") or ""
        message = iso.group("msg")
    elif syslog:
        occurred_at = _parse_syslog_ts(syslog.group("ts"))
        host = syslog.group("host") or default_host
        process_name = syslog.group("proc") or ""
        message = syslog.group("msg")

    bracket = BRACKET_LEVEL_RE.match(message)
    if bracket and not level:
        level = canonicalize_level(bracket.group("level"))
        message = bracket.group("msg")

    if not level:
        found = LEVEL_RE.search(raw)
        level = canonicalize_level(found.group(1)) if found else "info"

    return NormalizedEvent(
        raw=raw,
        message=message.strip(),
        level=level or "info",
        host=host,
        process_name=process_name,
        occurred_at=occurred_at,
        signature=make_signature(message.strip()),
    )


def parse_text(text: str, default_host: str = "") -> list[NormalizedEvent]:
    events: list[NormalizedEvent] = []
    for line in text.splitlines():
        event = parse_line(line, default_host=default_host)
        if event:
            events.append(event)
    return events


def iter_levels(events: Iterable[NormalizedEvent], *levels: str) -> list[NormalizedEvent]:
    wanted = {item.lower() for item in levels}
    return [event for event in events if event.level in wanted]
