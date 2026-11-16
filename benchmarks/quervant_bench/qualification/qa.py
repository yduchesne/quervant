"""Pinned framework/source QA evidence, roster matching and QA receipts.

BM-06 never executes QA, approves a log or mints a CI attestation. It reads two
externally pinned QA documents plus their per-check records, verifies the exact
closed shape, the exact versioned roster, the source/profile/toolchain bindings and
the per-check digest equality, then issues the two BM-01 QA receipts.

In L2 these records are *simulated evidence of the qualification mechanism*; they
are not external CI attestations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..config.codec import (
    canonical_document_bytes,
    content_digest,
    decode_text,
    loads_json,
)
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..evidence.paths import (
    list_directory_beneath,
    open_regular_beneath,
    require_safe_root,
    validate_relative_member,
)
from .contracts import (
    MAX_DOCUMENT_BYTES,
    QA_EVIDENCE_NAMES,
    validate_qa_check_record,
    validate_qa_evidence,
)
from .identity import require_anchor
from .receipts import build_stage_receipt, validator_identity, verify_stage_receipt

QA_GATES: tuple[str, ...] = ("framework-qa", "source-qa")


def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def toolchain_digest(toolchain_id: str) -> str:
    """Return the canonical binding digest of one frozen toolchain literal."""

    return content_digest(
        {
            "kind": "synthetic-qa-toolchain",
            "schema_version": 1,
            "toolchain_id": toolchain_id,
        }
    )


def _read_canonical(root: Path, relative: str, label: str) -> tuple[dict[str, Any], str]:
    handle = open_regular_beneath(root, relative)
    with handle:
        payload = handle.read(MAX_DOCUMENT_BYTES + 1)
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{label} exceeds the document budget",
            reference=relative,
        )
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{label} is not stored in canonical byte form",
            reference=relative,
        )
    return dict(document), content_digest(document)


def _read_check_records(
    root: Path, gate: str, evidence: Mapping[str, Any]
) -> list[tuple[dict[str, Any], str]]:
    """Read exactly the declared per-check records for ``gate``."""

    expected_names = tuple(
        f"{check['check_id']}.json" for check in evidence["checks"]
    )
    if list(list_directory_beneath(root, gate)) != list(expected_names):
        raise _fail(
            "the QA evidence directory does not contain exactly the declared records",
            gate,
        )
    records: list[tuple[dict[str, Any], str]] = []
    for expected_name, check in zip(expected_names, evidence["checks"]):
        relative = validate_relative_member(f"{gate}/{expected_name}")
        record, digest = _read_canonical(root, relative, "QA per-check record")
        validated = validate_qa_check_record(record, gate, check["check_id"])
        if digest != check["evidence_digest"]:
            raise _fail(
                "a per-check record digest does not match the QA evidence digest",
                f"{gate}/{expected_name}",
            )
        for field in ("executed", "status", "failed", "mandatory_skipped"):
            if validated[field] != check[field]:
                raise _fail(
                    f"per-check record {field} does not match the QA evidence",
                    f"{gate}/{expected_name}",
                )
        for field in ("source_set_digest", "toolchain_id"):
            if validated[field] != evidence[field]:
                raise _fail(
                    f"per-check record {field} does not match the QA evidence",
                    f"{gate}/{expected_name}",
                )
        records.append((validated, digest))
    return records


def read_qa_evidence(
    *,
    qa_evidence_root: Path,
    gate: str,
    expected_document_digest: str,
    profile_digest: str,
    source_set_digest: str,
) -> tuple[dict[str, Any], str]:
    """Read and fully verify one pinned QA evidence document and its records."""

    if gate not in QA_EVIDENCE_NAMES:
        raise _fail("unknown QA gate", "qa_gate")
    if not isinstance(qa_evidence_root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT, "qa_evidence_root must be a Path", field_path="qa_evidence_root"
        )
    anchor = require_anchor(expected_document_digest, f"expected_{gate.replace('-', '_')}_digest")
    root = require_safe_root(qa_evidence_root)
    document, digest = _read_canonical(
        root, QA_EVIDENCE_NAMES[gate], f"{gate} evidence"
    )
    evidence = validate_qa_evidence(document, gate)
    if digest != anchor:
        raise _fail(
            "QA evidence digest does not match the independently pinned anchor",
            "qa-evidence",
        )
    if evidence["profile_digest"] != profile_digest:
        raise _fail("QA evidence profile binding does not match", "profile_digest")
    if evidence["source_set_digest"] != source_set_digest:
        raise _fail("QA evidence source binding does not match", "source_set_digest")
    _read_check_records(root, gate, evidence)
    return evidence, digest


def build_qa_receipt(
    *,
    gate: str,
    subject: Mapping[str, Any],
    evidence_document: Mapping[str, Any],
    evidence_digest: str,
    profile_digest: str,
    source_set_digest: str,
) -> dict[str, Any]:
    """Build one QA receipt binding the exact pinned evidence bytes."""

    evidence = validate_qa_evidence(evidence_document, gate)
    if evidence["profile_digest"] != profile_digest:
        raise _fail("QA evidence profile binding does not match", "profile_digest")
    if evidence["source_set_digest"] != source_set_digest:
        raise _fail("QA evidence source binding does not match", "source_set_digest")
    return build_stage_receipt(
        gate=gate,
        subject=subject,
        validator=validator_identity(gate, source_set_digest),
        inputs={
            f"{gate}-evidence": evidence_digest,
            "qualification-profile": profile_digest,
            "source-set": source_set_digest,
            "qa-toolchain": toolchain_digest(evidence["toolchain_id"]),
        },
        dependencies=(),
        outputs={f"{gate}-evidence": evidence_digest},
        profile_digest=profile_digest,
    )


def verify_qa_receipt(
    *,
    gate: str,
    receipt_document: Mapping[str, Any],
    subject: Mapping[str, Any],
    evidence_document: Mapping[str, Any],
    evidence_digest: str,
    profile_digest: str,
    source_set_digest: str,
) -> None:
    evidence = validate_qa_evidence(evidence_document, gate)
    verify_stage_receipt(
        receipt_document,
        gate=gate,
        source_set_digest=source_set_digest,
        expected_subject=subject,
        inputs={
            f"{gate}-evidence": evidence_digest,
            "qualification-profile": profile_digest,
            "source-set": source_set_digest,
            "qa-toolchain": toolchain_digest(evidence["toolchain_id"]),
        },
        outputs={f"{gate}-evidence": evidence_digest},
        dependencies=(),
        profile_digest=profile_digest,
    )


__all__ = [
    "QA_GATES",
    "build_qa_receipt",
    "read_qa_evidence",
    "toolchain_digest",
    "verify_qa_receipt",
]
