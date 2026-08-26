from app.cursors import PAGE_SIZE, page_cursors, save_all


def test_checkpoint_pages_without_db(tmp_path, monkeypatch):
    from app import cursors as store
    from app.config import settings

    monkeypatch.setattr(settings.app, "data_dir", str(tmp_path))
    monkeypatch.setattr(store, "cursors_path", lambda: tmp_path / "cursors.json")

    save_all(
        [
            {
                "server_id": 1,
                "server_name": "web",
                "log_path": f"/var/log/app/{i:03d}.log",
                "offset": i,
                "size": i * 10,
                "inode": 0,
                "updated_at": "2026-08-26 10:00:00",
            }
            for i in range(63)
        ]
    )
    first = page_cursors(0, PAGE_SIZE)
    assert first["total"] == 63
    assert len(first["items"]) == 50
    assert first["has_more"] is True
    second = page_cursors(50, PAGE_SIZE)
    assert len(second["items"]) == 13
    assert second["has_more"] is False
