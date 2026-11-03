# PR 15E Phase 5 — selective DOC_KEYS decoding for singleton hits

**Status: `P5_IMPLEMENTED` + `P5_QA_PASS` + `P5_PERF_MEASURED`** (phase acceptance is
reserved to the maintainer/reviewer; no Phase 6 work, no merge).

One optimization inside PR #83: when a segment contributes exactly one scored or projected
hit and has at least 1,024 physical documents, resolve that hit's logical key by scanning
the existing `DOC_KEYS` v1 section once and owning only the requested key. Every other shape
keeps the unchanged full-key cache path.

| Item | Value |
|---|---|
| Branch / PR | `dev/pr15e-b1-live-bitmap-postings-membership` / #83 |
| Phase 4 anchor (arm A) | `784c1af8fd3a7d69978c4214fcef3b1464cb63ec` |
| Phase 5 production code SHA | `9881789b6c00a14bed995a5bc7e38ae18536d125` |
| Runner `p5` stage SHA / measured arm B | `66b266fd8850c90836d4327700f279a2ed2c4b92` (Rust tree identical to the code SHA: `git diff --name-only 9881789..66b266f -- crates/` is empty) |

## 1. P0 preflight (observed)

| Check | Observation |
|---|---|
| Branch / HEAD at start | `dev/pr15e-b1-live-bitmap-postings-membership` at `784c1af` (Phase 4 evidence head), clean tracked tree |
| `784c1af` is HEAD | yes (exact anchor) |
| `main` | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` (unchanged) |
| Pre-existing Phase 5 code | none |
| Source premises verified | `encode_doc_keys` writes v1 + count + one length-prefixed key per document in physical order; `decode_doc_keys` enforces `count == doc_count`, `check_entries`, `usize` conversion, `count_min_bytes(...,3,...)`, UTF-8, `DocumentKey::new`, `expect_end`; `DocumentKey::new` rejects only empty and `> MAX_BYTES (1024)`; `doc_key(doc_id)` indexes the full vector by physical id (no logical-key join) |

## 2. Two-path control flow

* **Path A (optimized, per site independently).** `collect_mixed`: after the unchanged
  `total_hits` increment, at the existing `reader.doc_key(doc_id)?` expression, use
  `doc_key_selected` iff `scored.len() == 1 && reader.doc_count() >= 1024`.
  `project_selected_hits`: in the existing physical-key parity loop, use it iff
  `indices.len() == 1 && reader.doc_count() >= 1024`.
* **Path B (legacy).** Every other shape — 0 hits, ≥2 hits, segments below 1,024 docs,
  Boolean/phrase/multi-term/typed/mixed queries, aggregation, cursor, mutation selection,
  pure lexical executor, the standalone `LexicalSearcher` — keeps the original
  `doc_key`/`doc_keys` full-cache path byte-identically.

Selective accessor behaviour: if this query-local reader already holds a full key cache, the
requested key is cloned from it (no second decode, cache never replaced); otherwise the
single scan runs and the cache is **not** installed.

## 3. Implementation

`segment/reader.rs`:

* `fn decode_doc_key_selected(reader, selected_doc_id)` — same ordered framing checks as the
  full decoder, out-of-range id rejected with the existing `Corrupt { context: "doc keys" }`
  shape, every key UTF-8-validated and checked against the constructor's exact rules
  (non-empty, ≤ 1024 bytes) **without owning unselected strings**, only the selected
  `DocumentKey` owned, `expect_end` enforced after the full scan, and a typed corruption
  error for the impossible "not selected" case.
* `pub(crate) fn doc_key_selected(doc_id)` — cache-first clone or single scan; never calls
  `doc_keys()`, never installs the cache.
* Test-only witnesses (`#[cfg(test)]`): cache occupancy and an owned-selected-key counter.
  Public `doc_key`/`doc_keys` unchanged.

`search/unified.rs`: the two call sites above only. No score, sort, cursor, ledger, batch,
aggregation, projection-plan, or `total_hits` logic touched.

## 4. Correctness evidence

Codec/reader (`segment/tests.rs` `phase5`, 10 tests): sizes 1/2/1023/1024/1025 with
first/middle/last selection; 200 seeded fixtures with 1–1024-byte UTF-8 keys compared against
the accepted full decoder; corruption in an unselected key **after** and **before** the
selected one (no early exit, no skipped prefix); out-of-range ids (including `u64::MAX`) with
no cache install; version/count mismatch; truncation and trailing bytes; invalid UTF-8, empty
and oversized keys in selected and unselected slots (parity with the legacy decoder); cache
ownership in both orders with exactly one owned key on the cold path and zero on the cached
path; duplicate logical keys keeping physical identity. Corruption is injected through a
checksum-valid rebuilt container so the codec (not the digest) is what rejects it.

Query/projection: key-parity rejection on the fast path (`CorruptIndex`, zero projection
charged) via `project_selected_hits` with a crafted mismatched physical key on a 1,100-doc
segment.

