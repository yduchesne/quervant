"""Official seven-gate ``receipt.v1`` graph, freeze snapshot and manifest algebra.

The BM-01 receipt schema, canonical encoder and digest conventions are reused
unchanged. A receipt is only built after its stage semantics have been verified; a
receipt whose own hash matches but whose inputs, outputs or dependency edges are
wrong is rejected by :func:`verify_official_receipt`.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..config.codec import canonical_document_bytes, content_digest
from ..config.contracts import validate_receipt
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCOPE_MISMATCH,
    BenchError,
)
from ..config.identity import validate_digest
from ..qualification.contracts import (
    bound_payload,
    document_digest,
    require_closed,
    validate_subject,
)
from .contracts import (
    ATTESTATION_NAME,
    DEPENDENCY_GATES,
    FREEZE_MEMBERS,
    INPUT_NAMES,
    MANIFEST_KIND,
    MANIFEST_MEMBERS,
    OFFICIAL_GATE_ORDER,
    OFFICIAL_SCOPE,
    OFFICIAL_VALIDATOR_IDS,
    OFFICIAL_VALIDATOR_IDS_V2,
    OUTPUT_NAMES,
    POLICY_GATES,
    QA_ROSTER_GATES,
    REAL_ORIGIN,
    SCHEMA_VERSION,
    SNAPSHOT_KIND,
    VALIDATOR_VERSION,
    input_names_for,
    require_profile_version,
    validate_official_freeze_snapshot,
    validate_official_manifest,
)


def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def official_validator_identity(gate: str, source_set_digest: str, *, profile_version: int = 1) -> dict[str, Any]:
    """Return the official stage validator identity (never the synthetic one)."""

    version = require_profile_version(profile_version, "profile_version")
    registry = OFFICIAL_VALIDATOR_IDS if version == 1 else OFFICIAL_VALIDATOR_IDS_V2
    if type(gate) is not str or gate not in registry:
        raise BenchError(BM_SCHEMA_INVALID, f"unknown official gate: {gate!r}", field_path="gate")
    return {
        "validator_id": registry[gate],
        "validator_version": VALIDATOR_VERSION if version == 1 else 2,
        "source_digest": validate_digest(source_set_digest, "validator.source_digest"),
    }


def dependency_entry(document: Mapping[str, Any]) -> dict[str, str]:
    """Return the closed dependency record for one upstream receipt."""

    receipt = validate_receipt(document)
    return {
        "name": receipt.gate,
        "digest": content_digest(dict(document)),
        "gate": receipt.gate,
        "receipt_id": receipt.receipt_id,
    }


def _sorted_entries(entries: Mapping[str, str], field: str) -> list[dict[str, str]]:
    if not isinstance(entries, Mapping):
        raise BenchError(BM_SCHEMA_INVALID, f"{field} must be a mapping", field_path=field)
    return [
        {"name": name, "digest": validate_digest(entries[name], f"{field}.{name}")}
        for name in sorted(entries)
    ]


def build_official_receipt(
    *,
    gate: str,
    subject: Mapping[str, Any],
    source_set_digest: str,
    inputs: Mapping[str, str],
    outputs: Mapping[str, str],
    dependencies: Sequence[Mapping[str, Any]] = (),
    qa_roster_digest: str | None = None,
    policy_digest: str | None = None,
    profile_version: int = 1,
) -> dict[str, Any]:
    """Build and immediately re-verify one real/official receipt."""

    if gate not in OFFICIAL_VALIDATOR_IDS:
        raise BenchError(BM_SCHEMA_INVALID, f"unknown official gate: {gate!r}", field_path="gate")
    expected_subject = validate_subject(subject)
    identity = official_validator_identity(gate, source_set_digest, profile_version=profile_version)
    if tuple(sorted(inputs)) != input_names_for(gate, profile_version=profile_version):
        raise _fail(f"{gate} receipt inputs are not the exact required set", "inputs")
    if tuple(sorted(outputs)) != OUTPUT_NAMES[gate]:
        raise _fail(f"{gate} receipt outputs are not the exact required set", "outputs")
    if tuple(sorted(validate_receipt(dep).gate for dep in dependencies)) != DEPENDENCY_GATES[gate]:
        raise _fail(f"{gate} receipt dependencies are not the required graph edges", "dependencies")
    dependency_entries = sorted(
        (dependency_entry(dep) for dep in dependencies), key=lambda entry: entry["name"]
    )
    payload: dict[str, Any] = {
        "kind": "receipt",
        "schema_version": 1,
        "gate": gate,
        "status": "pass",
        "evidence_origin": REAL_ORIGIN,
        "qualification_scope": OFFICIAL_SCOPE,
        "subject": expected_subject,
        "validator": identity,
        "inputs": _sorted_entries(inputs, "inputs"),
        "dependencies": dependency_entries,
        "outputs": _sorted_entries(outputs, "outputs"),
    }
    if gate in QA_ROSTER_GATES:
        if qa_roster_digest is None:
            raise _fail("qa_roster_digest is required for this gate", "qa_roster_digest")
        payload["qa_roster_digest"] = validate_digest(qa_roster_digest, "qa_roster_digest")
    elif qa_roster_digest is not None:
        raise _fail("qa_roster_digest is not permitted for this gate", "qa_roster_digest")
    if gate in POLICY_GATES:
        if policy_digest is None:
            raise _fail("policy_digest is required for this gate", "policy_digest")
        payload["policy_digest"] = validate_digest(policy_digest, "policy_digest")
    elif policy_digest is not None:
        raise _fail("policy_digest is not permitted for this gate", "policy_digest")
    document = dict(payload)
    document["receipt_id"] = content_digest(payload)
    validate_receipt(document)
    verify_official_receipt(
        document,
        gate=gate,
        subject=expected_subject,
        source_set_digest=source_set_digest,
        inputs=inputs,
        outputs=outputs,
        dependencies=dependencies,
        qa_roster_digest=qa_roster_digest,
        policy_digest=policy_digest,
        profile_version=profile_version,
    )
    return document


def verify_official_receipt(
    document: object,
    *,
    gate: str,
    subject: Mapping[str, Any],
    source_set_digest: str,
    inputs: Mapping[str, str],
    outputs: Mapping[str, str],
    dependencies: Sequence[Mapping[str, Any]] = (),
    qa_roster_digest: str | None = None,
    policy_digest: str | None = None,
    profile_version: int = 1,
) -> Any:
    """Semantically re-verify one official receipt against its expected edges."""

    identity = official_validator_identity(gate, source_set_digest, profile_version=profile_version)
    receipt = validate_receipt(document)
    if receipt.gate != gate:
        raise _fail("receipt gate does not match the expected stage", "gate")
    if receipt.status != "pass":
        raise _fail("receipt status is not 'pass'", "status")
    if (receipt.evidence_origin, receipt.qualification_scope) != (REAL_ORIGIN, OFFICIAL_SCOPE):
        raise BenchError(
            BM_SCOPE_MISMATCH,
            "receipt origin/scope is not real/official",
            field_path="qualification_scope",
        )
    if tuple(sorted(inputs)) != input_names_for(gate, profile_version=profile_version):
        raise _fail(f"{gate} receipt inputs are not the exact required set", "inputs")
    expected_subject = validate_subject(subject)
    actual_subject = {
        "experiment_id": receipt.subject.experiment_id,
        "run_id": receipt.subject.run_id,
        "protocol_digest": receipt.subject.protocol_digest,
        "workload_digest": receipt.subject.workload_digest,
    }
    if actual_subject != expected_subject:
        raise _fail("receipt subject does not match the qualified run", "subject")
    if (
        receipt.validator.validator_id != identity["validator_id"]
        or receipt.validator.validator_version != identity["validator_version"]
        or receipt.validator.source_digest != identity["source_digest"]
    ):
        raise _fail("receipt validator identity is not the official stage identity", "validator")
    from ..config.contracts import EvidenceEntry

    expected_inputs = [
        EvidenceEntry(name=entry["name"], digest=entry["digest"])
        for entry in _sorted_entries(inputs, "inputs")
    ]
    if list(receipt.inputs) != expected_inputs:
        raise _fail("receipt inputs are not the exact expected bindings", "inputs")
    expected_outputs = [
        EvidenceEntry(name=entry["name"], digest=entry["digest"])
        for entry in _sorted_entries(outputs, "outputs")
    ]
    if list(receipt.outputs) != expected_outputs:
        raise _fail("receipt outputs are not the exact expected bindings", "outputs")
    expected_dependencies = sorted(
        (dependency_entry(dep) for dep in dependencies), key=lambda entry: entry["name"]
    )
    actual_dependencies = [
        {
            "name": entry.name,
            "digest": entry.digest,
            "gate": entry.gate,
            "receipt_id": entry.receipt_id,
        }
        for entry in receipt.dependencies
    ]
    if actual_dependencies != expected_dependencies:
        raise _fail("receipt dependency edges are not the exact expected graph", "dependencies")
    for entry in receipt.dependencies:
        if entry.name != entry.gate:
            raise _fail("dependency name must equal its gate slug", "dependencies")
    expected_profile = (
        validate_digest(qa_roster_digest, "qa_roster_digest") if gate in QA_ROSTER_GATES else None
    )
    if receipt.qa_roster_digest != expected_profile:
        raise _fail("receipt qa_roster_digest does not match the binding", "qa_roster_digest")
    expected_policy = (
        validate_digest(policy_digest, "policy_digest") if gate in POLICY_GATES else None
    )
    if receipt.policy_digest != expected_policy:
        raise _fail("receipt policy_digest does not match the binding", "policy_digest")
    return receipt


def receipt_digest(document: Mapping[str, Any]) -> str:
    """Return the canonical receipt identity of one official receipt."""

    return validate_receipt(document).receipt_id


def member_record(name: str, document: Mapping[str, Any]) -> dict[str, Any]:
    """Return the manifest/snapshot record for one canonical document member."""

    payload = canonical_document_bytes(dict(document))
    return {
        "path": name,
        "byte_length": len(payload),
        "digest": document_digest(document),
    }


def build_official_freeze_snapshot(
    *,
    subject: Mapping[str, Any],
    approved_design_digest: str,
    authorization_digest: str,
    source_set_digest: str,
    members: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the canonical in-memory pre-attestation freeze snapshot."""

    records = sorted(
        (
            {
                "path": member["path"],
                "byte_length": member["byte_length"],
                "digest": member["digest"],
            }
            for member in members
        ),
        key=lambda record: record["path"],
    )
    snapshot = {
        "kind": SNAPSHOT_KIND,
        "schema_version": SCHEMA_VERSION,
        "evidence_origin": REAL_ORIGIN,
        "qualification_scope": OFFICIAL_SCOPE,
        "subject": dict(subject),
        "approved_design_digest": approved_design_digest,
        "authorization_digest": authorization_digest,
        "source_set_digest": source_set_digest,
        "members": records,
    }
    return validate_official_freeze_snapshot(snapshot)


