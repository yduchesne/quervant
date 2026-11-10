# PR 15I-C fixup — errata for the prior negative report

Additive corrections only. No sealed raw file, published report or receipt is
edited; the original documents and the `paired-01` campaign remain immutable
(`FX-D84`).

## E1 — "every per-block ratio below 1.15" was false

`docs/pr-artifacts/pr-15i-c/performance-decision.md` §2 said *"Every per-block
ratio on every lane is below the 1.15 per-block ceiling"*. That is incorrect.

Raw `target/pr15i-c/campaigns/paired-01/raw/measurements.json` records these
non-primary block ratios:

| Lane | Block ratios | Blocks above 1.15 |
|---|---|---|
| 10K absent/k100 | 1.3976, 1.3589, 1.4500, 1.1990 | 4 of 4 |
| 10K rare/k100 | 1.0747, 1.2047, 1.3378, 1.3104 | 3 of 4 |
| 100K absent/k100 | 1.7245, 1.7142, 1.7089, 1.8299 | 4 of 4 |
| 100K rare/k100 | 1.6827, 1.7210, 1.7114, 1.7553 | 4 of 4 |

So the historical candidate failed **both** the non-primary median ceiling and the
per-block ceiling on four lanes. The independent verifier's `C-P09 FAIL` and the
`15IC_PERFORMANCE_REJECTED_SAFE_ROLLBACK` decision remain correct; only the prose
claim of per-block compliance was wrong.

## E2 — `live_work` / `leaf_decode` mis-attribution in the stage-profile prose

`docs/pr-artifacts/pr-15i-c/diagnostic-stage-profile.md` §2 prose said the
"`live_work` scan then costs 8.3 ms". The table above that sentence reports
`leaf_decode_ns = 8,327,826` and `live_work_ns = 344,405` for
100K common/k100. The 8.3 ms belongs to **`leaf_decode_ns`**; `live_work_ns` is
0.34 ms. Tables and raw counters were correct and are not changed.

## E3 — causal wording

The prior diagnosis should be read as *"consistent with a compiler-layout /
inlining effect; controlled code changes strongly suggest this cause"*, not as
proven machine-level causation. The fixup's own machine-code capture
(`fixup-codegen-evidence.md`) supplies the missing symbol-level fact (the merged
baseline's generic executor is inlined into `execute_unified`), but `perf` counters
are unavailable on this host, so no microarchitectural claim is made.

## E4 — baseline stage profile never existed

The original arm A never contained the non-default `pr15ic-probe` feature, so no
baseline stage profile exists and none is claimed. The fixup's A/G comparison uses
source-neutral release binaries and symbol/disassembly capture instead.

## E5 — F0 harness defect in the fixup's first diagnostic attempt

`target/pr15i-c/layout-diagnostics/generic-boundary-01` is **not valid evidence**:
the controller wrote the control arm's build tree under `setup/build/B` while the
independent verifier resolves `setup/build/G`, so that run could never be
verified (`LV_BINARY`). It is preserved, untouched, as an invalid attempt. The
`generic-boundary-02` directory was created and blocked by a dirty worktree
before any sample was recorded. Valid, independently verified runs are
`generic-boundary-03` (PASS) and `generic-boundary-04` (FAIL).
