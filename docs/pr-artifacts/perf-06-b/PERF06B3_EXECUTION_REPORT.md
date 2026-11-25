# PERF-06-B3 — execution report (implementation complete; independent review pending)

**Disposition:** `PERF06_B3_READY_FOR_INDEPENDENT_REVIEW` (G0–G9 complete on the tested
source; **G10 remains maintainer-owned and OPEN**).

> No performance claim is made. B3 reports **structural** correctness and resource
> evidence only (retained bytes, allocation counts, borrow counts). It runs no
> profiling, no Criterion benchmark, no warm qualification and no cross-engine
> comparison; PERF-06-B4 owns all performance qualification.

## 1. Source admission (G0)

| Item | Value |
|---|---|
| Accepted post-B2 `main` | `ce7dea12c0f8f84fdc3a80306083e38c8df30ce2` (`Merge pull request #127 from yduchesne/dev/perf06-b2`) |
| PR #127 state (authenticated `gh` read) | `MERGED`, merged at `2026-11-25T18:17:43Z`, merge commit `ce7dea12c0f8f84fdc3a80306083e38c8df30ce2`, head `8ee4b83d2320014c4f57699b6d6b031e6a1afedb` |
| Reviewed B2 executable/test base | `7218d5e57c0ce1734a94ed0db93f94a3a7ecf477` (`git merge-base --is-ancestor … origin/main` → 0) |
| Protected B2 blob reconciliation | `git diff --name-status 7218d5e..origin/main -- unified.rs typed_compare.rs column.rs perf06_b2_ordinals.rs` is **empty** — byte-identical |
| Post-B2 additions on `main` | documentation/evidence only (`PERF06B2_EXECUTION_REPORT.md`, `PERF06B2_F1_DETAILED_FIXUP_PLAN.md`, `b2-f1-*` evidence). No executable change, so D02/D03 do not apply |
| Branch | `dev/perf06-b3`, created from and still at `ce7dea1` before the B3 commits (no rebase, no manual merge, no PR #127 amendment) |
| Pre-existing untracked file | `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` (B1-F2 evidence). **D05**: recorded and left untouched; not added to this change set |

Transcript: `docs/pr-artifacts/perf-06-b/evidence/b3-preflight.txt`.

## 2. INV-B3 worksheet (G1) — written before production edits

| ID | Invariant | Plausible wrong implementation | Proof |
|---|---|---|---|
| I01 | Hash of validated key bytes equals the old `d3c::hash_key(&DocumentKey)` bit-for-bit within one process | hash the 2-byte length prefix, use a different hasher, normalize Unicode | `b3_tests::b3_u01_hash_parity_with_the_original_d3c_formula` (64 literal keys vs an inline re-implementation of the frozen formula), `b3_u03`, `b3_u10` |
| I02 | Hash equality is only a prefilter; every apparent duplicate is confirmed with full raw UTF-8 equality | treat a 64-bit collision as identity, prefix match accepted | `b3_u04_u23_fingerprints_are_prefilters_never_identity`, `b3_u08_u19`, `b3_u02` |
| I03 | For Linear and Prefilter the duplicate error precedes any rejection, even for a numeric loser | numeric loser bypasses the retained duplicate scan | `b3_u04…` (losing-position duplicate), `b3_u05_u15`, `b3_u08_u19` |
| I04 | Original strategy selection, P2 probes, activation/disable counters and ExactSet accounting are unchanged | new index/hash threshold, altered bitset, silent ExactSet switch | `b3_u05_u15_compact_policy_matches_the_owned_policy` (per-candidate `exact_scans`/`admissions`/`is_disabled` parity for Linear + P0/P2 Prefilter), `b3_u09`, `b3_u15` (existing `d3c_tests::` suite) |
| I05 | A losing `Single` candidate owns no `DocumentKey`, decodes no per-row key string and owns no sort string | still call `doc_key`/`doc_key_view` per loser | `b3_u06_u18_losing_candidates_own_no_key` (50 000 matches: `owned_key_materializations() ≤ K+1`, `b3_raw_key_borrows() ≤ K+1`, `single_rejected_without_copy() == matches − owned`), `b3_u07`, `b3_i02` |
| I06 | A numeric tie compares full raw key bytes ascending; unequal ranks never touch key bytes | compare hashes as lexical rank, reverse key order under `Desc` | `b3_u02_numeric_order_matches_the_b2_owned_path_and_a_byte_oracle`, `b3_u08_u19` (64 seeded cases × 7 K × 4 direction/placement) |
| I07 | The directory is validated, metered and retained once per verified state; binding allocates nothing per document | per-query O(N) construction, undocumented memory, unbounded cache | `b3_u10_directory_is_retained_once_per_verified_state`, `b3_u12_exact_cap_one_under_and_injected_refusal`, `b3_u06` |
| I08 | An optional metadata failure is a whole-segment pre-candidate fallback to owned B2, never partial compact access | build half the hashes then use them, downgrade corruption | `b3_u12_*`, `b3_u16_mixed_ready_and_unavailable_segments` |
| I09 | Corrupt DOC_KEYS/UTF-8/framing/count stay authoritative typed errors, not `NotAvailable` or success | suppress a malformed unselected key with `.ok()` | `b3_u11_corrupt_doc_keys_stays_authoritative_and_unbound`, `b3_u01`, `b3_i07` |
| I10 | `MetadataBudget`/`SegmentLimits` checks precede allocation; RAII releases on failure/cancel/unwind; no cache poison | miscount the hash vector, sticky `Cancelled`, stranded `Building` | `b3_u12_*`, `b3_u13_cancellation_resets_and_retries`, `b3_u14_error_and_panic_restore_empty`, `b3_u21_concurrent_binders_share_one_owner` |
| I11 | Logical candidate charge, Single string budget, MultiOne full decode, heap preflight/commit/release and the owned cursor tuple are exactly B2 | bill the 8-byte hash instead of UTF-8 bytes, skip losing MultiOne | in-handler `cfg(test)` charge equality assertions, `b3_u17`, `b3_u07`, `b3_i05` |
| I12 | Physical `segment_index`/`doc_id`, `total_hits`, BM25 score bits, live masks, projections, generation and PIT isolation are unchanged | use a key rank for scoring, let an old PIT see new bytes | `b3_i01`, `b3_i03`, `b3_i04`, `b3_i05` |
| I13 | Ineligible, absent, cursor, aggregate, batch, typed/JSON/geo, legacy v1/mixed and **resolved** ExactSet never use B3 | widen eligibility, change the public cursor | `b3_u09_mode_gating_and_ineligible_shapes`, `b3_u20_u22…`, `b3_i05`, `b3_i06`, `b3_i08` |
| I14 | No persisted hash, format, writer, manifest, objectstore, benchmark, dependency or public API change | new required feature, rewritten frozen fixture | §6 protected-path reconciliation; `b3_i04` keeps the frozen v1 fixture byte-identical |
| I15 | The new metadata build happens only after a matched candidate reaches key resolution in that segment | a zero-hit query validates unrelated corrupt DOC_KEYS | `b3_u11` (state code `0`, offsets cell `None` before any access), `b3_u20_u22` (`b3_build_attempts() == 0`), `b3_i07` (zero-match query succeeds) |
| I16 | Safe Rust only: no unchecked UTF-8, no leaking `'static` borrow, no self-reference, no collision assumption | `from_utf8_unchecked`, pointer cast, key slice outliving the reader | source audit (§6); `BoundKeyIdentity<'a>` borrows the reader's own immutable body and never escapes the guard |

## 3. Implementation (frozen architecture)

### 3.1 `crates/quervant-core/src/segment/reader.rs`

* `runtime_doc_key_hash(&str) -> u64` — exactly `DefaultHasher::new()` + `str::Hash`
  + `finish()`. `d3c::hash_key` now delegates to it, so probe positions, seed, P2
  profile, bit layout, hash inputs and mode selection are unchanged.
* `KeyFingerprints { hashes: Vec<u64>, _reservation }` — one runtime hash per
  physical `doc_id`, retained by the shared verified state; no document text and
  no `DocumentKey`.
* `KeyFingerprintCache` — `Mutex<KeyFingerprintState>` + `Condvar` with the frozen
  four states `Empty / Building / Ready / Unavailable`, and
  `KeyFingerprintBuildGuard` (the B1 `FieldBuildGuard` pattern) restoring
  `Building → Empty` on error, cancellation and unwind.
* `VerifiedSegmentState::ensure_key_fingerprints` — claims a build under the
  mutex, runs the whole build and every cancellation poll **outside** it, polls
  at least every 256 validated rows, and polls immediately before `Ready` or
  `Unavailable` publication. `Cancelled` is never cached. A capacity refusal is
  sticky per verified state.
* `VerifiedSegmentState::build_key_fingerprints` — admission order:
  `limits.check_entries` (typed), `usize::try_from` (typed), `check_alloc::<u64>`
  / `check_allocation_bytes` (optional refusal), `MetadataMeter::reserve`
  (`element_bytes::<u64>(N)`, `LimitExceeded → Unavailable`),
  `charge_vec::<u64>(N)`, `try_reserve_exact`, measured-capacity recheck against
  the single-allocation cap **and** the allowance, per-row `offsets.range` +
  `ByteReader::len_prefixed_u16("doc key")` + `str::from_utf8` + non-empty/≤
  `DocumentKey::MAX_BYTES` + `expect_end`, then `meter.extend(owner)` /
  `charge_arc::<KeyFingerprints>()` and `finalize(measured_capacity + owner)`.
  There is **no** second reservation of the hash vector.
* `SegmentReader::bind_key_identity(&dyn Cancellation) -> SegmentResult<Option<BoundKeyIdentity>>`
  — polls cancellation first, refuses a missing `DOC_KEYS` with the existing
  `MissingSection`, returns `Ok(None)` when the verified state has no metadata
  budget or when the existing lazy `key_offsets` cell resolves to `None`
  (reusing `try_build_key_directory`, never a competing offset builder), then
  resolves the fingerprint state machine and checks
  `offsets.ends.len() == doc_count + 1` and `hashes.len() == doc_count`.
* `BoundKeyIdentity::{meta, key_str}` — `meta` is one `hashes.get(index)`, one
  `offsets.range(doc_id)` and checked `record_len.checked_sub(2)`; it performs no
  hashing, no `ByteReader`, no UTF-8 decode and no allocation. `key_str`
  revalidates the length prefix, `expect_end`, UTF-8 and the
  `DocumentKey` bounds and returns `&'a str` borrowed from the reader's own
  immutable body.
* The on-disk `DOC_KEYS` bytes, `decode_doc_keys`, `doc_key`, `doc_key_selected`,
  `decode_doc_key_at_validated_offset` and every public reader method are
  untouched.

### 3.2 `crates/quervant-core/src/search/unified.rs`

* `MixedEntry.key_hash: Option<u64>` — `Some` for every B2 numeric-mode retained
  entry (compact **and** owned fallback), `None` on every legacy/relevance/typed
  path and in every test constructor. Inline; adds no heap allocation and does
  not change `candidate_charge`.
* `d3c::State::supports_compact_key()` — `true` for the **resolved** `Linear` and
  `Prefilter` kinds only; `false` for `ExactSet`.
* `d3c::compact_exact_scan` + `d3c::State::check_compact` — one hash-first pass
  that fails closed on any retained entry with a missing fingerprint, resolves
  the borrowed raw candidate key **at most once and only after a hash match**,
  and then performs the unchanged exact byte comparison. Probe positions,
  `active_bits`, `disabled`, `disable_after`, `admissions` and the `exact_scans`
  witness keep their original definitions. Reaching it in `ExactSet` mode returns
  `CorruptIndex { "compact key path entered ExactSet mode" }` before mutation.
* `CompactHashAudit` — the B2 `OrdinalHeapAudit` analogue: one request-local scan
  proving every retained numeric entry carries a validated fingerprint, run
  before the first compact duplicate decision and maintained inductively.
* `PreparedOrdinalCandidate` / `prepare_ordinal_candidate` — the mandated shared
  extraction. Both the owned B2 handler and the compact handler call it once per
  matched document, preserving the frozen validation and error order (one
  `read_sort_row`, one `translate`, `Single` term length, `MultiOne` complete
  legacy `sort_tuple_for_doc` before any decision).
* `materialize_prepared_sort_value` — the mandated second extraction; mirrors the
  frozen B2 materialization and never allocates a key.
* `candidate_charge_parts_with_key_len` / `ordinal_keyword_candidate_charge_with_len`
  — the identical logical formula over an already validated key length, with the
  old `&DocumentKey` wrappers preserved for every existing call site and test.
* `consider_compact_ordinal_candidate` — the frozen per-candidate order:
  1. `identity.meta(doc_id)`;
  2. `prepare_ordinal_candidate`;
  3. logical charge from `meta.utf8_len`;
  4. `CompactHashAudit::verify_once`;
  5. `check_compact` (exact duplicate policy, before competitiveness);
  6. `OrdinalHeapAudit::verify_once` and the numeric comparison, borrowing raw
     key bytes **only** on an equal numeric rank;
  7. on a win, one `identity.key_str` + one fallibly owned `String` →
     `DocumentKey::new`, mapped to the existing
     `ResourceLimit { limit: u64::MAX, requested: u64::MAX }` convention;
  8. owned sort value, unchanged `experiment.admit` / `heap_admit_candidate`.
* `KeyBinder { Unattempted, Ready(BoundKeyIdentity), Fallback }` — declared inside
  each segment's matched loop and attempted at most once, on the first matched,
  scored candidate, exactly where the original code resolved its owned key.

Both required extractions were performed; **D28 was not triggered** (no B2 error
or validation order changed, no second collector exists).

## 4. Tests actually executed (G4/G5)

"Executed" means the command ran on the tested source and reported `ok`.

### 4.1 Crate unit/adversarial tests

`crates/quervant-core/src/segment/reader.rs::b3_key_identity_tests` (8 tests):

| Plan ID | Test |
|---|---|
| U01 | `b3_u01_invalid_empty_key_is_rejected_before_publication` |
| U03 | `b3_u03_bound_directory_matches_the_authoritative_decoder` |
| U10 | `b3_u10_directory_is_retained_once_per_verified_state` |
| U11 | `b3_u11_corrupt_doc_keys_stays_authoritative_and_unbound` |
| U12 | `b3_u12_exact_cap_one_under_and_injected_refusal`, `b3_u12_injected_allocation_refusal_keeps_the_old_path` |
| U13 | `b3_u13_cancellation_resets_and_retries` |
| U14 | `b3_u14_error_and_panic_restore_empty` |
| U21 | `b3_u21_concurrent_binders_share_one_owner` |

`crates/quervant-core/src/search/unified.rs::b3_tests` (11 tests):

| Plan ID | Test |
|---|---|
| U01 | `b3_u01_hash_parity_with_the_original_d3c_formula` |
| U02, U17 | `b3_u02_numeric_order_matches_the_b2_owned_path_and_a_byte_oracle`, `b3_u17_key_lengths_and_budget_failure` |
| U04, U23 | `b3_u04_u23_fingerprints_are_prefilters_never_identity` |
| U05, U15 | `b3_u05_u15_compact_policy_matches_the_owned_policy` (+ the pre-existing `d3c_tests::` matrix) |
| U06, U18 | `b3_u06_u18_losing_candidates_own_no_key` (50 000 matched documents) |
| U07 | `b3_u07_reverse_order_and_multi_one_losers` |
| U08, U19 | `b3_u08_u19_seeded_differential_oracle` (seed `0xB306_2026_0000_0001`, 64 cases, 1–5 segments, ≤24 docs, K ∈ {1,2,5,10,20,32,100}, 4 direction/placement combinations) |
| U09 | `b3_u09_mode_gating_and_ineligible_shapes` |
| U16 | `b3_u16_mixed_ready_and_unavailable_segments` (both orders) |
| U20, U22 | `b3_u20_u22_empty_no_match_and_ineligible_paths` |
| U24 | `b3_u04_u23` missing-fingerprint audit + `b3_u06` audit-once witness + source audit (§6) |

The `--lib b3_` filter also selects **three pre-existing tests from earlier
series** that merely share the prefix (`search::execute::budget_tests::b3_u01_*`,
`b3_u02_*`, `search::unified::phase4_tests::phase4_b3_u03_*`). They pass and are
not part of B3.

### 4.2 Real integration/lifecycle tests

`crates/quervant-core/tests/perf06_b3_keys.rs` (8 tests, all `ok`):

| Plan ID | Test | Topology |
|---|---|---|
| I01 | `b3_i01_filesystem_corpus_full_order_projection_and_scores` | frozen 18-row/3-segment real `FsDirectory`; K ∈ {1,5,10,18}; 4 direction/placement combinations; 6-field projection; score bits |
| I02 | `b3_i02_sequential_keys_repeat_queries_are_stable` | real 1 000-row sequential-key filesystem index; K ∈ {10,100}; repeated same-snapshot queries; literal order oracle |
| I03 | `b3_i03_held_pits_and_immutable_objects_across_mutation` | held g3 PIT, append Chicago (g4), delete Boston (g5), compact (g6); old PIT view exact; every pre-g4 immutable object byte-identical |
| I04 | `b3_i04_genuine_v1_fixture_then_compaction` | genuine pre-B1 COLUMNS v1 fixture at g3/g4, real compaction to one v2 segment at g5; frozen fixture bytes unchanged |
| I05 | `b3_i05_cursor_pages_pinned_batch_and_ineligible_shapes` | cursor pages `[5,5,5,3]` with owned cursor tuples, `execute_batch_pinned`, grouped `execute_batch` aggregation against a literal per-city count oracle |
| I06 | `b3_i06_rustfs_suite_registration_is_unchanged` | the pinned real RustFS test `b1_r01_cold_shared_ordinals_and_pit` is still registered exactly once and the suite is unmodified; **execution evidence is the hosted `rustfs` job only** (§7) |
| I07 | `b3_i07_corrupt_doc_keys_is_authoritative` | valid outer container with a corrupt `DOC_KEYS` datum: open succeeds, every key access is `InvalidUtf8 { context: "doc key" }`, and the pristine snapshot keeps matched + zero-match contracts |
| I08 | `b3_i08_resource_limits_and_exact_set_fallback` | candidate-budget refusal stays the original typed `ResourceLimit` with no partial result; resolved-ExactSet output identical to the default configuration |

### 4.3 Documented topology limitations (D38)

* The **metadata-capacity-only** fallback (B2 ordinals `Ready`, B3 fingerprint
  directory refused) cannot be isolated through public snapshot knobs: the reader
  metadata cap is `IndexLimits::max_snapshot_bytes`, and shrinking it also
  prevents segment materialization. It is therefore proved by the private unit
  tests `b3_u12_exact_cap_one_under_and_injected_refusal`,
  `b3_u12_injected_allocation_refusal_keeps_the_old_path` and
  `b3_u16_mixed_ready_and_unavailable_segments`, and I08 documents this honestly
  instead of falsifying a public test.
* A committed filesystem segment cannot be rewritten with a corrupt `DOC_KEYS`
  body behind its recorded length/committed-state check
  (`CorruptCommittedState { length mismatch … }`). The collector-level matched
  query behaviour for that topology is proved by
  `b3_u11_corrupt_doc_keys_stays_authoritative_and_unbound`; I07 asserts the
  public reader contract on a rebuilt valid outer container and the pristine
  snapshot's matched/zero-match contracts.
* Structural "no owned key for a loser" counters are `pub(crate)`, so the
  counter evidence is the unit test `b3_u06_u18_losing_candidates_own_no_key`;
  I02 asserts the observable equivalence on the real filesystem corpus.

## 5. Local QA ledger (G7) — one consolidated run on the final tested source

Tested working tree: B3 source + tests + docs, `HEAD` = the tested commit recorded
in §8. Every command below ran **after** the last substantive source/test edit.

| # | Command | Result | Evidence |
|---|---|---|---|
| 1 | `cargo +1.98.1 fmt --all -- --check` | PASS | `b3-fmt_1.98.1.log` |
| 2 | `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | PASS | `b3-clippy_1.98.1_default.log` |
| 3 | `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | PASS | `b3-clippy_1.98.1_all-features.log` |
| 4 | `cargo +1.98.1 test --workspace --all-targets` | PASS — 2 697 passed, 0 failed, 16 ignored | `b3-test_1.98.1_default.log` |
| 5 | `cargo +1.98.1 test --workspace --all-targets --all-features` | PASS — 2 742 passed, 0 failed, 100 ignored | `b3-test_1.98.1_all-features.log` |
| 6 | `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **93.09 %** lines (70 826 lines, 4 894 missed), 93.49 % regions | `b3-coverage-default.log` |
| 7 | `cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.67 %** lines (72 335 lines, 5 302 missed), 93.17 % regions | `b3-coverage-all-features.log` |
| 8 | `cargo +1.98.1 doc --workspace --no-deps` | PASS | `b3-doc_default.log` |
| 9 | `cargo +1.98.1 doc --workspace --all-features --no-deps` | PASS | `b3-doc_all-features.log` |
| 10 | `cargo +1.98.1 bench --workspace --no-run` | PASS (compile only) | `b3-bench_no-run.log` |
| 11 | `bash benchmarks/scripts/test-scripts.sh` | PASS | `b3-benchmark_scripts.log` |
| 12 | `cargo +1.85.0 fmt --all -- --check` | PASS | `b3-fmt_1.85.0.log` |
| 13 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS | `b3-clippy_1.85.0_all-features.log` |
| 14 | `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2 742 passed, 0 failed, 100 ignored | `b3-test_1.85.0_all-features.log` |
| 15 | `git diff --check` | PASS (no output) | `b3-git_diff_--check.log` |

Coverage scope: the whole Rust workspace, all targets, **no exclusions**. Both
floors are above 85 %.

Focused red/green session (P5): `b3-focused-tests.log` — `b3_` lib 23 passed;
`perf06_b3_keys` 8 passed; `b2_` lib 30 passed; `perf06_b2_ordinals` 8 passed;
`b1_` lib 64 passed; `perf06_b1_ordinals` 9 passed / 2 ignored;
`--features pr15i-d3c-experiment d3c_tests::` 41 passed / 1 ignored (the `d3c_`
filter alone selects zero tests, so the precise `d3c_tests::` filter was used and
the exact count recorded); the untimed adapter contract test
`query_session_constructs_exactly_one_snapshot_for_the_whole_session` passed.

**Baseline negative results preserved.** The historical 15H-C and 15I-D1-F
rejections are unchanged and were not reclassified: no whole-cache of owned
per-document strings, no per-candidate `doc_key_view` acquire/check/decode loop,
no new global retained-key fingerprint index, no new eligibility threshold.

## 6. Allowlist and protected-path reconciliation

Changed/added (exactly the permitted set):

```
M crates/quervant-core/src/segment/reader.rs
M crates/quervant-core/src/search/unified.rs
A crates/quervant-core/tests/perf06_b3_keys.rs
A docs/pr-artifacts/perf-06-b/PERF06B3_EXECUTION_REPORT.md
A docs/pr-artifacts/perf-06-b/evidence/b3-*.log|txt
M docs/ARCHITECTURE.md
M docs/PERF_OPTIMIZATION_ROADMAP.md
```

Executable changes are confined to the two permitted production files plus the
permitted new test file. Verified untouched: segment codecs/writers/format and the
original `DOC_KEYS` bytes; `index/*`, `search/{execute,typed,typed_compare,
unified_cursor,score,work,batch,memory}.*`, `contract/*`, `remote/*`,
storage/objectstore/distributed; `Cargo.toml`/`Cargo.lock`; every toolchain file;
`.github/workflows/*`; all `benchmarks/*`; the frozen B1/B2 fixture packages and
every historical PERF result. No new dependency, no public API addition, no new
public configuration, no persisted hash and no feature flag.

Safety audit: no `unsafe`, no `from_utf8_unchecked`, no pointer casts of key
data, no process-global key cache, no leaked `'static` borrow, no second offset
builder, no `doc_keys()` call on the compact path, and no per-candidate
tracing/metric/allocation. Every new allocation is charged to
`MetadataBudget`/`SegmentLimits` before it happens.

## 7. CI (G8) and RustFS (G6)

Ordinary `.github/workflows/ci.yml` is unchanged; all five normal jobs
(`rust`, `msrv`, `rustfs`, `benchmark-adapter-contract`,
`python-benchmark-framework`) are required on the exact tested source. State:
**recorded in `b3-ci-status.txt` / `b3-ci-rustfs-extract.txt` once the draft PR
run completes**; a green job alone does not close a correctness gate, and the
hosted `rustfs` log must show
`test b1_r01_cold_shared_ordinals_and_pit ... ok` for G6 to pass. No local RustFS
bootstrap, no fake remote adapter and no new remote code or claim.

## 8. Identities and applied decision rules

| Identity | Value |
|---|---|
| START (accepted post-B2 `main`) | `ce7dea12c0f8f84fdc3a80306083e38c8df30ce2` |
| TESTED (final executable/test source) | see `b3-delivery.txt` |
| FINAL (terminal PR head, may be docs-only) | see `b3-delivery.txt` |

Decision rows applied:

| Rule | Trigger | Action taken |
|---|---|---|
| D01 | PR #127 merged, reviewed blobs present, clean branch | Recorded merge SHA + empty protected-blob diff, created `dev/perf06-b3` from `ce7dea1` |
| D05 | Pre-existing untracked `f2-ci-status.txt` | Recorded, left untouched, not added |
| D06 | Strict B2 numeric `Ready` in Linear/Prefilter with matched segment | Bind once on the first matched key; compact path only |
| D07 | Resolved `ExactSet` | Old owned-B2 key mode, no directory; configured ExactSet at K<32 resolves Linear and follows the Linear rule |
| D08 | Ineligible cursor/batch/aggregate/relevance/geo/JSON/multisort | Original path, no B3 initialization |
| D09 | Zero matched candidates in a segment | No key preparation |
| D10 | No verified-state metadata budget | `bind_key_identity` → `None`; segment owned-B2 fallback |
| D11 | Existing `key_offsets` refused | Segment owned-B2 fallback; the first key's authoritative decoder preserves the typed corruption |
| D12 | Fingerprint allowance / single-allocation cap exceeded | Sticky per-state `Unavailable`, meter released |
| D13 | `try_reserve_exact` refused | `Unavailable`, allowance released |
| D14 | Genuine DOC_KEYS corruption | Existing precise typed `SegmentError` |
| D15 | Cancellation before/during build or before publication | Typed `Cancelled`, guard restores `Empty`, retry allowed |
| D16 | Cancellation after successful publication | Caller may be cancelled; the shared owner is never erased |
| D17 | Competing binders | One builder, predicate condvar wait, cancellation polls outside the mutex |
| D19/D22/D23 | Hash match with different bytes / absent probe bit / bit pair positive | Exact UTF-8 comparison; unchanged probe semantics |
| D20 | Hash and bytes both match | Original duplicate `CorruptIndex` before numeric rejection |
| D24/D25 | Unequal / equal numeric rank | No key bytes / borrow raw bytes once and compare ascending |
| D26/D27 | Competitive / losing candidate | One fallible owned key and sort value / no owned key |
| D29 | A later segment's directory unavailable | That segment uses owned B2; all retained numeric entries still carry `Some(key_hash)` |
| D30/D31/D32 | Missing fingerprint / `0` and `u64::MAX` hashes / bad doc id | One-time audit fails closed / ordinary `Some(u64)` / typed `Corrupt` |
| D34/D35/D36 | Single logical budget, MultiOne decode, heap preflight | Unchanged B2 ordering and typed errors |
| D37 | Existing ExactSet/Prefilter/B2 tests | Narrow repair only; no assertion removed; all rerun green |
| D38 | Metadata-only fallback not isolable publicly | Private segment-metadata unit tests, limitation documented (§4.3) |
| D44 | Performance concern | Recorded as a B4 risk; no timing, profiling or threshold change |
| D45 | Docs-only terminal commit | Protected recursive-list + executable-blob diff only |
| D49 | Mechanical test-source differences | Local compatibility edits with red/green evidence |

Rows **not** triggered: D02 (PR #127 is merged), D03 (no executable post-B2
change), D04 (clean worktree), D18 (hash parity proved), D28 (extraction
semantics-preserving), D33 (no unsafe/self-reference needed), D39–D43 (no
blocked service in the local scope, no flaky failure, no toolchain/dependency
change), D46–D48, D50 (verified key offsets present).

## 9. Residuals and risks (for B4 / maintainer)

* **No performance result.** B3 is a structural change; the historical 15H-C and
  15I-D1-F rejections show that removing owned key work did not previously
  translate into a qualified warm win. B4 must measure before any claim.
* The compact path adds one `u64` per matched candidate in `MixedEntry` and one
  `Vec<u64>` per eligible segment (charged to `MetadataBudget`), plus an O(K)
  hash-first retained scan whose iteration count equals the previous O(K) exact
  scan. This is a deliberate resource trade whose net effect is a B4 question.
* The retained directory is valid only for one process and one verified segment
  state; it is never persisted and never compared across snapshots.
* G10 — independent review, acceptance and merge — remains **OPEN**; the agent
  cannot close it and makes no merge or release claim.
