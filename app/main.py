from __future__ import annotations

import io
import json
import logging
import os
import time
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.config import ROOT, settings
from app.db import dump_json, get_db, parse_json_list
from app.models import CollectRun, Finding, Report, Server, init_db
from app.charts import chart_summary
from app.cursors import PAGE_SIZE, migrate_from_db, page_cursors
from app.pipeline.reports import generate_reports
from app.resources import (
    SAMPLE_JSON,
    delete_snapshot,
    generate_resource_reports,
    group_resource_report_rows,
    import_snapshots_from_path,
    is_resource_plugin,
    list_snapshots,
    parse_payload,
    save_snapshot,
    snapshot_server_names,
    snapshots_for_name,
    today_stamp,
)
from app.plugins import editor as plugin_editor
from app.plugins.loader import load_manifests, read_script as plugin_script
from app.plugins.runtime import assigned_plugins
from app.pipeline.runner import collect_and_analyze
from app.scheduler import shutdown_scheduler, start_scheduler
from app.seed import seed_demo
from app.resource_script import (
    DATA_FOLDER,
    build_script,
    catalog as resource_catalog,
    clean_search_names,
    default_modules,
    script_folder_name,
)
from app.resource_collect import (
    collect_server,
    dump_plugins,
    plugin_for_server,
    render_script,
    resource_plugins,
    test_connection,
)
from app.secrets_store import delete_key, encrypt, key_label, save_key
from app.server_modes import (
    get_modes,
    migrate_from_file as migrate_modes_from_file,
    set_instances,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


def _fmt_ts(value) -> str:
    if not value:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).replace("T", " ")[:19]


templates.env.filters["ts"] = _fmt_ts


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    from app.models import SessionLocal

    migrate_modes_from_file()
    db = SessionLocal()
    try:
        seed_demo(db)
        if os.environ.get("GUARDIAN_TESTING") != "1":
            collect_and_analyze(db)
    finally:
        db.close()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title=settings.app.name, lifespan=lifespan, dependencies=[Depends(require_auth)])
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


def _service_bind(request: Request) -> str:
    """브라우저가 이 기동 서버에 들어온 주소. 설정 파일의 127.0.0.1 고정값이 아니다."""
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    if host:
        return host
    hostname = request.url.hostname or settings.app.host or "127.0.0.1"
    port = request.url.port or settings.app.port
    if port and int(port) not in (80, 443):
        return f"{hostname}:{port}"
    return str(hostname)


def _ctx(request: Request, **extra):
    data = {
        "request": request,
        "app_name": settings.app.name,
        "auth_enabled": settings.auth.enabled,
        "dify_enabled": settings.dify.enabled,
        "report_time": settings.scheduler.daily_report_time,
        "bind": _service_bind(request),
        "collect_lookback_hours": settings.collect.lookback_hours,
        "openai_enabled": bool(settings.openai.enabled and settings.openai.api_key),
        "error": "",
        "notice": "",
        "saved": 0,
        "tested": "",
    }
    data.update(extra)
    flash = json.dumps(
        {
            "error": str(data.get("error") or ""),
            "notice": str(data.get("notice") or ""),
            "saved": int(data.get("saved") or 0),
            "tested": str(data.get("tested") or ""),
        },
        ensure_ascii=False,
    )
    data["flash_json"] = flash.replace("<", "\\u003c").replace(">", "\\u003e")
    return data


def _resource_servers(db: Session) -> list[Server]:
    return [
        item
        for item in db.query(Server).order_by(Server.name).all()
        if item.collect_resources
    ]


def _resources_page_ctx(request: Request, db: Session, **extra):
    servers = _resource_servers(db)
    groups = list_snapshots()
    group_map = {group["server"]: group for group in groups}
    plugin_map = {item.name: parse_json_list(item.plugins) for item in servers}
    payload = {
        "servers": servers,
        "groups": groups,
        "group_map": group_map,
        "group_map_json": json.dumps(group_map, ensure_ascii=False),
        "plugin_map": plugin_map,
        "resource_plugins": resource_plugins(),
        "today": today_stamp(),
        "sample": json.dumps(SAMPLE_JSON, ensure_ascii=False, indent=2),
        "saved": 0,
        "error": "",
        "notice": "",
        "open_add": False,
    }
    payload.update(extra)
    return _ctx(request, **payload)


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app.name}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    servers = db.query(Server).order_by(Server.name).all()
    findings = (
        db.query(Finding)
        .order_by(Finding.updated_at.desc())
        .limit(20)
        .all()
    )
    runs = db.query(CollectRun).order_by(CollectRun.started_at.desc()).limit(5).all()
    reports = db.query(Report).order_by(Report.created_at.desc()).all()
    resource_reports = [item for item in reports if is_resource_plugin(item.plugin)]
    log_reports = [item for item in reports if not is_resource_plugin(item.plugin)]
    snapshot_names = snapshot_server_names()
    resource_servers = _resource_servers(db)
    report_groups = group_resource_report_rows(
        resource_reports,
        registered=[server.name for server in resource_servers],
        snapshot_names=snapshot_names,
    )
    resource_attention = sum(
        1 for row in report_groups if (row.get("metrics") or {}).get("level") in {"warn", "danger"}
    )
    counts = {
        "servers": len(servers),
        "resource_servers": len(resource_servers),
        "findings": db.query(Finding).count(),
        "errors": db.query(Finding).filter(Finding.severity == "error").count(),
        "reports": len(log_reports),
        "resource_reports": len(resource_reports),
        "resource_attention": resource_attention,
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _ctx(
            request,
            servers=servers,
            findings=findings,
            runs=runs,
            reports=log_reports[:5],
            counts=counts,
            report_groups=report_groups,
        ),
    )


