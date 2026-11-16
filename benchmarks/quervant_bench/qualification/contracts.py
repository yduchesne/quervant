"""Closed internal v1 records for the BM-06 synthetic qualification chain.

Nothing here is a public BM-01 schema, a new error code or a real qualification.
Every record is a strict, closed, canonically encoded v1 document whose digest is
``config.codec.content_digest`` over the canonical payload bytes (without the
trailing newline that persisted documents carry).

The validators in this module check *shape and internal identity* only. Cross-record
semantics (gate graph, anchors, replay, QA rosters) belong to the other BM-06
modules; a syntactically valid record is never sufficient for a gate PASS.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..analysis.contracts import DECISION_STATUSES
from ..config.codec import canonical_document_bytes, content_digest
from ..config.contracts import derive_origin_scope, validate_origin_scope
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCHEMA_UNSUPPORTED,
    BM_SCOPE_MISMATCH,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import (
    validate_digest,
    validate_positive_int,
    validate_semantic_id,
    validate_uuid4,
)
from ..evidence.paths import validate_relative_member

SCHEMA_VERSION = 1
EVIDENCE_ORIGIN = "synthetic"
QUALIFICATION_SCOPE = "simulated"

PROFILE_KIND = "synthetic-qualification-profile"
QA_EVIDENCE_KIND = "synthetic-qa-evidence"
QA_CHECK_KIND = "synthetic-qa-check"
ADMISSION_INDEX_KIND = "synthetic-sealed-admission-index"
ASSESSMENT_KIND = "synthetic-verification-assessment"
ACCEPTANCE_KIND = "synthetic-acceptance-summary"
SNAPSHOT_KIND = "simulated-freeze-snapshot"
MANIFEST_KIND = "simulated-qualification-manifest"

#: The seven BM-01 receipt gates, in the normative qualification order.
GATE_ORDER: tuple[str, ...] = (
    "admission",
    "analysis",
    "verification",
    "framework-qa",
    "source-qa",
    "acceptance",
    "attestation",
)

FRAMEWORK_QA_ROSTER: tuple[str, ...] = (
    "python-contracts",
    "python-mutations",
    "python-vertical",
)
SOURCE_QA_ROSTER: tuple[str, ...] = (
    "rust-clippy",
    "rust-coverage",
    "rust-format",
    "rust-msrv",
    "rust-stable",
    "rustfs-service",
)
VERIFIER_CHECK_IDS: tuple[str, ...] = (
    "VC-01-SCOPE",
    "VC-02-PROFILE-BINDINGS",
    "VC-03-STRUCTURAL-REPLAY",
    "VC-04-SEALED-INPUT-INVENTORY",
    "VC-05-INDEPENDENT-STATISTICS",
    "VC-06-INDEPENDENT-BOOTSTRAP",
    "VC-07-INDEPENDENT-POLICY",
    "VC-08-OUTPUT-IDENTITY",
    "VC-09-POST-READ-INTEGRITY",
)
FRAMEWORK_TOOLCHAIN_ID = "python-3-12"
SOURCE_TOOLCHAIN_ID = "rust-1-85-and-1-98"

PROFILE_ID = "synthetic-framework"
PROFILE_VERSION = 1
MAX_DOCUMENT_BYTES = 1_048_576

#: Durable member names in normative creation order; ``manifest.json`` is last.
MEMBER_NAMES: tuple[str, ...] = (
    "admission-index.json",
    "admission.json",
    "analysis.json",
    "policy.json",
    "analysis-receipt.json",
    "verification-assessment.json",
    "verification.json",
    "framework-qa-evidence.json",
    "framework-qa.json",
    "source-qa-evidence.json",
    "source-qa.json",
    "acceptance-summary.json",
    "acceptance.json",
    "attestation.json",
    "manifest.json",
)
MANIFEST_NAME = "manifest.json"
PENDING_NAME = "manifest.pending"
ATTESTATION_NAME = "attestation.json"
MANIFEST_MEMBERS: tuple[str, ...] = tuple(
    sorted(MEMBER_NAMES[:14])
)
FREEZE_MEMBERS: tuple[str, ...] = tuple(
    sorted(MEMBER_NAMES[:13])
)

#: Canonical JSON file names consumed/produced for each QA gate.
QA_EVIDENCE_NAMES: dict[str, str] = {
    "framework-qa": "framework-qa-evidence.json",
    "source-qa": "source-qa-evidence.json",
}

_COUNTS_KEYS = frozenset(
    {
        "controls_completed",
        "treatments_completed",
        "slots_completed",
        "lane_envelopes",
        "synthetic_samples",
    }
)
_SUBJECT_KEYS = frozenset(
    {"experiment_id", "run_id", "protocol_digest", "workload_digest"}
)
_MEMBER_KEYS = frozenset({"path", "byte_length", "digest"})


@dataclass(frozen=True)
class QualificationResult:
    """The only public BM-06 result value."""

    disposition: str
    experiment_id: str
    run_id: str
    manifest_digest: str
    attestation_receipt_id: str
    output_directory: Path


def _schema(message: str, field: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field)


def _identity(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def require_mapping(document: object, field: str) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        raise _schema(f"{field} must be a JSON object", field)
    return document


def require_closed(
    document: object, field: str, expected: frozenset[str] | set[str]
) -> Mapping[str, Any]:
    """Return ``document`` after enforcing an exact closed field set."""

    doc = require_mapping(document, field)
    keys = set(doc)
    missing = sorted(expected - keys)
    if missing:
        raise _schema(f"{field} is missing required field {missing[0]!r}", field)
    extra = sorted(keys - expected)
    if extra:
        raise _schema(f"{field} contains unknown field {extra[0]!r}", field)
    return doc


def require_uint(value: object, field: str, *, maximum: int | None = None) -> int:
    """Validate a non-negative integer that must not be a boolean."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise _schema(f"{field} must be an integer", field)
    if value < 0:
        raise _schema(f"{field} must be non-negative", field)
    if maximum is not None and value > maximum:
        raise _schema(f"{field} must not exceed {maximum}", field)
    return value


