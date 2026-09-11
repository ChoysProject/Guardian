from __future__ import annotations

import json
import logging
import re
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
    "facts 와 stats 에 있는 숫자만 사용한다. 없는 수치와 없는 항목(네트워크 대역폭, 응답시간 등)은 만들지 않는다. "
    "예시 숫자(75%, 82% 같은 값)를 쓰지 않는다. "
    "마크다운 보고서(### 제목, **굵게**)와 영어 서두(Certainly 등)를 쓰지 않는다. "
    '출력은 {"summary": "두세 문장", "risks": ["..."], "actions": ["..."]} JSON 객체만 낸다. '
    "summary 는 줄바꿈 없이, 실제 수치를 넣은 두세 문장이다. "
    "risks 와 actions 는 각각 최대 3개. 위험 없으면 빈 배열."
)


def review_resources(payload: dict[str, Any]) -> dict[str, Any]:
    """리소스 추이 통계를 LLM에 보내 총평을 받는다. 실패하면 규칙 결과만 남긴다."""
    if not payload:
        return {}
    try:
        if settings.openai.enabled and settings.openai.api_key:
            return _call_openai_resources(payload)
        if settings.dify.enabled:
            comments = _call_dify(_dify_review_input(payload))
            text = "\n".join(item for item in comments if item).strip()
            if not text:
                return {}
            parsed = _parse_review(text)
            if parsed.get("summary") or parsed.get("risks") or parsed.get("actions"):
                return parsed
            return {"summary": text}
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


def _dify_review_input(payload: dict[str, Any]) -> dict[str, Any]:
    cpu = payload.get("cpu") or {}
    mem = payload.get("mem") or {}
    disks = payload.get("disks") or []
    return {
        "task": "resource_review",
        "instruction": RESOURCE_SYSTEM,
        "facts": {
            "server": payload.get("server"),
            "cpu_last_pct": cpu.get("last"),
            "cpu_avg_pct": cpu.get("avg"),
            "cpu_max_pct": cpu.get("max"),
            "mem_last_pct": mem.get("last"),
            "mem_avg_pct": mem.get("avg"),
            "disks": [
                {
                    "mount": item.get("mount"),
                    "used_pct": item.get("last"),
                    "free_gb": item.get("free_gb"),
                }
                for item in disks[:8]
            ],
            "instances": [
                {
                    "name": item.get("name"),
                    "ok": item.get("ok"),
                    "problem": item.get("problem"),
                }
                for item in (payload.get("instances") or [])[:12]
            ],
        },
        "stats": payload,
    }


def _normalize_ai_text(text: str) -> str:
    body = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    body = re.sub(
        r"^(certainly|sure|of course|okay|ok)[^.?!]*[.?!]\s*",
        "",
        body,
        flags=re.I,
    )
    if "\n" not in body and ("###" in body or "**" in body):
        body = re.sub(r"\s*(#{2,4}\s+)", r"\n\n\1", body)
        body = re.sub(r"\s+-\s+", "\n- ", body)
    return body.strip()


def _parse_review(text: str) -> dict[str, Any]:
    if not text:
        return {}
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        body = body.split("\n", 1)[-1] if "\n" in body else body
    parsed: Any = None
    start = body.find("{")
    end = body.rfind("}")
    if start >= 0 and end > start:
        snippet = body[start : end + 1]
        try:
            loaded = json.loads(snippet)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict) and any(
            key in loaded for key in ("summary", "risks", "actions", "text", "answer")
        ):
            parsed = loaded
    if parsed is None:
        return {"summary": _normalize_ai_text(text)}
    if not isinstance(parsed, dict):
        return {"summary": _normalize_ai_text(text)}
    def _lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()][:3]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    return {
        "summary": _normalize_ai_text(
            str(
                parsed.get("summary")
                or parsed.get("text")
                or parsed.get("answer")
                or parsed.get("content")
                or ""
            )
        ),
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
