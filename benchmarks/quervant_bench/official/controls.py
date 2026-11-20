"""Live host readiness and real A/A control assessment.

Readiness uses the existing :class:`host.capabilities.LinuxCapabilityProvider`,
the frozen :class:`host.readiness.ReadinessLimits` and the pure
:func:`host.readiness.evaluate_readiness` evaluator. Ticks come from a real
``/proc/stat`` sampler in production; tests inject a deterministic sampler at
this external boundary and never claim measured evidence.

The cross-engine A/A uses the frozen 12-block x 4-slot order from the D3-C
control schedule and the frozen numeric windows, applied as exact rational
arithmetic. The retained-key A/A is the original measured D3-C control; here its
per-lane A/B ratios are recomputed independently from raw slots.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..config.codec import content_digest
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id
from ..host.capabilities import LinuxCapabilityProvider, collect_host_capabilities
from ..host.readiness import (
    ReadinessDiagnostic,
    ReadinessLimits,
    ReadinessObservation,
    evaluate_readiness,
)
from ..qualification.contracts import bound_payload, require_closed, require_uint
from .protocols import D3C_AA_SOFT_OUTLIERS, D3C_AA_WINDOWS

READINESS_SCHEMA = "official-host-readiness-v1"
CONTROL_SCHEMA = "official-cross-engine-control-v1"
CONTROL_ASSESSMENT_SCHEMA = "official-cross-engine-control-assessment-v1"
RETAINED_KEY_CONTROL_SCHEMA = "official-retained-key-control-assessment-v1"

PROC_STAT_PATH = "/proc/stat"
_PROC_CPU_PREFIX = "cpu"

_READINESS_KEYS = frozenset(
    {
        "schema",
        "study_id",
        "host_fingerprint",
        "adapter_cpu",
        "controller_cpu",
        "environment",
        "limits",
        "observations",
        "status",
        "reasons",
    }
)


def _identity(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


# ---------------------------------------------------------------------------
# /proc/stat sampling
# ---------------------------------------------------------------------------


def parse_proc_stat(text: str) -> dict[str, tuple[int, ...]]:
    """Parse per-CPU tick rows from ``/proc/stat`` text.

    Rows are ``cpuN user nice system idle iowait irq softirq steal`` and the eight
    values are preserved in that order. Aggregate ``cpu`` rows are ignored and a
    malformed row fails closed.
    """

    if not isinstance(text, str):
        raise BenchError(BM_UNSAFE_INPUT, "proc stat text must be a string")
    rows: dict[str, tuple[int, ...]] = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields or not fields[0].startswith(_PROC_CPU_PREFIX):
            continue
        name = fields[0]
        if name == _PROC_CPU_PREFIX:
            continue
        if not name[3:].isdigit():
            continue
        if len(fields) < 9:
            raise BenchError(BM_UNSAFE_INPUT, "proc stat row is truncated")
        try:
            ticks = tuple(int(value) for value in fields[1:9])
        except ValueError as exc:
            raise BenchError(BM_UNSAFE_INPUT, "proc stat row is not integral") from exc
        if any(tick < 0 for tick in ticks):
            raise BenchError(BM_UNSAFE_INPUT, "proc stat ticks must be non-negative")
        rows[name[3:]] = ticks
    if not rows:
        raise BenchError(BM_UNSAFE_INPUT, "proc stat contains no per-CPU rows")
    return dict(sorted(rows.items()))


def compute_interval(
    before: Mapping[str, Sequence[int]],
    after: Mapping[str, Sequence[int]],
    cpu: int,
) -> tuple[int, int, int]:
    """Return ``(elapsed_ticks, busy_permille, steal_permille)`` for one CPU."""

    key = str(cpu)
    if key not in before or key not in after:
        raise BenchError(BM_UNSAFE_INPUT, f"proc stat has no row for cpu{cpu}")
    previous = list(before[key])
    current = list(after[key])
    if len(previous) != 8 or len(current) != 8:
        raise BenchError(BM_UNSAFE_INPUT, "proc stat rows must hold eight counters")
    delta = [current[index] - previous[index] for index in range(8)]
    if any(value < 0 for value in delta):
        raise BenchError(BM_UNSAFE_INPUT, "proc stat counters went backwards")
    total = sum(delta)
    if total <= 0:
        raise BenchError(BM_UNSAFE_INPUT, "proc stat interval has no elapsed ticks")
    busy = (1000 * (total - delta[3] - delta[4])) // total
    steal = (1000 * delta[7]) // total
    return total, busy, steal


@dataclass(frozen=True)
class HostObservation:
    """One measured readiness observation for the pinned CPU pair."""

    elapsed_ms: int
    adapter_cpu: int
    controller_cpu: int
    ticks: Mapping[str, tuple[int, ...]]
    adapter_busy_permille: int
    adapter_steal_permille: int
    controller_busy_permille: int
    controller_steal_permille: int


def sample_host(
    *,
    adapter_cpu: int,
    controller_cpu: int,
    intervals: int,
    interval_ms: int,
    read_text: Callable[[str], str | None],
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[HostObservation]:
    """Sample real ``/proc/stat`` counters for the pinned CPU pair."""

    if adapter_cpu == controller_cpu:
        raise _identity("the adapter and controller CPUs must differ", "adapter_cpu")
    if intervals < 1:
        raise BenchError(BM_UNSAFE_INPUT, "intervals must be positive")
    observations: list[HostObservation] = []
    first_text = read_text(PROC_STAT_PATH)
    if first_text is None:
        raise BenchError(BM_UNSAFE_INPUT, "/proc/stat is unavailable on this host")
    previous = parse_proc_stat(first_text)
    previous_clock = clock()
    for _ in range(intervals):
        sleep(interval_ms / 1000.0)
        text = read_text(PROC_STAT_PATH)
        if text is None:  # pragma: no cover - guarded by the first read
            raise BenchError(BM_UNSAFE_INPUT, "/proc/stat became unavailable")
        current = parse_proc_stat(text)
        now = clock()
        elapsed_ms = int(round((now - previous_clock) * 1000))
        _, adapter_busy, adapter_steal = compute_interval(previous, current, adapter_cpu)
        _, controller_busy, controller_steal = compute_interval(
            previous, current, controller_cpu
        )
        observations.append(
            HostObservation(
                elapsed_ms=elapsed_ms,
                adapter_cpu=adapter_cpu,
                controller_cpu=controller_cpu,
                ticks={
                    str(adapter_cpu): tuple(current[str(adapter_cpu)]),
                    str(controller_cpu): tuple(current[str(controller_cpu)]),
                },
                adapter_busy_permille=adapter_busy,
                adapter_steal_permille=adapter_steal,
                controller_busy_permille=controller_busy,
                controller_steal_permille=controller_steal,
            )
        )
        previous = current
        previous_clock = now
    return observations


def limits_from_interval(
    *, interval_ms: int, min_interval_ms: int, max_interval_ms: int,
    max_busy_permille: int, max_median_busy_permille: int,
    max_steal_permille: int, min_intervals: int,
) -> ReadinessLimits:
    """Build the frozen readiness limits from the approved design values."""

    return ReadinessLimits(
        min_interval_ms=min_interval_ms,
        max_interval_ms=max_interval_ms,
        max_busy_permille=max_busy_permille,
        max_median_busy_permille=max_median_busy_permille,
        max_steal_permille=max_steal_permille,
        min_intervals=min_intervals,
    )


def assess_readiness(
    *,
    limits: ReadinessLimits,
    observations: Sequence[HostObservation],
) -> ReadinessDiagnostic:
    """Evaluate readiness over measured observations only."""

    converted: list[ReadinessObservation] = []
    for observation in observations:
        if not isinstance(observation, HostObservation):
            raise BenchError(BM_UNSAFE_INPUT, "observations must be HostObservation records")
        converted.append(
            ReadinessObservation(
                elapsed_ms=observation.elapsed_ms,
                busy_permille=max(
                    observation.adapter_busy_permille,
                    observation.controller_busy_permille,
                ),
                steal_permille=max(
                    observation.adapter_steal_permille,
                    observation.controller_steal_permille,
                ),
            )
        )
    return evaluate_readiness(limits, converted)


def host_fingerprint(capabilities: Mapping[str, Any], adapter_cpu: int, controller_cpu: int) -> str:
    """Return the canonical fingerprint of the observed host identity."""

    return content_digest(
        {
            "capabilities": dict(capabilities),
            "adapter_cpu": adapter_cpu,
            "controller_cpu": controller_cpu,
        }
    )


def collect_real_readiness(
    *,
    study_id: str,
    adapter_cpu: int,
    controller_cpu: int,
    limits: ReadinessLimits,
    intervals: int,
    interval_ms: int,
    provider: LinuxCapabilityProvider | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Collect one real readiness record (never a synthetic one)."""

    validate_semantic_id(study_id, "study_id")
    active = provider if provider is not None else LinuxCapabilityProvider()
    capabilities = collect_host_capabilities(active)
    if capabilities["environment"] == "unsupported":
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the host platform is not native Linux or WSL2",
        )
    observations = sample_host(
        adapter_cpu=adapter_cpu,
        controller_cpu=controller_cpu,
        intervals=intervals,
        interval_ms=interval_ms,
        read_text=active.read_text,
        sleep=sleep,
        clock=clock,
    )
    diagnostic = assess_readiness(limits=limits, observations=observations)
    record = {
        "schema": READINESS_SCHEMA,
        "study_id": study_id,
        "host_fingerprint": host_fingerprint(capabilities, adapter_cpu, controller_cpu),
        "adapter_cpu": adapter_cpu,
        "controller_cpu": controller_cpu,
        "environment": capabilities["environment"],
        "limits": {
            "min_interval_ms": limits.min_interval_ms,
            "max_interval_ms": limits.max_interval_ms,
            "max_busy_permille": limits.max_busy_permille,
            "max_median_busy_permille": limits.max_median_busy_permille,
            "max_steal_permille": limits.max_steal_permille,
            "min_intervals": limits.min_intervals,
        },
        "observations": [
            {
                "elapsed_ms": observation.elapsed_ms,
                "ticks": {key: list(value) for key, value in observation.ticks.items()},
                "adapter_busy_permille": observation.adapter_busy_permille,
                "adapter_steal_permille": observation.adapter_steal_permille,
                "controller_busy_permille": observation.controller_busy_permille,
                "controller_steal_permille": observation.controller_steal_permille,
            }
            for observation in observations
        ],
        "status": "READY" if diagnostic.status == "clear" else "BLOCKED",
        "reasons": list(diagnostic.reasons),
    }
    validate_readiness_record(record)
    return record


