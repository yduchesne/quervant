# M3 — Atomic delete by query: implementation evidence

**Status: IMPLEMENTED — local and real-RustFS qualification PASS; final-SHA CI
pending. Not DONE, not marked complete, and not ready to merge without explicit
human authorization.**

- Branch: `dev/m3-delete-by-query`
- Baseline: `bea042fea2ed106ae014c13fca0773fe49436fc7` (`origin/main` at branch
  start); PR #50 merge `874ac40b9e2b2948306be03c102f034e2275bc56` is an ancestor
- M3 implementation commit: `dcabb7e` (`feat(m3): implement atomic delete by query`)
- M3 R-01 fixup commit: `ef58f7f` (`perf(m3): stream non-scoring query membership`)
- Pre-fix R-01 baseline: `437d775`
- Evidence report commit: the commit containing this file; final local HEAD is
  the evidence-report commit, not CI-verified
- Host: Linux x86-64; stable `rustc 1.98.1`; MSRV `rustc 1.85.0`
- Plan: `QUERVANT_M3_DETAILED_IMPLEMENTATION_PLAN.md`

## 1. M3-AD09 resolution (approved)

The first execution of the plan stopped on `M3-AD09`: the durable whole-batch
fingerprint encoded only `max_matches` and `expected_generation` for a
`MutationTarget::Query`, never `selector.query`. The original reproduced
collision was:

```text
Query::MatchAll + max_matches=7 + expected_generation=Some(3)
Query::Term{field:"f", value:"x"} + max_matches=7 + expected_generation=Some(3)
  -> identical fingerprint
```

**Approved resolution (Option 1).** Batches containing at least one query target
use a versioned, domain-separated v2 query fingerprint domain
(`quervant.mutation.batch.fingerprint.v2.query`). The query branch now appends a
canonical encoding of the complete query AST. Explicit-key-only batches keep the
exact v1 domain and bytes. `BatchReplayRow.fingerprint` storage and the v2
mutation-state format are reused unchanged.

Post-fix negative regression tests:

- `index::mutation_state::m1_rejection_tests::query_fingerprint_no_longer_collides_across_distinct_asts`
- `index::mutation_state::m1_rejection_tests::explicit_key_only_fingerprints_are_byte_compatible`
- `index::mutation_state::m1_rejection_tests::query_fingerprint_is_domain_separated_from_explicit_key_fingerprints`
- `search::unified_cursor::tests::every_query_variant_is_encoded_deterministically_and_distinctly`
- `search::unified_cursor::tests::nested_values_preserve_raw_ast_order_and_bits`
- integration replay/conflict tests in `tests/m3_delete_by_query.rs` (T14/T16/T21/T25)

### 1.1 Query variant-to-encoding traceability

The canonical encoder is the existing unified-cursor AST encoding
(`search/unified_cursor.rs`), exposed crate-internally as
`encode_canonical_query`. It uses explicit variant tags, length-prefixed strings,
ordered arrays, JSON member order, polygon ring order and IEEE bit patterns. It
performs no semantic normalization. All variants are encodable losslessly and
deterministically; no `M3-AD09` encoding STOP remains.

