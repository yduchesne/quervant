# PR 15I-D3-B — design and correctness trace

Plan: `PR15I_D3_B_DETAILED_PLAN.md` (revision 1.0).
BASE: `39dbd9f571a58bea8cc03d5a406533298e809bfe` (merge of PR #97).
Branch: `dev/pr15i-d3b-retained-key-prefilter` (checked out at BASE before any edit).
Production change surface: `crates/quervant-core/src/search/unified.rs` only.

This document was written **before** the production edit, as required by §4 and §7
of the plan. It maps every invariant `DB-I01`–`DB-I15` to the implementation step,
the fixtures used, the test function names and the accepted error variants.

## 1. Verified source anchors (pre-edit)

| Anchor | Observed at BASE | Consequence |
|---|---|---|
| `UnifiedSearcher::collect_mixed` | `unified.rs:571` | sole production entry |
| Heap construction | `unified.rs:679` `BinaryHeap<MixedEntry<'_>>`; `heap_limit = top_k.limit.saturating_add(1)` at `:677` | filter is created immediately after the heap |
| Owned duplicate check | `unified.rs:907-914` literal `heap.iter().any(...)` | replaced by `check_retained_duplicate` |
| `heap_admit_candidate` | `unified.rs:1199-1235` | return type becomes `SearchResult<bool>` |
| `admit_legacy_keyword_candidate` | `unified.rs:1275-1314` (duplicate check at `:1308-1314`) | gains one private filter argument |
| `consider_borrowed_keyword_candidate` | `unified.rs:1323-1439` (duplicate check at `:1359-1364`, after `borrowed_keyword_candidate_charge`) | gains one private filter argument |
| `DocumentKey` | `contract/document.rs:120` `as_str()` | hashed with `std::collections::hash_map::DefaultHasher` |
| `execute.rs` | `BTreeMap<DocumentKey, f64>` ledger | untouched |

Call-site census (`grep -n heap_admit_candidate`): exactly four admission call
sites — owned main path (`:915`), legacy fallback (`:1314`), borrowed
`saturating` prefix fill (`:1376`), borrowed competitive replacement (`:1439`).
No fourth duplicate-check site exists, so `DBX-04` does not fire and `DBX-05`
authorizes implementation exactly as specified.

## 2. Authorized algorithm (implementation steps)

S2 `RetainedKeyPrefilter` — `bits: [u64; 16]`, `admissions: u16`, `disabled: bool`,
request-local, no allocation, monotonic (no bit is ever cleared), 1024 bits,
two probes derived from one `DefaultHasher` value:
`(hash & 1023, (hash >> 32) & 1023)`. `may_contain` is true only when both bits
are set, and is unconditionally true once `disabled`. `note_admitted` ORs both
bits and disables the filter at the 256th successful admission.

S3 `heap_admit_candidate` returns `SearchResult<bool>`: `Ok(true)` after the
unchanged insert transaction and after the unchanged replacement transaction,
`Ok(false)` when the candidate is not better than the worst entry, and the
original `Err` for every budget/cancellation exit. No ledger statement changes.

S4 `check_retained_duplicate(heap, key, Option<&RetainedKeyPrefilter>)`:

* `None` → literal original linear scan, `Ok(None)` when absent.
* `Some(disabled)` → literal original linear scan, `Ok(None)` when absent.
* active and either probe bit clear → skip the scan, `Ok(Some(hash))`.
* active and both probe bits set → run the literal original linear scan and only
  fail on real `DocumentKey` equality; `Ok(Some(hash))` otherwise.

Every failing path returns the original
`SearchError::CorruptIndex { detail: "duplicate live document key across segments" }`.

S4/S5 filter admission bookkeeping happens **only** after `heap_admit_candidate`
returned `Ok(true)`, via one small private wrapper (`admit_and_note`) that
forwards to the unchanged admission helper and then calls `note_admitted` once.
Losers and errors never touch the filter. Bits are never removed on eviction.

S5 activation: `(request.top_k.limit == 100).then(RetainedKeyPrefilter::default)`
immediately after heap construction. No other K (1, 9, 10, 32, 64, 99, 101, 256,
1000, user values) initializes the filter or hashes a key.

## 3. No-false-negative argument (checked before coding)

Claim: while the filter is active, for every entry currently retained in the
heap, `may_contain(retained_key_hash(entry.hit.key))` is true.

Proof sketch by induction over heap mutations:

1. Base: heap empty, trivially true.
2. Insert (`heap.len() < heap_limit`, `Ok(true)`): the caller notes the admitted
   key's hash immediately after success; both probe bits of that key become 1 and
   are never cleared.
3. Replacement (`Ok(true)`): the admitted key is noted the same way; the evicted
   key's bits may remain set (a permitted false positive) and all other retained
   keys are untouched, so their bits remain set.
4. Rejection (`Ok(false)` or `Err`): the heap does not change, so the invariant
   is preserved.
5. Saturation: at the 256th admission the filter is disabled; from then on
   `may_contain` returns `true` unconditionally, which is trivially
   over-approximating.

Counterexample search: the only way to obtain a false negative would be clearing
a bit (forbidden: `note_admitted` only ORs, no reset exists) or noting a key that
is not retained (forbidden: noting happens only after `Ok(true)`, i.e. after the
heap push; a `Err` path returns from the wrapper first). A cross-request or
cross-thread filter would also break the argument, hence the filter is a local
`Option<RetainedKeyPrefilter>` value inside one `collect_mixed` call — it cannot
escape the request.

A Bloom positive is **not** proof of duplication: collision and stale evicted
bits are resolved by the original exact scan.

## 4. Invariant → implementation → tests

Unit tests live in `#[cfg(test)] mod d3b_tests` inside `unified.rs`; production
path tests live in `crates/quervant-core/tests/pr15i_d3_b.rs`. `I09` is an
in-crate private-seam test because an integration test cannot construct a
duplicate-key heap without exposing private internals; it is listed there as
`i09_*` and documented in `test-matrix.md`.

| ID | Implementation witness | Positive test | Adversarial/negative test |
|---|---|---|---|
| DB-I01 | activation is exactly `top_k.limit == 100`; `None` runs the plain scan | `u01_non_k100_request_bypasses_filter`, `i01_*` | `u02_topk_activation_boundary_matrix`, `u03_k10_multisegment_high_match_no_hashing` |
| DB-I02 | bits are only ORed, never cleared; disabled ⇒ `may_contain` true | `u04_admitted_keys_set_both_bits`, `u05_more_than_heap_limit_admissions_no_false_negative` | `u06_evicted_key_bits_remain_monotonic`, `u07_saturation_disables_at_256_admissions` |
| DB-I03 | negative probes skip only the exact scan | `u08_large_losing_key_set_skips_exact_scans` | `u09_retained_duplicate_errors_even_when_losing`, `u10_forced_collision_resolves_with_exact_scan` |
| DB-I04 | positive ⇒ literal exact scan, error only on equality | `u10_forced_collision_resolves_with_exact_scan` | `u11_stale_evicted_fingerprint_is_inconclusive` |
| DB-I05 | three original check positions, same error precedence | `u12_owned_path_check_and_error`, `u13_borrowed_path_check_before_loss`, `u14_legacy_fallback_single_admission` | `u15_losing_borrowed_duplicate_error_wins`, `u16_malformed_losing_sort_error_precedes_check` |
| DB-I06 | note only after `Ok(true)`; none on `Err`/`Ok(false)` | `u17_successful_admission_notes_once` | `u18_preflight_insert_error_does_not_note`, `u19_replacement_error_does_not_note`, `u20_noncompetitive_candidate_returns_false` |
| DB-I07 | heap/sentinel/comparator untouched | `i02_*`, `i03_*` | `i04_*`, `u26_equal_score_tie_cursor_parity` |
| DB-I08 | no budget statement changed | `i05_*`, `u27_admission_bool_ledger_parity` | `i06_*`, `u19_replacement_error_does_not_note` |
| DB-I09 | per-request filter, snapshot-scoped readers | `i07_*`, `i08_*` | `i09_duplicate_retained_key_is_corrupt_index` (private seam) |
| DB-I10 | only `unified.rs` changes; no codec/manifest/API change | D3-B source preflight/verifier | `v25_*`/`v27_*` negative tooling tests |
| DB-I11 | identical corpus/oracle/index bytes, one host | controller preflight + A/A control | `v24_*`, `v25_*` |
| DB-I12 | frozen D3B-P01..P06 gates | paired campaigns | `v03`..`v16` synthetic gate fixtures |
| DB-I13 | filter is a local variable per `collect_mixed` call | `u21_sequential_requests_isolated`, `i10_*` | `u22_concurrent_requests_isolated` |
| DB-I14 | disabled/bypassed ⇒ literal exact scan | `u07_saturation_disables_at_256_admissions` | `u23_cap_exhaustion_keeps_comparator` |
| DB-I15 | additive revert restores BASE bytes | `R01` rollback QA (only if rejected) | `v27_*`/source diff equality |

Accepted error variants: only
`SearchError::CorruptIndex { detail: "duplicate live document key across segments" }`
for duplicates, plus the pre-existing `SearchError::Cancelled`,
`SearchError::Query(QueryError::BudgetExceeded { .. })`,
`SearchError::ResourceLimit { .. }` and the existing sort/keyword validation
errors — none is introduced, reordered or swallowed by D3-B.

## 5. Ambiguities resolved through the plan matrix

| Observation | Rule | Action |
|---|---|---|
| The legacy fallback re-checks the duplicate for two borrowed fallbacks that already checked | DBX-17 | keep the pre-existing effective order; at most one filter admission (only the successful admit notes) |
| `heap_admit_candidate` is also called from tests | DBX-05 | tests adapted mechanically to the boolean return; no semantics relaxed |
| 32-bit `usize` targets | plan §3.1 | first probe uses the low bits of `hash as usize`, second shifts the `u64` first; no unsafe/target specialization |
| No RustFS service in this environment | DBX-23 | record `RUSTFS_PENDING`; continue local verification, do not claim a pass |
| No plan rule otherwise fits | DBX-52 | HARD STOP |

## 6. Pre-edit QA baseline

The workspace at BASE is clean and was previously validated by the merged PR #97
pipeline; the pre-edit unit suites are executed in the same session as the first
post-edit run so that any regression is attributable. Results are recorded in
`qa.md`.