def build_official_attestation_receipt(
    *,
    subject: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    dependencies: Sequence[Mapping[str, Any]],
    source_set_digest: str,
    qa_roster_digest: str,
    policy_digest: str,
    authorization_digest: str,
    profile_version: int = 1,
) -> dict[str, Any]:
    """Build the acyclic attestation receipt over the frozen snapshot digest."""

    frozen = validate_official_freeze_snapshot(snapshot)
    snapshot_digest = document_digest(frozen)
    document = build_official_receipt(
        gate="attestation",
        subject=subject,
        source_set_digest=source_set_digest,
        inputs={
            "authorization": validate_digest(authorization_digest, "authorization_digest"),
            "freeze-snapshot": snapshot_digest,
            "source-set": validate_digest(source_set_digest, "source_set_digest"),
        },
        dependencies=dependencies,
        outputs={"freeze-snapshot": snapshot_digest},
        qa_roster_digest=qa_roster_digest,
        policy_digest=policy_digest,
        profile_version=profile_version,
    )
    for entry in document["outputs"]:
        if entry["name"] != "freeze-snapshot":
            raise _fail("attestation may output only the freeze snapshot", "outputs")
    return document


def build_official_manifest(
    *,
    subject: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    attestation_receipt: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    approved_design_digest: str,
    authorization_digest: str,
    source_set_digest: str,
    raw_series_root_digest: str,
) -> dict[str, Any]:
    """Build the final official completion manifest over the first 14 members."""

    frozen = validate_official_freeze_snapshot(snapshot)
    records = sorted(
        (
            {
                "path": member["path"],
                "byte_length": member["byte_length"],
                "digest": member["digest"],
            }
            for member in members
        ),
        key=lambda record: record["path"],
    )
    if tuple(record["path"] for record in records) != MANIFEST_MEMBERS:
        raise _fail("the manifest member set is not the exact 14-file inventory", "members")
    if ATTESTATION_NAME not in {record["path"] for record in records}:
        raise _fail("the manifest must include the attestation receipt", "members")
    manifest = {
        "kind": MANIFEST_KIND,
        "schema_version": SCHEMA_VERSION,
        "evidence_origin": REAL_ORIGIN,
        "qualification_scope": OFFICIAL_SCOPE,
        "subject": dict(subject),
        "approved_design_digest": approved_design_digest,
        "authorization_digest": authorization_digest,
        "source_set_digest": source_set_digest,
        "raw_series_root_digest": raw_series_root_digest,
        "freeze_snapshot": frozen,
        "attestation_digest": document_digest(dict(attestation_receipt)),
        "members": records,
    }
    validate_official_manifest(manifest)
    bound_payload(manifest, "manifest")
    return manifest


