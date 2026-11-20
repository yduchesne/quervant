"""Closed official-v1 record contracts for real qualification evidence.

Every document produced here carries ``evidence_origin="real"`` and
``qualification_scope="official"``. The validators check *shape and internal
identity* only; cross-record semantics (gate graph, trust anchors, raw inventory,
recomputation) belong to the other ``official`` modules.

Nothing in this module imports a synthetic-scope predicate: the official and
synthetic domains must be mutually inassimilable.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from ..config.codec import content_digest
from ..config.contracts import validate_origin_scope
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
    validate_semantic_id,
    validate_source_commit,
    validate_uuid4,
)
from ..evidence.paths import validate_relative_member
from ..qualification.contracts import (
    bound_payload,
    document_digest,
    require_closed,
    require_kind,
    require_mapping,
    require_true,
    require_uint,
    require_version,
    validate_subject,
)

REAL_ORIGIN = "real"
OFFICIAL_SCOPE = "official"
HISTORICAL_SCOPE = "historical_replay"
SCHEMA_VERSION = 1
CURRENT_BASELINE_PROFILE = "current-baseline-v2"
MAX_DOCUMENT_BYTES = 1_048_576

OFFICIAL_PROFILE_KIND = "official-qualification-profile"
PROFILE_ID = "official-qualification-facade"
PROFILE_VERSION = 1

EVIDENCE_INDEX_KIND = "official-evidence-admission-index"
ANALYSIS_KIND = "official-analysis-result"
POLICY_KIND = "official-policy-decision"
ASSESSMENT_KIND = "official-verification-assessment"
FRAMEWORK_QA_KIND = "official-framework-qa-evidence"
SOURCE_QA_KIND = "official-source-qa-evidence"
ACCEPTANCE_KIND = "official-acceptance-summary"
SNAPSHOT_KIND = "official-freeze-snapshot"
MANIFEST_KIND = "official-qualification-manifest"
TEMPORARY_AUTHORIZATION_KIND = "official-study-authorization"

#: The exact 15 durable member names, in normative creation order.
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
#: The fourteen members a manifest must describe.
MANIFEST_MEMBERS: tuple[str, ...] = tuple(sorted(MEMBER_NAMES[:14]))
#: The thirteen members frozen before the attestation receipt exists.
FREEZE_MEMBERS: tuple[str, ...] = tuple(sorted(MEMBER_NAMES[:13]))

#: The seven logical gates, in normative order.
OFFICIAL_GATE_ORDER: tuple[str, ...] = (
    "admission",
    "analysis",
    "verification",
    "framework-qa",
    "source-qa",
    "acceptance",
    "attestation",
)

#: Gate -> exact required input binding names (already sorted).
INPUT_NAMES: dict[str, tuple[str, ...]] = {
    "admission": (
        "authorization",
        "backend-protocol",
        "binary-manifest",
        "control-assessment",
        "corpus-manifest",
        "host-preflight",
        "raw-series-root",
        "source-set",
        "workload",
    ),
    "analysis": (
        "admission-index",
        "analysis-profile",
        "policy-profile",
        "raw-series-root",
        "source-set",
    ),
    "verification": (
        "analysis",
        "original-verifier",
        "policy",
        "raw-series-root",
        "source-set",
    ),
    "framework-qa": (
        "framework-qa-evidence",
        "qa-roster",
        "source-set",
        "toolchain",
    ),
    "source-qa": (
        "qa-roster",
        "source-qa-evidence",
        "source-set",
        "toolchain",
    ),
    "acceptance": (
        "admission-index",
        "analysis",
        "authorization",
        "control-assessment",
        "framework-qa-evidence",
        "historical-parity",
        "policy",
        "source-qa-evidence",
        "source-set",
        "verification-assessment",
    ),
    "attestation": ("authorization", "freeze-snapshot", "source-set"),
}

# Version selection comes from a freshly verified authorization, never from the
# receipt being checked. The v1 roster remains byte-for-byte unchanged.
INPUT_NAMES_V2: dict[str, tuple[str, ...]] = {
    **INPUT_NAMES,
    "acceptance": (
        "admission-index", "analysis", "authorization", "control-assessment",
        "framework-qa-evidence", "history-report", "policy", "relative-effects",
        "source-qa-evidence", "source-set", "verification-assessment",
    ),
}

#: Gate -> exact required output binding names (already sorted).
OUTPUT_NAMES: dict[str, tuple[str, ...]] = {
    "admission": ("admission-index",),
    "analysis": ("analysis", "policy"),
    "verification": ("verification-assessment",),
    "framework-qa": ("framework-qa-evidence",),
    "source-qa": ("source-qa-evidence",),
    "acceptance": ("acceptance-summary",),
    "attestation": ("freeze-snapshot",),
}

#: Gate -> exact required upstream gate edges (sorted).
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
OFFICIAL_VALIDATOR_IDS: dict[str, str] = {
    gate: f"official-{gate}" for gate in OFFICIAL_GATE_ORDER
}
VALIDATOR_VERSION = 1
OFFICIAL_VALIDATOR_IDS_V2: dict[str, str] = dict(OFFICIAL_VALIDATOR_IDS)

#: Independent verification check registry (Gate C).
VERIFIER_CHECK_IDS: tuple[str, ...] = (
    "RV-01-SCOPE",
    "RV-02-G0",
    "RV-03-RAW-INVENTORY",
    "RV-04-ORACLE",
    "RV-05-SCHEDULE",
    "RV-06-HOST-CONTROLS",
    "RV-07-STATISTICS",
    "RV-08-POLICY",
    "RV-09-IDENTITY",
    "RV-10-POST-READ-INTEGRITY",
)
VERIFICATION_STATUSES: tuple[str, ...] = (
    "VERIFIED_REAL",
    "BLOCKED",
    "FAILED",
)
SERIES_STATUSES: tuple[str, ...] = ("ADMITTED_REAL", "BLOCKED", "INVALID")

#: Gate B decision vocabulary (real, not the synthetic analysis vocabulary).
DECISION_INCONCLUSIVE = "INCONCLUSIVE"
DECISION_POLICY_NOT_DERIVABLE = "POLICY_NOT_DERIVABLE"
DECISION_SELECTED = "SELECTED_ELIGIBLE_REAL"
DECISION_TIE_PREFERENCE = "TIE_PREFERENCE_NOT_PROVEN_FASTER"
DECISION_BASELINE_ONLY = "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE"
DECISION_PER_K_RESOLVED = "PER_K_POLICY_RESOLVED"
OFFICIAL_DECISION_STATUSES: frozenset[str] = frozenset(
    {
        DECISION_INCONCLUSIVE,
        DECISION_POLICY_NOT_DERIVABLE,
        DECISION_SELECTED,
        DECISION_TIE_PREFERENCE,
        DECISION_BASELINE_ONLY,
        DECISION_PER_K_RESOLVED,
    }
)
#: Decisions that cannot support an accepted Gate D/E qualification.
UNRESOLVED_DECISIONS: frozenset[str] = frozenset(
    {DECISION_POLICY_NOT_DERIVABLE}
)
CANDIDATE_STATUSES: frozenset[str] = frozenset(
    {"ELIGIBLE", "INELIGIBLE", "INCONCLUSIVE"}
)

#: Family statistics-method identities.
STATISTICS_CROSS_ENGINE = "cross-engine-three-trial-range-v1"
STATISTICS_RETAINED_KEY = "retained-key-twelve-block-upper-median-v1"
OFFICIAL_STATISTICS_METHODS: frozenset[str] = frozenset(
    {STATISTICS_CROSS_ENGINE, STATISTICS_RETAINED_KEY}
)

#: Lane classes excluded from every official warm ratio policy.
EXCLUDED_LANE_CLASSES: tuple[str, ...] = (
    "process_cold",
    "scored_bm25",
    "throughput",
)
#: Measurement unit of every official ratio-bearing metric.
OFFICIAL_UNIT = "nanoseconds"

#: Historical parity dispositions.
PARITY_STATUSES: tuple[str, ...] = (
    "PASS",
    "BLOCKED",
    "FAILED",
    "NON_EQUIVALENT_CONTRACT",
    "EVIDENCE_UNAVAILABLE",
    "PRESENT_UNVERIFIED",
    "COMPARISON_COMPUTED_PENDING_REVIEW",
)
QA_STATUSES: tuple[str, ...] = ("PASS", "BLOCKED", "QA_UNVERIFIED")
CONTROL_STATUSES: tuple[str, ...] = ("PASS", "BLOCKED", "CONTROL_NOT_QUALIFIED")
ADMISSION_STATUSES: tuple[str, ...] = ("PASS", "BLOCKED")

#: Mandatory real framework QA roster (semantic slugs, executed for real).
FRAMEWORK_QA_ROSTER: tuple[str, ...] = (
    "benchmark-scripts",
    "bm-contract-inventory",
    "cross-engine-l2",
    "installed-console",
    "official-authorization-boundary",
    "official-control-boundary",
    "official-data-integrity",
    "official-deterministic",
    "official-independent-verification",
    "official-real-correctness",
    "official-source-set",
    "python-compileall",
    "python-full-suite",
    "python-mutations",
    "retained-key-l2",
)
#: Mandatory real source QA roster (semantic slugs, executed for real).
SOURCE_QA_ROSTER: tuple[str, ...] = (
    "adapter-build-lucene",
    "adapter-build-quervant",
    "adapter-build-tantivy",
    "adapter-correctness-10k-100k",
    "host-capability-readiness",
    "rust-bench-no-run",
    "rust-clippy-msrv-all-features",
    "rust-clippy-stable-all-features",
    "rust-clippy-stable-default",
    "rust-coverage-85",
    "rust-doc",
    "rust-fmt-msrv",
    "rust-fmt-stable",
    "rust-test-msrv-all-features",
    "rust-test-stable-all-features",
    "rust-test-stable-default",
    "rustfs-real-hosted",
    "source-binary-digests",
)
FRAMEWORK_TOOLCHAIN_ID = "python-3-12-pinned-venv"
SOURCE_TOOLCHAIN_ID = "rust-stable-and-1-85"

_SUBJECT_KEYS = frozenset(
    {"experiment_id", "run_id", "protocol_digest", "workload_digest"}
)
_MEMBER_KEYS = frozenset({"path", "byte_length", "digest"})
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
_QA_EVIDENCE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "qa_gate",
        "qa_roster_digest",
        "source_set_digest",
        "toolchain_id",
        "checks",
    }
)
_ADMISSION_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "subject",
        "study_id",
        "approved_design_digest",
        "authorization_digest",
        "source_set_digest",
        "host_identity_digest",
        "binary_manifest_digest",
        "corpus_manifest_digest",
        "original_verifier_digest",
        "raw_series_root_digest",
        "series_status",
        "members",
        "required_inventory",
        "comparability_digest",
    }
)
_ANALYSIS_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "subject",
        "study_id",
        "raw_series_root_digest",
        "analysis_profile_digest",
        "statistics_method_id",
        "eligible_lane_ids",
        "excluded_lane_classes",
        "control_result_digest",
        "campaigns",
        "statistics",
        "uncertainty",
        "limitations",
    }
)
_ANALYSIS_KEYS_V2 = _ANALYSIS_KEYS | {"retained_slot_statistics"}
_POLICY_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "subject",
        "study_id",
        "policy_digest",
        "analysis_digest",
        "decision_status",
        "selected_arm_id",
        "candidate_statuses",
        "reasons",
        "performance_claim_allowed",
    }
)
_ASSESSMENT_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "subject",
        "status",
        "study_id",
        "raw_series_root_digest",
        "analysis_digest",
        "policy_digest",
        "reference_id",
        "check_ids",
        "verified_claims",
    }
)
_ASSESSMENT_KEYS_V2 = _ASSESSMENT_KEYS | {
    "verification_scope", "policy_verification_status", "not_evaluated_checks",
}
_FRAMEWORK_QA_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "source_commit",
        "workflow_run_ids",
        "mandatory_jobs",
        "executed",
        "failed",
        "skipped_mandatory",
        "qa_roster_digest",
        "source_set_digest",
        "evidence_sources",
    }
)
_SOURCE_QA_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "source_commit",
        "toolchain_lock_digest",
        "source_set_digest",
        "build_digests",
        "adapter_correctness_digest",
        "host_preflight_digest",
        "mandatory_checks",
        "failed",
        "skipped_mandatory",
    }
)
_ACCEPTANCE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "subject",
        "approved_design_digest",
        "authorization_digest",
        "source_set_digest",
        "gate_receipt_ids",
        "policy_decision_status",
        "historical_parity_status",
        "required_control_status",
        "qa_status",
        "admission_status",
        "decision_scope",
    }
)
_ACCEPTANCE_KEYS_V2 = (_ACCEPTANCE_KEYS - {"historical_parity_status"}) | {
    "history_report_digest", "baseline_id", "baseline_verification_status", "policy_verification_status",
}
_SNAPSHOT_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "subject",
        "approved_design_digest",
        "authorization_digest",
        "source_set_digest",
        "members",
    }
)
_MANIFEST_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "subject",
        "approved_design_digest",
        "authorization_digest",
        "source_set_digest",
        "raw_series_root_digest",
        "freeze_snapshot",
        "attestation_digest",
        "members",
    }
)
_PROFILE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "profile_id",
        "profile_version",
        "required_gates",
        "required_verifier_checks",
        "framework_qa_roster",
        "source_qa_roster",
        "max_document_bytes",
    }
)


def _schema(message: str, field: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field)


def _identity(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def require_profile_version(value: object, field: str = "schema_version") -> int:
    """Select only the two reviewed official execution profiles."""

    if type(value) is not int or value not in (1, 2):
        raise _schema("unsupported official profile version", field)
    return value


def input_names_for(gate: str, *, profile_version: int = 1) -> tuple[str, ...]:
    version = require_profile_version(profile_version, "profile_version")
    roster = INPUT_NAMES if version == 1 else INPUT_NAMES_V2
    if type(gate) is not str or gate not in roster:
        raise _schema("unknown official gate", "gate")
    return roster[gate]


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def require_official_scope(
    document_or_origin: object, scope: object | None = None
) -> tuple[str, str]:
    """Require the ``real``/``official`` pair and return it.

    ``document_or_origin`` may be a mapping carrying
    ``evidence_origin``/``qualification_scope`` or a bare origin string (in which
    case ``scope`` must be supplied). Any other pair — including
    ``real``/``historical_replay`` and ``synthetic``/``simulated`` — is rejected
    before any side effect.
    """

    if isinstance(document_or_origin, Mapping):
        origin = document_or_origin.get("evidence_origin")
        declared_scope = document_or_origin.get("qualification_scope")
    else:
        origin = document_or_origin
        declared_scope = scope
    pair = validate_origin_scope(origin, declared_scope)
    if pair != (REAL_ORIGIN, OFFICIAL_SCOPE):
        raise BenchError(
            BM_SCOPE_MISMATCH,
            "the official facade accepts real/official evidence only",
            field_path="qualification_scope",
        )
    return pair


def require_historical_scope(
    document_or_origin: object, scope: object | None = None
) -> tuple[str, str]:
    """Require the ``real``/``historical_replay`` pair (read-only replay only)."""

    if isinstance(document_or_origin, Mapping):
        origin = document_or_origin.get("evidence_origin")
        declared_scope = document_or_origin.get("qualification_scope")
    else:
        origin = document_or_origin
        declared_scope = scope
    pair = validate_origin_scope(origin, declared_scope)
    if pair != (REAL_ORIGIN, HISTORICAL_SCOPE):
        raise BenchError(
            BM_SCOPE_MISMATCH,
            "historical replay accepts real/historical_replay evidence only",
            field_path="qualification_scope",
        )
    return pair


def validate_official_subject(subject: object, field: str = "subject") -> dict[str, str]:
    """Validate the four-key BM-01 receipt subject without widening it."""

    return validate_subject(subject, field)


# ---------------------------------------------------------------------------
# Shared closed-record helpers
# ---------------------------------------------------------------------------


def _digest_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _schema(f"{field} must be a non-empty array", field)
    return [validate_digest(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _semantic_list(value: object, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise _schema(f"{field} must be an array", field)
    if not value and not allow_empty:
        raise _schema(f"{field} must not be empty", field)
    result = [validate_semantic_id(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if result != sorted(result):
        raise _identity(f"{field} must be sorted", field)
    if len(set(result)) != len(result):
        raise _identity(f"{field} must not contain duplicates", field)
    return result


def validate_member_records(
    value: object,
    field: str,
    expected_paths: Sequence[str],
    *,
    allow_relative: bool = False,
) -> list[dict[str, Any]]:
    """Validate one sorted, exact, closed evidence member list."""

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
                f"{field}[{index}].path is not a durable member",
                f"{field}[{index}].path",
            )
        members.append(
            {
                "path": path,
                "byte_length": require_uint(
                    entry["byte_length"], f"{field}[{index}].byte_length"
                ),
                "digest": validate_digest(entry["digest"], f"{field}[{index}].digest"),
            }
        )
    paths = [member["path"] for member in members]
    if paths != sorted(paths):
        raise _identity(f"{field} must be sorted by path", field)
    if len(set(paths)) != len(paths):
        raise _identity(f"{field} must not contain duplicate paths", field)
    if expected_paths and tuple(paths) != tuple(expected_paths):
        raise _identity(f"{field} does not list exactly the expected paths", field)
    return members


def member_record(name: str, document: Mapping[str, Any]) -> dict[str, Any]:
    """Return the member identity record for one canonical document."""

    payload = bound_payload(document, name)
    return {
        "path": name,
        "byte_length": len(payload),
        "digest": document_digest(document),
    }


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def validate_official_profile(document: object) -> dict[str, Any]:
    """Validate the exact, reviewed official qualification profile."""

    doc = require_closed(document, "profile", _PROFILE_KEYS)
    require_version(doc, "profile")
    require_kind(doc, OFFICIAL_PROFILE_KIND, "profile")
    if doc["profile_id"] != PROFILE_ID:
        raise _identity("profile.profile_id is not the reviewed profile", "profile_id")
    if require_uint(doc["profile_version"], "profile_version") != PROFILE_VERSION:
        raise _identity("profile.profile_version is not supported", "profile_version")
    require_official_scope(doc)
    if doc["required_gates"] != list(OFFICIAL_GATE_ORDER):
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


def roster_for(gate: str) -> tuple[str, ...]:
    """Return the frozen QA roster for one QA gate."""

    if gate == "framework-qa":
        return FRAMEWORK_QA_ROSTER
    if gate == "source-qa":
        return SOURCE_QA_ROSTER
    raise _schema(f"{gate} is not a QA gate", "qa_gate")


def toolchain_for(gate: str) -> str:
    """Return the frozen toolchain literal for one QA gate."""

    if gate == "framework-qa":
        return FRAMEWORK_TOOLCHAIN_ID
    if gate == "source-qa":
        return SOURCE_TOOLCHAIN_ID
    raise _schema(f"{gate} is not a QA gate", "qa_gate")


# ---------------------------------------------------------------------------
# QA evidence
# ---------------------------------------------------------------------------


def validate_official_qa(document: object, gate: str) -> dict[str, Any]:
    """Validate one closed official QA evidence document against its roster."""

    roster = roster_for(gate)
    field = f"{gate}-evidence"
    doc = require_closed(document, field, _QA_EVIDENCE_KEYS)
    require_version(doc, field)
    kind = FRAMEWORK_QA_KIND if gate == "framework-qa" else SOURCE_QA_KIND
    require_kind(doc, kind, field)
    require_official_scope(doc)
    if doc["qa_gate"] != gate:
        raise _identity("QA evidence gate does not match the requested gate", "qa_gate")
    validate_digest(doc["qa_roster_digest"], "qa_roster_digest")
    validate_digest(doc["source_set_digest"], "source_set_digest")
    if doc["toolchain_id"] != toolchain_for(gate):
        raise _identity("QA evidence toolchain_id is not the frozen literal", "toolchain_id")
    raw_checks = doc["checks"]
    if not isinstance(raw_checks, list):
        raise _schema("QA evidence checks must be an array", "checks")
    checks: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_checks):
        check = require_closed(raw, f"checks[{index}]", _QA_CHECK_KEYS)
        check_id = check["check_id"]
        if not isinstance(check_id, str):
            raise _schema(f"checks[{index}].check_id must be a string", "check_id")
        require_true(check["executed"], f"checks[{index}].executed")
        if check["status"] != "pass":
            raise _identity(f"checks[{index}].status must be 'pass'", "status")
        if require_uint(check["failed"], f"checks[{index}].failed") != 0:
            raise _identity(f"checks[{index}].failed must be zero", "failed")
        if require_uint(check["mandatory_skipped"], f"checks[{index}].mandatory_skipped") != 0:
            raise _identity(
                f"checks[{index}].mandatory_skipped must be zero", "mandatory_skipped"
            )
        checks.append(
            {
                "check_id": check_id,
                "executed": True,
                "status": "pass",
                "failed": 0,
                "mandatory_skipped": 0,
                "evidence_digest": validate_digest(
                    check["evidence_digest"], f"checks[{index}].evidence_digest"
                ),
            }
        )
    if tuple(check["check_id"] for check in checks) != roster:
        raise _identity(
            "QA evidence checks must be exactly the frozen roster in order", "checks"
        )
    digests = [check["evidence_digest"] for check in checks]
    if len(set(digests)) != len(digests):
        raise _identity("QA evidence check digests must be unique", "checks")
    result = dict(doc)
    result["checks"] = checks
    bound_payload(result, field)
    return result


# ---------------------------------------------------------------------------
# Admission index (Gate A)
# ---------------------------------------------------------------------------


def validate_official_evidence_index(document: object) -> dict[str, Any]:
    """Validate the closed official admission index (Gate A output)."""

    doc = require_closed(document, "admission-index", _ADMISSION_KEYS)
    require_version(doc, "admission-index")
    require_kind(doc, EVIDENCE_INDEX_KIND, "admission-index")
    validate_official_subject(doc["subject"])
    require_official_scope(doc)
    validate_semantic_id(doc["study_id"], "study_id")
    for name in (
        "approved_design_digest",
        "authorization_digest",
        "source_set_digest",
        "host_identity_digest",
        "binary_manifest_digest",
        "corpus_manifest_digest",
        "original_verifier_digest",
        "raw_series_root_digest",
        "comparability_digest",
    ):
        validate_digest(doc[name], name)
    if doc["series_status"] not in SERIES_STATUSES:
        raise _identity("admission-index.series_status is not a frozen status", "series_status")
    members = validate_member_records(doc["members"], "members", (), allow_relative=True)
    if not members:
        raise _schema("admission-index.members must not be empty", "members")
    inventory = doc["required_inventory"]
    if not isinstance(inventory, list):
        raise _schema("admission-index.required_inventory must be an array", "required_inventory")
    normalized = [validate_relative_member(item) for item in inventory]
    if normalized != sorted(normalized):
        raise _identity("admission-index.required_inventory must be sorted", "required_inventory")
    if len(set(normalized)) != len(normalized):
        raise _identity(
            "admission-index.required_inventory must not contain duplicates",
            "required_inventory",
        )
    if normalized != [member["path"] for member in members]:
        raise _identity(
            "admission-index.required_inventory must match the member list",
            "required_inventory",
        )
    result = dict(doc)
    result["members"] = members
    result["required_inventory"] = normalized
    bound_payload(result, "admission-index")
    return result


# ---------------------------------------------------------------------------
# Analysis (Gate B)
# ---------------------------------------------------------------------------


def _validate_lane_id(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise _schema(f"{field} must be a string", field)
    return validate_relative_member(value)


def _validate_campaign_records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise _schema("campaigns must be a non-empty array", "campaigns")
    records: list[dict[str, Any]] = []
    ids: list[str] = []
    for index, raw in enumerate(value):
        entry = require_closed(
            raw,
            f"campaigns[{index}]",
            frozenset(
                {
                    "campaign_id",
                    "slot_count",
                    "lane_count",
                    "sample_count",
                    "control",
                    "descriptive_process_cold",
                }
            ),
        )
        campaign_id = _validate_lane_id(entry["campaign_id"], f"campaigns[{index}].campaign_id")
        ids.append(campaign_id)
        cold = entry["descriptive_process_cold"]
        if not isinstance(cold, list):
            raise _schema(
                f"campaigns[{index}].descriptive_process_cold must be an array",
                "descriptive_process_cold",
            )
        control_flag = entry["control"]
        if control_flag is not True and control_flag is not False:
            raise _schema("campaigns[].control must be a boolean", "control")
        records.append(
            {
                "campaign_id": campaign_id,
                "slot_count": require_uint(entry["slot_count"], "slot_count"),
                "lane_count": require_uint(entry["lane_count"], "lane_count"),
                "sample_count": require_uint(entry["sample_count"], "sample_count"),
                "control": bool(control_flag),
                "descriptive_process_cold": [
                    _validate_lane_id(item, "descriptive_process_cold")
                    for item in cold
                ],
            }
        )
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        raise _identity("campaigns must be sorted and unique", "campaigns")
    return records


def _validate_statistics(value: object, method_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _schema("statistics must be an object", "statistics")
    if method_id == STATISTICS_CROSS_ENGINE:
        expected = frozenset({"method_id", "unit", "engines", "lanes"})
    elif method_id == STATISTICS_RETAINED_KEY:
        expected = frozenset({"method_id", "unit", "arms", "lanes"})
    else:
        raise _identity("statistics_method_id is not a frozen method", "statistics_method_id")
    stats = require_closed(value, "statistics", expected)
    if stats["method_id"] != method_id:
        raise _identity("statistics.method_id does not match the analysis", "statistics.method_id")
    if stats["unit"] != OFFICIAL_UNIT:
        raise _identity("statistics.unit must be the official nanosecond unit", "statistics.unit")
    if method_id == STATISTICS_CROSS_ENGINE:
        engines = _semantic_list(stats["engines"], "statistics.engines")
        if engines != ["lucene", "quervant", "tantivy"]:
            raise _identity(
                "statistics.engines is not the frozen three-engine set",
                "statistics.engines",
            )
        lanes: list[dict[str, Any]] = []
        for index, raw in enumerate(_require_lane_array(stats["lanes"])):
            lane = require_closed(
                raw,
                f"statistics.lanes[{index}]",
                frozenset(
                    {
                        "lane_id",
                        "per_engine",
                        "comparisons",
                    }
                ),
            )
            lane_id = _validate_lane_id(lane["lane_id"], "lane_id")
            per_engine = require_closed(
                lane["per_engine"],
                "per_engine",
                frozenset({"lucene", "quervant", "tantivy"}),
            )
            normalized_engines: dict[str, Any] = {}
            for engine in sorted(per_engine):
                record = require_closed(
                    per_engine[engine],
                    f"per_engine.{engine}",
                    frozenset(
                        {
                            "trial_medians_ns",
                            "median_ns",
                            "min_ns",
                            "max_ns",
                            "dispersion",
                        }
                    ),
                )
                trials = record["trial_medians_ns"]
                if not isinstance(trials, list) or len(trials) != 3:
                    raise _schema(
                        f"per_engine.{engine}.trial_medians_ns must hold three trials",
                        "trial_medians_ns",
                    )
                values = [require_uint(item, "trial_median_ns") for item in trials]
                dispersion = _decimal_string(record["dispersion"], "dispersion")
                normalized_engines[engine] = {
                    "trial_medians_ns": values,
                    "median_ns": require_uint(record["median_ns"], "median_ns"),
                    "min_ns": require_uint(record["min_ns"], "min_ns"),
                    "max_ns": require_uint(record["max_ns"], "max_ns"),
                    "dispersion": dispersion,
                }
            comparisons: list[dict[str, Any]] = []
            if not isinstance(lane["comparisons"], list) or not lane["comparisons"]:
                raise _schema("comparisons must be a non-empty array", "comparisons")
            for cindex, raw_comparison in enumerate(lane["comparisons"]):
                comparison = require_closed(
                    raw_comparison,
                    f"comparisons[{cindex}]",
                    frozenset(
                        {
                            "comparator",
                            "ratio",
                            "dispersion_ok",
                            "ranges_overlap",
                            "inconclusive",
                        }
                    ),
                )
                engine = comparison["comparator"]
                if engine not in ("lucene", "tantivy"):
                    raise _identity("comparisons.comparator must be a comparator engine", "comparator")
                comparisons.append(
                    {
                        "comparator": engine,
                        "ratio": _decimal_string(comparison["ratio"], "ratio"),
                        "dispersion_ok": bool(comparison["dispersion_ok"]),
                        "ranges_overlap": bool(comparison["ranges_overlap"]),
                        "inconclusive": bool(comparison["inconclusive"]),
                    }
                )
            lanes.append(
                {"lane_id": lane_id, "per_engine": normalized_engines, "comparisons": comparisons}
            )
        return {
            "method_id": method_id,
            "unit": OFFICIAL_UNIT,
            "engines": engines,
            "lanes": lanes,
        }

    arms = _semantic_list(stats["arms"], "statistics.arms")
    lanes = []
    for index, raw in enumerate(_require_lane_array(stats["lanes"])):
        lane = require_closed(
            raw,
            f"statistics.lanes[{index}]",
            frozenset(
                {
                    "campaign_id",
                    "lane_id",
                    "n",
                    "class",
                    "k",
                    "arms",
                    "status",
                }
            ),
        )
        lane_id = _validate_lane_id(lane["lane_id"], "lane_id")
        campaign_id = _validate_lane_id(lane["campaign_id"], "campaign_id")
        per_arm = require_closed(lane["arms"], f"lanes[{index}].arms", frozenset(arms))
        normalized_arms: dict[str, Any] = {}
        for arm in arms:
            record = require_closed(
                per_arm[arm],
                f"arms.{arm}",
                frozenset(
                    {
                        "block_medians_ns",
                        "retained_block_indices",
                        "excluded_block_indices",
                        "retained_median_ns",
                        "blocks",
                    }
                ),
            )
            blocks = record["blocks"]
            block_values = _int_list(record["block_medians_ns"], "block_medians_ns")
            if len(block_values) != blocks:
                raise _identity("block_medians_ns length must equal blocks", "block_medians_ns")
            retained = _int_list(record["retained_block_indices"], "retained_block_indices")
            excluded = _int_list(record["excluded_block_indices"], "excluded_block_indices")
            if sorted(retained + excluded) != list(range(1, blocks + 1)):
                raise _identity(
                    "retained and excluded blocks must partition 1..blocks",
                    "retained_block_indices",
                )
            normalized_arms[arm] = {
                "blocks": blocks,
                "block_medians_ns": block_values,
                "retained_block_indices": retained,
                "excluded_block_indices": excluded,
                "retained_median_ns": require_uint(record["retained_median_ns"], "retained_median_ns"),
            }
        if lane["status"] not in ("analyzed", "inconclusive-insufficient-blocks"):
            raise _identity("lane status is not a frozen status", "status")
        lanes.append(
            {
                "campaign_id": campaign_id,
                "lane_id": lane_id,
                "n": require_uint(lane["n"], "n"),
                "class": require_semantic_id(lane["class"], "class"),
                "k": require_uint(lane["k"], "k"),
                "arms": normalized_arms,
                "status": lane["status"],
            }
        )
    coordinates = [(record["campaign_id"], record["lane_id"]) for record in lanes]
    if len(set(coordinates)) != len(coordinates):
        raise _identity(
            "each (campaign, lane) pair must appear exactly once", "statistics.lanes"
        )
    return {"method_id": method_id, "unit": OFFICIAL_UNIT, "arms": arms, "lanes": lanes}


def require_semantic_id(value: object, field: str) -> str:
    """Validate a semantic slug (thin alias used by record validators)."""

    return validate_semantic_id(value, field)


def _require_lane_array(value: object) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise _schema("statistics.lanes must be a non-empty array", "statistics.lanes")
    return value


def _int_list(value: object, field: str) -> list[int]:
    if not isinstance(value, list):
        raise _schema(f"{field} must be an array", field)
    return [require_uint(item, field) for item in value]


DECIMAL_FRACTION_DIGITS = 6


def _decimal_string(value: object, field: str) -> str:
    """Validate a fixed six-fractional-digit decimal literal (never a float)."""

    if not isinstance(value, str):
        raise _schema(f"{field} must be a decimal string", field)
    text = value
    whole, separator, fraction = text.partition(".")
    if not separator:
        raise _schema(f"{field} must carry six fractional digits", field)
    if not whole.isdigit() or whole == "":
        raise _schema(f"{field} has an invalid whole part", field)
    if len(whole) > 1 and whole.startswith("0"):
        raise _schema(f"{field} has a padded whole part", field)
    if len(fraction) != DECIMAL_FRACTION_DIGITS or not fraction.isdigit():
        raise _schema(f"{field} must carry exactly six fractional digits", field)
    return text


def _validate_uncertainty(value: object, method_id: str) -> dict[str, Any]:
    expected = (
        frozenset(
            {
                "method_id",
                "dispersion_limit",
                "overlap_rule",
                "significance_claim",
            }
        )
        if method_id == STATISTICS_CROSS_ENGINE
        else frozenset(
            {
                "method_id",
                "confidence_level",
                "resamples",
                "significance_claim",
            }
        )
    )
    stats = require_closed(value, "uncertainty", expected)
    if method_id == STATISTICS_CROSS_ENGINE:
        if stats["method_id"] != "pr15d-three-trial-discrete-range-v1":
            raise _identity("uncertainty.method_id is not the frozen method", "uncertainty.method_id")
        return {
            "method_id": stats["method_id"],
            "dispersion_limit": _decimal_string(stats["dispersion_limit"], "dispersion_limit"),
            "overlap_rule": bool(stats["overlap_rule"]),
            "significance_claim": _significance_claim(stats["significance_claim"]),
        }
    if stats["method_id"] != "retained-key-frozen-block-dispersion-v1":
        raise _identity("uncertainty.method_id is not the frozen method", "uncertainty.method_id")
    level = stats["confidence_level"]
    if not isinstance(level, str) or level not in ("0.95",):
        raise _identity("uncertainty.confidence_level must be the frozen 0.95", "confidence_level")
    return {
        "method_id": stats["method_id"],
        "confidence_level": level,
        "resamples": require_uint(stats["resamples"], "resamples"),
        "significance_claim": _significance_claim(stats["significance_claim"]),
    }


def _significance_claim(value: object) -> str:
    if value not in ("none", "frozen-model-declared"):
        raise _identity("significance_claim is not a frozen literal", "significance_claim")
    return str(value)


def validate_retained_slot_statistics(document: object) -> dict[str, Any]:
    """Validate the complete paired-slot payload without recalculating estimators."""

    from .policy_inputs import ARMS, CAMPAIGNS, CLASSES, KS, NS

    payload = require_closed(document, "retained_slot_statistics", frozenset({"method_id", "lanes"}))
    if payload["method_id"] != "retained-key-paired-slot-effects-v1":
        raise _identity("the paired-slot method is not registered", "retained_slot_statistics.method_id")
    lanes = require_mapping(payload["lanes"], "retained_slot_statistics.lanes")
    coordinates = {
        f"pr15d_v1/{n}/{name}/k{k}": (n, name, k)
        for n in NS for name in CLASSES for k in KS
    }
    if set(lanes) != set(coordinates):
        raise _identity("paired-slot statistics require all seventy-two lanes", "retained_slot_statistics.lanes")
    pairs = (("L", "A"), ("P", "A"), ("H", "A"), ("P", "L"), ("H", "L"), ("H", "P"))
    record_keys = frozenset({"retained", "retained_count", "latency", "raw_latency", "filter_sensitive"}) | {
        f"{prefix}_{numerator}_{denominator}" for numerator, denominator in pairs for prefix in ("R", "CI")
    }

    def positive(value: object, field: str) -> None:
        if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)) or value <= 0:
            raise _schema("paired-slot statistics need finite positive JSON numbers", field)

    for lane_id, (n, name, k) in coordinates.items():
        lane = require_closed(lanes[lane_id], "retained_slot_statistics.lanes", frozenset({"id", "n", "class", "k", "campaigns"}))
        if type(lane["n"]) is not int or type(lane["k"]) is not int or type(lane["class"]) is not str or type(lane["id"]) is not str:
            raise _schema("paired-slot coordinates have invalid types", "retained_slot_statistics.lanes")
        if (lane["id"], lane["n"], lane["class"], lane["k"]) != (lane_id, n, name, k):
            raise _identity("paired-slot coordinates differ from their registered lane", "retained_slot_statistics.lanes")
        campaigns = require_closed(lane["campaigns"], "retained_slot_statistics.campaigns", frozenset(CAMPAIGNS))
        for campaign in CAMPAIGNS:
            record = require_closed(campaigns[campaign], "retained_slot_statistics.campaigns", record_keys)
            retained = record["retained"]
            if not isinstance(retained, list) or any(type(block) is not int for block in retained):
                raise _schema("retained block IDs must be exact integers", "retained_slot_statistics.retained")
            if not 4 <= len(retained) <= 12 or retained != sorted(set(retained)) or any(block not in range(1, 13) for block in retained):
                raise _identity("paired-slot retained blocks are incomplete or invalid", "retained_slot_statistics.retained")
            if type(record["retained_count"]) is not int or record["retained_count"] != len(retained):
                raise _identity("paired-slot retained count differs from its IDs", "retained_slot_statistics.retained_count")
            if type(record["filter_sensitive"]) is not bool:
                raise _schema("paired-slot sensitivity must be boolean", "retained_slot_statistics.filter_sensitive")
            for field in ("latency", "raw_latency"):
                values = require_closed(record[field], "retained_slot_statistics." + field, frozenset(ARMS))
                for value in values.values():
                    positive(value, "retained_slot_statistics." + field)
            for numerator, denominator in pairs:
                ratio_key, interval_key = f"R_{numerator}_{denominator}", f"CI_{numerator}_{denominator}"
                positive(record[ratio_key], "retained_slot_statistics." + ratio_key)
                interval = require_closed(record[interval_key], "retained_slot_statistics." + interval_key, frozenset({"low", "high", "seed"}))
                positive(interval["low"], "retained_slot_statistics." + interval_key)
                positive(interval["high"], "retained_slot_statistics." + interval_key)
                if interval["low"] > interval["high"]:
                    raise _identity("paired-slot interval endpoints are reversed", "retained_slot_statistics." + interval_key)
                if type(interval["seed"]) is not int:
                    raise _schema("a paired-slot seed must be an exact integer", "retained_slot_statistics." + interval_key)
                require_uint(interval["seed"], "retained_slot_statistics." + interval_key, maximum=2**64 - 1)
    return dict(payload)


def validate_official_analysis(document: object) -> dict[str, Any]:
    """Validate the closed official analysis record (Gate B output)."""

    candidate = require_mapping(document, "analysis")
    version = require_profile_version(candidate.get("schema_version"))
    doc = require_closed(candidate, "analysis", _ANALYSIS_KEYS if version == 1 else _ANALYSIS_KEYS_V2)
    if version == 2 and doc["study_id"] != "retained-key-topk-real-v1":
        raise _identity("only retained paired-slot analysis uses schema2", "study_id")
    require_kind(doc, ANALYSIS_KIND, "analysis")
    validate_official_subject(doc["subject"])
    require_official_scope(doc)
    validate_semantic_id(doc["study_id"], "study_id")
    for name in (
        "raw_series_root_digest",
        "analysis_profile_digest",
        "control_result_digest",
    ):
        validate_digest(doc[name], name)
    method = doc["statistics_method_id"]
    if method not in OFFICIAL_STATISTICS_METHODS:
        raise _identity("statistics_method_id is not a frozen method", "statistics_method_id")
    eligible = doc["eligible_lane_ids"]
    if not isinstance(eligible, list) or not eligible:
        raise _schema("eligible_lane_ids must be a non-empty array", "eligible_lane_ids")
    lane_ids = [_validate_lane_id(item, "eligible_lane_ids") for item in eligible]
    if lane_ids != sorted(lane_ids):
        raise _identity("eligible_lane_ids must be sorted", "eligible_lane_ids")
    if len(set(lane_ids)) != len(lane_ids):
        raise _identity("eligible_lane_ids must not contain duplicates", "eligible_lane_ids")
    excluded = doc["excluded_lane_classes"]
    if not isinstance(excluded, list):
        raise _schema("excluded_lane_classes must be an array", "excluded_lane_classes")
    excluded_ids = [str(item) for item in excluded]
    if tuple(excluded_ids) != tuple(sorted(EXCLUDED_LANE_CLASSES)):
        raise _identity(
            "excluded_lane_classes must be the exact frozen exclusion set",
            "excluded_lane_classes",
        )
    limitations = _semantic_list(doc["limitations"], "limitations", allow_empty=True)
    campaigns = _validate_campaign_records(doc["campaigns"])
    statistics = _validate_statistics(doc["statistics"], method)
    uncertainty = _validate_uncertainty(doc["uncertainty"], method)
    statistic_lanes = {record["lane_id"] for record in statistics["lanes"]}
    if set(lane_ids) != statistic_lanes:
        raise _identity(
            "eligible_lane_ids must match the statistics lane set",
            "eligible_lane_ids",
        )
    result = dict(doc)
    result["eligible_lane_ids"] = lane_ids
    result["excluded_lane_classes"] = excluded_ids
    result["limitations"] = limitations
    result["campaigns"] = campaigns
    result["statistics"] = statistics
    result["uncertainty"] = uncertainty
    if version == 2:
        if method != STATISTICS_RETAINED_KEY:
            raise _identity("retained baseline analysis must preserve the descriptive method", "statistics_method_id")
        result["retained_slot_statistics"] = validate_retained_slot_statistics(doc["retained_slot_statistics"])
    bound_payload(result, "analysis")
    return result


# ---------------------------------------------------------------------------
# Policy (Gate B output)
# ---------------------------------------------------------------------------


def validate_retained_policy_payload(document: object) -> dict[str, Any]:
    """The complete nine-K result, with no implied global winning strategy."""

    from .policy_inputs import KS, POLICY_METHOD

    payload = require_closed(document, "retained_key_policy", frozenset({
        "method_id", "inputs_digest", "raw_series_root_digest", "statistics_digest", "rows",
    }))
    if payload["method_id"] != POLICY_METHOD:
        raise _identity("retained policy method is not the frozen T7/F2 method", "method_id")
    for name in ("inputs_digest", "raw_series_root_digest", "statistics_digest"):
        validate_digest(payload[name], name)
    rows = payload["rows"]
    if not isinstance(rows, list) or len(rows) != 9:
        raise _schema("retained policy needs exactly nine K rows", "rows")
    row_keys = frozenset({"k", "selected_strategy", "decision_status", "P_status", "H_status",
                          "P_reasons", "H_reasons", "filter_sensitive", "H_memory"})
    decision_codes = {
        "SELECTED_ELIGIBLE", "SELECTED_GM_CONFIRMED", "P_TIEBREAKER_NOT_PROVEN_FASTER",
        "LINEAR_BASE", "K_INCONCLUSIVE", "K_INCONCLUSIVE_FILTER_SENSITIVE", "K_INCONCLUSIVE_P_VS_H",
    }
    normalized = []
    for expected_k, value in zip(KS, rows):
        row = dict(require_closed(value, "retained_key_policy.rows", row_keys))
        if type(row["k"]) is not int or row["k"] != expected_k:
            raise _identity("retained policy K rows must be complete and in frozen order", "rows")
        if row["decision_status"] not in decision_codes or row["selected_strategy"] not in {"P", "H", "LINEAR_BASE", "INCONCLUSIVE"}:
            raise _identity("retained policy row has an unknown decision", "rows")
        for candidate in ("P", "H"):
            if row[f"{candidate}_status"] not in CANDIDATE_STATUSES:
                raise _identity("retained policy candidate status is invalid", "rows")
            reasons = row[f"{candidate}_reasons"]
            if not isinstance(reasons, list) or any(not isinstance(reason, str) or not reason or len(reason) > 256 for reason in reasons):
                raise _schema("retained policy reasons must be bounded nonempty strings", "rows")
        if type(row["filter_sensitive"]) is not bool:
            raise _schema("retained policy sensitivity must be boolean", "rows")
        require_uint(row["H_memory"], "H_memory")
        selected, status = row["selected_strategy"], row["decision_status"]
        if selected in ("P", "H") and row[f"{selected}_status"] != "ELIGIBLE":
            raise _identity("a selected retained policy candidate must be eligible", "rows")
        if selected == "INCONCLUSIVE" and not status.startswith("K_INCONCLUSIVE"):
            raise _identity("inconclusive retained policy row has a resolved code", "rows")
        if status.startswith("K_INCONCLUSIVE") and selected != "INCONCLUSIVE":
            raise _identity("inconclusive retained policy code selects an arm", "rows")
        if (selected == "LINEAR_BASE") != (status == "LINEAR_BASE"):
            raise _identity("baseline retained policy row has inconsistent code", "rows")
        if status == "LINEAR_BASE" and (row["P_status"], row["H_status"]) != ("INELIGIBLE", "INELIGIBLE"):
            raise _identity("baseline requires both candidates to be ineligible", "rows")
        if status in ("P_TIEBREAKER_NOT_PROVEN_FASTER", "SELECTED_GM_CONFIRMED") and (row["P_status"], row["H_status"]) != ("ELIGIBLE", "ELIGIBLE"):
            raise _identity("tie/GM comparison requires both eligible candidates", "rows")
        if status == "P_TIEBREAKER_NOT_PROVEN_FASTER" and selected != "P":
            raise _identity("the frozen tie preference selects P", "rows")
        if status == "SELECTED_ELIGIBLE" and row[f"{'H' if selected == 'P' else 'P'}_status"] != "INELIGIBLE":
            raise _identity("single eligible selection requires an ineligible alternative", "rows")
        if row["filter_sensitive"] and selected not in ("INCONCLUSIVE", "LINEAR_BASE"):
            raise _identity("filter-sensitive rows cannot claim a selected candidate", "rows")
        normalized.append(row)
    result = dict(payload)
    result["rows"] = normalized
    return result


def retained_policy_decisions(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize nine decisions without flattening a mixed per-K strategy."""

    rows = validate_retained_policy_payload(payload)["rows"]
    winners = {row["selected_strategy"] for row in rows}
    selected = None
    claim = False
    if "INCONCLUSIVE" in winners:
        status = DECISION_INCONCLUSIVE
    elif winners == {"LINEAR_BASE"}:
        status, selected = DECISION_BASELINE_ONLY, "linear"
    elif winners in ({"P"}, {"H"}):
        selected = "prefilter" if winners == {"P"} else "exact-set"
        tie = any(row["decision_status"] == "P_TIEBREAKER_NOT_PROVEN_FASTER" for row in rows)
        status = DECISION_TIE_PREFERENCE if tie else DECISION_SELECTED
        claim = not tie
    else:
        status = DECISION_PER_K_RESOLVED
    candidates = {"base": "INCONCLUSIVE", "linear": "ELIGIBLE" if winners == {"LINEAR_BASE"} else "INCONCLUSIVE"}
    for letter, name in (("P", "prefilter"), ("H", "exact-set")):
        states = {row[f"{letter}_status"] for row in rows}
        candidates[name] = next(iter(states)) if len(states) == 1 else "INCONCLUSIVE"
    return {"decision_status": status, "selected_arm_id": selected,
            "candidate_statuses": candidates, "performance_claim_allowed": claim,
            "reasons": ["authenticated-nine-k-policy-derived"]}


