"""Strict YAML/JSON reading and canonical JSON encoding.

Contract summary (see ``docs/pr-artifacts/bm-01/schema-and-cli-contract.md``):

* input text must be strict UTF-8 without a byte-order mark;
* JSON duplicate keys, ``NaN``/``Infinity`` and non-finite numbers are rejected;
* YAML must be a safe JSON-compatible subset: no anchors, aliases, merge keys,
  custom tags, timestamps, binary, sets, cyclic structures or multiple documents;
* documents are bounded in size, nesting depth, node count and scalar length;
* ``canonical_payload_bytes`` sorts object keys, preserves array order and never
  normalises Unicode;
* content digests are ``sha256:``-prefixed lower-case hexadecimal.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .errors import (
    BM_DUPLICATE_KEY,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)

MAX_DOCUMENT_BYTES = 1_048_576
MAX_NESTING_DEPTH = 32
MAX_COLLECTION_NODES = 10_000
MAX_SCALAR_BYTES = 4_096

_JSON_EXTENSIONS = frozenset({".json"})
_YAML_EXTENSIONS = frozenset({".yaml", ".yml"})

_ALLOWED_YAML_TAGS = frozenset(
    {
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:float",
        "tag:yaml.org,2002:bool",
        "tag:yaml.org,2002:null",
        "tag:yaml.org,2002:seq",
        "tag:yaml.org,2002:map",
    }
)


def decode_text(data: bytes) -> str:
    """Decode ``data`` as strict UTF-8 and enforce the document size budget."""

    if not isinstance(data, (bytes, bytearray)):
        raise BenchError(BM_UNSAFE_INPUT, "document input must be bytes")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"document exceeds the {MAX_DOCUMENT_BYTES}-byte limit",
        )
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BenchError(BM_UNSAFE_INPUT, "document is not valid UTF-8") from exc
    if text.startswith("\ufeff"):
        raise BenchError(BM_UNSAFE_INPUT, "document starts with a byte-order mark")
    return text


def _reject_constant(name: str) -> Any:
    raise BenchError(BM_UNSAFE_INPUT, f"non-finite JSON constant rejected: {name}")


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BenchError(BM_DUPLICATE_KEY, f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def loads_json(text: str) -> Any:
    """Parse strict JSON text (duplicate keys and non-finite numbers rejected)."""

    try:
        document = json.loads(
            text,
            object_pairs_hook=_no_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except BenchError:
        raise
    except json.JSONDecodeError as exc:
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"invalid JSON document at line {exc.lineno} column {exc.colno}",
        ) from exc
    _require_json_tree(document)
    return document


class _StrictSafeLoader(yaml.SafeLoader):
    """``SafeLoader`` that refuses aliases, anchors and merge keys."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            raise BenchError(BM_UNSAFE_INPUT, "YAML aliases are not permitted")
        event = self.peek_event()
        if getattr(event, "anchor", None) is not None:
            raise BenchError(BM_UNSAFE_INPUT, "YAML anchors are not permitted")
        return super().compose_node(parent, index)

    def flatten_mapping(self, node: Any) -> None:
        for key_node, _value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise BenchError(BM_UNSAFE_INPUT, "YAML merge keys are not permitted")
        # Deliberately do not call ``super().flatten_mapping``: safe documents
        # contain no merge keys, so flattening must never run.
        return None

    def construct_mapping(self, node: Any, deep: bool = False) -> Any:
        if not isinstance(node, yaml.MappingNode):
            raise BenchError(BM_SCHEMA_INVALID, "expected a YAML mapping node")
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise BenchError(BM_UNSAFE_INPUT, "YAML merge keys are not permitted")
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise BenchError(BM_SCHEMA_INVALID, "YAML mapping keys must be strings")
            if key in mapping:
                raise BenchError(BM_DUPLICATE_KEY, f"duplicate YAML mapping key: {key!r}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _scan_yaml_events(text: str) -> None:
    """Reject unsafe YAML parse events/tags before construction."""

    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.AliasEvent):
                raise BenchError(BM_UNSAFE_INPUT, "YAML aliases are not permitted")
            anchor = getattr(event, "anchor", None)
            if anchor is not None:
                raise BenchError(BM_UNSAFE_INPUT, "YAML anchors are not permitted")
            tag = getattr(event, "tag", None)
            if tag is not None and tag not in _ALLOWED_YAML_TAGS:
                raise BenchError(
                    BM_UNSAFE_INPUT,
                    f"YAML tag is outside the safe JSON subset: {tag}",
                )
    except BenchError:
        raise
    except yaml.YAMLError as exc:
        raise BenchError(BM_SCHEMA_INVALID, "invalid YAML document") from exc


