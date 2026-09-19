import re

from fastapi.testclient import TestClient

from app.main import app


def test_health_and_dashboard_and_pipeline():
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        home = client.get("/")
        assert home.status_code == 200
        assert "Guardian" in home.text
        assert "guardian-brand" in home.text
        assert "Goodmorning" not in home.text
        assert "감시 현황" in home.text
        assert "전체 현황" in home.text
        assert "overview-headline" in home.text
        assert "chartOverviewHealth" in home.text
        assert "AI 전체 총평" in home.text
        assert "전체 총평 다시 만들기" not in home.text
        assert "전체 총평 만들기" not in home.text
        assert 'href="#section-resources"' in home.text
        assert 'href="#section-logs"' in home.text
        assert 'sidenav-menu-heading">감시' not in home.text
        assert "로컬 서비스" in home.text
        assert "testserver" in home.text
        reached = client.get("/", headers={"host": "10.20.30.40:8080"})
        assert reached.status_code == 200
        assert "10.20.30.40:8080" in reached.text
        assert "리소스 및 성능" in home.text
        assert "로그 수집 대상 서버" in home.text
        assert 'href="/servers/logs"' in home.text
        assert 'href="/reports"' in home.text
        assert "로그 분석 보고서" in home.text
        assert "로그 분석 보고서 (추후 고도화)" not in home.text
        assert ">로그분석<" in home.text or "<span>로그분석</span>" in home.text
        assert 'id="chartRealtimeTrend"' in home.text
        assert 'id="trend-empty"' in home.text
        assert "guardian-charts.js?v=trend-info-1" in home.text
        assert 'data-kind="log"' in home.text
        assert "아직 로그분석이 없습니다. 수집 뒤에 보고서 화면에서 만드세요." not in home.text
        assert "리소스 및 성능 플러그인" not in home.text
        assert "리소스 및 성능 쉘 스크립트" in home.text
        assert 'href="/plugins/logs"' in home.text
        assert "로그 분석 플러그인 (추후 고도화)" not in home.text
        assert "js-soon" not in home.text

        collected = client.post("/collect", follow_redirects=True)
        assert collected.status_code == 200
        home_after = client.get("/")
        assert home_after.status_code == 200
        assert 'data-kind="log"' in home_after.text
        assert "ERROR" in home_after.text
        assert "징후" in home_after.text
        assert "전체 현황" in home_after.text
        assert "위험" in home_after.text
        assert 'id="card-log-' in home_after.text or 'id="card-resource-' in home_after.text
        assert "#card-log-" in home_after.text or "#section-logs" in home_after.text
        reviewed = client.post("/overview/review", follow_redirects=True)
        assert reviewed.status_code == 200
        assert "전체 현황" in reviewed.text
        assert "finding-table-dash" in home_after.text
        assert "finding-signature" in home_after.text

        findings = client.get("/api/findings")
        assert findings.status_code == 200
        body = findings.json()
        assert body, "데모 로그에서 Finding이 나와야 합니다"
        plugins = {item["plugin"] for item in body}
        assert any(name.startswith("stage1.") for name in plugins)
        assert "stage1.auth_failures" in plugins
        assert "stage1.disk_full" in plugins
        findings_page = client.get("/findings")
        assert findings_page.status_code == 200
        assert 'id="finding-search"' in findings_page.text
        assert "<th>AI</th>" not in findings_page.text
        assert "guardian-findings.js" in findings_page.text
        assert "data-finding-severity" in findings_page.text
        assert "finding-signature" in findings_page.text
        assert "신규" not in findings_page.text
        assert "열린" in findings_page.text
        assert "읽음" in findings_page.text
        fid = body[0]["id"]
        marked = client.post(f"/findings/{fid}/read", follow_redirects=True)
        assert marked.status_code == 200
        assert f'data-finding-id="{fid}"' in marked.text
        assert 'data-read="1"' in marked.text
        assert "징후를 읽음으로 두었습니다" in marked.text
        opened = client.post(f"/findings/{fid}/unread", follow_redirects=True)
        assert opened.status_code == 200
        assert "징후를 다시 열었습니다" in opened.text
        detail_src = next(
            (item for item in body if any(
                len(str(line)) >= 8 and "events in 60s window" not in str(line)
                for line in (item.get("sample_lines") or [])
            )),
            body[0],
        )
        detail = client.get(f"/findings/{detail_src['id']}")
        assert detail.status_code == 200
        assert "2단계 세부 플러그인으로 만들기" in detail.text
        assert "수집 때마다 AI를 부르지 않습니다" in detail.text
        assert "AI가 꺼져 있거나 호출에 실패했습니다" not in detail.text
        from_finding = client.get(f"/plugins/new?stage=2&finding={detail_src['id']}")
        assert from_finding.status_code == 200
        assert "2단계 세부 플러그인" in from_finding.text
        assert "phrases" in from_finding.text
        assert "수집된 ERROR/WARN 줄" in from_finding.text or "찾을 문구" in from_finding.text

        reports_page = client.get("/reports")
        assert reports_page.status_code == 200
        assert "demo-local" in reports_page.text
        assert "보고서 생성" in reports_page.text
        assert "박스를 누르면" in reports_page.text
        assert "오늘 보고서 생성" not in reports_page.text
        assert "선택 생성" not in reports_page.text
        assert "최근 보고서" not in reports_page.text
        assert "자료 있는 서버 모두 만들기" not in reports_page.text
        assert 'href="/servers/logs/' in reports_page.text
        assert 'id="reportFidget"' in reports_page.text
        assert "js-report-generate" in reports_page.text
        assert "guardian-report-fidget.js" in reports_page.text
        assert "guardian-resource-reports.js" in reports_page.text
        assert "resourceReportModal" in reports_page.text
        assert 'id="guardianConfirmModal"' in reports_page.text
        assert "guardian-ui.js" in reports_page.text
        generated = client.post(
            "/reports/generate",
            data={"selecting": "1", "servers": "demo-local"},
            follow_redirects=True,
        )
        assert generated.status_code == 200
        assert "보고서" in generated.text
        assert "server_report:demo-local" in generated.text
        assert "js-report-delete" in generated.text
        from app.models import Report, SessionLocal
        with SessionLocal() as db:
            stored = (
                db.query(Report)
                .filter(Report.plugin == "server_report:demo-local")
                .order_by(Report.id.desc())
                .first()
            )
        assert stored is not None
        assert stored.plugin.startswith("server_report:")
        assert not stored.plugin.startswith("resource_report")
        embedded = client.get(f"/reports/{stored.id}/embed")
        assert embedded.status_code == 200
        assert "demo-local" in embedded.text
        assert "Not Found" not in embedded.text
        markdown = client.get(f"/reports/{stored.id}/markdown")
        assert markdown.status_code == 200
        assert "text/markdown" in markdown.headers.get("content-type", "")
        missing = client.get("/reports/999999/embed")
        assert missing.status_code == 404

        charts = client.get("/api/charts/summary")
        assert charts.status_code == 200
        payload = charts.json()
        assert "timeline" in payload and "severity" in payload and "servers" in payload
        daily = client.get("/api/charts/summary?granularity=day")
        assert daily.status_code == 200
        assert daily.json()["granularity"] == "day"

        settings_page = client.get("/settings")
        assert settings_page.status_code == 200
        assert "auth.enabled" not in settings_page.text.lower() or "설정" in settings_page.text
        assert "수집 주기마다 호출하지 않습니다" in settings_page.text
        assert "시스템 설정" in settings_page.text
        assert "읽은 값" not in settings_page.text
        assert 'name="collect_interval"' in settings_page.text
        assert 'name="daily_report_time"' in settings_page.text

        checkpoints = client.get("/api/checkpoints?offset=0&limit=50")
        assert checkpoints.status_code == 200
        payload = checkpoints.json()
        assert "items" in payload and "has_more" in payload
        assert payload["limit"] == 50

        plugins_page = client.get("/plugins", follow_redirects=True)
        assert plugins_page.status_code == 200
        assert "리소스 및 성능 쉘 스크립트" in plugins_page.text
        assert "리소스 및 성능 플러그인" not in plugins_page.text
        log_plugins = client.get("/plugins/logs")
        assert log_plugins.status_code == 200
        assert "1단계" in log_plugins.text
        assert "2단계" in log_plugins.text
        assert "1단계 · 공통 플러그인" in log_plugins.text
        assert "2단계 · 세부 플러그인" in log_plugins.text
        assert "3단계 · 로그 보고서 플러그인" in log_plugins.text
        assert 'id="plugin-search"' in log_plugins.text
        assert "plugin-card" in log_plugins.text
        assert "plugin-card-grid" in log_plugins.text
        assert "plugin-card-desc" in log_plugins.text
        assert "plugin-chips" in log_plugins.text
        assert "plugin-chip" in log_plugins.text
        assert "더보기" in log_plugins.text
        assert "서버에서 쓰는 플러그인만 ON" in log_plugins.text
        assert log_plugins.text.count('class="tag ok">ON') == 2
        assert "plugin-meta" in log_plugins.text
        assert "text-truncate report-summary" not in log_plugins.text
        assert "애플리케이션" in log_plugins.text
        assert "웹 서버" in log_plugins.text
        assert 'data-stage-filter="1"' in log_plugins.text
        assert 'data-initial-stage="' in log_plugins.text
        assert 'data-stage-pane="1"' in log_plugins.text
        assert log_plugins.text.find('href="/plugins/new?stage=1"') < log_plugins.text.find(
            'href="/plugins/new?stage=2"'
        ) < log_plugins.text.find('href="/plugins/new?stage=3"')
        assert "세부 에러" not in log_plugins.text
        assert "우리 시스템" not in log_plugins.text
        assert "Nginx" in log_plugins.text
        assert "Oracle" in log_plugins.text
        assert "Java" in log_plugins.text
        assert "Python" in log_plugins.text
        assert "Spring Boot" in log_plugins.text
        new_plugin = client.get("/plugins/new?stage=2&server=demo-local")
        assert new_plugin.status_code == 200
        assert "demo-local_rules" in new_plugin.text
        assert "demo-local 전용" in new_plugin.text
        assert "찾을 오류 문구" in new_plugin.text
        assert "찾을 문구" in new_plugin.text
        assert "수집된 ERROR/WARN 줄" in new_plugin.text
        assert "OutOfMemoryError" in new_plugin.text
        assert "Deadlock detected" in new_plugin.text
        assert "Too many open files" in new_plugin.text
        listed = client.get("/reports")
        assert "삭제" in listed.text
        assert "js-report-delete" in listed.text
        assert "resourceDeleteModal" in listed.text

        servers_page = client.get("/servers/logs")
        assert servers_page.status_code == 200
        assert "로그 수집 대상 서버" in servers_page.text
        assert "등록한 서버" in servers_page.text
        assert "서버 등록하기" in servers_page.text
        assert "커넥션 상태" in servers_page.text
        assert "/servers/logs/connect-all" in servers_page.text
        assert "connection-status" in servers_page.text
        assert "정보" in servers_page.text
        assert "수정" in servers_page.text
        assert 'id="server-search"' in servers_page.text
        assert "server-add-actions" in servers_page.text
        assert 'data-fidget="log-collect"' in servers_page.text
        assert "1단계 공통 플러그인" in servers_page.text
        assert "2단계 세부 플러그인" in servers_page.text
        assert "2단계 우리 시스템" not in servers_page.text
        assert "Java" in servers_page.text
        assert "Python" in servers_page.text
        assert "Spring Boot" in servers_page.text
        assert "EAI (Inzent)" not in servers_page.text
        assert "MCI 대외인터페이스" not in servers_page.text
        assert "Nginx" in servers_page.text
        created = client.post(
            "/servers/logs",
            data={
                "name": "only-logs",
                "collector_type": "local",
                "host": "only-logs",
                "log_paths": "sample_logs/demo.log",
            },
            follow_redirects=True,
        )
        assert created.status_code == 200
        assert "only-logs" in created.text
        assert "only-logs 수정" in created.text
        assert "공개키" in created.text
        assert "시험 로그 넣기" in created.text
        assert "2단계 세부 플러그인 만들기" in created.text
        assert "이 서버 보고서 만들기" in created.text
        log_id = str(created.url).rstrip("/").rsplit("/", 2)[-2]
        seeded = client.post(f"/servers/logs/{log_id}/seed-logs", follow_redirects=True)
        assert seeded.status_code == 200
        assert "GuardianTestLogs" in seeded.text or "시험 로그" in seeded.text
        assert "disk.full" in seeded.text or "auth.failures" in seeded.text or "stage1." in seeded.text
        plugins_page = client.get("/plugins/logs")
        assert plugins_page.status_code == 200
        assert "2단계" in plugins_page.text
        assert "EAI (Inzent)" not in plugins_page.text
        assert "Java" in plugins_page.text
        filtered = client.get("/api/checkpoints?offset=0&limit=50&server_id=1")
        assert filtered.status_code == 200
        assert "items" in filtered.json()


