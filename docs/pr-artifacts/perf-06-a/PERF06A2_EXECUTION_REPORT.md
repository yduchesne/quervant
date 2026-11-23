# PERF-06-A2 — Execution Report

**PR:** `PERF-06-A2: Validated document/frequency-only postings decoding`
**Milestone / series:** `v0.1-perf` / PERF-06-A
**Plan of record:** [`PERF06A2_DETAILED_PLAN.md`](PERF06A2_DETAILED_PLAN.md) (copied unmodified from the approved plan)
**Status:** `PERF06_A2_IMPLEMENTED_READY_FOR_INDEPENDENT_REVIEW` (draft PR, not merged; independent review outstanding).
**No performance acquisition was performed.** No `quervant-bench run`, benchmark, profiling, Criterion, timing loop, cross-engine comparison or RustFS service startup was executed.

---

## 1. Repository, branch and SHA identity

| Item | Value |
|---|---|
| Repository | `yduchesne/quervant` |
| A1 dependency PR | `#120` `PERF-06-A1: Prepare query-local BM25 term weights` |
| A1 fixup head | `657352563c0fbe23759d64d9c2ac5b3b6f7be0a6` |
| A1 merge commit | `20134359c9a2c4257488357eb52e02f5317627d0` |
| `BASE_MAIN_SHA` (`origin/main` at branch creation) | `20134359c9a2c4257488357eb52e02f5317627d0` |
| A2 branch | `dev/perf06-a2-docfreq-postings` (new, from `origin/main`) |
| A2 implementation head | `359ab86a1d63df51d8bce78a212660c6cd5f3e75` (verified equal to the remote branch ref) |
| A2 PR | `#121` — draft, base `main`, not merged, no force push |
| A3 | not started |
| RustFS started locally | **No** (A2 changed no remote storage contract) |

### A1 merge verification (P0)

`gh pr view 120 --json state,mergedAt,mergeCommit,headRefOid` returned:

```
state=MERGED  mergedAt=2026-11-23T19:30:51Z
mergeCommit=20134359c9a2c4257488357eb52e02f5317627d0
headRefOid=657352563c0fbe23759d64d9c2ac5b3b6f7be0a6
```

`origin/main` == `20134359…`, so the A1 fixup is in accepted `main` (squash/merge ancestry verified via the GitHub merge commit, not ancestry alone). **D02 AUTO-RESOLVE applied.**

### Preflight state findings

| Check | Result |
|---|---|
| Worktree clean before start | PASS (no tracked/untracked changes) |
| Remote branch `dev/perf06-a2-docfreq-postings` | absent (PASS) |
| Existing PR mentioning `PERF-06-A2` / `docfreq` | none (PASS) |
| Pre-existing **empty** local branch `dev/perf06-a2` | present, created from `origin/main` at `2013435` with **zero commits** and no remote/PR |
| A2 branch created | `git switch -c dev/perf06-a2-docfreq-postings origin/main` |

**D04 record:** the local `dev/perf06-a2` placeholder was *not* deleted, reset, renamed or pushed, and no competing PR was created. Because it contains no commits and does not track a remote, it holds no A2 work; the plan-prescribed branch name was used. If the maintainer prefers the shorter placeholder name, the branch can be re-pointed after review — no force push is performed by this PR.

### Source blob table (verified against `origin/main` = base)

All 12 inspected blobs matched the plan table exactly before any edit (D03 did not trigger).

| Path | Expected (= actual at base) |
|---|---|
| `crates/quervant-core/src/segment/postings.rs` | `31e2981e0be42b316668016f46436c36dc0fc143` |
| `crates/quervant-core/src/segment/tests.rs` | `213ba6e7c640411f34ec10a0988b26e76be5acba` |
| `crates/quervant-core/src/search/score.rs` | `6f8bd0f54896aa201d932125dcf21417fb69d58c` |
| `crates/quervant-core/src/search/execute.rs` | `25516f05bae0631aae28a3d0e038882a3141a4ab` |
| `crates/quervant-core/src/segment/reader.rs` | `aa69f2bebb9746f44254a702438e91cea9a9b7a5` |
| `crates/quervant-core/src/segment/limits.rs` | `bf222b67e0675aadf6137642748d6b7f4c781328` |
| `crates/quervant-core/src/segment/format.rs` | `6932edd210e3cc480342f11c4e4ca7ae5ec39e77` |
| `crates/quervant-core/src/segment/error.rs` | `e44e48d5a2880d1431691c51919bcdc6268060fb` |
| `crates/quervant-core/tests/segment_codec.rs` | `7aeb5e0c1d88aa004e4f1e31f8602260c2739e88` |
| `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` | `b418c0e36728d292b35bb5bcc7df9a9d279279de` |
| `AGENTS.md` | `08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c` |
| `.github/workflows/ci.yml` | `df63adc43f9f27e1e84e539d00bb2d78361c5c03` |