def require_true(value: object, field: str) -> bool:
    if value is not True:
        raise _identity(f"{field} must be true for a passing gate", field)
    return True


def require_version(document: Mapping[str, Any], field: str) -> int:
    version = document.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _schema(f"{field}.schema_version must be an integer", "schema_version")
    if version != SCHEMA_VERSION:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            f"{field}.schema_version {version} is not supported",
            field_path="schema_version",
        )
    return version


def require_kind(document: Mapping[str, Any], kind: str, field: str) -> None:
    if document.get("kind") != kind:
        raise _schema(f"{field}.kind must be {kind!r}", "kind")


def require_origin_scope(document: Mapping[str, Any]) -> tuple[str, str]:
    return validate_origin_scope(
        document.get("evidence_origin"), document.get("qualification_scope")
    )


def require_synthetic_scope(document: Mapping[str, Any]) -> None:
    origin, scope = require_origin_scope(document)
    if (origin, scope) != (EVIDENCE_ORIGIN, QUALIFICATION_SCOPE):
        raise BenchError(
            BM_SCOPE_MISMATCH,
            "BM-06 qualifies synthetic/simulated evidence only",
            field_path="qualification_scope",
        )


def require_bundle_scope(bundle: object) -> None:
    """Reject any non-synthetic experiment bundle before touching evidence."""

    from ..config.contracts import ExperimentBundle

    if not isinstance(bundle, ExperimentBundle):
        raise _schema("a validated ExperimentBundle is required", "bundle")
    origin, scope = derive_origin_scope(bundle)
    adapter_document = bundle.adapter_document
    declared = (
        adapter_document.get("evidence_origin", origin),
        adapter_document.get("qualification_scope", scope),
    )
    if declared != (EVIDENCE_ORIGIN, QUALIFICATION_SCOPE):
        raise BenchError(
            BM_SCOPE_MISMATCH,
            "BM-06 accepts synthetic/simulated declarations only",
            field_path="adapter.qualification_scope",
        )


