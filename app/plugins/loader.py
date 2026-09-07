from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import yaml

from app.config import settings
from app.plugins.types import PluginManifest


def _read_manifest(path: Path) -> PluginManifest:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return PluginManifest(
        name=data.get("name") or path.parent.name,
        stage=int(data.get("stage", 2)),
        version=str(data.get("version", "1.0")),
        description=data.get("description", ""),
        plugin_type=data.get("type", "python"),
        targets=list(data.get("targets") or ["*"]),
        enabled=bool(data.get("enabled", True)),
        config=dict(data.get("config") or {}),
        rules=list(data.get("rules") or []),
        path=str(path.parent),
    )


def read_script(manifest: PluginManifest) -> str:
    """스크립트형(리소스 수집) 플러그인이 원격에서 돌릴 셸 내용."""
    path = Path(manifest.path) / "collect.sh"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_manifests(plugin_dir: Path | None = None) -> list[PluginManifest]:
    root = plugin_dir or settings.plugin_path
    if not root.exists():
        return []
    manifests = []
    for manifest_path in sorted(root.glob("**/manifest.yaml")):
        manifests.append(_read_manifest(manifest_path))
    return manifests


def load_python_callable(manifest: PluginManifest, attr: str):
    plugin_py = Path(manifest.path) / "plugin.py"
    if not plugin_py.exists():
        return None
    spec = importlib.util.spec_from_file_location(
        f"guardian_plugin_{manifest.stage}_{manifest.name}",
        plugin_py,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"플러그인을 불러올 수 없습니다: {plugin_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, attr, None)


def targets_match(manifest: PluginManifest, server_name: str) -> bool:
    if not manifest.targets or "*" in manifest.targets:
        return True
    return any(
        server_name == target or re.fullmatch(target, server_name)
        for target in manifest.targets
    )


def apply_yaml_rules(events, manifest: PluginManifest) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for rule in manifest.rules:
        pattern = re.compile(rule.get("pattern", ""), re.IGNORECASE)
        severity = rule.get("severity", "error")
        signature = rule.get("signature") or manifest.name
        min_count = int(rule.get("min_count", 1))
        matched = [event for event in events if pattern.search(event.raw) or pattern.search(event.message)]
        if len(matched) < min_count:
            continue
        samples = [event.raw for event in matched[:5]]
        host = matched[0].host if matched else ""
        occurred = matched[0].occurred_at
        findings.append(
            {
                "severity": severity,
                "signature": signature,
                "count": len(matched),
                "sample_lines": samples,
                "host": host,
                "occurred_at": occurred,
                "plugin": f"stage{manifest.stage}.{manifest.name}",
            }
        )
    return findings