### Baseline health (P0, on accepted `main`, before edits)

| Command | Result |
|---|---|
| `cargo test -p quervant-core --lib postings_round_trip_and_errors` | PASS 1 |
| `cargo test -p quervant-core --lib decoder_rejects_nonmonotone_doc_id_deltas` | PASS 1 |
| `cargo test -p quervant-core --test segment_codec` | PASS 24 |
| `cargo test -p quervant-core --test segment_corrective` | PASS 24 |
| `cargo test -p quervant-core --test pr15i_d2a_scoring_contract` | PASS 16 |
| `cargo test -p quervant-core --test pr07_properties` | PASS 4 |

---

## 2. Pre-implementation invariant challenge (written before production code)

Each row was challenged against adversarial inputs before the decoder was edited. Ambiguities were resolved only by the plan (§4–§5) — no new contract was invented.

| INV | Source anchor | Falsification attempt | Planned witness | Outcome |
|---|---|---|---|---|
| INV-01 | `read_one_with` (shared loop), `DocFreqPostingsReader::next_with` | 0 / 1 / 2 / 3 postings, freq 1..3, repeated EOF | U01, U02, U07, U09, I01 | PASS |
| INV-02 | shared decoder parses all 5 occurrence fields in both modes | corrupt **second**, nonwinning posting; truncated/invalid varint; start>end; zero length; decreasing value index; position overflow | U03, U04, U05, U08 | PASS |
| INV-03 | `DecodeDetail` gates only `reserve`/`push` and cached clone | reserve/clone counters on lean path | U01, U06, U07 | PASS (lean = 0/0) |
| INV-04 | `into_doc_freq` consumes `self`; `advance*` untouched | `next`→`advance`→`advance_with` on cached current; conversion after a full read | U02, U06, U07, U09, existing `segment_codec` | PASS |
| INV-05 | `check_entries`, `max_decoded_entries`, hypothetical `check_alloc::<Occurrence>` | exact limit, one byte below, `max_decoded_entries=1` with freq 2 | U05, U10, existing `b4_u05` | PASS |
| INV-06 | one `cancel_result` at each attempted posting boundary | counting canceller: cancel before first / after one / at EOF; poll count == attempts | U08, U09, existing SC-12 | PASS (3 polls for 2 postings + EOF) |
| INV-07 | `build_phrase` keeps full `Posting.occurrences` | phrase membership + positions on real index | U06, I02, `pr07_properties` | PASS |
| INV-08 | scoring/ledger unchanged | exact `f64::to_bits()` per key across term/prefix/And/phrase, K10 vs K100, reopen | I02, SC01–SC16 + A1, `pr14_unified_mixed` | PASS |
| INV-09 | no format/writer/snapshot change | diff audit: no encoder/dictionary/manifest/feature edits | §6 diff audit, I01/I02, CODEC suites | PASS |
| INV-10 | no benchmarks, format change, topology or API drift | command log + diff audit | §7, §11 | PASS |

---

## 3. Implementation summary (scope audit)

### 3.1 New API (`crates/quervant-core/src/segment/postings.rs`)

* `pub struct DocFreqPosting { pub doc_id: u64, pub freq: u64 }` (`Copy`).
* `pub struct DocFreqPostingsReader<'a> { inner: PostingsReader<'a> }`.
* `PostingsReader::into_doc_freq(self) -> DocFreqPostingsReader<'a>` — consumes the cursor, clears `current` (dropping the cached positional clone), continues at the next unread posting.
* `DocFreqPostingsReader::next()` / `next_with(&dyn Cancellation)`.
* Private `DecodeDetail { Full, DocFreq }` and one shared `read_one_with(cancel, detail)` containing the **entire former `next_with` body** with identical statement order, contexts, error variants and details.
* `PostingsReader::next_with` is now a thin router: `read_one_with(Full)` → build `Posting` → `current = Some(posting.clone())`. `next`, `advance`, `advance_with` bodies are unchanged.
* `#[cfg(test)] pub(crate) mod decode_observation` with thread-local `Cell<u64>` counters `positional_vector_reserves` and `cached_posting_clones` (`reset()` / `counts()`), incremented immediately before the only two full-mode materialization sites. No production counters, metrics, tracing, allocator hooks or profiler.