def validate_readiness_record(document: object) -> dict[str, Any]:
    """Validate the closed readiness record shape (no re-sampling)."""

    doc = require_closed(document, "readiness", _READINESS_KEYS)
    if doc["schema"] != READINESS_SCHEMA:
        raise BenchError(BM_SCHEMA_INVALID, "readiness schema is not the official schema")
    validate_semantic_id(doc["study_id"], "study_id")
    validate_digest(doc["host_fingerprint"], "host_fingerprint")
    adapter = require_uint(doc["adapter_cpu"], "adapter_cpu")
    controller = require_uint(doc["controller_cpu"], "controller_cpu")
    if adapter == controller:
        raise _identity("the pinned CPU pair must differ", "adapter_cpu")
    if doc["environment"] not in ("native-linux", "wsl2"):
        raise _identity("readiness environment is not a supported host class", "environment")
    observations = doc["observations"]
    if not isinstance(observations, list) or not observations:
        raise BenchError(BM_SCHEMA_INVALID, "readiness observations must be a non-empty array")
    for index, observation in enumerate(observations):
        entry = require_closed(
            observation,
            f"observations[{index}]",
            frozenset(
                {
                    "elapsed_ms",
                    "ticks",
                    "adapter_busy_permille",
                    "adapter_steal_permille",
                    "controller_busy_permille",
                    "controller_steal_permille",
                }
            ),
        )
        require_uint(entry["elapsed_ms"], "elapsed_ms")
        for name in (
            "adapter_busy_permille",
            "adapter_steal_permille",
            "controller_busy_permille",
            "controller_steal_permille",
        ):
            if require_uint(entry[name], name) > 1000:
                raise BenchError(BM_SCHEMA_INVALID, f"{name} must be a permille value")
        ticks = entry["ticks"]
        if not isinstance(ticks, Mapping) or set(ticks) != {str(adapter), str(controller)}:
            raise _identity("readiness ticks must cover exactly the CPU pair", "ticks")
        for name, values in ticks.items():
            if not isinstance(values, list) or len(values) != 8:
                raise BenchError(BM_SCHEMA_INVALID, "each tick row must hold eight counters")
            if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
                raise BenchError(BM_SCHEMA_INVALID, "ticks must be non-negative integers")
    if doc["status"] not in ("READY", "BLOCKED"):
        raise _identity("readiness status is not frozen", "status")
    reasons = doc["reasons"]
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise BenchError(BM_SCHEMA_INVALID, "readiness reasons must be strings")
    if doc["status"] == "READY" and reasons:
        raise _identity("a ready record must not carry failure reasons", "reasons")
    if doc["status"] == "BLOCKED" and not reasons:
        raise _identity("a blocked record must carry failure reasons", "reasons")
    bound_payload(doc, "readiness")
    return dict(doc)


