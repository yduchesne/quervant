"""Bounded, read-only historical retained-key evidence assessor.

The historical D3-C/T7/T7-F2 sources remain frozen read-only authorities. This
module never runs a historical controller, policy writer or timing command. It
only classifies the metadata preconditions under which any historical comparison
could be considered. Header-compatible metadata is **not** authentication: BM-07
has no approved full-archive verifier and must never return ``AUTHENTIC``.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import decode_text, loads_json
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_FILE_MISSING,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..evidence.hashing import sha256_regular_file
from ..evidence.paths import open_regular_beneath, require_safe_root

PARITY_EXACT = "EXACT"
PARITY_NUMERIC_TOLERANCE = "NUMERIC_WITH_APPROVED_TOLERANCE"
PARITY_SEMANTIC = "SEMANTIC"
PARITY_NON_EQUIVALENT = "NON_EQUIVALENT_CONTRACT"
PARITY_EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
PARITY_FAILED = "FAILED"

PARITY_CLASSES: tuple[str, ...] = (
    PARITY_EXACT,
    PARITY_NUMERIC_TOLERANCE,
    PARITY_SEMANTIC,
    PARITY_NON_EQUIVALENT,
    PARITY_EVIDENCE_UNAVAILABLE,
    PARITY_FAILED,
)

#: Reserved historical vocabulary for a future approved full-archive verifier.
#: BM-07 does not implement that verifier and must never return this value.
ARCHIVE_AUTHENTIC = "AUTHENTIC"
ARCHIVE_PRESENT_UNVERIFIED = "PRESENT_UNVERIFIED"
ARCHIVE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
ARCHIVE_FAILED_AUTHENTICATION = "FAILED_AUTHENTICATION"
_HEADER_COMPATIBLE = "HEADER_COMPATIBLE"

PARITY_NOT_EXECUTED = "NOT_EXECUTED"
LEGACY_PATHS_RETIRED = "NO"
HISTORICAL_ACCEPTANCE_GATE_BLOCKED = "BLOCKED"

#: Pinned by the frozen read-only D3-C verifier (``verify.py``). These literals
#: are copied here deliberately: importing a legacy runner is forbidden.
PINNED_PROTOCOL_SHA256 = (
    "c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c"
)
PINNED_BASE_SHA = "39dbd9f571a58bea8cc03d5a406533298e809bfe"
PINNED_EXPERIMENT_SHA = "3ad6c5184fbe9c011abb731415a007e3f19d21de"

REQUIRED_CONTROL_CAMPAIGN = "d3c-v3r3-base-aa-01"
REQUIRED_TREATMENT_CAMPAIGNS: tuple[str, ...] = (
    "d3c-v3r3-strategies-01",
    "d3c-v3r3-strategies-02",
)
REQUIRED_CAMPAIGNS: tuple[str, ...] = (
    REQUIRED_CONTROL_CAMPAIGN,
    *REQUIRED_TREATMENT_CAMPAIGNS,
)
REQUIRED_CAMPAIGN_FILES: tuple[str, ...] = (
    "manifest.json",
    "authorization.json",
)
MAX_MANIFEST_BYTES = 1_048_576
MAX_ARCHIVE_ENTRIES = 256

#: Reviewed H01–H08 equivalence decisions. The checked-in JSON ledger must match
#: these values exactly; they are not inferred from any new generic result.
HISTORICAL_CLASSES: Mapping[str, str] = {
    "H01": PARITY_SEMANTIC,
    "H02": PARITY_NON_EQUIVALENT,
    "H03": PARITY_SEMANTIC,
    "H04": PARITY_NON_EQUIVALENT,
    "H05": PARITY_NON_EQUIVALENT,
    "H06": PARITY_SEMANTIC,
    "H07": PARITY_SEMANTIC,
    "H08": PARITY_EVIDENCE_UNAVAILABLE,
}


def _unavailable(detail: str, *, protocol_digest: str | None) -> dict[str, Any]:
    return {
        "historical_archive": ARCHIVE_UNAVAILABLE,
        "historical_evidence_status": ARCHIVE_UNAVAILABLE,
        "historical_numeric_parity": PARITY_NOT_EXECUTED,
        "historical_decision_parity": PARITY_NOT_EXECUTED,
        "historical_acceptance_gate": HISTORICAL_ACCEPTANCE_GATE_BLOCKED,
        "historical_verifier": PARITY_NOT_EXECUTED,
        "legacy_paths_retired": LEGACY_PATHS_RETIRED,
        "protocol_sha256": protocol_digest,
        "detail": detail,
        "parity_classes": dict(HISTORICAL_CLASSES),
    }


def _present_unverified(
    detail: str, *, protocol_digest: str | None
) -> dict[str, Any]:
    result = _unavailable(detail, protocol_digest=protocol_digest)
    result["historical_archive"] = ARCHIVE_PRESENT_UNVERIFIED
    result["historical_evidence_status"] = ARCHIVE_PRESENT_UNVERIFIED
    return result


def _failed(detail: str, *, protocol_digest: str | None) -> dict[str, Any]:
    result = _unavailable(detail, protocol_digest=protocol_digest)
    result["historical_archive"] = ARCHIVE_FAILED_AUTHENTICATION
    result["historical_evidence_status"] = ARCHIVE_FAILED_AUTHENTICATION
    result["historical_verifier"] = PARITY_FAILED
    return result


def _protocol_digest(protocol_path: Path) -> str | None:
    """Return the pinned legacy protocol digest, or ``None`` if unavailable."""

    if not isinstance(protocol_path, Path):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "protocol_path must be a Path",
            field_path="protocol_path",
        )
    if not protocol_path.exists():
        return None
    if protocol_path.is_symlink() or not protocol_path.is_file():
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the historical protocol must be a regular file",
            field_path="protocol_path",
        )
    root = protocol_path.parent
    digest, _length = sha256_regular_file(
        root, protocol_path.name, max_bytes=MAX_MANIFEST_BYTES
    )
    return digest.removeprefix("sha256:")


def _audit_campaign(archive_root: Path, campaign: str) -> str:
    """Classify one campaign's metadata; never mint an authentication status."""

    directory = archive_root / campaign
    try:
        info = os.lstat(directory)
    except FileNotFoundError as exc:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the historical archive is missing a required campaign directory",
            reference=campaign,
        ) from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "a historical campaign entry is not a safe directory",
            reference=campaign,
        )
    documents: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_CAMPAIGN_FILES:
        relative = f"{campaign}/{name}"
        try:
            handle = open_regular_beneath(archive_root, relative)
        except BenchError as error:
            if error.code == BM_FILE_MISSING:
                raise BenchError(
                    BM_EVIDENCE_UNAVAILABLE,
                    "the historical archive is missing a required campaign file",
                    reference=relative,
                ) from error
            raise
        with handle:
            payload = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(payload) > MAX_MANIFEST_BYTES:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "a historical campaign document exceeds the audit budget",
                reference=relative,
            )
        try:
            document = loads_json(decode_text(payload))
        except BenchError:
            return ARCHIVE_FAILED_AUTHENTICATION
        if not isinstance(document, Mapping):
            return ARCHIVE_FAILED_AUTHENTICATION
        documents[name] = dict(document)
    manifest = documents["manifest.json"]
    authorization = documents["authorization.json"]
    if not _manifest_header_compatible(campaign, manifest):
        return ARCHIVE_FAILED_AUTHENTICATION
    if not _authorization_header_compatible(authorization):
        return ARCHIVE_FAILED_AUTHENTICATION
    return _HEADER_COMPATIBLE


