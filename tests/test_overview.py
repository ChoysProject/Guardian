from app.overview import build_overview, review_payload, save_overview_review, load_overview_review


def _group(name, level, status, verdict="", problem="", server_id=None):
    return {
        "name": name,
        "server_id": server_id,
        "metrics": {
            "level": level,
            "status": status,
            "verdict": verdict,
            "problem_text": problem,
        },
    }


def test_overview_empty_has_waiting_headline():
    overview = build_overview([], [])
    assert overview["status"] == "대기"
    assert "수집 대상이 없습니다" in overview["headline"]
    assert overview["level"] == ""


def test_overview_danger_joins_log_and_resource():
    overview = build_overview(
        [_group("spring-prod-01", "danger", "위험", problem="upstream timed out · HikariPool")],
        [_group("pg-db-01", "danger", "위험", problem="postgres deadlock detected")],
    )
    assert overview["level"] == "danger"
    assert overview["status"] == "위험"
    assert "위험 서버 2대" in overview["headline"]
    assert "spring-prod-01" in overview["headline"]
    assert "웹" in overview["story"] and "DB" in overview["story"]
    assert overview["charts"]["health"]["danger"] == 2
    assert overview["charts"]["log"]["danger"] == 1
    assert overview["charts"]["resource"]["danger"] == 1
    assert overview["focus"][0]["server"] == "pg-db-01"
    assert overview["focus"][0]["kind"] == "리소스"
    assert overview["focus"][0]["href"] == "#section-resources"
    assert overview["focus"][1]["server"] == "spring-prod-01"
    assert overview["focus"][1]["href"] == "#section-logs"
    linked = build_overview(
        [_group("spring-prod-01", "danger", "위험", problem="upstream timed out", server_id=3)],
        [_group("pg-db-01", "danger", "위험", problem="postgres deadlock detected", server_id=9)],
    )
    assert linked["focus"][0]["href"] == "#card-resource-9"
    assert linked["focus"][1]["href"] == "#card-log-3"
    assert "리소스는 pg-db-01" in overview["briefing"]
    assert any("spring-prod-01" in item for item in overview["risks"])
    payload = review_payload(overview)
    assert payload["kind"] == "fleet"
    assert "spring-prod-01" in payload["facts"]["log_danger"]


def test_overview_ok_when_all_clear():
    overview = build_overview(
        [_group("spring-ok-01", "ok", "여유")],
        [_group("mini-pc", "ok", "여유")],
    )
    assert overview["level"] == "ok"
    assert "여유" in overview["headline"]
    assert overview["story"] == ""


def test_overview_registered_but_not_collected_is_waiting():
    overview = build_overview([_group("demo-local", "", "")], [])
    assert overview["status"] == "대기"
    assert "수집된 로그" in overview["headline"]
    assert "아직 수집 전" in overview["log_line"]


def test_overview_review_roundtrip(tmp_path, monkeypatch):
    from app import overview as module

    monkeypatch.setattr(module, "overview_path", lambda: tmp_path / "overview_review.json")
    saved = save_overview_review({"summary": "전체가 위험합니다.", "risks": ["웹"], "actions": ["DB를 보세요"]})
    loaded = load_overview_review()
    assert saved["summary"] == "전체가 위험합니다."
    assert loaded["summary"] == "전체가 위험합니다."
    assert loaded["actions"] == ["DB를 보세요"]
