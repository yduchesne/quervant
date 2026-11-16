"""Gate coordinator: A→B→C→D→E over one sealed synthetic BM-03 run.

The coordinator owns orchestration only. Gate A is sealed structural admission,
Gate B calls the existing BM-04 derivation, Gate C calls the existing BM-05
independent verifier, Gate D validates pinned QA evidence plus the exact receipt
graph, and Gate E freezes and publishes the acyclic snapshot/attestation/manifest.

There is no CLI, no acquisition, no host readiness, no A/A cache and no persistent
success cache. All gate results are prepared in memory and exclusively published as
one immutable 15-file bundle whose ``manifest.json`` is the completion marker.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..analysis.aggregation import scenario_digest_of
from ..analysis.contracts import validate_analysis_result, validate_policy_decision
from ..analysis.derive import analyze_synthetic_run
from ..analysis.policy import read_policy_profile, read_resource_observations
from ..analysis.profiles import read_analysis_profile
from ..config.codec import content_digest
from ..config.contracts import ExperimentBundle
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_PUBLICATION_CONFLICT,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_uuid4
from ..evidence.paths import require_publication_base, require_safe_root
from ..evidence.provenance import repository_root
from ..execution.replay import VERIFIED_STATUS, replay_sealed_synthetic
from ..verification.contracts import CHECK_IDS, REFERENCE_ID, VERIFICATION_STATUS
from ..verification.verify import verify_synthetic_run
from . import admission, qa
from .contracts import (
    ACCEPTANCE_KIND,
    ASSESSMENT_KIND,
    FREEZE_MEMBERS,
    QUALIFICATION_SCOPE,
    SCHEMA_VERSION,
    QualificationResult,
    require_bundle_scope,
    subject_document,
    validate_acceptance_summary,
    validate_verification_assessment,
)
from .identity import require_anchor, verify_source_identity
from .manifest import (
    build_attestation_receipt,
    build_freeze_snapshot,
    build_manifest,
    member_record,
    verify_attestation_graph,
    verify_freeze_snapshot,
)
from .profiles import read_qualification_profile
from .publication import (
    ABSENT,
    COMMITTED,
    CommittedBundle,
    destination_state,
    load_bundle,
    publish_bundle,
)
from .receipts import build_stage_receipt, validator_identity, verify_stage_receipt

DISPOSITION_QUALIFIED = "SIMULATED_QUALIFIED"
DISPOSITION_REUSED = "REUSED_VERIFIED"

_I = "admission-index.json"
_A = "admission.json"
_AN = "analysis.json"
_P = "policy.json"
_B = "analysis-receipt.json"
_VA = "verification-assessment.json"
_C = "verification.json"
_FE = "framework-qa-evidence.json"
_F = "framework-qa.json"
_SE = "source-qa-evidence.json"
_S = "source-qa.json"
_AS = "acceptance-summary.json"
_D = "acceptance.json"
_E = "attestation.json"
_M = "manifest.json"


@dataclass(frozen=True)
class _Context:
    bundle: ExperimentBundle
    run_dir: Path
    scenario_root: Path
    profiles_root: Path
    resources_root: Path
    qa_evidence_root: Path
    source_root: Path
    output_base: Path
    qualification_profile_path: Path
    experiment_id: str
    run_id: str
    profile: dict[str, Any]
    profile_digest: str
    source_set_digest: str
    framework_qa_digest: str
    source_qa_digest: str

    @property
    def subject(self) -> dict[str, str]:
        return subject_document(self.bundle, self.run_id)


def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def _require_path(value: object, field: str) -> Path:
    if not isinstance(value, Path):
        raise BenchError(BM_UNSAFE_INPUT, f"{field} must be a Path", field_path=field)
    return value


def _require_disjoint(output: Path, roots: Sequence[tuple[Path, str]]) -> None:
    resolved_output = output.resolve()
    for root, label in roots:
        resolved_root = root.resolve()
        if (
            resolved_root == resolved_output
            or resolved_root in resolved_output.parents
            or resolved_output in resolved_root.parents
        ):
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"output_base must be disjoint from {label}",
                field_path="output_base",
            )


def _preflight(
    *,
    bundle: ExperimentBundle,
    run_dir: Path,
    scenario_root: Path,
    profiles_root: Path,
    resources_root: Path,
    qualification_profile_path: Path,
    qa_evidence_root: Path,
    expected_profile_digest: str,
    expected_framework_qa_digest: str,
    expected_source_qa_digest: str,
    source_root: Path,
    expected_source_set_digest: str,
    output_base: Path,
) -> _Context:
    """Type-, scope-, root- and anchor-check everything before any derivation."""

    if not isinstance(bundle, ExperimentBundle):
        raise BenchError(
            BM_UNSAFE_INPUT, "bundle must be an ExperimentBundle", field_path="bundle"
        )
    for value, field in (
        (run_dir, "run_dir"),
        (scenario_root, "scenario_root"),
        (profiles_root, "profiles_root"),
        (resources_root, "resources_root"),
        (qualification_profile_path, "qualification_profile_path"),
        (qa_evidence_root, "qa_evidence_root"),
        (source_root, "source_root"),
        (output_base, "output_base"),
    ):
        _require_path(value, field)
    require_bundle_scope(bundle)
    for root, label in (
        (run_dir, "run_dir"),
        (scenario_root, "scenario_root"),
        (profiles_root, "profiles_root"),
        (resources_root, "resources_root"),
        (qa_evidence_root, "qa_evidence_root"),
    ):
        require_safe_root(root)
        del label
    output = require_publication_base(output_base, repository_root())
    _require_disjoint(
        output,
        (
            (run_dir, "run_dir"),
            (scenario_root, "scenario_root"),
            (profiles_root, "profiles_root"),
            (resources_root, "resources_root"),
            (qa_evidence_root, "qa_evidence_root"),
            (qualification_profile_path.parent, "qualification profile root"),
        ),
    )
    run_id = validate_uuid4(run_dir.name, "run_id")
    experiment_id = bundle.experiment.experiment_id
    require_anchor(expected_profile_digest, "expected_profile_digest")
    require_anchor(expected_framework_qa_digest, "expected_framework_qa_digest")
    require_anchor(expected_source_qa_digest, "expected_source_qa_digest")
    source_set_digest = verify_source_identity(source_root, expected_source_set_digest)
    profile, profile_digest = read_qualification_profile(
        qualification_profile_path, expected_profile_digest
    )
    return _Context(
        bundle=bundle,
        run_dir=run_dir,
        scenario_root=scenario_root,
        profiles_root=profiles_root,
        resources_root=resources_root,
        qa_evidence_root=qa_evidence_root,
        source_root=source_root,
        output_base=output,
        qualification_profile_path=qualification_profile_path,
        experiment_id=experiment_id,
        run_id=run_id,
        profile=profile,
        profile_digest=profile_digest,
        source_set_digest=source_set_digest,
        framework_qa_digest=expected_framework_qa_digest,
        source_qa_digest=expected_source_qa_digest,
    )


def _analysis_inputs(
    *,
    index: Mapping[str, Any],
    analysis_profile: Any,
    policy_profile: Any,
    observations: Any,
    source_set_digest: str,
) -> dict[str, str]:
    return {
        "admission-index": content_digest(dict(index)),
        "analysis-profile": analysis_profile.digest,
        "policy-profile": policy_profile.digest,
        "resource-observations": observations.digest,
        "source-set": source_set_digest,
    }


def _verification_inputs(
    *,
    analysis_document: Mapping[str, Any],
    policy_document: Mapping[str, Any],
    index: Mapping[str, Any],
    source_set_digest: str,
) -> dict[str, str]:
    return {
        "analysis": content_digest(dict(analysis_document)),
        "policy": content_digest(dict(policy_document)),
        "source-seal": index["seal_raw_digest"],
        "source-set": source_set_digest,
    }


def _acceptance_inputs(
    *,
    index: Mapping[str, Any],
    analysis_document: Mapping[str, Any],
    policy_document: Mapping[str, Any],
    assessment_document: Mapping[str, Any],
    framework_evidence: Mapping[str, Any],
    source_evidence: Mapping[str, Any],
    profile_digest: str,
    source_set_digest: str,
) -> dict[str, str]:
    return {
        "admission-index": content_digest(dict(index)),
        "analysis": content_digest(dict(analysis_document)),
        "policy": content_digest(dict(policy_document)),
        "verification-assessment": content_digest(dict(assessment_document)),
        "framework-qa-evidence": content_digest(dict(framework_evidence)),
        "source-qa-evidence": content_digest(dict(source_evidence)),
        "qualification-profile": profile_digest,
        "source-set": source_set_digest,
    }


def _read_analysis_documents(
    context: _Context, index: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], Any, Any, Any]:
    analysis_document, policy_document = analyze_synthetic_run(
        bundle=context.bundle,
        run_dir=context.run_dir,
        scenario_root=context.scenario_root,
        profiles_root=context.profiles_root,
        resources_root=context.resources_root,
    )
    if not isinstance(analysis_document, Mapping) or not isinstance(
        policy_document, Mapping
    ):
        raise _fail("BM-04 derivation must return two documents", "analysis")
    analysis_profile = read_analysis_profile(context.profiles_root, context.bundle)
    policy_profile = read_policy_profile(context.profiles_root, context.bundle)
    observations = read_resource_observations(context.resources_root, context.bundle)
    validate_analysis_result(
        analysis_document, context.bundle, analysis_profile, index["seal_raw_digest"]
    )
    validate_policy_decision(
        policy_document,
        context.bundle,
        policy_profile,
        content_digest(dict(analysis_document)),
        observations.digest,
    )
    if analysis_document.get("run_id") != context.run_id:
        raise _fail("the derived analysis is not for the admitted run", "analysis.run_id")
    return (
        dict(analysis_document),
        dict(policy_document),
        analysis_profile,
        policy_profile,
        observations,
    )


def _verification_assessment(
    context: _Context,
    *,
    analysis_document: Mapping[str, Any],
    policy_document: Mapping[str, Any],
    index: Mapping[str, Any],
) -> dict[str, Any]:
    assessment = verify_synthetic_run(
        bundle=context.bundle,
        run_dir=context.run_dir,
        scenario_root=context.scenario_root,
        profiles_root=context.profiles_root,
        resources_root=context.resources_root,
        analysis_document=analysis_document,
        policy_document=policy_document,
    )
    if assessment.status != VERIFICATION_STATUS:
        raise _fail("BM-05 did not return a verified assessment", "status")
    if tuple(assessment.check_ids) != tuple(CHECK_IDS):
        raise _fail("BM-05 check ids are not the frozen registry", "check_ids")
    if tuple(CHECK_IDS) != tuple(context.profile["required_verifier_checks"]):
        raise _fail("the profile verifier registry is not the frozen registry", "profile")
    if assessment.experiment_id != context.experiment_id:
        raise _fail("the assessment experiment does not match", "experiment_id")
    if assessment.run_id != context.run_id:
        raise _fail("the assessment run does not match", "run_id")
    if assessment.analysis_digest != content_digest(dict(analysis_document)):
        raise _fail("the assessment does not bind the analysis document", "analysis_digest")
    if assessment.policy_digest != content_digest(dict(policy_document)):
        raise _fail("the assessment does not bind the policy document", "policy_digest")
    if assessment.source_seal_digest != index["seal_raw_digest"]:
        raise _fail("the assessment does not bind the sealed source", "source_seal_digest")
    if assessment.reference_id != REFERENCE_ID:
        raise _fail("the assessment reference identity is not frozen", "reference_id")
    document = {
        "kind": ASSESSMENT_KIND,
        "schema_version": SCHEMA_VERSION,
        **asdict(assessment),
    }
    document["check_ids"] = list(assessment.check_ids)
    return validate_verification_assessment(document)


def _qa_documents(
    context: _Context,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    framework, framework_digest = qa.read_qa_evidence(
        qa_evidence_root=context.qa_evidence_root,
        gate="framework-qa",
        expected_document_digest=context.framework_qa_digest,
        profile_digest=context.profile_digest,
        source_set_digest=context.source_set_digest,
    )
    source, source_digest = qa.read_qa_evidence(
        qa_evidence_root=context.qa_evidence_root,
        gate="source-qa",
        expected_document_digest=context.source_qa_digest,
        profile_digest=context.profile_digest,
        source_set_digest=context.source_set_digest,
    )
    if framework_digest != context.framework_qa_digest:
        raise _fail("framework QA evidence changed after reading", "framework-qa")
    if source_digest != context.source_qa_digest:
        raise _fail("source QA evidence changed after reading", "source-qa")
    return framework, source, framework_digest, source_digest


def _derive(context: _Context) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    """Build and verify every gate in memory; nothing is written until E passes."""

    profile_digest = context.profile_digest
    source_digest = context.source_set_digest

    index, admission_receipt = admission.build_admission(
        bundle=context.bundle,
        run_dir=context.run_dir,
        scenario_root=context.scenario_root,
        profile_digest=profile_digest,
        source_set_digest=source_digest,
    )
    if index["subject"]["run_id"] != context.run_id:
        raise _fail("the admitted run does not match the destination", "run_id")

    (
        analysis_document,
        policy_document,
        analysis_profile,
        policy_profile,
        observations,
    ) = _read_analysis_documents(context, index)
    policy_digest = content_digest(policy_document)
    analysis_receipt = build_stage_receipt(
        gate="analysis",
        subject=index["subject"],
        validator=validator_identity("analysis", source_digest),
        inputs=_analysis_inputs(
            index=index,
            analysis_profile=analysis_profile,
            policy_profile=policy_profile,
            observations=observations,
            source_set_digest=source_digest,
        ),
        dependencies=(admission_receipt,),
        outputs={
            "analysis": content_digest(analysis_document),
            "policy": policy_digest,
        },
        policy_digest=policy_digest,
    )

    assessment_document = _verification_assessment(
        context,
        analysis_document=analysis_document,
        policy_document=policy_document,
        index=index,
    )
    verification_receipt = build_stage_receipt(
        gate="verification",
        subject=index["subject"],
        validator=validator_identity("verification", source_digest),
        inputs=_verification_inputs(
            analysis_document=analysis_document,
            policy_document=policy_document,
            index=index,
            source_set_digest=source_digest,
        ),
        dependencies=(admission_receipt, analysis_receipt),
        outputs={
            "verification-assessment": content_digest(assessment_document),
        },
        policy_digest=policy_digest,
    )

    framework_evidence, source_evidence, framework_digest, source_digest_doc = (
        _qa_documents(context)
    )
    framework_receipt = qa.build_qa_receipt(
        gate="framework-qa",
        subject=index["subject"],
        evidence_document=framework_evidence,
        evidence_digest=framework_digest,
        profile_digest=profile_digest,
        source_set_digest=source_digest,
    )
    source_receipt = qa.build_qa_receipt(
        gate="source-qa",
        subject=index["subject"],
        evidence_document=source_evidence,
        evidence_digest=source_digest_doc,
        profile_digest=profile_digest,
        source_set_digest=source_digest,
    )

    acceptance_summary = {
        "kind": ACCEPTANCE_KIND,
        "schema_version": SCHEMA_VERSION,
        "subject": index["subject"],
        "evidence_origin": "synthetic",
        "qualification_scope": QUALIFICATION_SCOPE,
        "profile_digest": profile_digest,
        "source_set_digest": source_digest,
        "gate_receipt_ids": {
            "admission": admission_receipt["receipt_id"],
            "analysis": analysis_receipt["receipt_id"],
            "verification": verification_receipt["receipt_id"],
            "framework-qa": framework_receipt["receipt_id"],
            "source-qa": source_receipt["receipt_id"],
        },
        "framework_qa_evidence_digest": framework_digest,
        "source_qa_evidence_digest": source_digest_doc,
        "policy_decision_status": policy_document["decision_status"],
    }
    validate_acceptance_summary(acceptance_summary)
    acceptance_receipt = build_stage_receipt(
        gate="acceptance",
        subject=index["subject"],
        validator=validator_identity("acceptance", source_digest),
        inputs=_acceptance_inputs(
            index=index,
            analysis_document=analysis_document,
            policy_document=policy_document,
            assessment_document=assessment_document,
            framework_evidence=framework_evidence,
            source_evidence=source_evidence,
            profile_digest=profile_digest,
            source_set_digest=source_digest,
        ),
        dependencies=(
            admission_receipt,
            analysis_receipt,
            verification_receipt,
            framework_receipt,
            source_receipt,
        ),
        outputs={"acceptance-summary": content_digest(acceptance_summary)},
        profile_digest=profile_digest,
        policy_digest=policy_digest,
    )

    members: list[tuple[str, dict[str, Any]]] = [
        (_I, index),
        (_A, admission_receipt),
        (_AN, analysis_document),
        (_P, policy_document),
        (_B, analysis_receipt),
        (_VA, assessment_document),
        (_C, verification_receipt),
        (_FE, framework_evidence),
        (_F, framework_receipt),
        (_SE, source_evidence),
        (_S, source_receipt),
        (_AS, acceptance_summary),
        (_D, acceptance_receipt),
    ]
    snapshot = build_freeze_snapshot(
        subject=index["subject"],
        profile_digest=profile_digest,
        source_set_digest=source_digest,
        members=[
            member_record(name, document) for name, document in members
        ],
    )
    attestation_receipt = build_attestation_receipt(
        subject=index["subject"],
        snapshot=snapshot,
        dependencies=(
            admission_receipt,
            analysis_receipt,
            verification_receipt,
            framework_receipt,
            source_receipt,
            acceptance_receipt,
        ),
        profile_digest=profile_digest,
        policy_digest=policy_digest,
        source_set_digest=source_digest,
    )
    members.append((_E, attestation_receipt))
    manifest = build_manifest(
        subject=index["subject"],
        snapshot=snapshot,
        attestation_receipt=attestation_receipt,
        members=[member_record(name, document) for name, document in members],
        profile_digest=profile_digest,
        source_set_digest=source_digest,
    )

    _reverify_inputs(
        context,
        index=index,
        analysis_document=analysis_document,
        policy_document=policy_document,
        framework_evidence=framework_evidence,
        source_evidence=source_evidence,
    )
    return members, manifest


def _reverify_inputs(
    context: _Context,
    *,
    index: Mapping[str, Any],
    analysis_document: Mapping[str, Any],
    policy_document: Mapping[str, Any],
    framework_evidence: Mapping[str, Any],
    source_evidence: Mapping[str, Any],
) -> None:
    """Re-read every consumed dependency immediately before publication/return."""

    if verify_source_identity(context.source_root, context.source_set_digest) != (
        context.source_set_digest
    ):  # pragma: no cover - verify_source_identity raises on mismatch
        raise _fail("the source identity changed", "source-set")
    profile, profile_digest = read_qualification_profile(
        context.qualification_profile_path, context.profile_digest
    )
    del profile
    if profile_digest != context.profile_digest:
        raise _fail("the qualification profile changed", "profile")
    admission.verify_sealed_bytes(context.run_dir, index)
    replay = replay_sealed_synthetic(
        context.run_dir, bundle=context.bundle, scenario_root=context.scenario_root
    )
    if replay.status != VERIFIED_STATUS:
        raise _fail("the sealed run no longer replays", "evidence")
    framework, framework_digest = qa.read_qa_evidence(
        qa_evidence_root=context.qa_evidence_root,
        gate="framework-qa",
        expected_document_digest=context.framework_qa_digest,
        profile_digest=context.profile_digest,
        source_set_digest=context.source_set_digest,
    )
    source, source_digest = qa.read_qa_evidence(
        qa_evidence_root=context.qa_evidence_root,
        gate="source-qa",
        expected_document_digest=context.source_qa_digest,
        profile_digest=context.profile_digest,
        source_set_digest=context.source_set_digest,
    )
    if framework != framework_evidence or source != source_evidence:
        raise _fail("QA evidence changed during qualification", "qa-evidence")
    if framework_digest != context.framework_qa_digest or source_digest != (
        context.source_qa_digest
    ):
        raise _fail("QA evidence anchors changed during qualification", "qa-evidence")
    analysis_profile = read_analysis_profile(context.profiles_root, context.bundle)
    policy_profile = read_policy_profile(context.profiles_root, context.bundle)
    observations = read_resource_observations(context.resources_root, context.bundle)
    if analysis_profile.digest != analysis_document["analysis_profile_digest"]:
        raise _fail("the analysis profile changed", "analysis-profile")
    if policy_profile.digest != policy_document["policy_profile_digest"]:
        raise _fail("the policy profile changed", "policy-profile")
    if observations.digest != policy_document["resource_observations_digest"]:
        raise _fail("the resource observations changed", "resource-observations")
    if scenario_digest_of(context.scenario_root, context.bundle) != index["scenario_digest"]:
        raise _fail("the scenario fixture changed", "scenario")


def _verify_committed(context: _Context, committed: CommittedBundle) -> QualificationResult:
    """Fully re-verify a committed bundle against current anchors; never derives."""

    documents = committed.documents
    index = admission.verify_admission(
        bundle=context.bundle,
        run_dir=context.run_dir,
        scenario_root=context.scenario_root,
        index_document=documents[_I],
        receipt_document=documents[_A],
        profile_digest=context.profile_digest,
        source_set_digest=context.source_set_digest,
    )
    subject = index["subject"]
    if subject["run_id"] != context.run_id:
        raise _fail("the committed bundle is for a different run", "run_id")

    analysis_profile = read_analysis_profile(context.profiles_root, context.bundle)
    policy_profile = read_policy_profile(context.profiles_root, context.bundle)
    observations = read_resource_observations(context.resources_root, context.bundle)
    analysis_document = documents[_AN]
    policy_document = documents[_P]
    validate_analysis_result(
        analysis_document, context.bundle, analysis_profile, index["seal_raw_digest"]
    )
    validate_policy_decision(
        policy_document,
        context.bundle,
        policy_profile,
        content_digest(analysis_document),
        observations.digest,
    )
    policy_digest = content_digest(policy_document)
    verify_stage_receipt(
        documents[_B],
        gate="analysis",
        source_set_digest=context.source_set_digest,
        expected_subject=subject,
        inputs=_analysis_inputs(
            index=index,
            analysis_profile=analysis_profile,
            policy_profile=policy_profile,
            observations=observations,
            source_set_digest=context.source_set_digest,
        ),
        dependencies=(documents[_A],),
        outputs={
            "analysis": content_digest(analysis_document),
            "policy": policy_digest,
        },
        policy_digest=policy_digest,
    )

    assessment_document = validate_verification_assessment(documents[_VA])
    if assessment_document["experiment_id"] != context.experiment_id:
        raise _fail("the committed assessment experiment does not match", "experiment_id")
    if assessment_document["run_id"] != context.run_id:
        raise _fail("the committed assessment run does not match", "run_id")
    if assessment_document["analysis_digest"] != content_digest(analysis_document):
        raise _fail("the committed assessment does not bind the analysis", "analysis_digest")
    if assessment_document["policy_digest"] != policy_digest:
        raise _fail("the committed assessment does not bind the policy", "policy_digest")
    if assessment_document["source_seal_digest"] != index["seal_raw_digest"]:
        raise _fail("the committed assessment does not bind the seal", "source_seal_digest")
    verify_stage_receipt(
        documents[_C],
        gate="verification",
        source_set_digest=context.source_set_digest,
        expected_subject=subject,
        inputs=_verification_inputs(
            analysis_document=analysis_document,
            policy_document=policy_document,
            index=index,
            source_set_digest=context.source_set_digest,
        ),
        dependencies=(documents[_A], documents[_B]),
        outputs={"verification-assessment": content_digest(assessment_document)},
        policy_digest=policy_digest,
    )

    framework_evidence, framework_digest = qa.read_qa_evidence(
        qa_evidence_root=context.qa_evidence_root,
        gate="framework-qa",
        expected_document_digest=context.framework_qa_digest,
        profile_digest=context.profile_digest,
        source_set_digest=context.source_set_digest,
    )
    source_evidence, source_digest = qa.read_qa_evidence(
        qa_evidence_root=context.qa_evidence_root,
        gate="source-qa",
        expected_document_digest=context.source_qa_digest,
        profile_digest=context.profile_digest,
        source_set_digest=context.source_set_digest,
    )
    if framework_evidence != documents[_FE]:
        raise _fail("the committed framework QA evidence is not the pinned document", "framework-qa")
    if source_evidence != documents[_SE]:
        raise _fail("the committed source QA evidence is not the pinned document", "source-qa")
    qa.verify_qa_receipt(
        gate="framework-qa",
        receipt_document=documents[_F],
        subject=subject,
        evidence_document=framework_evidence,
        evidence_digest=framework_digest,
        profile_digest=context.profile_digest,
        source_set_digest=context.source_set_digest,
    )
    qa.verify_qa_receipt(
        gate="source-qa",
        receipt_document=documents[_S],
        subject=subject,
        evidence_document=source_evidence,
        evidence_digest=source_digest,
        profile_digest=context.profile_digest,
        source_set_digest=context.source_set_digest,
    )

    acceptance_summary = validate_acceptance_summary(documents[_AS])
    if acceptance_summary["subject"] != subject:
        raise _fail("the acceptance summary is for a different admitted run", "acceptance-summary.subject")
    if acceptance_summary["profile_digest"] != context.profile_digest:
        raise _fail("the acceptance summary qualification profile is stale", "acceptance-summary.profile_digest")
    if acceptance_summary["source_set_digest"] != context.source_set_digest:
        raise _fail("the acceptance summary source set is stale", "acceptance-summary.source_set_digest")
    expected_ids = {
        "admission": documents[_A]["receipt_id"],
        "analysis": documents[_B]["receipt_id"],
        "verification": documents[_C]["receipt_id"],
        "framework-qa": documents[_F]["receipt_id"],
        "source-qa": documents[_S]["receipt_id"],
    }
    if acceptance_summary["gate_receipt_ids"] != expected_ids:
        raise _fail("the acceptance summary receipt ids are not the upstream receipts", "gate_receipt_ids")
    if acceptance_summary["framework_qa_evidence_digest"] != framework_digest:
        raise _fail("the acceptance summary framework QA digest is stale", "framework-qa-evidence")
    if acceptance_summary["source_qa_evidence_digest"] != source_digest:
        raise _fail("the acceptance summary source QA digest is stale", "source-qa-evidence")
    if acceptance_summary["policy_decision_status"] != policy_document["decision_status"]:
        raise _fail("the acceptance summary policy status is not the verified policy", "policy_decision_status")
    verify_stage_receipt(
        documents[_D],
        gate="acceptance",
        source_set_digest=context.source_set_digest,
        expected_subject=subject,
        inputs=_acceptance_inputs(
            index=index,
            analysis_document=analysis_document,
            policy_document=policy_document,
            assessment_document=assessment_document,
            framework_evidence=framework_evidence,
            source_evidence=source_evidence,
            profile_digest=context.profile_digest,
            source_set_digest=context.source_set_digest,
        ),
        dependencies=(
            documents[_A],
            documents[_B],
            documents[_C],
            documents[_F],
            documents[_S],
        ),
        outputs={"acceptance-summary": content_digest(acceptance_summary)},
        profile_digest=context.profile_digest,
        policy_digest=policy_digest,
    )

    manifest = documents[_M]
    attestation_receipt = documents[_E]
    if manifest["subject"] != subject:
        raise _fail("the manifest is for a different admitted run", "manifest.subject")
    if manifest["profile_digest"] != context.profile_digest:
        raise _fail("the manifest qualification profile is stale", "manifest.profile_digest")
    if manifest["source_set_digest"] != context.source_set_digest:
        raise _fail("the manifest source set is stale", "manifest.source_set_digest")

    snapshot_digest = verify_freeze_snapshot(
        snapshot=manifest["freeze_snapshot"],
        attestation_receipt=attestation_receipt,
        documents={name: documents[name] for name in FREEZE_MEMBERS},
        subject=subject,
        profile_digest=context.profile_digest,
        source_set_digest=context.source_set_digest,
    )
    verify_attestation_graph(
        attestation_receipt=attestation_receipt,
        upstream=(
            documents[_A],
            documents[_B],
            documents[_C],
            documents[_F],
            documents[_S],
            documents[_D],
        ),
        subject=subject,
        snapshot_digest=snapshot_digest,
        profile_digest=context.profile_digest,
        policy_digest=policy_digest,
        source_set_digest=context.source_set_digest,
    )
    if manifest["attestation_digest"] != content_digest(attestation_receipt):
        raise _fail("the manifest attestation digest is not the receipt", "attestation_digest")

    _reverify_inputs(
        context,
        index=index,
        analysis_document=analysis_document,
        policy_document=policy_document,
        framework_evidence=framework_evidence,
        source_evidence=source_evidence,
    )
    return QualificationResult(
        disposition=DISPOSITION_REUSED,
        experiment_id=context.experiment_id,
        run_id=context.run_id,
        manifest_digest=committed.manifest_digest,
        attestation_receipt_id=attestation_receipt["receipt_id"],
        output_directory=committed.output_directory,
    )


def qualify_synthetic_run(
    *,
    bundle: ExperimentBundle,
    run_dir: Path,
    scenario_root: Path,
    profiles_root: Path,
    resources_root: Path,
    qualification_profile_path: Path,
    qa_evidence_root: Path,
    expected_profile_digest: str,
    expected_framework_qa_digest: str,
    expected_source_qa_digest: str,
    source_root: Path,
    expected_source_set_digest: str,
    output_base: Path,
) -> QualificationResult:
    """Qualify one sealed synthetic run or reuse an identical committed bundle."""

    context = _preflight(
        bundle=bundle,
        run_dir=run_dir,
        scenario_root=scenario_root,
        profiles_root=profiles_root,
        resources_root=resources_root,
        qualification_profile_path=qualification_profile_path,
        qa_evidence_root=qa_evidence_root,
        expected_profile_digest=expected_profile_digest,
        expected_framework_qa_digest=expected_framework_qa_digest,
        expected_source_qa_digest=expected_source_qa_digest,
        source_root=source_root,
        expected_source_set_digest=expected_source_set_digest,
        output_base=output_base,
    )
    state = destination_state(context.output_base, context.experiment_id, context.run_id)
    if state == COMMITTED:
        return _verify_committed(
            context,
            load_bundle(
                output_base=context.output_base,
                experiment_id=context.experiment_id,
                run_id=context.run_id,
            ),
        )
    if state != ABSENT:
        raise BenchError(
            BM_PUBLICATION_CONFLICT,
            "an incomplete qualification destination already exists",
        )
    members, manifest = _derive(context)
    attestation_receipt = dict(members)[_E]
    run_directory = publish_bundle(
        output_base=context.output_base,
        experiment_id=context.experiment_id,
        run_id=context.run_id,
        members=members,
        manifest=manifest,
    )
    committed = load_bundle(
        output_base=context.output_base,
        experiment_id=context.experiment_id,
        run_id=context.run_id,
    )
    verified = _verify_committed(context, committed)
    if verified.manifest_digest != content_digest(manifest):
        raise _fail("published manifest differs from the qualified manifest", "manifest")
    if verified.attestation_receipt_id != attestation_receipt["receipt_id"]:
        raise _fail("published attestation differs from the qualified attestation", "attestation")
    if verified.output_directory != run_directory:
        raise _fail("published directory differs from qualified destination", "output_directory")
    return QualificationResult(
        disposition=DISPOSITION_QUALIFIED,
        experiment_id=context.experiment_id,
        run_id=context.run_id,
        manifest_digest=content_digest(manifest),
        attestation_receipt_id=attestation_receipt["receipt_id"],
        output_directory=run_directory,
    )


def load_qualified_synthetic_run(
    *,
    bundle: ExperimentBundle,
    run_dir: Path,
    scenario_root: Path,
    profiles_root: Path,
    resources_root: Path,
    qualification_profile_path: Path,
    qa_evidence_root: Path,
    expected_profile_digest: str,
    expected_framework_qa_digest: str,
    expected_source_qa_digest: str,
    source_root: Path,
    expected_source_set_digest: str,
    output_base: Path,
) -> QualificationResult:
    """Load, re-verify and return one committed qualification; never derives/writes."""

    context = _preflight(
        bundle=bundle,
        run_dir=run_dir,
        scenario_root=scenario_root,
        profiles_root=profiles_root,
        resources_root=resources_root,
        qualification_profile_path=qualification_profile_path,
        qa_evidence_root=qa_evidence_root,
        expected_profile_digest=expected_profile_digest,
        expected_framework_qa_digest=expected_framework_qa_digest,
        expected_source_qa_digest=expected_source_qa_digest,
        source_root=source_root,
        expected_source_set_digest=expected_source_set_digest,
        output_base=output_base,
    )
    state = destination_state(context.output_base, context.experiment_id, context.run_id)
    if state != COMMITTED:
        raise BenchError(
            BM_PUBLICATION_CONFLICT,
            "no complete committed qualification exists for this run",
        )
    committed = load_bundle(
        output_base=context.output_base,
        experiment_id=context.experiment_id,
        run_id=context.run_id,
    )
    return _verify_committed(context, committed)


__all__ = [
    "DISPOSITION_QUALIFIED",
    "DISPOSITION_REUSED",
    "QualificationResult",
    "load_qualified_synthetic_run",
    "qualify_synthetic_run",
]
