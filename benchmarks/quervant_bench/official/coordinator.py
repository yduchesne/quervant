"""G0 -> A -> B -> C -> D -> E official qualification orchestration.

The coordinator owns the lifecycle. Production entry points require a
:class:`official.authorization.VerifiedOfficialAuthorization` (never a parsed
freeze), and Gate D requires a recomputed, externally approved
:class:`official.historical.VerifiedHistoricalParity` (never caller-supplied rows).

A separate, explicitly fixture-only helper derives the identical gate graph in
memory for deterministic tests. It cannot publish, cannot run a backend and can
never report a production qualified disposition.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config.codec import content_digest
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id
from ..qualification.contracts import document_digest
from . import analysis as official_analysis
from . import historical as official_historical
from .acquisition import require_transition
from . import qa_evidence as official_qa_evidence
from .admission import (
    AdmittedCrossEngine,
    AdmittedRetainedKey,
    VerifiedOfficialAdmission,
    reverify_official_admission,
    verify_authorized_source,
)
from .authorization import (
    VerifiedOfficialAuthorization,
    require_verified_official_authorization,
)
from .contracts import (
    ATTESTATION_NAME,
    DEPENDENCY_GATES,
    FRAMEWORK_QA_ROSTER,
    OFFICIAL_GATE_ORDER,
    SOURCE_QA_ROSTER,
    UNRESOLVED_DECISIONS,
    validate_official_acceptance,
    validate_official_qa,
)
from .controls import control_digest
from .protocols import (
    STUDY_CROSS_ENGINE,
    STUDY_RETAINED_KEY,
    OfficialFreeze,
    require_freeze,
    verify_backend_protocol,
)
from .publication import (
    OfficialAnchors,
    OfficialBundle,
    publish_official_bundle,
    validate_official_bundle_in_memory,
)
from .receipts import (
    build_official_attestation_receipt,
    build_official_freeze_snapshot,
    build_official_manifest,
    build_official_receipt,
    member_record,
    verify_gate_graph,
)
from .verification import verify_official_study

QA_ROSTER_KIND = "official-qa-roster"
ACCEPTANCE_SCOPE = "real-official-v1"
CONTROL_STATUS_PASS = "PASS"
QA_STATUS_PASS = "PASS"
PARITY_STATUS_PASS = "PASS"
TEST_ONLY_GRAPH_DISPOSITION = "TEST_ONLY_GRAPH_VERIFIED"
NOT_PUBLISHED_DISPOSITION = "VERIFIED_NOT_PUBLISHED"
QUALIFIED_DISPOSITION = "REAL_OFFICIAL_QUALIFIED"


def _identity(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def _schema(message: str, field: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field)


def qa_roster_document() -> dict[str, Any]:
    """Return the frozen QA roster profile document (a pure design constant)."""

    return {
        "kind": QA_ROSTER_KIND,
        "schema_version": 1,
        "framework": list(FRAMEWORK_QA_ROSTER),
        "source": list(SOURCE_QA_ROSTER),
    }


def qa_roster_digest() -> str:
    """Return the canonical digest independently pinned by the reviewer at G0."""

    return content_digest(qa_roster_document())


def _toolchain_digest(toolchain_id: str) -> str:
    return content_digest(
        {
            "kind": "official-qa-toolchain",
            "schema_version": 1,
            "toolchain_id": toolchain_id,
        }
    )


@dataclass(frozen=True)
class OfficialQualificationResult:
    """The terminal result of one official qualification attempt."""

    disposition: str
    study_id: str
    run_id: str
    manifest_digest: str
    attestation_receipt_id: str
    output_directory: Path | None
    anchors: OfficialAnchors | None = None
    fixture_only: bool = False


# ---------------------------------------------------------------------------
# QA anchoring
# ---------------------------------------------------------------------------


def _require_qa(
    evidence: object,
    *,
    gate: str,
    freeze: OfficialFreeze,
    roster_digest: str,
) -> dict[str, Any]:
    """Validate QA shape *and* the independently pinned G0 document digest."""

    if gate == "framework-qa":
        pinned = freeze.qa_framework_digest
    elif gate == "source-qa":
        pinned = freeze.qa_source_digest
    else:  # pragma: no cover - guarded by the caller
        raise _identity("unknown QA gate", "gate")
    document = validate_official_qa(evidence, gate)
    if document["source_set_digest"] != freeze.source_file_set_digest:
        raise _identity(
            "the QA evidence is bound to a different source set", "source_set_digest"
        )
    if document["qa_roster_digest"] != roster_digest:
        raise _identity("the QA evidence uses a different roster", "qa_roster_digest")
    # Boolean/integer confusion must not allow a truthy "skip" to read as zero.
    for index, check in enumerate(document["checks"]):
        if check["executed"] is not True:
            raise _identity("a QA check is not executed", f"checks[{index}].executed")
        if check["failed"] != 0 or isinstance(check["failed"], bool):
            raise _identity("a QA check reports failures", f"checks[{index}].failed")
        if check["mandatory_skipped"] != 0 or isinstance(check["mandatory_skipped"], bool):
            raise _identity(
                "a QA check reports a mandatory skip",
                f"checks[{index}].mandatory_skipped",
            )
        if check["status"] != "pass":
            raise _identity("a QA check is not passing", f"checks[{index}].status")
    observed = document_digest(document)
    if observed != pinned:
        raise _identity(
            f"the {gate} evidence does not match the independently pinned G0 digest",
            "qa_framework_digest" if gate == "framework-qa" else "qa_source_digest",
        )
    return document


def _build_qa_receipt(
    *,
    gate: str,
    evidence: Mapping[str, Any],
    subject: Mapping[str, Any],
    freeze: OfficialFreeze,
    roster_digest: str,
) -> dict[str, Any]:
    evidence_name = (
        "framework-qa-evidence" if gate == "framework-qa" else "source-qa-evidence"
    )
    inputs = {
        evidence_name: document_digest(dict(evidence)),
        "qa-roster": roster_digest,
        "source-set": freeze.source_file_set_digest,
        "toolchain": _toolchain_digest(evidence["toolchain_id"]),
    }
    return build_official_receipt(
        gate=gate,
        subject=subject,
        source_set_digest=freeze.source_file_set_digest,
        inputs=inputs,
        outputs={evidence_name: document_digest(dict(evidence))},
        dependencies=(),
        qa_roster_digest=roster_digest,
    )


# ---------------------------------------------------------------------------
# Shared gate derivation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DerivedBundle:
    documents: Mapping[str, Mapping[str, Any]]
    manifest: Mapping[str, Any]
    anchors: OfficialAnchors
    policy: Mapping[str, Any]
    assessment: Mapping[str, Any]
    qa_snapshot: Mapping[str, str] | None = None


def _derive_bundle(
    *,
    freeze: OfficialFreeze,
    template: Mapping[str, Any],
    admitted: AdmittedCrossEngine | AdmittedRetainedKey,
    framework_qa: object,
    source_qa: object,
    historical_parity: object,
    source_root: Path | None,
    fixture_only: bool,
    observed: Mapping[str, Any] | None = None,
    authorization: VerifiedOfficialAuthorization | None = None,
    qa_evidence_root: Path | None = None,
    output_root: Path | None = None,
    admission_capability: VerifiedOfficialAdmission | None = None,
    policy_inputs: Any | None = None,
) -> _DerivedBundle:
    """Derive the complete official gate graph from verified, anchored inputs."""

    study_id = template.get("study_id")
    if study_id not in (STUDY_CROSS_ENGINE, STUDY_RETAINED_KEY):
        raise _identity("the template is not an official study template", "study_id")
    if document_digest(dict(template)) != freeze.design_digest:
        raise _identity(
            "the supplied template is not the independently approved design",
            "design_digest",
        )
    backend = verify_backend_protocol(template)
    if backend["raw_digest"] != freeze.backend_protocol_digest:
        raise _identity(
            "the authorized backend protocol digest differs from the frozen bytes",
            "backend_protocol_digest",
        )
    if admitted.admission_index["authorization_digest"] != freeze.authorization_digest:
        raise _identity(
            "the admitted evidence belongs to a different authorization",
            "authorization_digest",
        )
    if source_root is not None and not fixture_only:
        verify_authorized_source(Path(source_root), freeze)

    roster_digest = qa_roster_digest()
    subject = dict(admitted.admission_index["subject"])
    if subject["run_id"] != freeze.run_id:
        raise _identity("the admitted subject run id differs from the authorization", "run_id")

    # --- Gate A -------------------------------------------------------------
    admission_inputs = {
        "authorization": freeze.authorization_digest,
        "backend-protocol": freeze.backend_protocol_digest,
        "binary-manifest": freeze.binary_manifest_digest,
        "control-assessment": control_digest(
            admitted.control_assessment
            if isinstance(admitted, AdmittedRetainedKey)
            else admitted.control
        ),
        "corpus-manifest": freeze.corpus_manifest_digest,
        "host-preflight": freeze.host_preflight_digest,
        "raw-series-root": admitted.raw_series_root_digest,
        "source-set": freeze.source_file_set_digest,
        "workload": freeze.backend_protocol_digest,
    }
    admission_receipt = build_official_receipt(
        gate="admission",
        subject=subject,
        source_set_digest=freeze.source_file_set_digest,
        inputs=admission_inputs,
        outputs={"admission-index": document_digest(dict(admitted.admission_index))},
    )

    # --- Gate B -------------------------------------------------------------
    analysis_document, policy_document = official_analysis.analyze_official_study(
        admitted=admitted, template=template, policy_inputs=policy_inputs
    )
    policy_profile = policy_document["policy_digest"]
    analysis_inputs = {
        "admission-index": document_digest(dict(admitted.admission_index)),
        "analysis-profile": freeze.design_digest,
        "policy-profile": policy_profile,
        "raw-series-root": analysis_document["raw_series_root_digest"],
        "source-set": freeze.source_file_set_digest,
    }
    analysis_receipt = build_official_receipt(
        gate="analysis",
        subject=subject,
        source_set_digest=freeze.source_file_set_digest,
        inputs=analysis_inputs,
        outputs={
            "analysis": document_digest(analysis_document),
            "policy": document_digest(policy_document),
        },
        dependencies=(admission_receipt,),
        policy_digest=policy_profile,
    )

    # --- Gate C -------------------------------------------------------------
    if fixture_only:
        from .authorization import _open_fixture_authorization

        gate_c_authorization: Any = _open_fixture_authorization(freeze)
    else:
        if authorization is None:  # pragma: no cover - guarded by the caller
            raise BenchError(
                BM_UNSAFE_INPUT,
                "production Gate C requires the caller's verified authorization",
                field_path="authorization",
            )
        gate_c_authorization = authorization
    qa_snapshot: dict[str, str] | None = None
    assessment = verify_official_study(
        admitted=admitted,
        template=template,
        authorization=gate_c_authorization,
        analysis=analysis_document,
        policy=policy_document,
        source_root=source_root,
        observed=observed,
        admission=admission_capability,
        policy_inputs=policy_inputs,
    )
    if assessment.get("status") != "VERIFIED_REAL":
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            f"independent verification is {assessment.get('status')}; gate C cannot pass",
            field_path="verification_status",
        )
    verification_inputs = {
        "analysis": document_digest(analysis_document),
        "original-verifier": freeze.original_reference_verifier_digest,
        "policy": document_digest(policy_document),
        "raw-series-root": analysis_document["raw_series_root_digest"],
        "source-set": freeze.source_file_set_digest,
    }
    verification_receipt = build_official_receipt(
        gate="verification",
        subject=subject,
        source_set_digest=freeze.source_file_set_digest,
        inputs=verification_inputs,
        outputs={"verification-assessment": document_digest(assessment)},
        dependencies=(admission_receipt, analysis_receipt),
        policy_digest=policy_profile,
    )

    # --- QA gates -----------------------------------------------------------
    framework_evidence = _require_qa(
        framework_qa, gate="framework-qa", freeze=freeze, roster_digest=roster_digest
    )
    source_evidence = _require_qa(
        source_qa, gate="source-qa", freeze=freeze, roster_digest=roster_digest
    )
    qa_snapshot: dict[str, str] | None = None
    if not fixture_only:
        if qa_evidence_root is None or output_root is None:
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                "production qualification requires the external executed-QA evidence root",
                field_path="qa_evidence_root",
            )
        qa_snapshot = official_qa_evidence.verify_executed_qa_evidence(
            qa_evidence_root=Path(qa_evidence_root),
            framework_summary=framework_evidence,
            source_summary=source_evidence,
            freeze=freeze,
            output_root=Path(output_root),
            raw_root=admitted.raw_root,
        )
    framework_receipt = _build_qa_receipt(
        gate="framework-qa",
        evidence=framework_evidence,
        subject=subject,
        freeze=freeze,
        roster_digest=roster_digest,
    )
    source_receipt = _build_qa_receipt(
        gate="source-qa",
        evidence=source_evidence,
        subject=subject,
        freeze=freeze,
        roster_digest=roster_digest,
    )

    if qa_snapshot is not None:
        # Second read barrier: the executed artifacts must be unchanged after Gate C.
        official_qa_evidence.reverify_executed_qa_evidence(
            qa_evidence_root=Path(qa_evidence_root),
            expected_snapshot=qa_snapshot,
            framework_summary=framework_evidence,
            source_summary=source_evidence,
            freeze=freeze,
            output_root=Path(output_root),
            raw_root=admitted.raw_root,
        )

    # --- Gate D -------------------------------------------------------------
    parity = official_historical.require_verified_historical_parity(
        historical_parity, study_id=str(study_id), for_production=not fixture_only
    )
    parity_status = (
        PARITY_STATUS_PASS if not parity.fixture_only else "COMPARISON_COMPUTED_PENDING_REVIEW"
    )
    if parity_status != PARITY_STATUS_PASS and not fixture_only:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "historical parity is not independently verified; Gate D cannot pass",
            field_path="historical_parity_status",
        )
    if policy_document["decision_status"] in UNRESOLVED_DECISIONS:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the official policy is not derivable; Gate D cannot pass",
            field_path="policy_decision_status",
        )
    parity_digest = parity.assessment_digest
    acceptance_document = {
        "kind": "official-acceptance-summary",
        "schema_version": 1,
        "evidence_origin": "real",
        "qualification_scope": "official",
        "subject": subject,
        "approved_design_digest": freeze.design_digest,
        "authorization_digest": freeze.authorization_digest,
        "source_set_digest": freeze.source_file_set_digest,
        "gate_receipt_ids": {
            "admission": admission_receipt["receipt_id"],
            "analysis": analysis_receipt["receipt_id"],
            "framework-qa": framework_receipt["receipt_id"],
            "source-qa": source_receipt["receipt_id"],
            "verification": verification_receipt["receipt_id"],
        },
        "policy_decision_status": policy_document["decision_status"],
        "historical_parity_status": parity_status,
        "required_control_status": CONTROL_STATUS_PASS,
        "qa_status": QA_STATUS_PASS,
        "admission_status": "PASS",
        "decision_scope": ACCEPTANCE_SCOPE,
    }
    acceptance = validate_official_acceptance(acceptance_document)
    acceptance_inputs = {
        "admission-index": document_digest(dict(admitted.admission_index)),
        "analysis": document_digest(analysis_document),
        "authorization": freeze.authorization_digest,
        "control-assessment": admission_inputs["control-assessment"],
        "framework-qa-evidence": document_digest(framework_evidence),
        "historical-parity": parity_digest,
        "policy": document_digest(policy_document),
        "source-qa-evidence": document_digest(source_evidence),
        "source-set": freeze.source_file_set_digest,
        "verification-assessment": document_digest(assessment),
    }
    acceptance_receipt = build_official_receipt(
        gate="acceptance",
        subject=subject,
        source_set_digest=freeze.source_file_set_digest,
        inputs=acceptance_inputs,
        outputs={"acceptance-summary": document_digest(acceptance)},
        dependencies=(
            admission_receipt,
            analysis_receipt,
            framework_receipt,
            source_receipt,
            verification_receipt,
        ),
        qa_roster_digest=roster_digest,
        policy_digest=policy_profile,
    )

    # --- Gate E -------------------------------------------------------------
    precondition_documents: dict[str, Mapping[str, Any]] = {
        "admission-index.json": admitted.admission_index,
        "admission.json": admission_receipt,
        "analysis.json": analysis_document,
        "policy.json": policy_document,
        "analysis-receipt.json": analysis_receipt,
        "verification-assessment.json": assessment,
        "verification.json": verification_receipt,
        "framework-qa-evidence.json": framework_evidence,
        "framework-qa.json": framework_receipt,
        "source-qa-evidence.json": source_evidence,
        "source-qa.json": source_receipt,
        "acceptance-summary.json": acceptance,
        "acceptance.json": acceptance_receipt,
    }
    snapshot = build_official_freeze_snapshot(
        subject=subject,
        approved_design_digest=freeze.design_digest,
        authorization_digest=freeze.authorization_digest,
        source_set_digest=freeze.source_file_set_digest,
        members=[
            member_record(name, precondition_documents[name])
            for name in sorted(precondition_documents)
        ],
    )
    attestation_receipt = build_official_attestation_receipt(
        subject=subject,
        snapshot=snapshot,
        dependencies=(
            acceptance_receipt,
            admission_receipt,
            analysis_receipt,
            framework_receipt,
            source_receipt,
            verification_receipt,
        ),
        source_set_digest=freeze.source_file_set_digest,
        qa_roster_digest=roster_digest,
        policy_digest=policy_profile,
        authorization_digest=freeze.authorization_digest,
    )
    documents = dict(precondition_documents)
    documents[ATTESTATION_NAME] = attestation_receipt
    manifest = build_official_manifest(
        subject=subject,
        snapshot=snapshot,
        attestation_receipt=attestation_receipt,
        members=[member_record(name, documents[name]) for name in sorted(documents)],
        approved_design_digest=freeze.design_digest,
        authorization_digest=freeze.authorization_digest,
        source_set_digest=freeze.source_file_set_digest,
        raw_series_root_digest=admitted.raw_series_root_digest,
    )

    expected_inputs = {
        "admission": admission_inputs,
        "analysis": analysis_inputs,
        "verification": verification_inputs,
        "framework-qa": {
            "framework-qa-evidence": document_digest(framework_evidence),
            "qa-roster": roster_digest,
            "source-set": freeze.source_file_set_digest,
            "toolchain": _toolchain_digest(framework_evidence["toolchain_id"]),
        },
        "source-qa": {
            "qa-roster": roster_digest,
            "source-qa-evidence": document_digest(source_evidence),
            "source-set": freeze.source_file_set_digest,
            "toolchain": _toolchain_digest(source_evidence["toolchain_id"]),
        },
        "acceptance": acceptance_inputs,
        "attestation": {
            "authorization": freeze.authorization_digest,
            "freeze-snapshot": document_digest(snapshot),
            "source-set": freeze.source_file_set_digest,
        },
    }
    expected_outputs = {
        "admission": {"admission-index": document_digest(dict(admitted.admission_index))},
        "analysis": {
            "analysis": document_digest(analysis_document),
            "policy": document_digest(policy_document),
        },
        "verification": {"verification-assessment": document_digest(assessment)},
        "framework-qa": {"framework-qa-evidence": document_digest(framework_evidence)},
        "source-qa": {"source-qa-evidence": document_digest(source_evidence)},
        "acceptance": {"acceptance-summary": document_digest(acceptance)},
        "attestation": {"freeze-snapshot": document_digest(snapshot)},
    }
    verify_gate_graph(
        {
            gate: documents[_receipt_name(gate)]
            for gate in OFFICIAL_GATE_ORDER
        },
        subject=subject,
        source_set_digest=freeze.source_file_set_digest,
        expected_inputs=expected_inputs,
        expected_outputs=expected_outputs,
        qa_roster_digest=roster_digest,
        policy_digest=policy_profile,
    )

    anchors = OfficialAnchors(
        subject=subject,
        approved_design_digest=freeze.design_digest,
        authorization_digest=freeze.authorization_digest,
        backend_protocol_digest=freeze.backend_protocol_digest,
        source_set_digest=freeze.source_file_set_digest,
        binary_manifest_digest=freeze.binary_manifest_digest,
        corpus_manifest_digest=freeze.corpus_manifest_digest,
        host_preflight_digest=freeze.host_preflight_digest,
        original_verifier_digest=freeze.original_reference_verifier_digest,
        policy_digest=policy_profile,
        qa_roster_digest=roster_digest,
        control_assessment_digest=admission_inputs["control-assessment"],
        historical_parity_digest=parity_digest,
    )
    return _DerivedBundle(
        documents=documents,
        manifest=manifest,
        anchors=anchors,
        policy=policy_document,
        assessment=assessment,
        qa_snapshot=qa_snapshot,
    )


# ---------------------------------------------------------------------------
# Public orchestration
# ---------------------------------------------------------------------------


def qualify_official_study(
    *,
    authorization: VerifiedOfficialAuthorization,
    template: Mapping[str, Any],
    admitted: VerifiedOfficialAdmission,
    framework_qa: object,
    source_qa: object,
    historical_parity: object,
    output_base: Path,
    qa_evidence_root: Path,
    source_root: Path | None = None,
    publish: bool = False,
    observed: Mapping[str, Any] | None = None,
    policy_inputs: Any | None = None,
) -> OfficialQualificationResult:
    """Run the complete G0-A-B-C-D-E sequence for one authorized study."""

    study_id = template.get("study_id")
    if study_id not in (STUDY_CROSS_ENGINE, STUDY_RETAINED_KEY):
        raise _identity("the template is not an official study template", "study_id")
    freeze = require_verified_official_authorization(
        authorization, study_id=str(study_id), for_production=True, observed=observed
    )
    # Gate A: re-admit the raw bytes against the same verified authorization.
    fresh = reverify_official_admission(
        admitted,
        authorization=authorization,
        template=template,
        source_root=source_root,
        observed=observed,
    )
    return _qualify_with_freeze(
        freeze=freeze,
        template=template,
        admitted=fresh,
        admission_capability=admitted,
        framework_qa=framework_qa,
        source_qa=source_qa,
        historical_parity=historical_parity,
        output_base=Path(output_base),
        source_root=source_root,
        publish=publish,
        fixture_only=False,
        observed=observed,
        authorization=authorization,
        qa_evidence_root=Path(qa_evidence_root),
        policy_inputs=policy_inputs,
    )


def qualify_fixture_graph_in_memory(
    *,
    authorization: VerifiedOfficialAuthorization,
    template: Mapping[str, Any],
    admitted: AdmittedCrossEngine | AdmittedRetainedKey,
    framework_qa: object,
    source_qa: object,
    historical_parity: object,
) -> OfficialQualificationResult:
    """Derive and verify the gate graph for deterministic fixtures only.

    Never publishes, never runs a backend and never returns a production
    qualification disposition.
    """

    study_id = template.get("study_id")
    if not isinstance(authorization, VerifiedOfficialAuthorization) or not authorization.fixture_only:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the in-memory fixture graph requires a fixture-only authorization",
            field_path="authorization",
        )
    if not getattr(admitted, "fixture_only", False):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the in-memory fixture graph requires a fixture-only admission record",
            field_path="admitted",
        )
    freeze = require_verified_official_authorization(
        authorization, study_id=str(study_id), for_production=False
    )
    return _qualify_with_freeze(
        freeze=freeze,
        template=template,
        admitted=admitted,
        framework_qa=framework_qa,
        source_qa=source_qa,
        historical_parity=historical_parity,
        output_base=None,
        source_root=None,
        publish=False,
        fixture_only=True,
        observed=None,
        authorization=authorization,
        qa_evidence_root=None,
    )


def _qualify_with_freeze(
    *,
    freeze: OfficialFreeze,
    template: Mapping[str, Any],
    admitted: AdmittedCrossEngine | AdmittedRetainedKey,
    framework_qa: object,
    source_qa: object,
    historical_parity: object,
    output_base: Path | None,
    source_root: Path | None,
    publish: bool,
    fixture_only: bool,
    observed: Mapping[str, Any] | None,
    authorization: VerifiedOfficialAuthorization,
    qa_evidence_root: Path | None,
    admission_capability: VerifiedOfficialAdmission | None = None,
    policy_inputs: Any | None = None,
) -> OfficialQualificationResult:
    derived = _derive_bundle(
        freeze=freeze,
        template=template,
        admitted=admitted,
        framework_qa=framework_qa,
        source_qa=source_qa,
        historical_parity=historical_parity,
        source_root=source_root,
        fixture_only=fixture_only,
        observed=observed,
        authorization=authorization,
        qa_evidence_root=qa_evidence_root,
        output_root=Path(output_base) if output_base is not None else None,
        admission_capability=admission_capability,
        policy_inputs=policy_inputs,
    )
    attestation_receipt = derived.documents[ATTESTATION_NAME]
    from .contracts import MEMBER_NAMES

    member_sequence = sorted(derived.documents.items(), key=lambda item: MEMBER_NAMES.index(item[0]))
    if fixture_only:
        report = validate_official_bundle_in_memory(
            output_base=output_base,
            study_id=str(template["study_id"]),
            run_id=freeze.run_id,
            members=member_sequence,
            manifest=dict(derived.manifest),
            anchors=derived.anchors,
            authorization=authorization,
        )
        return OfficialQualificationResult(
            disposition=str(report["disposition"]),
            study_id=str(template["study_id"]),
            run_id=freeze.run_id,
            manifest_digest=document_digest(dict(derived.manifest)),
            attestation_receipt_id=attestation_receipt["receipt_id"],
            output_directory=None,
            anchors=derived.anchors,
            fixture_only=True,
        )
    if not publish:
        return OfficialQualificationResult(
            disposition=NOT_PUBLISHED_DISPOSITION,
            study_id=str(template["study_id"]),
            run_id=freeze.run_id,
            manifest_digest=document_digest(dict(derived.manifest)),
            attestation_receipt_id=attestation_receipt["receipt_id"],
            output_directory=Path(output_base) if output_base is not None else None,
            anchors=derived.anchors,
            fixture_only=False,
        )
    if output_base is None:  # pragma: no cover - guarded by the caller
        raise _schema("publication needs an output base")
    if derived.qa_snapshot is not None:
        # Third read barrier: executed QA artifacts must still be unchanged.
        official_qa_evidence.reverify_executed_qa_evidence(
            qa_evidence_root=Path(qa_evidence_root),
            expected_snapshot=derived.qa_snapshot,
            framework_summary=derived.documents["framework-qa-evidence.json"],
            source_summary=derived.documents["source-qa-evidence.json"],
            freeze=freeze,
            output_root=Path(output_base),
            raw_root=admitted.raw_root,
        )
    bundle: OfficialBundle = publish_official_bundle(
        output_base=Path(output_base),
        study_id=str(template["study_id"]),
        run_id=freeze.run_id,
        members=member_sequence,
        manifest=derived.manifest,
        anchors=derived.anchors,
        authorization=authorization,
        observed=observed,
    )
    if bundle.disposition != "REUSED_VERIFIED":
        raise _identity(
            "post-publication verification did not confirm the committed bundle", "disposition"
        )
    return OfficialQualificationResult(
        disposition=QUALIFIED_DISPOSITION,
        study_id=str(template["study_id"]),
        run_id=freeze.run_id,
        manifest_digest=bundle.manifest_digest,
        attestation_receipt_id=attestation_receipt["receipt_id"],
        output_directory=bundle.output_directory,
        anchors=derived.anchors,
        fixture_only=False,
    )


def _receipt_name(gate: str) -> str:
    from .publication import GATE_RECEIPT_NAMES

    return GATE_RECEIPT_NAMES[gate]


def require_gate_order(current: str, target: str) -> str:
    """Require one legal lifecycle transition (delegates to acquisition)."""

    return require_transition(current, target)


def reuse_or_conflict(
    *,
    output_base: Path,
    study_id: str,
    run_id: str,
    anchors: OfficialAnchors,
    authorization: VerifiedOfficialAuthorization,
    observed: Mapping[str, Any] | None = None,
) -> OfficialBundle:
    """Return a fully re-verified committed bundle or a typed conflict."""

    from .publication import load_official_bundle, official_destination_state

    require_verified_official_authorization(
        authorization, study_id=study_id, for_production=True, observed=observed
    )
    state = official_destination_state(Path(output_base), study_id, run_id)
    if state != "committed":
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "no committed official bundle exists to reuse",
            field_path="output_base",
        )
    return load_official_bundle(
        output_base=Path(output_base), study_id=study_id, run_id=run_id, anchors=anchors
    )


__all__ = [
    "OfficialQualificationResult",
    "TEST_ONLY_GRAPH_DISPOSITION",
    "qualify_fixture_graph_in_memory",
    "qa_roster_digest",
    "qa_roster_document",
    "qualify_official_study",
    "require_gate_order",
    "reuse_or_conflict",
]