def test_custom_app_plugin_from_phrases_attaches_to_server():
    from app.db import parse_json_list
    from app.models import Server, SessionLocal
    from app.plugins import editor as plugin_editor
    from app.plugins.loader import load_manifests
    from app.resource_collect import dump_plugins

    name = "zz_order_app_test"

    def cleanup() -> None:
        try:
            plugin_editor.delete_plugin(2, name)
        except KeyError:
            pass
        db = SessionLocal()
        try:
            for server in db.query(Server).all():
                for field in ("log_plugins", "custom_plugins"):
                    current = parse_json_list(getattr(server, field, "") or "")
                    cleaned = [item for item in current if item != name]
                    if cleaned != current:
                        setattr(server, field, dump_plugins(cleaned))
            db.commit()
        finally:
            db.close()

    cleanup()
    try:
        with TestClient(app) as client:
            created = client.post(
                "/plugins/new",
                data={
                    "stage": "2",
                    "name": name,
                    "label": "주문시스템",
                    "phrases": "주문 타임아웃\nPAY-401",
                    "sample_logs": "2026-09-13 10:00:00 ERROR [OrderService] 재고 부족",
                    "bind_server": "demo-local",
                },
                follow_redirects=True,
            )
            assert created.status_code == 200
            catalog = client.get("/plugins/logs")
            assert catalog.status_code == 200
            assert "주문시스템" in catalog.text
            assert "2단계 · 세부 플러그인" in catalog.text
            assert "세부 에러" not in catalog.text
            assert "우리 시스템" not in catalog.text
            servers = client.get("/servers/logs")
            assert "주문시스템" in servers.text
            plugin = next(item for item in load_manifests() if item.name == name)
            assert plugin.system == "custom"
            patterns = [str(rule.get("pattern") or "") for rule in plugin.rules]
            assert any(re.search(item, "주문 타임아웃") for item in patterns)
            assert any(re.search(item, "PAY-401") for item in patterns)
            assert any(re.search(item, "재고 부족") for item in patterns)
        db = SessionLocal()
        try:
            demo = db.query(Server).filter(Server.name == "demo-local").one()
            assert name in parse_json_list(demo.custom_plugins or "")
        finally:
            db.close()
    finally:
        cleanup()