@app.get("/servers")
def servers_root():
    return RedirectResponse("/servers/resources", status_code=307)


@app.get("/servers/logs", response_class=HTMLResponse)
def servers_logs_page(request: Request, db: Session = Depends(get_db)):
    servers = [item for item in db.query(Server).order_by(Server.name).all() if item.collect_logs]
    modes = {item.name: get_modes(item.name) for item in servers}
    return templates.TemplateResponse(
        request,
        "servers.html",
        _ctx(request, servers=servers, server_modes=modes, error=""),
    )


@app.post("/servers/logs")
def create_log_server(
    request: Request,
    name: str = Form(...),
    collector_type: str = Form("ssh"),
    host: str = Form(""),
    port: int = Form(22),
    username: str = Form(""),
    key_path: str = Form(""),
    log_paths: str = Form(""),
    db: Session = Depends(get_db),
):
    servers = [item for item in db.query(Server).order_by(Server.name).all() if item.collect_logs]
    modes = {item.name: get_modes(item.name) for item in servers}
    try:
        clean = name.strip()
        if not clean:
            raise ValueError("서버 이름을 넣어 주세요.")
        exists = db.query(Server).filter(Server.name == clean).one_or_none()
        paths = [item.strip() for item in log_paths.replace(",", "\n").splitlines() if item.strip()]
        if exists:
            # 리소스 쪽에 이미 있는 서버면 로그 수집만 켜 준다.
            exists.collect_logs = True
            exists.log_paths = dump_json(paths) if paths else exists.log_paths
            db.commit()
        else:
            server = Server(
                name=clean,
                collector_type=collector_type,
                host=host.strip(),
                port=port,
                username=username.strip(),
                key_path=key_path.strip(),
                log_paths=dump_json(paths),
                collect_logs=True,
                collect_resources=False,
                enabled=True,
            )
            db.add(server)
            db.commit()
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "servers.html",
            _ctx(request, servers=servers, server_modes=modes, error=str(exc)),
            status_code=400,
        )
    return RedirectResponse("/servers/logs#collecting", status_code=303)


@app.get("/servers/resources", response_class=HTMLResponse)
def servers_resources_page(
    request: Request,
    db: Session = Depends(get_db),
    saved: int = 0,
    notice: str = "",
    error: str = "",
):
    return templates.TemplateResponse(
        request,
        "servers_resources.html",
        _resources_page_ctx(request, db, saved=saved or 0, notice=notice, error=error),
    )


@app.post("/servers/resources/new", response_class=HTMLResponse)
async def create_resource_server(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    collector_type: str = Form("ssh"),
    host: str = Form(""),
    port: int = Form(22),
    username: str = Form(""),
    auth_type: str = Form("key"),
    password: str = Form(""),
    key_path: str = Form(""),
    note: str = Form(""),
    collect_path: str = Form(""),
    plugins: list[str] = Form(default=[]),
    key_file: UploadFile | None = File(default=None),
):
    try:
        clean = name.strip()
        if not clean:
            raise ValueError("서버 이름을 넣어 주세요.")
        if db.query(Server).filter(Server.name == clean).one_or_none():
            raise ValueError(f"이미 있는 이름입니다: {clean}")
        stored_key = await _store_key(clean, auth_type, key_file, key_path)
        server = Server(
            name=clean,
            collector_type=collector_type,
            host=host.strip(),
            port=port,
            username=username.strip(),
            auth_type=auth_type,
            password_enc=encrypt(password) if auth_type == "password" else "",
            key_path=stored_key,
            log_paths=dump_json([]),
            collect_logs=False,
            collect_resources=True,
            instances=json.dumps([], ensure_ascii=False),
            plugins=dump_plugins(plugins),
            note=note.strip(),
            collect_path=collect_path.strip(),
            enabled=True,
        )
        db.add(server)
        db.commit()
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "servers_resources.html",
            _resources_page_ctx(request, db, error=str(exc), open_add=True),
            status_code=400,
        )
    return RedirectResponse("/servers/resources#collecting", status_code=303)


