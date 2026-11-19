"""Gate B: frozen per-family real analysis and official policy decision.

The arithmetic here is the *official* family method. It never imports
``analysis.analyze_synthetic_run``, never reclassifies synthetic evidence and
never invents a threshold from the observed data: every constant comes from the
independently approved design template.

A verified cross-engine study is intentionally ``INCONCLUSIVE``: the frozen
PR15D three-trial descriptive convention is not a rigorous selection policy. A
retained-key study needs authentic nine-K policy inputs; without them the only
honest outcome is ``POLICY_NOT_DERIVABLE``.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Callable, Mapping, Sequence

from ..config.codec import content_digest
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id
from ..qualification.contracts import bound_payload, document_digest
from .admission import (
    D3C_CAMPAIGN_NAMES,
    D3C_CONTROL_NAME,
    AdmittedCrossEngine,
    AdmittedRetainedKey,
    d3c_lane_keys,
    pr15d_lane_field,
    pr15d_lane_id,
    pr15d_lane_keys,
)
from .contracts import (
    DECISION_INCONCLUSIVE,
    DECISION_POLICY_NOT_DERIVABLE,
    DECISION_SELECTED,
    DECISION_TIE_PREFERENCE,
    EXCLUDED_LANE_CLASSES,
    OFFICIAL_UNIT,
    STATISTICS_CROSS_ENGINE,
    STATISTICS_RETAINED_KEY,
    validate_official_analysis,
    validate_official_policy,
)
from .controls import assess_retained_key_control, decimal_string
from .protocols import PR15D_ENGINES, STUDY_CROSS_ENGINE, STUDY_RETAINED_KEY

CROSS_ENGINE_DISPERSION_LIMIT = Fraction(110, 100)
CROSS_ENGINE_UNCERTAINTY_ID = "pr15d-three-trial-discrete-range-v1"
RETAINED_KEY_UNCERTAINTY_ID = "retained-key-frozen-block-dispersion-v1"
LANE_ANALYZED = "analyzed"
LANE_INSUFFICIENT = "inconclusive-insufficient-blocks"

#: Retained-key arm letters -> official semantic arm identifiers.
ARM_LABELS: dict[str, str] = {
    "A": "base",
    "L": "linear",
    "P": "prefilter",
    "H": "exact-set",
}
OFFICIAL_ARMS: tuple[str, ...] = tuple(sorted(ARM_LABELS.values()))


def _identity(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def _schema(message: str, field: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field)


# ---------------------------------------------------------------------------
# Frozen statistics primitives
# ---------------------------------------------------------------------------


def lower_median(values: Sequence[int]) -> int:
    """Return the frozen lower-middle median (``sorted[(n-1)//2]``).

    For twenty samples this is ``sorted[9]``; for three trial medians it is the
    middle value; for a retained set of four blocks it is ``sorted[1]``, exactly
    the historical D3-C ``median4`` convention.
    """

    if not values:
        raise BenchError(BM_UNSAFE_INPUT, "a median requires at least one value")
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def nearest_rank(values: Sequence[int], percentile: int) -> int:
    """Return the frozen nearest-rank percentile value."""

    if not values:
        raise BenchError(BM_UNSAFE_INPUT, "a percentile requires at least one value")
    if not 0 < percentile <= 100:
        raise BenchError(BM_UNSAFE_INPUT, "percentile must be in (0, 100]")
    ordered = sorted(values)
    index = (percentile * len(ordered) + 99) // 100 - 1
    return ordered[index]


def exact_ratio(numerator: int, denominator: int) -> Fraction:
    """Return an exact rational ratio of two positive integers."""

    if numerator <= 0 or denominator <= 0:
        raise BenchError(BM_UNSAFE_INPUT, "a ratio requires positive operands")
    return Fraction(numerator, denominator)


def dispersion(values: Sequence[int]) -> Fraction:
    """Return ``max/min`` as an exact rational dispersion."""

    if not values:
        raise BenchError(BM_UNSAFE_INPUT, "dispersion requires at least one value")
    if min(values) <= 0:
        raise BenchError(BM_UNSAFE_INPUT, "dispersion requires positive values")
    return Fraction(max(values), min(values))


def _six(value: Fraction) -> str:
    return decimal_string(value)


def _require_samples(lane: Mapping[str, Any]) -> list[int]:
    samples = lane.get("samples_ns")
    if not isinstance(samples, list) or len(samples) != 20:
        raise _identity("a measured lane must hold exactly twenty samples", "samples_ns")
    for sample in samples:
        if isinstance(sample, bool) or not isinstance(sample, int) or sample <= 0:
            raise _identity("measured samples must be positive integers", "samples_ns")
    return list(samples)


# ---------------------------------------------------------------------------
# Cross-engine analysis
# ---------------------------------------------------------------------------


def analyze_cross_engine_real(
    *,
    admitted: AdmittedCrossEngine,
    template: Mapping[str, Any],
    control: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the Gate B analysis and policy records for the PR15D family."""

    if template.get("study_id") != STUDY_CROSS_ENGINE:
        raise _identity("the template is for a different study", "study_id")
    subject = dict(admitted.admission_index["subject"])
    lane_records: list[dict[str, Any]] = []
    for key in pr15d_lane_keys():
        n, class_name, k, regime = key
        if regime != "warm":
            continue
        lane_id = pr15d_lane_id(n, class_name, k)
        per_engine: dict[str, Any] = {}
        for engine in sorted(PR15D_ENGINES):
            trial_medians = [
                lower_median(_require_samples(admitted.lane(trial, engine, key)))
                for trial in range(1, 4)
            ]
            engine_median = lower_median(trial_medians)
            per_engine[engine] = {
                "trial_medians_ns": trial_medians,
                "median_ns": engine_median,
                "min_ns": min(trial_medians),
                "max_ns": max(trial_medians),
                "dispersion": _six(dispersion(trial_medians)),
            }
        quervant = per_engine["quervant"]
        comparisons: list[dict[str, Any]] = []
        for comparator in ("lucene", "tantivy"):
            entry = per_engine[comparator]
            ratio = exact_ratio(entry["median_ns"], quervant["median_ns"])
            dispersion_ok = (
                Fraction(entry["max_ns"], entry["min_ns"]) <= CROSS_ENGINE_DISPERSION_LIMIT
                and Fraction(quervant["max_ns"], quervant["min_ns"])
                <= CROSS_ENGINE_DISPERSION_LIMIT
            )
            overlap = not (
                entry["max_ns"] < quervant["min_ns"] or quervant["max_ns"] < entry["min_ns"]
            )
            comparisons.append(
                {
                    "comparator": comparator,
                    "ratio": _six(ratio),
                    "dispersion_ok": bool(dispersion_ok),
                    "ranges_overlap": bool(overlap),
                    "inconclusive": bool((not dispersion_ok) or overlap),
                }
            )
        lane_records.append(
            {"lane_id": lane_id, "per_engine": per_engine, "comparisons": comparisons}
        )
    lane_records.sort(key=lambda record: record["lane_id"])

    cold_ids = [
        pr15d_lane_id(n, class_name, k)
        for (n, class_name, k, regime) in pr15d_lane_keys()
        if regime == "process_cold"
    ]
    analysis = {
        "kind": "official-analysis-result",
        "schema_version": 1,
        "evidence_origin": "real",
        "qualification_scope": "official",
        "subject": subject,
        "study_id": STUDY_CROSS_ENGINE,
        "raw_series_root_digest": admitted.raw_series_root_digest,
        "analysis_profile_digest": document_digest(dict(template)),
        "statistics_method_id": STATISTICS_CROSS_ENGINE,
        "eligible_lane_ids": sorted({record["lane_id"] for record in lane_records}),
        "excluded_lane_classes": list(EXCLUDED_LANE_CLASSES),
        "control_result_digest": content_digest(dict(control)),
        "campaigns": [
            {
                "campaign_id": "separate-aa-control",
                "slot_count": 48,
                "lane_count": len(control.get("lanes", [])),
                "sample_count": 48 * len(control.get("lanes", [])) * 20,
                "control": True,
                "descriptive_process_cold": [],
            },
            {
                "campaign_id": "three-trial-backend",
                "slot_count": 9,
                "lane_count": 288,
                "sample_count": 5_760,
                "control": False,
                "descriptive_process_cold": cold_ids,
            },
        ],
        "statistics": {
            "method_id": STATISTICS_CROSS_ENGINE,
            "unit": OFFICIAL_UNIT,
            "engines": list(sorted(PR15D_ENGINES)),
            "lanes": lane_records,
        },
        "uncertainty": {
            "method_id": CROSS_ENGINE_UNCERTAINTY_ID,
            "dispersion_limit": "1.100000",
            "overlap_rule": True,
            "significance_claim": "none",
        },
        "limitations": sorted(
            [
                "lexical-scored-not-comparable",
                "no-significance-claim",
                "physical-sort-workloads-differ",
                "process-cold-not-os-cold",
                "throughput-not-normalized",
            ]
        ),
    }
    validated_analysis = validate_official_analysis(analysis)
    policy = derive_official_policy(
        study_id=STUDY_CROSS_ENGINE,
        subject=subject,
        analysis_document=validated_analysis,
        policy_profile_digest=policy_profile_digest(
            STUDY_CROSS_ENGINE, template["policy"]["policy_chain"]
        ),
        decisions=_cross_engine_decisions(),
    )
    return validated_analysis, policy


def _cross_engine_decisions() -> dict[str, Any]:
    return {
        "decision_status": DECISION_INCONCLUSIVE,
        "selected_arm_id": None,
        "candidate_statuses": {"lucene": "INCONCLUSIVE", "quervant": "INCONCLUSIVE", "tantivy": "INCONCLUSIVE"},
        "reasons": [
            "descriptive-policy-has-no-significance-claim",
            "no-globally-fastest-engine-in-v1",
        ],
        "performance_claim_allowed": False,
    }


# ---------------------------------------------------------------------------
# Retained-key analysis
# ---------------------------------------------------------------------------


def retained_key_block_medians(
    slots: Sequence[Mapping[str, Any]], *, arm: str, lane_id: str
) -> list[int]:
    """Return twelve per-block lane medians for one arm (frozen combination)."""

    by_block: dict[int, dict[int, int]] = {}
    for slot in slots:
        if slot.get("arm") != arm:
            continue
        block = int(slot["block"])
        position = int(slot["position"])
        record = None
        for lane in slot["lanes"]:
            if lane.get("id") == lane_id:
                record = lane
                break
        if record is None:
            raise _identity("a slot does not hold the requested lane", "lanes")
        by_block.setdefault(block, {})[position] = int(record["summary_ns"]["median"])
    medians: list[int] = []
    for block in range(1, 13):
        positions = sorted(by_block.get(block, {}))
        if len(positions) != 2:
            raise _identity("each arm must appear twice per block", "block")
        values = [by_block[block][position] for position in positions]
        medians.append((values[0] + values[1]) // 2)
    return medians


def within_arm_cap(template: Mapping[str, Any], *, n: int, class_name: str) -> Fraction:
    """Return the frozen within-arm exclusion cap for one lane."""

    if n == 100_000 and class_name in ("medium", "common"):
        raw = template["statistics"]["within_arm_exclusion_cap_100k_medium_common"]
    else:
        raw = template["statistics"]["within_arm_exclusion_cap_other"]
    whole, _, fraction = str(raw).partition(".")
    return Fraction(int(whole) * 1_000_000 + int(fraction), 1_000_000)


def retained_block_indices(values: Sequence[int], cap: Fraction) -> list[int]:
    """Return the retained 1-based block indices under the frozen cap."""

    minimum = min(values)
    retained: list[int] = []
    for index, value in enumerate(values, start=1):
        if Fraction(value, minimum) <= cap:
            retained.append(index)
    return retained


def analyze_retained_key_real(
    *,
    admitted: AdmittedRetainedKey,
    template: Mapping[str, Any],
    policy_inputs: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the Gate B analysis for the retained-key family."""

    if template.get("study_id") != STUDY_RETAINED_KEY:
        raise _identity("the template is for a different study", "study_id")
    subject = dict(admitted.admission_index["subject"])
    min_retained = int(template["statistics"]["min_retained_blocks_per_lane"])
    arms = list(OFFICIAL_ARMS)
    lanes: list[dict[str, Any]] = []
    for campaign in D3C_CAMPAIGN_NAMES:
        for lane in d3c_lane_keys():
            lane_record: dict[str, Any] = {
                "campaign_id": campaign,
                "lane_id": lane["lane_id"],
                "n": lane["n"],
                "class": lane["class"],
                "k": lane["k"],
                "arms": {},
            }
            insufficient = False
            for arm in arms:
                letters = [letter for letter, label in ARM_LABELS.items() if label == arm]
                if len(letters) != 1:  # pragma: no cover - guarded by construction
                    raise _identity("an official arm label has no slot letter", "arms")
                values = retained_key_block_medians(
                    admitted.slots[campaign], arm=letters[0], lane_id=lane["lane_id"]
                )
                cap = within_arm_cap(template, n=lane["n"], class_name=lane["class"])
                retained = retained_block_indices(values, cap)
                excluded = [index for index in range(1, 13) if index not in retained]
                if len(retained) < min_retained:
                    insufficient = True
                retained_values = [values[index - 1] for index in retained]
                lane_record["arms"][arm] = {
                    "blocks": 12,
                    "block_medians_ns": values,
                    "retained_block_indices": retained,
                    "excluded_block_indices": excluded,
                    "retained_median_ns": lower_median(retained_values),
                }
            lane_record["status"] = LANE_INSUFFICIENT if insufficient else LANE_ANALYZED
            lanes.append(lane_record)

    control = admitted.control_assessment
    recomputed_control = assess_retained_key_control(
        slots=admitted.slots[D3C_CONTROL_NAME],
        lane_ids=[lane["lane_id"] for lane in d3c_lane_keys()],
        windows=template["controls"]["windows"],
    )
    if recomputed_control["a_a"]["passes"] is not True:
        raise _identity("the retained-key control does not pass", "control")
    if control["a_a"]["passes"] is not True:
        raise _identity("the admitted control assessment does not pass", "control")

    analysis = {
        "kind": "official-analysis-result",
        "schema_version": 1,
        "evidence_origin": "real",
        "qualification_scope": "official",
        "subject": subject,
        "study_id": STUDY_RETAINED_KEY,
        "raw_series_root_digest": admitted.raw_series_root_digest,
        "analysis_profile_digest": document_digest(dict(template)),
        "statistics_method_id": STATISTICS_RETAINED_KEY,
        "eligible_lane_ids": sorted({record["lane_id"] for record in lanes}),
        "excluded_lane_classes": list(EXCLUDED_LANE_CLASSES),
        "control_result_digest": content_digest(dict(control)),
        "campaigns": [
            {
                "campaign_id": D3C_CONTROL_NAME,
                "slot_count": 48,
                "lane_count": 72,
                "sample_count": 48 * 72 * 20,
                "control": True,
                "descriptive_process_cold": [],
            },
            *[
                {
                    "campaign_id": name,
                    "slot_count": 96,
                    "lane_count": 72,
                    "sample_count": 96 * 72 * 20,
                    "control": False,
                    "descriptive_process_cold": [],
                }
                for name in D3C_CAMPAIGN_NAMES
            ],
        ],
        "statistics": {
            "method_id": STATISTICS_RETAINED_KEY,
            "unit": OFFICIAL_UNIT,
            "arms": arms,
            "lanes": lanes,
        },
        "uncertainty": {
            "method_id": RETAINED_KEY_UNCERTAINTY_ID,
            "confidence_level": "0.95",
            "resamples": int(template["statistics"]["bootstrap_resamples"]),
            "significance_claim": "none",
        },
        "limitations": sorted(
            [
                "no-extrapolation-to-current-head",
                "old-v3r3-protocol-remains-diagnostic",
                "policy-inputs-may-be-unavailable",
                "retained-key-only",
            ]
        ),
    }
    validated = validate_official_analysis(analysis)
    policy = derive_official_policy(
        study_id=STUDY_RETAINED_KEY,
        subject=subject,
        analysis_document=validated,
        policy_profile_digest=policy_profile_digest(
            STUDY_RETAINED_KEY, template["policy"]["policy_chain"]
        ),
        decisions=None,
        template=template,
    )
    if policy_inputs is not None:
        from .contracts import retained_policy_decisions
        from .policy_inputs import reverify_retained_policy_inputs
        from .retained_policy import derive_retained_policy

        if getattr(policy_inputs, "scope", None) != "official":
            raise BenchError(BM_UNSAFE_INPUT, "historical policy inputs cannot be used for official analysis")
        fresh, memory = reverify_retained_policy_inputs(
            policy_inputs, admitted=admitted, for_production=not admitted.fixture_only
        )
        payload = derive_retained_policy(fresh, memory, policy_inputs.inputs_digest)
        policy.update(retained_policy_decisions(payload))
        policy["schema_version"] = 2
        policy["retained_key_policy"] = payload
        policy = validate_official_policy(policy)
    return validated, policy


# ---------------------------------------------------------------------------
# Policy decision
# ---------------------------------------------------------------------------


def policy_profile_digest(study_id: str, policy_chain: str) -> str:
    """Return the frozen policy-profile binding digest for one study.

    The value is a pure function of the approved study and policy chain, so an
    independent reviewer can pin it at G0 without seeing any measurement.
    """

    return content_digest(
        {
            "kind": "official-policy-profile",
            "schema_version": 1,
            "study_id": validate_semantic_id(study_id, "study_id"),
            "policy_chain": policy_chain,
        }
    )


def derive_official_policy(
    *,
    study_id: str,
    subject: Mapping[str, Any],
    analysis_document: Mapping[str, Any],
    policy_profile_digest: str,
    decisions: Mapping[str, Any] | None = None,
    template: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the official policy decision record.

    Cross-engine v1 is frozen to ``INCONCLUSIVE``. Retained-key v1 requires
    authentic nine-K policy inputs; with none available the only permitted
    outcome is ``POLICY_NOT_DERIVABLE``.
    """

    validate_semantic_id(study_id, "study_id")
    analysis = validate_official_analysis(dict(analysis_document))
    if study_id == STUDY_CROSS_ENGINE:
        if decisions is None:
            decisions = _cross_engine_decisions()
        elif decisions["decision_status"] != DECISION_INCONCLUSIVE:
            raise _identity(
                "the frozen cross-engine policy cannot select an engine in v1",
                "decision_status",
            )
    else:
        if decisions is None:
            if template is None:
                raise _schema("a retained-key policy needs the approved template", "template")
            decisions = {
                "decision_status": template["policy"]["not_derivable_status"],
                "selected_arm_id": None,
                "candidate_statuses": {
                    arm: "INCONCLUSIVE"
                    for arm in analysis["statistics"]["arms"]
                },
                "reasons": [
                    "authentic-policy-inputs-unavailable",
                    "no-fallback-arm-selection",
                    "policy-chain-not-rerun",
                ],
                "performance_claim_allowed": False,
            }
        else:
            status = decisions["decision_status"]
            if status == DECISION_TIE_PREFERENCE and decisions.get("performance_claim_allowed"):
                raise _identity(
                    "a tie preference must never claim a speed advantage",
                    "performance_claim_allowed",
                )
    policy = {
        "kind": "official-policy-decision",
        "schema_version": 1,
        "evidence_origin": "real",
        "qualification_scope": "official",
        "subject": dict(subject),
        "study_id": study_id,
        "policy_digest": validate_digest(policy_profile_digest, "policy_profile_digest"),
        "analysis_digest": document_digest(analysis),
        "decision_status": decisions["decision_status"],
        "selected_arm_id": decisions["selected_arm_id"],
        "candidate_statuses": dict(decisions["candidate_statuses"]),
        "reasons": list(decisions["reasons"]),
        "performance_claim_allowed": bool(decisions["performance_claim_allowed"]),
    }
    return validate_official_policy(policy)


def nine_k_decisions(
    *,
    selected_arm_id: str | None,
    tie: bool,
    reasons: Sequence[str],
    candidate_statuses: Mapping[str, str],
) -> dict[str, Any]:
    """Map an authenticated frozen nine-K policy result to the official schema.

    A tie preference is distinguishable from a proven speed advantage: a tie never
    permits a performance claim.
    """

    if tie:
        status = DECISION_TIE_PREFERENCE
    elif selected_arm_id is not None:
        status = DECISION_SELECTED
    else:  # pragma: no cover - caller error
        raise _identity("a nine-K decision must select an arm or record a tie", "selected_arm_id")
    return {
        "decision_status": status,
        "selected_arm_id": selected_arm_id,
        "candidate_statuses": dict(candidate_statuses),
        "reasons": list(reasons),
        "performance_claim_allowed": not tie,
    }


def require_resolved_policy(policy: Mapping[str, Any]) -> Mapping[str, Any]:
    """Reject an underivable policy before acceptance/attestation."""

    from .contracts import UNRESOLVED_DECISIONS

    status = policy.get("decision_status")
    if status in UNRESOLVED_DECISIONS:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            f"the official policy is {status}; gate D/E cannot pass",
            field_path="policy_decision_status",
        )
    return policy


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze_official_study(
    *,
    admitted: AdmittedCrossEngine | AdmittedRetainedKey,
    template: Mapping[str, Any],
    policy_inputs: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dispatch the frozen per-family Gate B analysis."""

    if isinstance(admitted, AdmittedCrossEngine):
        if policy_inputs is not None:
            raise BenchError(BM_UNSAFE_INPUT, "retained policy inputs cannot be supplied to cross-engine analysis")
        return analyze_cross_engine_real(
            admitted=admitted, template=template, control=admitted.control
        )
    if isinstance(admitted, AdmittedRetainedKey):
        return analyze_retained_key_real(admitted=admitted, template=template, policy_inputs=policy_inputs)
    raise BenchError(BM_UNSAFE_INPUT, "admitted evidence has an unknown family")


def analysis_digest(document: Mapping[str, Any]) -> str:
    """Return the canonical digest of an official analysis record."""

    return document_digest(validate_official_analysis(dict(document)))


def policy_digest(document: Mapping[str, Any]) -> str:
    """Return the canonical digest of an official policy record."""

    return document_digest(validate_official_policy(dict(document)))


__all__ = [
    "ARM_LABELS",
    "CROSS_ENGINE_DISPERSION_LIMIT",
    "OFFICIAL_ARMS",
    "LANE_ANALYZED",
    "LANE_INSUFFICIENT",
    "analysis_digest",
    "analyze_cross_engine_real",
    "analyze_official_study",
    "analyze_retained_key_real",
    "derive_official_policy",
    "dispersion",
    "exact_ratio",
    "lower_median",
    "nearest_rank",
    "nine_k_decisions",
    "policy_digest",
    "policy_profile_digest",
    "require_resolved_policy",
    "retained_block_indices",
    "retained_key_block_medians",
    "within_arm_cap",
]
