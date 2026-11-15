"""Bounded, streaming, read-only TAR.GZ and ZIP inspection.

Archives are treated as untrusted bytes. Members are hashed as they stream out of
the archive; nothing is extracted, normalized, executed or written to disk.
Unsupported formats are reported as unavailable rather than guessed at.
"""

from __future__ import annotations

import os
import stat
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.errors import (
    BM_NOT_IMPLEMENTED,
    BM_UNSAFE_INPUT,
    BenchError,
)
from .hashing import sha256_stream
from .paths import open_regular_beneath, validate_relative_member

_HARD_MAX_MEMBERS = 5000
_HARD_MAX_MEMBER_BYTES = 256 * 1024 * 1024
_HARD_MAX_TOTAL_UNCOMPRESSED_BYTES = 4 * 1024**3
_HARD_MAX_ARCHIVE_BYTES = 4 * 1024**3

_TAR_SUFFIXES = (".tar.gz",)
_ZIP_SUFFIXES = (".zip",)


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BenchError(BM_UNSAFE_INPUT, f"{field} must be an integer")
    if value < 1:
        raise BenchError(BM_UNSAFE_INPUT, f"{field} must be positive")
    return value


@dataclass(frozen=True)
class ArchiveLimits:
    """Hard upper bounds for one archive inspection."""

    max_members: int = _HARD_MAX_MEMBERS
    max_member_bytes: int = _HARD_MAX_MEMBER_BYTES
    max_total_uncompressed_bytes: int = _HARD_MAX_TOTAL_UNCOMPRESSED_BYTES
    max_archive_bytes: int = _HARD_MAX_ARCHIVE_BYTES

    def __post_init__(self) -> None:
        for field, hard in (
            ("max_members", _HARD_MAX_MEMBERS),
            ("max_member_bytes", _HARD_MAX_MEMBER_BYTES),
            ("max_total_uncompressed_bytes", _HARD_MAX_TOTAL_UNCOMPRESSED_BYTES),
            ("max_archive_bytes", _HARD_MAX_ARCHIVE_BYTES),
        ):
            value = _require_positive_int(getattr(self, field), field)
            if value > hard:
                raise BenchError(
                    BM_UNSAFE_INPUT,
                    f"{field} must not exceed the hard default {hard}",
                )


@dataclass(frozen=True)
class MemberDigest:
    """Exact identity of one archive member."""

    name: str
    digest: str
    byte_length: int


def _archive_size(handle: Any) -> int:
    info = os.fstat(handle.fileno())
    if not stat.S_ISREG(info.st_mode):  # pragma: no cover - guarded by open
        raise BenchError(BM_UNSAFE_INPUT, "archive is not a regular file")
    return int(info.st_size)


def _require_suffix(relative: str, suffixes: tuple[str, ...], kind: str) -> None:
    if not relative.lower().endswith(suffixes):
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            f"unsupported {kind} archive format for this verifier",
        )


def _check_announced(
    limits: ArchiveLimits,
    *,
    member_name: str,
    member_bytes: int,
    running_total: int,
) -> int:
    if member_bytes > limits.max_member_bytes:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"archive member exceeds the {limits.max_member_bytes}-byte limit: "
            f"{member_name}",
        )
    total = running_total + member_bytes
    if total > limits.max_total_uncompressed_bytes:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "archive exceeds the total uncompressed byte limit",
        )
    return total


def _hash_member(
    stream: Any, *, expected_bytes: int, member_name: str
) -> tuple[str, int]:
    digest, length = sha256_stream(stream, max_bytes=expected_bytes)
    if length != expected_bytes:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"archive member length does not match its declared size: {member_name}",
        )
    return digest, length


def inspect_tar_gz(
    root: Path, relative: str, limits: ArchiveLimits = ArchiveLimits()
) -> tuple[MemberDigest, ...]:
    """Stream-inspect one regular ``.tar.gz`` archive without extracting it."""

    member_name = validate_relative_member(relative)
    _require_suffix(member_name, _TAR_SUFFIXES, "TAR.GZ")
    handle = open_regular_beneath(root, member_name)
    with handle:
        if _archive_size(handle) > limits.max_archive_bytes:
            raise BenchError(
                BM_UNSAFE_INPUT, "archive file exceeds the archive byte limit"
            )
        try:
            with tarfile.open(fileobj=handle, mode="r:gz") as archive:
                members = _iter_tar_members(archive, limits)
        except BenchError:
            raise
        except (tarfile.TarError, EOFError, OSError) as exc:
            raise BenchError(
                BM_UNSAFE_INPUT, "archive is malformed, truncated or unreadable"
            ) from exc
    return tuple(sorted(members, key=lambda item: item.name))


