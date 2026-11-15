"""Pure readiness evaluation over supplied observations.

This module extracts decision *mechanics* only. It never samples a host, sleeps,
reads a clock, expires a result or authorizes acquisition. Thresholds are injected
from a validated policy; the historical T7/F2 constants are not global defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from ..config.errors import BM_UNSAFE_INPUT, BenchError

_REASON_INSUFFICIENT = "insufficient-intervals"
_REASON_INTERVAL = "interval-out-of-range"
_REASON_BUSY = "busy-exceeded"
_REASON_STEAL = "steal-exceeded"
_REASON_MEDIAN = "median-busy-exceeded"


def _require_int(value: object, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BenchError(BM_UNSAFE_INPUT, f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise BenchError(BM_UNSAFE_INPUT, f"{field} must be >= {minimum}")
    return value


def _require_permille(value: object, field: str) -> int:
    observed = _require_int(value, field, minimum=0)
    if observed > 1000:
        raise BenchError(BM_UNSAFE_INPUT, f"{field} must be in [0, 1000]")
    return observed


@dataclass(frozen=True)
class ReadinessLimits:
    """Injected readiness thresholds."""

    min_interval_ms: int
    max_interval_ms: int
    max_busy_permille: int
    max_median_busy_permille: int
    max_steal_permille: int
    min_intervals: int

    def __post_init__(self) -> None:
        minimum = _require_int(self.min_interval_ms, "min_interval_ms", minimum=1)
        maximum = _require_int(
            self.max_interval_ms, "max_interval_ms", minimum=1
        )
        if maximum < minimum:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "max_interval_ms must be >= min_interval_ms",
            )
        _require_int(self.min_intervals, "min_intervals", minimum=1)
        if self.min_intervals > 256:
            raise BenchError(BM_UNSAFE_INPUT, "min_intervals must be <= 256")
        _require_permille(self.max_busy_permille, "max_busy_permille")
        _require_permille(
            self.max_median_busy_permille, "max_median_busy_permille"
        )
        _require_permille(self.max_steal_permille, "max_steal_permille")


@dataclass(frozen=True)
class ReadinessObservation:
    """One supplied logical observation; no clock is read here."""

    elapsed_ms: int
    busy_permille: int
    steal_permille: int

    def __post_init__(self) -> None:
        _require_int(self.elapsed_ms, "elapsed_ms", minimum=0)
        _require_permille(self.busy_permille, "busy_permille")
        _require_permille(self.steal_permille, "steal_permille")


@dataclass(frozen=True)
class ReadinessDiagnostic:
    """Diagnostic outcome; ``clear`` is never an authorization token."""

    status: Literal["clear", "blocked"]
    reasons: tuple[str, ...]


def _lower_median(values: Sequence[int]) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def evaluate_readiness(
    limits: ReadinessLimits, observations: Sequence[ReadinessObservation]
) -> ReadinessDiagnostic:
    """Evaluate only the supplied immutable observation sequence."""

    if not isinstance(observations, Sequence):
        raise BenchError(BM_UNSAFE_INPUT, "observations must be a sequence")
    for index, observation in enumerate(observations):
        if not isinstance(observation, ReadinessObservation):
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"observations[{index}] must be a ReadinessObservation",
            )
        if (
            observation.elapsed_ms < 0
            or not 0 <= observation.busy_permille <= 1000
            or not 0 <= observation.steal_permille <= 1000
        ):
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"observations[{index}] is outside the permille or time domain",
            )

    reasons: set[str] = set()
    if len(observations) < limits.min_intervals:
        reasons.add(_REASON_INSUFFICIENT)

    busy_values: list[int] = []
    for observation in observations:
        busy_values.append(observation.busy_permille)
        if not (
            limits.min_interval_ms
            <= observation.elapsed_ms
            <= limits.max_interval_ms
        ):
            reasons.add(_REASON_INTERVAL)
        if observation.busy_permille > limits.max_busy_permille:
            reasons.add(_REASON_BUSY)
        if observation.steal_permille > limits.max_steal_permille:
            reasons.add(_REASON_STEAL)

    if busy_values and _lower_median(busy_values) > limits.max_median_busy_permille:
        reasons.add(_REASON_MEDIAN)

    ordered = tuple(sorted(reasons))
    return ReadinessDiagnostic(
        status="blocked" if ordered else "clear", reasons=ordered
    )
