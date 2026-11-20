"""Exclusive, crash-aware 15-file publication and read-only committed loading.

The production filesystem boundary is :class:`OsPublicationIO` with coarse, easily
fault-injected primitives. Publication never overwrites, repairs or cleans up. The
final ``manifest.json`` is created last as a hard link to a fully fsynced
``manifest.pending`` staging file; the loader requires exactly the 15 committed
names, no pending file and no link/directory surprises.
"""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config.codec import (
    canonical_document_bytes,
    content_digest,
    decode_text,
    loads_json,
)
from ..config.contracts import validate_receipt
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_INTERNAL_ERROR,
    BM_NOT_IMPLEMENTED,
    BM_PUBLICATION_CONFLICT,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_semantic_id, validate_uuid4
from ..evidence.paths import require_publication_base
from ..evidence.provenance import repository_root
from .contracts import (
    MANIFEST_MEMBERS,
    MANIFEST_NAME,
    MAX_DOCUMENT_BYTES,
    MEMBER_NAMES,
    PENDING_NAME,
    validate_manifest,
)
from .manifest import verify_freeze_snapshot, verify_manifest_members

COMMITTED_NAMES: frozenset[str] = frozenset(MEMBER_NAMES)
PRECONDITION_NAMES: tuple[str, ...] = MEMBER_NAMES[:14]

ABSENT = "absent"
COMMITTED = "committed"
INCOMPLETE = "incomplete"

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def _require_publication_primitives() -> None:
    """Fail closed when the required filesystem primitives are unavailable."""

    if not _O_NOFOLLOW or not getattr(os, "O_DIRECTORY", 0) or not hasattr(os, "link"):
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            "this platform cannot provide the required no-follow/link publication protocol",
        )


def _map_os_error(exc: OSError) -> BenchError:
    if exc.errno in {errno.EEXIST}:
        return BenchError(
            BM_PUBLICATION_CONFLICT, "publication target already exists"
        )
    if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EPERM}:
        return BenchError(BM_UNSAFE_INPUT, "publication path is not safely usable")
    unsupported = {
        getattr(errno, "EOPNOTSUPP", -1),
        getattr(errno, "ENOTSUP", -1),
        getattr(errno, "EXDEV", -1),
    }
    if exc.errno in unsupported:
        return BenchError(
            BM_NOT_IMPLEMENTED,
            "this platform cannot provide the required link/fsync publication protocol",
        )
    return BenchError(
        BM_INTERNAL_ERROR, "publication failed without publishing a completion marker"
    )


