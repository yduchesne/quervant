# PR 15I-D3-B-F1.2 — execution status

**Disposition: `D3BF12_PERFORMANCE_REJECTED_SAFE_ROLLBACK`.**

| Item | State |
|---|---|
| Branch | `dev/pr15i-d3b-retained-key-prefilter` |
| BASE / candidate | `39dbd9f5…` / `48d9abf3…` |
| Historical T0 / T1 / T2 | `155ebafa…` / `ac45c23f…` / `63b30a0b…` (all untouched) |
| F1.2 T3 tooling | `c86c3b1554cadbc11deaedf4de4f4d7247e1467c` |
| F1.2 protocol / manifest | `3946c1ca…` / `35f79751…` |
| Synthetic rehearsal | `SYNTHETIC_REHEARSAL_ONLY` PASS, 16/16 expected cases, publish guard PASS |
| Control 01 | `CONTROL_QUALIFIED`, independent verifier PASS, archived `935a4d87…` |
| Control 02 | NOT_RUN |
| Paired 01 | `QUALIFIED_REJECTED`, independent verifier PASS, drift/readiness/structure PASS, P03 FAIL, archived `9e1e59b6…` |
| Paired 02 / 03 | NOT_RUN (performance rejection is terminal) |
| Structural replacements used | 0 |
| Two qualified campaigns | NONE |
| Series P08 | `COMPARISON_PERFORMANCE_REJECTED` / FAIL |
| Production diff | `ADDITIVE_ROLLBACK` to BASE `bb7a1035…` (commit `5d3bf1f7…`) |
| Stable / MSRV QA | PASS — 2,464 all-targets and 2,468 all-feature tests each |
| Coverage | 92.68% lines |
| Python QA | F1.2 193, F1.1 143, F1 95, D3-B 61, PR15D 83 (3 skipped) |
| RustFS | `RUSTFS_HARNESS_PASS`; real production adapter m1/m2 tests PASS; D3-B `i12` query test not counted (test-side stale-view assertion) |
| Hosted CI | `CI_PENDING` |
| Independent review | `REVIEW_PENDING` |
| PR | `PR_NOT_CREATED` (SSH push only) |

## What was executed

1. Reconciled the pinned BASE/candidate and T0/T1/T2 identities, preserved the
   user's unrelated `disk-cleanup.sh` edit, and confirmed the two F1.1 defects
   were already repaired.
2. Created the isolated F1.2 tooling, added the frozen nine-key protocol delta,
   the non-query 5 s + 6 × 1 s `/proc/stat` readiness gate, the bounded
   three-attempt drift-only succession machine, sealed readiness/succession
   evidence, and 48+30+20 targeted tests.
3. Ran a full synthetic external-verifier rehearsal on transformed copies of the
   F1.1 control and blocked paired evidence, including positive, replacement,
   rejected and blocked series plus readiness/succession/seal negatives. Seven
   pre-T3 harness defects were found and corrected in the new namespace; all
   rounds are preserved. T3 was frozen only after the complete rehearsal passed.
4. Ran the fresh official A/A control: byte-identical BASE builds, `READY`
   host, 2,880 samples, 32 clear probes, zero drift, all nine A/A lanes in
   bounds. Independently verified and archived.
5. Ran paired campaign 01: fully structurally qualified and independently
   verified, with large 100K common/K100 (+9,760,624 ns) and medium/K100
   (+2,389,981 ns) improvements, but 100K common/K10 missed the frozen median
   floor by 19,627 ns (−519,627 ns vs −500,000; B/A 1.014986; all blocks within
   the block floor). Per the frozen rules this is a performance rejection.
6. Archived the negative evidence, stopped before campaign 02, restored
   `unified.rs` to the exact BASE blob in an additive commit, and reran all
   stable/MSRV/coverage/Python/RustFS QA on the final rollback tree.

## Next human decision

Review/CI/release decisions only. Whether to investigate the K10 regression in a
separate optimization PR (new source and protocol) or abandon the prefilter is a
human architectural decision; no further measurement is authorized here.
