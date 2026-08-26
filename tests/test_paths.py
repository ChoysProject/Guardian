from datetime import datetime
from zoneinfo import ZoneInfo

from app.collectors.local import LocalTailCollector
from app.collectors.paths import expand_log_patterns


def test_expand_daily_and_hourly_patterns():
    now = datetime(2026, 8, 26, 10, 15, tzinfo=ZoneInfo("Asia/Seoul"))
    daily = expand_log_patterns(
        ["/var/log/app/%Y-%m-%d/*.log"],
        now=now,
        lookback_hours=48,
    )
    assert "/var/log/app/2026-08-26/*.log" in daily
    assert "/var/log/app/2026-08-25/*.log" in daily
    assert "/var/log/app/2026-08-24/*.log" in daily

    hourly = expand_log_patterns(
        ["/var/log/app/%Y-%m-%d/%H.log"],
        now=now,
        lookback_hours=3,
    )
    assert "/var/log/app/2026-08-26/10.log" in hourly
    assert "/var/log/app/2026-08-26/09.log" in hourly
    assert "/var/log/app/2026-08-26/08.log" in hourly
    assert len(hourly) == 3


def test_plain_path_is_unchanged():
    assert expand_log_patterns(["/var/log/syslog"]) == ["/var/log/syslog"]


def test_local_glob_and_checkpoint(tmp_path):
    day = tmp_path / "2026-08-26"
    day.mkdir()
    (day / "app-01.log").write_text("ERROR one\n", encoding="utf-8")
    (day / "app-02.log").write_text("ERROR two\n", encoding="utf-8")
    collector = LocalTailCollector()
    paths = collector.resolve_paths(str(day / "*.log"))
    assert len(paths) == 2
    first = collector.read_incremental(paths[0], 0, 1024)
    second = collector.read_incremental(paths[0], first.new_offset, 1024)
    assert second.text == ""
    assert second.new_offset == first.new_offset
