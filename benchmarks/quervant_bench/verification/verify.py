"""Bounded orchestration of the independent BM-05 synthetic verifier.

``verify_synthetic_run`` is the only public entry point. It admits a validated
synthetic bundle, a sealed BM-03 run, the frozen profile/resource roots and two
supplied BM-04 documents, then independently recomputes every material statistic
and policy decision from the sealed treatment records.

The result is an in-memory :class:`VerificationAssessment`. There is no write,
repair, timer, adapter launch, receipt, attestation, publication or CLI verb.
Any failed check raises the existing typed ``BenchError``; a partial success is
not representable.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..analysis.contracts import (
    require_bounded_document,
    validate_analysis_result,
    validate_policy_decision,
)
from ..analysis.policy import read_policy_profile, read_resource_observations
from ..analysis.profiles import read_analysis_profile
from ..config.codec import canonical_document_bytes, content_digest
from ..config.contracts import ExperimentBundle
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_UNSUPPORTED,
    BenchError,
)
from ..execution.replay import VERIFIED_STATUS, replay_sealed_synthetic
from ..protocol.controls import read_protocol_campaigns
from .contracts import (
    BOOTSTRAP_ALGORITHM,
    BOOTSTRAP_INTERVAL_ID,
    CHECK_IDS,
    CONFIDENCE_BASIS_POINTS,
    EVIDENCE_ORIGIN,
    EXCLUSION_RULESET,
    FILTER_SENSITIVITY_ACTION,
    MAX_RESAMPLES,
    MIN_RESAMPLES,
    OUTPUT_DECIMAL_PLACES,
    QUALIFICATION_SCOPE,
    REFERENCE_ID,
    SLOT_AGGREGATOR,
    BLOCK_AGGREGATOR,
    VERIFICATION_STATUS,
    VerificationAssessment,
)
from .reference_bootstrap import compute_interval, ensure_draw_budget
from .reference_input import (
    ReferenceEvidence,
    collect_reference_evidence,
    require_disjoint_roots,
    require_lower_is_better_nanoseconds,
    require_synthetic_evidence_scope,
    scenario_digest,
    verify_consumed_files,
    verify_seal_unchanged,
)
from .reference_math import (
    CampaignStatistics,
    build_analysis_document,
    compare_statistics,
    compute_statistics,
)
from .reference_policy import evaluate_reference_policy


def _identity(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _require_mapping(value: object, field_path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BenchError(
            BM_SCHEMA_INVALID, f"{field_path} must be a JSON object", field_path=field_path
        )
    return value


def _require_equal(actual: object, expected: object, field_path: str) -> None:
    if type(actual) is not type(expected) or actual != expected:
        raise _identity(
            f"{field_path} does not match the independently derived value "
            f"(expected {expected!r}, found {actual!r})",
            field_path,
        )


# ---------------------------------------------------------------------------
# Profile bindings
# ---------------------------------------------------------------------------


def _assert_reference_profile_bindings(
    analysis_profile: Any, policy_profile: Any, bundle: ExperimentBundle
) -> None:
    """Assert the frozen v1 literals instead of silently accepting new semantics."""

    def unsupported(message: str, field_path: str) -> BenchError:
        return BenchError(BM_SCHEMA_UNSUPPORTED, message, field_path=field_path)

    if analysis_profile.slot_aggregator != SLOT_AGGREGATOR:
        raise unsupported(
            f"slot_aggregator must be {SLOT_AGGREGATOR!r}", "slot_aggregator"
        )
    if analysis_profile.block_aggregator != BLOCK_AGGREGATOR:
        raise unsupported(
            f"block_aggregator must be {BLOCK_AGGREGATOR!r}", "block_aggregator"
        )
    if analysis_profile.estimator_id not in {
        "median-paired-ratios-v1",
        "ratio-of-arm-medians-v1",
    }:
        raise unsupported(
            "estimator_id is not one of the two frozen v1 estimators", "estimator_id"
        )
    bootstrap = analysis_profile.bootstrap
    if bootstrap.algorithm_id != BOOTSTRAP_ALGORITHM:
        raise unsupported(
            f"bootstrap.algorithm_id must be {BOOTSTRAP_ALGORITHM!r}",
            "bootstrap.algorithm_id",
        )
    if bootstrap.interval_id != BOOTSTRAP_INTERVAL_ID:
        raise unsupported(
            f"bootstrap.interval_id must be {BOOTSTRAP_INTERVAL_ID!r}",
            "bootstrap.interval_id",
        )
    if bootstrap.confidence_basis_points != CONFIDENCE_BASIS_POINTS:
        raise unsupported(
            f"bootstrap.confidence_basis_points must be {CONFIDENCE_BASIS_POINTS}",
            "bootstrap.confidence_basis_points",
        )
    if not MIN_RESAMPLES <= bootstrap.resamples <= MAX_RESAMPLES:
        raise unsupported(
            f"bootstrap.resamples must be in [{MIN_RESAMPLES}, {MAX_RESAMPLES}]",
            "bootstrap.resamples",
        )
    if isinstance(bootstrap.seed, bool) or not isinstance(bootstrap.seed, int):
        raise _identity("bootstrap.seed must be an integer", "bootstrap.seed")
    if not 0 <= bootstrap.seed <= 2**64 - 1:
        raise _identity(
            "bootstrap.seed must be an unsigned 64-bit integer", "bootstrap.seed"
        )
    exclusion = analysis_profile.exclusion
    if exclusion.ruleset_id != EXCLUSION_RULESET:
        raise unsupported(
            f"exclusion.ruleset_id must be {EXCLUSION_RULESET!r}",
            "exclusion.ruleset_id",
        )
    if exclusion.symmetric_by_lane_and_block is not True:
        raise _identity(
            "exclusion.symmetric_by_lane_and_block must be true",
            "exclusion.symmetric_by_lane_and_block",
        )
    if analysis_profile.output_precision_decimal_places != OUTPUT_DECIMAL_PLACES:
        raise unsupported(
            f"output_precision_decimal_places must be {OUTPUT_DECIMAL_PLACES}",
            "output_precision_decimal_places",
        )
    if policy_profile.selection.filter_sensitivity_action != FILTER_SENSITIVITY_ACTION:
        raise unsupported(
            "selection.filter_sensitivity_action must be 'inconclusive'",
            "selection.filter_sensitivity_action",
        )
    if policy_profile.metric_direction != bundle.adapter.measurement_envelope.direction:
        raise _identity(
            "the policy metric direction must match the adapter envelope",
            "metric_direction",
        )


def _candidate_order(bundle: ExperimentBundle, baseline_arm_id: str) -> tuple[str, ...]:
    declared = tuple(arm.arm_id for arm in bundle.experiment.arms)
    if baseline_arm_id not in declared:
        raise _identity(
            "the frozen policy baseline must be a declared experiment arm",
            "baseline_arm_id",
        )
    candidates = tuple(
        arm_id for arm_id in declared if arm_id != baseline_arm_id
    )
    if not candidates:
        raise _identity(
            "a paired verification requires at least one candidate arm",
            "candidate_ids",
        )
    return candidates


# ---------------------------------------------------------------------------
# Deterministic first-difference comparison
# ---------------------------------------------------------------------------


def _first_difference(
    expected: object, actual: object, path: str
) -> tuple[str, object, object] | None:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        expected_keys = set(expected)
        actual_keys = set(actual)
        missing = sorted(expected_keys - actual_keys)
        if missing:
            return (
                f"{path}.{missing[0]}" if path else missing[0],
                "<required>",
                "<missing>",
            )
        extra = sorted(actual_keys - expected_keys)
        if extra:
            return (
                f"{path}.{extra[0]}" if path else extra[0],
                "<unexpected>",
                "<present>",
            )
        for key in sorted(expected_keys):
            child = f"{path}.{key}" if path else str(key)
            difference = _first_difference(expected[key], actual[key], child)
            if difference is not None:
                return difference
        return None
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return (f"{path}.length", len(expected), len(actual))
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            difference = _first_difference(left, right, f"{path}[{index}]")
            if difference is not None:
                return difference
        return None
    if type(expected) is not type(actual):
        return (path, expected, actual)
    if expected != actual:
        return (path, expected, actual)
    return None


def _require_no_difference(
    expected: Mapping[str, Any], actual: Mapping[str, Any], label: str
) -> None:
    difference = _first_difference(expected, actual, label)
    if difference is not None:
        field_path, expected_value, actual_value = difference
        raise _identity(
            f"{label} does not match the independently reconstructed document at "
            f"{field_path} (expected {expected_value!r}, found {actual_value!r})",
            field_path,
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def verify_synthetic_run(
    *,
    bundle: ExperimentBundle,
    run_dir: Path,
    scenario_root: Path,
    profiles_root: Path,
    resources_root: Path,
    analysis_document: Mapping[str, Any],
    policy_document: Mapping[str, Any],
) -> VerificationAssessment:
    """Independently verify one synthetic BM-04 analysis/policy result pair."""

    # VC-01 — types, safe disjoint roots and synthetic/simulated scope only.
    if not isinstance(bundle, ExperimentBundle):
        raise _identity("a validated ExperimentBundle is required", "bundle")
    require_disjoint_roots(
        run_dir=run_dir,
        scenario_root=scenario_root,
        profiles_root=profiles_root,
        resources_root=resources_root,
    )
    supplied_analysis = _require_mapping(analysis_document, "analysis")
    supplied_policy = _require_mapping(policy_document, "policy")
    require_synthetic_evidence_scope(bundle)
    require_lower_is_better_nanoseconds(bundle)

    # VC-02 — frozen profiles, resources and declared identities.
    analysis_profile = read_analysis_profile(profiles_root, bundle)
    policy_profile = read_policy_profile(profiles_root, bundle)
    observations = read_resource_observations(resources_root, bundle)
    _assert_reference_profile_bindings(analysis_profile, policy_profile, bundle)
    baseline_arm_id = policy_profile.baseline_arm_id
    candidate_ids = _candidate_order(bundle, baseline_arm_id)
    if tuple(policy_profile.candidate_order) != candidate_ids:
        raise _identity(
            "the frozen policy candidate order must be every declared non-baseline "
            "arm in experiment order",
            "candidate_order",
        )
    lane_ids = tuple(lane.lane_id for lane in bundle.workload.lanes)
    minimum_retained = max(int(analysis_profile.exclusion.minimum_retained_blocks), 2)
    declarations = read_protocol_campaigns(bundle)
    comparisons = (
        len(candidate_ids) * len(lane_ids) * declarations.required_treatments
    )
    ensure_draw_budget(
        resamples=analysis_profile.bootstrap.resamples,
        blocks=bundle.protocol.schedule.blocks,
        comparisons=comparisons,
    )

    # VC-03 — mandatory structural admission gate.
    initial_scenario_digest = scenario_digest(scenario_root, bundle)
    replay = replay_sealed_synthetic(
        run_dir, bundle=bundle, scenario_root=scenario_root
    )
    if replay.status != VERIFIED_STATUS:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the sealed run did not pass structural replay",
            field_path="evidence",
        )

    # VC-04 — independent seal + treatment inventory.
    evidence = collect_reference_evidence(
        bundle=bundle,
        run_dir=run_dir,
        scenario_root=scenario_root,
    )
    if evidence.run_id != replay.run_id:
        raise _identity(
            "the seal run identity does not match the replayed run", "run_id"
        )
    if evidence.scenario_digest != initial_scenario_digest:
        raise _identity(
            "the seal scenario digest does not match the declared scenario",
            "scenario_digest",
        )

    # VC-05 — first-line structural validation plus independent statistics.
    validate_analysis_result(
        supplied_analysis, bundle, analysis_profile, evidence.seal_digest
    )
    statistics = compute_statistics(
        campaign_indices=evidence.campaign_indices,
        lane_ids=evidence.lane_ids,
        slots=evidence.slots,
        arms=evidence.arms,
        samples=evidence.samples,
        baseline_arm_id=baseline_arm_id,
        candidate_ids=candidate_ids,
        direction=bundle.adapter.measurement_envelope.direction,
        caps={
            lane_id: analysis_profile.exclusion.cap_for(lane_id)
            for lane_id in lane_ids
        },
        blocks_total=bundle.protocol.schedule.blocks,
        minimum_retained=minimum_retained,
        estimator_id=analysis_profile.estimator_id,
    )
    compare_statistics(supplied_analysis, statistics)

    # VC-06 — independent bootstrap intervals and full analysis reconstruction.
    intervals = _bootstrap_intervals(
        statistics=statistics,
        evidence=evidence,
        bundle=bundle,
        analysis_profile=analysis_profile,
        baseline_arm_id=baseline_arm_id,
    )
    expected_analysis = build_analysis_document(
        experiment_id=bundle.experiment.experiment_id,
        run_id=evidence.run_id,
        source_seal_digest=evidence.seal_digest,
        freeze_digest=evidence.freeze_digest,
        protocol_digest=bundle.protocol_digest,
        analysis_profile_digest=analysis_profile.digest,
        analysis_id=analysis_profile.analysis_id,
        analysis_version=analysis_profile.analysis_version,
        estimator_id=analysis_profile.estimator_id,
        algorithm_id=analysis_profile.bootstrap.algorithm_id,
        confidence_basis_points=analysis_profile.bootstrap.confidence_basis_points,
        resamples=analysis_profile.bootstrap.resamples,
        seed=analysis_profile.bootstrap.seed,
        baseline_arm_id=baseline_arm_id,
        candidate_ids=candidate_ids,
        lane_ids=lane_ids,
        direction=bundle.adapter.measurement_envelope.direction,
        campaigns=statistics,
        intervals=intervals,
    )
    _require_no_difference(expected_analysis, supplied_analysis, "analysis")

    # VC-07 — independent policy reconstruction and full comparison.
    analysis_digest = content_digest(supplied_analysis)
    validate_policy_decision(
        supplied_policy,
        bundle,
        policy_profile,
        analysis_digest,
        observations.digest,
    )
    expected_policy = evaluate_reference_policy(
        analysis_document=expected_analysis,
        policy_profile=policy_profile,
        observations=observations,
        minimum_retained=minimum_retained,
        experiment_id=bundle.experiment.experiment_id,
        run_id=evidence.run_id,
        analysis_digest=analysis_digest,
    )
    _require_no_difference(expected_policy, supplied_policy, "policy")

    # VC-08 — source-derived identity and canonical output budgets.
    require_bounded_document(supplied_analysis, "analysis")
    require_bounded_document(supplied_policy, "policy")
    canonical_document_bytes(supplied_analysis)
    canonical_document_bytes(supplied_policy)
    _require_equal(
        supplied_analysis.get("experiment_id"),
        bundle.experiment.experiment_id,
        "analysis.experiment_id",
    )
    _require_equal(supplied_analysis.get("run_id"), evidence.run_id, "analysis.run_id")
    _require_equal(
        supplied_analysis.get("source_seal_digest"),
        evidence.seal_digest,
        "analysis.source_seal_digest",
    )
    _require_equal(
        supplied_analysis.get("freeze_digest"),
        evidence.freeze_digest,
        "analysis.freeze_digest",
    )
    _require_equal(
        supplied_analysis.get("protocol_digest"),
        bundle.protocol_digest,
        "analysis.protocol_digest",
    )
    _require_equal(
        supplied_analysis.get("analysis_profile_digest"),
        analysis_profile.digest,
        "analysis.analysis_profile_digest",
    )
    _require_equal(
        supplied_analysis.get("baseline_arm_id"),
        baseline_arm_id,
        "analysis.baseline_arm_id",
    )
    _require_equal(
        supplied_analysis.get("candidate_ids"),
        list(candidate_ids),
        "analysis.candidate_ids",
    )
    _require_equal(
        supplied_analysis.get("lane_ids"),
        list(lane_ids),
        "analysis.lane_ids",
    )
    policy_digest = content_digest(supplied_policy)
    _require_equal(
        supplied_policy.get("analysis_digest"),
        analysis_digest,
        "policy.analysis_digest",
    )
    _require_equal(
        supplied_policy.get("experiment_id"),
        bundle.experiment.experiment_id,
        "policy.experiment_id",
    )
    _require_equal(supplied_policy.get("run_id"), evidence.run_id, "policy.run_id")
    _require_equal(
        supplied_policy.get("policy_profile_digest"),
        policy_profile.digest,
        "policy.policy_profile_digest",
    )
    _require_equal(
        supplied_policy.get("resource_observations_digest"),
        observations.digest,
        "policy.resource_observations_digest",
    )
    _require_equal(
        supplied_policy.get("baseline_arm_id"),
        baseline_arm_id,
        "policy.baseline_arm_id",
    )

    # VC-09 — post-read byte integrity, second replay and unchanged profiles.
    verify_consumed_files(run_dir, evidence.consumed)
    verify_seal_unchanged(run_dir, evidence.seal_bytes)
    if read_analysis_profile(profiles_root, bundle).digest != analysis_profile.digest:
        raise _identity(
            "the analysis profile changed during verification", "analysis_profile"
        )
    if read_policy_profile(profiles_root, bundle).digest != policy_profile.digest:
        raise _identity(
            "the policy profile changed during verification", "policy_profile"
        )
    if read_resource_observations(resources_root, bundle).digest != observations.digest:
        raise _identity(
            "the resource observations changed during verification", "resources"
        )
    if scenario_digest(scenario_root, bundle) != initial_scenario_digest:
        raise _identity(
            "the declared scenario changed during verification", "scenario"
        )
    second_replay = replay_sealed_synthetic(
        run_dir, bundle=bundle, scenario_root=scenario_root
    )
    if second_replay.status != VERIFIED_STATUS:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the sealed run no longer passes structural replay",
            field_path="evidence",
        )

    return VerificationAssessment(
        status=VERIFICATION_STATUS,
        experiment_id=bundle.experiment.experiment_id,
        run_id=evidence.run_id,
        evidence_origin=EVIDENCE_ORIGIN,
        qualification_scope=QUALIFICATION_SCOPE,
        analysis_digest=analysis_digest,
        policy_digest=policy_digest,
        source_seal_digest=evidence.seal_digest,
        reference_id=REFERENCE_ID,
        check_ids=CHECK_IDS,
    )


def _bootstrap_intervals(
    *,
    statistics: tuple[CampaignStatistics, ...],
    evidence: ReferenceEvidence,
    bundle: ExperimentBundle,
    analysis_profile: Any,
    baseline_arm_id: str,
) -> dict[tuple[int, str, str], Any]:
    direction = bundle.adapter.measurement_envelope.direction
    intervals: dict[tuple[int, str, str], Any] = {}
    for campaign in statistics:
        for lane in campaign.lanes:
            for candidate in lane.candidates:
                if candidate.retained_point is None:
                    continue
                key = (
                    campaign.campaign_index,
                    lane.lane_id,
                    candidate.candidate_arm_id,
                )
                intervals[key] = compute_interval(
                    candidate.retained_rows,
                    seed=analysis_profile.bootstrap.seed,
                    protocol_digest=bundle.protocol_digest,
                    campaign_index=campaign.campaign_index,
                    lane_id=lane.lane_id,
                    candidate_id=candidate.candidate_arm_id,
                    baseline_id=baseline_arm_id,
                    estimator_id=analysis_profile.estimator_id,
                    direction=direction,
                    resamples=analysis_profile.bootstrap.resamples,
                    confidence_basis_points=(
                        analysis_profile.bootstrap.confidence_basis_points
                    ),
                )
    return intervals


__all__ = ["verify_synthetic_run"]
