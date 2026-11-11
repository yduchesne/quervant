# PR 15I-D2-A — execution status

**Status: `D2A_SCORE_COST_LOW_PRIORITY` — complete measurement deliverable, no
optimization delivered.**

| Item | Value |
|---|---|
| BASE | `9429dce99827f25766a92c1fbded8f78a0b168f1` |
| Final tooling freeze T0 | `747ceb2464425f2392829c5165decf4c697cf34b` |
| Evidence/test commit | `9e1641dcee77ac0e5876a427de1f8e56c36a5ab0` |
| Qualified A/A | `d2a-base-aa-01` |
| Qualified paired campaigns | `d2a-unbatched-01`, `d2a-unbatched-02` |
| Independent aggregate | `D2A_SCORE_COST_LOW_PRIORITY` |
| Semantic status | `D2_B_NOT_AUTHORIZED_BY_D2A` |
| Production source change | None |
| D2-B implementation | None |

## What was delivered

1. An insertion-only, independently reversible scratch diagnostic controller
   (`benchmarks/pr15i_d2a/`) with a frozen protocol and T0 tooling manifest.
2. A three-arm A/Q/P recorder with the ten inherited D0 stages, three nested
   score stages and six checked counters.
3. A test-only real `FsDirectory` scoring-contract suite (SC-01…SC-15, 15
   passing tests; SC-16 cites existing private scorer tests).
4. One qualified A/A control and two qualified independent A/Q/P campaigns,
   with exclusive seals, independent verification, archive sidecars and
   round-trip re-verification.
5. A closed-form §11 decision and a source-backed semantic feasibility report.

## What was not delivered

- No late-scoring implementation, alternate scorer, eligibility fast path or
  shadow executor.
- No BM25 equation, score value, `ProjectedHit`, search API, segment format,
  PR15D adapter, corpus, oracle, lockfile, CI or threshold change.
- No D2-B authorization. The semantic report identifies unresolved
  non-winner error/budget/cancellation parity; the quantitative verdict is
  independently low priority.

## Attempts and retention

| Attempt | Outcome | Disposition |
|---|---|---|
| A/A under T0 `bb3a6e5` | Qualified, then series superseded by the metadata defect | Archived under `superseded/` |
| Paired 01 under T0 `2774c87` | Rejected by `verify.py` (Q fingerprint metadata) | Preserved under `superseded/paired/` |
| A/A attempt 1 under final T0 | One 10K absent block `1.269948 > 1.25` | Preserved, excluded; one retry used |
| Final A/A, paired 01, paired 02 | All qualified | Archived canonically |

No accepted sample was overwritten, resumed or selectively rerun. The final
A/A retry is the only preauthorized retry, and it was preceded by documented
quiescence.

## Remaining external gates

- Hosted CI has **not** been run for this local branch.
- Independent human review has **not** occurred.
- No PR has been created/pushed; local commit `9e1641d` is the candidate tree.
- Real RustFS end-to-end scoring attribution is not required by this
  measurement-only PR and was not run locally; the existing RustFS CI jobs are
  separate.

## Final decision rationale

The score-accumulation stage consumes about 0.66 ms on 100K medium/K100 and
2.63 ms on 100K common/K100/K10. Only common/K10 crosses both the 2 ms and 8%
thresholds in both campaigns, so at most one of the three primary lanes
qualifies; the gate requires two. The predeclared result is therefore
`D2A_SCORE_COST_LOW_PRIORITY`. Qualified negative evidence is the intended
deliverable and requires no threshold change.
