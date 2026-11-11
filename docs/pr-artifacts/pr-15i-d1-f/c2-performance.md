# PR 15I-D1-F C2 — paired performance qualification

Frozen comparison `BASE -> C2`, tooling F0 `5eac5ca…`, measured C2
`b328b83…`. One A/A control and one paired campaign were run; the paired
campaign was structurally valid but failed the mandatory primary gate, so the
second campaign was not run (FDX-23).

## Campaign execution

| Campaign | Slots | Timed samples | Warmups | Clear probes | Index builds | Status |
|---|---:|---:|---:|---:|---:|---|
| `c2-base-aa-01` (A/A control) | 16 | 2,880 | 720 | 32 | 2 | `CONTROL_QUALIFIED` |
| `c2-base-01` | 16 | 2,880 | 720 | 32 | 4 | `CAMPAIGN_REJECTED` |
| `c2-base-02` | — | — | — | — | — | not run (stop rule) |

Every slot used 9 lanes × (5 warmups + 20 integer `engine_ns` samples), one
fresh pinned adapter process per `(arm, lane, slot)`, and two clear contention
probes. Both arms produced distinct source/binary identities and byte-identical
committed indexes with the LZ4 sentinels.

The A/A control (identical BASE binaries from two independent builds of the
same tree) qualified all nine lanes: every block ratio was inside
`[0.80, 1.25]` and every lower-median ratio inside `[0.85, 1.15]`
(100K common/K100 0.9545; 100K common/K10 0.9396; 10K common/K100 1.0149).
Drift PASS. An earlier attempt, built from two different worktrees, disclosed a
binary-path SHA discrepancy and was blocked by a single noisy 10K rare block
(1.51 > 1.50); it is preserved unarchived and was superseded by the one
authorized transient retry.

## c2-base-01 results

| Lane | Block d values (ns) | Lower median d (ns) | B/A median |
|---|---|---:|---:|
| 10K absent/K100 | +10,862 / +12,695 / -1,283 / +13,384 | +10,862 | 0.7521 |
| 10K rare/K100 | -4,767 / +16,913 / -18,700 / +2,018 | -4,767 | 0.9639 |
| 10K medium/K100 | +361,579 / +236,775 / +271,471 / +315,013 | +271,471 | 0.8258 |
| 10K common/K100 | -10,312 / -43,405 / -125,217 / +41,982 | -43,405 | 1.0025 |
| 100K absent/K100 | +3,392 / -412 / +17,233 / -5,913 | -412 | 0.9857 |
| 100K rare/K100 | +412 / -7,700 / -275 / +2,750 | -275 | 0.9983 |
| 100K medium/K100 | +4,274,055 / +3,469,586 / +3,397,628 / +2,976,556 | **+3,397,628** | 0.7996 |
| 100K common/K100 | -309,513 / -841,226 / -1,174,205 / -594,275 | **-841,226** | 1.0142 |
| 100K common/K10 | +2,611,724 / +1,711,693 / +1,570,665 / +1,008,425 | **+1,570,665** | 0.9465 |

| Gate | Result |
|---|---|
| FC2-P00 structural | PASS |
| FC2-P01 mandatory primary win | **FAIL** |
| FC2-P02 both common lanes guard | PASS |
| FC2-P03 medium/10K-common guard | PASS |
| FC2-P04 absent/rare neutrality | PASS |
| FC2-P05 10K medium guard | PASS |
| FC2-P06 structural identity/index/oracle/archive | PASS |
| FC2-P07 both campaigns | not reached |

`FC2-P01` requires at least one of 100K common/K100 or 100K common/K10 to reach
a +2,000,000 ns lower median with at least 3/4 blocks nonnegative.
100K common/K10 produced a real but smaller win (+1,570,665 ns, all four blocks
positive); 100K common/K100 was consistently slower (-841,226 ns). The K100
result is not an outlier: all four blocks are negative. 100K medium/K100
improved strongly (+3,397,628 ns), but the frozen contract requires the common
primary win, so the campaign is `CAMPAIGN_REJECTED`.

Observed pattern (diagnostic only, not a new gate): the borrowed path avoids
allocation for losing candidates and helped 100K medium/K100 and K10, while
for the 50,000-candidate common/K100 lane the per-candidate re-validation and
offset lookup path did not beat the existing decoded-cache clone path. This
explanation is a hypothesis; the verdict rests only on the frozen gates.

## Verdict and disposition

`COMPARISON_PERFORMANCE_REJECTED`. Negative evidence is archived; C2 was
rolled back additively to exact BASE bytes (`051c319…`) and `c2-base-02` was
not run. No threshold was changed, no sample or slot was selected, and the
historical C1 rejection is unchanged.
