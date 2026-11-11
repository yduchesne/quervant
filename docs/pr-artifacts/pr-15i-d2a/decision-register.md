# PR 15I-D2-A — decision register

| ID | Trigger observed | Category | Authorized action taken | Prohibited alternative avoided | Evidence |
|---|---|---|---|---|---|
| DA-01 | `origin/main` = `9429dce` contains the merged D1-F closeout and C2 revert | AUTO-RESOLVE | Pinned `9429dce`; verified production source matches the audited blobs | Using the rejected C1/C2 candidate or inventing a merge | `preflight.md` |
| DA-03 | Required control-flow anchors are unique in BASE | AUTO-RESOLVE | Proceeded with insertion-only patch after exact anchor counts | Regex/fuzzy anchor matching | `source-proof.md`, `test_patch.py` |
| DA-05 | PR15D adapter builds with `--locked` | AUTO-RESOLVE | Used the frozen lockfile unchanged | Updating the lockfile for convenience | preflight build log |
| DA-07 | D0 materializer pins `7237bce`, not BASE | AUTO-RESOLVE | Created independent `patch_source.py`/`source_proof.py`; D0 unchanged | Running the D0 materializer unchanged | `source-proof.md` |
| DA-08 | Patch changes exactly six allowlisted scratch files and reverses to BASE | AUTO-RESOLVE | Built A and Q/P; recorded hashes | Editing additional files | `series-build.json` |
| DA-11 | Absent lane has zero hits/calls | AUTO-RESOLVE | Emitted 0 ns child stages and `NOT_APPLICABLE` fractions | Dividing by zero or filling omitted values | campaign stage tables |
| DA-15 | Host authorized and contention probes clear | AUTO-RESOLVE | Executed campaigns without renewed approval | Asking for routine confirmation | 128 clear probes |
| DA-16 | First final-T0 A/A attempt failed a transient block ratio | AUTO-RESOLVE | Preserved attempt 1; one complete fresh retry after quiescence | Selective lane rerun or threshold change | `preflight.md`, superseded evidence |
| DA-18 | Any oracle/index/binary mismatch | HARD STOP (not triggered) | No mismatch occurred; verifier PASS | Rerunning selected lanes | `verification.json` |
| DA-19 | First paired campaign structurally/intrusion qualified | AUTO-RESOLVE | Archived campaign 01 and ran campaign 02 unchanged | Pooling or skipping independent confirmation | `performance-qualification.md` |
| DA-20 | Campaign 01 below the quantitative priority gate | AUTO-RESOLVE | Ran campaign 02 unchanged for independent confirmation | Tuning thresholds or adding campaigns | same |
| DA-23 | Quantitative gate met | Not triggered | No D2-B implementation | Implementing an executor | verdict |
| DA-24 | Quantitative gate failed in both campaigns | AUTO-RESOLVE | Reported `D2A_SCORE_COST_LOW_PRIORITY`; archived negative evidence | New optimization work | aggregate JSON |
| DA-25 | Non-winner error/budget/cancellation parity cannot be proven | DEFER AND CONTINUE | Recorded `D2_B_NOT_AUTHORIZED_BY_D2A`; completed measurement | Implementing a skip-scoring path | `correctness-trace.md` |
| DA-26 | Raw evidence initially only under `target/` | AUTO-RESOLVE (resolved) | Archived all three qualified campaigns with exclusive create before closeout | Treating `target/` as durable | `evidence-index.md` |
| DA-28 | No off-host backup supplied | AUTO-RESOLVE | Recorded `SAME_DISK_ONLY`; made no disaster-safe claim | Calling same-disk storage a backup | archive records |
| DA-29 | Local real RustFS unavailable | DEFER AND CONTINUE | No RustFS claim; local scoring attribution proceeded | Faking remote coverage | `qa.md` |
| DA-32 | New test/coverage regressions | HARD STOP (not triggered) | Final QA reported in `qa.md`; no waivers | Lowering coverage or excluding crates | `qa.md` |
| DA-35 | Verifier rejected campaign 01 under T0 `2774c87` because Q-slot derivative metadata was wrong | HARD STOP for that series | Preserved campaign 01 as superseded; corrected tooling; froze new T0 `747ceb2`; discarded prior qualification and reran A/A and both campaigns | Silently patching and reverifying as though the protocol had not changed | `preflight.md`, superseded evidence |
| DA-36 | Unexpected condition | Not triggered | — | Improvising | — |

## Blocked/independent task split

No routine task is blocked. The following are explicitly **not** authorized or
not applicable:

- D2-B implementation: not authorized by D2-A and not recommended by the
  `LOW_PRIORITY` verdict.
- Real RustFS end-to-end scoring attribution: not required for this
  measurement-only PR; existing hosted CI remains a separate gate.
- Production score/executor/format changes: out of scope.
