# PR 14F — `pr14_p4_v1` benchmark report

**Status: `BLOCKED — OPERATOR ATTESTATION REQUIRED`. No fresh trial was
executed. No new performance number exists in this document.**

## 1. Result boundary

`pr14_p4_v1` compares Quervant local `FsDirectory` with Quervant backed by the
pinned real RustFS. It is not a Quervant-vs-Tantivy/Lucene comparison and not a
production p99 SLO. Lanes `local-cold`, `local-warm`, `remote-cold` and
`remote-warm` are never pooled.

Required publication evidence — three independent source-identical qualified
trials, 14 `(lane, workload)` pairs, 20 samples each, live `clear` contention per
trial, validator PASS with the approved W08 N/A waiver and the strict auditor
PASS — is **absent** because the human operator idle attestation was not
supplied. The agent did not invent one, run a diagnostic substitute, or promote
historical data.

## 2. Current measurements

| Item | Value |
|---|---|
| Fresh qualified trials | 0 of 3 |
| Fresh raw CSV files | 0 |
| Fresh sanitized reports | 0 |
| Contention records | 0 |
| Lane/workload tables | **not produced** |
| p50/p95/p99 values | **not produced** |

No table of latencies is included: producing one would require either measured
samples or relabelled historical values, both prohibited here (AD-F17/AF-BF17).

## 3. Historical provenance (not current results)

The committed files `benchmarks/reports/pr14-p4-t{1,2,3}.json` were produced on
`ab9b2d7da066ec80190dcee70a8cebfd81481b80` in an earlier qualification cycle.
They remain byte-identical (SHA-256 recorded in `baseline-inventory.md`) and are
**provenance only**. They are not re-validated, not re-stamped with the PR 14F
source SHA, not pooled with anything, and not the basis of any acceptance claim.
Their `raw_csv` pointers are absolute historical paths that need not exist on
this host.

## 4. Frozen contract that an attested campaign will measure

| Pair | Workload | Oracle / recorded `hits` |
|---|---|---|
| `local-cold` | W09 reopen + W01 | 10,000 |
| `local-warm` | W02 mixed | 10,000 |
| `local-warm` | W03 JSON `$.n == 5` | 2,000 |
| `local-warm` | W04 geo bbox | 6,000 |
| `local-warm` | W05 IP + time | 2,500 |
| `local-warm` | W06 aggregation batch | 1 (batch response length; oracle separately asserts 4 × 5,000 = 20,000) |
| `local-warm` | W07 ordered batch | 3 (batch response length; oracle separately asserts S/F/S) |
| `remote-cold` | W01 open + first query | 10,000 |
| `remote-warm` | W02–W07 | same as local-warm |

Corpus: 20,000 documents, three immutable segments, seed `0x14F4_2026`, digest
`80ef56151e6b1e4625fb2e5d9f03106a3fa9e292ffea77d4f4630f4a753f8768`. Warmups 3,
samples 20, runner percentile convention nearest-rank
(`round((n-1)*p)` on sorted samples).

W08 is **NOT APPLICABLE (APPROVED)** under the unchanged Option 2 waiver; it is
never reported as measured or passed (AD-F12).

## 5. How the report will be produced once unblocked

1. Operator attests idleness and supplies provider env.
2. `bash benchmarks/scripts/run-pr14-p4.sh --trials=3 --idle-confirmed` writes
   raw CSV and sanitized JSON under ignored
   `target/pr14-p4/{reports,qualification}/<source-sha>/`.
3. `validate-pr14-p4.py --w08-exemption …` and `audit-pr14f-trials.py` must both
   pass.
4. Sanitized copies go to unique tracked names
   `benchmarks/reports/pr14f-p4-<sha-prefix>-t{1,2,3}.json`; raw CSV is archived
   with SHA-256 and a durable locator.
5. Per-lane p50/p95/p99 and cross-trial dispersion are derived directly from the
   raw CSVs; cold/warm and local/remote are never pooled.

If the raw CSV cannot be durably archived, the report must say
`RAW ARCHIVE BLOCKED`; the current report is already blocked before that gate.

## 6. Non-claims

- No fresh latency, throughput, memory or I/O number is asserted.
- No cross-engine superiority is asserted.
- No production p99 or SLO claim is made.
- PR 14 remains **IN PROGRESS / NOT ACCEPTED**; v0.1 is **NOT RELEASED**.
