# PR 7 adversarial review

## Scope

Adversarial review of the PR 7 lexical executor, its resource bounds and its
read-only integration with PR 5/6. This review records plausible remaining
failures and their dispositions.

## Plausible failure modes and dispositions

| # | Plausible failure | Finding | Disposition |
|---|---|---|---|
| 1 | Score inflation from repeated clauses | Duplicate `Term`/`Phrase` clauses are interned into one compiled leaf and scored once. Verified by `u15` and `plan::duplicate_clauses_share_a_leaf`. | Closed |
| 2 | Phrase matches across multi-valued field boundaries | Chains require an identical `value_index`; verified by `u10`, `phrase::multi_value_boundaries_are_never_bridged`, `p02`. | Closed |
| 3 | Stopword holes collapse adjacency | Components are concatenated and analyzed once, preserving analyzed positions; verified by `u08`. | Closed (documented v1 semantics) |
| 4 | Directory/term scan blow-up | Field-length and document-frequency preparation scans the field dictionary and postings; bounds `max_dictionary_terms_examined`, `max_scanned_posting_occurrences`, `max_field_length_entries/bytes` and `max_total_work_units` fail closed. Verified by `f07`, `f08`. | Closed for safety; see performance note |
| 5 | Unsupported subtree silently skipped | Compilation rejects unsupported operators before any segment is opened; the sweep test covers every contract variant. | Closed |
| 6 | Partial results on budget exhaustion | Errors propagate and no response is returned; RAII drops guarded readers and reservations. Verified by `f12`. | Closed |
| 7 | Cancellation ignored on no-match/large-universe paths | `SearchWork` polls cancellation around `MatchAll`, `Not` complement, dictionary scans and posting loops. Verified by `f09`, `f10`. | Closed |
| 8 | Snapshot mutated by search | The searcher borrows an immutable `ReaderSnapshot` and never calls writer/commit APIs. Verified by `i04`. | Closed |
| 9 | Duplicate committed keys silently resolved | Merge detects a repeated live key and returns `CorruptIndex`. Not reachable through the writer; covered defensively. | Accepted residual gap |
| 10 | `InvalidScore` path never observable | Non-finite scores are rejected by construction; `bm25` unit tests cover `df > n` and non-finite paths. | Open (test-only) |
| 11 | Phrase concatenation semantics differ from a future conjunction-of-terms contract | Documented; PR 8 owns multi-term operators. | Accepted |
| 12 | Field-length rescan cost is pathological | Measured below; no format change is made without approval. | Accepted residual risk |

## Microbenchmark baseline

Representative release run on the development machine (`cargo run --release -p
quervant-core --example pr07_bench`), synthetic 2,000-document corpus in 4
segments (8 whitespace tokens per document), correctness-gated against a naive
oracle before timing:

| Workload | p50 | p95 | p99 |
|---|---|---|---|
| term | 6.8 ms | 8.2 ms | 9.2 ms |
| and | 6.4 ms | 7.4 ms | 9.7 ms |
| or | 7.6 ms | 9.3 ms | 11.7 ms |
| phrase | 7.0 ms | 9.4 ms | 11.6 ms |
| match_all | 4.5 ms | 5.5 ms | 6.9 ms |
| pure_negative | 8.9 ms | 11.6 ms | 14.7 ms |

Dispatch comparison over a 1,000,000-element postings cursor (concrete
`VecCursor` traversal vs `EnumCursor` vs `&mut dyn Cursor`), 100 rounds:

| Strategy | p50 | p95 | p99 |
|---|---|---|---|
| concrete | 335.7 us | 617.2 us | 1482.6 us |
| enum | 265.1 us | 523.5 us | 724.2 us |
| dyn | 232.3 us | 462.2 us | 790.2 us |

The dispatch differences are within run-to-run noise and do not establish that
any strategy is faster. Per `AGENTS.md`, no performance claim is made; the
executor keeps its concrete/enum compiled representation. PR 15 owns the full
comparative harness (RSS, allocations, cold/warm, Tantivy/Lucene). The release
example binary is 1,879,776 bytes (1.8 MiB).

