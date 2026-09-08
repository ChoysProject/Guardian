"""등록한 서버에 SSH 로 붙어 리소스 수집 플러그인을 돌리고 결과를 받아 둔다."""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.plugins.loader import load_manifests, read_script, targets_match
from app.plugins.types import PluginManifest
from app.resources import parse_payload, save_snapshot, today_stamp
from app.secrets_store import decrypt
from app.server_modes import parse_list

logger = logging.getLogger(__name__)

DEFAULT_PLUGIN = "resource_basic"


def resource_plugins(enabled_only: bool = True) -> list[PluginManifest]:
    return [
        item
        for item in load_manifests()
        if item.stage == 4 and (item.enabled or not enabled_only)
    ]


def plugin_for_server(server) -> PluginManifest | None:
    """서버에 끼워 둔 플러그인을 먼저 보고, 없으면 대상이 맞는 것을 쓴다."""
    items = resource_plugins()
    chosen = parse_list(getattr(server, "plugins", "[]"))
    for name in chosen:
        for item in items:
            if item.name == name:
                return item
    for item in items:
        if item.targets and "*" not in item.targets and targets_match(item, server.name):
            return item
    for item in items:
        if item.name == DEFAULT_PLUGIN:
            return item
    return items[0] if items else None


def render_script(manifest: PluginManifest, server) -> str:
    script = read_script(manifest)
    if not script.strip():
        raise ValueError(f"{manifest.name} 플러그인에 수집 스크립트가 없습니다.")
    instances = " ".join(parse_list(getattr(server, "instances", "[]")))
    collect_path = (getattr(server, "collect_path", "") or "").strip().replace("\\", "/").replace('"', "")
    replaced = (
        script.replace("{{server}}", server.name)
        .replace("{{instances}}", instances)
        .replace("{{date}}", today_stamp())
        .replace("{{plugin}}", manifest.name)
    )
    if collect_path:
        replaced = replaced.replace('OUT_DIR="__GUARDIAN_COLLECT_PATH__"', f'OUT_DIR="{collect_path}"', 1)
    return replaced.replace("\r\n", "\n")


def _private_key(server):
    import paramiko

    path = Path(server.key_path or "").expanduser()
    if not server.key_path or not path.exists():
        raise ValueError("등록한 개인키 파일을 찾지 못했습니다.")
    errors = []
    for loader in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return loader.from_private_key_file(str(path))
        except Exception as exc:  # noqa: BLE001 — 키 종류를 차례로 시도
            errors.append(f"{loader.__name__}: {exc}")
    raise ValueError("개인키를 읽지 못했습니다. " + " | ".join(errors))


def _connect(server):
    import paramiko

    if not server.host:
        raise ValueError("호스트(IP)가 비어 있습니다.")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    auth = (server.auth_type or "key").strip()
    password = decrypt(server.password_enc or "") if auth == "password" else ""
    pkey = _private_key(server) if auth == "key" else None
    if auth == "password" and not password:
        raise ValueError("저장된 비밀번호가 없습니다. 서버 수정에서 다시 넣어 주세요.")
    client.connect(
        hostname=server.host,
        port=int(server.port or 22),
        username=server.username or None,
        password=password or None,
        pkey=pkey,
        timeout=settings.collect.ssh_timeout_seconds,
        allow_agent=auth == "agent",
        look_for_keys=auth == "agent",
    )
    return client


def run_remote(server, script: str) -> str:
    """스크립트를 통째로 표준입력에 흘려 넣고 찍힌 내용을 받는다."""
    if (server.collector_type or "ssh") == "local":
        done = subprocess.run(
            ["bash", "-s"],
            input=script,
            capture_output=True,
            text=True,
            timeout=settings.collect.ssh_timeout_seconds * 3,
        )
        if done.stdout.strip():
            return done.stdout
        raise ValueError(f"스크립트 실행 실패: {done.stderr.strip()[:300]}")

    client = _connect(server)
    try:
        stdin, stdout, stderr = client.exec_command(
            "bash -s", timeout=settings.collect.ssh_timeout_seconds * 3
        )
        stdin.write(script)
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            return out
        raise ValueError(f"결과가 비었습니다 (exit {code}). {err.strip()[:300]}")
    finally:
        client.close()


def _extract_json(text: str) -> str:
    body = (text or "").strip()
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("결과에서 JSON을 찾지 못했습니다: " + body[:200])
    return body[start : end + 1]


def collect_server(db, server, *, when: datetime | None = None) -> dict[str, Any]:
    """한 서버에서 리소스를 받아 저장한다. 실패하면 서버에 사유를 남긴다."""
    manifest = plugin_for_server(server)
    if manifest is None:
        raise ValueError("쓸 수 있는 리소스 수집 플러그인이 없습니다.")
    try:
        script = render_script(manifest, server)
        raw = run_remote(server, script)
        try:
            snapshots = parse_payload(
                _extract_json(raw),
                fallback_server=server.name,
                fallback_date=today_stamp(when),
            )
            if not snapshots:
                raise ValueError("받은 자료가 없습니다.")
            snapshot = snapshots[0]
        except Exception as parse_exc:
            snapshot = {
                "server": server.name,
                "date": today_stamp(when),
                "cpu": {"usage_pct": None},
                "mem": {"used_pct": None},
                "disk": [],
                "instances": [],
                "top": [],
                "extra": {"status": "partial", "error": str(parse_exc)[:300]},
            }
        snapshot["server"] = server.name
        save_snapshot(snapshot)
    except Exception as exc:  # noqa: BLE001 — 사유를 화면에 남긴다
        logger.warning("리소스 수집 실패: %s (%s)", server.name, exc)
        server.last_resource_error = str(exc)[:500]
        try:
            save_snapshot(
                {
                    "server": server.name,
                    "date": today_stamp(when),
                    "cpu": {"usage_pct": None},
                    "mem": {"used_pct": None},
                    "disk": [],
                    "instances": [],
                    "top": [],
                    "extra": {"status": "failed", "error": str(exc)[:300]},
                }
            )
        except Exception:  # noqa: BLE001 — 스냅샷 저장까지 실패해도 사유는 남긴다
            pass
        db.commit()
        raise
    server.last_resource_at = datetime.utcnow()
    server.last_resource_error = ""
    db.commit()
    return snapshot


def test_connection(server) -> str:
    """접속만 해 보고 서버가 뭐라고 답하는지 돌려준다."""
    if (server.collector_type or "ssh") == "local":
        return "local 수집기는 접속 확인이 필요 없습니다."
    client = _connect(server)
    try:
        _, stdout, stderr = client.exec_command(
            "uname -a; echo; uptime", timeout=settings.collect.ssh_timeout_seconds
        )
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        return out or err or "응답이 비었습니다."
    finally:
        client.close()


def plugin_names() -> list[str]:
    return [item.name for item in resource_plugins()]


def dump_plugins(names: list[str] | None) -> str:
    cleaned = []
    for name in names or []:
        text = str(name or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return json.dumps(cleaned, ensure_ascii=False)
