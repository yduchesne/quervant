# PR 15I-D3-B — test matrix and executed evidence

All tests are behavior-focused; each row names the executable test and the
observable assertion. Unit tests live in `#[cfg(test)] mod d3b_tests` inside
`crates/quervant-core/src/search/unified.rs`; production-path tests live in
`crates/quervant-core/tests/pr15i_d3_b.rs`. `I09` is an in-crate test because an
integration test cannot construct a duplicate-key `MixedEntry` heap without
exposing private internals (`u09`), and the plan forbids a fabricated public
corruption input.

## Unit matrix (U01–U28) — 28 tests, all passing

| ID | Test | Independent expectation |
|---|---|---|
| U01 | `u01_non_k100_request_bypasses_filter` | K10 public search: 150 hits, 10 returned, zero filter activations and zero hashes |
| U02 | `u02_topk_activation_boundary_matrix` | K ∈ {1,9,10,32,64,99,100,101,256}: exactly K100 activates; `heap_limit == K+1` |
| U03 | `u03_k10_multisegment_high_match_no_hashing` | 1,000 hits: K10 relevance and keyword-sort searches hash nothing and bypass the filter 1,000 times |
| U04 | `u04_admitted_keys_set_both_bits` | both `d3b_indices` bits set for every admitted key; `admissions == 64` |
| U05 | `u05_more_than_heap_limit_admissions_no_false_negative` | 201 admitted keys all report positive membership |
| U06 | `u06_evicted_key_bits_remain_monotonic` | evicted key's bits remain; a positive triggers exactly one exact rescan and no error |
| U07 | `u07_saturation_disables_at_256_admissions` | disabled exactly at 256; later notes mutate nothing; disabled checks are literal scans returning `None` |
| U08 | `u08_large_losing_key_set_skips_exact_scans` | 10,000 distinct losers: no false result, >9,000 negative skips, counters sum to 10,000 |
| U09 | `u09_retained_duplicate_errors_even_when_losing` | retained duplicate returns the exact `CorruptIndex` detail; admissions unchanged |
| U10 | `u10_forced_collision_resolves_with_exact_scan` | both bits forced for a distinct key: exact scan runs, returns `Ok`, never a false corruption |
| U11 | `u11_stale_evicted_fingerprint_is_inconclusive` | stale evicted fingerprint is a positive (one rescan) and is accepted |
| U12 | `u12_owned_path_check_and_error` | inactive filter path performs the literal scan and returns the original error detail |
| U13 | `u13_borrowed_path_check_before_loss` | borrowed keyword path errors on a retained duplicate before competitiveness |
| U14 | `u14_legacy_fallback_single_admission` | legacy fallback: one check, one admission, one note; duplicate returns the same error |
| U15 | `u15_losing_borrowed_duplicate_error_wins` | losing duplicate errors before the noncompetitive early return (no materialization) |
| U16 | `u16_malformed_losing_sort_error_precedes_check` | malformed losing sort view still returns `InvalidUtf8`, with zero hashes/checks |
| U17 | `u17_successful_admission_notes_once` | two pushes + one replacement produce exactly three notes and three filter admissions |
| U18 | `u18_preflight_insert_error_does_not_note` | `ResourceLimit` on insert: heap empty, filter empty |
| U19 | `u19_replacement_error_does_not_note` | `ResourceLimit` on replacement: heap, ledger and filter unchanged |
| U20 | `u20_noncompetitive_candidate_returns_false` | loser returns `Ok(false)`, no note, no leaked charge (a later insert still fits) |
| U21 | `u21_sequential_requests_isolated` | two sequential searches activate two fresh filters with identical results/cursor |
| U22 | `u22_concurrent_requests_isolated` | two concurrent searches return identical 100-hit pages |
| U23 | `u23_cap_exhaustion_keeps_comparator` | 256 admissions across replacements disable the filter; sorted scores strictly decrease; disabled duplicate errors |
| U24 | `u24_key_identity_and_hash_stability` | hash stability for short/unicode/max-length keys; empty and over-long keys rejected |
| U25 | `u25_identical_indices_safe` | both probes on the same bit: no false negative |
| U26 | `u26_equal_score_tie_cursor_parity` | 101 equal-score hits: key-ascending order, sentinel cursor `k00099`, bitwise-equal scores |
| U27 | `u27_admission_bool_ledger_parity` | insert/replacement return `true`, loser returns `false`, heap length exact |
| U28 | `u28_test_witnesses_are_test_gated` | source scan proves the observation module and every witness call are `#[cfg(test)]` |

