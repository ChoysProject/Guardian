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
    if cpu is not None:
        item["cpu_pct"] = cpu
    if mem_mb is not None:
        item["mem_mb"] = mem_mb
    if restarts is not None:
        item["restarts"] = restarts
    if pids is not None:
        item["pids"] = pids
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
        swap = _as_pct(_first(mem_raw, "swap_used_pct", "swap_pct"))
        if swap is not None:
            mem_block["swap_used_pct"] = swap
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


def analyze_server(server: str, *, days: int = 7, end: str | None = None) -> dict[str, Any]:
    from app.server_modes import get_instances

    registered = get_instances(server)
    items = snapshots_for(server, days=days, end=end)
    cpu = _series([((item.get("cpu") or {}).get("usage_pct")) for item in items])
    mem = _series([((item.get("mem") or {}).get("used_pct")) for item in items])
    cpu_peak = _series([((item.get("cpu") or {}).get("peak_pct")) for item in items])
    mem_peak = _series([((item.get("mem") or {}).get("peak_pct")) for item in items])
    swap = _series([((item.get("mem") or {}).get("swap_used_pct")) for item in items])
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
                name, {"name": name, "days": 0, "cpu": [], "mem": [], "restarts": 0}
            )
            stat["days"] += 1
            if inst.get("cpu_pct") is not None:
                stat["cpu"].append(float(inst["cpu_pct"]))
            if inst.get("mem_mb") is not None:
                stat["mem"].append(float(inst["mem_mb"]))
            if inst.get("restarts"):
                stat["restarts"] += int(inst["restarts"])
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
            "series": cpu,
        },
        "mem": {
            "avg": _avg(mem),
            "max": max(mem) if mem else None,
            "last": mem[-1] if mem else None,
            "direction": _direction(mem),
            "peak_max": max(mem_peak) if mem_peak else None,
            "swap_max": max(swap) if swap else None,
            "series": mem,
        },
        "disks": disks,
        "busy_hours": _busy_hours(hour_cpu, hour_mem),
        "top_processes": top_processes,
        "instances": registered,
        "instances_detail": instances_detail,
        "instance_fail": instance_fail,
        "instance_missing": instance_missing,
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
    }


def _fmt_gb(value: float | None) -> str:
    return "-" if value is None else f"{value}GB"


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
    if row.get("fail_days"):
        parts.append(f"중단 {row.get('fail_days')}일")
    if row.get("missing_days"):
        parts.append(f"자료 없음 {row.get('missing_days')}일")
    if not row.get("registered"):
        parts.append("등록 안 된 인스턴스")
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
    disks = analysis.get("disks") or []
    busy = analysis.get("busy_hours") or []
    top = analysis.get("top_processes") or []
    detail = analysis.get("instances_detail") or []
    registered = analysis.get("instances") or []
    review = ai or {}
    ai_summary = str(review.get("summary") or "").strip()
    ai_risks = review.get("risks") or []
    ai_actions = review.get("actions") or []

    soonest = [disk for disk in disks if disk.get("days_to_full") is not None]
    soonest.sort(key=lambda disk: disk["days_to_full"])
    summary_bits = [
        f"자료 {analysis.get('count') or 0}일",
        f"CPU {_fmt_pct(cpu.get('last'))} ({cpu.get('direction') or '-'})",
        f"MEM {_fmt_pct(mem.get('last'))} ({mem.get('direction') or '-'})",
    ]
    if soonest:
        first = soonest[0]
        summary_bits.append(f"{first['mount']} 약 {first['days_to_full']}일 뒤 만적")
    if fail:
        summary_bits.append(f"인스턴스 이상 {len(fail)}종")
    if missing:
        summary_bits.append(f"자료 빠진 인스턴스 {len(missing)}종")
    summary = ", ".join(summary_bits)

    md = [
        f"# {title}",
        "",
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
            md.append(f"- `{disk['mount']}` {_disk_line(disk)}")
    else:
        md.append("- 디스크 자료 없음")
    md += ["", "## 인스턴스", ""]
    if registered:
        md.append(f"- 등록한 인스턴스: {', '.join(registered)}")
    for row in detail:
        md.append(f"- **{row['name']}** {_instance_line(row)}")
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

    cpu_rows = [
        f"<li>CPU 평균 {_fmt_pct(cpu.get('avg'))}, 최대 {_fmt_pct(cpu.get('max'))}, 최근 {_fmt_pct(cpu.get('last'))}, 방향 {escape(str(cpu.get('direction')))}</li>",
        f"<li>MEM 평균 {_fmt_pct(mem.get('avg'))}, 최대 {_fmt_pct(mem.get('max'))}, 최근 {_fmt_pct(mem.get('last'))}, 방향 {escape(str(mem.get('direction')))}</li>",
    ]
    if cpu.get("peak_max") is not None:
        cpu_rows.append(
            f"<li>하루 중 최고 CPU {_fmt_pct(cpu.get('peak_max'))}, MEM {_fmt_pct(mem.get('peak_max'))}</li>"
        )
    if mem.get("swap_max") is not None:
        cpu_rows.append(f"<li>스왑 최대 {_fmt_pct(mem.get('swap_max'))}</li>")
    if busy:
        cpu_rows.append(
            "<li>바쁜 시간대: "
            + escape(", ".join(f"{row['hour']}시 CPU {_fmt_pct(row.get('cpu_avg'))}" for row in busy))
            + "</li>"
        )
    cpu_html = "".join(cpu_rows)

    disk_html = "".join(
        f"<li><code>{escape(str(disk['mount']))}</code> {escape(_disk_line(disk))}</li>"
        for disk in disks
    ) or "<li>디스크 자료 없음</li>"

    inst_rows = [f"<li>등록한 인스턴스: {escape(', '.join(registered))}</li>"] if registered else []
    inst_rows += [
        f"<li><strong>{escape(row['name'])}</strong> {escape(_instance_line(row))}</li>"
        for row in detail
    ]
    inst_rows += [
        f"<li><strong>{escape(name)}</strong> 중단 날짜: {escape(', '.join(days_failed))}</li>"
        for name, days_failed in sorted(fail.items())
    ]
    inst_rows += [
        f"<li><strong>{escape(name)}</strong> 자료 없는 날짜: {escape(', '.join(days_missing))}</li>"
        for name, days_missing in sorted(missing.items())
    ]
    if not inst_rows:
        inst_rows.append("<li>기간 내 인스턴스 이상은 없습니다.</li>")
    inst_html = "".join(inst_rows)

    top_html = ""
    if top:
        top_html = "<h2>CPU 상위 프로세스</h2><ul>" + "".join(
            f"<li><code>{escape(str(row['name']))}</code> 평균 {_fmt_pct(row.get('cpu_avg'))}</li>"
            for row in top
        ) + "</ul>"

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
  {ai_html}
  <h2>CPU / MEM</h2>
  <ul>{cpu_html}</ul>
  <h2>Disk</h2>
  <ul>{disk_html}</ul>
  <h2>인스턴스</h2>
  <ul>{inst_html}</ul>
  {top_html}
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
