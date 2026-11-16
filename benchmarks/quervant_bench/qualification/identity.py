"""Source-file-set identity and independently pinned trust anchors.

The roster is deterministic and closed: tracked Python modules of the benchmark
package, the CI workflow, the package manifest, the script test runner and every
BM-01 schema. Untracked production Python (or schema) files fail closed instead of
being silently omitted from the digest.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Sequence

from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest
from ..evidence.hashing import source_file_set_digest
from ..evidence.paths import require_safe_root

SOURCE_DIRECTORIES: tuple[str, ...] = (
    "benchmarks/quervant_bench/config",
    "benchmarks/quervant_bench/evidence",
    "benchmarks/quervant_bench/host",
    "benchmarks/quervant_bench/execution",
    "benchmarks/quervant_bench/protocol",
    "benchmarks/quervant_bench/analysis",
    "benchmarks/quervant_bench/verification",
    "benchmarks/quervant_bench/qualification",
    "benchmarks/quervant_bench/migrations",
    "benchmarks/quervant_bench/tests",
)
SCHEMA_DIRECTORY = "benchmarks/quervant_bench/config/schemas"
EXTRA_SOURCE_FILES: tuple[str, ...] = (
    ".github/workflows/ci.yml",
    "benchmarks/pyproject.toml",
    "benchmarks/scripts/test-scripts.sh",
)

_GIT_ENVIRONMENT = {"GIT_TERMINAL_PROMPT": "0"}


def require_anchor(value: object, field: str) -> str:
    """Return a validated pinned digest or a typed ``EVIDENCE_UNAVAILABLE``."""

    if value is None or (isinstance(value, str) and not value):
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            f"{field} must be an independently pinned digest",
            field_path=field,
        )
    return validate_digest(value, field)


def _git(repo_root: Path, arguments: Sequence[str]) -> bytes:
    environment = dict(os.environ)
    environment.update(_GIT_ENVIRONMENT)
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
            env=environment,
        )
    except OSError as exc:  # pragma: no cover - git is a test prerequisite
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE, "git is required to enumerate the source roster"
        ) from exc
    if completed.returncode != 0:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the source root is not a usable git work tree",
            field_path="source_root",
        )
    return completed.stdout


def require_repository_root(source_root: Path) -> Path:
    """Validate ``source_root`` as the root of its own git work tree."""

    if not isinstance(source_root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT, "source_root must be a Path", field_path="source_root"
        )
    root = require_safe_root(source_root)
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:  # pragma: no cover - defensive
        raise BenchError(
            BM_UNSAFE_INPUT, "the source root cannot be resolved"
        ) from exc
    toplevel = _git(resolved, ["rev-parse", "--show-toplevel"]).decode("utf-8").strip()
    if not toplevel:
        raise BenchError(BM_UNSAFE_INPUT, "the git work tree root is unavailable")
    try:
        discovered = Path(toplevel).resolve(strict=True)
    except OSError as exc:  # pragma: no cover - defensive
        raise BenchError(
            BM_UNSAFE_INPUT, "the git work tree root cannot be resolved"
        ) from exc
    if discovered != resolved:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "source_root must be the repository (git work tree) root",
            field_path="source_root",
        )
    return resolved


def _tracked_paths(root: Path) -> frozenset[str]:
    arguments = ["ls-files", "-z", "--", *SOURCE_DIRECTORIES, SCHEMA_DIRECTORY]
    arguments.extend(EXTRA_SOURCE_FILES)
    output = _git(root, arguments)
    return frozenset(
        entry for entry in output.decode("utf-8").split("\x00") if entry
    )


def _reject_unsafe_entry(root: Path, relative: str) -> None:
    info = os.lstat(root / relative)
    if stat.S_ISLNK(info.st_mode):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "source roster entries must not be symbolic links",
            reference=relative,
        )
    if not stat.S_ISREG(info.st_mode):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "source roster entries must be regular files",
            reference=relative,
        )


def _walk_production_python(root: Path) -> set[str]:
    """Collect on-disk ``*.py`` beneath the roster directories, failing on links."""

    found: set[str] = set()
    for directory in SOURCE_DIRECTORIES:
        base = root / directory
        if not base.is_dir() or base.is_symlink():
            raise BenchError(
                BM_UNSAFE_INPUT,
                "a source roster directory is missing or unsafe",
                reference=directory,
            )
        for current, dirnames, filenames in os.walk(base, followlinks=False):
            current_path = Path(current)
            for name in list(dirnames):
                candidate = current_path / name
                if candidate.is_symlink():
                    raise BenchError(
                        BM_UNSAFE_INPUT,
                        "source roster directories must not contain symbolic links",
                        reference=str(candidate.relative_to(root)),
                    )
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                relative = str((current_path / name).relative_to(root))
                found.add(relative)
    return found


def _walk_schema_json(root: Path) -> set[str]:
    base = root / SCHEMA_DIRECTORY
    if not base.is_dir() or base.is_symlink():
        raise BenchError(
            BM_UNSAFE_INPUT, "the BM-01 schema directory is missing or unsafe"
        )
    found: set[str] = set()
    for name in sorted(os.listdir(base)):
        candidate = base / name
        if candidate.is_symlink():
            raise BenchError(
                BM_UNSAFE_INPUT,
                "the BM-01 schema directory must not contain symbolic links",
                reference=f"{SCHEMA_DIRECTORY}/{name}",
            )
        if name.endswith(".json"):
            found.add(f"{SCHEMA_DIRECTORY}/{name}")
    return found


def source_roster(source_root: Path) -> tuple[str, ...]:
    """Return the exact, sorted, tracked BM-06 source-file-set roster."""

    root = require_repository_root(source_root)
    tracked = _tracked_paths(root)

    roster: set[str] = set()
    for path in tracked:
        if path in EXTRA_SOURCE_FILES:
            roster.add(path)
            continue
        if path.startswith(SCHEMA_DIRECTORY + "/") and path.endswith(".json"):
            roster.add(path)
            continue
        if path.endswith(".py") and any(
            path.startswith(directory + "/") for directory in SOURCE_DIRECTORIES
        ):
            roster.add(path)

    untracked_python = _walk_production_python(root) - tracked
    if untracked_python:
        offender = sorted(untracked_python)[0]
        raise BenchError(
            BM_UNSAFE_INPUT,
            "untracked production Python file is outside the frozen source roster",
            reference=offender,
        )
    untracked_schema = _walk_schema_json(root) - tracked
    if untracked_schema:
        offender = sorted(untracked_schema)[0]
        raise BenchError(
            BM_UNSAFE_INPUT,
            "untracked BM-01 schema file is outside the frozen source roster",
            reference=offender,
        )
    for extra in EXTRA_SOURCE_FILES:
        if extra not in tracked or not (root / extra).is_file():
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                "a mandatory source roster file is missing or untracked",
                reference=extra,
            )
    if not roster:
        raise BenchError(BM_EVIDENCE_UNAVAILABLE, "the source roster is empty")
    for relative in sorted(roster):
        _reject_unsafe_entry(root, relative)
    return tuple(sorted(roster))


def compute_source_set_digest(source_root: Path) -> str:
    """Hash the exact frozen source roster."""

    root = require_repository_root(source_root)
    return source_file_set_digest(root, source_roster(root))


def verify_source_identity(source_root: Path, expected_source_set_digest: str) -> str:
    """Rehash the source roster and compare it with the pinned anchor."""

    anchor = require_anchor(expected_source_set_digest, "expected_source_set_digest")
    digest = compute_source_set_digest(source_root)
    if digest != anchor:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the source file set does not match the pinned source anchor",
            field_path="expected_source_set_digest",
        )
    return digest


__all__ = [
    "EXTRA_SOURCE_FILES",
    "SCHEMA_DIRECTORY",
    "SOURCE_DIRECTORIES",
    "compute_source_set_digest",
    "require_anchor",
    "require_repository_root",
    "source_roster",
    "verify_source_identity",
]
