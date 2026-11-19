"""Bounded historical-input inventory and proportional comparison disclosure.

The historical contract is a *disclosure*, not an acceptance gate: authentic
evidence that is present may be re-analysed, authentic reported effects without
raw inputs may be shown as reported, and anything missing, invalid, unverified or
semantically incompatible is recorded with an explicit status. Nothing here can
mint a historical PASS, a measurement, or an independent approval, and nothing
here can block an independently verified current baseline.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..config.codec import content_digest
from ..config.errors import BM_EVIDENCE_UNAVAILABLE, BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError
from ..evidence.paths import open_regular_beneath, require_safe_root, validate_relative_member
from . import relative_effects
from .policy_inputs import HISTORICAL_ARCHIVE_DIGESTS

INVENTORY_KIND = "official-baseline-history-inputs"
INVENTORY_SCHEMA_VERSION = 1
REPORT_KIND = "official-baseline-history"
REPORT_SCHEMA_VERSION = 1
FAMILY_RETAINED = "retained-key"
FAMILY_CROSS_ENGINE = "cross-engine"
FAMILIES = (FAMILY_RETAINED, FAMILY_CROSS_ENGINE)
#: Every place a history input may come from, with its fixed owning reader.
INPUT_ROLES = {
    "retained-archive": FAMILY_RETAINED,
    "retained-micro": FAMILY_RETAINED,
    "retained-f1-receipt": FAMILY_RETAINED,
    "retained-t6-receipt": FAMILY_RETAINED,
    "pr15d-archive": FAMILY_CROSS_ENGINE,
    "pr15d-aggregate": FAMILY_CROSS_ENGINE,
    "retained-analysis": FAMILY_RETAINED,
    "retained-policy": FAMILY_RETAINED,
}
STATUS_FOUND = "FOUND"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_INVALID = "INVALID"
STATUS_UNVERIFIED = "UNVERIFIED"
STATUS_NOT_COMPARABLE = "NOT_COMPARABLE"
STATUSES = (
    STATUS_FOUND,
    STATUS_UNAVAILABLE,
    STATUS_INVALID,
    STATUS_UNVERIFIED,
    STATUS_NOT_COMPARABLE,
)
#: Roles whose identity is pinned by an independent frozen digest.
FROZEN_DIGEST_ROLES = frozenset({"retained-archive"})
#: Fixed supported historical source catalog: ``(role, identity) -> raw digest``.
#: A candidate may only restate these anchors; it cannot supply its own.
SUPPORTED_SOURCES: dict[tuple[str, str], str] = {
    ("retained-archive", "d3c-v3r3-base-aa-01"):
        "sha256:e02ff5661ecb12d76cddedfd701decdbc4004a7e6c16a40ae09a53733a409ba6",
    ("retained-archive", "d3c-v3r3-strategies-01"):
        "sha256:721e1f543e2a8f0b9b13e2894c22676e7e400ea2568e4a2de7976c28daa2f87e",
    ("retained-archive", "d3c-v3r3-strategies-02"):
        "sha256:72391496dd1d458ba39fb0e347f0446048878ae4180d4cb087f41e788efa3444",
    ("retained-f1-receipt", "38a937fdf0b09f1330f26423dabb311399c8a4cf"):
        "sha256:80f21e8fb7c9a76d466d749b0253f50bf8955112db0214386abbfcb9a9532ee1",
    ("retained-t6-receipt", "44ccd9e027071cf12777610abae5e6ab5f03177f"):
        "sha256:05c7a677fbb7e3e808efd098670e561cb9be41cc72af668572f21d23a7144e93",
    ("pr15d-archive", "20261031T005545Z-40a9c26a57aa23640904075e77be956ee52718bc"):
        "sha256:426dff2920b55ff63766da284421cf698f9950011da409b88a33be5d6d4e7bab",
    ("pr15d-aggregate", "20261031T005545Z-40a9c26a57aa23640904075e77be956ee52718bc"):
        "sha256:c9e8ed722aefc4fef43837a5511c2c88575287497b449f68f82f7ea0c251b257",
    ("retained-analysis", "a59fdfc0230aa15b71aaf11566960bc47f7c7723"):
        "sha256:2c3854e4ff02f5acc9d7837d0267ae40101180df01c7db088705451bc8df3065",
    ("retained-policy", "a59fdfc0230aa15b71aaf11566960bc47f7c7723"):
        "sha256:e68ce9298e3be05540f732d51408085fc0f742e5fed45db52a2e48454576be21",
}
INVENTORY_KEYS = frozenset({"kind", "schema_version", "candidates"})
CANDIDATE_KEYS = frozenset({"family", "input_role", "path", "source_identity", "expected_digest"})
REPORT_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "baseline_id",
        "study_id",
        "source_commit",
        "current_raw_digest",
        "entries",
    }
)
ENTRY_KEYS = frozenset(
    {"input_role", "source_identity", "input_digest", "status", "reason", "normalized_rows"}
)
MAX_INVENTORY_BYTES = 1_048_576
MAX_HISTORY_BYTES = 64 * 1024 * 1024


def _schema(message: str, field_path: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


def _identity(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _unsafe(message: str, field_path: str) -> BenchError:
    return BenchError(BM_UNSAFE_INPUT, message, field_path=field_path)


def raw_digest(path: Path) -> str:
    """Return the ``sha256:``-prefixed raw digest of one regular file."""

    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1_048_576)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_HISTORY_BYTES:
                raise _unsafe("the historical input exceeds its byte budget", "path")
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def validate_inventory(document: object) -> dict[str, Any]:
    """Validate the closed location inventory (a list of candidates, never a PASS list)."""

    if not isinstance(document, Mapping):
        raise _schema("the history inventory must be an object", "inventory")
    if set(document) != INVENTORY_KEYS:
        raise _schema("the history inventory has an unexpected shape", "inventory")
    if document["kind"] != INVENTORY_KIND:
        raise _schema("unexpected history inventory kind", "kind")
    if type(document["schema_version"]) is not int or document["schema_version"] != INVENTORY_SCHEMA_VERSION:
        raise _schema("unsupported history inventory version", "schema_version")
    candidates = document["candidates"]
    if not isinstance(candidates, list):
        raise _schema("history candidates must be a list", "candidates")
    seen: set[tuple[str, str, str]] = set()
    validated: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or set(candidate) != CANDIDATE_KEYS:
            raise _schema("a history candidate has an unexpected shape", "candidates")
        family = candidate["family"]
        role = candidate["input_role"]
        if family not in FAMILIES:
            raise _schema("unknown history family", "family")
        if role not in INPUT_ROLES:
            raise _schema("unknown history input role", "input_role")
        if INPUT_ROLES[role] != family:
            raise _identity("the input role belongs to another family", "input_role")
        path = candidate["path"]
        if not isinstance(path, str) or not path:
            raise _schema("a history candidate needs a path string", "path")
        identity = candidate["source_identity"]
        if not isinstance(identity, str) or not identity:
            raise _schema("a history candidate needs a source identity", "source_identity")
        digest = candidate["expected_digest"]
        if digest is not None:
            if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
                raise _schema("expected_digest must be a sha256: digest or null", "expected_digest")
        if role in FROZEN_DIGEST_ROLES and digest is None:
            raise _identity(
                "a frozen historical archive needs its independently known digest",
                "expected_digest",
            )
        key = (family, role, identity)
        if key in seen:
            raise _schema("duplicate history candidate identity", "candidates")
        seen.add(key)
        validated.append(dict(candidate))
    return {
        "kind": INVENTORY_KIND,
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "candidates": validated,
    }


def _frozen_digest_for(role: str, identity: str) -> str | None:
    if role == "retained-archive":
        return HISTORICAL_ARCHIVE_DIGESTS.get(identity)
    return SUPPORTED_SOURCES.get((role, identity))


def classify_candidate(provider_root: Path, candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return one history entry for a candidate, authenticating it where possible.

    Precedence: unsafe path, then absence, then an unreadable/symlinked/special
    target, then identity and digest authentication. The candidate's declared digest
    is only cross-checked against the fixed catalog; it is never a trust root.
    """

    role = candidate["input_role"]
    identity_text = candidate["source_identity"]
    declared = candidate["expected_digest"]
    entry = {
        "input_role": role,
        "source_identity": identity_text,
        "input_digest": None,
        "status": STATUS_UNAVAILABLE,
        "reason": "not-found",
        "normalized_rows": [],
    }
    try:
        member = validate_relative_member(candidate["path"])
    except BenchError:
        entry.update(status=STATUS_INVALID, reason="unsafe-path")
        return entry
    root = require_safe_root(Path(provider_root))
    path = root / member
    if not path.exists() and not path.is_symlink():
        return entry
    try:
        handle = open_regular_beneath(root, member)
    except BenchError as error:
        entry.update(status=STATUS_INVALID, reason=f"unsafe-read:{error.code}")
        return entry
    digest = hashlib.sha256()
    total = 0
    try:
        with handle:
            while True:
                chunk = handle.read(1_048_576)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_HISTORY_BYTES:
                    entry.update(status=STATUS_INVALID, reason="budget-exceeded")
                    return entry
                digest.update(chunk)
    except OSError:
        entry.update(status=STATUS_INVALID, reason="read-failed")
        return entry
    observed = "sha256:" + digest.hexdigest()
    entry["input_digest"] = observed
    frozen = _frozen_digest_for(str(role), str(identity_text))
    if frozen is None:
        # An unsupported identity cannot be promoted by a caller-supplied hash.
        entry.update(status=STATUS_UNVERIFIED, reason="unsupported-source-identity")
        return entry
    if declared is not None and declared != frozen:
        entry.update(status=STATUS_INVALID, reason="declared-digest-conflicts-with-independent-anchor")
        return entry
    if observed != frozen:
        entry.update(status=STATUS_INVALID, reason="digest-mismatch")
        return entry
    if role in ("pr15d-aggregate", "retained-analysis", "retained-policy"):
        # An explicit historical ratio/derived document may be shown as reported,
        # never as a recomputed comparison.
        entry.update(status=STATUS_FOUND, reason="as-reported-input")
        return entry
    entry.update(status=STATUS_FOUND, reason="authenticated")
    return entry


