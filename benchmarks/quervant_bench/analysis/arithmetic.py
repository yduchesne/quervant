"""Pure BM-04 arithmetic: slot medians, block values, effect ratios, GM.

Everything here is a deterministic function of its arguments. There is no I/O, no
randomness, no policy decision and no floating-point arithmetic: the only numeric
type is :class:`decimal.Decimal`, always evaluated inside a local precision-50,
round-half-even context so that an ambient global context can never change a
result.

Two **non-equivalent** estimators live here and are never interchangeable:

* ``median-paired-ratios-v1`` — the median of the per-block normalised effects;
* ``ratio-of-arm-medians-v1`` — the ratio of the per-arm medians over the same
  selected blocks. It is a pure comparison calculator for historical replay, not
  the new default.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext
from typing import Any

from ..config.errors import BM_SCHEMA_INVALID, BenchError
from .contracts import (
    DIRECTION_HIGHER_IS_BETTER,
    DIRECTION_LOWER_IS_BETTER,
    DIRECTIONS,
    ESTIMATOR_MEDIAN_PAIRED_RATIOS,
    ESTIMATOR_RATIO_OF_ARM_MEDIANS,
    decimal_context,
    require_finite_positive,
)


def _invalid(message: str, field_path: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


def _require_direction(direction: object) -> str:
    if not isinstance(direction, str) or direction not in DIRECTIONS:
        raise _invalid(
            f"direction must be one of {sorted(DIRECTIONS)}", "direction"
        )
    return direction


def slot_median(values: Sequence[int]) -> Decimal:
    """Return the exact statistical median of one slot's positive integer samples.

    Odd counts yield the middle value; even counts yield the exact Decimal average
    of the two middle values (never an integer floor division). Warmup values are
    never observations and must not be passed here.
    """

    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid("slot samples must be a sequence of integers", "samples")
    if not values:
        raise _invalid("a slot must contain at least one sample", "samples")
    cleaned: list[int] = []
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid(
                f"samples[{index}] must be an integer", f"samples[{index}]"
            )
        if value <= 0:
            raise _invalid(
                f"samples[{index}] must be positive", f"samples[{index}]"
            )
        cleaned.append(value)
    ordered = sorted(cleaned)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return Decimal(ordered[middle])
    with localcontext(decimal_context()):
        return (Decimal(ordered[middle - 1]) + Decimal(ordered[middle])) / Decimal(2)


def arm_block_value(slot_medians: Sequence[Decimal]) -> Decimal:
    """Return the arithmetic mean of one arm's declared slot medians in a block."""

    if isinstance(slot_medians, (str, bytes)) or not isinstance(slot_medians, Sequence):
        raise _invalid("slot medians must be a sequence", "slot_medians")
    if not slot_medians:
        raise _invalid("a block must contain at least one slot median", "slot_medians")
    total = Decimal(0)
    with localcontext(decimal_context()):
        for index, value in enumerate(slot_medians):
            total += require_finite_positive(value, f"slot_medians[{index}]")
        return total / Decimal(len(slot_medians))