class OsPublicationIO:
    """The production filesystem boundary used by exclusive publication."""

    def create_directory(self, path: Path) -> None:
        os.mkdir(path)

    def create_exclusive(self, path: Path) -> int:
        try:
            return os.open(
                str(path),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
                0o644,
            )
        except OSError as exc:
            raise _map_os_error(exc) from exc

    def write_all(self, descriptor: int, payload: bytes) -> None:
        remaining = memoryview(payload)
        while remaining:
            try:
                written = os.write(descriptor, remaining)
            except OSError as exc:
                raise _map_os_error(exc) from exc
            if written <= 0:  # pragma: no cover - defensive
                raise _map_os_error(OSError(errno.EIO, "short write"))
            remaining = remaining[written:]

    def fsync_file(self, descriptor: int) -> None:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            raise _map_os_error(exc) from exc

    def close(self, descriptor: int) -> None:
        os.close(descriptor)

    def fsync_dir(self, directory: Path) -> None:
        try:
            descriptor = os.open(
                str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
        except OSError as exc:
            raise _map_os_error(exc) from exc
        try:
            os.fsync(descriptor)
        except OSError as exc:
            raise _map_os_error(exc) from exc
        finally:
            os.close(descriptor)

    def hardlink_no_replace(self, source: Path, destination: Path) -> None:
        try:
            os.link(source, destination)
        except OSError as exc:
            raise _map_os_error(exc) from exc

    def unlink_pending(self, path: Path) -> None:
        try:
            os.unlink(path)
        except OSError as exc:
            raise _map_os_error(exc) from exc


@dataclass(frozen=True)
class CommittedBundle:
    """The read-only result of loading one committed qualification directory."""

    output_directory: Path
    documents: Mapping[str, Mapping[str, Any]]
    payloads: Mapping[str, bytes]
    manifest_digest: str


def validate_destination_names(output_base: Path, experiment_id: str, run_id: str) -> Path:
    base = require_publication_base(output_base, repository_root())
    experiment = validate_semantic_id(experiment_id, "experiment_id")
    run = validate_uuid4(run_id, "run_id")
    return base / experiment / run


def _safe_directory(directory: Path) -> bool:
    return directory.is_dir() and not directory.is_symlink()


def destination_state(output_base: Path, experiment_id: str, run_id: str) -> str:
    """Classify a destination as absent, committed or incomplete (never repairs)."""

    run_dir = validate_destination_names(output_base, experiment_id, run_id)
    experiment_dir = run_dir.parent
    if not os.path.lexists(experiment_dir):
        return ABSENT
    if not _safe_directory(experiment_dir):
        raise BenchError(
            BM_UNSAFE_INPUT, "experiment output path is not a safe directory"
        )
    if not os.path.lexists(run_dir):
        return ABSENT
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise BenchError(BM_UNSAFE_INPUT, "run output path is not a safe directory")
    with os.scandir(run_dir) as iterator:
        names = {entry.name for entry in iterator}
    if names != COMMITTED_NAMES:
        return INCOMPLETE
    for entry in os.scandir(run_dir):
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            raise BenchError(
                BM_UNSAFE_INPUT,
                "committed qualification entries must be regular files",
                reference=entry.name,
            )
    return COMMITTED


def _require_member_bytes(
    members: Sequence[tuple[str, Mapping[str, Any]]],
    manifest: Mapping[str, Any],
) -> list[tuple[str, bytes]]:
    names = tuple(name for name, _document in members)
    if names != PRECONDITION_NAMES:
        raise _fail("the published member order is not the exact 14-file inventory", "members")
    entries = validate_manifest(manifest)
    expected = {member["path"]: member for member in entries["members"]}
    payloads: list[tuple[str, bytes]] = []
    for name, document in members:
        payload = canonical_document_bytes(dict(document))
        if len(payload) > MAX_DOCUMENT_BYTES:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"{name} exceeds the committed document budget",
                reference=name,
            )
        member = expected.get(name)
        if member is None:
            raise _fail("the manifest does not declare a published member", name)
        if member["byte_length"] != len(payload):
            raise _fail("the manifest byte length does not match the published bytes", name)
        if member["digest"] != content_digest(dict(document)):
            raise _fail("the manifest digest does not match the published bytes", name)
        payloads.append((name, payload))
    return payloads


def publish_validated_members_atomic(
    *,
    run_dir: Path,
    payloads: Sequence[tuple[str, bytes]],
    manifest_payload: bytes,
    io: OsPublicationIO | None = None,
) -> Path:
    """Write already-validated canonical members and the exclusive commit marker.

    This is the single mechanical durability implementation shared by the
    synthetic and official publishers. The caller must have validated the member
    semantics and the manifest *before* calling; this function never reinterprets
    bytes and never clears, repairs or overwrites an existing destination.
    """

    _require_publication_primitives()
    backend = io if io is not None else OsPublicationIO()
    for _name, payload in payloads:
        if not isinstance(payload, (bytes, bytearray)):
            raise BenchError(BM_INTERNAL_ERROR, "publication payloads must be bytes")
    if not isinstance(manifest_payload, (bytes, bytearray)):  # pragma: no cover - defensive
        raise BenchError(BM_INTERNAL_ERROR, "the manifest payload must be bytes")

    def guard(operation: Any) -> Any:
        try:
            return operation()
        except BenchError:
            raise
        except OSError as exc:
            raise _map_os_error(exc) from exc

    experiment_dir = run_dir.parent
    if os.path.lexists(experiment_dir):
        if not _safe_directory(experiment_dir):
            raise BenchError(
                BM_UNSAFE_INPUT, "experiment output path is not a safe directory"
            )
    else:
        try:
            guard(lambda: backend.create_directory(experiment_dir))
        except BenchError as error:
            if error.code != BM_PUBLICATION_CONFLICT:
                raise
        if not _safe_directory(experiment_dir):
            raise BenchError(
                BM_UNSAFE_INPUT, "experiment output path is not a safe directory"
            )
    guard(lambda: backend.create_directory(run_dir))

    for name, payload in payloads:
        descriptor = guard(lambda name=name: backend.create_exclusive(run_dir / name))
        try:
            guard(lambda descriptor=descriptor, payload=payload: backend.write_all(descriptor, payload))
            guard(lambda descriptor=descriptor: backend.fsync_file(descriptor))
        finally:
            backend.close(descriptor)

    guard(lambda: backend.fsync_dir(run_dir))

    pending = run_dir / PENDING_NAME
    descriptor = guard(lambda: backend.create_exclusive(pending))
    try:
        guard(lambda descriptor=descriptor: backend.write_all(descriptor, manifest_payload))
        guard(lambda descriptor=descriptor: backend.fsync_file(descriptor))
    finally:
        backend.close(descriptor)

    guard(lambda: backend.hardlink_no_replace(pending, run_dir / MANIFEST_NAME))
    guard(lambda: backend.fsync_dir(run_dir))
    guard(lambda: backend.unlink_pending(pending))
    guard(lambda: backend.fsync_dir(run_dir))
    return run_dir