def validate_official_policy(document: object) -> dict[str, Any]:
    """Validate the closed official policy decision record."""

    version = document.get("schema_version") if isinstance(document, Mapping) else None
    v2 = type(version) is int and version == 2
    doc = require_closed(document, "policy", _POLICY_KEYS | ({"retained_key_policy"} if v2 else set()))
    if not v2:
        require_version(doc, "policy")
    else:
        from .protocols import STUDY_RETAINED_KEY
        if doc["study_id"] != STUDY_RETAINED_KEY:
            raise _identity("policy schema 2 is reserved for retained-key", "study_id")
    require_kind(doc, POLICY_KIND, "policy")
    validate_official_subject(doc["subject"])
    require_official_scope(doc)
    validate_semantic_id(doc["study_id"], "study_id")
    validate_digest(doc["policy_digest"], "policy_digest")
    validate_digest(doc["analysis_digest"], "analysis_digest")
    status = doc["decision_status"]
    if status not in OFFICIAL_DECISION_STATUSES:
        raise _identity("policy.decision_status is not a frozen decision", "decision_status")
    if status == DECISION_PER_K_RESOLVED and not v2:
        raise _identity("per-K policy requires the complete version 2 payload", "schema_version")
    selected = doc["selected_arm_id"]
    if selected is not None:
        selected = validate_semantic_id(selected, "selected_arm_id")
    if status in (DECISION_INCONCLUSIVE, DECISION_POLICY_NOT_DERIVABLE) and selected is not None:
        raise _identity(
            "an inconclusive or underivable policy must not select an arm",
            "selected_arm_id",
        )
    candidates = doc["candidate_statuses"]
    if not isinstance(candidates, Mapping) or not candidates:
        raise _schema("candidate_statuses must be a non-empty object", "candidate_statuses")
    normalized: dict[str, str] = {}
    for key in sorted(candidates):
        arm = validate_semantic_id(key, f"candidate_statuses.{key}")
        status_value = candidates[key]
        if status_value not in CANDIDATE_STATUSES:
            raise _identity("candidate status is not a frozen status", "candidate_statuses")
        normalized[arm] = status_value
    if selected is not None and normalized.get(selected) != "ELIGIBLE":
        raise _identity("a selected arm must be ELIGIBLE", "selected_arm_id")
    reasons = _semantic_list(doc["reasons"], "reasons", allow_empty=False)
    claim = doc["performance_claim_allowed"]
    if claim is not False and claim is not True:
        raise _schema("performance_claim_allowed must be a boolean", "performance_claim_allowed")
    if claim is True and status not in (
        DECISION_SELECTED,
        DECISION_TIE_PREFERENCE,
        DECISION_BASELINE_ONLY,
    ):
        raise _identity(
            "performance_claim_allowed must be false without a resolved policy decision",
            "performance_claim_allowed",
        )
    result = dict(doc)
    result["selected_arm_id"] = selected
    result["candidate_statuses"] = normalized
    result["reasons"] = reasons
    result["performance_claim_allowed"] = bool(claim)
    if v2:
        payload = validate_retained_policy_payload(doc["retained_key_policy"])
        expected = retained_policy_decisions(payload)
        for name, value in expected.items():
            if result[name] != value:
                raise _identity("global retained policy summary differs from its nine K rows", name)
        result["retained_key_policy"] = payload
    bound_payload(result, "policy")
    return result


