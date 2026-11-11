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

BASE_SHA = "409fb0fdf370bb4d4dade5ea507c6fa4518b5220"
FEATURE = "pr15id3a-probe"

UNIFIED = "crates/quervant-core/src/search/unified.rs"
EXECUTE = "crates/quervant-core/src/search/execute.rs"
SEARCH_MOD = "crates/quervant-core/src/search/mod.rs"
D3A_PROBE = "crates/quervant-core/src/search/d3a_probe.rs"
CORE_CARGO = "crates/quervant-core/Cargo.toml"
ADAPTER = "benchmarks/pr15d/adapters/quervant/src/main.rs"

DERIVATIVE_FILES = (UNIFIED, EXECUTE, SEARCH_MOD, D3A_PROBE, CORE_CARGO, ADAPTER)

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
    (UNIFIED, "keyword_helpers"): (
        "/// PR 15H-B: conservative charge for a borrowed single-keyword sort candidate.",
        "\n/// One bounded top-K entry.",
    ),
    (EXECUTE, "score_segment"): (
        "fn score_segment(\n",
        "\n/// Test-only observation of membership callbacks.",
    ),
}

D3A_PROBE_RS = '''//! Diagnostic-only, thread-local recorder; never committed to Quervant.
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
pub const MATCHED_RESERVE: usize = 13;
pub const SCORED_VEC_BUILD: usize = 14;
pub const TEMP_RELEASE: usize = 15;
pub const MATCH_INSERT_SAMPLE: usize = 16;
pub const CANDIDATE_SAMPLE: usize = 17;
pub const CANDIDATE_KEY: usize = 18;
pub const CANDIDATE_SORT_VIEW: usize = 19;
pub const CANDIDATE_SORT_CHARGE: usize = 20;
pub const CANDIDATE_DUPLICATE: usize = 21;
pub const CANDIDATE_COMPARE: usize = 22;
pub const CANDIDATE_MATERIALIZE: usize = 23;
pub const CANDIDATE_HEAP: usize = 24;

pub const MATCHED_DOCS: usize = 0;
pub const SCORED_DOCS: usize = 1;
pub const CANDIDATE_DOCS: usize = 2;
pub const BM25_CALLS: usize = 3;
pub const SCORING_MAP_ENTRIES: usize = 4;
pub const POSITIVE_TERM_OWNERS: usize = 5;
pub const CANDIDATE_SAMPLES_FIRST: usize = 6;
pub const CANDIDATE_SAMPLES_STEADY: usize = 7;
pub const CANDIDATE_SAMPLES_FAST: usize = 8;
pub const CANDIDATE_SAMPLES_FALLBACK: usize = 9;
pub const CANDIDATE_SAMPLES_INSERT: usize = 10;
pub const CANDIDATE_SAMPLES_REPLACE: usize = 11;
pub const CANDIDATE_SAMPLES_REJECT: usize = 12;
pub const MATCH_INSERT_SAMPLES: usize = 13;
pub const CANDIDATE_SAMPLES_KEY: usize = 14;

pub const NAMES: [&str; 25] = [
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
    "score_map_ns",
    "score_owner_ns",
    "score_accumulate_ns",
    "matched_reserve_ns",
    "scored_vec_build_ns",
    "temp_release_ns",
    "match_insert_sample_ns",
    "candidate_sample_ns",
    "candidate_key_ns",
    "candidate_sort_view_ns",
    "candidate_sort_charge_ns",
    "candidate_duplicate_ns",
    "candidate_compare_ns",
    "candidate_materialize_ns",
    "candidate_heap_ns",
];
pub const COUNT_NAMES: [&str; 15] = [
    "matched_docs",
    "scored_docs",
    "candidate_docs",
    "bm25_calls",
    "scoring_map_entries",
    "positive_term_owners",
    "candidate_samples_first",
    "candidate_samples_steady",
    "candidate_samples_fast",
    "candidate_samples_fallback",
    "candidate_samples_insert",
    "candidate_samples_replace",
    "candidate_samples_reject",
    "match_insert_samples",
    "candidate_samples_key",
];

const MAX_SEGMENTS: usize = 32;
const STRATA: usize = 2;
const CHILDREN: usize = 8;
const FIRST: usize = 0;
const STEADY: usize = 1;
const SAMPLE_THRESHOLD: usize = 512;
const FIRST_SAMPLES: usize = 128;
const STEADY_STRIDE: usize = 64;
const MATCH_INSERT_THRESHOLD: usize = 128;

#[derive(Clone, Copy)]
struct SegmentDescriptor {
    scored_len: u64,
    first_samples: u64,
    steady_samples: u64,
    match_insert_samples: u64,
}
const ZERO_DESCRIPTOR: SegmentDescriptor = SegmentDescriptor {
    scored_len: 0,
    first_samples: 0,
    steady_samples: 0,
    match_insert_samples: 0,
};

thread_local! {
    static ACTIVE: Cell<bool> = const { Cell::new(false) };
    static SAMPLE_ACTIVE: Cell<bool> = const { Cell::new(false) };
    static SAMPLE_STRATUM: Cell<usize> = const { Cell::new(0) };
    static STAGES: RefCell<[u64; 25]> = const { RefCell::new([0; 25]) };
    static COUNTS: RefCell<[u64; 15]> = const { RefCell::new([0; 15]) };
    static SEGMENTS: RefCell<[SegmentDescriptor; MAX_SEGMENTS]> =
        const { RefCell::new([ZERO_DESCRIPTOR; MAX_SEGMENTS]) };
    static SEGMENT_LEN: Cell<usize> = const { Cell::new(0) };
    static SEGMENT_OVERFLOW: Cell<bool> = const { Cell::new(false) };
    static PENDING_MATCH_INSERTS: Cell<u64> = const { Cell::new(0) };
    static STRATA_NS: RefCell<[[u64; CHILDREN]; STRATA]> =
        const { RefCell::new([[0; CHILDREN]; STRATA]) };
    static STRATA_COUNT: RefCell<[u64; STRATA]> = const { RefCell::new([0; STRATA]) };
}

fn strata_child(id: usize) -> Option<usize> {
    match id {
        CANDIDATE_SAMPLE => Some(0),
        CANDIDATE_KEY => Some(1),
        CANDIDATE_SORT_VIEW => Some(2),
        CANDIDATE_SORT_CHARGE => Some(3),
        CANDIDATE_DUPLICATE => Some(4),
        CANDIDATE_COMPARE => Some(5),
        CANDIDATE_MATERIALIZE => Some(6),
        CANDIDATE_HEAP => Some(7),
        _ => None,
    }
}

fn add_stage(id: usize, elapsed: u64, stratum: Option<usize>) {
    STAGES.with(|x| {
        let mut data = x.borrow_mut();
        data[id] = data[id]
            .checked_add(elapsed)
            .expect("diagnostic stage accumulator overflow");
    });
    if let (Some(stratum), Some(child)) = (stratum, strata_child(id)) {
        STRATA_NS.with(|x| {
            let mut data = x.borrow_mut();
            data[stratum][child] = data[stratum][child]
                .checked_add(elapsed)
                .expect("diagnostic stratum accumulator overflow");
        });
    }
}

fn add_count(id: usize, value: u64) {
    COUNTS.with(|x| {
        let mut data = x.borrow_mut();
        data[id] = data[id]
            .checked_add(value)
            .expect("diagnostic count overflow");
    });
}

pub fn reset() {
    STAGES.with(|x| *x.borrow_mut() = [0; 25]);
    COUNTS.with(|x| *x.borrow_mut() = [0; 15]);
    SEGMENTS.with(|x| *x.borrow_mut() = [ZERO_DESCRIPTOR; MAX_SEGMENTS]);
    SEGMENT_LEN.with(|x| x.set(0));
    SEGMENT_OVERFLOW.with(|x| x.set(false));
    PENDING_MATCH_INSERTS.with(|x| x.set(0));
    STRATA_NS.with(|x| *x.borrow_mut() = [[0; CHILDREN]; STRATA]);
    STRATA_COUNT.with(|x| *x.borrow_mut() = [0; STRATA]);
    SAMPLE_ACTIVE.with(|x| x.set(false));
    SAMPLE_STRATUM.with(|x| x.set(0));
    ACTIVE.with(|x| x.set(true));
}

pub struct Span {
    id: usize,
    start: Option<Instant>,
}

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
            add_stage(self.id, elapsed, None);
        }
    }
}

pub struct MicroSpan {
    id: usize,
    start: Option<Instant>,
}

pub fn micro_span(id: usize) -> MicroSpan {
    assert!(id < NAMES.len(), "invalid diagnostic timer");
    let active = ACTIVE.with(Cell::get) && SAMPLE_ACTIVE.with(Cell::get);
    MicroSpan {
        id,
        start: active.then(Instant::now),
    }
}

impl Drop for MicroSpan {
    fn drop(&mut self) {
        if let Some(start) = self.start {
            let elapsed = u64::try_from(start.elapsed().as_nanos())
                .expect("diagnostic timer overflow");
            let stratum = SAMPLE_STRATUM.with(Cell::get);
            add_stage(self.id, elapsed, Some(stratum));
        }
    }
}

pub fn count(id: usize, value: u64) {
    assert!(id < COUNT_NAMES.len(), "invalid diagnostic counter");
    if ACTIVE.with(Cell::get) {
        add_count(id, value);
    }
}

pub fn sample_count(id: usize) {
    assert!(id < COUNT_NAMES.len(), "invalid diagnostic counter");
    if ACTIVE.with(Cell::get) && SAMPLE_ACTIVE.with(Cell::get) {
        add_count(id, 1);
    }
}

pub fn begin_segment() {
    if ACTIVE.with(Cell::get) {
        PENDING_MATCH_INSERTS.with(|x| x.set(0));
    }
}

pub fn register_segment(scored_len: usize) {
    if !ACTIVE.with(Cell::get) {
        return;
    }
    let pending = PENDING_MATCH_INSERTS.with(|x| x.replace(0));
    let length = SEGMENT_LEN.with(Cell::get);
    if length >= MAX_SEGMENTS {
        SEGMENT_OVERFLOW.with(|x| x.set(true));
        return;
    }
    SEGMENTS.with(|x| {
        let mut data = x.borrow_mut();
        data[length] = SegmentDescriptor {
            scored_len: u64::try_from(scored_len).expect("diagnostic segment length overflow"),
            first_samples: 0,
            steady_samples: 0,
            match_insert_samples: pending,
        };
    });
    SEGMENT_LEN.with(|x| x.set(length + 1));
}

pub struct MatchInsertSample {
    start: Option<Instant>,
}

pub fn match_insert_sample(pre_insert_len: usize) -> MatchInsertSample {
    if !ACTIVE.with(Cell::get) {
        return MatchInsertSample { start: None };
    }
    if pre_insert_len < MATCH_INSERT_THRESHOLD
        || (pre_insert_len - MATCH_INSERT_THRESHOLD) % STEADY_STRIDE != 0
    {
        return MatchInsertSample { start: None };
    }
    add_count(MATCH_INSERT_SAMPLES, 1);
    PENDING_MATCH_INSERTS.with(|x| {
        x.set(x.get().checked_add(1).expect("diagnostic insert sample overflow"))
    });
    MatchInsertSample {
        start: Some(Instant::now()),
    }
}

impl Drop for MatchInsertSample {
    fn drop(&mut self) {
        if let Some(start) = self.start {
            let elapsed = u64::try_from(start.elapsed().as_nanos())
                .expect("diagnostic timer overflow");
            add_stage(MATCH_INSERT_SAMPLE, elapsed, None);
        }
    }
}

pub struct CandidateSample {
    stratum: usize,
    start: Option<Instant>,
}

pub fn candidate_sample(n: usize, ordinal: usize) -> CandidateSample {
    if !ACTIVE.with(Cell::get) || n < SAMPLE_THRESHOLD {
        return CandidateSample {
            stratum: FIRST,
            start: None,
        };
    }
    let stratum = if ordinal < FIRST_SAMPLES {
        FIRST
    } else if (ordinal - FIRST_SAMPLES) % STEADY_STRIDE == 0 {
        STEADY
    } else {
        return CandidateSample {
            stratum: FIRST,
            start: None,
        };
    };
    let counter = if stratum == FIRST {
        CANDIDATE_SAMPLES_FIRST
    } else {
        CANDIDATE_SAMPLES_STEADY
    };
    add_count(counter, 1);
    STRATA_COUNT.with(|x| {
        let mut data = x.borrow_mut();
        data[stratum] = data[stratum]
            .checked_add(1)
            .expect("diagnostic stratum count overflow");
    });
    let length = SEGMENT_LEN.with(Cell::get);
    if length > 0 {
        SEGMENTS.with(|x| {
            let mut data = x.borrow_mut();
            let descriptor = &mut data[length - 1];
            if stratum == FIRST {
                descriptor.first_samples = descriptor
                    .first_samples
                    .checked_add(1)
                    .expect("diagnostic segment sample overflow");
            } else {
                descriptor.steady_samples = descriptor
                    .steady_samples
                    .checked_add(1)
                    .expect("diagnostic segment sample overflow");
            }
        });
    }
    SAMPLE_STRATUM.with(|x| x.set(stratum));
    SAMPLE_ACTIVE.with(|x| x.set(true));
    CandidateSample {
        stratum,
        start: Some(Instant::now()),
    }
}

impl Drop for CandidateSample {
    fn drop(&mut self) {
        if let Some(start) = self.start {
            let elapsed = u64::try_from(start.elapsed().as_nanos())
                .expect("diagnostic timer overflow");
            add_stage(CANDIDATE_SAMPLE, elapsed, Some(self.stratum));
            SAMPLE_ACTIVE.with(|x| x.set(false));
        }
    }
}

/// MUST be called after `engine_ns` has already stopped.
pub fn take() -> (
    Vec<(&'static str, u64)>,
    Vec<(&'static str, u64)>,
    Vec<[u64; 4]>,
    [[u64; CHILDREN]; STRATA],
    [u64; STRATA],
    bool,
) {
    ACTIVE.with(|x| x.set(false));
    let stages = STAGES.with(|x| *x.borrow());
    let counts = COUNTS.with(|x| *x.borrow());
    let length = SEGMENT_LEN.with(Cell::get).min(MAX_SEGMENTS);
    let segments = SEGMENTS.with(|x| {
        let data = x.borrow();
        data[..length]
            .iter()
            .map(|descriptor| {
                [
                    descriptor.scored_len,
                    descriptor.first_samples,
                    descriptor.steady_samples,
                    descriptor.match_insert_samples,
                ]
            })
            .collect()
    });
    let strata_ns = STRATA_NS.with(|x| *x.borrow());
    let strata_count = STRATA_COUNT.with(|x| *x.borrow());
    let unsupported = SEGMENT_OVERFLOW.with(Cell::get);
    (
        NAMES.iter().copied().zip(stages).collect(),
        COUNT_NAMES.iter().copied().zip(counts).collect(),
        segments,
        strata_ns,
        strata_count,
        unsupported,
    )
}
'''

