"""Independent reconstruction of BM-04 paired arithmetic and exclusions.

Nothing in this module imports ``analysis.arithmetic``, ``analysis.pruning``,
``analysis.bootstrap`` or the BM-04 decimal formatting helpers. The formulas are
re-derived from the frozen written contract:

* per-slot statistical median (never a pooled or floor-division approximation);
* per-arm block value as the mean of that arm's declared **slot medians**;
* ``within-arm-spread-v1`` symmetric whole-block exclusion on the unfiltered
  spread, applied to every arm;
* direction-aware normalised effects where a smaller value is always better;
* both frozen estimators (median of paired ratios, ratio of arm medians);
* 12-place round-half-even rendering with an independently implemented
  quantisation step.

All calculations use a fresh ``Context(prec=50, rounding=ROUND_HALF_EVEN)``. An
ambient global decimal context is never read and never mutated.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from typing import Any, Protocol

from ..config.errors import BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BenchError
from ..protocol.schedule import ScheduleSlot
from .contracts import (
    DECIMAL_PRECISION,
    DECIMAL_QUANTUM,
    DIRECTIONS,
    ESTIMATOR_MEDIAN_PAIRED_RATIOS,
    ESTIMATOR_RATIO_OF_ARM_MEDIANS,
    ESTIMATORS,
    LANE_STATUS_ANALYZED,
    LANE_STATUS_INSUFFICIENT,
    OUTPUT_DECIMAL_PLACES,
)

_DECIMAL_LITERAL = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]{1,12})?$")


def _invalid(message: str, field_path: str = "value") -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


def _identity(message: str, field_path: str = "value") -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def decimal_context() -> Context:
    """Return a fresh precision-50 round-half-even context (never global)."""

    return Context(prec=DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN)


# ---------------------------------------------------------------------------
# Decimal form
# ---------------------------------------------------------------------------


def require_decimal(value: object, field_path: str) -> Decimal:
    """Require a finite positive ``Decimal`` (never a bool, int or float)."""

    if not isinstance(value, Decimal):
        raise _invalid(f"{field_path} must be a Decimal", field_path)
    if not value.is_finite():
        raise _invalid(f"{field_path} must be finite", field_path)
    if value <= 0:
        raise _invalid(f"{field_path} must be positive", field_path)
    return value


def parse_effect_literal(value: object, field_path: str) -> Decimal:
    """Parse one canonical unsigned decimal literal (1..12 fractional places)."""

    if not isinstance(value, str) or _DECIMAL_LITERAL.fullmatch(value) is None:
        raise _invalid(
            f"{field_path} must be an unsigned decimal literal with at most "
            f"{OUTPUT_DECIMAL_PLACES} fractional places",
            field_path,
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - regex already excludes this
        raise _invalid(f"{field_path} is not a decimal", field_path) from exc
    if not parsed.is_finite():  # pragma: no cover - regex already excludes this
        raise _invalid(f"{field_path} must be finite", field_path)
    return parsed


def quantize_12(value: Decimal, field_path: str = "value") -> Decimal:
    """Quantise one value to exactly twelve fractional places, half-even."""

    require_decimal(value, field_path)
    try:
        with localcontext(decimal_context()):
            return value.quantize(DECIMAL_QUANTUM)
    except InvalidOperation as exc:
        raise _invalid(
            f"{field_path} is outside the representable quantisation range",
            field_path,
        ) from exc


def format_12(value: Decimal, field_path: str = "value") -> str:
    """Render one positive effect as a fixed twelve-fractional-digit string."""

    return format(quantize_12(value, field_path), "f")


def format_policy_limit_12(value: Decimal, field_path: str = "policy_limit") -> str:
    """Render a finite *nonnegative* policy threshold to exactly 12 places.

    Policy bounds may legitimately be zero. Measured effects, samples and
    denominators remain strict-positive through :func:`require_decimal` and
    :func:`format_12`; this formatter is only for frozen threshold display.
    """

    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise _invalid(
            f"{field_path} must be a finite nonnegative Decimal", field_path
        )
    try:
        with localcontext(decimal_context()):
            rounded = value.quantize(DECIMAL_QUANTUM)
    except InvalidOperation as exc:
        raise _invalid(
            f"{field_path} is outside the representable quantisation range",
            field_path,
        ) from exc
    return format(rounded, "f")


# ---------------------------------------------------------------------------
# Slot / block / exclusion arithmetic
# ---------------------------------------------------------------------------


def _require_sequence(values: object, field_path: str) -> Sequence[Any]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid(f"{field_path} must be a sequence", field_path)
    if not values:
        raise _invalid(f"{field_path} must not be empty", field_path)
    return values


def slot_median(values: Sequence[int]) -> Decimal:
    """Return the exact median of one slot's positive integer samples."""

    cleaned: list[int] = []
    for index, value in enumerate(_require_sequence(values, "samples")):
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid(f"samples[{index}] must be an integer", f"samples[{index}]")
        if value <= 0:
            raise _invalid(f"samples[{index}] must be positive", f"samples[{index}]")
        cleaned.append(value)
    cleaned.sort()
    middle = len(cleaned) // 2
    if len(cleaned) % 2 == 1:
        return Decimal(cleaned[middle])
    with localcontext(decimal_context()):
        return (Decimal(cleaned[middle - 1]) + Decimal(cleaned[middle])) / Decimal(2)


