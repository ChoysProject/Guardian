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


def _call_dify(payload: list[dict[str, Any]] | dict[str, Any]) -> list[str]:
    url = settings.dify.base_url.rstrip("/") + "/workflows/run"
    expected = len(payload) if isinstance(payload, list) else 1
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
    return _extract_comments(data, expected=expected)


PREFERRED_OUTPUT_KEYS = (
    "comments",
    "analysis",
    "text",
    "answer",
    "output",
    "result",
    "body",
    "content",
    "summary",
)


def _review_json(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if not any(key in value for key in ("summary", "risks", "actions")):
        return ""
    body = {key: value[key] for key in ("summary", "risks", "actions") if key in value}
    if not body:
        return ""
    return json.dumps(body, ensure_ascii=False)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_as_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        packed = _review_json(value)
        if packed:
            return packed
        for key in PREFERRED_OUTPUT_KEYS:
            text = _as_text(value.get(key))
            if text:
                return text
        for key, item in value.items():
            if key in {"files", "usage", "metadata", "error"}:
                continue
            text = _as_text(item)
            if text:
                return text
    return ""


def _extract_comments(data: dict[str, Any], expected: int) -> list[str]:
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    status = inner.get("status") or data.get("status") or ""
    if status and str(status).lower() not in {"succeeded", "success", "ok", ""}:
        logger.warning("Dify 상태가 성공이 아닙니다: %s %s", status, inner.get("error") or "")
    outputs = inner.get("outputs") or data.get("outputs") or {}
    text = ""
    if isinstance(outputs, dict):
        for key in PREFERRED_OUTPUT_KEYS:
            text = _as_text(outputs.get(key))
            if text:
                break
        if not text:
            text = _as_text(outputs)
    else:
        text = _as_text(outputs)
    if not text:
        keys = list(outputs) if isinstance(outputs, dict) else type(outputs).__name__
        logger.warning("Dify 출력을 읽지 못했습니다. outputs 키: %s", keys)
        return [""] * expected
    packed = _review_json(outputs) if isinstance(outputs, dict) else ""
    if packed:
        text = packed
    if text.startswith("[") or text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
            if isinstance(parsed, dict):
                return [json.dumps(parsed, ensure_ascii=False)]
        except json.JSONDecodeError:
            pass
    return [text] + [""] * (expected - 1)
