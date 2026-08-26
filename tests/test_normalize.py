from app.pipeline.normalize import make_signature, parse_line, parse_text


def test_parse_iso_error_line():
    event = parse_line("2026-08-25 10:03:44 ERROR [worker] Connection refused to 10.0.0.12:5432")
    assert event is not None
    assert event.level == "error"
    assert event.process_name == "worker"
    assert "Connection refused" in event.message
    assert "<ip>" in event.signature
    assert "10.0.0.12" not in event.signature


def test_parse_syslog_auth():
    event = parse_line(
        "Aug 25 11:15:03 demo-local sshd[4412]: Failed password for root from 192.168.10.5 port 55122 ssh2",
        default_host="fallback",
    )
    assert event is not None
    assert event.host == "demo-local"
    assert event.process_name == "sshd"
    assert event.level == "info"


def test_parse_bracket_level():
    event = parse_line("[ERROR] boom")
    assert event is not None
    assert event.level == "error"
    assert event.message == "boom"


def test_signature_strips_noise():
    sig = make_signature("timeout id=0xabc user=9 uuid=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert "0xabc" not in sig
    assert "<hex>" in sig
    assert "<uuid>" in sig


def test_parse_text_skips_blank():
    events = parse_text("\n\nINFO ok\n")
    assert len(events) == 1
    assert events[0].level == "info"
