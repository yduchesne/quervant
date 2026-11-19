"""Bounded historical-input inventory, strict readers and proportional disclosure.

Historical evidence is a *disclosure*: an input is authenticated only by the fixed
immutable catalog below plus its owning reader. A candidate's declared digest is a
cross-check, never a trust root, and no caller can register a new source, override a
digest or promote an unknown identity. Reading is descriptor-based, single-link,
bounded and repeated, so a replaced or linked file cannot be hashed differently from
the bytes that were parsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

import hashlib
import json
import os

from ..config.codec import content_digest
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest
from ..evidence.archives import ArchiveLimits, inspect_zip
from ..evidence.paths import open_regular_beneath, require_safe_root, validate_relative_member
from . import relative_effects
from .policy_inputs import HISTORICAL_ARCHIVE_DIGESTS

INVENTORY_KIND = "official-baseline-history-inputs"
INVENTORY_SCHEMA_VERSION = 1
REPORT_KIND = "official-baseline-history"
REPORT_SCHEMA_VERSION = 1
FAMILY_RETAINED = "retained-key"
FAMILY_CROSS_ENGINE = "cross-engine"
FAMILIES = (FAMILY_RETAINED, FAMILY_CROSS_ENGINE)
INPUT_ROLES = {
    "retained-archive": FAMILY_RETAINED,
    "retained-micro": FAMILY_RETAINED,
    "retained-f1-receipt": FAMILY_RETAINED,
    "retained-t6-receipt": FAMILY_RETAINED,
    "pr15d-archive": FAMILY_CROSS_ENGINE,
    "pr15d-aggregate": FAMILY_CROSS_ENGINE,
    "retained-analysis": FAMILY_RETAINED,
    "retained-policy": FAMILY_RETAINED,
}
STATUS_FOUND = "FOUND"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_INVALID = "INVALID"
STATUS_UNVERIFIED = "UNVERIFIED"
STATUS_NOT_COMPARABLE = "NOT_COMPARABLE"
STATUSES = (
    STATUS_FOUND,
    STATUS_UNAVAILABLE,
    STATUS_INVALID,
    STATUS_UNVERIFIED,
    STATUS_NOT_COMPARABLE,
)
SUMMARY_ROLES = frozenset({"pr15d-aggregate", "retained-analysis"})
METADATA_ROLES = frozenset({"retained-micro", "retained-f1-receipt", "retained-t6-receipt", "retained-policy"})
INVENTORY_KEYS = frozenset({"kind", "schema_version", "candidates"})
CANDIDATE_KEYS = frozenset({"family", "input_role", "path", "source_identity", "expected_digest"})
REPORT_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "baseline_id",
        "study_id",
        "source_commit",
        "current_raw_digest",
        "entries",
    }
)
ENTRY_KEYS = frozenset(
    {"input_role", "source_identity", "input_digest", "status", "reason", "normalized_rows"}
)
MAX_CANDIDATES = 32
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 100_000
MAX_INVENTORY_BYTES = 1_048_576
MAX_HISTORY_BYTES = 4 * 1_048_576
RAW_DIGEST_BUDGET = 64 * 1_048_576
MAX_NUMERIC_TOKEN_CHARS = 1024

RETAINED_PROTOCOL = "c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c"
RETAINED_EXPERIMENT = "3ad6c5184fbe9c011abb731415a007e3f19d21de"
RETAINED_BASE = "39dbd9f571a58bea8cc03d5a406533298e809bfe"
RETAINED_T6 = "44ccd9e027071cf12777610abae5e6ab5f03177f"
RETAINED_F1 = "38a937fdf0b09f1330f26423dabb311399c8a4cf"
RETAINED_CONTROL = "d3c-v3r3-base-aa-01"
RETAINED_CAMPAIGNS = ("d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02")
T6_TOOLING_MANIFEST_RAW = "62911a324f63398383323eadebf3acb73120ddb42a9d27300fc924c3c38732f3"
PR15D_EVIDENCE_MANIFEST_RAW = "bdc8308d1b0279959395a0dd1e0b375da6efd4154b0fadf216b80fbd80a95c6f"
PR15D_RUN = "20261031T005545Z-40a9c26a57aa23640904075e77be956ee52718bc"
PR15D_SOURCE = "40a9c26a57aa23640904075e77be956ee52718bc"
PR15D_ARCHIVE_BYTES = 502_566
PR15D_AGGREGATE_RUN = PR15D_RUN
PR15D_AGGREGATE_SOURCE = PR15D_SOURCE
PR15D_AGGREGATE_SCHEMA = "pr15d-aggregate-v1"
PR15D_WORKLOAD = "pr15d_v1"
PR15D_CLASSES = ("absent", "rare", "medium", "common")
PR15D_N = (10_000, 100_000)
PR15D_K = (10, 100)
PR15D_COMPARATORS = ("lucene", "tantivy")
PR15D_AGGREGATE_KEYS = frozenset(
    {
        "schema", "workload", "run_id", "source_sha", "host_fingerprint", "filesystem",
        "corpus_digests", "trials", "samples_per_lane", "dispersion_limit", "status",
        "performance_threshold_failure", "score_comparison", "scored_lane", "scored_ratios",
        "regimes", "sort_physical_keys", "latency", "indexing", "throughput", "limitations",
        "query_api_shape", "ingest_metric", "timing_boundary",
    }
)
PR15D_LANE_KEYS = frozenset({"id", "n", "class", "k", "regime", "field", "term", "engines", "comparisons"})
PR15D_ENGINE_KEYS = frozenset(
    {"trial_medians_ns", "median_ns", "dispersion_max_over_min", "trial_p95_ns", "trial_p99_ns"}
)
PR15D_COMPARISON_KEYS = frozenset(
    {"engine_over_quervant_ratio", "quervant_over_engine_speedup",
     "trial_median_range_overlap", "inconclusive", "note"}
)
PR15D_FIELD_TERM = {
    "absent": ("key", "never"),
    "rare": ("key", "singleton"),
    "medium": ("group", "medium"),
    "common": ("key", "common"),
}
RETAINED_ANALYSIS_SCHEMA = "pr15i-d3c-t7-analysis-v1"
RETAINED_ANALYSIS_KEYS = frozenset({"schema", "protocol_sha256", "series", "lanes"})
RETAINED_LANE_KEYS = frozenset({"id", "n", "class", "k", "campaigns"})
RETAINED_CAMPAIGN_KEYS = frozenset(
    {
        "retained", "excluded", "cap", "retained_count", "latency", "raw_latency",
        "raw_ratio", "filter_sensitive",
    }
    | {f"R_{numerator}_{denominator}" for _r, _c, baseline, treatment in relative_effects.RETAINED_FIELDS
       for numerator, denominator in ((treatment, baseline),)}
    | {f"CI_{numerator}_{denominator}" for _r, _c, baseline, treatment in relative_effects.RETAINED_FIELDS
       for numerator, denominator in ((treatment, baseline),)}
)
RETAINED_ARMS = ("A", "L", "P", "H")
POLICY_SCHEMAS = ("pr15i-d3c-t7-policy-v1", "pr15i-d3c-t7f2-policy-v1")
POLICY_STATUS = "T7_POLICY_DERIVED_PENDING_INDEPENDENT_VERIFICATION"
POLICY_KEYS = frozenset({"schema", "protocol_sha256", "status", "rows"})
POLICY_ROW_KEYS_F1 = frozenset(
    {"k", "selected_strategy", "decision_status", "P_status", "H_status",
     "P_reasons", "H_reasons", "filter_sensitive", "P_gm", "H_gm", "H_memory"}
)
POLICY_ROW_KEYS_F2 = frozenset(
    {"k", "selected_strategy", "decision_status", "P_status", "H_status",
     "P_reasons", "H_reasons", "filter_sensitive", "H_memory"}
)
POLICY_SELECTED = ("P", "H", "LINEAR_BASE", "INCONCLUSIVE")
POLICY_ELIGIBILITY = ("ELIGIBLE", "INELIGIBLE", "INCONCLUSIVE")
POLICY_DECISIONS = (
    "LINEAR_BASE",
    "SELECTED_ELIGIBLE",
    "P_TIEBREAKER_NOT_PROVEN_FASTER",
    "K_INCONCLUSIVE",
    "K_INCONCLUSIVE_FILTER_SENSITIVE",
    "K_INCONCLUSIVE_P_VS_H",
    "SELECTED_GM_CONFIRMED",
)
RETAINED_K_VALUES = (1, 10, 32, 64, 100, 128, 256, 512, 1024)


@dataclass(frozen=True)
class SourceRecord:
    """One immutable authenticated historical source identity."""

    family: str
    role: str
    identity: str
    digest: str | None
    reader: str


CATALOG: tuple[SourceRecord, ...] = (
    SourceRecord(FAMILY_RETAINED, "retained-archive", "d3c-v3r3-base-aa-01",
                 HISTORICAL_ARCHIVE_DIGESTS["d3c-v3r3-base-aa-01"], "archive"),
    SourceRecord(FAMILY_RETAINED, "retained-archive", "d3c-v3r3-strategies-01",
                 HISTORICAL_ARCHIVE_DIGESTS["d3c-v3r3-strategies-01"], "archive"),
    SourceRecord(FAMILY_RETAINED, "retained-archive", "d3c-v3r3-strategies-02",
                 HISTORICAL_ARCHIVE_DIGESTS["d3c-v3r3-strategies-02"], "archive"),
    SourceRecord(FAMILY_RETAINED, "retained-f1-receipt", RETAINED_F1,
                 "sha256:80f21e8fb7c9a76d466d749b0253f50bf8955112db0214386abbfcb9a9532ee1",
                 "f1-receipt"),
    SourceRecord(FAMILY_RETAINED, "retained-t6-receipt", RETAINED_T6,
                 "sha256:05c7a677fbb7e3e808efd098670e561cb9be41cc72af668572f21d23a7144e93",
                 "t6-receipt"),
    SourceRecord(FAMILY_RETAINED, "retained-micro", "micro-05", None, "micro"),
    SourceRecord(FAMILY_RETAINED, "retained-analysis", "a59fdfc0230aa15b71aaf11566960bc47f7c7723",
                 "sha256:2c3854e4ff02f5acc9d7837d0267ae40101180df01c7db088705451bc8df3065",
                 "retained-analysis"),
    SourceRecord(FAMILY_RETAINED, "retained-policy", "a59fdfc0230aa15b71aaf11566960bc47f7c7723",
                 "sha256:e68ce9298e3be05540f732d51408085fc0f742e5fed45db52a2e48454576be21",
                 "retained-policy"),
    SourceRecord(FAMILY_CROSS_ENGINE, "pr15d-archive", PR15D_RUN,
                 "sha256:426dff2920b55ff63766da284421cf698f9950011da409b88a33be5d6d4e7bab",
                 "pr15d-archive"),
    SourceRecord(FAMILY_CROSS_ENGINE, "pr15d-aggregate", PR15D_RUN,
                 "sha256:c9e8ed722aefc4fef43837a5511c2c88575287497b449f68f82f7ea0c251b257",
                 "pr15d-aggregate"),
)
SUPPORTED_SOURCES = MappingProxyType(
    {(record.role, record.identity): record.digest for record in CATALOG}
)


def _schema(message: str, field_path: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


def _identity(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _unsafe(message: str, field_path: str) -> BenchError:
    return BenchError(BM_UNSAFE_INPUT, message, field_path=field_path)


def record_for(role: str, identity: str) -> SourceRecord | None:
    """Return the fixed catalog record for one (role, identity) pair."""

    for record in CATALOG:
        if record.role == role and record.identity == identity:
            return record
    return None


# ---------------------------------------------------------------------------
# Stable, bounded observation
# ---------------------------------------------------------------------------


def _identity_tuple(info: Any) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )


def _observe(
    root: Path, relative: str, *, max_bytes: int
) -> tuple[bytes, str, tuple[int, ...]]:
    """One stable bounded observation of ``root/relative`` through no-follow descriptors."""

    member = validate_relative_member(relative)
    anchor = Path(root.anchor)
    try:
        target = root / member
        from_anchor = str(target.relative_to(anchor))
    except ValueError as error:  # pragma: no cover - defensive
        raise _unsafe("the provider path escapes the filesystem root", "path") from error
    try:
        handle = open_regular_beneath(anchor, from_anchor)
    except BenchError:
        raise
    try:
        info = os.fstat(handle.fileno())
        if not os.path.exists and __import__("stat").S_ISREG(info.st_mode):
            raise _unsafe("the historical input must be a regular file", "path")
        if info.st_nlink != 1:
            raise _unsafe("the historical input must have a single link", "path")
        if info.st_size > max_bytes:
            raise _unsafe("the historical input exceeds its byte budget", "path")
        observed = _identity_tuple(info)
        payload = bytearray()
        digest = hashlib.sha256()
        while True:
            chunk = handle.read(1_048_576)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > max_bytes:
                raise _unsafe("the historical input exceeds its byte budget", "path")
            digest.update(chunk)
        after = os.fstat(handle.fileno())
    finally:
        handle.close()
    if _identity_tuple(after) != observed or len(payload) != observed[2]:
        raise _identity("the historical input changed while it was read", "path")
    return bytes(payload), "sha256:" + digest.hexdigest(), observed


def _stable_observation(
    root: Path, relative: str, *, max_bytes: int
) -> tuple[bytes, str, tuple[int, ...]]:
    """Observe twice through the same safe path and require identical results."""

    first = _observe(root, relative, max_bytes=max_bytes)
    second = _observe(root, relative, max_bytes=max_bytes)
    if first[1] != second[1] or first[2] != second[2]:
        raise _identity("the historical input changed between observations", "path")
    return first


def _parse(payload: bytes, field_path: str, *, decimals: bool) -> Any:
    """Strict JSON parse; ``decimals`` keeps source numeric tokens exact."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise _schema("a historical document repeats a JSON key", field_path)
            result[key] = value
        return result

    def constant(token: str) -> Any:
        raise _schema("a historical document contains a non-finite number", field_path)

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _schema("a historical document is not valid UTF-8", field_path) from error
    if text.startswith("\ufeff"):
        raise _schema("a historical document must not carry a BOM", field_path)
    if any(len(token) > MAX_NUMERIC_TOKEN_CHARS for token in text.split('"')[-1:]):
        raise _schema("a numeric token exceeds its budget", field_path)

    def reject_overflow(token: str) -> Any:
        raise _schema("a historical document contains an out-of-range number", field_path)

    try:
        document = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=constant,
            parse_float=Decimal if decimals else reject_overflow,
            parse_int=int,
        )
    except BenchError:
        raise
    except (ValueError, RecursionError) as error:
        raise _schema("a historical document is not valid JSON", field_path) from error
    if not isinstance(document, dict):
        raise _schema("a historical document must be a JSON object", field_path)

    stack = [(document, 0)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise _schema("a historical document exceeds its node budget", field_path)
        if depth > MAX_JSON_DEPTH:
            raise _schema("a historical document exceeds its depth budget", field_path)
        if isinstance(node, dict):
            stack.extend((value, depth + 1) for value in node.values())
        elif isinstance(node, list):
            stack.extend((value, depth + 1) for value in node)
    return document


def _read_history_document(
    root: Path, relative: str, *, max_bytes: int, decimals: bool = False
) -> tuple[bytes, str, dict[str, Any], Any]:
    """Return (payload, raw digest, ordinary view, exact-numeric view or None)."""

    payload, digest, _observed = _stable_observation(root, relative, max_bytes=max_bytes)
    document = _parse(payload, relative, decimals=False)
    exact = _parse(payload, relative, decimals=True) if decimals else None
    return payload, digest, document, exact


def raw_digest(path: Path) -> str:
    """Return the ``sha256:`` raw digest of one stable regular file."""

    target = Path(path)
    if not target.is_absolute():
        target = target.resolve()
    return _stable_observation(
        Path(target.anchor), str(target.relative_to(target.anchor)), max_bytes=RAW_DIGEST_BUDGET
    )[1]


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


def validate_candidate(candidate: object) -> dict[str, Any]:
    """Validate one closed inventory candidate."""

    if not isinstance(candidate, Mapping) or set(candidate) != CANDIDATE_KEYS:
        raise _schema("a history candidate has an unexpected shape", "candidates")
    family = candidate["family"]
    role = candidate["input_role"]
    if type(family) is not str or type(role) is not str:
        raise _schema("family and input_role must be strings", "candidates")
    if family not in FAMILIES:
        raise _schema("unknown history family", "family")
    if role not in INPUT_ROLES:
        raise _schema("unknown history input role", "input_role")
    if INPUT_ROLES[role] != family:
        raise _identity("the input role belongs to another family", "input_role")
    path = candidate["path"]
    if type(path) is not str or not path:
        raise _schema("a history candidate needs a path string", "path")
    identity = candidate["source_identity"]
    if type(identity) is not str or not identity:
        raise _schema("a history candidate needs a source identity", "source_identity")
    digest = candidate["expected_digest"]
    if digest is not None:
        validate_digest(digest, "expected_digest")
    return dict(candidate)


def validate_inventory(document: object) -> dict[str, Any]:
    """Validate the closed location inventory (never a PASS list)."""

    if not isinstance(document, Mapping):
        raise _schema("the history inventory must be an object", "inventory")
    if set(document) != INVENTORY_KEYS:
        raise _schema("the history inventory has an unexpected shape", "inventory")
    if document["kind"] != INVENTORY_KIND:
        raise _schema("unexpected history inventory kind", "kind")
    if type(document["schema_version"]) is not int or document["schema_version"] != INVENTORY_SCHEMA_VERSION:
        raise _schema("unsupported history inventory version", "schema_version")
    candidates = document["candidates"]
    if not isinstance(candidates, list):
        raise _schema("history candidates must be a list", "candidates")
    if len(candidates) > MAX_CANDIDATES:
        raise _schema("the history inventory exceeds its candidate budget", "candidates")
    validated: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        record = validate_candidate(candidate)
        key = (record["family"], record["input_role"], record["source_identity"])
        if key in seen:
            raise _schema("duplicate history candidate identity", "candidates")
        seen.add(key)
        validated.append(record)
    return {
        "kind": INVENTORY_KIND,
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "candidates": validated,
    }


# ---------------------------------------------------------------------------
# Fixed summary adapters
# ---------------------------------------------------------------------------


def _require_exact_keys(document: Mapping[str, Any], keys: frozenset[str], field: str) -> None:
    if set(document) != keys:
        raise _schema("the document has an unexpected shape", field)


def _positive_number(value: object, field: str) -> Decimal | int:
    if type(value) is bool or not isinstance(value, (int, Decimal)):
        raise _schema("expected an exact JSON number", field)
    if value <= 0:
        raise _schema("expected a positive number", field)
    return value


def pr15d_aggregate_rows(
    document: Mapping[str, Any], *, input_digest: str
) -> list[dict[str, Any]]:
    """Project the authentic corrected PR15D aggregate into 32 AS_REPORTED rows."""

    _require_exact_keys(document, PR15D_AGGREGATE_KEYS, "aggregate")
    if document["schema"] != PR15D_AGGREGATE_SCHEMA:
        raise _schema("unexpected PR15D aggregate schema", "schema")
    if document["workload"] != PR15D_WORKLOAD:
        raise _schema("unexpected PR15D workload identity", "workload")
    if document["run_id"] != PR15D_RUN:
        raise _identity("unexpected PR15D run identity", "run_id")
    if document["source_sha"] != PR15D_SOURCE:
        raise _identity("unexpected PR15D measured source", "source_sha")
    if document["status"] != "QUALIFIED":
        raise _identity("the PR15D aggregate is not qualified", "status")
    for field, expected in (("trials", 3), ("samples_per_lane", 20)):
        if type(document[field]) is not int or document[field] != expected:
            raise _identity("the PR15D aggregate has an unexpected design", field)
    if document["regimes"] != ["process_cold", "warm"]:
        raise _identity("the PR15D regimes are unexpected", "regimes")
    fingerprint = document["host_fingerprint"]
    if type(fingerprint) is not str or len(fingerprint) != 64:
        raise _schema("the PR15D host fingerprint is not a raw digest", "host_fingerprint")
    if any(character not in "0123456789abcdef" for character in fingerprint):
        raise _schema("the PR15D host fingerprint is not lowercase hex", "host_fingerprint")
    lanes = {
        f"{PR15D_WORKLOAD}/{n}/{class_name}/k{k}": (n, class_name, k)
        for n in PR15D_N
        for class_name in PR15D_CLASSES
        for k in PR15D_K
    }
    seen: set[tuple[str, str]] = set()
    warm: list[Mapping[str, Any]] = []
    for lane in document["latency"]:
        if not isinstance(lane, Mapping):
            raise _schema("a PR15D lane must be an object", "latency")
        _require_exact_keys(lane, PR15D_LANE_KEYS, "latency")
        lane_id = lane["id"]
        if type(lane_id) is not str:
            raise _schema("a PR15D lane id must be a string", "id")
        if lane_id not in lanes:
            raise _identity("the PR15D aggregate contains an unregistered lane", "id")
        n, class_name, k = lanes[lane_id]
        if (lane["n"], lane["class"], lane["k"]) != (n, class_name, k):
            raise _identity("the PR15D lane coordinates disagree with its identity", "id")
        if (lane["field"], lane["term"]) != PR15D_FIELD_TERM[class_name]:
            raise _identity("the PR15D lane field/term disagrees with its class", "field")
        regime = lane["regime"]
        if regime not in ("warm", "process_cold"):
            raise _identity("the PR15D aggregate regimes are unexpected", "regime")
        if (lane_id, regime) in seen:
            raise _schema("the PR15D aggregate repeats a lane", "latency")
        seen.add((lane_id, regime))
        engines = lane["engines"]
        if not isinstance(engines, Mapping) or set(engines) != {"quervant", "lucene", "tantivy"}:
            raise _schema("a PR15D lane needs its three engines", "engines")
        for engine_record in engines.values():
            _require_exact_keys(engine_record, PR15D_ENGINE_KEYS, "engines")
            for field in ("trial_medians_ns", "trial_p95_ns", "trial_p99_ns"):
                values = engine_record[field]
                if not isinstance(values, list) or len(values) != 3:
                    raise _schema("a PR15D trial array needs three values", field)
                for value in values:
                    if type(value) is not int or value <= 0:
                        raise _schema("a PR15D trial value must be a positive integer", field)
            if type(engine_record["median_ns"]) is not int or engine_record["median_ns"] <= 0:
                raise _schema("a PR15D median must be a positive integer", "median_ns")
            _positive_number(engine_record["dispersion_max_over_min"], "dispersion_max_over_min")
        comparisons = lane["comparisons"]
        if not isinstance(comparisons, Mapping) or set(comparisons) != set(PR15D_COMPARATORS):
            raise _schema("a PR15D lane needs both comparator entries", "comparisons")
        for engine in PR15D_COMPARATORS:
            entry = comparisons[engine]
            _require_exact_keys(entry, PR15D_COMPARISON_KEYS, "comparisons")
            _positive_number(entry["engine_over_quervant_ratio"], "engine_over_quervant_ratio")
            _positive_number(entry["quervant_over_engine_speedup"], "quervant_over_engine_speedup")
            for flag in ("trial_median_range_overlap", "inconclusive"):
                if type(entry[flag]) is not bool:
                    raise _schema("a PR15D comparison flag must be boolean", flag)
            if type(entry["note"]) is not str:
                raise _schema("a PR15D comparison note must be a string", "note")
        if regime == "warm":
            warm.append(lane)
    expected = {(lane_id, regime) for lane_id in lanes for regime in ("warm", "process_cold")}
    if seen != expected:
        raise _identity("the PR15D aggregate is incomplete", "latency")
    rows: list[dict[str, Any]] = []
    for lane in sorted(warm, key=lambda item: item["id"]):
        for engine in PR15D_COMPARATORS:
            rows.append(
                relative_effects.effect_row(
                    study_id=relative_effects.STUDY_CROSS_ENGINE,
                    run_id=PR15D_RUN,
                    campaign_id="three-trial-backend",
                    lane_id=lane["id"],
                    metric="latency",
                    unit="ns",
                    regime="warm",
                    direction="lower",
                    baseline="quervant",
                    treatment=engine,
                    method_id=relative_effects.HISTORICAL_CROSS_METHOD_ID,
                    ratio=lane["comparisons"][engine]["engine_over_quervant_ratio"],
                    uncertainty=None,
                    decision=relative_effects.CROSS_ENGINE_DECISION,
                    evidence_level=relative_effects.EVIDENCE_AS_REPORTED,
                    source_commit=PR15D_SOURCE,
                    host_environment=None,
                    host_identity="sha256:" + fingerprint,
                    input_digest=input_digest,
                )
            )
    if len(rows) != 32:
        raise _identity("the PR15D aggregate does not yield 32 warm rows", "latency")
    return rows


def _retained_cap(n: int, class_name: str) -> Decimal:
    return Decimal("1.25") if n == 100_000 and class_name in ("medium", "common") else Decimal("1.5")


def retained_analysis_rows(
    document: Mapping[str, Any], *, input_digest: str
) -> list[dict[str, Any]]:
    """Project the authentic retained analysis into 864 AS_REPORTED rows."""

    _require_exact_keys(document, RETAINED_ANALYSIS_KEYS, "analysis")
    if document["schema"] != RETAINED_ANALYSIS_SCHEMA:
        raise _schema("unexpected retained analysis schema", "schema")
    if str(document["protocol_sha256"]).removeprefix("sha256:") != RETAINED_PROTOCOL:
        raise _identity("the retained analysis protocol differs", "protocol_sha256")
    series = document["series"]
    if not isinstance(series, list) or list(series) != list(RETAINED_CAMPAIGNS):
        raise _identity("the retained analysis series is unexpected", "series")
    lanes = document["lanes"]
    registered = set(relative_effects.lane_ids(relative_effects.STUDY_RETAINED_KEY))
    if not isinstance(lanes, Mapping) or set(lanes) != registered:
        raise _identity("the retained analysis lane set is incomplete", "lanes")
    rows: list[dict[str, Any]] = []
    for lane_id in sorted(lanes):
        lane = lanes[lane_id]
        if not isinstance(lane, Mapping):
            raise _schema("a retained lane must be an object", "lanes")
        _require_exact_keys(lane, RETAINED_LANE_KEYS, "lanes")
        if lane["id"] != lane_id:
            raise _schema("a retained lane record disagrees with its identity", "lanes")
        _text, n_text, class_name, k_text = lane_id.split("/")
        if (lane["n"], lane["class"], lane["k"]) != (int(n_text), class_name, int(k_text[1:])):
            raise _identity("retained lane coordinates disagree with their identity", "lanes")
        campaigns = lane["campaigns"]
        if not isinstance(campaigns, Mapping) or set(campaigns) != set(RETAINED_CAMPAIGNS):
            raise _identity("a retained lane needs both campaigns", "campaigns")
        for campaign in RETAINED_CAMPAIGNS:
            record = campaigns[campaign]
            if not isinstance(record, Mapping):
                raise _schema("a retained campaign record must be an object", "campaigns")
            _require_exact_keys(record, RETAINED_CAMPAIGN_KEYS, "campaigns")
            retained = record["retained"]
            if (
                not isinstance(retained, list)
                or not 4 <= len(retained) <= 12
                or any(type(block) is not int for block in retained)
                or retained != sorted(set(retained))
                or any(block not in range(1, 13) for block in retained)
            ):
                raise _identity("the retained block list is invalid", "retained")
            if type(record["retained_count"]) is not int or record["retained_count"] != len(retained):
                raise _identity("retained_count disagrees with the block list", "retained_count")
            cap = _retained_cap(lane["n"], lane["class"])
            if Decimal(str(record["cap"])) != cap:
                raise _identity("the retained cap is unexpected", "cap")
            excluded = record["excluded"]
            if not isinstance(excluded, list):
                raise _schema("the excluded block list must be a list", "excluded")
            complement = [block for block in range(1, 13) if block not in retained]
            if [item.get("block") for item in excluded if isinstance(item, Mapping)] != complement:
                raise _identity("the excluded block set is not the complement", "excluded")
            for item in excluded:
                if not isinstance(item, Mapping) or set(item) != {"block", "within", "arms"}:
                    raise _schema("an excluded block record has an unexpected shape", "excluded")
                within = item["within"]
                if not isinstance(within, Mapping) or set(within) != set(RETAINED_ARMS):
                    raise _schema("an excluded block needs every arm", "within")
                for arm in RETAINED_ARMS:
                    _positive_number(within[arm], "within")
                arms = item["arms"]
                if not isinstance(arms, list) or arms != [
                    arm for arm in RETAINED_ARMS if Decimal(str(within[arm])) > cap
                ]:
                    raise _identity("the excluded arms disagree with the ratios", "arms")
                if not arms:
                    raise _identity("an excluded block must violate the cap", "arms")
            for field in ("latency", "raw_latency"):
                table = record[field]
                if not isinstance(table, Mapping) or set(table) != set(RETAINED_ARMS):
                    raise _schema("a latency table needs every arm", field)
                for arm in RETAINED_ARMS:
                    _positive_number(table[arm], field)
            raw_ratio = record["raw_ratio"]
            if not isinstance(raw_ratio, Mapping) or set(raw_ratio) != {"L", "P", "H"}:
                raise _schema("raw_ratio needs L, P and H", "raw_ratio")
            for arm in ("L", "P", "H"):
                _positive_number(raw_ratio[arm], "raw_ratio")
            if type(record["filter_sensitive"]) is not bool:
                raise _schema("filter_sensitive must be boolean", "filter_sensitive")
            for ratio_field, ci_field, baseline, treatment in relative_effects.RETAINED_FIELDS:
                _positive_number(record[ratio_field], ratio_field)
                interval = record[ci_field]
                if not isinstance(interval, Mapping) or set(interval) != {"low", "high", "seed"}:
                    raise _schema("a retained effect needs its original interval", ci_field)
                rows.append(
                    relative_effects.effect_row(
                        study_id=relative_effects.STUDY_RETAINED_KEY,
                        run_id=campaign,
                        campaign_id=campaign,
                        lane_id=lane_id,
                        metric="latency",
                        unit="ns",
                        regime="warm",
                        direction="lower",
                        baseline=baseline,
                        treatment=treatment,
                        method_id=relative_effects.RETAINED_METHOD_ID,
                        ratio=record[ratio_field],
                        uncertainty=interval,
                        decision=relative_effects.RETAINED_DECISION,
                        evidence_level=relative_effects.EVIDENCE_AS_REPORTED,
                        source_commit=RETAINED_EXPERIMENT,
                        host_environment=None,
                        host_identity=None,
                        input_digest=input_digest,
                    )
                )
    if len(rows) != 864:
        raise _identity("the retained analysis does not yield 864 rows", "lanes")
    return rows


# ---------------------------------------------------------------------------
# Remaining fixed role readers
# ---------------------------------------------------------------------------


def _read_archive(root: Path, record: SourceRecord) -> None:
    from .historical import audit_retained_key_archive

    campaign = record.identity
    archive = f"{campaign}.tar.gz"
    _stable_observation(root, archive, max_bytes=RAW_DIGEST_BUDGET)
    _stable_observation(root, archive + ".sha256", max_bytes=MAX_HISTORY_BYTES)
    audit = audit_retained_key_archive(root, campaign, limits=ArchiveLimits())
    if audit.archive_digest != record.digest:
        raise _identity("the retained archive differs from its frozen digest", "archive")
    if str(audit.manifest_protocol_digest).removeprefix("sha256:") != RETAINED_PROTOCOL:
        raise _identity("the retained archive protocol differs", "archive")
    _stable_observation(root, archive, max_bytes=RAW_DIGEST_BUDGET)
    _stable_observation(root, archive + ".sha256", max_bytes=MAX_HISTORY_BYTES)


def _read_micro(document: Mapping[str, Any]) -> None:
    from .policy_inputs import validate_micro_table

    validate_micro_table(document)


def _source_root(source_root: Path | None) -> Path:
    if source_root is not None:
        return require_safe_root(Path(source_root))
    from ..evidence.provenance import repository_root

    return Path(repository_root())


def _read_t6(document: Mapping[str, Any], digest: str, record: SourceRecord) -> None:
    """Private read-only adapter mirroring the frozen T6 receipt fields."""

    if digest != record.digest:
        raise _identity("the T6 receipt differs from its frozen digest", "receipt")
    expected_keys = {
        "schema",
        "protocol_sha256",
        "control_name",
        "campaign_names",
        "t6_commit",
        "tooling_manifest_sha256",
        "protected_files",
        "receipt_origin",
    }
    if set(document) != expected_keys:
        raise _schema("the T6 receipt has an unexpected shape", "receipt")
    if document["schema"] != "pr15i-d3c-freeze-v1":
        raise _schema("unexpected T6 receipt schema", "schema")
    if str(document["protocol_sha256"]).removeprefix("sha256:") != RETAINED_PROTOCOL:
        raise _identity("the T6 receipt protocol differs", "protocol_sha256")
    if document["t6_commit"] != RETAINED_T6:
        raise _identity("the T6 receipt names another commit", "t6_commit")
    if document["control_name"] != RETAINED_CONTROL:
        raise _identity("the T6 receipt names another control campaign", "control_name")
    if list(document["campaign_names"]) != list(RETAINED_CAMPAIGNS):
        raise _identity("the T6 receipt campaign order is unexpected", "campaign_names")
    if str(document["tooling_manifest_sha256"]).removeprefix("sha256:") != T6_TOOLING_MANIFEST_RAW:
        raise _identity("the T6 tooling manifest differs", "tooling_manifest_sha256")
    files = document["protected_files"]
    if not isinstance(files, Mapping) or not files:
        raise _schema("the T6 receipt needs its protected files", "protected_files")
    for path, value in files.items():
        if type(path) is not str or path.startswith("/") or ".." in path.split("/"):
            raise _unsafe("the T6 receipt contains an unsafe protected path", "protected_files")
        if type(value) is not str or len(value) != 64:
            raise _schema("a protected-file digest must be 64 hex characters", "protected_files")
        if any(character not in "0123456789abcdef" for character in value):
            raise _schema("a protected-file digest must be lowercase hex", "protected_files")
    if document.get("receipt_origin") != "historical":
        raise _identity("the T6 receipt origin is unexpected", "receipt_origin")


def _read_policy(document: Mapping[str, Any]) -> None:
    _require_exact_keys(document, POLICY_KEYS, "policy")
    schema = document["schema"]
    if schema not in POLICY_SCHEMAS:
        raise _schema("unexpected retained policy schema", "schema")
    if str(document["protocol_sha256"]).removeprefix("sha256:") != RETAINED_PROTOCOL:
        raise _identity("the retained policy protocol differs", "protocol_sha256")
    if document["status"] != POLICY_STATUS:
        raise _identity("the retained policy status is unexpected", "status")
    rows = document["rows"]
    if not isinstance(rows, list) or len(rows) != len(RETAINED_K_VALUES):
        raise _identity("the retained policy needs nine rows", "rows")
    keys = POLICY_ROW_KEYS_F1 if schema == "pr15i-d3c-t7-policy-v1" else POLICY_ROW_KEYS_F2
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != keys:
            raise _schema("a retained policy row has an unexpected shape", "rows")
        if row["k"] != RETAINED_K_VALUES[index]:
            raise _identity("the retained policy K order is unexpected", "rows")
        if row["selected_strategy"] not in POLICY_SELECTED:
            raise _schema("unknown retained selection label", "rows")
        if row["P_status"] not in POLICY_ELIGIBILITY or row["H_status"] not in POLICY_ELIGIBILITY:
            raise _schema("unknown retained eligibility label", "rows")
        if row["decision_status"] not in POLICY_DECISIONS:
            raise _schema("unknown retained decision label", "rows")
        if row["decision_status"] == "SELECTED_GM_CONFIRMED" and schema != "pr15i-d3c-t7f2-policy-v1":
            raise _identity("only the verified policy schema may confirm a GM selection", "rows")
        for field in ("P_reasons", "H_reasons"):
            reasons = row[field]
            if not isinstance(reasons, list) or any(type(item) is not str for item in reasons):
                raise _schema("policy reasons must be strings", field)
        if type(row["filter_sensitive"]) is not bool:
            raise _schema("policy filter_sensitive must be boolean", "rows")
        memory = row["H_memory"]
        if memory is not None and (type(memory) is not int or memory < 0):
            raise _schema("H_memory must be null or a non-negative integer", "rows")
        if schema == "pr15i-d3c-t7-policy-v1":
            for field in ("P_gm", "H_gm"):
                values = row[field]
                if not isinstance(values, list) or len(values) != 2:
                    raise _schema("a GM array needs two values", field)
                for value in values:
                    _positive_number(value, field)


def _read_pr15d_archive(root: Path, relative: str, record: SourceRecord) -> None:
    manifest_path = Path("docs/pr-artifacts/pr-15d/b-evidence-manifest.json")
    from ..evidence.provenance import repository_root

    manifest = Path(repository_root()) / manifest_path
    raw = raw_digest(manifest)
    if raw != "sha256:" + PR15D_EVIDENCE_MANIFEST_RAW:
        raise _identity("the PR15D evidence manifest differs from its pinned hash", "manifest")
    document, _digest, manifest_document, _exact = _read_history_document(
        Path(repository_root()), str(manifest_path), max_bytes=MAX_HISTORY_BYTES
    )
    if manifest_document.get("schema") != "pr15d-evidence-manifest-v1":
        raise _schema("unexpected PR15D evidence manifest schema", "manifest")
    if manifest_document.get("run_id") != PR15D_RUN or manifest_document.get("source_sha") != PR15D_SOURCE:
        raise _identity("the PR15D evidence manifest names another run", "manifest")
    payload, digest, _observed = _stable_observation(root, relative, max_bytes=RAW_DIGEST_BUDGET)
    if digest != record.digest:
        raise _identity("the PR15D archive differs from its pinned digest", "archive")
    if len(payload) != PR15D_ARCHIVE_BYTES:
        raise _identity("the PR15D archive has an unexpected length", "archive")
    members = inspect_zip(root, relative, ArchiveLimits())
    names = [member.name for member in members]
    if len({name.casefold() for name in names}) != len(names):
        raise _identity("the PR15D archive has case-colliding members", "archive")
    published: dict[str, tuple[int, str]] = {}
    for group in ("raw_manifests", "contention_records", "resources", "validation"):
        records = manifest_document.get(group)
        if not isinstance(records, list):
            raise _schema("the PR15D manifest needs its member tables", group)
        for item in records:
            if not isinstance(item, Mapping) or set(item) != {"path", "bytes", "sha256"}:
                raise _schema("a PR15D manifest member has an unexpected shape", group)
            published[item["path"]] = (item["bytes"], item["sha256"])
    observed = {member.name: (member.size_bytes, member.sha256.removeprefix("sha256:")) for member in members}
    if set(observed) != set(published):
        raise _identity("the PR15D archive member set differs from the manifest", "archive")
    for name, (size_bytes, sha) in published.items():
        if observed[name] != (size_bytes, sha):
            raise _identity("a PR15D archive member differs from the manifest", "archive")
    _stable_observation(root, relative, max_bytes=RAW_DIGEST_BUDGET)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _entry(record_status: str, reason: str, digest: str | None, rows: list[dict[str, Any]] | None = None):
    return {
        "status": record_status,
        "reason": reason,
        "input_digest": digest,
        "normalized_rows": rows or [],
    }


def classify_candidate(
    provider_root: Path, candidate: Mapping[str, Any], *, source_root: Path | None = None
) -> dict[str, Any]:
    """Classify one candidate through the fixed catalog and its owning reader."""

    validated = validate_candidate(candidate)
    role = validated["input_role"]
    identity = validated["source_identity"]
    entry = {
        "input_role": role,
        "source_identity": identity,
        "input_digest": None,
        "status": STATUS_UNAVAILABLE,
        "reason": "not-found",
        "normalized_rows": [],
    }
    record = record_for(role, identity)
    provider = Path(provider_root)
    try:
        member = validate_relative_member(validated["path"])
    except BenchError as error:
        entry.update(_entry(STATUS_INVALID, f"unsafe-path:{error.code}", None))
        return entry
    if not (provider / member).exists() and not (provider / member).is_symlink():
        return entry
    try:
        payload, digest, _observed = _stable_observation(
            provider, member, max_bytes=RAW_DIGEST_BUDGET if role in ("retained-archive", "pr15d-archive") else MAX_HISTORY_BYTES
        )
    except BenchError as error:
        reason = (
            f"changed-during-read:{error.code}"
            if error.code == BM_IDENTITY_INVALID
            else f"unsafe-input:{error.code}"
        )
        entry.update(_entry(STATUS_INVALID, reason, None))
        return entry
    entry["input_digest"] = digest
    if record is None:
        entry.update(_entry(STATUS_UNVERIFIED, "unsupported-source-identity", digest))
        return entry
    declared = validated["expected_digest"]
    if declared is not None and declared != record.digest:
        entry.update(
            _entry(STATUS_INVALID, "declared-digest-conflicts-with-independent-anchor", digest)
        )
        return entry
    if record.digest is None:
        entry.update(_entry(STATUS_UNVERIFIED, "no-independent-raw-digest", digest))
        return entry
    if declared is None:
        entry.update(
            _entry(STATUS_INVALID, "declared-digest-conflicts-with-independent-anchor", digest)
        )
        return entry
    if digest != record.digest:
        entry.update(_entry(STATUS_INVALID, "digest-mismatch", digest))
        return entry
    try:
        rows = _dispatch_reader(record, role, provider, member, payload, digest, source_root)
    except BenchError as error:
        entry.update(_entry(STATUS_INVALID, f"{error.code}:{error.field_path or 'input'}", digest))
        return entry
    entry.update(rows)
    return entry


def _dispatch_reader(
    record: SourceRecord,
    role: str,
    provider: Path,
    member: str,
    payload: bytes,
    digest: str,
    source_root: Path | None,
) -> dict[str, Any]:
    if record.reader == "archive":
        if Path(member).name != f"{record.identity}.tar.gz":
            raise _identity("the retained archive basename is unexpected", "path")
        _read_archive(provider, record)
        return _entry(
            STATUS_FOUND, "authenticated-archive;replay-unavailable:shared-projector", digest
        )
    if record.reader == "pr15d-archive":
        _read_pr15d_archive(provider, member, record)
        return _entry(
            STATUS_FOUND, "authenticated-archive;replay-unavailable:shared-projector", digest
        )
    document = _parse(payload, member, decimals=True)
    if record.reader == "micro":
        _read_micro(_ordinary_view(payload, member))
        return _entry(STATUS_UNVERIFIED, "no-independent-raw-digest", digest)
    if record.reader == "f1-receipt":
        from .policy_inputs import _f1_identity

        root = _source_root(source_root)
        receipt = provider / member
        _stable_observation(provider, member, max_bytes=MAX_HISTORY_BYTES)
        _f1_identity(receipt, root)
        _stable_observation(provider, member, max_bytes=MAX_HISTORY_BYTES)
        return _entry(STATUS_FOUND, "authenticated-receipt", digest)
    if record.reader == "t6-receipt":
        _read_t6(_ordinary_view(payload, member), digest, record)
        return _entry(STATUS_FOUND, "authenticated-historical-receipt", digest)
    if record.reader == "pr15d-aggregate":
        return _entry(
            STATUS_FOUND,
            "authenticated-as-reported-summary",
            digest,
            pr15d_aggregate_rows(document, input_digest=digest),
        )
    if record.reader == "retained-analysis":
        return _entry(
            STATUS_FOUND,
            "authenticated-as-reported-summary",
            digest,
            retained_analysis_rows(document, input_digest=digest),
        )
    if record.reader == "retained-policy":
        _read_policy(_ordinary_view(payload, member))
        return _entry(STATUS_FOUND, "authenticated-policy-metadata", digest)
    raise _schema("the catalog names an unknown reader", "reader")  # pragma: no cover


def _ordinary_view(payload: bytes, member: str) -> dict[str, Any]:
    return _parse(payload, member, decimals=False)


def build_entries(
    provider_root: Path, inventory: Mapping[str, Any], *, source_root: Path | None = None
) -> list[dict[str, Any]]:
    """Authenticate every inventory candidate under ``provider_root``."""

    validated = validate_inventory(inventory)
    return [
        classify_candidate(provider_root, candidate, source_root=source_root)
        for candidate in validated["candidates"]
    ]


# ---------------------------------------------------------------------------
# Disclosures
# ---------------------------------------------------------------------------


def validate_entry(entry: object) -> dict[str, Any]:
    """Validate one history entry against the fixed catalog."""

    if not isinstance(entry, Mapping) or set(entry) != ENTRY_KEYS:
        raise _schema("a history entry has an unexpected shape", "entries")
    role = entry["input_role"]
    identity = entry["source_identity"]
    if type(role) is not str or role not in INPUT_ROLES:
        raise _schema("unknown history input role", "input_role")
    if type(identity) is not str or not identity:
        raise _schema("a history entry needs a source identity", "source_identity")
    status = entry["status"]
    if type(status) is not str or status not in STATUSES:
        raise _schema("unknown history status", "status")
    if type(entry["reason"]) is not str or not entry["reason"]:
        raise _schema("a history entry needs a reason", "reason")
    digest = entry["input_digest"]
    if digest is not None:
        validate_digest(digest, "input_digest")
    rows = entry["normalized_rows"]
    if not isinstance(rows, list):
        raise _schema("normalized rows must be a list", "normalized_rows")
    record = record_for(role, identity)
    if status == STATUS_FOUND:
        if record is None:
            raise _identity("a found entry must select a fixed catalog record", "source_identity")
        if record.digest is None or digest != record.digest:
            raise _identity("a found entry must match its independent digest", "input_digest")
        if role not in SUMMARY_ROLES and rows:
            raise _identity("only the two summary roles contribute rows", "normalized_rows")
    elif rows:
        raise _identity("an unusable input must not contribute normalized rows", "normalized_rows")
    for row in rows:
        validated = relative_effects.validate_row(row, current=False)
        if validated["input_digest"] != digest:
            raise _identity("a historical row cites another source digest", "normalized_rows")
        if validated["evidence_level"] != relative_effects.EVIDENCE_AS_REPORTED:
            raise _identity("a summary row is AS_REPORTED, never recomputed", "normalized_rows")
        if validated["study_id"] != (
            relative_effects.STUDY_RETAINED_KEY
            if INPUT_ROLES[role] == FAMILY_RETAINED
            else relative_effects.STUDY_CROSS_ENGINE
        ):
            raise _identity("a historical row belongs to another family", "normalized_rows")
    return dict(entry)


def report_payload(
    *,
    baseline_id: str,
    study_id: str,
    source_commit: str,
    current_raw_digest: str,
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the seven-key history disclosure document."""

    return {
        "kind": REPORT_KIND,
        "schema_version": REPORT_SCHEMA_VERSION,
        "baseline_id": baseline_id,
        "study_id": study_id,
        "source_commit": source_commit,
        "current_raw_digest": current_raw_digest,
        "entries": [validate_entry(entry) for entry in entries],
    }


def validate_report(document: object) -> dict[str, Any]:
    """Validate a history disclosure document."""

    if not isinstance(document, Mapping):
        raise _schema("the history report must be an object", "report")
    if set(document) != REPORT_KEYS:
        raise _schema("the history report has an unexpected shape", "report")
    if document["kind"] != REPORT_KIND:
        raise _schema("unexpected history report kind", "kind")
    if type(document["schema_version"]) is not int or document["schema_version"] != REPORT_SCHEMA_VERSION:
        raise _schema("unsupported history report version", "schema_version")
    relative_effects._header(document, "baseline_id", document["baseline_id"])
    relative_effects._header(document, "study_id", document["study_id"])
    relative_effects._header(document, "source_commit", document["source_commit"])
    relative_effects._header(document, "current_raw_digest", document["current_raw_digest"])
    entries_value = document["entries"]
    if not isinstance(entries_value, list):
        raise _schema("history entries must be a list", "entries")
    if len(entries_value) > MAX_CANDIDATES:
        raise _schema("the history report exceeds its entry budget", "entries")
    entries = [validate_entry(entry) for entry in entries_value]
    if len({(entry["input_role"], entry["source_identity"]) for entry in entries}) != len(entries):
        raise _schema("duplicate history entry identity", "entries")
    family = (
        FAMILY_RETAINED
        if document["study_id"] == relative_effects.STUDY_RETAINED_KEY
        else FAMILY_CROSS_ENGINE
    )
    for entry in entries:
        if INPUT_ROLES[entry["input_role"]] != family:
            raise _identity("a history entry belongs to another family", "entries")
    return {**dict(document), "entries": entries}


def open_verified_baseline_disclosures(
    *,
    operation_root: Path,
    baseline_id: str,
    study_id: str,
    source_commit: str,
    current_raw_digest: str,
) -> dict[str, Any]:
    """Reopen both baseline disclosures and bind them to the given identities."""

    root = require_safe_root(Path(operation_root))
    observed: dict[str, Any] = {}
    for name, kind in (
        ("history-report.json", REPORT_KIND),
        ("relative-effects.json", relative_effects.ROWS_KIND),
    ):
        try:
            _payload, digest, document, _exact = _read_history_document(
                root, name, max_bytes=MAX_HISTORY_BYTES
            )
        except BenchError as error:
            if error.code in (BM_FILE_MISSING, BM_UNSAFE_INPUT) and "budget" not in str(error):
                raise BenchError(
                    BM_EVIDENCE_UNAVAILABLE,
                    "a baseline disclosure is unavailable",
                    field_path=name,
                ) from error
            raise
        validated = validate_report(document) if kind == REPORT_KIND else relative_effects.validate_disclosure(document)
        if validated["kind"] != kind:
            raise _schema("unexpected disclosure kind", name)
        for field, expected in (
            ("baseline_id", baseline_id),
            ("study_id", study_id),
            ("source_commit", source_commit),
            ("current_raw_digest", current_raw_digest),
        ):
            if validated[field] != expected:
                raise _identity("the disclosure is bound to another identity", field)
        observed[name] = {
            "digest": content_digest(validated),
            "path": root / name,
            "document": validated,
        }
    return {
        "history_report_digest": observed["history-report.json"]["digest"],
        "relative_effects_digest": observed["relative-effects.json"]["digest"],
        "history_report_path": observed["history-report.json"]["path"],
        "relative_effects_path": observed["relative-effects.json"]["path"],
        "statuses": sorted(
            {entry["status"] for entry in observed["history-report.json"]["document"]["entries"]}
        ),
    }


def comparable_pairs(
    entries: Iterable[Mapping[str, Any]]
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    """Return (historical entry, row) pairs that may enter a proportional comparison."""

    pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for entry in entries:
        validated = validate_entry(entry)
        if validated["status"] != STATUS_FOUND:
            continue
        for row in validated["normalized_rows"]:
            pairs.append((validated, row))
    return pairs


__all__ = [
    "CATALOG",
    "CANDIDATE_KEYS",
    "ENTRY_KEYS",
    "FAMILIES",
    "FAMILY_CROSS_ENGINE",
    "FAMILY_RETAINED",
    "INPUT_ROLES",
    "INVENTORY_KIND",
    "INVENTORY_SCHEMA_VERSION",
    "MAX_CANDIDATES",
    "METADATA_ROLES",
    "PR15D_AGGREGATE_RUN",
    "PR15D_AGGREGATE_SOURCE",
    "PR15D_RUN",
    "REPORT_KIND",
    "REPORT_SCHEMA_VERSION",
    "RETAINED_CAMPAIGNS",
    "STATUSES",
    "STATUS_FOUND",
    "STATUS_INVALID",
    "STATUS_NOT_COMPARABLE",
    "STATUS_UNAVAILABLE",
    "STATUS_UNVERIFIED",
    "SUPPORTED_SOURCES",
    "SUMMARY_ROLES",
    "SourceRecord",
    "build_entries",
    "classify_candidate",
    "comparable_pairs",
    "open_verified_baseline_disclosures",
    "pr15d_aggregate_rows",
    "raw_digest",
    "record_for",
    "report_payload",
    "retained_analysis_rows",
    "validate_candidate",
    "validate_entry",
    "validate_inventory",
    "validate_report",
]
