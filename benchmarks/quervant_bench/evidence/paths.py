"""Root-confined, no-symlink file access for untrusted evidence directories.

The only supported host class is a POSIX system exposing ``O_NOFOLLOW`` and
``dir_fd`` descriptor-relative ``os.open``. Everything else fails closed with
``BM_NOT_IMPLEMENTED`` rather than falling back to a string-only check followed
by a symlink-following open.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path
from typing import BinaryIO, Sequence

from ..config.errors import (
    BM_FILE_MISSING,
    BM_NOT_IMPLEMENTED,
    BM_UNSAFE_INPUT,
    BenchError,
)

MAX_RELATIVE_BYTES = 4096
MAX_COMPONENTS = 32

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", None)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


def _descriptor_support() -> bool:
    """Return whether the required safe descriptor semantics are available."""

    if _O_NOFOLLOW is None or _O_DIRECTORY is None:
        return False
    try:
        supported = os.supports_dir_fd
    except AttributeError:  # pragma: no cover - very old Python only
        return False
    return os.open in supported


def _require_descriptor_support() -> None:
    if not _descriptor_support():  # pragma: no cover - Linux/WSL2 path is used
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            "safe descriptor-relative file access is unavailable on this platform",
        )


def validate_relative_member(name: str) -> str:
    """Validate one POSIX-style relative evidence member name.

    Symbols are case-sensitive and Unicode is preserved exactly. Absolute
    paths, traversal, backslashes, drive colons, control characters and
    resource-bound violations are rejected before any file access.
    """

    if not isinstance(name, str):
        raise BenchError(BM_UNSAFE_INPUT, "evidence member name must be a string")
    if not name:
        raise BenchError(BM_UNSAFE_INPUT, "evidence member name must not be empty")
    if len(name.encode("utf-8")) > MAX_RELATIVE_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"evidence member name exceeds {MAX_RELATIVE_BYTES} UTF-8 bytes",
        )
    for character in name:
        codepoint = ord(character)
        if codepoint < 0x20 or codepoint == 0x7F:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "evidence member name contains an ASCII control character",
            )
    if "\\" in name:
        raise BenchError(
            BM_UNSAFE_INPUT, "evidence member name must use '/' separators"
        )
    if name.startswith("/"):
        raise BenchError(BM_UNSAFE_INPUT, "evidence member name must be relative")
    if ":" in name:
        raise BenchError(
            BM_UNSAFE_INPUT, "evidence member name must not contain a drive colon"
        )
    components = name.split("/")
    if len(components) > MAX_COMPONENTS:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"evidence member path exceeds {MAX_COMPONENTS} components",
        )
    for component in components:
        if component in {"", ".", ".."}:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "evidence member path must not contain empty, '.' or '..' components",
            )
    return name


def _reject_symlinked_ancestors(root: Path) -> None:
    for candidate in [root, *root.parents]:
        try:
            if candidate.is_symlink():
                raise BenchError(
                    BM_UNSAFE_INPUT,
                    "evidence root or one of its ancestors is a symbolic link",
                )
        except OSError as exc:  # pragma: no cover - defensive
            raise BenchError(
                BM_UNSAFE_INPUT, "evidence root ancestry cannot be inspected"
            ) from exc


def require_safe_root(root: Path) -> Path:
    """Validate that ``root`` is an existing, non-symlinked directory."""

    candidate = Path(root)
    if not candidate.exists():
        raise BenchError(BM_FILE_MISSING, "evidence root does not exist")
    if not candidate.is_dir():
        raise BenchError(BM_UNSAFE_INPUT, "evidence root must be a directory")
    _reject_symlinked_ancestors(candidate)
    return candidate


def _map_open_error(exc: OSError) -> BenchError:
    if exc.errno in {errno.ENOENT}:
        return BenchError(BM_FILE_MISSING, "evidence file does not exist")
    if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EPERM}:
        return BenchError(
            BM_UNSAFE_INPUT,
            "evidence path is not a safe regular file beneath the root",
        )
    return BenchError(BM_UNSAFE_INPUT, "evidence path cannot be opened safely")


def _open_directory_fd(root: Path, components: Sequence[str]) -> int:
    """Open a directory descriptor by walking ``components`` without symlinks."""

    directory_flags = os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW
    try:
        fd = os.open(str(root), directory_flags)
    except OSError as exc:  # pragma: no cover - defensive
        raise _map_open_error(exc) from exc
    try:
        for component in components:
            next_fd = os.open(component, directory_flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
    except OSError as exc:
        os.close(fd)
        raise _map_open_error(exc) from exc
    return fd


def open_regular_beneath(root: Path, relative: str) -> BinaryIO:
    """Open one declared regular file beneath ``root`` without following links.

    Every intermediate component is opened with ``O_DIRECTORY | O_NOFOLLOW``
    relative to its parent descriptor and the leaf is opened with ``O_NOFOLLOW``.
    Only regular files are accepted. The returned handle is read-only and owns
    its descriptor.
    """

    _require_descriptor_support()
    member = validate_relative_member(relative)
    safe_root = require_safe_root(root)

    components = member.split("/")
    directory_fd = _open_directory_fd(safe_root, components[:-1])
    try:
        try:
            leaf_fd = os.open(
                components[-1],
                os.O_RDONLY | _O_NOFOLLOW | _O_NONBLOCK,
                dir_fd=directory_fd,
            )
        except OSError as exc:
            raise _map_open_error(exc) from exc
    finally:
        os.close(directory_fd)

    try:
        info = os.fstat(leaf_fd)
        if not stat.S_ISREG(info.st_mode):
            raise BenchError(
                BM_UNSAFE_INPUT, "evidence path is not a regular file"
            )
    except BaseException:
        os.close(leaf_fd)
        raise
    return os.fdopen(leaf_fd, "rb")


def list_directory_beneath(root: Path, relative: str) -> tuple[str, ...]:
    """Return the sorted entry names of one directory beneath ``root``.

    The directory walk uses the same descriptor-relative, no-symlink discipline
    as :func:`open_regular_beneath`. Entries are names only; no entry is opened.
    """

    _require_descriptor_support()
    member = validate_relative_member(relative)
    safe_root = require_safe_root(root)
    directory_fd = _open_directory_fd(safe_root, member.split("/"))
    try:
        try:
            names = os.listdir(directory_fd)
        except OSError as exc:  # pragma: no cover - defensive
            raise _map_open_error(exc) from exc
    finally:
        os.close(directory_fd)
    return tuple(sorted(names))


def list_declared_files_beneath(
    root: Path, names: Sequence[str]
) -> tuple[str, ...]:
    """Validate, de-duplicate and sort an explicit declared evidence set.

    The function never discovers additional files. A duplicate declaration is a
    contract error; the caller is responsible for comparing the returned set with
    the actual closed directory contents where that is required.
    """

    require_safe_root(root)
    validated = [validate_relative_member(name) for name in names]
    if len(set(validated)) != len(validated):
        raise BenchError(
            BM_UNSAFE_INPUT, "declared evidence names must be unique"
        )
    return tuple(sorted(validated))
