# PR 15C-B qualified measurement — provenance and results

Status: **QUALIFIED.** Both sides produced three independently qualified trials on
the same host with identical tooling. This is the first `QUALIFIED` before/after
assessment for PR 15C-B; the earlier diagnostic series
(`docs/pr-artifacts/pr-15c-b/trials/`, `comparison.md`) remains `UNQUALIFIED` and
is **not** reclassified.

Machine-readable results: `benchmarks/reports/pr15c-b/pr15c-b-qualified-comparison.json`.
Rendered report (tool output, unmodified): `comparison-qualified.md`.
Source-locked inputs: `benchmarks/reports/pr15c-b/{before,after}/`.

## 1. Measured sources

The benchmark runner refuses an uncommitted worktree and records `git rev-parse
HEAD`, so the identical A-R2 tooling patch had to be committed in each measured
worktree. The measured SHAs are therefore *engine commit + tooling commit*; the
engine identity is carried by the `crates/` subtree.

| | Before | After |
|---|---|---|
| Measured SHA (recorded by the runner) | `f7d6be721ba625cbd90f24cfbcd8551cc8ba309a` | `04ad3509c86d08fe296adde1d67c19aa7c7f2651` |
| Engine commit | `42b19445dd79a90d8701b4306e305c6e4e44cd57` | `b4682d0fdebaa691b55bb29b32f3499781a8fc04` |
| Tooling commit (same patch, same message) | `f7d6be7` | `04ad350` |
| `crates/` subtree | `5bfc61840498053a2f875c1416867c47cd83cb23` | `ad1a756c0ebc89344b55573da1fe00b7812c8ae9` |
| Same subtree at the engine commit | `git rev-parse 42b1944:crates` = `5bfc6184…` ✅ | `git rev-parse b4682d0:crates` = `ad1a756c…` ✅ |

Proof that the tooling patch changes no benchmark, workload or engine input:

```text
$ git diff --stat f7d6be7 04ad350 -- benchmarks crates/quervant-core/benches \
    crates/quervant-core/examples Cargo.toml Cargo.lock
(empty)
```

The only differences between the two measured commits are `crates/` (the PR 15C-A
engine change + the FST test-only fix) and `docs/pr-artifacts/pr-15c-a/` +
`docs/architecture/`. No workload, lane, corpus, oracle, digest, Criterion
setting, manifest or lockfile differs.

### Identical tooling (rule X24 satisfied)

`benchmarks/scripts/` is byte-identical in both worktrees:

| File | SHA-256 (both worktrees) |
|---|---|
| `validate-pr15b.py` | `035114504116d335b95795700559f025a838bf1ad5946cc9b826ffa1279b80cc` |
| `run-pr15b.sh` | `40bca3139d7e9f8116d1dc2c64dba3bbee52fdcdbca9d35001f2cb75bec71a9e` |
| `pr15cb-profiler-evidence.py` | `1d9c55522ebf20ae14126c707a36a34c42df1f39e649f4b050e1a67021f74c8f` |
| `profile-pr15b.sh` (frozen, unmodified) | `72a8e607a630e398fd9bed69deac3c08851e486723dc6d73097228149b1526f9` |
| `test-scripts.sh` | `3f6015df4375ae2c0de1837c4ec548adcd6b718ae52bc0df3782aedbaf5e2434` |
| `compare-pr15c-b.py` | `f6ff371d3f5e8769df8955126ec9592642ed68cd2e48e711608a5702a4729e50` |

## 2. Operator attestation and contention

- **Operator idle attestation supplied by the human operator**: "I confirm that no
  competing benchmark workloads are running on the measurement host." The runner
  was therefore invoked with `--idle-confirmed`; the agent did not supply the
  attestation itself and did not use `--allow-contended`.
- The automated contention detector ran **pre / post / final** for every trial:
  **18/18 samples `clear`** (0 competing processes, CPU busy fraction ≤ 0.005 on
  the pre-series probe).
- Both series ran sequentially, one benchmark process at a time, order **A then B**
  fixed before measurement.

## 3. Environment (identical on both sides, verified by the comparator)

`Intel(R) Core(TM) i7-10750H @ 2.60 GHz`, 12 logical CPUs, `MemTotal 32774784 kB`,
`Linux 6.18.33.2-microsoft-standard-WSL2 … x86_64` (WSL2 = true), `ext4`,
`cargo 1.98.1 (797e8a9bc 2026-08-05)`, `criterion 0.7.0`.
Workload `pr15b_v1`, canonical fixture
`104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087`, 30/30 lanes.

## 4. Commands

```sh
# tooling-only commit applied identically in each worktree, then pre-built
cargo bench -p quervant-core --bench unified_diagnostics --no-run
CARGO_PROFILE_RELEASE_DEBUG=1 cargo build --release \
    -p quervant-core --example pr15b_profile      # profiling driver, outside timing

# series A (before) 00:10:28Z → 00:31:52Z, exit 0
bash benchmarks/scripts/run-pr15b.sh --trials 3 --idle-confirmed
# series B (after)  00:31:55Z → 00:49:21Z, exit 0
bash benchmarks/scripts/run-pr15b.sh --trials 3 --idle-confirmed

# strict comparison, exit 0
python3 benchmarks/scripts/compare-pr15c-b.py compare \
  --before  <before>/pr15b-qualified.json --after <after>/pr15b-qualified.json \
  --before-trial <before>/trial-{1,2,3}/trial.json \
  --after-trial  <after>/trial-{1,2,3}/trial.json \
  --expected-before-sha f7d6be721ba625cbd90f24cfbcd8551cc8ba309a \
  --expected-after-sha  04ad3509c86d08fe296adde1d67c19aa7c7f2651 \
  --out-json benchmarks/reports/pr15c-b/pr15c-b-qualified-comparison.json \
  --out-md   docs/pr-artifacts/pr-15c-b/comparison-qualified.md
```

