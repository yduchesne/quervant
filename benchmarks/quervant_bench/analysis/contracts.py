"""Closed BM-04 records, numeric primitives and output-contract validators.

This module owns three things and nothing else:

* the exact decimal-literal grammar and the 12-place canonical rendering shared by
  every BM-04 document;
* the frozen intermediate records (exclusion ledger, block effects, candidate
  estimates, analysis and policy result documents);
* strict closed-field structural **and** identity validation of the two BM-04
  output documents. It deliberately does **not** recompute statistics: independent
  recomputation is BM-05's job.

No I/O, no clock, no process, no adapter, no Gate A-E receipt.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from ..config.contracts import ExperimentBundle, validate_origin_scope
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCHEMA_UNSUPPORTED,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id, validate_uuid4

# ---------------------------------------------------------------------------
# Frozen numeric constants
# ---------------------------------------------------------------------------

#: Working precision for every BM-04 decimal computation.
DECIMAL_PRECISION = 50
#: Final quantisation step; every serialised ratio/GM/CI has exactly 12 places.
DECIMAL_QUANTUM = Decimal("0.000000000001")
OUTPUT_DECIMAL_PLACES = 12
#: v1 fixes 95% confidence (250 basis points per tail).
CONFIDENCE_BASIS_POINTS = 9500
TAIL_BASIS_POINTS = (10_000 - CONFIDENCE_BASIS_POINTS) // 2
BASIS_POINTS_TOTAL = 10_000

#: Closed set of supported estimators.
ESTIMATOR_MEDIAN_PAIRED_RATIOS = "median-paired-ratios-v1"
ESTIMATOR_RATIO_OF_ARM_MEDIANS = "ratio-of-arm-medians-v1"
ESTIMATORS: frozenset[str] = frozenset(
    {ESTIMATOR_MEDIAN_PAIRED_RATIOS, ESTIMATOR_RATIO_OF_ARM_MEDIANS}
)

#: Closed set of metric directions (mirrors the BM-01 adapter envelope).
DIRECTION_LOWER_IS_BETTER = "lower-is-better"
DIRECTION_HIGHER_IS_BETTER = "higher-is-better"
DIRECTIONS: frozenset[str] = frozenset(
    {DIRECTION_LOWER_IS_BETTER, DIRECTION_HIGHER_IS_BETTER}
)

#: Analysis output vocabulary.
ANALYSIS_KIND = "synthetic-analysis-result"
POLICY_KIND = "synthetic-policy-decision"
DERIVED_STATUS = "derived-synthetic"
OUTPUT_SCHEMA_VERSION = 1
SYNTHETIC_ORIGIN = "synthetic"
SIMULATED_SCOPE = "simulated"

LANE_STATUS_ANALYZED = "analyzed"
LANE_STATUS_INSUFFICIENT = "inconclusive-insufficient-blocks"

#: Policy output vocabulary.
CANDIDATE_ELIGIBLE = "ELIGIBLE"
CANDIDATE_INELIGIBLE = "INELIGIBLE"
CANDIDATE_INCONCLUSIVE = "INCONCLUSIVE"
DECISION_SELECTED = "SELECTED_ELIGIBLE_SYNTHETIC"
DECISION_TIE_PREFERENCE = "TIE_PREFERENCE_NOT_PROVEN_FASTER"
DECISION_BASELINE_ONLY = "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE"
DECISION_INCONCLUSIVE = "INCONCLUSIVE"
DECISION_STATUSES: frozenset[str] = frozenset(
    {
        DECISION_SELECTED,
        DECISION_TIE_PREFERENCE,
        DECISION_BASELINE_ONLY,
        DECISION_INCONCLUSIVE,
    }
)

#: Canonical output byte budget per document.
MAX_OUTPUT_BYTES = 1_048_576
#: Hard budget on emitted analysis records for one derivation.
MAX_ANALYSIS_RECORDS = 10_000
#: Hard bootstrap draw budget across one complete derivation.
MAX_TOTAL_DRAWS = 2_000_000

_DECIMAL_LITERAL = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]{1,12})?$")


def _fail(message: str, field_path: str | None = None) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _schema(message: str, field_path: str | None = None) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


# ---------------------------------------------------------------------------
# Decimal primitives
# ---------------------------------------------------------------------------


def decimal_context() -> Any:
    """Return a fresh precision-50, round-half-even decimal context."""

    from decimal import Context, ROUND_HALF_EVEN

    return Context(prec=DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN)


def parse_decimal_literal(value: object, field_path: str) -> Decimal:
    """Parse one canonical decimal literal string; never accept a float or bool."""

    if not isinstance(value, str):
        raise _schema(f"{field_path} must be a decimal literal string", field_path)
    if _DECIMAL_LITERAL.fullmatch(value) is None:
        raise _schema(
            f"{field_path} must match ^(0|[1-9][0-9]*)(\\.[0-9]{{1,12}})?$",
            field_path,
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - regex already excludes this
        raise _schema(f"{field_path} is not a decimal", field_path) from exc
    if not parsed.is_finite():  # pragma: no cover - regex already excludes this
        raise _schema(f"{field_path} must be finite", field_path)
    return parsed


def require_finite_positive(value: object, field_path: str) -> Decimal:
    """Require a finite, strictly positive Decimal (never a bool or float)."""

    if not isinstance(value, Decimal):
        raise _schema(f"{field_path} must be a Decimal", field_path)
    if not value.is_finite():
        raise _schema(f"{field_path} must be finite", field_path)
    if value <= 0:
        raise _schema(f"{field_path} must be positive", field_path)
    return value


def quantize_effect(value: Decimal) -> Decimal:
    """Quantise one ratio/GM/CI value to exactly 12 fractional digits."""

    if not isinstance(value, Decimal):
        raise _schema("a quantised value must be a Decimal")
    if not value.is_finite():
        raise _schema("a quantised value must be finite")
    try:
        with localcontext(decimal_context()):
            return value.quantize(DECIMAL_QUANTUM)
    except InvalidOperation as exc:
        raise _schema("a quantised value is outside the representable range") from exc


def format_effect(value: Decimal) -> str:
    """Render one quantised value as a fixed 12-fractional-digit string."""

    return format(quantize_effect(value), "f")


def require_formatted_effect(value: object, field_path: str) -> Decimal:
    """Parse a serialised 12-place effect string and require exactness."""

    parsed = parse_decimal_literal(value, field_path)
    exponent = parsed.as_tuple().exponent
    if not isinstance(exponent, int) or exponent != -OUTPUT_DECIMAL_PLACES:
        raise _schema(
            f"{field_path} must carry exactly {OUTPUT_DECIMAL_PLACES} fractional digits",
            field_path,
        )
    return parsed


# ---------------------------------------------------------------------------
# Closed-record primitives
# ---------------------------------------------------------------------------


def require_mapping(value: object, field_path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _schema(f"{field_path} must be a JSON object", field_path)
    return value


def require_closed(
    value: object, field_path: str, expected: frozenset[str]
) -> Mapping[str, Any]:
    doc = require_mapping(value, field_path)
    if set(doc) != expected:
        raise _schema(
            f"{field_path} must use the exact closed field set {sorted(expected)}",
            field_path,
        )
    return doc


def require_list(value: object, field_path: str) -> list[Any]:
    if not isinstance(value, list):
        raise _schema(f"{field_path} must be an array", field_path)
    return value


def require_int(
    value: object, field_path: str, *, minimum: int = 0, maximum: int | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _schema(f"{field_path} must be an integer", field_path)
    if value < minimum:
        raise _schema(f"{field_path} must be >= {minimum}", field_path)
    if maximum is not None and value > maximum:
        raise _schema(f"{field_path} must be <= {maximum}", field_path)
    return value


def require_bool(value: object, field_path: str) -> bool:
    if not isinstance(value, bool):
        raise _schema(f"{field_path} must be a boolean", field_path)
    return value


def require_enum(value: object, field_path: str, allowed: Iterable[str]) -> str:
    options = frozenset(allowed)
    if not isinstance(value, str) or value not in options:
        raise _schema(
            f"{field_path} must be one of {sorted(options)}", field_path
        )
    return value


def require_synthetic_scope(origin: object, scope: object, field_path: str) -> tuple[str, str]:
    """Require the synthetic/simulated origin/scope pair and nothing else."""

    pair = validate_origin_scope(origin, scope)
    if pair != (SYNTHETIC_ORIGIN, SIMULATED_SCOPE):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "BM-04 analysis accepts synthetic/simulated evidence only",
            field_path=field_path,
        )
    return pair


def require_bounded_document(document: Mapping[str, Any], field_path: str) -> bytes:
    """Serialise a document canonically and enforce the 1 MiB output budget."""

    from ..config.codec import canonical_document_bytes

    payload = canonical_document_bytes(document)
    if len(payload) > MAX_OUTPUT_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{field_path} exceeds the {MAX_OUTPUT_BYTES}-byte canonical output budget",
            field_path=field_path,
        )
    return payload


# ---------------------------------------------------------------------------
# Intermediate records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExclusionLedgerRow:
    """One retained-or-excluded lane/block decision for every compared arm."""

    block: int
    status: str
    reason: str
    trigger_arms: tuple[str, ...]
    arm_spreads: tuple[tuple[str, Decimal], ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "block": self.block,
            "status": self.status,
            "reason": self.reason,
            "trigger_arms": list(self.trigger_arms),
            "arm_spreads": [
                {"arm_id": arm_id, "spread": format_effect(spread)}
                for arm_id, spread in self.arm_spreads
            ],
        }


@dataclass(frozen=True)
class ExclusionLedger:
    """The complete signed exclusion ledger for one campaign/lane."""

    lane_id: str
    rows: tuple[ExclusionLedgerRow, ...]
    retained_blocks: tuple[int, ...]
    excluded_blocks: tuple[int, ...]

    def to_document(self) -> list[dict[str, Any]]:
        return [row.to_document() for row in self.rows]


@dataclass(frozen=True)
class BlockEffect:
    """One block's direction-aware effect plus its raw candidate/baseline ratio."""

    block: int
    normalized_effect: Decimal
    raw_candidate_over_baseline: Decimal

    def to_document(self) -> dict[str, Any]:
        return {
            "block": self.block,
            "normalized_effect": format_effect(self.normalized_effect),
            "raw_candidate_over_baseline": format_effect(
                self.raw_candidate_over_baseline
            ),
        }


