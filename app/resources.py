from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings

RESOURCE_PLUGIN = "resource_report"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SERVER_RE = re.compile(r"^[A-Za-z0-9._-]+$")
OK_VALUES = {"ok", "up", "running", "true", "1", "yes", "on"}

SAMPLE_JSON = {
    "server": "eai-01",
    "date": "2026-09-01",
    "cpu": {"usage_pct": 23.5},
    "mem": {"used_pct": 61.2, "used_mb": 4980, "total_mb": 8192},
    "disk": [
        {"mount": "/", "used_pct": 72.0},
        {"mount": "/data", "used_pct": 41.0},
    ],
    "instances": [
        {"name": "was", "ok": True},
        {"name": "mq", "ok": True, "detail": "pid 2201"},
    ],
}


def resources_root() -> Path:
    path = settings.data_path / "resources"
    path.mkdir(parents=True, exist_ok=True)
    return path


def today_stamp(when: datetime | None = None) -> str:
    tz = ZoneInfo(settings.app.timezone)
    now = when or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    return now.strftime("%Y-%m-%d")


def is_resource_plugin(plugin: str | None) -> bool:
    return str(plugin or "").startswith(RESOURCE_PLUGIN)


def _safe_server(name: str) -> str:
    text = re.sub(r"[^\w.-]+", "_", (name or "").strip()).strip("._")
    if not text or not SERVER_RE.fullmatch(text):
        raise ValueError("서버 이름이 올바르지 않습니다.")
    return text


def _valid_date(value: str) -> str:
    text = (value or "").strip()
    if not DATE_RE.fullmatch(text):
        raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
    datetime.strptime(text, "%Y-%m-%d")
    return text


def snapshot_path(server: str, date: str) -> Path:
    return resources_root() / _safe_server(server) / f"{_valid_date(date)}.json"


