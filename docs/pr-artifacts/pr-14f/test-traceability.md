# PR 14F — test and evidence traceability

**Status:** qualified benchmark campaign PASS at source SHA
`7df492023397a512e400b03865a989020eff1430`; remaining PR 14F gates are the
durable raw archive, final-head CI, independent review and merge authorization.

## 1. BF01–BF20

| ID | Required proof | State | Evidence |
|---|---|---|---|
| BF01 | Branch ancestry, clean base, 40-char source SHA | **PASS** | `baseline-inventory.md` §1; source lock `7df492023397a512e400b03865a989020eff1430` |
| BF02 | Historical t1/t2/t3 SHA-256 unchanged | **PASS** | `baseline-inventory.md` §3; re-checked after publication |
| BF03 | Diagnostic env absent in qualified child, set only in diagnostic | **PASS** | 58 shell tests: 3 × `diag:unset`, 2 × `diag:1`; inherited value removed by `env -u` |
| BF04 | `--trials=3` and `--trials 3` accepted; invalid exit 2 | **PASS** | shell tests cover both forms and `0`, `21`, `abc`, missing, unknown switch |
| BF05 | Report dir under ignored `target/`; no tracked dirty transition | **PASS** | absolute `$ROOT/target/...`; shell test asserts absolute path; `git status` clean after campaign |
| BF06 | Validator negative self-test; W08 required/approved | **PASS** | `validate-pr14-p4.py --self-test` → `PASS self-test`; approved waiver unchanged |
| BF07 | Auditor rejects stale SHA, altered digest, duplicate/short/missing rows, bad measurements | **PASS** | 25/25 `test-pr14f-audit.py` tests |
| BF08 | Contemporaneous operator idle attestation; agent did not infer it | **PASS (timing disclosed)** | human statement in `qualification-attempts.md` §1; corrected campaign timing disclosed |
| BF09 | Native Linux FS and exact pinned real RustFS digest/version/health | **PASS** | `environment-and-provider.md`; ext4; digest `1803faef…6a3c`; health `1.0.1` |
| BF10 | Each trial has a separate live contention record `state=clear` | **PASS** | t1 `0.003331`, t2 `0.004990`, t3 `0.003744`; competing 0 |
| BF11 | Hand-derived correctness oracle before timing (W01–W07/W09) | **PASS** | each trial completed the independent oracle before timing |
| BF12 | Corpus 20,000 / 3 segments / seed / expected digest | **PASS** | all trials emitted `80ef5615…f8768`, 20,000 docs |
| BF13 | 14 pairs × 20 distinct samples, finite positive times, valid hits | **PASS** | auditor PASS on three CSVs (280 rows each, indices `0..19`, correct hits) |
| BF14 | Three independent source-identical qualified trials | **PASS** | t1/t2/t3, all `sha=7df4920…`, distinct reports/CSVs, no pooling |
| BF15 | Validator PASS with W08 explicit approved N/A | **PASS** | `PASS: 3 qualified pr14_p4_v1 trials` |
| BF16 | SHA-256 of 3 CSV/JSON/contention; truthful raw archive | **PASS (operator-attested durable)** | deterministic 21-member package `6cef9c71…8fe66d`; all checksums verify; Google Drive copy declared same SHA-256; agent re-download blocked by Google auth |
| BF17 | Per-lane p50/p95/p99 from raw CSV; historical separation | **PASS** | `benchmark-report.md` tables derived by a read-only stdlib analysis staged with the raw evidence; historical files untouched |
| BF18 | Stable/MSRV fmt/clippy/tests/docs/bench/scripts/coverage ≥85% | **PASS** | `validation-report.md`; 91.84% lines; 58 shell + 25 auditor tests |
| BF19 | PR-head CI `rust`, `msrv`, `rustfs` success on exact immutable SHA | **PASS at `4c94ba8`, `bd1fed7`, `8887541`; current binding head pending** | PR #67 runs 40424504536, 40441448948, 40443185707; public API verified |
| BF20 | Independent review and maintainer merge authorization | **NOT DONE** | no reviewer; no merge |

## 2. Preauthorized decision matrix

