"""Read-only source, build and validator identity verification.

Git access is limited to argument-list subprocess calls that read objects from a
local repository. No shell, checkout, worktree switch, fetch, build or execution
is performed. Source identities are hashes of raw bytes, never timestamps or
absolute host paths.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_source_commit
from .hashing import (
    sha256_regular_file,
    sha256_stream,
    source_file_set_digest,
)
from .paths import list_declared_files_beneath, validate_relative_member

_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
_MAX_BUILD_FILE_BYTES = 4 * 1024**3

#: Exact implementation source files that constitute the shared validator.
VALIDATOR_SOURCE_PATHS: tuple[str, ...] = (
    "config/codec.py",
    "config/contracts.py",
    "config/errors.py",
    "config/identity.py",
    "config/schemas.py",
    "evidence/admission.py",
    "evidence/archives.py",
    "evidence/hashing.py",
    "evidence/manifests.py",
    "evidence/paths.py",
    "evidence/provenance.py",
    "evidence/publication.py",
    "evidence/receipts.py",
)


@dataclass(frozen=True)
class VerifiedBlob:
    """One tracked path whose raw blob bytes were verified."""

    path: str
    sha256: str


@dataclass(frozen=True)
class GitSourceIdentity:
    """Verified source identity for a pinned commit."""

    commit: str
    tree_sha: str
    files: tuple[VerifiedBlob, ...]


@dataclass(frozen=True)
class BuildFileIdentity:
    """Verified build artifact identity."""

    digest: str
    byte_length: int


def repository_root() -> Path:
    """Return the repository root containing this package."""

    return Path(__file__).resolve().parents[3]


def _run_git(repo_root: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
            env=environment,
        )
    except OSError as exc:  # pragma: no cover - git absent
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git is unavailable for source verification"
        ) from exc


def _require_repository(repo_root: Path) -> Path:
    candidate = Path(repo_root)
    if not candidate.is_dir():
        raise BenchError(BM_EVIDENCE_UNAVAILABLE, "repository root is unavailable")
    return candidate


def verify_git_commit(
    repo_root: Path,
    expected_commit: str,
    *,
    expected_paths: Mapping[str, str],
) -> GitSourceIdentity:
    """Verify a pinned commit, its tree and the raw bytes of named tracked paths."""

    commit = validate_source_commit(expected_commit)
    if not expected_paths:
        raise BenchError(
            BM_IDENTITY_INVALID, "at least one tracked path must be declared"
        )
    paths = list(expected_paths)
    if len(set(paths)) != len(paths):
        raise BenchError(BM_IDENTITY_INVALID, "tracked paths must be unique")
    if paths != sorted(paths):
        raise BenchError(BM_IDENTITY_INVALID, "tracked paths must be sorted")
    expected: dict[str, str] = {}
    for path in paths:
        validate_relative_member(path)
        expected[path] = validate_digest(
            expected_paths[path], f"expected_paths[{path!r}]"
        )

    repository = _require_repository(repo_root)
    exists = _run_git(repository, ["cat-file", "-e", f"{commit}^{{commit}}"])
    if exists.returncode != 0:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            f"pinned commit is not available in this repository: {commit}",
        )
    tree = _run_git(repository, ["rev-parse", f"{commit}^{{tree}}"])
    if tree.returncode != 0:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "pinned commit tree cannot be resolved"
        )
    tree_sha = tree.stdout.decode("ascii", errors="strict").strip()
    if _GIT_OBJECT_RE.fullmatch(tree_sha) is None:
        raise BenchError(
            BM_IDENTITY_INVALID, "resolved Git tree identity is malformed"
        )

    verified: list[VerifiedBlob] = []
    for path, digest in expected.items():
        shown = _run_git(repository, ["show", f"{commit}:{path}"])
        if shown.returncode != 0:
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                f"tracked path is unavailable at the pinned commit: {path}",
            )
        observed, _length = sha256_stream(_BytesReader(shown.stdout), max_bytes=len(shown.stdout))
        if observed != digest:
            raise BenchError(
                BM_IDENTITY_INVALID,
                f"tracked path bytes do not match the pinned digest: {path}",
            )
        verified.append(VerifiedBlob(path=path, sha256=observed))

    return GitSourceIdentity(
        commit=commit, tree_sha=tree_sha, files=tuple(verified)
    )


class _BytesReader:
    """Minimal read-only stream adapter over immutable bytes."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def require_clean_head(repo_root: Path) -> None:
    """Require the active working tree to have no tracked or untracked changes."""

    repository = _require_repository(repo_root)
    status = _run_git(repository, ["status", "--porcelain=v1"])
    if status.returncode != 0:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "repository status cannot be inspected"
        )
    if status.stdout.strip():
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the active working tree does not correspond exactly to a clean commit",
        )


def verify_build_file(
    root: Path, relative_binary: str, expected_digest: str
) -> BuildFileIdentity:
    """Hash one declared regular build artifact without executing it."""

    validate_relative_member(relative_binary)
    expected = validate_digest(expected_digest, "expected_digest")
    digest, length = sha256_regular_file(
        root, relative_binary, max_bytes=_MAX_BUILD_FILE_BYTES
    )
    if digest != expected:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "build artifact bytes do not match the pinned digest",
        )
    return BuildFileIdentity(digest=digest, byte_length=length)


def verify_validator_source(
    root: Path,
    paths: Sequence[str],
    expected_source_digest: str,
) -> str:
    """Verify the exact validator source-file-set identity."""

    expected = validate_digest(expected_source_digest, "expected_source_digest")
    declared = list_declared_files_beneath(root, paths)
    observed = source_file_set_digest(root, declared)
    if observed != expected:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "validator source file set does not match the pinned digest",
        )
    return observed


__all__ = [
    "VALIDATOR_SOURCE_PATHS",
    "BuildFileIdentity",
    "GitSourceIdentity",
    "VerifiedBlob",
    "require_clean_head",
    "repository_root",
    "verify_build_file",
    "verify_git_commit",
    "verify_validator_source",
]
