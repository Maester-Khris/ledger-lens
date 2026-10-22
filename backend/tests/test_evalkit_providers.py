"""Chat eval (plan 2026-10-21, Task 2): provider clients and the per-model token limiter. No network."""
import pytest

from scripts.evalkit import providers
from scripts.evalkit.providers import GROQ_LIMITS, GROQ_SETTINGS, PROVIDERS, DailyBudgetExceeded, TokenLimiter, chat_client, estimate_tokens


class FakeTime:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _limiter(fake: FakeTime, **limits) -> TokenLimiter:
    settings = {"tokens_per_minute": 8000, "requests_per_minute": 30, "tokens_per_day": 200000} | limits
    return TokenLimiter(**settings, clock=fake.clock, sleep=fake.sleep)


def test_groq_limits_match_the_free_tier():
    assert GROQ_LIMITS == {"tokens_per_minute": 8000, "requests_per_minute": 30, "tokens_per_day": 200000}


def test_limiter_waits_when_the_minute_is_full():
    fake = FakeTime()
    limiter = _limiter(fake)
    limiter.acquire(5000)
    limiter.acquire(5000)
    assert fake.sleeps == [pytest.approx(60.0)]


def test_limiter_does_not_wait_under_the_limits():
    fake = FakeTime()
    limiter = _limiter(fake)
    limiter.acquire(3000)
    limiter.acquire(3000)
    assert fake.sleeps == []


def test_limiter_counts_requests():
    fake = FakeTime()
    limiter = _limiter(fake)
    for _ in range(31):
        limiter.acquire(1)
    assert len(fake.sleeps) == 1


def test_request_larger_than_a_minute_is_refused():
    with pytest.raises(ValueError):
        _limiter(FakeTime()).acquire(9000)


def test_daily_budget_raises():
    fake = FakeTime()
    limiter = _limiter(fake, tokens_per_minute=1_000_000)
    limiter.acquire(150000)
    with pytest.raises(DailyBudgetExceeded):
        limiter.acquire(60000)


def test_daily_budget_frees_after_a_day():
    fake = FakeTime()
    limiter = _limiter(fake, tokens_per_minute=1_000_000)
    limiter.acquire(150000)
    fake.now += 24 * 3600 + 1
    limiter.acquire(60000)


def test_daily_usage_survives_a_restart(tmp_path):
    fake = FakeTime()
    log = tmp_path / "usage-qwen.jsonl"
    first = TokenLimiter(tokens_per_minute=1_000_000, requests_per_minute=30, tokens_per_day=200000,
                         clock=fake.clock, sleep=fake.sleep, usage_log=log)
    first.acquire(150000)
    second = TokenLimiter(tokens_per_minute=1_000_000, requests_per_minute=30, tokens_per_day=200000,
                          clock=fake.clock, sleep=fake.sleep, usage_log=log)
    with pytest.raises(DailyBudgetExceeded):
        second.acquire(60000)


def test_estimate_tokens():
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 400) == 101


def test_groq_client_points_at_groq(tmp_path, monkeypatch):
    env = tmp_path / ".env.demo"
    env.write_text("GROQ_API_KEY=test-groq-key\n")
    monkeypatch.setattr(providers, "ENV_FILE", env)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    client = chat_client("groq", "qwen/qwen3.8-27b")
    assert client.openai_api_base == PROVIDERS["groq"]
    assert client.model_name == "qwen/qwen3.8-27b"
    assert client.temperature == 0.0


def test_missing_key_is_an_error(tmp_path, monkeypatch):
    env = tmp_path / ".env.demo"
    env.write_text("")
    monkeypatch.setattr(providers, "ENV_FILE", env)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        chat_client("anthropic", "claude-sonnet-5-5")


def test_unknown_provider_is_an_error():
    with pytest.raises(ValueError):
        chat_client("mistral", "x")


def test_groq_settings_bound_reasoning_and_completion_for_every_groq_model():
    for model in ("qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"):
        assert GROQ_SETTINGS[model]["max_tokens"] == 2500 and GROQ_SETTINGS[model]["reasoning_effort"]


def test_client_passes_reasoning_effort_and_max_tokens(tmp_path, monkeypatch):
    env = tmp_path / ".env.demo"
    env.write_text("GROQ_API_KEY=k\n")
    monkeypatch.setattr(providers, "ENV_FILE", env)
    client = chat_client("groq", "openai/gpt-oss-20b", reasoning_effort="low", max_tokens=600)
    assert client.reasoning_effort == "low" and client.max_tokens == 600


def test_a_limiter_without_a_daily_cap_never_raises_for_the_day():
    fake = FakeTime()
    limiter = _limiter(fake, tokens_per_minute=1_000_000, tokens_per_day=None)
    for _ in range(3):
        limiter.acquire(150000)


def test_groq_daily_limit_errors_are_recognised():
    from scripts.evalkit.providers import is_daily_limit
    daily = RuntimeError("Error code: 429 - Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 198638")
    assert is_daily_limit(daily)
    assert not is_daily_limit(RuntimeError("Rate limit reached ... on tokens per minute (TPM): Limit 8000"))
