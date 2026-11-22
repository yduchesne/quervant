"""PERF-02-B bounded warm sort-path diagnostics (bench-only, never a benchmark run).

This module is a *measurement helper* for one diagnostic campaign. It

* generates the fixed diagnostic JSONL request streams (no timestamps, no
  randomness, byte-identical when regenerated),
* validates every adapter reply against the independent
  :func:`quervant_bench.lean.runtime.expected_answer` oracle and summarizes only
  the query-only ``engine_ns`` values of the ``sample`` rows,
* classifies saved ``perf script`` call-stack samples into nonoverlapping
  query/sort buckets.

It never executes ``quervant-bench run``, never times anything itself, never
spawns a subprocess, never touches production Rust source, and never publishes a
``benchmark-result-v1`` artifact. Every summary it writes is explicitly labelled
``mode=diagnostic-unqualified`` and ``timed_campaign=false``.

Three commands only::

    python -m quervant_bench.lean.perf02b_diagnostics inputs \\
        --config <A=A-config> --output-dir target/perf02b
    python -m quervant_bench.lean.perf02b_diagnostics verify \\
        --config <A=A-config> --request-file <jsonl> --response-file <jsonl> \\
        --output target/perf02b/validated/<name>.json
    python -m quervant_bench.lean.perf02b_diagnostics summarize \\
        --config <A=A-config> --output-dir target/perf02b
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .artifacts import ArtifactError, load_configuration
from .configuration import lanes_for, validate_configuration
from .runtime import ADAPTER_SCHEMA, MeasurementBlocked, expected_answer, validate_reply

DIAGNOSTIC_MODE = "diagnostic-unqualified"
INPUTS_MANIFEST_SCHEMA = "perf02b-inputs-manifest-v1"
VALIDATED_SCHEMA = "perf02b-validated-lane-record-v1"
SUMMARY_SCHEMA = "perf02b-diagnostic-summary-v1"

BASELINE_WARMUPS = 10
BASELINE_SAMPLES = 50
PROFILE_WARMUPS = 100
PROFILE_SAMPLES = 800
MIN_QUERY_SAMPLES = 400
MIN_ATTRIBUTABLE_FRACTION = 0.85
SAMPLE_DECIMALS = 1

STUDY_TAIL = ("benchmarks", "studies", "perf-02", "warm", "configurations")
BASELINE_SIZES = (10_000, 100_000)
BASELINE_FILES = {
    10_000: "baseline-n10000.jsonl",
    100_000: "baseline-n100000.jsonl",
}

# Fixed primary lane order. The four profile files are emitted and classified in
# exactly this order; no lane may be substituted.
PRIMARY_LANES: tuple[tuple[str, str], ...] = (
    ("medium-k10", "100000/medium/k10/warm"),
    ("medium-k100", "100000/medium/k100/warm"),
    ("common-k10", "100000/common/k10/warm"),
    ("common-k100", "100000/common/k100/warm"),
)
PROFILE_FILES = {slug: f"profile-n100000-{slug}.jsonl" for slug, _ in PRIMARY_LANES}
PROFILE_LANE_IDS = frozenset(lane_id for _, lane_id in PRIMARY_LANES)
PROFILE_LANE_FOR_SLUG = dict(PRIMARY_LANES)

REQUEST_ID = re.compile(
    r"^(?P<phase>baseline|profile):(?P<lane>[^:]+):(?P<kind>warmup|sample):(?P<index>\d+)$"
)
LANE_ID = re.compile(r"^(?P<n>\d+)/(?P<cls>[a-z]+)/k(?P<k>\d+)/(?P<regime>warm)$")
PINNED_REVISION = re.compile(r"^[0-9a-f]{40}$")

# perf script record layout: ``<comm> <pid>/<tid> <time>: <event>: <rest>``
PERF_HEADER = re.compile(
    r"^(?P<comm>\S+)\s+(?P<pid>\d+)/(?P<tid>\d+)\s+(?P<time>\d+(?:\.\d+)?):\s+"
    r"(?P<event>[^\s:]+(?::[A-Za-z]+)?):\s*(?P<rest>.*)$"
)
# Callchain frame: ``\t  <ip> <sym> (<dso>)``; ``[unknown]`` means unsymbolized.
PERF_FRAME = re.compile(r"^\s+(?P<ip>[0-9a-fA-F]+)\s+(?P<sym>.*?)\s+\((?P<dso>[^)]*)\)\s*$")
UNSYMBOLIZED = frozenset({"", "[unknown]", "unknown", "??"})
PROCESS_PREFIX = "pr15d-quervant"
CPU_CLOCK_EVENT = "cpu-clock"

# Fixed, demangled-symbol substring rules. Bare ``search``/``sort``/``column``
# words are deliberately absent: they would match unrelated functions.
QUERY_MARKERS = (
    "UnifiedSearcher::search",
    "UnifiedSearcher::collect_mixed",
    "evaluate_lexical_with",
    "quervant_core::search::unified::",
    "quervant_core::search::execute::",
)
SORT_MARKERS = (
    "consider_borrowed_keyword_candidate",
    "keyword_sort_view",
    "compare_borrowed_keyword_to_owned",
    "owned_keyword_sort_value",
    "materialize_keyword_entry",
    "admit_legacy_keyword_candidate",
    "sort_tuple_for_doc",
)
ROOT_MARKERS = ("UnifiedSearcher::search", "UnifiedSearcher::collect_mixed")
# Bounded, explicitly identifiable process-startup / index-open / transport
# overhead. Anything else that is not a query stack is UNKNOWN, not startup.
STARTUP_MARKERS = (
    "__libc_start_main",
    "std::rt::lang_start",
    "lang_start_internal",
    "pr15d_quervant_adapter::main",
    "std::sys::pal::unix::",
)


class DiagnosticError(ArtifactError):
    """A PERF-02-B diagnostic input, reply or evidence file is unusable."""


# --------------------------------------------------------------------------- #
# Configuration identity
# --------------------------------------------------------------------------- #


def _require_study_location(path: Path) -> None:
    parts = path.resolve().parts
    if len(parts) < len(STUDY_TAIL) + 1 or parts[-len(STUDY_TAIL) - 1:-1] != STUDY_TAIL:
        raise DiagnosticError(
            "configuration must reside in benchmarks/studies/perf-02/warm/configurations"
        )


def _require_pinned_a_equal_a(config: Mapping[str, Any]) -> str:
    """Return the single pinned accepted revision the diagnostic may execute."""
    if config.get("family") != "perf-02":
        raise DiagnosticError("PERF-02-B requires the perf-02 benchmark family")
    if config.get("baseline") != "A":
        raise DiagnosticError("PERF-02-B requires baseline arm A")
    workload = config.get("workload")
    if not isinstance(workload, Mapping) or workload.get("regimes") != ["warm"]:
        raise DiagnosticError("PERF-02-B requires the single warm measurement regime")
    arms = config.get("arms")
    if not isinstance(arms, Mapping) or set(arms) != {"A", "B"}:
        raise DiagnosticError("PERF-02-B requires exactly the pinned A/B arms")
    for arm_id in ("A", "B"):
        arm = arms[arm_id]
        if not isinstance(arm, Mapping):
            raise DiagnosticError(f"arm {arm_id} is not an object")
        if arm.get("engine") != "quervant":
            raise DiagnosticError(f"arm {arm_id} must be the Quervant engine")
        if arm.get("mode") != "by-top-k":
            raise DiagnosticError(f"arm {arm_id} must use the production by-top-k dispatch")
        if arm.get("source") != "pinned":
            raise DiagnosticError(f"arm {arm_id} must be pinned to a committed revision")
        revision = arm.get("revision")
        if not isinstance(revision, str) or not PINNED_REVISION.fullmatch(revision):
            raise DiagnosticError(f"arm {arm_id} requires a full 40-hex pinned commit")
    if arms["A"]["revision"] != arms["B"]["revision"]:
        raise DiagnosticError("both arms must pin the same accepted revision (A=A)")
    return str(arms["A"]["revision"])


def _load(config_path: Path) -> tuple[dict[str, Any], str]:
    path = Path(config_path)
    try:
        if path.is_symlink():
            raise DiagnosticError("configuration must not be a symlink")
        config = load_configuration(path)
        validate_configuration(config)
    except DiagnosticError:
        raise
    except ArtifactError as error:
        raise DiagnosticError(str(error)) from error
    _require_study_location(path)
    revision = _require_pinned_a_equal_a(config)
    return config, revision


def _expected_lane_ids() -> frozenset[str]:
    return frozenset(
        f"{n}/{cls}/k{k}/warm"
        for n in BASELINE_SIZES
        for cls in ("absent", "rare", "medium", "common")
        for k in (10, 100)
    )


def _lanes(config: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    ordered = lanes_for(config)
    ids = [lane["id"] for lane in ordered]
    if len(ids) != 16 or len(set(ids)) != 16 or set(ids) != set(_expected_lane_ids()):
        raise DiagnosticError(
            "PERF-02-B requires exactly the 16 declared 10K/100K warm lanes"
        )
    if not PROFILE_LANE_IDS <= set(ids):
        raise DiagnosticError("configuration is missing one of the four primary profile lanes")
    return {lane["id"]: dict(lane) for lane in ordered}, ids


# --------------------------------------------------------------------------- #
# Deterministic request generation
# --------------------------------------------------------------------------- #


def _request(phase: str, lane: Mapping[str, Any], kind: str, index: int) -> dict[str, Any]:
    return {
        "request_id": f"{phase}:{lane['id']}:{kind}:{index}",
        "op": "query",
        "field": lane["field"],
        "term": lane["term"],
        "k": lane["k"],
        "mode": "warm",
    }


def _stream(phase: str, lane: Mapping[str, Any], warmups: int, samples: int) -> list[dict[str, Any]]:
    rows = [_request(phase, lane, "warmup", index) for index in range(warmups)]
    rows.extend(_request(phase, lane, "sample", index) for index in range(samples))
    return rows


def _encode(rows: Iterable[Mapping[str, Any]]) -> bytes:
    text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
        for row in rows
    )
    return text.encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_once(path: Path, payload: bytes) -> str:
    """Write a diagnostic file exactly once; identical bytes are a safe no-op."""
    if path.is_symlink():
        raise DiagnosticError(f"refusing symlink diagnostic destination: {path}")
    if path.exists():
        if not path.is_file():
            raise DiagnosticError(f"existing diagnostic path is not a regular file: {path}")
        if path.read_bytes() == payload:
            return "REUSED"
        raise DiagnosticError(f"existing diagnostic file differs; refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError as error:  # concurrent writer won the race
        raise DiagnosticError(f"diagnostic file appeared concurrently: {path}") from error
    except OSError as error:
        raise DiagnosticError(f"cannot write diagnostic file {path}: {error}") from error
    return "WRITTEN"


def request_streams(config: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The six fixed diagnostic request streams, in prescribed file order."""
    lanes, ordered = _lanes(config)
    files: dict[str, list[dict[str, Any]]] = {}
    for n in BASELINE_SIZES:
        rows: list[dict[str, Any]] = []
        for lane_id in ordered:
            lane = lanes[lane_id]
            if lane["n"] != n:
                continue
            rows.extend(_stream("baseline", lane, BASELINE_WARMUPS, BASELINE_SAMPLES))
        files[BASELINE_FILES[n]] = rows
    for slug, lane_id in PRIMARY_LANES:
        files[PROFILE_FILES[slug]] = _stream(
            "profile", lanes[lane_id], PROFILE_WARMUPS, PROFILE_SAMPLES
        )
    return files