# ---------------------------------------------------------------------------
# Exact-window arithmetic
# ---------------------------------------------------------------------------

WindowSet = Mapping[str, str]


def _fraction(value: str, field: str) -> Fraction:
    if not isinstance(value, str):
        raise BenchError(BM_SCHEMA_INVALID, f"{field} must be a decimal string")
    whole, separator, fraction = value.partition(".")
    if not separator or not fraction.isdigit() or len(fraction) != 6 or not whole.isdigit():
        raise BenchError(BM_SCHEMA_INVALID, f"{field} must carry six fractional digits")
    return Fraction(int(whole) * 1_000_000 + int(fraction), 1_000_000)


def frozen_windows() -> WindowSet:
    """Return the frozen A/A numeric windows (never re-derived from data)."""

    return dict(D3C_AA_WINDOWS)


def _median(values: Sequence[Fraction]) -> Fraction:
    if not values:
        raise BenchError(BM_UNSAFE_INPUT, "median requires at least one value")
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def classify_ratios(
    ratios: Sequence[Fraction],
    windows: WindowSet,
    *,
    exempt: bool,
    soft_outliers: int = D3C_AA_SOFT_OUTLIERS,
) -> dict[str, Any]:
    """Apply the frozen A/A window rule to one lane's block ratios."""

    if not ratios:
        raise BenchError(BM_UNSAFE_INPUT, "a lane needs at least one block ratio")
    median = _median(ratios)
    block_min = _fraction(windows["block_min"], "block_min")
    block_max = _fraction(windows["block_max"], "block_max")
    median_min = _fraction(windows["median_min"], "median_min")
    median_max = _fraction(windows["median_max"], "median_max")
    hard_min = _fraction(windows["exempt_hard_min"], "exempt_hard_min")
    hard_max = _fraction(windows["exempt_hard_max"], "exempt_hard_max")
    outliers = [ratio for ratio in ratios if not block_min <= ratio <= block_max]
    median_ok = median_min <= median <= median_max
    if exempt:
        window_ok = len(outliers) <= soft_outliers and all(
            hard_min <= ratio <= hard_max for ratio in ratios
        )
    else:
        window_ok = not outliers
    return {
        "median_ratio": median,
        "passes": bool(median_ok and window_ok),
        "outlier_count": len(outliers),
    }


