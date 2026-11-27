# PERF-06-C3 — Certified deferred BM25 for strict-term ordinal Top-K

**Repository:** `yduchesne/quervant`

**Plan date:** 2026-11-26 (Pacific Time)

**Required base:** merged `main@6bc977e6a26c183609b7ca53eca51d3ab09ce337`.

**Predecessor:** PR #131 is merged (verified `merged=true`; merge commit is the base above). Its final reviewed branch head was `da033ff19b3facd4f0a5319506a64e658156e93f`. C2 is accepted for correctness, not for performance. The historical reports in the merged tree remain historical; their earlier unmerged/G10-open wording is not a current PR-state assertion.

**New branch:** `dev/perf06-c3`, from the required base. Create one draft PR against `main`; suggested title: `PERF-06-C3: certify and defer strict-term ordinal BM25 to returned hits`. Do not guess the PR number. The branch did not exist in the authoring-time branch search. Do not merge.

**Authoring validation:** the pinned source/contract, fixture helpers, toolchain versions, call sites and error variants were inspected; the proposed Rust has not been compiled or executed in the authoring environment. All code-level and empirical acceptance remains to be established by the executing agent. Any contradiction with the pinned source must follow the STOP rules, not an inferred replacement design.

**Authority:** `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md` §§3–8; `docs/PERF_OPTIMIZATION_ROADMAP.md` PERF-06-C3 row; `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`; `AGENTS.md`; `docs/TESTING.md`. This plan specifies the implementation, not a menu of alternative designs. The maintainer's authorization to execute this plan approves its bounded private representation and the decisions in §11. It does not approve a semantic change or performance claim.

> **Continuous execution authorization:** Execute the approved plan from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, permitted AUTO-RESOLVE decisions, and ordinary verification checkpoints. Stop affected work only for an explicitly applicable HARD STOP, a genuinely missing human decision, or an essential external dependency that prevents that work. When the obstacle is isolated, record its scope and continue every independent, safe, authorized task. Do not reinterpret an informational checkpoint as a request for approval.

**Terminal deliverable:** implementation, executed correctness evidence, ordinary repository QA and independent-review handoff. No actual performance benchmark, profiling, timed cross-engine run, qualification campaign, C4 implementation, merge, or promotion of a performance baseline is authorized. The host may be assumed available for ordinary tests; no performance acquisition is authorized by this assumption.

## 1. Purpose and current-main delta

C2 already removes the second full-match scored pair vector. It validates the complete postings stream, retains one `(u64 doc_id, u64 freq)` vector, charges the accepted logical matched/scored reservations, rewrites each frequency word to score bits using the existing `FieldStats::bm25_score`, then hands every scored match to B2/B3. The ordinal heap owns at most K+1 competitive entries. It retains exact hit counts, tie ordering, key validation, cursor and projection behavior.

C3 removes the **unnecessary BM25 arithmetic on rejected and subsequently evicted candidates and on the extra cursor lookahead**. For a request certified safe, retain the exact integer frequency of each temporarily competitive entry, then calculate only the returned K scores after global heap selection. Do not skip decoding, logical admissions, counting, key/column validation, duplicate checks, or existing fallible key/sort materialization.

The distinction between *competitive provisional entries* and *final returned hits* is essential. Existing B2/B3 materialize a key and sort tuple when a candidate is competitive, before the fallible heap admission, including replacements and the K+1 lookahead. A later eviction does not retroactively make these allocations unnecessary under the accepted failure contract. Do not move these fallible operations to finalization or invent a borrowed-key heap. Preserve them exactly; C3 defers only score/output materialization that is proven non-erroring. Final stored-field projection remains the existing selected-hit projection. This is the narrow C1 §5/§7 interpretation: losers own nothing beyond existing B2/B3 obligations; no new loser score or projected result object is created.

One dominant architectural concern: **only defer a potentially fallible computation when a request-wide proof establishes it cannot fail for any valid decoded match, and preserve the existing allocation/error boundary otherwise.**

## 2. Source admission and reuse

### 2.1 Authoring-time source anchors

The following paths and blobs were inspected at the pinned merged base. Line numbers are navigation aids, not instructions to edit a line number blindly.

| Path | Git blob / relevant symbols |
| --- | --- |
| `Cargo.toml` | `40bd37bd5314009eeb7b81f201f5ae0180be26f7`; workspace core/objectstore/distributed; MSRV 1.85 |
| `rust-toolchain.toml` | `73cb934de4706a914c15e8db2a3c037ce75699d9`; stable, fmt, clippy |
| `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` | `c871d370dc050fad9457bfa81a8421dbb846fbf2` |
| `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md` | `09333d930f46778536d9a9c6d93f6738b26fb2c6`; §5 certificate contract |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | `2de7f7fc3c5037a0e5584dc85f4b1bff9005bbf3` |
| `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` | `f77507ecdc99f61426ece75a1d49bcbce5bdb1de` |
| `AGENTS.md` | `08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c` |
| `docs/TESTING.md` | `91c8643eaa041b0cb475949bcefa7c074ae27fe3` |
| `.github/workflows/ci.yml` | `e8aeae6a892c76a295c27541397c1a504c77c4e3`; stable 1.98.1, MSRV 1.85.0, 5 ordinary jobs |
| `crates/quervant-core/src/search/score.rs` | `249122b50e2504593dc33056965dee366f31ab4b`; `bm25`, `idf_log`, `prepare_idf`, `bm25_with_idf`, `FieldStats`, `SnapshotStats`, `compute_stats` |
| `crates/quervant-core/src/search/execute.rs` | `942cfb313091931ae9059208440615e2e5209590`; `build_leaf_data`, `SegmentCandidateLedger`, `effective_live_examination_count`, `take_strict_one_term_postings`, `visit_strict_term_scored_with`, `c2_observation`, `c2_physical_tests` |
| `crates/quervant-core/src/search/unified.rs` | `647ee3a27e4d99b30eed55b0133abdc2a25b40bd`; `strict_term_dispatch_eligible` (~663), `collect_mixed` (~714), `collect_mixed_legacy_body` (~992), `collect_strict_term_ordinal_body` (~1367), `SelectedHit` (~1600), `d3c::State`, both ordinal candidate handlers (~2990/3157), `MixedEntry` (~3283), `project_selected_hits` (~3510), C2 tests (~11363) |
| `crates/quervant-core/src/search/typed_compare.rs` | `08b4c13d9282362295904509035a6e3cab9b44b0`; `ordinal_sort_key_cmp`, `compare_candidates` |
| `crates/quervant-core/src/search/work.rs` | `e1f3b2ff06ad44ec27256dbc1d15939ce41e2532`; `MixedWorkMeter` |
| `crates/quervant-core/src/search/unified_cursor.rs` | `28cd401eb4208ad20d9a07d70dd04b9d6d91072c`; existing binding/fingerprint/last key/sort/score |
| `crates/quervant-core/src/segment/postings.rs` | `4a3abeeb921cb5ca8ecbbd93a2b71c49c4f3f538`; `DocFreqPostingsReader::next_with` delegates to `read_one_with` which validates nonzero frequency, ordering, bounds, positions and stream termination |
| `crates/quervant-core/tests/perf06_c2_physical.rs` | `7bf4601451bcef1ee974088c638375e2c4049bc6`; real `FsDirectory` corpus/score/cursor/PIT/resource tests |

### 2.2 Admission commands (G0)

From the repository root, before editing:

```sh
git remote get-url origin
git status --porcelain=v1 --untracked-files=all
git fetch origin --prune
gh pr view 131 --repo yduchesne/quervant --json number,state,mergedAt,mergeCommit,headRefOid
B=6bc977e6a26c183609b7ca53eca51d3ab09ce337
test "$(git rev-parse origin/main)" = "$B"
git cat-file -e "$B^{commit}"
git ls-remote --heads origin dev/perf06-c3
git branch --list dev/perf06-c3
```

Require the repository identity, merged PR, exact main and every blob in the table (`git rev-parse "$B:<path>"`). Do not edit an older PR. Create from `origin/main` using `git switch -c dev/perf06-c3 origin/main` only if neither local nor remote branch exists. An existing C3 branch exactly at B with no work is admissible under D03; otherwise STOP for a continuation plan. No force-push/reset/stash/delete, no rebase over unseen main. The agent may fetch and inspect a new main but cannot decide a new baseline. Record clean tracked status and any foreign untracked paths; leave them alone if disjoint from all planned inputs/outputs. An untracked/ignored Cargo configuration, source shadow, or input that might alter compilation is not disjoint.

Verify the entire current contract, guide, AGENTS, TESTING, the relevant function bodies and tests, the workspace and actual CI. Inspect the existing storage interfaces (`Directory`, `SegmentStore`, `SegmentCache`, `ObjectStore`), snapshot binding and immutable guard lifetimes to confirm no new storage or format responsibility. Inspect `rg` occurrences of `MixedEntry`, `visit_strict_term_scored_with`, `consider_ordinal_keyword_candidate`, `consider_compact_ordinal_candidate`, `bm25_score` and `ScoreFailureArm`. Check for an existing C3 implementation or duplicate certificate abstraction. The authoritative source anchors above take precedence over old plans and reports. Record the source inventory and no-existing-C3 conclusion; source contradiction => D04, not redesign.

Use stable toolchain `1.98.1` and MSRV `1.85.0`, verified from CI. Record versions of `rustc`, Cargo, `cargo-llvm-cov`, Python and Git; use `env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE` for every Rust command (unset these in the executing shell as well). Do not introduce a C3 feature or environment switch. Preserve all repository features, including the existing experimental duplicate strategy configurations. Capture baseline checks before modifying production source (see §10).

### 2.3 Current source behavior that must not be rediscovered by the agent

- `compute_stats` counts N with checked `u64` sums, then field `total_length` with checked `u64` additions; persisted norms all-live path uses norm total and dictionary df; partially-live path sums selected lengths and validates/scans queried postings; legacy path reconstructs bounded lengths using real postings. `avgdl = total_length as f64 / n as f64` for `n>0`, else 0. The prepared IDF is generated only after final df/n. Do not recompute stats or IDF.
- `FieldStats::length` is total over `(segment_index,doc_id)`, returns a `u64` (0 for absence). It cannot raise a scoring error. Keep its exact behavior and all earlier reader/norm validation; don't turn missing length into a new corruption rule or validate tf <= dl.
- C2's `strict_term_dispatch_eligible` checks the existing compiled shape, one sortable Keyword ordinal field and `field.doc_freq(term) > K+1`. The field that supplies BM25 may differ from the sort field. Do not accidentally use the sort field as the scoring field. Do not add a second query compiler, count scan, B1 map, or second postings decoder.
- `collect_mixed` performs shared validation/statistics/ordinal/duplicate state preparation, then makes one physical-family decision. C2 per-segment setup is column, bound ordinal and translation, JSON and geo setup, evaluator, key binder on first candidate, collect, geo cleanup. Never eagerly bind later segment columns to establish C3 safety. Preserve the segment order (content-addressed manifest order, not insertion order).
- `MixedEntry::cmp` compares relevance only when `relevance=true`; ordinal entries are `false` and `ordinal_sort=Some`, using `ordinal_candidate_order` with exact ascending logical-key ties. `d3c::State::{check,check_compact,admit}` and `candidate_charge` use key, sort, charges, and `Ord`, not the score. The final cursor stores `last_score=None` for explicit sort; `project_selected_hits` reads physical segment/doc IDs and keys, not frequency. These are the premises allowing deferral.
- `select_keys` uses a separate complete-membership path. Relevance, typed, batch, aggregation, follow-on cursors, non-strict terms and B1 NotAvailable must retain Legacy. C2 eagerly scores for any strictly selected but uncertified request. B3 optional refusal uses its existing owned-key B2 fallback *within* the chosen family, not a request replay.

## 3. Correctness contract and safety proof (G1)

### 3.1 Invariants and traceability

| ID | Falsifiable invariant | Implementation / acceptance |
| --- | --- | --- |
| I01 | No new eligible shape. Exactly one family choice; exactly one C3 certification attempt for a strict request; Legacy is not replayed. | P2/P3/P4; U02/U03/U10; existing C2 U01/U02/U19/U20 |
| I02 | Every valid decoded matching posting has a non-erroring finite nonnegative score under the certificate; any unproven input takes C2 eager before any candidate. | P1; S01/S02/U03/U04 |
| I03 | Full posting validation and exact count preserved; no early exit after K or K+1; zero/deleted postings handled as before. | P2/P3; P01/U02/U04/U05/U11; C2 U06/U21 |
| I04 | On certified success actual `bm25_score` calls equal returned hits, not admissions, M, or K+1. Raw `u64` tf and physical identity stay associated through replacement and across segments. Score bits exactly equal eager and Legacy. | P1–P4; S02/P01/U01/U07/U11/I01–I02 |
| I05 | All numeric ordering, missing/null placement, tie keys, B3 hash equality, fallback and MultiOne decoding retain B2/B3 behavior. | P3; U06/U07/U08/U13/U14, existing B2/B3 regressions |
| I06 | Exact old work charges, virtual `16/48/64*M` admissions, global+segment/duplicate heap budget, release order and typed errors. No extra M allocation and no side heap. | P2/P3; P01/U05/U09; C2 P05/U10/U11/I08 |
| I07 | Real faults in unselected matches still surface with the same nested error; invalid score remains at eager score checkpoint; malformed later segments never cause earlier checks to be bypassed. | P1–P4; U03/U04/U05, retained C2 U12/U17 |
| I08 | Cursor, projection, snapshot/PIT, cancellation checkpoint schedule, retry and sibling APIs unchanged; no partial page. | P3/P4; U02/U05/U10/I01–I03; all C2 integration/regression |
| I09 | No production counters, global test interference, format/ABI/wire/API changes or new dependencies; legacy hot loop unchanged except explicit representation plumbing. | P1–P4; source audit + U12; both feature regimes and CI |
| I10 | Final results and evidence tied to immutable tested source; no claimed performance benefit or hidden failed check. | §10/§12; C4 owns performance |

### 3.2 The only authorized certificate

Let `T` be the scoring field's sum of effective-live field lengths, `n` the checked total effective-live document count, `df` the prepared term's document frequency, `tf` its decoded frequency, `dl` the `u64` document length, and `a=avgdl`. In normal `compute_stats`, both T and n are checked `u64`, and `a=T as f64/n as f64` for n>0. Conversion to f64 is monotone; `u64::MAX as f64` rounds to exactly 2^64. If T>0 and n>0, `2^-64 <= a <= 2^64` inclusive. These bounds are exactly representable binary64 constants; no approximate integer narrowing is necessary. The norm source may produce length 0, including an absent field; the proof covers the entire `u64` domain, so no scan for max length or minimum tf is needed.

`idf_log(df,n) = ln(1+(n_f-df_f+0.5)/(df_f+0.5))` with `df<=n`, `df>=1`. Monotone rounding implies `n_f>=df_f`, denominator >=0.5, argument finite and >=1; max argument <=1+2^65 (conservatively), so natural log <= 65 ln(2) plus negligible rounding < 46 < 64. The code consumes its existing prepared result rather than recomputing log. Explicit runtime guard `idf.is_finite() && (0.0..=64.0).contains(&idf)` verifies sufficient bounds even for unusual/synthetic statistics. A stored `-0.0` compares equal to zero; the existing `+0.0` accumulator preserves accepted output bits. No requirement to compute IDF a second time to prove its exact value: in real source it is immutable and produced by `prepare_idf` once; any certified bounded IDF uses the *same* actual prepared value as C2.

For any `tf>=1` decoded by the real posting reader, `tf_f` is finite in [1,2^64], `dl_f` in [0,2^64]. `BM25_K1=1.2` and `BM25_B=0.75` are pinned constants. Preserve the expression in `bm25_with_idf` exactly:

```text
denominator = tf_f + 1.2 * (1.0 - 0.75 + 0.75 * dl_f / a)
score = idf * (tf_f * (1.2 + 1.0)) / denominator
```

Even with conservative round-up allowances, the division `0.75 * dl_f / a` is <=2^128, the normalization product and sum <2^131, and the denominator is finite, positive and >=1. `tf_f * (1.2+1.0)` <2^66; IDF <=64 implies numerator <2^72. Every intermediate is far below binary64 overflow (near 2^1024), and all nonzero divisors are positive. Roundoff cannot make nonnegative values negative; underflow to zero is acceptable. Thus the score is finite and >=0, and `bm25_with_idf` cannot produce `InvalidScore`. The exact `+0.0` addition used by C2 cannot create an error. No score-dependent ordering or cursor field consumes a deferred value. The proof is uniform over all segments/documents, not sampled and not dependent on a future winner. Rust f64 operations remain in original grouping; no fused multiply-add/reassociation, no scalar rewrite, no floating representation of raw frequency.

The selector is intentionally conservative. The only approved certificate is for present positive n, present positive df with df<=n, present bounded prepared IDF, and finite avgdl in [2^-64,2^64]. Everything outside these conditions takes the existing eager C2 if C2 was already selected, otherwise Legacy. The proof does not authorize errors or zero shortcuts at preparation. No new logical work charge for a constant-time metadata predicate or for scoring only K: existing BM25 itself did not charge a separate per-score work unit, and C2 charges the complete original N/scanned/virtual ledger. Certificate uses two borrowed references (fixed stack state); no allocation, lock, IO, or new cancellation poll. Keep existing `compute_stats` and work accounting unchanged.

### 3.3 Case matrix for `bm25`, `bm25_with_idf` and `FieldStats::bm25_score`

Actual decision order in `FieldStats::bm25_score`: absent term calls scalar df=0; early zero on tf=0/n=0/avgdl<=0; invalid df>n; df=0 scalar fallback; missing prepared IDF => `CorruptIndex`; then prepared arithmetic. Scalar `bm25` similarly returns zero *before* df>n; otherwise calls `idf_log`, then `bm25_with_idf`. This table is normative; never promote a failure to certificate preparation.

