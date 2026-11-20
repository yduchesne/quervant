"""Verified external G0 authorization boundary.

A plain :class:`official.protocols.OfficialFreeze` is *not* an authorization: it is
parsed data. Production work may only proceed from a
:class:`VerifiedOfficialAuthorization`, which is created solely by
:func:`open_verified_official_authorization` after it has (1) validated an
externally approved approval record, (2) re-read the candidate authorization through
the bounded canonical reader, (3) re-run :func:`official.protocols.verify_g0_authorization`
against an *independently supplied* digest and freshly observed identities, and
(4) cross-checked every digest.

Nothing here invents a signing authority, a public key or a network PKI. The
approval record is a closed, operator-supplied document in an approved external
location; an approval identifier alone is not a cryptographic attestation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import content_digest
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id, validate_source_commit, validate_uuid4
from ..evidence.paths import require_safe_root
from ..evidence.provenance import repository_root
from ..qualification.contracts import (
    document_digest,
    require_closed,
    require_uint,
)
from .protocols import (
    CURRENT_BASELINE_PROFILE,
    OBSERVED_IDENTITY_FIELDS,
    OfficialFreeze,
    _is_utc_timestamp,
    read_canonical_json,
    validate_authorization,
    validate_root_identity,
    verify_g0_authorization,
)
from .contracts import require_profile_version

APPROVAL_RECORD_KIND = "official-g0-approval-record"
APPROVAL_RECORD_SUFFIX = ".approval.json"
MAX_APPROVAL_RECORD_BYTES = 65_536

_APPROVAL_RECORD_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "study_id",
        "approved_authorization_digest",
        "independent_review_id",
        "approved_at_utc",
    }
)

_CREATION_SENTINEL = object()


def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


@dataclass(frozen=True)
class VerifiedOfficialAuthorization:
    """An immutable capability proving a verified external G0 authorization.

    ``fixture_only`` is ``True`` only for internal deterministic tests. No public
    option turns it off: production entry points reject it unconditionally.
    """

    freeze: OfficialFreeze
    approval_digest: str
    authorization_document_digest: str
    observed_identity_digest: str
    authorization_path: Path
    approval_source_identity: str
    fixture_only: bool
    _sentinel: object = field(default=None, repr=False, compare=False)
    _approval_source_root: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._sentinel is not _CREATION_SENTINEL:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "VerifiedOfficialAuthorization may only be created by the verified factories",
                field_path="authorization",
            )
        validate_digest(self.approval_digest, "approval_digest")
        validate_digest(self.authorization_document_digest, "authorization_document_digest")
        validate_digest(self.observed_identity_digest, "observed_identity_digest")
        if not isinstance(self.freeze, OfficialFreeze):
            raise BenchError(BM_UNSAFE_INPUT, "authorization.freeze must be an OfficialFreeze")
        if self.fixture_only is not True and self.fixture_only is not False:
            raise BenchError(BM_UNSAFE_INPUT, "authorization.fixture_only must be a boolean")
        if self.approval_digest != self.freeze.authorization_digest:
            raise _fail(
                "the approval digest does not equal the freeze authorization digest",
                "approval_digest",
            )

    @property
    def study_id(self) -> str:
        return self.freeze.study_id

    @property
    def run_id(self) -> str:
        return self.freeze.run_id


# ---------------------------------------------------------------------------
# Approval record (operator-supplied, externally approved)
# ---------------------------------------------------------------------------


def approval_record_path(approval_source_root: Path, approval_source_identity: str) -> Path:
    """Return the closed approval-record path for one approved control identity."""

    identity = validate_semantic_id(approval_source_identity, "approval_source_identity")
    return Path(approval_source_root) / f"{identity}{APPROVAL_RECORD_SUFFIX}"


def _validate_approval_source_root(approval_source_root: Path, authorization_path: Path) -> Path:
    root = require_safe_root(Path(approval_source_root))
    resolved = root.resolve()
    repository = repository_root().resolve()
    if resolved == repository or repository in resolved.parents:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the approval source must not be inside the repository",
            field_path="approval_source_root",
        )
    for forbidden in ("target", "benchmark-results"):
        candidate = (repository / forbidden).resolve()
        if resolved == candidate or candidate in resolved.parents:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "the approval source must not be a build/run/output directory",
                field_path="approval_source_root",
            )
    authorization_parent = Path(authorization_path).resolve().parent
    if resolved == authorization_parent or authorization_parent in resolved.parents:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the approval source must not be inside the candidate authorization directory",
            field_path="approval_source_root",
        )
    return resolved


def read_approval_record(
    *, approval_source_root: Path, approval_source_identity: str
) -> tuple[dict[str, Any], str]:
    """Read and validate one closed approval record (bounded, no links)."""

    path = approval_record_path(approval_source_root, approval_source_identity)
    if path.is_symlink() or not path.is_file():
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the independent approval record is unavailable",
            field_path="approval_source_identity",
        )
    document = read_canonical_json(path, max_bytes=MAX_APPROVAL_RECORD_BYTES)
    record = require_closed(document, "approval-record", _APPROVAL_RECORD_KEYS)
    if record["kind"] != APPROVAL_RECORD_KIND:
        raise BenchError(BM_SCHEMA_INVALID, "the approval record kind is not recognised")
    if require_uint(record["schema_version"], "schema_version") != 1:
        raise BenchError(BM_SCHEMA_INVALID, "the approval record schema_version is not supported")
    validate_semantic_id(record["study_id"], "study_id")
    validate_digest(record["approved_authorization_digest"], "approved_authorization_digest")
    review = record["independent_review_id"]
    if not isinstance(review, str) or not review:
        raise BenchError(BM_SCHEMA_INVALID, "independent_review_id must be a non-empty string")
    validate_semantic_id(review, "independent_review_id")
    approved_at = record["approved_at_utc"]
    if not isinstance(approved_at, str) or not _is_utc_timestamp(approved_at):
        raise BenchError(BM_SCHEMA_INVALID, "approved_at_utc must be a UTC timestamp")
    return dict(record), document_digest(record)


def _observed_identity_digest(observations: Mapping[str, Any], *, profile_version: int = 1) -> str:
    if not isinstance(observations, Mapping):
        raise BenchError(BM_UNSAFE_INPUT, "actual observations must be a mapping")
    version = require_profile_version(profile_version, "profile_version")
    if version == 2:
        keys = set(OBSERVED_IDENTITY_FIELDS) | {
            "output_root_identity", "acceptance_profile", "baseline_id",
            "preservation_root_identity", "runtime_freeze_digest",
        }
        if set(observations) != keys:
            raise BenchError(BM_SCHEMA_INVALID, "v2 observations must contain exactly twenty identities", field_path="observed")
        for name in OBSERVED_IDENTITY_FIELDS:
            if name == "source_commit":
                validate_source_commit(observations[name], name)
            else:
                validate_digest(observations[name], name)
        if type(observations["acceptance_profile"]) is not str or observations["acceptance_profile"] != CURRENT_BASELINE_PROFILE:
            raise _fail("the observed acceptance profile is not registered", "acceptance_profile")
        validate_uuid4(observations["baseline_id"], "baseline_id")
        for name in ("output_root_identity", "preservation_root_identity"):
            validate_root_identity(observations[name], name)
        if observations["runtime_freeze_digest"] is not None:
            validate_digest(observations["runtime_freeze_digest"], "runtime_freeze_digest")
        return content_digest({
            "kind": "official-g0-observed-identity", "schema_version": 2,
            "observations": dict(observations),
        })
    return content_digest(
        {
            "kind": "official-g0-observed-identity",
            "schema_version": 1,
            "observations": {str(key): str(observations[key]) for key in sorted(observations)},
        }
    )


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def open_verified_official_authorization(
    *,
    authorization_path: Path,
    independently_approved_digest: str,
    actual_observations: Mapping[str, Any],
    approval_source_identity: str,
    approval_source_root: Path,
) -> VerifiedOfficialAuthorization:
    """Create the only production authorization capability.

    A missing/unsafe approval source, a mismatched approved digest, changed
    authorization bytes or a mismatched observed identity all fail closed before any
    capability exists.
    """

    approved = validate_digest(independently_approved_digest, "independently_approved_digest")
    if not isinstance(actual_observations, Mapping):
        raise BenchError(BM_UNSAFE_INPUT, "actual_observations must be a mapping")
    path = Path(authorization_path)
    source_root = _validate_approval_source_root(Path(approval_source_root), path)
    record, record_digest = read_approval_record(
        approval_source_root=source_root,
        approval_source_identity=approval_source_identity,
    )
    if record["approved_authorization_digest"] != approved:
        raise _fail(
            "the approval record does not approve the supplied authorization digest",
            "independently_approved_digest",
        )
    missing = [name for name in OBSERVED_IDENTITY_FIELDS if name not in actual_observations]
    if missing:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            f"the caller did not observe {missing[0]} independently",
            field_path=missing[0],
        )
    if "output_root_identity" not in actual_observations:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the caller did not observe output_root_identity independently",
            field_path="output_root_identity",
        )
    candidate = validate_authorization(read_canonical_json(path))
    candidate_digest = document_digest(candidate)
    if candidate_digest != approved:
        raise _fail(
            "the authorization document does not match the approved digest",
            "independently_approved_digest",
        )
    freeze = verify_g0_authorization(path, approved, actual_observations)
    if record["study_id"] != freeze.study_id:
        raise _fail("the approval record is for a different study", "study_id")
    del record_digest
    return VerifiedOfficialAuthorization(
        freeze=freeze,
        approval_digest=approved,
        authorization_document_digest=candidate_digest,
        observed_identity_digest=_observed_identity_digest(actual_observations, profile_version=freeze.profile_version),
        authorization_path=path.resolve(),
        approval_source_identity=approval_source_identity,
        fixture_only=False,
        _sentinel=_CREATION_SENTINEL,
        _approval_source_root=source_root,
    )


def _open_fixture_authorization(freeze: OfficialFreeze) -> VerifiedOfficialAuthorization:
    """Test-only capability used by deterministic fixture graphs.

    It is categorically rejected by every production entry point
    (``for_production=True``), cannot publish and cannot issue official receipts.
    """

    if not isinstance(freeze, OfficialFreeze):
        raise BenchError(BM_UNSAFE_INPUT, "a fixture authorization needs an OfficialFreeze")
    return VerifiedOfficialAuthorization(
        freeze=freeze,
        approval_digest=freeze.authorization_digest,
        authorization_document_digest=freeze.authorization_digest,
        observed_identity_digest=content_digest(
            {"kind": "official-g0-observed-identity", "schema_version": 1, "fixture": True}
        ),
        authorization_path=Path("<fixture-authorization>"),
        approval_source_identity="fixture-approval",
        fixture_only=True,
        _sentinel=_CREATION_SENTINEL,
        _approval_source_root=None,
    )


# ---------------------------------------------------------------------------
# Boundary used by production entry points
# ---------------------------------------------------------------------------


def require_verified_official_authorization(
    authorization: object,
    *,
    study_id: str,
    for_production: bool = True,
    observed: Mapping[str, Any] | None = None,
) -> OfficialFreeze:
    """Revalidate a capability and return its freeze.

    Production callers must pass fresh ``observed`` identities: an already-open
    capability is never trusted on object identity alone, and a changed approval
    record, changed authorization bytes or stale observations all fail closed.
    """

    if not isinstance(authorization, VerifiedOfficialAuthorization):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "a VerifiedOfficialAuthorization is required; a parsed freeze is not an authorization",
            field_path="authorization",
        )
    if authorization.fixture_only:
        if for_production:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "a fixture-only authorization can never authorize official production work",
                field_path="authorization",
            )
        if authorization.freeze.study_id != study_id:
            raise _fail("the fixture authorization is for a different study", "study_id")
        return authorization.freeze
    if authorization._approval_source_root is None:  # noqa: SLF001 - creation guard
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the approval source root is unavailable for revalidation",
            field_path="approval_source_root",
        )
    source_root = _validate_approval_source_root(
        Path(authorization._approval_source_root),  # noqa: SLF001 - creation guard
        authorization.authorization_path,
    )
    record, _record_digest = read_approval_record(
        approval_source_root=source_root,
        approval_source_identity=authorization.approval_source_identity,
    )
    if record["approved_authorization_digest"] != authorization.approval_digest:
        raise _fail(
            "the approval record no longer approves the authorization digest",
            "approval_digest",
        )
    if record["study_id"] != study_id or authorization.freeze.study_id != study_id:
        raise _fail("the authorization is for a different study", "study_id")
    candidate = validate_authorization(read_canonical_json(authorization.authorization_path))
    candidate_digest = document_digest(candidate)
    if (
        candidate_digest != authorization.approval_digest
        or candidate_digest != authorization.authorization_document_digest
    ):
        raise _fail(
            "the authorization bytes changed after approval",
            "approval_digest",
        )
    if observed is None:
        if for_production:
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                "fresh identity observations are required for official production work",
                field_path="observed",
            )
        return authorization.freeze
    refreshed = verify_g0_authorization(
        authorization.authorization_path, authorization.approval_digest, observed
    )
    if _observed_identity_digest(observed, profile_version=refreshed.profile_version) != authorization.observed_identity_digest:
        raise _fail(
            "the observed identities changed after authorization",
            "observed_identity_digest",
        )
    if refreshed.study_id != study_id:  # pragma: no cover - guarded above
        raise _fail("the authorization is for a different study", "study_id")
    return refreshed


__all__ = [
    "APPROVAL_RECORD_KIND",
    "APPROVAL_RECORD_SUFFIX",
    "VerifiedOfficialAuthorization",
    "approval_record_path",
    "open_verified_official_authorization",
    "read_approval_record",
    "require_verified_official_authorization",
]