def median_of(values: Sequence[Decimal]) -> Decimal:
    """Return the exact median of non-empty positive decimals."""

    ordered = sorted(
        require_decimal(value, f"values[{index}]")
        for index, value in enumerate(_require_sequence(values, "values"))
    )
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    with localcontext(decimal_context()):
        return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def mean_of(values: Sequence[Decimal]) -> Decimal:
    """Return the arithmetic mean of non-empty positive decimals."""

    total = Decimal(0)
    with localcontext(decimal_context()):
        for index, value in enumerate(_require_sequence(values, "values")):
            total += require_decimal(value, f"values[{index}]")
        return total / Decimal(len(values))


def within_arm_spread(slot_medians: Sequence[Decimal]) -> Decimal:
    """Return ``max(slot medians) / min(slot medians)`` at precision 50."""

    ordered = [
        require_decimal(value, f"slot_medians[{index}]")
        for index, value in enumerate(_require_sequence(slot_medians, "slot_medians"))
    ]
    with localcontext(decimal_context()):
        return max(ordered) / min(ordered)


def raw_ratio(candidate_value: Decimal, baseline_value: Decimal) -> Decimal:
    """Return ``candidate / baseline`` exactly (positive operands only)."""

    require_decimal(candidate_value, "candidate_value")
    require_decimal(baseline_value, "baseline_value")
    with localcontext(decimal_context()):
        return candidate_value / baseline_value


def normalized_effect(
    candidate_value: Decimal, baseline_value: Decimal, direction: str
) -> Decimal:
    """Return the direction-aware effect; a smaller value is always better."""

    if direction not in DIRECTIONS:
        raise _invalid(
            f"direction must be one of {sorted(DIRECTIONS)}", "direction"
        )
    if direction == "lower-is-better":
        return raw_ratio(candidate_value, baseline_value)
    return raw_ratio(baseline_value, candidate_value)


def _validated_rows(
    rows: Sequence[tuple[int, Decimal, Decimal]]
) -> list[tuple[int, Decimal, Decimal]]:
    validated: list[tuple[int, Decimal, Decimal]] = []
    for index, row in enumerate(_require_sequence(rows, "block_rows")):
        field = f"block_rows[{index}]"
        if not isinstance(row, tuple) or len(row) != 3:
            raise _invalid(
                "each block row must be a (block, baseline, candidate) tuple", field
            )
        block, baseline, candidate = row
        if isinstance(block, bool) or not isinstance(block, int) or block < 1:
            raise _invalid(f"{field}[0] must be a positive integer block id", field)
        require_decimal(baseline, f"{field}[1]")
        require_decimal(candidate, f"{field}[2]")
        validated.append((block, baseline, candidate))
    return validated