| Case | Certificate / production route | Existing outcome retained |
| --- | --- | --- |
| Valid positive n/df, present IDF in [0,64], avgdl within proof bounds, valid decoded tf>0 | Certify C3 iff all C2 requirements already true | Non-erroring, bit-identical returned scores |
| tf=0 in authenticated posting payload | No valid decoded candidate; decoder rejects | `SearchError::Segment(SegmentError::ZeroFrequency { doc_id })` at original posting boundary, before callback; scalar synthetic tf=0 returns +0.0 before invalid df/IDF; do not change either |
| n=0 or avgdl=0, negative, negative infinity | No certificate; eager if strict family already selected | `Ok(0.0)` for matched scorer early-zero branch even with later invalid df or missing IDF; no invented corruption |
| avgdl NaN | No certificate | For otherwise valid positive tf/df/n, arithmetic returns `InvalidScore { detail: "BM25 produced a non-finite or negative score" }` |
| avgdl +infinity, positive below 2^-64, above 2^64 | No certificate, even if particular score would be finite | Call exact eager arithmetic; preserve its result or error, not a guessed error |
| df>n with positive n and avgdl | No certificate | `InvalidScore { detail: "document frequency exceeds the live-document count" }` in first applicable segment scorer, not preparation |
| df=0 or missing term record | C2 count guard normally chooses Legacy; direct certificate refuses | Scalar df=0 fallback, not automatically zero (unless early zero branch applies) |
| Missing field stats | C2 count guard chooses Legacy; direct certificate unavailable | Existing scorer absence contributes +0.0; no new error |
| Valid df but missing prepared IDF | No certificate | `CorruptIndex { detail: "prepared BM25 IDF missing for valid term" }` at score site |
| Prepared IDF NaN, +infinity, negative (except signed zero) | No certificate | Eager exact InvalidScore when nonfinite or negative; earlier zero guards still win |
| Prepared finite IDF >64 | No certificate (conservative) | Existing eager result or error, including successful finite values |
| Extreme `u64` tf, dl, n, df (incl >2^53), IDF 0 or -0.0, avgdl bounds | Certificate iff other guards true | Preserve integer tf exactly; final score uses original `u64 as f64` conversion and exact accumulator |
| Test-only armed `execute::c2_observation::ScoreFailureArm` | Forced C2 eager, even with valid metadata | Existing synthetic score fault before per-segment candidates, labelled `INJECTED_C2_ONLY`; never use this injector to claim natural score corruption or same-fault Legacy parity |

### 3.4 State/ownership and ledger worksheet

```
shared existing preflight -> one C2 family decision
 Legacy -> unchanged legacy loop -> existing finalization
 Strict -> certify once (read-only)
   unavailable -> eager C2 (existing in-place score bits)
   certified -> C3 (untouched integer posting frequencies)
 per segment:
   existing bind/JSON/geo -> full decode -> N examination & membership polls
   -> P/S/T compatibility admissions -> eager score OR certified no-error phase
   -> drop leaf metadata -> release S/P/T -> ledger.finish -> drop ledger
   -> count each match -> existing B2/B3 validation/duplicate/competitiveness
   -> candidate heap with inline tf only for competitive C3 entries
   -> existing cleanup; release segment posting vector before next segment
 after all segments complete:
   sort bounded K+1 entries -> finalize only first K lexical scores
   -> existing cursor construction/truncate -> existing projection/response
```

| Checkpoint | Logical accounting (m live matches in this segment, G existing global charges) | Failure behavior |
| --- | --- | --- |
| Full decoder, including tombstoned rows | Existing `charge_scanned(freq)` (`1+freq` work); retain 16*m bytes/m entries, as today | Decode/limit/cancel error; RAII ledger unwinds; no candidate |
| N examination | Existing effective-live count/bitmap chunk polls + N lexical units, not m | Same typed error, no candidate |
| Membership | Each decoded live row once, existing per-posting poll | Same cancellation point |
| Matched admission | `m` entries / `48*m` bytes in addition to P | `preflight` then commit; exact checked limit |
| Scored admission | `m` entries / `64*m` additional bytes even when C3 skips arithmetic | Peak `3*m` entries and `G+128*m` bytes; same failure precedence |
| Score phase | Eager uses exact old rewrite; certified keeps raw tf (no copy, no extra vector); no new charge | Eager typed errors preserved; C3 proof establishes no score failure here |
| Release | Release matched, posting, scored in exact accepted order, finish, drop ledger before first candidate | RAII failure and no partial response |
| Candidate | Same B2/B3 owned materialization and global candidate charge `64+key_len+32+[keyword_len+4]` (MultiOne same existing calculation). Existing `d3c` table charges and preflight insert before release old. | No new/removed error or reservation; replacement at full heap preserves transient peak |
| Finalization | In-place score update on the already owned bounded heap entries; no new score allocation/IO; cursor and projection accounting unchanged | Typed unexpected internal mismatch, no replay, no partial page |

Explicit numerical checks: for K=1/10/100, m=K+2 => (entries, bytes)=(9,384),(36,1536),(306,13056). One-under must fail at the same checkpoint, and exact segment peak is admitted (subsequent heap may reject; compare exact verdict to eager). For any m in {0,1,K,K+1,K+2}, `3*m`/`128*m` are the same per-segment phase peaks if strict selected request-wide; an empty segment still pays N examination. The global retained G (including duplicate strategy accounting) participates in each later segment's peak and replacement. Do not substitute a per-segment C3 eligibility rule or charge only m or K. Public failures return `Err` with no partial page; scratch/heap are request-local and destroyed, immutable reader state remains usable. Existing accepted C2 virtual release occurs before callbacks even though the single posting allocation remains alive during callbacks; preserve this exact model, do not reinterpret it as measured RSS.

## 4. Prescribed implementation

Only the changes specified below are authorized. Do not choose a different implementation. Implement red-first per §6, then production P1–P4 in order. A small mechanical compile correction allowed by D08 is not permission to change a signature/contract below.

### P1 — private request-wide certificate (`score.rs`)

Do not edit any existing BM25 expression, `prepare_idf`, `compute_stats`, `FieldStats::length`, `FieldStats::doc_freq`, or `SnapshotStats` layout. Add the following private-to-crate proof token adjacent to `FieldStats`. The token borrows the immutable stats and exact normalized term, so it cannot outlive them or refer to a different query. Fields remain private to `score.rs`.

```rust
// PERF-06-C3: sufficient (not necessary) bounds on prepared BM25 arithmetic.
const C3_AVGDL_MAX: f64 = 18_446_744_073_709_551_616.0; // 2^64
const C3_AVGDL_MIN: f64 = 1.0 / C3_AVGDL_MAX;
const C3_IDF_MAX: f64 = 64.0;

pub(crate) struct DeferredBm25<'s, 'a> {
    field: &'s FieldStats<'a>,
    term: &'s str,
}

impl<'a> FieldStats<'a> {
    pub(crate) fn certify_deferred<'s>(
        &'s self,
        term: &'s str,
    ) -> Option<DeferredBm25<'s, 'a>> {
        let stat = self.df.get(term)?;
        let idf = stat.idf?;
        if self.n == 0
            || stat.doc_freq == 0
            || stat.doc_freq > self.n
            || !self.avgdl.is_finite()
            || !(C3_AVGDL_MIN..=C3_AVGDL_MAX).contains(&self.avgdl)
            || !idf.is_finite()
            || !(0.0..=C3_IDF_MAX).contains(&idf)
        {
            return None;
        }
        Some(DeferredBm25 { field: self, term })
    }
}

impl DeferredBm25<'_, '_> {
    pub(crate) fn matches(&self, field: &FieldStats<'_>, term: &str) -> bool {
        std::ptr::eq(self.field, field) && self.term == term
    }

    pub(crate) fn score(
        &self,
        segment_index: usize,
        doc_id: u64,
        tf: std::num::NonZeroU64,
    ) -> SearchResult<f64> {
        let dl = self.field.length(segment_index, doc_id);
        let mut score = 0.0_f64;
        score += self.field.bm25_score(self.term, tf.get(), dl)?;
        Ok(score)
    }
}
```

`matches` verifies the exact borrowed scoring field/term at the deferred visitor's already validated shape boundary (not the sort field, not a new stat lookup per hit). `score` is the only deferred scorer; no second formula, no `unwrap`, no `unsafe`, no float tf transport, no score cache. If the borrowed reference lifetime requires an explicit generic lifetime on `impl`/`matches` to compile, D08 permits only lifetime annotation preserving reference identity and no new ownership. Verify against both toolchains. Do not turn certificate rejection into an error. Document proof from §3 next to the bounds (brief and link contract/report).

**Test-only instrumentation:** add `#[cfg(test)]` module `c3_score_observation` in `score.rs`. Use `thread_local!` with `Cell<usize>` actual `BM25_CALLS`; `reset`, `calls`, `record_call` analogous to existing IDF observation. Insert only `#[cfg(test)] c3_score_observation::record_call();` as first statement of `FieldStats::bm25_score`. This observes *actual* calls through the one accepted scorer including eager/reference calls; never count based on estimated M or final page length. No reset inside production requests. Test-only synthetic fault seam (see P5) lives in this module; no mutation method in normal build. Keep the prior C2/A1/A2 counters unchanged. This is a TLS observation, not a cross-thread aggregate.

### P2 — preserve one posting allocation and exact C2 preparation (`execute.rs`)

Refactor only `visit_strict_term_scored_with` into a shared private const-generic implementation and two thin typed entry wrappers. Do not modify `build_leaf_data`, the decoder, generic scorer, generic membership visitor, `SearchWork`, or ledger operations. `use super::score::DeferredBm25` (add to existing import). Preserve all existing arguments/order in the old wrapper.

1. Rename the old body to `fn visit_strict_term_payload_with<const DEFERRED: bool, F>(...) -> SearchResult<()>`. Its parameters are the old `visit_strict_term_scored_with` parameters with `certificate: Option<&DeferredBm25<'_, '_>>` immediately before the final callback and `mut on_payload: F` replacing `mut on_scored`. Bound `F: FnMut(u64, u64, usize, &mut CandidateBudget) -> SearchResult<()>`. The second `u64` is the raw word, not an f64.
2. From the first C2 observation through `m`, both virtual reservations, and release sequence, mechanically retain the old statements with the following sole changes. Immediately after the existing `let term = match leaf_data.as_slice() ...` (where field and term are known), insert the check below. It fails only on an internal misuse of the private function, not on a real certificate rejection (which has already selected eager). No per-document certificate test.

```rust
if DEFERRED {
    let cert = certificate.ok_or_else(strict_term_shape_error)?;
    let field = stats.field(field_id).ok_or_else(strict_term_shape_error)?;
    if !cert.matches(field, term) {
        return Err(strict_term_shape_error());
    }
} else if certificate.is_some() {
    return Err(strict_term_shape_error());
}
```

3. Wrap the existing entire eager scoring phase (starting `#[cfg(test)] c2_observation::record_inplace_start(&scored_postings);` through `record_inplace_finish`) in `if !DEFERRED { ... }`. It must be byte-equivalent aside from indentation; keep `ScoreFailureArm`, field stats lookup, `let mut score = 0.0_f64; score += contribution; row.1 = score.to_bits()` and the whole-segment completion observation. Rename the local `scored_postings` to `postings` consistently if desired only under D08; preferred keep the original name with comment that under DEFERRED the word remains tf. No new loop to validate or rewrite frequencies under DEFERRED: the accepted decoder already proved positive integer frequency and every row receives the original membership poll. The const parameter creates two monomorphizations; no runtime per-hit scorer dispatch.
4. Keep drop/release/finish sequence exactly. Change only the final callback argument to `on_payload(*doc_id, *word, matched_count, budget)?;` and keep `c2_observation::record_callback()` immediately after successful callback. Thus the original C2 common witness counts successful deferred callbacks too, while `converted_rows()` remains zero for C3. The whole old function is still the only place that decodes this term. Do not build an extra vector or retain a segment vector across segments.
5. Restore `pub(crate) fn visit_strict_term_scored_with<F>` with the original argument types and names, calling `visit_strict_term_payload_with::<false, _>` with the same inputs, `None`, and `|doc_id, bits, matched_count, budget| on_scored(doc_id, f64::from_bits(bits), matched_count, budget)`. Its `F` and `mut on_scored` signature stays exactly as old; all old direct tests remain unchanged. This wrapper remains used by production eager C2.
6. Add `pub(crate) fn visit_strict_term_deferred_with<F>` with the same input parameters plus `certificate: &DeferredBm25<'_, '_>` immediately before `mut on_candidate: F`. Its bound is `F: FnMut(u64, std::num::NonZeroU64, usize, &mut CandidateBudget) -> SearchResult<()>`. It calls `visit_strict_term_payload_with::<true, _>` with the exact inputs, `Some(certificate)`, and this closure:

```rust
|doc_id, tf, matched_count, budget| {
    let tf = std::num::NonZeroU64::new(tf).ok_or_else(|| {
        SearchError::Segment(crate::segment::SegmentError::ZeroFrequency { doc_id })
    })?;
    on_candidate(doc_id, tf, matched_count, budget)
}
```

The zero guard is defensive; the only actual producer is the existing full decoder that already rejects zero before any callback. Do not use `new_unchecked` or relax decoder checks. Do not add any other new error. `pub(crate)` matches the existing internal execute seam; no re-export or public API. Add test-only `c2_observation::score_failure_armed() -> bool` reading the existing `SCORE_FAILURE_DOC` TLS without resetting it, for P4's eager override. The existing C2 physical tests call the restored eager wrapper and are byte-identical. No changes to generic `evaluate_lexical_with` or `visit_lexical_membership_with`.

### P3 — one inline frequency, reuse exact ordinal collectors (`unified.rs`)

**Prescribed representation decision:** keep `SelectedHit`, `ProjectedHit`, `UnifiedResponse`, `UnifiedCursor`, `MixedEntry` comparator and all charge formulas unchanged. Add exactly one private field to `MixedEntry<'a>`:

```rust
    /// C3 only: positive raw term frequency for this retained physical hit.
    /// Present iff the hit has not yet been scored by the certified route.
    /// Eager/Legacy entries always use None. Never consulted by Ord or d3c.
    deferred_tf: Option<std::num::NonZeroU64>,
```

Why not an M-sized side map, an f64 bit pun or a second decoder? The inline integer is typed, lossless, follows the exact entry across heap push/pop/sort/replacements, needs no allocation or identity lookup, and never changes public score type. Rust's `Option<NonZeroU64>` niche is one u64 word; the accepted base logical charge is a compatibility policy, not `size_of::<MixedEntry>()`. It remains unchanged. This can increase the physical heap entry size by up to one word (measure actual old/new size and alignment; test U12 uses an old-layout mirror). Physical overhead is bounded by the *existing* heap capacity times that word; do not call the logical bytes a physical bound or claim a free optimization. This is a deliberate representation choice to avoid changing relevance comparisons or smuggling a raw tf into an f64; C4 must guard absent/rare and all other required lanes for layout/codegen effects. If on the supported host the size increases by more than one u64 word or alignment changes, STOP D10, no unsafe packing or alternative representation.

1. All existing `MixedEntry { ... }` literals get `deferred_tf: None`, including the generic legacy direct entry, borrowed-key entry, ordinary keyword entry, and test constructors. The two ordinal constructors instead use the parameter below. No other struct field or function comparison changes. At the pinned base there are 9 actual `MixedEntry` literals (5 production, 4 test). Verify using `rg -n 'MixedEntry\s*\{'`, excluding comments/declaration; if inventory differs, D04. Struct declaration uses `MixedEntry<'a> {` not the literal pattern.
2. Add `deferred_tf: Option<std::num::NonZeroU64>` immediately after the existing `include_score: bool` parameter to *only* `consider_ordinal_keyword_candidate` and `consider_compact_ordinal_candidate`. Keep both functions' existing bodies/order verbatim except store `deferred_tf` in their constructed `MixedEntry` instead of `None`. The existing `score: if include_score { Some(score) } else { None }` remains unchanged. For all existing call sites in Legacy and existing B2 tests pass `None` after `scoring`/`true`. At base `consider_ordinal_keyword_candidate` has 6 call sites (Legacy, C2, four direct B2 calls); `consider_compact_ordinal_candidate` has 2 (Legacy, C2). Update the two C2 sites per P4 to pass the closure's value. If any additional call site is found, STOP D04 and inspect, do not blanket add a default argument blindly.
3. Do not add a conditional inside `MixedEntry::cmp`, `candidate_charge`, `d3c::State` or `heap_admit_candidate`. The only constructor allowed to pass `Some(tf)` is the certified strict route's typed deferred callback. It always uses `score=0.0`, `include_score=false`, `deferred_tf=Some(tf)`. `0.0` is an unused argument to the existing include-score branch, not a user score or encoded tf. Every eager caller uses original score and original include-score flag, `None` tf. The existing ordinal constructors set `relevance=false` and `ordinal_sort=Some(prepared.numeric)`; thus C3 entries cannot take relevance comparison. Full sort/key/duplicate validation and all fallible ownership and heap charges stay exactly where they were. `MultiOne` still decodes its full tuple even for losers; owned-key fallback still owns keys as required. Never defer an allocation that formerly could fail before a later segment/error.
4. `SelectedHit` and the public projection/handoff are protected. Do not introduce a second heap, separate frequency table, full-M index, new score enum in public types, re-open for tf or compute BM25 for a provisional insertion. Entry replacement/pop drops frequency together with the entry. Do not apply `key_hash` as identity or use it to retrieve a frequency.

### P4 — select C3 once, use typed visitor, score only returned entries (`unified.rs`)

