# PR 14F — test and evidence traceability

**Status:** harness and local validation complete; benchmark qualification
blocked on the operator idle attestation.

## 1. BF01–BF20

| ID | Required proof | State | Evidence |
|---|---|---|---|
| BF01 | Branch ancestry, clean base, 40-char source SHA | **PASS** | `baseline-inventory.md` §1; branch from `origin/main` `7b1b84be…`; source lock `162cbfea…` |
| BF02 | Historical t1/t2/t3 SHA-256 unchanged | **PASS** | `baseline-inventory.md` §3; re-checked after source-lock commit |
| BF03 | Diagnostic env absent in qualified child, set only in diagnostic | **PASS (stub-level)** | `test-scripts.sh` PR14F block: 3 × `diag:unset`, 2 × `diag:1`; wrapper `env -u` array. No live qualified child exists to observe |
| BF04 | `--trials=3` and `--trials 3` accepted; invalid exit 2 | **PASS** | `test-scripts.sh`: space form accepted; `0`, `21`, `abc`, missing, unknown switch all exit 2 |
| BF05 | Report dir under ignored `target/`; no tracked dirty transition | **PASS (static/stub)** | `git check-ignore target/pr14-p4/` → `.gitignore:7`; runner `QUERVANT_P4_REPORT_DIR`; stub campaign wrote only under `target/pr14-p4/`; `git status --short` after tests showed no tracked change |
| BF06 | Validator negative self-test; W08 required/approved | **PASS** | `validate-pr14-p4.py --self-test` → `PASS self-test`; approved waiver unchanged |
| BF07 | Auditor rejects stale SHA, altered digest, duplicate/short/missing rows, bad measurements | **PASS** | 25/25 `test-pr14f-audit.py` tests |
| BF08 | Contemporaneous operator idle attestation; agent did not infer it | **PASS** | human statement recorded in `qualification-attempts.md` §1; host was idle (`0.27` load, 100% idle) |
| BF09 | Native Linux FS and exact pinned real RustFS digest/version/health | **PASS** | `environment-and-provider.md` §1–2; ext4; digest `1803faef…6a3c`; health `1.0.1` |
| BF10 | Each trial has a separate live contention record `state=clear` | **BLOCKED (1 of 3)** | t1 record `state=clear`, CPU busy `0.003745`, competing 0; t2/t3 never ran |
| BF11 | Hand-derived correctness oracle before timing (W01–W07/W09) | **PASS for t1; campaign BLOCKED** | t1 completed correctness before timing; t2/t3 absent |
| BF12 | Corpus 20,000 / 3 segments / seed / expected digest | **PASS for t1** | t1 emitted `80ef5615…f8768`, 20,000 docs; static replication in `baseline-inventory.md` §4 |
| BF13 | 14 pairs × 20 distinct samples, finite positive times, valid hits | **PASS for t1; campaign BLOCKED** | t1 CSV: 280 rows, 14 pairs, indices `0..19`, correct hits, positive finite; t2/t3 absent |
| BF14 | Three independent source-identical qualified trials | **BLOCKED** | 1 of 3; t1 unpublishable because the campaign aborted |
| BF15 | Validator PASS with W08 explicit approved N/A | **BLOCKED** | no reports to validate |
| BF16 | SHA-256 of 3 CSV/JSON/contention; truthful raw archive | **BLOCKED** | t1 hashes recorded; t2/t3 absent; no durable archive |
| BF17 | Per-lane p50/p95/p99 from raw CSV; historical separation | **BLOCKED** | `benchmark-report.md` deliberately contains no numbers |
| BF18 | Stable/MSRV fmt/clippy/tests/docs/bench/scripts/coverage ≥85% | **PASS** | `validation-report.md`; coverage 91.84% lines |
| BF19 | PR-head CI `rust`, `msrv`, `rustfs` success on exact immutable SHA | **NOT RUN** | no PR yet; push/PR attempted after this commit |
| BF20 | Independent review and maintainer merge authorization | **NOT DONE** | no reviewer; no merge |

## 2. Preauthorized decision matrix