def compute_estimator(
    rows: Sequence[tuple[int, Decimal, Decimal]],
    direction: str,
    estimator_id: str,
) -> Decimal:
    """Apply one explicitly named frozen estimator to paired block rows."""

    if estimator_id not in ESTIMATORS:
        raise _invalid(
            f"estimator_id must be one of {sorted(ESTIMATORS)}", "estimator_id"
        )
    validated = _validated_rows(rows)
    if estimator_id == ESTIMATOR_MEDIAN_PAIRED_RATIOS:
        return median_of(
            [normalized_effect(candidate, baseline, direction)
             for _block, baseline, candidate in validated]
        )
    baseline_median = median_of([row[1] for row in validated])
    candidate_median = median_of([row[2] for row in validated])
    return normalized_effect(candidate_median, baseline_median, direction)


def geometric_mean(values: Sequence[Decimal]) -> Decimal:
    """Return ``exp(sum(ln(r)) / N)`` at precision 50 for positive effects."""

    with localcontext(decimal_context()):
        total = Decimal(0)
        for index, value in enumerate(_require_sequence(values, "values")):
            total += require_decimal(value, f"values[{index}]").ln()
        return (total / Decimal(len(values))).exp()


def worst_campaign_gm(campaign_gms: Sequence[Decimal]) -> Decimal:
    """Return ``max(GM)``; a lower normalised effect always favours improvement."""

    if not campaign_gms:
        raise _invalid("at least one campaign GM is required", "campaign_gms")
    return max(
        require_decimal(value, f"campaign_gms[{index}]")
        for index, value in enumerate(campaign_gms)
    )


def relative_delta(first: Decimal, second: Decimal) -> Decimal:
    """Return ``|a-b| / min(a,b)`` at precision 50."""

    require_decimal(first, "first")
    require_decimal(second, "second")
    with localcontext(decimal_context()):
        return abs(first - second) / min(first, second)


def sign_of(value: Decimal) -> int:
    """Return the parity comparison of one effect against 1.

    This is **only** an individual effect/parity comparator. It must never be
    used to compare two candidates: pair order is relative magnitude, supplied
    by :func:`compare_candidate_order`.
    """

    if not isinstance(value, Decimal) or not value.is_finite():
        raise _invalid("value must be a finite Decimal", "value")
    if value > 1:
        return 1
    if value < 1:
        return -1
    return 0


def compare_candidate_order(first: Decimal, second: Decimal) -> int:
    """Return -1, 0 or +1 from the ordering of two positive candidate effects."""

    require_decimal(first, "first")
    require_decimal(second, "second")
    return (first > second) - (first < second)


# ---------------------------------------------------------------------------
# Independent statistics model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockEffectStatistics:
    """One block's normalised and raw candidate/baseline effects."""

    block: int
    normalized_effect: Decimal
    raw_candidate_over_baseline: Decimal


@dataclass(frozen=True)
class LedgerRowStatistics:
    """One symmetric whole-block exclusion decision."""

    block: int
    status: str
    reason: str
    trigger_arms: tuple[str, ...]
    arm_spreads: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class CandidateStatistics:
    """Independent statistics for one candidate in one campaign/lane."""

    candidate_arm_id: str
    raw_point: Decimal
    retained_point: Decimal | None
    status: str
    raw_effects: tuple[BlockEffectStatistics, ...]
    retained_effects: tuple[BlockEffectStatistics, ...]
    retained_rows: tuple[tuple[int, Decimal, Decimal], ...]


@dataclass(frozen=True)
class LaneStatistics:
    """Independent statistics for one campaign/lane."""

    lane_id: str
    blocks_total: int
    ledger: tuple[LedgerRowStatistics, ...]
    retained_blocks: tuple[int, ...]
    excluded_blocks: tuple[int, ...]
    candidates: tuple[CandidateStatistics, ...]


@dataclass(frozen=True)
class CampaignStatistics:
    """Independent statistics for one treatment campaign."""

    campaign_index: int
    lanes: tuple[LaneStatistics, ...]