Import `DeferredBm25` alongside `SnapshotStats` and `compute_stats`. Keep `strict_term_dispatch_eligible` byte-identical. Add a private helper `fn strict_score_certificate<'s, 'a>(plan: &'s UnifiedPlan, stats: &'s SnapshotStats<'a>) -> Option<DeferredBm25<'s, 'a>>` near the dispatch code. Its body:

```rust
#[cfg(test)]
if c3_observation::eager_forced() || execute::c2_observation::score_failure_armed() {
    return None;
}
let [CompiledLeaf::Term { field_id, terms }] = plan.lexical_leaves.as_slice() else {
    return None;
};
let [term] = terms.as_slice() else { return None; };
stats.field(*field_id)?.certify_deferred(term.as_str())
```

No compiler, new analysis, lookup beyond the existing stats field/term, or additional validation error. Caller has already passed C2 static and dynamic eligibility. `strict_score_certificate` must be called only within `collect_mixed` strict-family selection, exactly once per selected strict request; never call for Legacy or to retry after an error.

1. In `collect_mixed` keep all shared preflight and original `physical_ordinal_field` computation intact. After that computation and before `match (physical_ordinal_field, ordinal_map.as_ref())`, declare `let mut deferred_score = None;`. Within `(Some(field_id), Some(map))` arm, after original `record_strict_route()`, assign `deferred_score = strict_score_certificate(plan, &stats);`. Add TLS route witnesses in `#[cfg(test)]` code (`deferred_route`, `eager_strict_route`), exactly one of them incremented at this arm's decision. A pre-route failure records neither. Legacy arm remains exactly as before (except P3 argument/literal plumbing in its body). No `ForceEager` hook in non-test build.
2. Make `collect_strict_term_ordinal_body<'a, const DEFERRED: bool>` const-generic; add `certificate: Option<&DeferredBm25<'_, '_>>` immediately before `cancel` in signature. Within the strict match arm select once: `if let Some(cert) = deferred_score.as_ref() { collect_strict_term_ordinal_body::<true>([original arguments], Some(cert), cancel)?; } else { collect_strict_term_ordinal_body::<false>([original arguments], None, cancel)?; }`. The bracket notation means mechanically preserve the original argument list through `&mut total_hits`, not a literal Rust array or new wrapper. Only these two invocations are allowed. No certification after this decision. `c2_observation::strict_routes()` continues to count both variants as one strict family.
3. At entry of the const-generic body check `if DEFERRED != certificate.is_some() { return Err(SearchError::CorruptIndex { detail: "strict ordinal score certificate mismatch".to_owned() }); }` once. Keep original segment loop, order, `ColumnAccess`, `bound`, translation, `JsonAccess`, geo setup and drop/cleanup identical. Do not move the per-segment B3 binding or any other fallible step.
4. Mechanically extract the existing *body of the callback* passed to `execute::visit_strict_term_scored_with` into a local closure just after `let mut key_binder = KeyBinder::Unattempted;`:

```rust
let mut accept = |doc_id: u64,
                  score: f64,
                  include_score: bool,
                  deferred_tf: Option<std::num::NonZeroU64>,
                  matched_count: usize,
                  budget: &mut CandidateBudget| -> SearchResult<()> {
    // Insert exactly the original callback body here. In the two ordinal
    // handler invocations replace the old literal `true` with `include_score`
    // followed by the new `deferred_tf` argument. Nothing else changes.
};
```

The closure increments `total_hits` checked before entered numeric candidate, performs identical first-key binding (`B3` optional refusal/ExactSet fallback), audit, compact handler or existing selected-key/owned-key path. Keep `single_hit_segment = matched_count == 1 && reader.doc_count() >= 1024`. Preserve the matched_count supplied by the evaluator. Then replace the original visitor call by the following exact structure (arguments are the current source order):

```rust
if DEFERRED {
    let cert = certificate.ok_or_else(|| SearchError::CorruptIndex {
        detail: "strict ordinal score certificate mismatch".to_owned(),
    })?;
    execute::visit_strict_term_deferred_with(
        reader, &plan.lexical_leaves, expansion, stats, &plan.positive_lexical,
        segment_index, &live[segment_index], budget, meter, cancel, cert,
        |doc_id, tf, matched_count, budget| {
            accept(doc_id, 0.0, false, Some(tf), matched_count, budget)
        },
    )?;
} else {
    execute::visit_strict_term_scored_with(
        reader, &plan.lexical_leaves, expansion, stats, &plan.positive_lexical,
        segment_index, &live[segment_index], budget, meter, cancel,
        |doc_id, score, matched_count, budget| {
            accept(doc_id, score, true, None, matched_count, budget)
        },
    )?;
}
```

Both alternatives share the same callback; `DEFERRED` is const, not a request flag tested per document. Keep the existing `record_collected_segment` immediately after the visitor succeeds, before cleanup. The borrow of the local closure must end before reading heap/counters or cleaning up; use a lexical block around the closure + visitor dispatch if NLL requires it (D08), never clone heap, change ordering, or use `RefCell`/mutex for production borrow workarounds. C2 `ScoreFailureArm` still affects eager exactly as before. No new per-hit logging or runtime instrumentation.

5. Finalization: add a private function near `MixedEntry`, `fn finalize_deferred_entries(entries: &mut [MixedEntry<'_>], k: usize, certificate: &DeferredBm25<'_, '_>) -> SearchResult<()>` with the following precise behavior. First validate all bounded retained entries (including lookahead) before computing any final score: each has `relevance == false`, `ordinal_sort.is_some()`, `deferred_tf.is_some()`, `hit.score.is_none()`. Any disagreement returns `SearchError::CorruptIndex { detail: "invalid deferred ordinal candidate".to_owned() }`. This check verifies private representation, not a new on-disk validation. Then `for entry in entries.iter_mut().take(k)` take `entry.deferred_tf` using `.take().ok_or_else` with the same error, compute `certificate.score(entry.hit.segment_index, entry.hit.doc_id, tf)?`, assign `entry.hit.score = Some(score)`; test-only record the exact `(segment_index, doc_id, tf.get())` tuple after success. No cancellation poll, allocation, clone, new read or work charge in production finalization. The original eager score loop did not poll cancellation during scoring; moving the non-erroring arithmetic preserves the sequence of poll calls, not the wall-clock instant of a cooperative cancellation. Do not add a new poll after collection.
6. In `collect_mixed`, at the exact existing `let mut selected: Vec<SelectedHit> = heap.into_sorted_vec().into_iter().map(|entry| entry.hit).collect();` statement, use:

```rust
let mut selected: Vec<SelectedHit> = if let Some(cert) = deferred_score.as_ref() {
    let mut entries = heap.into_sorted_vec();
    finalize_deferred_entries(&mut entries, request.top_k.limit, cert)?;
    entries.into_iter().map(|entry| entry.hit).collect()
} else {
    heap.into_sorted_vec().into_iter().map(|entry| entry.hit).collect()
};
```

Leave aggregation finish and subsequent cursor/truncate code byte-identical. The sentinel's private tf is discarded by the mapping; its `score=None` can exist only at index K in `selected`, and the unchanged cursor builder uses the last *returned* entry at K-1, with no explicit-sort `last_score`, then truncates the lookahead before `collect_mixed` returns. There is no unscored returned lexical hit. If `selected.len()<=K` all entries have been finalized. Every score comes from its own stored physical `(segment_index,doc_id,tf)` and the single immutable cert. The existing `Vec` conversion has the same ownership behavior as before (no extra M object). An unexpected score error propagates, no partial response or eager replay. No change to the eager/Legacy final mapping beyond the outer once-per-request branch. Do not add validation to the generic comparator or modify public result types to handle a leaked private candidate; enforce constructors and this finalization check. The new guard only applies to certified path and cannot relax an existing check.

### P5 — test seams and retained C2 behavior

All hooks are `#[cfg(test)]` only. Do not add production strategy, environment variable or feature. Add `c3_observation` module in `unified.rs` using TLS `Cell<usize>` for certificate attempts, deferred/eager strict route counts and TLS `RefCell<Vec<(usize,u64,u64)>>` for final-score identities. Expose reset/get/record analogous to existing `c2_observation`. Add `ForceEager { previous: bool }` RAII using a TLS `Cell<bool>` as in `ForceLegacy`, restores previous on drop (including nested use/panic). `reset()` clears only counters and identities, **not** the force arm. Record `certificate_attempts` at `strict_score_certificate` entry (insert the test-only record call before the P4 force checks), even if test force applies; record route choice in P4. Actual BM25 calls are observed only in `FieldStats::bm25_score`. `reset_witnesses` in the existing C2 test module may add calls to reset the new witnesses and score counter, not alter old resets. Reset before arming, then snapshot all witnesses before running a reference.

To preserve all original eager C2 semantic evidence while default requests now exercise C3, add exactly `let _force_eager = c3_observation::ForceEager::apply();` as first statement of each of the existing **24** `c2_u*` functions in `unified.rs::c2_tests`. Do not modify any other original case, expected value, assertion, error payload, fixture, row completion array or case print. All five `execute::c2_physical_tests` remain on old eager wrapper without edits; all nine existing `perf06_c2_physical` integration tests retain their source and run the *normal* public route (C3 where eligible). Existing B1/B2/B3 tests run normally except the four direct B2 calls and four old MixedEntry test literals receive the None plumbing. A forced C2-only regression is not C3 acceptance; the separate C3 matrix below exercises default dispatch and no forced-defer seam exists.

**Shared synthetic stats fault seam** (required to test actual eager fallback errors, not merely helper return values): within `score.rs::c3_score_observation`, define a `#[derive(Clone,Copy)]` test enum `StatFault { DfAboveN, MissingIdf, Idf(f64), Avgdl(f64), NZero, ZeroDf, MissingTerm, MissingField, ZeroAvgdlWithDfAboveN }`. TLS `Cell<Option<StatFault>>` with default None; `StatFaultArm::arm(fault)` saves/restores previous (same RAII convention). Reset of call counter must not change fault arm. Add `pub(crate) fn apply_fault(stats: &mut SnapshotStats<'_>, field_id: u32, term: &str)` in this child module. No-op when unarmed; when armed mutate only the target field/term: `MissingField` removes the field; `MissingTerm` removes term from df; otherwise find field and record with `.expect` in test-only code. `DfAboveN`: set `stat.doc_freq = field.n.checked_add(1).expect("small synthetic n")`; `MissingIdf`: set `stat.idf=None`; `Idf(value)`: set Some(value); `Avgdl(value)`: assign avgdl; `NZero`: set n=0 without changing df/lengths; `ZeroDf`: set doc_freq=0, idf=None; `ZeroAvgdlWithDfAboveN`: set avgdl=0 and doc_freq=n+1. Do not synthesize an error directly. Mutations exercise real `bm25_score` branches. Source fields are private but accessible to this child module; no public fixture API.

At `collect_mixed` immediately after existing immutable `let stats = { ... compute_stats ... }`, add only the following test-only shadow/seam (before B1 prep and route decision). This placement also affects forced Legacy, so comparisons genuinely receive the same injected statistic. Do not mutate stats after certificate creation.

```rust
#[cfg(test)]
let stats = {
    let mut stats = stats;
    if let [CompiledLeaf::Term { field_id, terms }] = plan.lexical_leaves.as_slice() {
        if let [term] = terms.as_slice() {
            super::score::c3_score_observation::apply_fault(&mut stats, *field_id, term);
        }
    }
    stats
};
```

Synthetic cases are labelled `INJECTED_SHARED_STATS`; no claim they can occur in a valid persisted index. The existing C2 late-score injector is `INJECTED_C2_ONLY`, not shared. Do not introduce a hook that forces certificate acceptance or changes actual score results. Direct helper tests can construct private `FieldStats` in its own test module. Retain existing reset/arm order in C2; never change certificate test counter code from A2. Test-only logging of rows is allowed, not normal-build telemetry.

## 5. File map and cross-component impact

Closed allowlist, relative to B. Everything not listed is protected, including untracked files. No blanket `docs/**` or `crates/**` permission.

| File | Authorized delta |
| --- | --- |
| `crates/quervant-core/src/search/score.rs` | P1 proof token, constants, one test-only call observation, P5 test-only stat fault seam, S01/S02 tests in the existing test module |
| `crates/quervant-core/src/search/execute.rs` | P2 two typed wrappers/shared const body, test-only armed-state accessor, P01 direct visitor test in existing `c2_physical_tests` module |
| `crates/quervant-core/src/search/unified.rs` | P3/P4 exact changes, P5 test-only seams, 24 first-statement C2 eager guards, four old B2 call adjustments plus four old test literal adjustments as specified in P3, new U01–U12 tests in existing `c2_tests`; U13/U14 in existing `b3_tests` |
| `crates/quervant-core/tests/perf06_c2_physical.rs` | Append only I01–I03 and the bounded fixture/response helpers prescribed below; original 9 tests byte-identical |
| `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md` | Append implementation note (no change to normative C1 text or earlier notes) |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | Append dated C2-merged/C3 status and proof/limitations note |
| `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` | Append matching dated status note |
| `docs/pr-artifacts/perf-06-c/PERF06C3_DETAILED_IMPLEMENTATION_PLAN.md` | Approved plan verbatim; verify SHA-256, no normalization after approval |
| `docs/pr-artifacts/perf-06-c/PERF06C3_EXECUTION_REPORT.md` | New report in §12 format |
| `docs/pr-artifacts/perf-06-c/evidence/c3/` | Only new C3 receipts, manifest, source audit, recorder/checker, bounded patches and case/inventory summaries required in §10. No historical file changes. |

The following map determines regression obligations and prohibits silent propagation of the optimization into other subsystems.

| Component | C3 action | Required evidence |
| --- | --- | --- |
| BM25 scalar and prepared scorer | Reuse intact; certificate reads immutable stats; final calculation calls same method | S01/S02/U01/U03/U07/U11; existing score tests |
| Posting codecs, norm formats, reader/segment guards | No changes | P01/U04/U05; retained codec and reader suites |
| Strict executor | Const mode; common validated decoder/ledger | P01 and all five old C2 physical tests |
| Generic lexical/typed/geo/JSON/Boolean/batch/aggregation | No new eligibility; no change in scoring, comparator or work/response semantics | U02/U10 and old C2 U01/U19/U20; workspace integration |
| B1 ordinals/B2 row interpretation/B3 duplicate machinery | Unchanged algorithm and error order, same heap and binding; new inline field only | U06/U07/U08/U13/U14; B1/B2/B3 suites |
| `select_keys`, mutation matching, writer, merge and storage | No changes | Old C2 U19; public PIT/mutation I02 and full mutation suites |
| Cursor, projection, batch memory, result API | Existing handoff/identity and projection unchanged | U07/U08/I01–I03; existing integration and API suites |
| Cargo, CI, benchmarks, CLI, `quervant-objectstore`, `quervant-distributed`, configuration, format, remote topology | Protected | Immutable-path comparison; required ordinary CI including existing real RustFS job |

Do not edit previous C2 reports or receipts, accepted B4 data/configs or historical whitespace exceptions. No additional branch, dependency, flag, tracing/logging in normal hot loops, test skip/ignore, test filter change, fallback-on-error or performance tooling. The C3 delta starts at the **merged** B; historical whitespace already in B is not a new C3 diagnostic.

## 6. Pre-implementation challenge and deterministic red-first proof

Before changing production logic, write the following worksheet into the report with the source anchor and actual answer for each. A correct answer is required, not a copied assertion of confidence. If actual source contradicts the answer, D04/D10/D11 apply.

1. Why does checking only `sort.fields.len()==1` fail to establish eligibility? Cite the complete existing C2 predicate, `M>K+1` proof and the B1 ordinal requirement. Show that the lexical field and sortable field can be different.
2. Why is positive integer tf sufficient for the uniform bound? Locate the decoder's `ZeroFrequency` rejection, checked stats sums, and `FieldStats::length` return domain. Reproduce §3.2 bounds; include `u64::MAX` conversion rounding, `df>n`, missing stat/idf, early zero before errors, NaN/infinity, and signed zero. Identify the exact `InvalidScore` branches that cannot be taken for a certified request.
3. Why is checking only final winners for score validity unsafe? Use losing invalid score and simultaneous corrupted key as counterexample. Show why the certificate is a read-only *request-wide* proof, not a pre-scan of future winners or an error-swallowing policy.
4. List every current producer and consumer of `MixedEntry` and every read of `.score` on retained hits. Show that numeric ordering, duplicate equality/hash, cursor explicit-sort field, `candidate_charge`, and projection do not use the score. Explain why `score=None` is private only and cannot leak out of a certified successful query.
5. Draw the ledger transition sequence for m=0/1/K/K+1/K+2, plus an earlier completed segment's G. Explain exact `3m` and `G+128m` peak; replacement admits new before dropping old. Why can a physical optimization not remove a logical charge? Explain the no-new-M-allocation rule.
6. Show why moving a fallible key/tuple allocation or binding later segments before earlier candidates can alter accepted error precedence. Distinguish initially rejected losers from provisional winners subsequently evicted. Specify existing `MultiOne` and B3 refusal obligations.
7. List existing cancellation poll sites in the strict path before/after the old score loop and actual `MixedWorkMeter` checks. Show that no new poll is introduced. Define cooperative cancellation schedule, not wall-clock equality.
8. Show how final score identity follows a heap entry through replacement/sort, and why only K, not K+1, invokes the scorer. Explain the same snapshot/reader/norms lifetime until finalization; no reopen for tf.
9. Record the original test inventories (24/5/9, broad 39 including historical accounting tests) and the new test names below. Explain why C2's direct eager observations stay in force in the old unit suite but normal public integration will exercise C3. Demonstrate the test-only late-fault override cannot force certificate acceptance.
10. Record the exact C4 dependency, protected runtime/format paths, all applicable local/CI gates, and evidence-source linkage. Identify any pre-existing report issue without reopening C2. Confirm the actual authoring guide and decision matrix allow no unlisted semantic decisions.

