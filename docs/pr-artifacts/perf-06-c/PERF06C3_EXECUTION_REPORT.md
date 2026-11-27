# PERF-06-C3 execution report — certified deferred BM25 for strict-term ordinal Top-K

**Status:** implementation complete; local correctness evidence, repository QA and
independent-review handoff delivered. **No performance benchmark, profiler,
timing run, qualification campaign, C4 work, merge or baseline promotion was
executed or is claimed.** G10 (independent review + maintainer acceptance) is
OPEN and is not a coding-agent gate.

## 1. Source identity

| Fact | Value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Required base `B` | `6bc977e6a26c183609b7ca53eca51d3ab09ce337` (merged PR #131) |
| Predecessor PR | #131, `state=MERGED`, `mergedAt=2026-11-26T23:00:00Z`, head `da033ff19b3facd4f0a5319506a64e658156e93f` |
| Branch | `dev/perf06-c3` (created from `origin/main`; no pre-existing branch or PR) |
| RED commit | `0c295d1390869826c581a6c589d299cd13c4c99f` |
| `TESTED` commit | `6ea6b7ce049d613a29864f1eae53dea5fd61e75f` |
| `TESTED` tree | `ee12c6b576ebd877e46e56512d4e786ef76a41af` |
| Plan SHA-256 | `69b1aeba951d13361936ef8ffed75f77ec88362d3c7a38727b4eedd684f9a755` |
| Recorder SHA-256 | `5bbb38e1b4b7538c56e80eacf1f694de19ccbd49528333f95553fde4bf80418d` |
| RED patch (raw) SHA-256 | `a748a008be870761d66d17fdee83b90a5828d31732bf84110460de9fa9f1ae54` (stored Base64 in `evidence/c3/red.patch.b64`) |
| `B..TESTED` diff SHA-256 | `3adccd3f71a456049f15072d97b6fee2e693d9175f2aa74633c7cf3fb2969c8b` |
| Manifest SHA-256 | `2f7478a2dc72fe955a8d245bade407b28194429aad33709166573bcc45b264ac` |
| Source-audit SHA-256 | see `evidence/c3/manifest.json` (`source_audit_sha256`) |
| Receipts | 9 baseline + 1 expected-red + 65 final (`evidence/c3/manifest.json`) |

All 17 anchor blobs listed in the plan §2.1 were verified equal to `B` before any
edit (`git rev-parse "$B:<path>"`); no shadow build input was present. The only
foreign untracked path was
`docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` (disjoint prior evidence,
left untouched, D02).

### Tested source adjustment after the first `TESTED`

A first `TESTED` commit `8b6f827be93a422e858609e20c0fb96647c7c302` was made and
fully receipted. The prescribed protected-source audit then showed a
**comment-only** difference inside the `if !DEFERRED` eager branch: the accepted
three-line comment had been shortened. The comment was restored verbatim and a
new immutable `TESTED` `6ea6b7ce049d613a29864f1eae53dea5fd61e75f` was created;
**every** final receipt was regenerated against it. The superseded receipts are
retained under `evidence/c3/receipts-superseded/` and are not acceptance
evidence.

## 2. G1 worksheet (actual answers)

1. **Why is `sort.fields.len()==1` insufficient?** The complete C2 predicate is
   `strict_term_dispatch_eligible` (`unified.rs`), which requires, in order:
   `standalone`, no aggregation, no `after`, `single_term_postings_eligible`,
   `keyword_ordinal_eligible`, `root == Lexical(0)`, exactly one lexical leaf,
   no typed leaves, one `CompiledLeaf::Term` with one analyzed term,
   `positive_lexical == {0}`, the scoring-field membership check, the
   sort-field/codec-field equality, and finally
   `field.doc_freq(term) > K+1`. The B1 ordinal requirement is that the single
   explicit sort field be `Keyword`/`Single`/columnar (via
   `keyword_sort_late_eligible`) with no `multi` selector. The **lexical scoring
   field** is `plan.lexical_leaves[0].field_id`; the **sortable field** is
   `request.sort.fields[0].field`. The predicate only requires the sort field to
   have a prepared ordinal column; the code deliberately scores from the
   lexical leaf's field stats, and the two fields may differ (e.g. query
   `grp=common`, sort `doc_id`). Using the sort field as the scoring field would
   be wrong, and is not done.
