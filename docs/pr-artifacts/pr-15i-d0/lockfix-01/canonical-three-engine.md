# PR 15I-D0 lockfix-01 — canonical three-engine campaign

**Status: `QUALIFIED`.** The unmodified PR 15D harness ran on `COMPAT_BASE`
(`a53ee021acbe5f30db2b3298a11fcd99e72c2945`) and its own validator returned
`{"status": "QUALIFIED", "errors": 0}`.

## 1. Run identity

| Item | Value |
|---|---|
| Source SHA | `a53ee021acbe5f30db2b3298a11fcd99e72c2945` |
| Workload | `pr15d_v1` |
| Corpus manifest | `69052c66…` (unchanged) |
| Engines | Quervant, Tantivy 0.22.1, Lucene 9.12.3 |
| Trials | 3 × 20 samples per lane |
| All 9 engine-trials qualified | yes |
| Contention probes | 54 / 54 `clear` |
| Host fingerprint | `4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f` |
| Filesystem | native `ext4` |
| Validator | `QUALIFIED`, 0 errors |
| Aggregator | exit 0 |
| Performance threshold failure | `False` (no threshold) |
| Score comparison | `NOT_APPLICABLE` |
| Scored lane | `SEMANTICALLY_NONCOMPARABLE` |

## 2. Exact-term latency

Median of three trial medians. `(I)` is the aggregate's honest
`INCONCLUSIVE` marker (trial dispersion > 1.10 or overlapping trial medians);
it is not a pass. Ratios carry no significance claim.

| Lane | Regime | Quervant ns | Tantivy ns | Lucene ns | Q/T | Q/L |
|---|---|---:|---:|---:|---:|---:|
| 10K absent K10 | process_cold | 12,653,797 | 47,901 | 19,427,111 | 264.166 (I) | 0.651 |
| 10K absent K10 | warm | 43,101 | 14,100 | 323,305 | 3.057 (I) | 0.133 |
| 10K absent K100 | process_cold | 12,645,697 | 44,800 | 20,459,827 | 282.270 (I) | 0.618 (I) |
| 10K absent K100 | warm | 44,201 | 12,200 | 329,905 | 3.623 (I) | 0.134 (I) |
| 10K common K10 | process_cold | 19,030,210 | 151,502 | 36,691,980 | 125.610 (I) | 0.519 |
| 10K common K10 | warm | 3,678,658 | 84,401 | 1,724,326 | 43.585 (I) | 2.133 (I) |
| 10K common K100 | process_cold | 20,752,223 | 253,404 | 57,403,526 | 81.894 (I) | 0.362 |
| 10K common K100 | warm | 4,464,073 | 137,902 | 3,570,757 | 32.371 | 1.250 (I) |
| 10K medium K10 | process_cold | 17,207,875 | 84,402 | 37,130,600 | 203.880 (I) | 0.463 |
| 10K medium K10 | warm | 1,639,525 | 36,201 | 1,421,923 | 45.289 | 1.153 (I) |
| 10K medium K100 | process_cold | 17,815,277 | 177,703 | 63,456,231 | 100.253 (I) | 0.281 |
| 10K medium K100 | warm | 2,205,634 | 101,201 | 4,689,175 | 21.795 (I) | 0.470 (I) |
| 10K rare K10 | process_cold | 15,758,546 | 47,900 | 28,088,051 | 328.988 (I) | 0.561 |
| 10K rare K10 | warm | 59,801 | 13,400 | 789,513 | 4.463 (I) | 0.076 (I) |
| 10K rare K100 | process_cold | 15,846,147 | 54,301 | 28,304,546 | 291.821 (I) | 0.560 |
| 10K rare K100 | warm | 54,301 | 14,800 | 737,712 | 3.669 | 0.074 (I) |
| 100K absent K10 | process_cold | 128,320,843 | 63,801 | 19,726,527 | 2011.267 (I) | 6.505 |
| 100K absent K10 | warm | 259,604 | 16,200 | 381,106 | 16.025 | 0.681 (I) |
| 100K absent K100 | process_cold | 128,628,438 | 73,001 | 19,873,118 | 1762.009 (I) | 6.472 |
| 100K absent K100 | warm | 263,104 | 16,501 | 402,506 | 15.945 (I) | 0.654 (I) |
| 100K common K10 | process_cold | 193,337,759 | 761,012 | 37,226,606 | 254.053 (I) | 5.194 |
| 100K common K10 | warm | 37,007,290 | 624,810 | 2,117,934 | 59.230 (I) | 17.473 (I) |
| 100K common K100 | process_cold | 204,232,260 | 857,214 | 58,150,917 | 238.251 (I) | 3.512 |
| 100K common K100 | warm | 48,546,579 | 670,710 | 3,581,257 | 72.381 | 13.556 (I) |
| 100K medium K10 | process_cold | 174,011,190 | 309,805 | 37,892,704 | 561.680 (I) | 4.592 |
| 100K medium K10 | warm | 17,069,872 | 175,802 | 1,687,626 | 97.097 | 10.115 (I) |
| 100K medium K100 | process_cold | 176,344,764 | 441,707 | 68,833,102 | 399.235 (I) | 2.562 |
| 100K medium K100 | warm | 20,117,238 | 245,304 | 4,892,277 | 82.009 | 4.112 |
| 100K rare K10 | process_cold | 156,498,206 | 90,901 | 28,675,655 | 1721.633 (I) | 5.458 |
| 100K rare K10 | warm | 263,904 | 19,500 | 706,712 | 13.534 (I) | 0.373 (I) |
| 100K rare K100 | process_cold | 156,953,212 | 83,601 | 28,861,260 | 1877.408 (I) | 5.438 |
| 100K rare K100 | warm | 265,704 | 20,500 | 815,113 | 12.961 (I) | 0.326 (I) |