def subject_document(bundle: Any, run_id: str) -> dict[str, str]:
    """Build the BM-01 receipt subject for one qualified run."""

    return {
        "experiment_id": validate_semantic_id(
            bundle.experiment.experiment_id, "subject.experiment_id"
        ),
        "run_id": validate_uuid4(run_id, "subject.run_id"),
        "protocol_digest": validate_digest(
            bundle.protocol_digest, "subject.protocol_digest"
        ),
        "workload_digest": validate_digest(
            bundle.workload_digest, "subject.workload_digest"
        ),
    }


def validate_subject(value: object, field: str = "subject") -> dict[str, str]:
    subject = require_closed(value, field, _SUBJECT_KEYS)
    return {
        "experiment_id": validate_semantic_id(
            subject["experiment_id"], f"{field}.experiment_id"
        ),
        "run_id": validate_uuid4(subject["run_id"], f"{field}.run_id"),
        "protocol_digest": validate_digest(
            subject["protocol_digest"], f"{field}.protocol_digest"
        ),
        "workload_digest": validate_digest(
            subject["workload_digest"], f"{field}.workload_digest"
        ),
    }


def bound_payload(document: Mapping[str, Any], field: str) -> bytes:
    """Return canonical bytes, rejecting documents over the 1 MiB budget."""

    payload = canonical_document_bytes(dict(document))
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{field} exceeds the {MAX_DOCUMENT_BYTES}-byte budget",
            field_path=field,
        )
    return payload


def roster_for(gate: str) -> tuple[str, ...]:
    if gate == "framework-qa":
        return FRAMEWORK_QA_ROSTER
    if gate == "source-qa":
        return SOURCE_QA_ROSTER
    raise _schema(f"{gate} is not a QA gate", "qa_gate")


def toolchain_for(gate: str) -> str:
    if gate == "framework-qa":
        return FRAMEWORK_TOOLCHAIN_ID
    if gate == "source-qa":
        return SOURCE_TOOLCHAIN_ID
    raise _schema(f"{gate} is not a QA gate", "qa_gate")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

_PROFILE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "profile_id",
        "profile_version",
        "evidence_origin",
        "qualification_scope",
        "required_gates",
        "required_verifier_checks",
        "framework_qa_roster",
        "source_qa_roster",
        "max_document_bytes",
    }
)


def validate_profile(document: object) -> dict[str, Any]:
    """Validate the exact versioned synthetic qualification profile."""

    doc = require_closed(document, "profile", _PROFILE_KEYS)
    require_version(doc, "profile")
    require_kind(doc, PROFILE_KIND, "profile")
    if doc["profile_id"] != PROFILE_ID:
        raise _identity("profile.profile_id is not the frozen profile", "profile_id")
    if validate_positive_int(doc["profile_version"], "profile_version") != PROFILE_VERSION:
        raise _identity("profile.profile_version is not supported", "profile_version")
    require_synthetic_scope(doc)
    if doc["required_gates"] != list(GATE_ORDER):
        raise _identity("profile.required_gates is not the frozen gate list", "required_gates")
    if doc["required_verifier_checks"] != list(VERIFIER_CHECK_IDS):
        raise _identity(
            "profile.required_verifier_checks is not the frozen registry",
            "required_verifier_checks",
        )
    if doc["framework_qa_roster"] != list(FRAMEWORK_QA_ROSTER):
        raise _identity("profile.framework_qa_roster is not the frozen roster", "framework_qa_roster")
    if doc["source_qa_roster"] != list(SOURCE_QA_ROSTER):
        raise _identity("profile.source_qa_roster is not the frozen roster", "source_qa_roster")
    if require_uint(doc["max_document_bytes"], "max_document_bytes") != MAX_DOCUMENT_BYTES:
        raise _identity(
            "profile.max_document_bytes is not the reviewed budget", "max_document_bytes"
        )
    bound_payload(doc, "profile")
    return dict(doc)


