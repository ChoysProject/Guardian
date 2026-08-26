from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


DATE_KEYS = ("%Y", "%m", "%d", "%j")
HOUR_KEYS = ("%H",)


def expand_log_patterns(
    patterns: list[str],
    *,
    now: datetime | None = None,
    timezone: str = "Asia/Seoul",
    lookback_hours: int = 48,
) -> list[str]:
    """일자/시간 토큰이 있는 경로를 최근 구간의 실제 경로 패턴으로 펼친다."""
    tz = ZoneInfo(timezone)
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)

    expanded: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        if not pattern:
            continue
        for item in _expand_one(pattern, current, lookback_hours):
            if item not in seen:
                seen.add(item)
                expanded.append(item)
    return expanded


def _expand_one(pattern: str, now: datetime, lookback_hours: int) -> list[str]:
    needs_hour = any(token in pattern for token in HOUR_KEYS)
    needs_day = any(token in pattern for token in DATE_KEYS)
    if not needs_hour and not needs_day:
        return [pattern]

    slots: list[datetime] = []
    hours = max(1, lookback_hours)
    if needs_hour:
        for offset in range(hours):
            slots.append(now - timedelta(hours=offset))
    else:
        seen_days: set = set()
        for offset in range(hours):
            slot = now - timedelta(hours=offset)
            day = slot.date()
            if day in seen_days:
                continue
            seen_days.add(day)
            slots.append(slot)

    results: list[str] = []
    seen: set[str] = set()
    for slot in slots:
        value = slot.strftime(pattern)
        if value not in seen:
            seen.add(value)
            results.append(value)
    return results
