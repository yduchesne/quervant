#!/usr/bin/env python3
"""PR 15F P0 attribution: turn private perf reports into a sanitized analysis.

The parser reads the private ``perf-self.txt`` and ``perf-calltree.txt`` artifacts
that the capture driver already produced. It never re-runs a profiler, never
reads ``perf.data`` and never publishes raw symbols with process metadata.

Two ownership views are produced and kept separate:

* ``exclusive_percent`` — strict self-sample ownership. A symbol's self share is
  assigned to a group only when every *material* call-tree occurrence of that
  symbol resolves to that same group; otherwise the share is unknown (G08/R08).
  Only this view is used by the deterministic ranking rule.
* ``inclusive_percent`` — the maximum single-path inclusive share per group.
  Inclusive paths are never added together.

``allocated_exclusive_percent`` is a clearly labelled diagnostic that splits a
symbol's strict self share across its material occurrence paths in proportion to
those paths' inclusive shares. It is reported for transparency and is **never**
used for ranking.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import profile_queries as pq  # noqa: E402

SCHEMA_ANALYSIS = "pr15f-attribution-v1"
MATERIAL_OCCURRENCE_PERCENT = 0.5

ROW_RE = re.compile(
    r"^\s*(\d+\.\d+)%\s+(\d+\.\d+)%\s+\S+\s+(\S+)\s+\[[.k]\]\s+(\S+)"
)
SELF_RE = re.compile(r"^\s*(\d+\.\d+)%\s+(\S+)\s+\[[.k]\]\s+(\S+)")
BRANCH_RE = re.compile(r"(\|?--)(\d+\.\d+)%--(\S+)\s*$")

QUERY_GROUPS = {
    "G01": "staging/reader",
    "G02": "planning/stats",
    "G03": "columns",
    "G04": "key decoding",
    "G05": "STORED projection",
    "G06A": "posting decode / candidate membership",
    "G06B": "match staging / BM25",
    "G06C": "sort / heap / top-K",
    "G07": "adapter/serialization",
    "G08": "unclassified",
}

REOPEN_GROUPS = {
    "R01": "directory open",
    "R02": "CURRENT / manifest / descriptor verification",
    "R03": "immutable segment read + digest",
    "R04": "segment container parse + metadata",
    "R05": "mutation-state decode",
    "R06": "revision visibility masks",
    "R07": "snapshot creation",
    "R08": "runtime/allocator/unknown",
}

# Ordered (rule id, group, alternative anchors). The first matching rule wins.
# Anchors are matched against both the raw Rust v0 mangled symbol and the
# c++filt-demangled symbol, so classification survives demangler availability.
QUERY_RULES = (
    ("G07", "G07", (r"pr15d_quervant_adapter", r"serde_json", r"projected_doc_id")),
    ("G05", "G05", (r"stored_docs_selected", r"decode_stored_selected",
                    r"project_selected_hits", r"6stored", r"segment::stored")),
    ("G04", "G04", (r"doc_key_selected", r"decode_doc_keys", r"dockey",
                    r"doc_key\b")),
    ("G03", "G03", (r"ColumnAccess", r"ColumnReader", r"typed_compare",
                    r"segment::column", r"6column", r"read_u64_at")),
    ("G01", "G01", (r"open_segment_reader", r"ReaderSnapshot", r"GuardedSegmentReader",
                    r"build_masks_from_readers", r"visibility", r"live_docs")),
    ("G06C", "G06C", (r"collect_mixed", r"sort_tuple_for_doc", r"MixedEntry",
                      r"heap", r"topk", r"cursor")),
    ("G06B", "G06B", (r"score_segment", r"bm25", r"score_lookup", r"scored")),
    ("G06A", "G06A", (r"evaluate_lexical_with", r"build_leaf_data", r"postings",
                      r"Postings", r"membership", r"bitmap", r"candidate")),
    ("G02", "G02", (r"UnifiedSearcher", r"search_impl", r"unified_plan",
                    r"compute_stats", r"unified_plan6compile",
                    r"effective_live_examination_count", r"execute_unified")),
)

REOPEN_RULES = (
    ("R01", "R01", (r"FsDirectory", r"storage3fs", r"storage::fs")),
    ("R07", "R07", (r"new_with_masks", r"ReaderSnapshot", r"snapshot")),
    ("R06", "R06", (r"build_masks_from_readers", r"visibility")),
    ("R05", "R05", (r"MutationStateV1", r"mutation_state", r"synthesize_legacy_state")),
    ("R02", "R02", (r"read_current", r"Manifest::decode", r"manifest",
                    r"7support9read_current")),
    ("R04", "R04", (r"SegmentReader", r"parse_container", r"decode_metadata")),
    ("R03", "R03", (r"verify_bytes", r"read_verified", r"ContentDescriptor",
                    r"ContentDigest", r"format6sha256", r"sha2")),
)

DIGEST_ANCHORS = (
    r"sha2",
    r"format6sha256",
    r"ContentDigest",
    r"ContentDescriptor",
    r"verify_bytes",
)


class AnalysisError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Report parsing
# ---------------------------------------------------------------------------


def parse_self_report(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        match = SELF_RE.match(line)
        if match:
            rows.append(
                {
                    "percent": float(match.group(1)),
                    "dso": match.group(2),
                    "symbol": match.group(3),
                }
            )
    return rows


def parse_header(text: str) -> dict:
    samples = None
    lost = None
    match = re.search(r"#\s*Samples:\s*(\d+(?:\.\d+)?)\s*([KMG]?)\s+of event", text)
    if match:
        scale = {"": 1, "K": 1000, "M": 1000 * 1000, "G": 1000 * 1000 * 1000}
        samples = int(round(float(match.group(1)) * scale[match.group(2)]))
    lost_match = re.search(r"#\s*Total Lost Samples:\s*(\d+)", text)
    if lost_match:
        lost = int(lost_match.group(1))
    return {"sample_count": samples, "lost_samples": lost}


def parse_calltree(text: str) -> list[dict]:
    """Return call-tree occurrences with a reconstructed ancestor path."""
    occurrences: list[dict] = []
    stack: list[tuple[int, str]] = []
    pending: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        row = ROW_RE.match(line)
        if row:
            symbol = row.group(4)
            stack = [(0, symbol)]
            pending = []
            occurrences.append(
                {
                    "percent": float(row.group(1)),
                    "self_percent": float(row.group(2)),
                    "symbol": symbol,
                    "path": [symbol],
                    "kind": "row",
                }
            )
            continue
        branch = BRANCH_RE.search(line)
        if branch:
            column = line.index(branch.group(1))
            symbol = branch.group(3)
            while stack and stack[-1][0] >= column:
                stack.pop()
            path = [symbol for _, symbol in stack] + pending + [symbol]
            occurrences.append(
                {
                    "percent": float(branch.group(2)),
                    "self_percent": None,
                    "symbol": symbol,
                    "path": path,
                    "kind": "branch",
                }
            )
            stack.append((column, symbol))
            pending = []
            continue
        stripped = line.strip().strip("|").strip()
        if stripped and not set(stripped) <= set("| "):
            token = stripped.split()[-1]
            if not token.startswith("0x") and not token.startswith("---"):
                pending.append(token)
    return occurrences


# ---------------------------------------------------------------------------
# Symbol demangling (c++filt is optional; classification works on raw too)
# ---------------------------------------------------------------------------


def demangle_symbols(symbols: list[str], finder=shutil.which) -> tuple[dict, dict]:
    unique = sorted(set(symbols))
    path = finder("c++filt")
    if not path:
        return ({symbol: symbol for symbol in unique}, {"available": False})
    payload = "\n".join(unique) + "\n"
    result = subprocess.run(
        [path],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ({symbol: symbol for symbol in unique}, {"available": False})
    demangled = (result.stdout or "").splitlines()
    if len(demangled) != len(unique):
        return ({symbol: symbol for symbol in unique}, {"available": False})
    version = subprocess.run(
        [path, "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return (
        dict(zip(unique, demangled)),
        {
            "available": True,
            "tool": path,
            "version": (version.stdout or version.stderr or "").splitlines()[0]
            if (version.stdout or version.stderr)
            else None,
        },
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

MUTATION_MARKERS = (r"MutationStateV1", r"mutation_state", r"synthesize_legacy_state")
MANIFEST_MARKERS = (r"read_current", r"Manifest", r"3manifest")
VISIBILITY_MARKERS = (r"build_masks_from_readers", r"visibility")
SNAPSHOT_MARKERS = (r"new_with_masks", r"ReaderSnapshot")
# Frames that enclose the whole measured query process. Their inclusive share is
# tautological (the adapter root contains every operation), so they are excluded
# from inclusive-candidate evidence while their own self samples remain
# classifiable for exclusive ownership.
UMBRELLA_ANCHORS = (
    r"pr15d_quervant_adapter",
    r"QuerySession",
    r"handle_query",
    r"UnifiedSearcher",
    r"search_impl",
    r"execute_unified",
)

_INLINE_TOKEN = "(inlined)"

STANDARD_MARKERS = (
    r"std",
    r"alloc",
    r"libc",
    r"ld-linux",
    r"libgcc",
    r"Unknown",
)


def _matches(symbol: str, anchors) -> bool:
    return any(re.search(anchor, symbol) for anchor in anchors)


def leaf_is_digest(symbol: str) -> bool:
    return _matches(symbol, DIGEST_ANCHORS)


def is_standard_symbol(symbol: str) -> bool:
    return _matches(symbol, STANDARD_MARKERS) and not _matches(
        symbol, (r"quervant_core", r"pr15d_quervant_adapter", r"pr15f_reopen_probe")
    )


def classify_query_symbol(symbol: str) -> str | None:
    if is_standard_symbol(symbol):
        return "G08"
    for _rule, group, anchors in QUERY_RULES:
        if _matches(symbol, anchors):
            return group
    return None


def classify_reopen_leaf(symbol: str) -> str | None:
    if is_standard_symbol(symbol):
        return "R08"
    for _rule, group, anchors in REOPEN_RULES:
        if _matches(symbol, anchors):
            return group
    return None


def classify_reopen_occurrence(path: list[str]) -> str:
    """Map a full caller path to one reopen category, digest-aware.

    A path that contains an integrity-digest frame anywhere (``sha2``,
    ``format::sha256``, ``ContentDigest``, ``ContentDescriptor``) is a digest
    verification path. Its object identity comes from the caller chain:
    mutation-state decode, manifest/CURRENT verification, or segment read.
    """
    if not path:
        return "R08"
    leaf = path[-1]
    joined = " ".join(path)
    if is_standard_symbol(leaf):
        return "R08"
    digest_path = any(leaf_is_digest(symbol) for symbol in path[-3:]) or _matches(
        joined, (r"format6sha256", r"format::sha256", r"sha2")
    )
    if digest_path:
        if _matches(joined, MUTATION_MARKERS):
            return "R05"
        if _matches(joined, MANIFEST_MARKERS):
            return "R02"
        if _matches(
            joined,
            (r"read_verified", r"SegmentReader", r"verify_bytes"),
        ):
            return "R03"
        return "R08"
    if _matches(joined, MUTATION_MARKERS):
        return "R05"
    if _matches(joined, (r"read_current", r"Manifest")):
        return "R02"
    if _matches(joined, VISIBILITY_MARKERS):
        return "R06"
    if _matches(joined, SNAPSHOT_MARKERS):
        return "R07"
    if _matches(joined, (r"FsDirectory", r"storage3fs")):
        return "R01"
    if _matches(
        joined,
        (r"SegmentReader", r"parse_container", r"decode_metadata"),
    ):
        return "R04"
    if _matches(joined, (r"read_verified", r"verify_bytes")):
        return "R03"
    return "R08"


# ---------------------------------------------------------------------------
# Ownership views
# ---------------------------------------------------------------------------


def summarise(
    self_rows: list[dict],
    calltree: list[dict],
    *,
    mode: str,
    demangled: dict,
) -> dict:
    """Return strict exclusive, inclusive and diagnostic allocated shares."""
    if mode == "query":
        groups = QUERY_GROUPS
        unknown = "G08"
        leaf_group = lambda symbol: classify_query_symbol(symbol) or unknown  # noqa: E731
    elif mode == "reopen":
        groups = REOPEN_GROUPS
        unknown = "R08"
        leaf_group = lambda symbol: classify_reopen_leaf(symbol) or unknown  # noqa: E731
    else:  # pragma: no cover - defensive
        raise AnalysisError("X40_MODE", f"unknown attribution mode {mode!r}")

    # Material call-tree occurrences per raw symbol, with their category.
    material: dict[str, list[dict]] = {}
    inclusive_by_group: dict[str, float] = {group: 0.0 for group in groups}
    inclusive_paths: dict[str, list[str]] = {group: [] for group in groups}
    for occurrence in calltree:
        percent = occurrence["percent"]
        if percent < MATERIAL_OCCURRENCE_PERCENT:
            continue
        path = [
            _normalise_symbol(symbol, demangled)
            for symbol in occurrence["path"]
            if symbol != _INLINE_TOKEN and not symbol.startswith("0x")
        ]
        # perf repeats aggregated summary roots; only a contextual path (at least
        # three frames, i.e. root -> stage -> leaf) is attributable.
        if len(path) < 3:
            continue
        category = (
            classify_reopen_occurrence(path)
            if mode == "reopen"
            else leaf_group(path[-1] if path else "")
        )
        umbrella = mode == "query" and _matches(path[-1], UMBRELLA_ANCHORS)
        if not umbrella and percent > inclusive_by_group[category]:
            inclusive_by_group[category] = percent
            inclusive_paths[category] = path
        raw_leaf = occurrence["symbol"]
        material.setdefault(raw_leaf, []).append(
            {"percent": percent, "category": category, "path": path}
        )

    exclusive_by_group: dict[str, float] = {group: 0.0 for group in groups}
    allocated_by_group: dict[str, float] = {group: 0.0 for group in groups}
    ambiguous: dict[str, dict] = {}
    parsed_total = 0.0
    for row in self_rows:
        raw_symbol = row["symbol"]
        symbol = _normalise_symbol(raw_symbol, demangled)
        share = row["percent"]
        parsed_total += share
        occurrences = material.get(raw_symbol, [])
        categories = sorted({occurrence["category"] for occurrence in occurrences})
        if not occurrences and mode == "query":
            # Leaf rules are group-specific for queries; a missing contextual
            # call-tree occurrence does not make the owner uncertain.
            categories = [leaf_group(symbol)]
        if len(categories) == 1:
            exclusive_by_group[categories[0]] += share
        else:
            # No material call-tree occurrence, or more than one logical owner.
            exclusive_by_group[unknown] += share
            if len(categories) > 1:
                ambiguous[symbol] = {
                    "self_percent": round(share, 4),
                    "categories": categories,
                }
        if occurrences:
            weights = sum(occurrence["percent"] for occurrence in occurrences)
            for occurrence in occurrences:
                allocated_by_group[occurrence["category"]] += (
                    share * occurrence["percent"] / weights
                )
        else:
            allocated_by_group[unknown] += share

    # Rows below perf's 0.5% display threshold were not printed; they are unknown.
    remainder = max(0.0, 100.0 - parsed_total)
    exclusive_by_group[unknown] += remainder

    def _round(mapping):
        return {key: round(value, 4) for key, value in mapping.items()}

    exclusive = _round(exclusive_by_group)
    inclusive = _round(inclusive_by_group)
    allocated = _round(allocated_by_group)
    exclusive_total = round(sum(exclusive.values()), 4)
    if exclusive_total > 100.0 + 1e-6:
        raise AnalysisError(
            "X41_PARTITION", f"exclusive ownership sums to {exclusive_total}"
        )
    return {
        "mode": mode,
        "groups": groups,
        "exclusive_percent": exclusive,
        "inclusive_percent": inclusive,
        "allocated_exclusive_percent": allocated,
        "unknown_exclusive_percent": exclusive[unknown],
        "exclusive_total_percent": exclusive_total,
        "ambiguous_symbols": ambiguous,
        "inclusive_paths": {
            group: path for group, path in inclusive_paths.items() if path
        },
        "unparsed_remainder_percent": round(remainder, 4),
    }


def _normalise_symbol(raw: str, demangled: dict) -> str:
    return demangled.get(raw, raw)


# ---------------------------------------------------------------------------
# Deterministic ranking rule (P4 §8.2)
# ---------------------------------------------------------------------------


def stage_key(path: list[str]) -> str:
    """Logical reopen stage for an inclusive path, most specific object first."""
    joined = " ".join(path)
    if _matches(joined, MUTATION_MARKERS):
        return "mutation_state"
    if _matches(joined, (r"read_current", r"Manifest")):
        return "manifest"
    if _matches(joined, VISIBILITY_MARKERS):
        return "visibility"
    if _matches(joined, SNAPSHOT_MARKERS):
        return "snapshot"
    if _matches(joined, (r"FsDirectory", r"storage3fs")):
        return "directory"
    if _matches(joined, (r"SegmentReader", r"parse_container", r"decode_metadata")):
        return "segment_container"
    if _matches(joined, (r"read_verified", r"verify_bytes")):
        return "segment_digest"
    return "root"


def _contiguous_sublist(shorter: list[str], longer: list[str]) -> bool:
    if not shorter or not longer or len(shorter) > len(longer):
        return False
    for start in range(len(longer) - len(shorter) + 1):
        if longer[start : start + len(shorter)] == shorter:
            return True
    return False


def _paths_overlap(left: list[str], right: list[str], mode: str = "reopen") -> bool:
    """True when both inclusive paths belong to the same call subtree."""
    if not left or not right:
        return False
    if mode == "query":
        # Query call trees repeat aggregated roots; an ancestor/descendant chain
        # is the same subtree and therefore not a disjoint competitor.
        return _contiguous_sublist(left, right) or _contiguous_sublist(right, left)
    left_key = stage_key(left)
    return left_key != "root" and left_key == stage_key(right)


def classify_workload(shares: dict, groups: dict) -> dict:
    unknown = groups.get("__unknown__")
    exclusive = {
        key: value
        for key, value in shares["exclusive_percent"].items()
        if value and key != unknown
    }
    inclusive = {
        key: value
        for key, value in shares["inclusive_percent"].items()
        if value and key != unknown
    }
    unknown_share = shares["unknown_exclusive_percent"]
    ordered = sorted(exclusive.items(), key=lambda item: (-item[1], item[0]))
    top_group, top_share = ordered[0] if ordered else (None, 0.0)
    second_share = ordered[1][1] if len(ordered) > 1 else 0.0
    strong = (
        top_group is not None
        and top_share >= 20.0
        and (top_share - second_share) >= 5.0
        and unknown_share <= 10.0
    )
    if strong:
        return {
            "classification": "STRONG_EXCLUSIVE_CANDIDATE",
            "group": top_group,
            "exclusive_percent": top_share,
            "runner_up_percent": second_share,
            "unknown_exclusive_percent": unknown_share,
            "rule": "RULE_STRONG_EXCLUSIVE_20_5_10",
        }
    paths = shares.get("inclusive_paths", {})
    mode = shares.get("mode", "reopen")
    qualifying = [
        (group, value)
        for group, value in inclusive.items()
        if value >= 35.0
    ]
    eligible = []
    for group, value in qualifying:
        path = paths.get(group, [])
        disjoint = False
        for other, other_value in qualifying:
            if other == group or other_value < 35.0:
                continue
            other_path = paths.get(other, [])
            if not _paths_overlap(path, other_path, mode):
                disjoint = True
                break
        if not disjoint:
            eligible.append((group, value, len(path)))
    if eligible:
        group, share, _depth = sorted(eligible, key=lambda item: (-item[2], -item[1], item[0]))[0]
        return {
            "classification": "LIKELY_INCLUSIVE_CANDIDATE",
            "group": group,
            "inclusive_percent": share,
            "unknown_exclusive_percent": unknown_share,
            "rule": "RULE_INCLUSIVE_35",
            "note": "inclusive-only; not an estimated improvement",
        }
    return {
        "classification": "UNRESOLVED",
        "unknown_exclusive_percent": unknown_share,
        "rule": "RULE_UNRESOLVED",
    }


# ---------------------------------------------------------------------------
# Campaign analysis
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as error:
        raise AnalysisError("X40_EVIDENCE", f"cannot read {path}: {error}")


def analyse_capture(capture_dir: str, *, mode: str) -> dict:
    capture = pq.read_json(os.path.join(capture_dir, "capture.json"))
    self_text = _read(os.path.join(capture_dir, "perf-self.txt"))
    calltree_text = _read(os.path.join(capture_dir, "perf-calltree.txt"))
    self_rows = parse_self_report(self_text)
    calltree = parse_calltree(calltree_text)
    header = parse_header(self_text)
    raw_symbols = [row["symbol"] for row in self_rows] + [
        occurrence["symbol"] for occurrence in calltree
    ]
    demangled, demangler = demangle_symbols(raw_symbols)
    shares = summarise(self_rows, calltree, mode=mode, demangled=demangled)
    unknown = "G08" if mode == "query" else "R08"
    groups = {"__unknown__": unknown, **shares["groups"]}
    ranking = classify_workload(shares, groups)
    return {
        "capture_id": capture.get("capture_id"),
        "lane_id": capture.get("lane_id"),
        "tool": capture.get("tool"),
        "n": capture.get("n"),
        "class": capture.get("class"),
        "k": capture.get("k"),
        "seconds": capture.get("seconds"),
        "sample_count": header["sample_count"],
        "lost_samples": header["lost_samples"],
        "profiled_query_count": capture.get("profiled_query_count"),
        "warmups": capture.get("warmups"),
        "adapter_pid_samples": capture.get("adapter_pid_sample_count"),
        "contention_before": capture.get("contention_before"),
        "contention_after": capture.get("contention_after"),
        "source_sha": capture.get("source_sha"),
        "binary_sha256": capture.get("binary_sha256"),
        "tool_version": capture.get("tool_version"),
        "demangler": demangler,
        "self_rows": len(self_rows),
        "calltree_occurrences": len(calltree),
        "material_occurrence_percent": MATERIAL_OCCURRENCE_PERCENT,
        **shares,
        "rank": ranking,
    }


def _layout_summary(run_dir: str, n: int) -> dict:
    record = pq.read_json(os.path.join(run_dir, "inventory", f"n{n}.json"))
    sections = sorted(
        record["section_bytes"].items(), key=lambda item: (-item[1], item[0])
    )
    top = [
        {"kind": kind, "bytes": value}
        for kind, value in sections[:3]
    ]
    return {
        "total_file_bytes": record["total_file_bytes"],
        "bytes_per_document": round(record["total_file_bytes"] / n, 3),
        "segment_file_bytes": record["segment_file_bytes"],
        "manifest_file_bytes": record["manifest_file_bytes"],
        "mutation_state_file_bytes": record["mutation_state_file_bytes"],
        "metadata_file_bytes": record["metadata_file_bytes"],
        "segment_section_bytes_total": record["segment_section_bytes_total"],
        "segment_nonsection_bytes_total": record["segment_nonsection_bytes_total"],
        "section_bytes": record["section_bytes"],
        "section_counts": record["section_counts"],
        "top_three_sections": top,
        "top_three_share_percent": round(
            100.0 * sum(entry["bytes"] for entry in top) / record["total_file_bytes"], 4
        ),
        "content_sha256": record["content_sha256"],
        "read_only": record["read_only"],
        "reconciliation": record["reconciliation"],
        "work_requires_format_change": True,
        "architecture_label": "ARCHITECTURE_DESIGN_REQUIRED",
    }


def build_analysis(run_dir: str) -> dict:
    preflight = pq.read_json(os.path.join(run_dir, "preflight.json"))
    queries = {}
    for descriptor in pq.perf_lane_descriptors():
        capture_dir = os.path.join(run_dir, descriptor["rel_dir"].replace("/", os.sep))
        if not os.path.isfile(os.path.join(capture_dir, "capture.json")):
            queries[descriptor["pr15f_lane_id"]] = {
                "capture_id": descriptor["capture_id"],
                "status": "NOT_CAPTURED",
            }
            continue
        queries[descriptor["pr15f_lane_id"]] = analyse_capture(capture_dir, mode="query")

    reopen = {}
    for n in pq.eprofile.N_VALUES:
        capture_dir = os.path.join(run_dir, "reopen", "perf", f"n{n}")
        if not os.path.isfile(os.path.join(capture_dir, "capture.json")):
            reopen[str(n)] = {"status": "NOT_CAPTURED"}
            continue
        record = analyse_capture(capture_dir, mode="reopen")
        record["loop_iterations"] = pq.eprofile.read_json(
            os.path.join(capture_dir, "capture.json")
        ).get("profiled_query_count")
        reopen[str(n)] = record

    layout = {}
    for n in pq.eprofile.N_VALUES:
        path = os.path.join(run_dir, "inventory", f"n{n}.json")
        layout[str(n)] = _layout_summary(run_dir, n) if os.path.isfile(path) else {
            "status": "NOT_CAPTURED"
        }

    # Ranking summary: keep only defined classifications in the headline map.
    ranking = {
        "query": {
            lane: value.get("rank", {"classification": "UNRESOLVED"})
            for lane, value in queries.items()
        },
        "reopen": {
            n: value.get("rank", {"classification": "UNRESOLVED"})
            for n, value in reopen.items()
        },
        "layout": {
            n: {
                "classification": value.get("architecture_label", "NOT_CAPTURED"),
                "total_file_bytes": value.get("total_file_bytes"),
                "top_three_sections": value.get("top_three_sections"),
            }
            for n, value in layout.items()
        },
    }
    return {
        "schema": SCHEMA_ANALYSIS,
        "measured_source_sha": preflight["source_sha"],
        "probe_binary_sha256": preflight["probe"]["binary_sha256"],
        "methods": {
            "exclusive": (
                "strict self samples; a symbol is owned only when every material "
                "call-tree occurrence resolves to one group, else unknown"
            ),
            "inclusive": (
                "maximum single-path inclusive share per group; never summed"
            ),
            "allocated_exclusive": (
                "diagnostic proportional split of a symbol's self share over its "
                "material occurrence paths; never used for ranking"
            ),
            "material_occurrence_percent": MATERIAL_OCCURRENCE_PERCENT,
        },
        "non_additivity_warning": (
            "Exclusive percentages partition self samples; inclusive percentages "
            "overlap and must never be added to them or to each other."
        ),
        "ranking_rules": {
            "STRONG_EXCLUSIVE": ">=20.0% top exclusive, >=5.0pp lead, unknown <=10.0%",
            "LIKELY_INCLUSIVE": ">=35.0% inclusive with no competing >=35.0% path",
            "else": "UNRESOLVED",
        },
        "query": queries,
        "reopen": reopen,
        "layout": layout,
        "ranking": ranking,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="attribution.py",
        description="PR 15F P0 deterministic attribution and ranking.",
        allow_abbrev=False,
    )
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_dir = pq.resolve_run_dir(args.run, must_exist=True)
        analysis = build_analysis(run_dir)
        out = pq.eprofile.resolve_under(
            os.path.dirname(os.path.abspath(run_dir)),
            args.out,
            label="analysis output",
            base=REPO_ROOT,
        )
        pq.write_json(out, analysis)
    except (pq.Pr15fError, AnalysisError) as error:
        code = getattr(error, "code", "X99")
        print(f"{code}: {error}", file=sys.stderr)
        return pq.EXIT_FAILED
    print(
        json.dumps(
            {
                "status": "ANALYSED",
                "schema": SCHEMA_ANALYSIS,
                "query_lanes": len(analysis["query"]),
                "reopen": sorted(analysis["reopen"]),
            },
            sort_keys=True,
        )
    )
    return pq.EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