Mode-dependent behaviour is **exactly two** things:
1. `occurrences.reserve(freq as usize)` only in `Full`;
2. `occurrences.push(Occurrence { .. })` only in `Full`.

Byte parsing/validation, `check_entries`, `check_alloc::<Occurrence>(freq)`, monotonicity/overflow checks, `expect_end("postings")`, `finished` handling and `docs_read`/`previous_doc` commits are identical in both modes.

**Deviation (mechanical, recorded):** the plan text says the private `enum DecodeDetail` lives "within the existing `impl PostingsReader`". Rust does not permit `enum` items inside an `impl` block, so the enum is a private module-level item directly beside the decoder, with an in-code comment stating this. No behavioural difference.

### 3.2 Consumer conversions — exactly C1–C4

| ID | File / function | Diff |
|---|---|---|
| C1 | `search/execute.rs::build_leaf_data`, `CompiledLeaf::Term` | `if let Some(postings) = reader.postings(..)` + `let mut postings = postings.into_doc_freq();` |
| C2 | `search/execute.rs::build_leaf_data`, `CompiledLeaf::MultiTerm` | `reader.postings_for_entry(entry)?.into_doc_freq()` |
| C3 | `search/score.rs::compute_stats`, persisted-norms partially-live DF scan | `let Some(postings) = …` + `let mut postings = postings.into_doc_freq();` |
| C4 | `search/score.rs::compute_stats`, legacy no-norms reconstruction | `reader.postings_for_entry(entry)?.into_doc_freq()` |
| C5 (protected) | `search/execute.rs::build_phrase` | **unchanged** — still `if let Some(mut postings) = reader.postings(field_id, &token.term)?` then `postings.next_with(cancel)` with `posting.occurrences` ownership |

`git diff` on `execute.rs` is 5 changed lines and on `score.rs` 5 changed lines; every other line is byte-identical, including A1 prepared-IDF code.

### 3.3 Changed files (complete list)

```
crates/quervant-core/src/search/execute.rs         (+5/-4 lines of code)
crates/quervant-core/src/search/score.rs           (+5/-4)
crates/quervant-core/src/segment/postings.rs       (+158/-19)
crates/quervant-core/src/segment/tests.rs          (+737)
crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs (+82)
crates/quervant-core/tests/segment_codec.rs        (+89)
docs/pr-artifacts/perf-06-a/PERF06A2_DETAILED_PLAN.md   (new, copy of approved plan)
docs/pr-artifacts/perf-06-a/PERF06A2_EXECUTION_REPORT.md (new, this report)
```

No changes to `segment/mod.rs`, `segment/reader.rs`, `segment/limits.rs`, `segment/format.rs`, `segment/error.rs`, `segment/build.rs`, encoder, dictionary, schema, norms, manifest, feature ids, wire bytes, CI definitions, `AGENTS.md`, roadmap or benchmark harness.

---

## 4. RED evidence (P1, before production edits)

A2-U01/U05/U07 were written first against the not-yet-existing API. `cargo test -p quervant-core --lib a2_u` failed only on missing-API symbols:

