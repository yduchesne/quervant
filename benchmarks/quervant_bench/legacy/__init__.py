"""Read-only registry of legacy benchmarking formats.

The registry is **data**, not an implementation. It records historical schema
literals verbatim so that later milestones can build read-only adapters without
rewriting historical identities. BM-01 never claims parity and never marks a
legacy format ``verified``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config.errors import BM_SCHEMA_INVALID, BenchError

REGISTRY_PATH = Path(__file__).resolve().parent / "legacy_formats.v1.json"

READER_STATUSES: tuple[str, ...] = (
    "original_tool_only",
    "planned_read_only_adapter",
    "unsupported_documented",
)
FUTURE_DISPOSITIONS: tuple[str, ...] = (
    "retain_live",
    "read_only_adapter_later",
    "preserve_archive",
    "candidate_migrate_later",
    "external_not_present",
)
EQUIVALENCE_STATUSES: tuple[str, ...] = (
    "not_verified",
    "evidence_unavailable",
)


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the legacy-format registry."""

    source = Path(path) if path is not None else REGISTRY_PATH
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - packaging guard
        raise BenchError(BM_SCHEMA_INVALID, "legacy format registry is missing") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchError(
            BM_SCHEMA_INVALID, "legacy format registry is not valid JSON"
        ) from exc
    validate_registry(data)
    return data


def validate_registry(data: object) -> None:
    """Validate the registry's structure and BM-01 prohibition on parity claims."""

    if not isinstance(data, dict):
        raise BenchError(BM_SCHEMA_INVALID, "legacy registry must be an object")
    if data.get("kind") != "legacy-format-registry":
        raise BenchError(
            BM_SCHEMA_INVALID,
            "legacy registry kind must be 'legacy-format-registry'",
        )
    if data.get("registry_version") != 1:
        raise BenchError(BM_SCHEMA_INVALID, "legacy registry version must be 1")
    source_commit = data.get("source_baseline_sha")
    if not isinstance(source_commit, str) or len(source_commit) != 40:
        raise BenchError(
            BM_SCHEMA_INVALID,
            "legacy registry source_baseline_sha must be a 40-character commit",
        )
    formats = data.get("formats")
    if not isinstance(formats, list) or not formats:
        raise BenchError(BM_SCHEMA_INVALID, "legacy registry must list formats")

    seen: set[tuple[str, int]] = set()
    for index, entry in enumerate(formats):
        if not isinstance(entry, dict):
            raise BenchError(
                BM_SCHEMA_INVALID, f"formats[{index}] must be an object"
            )
        format_id = entry.get("legacy_format_id")
        version = entry.get("legacy_version")
        if not isinstance(format_id, str) or not format_id:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"formats[{index}].legacy_format_id must be a non-empty string",
            )
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"formats[{index}].legacy_version must be a positive integer",
            )
        key = (format_id, version)
        if key in seen:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"duplicate legacy format registration: {format_id} v{version}",
            )
        seen.add(key)
        paths = entry.get("source_paths")
        if (
            not isinstance(paths, list)
            or not paths
            or not all(isinstance(item, str) and item for item in paths)
        ):
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"formats[{index}].source_paths must be a non-empty string array",
            )
        if entry.get("reader_status") not in READER_STATUSES:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"formats[{index}].reader_status is not recognised",
            )
        if entry.get("future_disposition") not in FUTURE_DISPOSITIONS:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"formats[{index}].future_disposition is not recognised",
            )
        equivalence = entry.get("new_equivalence_status")
        if equivalence == "verified":
            raise BenchError(
                BM_SCHEMA_INVALID,
                "BM-01 must not claim verified legacy/new equivalence",
            )
        if equivalence not in EQUIVALENCE_STATUSES:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"formats[{index}].new_equivalence_status is not recognised",
            )


def registry_format_ids(path: Path | None = None) -> dict[str, int]:
    """Return ``legacy_format_id -> legacy_version`` for the checked-in registry."""

    data = load_registry(path)
    return {
        entry["legacy_format_id"]: entry["legacy_version"]
        for entry in data["formats"]
    }