def test_plugin_from_picked_collected_line():
    from app.db import parse_json_list
    from app.models import Server, SessionLocal
    from app.plugins import editor as plugin_editor
    from app.plugins.loader import load_manifests
    from app.resource_collect import dump_plugins

    name = "zz_from_logs_test"
    line = "2026-08-25 10:03:44 ERROR [worker] Connection refused to 10.0.0.12:5432"

    def cleanup() -> None:
        try:
            plugin_editor.delete_plugin(2, name)
        except KeyError:
            pass
        db = SessionLocal()
        try:
            for server in db.query(Server).all():
                for field in ("log_plugins", "custom_plugins"):
                    current = parse_json_list(getattr(server, field, "") or "")
                    cleaned = [item for item in current if item != name]
                    if cleaned != current:
                        setattr(server, field, dump_plugins(cleaned))
            db.commit()
        finally:
            db.close()

    cleanup()
    try:
        with TestClient(app) as client:
            created = client.post(
                "/plugins/new",
                data={
                    "stage": "2",
                    "name": name,
                    "label": "워커앱",
                    "picked_logs": line,
                    "bind_server": "demo-local",
                    "server_names": "demo-local",
                },
                follow_redirects=True,
            )
            assert created.status_code == 200
            plugin = next(item for item in load_manifests() if item.name == name)
            patterns = [str(rule.get("pattern") or "") for rule in plugin.rules]
            assert any(re.search(item, "Connection refused to 10.0.0.12:5432") for item in patterns)
        db = SessionLocal()
        try:
            demo = db.query(Server).filter(Server.name == "demo-local").one()
            assert name in parse_json_list(demo.custom_plugins or "")
        finally:
            db.close()
    finally:
        cleanup()


