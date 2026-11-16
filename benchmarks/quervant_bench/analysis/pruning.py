"""Symmetric `within-arm-spread-v1` exclusions and the retained-block ledger.

The rule is deliberately narrow and outcome-blind:

* for every scheduled treatment campaign, lane and block, compute each arm's
  within-block spread ``max(slot_median) / min(slot_median)`` exactly;
* exclude the **whole lane/block for every arm** if and only if **any** arm's
  spread is *strictly greater* than that lane's frozen cap;
* never prune a single arm, never look at the candidate/baseline effect, a
  confidence interval, memory usage or a desired winner, and never mutate the raw
  evidence.

A single-slot arm has spread exactly ``1``. Missing values are structural errors,
not contamination.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext

from ..config.errors import BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BenchError
from ..config.identity import validate_semantic_id
from .contracts import ExclusionLedger, ExclusionLedgerRow, decimal_context
from .profiles import AnalysisProfile


def _fail(message: str, field_path: str | None = None) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _invalid(message: str, field_path: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


def within_arm_spread(slot_medians: Sequence[Decimal]) -> Decimal:
    """Return ``max/min`` of one arm's slot medians at precision 50."""

    if isinstance(slot_medians, (str, bytes)) or not isinstance(slot_medians, Sequence):
        raise _invalid("slot medians must be a sequence", "slot_medians")
    if not slot_medians:
        raise _invalid("an arm must declare at least one slot median", "slot_medians")
    values: list[Decimal] = []
    for index, value in enumerate(slot_medians):
        if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
            raise _invalid(
                f"slot_medians[{index}] must be a finite positive Decimal",
                f"slot_medians[{index}]",
            )
        values.append(value)
    with localcontext(decimal_context()):
        return max(values) / min(values)


def apply_lane_block_exclusions(
    block_slot_medians: Mapping[int, Mapping[str, Sequence[Decimal]]],
    analysis_profile: AnalysisProfile,
    lane_id: str,
) -> ExclusionLedger:
    """Return the complete signed exclusion ledger for one campaign/lane."""

    if not isinstance(analysis_profile, AnalysisProfile):
        raise _fail("a validated AnalysisProfile is required", "analysis_profile")
    resolved_lane = validate_semantic_id(lane_id, "lane_id")
    if not isinstance(block_slot_medians, Mapping):
        raise _invalid("block slot medians must be a mapping", "block_slot_medians")
    if not block_slot_medians:
        raise _invalid("a lane must declare at least one block", "block_slot_medians")

    block_ids = sorted(block_slot_medians)
    if block_ids != list(range(1, len(block_ids) + 1)):
        raise _fail(
            "blocks must be exactly 1..N in the declared schedule",
            "block_slot_medians",
        )

    arms: tuple[str, ...] | None = None
    for block in block_ids:
        arms_for_block = block_slot_medians[block]
        if not isinstance(arms_for_block, Mapping) or not arms_for_block:
            raise _invalid(
                f"block {block} must map at least one arm to its slot medians",
                f"block_slot_medians[{block}]",
            )
        resolved_arms = tuple(
            sorted(validate_semantic_id(arm_id, f"block_slot_medians[{block}].arm_id")
                   for arm_id in arms_for_block)
        )
        if arms is None:
            arms = resolved_arms
        elif resolved_arms != arms:
            raise _fail(
                "every block must declare the same arms; a missing arm is a "
                "structural error, not an exclusion",
                f"block_slot_medians[{block}]",
            )

    cap = analysis_profile.exclusion.cap_for(resolved_lane)
    rows: list[ExclusionLedgerRow] = []
    retained: list[int] = []
    excluded: list[int] = []
    for block in block_ids:
        spreads = tuple(
            (arm_id, within_arm_spread(block_slot_medians[block][arm_id]))
            for arm_id in arms or ()
        )
        trigger_arms = tuple(
            arm_id for arm_id, spread in spreads if spread > cap
        )
        if trigger_arms:
            excluded.append(block)
            rows.append(
                ExclusionLedgerRow(
                    block=block,
                    status="excluded",
                    reason="within-arm-spread",
                    trigger_arms=trigger_arms,
                    arm_spreads=spreads,
                )
            )
        else:
            retained.append(block)
            rows.append(
                ExclusionLedgerRow(
                    block=block,
                    status="retained",
                    reason="none",
                    trigger_arms=(),
                    arm_spreads=spreads,
                )
            )
    return ExclusionLedger(
        lane_id=resolved_lane,
        rows=tuple(rows),
        retained_blocks=tuple(retained),
        excluded_blocks=tuple(excluded),
    )


def arm_block_values(
    block_slot_medians: Mapping[int, Mapping[str, Sequence[Decimal]]],
) -> dict[int, dict[str, Decimal]]:
    """Return each arm's block value (mean of its declared slot medians)."""

    from .arithmetic import arm_block_value

    values: dict[int, dict[str, Decimal]] = {}
    for block in sorted(block_slot_medians):
        values[block] = {
            arm_id: arm_block_value(block_slot_medians[block][arm_id])
            for arm_id in sorted(block_slot_medians[block])
        }
    return values


__all__ = [
    "ExclusionLedger",
    "ExclusionLedgerRow",
    "apply_lane_block_exclusions",
    "arm_block_values",
    "within_arm_spread",
]
