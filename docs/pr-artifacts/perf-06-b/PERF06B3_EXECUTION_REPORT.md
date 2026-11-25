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

## 7. CI (G8) and RustFS (G6) — PASS on the tested source

Ordinary `.github/workflows/ci.yml` is unchanged (no workflow, trigger or job
edit in this change set). Run `45687076012` (`event: pull_request`) on head
`aa5c4497bb2a1fcc99a6ab9d9731db86ef7a4479` — the exact tested executable/test
source — completed with **all five normal jobs successful**:

| Job | Result | Duration | Job id |
|---|---|---|---|
| `rust` | PASS | 22m18s | `139462389252` |
| `msrv` | PASS | 7m38s | `139462389952` |
| `rustfs` | PASS | 2m32s | `139462389977` |
| `benchmark-adapter-contract` | PASS | 1m14s | `139462389850` |
| `python-benchmark-framework` | PASS | 2m47s | `139462389923` |

**G6 real-boundary evidence (not merely a green job).** The hosted `rustfs` job
actually ran the pinned real-RustFS acceptance test; its log
(`b3-ci-rustfs-job.log`, extract `b3-ci-rustfs-extract.txt`) shows:

```
Running tests/perf06_b1_rustfs.rs (...)
running 1 test
test b1_r01_cold_shared_ordinals_and_pit ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 2.43s
```

No local RustFS bootstrap, no fake remote adapter, no new remote code and no
remote-performance claim. Status: `b3-ci-status.txt`.

No duplicate-run trigger was introduced: PR changes run through `pull_request`
only, and no feature branch was added to any `push.branches` filter.

## 8. Identities and applied decision rules

| Identity | Value |
|---|---|
| START (accepted post-B2 `main`) | `ce7dea12c0f8f84fdc3a80306083e38c8df30ce2` |
| TESTED (final executable/test source) | `aa5c4497bb2a1fcc99a6ab9d9731db86ef7a4479` |
| FINAL (terminal PR head, docs-only after TESTED) | see `b3-delivery.txt` |
| REMOTE_VERIFIED (CI run for TESTED) | run `45687076012`, head `aa5c4497…`, all five jobs green |

`aa5c4497…` contains the production and test source **and** the first version of
this report; every later commit on this branch is documentation/evidence only,
and `b3-delivery.txt` records the executable-blob diff between TESTED and FINAL.

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

---

# B3-F1 independent-review fixup

Scope: close the four acceptance-evidence gaps identified by independent review of
PR #128 without changing the accepted B3 runtime behavior. Plan:
`docs/pr-artifacts/perf-06-b/PERF06B3_F1_DETAILED_FIXUP_PLAN.md` (committed verbatim).
Everything above this heading is the original B3 report and is preserved unchanged.

## F1-0. Identity at fixup start

