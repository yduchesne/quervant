"""Reusable raw-byte SHA-256 and file-identity helpers.

All digests here are ``sha256:``-prefixed lower-case hexadecimal digests of the
**raw bytes** supplied or read. They are deliberately distinct from BM-01
``config.codec.content_digest``, which hashes canonical JSON payload bytes.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO, Sequence

from ..config.codec import content_digest
from ..config.errors import BM_UNSAFE_INPUT, BenchError
from .paths import open_regular_beneath, validate_relative_member

CHUNK_BYTES = 1_048_576
MAX_SOURCE_FILE_BYTES = 256 * 1024 * 1024


def _require_budget(max_bytes: object, field: str = "max_bytes") -> int:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
        raise BenchError(BM_UNSAFE_INPUT, f"{field} must be an integer")
    if max_bytes < 0:
        raise BenchError(BM_UNSAFE_INPUT, f"{field} must be non-negative")
    return max_bytes


def sha256_stream(stream: BinaryIO, *, max_bytes: int) -> tuple[str, int]:
    """Hash at most ``max_bytes`` of ``stream`` in bounded chunks.

    Returns ``(digest, byte_length)``. Reading one byte past the budget fails
    closed rather than returning a truncated digest.
    """

    budget = _require_budget(max_bytes)
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = stream.read(CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > budget:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"input exceeds the {budget}-byte budget",
            )
        digest.update(chunk)
    return "sha256:" + digest.hexdigest(), total


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def sha256_regular_file(
    root: Path, relative: str, *, max_bytes: int
) -> tuple[str, int]:
    """Hash one confined regular file and detect concurrent replacement.

    The descriptor is held for the whole read. File identity metadata is
    compared immediately after the read; callers performing critical admission
    must additionally perform a second full hash before publishing.
    """

    budget = _require_budget(max_bytes)
    handle = open_regular_beneath(root, relative)
    with handle:
        before = os.fstat(handle.fileno())
        digest, length = sha256_stream(handle, max_bytes=budget)
        after = os.fstat(handle.fileno())
    if length != before.st_size:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "regular file length changed while it was being hashed",
        )
    if _identity(before) != _identity(after):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "regular file identity changed while it was being hashed",
        )
    return digest, length


def source_file_set_digest(root: Path, paths: Sequence[str]) -> str:
    """Return the canonical identity digest of an explicit source file set.

    Paths must already be unique and sorted ascending. Filesystem timestamps are
    never part of the identity; any tracked content change changes the digest.
    """

    validated = [validate_relative_member(path) for path in paths]
    if not validated:
        raise BenchError(BM_UNSAFE_INPUT, "source file set must not be empty")
    if len(set(validated)) != len(validated):
        raise BenchError(BM_UNSAFE_INPUT, "source file set paths must be unique")
    if validated != sorted(validated):
        raise BenchError(BM_UNSAFE_INPUT, "source file set paths must be sorted")

    files: list[dict[str, object]] = []
    for path in validated:
        digest, length = sha256_regular_file(
            root, path, max_bytes=MAX_SOURCE_FILE_BYTES
        )
        files.append({"path": path, "digest": digest, "bytes": length})
    return content_digest(
        {
            "schema_version": 1,
            "kind": "source-file-set",
            "files": files,
        }
    )