EDITS = [
    # --- crates/quervant-core/Cargo.toml -----------------------------------
    {
        "file": CORE_CARGO,
        "function": "features",
        "region": None,
        "anchor": "[features]\n",
        "placement": "after",
        "text": "pr15id3a-probe = []\n",
        "label": "FEATURE",
    },
    # --- crates/quervant-core/src/search/mod.rs ----------------------------
    {
        "file": SEARCH_MOD,
        "function": "module_declarations",
        "region": None,
        "anchor": "#[cfg(test)]\nmod diagnostics;\n",
        "placement": "after",
        "text": '#[cfg(feature = "pr15id3a-probe")]\npub mod d3a_probe;\n',
        "label": "MODULE",
    },
    # --- mechanical compile-path imports ----------------------------------
    {
        "file": UNIFIED,
        "function": "imports",
        "region": None,
        "anchor": "use super::error::{SearchError, SearchResult};\n",
        "placement": "before",
        "text": "use super::d3a_probe;\n",
        "label": "IMPORT",
    },
    {
        "file": EXECUTE,
        "function": "imports",
        "region": None,
        "anchor": "use super::error::{SearchError, SearchResult};\n",
        "placement": "before",
        "text": "use super::d3a_probe;\n",
        "label": "IMPORT",
    },
    # --- crates/quervant-core/src/search/unified.rs : execute_unified ------
    {
        "file": UNIFIED,
        "function": "execute_unified",
        "region": "execute_unified",
        "anchor": "let bindings =",
        "placement": "before",
        "text": "let _d3a_plan = d3a_probe::span(d3a_probe::PLAN);\n        ",
        "label": "PLAN_START",
    },
    {
        "file": UNIFIED,
        "function": "execute_unified",
        "region": "execute_unified",
        "anchor": "let (page, total_hits, next_cursor, aggregation_result) = self.collect_mixed(",
        "placement": "before",
        "text": "drop(_d3a_plan);\n        ",
        "label": "PLAN_END",
    },
    {
        "file": UNIFIED,
        "function": "execute_unified",
        "region": "execute_unified",
        "anchor": "let fields = project_selected_hits(",
        "placement": "before",
        "text": "let _d3a_projection = d3a_probe::span(d3a_probe::PROJECTION);\n        ",
        "label": "PROJECTION_START",
    },
    {
        "file": UNIFIED,
        "function": "execute_unified",
        "region": "execute_unified",
        "anchor": "let retained = if retain {",
        "placement": "before",
        "text": "drop(_d3a_projection);\n        ",
        "label": "PROJECTION_END",
    },
    # --- crates/quervant-core/src/search/unified.rs : collect_mixed --------
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let mut guards = Vec::new();",
        "placement": "before",
        "text": "let _d3a_reader = d3a_probe::span(d3a_probe::READER_LIVE);\n        ",
        "label": "READER_LIVE_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let synth = plan::synthetic_query(plan);",
        "placement": "before",
        "text": "drop(_d3a_reader);\n        ",
        "label": "READER_LIVE_END",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let expansion = {",
        "placement": "before",
        "text": "let _d3a_expand = d3a_probe::span(d3a_probe::EXPAND);\n        ",
        "label": "EXPAND_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let stats = {",
        "placement": "before",
        "text": (
            "drop(_d3a_expand);\n        "
            "let _d3a_stats = d3a_probe::span(d3a_probe::STATS);\n        "
        ),
        "label": "EXPAND_END_STATS_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let mut budget = CandidateBudget::new(",
        "placement": "before",
        "text": "drop(_d3a_stats);\n        ",
        "label": "STATS_END",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let scored = execute::evaluate_lexical_with(",
        "placement": "before",
        "text": "let _d3a_evaluate = d3a_probe::span(d3a_probe::EVALUATE);\n            ",
        "label": "EVALUATE_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "// PR 15E Phase 5:",
        "placement": "before",
        "text": (
            "drop(_d3a_evaluate);\n            "
            "d3a_probe::count(d3a_probe::CANDIDATE_DOCS,\n"
            '                u64::try_from(scored.len()).expect("diagnostic candidate count overflow"));\n'
            "            let _d3a_candidate = d3a_probe::span(d3a_probe::CANDIDATE);\n"
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
        "text": "drop(_d3a_candidate);\n            ",
        "label": "CANDIDATE_END",
    },
    # --- candidate loop: ordinal, registration, sample guard ---------------
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "for (doc_id, score) in scored {",
        "placement": "before",
        "text": (
            "d3a_probe::register_segment(scored.len());\n"
            "            let _d3a_scored_len = scored.len();\n"
            "            let mut _d3a_ordinal: usize = 0;\n"
            "            "
        ),
        "label": "SEGMENT_REGISTER_AND_ORDINAL",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "total_hits = total_hits",
        "placement": "before",
        "text": (
            "let _d3a_candidate_sample = "
            "d3a_probe::candidate_sample(_d3a_scored_len, _d3a_ordinal);\n"
            "                _d3a_ordinal = _d3a_ordinal\n"
            '                    .checked_add(1)\n'
            '                    .expect("diagnostic candidate ordinal overflow");\n'
            "                "
        ),
        "label": "CANDIDATE_SAMPLE_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "let key = if single_hit_segment {",
        "placement": "before",
        "text": (
            "let _d3a_key = d3a_probe::micro_span(d3a_probe::CANDIDATE_KEY);\n"
            "                "
        ),
        "label": "CANDIDATE_KEY_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": "                    reader.doc_key(doc_id)?\n                };\n",
        "placement": "after",
        "text": (
            "                drop(_d3a_key);\n"
            "                d3a_probe::sample_count(d3a_probe::CANDIDATE_SAMPLES_KEY);\n"
        ),
        "label": "CANDIDATE_KEY_END_AND_KEY_COUNT",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": (
            "                if heap\n"
            "                    .iter()\n"
            "                    .any(|existing| existing.hit.key == entry.hit.key)\n"
            "                {\n"
            "                    return Err(SearchError::CorruptIndex {\n"
            '                        detail: "duplicate live document key across segments".to_owned(),\n'
            "                    });\n"
            "                }\n"
        ),
        "placement": "before",
        "text": (
            "                let _d3a_duplicate = "
            "d3a_probe::micro_span(d3a_probe::CANDIDATE_DUPLICATE);\n"
        ),
        "label": "GENERIC_DUPLICATE_START",
    },
    {
        "file": UNIFIED,
        "function": "collect_mixed",
        "region": "collect_mixed",
        "anchor": (
            "                if heap\n"
            "                    .iter()\n"
            "                    .any(|existing| existing.hit.key == entry.hit.key)\n"
            "                {\n"
            "                    return Err(SearchError::CorruptIndex {\n"
            '                        detail: "duplicate live document key across segments".to_owned(),\n'
            "                    });\n"
            "                }\n"
        ),
        "placement": "after",
        "text": "                drop(_d3a_duplicate);\n",
        "label": "GENERIC_DUPLICATE_END",
    },
    # --- borrowed keyword helpers -----------------------------------------
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": "let view = columns.keyword_sort_view(field_id, doc_id)?;",
        "placement": "before",
        "text": (
            "let _d3a_sort_view = "
            "d3a_probe::micro_span(d3a_probe::CANDIDATE_SORT_VIEW);\n    "
        ),
        "label": "SORT_VIEW_START",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": "let view = columns.keyword_sort_view(field_id, doc_id)?;",
        "placement": "after",
        "text": "    drop(_d3a_sort_view);\n",
        "label": "SORT_VIEW_END",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": "let Some(charge) = borrowed_keyword_candidate_charge(&key, &view)? else {",
        "placement": "before",
        "text": (
            "let _d3a_sort_charge = "
            "d3a_probe::micro_span(d3a_probe::CANDIDATE_SORT_CHARGE);\n    "
        ),
        "label": "SORT_CHARGE_START",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": "    // Stale/duplicate retained state must surface even for a losing candidate.",
        "placement": "before",
        "text": "drop(_d3a_sort_charge);\n    ",
        "label": "SORT_CHARGE_END",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": (
            "    if heap.iter().any(|existing| existing.hit.key == key) {\n"
            "        return Err(SearchError::CorruptIndex {\n"
            '            detail: "duplicate live document key across segments".to_owned(),\n'
            "        });\n"
            "    }\n"
        ),
        "placement": "before",
        "text": (
            "    let _d3a_duplicate = "
            "d3a_probe::micro_span(d3a_probe::CANDIDATE_DUPLICATE);\n"
        ),
        "label": "BORROWED_DUPLICATE_START",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": (
            "    if heap.iter().any(|existing| existing.hit.key == key) {\n"
            "        return Err(SearchError::CorruptIndex {\n"
            '            detail: "duplicate live document key across segments".to_owned(),\n'
            "        });\n"
            "    }\n"
        ),
        "placement": "after",
        "text": "    drop(_d3a_duplicate);\n",
        "label": "BORROWED_DUPLICATE_END",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": "        let entry = materialize_keyword_entry(",
        "placement": "before",
        "text": (
            "        let _d3a_materialize = "
            "d3a_probe::micro_span(d3a_probe::CANDIDATE_MATERIALIZE);\n"
        ),
        "label": "MATERIALIZE_INSERT_START",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": "            charge,\n        )?;\n",
        "placement": "after",
        "text": (
            "\n        drop(_d3a_materialize);\n"
            "        d3a_probe::sample_count(d3a_probe::CANDIDATE_SAMPLES_FAST);"
        ),
        "label": "MATERIALIZE_INSERT_END_FAST_COUNT",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": "let Some(sort_ordering) = compare_borrowed_keyword_to_owned(",
        "placement": "before",
        "text": (
            "let _d3a_compare = "
            "d3a_probe::micro_span(d3a_probe::CANDIDATE_COMPARE);\n    "
        ),
        "label": "COMPARE_START",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": (
            "    let ordering = if sort_ordering == Ordering::Equal {\n"
            "        key.as_str()\n"
            "            .as_bytes()\n"
            "            .cmp(worst.hit.key.as_str().as_bytes())\n"
            "    } else {\n"
            "        sort_ordering\n"
            "    };\n"
        ),
        "placement": "after",
        "text": "    drop(_d3a_compare);\n",
        "label": "COMPARE_END",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": (
            "    if ordering != Ordering::Less {\n"
            "        #[cfg(test)]\n"
            "        b_observation::record_rejected();\n"
            "        return Ok(());\n"
            "    }\n"
        ),
        "placement": "before",
        "text": (
            "        d3a_probe::sample_count(d3a_probe::CANDIDATE_SAMPLES_FAST);\n"
            "        d3a_probe::sample_count(d3a_probe::CANDIDATE_SAMPLES_REJECT);\n"
        ),
        "label": "NONCOMPETITIVE_REJECT",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": (
            "    let entry = materialize_keyword_entry(\n"
            "        &view,\n"
            "        request,\n"
            "        segment_index,\n"
            "        doc_id,\n"
            "        key,\n"
            "        score,\n"
            "        include_score,\n"
            "        charge,\n"
            "    )?;\n"
            "    heap_admit_candidate(entry, heap, heap_limit, budget, scope)\n"
            "}\n"
        ),
        "placement": "before",
        "text": (
            "    let _d3a_materialize = "
            "d3a_probe::micro_span(d3a_probe::CANDIDATE_MATERIALIZE);\n"
        ),
        "label": "MATERIALIZE_ADMIT_START",
    },
    {
        "file": UNIFIED,
        "function": "consider_borrowed_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": "        charge,\n    )?;\n",
        "placement": "after",
        "text": (
            "\n    drop(_d3a_materialize);\n"
            "    d3a_probe::sample_count(d3a_probe::CANDIDATE_SAMPLES_FAST);"
        ),
        "label": "MATERIALIZE_ADMIT_END_FAST_COUNT",
    },
    {
        "file": UNIFIED,
        "function": "admit_legacy_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": "    #[cfg(test)]\n    b_observation::record_legacy();",
        "placement": "after",
        "text": (
            "\n    d3a_probe::sample_count(d3a_probe::CANDIDATE_SAMPLES_FALLBACK);"
        ),
        "label": "FALLBACK_COUNT",
    },
    {
        "file": UNIFIED,
        "function": "admit_legacy_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": (
            "    if heap\n"
            "        .iter()\n"
            "        .any(|existing| existing.hit.key == entry.hit.key)\n"
            "    {\n"
            "        return Err(SearchError::CorruptIndex {\n"
            '            detail: "duplicate live document key across segments".to_owned(),\n'
            "        });\n"
            "    }\n"
        ),
        "placement": "before",
        "text": (
            "    let _d3a_duplicate = "
            "d3a_probe::micro_span(d3a_probe::CANDIDATE_DUPLICATE);\n"
        ),
        "label": "LEGACY_DUPLICATE_START",
    },
    {
        "file": UNIFIED,
        "function": "admit_legacy_keyword_candidate",
        "region": "keyword_helpers",
        "anchor": (
            "    if heap\n"
            "        .iter()\n"
            "        .any(|existing| existing.hit.key == entry.hit.key)\n"
            "    {\n"
            "        return Err(SearchError::CorruptIndex {\n"
            '            detail: "duplicate live document key across segments".to_owned(),\n'
            "        });\n"
            "    }\n"
        ),
        "placement": "after",
        "text": "    drop(_d3a_duplicate);\n",
        "label": "LEGACY_DUPLICATE_END",
    },
    # --- shared heap admission --------------------------------------------
    {
        "file": UNIFIED,
        "function": "heap_admit_candidate",
        "region": "keyword_helpers",
        "anchor": (
            "    let charge = entry.charge;\n"
            "    if heap.len() < heap_limit {\n"
        ),
        "placement": "before",
        "text": (
            "    let _d3a_heap = "
            "d3a_probe::micro_span(d3a_probe::CANDIDATE_HEAP);\n"
        ),
        "label": "HEAP_START",
    },
    {
        "file": UNIFIED,
        "function": "heap_admit_candidate",
        "region": "keyword_helpers",
        "anchor": (
            "        heap_preflight_insert(budget, heap_memory.as_deref(), charge)?;\n"
            "        heap_commit_insert(budget, heap_memory, charge)?;\n"
            "        heap.push(entry);\n"
        ),
        "placement": "after",
        "text": "        d3a_probe::sample_count(d3a_probe::CANDIDATE_SAMPLES_INSERT);\n",
        "label": "HEAP_INSERT_COUNT",
    },
    {
        "file": UNIFIED,
        "function": "heap_admit_candidate",
        "region": "keyword_helpers",
        "anchor": "            heap.push(entry);\n        }\n",
        "placement": "after",
        "text": (
            " else {\n"
            "            d3a_probe::sample_count(d3a_probe::CANDIDATE_SAMPLES_REJECT);\n"
            "        }\n"
        ),
        "label": "HEAP_REJECT_COUNT",
    },
    {
        "file": UNIFIED,
        "function": "heap_admit_candidate",
        "region": "keyword_helpers",
        "anchor": "            heap.push(entry);\n",
        "placement": "after",
        "text": "            d3a_probe::sample_count(d3a_probe::CANDIDATE_SAMPLES_REPLACE);\n",
        "label": "HEAP_REPLACE_COUNT",
    },
    {
        "file": UNIFIED,
        "function": "heap_admit_candidate",
        "region": "keyword_helpers",
        "anchor": (
            "    Ok(())\n"
            "}\n"
            "\n"
            "/// Materialize the owned tuple for one validated borrowed keyword candidate."
        ),
        "placement": "before",
        "text": "    drop(_d3a_heap);\n",
        "label": "HEAP_END",
    },
    # --- crates/quervant-core/src/search/execute.rs ------------------------
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let (leaf_data, leaf_charges) = {",
        "placement": "before",
        "text": (
            "d3a_probe::begin_segment();\n    "
            "let _d3a_leaf = d3a_probe::span(d3a_probe::LEAF_DECODE);\n    "
        ),
        "label": "BEGIN_SEGMENT_LEAF_DECODE_START",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let mut matched: BTreeSet<u64> = BTreeSet::new();",
        "placement": "before",
        "text": (
            "drop(_d3a_leaf);\n    "
            "let _d3a_membership = d3a_probe::span(d3a_probe::MEMBERSHIP);\n    "
        ),
        "label": "LEAF_DECODE_END_MEMBERSHIP_START",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let matched_entries = matched.len() as u64;",
        "placement": "before",
        "text": "drop(_d3a_membership);\n    ",
        "label": "MEMBERSHIP_END",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let matched_entries = matched.len() as u64;",
        "placement": "before",
        "text": (
            "let _d3a_matched_reserve = "
            "d3a_probe::span(d3a_probe::MATCHED_RESERVE);\n    "
        ),
        "label": "MATCHED_RESERVE_START",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let matched_entries = matched.len() as u64;",
        "placement": "after",
        "text": "\n    d3a_probe::count(d3a_probe::MATCHED_DOCS, matched_entries);",
        "label": "MATCHED_DOCS_COUNT",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "    ledger.reserve_with_memory(matched_entries, matched_bytes, memory.as_deref_mut())?;",
        "placement": "after",
        "text": "\n    drop(_d3a_matched_reserve);",
        "label": "MATCHED_RESERVE_END",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let (scored, scored_charges) = score_segment(",
        "placement": "before",
        "text": "let _d3a_score = d3a_probe::span(d3a_probe::SCORE_VECTOR);\n    ",
        "label": "SCORE_VECTOR_START",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "// Segment-owned temporaries are released here;",
        "placement": "before",
        "text": "drop(_d3a_score);\n    ",
        "label": "SCORE_VECTOR_END",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let scored_vec: Vec<(u64, f64)> = scored.into_iter().collect();",
        "placement": "before",
        "text": (
            "let _d3a_scored_vec = "
            "d3a_probe::span(d3a_probe::SCORED_VEC_BUILD);\n    "
        ),
        "label": "SCORED_VEC_BUILD_START",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "let scored_vec: Vec<(u64, f64)> = scored.into_iter().collect();",
        "placement": "after",
        "text": (
            "\n    drop(_d3a_scored_vec);\n"
            "    d3a_probe::count(d3a_probe::SCORED_DOCS,\n"
            '        u64::try_from(scored_vec.len()).expect("diagnostic score count overflow"));'
        ),
        "label": "SCORED_VEC_BUILD_END_SCORED_COUNT",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "// Segment-owned temporaries are released here;",
        "placement": "before",
        "text": "let _d3a_temp_release = d3a_probe::span(d3a_probe::TEMP_RELEASE);\n    ",
        "label": "TEMP_RELEASE_START",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "    Ok(scored_vec)\n}",
        "placement": "before",
        "text": "drop(_d3a_temp_release);\n    ",
        "label": "TEMP_RELEASE_END",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "matched.insert(*doc_id);",
        "placement": "before",
        "text": (
            "let _d3a_match_insert = "
            "d3a_probe::match_insert_sample(matched.len());\n                "
        ),
        "label": "MATCH_INSERT_POSTINGS_START",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "matched.insert(*doc_id);",
        "placement": "after",
        "text": "\n                drop(_d3a_match_insert);",
        "label": "MATCH_INSERT_POSTINGS_END",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "matched.insert(doc_id);",
        "placement": "before",
        "text": (
            "let _d3a_match_insert = "
            "d3a_probe::match_insert_sample(matched.len());\n                "
        ),
        "label": "MATCH_INSERT_BITMAP_START",
    },
    {
        "file": EXECUTE,
        "function": "evaluate_lexical_with",
        "region": "evaluate_lexical_with",
        "anchor": "matched.insert(doc_id);",
        "placement": "after",
        "text": "\n                drop(_d3a_match_insert);",
        "label": "MATCH_INSERT_BITMAP_END",
    },
    # --- PR 15I-D2-A inherited nested score stages -------------------------
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "let entries = matches.len() as u64;",
        "placement": "before",
        "text": "let _d3a_score_map = d3a_probe::span(d3a_probe::SCORE_MAP);\n    ",
        "label": "SCORE_MAP_START",
    },
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "if scores.is_empty() {",
        "placement": "before",
        "text": (
            "drop(_d3a_score_map);\n    "
            "d3a_probe::count(d3a_probe::SCORING_MAP_ENTRIES, entries);\n    "
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
            "d3a_probe::count(d3a_probe::BM25_CALLS, 0);\n            "
            "d3a_probe::count(d3a_probe::POSITIVE_TERM_OWNERS, 0);\n            "
        ),
        "label": "EMPTY_ZERO_COUNTS",
    },
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "let mut owner: BTreeMap<(u32, &str), usize> = BTreeMap::new();",
        "placement": "before",
        "text": "let _d3a_score_owner = d3a_probe::span(d3a_probe::SCORE_OWNER);\n    ",
        "label": "SCORE_OWNER_START",
    },
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": (
            "    for (index, leaf) in leaf_data.iter().enumerate() {\n"
            "        // Only scoring-eligible (positive/even-`Not`-parity) leaves contribute."
        ),
        "placement": "before",
        "text": (
            "    drop(_d3a_score_owner);\n    "
            "d3a_probe::count(d3a_probe::POSITIVE_TERM_OWNERS,\n"
            '        u64::try_from(owner.len()).expect("diagnostic owner count overflow"));\n'
            "    let _d3a_score_accumulate = "
            "d3a_probe::span(d3a_probe::SCORE_ACCUMULATE);\n    "
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
            "d3a_probe::count(d3a_probe::BM25_CALLS, 1);\n"
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
            "d3a_probe::count(d3a_probe::BM25_CALLS, 1);\n"
        ),
        "label": "BM25_CALL_PHRASE",
    },
    {
        "file": EXECUTE,
        "function": "score_segment",
        "region": "score_segment",
        "anchor": "    Ok((scores, charges))\n}",
        "placement": "before",
        "text": "    drop(_d3a_score_accumulate);\n",
        "label": "SCORE_ACCUMULATE_END",
    },
    # --- benchmarks/pr15d/adapters/quervant/src/main.rs -------------------
    {
        "file": ADAPTER,
        "function": "imports",
        "region": None,
        "anchor": "use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};\n",
        "placement": "after",
        "text": "use quervant_core::search::d3a_probe;\n",
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
            "                d3a_probe::reset();\n"
            "                let mut body = session.as_ref()\n"
            '                    .expect("query session is always present here")\n'
            "                    .query(&request)?;\n"
            "                let (stages, counts, segments, sample_strata_ns,\n"
            "                    sample_strata_count, segments_unsupported) = d3a_probe::take();\n"
            "                let object = body.as_object_mut().ok_or_else(|| {\n"
            '                    AdapterError::new("diagnostic", "query body was not an object")\n'
            "                })?;\n"
            '                object.insert("stage_ns".to_owned(), json!(stages));\n'
            '                object.insert("counts".to_owned(), json!(counts));\n'
            '                object.insert("segments".to_owned(), json!(segments));\n'
            '                object.insert("sample_strata_ns".to_owned(), json!(sample_strata_ns));\n'
            '                object.insert("sample_strata_count".to_owned(), json!(sample_strata_count));\n'
            '                object.insert("segments_unsupported".to_owned(), json!(segments_unsupported));\n'
            "                Ok(body)\n"
            "            },\n"
            "            "
        ),
        "label": "QUERY_PROBE_ARM",
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
            "D3A_PATCH_REGION",
            f"{path}:{region}: start delimiter occurs {text.count(start_delim)} times",
        )
    if text.count(stop_delim) != 1:
        raise PatchError(
            "D3A_PATCH_REGION",
            f"{path}:{region}: stop delimiter occurs {text.count(stop_delim)} times",
        )
    start = text.index(start_delim)
    stop = text.index(stop_delim)
    if stop <= start:
        raise PatchError(
            "D3A_PATCH_REGION", f"{path}:{region}: stop delimiter precedes start"
        )
    return start, stop


