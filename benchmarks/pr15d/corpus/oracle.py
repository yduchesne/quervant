#!/usr/bin/env python3
"""Independent, engine-neutral oracle for the frozen PR15D v1 corpus.

This module is deliberately standard-library only. It never imports an engine
adapter, a harness timing helper or a benchmark report writer, so it can be used
to recompute the expected exact hit sets from the raw TSV bytes alone.
"""

from __future__ import annotations

import hashlib
import json
import os

SCHEMA_CORPUS = "pr15d-corpus-v1"
WORKLOAD = "pr15d_v1"
FIELDS = ("doc_id", "key", "group", "body", "payload")
HEADER = "\t".join(FIELDS)
N_VALUES = (10000, 100000)
K_VALUES = (10, 100)

# (class name, field, term)
CLASSES = (
    ("absent", "key", "never"),
    ("rare", "key", "singleton"),
    ("medium", "group", "medium"),
    ("common", "key", "common"),
)

_FIELD_POSITION = {"doc_id": 0, "key": 1, "group": 2, "body": 3, "payload": 4}


class CorpusError(Exception):
    """A precise, typed corpus/oracle rejection."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def corpus_filename(n: int) -> str:
    return f"{WORKLOAD}_N{n}.tsv"


def manifest_filename() -> str:
    return f"{WORKLOAD}_manifest.json"


def row_values(i: int) -> tuple[str, str, str, str, str]:
    """Return the frozen row formula for logical index ``i``."""
    doc_id = "d%08d" % i
    if i == 0:
        key = "singleton"
    elif i % 2 == 0:
        key = "common"
    else:
        key = "other"
    group = "medium" if i % 8 == 0 else "different"
    body = "alpha beta" if i % 2 == 0 else "gamma delta"
    payload = "payload-%08d" % i
    return doc_id, key, group, body, payload


def build_tsv_text(n: int) -> str:
    """Return the deterministic TSV text for ``n`` documents."""
    if n <= 0:
        raise CorpusError("invalid_size", f"n must be positive: {n}")
    lines = [HEADER]
    lines.extend("\t".join(row_values(i)) for i in range(n))
    return "\n".join(lines) + "\n"


def build_row_formula(n: int) -> list[tuple[str, str, str, str, str]]:
    return [row_values(i) for i in range(n)]


def canonical_json_bytes(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_rows(rows: list[tuple[str, str, str, str, str]], expected_n: int | None):
    seen: set[str] = set()
    previous = ""
    for line_number, row in enumerate(rows, start=2):
        if len(row) != len(FIELDS):
            raise CorpusError(
                "row_arity", f"line {line_number}: expected 5 columns, found {len(row)}"
            )
        for value in row:
            if "\t" in value or "\n" in value or "\r" in value:
                raise CorpusError(
                    "embedded_delimiter", f"line {line_number}: tab/newline in value"
                )
            if not value.isascii():
                raise CorpusError(
                    "non_ascii", f"line {line_number}: value is not ASCII"
                )
        doc_id = row[0]
        if doc_id in seen:
            raise CorpusError("duplicate_doc_id", f"line {line_number}: {doc_id}")
        if previous and doc_id <= previous:
            raise CorpusError(
                "doc_id_not_increasing",
                f"line {line_number}: {doc_id} <= {previous}",
            )
        seen.add(doc_id)
        previous = doc_id
    if expected_n is not None and len(rows) != expected_n:
        raise CorpusError(
            "row_count", f"expected {expected_n} rows, found {len(rows)}"
        )


def parse_tsv_text(text: str, expected_n: int | None = None) -> list[tuple[str, str, str, str, str]]:
    """Strictly parse TSV text, refusing malformed input before any adapter launch."""
    if text.endswith("\r\n") or "\r" in text:
        raise CorpusError("carriage_return", "only \\n line endings are accepted")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or lines[0] != HEADER:
        raise CorpusError("header", f"expected header {HEADER!r}")
    rows: list[tuple[str, str, str, str, str]] = []
    for line_number, line in enumerate(lines[1:], start=2):
        row = tuple(line.split("\t"))
        if len(row) != len(FIELDS):
            raise CorpusError(
                "row_arity", f"line {line_number}: expected 5 columns, found {len(row)}"
            )
        rows.append(row)  # type: ignore[arg-type]
    _validate_rows(rows, expected_n)
    return rows


def load_tsv(path: str, expected_n: int | None = None) -> list[tuple[str, str, str, str, str]]:
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            text = handle.read()
    except OSError as error:
        raise CorpusError("unreadable_corpus", f"{path}: {error}") from error
    return parse_tsv_text(text, expected_n=expected_n)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CorpusError("unreadable_corpus", f"{path}: {error}") from error
    return digest.hexdigest()


def enumerate_matches(rows, field: str, term: str) -> list[str]:
    """Return matching ``doc_id`` values in ascending lexical order."""
    if field not in ("key", "group"):
        raise CorpusError("unknown_field", f"field {field!r} is not searchable")
    position = _FIELD_POSITION[field]
    matches = [row[0] for row in rows if row[position] == term]
    if matches != sorted(matches):
        raise CorpusError("unsorted_matches", "source rows are not doc_id ordered")
    return matches


def expected(rows, field: str, term: str, k: int) -> dict:
    if k <= 0:
        raise CorpusError("invalid_k", f"k must be positive: {k}")
    matches = enumerate_matches(rows, field, term)
    return {"total_hits": len(matches), "doc_ids": matches[:k]}


def workload_id(n: int, class_name: str, k: int) -> str:
    return f"{WORKLOAD}/{n}/{class_name}/k{k}"


def query_matrix() -> list[dict]:
    """The frozen 16 mandatory query descriptors (N x class x K)."""
    queries = []
    for n in N_VALUES:
        for class_name, field, term in CLASSES:
            for k in K_VALUES:
                queries.append(
                    {
                        "id": workload_id(n, class_name, k),
                        "n": n,
                        "class": class_name,
                        "field": field,
                        "term": term,
                        "k": k,
                    }
                )
    return queries


def build_manifest(corpus_dir: str) -> dict:
    """Compute the complete manifest from already-written TSV files."""
    corpora = []
    rows_by_n: dict[int, list] = {}
    for n in N_VALUES:
        path = os.path.join(corpus_dir, corpus_filename(n))
        rows = load_tsv(path, expected_n=n)
        rows_by_n[n] = rows
        corpora.append(
            {
                "n": n,
                "rows": len(rows),
                "path": corpus_filename(n),
                "sha256": sha256_file(path),
                "bytes": os.path.getsize(path),
            }
        )
    queries = []
    for descriptor in query_matrix():
        result = expected(
            rows_by_n[descriptor["n"]],
            descriptor["field"],
            descriptor["term"],
            descriptor["k"],
        )
        descriptor = dict(descriptor)
        descriptor["total_hits"] = result["total_hits"]
        descriptor["doc_ids"] = result["doc_ids"]
        queries.append(descriptor)
    return {
        "schema": SCHEMA_CORPUS,
        "workload": WORKLOAD,
        "fields": list(FIELDS),
        "n_values": list(N_VALUES),
        "k_values": list(K_VALUES),
        "classes": [
            {"name": name, "field": field, "term": term}
            for name, field, term in CLASSES
        ],
        "corpora": corpora,
        "queries": queries,
    }


def verify_corpus(corpus_dir: str, manifest: dict) -> list[dict]:
    """Return a list of precise errors; an empty list means fully verified."""
    errors: list[dict] = []

    def reject(code: str, detail: str):
        errors.append({"code": code, "detail": detail})

    if manifest.get("schema") != SCHEMA_CORPUS:
        reject("schema_mismatch", f"expected {SCHEMA_CORPUS}")
    if manifest.get("workload") != WORKLOAD:
        reject("workload_mismatch", f"expected {WORKLOAD}")
    if manifest.get("fields") != list(FIELDS):
        reject("field_mismatch", "manifest field list differs from the frozen contract")
    if manifest.get("n_values") != list(N_VALUES):
        reject("n_values_mismatch", "manifest N values differ from the frozen matrix")
    if manifest.get("k_values") != list(K_VALUES):
        reject("k_values_mismatch", "manifest K values differ from the frozen matrix")

    declared = {entry.get("n"): entry for entry in manifest.get("corpora", [])}
    if sorted(declared) != list(N_VALUES):
        reject("corpus_set", "manifest corpus set differs from the frozen matrix")
        return errors

    rows_by_n: dict[int, list] = {}
    for n in N_VALUES:
        entry = declared[n]
        path = os.path.join(corpus_dir, corpus_filename(n))
        try:
            actual_sha = sha256_file(path)
        except CorpusError as error:
            reject(error.code, error.detail)
            continue
        if actual_sha != entry.get("sha256"):
            reject(
                "corpus_digest_mismatch",
                f"N={n}: manifest {entry.get('sha256')} != actual {actual_sha}",
            )
        try:
            rows = load_tsv(path, expected_n=n)
        except CorpusError as error:
            reject(error.code, error.detail)
            continue
        rows_by_n[n] = rows
        if os.path.getsize(path) != entry.get("bytes"):
            reject("corpus_byte_count", f"N={n}: byte count differs from manifest")
        if len(rows) != entry.get("rows"):
            reject("corpus_row_count", f"N={n}: row count differs from manifest")

    expected_queries = {query["id"]: query for query in query_matrix()}
    declared_queries = {}
    for query in manifest.get("queries", []):
        query_id = query.get("id")
        if query_id in declared_queries:
            reject("duplicate_query", f"duplicate query manifest entry {query_id}")
            continue
        declared_queries[query_id] = query
    if sorted(declared_queries) != sorted(expected_queries):
        reject("query_set", "manifest query set differs from the frozen matrix")
    for query_id, descriptor in expected_queries.items():
        entry = declared_queries.get(query_id)
        if entry is None:
            continue
        n = descriptor["n"]
        if n not in rows_by_n:
            continue
        result = expected(
            rows_by_n[n], descriptor["field"], descriptor["term"], descriptor["k"]
        )
        if entry.get("total_hits") != result["total_hits"]:
            reject(
                "oracle_count_mismatch",
                f"{query_id}: manifest {entry.get('total_hits')} != oracle {result['total_hits']}",
            )
        if entry.get("doc_ids") != result["doc_ids"]:
            reject("oracle_ids_mismatch", f"{query_id}: tuple differs from oracle")
        for key in ("n", "class", "field", "term", "k"):
            if entry.get(key) != descriptor[key]:
                reject(
                    "query_descriptor_mismatch",
                    f"{query_id}: {key} differs from the frozen matrix",
                )
    return errors


def load_and_verify(corpus_dir: str) -> tuple[dict, dict[int, list]]:
    """Load the manifest, verify it against the TSV bytes, and return rows."""
    manifest_path = os.path.join(corpus_dir, manifest_filename())
    try:
        with open(manifest_path, "rb") as handle:
            manifest = json.loads(handle.read().decode("utf-8"))
    except OSError as error:
        raise CorpusError("unreadable_manifest", f"{manifest_path}: {error}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorpusError("malformed_manifest", str(error)) from error
    errors = verify_corpus(corpus_dir, manifest)
    if errors:
        first = errors[0]
        raise CorpusError(first["code"], first["detail"])
    rows_by_n = {
        n: load_tsv(os.path.join(corpus_dir, corpus_filename(n)), expected_n=n)
        for n in N_VALUES
    }
    return manifest, rows_by_n


if __name__ == "__main__":  # pragma: no cover - tiny CLI convenience
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Verify a generated PR15D corpus.")
    parser.add_argument("--corpus", required=True)
    args = parser.parse_args()
    try:
        manifest, rows = load_and_verify(args.corpus)
    except CorpusError as error:
        print(f"CORPUS INVALID: {error.code}: {error.detail}", file=sys.stderr)
        sys.exit(2)
    print(
        json.dumps(
            {
                "manifest_sha256": sha256_bytes(canonical_json_bytes(manifest)),
                "rows": {str(n): len(rows[n]) for n in N_VALUES},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