Both aggregates were re-derived independently with
`validate-pr15b.py aggregate` from the six source trial manifests and were
**byte-identical** to the runner's output.

## 5. Profiler evidence (A-R2)

`profiler_status = AVAILABLE` in all six trials, and every trial carries a
`profiler_evidence` record that the runner wrote **and independently re-verified**
(regular non-symlink file, positive size, recomputed SHA-256) before passing it on:

| Side | Trial | Timestamp (UTC) | Tool | Version | Artifact | Size (B) | SHA-256 (prefix) |
|---|---|---|---|---|---|---|---|
| before | 1 | 2026-10-30T00:17:39Z | heaptrack | 1.5.0 | `profiler/heaptrack.gz` | 2 053 823 | `ca7a99a89913…` |
| before | 2 | 2026-10-30T00:24:50Z | heaptrack | 1.5.0 | `profiler/heaptrack.gz` | 2 071 912 | `35a3d33f29de…` |
| before | 3 | 2026-10-30T00:31:52Z | heaptrack | 1.5.0 | `profiler/heaptrack.gz` | 2 158 512 | `d7b6f44cbcee…` |
| after | 1 | 2026-10-30T00:37:44Z | heaptrack | 1.5.0 | `profiler/heaptrack.gz` | 3 022 357 | `caeb34057071…` |
| after | 2 | 2026-10-30T00:43:33Z | heaptrack | 1.5.0 | `profiler/heaptrack.gz` | 3 062 429 | `712a8ea315b8…` |
| after | 3 | 2026-10-30T00:49:21Z | heaptrack | 1.5.0 | `profiler/heaptrack.gz` | 3 084 027 | `dce2d8218aac…` |

`perf` was attempted first in every trial and **genuinely failed** (exit 2:
`/usr/bin/perf` is the distro wrapper and cannot find a kernel-matched binary for
`6.18.33.2-microsoft`). No `PATH`, kernel, package or privilege change was made;
the runner therefore used the documented `heaptrack` fallback. The evidence records
are published under `benchmarks/reports/pr15c-b/{before,after}/evidence-trial-*.json`
as references to the raw artifacts (which stay untracked under `target/`).

## 6. Result

`13` lanes classified `IMPROVEMENT`, `0` `REGRESSION`, `17` `INCONCLUSIVE`
(the predeclared dispersion heuristic), of 30. **No lane regressed.**

| group | lanes | speedup median | min | max |
|---|---:|---:|---:|---:|
| U01/U02 no/rare hits | 6 | 26.054 | 9.360 | 64.247 |
| U03/U04 lexical mixed | 6 | 4.879 | 1.814 | 5.744 |
| U05–U10 typed/JSON/sort/projection/aggregation/batch | 9 | 4.965 | 2.027 | 7.736 |
| U11 segment topology | 6 | 6.548 | 2.911 | 16.165 |
| U12 PIT pages | 2 | 5.065 | 4.971 | 5.160 |
| U13 geo | 1 | 5.759 | 5.759 | 5.759 |

Smallest effect in the whole series: `u04/n100000/common-mixed` at **1.81×**
(−44.9 %). Largest: `u01/n100000/absent` at **64.2×** (−98.4 %). The pattern is
exactly the mechanism PR 15C-A removes: the `absent`/`rare` lanes are dominated by
per-acquisition segment verification, while the selective lexical lanes are
dominated by residual postings traversal and scoring.

### Why 17 lanes are `INCONCLUSIVE` (and why that is not a contradiction)

The comparator's predeclared heuristic marks a lane `INCONCLUSIVE` when any
per-side trial-median spread exceeds 1.10×, when the before/after trial-median
ranges overlap, or when `|delta_pct| < 3 %`. In this series the **before** side
alone had spreads up to 1.205× (`u09`, `u10`) and 1.165× (`u06`, `u07`/k1000) —
WSL2 frequency/thermal variation across a 21-minute series with only three
medians per side. Every one of those lanes still shows a 2×–64× improvement; none
is anywhere near the 3 % floor and none regressed. The label therefore means
"the predeclared noise bound cannot separate trial-to-trial spread from the
effect", **not** "no effect". No statistical-significance claim is made anywhere.

## 7. Comparison with the earlier diagnostic series (context only)

The earlier unqualified series (`comparison.md`, engine SHAs `42b1944`/`b4682d0`,
no profiler evidence, no attestation) produced the same qualitative picture with
tighter dispersion (all 30 lanes `IMPROVEMENT`). Absolute medians differ by
roughly +10 % on the before side between sessions, which is normal for this host
and is why cross-session absolute latencies are never used as a denominator. Only
the same-series ratio is reported.

## 8. Limits

- Microbenchmark iteration medians of three independent trials, not production
  request p95/p99, not an SLA, not extrapolable off this host.
- `perf` attribution was impossible on this host; `heaptrack` is the evidence
  source. Causal attribution for this PR comes from the earlier untimed `perf`
  profile recorded in `diagnostics.md` (which used a version-mismatched `perf`
  binary via a shim) and must be read as instrumented context, not as a qualified
  timing.
- Every trial's profiler capture runs *between* trials, starting only after the
  Criterion process exits and after the final contention sample. It cannot enter a
  timed region, but it does briefly warm the page cache before the next trial.
- No reverse-order paired series was run; the A→B order was fixed before
  measurement and is recorded here.
