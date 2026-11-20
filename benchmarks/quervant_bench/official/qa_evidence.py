"""Read-only verification of executed official QA check artifacts.

An official QA *summary* records, per check, the canonical digest of an executed
check record. This module proves that each of those records and its raw execution
log actually exist in an independently approved external evidence root, that they
are safe regular files with bounded size, that the record binds the raw log bytes,
that the record digest equals the G0-pinned summary entry, and that the whole
summary digest equals the G0 pin.

Nothing here writes, creates, downloads or repairs evidence, and no CI result is
inferred from a status string.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import (
    canonical_document_bytes,
    decode_text,
    loads_json,
)
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id, validate_source_commit
from ..evidence.hashing import sha256_regular_file
from ..evidence.paths import (
    open_regular_beneath,
    require_safe_root,
    validate_relative_member,
)
from ..evidence.provenance import repository_root
from ..qualification.contracts import document_digest, require_closed, require_uint
from .contracts import (
    FRAMEWORK_QA_ROSTER,
    OFFICIAL_SCOPE,
    REAL_ORIGIN,
    SOURCE_QA_ROSTER,
    toolchain_for,
    validate_official_qa,
)
from .protocols import OfficialFreeze

EXECUTED_CHECK_KIND = "official-executed-qa-check"
MAX_CHECK_RECORD_BYTES = 65_536
MAX_LOG_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 384 * 1024 * 1024
EXECUTORS: tuple[str, ...] = ("hosted-ci", "operator-attested")
_CHECK_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "qa_gate",
        "check_id",
        "source_commit",
        "source_set_digest",
        "toolchain_id",
        "executor",
        "execution_reference",
        "job_name",
        "executed",
        "status",
        "failed",
        "mandatory_skipped",
        "command_exit_code",
        "log_path",
        "log_raw_sha256",
    }
)
_RUN_URL = re.compile(r"^https://github\.com/yduchesne/quervant/actions/runs/[1-9][0-9]*$")

#: The only permitted ``(gate, check_id) -> (executor, job_name)`` mapping.
GATE_CHECK_EXECUTORS: dict[tuple[str, str], tuple[str, str]] = {}


def _register(gate: str, executor: str, job_name: str, check_ids: tuple[str, ...]) -> None:
    for check_id in check_ids:
        key = (gate, check_id)
        if key in GATE_CHECK_EXECUTORS:  # pragma: no cover - construction guard
            raise RuntimeError(f"duplicate QA check registration: {key}")
        GATE_CHECK_EXECUTORS[key] = (executor, job_name)


_register(
    "framework-qa",
    "hosted-ci",
    "rust",
    ("benchmark-scripts",),
)
_register(
    "framework-qa",
    "hosted-ci",
    "python-contracts",
    (
        "bm-contract-inventory",
        "cross-engine-l2",
        "installed-console",
        "official-authorization-boundary",
        "official-control-boundary",
        "official-data-integrity",
        "official-deterministic",
        "official-independent-verification",
        "official-source-set",
        "python-compileall",
        "python-full-suite",
        "python-mutations",
        "retained-key-l2",
    ),
)
_register(
    "framework-qa",
    "hosted-ci",
    "comparative-full-correctness",
    ("official-real-correctness",),
)
_register(
    "source-qa",
    "hosted-ci",
    "comparative-full-correctness",
    (
        "adapter-build-lucene",
        "adapter-build-quervant",
        "adapter-build-tantivy",
        "adapter-correctness-10k-100k",
    ),
)
_register(
    "source-qa",
    "operator-attested",
    "operator-local",
    ("host-capability-readiness", "source-binary-digests"),
)
_register(
    "source-qa",
    "hosted-ci",
    "rust",
    (
        "rust-bench-no-run",
        "rust-clippy-stable-all-features",
        "rust-clippy-stable-default",
        "rust-coverage-85",
        "rust-doc",
        "rust-fmt-stable",
        "rust-test-stable-all-features",
        "rust-test-stable-default",
    ),
)
_register(
    "source-qa",
    "hosted-ci",
    "msrv",
    (
        "rust-clippy-msrv-all-features",
        "rust-fmt-msrv",
        "rust-test-msrv-all-features",
    ),
)
_register("source-qa", "hosted-ci", "rustfs", ("rustfs-real-hosted",))


def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def _require_roster_mapping() -> None:
    framework = {check for (gate, check) in GATE_CHECK_EXECUTORS if gate == "framework-qa"}
    source = {check for (gate, check) in GATE_CHECK_EXECUTORS if gate == "source-qa"}
    if framework != set(FRAMEWORK_QA_ROSTER) or source != set(SOURCE_QA_ROSTER):
        raise BenchError(
            BM_SCHEMA_INVALID,
            "the frozen QA job map does not match the exact official rosters",
            field_path="GATE_CHECK_EXECUTORS",
        )


def check_record_relative(gate: str, check_id: str) -> str:
    """Return the exact relative path of one executed check record."""

    return f"{gate}/{validate_semantic_id(check_id, 'check_id')}.json"


def check_log_relative(gate: str, check_id: str) -> str:
    """Return the exact relative path of one executed check log."""

    return f"logs/{gate}/{validate_semantic_id(check_id, 'check_id')}.log"


def _expected_members() -> tuple[str, ...]:
    _require_roster_mapping()
    members: list[str] = []
    for gate, roster in (
        ("framework-qa", FRAMEWORK_QA_ROSTER),
        ("source-qa", SOURCE_QA_ROSTER),
    ):
        for check_id in roster:
            members.append(check_record_relative(gate, check_id))
            members.append(check_log_relative(gate, check_id))
    return tuple(sorted(members))


def _validate_roots(
    *, qa_evidence_root: Path, output_root: Path, raw_root: Path
) -> Path:
    root = require_safe_root(Path(qa_evidence_root))
    resolved = root.resolve()
    repository = repository_root().resolve()
    if resolved == repository or repository in resolved.parents:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the QA evidence root must not be inside the repository",
            field_path="qa_evidence_root",
        )
    for forbidden in ("target", "benchmark-results"):
        candidate = (repository / forbidden).resolve()
        if resolved == candidate or candidate in resolved.parents:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "the QA evidence root must not be a build/run/output directory",
                field_path="qa_evidence_root",
            )
    for label, other in (("output_root", output_root), ("raw_root", raw_root)):
        candidate = Path(other)
        try:
            other_resolved = candidate.resolve()
        except OSError:  # pragma: no cover - defensive
            raise BenchError(BM_UNSAFE_INPUT, f"{label} cannot be resolved safely") from None
        if resolved == other_resolved or other_resolved in resolved.parents:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"the QA evidence root must be disjoint from the {label}",
                field_path="qa_evidence_root",
            )
    return root


def _walk_members(root: Path) -> tuple[str, ...]:
    """Return every regular file beneath ``root``, rejecting links and specials."""

    import os
    import stat

    members: list[str] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in list(dirnames):
            if (current_path / name).is_symlink():
                raise BenchError(
                    BM_UNSAFE_INPUT,
                    "the QA evidence root must not contain symbolic links",
                    field_path="qa_evidence_root",
                )
        for name in sorted(filenames):
            candidate = current_path / name
            info = os.lstat(candidate)
            if not stat.S_ISREG(info.st_mode):
                raise BenchError(
                    BM_UNSAFE_INPUT, "QA evidence members must be regular files"
                )
            if info.st_nlink != 1:
                raise BenchError(
                    BM_UNSAFE_INPUT, "QA evidence members must not be hard links"
                )
            members.append(str(candidate.relative_to(root)).replace(os.sep, "/"))
    return tuple(sorted(members))


def _read_member_bytes(root: Path, relative: str, *, limit: int) -> bytes:
    member = validate_relative_member(relative)
    handle = open_regular_beneath(root, member)
    with handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"QA evidence member exceeds the {limit}-byte budget",
            reference=member,
        )
    return payload


def _validate_execution_reference(
    *, executor: str, job_name: str, reference: object, check_id: str
) -> str:
    if not isinstance(reference, str) or not reference:
        raise BenchError(
            BM_SCHEMA_INVALID, "execution_reference must be a non-empty string", check_id
        )
    if executor == "hosted-ci":
        if _RUN_URL.fullmatch(reference) is None:
            raise _fail(
                "a hosted-ci check needs the exact workflow run URL of this repository",
                check_id,
            )
    else:
        if len(reference) > 64 or validate_semantic_id(reference, "execution_reference") != reference:
            raise _fail(
                "an operator-attested check needs an approved semantic execution identity",
                check_id,
            )
    if job_name == "operator-local" and executor != "operator-attested":
        raise _fail("an operator-local job must not be labelled hosted-ci", check_id)
    if executor == "hosted-ci" and job_name == "operator-local":
        raise _fail("a hosted job must not use the operator-local identity", check_id)
    return reference


def _validate_check_record(
    *,
    root: Path,
    gate: str,
    check_id: str,
    freeze: OfficialFreeze,
    summary_check: Mapping[str, Any],
) -> tuple[dict[str, Any], bytes]:
    relative = check_record_relative(gate, check_id)
    payload = _read_member_bytes(root, relative, limit=MAX_CHECK_RECORD_BYTES)
    document = loads_json(decode_text(payload))
    if not isinstance(document, Mapping):
        raise BenchError(BM_SCHEMA_INVALID, "an executed QA check record must be an object")
    if canonical_document_bytes(dict(document)) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "an executed QA check record is not stored in canonical byte form",
            reference=relative,
        )
    record = require_closed(document, "executed-qa-check", _CHECK_KEYS)
    if record["kind"] != EXECUTED_CHECK_KIND:
        raise BenchError(BM_SCHEMA_INVALID, "the executed QA check kind is not recognised")
    if require_uint(record["schema_version"], "schema_version") != 1:
        raise BenchError(BM_SCHEMA_INVALID, "the executed QA check schema_version is unsupported")
    if (record["evidence_origin"], record["qualification_scope"]) != (
        REAL_ORIGIN,
        OFFICIAL_SCOPE,
    ):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "an executed QA check record must be real/official evidence",
            field_path="qualification_scope",
        )
    if record["qa_gate"] != gate:
        raise _fail("the executed QA check gate does not match its directory", check_id)
    if record["check_id"] != check_id:
        raise _fail("the executed QA check id does not match its file name", check_id)
    if validate_source_commit(record["source_commit"], "source_commit") != freeze.source_commit:
        raise _fail("the executed QA check was run on a different source commit", check_id)
    if (
        validate_digest(record["source_set_digest"], "source_set_digest")
        != freeze.source_file_set_digest
    ):
        raise _fail("the executed QA check covers a different source set", check_id)
    if record["toolchain_id"] != toolchain_for(gate):
        raise _fail("the executed QA check used a different toolchain", check_id)
    executor = record["executor"]
    if executor not in EXECUTORS:
        raise _fail("the executed QA check executor is not recognised", check_id)
    expected_executor, expected_job = GATE_CHECK_EXECUTORS[(gate, check_id)]
    if executor != expected_executor or record["job_name"] != expected_job:
        raise _fail(
            "the executed QA check runner/job is not the frozen identity for this check",
            check_id,
        )
    _validate_execution_reference(
        executor=executor,
        job_name=str(record["job_name"]),
        reference=record["execution_reference"],
        check_id=check_id,
    )
    if record["executed"] is not True:
        raise _fail("the executed QA check is not marked executed", check_id)
    if record["status"] != "pass":
        raise _fail("the executed QA check is not passing", check_id)
    for name in ("failed", "mandatory_skipped", "command_exit_code"):
        require_uint(record[name], name)
        if record[name] != 0:
            raise _fail(f"the executed QA check records {name} != 0", check_id)
    expected_log = check_log_relative(gate, check_id)
    if record["log_path"] != expected_log:
        raise _fail("the executed QA check log path is not the frozen relative path", check_id)
    log_digest, log_length = sha256_regular_file(root, expected_log, max_bytes=MAX_LOG_BYTES)
    if log_length == 0:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "an executed QA check log is empty", reference=expected_log
        )
    if validate_digest(record["log_raw_sha256"], "log_raw_sha256") != log_digest:
        raise _fail("the executed QA check log bytes do not match the record", check_id)
    observed_record_digest = document_digest(record)
    if observed_record_digest != validate_digest(
        summary_check["evidence_digest"], "summary.evidence_digest"
    ):
        raise _fail(
            "the executed QA check record does not match the G0-pinned summary entry",
            check_id,
        )
    return record, payload


def _verify_gate(
    *,
    root: Path,
    gate: str,
    roster: tuple[str, ...],
    summary: Mapping[str, Any],
    freeze: OfficialFreeze,
    snapshot: dict[str, str],
    budget: list[int],
) -> None:
    pinned = (
        freeze.qa_framework_digest if gate == "framework-qa" else freeze.qa_source_digest
    )
    if document_digest(dict(summary)) != pinned:
        raise _fail(
            "the QA summary does not match the independently pinned G0 digest",
            "qa_framework_digest" if gate == "framework-qa" else "qa_source_digest",
        )
    checks = summary["checks"]
    if tuple(check["check_id"] for check in checks) != roster:  # pragma: no cover - shape
        raise _fail("the QA summary check roster is not the frozen roster", gate)
    for index, check_id in enumerate(roster):
        _record, record_bytes = _validate_check_record(
            root=root,
            gate=gate,
            check_id=check_id,
            freeze=freeze,
            summary_check=checks[index],
        )
        log_relative = check_log_relative(gate, check_id)
        log_digest, log_length = sha256_regular_file(
            root, log_relative, max_bytes=MAX_LOG_BYTES
        )
        budget[0] += len(record_bytes) + log_length
        if budget[0] > MAX_TOTAL_BYTES:
            raise BenchError(
                BM_UNSAFE_INPUT, "the QA evidence exceeds the total byte budget"
            )
        snapshot[check_record_relative(gate, check_id)] = document_digest_hex(record_bytes)
        snapshot[log_relative] = log_digest


def document_digest_hex(payload: bytes) -> str:
    """Return the ``sha256:`` digest of raw member bytes."""

    import hashlib

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def verify_executed_qa_evidence(
    *,
    qa_evidence_root: Path,
    framework_summary: Mapping[str, Any],
    source_summary: Mapping[str, Any],
    freeze: OfficialFreeze,
    output_root: Path,
    raw_root: Path,
) -> dict[str, str]:
    """Verify both complete rosters and return the 66-member raw snapshot."""

    root = _validate_roots(
        qa_evidence_root=qa_evidence_root, output_root=output_root, raw_root=raw_root
    )
    expected = _expected_members()
    observed = _walk_members(root)
    if observed != expected:
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        if missing:
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                "a required executed QA evidence member is unavailable",
                reference=missing[0],
            )
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the QA evidence root contains an unexpected member",
            reference=extra[0],
        )
    validated_framework = validate_official_qa(dict(framework_summary), "framework-qa")
    validated_source = validate_official_qa(dict(source_summary), "source-qa")
    for summary, gate in ((validated_framework, "framework-qa"), (validated_source, "source-qa")):
        if summary["source_set_digest"] != freeze.source_file_set_digest:
            raise _fail("a QA summary covers a different source set", gate)
    snapshot: dict[str, str] = {}
    budget = [0]
    _verify_gate(
        root=root,
        gate="framework-qa",
        roster=FRAMEWORK_QA_ROSTER,
        summary=validated_framework,
        freeze=freeze,
        snapshot=snapshot,
        budget=budget,
    )
    _verify_gate(
        root=root,
        gate="source-qa",
        roster=SOURCE_QA_ROSTER,
        summary=validated_source,
        freeze=freeze,
        snapshot=snapshot,
        budget=budget,
    )
    if len(snapshot) != len(expected):
        raise _fail("the executed QA snapshot is not the complete 66-member set", "snapshot")
    return dict(sorted(snapshot.items()))


def reverify_executed_qa_evidence(
    *,
    qa_evidence_root: Path,
    expected_snapshot: Mapping[str, str],
    framework_summary: Mapping[str, Any],
    source_summary: Mapping[str, Any],
    freeze: OfficialFreeze,
    output_root: Path,
    raw_root: Path,
) -> None:
    """Repeat every no-follow read and require the exact unchanged snapshot."""

    if not isinstance(expected_snapshot, Mapping) or len(expected_snapshot) != 66:
        raise _fail("the expected QA snapshot is not the complete 66-member set", "snapshot")
    observed = verify_executed_qa_evidence(
        qa_evidence_root=qa_evidence_root,
        framework_summary=framework_summary,
        source_summary=source_summary,
        freeze=freeze,
        output_root=output_root,
        raw_root=raw_root,
    )
    if dict(observed) != dict(expected_snapshot):
        differences = sorted(
            key
            for key in set(observed) | set(expected_snapshot)
            if observed.get(key) != expected_snapshot.get(key)
        )
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the executed QA evidence changed after verification",
            reference=differences[0] if differences else None,
        )


__all__ = [
    "EXECUTED_CHECK_KIND",
    "EXECUTORS",
    "GATE_CHECK_EXECUTORS",
    "MAX_CHECK_RECORD_BYTES",
    "MAX_LOG_BYTES",
    "MAX_TOTAL_BYTES",
    "check_log_relative",
    "check_record_relative",
    "document_digest_hex",
    "reverify_executed_qa_evidence",
    "verify_executed_qa_evidence",
]
