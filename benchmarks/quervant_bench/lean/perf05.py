"""PERF-05-C: deterministic B-only warm analysis against retained historical A.

Pure, read-only helpers. Nothing here launches a benchmark, builds an adapter,
opens an index, starts a service, samples the CPU or runs a profiler. The
historical A result is loaded from one frozen on-disk path and compared
descriptively; it is never re-executed or paired sample-by-sample with B.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from . import runtime
from .artifacts import ArtifactError, load_result
from .configuration import (
    PERF05_HISTORICAL_ARM,
    PERF05_HISTORICAL_BLOB,
    PERF05_HISTORICAL_CONFIGURATION_ID,
    PERF05_HISTORICAL_MODE,
    PERF05_HISTORICAL_RESULT,
    PERF05_HISTORICAL_RUN_ID,
    PERF05_HISTORICAL_SOURCE,
    lanes_for,
)

HISTORICAL_RELATIVE_PATH = (
    "benchmarks/studies/cross-engine/warm/results/" + PERF05_HISTORICAL_RESULT
)
PRIMARY_LANES = frozenset({
    "100000/medium/k10/warm",
    "100000/medium/k100/warm",
    "100000/common/k10/warm",
    "100000/common/k100/warm",
})
PRIMARY_MAX_RATIO = Decimal("0.95")
GUARD_MAX_RATIO = Decimal("1.10")
B_SLOTS_PER_LANE = 24
B_BLOCK_COUNT = 12

# Frozen historical Q-arm medians (nanoseconds) from the retained result.
EXPECTED_MEDIANS = {
    "10000/absent/k10/warm": "39013",
    "10000/absent/k100/warm": "38825.25",
    "10000/rare/k10/warm": "47526",
    "10000/rare/k100/warm": "47150.5",
    "10000/medium/k10/warm": "1487246.125",
    "10000/medium/k100/warm": "1593144.75",
    "10000/common/k10/warm": "3239065.125",
    "10000/common/k100/warm": "3273317",
    "100000/absent/k10/warm": "231715.625",
    "100000/absent/k100/warm": "232478",
    "100000/rare/k10/warm": "242403.125",
    "100000/rare/k100/warm": "241365.625",
    "100000/medium/k10/warm": "15438918.875",
    "100000/medium/k100/warm": "15528062.875",
    "100000/common/k10/warm": "33829324",
    "100000/common/k100/warm": "33481856.875",
}


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ArtifactError(f"{label} must be numeric")
    try:
        number = Decimal(str(value))
    except (ArithmeticError, ValueError) as error:
        raise ArtifactError(f"{label} is invalid") from error
    if not number.is_finite() or number < 0:
        raise ArtifactError(f"{label} must be finite and nonnegative")
    return number


def _finite(value: Decimal) -> float:
    result = float(value)
    if result == float("inf") or result == float("-inf"):
        raise ArtifactError("B-only estimate outside reportable range")
    return result


def verify_historical_reference(root: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the one frozen historical A result without executing A.

    Returns a read-only summary (identifiers, 16 Q medians/block vectors and
    context). Any mismatch is a typed ArtifactError before B acquisition.
    """
    reference = config.get("historical_reference")
    if not isinstance(reference, Mapping):
        raise ArtifactError("perf-05 configuration lacks historical_reference")
    expected = {
        "family": "cross-engine",
        "result_file": PERF05_HISTORICAL_RESULT,
        "git_blob_sha1": PERF05_HISTORICAL_BLOB,
        "configuration_id": PERF05_HISTORICAL_CONFIGURATION_ID,
        "run_id": PERF05_HISTORICAL_RUN_ID,
        "arm": PERF05_HISTORICAL_ARM,
        "source_revision": PERF05_HISTORICAL_SOURCE,
        "mode": PERF05_HISTORICAL_MODE,
    }
    if dict(reference) != expected:
        raise ArtifactError("perf-05 historical reference is not the fixed reference")

    path = Path(root) / HISTORICAL_RELATIVE_PATH
    if path.is_symlink() or not path.is_file():
        raise ArtifactError("historical A result file is missing or symlinked")
    try:
        digest = runtime._git(root, "hash-object", HISTORICAL_RELATIVE_PATH)
    except (ArtifactError, OSError, ValueError) as error:
        raise ArtifactError(f"cannot identify historical A result: {error}") from error
    if digest != PERF05_HISTORICAL_BLOB:
        raise ArtifactError("historical A result Git blob differs from the frozen identity")

    try:
        data = load_result(path)
    except ArtifactError as error:
        raise ArtifactError(f"historical A result cannot be loaded: {error}") from error
    if data.get("family") != "cross-engine" or data.get("status") != "COMPLETE":
        raise ArtifactError("historical A result is not a complete cross-engine result")
    for field, expected_value in (
            ("configuration_id", PERF05_HISTORICAL_CONFIGURATION_ID),
            ("run_id", PERF05_HISTORICAL_RUN_ID)):
        if data.get(field) != expected_value:
            raise ArtifactError(f"historical A {field} differs from the frozen identity")

    context = data.get("context")
    build = context.get("build") if isinstance(context, Mapping) else None
    if not isinstance(context, Mapping) or not isinstance(build, Mapping):
        raise ArtifactError("historical A result lacks build/source context")
    if (context.get("source_revision") != PERF05_HISTORICAL_SOURCE or
            build.get("source_revision") != PERF05_HISTORICAL_SOURCE):
        raise ArtifactError("historical A measured source revision differs")
    if build.get("compiler_options") != "cargo --release --locked":
        raise ArtifactError("historical A was not a release/locked uninstrumented build")
    if build.get("quervant_strategy_feature_enabled") is not False:
        raise ArtifactError("historical A build unexpectedly enabled the strategy feature")

    expected_lanes = {lane["id"] for lane in lanes_for(config)}
    analysis = data.get("analysis")
    lanes = analysis.get("lanes") if isinstance(analysis, Mapping) else None
    if not isinstance(lanes, Mapping) or set(lanes) != expected_lanes:
        raise ArtifactError("historical A lane matrix differs from the warm study")

    controls = data.get("controls")
    control_analysis = controls.get("analysis") if isinstance(controls, Mapping) else None
    control_lanes = control_analysis.get("lanes") if isinstance(control_analysis, Mapping) else None
    if not isinstance(control_lanes, Mapping) or set(control_lanes) != expected_lanes:
        raise ArtifactError("historical A/A control lane matrix differs")
    for lane_id, lane in control_lanes.items():
        comparisons = lane.get("comparisons") if isinstance(lane, Mapping) else None
        if (not isinstance(comparisons, Mapping) or not comparisons or
                any(not isinstance(value, Mapping) or value.get("status") != "PASS"
                    for value in comparisons.values())):
            raise ArtifactError(f"historical A/A control is not PASS in {lane_id}")
    if isinstance(controls, Mapping):
        for key, value in controls.items():
            if key.startswith("readiness_") and isinstance(value, Mapping):
                if value.get("status") != "clear":
                    raise ArtifactError(f"historical readiness observation {key} is not clear")

    raw = data.get("raw_samples")
    if not isinstance(raw, list):
        raise ArtifactError("historical A result lacks raw samples")
    q_samples = [row for row in raw
                 if isinstance(row, Mapping) and row.get("arm_id") == PERF05_HISTORICAL_ARM]
    if not q_samples:
        raise ArtifactError("historical Q raw samples are missing")
    if any(row.get("oracle_ok") is not True for row in q_samples):
        raise ArtifactError("historical Q raw sample has oracle_ok != True")
    if {row.get("lane_id") for row in q_samples} != expected_lanes:
        raise ArtifactError("historical Q raw samples do not cover every lane")

    summary_lanes: dict[str, Any] = {}
    for lane_id in sorted(expected_lanes):
        arm_absolute = lanes[lane_id].get("arm_absolute") if isinstance(lanes[lane_id], Mapping) else None
        q = arm_absolute.get(PERF05_HISTORICAL_ARM) if isinstance(arm_absolute, Mapping) else None
        if not isinstance(q, Mapping):
            raise ArtifactError(f"historical Q arm is missing in {lane_id}")
        block_values = q.get("block_values")
        if not isinstance(block_values, list) or len(block_values) != B_BLOCK_COUNT:
            raise ArtifactError(f"historical Q block vector is not 12 values in {lane_id}")
        decimals = [_decimal(value, f"historical block value {lane_id}") for value in block_values]
        if any(value <= 0 for value in decimals):
            raise ArtifactError(f"historical Q block value is nonpositive in {lane_id}")
        recomputed = median(decimals)
        stored = _decimal(q.get("median_block_value"), f"historical median {lane_id}")
        if recomputed != stored:
            raise ArtifactError(f"historical Q median does not recompute in {lane_id}")
        if stored != Decimal(EXPECTED_MEDIANS[lane_id]):
            raise ArtifactError(f"historical Q median differs from the frozen fixture in {lane_id}")
        summary_lanes[lane_id] = {
            "median_block_value": _finite(stored),
            "block_values": [_finite(value) for value in decimals],
        }

    return {
        "schema": "bm10-historical-reference-v1",
        "result_file": PERF05_HISTORICAL_RESULT,
        "git_blob_sha1": PERF05_HISTORICAL_BLOB,
        "configuration_id": PERF05_HISTORICAL_CONFIGURATION_ID,
        "run_id": PERF05_HISTORICAL_RUN_ID,
        "arm": PERF05_HISTORICAL_ARM,
        "source_revision": PERF05_HISTORICAL_SOURCE,
        "mode": PERF05_HISTORICAL_MODE,
        "lanes": summary_lanes,
        "context": dict(context),
    }


