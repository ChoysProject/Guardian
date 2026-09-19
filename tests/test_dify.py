from app.ai.dify import _extract_comments, findings_payload
from app.ai.gateway import annotate_findings, review_fleet, review_logs, review_resources
from app.config import settings


def test_payload_is_summary_not_raw_dump():
    long_line = "ERROR " + ("x" * 500)
    payload = findings_payload(
        [
            {
                "host": "db-01",
                "severity": "error",
                "signature": "boom",
                "count": 12,
                "plugin": "stage1.common",
                "sample_lines": [long_line, "second"],
            }
        ]
    )
    assert payload[0]["count"] == 12
    assert len(payload[0]["sample_lines"][0]) <= 200
    assert "raw_log" not in payload[0]


def test_annotate_disabled_keeps_rule_results():
    assert settings.dify.enabled is False
    assert not settings.openai.api_key
    comments = annotate_findings([{"signature": "a"}, {"signature": "b"}])
    assert comments == ["", ""]


def test_annotate_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(settings.openai, "enabled", True)
    monkeypatch.setattr(settings.openai, "api_key", "sk-test")

    def boom(_payload):
        raise RuntimeError("openai down")

    monkeypatch.setattr("app.ai.gateway._call_openai", boom)
    comments = annotate_findings([{"signature": "a"}])
    assert comments == [""]


def test_collect_does_not_call_ai(monkeypatch):
    def boom(_findings):
        raise AssertionError("수집 경로에서 AI를 부르면 안 됩니다")

    monkeypatch.setattr("app.ai.gateway.annotate_findings", boom)
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        collected = client.post("/collect", follow_redirects=True)
        assert collected.status_code == 200


def test_extract_dify_default_output_key():
    comments = _extract_comments(
        {"data": {"status": "succeeded", "outputs": {"output": "CPU가 높습니다."}}},
        expected=1,
    )
    assert comments == ["CPU가 높습니다."]


def test_extract_dify_json_object_output():
    comments = _extract_comments(
        {
            "data": {
                "outputs": {
                    "text": {"summary": "메모리가 빠듯합니다.", "risks": ["스왑 증가"]}
                }
            }
        },
        expected=1,
    )
    assert "메모리가 빠듯합니다." in comments[0]
    assert "스왑 증가" in comments[0]


def test_review_resources_sends_facts_not_a_list(monkeypatch):
    monkeypatch.setattr("app.ai.gateway.settings.openai.enabled", False)
    monkeypatch.setattr("app.ai.gateway.settings.dify.enabled", True)
    seen = {}

    def fake_dify(payload):
        seen["payload"] = payload
        return ['{"summary": "CPU 최근 0.8%로 여유입니다.", "risks": [], "actions": []}']

    monkeypatch.setattr("app.ai.gateway._call_dify", fake_dify)
    review = review_resources({"server": "eai", "cpu": {"last": 0.8}, "mem": {"last": 30.4}, "disks": []})
    assert isinstance(seen["payload"], dict)
    assert seen["payload"]["facts"]["cpu_last_pct"] == 0.8
    assert review["summary"] == "CPU 최근 0.8%로 여유입니다."


def test_review_resources_uses_dify_text(monkeypatch):
    monkeypatch.setattr("app.ai.gateway.settings.openai.enabled", False)
    monkeypatch.setattr("app.ai.gateway.settings.dify.enabled", True)

    def fake_dify(_payload):
        return ["디스크가 빠르게 찹니다."]

    monkeypatch.setattr("app.ai.gateway._call_dify", fake_dify)
    review = review_resources({"server": "eai", "cpu": {"last": 10}})
    assert review["summary"] == "디스크가 빠르게 찹니다."


def test_review_logs_disabled_keeps_rule_results():
    assert review_logs({"server": "EAI_LOG", "stats": {"lines": 3}, "findings": []}) == {}


def test_review_logs_uses_dify_facts(monkeypatch):
    monkeypatch.setattr("app.ai.gateway.settings.openai.enabled", False)
    monkeypatch.setattr("app.ai.gateway.settings.dify.enabled", True)
    seen = {}

    def fake_dify(payload):
        seen["payload"] = payload
        return ['{"summary": "ERROR 2건입니다.", "risks": [], "actions": []}']

    monkeypatch.setattr("app.ai.gateway._call_dify", fake_dify)
    review = review_logs(
        {
            "server": "EAI_LOG",
            "stats": {"lines": 40, "error": 2, "warn": 0},
            "findings": [{"signature": "spring.boot_failed", "count": 2, "severity": "error"}],
        }
    )
    assert seen["payload"]["task"] == "log_review"
    assert seen["payload"]["facts"]["lines"] == 40
    assert review["summary"] == "ERROR 2건입니다."


def test_review_fleet_disabled_keeps_rule_results():
    assert review_fleet({"kind": "fleet", "facts": {"headline": "위험 서버 1대입니다."}}) == {}


def test_review_fleet_uses_dify_facts(monkeypatch):
    monkeypatch.setattr("app.ai.gateway.settings.openai.enabled", False)
    monkeypatch.setattr("app.ai.gateway.settings.dify.enabled", True)
    seen = {}

    def fake_dify(payload):
        seen["payload"] = payload
        return ['{"summary": "웹과 DB가 같이 위험합니다.", "risks": ["spring-prod-01"], "actions": ["DB를 보세요"]}']

    monkeypatch.setattr("app.ai.gateway._call_dify", fake_dify)
    review = review_fleet(
        {
            "kind": "fleet",
            "facts": {
                "headline": "위험 서버 2대입니다.",
                "log_danger": ["spring-prod-01"],
                "resource_danger": ["pg-db-01"],
            },
        }
    )
    assert seen["payload"]["task"] == "fleet_review"
    assert seen["payload"]["facts"]["log_danger"] == ["spring-prod-01"]
    assert review["summary"] == "웹과 DB가 같이 위험합니다."
