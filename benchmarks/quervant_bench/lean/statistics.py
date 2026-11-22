"""Direct paired-block benchmark analysis; no source/evidence certification dependency.

Each block is the resampling unit. A slot contributes one median, each arm/block
contributes the mean of its slot medians, and the paired estimator is the median
of treatment/baseline ratios. Statistical outcomes are not approval gates.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, localcontext
import hashlib
from random import Random
from statistics import median
from typing import Any, Mapping, Sequence

from .artifacts import ArtifactError

ESTIMATOR = "median-paired-ratios-v1"


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ArtifactError(f"{label} must be a positive integer")
    return value


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ArtifactError(f"{label} must be numeric")
    try:
        number = Decimal(str(value))
    except ArithmeticError as error:
        raise ArtifactError(f"{label} is invalid") from error
    if not number.is_finite() or number < 0:
        raise ArtifactError(f"{label} must be finite and nonnegative")
    return number


def _median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ArtifactError("median requires observations")
    return median(values)


def _effect(ratio: Decimal, direction: str) -> Decimal:
    if direction == "lower":
        return Decimal(100) * (Decimal(1) - ratio)
    if direction == "higher":
        return Decimal(100) * (ratio - Decimal(1))
    raise ArtifactError("metric direction must be lower or higher")


def _finite_float(value: Decimal) -> float:
    result = float(value)
    if result == float("inf") or result == float("-inf"):
        raise ArtifactError("numeric estimate outside reportable range")
    return result


def schedule(arms: Sequence[str], *, blocks: int, slots_per_arm: int, seed: int) -> list[dict[str, int | str]]:
    """Produce a seeded, exactly position-balanced, randomized cyclic schedule.

    A block contains equal multiplicity of each arm. A shuffled base tile is
    expanded with cyclic rotations in cycles of arm_count blocks.
    """
    _positive_int(blocks, "blocks")
    _positive_int(slots_per_arm, "slots_per_arm")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
        raise ArtifactError("schedule seed must be an unsigned 64-bit integer")
    if len(arms) < 2 or len(arms) > 8 or len(set(arms)) != len(arms):
        raise ArtifactError("schedule needs 2-8 distinct arms")
    if any(not isinstance(x, str) or not x for x in arms):
        raise ArtifactError("invalid arm ID")
    if blocks % len(arms):
        raise ArtifactError("block count must be divisible by arm count for exact position balance")
    random = Random(seed)
    result: list[dict[str, int | str]] = []
    for cycle in range(blocks // len(arms)):
        tile = list(arms)
        random.shuffle(tile)
        rotations = list(range(len(arms)))
        random.shuffle(rotations)
        for rotation in rotations:
            # Count blocks by completed slot groups, not the number of rows.
            block = len(result) // (len(arms) * slots_per_arm) + 1
            expanded = [tile[(position + rotation) % len(arms)] for position in range(len(arms)) for _ in range(slots_per_arm)]
            # Shift the slot order within each balanced block without breaking
            # positional balance of occurrences across the rotation cycle.
            for position, arm in enumerate(expanded, start=1):
                result.append({"block": block, "position": position, "arm_id": arm})
    # The tiles above place each repeated arm in adjacent slot positions. The
    # exact balance guarantee follows from rotating one entire tile per cycle.
    for position in range(1, len(arms) * slots_per_arm + 1):
        counts = Counter(r["arm_id"] for r in result if r["position"] == position)
        if any(counts[a] != blocks // len(arms) for a in arms):
            raise ArtifactError("generated schedule is not position-balanced")
    return result


def analyze(
    samples: Sequence[Mapping[str, Any]],
    *,
    arms: Sequence[str],
    baseline: str,
    lanes: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate complete raw samples and derive effects, CIs and outcomes."""
    if not isinstance(samples, (list, tuple)) or not samples:
        raise ArtifactError("no raw samples")
    if len(set(arms)) != len(arms) or baseline not in arms:
        raise ArtifactError("baseline and arms inconsistent")
    blocks = _positive_int(policy.get("blocks"), "blocks")
    repetitions = _positive_int(policy.get("slots_per_arm"), "slots_per_arm")
    sample_count = _positive_int(policy.get("samples"), "samples")
    resamples = _positive_int(policy.get("bootstrap_resamples"), "bootstrap_resamples")
    if resamples > 100_000:
        raise ArtifactError("bootstrap resampling budget exceeded")
    seed = policy.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
        raise ArtifactError("bootstrap seed must be a 64-bit unsigned integer")
    min_blocks = _positive_int(policy.get("min_blocks", 4), "min_blocks")
    min_gain = _decimal(policy.get("min_gain_percent", 0), "min_gain_percent")
    regression = _decimal(policy.get("max_regression_percent", 0), "max_regression_percent")
    max_aa = _decimal(policy.get("max_aa_gain_percent", 10), "max_aa_gain_percent")
    excluded = policy.get("exclude_blocks", {})
    if not isinstance(excluded, dict):
        raise ArtifactError("exclude_blocks must map lanes to declared whole blocks")
    lane_map = {lane["id"]: lane for lane in lanes}
    if len(lane_map) != len(lanes) or not lane_map:
        raise ArtifactError("lane identifiers must be unique")
    unexpected_exclusions = set(excluded) - set(lane_map)
    if unexpected_exclusions:
        raise ArtifactError("exclusions refer to unknown lanes")
    matrix: dict[tuple[str, int, int, str], Decimal] = {}
    positions: dict[tuple[int, int], str] = {}
    for item in samples:
        arm = item.get("arm_id")
        lane = item.get("lane_id")
        block = _positive_int(item.get("block"), "sample block")
        position = _positive_int(item.get("position"), "slot position")
        if arm not in arms or lane not in lane_map or block > blocks or position > len(arms) * repetitions:
            raise ArtifactError("sample references an undeclared arm, lane, block or position")
        if item.get("oracle_ok") is not True:
            raise ArtifactError("cannot analyze samples without verified search correctness")
        observations = item.get("samples_ns")
        if not isinstance(observations, list) or len(observations) != sample_count:
            raise ArtifactError("slot has an incomplete timed sample series")
        if any(isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in observations):
            raise ArtifactError("timed observations must be positive integer nanoseconds")
        key = (str(lane), block, position, str(arm))
        if key in matrix:
            raise ArtifactError("duplicate slot/lane sample")
        current = positions.setdefault((block, position), str(arm))
        if current != arm:
            raise ArtifactError("slot position assigned to multiple arms")
        matrix[key] = _median([Decimal(x) for x in observations])
    if len(positions) != blocks * len(arms) * repetitions:
        raise ArtifactError("incomplete block/slot schedule")
    for block in range(1, blocks + 1):
        counts = Counter(positions[(block, p)] for p in range(1, len(arms) * repetitions + 1))
        if any(counts[arm] != repetitions for arm in arms):
            raise ArtifactError("unbalanced block/slot acquisition")
    if len(matrix) != len(positions) * len(lanes):
        raise ArtifactError("missing per-lane slot samples")
    for key, arm in positions.items():
        if any((lane, *key, arm) not in matrix for lane in lane_map):
            raise ArtifactError("missing per-lane slot measurements")

    result: dict[str, Any] = {"schema": "bm10-analysis-v1", "estimator": ESTIMATOR,
                              "bootstrap_method": "paired-whole-block-percentile-v1", "lanes": {}}
    with localcontext() as ctx:
        ctx.prec = 50
        for lane_id, lane in lane_map.items():
            direction = lane.get("direction", "lower")
            unit = lane.get("unit", "ns")
            if direction not in ("lower", "higher") or not isinstance(unit, str) or not unit:
                raise ArtifactError("invalid lane metric direction/unit")
            exclusions = excluded.get(lane_id, [])
            if not isinstance(exclusions, list) or len(set(exclusions)) != len(exclusions):
                raise ArtifactError("exclusions must be a list of unique block numbers")
            if any(isinstance(x, bool) or not isinstance(x, int) or not 1 <= x <= blocks for x in exclusions):
                raise ArtifactError("excluded block outside schedule")
            raw_blocks: dict[str, list[Decimal]] = {arm: [] for arm in arms}
            for block in range(1, blocks + 1):
                for arm in arms:
                    values = [v for (ln, b, _p, a), v in matrix.items() if ln == lane_id and b == block and a == arm]
                    if len(values) != repetitions:
                        raise ArtifactError("block is missing arm/slot observations")
                    raw_blocks[arm].append(sum(values) / Decimal(repetitions))
            eligible = [block - 1 for block in range(1, blocks + 1) if block not in exclusions]
            row: dict[str, Any] = {
                "metric": lane.get("metric", "search_latency"), "unit": unit,
                "direction": direction, "raw_blocks": blocks,
                "excluded_blocks": sorted(exclusions), "retained_blocks": len(eligible),
                "arm_absolute": {a: {"median_block_value": _finite_float(_median(v)),
                                     "block_values": [_finite_float(x) for x in v]} for a, v in raw_blocks.items()},
                "comparisons": {},
            }
            comparable = lane.get("comparability", "COMPARABLE") == "COMPARABLE"
            for arm in arms:
                if arm == baseline:
                    continue
                if not comparable:
                    row["comparisons"][arm] = {"status": "NON_COMPARABLE", "reason": lane.get("reason", "operation mismatch")}
                    continue
                if len(eligible) < min_blocks:
                    row["comparisons"][arm] = {"status": "INCONCLUSIVE", "reason": "insufficient retained blocks"}
                    continue
                denominator = raw_blocks[baseline]
                if any(denominator[i] <= 0 for i in eligible):
                    row["comparisons"][arm] = {"status": "NOT_COMPUTABLE", "reason": "zero baseline"}
                    continue
                ratios = [raw_blocks[arm][i] / denominator[i] for i in eligible]
                center = _median(ratios)
                seed_bytes = hashlib.sha256(f"{seed}|{lane_id}|{arm}".encode("utf-8")).digest()
                rng = Random(int.from_bytes(seed_bytes[:8], "big"))
                draws = sorted(_median([ratios[rng.randrange(len(ratios))] for _ in ratios]) for _ in range(resamples))
                lo = draws[max(0, (resamples * 25 + 999) // 1000 - 1)]
                hi = draws[min(resamples - 1, (resamples * 975 + 999) // 1000 - 1)]
                signed = _effect(center, direction)
                ci_gain = sorted((_effect(lo, direction), _effect(hi, direction)))
                if arm in set(policy.get("control_arms", [])):
                    status = "PASS" if abs(signed) <= max_aa and ci_gain[0] >= -max_aa and ci_gain[1] <= max_aa else "FAIL"
                    kind = "A/A"
                else:
                    kind = "treatment"
                    status = ("IMPROVED" if ci_gain[0] > min_gain else
                              "REGRESSED" if ci_gain[1] < -regression else "INCONCLUSIVE")
                row["comparisons"][arm] = {
                    "kind": kind, "status": status, "baseline_arm": baseline,
                    "treatment_arm": arm, "ratio_b_over_a": _finite_float(center),
                    "ratio_ci_95": [_finite_float(lo), _finite_float(hi)],
                    "gain_percent": _finite_float(signed),
                    "gain_ci_95_percent": [_finite_float(x) for x in ci_gain],
                    "retained_paired_ratios": [_finite_float(x) for x in ratios],
                    "bootstrap_resamples": resamples,
                }
            result["lanes"][lane_id] = row
    return result


def compare_historical(current: Mapping[str, Any], historical: Mapping[str, Any] | None,
                       *, lane_id: str, treatment_arm: str) -> dict[str, Any]:
    """Compare within-run effect percentages only; never absolute timings."""
    if historical is None:
        return {"status": "UNAVAILABLE", "reason": "historical result unavailable"}
    try:
        curr = current["analysis"]["lanes"][lane_id]
        hist = historical["analysis"]["lanes"][lane_id]
        c = curr["comparisons"][treatment_arm]
        h = hist["comparisons"][treatment_arm]
    except (KeyError, TypeError):
        return {"status": "NOT_COMPARABLE", "reason": "missing matching lane/arm effects"}
    attributes = ("metric", "unit", "direction")
    if any(curr.get(x) != hist.get(x) for x in attributes):
        return {"status": "NOT_COMPARABLE", "reason": "metric/unit/direction differ"}
    if any(c.get(x) != h.get(x) for x in ("kind", "baseline_arm", "treatment_arm")) or c.get("kind") != "treatment":
        return {"status": "NOT_COMPARABLE", "reason": "arm roles/orientation differ"}
    if current["analysis"].get("estimator") != historical["analysis"].get("estimator"):
        return {"status": "NOT_COMPARABLE", "reason": "estimators differ"}
    coordinates = ("workload_id", "cache_regime", "timed_operation", "query_semantics")
    clane = next((x for x in current.get("lanes", []) if x.get("id") == lane_id), {})
    hlane = next((x for x in historical.get("lanes", []) if x.get("id") == lane_id), {})
    if not clane or not hlane or any(clane.get(x) != hlane.get(x) for x in coordinates):
        return {"status": "NOT_COMPARABLE", "reason": "workload or timed operation differs"}
    if "gain_percent" not in c or "gain_percent" not in h:
        return {"status": "UNAVAILABLE", "reason": "a run lacks a computable effect"}
    contexts_match = current.get("context") == historical.get("context")
    return {
        "status": "COMPARABLE" if contexts_match else "CONTEXT_CHANGED",
        "historical_gain_percent": h["gain_percent"],
        "current_gain_percent": c["gain_percent"],
        "effect_change_percentage_points": c["gain_percent"] - h["gain_percent"],
        "caution": "descriptive change only; not a code-only causal claim" if not contexts_match else None,
    }