class IntervalLike(Protocol):
    """Minimal read-only view of an independently computed bootstrap interval."""

    low: Decimal
    high: Decimal
    stream_digest: str


def _slot_positions(
    slots: Sequence[ScheduleSlot], blocks_total: int, arms: Sequence[str]
) -> dict[int, dict[str, tuple[int, ...]]]:
    if not slots:
        raise _identity("the compiled schedule has no slots", "schedule")
    board: dict[int, dict[str, list[int]]] = {}
    seen: set[tuple[int, int]] = set()
    for slot in slots:
        key = (slot.block, slot.position)
        if key in seen:
            raise _identity("the compiled schedule repeats a block/position", "schedule")
        seen.add(key)
        if slot.block < 1 or slot.block > blocks_total:
            raise _identity("a schedule slot names a block outside the schedule", "schedule")
        board.setdefault(slot.block, {}).setdefault(slot.arm_id, []).append(
            slot.position
        )

    widths: set[int] = set()
    for block in range(1, blocks_total + 1):
        if block not in board:
            raise _identity(f"the schedule omits block {block}", "schedule")
        if tuple(sorted(board[block])) != tuple(sorted(arms)):
            raise _identity(
                f"block {block} does not declare the experiment arm set", "schedule"
            )
        positions = sorted(
            position for values in board[block].values() for position in values
        )
        if positions != list(range(1, len(positions) + 1)):
            raise _identity(
                f"block {block} positions must be exactly 1..N", "schedule"
            )
        widths.add(len(positions))
    if len(widths) != 1 or len(seen) != blocks_total * widths.pop():
        raise _identity("the schedule does not form a complete block grid", "schedule")
    return {
        block: {
            arm_id: tuple(sorted(positions)) for arm_id, positions in arms_map.items()
        }
        for block, arms_map in board.items()
    }


