# PR 15E Phase 4 — targeted performance qualification

**Status: `P4_PERF_MEASURED`** — independent phase review pending. No Phase 5 work and no
merge were performed.

Sanitized machine-readable summary:
`benchmarks/reports/pr15e-b1/phase4-targeted-comparison.json`. Raw samples, build logs,
index digests, host details and the operator attestation stay private under
`target/pr15e-b1/p4/` (gitignored).

## 1. Identity and parity

| Item | Value |
|---|---|
| Arm A — accepted Phase 3 | `df9b8565a4e47c5c66a7edeb566333643672e3fa` (pinned predecessor) |
| Arm B — Phase 4 | `483cd55b4c0e6eed44daddacd47f0889cd35cd8b` (descends from `b7a9def`; Rust tree identical to code SHA `29e89e2`) |
| Tooling revision | `483cd55b4c0e6eed44daddacd47f0889cd35cd8b` |
| Release adapter SHA-256 | A `1fbf3e03e3ce…` · B `14510b73c100…` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` (both arms) |
| Host fingerprint | identical both arms (`4f971362f029…`) |
| Trials / samples | 3 / 20 per lane, 9 lanes, both arms |
| Contention probes | 54/54 `clear` (before and after every trial) |
| Oracle | untimed per lane + `validate_query_response` on every sample, both arms: PASS |
| `total_hits` parity | identical for every lane across arms |

Host authorization provenance: the maintainer's Phase 4 instruction explicitly authorized
assuming the host idle and starting the timed run without a new confirmation; that
instruction — not an observed fact — is the provenance of `--idle-confirmed`. The runner's
real before/after contention probes remained mandatory and were all `clear`.

## 2. Results — ratio = Phase 4 median / Phase 3 median

| Lane | Arm A median | Arm B median | ratio | paired trial ratios | verdict |
|---|---:|---:|---:|---|---|
| `n100000/rare/k100` (**primary**) | 32 853 907 ns | 32 151 619 ns | **0.979** | 0.986, 0.995, 0.948 | **B_FASTER** |
| `n100000/rare/k10` | 33 257 730 ns | 32 495 946 ns | 0.977 | 1.022, 1.012, 0.928 | INCONCLUSIVE |
| `n10000/rare/k100` | 3 359 304 ns | 3 194 239 ns | 0.951 | 1.036, 0.954, 0.867 | INCONCLUSIVE |
| `n100000/absent/k100` | 1 736 633 ns | 1 090 537 ns | **0.628** | 0.659, 0.638, 0.617 | B_FASTER |
| `n10000/absent/k100` | 186 283 ns | 131 513 ns | **0.706** | 0.706, 0.716, 0.660 | B_FASTER |
| `n100000/medium/k100` | 46 376 142 ns | 43 527 383 ns | 0.939 | 0.927, 0.954, 0.928 | B_FASTER |
| `n100000/common/k100` | 76 184 659 ns | 76 225 490 ns | 1.001 | 0.992, 1.004, 1.006 | INCONCLUSIVE |
| `n100000/common/k10` | 64 486 388 ns | 64 745 921 ns | 1.004 | 0.999, 0.993, 1.005 | INCONCLUSIVE |
| `n10000/common/k100` | 7 200 384 ns | 7 065 739 ns | 0.981 | 1.029, 1.008, 0.968 | INCONCLUSIVE |

Per-trial medians (dispersion evidence, trial order as measured):

| Lane | A trial medians (ns) | B trial medians (ns) |
|---|---|---|
| `100K/rare/k100` | 32 853 907 · 32 170 297 · 33 901 810 | 32 402 505 · 32 013 472 · 32 151 619 |
| `100K/rare/k10` | 33 257 730 · 32 106 797 · 33 894 695 | 33 994 944 · 32 495 946 · 31 468 533 |
| `10K/rare/k100` | 3 082 153 · 3 359 304 · 3 537 625 | 3 194 239 · 3 203 771 · 3 068 349 |
| `100K/absent/k100` | 1 736 633 · 1 710 075 · 1 743 317 | 1 144 076 · 1 090 537 · 1 076 361 |
| `10K/absent/k100` | 196 733 · 183 801 · 186 283 | 138 991 · 131 513 · 122 890 |
| `100K/medium/k100` | 47 474 951 · 45 624 186 · 46 376 142 | 44 010 395 · 43 527 383 · 43 056 161 |
| `100K/common/k100` | 76 872 265 · 74 594 246 · 76 184 659 | 76 225 490 · 74 867 380 · 76 658 246 |
| `100K/common/k10` | 65 101 002 · 64 486 388 · 64 403 322 | 65 039 444 · 64 003 715 · 64 745 921 |
| `10K/common/k100` | 7 200 384 · 6 969 557 · 7 300 828 | 7 405 603 · 7 028 602 · 7 065 739 |

Percentiles (median of the three per-trial percentiles) are published in the JSON report.

**Primary lane: `B_FASTER`** (all three paired ratios < 1). **No lane is `A_FASTER`.**
Four controls are `INCONCLUSIVE` and are reported as such rather than as wins.

## 3. Reading the result

* The primary single-posting lane improves by ~2% in wall clock: after B1b the per-document
  membership test is already cheap, so the remaining cost on this lane is statistics, hit
  handling and transport, not the live-document loop.
* The **zero-hit lanes** show the real effect of removing the per-live-document predicate
  call: 100K absent 1.737 ms → 1.091 ms (**0.628**) and 10K absent 0.186 ms → 0.132 ms
  (**0.706**). The full logical work charge is preserved (work-limit admission is identical
  to Phase 3 — asserted by tests).
* 100K medium improves consistently (0.939). High-selectivity `common` lanes are unchanged
  (≈1.00) because their time is dominated by scoring ~50K hits, which this phase
  deliberately does not touch.
* The two `rare` top-K/10K lanes are sign-inconsistent (some trials slightly slower) and are
  `INCONCLUSIVE`; they are not claimed as wins.

## 4. Historical context (not same-session ratios)

Same-host Phase 3 campaign (different session, retained as historical reference only):
primary 78.65 ms → 32.17 ms, medium → 45.13 ms, common → 74.68 ms. Original PR15D `main`
figures come from a third session. None of these are used as Phase 4 paired ratios.

## 5. Limits

* Synthetic exact-term `FsDirectory` workload, `doc_id ASC` sort; says nothing about BM25
  ranking quality, remote-latency execution or distributed search.
* In-process adapter samples include JSON transport but exclude build and index creation.
* Wall-clock `engine_ns` only; no CPU or allocation measurement.
* The logical per-live-document work charge is unchanged, so no previously rejected query
  becomes admissible.
* Single host, single session, trial-paired; not a production p99 or cross-host claim.
* Only the fixed eligible shape is optimized; all other query shapes keep the legacy scan.

## 6. Reproduction

```sh
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /home/yduchesne/pr15e-p4-work/phase3 \
  --stage p4 --out "$PWD/target/pr15e-b1/p4" --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /home/yduchesne/pr15e-p4-work/phase4 \
  --stage p4 --out "$PWD/target/pr15e-b1/p4" --idle-confirmed
```

The runner refuses a missing attestation, a non-`clear` probe, mismatched corpus/host/lane
sets or trial counts, a reversed arm order, a non-`df9b856` arm A, and an arm B that does
not descend from `b7a9def`.