def median(values: Sequence[Decimal]) -> Decimal:
    """Return the exact median of a non-empty sequence of decimals."""

    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid("values must be a sequence", "values")
    if not values:
        raise _invalid("median requires at least one value", "values")
    ordered = sorted(require_finite_positive(value, "values[]") for value in values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    with localcontext(decimal_context()):
        return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def raw_ratio(candidate_value: Decimal, baseline_value: Decimal) -> Decimal:
    """Return ``T(candidate) / T(baseline)`` exactly, rejecting a zero denominator."""

    require_finite_positive(candidate_value, "candidate_value")
    require_finite_positive(baseline_value, "baseline_value")
    with localcontext(decimal_context()):
        return candidate_value / baseline_value


def normalized_effect(
    candidate_value: Decimal, baseline_value: Decimal, direction: str
) -> Decimal:
    """Return the direction-aware effect; a smaller value is always better.

    ``lower-is-better`` yields ``candidate / baseline``;
    ``higher-is-better`` yields ``baseline / candidate``. Candidate identity is
    never swapped to invert a direction.
    """

    resolved = _require_direction(direction)
    if resolved == DIRECTION_LOWER_IS_BETTER:
        return raw_ratio(candidate_value, baseline_value)
    return raw_ratio(baseline_value, candidate_value)


def require_block_rows(
    block_rows: Sequence[tuple[int, Decimal, Decimal]],
) -> tuple[tuple[int, Decimal, Decimal], ...]:
    """Validate ascending unique block rows of positive ``(baseline, candidate)``."""

    if isinstance(block_rows, (str, bytes)) or not isinstance(block_rows, Sequence):
        raise _invalid("block rows must be a sequence", "block_rows")
    if not block_rows:
        raise _invalid("block rows must not be empty", "block_rows")
    rows: list[tuple[int, Decimal, Decimal]] = []
    previous_block = 0
    for index, row in enumerate(block_rows):
        field = f"block_rows[{index}]"
        if not isinstance(row, tuple) or len(row) != 3:
            raise _invalid("each block row must be a (block, baseline, candidate) tuple", field)
        block, baseline, candidate = row
        if isinstance(block, bool) or not isinstance(block, int):
            raise _invalid(f"{field}[0] must be an integer block id", field)
        if block <= previous_block:
            raise _invalid(
                "block rows must be strictly ascending by block id", field
            )
        previous_block = block
        require_finite_positive(baseline, f"{field}[1]")
        require_finite_positive(candidate, f"{field}[2]")
        rows.append((block, baseline, candidate))
    return tuple(rows)


def validate_block_row(row: object, field_path: str) -> tuple[int, Decimal, Decimal]:
    """Validate one ``(block, baseline, candidate)`` row without ordering rules."""

    if not isinstance(row, tuple) or len(row) != 3:
        raise _invalid(
            "each block row must be a (block, baseline, candidate) tuple", field_path
        )
    block, baseline, candidate = row
    if isinstance(block, bool) or not isinstance(block, int):
        raise _invalid(f"{field_path}[0] must be an integer block id", field_path)
    require_finite_positive(baseline, f"{field_path}[1]")
    require_finite_positive(candidate, f"{field_path}[2]")
    return block, baseline, candidate


def paired_block_effects(
    block_rows: Sequence[tuple[int, Decimal, Decimal]], direction: str
) -> tuple[Decimal, ...]:
    """Return the direction-aware effects of the given rows.

    Row order is irrelevant to the median; strict ascending unique input is
    enforced separately by :func:`require_block_rows` at each API boundary. This
    keeps a bootstrap replicate (which legitimately repeats block ids) evaluable by
    the *same* estimator.
    """

    resolved = _require_direction(direction)
    if isinstance(block_rows, (str, bytes)) or not isinstance(block_rows, Sequence):
        raise _invalid("block rows must be a sequence", "block_rows")
    if not block_rows:
        raise _invalid("block rows must not be empty", "block_rows")
    effects: list[Decimal] = []
    for index, row in enumerate(block_rows):
        _block, baseline, candidate = validate_block_row(row, f"block_rows[{index}]")
        effects.append(normalized_effect(candidate, baseline, resolved))
    return tuple(effects)


def median_paired_ratios(
    block_rows: Sequence[tuple[int, Decimal, Decimal]], direction: str
) -> Decimal:
    """Return the ``median-paired-ratios-v1`` estimate (unquantised)."""

    return median(paired_block_effects(block_rows, direction))


def ratio_of_arm_medians(
    block_rows: Sequence[tuple[int, Decimal, Decimal]], direction: str
) -> Decimal:
    """Return the ``ratio-of-arm-medians-v1`` estimate (unquantised).

    The numerator and denominator are the medians of the **same** selected blocks,
    so this is deliberately not the median of the per-block ratios.
    """

    resolved = _require_direction(direction)
    if isinstance(block_rows, (str, bytes)) or not isinstance(block_rows, Sequence):
        raise _invalid("block rows must be a sequence", "block_rows")
    if not block_rows:
        raise _invalid("block rows must not be empty", "block_rows")
    validated = [
        validate_block_row(row, f"block_rows[{index}]")
        for index, row in enumerate(block_rows)
    ]
    baseline_median = median([row[1] for row in validated])
    candidate_median = median([row[2] for row in validated])
    return normalized_effect(candidate_median, baseline_median, resolved)


def compute_paired_effect(
    block_rows: Sequence[tuple[int, Decimal, Decimal]],
    direction: str,
    estimator_id: str = ESTIMATOR_MEDIAN_PAIRED_RATIOS,
) -> Decimal:
    """Dispatch to the explicitly named estimator; never an implicit default."""

    if estimator_id == ESTIMATOR_MEDIAN_PAIRED_RATIOS:
        return median_paired_ratios(block_rows, direction)
    if estimator_id == ESTIMATOR_RATIO_OF_ARM_MEDIANS:
        return ratio_of_arm_medians(block_rows, direction)
    raise _invalid(
        f"estimator_id must be one of "
        f"{sorted((ESTIMATOR_MEDIAN_PAIRED_RATIOS, ESTIMATOR_RATIO_OF_ARM_MEDIANS))}",
        "estimator_id",
    )


def geometric_mean(values: Sequence[Decimal]) -> Decimal:
    """Return ``exp(sum(ln(r_i)) / N)`` at precision 50 for positive effects."""

    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid("geometric-mean values must be a sequence", "values")
    if not values:
        raise _invalid("geometric mean requires at least one value", "values")
    with localcontext(decimal_context()):
        total = Decimal(0)
        for index, value in enumerate(values):
            total += require_finite_positive(value, f"values[{index}]").ln()
        return (total / Decimal(len(values))).exp()


def worst_campaign_gm(campaign_gms: Sequence[Decimal]) -> Decimal:
    """Return ``max(GM_campaign)``: lower normalised effects favour improvement."""

    if not campaign_gms:
        raise _invalid("at least one campaign GM is required", "campaign_gms")
    for index, value in enumerate(campaign_gms):
        require_finite_positive(value, f"campaign_gms[{index}]")
    return max(campaign_gms)


def relative_delta(first: Decimal, second: Decimal) -> Decimal:
    """Return ``|a-b| / min(a,b)`` for two positive values."""

    require_finite_positive(first, "first")
    require_finite_positive(second, "second")
    with localcontext(decimal_context()):
        return abs(first - second) / min(first, second)


def compare_operator(value: Decimal, limit: Decimal, operator: str) -> bool:
    """Evaluate a frozen comparison operator exactly; no tolerance is applied."""

    if operator == "lt":
        return value < limit
    if operator == "le":
        return value <= limit
    raise BenchError(
        BM_SCHEMA_INVALID,
        "ci_operator must be 'lt' or 'le'",
        field_path="ci_operator",
    )


def direction_of(value: Any) -> str:
    """Return the validated direction string (kept for callers that carry ``Any``)."""

    return _require_direction(value)


__all__ = [
    "DIRECTION_HIGHER_IS_BETTER",
    "DIRECTION_LOWER_IS_BETTER",
    "ESTIMATOR_MEDIAN_PAIRED_RATIOS",
    "ESTIMATOR_RATIO_OF_ARM_MEDIANS",
    "arm_block_value",
    "compare_operator",
    "compute_paired_effect",
    "direction_of",
    "geometric_mean",
    "median",
    "median_paired_ratios",
    "normalized_effect",
    "paired_block_effects",
    "ratio_of_arm_medians",
    "raw_ratio",
    "relative_delta",
    "require_block_rows",
    "slot_median",
    "validate_block_row",
    "worst_campaign_gm",
]
