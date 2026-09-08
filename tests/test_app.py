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

        collected = client.post("/collect", follow_redirects=True)
        assert collected.status_code == 200

        findings = client.get("/api/findings")
        assert findings.status_code == 200
        body = findings.json()
        assert body, "데모 로그에서 Finding이 나와야 합니다"
        plugins = {item["plugin"] for item in body}
        assert any(name.startswith("stage1.") for name in plugins)
        assert "stage2.auth_failures" in plugins
        assert "stage2.disk_full" in plugins

        reports_page = client.get("/reports")
        assert reports_page.status_code == 200
        assert "demo-local" in reports_page.text
        assert "선택 생성" in reports_page.text
        generated = client.post(
            "/reports/generate",
            data={"selecting": "1", "servers": "demo-local"},
            follow_redirects=True,
        )
        assert generated.status_code == 200
        assert "보고서" in generated.text
        assert "server_report:demo-local" in generated.text

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

        checkpoints = client.get("/api/checkpoints?offset=0&limit=50")
        assert checkpoints.status_code == 200
        payload = checkpoints.json()
        assert "items" in payload and "has_more" in payload
        assert payload["limit"] == 50

        plugins_page = client.get("/plugins", follow_redirects=True)
        assert plugins_page.status_code == 200
        assert "리소스 및 성능 쉘 스크립트" in plugins_page.text
        assert "리소스 및 성능 플러그인" in plugins_page.text
        log_plugins = client.get("/plugins/logs")
        assert log_plugins.status_code == 200
        assert "Stage 2" in log_plugins.text
        new_plugin = client.get("/plugins/new?stage=2&server=demo-local")
        assert new_plugin.status_code == 200
        assert "demo-local_rules" in new_plugin.text
        assert "demo-local 전용" in new_plugin.text
        listed = client.get("/reports")
        assert "삭제" in listed.text

        servers_page = client.get("/servers/logs")
        assert servers_page.status_code == 200
        assert "로그 수집 대상 서버" in servers_page.text
        assert "수집 중인 서버" in servers_page.text
        assert "정보" in servers_page.text
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
        filtered = client.get("/api/checkpoints?offset=0&limit=50&server_id=1")
        assert filtered.status_code == 200
        assert "items" in filtered.json()
