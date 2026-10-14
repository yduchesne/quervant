# PR 7 Amendment 04 baseline — `quervant-bench-v1`

**Status:** pre-optimization baseline. No competitive comparison; no improvement
claimed. Raw Criterion output is untracked; the machine-readable manifest is
`pr07-amendment04-baseline.json` (validated by `scripts/validate-report.py`).

## Provenance

| Field | Value |
|---|---|
| run_id | `20261014T011531Z-dad2514` |
| git_sha | `dad2514e16698b7a65bb607c10b97a868e7e94e8` (clean tree) |
| timestamp_utc | 2026-10-14T01:15:31Z |
| toolchain | rustc 1.98.1 |
| os/kernel | Linux 6.18.33.2-microsoft-standard-WSL2 x86_64 |
| WSL2 | true |
| CPU | Intel(R) Core(TM) i7-10750H @ 2.60GHz (12 logical CPUs) |
| filesystem | ext4 (native Linux; not `/mnt/c`) |
| memory | ~32,774,780 kB |
| criterion | 0.7.0 (dev-only) |
| fixture | `pr07_amendment04_v1`, seed `0xA404202600000001` |
| dataset digests (4 segments) | 2K `4f5e8d22…`, 10K `e25f456a…`, 100K `e0beb840…` |
| correctness gate | PASS (9/9 `pr07_amendment04`, incl. oracle-negative) |
| profiler_status | **UNAVAILABLE** (`perf`, `cargo-flamegraph`, `heaptrack` not installed) |

## Measured results (warm, preopened committed snapshot, top-K 10 unless noted)

Midpoint of the Criterion confidence interval; full CI bounds are in the JSON.

| Workload | 2,000 docs | 10,000 docs | 100,000 docs |
|---|---:|---:|---:|
| search `term-rare` | 7.58 ms | 34.96 ms | 327.49 ms |
| search `term-common` | 8.04 ms | 49.58 ms | 393.70 ms |
| search `term-medium` | 7.26 ms | – | – |
| search `term-absent` | 7.58 ms | – | – |
| search `and-common-medium` | 7.95 ms | – | – |
| search `or-common-rare` | 8.52 ms | – | – |
| search `phrase-present` | 7.63 ms | 32.77 ms | – |
| search `phrase-repeated` | 7.86 ms | 33.00 ms | – |
| search `match-all` | 5.31 ms | – | – |
| search `pure-negative` | 5.35 ms | – | – |
| search `term-common` top-K 100 | 8.89 ms | – | – |
| postings `cursor_open_plus_decode/ctoken` | 148.7 µs | 716.2 µs | 7.35 ms |
| dictionary `lookup_present/ctoken` | 6.87 ns | 6.58 ns | 6.65 ns |
| dictionary `lookup_absent` | 186.96 ns | 180.73 ns | 185.65 ns |
| `bm25` reference control | 49.6 ns (fixed input set) | | |

Sample counts: 30 for ≤10K, 20 for 100K. Warmup 2 s; measurement 3–6 s. The 1M
extended lane was **not run** and is explicitly out of this baseline.

## Observation vs hypothesis (honest, not a direct attribution)

- At 2K, **every scored term query costs ~7.3–8.5 ms regardless of selectivity**
  (rare and absent are as slow as common), while `MatchAll`/pure-negative queries
  with no scoring fields cost ~5.3 ms (~2.2 ms less). That gap is consistent with
  the unconditional whole-field dictionary/posting scan in `compute_stats`.
- At 100K, rare (327 ms) and common (394 ms) differ by only ~20% despite a ~1000×
  difference in hit count, which is difficult to explain by matching and scoring
  work alone and is consistent with the scan dominating.
- **This is a data-supported hypothesis, not a measured `compute_stats`
  percentage.** `compute_stats` is crate-private and was deliberately not exposed;
  `perf`/flamegraph were unavailable on this WSL2 host, so no symbol-level CPU
  profile could be captured. Profiling is classified **BLOCKED / UNAVAILABLE**,
  not PASS. Amendment 05 (persistent norms/statistics) owns the optimization; this
  baseline is the reference to compare against.

## Reproducing

```sh
bash benchmarks/scripts/run-pr07-baseline.sh
cargo bench -p quervant-core --no-run            # compilation gate
# Profiling requires tools that were unavailable here:
bash benchmarks/scripts/profile-pr07.sh --mode perf --workload rare-100k --out target/pr07-profiles/perf
bash benchmarks/scripts/profile-pr07.sh --mode heaptrack --workload rare-100k --out target/pr07-profiles/heaptrack
```

## Limitations

- Absolute latencies are host-specific and must not be extrapolated.
- Tombstone/deletion lane is NOT APPLICABLE for insert-only PR 7 (PR 9 owns
  mutation). The reader live bitmap is asserted all-true instead.
- No Lucene/Tantivy adapters were run; no cross-engine ratio is claimed.
- Allocation profiling (`heaptrack`) is unavailable; no allocation-count claim is
  made.
