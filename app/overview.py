from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.config import settings


def overview_path():
    return settings.data_path / "overview_review.json"


def build_overview(log_groups: list[dict], resource_groups: list[dict]) -> dict[str, Any]:
    """로그·리소스 카드를 한 판의 전체 현황으로 묶는다."""
    log_rows = _rows(log_groups, "로그")
    res_rows = _rows(resource_groups, "리소스")
    facts = {
        "log_servers": len(log_rows),
        "resource_servers": len(res_rows),
        "log_danger": _names(log_rows, "danger"),
        "log_warn": _names(log_rows, "warn"),
        "log_ok": _names(log_rows, "ok"),
        "resource_danger": _names(res_rows, "danger"),
        "resource_warn": _names(res_rows, "warn"),
        "resource_ok": _names(res_rows, "ok"),
        "log_problems": _problems(log_rows),
        "resource_problems": _problems(res_rows),
    }
    level, status = _level(facts)
    headline = _headline(facts, level)
    story = _story(facts)
    health = _health_mix(log_rows, res_rows)
    charts = {
        "health": health,
        "log": _bar_mix(log_rows),
        "resource": _bar_mix(res_rows),
    }
    return {
        "level": level,
        "status": status,
        "headline": headline,
        "story": story,
        "briefing": _briefing(facts, level, story),
        "log_line": _side_line("로그", facts["log_danger"], facts["log_warn"], facts["log_ok"], facts["log_servers"]),
        "resource_line": _side_line(
            "리소스",
            facts["resource_danger"],
            facts["resource_warn"],
            facts["resource_ok"],
            facts["resource_servers"],
        ),
        "risks": _risks(facts),
        "actions": _actions(facts, level),
        "focus": _focus(log_rows, res_rows),
        "facts": facts,
        "charts": charts,
        "charts_json": json.dumps(charts, ensure_ascii=False).replace("</", "<\\/"),
        "server_names_json": json.dumps(_server_names(log_rows, res_rows), ensure_ascii=False).replace("</", "<\\/"),
        "ai": load_overview_review(),
    }


def load_overview_review() -> dict[str, Any]:
    path = overview_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "summary": str(data.get("summary") or "").strip(),
        "risks": [str(item).strip() for item in (data.get("risks") or []) if str(item).strip()][:3],
        "actions": [str(item).strip() for item in (data.get("actions") or []) if str(item).strip()][:3],
        "at": str(data.get("at") or "").strip(),
    }