2. **Why does positive integer tf suffice for a uniform bound?** `read_one_with`
   rejects `freq == 0` with `SegmentError::ZeroFrequency` before any callback and
   caps `freq` at `max_decoded_entries`, so a decoded match has `tf ∈ [1, 2^64]`.
   `compute_stats` accumulates `n` and each field `total_length` with checked
   `u64` additions, so `avgdl = T as f64 / n as f64`; `u64::MAX as f64` rounds to
   exactly `2^64`, hence for `T>0, n>0`, `2^-64 <= avgdl <= 2^64`.
   `FieldStats::length` returns a `u64` in `[0, 2^64]` and is total. The prepared
   IDF is `ln(1 + (n-df+0.5)/(df+0.5))` with `1 <= df <= n`, whose maximum is
   below `46 < 64`. With `BM25_K1=1.2`, `BM25_B=0.75` the intermediate
   `0.75*dl/avgdl` is at most `2^128`, the denominator is finite, positive and
   `>= 1`, and the numerator is `< 2^72`; every intermediate is far below binary64
   overflow. Round-off cannot make nonnegative operands negative; underflow to
   zero is fine. Therefore `bm25_with_idf` cannot take its `InvalidScore` branch
   for a certified request. The case matrix: `tf=0` is impossible from the
   decoder (rejected earlier); `n=0`, `avgdl<=0` take the early `Ok(0.0)` branch
   that precedes `df>n` and the missing-IDF error; `avgdl` NaN takes
   `InvalidScore`; `df>n` takes the `InvalidScore` "document frequency exceeds"
   branch; a missing prepared IDF takes `CorruptIndex`; a NaN/±inf/negative
   prepared IDF takes `InvalidScore`. All of those are outside the certificate,
   so the eager path preserves them. `-0.0` compares equal to zero and the
   `+0.0` accumulator turns it into `+0.0`, so signed zero is preserved.
3. **Why is checking only final winners unsafe?** A losing document with an
   invalid score must still raise the accepted typed error; skipping it would
   hide real corruption. The certificate is therefore a read-only, request-wide
   proof over the *immutable prepared statistics* taken **before** any candidate,
   not a post-hoc scan of winners and not an error-swallowing policy. U03 row
   `U03-01` shows `df>n` surfacing on the first scored document even though it
   will not be returned; U03-C1/C2 show the same for a simultaneously corrupted
   key.
4. **Producers/consumers of `MixedEntry` and every `.score` read.** Production
   literals: the legacy direct entry, `materialize_borrowed_keyword_entry`,
   `admit_legacy_keyword_candidate`, `consider_ordinal_keyword_candidate`,
   `consider_compact_ordinal_candidate` (5), plus 4 test literals. `.score` is
   read only by (a) `default_relevance_cmp` for relevance-sorted requests and (b)
   the cursor builder for relevance requests; both are `relevance == true` paths
   that a certified request never takes (certified entries are
   `relevance=false`, `ordinal_sort=Some`). `Ord`/`ordinal_candidate_order`,
   `candidate_charge*`, `d3c::State`, the duplicate policy and
   `project_selected_hits` never read `.score`. The `K+1` lookahead keeps
   `score = None`, and `selected` is truncated to `K` before the cursor is built
   from index `K-1`, so no unscored returned hit can leak.
5. **Ledger transitions.** Per segment: `P = 16m` leaf, `S = 48m` matched set,
   `T = 64m` scored map, so the strict phase peak is `3m` entries and `128m`
   bytes; an earlier completed segment leaves the global heap charge `G` live.
   Replacement is preflight-admit-new-then-drop-old, so the transient peak is
   the larger of the two, never the sum beyond the existing table. m=K+2 for
   K=1/10/100 gives (9, 384) / (36, 1536) / (306, 13056). C3 keeps every
   admission and release in the accepted order; it removes only the *scoring
   arithmetic*, not a logical charge: a resource limit is a compatibility
   contract, not an artefact of which physical bytes exist. No new M-sized
   allocation exists — the sole retained vector is the one the decoder already
   produced.
6. **Why not move key/tuple materialization later?** A candidate can be admitted
   and later evicted, and the accepted failure contract makes its key/tuple
   allocation fallible at admission time. Deferring it to finalization would let
   a later segment's error or a later key error win differently, and would
   change the error precedence for `MultiOne` (which must decode its full legacy
   tuple before the reject decision) and for B3 refusal (per-segment owned-key
   fallback). C3 therefore defers only the non-erroring score computation.
7. **Cancellation.** Poll sites in the strict path are: per decoded posting,
   after the `N` lexical charge, inside `build_leaf_data`/decoder limits, and at
   each candidate callback boundary. The eager score loop never polled, and the
   deferred finalizer does not poll, so the poll *schedule* is identical. U10
   measures a deterministic `P = 96` polls and sweeps `cancel_at = 1..=P+1` with
   identical poll counts on both routes.
8. **Score identity through the heap.** Each `MixedEntry` carries its own
   `(segment_index, doc_id, tf)`; replacement drops the whole old entry, and
   `into_sorted_vec` reorders entries without touching those fields. Only the
   first `K` of the sorted vector is scored, using the same immutable
   `SnapshotStats` and norm source that the eager path used, in the same
   snapshot/reader lifetime. There is no re-open for tf.