| # | `Query` variant | Tag | Encoded payload | Test |
|---|---|---|---|---|
| 1 | `MatchAll` | 1 | tag only | `every_query_variant_is_encoded_deterministically_and_distinctly` |
| 2 | `Term` | 2 | field, `FieldValue` | same + `nested_values_preserve_raw_ast_order_and_bits` |
| 3 | `Phrase` | 3 | field, ordered terms | same |
| 4 | `Prefix` | 4 | field, prefix | same |
| 5 | `Glob` | 5 | field, pattern | same |
| 6 | `Regex` | 6 | field, pattern | same |
| 7 | `Fuzzy` | 7 | field, value, max_edits, transpositions | same |
| 8 | `Range` | 8 | field, lower `Bound`, upper `Bound` | same |
| 9 | `TimeRange` | 9 | field, start/end `Timestamp` micros | same |
| 10 | `Exists` | 10 | field | same |
| 11 | `Missing` | 11 | field | same |
| 12 | `IsNull` | 12 | field | same |
| 13 | `In` | 13 | field, ordered values | same |
| 14 | `NotIn` | 14 | field, ordered values | same |
| 15 | `IpExact` | 15 | field, tagged IPv4/IPv6 octets | same |
| 16 | `IpRange` | 16 | field, start/end IP | same |
| 17 | `IpInCidr` | 17 | field, IP + prefix | same |
| 18 | `IpNotInCidr` | 18 | field, IP + prefix | same |
| 19 | `JsonPathEquals` | 19 | field, path segments, value | same + nested-order test |
| 20 | `JsonPathExists` | 20 | field, path segments | same |
| 21 | `JsonPathRange` | 21 | field, concrete path, bounds | same |
| 22 | `JsonPathArrayContains` | 22 | field, concrete path, value | same |
| 23 | `GeoBoundingBox` | 23 | west/south/east/north f64 bits | same |
| 24 | `GeoRadius` | 24 | center lon/lat, meters | same |
| 25 | `GeoPolygon` | 25 | outer ring, ordered holes | same |
| 26 | `And` | 26 | ordered children | same + nested-order test |
| 27 | `Or` | 27 | ordered children | same |
| 28 | `Not` | 28 | child | same |

Nested value encodings: `FieldValue` tags 1–11 (Text, Keyword, Bool, I64, U64,
F64 bits, Timestamp micros, Json, GeoPoint, Ip, Cidr); `Bound` tags 0–2
(Unbounded/Included/Excluded); `JsonValue` tags 0–5 with ordered object entries
and tagged numeric representation; `JsonPathSegment` tags 0–2
(Member/Index/Wildcard); `IpNetwork` = tagged IP + prefix byte. No variant lacks a
deterministic lossless encoding.

## 1A. M3 R-01 fixup — streaming non-scoring membership

**Pre-fix baseline:** `437d775` (the branch state reviewed by the fixup plan).
R-01 was verified by source inspection: `UnifiedSearcher::select_keys` called
`execute::evaluate_lexical_with`, which built a full per-segment matched set,
called `score_segment`, and returned every scored match before selection applied
the first-over-limit test. This was an efficiency defect, not a demonstrated
correctness failure.

**Fixup.** Added `execute::VisitControl` and
`execute::visit_lexical_membership_with`, a callback-driven traversal that reuses
the same `SegmentCandidateLedger`, `build_leaf_data`, `SearchWork`, effective-live
set, cancellation checks and per-document examination charges as
`evaluate_lexical_with`. The visitor does not construct a matched set, does not
call `score_segment`, and does not materialize a scored vector. `select_keys` now
passes the existing `evaluate_unified` predicate and performs key extraction,
`seen` deduplication, `limit+1` detection, candidate-byte charging and selection
inside `on_match`; it returns `Stop` on the first distinct over-limit key.

**FD-04:** `compute_stats` is still executed intentionally (`_stats`), preserving
work/cancellation accounting. Removing it remains a separately approved follow-up.
**EX-01 adaptation:** `on_match` receives the already-borrowed shared
`CandidateBudget` in addition to the document id. This is required to preserve one
combined candidate budget rather than a separate-budget cap bypass; no public API,
scored evaluator, fingerprint, mutation-state format or writer phase ordering
changed.

### 1A.1 Fixup acceptance traceability

