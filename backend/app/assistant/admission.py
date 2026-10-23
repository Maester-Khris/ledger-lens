"""Admission control for chat turns: a limit on turns in flight in this process.

Past the limit a turn is refused at once instead of queued, so an overloaded process answers "busy" quickly rather than
answering everyone slowly. The count lives in the process, so each replica protects its own CPU and capacity adds up as
replicas are added (the design MediCoord uses). There is no lock: every change happens on the event loop thread, between
awaits. 0 means off, until the limit is set from a measured knee."""
import random
from collections.abc import Callable

_in_flight = 0


class Busy(Exception):
    """The turns in flight in this process have reached the limit."""


class Slot:
    """One held turn slot; releasing it more than once is a no-op."""

    def __init__(self) -> None:
        self._released = False

    def release(self) -> None:
        global _in_flight
        if self._released:
            return
        self._released = True
        _in_flight -= 1


def admit(limit: int) -> Slot:
    global _in_flight
    if limit > 0 and _in_flight >= limit:
        raise Busy()
    _in_flight += 1
    return Slot()


def in_flight() -> int:
    return _in_flight


def retry_after_seconds(base: int, rng: Callable[[], float] = random.random) -> int:
    return base + int(rng() * 3)
