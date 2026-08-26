from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.models import SessionLocal
from app.pipeline.reports import generate_reports
from app.pipeline.runner import collect_and_analyze

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone=settings.app.timezone)


def _collect_job() -> None:
    db = SessionLocal()
    try:
        collect_and_analyze(db)
    except Exception:
        logger.exception("예약 수집 실패")
    finally:
        db.close()


def _report_job() -> None:
    db = SessionLocal()
    try:
        generate_reports(db, datetime.now(ZoneInfo(settings.app.timezone)))
    except Exception:
        logger.exception("일일 보고서 생성 실패")
    finally:
        db.close()


def start_scheduler() -> None:
    if os.environ.get("GUARDIAN_TESTING") == "1":
        return
    if scheduler.running:
        return
    hour, minute = _parse_hhmm(settings.scheduler.daily_report_time)
    scheduler.add_job(
        _collect_job,
        IntervalTrigger(seconds=max(settings.collect.interval_seconds, 15)),
        id="collect",
        replace_existing=True,
    )
    scheduler.add_job(
        _report_job,
        CronTrigger(hour=hour, minute=minute, timezone=settings.app.timezone),
        id="daily_report",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "스케줄 시작: 수집 %ss, 일일 보고서 %s",
        settings.collect.interval_seconds,
        settings.scheduler.daily_report_time,
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hour_s, minute_s = value.split(":")
        return int(hour_s), int(minute_s)
    except Exception:
        return 18, 0
