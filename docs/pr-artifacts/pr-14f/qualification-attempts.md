# PR 14F — qualification attempts and operator gate

**Status:** `BLOCKED — CAMPAIGN ABORTED AFTER T1 (HARNESS REPORT-PATH DEFECT)`.
One trial (`t1`) executed completely and reported `qualified=true` with a
`clear` contention record, but the wrapper aborted before appending it because
the relative `QUERVANT_P4_REPORT_DIR` resolved under
`crates/quervant-core/target/…` instead of the repository `target/…`. Trials
`t2` and `t3` were never started. **0 of 3 trials are publishable.**

## 1. Operator attestation

The human operator supplied the required contemporaneous statement on
2026-10-26:

> “I confirm that competing benchmark workloads have been stopped and that the
> machine is sufficiently idle for performance measurements. You are authorized
> to execute the three qualified PR 14F benchmark trials using
> `--idle-confirmed`.”

The agent did not infer the attestation from metrics. Host state immediately
before the campaign: load `0.27 0.09 0.24`, 100% idle CPU, 0 runnable
processes.

## 2. Gate state

| Gate | State | Evidence |
|---|---|---|
| Source-locked executable | **PASS** | measurement at detached `162cbfea509d5f03df4bedb89a09d9be4cafb75e`; clean tree |
| Operator idle attestation | **PASS** | §1 |
| Pinned real RustFS digest and health | **PASS** | `environment-and-provider.md`; exercised by t1 |
| t1 committed source SHA | **PASS** | report `sha = 162cbfea…` |
| t1 corpus digest / oracle | **PASS** | digest `80ef5615…f8768`; correctness ran before timing |
| t1 live contention | **PASS** | `state=clear`, `cpu_busy_fraction=0.003745`, competing = 0 |
| t1 report placement and campaign continuation | **FAIL** | wrapper exited 1 before t2 |
| Trials t2/t3 | **NOT STARTED** | wrapper aborted |
| Validator / strict audit on three reports | **NOT RUN** | only one report artifact exists |
| Publication | **BLOCKED** | 0 of 3 publishable |

## 3. Attempt ledger

| Attempt id | UTC window | Kind | Result | Detail |
|---|---|---|---|---|
| `t1-attempt-1` | 2026-10-26T22:43:30Z–22:54:30Z | qualified trial | **RUNNER PASS / CAMPAIGN FAIL** | 648.53 s; `1 passed`; `qualified=true`; report written under `crates/quervant-core/target/pr14-p4/reports/162cbfea…/pr14-p4-t1.json` |
| `t2` | — | qualified trial | **NOT STARTED** | wrapper aborted after t1 |
| `t3` | — | qualified trial | **NOT STARTED** | wrapper aborted after t1 |
| `prequal-provider-1` | 2026-10-26T21:29Z–21:30Z | provider verification | PASS | pinned digest pulled/inspected; health `1.0.1` |
| `preflight-local-1` | 2026-10-26T21:30Z–21:56Z | local validation | PASS | `validation-report.md` |

No trial was rejected for correctness, provider identity, contention or data
integrity. `t1` is an unpublishable qualified artifact solely because the
campaign harness aborted and the remaining two independent trials do not exist.

## 4. Preserved t1 artifacts

Staged read-only copies (byte-identical, never rewritten) are under the ignored
directory:

```text
target/pr14-p4/attempts/162cbfea509d-t1-harness-failure/
  pr14-p4-t1.json
  pr14-p4-t1.csv
  pr14-p4-contention-t1.json
  pr14-p4-t1-run.log
  SHA256SUMS
```

| Artifact | SHA-256 |
|---|---|
| `pr14-p4-t1.json` | `c19a3103386c502e023f9d41604b08392ae94526fde387db4fd81501b2593a26` |
| `pr14-p4-t1.csv` | `f02818f2a413556e755aeec859ffa306379350cdd271753154f0366bcbc43543` |
| `pr14-p4-contention-t1.json` | `40f82b2f357295626046209d133fcc9f7fb4088a2903ab54ecbc4a8e3bb3c421` |
| `pr14-p4-t1-run.log` | `a89716d58a7e8daefcae197c1a7d6b5a24894efd10cd58ac198c1d3e3cc155c8` |

The report's acquisition-time `raw_csv` pointer is the absolute repository path
`…/quervant/target/pr14-p4/pr14-p4-t1.csv`; it is not rewritten. Independent
re-check of the CSV: 280 data rows, exactly 14 required pairs, sample indices
`0..19` per pair, positive finite durations, correct runner `hits` (including
W06 `1` and W07 `3`).

## 5. Root cause of the abort

`run-pr14-p4.sh` sets `report_dir="target/pr14-p4/reports/$source_sha"` and
passes it through `QUERVANT_P4_REPORT_DIR`. The wrapper `cd`s to the repository
root, but `cargo test` runs the test binary with its working directory set to
the package root (`crates/quervant-core`). `PathBuf::from("target/pr14-p4/…")`
in the runner therefore resolved to
`crates/quervant-core/target/pr14-p4/…`, while the wrapper checked
`$ROOT/target/pr14-p4/…`. The wrapper’s fail-closed report-existence check
aborted the campaign after t1.

The trial data are unaffected: raw CSV uses `CARGO_MANIFEST_DIR`, and the JSON
content is correct. The defect is in qualified-campaign path orchestration.

## 6. Required to resume

A minimal, reviewable fix is to make the qualified report and qualification
directories absolute in the wrapper:

```bash
report_dir="$ROOT/target/pr14-p4/reports/$source_sha"
qualification_dir="$ROOT/target/pr14-p4/qualification/$source_sha"
```

This changes an executable harness input, so it requires a **new source lock
and a fresh three-trial campaign** (AD-F04/X18). `t1` from the old lock cannot
be reused or promoted. The operator must also re-supply the idle attestation for
the new campaign.

Approval is requested for exactly this fix plus a re-locked campaign. No
unapproved fix was applied to the source-locked executable.

## 7. Provider lifecycle note

The pinned RustFS container `quervant-pr14f-rustfs` is healthy and was exercised
by t1 (bucket creation, three commits, cold opens, warm queries). It remains
running for a corrected campaign. Credentials, endpoint and bucket values are
not recorded in this document.
