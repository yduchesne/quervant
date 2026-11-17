"""Closed, independent cross-engine semantic and wire-projection contracts.

This module owns the *only* accepted interpretation of the BM-08 cross-engine
companion documents:

* the pure exact-keyword corpus oracle (a small arithmetic formula, never an
  engine invocation and never a historical PR15D import);
* the closed semantic-comparability ledger that classifies warm keyword-exact
  lanes as comparable and scored / process-cold / throughput classes as excluded;
* the source-only engine identity bindings (raw file bytes, never binaries);
* the untimed adapter **wire projection** contract.

Nothing here schedules, times, spawns, imports or builds an engine. The historical
PR15D adapters all measure with ``Instant``/``System.nanoTime()`` inside their
``query`` operation, so no live ``op=query`` may be issued to produce a projection.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..config.codec import MAX_DOCUMENT_BYTES, content_digest
from ..config.contracts import Lane
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import (
    validate_digest,
    validate_nonnegative_int,
    validate_semantic_id,
)
from ..evidence.paths import open_regular_beneath, require_safe_root

ORACLE_GOLDEN_NAME = "oracle-golden.v1.json"
SEMANTIC_COMPARABILITY_NAME = "semantic-comparability.v1.json"
ENGINE_SOURCE_BINDINGS_NAME = "engine-source-bindings.v1.json"

ORACLE_GOLDEN_KIND = "cross-engine-oracle-golden"
SEMANTIC_COMPARABILITY_KIND = "cross-engine-semantic-comparability"
ENGINE_SOURCE_BINDINGS_KIND = "cross-engine-source-bindings"

ORACLE_ID = "synthetic-contract-oracle"
ORACLE_VERSION = 1
QUERY_SEMANTICS_ID = "cross-engine-exact-keyword"
ADAPTER_SCHEMA = "pr15d-adapter-v1"
WARM_CACHE_REGIME = "warm"
SEARCH_OPERATION = "search"
SOURCE_QUALIFICATION = "SOURCE_ONLY_NOT_BUILT"
ANALYZER_ID = "keyword-exact"

#: The three declared logical engine labels, in the frozen experiment order.
ARM_IDS: tuple[str, ...] = ("quervant", "tantivy", "lucene")
#: Source-binding records are ordered lexically by engine identifier.
ENGINE_IDS: tuple[str, ...] = ("lucene", "quervant", "tantivy")
BASELINE_ARM_ID = "quervant"
CANDIDATE_ORDER: tuple[str, ...] = ("tantivy", "lucene")

#: Frozen PR15D corpus sizes, selectivity classes, searchable field/term pairs
#: and result-set sizes.
CORPUS_SIZES: tuple[int, ...] = (10000, 100000)
CLASSES: tuple[tuple[str, str, str], ...] = (
    ("absent", "key", "never"),
    ("rare", "key", "singleton"),
    ("medium", "group", "medium"),
    ("common", "key", "common"),
)
TOP_K_VALUES: tuple[int, ...] = (10, 100)

#: Closed excluded-class table; only these three literal rows are accepted.
EXCLUDED_CLASSES: tuple[dict[str, str], ...] = (
    {
        "class_id": "index-throughput",
        "status": "DEFERRED",
        "reason": "no-untimed-performance-contract",
    },
    {
        "class_id": "process-cold",
        "status": "DEFERRED",
        "reason": "real-process-cache-state-unverified",
    },
    {
        "class_id": "scored-bm25",
        "status": "NONCOMPARABLE",
        "reason": "ranking-and-scoring-not-equivalent",
    },
)

_LANE_ID_RE = re.compile(r"^n(?P<n>[0-9]{6})-(?P<cls>[a-z]+)-k(?P<k>[0-9]{3})-warm$")
_DOC_ID_RE = re.compile(r"^d[0-9]{8}$")
#: Excluded class identifiers are historical prose labels, not new public slugs,
#: so they are validated structurally and then matched against the frozen table.
_CLASS_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")

MAX_COMPANION_BYTES = MAX_DOCUMENT_BYTES
MAX_SOURCE_FILE_BYTES = 8 * 1024 * 1024

ORACLE_GOLDEN_KEYS = frozenset(
    {"kind", "schema_version", "evidence_origin", "qualification_scope", "rows"}
)
ORACLE_ROW_KEYS = frozenset(
    {
        "lane_id",
        "corpus_size",
        "selectivity_class",
        "field",
        "term",
        "top_k",
        "total_hits",
        "doc_ids",
    }
)
SEMANTIC_COMPARABILITY_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "reference_spec_digest",
        "oracle_golden_digest",
        "engine_source_bindings_digest",
        "comparable_lane_ids",
        "excluded_classes",
    }
)
EXCLUDED_CLASS_KEYS = frozenset({"class_id", "status", "reason"})
ENGINE_SOURCE_BINDINGS_KEYS = frozenset(
    {"kind", "schema_version", "evidence_origin", "qualification_scope", "engines"}
)
ENGINE_ENTRY_KEYS = frozenset(
    {
        "engine_id",
        "adapter_schema",
        "declared_engine_version",
        "analyzer",
        "source_files",
        "source_qualification",
    }
)
SOURCE_FILE_KEYS = frozenset({"path", "byte_length", "sha256"})
REPLY_PROJECTION_KEYS = frozenset(
    {"schema", "engine", "request_id", "status", "total_hits", "doc_ids"}
)
LANE_PARAM_KEYS = frozenset({"corpus_size", "top_k", "selectivity_class", "query_id"})

#: Exact allowlisted source files per engine. Nothing else may be bound.
SOURCE_FILE_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "quervant": (
        "benchmarks/pr15d/adapters/quervant/Cargo.lock",
        "benchmarks/pr15d/adapters/quervant/Cargo.toml",
        "benchmarks/pr15d/adapters/quervant/src/main.rs",
    ),
    "tantivy": (
        "benchmarks/pr15d/adapters/tantivy/Cargo.lock",
        "benchmarks/pr15d/adapters/tantivy/Cargo.toml",
        "benchmarks/pr15d/adapters/tantivy/src/main.rs",
    ),
    "lucene": (
        "benchmarks/pr15d/adapters/lucene/A1-CHECKSUMS.sha256",
        "benchmarks/pr15d/adapters/lucene/build.gradle",
        "benchmarks/pr15d/adapters/lucene/gradle/wrapper/gradle-wrapper.jar",
        "benchmarks/pr15d/adapters/lucene/gradle/wrapper/gradle-wrapper.properties",
        "benchmarks/pr15d/adapters/lucene/gradlew",
        "benchmarks/pr15d/adapters/lucene/gradlew.bat",
        "benchmarks/pr15d/adapters/lucene/settings.gradle",
        "benchmarks/pr15d/adapters/lucene/src/main/java/org/quervant/bench/Adapter.java",
    ),
}

DECLARED_ENGINE_VERSIONS: dict[str, str] = {
    "lucene": "Apache Lucene 9.12.3",
    "quervant": "quervant-core 0.1.0",
    "tantivy": "tantivy 0.22.1",
}

#: Literal pins that must still be present in the original source bytes.
REQUIRED_SOURCE_PINS: tuple[tuple[str, bytes], ...] = (
    (
        "benchmarks/pr15d/adapters/quervant/src/main.rs",
        b'const ENGINE_VERSION: &str = "quervant-core 0.1.0";',
    ),
    (
        "benchmarks/pr15d/adapters/tantivy/Cargo.toml",
        b'tantivy = "=0.22.1"',
    ),
    (
        "benchmarks/pr15d/adapters/tantivy/src/main.rs",
        b'const ENGINE_VERSION: &str = "tantivy 0.22.1";',
    ),
    (
        "benchmarks/pr15d/adapters/lucene/build.gradle",
        b"org.apache.lucene:lucene-core:9.12.3",
    ),
    (
        "benchmarks/pr15d/adapters/lucene/build.gradle",
        b"JavaLanguageVersion.of(21)",
    ),
    (
        "benchmarks/pr15d/adapters/lucene/src/main/java/org/quervant/bench/Adapter.java",
        b'"Apache Lucene 9.12.3"',
    ),
)


def _schema(message: str, field_path: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


def _fail(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _require_closed(value: object, field_path: str, keys: frozenset[str]) -> Mapping:
    if not isinstance(value, Mapping):
        raise _schema(f"{field_path} must be an object", field_path)
    actual = set(value)
    if actual != keys:
        raise _schema(
            f"{field_path} must use the exact closed field set",
            field_path,
        )
    return value


def _require_int(value: object, field_path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _schema(f"{field_path} must be an integer", field_path)
    return value


def _require_exact_int(value: object, field_path: str) -> int:
    """Require a genuine ``int``; ``bool`` is never an acceptable integer."""

    if type(value) is not int:
        raise _schema(f"{field_path} must be an integer", field_path)
    return value


def _require_synthetic_scope(origin: object, scope: object) -> None:
    if origin != "synthetic" or scope != "simulated":
        raise _fail(
            "cross-engine companion documents must remain synthetic/simulated",
            "qualification_scope",
        )


# ---------------------------------------------------------------------------
# Independent exact-keyword corpus oracle
# ---------------------------------------------------------------------------


def lane_id_for(corpus_size: int, selectivity_class: str, top_k: int) -> str:
    """Return the frozen lane identifier for one matrix cell."""

    return "n%06d-%s-k%03d-warm" % (corpus_size, selectivity_class, top_k)


def expected_lane_ids() -> tuple[str, ...]:
    """Return the 16 lexicographically sorted frozen lane identifiers."""

    lane_ids = [
        lane_id_for(corpus_size, selectivity_class, top_k)
        for corpus_size in CORPUS_SIZES
        for selectivity_class, _field, _term in CLASSES
        for top_k in TOP_K_VALUES
    ]
    return tuple(sorted(lane_ids))


def _class_entry(selectivity_class: object) -> tuple[str, str]:
    for name, field, term in CLASSES:
        if name == selectivity_class:
            return field, term
    raise _fail(
        "selectivity_class is outside the frozen exact-keyword matrix",
        "selectivity_class",
    )


def exact_total_hits(corpus_size: int, selectivity_class: str) -> int:
    """Return the frozen PR15D exact-match cardinality for one class."""

    if selectivity_class == "absent":
        return 0
    if selectivity_class == "rare":
        return 1
    if selectivity_class == "medium":
        return corpus_size // 8
    if selectivity_class == "common":
        return corpus_size // 2 - 1
    raise _fail(
        "selectivity_class is outside the frozen exact-keyword matrix",
        "selectivity_class",
    )


def exact_matching_ids(corpus_size: int, selectivity_class: str) -> list[str]:
    """Return the frozen ascending ``doc_id`` match list for one class."""

    if selectivity_class == "absent":
        return []
    if selectivity_class == "rare":
        return ["d%08d" % 0]
    if selectivity_class == "medium":
        return ["d%08d" % index for index in range(0, corpus_size, 8)]
    if selectivity_class == "common":
        return ["d%08d" % index for index in range(2, corpus_size, 2)]
    raise _fail(
        "selectivity_class is outside the frozen exact-keyword matrix",
        "selectivity_class",
    )


def compute_oracle_row(
    corpus_size: int, selectivity_class: str, top_k: int
) -> dict[str, Any]:
    """Recompute one oracle row from the frozen arithmetic formula alone."""

    if corpus_size not in CORPUS_SIZES:
        raise _fail("corpus_size is outside the frozen matrix", "corpus_size")
    if top_k not in TOP_K_VALUES:
        raise _fail("top_k is outside the frozen matrix", "top_k")
    field, term = _class_entry(selectivity_class)
    total = exact_total_hits(corpus_size, selectivity_class)
    matches = exact_matching_ids(corpus_size, selectivity_class)
    if len(matches) != total:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the frozen oracle formula disagrees with its own match list",
            field_path="total_hits",
        )
    return {
        "lane_id": lane_id_for(corpus_size, selectivity_class, top_k),
        "corpus_size": corpus_size,
        "selectivity_class": selectivity_class,
        "field": field,
        "term": term,
        "top_k": top_k,
        "total_hits": total,
        "doc_ids": matches[: min(top_k, total)],
    }


def expected_oracle_rows() -> tuple[dict[str, Any], ...]:
    """Return the independently computed 16 rows in sorted lane order."""

    rows = [
        compute_oracle_row(corpus_size, selectivity_class, top_k)
        for corpus_size in CORPUS_SIZES
        for selectivity_class, _field, _term in CLASSES
        for top_k in TOP_K_VALUES
    ]
    return tuple(sorted(rows, key=lambda row: row["lane_id"]))


def _validate_doc_ids(value: object, field_path: str) -> list[str]:
    if not isinstance(value, list):
        raise _schema(f"{field_path} must be an array", field_path)
    result: list[str] = []
    previous: str | None = None
    for index, item in enumerate(value):
        if not isinstance(item, str) or _DOC_ID_RE.fullmatch(item) is None:
            raise _fail(
                f"{field_path}[{index}] must be a lower-case dNNNNNNNN document ID",
                field_path,
            )
        if previous is not None and not item > previous:
            raise _fail(
                f"{field_path} must be strictly ascending and unique", field_path
            )
        previous = item
        result.append(item)
    return result


def validate_oracle_golden(document: object) -> tuple[dict[str, Any], ...]:
    """Validate the independent oracle golden against the frozen formula."""

    doc = _require_closed(document, "oracle-golden", ORACLE_GOLDEN_KEYS)
    if doc["kind"] != ORACLE_GOLDEN_KIND:
        raise _schema("oracle-golden kind is invalid", "kind")
    if _require_int(doc["schema_version"], "schema_version") != 1:
        raise _schema("oracle-golden schema_version is invalid", "schema_version")
    _require_synthetic_scope(doc["evidence_origin"], doc["qualification_scope"])
    raw_rows = doc["rows"]
    if not isinstance(raw_rows, list):
        raise _schema("oracle-golden rows must be an array", "rows")
    if len(raw_rows) != len(expected_lane_ids()):
        raise _fail(
            "oracle-golden must declare exactly the 16 frozen matrix rows", "rows"
        )
    rows: list[dict[str, Any]] = []
    seen: list[str] = []
    for index, raw_row in enumerate(raw_rows):
        field_path = f"rows[{index}]"
        row = _require_closed(raw_row, field_path, ORACLE_ROW_KEYS)
        lane_id = validate_semantic_id(row["lane_id"], f"{field_path}.lane_id")
        corpus_size = _require_int(row["corpus_size"], f"{field_path}.corpus_size")
        top_k = _require_int(row["top_k"], f"{field_path}.top_k")
        total_hits = _require_int(row["total_hits"], f"{field_path}.total_hits")
        selectivity_class = row["selectivity_class"]
        _class_entry(selectivity_class)
        expected = compute_oracle_row(corpus_size, selectivity_class, top_k)
        if lane_id != expected["lane_id"]:
            raise _fail(
                f"{field_path}.lane_id does not encode its own matrix cell",
                f"{field_path}.lane_id",
            )
        if row["field"] != expected["field"] or row["term"] != expected["term"]:
            raise _fail(
                f"{field_path} declares a field/term outside the frozen matrix",
                f"{field_path}.field",
            )
        if total_hits != expected["total_hits"]:
            raise _fail(
                f"{field_path}.total_hits disagrees with the frozen formula",
                f"{field_path}.total_hits",
            )
        doc_ids = _validate_doc_ids(row["doc_ids"], f"{field_path}.doc_ids")
        if doc_ids != expected["doc_ids"]:
            raise _fail(
                f"{field_path}.doc_ids disagrees with the frozen formula",
                f"{field_path}.doc_ids",
            )
        seen.append(lane_id)
        rows.append(expected)
    if seen != sorted(seen) or len(set(seen)) != len(seen):
        raise _fail(
            "oracle-golden rows must be ascending and unique by lane_id", "rows"
        )
    if tuple(seen) != expected_lane_ids():
        raise _fail("oracle-golden must cover exactly the frozen lanes", "rows")
    return tuple(rows)


def oracle_row_for_lane(lane: Lane) -> dict[str, Any]:
    """Derive the reviewed oracle row for one declared BM-01 warm keyword lane."""

    if not isinstance(lane, Lane):
        raise _fail("a validated BM-01 Lane is required", "lane")
    if lane.operation != SEARCH_OPERATION or lane.cache_regime != WARM_CACHE_REGIME:
        raise _fail(
            "only warm keyword-exact search lanes are comparable", "lane.cache_regime"
        )
    params = dict(lane.params)
    if set(params) != LANE_PARAM_KEYS:
        raise _schema(
            "a comparable lane must declare exactly the closed parameter set",
            "lane.params",
        )
    language_class = validate_semantic_id(
        params["selectivity_class"], "lane.params.selectivity_class"
    )
    query_id = validate_semantic_id(params["query_id"], "lane.params.query_id")
    if query_id != lane.lane_id:
        raise _fail(
            "lane.params.query_id must equal the lane identifier",
            "lane.params.query_id",
        )
    corpus_size = _require_int(params["corpus_size"], "lane.params.corpus_size")
    top_k = _require_int(params["top_k"], "lane.params.top_k")
    expected = compute_oracle_row(corpus_size, language_class, top_k)
    if expected["lane_id"] != lane.lane_id:
        raise _fail(
            "lane identifier does not encode its own matrix cell", "lane.lane_id"
        )
    return expected


# ---------------------------------------------------------------------------
# Semantic comparability ledger
# ---------------------------------------------------------------------------


def validate_semantic_comparability(
    document: object,
    *,
    workload_lane_ids: Sequence[str],
    oracle_golden_digest: str,
    engine_source_bindings_digest: str,
    reference_spec_digest: str,
) -> str:
    """Validate the closed comparability ledger; return its content digest."""

    doc = _require_closed(
        document, "semantic-comparability", SEMANTIC_COMPARABILITY_KEYS
    )
    if doc["kind"] != SEMANTIC_COMPARABILITY_KIND:
        raise _schema("semantic-comparability kind is invalid", "kind")
    if _require_int(doc["schema_version"], "schema_version") != 1:
        raise _schema(
            "semantic-comparability schema_version is invalid", "schema_version"
        )
    _require_synthetic_scope(doc["evidence_origin"], doc["qualification_scope"])

    validate_digest(doc["reference_spec_digest"], "reference_spec_digest")
    validate_digest(doc["oracle_golden_digest"], "oracle_golden_digest")
    validate_digest(
        doc["engine_source_bindings_digest"], "engine_source_bindings_digest"
    )
    if doc["oracle_golden_digest"] != oracle_golden_digest:
        raise _fail(
            "semantic-comparability must bind the checked-in oracle golden digest",
            "oracle_golden_digest",
        )
    if doc["engine_source_bindings_digest"] != engine_source_bindings_digest:
        raise _fail(
            "semantic-comparability must bind the checked-in source bindings digest",
            "engine_source_bindings_digest",
        )
    if doc["reference_spec_digest"] != reference_spec_digest:
        raise _fail(
            "semantic-comparability must bind the frozen reference spec digest",
            "reference_spec_digest",
        )

    raw_ids = doc["comparable_lane_ids"]
    if not isinstance(raw_ids, list):
        raise _schema("comparable_lane_ids must be an array", "comparable_lane_ids")
    comparable = [
        validate_semantic_id(item, f"comparable_lane_ids[{index}]")
        for index, item in enumerate(raw_ids)
    ]
    if comparable != list(expected_lane_ids()):
        raise _fail(
            "comparable_lane_ids must be exactly the 16 sorted warm keyword lanes",
            "comparable_lane_ids",
        )
    if sorted(workload_lane_ids) != comparable:
        raise _fail(
            "comparable_lane_ids must equal the measured workload lane set",
            "comparable_lane_ids",
        )

    raw_excluded = doc["excluded_classes"]
    if not isinstance(raw_excluded, list):
        raise _schema("excluded_classes must be an array", "excluded_classes")
    excluded: list[dict[str, str]] = []
    for index, raw_entry in enumerate(raw_excluded):
        field_path = f"excluded_classes[{index}]"
        entry = _require_closed(raw_entry, field_path, EXCLUDED_CLASS_KEYS)
        class_id = entry["class_id"]
        if (
            not isinstance(class_id, str)
            or len(class_id) > 64
            or _CLASS_ID_RE.fullmatch(class_id) is None
        ):
            raise _schema(
                f"{field_path}.class_id must be a lower-case class identifier",
                field_path,
            )
        excluded.append(
            {
                "class_id": class_id,
                "status": entry["status"],
                "reason": entry["reason"],
            }
        )
    if excluded != list(EXCLUDED_CLASSES):
        raise _fail(
            "excluded_classes must be exactly the frozen excluded-class table",
            "excluded_classes",
        )
    return content_digest(dict(doc))


# ---------------------------------------------------------------------------
# Source-only engine identity bindings
# ---------------------------------------------------------------------------


def _read_source_file(repo_root: Path, relative: str) -> bytes:
    try:
        handle = open_regular_beneath(repo_root, relative)
    except BenchError as error:
        if error.code in (BM_IDENTITY_INVALID, BM_SCHEMA_INVALID):
            raise
        raise _fail(
            "a bound adapter source file is missing or unsafe", relative
        ) from error
    with handle:
        payload = handle.read(MAX_SOURCE_FILE_BYTES + 1)
    if len(payload) > MAX_SOURCE_FILE_BYTES:
        raise _fail(
            "a bound adapter source file exceeds the bounded read budget", relative
        )
    return payload


def _validate_source_files(
    engine_id: str, raw_files: object, repo_root: Path
) -> None:
    if not isinstance(raw_files, list) or not raw_files:
        raise _schema(
            f"engines[{engine_id}].source_files must be a non-empty array",
            "source_files",
        )
    allowlist = SOURCE_FILE_ALLOWLIST[engine_id]
    paths: list[str] = []
    for index, raw_entry in enumerate(raw_files):
        field_path = f"engines[{engine_id}].source_files[{index}]"
        entry = _require_closed(raw_entry, field_path, SOURCE_FILE_KEYS)
        path = entry["path"]
        if not isinstance(path, str) or path not in allowlist:
            raise _fail(
                "a bound source path is outside the frozen allowlist", field_path
            )
        if path in paths:
            raise _fail("bound source paths must be unique", field_path)
        paths.append(path)
        byte_length = _require_int(entry["byte_length"], f"{field_path}.byte_length")
        if byte_length < 0:
            raise _schema(f"{field_path}.byte_length must be non-negative", field_path)
        declared_digest = validate_digest(entry["sha256"], f"{field_path}.sha256")
        payload = _read_source_file(repo_root, path)
        if len(payload) != byte_length:
            raise _fail(
                "a bound adapter source file length differs from the frozen binding",
                field_path,
            )
        actual = "sha256:" + hashlib.sha256(payload).hexdigest()
        if actual != declared_digest:
            raise _fail(
                "a bound adapter source file digest differs from the frozen binding",
                field_path,
            )
    if tuple(paths) != tuple(sorted(allowlist)):
        raise _fail(
            f"engines[{engine_id}].source_files must bind the exact allowlist",
            "source_files",
        )


def _validate_source_pins(repo_root: Path) -> None:
    for relative, needle in REQUIRED_SOURCE_PINS:
        payload = _read_source_file(repo_root, relative)
        if needle not in payload:
            raise _fail(
                "an original adapter version pin is missing or changed", relative
            )


def validate_engine_source_bindings(
    repo_root: Path, document: object
) -> str:
    """Verify raw source bytes and version pins; return the document digest."""

    if not isinstance(repo_root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "repo_root must be a Path",
            field_path="repo_root",
        )
    require_safe_root(repo_root)
    doc = _require_closed(
        document, "engine-source-bindings", ENGINE_SOURCE_BINDINGS_KEYS
    )
    if doc["kind"] != ENGINE_SOURCE_BINDINGS_KIND:
        raise _schema("engine-source-bindings kind is invalid", "kind")
    if _require_int(doc["schema_version"], "schema_version") != 1:
        raise _schema(
            "engine-source-bindings schema_version is invalid", "schema_version"
        )
    _require_synthetic_scope(doc["evidence_origin"], doc["qualification_scope"])

    raw_engines = doc["engines"]
    if not isinstance(raw_engines, list):
        raise _schema("engines must be an array", "engines")
    if len(raw_engines) != len(ENGINE_IDS):
        raise _fail("engines must declare exactly three source bindings", "engines")
    seen: list[str] = []
    for index, raw_entry in enumerate(raw_engines):
        field_path = f"engines[{index}]"
        entry = _require_closed(raw_entry, field_path, ENGINE_ENTRY_KEYS)
        engine_id = validate_semantic_id(
            entry["engine_id"], f"{field_path}.engine_id"
        )
        if engine_id not in ENGINE_IDS:
            raise _fail(
                "an unlisted engine identifier is not permitted", field_path
            )
        seen.append(engine_id)
        if entry["adapter_schema"] != ADAPTER_SCHEMA:
            raise _fail("adapter_schema is not the frozen PR15D schema", field_path)
        if entry["analyzer"] != ANALYZER_ID:
            raise _fail("analyzer must be the frozen keyword-exact analyzer", field_path)
        if entry["source_qualification"] != SOURCE_QUALIFICATION:
            raise _fail(
                "source_qualification must remain SOURCE_ONLY_NOT_BUILT", field_path
            )
        if entry["declared_engine_version"] != DECLARED_ENGINE_VERSIONS[engine_id]:
            raise _fail(
                "declared_engine_version differs from the frozen source literal",
                field_path,
            )
        _validate_source_files(engine_id, entry["source_files"], repo_root)
    if tuple(seen) != ENGINE_IDS:
        raise _fail(
            "engine source bindings must be ordered lucene, quervant, tantivy",
            "engines",
        )
    _validate_source_pins(repo_root)
    return content_digest(dict(doc))


# ---------------------------------------------------------------------------
# Untimed adapter wire projection
# ---------------------------------------------------------------------------


def validate_keyword_reply_projection(
    lane: Lane,
    engine_id: str,
    reply_projection: object,
    oracle_row: Mapping,
) -> None:
    """Validate one closed, untimed adapter reply projection.

    The supplied ``oracle_row`` is **untrusted input**. Its truth is independently
    recomputed from the validated frozen lane via :func:`oracle_row_for_lane`, so a
    coherently forged row plus reply pair can never validate itself.

    Only the six frozen reply fields are accepted. Any timing, scoring,
    binary-identity or extra field is rejected; a count-only match is never
    sufficient, and a boolean is never accepted where an integer count is required.
    """

    if not isinstance(lane, Lane):
        raise _fail("a validated BM-01 Lane is required", "lane")
    if not isinstance(engine_id, str) or engine_id not in ENGINE_IDS:
        raise _fail(
            "reply projection engine is outside the declared engine set", "engine"
        )

    # 1. Independent, frozen authority for this lane.
    expected = oracle_row_for_lane(lane)

    # 2-4. The caller's row must be exactly the reviewed shape and value.
    provided = _require_closed(oracle_row, "oracle_row", ORACLE_ROW_KEYS)
    for field in ("corpus_size", "top_k", "total_hits"):
        _require_exact_int(provided[field], f"oracle_row.{field}")
    for field in ("lane_id", "selectivity_class", "field", "term"):
        if type(provided[field]) is not str:
            raise _schema(f"oracle_row.{field} must be a string", f"oracle_row.{field}")
    if type(provided["doc_ids"]) is not list:
        raise _schema("oracle_row.doc_ids must be an array", "oracle_row.doc_ids")
    _validate_doc_ids(provided["doc_ids"], "oracle_row.doc_ids")
    for field in (
        "lane_id",
        "corpus_size",
        "selectivity_class",
        "field",
        "term",
        "top_k",
        "total_hits",
        "doc_ids",
    ):
        if provided[field] != expected[field]:
            raise _fail(
                f"oracle_row.{field} is not independently verified",
                f"oracle_row.{field}",
            )

    # 5. Closed six-field reply projection.
    projection = _require_closed(reply_projection, "reply_projection", REPLY_PROJECTION_KEYS)
    if projection["schema"] != ADAPTER_SCHEMA:
        raise _fail("reply projection schema is not the frozen PR15D schema", "schema")
    if projection["engine"] != engine_id:
        raise _fail(
            "reply projection engine does not match the requested engine", "engine"
        )
    if projection["request_id"] != "query-" + lane.lane_id:
        raise _fail(
            "reply projection request_id must be query-<lane_id>", "request_id"
        )
    if projection["status"] != "ok":
        raise _fail("reply projection status must be ok", "status")

    # 6. Compare against the independently recomputed truth only.
    total_hits = validate_nonnegative_int(
        projection["total_hits"], "total_hits"
    )
    if total_hits != expected["total_hits"]:
        raise _fail(
            "reply projection total_hits disagrees with the oracle", "total_hits"
        )
    doc_ids = _validate_doc_ids(projection["doc_ids"], "doc_ids")
    if doc_ids != expected["doc_ids"]:
        raise _fail(
            "reply projection doc_ids disagree with the oracle (count-only match "
            "is not sufficient)",
            "doc_ids",
        )


__all__ = [
    "ADAPTER_SCHEMA",
    "ANALYZER_ID",
    "ARM_IDS",
    "BASELINE_ARM_ID",
    "CANDIDATE_ORDER",
    "CLASSES",
    "CORPUS_SIZES",
    "DECLARED_ENGINE_VERSIONS",
    "ENGINE_IDS",
    "ENGINE_SOURCE_BINDINGS_NAME",
    "EXCLUDED_CLASSES",
    "LANE_PARAM_KEYS",
    "ORACLE_GOLDEN_NAME",
    "ORACLE_ID",
    "ORACLE_ROW_KEYS",
    "ORACLE_VERSION",
    "QUERY_SEMANTICS_ID",
    "REPLY_PROJECTION_KEYS",
    "SEMANTIC_COMPARABILITY_NAME",
    "SOURCE_FILE_ALLOWLIST",
    "TOP_K_VALUES",
    "compute_oracle_row",
    "exact_matching_ids",
    "exact_total_hits",
    "expected_lane_ids",
    "expected_oracle_rows",
    "lane_id_for",
    "oracle_row_for_lane",
    "validate_engine_source_bindings",
    "validate_keyword_reply_projection",
    "validate_oracle_golden",
    "validate_semantic_comparability",
]