# ---------------------------------------------------------------------------
# Verification assessment (Gate C output)
# ---------------------------------------------------------------------------


def validate_official_verification(document: object) -> dict[str, Any]:
    """Validate the closed independent verification assessment."""

    candidate = require_mapping(document, "verification-assessment")
    version = require_profile_version(candidate.get("schema_version"))
    doc = require_closed(candidate, "verification-assessment", _ASSESSMENT_KEYS if version == 1 else _ASSESSMENT_KEYS_V2)
    require_kind(doc, ASSESSMENT_KIND, "verification-assessment")
    validate_official_subject(doc["subject"])
    require_official_scope(doc)
    status = doc["status"]
    statuses = VERIFICATION_STATUSES if version == 1 else ("VERIFIED_CURRENT_BASELINE", "BLOCKED", "FAILED")
    if type(status) is not str or status not in statuses:
        raise _identity("verification status is not a frozen status", "status")
    validate_semantic_id(doc["study_id"], "study_id")
    for name in ("raw_series_root_digest", "analysis_digest", "policy_digest"):
        validate_digest(doc[name], name)
    if doc["reference_id"] != "official-independent-reference-v1":
        raise _identity("reference_id is not the frozen independent reference", "reference_id")
    check_ids = doc["check_ids"]
    if not isinstance(check_ids, list):
        raise _schema("check_ids must be an array", "check_ids")
    expected_checks = VERIFIER_CHECK_IDS
    if version == 2:
        if doc["verification_scope"] != CURRENT_BASELINE_PROFILE:
            raise _identity("verification scope is not current-baseline-v2", "verification_scope")
        policy_status = doc["policy_verification_status"]
        if type(policy_status) is not str or policy_status not in ("PASS", "NOT_EVALUATED"):
            raise _identity("unknown baseline policy verification status", "policy_verification_status")
        omitted = doc["not_evaluated_checks"]
        if not isinstance(omitted, list):
            raise _schema("not_evaluated_checks must be an array", "not_evaluated_checks")
        expected_omitted = [] if policy_status == "PASS" else ["RV-08-POLICY"]
        if omitted != expected_omitted:
            raise _identity("only an unevaluated policy check may be omitted", "not_evaluated_checks")
        if policy_status == "NOT_EVALUATED":
            if doc["study_id"] != "retained-key-topk-real-v1":
                raise _identity("only absent retained policy inputs permit an unevaluated policy", "policy_verification_status")
            expected_checks = tuple(check for check in VERIFIER_CHECK_IDS if check != "RV-08-POLICY")
    if status in ("VERIFIED_REAL", "VERIFIED_CURRENT_BASELINE"):
        if tuple(check_ids) != expected_checks:
            raise _identity("a verified assessment needs the frozen check registry", "check_ids")
    elif check_ids:
        for item in check_ids:
            if item not in VERIFIER_CHECK_IDS:
                raise _identity("check id is not in the frozen registry", "check_ids")
    claims = _semantic_list(doc["verified_claims"], "verified_claims", allow_empty=True)
    if version == 2 and doc["policy_verification_status"] == "NOT_EVALUATED" and "policy-decision" in claims:
        raise _identity("unevaluated policy cannot claim policy-decision verification", "verified_claims")
    result = dict(doc)
    result["check_ids"] = list(check_ids)
    result["verified_claims"] = claims
    bound_payload(result, "verification-assessment")
    return result