### 6.1 Baseline then one deliberately red test

Run baseline commands in §10.2 before any source edit. Write only the TLS `BM25_CALLS` observation and the `record_call` insertion from P1, and add exactly this test at the end of `unified.rs::c2_tests` (no ForceEager guard in a `c3_u*` test):

```rust
#[test]
fn c3_u01_winner_score_count() {
    let fixture = Fixture::new(&[body_documents(40)]);
    let request = request_asc(term_body(), 3);
    reset_witnesses();
    crate::search::score::c3_score_observation::reset();
    let actual = run_with(&fixture, &request, SearchLimits::default(), linear_config())
        .expect("strict lexical request");
    assert_eq!(actual.total_hits, 40);
    assert_eq!(keys(&actual), vec![bounded_key(0), bounded_key(1), bounded_key(2)]);
    assert!(actual.next_cursor.is_some());
    assert_eq!(c2_observation::strict_routes(), 1);
    let calls = crate::search::score::c3_score_observation::calls();
    eprintln!("C3 U01 BM25 calls={calls} expected=3");
    assert_eq!(calls, 3, "only returned hits are scored");
}
```

Format; stage only these test-only edits; require committed-range and staged whitespace clean. Commit locally as `RED` (one explicitly expected failing test; never push a failing branch). Capture immutable RED and its `B..RED` diff digest. Run exactly:

```sh
cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c3_u01_winner_score_count -- --exact --nocapture --test-threads=1
```

Expected RED: exactly one test executed, 101, the preceding assertions pass, observed `calls=40 expected=3`, panic at the count assertion, left 40 right 3. A compile error, zero selected tests, earlier assertion failure, or unexpected pass does not establish the red proof. Classify and stop under D10; no adjusting the red fixture to manufacture failure. This proof is not a mandatory-final-gate failure and must be preserved as such. Do not modify this test after obtaining red except formatting from the common toolchain. When C3 is implemented the identical test must pass with actual calls=3. The red commit is intentionally local until the green tested commit is ready.

## 7. Unit and adversarial acceptance design

### 7.1 Test instrumentation, naming and reference helpers

Create precisely two S functions in the existing `score.rs` unit test module (`c3_s01_certificate_matrix`, `c3_s02_uniform_bound_and_bits`), one P function in `execute.rs::c2_physical_tests` (`c3_p01_deferred_decode_and_ledger`), twelve U functions in `unified.rs::c2_tests` (`c3_u01_winner_score_count` through `c3_u12_private_representation` named below), two U functions in `unified.rs::b3_tests` (`c3_u13_collision_with_deferred_frequency`, `c3_u14_multione_deferred_scores`), and three integration functions in `perf06_c2_physical.rs` named in §8. No additional registration is authorized by this plan; matrix rows are not separate registered tests. Preserve all old test names, no skip/ignore. The source/name inventory is 17 new unit functions and 3 new integration functions, not a count of invocations. Confirm the old 24 C2 unified, 5 C2 physical and 9 C2 integration names by exact name set (not a broad substring; new C3 functions inside old modules match `c2_` too). The old broad `--lib c2_` filter gains 13 functions (12 U, 1 P), so its baseline 39 becomes 52; the 2 B3-module U tests are outside this filter. Report old/new exact sets rather than relying solely on this arithmetic. New C3 selection `--lib c3_` must select exactly 17 tests; final integration target 12 tests. The existing `--lib b3_` filter also matches two new B3-module U tests; report them separately.

Test helpers in `c2_tests`:

- `assert_c3_full_response(actual, expected, label)`: use `projected` (includes optional score bits, exact key and projected fields) and compare `total_hits`, `generation`, `view_ordinal`, the entire `next_cursor` and `aggregation`. Do not use `bits()` on possibly unscored typed hits. For same-query references require full cursor equality, not presence. Assert literal expected key/count/score/projection independently wherever specified.
- `c3_run_eager(fixture, request, limits, config)`: `reset_witnesses(); let _guard=c3_observation::ForceEager::apply(); run_with(...)`. When strict eligible, require route counters strict=1, Legacy=0, eager=1, deferred=0. For use in a matrix with ineligible cases, assert expected route at caller rather than require strict unconditionally. Keep reset separate from arming and do not reset stat/force arms.
- `c3_run_legacy`: reset witnesses, arm existing `c2_observation::ForceLegacy`, same request/snapshot/config/limits; require Legacy=1/strict=0 and no C3 route/cert on requests that reach the decision. For pre-route failure assert both route counts zero. Reuse existing `forced_legacy_with` when its route assertion fits. Do not change the actual query to force Legacy in unit tests.
- `c3_assert_certified(m,k,segments)`: called **before** any reference/reset. Require strict=1, legacy=0, certificate attempts=1, deferred=1, eager=0, `physical::strict_evaluator_calls()==segments`, `physical::strict_membership_observations()==m`, `physical::callbacks()==m`, `physical::converted_rows()==0`, `b2_observation::numeric_candidates()==m`, real BM25 calls=`min(m,k)`, final identity records exactly `min(m,k)` in returned order. The fixture must be actually eligible, `m>k+1`, except direct P01 tests. Inspect `c3_observation` recorded tuples against literal/decoded physical identities where requested. Reset B2/B3 and reader counters in addition to `reset_witnesses` before tests using those counters. Never warm a fixture intended for an allocation-refusal injection before that injection.
- `c3_assert_error_parity(actual,reference,expected)`: match the exact typed variant and payload for cases named below; for additional cases use `format!("{error:?}")` equality of the complete error including nested variants and all fields, not a category-only assertion. Never accept success as an alternative for a mandatory failure. A successful paired result uses full-response equality; mismatched Result branch fails. An independently specified error or literal oracle is mandatory for each boundary row, not just two equally wrong paths.

The following acceptance rows specify all fixture inputs and outcomes. Use existing helper names and exact native fixture builders rather than invented storage adapters. Case completion evidence: `eprintln!("C3 <ID> <row> ...")` only after assertions; print required observed counters, variant/payload and recovery; each matrix must assert its exact case count or ordered ID list at end. Any discrepancy is a scoped STOP, not permission to trim or skip a row. S/U/I tests use real core code, not mocked scorers. The synthetic stat seam changes data, not return values; C2-only injector evidence is explicitly structural.

### S01 — certificate decision table (`c3_s01_certificate_matrix`)

Construct private `FieldStats` in `score.rs`'s existing test module with the actual source field layout. For each row create a fresh stats object: n=30, avgdl=2.0, one term `"alpha"` with df=30 and `Some(prepare_idf(30,30).expect(...))` (equivalently assign `prepare_idf` directly), lengths `vec![SegmentLengths::Persisted(&lengths)]`, local `lengths=[0u64,1,u64::MAX]`. Base certificate must match the same field+term, not a different term or a second identical field object. `PreparedTermStat` uses actual `doc_freq`/`idf` fields. Change only the input named per row. No need to mutate production API.

| IDs | Mutations relative to base | Certificate |
| --- | --- | --- |
| S01-01 | none | Some |
| S01-02/03/04 | n=0; df=0; df=31 | None each |
| S01-05/06 | remove `alpha`; idf=None | None each |
| S01-07..13 | avgdl=0, -1, NaN, +inf, -inf, C3_AVGDL_MIN/2, C3_AVGDL_MAX*2 | None each |
| S01-14..16 | avgdl=C3_AVGDL_MIN, 1, C3_AVGDL_MAX | Some each |
| S01-17..21 | idf=NaN,+inf,-inf,-1,65 | None each |
| S01-22..24 | idf=0,-0.0,64 | Some each |

Check exactly 24 rows; absent term lookup must not be certified for any other term. `matches` identity check against an independently created but numerically identical field must be false. Direct eager `bm25_score("alpha",0,...)` with invalid df and missing IDF must return zero bits, not the deferred error. Test-only certificate is read-only; do not assert every None case is an error.

### S02 — uniform bound, bit grouping, degenerate cases (`c3_s02_uniform_bound_and_bits`)

Use four `(n,df)` pairs: `(1,1)`, `(u64::MAX,1)`, `(u64::MAX,u64::MAX)`, `(9_007_199_254_740_993,9_007_199_254_740_992)`. For each set prepared IDF using existing `prepare_idf(df,n)`, avgdl from `[C3_AVGDL_MIN,1.0,C3_AVGDL_MAX]`, use lengths `[0,1,u64::MAX]` as persisted slice. For each tf `[1,9_007_199_254_740_993,u64::MAX]` and each doc index 0..3 (length from array), require certificate exists; call `certificate.score(0,doc_id,NonZeroU64::new(tf).unwrap())` and compare `.to_bits()` to both `0.0_f64 + field.bm25_score("alpha",tf,dl).unwrap()` and `0.0_f64 + bm25(tf,df,n,dl,avgdl).unwrap()`. Assert finite nonnegative. Exactly 108 cases. No claim these synthetic extremes fit a real configured decode budget; this is a mathematical superset test. Separately fix n=df=1, avgdl=1, tf=1, dl=1 and explicitly inject prepared idf `0.0`, `-0.0`, `64.0`; certificate score must equal the same prepared eager bits (not scalar for anomalous IDF). For first two assert +0.0 bits. Also verify the length accessor's existing zero-on-absence behavior via certificate at nonexistent segment/doc identity in this synthetic stats object only; it must equal eager for dl=0, not a new error rule. Verify `bm25(0,... invalid df ...)` zero, and actual `FieldStats::bm25_score` invalid positive df/missing prepared IDF variants and exact details. These complement U03 public routing/fallback; don't change `bm25` to satisfy them.

### P01 — exact direct deferred visitor charges and identity (`c3_p01_deferred_decode_and_ledger`)

Append in `execute.rs::c2_physical_tests`; reuse `index(20)`, reader guard, `live` mask, `strict_inputs`, `make_budget` and `make_meter_with` exactly as retained P05. Tombstone every third physical id as in P05. Scoring term `grp/common`; obtain cert from `inputs.stats.field(reader.schema().field_id("grp").expect(...)).expect(...).certify_deferred("common").expect(...)` before any call. Same `inputs.leaves`, expansion and positive set. Copy P05's row struct, six rows, meter total assertions, exact error matches and zero-ledger checks into the new function; replace only the two evaluator calls with `visit_strict_term_deferred_with(...,&NeverCancel,&cert, callback)`. The callback must require `tf.get()==1`, matched_count=13, store raw physical ids; on recovery require exactly `[1,2,4,5,7,8,10,11,13,14,16,17,19]`. Reset actual score calls and physical observations per row and recovery; both must use zero BM25 calls, zero converted rows. No simulated success or extra work charge.

| Total cap | Scanned cap | Required outcome | Total used | Callbacks |
| ---: | ---: | --- | ---: | ---: |
| MAX | 10 | ResourceLimit {10,11} | 20 | 0 |
| MAX | 19 | ResourceLimit {19,20} | 38 | 0 |
| MAX | 20 | Success | 53 | 13 |
| MAX | 21 | Success | 53 | 13 |
| 52 | 20 | ResourceLimit {52,53} | 40 | 0 |
| 53 | 20 | Success | 53 | 13 |

All rows recover on the *same* budget with fresh meter 53/20; every budget field zero after each call, including recovery. Verify six rows completed. Additional misuse subcase: build a second `strict_inputs(&readers, &live_rows[0])` and a certificate from that distinct stats object; invoke deferred visitor with the original stats and second cert. Expect exact `CorruptIndex { detail: "single-term postings eligibility mismatch" }`, no callback, all three ledger fields zero. Same-budget retry with original cert succeeds, raw tf and order exact. This is an internal defensive guard test, not a normal fallback route. Do not add a second scoring implementation to compare tf.

### U01/U02 — dispatch, count boundaries, ineligible routes

U01 is exactly the immutable red-first test above. U02 name `c3_u02_dispatch_and_count_matrix`. Use existing `Fixture`, `documents`, `other_documents`, `request_asc`, `term_common`, `term_absent`. For each K in `[1,10,31,32,100]`, each M in `[0,1,K,K+1,K+2]`, build a fresh fixture (M=0 uses 8 documents and absent term; others all common). Even duplicate input rows when K=1 get distinct matrix IDs; execute exactly 25 rows. Require literal `total_hits=M`, keys first min(M,K), cursor presence exactly M>K; when eligible C3 witness as above, otherwise Legacy only, no cert attempt or final scoring identity. Compare complete response with same-request forced C2 eager (in strict cases) and Legacy. Preserve count semantics on every row. Then use existing split fixture from C2 U02 (`other_documents(3,100)`, `documents(1)`, `documents(12).skip(1)`), K=10; assert 3 evaluator calls, 12 membership/callbacks, final 10 actual calls, exact first ten keys, cursor and full responses. Native segment order irrelevant for this row; assert physical counts from guard and not insertion order.

Copy the complete ineligible-query, sort-shape, batch/aggregation and after-cursor subcase constructions from existing `c2_u01_static_dispatch_matrix` into U02, using the same 24-doc fixture. No change to inputs; unlike the preserved C2 test, add no ForceEager guard. For successful cases assert Legacy=1, strict=0, cert attempts=0, deferred/eager=0, final identities empty; compare ordinary result to same-query forced Legacy. For malformed sort/non-columnar field assert exact pre-route error parity (both routes/cert attempts=0). Relevance uses original scores and cursor semantics. Batch and aggregation execute with same existing real `BatchExecutionMeter`/search methods and must select Legacy, no certificate; assert result/count and old U01/U19 regressions. For cursor use an actual C3 first page and then `after` (not constructed fake token), assert second page Legacy, no certificate and literal next keys. For B1 `NotAvailable`, retain C2 U17's enum tests and execute the existing B1 acceptance suites; the C2 selector and B1 preparation are byte-identical, no new B1 fault injection or guessed budget is authorized. Record source equality and actual executed B1 regressions. All B1 errors continue to propagate; no new selector test seam. Do not claim enum-only coverage proves real refusal.

### U03 — actual shared-stat fallback and competing errors (`c3_u03_uncertified_stats_eager_precedence`)

Use `Fixture::new(&[body_documents(30)])`, exact `request_asc(term_body(),3)`, `linear_config()`. A fresh base search gives `M=30`, first 3 keys, cursor; `n=df=30`. For each row arm `StatFaultArm` **after resetting counters**. Run normal search (no ForceEager), capture route counters/results, then same synthetic fault and same query/snapshot/limits/config with forced Legacy. The same fault arm stays active through both calls; `reset_witnesses` must not clear it. For strict fallback successes require eager=1, deferred=0, cert attempt=1, actual scorer calls=30, converted=30, callbacks=30, final identities empty. For strict errors expect eager route, cert attempt=1, no candidates, no converted rows, one actual scorer call at first bad score (all docs match). For the three count-guard Legacy rows expect strict=0, no cert, no deferred final identities. Compare exact results including complete cursor. Remove arm; same-snapshot unarmed recovery must certify, score exactly 3, and equal the pristine response. Do not require ordinary coherent scores to equal synthetic successful scores except where zero explicitly specified.

| Row | StatFault | Expected default path and outcome |
| --- | --- | --- |
| U03-01 | DfAboveN | eager C2, InvalidScore: `document frequency exceeds the live-document count` |
| U03-02 | MissingIdf | eager C2, CorruptIndex: `prepared BM25 IDF missing for valid term` |
| U03-03/04/05 | Idf(NaN), Idf(+inf), Idf(-1.0) | eager C2, InvalidScore: `BM25 produced a non-finite or negative score` |
| U03-06 | Avgdl(NaN) | same eager InvalidScore |
| U03-07/08/09 | NZero, Avgdl(0.0), Avgdl(-1.0) | eager C2, successful all returned scores +0.0 |
| U03-10 | ZeroAvgdlWithDfAboveN | eager C2, early zero succeeds, no df error |
| U03-11 | Avgdl(+inf) | eager C2, existing finite positive arithmetic, exact Legacy parity |
| U03-12 | Avgdl(C3_AVGDL_MIN/2) (use literal `0.5 / 18_446_744_073_709_551_616.0` in unified tests) | eager C2, finite nonnegative score, exact Legacy parity |
| U03-13 | Avgdl(36_893_488_147_419_103_232.0) | eager C2, finite nonnegative score, exact Legacy parity |
| U03-14 | Idf(65.0) | eager C2, finite positive score, exact Legacy parity |
| U03-15/16/17 | ZeroDf, MissingTerm, MissingField | Legacy by unchanged count guard; same result as forced Legacy, first two use scalar df=0, missing field gives +0.0 |

Execute all 17 IDs; report `INJECTED_SHARED_STATS`. Add two competing-fault subcases: use copied container from the U04 pristine 32-row `grp/common` fixture, mutate only D0 via the actual `u12_corrupt_doc_key`; use corresponding `request_asc(term_common(),3)`. Arm `DfAboveN` then `MissingIdf` on separate freshly rebuilt snapshots, run normal and same-fault forced Legacy. Require respectively exact score error U03-01 or U03-02 **before** corrupted key resolution, zero callbacks/numeric entries, one actual scorer call, zero B3 build attempts, eager route. After clearing arm the exact `InvalidUtf8 { context: "doc key" }` error must surface on the corrupted snapshot via C3. Pristine snapshot recover as above. Real corruption + shared synthetic stat proves order, not a claim those invalid stats occur naturally in valid storage. Do not use the C2-only score injector as the shared stat reference.

### U04 — full real corrupt-byte precedence matrix (`c3_u04_corruption_precedence`)