| ID | Scenario / oracle | Test evidence |
|---|---|---|
| T01 | Small single-segment MatchAll, exact sorted keys | `m3_t05_multiple_segments_and_versions_dedupe_by_logical_key`, `m3_t06_more_than_page_size_is_not_truncated` |
| T02 | Mixed Term/Boolean/typed/JSON/geo expected keys | `m3_t03_complete_membership_for_mixed_predicates`, `m3_t04_bbox_and_json_predicates_are_exact` |
| T03 | One segment, many more than limit | `m3_fixup_t03_one_segment_limit_plus_one` |
| T04 | Duplicate physical versions / live mask | `m3_t05_multiple_segments_and_versions_dedupe_by_logical_key` |
| T05 | First extra match in a later segment | `m3_fixup_t05_over_limit_in_later_segment` |
| T06 | Callback stops on first over-limit distinct match; no scoring | `select_keys_stops_at_first_over_limit_distinct_match`; source review confirms no `score_segment` call in `visit_lexical_membership_with` |
| T07 | Zero writer bound with zero/one match | `m3_t08_zero_writer_bound_and_cumulative_batch_bound`, `m3_t13_zero_match_is_a_replayable_noop` |
| T08 | Exact-at-limit and reordered segments | `m3_t07_selector_and_writer_bounds_fail_closed`, `m3_t26_writer_query_bound_exact_and_one_over` |
| T09 | Low candidate bytes/entries/work budget | `select_keys_obeys_candidate_budget_and_mid_selection_cancellation`, `m3_t19_response_and_replay_limits_reject_whole_batch`, `m3_t20_cumulative_query_keys_bound_fails_before_installation`, `m3_t27_replay_key_bound_fails_closed`, `m3_t28_query_depth_budget_is_not_bypassed` |
| T10 | Cancellation before/during selection | `m3_t18_cancellation_and_query_validation_are_atomic`, `select_keys_obeys_candidate_budget_and_mid_selection_cancellation` |
| T11 | Pending/flushed newer writer revision | `m3_t10_pending_and_flushed_newer_revision_conflict` |
| T12 | Explicit mutation followed by overlapping query delete | `m3_t11_earlier_explicit_command_and_overlapping_selectors_conflict` |
| T13 | Query AST changes under reused replay token | `m3_t14_same_token_with_different_query_conflicts_before_selection` |
| T14 | Matching durable replay after reopen / changed generation | `m3_t16_filesystem_commit_reopen_and_replay`, `m3_t25_replay_does_not_rerun_selector_after_query_changes` |
| T15 | Explicit-only v1 fingerprint goldens | `explicit_key_only_fingerprints_are_byte_compatible` |
| T16 | M2 shrink/equal-size/Unset at document-byte limit | `m2_f01_t11_late_over_limit_update_rejects_whole_batch_and_retries`, `m2_f01_t12_exact_limit_shrink_commits_and_reopens_with_queries`, `m2_f01_t13_exact_limit_update_replays_after_reopen` |
| T17 | M2 patch failure after earlier prospective mutation | M2 suite failure-atomicity tests; `m3_t12_late_failure_rolls_back_and_retry_succeeds` |
| T18 | Scored unified search unchanged | `pr14_unified_mixed`, `pr14_unified_cursor`, existing `c3_*` scored tests |
| T19 | Scored search cancellation/budget unchanged | existing `d_json_cancellation_cleanup` and scored budget tests |
| T20 | Local filesystem commit/reopen/PIT/old generation | `m3_t15_pit_and_previous_generation_are_immutable`, `m3_t16_filesystem_commit_reopen_and_replay` |
| T21 | Real RustFS M3, M1/M2, PR13 regressions | Three M3 real-RustFS runs; M1/M2 real-RustFS; PR13 remote/oracle/oracle_geo |

### 1A.2 Correctness-gated large-match workload

Temporary release-mode probe (removed after measurement): 9,000 documents in one
committed segment, lexical term query matching every document, selector
`max_matches = 50`, expected `MatchLimitExceeded { limit: 50, matched: 51 }`.
Each run used the same writer and the rejected batch left no state.

| Tree | Run 0 | Run 1 | Run 2 | Scoring invoked? |
|---|---|---|---|---|
| Pre-fix `437d775` | 27 ms | 28 ms | 28 ms | Yes (`score_segment` over the full matched set) |
| Fixup tree | 6 ms | 6 ms | 6 ms | No (`visit_lexical_membership_with`, early stop) |

Peak observed memory was not instrumented; this is **not** a formal speedup claim.
Pre-match setup (`compute_stats`, expansion, live-set construction) remains
bounded by existing search limits (RISK-A/B below).

## 2. Implementation summary

