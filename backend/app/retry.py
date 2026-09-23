import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def call_with_retries(
    fn: Callable[[], T], *, attempts: int = 3, base_delay: float = 0.5, retry_on: tuple[type[BaseException], ...]
) -> T:
    """Exponential backoff with full jitter; only the listed (transient) errors are retried."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_on:
            if attempt == attempts:
                raise
            time.sleep(random.uniform(0, base_delay * 2 ** (attempt - 1)))
    raise AssertionError("unreachable")