def _clean_names(items: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in items or []:
        for part in str(raw or "").replace(",", "\n").splitlines():
            text = part.strip()
            if text and text not in cleaned:
                cleaned.append(text)
    return cleaned


async def _store_key(server_name: str, auth_type: str, upload: UploadFile | None, typed_path: str) -> str:
    if auth_type != "key":
        return ""
    if upload is not None and (upload.filename or "").strip():
        return save_key(server_name, await upload.read())
    return (typed_path or "").strip()


@app.get("/servers/resources/{server_id}/edit", response_class=HTMLResponse)
def resource_server_edit(
    server_id: int,
    request: Request,
    db: Session = Depends(get_db),
    tested: str = "",
    error: str = "",
    notice: str = "",
):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    manifest = plugin_for_server(server)
    recent = snapshots_for_name(server.name)[:7]
    return templates.TemplateResponse(
        request,
        "server_resource_edit.html",
        _ctx(
            request,
            server=server,
            chosen=parse_json_list(server.plugins),
            resource_plugins=resource_plugins(),
            effective_plugin=manifest.name if manifest else "",
            script_plugin=manifest.name if manifest else "",
            script_text=plugin_script(manifest) if manifest else "",
            key_label=key_label(server.key_path),
            recent=recent,
            tested=tested,
            error=error,
            notice=notice,
        ),
    )


@app.post("/servers/resources/{server_id}/edit", response_class=HTMLResponse)
async def resource_server_save(
    server_id: int,
    request: Request,
    db: Session = Depends(get_db),
    host: str = Form(""),
    port: int = Form(22),
    username: str = Form(""),
    collector_type: str = Form("ssh"),
    auth_type: str = Form("key"),
    password: str = Form(""),
    key_path: str = Form(""),
    note: str = Form(""),
    collect_path: str = Form(""),
    plugins: list[str] = Form(default=[]),
    key_file: UploadFile | None = File(default=None),
):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    server.host = host.strip()
    server.port = port
    server.username = username.strip()
    server.collector_type = collector_type
    server.note = note.strip()
    server.collect_path = collect_path.strip()
    server.collect_resources = True
    server.plugins = dump_plugins(plugins)
    previous_key = server.key_path
    server.auth_type = auth_type
    if auth_type == "key":
        stored = await _store_key(server.name, auth_type, key_file, key_path or previous_key)
        server.key_path = stored
        server.password_enc = ""
    elif auth_type == "password":
        if password.strip():
            server.password_enc = encrypt(password)
        server.key_path = ""
        if previous_key:
            delete_key(previous_key)
    else:
        server.password_enc = ""
        server.key_path = ""
    db.commit()
    return RedirectResponse(f"/servers/resources/{server_id}/edit", status_code=303)


@app.post("/servers/resources/{server_id}/delete")
def resource_server_delete(server_id: int, db: Session = Depends(get_db)):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    if server.collect_logs:
        # 로그 수집도 하는 서버면 리소스 수집 대상에서만 제거한다.
        server.collect_resources = False
        db.commit()
    else:
        if server.key_path:
            delete_key(server.key_path)
        db.delete(server)
        db.commit()
    return RedirectResponse("/servers/resources#collecting", status_code=303)


@app.post("/servers/resources/{server_id}/collect", response_class=HTMLResponse)
def resource_server_collect(server_id: int, request: Request, db: Session = Depends(get_db)):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    try:
        snapshot = collect_server(db, server)
    except Exception as exc:  # noqa: BLE001 — 사유를 화면에 그대로 보여 준다
        return RedirectResponse(
            f"/servers/resources?error={quote(f'{server.name} 수집 실패: {exc}')}#collecting",
            status_code=303,
        )
    notice = quote(f"{server.name} · {snapshot.get('date')} 자료를 받았습니다.")
    return RedirectResponse(f"/servers/resources?notice={notice}#collecting", status_code=303)


@app.post("/servers/resources/{server_id}/test")
def resource_server_test(server_id: int, db: Session = Depends(get_db)):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    try:
        result = quote(test_connection(server)[:400])
        return RedirectResponse(
            f"/servers/resources/{server_id}/edit?tested={result}", status_code=303
        )
    except Exception as exc:  # noqa: BLE001 — 접속 실패 사유를 보여 준다
        return RedirectResponse(
            f"/servers/resources/{server_id}/edit?error={quote(str(exc)[:400])}", status_code=303
        )


@app.post("/servers/resources/{server_id}/clear-error")
def resource_server_clear_error(server_id: int, db: Session = Depends(get_db)):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    server.last_resource_error = ""
    db.commit()
    return RedirectResponse(f"/servers/resources/{server_id}/edit", status_code=303)


@app.post("/servers/resources/{server_id}/reload-path", response_class=HTMLResponse)
def resource_server_reload_path(server_id: int, request: Request, db: Session = Depends(get_db)):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    referer = request.headers.get("referer", "")
    back_to_edit = f"/servers/resources/{server_id}/edit" in referer
    try:
        saved, errors = import_snapshots_from_path(server.name, server.collect_path)
    except ValueError as exc:
        server.last_resource_error = str(exc)[:500]
        db.commit()
        if back_to_edit:
            return RedirectResponse(
                f"/servers/resources/{server_id}/edit?error={quote(str(exc)[:400])}", status_code=303
            )
        return RedirectResponse(
            f"/servers/resources?error={quote(f'{server.name}: ' + str(exc)[:400])}#collecting",
            status_code=303,
        )
    server.last_resource_at = datetime.utcnow()
    server.last_resource_error = "; ".join(errors)[:500] if errors else ""
    db.commit()
    notice = quote(f"수집 경로에서 {saved}건을 다시 가져왔습니다." + (f" ({len(errors)}건 실패)" if errors else ""))
    if back_to_edit:
        return RedirectResponse(f"/servers/resources/{server_id}/edit?notice={notice}", status_code=303)
    return RedirectResponse(f"/servers/resources?notice={notice}#collecting", status_code=303)


def _script_zip(folder: str, script: str) -> bytes:
    buf = io.BytesIO()
    now = time.localtime()[:6]
    script_info = zipfile.ZipInfo(f"{folder}/collect.sh")
    script_info.date_time = now
    script_info.external_attr = 0o755 << 16
    data_info = zipfile.ZipInfo(f"{folder}/{DATA_FOLDER}/.keep")
    data_info.date_time = now
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(script_info, script.replace("\r\n", "\n"))
        zf.writestr(data_info, "")
    return buf.getvalue()


@app.get("/servers/resources/{server_id}/script.sh")
def resource_server_script(server_id: int, db: Session = Depends(get_db)):
    """스크립트 폴더(이름/collect.sh + DailyData/)를 zip 으로 내려 준다."""
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    manifest = plugin_for_server(server)
    if manifest is None:
        raise HTTPException(404, "쓸 수 있는 리소스 수집 플러그인이 없습니다.")
    try:
        body = render_script(manifest, server)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    folder = script_folder_name(manifest.name)
    return Response(
        _script_zip(folder, body),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder}.zip"'},
    )


