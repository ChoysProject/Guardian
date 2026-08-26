from __future__ import annotations

import json
import logging
from typing import Any, Iterable

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

MAX_SAMPLE_CHARS = 200
MAX_FINDINGS_PER_CALL = 30


def findings_payload(findings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """LLM에는 원본 로그 전체가 아니라 추린 징후만 보낸다."""
    payload = []
    for item in list(findings)[:MAX_FINDINGS_PER_CALL]:
        samples = []
        for line in item.get("sample_lines") or []:
            text = str(line)[:MAX_SAMPLE_CHARS]
            samples.append(text)
        payload.append(
            {
                "host": item.get("host", ""),
                "severity": item.get("severity", ""),
                "signature": item.get("signature", ""),
                "count": item.get("count", 1),
                "plugin": item.get("plugin", ""),
                "sample_lines": samples[:3],
            }
        )
    return payload


def annotate_findings(findings: list[dict[str, Any]]) -> list[str]:
    """Dify 호출. 실패하면 빈 주석을 돌려 규칙 결과를 그대로 보여 준다."""
    if not findings:
        return []
    if not settings.dify.enabled:
        return [""] * len(findings)
    try:
        comments = _call_dify(findings_payload(findings))
        if len(comments) < len(findings):
            comments.extend([""] * (len(findings) - len(comments)))
        return comments[: len(findings)]
    except Exception:
        logger.exception("Dify 호출 실패 — 규칙 결과만 유지합니다.")
        return [""] * len(findings)


def _call_dify(payload: list[dict[str, Any]]) -> list[str]:
    url = settings.dify.base_url.rstrip("/") + "/workflows/run"
    body = {
        "inputs": {settings.dify.input_key: json.dumps(payload, ensure_ascii=False)},
        "response_mode": "blocking",
        "user": settings.dify.user,
    }
    if settings.dify.workflow_id:
        body["workflow_id"] = settings.dify.workflow_id
    headers = {
        "Authorization": f"Bearer {settings.dify.api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=settings.dify.timeout_seconds) as client:
        response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
    return _extract_comments(data, expected=len(payload))


def _extract_comments(data: dict[str, Any], expected: int) -> list[str]:
    outputs = (
        data.get("data", {}).get("outputs")
        or data.get("outputs")
        or {}
    )
    raw = (
        outputs.get("comments")
        or outputs.get("analysis")
        or outputs.get("text")
        or outputs.get("answer")
        or ""
    )
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, dict):
        items = raw.get("items") or raw.get("findings") or []
        if isinstance(items, list):
            return [str(item.get("comment", item)) for item in items]
    text = str(raw).strip()
    if not text:
        return [""] * expected
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return [text] + [""] * (expected - 1)