@dataclass(frozen=True)
class CandidateLaneEstimate:
    """One candidate's estimate for one campaign/lane comparison."""

    candidate_arm_id: str
    comparison_direction: str
    raw_point_effect: Decimal
    retained_point_effect: Decimal | None
    ci_low: Decimal | None
    ci_high: Decimal | None
    bootstrap_stream_digest: str | None
    status: str
    raw_block_effects: tuple[BlockEffect, ...]
    retained_block_effects: tuple[BlockEffect, ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "candidate_arm_id": self.candidate_arm_id,
            "comparison_direction": self.comparison_direction,
            "raw_point_effect": format_effect(self.raw_point_effect),
            "retained_point_effect": (
                None
                if self.retained_point_effect is None
                else format_effect(self.retained_point_effect)
            ),
            "ci_low": None if self.ci_low is None else format_effect(self.ci_low),
            "ci_high": None if self.ci_high is None else format_effect(self.ci_high),
            "bootstrap_stream_digest": self.bootstrap_stream_digest,
            "status": self.status,
            "raw_block_effects": [item.to_document() for item in self.raw_block_effects],
            "retained_block_effects": [
                item.to_document() for item in self.retained_block_effects
            ],
        }


@dataclass(frozen=True)
class BootstrapInterval:
    """One deterministic paired-block bootstrap interval.

    ``stream_digest`` is the identity of the derived SHA-256 sampling stream. It
    is a method identity, **not** a source authentication token.
    """

    low: Decimal
    high: Decimal
    seed: int
    resamples: int
    algorithm_id: str
    estimator_id: str
    confidence_basis_points: int
    paired_block_count: int
    stream_digest: str

    def to_document(self) -> dict[str, Any]:
        return {
            "low": format_effect(self.low),
            "high": format_effect(self.high),
            "seed": self.seed,
            "resamples": self.resamples,
            "algorithm_id": self.algorithm_id,
            "estimator_id": self.estimator_id,
            "confidence_basis_points": self.confidence_basis_points,
            "paired_block_count": self.paired_block_count,
            "stream_digest": self.stream_digest,
        }


