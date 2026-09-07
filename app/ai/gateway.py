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


RESOURCE_SYSTEM = (
    "서버 리소스 추이 요약을 한국어로 해석한다. "
    "주어진 JSON 통계만 보고, 없는 수치를 지어내지 않는다. "
    "디스크 소진 예상일, 피크 시간대, 인스턴스 재시작·중단처럼 근거가 있는 것만 짚는다. "
    '출력은 {"summary": "두세 문장", "risks": ["..."], "actions": ["..."]} 형태의 JSON 객체만 낸다. '
    "risks 와 actions 는 각각 최대 3개, 한 줄씩 쓴다."
)


def review_resources(payload: dict[str, Any]) -> dict[str, Any]:
    """리소스 추이 통계를 LLM에 보내 총평을 받는다. 실패하면 규칙 결과만 남긴다."""
    if not payload:
        return {}
    try:
        if settings.openai.enabled and settings.openai.api_key:
            return _call_openai_resources(payload)
        if settings.dify.enabled:
            comments = _call_dify([payload])
            text = "\n".join(item for item in comments if item).strip()
            return {"summary": text} if text else {}
        return {}
    except Exception:
        logger.exception("AI 리소스 총평 실패 — 규칙 결과만 유지합니다.")
        return {}


def _call_openai_resources(payload: dict[str, Any]) -> dict[str, Any]:
    url = settings.openai.base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": settings.openai.model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": RESOURCE_SYSTEM},
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
    return _parse_review(text)


def _parse_review(text: str) -> dict[str, Any]:
    if not text:
        return {}
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        body = body.split("\n", 1)[-1] if "\n" in body else body
    start = body.find("{")
    end = body.rfind("}")
    if start >= 0 and end > start:
        body = body[start : end + 1]
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {"summary": text.strip()}
    if not isinstance(parsed, dict):
        return {"summary": text.strip()}
    def _lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()][:3]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    return {
        "summary": str(parsed.get("summary") or "").strip(),
        "risks": _lines(parsed.get("risks")),
        "actions": _lines(parsed.get("actions")),
    }


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
