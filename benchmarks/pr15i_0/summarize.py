#!/usr/bin/env python3
"""PR 15I-0 stable report calculator.

It is a *calculator*, not an optimizer: it only turns already-qualified,
already-sealed manifests into sorted-key JSON and Markdown. It never re-derives a
measurement from historical tables, never mixes historical and current samples
and never turns an inclusive CPU share into a millisecond estimate.

```sh
python3 benchmarks/pr15i_0/summarize.py \
  --verification target/pr15i-0/verification-02.json \
  --pr15d-run "$D_RUN" --pr15f-run "$F_RUN" \
  --pr15f-prepared "$PREP" --mutation-run "$M_RUN" \
  --out-json benchmarks/reports/pr15i-0/pr15i-0-summary.json \
  --out-md docs/pr-artifacts/pr-15i-0/measurements.md
```
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:  # make the sibling verifier importable
    sys.path.insert(0, _THIS_DIR)

import verify as verifier  # noqa: E402  (sibling module in this directory)

SCHEMA_SUMMARY = "pr15i-0-summary-v1"
SCHEMA_PRIVACY = "pr15i-0-privacy-scan-v1"
ENGINES = ("quervant", "tantivy", "lucene")
N_VALUES = (10000, 100000)
SECTION_ORDER = (
    "Schema",
    "Dictionary",
    "Postings",
    "DocKeys",
    "VersionRefs",
    "LiveDocs",
    "Stored",
    "Columns",
    "TimeBounds",
    "GeoBounds",
    "SortedRemap",
    "SegmentMeta",
    "FieldNorms",
    "JsonPaths",
    "SpatialPoints",
)
MUTATION_COMPONENTS = (
    "state_header_bytes",
    "row_key_prefix_bytes",
    "row_key_bytes",
    "row_revision_bytes",
    "row_status_bytes",
    "live_pointer_prefix_bytes",
    "live_pointer_id_bytes",
    "live_doc_id_bytes",
    "replay_header_bytes",
    "replay_token_prefix_bytes",
    "replay_token_bytes",
    "replay_fingerprint_bytes",
    "replay_key_prefix_bytes",
    "replay_key_bytes",
    "replay_intent_bytes",
    "replay_revision_bytes",
    "batch_replay_opaque_bytes",
)
HISTORICAL = {
    "label": "2026 PR15F HISTORICAL",
    "source": "docs/pr-artifacts/pr-15f/p0-analysis.md",
    "revision": "historical PR15F campaign (superseded as today's baseline)",
    "index_bytes_100000": 30965025,
    "mutation_sidecar_bytes_100000": 9600180,
    "stored_bytes_100000": 9662513,
    "dictionary_bytes_100000": 3500207,
    "postings_bytes_100000": 3983573,
}
REJECTED_CANDIDATE = {
    "label": "2026 PR15H-E EXPERIMENTAL REJECTION",
    "candidate_commit": "72b18e249f2a83b77fd2faaf05deb6f0d60eaad6",
    "rollback_commit": "8d722ad0c0cff6b947fcdc762bb2ccaacdfcff0b",
    "status": "E_SIZE_REJECTED_SAFE_ROLLBACK",
    "dictionary_bytes_100000": 1618170,
    "dictionary_bytes_baseline_100000": 3500207,
}
PRIVACY_PATTERNS = (
    (re.compile(r"/home/[A-Za-z0-9._-]+"), "unix home path"),
    (re.compile(r"/mnt/[a-z]/"), "windows mount path"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws access key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
)
REPORT_SCAN_TARGETS = (
    "docs/pr-artifacts/pr-15i-0/measurements.md",
    "docs/pr-artifacts/pr-15i-0/storage-attribution.md",
    "docs/pr-artifacts/pr-15i-0/performance-attribution.md",
    "docs/pr-artifacts/pr-15i-0/compatibility-matrix.md",
    "docs/pr-artifacts/pr-15i-0/architecture-15i-a.md",
    "docs/pr-artifacts/pr-15i-0/architecture-15i-b.md",
    "docs/pr-artifacts/pr-15i-0/architecture-15i-c.md",
    "docs/pr-artifacts/pr-15i-0/decision-register.md",
    "docs/pr-artifacts/pr-15i-0/final-report.md",
    "benchmarks/reports/pr15i-0/pr15i-0-summary.json",
    "benchmarks/reports/pr15i-0/pr15i-0-summary.md",
    "benchmarks/reports/pr15i-0/historical-context.json",
)


class SummaryError(Exception):
    pass


# The measured source this fixup publishes for. Publication refuses any other
# source so a report can never be derived from an unqualified revision.
FROZEN_MEASURED_SOURCE_SHA = "48e7d3a0771f9ccd1cc0bf1d07eadac4b2b5f39f"

OUTPUT_REL_PATHS = {
    "out_json": "benchmarks/reports/pr15i-0/pr15i-0-summary.json",
    "out_md": "docs/pr-artifacts/pr-15i-0/measurements.md",
}
IMPLICIT_OUTPUT_REL_PATHS = (
    "benchmarks/reports/pr15i-0/pr15i-0-summary.md",
    "benchmarks/reports/pr15i-0/historical-context.json",
    "benchmarks/reports/pr15i-0/privacy-scan.json",
)
INPUT_LABELS = (
    ("pr15d_run", "--pr15d-run", "pr15d-run"),
    ("pr15f_prepared", "--pr15f-prepared", "pr15f-prepared"),
    ("pr15f_run", "--pr15f-run", "pr15f-run"),
    ("mutation_run", "--mutation-run", "mutation-run"),
)


def canonical_json_bytes(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        + b"\n"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_bytes(path: str, data: bytes) -> str:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return sha256_bytes(data)


def median_int(values) -> int:
    ordered = sorted(values)
    if not ordered:
        raise SummaryError("cannot take a median of an empty sample")
    return ordered[len(ordered) // 2]


def ratio(numerator, denominator):
    if not isinstance(numerator, (int, float)) or not isinstance(denominator, (int, float)):
        return None
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def rounded(value, digits: int = 3):
    if value is None:
        return None
    return float(f"{value:.{digits}f}")


def not_comparable(reason: str) -> dict:
    return {"status": "NOT_COMPARABLE", "reason": reason}


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect_index_bytes(pr15d_run: str) -> dict:
    """Median index bytes per (document count, engine) over the three trials."""
    samples: dict[tuple[int, str], list[int]] = {}
    for trial in (1, 2, 3):
        for engine in ENGINES:
            path = os.path.join(pr15d_run, "trials", f"trial-{trial}", f"{engine}.json")
            manifest = read_json(path)
            for n in N_VALUES:
                entry = (manifest.get("build") or {}).get(str(n)) or {}
                samples.setdefault((n, engine), []).append(int(entry["index_bytes"]))
    result = {}
    for (n, engine), values in samples.items():
        result.setdefault(str(n), {})[engine] = median_int(values)
    return result


def collect_build_medians(pr15d_run: str) -> dict:
    """Median ingest/commit/reopen nanoseconds and segment counts per engine."""
    keys = ("index_ns", "commit_ns", "reopen_ns", "segment_count")
    samples: dict[tuple[int, str, str], list[int]] = {}
    for trial in (1, 2, 3):
        for engine in ENGINES:
            manifest = read_json(
                os.path.join(pr15d_run, "trials", f"trial-{trial}", f"{engine}.json")
            )
            for n in N_VALUES:
                entry = (manifest.get("build") or {}).get(str(n)) or {}
                for key in keys:
                    if isinstance(entry.get(key), (int, float)) and not isinstance(
                        entry.get(key), bool
                    ):
                        samples.setdefault((n, engine, key), []).append(int(entry[key]))
    result = {}
    for (n, engine, key), values in samples.items():
        result.setdefault(str(n), {}).setdefault(engine, {})[key] = median_int(values)
    return result


def collect_latency(pr15d_run: str) -> dict:
    """Median warm and process-cold lane medians per engine, per lane."""
    samples: dict[tuple[str, int, str, int, str], list[int]] = {}
    for trial in (1, 2, 3):
        for engine in ENGINES:
            manifest = read_json(
                os.path.join(pr15d_run, "trials", f"trial-{trial}", f"{engine}.json")
            )
            for lane in manifest.get("lanes") or []:
                key = (
                    lane["regime"],
                    int(lane["n"]),
                    lane["class"],
                    int(lane["k"]),
                    engine,
                )
                samples.setdefault(key, []).append(int(lane["summary_ns"]["median"]))
    lanes = {}
    for (regime, n, class_name, k, engine), values in samples.items():
        lane_id = f"{regime}/{n}/{class_name}/k{k}"
        entry = lanes.setdefault(
            lane_id,
            {
                "regime": regime,
                "n": n,
                "class": class_name,
                "k": k,
                "engines": {},
            },
        )
        entry["engines"][engine] = {
            "median_ns": median_int(values),
            "trial_medians_ns": sorted(values),
        }
    return lanes


def collect_sections(inventory: dict) -> dict:
    total = inventory["total_file_bytes"]
    sections = {}
    for kind, value in sorted((inventory.get("section_bytes") or {}).items()):
        sections[kind] = {
            "bytes": value,
            "share_of_index_percent": rounded(100.0 * value / total, 4),
        }
    return {
        "total_file_bytes": total,
        "segment_file_bytes": inventory.get("segment_file_bytes"),
        "segment_section_bytes": inventory.get("segment_section_bytes_total"),
        "segment_nonsection_bytes": inventory.get("segment_nonsection_bytes_total"),
        "manifest_file_bytes": inventory.get("manifest_file_bytes"),
        "metadata_file_bytes": inventory.get("metadata_file_bytes"),
        "mutation_state_file_bytes": inventory.get("mutation_state_file_bytes"),
        "file_count": inventory.get("file_count"),
        "content_sha256": inventory.get("content_sha256"),
        "sections": sections,
    }


def collect_mutation(mutation_run: str) -> dict:
    result = {}
    for n in N_VALUES:
        path = os.path.join(mutation_run, f"n{n}.json")
        breakdown = read_json(path)
        components = breakdown.get("component_bytes") or {}
        sidecar = breakdown["sidecar_file_bytes"]
        result[str(n)] = {
            "payload_version": breakdown["payload_version"],
            "row_count": breakdown["row_count"],
            "live_count": breakdown["live_count"],
            "deleted_count": breakdown["deleted_count"],
            "replay_count": breakdown["replay_count"],
            "sidecar_file_bytes": sidecar,
            "payload_bytes": breakdown["payload_bytes"],
            "container_overhead_bytes": breakdown["container_overhead_bytes"],
            "batch_replay_detail": breakdown["batch_replay_detail"],
            "component_bytes": {
                name: components.get(name, 0) for name in MUTATION_COMPONENTS
            },
            "component_share_percent": {
                name: rounded(100.0 * components.get(name, 0) / sidecar, 4)
                for name in MUTATION_COMPONENTS
            },
            "saved_bytes_upper_bound": {
                name: components.get(name, 0) for name in MUTATION_COMPONENTS
            },
            "saved_bytes_upper_bound_label": "PHYSICAL_ZERO_BYTE_CEILING_ONLY",
            "bytes_per_document": rounded(sidecar / int(n), 4),
            "breakdown_sha256": sha256_file(path),
        }
    return result


def collect_quervant_profile(pr15f_run: str) -> dict:
    reopen_path = os.path.join(pr15f_run, "reopen", "single", "summary.json")
    analysis_path = os.path.join(pr15f_run, "analysis.json")
    reopen = read_json(reopen_path)
    analysis = read_json(analysis_path)
    reopen_medians = {}
    for n in ("10000", "100000"):
        totals = [
            sample["reopen_total_ns"]
            for sample in (reopen.get("n") or {}).get(n, {}).get("samples_ns") or []
        ]
        cores = [
            sample["reopen_core_ns"]
            for sample in (reopen.get("n") or {}).get(n, {}).get("samples_ns") or []
        ]
        reopen_medians[n] = {
            "sample_count": len(totals),
            "reopen_total_ns_median": median_int(totals) if totals else None,
            "reopen_core_ns_median": median_int(cores) if cores else None,
        }
    lanes = {}
    for lane_id, frame in sorted((analysis.get("query") or {}).items()):
        lanes[lane_id] = {
            "sample_count": frame.get("sample_count"),
            "lost_samples": frame.get("lost_samples"),
            "contention_before": frame.get("contention_before"),
            "contention_after": frame.get("contention_after"),
            "exclusive_percent": frame.get("exclusive_percent"),
            "allocated_exclusive_percent": frame.get("allocated_exclusive_percent"),
            "inclusive_percent": frame.get("inclusive_percent"),
            "unknown_exclusive_percent": frame.get("unknown_exclusive_percent"),
            "unparsed_remainder_percent": frame.get("unparsed_remainder_percent"),
            "groups": frame.get("groups"),
            "rank": frame.get("rank"),
        }
    reopen_frames = {}
    for n, frame in sorted((analysis.get("reopen") or {}).items()):
        if not isinstance(frame, dict):
            continue
        reopen_frames[n] = {
            "exclusive_percent": frame.get("exclusive_percent"),
            "inclusive_percent": frame.get("inclusive_percent"),
            "groups": frame.get("groups"),
            "sample_count": frame.get("sample_count"),
        }
    allocation_path = os.path.join(pr15f_run, "allocation", "summary.json")
    allocation = read_json(allocation_path) if os.path.isfile(allocation_path) else None
    allocation_lanes = (allocation or {}).get("captures")
    if allocation_lanes is None:
        allocation_lanes = (allocation or {}).get("lanes") or []
    if isinstance(allocation_lanes, dict):
        allocation_lanes = list(allocation_lanes.values())
    allocation_lanes = [lane for lane in allocation_lanes if isinstance(lane, dict)]
    return {
        "reopen_single": reopen_medians,
        "reopen_fresh_processes_total": reopen.get("fresh_processes_total"),
        "lanes": lanes,
        "reopen_frames": reopen_frames,
        "allocation": {
            "status": (allocation or {}).get("status", "ALLOCATION_NOT_MEASURED"),
            "captured": [
                lane.get("capture_id") or lane.get("lane_id")
                for lane in allocation_lanes
                if lane.get("status") == "CAPTURED"
            ],
            "heaptrack_version": next(
                (
                    lane.get("heaptrack_version")
                    for lane in allocation_lanes
                    if lane.get("heaptrack_version")
                ),
                None,
            ),
        },
    }


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def derive(verification: dict, pr15d_run: str, pr15f_run: str, mutation_run: str) -> dict:
    gates = verification.get("gates") or {}
    gate_status = {gate: entry.get("status") for gate, entry in gates.items()}
    qualified = verification.get("qualified") is True

    index_bytes = collect_index_bytes(pr15d_run)
    build = collect_build_medians(pr15d_run)
    latency = collect_latency(pr15d_run)

    index_ratios = {}
    for n in N_VALUES:
        entry = {"bytes": dict(index_bytes[str(n)])}
        if gate_status.get("I0-P03") == "PASS":
            quervant = index_bytes[str(n)]["quervant"]
            entry["ratio_quervant_over"] = {
                engine: rounded(ratio(quervant, index_bytes[str(n)][engine]))
                for engine in ENGINES
                if engine != "quervant"
            }
            entry["caveat"] = "PHYSICAL_SEGMENT_SCHEMA_DIFFERS"
        else:
            entry["ratio_quervant_over"] = not_comparable("three-engine gate is not PASS")
        index_ratios[str(n)] = entry

    query_ratios = {}
    for lane_id, lane in sorted(latency.items()):
        engines = lane["engines"]
        entry = {
            "regime": lane["regime"],
            "n": lane["n"],
            "class": lane["class"],
            "k": lane["k"],
            "median_ns": {engine: value["median_ns"] for engine, value in engines.items()},
        }
        comparability_reason = None
        if gate_status.get("I0-P03") != "PASS":
            comparability_reason = "three-engine gate is not PASS"
        elif "quervant" not in engines or "tantivy" not in engines:
            comparability_reason = "lane is missing an engine"
        elif lane["regime"] != "warm":
            comparability_reason = (
                "process_cold means a fresh process, not an OS-cache-cold measurement"
            )
        if comparability_reason:
            entry["ratio_quervant_over_tantivy"] = not_comparable(comparability_reason)
        else:
            entry["ratio_quervant_over_tantivy"] = rounded(
                ratio(engines["quervant"]["median_ns"], engines["tantivy"]["median_ns"])
            )
        entry["physical_sort_caveat"] = "PHYSICAL_SORT_ENCODING_DIFFERS"
        query_ratios[f"{lane_id}"] = entry

    reopen_ratios = {}
    for n in N_VALUES:
        quervant = build[str(n)]["quervant"]["reopen_ns"]
        entry = {
            "reopen_ns": {
                engine: build[str(n)][engine]["reopen_ns"] for engine in ENGINES
            }
        }
        if gate_status.get("I0-P03") == "PASS":
            entry["ratio_quervant_over_tantivy"] = rounded(
                ratio(quervant, build[str(n)]["tantivy"]["reopen_ns"])
            )
        else:
            entry["ratio_quervant_over_tantivy"] = not_comparable(
                "three-engine gate is not PASS"
            )
        reopen_ratios[str(n)] = entry

    return {
        "qualified": qualified,
        "gate_status": gate_status,
        "index_bytes": index_ratios,
        "build_medians_ns": build,
        "latency": query_ratios,
        "reopen": reopen_ratios,
        "quervant_profile": collect_quervant_profile(pr15f_run),
        "mutation": collect_mutation(mutation_run),
    }


def attach_sections(summary: dict, pr15f_run: str) -> None:
    sections = {}
    for n in N_VALUES:
        inventory = read_json(os.path.join(pr15f_run, "inventory", f"n{n}.json"))
        sections[str(n)] = collect_sections(inventory)
    summary["sections"] = sections


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def fmt_int(value) -> str:
    if value is None:
        return "NOT_MEASURED"
    return f"{int(value):,}"


def fmt_ratio(value) -> str:
    if not isinstance(value, (int, float)):
        if isinstance(value, dict):
            return value.get("status", "NOT_COMPARABLE")
        return "NOT_COMPARABLE"
    return f"{value:.3f}"


def fmt_percent(value) -> str:
    if not isinstance(value, (int, float)):
        return "NOT_MEASURED"
    return f"{value:.4f}"


def render_markdown(summary: dict, verification: dict) -> str:
    lines = []
    add = lines.append
    add("# PR 15I-0 — measured baseline")
    add("")
    add(f"**Status: `{verification.get('overall_status')}`**")
    add("")
    add("Generated by `benchmarks/pr15i_0/summarize.py` from already-qualified/sealed")
    add("manifests only. No number here is copied from a historical report, and no")
    add("inclusive CPU share is converted into a latency estimate.")
    add("")
    add("## Source and gate identity")
    add("")
    add("| Item | Value |")
    add("|---|---|")
    add(f"| Measured source | `{verification.get('source_sha')}` |")
    protocol = verification.get("protocol") or {}
    add(f"| Measurement contract SHA-256 | `{protocol.get('sha256')}` |")
    add(f"| Controller version | `{verification.get('controller_version')}` |")
    add("")
    add("| Gate | Status |")
    add("|---|---|")
    for gate, status in sorted((verification.get("gates") or {}).items()):
        add(f"| `{gate}` | `{status.get('status')}` |")
    add("")

    add("## Index bytes (PR 15D, median of three qualified trials)")
    add("")
    add("| Documents | Quervant | Tantivy | Lucene | Quervant/Tantivy | Quervant/Lucene |")
    add("|---:|---:|---:|---:|---:|---:|")
    for n in N_VALUES:
        entry = summary["index_bytes"][str(n)]
        bytes_map = entry["bytes"]
        ratios = entry["ratio_quervant_over"]
        add(
            "| {} | {} | {} | {} | {} | {} |".format(
                fmt_int(n),
                fmt_int(bytes_map.get("quervant")),
                fmt_int(bytes_map.get("tantivy")),
                fmt_int(bytes_map.get("lucene")),
                fmt_ratio((ratios or {}).get("tantivy")),
                fmt_ratio((ratios or {}).get("lucene")),
            )
        )
    add("")
    add("Segment/schema layouts differ physically between engines; the ratios compare")
    add("whole committed index bytes, not equivalent physical structures.")
    add("")

    add("## Ingest, commit and reopen (PR 15D medians, nanoseconds)")
    add("")
    add("| Documents | Engine | Ingest | Commit | Reopen | Segments |")
    add("|---:|---|---:|---:|---:|---:|")
    for n in N_VALUES:
        for engine in ENGINES:
            entry = summary["build_medians_ns"][str(n)][engine]
            add(
                "| {} | {} | {} | {} | {} | {} |".format(
                    fmt_int(n),
                    engine,
                    fmt_int(entry.get("index_ns")),
                    fmt_int(entry.get("commit_ns")),
                    fmt_int(entry.get("reopen_ns")),
                    fmt_int(entry.get("segment_count")),
                )
            )
    add("")
    add("Reopen ratios (Quervant/Tantivy):")
    add("")
    add("| Documents | Ratio |")
    add("|---:|---:|")
    for n in N_VALUES:
        add(f"| {fmt_int(n)} | {fmt_ratio(summary['reopen'][str(n)]['ratio_quervant_over_tantivy'])} |")
    add("")

    add("## Warm and process-cold query medians (PR 15D)")
    add("")
    add("`process_cold` means a fresh adapter process per sample — never OS-cache-cold.")
    add("All values are exact-match + exact-count + explicit ascending `doc_id` sort.")
    add("No BM25 score comparability is claimed anywhere.")
    add("")
    add("| Regime | N | Class | K | Quervant ns | Tantivy ns | Lucene ns | Q/T |")
    add("|---|---:|---|---:|---:|---:|---:|---:|")
    for lane_id in sorted(summary["latency"]):
        entry = summary["latency"][lane_id]
        med = entry["median_ns"]
        add(
            "| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                entry["regime"],
                fmt_int(entry["n"]),
                entry["class"],
                entry["k"],
                fmt_int(med.get("quervant")),
                fmt_int(med.get("tantivy")),
                fmt_int(med.get("lucene")),
                fmt_ratio(entry["ratio_quervant_over_tantivy"]),
            )
        )
    add("")
    add("The Quervant column uses a `Keyword` sort column, Tantivy a numeric ordinal")
    add("and Lucene `SortedDocValues`: the ordering is logically equivalent, the")
    add("physical representation is not, so no low-level operator parity is claimed.")
    add("")

    add("## Physical index composition (PR 15F read-only inventory)")
    add("")
    add("| Documents | Total | Segments | Segment sections | Segment overhead | Manifest | Metadata | Mutation sidecar |")
    add("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for n in N_VALUES:
        entry = summary["sections"][str(n)]
        add(
            "| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                fmt_int(n),
                fmt_int(entry["total_file_bytes"]),
                fmt_int(entry["segment_file_bytes"]),
                fmt_int(entry["segment_section_bytes"]),
                fmt_int(entry["segment_nonsection_bytes"]),
                fmt_int(entry["manifest_file_bytes"]),
                fmt_int(entry["metadata_file_bytes"]),
                fmt_int(entry["mutation_state_file_bytes"]),
            )
        )
    add("")
    kinds = sorted(
        {kind for n in N_VALUES for kind in summary["sections"][str(n)]["sections"]}
    )
    add("### Segment sections (bytes and share of the whole committed index)")
    add("")
    header = "| Section |" + "".join(f" {fmt_int(n)} B | share |" for n in N_VALUES)
    add(header)
    add("|---|" + "---:|---:|" * len(N_VALUES))
    for kind in kinds:
        cells = []
        for n in N_VALUES:
            entry = summary["sections"][str(n)]["sections"].get(kind)
            if entry is None:
                cells.append(" 0 | 0.0000% |")
            else:
                cells.append(
                    f" {fmt_int(entry['bytes'])} | {entry['share_of_index_percent']:.4f}% |"
                )
        add(f"| {kind} |" + "".join(cells))
    add("")

    add("## Mutation-state sidecar byte attribution (PR 15I-0 probe)")
    add("")
    add("Every payload byte is reconstructed from the *original* verified bytes and")
    add("reconciled exactly. The version-2 batch replay remainder is intentionally")
    add("opaque: `SEMANTIC_BATCH_DETAIL_NOT_VERIFIED`.")
    add("")
    add("| Documents | Payload version | Rows (live/deleted) | Replay rows | Payload B | Overhead B | File B | B/doc |")
    add("|---:|---:|---|---:|---:|---:|---:|---:|")
    for n in N_VALUES:
        entry = summary["mutation"][str(n)]
        add(
            "| {} | {} | {} / {} | {} | {} | {} | {} | {:.4f} |".format(
                fmt_int(n),
                entry["payload_version"],
                fmt_int(entry["live_count"]),
                fmt_int(entry["deleted_count"]),
                fmt_int(entry["replay_count"]),
                fmt_int(entry["payload_bytes"]),
                fmt_int(entry["container_overhead_bytes"]),
                fmt_int(entry["sidecar_file_bytes"]),
                entry["bytes_per_document"],
            )
        )
    add("")
    add("| Component | 10K B | 10K % of sidecar | 100K B | 100K % of sidecar |")
    add("|---|---:|---:|---:|---:|")
    for name in MUTATION_COMPONENTS:
        cells = [f"`{name}`"]
        for n in N_VALUES:
            entry = summary["mutation"][str(n)]
            cells.append(fmt_int(entry["component_bytes"][name]))
            cells.append(f"{fmt_percent(entry['component_share_percent'][name])}%")
        add("| " + " | ".join(cells) + " |")
    add("")
    add("`saved_bytes_upper_bound` in the JSON is a **physical zero-byte ceiling only**.")
    add("It is not an achievable saving and must not be used as a benefit forecast.")
    add("")

    add("## Quervant CPU attribution (PR 15F, nine warm lanes)")
    add("")
    add("Exclusive shares partition up to 100%; inclusive shares overlap and are never")
    add("summed. The `G08`/unknown bucket is reported as measured, never redistributed.")
    add("")
    add("| Lane | Samples | Lost | Unknown % | Exclusive sum % | Rank |")
    add("|---|---:|---:|---:|---:|---|")
    for lane_id in sorted(summary["quervant_profile"]["lanes"]):
        frame = summary["quervant_profile"]["lanes"][lane_id]
        rank = (frame.get("rank") or {}).get("classification", "UNRESOLVED")
        add(
            "| {} | {} | {} | {} | {:.4f} | {} |".format(
                lane_id,
                fmt_int(frame.get("sample_count")),
                fmt_int(frame.get("lost_samples")),
                fmt_percent(frame.get("unknown_exclusive_percent")),
                sum((frame.get("exclusive_percent") or {}).values()),
                rank,
            )
        )
    add("")
    allocation = summary["quervant_profile"]["allocation"]
    add(f"Allocation capture: `{allocation['status']}`"
        + (f" ({len(allocation['captured'])} lanes)" if allocation["captured"] else ""))
    add("")
    add("Reopen fresh-process single-shot medians (public API probe):")
    add("")
    add("| Documents | Samples | Reopen total ns | Reopen core ns |")
    add("|---:|---:|---:|---:|")
    for n in N_VALUES:
        entry = summary["quervant_profile"]["reopen_single"][str(n)]
        add(
            "| {} | {} | {} | {} |".format(
                fmt_int(n),
                fmt_int(entry["sample_count"]),
                fmt_int(entry["reopen_total_ns_median"]),
                fmt_int(entry["reopen_core_ns_median"]),
            )
        )
    add("")
    add("Stage-level latency is `NOT_MEASURED`: PR 15I-0 does not add production timing")
    add("hooks, so attributions above remain sampled CPU shares, not milliseconds.")
    add("")

    add("## Historical context (never mixed into the tables above)")
    add("")
    add("| Item | Value | Label |")
    add("|---|---:|---|")
    add(
        f"| 100K committed index bytes | {fmt_int(HISTORICAL['index_bytes_100000'])} | {HISTORICAL['label']} |"
    )
    add(
        f"| 100K mutation sidecar bytes | {fmt_int(HISTORICAL['mutation_sidecar_bytes_100000'])} | {HISTORICAL['label']} |"
    )
    add(
        f"| 100K STORED bytes | {fmt_int(HISTORICAL['stored_bytes_100000'])} | {HISTORICAL['label']} |"
    )
    add(
        f"| 100K Dictionary bytes | {fmt_int(HISTORICAL['dictionary_bytes_100000'])} | {HISTORICAL['label']} |"
    )
    add(
        f"| 100K document-v2 dictionary candidate | {fmt_int(REJECTED_CANDIDATE['dictionary_bytes_100000'])} | {REJECTED_CANDIDATE['label']} (`{REJECTED_CANDIDATE['status']}`) |"
    )
    add("")
    return "\n".join(lines) + "\n"


def render_markdown_table(summary: dict) -> str:
    lines = ["# PR 15I-0 — compact measured summary", ""]
    lines.append("| Documents | Engine | Index bytes |")
    lines.append("|---:|---|---:|")
    for n in N_VALUES:
        for engine in ENGINES:
            lines.append(
                f"| {fmt_int(n)} | {engine} | {fmt_int(summary['index_bytes'][str(n)]['bytes'][engine])} |"
            )
    lines.append("")
    lines.append("| Documents | Sidecar bytes | Payload bytes | Overhead bytes |")
    lines.append("|---:|---:|---:|---:|")
    for n in N_VALUES:
        entry = summary["mutation"][str(n)]
        lines.append(
            f"| {fmt_int(n)} | {fmt_int(entry['sidecar_file_bytes'])} | "
            f"{fmt_int(entry['payload_bytes'])} | {fmt_int(entry['container_overhead_bytes'])} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


def scan_reports(root: str) -> dict:
    """Hash and privacy-inspect the complete frozen report inventory.

    Every mandatory report must be present exactly once. A missing, nonregular,
    symlinked, unreadable or non-UTF-8 report is a hard problem: a scan over a
    subset is never `PASS`.
    """
    files = []
    problems = []
    for relative in REPORT_SCAN_TARGETS:
        path = os.path.join(root, relative)
        if os.path.islink(path) or not os.path.isfile(path):
            problems.append({"path": relative, "match": "missing or not a regular file"})
            continue
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError as error:
            problems.append({"path": relative, "match": f"unreadable: {error}"})
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            problems.append({"path": relative, "match": f"not valid UTF-8: {error}"})
            continue
        for pattern, label in PRIVACY_PATTERNS:
            if pattern.search(text):
                problems.append({"path": relative, "match": label})
        files.append({"path": relative, "sha256": sha256_bytes(raw)})
    return {
        "schema": SCHEMA_PRIVACY,
        "status": "PASS" if not problems and len(files) == len(REPORT_SCAN_TARGETS) else "FAIL",
        "files": files,
        "problems": problems,
    }


# ---------------------------------------------------------------------------
# Publication preflight (RF-02 / RF-04)
# ---------------------------------------------------------------------------


def _reject(code: str, detail: str):
    raise SummaryError(f"{code}: {detail}")


def _require_canonical(root: str, value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        _reject("RF02_INPUT_PATH", f"{label} is empty")
    if not os.path.isabs(value):
        _reject("RF02_INPUT_PATH", f"{label} must be an absolute path")
    candidate = os.path.abspath(value)
    if os.path.realpath(value) != candidate:
        _reject("RF02_INPUT_PATH", f"{label} is not canonical or contains a symlink")
    if os.path.islink(candidate) or not os.path.isdir(candidate):
        _reject("RF02_INPUT_PATH", f"{label} is not a real directory")
    relative = os.path.relpath(candidate, root).replace(os.sep, "/")
    if relative.startswith(".."):
        _reject("RF02_INPUT_PATH", f"{label} escapes the repository root")
    return candidate


def validate_output_destinations(root: str, out_json: str, out_md: str) -> dict:
    """Resolve and confine every output destination before any write."""
    resolved = {}
    for argument, supplied in (("out_json", out_json), ("out_md", out_md)):
        flag = "--" + argument.replace("_", "-")
        expected = os.path.join(root, *OUTPUT_REL_PATHS[argument].split("/"))
        if not supplied:
            _reject("RF04_OUTPUT_PATH", f"{flag} is empty")
        # Accept exactly the canonical absolute spelling or the exact canonical
        # repository-relative spelling. Anything that `normpath` would rewrite
        # (`..`, `.`, doubled or trailing separators) is a noncanonical alias.
        candidate = supplied if os.path.isabs(supplied) else os.path.join(root, supplied)
        if os.path.normpath(candidate) != candidate:
            _reject("RF04_OUTPUT_PATH", f"{flag} is not a canonical path")
        if candidate != expected:
            _reject(
                "RF04_OUTPUT_PATH",
                f"{flag} must be exactly {OUTPUT_REL_PATHS[argument]}",
            )
        if os.path.realpath(candidate) != candidate:
            _reject("RF04_OUTPUT_SYMLINK", f"{flag} is a symlink or alias")
        resolved[argument] = candidate
    for relative in IMPLICIT_OUTPUT_REL_PATHS:
        resolved[relative] = os.path.join(root, *relative.split("/"))
    for label, path in resolved.items():
        parent = os.path.dirname(path)
        if not os.path.isdir(parent) or os.path.islink(parent):
            _reject(
                "RF04_OUTPUT_LAYOUT",
                f"output directory for {label} does not exist as a real directory",
            )
        if os.path.realpath(parent) != os.path.abspath(parent):
            _reject("RF04_OUTPUT_SYMLINK", f"output directory for {label} is a symlink")
        if os.path.exists(path):
            if os.path.islink(path) or not os.path.isfile(path):
                _reject(
                    "RF04_OUTPUT_SYMLINK",
                    f"existing output for {label} is not a regular file",
                )
        temporary = path + ".tmp"
        if os.path.lexists(temporary):
            if os.path.islink(temporary) or not os.path.isfile(temporary):
                _reject(
                    "RF04_OUTPUT_SYMLINK",
                    f"stale temporary output for {label} is not a regular file",
                )
    return resolved


def _read_seal(path: str) -> dict:
    try:
        seal = read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        _reject("RF02_SEAL", f"seal {path} is unreadable: {error}")
    if not isinstance(seal, dict):
        _reject("RF02_SEAL", f"seal {path} is not a JSON object")
    return seal


def read_seal_sha(directory: str) -> str:
    path = os.path.join(directory, "seal.json")
    if not os.path.isfile(path):
        _reject("RF02_SEAL", f"{directory} has no seal.json")
    return sha256_file(path)


def validate_verified_publication_inputs(args, verification, root: str) -> dict:
    """Prove that the supplied campaigns are exactly the ones that were verified.

    Runs before ``derive()``, every ``collect_*()`` and every write. Any mismatch
    raises ``SummaryError`` with a stable ``RF02_*`` code and changes no byte.
    """
    if not isinstance(verification, dict):
        _reject("RF02_VERIFICATION", "verification record is not a JSON object")
    if verification.get("test_fixture") is True:
        _reject("RF02_VERIFICATION", "verification record is a synthetic fixture")

    try:
        protocol = verifier.load_protocol(root)
    except verifier.VerificationError as error:
        _reject("RF02_PROTOCOL", f"{error.code}: {error.detail}")
    protocol_sha = protocol["sha256"]

    verification_path = os.path.abspath(args.verification)
    if os.path.realpath(args.verification) != verification_path:
        _reject("RF02_VERIFICATION", "verification path is not canonical")
    target_root = os.path.join(root, "target", "pr15i-0")
    if not verification_path.startswith(target_root + os.sep):
        _reject("RF02_VERIFICATION", "verification must live under target/pr15i-0/")
    if not os.path.isfile(verification_path):
        _reject("RF02_VERIFICATION", "verification record does not exist")

    if verification.get("schema") != verifier.SCHEMA_VERIFICATION:
        _reject("RF02_VERIFICATION", "verification schema drift")
    if verification.get("controller_version") != verifier.CONTROLLER_VERSION:
        _reject("RF02_VERIFICATION", "verification controller version drift")
    if verification.get("qualified") is not True:
        _reject("RF02_NOT_QUALIFIED", "verification is not qualified")
    if verification.get("overall_status") != "15I0_QUALIFIED_REVIEW_READY":
        _reject(
            "RF02_NOT_QUALIFIED",
            f"verification status is {verification.get('overall_status')!r}",
        )
    if verification.get("source_sha") != FROZEN_MEASURED_SOURCE_SHA:
        _reject(
            "RF02_SOURCE",
            f"verification source {verification.get('source_sha')!r} is not the frozen "
            f"measured source {FROZEN_MEASURED_SOURCE_SHA}",
        )
    recorded_protocol = (verification.get("protocol") or {}).get("sha256")
    if recorded_protocol != protocol_sha:
        _reject(
            "RF02_PROTOCOL",
            f"verification protocol {recorded_protocol!r} is not {protocol_sha}",
        )

    gates = verification.get("gates")
    if not isinstance(gates, dict):
        _reject("RF02_GATES", "verification has no gate map")
    if set(gates) != set(verifier.GATE_IDS):
        missing = sorted(set(verifier.GATE_IDS) - set(gates))
        extra = sorted(set(gates) - set(verifier.GATE_IDS))
        _reject(
            "RF02_GATES",
            f"verification gate set mismatch (missing={missing}, extra={extra})",
        )
    statuses = {name: (entry or {}).get("status") for name, entry in gates.items()}
    for gate in verifier.GATE_IDS:
        if gate == "I0-P12":
            continue
        if statuses[gate] != "PASS":
            _reject(
                "RF02_GATES",
                f"required gate {gate} is {statuses[gate]!r}, not PASS",
            )
    if statuses["I0-P12"] not in ("PASS", "NOT_MEASURED"):
        _reject("RF02_GATES", f"allocation gate is {statuses['I0-P12']!r}")

    observations = verification.get("observations")
    if not isinstance(observations, dict):
        _reject("RF02_IDENTITY", "verification has no observations")
    for key in ("pr15d", "pr15f", "mutation"):
        if not isinstance(observations.get(key), dict):
            _reject("RF02_IDENTITY", f"verification has no observations.{key} record")
    inputs = observations.get("inputs")
    if not isinstance(inputs, dict):
        _reject("RF02_IDENTITY", "verification has no observations.inputs")
    expected_labels = {label for label, _flag, _seal in INPUT_LABELS}
    if set(inputs) != expected_labels:
        missing = sorted(expected_labels - set(inputs))
        extra = sorted(set(inputs) - expected_labels)
        _reject(
            "RF02_IDENTITY",
            f"observations.inputs label set mismatch (missing={missing}, extra={extra})",
        )
    seals = observations.get("seals")
    if not isinstance(seals, dict):
        _reject("RF02_IDENTITY", "verification has no observations.seals")

    # Recompute the current identity of every supplied campaign.
    current = verifier.prepare_inputs(
        root,
        {label: _require_canonical(root, getattr(args, label), flag) for label, flag, _s in INPUT_LABELS},
    )

    gate_probe = verifier.Gates()
    corpus_digests = set()
    for label, flag, seal_label in INPUT_LABELS:
        directory = getattr(args, label)
        recorded = inputs[label]
        if not isinstance(recorded, dict):
            _reject("RF02_IDENTITY", f"observations.inputs.{label} is malformed")
        if recorded.get("path") != current[label]["path"]:
            _reject(
                "RF02_INPUT_MISMATCH",
                f"{flag} is {current[label]['path']} but the verification approved "
                f"{recorded.get('path')}",
            )
        if recorded.get("manifests") != current[label]["manifests"]:
            _reject(
                "RF02_MANIFEST_HASH",
                f"{flag} manifest bytes drifted from the verified identity",
            )
        seal_sha = current[label]["seal_sha256"]
        if seal_sha is None:
            _reject("RF02_SEAL", f"{flag} has no seal.json")
        if recorded.get("seal_sha256") != seal_sha:
            _reject("RF02_SEAL", f"{flag} seal.json drifted from the verified identity")
        recorded_seal = seals.get(seal_label)
        if not isinstance(recorded_seal, dict):
            _reject("RF02_IDENTITY", f"observations.seals has no {seal_label} entry")
        if recorded_seal.get("status") != "QUALIFIED":
            _reject("RF02_SEAL", f"{seal_label} observed seal status is not QUALIFIED")
        if recorded_seal.get("sha256") != seal_sha:
            _reject("RF02_SEAL", f"{seal_label} observed seal digest drifted")

        seal = _read_seal(os.path.join(directory, "seal.json"))
        sealed_corpus = seal.get("corpus_manifest_sha256")
        corpus_digests.add(sealed_corpus)

    # Corpus identity: run manifest, prepared manifest and every seal must agree.
    try:
        run_manifest = read_json(os.path.join(args.pr15d_run, "run.json"))
        prepared_manifest = read_json(os.path.join(args.pr15f_prepared, "prepare.json"))
    except (OSError, json.JSONDecodeError) as error:
        _reject("RF02_CORPUS", f"campaign corpus manifests are unreadable: {error}")
    corpus_a = run_manifest.get("corpus_manifest_sha256")
    corpus_b = (prepared_manifest.get("corpus") or {}).get("manifest_sha256")
    if not isinstance(corpus_a, str) or not verifier.SHA256_RE.fullmatch(corpus_a):
        _reject("RF02_CORPUS", "PR 15D corpus manifest digest is invalid")
    if corpus_a != corpus_b:
        _reject("RF02_CORPUS", "PR 15D and PR 15F corpus manifests differ")
    if corpus_digests != {corpus_a}:
        _reject(
            "RF02_CORPUS",
            f"seal corpus digests {sorted(str(item) for item in corpus_digests)} do not "
            f"all equal {corpus_a}",
        )

    # Rehash every sealed campaign with the corrected qualification rules.
    for label, flag, seal_label in INPUT_LABELS:
        directory = getattr(args, label)
        seal = verifier.verify_seal(
            directory,
            FROZEN_MEASURED_SOURCE_SHA,
            protocol_sha,
            corpus_a,
            gate_probe,
            seal_label,
        )
        if seal is None:
            entry = gate_probe.get("I0-P09")
            _reject("RF02_SEAL", f"{seal_label} failed requalification: {entry['detail']}")

    qa_record = observations.get("qa_record")
    if not isinstance(qa_record, dict):
        _reject("RF02_QA", "verification has no observations.qa_record")
    qa_relative = qa_record.get("path")
    qa_sha = qa_record.get("sha256")
    if not isinstance(qa_relative, str) or not isinstance(qa_sha, str):
        _reject("RF02_QA", "observations.qa_record is malformed")
    qa_path = os.path.join(root, *qa_relative.split("/"))
    if os.path.islink(qa_path) or not os.path.isfile(qa_path):
        _reject("RF02_QA", "the referenced QA record is missing or not a regular file")
    if sha256_file(qa_path) != qa_sha:
        _reject("RF02_QA", "the QA record changed after the verification approved it")

    return {
        "verification_path": verification_path,
        "verification_sha256": sha256_file(verification_path),
        "protocol_sha256": protocol_sha,
        "corpus_manifest_sha256": corpus_a,
        "qa_path": qa_path,
        "qa_sha256": qa_sha,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(args) -> int:
    root = os.path.realpath(args.root)
    if not os.path.isdir(root) or not os.path.isfile(os.path.join(root, "Cargo.toml")):
        raise SummaryError("RF02_ROOT: --root is not the repository root")
    try:
        verification = read_json(args.verification)
    except (OSError, json.JSONDecodeError) as error:
        raise SummaryError(f"RF02_VERIFICATION: verification is unreadable: {error}")

    # Every identity and destination check happens before the first derived
    # number is computed and before the first byte is written.
    bound = validate_verified_publication_inputs(args, verification, root)
    destinations = validate_output_destinations(root, args.out_json, args.out_md)

    summary = {
        "schema": SCHEMA_SUMMARY,
        "controller_version": verification.get("controller_version"),
        "source_sha": verification.get("source_sha"),
        "protocol_sha256": (verification.get("protocol") or {}).get("sha256"),
        "verification": {
            "path": os.path.relpath(os.path.abspath(args.verification), root).replace(
                os.sep, "/"
            ),
            "sha256": sha256_file(args.verification),
            "overall_status": verification.get("overall_status"),
            "qualified": verification.get("qualified"),
        },
    }
    summary["binding"] = {
        "protocol_sha256": bound["protocol_sha256"],
        "corpus_manifest_sha256": bound["corpus_manifest_sha256"],
        "qa_record": {
            "path": os.path.relpath(bound["qa_path"], root).replace(os.sep, "/"),
            "sha256": bound["qa_sha256"],
        },
        "inputs": {
            label: {
                "path": os.path.relpath(os.path.abspath(getattr(args, label)), root).replace(
                    os.sep, "/"
                ),
                "seal_sha256": read_seal_sha(os.path.abspath(getattr(args, label))),
            }
            for label, _flag, _seal in INPUT_LABELS
        },
    }
    summary.update(derive(verification, args.pr15d_run, args.pr15f_run, args.mutation_run))
    attach_sections(summary, args.pr15f_run)

    # Render everything in memory, then replace only the five allowlisted files.
    json_bytes = canonical_json_bytes(summary)
    markdown_bytes = render_markdown(summary, verification).encode("utf-8")
    table_bytes = render_markdown_table(summary).encode("utf-8")
    historical = {
        "schema": "pr15i-0-historical-context-v1",
        "label": HISTORICAL["label"],
        "source": HISTORICAL["source"],
        "revision": HISTORICAL["revision"],
        "values": {
            key: value
            for key, value in HISTORICAL.items()
            if key not in ("label", "source", "revision")
        },
        "rejected_candidate": REJECTED_CANDIDATE,
        "mixing_policy": "historical values are never combined with current samples",
    }
    historical_bytes = canonical_json_bytes(historical)

    # The scan inspects the twelve reports including the four just rendered, so it
    # is computed after those bytes exist on disk.
    try:
        json_sha = write_bytes(destinations["out_json"], json_bytes)
        md_sha = write_bytes(destinations["out_md"], markdown_bytes)
        table_sha = write_bytes(
            destinations["benchmarks/reports/pr15i-0/pr15i-0-summary.md"], table_bytes
        )
        historical_sha = write_bytes(
            destinations["benchmarks/reports/pr15i-0/historical-context.json"],
            historical_bytes,
        )
        scan = scan_reports(root)
        scan_sha = write_bytes(
            destinations["benchmarks/reports/pr15i-0/privacy-scan.json"],
            canonical_json_bytes(scan),
        )
    except OSError as error:
        print(
            json.dumps(
                {"status": "PUBLICATION_PARTIAL", "detail": str(error)}, sort_keys=True
            )
        )
        return 2

    print(
        json.dumps(
            {
                "status": "WRITTEN",
                "qualified": summary["qualified"],
                "json_sha256": json_sha,
                "markdown_sha256": md_sha,
                "compact_markdown_sha256": table_sha,
                "historical_context_sha256": historical_sha,
                "privacy_scan": scan["status"],
                "privacy_scan_sha256": scan_sha,
            },
            sort_keys=True,
        )
    )
    return 0 if scan["status"] == "PASS" else 1


SCAN_ONLY_REL = "benchmarks/reports/pr15i-0/privacy-scan.json"


def run_scan_only(root: str) -> int:
    """Recompute the privacy scan for the frozen twelve reports.

    The only permitted write is ``benchmarks/reports/pr15i-0/privacy-scan.json``.
    A failing scan is never written, so a stale PASS can never be manufactured.
    """
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        raise SummaryError("RF02_ROOT: --root is not a directory")
    destination = os.path.join(root, *SCAN_ONLY_REL.split("/"))
    parent = os.path.dirname(destination)
    if not os.path.isdir(parent) or os.path.islink(parent):
        raise SummaryError("RF04_OUTPUT_LAYOUT: the PR 15I-0 report directory is missing")
    if os.path.exists(destination) and (os.path.islink(destination) or not os.path.isfile(destination)):
        raise SummaryError("RF04_OUTPUT_SYMLINK: the privacy scan path is not a regular file")
    scan = scan_reports(root)
    if scan["status"] != "PASS":
        print(
            json.dumps(
                {
                    "status": "SCAN_FAILED",
                    "files": len(scan["files"]),
                    "problems": scan["problems"][:10],
                    "written": False,
                },
                sort_keys=True,
            )
        )
        return 1
    digest = write_bytes(destination, canonical_json_bytes(scan))
    print(
        json.dumps(
            {
                "status": "SCANNED",
                "files": len(scan["files"]),
                "problems": 0,
                "privacy_scan_sha256": digest,
                "written": True,
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--scan-only" in argv:
        parser = argparse.ArgumentParser(
            prog="summarize.py --scan-only",
            description="Recompute only the PR 15I-0 privacy scan.",
            allow_abbrev=False,
        )
        parser.add_argument(
            "--root",
            default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        )
        parser.add_argument("--scan-only", action="store_true", required=True)
        try:
            return run_scan_only(parser.parse_args(argv).root)
        except (SummaryError, OSError) as error:
            print(f"scan-only failed: {error}", file=sys.stderr)
            return 1

    parser = argparse.ArgumentParser(
        prog="summarize.py",
        description="PR 15I-0 stable report calculator.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--root",
        default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )
    parser.add_argument("--verification", required=True)
    parser.add_argument("--pr15d-run", required=True)
    parser.add_argument("--pr15f-run", required=True)
    parser.add_argument("--pr15f-prepared", required=True)
    parser.add_argument("--mutation-run", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (SummaryError, OSError, KeyError, TypeError) as error:
        print(f"summarize failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
