# PR 15I-C — Performance decision

**Decision: `15IC_PERFORMANCE_REJECTED_SAFE_ROLLBACK`**

The candidate passed every correctness, budget-parity, source and provenance gate
that was executed, and it *improved* all three primary lanes. It nevertheless fails
the frozen non-primary gate `C-P09`, so the production change was rolled back
additively and every measurement artefact preserved.

## 1. Campaign

| Item | Value |
|---|---|
| Campaign | `target/pr15i-c/campaigns/paired-01` |
| Protocol | `pr15i-c-physical-v1` (SHA-256 pinned in `raw/manifest.json`) |
| A | `f70cde62e709383d82693ad548a8c69c7f772bef` (merged PR 15I-B, LZ4 STORED v2) |
| B | `395e05c629c5929f0164764c51c5a1b60b8acd1c` |
| Schedule | 4 balanced blocks, `ABBA / BAAB / BAAB / ABBA`, 16 slots |
| Samples | 9 lanes × 5 warmups × 20 measured × 16 slots = 720 warmups, 2 880 samples |
| Contention | clear before and after every slot |
| Filesystem | native `ext4` |
| Index parity | 12 remeasured builds, byte-identical A/B layout and segment digests |
| Score parity | identical keys, order and `to_bits` on all nine lanes |
| Independent verifier | `target/pr15i-c/reviews/paired-01-verification.json` |

## 2. Per-lane results (median of four block ratios, B/A)

| Lane | Gate | Block ratios | Median | Result |
|---|---|---|---|---|
| 10K absent/k100 | non-primary ≤1.05 | 1.3976, 1.3589, 1.4500, 1.1990 | **1.3783** | FAIL |
| 10K rare/k100 | non-primary ≤1.05 | 1.0747, 1.2047, 1.3378, 1.3104 | **1.2575** | FAIL |
| 10K medium/k100 | non-primary ≤1.05 | 0.9206, 0.9286, 0.9131, 0.9525 | 0.9246 | PASS |
| 10K common/k100 | primary ≤0.90 | 0.8789, 0.8915, 0.8992, 0.8924 | **0.8920** | PASS |
| 100K absent/k100 | non-primary ≤1.05 | 1.7245, 1.7142, 1.7089, 1.8299 | **1.7193** | FAIL |
| 100K rare/k100 | non-primary ≤1.05 | 1.6827, 1.7210, 1.7114, 1.7553 | **1.7162** | FAIL |
| 100K medium/k100 | non-primary ≤1.05 | 0.9155, 0.9320, 0.9087, 0.9133 | 0.9144 | PASS |
| 100K common/k100 | primary ≤0.90 | 0.8560, 0.8607, 0.8351, 0.8393 | **0.8476** | PASS |
| 100K common/k10 | primary ≤0.90 | 0.7913, 0.7851, 0.7820, 0.7858 | **0.7854** | PASS |

Every per-block ratio on every lane is below the 1.15 per-block ceiling, so the
failure is a stable median effect, not one distorted block.

Absolute tails (median of the 16 per-slot values):

| Lane | A p95 | B p95 | A p99 | B p99 |
|---|---|---|---|---|
| 100K common/k100 | 50.07 ms | 42.38 ms | 50.53 ms | 42.72 ms |
| 100K common/k10 | 38.08 ms | 29.80 ms | 38.64 ms | 30.29 ms |
| 10K common/k100 | 4.71 ms | 4.21 ms | 4.78 ms | 4.29 ms |
| 100K medium/k100 | 21.04 ms | 19.08 ms | 21.39 ms | 19.90 ms |
| 100K absent/k100 | 0.313 ms | 0.510 ms | 0.331 ms | 0.541 ms |
| 100K rare/k100 | 0.319 ms | 0.560 ms | 0.343 ms | 0.582 ms |

The qualified result would have been a 10.8–21.5% latency reduction and an
8.7–14.4% p99 reduction on the primary common lanes.

## 3. Why the rejection stands

* The gate is frozen and was not retuned after seeing data.
* Four of six non-primary lanes exceed the 1.05 median ceiling by a wide margin
  (1.26–1.72×); no averaging or lane selection can legitimately absorb that.
* `C-P10..C-P12` (schedule, rebuild parity, source/binary proof) all pass, so this
  is a *valid* performance failure, not invalid evidence.
* `diagnostic-stage-profile.md` shows the regression is a codegen/inlining cliff in
  `collect_mixed` triggered by any data-dependent call before the segment loop —
  including a call whose body is effectively `false`. The operator's own work is
  what produces the common-lane win. That finding is preserved for a future,
  separately approved experiment; it is not a licence to restructure and re-run
  inside this PR.

## 4. Rollback performed

* Production paths restored from `BASE_CONTENT_SHA`
  (`search/unified.rs`, `search/execute.rs`, `search/diagnostics.rs`,
  `search/mod.rs`, `crates/quervant-core/Cargo.toml`).
* `crates/quervant-core/tests/pr15i_c_physical.rs` removed: its premise (an active
  fast path) no longer exists.
* Retained: this artefact directory, `benchmarks/pr15i_c/` controller, verifier,
  adversarial tests, stage/score probes, the sealed campaign and the independent
  verification receipt.
* Protected-path diff versus `BASE_CONTENT_SHA` is empty after the rollback commit;
  baseline LZ4 STORED `(0x000D, 1)` and mutation-state V3 `(0x000C, 1)` are
  unchanged.

## 5. Not delivered

No `15I-C` capability, roadmap status, format change or performance claim is
delivered. The 15I-C architecture remains a design proposal.