def _manifest_header_compatible(campaign: str, manifest: Mapping[str, Any]) -> bool:
    """Check only the frozen manifest header literals; never authenticate."""

    if manifest.get("schema") != "pr15i-d3c-manifest-v1":
        return False
    if manifest.get("protocol_sha256") != PINNED_PROTOCOL_SHA256:
        return False
    if manifest.get("source_base_sha") != PINNED_BASE_SHA:
        return False
    if manifest.get("campaign") != campaign:
        return False
    if campaign == REQUIRED_CONTROL_CAMPAIGN:
        if manifest.get("kind") != "control":
            return False
        if manifest.get("source_experiment_sha") is not None:
            return False
    else:
        if manifest.get("kind") != "four_arm":
            return False
        if manifest.get("source_experiment_sha") != PINNED_EXPERIMENT_SHA:
            return False
    return True


def _authorization_header_compatible(authorization: Mapping[str, Any]) -> bool:
    """Check only the frozen authorization header; never validate a signature."""

    return (
        authorization.get("schema") == "pr15i-d3c-authorization-v1"
        and authorization.get("protocol_sha256") == PINNED_PROTOCOL_SHA256
        and (
            "rehearsal_only" not in authorization
            or type(authorization["rehearsal_only"]) is bool
        )
        and authorization.get("rehearsal_only", False) is False
    )