def test_finding_signature_shortens_and_read_survives_same_day():
    from datetime import datetime

    from app.main import _shorten
    from app.models import Finding, Server, SessionLocal
    from app.pipeline.runner import _upsert_finding

    assert _shorten("짧은", 36) == "짧은"
    assert _shorten("x" * 50, 36).endswith("...")
    assert len(_shorten("x" * 50, 36)) == 36

    with TestClient(app) as client:
        collected = client.post("/collect", follow_redirects=True)
        assert collected.status_code == 200
        page = client.get("/findings")
        assert "finding-signature" in page.text
        assert "신규" not in page.text

    db = SessionLocal()
    try:
        item = db.query(Finding).order_by(Finding.count.desc()).first()
        assert item is not None
        item.read_at = datetime.utcnow()
        before = item.count
        db.commit()
        server = db.get(Server, item.server_id)
        _upsert_finding(
            db,
            server,
            {
                "occurred_at": item.occurred_at,
                "plugin": item.plugin,
                "signature": item.signature,
                "severity": item.severity,
                "count": 1,
                "sample_lines": ["again"],
                "host": item.host,
            },
        )
        db.commit()
        db.refresh(item)
        assert item.read_at is not None
        assert item.count == before + 1
    finally:
        db.close()


def test_used_log_plugin_shows_on():
    from app.models import Server, SessionLocal
    from app.resource_collect import dump_plugins

    with TestClient(app) as client:
        before = client.get("/plugins/logs")
        n = before.text.count('class="tag ok">ON')
        assert n == 2
        unused = client.get("/plugins/resources")
        assert 'class="tag ok">ON' not in unused.text
        with SessionLocal() as db:
            demo = db.query(Server).filter(Server.name == "demo-local").one()
            previous = demo.log_plugins
            demo.log_plugins = dump_plugins(["java"])
            db.commit()
        try:
            after = client.get("/plugins/logs")
            assert after.text.count('class="tag ok">ON') == n + 1
        finally:
            with SessionLocal() as db:
                demo = db.query(Server).filter(Server.name == "demo-local").one()
                demo.log_plugins = previous
                db.commit()