def _context_differences(current: Mapping[str, Any],
                         historical: Mapping[str, Any]) -> list[str]:
    differences: list[str] = []
    if not isinstance(current, Mapping) or not isinstance(historical, Mapping):
        return ["context unavailable"]
    current_host = current.get("host") if isinstance(current.get("host"), Mapping) else current
    historical_host = historical.get("host") if isinstance(historical.get("host"), Mapping) else {}
    for key in ("system", "architecture", "filesystem"):
        if current_host.get(key) != historical_host.get(key):
            differences.append(
                f"host.{key}: {current_host.get(key)!r} != {historical_host.get(key)!r}")
    current_build = current.get("build") if isinstance(current.get("build"), Mapping) else {}
    historical_build = historical.get("build") if isinstance(historical.get("build"), Mapping) else {}
    for key in ("compiler_options", "quervant_strategy_feature_enabled"):
        if current_build.get(key) != historical_build.get(key):
            differences.append(
                f"build.{key}: {current_build.get(key)!r} != {historical_build.get(key)!r}")
    current_tools = current_host.get("toolchains")
    historical_tools = historical_host.get("toolchains")
    if isinstance(current_tools, Mapping) and isinstance(historical_tools, Mapping):
        for key in ("rustc", "cargo"):
            if current_tools.get(key) != historical_tools.get(key):
                differences.append(
                    f"toolchain.{key}: {current_tools.get(key)!r} != {historical_tools.get(key)!r}")
    return differences