```
error[E0432]: unresolved import `super::postings::decode_observation`   (2×)
error[E0599]: no method named `into_doc_freq` found for struct `PostingsReader<'a>` (6×)
error[E0614]: type `u64` cannot be dereferenced                          (2×, test-local)
```

The two `E0614` diagnostics were a genuine **test-local** bug (binding modes in a `matches!` guard inside `a2_u05`), fixed by matching the error and using `assert_eq!` on the bound fields; they were not missing-API evidence. **D19 applied:** the missing-API failure was preserved as RED, the test bug was fixed, no assertion was weakened, and implementation followed.

---

## 5. GREEN evidence — unit tests (`crates/quervant-core/src/segment/tests.rs`)

`cargo test -p quervant-core --lib a2_u` → **10 passed, 0 failed**.

| Test ID | Name | Executed | Passed |
|---|---|---|---|
| A2-U01 | `a2_u01_docfreq_positional_parity_and_zero_materialization` | yes | yes |
| A2-U02 | `a2_u02_doc_only_and_empty_lookup` | yes | yes |
| A2-U03 | `a2_u03_doc_id_and_frequency_errors_match_full` | yes | yes |
| A2-U04 | `a2_u04_all_positional_corruptions_match_full` | yes | yes |
| A2-U05 | `a2_u05_positional_hypothetical_budget` | yes | yes |
| A2-U06 | `a2_u06_full_reader_advance_and_phrase_unmodified` | yes | yes |
| A2-U07 | `a2_u07_lean_mixed_conversion_and_no_clones` | yes | yes |
| A2-U08 | `a2_u08_cancel_and_corrupt_unselected` | yes | yes |
| A2-U09 | `a2_u09_trailing_and_repeated_eof` | yes | yes |
| A2-U10 | `a2_u10_frequency_transport_for_work_charges` | yes | yes |

### 5.1 Malformed-byte differential parity table (same bytes, both modes)

Fixtures are hand-built with `ByteWriter` (no production encoder is modified to emit corruption). Every row compares the concrete typed error, not only its category.

| Fixture | Expected error (both modes) | Verified |
|---|---|---|
| duplicate second doc-id delta `0` | `NonMonotoneDocId { previous: 1, next: 1 }` | yes (first posting still returned) |
| second doc delta `u64::MAX` after doc `1` | `Corrupt { context: "postings", detail: "doc id overflow" }` | yes (first posting still returned) |
| first doc id `9` with `segment_doc_count = 5` | `Corrupt { context: "postings", detail: "doc id out of range" }` | yes |
| zero frequency | `ZeroFrequency { doc_id: 0 }` | yes |
| frequency `2` with `max_decoded_entries = 1` | `LimitExceeded { limit: 1, requested: 2 }` | yes (before alloc check) |
| `check_alloc` one byte below `2 * size_of::<Occurrence>()` | `LimitExceeded { limit: 79, requested: 80 }` | yes, identical Debug |
| second position delta `0` | `NonMonotonePosition { doc_id: 0 }` | yes |
| first / second `position_length = 0` | `Corrupt { detail: "zero position length" }` | yes |
| value index `1` then `0` | `Corrupt { detail: "value index decreased" }` | yes |
| `start_offset 2 > end_offset 1` | `Corrupt { detail: "start offset exceeds end offset" }` | yes |
| second position `u64::MAX` after position `1` | `Corrupt { detail: "position overflow" }` | yes |
| truncated final `end offset` | `Truncated { context: "end offset", needed: 1, available: 0 }` | yes |
| non-canonical 2-byte varint `0x82 0x00` | `InvalidVarint { context: "start offset" }` | yes |
| trailing byte after declared count | `Corrupt { context: "postings", detail: "1 trailing bytes" }` only on the EOF request | yes, after all declared postings |
| corruption only in the later, dead/nonwinning posting | same corruption error; no silent skip | yes (U08) |

### 5.2 Zero-materialization proof

`decode_observation::counts()` = `(positional_vector_reserves, cached_posting_clones)`.

* Three-posting positional lean read: `(0, 0)`.
* Same block through the full reader: both counters `> 0`.
* Full `next()` once then `into_doc_freq()`: `(1, 1)` and **unchanged** `(1, 1)` after finishing the lean reads — no extra reserve/clone after conversion, and the already-read posting is not re-emitted.

Independent source audit (`grep -n "clone()\|reserve\|Vec::with_capacity"` on `postings.rs`): the only occurrence-vector `reserve` and the only cached `Posting::clone` are inside the `Full` branch / `next_with`; the only other `clone()` is `advance_with`'s `current.clone()` (full API, unchanged).

### 5.3 Full-reader / EOF / advance / cancellation behaviour

* `next` → `advance(1)`/`advance(0)` return the cached current posting; `advance(4)`/`advance_with(7)` walk forward; `advance(99)` returns `None`; repeated `next` after EOF returns `None` repeatedly in both modes.
* Boundary cancellation is polled exactly once per attempted posting: two postings + EOF = 3 polls in both modes (no per-occurrence polling added).
* Cancel before first / after one posting / instead of EOF yields `SegmentError::Cancelled` with identical precedence in both modes.
* Doc-only blocks: `is_positional() == false`, empty occurrence vectors in the full reader, identical doc/freq sequence in the lean reader.

---

## 6. GREEN evidence — real production-path integration tests

| Test ID | File | Scenario | Result |
|---|---|---|---|
| A2-I01 | `crates/quervant-core/tests/segment_codec.rs` | `a2_i01_real_segment_docfreq_matches_full`: real `sample()` `SegmentBuilder` bytes → `SegmentReader::open`, content descriptor verified; two independent cursors (full + `into_doc_freq`) for `hello` (1 posting, positional) and `world` (2 postings); full reader supplies real positions; absent term → `None` | PASS |
| A2-I02 | `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` | `a2_i02_fs_term_prefix_phrase_and_generic_parity`: 12 real documents (`batch(12, \|i\| i % 3 + 1)`), real `FsDirectory` writer→commit→reopen, `UnifiedSearcher`; Term / Prefix `alp` / `And([term])` / Phrase `["alpha","alpha"]` / absent term; K10 vs K100; fresh `Index::open_existing` | PASS |

I02 exact expectations (derived independently from `i % 3 + 1`, not from the query):
`total_hits = 12` for term, prefix and generic Boolean, identical ordered keys and identical per-key `score.to_bits()`; phrase = exactly 8 hits (`k00001,k00002,k00004,k00005,k00007,k00008,k00010,k00011`), all scored; absent term = 0 hits; K10 = first 10 keys of K100 with matching score bits; reopen bitwise-identical.

### 6.1 Existing focused regression suites (final source)

| Suite | Result |
|---|---|
| `segment_codec` | PASS 25 |
| `segment_corrective` | PASS 24 |
| `pr15i_d2a_scoring_contract` | PASS 17 (includes A1 prepared-IDF cases + A2-I02) |
| `pr07_properties` | PASS 4 |
| `pr07_integration` | PASS 12 |
| `pr14_unified_mixed` | PASS 14 |
| `pr15h_b_sort_materialization` | PASS 6 |

The final-tree counts above include the two newly added integration tests (A2-I01 and A2-I02). The 24/16 counts in §1 are deliberately retained as **pre-change baseline** results.

Phrase/positional semantics, Boolean/generic fallback, candidate ledgers/work meters (`b4_u05`, `sc13`), cancellation (`sc12`), PIT/cursor, mutable/live and writer/reopen suites all ran inside the workspace runs below; none were skipped.

---

## 7. Mandatory local QA (final working tree)

Toolchains: `stable` (active) and `1.85.0` (MSRV). Coverage via `cargo llvm-cov`.

| # | Command | Result |
|---|---|---|
| 1 | `cargo fmt --all -- --check` | PASS (`cargo fmt --all` applied first; only in-scope new-code hunks reformatted — D17) |
| 2 | `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| 3 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| 4 | `cargo test --workspace --all-targets` | PASS — **2531 passed, 0 failed, 13 ignored** |
| 5 | `cargo test --workspace --all-targets --all-features` | PASS — **2576 passed, 0 failed, 94 ignored** (ignored = service/network-gated) |
| 6 | `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **line coverage 92.75%**, exit 0 |
| 7 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **line coverage 92.32%**, exit 0 |
| 8 | `cargo doc --workspace --no-deps` | PASS |
| 9 | `cargo doc --workspace --all-features --no-deps` | PASS |
| 10 | `cargo bench --workspace --no-run` (CI compile-only parity; **no** benchmark executed) | PASS |
| 11 | `cargo +1.85.0 fmt --all -- --check` | PASS |
| 12 | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| 13 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| 14 | `cargo +1.85.0 test --workspace --all-targets` | PASS |
| 15 | `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — **2576 passed, 0 failed, 94 ignored** |
| 16 | `git diff --check` | PASS |