The query latencies are dominated by the approved v1 O(indexed postings)
field-length recomputation (no on-disk norms) plus per-query segment reopening.
This is the explicitly prescribed reference behaviour in D07-04 ("expensive but
correct v1 reference implementation"). A norms format would be a separately
approved PR 5 format extension; it is **not** introduced here.

## Residual risks accepted

1. Duplicate live keys are detected during merge rather than eagerly; the writer
   prevents the state, and the defensive path is typed.
2. The `InvalidScore` guard is defensive and not reachable through the public
   API for well-formed statistics.
3. Phrase position semantics are the documented PR 7 v1 policy (single
   tokenization boundary across components).
4. No allocations/RSS measurement in PR 7; deferred to PR 15.

## Amendment 01 adversarial review

### Corrected defects and counterexamples

| # | Defect / counterexample | Correction | Evidence |
|---|---|---|---|
| 1 | `NOT(AND(alpha,beta))` scored `{alpha}`/`{beta}` positively | Odd-`Not` leaves are excluded from scoring; membership unchanged | S01/S02/S04/S07 |
| 2 | Two segments each within the per-segment bound were cumulatively rejected | Per-segment peak entries reset between segments | B01–B05 |
| 3 | `max_scanned_posting_occurrences` was not enforced independently | Cumulative scanned counter rejects one-over | F01 |
| 4 | Heap replacement could grow `bytes` past the bound unchecked | Replacement total checked before mutation | H01/H02 |
| 5 | Field-length occupancy used `*slot == 0` rather than entry state | Explicit `HashMap::Entry` handling | L03 |
| 6 | Segment temporaries were unaccounted against the byte budget | `CandidateBudget` tracks segment + global bytes atomically | B07, budget unit tests |

### Residual risks (amendment)

1. Byte figures are deterministic **logical accounting units**, not exact
   allocator/RSS measurements; Rust's allocator still governs OOM.
2. `match_phrase`'s internal scratch `Vec`s are not separately charged (the
   occurrence map and match reservation dominate and are charged).
3. The field-length recomputation remains O(indexed postings) per query and is
   deliberately deferred to separately approved performance/format work.
4. No RustFS validation (local-only PR 7); no WAND/streaming execution.
5. Duplicate-live-key detection still happens during merge.

### Post-amendment benchmark (appended, not replacing the baseline)

Same `pr07_bench` corpus and methodology as the baseline above; release build on
2026-10-14.

| Workload | p50 | p95 | p99 |
|---|---|---|---|
| term | 6.4 ms | 10.3 ms | 12.7 ms |
| and | 6.0 ms | 6.4 ms | 6.5 ms |
| or | 6.3 ms | 7.0 ms | 7.1 ms |
| phrase | 6.0 ms | 6.9 ms | 7.2 ms |
| match_all | 4.1 ms | 4.8 ms | 4.9 ms |
| pure_negative | 4.1 ms | 4.3 ms | 4.3 ms |

Pure-negative is materially faster than the baseline (4.1 ms vs 8.9 ms p50)
because negative-only fields are no longer scanned for BM25 statistics. Other
differences are within microbench noise and are not presented as regressions or
performance proof. Dispatch p50: concrete 167.1 us, enum 171.6 us, dyn
157.4 us — still inconclusive; no speed claim is made.

## Amendment 02 adversarial self-review

### Challenged faults and dispositions

| Plausible fault | Finding |
|---|---|
| Transfer counters updated before validation | `transfer_segment_to_global` validates entries/bytes/overflow and computes all new values before committing any counter; `a2_04` asserts unchanged counters on rejection. |
| Batch double-charged on insertion | `execute_search` drains a `SegmentResults` already charged to `global_bytes` and never calls a reserve for it. |
| Batch uncharged between segment and global | `execute_segment` transfers before `finish()` and before returning; `finish` now errors on any residual reservation. End-to-end acceptance cannot distinguish this transient (segment checks dominate); primitive `a2_01`/`a2_05` cover it. |
| Phrase scratch retained across sibling leaves | `build_phrase` releases scratch after `drop(distinct)`; `a2_02` fails on `161cf5e` and passes after. |
| `ReservedSet::release` releases before drop | `release` destructures, `drop(set)` first, then releases. |
| `Or::append` miscounts moved entries | Reserve `next.entries` for growth, release only the unused delta, then release the consumed `next` reservation; `a2_08` checks set algebra and peaks. |
| Result vector double-released on cancellation | Early return drops the ledger, which releases outstanding segment charges exactly once; `a2_09` reuses the snapshot afterwards. |
| Checked arithmetic overflow | `a2_04`/`a2_07` cover transfer and `Charges` overflow atomically. |
| Duplicate key abort leaves partial response | The whole request aborts with `CorruptIndex`; no response is returned. |
| Zero-result paths spuriously charge | Empty live sets / empty matches reserve zero entries and release immediately; existing empty-index and pure-negative suites pass. |
| Ranking changes from reordered drops | No scoring path changed; `a2_11`, `a2_12` and all S/U/I/P suites pass. |

### Residual risks (amendment 02)

1. Logical accounting is not exact RSS or allocator capacity; OOM remains
   governed by Rust's allocator.
2. `match_phrase` internal scratch vectors are not individually byte-charged
   (bounded deterministic work; disclosed, not hidden as exact memory bounds).
3. Field-length recomputation remains O(indexed postings).
4. No RustFS/WAND/streaming scope; duplicate-key detection still occurs during
   merge.

### Post-Amendment-02 benchmark (appended)

`cargo run --release -p quervant-core --example pr07_bench`, 2026-10-14, same
corpus/methodology: term p50 6.25 ms / p99 6.71 ms; and 6.20 / 6.66; or 6.19 /
6.89; phrase 5.80 / 6.92; match_all 4.06 / 4.62; pure_negative 3.94 / 4.56.
Dispatch concrete 163.4 us, enum 164.5 us, dyn 160.9 us (inconclusive). These
are within microbench noise of Amendment 01; no performance claim is made.