# ---------------------------------------------------------------------------
# QA evidence and per-check records
# ---------------------------------------------------------------------------

_QA_EVIDENCE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "qa_gate",
        "profile_digest",
        "source_set_digest",
        "toolchain_id",
        "checks",
    }
)
_QA_CHECK_KEYS = frozenset(
    {
        "check_id",
        "executed",
        "status",
        "failed",
        "mandatory_skipped",
        "evidence_digest",
    }
)
_QA_CHECK_RECORD_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "qa_gate",
        "check_id",
        "evidence_origin",
        "qualification_scope",
        "source_set_digest",
        "toolchain_id",
        "executed",
        "status",
        "failed",
        "mandatory_skipped",
    }
)


def validate_qa_check_shape(document: object, field: str) -> dict[str, Any]:
    check = require_closed(document, field, _QA_CHECK_KEYS)
    check_id = check["check_id"]
    if not isinstance(check_id, str) or not check_id:
        raise _schema(f"{field}.check_id must be a non-empty string", f"{field}.check_id")
    require_true(check["executed"], f"{field}.executed")
    if check["status"] != "pass":
        raise _identity(f"{field}.status must be 'pass'", f"{field}.status")
    if require_uint(check["failed"], f"{field}.failed") != 0:
        raise _identity(f"{field}.failed must be zero", f"{field}.failed")
    if require_uint(check["mandatory_skipped"], f"{field}.mandatory_skipped") != 0:
        raise _identity(
            f"{field}.mandatory_skipped must be zero", f"{field}.mandatory_skipped"
        )
    validate_digest(check["evidence_digest"], f"{field}.evidence_digest")
    return dict(check)


def validate_qa_evidence(document: object, gate: str) -> dict[str, Any]:
    """Validate one closed QA evidence document against its exact roster."""

    roster = roster_for(gate)
    doc = require_closed(document, f"{gate}-evidence", _QA_EVIDENCE_KEYS)
    require_version(doc, f"{gate}-evidence")
    require_kind(doc, QA_EVIDENCE_KIND, f"{gate}-evidence")
    require_synthetic_scope(doc)
    if doc["qa_gate"] != gate:
        raise _identity("QA evidence gate does not match the requested gate", "qa_gate")
    validate_digest(doc["profile_digest"], "profile_digest")
    validate_digest(doc["source_set_digest"], "source_set_digest")
    if doc["toolchain_id"] != toolchain_for(gate):
        raise _identity(
            "QA evidence toolchain_id is not the frozen literal", "toolchain_id"
        )
    raw_checks = doc["checks"]
    if not isinstance(raw_checks, list):
        raise _schema("QA evidence checks must be an array", "checks")
    checks = [
        validate_qa_check_shape(raw, f"checks[{index}]")
        for index, raw in enumerate(raw_checks)
    ]
    if tuple(check["check_id"] for check in checks) != roster:
        raise _identity(
            "QA evidence checks must be exactly the frozen roster in order", "checks"
        )
    digests = [check["evidence_digest"] for check in checks]
    if len(set(digests)) != len(digests):
        raise _identity("QA evidence check digests must be unique", "checks")
    bound_payload(doc, f"{gate}-evidence")
    return dict(doc)


def validate_qa_check_record(document: object, gate: str, check_id: str) -> dict[str, Any]:
    """Validate one external per-check record against its constructed path identity."""

    roster_for(gate)
    doc = require_closed(document, "qa-check-record", _QA_CHECK_RECORD_KEYS)
    require_version(doc, "qa-check-record")
    require_kind(doc, QA_CHECK_KIND, "qa-check-record")
    require_synthetic_scope(doc)
    if doc["qa_gate"] != gate:
        raise _identity("per-check record gate does not match", "qa_gate")
    if doc["check_id"] != check_id:
        raise _identity("per-check record check_id does not match", "check_id")
    validate_digest(doc["source_set_digest"], "source_set_digest")
    if doc["toolchain_id"] != toolchain_for(gate):
        raise _identity("per-check toolchain_id is not the frozen literal", "toolchain_id")
    require_true(doc["executed"], "executed")
    if doc["status"] != "pass":
        raise _identity("per-check status must be 'pass'", "status")
    if require_uint(doc["failed"], "failed") != 0:
        raise _identity("per-check failed must be zero", "failed")
    if require_uint(doc["mandatory_skipped"], "mandatory_skipped") != 0:
        raise _identity("per-check mandatory_skipped must be zero", "mandatory_skipped")
    bound_payload(doc, "qa-check-record")
    return dict(doc)


