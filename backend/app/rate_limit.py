"""Sliding-window rate limits for the public demo's chat (P3). Framework-free.

ponytail: the in-memory window is correct for one process; with several processes, set `REDIS_URL` and the Redis
window below is used. Keys of visitors who never come back keep a small deque; fine at demo traffic, add an eviction
sweep if it grows."""
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

import sentry_sdk

logger = logging.getLogger(__name__)


class SlidingWindowLimiter:
    """At most `limit` hits per key within any `window_seconds`."""

    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def wait(self, key: str) -> float:
        """Seconds until `key` may hit again; 0 = allowed now. Records nothing."""
        with self._lock:
            hits = self._recent(key)
            return 0.0 if len(hits) < self.limit else hits[0] + self.window_seconds - self._clock()

    def hit(self, key: str) -> None:
        with self._lock:
            self._recent(key).append(self._clock())

    def _recent(self, key: str) -> deque[float]:
        cutoff = self._clock() - self.window_seconds
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits


class RedisWindowLimiter:
    """The same sliding window, shared by every process that uses the same Redis (workers, replicas)."""

    def __init__(self, client: Any, name: str, limit: int, window_seconds: float) -> None:
        self.client = client
        self.name = name
        self.limit = limit
        self.window_seconds = window_seconds

    def key(self, key: str) -> str:
        return f"rl:{self.name}:{key}"


# Atomic check-and-record sliding window across multiple keys.
# Implemented as a single Lua script so the evaluation and recording steps are executed
# atomically across all workers and replicas, preventing race conditions where multiple
# concurrent requests could slip through or leave partial hits recorded if one key is full:
# 1. Read Redis TIME (seconds * 1000 + microseconds // 1000) for a clock shared by all replicas.
# 2. For each key, evict expired members (score <= now - window). If ZCARD >= limit, calculate
#    the wait until the oldest member expires (oldest_score + window - now), tracking the maximum wait.
# 3. If the largest wait > 0, return it in milliseconds and record nothing on any key.
# 4. Otherwise, record the member on all keys (ZADD) and set TTL (PEXPIRE) to the window, returning 0.
_LUA_WINDOW_SCRIPT = """
local time = redis.call('TIME')
local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
local max_wait = 0

for i = 1, #KEYS do
    local key = KEYS[i]
    local limit = tonumber(ARGV[(i - 1) * 2 + 1])
    local window = tonumber(ARGV[(i - 1) * 2 + 2])
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
    if redis.call('ZCARD', key) >= limit then
        local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
        if #oldest >= 2 then
            local wait = tonumber(oldest[2]) + window - now
            if wait > max_wait then
                max_wait = wait
            end
        end
    end
end

if max_wait > 0 then
    return max_wait
end

local member = ARGV[#KEYS * 2 + 1]
for i = 1, #KEYS do
    local key = KEYS[i]
    local window = tonumber(ARGV[(i - 1) * 2 + 2])
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, window)
end

return 0
"""


def _admit_redis(checks: Sequence[tuple[RedisWindowLimiter, str]]) -> float:
    """Atomic multi-key sliding window check and record in Redis; returns wait in seconds."""
    if not checks:
        return 0.0
    client = checks[0][0].client
    keys = [limiter.key(key) for limiter, key in checks]
    args: list[Any] = []
    for limiter, _ in checks:
        args.append(limiter.limit)
        args.append(int(round(limiter.window_seconds * 1000)))
    args.append(uuid.uuid4().hex)
    try:
        raw_wait = client.eval(_LUA_WINDOW_SCRIPT, len(keys), *keys, *args)
        return float(raw_wait) / 1000
    except Exception as exc:
        # A broken limiter must not take the chat down.
        logger.warning("rate_limit_unavailable: %s: %s", type(exc).__name__, exc)
        sentry_sdk.capture_message("rate limiter unavailable, allowing requests", level="warning")
        return 0.0


def admit(checks: Sequence[tuple[SlidingWindowLimiter | RedisWindowLimiter, str]]) -> float:
    """0 = allowed, and the hit is recorded on every limiter. Otherwise the longest wait, and nothing is recorded,
    so a refused request never extends its own wait. Redis limiters do the check-and-record in one atomic script."""
    if checks and all(isinstance(limiter, RedisWindowLimiter) for limiter, _ in checks):
        return _admit_redis(checks)  # type: ignore[arg-type]
    wait = max(limiter.wait(key) for limiter, key in checks)  # type: ignore[union-attr]
    if wait <= 0:
        for limiter, key in checks:
            limiter.hit(key)  # type: ignore[union-attr]
    return wait