def compute_statistics(
    *,
    campaign_indices: Sequence[int],
    lane_ids: Sequence[str],
    slots: Sequence[ScheduleSlot],
    arms: Sequence[str],
    samples: Mapping[tuple[int, str, int, str, int], Sequence[int]],
    baseline_arm_id: str,
    candidate_ids: Sequence[str],
    direction: str,
    caps: Mapping[str, Decimal],
    blocks_total: int,
    minimum_retained: int,
    estimator_id: str,
) -> tuple[CampaignStatistics, ...]:
    """Reconstruct every raw and retained statistic from the sealed samples."""

    if direction not in DIRECTIONS:
        raise _invalid(
            f"direction must be one of {sorted(DIRECTIONS)}", "direction"
        )
    if estimator_id not in ESTIMATORS:
        raise _invalid(
            f"estimator_id must be one of {sorted(ESTIMATORS)}", "estimator_id"
        )
    if baseline_arm_id not in arms:
        raise _identity("the baseline must be a declared experiment arm", "baseline_arm_id")
    if tuple(candidate_ids) != tuple(
        arm_id for arm_id in arms if arm_id != baseline_arm_id
    ):
        raise _identity(
            "candidate order must be the declared non-baseline arm order",
            "candidate_ids",
        )
    if blocks_total < 1:
        raise _identity("the schedule must declare at least one block", "blocks_total")
    if minimum_retained < 1:
        raise _identity("minimum_retained must be positive", "minimum_retained")
    for lane_id in lane_ids:
        if lane_id not in caps:
            raise _identity(
                f"the analysis profile declares no cap for lane {lane_id!r}",
                "exclusion.per_lane_caps",
            )
        require_decimal(caps[lane_id], f"caps[{lane_id!r}]")

    positions = _slot_positions(slots, blocks_total, arms)
    arm_order = tuple(sorted(arms))
    campaigns: list[CampaignStatistics] = []
    for campaign_index in campaign_indices:
        lanes: list[LaneStatistics] = []
        for lane_id in lane_ids:
            block_medians: dict[int, dict[str, list[Decimal]]] = {}
            block_values: dict[int, dict[str, Decimal]] = {}
            for block in range(1, blocks_total + 1):
                per_arm: dict[str, list[Decimal]] = {}
                for arm_id in arms:
                    medians: list[Decimal] = []
                    for position in positions[block][arm_id]:
                        key = (campaign_index, lane_id, block, arm_id, position)
                        vector = samples.get(key)
                        if vector is None:
                            raise _identity(
                                "the sealed sample inventory is incomplete for "
                                f"{key!r}",
                                "samples",
                            )
                        medians.append(slot_median(vector))
                    per_arm[arm_id] = medians
                block_medians[block] = per_arm
                block_values[block] = {
                    arm_id: mean_of(per_arm[arm_id]) for arm_id in arms
                }

            cap = caps[lane_id]
            ledger: list[LedgerRowStatistics] = []
            retained: list[int] = []
            excluded: list[int] = []
            for block in range(1, blocks_total + 1):
                spreads = tuple(
                    (arm_id, within_arm_spread(block_medians[block][arm_id]))
                    for arm_id in arm_order
                )
                triggers = tuple(
                    arm_id for arm_id, spread in spreads if spread > cap
                )
                if triggers:
                    excluded.append(block)
                    ledger.append(
                        LedgerRowStatistics(
                            block=block,
                            status="excluded",
                            reason="within-arm-spread",
                            trigger_arms=triggers,
                            arm_spreads=spreads,
                        )
                    )
                else:
                    retained.append(block)
                    ledger.append(
                        LedgerRowStatistics(
                            block=block,
                            status="retained",
                            reason="none",
                            trigger_arms=(),
                            arm_spreads=spreads,
                        )
                    )

            candidates: list[CandidateStatistics] = []
            for candidate_id in candidate_ids:
                rows_all = [
                    (
                        block,
                        block_values[block][baseline_arm_id],
                        block_values[block][candidate_id],
                    )
                    for block in range(1, blocks_total + 1)
                ]
                raw_effects = tuple(
                    BlockEffectStatistics(
                        block=block,
                        normalized_effect=normalized_effect(
                            candidate_value, baseline_value, direction
                        ),
                        raw_candidate_over_baseline=raw_ratio(
                            candidate_value, baseline_value
                        ),
                    )
                    for block, baseline_value, candidate_value in rows_all
                )
                raw_point = quantize_12(
                    compute_estimator(rows_all, direction, estimator_id)
                )
                retained_rows = tuple(
                    row for row in rows_all if row[0] in retained
                )
                if len(retained_rows) >= minimum_retained:
                    candidates.append(
                        CandidateStatistics(
                            candidate_arm_id=candidate_id,
                            raw_point=raw_point,
                            retained_point=quantize_12(
                                compute_estimator(
                                    retained_rows, direction, estimator_id
                                )
                            ),
                            status=LANE_STATUS_ANALYZED,
                            raw_effects=raw_effects,
                            retained_effects=tuple(
                                effect
                                for effect in raw_effects
                                if effect.block in retained
                            ),
                            retained_rows=retained_rows,
                        )
                    )
                else:
                    candidates.append(
                        CandidateStatistics(
                            candidate_arm_id=candidate_id,
                            raw_point=raw_point,
                            retained_point=None,
                            status=LANE_STATUS_INSUFFICIENT,
                            raw_effects=raw_effects,
                            retained_effects=(),
                            retained_rows=retained_rows,
                        )
                    )
            lanes.append(
                LaneStatistics(
                    lane_id=lane_id,
                    blocks_total=blocks_total,
                    ledger=tuple(ledger),
                    retained_blocks=tuple(retained),
                    excluded_blocks=tuple(excluded),
                    candidates=tuple(candidates),
                )
            )
        campaigns.append(
            CampaignStatistics(campaign_index=campaign_index, lanes=tuple(lanes))
        )
    return tuple(campaigns)


# ---------------------------------------------------------------------------
# Document reconstruction and statistics comparison
# ---------------------------------------------------------------------------