Reuse the complete native U12 fixture and mutators, not an invented format: `documents(30)` extended with `other_documents(2,30)`, K=3, `term_common` ascending doc_id, all 32 effective-live, field norms present, physical DOC_KEYS order `doc000000..doc000031`, posting df=30. Use the existing `CopiedSegment`, `u12_corrupt_doc_key`, `u12_corrupt_final_posting`, `u12_corrupt_sort_column`, `u12_probe_*`, `c2_f1_snapshot`, `c2_f1_run_snapshot`, and `assert_u12_error`. Copy U12's exact `pristine/postings_offset/postings_length` preparation and guarded row/probe/zero-match/repeat/pristine-recovery logic. The approved posting mutation remains compact-short positional, 218-byte payload, marker 7, last frequency byte +67, not +66. Never rewrite a codec offset or construct a different fixture if guards fail. Use the combined-column row probe ordering already accepted in A1 (column probe only if column corrupted; else actual key/posting probes as applicable). All real byte cases compare to same-query forced C2 eager and forced Legacy on the same immutable bytes with exact nested `assert_u12_error`. Explicitly do not reuse U12's old `converted=30` expectation for C3: normal certified path keeps raw tf, not score bits.

| Ordered row ID | Required error | strict/deferred/eager | membership | numeric/callback | BM25 calls |
| --- | --- | --- | ---: | --- | ---: |
| D0 | Segment InvalidUtf8, `doc key` | 1/1/0 | 30 | 1/0 | 0 |
| D29 | same | 1/1/0 | 30 | 1/0 | 0 |
| D31 (nonmatching key) | same | 1/1/0 | 30 | 1/0 | 0 |
| P29 | Segment ZeroFrequency {doc_id:29} | 1/1/0 | 0 | 0/0 | 0 |
| P29+D0 | same posting error wins | 1/1/0 | 0 | 0/0 | 0 |
| C0 | Index(Segment(InvalidUtf8 `keyword`)) | 0/0/0 | 0 | 0/0 | 0 |
| C29 | same | 0/0/0 | 0 | 0/0 | 0 |
| C29+P29+D0 | same column error wins | 0/0/0 | 0 | 0/0 | 0 |
| S29+D0 | existing injected C2 InvalidScore | 1/0/1 | 30 | 0/0 | 29 |

All rows `converted=0` and final identities empty on failure; certificate attempts exactly strict count. The C rows are eagerly rejected before route selection, **not C3 candidate execution**. U12's `S29+D0` uses actual `ScoreFailureArm::arm(29)` (arms after reset) and proves test-only forced eager fallback; label `INJECTED_C2_ONLY`. The hook fails before the 30th real scorer call; no same-fault Legacy comparison. Unarmed C3, forced eager and forced Legacy on those bytes give D0 error. Repeat every real byte fault; on zero-match controls before key/posting processing, exact empty outcome exactly when existing U12 executes that control; column rows retain direct eager column probes and actual fault-query assertions. At end of every row, verify original immutable bytes unchanged and same pristine request returns exact initial response, certified with 3 scores. Each row returns its ID after all checks. Assert fixed ordered 9-element completion array identical to the table. No green function with omitted rows.

### U05 — later-segment failure and deferred finalization (`c3_u05_native_later_segment_boundary`)

Use exactly U21's `Fixture::new(&[body_documents(6), body_documents(40).into_iter().skip(6).collect()])`, `assert_native_boundary_fixture`, `request_asc(term_body(),2)`, `linear_config()`. Verified native order is segment0 34 docs global 6..39, scanned 87, segment1 6 docs global 0..5, scanned 13; do not assume insertion order. Existing `with_max_scanned_posting_occurrences` method. Require exact cases below and complete-response parity with eager and Legacy of the same query/limits/config. For failed rows no final scorer call or final identity (even after earlier segment collected). All `converted_rows=0`. Assert `b2_observation::bound_columns`, evaluator count, membership, numeric/callback, `collected_segments` exactly. The row count is four; following each of the three failures retry at 100 on same snapshot and compare full response to cap-100 control, 40 total, keys 0,1, complete cursor, exactly two scorer calls. Also require success row's repeat (four recovery/repeat lines total, three after failures).

| cap | outcome | evaluators/bound | membership/numeric/callback | collected `(segment,heap_len,total)` | final BM25 |
| ---: | --- | --- | --- | --- | ---: |
| 86 | ResourceLimit {86,87} | 1/1 | 0/0/0 | [] | 0 |
| 87 | ResourceLimit {87,88} | 2/2 | 34/34/34 | [(0,3,34)] | 0 |
| 99 | ResourceLimit {99,100} | 2/2 | 34/34/34 | [(0,3,34)] | 0 |
| 100 | Success | 2/2 | 40/40/40 | [(0,3,34),(1,3,40)] | 2 |

Require strict/deferred=1, eager=0, no Legacy replay for normal cases. Keep C2 U21 intact under ForceEager. This case demonstrates that C3 does not finalize or return the first segment before processing later failures. C2's U17 native late-score injector remains under the original eager test guard; U04 exercises automatic synthetic override without that guard.

### U06 — actual B3 optional fallback (`c3_u06_b3_refusal_matrix`)

Reuse the five fully executed B3 refusal/control blocks in `c2_u17_ordinal_unavailable_and_b3_refusal`, including their exact probes, fresh fixtures, `B3ProbeReset`, `Rc<Cell<usize>>` fired counters, configs and recorded collected tuples. The new function does not install ForceEager. Keep `request_asc(term_common(),3)` and 40 docs; for split use two native 20-doc segments; expected order tuple counts independent of key distribution. Copy the nested assertion helper and adjust only C3-specific assertions: `converted_rows=0`, `c3_assert_certified(40,3,segments)`, complete score/response equality against eager and Legacy, literal first three keys. Capture the probe counters before either reference. For references clear probe using existing clear function (and allow guard to clear on drop). A cold optional refusal may be sticky/cache-dependent, so don't require reference identical build counters; require exact public response. Original C2 U17 itself remains unchanged except ForceEager first line.

| Row | Config/actual probe | attempts/published/refused | owned-key fallback indices | collected |
| --- | --- | --- | --- | --- |
| 1 | single segment, Linear, BeforeHashAllocation refuses | 1/0/1 | [0] | [(0,4,40)] |
| 2 | two segments, first refuses, second continues | 2/1/1 | [0] | [(0,4,20),(1,4,40)] |
| 3 | two segments, first continues, second refuses | 2/1/1 | [1] | same |
| 4 | two segments, all ready | 2/2/0 | [] | same |
| 5 | two segments, ExactSet (threshold 1) | 0/0/0 | [0,1] | same |

Every row default C3=1, cert attempt=1, 40 candidates counted, final 3 BM25 calls, no new fallback. Assert exactly five rows complete, actual probe invocation count as in C2 U17. No binding pre-scan or change to allocation refusal behavior.

### U07 — provisional ownership versus final scoring (`c3_u07_replacement_and_final_identity`)

Single fresh `Fixture::new(&[body_documents(40)])` per Asc/Desc case; K=3, `linear_config`, sort doc_id, missing Last. Before run assert actual physical order using guard's `doc_keys()` equals `bounded_key(0..40)`; field length and raw tf from input formula `1+i%4` alpha and `i%5` gamma, n=df=40, total length 180, avgdl=4.5. No fake key/score. Reset all witnesses. Require literal winner indices `[0,1,2]` Asc and `[39,38,37]` Desc, complete exact fields, total40 and last returned key in cursor; explicit sort `last_score=None`. Compare C3 to forced eager and forced Legacy complete response. Require actual final identity records `[(0,0,1),(0,1,2),(0,2,3)]` or `[(0,39,4),(0,38,3),(0,37,2)]` in response order; exactly 3 scores in each. Assert independently computed expected score bits from input (scalar test reference formula as in S02; use actual `0.0 + (idf * (tf*(1.2+1.0)) / (tf + 1.2*(1.0-0.75+0.75*dl/4.5)))`, IDF from `(1.0_f64+(40.0-40.0+0.5)/(40.0+0.5)).ln()`). Ensure no scoring of K+1 or evicted candidates by count and identities. Asc exactly 4 owned compact keys, 4 owned single strings, 36 single rejections without copy; Desc exactly 40 of each owned materialization, 0 single rejections (every candidate replaces). Require `b3_meta_reads=40`, no fallback, one-time audits 1. This is the important reverse-competitive counterexample: **40 provisional allocations are retained, but only 3 scores are computed**. Do not change B2/B3 to make the ownership assertion smaller. The source of ownership witnesses is existing counters, not allocation estimates.

### U08 — null/missing and ties (`c3_u08_rank_ties_and_null_order`)

Reuse U14 `Rank`, `ranked_document`, `rank_sort`, and exact 8-row array `[Value("b"),Missing,Value("a"),Null,Value("b"),Value("c"),Value("a"),Value("b")]`; K=3, query common, `linear_config`. For each direction/placement expected returned logical document indices:

| Direction / missing placement | Indices |
| --- | --- |
| Asc / First | [1,3,2] |
| Desc / First | [1,3,5] |
| Asc / Last | [2,6,0] |
| Desc / Last | [5,0,4] |

Assert 8 count, 3 actual BM25 calls, full same-query cursor/eager/Legacy parity and literal keys/fields. Equal ranks tie by ascending byte key even Desc. Require full 4-row completion. Do not replace missing/null with a default value. MultiOne is separately proven in U14 below (using native accepted B3 fixture, not a guessed cardinality construction).

### U09 — exact virtual ledger boundaries (`c3_u09_logical_budget_edges`)

Copy the fixture and caps of old U10 (m,K in 3/1,12/10,102/100). For each m, peak_entries=3m, peak_bytes=128m, existing `with_max_segment_candidate_entries` / `with_max_total_candidate_bytes`. One-under entry row `(peak_entries-1,peak_bytes)` requires `ResourceLimit {limit:peak_entries-1,requested:peak_entries}`; one-under byte row `(peak_entries,peak_bytes-1)` requires `{peak_bytes-1,peak_bytes}` Old U10 has already established these exact fixture/default-config boundaries; a contrary result in default C3 is failure, not a reason to retune. Require strict/deferred=1, zero callbacks, zero scores, no final identity. Compare same limits against forced eager and Legacy with exact payload. At exact `(peak_entries,peak_bytes)` virtual segment phase is admitted; observe all `m` membership events and compare exact full verdict to eager and Legacy (if a subsequent existing heap cap rejects, require same exact failure and no final scores, not an alternative success). Generous `(peak_entries,peak_bytes*4)` succeeds with literal keys, K scores, exact total/cursor and parity. Four rows per m = 12, then unarmed retry after each failure as in retained U10/U11. Retain existing default duplicate config in these comparisons; P01 uses no global heap. Also rerun retained B2 direct replacement tests covering transient heap byte peaks and existing U11 with RAII/peak assertions; source-audit `candidate_charge`, duplicate table, and preflight/release code. Do not guess a new G/table capacity or assume `size_of::<MixedEntry>()` is the logical byte charge.

### U10 — cancellation and same-snapshot recovery (`c3_u10_cancel_poll_parity`)

Use one 40-body fixture, K=3, `request_asc(term_body(),3)`, `exact_set_config_threshold_one()` to avoid compact-key build refusal and different B3 cache warm-up. First warm same immutable snapshot through eager and C3 with `NeverCancel`, assert same full response. Then use existing `CancelAfter { polls: AtomicU64::new(0), cancel_at: 0 }` (0 disables cancellation in actual implementation). Run C3 and forced eager separately, read polls after each and require equality, `0<P<=4096` for this bounded fixture, exact healthy responses and expected C3/eager score counts. For each `cancel_at=1..=P+1`, new counters and `CancelAfter` with that value; use same snapshot, config, limits, public search calls, correct ForceEager RAII. Capture C3 and eager result, poll count, actual score count and final identities before reference/reset. For `cancel_at<=P`, both must return exact `SearchError::Cancelled` and identical poll count; if cancellation occurs in a later post-score projection phase, score count may be K on C3, otherwise 0 (never partially finalized; there is no poll in the final score loop). For `P+1`, both succeed with identical full response, same P polls, C3 scores exactly K. Require actual cancellations and success, P+1 rows, no ResourceLimit accepted as an alternative. A poll schedule mismatch is D11, not permission to insert/remove cancellation checks. Repeat `NeverCancel` after sweep and assert exact pristine response and certified witnesses. Pre-cancelled `CancellationFlag` separately must yield Cancelled on both. This proves deterministic check-site parity, not identical wall-clock cancellation latency; no sleeps or timers. Cursor/aggregate/batch sibling cancellation is covered by retained suites; no new scope.

### U11 — seeded differential matrix (`c3_u11_seeded_final_scores`)

Use existing `Rng` xorshift and `document_with_body(index,repeats,padding)`; fixed seed `0xC306_2026_0000_0001`. Eight distributions d=0..7, count=120+3*d, segments=1+d%4. For each global i, repeats=1+rng.below(4), padding=rng.below(6), put document into bucket `i % segments`; keep literal `(tf,dl=tf+padding)` table indexed by i. All match alpha. Construct real `Fixture`; verify each physical id's key from each actual reader, build test-only key-to-(segment,doc_id) map using existing key access; assert no duplicates and expected count. For each K `[1,10,31,32,100]`, direction Asc/Desc, missing First/Last, use exact existing doc_id sort request and `linear_config`. Each row must certify, exact count, literal first/last K keys in direction, exact projected doc_id field, actual BM25 calls K, recorded `(segment,doc,tf)` matches table for each returned key in order. Compare complete responses/score bits to forced eager and Legacy. Independently compute n=df=count and avgdl from input total lengths; for each winner check bits from scalar formula with accepted grouping as in U07. Since all rows have M>K+1, no skip or conditional continue. Exactly 160 rows; log seed and d/K/direction/placement on failure, report completion count. No RNG dependency, no unbounded fuzzing or random host state.

### U12 — private representation and finalization guard (`c3_u12_private_representation`)

At unit test scope define `#[allow(dead_code)] struct OldMixedEntry<'a>` with the exact B fields in original declaration order (`hit: SelectedHit`, `charge:u64`, `sort:&'a Sort`, `relevance:bool`, `ordinal_sort:Option<OrdinalSortKey>`, `key_hash:Option<u64>`). Use `size_of` / `align_of` to assert new entry alignment equal, size >= old and <= old+8; `size_of::<Option<NonZeroU64>>() == size_of::<u64>()`. Print actual old/new size/alignment and target, not a guessed absolute layout. No change to public layout/API. Create real `Fixture::new(&[documents(8)])`, open guard, live effective mask, real `compute_stats` using actual reader, lexical scoring field id `grp`, `QueryTerms` from one `BTreeSet` of `"common"`; Use `let readers = [reader]; let live_rows = [live]; let fields = [grp_field_id]; let query_terms = BTreeMap::from([(grp_field_id, BTreeSet::from(["common".to_owned()]))]); let limits = SearchLimits::default();` and `let mut meter = MixedWorkMeter::new(limits.max_total_work_units(), limits.max_typed_work_units(), limits.max_scanned_posting_occurrences(), &NeverCancel); let mut work = SearchWork::shared(&mut meter);` (the constructor from the pinned `strict_inputs` helper). Invoke exactly `compute_stats(&readers, &live_rows, &fields, &query_terms, &limits, &mut work, &NeverCancel)` and certify its field. Construct three synthetic `MixedEntry`s in ascending doc/key/rank order for docs 0,1,2, `score=None`, `deferred_tf=NonZeroU64::new(1)`, `ordinal_sort=Some(Value(i as u64))`, `relevance=false`, sort reference to real request, charge via existing `candidate_charge` and hash metadata if applicable. Use actual `SelectedHit` fields from source and existing direct constructors as model. Call `finalize_deferred_entries(&mut entries,2,&cert)`: actual BM25 calls 2, first two `Some` with eager bits (capture count before comparison), tf cleared for those, lookahead remains `None` score and original tf, exact identity records. For each separate fresh array mutate **only last entry** to `deferred_tf=None`, preexisting `hit.score=Some(0.0)`, `ordinal_sort=None`, or `relevance=true` (four rows). Require exact `CorruptIndex {detail:"invalid deferred ordinal candidate"}`, no score calls, first entries unchanged and no final identity. These private misuse tests require no production injection, are not on-disk error claims. The finalizer must validate all retained entries before any score, including the sentinel; don't repair or score malformed entries. Do not change the charge model or comparator to satisfy size assertions; D10 if unsupported layout.

### U13/U14 — collision and MultiOne with deferred entries (existing `b3_tests` module)

U13 `c3_u13_collision_with_deferred_frequency`: reset the TLS score observation before the first case; reuse `synthetic_entry` and exact check cases of `b3_u04_u23_fingerprints_are_prefilters_never_identity`. Copy test body into new function; for each synthetic entry create using `synthetic_entry` then set `hit.score=None`, `deferred_tf=NonZeroU64::new(7)` before pushing. Reuse exact shared fingerprint `0xDEAD_BEEF`, `d3c::State::for_test(d3c::Kind::Linear,d3c::Profile::P0,8)`, callback strings and sentinel hashes 0/MAX. Different bytes under same hash allowed, same key returns exact duplicate CorruptIndex (require `SearchError::CorruptIndex { ref detail } if detail == "duplicate live document key across segments"`, the exact current `d3c::duplicate_error` detail), different hash never resolves exact key, missing fingerprint fails closed even on non-worst entry. The original test's one-time hash audit checks remain. Assert no actual BM25 calls and no materialized returned hits; this is direct duplicate-policy structural evidence, not public forced collision. Compare the outcome to the identical eager synthetic entries from the original helper, with exact same error values. Keep original regression unchanged apart from `MixedEntry` literal plumbing.

