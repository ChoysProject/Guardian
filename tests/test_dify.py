from app.ai.dify import findings_payload
from app.ai.gateway import annotate_findings
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
