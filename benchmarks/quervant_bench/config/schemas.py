"""Local registry of frozen JSON Schema (Draft 2020-12) contract documents.

Only checked-in ``quervant_bench/config/schemas/*.vN.schema.json`` files are
loadable. There is no network resolution, no remote ``$ref`` and no dynamic import
of arbitrary Python modules.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .errors import (
    BM_SCHEMA_INVALID,
    BM_SCHEMA_UNSUPPORTED,
    BM_UNSAFE_INPUT,
    BenchError,
)

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
SCHEMA_ID_PREFIX = "urn:quervant-bench:contract:"
SCHEMA_FILENAME_RE = re.compile(
    r"^(?P<kind>[a-z][a-z0-9]*)\.v(?P<version>[1-9][0-9]*)\.schema\.json$"
)


def schema_id(kind: str, version: int) -> str:
    """Return the canonical ``$id`` URN for a contract kind/version."""

    return f"{SCHEMA_ID_PREFIX}{kind}:v{version}"


def _iter_remote_refs(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and not value.startswith("#"):
                found.append(value)
            else:
                found.extend(_iter_remote_refs(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_iter_remote_refs(item))
    return found


def _load_schema_file(path: Path, kind: str, version: int) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"schema file is not valid JSON: {path.name}",
        ) from exc
    if not isinstance(document, dict):
        raise BenchError(BM_SCHEMA_INVALID, f"schema must be an object: {path.name}")
    expected_id = schema_id(kind, version)
    if document.get("$id") != expected_id:
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"schema $id must be {expected_id!r} in {path.name}",
        )
    remote = _iter_remote_refs(document)
    if remote:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"remote $ref is not permitted in {path.name}: {remote[0]}",
        )
    try:
        Draft202012Validator.check_schema(document)
    except SchemaError as exc:
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"schema does not compile: {path.name}: {exc.message}",
        ) from exc
    return document


@lru_cache(maxsize=1)
def registry() -> dict[tuple[str, int], Path]:
    """Return the ``(kind, version) -> path`` allowlist of local schemas."""

    if not SCHEMA_DIR.is_dir():  # pragma: no cover - packaging guard
        raise BenchError(BM_SCHEMA_INVALID, "schema directory is missing")
    registry_map: dict[tuple[str, int], Path] = {}
    for path in sorted(SCHEMA_DIR.iterdir()):
        if not path.is_file():
            continue
        match = SCHEMA_FILENAME_RE.fullmatch(path.name)
        if match is None:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"unexpected schema filename: {path.name}",
            )
        key = (match.group("kind"), int(match.group("version")))
        if key in registry_map:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"duplicate schema registration: {path.name}",
            )
        registry_map[key] = path
    if not registry_map:  # pragma: no cover - packaging guard
        raise BenchError(BM_SCHEMA_INVALID, "no contract schemas are checked in")
    return registry_map


def supported_kinds() -> dict[str, tuple[int, ...]]:
    """Return ``kind -> sorted versions`` for the local allowlist."""

    kinds: dict[str, list[int]] = {}
    for kind, version in registry():
        kinds.setdefault(kind, []).append(version)
    return {kind: tuple(sorted(versions)) for kind, versions in sorted(kinds.items())}


@lru_cache(maxsize=None)
def schema_document(kind: str, version: int) -> dict[str, Any]:
    """Load and compile-check a schema; unsupported pairs fail closed."""

    path = registry().get((kind, version))
    if path is None:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            f"unsupported schema: kind={kind!r} version={version!r}",
        )
    return _load_schema_file(path, kind, version)


@lru_cache(maxsize=None)
def compiled_validator(kind: str, version: int) -> Draft202012Validator:
    """Return a cached compiled validator for a supported schema."""

    return Draft202012Validator(schema_document(kind, version))


def _format_path(parts: Any) -> str:
    rendered = ""
    for part in parts:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += f".{part}" if rendered else str(part)
    return rendered


def validate_schema(kind: str, version: int, document: Any) -> None:
    """Validate shape only; raise the first deterministic schema violation."""

    validator = compiled_validator(kind, version)

    def sort_key(error: Any) -> tuple[str, str]:
        return (_format_path(error.absolute_path), error.message)

    errors = sorted(validator.iter_errors(document), key=sort_key)
    if errors:
        first = errors[0]
        raise BenchError(
            BM_SCHEMA_INVALID,
            first.message,
            field_path=_format_path(first.absolute_path) or None,
        )


def check_all_schemas() -> list[tuple[str, int]]:
    """Compile-check every checked-in schema; return the checked pairs."""

    checked: list[tuple[str, int]] = []
    for kind, version in sorted(registry()):
        schema_document(kind, version)
        checked.append((kind, version))
    return checked