def loads_yaml(text: str) -> Any:
    """Parse the safe YAML subset into JSON-compatible Python values."""

    _scan_yaml_events(text)
    try:
        documents = list(yaml.load_all(text, Loader=_StrictSafeLoader))
    except BenchError:
        raise
    except yaml.YAMLError as exc:
        raise BenchError(BM_SCHEMA_INVALID, "invalid YAML document") from exc
    if len(documents) != 1:
        raise BenchError(BM_UNSAFE_INPUT, "exactly one YAML document is required")
    document = documents[0]
    _require_json_tree(document)
    return document


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_json_tree(document: Any) -> None:
    """Validate bounds and JSON compatibility of a parsed document tree."""

    nodes = 0
    stack: list[tuple[Any, int]] = [(document, 0)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, dict):
            if depth + 1 > MAX_NESTING_DEPTH:
                raise BenchError(
                    BM_UNSAFE_INPUT,
                    f"document nesting depth exceeds {MAX_NESTING_DEPTH}",
                )
            nodes += 1
            if nodes > MAX_COLLECTION_NODES:
                raise BenchError(
                    BM_UNSAFE_INPUT,
                    f"document exceeds {MAX_COLLECTION_NODES} collection nodes",
                )
            for key, child in value.items():
                if not isinstance(key, str):
                    raise BenchError(BM_SCHEMA_INVALID, "object keys must be strings")
                _require_scalar_bounds(key)
                stack.append((child, depth + 1))
        elif isinstance(value, list):
            if depth + 1 > MAX_NESTING_DEPTH:
                raise BenchError(
                    BM_UNSAFE_INPUT,
                    f"document nesting depth exceeds {MAX_NESTING_DEPTH}",
                )
            nodes += 1
            if nodes > MAX_COLLECTION_NODES:
                raise BenchError(
                    BM_UNSAFE_INPUT,
                    f"document exceeds {MAX_COLLECTION_NODES} collection nodes",
                )
            for child in value:
                stack.append((child, depth + 1))
        elif isinstance(value, str):
            _require_scalar_bounds(value)
        elif value is None or isinstance(value, bool):
            continue
        elif _is_int(value):
            continue
        elif isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise BenchError(BM_UNSAFE_INPUT, "non-finite YAML number rejected")
        else:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"value type outside the safe JSON subset: {type(value).__name__}",
            )


def _require_scalar_bounds(value: str) -> None:
    if len(value.encode("utf-8")) > MAX_SCALAR_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"scalar exceeds the {MAX_SCALAR_BYTES}-byte limit",
        )


def load_document(path: Path) -> Any:
    """Read and strictly parse one ``.json``/``.yaml``/``.yml`` document."""

    suffix = path.suffix.lower()
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise BenchError(BM_SCHEMA_INVALID, "document does not exist") from exc
    text = decode_text(data)
    if suffix in _JSON_EXTENSIONS:
        return loads_json(text)
    if suffix in _YAML_EXTENSIONS:
        return loads_yaml(text)
    raise BenchError(BM_SCHEMA_INVALID, f"unsupported document extension: {suffix!r}")


def canonical_payload_bytes(document: Any) -> bytes:
    """Return canonical JSON bytes: sorted keys, no whitespace, UTF-8."""

    try:
        encoded = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise BenchError(
            BM_SCHEMA_INVALID,
            "document is not canonically encodable",
        ) from exc
    return encoded.encode("utf-8")


def canonical_document_bytes(document: Any) -> bytes:
    """Return canonical payload bytes plus exactly one trailing newline."""

    return canonical_payload_bytes(document) + b"\n"


def content_digest(document: Any) -> str:
    """Return ``sha256:<hex>`` over the canonical payload bytes of ``document``."""

    return "sha256:" + hashlib.sha256(canonical_payload_bytes(document)).hexdigest()


def sha256_prefix(data: bytes) -> str:
    """Return ``sha256:<hex>`` over raw bytes (legacy bare-hex stays elsewhere)."""

    return "sha256:" + hashlib.sha256(data).hexdigest()