def find_unique(text: str, anchor: str, start: int, stop: int, path: str, label: str) -> int:
    region = text[start:stop]
    count = region.count(anchor)
    if count != 1:
        raise PatchError(
            "D3A_PATCH_ANCHOR",
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
                "D3A_PATCH_OVERLAP",
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
            "D3A_PATCH_COMMAND", f"{label} failed ({result.returncode}): {result.stdout[-4000:]}"
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
        raise PatchError("D3A_PATCH_GIT", f"git {' '.join(args)}: {result.stdout.strip()}")
    return result.stdout.rstrip("\n")


def check_pristine_base(root: str) -> str:
    head = _git(root, "rev-parse", "HEAD")
    if head != BASE_SHA:
        raise PatchError("D3A_PATCH_BASE", f"{root} HEAD is {head}, expected {BASE_SHA}")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise PatchError(
            "D3A_PATCH_DIRTY", f"{root} tracked/untracked changes present: {status}"
        )
    return head


def check_derivative_absent(root: str) -> None:
    probe_path = os.path.join(root, D3A_PROBE)
    if os.path.exists(probe_path):
        raise PatchError("D3A_PATCH_EXISTS", f"{D3A_PROBE} already exists")
    cargo = os.path.join(root, CORE_CARGO)
    text = open(cargo, "rb").read().decode("utf-8")
    if FEATURE in text:
        raise PatchError("D3A_PATCH_EXISTS", f"feature {FEATURE!r} already present")
    mod_text = open(os.path.join(root, SEARCH_MOD), "rb").read().decode("utf-8")
    if "pub mod d3a_probe;" in mod_text or "d3a_probe" in mod_text:
        raise PatchError("D3A_PATCH_EXISTS", "d3a_probe module already declared")
    adapter_text = open(os.path.join(root, ADAPTER), "rb").read().decode("utf-8")
    if "query_probe" in adapter_text:
        raise PatchError("D3A_PATCH_EXISTS", "query_probe arm already present")


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
                "D3A_REVERSE_EDIT",
                f"{path}: non-insertion diff opcode {tag} at base {i1}:{i2}",
            )
    if "".join(reconstructed) != base_text:
        raise PatchError("D3A_REVERSE_EDIT", f"{path}: reversing insertions did not restore BASE")
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
    with open(os.path.join(root, D3A_PROBE), "wb") as handle:
        handle.write(D3A_PROBE_RS.encode("utf-8"))

    for relative in (UNIFIED, EXECUTE, SEARCH_MOD, D3A_PROBE, ADAPTER):
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
        if relative == D3A_PROBE:
            formatted = D3A_PROBE_RS
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
            "D3A_PATCH_EXTRA",
            f"scratch tree changed unexpected paths: {sorted(changed ^ expected)}",
        )

    _git(root, "add", "-N", D3A_PROBE)
    binary_diff = subprocess.run(
        ["git", "diff", "--binary", BASE_SHA],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    _git(root, "reset", "--", D3A_PROBE)
    if binary_diff.returncode != 0:
        raise PatchError("D3A_PATCH_GIT", "git diff --binary BASE failed")

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
        "schema": "pr15i-d3a-source-derivation-v1",
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
            "score_map_ns",
            "score_owner_ns",
            "score_accumulate_ns",
            "matched_reserve_ns",
            "scored_vec_build_ns",
            "temp_release_ns",
            "match_insert_sample_ns",
            "candidate_sample_ns",
            "candidate_key_ns",
            "candidate_sort_view_ns",
            "candidate_sort_charge_ns",
            "candidate_duplicate_ns",
            "candidate_compare_ns",
            "candidate_materialize_ns",
            "candidate_heap_ns",
        ],
        "counter_labels": [
            "matched_docs",
            "scored_docs",
            "candidate_docs",
            "bm25_calls",
            "scoring_map_entries",
            "positive_term_owners",
            "candidate_samples_first",
            "candidate_samples_steady",
            "candidate_samples_fast",
            "candidate_samples_fallback",
            "candidate_samples_insert",
            "candidate_samples_replace",
            "candidate_samples_reject",
            "match_insert_samples",
            "candidate_samples_key",
        ],
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