def generate_inputs(config_path: Path, output_dir: Path) -> dict[str, Any]:
    """Create ``<output-dir>/requests/`` with the six JSONL streams and a manifest."""
    config, revision = _load(config_path)
    directory = Path(output_dir) / "requests"
    streams = request_streams(config)
    payloads = {name: _encode(rows) for name, rows in streams.items()}
    states = {name: _write_once(directory / name, payloads[name]) for name in streams}

    counts: dict[str, Any] = {}
    for name, rows in streams.items():
        phase = "baseline" if name.startswith("baseline-") else "profile"
        lanes = sorted({row["request_id"].split(":")[1] for row in rows})
        per_lane = len(rows) // len(lanes)
        counts[name] = {
            "rows": len(rows),
            "lanes": lanes,
            "rows_per_lane": per_lane,
            "warmups_per_lane": BASELINE_WARMUPS if phase == "baseline" else PROFILE_WARMUPS,
            "samples_per_lane": BASELINE_SAMPLES if phase == "baseline" else PROFILE_SAMPLES,
        }
        if per_lane * len(lanes) != len(rows):
            raise DiagnosticError(f"internal request-count inconsistency for {name}")

    manifest = {
        "schema": INPUTS_MANIFEST_SCHEMA,
        "diagnostic_only": True,
        "timed_campaign": False,
        "benchmark_result_v1": False,
        "source_revision": revision,
        "configuration_file": Path(config_path).name,
        "configuration_id": config["configuration_id"],
        "configuration_name": config["name"],
        "lane_ids": list(_lanes(config)[1]),
        "primary_lane_ids": [lane_id for _, lane_id in PRIMARY_LANES],
        "request_files": list(streams),
        "counts": counts,
        "sha256": {name: _sha256(payloads[name]) for name in streams},
    }
    manifest_path = directory / "inputs-manifest.json"
    states[manifest_path.name] = _write_once(
        manifest_path, (json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    return {
        "state": "REUSED" if set(states.values()) == {"REUSED"} else "WRITTEN",
        "directory": str(directory),
        "manifest": str(manifest_path),
        "files": states,
        "manifest_body": manifest,
    }


# --------------------------------------------------------------------------- #
# Reply validation and descriptive statistics
# --------------------------------------------------------------------------- #


def _pairs(items: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise DiagnosticError(f"diagnostic stream must be a regular non-symlink file: {path}")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise DiagnosticError(f"cannot read diagnostic stream {path}: {error}") from error
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DiagnosticError(f"diagnostic stream is not valid UTF-8: {path}: {error}") from error
    if "\r" in text:
        raise DiagnosticError(f"diagnostic stream contains CR characters: {path}")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not line:
            raise DiagnosticError(f"{path}: empty line {number}")
        try:
            value = json.loads(line, object_pairs_hook=_pairs)
        except ValueError as error:
            raise DiagnosticError(f"{path}: line {number} is not valid JSON: {error}") from error
        if not isinstance(value, dict):
            raise DiagnosticError(f"{path}: line {number} is not a JSON object")
        rows.append(value)
    return rows


def _parse_request_id(value: Any) -> tuple[str, str, str, int]:
    if not isinstance(value, str):
        raise DiagnosticError("request_id must be a string")
    match = REQUEST_ID.fullmatch(value)
    if match is None:
        raise DiagnosticError(
            f"request_id must be <phase>:<lane-id>:<kind>:<index>, found {value!r}"
        )
    return match["phase"], match["lane"], match["kind"], int(match["index"])


def _validate_request(row: Mapping[str, Any], lanes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    request_id = row.get("request_id")
    phase, lane_id, kind, index = _parse_request_id(request_id)
    lane = lanes.get(lane_id)
    if lane is None:
        raise DiagnosticError(f"unrecognised lane in request_id {request_id!r}")
    if row.get("op") != "query":
        raise DiagnosticError(f"request {request_id} must be a query, not an index/commit/reopen op")
    if row.get("mode") != "warm":
        raise DiagnosticError(f"request {request_id} must use mode=warm")
    for field in ("field", "term", "k"):
        if row.get(field) != lane[field]:
            raise DiagnosticError(
                f"request {request_id} {field}={row.get(field)!r} disagrees with "
                f"lane {lane_id} {field}={lane[field]!r}"
            )
    return {"request_id": request_id, "phase": phase, "lane_id": lane_id,
            "kind": kind, "index": index, "lane": lane}


def _expected_sequence(phase: str, lanes: Mapping[str, Mapping[str, Any]],
                       ordered: Sequence[str], present: Sequence[str]) -> tuple[list[str], list[str]]:
    """The only accepted request_id order for this stream; raises on a bad lane set."""
    if phase == "baseline":
        sizes = {lanes[lane_id]["n"] for lane_id in present}
        if len(sizes) != 1:
            raise DiagnosticError("a baseline stream must cover exactly one corpus size")
        size = sizes.pop()
        canonical = [lane_id for lane_id in ordered if lanes[lane_id]["n"] == size]
        if len(canonical) != 8 or set(present) != set(canonical) or len(present) != 8:
            raise DiagnosticError(
                f"baseline stream must cover all eight {size}-document lanes"
            )
        warmups, samples = BASELINE_WARMUPS, BASELINE_SAMPLES
    else:
        if len(present) != 1 or present[0] not in PROFILE_LANE_IDS:
            raise DiagnosticError(
                "a profile stream must select exactly one of the four primary profile lanes"
            )
        canonical = [present[0]]
        warmups, samples = PROFILE_WARMUPS, PROFILE_SAMPLES
    sequence: list[str] = []
    for lane_id in canonical:
        sequence.extend(f"{phase}:{lane_id}:warmup:{index}" for index in range(warmups))
        sequence.extend(f"{phase}:{lane_id}:sample:{index}" for index in range(samples))
    return sequence, canonical


def nearest_rank_p90(values: Sequence[int]) -> int:
    """Nearest-rank p90: ``sorted[N-1][ceil(0.90 * N) - 1]`` (never interpolated)."""
    if not values:
        raise DiagnosticError("cannot compute p90 of an empty sample set")
    ordered = sorted(values)
    rank = max(1, math.ceil(0.90 * len(ordered)))
    return ordered[rank - 1]


def _milliseconds(nanoseconds: float) -> float:
    return round(nanoseconds / 1_000_000, 6)


def _exact(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def validate_streams(config_path: Path, request_file: Path, response_file: Path) -> tuple[dict[str, Any], str]:
    """Validate one request/response pair; return the summary body and revision."""
    config, revision = _load(config_path)
    lanes, ordered = _lanes(config)
    requests = _read_jsonl(request_file)
    responses = _read_jsonl(response_file)

    parsed = [_validate_request(row, lanes) for row in requests]

    if len(responses) < len(parsed):
        raise DiagnosticError(
            f"response stream is incomplete: first missing request_id={parsed[len(responses)]['request_id']}"
        )
    if len(responses) > len(parsed):
        raise DiagnosticError(
            f"response stream has an extra reply after request_id={parsed[-1]['request_id']}"
        )

    phases = {entry["phase"] for entry in parsed}
    if len(phases) > 1:
        raise DiagnosticError("one diagnostic stream must not mix baseline and profile phases")
    phase = "profile" if "profile" in phases else "baseline"

    present: list[str] = []
    for entry in parsed:
        if entry["lane_id"] not in present:
            present.append(entry["lane_id"])
    sequence, canonical = _expected_sequence(phase, lanes, ordered, present)
    actual = [entry["request_id"] for entry in parsed]
    for expected, observed in zip(sequence, actual):
        if expected != observed:
            raise DiagnosticError(
                f"unexpected request order: expected {expected}, found {observed}"
            )
    if len(actual) != len(sequence):
        index = min(len(actual), len(sequence))
        offending = actual[index] if index < len(actual) else sequence[index]
        raise DiagnosticError(f"request stream is incomplete or excessive at {offending}")

    samples: dict[str, list[int]] = {lane_id: [] for lane_id in canonical}
    warmups: dict[str, int] = {lane_id: 0 for lane_id in canonical}
    totals: dict[str, int] = {}

    for entry, response in zip(parsed, responses):
        request_id = entry["request_id"]
        lane = entry["lane"]
        if response.get("request_id") != request_id:
            raise DiagnosticError(
                f"reply request_id mismatch: expected {request_id}, "
                f"found {response.get('request_id')!r}"
            )
        if response.get("schema") != ADAPTER_SCHEMA:
            raise DiagnosticError(f"reply {request_id} has an unexpected schema")
        if response.get("engine") != "quervant":
            raise DiagnosticError(f"reply {request_id} was not produced by the Quervant engine")
        if response.get("status") != "ok":
            raise DiagnosticError(f"reply {request_id} is not status=ok")
        total_hits = response.get("total_hits")
        if isinstance(total_hits, bool) or not isinstance(total_hits, int) or total_hits < 0:
            raise DiagnosticError(f"reply {request_id} has an invalid total_hits")
        expected = expected_answer(lane["n"], lane["field"], lane["term"], lane["k"])
        try:
            duration = validate_reply(response, lane, expected)
        except MeasurementBlocked as error:
            raise DiagnosticError(f"reply {request_id} failed the oracle: {error}") from error
        # validate_reply already proved this reply equals the independent oracle
        # for its lane, so the lane total is authoritative and uncontradictable.
        totals[entry["lane_id"]] = total_hits
        if entry["kind"] == "warmup":
            warmups[entry["lane_id"]] += 1
        else:
            samples[entry["lane_id"]].append(duration)

    request_sha = _sha256(Path(request_file).read_bytes())
    response_sha = _sha256(Path(response_file).read_bytes())
    records: list[dict[str, Any]] = []
    for lane_id in canonical:
        values = samples[lane_id]
        if not values:
            raise DiagnosticError(f"lane {lane_id} has no timed sample rows")
        median = statistics.median(values)
        p90 = nearest_rank_p90(values)
        records.append({
            "schema": VALIDATED_SCHEMA,
            "source_revision": revision,
            "configuration_id": config["configuration_id"],
            "configuration_file": Path(config_path).name,
            "mode": DIAGNOSTIC_MODE,
            "timed_campaign": False,
            "benchmark_result_v1": False,
            "lane_id": lane_id,
            "phase": phase,
            "warmups": warmups[lane_id],
            "samples": len(values),
            "total_hits": totals[lane_id],
            "median_engine_ms": _milliseconds(median),
            "p90_engine_ms": _milliseconds(p90),
            "median_engine_ns": _exact(median),
            "p90_engine_ns": p90,
            "oracle_status": "PASS",
            "checksums": {"request_sha256": request_sha, "response_sha256": response_sha},
        })

    body: Any = records if phase == "baseline" else records[0]
    return {"phase": phase, "body": body, "records": records}, revision


def verify_stream(config_path: Path, request_file: Path, response_file: Path,
                  output: Path) -> dict[str, Any]:
    validated, _revision = validate_streams(config_path, request_file, response_file)
    payload = (json.dumps(validated["body"], sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    state = _write_once(Path(output), payload)
    return {"state": state, "output": str(output), "phase": validated["phase"],
            "lanes": [record["lane_id"] for record in validated["records"]]}


# --------------------------------------------------------------------------- #
# perf-script CPU attribution
# --------------------------------------------------------------------------- #


def _split_perf_records(text: str) -> list[tuple[str, list[str]]]:
    """Split ``perf script`` output into (header, indented frames) records."""
    records: list[tuple[str, list[str]]] = []
    header: str | None = None
    frames: list[str] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            if header is not None:
                records.append((header, frames))
                header, frames = None, []
            continue
        if raw_line[0] in " \t":
            if header is None:
                raise DiagnosticError("perf script frame appears before any event header")
            frames.append(raw_line)
            continue
        if header is not None:
            records.append((header, frames))
        header, frames = raw_line, []
    if header is not None:
        records.append((header, frames))
    return records


def _is_cpu_clock(event: str) -> bool:
    return event == CPU_CLOCK_EVENT or event.startswith(f"{CPU_CLOCK_EVENT}:")


def _frame_symbols(header: str, frames: Sequence[str]) -> list[str]:
    header_match = PERF_HEADER.fullmatch(header)
    if header_match is None:
        raise DiagnosticError(f"unrecognised perf script event header: {header!r}")
    symbols: list[str] = []
    rest = header_match["rest"].strip()
    if rest:
        inline = PERF_FRAME.fullmatch(f"\t{rest}")
        if inline is not None and inline["sym"].strip() not in UNSYMBOLIZED:
            symbols.append(inline["sym"].strip())
    for frame in frames:
        match = PERF_FRAME.fullmatch(frame)
        if match is None:
            raise DiagnosticError(f"unrecognised perf script callchain frame: {frame.strip()!r}")
        symbol = match["sym"].strip()
        if symbol not in UNSYMBOLIZED:
            symbols.append(symbol)
    return symbols


def _matches(symbols: Sequence[str], markers: Sequence[str]) -> bool:
    return any(marker in symbol for symbol in symbols for marker in markers)


def classify_perf_script(text: str) -> dict[str, Any]:
    """Classify every ``cpu-clock`` sample once into nonoverlapping buckets."""
    total = query = sort = startup = unknown = other_process = 0
    root_visible = False
    events: set[str] = set()
    records = _split_perf_records(text)
    for header, frames in records:
        header_match = PERF_HEADER.fullmatch(header)
        if header_match is None:
            raise DiagnosticError(f"unrecognised perf script event header: {header!r}")
        event = header_match["event"]
        if not _is_cpu_clock(event):
            continue
        events.add(event)
        symbols = _frame_symbols(header, frames)
        total += 1
        if not header_match["comm"].startswith(PROCESS_PREFIX):
            other_process += 1
            unknown += 1
            continue
        if _matches(symbols, QUERY_MARKERS):
            query += 1
            if _matches(symbols, ROOT_MARKERS):
                root_visible = True
            if _matches(symbols, SORT_MARKERS):
                sort += 1
        elif _matches(symbols, STARTUP_MARKERS):
            startup += 1
        else:
            unknown += 1

    covered = query + startup
    fraction = covered / total if total else 0.0
    share = round(100 * sort / query, SAMPLE_DECIMALS) if query else None
    reasons: list[str] = []
    if total == 0:
        reasons.append("no cpu-clock samples")
    if query < MIN_QUERY_SAMPLES:
        reasons.append(f"recognised query samples {query} < {MIN_QUERY_SAMPLES}")
    if total and fraction < MIN_ATTRIBUTABLE_FRACTION:
        reasons.append(f"attributable sample fraction {fraction:.3f} < {MIN_ATTRIBUTABLE_FRACTION}")
    if total and unknown * 2 >= total:
        reasons.append("UNKNOWN is a dominant sample bucket")
    if total and unknown >= query:
        reasons.append("UNKNOWN samples are not fewer than recognised query samples")
    if total and not root_visible:
        reasons.append("no root sort/search call chain is symbolised")
    return {
        "total_cpu_samples": total,
        "query_cpu_samples": query,
        "sort_cpu_samples": sort,
        "other_query_samples": query - sort,
        "startup_overhead_samples": startup,
        "unknown_samples": unknown,
        "other_process_samples": other_process,
        "attributable_sample_fraction": round(fraction, 4),
        "root_chain_visible": root_visible,
        "sort_query_cpu_share_percent": share,
        "cpu_events": sorted(events),
        "evidence_status": "PASS" if not reasons else "INSUFFICIENT_VISIBILITY",
        "evidence_reasons": reasons,
    }


# --------------------------------------------------------------------------- #
# Read-only summary assembly
# --------------------------------------------------------------------------- #


def _read_json_object(path: Path, label: str) -> Any:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise DiagnosticError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeError, ValueError) as error:
        raise DiagnosticError(f"cannot decode {label} {path}: {error}") from error
    return value


def _require_identity(record: Mapping[str, Any], config: Mapping[str, Any], revision: str,
                      label: str) -> None:
    if record.get("source_revision") != revision:
        raise DiagnosticError(f"{label} source revision differs from the configuration")
    if record.get("configuration_id") != config["configuration_id"]:
        raise DiagnosticError(f"{label} configuration identity differs")
    if record.get("mode") != DIAGNOSTIC_MODE:
        raise DiagnosticError(f"{label} is not a diagnostic-unqualified record")
    if record.get("benchmark_result_v1") is not False:
        raise DiagnosticError(f"{label} must not be benchmark-result-v1 evidence")
    if record.get("timed_campaign") is not False:
        raise DiagnosticError(f"{label} must not claim a timed campaign")


def summarize(config_path: Path, output_dir: Path) -> dict[str, Any]:
    """Combine validated summaries and perf captures into one deterministic summary."""
    config, revision = _load(config_path)
    directory = Path(output_dir)
    validated_dir = directory / "validated"

    baseline: list[dict[str, Any]] = []
    for n in BASELINE_SIZES:
        name = BASELINE_FILES[n]
        label = f"validated/{name.replace('.jsonl', '.json')}"
        data = _read_json_object(validated_dir / f"{name[:-6]}.json", label)
        if not isinstance(data, list) or len(data) != 8:
            raise DiagnosticError(f"{label} must contain exactly eight baseline lane records")
        for record in data:
            if not isinstance(record, Mapping):
                raise DiagnosticError(f"{label} contains a non-object lane record")
            _require_identity(record, config, revision, label)
            if record.get("lane_id") not in _expected_lane_ids():
                raise DiagnosticError(f"{label} declares an unknown lane")
            baseline.append(dict(record))
    if len({record["lane_id"] for record in baseline}) != 16:
        raise DiagnosticError("baseline summaries must cover 16 distinct lanes")

    profiles: list[dict[str, Any]] = []
    for slug, lane_id in PRIMARY_LANES:
        validated_name = f"profile-n100000-{slug}.json"
        label = f"validated/{validated_name}"
        record = _read_json_object(validated_dir / validated_name, label)
        if not isinstance(record, Mapping):
            raise DiagnosticError(f"{label} must be a single lane record")
        _require_identity(record, config, revision, label)
        if record.get("lane_id") != lane_id:
            raise DiagnosticError(f"{label} declares lane {record.get('lane_id')!r}, expected {lane_id}")
        if record.get("samples") != PROFILE_SAMPLES or record.get("warmups") != PROFILE_WARMUPS:
            raise DiagnosticError(f"{label} does not contain the prescribed 100+800 rows")
        script_path = directory / f"{slug}.perf-script.txt"
        report_path = directory / f"{slug}.perf-report.txt"
        for path, kind in ((script_path, "perf script"), (report_path, "perf report")):
            if path.is_symlink() or not path.is_file():
                raise DiagnosticError(f"missing {kind} capture: {path}")
        try:
            script_text = script_path.read_text(encoding="utf-8", errors="strict")
            report_bytes = report_path.read_bytes()
        except (OSError, UnicodeError) as error:
            raise DiagnosticError(f"cannot read captured perf output: {error}") from error
        if not report_bytes.strip():
            raise DiagnosticError(f"perf report capture is empty: {report_path}")
        classification = classify_perf_script(script_text)
        profiles.append({
            "profile_slug": slug,
            "lane_id": lane_id,
            "profiled_queries": record["samples"],
            "warmups": record["warmups"],
            "total_hits": record["total_hits"],
            "median_engine_ms": record["median_engine_ms"],
            "p90_engine_ms": record["p90_engine_ms"],
            "oracle_status": record["oracle_status"],
            **classification,
            "perf_script_sha256": _sha256(script_text.encode("utf-8")),
            "perf_report_sha256": _sha256(report_bytes),
            "validated_record_sha256": _sha256(
                (json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
            ),
        })

    blocked = [profile["profile_slug"] for profile in profiles if profile["evidence_status"] != "PASS"]
    summary = {
        "schema": SUMMARY_SCHEMA,
        "mode": DIAGNOSTIC_MODE,
        "timed_campaign": False,
        "benchmark_result_v1": False,
        "source_revision": revision,
        "configuration_id": config["configuration_id"],
        "configuration_file": Path(config_path).name,
        "cpu_attribution_status": "CPU_ATTRIBUTION_BLOCKED" if blocked else "PASS",
        "cpu_attribution_blocked_profiles": blocked,
        "sample_decimals": SAMPLE_DECIMALS,
        "attribution_rule": "nonoverlapping cpu-clock call-stack samples",
        "baseline": baseline,
        "profiles": profiles,
        "limitations": [
            "sampled CPU share is not wall-clock latency and not a predicted speedup",
            "perf record is launch-scoped and includes bounded process startup",
            "per-candidate borrow/fallback/materialisation counts are NOT_MEASURED in release",
            "no treatment gain, no A/B result and no benchmark-result-v1 evidence",
        ],
    }
    payload = (json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path = directory / "summary.json"
    state = _write_once(path, payload)
    return {"state": state, "output": str(path),
            "cpu_attribution_status": summary["cpu_attribution_status"],
            "blocked_profiles": blocked}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m quervant_bench.lean.perf02b_diagnostics",
        description="PERF-02-B bounded warm sort-path diagnostics (never a benchmark run)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    inputs = commands.add_parser("inputs", help="generate the six fixed diagnostic request streams")
    inputs.add_argument("--config", required=True, type=Path)
    inputs.add_argument("--output-dir", required=True, type=Path)

    verify = commands.add_parser("verify", help="validate one request/response pair and summarize it")
    verify.add_argument("--config", required=True, type=Path)
    verify.add_argument("--request-file", required=True, type=Path)
    verify.add_argument("--response-file", required=True, type=Path)
    verify.add_argument("--output", required=True, type=Path)

    summarize_cmd = commands.add_parser("summarize", help="assemble the deterministic diagnostic summary")
    summarize_cmd.add_argument("--config", required=True, type=Path)
    summarize_cmd.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "inputs":
            result = generate_inputs(arguments.config, arguments.output_dir)
        elif arguments.command == "verify":
            result = verify_stream(arguments.config, arguments.request_file,
                                   arguments.response_file, arguments.output)
        else:
            result = summarize(arguments.config, arguments.output_dir)
    except ArtifactError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