Per-file coverage relevant to this change (`cargo llvm-cov report`): `segment/postings.rs` **94.38% lines / 100% functions**, `search/execute.rs` 96.81% lines, `search/score.rs` 92.96% lines.

`D24` did not trigger; `D23` did not trigger.

### 7.1 Hosted CI on the implementation head `359ab86` (PR #121, run `45262516891`)

| Job | Result | Duration |
|---|---|---|
| `rust` (all-features clippy + tests + all-features coverage + all-features docs + bench compile) | **pass** | 21m46s |
| `msrv` (`1.85.0` clippy/tests, all-features) | **pass** | 10m24s |
| `rustfs` (existing RustFS service integration) | **pass** | 2m39s |
| `benchmark-adapter-contract` | **pass** | 1m31s |
| `python-benchmark-framework` | **pass** | 3m45s |

`git diff --check` note: the only whitespace diagnostics in the staged tree are the nine Markdown
hard-break trailing spaces inherited verbatim from the approved plan copy
(`PERF06A2_DETAILED_PLAN.md`); the already-merged `PERF06A1_DETAILED_PLAN.md` carries the identical
nine lines. `git diff --check` over the code paths and over this report is clean.

---

## 8. Applied exception-matrix rows

| Row | Trigger observed | Action taken |
|---|---|---|
| D02 | PR #120 MERGED; `origin/main` blobs equal the A1 fixup blobs | AUTO-RESOLVE: recorded merge/main SHA and exact blobs, created clean A2 branch |
| D05 | Exactly four doc/freq consumer loops + one protected phrase loop | AUTO-RESOLVE: converted C1–C4 only |
| D06 | `SegmentReader::postings`/`postings_for_entry` return the existing cursor | AUTO-RESOLVE: converted locally; `reader.rs` untouched |
| D07 | positional `check_alloc::<Occurrence>(freq)` precedes parsing | AUTO-RESOLVE: preserved in both modes (U05) |
| D08 | `advance_with` relies on `current: Option<Posting>` clone | AUTO-RESOLVE: retained full clone; only lean omits it (U06) |
| D09 | conversion after a full read in a test | AUTO-RESOLVE: cached clone cleared, next unread record emitted (U07) |
| D10 | six checked occurrence components/relationships exist | AUTO-RESOLVE: all parsed in the shared helper; branch only on `reserve`/`push` (U04) |
| D11 | `build_phrase` needs `Posting.occurrences` | AUTO-RESOLVE: phrase kept on the full cursor (I02, U06) |
| D13 | malformed positional records required | AUTO-RESOLVE: raw `ByteWriter` fixtures; encoder untouched (U04) |
| D17 | `cargo fmt` reformatted only new in-scope hunks | AUTO-RESOLVE: kept, recorded |
| D19 | RED failure was solely the missing API | AUTO-RESOLVE: preserved RED output, implemented, continued |
| D22 | in-scope formatting/clippy adjustments | AUTO-RESOLVE: bounded mechanical fixes; no suppressions added except the plan-mandated `#[allow(clippy::should_implement_trait)]` on the domain cursor's `next` |
| D29 | RustFS not started although no remote contract changed | AUTO-RESOLVE: local `FsDirectory` real integration + existing hosted CI job preserved |