def build_entries(
    provider_root: Path, inventory: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Authenticate every inventory candidate under ``provider_root``."""

    validated = validate_inventory(inventory)
    root = require_safe_root(Path(provider_root))
    return [classify_candidate(root, candidate) for candidate in validated["candidates"]]


def report_payload(
    *,
    baseline_id: str,
    study_id: str,
    source_commit: str,
    current_raw_digest: str,
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the closed history disclosure document."""

    return {
        "kind": REPORT_KIND,
        "schema_version": REPORT_SCHEMA_VERSION,
        "baseline_id": baseline_id,
        "study_id": study_id,
        "source_commit": source_commit,
        "current_raw_digest": current_raw_digest,
        "entries": [validate_entry(entry) for entry in entries],
    }


def validate_entry(entry: object) -> dict[str, Any]:
    """Validate one history entry."""

    if not isinstance(entry, Mapping) or set(entry) != ENTRY_KEYS:
        raise _schema("a history entry has an unexpected shape", "entries")
    if entry["input_role"] not in INPUT_ROLES:
        raise _schema("unknown history input role", "input_role")
    status = entry["status"]
    if status not in STATUSES:
        raise _schema("unknown history status", "status")
    if not isinstance(entry["reason"], str) or not entry["reason"]:
        raise _schema("a history entry needs a reason", "reason")
    digest = entry["input_digest"]
    if digest is not None and not (isinstance(digest, str) and digest.startswith("sha256:")):
        raise _schema("input_digest must be a sha256: digest or null", "input_digest")
    if status == STATUS_FOUND and digest is None:
        raise _identity("a found input needs its observed digest", "input_digest")
    rows = entry["normalized_rows"]
    if not isinstance(rows, list):
        raise _schema("normalized rows must be a list", "normalized_rows")
    if status in (STATUS_INVALID, STATUS_UNAVAILABLE, STATUS_UNVERIFIED) and rows:
        raise _identity("an unusable input must not contribute normalized rows", "normalized_rows")
    for row in rows:
        relative_effects.validate_row(row)
    return dict(entry)


def validate_report(document: object) -> dict[str, Any]:
    """Validate a history disclosure document."""

    if not isinstance(document, Mapping):
        raise _schema("the history report must be an object", "report")
    if set(document) != REPORT_KEYS:
        raise _schema("the history report has an unexpected shape", "report")
    if document["kind"] != REPORT_KIND:
        raise _schema("unexpected history report kind", "kind")
    if type(document["schema_version"]) is not int or document["schema_version"] != REPORT_SCHEMA_VERSION:
        raise _schema("unsupported history report version", "schema_version")
    entries = [validate_entry(entry) for entry in document["entries"]]
    if len({(entry["input_role"], entry["source_identity"]) for entry in entries}) != len(entries):
        raise _schema("duplicate history entry identity", "entries")
    return {**dict(document), "entries": entries}


def open_verified_baseline_disclosures(
    *,
    operation_root: Path,
    baseline_id: str,
    study_id: str,
    source_commit: str,
    current_raw_digest: str,
) -> dict[str, Any]:
    """Reopen both baseline disclosures from the operation root and bind them.

    Returns the two observed payload digests plus the private paths. This proves
    only that the operation carries internally consistent, identity-bound
    disclosures; it grants no history PASS and no current-data authority.
    """

    root = require_safe_root(Path(operation_root))
    observed: dict[str, Any] = {}
    for name, kind, validator in (
        ("history-report.json", REPORT_KIND, validate_report),
        ("relative-effects.json", relative_effects.ROWS_KIND, relative_effects.validate_disclosure),
    ):
        path = root / name
        if path.is_symlink():
            raise _unsafe("a disclosure may not be a symlink", name)
        if not path.is_file():
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                "a baseline disclosure is unavailable",
                field_path=name,
            )
        if path.stat().st_size > MAX_HISTORY_BYTES:
            raise _unsafe("a baseline disclosure exceeds its byte budget", name)
        import json

        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise _schema("a baseline disclosure is not valid JSON", name) from error
        validated = validator(document)
        if validated["kind"] != kind:
            raise _schema("unexpected disclosure kind", name)
        for field, expected in (
            ("baseline_id", baseline_id),
            ("study_id", study_id),
            ("source_commit", source_commit),
            ("current_raw_digest", current_raw_digest),
        ):
            if validated[field] != expected:
                raise _identity("the disclosure is bound to another identity", field)
        observed[name] = {
            "digest": content_digest(validated),
            "path": path,
            "document": validated,
        }
    return {
        "history_report_digest": observed["history-report.json"]["digest"],
        "relative_effects_digest": observed["relative-effects.json"]["digest"],
        "history_report_path": observed["history-report.json"]["path"],
        "relative_effects_path": observed["relative-effects.json"]["path"],
        "statuses": sorted({entry["status"] for entry in observed["history-report.json"]["document"]["entries"]}),
    }


