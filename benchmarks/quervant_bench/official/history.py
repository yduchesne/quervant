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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

import hashlib
import json
import math
import os
import stat

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
from ..evidence.archives import ArchiveLimits, MemberDigest, inspect_zip
from ..evidence.paths import open_regular_beneath, validate_relative_member
from ..evidence.provenance import repository_root
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


@dataclass(frozen=True)
class _FileObservation:
    """One stable observation of a single regular file."""

    root: Path
    relative: str
    max_bytes: int
    digest: str
    byte_length: int
    identity: tuple[int, int, int, int, int, int]


@dataclass(frozen=True)
class _DependencyUnavailable(Exception):
    """First-read absence of a fixed role dependency (not a status)."""

    kind: str


def _identity_tuple(info: Any) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )


def _lexical(root: Path) -> tuple[Path, Path]:
    """Return ``(anchor, lexical root)`` without resolving symlinks or ``..``."""

    base = Path.cwd()
    lexical = Path(root)
    if not lexical.is_absolute():
        lexical = base / lexical
    return Path(lexical.anchor), lexical


def _observe_file(
    root: Path, relative: str, *, max_bytes: int, capture: bool = False
) -> tuple[_FileObservation, bytes | None]:
    """One bounded, streaming, single-link observation through no-follow descriptors."""

    member = validate_relative_member(relative)
    anchor, lexical_root = _lexical(root)
    target = lexical_root / member
    try:
        from_anchor = str(target.relative_to(anchor))
    except ValueError as error:  # pragma: no cover - defensive
        raise _unsafe("the provider path escapes the filesystem root", "path") from error
    try:
        handle = open_regular_beneath(anchor, from_anchor)
    except OSError as error:
        raise _unsafe("the historical input could not be opened", "path") from error
    payload: bytearray | None = bytearray() if capture else None
    digest = hashlib.sha256()
    total = 0
    close_error: OSError | None = None
    try:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise _unsafe("the historical input must be a regular file", "path")
        if info.st_nlink != 1:
            raise _unsafe("the historical input must have a single link", "path")
        if info.st_size > max_bytes:
            raise _unsafe("the historical input exceeds its byte budget", "path")
        observed = _identity_tuple(info)
        while True:
            remaining = max_bytes - total
            chunk = handle.read(min(1_048_576, remaining + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise _unsafe("the historical input exceeds its byte budget", "path")
            digest.update(chunk)
            if payload is not None:
                payload.extend(chunk)
        after = os.fstat(handle.fileno())
        if _identity_tuple(after) != observed or total != observed[2]:
            raise _identity("the historical input changed while it was read", "path")
    except OSError as error:
        raise _unsafe("the historical input could not be read", "path") from error
    finally:
        try:
            handle.close()
        except OSError as error:
            close_error = error
    # A pending primary failure propagates through finally and bypasses this
    # branch; a cleanup failure becomes the result only after a successful read.
    if close_error is not None:
        raise _unsafe("the historical input could not be closed", "path") from close_error
    return (
        _FileObservation(
            root=lexical_root,
            relative=member,
            max_bytes=max_bytes,
            digest="sha256:" + digest.hexdigest(),
            byte_length=total,
            identity=observed,
        ),
        bytes(payload) if payload is not None else None,
    )


def _require_same_observation(before: _FileObservation) -> None:
    """Reopen the original lexical path and require identical identity, length and digest."""

    try:
        after, _payload = _observe_file(
            before.root, before.relative, max_bytes=before.max_bytes
        )
    except BenchError as error:
        if error.code == BM_FILE_MISSING:
            raise _identity("the historical input changed between observations", "path") from error
        raise
    if after.identity != before.identity or after.digest != before.digest or after.byte_length != before.byte_length:
        raise _identity("the historical input changed between observations", "path")


def _parse(payload: bytes, field_path: str, *, decimals: bool) -> Any:
    """Strict JSON parse with per-token length and finiteness enforcement."""

    def require_token(token: str) -> None:
        if len(token) > MAX_NUMERIC_TOKEN_CHARS:
            raise _unsafe("a numeric token exceeds its budget", field_path)

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise _schema("a historical document repeats a JSON key", field_path)
            result[key] = value
        return result

    def constant(token: str) -> Any:
        raise _schema("a historical document contains a non-finite number", field_path)

    def parse_integer(token: str) -> int:
        require_token(token)
        try:
            return int(token)
        except (ValueError, OverflowError) as error:
            raise _schema("a historical document contains an invalid number", field_path) from error

    def parse_fractional(token: str) -> Any:
        require_token(token)
        try:
            ordinary = float(token)
        except (ValueError, OverflowError) as error:
            raise _schema("a historical document contains an invalid number", field_path) from error
        if not math.isfinite(ordinary):
            raise _schema("a historical document contains an out-of-range number", field_path)
        if not decimals:
            return ordinary
        try:
            exact = Decimal(token)
        except (ValueError, OverflowError, InvalidOperation) as error:
            raise _schema("a historical document contains an invalid number", field_path) from error
        if not exact.is_finite():
            raise _schema("a historical document contains a non-finite number", field_path)
        return exact

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _schema("a historical document is not valid UTF-8", field_path) from error
    if text.startswith("\ufeff"):
        raise _schema("a historical document must not carry a BOM", field_path)
    try:
        document = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=constant,
            parse_float=parse_fractional,
            parse_int=parse_integer,
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
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise _unsafe("a historical document exceeds its structural budget", field_path)
        if isinstance(node, dict):
            stack.extend((value, depth + 1) for value in node.values())
        elif isinstance(node, list):
            stack.extend((value, depth + 1) for value in node)
    return document


def _read_history_document(
    root: Path, relative: str, *, max_bytes: int, decimals: bool = False
) -> tuple[bytes, str, dict[str, Any], Any]:
    """Observe, parse the requested views, then require the same observation."""

    before, payload = _observe_file(root, relative, max_bytes=max_bytes, capture=True)
    assert payload is not None
    document = _parse(payload, relative, decimals=False)
    exact = _parse(payload, relative, decimals=True) if decimals else None
    _require_same_observation(before)
    return payload, before.digest, document, exact


def raw_digest(path: Path) -> str:
    """Return the ``sha256:`` raw digest of one stable regular file (streaming)."""

    target = Path.cwd() / Path(path) if not Path(path).is_absolute() else Path(path)
    before, _payload = _observe_file(
        target.parent, target.name, max_bytes=RAW_DIGEST_BUDGET
    )
    _require_same_observation(before)
    return before.digest


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


def _require_exact_keys(document: object, keys: frozenset[str], field: str) -> None:
    if not isinstance(document, Mapping) or set(document) != keys:
        raise _schema("the document has an unexpected shape", field)


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
    latency = document["latency"]
    if not isinstance(latency, list):
        raise _schema("PR15D latency lanes must be a list", "latency")
    for lane in latency:
        if not isinstance(lane, Mapping):
            raise _schema("a PR15D lane must be an object", "latency")
        _require_exact_keys(lane, PR15D_LANE_KEYS, "latency")
        lane_id = lane["id"]
        if type(lane_id) is not str:
            raise _schema("a PR15D lane id must be a string", "id")
        if lane_id not in lanes:
            raise _identity("the PR15D aggregate contains an unregistered lane", "id")
        n, class_name, k = lanes[lane_id]
        for field in ("n", "k"):
            if type(lane[field]) is not int:
                raise _schema("a PR15D coordinate must be an exact integer", field)
        for field in ("class", "regime", "field", "term"):
            if type(lane[field]) is not str:
                raise _schema("a PR15D lane string field is mistyped", field)
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
            _exact_positive(engine_record["dispersion_max_over_min"], "dispersion_max_over_min")
        comparisons = lane["comparisons"]
        if not isinstance(comparisons, Mapping) or set(comparisons) != set(PR15D_COMPARATORS):
            raise _schema("a PR15D lane needs both comparator entries", "comparisons")
        for engine in PR15D_COMPARATORS:
            entry = comparisons[engine]
            _require_exact_keys(entry, PR15D_COMPARISON_KEYS, "comparisons")
            _exact_positive(entry["engine_over_quervant_ratio"], "engine_over_quervant_ratio")
            _exact_positive(entry["quervant_over_engine_speedup"], "quervant_over_engine_speedup")
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
    if type(document["protocol_sha256"]) is not str:
        raise _schema("the retained analysis protocol must be a string", "protocol_sha256")
    if document["protocol_sha256"] != RETAINED_PROTOCOL:
        raise _identity("the retained analysis protocol differs", "protocol_sha256")
    series = document["series"]
    if not isinstance(series, list) or any(type(campaign) is not str for campaign in series):
        raise _schema("the retained analysis series must be a list of strings", "series")
    if series != list(RETAINED_CAMPAIGNS):
        raise _identity("the retained analysis series is unexpected", "series")
    lanes = document["lanes"]
    registered = set(relative_effects.lane_ids(relative_effects.STUDY_RETAINED_KEY))
    if not isinstance(lanes, Mapping):
        raise _schema("retained analysis lanes must be an object", "lanes")
    if set(lanes) != registered:
        raise _identity("the retained analysis lane set is incomplete", "lanes")
    rows: list[dict[str, Any]] = []
    for lane_id in sorted(lanes):
        lane = lanes[lane_id]
        if not isinstance(lane, Mapping):
            raise _schema("a retained lane must be an object", "lanes")
        _require_exact_keys(lane, RETAINED_LANE_KEYS, "lanes")
        if type(lane["id"]) is not str:
            raise _schema("a retained lane id must be a string", "id")
        if lane["id"] != lane_id:
            raise _schema("a retained lane record disagrees with its identity", "lanes")
        _text, n_text, class_name, k_text = lane_id.split("/")
        for field in ("n", "k"):
            if type(lane[field]) is not int:
                raise _schema("a retained coordinate must be an exact integer", field)
        if type(lane["class"]) is not str:
            raise _schema("a retained class must be a string", "class")
        if (lane["n"], lane["class"], lane["k"]) != (int(n_text), class_name, int(k_text[1:])):
            raise _identity("retained lane coordinates disagree with their identity", "lanes")
        campaigns = lane["campaigns"]
        if not isinstance(campaigns, Mapping):
            raise _schema("retained campaigns must be an object", "campaigns")
        if set(campaigns) != set(RETAINED_CAMPAIGNS):
            raise _identity("a retained lane needs both campaigns", "campaigns")
        for campaign in RETAINED_CAMPAIGNS:
            record = campaigns[campaign]
            if not isinstance(record, Mapping):
                raise _schema("a retained campaign record must be an object", "campaigns")
            _require_exact_keys(record, RETAINED_CAMPAIGN_KEYS, "campaigns")
            retained = record["retained"]
            if not isinstance(retained, list) or any(type(block) is not int for block in retained):
                raise _schema("retained blocks must be a list of exact integers", "retained")
            if (
                not 4 <= len(retained) <= 12
                or retained != sorted(set(retained))
                or any(block not in range(1, 13) for block in retained)
            ):
                raise _identity("the retained block list is invalid", "retained")
            if type(record["retained_count"]) is not int or record["retained_count"] != len(retained):
                raise _identity("retained_count disagrees with the block list", "retained_count")
            cap = _retained_cap(lane["n"], lane["class"])
            cap_value = _exact_positive(record["cap"], "cap")
            if cap_value != cap:
                raise _identity("the retained cap is unexpected", "cap")
            excluded = record["excluded"]
            if not isinstance(excluded, list):
                raise _schema("the excluded block list must be a list", "excluded")
            complement = [block for block in range(1, 13) if block not in retained]
            for item in excluded:
                if not isinstance(item, Mapping) or "block" not in item:
                    raise _schema("an excluded block record has an unexpected shape", "excluded")
                if type(item["block"]) is not int:
                    raise _schema("an excluded block id must be an exact integer", "excluded")
            if [item["block"] for item in excluded] != complement:
                raise _identity("the excluded block set is not the complement", "excluded")
            for item in excluded:
                if not isinstance(item, Mapping) or set(item) != {"block", "within", "arms"}:
                    raise _schema("an excluded block record has an unexpected shape", "excluded")
                within = item["within"]
                if not isinstance(within, Mapping) or set(within) != set(RETAINED_ARMS):
                    raise _schema("an excluded block needs every arm", "within")
                for arm in RETAINED_ARMS:
                    _exact_positive(within[arm], "within")
                arms = item["arms"]
                if not isinstance(arms, list) or any(type(arm) is not str for arm in arms):
                    raise _schema("excluded arms must be a list of strings", "arms")
                if arms != [arm for arm in RETAINED_ARMS if within[arm] > cap]:
                    raise _identity("the excluded arms disagree with the ratios", "arms")
                if not arms:
                    raise _identity("an excluded block must violate the cap", "arms")
            for field in ("latency", "raw_latency"):
                table = record[field]
                if not isinstance(table, Mapping) or set(table) != set(RETAINED_ARMS):
                    raise _schema("a latency table needs every arm", field)
                for arm in RETAINED_ARMS:
                    _exact_positive(table[arm], field)
            raw_ratio = record["raw_ratio"]
            if not isinstance(raw_ratio, Mapping) or set(raw_ratio) != {"L", "P", "H"}:
                raise _schema("raw_ratio needs L, P and H", "raw_ratio")
            for arm in ("L", "P", "H"):
                _exact_positive(raw_ratio[arm], "raw_ratio")
            if type(record["filter_sensitive"]) is not bool:
                raise _schema("filter_sensitive must be boolean", "filter_sensitive")
            for ratio_field, ci_field, baseline, treatment in relative_effects.RETAINED_FIELDS:
                _exact_positive(record[ratio_field], ratio_field)
                interval = record[ci_field]
                if not isinstance(interval, Mapping) or set(interval) != {"low", "high", "seed"}:
                    raise _schema("a retained effect needs its original interval", ci_field)
                for endpoint in ("low", "high"):
                    _exact_positive(interval[endpoint], ci_field)
                if type(interval["seed"]) is not int:
                    raise _schema("a retained interval seed must be an exact integer", ci_field)
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


def _archive_bound() -> int:
    return ArchiveLimits().max_archive_bytes


def _source_root(source_root: Path | None) -> Path:
    """Use the explicit source checkout or the package's repository root."""

    return Path(source_root) if source_root is not None else repository_root()


def _retained_archive_paths(
    provider: Path, member: str, campaign: str
) -> tuple[Path, str, str]:
    """Return ``(parent, archive basename, sidecar basename)`` for one retained archive."""

    validated = validate_relative_member(member)
    if type(campaign) is not str or campaign not in (RETAINED_CONTROL, *RETAINED_CAMPAIGNS):
        raise _identity("the retained campaign is not a fixed archivable campaign", "campaign")
    basename = f"{campaign}.tar.gz"
    if Path(validated).name != basename:
        raise _identity("the retained archive basename is unexpected", "path")
    return provider / Path(validated).parent, basename, basename + ".sha256"


def _read_archive(
    provider: Path,
    member: str,
    record: SourceRecord,
    observations: list[_FileObservation],
) -> tuple[str, str]:
    parent, basename, sidecar = _retained_archive_paths(provider, member, record.identity)
    try:
        sidecar_observation, sidecar_payload = _observe_file(
            parent, sidecar, max_bytes=MAX_HISTORY_BYTES, capture=True
        )
    except BenchError as error:
        if error.code == BM_FILE_MISSING:
            raise _DependencyUnavailable("sidecar") from error
        raise
    observations.append(sidecar_observation)
    assert sidecar_payload is not None
    sidecar_document = _parse(sidecar_payload, sidecar, decimals=False)
    members = sidecar_document.get("members")
    if not isinstance(members, Mapping) or not members:
        raise _schema("the retained sidecar needs its member map", "sidecar")
    names = []
    for name in members:
        if type(name) is not str:
            raise _schema("a sidecar member name must be a string", "sidecar")
        names.append(validate_relative_member(name))
    if len({name.casefold() for name in names}) != len(names):
        raise _identity("the retained sidecar has case-colliding members", "sidecar")
    from .historical import audit_retained_key_archive

    try:
        audit = audit_retained_key_archive(parent, record.identity, limits=ArchiveLimits())
    except BenchError as error:
        if error.code in (BM_FILE_MISSING, BM_EVIDENCE_UNAVAILABLE):
            raise _identity("an observed archive input became unavailable", "path") from error
        raise
    except OSError as error:
        raise _unsafe("an observed archive input could not be read", "path") from error
    if audit.archive_digest != record.digest:
        raise _identity("the retained archive differs from its frozen digest", "archive")
    if audit.manifest_protocol_digest != RETAINED_PROTOCOL:
        raise _identity("the retained archive protocol differs", "archive")
    return (
        STATUS_FOUND,
        "authenticated-archive;replay-unavailable:shared-projector",
    )


def _read_micro(payload: bytes, member: str) -> tuple[str, str]:
    from .policy_inputs import validate_micro_table

    validate_micro_table(_parse(payload, member, decimals=False))
    return STATUS_UNVERIFIED, "no-independent-raw-digest"


F1_SOURCE_PATHS = (
    "benchmarks/pr15i_d3_c_t7/analysis.py",
    "benchmarks/pr15i_d3_c_t7/policy.py",
    "benchmarks/pr15i_d3_c_t7/verify_derived.py",
    "benchmarks/pr15i_d3_c_t7/freeze.py",
)


def _f1_file_map(document: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate the fixed F1 receipt identity map and return its four source paths."""

    if not isinstance(document, Mapping):
        raise _schema("the F1 receipt must be an object", "receipt")
    if type(document.get("t7_commit")) is not str or document["t7_commit"] != RETAINED_F1:
        raise _identity("the F1 receipt names another source revision", "t7_commit")
    files = document.get("files")
    if not isinstance(files, Mapping) or set(files) != {
        "analysis.py", "policy.py", "verify_derived.py", "freeze.py"
    }:
        raise _schema("the F1 receipt needs its four frozen sources", "files")
    for name, value in files.items():
        if type(value) is not str or len(value) != 64:
            raise _schema("an F1 source digest must be 64 hex characters", "files")
        if any(character not in "0123456789abcdef" for character in value):
            raise _schema("an F1 source digest must be lowercase hex", "files")
    return F1_SOURCE_PATHS


def _read_f1(
    provider: Path,
    member: str,
    payload: bytes,
    before: _FileObservation,
    source_root: Path | None,
    observations: list[_FileObservation],
) -> tuple[str, str]:
    from .policy_inputs import _f1_identity

    root = _source_root(source_root)
    _f1_file_map(_parse(payload, member, decimals=False))
    source_observations: list[_FileObservation] = []
    for relative in F1_SOURCE_PATHS:
        try:
            observation, _none = _observe_file(root, relative, max_bytes=MAX_HISTORY_BYTES)
        except BenchError as error:
            if error.code == BM_FILE_MISSING:
                raise _DependencyUnavailable("source") from error
            raise
        observations.append(observation)
        source_observations.append(observation)
    try:
        digest, sources = _f1_identity(provider / member, root)
    except BenchError as error:
        if error.code in (BM_FILE_MISSING, BM_EVIDENCE_UNAVAILABLE):
            raise _identity("an observed F1 input became unavailable", "path") from error
        raise
    except OSError as error:
        raise _unsafe("an observed F1 input could not be read", "path") from error
    if digest != before.digest:
        raise _identity("the F1 receipt identity changed", "receipt")
    if set(sources) != set(F1_SOURCE_PATHS):
        raise _identity("the F1 owner returned another source set", "files")
    for observation, relative in zip(source_observations, F1_SOURCE_PATHS):
        if sources[relative] != observation.digest:
            raise _identity("an F1 source digest disagrees with its observation", relative)
    return STATUS_FOUND, "authenticated-receipt"


T6_REQUIRED = {
    "schema": "pr15i-d3c-freeze-v1",
    "protocol_sha256": RETAINED_PROTOCOL,
    "control_name": RETAINED_CONTROL,
    "campaign_names": list(RETAINED_CAMPAIGNS),
    "t6_commit": RETAINED_T6,
    "tooling_manifest_sha256": T6_TOOLING_MANIFEST_RAW,
}


def _t6_known_fields(document: Mapping[str, Any]) -> None:
    """Validate the seven known T6 fields as a subset; unrelated metadata is allowed."""

    if not isinstance(document, Mapping):
        raise _schema("the T6 receipt must be an object", "receipt")
    for field, expected in T6_REQUIRED.items():
        if field not in document:
            raise _schema("the T6 receipt is missing a required field", field)
        actual = document[field]
        if field == "campaign_names":
            if not isinstance(actual, list) or list(actual) != expected:
                raise _identity("the T6 receipt campaign order is unexpected", field)
            continue
        if type(actual) is not str or actual != expected:
            raise _identity("the T6 receipt field is unexpected", field)
    files = document.get("protected_files")
    if not isinstance(files, Mapping) or not files:
        raise _schema("the T6 receipt needs its protected files", "protected_files")
    for path, value in files.items():
        if type(path) is not str:
            raise _schema("a protected path must be a string", "protected_files")
        validate_relative_member(path)
        if type(value) is not str or len(value) != 64:
            raise _schema("a protected-file digest must be 64 hex characters", "protected_files")
        if any(character not in "0123456789abcdef" for character in value):
            raise _schema("a protected-file digest must be lowercase hex", "protected_files")


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
POLICY_ROW_KEYS_F1 = frozenset(
    {"k", "selected_strategy", "decision_status", "P_status", "H_status",
     "P_reasons", "H_reasons", "filter_sensitive", "P_gm", "H_gm", "H_memory"}
)
POLICY_ROW_KEYS_F2 = frozenset(
    {"k", "selected_strategy", "decision_status", "P_status", "H_status",
     "P_reasons", "H_reasons", "filter_sensitive", "H_memory"}
)


def _exact_positive(value: object, field: str) -> Decimal | int:
    """Summary numbers: exactly int or Decimal, finite and positive."""

    if type(value) not in (int, Decimal):
        raise _schema("expected an exact JSON number", field)
    if type(value) is Decimal:
        if not value.is_finite():
            raise _schema("expected a finite number", field)
    if value <= 0:
        raise _schema("expected a positive number", field)
    return value


def _ordinary_positive(value: object, field: str) -> float | int:
    """Ordinary metadata numbers: exactly int or float, finite and positive."""

    if type(value) not in (int, float):
        raise _schema("expected an ordinary JSON number", field)
    if type(value) is float and not math.isfinite(value):
        raise _schema("expected a finite number", field)
    if value <= 0:
        raise _schema("expected a positive number", field)
    return value


def _read_policy(document: Mapping[str, Any]) -> None:
    _require_exact_keys(document, POLICY_KEYS, "policy")
    schema = document["schema"]
    if type(schema) is not str or schema not in POLICY_SCHEMAS:
        raise _schema("unexpected retained policy schema", "schema")
    if type(document["protocol_sha256"]) is not str or document["protocol_sha256"] != RETAINED_PROTOCOL:
        raise _identity("the retained policy protocol differs", "protocol_sha256")
    if type(document["status"]) is not str or document["status"] != POLICY_STATUS:
        raise _identity("the retained policy status is unexpected", "status")
    rows = document["rows"]
    if not isinstance(rows, list) or len(rows) != len(RETAINED_K_VALUES):
        raise _identity("the retained policy needs nine rows", "rows")
    keys = POLICY_ROW_KEYS_F1 if schema == POLICY_SCHEMAS[0] else POLICY_ROW_KEYS_F2
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != keys:
            raise _schema("a retained policy row has an unexpected shape", "rows")
        if type(row["k"]) is not int or row["k"] != RETAINED_K_VALUES[index]:
            raise _identity("the retained policy K order is unexpected", "rows")
        for field, allowed in (
            ("selected_strategy", POLICY_SELECTED),
            ("decision_status", POLICY_DECISIONS),
            ("P_status", POLICY_ELIGIBILITY),
            ("H_status", POLICY_ELIGIBILITY),
        ):
            value = row[field]
            if type(value) is not str or value not in allowed:
                raise _schema("an unexpected retained policy label", field)
        if row["decision_status"] == "SELECTED_GM_CONFIRMED" and schema != POLICY_SCHEMAS[1]:
            raise _identity("only the verified schema may confirm a GM selection", "rows")
        for field in ("P_reasons", "H_reasons"):
            reasons = row[field]
            if not isinstance(reasons, list) or any(type(item) is not str for item in reasons):
                raise _schema("policy reasons must be strings", field)
        if type(row["filter_sensitive"]) is not bool:
            raise _schema("policy filter_sensitive must be boolean", "filter_sensitive")
        memory = row["H_memory"]
        if memory is not None and (type(memory) is not int or memory < 0):
            raise _schema("H_memory must be null or a non-negative integer", "H_memory")
        if schema == POLICY_SCHEMAS[0]:
            for field in ("P_gm", "H_gm"):
                values = row[field]
                if not isinstance(values, list) or len(values) != 2:
                    raise _schema("a GM array needs two values", field)
                for value in values:
                    _ordinary_positive(value, field)


PR15D_EVIDENCE_MANIFEST = "docs/pr-artifacts/pr-15d/b-evidence-manifest.json"
PR15D_UNPUBLISHED = ("README.md", "SHA256SUMS", "run.json")


def _pr15d_binding(
    manifest: Mapping[str, Any],
    members: Sequence[Any],
    *,
    archive_digest: str,
    archive_bytes: int,
) -> None:
    """Pure binding check of the committed manifest against inspected members."""

    if not isinstance(manifest, Mapping):
        raise _schema("the PR15D evidence manifest must be an object", "manifest")
    if manifest.get("schema") != "pr15d-evidence-manifest-v1":
        raise _schema("unexpected PR15D evidence manifest schema", "manifest")
    if manifest.get("run_id") != PR15D_RUN or manifest.get("source_sha") != PR15D_SOURCE:
        raise _identity("the PR15D evidence manifest names another run", "manifest")
    package = manifest.get("package")
    if not isinstance(package, Mapping) or set(package) != {"path", "bytes", "sha256"}:
        raise _schema("the PR15D manifest needs its package record", "package")
    if type(package["path"]) is not str or type(package["sha256"]) is not str:
        raise _schema("the PR15D package path and digest must be strings", "package")
    if type(package["bytes"]) is not int:
        raise _schema("the PR15D package length must be an exact integer", "package")
    if Path(package["path"]).name != f"{PR15D_RUN}.zip":
        raise _identity("the PR15D package path is unexpected", "package")
    if package["bytes"] != PR15D_ARCHIVE_BYTES:
        raise _identity("the PR15D package length is unexpected", "package")
    if package["sha256"] != PR15D_ARCHIVE_DIGEST_HEX:
        raise _identity("the PR15D package hash is unexpected", "package")
    if type(archive_bytes) is not int or type(archive_digest) is not str:
        raise _schema("the archive observation has mistyped identity fields", "archive")
    if archive_bytes != package["bytes"] or archive_digest != "sha256:" + package["sha256"]:
        raise _identity("the inspected archive differs from the manifest package", "package")
    names = manifest.get("members")
    if not isinstance(names, list):
        raise _schema("the PR15D member set must be a list", "members")
    if len(names) != 68:
        raise _identity("the PR15D manifest needs 68 members", "members")
    normalized = []
    for name in names:
        if type(name) is not str:
            raise _schema("a PR15D member name must be a string", "members")
        normalized.append(validate_relative_member(name))
    if len({name.casefold() for name in normalized}) != len(normalized):
        raise _identity("the PR15D manifest has case-colliding members", "members")
    published: dict[str, tuple[int, str]] = {}
    published_folded: set[str] = set()
    groups = (
        ("raw_manifests", 9, False),
        ("contention_records", 54, False),
        ("resources", 1, True),
        ("validation", 1, True),
    )
    for group, expected_count, singleton in groups:
        records = manifest.get(group)
        if singleton:
            if not isinstance(records, Mapping):
                raise _schema("the PR15D manifest singleton group must be an object", group)
            entries = [records]
        else:
            if not isinstance(records, list):
                raise _schema("a PR15D manifest member group must be a list", group)
            if len(records) != expected_count:
                raise _identity("a PR15D manifest member group is incomplete", group)
            entries = records
        for item in entries:
            if not isinstance(item, Mapping) or set(item) != {"path", "bytes", "sha256"}:
                raise _schema("a PR15D manifest member has an unexpected shape", group)
            path = item["path"]
            if type(path) is not str:
                raise _schema("a PR15D member path must be a string", group)
            path = validate_relative_member(path)
            if type(item["bytes"]) is not int or item["bytes"] < 0:
                raise _schema("a PR15D member length must be a non-negative integer", group)
            sha = item["sha256"]
            if type(sha) is not str or len(sha) != 64:
                raise _schema("a PR15D member hash must be 64 hex characters", group)
            if any(character not in "0123456789abcdef" for character in sha):
                raise _schema("a PR15D member hash must be lowercase hex", group)
            if path.casefold() in published_folded:
                raise _schema("a PR15D member is published twice or case-collides", group)
            published_folded.add(path.casefold())
            published[path] = (item["bytes"], sha)
    if not set(published) <= set(normalized):
        raise _identity("a published member is absent from the full member set", "members")
    if set(normalized) - set(published) != set(PR15D_UNPUBLISHED):
        raise _identity("the unpublished member set is unexpected", "members")
    if not isinstance(members, (list, tuple)):
        raise _schema("inspected members must be a sequence of member records", "archive")
    inspected: dict[str, tuple[int, str]] = {}
    inspected_folded: set[str] = set()
    for member in members:
        if not isinstance(member, MemberDigest):
            raise _schema("an inspected member must be a MemberDigest", "archive")
        name = member.name
        if type(name) is not str:
            raise _schema("an inspected member name must be a string", "archive")
        name = validate_relative_member(name)
        if name.casefold() in inspected_folded:
            raise _schema("the archive repeats or case-collides a member", "archive")
        inspected_folded.add(name.casefold())
        if type(member.byte_length) is not int or member.byte_length < 0:
            raise _schema("an inspected member length must be a non-negative integer", "archive")
        if (
            type(member.digest) is not str
            or not member.digest.startswith("sha256:")
            or len(member.digest) != 71
            or any(character not in "0123456789abcdef" for character in member.digest[7:])
        ):
            raise _schema("an inspected member digest must be a prefixed lowercase hash", "archive")
        inspected[name] = (member.byte_length, member.digest.removeprefix("sha256:"))
    if set(inspected) != set(normalized):
        raise _identity("the archive member set differs from the manifest", "archive")
    for name, (length, sha) in published.items():
        if inspected.get(name) != (length, sha):
            raise _identity("an archive member differs from the manifest", name)


PR15D_ARCHIVE_DIGEST_HEX = "426dff2920b55ff63766da284421cf698f9950011da409b88a33be5d6d4e7bab"


def _read_pr15d_archive(
    provider: Path,
    member: str,
    before: _FileObservation,
    source_root: Path | None,
    observations: list[_FileObservation],
) -> tuple[str, str]:
    root = _source_root(source_root)
    try:
        manifest_observation, manifest_payload = _observe_file(
            root, PR15D_EVIDENCE_MANIFEST, max_bytes=MAX_HISTORY_BYTES, capture=True
        )
    except BenchError as error:
        if error.code == BM_FILE_MISSING:
            raise _DependencyUnavailable("source") from error
        raise
    observations.append(manifest_observation)
    if manifest_observation.digest != "sha256:" + PR15D_EVIDENCE_MANIFEST_RAW:
        raise _identity("the PR15D evidence manifest differs from its pinned hash", "manifest")
    assert manifest_payload is not None
    manifest = _parse(manifest_payload, PR15D_EVIDENCE_MANIFEST, decimals=False)
    try:
        members = inspect_zip(provider, member, ArchiveLimits())
    except BenchError as error:
        if error.code in (BM_FILE_MISSING, BM_EVIDENCE_UNAVAILABLE):
            raise _identity("an observed PR15D input became unavailable", "path") from error
        raise
    except OSError as error:
        raise _unsafe("an observed PR15D input could not be read", "path") from error
    _pr15d_binding(
        manifest,
        members,
        archive_digest=before.digest,
        archive_bytes=before.byte_length,
    )
    return (
        STATUS_FOUND,
        "authenticated-archive;replay-unavailable:shared-projector",
    )


def _entry(status: str, reason: str, digest: str | None, rows=None) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "input_digest": digest,
        "normalized_rows": rows or [],
    }


def _role_bound(role: str) -> int:
    return _archive_bound() if role in ("retained-archive", "pr15d-archive") else MAX_HISTORY_BYTES


def _needs_payload(role: str) -> bool:
    return role not in ("retained-archive", "pr15d-archive")


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
    provider = Path(provider_root)
    try:
        member = validate_relative_member(validated["path"])
    except BenchError as error:
        entry.update(_entry(STATUS_INVALID, f"unsafe-path:{error.code}", None))
        return entry
    try:
        before, payload = _observe_file(
            provider,
            member,
            max_bytes=_role_bound(role),
            capture=_needs_payload(role),
        )
    except BenchError as error:
        if error.code == BM_FILE_MISSING:
            return entry
        reason = (
            f"changed-during-read:{error.code}"
            if error.code == BM_IDENTITY_INVALID and error.field_path == "path"
            else f"unsafe-input:{error.code}"
        )
        entry.update(_entry(STATUS_INVALID, reason, None))
        return entry
    observations = [before]
    entry["input_digest"] = before.digest
    record = record_for(role, identity)
    if record is None:
        entry.update(_entry(STATUS_UNVERIFIED, "unsupported-source-identity", before.digest))
        return _finalise(entry, observations)
    declared = validated["expected_digest"]
    if record.digest is not None and declared != record.digest:
        entry.update(
            _entry(STATUS_INVALID, "declared-digest-conflicts-with-independent-anchor", before.digest)
        )
        return entry
    if record.digest is not None and before.digest != record.digest:
        entry.update(_entry(STATUS_INVALID, "digest-mismatch", before.digest))
        return entry
    if record.digest is None and declared is not None and declared != before.digest:
        entry.update(_entry(STATUS_INVALID, "digest-mismatch", before.digest))
        return entry
    try:
        status, reason, rows = _dispatch(
            record, role, provider, member, before, payload, source_root, observations
        )
    except _DependencyUnavailable as unavailable:
        entry.update(
            _entry(
                STATUS_UNVERIFIED,
                f"owning-reader-{unavailable.kind}-unavailable",
                before.digest,
            )
        )
        return _finalise(entry, observations)
    except BenchError as error:
        reason = (
            f"changed-during-read:{error.code}"
            if error.code == BM_IDENTITY_INVALID and error.field_path == "path"
            else f"{error.code}:{error.field_path or 'input'}"
        )
        entry.update(_entry(STATUS_INVALID, reason, before.digest))
        return entry
    entry.update(_entry(status, reason, before.digest, rows))
    return _finalise(entry, observations)


def _recheck(observations: Sequence[_FileObservation]) -> None:
    for observation in observations:
        _require_same_observation(observation)


def _finalise(
    entry: dict[str, Any], observations: Sequence[_FileObservation]
) -> dict[str, Any]:
    """Recheck every recorded observation; a change downgrades the result to INVALID."""

    try:
        _recheck(observations)
    except BenchError as error:
        return {
            "input_role": entry["input_role"],
            "source_identity": entry["source_identity"],
            "input_digest": entry["input_digest"],
            "status": STATUS_INVALID,
            "reason": f"changed-during-read:{error.code}",
            "normalized_rows": [],
        }
    return entry


def _dispatch(
    record: SourceRecord,
    role: str,
    provider: Path,
    member: str,
    before: _FileObservation,
    payload: bytes | None,
    source_root: Path | None,
    observations: list[_FileObservation],
) -> tuple[str, str, list[dict[str, Any]]]:
    if record.reader == "archive":
        status, reason = _read_archive(provider, member, record, observations)
        return status, reason, []
    if record.reader == "pr15d-archive":
        status, reason = _read_pr15d_archive(provider, member, before, source_root, observations)
        return status, reason, []
    assert payload is not None
    if record.reader == "micro":
        status, reason = _read_micro(payload, member)
        return status, reason, []
    if record.reader == "f1-receipt":
        status, reason = _read_f1(provider, member, payload, before, source_root, observations)
        return status, reason, []
    if record.reader == "t6-receipt":
        _t6_known_fields(_parse(payload, member, decimals=False))
        return STATUS_FOUND, "authenticated-historical-receipt", []
    if record.reader == "pr15d-aggregate":
        _parse(payload, member, decimals=False)
        document = _parse(payload, member, decimals=True)
        return (
            STATUS_FOUND,
            "authenticated-as-reported-summary",
            pr15d_aggregate_rows(document, input_digest=before.digest),
        )
    if record.reader == "retained-analysis":
        _parse(payload, member, decimals=False)
        document = _parse(payload, member, decimals=True)
        return (
            STATUS_FOUND,
            "authenticated-as-reported-summary",
            retained_analysis_rows(document, input_digest=before.digest),
        )
    if record.reader == "retained-policy":
        _read_policy(_parse(payload, member, decimals=False))
        return STATUS_FOUND, "authenticated-policy-metadata", []
    raise _schema("the catalog names an unknown reader", "reader")  # pragma: no cover


def build_entries(
    provider_root: Path, inventory: Mapping[str, Any], *, source_root: Path | None = None
) -> list[dict[str, Any]]:
    """Authenticate every inventory candidate under ``provider_root``."""

    validated = validate_inventory(inventory)
    return [
        classify_candidate(provider_root, candidate, source_root=source_root)
        for candidate in validated["candidates"]
    ]


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
    if not rows:
        return dict(entry)
    expected = _summary_metadata(role)
    for row in relative_effects.unique_rows(rows, current=False):
        if row["input_digest"] != digest:
            raise _identity("a historical row cites another source digest", "normalized_rows")
        if row["evidence_level"] != relative_effects.EVIDENCE_AS_REPORTED:
            raise _identity("a summary row is AS_REPORTED, never recomputed", "normalized_rows")
        _check_summary_row(row, expected)
    return dict(entry)


def _summary_metadata(role: str) -> dict[str, str]:
    if role == "pr15d-aggregate":
        return {
            "study_id": relative_effects.STUDY_CROSS_ENGINE,
            "run_id": PR15D_RUN,
            "campaign_id": "three-trial-backend",
            "source_commit": PR15D_SOURCE,
            "method_id": relative_effects.HISTORICAL_CROSS_METHOD_ID,
        }
    if role == "retained-analysis":
        return {
            "study_id": relative_effects.STUDY_RETAINED_KEY,
            "campaign_id": "",
            "source_commit": RETAINED_EXPERIMENT,
            "method_id": relative_effects.RETAINED_METHOD_ID,
        }
    return {}


def _check_summary_row(row: Mapping[str, Any], expected: Mapping[str, str]) -> None:
    if not expected:
        raise _identity("only the two summary roles contribute rows", "normalized_rows")
    for field, value in expected.items():
        if value and row[field] != value:
            raise _identity("a summary row cites another fixed identity", "normalized_rows")
    if expected["study_id"] == relative_effects.STUDY_RETAINED_KEY:
        if row["campaign_id"] not in RETAINED_CAMPAIGNS:
            raise _identity("a retained row names another campaign", "normalized_rows")
        if row["run_id"] != row["campaign_id"]:
            raise _identity("a retained row run must equal its campaign", "normalized_rows")
    elif row["run_id"] != PR15D_RUN:
        raise _identity("a cross-engine summary row cites another run", "normalized_rows")


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

    root = Path(operation_root)
    observed: dict[str, Any] = {}
    observations: list[_FileObservation] = []
    captured: list[tuple[str, str, bytes]] = []
    for name, kind in (
        ("history-report.json", REPORT_KIND),
        ("relative-effects.json", relative_effects.ROWS_KIND),
    ):
        try:
            before, payload = _observe_file(
                root, name, max_bytes=MAX_HISTORY_BYTES, capture=True
            )
        except BenchError as error:
            if error.code == BM_FILE_MISSING:
                raise BenchError(
                    BM_EVIDENCE_UNAVAILABLE,
                    "a baseline disclosure is unavailable",
                    field_path=name,
                ) from error
            raise
        observations.append(before)
        assert payload is not None
        captured.append((name, kind, payload))
    for name, kind, payload in captured:
        document = _parse(payload, name, decimals=False)
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
    _recheck(observations)
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
