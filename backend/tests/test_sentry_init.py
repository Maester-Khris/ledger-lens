import importlib

import pytest


def test_health_sends_nothing_to_sentry(monkeypatch):
    # The temporary dashboard ping must not exist in committed code.
    import app.routes.health as health_module
    source = open(health_module.__file__, encoding="utf-8").read()
    assert "capture_message" not in source
    assert "SENTRY TEST" not in source


def test_sentry_off_without_dsn(monkeypatch):
    import sentry_sdk
    monkeypatch.setattr("app.config.SENTRY_DSN", None)
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    import app.main as main_module
    importlib.reload(main_module)
    assert calls == []
