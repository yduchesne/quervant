"""Gate E: exclusive immutable official publication and strict re-open.

The mechanical durability sequence is the *existing* ``OsPublicationIO`` protocol,
extracted into ``qualification.publication.publish_validated_members_atomic`` and
shared by both publishers. This module supplies the real semantic validator, the
13/14/15-member freeze algebra, post-publication re-verification against
externally pinned anchors and the ``REUSED_VERIFIED`` path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config.codec import canonical_document_bytes, content_digest
from ..config.contracts import validate_receipt
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_PUBLICATION_CONFLICT,
    BM_SCOPE_MISMATCH,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id, validate_uuid4
from ..evidence.paths import require_publication_base
from ..evidence.provenance import repository_root
from ..qualification.contracts import document_digest
from ..qualification.publication import (
    ABSENT,
    COMMITTED,
    INCOMPLETE,
    OsPublicationIO,
    _read_canonical,
    destination_state,
    publish_validated_members_atomic,
)
from .contracts import (
    ATTESTATION_NAME,
    FREEZE_MEMBERS,
    MANIFEST_MEMBERS,
    MANIFEST_NAME,
    MAX_DOCUMENT_BYTES,
    MEMBER_NAMES,
    PENDING_NAME,
    validate_official_acceptance,
    validate_official_analysis,
    validate_official_evidence_index,
    validate_official_freeze_snapshot,
    validate_official_manifest,
    validate_official_policy,
    validate_official_qa,
    validate_official_verification,
)
from .receipts import (
    verify_gate_graph,
    verify_official_freeze_snapshot,
    verify_official_manifest_members,
)

REUSED_VERIFIED = "REUSED_VERIFIED"
PUBLISHED_VERIFIED = "PUBLISHED_VERIFIED"
OFFICIAL_OUTPUT_ROOT = "benchmark-results/qualified-official"

#: Gate -> durable receipt member name.
GATE_RECEIPT_NAMES: dict[str, str] = {
    "admission": "admission.json",
    "analysis": "analysis-receipt.json",
    "verification": "verification.json",
    "framework-qa": "framework-qa.json",
    "source-qa": "source-qa.json",
    "acceptance": "acceptance.json",
    "attestation": ATTESTATION_NAME,
}
#: Gate -> (output binding name, durable member name).
GATE_OUTPUT_MEMBERS: dict[str, tuple[tuple[str, str], ...]] = {
    "admission": (("admission-index", "admission-index.json"),),
    "analysis": (("analysis", "analysis.json"), ("policy", "policy.json")),
    "verification": (("verification-assessment", "verification-assessment.json"),),
    "framework-qa": (("framework-qa-evidence", "framework-qa-evidence.json"),),
    "source-qa": (("source-qa-evidence", "source-qa-evidence.json"),),
    "acceptance": (("acceptance-summary", "acceptance-summary.json"),),
    "attestation": (("freeze-snapshot", "manifest.json"),),
}


def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


@dataclass(frozen=True)
class OfficialAnchors:
    """Externally pinned identities required to read a committed official root.

    Every value must come from the reviewer-approved G0 authorization, the
    approved design template, or the independently observed stage evidence; none
    may be copied out of the committed manifest under test.
    """

    subject: Mapping[str, Any]
    approved_design_digest: str
    authorization_digest: str
    backend_protocol_digest: str
    source_set_digest: str
    binary_manifest_digest: str
    corpus_manifest_digest: str
    host_preflight_digest: str
    original_verifier_digest: str
    policy_digest: str
    qa_roster_digest: str
    control_assessment_digest: str
    historical_parity_digest: str

    def __post_init__(self) -> None:
        for name in (
            "approved_design_digest",
            "authorization_digest",
            "backend_protocol_digest",
            "source_set_digest",
            "binary_manifest_digest",
            "corpus_manifest_digest",
            "host_preflight_digest",
            "original_verifier_digest",
            "policy_digest",
            "qa_roster_digest",
            "control_assessment_digest",
            "historical_parity_digest",
        ):
            validate_digest(getattr(self, name), name)
        if not isinstance(self.subject, Mapping):
            raise BenchError(BM_UNSAFE_INPUT, "anchors.subject must be a mapping")

    def workload_digest(self) -> str:
        """Return the authorized workload (backend protocol) digest."""

        return self.backend_protocol_digest


def official_output_base(approved_identity: str | None = None) -> Path:
    """Return the official publication base (never the synthetic ``qualified`` root)."""

    base = (
        Path(approved_identity)
        if approved_identity is not None
        else repository_root() / OFFICIAL_OUTPUT_ROOT
    )
    return require_publication_base(base, repository_root())


def validate_official_member(name: str, document: object) -> dict[str, Any]:
    """Validate one durable official member against its frozen kind."""

    mapping = {
        "admission-index.json": validate_official_evidence_index,
        "analysis.json": validate_official_analysis,
        "policy.json": validate_official_policy,
        "verification-assessment.json": validate_official_verification,
        "acceptance-summary.json": validate_official_acceptance,
        "manifest.json": validate_official_manifest,
        "framework-qa-evidence.json": lambda doc: validate_official_qa(doc, "framework-qa"),
        "source-qa-evidence.json": lambda doc: validate_official_qa(doc, "source-qa"),
    }
    if name in mapping:
        return mapping[name](document)
    reverse = {value: key for key, value in GATE_RECEIPT_NAMES.items()}
    gate = reverse.get(name)
    if gate is None:
        raise _fail("the member name is not an official durable member", "member")
    receipt = validate_receipt(document)
    if receipt.gate != gate:
        raise _fail("the receipt gate does not match its durable file name", gate)
    if (receipt.evidence_origin, receipt.qualification_scope) != ("real", "official"):
        raise BenchError(
            BM_SCOPE_MISMATCH,
            "the receipt is not real/official evidence",
            field_path="qualification_scope",
        )
    return dict(document)


@dataclass(frozen=True)
class OfficialBundle:
    """A fully re-verified, read-only official qualification directory."""

    disposition: str
    output_directory: Path
    documents: Mapping[str, Mapping[str, Any]]
    payloads: Mapping[str, bytes]
    manifest_digest: str
    study_id: str
    run_id: str


def _require_member_payloads(
    members: Sequence[tuple[str, Mapping[str, Any]]],
    manifest: Mapping[str, Any],
) -> list[tuple[str, bytes]]:
    names = tuple(name for name, _document in members)
    if names != MEMBER_NAMES[:14]:
        raise _fail("the published member order is not the exact 14-file inventory", "members")
    validated_manifest = validate_official_manifest(manifest)
    expected = {member["path"]: member for member in validated_manifest["members"]}
    payloads: list[tuple[str, bytes]] = []
    for name, document in members:
        payload = canonical_document_bytes(dict(document))
        if len(payload) > MAX_DOCUMENT_BYTES:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"{name} exceeds the committed document budget",
                reference=name,
            )
        member = expected.get(name)
        if member is None:
            raise _fail("the manifest does not declare a published member", name)
        if member["byte_length"] != len(payload):
            raise _fail("the manifest byte length does not match the published bytes", name)
        if member["digest"] != content_digest(dict(document)):
            raise _fail("the manifest digest does not match the published bytes", name)
        payloads.append((name, payload))
    return payloads


def publish_official_bundle(
    *,
    output_base: Path,
    study_id: str,
    run_id: str,
    members: Sequence[tuple[str, Mapping[str, Any]]],
    manifest: Mapping[str, Any],
    anchors: OfficialAnchors | None = None,
    io: OsPublicationIO | None = None,
) -> OfficialBundle:
    """Exclusively publish and then re-open the complete official qualification."""

    experiment = validate_semantic_id(study_id, "study_id")
    run = validate_uuid4(run_id, "run_id")
    base = require_publication_base(Path(output_base), repository_root())
    run_dir = base / experiment / run
    state = destination_state(base, experiment, run)
    if state == COMMITTED:
        raise BenchError(
            BM_PUBLICATION_CONFLICT,
            "an official qualification destination already exists",
            reference=f"{experiment}/{run}",
        )
    if state == INCOMPLETE:
        raise BenchError(
            BM_PUBLICATION_CONFLICT,
            "an incomplete official destination exists and must not be repaired",
            reference=f"{experiment}/{run}",
        )
    payloads = _require_member_payloads(members, manifest)
    publish_validated_members_atomic(
        run_dir=run_dir,
        payloads=payloads,
        manifest_payload=canonical_document_bytes(dict(manifest)),
        io=io,
    )
    if anchors is None:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "post-publication verification requires the externally pinned anchors",
            field_path="anchors",
        )
    return load_official_bundle(
        output_base=base, study_id=experiment, run_id=run, anchors=anchors
    )


def _load_member(run_dir: Path, name: str) -> tuple[dict[str, Any], bytes]:
    document, payload = _read_canonical(run_dir, name)
    validated = validate_official_member(name, document)
    if canonical_document_bytes(validated) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "a committed official member is not stored in canonical byte form",
            reference=name,
        )
    return dict(validated), payload


def _expected_outputs(
    documents: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    outputs: dict[str, dict[str, str]] = {}
    for gate, bindings in GATE_OUTPUT_MEMBERS.items():
        resolved: dict[str, str] = {}
        for binding, member in bindings:
            if gate == "attestation":
                snapshot = validate_official_freeze_snapshot(manifest["freeze_snapshot"])
                resolved[binding] = document_digest(snapshot)
            else:
                resolved[binding] = document_digest(documents[member])
        outputs[gate] = resolved
    return outputs


def _expected_inputs(
    documents: Mapping[str, Mapping[str, Any]],
    anchors: OfficialAnchors,
) -> dict[str, dict[str, str]]:
    admission_index = documents["admission-index.json"]
    analysis = documents["analysis.json"]
    policy = documents["policy.json"]
    framework_evidence = documents["framework-qa-evidence.json"]
    source_evidence = documents["source-qa-evidence.json"]
    verification = documents["verification-assessment.json"]
    return {
        "admission": {
            "authorization": anchors.authorization_digest,
            "backend-protocol": anchors.backend_protocol_digest,
            "binary-manifest": anchors.binary_manifest_digest,
            "control-assessment": anchors.control_assessment_digest,
            "corpus-manifest": anchors.corpus_manifest_digest,
            "host-preflight": anchors.host_preflight_digest,
            "raw-series-root": admission_index["raw_series_root_digest"],
            "source-set": anchors.source_set_digest,
            "workload": anchors.workload_digest(),
        },
        "analysis": {
            "admission-index": document_digest(admission_index),
            "analysis-profile": anchors.approved_design_digest,
            "policy-profile": anchors.policy_digest,
            "raw-series-root": analysis["raw_series_root_digest"],
            "source-set": anchors.source_set_digest,
        },
        "verification": {
            "analysis": document_digest(analysis),
            "original-verifier": anchors.original_verifier_digest,
            "policy": document_digest(policy),
            "raw-series-root": analysis["raw_series_root_digest"],
            "source-set": anchors.source_set_digest,
        },
        "framework-qa": {
            "framework-qa-evidence": document_digest(framework_evidence),
            "qa-roster": anchors.qa_roster_digest,
            "source-set": anchors.source_set_digest,
            "toolchain": document_digest(
                {
                    "kind": "official-qa-toolchain",
                    "schema_version": 1,
                    "toolchain_id": framework_evidence["toolchain_id"],
                }
            ),
        },
        "source-qa": {
            "qa-roster": anchors.qa_roster_digest,
            "source-qa-evidence": document_digest(source_evidence),
            "source-set": anchors.source_set_digest,
            "toolchain": document_digest(
                {
                    "kind": "official-qa-toolchain",
                    "schema_version": 1,
                    "toolchain_id": source_evidence["toolchain_id"],
                }
            ),
        },
        "acceptance": {
            "admission-index": document_digest(admission_index),
            "analysis": document_digest(analysis),
            "authorization": anchors.authorization_digest,
            "control-assessment": anchors.control_assessment_digest,
            "framework-qa-evidence": document_digest(framework_evidence),
            "historical-parity": anchors.historical_parity_digest,
            "policy": document_digest(policy),
            "source-qa-evidence": document_digest(source_evidence),
            "source-set": anchors.source_set_digest,
            "verification-assessment": document_digest(verification),
        },
        "attestation": {
            "authorization": anchors.authorization_digest,
            "freeze-snapshot": document_digest(
                validate_official_freeze_snapshot(
                    documents["manifest.json"]["freeze_snapshot"]
                )
            ),
            "source-set": anchors.source_set_digest,
        },
    }


def load_official_bundle(
    *,
    output_base: Path,
    study_id: str,
    run_id: str,
    anchors: OfficialAnchors,
) -> OfficialBundle:
    """Strictly load and fully re-verify one committed official directory."""

    if not isinstance(anchors, OfficialAnchors):
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "an official read requires externally pinned anchors",
            field_path="anchors",
        )
    experiment = validate_semantic_id(study_id, "study_id")
    run = validate_uuid4(run_id, "run_id")
    base = require_publication_base(Path(output_base), repository_root())
    run_dir = base / experiment / run
    if run_dir.is_symlink():
        raise BenchError(BM_UNSAFE_INPUT, "the official destination must not be a symlink")
    if not run_dir.is_dir():
        raise BenchError(BM_PUBLICATION_CONFLICT, "no committed official destination exists")
    names = sorted(os.listdir(run_dir))
    if set(names) != set(MEMBER_NAMES):
        raise BenchError(
            BM_PUBLICATION_CONFLICT,
            "the official destination is incomplete or contains unexpected entries",
        )
    documents: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes] = {}
    for name in MEMBER_NAMES:
        documents[name], payloads[name] = _load_member(run_dir, name)
    manifest = validate_official_manifest(documents[MANIFEST_NAME])
    manifest_digest = verify_official_manifest_members(
        manifest=manifest,
        payloads={name: payloads[name] for name in MANIFEST_MEMBERS},
        documents={name: documents[name] for name in MANIFEST_MEMBERS},
    )
    attestation = validate_receipt(documents[ATTESTATION_NAME])
    if attestation.gate != "attestation":
        raise _fail("the completion attestation is not an attestation receipt", "gate")
    subject = manifest["subject"]
    for name, expected in (
        ("subject", anchors.subject),
        ("source_set_digest", anchors.source_set_digest),
        ("authorization_digest", anchors.authorization_digest),
        ("approved_design_digest", anchors.approved_design_digest),
    ):
        if manifest[name] != expected:
            raise _fail(
                "the committed manifest is not bound to the independently pinned identity",
                name,
            )
    if documents["acceptance.json"].get("qa_roster_digest") != anchors.qa_roster_digest:
        raise _fail("the acceptance receipt QA roster digest differs from the pin", "qa_roster_digest")
    if documents["acceptance.json"].get("policy_digest") != anchors.policy_digest:
        raise _fail("the acceptance receipt policy digest differs from the pin", "policy_digest")
    snapshot_digest = verify_official_freeze_snapshot(
        snapshot=manifest["freeze_snapshot"],
        attestation_receipt=documents[ATTESTATION_NAME],
        documents={name: documents[name] for name in FREEZE_MEMBERS},
        subject=subject,
        approved_design_digest=anchors.approved_design_digest,
        authorization_digest=anchors.authorization_digest,
        source_set_digest=anchors.source_set_digest,
    )
    if snapshot_digest == manifest_digest:  # pragma: no cover - defensive
        raise _fail("the snapshot and manifest digests must be distinct", "manifest")
    verify_gate_graph(
        {gate: documents[name] for gate, name in GATE_RECEIPT_NAMES.items()},
        subject=subject,
        source_set_digest=anchors.source_set_digest,
        expected_inputs=_expected_inputs(documents, anchors),
        expected_outputs=_expected_outputs(documents, manifest),
        qa_roster_digest=anchors.qa_roster_digest,
        policy_digest=anchors.policy_digest,
    )
    acceptance = documents["acceptance-summary.json"]
    for name, expected in (
        ("source_set_digest", anchors.source_set_digest),
        ("authorization_digest", anchors.authorization_digest),
        ("approved_design_digest", anchors.approved_design_digest),
    ):
        if acceptance[name] != expected:
            raise _fail("the acceptance summary is not bound to the pinned identity", name)
    return OfficialBundle(
        disposition=REUSED_VERIFIED,
        output_directory=run_dir,
        documents=documents,
        payloads=payloads,
        manifest_digest=manifest_digest,
        study_id=experiment,
        run_id=run,
    )


def official_destination_state(output_base: Path, study_id: str, run_id: str) -> str:
    """Classify an official destination without ever repairing it."""

    base = require_publication_base(Path(output_base), repository_root())
    return destination_state(
        base, validate_semantic_id(study_id, "study_id"), validate_uuid4(run_id)
    )


__all__ = [
    "ABSENT",
    "COMMITTED",
    "GATE_RECEIPT_NAMES",
    "INCOMPLETE",
    "OFFICIAL_OUTPUT_ROOT",
    "OfficialAnchors",
    "OfficialBundle",
    "PENDING_NAME",
    "PUBLISHED_VERIFIED",
    "REUSED_VERIFIED",
    "load_official_bundle",
    "official_destination_state",
    "official_output_base",
    "publish_official_bundle",
    "validate_official_member",
]
