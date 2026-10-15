from app.sentry_scrub import scrub_event


def test_request_body_is_removed():
    event = {"request": {"data": {"message": "What is the fee?"}, "url": "/chat"}}
    out = scrub_event(event, {})
    assert "data" not in out["request"]
    assert out["request"]["url"] == "/chat"


def test_message_text_is_removed():
    event = {"message": "Q: what is the fee for Tremblay?"}
    out = scrub_event(event, {})
    assert out["message"] == "[Filtered]"


def test_exception_value_is_removed():
    event = {"exception": {"values": [{"type": "ValueError", "value": "bad input: John Tremblay"}]}}
    out = scrub_event(event, {})
    assert out["exception"]["values"][0]["value"] == "[Filtered]"
    assert out["exception"]["values"][0]["type"] == "ValueError"


def test_event_without_sensitive_parts_is_unchanged():
    event = {"level": "error", "environment": "demo"}
    assert scrub_event(event, {}) == event