## Amendment 03 adversarial self-review

### Challenged faults and dispositions

| Plausible fault | Finding |
|---|---|
| Budget mutated before ledger validation | `checked_*` compute the complete `LedgerState` (budget + ledger + consistency) before `commit`; T02–T04 assert unchanged state. |
| Direct release partially updates | `release_segment` validates both subtractions into locals before assigning; T01. |
| Failed op corrupts a later op/finish/Drop | T06/T08 plus the seeded T07 model assert recovery and cleanup. |
| Phrase scratch allocated before charge | Every bounded vector reserves its fixed capacity through `PhraseScratch::reserve` before `try_reserve_exact`; P01/P02. |
| Sibling scratch retained | `build_phrase` drops the scratch guard before returning; `match_phrase` releases per-phase; P04, `a2_02`. |
| Old/new intersection buffers double-released | The new reservation is live before the old vector is dropped and its charge released; P02. |
| `Or::append` miscounts | Unchanged `eval_node` accounting remains covered by `a2_08`. |
| Retained `term_freqs` double-charged | Output is capacity-bounded but charged only by the caller's `PHRASE_MATCH*` reservation; P12. |
| Error/cancellation leaks scratch | `PhraseScratch` per-phase release plus `Drop`; `phrase_scratch_returns_to_zero`, P06, P07. |
| Checked overflow | T05 plus `Charges`/`bytes_for_count` checked arithmetic. |
| Ranking changes from reordered drops | No scoring path changed; P08–P10 and all S/U/I/P suites pass. |

### Residual risks (amendment 03)

1. Scratch/byte figures are conservative **logical** units, not allocator-exact
   RSS or capacity; OOM remains governed by Rust's allocator.
2. `match_phrase` scratch is now charged, resolving the prior Amendment 02
   residual risk; the units remain estimates.
3. Field-length recomputation remains O(indexed postings).
4. No RustFS/WAND/streaming scope; duplicate-key detection still occurs during
   merge.

### Post-Amendment-03 benchmark (appended)

`cargo run --release -p quervant-core --example pr07_bench`, 2026-10-14: term
6.45 / 8.37 ms (p50/p99); and 6.22 / 6.96; or 7.34 / 9.46; phrase 6.52 / 8.51;
match_all 4.17 / 5.30; pure_negative 4.10 / 5.70. Dispatch concrete 169.2 us,
enum 167.2 us, dyn 164.8 us. Within noise; no performance claim is made.

## Amendment 04 adversarial review

Measurement infrastructure only; no production code changed.

| Plausible fault | Disposition |
|---|---|
| Benchmark times setup, not the operation | Fixtures built and oracle-checked before groups; A4-T13; each `b.iter` is one `search` |
| Oracle is wrong / tautological | Independent token-list oracle; A4-T12 proves a wrong expectation aborts |
| Synthetic stand-in for real codec | `postings`/`dictionary` use the production `SegmentReader`/codec via public APIs |
| `bm25` bench pretends to measure production | Labeled reference-arithmetic **control**; production scoring measured end-to-end in `search` |
| Private API exposed to enable a benchmark | None exposed; private `bm25`/`compute_stats` remain private |
| Profiler missing but reported PASS | `profile-pr07.sh` exits 2 with `UNAVAILABLE`; A4-T10 |
| Baseline overwritten | SHA+timestamp run dirs, disambiguated on collision; A4-T14; raw data untracked |
| Manifest invents numbers | Report generated only from the executed `dad2514` run; validator A4-T15 |
| Criterion breaks MSRV | 0.7.0 pinned and `cargo +1.85.0 bench --no-run` verified; A4-T09 |
| Competitive claim from Quervant-only run | No competitor run; ratio policy documented (A4-T16) |
| Selection of a misleading "rare" term | Rare sentinel injected in exactly one known document; counts asserted |
| Cross-environment extrapolation | Policy forbids it; absolute host-specific latencies recorded |

### Residual risks (amendment 04)

1. `perf`/flamegraph/heaptrack unavailable; `compute_stats` attribution is a
data-supported hypothesis (selectivity insensitivity, `MatchAll` isolation), not
a symbol-level CPU profile — classified **BLOCKED**, not PASS.
2. Absolute timings are WSL2/host-specific.
3. No allocation counts.
4. No Lucene/Tantivy adapters or ratios (PR 15).
5. 25% tombstone lane NOT APPLICABLE for insert-only PR 7 (PR 9); 1M extended lane
unmeasured.

### Baseline observation

Clean-tree `dad2514`: 2K scored term queries cost ~7.3–8.5 ms almost independent
of selectivity while `MatchAll` costs ~5.3 ms; at 100K, `term-rare` (327 ms) and
`term-common` (394 ms) differ by ~20% despite a ~1000× hit-count difference. This
supports, but does not directly prove, that the unconditional `compute_stats`
posting scan dominates. Amendment 05 owns the optimization; Amendment 04 claims
no improvement.