U14 `c3_u14_multione_deferred_scores`: copy only the MultiOne block of existing `b3_u07_reverse_order_and_multi_one_losers` using exact `City::Multi`, `build_segments`, `term()`, `request`, `sort_field` and snapshot. 64 rows `m{index:05}`, value `m{index:08}`, ascending, K=5. Reset existing B2/B3, C2/C3 and score observations before real `search`. Require strict/deferred=1, cert attempt=1, zero eager, total64, 64 callbacks and numeric candidates, 64 full MultiOne legacy decodes, zero owned single strings, 6 compact key materializations (physical/rank order as existing fixture, assert literal physical key order via reader; if fixture order differs, D04 rather than change expectation), actual BM25 5 and final identities=5. Literal keys `m00000..m00004`; score bits and full projected fields parity with same-query forced eager and forced Legacy via existing `search` helper and RAII guards (reset observations before each, require correct route). Compare whole cursor, total, generation/view, aggregation; no different query AST. Require stored/rank `MultiOne` semantics unchanged. Do not insert a Multi value in a different schema or assert the loser never decodes its tuple. If existing B3 helper's query/search shape contradicts actual C2 eligibility, STOP D04 (do not force acceptance).

## 8. Real persistent-index acceptance (G5)

Add only three tests to existing `crates/quervant-core/tests/perf06_c2_physical.rs`, using its real `TempDir`, `FsDirectory`, `Index`, writer, commit/reopen, `Corpus`, `scoring_schema`, `scoring_document`, `large_index_limits`, `request`, `doc_id_sort`, `scoring_projection`, `term_query`, `legacy_query`, `legacy_text_query`, `search_with` and `keys`/`scores` helpers as appropriate. No test-only route counters in normal build or feature flag to force C3. Public calls exercise the normal default path, validated in unit tests separately. No remote topology change; the existing ordinary CI RustFS real-body job remains mandatory regression, not C3 timing. Use temp directories as in existing suite and cleanup on drop. Do not fake `Index`, codecs, projections, or BM25.

### I01 `c3_i01_real_scores_and_explicit_cursor`

Use real scoring corpus exactly `c2_i02_scores_full_projection_and_reverse_sort`, but split commits into slices 0..6 and 6..40, using `scoring_schema`, `scoring_document`, `large_index_limits`, then close writer/index and reopen from `FsDirectory` as I02 does. Same public term `text_term("body","alpha")`, independent `And` wrapper via existing `legacy_text_query`. n=df=40, total length 180, avgdl 4.5. For K in `[1,3,10]` and directions Asc/Desc, create same explicit `doc_id_sort`, projection `scoring_projection`. Require literal ordered IDs `s0000..` or `s0039..` (derive from input, not engine), `total_hits=40`, full projected fields from `scoring_document` input (`doc_id` and exact body string, in projection order; compare existing `FieldValues`), every score Some finite nonnegative and exact bits from the scalar input formula in U07 (use actual tf and dl, no copied production scorer as only oracle). Compare ordered keys, projected fields, score bits, total, generation/view, aggregation against wrapper Legacy. Compare cursor `snapshot_binding`, `last_key`, `last_sort_values`, `last_score()==None` with wrapper; wrapper query has different fingerprint, so **do not assert full cursor equality across different ASTs**. Repeat the exact original query and assert full `UnifiedResponse` equality plus explicit score bits and full cursor equality. Follow original cursor with same query/sort and K, require next literal page no skips/duplicates and exact scores. Assert six combinations complete. Existing 9 public C2 integrations run unchanged in addition.

### I02 `c3_i02_real_pit_update_merge_and_paging`

Use same real scoring schema, 40 rows split 6/34 as I01; keep reopened Index and pinned old snapshot. Create a writer from the index and apply exactly `MutationRequest::delete(DocumentKey::new("s0002").expect(...))`, `MutationRequest::upsert(updated)` with `updated=scoring_document(6)` whose body overwritten with Text `"gamma"` (no alpha), and insert `scoring_document(40)`; commit and refresh as existing C2 I03. Old snapshot still exactly 40 matches, new snapshot exactly 39 (0..40 inclusive excluding 2,6). For each snapshot use `UnifiedSearcher::new` and same term/sort/projection, K=3 ascending. Collect pages until None with hard bound 20 pages; first page and every continuation require same exact total, literal sequence and no duplicates; check score bits against a same-snapshot wrapper Legacy first page, and scalar formula for every returned doc using input-derived n,df,total lengths including the updated nonmatching doc. New snapshot n=40 (delete one/add one), df=39, old total length=180, new total length = `180 - dl(2) - dl(6) + 1 + dl(40)` where dl(i)=1+i%4+i%5, so 180-5-4+1+1=173; avgdl 173/40. Recompute literal arithmetic from the input array, assert exact integer totals. Updated doc remains live and contributes length 1 but not a match. Preserve old response and cursor before mutation; run old snapshot again after new publication, compare exact response bits and cursor, do not accept an old cursor on new snapshot (same exact error as existing cursor rejection test, exact `SearchError::Query(QueryError::InvalidQuery(InvalidQueryReason::CursorPitMismatch))`, using `quervant_core::contract::error::{QueryError, InvalidQueryReason}`). Then `writer.compact(); writer.commit()` and reopen as existing I03. Query both old pinned and reopened new snapshots, exact old results unchanged and new logical results/count/score bits identical to new precompaction view (generation/view/cursor binding legitimately changed; do not compare cursor identity across views). Actual new source/codec remains unchanged; no writes except these normal real fixture operations. No assumption about native segment ordinal order in this integration test. Test the exact paging keys on both pre/post compaction. If writer API/schema/fixture does not support the specified mutation, STOP D04; do not reduce to MemoryDirectory.

### I03 `c3_i03_real_resource_and_cancellation_edges`

Use the exact same real filesystem `c2_i08_resource_cancellation_atomicity` fixtures, request/projection, limits and expected literal keys; copy its test body into the new test (do not weaken or edit I08). Single 48-row B4 corpus, K=3, `key/common`, 23 matches; exact candidate caps 69/2944, failures `{68,69}`, `{2943,2944}`. Two-segment corpus 0..24 and 24..48 scanned boundary `{22,23}`, cap23 success, pre-cancelled flag gives typed Cancelled. Require all exact failures, independent same-snapshot retry success, complete response parity including actual score bits, all fields, full cursor, total/generation/view/aggregation. In addition compare the admitted and retry results to existing public `legacy_query("key","common")` with default limits on the same snapshot (different cursor fingerprint: compare all cursor fields except fingerprint; for same-query retry use complete equality). Require literal first three keys from existing `expected_lane_keys` formula, total23. Report exact cap outcomes and retry identities. Existing I08 also executes and remains preserved. This deliberately reuses the public failure-path matrix under default C3, not a claim of new real memory-accounting mechanisms. Do not run timed workload or profiler.

## 9. Failure, retry, identity and compatibility contract

- The certificate is request-local and cannot escape `collect_mixed`. It borrows the exact already-prepared field and term until the heap is finalized; neither a snapshot cache nor a new persistent proof is introduced. The guard/readers/`SnapshotStats` outlive finalization. The physical identity is `(segment_index, doc_id)` in the pinned reader snapshot, not the logical key alone, a generation number alone or a B3 hash. Key ties and duplicate identity remain byte-exact. The `NonZeroU64` in a retained entry belongs to that physical hit; a replacement evicts the entire old entry.
- Existing immutable segment IDs/content digests, manifest generation, snapshot `binding_id`, local cache keys and remote ObjectStore keys keep their distinct meanings. C3 writes none of them. No new section, sidecar, serialized representation, compatibility version, durability or commit boundary. No existing committed data rewrite or index rebuild required. Existing local atomic commit/fsync, remote conditional publication, restart and old reader retention remain owned by the existing Index/Writer/Directory/SegmentStore/SegmentCache/ObjectStore components. I02 checks lifecycle by using those components, not by changing them.
- Before selection: original request validation, cursor checks, stats, B1 preparation, duplicate-state creation and all associated errors remain in place. Certificate unavailability is a successful *decision* for eager C2, not a new `SearchError` and not a retry. An unexpected corrupt read, resource refusal not already optional in B1/B3, score error or cancellation never causes a second route attempt.
- Per segment: original column/ordinal, JSON/geo, posting stream, work/virtual reservations, eager score if unproven, candidate key/row/hash/duplicate/heap operations, and release sequence remain. B1 NotAvailable retains existing Legacy route; B1 error is authoritative. B3 optional refusal/ExactSet use existing owned-key path; B3 error is authoritative. Any existing error in a nonwinning row still surfaces. No lazy score exception hidden by a later candidate or later segment.
- After collection: a private mismatch or unexpectedly fallible score in finalization propagates `Err`; because the request has not produced a response, no partial page is published. Do not replay eager or Legacy. If such an error is reached with a purportedly certified **real** request, acceptance stops (proof defect, D11); no policy to downgrade after selection. Existing projection/response budgeting may still fail after scoring exactly as C2; C3 does not waive those errors.
- A failed or cancelled search destroys request-local state, not the pinned immutable reader. Same-snapshot retry builds a new certificate and heap, returns the exact admitted result, and cannot reuse or leak private raw tf. Cooperative poll sites and logical totals, not wall-clock scheduling, are preserved. The deterministic cancel test is not a latency benchmark.
- No new network call, asynchronous task, lock, cache, synchronization primitive, unsafe code, dependency, public trait or format change. No reliance on filesystem behavior beyond existing real test path. Existing reader tests, including the A2 thread-local certificate observation, are retained byte-for-byte. Separate compiler/target-specific heap layout check (U12) is mandatory; this is not a public ABI promise.

## 10. Execution, QA and reproducible evidence

### 10.1 Order and immutable source points

Execute continuously in this order. The listed stages are checkpoints, not requests for permission.

1. G0: fetch, pin B, confirm exact branch/PR state, source/consumer inventory and file allowlist; record exact plan hash, compiler, tool versions and source blobs. Read governing documents and answer §6 worksheet (G1). Do not edit a prior C2 plan. Create local branch as §2.2. Prepare the evidence directory outside the checkout until delivery.
2. Baseline: execute §10.2 against B (before source modification), record original test inventories and exact baseline receipts. Any failure => §11, not a green-by-retry. Write the minimal red instrumentation/test, `cargo fmt --all`, commit RED as §6.1. Run red once with receipt. Record exact B..RED diff and digest. Do not implement production change until expected red is established.
3. Implement P1–P5 and tests in order; run focused commands as each section becomes coherent. Do not commit or publish a partial solution as accepted. Scope check and formatter; inspect any changes to protected files. Once ready, commit all final source/test modifications as **TESTED**. Include the exact approved plan if desired; if included, verify bytes/hash before commit. `git status --porcelain=v1 --untracked-files=all` must show no unexpected tracked change and only recorded disjoint untracked paths. No staged or dirty source during final commands. Record `git rev-parse HEAD`, tree and commit ancestry. Verify B..TESTED source allowlist, `git diff --check B...TESTED`, worktree and staged checks. All final commands and receipts reference this immutable commit.
4. Execute every final targeted/inventory/QA command in §10.2–3 from TESTED. Exact failure taxonomy in §11. If authorized mechanical fix is necessary after TESTED, record old failing receipt, fix only authorized cause, make new TESTED commit, repeat all affected final QA (all Rust QA, coverage and acceptance on source/test change). Never overwrite old attempts. Successful earlier commands cannot be attributed to changed source. Do not repeatedly run commands just to get green.
5. Inspect all output and decode receipts, assert inventory/row counts, inspect changed production coverage, run source/diff audit and adversarial review §10.4. Generate report, raw receipt manifest and append-only documentation updates (§12); no historical rewrite. Stage exactly allowlisted paths. Check `git diff --cached --check`, commit docs/evidence, require `git diff --check B...HEAD`, verify equality of all non-document paths TESTED..HEAD. Capture exact DOCS_FINAL, push after all local required checks pass; if blocked, push a draft only when safe to preserve work and clearly label blocked, never a readiness claim. Do not publish the intentionally red revision alone.
6. Create one draft PR with `gh pr create --draft --base main --head dev/perf06-c3 --title ... --body-file ...` if none exists; use actual assigned number. Do not toggle readiness or merge. Inspect required ordinary CI on the actual final head and exact base merge ref. No duplicate dispatch, CI rewrite, push-trigger addition or manual second job to mask a failure. If genuinely queued/running, mark CI pending; do not wait indefinitely (bounded §11). Local PASS does not substitute for required CI or real-body logs.
7. Final delivery: verify remote `H` equals local last pushed HEAD and exact PR metadata, check B still the applicable merge base. Validate all receipts and committed range at H, check non-doc equality with TESTED, record CI head/merge SHA/jobs. Use the terminal report block in §12 to give **all final identity/range facts inline**, plus attachment/link of actual bytes for any external evidence. No requirement for a separate ZIP if the complete terminal facts are inline and all raw command receipts are committed; this avoids C2's lost attachment and endless self-referential commit. Update PR body using `gh pr edit --body-file ...`, fetch it back, compare text, keep `draft=true`, no further docs commit merely to record H (the final live PR body/terminal report can name H and CI run). If any docs-only change is genuinely required after push, repeat final range/identity/metadata checks and observe the new head's CI. Do not run Rust QA again for strictly docs-only, source-equivalent changes unless a doc consumed by build/test changed. Evidence always names what actually executed.

### 10.2 Exact command catalog (baseline and targeted final)

Use `export` only for existing approved environment setup; unset experiment overrides for all commands. Commands in this section run from workspace root with the existing Cargo configuration. Do not invent a script or change test harness. Record each invocation separately with §10.5 recorder; filters must select intended test names. Use literal `cargo +1.98.1` (stable used in current CI) and `cargo +1.85.0`. If a listed supported toolchain is unavailable, D06. No bare performance commands. The named regression targets below are actual existing tests; first verify names at B. A missing target is D04. `--test-threads` is a test invocation configuration, not a global serialization workaround.

Baseline at B, execute (not just list):

```sh
cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u -- --list --format terse
cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p -- --list --format terse
cargo +1.98.1 test -p quervant-core --lib c2_ -- --list --format terse
cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --list --format terse
cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib segment::reader::stored_blocks_reader_tests:: -- --test-threads=8
cargo +1.98.1 test -p quervant-core --lib search::score::tests:: -- --test-threads=1
```

Require B exact C2 inventories (24/5/39/9), real executions and zero unexpected failures. Preserve receipt for any unexpected baseline discrepancy; do not modify B or C2. If the score module's test selection is empty due to a namespace contradiction, D04 (verify actual registration rather than guessing). Existing CI at B can be recorded as supporting historical evidence, never replacement for baseline commands.

Final inventory at TESTED:

```sh
cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u -- --list --format terse
cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p -- --list --format terse
cargo +1.98.1 test -p quervant-core --lib c2_ -- --list --format terse
cargo +1.98.1 test -p quervant-core --lib c3_ -- --list --format terse
cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --list --format terse
```

Expected 24/5/52/17/12, actual name sets as §7.1 and §8. Compare the old inventory using exact names, not arithmetic alone. Final C3 focused case output: execute each individual named test once with `--exact --nocapture --test-threads=1`, using this fixed table to construct the command (no fuzzy matching). Use `cargo +1.98.1 test -p quervant-core --lib <full-name> -- --exact --nocapture --test-threads=1` for unit rows, `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical <name> -- --exact --nocapture --test-threads=1` for integration rows. Names below are mandatory registrations, not suggestions.

| ID | Full unit name / integration name |
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

Each focused invocation must execute one test and pass; expected matrix completion lines must be present. Run all suites as well (not a substitute for the focused output):

```sh
cargo +1.98.1 test -p quervant-core --lib c3_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib c3_ -- --test-threads=8
cargo +1.85.0 test -p quervant-core --lib --all-features c3_ -- --test-threads=8
cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u -- --test-threads=8
cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p -- --test-threads=8
cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib search::score::tests:: -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib segment::reader::stored_blocks_reader_tests:: -- --test-threads=8
cargo +1.98.1 test -p quervant-core --lib b1_
cargo +1.98.1 test -p quervant-core --lib b2_
cargo +1.98.1 test -p quervant-core --lib b3_
cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals
cargo +1.98.1 test -p quervant-core --test perf06_b2_ordinals
cargo +1.98.1 test -p quervant-core --test perf06_b3_keys
cargo +1.98.1 test -p quervant-core --test pr15h_a_candidate_materialization
cargo +1.98.1 test -p quervant-core --test pr15h_a2_dispatch
```

All required tests must run, pass, and retain the accepted existing ignore set (existing opt-in RustFS cases run through real-service job). Explicitly check existing eager C2 U12 `completed=9` and all U17/U21 rows; focused C3 tests do not supersede them. Use exact C2 receipts where detailed row parity is required: add focused serial `--exact --nocapture` executions of old `c2_u12_corrupt_selected_unselected_and_multi_fault`, `c2_u17_ordinal_unavailable_and_b3_refusal`, `c2_u21_work_budget_exhaustion_after_prior_segment` using same full `search::unified::c2_tests::` prefix; and `search::execute::c2_physical_tests::c2_p05_n_examination_and_scanned_frequency`. Names verified at B; preserve original expected case lines (they describe the forced eager branch, not C3). The local filesystem integration suite contains both old 9 and new 3 real tests. Report child-process summaries separately from top-level target totals; no double counting, no inference of absent tests from interleaved output. Inventory counts are unique registrations, not repeated executions.

### 10.3 Final local workspace gates and ordinary hosted CI

All commands below are mandatory on the final immutable TESTED source. No undocumented substitutions; both tools and both features explicit. Stable default/all-features and MSRV default/all-features coverage of tests/lints; coverage measured on stable, both feature regimes, minimum 85% workspace line coverage. Do not lower threshold or exclude a new module/file. Run docs and bench compilation only as repository QA (not an actual benchmark).

