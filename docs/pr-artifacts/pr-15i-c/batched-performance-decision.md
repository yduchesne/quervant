# PR 15I-C batched-noise follow-up — performance decision

**Decision: `15IC_PERFORMANCE_REJECTED_SAFE_ROLLBACK`**

The batched diagnostic passed its new prospective A/A stability gate and the A/G
control was neutral, so the outside-generic dispatch candidate was implemented and
measured under the **unchanged, unbatched** frozen PR15I-C contract. That contract
failed on the low-match lanes, so the production change was rolled back additively
and every artefact preserved.

## 1. Evidence layers (never blended)

| Layer | Identity | Result |
|---|---|---|
| Batched A/A (4 campaigns, same executable) | `target/pr15i-c/batched-noise-v1/aa-0N` | **PASS** — aggregate medians 0.9943–1.0089, all four campaign medians in [0.94, 1.06], none outside [0.85, 1.15], every short-lane slot median ≥ 1 ms, zero block outliers > 1.15 |
| Batched A/G (4 campaigns, pinned historical G) | `…/ag-0N` | `15IC_AG_DIAGNOSTIC_NEUTRAL` — aggregates 0.9834–1.0006, 4/4 runs ≤ 1.05 per lane; observation only |
| Frozen unbatched final campaign | `target/pr15i-c/campaigns/outside-dispatch-batched-01` | **C-P06/07/08 PASS, C-P09 FAIL** |

## 2. Final frozen campaign (nine lanes, 16 slots, 2 880 samples)

A `6f6463cb…`; B `92a741876f6f6823d9d1792fc391dbb1bbecceb0`
(`B_IMPLEMENTATION_SHA` = `B_MEASURED_SHA`); verifier:
`target/pr15i-c/reviews/paired-01-verification.json` is historical — this
campaign's receipt is `target/pr15i-c/reviews/outside-dispatch-batched-01-verification.json`.

| Lane | Block ratios | Median | Gate |
|---|---|---|---|
| 10K absent/k100 | 1.3966, 1.4304, 1.3302, 1.6142 | **1.4135** | FAIL |
| 10K rare/k100 | 1.3058, 1.3765, 1.3802, 1.2717 | **1.3411** | FAIL |
| 10K medium/k100 | 0.9112, 0.9452, 0.9418, 0.8986 | 0.9265 | PASS |
| 10K common/k100 | 0.8944, 0.8804, 0.8903, 0.8880 | **0.8892** | PASS |
| 100K absent/k100 | 1.6765, 1.7123, 1.7395, 1.7491 | **1.7259** | FAIL |
| 100K rare/k100 | 1.6659, 1.6198, 1.6479, 1.7988 | **1.6569** | FAIL |
| 100K medium/k100 | 0.8871, 0.9149, 0.9169, 0.8976 | 0.9062 | PASS |
| 100K common/k100 | 0.8618, 0.8612, 0.8649, 0.8612 | **0.8615** | PASS |
| 100K common/k10 | 0.7854, 0.7870, 0.7866, 0.7830 | **0.7860** | PASS |

All four blocks exceed the frozen 1.15 per-block ceiling on each absent/rare
lane. The three primary lanes pass comfortably (10.8–21.4% faster), matching the
historical candidate's gains exactly, and the medium lanes also improve.

## 3. Why this is a rejection and not a diagnostic result

* The frozen contract is numerical, unbatched and unchanged: three primary lanes
  `median ≤ 0.90` with every block `≤ 1.15`; six non-primary lanes
  `median ≤ 1.05` with every block `≤ 1.15` (`NC-D67`/`NC-D68`).
* The batched diagnostic is explicitly *not* a substitute: its A/A band
  `[0.97, 1.03]` and observational per-block rule cannot waive `C-P09`
  (`NC-D97`).
* The evidence is valid: source ancestry, allowlisted scope, 12 byte-identical
  index rebuilds with the LZ4 STORED v2 sentinel, frozen corpus/oracle, clear
  contention before and after all 16 slots, and controller/verifier agreement.

## 4. What this adds to the historical picture

Three independent measurement regimes now agree that the exact-term physical
operator wins on common/medium queries and loses badly on absent/rare ones when
measured per request:

| Regime | Common lanes | Absent/rare lanes |
|---|---|---|
| Historical in-generic candidate (`paired-01`, unbatched) | 0.85–0.89 | 1.26–1.72 |
| Outside-dispatch candidate (this campaign, unbatched) | 0.86–0.89 | 1.34–1.73 |
| Batched A/G control of the generic boundary (diagnostic) | ≈0.98–1.00 | ≈0.98–1.00 |

So moving the dispatch out of `collect_mixed` did **not** remove the low-match
regression; the regression is not caused by an eligibility branch *inside*
`collect_mixed`. It follows the presence of the specialization in the binary and
shows up whenever the query is timed as an individual request. The batched
study's neutrality for the *generic-boundary-only* control is therefore not
evidence about this architecture, which is exactly why the plan kept the two
layers separate.

## 5. Rollback performed

* Production restored from merged `BASE`: `search/unified.rs`,
  `search/execute.rs`, `search/score.rs`, `search/diagnostics.rs`,
  `search/mod.rs`, `crates/quervant-core/Cargo.toml`.
* `crates/quervant-core/tests/pr15i_c_physical.rs` removed (its premise, an
  active fast path, no longer exists).
* Retained: the batched protocol/patcher/controller/verifier and their 92 tests,
  the eight sealed campaigns with 8 receipts plus the aggregate receipt, the
  frozen final campaign with its receipt, and every prior negative artefact.
* Protected-path diff versus merged base is empty after the rollback commit.

## 6. Not delivered

No PR 15I-C capability, roadmap status or performance claim. The architecture
proposal remains unimplemented and the frozen acceptance contract remains
unsatisfied by every candidate measured so far.