| X | Trigger | Applied? | Action / evidence |
|---|---|---|---|
| X01 | Dirty workspace before branch | No | tree was clean |
| X02 | `origin/main` moves during planning | No | no drift observed |
| X03 | Source differs materially from frozen assumptions | No | runner/wrapper/workload match the plan’s described state; only the anticipated hazards were present |
| X04 | `--list` lacks `pr14_p4_benchmark` | No | `--list` shows `pr14_p4_benchmark: test` |
| X05 | Qualified diagnostic-env bug | Yes | array + `env -u`; stub tests BF03 |
| X06 | Shell test needs a new framework | No | existing `test-scripts.sh` + `mktemp`/PATH stubs |
| X07 | Historical reports tracked | Yes | `QUERVANT_P4_REPORT_DIR` under ignored `target/`; old bytes preserved |
| X08 | Validator lacks row/SHA strictness | Yes | separate read-only auditor; validator untouched |
| X09 | Native FS missing / drvfs | No | ext4 root |
| X10 | Provider digest/health unverifiable | No | pinned digest pulled and inspected; health `1.0.1` |
| X11 | Contention `suspected`/`unknown` | No | t1 `state=clear` |
| X12 | Corpus digest mismatch | No | replicated and fixed digest agree |
| X13 | Qualified attempt fails after artifacts | **Yes** | t1 runner PASS but wrapper aborted on report-path check; artifacts preserved and labelled; retry orchestration not approved → **HARD STOP** |
| X14 | Post-hoc unqualified/short/dirty report | Not reached | no report |
| X15 | Idle attestation absent | **Resolved, then X13** | operator supplied the attestation; campaign then aborted on X13 |
| X16 | `/proc` unavailable/malformed | No | `/proc` readable; detector not run for a trial |
| X17 | RustFS env/credentials absent | Yes | DEFER AND CONTINUE: no secrets requested; provider prequalified without credentials in evidence |
| X18 | Executable changes after source lock | No | campaign stopped instead of patching the locked wrapper; executable diff remains empty |
| X19 | Artifact dir/report collision | No | fresh `target/` path; `create_new` guard |
| X20 | Historical JSON stale absolute raw path | Yes | provenance only; never edited |
| X21 | W08 absent with approved exemption | Yes | unchanged waiver passed to validator at campaign time |
| X22 | W08 exemption missing/invalid | No | manifest present and structurally valid |
| X23 | Raw CSV archive not established | Not reached | no raw CSV exists |
| X24 | Validator PASS but audit FAIL | Not reached | neither ran on fresh data |
| X25 | Non-finite/missing/duplicate/incorrect samples | Not reached | no fresh data; auditor tests cover rejection |
| X26 | New latency differs from historical | Not reached | no measurement |
| X27 | Coverage below 85% | No | 91.84% lines |
| X28 | Stable/MSRV/compiler/test failure | No | all local gates PASS |
| X29 | `gh` auth/PR creation impossible | Pending | see `validation-report.md` §5 |
| X30 | Final-head CI queued/in progress/failing | Pending | no PR head yet |
| X31 | Reviewer demands production/interface change | Not reached | no review |
| X32 | Unforeseen condition | **Yes** | cargo runs tests with cwd `crates/quervant-core`, so the relative report dir landed under the package `target/`; stopped without improvising a fix. Details in `qualification-attempts.md` §5 |

## 3. Negative-case coverage of the new harness code

| Behavior | Test |
|---|---|
| Parser: missing/invalid/unknown args exit 2 | `test-scripts.sh` PR14F block |
| Parser: both `--trials` forms | `test-scripts.sh` PR14F block |
| Idle gate in qualified mode | `test-scripts.sh` |
| Exactly three qualified trials | `test-scripts.sh` |
| Dirty-tree rejection | `test-scripts.sh` |
| Missing provider env rejection | `test-scripts.sh` |
| Inherited diagnostic variable removed | `test-scripts.sh` |
| Per-trial contention invocation | counter file = 3 |
| W08 exemption passed to validator | validator log grep |
| Fresh report non-empty check | stub cargo writes report; wrapper requires it |
| Auditor: stale/bad SHA, digest, rows, lanes, samples, hits, times, W08, CSV, contention | `test-pr14f-audit.py` (25) |

These are harness tests. They do not substitute for the blocked real-provider
qualification.