def publish_bundle(
    *,
    output_base: Path,
    experiment_id: str,
    run_id: str,
    members: Sequence[tuple[str, Mapping[str, Any]]],
    manifest: Mapping[str, Any],
    io: OsPublicationIO | None = None,
) -> Path:
    """Exclusively publish the 14 documents and the final completion manifest."""

    _require_publication_primitives()
    run_dir = validate_destination_names(output_base, experiment_id, run_id)
    payloads = _require_member_bytes(members, manifest)
    return publish_validated_members_atomic(
        run_dir=run_dir,
        payloads=payloads,
        manifest_payload=canonical_document_bytes(dict(manifest)),
        io=io,
    )


def _read_canonical(root: Path, name: str) -> tuple[dict[str, Any], bytes]:
    from ..evidence.paths import open_regular_beneath

    handle = open_regular_beneath(root, name)
    with handle:
        payload = handle.read(MAX_DOCUMENT_BYTES + 1)
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "committed document exceeds the size limit",
            reference=name,
        )
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "committed document is not stored in canonical byte form",
            reference=name,
        )
    return dict(document), payload


def load_bundle(
    *, output_base: Path, experiment_id: str, run_id: str
) -> CommittedBundle:
    """Strictly load one complete 15-file qualification directory; never writes."""

    run_dir = validate_destination_names(output_base, experiment_id, run_id)
    if run_dir.is_symlink():
        raise BenchError(BM_UNSAFE_INPUT, "run destination must not be a symlink")
    if not run_dir.is_dir():
        raise BenchError(
            BM_PUBLICATION_CONFLICT, "no committed qualification destination exists"
        )
    entries: dict[str, os.DirEntry[str]] = {}
    with os.scandir(run_dir) as iterator:
        for entry in iterator:
            entries[entry.name] = entry
    if set(entries) != COMMITTED_NAMES:
        raise BenchError(
            BM_PUBLICATION_CONFLICT,
            "qualification destination is incomplete or contains unexpected entries",
        )
    for name, entry in entries.items():
        if entry.name == PENDING_NAME:  # pragma: no cover - excluded above
            raise BenchError(BM_PUBLICATION_CONFLICT, "qualification is incomplete")
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"committed entry is not a regular file: {name}",
            )
        info = entry.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"committed entry is not an exclusive regular file: {name}",
            )

    documents: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes] = {}
    for name in MEMBER_NAMES:
        document, payload = _read_canonical(run_dir, name)
        documents[name] = document
        payloads[name] = payload

    manifest = validate_manifest(documents[MANIFEST_NAME])
    manifest_digest = verify_manifest_members(
        manifest=manifest,
        payloads={name: payloads[name] for name in MANIFEST_MEMBERS},
        documents={name: documents[name] for name in MANIFEST_MEMBERS},
    )
    attestation = validate_receipt(documents["attestation.json"])
    if attestation.gate != "attestation":
        raise _fail("the completion attestation is not an attestation receipt", "gate")
    snapshot_digest = verify_freeze_snapshot(
        snapshot=manifest["freeze_snapshot"],
        attestation_receipt=documents["attestation.json"],
        documents={name: documents[name] for name in PRECONDITION_NAMES[:13]},
        subject=manifest["subject"],
        profile_digest=manifest["profile_digest"],
        source_set_digest=manifest["source_set_digest"],
    )
    if snapshot_digest == manifest_digest:  # pragma: no cover - defensive
        raise _fail("the snapshot and manifest digests must be distinct", "manifest")
    return CommittedBundle(
        output_directory=run_dir,
        documents=documents,
        payloads=payloads,
        manifest_digest=manifest_digest,
    )


__all__ = [
    "ABSENT",
    "COMMITTED",
    "COMMITTED_NAMES",
    "CommittedBundle",
    "INCOMPLETE",
    "OsPublicationIO",
    "PRECONDITION_NAMES",
    "destination_state",
    "load_bundle",
    "publish_bundle",
    "publish_validated_members_atomic",
    "validate_destination_names",
]