9. **Inventories.** At `B`: `search::unified::c2_tests::c2_u` = 24,
   `search::execute::c2_physical_tests::c2_p` = 5, broad `--lib c2_` = 39,
   `perf06_c2_physical` = 9. At `TESTED`: 24 / 5 / **52** / **26** (see the
   note in §6) / **12**, i.e. exactly 17 new unit functions and 3 new
   integration functions. The old C2 direct eager observations stay in force
   because all 24 `c2_u*` functions carry a first-statement
   `c3_observation::ForceEager::apply()` guard; the normal public integration
   path now exercises C3. The C2-only late-score injector cannot force
   certificate acceptance: `strict_score_certificate` returns `None` when
   `execute::c2_observation::score_failure_armed()` is true, and there is no
   force-defer hook at all.
10. **C4 dependency and protected paths.** C4 owns the approved warm
    qualification of the incremental C over accepted A+B, including absent/rare
    lanes and the layout/codegen guard for the one-word entry growth. Protected:
    `Cargo.*`, `rust-toolchain.toml`, `.github/**`, `benchmarks/**`,
    `quervant-objectstore`, `quervant-distributed`, segment codecs, manifests,
    writers, `select_keys`, the public API and the cursor/PIT machinery. All
    applicable local and CI gates are enumerated in §4–§5.

## 3. What was implemented

* **P1 `score.rs`** — the private, request-local `DeferredBm25` proof token with
  the conservative sufficient bounds (`n>0`, `df>0`, `df<=n`, finite `avgdl` in
  `[2^-64, 2^64]`, finite prepared IDF in `[0, 64]`), plus the test-only
  `c3_score_observation` counter and the `INJECTED_SHARED_STATS` fault seam.
  `bm25`, `idf_log`, `prepare_idf`, `bm25_with_idf`, `compute_stats`,
  `FieldStats::length` and `doc_freq` are unchanged.
* **P2 `execute.rs`** — `visit_strict_term_payload_with<const DEFERRED, F>`
  shares one validated decoder/`N`-charge/membership/admission/release sequence;
  two thin typed wrappers keep the eager `f64` contract and add the raw
  `NonZeroU64` one. The accepted eager statements are byte-identical inside
  `if !DEFERRED`.
* **P3/P4 `unified.rs`** — one inline
  `deferred_tf: Option<NonZeroU64>` on `MixedEntry` (layout: 136→144 bytes,
  alignment 8→8, delta exactly one `u64` word), one request-wide certificate
  attempt, one const-generic strict body, and a finalizer that validates every
  retained entry (including the sentinel) before scoring only the first `K`.
* **P5** — `c3_observation` route/identity witnesses, `ForceEager` RAII,
  `StatFault`/`StatFaultArm`, and the 24 first-statement C2 eager guards.

### Deliberate representation decision

`Option<NonZeroU64>` has an 8-byte niche: the measured entry size grows by
exactly one `u64` word and alignment is unchanged (U12:
`old=136/8 new=144/8 delta=8`). The *logical* charge formulas are unchanged
because they are a compatibility policy, not `size_of::<MixedEntry>()`; the
physical heap grows by at most `(K+1) * 8` bytes. C4 must guard this lane.

## 4. Baseline then red-first proof

Baseline at `B` (9 receipts): C2 unit 24 passed, C2 physical 5 passed, broad
`--lib c2_` 39 registered, integration 9 passed, reader 9 passed, score 17
passed. No baseline failure.

The RED step added only the TLS `BM25_CALLS` observation, one `record_call()`
statement and `c3_u01_winner_score_count`. Observed exactly:

```text
running 1 test
test search::unified::c2_tests::c3_u01_winner_score_count ... C3 U01 BM25 calls=40 expected=3
thread '... c3_u01_winner_score_count' panicked:
assertion `left == right` failed: only returned hits are scored
  left: 40
 right: 3
test result: FAILED. 0 passed; 1 failed; ... finished in 0.02s
```

exit `101`, one executed test, all preceding assertions passed: **EXPECTED RED**
(D09). The identical test now passes with `C3 U01 BM25 calls=3 expected=3`.

## 5. Local QA gates

Run on `TESTED` = `6ea6b7ce049d613a29864f1eae53dea5fd61e75f`, clean tracked
worktree, `QUERVANT_PR15I_D3C_*` unset for every command.

| Gate | Result |
| --- | --- |
| `cargo +1.98.1 fmt --all -- --check` | PASS (exit 0, empty output) |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.98.1 clippy ... --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.85.0 clippy ... --all-features -- -D warnings` | PASS |
| `cargo +1.98.1 test --workspace --all-targets` | PASS — 2759 passed, 0 failed |
| `cargo +1.98.1 test --workspace --all-targets --all-features` | PASS — 2804 passed, 0 failed |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 2759 passed, 0 failed |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2804 passed, 0 failed |
| `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — `TOTAL 127974 7869 93.85%` lines |
| `cargo +1.98.1 llvm-cov ... --all-features --fail-under-lines 85` | PASS — `TOTAL 130732 8445 93.54%` lines |
| `cargo +1.98.1 doc --workspace --no-deps` | PASS |
| `cargo +1.98.1 doc --workspace --all-features --no-deps` | PASS |
| `cargo +1.98.1 bench --workspace --no-run` | PASS (compilation only; no benchmark executed) |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 script tests |