# ---------------------------------------------------------------------------
# Admission index
# ---------------------------------------------------------------------------

_ADMISSION_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "subject",
        "evidence_origin",
        "qualification_scope",
        "seal_raw_digest",
        "freeze_digest",
        "scenario_digest",
        "protocol_digest",
        "profile_digest",
        "source_set_digest",
        "counts",
        "files",
    }
)
_FILE_KEYS = frozenset({"path", "byte_length", "raw_digest"})


def validate_member_list(
    value: object,
    field: str,
    expected_paths: tuple[str, ...],
    *,
    allow_relative: bool = False,
) -> list[dict[str, Any]]:
    """Validate a sorted, exact, closed member record list."""

    if not isinstance(value, list):
        raise _schema(f"{field} must be an array", field)
    members: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        entry = require_closed(raw, f"{field}[{index}]", _MEMBER_KEYS)
        path = entry["path"]
        if not isinstance(path, str):
            raise _schema(f"{field}[{index}].path must be a string", f"{field}[{index}].path")
        if allow_relative:
            validate_relative_member(path)
        elif path not in expected_paths:
            raise _identity(
                f"{field}[{index}].path is not a durable member", f"{field}[{index}].path"
            )
        members.append(
            {
                "path": path,
                "byte_length": require_uint(
                    entry["byte_length"], f"{field}[{index}].byte_length"
                ),
                "digest": validate_digest(
                    entry["digest"], f"{field}[{index}].digest"
                ),
            }
        )
    paths = [member["path"] for member in members]
    if paths != sorted(paths):
        raise _identity(f"{field} must be sorted by path", field)
    if len(set(paths)) != len(paths):
        raise _identity(f"{field} must not contain duplicate paths", field)
    if tuple(paths) != expected_paths:
        raise _identity(f"{field} does not list exactly the expected paths", field)
    return members


def validate_admission_index(document: object) -> dict[str, Any]:
    """Validate the closed sealed-run admission index (shape and identity fields)."""

    doc = require_closed(document, "admission-index", _ADMISSION_KEYS)
    require_version(doc, "admission-index")
    require_kind(doc, ADMISSION_INDEX_KIND, "admission-index")
    validate_subject(doc["subject"])
    require_synthetic_scope(doc)
    for name in (
        "seal_raw_digest",
        "freeze_digest",
        "scenario_digest",
        "protocol_digest",
        "profile_digest",
        "source_set_digest",
    ):
        validate_digest(doc[name], name)
    counts = require_closed(doc["counts"], "counts", _COUNTS_KEYS)
    for name in sorted(_COUNTS_KEYS):
        require_uint(counts[name], f"counts.{name}")
    raw_files = doc["files"]
    if not isinstance(raw_files, list) or not raw_files:
        raise _schema("admission-index.files must be a non-empty array", "files")
    files: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_files):
        entry = require_closed(raw, f"files[{index}]", _FILE_KEYS)
        path = validate_relative_member(entry["path"])
        files.append(
            {
                "path": path,
                "byte_length": require_uint(
                    entry["byte_length"], f"files[{index}].byte_length"
                ),
                "raw_digest": validate_digest(
                    entry["raw_digest"], f"files[{index}].raw_digest"
                ),
            }
        )
    paths = [entry["path"] for entry in files]
    if paths != sorted(paths):
        raise _identity("admission-index.files must be sorted by path", "files")
    if len(set(paths)) != len(paths):
        raise _identity("admission-index.files paths must be unique", "files")
    if "seal.json" in paths:
        raise _identity("admission-index.files must not list seal.json", "files")
    bound_payload(doc, "admission-index")
    return dict(doc)


