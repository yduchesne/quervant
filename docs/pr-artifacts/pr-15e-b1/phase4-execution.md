# PR 15E Phase 4 — postings-driven single-term candidate enumeration

**Status: `P4_IMPLEMENTED` + `P4_QA_PASS` + `P4_PERF_MEASURED`** (phase acceptance is
reserved to the maintainer/reviewer; no Phase 5 work, no merge).

One optimization inside existing PR #83: for exactly one eligible unified query shape,
enumerate the already-decoded, effective-live postings instead of invoking the membership
predicate for every effective-live document. Scorer, plan, ledger, sort, pagination,
projection, aggregation, storage and formats are unchanged.

| Item | Value |
|---|---|
| Branch / PR | `dev/pr15e-b1-live-bitmap-postings-membership` / #83 |
| Phase 3 accepted source (arm A) | `df9b8565a4e47c5c66a7edeb566333643672e3fa` |
| Phase 4 production code SHA | `29e89e23fa0e15d559ed491c1f55e1d3b913cd02` |
| Runner `p4` stage SHA | `483cd55b4c0e6eed44daddacd47f0889cd35cd8b` |
| Measured arm B SHA | `483cd55b4c0e6eed44daddacd47f0889cd35cd8b` (Rust tree byte-identical to the code SHA: `git diff --name-only 29e89e2..483cd55 -- crates/` is empty) |

## 1. P0 preflight (observed)