def verify_official_freeze_snapshot(
    *,
    snapshot: Mapping[str, Any],
    attestation_receipt: Mapping[str, Any],
    documents: Mapping[str, Mapping[str, Any]],
    subject: Mapping[str, Any],
    approved_design_digest: str,
    authorization_digest: str,
    source_set_digest: str,
    profile_version: int = 1,
) -> str:
    """Reconstruct the snapshot from committed bytes and cross-check Gate E."""

    require_profile_version(profile_version, "profile_version")
    frozen = validate_official_freeze_snapshot(snapshot)
    if set(documents) != set(FREEZE_MEMBERS):
        raise _fail("the frozen member set is not the exact 13 documents", "members")
    reconstructed = build_official_freeze_snapshot(
        subject=subject,
        approved_design_digest=approved_design_digest,
        authorization_digest=authorization_digest,
        source_set_digest=source_set_digest,
        members=[member_record(name, documents[name]) for name in FREEZE_MEMBERS],
    )
    if reconstructed != frozen:
        raise _fail(
            "the freeze snapshot does not match the committed member bytes",
            "freeze_snapshot",
        )
    outputs = attestation_receipt.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 1:
        raise _fail("the attestation receipt must declare one output", "outputs")
    output = outputs[0]
    if output.get("name") != "freeze-snapshot":
        raise _fail("the attestation output must be the freeze snapshot", "outputs")
    snapshot_digest = document_digest(frozen)
    if output.get("digest") != snapshot_digest:
        raise _fail(
            "the attestation output does not match the reconstructed snapshot",
            "freeze_snapshot",
        )
    for field, expected in (
        ("subject", subject),
        ("approved_design_digest", approved_design_digest),
        ("authorization_digest", authorization_digest),
        ("source_set_digest", source_set_digest),
    ):
        if frozen.get(field) != expected:
            raise _fail("the freeze snapshot is not bound to the current anchors", field)
    return snapshot_digest


