"""Wilson score intervals and binomial rate summaries for evaluation metrics."""
import math


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)) / denom
    low = max(0.0, center - half)
    high = min(1.0, center + half)
    return (low, high)


def rate(successes: int, n: int) -> dict:
    interval = wilson(successes, n)
    if interval is None:
        return {"n": 0, "successes": successes, "rate": None, "low": None, "high": None}
    low, high = interval
    return {
        "n": n,
        "successes": successes,
        "rate": successes / n,
        "low": low,
        "high": high,
    }