```sh
cargo +1.98.1 fmt --all -- --check
cargo +1.85.0 fmt --all -- --check
cargo +1.98.1 clippy --workspace --all-targets -- -D warnings
cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 clippy --workspace --all-targets -- -D warnings
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.98.1 test --workspace --all-targets
cargo +1.98.1 test --workspace --all-targets --all-features
cargo +1.85.0 test --workspace --all-targets
cargo +1.85.0 test --workspace --all-targets --all-features
cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85
cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo +1.98.1 doc --workspace --no-deps
cargo +1.98.1 doc --workspace --all-features --no-deps
cargo +1.98.1 bench --workspace --no-run
bash benchmarks/scripts/test-scripts.sh
```

Use actual totals from decoded `TOTAL` coverage lines (total, missed, covered=total-minus-missed, percent). Record actual tool version and output. Inspect new certificate, both wrapper paths, finalizer success/mismatch, both B2/B3 routes and fallback; coverage of a pre-route branch is not coverage of actual candidate validation. Explain uncovered unreachable/internal defensive paths without weakening the floor; if behavior is not tested under the prescribed cases, STOP rather than invent additional architecture. Coverage is necessary not sufficient.

Ordinary CI `.github/workflows/ci.yml` five jobs: `rust`, `msrv`, `python-benchmark-framework`, `benchmark-adapter-contract`, `rustfs`. Require each completed success on the final applicable PR merge ref; record workflow run URL/ID, event, workflow head SHA, merge checkout SHA and parent base/head; verify actual job log target executions and actual RustFS real test bodies (not mere successful empty filters). Existing CI includes the real S3 adapter, remote core/reader, mutation, restart, compaction, crash and proxy tests. No new local RustFS bootstrap is mandated: C3 modifies request-local scoring, not remote storage/codec/materialization; actual new real integration is local `FsDirectory`, existing hosted RustFS is the required remote regression. If actual CI logs are not available, D21 (cannot claim real-body proof). For no access to a required real boundary, G8 BLOCKED. Keep CI and benchmark framework unchanged. Use ordinary CI, never launch a real cross-engine benchmark. Existing synthetic/mocked adapter contract and compile checks are regression only.

CI may show successful `git diff --check` against a clean working tree; **that is not** a committed-range whitespace gate. Require local raw `git diff --check "$B"..."$H"` exit zero; a previous C2 exception does not apply to the new range. Check staged and working tree as well. No new whitespace exception preauthorized.

### 10.4 Exact scope/source audit and adversarial self-review

Create `evidence/c3/source-audit.md` plus machine-readable path lists and diff SHA-256 (lossless encoded patch if committing raw diff would introduce whitespace). Compare `git diff --name-status "$B" "$TESTED"`, `git diff --name-status "$TESTED" "$H"`, both `--check` ranges. Every non-doc path outside the four source/test files is protected. Do not rely on the report's textual assertions or `git status` alone. Use exact Git blobs of B and TESTED; compare all unchanged functions by byte equality, not just similar logic. The following procedure is prescribed to implement the reviewer check with Python 3 stdlib and `git show`: extract each top-level function/item from the named existing source by matching its exact declaration and ending at its column-zero closing brace (or next named top-level declaration); for nested `impl` methods start at exact four-space `fn ...`, end at its four-space closing brace. If an anchor is missing/ambiguous, STOP D04. Compare the original and final contents, including comments where no change authorized. Record all command/script bytes in the evidence, not just a boolean. For exact mechanical plumbing, reverse only the named inserted `None` argument or field at its matched call/literal and compare original; compare any reindentation by stripping the identical added common indentation only. Do not use a broad whitespace-insensitive comparison to claim semantic equivalence.

Protected comparisons (record individual PASS/FAIL):

| Source | Required exact checks |
| --- | --- |
| `score.rs` | `bm25`, `idf_log`, `prepare_idf`, `bm25_with_idf`, `compute_stats`, `FieldStats::length`, `doc_freq` unchanged; `FieldStats::bm25_score` equals original after removing the one test-only call; new token uses original scorer with exact accumulation; no other producer or mutation of stats in normal build |
| `execute.rs` | `build_leaf_data`, `take_strict_one_term_postings`, `effective_live_examination_count`, `evaluate_lexical_with`, `visit_lexical_membership_with`, `SegmentCandidateLedger` and candidate budget helpers unchanged; original eager loop inside const branch matches B after indentation adjustment, decoder/N/membership/admission/drop/release/finish and callback ordering unchanged; final callback raw word and two typed wrappers only; all five old direct C2 tests unchanged |
| `unified.rs` | `strict_term_dispatch_eligible`, `keyword_ordinal_eligible`, existing B1 preparation, `d3c` module, `heap_admit_candidate`, `candidate_charge*`, `ordinal_candidate_order`, `MixedEntry` comparison impls, `SelectedHit`, public request/response, `project_selected_hits`, cursor validation/construction, `select_keys` unchanged; Legacy loop matches B after only two added `None` arguments and one literal field; ordinal handlers match B after only added signature parameter and entry field; C2 setup/cleanup matches B; exactly two compile-time mode instantiations, no per-hit dispatch. The rest of `collect_mixed` is the original shared sequence except P4 test shadow/once selector/final conversion |
| tests | B old C2 24 function bodies equal final after removing exactly one first-line ForceEager guard; test helper `reset_witnesses` only additional resets; four B2 call changes and four old `MixedEntry` test literal fields, all other old B1/B2/B3/reader and historical tests unchanged; integration file original prefix exact; every new named registration exists exactly once |
| all other files | `git diff B..TESTED --name-only` contains only exact scope paths and the approved plan if present; after TESTED only docs/evidence allowed. Check `Cargo.*`, toolchain, `.cargo`, `.github`, benchmark/config/script, other crates, segment files, docs not named in allowlist, generated/ignored source inputs remain unchanged |

If a machine extraction is unavailable because of source formatting, D08 permits a recorded exact manual `git diff --unified=...` hunk-to-step audit of the same named regions; not omission of source check. No arbitrary formatting pass across old code. Format changes within new code only. A protected-source diff is D10. Include full exact final Git diff digest, tested tree, red patch digest, source audit tool/commands and result, protected comparisons and review notes. Proof of no extra M allocation: inspect every new production `Vec`, `collect`, `try_reserve`, `clone`, `HashMap`, `Box` and scorer call; only existing heap conversion/selection, original posting vector and no new per-match allocation. Any unexpected new allocation outside original operations is a defect. Check actual new layout output and no new charge arithmetic. `git diff --check` all relevant ranges mandatory; source-freeze artifact must be independently replayable from exact named commits.

Final adversarial questions (answer with evidence, not yes/no):

1. Could an uncertified loser with a score fault be skipped or displaced by a key/heap failure? Explain U03 and actual U04 mixed-fault precedence; no new validation at preparation.
2. Could early successful segment be returned/scored despite later failure? U05 and exact counters. Could a rejected candidate skip decoder or work/byte charge? P01, U09, C2 regression.
3. Could the sentinel be scored or leak score None? U07/U12 and exact cursor/projection source. Could a frequency attach to the wrong physical row after eviction, across segment ranks or after PIT mutation? U07/U11/I02.
4. Could a B3 collision/refusal, null/MultiOne, missing field or ineligible query choose a different path? U02/U06/U08/U13/U14, protected B1/B2/B3 algorithms. Could force arms or synthetic mutations contaminate another thread/test? Inspect TLS RAII and repeated parallel runs.
5. Could source-level refactor impose per-hit dispatch or change legacy comparison/accounting? Show exact diff and layout; preserve legacy statements. Report physical layout effect and no warm-performance assertion; C4 guards.
6. Could a PASS be based on zero selected tests, skipped matrix rows, stale output, missing CI or misleading count? Show exact name sets, executed rows, manifest verification, raw output and final remote identity; distinguish synthetic and real evidence, current and historical. Do not report unsupported terminal attachment or hidden waiver.

### 10.5 Lossless receipts, no recursive whitespace or phantom delivery

Use one recorder for baseline, red and final commands. It may be an external script during execution, then commit the exact script with evidence. It is not new production tooling. Implement **exactly** the following standalone Python 3 stdlib recorder, saved as `docs/pr-artifacts/perf-06-c/evidence/c3/record.py` at delivery (keep a working copy outside checkout during baseline/QA). Invoke `python3 <recorder> <absolute-output.json> <expected-commit> <label> <command...>` from repo root. `expected-commit` is immutable B, RED or TESTED as appropriate. Command arguments are actual argv, no shell string; for existing shell script use `bash` argv as listed. Sanitize experiment overrides in child; record explicit environment removals, tool versions in preflight receipt, actual cwd, UTC times, before/after commit/tree/index status, return code, raw stdout/stderr combined exact bytes and SHA-256. `capture_output` of small direct command results is bounded by ordinary test logs; record separate attempts not aggregate giant transcript. No timing measurements beyond receipt start/end. No retries automatically. Store JSON with single newline; Base64 prevents raw output whitespace from introducing git diagnostics.

```python
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess as sp
import sys


def run_git(*args):
    return sp.check_output(["git", *args], stderr=sp.STDOUT)


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def identity():
    return {
        "head": run_git("rev-parse", "HEAD").decode().strip(),
        "tree": run_git("rev-parse", "HEAD^{tree}").decode().strip(),
        "index_tree": run_git("write-tree").decode().strip(),
        "tracked_status_b64": base64.b64encode(
            run_git("status", "--porcelain=v1", "-z", "--untracked-files=no")
        ).decode("ascii"),
    }


def main():
    if len(sys.argv) < 5:
        raise SystemExit("record.py OUTPUT EXPECTED_COMMIT LABEL COMMAND [ARGS...]")
    out = Path(sys.argv[1])
    if not out.is_absolute() or out.exists():
        raise SystemExit("receipt path must be absolute and new")
    expected = sys.argv[2]
    label = sys.argv[3]
    argv = sys.argv[4:]
    env = os.environ.copy()
    removed = ["QUERVANT_PR15I_D3C_STRATEGY", "QUERVANT_PR15I_D3C_PREFILTER_PROFILE"]
    for name in removed:
        env.pop(name, None)
    before = identity()
    if before["head"] != expected or before["tracked_status_b64"] or before["tree"] != before["index_tree"]:
        raise SystemExit("source admission failed before execution")
    start = utc()
    result = sp.run(argv, stdout=sp.PIPE, stderr=sp.STDOUT, env=env, check=False)
    end = utc()
    after = identity()
    raw = result.stdout
    valid = before == after
    receipt = {
        "schema": "quervant-perf06-c3-receipt-v1",
        "label": label,
        "cwd": os.getcwd(),
        "argv": argv,
        "removed_env_names": removed,
        "started_utc": start,
        "ended_utc": end,
        "expected_commit": expected,
        "before": before,
        "after": after,
        "source_identity_valid": valid,
        "command_exit_code": result.returncode,
        "combined_output_size": len(raw),
        "combined_output_sha256": hashlib.sha256(raw).hexdigest(),
        "combined_output_base64": base64.b64encode(raw).decode("ascii"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    sys.stdout.buffer.write(raw)
    return result.returncode if valid else 125


if __name__ == "__main__":
    sys.exit(main())
```

Use a separate preflight/scope record to record ignored/untracked source/build-input check, exact toolchain versions and applicable environment variables without secrets. This recorder's tracked-source check does not by itself prove absence of ignored configuration changes. Reject shadow inputs in G0. If `sp.run` fails to launch, preserve actual launch error, no fabricated receipt; D06. Git write-tree writes a Git object representing current index, not source or a commit; clean before/after required. Do not capture secrets or credentials; known commands should not emit them; any unexpected secret => D22, stop publication and request safe disposition. Never rewrite raw evidence to hide a failure; if credentials are present, retain locally restricted and record redaction reason/hash only after human approval. No raw history rewritten.

Every receipt's exact expected commit and argv, source identity flag, exit code, output size/hash and Base64 must be independently checked before manifest inclusion. Use `base64.b64decode(value, validate=True)` then SHA-256 and length equality; verify unique receipt path, unique label+attempt, actual registered test/rows, exact command. For expected red require exit101 with the precise panic and one executed test, classify EXPECTED_RED; all required final commands exit0 and valid identity. No auto-parser may classify PASS merely because exit0 if a required exact test didn't execute. Report counts from actual target summaries and exact inventory names; interleaved subprocess output can prevent a unique aggregate; preserve raw, mark a derived total ambiguous and report unambiguous top-level counts and observed child results separately, not a made-up number. No test rerun solely to get prettier aggregate. Coverage must have one actual final `TOTAL` row from each command; parse correct labels (total minus missed). Store an index/manifest JSON including each receipt's label/path/command/source/actual exit/classification/size/sha256, plan hash, recorder hash, source audit hashes, expected red and tested commit, baseline inventories, final inventories and matrix counts. Verify manifest by reading each actual committed file and rehashing; manifest's own SHA-256 is recorded in report and later terminal block, not recursively in itself. Reject missing or extraneous receipt or unjustified attempts.

Record raw Git check exit/stdout/stderr for each check, including failure, outside the checked commit or in Base64 JSON. Never commit a raw `git diff --check` transcript containing its own whitespace diagnostic lines. Require plan and all new files no trailing whitespace/no extra blank EOF; do not rewrite an approved plan if its hash mismatches, STOP D04. After last docs commit, verify raw exit code and stdout `git diff --check "$B"..."$H"` and `"$TESTED".."$H"`, `git diff --check`, `git diff --cached --check`. If exit0, output empty, give that fact and exact command/H inline; else provide actual diagnostics losslessly (external attachment or Base64 inline) and BLOCKED. Never say a clean working tree proves the full range clean. No self-referential final commit. For terminal identities, final PR body and full inline report suffice; any supplemental ZIP/Markdown named by path must be actually attached or supplied as a working accessible URL, not merely a local `/tmp` path/hash. Preserve all prior failed receipts. No further evidence-only rerun after acceptance unless a new defect is identified.

## 11. Preauthorized decisions and exception-handling matrix

This matrix is exhaustive for agent discretion, not for possible world states. **AUTO-RESOLVE** means perform exactly the authorized operation after verifying the trigger. **DEFER AND CONTINUE** means keep the named gate blocked, record the evidence, do independent authorized work only. **HARD STOP** means stop affected work immediately, report exact observation and request smallest human amendment; continue only tasks provably independent, never implement a dependent guess. If no row applies, D32. If several apply, most restrictive controls. Owner M=maintainer/plan author (architecture, scope, any waiver, acceptance); E=execution environment/repository access owner; R=independent reviewer. Agent may not self-authorize a waiver. Every applied rule is recorded with ID, actual trigger, source, action, verification, gate and owner. Routine success is not a reason to ask permission.

