# PR 15E Phase 5 — targeted performance qualification

**Status: `P5_PERF_MEASURED_REVIEW_PENDING`** — independent phase review pending. No Phase 6
work and no merge were performed.

Sanitized machine-readable summary:
`benchmarks/reports/pr15e-b1/phase5-targeted-comparison.json`. Raw samples, build logs, index
digests, host details and the attestation stay private under `target/pr15e-b1/p5/`.

## 1. Identity and parity

| Item | Value |
|---|---|
| Arm A — accepted Phase 4 anchor | `784c1af8fd3a7d69978c4214fcef3b1464cb63ec` (pinned predecessor) |
| Arm B — Phase 5 | `66b266fd8850c90836d4327700f279a2ed2c4b92` (descendant; Rust tree identical to code SHA `9881789`) |
| Tooling revision | `66b266fd8850c90836d4327700f279a2ed2c4b92` |
| Release adapter SHA-256 | A `8ac4383f4cd8…` · B `75b0f9b71213…` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` (both arms) |
| Host fingerprint | identical both arms (`4f971362f029…`) |
| Trials / samples | 3 / 20 per lane, 9 lanes, both arms |
| Contention probes | 54/54 `clear` (before and after every trial) |
| Oracle | untimed per lane + `validate_query_response` on every sample, both arms: PASS |
| `total_hits` parity | identical for every lane across arms |

Idle provenance: the maintainer's Phase 5 instruction authorized assuming the host idle; the
flag is recorded as provenance, not as an observed fact, and the runner's real before/after
contention probes remained mandatory.

## 2. Results — ratio = Phase 5 median / Phase 4 median

| Lane | Arm A median | Arm B median | ratio | paired trial ratios | verdict |
|---|---:|---:|---:|---|---|
| `n100000/rare/k100` (**primary**) | 31 543 914 ns | 24 277 715 ns | 0.770 | 0.775, 0.782, 0.753 | **B_FASTER** |
| `n100000/rare/k10` | 31 560 631 ns | 23 795 771 ns | 0.754 | 0.752, 0.767, 0.752 | **B_FASTER** |
| `n10000/rare/k100` | 3 228 675 ns | 2 359 052 ns | 0.731 | 0.715, 0.799, 0.730 | **B_FASTER** |
| `n100000/absent/k100` | 1 077 951 ns | 1 078 398 ns | 1.000 | 0.955, 1.000, 1.076 | INCONCLUSIVE |
| `n10000/absent/k100` | 134 926 ns | 122 850 ns | 0.910 | 0.895, 0.895, 1.021 | INCONCLUSIVE |
| `n100000/medium/k100` | 42 569 043 ns | 41 432 916 ns | 0.973 | 0.978, 0.974, 0.962 | **B_FASTER** |
| `n100000/common/k100` | 73 280 188 ns | 72 814 394 ns | 0.994 | 0.997, 0.986, 0.996 | **B_FASTER** |
| `n100000/common/k10` | 61 930 859 ns | 60 785 888 ns | 0.982 | 0.979, 0.984, 0.978 | **B_FASTER** |
| `n10000/common/k100` | 6 985 240 ns | 6 808 424 ns | 0.975 | 0.958, 0.980, 0.951 | **B_FASTER** |

| Lane | A trial medians (ns) | B trial medians (ns) |
|---|---|---|
| `n100000/rare/k100` | 31 762 713 · 31 061 191 · 31 543 914 | 24 620 127 · 24 277 715 · 23 747 102 |
| `n100000/rare/k10` | 32 488 155 · 31 022 210 · 31 560 631 | 24 438 137 · 23 795 771 · 23 737 984 |
| `n10000/rare/k100` | 3 228 675 · 3 009 007 · 3 232 274 | 2 309 513 · 2 403 602 · 2 359 052 |
| `n100000/absent/k100` | 1 115 071 · 1 077 951 · 1 065 757 | 1 064 597 · 1 078 398 · 1 146 927 |
| `n10000/absent/k100` | 138 251 · 134 926 · 120 334 | 123 736 · 120 811 · 122 850 |
| `n100000/medium/k100` | 43 571 234 · 42 529 585 · 42 569 043 | 42 628 003 · 41 432 916 · 40 959 920 |
| `n100000/common/k100` | 73 907 838 · 73 280 188 · 73 086 191 | 73 675 743 · 72 244 240 · 72 814 394 |
| `n100000/common/k10` | 62 628 913 · 61 752 000 · 61 930 859 | 61 313 630 · 60 785 888 · 60 544 713 |
| `n10000/common/k100` | 6 985 240 · 6 946 851 · 7 226 892 | 6 691 750 · 6 808 424 · 6 871 064 |

**Primary lane `B_FASTER`** (every paired trial ratio < 1). **No lane is `A_FASTER`.** Two
no-hit controls are `INCONCLUSIVE` and are reported as such.

Percentiles (median of the three per-trial percentiles, ns):

| Lane | A p95 | A p99 | B p95 | B p99 |
|---|---:|---:|---:|---:|
| `100K/rare/k100` | 33 657 642 | 34 214 269 | 24 721 770 | 25 294 569 |
| `100K/rare/k10` | 32 705 806 | 33 085 831 | 24 628 340 | 25 005 447 |
| `10K/rare/k100` | 3 413 659 | 3 435 621 | 2 483 569 | 2 579 162 |
| `100K/absent/k100` | 1 223 278 | 1 312 419 | 1 324 128 | 1 460 414 |
| `10K/absent/k100` | 150 674 | 188 850 | 138 541 | 189 226 |
| `100K/medium/k100` | 44 890 661 | 45 985 816 | 42 489 010 | 43 374 661 |
| `100K/common/k100` | 74 799 281 | 75 365 869 | 73 832 617 | 75 218 682 |
| `100K/common/k10` | 63 539 756 | 64 575 128 | 63 984 121 | 64 219 889 |
| `10K/common/k100` | 7 502 056 | 7 750 472 | 7 280 450 | 7 628 028 |

## 3. Reading the result

* The **primary** singleton lane improves from ~31.54 ms to ~24.28 ms (ratio **0.770**), and
  the top-K and 10K scaling controls track it (0.754 and 0.731). These are the only lanes
  that take the selective key path, so the improvement is attributable to removing the
  full-segment key materialization for a one-hit query.
* The **no-hit controls** decode no keys at all and are `INCONCLUSIVE` (100K: ratios 0.955 /
  1.000 / 1.076; 10K: 0.895 / 0.895 / 1.021) — no systematic change in the untouched
  zero-hit path.
* The multi-hit lanes (`medium`, `common`, `common/k10`, 10K `common`) use the unchanged
  full-key cache path. Their small consistent differences (0.973–0.994) are **not**
  attributed to Phase 5 and are best read as build/layout noise: the optimization does not
  execute on those lanes.
* Percentiles for every lane are in the JSON report; the primary lane moves from ~33.66 ms
  p95 / 34.21 ms p99 to ~24.72 ms p95 / 25.29 ms p99.

## 4. Historical context (cross-session, not paired)

Phase 4 same-host campaign (different session): primary 32.85 → 32.15 ms; Phase 3: 78.65 →
32.17 ms; original PR15D `main` figures from a third session. None of these are used as
Phase 5 paired ratios or in the verdict.

## 5. Limits

* Only segments with exactly one selected hit and ≥ 1,024 physical documents take the fast
  path; all scoring, sorting, cursor, projection, batch and work/memory semantics are
  unchanged, and validation is still O(segment docs) encoded bytes.
* Synthetic exact-term `FsDirectory` workload; says nothing about BM25 ranking quality,
  remote-latency execution or distributed search.
* In-process adapter samples include JSON transport but exclude build and index creation.
* Wall-clock `engine_ns` only; no CPU or allocation measurement was performed, so this
  campaign does not quantify the key-allocation reduction itself.
* Single host, single session, trial-paired; not a cross-host or production-p99 claim.

## 6. Reproduction

```sh
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /home/yduchesne/pr15e-p5-work/phase4 \
  --stage p5 --out "$PWD/target/pr15e-b1/p5" --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /home/yduchesne/pr15e-p5-work/phase5 \
  --stage p5 --out "$PWD/target/pr15e-b1/p5" --idle-confirmed
```

The runner refuses a missing attestation, a non-`clear` probe, mismatched corpus/host/lane
sets or trial counts, a reversed arm order, a non-`784c1af` arm A, and an arm B that does not
descend from the anchor.