def save_overview_review(review: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "summary": str(review.get("summary") or "").strip(),
        "risks": [str(item).strip() for item in (review.get("risks") or []) if str(item).strip()][:3],
        "actions": [str(item).strip() for item in (review.get("actions") or []) if str(item).strip()][:3],
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    overview_path().parent.mkdir(parents=True, exist_ok=True)
    overview_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def review_payload(overview: dict[str, Any]) -> dict[str, Any]:
    facts = overview.get("facts") or {}
    return {
        "kind": "fleet",
        "facts": {
            "headline": overview.get("headline"),
            "level": overview.get("level"),
            "log_danger": facts.get("log_danger") or [],
            "log_warn": facts.get("log_warn") or [],
            "log_ok": facts.get("log_ok") or [],
            "resource_danger": facts.get("resource_danger") or [],
            "resource_warn": facts.get("resource_warn") or [],
            "resource_ok": facts.get("resource_ok") or [],
            "log_problems": (facts.get("log_problems") or [])[:8],
            "resource_problems": (facts.get("resource_problems") or [])[:8],
            "health": {
                "danger": len(set(facts.get("log_danger") or []) | set(facts.get("resource_danger") or [])),
                "warn": len(set(facts.get("log_warn") or []) | set(facts.get("resource_warn") or [])),
                "ok": len(set(facts.get("log_ok") or []) | set(facts.get("resource_ok") or [])),
            },
        },
    }


def _rows(groups: list[dict], kind: str) -> list[dict]:
    rows = []
    for group in groups or []:
        metrics = group.get("metrics") or {}
        name = str(group.get("name") or "").strip()
        if not name:
            continue
        problem = str(metrics.get("problem_text") or metrics.get("verdict") or "").strip()
        if not problem and str(metrics.get("level") or "") in {"warn", "danger"}:
            bits = []
            for cell in metrics.get("cells") or []:
                label = str(cell.get("label") or "").strip()
                value = str(cell.get("value") or "").strip()
                if label and value:
                    bits.append(f"{label} {value}")
            problem = " · ".join(bits[:4])
        rows.append(
            {
                "name": name,
                "kind": kind,
                "server_id": group.get("server_id"),
                "level": str(metrics.get("level") or ""),
                "status": str(metrics.get("status") or ""),
                "verdict": str(metrics.get("verdict") or ""),
                "problem": problem,
            }
        )
    return rows


def _names(rows: list[dict], level: str) -> list[str]:
    return [item["name"] for item in rows if item.get("level") == level]


def _problems(rows: list[dict]) -> list[dict[str, str]]:
    ranked = [item for item in rows if item.get("level") in {"danger", "warn"}]
    ranked.sort(key=lambda item: 0 if item.get("level") == "danger" else 1)
    out = []
    for item in ranked[:6]:
        out.append(
            {
                "server": item["name"],
                "status": item.get("status") or item.get("level") or "",
                "detail": (item.get("problem") or item.get("verdict") or "")[:160],
            }
        )
    return out


def _level(facts: dict[str, Any]) -> tuple[str, str]:
    if facts["log_danger"] or facts["resource_danger"]:
        return "danger", "위험"
    if facts["log_warn"] or facts["resource_warn"]:
        return "warn", "주의"
    if facts["log_ok"] or facts["resource_ok"]:
        return "ok", "여유"
    if facts["log_servers"] or facts["resource_servers"]:
        return "", "대기"
    return "", "대기"


def _headline(facts: dict[str, Any], level: str) -> str:
    if not facts["log_servers"] and not facts["resource_servers"]:
        return "아직 로그나 리소스 수집 대상이 없습니다."
    danger_n = len(facts["log_danger"]) + len(facts["resource_danger"])
    warn_n = len(facts["log_warn"]) + len(facts["resource_warn"])
    if level == "danger":
        names = (facts["resource_danger"] + facts["log_danger"])[:3]
        shown = " · ".join(names)
        extra = danger_n - len(names)
        tail = f" 외 {extra}대" if extra > 0 else ""
        return f"위험 서버 {danger_n}대입니다. {shown}{tail}를 먼저 보세요."
    if level == "warn":
        return f"주의가 필요한 서버가 {warn_n}대입니다. 추이를 봐야 합니다."
    if level == "ok":
        return "등록한 서버는 여유입니다. 로그 징후와 리소스 이상이 없습니다."
    return "아직 수집된 로그·리소스가 없습니다. 수집하면 전체가 한 판으로 보입니다."


def _story(facts: dict[str, Any]) -> str:
    blob = " ".join(
        f"{item.get('server')} {item.get('detail')}"
        for item in (facts.get("log_problems") or []) + (facts.get("resource_problems") or [])
    ).lower()
    web = any(key in blob for key in ("upstream", "timeout", "nginx", "apache", "연결 거부", "connection refused"))
    app = any(key in blob for key in ("hikari", "pool", "bean", "spring", "heap"))
    db = any(key in blob for key in ("postgres", "deadlock", "too many connections", "슬롯", "mysql", "ora-"))
    bits = [name for flag, name in ((web, "웹"), (app, "앱"), (db, "DB")) if flag]
    if len(bits) >= 2:
        return f"{' · '.join(bits)} 징후가 같이 보입니다. 한 경로의 장애로 보는 편이 맞습니다."
    return ""


def _side_line(label: str, danger: list[str], warn: list[str], ok: list[str], total: int) -> str:
    if not total:
        return f"{label} 수집 대상이 없습니다."
    if danger:
        return f"{label} 위험 {len(danger)}대 · {' · '.join(danger[:3])}"
    if warn:
        return f"{label} 주의 {len(warn)}대 · {' · '.join(warn[:3])}"
    if ok:
        return f"{label} {len(ok)}대 여유"
    return f"{label} {total}대 · 아직 수집 전입니다."


def _risks(facts: dict[str, Any]) -> list[str]:
    lines = []
    for item in (facts.get("log_problems") or [])[:3]:
        detail = item.get("detail") or "징후"
        lines.append(f"{item['server']} 로그 · {detail}")
    for item in (facts.get("resource_problems") or [])[:2]:
        detail = item.get("detail") or "상태 이상"
        lines.append(f"{item['server']} 리소스 · {detail}")
    return lines[:4]


def _server_names(log_rows: list[dict], res_rows: list[dict]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in res_rows + log_rows:
        name = str(row.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    names.sort(key=len, reverse=True)
    return names


def _worse(left: str, right: str) -> str:
    rank = {"": 0, "waiting": 0, "ok": 1, "warn": 2, "danger": 3}
    return left if rank.get(left, 0) >= rank.get(right, 0) else right


def _mix_of(rows: list[dict]) -> dict[str, int]:
    mix = {"danger": 0, "warn": 0, "ok": 0, "waiting": 0, "total": len(rows)}
    for row in rows:
        key = row.get("level") if row.get("level") in {"danger", "warn", "ok"} else "waiting"
        mix[key] += 1
    return mix


def _health_mix(log_rows: list[dict], res_rows: list[dict]) -> dict[str, int]:
    by_name: dict[str, str] = {}
    for row in log_rows + res_rows:
        name = row.get("name") or ""
        if not name:
            continue
        by_name[name] = _worse(by_name.get(name, ""), str(row.get("level") or ""))
    mix = {"danger": 0, "warn": 0, "ok": 0, "waiting": 0, "total": len(by_name)}
    for level in by_name.values():
        key = level if level in {"danger", "warn", "ok"} else "waiting"
        mix[key] += 1
    return mix


def _bar_mix(rows: list[dict]) -> dict[str, Any]:
    mix = _mix_of(rows)
    total = mix["total"] or 0
    segs = []
    for key, label in (("danger", "위험"), ("warn", "주의"), ("ok", "여유"), ("waiting", "대기")):
        count = mix[key]
        if not count:
            continue
        segs.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "pct": round(100 * count / total, 1) if total else 0,
            }
        )
    mix["segs"] = segs
    return mix


def _focus(log_rows: list[dict], res_rows: list[dict]) -> list[dict[str, Any]]:
    items = []
    for row in res_rows + log_rows:
        if row.get("level") not in {"danger", "warn"}:
            continue
        kind = row.get("kind") or ""
        sid = row.get("server_id")
        if kind == "리소스":
            href = f"#card-resource-{sid}" if sid else "#section-resources"
        else:
            href = f"#card-log-{sid}" if sid else "#section-logs"
        items.append(
            {
                "server": row["name"],
                "kind": kind,
                "level": row.get("level") or "",
                "status": row.get("status") or row.get("level") or "",
                "detail": (row.get("problem") or row.get("verdict") or "")[:140],
                "href": href,
            }
        )
    items.sort(key=lambda item: 0 if item.get("level") == "danger" else 1)
    return items[:5]


def _briefing(facts: dict[str, Any], level: str, story: str) -> str:
    parts = []
    if story:
        parts.append(story)
    if level == "danger":
        log_names = facts["log_danger"][:2]
        res_names = facts["resource_danger"][:2]
        bits = []
        if res_names:
            bits.append("리소스는 " + ", ".join(res_names))
        if log_names:
            bits.append("로그는 " + ", ".join(log_names))
        if bits:
            parts.append(" · ".join(bits) + "부터 같이 보는 편이 맞습니다.")
    elif level == "warn":
        parts.append("당장 멈춘 것은 아니지만, 추이가 커지기 전에 해당 카드를 열어 보세요.")
    elif level == "ok":
        parts.append("아래 서버 카드는 참고용이고, 지금은 전체가 여유입니다.")
    elif not facts["log_servers"] and not facts["resource_servers"]:
        parts.append("로그 수집 대상과 리소스 수집 대상을 등록하면 전체가 한 판으로 보입니다.")
    else:
        parts.append("수집이 끝나면 위험·주의·여유가 도넛에 채워집니다.")
    return " ".join(part for part in parts if part)


def _actions(facts: dict[str, Any], level: str) -> list[str]:
    if level == "danger":
        first = (facts["log_danger"] or facts["resource_danger"] or [""])[0]
        return [
            f"{first} 징후와 리소스 카드를 먼저 연다" if first else "위험 서버 카드를 연다",
            "로그 분석 보고서에서 해당 서버 보고서를 만든다",
        ]
    if level == "warn":
        return ["주의 서버의 추이를 감시 현황에서 다시 본다"]
    if facts["log_servers"] or facts["resource_servers"]:
        return ["이상 징후가 생기면 이 칸의 상태가 위험으로 바뀝니다"]
    return ["로그 수집 대상 서버와 리소스 수집 대상 서버를 등록하세요"]
