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
from dataclasses import dataclass, field
from fractions import Fraction
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
    row_id = _validate_row_id_slug(record["row_id"], "row_id")
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
    # A caller-supplied row set, a reviewer *label* and a self-consistent digest are
    # never sufficient. Only an independently recomputed comparison bound to an
    # externally approved mapping may open Gate D (see
    # ``open_verified_historical_parity``). This assessment therefore never returns
    # PASS.
    reasons.append("parity-requires-independently-recomputed-approved-mapping")
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
    elif study_id == STUDY_RETAINED_KEY and not policy_inputs_available:
        overall = "EVIDENCE_UNAVAILABLE"
        reasons.append("authentic-policy-inputs-unavailable")
    else:
        overall = "COMPARISON_COMPUTED_PENDING_REVIEW"
    if reviewer_approval_id is None:
        reasons.append("independent-reviewer-approval-missing")

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
    "PARITY_APPROVAL_KIND",
    "PARITY_MAPPING_KIND",
    "PARITY_METRICS",
    "VerifiedHistoricalParity",
    "_open_fixture_historical_parity",
    "open_verified_historical_parity",
    "parity_approval_record_path",
    "require_verified_historical_parity",
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


# ---------------------------------------------------------------------------
# Independently recomputed, externally approved historical parity
# ---------------------------------------------------------------------------

PARITY_MAPPING_KIND = "official-historical-parity-mapping"
PARITY_APPROVAL_KIND = "official-historical-parity-approval"
PARITY_APPROVAL_SUFFIX = ".parity-approval.json"
MAX_PARITY_DOCUMENT_BYTES = 1_048_576

_MAPPING_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "study_id",
        "original_verifier_digest",
        "tolerance_identity",
        "archive_member_digests",
        "rows",
    }
)
_ROW_KEYS = frozenset({"row_id", "metric", "expected", "tolerance", "locator"})
_LOCATOR_KEYS = frozenset({"engine", "trial", "n", "class", "k", "regime"})
_APPROVAL_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "study_id",
        "approved_mapping_digest",
        "independent_review_id",
        "approved_at_utc",
    }
)

#: Frozen PR15D historical replay contract (literal, never derived from a mapping).
PARITY_ENGINES: tuple[str, ...] = ("quervant", "tantivy", "lucene")
PARITY_TRIALS: tuple[int, ...] = (1, 2, 3)
PARITY_N_VALUES: tuple[int, ...] = (10_000, 100_000)
PARITY_CLASSES: tuple[str, ...] = ("absent", "rare", "medium", "common")
PARITY_TOP_K: tuple[int, ...] = (10, 100)
PARITY_REGIMES: tuple[str, ...] = ("process_cold", "warm")
PARITY_REQUIRED_ROW_COUNT = (
    len(PARITY_ENGINES)
    * len(PARITY_TRIALS)
    * len(PARITY_N_VALUES)
    * len(PARITY_CLASSES)
    * len(PARITY_TOP_K)
    * len(PARITY_REGIMES)
    * 5
)
_REGIME_TOKENS: dict[str, str] = {"process_cold": "pc", "warm": "wm"}
_METRIC_TOKENS: dict[str, str] = {
    "lane-median-ns": "med",
    "lane-p95-ns": "p95",
    "lane-p99-ns": "p99",
    "total-hits": "hits",
    "doc-ids": "ids",
}
#: Exact archived member inventory required for a complete historical replay.
PARITY_REQUIRED_ARCHIVE_MEMBERS: tuple[str, ...] = tuple(
    sorted(
        [
            "run.json",
            *[
                f"trials/trial-{trial}/{engine}.json"
                for trial in PARITY_TRIALS
                for engine in PARITY_ENGINES
            ],
        ]
    )
)

#: Closed metric identities the independent comparator can recompute.
PARITY_METRICS: tuple[str, ...] = (
    "lane-median-ns",
    "lane-p95-ns",
    "lane-p99-ns",
    "total-hits",
    "doc-ids",
)
#: Metrics whose expected value is a list of document identifiers.
PARITY_LIST_METRICS: frozenset[str] = frozenset({"doc-ids"})