**D04 note:** a zero-commit local placeholder branch `dev/perf06-a2` existed; see §1. It contained no work, was neither modified nor deleted, and the prescribed branch name was used. This is disclosed rather than treated as a silently-overwritten branch.

No `HARD STOP` row (D03, D12, D14–D16, D27, D28, D30, D31, D32) triggered.

---

## 9. Out-of-scope audit

* **No** index/segment/manifest/dictionary/norms/schema/feature-id/wire-format change; encoder and every persisted byte layout are untouched (INV-09).
* **No** skip index, positional compression, separated streams or partial/range caching (A3 scope).
* **No** BM25/A1 redesign; prepared-IDF code and all scoring formulas are byte-identical outside the four conversion lines (D30 not triggered; SC suite scores bit-equal).
* **No** `TermPostings`, B1–B5 dispatch, score-buffer ownership or evaluator rewrite (PERF-05 preserved).
* **No** new `SegmentReader` factory, cache, global/static state or durable state; the new view owns only a query-local cursor.
* **No** benchmark/profiling/timing acquisition, Criterion, cross-engine comparison, process-cold study or RustFS startup.
* **No** new dependency, module, trait or generic framework.
* **No** merge, no A3 work, no force push.

---

## 10. Unresolved failures and residual risks

| Item | State |
|---|---|
| Local mandatory gates | All PASS (§7) |
| Hosted CI on the implementation head `359ab86` | All five jobs PASS (§7.1); the evidence-doc commit that records them is docs-only |
| RustFS / ignored service-gated tests | Not run locally by design (A2 changes no remote contract; D29). Existing hosted jobs remain the baseline evidence. |
| Performance claim | **None.** A2 has no speedup acceptance gate; warm qualification is PERF-06-A4. |
| `DocFreqPostingsReader` lacks `advance`/`posting_doc_count` | Intentional (no observed consumer); adding them later is a separate plan. |
| Local placeholder branch `dev/perf06-a2` | Retained untouched; see §1 disclosure. |

---

## 11. Typed disposition

`PERF06_A2_IMPLEMENTED_READY_FOR_INDEPENDENT_REVIEW` — implementation, unit/integration tests,
both toolchains, workspace coverage, docs and hosted CI on the implementation head all pass.
The PR (`#121`) is a **draft**, targets `main`, was published without force and is **not**
merged; A3 has not been started. Independent review remains outstanding and is required before
any merge decision.
