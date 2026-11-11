#!/usr/bin/env python3
"""Materialize the PR 15I-D2-A diagnostic source derivative.

This script is the *only* authorized way to produce the instrumented scratch
tree used for the A/Q/P attribution measurements.  It applies a closed set of
literal, insertion-only edits to a pristine `BASE` worktree and then proves that
removing exactly those inserted bytes restores the original `BASE` bytes.

The script never touches accepted production source, never changes an algorithm,
and never commits anything.  The committed repository contains this deterministic
materializer and its independent proof (`source_proof.py`), not the derivative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

BASE_SHA = "9429dce99827f25766a92c1fbded8f78a0b168f1"
FEATURE = "pr15id2a-probe"

UNIFIED = "crates/quervant-core/src/search/unified.rs"
EXECUTE = "crates/quervant-core/src/search/execute.rs"
SEARCH_MOD = "crates/quervant-core/src/search/mod.rs"
D2A_PROBE = "crates/quervant-core/src/search/d2a_probe.rs"
CORE_CARGO = "crates/quervant-core/Cargo.toml"
ADAPTER = "benchmarks/pr15d/adapters/quervant/src/main.rs"

DERIVATIVE_FILES = (UNIFIED, EXECUTE, SEARCH_MOD, D2A_PROBE, CORE_CARGO, ADAPTER)

REGIONS = {
    (UNIFIED, "execute_unified"): (
        "    fn execute_unified(",
        "    fn keyword_sort_late_eligible(",
    ),
    (UNIFIED, "collect_mixed"): (
        "    fn collect_mixed(",
        "\n}\n\nimpl std::fmt::Debug for UnifiedSearcher<'_>",
    ),
    (EXECUTE, "evaluate_lexical_with"): (
        "pub(crate) fn evaluate_lexical_with<",
        "\n#[cfg(test)]\nmod budget_tests",
    ),
    (EXECUTE, "score_segment"): (
        "fn score_segment(\n",
        "\n/// Test-only observation of membership callbacks.",
    ),
}

D2A_PROBE_RS = '''//! Diagnostic-only, thread-local recorder; never committed to Quervant.
use std::cell::{Cell, RefCell};
use std::time::Instant;

pub const PLAN: usize = 0;
pub const READER_LIVE: usize = 1;
pub const EXPAND: usize = 2;
pub const STATS: usize = 3;
pub const EVALUATE: usize = 4;
pub const CANDIDATE: usize = 5;
pub const PROJECTION: usize = 6;
pub const LEAF_DECODE: usize = 7;
pub const MEMBERSHIP: usize = 8;
pub const SCORE_VECTOR: usize = 9;
pub const SCORE_MAP: usize = 10;
pub const SCORE_OWNER: usize = 11;
pub const SCORE_ACCUMULATE: usize = 12;
pub const MATCHED_COUNT: usize = 0;
pub const SCORED_COUNT: usize = 1;
pub const CANDIDATE_COUNT: usize = 2;
pub const BM25_CALLS: usize = 3;
pub const SCORING_MAP_ENTRIES: usize = 4;
pub const POSITIVE_TERM_OWNERS: usize = 5;
pub const NAMES: [&str; 13] = [
    "plan_ns", "reader_live_ns", "expand_ns", "stats_ns",
    "evaluate_ns", "candidate_ns", "projection_ns", "leaf_decode_ns",
    "membership_ns", "score_vector_ns", "score_map_ns", "score_owner_ns",
    "score_accumulate_ns",
];
pub const COUNT_NAMES: [&str; 6] = [
    "matched_docs", "scored_docs", "candidate_docs", "bm25_calls",
    "scoring_map_entries", "positive_term_owners",
];
thread_local! {
    static ACTIVE: Cell<bool> = const { Cell::new(false) };
    static STAGES: RefCell<[u64; 13]> = const { RefCell::new([0; 13]) };
    static COUNTS: RefCell<[u64; 6]> = const { RefCell::new([0; 6]) };
}

pub fn reset() {
    STAGES.with(|x| *x.borrow_mut() = [0; 13]);
    COUNTS.with(|x| *x.borrow_mut() = [0; 6]);
    ACTIVE.with(|x| x.set(true));
}

pub struct Span { id: usize, start: Option<Instant> }
pub fn span(id: usize) -> Span {
    assert!(id < NAMES.len(), "invalid diagnostic timer");
    let start = ACTIVE.with(|x| x.get().then(Instant::now));
    Span { id, start }
}
impl Drop for Span {
    fn drop(&mut self) {
        if let Some(start) = self.start {
            let elapsed = u64::try_from(start.elapsed().as_nanos())
                .expect("diagnostic timer overflow");
            STAGES.with(|x| {
                let mut data = x.borrow_mut();
                data[self.id] = data[self.id].checked_add(elapsed)
                    .expect("diagnostic stage accumulator overflow");
            });
        }
    }
}
pub fn count(id: usize, value: u64) {
    assert!(id < COUNT_NAMES.len(), "invalid diagnostic counter");
    if ACTIVE.with(Cell::get) {
        COUNTS.with(|x| {
            let mut data = x.borrow_mut();
            data[id] = data[id].checked_add(value)
                .expect("diagnostic count overflow");
        });
    }
}
/// MUST be called after `engine_ns` has already stopped.
pub fn take() -> (Vec<(&'static str, u64)>, Vec<(&'static str, u64)>) {
    ACTIVE.with(|x| x.set(false));
    let stages = STAGES.with(|x| *x.borrow());
    let counts = COUNTS.with(|x| *x.borrow());
    (
        NAMES.iter().copied().zip(stages).collect(),
        COUNT_NAMES.iter().copied().zip(counts).collect(),
    )
}
'''

# Closed, insertion-only edit inventory.  Every literal below is copied from the
# frozen PR 15I-D2-A plan; the independent proof carries its own copy.
EDITS = [
    # --- crates/quervant-core/Cargo.toml -----------------------------------
    {
        "file": CORE_CARGO,
        "function": "features",
        "region": None,
        "anchor": "[features]\n",
        "placement": "after",
        "text": "pr15id2a-probe = []\n",
        "label": "FEATURE",
    },
    # --- crates/quervant-core/src/search/mod.rs ----------------------------
    {
        "file": SEARCH_MOD,
        "function": "module_declarations",
        "region": None,
        "anchor": "#[cfg(test)]\nmod diagnostics;\n",
        "placement": "after",
        "text": '#[cfg(feature = "pr15id2a-probe")]\npub mod d2a_probe;\n',
        "label": "MODULE",
    },
    # --- mechanical compile-path imports (required for Rust name resolution) --
    {
        "file": UNIFIED,
        "function": "imports",
        "region": None,
        "anchor": "use super::error::{SearchError, SearchResult};\n",
        "placement": "before",
        "text": "use super::d2a_probe;\n",
        "label": "IMPORT",
    },
    {
        "file": EXECUTE,
        "function": "imports",
        "region": None,
        "anchor": "use super::error::{SearchError, SearchResult};\n",
        "placement": "before",
        "text": "use super::d2a_probe;\n",
        "label": "IMPORT",
    },
    # --- crates/quervant-core/src/search/unified.rs ------------------------
    {
        "file": UNIFIED,
        "function": "execute_unified",
        "region": "execute_unified",
        "anchor": "let bindings =",
        "placement": "before",
        "text": "let _d0_plan = d2a_probe::span(d2a_probe::PLAN);\n        ",
        "label": "PLAN_START",
    },
    {
        "file": UNIFIED,
        "function": "execute_unified",
        "region": "execute_unified",
        "anchor": "let (page, total_hits, next_cursor, aggregation_result) = self.collect_mixed(",
        "placement": "before",
        "text": "drop(_d0_plan);\n        ",
        "label": "PLAN_END",
    },
    {
        "file": UNIFIED,
        "function": "execute_unified",
        "region": "execute_unified",
        "anchor": "let fields = project_selected_hits(",
        "placement": "before",
        "text": "let _d0_projection = d2a_probe::span(d2a_probe::PROJECTION);\n        ",
        "label": "PROJECTION_START",
    },
    {
        "file": UNIFIED,
        "function": "execute_unified",
        "region": "execute_unified",
        "anchor": "let retained = if retain {",
        "placement": "before",
        "text": "drop(_d0_projection);\n        ",
        "label": "PROJECTION_END",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let mut guards = Vec::new();",
        "placement": "before",
        "text": "let _d0_reader = d2a_probe::span(d2a_probe::READER_LIVE);\n        ",
        "label": "READER_LIVE_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let synth = plan::synthetic_query(plan);",
        "placement": "before",
        "text": "drop(_d0_reader);\n        ",
        "label": "READER_LIVE_END",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let expansion = {",
        "placement": "before",
        "text": "let _d0_expand = d2a_probe::span(d2a_probe::EXPAND);\n        ",
        "label": "EXPAND_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let stats = {",
        "placement": "before",
        "text": (
            "drop(_d0_expand);\n        "
            "let _d0_stats = d2a_probe::span(d2a_probe::STATS);\n        "
        ),
        "label": "EXPAND_END_STATS_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let mut budget = CandidateBudget::new(",
        "placement": "before",
        "text": "drop(_d0_stats);\n        ",
        "label": "STATS_END",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let scored = execute::evaluate_lexical_with(",
        "placement": "before",
        "text": "let _d0_evaluate = d2a_probe::span(d2a_probe::EVALUATE);\n            ",
        "label": "EVALUATE_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "// PR 15E Phase 5:",
        "placement": "before",
        "text": (
            "drop(_d0_evaluate);\n            "
            "d2a_probe::count(d2a_probe::CANDIDATE_COUNT,\n"
            '                u64::try_from(scored.len()).expect("diagnostic candidate count overflow"));\n'
            "            let _d0_candidate = d2a_probe::span(d2a_probe::CANDIDATE);\n"
            "            "
        ),
        "label": "EVALUATE_END_CANDIDATE_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "// Drop the geo allocations first; their batch reservations",
        "placement": "before",
        "text": "drop(_d0_candidate);\n            ",
        "label": "CANDIDATE_END",
    },
    # --- crates/quervant-core/src/search/execute.rs ------------------------
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let (leaf_data, leaf_charges) = {",
        "placement": "before",
        "text": "let _d0_leaf = d2a_probe::span(d2a_probe::LEAF_DECODE);\n    ",
        "label": "LEAF_DECODE_START",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let mut matched: BTreeSet<u64> = BTreeSet::new();",
        "placement": "before",
        "text": (
            "drop(_d0_leaf);\n    "
            "let _d0_membership = d2a_probe::span(d2a_probe::MEMBERSHIP);\n    "
        ),
        "label": "LEAF_DECODE_END_MEMBERSHIP_START",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let matched_entries = matched.len() as u64;",
        "placement": "before",
        "text": "drop(_d0_membership);\n    ",
        "label": "MEMBERSHIP_END",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let matched_entries = matched.len() as u64;",
        "placement": "after",
        "text": "\n    d2a_probe::count(d2a_probe::MATCHED_COUNT, matched_entries);",
        "label": "MATCHED_COUNT",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let (scored, scored_charges) = score_segment(",
        "placement": "before",
        "text": "let _d0_score = d2a_probe::span(d2a_probe::SCORE_VECTOR);\n    ",
        "label": "SCORE_VECTOR_START",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "// Segment-owned temporaries are released here;",
        "placement": "before",
        "text": "drop(_d0_score);\n    ",
        "label": "SCORE_VECTOR_END",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let scored_vec: Vec<(u64, f64)> = scored.into_iter().collect();",
        "placement": "after",
        "text": (
            "\n    d2a_probe::count(d2a_probe::SCORED_COUNT,\n"
            '        u64::try_from(scored_vec.len()).expect("diagnostic score count overflow"));'
        ),
        "label": "SCORED_COUNT",
    },
    # --- benchmarks/pr15d/adapters/quervant/src/main.rs -------------------
    {
        "file": ADAPTER,
        "function": "imports",
        "region": None,
        "anchor": "use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};\n",
        "placement": "after",
        "text": "use quervant_core::search::d2a_probe;\n",
        "label": "IMPORT",
    },
    {
        "file": ADAPTER,
        "function": "run",
        "region": None,
        "anchor": '"metadata" => Ok(json!({',
        "placement": "before",
        "text": (
            '"query_probe" => {\n'
            "                if session.is_none() {\n"
            "                    let path = active_index_dir.as_deref().ok_or_else(|| {\n"
            '                        AdapterError::new("request", "query mode requires --index-dir")\n'
            "                    })?;\n"
            "                    session = Some(QuerySession::open(path)?);\n"
            "                }\n"
            "                d2a_probe::reset();\n"
            "                let mut body = session.as_ref()\n"
            '                    .expect("query session is always present here")\n'
            "                    .query(&request)?;\n"
            "                let (stages, counts) = d2a_probe::take();\n"
            "                let object = body.as_object_mut().ok_or_else(|| {\n"
            '                    AdapterError::new("diagnostic", "query body was not an object")\n'
            "                })?;\n"
            '                object.insert("stage_ns".to_owned(), json!(stages));\n'
            '                object.insert("counts".to_owned(), json!(counts));\n'
            "                Ok(body)\n"
            "            },\n"
            "            "
        ),
        "label": "QUERY_PROBE_ARM",
    },
    # --- PR 15I-D2-A nested score subspans and counters (scratch only) -----
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "let entries = matches.len() as u64;",
        "placement": "before",
        "text": "let _d2a_score_map = d2a_probe::span(d2a_probe::SCORE_MAP);\n    ",
        "label": "SCORE_MAP_START",
    },
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "if scores.is_empty() {",
        "placement": "before",
        "text": (
            "drop(_d2a_score_map);\n    "
            "d2a_probe::count(d2a_probe::SCORING_MAP_ENTRIES, entries);\n    "
        ),
        "label": "SCORE_MAP_END_MAP_COUNT",
    },
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "return Ok((scores, charges));",
        "placement": "before",
        "text": (
            "d2a_probe::count(d2a_probe::BM25_CALLS, 0);\n            "
            "d2a_probe::count(d2a_probe::POSITIVE_TERM_OWNERS, 0);\n            "
        ),
        "label": "EMPTY_ZERO_COUNTS",
    },
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "let mut owner: BTreeMap<(u32, &str), usize> = BTreeMap::new();",
        "placement": "before",
        "text": "let _d2a_score_owner = d2a_probe::span(d2a_probe::SCORE_OWNER);\n    ",
        "label": "SCORE_OWNER_START",
    },
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "    for (index, leaf) in leaf_data.iter().enumerate() {\n        // Only scoring-eligible (positive/even-`Not`-parity) leaves contribute.",
        "placement": "before",
        "text": (
            "    drop(_d2a_score_owner);\n    "
            "d2a_probe::count(d2a_probe::POSITIVE_TERM_OWNERS,\n"
            '        u64::try_from(owner.len()).expect("diagnostic owner count overflow"));\n'
            "    let _d2a_score_accumulate = "
            "d2a_probe::span(d2a_probe::SCORE_ACCUMULATE);\n    "
        ),
        "label": "SCORE_OWNER_END_OWNER_COUNT_ACCUMULATE_START",
    },
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "                            let dl = field_stats.length(segment_index, *doc_id);\n",
        "placement": "after",
        "text": (
            "                            "
            "d2a_probe::count(d2a_probe::BM25_CALLS, 1);\n"
        ),
        "label": "BM25_CALL_TERM",
    },
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "                        let dl = field_stats.length(segment_index, phrase_match.doc_id);\n",
        "placement": "after",
        "text": (
            "                        "
            "d2a_probe::count(d2a_probe::BM25_CALLS, 1);\n"
        ),
        "label": "BM25_CALL_PHRASE",
    },
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "    Ok((scores, charges))\n}",
        "placement": "before",
        "text": "    drop(_d2a_score_accumulate);\n",
        "label": "SCORE_ACCUMULATE_END",
    },
]


class PatchError(Exception):
    """A precise, typed rejection.  Never converted into partial success."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def extract_region(text: str, delimiters, path: str, region: str) -> tuple[int, int]:
    start_delim, stop_delim = delimiters
    if text.count(start_delim) != 1:
        raise PatchError(
            "D2A_PATCH_REGION",
            f"{path}:{region}: start delimiter occurs {text.count(start_delim)} times",
        )
    if text.count(stop_delim) != 1:
        raise PatchError(
            "D2A_PATCH_REGION",
            f"{path}:{region}: stop delimiter occurs {text.count(stop_delim)} times",
        )
    start = text.index(start_delim)
    stop = text.index(stop_delim)
    if stop <= start:
        raise PatchError(
            "D2A_PATCH_REGION", f"{path}:{region}: stop delimiter precedes start"
        )
    return start, stop