@app.post("/servers/resources/{server_id}/script")
def resource_server_script_save(
    server_id: int,
    db: Session = Depends(get_db),
    script: str = Form(""),
):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    manifest = plugin_for_server(server)
    if manifest is None:
        return RedirectResponse(
            f"/servers/resources/{server_id}/edit?error={quote('쓸 수 있는 리소스 수집 플러그인이 없습니다.')}",
            status_code=303,
        )
    try:
        plugin_editor.write_script(Path(manifest.path), script)
    except ValueError as exc:
        return RedirectResponse(
            f"/servers/resources/{server_id}/edit?error={quote(str(exc)[:400])}", status_code=303
        )
    notice = quote(f"{manifest.name} 수집 스크립트를 저장했습니다.")
    return RedirectResponse(
        f"/servers/resources/{server_id}/edit?notice={notice}", status_code=303
    )


@app.post("/servers/resources", response_class=HTMLResponse)
async def servers_resources_upload(
    request: Request,
    db: Session = Depends(get_db),
    server: str = Form(""),
    date: str = Form(""),
    payload: str = Form(""),
    bind_server: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    texts: list[str] = []
    if payload.strip():
        texts.append(payload)
    for upload in files:
        filename = (upload.filename or "").strip()
        if not filename:
            continue
        raw = await upload.read()
        try:
            texts.append(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            return templates.TemplateResponse(
                request,
                "servers_resources.html",
                _resources_page_ctx(request, db, error=f"{filename} 을 읽을 수 없습니다: {exc}"),
                status_code=400,
            )
    saved = 0
    try:
        if not texts:
            raise ValueError("올릴 JSON 파일을 선택하세요.")
        for text in texts:
            for snapshot in parse_payload(text, fallback_server=bind_server or server, fallback_date=date):
                if bind_server.strip():
                    snapshot["server"] = bind_server.strip()
                save_snapshot(snapshot)
                saved += 1
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "servers_resources.html",
            _resources_page_ctx(request, db, error=str(exc)),
            status_code=400,
        )
    return RedirectResponse(f"/servers/resources?saved={saved}", status_code=303)


@app.post("/servers/resources/delete")
def servers_resources_delete(
    request: Request,
    server: str = Form(...),
    date: str = Form(...),
    db: Session = Depends(get_db),
):
    delete_snapshot(server, date)
    referer = request.headers.get("referer", "")
    row = db.query(Server).filter(Server.name == server).one_or_none()
    if row and f"/servers/resources/{row.id}/edit" in referer:
        return RedirectResponse(f"/servers/resources/{row.id}/edit", status_code=303)
    return RedirectResponse("/servers/resources", status_code=303)


@app.post("/servers/{server_id}/instances")
def update_instances(
    server_id: int,
    instances: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    set_instances(server.name, instances)
    return RedirectResponse("/servers/logs#collecting", status_code=303)


@app.post("/servers/{server_id}/toggle")
def toggle_server(server_id: int, db: Session = Depends(get_db)):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    server.enabled = not server.enabled
    db.commit()
    return RedirectResponse("/servers/logs#collecting", status_code=303)


@app.post("/servers/{server_id}/collect")
def collect_one(server_id: int, db: Session = Depends(get_db)):
    collect_and_analyze(db, server_ids=[server_id])
    return RedirectResponse("/servers/logs#collecting", status_code=303)


@app.post("/collect")
def collect_all(db: Session = Depends(get_db)):
    collect_and_analyze(db)
    return RedirectResponse("/", status_code=303)


@app.get("/findings", response_class=HTMLResponse)
def findings_page(request: Request, db: Session = Depends(get_db)):
    items = db.query(Finding).order_by(Finding.updated_at.desc()).limit(200).all()
    servers = {server.id: server.name for server in db.query(Server).all()}
    rows = []
    for item in items:
        rows.append(
            {
                "finding": item,
                "server_name": servers.get(item.server_id, str(item.server_id)),
                "samples": parse_json_list(item.sample_lines),
            }
        )
    return templates.TemplateResponse(request, "findings.html", _ctx(request, rows=rows))


@app.get("/findings/{finding_id}", response_class=HTMLResponse)
def finding_detail(finding_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(Finding, finding_id)
    if not item:
        raise HTTPException(404)
    server = db.get(Server, item.server_id)
    return templates.TemplateResponse(
        request,
        "finding_detail.html",
        _ctx(
            request,
            finding=item,
            server=server,
            samples=parse_json_list(item.sample_lines),
        ),
    )


@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, db: Session = Depends(get_db)):
    items = [
        item
        for item in db.query(Report).order_by(Report.created_at.desc()).all()
        if not is_resource_plugin(item.plugin)
    ]
    enabled_servers = [
        item
        for item in db.query(Server).filter(Server.enabled.is_(True)).order_by(Server.name).all()
        if get_modes(item.name)["logs"]
    ]
    return templates.TemplateResponse(
        request,
        "reports.html",
        _ctx(request, reports=items, enabled_servers=enabled_servers),
    )


@app.post("/reports/generate")
def reports_generate(
    db: Session = Depends(get_db),
    selecting: str = Form(""),
    servers: list[str] = Form(default=[]),
):
    names = [item for item in servers if item] if selecting else None
    generate_reports(db, server_names=names)
    return RedirectResponse("/reports", status_code=303)


@app.get("/reports/resources", response_class=HTMLResponse)
def reports_resources_page(request: Request, db: Session = Depends(get_db)):
    items = [
        item
        for item in db.query(Report).order_by(Report.created_at.desc()).all()
        if is_resource_plugin(item.plugin)
    ]
    snapshot_names = snapshot_server_names()
    registered = [server.name for server in _resource_servers(db)]
    return templates.TemplateResponse(
        request,
        "reports_resources.html",
        _ctx(
            request,
            reports=items,
            report_groups=group_resource_report_rows(
                items, registered=registered, snapshot_names=snapshot_names
            ),
            resource_servers=snapshot_names,
            days=7,
        ),
    )


@app.post("/reports/resources/generate")
def reports_resources_generate(
    db: Session = Depends(get_db),
    selecting: str = Form(""),
    servers: list[str] = Form(default=[]),
):
    names = [item for item in servers if item] if selecting else None
    generate_resource_reports(db, server_names=names, days=7)
    return RedirectResponse("/reports/resources", status_code=303)


def _remove_report(db: Session, item: Report) -> None:
    for path in (item.markdown_path, item.html_path):
        if path:
            file_path = Path(path)
            if file_path.exists():
                file_path.unlink()
    db.delete(item)


def _reports_after_delete(plugin: str | None, count: int) -> str:
    target = "/reports/resources" if is_resource_plugin(plugin) else "/reports"
    return f"{target}?toast=deleted&count={count}"


@app.post("/reports/delete")
def reports_delete_many(
    db: Session = Depends(get_db),
    report_ids: list[int] = Form(default=[]),
):
    removed = 0
    plugin = None
    for report_id in report_ids:
        item = db.get(Report, report_id)
        if not item:
            continue
        if plugin is None:
            plugin = item.plugin
        _remove_report(db, item)
        removed += 1
    if not removed:
        return RedirectResponse("/reports/resources?toast=delete_none", status_code=303)
    db.commit()
    return RedirectResponse(_reports_after_delete(plugin, removed), status_code=303)


@app.post("/reports/{report_id}/delete")
def reports_delete(report_id: int, db: Session = Depends(get_db)):
    item = db.get(Report, report_id)
    if not item:
        raise HTTPException(404)
    plugin = item.plugin
    _remove_report(db, item)
    db.commit()
    return RedirectResponse(_reports_after_delete(plugin, 1), status_code=303)


@app.get("/reports/{report_id}/embed", response_class=HTMLResponse)
def report_embed(report_id: int, db: Session = Depends(get_db)):
    item = db.get(Report, report_id)
    if not item or not is_resource_plugin(item.plugin):
        raise HTTPException(404)
    if item.html_path and Path(item.html_path).exists():
        return HTMLResponse(Path(item.html_path).read_text(encoding="utf-8"))
    raise HTTPException(404)


@app.get("/reports/{report_id}", response_class=HTMLResponse)
def report_detail(report_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(Report, report_id)
    if not item:
        raise HTTPException(404)
    markdown = ""
    html = ""
    if item.markdown_path and Path(item.markdown_path).exists():
        markdown = Path(item.markdown_path).read_text(encoding="utf-8")
    if item.html_path and Path(item.html_path).exists():
        html = Path(item.html_path).read_text(encoding="utf-8")
    return templates.TemplateResponse(
        request,
        "report_detail.html",
        _ctx(request, report=item, markdown=markdown, html=html),
    )


def _form_targets(
    all_servers: str,
    server_names: list[str],
    target_patterns: str,
    bind_server: str = "",
) -> list[str]:
    if all_servers:
        return ["*"]
    names = [item.strip() for item in server_names if item.strip()]
    extra = [item.strip() for item in (target_patterns or "").replace("\n", ",").split(",") if item.strip()]
    bound = bind_server.strip()
    if bound and bound not in names:
        names.append(bound)
    return names + extra or (["*"] if not bound else [bound])


@app.get("/plugins")
def plugins_root():
    return RedirectResponse("/plugins/resources", status_code=307)


def _plugins_page(request: Request, kind: str, **extra):
    items = load_manifests()
    payload = {
        "kind": kind,
        "stage2": [item for item in items if item.stage == 2],
        "stage3": [item for item in items if item.stage == 3],
        "stage4": [item for item in items if item.stage == 4],
        "error": "",
        "form_name": "",
        "form_description": "",
        "plugin_instances": [],
        "module_catalog": resource_catalog() if kind == "resources" else [],
        "selected_modules": default_modules() if kind == "resources" else [],
        "preview_script": "",
    }
    if kind == "resources" and not extra.get("preview_script"):
        script, _ = build_script(payload["selected_modules"], plugin_name=payload.get("form_name") or "resource")
        payload["preview_script"] = script
    payload.update(extra)
    return templates.TemplateResponse(request, "plugins.html", _ctx(request, **payload))


@app.get("/plugins/resources", response_class=HTMLResponse)
def plugins_resources_page(request: Request):
    return _plugins_page(request, "resources")


@app.get("/plugins/logs", response_class=HTMLResponse)
def plugins_logs_page(request: Request):
    return _plugins_page(request, "logs")


@app.get("/plugins/resource-plugins", response_class=HTMLResponse)
def plugins_resource_plugins_page(request: Request):
    return templates.TemplateResponse(request, "plugins_resource.html", _ctx(request))


def _default_plugin_name(stage: int, bind: str) -> str:
    if not bind:
        return ""
    safe = bind.replace(".", "_")
    if stage == 3:
        return f"{safe}_report"
    if stage == 4:
        return f"{safe}_resource"
    return f"{safe}_rules"


@app.get("/plugins/new", response_class=HTMLResponse)
def plugin_new(request: Request, stage: int = 2, server: str = "", db: Session = Depends(get_db)):
    if stage not in (2, 3, 4):
        stage = 2
    servers = db.query(Server).order_by(Server.name).all()
    bind = server.strip()
    base_script = ""
    if stage == 4:
        sample = ROOT / "plugins" / "stage4" / "resource_basic" / "collect.sh"
        base_script = sample.read_text(encoding="utf-8") if sample.exists() else ""
    return templates.TemplateResponse(
        request,
        "plugin_new.html",
        _ctx(
            request,
            stage=stage,
            servers=servers,
            error="",
            bind_server=bind,
            default_name=_default_plugin_name(stage, bind),
            script=base_script,
        ),
    )


@app.post("/plugins/new", response_class=HTMLResponse)
def plugin_create(
    request: Request,
    db: Session = Depends(get_db),
    stage: int = Form(2),
    name: str = Form(...),
    description: str = Form(""),
    title: str = Form(""),
    mode: str = Form("all"),
    all_servers: str = Form(""),
    server_names: list[str] = Form(default=[]),
    target_patterns: str = Form(""),
    bind_server: str = Form(""),
    rule_pattern: list[str] = Form(default=[]),
    rule_severity: list[str] = Form(default=[]),
    rule_signature: list[str] = Form(default=[]),
    rule_min_count: list[str] = Form(default=[]),
    script: str = Form(""),
    modules: list[str] = Form(default=[]),
    plugin_instances: list[str] = Form(default=[]),
):
    servers = db.query(Server).order_by(Server.name).all()
    bind = bind_server.strip()
    searches = clean_search_names(plugin_instances)
    try:
        targets = _form_targets(all_servers or ("1" if stage == 4 and not bind else ""), server_names, target_patterns, bind)
        if stage == 4:
            body = script
            chosen = [item.strip() for item in modules if item.strip()]
            if chosen:
                body, _ = build_script(chosen, instances=searches, plugin_name=name.strip())
            if not body.strip():
                raise ValueError("수집할 모듈을 하나 이상 고르거나 스크립트를 넣어 주세요.")
            plugin_editor.create_resource_plugin(
                name.strip(),
                description=description,
                targets=targets or ["*"],
                script=body,
                config={"modules": chosen or default_modules(), "instances": searches},
            )
        elif stage == 3:
            plugin_editor.create_report_plugin(
                name.strip(),
                description=description,
                targets=targets,
                title=title or (f"{bind} 일일 보고서" if bind else ""),
                mode=mode,
            )
        else:
            rules = plugin_editor.clean_rules(rule_pattern, rule_severity, rule_signature, rule_min_count)
            plugin_editor.create_rules_plugin(
                name.strip(),
                description=description,
                targets=targets,
                rules=rules,
            )
    except (ValueError, FileExistsError, KeyError) as exc:
        if stage == 4 and not bind:
            chosen = [item.strip() for item in modules if item.strip()] or default_modules()
            preview, _ = build_script(chosen, instances=searches, plugin_name=name.strip())
            return _plugins_page(
                request,
                "resources",
                error=str(exc),
                form_name=name.strip(),
                form_description=description,
                plugin_instances=searches,
                selected_modules=chosen,
                preview_script=preview,
            )
        return templates.TemplateResponse(
            request,
            "plugin_new.html",
            _ctx(
                request,
                stage=stage,
                servers=servers,
                error=str(exc),
                bind_server=bind,
                default_name=name.strip() or _default_plugin_name(stage, bind),
                script=script,
            ),
            status_code=400,
        )
    if stage == 4:
        return RedirectResponse("/plugins/resources", status_code=303)
    return RedirectResponse("/servers/logs" if bind else "/plugins/logs", status_code=303)


def _preview_script(modules: list[str], instances: list[str], name: str) -> tuple[str, list[str], list[str], list[str]]:
    chosen = [item.strip() for item in modules if item.strip()] or default_modules()
    searches = clean_search_names(instances)
    script, skipped = build_script(chosen, instances=searches, plugin_name=name)
    return script, skipped, chosen, searches


@app.get("/plugins/resources/preview")
def plugins_resources_preview(
    modules: list[str] = Query(default=[]),
    instances: list[str] = Query(default=[]),
    name: str = Query(""),
):
    script, skipped, chosen, searches = _preview_script(modules, instances, name)
    return {"script": script, "skipped": skipped, "modules": chosen, "instances": searches}


@app.get("/plugins/resources/preview.zip")
def plugins_resources_preview_zip(
    modules: list[str] = Query(default=[]),
    instances: list[str] = Query(default=[]),
    name: str = Query(""),
):
    script, _, _, _ = _preview_script(modules, instances, name)
    folder = script_folder_name(name)
    return Response(
        _script_zip(folder, script),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder}.zip"'},
    )


@app.get("/plugins/{stage}/{name}", response_class=HTMLResponse)
def plugin_edit(stage: int, name: str, request: Request, db: Session = Depends(get_db)):
    try:
        plugin = plugin_editor.get_manifest(stage, name)
    except KeyError:
        raise HTTPException(404)
    servers = db.query(Server).order_by(Server.name).all()
    known = {item.name for item in servers}
    extra = ", ".join(item for item in plugin.targets if item != "*" and item not in known)
    return templates.TemplateResponse(
        request,
        "plugin_edit.html",
        _ctx(
            request,
            plugin=plugin,
            servers=servers,
            extra_targets=extra,
            script=plugin_editor.read_script(stage, name) if stage == 4 else "",
            module_catalog=resource_catalog() if stage == 4 else [],
            selected_modules=((plugin.config or {}).get("modules") or default_modules()) if stage == 4 else [],
            plugin_instances=clean_search_names((plugin.config or {}).get("instances") or []) if stage == 4 else [],
            preview_script=plugin_editor.read_script(stage, name) if stage == 4 else "",
            error="",
        ),
    )


@app.get("/plugins/{stage}/{name}/script.zip")
def plugin_script_zip(stage: int, name: str):
    if stage != 4:
        raise HTTPException(404)
    try:
        plugin_editor.get_manifest(stage, name)
    except KeyError:
        raise HTTPException(404)
    body = plugin_editor.read_script(stage, name)
    if not body.strip():
        raise HTTPException(404, "수집 스크립트가 없습니다.")
    folder = script_folder_name(name)
    return Response(
        _script_zip(folder, body),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder}.zip"'},
    )


@app.post("/plugins/{stage}/{name}", response_class=HTMLResponse)
def plugin_save(
    stage: int,
    name: str,
    request: Request,
    db: Session = Depends(get_db),
    enabled: str = Form(""),
    description: str = Form(""),
    all_servers: str = Form(""),
    server_names: list[str] = Form(default=[]),
    target_patterns: str = Form(""),
    title: str = Form(""),
    mode: str = Form("all"),
    intro: str = Form(""),
    rule_pattern: list[str] = Form(default=[]),
    rule_severity: list[str] = Form(default=[]),
    rule_signature: list[str] = Form(default=[]),
    rule_min_count: list[str] = Form(default=[]),
    script: str = Form(""),
    modules: list[str] = Form(default=[]),
    plugin_instances: list[str] = Form(default=[]),
):
    servers = db.query(Server).order_by(Server.name).all()
    try:
        plugin = plugin_editor.get_manifest(stage, name)
        targets = ["*"] if stage == 4 else _form_targets(all_servers, server_names, target_patterns)
        rules = None
        config = None
        body = script
        if plugin.plugin_type == "rules":
            rules = plugin_editor.clean_rules(rule_pattern, rule_severity, rule_signature, rule_min_count)
        if stage == 3:
            config = {"title": title, "mode": mode, "intro": intro}
        if stage == 4:
            chosen = [item.strip() for item in modules if item.strip()]
            searches = clean_search_names(plugin_instances)
            if chosen:
                body, _ = build_script(chosen, instances=searches, plugin_name=name)
            config = {"modules": chosen or (plugin.config or {}).get("modules") or [], "instances": searches}
        plugin_editor.save_plugin(
            stage,
            name,
            enabled=True if stage == 4 else bool(enabled),
            targets=targets,
            description=description,
            rules=rules,
            config=config,
            script=body if stage == 4 else None,
        )
    except (ValueError, KeyError) as exc:
        plugin = plugin_editor.get_manifest(stage, name)
        extra = ", ".join(
            item for item in plugin.targets if item != "*" and item not in {srv.name for srv in servers}
        )
        return templates.TemplateResponse(
            request,
            "plugin_edit.html",
            _ctx(
                request,
                plugin=plugin,
                servers=servers,
                extra_targets=extra,
                script=script,
                module_catalog=resource_catalog() if stage == 4 else [],
                selected_modules=modules if stage == 4 else [],
                plugin_instances=clean_search_names(plugin_instances) if stage == 4 else [],
                preview_script=script,
                error=str(exc),
            ),
            status_code=400,
        )
    return RedirectResponse("/plugins/resources" if stage == 4 else "/plugins/logs", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    safe = {
        "config_path": str(settings.config_path),
        "host": settings.app.host,
        "port": settings.app.port,
        "timezone": settings.app.timezone,
        "auth_enabled": settings.auth.enabled,
        "openai_enabled": bool(settings.openai.enabled and settings.openai.api_key),
        "openai_model": settings.openai.model,
        "dify_enabled": settings.dify.enabled,
        "collect_interval": settings.collect.interval_seconds,
        "daily_report_time": settings.scheduler.daily_report_time,
        "plugin_dir": str(settings.plugin_path),
    }
    return templates.TemplateResponse(
        request,
        "settings.html",
        _ctx(request, cfg=safe, cfg_json=json.dumps(safe, ensure_ascii=False, indent=2)),
    )


@app.get("/api/findings")
def api_findings(db: Session = Depends(get_db)):
    items = db.query(Finding).order_by(Finding.updated_at.desc()).limit(200).all()
    return [
        {
            "id": item.id,
            "host": item.host,
            "severity": item.severity,
            "signature": item.signature,
            "count": item.count,
            "plugin": item.plugin,
            "ai_comment": item.ai_comment,
            "sample_lines": parse_json_list(item.sample_lines),
            "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
        }
        for item in items
    ]


@app.get("/api/charts/summary")
def api_charts_summary(granularity: str = "hour", db: Session = Depends(get_db)):
    return chart_summary(db, granularity)


@app.get("/api/checkpoints")
def api_checkpoints(
    offset: int = 0,
    limit: int = PAGE_SIZE,
    server_id: int | None = None,
    db: Session = Depends(get_db),
):
    migrate_from_db(db)
    return page_cursors(offset, limit, server_id=server_id)


@app.get("/api/servers")
def api_servers(db: Session = Depends(get_db)):
    return [
        {
            "id": item.id,
            "name": item.name,
            "collector_type": item.collector_type,
            "host": item.host,
            "enabled": item.enabled,
            "last_collect_at": item.last_collect_at.isoformat() if item.last_collect_at else None,
            "last_error": item.last_error,
            "log_paths": parse_json_list(item.log_paths),
        }
        for item in db.query(Server).all()
    ]
