from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent.parent


class AppSettings(BaseModel):
    name: str = "Goodmorning Check"
    host: str = "127.0.0.1"
    port: int = 8080
    data_dir: str = "data"
    timezone: str = "Asia/Seoul"
    seed_demo: bool = True


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
