"""Exclusive, fsync-durable publication of one synthetic evidence run.

All writes are descriptor-relative with ``O_CREAT | O_EXCL | O_NOFOLLOW``; a
directory entry is created exclusively, the file is fsynced, then its parent
directory is fsynced. ``seal.json`` is the last committed artifact and is written
only through :meth:`ExecutionStore.commit_seal`.

This store is for deterministic simulation only. It is **not** a general
production evidence backend and its durability story must be revisited before a
real qualification campaign is designed.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import sha256_prefix
from ..config.errors import (
    BM_INTERNAL_ERROR,
    BM_NOT_IMPLEMENTED,
    BM_PUBLICATION_CONFLICT,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_semantic_id, validate_uuid4
from ..evidence.paths import (
    open_regular_beneath,
    require_disjoint_admission_roots,
    require_safe_root,
    validate_relative_member,
)
from .contracts import MAX_CANONICAL_RECORD_BYTES
from .recorder import record_bytes, validate_seal_document

SEAL_NAME = "seal.json"

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", None)


def _require_descriptor_support() -> None:
    if _O_NOFOLLOW is None or _O_DIRECTORY is None:  # pragma: no cover - Linux only
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            "safe descriptor-relative publication is unavailable on this platform",
        )
    if os.open not in getattr(os, "supports_dir_fd", set()):  # pragma: no cover
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            "safe descriptor-relative publication is unavailable on this platform",
        )


def _map_os_error(exc: OSError) -> BenchError:
    if exc.errno in {errno.EEXIST}:
        return BenchError(BM_PUBLICATION_CONFLICT, "publication target already exists")
    if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EPERM, errno.EISDIR}:
        return BenchError(
            BM_UNSAFE_INPUT, "publication path is not safely usable"
        )
    unsupported = {
        getattr(errno, "EOPNOTSUPP", -1),
        getattr(errno, "ENOTSUP", -1),
        getattr(errno, "EXDEV", -1),
        getattr(errno, "EINVAL", -1),
    }
    if exc.errno in unsupported:
        return BenchError(
            BM_NOT_IMPLEMENTED,
            "this platform cannot provide the required fsync publication protocol",
        )
    return BenchError(
        BM_INTERNAL_ERROR,
        "publication failed without publishing a completion marker",
    )


def _fsync_dir(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise _map_os_error(exc) from exc


def _open_dir(path: Path) -> int:
    flags = os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW
    try:
        return os.open(str(path), flags)
    except OSError as exc:
        raise _map_os_error(exc) from exc


def _ensure_child_dir(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise _map_os_error(exc) from exc
    try:
        os.mkdir(name, 0o755, dir_fd=parent_fd)
    except FileExistsError as exc:  # pragma: no cover - race between open and mkdir
        raise BenchError(BM_PUBLICATION_CONFLICT, "publication target already exists") from exc
    except OSError as exc:
        raise _map_os_error(exc) from exc
    _fsync_dir(parent_fd)
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:  # pragma: no cover - defensive
        raise _map_os_error(exc) from exc


class ExecutionStore:
    """One exclusive per-run evidence root."""

    __slots__ = ("_run_dir", "_output_base", "_evidence_root", "_experiment_id", "_run_id")

    def __init__(
        self,
        run_dir: Path,
        *,
        output_base: Path,
        evidence_root: Path,
        experiment_id: str,
        run_id: str,
    ) -> None:
        self._run_dir = run_dir
        self._output_base = output_base
        self._evidence_root = evidence_root
        self._experiment_id = experiment_id
        self._run_id = run_id

    # -- construction -----------------------------------------------------

    @classmethod
    def create(
        cls,
        output_base: Path,
        experiment_id: str,
        run_id: str,
        *,
        evidence_root: Path,
        repo_root: Path,
    ) -> "ExecutionStore":
        """Create a new per-run directory exclusively; never reuse an identity."""

        _require_descriptor_support()
        experiment = validate_semantic_id(experiment_id, "experiment_id")
        run = validate_uuid4(run_id, "run_id")
        evidence, output = require_disjoint_admission_roots(
            evidence_root, output_base, repo_root
        )
        experiment_dir = output / experiment
        if experiment_dir.is_symlink():
            raise BenchError(
                BM_UNSAFE_INPUT, "experiment output directory must not be a symlink"
            )
        try:
            os.mkdir(experiment_dir)
        except FileExistsError:
            pass
        except OSError as exc:
            raise _map_os_error(exc) from exc
        if experiment_dir.is_symlink() or not experiment_dir.is_dir():
            raise BenchError(
                BM_UNSAFE_INPUT, "experiment output path is not a plain directory"
            )
        run_dir = experiment_dir / run
        try:
            os.mkdir(run_dir)
        except FileExistsError as exc:
            raise BenchError(
                BM_PUBLICATION_CONFLICT,
                "an execution destination already exists for this run",
            ) from exc
        except OSError as exc:
            raise _map_os_error(exc) from exc
        _fsync_dir(_open_dir(experiment_dir))
        _fsync_dir(_open_dir(output))
        return cls(
            run_dir,
            output_base=output,
            evidence_root=evidence,
            experiment_id=experiment,
            run_id=run,
        )

    # -- attributes -------------------------------------------------------

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def output_base(self) -> Path:
        return self._output_base

    @property
    def evidence_root(self) -> Path:
        return self._evidence_root

    @property
    def experiment_id(self) -> str:
        return self._experiment_id

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def relative_run_dir(self) -> str:
        """Return the repository/output-relative run location for reporting."""

        return f"{self._experiment_id}/{self._run_id}"

    # -- writing ----------------------------------------------------------

    def _open_directory_chain(self, components: tuple[str, ...], *, create: bool) -> int:
        descriptor = _open_dir(self._run_dir)
        for component in components:
            if create:
                next_descriptor = _ensure_child_dir(descriptor, component)
            else:
                flags = os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW
                try:
                    next_descriptor = os.open(component, flags, dir_fd=descriptor)
                except OSError as exc:
                    raise _map_os_error(exc) from exc
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor

    def write_new(self, relative: str, document: Mapping[str, Any]) -> str:
        """Exclusively write one canonical record and return its raw-byte digest."""

        member = validate_relative_member(relative)
        if member == SEAL_NAME:
            raise BenchError(
                BM_PUBLICATION_CONFLICT,
                "the completion seal must be published through commit_seal",
            )
        return self._write_exclusive(member, document)

    def _write_exclusive(self, member: str, document: Mapping[str, Any]) -> str:
        _require_descriptor_support()
        payload = record_bytes(dict(document))
        components = member.split("/")
        directory_fd = self._open_directory_chain(tuple(components[:-1]), create=True)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW
            try:
                descriptor = os.open(components[-1], flags, 0o644, dir_fd=directory_fd)
            except OSError as exc:
                raise _map_os_error(exc) from exc
            try:
                written = 0
                while written < len(payload):
                    written += os.write(descriptor, payload[written:])
                try:
                    os.fsync(descriptor)
                except OSError as exc:
                    raise _map_os_error(exc) from exc
            finally:
                os.close(descriptor)
            _fsync_dir(directory_fd)
        finally:
            os.close(directory_fd)
        return sha256_prefix(payload)

    def commit_seal(self, seal_document: Mapping[str, Any]) -> str:
        """Publish the last artifact exclusively and return its raw-byte digest."""

        validate_seal_document(seal_document)
        return self._write_exclusive(SEAL_NAME, seal_document)

    # -- reading ----------------------------------------------------------

    def read_raw(self, relative: str) -> bytes:
        """Read one bounded stored record without following links."""

        member = validate_relative_member(relative)
        handle = open_regular_beneath(self._run_dir, member)
        with handle:
            payload = handle.read(MAX_CANONICAL_RECORD_BYTES + 1)
        if len(payload) > MAX_CANONICAL_RECORD_BYTES:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "stored record exceeds the canonical record budget",
                reference=member,
            )
        return payload

    def list_existing(self) -> tuple[str, ...]:
        """Return every stored relative path, sorted, with no link traversal."""

        _require_descriptor_support()
        require_safe_root(self._run_dir)
        collected: list[str] = []
        self._walk("", collected)
        return tuple(sorted(collected))

    def _walk(self, relative: str, collected: list[str]) -> None:
        components = tuple(relative.split("/")) if relative else ()
        directory_fd = self._open_directory_chain(components, create=False)
        try:
            try:
                names = sorted(os.listdir(directory_fd))
            except OSError as exc:  # pragma: no cover - defensive
                raise _map_os_error(exc) from exc
            for name in names:
                try:
                    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                except OSError as exc:
                    raise _map_os_error(exc) from exc
                child = f"{relative}/{name}" if relative else name
                if stat.S_ISLNK(info.st_mode):
                    raise BenchError(
                        BM_UNSAFE_INPUT,
                        "stored evidence must not contain symbolic links",
                        reference=child,
                    )
                if stat.S_ISDIR(info.st_mode):
                    self._walk(child, collected)
                elif stat.S_ISREG(info.st_mode):
                    collected.append(child)
                else:
                    raise BenchError(
                        BM_UNSAFE_INPUT,
                        "stored evidence must contain only regular files and directories",
                        reference=child,
                    )
        finally:
            os.close(directory_fd)