def comparable_pairs(
    entries: Iterable[Mapping[str, Any]]
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    """Return (historical, current) row pairs that may enter a proportional comparison."""

    pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for entry in entries:
        validated = validate_entry(entry)
        if validated["status"] != STATUS_FOUND:
            continue
        for row in validated["normalized_rows"]:
            pairs.append((validated, row))
    return pairs


__all__ = [
    "CANDIDATE_KEYS",
    "ENTRY_KEYS",
    "FAMILIES",
    "FAMILY_CROSS_ENGINE",
    "FAMILY_RETAINED",
    "FROZEN_DIGEST_ROLES",
    "INPUT_ROLES",
    "INVENTORY_KIND",
    "INVENTORY_SCHEMA_VERSION",
    "REPORT_KIND",
    "REPORT_SCHEMA_VERSION",
    "STATUSES",
    "SUPPORTED_SOURCES",
    "STATUS_FOUND",
    "STATUS_INVALID",
    "STATUS_UNAVAILABLE",
    "STATUS_NOT_COMPARABLE",
    "STATUS_UNVERIFIED",
    "build_entries",
    "classify_candidate",
    "comparable_pairs",
    "open_verified_baseline_disclosures",
    "raw_digest",
    "report_payload",
    "validate_entry",
    "validate_inventory",
    "validate_report",
]