Workspace test totals count every `test result: ok. N passed` line in the
receipt; doctests and per-target binaries are included, and no target failed.

### Coverage inspection of the new behavior

A diagnostic `llvm-cov --lcov` run on the same commit was inspected. Every
uncovered line in the new production regions is an internal defensive guard that
is unreachable by construction:

* `visit_strict_term_payload_with`: the two `_ => return Err(strict_term_shape_error())`
  arms, the `certificate.is_some()` refusal in eager mode, the
  `positive.contains(&0) == false` `None` field-stats arm, and the
  `usize::try_from(m)` overflow arm.
* `strict_score_certificate`: the two non-single-leaf `return None` arms.
* `collect_strict_term_ordinal_body`: the `DEFERRED != certificate.is_some()`
  mismatch guard (unreachable through the two permitted invocations) and the
  pre-existing typed-geo loop that C2 never populates.
* Pre-existing (not C3) uncovered branches remain unchanged.

No new production line is untested by behavior; the coverage floor is exceeded
by a wide margin (93.85% / 93.54% against 85%).

## 6. Test inventory

| Selection | `B` | `TESTED` | Composition |
| --- | ---: | ---: | --- |
| `--lib search::unified::c2_tests::c2_u` | 24 | 24 | unchanged old names |
| `--lib search::execute::c2_physical_tests::c2_p` | 5 | 5 | unchanged old names |
| `--lib c2_` (broad) | 39 | **52** | 39 old + 12 new `c3_u*` + 1 new `c3_p01` |
| `--lib c3_` | 9 | **26** | 9 pre-existing unrelated `search::unified::tests::c3_*` storage-accounting tests + 17 new |
| `--test perf06_c2_physical` | 9 | **12** | 9 old unchanged + I01–I03 |

**Inventory note (plan/source discrepancy, recorded not silently absorbed):**
the plan expected `--lib c3_` to select *exactly 17* tests. The actual base tree
already contains **9 unrelated pre-existing test functions** whose names begin
with `c3_` in `search::unified::tests`
(`c3_insert_exact_one_over_atomic`, `c3_path_*` × 6,
`c3_replacement_overlap_peak`, `c3_replacement_reject_atomic`), from the
historical PR 15H stage-C accounting work. The new PERF-06-C3 registrations are
exactly the 17 names required by the plan and are present exactly once; the
coarse `c3_` substring filter consequently selects 26. Exact name sets are in
`evidence/c3/inventories.txt`; this is an inventory-reporting correction, not an
architecture change, and no pre-existing test was renamed or removed.

New PERF-06-C3 registrations (17 unit + 3 integration):

| ID | Full name |
| --- | --- |
| S01 | `search::score::tests::c3_s01_certificate_matrix` |
| S02 | `search::score::tests::c3_s02_uniform_bound_and_bits` |
| P01 | `search::execute::c2_physical_tests::c3_p01_deferred_decode_and_ledger` |
| U01 | `search::unified::c2_tests::c3_u01_winner_score_count` |
| U02 | `search::unified::c2_tests::c3_u02_dispatch_and_count_matrix` |
| U03 | `search::unified::c2_tests::c3_u03_uncertified_stats_eager_precedence` |
| U04 | `search::unified::c2_tests::c3_u04_corruption_precedence` |
| U05 | `search::unified::c2_tests::c3_u05_native_later_segment_boundary` |
| U06 | `search::unified::c2_tests::c3_u06_b3_refusal_matrix` |
| U07 | `search::unified::c2_tests::c3_u07_replacement_and_final_identity` |
| U08 | `search::unified::c2_tests::c3_u08_rank_ties_and_null_order` |
| U09 | `search::unified::c2_tests::c3_u09_logical_budget_edges` |
| U10 | `search::unified::c2_tests::c3_u10_cancel_poll_parity` |
| U11 | `search::unified::c2_tests::c3_u11_seeded_final_scores` |
| U12 | `search::unified::c2_tests::c3_u12_private_representation` |
| U13 | `search::unified::b3_tests::c3_u13_collision_with_deferred_frequency` |
| U14 | `search::unified::b3_tests::c3_u14_multione_deferred_scores` |
| I01 | `c3_i01_real_scores_and_explicit_cursor` |
| I02 | `c3_i02_real_pit_update_merge_and_paging` |
| I03 | `c3_i03_real_resource_and_cancellation_edges` |

## 7. Case and row totals (from the focused receipts)