_CREATION_SENTINEL = object()


@dataclass(frozen=True)
class VerifiedHistoricalParity:
    """An immutable capability proving recomputed, externally approved parity."""

    study_id: str
    archive_inventory_digest: str
    original_verifier_digest: str
    mapping_digest: str
    rows_digest: str
    approved_tolerance_identity: str
    reviewer_record_digest: str
    assessment_digest: str
    scope: str
    fixture_only: bool
    _sentinel: object = field(default=None, repr=False, compare=False)
    _mapping_path: Path | None = field(default=None, repr=False, compare=False)
    _archive_root: Path | None = field(default=None, repr=False, compare=False)
    _approval_source_root: Path | None = field(default=None, repr=False, compare=False)
    _approval_source_identity: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._sentinel is not _CREATION_SENTINEL:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "VerifiedHistoricalParity may only be created by the verified factories",
                field_path="historical_parity",
            )
        for name in (
            "archive_inventory_digest",
            "original_verifier_digest",
            "mapping_digest",
            "rows_digest",
            "reviewer_record_digest",
            "assessment_digest",
        ):
            validate_digest(getattr(self, name), name)
        if self.scope != "historical_replay":
            raise _identity("the parity scope must be historical_replay", "scope")


def parity_row_id(
    engine: str, trial: int, n: int, class_name: str, k: int, regime: str, metric: str
) -> str:
    """Return the frozen deterministic row identity for one comparison cell."""

    return (
        f"{engine}-t{trial}-n{n}-{class_name}-k{k}-"
        f"{_REGIME_TOKENS[regime]}-{_METRIC_TOKENS[metric]}"
    )


def expected_cross_engine_parity_coordinates() -> tuple[tuple[Any, ...], ...]:
    """Return the exhaustive, lexicographically ordered parity coordinates.

    The order is ``(engine, trial, n, class, k, regime, metric)`` and the result has
    exactly ``PARITY_REQUIRED_ROW_COUNT`` entries. It never depends on a mapping or
    on archived results.
    """

    coordinates = [
        (engine, trial, n, class_name, k, regime, metric)
        for engine in PARITY_ENGINES
        for trial in PARITY_TRIALS
        for n in PARITY_N_VALUES
        for class_name in PARITY_CLASSES
        for k in PARITY_TOP_K
        for regime in PARITY_REGIMES
        for metric in PARITY_METRICS
    ]
    coordinates.sort()
    if len(coordinates) != PARITY_REQUIRED_ROW_COUNT:  # pragma: no cover - construction
        raise BenchError(
            BM_INTERNAL_ERROR, "the frozen parity coordinate set is not complete"
        )
    return tuple(coordinates)


def parity_approval_record_path(approval_source_root: Path, identity: str) -> Path:
    """Return the closed parity-approval record path."""

    return Path(approval_source_root) / (
        f"{validate_semantic_id(identity, 'approval_source_identity')}{PARITY_APPROVAL_SUFFIX}"
    )


def _read_parity_approval(*, approval_source_root: Path, identity: str) -> tuple[dict[str, Any], str]:
    from .authorization import _validate_approval_source_root
    from .protocols import _is_utc_timestamp, read_canonical_json

    path = parity_approval_record_path(approval_source_root, identity)
    if path.is_symlink() or not path.is_file():
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the independent parity approval record is unavailable",
            field_path="approval_source_identity",
        )
    document = read_canonical_json(path, max_bytes=MAX_PARITY_DOCUMENT_BYTES)
    record = require_closed(document, "parity-approval", _APPROVAL_KEYS)
    if record["kind"] != PARITY_APPROVAL_KIND:
        raise BenchError(BM_SCHEMA_INVALID, "the parity approval kind is not recognised")
    if require_uint(record["schema_version"], "schema_version") != 1:
        raise BenchError(BM_SCHEMA_INVALID, "the parity approval schema_version is not supported")
    validate_semantic_id(record["study_id"], "study_id")
    validate_digest(record["approved_mapping_digest"], "approved_mapping_digest")
    review = record["independent_review_id"]
    if not isinstance(review, str) or not review:
        raise BenchError(BM_SCHEMA_INVALID, "independent_review_id must be a non-empty string")
    validate_semantic_id(review, "independent_review_id")
    if not isinstance(record["approved_at_utc"], str) or not _is_utc_timestamp(
        record["approved_at_utc"]
    ):
        raise BenchError(BM_SCHEMA_INVALID, "approved_at_utc must be a UTC timestamp")
    del _validate_approval_source_root  # imported for its side-effect validation helper
    return dict(record), content_digest(dict(record))