| File | Change |
|---|---|
| `crates/quervant-core/src/search/unified_cursor.rs` | Exposed the existing canonical query-AST encoder crate-internally; added all-variant encoding tests. |
| `crates/quervant-core/src/search/execute.rs` | Added the private `VisitControl` and `visit_lexical_membership_with` streaming membership traversal; scored `evaluate_lexical_with`/`score_segment` remain unchanged. |
| `crates/quervant-core/src/search/unified.rs` | Added the private `UnifiedSearcher::select_keys` complete-membership visitor. R-01 fixup rewires it to `execute::visit_lexical_membership_with`; it reuses compiled plan, expansion, BM25 statistics, typed/JSON/geo predicates and stops at the first distinct over-limit key. |
| `crates/quervant-core/src/search/mod.rs` | Crate-internal re-exports for the encoder and `CompleteKeySelection`. |
| `crates/quervant-core/src/index/query_selection.rs` | New private adapter: committed-snapshot selection, search-error mapping, committed mutation-state revision evidence, complete/limit outcome. |
| `crates/quervant-core/src/index/mutation_state.rs` | Versioned query fingerprint domain + canonical query encoding; compatibility and collision tests. |
| `crates/quervant-core/src/index/writer.rs` | Query+Delete preflight; replay-before-generation/selection; one committed snapshot for all selectors; cumulative key bounds; selection-revision/overlap conflict checks; `delete_by_query` convenience. |
| `crates/quervant-core/src/index/limits.rs` | `max_query_matches` default 1,024, getter and non-clamping builder; tests. |
| `crates/quervant-core/src/contract/mutation.rs` | Contract docs activate query-delete only; query update/upsert reserved for M4. |
| `crates/quervant-core/src/remote/mod.rs` | `RemoteIndexWriter::delete_by_query` thin local delegation; no admission-time remote I/O. |
| `crates/quervant-core/tests/m3_delete_by_query.rs` | M3 integration, adversarial, filesystem, fake-remote, seeded-model and ignored real-RustFS tests. |
| `.github/workflows/ci.yml` | Named M3 real-RustFS step, three independent runs. |
| `docs/ARCHITECTURE.md`, `docs/ROADMAP_V01.md` | M3 architecture section; M2 marked DONE; M3 marked implemented but not DONE. |

No segment, manifest, mutation-state, `CURRENT`, cursor or remote-cache wire
format was changed. Replay uses the existing fingerprint field and bounded
response encoding.

## 3. Invariant and test traceability

| Plan ID | Observable invariant | M3 test(s) |
|---|---|---|
| M3-I01 | Query+Delete only; other query actions typed-rejected | `m3_t01_query_delete_only`; M1 raw-preflight unit tests |
| M3-I02 | One committed batch-initial snapshot | `m3_t02_committed_selection_excludes_pending_and_volatile_changes`; `m3_t11...disjoint` |
| M3-I03 | Exact complete logical-key membership, no duplicates/truncation | `m3_t03_complete_membership_for_mixed_predicates`; `m3_t04_bbox_and_json_predicates_are_exact`; `m3_t05_multiple_segments_and_versions_dedupe_by_logical_key`; `m3_t06_more_than_page_size_is_not_truncated` |
| M3-I04 | Limits fail closed with no partial success | `m3_t07_selector_and_writer_bounds_fail_closed`; `m3_t08_zero_writer_bound_and_cumulative_batch_bound`; `m3_t19_response_and_replay_limits_reject_whole_batch`; `m3_t20_cumulative_query_keys_bound_fails_before_installation`; `m3_t26_writer_query_bound_exact_and_one_over`; `m3_t27_replay_key_bound_fails_closed`; `m3_t28_query_depth_budget_is_not_bypassed` |
| M3-I05 | Committed generation precondition | `m3_t09_generation_precondition` |
| M3-I06 | Stale writer revision cannot be deleted | `m3_t10_pending_and_flushed_newer_revision_conflict`; `m3_t11_earlier_explicit_command_and_overlapping_selectors_conflict` |
| M3-I07 | All-or-nothing tombstones and revision allocation | `m3_t12_late_failure_rolls_back_and_retry_succeeds`; `m3_t16_filesystem_commit_reopen_and_replay`; `m3_t21_convenience_api_and_durable_replay` |
| M3-I08 | Zero matches = no-op, no revisions, replayable | `m3_t13_zero_match_is_a_replayable_noop` |
| M3-I09 | PIT and previous generation immutable | `m3_t15_pit_and_previous_generation_are_immutable`; `m3_t16...` |
| M3-I10 | Durable replay does not rerun selector | `m3_t13...`; `m3_t14_same_token_with_different_query_conflicts_before_selection`; `m3_t25_replay_does_not_rerun_selector_after_query_changes` |
| M3-I11 | Remote path identical, admission no I/O | `m3_t23_remote_admission_makes_no_remote_calls_and_replays_after_reopen`; ignored `m3_t24_real_rustfs_delete_by_query_reopen_and_replay` |
| M3-I12 | Existing explicit-key/M2 semantics unchanged | unchanged M1/M2 suites (`m1_batches`, `m2_patches`) PASS |

