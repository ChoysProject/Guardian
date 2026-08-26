from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.ai.dify import _call_dify, findings_payload
from app.config import settings

logger = logging.getLogger(__name__)


def annotate_findings(findings: list[dict[str, Any]]) -> list[str]:
    """추린 징후만 LLM에 보낸다. 실패하면 규칙 결과만 유지한다."""
    if not findings:
        return []
    empty = [""] * len(findings)
    payload = findings_payload(findings)
    try:
        if settings.openai.enabled and settings.openai.api_key:
            comments = _call_openai(payload)
        elif settings.dify.enabled:
            comments = _call_dify(payload)
        else:
            return empty
        if len(comments) < len(findings):
            comments.extend([""] * (len(findings) - len(comments)))
        return comments[: len(findings)]
    except Exception:
        logger.exception("AI 호출 실패 — 규칙 결과만 유지합니다.")
        return empty


def _call_openai(payload: list[dict[str, Any]]) -> list[str]:
    url = settings.openai.base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": settings.openai.model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "서버 로그에서 추린 이상징후를 한국어로 짧게 해석한다. "
                    "원본 로그 전체가 아니라 주어진 JSON만 본다. "
                    "입력 배열과 같은 길이의 JSON 문자열 배열만 출력한다."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.openai.api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=settings.openai.timeout_seconds) as client:
        response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
    text = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    if not text:
        return [""] * len(payload)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return [text] + [""] * (len(payload) - 1)
