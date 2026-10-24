# PR 14C — benchmark report (`pr14_p4_v1`)

**Status: `BLOCKED` — no qualified PR 14C benchmark trial was executed.**
This report contains **no current-branch measurement**. It records why the
benchmark gate is blocked and preserves the historical provenance separately.

## 1. Why no qualified trial was run

| Condition (AD-14C-03/04, plan §7) | State at PR 14C |
|---|---|
| Pinned real RustFS available | YES — image digest verified, container started, health `1.0.1` |
| Versioned workload `pr14_p4_v1` and harness present | YES — unchanged since P4 |
| Validator self-test PASS | YES — `python3 benchmarks/scripts/validate-pr14-p4.py --self-test` → `PASS self-test` |
| Clean tracked tree at execution time | At P1 preflight, yes; benchmark window not reached |
| Operator `--idle-confirmed` attestation on a quiet native-Linux host | **NOT PROVIDED** (host is WSL2; qualified mode refuses without the flag) |
| Overall PR 14 acceptance path | **Blocked** by `R-14A-JSON-MEM` = `REQUIRE SEPARATE CORRECTION` |

A diagnostic run would be permitted without idle attestation, but a diagnostic
run **cannot qualify** and cannot substitute for the three independent qualified
trials. Running it would not change any gate, so it was not performed.

Because the human decision requires a separate correction before PR 14 can be
accepted, fresh PR 14C trials would not unblock acceptance. They remain
mandatory for any later acceptance attempt.

## 2. Historical provenance (not a PR 14C measurement)

The only P4 trials of record were produced on source SHA
`ab9b2d7da066ec80190dcee70a8cebfd81481b80` (2026-10-19), which is **138 commits
behind** the PR 14C baseline `376023b`. They must not be presented as
current-branch metrics.

| Item | Historical value |
|---|---|
| Workload | `benchmarks/workloads/pr14_p4_v1.md` (unchanged) |
| Corpus | 20,000 deterministic documents, 3 immutable segments, seed `0x14F4_2026` |
| Corpus digest | `80ef56151e6b1e4625fb2e5d9f03106a3fa9e292ffea77d4f4630f4a753f8768` |
| Trials | `t1`, `t2`, `t3` (`qualified=true`, `idle_confirmed=true`, `contention=clear`, `dirty=false`) |
| Warmups / samples | 3 / 20 per configuration per trial |
| Toolchain then | stable 1.98.1, WSL2 native Linux filesystem |
| Validator | `PASS: 3 qualified pr14_p4_v1 trials` with `--w08-exemption` (re-run during PR 14C) |
| Sanitized reports | `benchmarks/reports/pr14-p4-t{1,2,3}.json` |
| Raw CSVs (local, untracked) | `target/pr14-p4/pr14-p4-t{1,2,3}.csv` from the historical run |

Historical aggregate (microseconds, 60 samples per row) — **reproduced from
`docs/pr-artifacts/pr-14/p4-benchmark-report.md` for provenance only, not
re-measured in PR 14C**:

| Lane | Workload | p50 | p95 | p99 |
|---|---|---:|---:|---:|
| local-cold | W09 | 2,791,865 | 3,256,871 | 3,286,073 |
| local-warm | W02 | 1,346,260 | 1,446,588 | 1,456,796 |
| local-warm | W03 | 1,183,726 | 1,242,747 | 1,253,266 |
| local-warm | W04 | 1,185,522 | 1,344,568 | 1,347,164 |
| local-warm | W05 | 1,194,371 | 1,243,851 | 1,248,136 |
| local-warm | W06 | 1,412,135 | 1,460,267 | 1,461,621 |
| local-warm | W07 | 2,668,916 | 2,885,063 | 2,892,061 |
| remote-cold | W01 | 3,366,827 | 3,736,412 | 4,112,644 |
| remote-warm | W02 | 1,355,753 | 1,405,939 | 1,425,736 |
| remote-warm | W03 | 1,185,093 | 1,215,781 | 1,258,194 |
| remote-warm | W04 | 1,159,450 | 1,203,056 | 1,218,657 |
| remote-warm | W05 | 1,157,692 | 1,174,207 | 1,209,331 |
| remote-warm | W06 | 1,367,564 | 1,409,101 | 1,437,548 |
| remote-warm | W07 | 2,631,199 | 2,673,779 | 2,686,434 |

No cross-engine (Tantivy/Lucene) comparison exists here; PR 15B owns that. No
p99 SLO or superiority claim is made. Values are sample quantiles from one
historical environment.

## 3. Workload and correctness oracle (contract, unchanged)

`pr14_p4_v1` lane expectations are hand-derived from the corpus contract and
asserted **before** timing:

| ID | Query | Expected |
|---|---|---|
| W01 | mixed `title:alpha AND n in [0,20000)` (cold open + first query) | 10,000 |
| W02 | W01 repeatedly, warm | 10,000 |
| W03 | JSON `$.n == 5`, projection + sort by `n` | 2,000 |
| W04 | geo bbox `[-1,-1,2,2]`, distance sort | 6,000 |
| W05 | IP `192.0.2.1` AND `ts in [0,10000e6)` | 2,500 |
| W06 | group `host`, count + sum `n` | 4 groups × 5,000 |
| W07 | ordered 3-slot batch: aggregation success, invalid aggregation failure, plain success | S/F/S |
| W08 | forced cache eviction → reload → W01 | **DEFERRED / NOT APPLICABLE** for v0.1 |
| W09 | local `FsDirectory` cold reopen → W01 | 10,000 |

## 4. W08 — approved exception (not a measured pass)

`W08` is **NOT APPLICABLE** for v0.1 under the approved Option 2
snapshot-lifetime pinning decision (`docs/pr-artifacts/pr-14/p4-w08-stop.md`,
`benchmarks/reports/pr14-p4-w08-exemption.json`). The validator requires the
exemption manifest; it was exercised successfully in PR 14C. W08 is never
reported as measured or PASS.

## 5. What a future acceptance attempt must produce

1. Operator `--idle-confirmed` attestation and contention `clear`
   (`check-pr07-contention.py`), on a native Linux filesystem.
2. A clean tracked tree at the recorded source SHA.
3. Three independent trials, each with the pre-timing correctness oracle and
   warmups ≥ 3 / samples ≥ 20 for every lane.
4. Archived raw CSVs plus sanitized reports recording toolchain, kernel, fs,
   CPU, dataset digest, seed, cache regime, failed/unqualified attempts.
5. Validator PASS, including the W08 exemption manifest.
6. A report that never pools cold/warm or local/remote, and makes no
   cross-engine claim.

## 6. Status

| Flag | State |
|---|---|
| Benchmark harness present and self-tested | YES |
| Qualified PR 14C trials | **0 of 3** |
| C08 | **BLOCKED** |
| C-T10 | **BLOCKED** |
| C-T11 (W08 exemption) | PASS |
| Historical provenance cited as current measurement | **NO** |
