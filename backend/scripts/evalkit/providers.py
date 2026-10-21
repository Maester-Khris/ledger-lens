"""LLM provider clients and per-model rate/token limiters for the chat evaluation pipeline."""
from collections.abc import Callable
import json
import os
from pathlib import Path
import time
from typing import Any

from dotenv import dotenv_values
from langchain_openai import ChatOpenAI

from app import config

ENV_FILE: Path = config.BACKEND_DIR / ".env.demo"

PROVIDERS: dict[str, str | None] = {
    "groq": "https://api.groq.com/openai/v1/",
    "anthropic": "https://api.anthropic.com/v1/",
    "openai": None,
}

KEYS: dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

GROQ_LIMITS: dict[str, int] = {
    "tokens_per_minute": 8000,
    "requests_per_minute": 30,
    "tokens_per_day": 200000,
}

_MINUTE_SECONDS = 60.0
_DAY_SECONDS = 86400.0


class DailyBudgetExceeded(Exception):
    """Raised when a request would exceed the model's 24-hour token budget."""


class TokenLimiter:
    def __init__(
        self,
        tokens_per_minute: int,
        requests_per_minute: int,
        tokens_per_day: int,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        usage_log: Path | None = None,
    ) -> None:
        self.tokens_per_minute = tokens_per_minute
        self.requests_per_minute = requests_per_minute
        self.tokens_per_day = tokens_per_day
        self.clock = clock
        self.sleep = sleep
        self.usage_log = usage_log
        self._entries: list[tuple[float, int]] = []
        if self.usage_log is not None and self.usage_log.exists():
            now = self.clock()
            for line in self.usage_log.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = float(row["t"])
                tok = int(row["tokens"])
                if t > now - _DAY_SECONDS:
                    self._entries.append((t, tok))

    def acquire(self, tokens: int) -> None:
        if tokens > self.tokens_per_minute:
            raise ValueError(
                f"Request of {tokens} tokens exceeds tokens_per_minute ({self.tokens_per_minute})"
            )
        now = self.clock()
        self._entries = [(t, tok) for t, tok in self._entries if t > now - _DAY_SECONDS]
        day_tokens = sum(tok for _, tok in self._entries)
        if day_tokens + tokens > self.tokens_per_day:
            raise DailyBudgetExceeded(
                f"Request of {tokens} tokens exceeds remaining daily budget ({self.tokens_per_day - day_tokens})"
            )

        while True:
            now = self.clock()
            self._entries = [(t, tok) for t, tok in self._entries if t > now - _DAY_SECONDS]
            minute_entries = [(t, tok) for t, tok in self._entries if t > now - _MINUTE_SECONDS]
            minute_tokens = sum(tok for _, tok in minute_entries)
            minute_requests = len(minute_entries)
            if (
                minute_tokens + tokens <= self.tokens_per_minute
                and minute_requests + 1 <= self.requests_per_minute
            ):
                self._entries.append((now, tokens))
                if self.usage_log is not None:
                    self.usage_log.parent.mkdir(parents=True, exist_ok=True)
                    with self.usage_log.open("a", encoding="utf-8") as out:
                        out.write(json.dumps({"t": now, "tokens": tokens}) + "\n")
                        out.flush()
                return
            oldest_entry_time = minute_entries[0][0]
            self.sleep(oldest_entry_time + _MINUTE_SECONDS - now)


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


def chat_client(
    provider: str,
    model: str,
    *,
    temperature: float = 0.0,
    timeout: float = 120,
) -> ChatOpenAI:
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    key_var = KEYS[provider]
    env = dotenv_values(ENV_FILE)
    api_key = env.get(key_var) or os.environ.get(key_var)
    if not api_key:
        raise RuntimeError(f"{key_var} is not set in {ENV_FILE} or environment")
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "timeout": timeout,
        "api_key": api_key,
        "max_retries": 2,
    }
    base_url = PROVIDERS[provider]
    if base_url is not None:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)
