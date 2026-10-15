import pytest

from app import config, deps
from app.rate_limit import SlidingWindowLimiter, admit


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_window_slides_and_a_refused_request_does_not_extend_the_wait():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(2, 10, clock=clock)
    assert admit([(limiter, "k")]) == 0
    clock.now = 4
    assert admit([(limiter, "k")]) == 0
    clock.now = 5
    assert admit([(limiter, "k")]) == 5  # the first hit leaves the window at t=10
    clock.now = 10
    assert admit([(limiter, "k")]) == 0  # the refused hit at t=5 was not recorded
    assert admit([(limiter, "other")]) == 0  # keys are independent


def test_a_request_is_recorded_on_every_limiter_or_on_none():
    clock = FakeClock()
    tight, loose = SlidingWindowLimiter(1, 10, clock=clock), SlidingWindowLimiter(5, 10, clock=clock)
    assert admit([(tight, "a"), (loose, "ip")]) == 0
    assert admit([(tight, "a"), (loose, "ip")]) == 10
    assert loose.wait("ip") == 0 and len(loose._recent("ip")) == 1  # the refused request left no trace


@pytest.fixture()
def small_limits(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    monkeypatch.setattr(deps, "chat_limits", (SlidingWindowLimiter(2, 600), SlidingWindowLimiter(3, 600)))


def _guest(client) -> str:
    return client.post("/guests").json()["id"]


def _ask(client, guest: str | None, ip: str = "203.0.113.7", forged: str = "10.0.0.1"):
    headers = {"X-Forwarded-For": f"{forged}, {ip}"}  # Railway's edge appends the address it saw on the right
    if guest is not None:
        headers["X-Guest-Id"] = guest
    # An empty body: admitted requests stop at 422 after the limiter counted them, so no LLM call is made.
    return client.post("/chat", headers=headers, json={})


def test_a_guest_is_limited_and_told_when_to_retry(small_limits, client):
    guest = _guest(client)
    assert [_ask(client, guest).status_code for _ in range(2)] == [422, 422]
    refused = _ask(client, guest)
    assert refused.status_code == 429 and refused.json()["type"] == "/problems/rate-limited"
    assert int(refused.headers["retry-after"]) > 0 and "try again in" in refused.json()["detail"]


def test_a_new_guest_per_request_still_hits_the_ip_limit(small_limits, client):
    assert [_ask(client, _guest(client)).status_code for _ in range(4)] == [422, 422, 422, 429]


def test_the_ip_is_the_one_the_proxy_appended_not_a_forged_entry(small_limits, client):
    for forged in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        assert _ask(client, _guest(client), ip="198.51.100.1", forged=forged).status_code == 422
    assert _ask(client, _guest(client), ip="198.51.100.1", forged="4.4.4.4").status_code == 429
    assert _ask(client, _guest(client), ip="198.51.100.2").status_code == 422  # another real IP is unaffected


def test_no_limit_outside_demo_mode(client, monkeypatch):
    monkeypatch.setattr(deps, "chat_limits", (SlidingWindowLimiter(1, 600), SlidingWindowLimiter(1, 600)))
    guest = _guest(client)
    assert {_ask(client, guest).status_code for _ in range(3)} == {422}