@dataclass(frozen=True)
class AnalysisLaneRow:
    """One campaign's per-lane analysis row."""

    lane_id: str
    blocks_total: int
    ledger: ExclusionLedger
    candidates: tuple[CandidateLaneEstimate, ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "blocks_total": self.blocks_total,
            "retained_blocks": list(self.ledger.retained_blocks),
            "excluded_blocks": list(self.ledger.excluded_blocks),
            "exclusion_ledger": self.ledger.to_document(),
            "candidates": [item.to_document() for item in self.candidates],
        }


@dataclass(frozen=True)
class AnalysisCampaign:
    """One treatment campaign's analysis rows."""

    campaign_index: int
    lanes: tuple[AnalysisLaneRow, ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "campaign_index": self.campaign_index,
            "lanes": [item.to_document() for item in self.lanes],
        }


@dataclass(frozen=True)
class AnalysisResult:
    """The complete in-memory ``synthetic-analysis-result`` payload."""

    experiment_id: str
    run_id: str
    source_seal_digest: str
    freeze_digest: str
    protocol_digest: str
    analysis_profile_digest: str
    analysis_id: str
    analysis_version: int
    estimator_id: str
    algorithm_id: str
    confidence_basis_points: int
    resamples: int
    seed: int
    baseline_arm_id: str
    candidate_ids: tuple[str, ...]
    lane_ids: tuple[str, ...]
    campaigns: tuple[AnalysisCampaign, ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "kind": ANALYSIS_KIND,
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "evidence_origin": SYNTHETIC_ORIGIN,
            "qualification_scope": SIMULATED_SCOPE,
            "status": DERIVED_STATUS,
            "source_seal_digest": self.source_seal_digest,
            "freeze_digest": self.freeze_digest,
            "protocol_digest": self.protocol_digest,
            "analysis_profile_digest": self.analysis_profile_digest,
            "analysis_id": self.analysis_id,
            "analysis_version": self.analysis_version,
            "estimator_id": self.estimator_id,
            "algorithm_id": self.algorithm_id,
            "confidence_basis_points": self.confidence_basis_points,
            "resamples": self.resamples,
            "seed": self.seed,
            "baseline_arm_id": self.baseline_arm_id,
            "candidate_ids": list(self.candidate_ids),
            "lane_ids": list(self.lane_ids),
            "campaigns": [item.to_document() for item in self.campaigns],
        }

    def record_count(self) -> int:
        """Return the number of emitted analysis leaf records."""

        total = 0
        for campaign in self.campaigns:
            for lane in campaign.lanes:
                total += 1 + len(lane.ledger.rows)
                for candidate in lane.candidates:
                    total += (
                        1
                        + len(candidate.raw_block_effects)
                        + len(candidate.retained_block_effects)
                    )
        return total


# ---------------------------------------------------------------------------
# Analysis output validation
# ---------------------------------------------------------------------------