def find_unique(text: str, anchor: str, start: int, stop: int, path: str, label: str) -> int:
    region = text[start:stop]
    count = region.count(anchor)
    if count != 1:
        raise PatchError(
            "D2A_PATCH_ANCHOR",
            f"{path}:{label}: anchor {anchor!r} occurs {count} times in region",
        )
    return start + region.index(anchor)


def apply_edits(base_text: str, file: str) -> tuple[str, list[dict]]:
    """Insert the approved literals for ``file``; return text + insertion inventory."""
    file_edits = [edit for edit in EDITS if edit["file"] == file]
    points = []
    for sequence, edit in enumerate(file_edits):
        if edit["region"] is None:
            start, stop = 0, len(base_text)
        else:
            start, stop = extract_region(
                base_text, REGIONS[(file, edit["region"])], file, edit["region"]
            )
        index = find_unique(base_text, edit["anchor"], start, stop, file, edit["label"])
        point = index if edit["placement"] == "before" else index + len(edit["anchor"])
        points.append((point, sequence, edit, index))
    points.sort(key=lambda item: (item[0], item[1]))

    pieces = []
    insertions = []
    cursor = 0
    written = 0
    for point, _sequence, edit, anchor_index in points:
        if point < cursor:
            raise PatchError(
                "D2A_PATCH_OVERLAP",
                f"{file}:{edit['label']}: insertion point {point} precedes cursor {cursor}",
            )
        chunk = base_text[cursor:point]
        pieces.append(chunk)
        written += len(chunk)
        insertions.append(
            {
                "file": file,
                "function": edit["function"],
                "label": edit["label"],
                "before_anchor": edit["anchor"] if edit["placement"] == "before" else None,
                "after_anchor": edit["anchor"] if edit["placement"] == "after" else None,
                "anchor_original_offset": anchor_index,
                "byte_offset": written,
                "inserted_sha256": sha256_bytes(edit["text"].encode("utf-8")),
                "inserted_len": len(edit["text"].encode("utf-8")),
                "text": edit["text"],
            }
        )
        pieces.append(edit["text"])
        written += len(edit["text"].encode("utf-8"))
        cursor = point
    pieces.append(base_text[cursor:])
    return "".join(pieces), insertions


