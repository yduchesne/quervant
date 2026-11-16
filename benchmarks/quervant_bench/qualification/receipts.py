"""Generic BM-01 receipt-v1 construction and exact stage-graph verification.

BM-01 validates receipt shape and self-content identity only. This module adds the
semantic layer BM-06 needs: one legal gate, ``status='pass'``, synthetic/simulated
scope, exact validator identity, exact sorted inputs/outputs and the exact upstream
dependency set for that stage. A syntactically valid receipt with a correct
self-hash but a wrong dependency edge is rejected.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..config.codec import content_digest
from ..config.contracts import (
    EvidenceEntry,
    Receipt,
    ReceiptSubject,
    validate_receipt,
)
from ..config.errors import BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BenchError
from ..config.identity import validate_digest
from .contracts import (
    EVIDENCE_ORIGIN,
    GATE_ORDER,
    QUALIFICATION_SCOPE,
    require_closed,
    validate_subject,
)

VALIDATOR_IDS: dict[str, str] = {gate: f"synthetic-{gate}" for gate in GATE_ORDER}
VALIDATOR_VERSION = 1

INPUT_NAMES: dict[str, tuple[str, ...]] = {
    "admission": tuple(
        sorted(
            {
                "seal",
                "protocol",
                "workload",
                "qualification-profile",
                "scenario",
                "source-set",
            }
        )
    ),
    "analysis": tuple(
        sorted(
            {
                "admission-index",
                "analysis-profile",
                "policy-profile",
                "resource-observations",
                "source-set",
            }
        )
    ),
    "verification": ("analysis", "policy", "source-seal", "source-set"),
    "framework-qa": tuple(
        sorted(
            {
                "framework-qa-evidence",
                "qa-toolchain",
                "qualification-profile",
                "source-set",
            }
        )
    ),
    "source-qa": tuple(
        sorted(
            {
                "source-qa-evidence",
                "qa-toolchain",
                "qualification-profile",
                "source-set",
            }
        )
    ),
    "acceptance": tuple(
        sorted(
            {
                "admission-index",
                "analysis",
                "policy",
                "verification-assessment",
                "framework-qa-evidence",
                "source-qa-evidence",
                "qualification-profile",
                "source-set",
            }
        )
    ),
    "attestation": ("freeze-snapshot", "qualification-profile", "source-set"),
}
OUTPUT_NAMES: dict[str, tuple[str, ...]] = {
    "admission": ("admission-index",),
    "analysis": ("analysis", "policy"),
    "verification": ("verification-assessment",),
    "framework-qa": ("framework-qa-evidence",),
    "source-qa": ("source-qa-evidence",),
    "acceptance": ("acceptance-summary",),
    "attestation": ("freeze-snapshot",),
}
DEPENDENCY_GATES: dict[str, tuple[str, ...]] = {
    "admission": (),
    "analysis": ("admission",),
    "verification": ("admission", "analysis"),
    "framework-qa": (),
    "source-qa": (),
    "acceptance": (
        "admission",
        "analysis",
        "framework-qa",
        "source-qa",
        "verification",
    ),
    "attestation": (
        "acceptance",
        "admission",
        "analysis",
        "framework-qa",
        "source-qa",
        "verification",
    ),
}
QA_ROSTER_GATES: frozenset[str] = frozenset(
    {"framework-qa", "source-qa", "acceptance", "attestation"}
)
POLICY_GATES: frozenset[str] = frozenset(
    {"analysis", "verification", "acceptance", "attestation"}
)


def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def _sorted_entries(entries: Mapping[str, str], field: str) -> list[dict[str, str]]:
    if not isinstance(entries, Mapping):
        raise BenchError(BM_SCHEMA_INVALID, f"{field} must be a mapping", field_path=field)
    result: list[dict[str, str]] = []
    for name in sorted(entries):
        result.append(
            {"name": name, "digest": validate_digest(entries[name], f"{field}.{name}")}
        )
    return result


def validator_identity(gate: str, source_set_digest: str) -> dict[str, Any]:
    """Return the stage-specific versioned validator identity."""

    if gate not in VALIDATOR_IDS:
        raise BenchError(BM_SCHEMA_INVALID, f"unknown gate: {gate!r}", field_path="gate")
    return {
        "validator_id": VALIDATOR_IDS[gate],
        "validator_version": VALIDATOR_VERSION,
        "source_digest": validate_digest(
            source_set_digest, "validator.source_digest"
        ),
    }


def _dependency_entry(document: Mapping[str, Any]) -> dict[str, str]:
    receipt = validate_receipt(document)
    return {
        "name": receipt.gate,
        "digest": content_digest(dict(document)),
        "gate": receipt.gate,
        "receipt_id": receipt.receipt_id,
    }


def build_stage_receipt(
    *,
    gate: str,
    subject: Mapping[str, Any],
    validator: Mapping[str, Any],
    inputs: Mapping[str, str],
    dependencies: Sequence[Mapping[str, Any]] = (),
    outputs: Mapping[str, str],
    profile_digest: str | None = None,
    policy_digest: str | None = None,
) -> dict[str, Any]:
    """Build one closed BM-01 ``receipt.v1`` for a completed logical gate.

    Construction never invents a PASS: callers may only build a receipt after the
    stage semantics have been established. The result is immediately
    shape-validated and graph-checked against the caller's own inputs.
    """

    if gate not in GATE_ORDER:
        raise BenchError(BM_SCHEMA_INVALID, f"unknown gate: {gate!r}", field_path="gate")
    expected_subject = validate_subject(subject)
    identity = require_closed(
        validator,
        "validator",
        frozenset({"validator_id", "validator_version", "source_digest"}),
    )
    if identity["validator_id"] != VALIDATOR_IDS[gate]:
        raise _fail("validator_id does not match the gate", "validator.validator_id")
    if identity["validator_version"] != VALIDATOR_VERSION:
        raise _fail(
            "validator_version is not supported", "validator.validator_version"
        )
    source_digest = validate_digest(identity["source_digest"], "validator.source_digest")

    expected_inputs = INPUT_NAMES[gate]
    expected_outputs = OUTPUT_NAMES[gate]
    if tuple(sorted(inputs)) != expected_inputs:
        raise _fail(f"{gate} receipt inputs are not the exact required set", "inputs")
    if tuple(sorted(outputs)) != expected_outputs:
        raise _fail(f"{gate} receipt outputs are not the exact required set", "outputs")
    input_entries = _sorted_entries(inputs, "inputs")
    output_entries = _sorted_entries(outputs, "outputs")

    expected_dependencies = DEPENDENCY_GATES[gate]
    if tuple(sorted(validate_receipt(dep).gate for dep in dependencies)) != (
        expected_dependencies
    ):
        raise _fail(f"{gate} receipt dependencies are not the required graph edges", "dependencies")
    dependency_entries = sorted(
        (_dependency_entry(dep) for dep in dependencies), key=lambda entry: entry["name"]
    )

    payload: dict[str, Any] = {
        "kind": "receipt",
        "schema_version": 1,
        "gate": gate,
        "status": "pass",
        "evidence_origin": EVIDENCE_ORIGIN,
        "qualification_scope": QUALIFICATION_SCOPE,
        "subject": expected_subject,
        "validator": {
            "validator_id": VALIDATOR_IDS[gate],
            "validator_version": VALIDATOR_VERSION,
            "source_digest": source_digest,
        },
        "inputs": input_entries,
        "dependencies": dependency_entries,
        "outputs": output_entries,
    }
    if gate in QA_ROSTER_GATES:
        if profile_digest is None:
            raise _fail("qa_roster_digest is required for this gate", "qa_roster_digest")
        payload["qa_roster_digest"] = validate_digest(profile_digest, "qa_roster_digest")
    elif profile_digest is not None:
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
    verify_stage_receipt(
        document,
        gate=gate,
        source_set_digest=source_digest,
        expected_subject=expected_subject,
        inputs=inputs,
        outputs=outputs,
        dependencies=dependencies,
        profile_digest=profile_digest,
        policy_digest=policy_digest,
    )
    return document


def verify_stage_receipt(
    document: object,
    *,
    gate: str,
    source_set_digest: str,
    expected_subject: Mapping[str, Any],
    inputs: Mapping[str, str],
    outputs: Mapping[str, str],
    dependencies: Sequence[Mapping[str, Any]] = (),
    profile_digest: str | None = None,
    policy_digest: str | None = None,
) -> Receipt:
    """Semantically re-verify one stage receipt against its expected edges."""

    receipt = validate_receipt(document)
    if receipt.gate != gate:
        raise _fail("receipt gate does not match the expected stage", "gate")
    if receipt.status != "pass":
        raise _fail("receipt status is not 'pass'", "status")
    if (receipt.evidence_origin, receipt.qualification_scope) != (
        EVIDENCE_ORIGIN,
        QUALIFICATION_SCOPE,
    ):
        raise _fail("receipt origin/scope is not synthetic/simulated", "qualification_scope")
    subject = validate_subject(expected_subject)
    actual_subject = {
        "experiment_id": receipt.subject.experiment_id,
        "run_id": receipt.subject.run_id,
        "protocol_digest": receipt.subject.protocol_digest,
        "workload_digest": receipt.subject.workload_digest,
    }
    if actual_subject != subject:
        raise _fail("receipt subject does not match the qualified run", "subject")
    expected_validator = validator_identity(gate, source_set_digest)
    if (
        receipt.validator.validator_id != expected_validator["validator_id"]
        or receipt.validator.validator_version
        != expected_validator["validator_version"]
        or receipt.validator.source_digest != expected_validator["source_digest"]
    ):
        raise _fail("receipt validator identity is not the pinned stage identity", "validator")

    expected_input_entries = [
        EvidenceEntry(name=entry["name"], digest=entry["digest"])
        for entry in _sorted_entries(inputs, "inputs")
    ]
    if list(receipt.inputs) != expected_input_entries:
        raise _fail("receipt inputs are not the exact expected bindings", "inputs")
    expected_output_entries = [
        EvidenceEntry(name=entry["name"], digest=entry["digest"])
        for entry in _sorted_entries(outputs, "outputs")
    ]
    if list(receipt.outputs) != expected_output_entries:
        raise _fail("receipt outputs are not the exact expected bindings", "outputs")

    expected_dependencies = sorted(
        (_dependency_entry(dep) for dep in dependencies), key=lambda entry: entry["name"]
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
    if actual_dependencies != sorted(expected_dependencies, key=lambda entry: entry["name"]):
        raise _fail("receipt dependency edges are not the exact expected graph", "dependencies")
    for entry in receipt.dependencies:
        if entry.name != entry.gate:
            raise _fail("dependency name must equal its gate slug", "dependencies")

    expected_profile = (
        validate_digest(profile_digest, "qa_roster_digest")
        if gate in QA_ROSTER_GATES
        else None
    )
    if receipt.qa_roster_digest != expected_profile:
        raise _fail("receipt qa_roster_digest does not match the profile binding", "qa_roster_digest")
    expected_policy = (
        validate_digest(policy_digest, "policy_digest") if gate in POLICY_GATES else None
    )
    if receipt.policy_digest != expected_policy:
        raise _fail("receipt policy_digest does not match the policy binding", "policy_digest")
    return receipt


def receipt_digest(document: Mapping[str, Any]) -> str:
    """Return the canonical digest of one receipt document."""

    validate_receipt(document)
    return content_digest(dict(document))


def subject_mapping(subject: ReceiptSubject) -> dict[str, str]:
    """Convert a validated subject record back into its closed document shape."""

    return {
        "experiment_id": subject.experiment_id,
        "run_id": subject.run_id,
        "protocol_digest": subject.protocol_digest,
        "workload_digest": subject.workload_digest,
    }


__all__ = [
    "DEPENDENCY_GATES",
    "INPUT_NAMES",
    "OUTPUT_NAMES",
    "POLICY_GATES",
    "QA_ROSTER_GATES",
    "VALIDATOR_IDS",
    "VALIDATOR_VERSION",
    "build_stage_receipt",
    "receipt_digest",
    "subject_mapping",
    "validator_identity",
    "verify_stage_receipt",
]
