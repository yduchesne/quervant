#!/usr/bin/env python3
"""Independent reverse proof for the PR 15I-D2-A diagnostic source derivative.

This module deliberately does **not** import the materializer.  It carries its own
copy of the closed, insertion-only edit inventory, rebuilds the expected
derivative from `BASE` (including the same deterministic `rustfmt` pass), and
proves that the actual scratch tree is byte-identical to that expectation.  It
then removes exactly the inserted bytes and requires the original `BASE` bytes
back.  A single unexpected byte, extra production file, default-feature change or
unapproved `#[inline]`/`pub` addition is a hard rejection.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

BASE_SHA = "9429dce99827f25766a92c1fbded8f78a0b168f1"
FEATURE = "pr15id2a-probe"

UNIFIED = "crates/quervant-core/src/search/unified.rs"
EXECUTE = "crates/quervant-core/src/search/execute.rs"
SEARCH_MOD = "crates/quervant-core/src/search/mod.rs"
D2A_PROBE = "crates/quervant-core/src/search/d2a_probe.rs"
CORE_CARGO = "crates/quervant-core/Cargo.toml"
ADAPTER = "benchmarks/pr15d/adapters/quervant/src/main.rs"

DERIVATIVE_FILES = (UNIFIED, EXECUTE, SEARCH_MOD, D2A_PROBE, CORE_CARGO, ADAPTER)
EXISTING_FILES = (UNIFIED, EXECUTE, SEARCH_MOD, CORE_CARGO, ADAPTER)
RUST_FILES = (UNIFIED, EXECUTE, SEARCH_MOD, D2A_PROBE, ADAPTER)

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

# Independent copy of the approved literal insertions (see the plan §5.3-§5.5).
APPROVED_EDITS = [
    {
        "file": CORE_CARGO,
        "region": None,
        "anchor": "[features]\n",
        "placement": "after",
        "text": "pr15id2a-probe = []\n",
        "label": "FEATURE",
    },
    {
        "file": SEARCH_MOD,
        "region": None,
        "anchor": "#[cfg(test)]\nmod diagnostics;\n",
        "placement": "after",
        "text": '#[cfg(feature = "pr15id2a-probe")]\npub mod d2a_probe;\n',
        "label": "MODULE",
    },
    {
        "file": UNIFIED,
        "region": None,
        "anchor": "use super::error::{SearchError, SearchResult};\n",
        "placement": "before",
        "text": "use super::d2a_probe;\n",
        "label": "IMPORT",
    },
    {
        "file": EXECUTE,
        "region": None,
        "anchor": "use super::error::{SearchError, SearchResult};\n",
        "placement": "before",
        "text": "use super::d2a_probe;\n",
        "label": "IMPORT",
    },
    {
        "file": UNIFIED,
        "region": "execute_unified",
        "anchor": "let bindings =",
        "placement": "before",
        "text": "let _d0_plan = d2a_probe::span(d2a_probe::PLAN);\n        ",
        "label": "PLAN_START",
    },
    {
        "file": UNIFIED,
        "region": "execute_unified",
        "anchor": "let (page, total_hits, next_cursor, aggregation_result) = self.collect_mixed(",
        "placement": "before",
        "text": "drop(_d0_plan);\n        ",
        "label": "PLAN_END",
    },
    {
        "file": UNIFIED,
        "region": "execute_unified",
        "anchor": "let fields = project_selected_hits(",
        "placement": "before",
        "text": "let _d0_projection = d2a_probe::span(d2a_probe::PROJECTION);\n        ",
        "label": "PROJECTION_START",
    },
    {
        "file": UNIFIED,
        "region": "execute_unified",
        "anchor": "let retained = if retain {",
        "placement": "before",
        "text": "drop(_d0_projection);\n        ",
        "label": "PROJECTION_END",
    },
    {
        "file": UNIFIED,
        "region": "collect_mixed",
        "anchor": "let mut guards = Vec::new();",
        "placement": "before",
        "text": "let _d0_reader = d2a_probe::span(d2a_probe::READER_LIVE);\n        ",
        "label": "READER_LIVE_START",
    },
    {
        "file": UNIFIED,
        "region": "collect_mixed",
        "anchor": "let synth = plan::synthetic_query(plan);",
        "placement": "before",
        "text": "drop(_d0_reader);\n        ",
        "label": "READER_LIVE_END",
    },
    {
        "file": UNIFIED,
        "region": "collect_mixed",
        "anchor": "let expansion = {",
        "placement": "before",
        "text": "let _d0_expand = d2a_probe::span(d2a_probe::EXPAND);\n        ",
        "label": "EXPAND_START",
    },
    {
        "file": UNIFIED,
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
        "region": "collect_mixed",
        "anchor": "let mut budget = CandidateBudget::new(",
        "placement": "before",
        "text": "drop(_d0_stats);\n        ",
        "label": "STATS_END",
    },
    {
        "file": UNIFIED,
        "region": "collect_mixed",
        "anchor": "let scored = execute::evaluate_lexical_with(",
        "placement": "before",
        "text": "let _d0_evaluate = d2a_probe::span(d2a_probe::EVALUATE);\n            ",
        "label": "EVALUATE_START",
    },
    {
        "file": UNIFIED,
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
        "region": "collect_mixed",
        "anchor": "// Drop the geo allocations first; their batch reservations",
        "placement": "before",
        "text": "drop(_d0_candidate);\n            ",
        "label": "CANDIDATE_END",
    },
    {
        "file": EXECUTE,
        "region": "evaluate_lexical_with",
        "anchor": "let (leaf_data, leaf_charges) = {",
        "placement": "before",
        "text": "let _d0_leaf = d2a_probe::span(d2a_probe::LEAF_DECODE);\n    ",
        "label": "LEAF_DECODE_START",
    },
    {
        "file": EXECUTE,
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
        "region": "evaluate_lexical_with",
        "anchor": "let matched_entries = matched.len() as u64;",
        "placement": "before",
        "text": "drop(_d0_membership);\n    ",
        "label": "MEMBERSHIP_END",
    },
    {
        "file": EXECUTE,
        "region": "evaluate_lexical_with",
        "anchor": "let matched_entries = matched.len() as u64;",
        "placement": "after",
        "text": "\n    d2a_probe::count(d2a_probe::MATCHED_COUNT, matched_entries);",
        "label": "MATCHED_COUNT",
    },
    {
        "file": EXECUTE,
        "region": "evaluate_lexical_with",
        "anchor": "let (scored, scored_charges) = score_segment(",
        "placement": "before",
        "text": "let _d0_score = d2a_probe::span(d2a_probe::SCORE_VECTOR);\n    ",
        "label": "SCORE_VECTOR_START",
    },
    {
        "file": EXECUTE,
        "region": "evaluate_lexical_with",
        "anchor": "// Segment-owned temporaries are released here;",
        "placement": "before",
        "text": "drop(_d0_score);\n    ",
        "label": "SCORE_VECTOR_END",
    },
    {
        "file": EXECUTE,
        "region": "evaluate_lexical_with",
        "anchor": "let scored_vec: Vec<(u64, f64)> = scored.into_iter().collect();",
        "placement": "after",
        "text": (
            "\n    d2a_probe::count(d2a_probe::SCORED_COUNT,\n"
            '        u64::try_from(scored_vec.len()).expect("diagnostic score count overflow"));'
        ),
        "label": "SCORED_COUNT",
    },
    {
        "file": ADAPTER,
        "region": None,
        "anchor": "use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};\n",
        "placement": "before",
        "text": "use quervant_core::search::d2a_probe;\n",
        "label": "IMPORT",
    },
    {
        "file": ADAPTER,
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
    {
        "file": EXECUTE,
        "region": "score_segment",
        "anchor": "let entries = matches.len() as u64;",
        "placement": "before",
        "text": "let _d2a_score_map = d2a_probe::span(d2a_probe::SCORE_MAP);\n    ",
        "label": "SCORE_MAP_START",
    },
    {
        "file": EXECUTE,
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
        "region": "score_segment",
        "anchor": "let mut owner: BTreeMap<(u32, &str), usize> = BTreeMap::new();",
        "placement": "before",
        "text": "let _d2a_score_owner = d2a_probe::span(d2a_probe::SCORE_OWNER);\n    ",
        "label": "SCORE_OWNER_START",
    },
    {
        "file": EXECUTE,
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
        "region": "score_segment",
        "anchor": "    Ok((scores, charges))\n}",
        "placement": "before",
        "text": "    drop(_d2a_score_accumulate);\n",
        "label": "SCORE_ACCUMULATE_END",
    },
]


class ProofError(Exception):
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


def _region(text: str, delimiters, path: str) -> tuple[int, int]:
    start_delim, stop_delim = delimiters
    if text.count(start_delim) != 1 or text.count(stop_delim) != 1:
        raise ProofError("D2A_PROOF_ANCHOR", f"{path}: region delimiters are not unique")
    start = text.index(start_delim)
    stop = text.index(stop_delim)
    if stop <= start:
        raise ProofError("D2A_PROOF_ANCHOR", f"{path}: empty region")
    return start, stop


def _apply(base_text: str, file: str) -> str:
    edits = [edit for edit in APPROVED_EDITS if edit["file"] == file]
    points = []
    for sequence, edit in enumerate(edits):
        if edit["region"] is None:
            start, stop = 0, len(base_text)
        else:
            start, stop = _region(base_text, REGIONS[(file, edit["region"])], file)
        region = base_text[start:stop]
        if region.count(edit["anchor"]) != 1:
            raise ProofError(
                "D2A_PROOF_ANCHOR",
                f"{file}:{edit['label']}: anchor occurrence is not exactly one",
            )
        index = start + region.index(edit["anchor"])
        point = index if edit["placement"] == "before" else index + len(edit["anchor"])
        points.append((point, sequence, edit["text"]))
    points.sort(key=lambda item: (item[0], item[1]))
    pieces = []
    cursor = 0
    for point, _sequence, text in points:
        if point < cursor:
            raise ProofError("D2A_PROOF_ANCHOR", f"{file}: overlapping application")
        pieces.append(base_text[cursor:point])
        pieces.append(text)
        cursor = point
    pieces.append(base_text[cursor:])
    return "".join(pieces)


def build_expected(base_texts: dict[str, str]) -> dict[str, bytes]:
    """Independently rebuild the expected derivative, including rustfmt."""
    expected = {}
    for relative in EXISTING_FILES:
        if relative not in base_texts:
            raise ProofError("D2A_PROOF_INPUT", f"missing BASE text for {relative}")
    temporary = tempfile.mkdtemp(prefix="pr15id0-proof-")
    try:
        for relative in EXISTING_FILES:
            path = os.path.join(temporary, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(_apply(base_texts[relative], relative).encode("utf-8"))
        probe_path = os.path.join(temporary, D2A_PROBE)
        os.makedirs(os.path.dirname(probe_path), exist_ok=True)
        with open(probe_path, "wb") as handle:
            handle.write(D2A_PROBE_RS.encode("utf-8"))
        for relative in RUST_FILES:
            _rustfmt(os.path.join(temporary, relative), relative)
        for relative in DERIVATIVE_FILES:
            with open(os.path.join(temporary, relative), "rb") as handle:
                expected[relative] = handle.read()
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return expected


def _rustfmt(path: str, relative: str) -> None:
    first = subprocess.run(
        ["rustfmt", "--edition", "2024", "--config", "skip_children=true", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if first.returncode != 0:
        raise ProofError("D2A_PROOF_RUSTFMT", f"{relative}: {first.stdout[-2000:]}")
    second = subprocess.run(
        ["rustfmt", "--edition", "2024", "--config", "skip_children=true", "--check", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if second.returncode != 0:
        raise ProofError("D2A_PROOF_RUSTFMT", f"{relative} is not rustfmt-idempotent")


def reverse_insertions(base_text: str, derivative_text: str, path: str) -> list[dict]:
    """Remove only inserted bytes; reject replace/delete and prove BASE identity."""
    base_lines = base_text.splitlines(keepends=True)
    derivative_lines = derivative_text.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=base_lines, b=derivative_lines, autojunk=False)
    insertions = []
    reconstructed = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            reconstructed.extend(derivative_lines[j1:j2])
        elif tag == "insert":
            inserted = "".join(derivative_lines[j1:j2])
            insertions.append(
                {
                    "path": path,
                    "byte_offset": sum(len(line) for line in derivative_lines[:j1]),
                    "text": inserted,
                }
            )
        else:
            raise ProofError(
                "D2A_PROOF_EXTRA",
                f"{path}: diff opcode {tag} at base lines {i1}:{i2} is not an insertion",
            )
    if "".join(reconstructed) != base_text:
        raise ProofError("D2A_PROOF_REVERSE", f"{path}: reverse edit did not restore BASE")
    return insertions


def verify_derivative(base_texts: dict[str, str], actual: dict[str, bytes]) -> dict:
    expected = build_expected(base_texts)
    for relative in DERIVATIVE_FILES:
        if actual.get(relative) != expected[relative]:
            raise ProofError(
                "D2A_PROOF_EXTRA",
                f"{relative}: scratch bytes differ from the approved insertion-only derivative",
            )

    insertions = []
    for relative in EXISTING_FILES:
        insertions.extend(
            reverse_insertions(
                base_texts[relative], actual[relative].decode("utf-8"), relative
            )
        )
    if actual[D2A_PROBE] != expected[D2A_PROBE]:
        raise ProofError("D2A_PROOF_EXTRA", "diagnostic recorder module bytes differ")

    cargo = actual[CORE_CARGO].decode("utf-8")
    if cargo.count(f"{FEATURE} = []") != 1:
        raise ProofError("D2A_PROOF_FEATURE", "diagnostic feature is not declared exactly once")
    if 'default = ["stored-lz4"]' not in cargo:
        raise ProofError("D2A_PROOF_FEATURE", "default feature set changed")
    if f"{FEATURE} = []" in base_texts[CORE_CARGO]:
        raise ProofError("D2A_PROOF_FEATURE", "diagnostic feature existed in BASE")

    search_mod = actual[SEARCH_MOD].decode("utf-8")
    if search_mod.count('pub mod d2a_probe;') != 1:
        raise ProofError("D2A_PROOF_MODULE", "d2a_probe module declaration is not exactly one")
    if '#[cfg(feature = "pr15id2a-probe")]\npub mod d2a_probe;' not in search_mod:
        raise ProofError("D2A_PROOF_MODULE", "d2a_probe module is not feature-gated")
    if '#[cfg(test)]\nmod diagnostics;' not in search_mod:
        raise ProofError("D2A_PROOF_MODULE", "existing diagnostics cfg changed")

    for relative in EXISTING_FILES:
        base_text = base_texts[relative]
        actual_text = actual[relative].decode("utf-8")
        if actual_text.count("#[inline") != base_text.count("#[inline"):
            raise ProofError("D2A_PROOF_INLINE", f"{relative}: added an #[inline] attribute")
        for line in actual_text.splitlines():
            if line.startswith("pub ") and line not in base_text.splitlines():
                if line != "pub mod d2a_probe;":
                    raise ProofError(
                        "D2A_PROOF_PUBLIC_API", f"{relative}: unexpected public item {line!r}"
                    )
    if actual[ADAPTER].decode("utf-8").count('"query_probe" =>') != 1:
        raise ProofError("D2A_PROOF_ADAPTER", "query_probe arm is not exactly one")
    for relative in (UNIFIED, EXECUTE, SEARCH_MOD, CORE_CARGO):
        if "query_probe" in actual[relative].decode("utf-8"):
            raise ProofError("D2A_PROOF_ADAPTER", f"{relative}: query_probe leaked outside adapter")

    fingerprint = sha256_bytes(
        canonical_json_bytes(
            {relative: sha256_bytes(actual[relative]) for relative in DERIVATIVE_FILES}
        )
    )
    return {
        "status": "VERIFIED",
        "derivative_fingerprint_sha256": fingerprint,
        "insertions": insertions,
        "checks": {
            "byte_identical_to_independent_derivative": True,
            "reverse_edit_restores_base": True,
            "only_six_derivative_paths": True,
            "feature_non_default": True,
            "module_feature_gated": True,
            "no_added_inline_attributes": True,
            "no_added_public_items": True,
            "query_probe_adapter_only": True,
        },
    }


def _git(root: str, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ProofError("D2A_PROOF_GIT", f"git {' '.join(args)}: {result.stdout.strip()}")
    return result.stdout.rstrip("\n")


def verify_changed_paths(changed) -> None:
    expected = set(DERIVATIVE_FILES)
    normalized = {path.replace(os.sep, "/") for path in changed}
    if normalized != expected:
        raise ProofError(
            "D2A_PROOF_EXTRA",
            f"scratch tree changed unexpected paths: {sorted(normalized ^ expected)}",
        )


def prove(checkout_root: str, instrumented_root: str) -> dict:
    checkout_root = os.path.abspath(checkout_root)
    instrumented_root = os.path.abspath(instrumented_root)

    head = _git(checkout_root, "rev-parse", "HEAD")
    if head != BASE_SHA:
        raise ProofError("D2A_PROOF_BASE", f"checkout HEAD is {head}, expected {BASE_SHA}")
    if _git(checkout_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ProofError("D2A_PROOF_DIRTY", "canonical checkout is not clean")

    scratch_head = _git(instrumented_root, "rev-parse", "HEAD")
    if scratch_head != BASE_SHA:
        raise ProofError(
            "D2A_PROOF_BASE", f"scratch HEAD is {scratch_head}, expected {BASE_SHA}"
        )

    base_texts = {
        relative: open(os.path.join(checkout_root, relative), "rb").read().decode("utf-8")
        for relative in EXISTING_FILES
    }
    actual = {
        relative: open(os.path.join(instrumented_root, relative), "rb").read()
        for relative in DERIVATIVE_FILES
    }

    status = _git(instrumented_root, "status", "--porcelain=v1", "--untracked-files=all")
    changed = set()
    for line in status.splitlines():
        if not line.strip():
            continue
        changed.add(line[3:].strip().replace(os.sep, "/"))
    verify_changed_paths(changed)

    proof = verify_derivative(base_texts, actual)
    proof["base_sha"] = BASE_SHA
    proof["checkout_root"] = checkout_root
    proof["instrumented_root"] = instrumented_root
    proof["base_source_sha256"] = {
        relative: sha256_bytes(base_texts[relative].encode("utf-8"))
        for relative in EXISTING_FILES
    }
    proof["derivative_sha256"] = {
        relative: sha256_bytes(actual[relative]) for relative in DERIVATIVE_FILES
    }
    return proof


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Independently prove the D2A derivative.")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--instrumented-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        proof = prove(os.path.abspath(args.checkout_root), os.path.abspath(args.instrumented_root))
    except ProofError as error:
        print(f"SOURCE PROOF FAILED: {error}", file=sys.stderr)
        return 2
    directory = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(directory, exist_ok=True)
    temporary = args.out + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(canonical_json_bytes(proof) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, args.out)
    print(
        json.dumps(
            {
                "status": proof["status"],
                "derivative_fingerprint_sha256": proof["derivative_fingerprint_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