# ---------------------------------------------------------------------------
# Acceptance summary (Gate D output)
# ---------------------------------------------------------------------------


def validate_official_acceptance(document: object) -> dict[str, Any]:
    """Validate the closed official acceptance summary."""

    candidate = require_mapping(document, "acceptance-summary")
    version = require_profile_version(candidate.get("schema_version"))
    doc = require_closed(candidate, "acceptance-summary", _ACCEPTANCE_KEYS if version == 1 else _ACCEPTANCE_KEYS_V2)
    require_kind(doc, ACCEPTANCE_KIND, "acceptance-summary")
    validate_official_subject(doc["subject"])
    require_official_scope(doc)
    for name in (
        "approved_design_digest",
        "authorization_digest",
        "source_set_digest",
    ):
        validate_digest(doc[name], name)
    ids = require_closed(
        doc["gate_receipt_ids"],
        "gate_receipt_ids",
        frozenset({"admission", "analysis", "framework-qa", "source-qa", "verification"}),
    )
    receipt_ids = {
        gate: validate_digest(ids[gate], f"gate_receipt_ids.{gate}") for gate in sorted(ids)
    }
    if doc["policy_decision_status"] not in OFFICIAL_DECISION_STATUSES:
        raise _identity("acceptance policy_decision_status is not frozen", "policy_decision_status")
    if version == 1 and doc["historical_parity_status"] not in PARITY_STATUSES:
        raise _identity("acceptance historical_parity_status is not frozen", "historical_parity_status")
    if version == 2:
        validate_digest(doc["history_report_digest"], "history_report_digest")
        validate_uuid4(doc["baseline_id"], "baseline_id")
        if doc["baseline_verification_status"] not in ("VERIFIED_CURRENT_BASELINE", "BLOCKED", "FAILED"):
            raise _identity("baseline verification status is not registered", "baseline_verification_status")
        if doc["policy_verification_status"] not in ("PASS", "NOT_EVALUATED"):
            raise _identity("policy verification status is not registered", "policy_verification_status")
    if doc["required_control_status"] not in CONTROL_STATUSES:
        raise _identity("acceptance required_control_status is not frozen", "required_control_status")
    if doc["qa_status"] not in QA_STATUSES:
        raise _identity("acceptance qa_status is not frozen", "qa_status")
    if doc["admission_status"] not in ADMISSION_STATUSES:
        raise _identity("acceptance admission_status is not frozen", "admission_status")
    if doc["decision_scope"] != ("real-official-v1" if version == 1 else "real-current-baseline-v2"):
        raise _identity("acceptance decision_scope is not the frozen literal", "decision_scope")
    result = dict(doc)
    result["gate_receipt_ids"] = receipt_ids
    bound_payload(result, "acceptance-summary")
    return result