# ---------------------------------------------------------------------------
# Verification assessment wrapper
# ---------------------------------------------------------------------------

_ASSESSMENT_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "status",
        "experiment_id",
        "run_id",
        "evidence_origin",
        "qualification_scope",
        "analysis_digest",
        "policy_digest",
        "source_seal_digest",
        "reference_id",
        "check_ids",
    }
)


def validate_verification_assessment(
    document: object, *, expected_check_ids: tuple[str, ...] = VERIFIER_CHECK_IDS
) -> dict[str, Any]:
    doc = require_closed(document, "verification-assessment", _ASSESSMENT_KEYS)
    require_version(doc, "verification-assessment")
    require_kind(doc, ASSESSMENT_KIND, "verification-assessment")
    if doc["status"] != "verified-synthetic":
        raise _identity(
            "verification-assessment.status must be 'verified-synthetic'", "status"
        )
    validate_semantic_id(doc["experiment_id"], "experiment_id")
    validate_uuid4(doc["run_id"])
    require_synthetic_scope(doc)
    for name in ("analysis_digest", "policy_digest", "source_seal_digest"):
        validate_digest(doc[name], name)
    if doc["reference_id"] != "independent-synthetic-v1":
        raise _identity(
            "verification-assessment.reference_id is not the frozen reference",
            "reference_id",
        )
    if not isinstance(doc["check_ids"], list):
        raise _schema("verification-assessment.check_ids must be an array", "check_ids")
    if tuple(doc["check_ids"]) != expected_check_ids:
        raise _identity(
            "verification-assessment.check_ids is not the frozen registry", "check_ids"
        )
    bound_payload(doc, "verification-assessment")
    return dict(doc)


# ---------------------------------------------------------------------------
# Acceptance summary
# ---------------------------------------------------------------------------

_ACCEPTANCE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "subject",
        "evidence_origin",
        "qualification_scope",
        "profile_digest",
        "source_set_digest",
        "gate_receipt_ids",
        "framework_qa_evidence_digest",
        "source_qa_evidence_digest",
        "policy_decision_status",
    }
)
_ACCEPTANCE_GATES = ("acceptance", "admission", "analysis", "framework-qa", "source-qa", "verification")


def validate_acceptance_summary(document: object) -> dict[str, Any]:
    doc = require_closed(document, "acceptance-summary", _ACCEPTANCE_KEYS)
    require_version(doc, "acceptance-summary")
    require_kind(doc, ACCEPTANCE_KIND, "acceptance-summary")
    validate_subject(doc["subject"])
    require_synthetic_scope(doc)
    validate_digest(doc["profile_digest"], "profile_digest")
    validate_digest(doc["source_set_digest"], "source_set_digest")
    validate_digest(
        doc["framework_qa_evidence_digest"], "framework_qa_evidence_digest"
    )
    validate_digest(doc["source_qa_evidence_digest"], "source_qa_evidence_digest")
    ids = require_closed(
        doc["gate_receipt_ids"],
        "gate_receipt_ids",
        frozenset({"admission", "analysis", "verification", "framework-qa", "source-qa"}),
    )
    for gate in sorted(ids):
        validate_digest(ids[gate], f"gate_receipt_ids.{gate}")
    if doc["policy_decision_status"] not in DECISION_STATUSES:
        raise _identity(
            "acceptance-summary.policy_decision_status is not a frozen decision",
            "policy_decision_status",
        )
    bound_payload(doc, "acceptance-summary")
    return dict(doc)


# ---------------------------------------------------------------------------
# Freeze snapshot and final manifest
# ---------------------------------------------------------------------------

_SNAPSHOT_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "subject",
        "evidence_origin",
        "qualification_scope",
        "profile_digest",
        "source_set_digest",
        "members",
    }
)
_MANIFEST_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "subject",
        "evidence_origin",
        "qualification_scope",
        "profile_digest",
        "source_set_digest",
        "freeze_snapshot",
        "attestation_digest",
        "members",
    }
)