_ANALYSIS_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "experiment_id",
        "run_id",
        "evidence_origin",
        "qualification_scope",
        "status",
        "source_seal_digest",
        "freeze_digest",
        "protocol_digest",
        "analysis_profile_digest",
        "analysis_id",
        "analysis_version",
        "estimator_id",
        "algorithm_id",
        "confidence_basis_points",
        "resamples",
        "seed",
        "baseline_arm_id",
        "candidate_ids",
        "lane_ids",
        "campaigns",
    }
)
_CAMPAIGN_KEYS = frozenset({"campaign_index", "lanes"})
_LANE_KEYS = frozenset(
    {
        "lane_id",
        "blocks_total",
        "retained_blocks",
        "excluded_blocks",
        "exclusion_ledger",
        "candidates",
    }
)
_LEDGER_KEYS = frozenset(
    {"block", "status", "reason", "trigger_arms", "arm_spreads"}
)
_SPREAD_KEYS = frozenset({"arm_id", "spread"})
_CANDIDATE_KEYS = frozenset(
    {
        "candidate_arm_id",
        "comparison_direction",
        "raw_point_effect",
        "retained_point_effect",
        "ci_low",
        "ci_high",
        "bootstrap_stream_digest",
        "status",
        "raw_block_effects",
        "retained_block_effects",
    }
)
_BLOCK_EFFECT_KEYS = frozenset(
    {"block", "normalized_effect", "raw_candidate_over_baseline"}
)


def _require_ascending_ints(value: object, field_path: str) -> tuple[int, ...]:
    items = require_list(value, field_path)
    numbers = tuple(
        require_int(item, f"{field_path}[{index}]")
        for index, item in enumerate(items)
    )
    if numbers != tuple(sorted(set(numbers))):
        raise _fail(f"{field_path} must be ascending and unique", field_path)
    return numbers


def _validate_block_effects(
    value: object, field_path: str
) -> tuple[dict[str, Any], ...]:
    entries = require_list(value, field_path)
    blocks: list[int] = []
    for index, raw in enumerate(entries):
        entry = require_closed(raw, f"{field_path}[{index}]", _BLOCK_EFFECT_KEYS)
        block = require_int(entry["block"], f"{field_path}[{index}].block", minimum=1)
        require_formatted_effect(
            entry["normalized_effect"], f"{field_path}[{index}].normalized_effect"
        )
        require_formatted_effect(
            entry["raw_candidate_over_baseline"],
            f"{field_path}[{index}].raw_candidate_over_baseline",
        )
        blocks.append(block)
    if blocks != sorted(set(blocks)):
        raise _fail(f"{field_path} must be in ascending unique block order", field_path)
    return tuple(entries)