Integration (`tests/pr15e_b1.rs`, 6 tests, production writer→snapshot→`UnifiedSearcher`):
singleton hits at first/middle/last physical positions (key, score, projected fields,
`total_hits`); 0/2/5/6-hit lanes plus an ineligible Boolean shape; delete + upsert with a
pinned PIT keeping per-generation keys; ascending/descending sort with cursor paging (no
duplicate or missing keys); standalone-vs-batch parity; unchanged exact/one-below work-cap
admission.

## 5. QA — actual results on the Phase 5 head (`66b266f`)

| Gate | Result |
|---|---|
| `cargo fmt --all -- --check` (stable + 1.85.0) | PASS |
| clippy `--workspace --all-targets` ± `--all-features`, stable + MSRV | PASS (4/4) |
| `cargo test --workspace --all-targets` (stable) | PASS — 2227 passed, 0 failed, 10 ignored |
| `… --all-features` (stable) | PASS — 2231 passed, 0 failed, 75 ignored |
| `cargo +1.85.0 test` (default / all-features) | PASS — 2227 / 2231 passed |
| `cargo llvm-cov --all-features --fail-under-lines 85` | PASS — **lines 92.52%** (85694 lines, 6411 missed), functions 88.08%, regions 91.99% |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compile only) |
| PR15D adapter tests (stable + MSRV, `--locked`) | PASS — 5 each |
| `python3 -m unittest discover -s benchmarks/pr15e_b1 -p 'test_*.py' -v` | PASS — 64 tests |
| PR15D harness + PR15E Python suites | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108/108 |
| `git diff --check` | PASS |
| PR15E real-adapter integration (`PR15E_RUN_REAL_INTEGRATION=1`) | PASS — recorded `source_sha=66b266f` |
| Real RustFS (26 invocations, podman + pinned digest `1803faef…`, exact CI env/commands) | PASS — s3 8, proxy 5, remote 3, oracle 1, oracle_geo 1, m1 1, m2 1, m3 3×1, m5 3×1, crash proxy 7, k0 5, k05 10×1 |
| Exact-head GitHub CI (`rust`/`msrv`/`rustfs`) | **`CI_BLOCKED_CREDENTIALS`** — token invalid, branch not pushed; no CI claim |

## 6. Triggered decision rules

| Rule | Trigger | Class | Action |
|---|---|---|---|
| S01 | HEAD = anchor `784c1af`, no unrelated edits | AR | Worked on the branch; recorded ancestry |
| S03 | DOC_KEYS is one key per ascending physical doc | AR | Premise proven from `encode_doc_keys`/`decode_doc_keys`/`doc_key`; proceeded |
| S05 | Selected id ≥ count | AR | Existing range `Corrupt`, no cache write (tested) |
| S06 | Version/count/limit/truncation mismatch | AR | Existing typed errors in original check order (tested) |
| S07 | Unselected UTF-8/key validity | AR | Validated without owning a `String`; existing typed shapes (tested) |
| S08 | Selected key found | AR | Scan continues to `expect_end` (tested) |
| S09/S29 | Full cache already populated | AR | Clone selected key, no reparse, cache untouched (tested) |
| S10 | Cold selective path | AR | One owned key, cache stays empty (tested with witness) |
| S11 | Test-only instrumentation | AR | `#[cfg(test)]` witnesses only; no production counters |
| S12/S13 | Threshold/singleton rules per site | AR | Exact predicates implemented; each site decided independently |
| S15 | Allocation-only admissibility change | AR | Declared `SegmentLimits` checks preserved; no cap relaxed |
| S18 | Local RustFS substitution | AR | Podman + pinned image + exact CI commands; disclosed |
| S19 | Phase 5 timing under the maintainer's assume-idle instruction | AR | `--idle-confirmed` used with recorded provenance; real probes mandatory (54/54 `clear`) |
| S22 | Primary `B_FASTER`, no control `A_FASTER`, all gates PASS | AR | Published `P5_PERF_MEASURED_REVIEW_PENDING`; stopped before Phase 6 |
| S25 | GitHub credentials invalid | DC | `CI_BLOCKED_CREDENTIALS`; local commits kept; no CI PASS claim |
| S30 | Selected key construction failure | AR | Mapped typed error; cache left empty |
| S31 | Docs/tooling commits after the code SHA | AR | Rust tree proven identical before treating QA as valid |

## 7. Residual risks and limits

* The optimization only removes the O(segment docs) key **allocation** for singleton-hit
  queries; validation is still O(segment docs) encoded bytes, by design.
* Multi-hit lanes keep the legacy path, so their small consistent differences in the paired
  campaign are not attributed to Phase 5 (see the qualification doc).
* No CPU/allocation measurement was performed; the PR15E-A key-decode allocation observation
  remains historical motivation, not a Phase 5 attribution.
* Wall-clock only, single host, synthetic exact-term `FsDirectory` workload, in-process
  adapter samples.
* G11 remains `PENDING_REVIEW` under the recorded maintainer waiver; no PASS claimed.
