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
_GIT_SIZE_RE = re.compile(r"^(0|[1-9][0-9]*)\n?$")
_MAX_GIT_METADATA_BYTES = 128
_MAX_GIT_BLOB_BYTES = 256 * 1024 * 1024
_MAX_BUILD_FILE_BYTES = 4 * 1024**3

#: Exact implementation source files that constitute the shared validator.
VALIDATOR_SOURCE_PATHS: tuple[str, ...] = (
    "__init__.py",
    "config/__init__.py",
    "config/codec.py",
    "config/contracts.py",
    "config/errors.py",
    "config/identity.py",
    "config/profiles.py",
    "config/schemas.py",
    "evidence/__init__.py",
    "evidence/admission.py",
    "evidence/archives.py",
    "evidence/hashing.py",
    "evidence/manifests.py",
    "evidence/paths.py",
    "evidence/provenance.py",
    "evidence/publication.py",
    "evidence/receipts.py",
    "host/__init__.py",
    "host/capabilities.py",
    "host/readiness.py",
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


def _git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _run_git(repo_root: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
            env=_git_environment(),
        )
    except OSError as exc:  # pragma: no cover - git absent
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git is unavailable for source verification"
        ) from exc


def _terminate_git_child(process: subprocess.Popen) -> None:
    """Close the pipe and kill/reap a child on every failure path."""

    stream = process.stdout
    if stream is not None:
        try:
            if not stream.closed:
                stream.close()
        except OSError:  # pragma: no cover - defensive
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:  # pragma: no cover - already exited
            pass
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:  # pragma: no cover - hard-hung child
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=30)
        except (subprocess.TimeoutExpired, OSError):  # pragma: no cover
            pass
    except OSError:  # pragma: no cover - defensive
        pass


def _declared_blob_size(size_result: subprocess.CompletedProcess) -> int:
    if size_result.returncode != 0:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git blob size cannot be resolved"
        )
    raw = size_result.stdout
    if len(raw) > _MAX_GIT_METADATA_BYTES:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git blob size metadata is unexpectedly large"
        )
    try:
        text = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git blob size metadata is malformed"
        ) from exc
    if _GIT_SIZE_RE.fullmatch(text) is None:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git blob size metadata is malformed"
        )
    return int(text.rstrip("\n"))


def _hash_git_blob(
    repo_root: Path, commit: str, path: str
) -> tuple[str, int]:
    """Hash one Git blob with a size preflight and bounded streaming reads."""

    declared = _declared_blob_size(
        _run_git(repo_root, ["cat-file", "-s", f"{commit}:{path}"])
    )
    if declared > _MAX_GIT_BLOB_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"git blob exceeds the {_MAX_GIT_BLOB_BYTES}-byte verification budget",
        )
    try:
        process = subprocess.Popen(
            ["git", "-C", str(repo_root), "cat-file", "blob", f"{commit}:{path}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            shell=False,
            env=_git_environment(),
        )
    except OSError as exc:  # pragma: no cover - git absent
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git blob stream cannot be started"
        ) from exc

    stream = process.stdout
    if stream is None:  # pragma: no cover - defensive
        _terminate_git_child(process)
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git blob stream has no readable output"
        )
    try:
        digest, length = sha256_stream(stream, max_bytes=_MAX_GIT_BLOB_BYTES)
    except BaseException:
        _terminate_git_child(process)
        raise
    try:
        stream.close()
    except OSError:  # pragma: no cover - defensive
        pass
    try:
        returncode = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        _terminate_git_child(process)
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git blob stream timed out"
        )
    except OSError as exc:  # pragma: no cover - defensive
        _terminate_git_child(process)
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git blob stream cannot be reaped"
        ) from exc
    if returncode != 0:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git blob streaming failed"
        )
    if length != declared:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "git blob length does not match its declared size",
        )
    return digest, length


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
    if len(tree.stdout) > _MAX_GIT_METADATA_BYTES:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "resolved Git tree identity is unexpectedly large"
        )
    try:
        tree_sha = tree.stdout.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "resolved Git tree identity is malformed"
        ) from exc
    if _GIT_OBJECT_RE.fullmatch(tree_sha) is None:
        raise BenchError(
            BM_IDENTITY_INVALID, "resolved Git tree identity is malformed"
        )

    verified: list[VerifiedBlob] = []
    for path, digest in expected.items():
        observed, _length = _hash_git_blob(repository, commit, path)
        if observed != digest:
            raise BenchError(
                BM_IDENTITY_INVALID,
                f"tracked path bytes do not match the pinned digest: {path}",
            )
        verified.append(VerifiedBlob(path=path, sha256=observed))

    return GitSourceIdentity(
        commit=commit, tree_sha=tree_sha, files=tuple(verified)
    )


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