def validate_freeze_snapshot(document: object) -> dict[str, Any]:
    doc = require_closed(document, "freeze-snapshot", _SNAPSHOT_KEYS)
    require_version(doc, "freeze-snapshot")
    require_kind(doc, SNAPSHOT_KIND, "freeze-snapshot")
    validate_subject(doc["subject"])
    require_synthetic_scope(doc)
    validate_digest(doc["profile_digest"], "profile_digest")
    validate_digest(doc["source_set_digest"], "source_set_digest")
    validate_member_list(doc["members"], "members", FREEZE_MEMBERS)
    bound_payload(doc, "freeze-snapshot")
    return dict(doc)


def validate_manifest(document: object) -> dict[str, Any]:
    doc = require_closed(document, "manifest", _MANIFEST_KEYS)
    require_version(doc, "manifest")
    require_kind(doc, MANIFEST_KIND, "manifest")
    validate_subject(doc["subject"])
    require_synthetic_scope(doc)
    validate_digest(doc["profile_digest"], "profile_digest")
    validate_digest(doc["source_set_digest"], "source_set_digest")
    validate_digest(doc["attestation_digest"], "attestation_digest")
    snapshot = validate_freeze_snapshot(doc["freeze_snapshot"])
    for name in ("subject", "profile_digest", "source_set_digest"):
        if snapshot[name] != doc[name]:
            raise _identity(
                f"manifest.freeze_snapshot.{name} does not match the manifest", name
            )
    validate_member_list(doc["members"], "members", MANIFEST_MEMBERS)
    attestation = [member for member in doc["members"] if member["path"] == ATTESTATION_NAME]
    if len(attestation) != 1 or attestation[0]["digest"] != doc["attestation_digest"]:
        raise _identity(
            "manifest.members attestation digest does not match attestation_digest",
            "attestation_digest",
        )
    bound_payload(doc, "manifest")
    return dict(doc)


def document_digest(document: Mapping[str, Any]) -> str:
    """Return the canonical content digest used for every internal record."""

    return content_digest(dict(document))


__all__ = [
    "ACCEPTANCE_KIND",
    "ADMISSION_INDEX_KIND",
    "ASSESSMENT_KIND",
    "ATTESTATION_NAME",
    "EVIDENCE_ORIGIN",
    "FRAMEWORK_QA_ROSTER",
    "FRAMEWORK_TOOLCHAIN_ID",
    "FREEZE_MEMBERS",
    "GATE_ORDER",
    "MANIFEST_KIND",
    "MANIFEST_MEMBERS",
    "MANIFEST_NAME",
    "MAX_DOCUMENT_BYTES",
    "MEMBER_NAMES",
    "PENDING_NAME",
    "PROFILE_ID",
    "PROFILE_KIND",
    "PROFILE_VERSION",
    "QA_CHECK_KIND",
    "QA_EVIDENCE_KIND",
    "QA_EVIDENCE_NAMES",
    "QUALIFICATION_SCOPE",
    "QualificationResult",
    "SNAPSHOT_KIND",
    "SOURCE_QA_ROSTER",
    "SOURCE_TOOLCHAIN_ID",
    "VERIFIER_CHECK_IDS",
    "bound_payload",
    "document_digest",
    "require_bundle_scope",
    "require_closed",
    "require_kind",
    "require_mapping",
    "require_origin_scope",
    "require_synthetic_scope",
    "require_true",
    "require_uint",
    "require_version",
    "roster_for",
    "subject_document",
    "toolchain_for",
    "validate_acceptance_summary",
    "validate_admission_index",
    "validate_freeze_snapshot",
    "validate_manifest",
    "validate_member_list",
    "validate_profile",
    "validate_qa_check_record",
    "validate_qa_check_shape",
    "validate_qa_evidence",
    "validate_subject",
    "validate_verification_assessment",
]
