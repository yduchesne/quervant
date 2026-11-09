# PR 15I-C fixup — performance decision (F0 generic-boundary control)

**Decision: `15IC_GENERIC_BOUNDARY_REJECTED_SAFE_ROLLBACK`**

The generic out-of-line boundary (`#[inline(never)]` on
`UnifiedSearcher::collect_mixed`, the only production change in F0) did **not**
reliably satisfy the prescribed generic-neutrality gate. Because F0 is a hard
precondition for restoring the physical operator, no fast-path source was
restored and no nine-lane campaign was run. Production is restored byte-for-byte
to merged PR 15I-B.

## 1. What was measured

Seven frozen PR15D warm lanes, eight paired blocks
(`ABBA BAAB BAAB ABBA BAAB ABBA ABBA BAAB`), 5 warmups and 10 measured samples per
lane per slot: 32 slots, 224 lane records, 1 120 warmups, 2 240 timed samples.
Arms: A = `6f6463cb…` (merged PR 15I-B), G = `50b56e9…` (+`#[inline(never)]`).
Gate (frozen in the plan, no slack): each lane `median B/A <= 1.05` **and every one
of its eight blocks `<= 1.15`**.

## 2. Runs

| Run | Validity | Outcome |
|---|---|---|
| `generic-boundary-01` | **INVALID** — controller wrote the control build tree under `setup/build/B`; the verifier resolves `setup/build/G`, so the run can never be verified (`LV_BINARY`). Preserved untouched. | controller said FAIL (10K rare block 5 = 1.1655) |
| `generic-boundary-02` | **BLOCKED before measurement** — prior run's regenerated adapter lockfile made the shared worktree dirty | no samples |
| `generic-boundary-03` | **VALID** (independently verified, receipt `reports/layout-generic-boundary-03.json`) | PASS — all 7 medians ≤0.9984, max block 1.0853 |
| `generic-boundary-04` | **VALID** (independently verified, receipt `layout-generic-boundary-04.json`) | **FAIL** — see below |

`-03` and `-04` were both run with the committed tooling
(`layout_diag.py` at the tooling commit `7fbea7f`); `-04` used the exact same
controller bytes and produced its own sealed raw and receipt.

## 3. `generic-boundary-04` (valid FAIL)

| Lane | Block ratios (8) | Median | Gate |
|---|---|---|---|
| 10K absent/k100 | 0.9238, 1.0161, 0.8153, 0.7524, 1.0802, 1.0189, 0.8751, 0.9080 | 0.9159 | PASS |
| 10K rare/k100 | 1.0072, 0.9667, 0.9732, 0.9745, 1.0052, 0.9430, 1.0117, **1.2190** | 0.9899 | **FAIL** |
| 10K common/k100 | 0.9864, 0.9772, 1.0262, 0.9730, 0.9871, 1.0063, 0.9709, 0.9747 | 0.9818 | PASS |
| 100K absent/k100 | 0.9668, 1.0648, **1.2137**, 1.0358, 1.0276, 0.9842, 1.0022, 1.0178 | 1.0227 | **FAIL** |
| 100K rare/k100 | 0.9921, 1.0350, 1.0300, 0.9644, 0.9981, 0.9188, 0.9971, 1.0146 | 0.9976 | PASS |
| 100K common/k100 | 0.9819, 0.9786, 0.9635, 0.9955, 0.9983, 1.0047, 0.9896, 1.0073 | 0.9925 | PASS |
| 100K common/k10 | 1.0441, 0.9881, 0.9850, 1.0030, 0.9863, 1.0061, 0.9974, 0.9748 | 0.9927 | PASS |

Both failures are single outlying slot medians in an otherwise neutral block:

| Block | A slot medians | B slot medians | Block ratio |
|---|---|---|---|
| 10K rare, block 8 | 56 501, 49 000 ns | 50 501, **78 102** ns | 1.2190 |
| 100K absent, block 3 | 250 904, 247 504 ns | 252 904, **352 006** ns | 1.2137 |

Every lane median in every valid run is ≈1.0, and the two valid runs disagree on
which blocks fail. The failure is therefore *not* a systematic regression of the
boundary, but the frozen gate has no statistical slack: with one outlier slot in
64 per lane the run fails, and two of the three attempted runs (both of the two
verifiable ones) did fail at least one block.

## 4. Decision rule applied

`FX-D33` — a valid control exceeding `1.05` median or `1.15` block on any lane
requires the attribute to be rolled back and a **HARD STOP** on operator
restoration. The plan explicitly forbids retuning, re-running for a favourable
sample, or treating the common-lane neutrality as compensation. `FX-D27`
(invalid run from contention) does not apply: every slot's before/after
contention probe was `clear` and the independent verifier enforces that.

Consequences, executed:

* `15IC_GENERIC_BOUNDARY_REJECTED_SAFE_ROLLBACK`.
* F-03 (restore the exact C operator), F-04 (`FX-U/I/F` suites, score-bit/budget
  parity on the refactor) and F-05 (frozen nine-lane campaign) were **not
  executed**. No results for them are claimed anywhere.
* Production restored to merged PR 15I-B; the G attribute is gone.
* The historical negative candidate `paired-01` and its receipt stay immutable and
  are not re-used as evidence for this fixup.

## 5. Factual finding for a future plan (not a waiver)

Two facts are now established and should inform a future, separately approved
specification rather than be worked around here:

1. **Mechanism confirmed at symbol level.** In merged PR 15I-B the generic
   `collect_mixed` is inlined into `execute_unified`; the single
   `#[inline(never)]` attribute does take it out of line (2 644 instructions moved
   out, `execute_unified` shrinks from 3 993 to 1 898 instructions). So the
   historical regression's suspected inlining/layout sensitivity is real and
   measurable in machine code, even though `perf` counters are unavailable on this
   host (see `fixup-codegen-evidence.md`).
2. **The `1.15` per-block ceiling is under-powered on sub-millisecond lanes.**
   The failing lanes run at ~50–250 µs per query, where a single slot median can
   deviate by 1.5× from scheduling noise even with clear contention probes. A gate
   that combines a four-or-eight-block median with a hard per-block ceiling
   implicitly demands outlier-free measurement at that scale. Any future plan that
   needs to qualify a layout change on these lanes should specify the statistical
   property it actually wants *before* seeing data (for example a per-lane
   distribution-free bound with a stated false-rejection budget), and must still
   gate the authoritative nine-lane campaign on the frozen `C-P06..C-P09`
   thresholds.

Neither fact authorizes proceeding without a new accepted gate; both are recorded
so the next attempt does not have to rediscover them.
