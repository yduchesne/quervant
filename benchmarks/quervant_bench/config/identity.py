"""Semantic identifiers, digests and content-identity helpers.

New public identifiers are PR-agnostic semantic slugs. Historical labels may
contain PR/phase tokens, but only in an explicitly named ``provenance`` map — never
in a new identifier, schema ``$id``, command or artifact name.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from .codec import content_digest
from .errors import BM_IDENTITY_INVALID, BenchError

SLUG_MIN_LENGTH = 3
SLUG_MAX_LENGTH = 64

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_PR_PHASE_RE = re.compile(
    r"(?:^|-)(?:pr\d+[a-z0-9]*|bm-?\d+|t\d+f?\d*)(?=-|$)"
)
_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

UINT64_MAX = 2**64 - 1


def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def is_semantic_slug(value: object) -> bool:
    """Return whether ``value`` is a syntactically valid semantic slug."""

    return (
        isinstance(value, str)
        and SLUG_MIN_LENGTH <= len(value) <= SLUG_MAX_LENGTH
        and _SLUG_RE.fullmatch(value) is not None
    )


def contains_pr_phase_token(value: str) -> bool:
    """Return whether a slug embeds a PR/phase label segment."""

    return _PR_PHASE_RE.search(value) is not None


def validate_semantic_id(value: object, field: str) -> str:
    """Validate a new public semantic identifier and return it unchanged."""

    if not isinstance(value, str):
        raise _fail(f"{field} must be a string", field)
    if not SLUG_MIN_LENGTH <= len(value) <= SLUG_MAX_LENGTH:
        raise _fail(
            f"{field} must be {SLUG_MIN_LENGTH}-{SLUG_MAX_LENGTH} characters",
            field,
        )
    if _SLUG_RE.fullmatch(value) is None:
        raise _fail(
            f"{field} must be a lower-case ASCII semantic slug "
            "(letters, digits and single hyphens)",
            field,
        )
    if contains_pr_phase_token(value):
        raise _fail(f"{field} must not embed a PR or phase identifier", field)
    return value


def validate_positive_int(value: object, field: str) -> int:
    """Validate a positive integer, rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"{field} must be an integer", field)
    if value < 1:
        raise _fail(f"{field} must be positive", field)
    return value


def validate_nonnegative_int(value: object, field: str) -> int:
    """Validate a non-negative integer, rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"{field} must be an integer", field)
    if value < 0:
        raise _fail(f"{field} must be non-negative", field)
    return value


def validate_uint64(value: object, field: str) -> int:
    """Validate an unsigned 64-bit integer seed, rejecting booleans and floats."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"{field} must be an integer seed", field)
    if value < 0 or value > UINT64_MAX:
        raise _fail(f"{field} must be in [0, {UINT64_MAX}]", field)
    return value


def is_canonical_uuid4(value: object) -> bool:
    """Return whether ``value`` is an exact lower-case canonical UUIDv4 string."""

    return isinstance(value, str) and _UUID4_RE.fullmatch(value) is not None


def normalize_uuid4(value: object, field: str = "run_id") -> str:
    """Return the canonical lower-case form of a UUIDv4, or raise."""

    if not isinstance(value, str):
        raise _fail(f"{field} must be a string", field)
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise _fail(f"{field} must be a UUID", field) from exc
    if parsed.version != 4:
        raise _fail(f"{field} must be a UUIDv4", field)
    canonical = str(parsed)
    if not is_canonical_uuid4(canonical):  # pragma: no cover - defensive
        raise _fail(f"{field} is not a canonical UUIDv4", field)
    return canonical


def validate_uuid4(value: object, field: str = "run_id") -> str:
    """Validate an exact canonical lower-case UUIDv4 string."""

    if not isinstance(value, str):
        raise _fail(f"{field} must be a string", field)
    normalize_uuid4(value, field)
    if not is_canonical_uuid4(value):
        raise _fail(f"{field} must be a lower-case canonical UUIDv4", field)
    return value


def validate_digest(value: object, field: str) -> str:
    """Validate a ``sha256:``-prefixed lower-case content digest."""

    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise _fail(f"{field} must be 'sha256:' followed by 64 lower-case hex digits", field)
    return value


def validate_source_commit(value: object, field: str = "source_commit") -> str:
    """Validate a 40-character lower-case git commit identity."""

    if not isinstance(value, str) or _SOURCE_COMMIT_RE.fullmatch(value) is None:
        raise _fail(f"{field} must be 40 lower-case hexadecimal characters", field)
    return value


def binding_digest(fields: dict[str, Any]) -> str:
    """Return the content digest of a canonical binding payload.

    Used for synthetic policy/analysis/validator bindings where no real accepted
    decision exists. It is an identity check only, never authenticity evidence.
    """

    return content_digest(fields)