| Check | Observation |
|---|---|
| Branch / HEAD at start | `dev/pr15e-b1-live-bitmap-postings-membership` at `b7a9def` (Phase 3 evidence head), clean tracked tree |
| `b7a9def` is an ancestor of HEAD | yes |
| `main` | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` (unchanged; PR #82 merge) |
| Phase 4 code already present | none (`postings_candidate_eligible`, `single_term_postings_eligible`, `P4_PREDECESSOR` all absent) |
| Seams inspected | `execute.rs::{evaluate_lexical_with, visit_lexical_membership_with, build_leaf_data, score_segment, LeafData, TermPostings}`; `unified.rs::{collect_mixed, single_term_postings_eligible}`; `unified_plan.rs::{UnifiedNode, UnifiedPlan}`; `plan.rs::CompiledLeaf`; `work.rs::MixedWorkMeter`; runner stage table |
| Baseline QA | `pr15e_b1` (11), `pr14_unified_mixed` (14), `pr14_projection` (14), workspace 2210 tests: PASS before edits |

## 2. Authorized eligibility rule (P4-AD-01) — as implemented

`single_term_postings_eligible(plan, request, aggregation)` in `search/unified.rs`,
computed **once per query** from the compiled plan:

1. `plan.root` is exactly `UnifiedNode::Lexical(0)`.
2. `plan.lexical_leaves.len() == 1` and it is `CompiledLeaf::Term` with `terms.len() == 1`
   (so a one-analyzed-term query with zero postings is still eligible).
3. `plan.typed_leaves.is_empty()` and `plan.positive_lexical == {0}`.
4. `aggregation.is_none()`.
5. `request.after.is_none()`.
6. Sorting is **not** restricted — the frozen PR15D adapter sorts by `doc_id ASC`.

Everything else takes the unmodified Phase 3 live-bitmap scan. There is no dynamic
string classification, no public API and no feature flag.

## 3. Mechanics (P4-AD-02) — as implemented

* One `evaluate_lexical_with`, one existing ledger/`build_leaf_data`/`score_segment`
  pipeline, and a new private `postings_candidate_eligible: bool` argument supplied only
  by the unified caller.
* After `build_leaf_data`, a runtime shape guard accepts only one `LeafData::Term` with
  exactly one `TermPostings` and `typed_examination == false`; anything else returns
  `CorruptIndex("single-term postings eligibility mismatch")` rather than enumerating a
  partial stream (D06 path, not triggered in practice).
* **Preserved logical work charge:** the number of `true` flags in the same
  effective-live bitmap is counted in ≤4096-position chunks (cancellation polled before,
  per chunk and after) and charged once with `meter.charge_lexical(live_count)`. The
  charge is never `postings.len()`; zero live documents charge nothing but still poll
  cancellation.
* Candidates are borrowed directly from `terms[0].postings` in the decoder's strictly
  ascending, effective-live-filtered order: no copy, re-sort, extra set or index seek.
  The original `is_match` callback is still invoked per candidate; matches feed the
  unchanged `matched` set, ledger reservation, `score_segment` and response pipeline.
* The legacy loop is retained verbatim for every ineligible shape; `work.rs`,
  `visit_lexical_membership_with`, scoring, memory and batch accounting are untouched.

## 4. Correctness evidence

Unit/in-crate (`search::unified::phase4_tests`, 8 tests): eligibility matrix
(Boolean/negation/phrase/prefix/glob/regex/fuzzy/typed/two-analyzed-term/aggregation);
candidate-visitation witness (1 matching posting ⇒ **1** predicate call vs **1000** in the
ineligible twin; absent term ⇒ **0**); fixture-exact results and totals for top-K
1/10/100; work-charge parity with the ineligible twin plus exact/one-below boundaries;
cancellation during bitmap counting (0 and 1 polls); zero-live and 4096/4097 boundary
bitmaps; cursor fallback (legacy scan); and the frozen adapter's exact query shape
(Keyword `key`, `doc_id ASC` sort, field projection) proven eligible with exactly one
candidate. Negative controls confirmed in the same suite: `postings.len()` as the charge
would break the parity assertion, multi-analyzed-term leaves fall back, and no early
top-K stop is introduced (`total_hits` exact).

Integration (`tests/pr15e_b1.rs`, 2 new tests): exact-term queries across four segments
with five deletes and one upsert, sorted and unsorted, against the model-derived
expectation; and all fallback shapes (`And`/`Or`/`Not`/`Phrase`/`MatchAll`) against the
model. Existing acceptance suites (`pr14_*`, `pr07_*`, `pr09_*`, `m1`–`m5`, `pr13_*`,
Phase 3 selective-stored tests) run unchanged.

## 5. QA — actual results on the Phase 4 head (`483cd55`)

| Gate | Result |
|---|---|
| `cargo fmt --all -- --check` (stable + 1.85.0) | PASS |
| clippy `--workspace --all-targets` ± `--all-features`, stable + MSRV | PASS (4/4) |
| `cargo test --workspace --all-targets` (stable) | PASS — 2210 passed, 0 failed, 10 ignored |
| `… --all-features` (stable) | PASS — 2214 passed, 0 failed, 75 ignored |
| `cargo +1.85.0 test` (default / all-features) | PASS — 2210 / 2214 passed |
| `cargo llvm-cov --all-features --fail-under-lines 85` | PASS — **lines 92.52%** (85479 lines, 6398 missed), functions 88.07%, regions 91.99% |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compile only) |
| PR15D adapter tests (stable + MSRV, `--locked`) | PASS — 5 each |
| `python3 benchmarks/pr15e_b1/test_run_targeted.py` | PASS — 58 tests |
| PR15D harness + PR15E Python suites | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108/108 |
| `git diff --check` | PASS |
| PR15E real-adapter integration (`PR15E_RUN_REAL_INTEGRATION=1`) | PASS — recorded `source_sha=483cd55` |
| Real RustFS (26 invocations, podman + pinned digest `1803faef…`, exact CI env/commands) | PASS — s3 8, proxy 5, remote 3, oracle 1, oracle_geo 1, m1 1, m2 1, m3 3×1, m5 3×1, crash proxy 7, k0 5, k05 10×1 |
| Exact-head GitHub CI (`rust`/`msrv`/`rustfs`) | **`CI_BLOCKED_CREDENTIALS`** — token invalid, branch not pushed; no CI claim |

## 6. Triggered decision rules

| Rule | Trigger | Class | Action |
|---|---|---|---|
| D01 | Branch = PR #83, `b7a9def` ancestor, no unrelated edits | AR | Continued on the same branch; recorded SHAs |
| D03 | Compiled plan matches every AD-01 clause, incl. `doc_id ASC` sort | AR | Eligibility TRUE for the frozen adapter shape (test-proven) |
| D04/D05 | Any clause false; ≥2 analyzed terms | AR | FALSE → exact legacy scan (matrix + fallback tests) |
| D07 | Empty postings for an eligible query | AR | Full effective-live charge, zero candidates (witness 0) |
| D09 | Logical work cap | AR | One bulk `charge_lexical(live_count)`; parity with the ineligible twin proven |
| D10 | One-below work cap / batch overflow | AR | Existing `ResourceLimit`, no relaxation (tested) |
| D11 | Frozen adapter eligibility | AR | Proven eligible by an in-crate replica test; all nine lanes therefore exercise the new path |
| D13 | Cancellation during count/candidates | AR | `Cancelled` propagates; subsequent identical query succeeds |
| D19 | `python -m unittest` form | AR | Direct script invocation used and recorded |
| D20 | Architecture/roadmap docs | DC | Not updated; deferred until performance acceptance |
| D25 | No new idle confirmation supplied | AR | Maintainer's Phase 4 instruction to assume idle used as authorization for `--idle-confirmed`; provenance recorded; real before/after probes still enforced (54/54 `clear`) |
| D26/D27 | Primary lane / control regressions | AR | Primary `B_FASTER`; no lane `A_FASTER`; INCONCLUSIVE controls disclosed (see qualification doc) |
| D28 | Primary `B_FASTER`, no control `A_FASTER` | AR | `P4_PERF_MEASURED` published; stopped before Phase 5 |
| D29 | GitHub credentials missing | DC | Local commits kept; `CI_BLOCKED_CREDENTIALS` reported; no CI PASS claim |
| D30 | Real RustFS | AR | Ran locally under podman with the pinned image; disclosed |

## 7. Performance (summary; details in `phase4-qualification.md`)

Primary `n100000/rare/k100`: 32,853,907 ns → 32,151,619 ns (ratio 0.979; paired
0.986 / 0.995 / 0.948) = **B_FASTER**. Zero-hit lanes improve most
(100K absent 0.628, 10K absent 0.706) because the scan no longer calls the predicate for
documents that cannot match. 100K medium 0.939 = `B_FASTER`; the two `rare` top-K/10K lanes
and all `common` lanes are `INCONCLUSIVE` (sign-inconsistent, ≈1.0); **no lane is
`A_FASTER`**.

## 8. Recorded variances

The Phase 4 unit tests live in the existing `unified.rs` `#[cfg(test)] mod phase4_tests`
rather than in `execute.rs` or a new integration file: the mandated predicate-call witness
requires in-crate access, and the real index fixtures every unified test uses live there.
It is a test-only module in an allowed production file, with no public or benchmark-build
surface. Documented in `phase4-design-and-decisions.md` §3.

## 9. Residual risks and limits

* The benefit is largest when the eligible term matches few or no documents; high-selectivity
  lanes are dominated by scoring/hit handling that this phase deliberately does not change.
* Only the fixed eligible shape is optimized; Boolean, phrase, multi-term, typed, mixed,
  aggregation, cursor and mutation-selection paths keep the legacy scan by design.
* The logical work charge is intentionally unchanged, so a query rejected before for work
  reasons is still rejected — no admissibility change.
* Wall-clock only, single host, synthetic exact-term `FsDirectory` workload, in-process
  adapter samples (JSON transport included).
* Upstream PR15E-A profiling remains `PENDING_REVIEW` under the recorded maintainer waiver;
  no G11 PASS is claimed.
