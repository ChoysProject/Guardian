from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent.parent


class AppSettings(BaseModel):
    name: str = "Guardian"
    host: str = "127.0.0.1"
    port: int = 8080
    data_dir: str = "data"
    timezone: str = "Asia/Seoul"
    seed_demo: bool = False


class DatabaseSettings(BaseModel):
    url: str = "sqlite:///data/guardian.db"


class AuthSettings(BaseModel):
    enabled: bool = False
    username: str = "admin"
    password: str = "changeme"


class CollectSettings(BaseModel):
    interval_seconds: int = 60
    ssh_timeout_seconds: int = 20
    max_bytes_per_file: int = 1_048_576
    max_bytes_per_server: int = 8_388_608
    lookback_hours: int = 48
    persist_raw_events: bool = False


class OpenAISettings(BaseModel):
    enabled: bool = False
    api_key: str = ""
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 30


class DifySettings(BaseModel):
    enabled: bool = False
    base_url: str = "http://dify.internal/v1"
    api_key: str = ""
    workflow_id: str = ""
    user: str = "guardian"
    timeout_seconds: int = 30
    input_key: str = "findings_json"


class SchedulerSettings(BaseModel):
    daily_report_time: str = "18:00"


class PluginSettings(BaseModel):
    dir: str = "plugins"


class RetentionSettings(BaseModel):
    log_event_days: int = 7


class Settings(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    collect: CollectSettings = Field(default_factory=CollectSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    dify: DifySettings = Field(default_factory=DifySettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    plugins: PluginSettings = Field(default_factory=PluginSettings)
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    config_path: Path = ROOT / "config.yaml"

    @property
    def data_path(self) -> Path:
        path = Path(self.app.data_dir)
        if not path.is_absolute():
            path = ROOT / path
        return path

    @property
    def plugin_path(self) -> Path:
        path = Path(self.plugins.dir)
        if not path.is_absolute():
            path = ROOT / path
        return path

    @property
    def reports_path(self) -> Path:
        return self.data_path / "reports"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"설정 파일이 객체가 아닙니다: {path}")
    return data


def load_settings(config_path: Path | None = None) -> Settings:
    import os

    path = config_path or Path(os.environ.get("GUARDIAN_CONFIG", ROOT / "config.yaml"))
    if not path.exists():
        path = ROOT / "config.example.yaml"
    data = _read_yaml(path)
    settings = Settings.model_validate(data)
    settings.config_path = path
    if not settings.openai.api_key:
        settings.openai.api_key = os.environ.get("OPENAI_API_KEY", "")
    return settings


settings = load_settings()

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$")


def _normalize_report_time(value: str) -> str:
    text = (value or "").strip()
    if not _TIME_RE.match(text):
        raise ValueError("일일 보고서 시각은 HH:MM 형식입니다.")
    hour_s, minute_s = text.split(":")[:2]
    hour = int(hour_s)
    minute = int(minute_s)
    if hour > 23 or minute > 59:
        raise ValueError("일일 보고서 시각은 HH:MM 형식입니다.")
    return f"{hour:02d}:{minute:02d}"


def update_runtime_settings(interval_seconds: int | str, daily_report_time: str) -> None:
    try:
        interval = int(interval_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("수집 주기는 초 단위 숫자입니다.") from exc
    if interval < 15 or interval > 86400:
        raise ValueError("수집 주기는 15초에서 86400초 사이입니다.")
    time_s = _normalize_report_time(daily_report_time)
    path = settings.config_path
    data = _read_yaml(path) if path.exists() else {}
    if not isinstance(data, dict):
        data = {}
    collect = data.get("collect")
    if not isinstance(collect, dict):
        collect = {}
        data["collect"] = collect
    collect["interval_seconds"] = interval
    sched = data.get("scheduler")
    if not isinstance(sched, dict):
        sched = {}
        data["scheduler"] = sched
    sched["daily_report_time"] = time_s
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
    except OSError as exc:
        raise ValueError("설정 파일을 저장하지 못했습니다.") from exc
    settings.collect.interval_seconds = interval
    settings.scheduler.daily_report_time = time_s