def validate_analysis_result(
    document: object,
    bundle: ExperimentBundle,
    analysis_profile: Any,
    seal_digest: str,
) -> Mapping[str, Any]:
    """Strict structural and identity validation of one analysis document.

    This is not an independent recomputation (BM-05 owns that): it proves the
    closed field sets, the 12-place decimal form, the ordering rules and every
    identity binding against the declared bundle and analysis profile.
    """

    doc = require_closed(document, "analysis", _ANALYSIS_KEYS)
    if doc["kind"] != ANALYSIS_KIND:
        raise _schema("analysis.kind is invalid", "kind")
    if doc["schema_version"] != OUTPUT_SCHEMA_VERSION:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            "analysis.schema_version is not supported",
            field_path="schema_version",
        )
    require_synthetic_scope(
        doc["evidence_origin"], doc["qualification_scope"], "qualification_scope"
    )
    if doc["status"] != DERIVED_STATUS:
        raise _schema("analysis.status must be 'derived-synthetic'", "status")
    experiment_id = validate_semantic_id(doc["experiment_id"], "experiment_id")
    if experiment_id != bundle.experiment.experiment_id:
        raise _fail("analysis.experiment_id must match the bundle", "experiment_id")
    validate_uuid4(doc["run_id"], "run_id")
    for name in (
        "source_seal_digest",
        "freeze_digest",
        "protocol_digest",
        "analysis_profile_digest",
    ):
        validate_digest(doc[name], name)
    if doc["source_seal_digest"] != seal_digest:
        raise _fail(
            "analysis.source_seal_digest must match the replayed seal",
            "source_seal_digest",
        )
    if doc["protocol_digest"] != bundle.protocol_digest:
        raise _fail(
            "analysis.protocol_digest must match the declared protocol",
            "protocol_digest",
        )
    if doc["analysis_profile_digest"] != analysis_profile.digest:
        raise _fail(
            "analysis.analysis_profile_digest must match the frozen profile",
            "analysis_profile_digest",
        )
    if (
        doc["analysis_id"] != analysis_profile.analysis_id
        or doc["analysis_version"] != analysis_profile.analysis_version
    ):
        raise _fail(
            "analysis identity must match the frozen profile",
            "analysis_id",
        )
    if (
        doc["analysis_id"] != bundle.experiment.analysis.analysis_id
        or doc["analysis_version"] != bundle.experiment.analysis.analysis_version
        or doc["analysis_profile_digest"] != bundle.experiment.analysis.analysis_digest
    ):
        raise _fail(
            "analysis identity must match the experiment analysis binding",
            "analysis_id",
        )
    if doc["estimator_id"] != analysis_profile.estimator_id:
        raise _fail("analysis.estimator_id must match the profile", "estimator_id")
    if doc["algorithm_id"] != analysis_profile.bootstrap.algorithm_id:
        raise _fail("analysis.algorithm_id must match the profile", "algorithm_id")
    if doc["confidence_basis_points"] != CONFIDENCE_BASIS_POINTS:
        raise _fail(
            "analysis.confidence_basis_points must be 9500",
            "confidence_basis_points",
        )
    if doc["resamples"] != analysis_profile.bootstrap.resamples:
        raise _fail("analysis.resamples must match the profile", "resamples")
    if doc["seed"] != analysis_profile.bootstrap.seed:
        raise _fail("analysis.seed must match the profile", "seed")

    declared_arms = tuple(arm.arm_id for arm in bundle.experiment.arms)
    baseline_arm_id = validate_semantic_id(doc["baseline_arm_id"], "baseline_arm_id")
    if baseline_arm_id not in declared_arms:
        raise _fail("analysis.baseline_arm_id must be a declared arm", "baseline_arm_id")
    raw_candidates = require_list(doc["candidate_ids"], "candidate_ids")
    candidate_ids = tuple(
        validate_semantic_id(item, f"candidate_ids[{index}]")
        for index, item in enumerate(raw_candidates)
    )
    expected_candidates = tuple(
        arm_id for arm_id in declared_arms if arm_id != baseline_arm_id
    )
    if candidate_ids != expected_candidates:
        raise _fail(
            "analysis.candidate_ids must be the declared non-baseline arms in bundle order",
            "candidate_ids",
        )
    declared_lanes = tuple(lane.lane_id for lane in bundle.workload.lanes)
    raw_lanes = require_list(doc["lane_ids"], "lane_ids")
    lane_ids = tuple(
        validate_semantic_id(item, f"lane_ids[{index}]")
        for index, item in enumerate(raw_lanes)
    )
    if lane_ids != declared_lanes:
        raise _fail(
            "analysis.lane_ids must be the declared workload lanes in bundle order",
            "lane_ids",
        )

    raw_campaigns = require_list(doc["campaigns"], "campaigns")
    indices: list[int] = []
    for campaign_index, raw_campaign in enumerate(raw_campaigns):
        campaign = require_closed(
            raw_campaign, f"campaigns[{campaign_index}]", _CAMPAIGN_KEYS
        )
        index = require_int(
            campaign["campaign_index"],
            f"campaigns[{campaign_index}].campaign_index",
        )
        indices.append(index)
        raw_lanes_rows = require_list(
            campaign["lanes"], f"campaigns[{campaign_index}].lanes"
        )
        if len(raw_lanes_rows) != len(lane_ids):
            raise _fail(
                "each campaign must carry exactly one row per declared lane",
                "campaigns[].lanes",
            )
        for lane_position, raw_lane in enumerate(raw_lanes_rows):
            field = f"campaigns[{campaign_index}].lanes[{lane_position}]"
            lane = require_closed(raw_lane, field, _LANE_KEYS)
            if lane["lane_id"] != lane_ids[lane_position]:
                raise _fail("campaign lane rows must follow the declared lane order", field)
            blocks_total = require_int(lane["blocks_total"], f"{field}.blocks_total")
            retained = _require_ascending_ints(lane["retained_blocks"], f"{field}.retained_blocks")
            excluded = _require_ascending_ints(lane["excluded_blocks"], f"{field}.excluded_blocks")
            if set(retained) & set(excluded):
                raise _fail("a block cannot be both retained and excluded", field)
            if len(retained) + len(excluded) != blocks_total:
                raise _fail(
                    "retained plus excluded blocks must equal blocks_total", field
                )
            ledger = require_list(lane["exclusion_ledger"], f"{field}.exclusion_ledger")
            if len(ledger) != blocks_total:
                raise _fail(
                    "the exclusion ledger must list every scheduled block", field
                )
            ledger_blocks: list[int] = []
            ledger_retained: list[int] = []
            ledger_excluded: list[int] = []
            for position, raw_row in enumerate(ledger):
                row_field = f"{field}.exclusion_ledger[{position}]"
                row = require_closed(raw_row, row_field, _LEDGER_KEYS)
                block = require_int(row["block"], f"{row_field}.block", minimum=1)
                ledger_blocks.append(block)
                status = require_enum(
                    row["status"], f"{row_field}.status", ("retained", "excluded")
                )
                reason = require_enum(
                    row["reason"], f"{row_field}.reason", ("within-arm-spread", "none")
                )
                if (status, reason) not in (
                    ("retained", "none"),
                    ("excluded", "within-arm-spread"),
                ):
                    raise _fail("ledger status and reason are inconsistent", row_field)
                (ledger_retained if status == "retained" else ledger_excluded).append(block)
                triggers = require_list(row["trigger_arms"], f"{row_field}.trigger_arms")
                trigger_arms = [
                    validate_semantic_id(item, f"{row_field}.trigger_arms[]")
                    for item in triggers
                ]
                if trigger_arms != sorted(set(trigger_arms)):
                    raise _fail(
                        "ledger trigger arms must be ascending and unique", row_field
                    )
                if status == "retained" and trigger_arms:
                    raise _fail("a retained block cannot have trigger arms", row_field)
                if status == "excluded" and not trigger_arms:
                    raise _fail("an excluded block must name its trigger arms", row_field)
                spreads = require_list(row["arm_spreads"], f"{row_field}.arm_spreads")
                spread_arms: list[str] = []
                for spread_position, raw_spread in enumerate(spreads):
                    spread_field = f"{row_field}.arm_spreads[{spread_position}]"
                    spread = require_closed(raw_spread, spread_field, _SPREAD_KEYS)
                    spread_arms.append(
                        validate_semantic_id(spread["arm_id"], f"{spread_field}.arm_id")
                    )
                    require_formatted_effect(spread["spread"], f"{spread_field}.spread")
                if spread_arms != sorted(set(spread_arms)):
                    raise _fail(
                        "ledger arm spreads must be ascending and unique", row_field
                    )
                if not set(trigger_arms) <= set(spread_arms):
                    raise _fail(
                        "every trigger arm must carry a recorded spread", row_field
                    )
            if ledger_blocks != list(range(1, blocks_total + 1)):
                raise _fail(
                    "the exclusion ledger must list blocks 1..blocks_total in order",
                    field,
                )
            if tuple(ledger_retained) != retained:
                raise _fail("retained_blocks must match the ledger", field)
            if tuple(ledger_excluded) != excluded:
                raise _fail("excluded_blocks must match the ledger", field)

            raw_candidates = require_list(lane["candidates"], f"{field}.candidates")
            if len(raw_candidates) != len(candidate_ids):
                raise _fail("each lane must carry one row per candidate", field)
            for candidate_position, raw_candidate in enumerate(raw_candidates):
                candidate_field = f"{field}.candidates[{candidate_position}]"
                candidate = require_closed(raw_candidate, candidate_field, _CANDIDATE_KEYS)
                if candidate["candidate_arm_id"] != candidate_ids[candidate_position]:
                    raise _fail(
                        "candidate rows must follow the declared candidate order",
                        candidate_field,
                    )
                direction = require_enum(
                    candidate["comparison_direction"],
                    f"{candidate_field}.comparison_direction",
                    DIRECTIONS,
                )
                if direction != bundle.adapter.measurement_envelope.direction:
                    raise _fail(
                        "candidate comparison_direction must match the adapter envelope",
                        candidate_field,
                    )
                require_formatted_effect(
                    candidate["raw_point_effect"], f"{candidate_field}.raw_point_effect"
                )
                status = require_enum(
                    candidate["status"], f"{candidate_field}.status", (LANE_STATUS_ANALYZED, LANE_STATUS_INSUFFICIENT)
                )
                retained_effect = candidate["retained_point_effect"]
                ci_low = candidate["ci_low"]
                ci_high = candidate["ci_high"]
                stream_digest = candidate["bootstrap_stream_digest"]
                nullable = (retained_effect, ci_low, ci_high, stream_digest)
                if status == LANE_STATUS_INSUFFICIENT:
                    if any(item is not None for item in nullable):
                        raise _fail(
                            "an insufficient-block lane must null its retained effect, CI and stream digest",
                            candidate_field,
                        )
                else:
                    if any(item is None for item in nullable):
                        raise _fail(
                            "an analysed lane must carry its retained effect, CI and stream digest",
                            candidate_field,
                        )
                    require_formatted_effect(
                        retained_effect, f"{candidate_field}.retained_point_effect"
                    )
                    low = require_formatted_effect(ci_low, f"{candidate_field}.ci_low")
                    high = require_formatted_effect(ci_high, f"{candidate_field}.ci_high")
                    if low > high:
                        raise _fail("ci_low must not exceed ci_high", candidate_field)
                    validate_digest(stream_digest, f"{candidate_field}.bootstrap_stream_digest")
                raw_effects = _validate_block_effects(
                    candidate["raw_block_effects"], f"{candidate_field}.raw_block_effects"
                )
                retained_effects = _validate_block_effects(
                    candidate["retained_block_effects"],
                    f"{candidate_field}.retained_block_effects",
                )
                raw_blocks = [entry["block"] for entry in raw_effects]
                if raw_blocks != list(range(1, blocks_total + 1)):
                    raise _fail(
                        "raw_block_effects must cover every scheduled block in order",
                        candidate_field,
                    )
                if [entry["block"] for entry in retained_effects] != list(retained):
                    raise _fail(
                        "retained_block_effects must match retained_blocks",
                        candidate_field,
                    )
    if indices != list(range(len(indices))):
        raise _fail(
            "campaigns must be treatment-only and ordered by campaign_index",
            "campaigns",
        )
    return doc