| X | Trigger | Applied? | Action / evidence |
|---|---|---|---|
| X01 | Dirty workspace before branch | No | clean tree |
| X02 | `origin/main` moves during planning | No | no drift |
| X03 | Source differs materially from frozen assumptions | No | anticipated harness state only |
| X04 | `--list` lacks `pr14_p4_benchmark` | No | `pr14_p4_benchmark: test` present |
| X05 | Qualified diagnostic-env bug | Yes | array + `env -u`; shell tests |
| X06 | Shell test needs a new framework | No | existing harness + PATH stubs |
| X07 | Historical reports tracked | Yes | `QUERVANT_P4_REPORT_DIR` under ignored `target/`; old bytes preserved |
| X08 | Validator lacks row/SHA strictness | Yes | separate read-only auditor; validator untouched |
| X09 | Native FS missing / drvfs | No | ext4 root |
| X10 | Provider digest/health unverifiable | No | pinned digest pulled/inspected; health `1.0.1` |
| X11 | Contention `suspected`/`unknown` | No | all three checks `clear` |
| X12 | Corpus digest mismatch | No | `80ef5615…f8768` in all trials |
| X13 | Qualified attempt fails after artifacts | **Yes** | campaign-1 t1 aborted on report path; preserved and disclosed; operator approved fix; campaign-2 ran three fresh trials |
| X14 | Post-hoc unqualified/short/dirty report | No | all three reports qualified, 20 samples, clean |
| X15 | Idle attestation absent | Resolved | attestation supplied; corrected-campaign timing disclosed in adversarial review |
| X16 | `/proc` unavailable/malformed | No | live detector succeeded for every trial |
| X17 | RustFS env/credentials absent | Initially yes | non-secret env and disposable credentials supplied locally; never recorded |
| X18 | Executable changes after source lock | **Yes, approved** | wrapper absolute-path fix; new source lock `7df4920`; all three trials repeated; old t1 not reused |
| X19 | Artifact dir/report collision | No | fresh `target/` path; `create_new` guard |
| X20 | Historical JSON stale absolute raw path | Yes | provenance only; never edited |
| X21 | W08 absent with approved exemption | Yes | unchanged waiver passed to validator |
| X22 | W08 exemption missing/invalid | No | manifest valid |
| X23 | Raw CSV archive not established | **Resolved (operator-attested)** | deterministic package verified locally; Google Drive copy with matching declared SHA-256 |
| X24 | Validator PASS but audit FAIL | No | both PASS |
| X25 | Non-finite/missing/duplicate/incorrect samples | No | auditor PASS; 280 rows/CSV |
| X26 | New latency differs from historical | Yes | descriptive dispersion reported; no invented threshold |
| X27 | Coverage below 85% | No | 91.84% lines |
| X28 | Stable/MSRV/compiler/test failure | No | all local gates PASS |
| X29 | `gh` auth/PR creation impossible | Pending | token invalid; PR #67 already exists; CI verified via public API |
| X30 | Final-head CI queued/in progress/failing | Pending | `4c94ba8`, `bd1fed7`, `8887541` green; current binding head pending |
| X31 | Reviewer demands production/interface change | Not reached | no review |
| X32 | Unforeseen condition | **Yes** | cargo cwd/report-path defect in campaign 1; stopped, disclosed, approved fix, new lock and fresh campaign |

## 3. New harness tests

| Behavior | Test |
|---|---|
| Parser: missing/invalid/unknown args exit 2 | `test-scripts.sh` |
| Parser: both `--trials` forms | `test-scripts.sh` |
| Idle gate / exactly three qualified trials | `test-scripts.sh` |
| Dirty-tree and missing-provider-env rejection | `test-scripts.sh` |
| Inherited diagnostic variable removed | `test-scripts.sh` |
| Per-trial contention invocation | counter = 3 |
| W08 exemption passed to validator | validator log |
| **Absolute report/qualification paths** | shell stub asserts `$ROOT/target/...` and rejects relative |
| Auditor correctness/row/staleness rejection | 25 `test-pr14f-audit.py` tests |
| Percentile summary consistency | read-only derivation staged in the raw-evidence archive (not a measurement input) |

These tests support the harness; the real qualification is the executed
three-trial campaign.