def _validate_row_id_slug(value: object, field: str) -> str:
    """Validate the frozen row-id syntax (coordinate labels, not public IDs).

    The frozen ``engine-t{n}-n{N}-...`` form legitimately contains a ``t{n}``
    segment, which the generic public-identifier rule reserves for phase labels.
    Row ids are derived coordinate labels, so only the slug syntax and bounds are
    enforced here.
    """

    if not isinstance(value, str):
        raise BenchError(BM_SCHEMA_INVALID, f"{field} must be a string", field_path=field)
    if not 3 <= len(value) <= 64:
        raise _identity(f"{field} must be 3-64 characters", field)
    import re as _re

    if _re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value) is None:
        raise _identity(
            f"{field} must be a lower-case semantic slug (letters, digits, hyphens)", field
        )
    return value


def _require_int_in(value: object, field: str, allowed: Sequence[int]) -> int:
    if type(value) is not int or value not in allowed:
        raise _identity(f"{field} is not one of the frozen values", field)
    return int(value)


def _require_str_in(value: object, field: str, allowed: Sequence[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _identity(f"{field} is not one of the frozen values", field)
    return str(value)


def _validate_mapping(document: object) -> dict[str, Any]:
    """Validate the closed, complete six-dimensional equivalence mapping."""

    from .protocols import _decimal as _protocol_decimal

    mapping = require_closed(document, "parity-mapping", _MAPPING_KEYS)
    if mapping["kind"] != PARITY_MAPPING_KIND:
        raise BenchError(BM_SCHEMA_INVALID, "the parity mapping kind is not recognised")
    if require_uint(mapping["schema_version"], "schema_version") != 1:
        raise BenchError(BM_SCHEMA_INVALID, "the parity mapping schema_version is not supported")
    study_id = validate_semantic_id(mapping["study_id"], "study_id")
    if study_id != STUDY_CROSS_ENGINE:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "only the complete cross-engine PR15D matrix is supported; retained-key "
            "parity needs authentic T7/F2 policy inputs and a separately approved schema",
            field_path="study_id",
        )
    validate_digest(mapping["original_verifier_digest"], "original_verifier_digest")
    tolerance_identity = validate_semantic_id(mapping["tolerance_identity"], "tolerance_identity")
    members = mapping["archive_member_digests"]
    if not isinstance(members, Mapping) or not members:
        raise BenchError(BM_SCHEMA_INVALID, "archive_member_digests must be a non-empty object")
    declared: dict[str, str] = {}
    for name, digest in members.items():
        member = validate_relative_member(str(name))
        if member in declared:
            raise _identity("archive_member_digests repeats a member", "archive_member_digests")
        declared[member] = validate_digest(digest, f"archive_member_digests.{member}")
    if tuple(sorted(declared)) != PARITY_REQUIRED_ARCHIVE_MEMBERS:
        raise _identity(
            "the archive member set is not the exact required PR15D historical inventory",
            "archive_member_digests",
        )

    rows = mapping["rows"]
    if not isinstance(rows, list) or not rows:
        raise BenchError(BM_SCHEMA_INVALID, "the parity mapping must declare at least one row")
    required = expected_cross_engine_parity_coordinates()
    if len(rows) != len(required):
        raise _identity(
            f"the parity mapping must declare exactly {len(required)} rows", "rows"
        )
    normalized_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_coordinates: set[tuple[Any, ...]] = set()
    for index, raw in enumerate(rows):
        row = require_closed(raw, f"rows[{index}]", _ROW_KEYS)
        row_id = _validate_row_id_slug(row["row_id"], "row_id")
        if row_id in seen_ids:
            raise _identity("the parity mapping repeats a row id", "rows")
        seen_ids.add(row_id)
        metric = row["metric"]
        if not isinstance(metric, str) or metric not in PARITY_METRICS:
            raise _identity("the parity mapping uses an unsupported metric", "metric")
        locator = require_closed(row["locator"], f"rows[{index}].locator", _LOCATOR_KEYS)
        normalized_locator = {
            "engine": _require_str_in(locator["engine"], "engine", PARITY_ENGINES),
            "trial": _require_int_in(locator["trial"], "trial", PARITY_TRIALS),
            "n": _require_int_in(locator["n"], "n", PARITY_N_VALUES),
            "class": _require_str_in(locator["class"], "class", PARITY_CLASSES),
            "k": _require_int_in(locator["k"], "k", PARITY_TOP_K),
            "regime": _require_str_in(locator["regime"], "regime", PARITY_REGIMES),
        }
        coordinate = (
            normalized_locator["engine"],
            normalized_locator["trial"],
            normalized_locator["n"],
            normalized_locator["class"],
            normalized_locator["k"],
            normalized_locator["regime"],
            metric,
        )
        if coordinate in seen_coordinates:
            raise _identity(
                "the parity mapping repeats a (engine, trial, n, class, k, regime, metric) cell",
                "rows",
            )
        seen_coordinates.add(coordinate)
        expected_id = parity_row_id(
            normalized_locator["engine"],
            normalized_locator["trial"],
            normalized_locator["n"],
            normalized_locator["class"],
            normalized_locator["k"],
            normalized_locator["regime"],
            metric,
        )
        if row_id != expected_id:
            raise _identity(
                "the row id is not the frozen deterministic identity for its cell", "row_id"
            )
        if metric in PARITY_LIST_METRICS:
            expected_value = row["expected"]
            if not isinstance(expected_value, list) or any(
                not isinstance(item, str) for item in expected_value
            ):
                raise BenchError(BM_SCHEMA_INVALID, "doc-ids rows need a string array")
            identifiers = list(expected_value)
            for identifier in identifiers:
                if len(identifier) != 9 or not identifier.startswith("d") or not identifier[1:].isdigit():
                    raise _identity("doc-ids entries must be dNNNNNNNN identifiers", "expected")
            if identifiers != sorted(set(identifiers)):
                raise _identity("doc-ids entries must be ordered and unique", "expected")
            normalized_expected: Any = identifiers
        elif metric == "total-hits":
            if type(row["expected"]) is not int:
                raise BenchError(
                    BM_SCHEMA_INVALID, "total-hits must be a built-in integer", "expected"
                )
            if int(row["expected"]) < 0:
                raise _identity("total-hits must be nonnegative", "expected")
            normalized_expected = int(row["expected"])
        else:
            if type(row["expected"]) is not int:
                raise BenchError(
                    BM_SCHEMA_INVALID, "a duration metric must be a built-in integer", "expected"
                )
            if int(row["expected"]) <= 0:
                raise _identity("a duration metric must be positive", "expected")
            normalized_expected = int(row["expected"])
        normalized_rows.append(
            {
                "row_id": row_id,
                "metric": metric,
                "expected": normalized_expected,
                "tolerance": _protocol_decimal(row["tolerance"], "tolerance"),
                "locator": normalized_locator,
            }
        )
    observed_coordinates = tuple(
        (
            row["locator"]["engine"],
            row["locator"]["trial"],
            row["locator"]["n"],
            row["locator"]["class"],
            row["locator"]["k"],
            row["locator"]["regime"],
            row["metric"],
        )
        for row in normalized_rows
    )
    if observed_coordinates != required:
        raise _identity(
            "the parity rows are not the complete frozen matrix in the required order", "rows"
        )
    return {
        "kind": PARITY_MAPPING_KIND,
        "schema_version": 1,
        "study_id": study_id,
        "original_verifier_digest": mapping["original_verifier_digest"],
        "tolerance_identity": tolerance_identity,
        "archive_member_digests": declared,
        "rows": normalized_rows,
    }


def _references_lower_median(values: Sequence[int]) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def _references_percentile(values: Sequence[int], percentile: int) -> int:
    ordered = sorted(values)
    index = -(-(percentile * len(ordered)) // 100) - 1
    return ordered[index]


def _tolerance_fraction(raw: str) -> Fraction:
    whole, _, fraction = str(raw).partition(".")
    return Fraction(int(whole) * 1_000_000 + int(fraction), 1_000_000)


_PARITY_FIELD_TERM: dict[str, tuple[str, str]] = {
    "absent": ("key", "never"),
    "rare": ("key", "singleton"),
    "medium": ("group", "medium"),
    "common": ("key", "common"),
}


def _recompute_row(
    row: Mapping[str, Any],
    archive_root: Path,
    *,
    trial_cache: dict[str, Any] | None = None,
) -> Any:
    """Recompute one declared metric from the authentic archive bytes.

    The archived lane is validated semantically (id, regime, N, K, field and term)
    before any number is trusted, and every quantile is recomputed with the frozen
    PR15D nearest-rank indices for twenty samples (9 / 18 / 19).
    """

    from .protocols import read_canonical_json

    locator = row["locator"]
    relative = f"trials/trial-{locator['trial']}/{locator['engine']}.json"
    cache = trial_cache if trial_cache is not None else {}
    manifest = cache.get(relative)
    if manifest is None:
        manifest = read_canonical_json(archive_root / relative)
        cache[relative] = manifest
    lanes = manifest.get("lanes")
    if not isinstance(lanes, list):
        raise _identity("the archived trial manifest has no lane array", "lanes")
    expected_field, expected_term = _PARITY_FIELD_TERM[locator["class"]]
    expected_lane_id = (
        f"pr15d_v1/{locator['n']}/{locator['class']}/k{locator['k']}"
    )
    wanted = (
        locator["n"],
        locator["class"],
        locator["k"],
        locator["regime"],
    )
    matches = [
        lane
        for lane in lanes
        if (lane.get("n"), lane.get("class"), lane.get("k"), lane.get("regime")) == wanted
    ]
    if len(matches) != 1:
        raise _identity("the archived trial manifest lacks exactly one mapped lane", "lanes")
    lane = matches[0]
    if lane.get("id") != expected_lane_id:
        raise _identity("the archived lane id does not match its coordinates", "id")
    if lane.get("field") != expected_field or lane.get("term") != expected_term:
        raise _identity(
            "the archived lane field/term does not match its selectivity class", "field"
        )
    samples = lane.get("samples_ns")
    if not isinstance(samples, list) or len(samples) != 20:
        raise _identity("the archived lane does not hold twenty samples", "samples_ns")
    for sample in samples:
        if isinstance(sample, bool) or not isinstance(sample, int) or sample <= 0:
            raise _identity("the archived lane has a non-positive sample", "samples_ns")
    metric = row["metric"]
    if metric == "lane-median-ns":
        return _references_percentile(samples, 50)
    if metric == "lane-p95-ns":
        return _references_percentile(samples, 95)
    if metric == "lane-p99-ns":
        return _references_percentile(samples, 99)
    if metric == "total-hits":
        total = lane.get("total_hits")
        if type(total) is not int or total < 0:
            raise _identity("the archived lane total_hits is not a nonnegative integer", "total_hits")
        return total
    identifiers = lane.get("doc_ids")
    if not isinstance(identifiers, list) or any(not isinstance(item, str) for item in identifiers):
        raise _identity("the archived lane doc_ids is not a string array", "doc_ids")
    return list(identifiers)


def _compare_row(row: Mapping[str, Any], observed: Any) -> bool:
    expected = row["expected"]
    if row["metric"] in PARITY_LIST_METRICS:
        return list(observed) == list(expected)
    if isinstance(observed, bool) or not isinstance(observed, int):
        return False
    tolerance = _tolerance_fraction(row["tolerance"])
    if tolerance == 0:
        return observed == expected
    return abs(Fraction(observed - expected)) <= tolerance * Fraction(expected)


def _expected_answers(n: int, class_name: str, k: int) -> dict[str, Any]:
    """Closed-form PR15D answer set for the frozen corpus (independent of the archive)."""

    if class_name == "absent":
        identifiers: list[str] = []
    elif class_name == "rare":
        identifiers = ["d00000000"]
    elif class_name == "medium":
        identifiers = [f"d{index:08}" for index in range(0, n, 8)]
    else:
        identifiers = [f"d{index:08}" for index in range(2, n, 2)]
    return {"total_hits": len(identifiers), "doc_ids": identifiers[:k]}


def _recompute_rows(
    mapping: Mapping[str, Any], archive_root: Path
) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    trial_cache: dict[str, Any] = {}
    verified_answers: set[tuple[Any, ...]] = set()
    for row in mapping["rows"]:
        locator = row["locator"]
        answer_key = (locator["engine"], locator["trial"], locator["n"], locator["class"], locator["k"], locator["regime"])
        if row["metric"] in ("total-hits", "doc-ids") and answer_key not in verified_answers:
            expected = _expected_answers(locator["n"], locator["class"], locator["k"])
            hits_row = dict(row, metric="total-hits")
            if _recompute_row(hits_row, archive_root, trial_cache=trial_cache) != expected["total_hits"]:
                raise _identity(
                    "the archived total_hits differs from the independent corpus oracle",
                    row["row_id"],
                )
            ids_row = dict(row, metric="doc-ids")
            if _recompute_row(ids_row, archive_root, trial_cache=trial_cache) != expected["doc_ids"]:
                raise _identity(
                    "the archived doc_ids differ from the independent corpus oracle",
                    row["row_id"],
                )
            verified_answers.add(answer_key)
        observed = _recompute_row(row, archive_root, trial_cache=trial_cache)
        if not _compare_row(row, observed):
            raise _identity(
                f"historical comparison row {row['row_id']} is outside its approved tolerance",
                row["row_id"],
            )
        rows.append(
            {
                "row_id": row["row_id"],
                "metric": row["metric"],
                "observed": observed if not isinstance(observed, list) else list(observed),
                "expected": row["expected"]
                if not isinstance(row["expected"], list)
                else list(row["expected"]),
                "tolerance": row["tolerance"],
            }
        )
    return rows, content_digest(
        {"kind": "official-historical-rows", "schema_version": 1, "rows": rows}
    )


def _archive_inventory(mapping: Mapping[str, Any], archive_root: Path) -> str:
    records = audit_declared_archive(Path(archive_root), mapping["archive_member_digests"])
    return content_digest(
        {"kind": "official-declared-archive", "schema_version": 1, "members": records}
    )


def _verified_verifier_digest(study_id: str, mapping: Mapping[str, Any], repo_root: Path | None) -> str:
    relative = (
        "benchmarks/pr15d/harness/validate.py"
        if study_id == STUDY_CROSS_ENGINE
        else "benchmarks/pr15i_d3_c/verify.py"
    )
    root = Path(repo_root) if repo_root is not None else repository_root()
    observed, _length = sha256_regular_file(root, relative, max_bytes=MAX_LEGACY_FILE_BYTES)
    if observed != mapping["original_verifier_digest"]:
        raise _identity(
            "the historical original verifier differs from the approved mapping",
            "original_verifier_digest",
        )
    return observed


def open_verified_historical_parity(
    *,
    study_id: str,
    archive_root: Path,
    mapping_path: Path,
    independently_approved_mapping_digest: str,
    approval_source_root: Path,
    approval_source_identity: str,
    repo_root: Path | None = None,
) -> VerifiedHistoricalParity:
    """Create a parity capability by independently recomputing an approved mapping."""

    from .authorization import _validate_approval_source_root
    from .protocols import read_canonical_json

    approved = validate_digest(
        independently_approved_mapping_digest, "independently_approved_mapping_digest"
    )
    if study_id == STUDY_RETAINED_KEY:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "retained-key historical parity needs the authentic T7/F2 policy inputs and an "
            "approved nine-K mapping, which are not available",
            field_path="study_id",
        )
    if study_id != STUDY_CROSS_ENGINE:
        raise _identity("unknown official study", "study_id")
    root = require_safe_root(Path(archive_root))
    mapping_file = Path(mapping_path)
    source_root = _validate_approval_source_root(Path(approval_source_root), mapping_file)
    record, record_digest = _read_parity_approval(
        approval_source_root=source_root, identity=approval_source_identity
    )
    if record["study_id"] != study_id:
        raise _identity("the parity approval is for a different study", "study_id")
    if record["approved_mapping_digest"] != approved:
        raise _fail("the approval record does not approve the supplied mapping digest", "approved")
    mapping = _validate_mapping(read_canonical_json(mapping_file))
    mapping_digest = content_digest(mapping)
    if mapping_digest != approved or mapping["study_id"] != study_id:
        raise _identity(
            "the mapping does not match the independently approved digest", "approved"
        )
    verifier_digest = _verified_verifier_digest(study_id, mapping, repo_root)
    inventory_digest = _archive_inventory(mapping, root)
    rows, rows_digest = _recompute_rows(mapping, root)
    assessment = {
        "kind": "official-historical-parity",
        "schema_version": 1,
        "evidence_origin": "real",
        "qualification_scope": "historical_replay",
        "study_id": study_id,
        "status": "PASS",
        "rows": [
            {
                "row_id": "cross-engine-complete-matrix",
                "legacy_source_identity": verifier_digest,
                "legacy_verifier_version": mapping["tolerance_identity"],
                "original_result": f"{len(mapping['rows'])} approved rows",
                "comparison_scope": "independently-recomputed-six-dimensional-matrix",
                "expected_equivalence": "EXACT_OR_APPROVED_TOLERANCE",
                "computed_comparison": f"{len(rows)} rows recomputed",
                "approved_tolerance": mapping["tolerance_identity"],
                "reviewer_approval_id": record["independent_review_id"],
                "status": "PASS",
            },
            {
                "row_id": "cross-engine-archive-inventory",
                "legacy_source_identity": "declared-pr15d-archive",
                "legacy_verifier_version": "pr15d-validation-v1",
                "original_result": "archive members approved",
                "comparison_scope": "byte-identity",
                "expected_equivalence": "EXACT",
                "computed_comparison": inventory_digest,
                "approved_tolerance": "NONE",
                "reviewer_approval_id": record["independent_review_id"],
                "status": "PASS",
            },
        ],
        "authenticated_archives": [
            {
                "campaign": "cross-engine-archive",
                "archive_digest": inventory_digest,
                "member_count": len(mapping["archive_member_digests"]),
            }
        ],
        "policy_inputs_status": "NON_EQUIVALENT_CONTRACT",
        "reviewer_approval_id": record["independent_review_id"],
        "reasons": ["independently-recomputed-and-externally-approved"],
    }
    assessment_document = validate_parity_assessment(assessment)
    return VerifiedHistoricalParity(
        study_id=study_id,
        archive_inventory_digest=inventory_digest,
        original_verifier_digest=verifier_digest,
        mapping_digest=mapping_digest,
        rows_digest=rows_digest,
        approved_tolerance_identity=mapping["tolerance_identity"],
        reviewer_record_digest=record_digest,
        assessment_digest=content_digest(assessment_document),
        scope="historical_replay",
        fixture_only=False,
        _sentinel=_CREATION_SENTINEL,
        _mapping_path=mapping_file.resolve(),
        _archive_root=root.resolve(),
        _approval_source_root=source_root,
        _approval_source_identity=approval_source_identity,
    )


def _open_fixture_historical_parity(
    *, study_id: str, fixture_only: bool = True
) -> VerifiedHistoricalParity:
    """Test-only parity capability; never authorizes production Gate D."""

    digest = "sha256:" + "f" * 64
    assessment = {
        "kind": "official-historical-parity",
        "schema_version": 1,
        "evidence_origin": "real",
        "qualification_scope": "historical_replay",
        "study_id": study_id,
        "status": "COMPARISON_COMPUTED_PENDING_REVIEW",
        "rows": [
            {
                "row_id": "fixture-row",
                "legacy_source_identity": "fixture",
                "legacy_verifier_version": "fixture",
                "original_result": "fixture",
                "comparison_scope": "fixture",
                "expected_equivalence": "fixture",
                "computed_comparison": "fixture",
                "approved_tolerance": None,
                "reviewer_approval_id": None,
                "status": "COMPARISON_COMPUTED_PENDING_REVIEW",
            }
        ],
        "authenticated_archives": [],
        "policy_inputs_status": "BLOCKED",
        "reviewer_approval_id": None,
        "reasons": ["fixture-only"],
    }
    return VerifiedHistoricalParity(
        study_id=study_id,
        archive_inventory_digest=digest,
        original_verifier_digest=digest,
        mapping_digest=digest,
        rows_digest=digest,
        approved_tolerance_identity="fixture-tolerance",
        reviewer_record_digest=digest,
        assessment_digest=content_digest(assessment),
        scope="historical_replay",
        fixture_only=fixture_only,
        _sentinel=_CREATION_SENTINEL,
        _mapping_path=None,
        _archive_root=None,
        _approval_source_root=None,
        _approval_source_identity=None,
    )


def require_verified_historical_parity(
    parity: object, *, study_id: str, for_production: bool = True
) -> VerifiedHistoricalParity:
    """Revalidate a parity capability; a caller-created record authorizes nothing."""

    if not isinstance(parity, VerifiedHistoricalParity):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "a VerifiedHistoricalParity is required; caller rows are not parity evidence",
            field_path="historical_parity",
        )
    if parity.study_id != study_id:
        raise _identity("the parity record is for a different study", "study_id")
    if parity.fixture_only:
        if for_production:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "a fixture-only parity record can never open production Gate D",
                field_path="historical_parity",
            )
        return parity
    if parity._mapping_path is None or parity._archive_root is None:  # noqa: SLF001
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the parity record has no revalidatable mapping/archive identity",
            field_path="historical_parity",
        )
    from .protocols import read_canonical_json

    record, record_digest = _read_parity_approval(
        approval_source_root=Path(parity._approval_source_root),  # noqa: SLF001
        identity=str(parity._approval_source_identity),  # noqa: SLF001
    )
    if record_digest != parity.reviewer_record_digest:
        raise _identity("the parity approval record changed after review", "reviewer_record_digest")
    mapping = _validate_mapping(read_canonical_json(Path(parity._mapping_path)))  # noqa: SLF001
    if content_digest(mapping) != parity.mapping_digest:
        raise _identity("the approved parity mapping changed after review", "mapping_digest")
    if record["approved_mapping_digest"] != parity.mapping_digest:
        raise _identity("the approval record no longer approves the mapping", "mapping_digest")
    verifier_digest = _verified_verifier_digest(study_id, mapping, None)
    if verifier_digest != parity.original_verifier_digest:
        raise _identity("the historical verifier identity changed", "original_verifier_digest")
    inventory_digest = _archive_inventory(mapping, Path(parity._archive_root))  # noqa: SLF001
    if inventory_digest != parity.archive_inventory_digest:
        raise _identity("the authentic archive changed after review", "archive_inventory_digest")
    _rows, rows_digest = _recompute_rows(mapping, Path(parity._archive_root))  # noqa: SLF001
    if rows_digest != parity.rows_digest:
        raise _identity("the recomputed comparison changed after review", "rows_digest")
    return parity
