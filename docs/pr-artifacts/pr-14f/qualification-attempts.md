# PR 14F — qualification attempts and operator gate

**Status:** `BLOCKED — OPERATOR ATTESTATION REQUIRED`. Zero qualified trials,
zero diagnostic trials, zero rejected attempts.

## 1. Gate state

| Gate | State | Evidence |
|---|---|---|
| Source-locked executable | **PASS** | `162cbfea509d5f03df4bedb89a09d9be4cafb75e`; tracked tree clean before provider work |
| Harness corrections committed before measurement | **PASS** | `harness-corrections.md` |
| Native Linux filesystem | **PASS** | ext4 root, WSL2 (allowed) |
| Pinned real RustFS digest and health | **PASS** | `environment-and-provider.md` |
| Operator idle attestation | **ABSENT** | no human statement; agent did not infer one |
| Host known idle at report time | **NO** | load average `5.82` (5 min) after validation workloads |
| Provider env exported for a campaign | **NO** | `QUERVANT_RUSTFS_*` unset in the agent session |
| Contention records for trials | **NONE** | no trial started, so no live detector run |

## 2. Attempt ledger

| Attempt id | UTC window | Kind | Result | Notes |
|---|---|---|---|---|
| — | — | qualified trials | **NOT STARTED** | `--idle-confirmed` never passed |
| — | — | diagnostic trial | **NOT STARTED** | would not change any gate; same reasoning as PR 14E |
| `prequal-provider-1` | 2026-10-26T21:29Z–21:30Z | provider verification | PASS | pinned digest pulled/inspected; health `1.0.1` |
| `preflight-local-1` | 2026-10-26T21:30Z–21:56Z | local validation | PASS | Stage F checks; see `validation-report.md` |

No report JSON, raw CSV or contention JSON was produced under
`target/pr14-p4/reports/162cbfea…` or
`target/pr14-p4/qualification/162cbfea…`. The historical
`benchmarks/reports/pr14-p4-t{1,2,3}.json` were not touched.

## 3. What is required to unblock

A human operator must supply a contemporaneous statement that competing
benchmark workloads are stopped and the host is sufficiently idle, then run (or
authorize the agent to run) the source-locked campaign:

```sh
export QUERVANT_RUSTFS_ENDPOINT=…   # non-secret; not recorded
export QUERVANT_RUSTFS_REGION=…
export QUERVANT_RUSTFS_BUCKET=…
export QUERVANT_RUSTFS_ACCESS_KEY=… # disposable; from secure local environment
export QUERVANT_RUSTFS_SECRET_KEY=…
bash benchmarks/scripts/run-pr14-p4.sh --trials=3 --idle-confirmed
```

The wrapper requires a clean tracked tree at the source-lock SHA. Any subsequent
executable change invalidates the campaign (X18).

## 4. Post-trial gates (not yet runnable)

```sh
python3 benchmarks/scripts/validate-pr14-p4.py \
  --w08-exemption benchmarks/reports/pr14-p4-w08-exemption.json \
  target/pr14-p4/reports/<SOURCE_SHA>/pr14-p4-t1.json \
  target/pr14-p4/reports/<SOURCE_SHA>/pr14-p4-t2.json \
  target/pr14-p4/reports/<SOURCE_SHA>/pr14-p4-t3.json
python3 benchmarks/scripts/audit-pr14f-trials.py \
  --expected-sha <SOURCE_SHA> \
  --expected-digest 80ef56151e6b1e4625fb2e5d9f03106a3fa9e292ffea77d4f4630f4a753f8768 \
  target/pr14-p4/reports/<SOURCE_SHA>/pr14-p4-t1.json \
  target/pr14-p4/reports/<SOURCE_SHA>/pr14-p4-t2.json \
  target/pr14-p4/reports/<SOURCE_SHA>/pr14-p4-t3.json
```

Both must pass before publication. Validator PASS alone is insufficient
(AD-F13/X24).

## 5. Provider lifecycle note

The pinned RustFS container `quervant-pr14f-rustfs` was started solely for
digest/health prequalification and left running so an attested campaign can
reuse the same instance. It is idle. If the operator prefers a cold provider
start, the container may be recreated from the same pinned digest; the harness
uses a unique remote prefix per trial and does not depend on container history.
