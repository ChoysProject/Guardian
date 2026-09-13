from datetime import datetime

from app.db import parse_json_list
from app.log_seed import sample_log_text, write_local_test_log
from app.models import Server


def test_sample_log_text_hits_builtin_rules():
    text = sample_log_text("wsl-01", when=datetime(2026, 9, 13, 19, 5, 3))
    assert "Failed password" in text
    assert "No space left on device" in text
    assert "Connection refused" in text
    assert "Sep 13 19:05:03" in text
    eai = sample_log_text("eai-01")
    assert "INZENT" in eai
    mci = sample_log_text("app-01", systems=["mci"])
    assert "MCI 012" in mci


def test_write_local_test_log_appends_and_attaches(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings.app, "data_dir", str(tmp_path))
    server = Server(name="seed-local", collector_type="local", log_paths="[]")
    first = write_local_test_log(server, "line-one\n")
    second = write_local_test_log(server, "line-two\n")
    assert first == second
    body = (tmp_path / "GuardianTestLogs" / "seed-local" / "guardian-test.log").read_text(encoding="utf-8")
    assert "line-one" in body and "line-two" in body
    assert first in parse_json_list(server.log_paths)