| ID | Observable trigger / source precondition | Category | Authorized response | Prohibited response | Evidence / gate / owner |
| --- | --- | --- | --- | --- | --- |
| D01 | Repo/base #131 merged exact B; no branch; clean tracked inputs | AUTO-RESOLVE | Create specified branch from B, proceed | Old branch reuse, arbitrary PR number, new base | preflight refs; G0/M |
| D02 | Existing disjoint foreign untracked files with verified no build/test influence | AUTO-RESOLVE | List paths, leave untouched and never stage | delete/stash/modify them; blanket add | status and input check; G0/G9/M |
| D03 | Existing C3 branch local/remote exactly B, no commits or conflicting PR | AUTO-RESOLVE | Use exact branch after fast-forward if required and safe | reuse nonempty work, reset/force/rebase | exact refs and PR metadata; G0/M |
| D04 | Main/merge/source blob, function/call inventory, fixture source, format/layout or approved plan hash differs; required test absent | HARD STOP | Record actual vs expected and smallest amendment | adapt fixture/caps/offset/API/branch by guessing; silently change plan | source/fixture receipts; affected G0–G6/M |
| D05 | Tracked dirty work, ambiguous untracked/ignored build config, unexpected C3 branch work or PR | HARD STOP | Preserve and report exact paths/commits | wipe/reset/stash/rebase or run uncertain source | status; G0/M |
| D06 | Required compiler, command, test tool or local infra unavailable | DEFER AND CONTINUE | Attempt ordinary documented setup (existing toolchain/dependencies); record precise blocker, continue safe other work | unsafe system changes, replacing required test by CI or fake, claim PASS | setup/launch logs; affected G0/G5/G7/E |
| D07 | Actual C2 or repository baseline test failure | DEFER AND CONTINUE | Preserve full raw result, identify whether pre-existing using same baseline proof; stop dependent acceptance; allow independent design/source audit | fix unrelated old code, retry until green, waive test | B receipt; affected gate G6/G7/M |
| D08 | Exact P1–P5 algorithm accepted but Rust compiler/formatter/lint requires purely mechanical lifetime annotation, borrow closure block, import/qualification, identifier formatting or explicit argument type | AUTO-RESOLVE | Make only the enumerated equivalent change, within authorized regions; record before/after diff and both toolchain check. For nested test-only fault pattern, use one `if let Some((field_id, term)) = match ...` with match `[CompiledLeaf::Term {field_id,terms}] => match terms.as_slice() { [term] => Some((*field_id,term)), _=>None }, _=>None` if needed to avoid collapsible-if lint on stable; no MSRV-incompatible let chains. Exact manual region audit permitted as §10.4. | change logic, public signature, add broad allow/ignore, clone, heap/scratch, `unsafe`, weaken asserts | compiler/diff; G2/G7/R |
| D09 | RED exit101 exactly one expected 40 vs 3 count failure | AUTO-RESOLVE | Preserve red receipt, proceed to P1–P5 | classify expected red as final fail, discard it | RED hash/output; G1/G3/R |
| D10 | RED unexpected outcome, private entry >old+8 or alignment change, extra allocation/new production instrumentation, protected source diff, actual source proof invalid | HARD STOP | Preserve actual evidence and stop affected implementation; report architecture contradiction | alternative representation/packing, reduced coverage/test, new design, accept unexpected red | red/layout/source diff; G2/G3/M |
| D11 | Real certified request can produce score error; error precedence, poll schedule, ledger, bit parity, cursor, actual callback or final score count differs from table | HARD STOP | Return failure; preserve raw failing case/source, isolate and request amendment | catch/replay eager, change proof bounds/caps/cases, use approximation, weaken checks | typed payload/identity/counters; G3/G4/G5/M |
| D12 | Existing C2 predicate false (static shape, cursor/batch, no B1 Ready, M<=K+1) | AUTO-RESOLVE | Original Legacy once | broaden eligibility, invoke certificate for Legacy, score only K on relevance | U02/source; G3/R |
| D13 | C2 strict selected, all §3 proof guards pass, no test-only override | AUTO-RESOLVE | Issue token, default C3 with typed raw frequency and final-only scoring | defer on partial proof, reselect per segment/doc | S/U witnesses; G3/R |
| D14 | C2 strict selected but any certificate guard fails | AUTO-RESOLVE | Entire request eager C2 before candidate; original error/zero behavior at score site | return new preparation error, fallback after candidate, special zero bypass | S01/U03; G3/G4/R |
| D15 | Existing B1 NotAvailable/real error or B3 optional refusal/ExactSet/real error | AUTO-RESOLVE | Preserve exact B1 Legacy/error or B3 owned path/error as §3/9; no new fallback | ignore genuine error or replay request, disable duplicate check | original regressions + U06; G4/R |
| D16 | Existing C2 synthetic late-score arm or ForceEager applied in unit test | AUTO-RESOLVE | Force eager strict path only if already eligible; keep test-only; preserve arm until drop | change real scorer, share synthetic fault with Legacy or introduce normal-build flag | P5/U04/old C2; G4/R |
| D17 | Expected exact typed cap/cancel/corrupt errors and same-snapshot recovery pass | AUTO-RESOLVE | Record actual exact row, continue | call expected negative case a failure of implementation; substitute success | P/U/I receipts; G3–G5/R |
| D18 | Required matrix case not executed, unexpected error, row completion/inventory mismatch or test selection zero | HARD STOP | Diagnose boundedly; if sole cause is exact CLI typo and registered name/fixture confirmed, correct to catalog command once, preserve old receipt; otherwise request amendment | skip case, reduce fixture, change expectation, wildcard instead of exact | raw output/name sets; G3–G6/M |
| D19 | Local fmt/clippy/QA failure directly attributable to a permitted mechanical D08 mistake | AUTO-RESOLVE | Apply D08 once per identified cause; new immutable TESTED, repeat full affected local QA and required CI | retry without correction, modify CI/floors, blanket suppress lint | failure/fix diff/new QA; G2/G7/R |
| D20 | Unexpected regression or coverage failure not D08, even if seems flaky | HARD STOP | Preserve actual failure; one diagnostic exact same command run allowed only to establish nondeterminism, with both receipts; compare B if needed. Keep gate blocked, request exact scope | retry-to-green, waiver, disable parallelism/change filters, edit unrelated tests | raw fail/repro/base evidence; G6/G7/M |
| D21 | CI queued/running, access denied, missing real-body logs or external service unavailable | DEFER AND CONTINUE | Observe ordinary run, bounded polling (up to 20 polls, 30s interval; stop sooner if terminal); capture known jobs/status/URL, report CI_PENDING or BLOCKED. Continue local docs/evidence | trigger duplicate CI, invent result, substitute empty filters or fake RustFS | job/run evidence; G8/E |
| D22 | Secret or sensitive external data appears in raw output | HARD STOP | Do not commit/publish affected raw file; preserve restricted bytes locally, record safe metadata and request redaction disposition | publish secret, silently rewrite record or fabricate clean output | restricted receipt metadata; G9/M |
| D23 | New committed range whitespace diagnostics | HARD STOP | If diagnostic only in newly authored non-frozen prose/receipt wrapper, before freeze correct whitespace losslessly (Base64 raw preserved), verify hash/raw bytes and range; otherwise report exact new diagnostics and request decision | reuse historical C2 exception, rewrite frozen plan/raw evidence or call failure PASS | actual git checks; G7/G9/M |
| D24 | Command output interleaved so derived aggregate count ambiguous, but required target launches/names/exit and cases verified | AUTO-RESOLVE | Report exact unambiguous top-level count/targets and separate observed child summaries; identify ambiguous derived aggregate; preserve raw | infer missing or fabricate total, rerun solely for pretty count | raw receipts; G9/R |
| D25 | Manifest/receipt hash or required attachment/terminal facts missing or disagree | HARD STOP | Recover actual bytes if retained, recompute honest current final metadata for same H, or qualify missing evidence; do not claim G9 PASS until delivered and verified | backdate/fabricate old output, cite inaccessible path as delivery | verification inventory; G9/M |
| D26 | Docs-only change after TESTED, all protected source/build inputs byte-identical | AUTO-RESOLVE | Retain local Rust evidence, repeat range checks/remote identity/new head CI as applicable | claim old head CI for new head without linkage, endless commit to store its own hash | immutable compare; G7–G9/R |
| D27 | Required CI completed success, actual run head/base linkage and logs verified | AUTO-RESOLVE | Record exact run/jobs; continue draft review handoff | equate CI with missing local verification, merge or toggle draft | run/job IDs; G8/R |
| D28 | New main movement, PR conflict, unauthorized status/head change or write permission failure | DEFER AND CONTINUE | Preserve branch/current results, report exact metadata and blocker; do safe independent local verification; await new baseline/delivery instruction | merge/rebase/force-push or toggle another actor's PR | current refs and status; G0/G8/G9/M or E |
| D29 | Every intermediate checkpoint passes | AUTO-RESOLVE | Continue immediately to next prescribed stage; no confirmation | stop at a routine checkpoint or wait for human signoff not required by plan | sequential ledger; all gates/R |
| D30 | All G0–G9 pass on same applicable source/H, G10 still open | AUTO-RESOLVE | Push draft, update/read back PR description, hand off `PERF06_C3_READY_FOR_INDEPENDENT_REVIEW` | mark roadmap DONE, merge, accept performance or start C4 | final report; G10/M |
| D31 | Host idle or someone requests real benchmark/profiler/acquisition while executing this plan | HARD STOP for performance task | Do not run it; continue correctness tasks only; C4 owns approved performance | any timing campaign, benchmark sample, profiler, warm target claim | no-acquisition declaration; G9/M |
| D32 | Any unlisted condition, unavailable contract, architectural ambiguity, inability to meet proof/test invariants | HARD STOP | Halt affected work; if independent safe tasks can proceed, do only those; record alternatives/recommendation and exact decision required from M | improvise architecture, broaden scope, weaken test/contract or self-approve | scoped stop record; affected gate/M |

For failure taxonomy, record **EXPECTED NEGATIVE ACCEPTANCE** (required rejected query), **EXPECTED RED** (single deliberately failing old-code test), **IMPLEMENTATION DEFECT**, **PRE-EXISTING REPRODUCED**, **FLAKY/NONDETERMINISTIC PROVEN**, **EXTERNAL BLOCKER**, or **UNCLASSIFIED / DECISION REQUIRED** with the exact evidence. A failure observed at B is baseline evidence, not a waiver; green repeat does not erase original failure. Preserve all attempts, no unbounded diagnostics. D23 is not a new exception; routine lossless whitespace repair of new unfrozen wrappers is authorized, frozen diagnostic changes need human decision. Escalation includes precise symbol/fixture/command, expected vs actual, affected invariants/gates, why independent work can or cannot continue, smallest requested decision, safe alternatives and recommendation. Continue no task that depends on an unresolved contradiction.

## 12. Acceptance gates, documentation and delivery

### 12.1 Objective gate ledger

| Gate | Required evidence before PASS |
| --- | --- |
| G0 source admission | Merged PR #131 and exact B/source/branch, no shadow inputs, baseline inventories and no unexplained source drift |
| G1 correctness preparation | §6 ten actual answers, §3 algebra/precedence, exact planned source anchor inventory and decision log; source agrees, no unresolved design choice |
| G2 implementation/isolation | Exact P1–P5 allowed edits and checker results, no additional producer/consumer, no public/codec/config/runtime telemetry or new M allocation, layout U12 within approved bound, unchanged algorithms/charges, all protected paths clean |
| G3 deferred score acceptance | RED observed exactly 40 vs 3; green identical U01; S01 24 rows, S02 108 + edge cases; U02/U07/U08/U11 count/score/order/identity/eligibility, actual BM25 count K (not a predicted count), U12 finalizer guards |
| G4 failure and accounting | P01 six rows + same-budget recovery + wrong cert, U03 shared stats 17 + competing cases, U04 all nine cases/repeats, U05 four native caps + recovery, U06 five actual B3 rows, U09 12 budget rows, U10 complete deterministic cancellation sweep, U13/U14 duplicates/MultiOne. Exact typed errors and complete response comparisons; no omitted cases |
| G5 real integration | Real `FsDirectory` I01 six combos, I02 pinned old/new/compact+reopen/paging, I03 exact public failures/retries; all 12 integration functions execute, no fake replacements |
| G6 regression and inventory | Original old exact sets 24/5/9 retained, broad old and new counts explained; 17 unit + 3 new integration, focused outputs + serial/8-thread/MSRV regressions, old C2 eager guards and all sibling retained suites, no new ignores |
| G7 local repository QA | All §10.3 actual commands pass on TESTED, both coverage >=85%, relevant changed behavior covered, final committed B...H, TESTED..H, staged/worktree whitespace exit0; no unresolved failure or waiver |
| G8 hosted regression | Five ordinary CI jobs success and actual logs real bodies on applicable H/base, source lineage verified; no fake or stale run |
| G9 documentation/evidence/delivery | Plan verbatim SHA, source audit and immutable red/tested identities, every receipt and manifest hash verified, complete actual case outputs and precise counts, append-only status, current live PR description verified, final H/metadata/CI/range facts delivered inline or actual attachment, no benchmark claim |
| G10 independent review and maintainer acceptance | OPEN. Agent never sets PASS or merges; independently reviewed/maintainer accepts and merges in separate decision. |

Dispositions derive from actual gates, not agent's desire to finish. Use exactly one of:

- `PERF06_C3_READY_FOR_INDEPENDENT_REVIEW` iff G0–G9 PASS, G10 OPEN.
- `PERF06_C3_IMPLEMENTED_LOCAL_QA_PASS_CI_PENDING` iff implementation, local acceptance and evidence pass but required final hosted run is pending; G8 pending, no acceptance claim. G9 may identify the incomplete hosted link as pending rather than claiming completion of G0–G9.
- `PERF06_C3_IMPLEMENTED_VERIFICATION_BLOCKED` iff code implementation complete but any required gate blocked/failed/unverified, including missing receipt, local/CI infrastructure, unresolved whitespace or regression. Do not report DONE.
- `PERF06_C3_IMPLEMENTATION_INCOMPLETE` iff required code/test design or implementation incomplete; provide exact done/remaining work and blockers. If a plan/source contradiction requires an amendment, include `STOP_PLAN_AMENDMENT_REQUIRED` as reason, not an alternative positive disposition.

If a final artifact is blocked solely on an external gate, deliver partial evidence truthfully; no automatic retry, merge, C4 or acceptance. A positive handoff is not a performance-qualified baseline.

### 12.2 Documentation (only authorized appends)

Append a dated implementation note to `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md` explaining the exact conservative bounds, request-local score token, unchanged C2 eligibility, same scorer/accumulator, typed integer freq in bounded heap, score only final returned hits not K+1; no other fallible candidate work deferred. Explain fallback/invalid stats ordering, no public/format/accounting change, test coverage classes and physical heap size tradeoff with actual U12 output. Do not modify the normative C1 contract or call C4 complete. Link plan/report.

Append dated rows/sections to `docs/PERF_OPTIMIZATION_ROADMAP.md` and `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`: record C2 #131 merged at B, preserving the earlier historical pre-merge G10/whitespace wording as contemporaneous; C3 actual branch/head/status/plan/report, exact proof boundary, tests and coverage status, no performance sample. C4 is next, not started; C4 owns final integrated incremental A+B→C warm qualification (and separately cumulative series reporting). Roadmap may not mark C3 DONE or baseline promoted before G10. No update to benchmark methodology or old plans/receipts. No AGENTS change. The implementation report is a snapshot as of its docs commit; the final PR body and terminal handoff supply final actual H and CI to avoid self-reference.

### 12.3 Suggested PR body (fill verified values only)

```markdown
## PERF-06-C3 — Certified deferred BM25 for strict-term ordinal Top-K

From merged C2 (#131). A request-wide proof over immutable prepared BM25
statistics and positive decoded frequencies permits the existing strict ordinal
route to keep raw tf in its K+1 heap and compute scores only for final returned
hits. The same scorer, full posting validation, exact count, B1/B2/B3 candidate
and duplicate semantics, logical charges, cursor and selected projection remain.
Unproven statistics keep eager C2; all originally ineligible shapes keep Legacy.
Competitive provisional key/sort allocations remain at their accepted fallible
boundaries. No new storage format, public API or benchmark execution.

Plan: [actual branch-pinned plan link]
Report and evidence: [actual link]
Tested source / final head / CI run: [actual identities and run status]
Acceptance: [actual gate ledger and disposition]
Coverage: [actual both measured scope percentages]
Known limitations: [actual proof/fallback/layout, any blocker]
G10 independent review/maintainer acceptance OPEN; C4 owns warm qualification.
```

Replace bracketed fields with verified values or explicit BLOCKED/PENDING; never assert unknown counts. Use `gh pr view <actual number> --json number,url,state,isDraft,headRefName,headRefOid,baseRefName,mergeStateStatus,body` and verify read-back matches intended body and last remote head. Compare CI to actual H and base; no fabricated run number. Do not edit PR #131. Don't mark roadmap status with stale preflight data.

### 12.4 Final report format (inline terminal facts mandatory)

Return the following exact fields (actual values, no placeholder `see report` for required identity). The Markdown execution report contains the full per-command and case evidence; terminal block must include enough facts to independently check the final remote state without another commit or missing attachment. Include the full GitHub links to evidence/PR, and deliver actual accessible artifacts if outside repo. Do not present mere `/tmp` path as proof of attachment. At least:

```text
REPO / BRANCH / ACTUAL PR / URL / DRAFT / MERGED
BASE_B / RED / TESTED / TESTED_TREE / DOCS_FINAL / REMOTE_H / origin/main
PLAN_SHA256 / RECORDER_SHA256 / RED_PATCH_SHA256 / TESTED_DIFF_SHA256
MANIFEST_SHA256 / SOURCE_AUDIT_SHA256 / FILE_COUNT / RECEIPT_COUNT
DISPOSITION
G0..G10 status with exact evidence and blockers
RED exit/selected count/failure assertion/observed 40, expected 3; GREEN result
S01/S02/P01/U01..U14/I01..I03 outcomes and executed row totals
Actual C3 scores vs M/K, ordered final identity cases, fallback and failure witnesses
Old and new exact test inventories; actual test launches and summary counts
Per-command local QA table with exit/source and counts; coverage TOTAL line(s)
CI run URL/id, event, H, merge checkout SHA, base SHA, job names/conclusions
Verified real RustFS executed test bodies (not just green status)
B...TESTED, B...H, TESTED..H, working-tree and staged whitespace command exits/output
TESTED..H changed paths; exact protected source/build equality and source audit result
Remote head verification command/output and PR body read-back verification
Applied rule ledger; unresolved failures and classifications; explicit exceptions (NONE unless actual human approval)
No performance benchmark / profiler / C4 / merge; G10 OPEN
```

For final whitespace and remote check evidence, record exact command/UTC/commit and actual exit/output, not implied by clean status. On success empty outputs may be reported as exactly empty; on failure deliver actual lossless bytes, exact path/diagnostic counts. Report `git diff --name-only TESTED..H` and full list or accessible committed list, distinguish intermediate docs commit from H, no ambiguous FINAL identity. Use `git ls-remote --heads origin dev/perf06-c3` and `git rev-parse HEAD` plus PR `headRefOid` equality. If no PR access, say BLOCKED with actual error. Independent review is not a coding-agent gate it can close.

### 12.5 Reviewer checklist and next dependency

- [ ] Fresh merged main, branch identity and exact approved contract/source used.
- [ ] Uniform safety proof, no hidden score errors and no score-dependent order; actual same-query eager and Legacy comparisons.
- [ ] Entire posting stream, native segment order, logical charge/admission/error order, null/MultiOne, key validation, duplicate semantics, cancellation checkpoints retained.
- [ ] Raw frequency inline follows physical identity; actual K scores, no sentinel or evicted scores; legacy path and representation bound audited.
- [ ] Exact deterministic red proof and all test/row names actually executed; all real filesystem mutation/PIT/reopen and applicable RustFS regressions.
- [ ] Both toolchains/feature regimes, coverage gates, CI, full committed-range whitespace and source freeze at same tested source.
- [ ] No fabricated evidence, no unexplained missing receipt, no stale PR body or terminal pointer; historical bytes preserved.
- [ ] No public contract/storage/persistence/API/benchmark framework changes or unrelated optimization, no C4 run or performance claim; G10 still maintainer-owned.

Sequence: accepted B4 → C1 contract (merged) → C2 executor (merged #131) → **C3 certified deferred scoring** (this PR, correctness-first) → C4 integrated correctness/performance qualification on an independently accepted C3 baseline. C4 must test absent/rare guard lanes as well as medium/common targets at 10K/100K and K=10/100 using the accepted warm methodology and separately attribute the incremental C gain over accepted A+B. This plan does not select or modify the C4 benchmark policy, authorize a campaign, or promise a speedup. It does not implement general early termination, score-free relevance ranking, WAND, new heap/column format, vector/Boolean optimization, remote topology or anything else beyond the bounded mechanism above.
