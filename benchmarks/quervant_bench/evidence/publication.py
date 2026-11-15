"""Exclusive, crash-aware publication and committed-root loading.

Publication never overwrites and never repairs. The final receipt name is created
last as a hard link to a fully fsynced staging file; that file is the completion
marker. A destination that lacks the marker, contains extra files or still has a
staging file is not reusable.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any, Mapping

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
from .manifests import validate_admission_index
from .paths import open_regular_beneath, require_publication_base
from .provenance import repository_root

INDEX_NAME = "admission-index.json"
RECEIPT_NAME = "admission.json"
PENDING_NAME = "admission.pending"
_COMMITTED_NAMES = frozenset({INDEX_NAME, RECEIPT_NAME})
_MAX_COMMITTED_BYTES = 1_048_576


def _map_os_error(exc: OSError) -> BenchError:
    if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EPERM}:
        return BenchError(
            BM_UNSAFE_INPUT, "publication path is not safely usable"
        )
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


def _fsync_file(descriptor: int) -> None:
    os.fsync(descriptor)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, payload: bytes) -> None:
    try:
        handle = open(path, "xb")
    except FileExistsError as exc:
        raise BenchError(
            BM_PUBLICATION_CONFLICT, "publication target already exists"
        ) from exc
    except OSError as exc:
        raise _map_os_error(exc) from exc
    try:
        handle.write(payload)
        handle.flush()
        _fsync_file(handle.fileno())
    except OSError as exc:
        raise _map_os_error(exc) from exc
    finally:
        handle.close()


def _require_output_base(output_base: Path) -> Path:
    return require_publication_base(output_base, repository_root())


def _require_experiment_directory(experiment_dir: Path) -> None:
    if experiment_dir.is_symlink():
        raise BenchError(
            BM_UNSAFE_INPUT, "experiment output directory must not be a symlink"
        )
    if not experiment_dir.is_dir():
        raise BenchError(
            BM_UNSAFE_INPUT, "experiment output path is not a directory"
        )


def publish_admission(
    output_base: Path,
    experiment_id: str,
    run_id: str,
    index_document: Mapping[str, Any],
    receipt_document: Mapping[str, Any],
) -> Path:
    """Exclusively publish one admission index and its completion receipt."""

    experiment = validate_semantic_id(experiment_id, "experiment_id")
    run = validate_uuid4(run_id, "run_id")
    base = _require_output_base(output_base)
    validate_admission_index(index_document)
    validate_receipt(receipt_document)

    experiment_dir = base / experiment
    try:
        os.mkdir(experiment_dir)
    except FileExistsError:
        pass
    except OSError as exc:
        raise _map_os_error(exc) from exc
    _require_experiment_directory(experiment_dir)

    run_dir = experiment_dir / run
    try:
        os.mkdir(run_dir)
    except FileExistsError as exc:
        raise BenchError(
            BM_PUBLICATION_CONFLICT,
            "an admission destination already exists for this run",
        ) from exc
    except OSError as exc:
        raise _map_os_error(exc) from exc

    index_bytes = canonical_document_bytes(dict(index_document))
    receipt_bytes = canonical_document_bytes(dict(receipt_document))

    _write_exclusive(run_dir / INDEX_NAME, index_bytes)
    _write_exclusive(run_dir / PENDING_NAME, receipt_bytes)
    try:
        _fsync_directory(run_dir)
        final_path = run_dir / RECEIPT_NAME
        if final_path.exists() or final_path.is_symlink():
            raise BenchError(
                BM_PUBLICATION_CONFLICT,
                "a completion receipt already exists for this run",
            )
        try:
            os.link(run_dir / PENDING_NAME, final_path)
        except FileExistsError as exc:
            raise BenchError(
                BM_PUBLICATION_CONFLICT,
                "a completion receipt already exists for this run",
            ) from exc
        except OSError as exc:
            raise _map_os_error(exc) from exc
        _fsync_directory(run_dir)
        try:
            os.unlink(run_dir / PENDING_NAME)
        except OSError as exc:
            raise _map_os_error(exc) from exc
        _fsync_directory(run_dir)
    except BenchError:
        raise
    except OSError as exc:
        raise _map_os_error(exc) from exc
    return run_dir


def _read_canonical_document(root: Path, name: str) -> dict:
    handle = open_regular_beneath(root, name)
    with handle:
        payload = handle.read(_MAX_COMMITTED_BYTES + 1)
    if len(payload) > _MAX_COMMITTED_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT, "committed document exceeds the size limit"
        )
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "committed document is not stored in canonical byte form",
        )
    return document


def load_committed_admission(
    output_base: Path, experiment_id: str, run_id: str
) -> tuple[dict, dict]:
    """Load exactly two canonical committed files; never rewrite or repair them."""

    experiment = validate_semantic_id(experiment_id, "experiment_id")
    run = validate_uuid4(run_id, "run_id")
    base = _require_output_base(output_base)
    run_dir = base / experiment / run
    if run_dir.is_symlink():
        raise BenchError(
            BM_UNSAFE_INPUT, "admission destination must not be a symlink"
        )
    if not run_dir.is_dir():
        raise BenchError(
            BM_PUBLICATION_CONFLICT, "no committed admission destination exists"
        )
    entries: dict[str, os.DirEntry] = {}
    with os.scandir(run_dir) as iterator:
        for entry in iterator:
            entries[entry.name] = entry
    if set(entries) != _COMMITTED_NAMES:
        raise BenchError(
            BM_PUBLICATION_CONFLICT,
            "admission destination is incomplete or contains unexpected entries",
        )
    for name, entry in entries.items():
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"committed admission entry is not a regular file: {name}",
            )

    index_document = _read_canonical_document(run_dir, INDEX_NAME)
    receipt_document = _read_canonical_document(run_dir, RECEIPT_NAME)
    validate_admission_index(index_document)
    receipt = validate_receipt(receipt_document)
    if len(receipt.outputs) != 1:
        raise BenchError(
            BM_IDENTITY_INVALID, "admission receipt must declare one output"
        )
    output = receipt.outputs[0]
    if output.name != "admission-index":
        raise BenchError(
            BM_IDENTITY_INVALID, "admission receipt output must be the index"
        )
    if output.digest != content_digest(index_document):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "admission receipt does not bind the committed index bytes",
        )
    return index_document, receipt_document


__all__ = ["load_committed_admission", "publish_admission"]