def decimal_string(value: Fraction) -> str:
    """Render an exact fraction with six fractional digits (half-even-free)."""

    scaled = value * 1_000_000
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    if remainder * 2 >= scaled.denominator:
        whole += 1
    return f"{whole // 1_000_000}.{whole % 1_000_000:06d}"


def assess_cross_engine_control(
    *,
    slots: Iterable[Mapping[str, Any]],
    warm_lane_ids: Sequence[str],
    windows: WindowSet | None = None,
) -> dict[str, Any]:
    """Independently assess the 12x4 Quervant/Quervant control from raw records.

    Each slot carries ``lanes`` with 20 positive integer ``samples_ns``. Two slots
    per arm per block are combined exactly as the frozen D3-C control does (the
    floor mean of the two per-slot medians), then the per-block B/A ratio is taken
    and the frozen windows applied.
    """

    active = dict(windows) if windows is not None else frozen_windows()
    lane_ids = list(warm_lane_ids)
    if not lane_ids:
        raise BenchError(BM_UNSAFE_INPUT, "the control needs at least one warm lane")
    by_arm_block: dict[str, dict[int, dict[int, dict[str, int]]]] = {}
    seen_slots: set[int] = set()
    blocks: set[int] = set()
    for slot in slots:
        if not isinstance(slot, Mapping):
            raise BenchError(BM_UNSAFE_INPUT, "control slots must be objects")
        number = require_uint(slot.get("slot"), "slot")
        block = require_uint(slot.get("block"), "block")
        position = require_uint(slot.get("position"), "position")
        arm = slot.get("arm")
        if arm not in ("A", "B"):
            raise _identity("control slot arm must be A or B", "arm")
        if number in seen_slots:
            raise _identity("control slot numbers must be unique", "slot")
        seen_slots.add(number)
        blocks.add(block)
        lanes = slot.get("lanes")
        if not isinstance(lanes, list):
            raise BenchError(BM_SCHEMA_INVALID, "control slot lanes must be an array")
        observed_ids = [lane.get("lane_id") for lane in lanes]
        if observed_ids != lane_ids:
            raise _identity("control slot lanes are not the exact warm lane set", "lanes")
        medians: dict[str, int] = {}
        for lane in lanes:
            samples = lane.get("samples_ns")
            if not isinstance(samples, list) or len(samples) != 20:
                raise _identity("control lanes must hold twenty samples", "samples_ns")
            if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in samples):
                raise _identity("control samples must be positive integers", "samples_ns")
            medians[str(lane["lane_id"])] = sorted(samples)[9]
        by_arm_block.setdefault(str(arm), {}).setdefault(block, {})[position] = medians

    if len(seen_slots) != 48 or len(blocks) != 12:
        raise _identity("the control must hold exactly 48 slots across 12 blocks", "slots")
    for arm in ("A", "B"):
        for block in sorted(blocks):
            positions = sorted(by_arm_block.get(arm, {}).get(block, {}))
            if len(positions) != 2:
                raise _identity("each arm must appear twice per control block", "slots")

    lane_results: dict[str, Any] = {}
    all_pass = True
    for lane_id in lane_ids:
        ratios: list[Fraction] = []
        for block in sorted(blocks):
            combined: dict[str, int] = {}
            for arm in ("A", "B"):
                positions = sorted(by_arm_block[arm][block])
                values = [by_arm_block[arm][block][position][lane_id] for position in positions]
                combined[arm] = (values[0] + values[1]) // 2
            if combined["A"] <= 0:
                raise _identity("a control median must be positive", "samples_ns")
            ratios.append(Fraction(combined["B"], combined["A"]))
        n, class_name = _lane_coordinates(lane_id)
        exempt = n == 10_000 and class_name in ("absent", "rare")
        result = classify_ratios(ratios, active, exempt=exempt)
        all_pass = all_pass and bool(result["passes"])
        lane_results[lane_id] = {
            "block_ratios": [decimal_string(ratio) for ratio in ratios],
            "median_ratio": decimal_string(result["median_ratio"]),
            "outlier_count": result["outlier_count"],
            "passes": bool(result["passes"]),
            "exempt": exempt,
        }
    return {
        "schema": CONTROL_ASSESSMENT_SCHEMA,
        "a_a": {"passes": all_pass, "lanes": lane_results},
        "windows": dict(active),
        "lanes": lane_ids,
        "slot_count": len(seen_slots),
        "block_count": len(blocks),
    }


