"""Read-only synthetic evidence admission and full revalidation on reuse.

This module never times, schedules, profiles, executes a measured campaign or
issues a real/official qualification. It verifies caller-pinned expectations
against actual bytes, builds a canonical admission index and a v1 admission
receipt, and publishes them exclusively.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from ..config import contracts, schemas
from ..config.codec import (
    MAX_DOCUMENT_BYTES,
    content_digest,
    decode_text,
    loads_json,
    sha256_prefix,
)
from ..config.contracts import Receipt, load_experiment_bundle
from ..config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_SCOPE_MISMATCH,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import (
    validate_digest,
    validate_positive_int,
    validate_semantic_id,
    validate_source_commit,
)
from ..host.capabilities import validate_host_capabilities
from .archives import ArchiveLimits, inspect_tar_gz, inspect_zip
from .hashing import sha256_regular_file
from .manifests import (
    ARCHIVE_TAR_NAME,
    ARCHIVE_ZIP_NAME,
    LOCK_NAMES,
    LOCK_RECORD_NAMES,
    RECORD_ENVIRONMENT,
    RECORD_EVIDENCE,
    RECORD_QA,
    REQUIRED_EVIDENCE_NAMES,
    TrustedAdmissionSpec,
    spec_digest,
    validate_admission_index,
)
from .paths import (
    list_directory_beneath,
    open_regular_beneath,
    require_disjoint_admission_roots,
    validate_relative_member,
)
from .provenance import (
    VALIDATOR_SOURCE_PATHS,
    repository_root,
    verify_git_commit,
    verify_validator_source,
)
from .publication import load_committed_admission, publish_admission
from .receipts import (
    build_admission_receipt,
    require_verified_locks,
    verify_admission_receipt,
)

_TREE_SHA_RE = __import__("re").compile(r"^[0-9a-f]{40}$")
_SOURCE_FILE_KEYS = frozenset({"path", "digest"})
_ADAPTER_KEYS = frozenset(
    {"kind", "schema_version", "adapter_id", "adapter_version", "adapter_digest"}
)
_ANALYSIS_KEYS = frozenset(
    {"kind", "schema_version", "analysis_id", "analysis_version", "analysis_digest"}
)
_BUILD_KEYS = frozenset({"kind", "schema_version", "build_identity"})
_SCHEMA_KEYS = frozenset({"kind", "schema_version", "schemas"})
_SCHEMA_ENTRY_KEYS = frozenset({"id", "digest"})
_SOURCE_KEYS = frozenset({"kind", "schema_version", "commit", "tree_sha", "files"})
_QA_KEYS = frozenset({"kind", "schema_version", "tests"})
_EVIDENCE_KEYS = frozenset(
    {"kind", "schema_version", "evidence_origin", "qualification_scope", "records"}
)


@dataclass(frozen=True)
class AdmissionResult:
    """Typed outcome of a synthetic admission or a verified reuse."""

    disposition: Literal["ADMITTED_SYNTHETIC", "REUSED_VERIFIED"]
    receipt: Receipt
    admission_index_digest: str
    output_root: Path


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _experiments_root() -> Path:
    return repository_root() / "benchmarks" / "experiments"


def _require_anchor(spec: TrustedAdmissionSpec, expected: str) -> str:
    anchor = validate_digest(expected, "spec_expected_digest")
    if spec_digest(spec) != anchor:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "trusted spec digest does not match the independently pinned anchor",
        )
    return anchor


def _require_synthetic_scope(spec: TrustedAdmissionSpec) -> None:
    origin, scope = contracts.validate_origin_scope(
        spec.evidence_origin, spec.qualification_scope
    )
    if (origin, scope) == ("real", "official"):
        raise BenchError(
            BM_ACQUISITION_PROHIBITED,
            "BM-02 does not admit real/official evidence or acquire measurements",
        )
    if (origin, scope) != ("synthetic", "simulated"):
        raise BenchError(
            BM_SCOPE_MISMATCH,
            "BM-02 only issues synthetic/simulated admission receipts",
        )


#: Fixed checked-in synthetic catalog used by the BM-02 vertical slice.
SYNTHETIC_CATALOG_EXPERIMENT = "synthetic-contract-smoke"


def _require_required_evidence(spec: TrustedAdmissionSpec) -> None:
    names = {item.name for item in spec.files}
    names.update(item.name for item in spec.archives)
    missing = [name for name in REQUIRED_EVIDENCE_NAMES if name not in names]
    if missing:
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"trusted spec is missing required evidence entries: {missing}",
        )
    if spec.subject.experiment_id != SYNTHETIC_CATALOG_EXPERIMENT:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "BM-02 admission is bound to the checked-in synthetic contract catalog",
        )


def _preflight(
    spec: TrustedAdmissionSpec,
    spec_expected_digest: str,
    verified_locks: Mapping[str, str],
) -> str:
    anchor = _require_anchor(spec, spec_expected_digest)
    _require_synthetic_scope(spec)
    _require_required_evidence(spec)
    require_verified_locks(spec, verified_locks)
    return anchor


def _spec_file(spec: TrustedAdmissionSpec, name: str):
    for entry in spec.files:
        if entry.name == name:
            return entry
    raise BenchError(
        BM_IDENTITY_INVALID, f"trusted spec does not declare evidence {name!r}"
    )


def _read_document(evidence_root: Path, relative: str) -> dict:
    handle = open_regular_beneath(evidence_root, relative)
    with handle:
        payload = handle.read(MAX_DOCUMENT_BYTES + 1)
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT, "evidence document exceeds the canonical size limit"
        )
    document = loads_json(decode_text(payload))
    if not isinstance(document, dict):
        raise BenchError(
            BM_IDENTITY_INVALID, "evidence record must be a JSON object"
        )
    return document


def _require_closed_directories(
    evidence_root: Path, declared_paths: list[str]
) -> None:
    groups: dict[str, set[str]] = {}
    for path in declared_paths:
        parent, _, base = path.rpartition("/")
        groups.setdefault(parent, set()).add(base)
    for parent in sorted(groups):
        actual = set(list_directory_beneath(evidence_root, parent))
        declared = groups[parent]
        extras = sorted(actual - declared)
        if extras:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"evidence directory {parent!r} contains undeclared entries: {extras}",
            )
        if declared - actual:
            raise BenchError(
                BM_FILE_MISSING,
                f"evidence directory {parent!r} is missing declared entries",
            )


def _observe_files(
    spec: TrustedAdmissionSpec, evidence_root: Path, limits: ArchiveLimits
) -> list[dict]:
    observed: list[dict] = []
    for entry in spec.files:
        digest, length = sha256_regular_file(
            evidence_root, entry.path, max_bytes=limits.max_member_bytes
        )
        if length != entry.byte_length or digest != entry.digest:
            raise BenchError(
                BM_IDENTITY_INVALID,
                f"evidence file does not match the trusted declaration: {entry.path}",
            )
        observed.append(
            {
                "name": entry.name,
                "path": entry.path,
                "byte_length": length,
                "digest": digest,
            }
        )
    return observed


def _observe_archives(
    spec: TrustedAdmissionSpec, evidence_root: Path, limits: ArchiveLimits
) -> list[dict]:
    observed: list[dict] = []
    for entry in spec.archives:
        digest, length = sha256_regular_file(
            evidence_root, entry.path, max_bytes=limits.max_archive_bytes
        )
        if length != entry.byte_length or digest != entry.digest:
            raise BenchError(
                BM_IDENTITY_INVALID,
                f"evidence archive does not match the trusted declaration: {entry.path}",
            )
        if entry.format == "tar-gz":
            members = inspect_tar_gz(evidence_root, entry.path, limits)
        elif entry.format == "zip":
            members = inspect_zip(evidence_root, entry.path, limits)
        else:  # pragma: no cover - guarded by the closed spec validator
            raise BenchError(BM_UNSAFE_INPUT, "unsupported archive format")
        if members != entry.members:
            raise BenchError(
                BM_IDENTITY_INVALID,
                f"archive members do not match the trusted declaration: {entry.path}",
            )
        observed.append(
            {
                "name": entry.name,
                "path": entry.path,
                "format": entry.format,
                "byte_length": length,
                "digest": digest,
                "members": [
                    {
                        "name": member.name,
                        "byte_length": member.byte_length,
                        "digest": member.digest,
                    }
                    for member in members
                ],
            }
        )
    return observed


def _observe_evidence(
    spec: TrustedAdmissionSpec, evidence_root: Path
) -> tuple[list[dict], list[dict]]:
    limits = ArchiveLimits()
    declared = [entry.path for entry in spec.files]
    declared.extend(entry.path for entry in spec.archives)
    _require_closed_directories(evidence_root, declared)
    files = _observe_files(spec, evidence_root, limits)
    archives = _observe_archives(spec, evidence_root, limits)
    return files, archives


def _require_exact_keys(document: Mapping[str, Any], expected: frozenset[str], field: str) -> None:
    if set(document) != expected:
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"{field} must use the exact closed field set",
        )


def _schema_registry_entries() -> list[dict]:
    registry = schemas.registry()
    entries: list[dict] = []
    for kind, version in sorted(registry):
        path = registry[(kind, version)]
        entries.append(
            {
                "id": schemas.schema_id(kind, version),
                "digest": sha256_prefix(path.read_bytes()),
            }
        )
    entries.sort(key=lambda item: item["id"])
    if len(entries) != 6:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the BM-01 schema registry must contain exactly six v1 schemas",
        )
    return entries


def _validate_adapter_record(
    record: Mapping[str, Any], bundle: contracts.ExperimentBundle
) -> None:
    _require_exact_keys(record, _ADAPTER_KEYS, "adapter-lock")
    if record["kind"] != "adapter-lock" or record["schema_version"] != 1:
        raise BenchError(BM_IDENTITY_INVALID, "adapter lock kind/version is invalid")
    adapter_id = validate_semantic_id(record["adapter_id"], "adapter-lock.adapter_id")
    adapter_version = validate_positive_int(
        record["adapter_version"], "adapter-lock.adapter_version"
    )
    adapter_digest = validate_digest(
        record["adapter_digest"], "adapter-lock.adapter_digest"
    )
    if adapter_id != bundle.adapter.adapter_id:
        raise BenchError(BM_IDENTITY_INVALID, "adapter lock adapter_id mismatch")
    if adapter_version != bundle.adapter.adapter_version:
        raise BenchError(BM_IDENTITY_INVALID, "adapter lock adapter_version mismatch")
    if adapter_digest != content_digest(bundle.adapter_document):
        raise BenchError(BM_IDENTITY_INVALID, "adapter lock adapter digest mismatch")


def _validate_analysis_record(
    record: Mapping[str, Any], bundle: contracts.ExperimentBundle
) -> None:
    _require_exact_keys(record, _ANALYSIS_KEYS, "analysis-lock")
    if record["kind"] != "analysis-lock" or record["schema_version"] != 1:
        raise BenchError(BM_IDENTITY_INVALID, "analysis lock kind/version is invalid")
    analysis_id = validate_semantic_id(
        record["analysis_id"], "analysis-lock.analysis_id"
    )
    analysis_version = validate_positive_int(
        record["analysis_version"], "analysis-lock.analysis_version"
    )
    analysis_digest = validate_digest(
        record["analysis_digest"], "analysis-lock.analysis_digest"
    )
    binding = bundle.experiment.analysis
    if (
        analysis_id != binding.analysis_id
        or analysis_version != binding.analysis_version
        or analysis_digest != binding.analysis_digest
    ):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "analysis lock does not match the experiment analysis binding",
        )


def _validate_build_record(
    record: Mapping[str, Any], bundle: contracts.ExperimentBundle
) -> None:
    _require_exact_keys(record, _BUILD_KEYS, "build-lock")
    if record["kind"] != "build-lock" or record["schema_version"] != 1:
        raise BenchError(BM_IDENTITY_INVALID, "build lock kind/version is invalid")
    identity = record["build_identity"]
    if not isinstance(identity, Mapping) or set(identity) != {"kind"}:
        raise BenchError(
            BM_IDENTITY_INVALID, "build lock identity must be a closed object"
        )
    if identity["kind"] != "synthetic":
        raise BenchError(
            BM_IDENTITY_INVALID,
            "BM-02 only supports the synthetic build identity marker",
        )
    if bundle.adapter.build_identity.kind != "synthetic":
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the BM-01 fixture adapter does not declare a synthetic build identity",
        )


def _validate_schema_record(record: Mapping[str, Any]) -> None:
    _require_exact_keys(record, _SCHEMA_KEYS, "schema-registry")
    if record["kind"] != "schema-registry" or record["schema_version"] != 1:
        raise BenchError(BM_IDENTITY_INVALID, "schema registry kind/version is invalid")
    entries = record["schemas"]
    if not isinstance(entries, list):
        raise BenchError(BM_IDENTITY_INVALID, "schema registry entries must be an array")
    validated: list[dict] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise BenchError(BM_IDENTITY_INVALID, "schema entry must be an object")
        _require_exact_keys(entry, _SCHEMA_ENTRY_KEYS, f"schema-registry.schemas[{index}]")
        validated.append(
            {
                "id": entry["id"],
                "digest": validate_digest(
                    entry["digest"], f"schema-registry.schemas[{index}].digest"
                ),
            }
        )
    if validated != _schema_registry_entries():
        raise BenchError(
            BM_IDENTITY_INVALID,
            "schema registry does not match the checked-in v1 schema files",
        )


def _validate_source_record(record: Mapping[str, Any]) -> None:
    _require_exact_keys(record, _SOURCE_KEYS, "source-lock")
    if record["kind"] != "source-lock" or record["schema_version"] != 1:
        raise BenchError(BM_IDENTITY_INVALID, "source lock kind/version is invalid")
    commit = validate_source_commit(record["commit"], "source-lock.commit")
    tree_sha = record["tree_sha"]
    if not isinstance(tree_sha, str) or _TREE_SHA_RE.fullmatch(tree_sha) is None:
        raise BenchError(BM_IDENTITY_INVALID, "source lock tree_sha is malformed")
    files = record["files"]
    if not isinstance(files, list) or not files:
        raise BenchError(BM_IDENTITY_INVALID, "source lock files must be a non-empty array")
    expected_paths: dict[str, str] = {}
    for index, entry in enumerate(files):
        if not isinstance(entry, Mapping):
            raise BenchError(BM_IDENTITY_INVALID, "source lock file must be an object")
        _require_exact_keys(entry, _SOURCE_FILE_KEYS, f"source-lock.files[{index}]")
        path = validate_relative_member(entry["path"])
        if path in expected_paths:
            raise BenchError(BM_IDENTITY_INVALID, "source lock paths must be unique")
        expected_paths[path] = validate_digest(
            entry["digest"], f"source-lock.files[{index}].digest"
        )
    if list(expected_paths) != sorted(expected_paths):
        raise BenchError(BM_IDENTITY_INVALID, "source lock paths must be sorted")
    identity = verify_git_commit(
        repository_root(), commit, expected_paths=expected_paths
    )
    if identity.tree_sha != tree_sha:
        raise BenchError(BM_IDENTITY_INVALID, "source lock tree identity mismatch")


def _validate_qa_record(record: Mapping[str, Any], spec: TrustedAdmissionSpec) -> None:
    _require_exact_keys(record, _QA_KEYS, "qa-roster")
    if record["kind"] != "qa-roster" or record["schema_version"] != 1:
        raise BenchError(BM_IDENTITY_INVALID, "QA roster kind/version is invalid")
    tests = record["tests"]
    if not isinstance(tests, list) or not tests:
        raise BenchError(BM_IDENTITY_INVALID, "QA roster tests must be a non-empty array")
    validated = [validate_semantic_id(item, "qa-roster.tests[]") for item in tests]
    if validated != sorted(set(validated)):
        raise BenchError(BM_IDENTITY_INVALID, "QA roster tests must be sorted and unique")
    if content_digest(record) != spec.qa_roster_digest:
        raise BenchError(
            BM_IDENTITY_INVALID, "QA roster digest does not match the trusted spec"
        )


def _validate_environment_record(record: Mapping[str, Any]) -> None:
    validate_host_capabilities(record)


def _validate_evidence_record(record: Mapping[str, Any]) -> None:
    _require_exact_keys(record, _EVIDENCE_KEYS, "synthetic-evidence")
    if record["kind"] != "synthetic-evidence" or record["schema_version"] != 1:
        raise BenchError(BM_IDENTITY_INVALID, "synthetic evidence kind/version is invalid")
    if (record["evidence_origin"], record["qualification_scope"]) != (
        "synthetic",
        "simulated",
    ):
        raise BenchError(
            BM_IDENTITY_INVALID, "synthetic evidence origin/scope is invalid"
        )
    if record["records"] != []:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "BM-02 synthetic evidence must not contain measurement records",
        )


def _validate_dependencies(
    spec: TrustedAdmissionSpec,
    evidence_root: Path,
    verified_locks: Mapping[str, str],
) -> None:
    bundle = load_experiment_bundle(spec.subject.experiment_id, _experiments_root())
    if spec.subject.protocol_digest != content_digest(bundle.protocol_document):
        raise BenchError(BM_IDENTITY_INVALID, "subject protocol digest mismatch")
    if spec.subject.workload_digest != content_digest(bundle.workload_document):
        raise BenchError(BM_IDENTITY_INVALID, "subject workload digest mismatch")
    if spec.policy_digest != bundle.experiment.policy.policy_digest:
        raise BenchError(BM_IDENTITY_INVALID, "policy digest mismatch")

    records: dict[str, dict] = {}
    for name in REQUIRED_EVIDENCE_NAMES:
        if name in {ARCHIVE_TAR_NAME, ARCHIVE_ZIP_NAME}:
            continue
        entry = _spec_file(spec, name)
        records[name] = _read_document(evidence_root, entry.path)

    _validate_adapter_record(records[LOCK_RECORD_NAMES["adapter-lock"]], bundle)
    _validate_analysis_record(records[LOCK_RECORD_NAMES["analysis-lock"]], bundle)
    _validate_build_record(records[LOCK_RECORD_NAMES["build-lock"]], bundle)
    _validate_schema_record(records[LOCK_RECORD_NAMES["schema-registry"]])
    _validate_source_record(records[LOCK_RECORD_NAMES["source-lock"]])
    _validate_qa_record(records[RECORD_QA], spec)
    _validate_environment_record(records[RECORD_ENVIRONMENT])
    _validate_evidence_record(records[RECORD_EVIDENCE])

    verify_validator_source(
        _package_root(),
        VALIDATOR_SOURCE_PATHS,
        spec.validator.source_digest,
    )

    spec_locks = {lock.name: lock.digest for lock in spec.locks}
    for lock_name in LOCK_NAMES:
        record = records[LOCK_RECORD_NAMES[lock_name]]
        observed = content_digest(record)
        if observed != verified_locks[lock_name]:
            raise BenchError(
                BM_IDENTITY_INVALID,
                f"verified lock {lock_name!r} does not match the actual record",
            )
        if observed != spec_locks[lock_name]:
            raise BenchError(
                BM_IDENTITY_INVALID,
                f"lock {lock_name!r} does not match the trusted specification",
            )


def _build_index(
    spec: TrustedAdmissionSpec,
    anchor: str,
    files: list[dict],
    archives: list[dict],
) -> dict:
    index = {
        "kind": "admission-index",
        "schema_version": 1,
        "subject": {
            "experiment_id": spec.subject.experiment_id,
            "run_id": spec.subject.run_id,
            "protocol_digest": spec.subject.protocol_digest,
            "workload_digest": spec.subject.workload_digest,
        },
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "trusted_spec_digest": anchor,
        "locks": [
            {"name": lock.name, "digest": lock.digest} for lock in spec.locks
        ],
        "files": files,
        "archives": archives,
    }
    validate_admission_index(index)
    return index


def _revalidate(
    spec: TrustedAdmissionSpec,
    anchor: str,
    evidence_root: Path,
    output_base: Path,
    verified_locks: Mapping[str, str],
) -> AdmissionResult:
    index_document, receipt_document = load_committed_admission(
        output_base, spec.subject.experiment_id, spec.subject.run_id
    )
    files, archives = _observe_evidence(spec, evidence_root)
    _validate_dependencies(spec, evidence_root, verified_locks)
    files_again, archives_again = _observe_evidence(spec, evidence_root)
    if files_again != files or archives_again != archives:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "evidence bytes changed during revalidation",
        )
    if index_document["files"] != files or index_document["archives"] != archives:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "committed admission index does not match the observed evidence",
        )
    receipt = verify_admission_receipt(
        receipt_document, index_document, spec, anchor, verified_locks
    )
    run_dir = Path(output_base) / spec.subject.experiment_id / spec.subject.run_id
    return AdmissionResult(
        disposition="REUSED_VERIFIED",
        receipt=receipt,
        admission_index_digest=content_digest(index_document),
        output_root=run_dir,
    )


def admit_synthetic(
    *,
    spec: TrustedAdmissionSpec,
    spec_expected_digest: str,
    evidence_root: Path,
    output_base: Path,
    verified_locks: Mapping[str, str],
) -> AdmissionResult:
    """Admit the synthetic evidence once, or fully reverify an existing result."""

    anchor = _preflight(spec, spec_expected_digest, verified_locks)
    root, base = require_disjoint_admission_roots(
        evidence_root, output_base, repository_root()
    )
    run_dir = base / spec.subject.experiment_id / spec.subject.run_id
    if run_dir.is_symlink():
        raise BenchError(
            BM_UNSAFE_INPUT, "admission destination must not be a symlink"
        )
    if run_dir.exists():
        return _revalidate(spec, anchor, root, base, verified_locks)

    files, archives = _observe_evidence(spec, root)
    _validate_dependencies(spec, root, verified_locks)
    files_again, archives_again = _observe_evidence(spec, root)
    if files_again != files or archives_again != archives:
        raise BenchError(
            BM_UNSAFE_INPUT, "evidence bytes changed during admission"
        )

    index_document = _build_index(spec, anchor, files, archives)
    receipt_document = build_admission_receipt(
        index_document, spec, anchor, verified_locks
    )
    receipt = verify_admission_receipt(
        receipt_document, index_document, spec, anchor, verified_locks
    )
    published = publish_admission(
        base,
        spec.subject.experiment_id,
        spec.subject.run_id,
        index_document,
        receipt_document,
    )
    return AdmissionResult(
        disposition="ADMITTED_SYNTHETIC",
        receipt=receipt,
        admission_index_digest=content_digest(index_document),
        output_root=published,
    )


def reverify_admission(
    *,
    spec: TrustedAdmissionSpec,
    spec_expected_digest: str,
    evidence_root: Path,
    output_base: Path,
    verified_locks: Mapping[str, str],
) -> AdmissionResult:
    """Fully revalidate a previously committed synthetic admission root."""

    anchor = _preflight(spec, spec_expected_digest, verified_locks)
    root, base = require_disjoint_admission_roots(
        evidence_root, output_base, repository_root()
    )
    return _revalidate(spec, anchor, root, base, verified_locks)


__all__ = [
    "AdmissionResult",
    "admit_synthetic",
    "reverify_admission",
]