def build_analysis_document(
    *,
    experiment_id: str,
    run_id: str,
    source_seal_digest: str,
    freeze_digest: str,
    protocol_digest: str,
    analysis_profile_digest: str,
    analysis_id: str,
    analysis_version: int,
    estimator_id: str,
    algorithm_id: str,
    confidence_basis_points: int,
    resamples: int,
    seed: int,
    baseline_arm_id: str,
    candidate_ids: Sequence[str],
    lane_ids: Sequence[str],
    direction: str,
    campaigns: Sequence[CampaignStatistics],
    intervals: Mapping[tuple[int, str, str], IntervalLike],
) -> dict[str, Any]:
    """Assemble the complete expected ``synthetic-analysis-result`` document."""

    campaign_documents: list[dict[str, Any]] = []
    for campaign in campaigns:
        lane_documents: list[dict[str, Any]] = []
        for lane in campaign.lanes:
            candidate_documents: list[dict[str, Any]] = []
            for candidate in lane.candidates:
                retained_point: str | None
                ci_low: str | None
                ci_high: str | None
                stream_digest: str | None
                if candidate.retained_point is None:
                    retained_point = None
                    ci_low = None
                    ci_high = None
                    stream_digest = None
                else:
                    key = (
                        campaign.campaign_index,
                        lane.lane_id,
                        candidate.candidate_arm_id,
                    )
                    interval = intervals.get(key)
                    if interval is None:
                        raise _identity(
                            "the independent bootstrap produced no interval for "
                            f"{key!r}",
                            "bootstrap",
                        )
                    retained_point = format_12(
                        candidate.retained_point, "retained_point_effect"
                    )
                    ci_low = format_12(interval.low, "ci_low")
                    ci_high = format_12(interval.high, "ci_high")
                    stream_digest = interval.stream_digest
                candidate_documents.append(
                    {
                        "candidate_arm_id": candidate.candidate_arm_id,
                        "comparison_direction": direction,
                        "raw_point_effect": format_12(
                            candidate.raw_point, "raw_point_effect"
                        ),
                        "retained_point_effect": retained_point,
                        "ci_low": ci_low,
                        "ci_high": ci_high,
                        "bootstrap_stream_digest": stream_digest,
                        "status": candidate.status,
                        "raw_block_effects": [
                            _block_effect_document(effect)
                            for effect in candidate.raw_effects
                        ],
                        "retained_block_effects": [
                            _block_effect_document(effect)
                            for effect in candidate.retained_effects
                        ],
                    }
                )
            lane_documents.append(
                {
                    "lane_id": lane.lane_id,
                    "blocks_total": lane.blocks_total,
                    "retained_blocks": list(lane.retained_blocks),
                    "excluded_blocks": list(lane.excluded_blocks),
                    "exclusion_ledger": [
                        _ledger_row_document(row) for row in lane.ledger
                    ],
                    "candidates": candidate_documents,
                }
            )
        campaign_documents.append(
            {
                "campaign_index": campaign.campaign_index,
                "lanes": lane_documents,
            }
        )
    return {
        "kind": "synthetic-analysis-result",
        "schema_version": 1,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "status": "derived-synthetic",
        "source_seal_digest": source_seal_digest,
        "freeze_digest": freeze_digest,
        "protocol_digest": protocol_digest,
        "analysis_profile_digest": analysis_profile_digest,
        "analysis_id": analysis_id,
        "analysis_version": analysis_version,
        "estimator_id": estimator_id,
        "algorithm_id": algorithm_id,
        "confidence_basis_points": confidence_basis_points,
        "resamples": resamples,
        "seed": seed,
        "baseline_arm_id": baseline_arm_id,
        "candidate_ids": list(candidate_ids),
        "lane_ids": list(lane_ids),
        "campaigns": campaign_documents,
    }


def _block_effect_document(effect: BlockEffectStatistics) -> dict[str, Any]:
    return {
        "block": effect.block,
        "normalized_effect": format_12(
            effect.normalized_effect, "normalized_effect"
        ),
        "raw_candidate_over_baseline": format_12(
            effect.raw_candidate_over_baseline, "raw_candidate_over_baseline"
        ),
    }