Additional independent oracle: `m3_t22_seeded_reference_model_sequence` uses
fixed seed `0x5EED_0003`, 24 bounded steps over an independent
`BTreeMap<String, (revision, live)>` model and manually defined group predicates.
No mismatch occurred; no minimized failing sequence exists.

## 4. Local command evidence

| Command | Result |
|---|---|
| `cargo test -p quervant-core --all-features --test m3_delete_by_query` | PASS — 29 passed, 0 failed, 1 ignored (real RustFS) |
| `cargo test -p quervant-core --all-features --test m1_batches` | PASS — 14 passed, 0 failed, 1 ignored |
| `cargo test -p quervant-core --all-features --test m2_patches` | PASS — 10 passed, 0 failed, 1 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS (all suites; no failures) |
| `cargo test --workspace --all-targets` | PASS (all suites; no failures) |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — workspace line coverage **91.66%** (46,441 lines; 91.04% region coverage) |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 script tests |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS (all suites; no failures) |
| `git diff --check` | PASS |

### 4.1 Explicit-key batch timing sanity

A temporary release-mode probe (removed after measurement) applied the same
100 × explicit 64-key `Delete` batch to a fresh in-memory writer, three times
per tree, on the pre-M3 baseline and the M3 tree:

| Tree | Run 0 | Run 1 | Run 2 |
|---|---|---|---|
| Pre-M3 `52af5ff` | 34 ms | 37 ms | 37 ms |
| M3 tree | 34 ms | 36 ms | 36 ms |

No meaningful regression is claimed or observed; the task does not claim an
improvement. Full performance/fault characterization remains M5.

## 5. Real RustFS qualification

The test `real_rustfs::m3_t24_real_rustfs_delete_by_query_reopen_and_replay` is
`#[ignore]` under the existing `s3` feature and uses a unique index prefix per
invocation. The CI workflow now runs it three times.

**Local result: PASS 3/3** against the pinned `rustfs/rustfs` image
(`sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`)
on `http://127.0.0.1:9000`, bucket `quervant-m3-local`, with a separate clean
index namespace per run. Each run exercised query-delete admission (no remote
I/O), commit, cold reopen, exact live-set verification, and durable replay.
Regression checks also passed:

- `cargo test -p quervant-core --all-features --test m1_batches -- --ignored --test-threads=1` — PASS
- `cargo test -p quervant-core --all-features --test m2_patches -- --ignored --test-threads=1` — PASS
- `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1` — PASS (3 tests)
- `cargo test -p quervant-core --all-features --test pr13_oracle -- --ignored --test-threads=1` — PASS
- `cargo test -p quervant-core --all-features --test pr13_oracle_geo -- --ignored --test-threads=1` — PASS

The fake ObjectStore test (`m3_t23`) remains a complementary no-I/O spy, not a
substitute for the real RustFS boundary.

## 6. Residual risks and deferred work

- Query mutation remains committed-snapshot-only by design; volatile refresh
  state is never selected.
- A query delete cannot delete a key changed after selection without a typed
  conflict; overlapping selectors and preceding explicit mutations reject the
  whole batch.
- Query selection uses the existing default search limits because `IndexLimits`
  has no separate search-limit field. No new public budget/limit kind was added.
- M4 (query update/replace/upsert) is not implemented.
- RISK-A/B accepted: `build_leaf_data`, `compute_stats` and the per-segment
  effective-live set can still scale with segment size before the first callback;
  this fixup does not claim O(limit) precomputation.
- M5 owns the comprehensive crash-point, concurrency, performance and full
  mutation fault campaign.
- Real RustFS 3/3 passed locally. Final-SHA `rust`/`msrv`/`rustfs` CI has not
  run because the branch has not been pushed, and explicit human merge
  authorization has not been given. M3 is not DONE.
