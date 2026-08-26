from __future__ import annotations

import logging
from typing import Any

from app.plugins.loader import apply_yaml_rules, load_manifests, load_python_callable, targets_match
from app.plugins.types import PluginContext, PluginManifest
from app.pipeline.normalize import NormalizedEvent

logger = logging.getLogger(__name__)


def run_stage1(server_name: str, host: str, events: list[NormalizedEvent]) -> list[dict[str, Any]]:
    return _run_stage(1, server_name, host, events)


def run_stage2(server_name: str, host: str, events: list[NormalizedEvent]) -> list[dict[str, Any]]:
    return _run_stage(2, server_name, host, events)


def _run_stage(stage: int, server_name: str, host: str, events: list[NormalizedEvent]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for manifest in load_manifests():
        if manifest.stage != stage or not manifest.enabled or not targets_match(manifest, server_name):
            continue
        try:
            findings.extend(_run_analyzer(manifest, server_name, host, events))
        except Exception:
            logger.exception("Stage%s 플러그인 실패: %s", stage, manifest.name)
    return findings


def run_stage3(ctx: PluginContext, names: list[str] | None = None) -> list[dict[str, Any]]:
    wanted = {item for item in (names or []) if item}
    reports: list[dict[str, Any]] = []
    all_findings = list(ctx.findings or [])
    for manifest in load_manifests():
        if manifest.stage != 3 or not manifest.enabled:
            continue
        if wanted and manifest.name not in wanted:
            continue
        try:
            reports.extend(_run_stage3_manifest(manifest, ctx, all_findings))
        except Exception:
            logger.exception("Stage3 플러그인 실패: %s", manifest.name)
    return [item for item in reports if item]


GLOBAL_STAGE3 = {"daily_report", "server_report"}


def assigned_plugins(server_name: str, stage: int | None = None) -> list[PluginManifest]:
    items = []
    for manifest in load_manifests():
        if not manifest.enabled:
            continue
        if stage is not None and manifest.stage != stage:
            continue
        if manifest.stage == 1:
            continue
        if manifest.stage == 3 and manifest.name in GLOBAL_STAGE3:
            continue
        if not manifest.targets or "*" in manifest.targets:
            continue
        if targets_match(manifest, server_name):
            items.append(manifest)
    return items


def _run_stage3_manifest(manifest: PluginManifest, ctx: PluginContext, all_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mode = str((manifest.config or {}).get("mode") or "all")
    if mode == "per_server":
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in all_findings:
            name = str(item.get("server") or item.get("host") or "-")
            if not targets_match(manifest, name):
                continue
            grouped.setdefault(name, []).append(item)
        rendered = []
        for server_name, items in grouped.items():
            sub = PluginContext(
                server_name=server_name,
                host=server_name,
                events=ctx.events,
                config={**manifest.config, **ctx.config, "server_name": server_name},
                period_start=ctx.period_start,
                period_end=ctx.period_end,
                findings=items,
            )
            result = _run_reporter(manifest, sub)
            if result:
                result["plugin"] = f"{manifest.name}:{server_name}"
                rendered.append(result)
        return rendered

    filtered = [
        item
        for item in all_findings
        if targets_match(manifest, str(item.get("server") or item.get("host") or ""))
    ]
    if not filtered and manifest.targets and "*" not in manifest.targets:
        return []
    sub = PluginContext(
        server_name=ctx.server_name,
        host=ctx.host,
        events=ctx.events,
        config={**manifest.config, **ctx.config},
        period_start=ctx.period_start,
        period_end=ctx.period_end,
        findings=filtered,
    )
    result = _run_reporter(manifest, sub)
    return [result] if result else []


def _run_analyzer(
    manifest: PluginManifest,
    server_name: str,
    host: str,
    events: list[NormalizedEvent],
) -> list[dict[str, Any]]:
    if manifest.plugin_type == "rules":
        return apply_yaml_rules(events, manifest)
    analyze = load_python_callable(manifest, "analyze")
    if analyze is None:
        return []
    ctx = PluginContext(
        server_name=server_name,
        host=host,
        events=events,
        config=manifest.config,
    )
    result = analyze(ctx)
    for item in result:
        item.setdefault("plugin", f"stage{manifest.stage}.{manifest.name}")
        item.setdefault("host", host)
    return result


def _run_reporter(manifest: PluginManifest, ctx: PluginContext) -> dict[str, Any]:
    render = load_python_callable(manifest, "render")
    if render is None:
        return {}
    ctx.config = {**manifest.config, **ctx.config}
    result = render(ctx)
    result.setdefault("plugin", manifest.name)
    return result
