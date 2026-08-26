from pathlib import Path

from app.collectors.local import LocalTailCollector


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
