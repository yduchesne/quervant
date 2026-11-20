"""Sanitized official qualification report and closeout gate evaluation.

The report is deliberately narrow: it states what was actually verified, keeps the
code/QA/acquisition/parity gates separate and never promotes a partial result into
``v0.1-bench COMPLETE``. It contains no host-local absolute paths, no raw samples
and no credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..config.codec import content_digest
from ..config.errors import BM_SCHEMA_INVALID, BenchError
from ..config.identity import (
    validate_digest,
    validate_semantic_id,
    validate_source_commit,
)
from ..qualification.contracts import require_closed, require_uint

REPORT_KIND = "official-qualification-report"
REPORT_VERSION = 1

GATE_STATUSES: tuple[str, ...] = ("PASS", "FAIL", "BLOCKED", "UNVERIFIED", "NOT_EXECUTED")
CLOSEOUT_READY = "READY_FOR_REVIEW"
CLOSEOUT_BLOCKED = "BLOCKED"
CURRENT_BASELINE_ACCEPTED = "CURRENT_BASELINE_ACCEPTED"
DISPOSITION_REAL_AND_HISTORICAL = "BM09_REAL_AND_HISTORICAL_ACCEPTED_READY_FOR_REVIEW"
DISPOSITION_IMPLEMENTATION_ONLY = "BM09_IMPLEMENTATION_L1_L2_PASS_REAL_BLOCKED"
DISPOSITION_REAL_PARTIAL = "BM09_REAL_PARTIAL_OR_INVALID"
DISPOSITION_REAL_ONLY = "BM09_REAL_ACCEPTED_HISTORICAL_PARITY_BLOCKED"
DISPOSITION_HARD_STOP = "BM09_HARD_STOP"
DISPOSITIONS: tuple[str, ...] = (
    DISPOSITION_REAL_AND_HISTORICAL,
    DISPOSITION_IMPLEMENTATION_ONLY,
    DISPOSITION_REAL_PARTIAL,
    DISPOSITION_REAL_ONLY,
    DISPOSITION_HARD_STOP,
)

_REPORT_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "branch",
        "planning_main_sha",
        "actual_main_base_sha",
        "implementation_sha",
        "gates",
        "real_series",
        "historical_parity",
        "disposition",
        "reasons",
    }
)
_GATE_KEYS = frozenset({"gate_id", "status", "evidence_digest"})
_SERIES_KEYS = frozenset(
    {
        "study_id",
        "run_id",
        "admission_status",
        "analysis_decision",
        "verification_status",
        "manifest_digest",
        "attestation_reopened",
        "performance_policy",
    }
)


def _identity(message: str, field: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field)


def build_report(
    *,
    branch: str,
    planning_main_sha: str,
    actual_main_base_sha: str,
    implementation_sha: str,
    gates: Sequence[Mapping[str, Any]],
    real_series: Sequence[Mapping[str, Any]],
    historical_parity_status: str,
    closeout_ready: bool,
) -> dict[str, Any]:
    """Build the sanitized report document (no absolute host paths)."""

    for value, field in (
        (branch, "branch"),
        (implementation_sha, "implementation_sha"),
    ):
        if not isinstance(value, str) or not value:
            raise _identity("report identity fields must be non-empty strings", field)
    for value, field in (
        (planning_main_sha, "planning_main_sha"),
        (actual_main_base_sha, "actual_main_base_sha"),
    ):
        validate_source_commit(value, field)
    gate_records: list[dict[str, Any]] = []
    for index, gate in enumerate(gates):
        record = require_closed(gate, f"gates[{index}]", _GATE_KEYS)
        gate_id = validate_semantic_id(record["gate_id"], "gate_id")
        if record["status"] not in GATE_STATUSES:
            raise _identity("a gate status is not a frozen status", "status")
        gate_records.append(
            {
                "gate_id": gate_id,
                "status": record["status"],
                "evidence_digest": (
                    None
                    if record["evidence_digest"] is None
                    else validate_digest(record["evidence_digest"], "evidence_digest")
                ),
            }
        )
    series_records: list[dict[str, Any]] = []
    for index, series in enumerate(real_series):
        record = require_closed(series, f"real_series[{index}]", _SERIES_KEYS)
        series_records.append(
            {
                "study_id": validate_semantic_id(record["study_id"], "study_id"),
                "run_id": record["run_id"],
                "admission_status": record["admission_status"],
                "analysis_decision": record["analysis_decision"],
                "verification_status": record["verification_status"],
                "manifest_digest": record["manifest_digest"],
                "attestation_reopened": bool(record["attestation_reopened"]),
                "performance_policy": record["performance_policy"],
            }
        )
    if historical_parity_status not in GATE_STATUSES:
        raise _identity("the historical parity status is not a frozen status", "historical_parity")
    disposition = (
        DISPOSITION_REAL_AND_HISTORICAL if closeout_ready else DISPOSITION_IMPLEMENTATION_ONLY
    )
    document = {
        "kind": REPORT_KIND,
        "schema_version": REPORT_VERSION,
        "branch": branch,
        "planning_main_sha": planning_main_sha,
        "actual_main_base_sha": actual_main_base_sha,
        "implementation_sha": implementation_sha,
        "gates": gate_records,
        "real_series": series_records,
        "historical_parity": historical_parity_status,
        "disposition": disposition,
        "reasons": sorted(
            [gate["gate_id"] for gate in gate_records if gate["status"] != "PASS"]
        )
        + ([] if historical_parity_status == "PASS" else ["historical-parity-not-pass"])
        + ([] if closeout_ready else ["closeout-gates-incomplete"]),
    }
    return validate_report(document)


def validate_report(document: object) -> dict[str, Any]:
    """Validate the closed sanitized report shape."""

    doc = require_closed(document, "report", _REPORT_KEYS)
    if doc["kind"] != REPORT_KIND:
        raise _identity("the report kind is not frozen", "kind")
    if require_uint(doc["schema_version"], "schema_version") != REPORT_VERSION:
        raise _identity("the report schema_version is not supported", "schema_version")
    if doc["disposition"] not in DISPOSITIONS:
        raise _identity("the report disposition is not a terminal outcome", "disposition")
    for entry in doc["gates"]:
        if entry["status"] not in GATE_STATUSES:
            raise _identity("a gate status is not frozen", "status")
    for entry in doc["reasons"]:
        if not isinstance(entry, str):
            raise _identity("report reasons must be strings", "reasons")
    return dict(doc)


@dataclass(frozen=True)
class CloseoutInputs:
    """The exact predicates required for a ``v0.1-bench COMPLETE`` claim."""

    l1_pass: bool = False
    l2_pass: bool = False
    g0_approved_both: bool = False
    host_readiness_and_controls_pass: bool = False
    retained_key_full_series_pass: bool = False
    cross_engine_full_series_pass: bool = False
    real_gates_pass: bool = False
    historical_parity_pass: bool = False
    attestation_reopen_pass: bool = False
    final_ci_success: bool = False
    independent_review_accepted: bool = False
    no_unresolved_findings: bool = False

    def missing(self) -> tuple[str, ...]:
        """Return the names of every unmet closeout predicate."""

        unmet = [
            name
            for name in (
                "l1_pass",
                "l2_pass",
                "g0_approved_both",
                "host_readiness_and_controls_pass",
                "retained_key_full_series_pass",
                "cross_engine_full_series_pass",
                "real_gates_pass",
                "historical_parity_pass",
                "attestation_reopen_pass",
                "final_ci_success",
                "independent_review_accepted",
                "no_unresolved_findings",
            )
            if not getattr(self, name)
        ]
        return tuple(unmet)


@dataclass(frozen=True)
class CurrentBaselineCloseoutInputs:
    """Current evidence predicates; optional history and policy are disclosures."""

    l1_pass: bool = False
    l2_pass: bool = False
    g0_approved_both: bool = False
    host_readiness_and_controls_pass: bool = False
    retained_key_full_series_pass: bool = False
    cross_engine_full_series_pass: bool = False
    current_baseline_verification_pass: bool = False
    source_qa_pass: bool = False
    attestation_reopen_pass: bool = False
    final_ci_success: bool = False
    complete_results_preserved: bool = False
    clean_checkout_replay_pass: bool = False
    independent_review_accepted: bool = False
    no_unresolved_findings: bool = False

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not bool:
                raise _identity("current-baseline closeout predicates must be boolean", name)

    def missing(self) -> tuple[str, ...]:
        self.__post_init__()
        return tuple(name for name in self.__dataclass_fields__ if not getattr(self, name))


def closeout_status(inputs: CloseoutInputs | CurrentBaselineCloseoutInputs) -> tuple[str, tuple[str, ...]]:
    """Return ``(status, missing predicates)``; never claims completion early."""

    if type(inputs) is CurrentBaselineCloseoutInputs:
        missing = inputs.missing()
        return (CURRENT_BASELINE_ACCEPTED if not missing else CLOSEOUT_BLOCKED, missing)
    if type(inputs) is not CloseoutInputs:
        raise _identity("closeout inputs must select an exact supported contract", "inputs")
    missing = inputs.missing()
    return (CLOSEOUT_READY if not missing else CLOSEOUT_BLOCKED, missing)


def disposition_for(
    *,
    closeout: str,
    real_series_attempted: bool = False,
    real_series_valid: bool = False,
    historical_parity_pass: bool = False,
) -> str:
    """Map the observed state to exactly one terminal disposition."""

    if closeout == CLOSEOUT_READY:
        return DISPOSITION_REAL_AND_HISTORICAL
    if real_series_attempted and not real_series_valid:
        return DISPOSITION_REAL_PARTIAL
    if real_series_valid and not historical_parity_pass:
        return DISPOSITION_REAL_ONLY
    return DISPOSITION_IMPLEMENTATION_ONLY


def report_digest(document: Mapping[str, Any]) -> str:
    """Return the canonical digest of a validated report."""

    return content_digest(validate_report(dict(document)))


__all__ = [
    "CLOSEOUT_BLOCKED",
    "CLOSEOUT_READY",
    "CloseoutInputs",
    "CurrentBaselineCloseoutInputs",
    "CURRENT_BASELINE_ACCEPTED",
    "DISPOSITIONS",
    "DISPOSITION_HARD_STOP",
    "DISPOSITION_IMPLEMENTATION_ONLY",
    "DISPOSITION_REAL_AND_HISTORICAL",
    "DISPOSITION_REAL_ONLY",
    "DISPOSITION_REAL_PARTIAL",
    "GATE_STATUSES",
    "REPORT_KIND",
    "build_report",
    "closeout_status",
    "disposition_for",
    "report_digest",
    "validate_report",
]
