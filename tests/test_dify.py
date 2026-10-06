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


def test_review_resources_strips_markdown_even_if_dify_ignores_instruction(monkeypatch):
    monkeypatch.setattr("app.ai.gateway.settings.openai.enabled", False)
    monkeypatch.setattr("app.ai.gateway.settings.dify.enabled", True)

    def fake_dify(_payload):
        return [
            '{"summary": "**현재 9대의 서버가 위험 상태입니다.**\\n### 요약\\n'
            "apache-web-02와 app-all-01이 주요 문제입니다.\", "
            '"risks": ["- **PLANDO** 서버 디스크 위험"], "actions": ["`PLANDO`를 확인한다"]}'
        ]

    monkeypatch.setattr("app.ai.gateway._call_dify", fake_dify)
    review = review_resources({"server": "eai", "cpu": {"last": 10}})
    assert "*" not in review["summary"]
    assert "#" not in review["summary"]
    assert "\n" not in review["summary"]
    assert "현재 9대의 서버가 위험 상태입니다." in review["summary"]
    assert "apache-web-02와 app-all-01이 주요 문제입니다." in review["summary"]
    assert review["risks"] == ["PLANDO 서버 디스크 위험"]
    assert review["actions"] == ["PLANDO를 확인한다"]


def test_review_fleet_strips_markdown_from_freeform_dify_report(monkeypatch):
    monkeypatch.setattr("app.ai.gateway.settings.openai.enabled", False)
    monkeypatch.setattr("app.ai.gateway.settings.dify.enabled", True)

    def fake_dify(_payload):
        # JSON 형식을 안 지키고 자유 서술형 마크다운 보고서를 그대로 뱉는 워크플로를 흉내낸다.
        return [
            "### 전체 현황\n"
            "**현재 9대의 서버가 위험 상태입니다.** 로그와 리소스가 겹치는 서버는 다음과 같습니다.\n"
            "- apache-web-02\n- app-all-01"
        ]

    monkeypatch.setattr("app.ai.gateway._call_dify", fake_dify)
    review = review_fleet({"kind": "fleet", "facts": {"headline": "위험 서버 9대입니다."}})
    assert "*" not in review["summary"]
    assert "#" not in review["summary"]
    assert "\n" not in review["summary"]
    assert "현재 9대의 서버가 위험 상태입니다." in review["summary"]
    assert "apache-web-02" in review["summary"]


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


def test_call_dify_requires_api_key(monkeypatch):
    from app.ai.dify import _call_dify

    monkeypatch.setattr(settings.dify, "api_key", "")
    try:
        _call_dify({"task": "fleet_review"})
    except RuntimeError as exc:
        assert "API 키" in str(exc)
    else:
        raise AssertionError("키가 없으면 실패해야 합니다")


def test_call_dify_rejects_see_other(monkeypatch):
    from app.ai.dify import _call_dify

    monkeypatch.setattr(settings.dify, "api_key", "app-test")
    monkeypatch.setattr(settings.dify, "base_url", "http://dify.internal/v1")

    class FakeResp:
        status_code = 303
        headers = {"location": "http://dify.internal/signin"}
        text = "See Other"

        def json(self):
            raise ValueError("not json")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResp()

    monkeypatch.setattr("app.ai.dify.httpx.Client", FakeClient)
    try:
        _call_dify({"task": "fleet_review"})
    except RuntimeError as exc:
        assert "303" in str(exc)
        assert "signin" in str(exc)
    else:
        raise AssertionError("303은 총평 실패여야 합니다")


def test_overview_review_toasts_dify_error(monkeypatch):
    from fastapi.testclient import TestClient
    from app.ai import gateway
    from app.main import app

    monkeypatch.setattr(gateway.settings.openai, "enabled", False)
    monkeypatch.setattr(gateway.settings.dify, "enabled", True)
    monkeypatch.setattr(gateway.settings.dify, "api_key", "")

    def boom(_payload):
        raise RuntimeError("Dify가 303 See Other 로 다른 주소로 넘겼습니다.")

    monkeypatch.setattr("app.ai.gateway._call_dify", boom)
    with TestClient(app) as client:
        reviewed = client.post("/overview/review", follow_redirects=False)
        assert reviewed.status_code == 303
        location = reviewed.headers.get("location", "")
        assert "error=" in location
        assert "303" in location or "Dify" in location
