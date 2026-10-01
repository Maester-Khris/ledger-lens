"""Sliding-window rate limits for the public demo's chat (P3). Framework-free.

ponytail: in-process memory, correct for the single Railway instance. With several API instances each one keeps its
own windows (the effective limit multiplies by the instance count): move the windows to Postgres or Redis then.
Keys of visitors who never come back keep a small deque; fine at demo traffic, add an eviction sweep if it grows."""
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence


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


def admit(checks: Sequence[tuple[SlidingWindowLimiter, str]]) -> float:
    """0 = allowed, and the hit is recorded on every limiter. Otherwise the longest wait, and nothing is recorded,
    so a refused request never extends its own wait."""
    wait = max(limiter.wait(key) for limiter, key in checks)
    if wait <= 0:
        for limiter, key in checks:
            limiter.hit(key)
    return wait
