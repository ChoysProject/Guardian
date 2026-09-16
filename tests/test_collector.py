from pathlib import Path
from types import SimpleNamespace

from app.collectors.factory import collector_for
from app.collectors.local import LocalTailCollector
from app.collectors.paths import expand_home_path
from app.collectors.ssh import SshTailCollector
from app.models import Server


def test_local_incremental_read(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("line-one\n", encoding="utf-8")
    collector = LocalTailCollector()
    first = collector.read_incremental(str(log), 0, 1024)
    assert "line-one" in first.text
    log.write_text("line-one\nline-two\n", encoding="utf-8")
    second = collector.read_incremental(str(log), first.new_offset, 1024, inode=first.inode)
    assert "line-two" in second.text
    assert "line-one" not in second.text


def test_local_rotation_resets_offset(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("abcdef", encoding="utf-8")
    collector = LocalTailCollector()
    first = collector.read_incremental(str(log), 0, 1024)
    log.write_text("z", encoding="utf-8")
    second = collector.read_incremental(str(log), first.new_offset, 1024)
    assert second.new_offset == 1
    assert second.text == "z"


def test_collector_for_ssh_uses_server_auth():
    server = Server(
        name="ssh-auth",
        collector_type="ssh",
        host="10.0.0.9",
        port=22,
        username="guardian",
        auth_type="password",
        key_path="",
    )
    collector = collector_for(server, ssh_timeout=5)
    assert isinstance(collector, SshTailCollector)
    assert collector.server is server
    assert collector_for(Server(name="local", collector_type="local")).__class__ is LocalTailCollector


def test_expand_home_path_tilde_and_dollar_home():
    assert expand_home_path("~/DailyData/logs/springboot*", "/home/choys") == (
        "/home/choys/DailyData/logs/springboot*"
    )
    assert expand_home_path("$HOME/DailyData/logs/springboot*", "/home/choys") == (
        "/home/choys/DailyData/logs/springboot*"
    )
    assert expand_home_path("/var/log/app.log", "/home/choys") == "/var/log/app.log"


def test_local_resolve_expands_user_home(tmp_path: Path, monkeypatch):
    logs = tmp_path / "DailyData" / "logs"
    logs.mkdir(parents=True)
    target = logs / "springboot-app.log"
    target.write_text("ERROR boom\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    collector = LocalTailCollector()
    paths = collector.resolve_paths("~/DailyData/logs/springboot*")
    assert any(Path(item).name == "springboot-app.log" for item in paths)


def test_ssh_resolve_expands_tilde_before_listdir():
    server = Server(name="EAI_LOG", collector_type="ssh", username="choys")
    collector = SshTailCollector(server)
    collector._home = "/home/choys"
    collector._sftp = SimpleNamespace(
        listdir=lambda parent: (
            ["springboot.log", "other.log"]
            if parent == "/home/choys/DailyData/logs"
            else (_ for _ in ()).throw(FileNotFoundError(parent))
        )
    )
    collector.open = lambda: None
    paths = collector.resolve_paths("~/DailyData/logs/springboot*")
    assert paths == ["/home/choys/DailyData/logs/springboot.log"]
    assert collector.resolve_paths("~/DailyData/logs/missing*") == []
