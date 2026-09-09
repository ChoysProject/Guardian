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
# 셸이 숫자 자리를 비워 두거나 df 가 - 를 찍은 경우: "count": } / "inode_pct": -
_EMPTY_JSON_VALUE = re.compile(r'":\s*([,}\]])')
_BARE_DASH_JSON_VALUE = re.compile(r":\s*-(?=\s*[,}\]])")

SAMPLE_JSON = {
    "server": "eai-01",
    "date": "2026-09-01",
    "cpu": {
        "usage_pct": 23.5,
        "peak_pct": 61.0,
        "cores": 4,
        "load1": 0.94,
        "samples": [
            {"hour": "00", "cpu_pct": 12.0, "mem_pct": 55.0},
            {"hour": "09", "cpu_pct": 48.0, "mem_pct": 62.0},
            {"hour": "14", "cpu_pct": 61.0, "mem_pct": 67.0},
        ],
    },
    "mem": {"used_pct": 61.2, "used_mb": 4980, "total_mb": 8192, "swap_used_pct": 3.0},
    "disk": [
        {"mount": "/", "used_pct": 72.0, "used_gb": 36.0, "total_gb": 50.0, "free_gb": 14.0},
        {"mount": "/data", "used_pct": 41.0, "used_gb": 82.0, "total_gb": 200.0, "free_gb": 118.0},
    ],
    "instances": [
        {"name": "was", "ok": True, "cpu_pct": 31.0, "mem_mb": 2048, "restarts": 0, "pids": 1},
        {"name": "mq", "ok": True, "detail": "pid 2201", "cpu_pct": 4.0, "mem_mb": 512, "restarts": 2},
    ],
    "top": [
        {"name": "java", "cpu_pct": 31.0, "mem_pct": 25.0},
        {"name": "postgres", "cpu_pct": 8.0, "mem_pct": 11.0},
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


def report_server_name(plugin: str | None) -> str:
    text = str(plugin or "")
    prefix = f"{RESOURCE_PLUGIN}:"
    if text.startswith(prefix):
        return text[len(prefix):]
    return ""


def group_resource_report_rows(
    reports: list[Any],
    *,
    registered: list[str] | None = None,
    snapshot_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    names: list[str] = []
    seen: set[str] = set()
    for name in [*(registered or []), *(snapshot_names or [])]:
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    buckets: dict[str, list[Any]] = {name: [] for name in names}
    for report in reports:
        server = report_server_name(getattr(report, "plugin", None)) or "기타"
        if server not in buckets:
            buckets[server] = []
            names.append(server)
        buckets[server].append(report)
    snap = set(snapshot_names or [])
    groups = []
    for name in names:
        items = buckets.get(name) or []
        latest = items[0] if items else None
        metrics = resource_card_metrics(name) if name in snap else {}
        verdict = ""
        if latest is not None:
            verdict = str(getattr(latest, "summary", "") or "").split(" · ")[0]
        report_items = []
        for item in items:
            start = getattr(item, "period_start", None)
            end = getattr(item, "period_end", None)
            start_text = start.date().isoformat() if hasattr(start, "date") else str(start or "")
            end_text = end.date().isoformat() if hasattr(end, "date") else str(end or "")
            report_items.append(
                {
                    "id": getattr(item, "id", None),
                    "title": str(getattr(item, "title", "") or ""),
                    "period": f"{start_text} ~ {end_text}".strip(" ~"),
                    "summary": str(getattr(item, "summary", "") or "").split(" · ")[0],
                }
            )
        groups.append(
            {
                "name": name,
                "reports": items,
                "report_items": report_items,
                "reports_json": json.dumps(report_items, ensure_ascii=False),
                "latest": latest,
                "has_data": name in snap,
                "metrics": metrics,
                "verdict": verdict or metrics.get("status") or "",
            }
        )
    return groups


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


def _as_num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in OK_VALUES


def _fold_mem_extra(mem_block: dict[str, Any], extra: dict[str, Any]) -> None:
    available = extra.get("mem_available")
    if isinstance(available, dict) and mem_block.get("available_mb") is None:
        avail = _as_num(available.get("available_mb"))
        if avail is not None:
            mem_block["available_mb"] = avail
    swap = extra.get("mem_swap")
    if not isinstance(swap, dict):
        return
    if mem_block.get("swap_used_pct") is None:
        pct = _as_pct(_first(swap, "used_pct", "swap_used_pct"))
        if pct is not None:
            mem_block["swap_used_pct"] = pct
    if mem_block.get("swap_used_mb") is None:
        used = _as_num(swap.get("used_mb"))
        if used is not None:
            mem_block["swap_used_mb"] = used
    if mem_block.get("swap_total_mb") is None:
        total = _as_num(swap.get("total_mb"))
        if total is not None:
            mem_block["swap_total_mb"] = total


def _parse_disk(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict):
                mount = str(row.get("mount") or row.get("path") or row.get("name") or "/").strip() or "/"
                pct = _as_pct(row.get("used_pct", row.get("usage_pct", row.get("pct"))))
                item = {"mount": mount, "used_pct": pct}
                used_gb = _as_num(_first(row, "used_gb", "used"))
                total_gb = _as_num(_first(row, "total_gb", "size_gb", "total"))
                free_gb = _as_num(_first(row, "free_gb", "avail_gb", "available_gb"))
                if free_gb is None and used_gb is not None and total_gb is not None:
                    free_gb = round(total_gb - used_gb, 1)
                if used_gb is not None:
                    item["used_gb"] = used_gb
                if total_gb is not None:
                    item["total_gb"] = total_gb
                if free_gb is not None:
                    item["free_gb"] = free_gb
                items.append(item)
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


def _instance_item(name: str, ok: Any, row: dict[str, Any]) -> dict[str, Any]:
    item = {"name": name, "ok": _as_bool(ok), "detail": str(row.get("detail") or "")}
    cpu = _as_num(_first(row, "cpu_pct", "cpu"))
    mem_mb = _as_num(_first(row, "mem_mb", "rss_mb", "memory_mb"))
    restarts = _as_int(_first(row, "restarts", "restart_count"))
    pids = _as_int(_first(row, "pids", "pid_count", "processes"))
    started = str(_first(row, "started_at", "since", "lstart") or "").strip()
    problem = str(_first(row, "problem", "issue", "fault") or "").strip()
    uptime_sec = _as_int(_first(row, "uptime_sec", "etime_sec"))
    if cpu is not None:
        item["cpu_pct"] = cpu
    if mem_mb is not None:
        item["mem_mb"] = mem_mb
    if restarts is not None:
        item["restarts"] = restarts
    if pids is not None:
        item["pids"] = pids
    if started:
        item["started_at"] = started
    if problem:
        item["problem"] = problem
    if uptime_sec is not None:
        item["uptime_sec"] = uptime_sec
    return item


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
                items.append(_instance_item(name, ok, row))
            elif isinstance(row, str) and row.strip():
                items.append({"name": row.strip(), "ok": True, "detail": ""})
    elif isinstance(raw, dict):
        for name, value in raw.items():
            if isinstance(value, dict):
                ok = value.get("ok", value.get("status", True))
                items.append(_instance_item(str(name), ok, value))
            else:
                items.append({"name": str(name), "ok": _as_bool(value), "detail": ""})
    return items


def _parse_samples(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return items
    for row in raw:
        if not isinstance(row, dict):
            continue
        hour = str(_first(row, "hour", "t", "time") or "").strip()
        if hour.isdigit():
            hour = f"{int(hour):02d}"
        elif ":" in hour:
            hour = hour.split(":")[0].zfill(2)
        if not hour:
            continue
        item = {"hour": hour}
        cpu = _as_pct(_first(row, "cpu_pct", "cpu", "usage_pct"))
        mem = _as_pct(_first(row, "mem_pct", "mem", "used_pct"))
        if cpu is not None:
            item["cpu_pct"] = cpu
        if mem is not None:
            item["mem_pct"] = mem
        items.append(item)
    items.sort(key=lambda item: item["hour"])
    return items


def _parse_top(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return items
    for row in raw:
        if not isinstance(row, dict):
            continue
        name = str(_first(row, "name", "command", "comm") or "").strip()
        if not name:
            continue
        item = {"name": name}
        cpu = _as_pct(_first(row, "cpu_pct", "cpu"))
        mem = _as_pct(_first(row, "mem_pct", "mem"))
        if cpu is not None:
            item["cpu_pct"] = cpu
        if mem is not None:
            item["mem_pct"] = mem
        items.append(item)
    return items[:10]


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
    samples = _parse_samples(
        (cpu_raw.get("samples") if isinstance(cpu_raw, dict) else None) or raw.get("samples")
    )
    cpu_block: dict[str, Any] = {"usage_pct": cpu_pct}
    if isinstance(cpu_raw, dict):
        for key, src in (("peak_pct", "peak_pct"), ("load1", "load1"), ("cores", "cores")):
            value = _as_num(cpu_raw.get(src))
            if value is not None:
                cpu_block[key] = value
    hourly_cpu = [item["cpu_pct"] for item in samples if item.get("cpu_pct") is not None]
    if hourly_cpu:
        if cpu_block.get("usage_pct") is None:
            cpu_block["usage_pct"] = round(sum(hourly_cpu) / len(hourly_cpu), 1)
        if cpu_block.get("peak_pct") is None:
            cpu_block["peak_pct"] = max(hourly_cpu)
        cpu_block["samples"] = samples
    elif samples:
        cpu_block["samples"] = samples
    mem_block: dict[str, Any] = {"used_pct": mem_pct, "used_mb": mem_used, "total_mb": mem_total}
    if isinstance(mem_raw, dict):
        avail = _as_num(_first(mem_raw, "available_mb", "avail_mb"))
        if avail is not None:
            mem_block["available_mb"] = avail
        swap = _as_pct(_first(mem_raw, "swap_used_pct", "swap_pct"))
        if swap is not None:
            mem_block["swap_used_pct"] = swap
        swap_used = _as_num(_first(mem_raw, "swap_used_mb"))
        swap_total = _as_num(_first(mem_raw, "swap_total_mb"))
        if swap_used is not None:
            mem_block["swap_used_mb"] = swap_used
        if swap_total is not None:
            mem_block["swap_total_mb"] = swap_total
    hourly_mem = [item["mem_pct"] for item in samples if item.get("mem_pct") is not None]
    if hourly_mem and mem_block.get("used_pct") is None:
        mem_block["used_pct"] = round(sum(hourly_mem) / len(hourly_mem), 1)
    if hourly_mem:
        mem_block["peak_pct"] = max(hourly_mem)
    snapshot = {
        "server": _safe_server(server),
        "date": _valid_date(date),
        "cpu": cpu_block,
        "mem": mem_block,
        "disk": _parse_disk(raw.get("disk") if "disk" in raw else raw.get("disks")),
        "instances": _parse_instances(raw.get("instances") if "instances" in raw else raw.get("instance")),
    }
    top = _parse_top(raw.get("top") if "top" in raw else raw.get("top_processes"))
    if top:
        snapshot["top"] = top
    extra = raw.get("extra")
    if isinstance(extra, dict):
        snapshot["extra"] = extra
        _fold_mem_extra(snapshot["mem"], extra)
    return snapshot


def _repair_loose_json(text: str) -> str:
    """수집 스크립트가 숫자를 비워 두거나 '-' 로 남긴 JSON을 고친다."""
    fixed = _EMPTY_JSON_VALUE.sub(r'": null\1', text)
    return _BARE_DASH_JSON_VALUE.sub(": null", fixed)


def parse_payload(text: str, *, fallback_server: str = "", fallback_date: str = "") -> list[dict[str, Any]]:
    raw_text = (text or "").strip()
    if not raw_text:
        raise ValueError("넣을 데이터가 없습니다.")
    try:
        loaded = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        try:
            loaded = json.loads(_repair_loose_json(raw_text))
        except json.JSONDecodeError:
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


def import_snapshots_from_path(server: str, path: str) -> tuple[int, list[str]]:
    """수집 경로에 놓인 JSON 파일을 전부 다시 읽어 스냅샷으로 저장한다.

    경로가 폴더면 그 안의 ``*.json`` 과 ``DailyData/*.json`` 을 전부, 파일이면 그 파일 하나만 읽는다.
    파일 하나가 잘못돼도 나머지는 계속 넣고, 실패한 파일 이름만 사유와 함께 돌려준다.
    """
    clean = (path or "").strip()
    if not clean:
        raise ValueError("수집 경로가 비어 있습니다.")
    target = Path(clean).expanduser()
    if not target.exists():
        raise ValueError(f"수집 경로를 찾을 수 없습니다: {clean}")
    if target.is_dir():
        files = sorted(target.glob("*.json"))
        daily = target / "DailyData"
        if daily.is_dir():
            files.extend(sorted(daily.glob("*.json")))
    else:
        files = [target]
    if not files:
        raise ValueError(f"경로에 JSON 파일이 없습니다: {clean}")
    saved = 0
    errors: list[str] = []
    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf-8")
            for snapshot in parse_payload(text, fallback_server=server, fallback_date=""):
                snapshot["server"] = server
                save_snapshot(snapshot)
                saved += 1
        except (ValueError, OSError) as exc:
            errors.append(f"{file_path.name}: {exc}")
    if not saved and errors:
        raise ValueError("; ".join(errors[:5]))
    return saved, errors


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
        return "유지"
    delta = values[-1] - values[0]
    if delta >= 3:
        return "상승"
    if delta <= -3:
        return "하락"
    return "유지"


def _growth_per_day(values: list[float]) -> float | None:
    """하루 평균 몇 %p 씩 오르는지. 두 점 이상일 때만 낸다."""
    if len(values) < 2:
        return None
    span = len(values) - 1
    return round((values[-1] - values[0]) / span, 2)


def _days_to_full(last: float | None, growth: float | None) -> int | None:
    if last is None or growth is None or growth <= 0.05:
        return None
    remain = 100.0 - last
    if remain <= 0:
        return 0
    return int(remain / growth)


def _busy_hours(hour_cpu: dict[str, list[float]], hour_mem: dict[str, list[float]]) -> list[dict[str, Any]]:
    rows = []
    for hour in sorted(set(hour_cpu) | set(hour_mem)):
        rows.append(
            {
                "hour": hour,
                "cpu_avg": _avg(hour_cpu.get(hour) or []),
                "mem_avg": _avg(hour_mem.get(hour) or []),
            }
        )
    rows.sort(key=lambda row: row["cpu_avg"] or 0, reverse=True)
    return rows[:3]


EXTRA_TEXT_FIELDS = {
    "kernel",
    "distro",
    "since",
    "instance_type",
    "path",
    "name",
    "cmd",
    "detail",
    "device",
    "iface",
    "proto",
    "local",
}
EXTRA_SKIP = {
    "empty",
    "status",
    "error",
    "cpu_usage",
    "mem_usage",
    "mem_available",
    "mem_swap",
    "disk_usage",
    "instance_search",
    "proc_service_alive",
    "proc_top_cpu",
}
FIELD_LABELS = {
    "load1": "1분",
    "load5": "5분",
    "load15": "15분",
    "cores": "코어",
    "steal_pct": "Steal %",
    "cs": "CS",
    "in": "Interrupt",
    "available_mb": "Available MB",
    "used_pct": "사용률",
    "used_mb": "사용 MB",
    "total_mb": "전체 MB",
    "hits": "건수",
    "iowait_pct": "I/O Wait %",
    "bytes": "용량(B)",
    "path": "경로",
    "established": "ESTABLISHED",
    "time_wait": "TIME_WAIT",
    "close_wait": "CLOSE_WAIT",
    "remote": "상대",
    "state": "상태",
    "started_at": "마지막 기동",
    "uptime_sec": "기동 후(초)",
    "problem": "문제",
    "restarts": "재시작",
    "count": "건수",
    "open": "열린 수",
    "distro": "배포판",
    "kernel": "커널",
    "since": "부팅",
    "instance_type": "인스턴스 타입",
    "ntp_synchronized": "NTP 동기",
    "lines": "crontab 줄",
    "inode_pct": "inode %",
    "mount": "마운트",
    "device": "장치",
    "iface": "인터페이스",
    "rx_bytes": "RX",
    "tx_bytes": "TX",
    "rx_drop": "RX drop",
    "tx_drop": "TX drop",
    "rx_err": "RX err",
    "tx_err": "TX err",
    "r_s": "r/s",
    "w_s": "w/s",
    "reads": "읽기",
    "writes": "쓰기",
    "name": "이름",
    "cpu_pct": "CPU",
    "mem_pct": "MEM",
    "proto": "프로토콜",
    "local": "로컬",
}
WARN_FIELDS = {
    ("cpu_steal", "steal_pct"): (5, 15),
    ("disk_iowait", "iowait_pct"): (15, 30),
    ("disk_inode", "inode_pct"): (80, 90),
    ("mem_swap", "used_pct"): (10, 30),
    ("mem_oom", "hits"): (1, 1),
    ("proc_zombie", "count"): (1, 5),
    ("sec_failed_login", "count"): (10, 50),
}


def _extra_title(key: str) -> str:
    from app.resource_script import module_by_id

    spec = module_by_id(key)
    if spec:
        return str(spec.get("name") or key)
    return key


def _extra_blank(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, dict):
        useful = {k: v for k, v in value.items() if k not in ("status", "error")}
        if value.get("status") in {"unavailable", "skipped"} and not useful:
            return True
        if not useful and value.get("status"):
            return True
    return isinstance(value, list) and not value


def _field_level(key: str, field: str, value: Any) -> str:
    if isinstance(value, bool):
        if key == "os_ntp_sync" and field == "ntp_synchronized":
            return "ok" if value else "danger"
        return "ok" if value else "warn"
    num = _as_num(value)
    if num is None:
        return ""
    warn, danger = WARN_FIELDS.get((key, field), (None, None))
    if warn is None:
        if field in {"used_pct", "usage_pct", "inode_pct"}:
            warn, danger = 80, 90
        else:
            return ""
    if num >= danger:
        return "danger"
    if num >= warn:
        return "warn"
    return "ok"


def _pct_level(value: float | None, *, warn: float = 70, danger: float = 85) -> str:
    if value is None:
        return ""
    if value >= danger:
        return "danger"
    if value >= warn:
        return "warn"
    return "ok"


def _analyze_extras(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, Any] = {}
    days: dict[str, int] = {}
    nums: dict[str, dict[str, list[float]]] = {}
    for item in items:
        extra = item.get("extra")
        if not isinstance(extra, dict):
            continue
        for key, body in extra.items():
            if key in EXTRA_SKIP or _extra_blank(body):
                continue
            if isinstance(body, list) and body and isinstance(body[0], dict) and "mount" in body[0]:
                body = [
                    row
                    for row in body
                    if isinstance(row, dict)
                    and not _is_noise_mount(str(row.get("mount") or ""), row.get("total_gb"))
                ]
                if _extra_blank(body):
                    continue
            latest[key] = body
            days[key] = days.get(key, 0) + 1
            rows = body if isinstance(body, list) else [body] if isinstance(body, dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for field, val in row.items():
                    if field in ("status", "error") or field in EXTRA_TEXT_FIELDS:
                        continue
                    num = _as_num(val)
                    if num is None:
                        continue
                    nums.setdefault(key, {}).setdefault(field, []).append(num)
    from app.resource_script import catalog

    order = [item["id"] for group in catalog() for item in group["modules"]]
    extras = []
    for key in [*order, *latest.keys()]:
        if key not in latest or any(row["key"] == key for row in extras):
            continue
        stats = {}
        for field, values in (nums.get(key) or {}).items():
            stats[field] = {
                "avg": _avg(values),
                "max": max(values) if values else None,
                "last": values[-1] if values else None,
                "direction": _direction(values),
                "level": _field_level(key, field, values[-1] if values else None),
            }
        extras.append(
            {
                "key": key,
                "title": _extra_title(key),
                "days": days.get(key, 0),
                "latest": latest[key],
                "stats": stats,
            }
        )
    return extras


def analyze_server(server: str, *, days: int = 7, end: str | None = None) -> dict[str, Any]:
    from app.server_modes import get_instances

    registered = get_instances(server)
    items = snapshots_for(server, days=days, end=end)
    cpu = _series([((item.get("cpu") or {}).get("usage_pct")) for item in items])
    mem = _series([((item.get("mem") or {}).get("used_pct")) for item in items])
    cpu_peak = _series([((item.get("cpu") or {}).get("peak_pct")) for item in items])
    mem_peak = _series([((item.get("mem") or {}).get("peak_pct")) for item in items])
    swap = _series([((item.get("mem") or {}).get("swap_used_pct")) for item in items])
    last_mem = (items[-1].get("mem") if items else {}) or {}
    load1 = _series([((item.get("cpu") or {}).get("load1")) for item in items])
    cores = _series([((item.get("cpu") or {}).get("cores")) for item in items])
    disk_rows: dict[str, list[float]] = {}
    disk_last: dict[str, dict[str, Any]] = {}
    instance_fail: dict[str, list[str]] = {}
    instance_missing: dict[str, list[str]] = {}
    instance_stats: dict[str, dict[str, Any]] = {}
    hour_cpu: dict[str, list[float]] = {}
    hour_mem: dict[str, list[float]] = {}
    top_cpu: dict[str, list[float]] = {}
    for item in items:
        date = str(item.get("date") or "")
        for disk in item.get("disk") or []:
            mount = str(disk.get("mount") or "/")
            pct = disk.get("used_pct")
            if pct is None:
                continue
            disk_rows.setdefault(mount, []).append(float(pct))
            disk_last[mount] = disk
        for sample in (item.get("cpu") or {}).get("samples") or []:
            hour = str(sample.get("hour") or "")
            if not hour:
                continue
            if sample.get("cpu_pct") is not None:
                hour_cpu.setdefault(hour, []).append(float(sample["cpu_pct"]))
            if sample.get("mem_pct") is not None:
                hour_mem.setdefault(hour, []).append(float(sample["mem_pct"]))
        for proc in item.get("top") or []:
            name = str(proc.get("name") or "")
            if name and proc.get("cpu_pct") is not None:
                top_cpu.setdefault(name, []).append(float(proc["cpu_pct"]))
        reported = set()
        for inst in item.get("instances") or []:
            name = str(inst.get("name") or "")
            if not name:
                continue
            reported.add(name)
            stat = instance_stats.setdefault(
                name, {"name": name, "days": 0, "cpu": [], "mem": [], "restarts": 0, "started_at": "", "problem": ""}
            )
            stat["days"] += 1
            if inst.get("cpu_pct") is not None:
                stat["cpu"].append(float(inst["cpu_pct"]))
            if inst.get("mem_mb") is not None:
                stat["mem"].append(float(inst["mem_mb"]))
            if inst.get("restarts"):
                stat["restarts"] += int(inst["restarts"])
            if inst.get("started_at"):
                stat["started_at"] = str(inst.get("started_at"))
            if inst.get("problem"):
                stat["problem"] = str(inst.get("problem"))
            elif inst.get("ok"):
                stat["problem"] = ""
            if not inst.get("ok"):
                instance_fail.setdefault(name, []).append(date)
        for name in registered:
            if name not in reported:
                instance_missing.setdefault(name, []).append(date)
    disks = []
    for mount, values in sorted(disk_rows.items()):
        latest = disk_last.get(mount) or {}
        growth = _growth_per_day(values)
        disks.append(
            {
                "mount": mount,
                "avg": _avg(values),
                "max": max(values) if values else None,
                "last": values[-1] if values else None,
                "direction": _direction(values),
                "growth_per_day": growth,
                "free_gb": latest.get("free_gb"),
                "total_gb": latest.get("total_gb"),
                "days_to_full": _days_to_full(values[-1] if values else None, growth),
            }
        )
    instances_detail = []
    for name in sorted(instance_stats):
        stat = instance_stats[name]
        instances_detail.append(
            {
                "name": name,
                "days": stat["days"],
                "cpu_avg": _avg(stat["cpu"]),
                "mem_avg_mb": _avg(stat["mem"]),
                "restarts": stat["restarts"],
                "started_at": stat.get("started_at") or "",
                "problem": stat.get("problem") or "",
                "fail_days": len(instance_fail.get(name) or []),
                "missing_days": len(instance_missing.get(name) or []),
                "registered": name in registered,
            }
        )
    top_processes = sorted(
        (
            {"name": name, "cpu_avg": _avg(values)}
            for name, values in top_cpu.items()
        ),
        key=lambda row: row["cpu_avg"] or 0,
        reverse=True,
    )[:5]
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
            "peak_avg": _avg(cpu_peak),
            "peak_max": max(cpu_peak) if cpu_peak else None,
            "load1_avg": _avg(load1),
            "load1_last": load1[-1] if load1 else None,
            "cores": cores[-1] if cores else None,
            "series": cpu,
        },
        "mem": {
            "avg": _avg(mem),
            "max": max(mem) if mem else None,
            "last": mem[-1] if mem else None,
            "direction": _direction(mem),
            "peak_max": max(mem_peak) if mem_peak else None,
            "swap_max": max(swap) if swap else None,
            "swap_last": swap[-1] if swap else None,
            "used_mb": last_mem.get("used_mb"),
            "total_mb": last_mem.get("total_mb"),
            "available_mb": last_mem.get("available_mb"),
            "swap_used_mb": last_mem.get("swap_used_mb"),
            "swap_total_mb": last_mem.get("swap_total_mb"),
            "series": mem,
        },
        "disks": _notable_disks(disks),
        "busy_hours": _busy_hours(hour_cpu, hour_mem),
        "top_processes": top_processes,
        "instances": registered,
        "instances_detail": instances_detail,
        "instance_fail": instance_fail,
        "instance_missing": instance_missing,
        "extras": _analyze_extras(items),
        "items": items,
    }


def _fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value}%"


def snapshot_server_names() -> list[str]:
    return [row["server"] for row in list_snapshots()]


def snapshots_for_name(server_name: str) -> list[dict[str, Any]]:
    for group in list_snapshots():
        if group["server"] == server_name:
            return list(group.get("snapshots") or [])
    return []


SAMPLE_PROFILES = (
    {
        "name": "demo-local",
        "cpu": 24.0,
        "cpu_delta": 1.6,
        "mem": 51.0,
        "mem_delta": 1.1,
        "cores": 4,
        "swap": 2.0,
        # mount, 시작 사용률, 하루 증가폭, 전체 용량(GB)
        "disks": [("/", 63.0, 1.4, 50), ("/var", 38.0, 0.5, 100)],
        # 이름, CPU, 메모리(MB), 하루 메모리 증가분(MB)
        "instances": [("was", 17.0, 1400.0, 60.0), ("sshd", 0.4, 40.0, 0.0)],
        "fail": ("was", 1),
    },
    {
        "name": "demo-web",
        "cpu": 18.0,
        "cpu_delta": 0.8,
        "mem": 44.0,
        "mem_delta": 0.6,
        "cores": 8,
        "swap": 0.0,
        "disks": [("/", 48.0, 0.7, 80)],
        "instances": [("nginx", 6.0, 260.0, 0.0), ("php-fpm", 9.0, 780.0, 12.0)],
        "fail": None,
    },
    {
        "name": "demo-db",
        "cpu": 31.0,
        "cpu_delta": 2.1,
        "mem": 72.0,
        "mem_delta": 1.4,
        "cores": 8,
        "swap": 11.0,
        "disks": [("/", 55.0, 0.4, 60), ("/data", 68.0, 1.8, 500)],
        "instances": [("postgres", 22.0, 3100.0, 40.0), ("listener", 1.2, 120.0, 0.0)],
        "fail": ("listener", 2),
    },
    {
        "name": "demo-auth",
        "cpu": 8.0,
        "cpu_delta": 0.3,
        "mem": 29.0,
        "mem_delta": 0.2,
        "cores": 2,
        "swap": 0.0,
        "disks": [("/", 41.0, 0.2, 40)],
        "instances": [("sshd", 0.6, 60.0, 0.0)],
        "fail": None,
    },
)

# 업무 시간에 높고 새벽에 낮은 하루 곡선
HOUR_CURVE = (
    0.45, 0.40, 0.38, 0.36, 0.38, 0.45,
    0.60, 0.85, 1.15, 1.35, 1.40, 1.30,
    1.10, 1.25, 1.45, 1.40, 1.25, 1.10,
    0.95, 0.80, 0.70, 0.62, 0.55, 0.48,
)


def _clamp_pct(value: float) -> float:
    return round(min(99.0, max(1.0, value)), 1)


def _hourly_samples(cpu_base: float, mem_base: float) -> list[dict[str, Any]]:
    rows = []
    for hour, factor in enumerate(HOUR_CURVE):
        rows.append(
            {
                "hour": f"{hour:02d}",
                "cpu_pct": _clamp_pct(cpu_base * factor),
                "mem_pct": _clamp_pct(mem_base * (0.9 + 0.15 * (factor - 0.9))),
            }
        )
    return rows


def write_sample_snapshots(*, days: int = 7, force: bool = False, when: datetime | None = None) -> int:
    window = max(int(days or 7), 1)
    end = datetime.strptime(today_stamp(when), "%Y-%m-%d")
    saved = 0
    for profile in SAMPLE_PROFILES:
        fail = profile.get("fail")
        for offset in range(window):
            day = (end - timedelta(days=offset)).strftime("%Y-%m-%d")
            age = window - 1 - offset
            path = snapshot_path(profile["name"], day)
            if path.exists() and not force:
                continue
            instances = []
            for name, cpu_pct, mem_mb, mem_growth in profile["instances"]:
                down = bool(fail) and fail[0] == name and fail[1] == offset
                instances.append(
                    {
                        "name": name,
                        "ok": not down,
                        "detail": "stopped" if down else "running",
                        "cpu_pct": 0.0 if down else round(cpu_pct * (1 + 0.03 * age), 1),
                        "mem_mb": round(mem_mb + mem_growth * age, 1),
                        "restarts": 1 if down else 0,
                        "pids": 0 if down else 1,
                    }
                )
            cpu_base = _clamp_pct(profile["cpu"] + profile["cpu_delta"] * age)
            mem_base = _clamp_pct(profile["mem"] + profile["mem_delta"] * age)
            samples = _hourly_samples(cpu_base, mem_base)
            disks = []
            for mount, base, delta, total_gb in profile["disks"]:
                pct = _clamp_pct(base + delta * age)
                used_gb = round(total_gb * pct / 100, 1)
                disks.append(
                    {
                        "mount": mount,
                        "used_pct": pct,
                        "used_gb": used_gb,
                        "total_gb": float(total_gb),
                        "free_gb": round(total_gb - used_gb, 1),
                    }
                )
            top = sorted(
                (
                    {
                        "name": item["name"],
                        "cpu_pct": item["cpu_pct"],
                        "mem_pct": round(min(99.0, item["mem_mb"] / 80), 1),
                    }
                    for item in instances
                ),
                key=lambda row: row["cpu_pct"],
                reverse=True,
            )
            snapshot = {
                "server": profile["name"],
                "date": day,
                "cpu": {
                    "usage_pct": cpu_base,
                    "peak_pct": max(row["cpu_pct"] for row in samples),
                    "cores": profile.get("cores", 4),
                    "load1": round(cpu_base * profile.get("cores", 4) / 100, 2),
                    "samples": samples,
                },
                "mem": {
                    "used_pct": mem_base,
                    "peak_pct": max(row["mem_pct"] for row in samples),
                    "swap_used_pct": profile.get("swap", 0.0),
                },
                "disk": disks,
                "instances": instances,
                "top": top,
            }
            save_snapshot(normalize_snapshot(snapshot))
            saved += 1
    return saved


def generate_resource_reports(
    db,
    server_names: list[str] | None = None,
    *,
    days: int = 7,
    when: datetime | None = None,
):
    from app.ai.gateway import review_resources
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
        review = review_resources(resource_payload(analysis))
        rendered = render_resource_report(analysis, start=start, end=end, ai=review)
        created.append(_store_report(db, rendered, start_dt, end_dt, end))
    db.commit()
    for report in created:
        db.refresh(report)
    return created


def resource_payload(analysis: dict[str, Any]) -> dict[str, Any]:
    """AI에는 원본 스냅샷이 아니라 추린 통계만 보낸다."""
    cpu = analysis.get("cpu") or {}
    mem = analysis.get("mem") or {}
    return {
        "server": analysis.get("server"),
        "days_with_data": analysis.get("count"),
        "window_days": analysis.get("days"),
        "cpu": {
            "avg": cpu.get("avg"),
            "max": cpu.get("max"),
            "last": cpu.get("last"),
            "peak_max": cpu.get("peak_max"),
            "direction": cpu.get("direction"),
            "series": cpu.get("series"),
        },
        "mem": {
            "avg": mem.get("avg"),
            "max": mem.get("max"),
            "last": mem.get("last"),
            "peak_max": mem.get("peak_max"),
            "swap_max": mem.get("swap_max"),
            "direction": mem.get("direction"),
            "series": mem.get("series"),
        },
        "disks": [
            {
                "mount": disk.get("mount"),
                "last": disk.get("last"),
                "growth_per_day": disk.get("growth_per_day"),
                "free_gb": disk.get("free_gb"),
                "days_to_full": disk.get("days_to_full"),
                "direction": disk.get("direction"),
            }
            for disk in (analysis.get("disks") or [])
        ],
        "busy_hours": analysis.get("busy_hours") or [],
        "top_processes": analysis.get("top_processes") or [],
        "instances": analysis.get("instances_detail") or [],
        "instance_fail_days": analysis.get("instance_fail") or {},
        "instance_missing_days": analysis.get("instance_missing") or {},
        "extras": [
            {
                "key": row.get("key"),
                "title": row.get("title"),
                "days": row.get("days"),
                "stats": row.get("stats") or {},
            }
            for row in (analysis.get("extras") or [])
        ],
    }


def _fmt_gb(value: float | None) -> str:
    return "-" if value is None else f"{value}GB"


def _fmt_mb(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 1024:
        gb = round(value / 1024, 1)
        return f"{gb:g}GB"
    return f"{int(round(value))}MB"


def _worse(*levels: str) -> str:
    if "danger" in levels:
        return "danger"
    if "warn" in levels:
        return "warn"
    for level in levels:
        if level:
            return level
    return ""


def resource_card_metrics(server: str) -> dict[str, Any]:
    items = snapshots_for_name(server)
    if not items:
        return {}
    last = items[0]
    cpu = (last.get("cpu") or {}).get("usage_pct")
    mem = last.get("mem") or {}
    disks = _notable_disks(
        [
            {
                "mount": row.get("mount"),
                "last": row.get("used_pct"),
                "total_gb": row.get("total_gb"),
                "free_gb": row.get("free_gb"),
            }
            for row in (last.get("disk") or [])
        ]
    )
    worst = disks[0] if disks else None
    instances = [
        row
        for row in (last.get("instances") or [])
        if row.get("name") and "{{" not in str(row.get("name"))
    ]
    live = sum(1 for row in instances if row.get("ok"))
    swap_pct = mem.get("swap_used_pct")
    level = _worse(
        _pct_level(cpu),
        _pct_level(mem.get("used_pct"), warn=80, danger=90),
        _pct_level(swap_pct, warn=10, danger=30),
        _disk_status(worst)[0] if worst else "",
        "danger" if any(not row.get("ok") for row in instances) else "",
    ) or "ok"
    labels = {"ok": "여유", "warn": "주의", "danger": "위험"}
    mem_size = ""
    if mem.get("used_mb") is not None and mem.get("total_mb") is not None:
        mem_size = f"{_fmt_mb(mem.get('used_mb'))} / {_fmt_mb(mem.get('total_mb'))}"
    return {
        "date": last.get("date") or "",
        "cpu_text": _fmt_pct(cpu),
        "mem_text": _fmt_pct(mem.get("used_pct")),
        "mem_size": mem_size,
        "swap_text": _fmt_pct(swap_pct) if swap_pct is not None else "",
        "disk_text": _fmt_pct(worst.get("last")) if worst else "-",
        "disk_name": _disk_alias(str(worst.get("mount"))) if worst else "디스크",
        "instances_text": f"{live}/{len(instances)}" if instances else "",
        "level": level,
        "status": labels.get(level, "-"),
    }


def _issue_lines(
    cpu: dict[str, Any],
    mem: dict[str, Any],
    disks: list[dict[str, Any]],
    fail: dict[str, Any],
    extras: list[dict[str, Any]],
) -> list[str]:
    lines: list[str] = []
    if _pct_level(cpu.get("last")) in {"warn", "danger"}:
        lines.append(f"CPU {_fmt_pct(cpu.get('last'))}")
    if _pct_level(mem.get("last"), warn=80, danger=90) in {"warn", "danger"}:
        lines.append(f"메모리 {_fmt_pct(mem.get('last'))}")
    swap_pct = mem.get("swap_last") if mem.get("swap_last") is not None else mem.get("swap_max")
    if _pct_level(swap_pct, warn=10, danger=30) in {"warn", "danger"}:
        lines.append(f"스왑 {_fmt_pct(swap_pct)}")
    for disk in disks:
        level, label = _disk_status(disk)
        if level in {"warn", "danger"}:
            lines.append(f"{_disk_alias(str(disk.get('mount')))} {label}")
    if fail:
        lines.append("인스턴스 중단 " + ", ".join(sorted(fail)))
    for extra in extras:
        worst = ""
        for row in (extra.get("stats") or {}).values():
            worst = _worse(worst, str(row.get("level") or ""))
        latest = extra.get("latest") or {}
        if extra.get("key") == "os_ntp_sync" and isinstance(latest, dict) and latest.get("ntp_synchronized") is False:
            worst = "danger"
        if extra.get("key") == "mem_oom" and isinstance(latest, dict) and _as_num(latest.get("hits")):
            worst = "danger"
        if extra.get("key") == "net_connections" and isinstance(latest, dict):
            tw = _as_num(latest.get("time_wait"))
            if tw is not None and tw >= 8000:
                worst = "warn"
        if worst in {"warn", "danger"}:
            lines.append(str(extra.get("title") or extra.get("key")))
    return lines


def _fmt_field(value: Any) -> str:
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if value is None or value == "":
        return "-"
    return str(value)


def _field_label(key: str) -> str:
    return FIELD_LABELS.get(key, key)


def _stat_line(stats: dict[str, Any]) -> str:
    parts = []
    for field, row in stats.items():
        last = row.get("last")
        bits = [f"{_field_label(field)} 최근 {_fmt_field(last)}"]
        if row.get("avg") is not None and row.get("avg") != last:
            bits.append(f"평균 {_fmt_field(row.get('avg'))}")
        if row.get("max") is not None and row.get("max") != last:
            bits.append(f"최대 {_fmt_field(row.get('max'))}")
        if row.get("direction") and row.get("direction") not in {"유지", "데이터 부족"}:
            bits.append(str(row["direction"]))
        parts.append(", ".join(bits))
    return " · ".join(parts)


def _latest_pairs(latest: Any) -> list[tuple[str, Any]]:
    if isinstance(latest, dict):
        return [(key, val) for key, val in latest.items() if key not in ("status", "error") and val not in (None, "")]
    return []


def _latest_rows(latest: Any) -> list[dict[str, Any]]:
    if isinstance(latest, list):
        return [row for row in latest if isinstance(row, dict)]
    return []


_NOISE_MOUNT = re.compile(
    r"^/(snap|dev|run|proc|sys|init|boot/efi)(/|$)|^/mnt/wsl|^/usr/lib/(modules|wsl)"
    r"|^/var/snap|^/var/lib/snapd|versions\.txt$"
)
_DISK_ALIAS = {
    "/": "시스템 디스크",
    "/var": "로그 · 가변 데이터",
    "/home": "홈",
    "/data": "데이터",
    "/opt": "응용 프로그램",
    "/mnt/c": "Windows C:",
}


def _is_noise_mount(mount: str, total_gb: float | None = None) -> bool:
    path = (mount or "").strip()
    if not path or _NOISE_MOUNT.search(path) or path.startswith("/mnt/wslg"):
        return True
    if total_gb is not None and total_gb < 2 and path not in _DISK_ALIAS:
        return True
    return False


def _disk_alias(mount: str) -> str:
    return _DISK_ALIAS.get(mount, mount)


def _notable_disks(disks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [row for row in disks if not _is_noise_mount(str(row.get("mount") or ""), row.get("total_gb"))]
    kept.sort(key=lambda row: (row.get("last") is None, -(row.get("last") or 0)))
    return kept[:6]


def _notable_inode_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = []
    for row in rows:
        mount = str(row.get("mount") or "")
        if _is_noise_mount(mount):
            continue
        kept.append(row)
    return kept[:6]


def _disk_status(disk: dict[str, Any]) -> tuple[str, str]:
    level = _pct_level(disk.get("last"), warn=80, danger=90)
    if disk.get("days_to_full") is not None and disk["days_to_full"] <= 14:
        level = "danger" if disk["days_to_full"] <= 7 else "warn"
    labels = {"ok": "여유", "warn": "주의", "danger": "위험"}
    return level, labels.get(level, "-")


def _instance_status(row: dict[str, Any]) -> tuple[str, str]:
    problem = str(row.get("problem") or "").strip()
    problem_label = {"failed": "실패", "stopped": "중지", "not_running": "없음"}.get(problem, problem)
    if row.get("fail_days") or problem in {"failed", "not_running", "stopped"}:
        return "danger", problem_label or "중단"
    if row.get("missing_days"):
        return "warn", "자료 없음"
    if problem:
        return "warn", problem_label
    return "ok", "정상"


def _overall_status(
    cpu: dict[str, Any],
    mem: dict[str, Any],
    disks: list[dict[str, Any]],
    fail: dict[str, Any],
    extras: list[dict[str, Any]],
) -> tuple[str, str]:
    levels = [
        _pct_level(cpu.get("last")),
        _pct_level(mem.get("last"), warn=80, danger=90),
        _pct_level(mem.get("swap_last") if mem.get("swap_last") is not None else mem.get("swap_max"), warn=10, danger=30),
    ]
    if fail:
        levels.append("danger")
    for disk in disks:
        levels.append(_disk_status(disk)[0])
    for extra in extras:
        for row in (extra.get("stats") or {}).values():
            if row.get("level") in {"warn", "danger"}:
                levels.append(row["level"])
        if extra.get("key") == "os_ntp_sync":
            latest = extra.get("latest") or {}
            if isinstance(latest, dict) and latest.get("ntp_synchronized") is False:
                levels.append("danger")
        if extra.get("key") == "mem_oom":
            latest = extra.get("latest") or {}
            if isinstance(latest, dict) and _as_num(latest.get("hits")):
                levels.append("danger")
    if "danger" in levels:
        return "danger", "다른 확인이 필요합니다"
    if "warn" in levels:
        return "warn", "대체로 괜찮지만 지켜볼 곳이 있습니다"
    return "ok", "지금은 여유 있습니다"


def _disk_line(disk: dict[str, Any]) -> str:
    parts = [
        f"평균 {_fmt_pct(disk.get('avg'))}",
        f"최대 {_fmt_pct(disk.get('max'))}",
        f"최근 {_fmt_pct(disk.get('last'))}",
        f"방향 {disk.get('direction')}",
    ]
    growth = disk.get("growth_per_day")
    if growth is not None:
        parts.append(f"하루 {growth:+.2f}%p")
    if disk.get("free_gb") is not None:
        parts.append(f"남은 용량 {_fmt_gb(disk.get('free_gb'))}")
    days_left = disk.get("days_to_full")
    if days_left is not None:
        parts.append(f"이 추세면 약 {days_left}일 뒤 가득 참")
    return ", ".join(parts)


def _instance_line(row: dict[str, Any]) -> str:
    parts = [f"자료 {row.get('days')}일"]
    if row.get("cpu_avg") is not None:
        parts.append(f"CPU 평균 {_fmt_pct(row.get('cpu_avg'))}")
    if row.get("mem_avg_mb") is not None:
        parts.append(f"MEM 평균 {row.get('mem_avg_mb')}MB")
    if row.get("restarts"):
        parts.append(f"재시작 {row.get('restarts')}회")
    if row.get("started_at"):
        parts.append(f"마지막 기동 {row.get('started_at')}")
    if row.get("problem"):
        parts.append(f"문제 {row.get('problem')}")
    if row.get("fail_days"):
        parts.append(f"중단 {row.get('fail_days')}일")
    if row.get("missing_days"):
        parts.append(f"자료 없음 {row.get('missing_days')}일")
    return ", ".join(parts)


def render_resource_report(
    analysis: dict[str, Any],
    *,
    start: str,
    end: str,
    ai: dict[str, Any] | None = None,
) -> dict[str, Any]:
    server = analysis["server"]
    title = f"{server} 리소스 추이 보고서"
    dates = analysis.get("dates") or []
    cpu = analysis.get("cpu") or {}
    mem = analysis.get("mem") or {}
    fail = analysis.get("instance_fail") or {}
    missing = analysis.get("instance_missing") or {}
    disks = _notable_disks(analysis.get("disks") or [])
    busy = analysis.get("busy_hours") or []
    top = analysis.get("top_processes") or []
    detail = [
        row
        for row in (analysis.get("instances_detail") or [])
        if row.get("name") and "{{" not in str(row.get("name"))
    ]
    detail.sort(
        key=lambda row: (
            0 if _instance_status(row)[0] == "danger" else 1 if _instance_status(row)[0] == "warn" else 2,
            str(row.get("name") or ""),
        )
    )
    registered = [name for name in (analysis.get("instances") or []) if name and "{{" not in name]
    extras = analysis.get("extras") or []
    review = ai or {}
    ai_summary = str(review.get("summary") or "").strip()
    ai_risks = review.get("risks") or []
    ai_actions = review.get("actions") or []
    overall, verdict = _overall_status(cpu, mem, disks, fail, extras)

    soonest = [disk for disk in disks if disk.get("days_to_full") is not None]
    soonest.sort(key=lambda disk: disk["days_to_full"])
    summary_bits = [
        verdict,
        f"자료 {analysis.get('count') or 0}일",
        f"CPU {_fmt_pct(cpu.get('last'))}",
        f"MEM {_fmt_pct(mem.get('last'))}",
    ]
    if soonest:
        first = soonest[0]
        summary_bits.append(f"{_disk_alias(str(first['mount']))} 약 {first['days_to_full']}일 뒤 가득 참")
    if fail:
        summary_bits.append(f"중단 {len(fail)}개")
    summary = " · ".join(summary_bits)

    md = [
        f"# {title}",
        "",
        f"- 한줄: {verdict}",
        f"- 기간: {start} ~ {end}",
        f"- 대상: {server}",
        f"- 요약: {summary}",
        f"- 있는 날짜: {', '.join(dates) if dates else '없음'}",
        "",
    ]
    if ai_summary or ai_risks or ai_actions:
        md += ["## AI 총평", ""]
        if ai_summary:
            md += [ai_summary, ""]
        if ai_risks:
            md.append("**눈여겨볼 것**")
            md += [f"- {item}" for item in ai_risks]
            md.append("")
        if ai_actions:
            md.append("**해볼 조치**")
            md += [f"- {item}" for item in ai_actions]
            md.append("")

    md += [
        "## CPU / MEM",
        "",
        f"- CPU 평균 {_fmt_pct(cpu.get('avg'))}, 최대 {_fmt_pct(cpu.get('max'))}, 최근 {_fmt_pct(cpu.get('last'))}, 방향 {cpu.get('direction')}",
        f"- MEM 평균 {_fmt_pct(mem.get('avg'))}, 최대 {_fmt_pct(mem.get('max'))}, 최근 {_fmt_pct(mem.get('last'))}, 방향 {mem.get('direction')}",
    ]
    if cpu.get("peak_max") is not None:
        md.append(f"- 하루 중 최고 CPU {_fmt_pct(cpu.get('peak_max'))}, MEM {_fmt_pct(mem.get('peak_max'))}")
    if mem.get("swap_max") is not None:
        md.append(f"- 스왑 최대 {_fmt_pct(mem.get('swap_max'))}")
    if cpu.get("load1_last") is not None:
        md.append(f"- Load1 최근 {cpu.get('load1_last')} (평균 {cpu.get('load1_avg')})")
    if cpu.get("cores") is not None:
        md.append(f"- 코어 {cpu.get('cores')}")
    if busy:
        md.append(
            "- 바쁜 시간대: "
            + ", ".join(
                f"{row['hour']}시 CPU {_fmt_pct(row.get('cpu_avg'))}" for row in busy
            )
        )
    md += ["", "## Disk", ""]
    if disks:
        for disk in disks:
            _level, label = _disk_status(disk)
            md.append(f"- {_disk_alias(str(disk['mount']))} ({disk['mount']}) {label} · {_disk_line(disk)}")
    else:
        md.append("- 디스크 자료 없음")
    md += ["", "## 인스턴스", ""]
    if registered:
        md.append(f"- 등록한 인스턴스: {', '.join(registered)}")
    for row in detail:
        _level, label = _instance_status(row)
        md.append(f"- **{row['name']}** {label} · {_instance_line(row)}")
    for name, days_failed in sorted(fail.items()):
        md.append(f"- **{name}** 중단 날짜: {', '.join(days_failed)}")
    for name, days_missing in sorted(missing.items()):
        md.append(f"- **{name}** 자료 없는 날짜: {', '.join(days_missing)}")
    if not detail and not fail and not missing:
        md.append("- 기간 내 인스턴스 이상은 없습니다.")
    if top:
        md += ["", "## CPU 상위 프로세스", ""]
        for row in top:
            md.append(f"- `{row['name']}` 평균 {_fmt_pct(row.get('cpu_avg'))}")
    for extra in extras:
        md += ["", f"## {extra['title']}", ""]
        md.append(f"- 자료 {extra.get('days')}일")
        if extra.get("stats"):
            md.append(f"- {_stat_line(extra['stats'])}")
        for field, val in _latest_pairs(extra.get("latest")):
            if field in (extra.get("stats") or {}):
                continue
            md.append(f"- {_field_label(field)}: {_fmt_field(val)}")
        rows = _latest_rows(extra.get("latest"))
        if extra["key"] == "disk_inode" or (rows and "mount" in rows[0]):
            rows = _notable_inode_rows(rows)
        for row in rows[:8]:
            bits = [f"{_field_label(k)} {_fmt_field(v)}" for k, v in row.items() if v not in (None, "")]
            if bits:
                md.append(f"- {', '.join(bits)}")
    markdown = "\n".join(md)

    ai_html = ""
    if ai_summary or ai_risks or ai_actions:
        blocks = [f"<p>{escape(ai_summary)}</p>"] if ai_summary else []
        if ai_risks:
            blocks.append(
                "<p>눈여겨볼 것</p><ul>"
                + "".join(f"<li>{escape(item)}</li>" for item in ai_risks)
                + "</ul>"
            )
        if ai_actions:
            blocks.append(
                "<p>해볼 조치</p><ul>"
                + "".join(f"<li>{escape(item)}</li>" for item in ai_actions)
                + "</ul>"
            )
        ai_html = "<h2>AI 총평</h2>" + "".join(blocks)

    def _tag(level: str, text: str) -> str:
        if not level:
            return escape(text)
        return f'<span class="tag {level}">{escape(text)}</span>'

    def _kpi(label: str, value: str, note: str = "", level: str = "") -> str:
        return (
            f'<div class="kpi {level}"><div class="label">{escape(label)}</div>'
            f'<div class="value">{value}</div>'
            f'{f"<div class=note>{escape(note)}</div>" if note else ""}</div>'
        )

    cpu_level = _pct_level(cpu.get("last"))
    mem_level = _pct_level(mem.get("last"), warn=80, danger=90)
    worst_disk = disks[0] if disks else None
    disk_level, disk_label = _disk_status(worst_disk) if worst_disk else ("", "-")
    live = sum(1 for row in detail if _instance_status(row)[0] == "ok")
    inst_level = "danger" if fail else ("warn" if missing else "ok")

    cpu_note = f"평균 {_fmt_pct(cpu.get('avg'))}"
    if cpu.get("cores") is not None:
        cpu_note += f" · {int(cpu['cores'])}코어"
    mem_bits = []
    if mem.get("used_mb") is not None and mem.get("total_mb") is not None:
        mem_bits.append(f"{_fmt_mb(mem.get('used_mb'))} / {_fmt_mb(mem.get('total_mb'))}")
    if mem.get("available_mb") is not None:
        mem_bits.append(f"여유 {_fmt_mb(mem.get('available_mb'))}")
    if mem.get("swap_total_mb") is not None and float(mem.get("swap_total_mb") or 0) <= 0:
        mem_bits.append("스왑 없음")
    else:
        swap_pct = mem.get("swap_last") if mem.get("swap_last") is not None else mem.get("swap_max")
        if mem.get("swap_used_mb") is not None and mem.get("swap_total_mb") is not None:
            mem_bits.append(
                f"스왑 {_fmt_mb(mem.get('swap_used_mb'))} / {_fmt_mb(mem.get('swap_total_mb'))}"
                + (f" ({_fmt_pct(swap_pct)})" if swap_pct is not None else "")
            )
        elif swap_pct is not None:
            mem_bits.append(f"스왑 {_fmt_pct(swap_pct)}")
        else:
            mem_bits.append("스왑 자료 없음")
    mem_note = " · ".join(mem_bits) or f"평균 {_fmt_pct(mem.get('avg'))}"
    swap_level = _pct_level(
        mem.get("swap_last") if mem.get("swap_last") is not None else mem.get("swap_max"),
        warn=10,
        danger=30,
    )
    mem_level = _worse(mem_level, swap_level)
    kpis = [
        _kpi("CPU 사용률", _fmt_pct(cpu.get("last")), cpu_note, cpu_level),
        _kpi("메모리", _fmt_pct(mem.get("last")), mem_note, mem_level),
    ]
    if worst_disk:
        kpis.append(
            _kpi(
                _disk_alias(str(worst_disk.get("mount") or "디스크")),
                _fmt_pct(worst_disk.get("last")),
                disk_label,
                disk_level,
            )
        )
    if detail or fail:
        kpis.append(_kpi("인스턴스", f"{live}/{len(detail) or len(fail)}", "정상/전체", inst_level))

    disk_rows = []
    for disk in disks:
        level, label = _disk_status(disk)
        left = _fmt_gb(disk.get("free_gb"))
        days_left = f" · {disk['days_to_full']}일 뒤 가득 참" if disk.get("days_to_full") is not None else ""
        disk_rows.append(
            "<tr>"
            f"<td><div class='name'>{escape(_disk_alias(str(disk['mount'])))}</div>"
            f"<div class='sub'>{escape(str(disk['mount']))}</div></td>"
            f"<td>{_tag(level, _fmt_pct(disk.get('last')))}</td>"
            f"<td>{escape(left)}{escape(days_left)}</td>"
            f"<td>{_tag(level, label)}</td>"
            "</tr>"
        )
    disk_html = (
        "<table><thead><tr><th>위치</th><th>사용</th><th>남은 공간</th><th>상태</th></tr></thead><tbody>"
        + "".join(disk_rows)
        + "</tbody></table>"
        if disk_rows
        else "<p class='empty'>디스크 자료가 없습니다.</p>"
    )

    inst_rows = []
    for row in detail:
        level, label = _instance_status(row)
        note = []
        if row.get("fail_days"):
            note.append(f"중단 {row['fail_days']}일")
        if row.get("started_at"):
            note.append(f"기동 {row['started_at']}")
        if row.get("problem"):
            note.append(str(row["problem"]))
        if row.get("cpu_avg") is not None:
            note.append(f"CPU {_fmt_pct(row.get('cpu_avg'))}")
        inst_rows.append(
            "<tr>"
            f"<td class='name'>{escape(row['name'])}</td>"
            f"<td>{_tag(level, label)}</td>"
            f"<td>{escape(' · '.join(note) or '-')}</td>"
            "</tr>"
        )
    inst_html = ""
    if inst_rows:
        inst_html = (
            "<h2>인스턴스</h2><table><thead><tr><th>이름</th><th>상태</th><th>마지막 기동 / 메모</th></tr></thead><tbody>"
            + "".join(inst_rows)
            + "</tbody></table>"
        )

    top_html = ""
    if top:
        top_html = (
            "<h2>지금 바쁜 프로세스</h2><table><thead><tr><th>프로세스</th><th>CPU</th></tr></thead><tbody>"
            + "".join(
                f"<tr><td>{escape(str(row['name']))}</td><td>{_fmt_pct(row.get('cpu_avg'))}</td></tr>"
                for row in top[:5]
            )
            + "</tbody></table>"
        )

    extra_rows = []
    extra_blocks = []
    for extra in extras:
        latest_rows = _latest_rows(extra.get("latest"))
        if extra["key"] == "disk_inode":
            latest_rows = _notable_inode_rows(latest_rows)
        stats = extra.get("stats") or {}
        if extra["key"] in {"os_info", "os_uptime", "os_cloud_meta"}:
            pairs = _latest_pairs(extra.get("latest"))
            extra_rows.append(
                "<tr>"
                f"<td>{escape(extra['title'])}</td>"
                f"<td colspan='2'>{escape(' · '.join(f'{_field_label(k)} {_fmt_field(v)}' for k, v in pairs) or '-')}</td>"
                "</tr>"
            )
        elif stats and extra["key"] != "disk_inode":
            first = next(iter(stats.values()))
            extra_rows.append(
                "<tr>"
                f"<td>{escape(extra['title'])}</td>"
                f"<td>{_tag(first.get('level') or '', _fmt_field(first.get('last')))}</td>"
                f"<td>{escape(_stat_line(stats))}</td>"
                "</tr>"
            )
        if extra["key"] == "disk_inode" and latest_rows:
            extra_blocks.append(
                "<h2>inode</h2><table><thead><tr><th>위치</th><th>사용</th></tr></thead><tbody>"
                + "".join(
                    f"<tr><td>{escape(_disk_alias(str(row.get('mount'))))}</td>"
                    f"<td>{_tag(_field_level('disk_inode', 'inode_pct', row.get('inode_pct')), _fmt_pct(_as_num(row.get('inode_pct'))))}</td></tr>"
                    for row in latest_rows
                )
                + "</tbody></table>"
            )
    extra_html = ""
    if extra_rows:
        extra_html = (
            "<h2>더 본 항목</h2><table><thead><tr><th>항목</th><th>값</th><th>메모</th></tr></thead><tbody>"
            + "".join(extra_rows)
            + "</tbody></table>"
        )
    extra_html += "".join(extra_blocks)
    issues = _issue_lines(cpu, mem, disks, fail, extras)
    issues_html = ""
    if issues:
        issues_html = (
            "<ul class='issues'>"
            + "".join(f"<li>{escape(line)}</li>" for line in issues)
            + "</ul>"
        )
    busy_html = ""
    if busy:
        busy_html = (
            "<p class='meta'>바쁜 시간 · "
            + escape(", ".join(f"{row['hour']}시 CPU {_fmt_pct(row.get('cpu_avg'))}" for row in busy[:2]))
            + "</p>"
        )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --card: #fff;
      --line: #e6e8ee;
      --text: #1d2433;
      --muted: #667085;
      --ok: #067647;
      --ok-bg: #ecfdf3;
      --warn: #b54708;
      --warn-bg: #fffaeb;
      --danger: #b42318;
      --danger-bg: #fef3f2;
    }}
    body {{ font-family: "Segoe UI", "Apple SD Gothic Neo", sans-serif; background: var(--bg); color: var(--text); margin: 0; }}
    .wrap {{ max-width: 880px; margin: 0 auto; padding: 32px 24px 48px; }}
    h1 {{ font-size: 1.45rem; margin: 0 0 6px; }}
    h2 {{ font-size: 0.95rem; margin: 28px 0 10px; color: #344054; }}
    .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 16px; }}
    .verdict {{ display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-radius: 14px; background: var(--card); border: 1px solid var(--line); margin-bottom: 16px; font-weight: 650; }}
    .verdict.ok {{ background: var(--ok-bg); border-color: #abefc6; color: var(--ok); }}
    .verdict.warn {{ background: var(--warn-bg); border-color: #fedf89; color: var(--warn); }}
    .verdict.danger {{ background: var(--danger-bg); border-color: #fecdca; color: var(--danger); }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }}
    .kpi {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; }}
    .kpi.ok {{ border-color: #abefc6; }}
    .kpi.warn {{ border-color: #fedf89; background: var(--warn-bg); }}
    .kpi.danger {{ border-color: #fecdca; background: var(--danger-bg); }}
    .kpi .label {{ color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
    .kpi .value {{ font-size: 1.7rem; font-weight: 700; letter-spacing: -0.03em; }}
    .kpi .note {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--line); font-size: 13px; }}
    th {{ color: var(--muted); font-weight: 600; background: #fafbff; }}
    tr:last-child td {{ border-bottom: 0; }}
    .name {{ font-weight: 650; }}
    .sub {{ color: var(--muted); font-size: 11px; margin-top: 2px; }}
    .tag {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 650; }}
    .tag.ok {{ background: var(--ok-bg); color: var(--ok); }}
    .tag.warn {{ background: var(--warn-bg); color: var(--warn); }}
    .tag.danger {{ background: var(--danger-bg); color: var(--danger); }}
    .empty {{ color: var(--muted); }}
    .issues {{ margin: 0 0 16px; padding-left: 1.2rem; color: var(--danger); }}
    .issues li {{ margin: 0.2rem 0; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{escape(server)} 상태</h1>
    <div class="meta">{escape(start)} ~ {escape(end)} · 자료 {analysis.get('count') or 0}일</div>
    <div class="verdict {overall}">{escape(verdict)}</div>
    {issues_html}
    <div class="kpis">{''.join(kpis)}</div>
    {busy_html}
    {ai_html}
    <h2>디스크</h2>
    {disk_html}
    {inst_html}
    {top_html}
    {extra_html}
  </div>
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