def _as_pct(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        for key in ("usage_pct", "used_pct", "pct", "percent"):
            if key in value:
                return _as_pct(value.get(key))
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return round(number, 1)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in OK_VALUES


def _parse_disk(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict):
                mount = str(row.get("mount") or row.get("path") or row.get("name") or "/").strip() or "/"
                pct = _as_pct(row.get("used_pct", row.get("usage_pct", row.get("pct"))))
                items.append({"mount": mount, "used_pct": pct})
            else:
                items.append({"mount": "/", "used_pct": _as_pct(row)})
    elif isinstance(raw, dict):
        if "used_pct" in raw or "usage_pct" in raw or "mount" in raw:
            items.append(
                {
                    "mount": str(raw.get("mount") or "/"),
                    "used_pct": _as_pct(raw.get("used_pct", raw.get("usage_pct"))),
                }
            )
        else:
            for mount, value in raw.items():
                items.append({"mount": str(mount), "used_pct": _as_pct(value)})
    elif raw is not None and raw != "":
        items.append({"mount": "/", "used_pct": _as_pct(raw)})
    return [item for item in items if item.get("used_pct") is not None or item.get("mount")]


def _parse_instances(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict):
                name = str(row.get("name") or row.get("instance") or "").strip()
                if not name:
                    continue
                ok = row.get("ok")
                if ok is None:
                    ok = row.get("status", row.get("state", True))
                items.append({"name": name, "ok": _as_bool(ok), "detail": str(row.get("detail") or "")})
            elif isinstance(row, str) and row.strip():
                items.append({"name": row.strip(), "ok": True, "detail": ""})
    elif isinstance(raw, dict):
        for name, value in raw.items():
            if isinstance(value, dict):
                ok = value.get("ok", value.get("status", True))
                items.append({"name": str(name), "ok": _as_bool(ok), "detail": str(value.get("detail") or "")})
            else:
                items.append({"name": str(name), "ok": _as_bool(value), "detail": ""})
    return items


def normalize_snapshot(
    raw: dict[str, Any],
    *,
    fallback_server: str = "",
    fallback_date: str = "",
) -> dict[str, Any]:
    server = str(raw.get("server") or raw.get("host") or fallback_server).strip()
    date = str(raw.get("date") or raw.get("day") or fallback_date).strip()
    cpu_raw = raw.get("cpu")
    mem_raw = raw.get("mem") if "mem" in raw else raw.get("memory")
    cpu_pct = _as_pct(cpu_raw)
    mem_pct = _as_pct(mem_raw)
    mem_used = None
    mem_total = None
    if isinstance(mem_raw, dict):
        try:
            mem_used = float(mem_raw["used_mb"]) if mem_raw.get("used_mb") is not None else None
        except (TypeError, ValueError):
            mem_used = None
        try:
            mem_total = float(mem_raw["total_mb"]) if mem_raw.get("total_mb") is not None else None
        except (TypeError, ValueError):
            mem_total = None
    snapshot = {
        "server": _safe_server(server),
        "date": _valid_date(date),
        "cpu": {"usage_pct": cpu_pct},
        "mem": {"used_pct": mem_pct, "used_mb": mem_used, "total_mb": mem_total},
        "disk": _parse_disk(raw.get("disk") if "disk" in raw else raw.get("disks")),
        "instances": _parse_instances(raw.get("instances") if "instances" in raw else raw.get("instance")),
    }
    extra = raw.get("extra")
    if isinstance(extra, dict):
        snapshot["extra"] = extra
    return snapshot


def parse_payload(text: str, *, fallback_server: str = "", fallback_date: str = "") -> list[dict[str, Any]]:
    raw_text = (text or "").strip()
    if not raw_text:
        raise ValueError("넣을 데이터가 없습니다.")
    try:
        loaded = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 형식이 아닙니다: {exc}") from exc
    rows: list[Any]
    if isinstance(loaded, list):
        rows = loaded
    elif isinstance(loaded, dict):
        if isinstance(loaded.get("snapshots"), list):
            rows = loaded["snapshots"]
        else:
            rows = [loaded]
    else:
        raise ValueError("JSON 객체 또는 배열이어야 합니다.")
    snapshots = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("각 항목은 JSON 객체여야 합니다.")
        snapshots.append(
            normalize_snapshot(row, fallback_server=fallback_server, fallback_date=fallback_date)
        )
    return snapshots


def save_snapshot(snapshot: dict[str, Any]) -> Path:
    path = snapshot_path(snapshot["server"], snapshot["date"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_snapshot(server: str, date: str) -> dict[str, Any] | None:
    path = snapshot_path(server, date)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def delete_snapshot(server: str, date: str) -> bool:
    path = snapshot_path(server, date)
    if not path.exists():
        return False
    path.unlink()
    return True


def list_snapshots() -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    root = resources_root()
    for path in sorted(root.glob("*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        server = str(data.get("server") or path.parent.name)
        grouped.setdefault(server, []).append(data)
    rows = []
    for server, items in sorted(grouped.items()):
        items.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
        rows.append({"server": server, "snapshots": items, "count": len(items)})
    return rows


def snapshots_for(server: str, *, days: int = 7, end: str | None = None) -> list[dict[str, Any]]:
    last = end or today_stamp()
    last_day = datetime.strptime(last, "%Y-%m-%d")
    wanted = {
        (last_day - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(max(days, 1))
    }
    found = []
    for date in sorted(wanted):
        item = load_snapshot(server, date)
        if item:
            found.append(item)
    return found


def _series(values: list[float | None]) -> list[float]:
    return [item for item in values if item is not None]


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _direction(values: list[float]) -> str:
    if len(values) < 2:
        return "데이터 부족"
    delta = values[-1] - values[0]
    if delta >= 3:
        return "상승"
    if delta <= -3:
        return "하락"
    return "유지"


def analyze_server(server: str, *, days: int = 7, end: str | None = None) -> dict[str, Any]:
    items = snapshots_for(server, days=days, end=end)
    cpu = _series([((item.get("cpu") or {}).get("usage_pct")) for item in items])
    mem = _series([((item.get("mem") or {}).get("used_pct")) for item in items])
    disk_rows: dict[str, list[float]] = {}
    instance_fail: dict[str, list[str]] = {}
    for item in items:
        date = str(item.get("date") or "")
        for disk in item.get("disk") or []:
            mount = str(disk.get("mount") or "/")
            pct = disk.get("used_pct")
            if pct is None:
                continue
            disk_rows.setdefault(mount, []).append(float(pct))
        for inst in item.get("instances") or []:
            name = str(inst.get("name") or "")
            if name and not inst.get("ok"):
                instance_fail.setdefault(name, []).append(date)
    disks = []
    for mount, values in sorted(disk_rows.items()):
        disks.append(
            {
                "mount": mount,
                "avg": _avg(values),
                "max": max(values) if values else None,
                "last": values[-1] if values else None,
                "direction": _direction(values),
            }
        )
    return {
        "server": server,
        "days": days,
        "count": len(items),
        "dates": [str(item.get("date") or "") for item in items],
        "cpu": {
            "avg": _avg(cpu),
            "max": max(cpu) if cpu else None,
            "last": cpu[-1] if cpu else None,
            "direction": _direction(cpu),
            "series": cpu,
        },
        "mem": {
            "avg": _avg(mem),
            "max": max(mem) if mem else None,
            "last": mem[-1] if mem else None,
            "direction": _direction(mem),
            "series": mem,
        },
        "disks": disks,
        "instance_fail": instance_fail,
        "items": items,
    }


def _fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value}%"


def snapshot_server_names() -> list[str]:
    return [row["server"] for row in list_snapshots()]


def generate_resource_reports(
    db,
    server_names: list[str] | None = None,
    *,
    days: int = 7,
    when: datetime | None = None,
):
    from app.models import Report
    from app.pipeline.reports import _store_report

    window = max(int(days or 7), 1)
    end = today_stamp(when)
    start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=window - 1)).strftime("%Y-%m-%d")
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
    names = [item for item in (server_names or []) if item]
    if not names:
        names = snapshot_server_names()
    created: list[Report] = []
    settings.reports_path.mkdir(parents=True, exist_ok=True)
    for server in names:
        analysis = analyze_server(server, days=window, end=end)
        if not analysis["count"]:
            continue
        rendered = render_resource_report(analysis, start=start, end=end)
        created.append(_store_report(db, rendered, start_dt, end_dt, end))
    db.commit()
    for report in created:
        db.refresh(report)
    return created


def render_resource_report(analysis: dict[str, Any], *, start: str, end: str) -> dict[str, Any]:
    server = analysis["server"]
    title = f"{server} 리소스 추이 보고서"
    dates = analysis.get("dates") or []
    cpu = analysis.get("cpu") or {}
    mem = analysis.get("mem") or {}
    fail = analysis.get("instance_fail") or {}
    summary_bits = [
        f"자료 {analysis.get('count') or 0}일",
        f"CPU {_fmt_pct(cpu.get('last'))} ({cpu.get('direction') or '-'})",
        f"MEM {_fmt_pct(mem.get('last'))} ({mem.get('direction') or '-'})",
    ]
    if fail:
        summary_bits.append(f"인스턴스 이상 {len(fail)}종")
    summary = ", ".join(summary_bits)

    md = [
        f"# {title}",
        "",
        f"- 기간: {start} ~ {end}",
        f"- 대상: {server}",
        f"- 요약: {summary}",
        f"- 있는 날짜: {', '.join(dates) if dates else '없음'}",
        "",
        "## CPU / MEM",
        "",
        f"- CPU 평균 {_fmt_pct(cpu.get('avg'))}, 최대 {_fmt_pct(cpu.get('max'))}, 최근 {_fmt_pct(cpu.get('last'))}, 방향 {cpu.get('direction')}",
        f"- MEM 평균 {_fmt_pct(mem.get('avg'))}, 최대 {_fmt_pct(mem.get('max'))}, 최근 {_fmt_pct(mem.get('last'))}, 방향 {mem.get('direction')}",
        "",
        "## Disk",
        "",
    ]
    disks = analysis.get("disks") or []
    if disks:
        for disk in disks:
            md.append(
                f"- `{disk['mount']}` 평균 {_fmt_pct(disk.get('avg'))}, "
                f"최대 {_fmt_pct(disk.get('max'))}, 최근 {_fmt_pct(disk.get('last'))}, "
                f"방향 {disk.get('direction')}"
            )
    else:
        md.append("- 디스크 자료 없음")
    md += ["", "## 인스턴스", ""]
    if fail:
        for name, days_failed in sorted(fail.items()):
            md.append(f"- **{name}** 이상 날짜: {', '.join(days_failed)}")
    else:
        md.append("- 기간 내 인스턴스 이상은 없습니다.")
    markdown = "\n".join(md)

    disk_html = "".join(
        f"<li><code>{escape(str(disk['mount']))}</code> 평균 {_fmt_pct(disk.get('avg'))}, "
        f"최대 {_fmt_pct(disk.get('max'))}, 최근 {_fmt_pct(disk.get('last'))}, "
        f"방향 {escape(str(disk.get('direction')))}</li>"
        for disk in disks
    ) or "<li>디스크 자료 없음</li>"
    inst_html = "".join(
        f"<li><strong>{escape(name)}</strong> 이상 날짜: {escape(', '.join(days_failed))}</li>"
        for name, days_failed in sorted(fail.items())
    ) or "<li>기간 내 인스턴스 이상은 없습니다.</li>"
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: Segoe UI, sans-serif; background: #12141a; color: #e8e4d9; margin: 32px; }}
    h1,h2 {{ font-weight: 600; }}
    code {{ font-family: Consolas, monospace; background: #1b1f28; padding: 2px 6px; }}
  </style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <p>기간: {escape(start)} ~ {escape(end)}<br>요약: {escape(summary)}</p>
  <h2>CPU / MEM</h2>
  <ul>
    <li>CPU 평균 {_fmt_pct(cpu.get('avg'))}, 최대 {_fmt_pct(cpu.get('max'))}, 최근 {_fmt_pct(cpu.get('last'))}, 방향 {escape(str(cpu.get('direction')))}</li>
    <li>MEM 평균 {_fmt_pct(mem.get('avg'))}, 최대 {_fmt_pct(mem.get('max'))}, 최근 {_fmt_pct(mem.get('last'))}, 방향 {escape(str(mem.get('direction')))}</li>
  </ul>
  <h2>Disk</h2>
  <ul>{disk_html}</ul>
  <h2>인스턴스</h2>
  <ul>{inst_html}</ul>
</body>
</html>
"""
    return {
        "plugin": f"{RESOURCE_PLUGIN}:{server}",
        "title": f"{end} {title}",
        "summary": summary,
        "markdown": markdown,
        "html": html,
    }