def analyze_b_only(
    b_raw: Sequence[Mapping[str, Any]],
    bb_analysis: Mapping[str, Any],
    historical: Mapping[str, Any],
    config: Mapping[str, Any],
    host_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Compute the B absolute estimate and the descriptive historical ratios."""
    lanes = lanes_for(config)
    lane_ids = {lane["id"] for lane in lanes}
    if not isinstance(b_raw, (list, tuple)) or len(b_raw) != B_SLOTS_PER_LANE * len(lane_ids):
        raise ArtifactError("B-only acquisition does not contain 24 slots for every lane")
    counts = Counter(row.get("lane_id") for row in b_raw if isinstance(row, Mapping))
    if set(counts) != lane_ids or any(counts[lane_id] != B_SLOTS_PER_LANE for lane_id in lane_ids):
        raise ArtifactError("B-only slot/lane records are incomplete")
    if any(row.get("oracle_ok") is not True for row in b_raw):
        raise ArtifactError("B-only raw observation has oracle_ok != True")

    bb_lanes = bb_analysis.get("lanes") if isinstance(bb_analysis, Mapping) else None
    if not isinstance(bb_lanes, Mapping) or set(bb_lanes) != lane_ids:
        raise ArtifactError("B/B analysis lane matrix differs")
    for lane_id, lane in bb_lanes.items():
        comparisons = lane.get("comparisons") if isinstance(lane, Mapping) else None
        if not isinstance(comparisons, Mapping) or not comparisons:
            raise ArtifactError(f"B/B lane lacks comparisons: {lane_id}")
        for arm, comparison in comparisons.items():
            if not isinstance(comparison, Mapping) or comparison.get("status") != "PASS":
                raise ArtifactError(f"B/B control is not PASS: {lane_id}/{arm}")
        absolute = lane.get("arm_absolute")
        for arm in ("BB", "BB2"):
            values = absolute.get(arm) if isinstance(absolute, Mapping) else None
            if (not isinstance(values, Mapping) or
                    not isinstance(values.get("block_values"), list) or
                    len(values["block_values"]) != B_BLOCK_COUNT):
                raise ArtifactError(f"B/B absolute block vector is incomplete: {lane_id}/{arm}")

    differences = _context_differences(
        host_context, historical.get("context", {}) if isinstance(historical, Mapping) else {})
    recorded_lanes = historical.get("lanes") if isinstance(historical, Mapping) else None
    if not isinstance(recorded_lanes, Mapping) or set(recorded_lanes) != lane_ids:
        raise ArtifactError("historical comparison lane matrix differs")
    out_lanes: dict[str, Any] = {}
    historical_comparison: dict[str, Any] = {}
    for lane in lanes:
        lane_id = lane["id"]
        absolute = bb_lanes[lane_id]["arm_absolute"]
        bb_values = absolute["BB"]["block_values"]
        bb2_values = absolute["BB2"]["block_values"]
        b_blocks = [
            (_decimal(bb_value, f"BB block {lane_id}") +
             _decimal(bb2_value, f"BB2 block {lane_id}")) / Decimal(2)
            for bb_value, bb2_value in zip(bb_values, bb2_values)
        ]
        b_median = median(b_blocks)
        recorded = recorded_lanes[lane_id]
        a_median = _decimal(recorded["median_block_value"], f"historical median {lane_id}")
        if a_median <= 0:
            raise ArtifactError(f"historical median is nonpositive in {lane_id}")
        ratio = b_median / a_median
        gain = Decimal(100) * (Decimal(1) - ratio)
        primary = lane_id in PRIMARY_LANES
        limit = PRIMARY_MAX_RATIO if primary else GUARD_MAX_RATIO
        out_lanes[lane_id] = {
            "metric": lane.get("metric", "search_latency"),
            "unit": lane.get("unit", "ns"),
            "direction": "lower",
            "cache_regime": lane.get("cache_regime"),
            "arm_absolute": {
                "B": {
                    "median_block_value": _finite(b_median),
                    "block_values": [_finite(value) for value in b_blocks],
                }
            },
            "comparisons": {},
        }
        historical_comparison[lane_id] = {
            "comparison_kind": "HISTORICAL_UNPAIRED_ABSOLUTE",
            "lane_class": "PRIMARY" if primary else "GUARD",
            "A": {
                "median_block_value": _finite(a_median),
                "block_values": list(recorded["block_values"]),
            },
            "B": {
                "median_block_value": _finite(b_median),
                "block_values": [_finite(value) for value in b_blocks],
            },
            "ratio_b_over_historical_a": _finite(ratio),
            "gain_percent": _finite(gain),
            "max_ratio": _finite(limit),
            "within_threshold": ratio <= limit,
        }

    if differences:
        disposition = "B_ONLY_HISTORICAL_CONTEXT_CHANGED"
    elif all(row["within_threshold"] for row in historical_comparison.values()):
        disposition = "B_ONLY_HISTORICAL_TARGETS_MET"
    else:
        disposition = "B_ONLY_HISTORICAL_TARGETS_NOT_MET"
    return {
        "schema": "bm10-b-only-analysis-v1",
        "estimator": "median-of-two-b-slot-medians-per-block-v1",
        "bootstrap_method": "NONE_FOR_HISTORICAL_COMPARISON",
        "comparison_kind": "HISTORICAL_UNPAIRED_ABSOLUTE",
        "lanes": out_lanes,
        "historical_comparison": historical_comparison,
        "context": {"matches": not differences, "differences": differences},
        "disposition": disposition,
    }
