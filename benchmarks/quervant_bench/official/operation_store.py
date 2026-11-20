"""Small, append-only operator journal outside the admitted raw directory.

Journal entries are progress records, never admission or acceptance capabilities.
Readers re-open raw evidence and derive the relevant stage independently. Equal
derived bytes may be reused; a conflicting result is preserved and rejected.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import canonical_document_bytes
from ..config.errors import BM_PUBLICATION_CONFLICT, BM_UNSAFE_INPUT, BenchError
from ..evidence.paths import open_regular_beneath, require_safe_root, validate_relative_member
from ..evidence.publication import _fsync_directory, _write_exclusive
from .operation_config import absolute_path


def create_directory(path: Path, *, exclusive: bool = False) -> Path:
    candidate = absolute_path(str(path), "output_path")
    try:
        candidate.mkdir(mode=0o700, parents=True, exist_ok=not exclusive)
    except FileExistsError as exc:
        raise BenchError(BM_PUBLICATION_CONFLICT, "the output already exists; use a new run identity") from exc
    except OSError as exc:
        raise BenchError(BM_UNSAFE_INPUT, "the output directory cannot be created") from exc
    return require_safe_root(candidate)


def write_record(root: Path, name: str, document: Mapping[str, Any], *, reuse: bool = False) -> str:
    """Publish one durable canonical record without replacing any previous bytes."""

    directory = require_safe_root(Path(root))
    member = validate_relative_member(name)
    if "/" in member:
        raise BenchError(BM_UNSAFE_INPUT, "journal record names must have one component")
    payload = canonical_document_bytes(dict(document))
    path = directory / member
    if os.path.lexists(path):
        if reuse:
            with open_regular_beneath(directory, member) as handle:
                existing = handle.read(len(payload) + 1)
            if existing == payload:
                return "REUSED_VERIFIED"
        raise BenchError(BM_PUBLICATION_CONFLICT, "a prior stage record differs or is incomplete", reference=member)
    _write_exclusive(path, payload)
    _fsync_directory(directory)
    return "CREATED"


class EventJournal:
    """One process writes a monotonically numbered, exclusive event sequence."""

    def __init__(self, root: Path) -> None:
        self.root = require_safe_root(root)
        self.number = 0

    def __call__(self, event: Mapping[str, Any]) -> None:
        self.number += 1
        write_record(self.root, f"event-{self.number:04d}.json", dict(event))