def _iter_tar_members(
    archive: tarfile.TarFile, limits: ArchiveLimits
) -> list[MemberDigest]:
    results: list[MemberDigest] = []
    seen: set[str] = set()
    total = 0
    count = 0
    for info in archive:
        count += 1
        if count > limits.max_members:
            raise BenchError(
                BM_UNSAFE_INPUT, "archive exceeds the member count limit"
            )
        if not info.isfile():
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"archive contains a non-regular member: {info.name!r}",
            )
        name = validate_relative_member(info.name)
        if name in seen:
            raise BenchError(
                BM_UNSAFE_INPUT, f"archive contains a duplicate member: {name!r}"
            )
        seen.add(name)
        total = _check_announced(
            limits,
            member_name=name,
            member_bytes=info.size,
            running_total=total,
        )
        extracted = archive.extractfile(info)
        if extracted is None:  # pragma: no cover - isfile() implies a payload
            raise BenchError(
                BM_UNSAFE_INPUT, f"archive member has no readable payload: {name!r}"
            )
        with extracted:
            digest, length = _hash_member(
                extracted, expected_bytes=info.size, member_name=name
            )
        results.append(
            MemberDigest(name=name, digest=digest, byte_length=length)
        )
    return results


def inspect_zip(
    root: Path, relative: str, limits: ArchiveLimits = ArchiveLimits()
) -> tuple[MemberDigest, ...]:
    """Stream-inspect one regular ``.zip`` archive without extracting it."""

    member_name = validate_relative_member(relative)
    _require_suffix(member_name, _ZIP_SUFFIXES, "ZIP")
    handle = open_regular_beneath(root, member_name)
    with handle:
        if _archive_size(handle) > limits.max_archive_bytes:
            raise BenchError(
                BM_UNSAFE_INPUT, "archive file exceeds the archive byte limit"
            )
        try:
            with zipfile.ZipFile(handle, mode="r") as archive:
                members = _iter_zip_members(archive, limits)
        except BenchError:
            raise
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError,
                OSError) as exc:
            raise BenchError(
                BM_UNSAFE_INPUT, "archive is malformed, truncated or unreadable"
            ) from exc
    return tuple(sorted(members, key=lambda item: item.name))


def _validate_zip_mode(info: zipfile.ZipInfo) -> None:
    mode = info.external_attr >> 16
    if not mode:
        return
    file_type = stat.S_IFMT(mode)
    if file_type == stat.S_IFLNK:
        raise BenchError(
            BM_UNSAFE_INPUT, f"ZIP archive contains a symbolic link: {info.filename!r}"
        )
    if file_type == stat.S_IFDIR:
        raise BenchError(
            BM_UNSAFE_INPUT, f"ZIP archive contains a directory entry: {info.filename!r}"
        )
    if file_type not in (0, stat.S_IFREG):
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"ZIP archive contains a special file entry: {info.filename!r}",
        )


def _iter_zip_members(
    archive: zipfile.ZipFile, limits: ArchiveLimits
) -> list[MemberDigest]:
    infos = archive.infolist()
    if len(infos) > limits.max_members:
        raise BenchError(BM_UNSAFE_INPUT, "archive exceeds the member count limit")
    results: list[MemberDigest] = []
    seen: set[str] = set()
    total = 0
    for info in infos:
        if info.is_dir():
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"ZIP archive contains a directory entry: {info.filename!r}",
            )
        if info.flag_bits & 0x1:
            raise BenchError(
                BM_UNSAFE_INPUT, "ZIP archive contains an encrypted entry"
            )
        _validate_zip_mode(info)
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"ZIP archive uses an unsupported compression method: {info.filename!r}",
            )
        name = validate_relative_member(info.filename)
        if name in seen:
            raise BenchError(
                BM_UNSAFE_INPUT, f"archive contains a duplicate member: {name!r}"
            )
        seen.add(name)
        total = _check_announced(
            limits,
            member_name=name,
            member_bytes=info.file_size,
            running_total=total,
        )
        with archive.open(info, mode="r") as stream:
            digest, length = _hash_member(
                stream, expected_bytes=info.file_size, member_name=name
            )
        results.append(
            MemberDigest(name=name, digest=digest, byte_length=length)
        )
    return results
