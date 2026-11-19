"""Closed operator outcome v2, separate from the frozen BM-01 registry.

The operator adds a new envelope version without changing any v1 schema byte or
registry member. This module loads one fixed package resource; configuration
cannot select a schema path, remote reference, or additional payload kind.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import schemas
from .errors import BM_SCHEMA_INVALID, BenchError

OPERATOR_PAYLOAD_KINDS = frozenset({
    "official-experiment-inspection",
    "official-authorization-inputs",
    "official-operation-result",
    "synthetic-operation-result",
    "synthetic-operation-stage",
})
OPERATOR_SCHEMA_PATH = Path(__file__).resolve().parent / "operator_schemas" / "outcome.v2.schema.json"


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    # Reuse the local-only schema reader and meta-schema checks, without adding
    # this path to the historical registry or permitting network resolution.
    schema = schemas._load_schema_file(OPERATOR_SCHEMA_PATH, "outcome", 2)
    return Draft202012Validator(schema)


def validate_operator_outcome(document: Any) -> None:
    """Validate the fixed v2 shape with deterministic typed schema failures."""

    errors = sorted(_validator().iter_errors(document),
        key=lambda error: (schemas._format_path(error.absolute_path), error.message))
    if errors:
        first = errors[0]
        raise BenchError(BM_SCHEMA_INVALID, first.message,
            field_path=schemas._format_path(first.absolute_path) or None)


__all__ = ["OPERATOR_PAYLOAD_KINDS", "validate_operator_outcome"]