## 3. Indexing, commit, reopen and size

| Engine | N | index_ns | commit_ns | reopen_ns | index_bytes | segments |
|---|---:|---:|---:|---:|---:|---:|
| Quervant | 10,000 | 20,604,121 | 140,133,636 | 22,543,260 | 1,560,111 | 1 |
| Quervant | 100,000 | 230,684,241 | 1,365,131,781 | 257,216,796 | 15,747,551 | 1 |
| Tantivy | 10,000 | 541,608 | 177,949,317 | 455,208 | 294,681 | 4 |
| Tantivy | 100,000 | 1,332,128,697 | 63,460,296 | 481,108 | 2,913,057 | 4 |
| Lucene | 10,000 | 173,986,247 | 139,003,194 | 35,044,589 | 186,052 | 1 |
| Lucene | 100,000 | 546,912,203 | 340,448,252 | 28,254,358 | 1,858,642 | 1 |

The Quervant 100K committed index is `15,747,551` bytes, matching the frozen
LZ4 sentinel; the stored section remains `1,661,455` bytes as required by the
paired protocol.

`serial_ops_per_second` (single sustained serial window, not multi-thread QPS):

| Engine | 10K | 100K |
|---|---:|---:|
| Quervant | 496.3462 | 57.406776 |
| Tantivy | 8,487.243842 | 3,181.04646 |
| Lucene | 575.310716 | 559.92687 |

## 4. Comparability caveats (must accompany every ratio)

- The lane is exact keyword membership, exact `total_hits`, ascending `doc_id`.
- Quervant sorts on a `Keyword` column, Tantivy on a numeric `ordinal` fast field
  and Lucene on sorted doc values. Logical ordering is equivalent; physical
  representation and cost are **not**.
- Quervant's unified executor performs positive-term BM25 work in this lane;
  Tantivy's PR 15D adapter uses `TermQuery(..., Basic)` + `Count` + numeric-sort
  `TopDocs`. No BM25 cost parity is claimed.
- `process_cold` is a fresh adapter process with an unopened reader, not an
  OS-cache-cold start.
- `(I)` markers are the aggregate's dispersion/overlap warnings; they are not
  hidden or removed.
- Index byte totals are descriptive and may vary with segment scheduling.
- Historical PR 15I-0 ratios are `NOT_CONTROLLED` and are not this result.

## 5. Evidence (local)

`target/pr15i-d0/lockfix-01/canonical-three-engine-01/` in the clean
`COMPAT_BASE` worktree:

- `run.json` (complete, qualified)
- `trials/trial-{1,2,3}/{quervant,tantivy,lucene}.json`
- `validation.json` → `QUALIFIED`
- `aggregate.json`, `aggregate.md`
- per-trial index, contention and build artifacts

Raw evidence is never committed.
