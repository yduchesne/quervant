"""Injected logical clock for deterministic simulation.

The clock is a counter of simulated nanoseconds. It never reads wall time,
thread/process time, a monotonic OS clock or Python's ``random``; it never
sleeps. Only the controller may advance it, and only after a validated envelope.
"""

from __future__ import annotations

from ..config.errors import BM_UNSAFE_INPUT, BenchError
from .contracts import MAX_LOGICAL_NS


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BenchError(BM_UNSAFE_INPUT, f"{field} must be an integer")
    return value


class LogicalClock:
    """A monotonically increasing simulated-nanosecond counter."""

    __slots__ = ("_now_ns",)

    def __init__(self, start_ns: int = 0) -> None:
        start = _require_int(start_ns, "start_ns")
        if start < 0 or start > MAX_LOGICAL_NS:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"start_ns must be in [0, {MAX_LOGICAL_NS}]",
            )
        self._now_ns = start

    def now_ns(self) -> int:
        """Return the current simulated instant without observing any clock."""

        return self._now_ns

    def advance_ns(self, delta: int) -> int:
        """Advance the simulated instant by ``delta`` and return the new value."""

        step = _require_int(delta, "delta")
        if step < 0:
            raise BenchError(BM_UNSAFE_INPUT, "delta must be non-negative")
        target = self._now_ns + step
        if target > MAX_LOGICAL_NS:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"logical clock would exceed {MAX_LOGICAL_NS}",
            )
        self._now_ns = target
        return target
