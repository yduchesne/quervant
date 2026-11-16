"""Strict, no-follow read of the independently pinned qualification profile.

The profile is a checked-in, versioned internal contract. Its canonical content
digest is compared with an anchor supplied by an independent authority; the file
can never supply its own trust anchor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config.codec import (
    canonical_document_bytes,
    content_digest,
    decode_text,
    loads_json,
)
from ..config.errors import BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from ..evidence.paths import (
    open_regular_beneath,
    require_safe_root,
    validate_relative_member,
)
from .contracts import MAX_DOCUMENT_BYTES, validate_profile
from .identity import require_anchor

PROFILE_FILE_NAME = "synthetic-framework.v1.json"


def default_profile_path() -> Path:
    """Return the checked-in profile path next to this module."""

    return Path(__file__).resolve().parent / "profiles" / PROFILE_FILE_NAME


def read_qualification_profile(
    path: Path, expected_profile_digest: str
) -> tuple[dict[str, Any], str]:
    """Read, validate and anchor one qualification profile document."""

    if not isinstance(path, Path):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "qualification_profile_path must be a Path",
            field_path="qualification_profile_path",
        )
    anchor = require_anchor(expected_profile_digest, "expected_profile_digest")
    parent = path.parent
    require_safe_root(parent)
    name = validate_relative_member(path.name)
    handle = open_regular_beneath(parent, name)
    with handle:
        payload = handle.read(MAX_DOCUMENT_BYTES + 1)
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "qualification profile exceeds the document budget",
            reference=name,
        )
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "qualification profile is not stored in canonical byte form",
            reference=name,
        )
    profile = validate_profile(document)
    digest = content_digest(profile)
    if digest != anchor:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "qualification profile digest does not match the pinned anchor",
            field_path="expected_profile_digest",
        )
    return profile, digest


__all__ = ["default_profile_path", "read_qualification_profile"]