# ---------------------------------------------------------------------------
# Freeze snapshot and final manifest (Gate E)
# ---------------------------------------------------------------------------


def validate_official_freeze_snapshot(document: object) -> dict[str, Any]:
    """Validate the closed pre-attestation freeze snapshot."""

    doc = require_closed(document, "freeze-snapshot", _SNAPSHOT_KEYS)
    require_version(doc, "freeze-snapshot")
    require_kind(doc, SNAPSHOT_KIND, "freeze-snapshot")
    validate_official_subject(doc["subject"])
    require_official_scope(doc)
    for name in ("approved_design_digest", "authorization_digest", "source_set_digest"):
        validate_digest(doc[name], name)
    result = dict(doc)
    result["members"] = validate_member_records(
        doc["members"], "members", FREEZE_MEMBERS
    )
    bound_payload(result, "freeze-snapshot")
    return result


def validate_official_manifest(document: object) -> dict[str, Any]:
    """Validate the closed official completion manifest."""

    doc = require_closed(document, "manifest", _MANIFEST_KEYS)
    require_version(doc, "manifest")
    require_kind(doc, MANIFEST_KIND, "manifest")
    validate_official_subject(doc["subject"])
    require_official_scope(doc)
    for name in (
        "approved_design_digest",
        "authorization_digest",
        "source_set_digest",
        "raw_series_root_digest",
        "attestation_digest",
    ):
        validate_digest(doc[name], name)
    snapshot = validate_official_freeze_snapshot(doc["freeze_snapshot"])
    for name in ("subject", "approved_design_digest", "authorization_digest", "source_set_digest"):
        if snapshot[name] != doc[name]:
            raise _identity(
                f"manifest.freeze_snapshot.{name} does not match the manifest", name
            )
    members = validate_member_records(doc["members"], "members", MANIFEST_MEMBERS)
    attestation = [member for member in members if member["path"] == ATTESTATION_NAME]
    if len(attestation) != 1 or attestation[0]["digest"] != doc["attestation_digest"]:
        raise _identity(
            "manifest.members attestation digest does not match attestation_digest",
            "attestation_digest",
        )
    result = dict(doc)
    result["freeze_snapshot"] = snapshot
    result["members"] = members
    bound_payload(result, "manifest")
    return result