def _lane_coordinates(lane_id: str) -> tuple[int, str]:
    parts = lane_id.split("/")
    if len(parts) != 4 or not parts[1].isdigit():
        raise BenchError(BM_SCHEMA_INVALID, f"lane id {lane_id!r} is not a known lane identity")
    return int(parts[1]), parts[2]


# ---------------------------------------------------------------------------
# Retained-key control (original measured D3-C A/A)
# ---------------------------------------------------------------------------


def assess_retained_key_control(
    *,
    slots: Iterable[Mapping[str, Any]],
    lane_ids: Sequence[str],
    windows: WindowSet | None = None,
) -> dict[str, Any]:
    """Recompute the D3-C control A/A assessment from raw slot records."""

    active = dict(windows) if windows is not None else frozen_windows()
    lane_order = list(lane_ids)
    if len(lane_order) != 72:
        raise _identity("the retained-key control must cover exactly 72 lanes", "lane_ids")
    ordered = list(slots)
    if len(ordered) != 48:
        raise _identity("the retained-key control must hold exactly 48 slots", "slots")
    by_arm_block: dict[str, dict[int, dict[int, dict[str, int]]]] = {}
    for slot in ordered:
        arm = slot.get("arm")
        if arm not in ("A", "B"):
            raise _identity("retained-key control arms must be A/B", "arm")
        block = require_uint(slot.get("block"), "block")
        position = require_uint(slot.get("position"), "position")
        lanes = slot.get("lanes")
        if not isinstance(lanes, list) or [lane.get("id") for lane in lanes] != lane_order:
            raise _identity("retained-key control lanes are not the exact 72-lane set", "lanes")
        medians: dict[str, int] = {}
        for lane in lanes:
            median = lane.get("summary_ns", {}).get("median") if isinstance(lane.get("summary_ns"), Mapping) else None
            if isinstance(median, bool) or not isinstance(median, int) or median <= 0:
                raise _identity("retained-key control lane median must be positive", "median")
            medians[str(lane["id"])] = median
        by_arm_block.setdefault(str(arm), {}).setdefault(block, {})[position] = medians
    lane_results: dict[str, Any] = {}
    all_pass = True
    for lane_id in lane_order:
        ratios: list[Fraction] = []
        for block in range(1, 13):
            positions_a = sorted(by_arm_block.get("A", {}).get(block, {}))
            positions_b = sorted(by_arm_block.get("B", {}).get(block, {}))
            if len(positions_a) != 2 or len(positions_b) != 2:
                raise _identity("each retained-key control arm must appear twice per block", "slots")
            a_values = [by_arm_block["A"][block][position][lane_id] for position in positions_a]
            b_values = [by_arm_block["B"][block][position][lane_id] for position in positions_b]
            combined_a = (a_values[0] + a_values[1]) // 2
            combined_b = (b_values[0] + b_values[1]) // 2
            if combined_a <= 0:
                raise _identity("a retained-key control median must be positive", "median")
            ratios.append(Fraction(combined_b, combined_a))
        n, class_name = _lane_coordinates(lane_id)
        exempt = n == 10_000 and class_name in ("absent", "rare")
        result = classify_ratios(ratios, active, exempt=exempt)
        all_pass = all_pass and bool(result["passes"])
        lane_results[lane_id] = {
            "block_ratios": [decimal_string(ratio) for ratio in ratios],
            "median_ratio": decimal_string(result["median_ratio"]),
            "outlier_count": result["outlier_count"],
            "passes": bool(result["passes"]),
            "exempt": exempt,
        }
    return {
        "schema": RETAINED_KEY_CONTROL_SCHEMA,
        "a_a": {"passes": all_pass, "lanes": lane_results},
        "windows": dict(active),
        "lanes": lane_order,
        "slot_count": 48,
        "block_count": 12,
    }


def require_control_pass(assessment: Mapping[str, Any], field: str = "control-assessment") -> Mapping[str, Any]:
    """Require an assessed control to pass before any treatment is allowed."""

    a_a = assessment.get("a_a")
    if not isinstance(a_a, Mapping) or a_a.get("passes") is not True:
        raise _identity("the real A/A control does not pass; treatment is blocked", field)
    return assessment


def control_digest(assessment: Mapping[str, Any]) -> str:
    """Return the canonical digest of an assessed control document."""

    return content_digest(dict(assessment))


__all__ = [
    "CONTROL_ASSESSMENT_SCHEMA",
    "CONTROL_SCHEMA",
    "HostObservation",
    "READINESS_SCHEMA",
    "RETAINED_KEY_CONTROL_SCHEMA",
    "assess_cross_engine_control",
    "assess_readiness",
    "assess_retained_key_control",
    "classify_ratios",
    "collect_real_readiness",
    "compute_interval",
    "control_digest",
    "decimal_string",
    "frozen_windows",
    "host_fingerprint",
    "limits_from_interval",
    "parse_proc_stat",
    "require_control_pass",
    "sample_host",
    "validate_readiness_record",
]
