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
    if stage not in (1, 2, 3, 4) or not NAME_RE.fullmatch(name or ""):
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
    script: str | None = None,
    system: str = "",
    system_label: str = "",
    label: str = "",
) -> None:
    folder = plugin_folder(stage, name)
    data = _read_raw(folder)
    data["enabled"] = bool(enabled)
    data["targets"] = ["*"] if stage == 4 else list(targets or [])
    if description:
        data["description"] = description
    if stage in (1, 2):
        if system.strip():
            data["system"] = system.strip()
        if system_label.strip():
            data["system_label"] = system_label.strip()
        if label.strip():
            data["label"] = label.strip()
    if rules is not None and data.get("type", "python") == "rules":
        data["rules"] = rules
    if config:
        current = dict(data.get("config") or {})
        current.update(config)
        data["config"] = current
    _dump(folder / "manifest.yaml", data)
    if script is not None and stage == 4:
        write_script(folder, script)


def write_script(folder: Path, script: str) -> Path:
    body = (script or "").replace("\r\n", "\n").strip()
    if not body:
        raise ValueError("수집 스크립트가 비어 있습니다.")
    if not body.startswith("#!"):
        body = "#!/bin/bash\n" + body
    path = folder / "collect.sh"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 원격이 리눅스라 줄바꿈은 항상 LF 로 둔다.
    path.write_bytes((body + "\n").encode("utf-8"))
    return path


def read_script(stage: int, name: str) -> str:
    path = plugin_folder(stage, name) / "collect.sh"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def create_resource_plugin(
    name: str,
    *,
    description: str = "",
    targets: list[str],
    script: str,
    config: dict[str, Any] | None = None,
) -> Path:
    folder = plugin_folder(4, name)
    if (folder / "manifest.yaml").exists():
        raise FileExistsError(f"이미 있는 플러그인입니다: {name}")
    write_script(folder, script)
    payload = {
        "name": name,
        "stage": 4,
        "version": "1.0",
        "type": "resource_script",
        "enabled": True,
        "description": description or f"{name} 리소스 수집",
        "targets": targets or ["*"],
    }
    if config:
        payload["config"] = config
    _dump(folder / "manifest.yaml", payload)
    return folder


def delete_plugin(stage: int, name: str) -> None:
    folder = plugin_folder(stage, name)
    if not (folder / "manifest.yaml").exists():
        raise KeyError(f"플러그인을 찾을 수 없습니다: stage{stage}/{name}")
    for child in sorted(folder.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        else:
            child.rmdir()
    folder.rmdir()


def create_rules_plugin(
    name: str,
    *,
    description: str = "",
    targets: list[str],
    rules: list[dict[str, Any]],
    system: str = "",
    system_label: str = "",
    label: str = "",
    stage: int = 2,
) -> Path:
    if stage not in (1, 2):
        raise ValueError("규칙 플러그인은 1단계 또는 2단계만 만들 수 있습니다.")
    folder = plugin_folder(stage, name)
    if (folder / "manifest.yaml").exists():
        raise FileExistsError(f"이미 있는 플러그인입니다: {name}")
    if stage == 1:
        system_id = system.strip() or name
        system_name = system_label.strip() or system_id
        shown = label.strip() or system_name or name
        desc = description or f"{shown} 공통 시스템 로그를 1단계에서 찾습니다."
    else:
        system_id = system.strip() or "custom"
        system_name = system_label.strip() or ("세부 에러" if system_id == "custom" else "")
        shown = label.strip() or system_name or name
        desc = description or f"{shown} 로그에서 세부 오류를 찾습니다."
    payload = {
        "name": name,
        "stage": stage,
        "version": "1.0",
        "type": "rules",
        "enabled": True,
        "description": desc,
        "targets": list(targets) if targets is not None else [],
        "system": system_id,
        "system_label": system_name or system_id,
        "label": shown,
        "rules": rules or [],
    }
    _dump(folder / "manifest.yaml", payload)
    return folder


def create_report_plugin(
    name: str,
    *,
    description: str = "",
    targets: list[str],
    title: str = "",
    mode: str = "all",
    intro: str = "",
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
                "intro": intro,
            },
        },
    )
    (folder / "plugin.py").write_text(STAGE3_PLUGIN_PY.format(name=name), encoding="utf-8")
    return folder


_LOG_TS = re.compile(r"^\s*\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+")
_LOG_LEVEL = re.compile(r"^\[?(?:DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|TRACE)\]?\s*[:\-]?\s*", re.I)
_LOG_LOGGER = re.compile(r"^(?:\[[^\]]{1,80}\]\s*|\S{1,80}\s+-\s+)")


def phrase_from_log_line(line: str) -> str:
    text = (line or "").strip()
    if not text or text.startswith("#"):
        return ""
    text = _LOG_TS.sub("", text, count=1)
    text = _LOG_LEVEL.sub("", text, count=1)
    text = _LOG_LOGGER.sub("", text, count=1)
    return text.strip()


def _rule_signature(plugin_name: str, phrase: str, index: int) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", phrase).strip("_").lower()[:24]
    if not slug or not re.search(r"[a-zA-Z]", slug):
        return f"{plugin_name}.phrase{index}"
    return f"{plugin_name}.{slug}"


def literal_rules(phrases: list[str], plugin_name: str) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in phrases:
        phrase = (raw or "").strip()
        if len(phrase) < 2:
            continue
        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        index = len(rules) + 1
        rules.append(
            {
                "pattern": re.escape(phrase),
                "severity": "error",
                "signature": _rule_signature(plugin_name, phrase, index),
                "min_count": 1,
            }
        )
    return rules


def rules_from_sample_logs(text: str, plugin_name: str) -> list[dict[str, Any]]:
    phrases = [phrase_from_log_line(line) for line in (text or "").splitlines()]
    return literal_rules(phrases, plugin_name)


def merge_rules(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for rule in group or []:
            pattern = str(rule.get("pattern") or "").strip()
            if not pattern or pattern in seen:
                continue
            seen.add(pattern)
            merged.append(rule)
    return merged


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