def verify_official_manifest_members(
    *,
    manifest: Mapping[str, Any],
    payloads: Mapping[str, bytes],
    documents: Mapping[str, Mapping[str, Any]],
) -> str:
    """Re-verify every committed member byte and return the manifest digest."""

    validated = validate_official_manifest(manifest)
    expected = {member["path"]: member for member in validated["members"]}
    if set(payloads) != set(MANIFEST_MEMBERS):
        raise _fail("the committed payload set is not the exact 14 members", "members")
    for name in MANIFEST_MEMBERS:
        payload = payloads[name]
        member = expected[name]
        if member["byte_length"] != len(payload):
            raise _fail("a committed member byte length differs from the manifest", name)
        if member["digest"] != document_digest(documents[name]):
            raise _fail("a committed member digest differs from the manifest", name)
        if canonical_document_bytes(dict(documents[name])) != payload:
            raise _fail("a committed member is not in canonical byte form", name)
    return document_digest(validated)


def verify_gate_graph(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    subject: Mapping[str, Any],
    source_set_digest: str,
    expected_inputs: Mapping[str, Mapping[str, str]],
    expected_outputs: Mapping[str, Mapping[str, str]],
    qa_roster_digest: str,
    policy_digest: str,
    profile_version: int = 1,
) -> dict[str, Mapping[str, Any]]:
    """Verify all seven official receipts and their exact dependency graph.

    ``expected_inputs``/``expected_outputs`` must be derived by the caller from
    externally pinned anchors and committed bytes, never copied out of the
    receipt under test.
    """

    require_profile_version(profile_version, "profile_version")
    by_gate: dict[str, Mapping[str, Any]] = {}
    for gate in OFFICIAL_GATE_ORDER:
        document = documents.get(gate)
        if document is None:
            raise _fail("a required official receipt is missing", gate)
        by_gate[gate] = document
    for gate in OFFICIAL_GATE_ORDER:
        dependencies = [by_gate[upstream] for upstream in DEPENDENCY_GATES[gate]]
        verify_official_receipt(
            by_gate[gate],
            gate=gate,
            subject=subject,
            source_set_digest=source_set_digest,
            inputs=expected_inputs[gate],
            outputs=expected_outputs[gate],
            dependencies=dependencies,
            qa_roster_digest=qa_roster_digest if gate in QA_ROSTER_GATES else None,
            policy_digest=policy_digest if gate in POLICY_GATES else None,
            profile_version=profile_version,
        )
    return by_gate


__all__ = [
    "build_official_attestation_receipt",
    "build_official_freeze_snapshot",
    "build_official_manifest",
    "build_official_receipt",
    "dependency_entry",
    "member_record",
    "official_validator_identity",
    "receipt_digest",
    "verify_gate_graph",
    "verify_official_freeze_snapshot",
    "verify_official_manifest_members",
    "verify_official_receipt",
]