def canonical_kind_for(name: str) -> str:
    """Return the frozen ``kind`` for a durable official member name."""

    mapping = {
        "admission-index.json": EVIDENCE_INDEX_KIND,
        "analysis.json": ANALYSIS_KIND,
        "policy.json": POLICY_KIND,
        "verification-assessment.json": ASSESSMENT_KIND,
        "framework-qa-evidence.json": FRAMEWORK_QA_KIND,
        "source-qa-evidence.json": SOURCE_QA_KIND,
        "acceptance-summary.json": ACCEPTANCE_KIND,
        "manifest.json": MANIFEST_KIND,
    }
    if name not in mapping:
        raise _schema(f"{name} has no canonical official kind", "member")
    return mapping[name]


__all__ = [
    "ACCEPTANCE_KIND",
    "ADMISSION_STATUSES",
    "ANALYSIS_KIND",
    "ASSESSMENT_KIND",
    "ATTESTATION_NAME",
    "CANDIDATE_STATUSES",
    "CONTROL_STATUSES",
    "CURRENT_BASELINE_PROFILE",
    "DECISION_BASELINE_ONLY",
    "DECISION_INCONCLUSIVE",
    "DECISION_POLICY_NOT_DERIVABLE",
    "DECISION_SELECTED",
    "DECISION_TIE_PREFERENCE",
    "DEPENDENCY_GATES",
    "EVIDENCE_INDEX_KIND",
    "EXCLUDED_LANE_CLASSES",
    "FRAMEWORK_QA_KIND",
    "FRAMEWORK_QA_ROSTER",
    "FRAMEWORK_TOOLCHAIN_ID",
    "FREEZE_MEMBERS",
    "HISTORICAL_SCOPE",
    "INPUT_NAMES",
    "INPUT_NAMES_V2",
    "MANIFEST_KIND",
    "MANIFEST_MEMBERS",
    "MANIFEST_NAME",
    "MAX_DOCUMENT_BYTES",
    "MEMBER_NAMES",
    "OFFICIAL_DECISION_STATUSES",
    "OFFICIAL_GATE_ORDER",
    "OFFICIAL_PROFILE_KIND",
    "OFFICIAL_SCOPE",
    "OFFICIAL_STATISTICS_METHODS",
    "OFFICIAL_UNIT",
    "OFFICIAL_VALIDATOR_IDS",
    "OFFICIAL_VALIDATOR_IDS_V2",
    "OUTPUT_NAMES",
    "PARITY_STATUSES",
    "PENDING_NAME",
    "POLICY_GATES",
    "POLICY_KIND",
    "PROFILE_ID",
    "PROFILE_VERSION",
    "QA_ROSTER_GATES",
    "QA_STATUSES",
    "REAL_ORIGIN",
    "SCHEMA_VERSION",
    "SERIES_STATUSES",
    "SNAPSHOT_KIND",
    "SOURCE_QA_KIND",
    "SOURCE_QA_ROSTER",
    "SOURCE_TOOLCHAIN_ID",
    "STATISTICS_CROSS_ENGINE",
    "STATISTICS_RETAINED_KEY",
    "TEMPORARY_AUTHORIZATION_KIND",
    "UNRESOLVED_DECISIONS",
    "VALIDATOR_VERSION",
    "VERIFICATION_STATUSES",
    "VERIFIER_CHECK_IDS",
    "canonical_kind_for",
    "content_digest",
    "document_digest",
    "input_names_for",
    "member_record",
    "require_historical_scope",
    "require_official_scope",
    "require_profile_version",
    "require_semantic_id",
    "roster_for",
    "toolchain_for",
    "validate_member_records",
    "validate_official_acceptance",
    "validate_official_analysis",
    "validate_official_evidence_index",
    "validate_official_freeze_snapshot",
    "validate_official_manifest",
    "validate_official_policy",
    "validate_official_profile",
    "validate_official_qa",
    "validate_official_subject",
    "validate_official_verification",
    "validate_retained_slot_statistics",
    "validate_source_commit",
    "validate_uuid4",
]
