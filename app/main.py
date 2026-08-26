from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
from app.plugins import editor as plugin_editor
from app.plugins.loader import load_manifests
from app.plugins.runtime import assigned_plugins
from app.pipeline.runner import collect_and_analyze
from app.scheduler import shutdown_scheduler, start_scheduler
from app.seed import seed_demo

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


def _ctx(request: Request, **extra):
    data = {
        "request": request,
        "app_name": settings.app.name,
        "auth_enabled": settings.auth.enabled,
        "dify_enabled": settings.dify.enabled,
        "report_time": settings.scheduler.daily_report_time,
        "bind": f"{settings.app.host}:{settings.app.port}",
        "collect_lookback_hours": settings.collect.lookback_hours,
        "openai_enabled": bool(settings.openai.enabled and settings.openai.api_key),
    }
    data.update(extra)
    return data


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
    reports = db.query(Report).order_by(Report.created_at.desc()).limit(5).all()
    counts = {
        "servers": len(servers),
        "findings": db.query(Finding).count(),
        "errors": db.query(Finding).filter(Finding.severity == "error").count(),
        "reports": db.query(Report).count(),
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _ctx(request, servers=servers, findings=findings, runs=runs, reports=reports, counts=counts),
    )


@app.get("/servers", response_class=HTMLResponse)
def servers_page(request: Request, db: Session = Depends(get_db)):
    servers = db.query(Server).order_by(Server.name).all()
    bindings = {item.name: assigned_plugins(item.name) for item in servers}
    return templates.TemplateResponse(
        request,
        "servers.html",
        _ctx(request, servers=servers, plugin_bindings=bindings),
    )


@app.post("/servers")
def create_server(
    name: str = Form(...),
    collector_type: str = Form("ssh"),
    host: str = Form(""),
    port: int = Form(22),
    username: str = Form(""),
    key_path: str = Form(""),
    log_paths: str = Form(""),
    db: Session = Depends(get_db),
):
    paths = [item.strip() for item in log_paths.replace(",", "\n").splitlines() if item.strip()]
    server = Server(
        name=name.strip(),
        collector_type=collector_type,
        host=host.strip(),
        port=port,
        username=username.strip(),
        key_path=key_path.strip(),
        log_paths=dump_json(paths),
        enabled=True,
    )
    db.add(server)
    db.commit()
    return RedirectResponse("/servers", status_code=303)


@app.post("/servers/{server_id}/toggle")
def toggle_server(server_id: int, db: Session = Depends(get_db)):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(404)
    server.enabled = not server.enabled
    db.commit()
    return RedirectResponse("/servers", status_code=303)


@app.post("/servers/{server_id}/collect")
def collect_one(server_id: int, db: Session = Depends(get_db)):
    collect_and_analyze(db, server_ids=[server_id])
    return RedirectResponse("/servers", status_code=303)


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
    items = db.query(Report).order_by(Report.created_at.desc()).all()
    enabled_servers = db.query(Server).filter(Server.enabled.is_(True)).order_by(Server.name).all()
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


@app.post("/reports/{report_id}/delete")
def reports_delete(report_id: int, db: Session = Depends(get_db)):
    item = db.get(Report, report_id)
    if not item:
        raise HTTPException(404)
    for path in (item.markdown_path, item.html_path):
        if path:
            file_path = Path(path)
            if file_path.exists():
                file_path.unlink()
    db.delete(item)
    db.commit()
    return RedirectResponse("/reports", status_code=303)


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


@app.get("/plugins", response_class=HTMLResponse)
def plugins_page(request: Request):
    items = load_manifests()
    return templates.TemplateResponse(
        request,
        "plugins.html",
        _ctx(
            request,
            stage2=[item for item in items if item.stage == 2],
            stage3=[item for item in items if item.stage == 3],
        ),
    )


@app.get("/plugins/new", response_class=HTMLResponse)
def plugin_new(request: Request, stage: int = 2, server: str = "", db: Session = Depends(get_db)):
    if stage not in (2, 3):
        stage = 2
    servers = db.query(Server).order_by(Server.name).all()
    bind = server.strip()
    default_name = ""
    if bind:
        safe = bind.replace(".", "_")
        default_name = f"{safe}_rules" if stage == 2 else f"{safe}_report"
    return templates.TemplateResponse(
        request,
        "plugin_new.html",
        _ctx(
            request,
            stage=stage,
            servers=servers,
            error="",
            bind_server=bind,
            default_name=default_name,
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
):
    servers = db.query(Server).order_by(Server.name).all()
    bind = bind_server.strip()
    try:
        targets = _form_targets(all_servers, server_names, target_patterns, bind)
        if stage == 3:
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
        safe = bind.replace(".", "_") if bind else ""
        default_name = f"{safe}_rules" if stage == 2 else f"{safe}_report" if safe else ""
        return templates.TemplateResponse(
            request,
            "plugin_new.html",
            _ctx(
                request,
                stage=stage,
                servers=servers,
                error=str(exc),
                bind_server=bind,
                default_name=name.strip() or default_name,
            ),
            status_code=400,
        )
    return RedirectResponse("/servers" if bind else "/plugins", status_code=303)


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
        _ctx(request, plugin=plugin, servers=servers, extra_targets=extra, error=""),
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
):
    servers = db.query(Server).order_by(Server.name).all()
    try:
        plugin = plugin_editor.get_manifest(stage, name)
        targets = _form_targets(all_servers, server_names, target_patterns)
        rules = None
        config = None
        if plugin.plugin_type == "rules":
            rules = plugin_editor.clean_rules(rule_pattern, rule_severity, rule_signature, rule_min_count)
        if stage == 3:
            config = {"title": title, "mode": mode, "intro": intro}
        plugin_editor.save_plugin(
            stage,
            name,
            enabled=bool(enabled),
            targets=targets,
            description=description,
            rules=rules,
            config=config,
        )
    except (ValueError, KeyError) as exc:
        plugin = plugin_editor.get_manifest(stage, name)
        extra = ", ".join(
            item for item in plugin.targets if item != "*" and item not in {srv.name for srv in servers}
        )
        return templates.TemplateResponse(
            request,
            "plugin_edit.html",
            _ctx(request, plugin=plugin, servers=servers, extra_targets=extra, error=str(exc)),
            status_code=400,
        )
    return RedirectResponse("/plugins", status_code=303)


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
def api_checkpoints(offset: int = 0, limit: int = PAGE_SIZE, db: Session = Depends(get_db)):
    migrate_from_db(db)
    return page_cursors(offset, limit)


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