| Item | Value |
|---|---|
| Repository / branch / PR | `yduchesne/quervant`, `dev/perf06-b3`, PR [#128](https://github.com/yduchesne/quervant/pull/128) `OPEN` / `isDraft: true` / `baseRefName: main` |
| Accepted `main` (post-B2 baseline) | `ce7dea12c0f8f84fdc3a80306083e38c8df30ce2` (`git merge-base --is-ancestor` → 0) |
| Prior B3 implementation/test SHA | `aa5c4497bb2a1fcc99a6ab9d9731db86ef7a4479` |
| Prior terminal PR head | `76609e8348e4502b4e835d13d7a7facea13bffc1` |
| `aa5c449..76609e8` diff | docs/evidence only; `crates/`, `.github/`, `benchmarks/`, `Cargo.toml`, `Cargo.lock` empty |
| START (F1 working tree) | `76609e8348e4502b4e835d13d7a7facea13bffc1` |
| Foreign untracked file | `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` — recorded and left untouched (R04) |

## F1-1. Pre-implementation correctness worksheet (G1)

Written **before** any F1 production or test edit.

| Invariant | Required observable behavior | Plausible incorrect result | New proof | Source anchor | Gate | Existed before F1 |
|---|---|---|---|---|---|---|
| **F1-I01** | A checksum/version/section-valid envelope with invalid **unselected** `DOC_KEYS` UTF-8 produces the authoritative typed error on a query with a match | `bind_key_identity` returns optional `None`, then search silently succeeds or returns partial hits | `b3_tests::b3_f1_u01_matching_query_rejects_corrupt_unselected_doc_key` | `reader.rs::bind_key_identity` (optional `Ok(None)` on refused offsets) + `search/unified.rs::collect_mixed` ordinal branch (`doc_key` fallback) | G2/F1-I01 | **No** — only direct `reader.doc_key` and pristine-query tests existed |
| **F1-I02** | A zero-match query against the same snapshot succeeds without key resolution; a later match still reports the corruption | eager key work makes zero-hit fail, or the failure poisons unrelated queries | same U01 test: zero-match first, then matched failure twice, then ineligible matched failure, then pristine success | `collect_mixed` loop (binder attempted only on the first **matched, scored** candidate) | G2/F1-I02 | **No** |
| **F1-I03** | A builder returning a typed error **after allocating** releases its reservation, restores `Building→Empty`, notifies a **known blocked waiter**, and that waiter succeeds on the same verified state | error resets without notification and strands the waiter or the budget | `b3_key_identity_tests::b3_f1_u02_error_wakes_actual_waiter_and_retries` | `KeyFingerprintBuildGuard::drop` + `ensure_key_fingerprints` `Next::Wait` | G3/F1-I03 | **No** — only a single-thread error/retry test |
| **F1-I04** | A builder panicking after allocation has the same RAII cleanup/waiter recovery without poisoning the cache mutex | panic strands `Building`, deadlocks the waiter or leaks metadata | `b3_f1_u03_panic_wakes_actual_waiter_and_retries` | same RAII guard (unwind path) | G3/F1-I04 | **No** — panic was only observed single-threaded |
| **F1-I05** | A deliberately poisoned fingerprint mutex returns the exact typed `Corrupt`; it never becomes optional `Unavailable` and never unwinds at the caller | `.unwrap()` panic, ignored poison, silent owned fallback | `b3_f1_u04_poisoned_fingerprint_lock_is_typed` | `fingerprint_lock_poisoned()` via `KeyFingerprintCache::lock` | G3/F1-I05 | **No** |
| **F1-I06** | The wait-entry witness belongs to the **specific cache** under test, not a process-global counter | an unrelated parallel test's wait releases the builder early | updated `b3_u21` + new U02/U03 (per-cache `wait_entries`) | `KeyFingerprintCache` (new `#[cfg(test)]` atomics) | G3/F1-I06 | **No** — `b3_global_wait_starts()` was process-global |
| **F1-I07** | `TopK=32` with the ExactSet threshold of 32 selects **resolved** ExactSet, uses the original owned B2 path and returns all 18 correct rows | K=18 accidentally exercises Linear and still passes | corrected `b3_i08_resource_limits_and_exact_set_fallback` + `d3c::State::production_mode_for_test` assertions in `b3_u09` | `d3c::State::production_mode`, `supports_compact_key` | G4/G5/F1-I07 | **No** — I08 used K=18 with threshold 32 |
| **F1-I08** | A two-field sort is ineligible for B3 and returns exact expected keys/score bits/projection, not an always-true assertion | a genuine sort failure hidden by `is_ok() \|\| is_err()` | corrected `b3_u09_mode_gating_and_ineligible_shapes` | `keyword_ordinal_eligible` (single sort field required) | G4/F1-I08 | **No** — assertion was tautological |
| **F1-I09** | No change to persisted data, cache transitions, key hashing, B2 ranking, duplicate policy or cursor; only the specified `#[cfg(test)]` witnesses | new cache, altered policy, new index bytes, extra production metric | whole-workspace default/all-feature QA + protected-path inventory + unchanged B1/B2/B3 suites | allowlist §3 of the plan | G1–G9/F1-I09 | n/a (invariant) |

### F1-1.1 Required challenge (answered from source before coding)

1. **How is the corrupt body rebuilt under a valid envelope?** `ContainerBuilder::new(ContainerKind::Segment, doc_count)` +
   `require_feature` / `optional_feature` for every original `(id, version)` + `section(kind, flags, aux, body)` for every
   original section, substituting only the mutated `DOC_KEYS` body, then `build()`. This recomputes the outer container
   framing and every section digest, so the result is checksum-valid; a raw byte flip in the committed file is not used
   because the committed length/descriptor check rejects it (`CorruptCommittedState { length mismatch … }`, previously
   observed while writing B3-I07).
2. **Why can the malformed key remain unselected yet validated?** `DOC_KEYS` is a flat record list, and the authoritative
   decoder (`decode_doc_keys` / `decode_doc_key_selected` / `validate_doc_keys_and_capture_offsets`) validates **every**
   record it scans. `k1` (physical doc 1) is never a query match, so the B3 binder claims the offsets directory only after
   the first matched candidate; `try_build_key_directory` then fails on the corrupt `k1` payload, `bind_key_identity`
   returns `Ok(None)`, and the collector's immediate owned fallback `reader.doc_key(0)` decodes the whole section and
   raises `InvalidUtf8 { context: "doc key" }`.
3. **Why can a test-only snapshot open the segment without mutating a committed index?** `ReaderSnapshot::for_test` is a
   `#[cfg(test)]` `pub(crate)` constructor over plain `SegmentSnapshot` values (meta + `Arc<Vec<u8>>` + doc count). It
   never touches `CURRENT`, the manifest or the directory, and every byte still passes the normal
   `VerifiedSegmentState` container/feature/section validation. `ContentDescriptor::of(&rebuilt)` supplies the matching
   descriptor for the new bytes.
4. **Why can the waiter not be released before its state-local wait-entry observation?** The waiter increments
   `wait_entries` **while holding the cache mutex** and only then calls `wait_timeout`, which atomically releases the
   mutex. The builder thread is parked outside the mutex (inside the `AfterHashAllocation` probe) until the main thread
   sends `release`, and the main thread sends it only after observing the incremented counter. Therefore the reset and the
   `notify_all` cannot complete before the waiter has parked.
5. **How does budget-zero-after-drop prove no leaked reservations?** `MetadataMeter` releases the whole unused allowance on
   drop and `MetadataReservation` releases the measured charge when the last owner drops. The ready-state charge may only
   be observed non-zero while a `Ready` owner (state or bound handle) is alive; after all threads exit and the last
   `Arc<VerifiedSegmentState>` is dropped, `MetadataBudget::used()` must be `0`. A non-zero value proves a leaked charge.

## F1-2. What changed (source scope, allowlist §3)

Only test code plus two `#[cfg(test)]` witnesses. No production behavior changed.

| File | F1 delta | Production semantics |
|---|---|---|
| `crates/quervant-core/src/search/unified.rs` | new `b3_tests::b3_f1_u01_matching_query_rejects_corrupt_unselected_doc_key`; rewritten `b3_u09_mode_gating_and_ineligible_shapes` | untouched (`UnifiedSearcher`, handlers, `d3c`, `KeyBinder`, comparator, costs, `MixedEntry` all byte-identical) |
| `crates/quervant-core/src/segment/reader.rs` | two `#[cfg(test)]` `AtomicU64` fields on `KeyFingerprintCache` (`wait_entries`, `raii_wake_notifications`) + their init and increment sites; new `b3_f1_u02`, `b3_f1_u03`, `b3_f1_u04`; strengthened `b3_u21` | untouched: state transitions, poll cadence, `notify_all`, `disarm`, public reader methods, metadata allowance, DOC_KEYS parsing, fingerprints and error mapping |
| `crates/quervant-core/tests/perf06_b3_keys.rs` | second half of `b3_i08` now requests K=32 on a fresh snapshot with literal oracles | n/a (test) |
| `docs/pr-artifacts/perf-06-b/PERF06B3_F1_DETAILED_FIXUP_PLAN.md` | verbatim authorized plan (md5 `a9aa4a47e7cbef2ae0f392ece61e3fe9`, 462 lines) | n/a |
| `docs/pr-artifacts/perf-06-b/evidence/b3-f1-*` | new sanitized logs/evidence | n/a |

`#[cfg(test)]`-only additions (compiled out of normal/benchmark builds):

```
KeyFingerprintCache { …, #[cfg(test)] wait_entries: AtomicU64, #[cfg(test)] raii_wake_notifications: AtomicU64 }
ensure_key_fingerprints  Next::Wait  → wait_entries.fetch_add(1, SeqCst)   (immediately before wait_timeout)
KeyFingerprintBuildGuard::drop       → raii_wake_notifications.fetch_add(1, SeqCst)  (before notify_all)
```

Both witnesses are read only inside `b3_key_identity_tests`, are per-`VerifiedSegmentState`,
and no release-build counter, lock, metric or tracing was added.

## F1-3. Invariant ledger (G1 → executed proof)

| Invariant | Test | Executed command | Result |
|---|---|---|---|
| F1-I01 | `b3_f1_u01_matching_query_rejects_corrupt_unselected_doc_key` | `cargo +1.98.1 test -p quervant-core --lib search::unified::b3_tests::b3_f1_u01_… -- --exact --test-threads=1` | **PASS** (1 selected, 1 passed) |
| F1-I02 | same test (zero-match arm first) | same | **PASS** |
| F1-I03 | `b3_f1_u02_error_wakes_actual_waiter_and_retries` | `… --lib b3_f1_u02_error_wakes_actual_waiter_and_retries -- --test-threads=1` | **PASS** (1/1) |
| F1-I04 | `b3_f1_u03_panic_wakes_actual_waiter_and_retries` | `… --lib b3_f1_u03_panic_wakes_actual_waiter_and_retries …` | **PASS** (1/1) |
| F1-I05 | `b3_f1_u04_poisoned_fingerprint_lock_is_typed` | `… --lib b3_f1_u04_poisoned_fingerprint_lock_is_typed …` | **PASS** (1/1) |
| F1-I06 | updated `b3_u21_concurrent_binders_share_one_owner` + U02/U03 | `… --lib b3_u21_concurrent_binders_share_one_owner …` | **PASS** (1/1) |
| F1-I07 | corrected `b3_i08_resource_limits_and_exact_set_fallback` + `production_mode_for_test` assertions in `b3_u09` | `cargo +1.98.1 test -p quervant-core --test perf06_b3_keys b3_i08_… -- --exact --test-threads=1`; `… --lib b3_u09_mode_gating_and_ineligible_shapes …` | **PASS** (1/1 each) |
| F1-I08 | corrected `b3_u09` (exact keys, count, cursor absence, legacy comparison) | same | **PASS** |
| F1-I09 | whole-workspace default/all-feature QA + protected inventory (F1-5) | §7.3 ledger | **PASS** |

Every command above selected **exactly one** named test (`running 1 test` in
`b3-f1-focused-tests.log`); `b3_` now selects **27** lib tests (23 B3 + 4 F1) and
the integration target selects **8**.

## F1-4. Concern-by-concern evidence

### F1-4.1 Corrupt-snapshot collector query (G2) — `b3_f1_u01`

Fixture: two real `MemoryDirectory` documents in one segment, physical order
`doc_keys() == ["k0","k1"]`, with `k0`/`grp=common` (matching) and
`k1`/`grp=other` (non-matching). Pristine matched query: `total_hits=1`, key `k0`,
projection `doc_id="a"`.

Corruption: the pristine segment is parsed and rebuilt through
`ContainerBuilder::new(ContainerKind::Segment, doc_count)` with **every** original
required/optional feature and **every** original section `(kind, flags, aux, body)`;
only the cloned `DOC_KEYS` body changes, at `windows(2)` position of the unique
literal `k1` payload (`assert_eq!(hits.len(), 1)`, `corrupt_at > 12`, first byte →
`0xFF`). The result is a fresh checksum-valid container; the original bytes are
asserted unchanged and no committed `CURRENT`/manifest/index object is touched.

Lazy open is asserted with the authoritative decoder:
`SegmentReader::open(rebuilt)` succeeds, while `doc_key(0)` returns
`SegmentError::InvalidUtf8 { context: "doc key" }` because the full decoder
validates the **unselected** `k1` record.

Then a real `ReaderSnapshot::for_test` is built from exactly one
`SegmentSnapshot::new(SegmentMeta::new(…, ContentDescriptor::of(&rebuilt), …),
Arc::new(rebuilt), doc_count)` with 256 MiB reader-copy and metadata caps
(the 2-document fixture is orders of magnitude smaller, so R15 does not apply),
and the **real `UnifiedSearcher`** runs, in this order:

| # | Request on the corrupt snapshot | Required result | Observed |
|---|---|---|---|
| 1 | `Term(grp = "no-such-group")`, K=1 | `Ok`, `total_hits=0`, empty hits, no cursor, `b3_build_attempts()==0` | PASS |
| 2 | strict `term()` = `Term(grp = "common")`, K=1 | `Err(SearchError::Segment(SegmentError::InvalidUtf8 { context: "doc key" }))` | PASS |
| 3 | same request repeated | same exact typed error (not a sticky success) | PASS |
| 4 | ineligible `legacy_term()` = `And([term()])`, K=1 | same exact typed error | PASS |
| 5 | pristine original snapshot | `Ok`, `total_hits=1`, key `k0`, projection `doc_id="a"` | PASS |

No partial response, no `NotAvailable`-as-success, no panic and no production
change was required (R12 path; R13/R14/R16 not triggered).

### F1-4.2 Failing-builder waiter recovery (G3) — `b3_f1_u02`/`u03`/`u04`/`u21`

Each test uses its **own** `admitted_state(bytes_with(400))` (400 documents, so the
`HashIndex256` boundary and a 7-byte key at `doc_id=399` really exist) and its own
budget; nothing is shared between U02, U03 and U04.

Protocol (identical shape for U02/U03): the builder thread installs the existing
`B3Probe::AfterHashAllocation` hook — which runs **outside** the cache mutex after
the real `Vec<u64>` allocation — signals `entered`, then blocks on a `release`
channel. The main thread starts a second binder only after `entered`, waits for
**that cache's** `wait_entries` to increase above its recorded baseline, and only
then releases the builder. Because the waiter increments while holding the mutex
and `wait_timeout` releases it atomically, the reset+notify cannot complete before
the waiter parked.

| Test | Builder outcome | Waiter | Post-conditions |
|---|---|---|---|
| `b3_f1_u02` | injected `Corrupt { context: "doc key identity", detail: "b3-f1-injected-error" }` after allocation | recovers, reads `meta(399).utf8_len == 7` | `state_code == 2` (Ready), one retained owner, `raii_wake_notifications` strictly increased, `budget.used() == 0` after the last owner drops |
| `b3_f1_u03` | `panic!("b3-f1-injected-post-allocation-panic")`, caught by `catch_unwind` in the builder thread | recovers, `meta(399).utf8_len == 7` | Ready, mutex **not** poisoned, notify witness increased, `budget.used() == 0` |
| `b3_f1_u04` | separate thread poisons only the fingerprint mutex | n/a | both binds return exactly `Corrupt { context: "doc key identity", detail: "fingerprint cache lock poisoned" }`; poison still set afterwards; `budget.used() == 0` |
| `b3_u21` | successful publication | parked waiter reuses the same owner | one build attempt, one directory build, waiter builds 0, `waiter_waits >= 1` (5 ms cadence may re-enter), state-local sequencing |

The RAII witness proves the cleanup notify **site executed**; it does **not** claim
the wake was caused only by it, because the production waiter also wakes on its
5 ms poll cadence. No timeout occurred in any run; 20 repeated executions of
U02/U03/U21 at `--test-threads=8` all passed (`repeat_runs_failed=0`), so no
flakiness classification was needed (R37 not triggered).

### F1-4.3 ExactSet at the real threshold (G5) — `b3_i08`

Threshold kept at the contract value 32 and the request TopK is now **32** on a
**fresh** snapshot taken after the resource-budget half of the test:

* `total_hits == 18`, `hits.len() == 18`, `next_cursor.is_none()`;
* `keys == order_for(corpus_rows(), Asc, Last)` — the literal input-derived
  18-key oracle;
* every hit's full six-field projection equals `expected_projected_fields(key)`;
* every score is `Some(finite)` and **bit-equal** to the separately executed
  ineligible `fallback_query()` request at K=32 on the same snapshot
  (`assert_scores_and_projection`, which also compares `generation` and
  `view_ordinal`);
* the default duplicate configuration at K=32 (resolves Prefilter) produces the
  same keys/count/score bits/projections — a differential contract check, not
  proof of ExactSet dispatch.

Proof that K=32 selects ExactSet lives at the unit seam (`b3_u09`):
`d3c::State::production_mode_for_test(32, exact_set_config()) == (ExactSet, P2)` and
`(31, …) == (Linear, P0)`, plus `b3_build_attempts() == 0` and
`b3_directory_builds() == 0` for that exact request as the **first** request on a
fresh snapshot (so a cached directory could not mask the observation). R30 path;
R34 not triggered.

### F1-4.4 Non-vacuous ineligible assertions (G4) — `b3_u09`

The former `assert!(error.is_ok() || error.is_err())` is replaced by an exact
oracle for the valid two-column sort (`doc_id ASC`, `n ASC`) on the three literal
rows: `Ok`, `total_hits == 3`, `keys == ["k00000","k00001","k00002"]`,
`hits.len() == 3`, `next_cursor.is_none()`, `b3_build_attempts() == 0` and
`b3_directory_builds() == 0` on a fresh snapshot, followed by an exact comparison
against the semantically equivalent ineligible `legacy_term()` request (keys,
count, score `to_bits()`, projected fields). No tautology remains.

## F1-5. Final QA ledger (G7) — one run on TESTED `52d7e69`

| # | Command | Result | Evidence |
|---|---|---|---|
| 1 | `cargo +1.98.1 fmt --all -- --check` | PASS | `b3-f1-fmt_1.98.1.log` |
| 2 | `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | PASS | `b3-f1-clippy_1.98.1_default.log` |
| 3 | `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | PASS | `b3-f1-clippy_1.98.1_all-features.log` |
| 4 | `cargo +1.98.1 test --workspace --all-targets` | PASS — **2701 passed, 0 failed, 16 ignored** | `b3-f1-test_1.98.1_default.log` |
| 5 | `cargo +1.98.1 test --workspace --all-targets --all-features` | PASS — **2746 passed, 0 failed, 100 ignored** | `b3-f1-test_1.98.1_all-features.log` |
| 6 | `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **93.12 %** lines (71 228 lines, 4 897 missed), 93.53 % regions | `b3-f1-coverage-default.log` |
| 7 | `cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.70 %** lines (72 737 lines, 5 313 missed), 93.20 % regions | `b3-f1-coverage-all-features.log` |
| 8 | `cargo +1.98.1 doc --workspace --no-deps` | PASS | `b3-f1-doc_default.log` |
| 9 | `cargo +1.98.1 doc --workspace --all-features --no-deps` | PASS | `b3-f1-doc_all-features.log` |
| 10 | `cargo +1.98.1 bench --workspace --no-run` | PASS (compile only; no samples run) | `b3-f1-bench_no-run.log` |
| 11 | `bash benchmarks/scripts/test-scripts.sh` | PASS | `b3-f1-benchmark_scripts.log` |
| 12 | `cargo +1.85.0 fmt --all -- --check` | PASS | `b3-f1-fmt_1.85.0.log` |
| 13 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS | `b3-f1-clippy_1.85.0_all-features.log` |
| 14 | `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2746 passed, 0 failed, 100 ignored | `b3-f1-test_1.85.0_all-features.log` |
| 15 | `git diff --check origin/main...HEAD` | PASS (see F1-5.1) | `b3-f1-git_diff_--check.log` |

Coverage scope: whole Rust workspace, all targets, **no exclusions**; both floors
above 85 %. Both toolchains used unchanged (Rust 1.98.1 and MSRV 1.85.0); no
dependency, lockfile or toolchain change.

Focused matrix on TESTED (`b3-f1-focused-tests.log`): the seven F1 named tests each
selected exactly 1 and passed; `b3_` lib **27 passed**; `perf06_b3_keys` **8
passed**; `b2_` lib **30 passed**; `perf06_b2_ordinals` **8 passed**; `b1_` lib
**64 passed**; `perf06_b1_ordinals` **9 passed / 2 ignored**;
`--features pr15i-d3c-experiment d3c_tests::` **41 passed / 1 ignored**; the
untimed adapter contract test passed; 20/20 repeat runs of the concurrency tests
passed.

### F1-5.1 Evidence sanitization (disclosed mechanical change)

`git diff --check origin/main...HEAD` initially failed **only** on trailing
whitespace inside six *verbatim captured CI-log copies* from the already-committed
B3 evidence (`b3-ci-rustfs-job.log`, `b3-ci-rustfs-extract.txt`, `b3-ci-status.txt`,
`b3-test_1.98.1_default.log`, `b3-test_1.98.1_all-features.log`,
`b3-test_1.85.0_all-features.log`). The F1 delta itself was already clean
(`git diff --check 76609e8..HEAD` → rc 0). The same class already exists in
`origin/main` (`b2-ci-rustfs-job.log` carries 124 such lines), so this is a
pre-existing property of the evidence directory, not an F1 defect.

Because §7.3 makes the check mandatory and §3 explicitly contemplates *sanitized*
logs/evidence, the six files were sanitized mechanically: trailing spaces stripped
and one blank line at EOF removed from three logs. This is provably
content-preserving — non-blank line counts are unchanged (1380 / 22 / 3430 / 3430
/ 3301) and `git diff -w` shows only the three single blank-EOF deletions, with no
other hunk. No test result, timestamp, exit code or line of evidence was altered or
removed, nothing was promoted, and the change touches documentation only, so it
does not invalidate the TESTED source QA (R39). It is isolated in its own commit
and is trivially revertible if the maintainer prefers the unsanitized logs.

New `b3-f1-*` evidence was sanitized on creation for the same reason.

## F1-6. Hosted CI and real RustFS (G6/G8)

Ordinary `.github/workflows/ci.yml` is unchanged (no workflow, trigger or job edit
exists in this change set; PR changes run on `pull_request` only, so no duplicate
run was introduced).

| Item | Value |
|---|---|
| Run | `45705309080` (`event: pull_request`, `workflow: Rust CI`) |
| Head | `b7753c5e6bccd443faf64b65c7b0f3d65fc2d083` |
| TESTED source | `52d7e69f40759f27be79434118c47171b06702b7` |
| Source equivalence | `git diff --name-status 52d7e69..b7753c5 -- crates/ benchmarks/ .github/ Cargo.toml Cargo.lock` is **empty** |
| Result | `rust` PASS 16m45s · `msrv` PASS 10m35s · `rustfs` PASS 2m36s · `benchmark-adapter-contract` PASS 1m26s · `python-benchmark-framework` PASS 4m0s |

**G6 real-boundary evidence (not a green job alone).** The hosted `rustfs` job
(`139525642745`) actually ran the pinned real-RustFS test
(`b3-f1-ci-rustfs-extract.txt`):

```
Running tests/perf06_b1_rustfs.rs (...)
running 1 test
test b1_r01_cold_shared_ordinals_and_pit ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 2.36s
```

No local RustFS service, no mock substitution, no extra dispatch, no cancelled job
and no benchmark acquisition. The F1 unit/probe tests are **not** presented as
RustFS evidence, and the historic B3 RustFS PASS is not reused: the quoted log is
from this run on this head.

## F1-7. Decision-matrix ledger

| Rule | Trigger as observed | Action taken |
|---|---|---|
| R01 | PR #128 `OPEN`, still based on accepted post-B2 `main`; branch `dev/perf06-b3` | Continued the existing branch with fast-forward pushes only; no new PR, no merge, no reset |
| R02 | `aa5c449..76609e8` was docs/evidence only; remote head reconciled | Carried the same source anchors forward; recorded blob identities |
| R04 | Foreign untracked `evidence/f2-ci-status.txt` (pre-existing B1-F2 evidence) | Recorded, left untouched, never staged or committed |
| R06 | B3 fingerprint/ordinal implementation present and matching frozen behavior | Preserved production source; only two `#[cfg(test)]` witnesses added |
| R07/R09/R10/R12 | `ReaderSnapshot::for_test`/`SegmentSnapshot::new`/`SegmentMeta::new`/`ContentDescriptor::of` available; container features/sections copied; lazy open + the typed unselected-key error observed; matched search returned the exact typed error | Used them for the single synthetic checksum-valid corrupt snapshot; asserted `SearchError::Segment(InvalidUtf8 { context: "doc key" })` |
| R08 | Unique literal `k1` payload inside the two-row `DOC_KEYS` body | Mutated only its first payload byte and rebuilt the outer envelope |
| R11 | Zero-hit strict-term query on the corrupt snapshot succeeded first | Recorded before the matched arms; no key directory was initialized |
| R17 | `B3Probe::AfterHashAllocation` exists and runs outside the cache mutex | Used it for U02/U03 with `mpsc` channels |
| R18 | Per-cache `#[cfg(test)]` atomics can be added | Added exactly `wait_entries` + `raii_wake_notifications` with init/increments |
| R19/R22/R23 | Waiter parked in *this* cache's `Building` predicate; RAII notify site executed; cadence re-entered the wait | Required a state-local `wait_entries` delta before release, a notify-witness delta, and `waiter_waits >= 1` |
| R20 | Injected typed error after allocation | Builder error surfaced, RAII restored `Empty`, same-cache retry reached Ready |
| R21 | Injected panic after allocation, mutex unlocked | Caught with `catch_unwind` in the builder thread; RAII restored; waiter recovered; mutex not poisoned |
| R24 | Builder failed, waiter retried, one Ready owner | `budget.used() == 0` only after the last state owner dropped |
| R25 | Two intermediate test-seam compile faults (`Debug` bound on `expect_err`, non-`Send` handle escaping a thread) | Fixed mechanically inside the new test-only code (`match` instead of `expect_err`, classify inside the thread); no production API change, no assertion weakened |
| R28 | Deliberately poisoned fingerprint mutex | Exact typed `Corrupt` on two binds, poison retained, no budget leak |
| R30 | ExactSet cutoff 32 with request K=32 and 18 live rows | Executed the real I08 ExactSet on a fresh snapshot with the literal 18-hit oracle |
| R32 | Existing U09 valid two-column sort returns exact expected output | Replaced the tautology with `expect(...)`, literal oracle, cursor absence and a legacy comparison |
| R35 (not triggered) | No protected production path, public API, format, dependency, benchmark or CI topology change was required | Allowlist respected |
| R38/R39 | FINAL head differs from TESTED only by documentation/evidence | Recorded the empty protected diff and `git diff --check`; reused the TESTED source QA and verified the final-head CI |
| R40 (not triggered for design) | The only unlisted condition was the whitespace gate interacting with immutable verbatim logs | Handled as documented in F1-5.1: mechanical, disclosed, content-preserving sanitization accepted because §3 explicitly sanctions *sanitized* logs/evidence; the alternative (editing no evidence) would leave a mandatory gate failing. Isolated in its own revertible commit |

**Red/green discipline.** No production RED was claimed or fabricated. Per §7.1 the
new assertions close *evidence* gaps, and all four new tests plus the two corrected
ones passed against the **existing** production source once written. The only
failing states observed were genuine test-seam compilation intermediates (R25),
which are recorded as such and are not a correctness defect. No flakiness was
claimed; 20/20 repeated runs of the concurrency tests passed (R37 not triggered).

## F1-8. Residuals

* No *public* committed corrupt-file injection exists: the matched-corruption proof
  is a crate unit test over a test-only snapshot, because a committed segment
  cannot be rewritten behind its recorded length/committed-state check. B3-I07
  remains the public **reader**-level boundary proof and is not relabelled.
* No *public* metadata-capacity-only fallback fixture exists; it remains proved
  privately (`b3_u12_*`, `b3_u16`), as before this fixup.
* Cache-wake causality is bounded by the production 5 ms timed polling: the tests
  prove actual same-cache wait entry, execution of the RAII notify site, successful
  same-state recovery and zero final leakage — deliberately **not** "notification
  was the unique cause".
* The historical 15H-C and 15I-D1-F performance rejections are unchanged and still
  not reclassified. No warm, cold, RSS, index-size or latency claim is made.
* B3 runtime behavior is unchanged: hash formula, cache state machine, duplicate
  policy, ranking, cursor, PIT, budgets and metadata accounting are identical.

## F1-9. Adversarial self-review (explicit answers)

| Question | Answer |
|---|---|
| Can a corrupted non-matching key escape a matched search? | No — `b3_f1_u01` drives a real `UnifiedSearcher` and gets the exact typed DOC_KEYS error. |
| Is the snapshot checksum valid and the descriptor recomputed? | Yes — rebuilt through `ContainerBuilder` (all features/sections) and `ContentDescriptor::of(&rebuilt)`. |
| Can a zero-hit query avoid key resolution? | Yes — asserted first, with `b3_build_attempts() == 0`. |
| Did any waiter really reach its own cache's `Building` wait? | Yes — state-local `wait_entries` delta gates the release; a global counter is no longer used for sequencing. |
| Could an unrelated test satisfy a global counter? | No longer — U21/U02/U03 sequence on the per-`VerifiedSegmentState` atomic (the global counter is only a post-hoc sanity check). |
| Does the RAII notify site execute on both error and panic? | Yes — `raii_wake_notifications` strictly increases in U02 and U03. |
| Does the final budget drop to zero when no owner remains? | Yes — asserted after the last state drop in U02/U03/U04. |
| Does deliberate poison return the right error without clearing the poison? | Yes — exact typed `Corrupt` twice, `is_poisoned()` still true. |
| Is ExactSet actually selected for K=32, not merely configured? | Yes — `production_mode_for_test(32, …) == (ExactSet, P2)` plus zero B3 binds/builds on a fresh snapshot, and the 18-row literal oracle. |
| Does the multi-sort test demand valid output instead of accepting either result? | Yes — exact keys/count/cursor plus a full legacy comparison; the tautology is gone. |
| Is release/benchmark source still unchanged? | Yes — production deltas are `#[cfg(test)]`-only; `cargo bench --no-run` and clippy on both toolchains pass. |

## F1-10. Delivery identities and handoff

| Identity | Value |
|---|---|
| START (F1) | `76609e8348e4502b4e835d13d7a7facea13bffc1` |
| TESTED (F1 executable/test source) | `52d7e69f40759f27be79434118c47171b06702b7` |
| REMOTE_VERIFIED (exact source-equivalent head run) | `b7753c5e6bccd443faf64b65c7b0f3d65fc2d083`, run `45705309080`, all five jobs PASS |
| FINAL (terminal docs/evidence head) | the head of the final documentation commit on `dev/perf06-b3` (self-referential SHAs cannot be embedded); identities and diffs are recorded in `b3-f1-delivery.txt` |
| Protected diff TESTED→FINAL | `crates/`, `benchmarks/`, `.github/`, `Cargo.toml`, `Cargo.lock` **empty** |

Final disposition: **`PERF06_B3_F1_READY_FOR_INDEPENDENT_REVIEW`** for G0–G9 on the
identities above. **G10 (independent review, acceptance, merge) remains
maintainer-owned and OPEN.** PR #128 stays a draft and unmerged (it was observed
briefly in "ready" state during the push window and was immediately returned to
draft, as the plan requires); no history was rewritten, no gate was waived, no
limit or threshold was changed, no benchmark was run and B4 was not started.