| Case | Executed rows / assertions |
| --- | --- |
| S01 | 24 certificate rows |
| S02 | 108 uniform-bound cases + degenerate/IDF rows |
| P01 | 6 ledger rows + same-budget recovery + foreign-certificate guard |
| U01 | red-first green: `BM25 calls=3` |
| U02 | 25 dispatch/count rows + 3-segment split + 12 ineligible shapes + cursor page 2 |
| U03 | 17 `INJECTED_SHARED_STATS` rows + 2 competing-fault rows + recovery |
| U04 | 9 real-byte corruption rows (`completed=9`) |
| U05 | 4 native cap rows + 4 recovery lines |
| U06 | 5 actual B3 refusal/control rows |
| U07 | Asc + Desc ownership/identity |
| U08 | 4 rank/placement rows |
| U09 | 12 logical-budget rows |
| U10 | 97 cancellation rows (P=96, 96 cancellations, 1 success) |
| U11 | 160 seeded differential rows |
| U12 | layout + finalize + 4 misuse rows |
| U13 | 5 collision/fingerprint rows |
| U14 | 64 MultiOne rows |
| I01 | 6 real score/cursor combinations |
| I02 | pinned old/new/compacted views + paging |
| I03 | exact entry/byte/scanned/atomicity/cancellation edges |

The complete emitted case lines are in `evidence/c3/case-output.txt`.

Notable observations, recorded rather than retuned:

* U09 `m=102, K=100` at the exact virtual peak `(306, 13056)` is rejected by the
  pre-existing **projection ledger** (`limit 13056 requested 13160`) *after* C3
  finalized its K scores; the eager and Legacy routes reject identically. The
  test therefore asserts verdict parity with eager/Legacy plus the invariant
  "identities track scores, and a rejection is either pre-score or
  post-finalization", instead of assuming a collection-time heap refusal. This
  is an accepted existing checkpoint, not a C3 behavior change.
* U03 `ZeroDf`/`MissingTerm`/`MissingField` rows are refused by the unchanged
  `M > K+1` count guard and stay Legacy (as specified), so
  `certificate_attempts == 0` there.
* U04 `S29+D0` is labelled `INJECTED_C2_ONLY`; it proves that an armed synthetic
  score fault still forces eager C2 and fails before the 30th real scorer call.
  It is not claimed as natural score corruption or as Legacy same-fault parity.

## 8. Real integration topology

* I01/I02: real `TempDir` + `FsDirectory`, real writer, two commits
  (`0..6`, `6..40`), close, `Index::open_with_limits` reopen, real
  `UnifiedSearcher`. I02 additionally performs a real `delete`, `upsert`,
  `insert`, `commit`, `refresh`, then `compact` + `commit` + reopen, while a
  pinned old snapshot stays live.
* I03: real `FsDirectory` single-commit 48-row corpus, plus a two-segment
  48-row corpus for the scanned-occurrence boundary, real `CancellationFlag`.
* The existing RustFS-backed CI job remains the mandatory remote regression; C3
  changes only request-local scoring, so no new remote topology is required.

## 9. Protected-source audit

`evidence/c3/source_audit.py` extracts each protected item from the exact `B`
and `TESTED` blobs by its rustfmt-clean declaration and compares it. Result:
**36 PASS, 0 FAIL, 1 INFO** (the INFO row is the authorized callback-body move
into the `accept` closure, where the two ordinal `true` include-score literals
became `include_score, deferred_tf`).

Items with exact byte equality include `bm25`, `idf_log`, `prepare_idf`,
`bm25_with_idf`, `compute_stats`, `FieldStats::length`, `doc_freq`,
`CandidateBudget`, `SegmentCandidateLedger` (+ inherent impl),
`effective_live_examination_count`, `build_leaf_data`,
`take_strict_one_term_postings`, `visit_lexical_membership_with`,
`evaluate_lexical_with`, `select_keys`, `keyword_sort_late_eligible`,
`keyword_ordinal_eligible`, `strict_term_dispatch_eligible`, `SelectedHit`,
`candidate_charge*`, `mod d3c`, `heap_admit_candidate`,
`ordinal_candidate_order`, `project_selected_hits` and all three
`MixedEntry` comparison impls.

Authorized mechanical-only differences were verified for
`FieldStats::bm25_score` (one test-only call), both ordinal handlers (one added
parameter and one entry field) and `collect_mixed_legacy_body` (two added `None`
arguments plus one added `deferred_tf: None` literal field). The
`visit_strict_term_payload_with` eager phase is byte-identical after the
`if !DEFERRED` de-indentation.

`git diff --name-status B TESTED` contains only the four allowlisted source/test
files. `git diff --check B..TESTED` exits 0 with empty output.

## 10. Scope, allocation and representation audit

* No new production `Vec`, `collect`, `try_reserve`, `clone`, `HashMap`, `Box` or
  extra scorer call was added outside the existing heap conversion/selection and
  the original posting vector.
* No new logical work charge, resource cap, error variant, dependency, feature
  flag, environment switch, public API, format, manifest, cache key or
  distributed surface.
* No production instrumentation: every new counter, witness and fault arm is
  `#[cfg(test)]`.

## 11. Gate ledger and disposition

