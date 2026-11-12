# PR 15I-D3-B-F1.2 — decision register

| Rule | Observed trigger | Action / result |
|---|---|---|
| F12-01 | Branch and HEAD `66cd833e…` as documented | Continued on the existing branch |
| F12-03/04 | `main`/`origin/main` still pinned; local SHAs valid | Pinned BASE; no rebase |
| F12-05/06 | Candidate blob `493f9382…`; protected file clean | Preserved until the qualified rollback |
| F12-07 | Pre-existing `disk-cleanup.sh` modification | Preserved untouched; not staged |
| F12-08/09 | T0/T1/T2 diffs empty; F1.1 archives match pinned SHA | Read-only historical reference only |
| F12-11/12 | Fresh F1.2 namespace; no official output names existed | Copied T2, created new names |
| F12-13/14 | Protocol delta exactly nine top-level entries; frozen gates equal | Froze candidate after tests |
| F12-15/17/19 | `/proc/stat` valid; settle 5,000.8/5,001.5 ms; all intervals in window; medians 19‰/0‰ | `READY`; proceeded to timed acquisition |
| F12-20/21 | No interval/steal/median failure; optional frequency advisory | Continued |
| F12-24/25 | Verifier independently rederived readiness, agreement | Structural readiness PASS |
| F12-26/27/28 | RD/SC suites and full rehearsal failed initially on harness bugs only | Fixed only new F1.2 tooling; T_PRE2..T_PRE9 and full rerun; no gate/algorithm change |
| F12-29/31 | Full external rehearsal passed; publish guard refused synthetic data | Permitted T3 freeze |
| F12-33/35 | T3 = `c86c3b15…`; tooling bytes unchanged during rehearsal | T3 frozen; no tooling edit afterwards |
| F12-37/38 | Control A/A binaries byte-identical (`e6363c86…`, 4,479,112 B) | Continued A/A timing |
| F12-41/42 | Corpus/oracle/index sentinels exact | Continued |
| F12-43/44 | Native ext4 for all seven roles; `findmnt` agrees | Continued |
| F12-45/46 | 32/32 clear probes; full affinity observations | Continued |
| F12-47 | Control independently `CONTROL_QUALIFIED`, READY | Archived and ran paired 01 |
| F12-50–52 | Paired 01 independently `QUALIFIED_REJECTED` (drift PASS, P03 FAIL) | Archived negative evidence, **no campaign 02**, rollback |
| F12-58/63 | Qualified rejection even though P01/P02 passed | Mandatory additive rollback; P08 FAIL |
| F12-65/66 | New archive paths; sidecars and extraction verified | Published both campaigns exclusively |
| F12-67 | `unified.rs` exact candidate and clean before rollback | Restored BASE blob `bb7a1035…`, additive commit `5d3bf1f7…` |
| F12-69/70 | RustFS harness started and health-checked; m1/m2 real adapter tests passed | `RUSTFS_HARNESS_PASS` + production adapter PASS; D3-B `i12` query test has a test-side bug and is not counted |
| F12-71 | No hosted CI/PR token in this session | Local-only closeout, `CI_PENDING`, `PR_NOT_CREATED` |
| F12-73 | Stable/MSRV all-feature tests, 92.68% coverage, all Python suites | PASS |
| F12-74 | CI/review not executed | Explicitly pending; no merge claim |

## Human decision required

Optional next steps only: merge/release review, hosted CI, independent source
review, and a decision on whether to investigate the 100K K10 regression in a
separate optimization PR or abandon the prefilter. No further benchmark run is
authorized by this plan.
