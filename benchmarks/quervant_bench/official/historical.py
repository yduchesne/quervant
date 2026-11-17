"""Read-only historical parity assessment and legacy byte-identity checks.

Nothing in this module writes, moves, extracts or deletes historical evidence. The
legacy series are treated as authentic operator-owned archives: their bytes are
hashed, their archives are audited with the bounded streaming inspector, and a
parity row only passes when an independent reviewer has approved the mapping and
the comparison actually ran.

A missing archive, an unauthenticated mapping or a genuinely non-equivalent
numeric contract is reported as ``EVIDENCE_UNAVAILABLE``/``BLOCKED``/
``NON_EQUIVALENT_CONTRACT`` — never as PASS.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config.codec import content_digest
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id
from ..evidence.archives import ArchiveLimits, inspect_tar_gz
from ..evidence.hashing import sha256_regular_file
from ..evidence.paths import require_safe_root, validate_relative_member
from ..evidence.provenance import repository_root
from ..qualification.contracts import bound_payload, require_closed, require_uint
from .contracts import (
    PARITY_STATUSES,
    require_historical_scope,
)
from .protocols import (
    D3C_CAMPAIGN_NAMES,
    D3C_CONTROL_NAME,
    STUDY_CROSS_ENGINE,
    STUDY_RETAINED_KEY,
)

PARITY_KIND = "official-historical-parity"
LEGACY_MANIFEST_PATH = "docs/pr-artifacts/bm-09/legacy-source-manifest.json"
MAX_LEGACY_FILE_BYTES = 64 * 1024 * 1024

#: Frozen legacy source paths whose bytes must never change.
FROZEN_LEGACY_PATHS: tuple[str, ...] = (
    "benchmarks/pr15d/harness/run.py",
    "benchmarks/pr15d/harness/validate.py",
    "benchmarks/pr15d/harness/aggregate.py",
    "benchmarks/pr15d/harness/smoke.py",
    "benchmarks/pr15d/corpus/generate.py",
    "benchmarks/pr15d/corpus/oracle.py",
    "benchmarks/pr15d/spec/pr15d_v1.json",
    "benchmarks/pr15d/spec/pr15d_v1.md",
    "benchmarks/pr15d/adapters/quervant/Cargo.toml",
    "benchmarks/pr15d/adapters/quervant/Cargo.lock",
    "benchmarks/pr15d/adapters/quervant/src/main.rs",
    "benchmarks/pr15d/adapters/tantivy/Cargo.toml",
    "benchmarks/pr15d/adapters/tantivy/Cargo.lock",
    "benchmarks/pr15d/adapters/tantivy/src/main.rs",
    "benchmarks/pr15d/adapters/lucene/build.gradle",
    "benchmarks/pr15d/adapters/lucene/settings.gradle",
    "benchmarks/pr15d/adapters/lucene/A1-CHECKSUMS.sha256",
    "benchmarks/pr15d/adapters/lucene/src/main/java/org/quervant/bench/Adapter.java",
    "benchmarks/pr15i_d3_c/run.py",
    "benchmarks/pr15i_d3_c/verify.py",
    "benchmarks/pr15i_d3_c/protocol_v3r3.json",
    "benchmarks/pr15i_d3_c/tooling_manifest.json",
    "benchmarks/pr15i_d3_c/analysis_v3.py",
    "benchmarks/pr15i_d3_c/policy.py",
    "benchmarks/pr15i_d3_c_t7/analysis.py",
    "benchmarks/pr15i_d3_c_t7/freeze.py",
    "benchmarks/pr15i_d3_c_t7/policy.py",
    "benchmarks/pr15i_d3_c_t7/verify_derived.py",
    "benchmarks/pr15i_d3_c_t7_f2/verify_policy.py",
    "benchmarks/pr15i_d3_c_t7_f2/admission.py",
    "benchmarks/pr15i_d3_c_t7_f2/acceptance_gate.py",
    "benchmarks/pr15i_d3_c_t7_f2/constants.py",
)

RETAINED_KEY_ARCHIVE_DIR = "pr15i-d3-c-v3r3"
RETAINED_KEY_ARCHIVES: tuple[str, ...] = (
    D3C_CONTROL_NAME,
    *D3C_CAMPAIGN_NAMES,
)

_PARITY_ROW_KEYS = frozenset(
    {
        "row_id",
        "legacy_source_identity",
        "legacy_verifier_version",
        "original_result",
        "comparison_scope",
        "expected_equivalence",
        "computed_comparison",
        "approved_tolerance",
        "reviewer_approval_id",
        "status",
    }
)
_PARITY_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "study_id",
        "status",
        "rows",
        "authenticated_archives",
        "policy_inputs_status",
        "reviewer_approval_id",
        "reasons",
    }
)


def _identity(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


# ---------------------------------------------------------------------------
# Legacy byte identity
# ---------------------------------------------------------------------------


def legacy_source_hashes(repo_root: Path | None = None) -> dict[str, str]:
    """Return the SHA-256 of every frozen legacy source file."""

    root = Path(repo_root) if repo_root is not None else repository_root()
    safe_root = require_safe_root(root)
    hashes: dict[str, str] = {}
    for relative in FROZEN_LEGACY_PATHS:
        member = validate_relative_member(relative)
        digest, _length = sha256_regular_file(
            safe_root, member, max_bytes=MAX_LEGACY_FILE_BYTES
        )
        hashes[relative] = digest
    return hashes


def build_legacy_manifest(repo_root: Path | None = None) -> dict[str, Any]:
    """Build the checked-in legacy source manifest document (candidate form)."""

    return {
        "kind": "official-legacy-source-manifest",
        "schema_version": 1,
        "files": [
            {"path": path, "digest": digest}
            for path, digest in sorted(legacy_source_hashes(repo_root).items())
        ],
    }


def verify_legacy_sources_unchanged(
    manifest: Mapping[str, Any], repo_root: Path | None = None
) -> str:
    """Require every frozen legacy source byte to match the checked-in manifest."""

    document = require_closed(
        manifest, "legacy-manifest", frozenset({"kind", "schema_version", "files"})
    )
    if document["kind"] != "official-legacy-source-manifest":
        raise BenchError(BM_SCHEMA_INVALID, "legacy manifest kind is not frozen")
    files = document["files"]
    if not isinstance(files, list) or not files:
        raise BenchError(BM_SCHEMA_INVALID, "legacy manifest must list its files")
    declared: dict[str, str] = {}
    for index, entry in enumerate(files):
        record = require_closed(entry, f"files[{index}]", frozenset({"path", "digest"}))
        path = validate_relative_member(record["path"])
        if path in declared:
            raise _identity("the legacy manifest repeats a path", "files")
        declared[path] = validate_digest(record["digest"], f"files[{index}].digest")
    if tuple(sorted(declared)) != tuple(sorted(FROZEN_LEGACY_PATHS)):
        raise _identity("the legacy manifest path set is not the frozen set", "files")
    observed = legacy_source_hashes(repo_root)
    for path in sorted(declared):
        if observed[path] != declared[path]:
            raise _identity(
                "a frozen legacy source file changed and must be restored byte-identically",
                path,
            )
    return content_digest(dict(document))


# ---------------------------------------------------------------------------
# Archive inspection (read-only, bounded)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArchiveAudit:
    """The authenticated identity of one historical archive."""

    campaign: str
    archive_digest: str
    member_count: int
    manifest_protocol_digest: str | None
    sidecar_digest: str | None


def _read_sidecar(root: Path, relative: str) -> tuple[dict[str, Any], str]:
    from ..evidence.paths import open_regular_beneath

    handle = open_regular_beneath(root, relative)
    with handle:
        payload = handle.read(4 * 1024 * 1024)
    from ..config.codec import decode_text, loads_json

    document = loads_json(decode_text(payload))
    if not isinstance(document, Mapping):
        raise BenchError(BM_SCHEMA_INVALID, "the archive sidecar must be a JSON object")
    return dict(document), content_digest(dict(document))


def audit_retained_key_archive(
    archive_root: Path,
    campaign: str,
    *,
    limits: ArchiveLimits | None = None,
) -> ArchiveAudit:
    """Audit one authentic D3-C archive and its sidecar without extracting it."""

    if campaign not in RETAINED_KEY_ARCHIVES:
        raise _identity("unknown retained-key campaign archive", "campaign")
    root = require_safe_root(archive_root)
    archive_name = validate_relative_member(f"{campaign}.tar.gz")
    sidecar_name = archive_name + ".sha256"
    for name in (archive_name, sidecar_name):
        candidate = root / name
        if candidate.is_symlink() or not candidate.is_file():
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                "an authentic historical archive or its sidecar is unavailable",
                reference=name,
            )
    members = inspect_tar_gz(root, archive_name, limits or ArchiveLimits())
    sidecar, sidecar_digest = _read_sidecar(root, sidecar_name)
    if sidecar.get("schema") != "pr15i-d3c-archive-v1":
        raise BenchError(BM_SCHEMA_INVALID, "the archive sidecar schema is not the frozen schema")
    if sidecar.get("campaign") != campaign:
        raise _identity("the archive sidecar names a different campaign", "campaign")
    declared = sidecar.get("members")
    if not isinstance(declared, Mapping):
        raise BenchError(BM_SCHEMA_INVALID, "the archive sidecar must declare its members")
    observed = {member.name: member for member in members}
    if set(observed) != set(declared):
        raise _identity("the archive member set differs from the sidecar", "members")
    for name, digest in declared.items():
        expected = "sha256:" + str(digest)
        if observed[name].digest != expected:
            raise _identity("an archive member digest differs from the sidecar", name)
    if require_uint(sidecar.get("member_count"), "member_count") != len(members):
        raise _identity("the archive member count differs from the sidecar", "member_count")
    archive_digest, _length = sha256_regular_file(
        root, archive_name, max_bytes=4 * 1024 * 1024 * 1024
    )
    if "sha256:" + str(sidecar.get("archive_sha256")) != archive_digest:
        raise _identity("the archive digest differs from the sidecar", "archive_sha256")
    manifest_protocol: str | None = None
    manifest_member = observed.get("manifest.json")
    if manifest_member is not None:
        manifest_protocol = _read_archive_manifest_protocol(root, archive_name)
    return ArchiveAudit(
        campaign=campaign,
        archive_digest=archive_digest,
        member_count=len(members),
        manifest_protocol_digest=manifest_protocol,
        sidecar_digest=sidecar_digest,
    )


def _read_archive_manifest_protocol(root: Path, archive_name: str) -> str | None:
    """Stream one archive member and return its recorded protocol digest."""

    import tarfile

    from ..evidence.paths import open_regular_beneath

    handle = open_regular_beneath(root, archive_name)
    with handle:
        with tarfile.open(fileobj=handle, mode="r:gz") as archive:
            for info in archive:
                if info.name != "manifest.json":
                    continue
                if not info.isfile() or info.size > 1024 * 1024:
                    return None
                extracted = archive.extractfile(info)
                if extracted is None:  # pragma: no cover - isfile() implies payload
                    return None
                with extracted:
                    payload = extracted.read(info.size + 1)
                from ..config.codec import decode_text, loads_json

                document = loads_json(decode_text(payload))
                if not isinstance(document, Mapping):
                    return None
                value = document.get("protocol_sha256")
                return str(value) if value is not None else None
    return None


def historical_archive_root(
    *, home: Path | None = None, campaign_dir: str = RETAINED_KEY_ARCHIVE_DIR
) -> Path:
    """Return the authentic D3-C evidence root beneath an operator ``HOME``."""

    base = Path(home) if home is not None else Path(os.path.expanduser("~"))
    return base / ".local" / "share" / "quervant" / "benchmark-evidence" / campaign_dir


# ---------------------------------------------------------------------------
# Parity assessment
# ---------------------------------------------------------------------------


def validate_parity_row(row: object) -> dict[str, Any]:
    """Validate one closed parity matrix row."""

    record = require_closed(row, "parity-row", _PARITY_ROW_KEYS)
    row_id = validate_semantic_id(record["row_id"], "row_id")
    for name in ("legacy_source_identity", "legacy_verifier_version", "comparison_scope", "expected_equivalence"):
        if not isinstance(record[name], str) or not record[name]:
            raise BenchError(BM_SCHEMA_INVALID, f"{name} must be a non-empty string")
    if record["status"] not in PARITY_STATUSES:
        raise _identity("parity row status is not frozen", "status")
    if record["status"] == "PASS":
        if not isinstance(record["reviewer_approval_id"], str) or not record["reviewer_approval_id"]:
            raise _identity("a passing parity row needs a reviewer approval id", "reviewer_approval_id")
        if record["approved_tolerance"] is None:
            raise _identity("a passing parity row needs an approved tolerance (or NONE)", "approved_tolerance")
    return dict(record)


def validate_parity_assessment(document: object) -> dict[str, Any]:
    """Validate the closed historical parity assessment record."""

    doc = require_closed(document, "historical-parity", _PARITY_KEYS)
    if doc["kind"] != PARITY_KIND:
        raise BenchError(BM_SCHEMA_INVALID, "historical parity kind is not frozen")
    if doc["schema_version"] != 1:
        raise BenchError(BM_SCHEMA_INVALID, "historical parity schema_version must be 1")
    require_historical_scope(doc)
    study_id = validate_semantic_id(doc["study_id"], "study_id")
    if doc["status"] not in PARITY_STATUSES:
        raise _identity("historical parity status is not frozen", "status")
    rows = doc["rows"]
    if not isinstance(rows, list) or not rows:
        raise BenchError(BM_SCHEMA_INVALID, "historical parity must hold at least one row")
    validated_rows = [validate_parity_row(row) for row in rows]
    ids = [row["row_id"] for row in validated_rows]
    if len(set(ids)) != len(ids):
        raise _identity("parity row ids must be unique", "rows")
    archives = doc["authenticated_archives"]
    if not isinstance(archives, list):
        raise BenchError(BM_SCHEMA_INVALID, "authenticated_archives must be an array")
    for index, entry in enumerate(archives):
        record = require_closed(entry, f"authenticated_archives[{index}]", frozenset({"campaign", "archive_digest", "member_count"}))
        validate_semantic_id(record["campaign"], "campaign")
        validate_digest(record["archive_digest"], "archive_digest")
        require_uint(record["member_count"], "member_count")
    if doc["policy_inputs_status"] not in PARITY_STATUSES:
        raise _identity("policy_inputs_status is not frozen", "policy_inputs_status")
    reasons = doc["reasons"]
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise BenchError(BM_SCHEMA_INVALID, "reasons must be a list of strings")
    reviewer = doc["reviewer_approval_id"]
    if reviewer is not None and (not isinstance(reviewer, str) or not reviewer):
        raise BenchError(BM_SCHEMA_INVALID, "reviewer_approval_id must be a string or null")
    if doc["status"] == "PASS":
        any_row_blocked = any(row["status"] != "PASS" for row in validated_rows)
        if any_row_blocked:
            raise _identity("a passing assessment cannot contain non-passing rows", "rows")
        if reviewer is None:
            raise _identity("a passing assessment needs an independent reviewer approval", "reviewer_approval_id")
        if study_id == STUDY_RETAINED_KEY and doc["policy_inputs_status"] != "PASS":
            raise _identity(
                "a retained-key parity pass needs authenticated policy inputs",
                "policy_inputs_status",
            )
        if study_id == STUDY_CROSS_ENGINE and doc["policy_inputs_status"] not in ("PASS", "NON_EQUIVALENT_CONTRACT"):
            raise _identity(
                "a cross-engine parity pass needs an approved policy mapping",
                "policy_inputs_status",
            )
    result = dict(doc)
    result["rows"] = validated_rows
    bound_payload(result, "historical-parity")
    return result


def assess_required_historical_parity(
    *,
    study_id: str,
    archive_root: Path | None = None,
    reviewer_approval_id: str | None = None,
    rows: Sequence[Mapping[str, Any]] = (),
    policy_inputs_available: bool = False,
    repo_root: Path | None = None,
    legacy_manifest: Mapping[str, Any] | None = None,
    cross_engine_expected: Mapping[str, str] | None = None,
    mapping_status: str | None = None,
) -> dict[str, Any]:
    """Assess historical parity read-only and never fabricate a pass.

    The outcome is ``PASS`` only when authenticated archives exist, every required
    row passed with an independent reviewer approval, and (for retained-key) the
    authentic T7/F2 policy inputs are present.
    """

    if study_id not in (STUDY_RETAINED_KEY, STUDY_CROSS_ENGINE):
        raise _identity("unknown official study", "study_id")
    reasons: list[str] = []
    archives: list[dict[str, Any]] = []
    if legacy_manifest is not None:
        verify_legacy_sources_unchanged(legacy_manifest, repo_root)
    else:
        reasons.append("checked-in-legacy-manifest-not-supplied")

    authenticated = True
    if study_id == STUDY_RETAINED_KEY:
        root = Path(archive_root) if archive_root is not None else historical_archive_root()
        if not root.is_dir():
            authenticated = False
            reasons.append("authentic-retained-key-archive-root-unavailable")
        else:
            for campaign in RETAINED_KEY_ARCHIVES:
                try:
                    audit = audit_retained_key_archive(root, campaign)
                except BenchError as error:
                    authenticated = False
                    reasons.append(f"archive-audit-failed:{campaign}:{error.code}")
                    continue
                archives.append(
                    {
                        "campaign": campaign,
                        "archive_digest": audit.archive_digest,
                        "member_count": audit.member_count,
                    }
                )
                if audit.manifest_protocol_digest is None:
                    authenticated = False
                    reasons.append(f"archive-manifest-protocol-missing:{campaign}")
    else:
        if archive_root is None or not Path(archive_root).is_dir() or not cross_engine_expected:
            authenticated = False
            reasons.append("authentic-cross-engine-archive-unavailable")
        else:
            try:
                records = audit_declared_archive(Path(archive_root), cross_engine_expected)
            except BenchError as error:
                authenticated = False
                reasons.append(f"archive-audit-failed:cross-engine:{error.code}")
            else:
                archives.append(
                    {
                        "campaign": "cross-engine-archive",
                        "archive_digest": content_digest(
                            {
                                "kind": "official-declared-archive",
                                "schema_version": 1,
                                "members": records,
                            }
                        ),
                        "member_count": len(records),
                    }
                )

    validated_rows = [validate_parity_row(row) for row in rows]
    statuses = [row["status"] for row in validated_rows]
    if any(status in ("FAILED",) for status in statuses):
        overall = "FAILED"
    elif any(status in ("NON_EQUIVALENT_CONTRACT",) for status in statuses):
        overall = "NON_EQUIVALENT_CONTRACT"
    elif not validated_rows:
        reasons.append("no-parity-rows-executed")
        overall = "BLOCKED"
    elif any(status in ("EVIDENCE_UNAVAILABLE",) for status in statuses) or not authenticated:
        overall = "EVIDENCE_UNAVAILABLE" if not authenticated else "BLOCKED"
    elif any(status != "PASS" for status in statuses):
        overall = "BLOCKED"
    elif reviewer_approval_id is None:
        overall = "BLOCKED"
        reasons.append("independent-reviewer-approval-missing")
    elif study_id == STUDY_RETAINED_KEY and not policy_inputs_available:
        overall = "EVIDENCE_UNAVAILABLE"
        reasons.append("authentic-policy-inputs-unavailable")
    else:
        overall = "PASS"

    if mapping_status is not None and mapping_status not in PARITY_STATUSES:
        raise _identity("mapping_status is not a frozen parity status", "mapping_status")
    if study_id == STUDY_RETAINED_KEY:
        # The retained-key family needs authentic T7/F2 policy inputs; a caller
        # assertion cannot substitute for them.
        policy_status = "PASS" if policy_inputs_available else "EVIDENCE_UNAVAILABLE"
    else:
        policy_status = mapping_status or "BLOCKED"
    document = {
        "kind": PARITY_KIND,
        "schema_version": 1,
        "evidence_origin": "real",
        "qualification_scope": "historical_replay",
        "study_id": study_id,
        "status": overall,
        "rows": validated_rows
        or [
            {
                "row_id": "required-parity-rows-missing",
                "legacy_source_identity": "unavailable",
                "legacy_verifier_version": "unavailable",
                "original_result": "unavailable",
                "comparison_scope": "unavailable",
                "expected_equivalence": "unavailable",
                "computed_comparison": "not-executed",
                "approved_tolerance": None,
                "reviewer_approval_id": None,
                "status": "EVIDENCE_UNAVAILABLE",
            }
        ],
        "authenticated_archives": archives,
        "policy_inputs_status": policy_status,
        "reviewer_approval_id": reviewer_approval_id,
        "reasons": sorted(set(reasons)),
    }
    return validate_parity_assessment(document)


def audit_declared_archive(
    root: Path, expected: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Authenticate an archive directory against reviewer-approved member digests.

    Every declared member must exist as a regular file with the approved digest and
    the directory must not contain an unexpected member. Nothing is extracted,
    rewritten or deleted.
    """

    safe_root = require_safe_root(Path(root))
    if not isinstance(expected, Mapping) or not expected:
        raise BenchError(BM_SCHEMA_INVALID, "a declared archive needs approved member digests")
    declared: dict[str, str] = {}
    for name, digest in expected.items():
        member = validate_relative_member(str(name))
        if member in declared:
            raise _identity("the declared archive repeats a member", "members")
        declared[member] = validate_digest(digest, f"members.{member}")
    from .admission import walk_raw_members

    actual = walk_raw_members(safe_root)
    if sorted(actual) != sorted(declared):
        raise _identity(
            "the archive member set differs from the approved member set", "members"
        )
    records: list[dict[str, Any]] = []
    for member in sorted(declared):
        observed, length = sha256_regular_file(
            safe_root, member, max_bytes=MAX_LEGACY_FILE_BYTES
        )
        if observed != declared[member]:
            raise _identity("an archive member differs from its approved digest", member)
        records.append({"path": member, "digest": observed, "byte_length": length})
    return records


def require_parity_pass(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Require a passing historical parity assessment before Gate D."""

    validated = validate_parity_assessment(dict(document))
    if validated["status"] != "PASS":
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            f"historical parity is {validated['status']}; Gate D cannot pass",
            field_path="historical_parity_status",
        )
    return validated


def parity_digest(document: Mapping[str, Any]) -> str:
    """Return the canonical digest of a validated parity assessment."""

    return content_digest(validate_parity_assessment(dict(document)))


__all__ = [
    "ArchiveAudit",
    "FROZEN_LEGACY_PATHS",
    "LEGACY_MANIFEST_PATH",
    "PARITY_KIND",
    "RETAINED_KEY_ARCHIVES",
    "assess_required_historical_parity",
    "audit_declared_archive",
    "audit_retained_key_archive",
    "build_legacy_manifest",
    "historical_archive_root",
    "legacy_source_hashes",
    "parity_digest",
    "require_parity_pass",
    "validate_parity_assessment",
    "validate_parity_row",
    "verify_legacy_sources_unchanged",
]