| Gate | Status | Evidence |
| --- | --- | --- |
| G0 source admission | PASS | merged #131 at exact `B`, 17 blobs verified, no shadow inputs, baseline 24/5/39/9 |
| G1 correctness preparation | PASS | §2 worksheet, §3 bounds, source anchors agree |
| G2 implementation/isolation | PASS | source audit 36 PASS/0 FAIL, layout `+8`, no new allocation/charge/API |
| G3 deferred score acceptance | PASS | RED 40 vs 3 and green 3; S01 24, S02 108, P01, U01/U02/U07/U08/U11/U12 |
| G4 failure and accounting | PASS | U03 17+2, U04 9, U05 4, U06 5, U09 12, U10 97, U13/U14 |
| G5 real integration | PASS | I01 6 combos, I02 pinned/updated/compacted paging, I03 exact failures/retries |
| G6 regression and inventory | PASS | old 24/5/9 retained, exact name sets recorded, no new ignores |
| G7 local repository QA | PASS | §5 table on the immutable `TESTED` |
| G8 hosted regression | see §12 | depends on the pushed head |
| G9 documentation/evidence/delivery | see §12 | plan verbatim, manifest verified, append-only docs |
| G10 independent review and maintainer acceptance | **OPEN** | never set by the agent |

**Disposition:** see the terminal handoff block. G10 is OPEN; C4 owns warm
qualification. No performance claim is made.

## 12. Receipt manifest and commands

Every final command below was executed exactly once against
`TESTED = 6ea6b7ce049d613a29864f1eae53dea5fd61e75f` with a clean tracked
worktree, `QUERVANT_PR15I_D3C_STRATEGY` and `QUERVANT_PR15I_D3C_PREFILTER_PROFILE`
removed in the child environment, and a raw Base64 stdout/stderr receipt whose
size and SHA-256 are verified in `evidence/c3/manifest.json`.