## Production-path matrix (I01–I12)

| ID | Test | Oracle |
|---|---|---|
| I01 | `i01_pr15d_shaped_lanes_match_independent_oracle` | PR15D formula at 10K/100K: common 4,999/49,999, medium 1,250/12,500, rare 1, absent 0, exact ordered ids |
| I02 | `i02_pagination_over_one_hundred` | 101/102/1,000 matching docs paginate K100 with no duplicate or omission |
| I03 | `i03_equal_score_tie_break_and_sort_directions` | equal-score key tie-break, Asc/Desc keyword sort, bitwise-equal scores |
| I04 | `i04_topk_boundary_with_one_hundred_one_hits` | K99/K100 produce a cursor; K101 exhausts the 101 hits with no cursor |
| I05 | `i05_single_and_multi_segment_parity` | one segment vs two committed segments: identical counts, keys and score bits |
| I06 | `i06_candidate_budget_exact_one_over` | minimal accepted candidate ceiling (bisected): exact-at accepted, one-under rejected with the requested value unchanged |
| I07 | `i07_pinned_snapshot_isolated_from_mutation` | pinned snapshot keeps 20 deleted hits and 100 common hits after a delete+upsert commit |
| I08 | `i08_keyword_sort_borrowed_and_owned_parity` | cursor page (owned path) equals the expected suffix; invalid sort keeps its typed error |
| I09 | in-crate `u09_retained_duplicate_errors_even_when_losing` | private heap seam; no public corruption input is fabricated |
| I10 | `i10_concurrent_requests_are_independent` | two concurrent searches over one snapshot return the same 100-hit page |
| I11 | `i11_fs_directory_reopen_parity` | real `FsDirectory`: commit, close, reopen twice, identical keys/scores |
| I12 | `real_rustfs::i12_real_rustfs_cold_bootstrap_query_parity` (`#[ignore]`, `s3` feature) | cold remote reader with an empty cache matches the writer view |

I12 could not be executed locally: the RustFS harness fails to start the pinned
image under podman-compose. Recorded as `RUSTFS_PENDING` in `qa.md`; it is not
reported as a pass.

## Benchmark negative matrix (V01–V28)

`benchmarks/pr15i_d3_b/test_verify.py` contains one independently constructed
fixture per V-ID (plus a summary-recompute and exclusive-create check). The
fixtures never import the controller.

| ID | Assertion |
|---|---|
| V01 | pristine synthetic control qualifies |
| V02 | pristine paired both-K100-win fixture passes every gate |
| V03 | zero-effect B fails P01/P02 |
| V04 | common/K100 1,999,999 ns fails P01 |
| V05 | common/K100 exactly 2,000,000 with 3 non-negative blocks passes; 2 blocks fails |
| V06 | medium/K100 exactly 1,000,000 with 3 non-negative blocks passes |
| V07 | medium/K100 999,999 ns fails P02 |
| V08 | K10 median −500,000 / block −1,500,000 / ratio 1.05 passes inclusively |
| V09 | K10 below median or block fails P03 |
| V10 | K10 ratio 1.050001 fails P03 |
| V11 | absent ratio exactly 1.15 passes P04 |
| V12 | ratio 1.150001 or block 1.500001 fails P04 |
| V13 | 10K common median exactly −2,000,000 fails P05 (strict) |
| V14 | 10K common block −3,000,001 fails P05 |
| V15 | 100K K100 block −1,500,001 fails P06 |
| V16 | only two non-negative target blocks fails P01 |
| V17 | one exempt-lane soft outlier with a passing median qualifies |
| V18 | two exempt-lane soft outliers are blocked |
| V19 | non-exempt soft outlier or any hard outlier is blocked |
| V20 | control median outside [0.85, 1.15] is blocked |
| V21 | 100K high-hit block drift 1.250001 is blocked |
| V22 | low-hit block drift 1.500001 is blocked |
| V23 | missing, duplicate or reordered slot/lane is invalid |
| V24 | oracle document-id tamper is invalid |
| V25 | binary, index-digest and 100K sentinel tamper is invalid |
| V26 | wrong protocol digest in a setup record is invalid |
| V27 | traversal, symlink and unlisted seal members are invalid |
| V28 | a second paired campaign after a non-qualified first campaign is invalid |
