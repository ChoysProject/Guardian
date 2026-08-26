from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from app.config import settings
from app.plugins.loader import load_manifests
from app.plugins.types import PluginManifest

NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
STAGE3_PLUGIN_PY = """from app.plugins.report_common import render_standard_report


def render(ctx) -> dict:
    result = render_standard_report(ctx)
    result["plugin"] = "{name}"
    return result
"""


def _root() -> Path:
    return settings.plugin_path.resolve()


def plugin_folder(stage: int, name: str) -> Path:
    if stage not in (2, 3) or not NAME_RE.fullmatch(name or ""):
        raise ValueError("플러그인 이름이 올바르지 않습니다.")
    folder = (_root() / f"stage{stage}" / name).resolve()
    if _root() not in folder.parents:
        raise ValueError("플러그인 경로가 올바르지 않습니다.")
    return folder


def get_manifest(stage: int, name: str) -> PluginManifest:
    for item in load_manifests():
        if item.stage == stage and item.name == name:
            return item
    raise KeyError(f"플러그인을 찾을 수 없습니다: stage{stage}/{name}")


def _dump(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    path.write_text(text, encoding="utf-8")


def _read_raw(folder: Path) -> dict[str, Any]:
    path = folder / "manifest.yaml"
    if not path.exists():
        raise KeyError("manifest.yaml 이 없습니다.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("manifest.yaml 형식이 올바르지 않습니다.")
    return data


def save_plugin(
    stage: int,
    name: str,
    *,
    enabled: bool,
    targets: list[str],
    description: str = "",
    rules: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
) -> None:
    folder = plugin_folder(stage, name)
    data = _read_raw(folder)
    data["enabled"] = bool(enabled)
    data["targets"] = targets or ["*"]
    if description:
        data["description"] = description
    if rules is not None and data.get("type", "python") == "rules":
        data["rules"] = rules
    if config:
        current = dict(data.get("config") or {})
        current.update(config)
        data["config"] = current
    _dump(folder / "manifest.yaml", data)


def create_rules_plugin(
    name: str,
    *,
    description: str = "",
    targets: list[str],
    rules: list[dict[str, Any]],
) -> Path:
    folder = plugin_folder(2, name)
    if (folder / "manifest.yaml").exists():
        raise FileExistsError(f"이미 있는 플러그인입니다: {name}")
    _dump(
        folder / "manifest.yaml",
        {
            "name": name,
            "stage": 2,
            "version": "1.0",
            "type": "rules",
            "enabled": True,
            "description": description or f"{name} 서버 규칙",
            "targets": targets or ["*"],
            "rules": rules or [],
        },
    )
    return folder


def create_report_plugin(
    name: str,
    *,
    description: str = "",
    targets: list[str],
    title: str = "",
    mode: str = "all",
) -> Path:
    folder = plugin_folder(3, name)
    if (folder / "manifest.yaml").exists():
        raise FileExistsError(f"이미 있는 플러그인입니다: {name}")
    _dump(
        folder / "manifest.yaml",
        {
            "name": name,
            "stage": 3,
            "version": "1.0",
            "type": "python",
            "enabled": True,
            "description": description or f"{name} 보고서",
            "targets": targets or ["*"],
            "config": {
                "mode": mode if mode in {"all", "per_server"} else "all",
                "title": title or name,
            },
        },
    )
    (folder / "plugin.py").write_text(STAGE3_PLUGIN_PY.format(name=name), encoding="utf-8")
    return folder


def clean_rules(patterns: list[str], severities: list[str], signatures: list[str], mins: list[str]) -> list[dict[str, Any]]:
    rules = []
    count = max(len(patterns), len(severities), len(signatures), len(mins), 0)
    for i in range(count):
        pattern = (patterns[i] if i < len(patterns) else "").strip()
        if not pattern:
            continue
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"정규식 오류: {pattern} ({exc})") from exc
        severity = (severities[i] if i < len(severities) else "error").strip() or "error"
        if severity not in {"error", "warn", "info", "debug"}:
            severity = "error"
        signature = (signatures[i] if i < len(signatures) else "").strip() or f"rule.{i+1}"
        try:
            min_count = int((mins[i] if i < len(mins) else "1") or 1)
        except ValueError:
            min_count = 1
        rules.append(
            {
                "pattern": pattern,
                "severity": severity,
                "signature": signature,
                "min_count": max(min_count, 1),
            }
        )
    return rules
