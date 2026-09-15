from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_settings_runtime_update_and_validation():
    old_interval = settings.collect.interval_seconds
    old_time = settings.scheduler.daily_report_time
    try:
        with TestClient(app) as client:
            saved = client.post(
                "/settings",
                data={"collect_interval": "90", "daily_report_time": "19:30"},
                follow_redirects=True,
            )
            assert saved.status_code == 200
            assert 'value="90"' in saved.text
            assert 'value="19:30"' in saved.text
            assert settings.collect.interval_seconds == 90
            assert settings.scheduler.daily_report_time == "19:30"
            text = settings.config_path.read_text(encoding="utf-8")
            assert "90" in text
            assert "19:30" in text

            bad = client.post(
                "/settings",
                data={"collect_interval": "3", "daily_report_time": "19:30"},
            )
            assert bad.status_code == 400
            assert "15초" in bad.text
            assert settings.collect.interval_seconds == 90
    finally:
        from app.config import update_runtime_settings

        update_runtime_settings(old_interval, old_time)