def assess_historical_evidence(
    *,
    archive_root: Path | None,
    protocol_path: Path,
) -> dict[str, Any]:
    """Return the reviewed historical status without executing any legacy code."""

    try:
        protocol_digest = _protocol_digest(protocol_path)
    except BenchError:
        raise
    if protocol_digest is None:
        return _unavailable(
            "the checked-in historical protocol is unavailable",
            protocol_digest=None,
        )
    if protocol_digest != PINNED_PROTOCOL_SHA256:
        return _failed(
            "the checked-in historical protocol digest differs from the pinned literal",
            protocol_digest=protocol_digest,
        )
    if archive_root is None:
        return _unavailable("no external historical archive was supplied", protocol_digest=protocol_digest)
    if not isinstance(archive_root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "archive_root must be a Path or None",
            field_path="archive_root",
        )
    if not archive_root.exists():
        return _unavailable("the external historical archive is absent", protocol_digest=protocol_digest)
    try:
        root = require_safe_root(archive_root)
    except BenchError as error:
        if error.code == BM_FILE_MISSING:
            return _unavailable(
                "the external historical archive is absent",
                protocol_digest=protocol_digest,
            )
        raise
    with os.scandir(root) as iterator:
        entries = [entry.name for entry in iterator]
    if not entries:
        return _unavailable(
            "the external historical archive is an empty stub",
            protocol_digest=protocol_digest,
        )
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the external historical archive exceeds the bounded audit budget",
            field_path="archive_root",
        )
    statuses: list[str] = []
    missing_detail: str | None = None
    for campaign in REQUIRED_CAMPAIGNS:
        try:
            statuses.append(_audit_campaign(root, campaign))
        except BenchError as error:
            if error.code == BM_EVIDENCE_UNAVAILABLE:
                missing_detail = missing_detail or error.message
                continue
            raise
    if ARCHIVE_FAILED_AUTHENTICATION in statuses:
        return _failed(
            "a required historical campaign has invalid metadata",
            protocol_digest=protocol_digest,
        )
    if missing_detail is not None:
        return _unavailable(missing_detail, protocol_digest=protocol_digest)
    if len(statuses) != len(REQUIRED_CAMPAIGNS) or any(
        status != _HEADER_COMPATIBLE for status in statuses
    ):
        raise BenchError(
            BM_UNSAFE_INPUT, "unrecognized historical audit state"
        )
    return _present_unverified(
        "historical headers compatible, full archive not authenticated",
        protocol_digest=protocol_digest,
    )


__all__ = [
    "ARCHIVE_AUTHENTIC",
    "ARCHIVE_FAILED_AUTHENTICATION",
    "ARCHIVE_PRESENT_UNVERIFIED",
    "ARCHIVE_UNAVAILABLE",
    "HISTORICAL_ACCEPTANCE_GATE_BLOCKED",
    "HISTORICAL_CLASSES",
    "LEGACY_PATHS_RETIRED",
    "PARITY_CLASSES",
    "PARITY_EXACT",
    "PARITY_EVIDENCE_UNAVAILABLE",
    "PARITY_FAILED",
    "PARITY_NON_EQUIVALENT",
    "PARITY_NOT_EXECUTED",
    "PARITY_NUMERIC_TOLERANCE",
    "PARITY_SEMANTIC",
    "PINNED_BASE_SHA",
    "PINNED_EXPERIMENT_SHA",
    "PINNED_PROTOCOL_SHA256",
    "REQUIRED_CAMPAIGNS",
    "assess_historical_evidence",
]