| Label | Command | Exit | Class |
| --- | --- | ---: | --- |
| `base_list_c2_broad` | `cargo +1.98.1 test -p quervant-core --lib c2_ -- --list --format terse` | 0 | BASELINE |
| `base_list_c2p` | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p -- --list --format terse` | 0 | BASELINE |
| `base_list_c2u` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u -- --list --format terse` | 0 | BASELINE |
| `base_list_integration` | `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --list --format terse` | 0 | BASELINE |
| `base_run_c2p` | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p -- --test-threads=1` | 0 | BASELINE |
| `base_run_c2u` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u -- --test-threads=1` | 0 | BASELINE |
| `base_run_integration` | `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --test-threads=1` | 0 | BASELINE |
| `base_run_reader` | `cargo +1.98.1 test -p quervant-core --lib segment::reader::stored_blocks_reader_tests:: -- --test-threads=8` | 0 | BASELINE |
| `base_run_score` | `cargo +1.98.1 test -p quervant-core --lib search::score::tests:: -- --test-threads=1` | 0 | BASELINE |
| `red_u01` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u01_winner_score_count -- --exact --nocapture --test-threads=1` | 101 | EXPECTED_RED |
| `diag_cov_lcov` | `cargo +1.98.1 llvm-cov --workspace --all-targets --lcov --output-path /tmp/c3evidence/diag.lcov` | 0 | PASS |
| `fin_i01` | `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical c3_i01_real_scores_and_explicit_cursor -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_i02` | `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical c3_i02_real_pit_update_merge_and_paging -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_i03` | `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical c3_i03_real_resource_and_cancellation_edges -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_list_c2_broad` | `cargo +1.98.1 test -p quervant-core --lib c2_ -- --list --format terse` | 0 | PASS |
| `fin_list_c2p` | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p -- --list --format terse` | 0 | PASS |
| `fin_list_c2u` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u -- --list --format terse` | 0 | PASS |
| `fin_list_c3` | `cargo +1.98.1 test -p quervant-core --lib c3_ -- --list --format terse` | 0 | PASS |
| `fin_list_integration` | `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --list --format terse` | 0 | PASS |
| `fin_old_p05` | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p05_n_examination_and_scanned_frequency -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_old_u12` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u12_corrupt_selected_unselected_and_multi_fault -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_old_u17` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u17_ordinal_unavailable_and_b3_refusal -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_old_u21` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u21_work_budget_exhaustion_after_prior_segment -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_p01` | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c3_p01_deferred_decode_and_ledger -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_s01` | `cargo +1.98.1 test -p quervant-core --lib search::score::tests::c3_s01_certificate_matrix -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_s02` | `cargo +1.98.1 test -p quervant-core --lib search::score::tests::c3_s02_uniform_bound_and_bits -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_suite_b1_int` | `cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals` | 0 | PASS |
| `fin_suite_b1_lib` | `cargo +1.98.1 test -p quervant-core --lib b1_` | 0 | PASS |
| `fin_suite_b2_int` | `cargo +1.98.1 test -p quervant-core --test perf06_b2_ordinals` | 0 | PASS |
| `fin_suite_b2_lib` | `cargo +1.98.1 test -p quervant-core --lib b2_` | 0 | PASS |
| `fin_suite_b3_int` | `cargo +1.98.1 test -p quervant-core --test perf06_b3_keys` | 0 | PASS |
| `fin_suite_b3_lib` | `cargo +1.98.1 test -p quervant-core --lib b3_` | 0 | PASS |
| `fin_suite_c2p_t1` | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p -- --test-threads=1` | 0 | PASS |
| `fin_suite_c2p_t8` | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p -- --test-threads=8` | 0 | PASS |
| `fin_suite_c2u_t1` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u -- --test-threads=1` | 0 | PASS |
| `fin_suite_c2u_t8` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u -- --test-threads=8` | 0 | PASS |
| `fin_suite_c3_msrv_af` | `cargo +1.85.0 test -p quervant-core --lib --all-features c3_ -- --test-threads=8` | 0 | PASS |
| `fin_suite_c3_t1` | `cargo +1.98.1 test -p quervant-core --lib c3_ -- --test-threads=1` | 0 | PASS |
| `fin_suite_c3_t8` | `cargo +1.98.1 test -p quervant-core --lib c3_ -- --test-threads=8` | 0 | PASS |
| `fin_suite_integration` | `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --test-threads=1` | 0 | PASS |
| `fin_suite_pr15h_a` | `cargo +1.98.1 test -p quervant-core --test pr15h_a_candidate_materialization` | 0 | PASS |
| `fin_suite_pr15h_a2` | `cargo +1.98.1 test -p quervant-core --test pr15h_a2_dispatch` | 0 | PASS |
| `fin_suite_reader` | `cargo +1.98.1 test -p quervant-core --lib segment::reader::stored_blocks_reader_tests:: -- --test-threads=8` | 0 | PASS |
| `fin_suite_score` | `cargo +1.98.1 test -p quervant-core --lib search::score::tests:: -- --test-threads=1` | 0 | PASS |
| `fin_u01` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u01_winner_score_count -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u02` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u02_dispatch_and_count_matrix -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u03` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u03_uncertified_stats_eager_precedence -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u04` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u04_corruption_precedence -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u05` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u05_native_later_segment_boundary -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u06` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u06_b3_refusal_matrix -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u07` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u07_replacement_and_final_identity -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u08` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u08_rank_ties_and_null_order -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u09` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u09_logical_budget_edges -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u10` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u10_cancel_poll_parity -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u11` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u11_seeded_final_scores -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u12` | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u12_private_representation -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u13` | `cargo +1.98.1 test -p quervant-core --lib search::unified::b3_tests::c3_u13_collision_with_deferred_frequency -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `fin_u14` | `cargo +1.98.1 test -p quervant-core --lib search::unified::b3_tests::c3_u14_multione_deferred_scores -- --exact --nocapture --test-threads=1` | 0 | PASS |
| `qa_bench_norun` | `cargo +1.98.1 bench --workspace --no-run` | 0 | PASS |
| `qa_bench_scripts` | `bash benchmarks/scripts/test-scripts.sh` | 0 | PASS |
| `qa_clippy_185` | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| `qa_clippy_185_af` | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `qa_clippy_198` | `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| `qa_clippy_198_af` | `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `qa_cov_198` | `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | 0 | PASS |
| `qa_cov_198_af` | `cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | PASS |
| `qa_doc_198` | `cargo +1.98.1 doc --workspace --no-deps` | 0 | PASS |
| `qa_doc_198_af` | `cargo +1.98.1 doc --workspace --all-features --no-deps` | 0 | PASS |
| `qa_fmt_185` | `cargo +1.85.0 fmt --all -- --check` | 0 | PASS |
| `qa_fmt_198` | `cargo +1.98.1 fmt --all -- --check` | 0 | PASS |
| `qa_test_185` | `cargo +1.85.0 test --workspace --all-targets` | 0 | PASS |
| `qa_test_185_af` | `cargo +1.85.0 test --workspace --all-targets --all-features` | 0 | PASS |
| `qa_test_198` | `cargo +1.98.1 test --workspace --all-targets` | 0 | PASS |
| `qa_test_198_af` | `cargo +1.98.1 test --workspace --all-targets --all-features` | 0 | PASS |
| `source_audit` | `python3 docs/pr-artifacts/perf-06-c/evidence/c3/source_audit.py 6bc977e6a26c183609b7ca53eca51d3ab09ce337 6ea6b7ce049d613a29864f1eae53dea5fd61e75f /tmp/c3evidence/source-audit.md` | 0 | PASS |

## 13. Exceptions and unresolved items

* **No authorized exceptions were requested or granted.** No performance
  benchmark, profiler, timing acquisition, C4 implementation, merge or baseline
  promotion was performed.
* Applied decision rules: D01/D03 (branch exactly at `B`), D02 (disjoint
  untracked prior evidence left untouched), D08 (mechanical lifetime elision,
  MSRV lint-clean nested `match` instead of a let-chain, `ok_or` instead of
  `ok_or_else`, range-loop to iterator, comment restoration), D09 (expected
  RED), D17 (expected negative acceptance rows), D18 (the `c3_` substring
  inventory collision reported exactly, no test renamed or skipped), D19
  (comment-only correction produced a new immutable `TESTED` and full repeat of
  every affected check), D24 (report exact unambiguous counts), D31 (no
  performance acquisition).
* **Known limitations:** the certificate is deliberately conservative and
  sufficient, not necessary; certified requests with unusual-but-valid
  statistics fall back to eager C2. The physical heap entry grows by one `u64`
  word; C4 must measure absent/rare lanes and layout/codegen effects. No
  performance improvement is claimed.

---

# Errata and closeout (PERF-06-C3-F1, 2026-11-26)

This section is an **append-only correction** of specific statements above. The
historical text is retained verbatim as the record of what was claimed at the
time; nothing above has been rewritten. Plan:
[PERF06C3F1_DETAILED_FIXUP_PLAN.md](PERF06C3F1_DETAILED_FIXUP_PLAN.md); F1
report: [PERF06C3F1_EXECUTION_REPORT.md](PERF06C3F1_EXECUTION_REPORT.md).

1. **Coverage column mislabel.** The §5 and §9 gate values `93.85 %` / `93.54 %`
   were **region** coverage, not line coverage. The actual historical **line**
   coverage from those same receipts is:
   `qa_cov_198.json` → total 77,232, missed 5,023, covered 72,209 → **93.50 %**;
   `qa_cov_198_af.json` → total 78,742, missed 5,438, covered 73,304 → **93.09 %**.
   Both exceed the 85 % line floor; this is a reporting correction, not a
   coverage failure. F1 reports measured **Lines** separately.
2. **U02 matrix domain.** The earlier `25` rows iterated `M = K+1+delta` with
   `delta ∈ [-2..2]`, i.e. `M ∈ {K-1, K, K+1, K+2, K+3}`, not the planned
   `M ∈ {0, 1, K, K+1, K+2}`. The earlier `C3 U02 split ... final-calls=12`
   diagnostic read the live counter **after** the Legacy reference run, so `12`
   was the Legacy count; the certified split assertion itself correctly observed
   `10`. The corrected empty/singleton matrix had not been executed before F1.
3. **U04 C29 descriptor.** The earlier `C29` row also set the final-posting
   mutation flag (`record == 29`), so it was not an isolated column-29 case; the
   isolated `C29` name was therefore not established. F1 makes it column-only and
   validates the nine descriptors against a literal ordered table.
4. **I02 later-page oracle coverage.** The earlier I02 verified later-page keys,
   counts and cursor continuation, but its per-hit score/field oracles covered
   only the first page of the old and new views. F1 validates every hit of all
   five view phases (198 checks).
5. **S01 guard independence.** The earlier `df = 0` and `df > n` rows also
   removed the prepared IDF, so they could pass through the independent
   missing-IDF refusal even if the advertised df guard were broken. The earlier
   PASS therefore did not independently prove those two guards.
6. **U09 exact-peak expectation (author correction).** The original plan's
   "any exact-peak failure must have no final scores" was **too broad** for the
   prescribed request. The accepted checkpoint order is collection/finalization
   then projection; for `M = 102, K = 100` at the exact virtual peak the
   projection ledger refuses with `ResourceLimit { 13056, 13160 }` **after**
   exactly 100 private scores and 100 recorded identities were computed. The
   earlier generic `scores == 0 || scores == K` allowance was **not** previously
   authorized; F1 replaces it with the literal twelve-row table and this single
   documented projection checkpoint.
7. **U04 execution classification.** The nine U04 rows are **eight byte-only
   corruption cases plus one real key-byte fault combined with
   `INJECTED_C2_ONLY`**; three column rows fail **before route dispatch** and are
   not C3 candidate execution. No assertion claimed that all nine executed C3
   candidate handling.
8. **Workspace test counts.** The all-visible sums `2759` / `2804` include ten
   child-process passes. The parent libtest totals are `2749 / 0 / 16 ignored`
   (default) and `2794 / 0 / 100 ignored` (all-features) on both toolchains;
   Criterion test-mode targets (10) and ignored tests are separate scopes; **no
   doctest target appeared** in those `--all-targets` commands.
9. **Hosted run closeout.** Run
   [45925006538](https://github.com/yduchesne/quervant/actions/runs/45925006538)
   (`pull_request`, attempt 1, workflow head `START`) **completed successfully**;
   all five jobs succeeded. Its workflow metadata identifies the PR head
   (`ee77917…`), while the job checkout identifies the separate GitHub merge
   commit `592241ec0ad408f30cbe1a0ab6cc0b7968aa56b6`. The `rustfs` job
   (`140264172087`) log contains 32 `test result: ok` summaries summing to
   **65 passed / 0 failed / 0 ignored** across repeated invocations, 37 unique
   named real-service tests and 53 top-level `test … ok` lines; that is not 32
   unique test bodies. The earlier "pending" observation was truthful at the time.
10. **Broad `c3_` inventory.** The `--lib c3_` count of `26` comprises **17 new
    PERF-06-C3** registrations plus **9 unrelated pre-existing**
    `search::unified::tests::c3_*` accounting tests. The original
    implementation-plan expectation of `17` for that broad filter was an author
    mistake; no test registration changed.
