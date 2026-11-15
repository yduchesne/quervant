"""Closed internal v1 contracts for trusted admission specs and admission indices.

These are **not** additional public BM-01 schemas. They are local, immutable,
hand-validated documents built with the BM-01 codecs. The trusted spec is the
only authority describing expected evidence bytes; it is supplied together with
an independently pinned canonical digest.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from ..config.codec import content_digest, decode_text, loads_json
from ..config.contracts import validate_origin_scope
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import (
    validate_digest,
    validate_positive_int,
    validate_semantic_id,
    validate_uuid4,
)
from .archives import ArchiveLimits, MemberDigest
from .paths import validate_relative_member

SPEC_KIND = "trusted-admission-spec"
INDEX_KIND = "admission-index"
SPEC_SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1

LOCK_NAMES: tuple[str, ...] = (
    "adapter-lock",
    "analysis-lock",
    "build-lock",
    "schema-registry",
    "source-lock",
)

#: Semantic evidence name carrying each lock record.
LOCK_RECORD_NAMES: dict[str, str] = {
    "adapter-lock": "record-adapter",
    "analysis-lock": "record-analysis",
    "build-lock": "record-build",
    "schema-registry": "record-schema",
    "source-lock": "record-source",
}

RECORD_ENVIRONMENT = "record-environment"
RECORD_QA = "record-qa"
RECORD_EVIDENCE = "synthetic-evidence"
ARCHIVE_TAR_NAME = "synthetic-tar"
ARCHIVE_ZIP_NAME = "synthetic-zip"

REQUIRED_EVIDENCE_NAMES: tuple[str, ...] = (
    "record-adapter",
    "record-analysis",
    "record-build",
    "record-environment",
    "record-qa",
    "record-schema",
    "record-source",
    "synthetic-evidence",
    ARCHIVE_TAR_NAME,
    ARCHIVE_ZIP_NAME,
)

RESERVED_INPUT_NAMES: frozenset[str] = frozenset(
    {
        "trusted-spec",
        "protocol-lock",
        "workload-lock",
        "validator-lock",
        "policy-lock",
        "qa-roster-lock",
        *LOCK_NAMES,
    }
)

MAX_DECLARED_ENTRIES = 256
MAX_COMBINED_ARCHIVE_MEMBERS = 5000

_SUBJECT_KEYS = frozenset(
    {"experiment_id", "run_id", "protocol_digest", "workload_digest"}
)
_VALIDATOR_KEYS = frozenset(
    {"validator_id", "validator_version", "source_digest"}
)
_SPEC_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "subject",
        "evidence_origin",
        "qualification_scope",
        "validator",
        "policy_digest",
        "qa_roster_digest",
        "locks",
        "files",
        "archives",
    }
)
_INDEX_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "subject",
        "evidence_origin",
        "qualification_scope",
        "trusted_spec_digest",
        "locks",
        "files",
        "archives",
    }
)
_LOCK_KEYS = frozenset({"name", "digest"})
_FILE_KEYS = frozenset({"name", "path", "byte_length", "digest"})
_ARCHIVE_KEYS = frozenset(
    {"name", "path", "format", "byte_length", "digest", "members"}
)
_MEMBER_KEYS = frozenset({"name", "byte_length", "digest"})
_ARCHIVE_FORMATS = frozenset({"tar-gz", "zip"})


@dataclass(frozen=True)
class SpecSubject:
    experiment_id: str
    run_id: str
    protocol_digest: str
    workload_digest: str


@dataclass(frozen=True)
class SpecValidator:
    validator_id: str
    validator_version: int
    source_digest: str


@dataclass(frozen=True)
class SpecLock:
    name: str
    digest: str


@dataclass(frozen=True)
class SpecFile:
    name: str
    path: str
    byte_length: int
    digest: str


@dataclass(frozen=True)
class SpecArchive:
    name: str
    path: str
    format: str
    byte_length: int
    digest: str
    members: tuple[MemberDigest, ...]


@dataclass(frozen=True)
class TrustedAdmissionSpec:
    kind: str
    schema_version: int
    subject: SpecSubject
    evidence_origin: str
    qualification_scope: str
    validator: SpecValidator
    policy_digest: str
    qa_roster_digest: str
    locks: tuple[SpecLock, ...]
    files: tuple[SpecFile, ...]
    archives: tuple[SpecArchive, ...]
    payload: Mapping[str, Any]


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BenchError(
            BM_SCHEMA_INVALID, f"{field} must be a JSON object", field_path=field
        )
    return value


def _require_exact_keys(
    document: Mapping[str, Any], expected: frozenset[str], field: str
) -> None:
    observed = set(document)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"{field} must use the exact closed field set "
            f"(missing={missing}, extra={extra})",
            field_path=field,
        )


def _list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise BenchError(
            BM_SCHEMA_INVALID, f"{field} must be an array", field_path=field
        )
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BenchError(
            BM_SCHEMA_INVALID, f"{field} must be an integer", field_path=field
        )
    if value < 0:
        raise BenchError(
            BM_SCHEMA_INVALID, f"{field} must be non-negative", field_path=field
        )
    return value


def _require_version(document: Mapping[str, Any], kind: str, version: int) -> None:
    if document.get("kind") != kind:
        raise BenchError(
            BM_SCHEMA_INVALID, f"kind must be {kind!r}", field_path="kind"
        )
    observed = document.get("schema_version")
    if isinstance(observed, bool) or not isinstance(observed, int) or observed != version:
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"schema_version must be {version}",
            field_path="schema_version",
        )


def _validate_subject(value: object) -> SpecSubject:
    document = _mapping(value, "subject")
    _require_exact_keys(document, _SUBJECT_KEYS, "subject")
    return SpecSubject(
        experiment_id=validate_semantic_id(
            document["experiment_id"], "subject.experiment_id"
        ),
        run_id=validate_uuid4(document["run_id"], "subject.run_id"),
        protocol_digest=validate_digest(
            document["protocol_digest"], "subject.protocol_digest"
        ),
        workload_digest=validate_digest(
            document["workload_digest"], "subject.workload_digest"
        ),
    )


def _validate_validator(value: object) -> SpecValidator:
    document = _mapping(value, "validator")
    _require_exact_keys(document, _VALIDATOR_KEYS, "validator")
    return SpecValidator(
        validator_id=validate_semantic_id(
            document["validator_id"], "validator.validator_id"
        ),
        validator_version=validate_positive_int(
            document["validator_version"], "validator.validator_version"
        ),
        source_digest=validate_digest(
            document["source_digest"], "validator.source_digest"
        ),
    )


def _validate_locks(value: object) -> tuple[SpecLock, ...]:
    entries = _list(value, "locks")
    locks: list[SpecLock] = []
    for index, raw in enumerate(entries):
        document = _mapping(raw, f"locks[{index}]")
        _require_exact_keys(document, _LOCK_KEYS, f"locks[{index}]")
        locks.append(
            SpecLock(
                name=validate_semantic_id(
                    document["name"], f"locks[{index}].name"
                ),
                digest=validate_digest(
                    document["digest"], f"locks[{index}].digest"
                ),
            )
        )
    names = [lock.name for lock in locks]
    if len(set(names)) != len(names):
        raise BenchError(BM_IDENTITY_INVALID, "lock names must be unique")
    if tuple(names) != LOCK_NAMES:
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"locks must contain exactly the sorted names {list(LOCK_NAMES)}",
        )
    return tuple(locks)


def _validate_members(value: object, field: str, limits: ArchiveLimits) -> tuple[MemberDigest, ...]:
    entries = _list(value, field)
    members: list[MemberDigest] = []
    for index, raw in enumerate(entries):
        document = _mapping(raw, f"{field}[{index}]")
        _require_exact_keys(document, _MEMBER_KEYS, f"{field}[{index}]")
        name = validate_relative_member(document["name"])
        byte_length = _nonnegative_int(
            document["byte_length"], f"{field}[{index}].byte_length"
        )
        if byte_length > limits.max_member_bytes:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"{field}[{index}] exceeds the member byte limit",
            )
        members.append(
            MemberDigest(
                name=name,
                digest=validate_digest(
                    document["digest"], f"{field}[{index}].digest"
                ),
                byte_length=byte_length,
            )
        )
    names = [member.name for member in members]
    if len(set(names)) != len(names):
        raise BenchError(BM_IDENTITY_INVALID, f"{field} member names must be unique")
    if names != sorted(names):
        raise BenchError(
            BM_IDENTITY_INVALID, f"{field} members must be sorted by name"
        )
    return tuple(members)


def _validate_evidence_lists(
    files_value: object, archives_value: object
) -> tuple[tuple[SpecFile, ...], tuple[SpecArchive, ...]]:
    limits = ArchiveLimits()
    raw_files = _list(files_value, "files")
    raw_archives = _list(archives_value, "archives")
    if not raw_files and not raw_archives:
        raise BenchError(
            BM_IDENTITY_INVALID, "at least one declared evidence entry is required"
        )
    if len(raw_files) + len(raw_archives) > MAX_DECLARED_ENTRIES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"at most {MAX_DECLARED_ENTRIES} evidence entries may be declared",
        )

    files: list[SpecFile] = []
    for index, raw in enumerate(raw_files):
        document = _mapping(raw, f"files[{index}]")
        _require_exact_keys(document, _FILE_KEYS, f"files[{index}]")
        byte_length = _nonnegative_int(
            document["byte_length"], f"files[{index}].byte_length"
        )
        if byte_length > limits.max_member_bytes:
            raise BenchError(
                BM_UNSAFE_INPUT, f"files[{index}] exceeds the member byte limit"
            )
        files.append(
            SpecFile(
                name=validate_semantic_id(
                    document["name"], f"files[{index}].name"
                ),
                path=validate_relative_member(document["path"]),
                byte_length=byte_length,
                digest=validate_digest(
                    document["digest"], f"files[{index}].digest"
                ),
            )
        )
    if [item.name for item in files] != sorted(item.name for item in files):
        raise BenchError(BM_IDENTITY_INVALID, "files must be sorted by name")

    archives: list[SpecArchive] = []
    member_total = 0
    for index, raw in enumerate(raw_archives):
        document = _mapping(raw, f"archives[{index}]")
        _require_exact_keys(document, _ARCHIVE_KEYS, f"archives[{index}]")
        archive_format = document["format"]
        if archive_format not in _ARCHIVE_FORMATS:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"archives[{index}].format must be one of {sorted(_ARCHIVE_FORMATS)}",
                field_path=f"archives[{index}].format",
            )
        byte_length = _nonnegative_int(
            document["byte_length"], f"archives[{index}].byte_length"
        )
        if byte_length > limits.max_archive_bytes:
            raise BenchError(
                BM_UNSAFE_INPUT, f"archives[{index}] exceeds the archive byte limit"
            )
        members = _validate_members(
            document["members"], f"archives[{index}].members", limits
        )
        member_total += len(members)
        if member_total > MAX_COMBINED_ARCHIVE_MEMBERS:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"at most {MAX_COMBINED_ARCHIVE_MEMBERS} archive members may be declared",
            )
        archives.append(
            SpecArchive(
                name=validate_semantic_id(
                    document["name"], f"archives[{index}].name"
                ),
                path=validate_relative_member(document["path"]),
                format=archive_format,
                byte_length=byte_length,
                digest=validate_digest(
                    document["digest"], f"archives[{index}].digest"
                ),
                members=members,
            )
        )
    if [item.name for item in archives] != sorted(item.name for item in archives):
        raise BenchError(BM_IDENTITY_INVALID, "archives must be sorted by name")

    names = [item.name for item in files] + [item.name for item in archives]
    if len(set(names)) != len(names):
        raise BenchError(
            BM_IDENTITY_INVALID, "evidence names must be unique across files and archives"
        )
    reserved = sorted(set(names) & RESERVED_INPUT_NAMES)
    if reserved:
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"evidence names must not shadow reserved receipt inputs: {reserved}",
        )
    paths = [item.path for item in files] + [item.path for item in archives]
    if len(set(paths)) != len(paths):
        raise BenchError(
            BM_IDENTITY_INVALID, "evidence paths must be unique across files and archives"
        )
    return tuple(files), tuple(archives)


def _validate_spec_document(document: object) -> TrustedAdmissionSpec:
    spec = _mapping(document, SPEC_KIND)
    _require_exact_keys(spec, _SPEC_KEYS, SPEC_KIND)
    _require_version(spec, SPEC_KIND, SPEC_SCHEMA_VERSION)
    subject = _validate_subject(spec["subject"])
    origin, scope = validate_origin_scope(
        spec["evidence_origin"], spec["qualification_scope"]
    )
    validator = _validate_validator(spec["validator"])
    policy_digest = validate_digest(spec["policy_digest"], "policy_digest")
    qa_roster_digest = validate_digest(
        spec["qa_roster_digest"], "qa_roster_digest"
    )
    locks = _validate_locks(spec["locks"])
    files, archives = _validate_evidence_lists(spec["files"], spec["archives"])
    return TrustedAdmissionSpec(
        kind=SPEC_KIND,
        schema_version=SPEC_SCHEMA_VERSION,
        subject=subject,
        evidence_origin=origin,
        qualification_scope=scope,
        validator=validator,
        policy_digest=policy_digest,
        qa_roster_digest=qa_roster_digest,
        locks=locks,
        files=files,
        archives=archives,
        payload=copy.deepcopy(dict(spec)),
    )


def load_trusted_spec(
    spec_bytes: bytes, *, expected_spec_digest: str
) -> TrustedAdmissionSpec:
    """Parse and validate a trusted spec against an independently pinned digest."""

    expected = validate_digest(
        expected_spec_digest, "expected_spec_digest"
    )
    text = decode_text(spec_bytes)
    document = loads_json(text)
    spec = _validate_spec_document(document)
    observed = content_digest(document)
    if observed != expected:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "trusted spec digest does not match the independently pinned anchor",
        )
    return spec


def spec_digest(spec: TrustedAdmissionSpec) -> str:
    """Return the canonical content digest of a trusted spec payload."""

    return content_digest(spec.payload)


def validate_admission_index(document: object) -> Mapping[str, Any]:
    """Validate the closed v1 admission-index shape without trusting its bytes."""

    index = _mapping(document, INDEX_KIND)
    _require_exact_keys(index, _INDEX_KEYS, INDEX_KIND)
    _require_version(index, INDEX_KIND, INDEX_SCHEMA_VERSION)
    _validate_subject(index["subject"])
    origin, scope = validate_origin_scope(
        index["evidence_origin"], index["qualification_scope"]
    )
    if (origin, scope) != ("synthetic", "simulated"):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "admission indices are synthetic/simulated only",
            field_path="qualification_scope",
        )
    validate_digest(index["trusted_spec_digest"], "trusted_spec_digest")
    _validate_locks(index["locks"])
    files, archives = _validate_evidence_lists(index["files"], index["archives"])
    if not files and not archives:  # pragma: no cover - guarded above
        raise BenchError(BM_IDENTITY_INVALID, "admission index is empty")
    return index
