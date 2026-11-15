"""Admission receipt construction and dependency-aware revalidation.

A receipt is never accepted from its own hash alone. Construction happens only
after the admission pipeline has verified every input byte; verification compares
all bindings against the trusted spec, the independently pinned anchor and the
observed admission index.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..config.codec import content_digest
from ..config.contracts import (
    EvidenceEntry,
    Receipt,
    ReceiptSubject,
    ValidatorIdentity,
    validate_receipt,
)
from ..config.errors import BM_IDENTITY_INVALID, BenchError
from ..config.identity import validate_digest
from .manifests import (
    LOCK_NAMES,
    TrustedAdmissionSpec,
    spec_digest,
    validate_admission_index,
)

def _require_anchor(spec: TrustedAdmissionSpec, expected_spec_digest: str) -> str:
    expected = validate_digest(expected_spec_digest, "expected_spec_digest")
    if spec_digest(spec) != expected:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "trusted spec digest does not match the independently pinned anchor",
        )
    return expected


def require_verified_locks(
    spec: TrustedAdmissionSpec, verified_locks: Mapping[str, str]
) -> dict[str, str]:
    if not isinstance(verified_locks, Mapping):
        raise BenchError(BM_IDENTITY_INVALID, "verified_locks must be a mapping")
    names = sorted(verified_locks)
    if tuple(names) != LOCK_NAMES:
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"verified_locks must contain exactly the sorted names {list(LOCK_NAMES)}",
        )
    validated: dict[str, str] = {}
    for name in names:
        validated[name] = validate_digest(
            verified_locks[name], f"verified_locks[{name!r}]"
        )
    expected = {lock.name: lock.digest for lock in spec.locks}
    if validated != expected:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "verified lock digests do not match the trusted specification",
        )
    return validated


def _require_index_binding(
    index: Mapping[str, Any], spec: TrustedAdmissionSpec, expected_spec_digest: str
) -> None:
    if index["trusted_spec_digest"] != expected_spec_digest:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "admission index does not bind the expected trusted spec digest",
        )
    subject = index["subject"]
    if subject["experiment_id"] != spec.subject.experiment_id:
        raise BenchError(BM_IDENTITY_INVALID, "admission index experiment mismatch")
    if subject["run_id"] != spec.subject.run_id:
        raise BenchError(BM_IDENTITY_INVALID, "admission index run mismatch")
    if subject["protocol_digest"] != spec.subject.protocol_digest:
        raise BenchError(BM_IDENTITY_INVALID, "admission index protocol mismatch")
    if subject["workload_digest"] != spec.subject.workload_digest:
        raise BenchError(BM_IDENTITY_INVALID, "admission index workload mismatch")
    if (index["evidence_origin"], index["qualification_scope"]) != (
        spec.evidence_origin,
        spec.qualification_scope,
    ):
        raise BenchError(BM_IDENTITY_INVALID, "admission index origin/scope mismatch")


def _expected_inputs(
    spec: TrustedAdmissionSpec,
    expected_spec_digest: str,
    verified_locks: Mapping[str, str],
    index: Mapping[str, Any],
) -> tuple[EvidenceEntry, ...]:
    pairs: dict[str, str] = {
        "trusted-spec": expected_spec_digest,
        "protocol-lock": spec.subject.protocol_digest,
        "workload-lock": spec.subject.workload_digest,
        "validator-lock": spec.validator.source_digest,
        "policy-lock": spec.policy_digest,
        "qa-roster-lock": spec.qa_roster_digest,
    }
    for name in LOCK_NAMES:
        pairs[name] = verified_locks[name]
    for entry in index["files"]:
        _add_pair(pairs, entry["name"], entry["digest"])
    for entry in index["archives"]:
        _add_pair(pairs, entry["name"], entry["digest"])
    return tuple(
        EvidenceEntry(name=name, digest=pairs[name]) for name in sorted(pairs)
    )


def _add_pair(pairs: dict[str, str], name: str, digest: str) -> None:
    if name in pairs:
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"receipt input name is duplicated or reserved: {name!r}",
        )
    pairs[name] = validate_digest(digest, f"receipt input digest for {name!r}")


def build_admission_receipt(
    index_document: Mapping[str, Any],
    spec: TrustedAdmissionSpec,
    spec_expected_digest: str,
    verified_locks: Mapping[str, str],
) -> dict[str, Any]:
    """Build and structurally validate one synthetic ``admission/pass`` receipt."""

    expected = _require_anchor(spec, spec_expected_digest)
    index = validate_admission_index(index_document)
    locks = require_verified_locks(spec, verified_locks)
    if tuple(index["locks"]) != tuple(
        {"name": lock.name, "digest": lock.digest} for lock in spec.locks
    ):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "admission index locks do not match the trusted specification",
        )
    _require_index_binding(index, spec, expected)

    inputs = _expected_inputs(spec, expected, locks, index)
    outputs = (
        EvidenceEntry(
            name="admission-index", digest=content_digest(index_document)
        ),
    )
    payload: dict[str, Any] = {
        "kind": "receipt",
        "schema_version": 1,
        "gate": "admission",
        "status": "pass",
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "subject": {
            "experiment_id": spec.subject.experiment_id,
            "run_id": spec.subject.run_id,
            "protocol_digest": spec.subject.protocol_digest,
            "workload_digest": spec.subject.workload_digest,
        },
        "validator": {
            "validator_id": spec.validator.validator_id,
            "validator_version": spec.validator.validator_version,
            "source_digest": spec.validator.source_digest,
        },
        "inputs": [
            {"name": entry.name, "digest": entry.digest} for entry in inputs
        ],
        "dependencies": [],
        "outputs": [
            {"name": entry.name, "digest": entry.digest} for entry in outputs
        ],
        "policy_digest": spec.policy_digest,
        "qa_roster_digest": spec.qa_roster_digest,
    }
    receipt_id = content_digest(payload)
    document = dict(payload)
    document["receipt_id"] = receipt_id
    validate_receipt(document)
    return document


def verify_admission_receipt(
    receipt_document: Mapping[str, Any],
    index_document: Mapping[str, Any],
    spec: TrustedAdmissionSpec,
    spec_expected_digest: str,
    verified_locks: Mapping[str, str],
) -> Receipt:
    """Fully verify a v1 admission receipt against the trusted bindings.

    This function does not rehash evidence bytes; ``reverify_admission`` performs
    that additional step before returning a reused status.
    """

    expected = _require_anchor(spec, spec_expected_digest)
    index = validate_admission_index(index_document)
    locks = require_verified_locks(spec, verified_locks)
    _require_index_binding(index, spec, expected)
    if tuple(index["locks"]) != tuple(
        {"name": lock.name, "digest": lock.digest} for lock in spec.locks
    ):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "admission index locks do not match the trusted specification",
        )

    receipt = validate_receipt(receipt_document)
    if receipt.gate != "admission":
        raise BenchError(
            BM_IDENTITY_INVALID,
            "BM-02 may only verify admission receipts",
            field_path="gate",
        )
    if receipt.status != "pass":
        raise BenchError(
            BM_IDENTITY_INVALID,
            "BM-02 only revalidates a previously published admission pass",
            field_path="status",
        )
    if (receipt.evidence_origin, receipt.qualification_scope) != (
        "synthetic",
        "simulated",
    ):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "admission receipts are synthetic/simulated only",
            field_path="qualification_scope",
        )
    expected_subject = ReceiptSubject(
        experiment_id=spec.subject.experiment_id,
        run_id=spec.subject.run_id,
        protocol_digest=spec.subject.protocol_digest,
        workload_digest=spec.subject.workload_digest,
    )
    if receipt.subject != expected_subject:
        raise BenchError(BM_IDENTITY_INVALID, "receipt subject binding mismatch")
    expected_validator = ValidatorIdentity(
        validator_id=spec.validator.validator_id,
        validator_version=spec.validator.validator_version,
        source_digest=spec.validator.source_digest,
    )
    if receipt.validator != expected_validator:
        raise BenchError(BM_IDENTITY_INVALID, "receipt validator binding mismatch")
    if receipt.policy_digest != spec.policy_digest:
        raise BenchError(BM_IDENTITY_INVALID, "receipt policy binding mismatch")
    if receipt.qa_roster_digest != spec.qa_roster_digest:
        raise BenchError(BM_IDENTITY_INVALID, "receipt QA roster binding mismatch")
    if receipt.dependencies:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "BM-02 admission receipts must not declare upstream dependencies",
        )
    expected_inputs = _expected_inputs(spec, expected, locks, index)
    if receipt.inputs != expected_inputs:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "receipt inputs are incomplete, extra or out of binding",
        )
    expected_outputs = (
        EvidenceEntry(
            name="admission-index", digest=content_digest(index_document)
        ),
    )
    if receipt.outputs != expected_outputs:
        raise BenchError(
            BM_IDENTITY_INVALID, "receipt output binding mismatch"
        )
    return receipt


__all__ = [
    "build_admission_receipt",
    "require_verified_locks",
    "verify_admission_receipt",
]