# ---------------------------------------------------------------------------
# Policy output validation
# ---------------------------------------------------------------------------

_POLICY_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "experiment_id",
        "run_id",
        "evidence_origin",
        "qualification_scope",
        "status",
        "analysis_digest",
        "policy_profile_digest",
        "resource_observations_digest",
        "policy_id",
        "policy_version",
        "baseline_arm_id",
        "candidate_results",
        "selected_arm_id",
        "decision_status",
        "reasons",
        "ranking",
    }
)
_POLICY_CANDIDATE_KEYS = frozenset(
    {"arm_id", "status", "worst_campaign_gm", "campaign_results"}
)
_POLICY_CAMPAIGN_KEYS = frozenset({"campaign_index", "status", "lanes"})
_POLICY_LANE_KEYS = frozenset(
    {
        "lane_id",
        "kind",
        "point_effect",
        "ci_low",
        "ci_high",
        "point_limit",
        "ci_limit",
        "ci_operator",
        "retained_blocks",
        "status",
        "reasons",
    }
)
_REASON_KEYS = frozenset({"candidate_arm_id", "campaign_index", "lane_id", "code"})
_RANKING_KEYS = frozenset({"arm_id", "worst_campaign_gm"})


def _sort_reasons(reasons: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    def key(item: Mapping[str, Any]) -> tuple[int, str, str]:
        campaign = item["campaign_index"]
        lane = item["lane_id"]
        return (
            -1 if campaign is None else int(campaign),
            "" if lane is None else str(lane),
            str(item["code"]),
        )

    return sorted(reasons, key=key)


def validate_policy_decision(
    document: object,
    bundle: ExperimentBundle,
    policy_profile: Any,
    analysis_digest: str,
    resources_digest: str,
) -> Mapping[str, Any]:
    """Strict structural and identity validation of one policy decision document."""

    doc = require_closed(document, "policy", _POLICY_KEYS)
    if doc["kind"] != POLICY_KIND:
        raise _schema("policy.kind is invalid", "kind")
    if doc["schema_version"] != OUTPUT_SCHEMA_VERSION:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            "policy.schema_version is not supported",
            field_path="schema_version",
        )
    require_synthetic_scope(
        doc["evidence_origin"], doc["qualification_scope"], "qualification_scope"
    )
    if doc["status"] != DERIVED_STATUS:
        raise _schema("policy.status must be 'derived-synthetic'", "status")
    experiment_id = validate_semantic_id(doc["experiment_id"], "experiment_id")
    if experiment_id != bundle.experiment.experiment_id:
        raise _fail("policy.experiment_id must match the bundle", "experiment_id")
    validate_uuid4(doc["run_id"], "run_id")
    validate_digest(doc["analysis_digest"], "analysis_digest")
    validate_digest(doc["policy_profile_digest"], "policy_profile_digest")
    validate_digest(doc["resource_observations_digest"], "resource_observations_digest")
    if doc["analysis_digest"] != analysis_digest:
        raise _fail("policy.analysis_digest must match the analysis document", "analysis_digest")
    if doc["policy_profile_digest"] != policy_profile.digest:
        raise _fail(
            "policy.policy_profile_digest must match the frozen policy",
            "policy_profile_digest",
        )
    if doc["resource_observations_digest"] != resources_digest:
        raise _fail(
            "policy.resource_observations_digest must match the frozen observations",
            "resource_observations_digest",
        )
    if (
        doc["policy_id"] != policy_profile.policy_id
        or doc["policy_version"] != policy_profile.policy_version
    ):
        raise _fail("policy identity must match the frozen policy profile", "policy_id")
    if (
        doc["policy_id"] != bundle.experiment.policy.policy_id
        or doc["policy_version"] != bundle.experiment.policy.policy_version
        or doc["policy_profile_digest"] != bundle.experiment.policy.policy_digest
        or doc["policy_profile_digest"] != bundle.protocol.policy.policy_digest
        or doc["policy_id"] != bundle.protocol.policy.policy_id
        or doc["policy_version"] != bundle.protocol.policy.policy_version
    ):
        raise _fail(
            "policy identity must match both experiment and protocol bindings",
            "policy_profile_digest",
        )
    if doc["baseline_arm_id"] != policy_profile.baseline_arm_id:
        raise _fail("policy.baseline_arm_id must match the frozen policy", "baseline_arm_id")

    raw_candidates = require_list(doc["candidate_results"], "candidate_results")
    if len(raw_candidates) != len(policy_profile.candidate_order):
        raise _fail("policy must report every frozen candidate", "candidate_results")
    statuses: dict[str, str] = {}
    gms: dict[str, Decimal | None] = {}
    for position, raw_candidate in enumerate(raw_candidates):
        field = f"candidate_results[{position}]"
        candidate = require_closed(raw_candidate, field, _POLICY_CANDIDATE_KEYS)
        arm_id = validate_semantic_id(candidate["arm_id"], f"{field}.arm_id")
        if arm_id != policy_profile.candidate_order[position]:
            raise _fail("policy candidate order must be the frozen order", field)
        status = require_enum(
            candidate["status"],
            f"{field}.status",
            (CANDIDATE_ELIGIBLE, CANDIDATE_INELIGIBLE, CANDIDATE_INCONCLUSIVE),
        )
        statuses[arm_id] = status
        worst_gm = candidate["worst_campaign_gm"]
        if worst_gm is None:
            gms[arm_id] = None
        else:
            gms[arm_id] = require_formatted_effect(worst_gm, f"{field}.worst_campaign_gm")
        if status == CANDIDATE_ELIGIBLE and worst_gm is None:
            raise _fail("an eligible candidate must carry a worst campaign GM", field)
        raw_campaigns = require_list(candidate["campaign_results"], f"{field}.campaign_results")
        campaign_indices: list[int] = []
        for campaign_position, raw_campaign in enumerate(raw_campaigns):
            campaign_field = f"{field}.campaign_results[{campaign_position}]"
            campaign = require_closed(raw_campaign, campaign_field, _POLICY_CAMPAIGN_KEYS)
            campaign_indices.append(
                require_int(campaign["campaign_index"], f"{campaign_field}.campaign_index")
            )
            require_enum(
                campaign["status"],
                f"{campaign_field}.status",
                (CANDIDATE_ELIGIBLE, CANDIDATE_INELIGIBLE, CANDIDATE_INCONCLUSIVE),
            )
            raw_lanes = require_list(campaign["lanes"], f"{campaign_field}.lanes")
            for lane_position, raw_lane in enumerate(raw_lanes):
                lane_field = f"{campaign_field}.lanes[{lane_position}]"
                lane = require_closed(raw_lane, lane_field, _POLICY_LANE_KEYS)
                validate_semantic_id(lane["lane_id"], f"{lane_field}.lane_id")
                require_enum(lane["kind"], f"{lane_field}.kind", ("target", "guardrail"))
                for name in ("point_effect", "ci_low", "ci_high"):
                    if lane[name] is not None:
                        require_formatted_effect(lane[name], f"{lane_field}.{name}")
                require_formatted_effect(lane["point_limit"], f"{lane_field}.point_limit")
                require_formatted_effect(lane["ci_limit"], f"{lane_field}.ci_limit")
                require_enum(lane["ci_operator"], f"{lane_field}.ci_operator", ("lt", "le"))
                require_int(lane["retained_blocks"], f"{lane_field}.retained_blocks")
                require_enum(
                    lane["status"],
                    f"{lane_field}.status",
                    ("pass", "unproven", "decisive-failure", "insufficient"),
                )
                codes = require_list(lane["reasons"], f"{lane_field}.reasons")
                for code in codes:
                    if not isinstance(code, str) or not code:
                        raise _schema("lane reason codes must be non-empty strings", lane_field)
        if campaign_indices != list(range(len(campaign_indices))):
            raise _fail(
                "campaign_results must be ordered by campaign_index", field
            )

    raw_reasons = require_list(doc["reasons"], "reasons")
    reasons: list[Mapping[str, Any]] = []
    for position, raw_reason in enumerate(raw_reasons):
        field = f"reasons[{position}]"
        reason = require_closed(raw_reason, field, _REASON_KEYS)
        validate_semantic_id(reason["candidate_arm_id"], f"{field}.candidate_arm_id")
        if reason["campaign_index"] is not None:
            require_int(reason["campaign_index"], f"{field}.campaign_index")
        if reason["lane_id"] is not None:
            validate_semantic_id(reason["lane_id"], f"{field}.lane_id")
        code = reason["code"]
        if not isinstance(code, str) or not code:
            raise _schema(f"{field}.code must be a non-empty string", field)
        reasons.append(reason)
    if list(_sort_reasons(reasons)) != [dict(item) for item in reasons]:
        raise _fail(
            "policy reasons must be sorted by (campaign_index, lane_id, code)", "reasons"
        )

    ranking = require_list(doc["ranking"], "ranking")
    ranked_arms: list[str] = []
    previous: Decimal | None = None
    for position, raw_entry in enumerate(ranking):
        field = f"ranking[{position}]"
        entry = require_closed(raw_entry, field, _RANKING_KEYS)
        arm_id = validate_semantic_id(entry["arm_id"], f"{field}.arm_id")
        gm = require_formatted_effect(entry["worst_campaign_gm"], f"{field}.worst_campaign_gm")
        if previous is not None and gm < previous:
            raise _fail("ranking must be ordered by ascending worst campaign GM", "ranking")
        previous = gm
        ranked_arms.append(arm_id)
    eligible = [arm_id for arm_id in policy_profile.candidate_order if statuses[arm_id] == CANDIDATE_ELIGIBLE]
    if ranked_arms != eligible:
        raise _fail(
            "ranking must list exactly the eligible candidates in frozen order",
            "ranking",
        )

    selected = doc["selected_arm_id"]
    status = doc["decision_status"]
    require_enum(status, "decision_status", DECISION_STATUSES)
    if selected is None:
        if status != DECISION_INCONCLUSIVE:
            raise _fail(
                "a null selected_arm_id requires decision_status INCONCLUSIVE",
                "decision_status",
            )
    else:
        validate_semantic_id(selected, "selected_arm_id")
        if selected == policy_profile.baseline_arm_id:
            if status != DECISION_BASELINE_ONLY:
                raise _fail(
                    "a baseline selection requires BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE",
                    "decision_status",
                )
        else:
            if status not in (DECISION_SELECTED, DECISION_TIE_PREFERENCE):
                raise _fail("a candidate selection requires a candidate decision status", "decision_status")
            if statuses.get(selected) != CANDIDATE_ELIGIBLE:
                raise _fail("a selected candidate must be eligible", "selected_arm_id")
    if status == DECISION_BASELINE_ONLY:
        if any(value == CANDIDATE_ELIGIBLE for value in statuses.values()):
            raise _fail(
                "the baseline-only fallback requires every candidate to be ineligible",
                "decision_status",
            )
        if any(value == CANDIDATE_INCONCLUSIVE for value in statuses.values()):
            raise _fail(
                "the baseline-only fallback forbids an inconclusive candidate",
                "decision_status",
            )
    if status == DECISION_SELECTED and len(eligible) != 1:
        raise _fail(
            "SELECTED_ELIGIBLE_SYNTHETIC requires exactly one eligible candidate",
            "decision_status",
        )
    if status == DECISION_INCONCLUSIVE and eligible:
        any_inconclusive = any(
            value == CANDIDATE_INCONCLUSIVE for value in statuses.values()
        )
        if not any_inconclusive:  # pragma: no cover - defensive
            raise _fail(
                "INCONCLUSIVE requires an inconclusive candidate", "decision_status"
            )
    return doc
