"""Frozen BM-05 verification contract: assessment record and check registry.

This module is deliberately tiny. It declares the single in-memory result a
successful independent verification may return, the stable ordered check-id
registry, and the literal v1 vocabulary the reference implementation is allowed
to recognise.

The literals below are a **reference copy**, not an import of BM-04 decision or
arithmetic code. :mod:`quervant_bench.verification.verify` asserts that every
declared profile still uses these frozen names, so a silent profile change is a
typed rejection rather than a silently accepted new semantics.

There is no receipt, no attestation, no persistence and no deployment
permission here. ``VerificationAssessment`` is an in-memory Python value only.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

# ---------------------------------------------------------------------------
# Public result vocabulary
# ---------------------------------------------------------------------------

VERIFICATION_STATUS = "verified-synthetic"
EVIDENCE_ORIGIN = "synthetic"
QUALIFICATION_SCOPE = "simulated"
REFERENCE_ID = "independent-synthetic-v1"

#: Stable, ordered check identifiers. An id is only attached to an assessment
#: after every mandatory check has passed.
CHECK_IDS: tuple[str, ...] = (
    "VC-01-SCOPE",
    "VC-02-PROFILE-BINDINGS",
    "VC-03-STRUCTURAL-REPLAY",
    "VC-04-SEALED-INPUT-INVENTORY",
    "VC-05-INDEPENDENT-STATISTICS",
    "VC-06-INDEPENDENT-BOOTSTRAP",
    "VC-07-INDEPENDENT-POLICY",
    "VC-08-OUTPUT-IDENTITY",
    "VC-09-POST-READ-INTEGRITY",
)


@dataclass(frozen=True)
class VerificationAssessment:
    """The only successful independent-verification result.

    The object is frozen, carries no receipt identity, has no write/publish
    method and cannot approve deployment or a real performance conclusion.
    """

    status: Literal["verified-synthetic"]
    experiment_id: str
    run_id: str
    evidence_origin: Literal["synthetic"]
    qualification_scope: Literal["simulated"]
    analysis_digest: str
    policy_digest: str
    source_seal_digest: str
    reference_id: Literal["independent-synthetic-v1"]
    check_ids: tuple[str, ...]


# ---------------------------------------------------------------------------
# Frozen reference vocabulary (asserted against the declared profiles)
# ---------------------------------------------------------------------------

OUTPUT_SCHEMA_VERSION = 1
ANALYSIS_KIND = "synthetic-analysis-result"
POLICY_KIND = "synthetic-policy-decision"
DERIVED_STATUS = "derived-synthetic"

DECIMAL_PRECISION = 50
DECIMAL_QUANTUM = Decimal("0.000000000001")
OUTPUT_DECIMAL_PLACES = 12

CONFIDENCE_BASIS_POINTS = 9500
TAIL_BASIS_POINTS = 250
BASIS_POINTS_TOTAL = 10_000
MIN_RESAMPLES = 100
MAX_RESAMPLES = 20_000
MAX_TOTAL_DRAWS = 2_000_000

SLOT_AGGREGATOR = "median-v1"
BLOCK_AGGREGATOR = "mean-of-slot-medians-v1"
EXCLUSION_RULESET = "within-arm-spread-v1"
BOOTSTRAP_ALGORITHM = "sha256-rejection-paired-block-v1"
BOOTSTRAP_INTERVAL_ID = "nearest-rank-percentile-v1"
FILTER_SENSITIVITY_ACTION = "inconclusive"

DIRECTION_LOWER_IS_BETTER = "lower-is-better"
DIRECTION_HIGHER_IS_BETTER = "higher-is-better"
DIRECTIONS = frozenset({DIRECTION_LOWER_IS_BETTER, DIRECTION_HIGHER_IS_BETTER})

ESTIMATOR_MEDIAN_PAIRED_RATIOS = "median-paired-ratios-v1"
ESTIMATOR_RATIO_OF_ARM_MEDIANS = "ratio-of-arm-medians-v1"
ESTIMATORS = frozenset(
    {ESTIMATOR_MEDIAN_PAIRED_RATIOS, ESTIMATOR_RATIO_OF_ARM_MEDIANS}
)

LANE_STATUS_ANALYZED = "analyzed"
LANE_STATUS_INSUFFICIENT = "inconclusive-insufficient-blocks"

CANDIDATE_ELIGIBLE = "ELIGIBLE"
CANDIDATE_INELIGIBLE = "INELIGIBLE"
CANDIDATE_INCONCLUSIVE = "INCONCLUSIVE"

DECISION_SELECTED = "SELECTED_ELIGIBLE_SYNTHETIC"
DECISION_TIE_PREFERENCE = "TIE_PREFERENCE_NOT_PROVEN_FASTER"
DECISION_BASELINE_ONLY = "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE"
DECISION_INCONCLUSIVE = "INCONCLUSIVE"

REASON_RESOURCE_OVER_LIMIT = "RESOURCE_OVER_LIMIT"
REASON_MISSING_RESOURCE = "MISSING_RESOURCE"
REASON_INSUFFICIENT_RETAINED_BLOCKS = "INSUFFICIENT_RETAINED_BLOCKS"
REASON_TARGET_DECISIVE_FAILURE = "TARGET_DECISIVE_FAILURE"
REASON_TARGET_UNPROVEN = "TARGET_UNPROVEN"
REASON_GUARDRAIL_DECISIVE_FAILURE = "GUARDRAIL_DECISIVE_FAILURE"
REASON_GUARDRAIL_UNPROVEN = "GUARDRAIL_UNPROVEN"
REASON_FILTER_SENSITIVE = "FILTER_SENSITIVE"
REASON_MISSING_RANKING_GM = "MISSING_RANKING_GM"

__all__ = [
    "CHECK_IDS",
    "EVIDENCE_ORIGIN",
    "QUALIFICATION_SCOPE",
    "REFERENCE_ID",
    "VERIFICATION_STATUS",
    "VerificationAssessment",
]