def _ledger_row_document(row: LedgerRowStatistics) -> dict[str, Any]:
    return {
        "block": row.block,
        "status": row.status,
        "reason": row.reason,
        "trigger_arms": list(row.trigger_arms),
        "arm_spreads": [
            {"arm_id": arm_id, "spread": format_12(spread, "spread")}
            for arm_id, spread in row.arm_spreads
        ],
    }


def _expect(actual: object, expected: object, field_path: str) -> None:
    if type(actual) is not type(expected) or actual != expected:
        raise _identity(
            f"{field_path} does not match the independently derived value "
            f"(expected {expected!r}, found {actual!r})",
            field_path,
        )


def _expect_mapping(value: object, field_path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field_path} must be a JSON object", field_path)
    return value


def _expect_list(value: object, field_path: str) -> list[Any]:
    if not isinstance(value, list):
        raise _invalid(f"{field_path} must be an array", field_path)
    return value


def compare_statistics(
    analysis_document: Mapping[str, Any],
    campaigns: Sequence[CampaignStatistics],
) -> None:
    """Compare every non-bootstrap analysis field with the independent model."""

    supplied_campaigns = _expect_list(
        analysis_document.get("campaigns"), "campaigns"
    )
    _expect(len(supplied_campaigns), len(campaigns), "campaigns")
    for campaign_position, expected_campaign in enumerate(campaigns):
        campaign_field = f"campaigns[{campaign_position}]"
        supplied_campaign = _expect_mapping(
            supplied_campaigns[campaign_position], campaign_field
        )
        _expect(
            supplied_campaign.get("campaign_index"),
            expected_campaign.campaign_index,
            f"{campaign_field}.campaign_index",
        )
        supplied_lanes = _expect_list(
            supplied_campaign.get("lanes"), f"{campaign_field}.lanes"
        )
        _expect(len(supplied_lanes), len(expected_campaign.lanes), f"{campaign_field}.lanes")
        for lane_position, expected_lane in enumerate(expected_campaign.lanes):
            lane_field = f"{campaign_field}.lanes[{lane_position}]"
            supplied_lane = _expect_mapping(supplied_lanes[lane_position], lane_field)
            _expect(
                supplied_lane.get("lane_id"),
                expected_lane.lane_id,
                f"{lane_field}.lane_id",
            )
            _expect(
                supplied_lane.get("blocks_total"),
                expected_lane.blocks_total,
                f"{lane_field}.blocks_total",
            )
            _expect(
                supplied_lane.get("retained_blocks"),
                list(expected_lane.retained_blocks),
                f"{lane_field}.retained_blocks",
            )
            _expect(
                supplied_lane.get("excluded_blocks"),
                list(expected_lane.excluded_blocks),
                f"{lane_field}.excluded_blocks",
            )
            supplied_ledger = _expect_list(
                supplied_lane.get("exclusion_ledger"),
                f"{lane_field}.exclusion_ledger",
            )
            _expect(
                len(supplied_ledger),
                len(expected_lane.ledger),
                f"{lane_field}.exclusion_ledger",
            )
            for row_position, expected_row in enumerate(expected_lane.ledger):
                row_field = f"{lane_field}.exclusion_ledger[{row_position}]"
                supplied_row = _expect_mapping(
                    supplied_ledger[row_position], row_field
                )
                _expect(
                    supplied_row.get("block"),
                    expected_row.block,
                    f"{row_field}.block",
                )
                _expect(
                    supplied_row.get("status"),
                    expected_row.status,
                    f"{row_field}.status",
                )
                _expect(
                    supplied_row.get("reason"),
                    expected_row.reason,
                    f"{row_field}.reason",
                )
                _expect(
                    supplied_row.get("trigger_arms"),
                    list(expected_row.trigger_arms),
                    f"{row_field}.trigger_arms",
                )
                supplied_spreads = _expect_list(
                    supplied_row.get("arm_spreads"), f"{row_field}.arm_spreads"
                )
                _expect(
                    len(supplied_spreads),
                    len(expected_row.arm_spreads),
                    f"{row_field}.arm_spreads",
                )
                for spread_position, (arm_id, spread) in enumerate(
                    expected_row.arm_spreads
                ):
                    spread_field = f"{row_field}.arm_spreads[{spread_position}]"
                    supplied_spread = _expect_mapping(
                        supplied_spreads[spread_position], spread_field
                    )
                    _expect(
                        supplied_spread.get("arm_id"),
                        arm_id,
                        f"{spread_field}.arm_id",
                    )
                    _expect(
                        supplied_spread.get("spread"),
                        format_12(spread, "spread"),
                        f"{spread_field}.spread",
                    )

            supplied_candidates = _expect_list(
                supplied_lane.get("candidates"), f"{lane_field}.candidates"
            )
            _expect(
                len(supplied_candidates),
                len(expected_lane.candidates),
                f"{lane_field}.candidates",
            )
            for candidate_position, expected_candidate in enumerate(
                expected_lane.candidates
            ):
                candidate_field = f"{lane_field}.candidates[{candidate_position}]"
                supplied_candidate = _expect_mapping(
                    supplied_candidates[candidate_position], candidate_field
                )
                _expect(
                    supplied_candidate.get("candidate_arm_id"),
                    expected_candidate.candidate_arm_id,
                    f"{candidate_field}.candidate_arm_id",
                )
                _expect(
                    supplied_candidate.get("status"),
                    expected_candidate.status,
                    f"{candidate_field}.status",
                )
                _expect(
                    supplied_candidate.get("raw_point_effect"),
                    format_12(expected_candidate.raw_point, "raw_point_effect"),
                    f"{candidate_field}.raw_point_effect",
                )
                expected_retained = (
                    None
                    if expected_candidate.retained_point is None
                    else format_12(
                        expected_candidate.retained_point, "retained_point_effect"
                    )
                )
                _expect(
                    supplied_candidate.get("retained_point_effect"),
                    expected_retained,
                    f"{candidate_field}.retained_point_effect",
                )
                _compare_block_effects(
                    supplied_candidate.get("raw_block_effects"),
                    expected_candidate.raw_effects,
                    f"{candidate_field}.raw_block_effects",
                )
                _compare_block_effects(
                    supplied_candidate.get("retained_block_effects"),
                    expected_candidate.retained_effects,
                    f"{candidate_field}.retained_block_effects",
                )


