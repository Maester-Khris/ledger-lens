"""N5: the Redis window must behave like the in-memory one and stay exact across processes."""
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import redis

from app import config, deps
from app.rate_limit import RedisWindowLimiter, SlidingWindowLimiter, admit


@pytest.fixture()
def client():
    return redis.Redis.from_url(config.TEST_REDIS_URL, socket_timeout=1)


def _limiter(client, limit, window):
    return RedisWindowLimiter(client, f"test-{uuid.uuid4().hex[:8]}", limit, window)


def test_allows_up_to_the_limit_then_reports_the_wait(client):
    limiter = _limiter(client, 2, 2)
    assert admit([(limiter, "k")]) == 0
    assert admit([(limiter, "k")]) == 0
    wait = admit([(limiter, "k")])
    assert 0 < wait <= 2


def test_the_window_slides(client):
    limiter = _limiter(client, 1, 0.3)
    assert admit([(limiter, "k")]) == 0
    assert admit([(limiter, "k")]) > 0
    time.sleep(0.35)
    assert admit([(limiter, "k")]) == 0


def test_a_refused_request_records_nothing_on_any_key(client):
    tight, loose = _limiter(client, 1, 10), _limiter(client, 5, 10)
    assert admit([(tight, "a"), (loose, "ip")]) == 0
    assert admit([(tight, "a"), (loose, "ip")]) > 0
    assert client.zcard(loose.key("ip")) == 1  # the refused request did not count against the IP


def test_admission_is_exact_under_concurrent_callers(client):
    limiter = _limiter(client, 10, 30)
    with ThreadPoolExecutor(max_workers=20) as pool:
        waits = list(pool.map(lambda _: admit([(limiter, "guest")]), range(40)))
    assert sum(1 for w in waits if w == 0) == 10


def test_redis_down_fails_open_and_warns(caplog):
    unreachable = redis.Redis(host="127.0.0.1", port=1, socket_timeout=0.2, socket_connect_timeout=0.2)
    limiter = RedisWindowLimiter(unreachable, "down", 1, 10)
    with caplog.at_level(logging.WARNING):
        assert admit([(limiter, "k")]) == 0
        assert admit([(limiter, "k")]) == 0
    assert "rate_limit_unavailable" in caplog.text


def test_chat_limits_use_redis_only_when_configured(monkeypatch):
    monkeypatch.setattr(config, "REDIS_URL", config.TEST_REDIS_URL)
    assert all(isinstance(limiter, RedisWindowLimiter) for limiter in deps.build_chat_limits())
    monkeypatch.setattr(config, "REDIS_URL", None)
    assert all(isinstance(limiter, SlidingWindowLimiter) for limiter in deps.build_chat_limits())