def _run(command, cwd, label):
    result = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PatchError(
            "D2A_PATCH_COMMAND", f"{label} failed ({result.returncode}): {result.stdout[-4000:]}"
        )
    return result.stdout


def _git(root, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PatchError("D2A_PATCH_GIT", f"git {' '.join(args)}: {result.stdout.strip()}")
    return result.stdout.rstrip("\n")


def check_pristine_base(root: str) -> str:
    head = _git(root, "rev-parse", "HEAD")
    if head != BASE_SHA:
        raise PatchError("D2A_PATCH_BASE", f"{root} HEAD is {head}, expected {BASE_SHA}")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise PatchError(
            "D2A_PATCH_DIRTY", f"{root} tracked/untracked changes present: {status}"
        )
    return head


def check_derivative_absent(root: str) -> None:
    probe_path = os.path.join(root, D2A_PROBE)
    if os.path.exists(probe_path):
        raise PatchError("D2A_PATCH_EXISTS", f"{D2A_PROBE} already exists")
    cargo = os.path.join(root, CORE_CARGO)
    text = open(cargo, "rb").read().decode("utf-8")
    if FEATURE in text:
        raise PatchError("D2A_PATCH_EXISTS", f"feature {FEATURE!r} already present")
    mod_text = open(os.path.join(root, SEARCH_MOD), "rb").read().decode("utf-8")
    if "pub mod d2a_probe;" in mod_text or "d2a_probe" in mod_text:
        raise PatchError("D2A_PATCH_EXISTS", "d2a_probe module already declared")
    adapter_text = open(os.path.join(root, ADAPTER), "rb").read().decode("utf-8")
    if "query_probe" in adapter_text:
        raise PatchError("D2A_PATCH_EXISTS", "query_probe arm already present")


def diff_insertions(base_text: str, derivative_text: str, path: str) -> list[dict]:
    """Return inserted fragments; require the only difference to be insertions."""
    import difflib

    base_lines = base_text.splitlines(keepends=True)
    derivative_lines = derivative_text.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=base_lines, b=derivative_lines, autojunk=False)
    insertions = []
    reconstructed = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            reconstructed.extend(derivative_lines[j1:j2])
        elif tag == "insert":
            offset = sum(len(line) for line in derivative_lines[:j1])
            inserted = "".join(derivative_lines[j1:j2])
            insertions.append({"byte_offset": offset, "text": inserted})
        else:
            raise PatchError(
                "D2A_REVERSE_EDIT",
                f"{path}: non-insertion diff opcode {tag} at base {i1}:{i2}",
            )
    if "".join(reconstructed) != base_text:
        raise PatchError("D2A_REVERSE_EDIT", f"{path}: reversing insertions did not restore BASE")
    return insertions


