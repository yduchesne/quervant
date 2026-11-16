"""The single high-level BM-04 derivation entry point.

``analyze_synthetic_run`` is importable Python, not a CLI verb. It reads four
read-only inputs, re-verifies the sealed system: synthetic run structurally,
reconstructs every treatment slot exactly once, computes raw and retained paired
estimates, the symmetric exclusion ledger, the deterministic bootstrap interval and
the frozen policy decision, then re-verifies every consumed byte before returning
two canonical in-memory documents.

It never writes a file, creates a directory, starts a process, reads a wall clock,
opens a socket or invokes an adapter, and it never issues a Gate A-E receipt or a
performance verdict.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..config.codec import content_digest
from ..config.contracts import ExperimentBundle
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_NOT_IMPLEMENTED,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..evidence.paths import require_safe_root
from ..execution.replay import VERIFIED_STATUS, replay_sealed_synthetic
from ..execution.store import SEAL_NAME
from ..execution.recorder import validate_seal_document
from .aggregation import (
    TreatmentSamples,
    read_treatment_samples,
    require_synthetic_scope,
    scenario_digest_of,
    verify_consumed_files,
)
from .arithmetic import (
    compute_paired_effect,
    normalized_effect,
    raw_ratio,
)
from .bootstrap import bootstrap_interval
from .contracts import (
    ANALYSIS_KIND,
    LANE_STATUS_ANALYZED,
    LANE_STATUS_INSUFFICIENT,
    MAX_ANALYSIS_RECORDS,
    AnalysisCampaign,
    AnalysisLaneRow,
    AnalysisResult,
    BlockEffect,
    CandidateLaneEstimate,
    ExclusionLedger,
    quantize_effect,
    require_bounded_document,
    validate_analysis_result,
    validate_policy_decision,
)
from .policy import (
    evaluate_policy,
    read_policy_profile,
    read_resource_observations,
)
from .pruning import apply_lane_block_exclusions, arm_block_values
from .profiles import read_analysis_profile, require_minimum_retained
from .policy import PolicyProfile
from .profiles import AnalysisProfile

_MAX_SEAL_BYTES = 1_048_576


def _fail(message: str, field_path: str | None = None) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _require_path(value: object, field_path: str) -> Path:
    if not isinstance(value, Path):
        raise BenchError(
            BM_UNSAFE_INPUT, f"{field_path} must be a Path", field_path=field_path
        )
    return value


def _within(candidate: Path, container: Path) -> bool:
    return candidate == container or container in candidate.parents


def _require_disjoint_roots(run_dir: Path, other: Path, label: str) -> None:
    if _within(other, run_dir) or _within(run_dir, other):
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{label} must be disjoint from the sealed run directory",
            field_path=label,
        )


def _read_seal_bytes(run_dir: Path) -> bytes:
    from ..evidence.paths import open_regular_beneath

    handle = open_regular_beneath(run_dir, SEAL_NAME)
    with handle:
        payload = handle.read(_MAX_SEAL_BYTES + 1)
    if len(payload) > _MAX_SEAL_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "seal.json exceeds the canonical record budget",
            reference=SEAL_NAME,
        )
    return payload


def _raw_digest(payload: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def derive_lane_estimates(
    *,
    block_slot_medians: dict[int, dict[str, list[Decimal]]],
    analysis_profile: AnalysisProfile,
    campaign_index: int,
    lane_id: str,
    baseline_arm_id: str,
    candidate_ids: Sequence[str],
    direction: str,
    protocol_digest: str,
    minimum_retained: int,
) -> tuple[ExclusionLedger, tuple[CandidateLaneEstimate, ...]]:
    """Derive one campaign/lane ledger plus every candidate estimate.

    Raw estimates are always computed over **all** scheduled blocks before any
    exclusion is applied. The retained estimate and its interval are produced only
    when at least ``minimum_retained`` blocks survive the symmetric ledger; an
    insufficient lane keeps its raw point estimate, its ledger and a JSON ``null``
    retained effect/CI instead of a fabricated interval.
    """

    ledger = apply_lane_block_exclusions(block_slot_medians, analysis_profile, lane_id)
    block_values = arm_block_values(block_slot_medians)
    blocks = sorted(block_values)
    candidates: list[CandidateLaneEstimate] = []
    for candidate_id in candidate_ids:
        rows_all = [
            (
                block,
                block_values[block][baseline_arm_id],
                block_values[block][candidate_id],
            )
            for block in blocks
        ]
        raw_effects = tuple(
            BlockEffect(
                block=block,
                normalized_effect=normalized_effect(
                    candidate_value, baseline_value, direction
                ),
                raw_candidate_over_baseline=raw_ratio(candidate_value, baseline_value),
            )
            for block, baseline_value, candidate_value in rows_all
        )
        raw_point = quantize_effect(
            compute_paired_effect(rows_all, direction, analysis_profile.estimator_id)
        )
        retained_rows = tuple(row for row in rows_all if row[0] in ledger.retained_blocks)
        if len(retained_rows) >= minimum_retained:
            interval = bootstrap_interval(
                retained_rows,
                seed=analysis_profile.bootstrap.seed,
                protocol_digest=protocol_digest,
                campaign_index=campaign_index,
                lane_id=lane_id,
                candidate_id=candidate_id,
                baseline_id=baseline_arm_id,
                estimator_id=analysis_profile.estimator_id,
                resamples=analysis_profile.bootstrap.resamples,
                confidence_basis_points=(
                    analysis_profile.bootstrap.confidence_basis_points
                ),
                direction=direction,
            )
            candidates.append(
                CandidateLaneEstimate(
                    candidate_arm_id=candidate_id,
                    comparison_direction=direction,
                    raw_point_effect=raw_point,
                    retained_point_effect=quantize_effect(
                        compute_paired_effect(
                            retained_rows, direction, analysis_profile.estimator_id
                        )
                    ),
                    ci_low=interval.low,
                    ci_high=interval.high,
                    bootstrap_stream_digest=interval.stream_digest,
                    status=LANE_STATUS_ANALYZED,
                    raw_block_effects=raw_effects,
                    retained_block_effects=tuple(
                        effect
                        for effect in raw_effects
                        if effect.block in ledger.retained_blocks
                    ),
                )
            )
        else:
            candidates.append(
                CandidateLaneEstimate(
                    candidate_arm_id=candidate_id,
                    comparison_direction=direction,
                    raw_point_effect=raw_point,
                    retained_point_effect=None,
                    ci_low=None,
                    ci_high=None,
                    bootstrap_stream_digest=None,
                    status=LANE_STATUS_INSUFFICIENT,
                    raw_block_effects=raw_effects,
                    retained_block_effects=(),
                )
            )
    return ledger, tuple(candidates)


def _build_campaigns(
    *,
    bundle: ExperimentBundle,
    samples: TreatmentSamples,
    analysis_profile: AnalysisProfile,
    direction: str,
    minimum_retained: int,
    baseline_arm_id: str,
    candidate_ids: tuple[str, ...],
) -> tuple[AnalysisCampaign, ...]:
    board = samples.block_slot_samples()
    campaigns: list[AnalysisCampaign] = []
    for campaign_index in samples.campaign_indices:
        lanes_rows: list[AnalysisLaneRow] = []
        for lane_id in samples.lane_ids:
            per_block = board[campaign_index][lane_id]
            block_slot_medians: dict[int, dict[str, list[Decimal]]] = {}
            for block in sorted(per_block):
                block_slot_medians[block] = {
                    arm_id: [_slot_median(values) for values in vectors]
                    for arm_id, vectors in per_block[block].items()
                }
            ledger, candidates = derive_lane_estimates(
                block_slot_medians=block_slot_medians,
                analysis_profile=analysis_profile,
                campaign_index=campaign_index,
                lane_id=lane_id,
                baseline_arm_id=baseline_arm_id,
                candidate_ids=candidate_ids,
                direction=direction,
                protocol_digest=bundle.protocol_digest,
                minimum_retained=minimum_retained,
            )
            lanes_rows.append(
                AnalysisLaneRow(
                    lane_id=lane_id,
                    blocks_total=len(block_slot_medians),
                    ledger=ledger,
                    candidates=candidates,
                )
            )
        campaigns.append(
            AnalysisCampaign(campaign_index=campaign_index, lanes=tuple(lanes_rows))
        )
    return tuple(campaigns)


def _slot_median(values: Sequence[int]) -> Decimal:
    from .arithmetic import slot_median

    return slot_median(values)


def _require_baseline_arm(
    bundle: ExperimentBundle, baseline_arm_id: str
) -> str:
    """Return the frozen policy baseline after a fail-closed membership check."""

    arms = tuple(arm.arm_id for arm in bundle.experiment.arms)
    if len(arms) < 2:
        raise _fail(
            "a paired analysis requires a baseline and at least one candidate arm",
            "arms",
        )
    if baseline_arm_id not in arms:
        raise _fail(
            "the frozen policy baseline must be a declared experiment arm",
            "baseline_arm_id",
        )
    return baseline_arm_id


def _require_candidate_ids(
    bundle: ExperimentBundle, baseline_arm_id: str
) -> tuple[str, ...]:
    candidate_ids = _candidate_ids(bundle, baseline_arm_id)
    if not candidate_ids:
        raise _fail(
            "a paired analysis requires at least one candidate arm", "candidate_ids"
        )
    return candidate_ids


def _candidate_ids(bundle: ExperimentBundle, baseline_arm_id: str) -> tuple[str, ...]:
    return tuple(
        arm.arm_id for arm in bundle.experiment.arms if arm.arm_id != baseline_arm_id
    )


def analyze_synthetic_run(
    *,
    bundle: ExperimentBundle,
    run_dir: Path,
    scenario_root: Path,
    profiles_root: Path,
    resources_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive the canonical analysis and policy documents for one sealed run.

    The order below is normative (§11): validate roots and scope, freeze the
    profiles, replay the seal, reconstruct the samples, compute, re-verify every
    consumed byte, then return two canonical in-memory documents.
    """

    # 1. Types, roots and scope — nothing is opened before the scope check.
    if not isinstance(bundle, ExperimentBundle):
        raise _fail("a validated ExperimentBundle is required", "bundle")
    target_run = _require_path(run_dir, "run_dir")
    scenario = _require_path(scenario_root, "scenario_root")
    profiles = _require_path(profiles_root, "profiles_root")
    resources_root_path = _require_path(resources_root, "resources_root")
    for root, label in (
        (target_run, "run_dir"),
        (scenario, "scenario_root"),
        (profiles, "profiles_root"),
        (resources_root_path, "resources_root"),
    ):
        require_safe_root(root)
        if label != "run_dir":
            _require_disjoint_roots(target_run, root, label)
    require_synthetic_scope(bundle)
    _require_synthetic_measurement(bundle)

    # 2. Freeze the independent profiles and resource observations.
    analysis_profile = read_analysis_profile(profiles, bundle)
    policy_profile = read_policy_profile(profiles, bundle)
    observations = read_resource_observations(resources_root_path, bundle)
    _require_policy_direction(policy_profile, analysis_profile, bundle)
    # The frozen, validated policy baseline is the single authority for every
    # comparison and output identity. There is no first-arm or lexical fallback.
    baseline_arm_id = _require_baseline_arm(bundle, policy_profile.baseline_arm_id)
    candidate_ids = _require_candidate_ids(bundle, baseline_arm_id)
    minimum_retained = require_minimum_retained(analysis_profile, bundle)
    scenario_digest = scenario_digest_of(scenario, bundle)

    # 3. Mandatory first integrity gate.
    replay = replay_sealed_synthetic(
        target_run, bundle=bundle, scenario_root=scenario
    )
    if replay.status != VERIFIED_STATUS:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the sealed run did not pass structural replay",
            field_path="evidence",
        )

    # 4. Read the canonical seal and reconstruct every treatment slot once.
    seal_payload = _read_seal_bytes(target_run)
    seal_digest = _raw_digest(seal_payload)
    from ..config.codec import canonical_document_bytes, decode_text, loads_json

    seal_document = loads_json(decode_text(seal_payload))
    if canonical_document_bytes(seal_document) != seal_payload:
        raise _fail("seal.json is not stored in canonical byte form", "seal")
    seal = validate_seal_document(seal_document)
    if seal.scenario_digest != scenario_digest:
        raise _fail("the seal scenario digest does not match the declared scenario", "seal")
    if seal.experiment_id != bundle.experiment.experiment_id:
        raise _fail("the seal experiment identity does not match the declared bundle", "seal")
    samples = read_treatment_samples(
        run_dir=target_run, bundle=bundle, seal_document=seal_document
    )

    # 5. Compute every raw estimate before exclusions, then the retained estimate.
    direction = bundle.adapter.measurement_envelope.direction
    campaigns = _build_campaigns(
        bundle=bundle,
        samples=samples,
        analysis_profile=analysis_profile,
        direction=direction,
        minimum_retained=minimum_retained,
        baseline_arm_id=baseline_arm_id,
        candidate_ids=candidate_ids,
    )
    result = AnalysisResult(
        experiment_id=bundle.experiment.experiment_id,
        run_id=seal.run_id,
        source_seal_digest=seal_digest,
        freeze_digest=seal.freeze_digest,
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
        lane_ids=tuple(lane.lane_id for lane in bundle.workload.lanes),
        campaigns=campaigns,
    )
    record_count = result.record_count()
    if record_count > MAX_ANALYSIS_RECORDS:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"the analysis would emit {record_count} records, above the "
            f"{MAX_ANALYSIS_RECORDS} budget",
            field_path="analysis",
        )
    analysis_document = result.to_document()
    validate_analysis_result(
        analysis_document, bundle, analysis_profile, seal_digest
    )
    analysis_digest = content_digest(analysis_document)

    decision = evaluate_policy(
        analysis_document,
        policy_profile,
        observations,
        minimum_retained_blocks=minimum_retained,
    )
    policy_document = decision.to_document(
        experiment_id=bundle.experiment.experiment_id,
        run_id=seal.run_id,
        analysis_digest=analysis_digest,
        policy_profile=policy_profile,
        resource_digest=observations.digest,
    )
    validate_policy_decision(
        policy_document,
        bundle,
        policy_profile,
        analysis_digest,
        observations.digest,
    )

    # 6. End-of-derivation integrity: reopen every consumed byte, replay again.
    require_bounded_document(analysis_document, ANALYSIS_KIND)
    require_bounded_document(policy_document, "synthetic-policy-decision")
    verify_consumed_files(target_run, samples.consumed)
    reseal_payload = _read_seal_bytes(target_run)
    if _raw_digest(reseal_payload) != seal_digest:
        raise _fail("seal.json changed during derivation", "seal")
    if (
        validate_seal_document(loads_json(decode_text(reseal_payload))).freeze_digest
        != seal.freeze_digest
    ):
        raise _fail("the seal freeze digest changed during derivation", "seal")
    second_replay = replay_sealed_synthetic(
        target_run, bundle=bundle, scenario_root=scenario
    )
    if second_replay.status != VERIFIED_STATUS:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the sealed run no longer passes structural replay",
            field_path="evidence",
        )
    if read_analysis_profile(profiles, bundle).digest != analysis_profile.digest:
        raise _fail("the analysis profile changed during derivation", "analysis_profile")
    if read_policy_profile(profiles, bundle).digest != policy_profile.digest:
        raise _fail("the policy profile changed during derivation", "policy_profile")
    if read_resource_observations(resources_root_path, bundle).digest != observations.digest:
        raise _fail("the resource observations changed during derivation", "resources")
    if scenario_digest_of(scenario, bundle) != scenario_digest:
        raise _fail("the scenario fixture changed during derivation", "scenario")

    return analysis_document, policy_document


def _require_synthetic_measurement(bundle: ExperimentBundle) -> None:
    """Reject an unsupported envelope before any computation."""

    envelope = bundle.adapter.measurement_envelope
    if envelope.unit != "nanoseconds" or envelope.direction != "lower-is-better":
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            "BM-04 derivation supports the synthetic lower-is-better nanosecond "
            "envelope only; higher-is-better is exercised by pure math tests",
            field_path="adapter.measurement_envelope",
        )


def _require_policy_direction(
    policy_profile: PolicyProfile,
    analysis_profile: AnalysisProfile,
    bundle: ExperimentBundle,
) -> None:
    direction = bundle.adapter.measurement_envelope.direction
    if policy_profile.metric_direction != direction:
        raise _fail(
            "the policy profile metric direction must match the adapter envelope",
            "metric_direction",
        )
    del analysis_profile


__all__ = ["analyze_synthetic_run", "derive_lane_estimates"]