def _compare_block_effects(
    supplied: object,
    expected: Sequence[BlockEffectStatistics],
    field_path: str,
) -> None:
    entries = _expect_list(supplied, field_path)
    _expect(len(entries), len(expected), field_path)
    for position, effect in enumerate(expected):
        entry_field = f"{field_path}[{position}]"
        entry = _expect_mapping(entries[position], entry_field)
        _expect(entry.get("block"), effect.block, f"{entry_field}.block")
        _expect(
            entry.get("normalized_effect"),
            format_12(effect.normalized_effect, "normalized_effect"),
            f"{entry_field}.normalized_effect",
        )
        _expect(
            entry.get("raw_candidate_over_baseline"),
            format_12(effect.raw_candidate_over_baseline, "raw_candidate_over_baseline"),
            f"{entry_field}.raw_candidate_over_baseline",
        )


__all__ = [
    "BlockEffectStatistics",
    "CampaignStatistics",
    "CandidateStatistics",
    "IntervalLike",
    "LaneStatistics",
    "LedgerRowStatistics",
    "build_analysis_document",
    "compare_statistics",
    "compute_estimator",
    "compute_statistics",
    "compare_candidate_order",
    "decimal_context",
    "format_12",
    "format_policy_limit_12",
    "geometric_mean",
    "mean_of",
    "median_of",
    "normalized_effect",
    "parse_effect_literal",
    "quantize_12",
    "raw_ratio",
    "relative_delta",
    "require_decimal",
    "sign_of",
    "slot_median",
    "within_arm_spread",
    "worst_campaign_gm",
]