def rustfmt(root: str, relative: str) -> None:
    path = os.path.join(root, relative)
    _run(["rustfmt", "--edition", "2024", path], root, f"rustfmt {relative}")
    _run(["rustfmt", "--edition", "2024", "--check", path], root, f"rustfmt --check {relative}")


def materialize(root: str, derivation_path: str | None = None) -> dict:
    """Apply the approved derivative to ``root`` and record the derivation proof."""
    check_pristine_base(root)
    check_derivative_absent(root)

    base_texts = {}
    for relative in (UNIFIED, EXECUTE, SEARCH_MOD, CORE_CARGO, ADAPTER):
        base_texts[relative] = open(os.path.join(root, relative), "rb").read().decode("utf-8")

    # Pre-compute every derivative in memory before writing anything.
    derivatives = {}
    pre_insertions = {}
    for relative in (UNIFIED, EXECUTE, SEARCH_MOD, CORE_CARGO, ADAPTER):
        derivatives[relative], pre_insertions[relative] = apply_edits(
            base_texts[relative], relative
        )

    for relative in (UNIFIED, EXECUTE, SEARCH_MOD, CORE_CARGO, ADAPTER):
        with open(os.path.join(root, relative), "wb") as handle:
            handle.write(derivatives[relative].encode("utf-8"))
    with open(os.path.join(root, D2A_PROBE), "wb") as handle:
        handle.write(D2A_PROBE_RS.encode("utf-8"))

    for relative in (UNIFIED, EXECUTE, SEARCH_MOD, D2A_PROBE, ADAPTER):
        rustfmt(root, relative)

    files = []
    for relative in DERIVATIVE_FILES:
        path = os.path.join(root, relative)
        derivative_bytes = open(path, "rb").read()
        base_sha = (
            sha256_bytes(base_texts[relative].encode("utf-8"))
            if relative in base_texts
            else "ABSENT"
        )
        if relative == D2A_PROBE:
            formatted = D2A_PROBE_RS
            # rustfmt may reformat the new module; require only formatting-equivalent
            # content by checking the token stream is unchanged is not attempted here.
            # The independent proof repeats the same rustfmt invocation.
            insertions = [{"byte_offset": 0, "text": derivative_bytes.decode("utf-8")}]
        else:
            base_text = base_texts[relative]
            insertions = diff_insertions(
                base_text, derivative_bytes.decode("utf-8"), relative
            )
        files.append(
            {
                "path": relative,
                "base_sha256": base_sha,
                "derivative_sha256": sha256_bytes(derivative_bytes),
                "insertions": [
                    {
                        "byte_offset": entry["byte_offset"],
                        "sha256": sha256_bytes(entry["text"].encode("utf-8")),
                        "len": len(entry["text"].encode("utf-8")),
                    }
                    for entry in insertions
                ],
            }
        )

    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    changed = set()
    for line in status.splitlines():
        if not line.strip():
            continue
        changed.add(line[3:].strip())
    changed = {path.replace(os.sep, "/") for path in changed}
    expected = set(DERIVATIVE_FILES)
    if changed != expected:
        raise PatchError(
            "D2A_PATCH_EXTRA",
            f"scratch tree changed unexpected paths: {sorted(changed ^ expected)}",
        )

    _git(root, "add", "-N", D2A_PROBE)
    binary_diff = subprocess.run(
        ["git", "diff", "--binary", BASE_SHA],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    _git(root, "reset", "--", D2A_PROBE)
    if binary_diff.returncode != 0:
        raise PatchError("D2A_PATCH_GIT", "git diff --binary BASE failed")

    fingerprint = sha256_bytes(
        canonical_json_bytes(
            {
                relative: sha256_bytes(open(os.path.join(root, relative), "rb").read())
                for relative in DERIVATIVE_FILES
            }
        )
    )
    rustfmt_version = _run(["rustfmt", "--version"], root, "rustfmt --version").strip()
    derivation = {
        "schema": "pr15i-d2a-source-derivation-v1",
        "base_sha": BASE_SHA,
        "feature": FEATURE,
        "feature_default": False,
        "profile": "release",
        "rustfmt": rustfmt_version,
        "files": files,
        "derivative_fingerprint_sha256": fingerprint,
        "git_diff_binary_sha256": sha256_bytes(binary_diff.stdout),
        "stage_labels": [
            "plan_ns",
            "reader_live_ns",
            "expand_ns",
            "stats_ns",
            "evaluate_ns",
            "candidate_ns",
            "projection_ns",
            "leaf_decode_ns",
            "membership_ns",
            "score_vector_ns",
        ],
        "counter_labels": ["matched_docs", "scored_docs", "candidate_docs"],
    }
    if derivation_path:
        directory = os.path.dirname(os.path.abspath(derivation_path))
        os.makedirs(directory, exist_ok=True)
        temporary = derivation_path + ".tmp"
        with open(temporary, "wb") as handle:
            handle.write(canonical_json_bytes(derivation) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, derivation_path)
    return derivation


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize the PR 15I-D2-A diagnostic source derivative."
    )
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--derivation-out", required=True)
    args = parser.parse_args(argv)
    try:
        derivation = materialize(
            os.path.abspath(args.checkout_root), os.path.abspath(args.derivation_out)
        )
    except PatchError as error:
        print(f"PATCH REJECTED: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "derivative_fingerprint_sha256": derivation["derivative_fingerprint_sha256"],
                "files": [entry["path"] for entry in derivation["files"]],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
