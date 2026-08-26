from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.pipeline.normalize import NormalizedEvent


@dataclass
class PluginManifest:
    name: str
    stage: int
    version: str = "1.0"
    description: str = ""
    plugin_type: str = "python"  # python | rules
    targets: list[str] = field(default_factory=lambda: ["*"])
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    rules: list[dict[str, Any]] = field(default_factory=list)
    path: str = ""


@dataclass
class PluginContext:
    server_name: str
    host: str
    events: list[NormalizedEvent]
    config: dict[str, Any]
    period_start: datetime | None = None
    period_end: datetime | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)


class AnalyzerPlugin(Protocol):
    def analyze(self, ctx: PluginContext) -> list[dict[str, Any]]:
        ...


class ReportPlugin(Protocol):
    def render(self, ctx: PluginContext) -> dict[str, Any]:
        ...
