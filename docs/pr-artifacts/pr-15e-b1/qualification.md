# PR 15E-B1 — performance qualification

**Status: `PERF_BLOCKED_OPERATOR`.** No timed measurement was executed, because the
mandatory operator idle confirmation (`--idle-confirmed`) was not available to this
coding agent. The agent is forbidden from generating that attestation, so no
`MEASURED` claim, ratio, speedup or regression verdict is reported here.

This document records (a) what *was* verified without timing, (b) exactly which
commands produce the qualified comparison, and (c) the limitations that must travel
with any future result.

## 1. Source and tooling identity

| Item | Value |
|---|---|
| Starting `main` (arm A for `b1a`/`final`) | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` |
| B1a commit (arm A for `b1b`) | `601765fbc253cf9db3a2bfb5d594156eecb35f51` |
| B1b commit (arm B for `b1b`/`final`) | `79218187390487eea0ced5e193147c15cd5a1e2a` |
| Tooling revision (runner + frozen imports) | `79218187390487eea0ced5e193147c15cd5a1e2a` |
| Runner | `benchmarks/pr15e_b1/run_targeted.py` |
| Measured engine | frozen PR15D Quervant adapter only |
| Corpus | regenerated from the frozen PR15D model, verified by `oracle.load_and_verify` |
| Corpus manifest SHA-256 (this tooling) | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Frozen PR15D artefacts | pinned by SHA-256 inside the runner and verified in both trees |

## 2. Untimed preflight that WAS executed

A dry-run invoked the runner's own functions (not the CLI) in
`target/pr15e-b1/preflight/` to prove the pipeline works for the operator. It
performed **no timing** and makes no performance claim.

| Step | Result |
|---|---|
| `resolve_source_tree` on the B1b worktree | clean, SHA `7921818…`, commit time read |
| `resolve_source_tree` on the baseline worktree | clean, SHA `c3083d8…` |
| `verify_frozen_files` (tooling, B1b, baseline) | PASS — all 7 pinned artefacts match |
| `require_native_filesystem` | `ext4` |
| `build_adapter` (`cargo build --release --locked`) | PASS, binary SHA-256 `55afa340db74b8803407714965f5a7b9c1e695400b306b06dc6d629e92d6710d` |
| `prepare_corpus` (frozen generator + verification) | PASS, manifest above |
| `build_indices` (n=10000, n=100000) | PASS, index digests `595b7783…` / `fd60b53f…` |
| `read_adapter_metadata` | `engine=quervant`, `analyzer=keyword-exact`, `index_backend=FsDirectory` |
| untimed oracle check, all 6 `b1a` lanes | PASS — `total_hits` 0 / 1 / 12500 / 49999 (n=100000) and 0 / 4999 (n=10000) |

This validates source resolution, frozen-hash guards, adapter build, corpus
generation/verification, index construction, adapter metadata and per-lane oracle
agreement. It does **not** validate any latency number.

## 3. Fixed measurement design (pre-registered, not yet run)

* `regime=warm`, 5 warmups + 20 measured samples per lane, real `FsDirectory`,
  independent oracle, one production adapter.
* 3 independent trials per compared commit; contention probe before **and** after
  every trial; non-`clear` ⇒ blocked, never downgraded.
* Identical immutable index bytes reused across the three trials of a source, with a
  digest re-checked before each trial.
* Build and index construction are outside every timed region.

| Stage | Lanes | Cheap arm A → arm B |
|---|---|---|
| `b1a` | `n100000/{absent,rare,medium,common}/k100`, `n10000/{absent,common}/k100` | `c3083d8` → `601765f` |
| `b1b` | `n100000/{medium,common,absent,rare}/k100`, `n10000/common/k100` | `601765f` → `7921818` |
| `final` | `n10000/{absent,rare,medium,common}/k100`, `n100000/{absent,rare,medium,common}/k100`, `n100000/common/k10` | `c3083d8` → `7921818` |

## 4. Exact commands required to complete qualification

Each measured commit needs its own clean worktree with its own Cargo target dir.
`<checkout>` is this repository; `--out` is the per-stage root.

```sh
# --- stage b1a: original main vs B1a ---
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /abs/worktrees/b1-baseline  --stage b1a \
  --out /abs/checkout/target/pr15e-b1/b1a --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /abs/worktrees/b1-b1a       --stage b1a \
  --out /abs/checkout/target/pr15e-b1/b1a --idle-confirmed

# --- stage b1b: B1a vs B1b ---
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /abs/worktrees/b1-b1a       --stage b1b \
  --out /abs/checkout/target/pr15e-b1/b1b --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /abs/worktrees/b1-b1b       --stage b1b \
  --out /abs/checkout/target/pr15e-b1/b1b --idle-confirmed

# --- stage final: original main vs B1b (9 lanes) ---
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /abs/worktrees/b1-baseline  --stage final \
  --out /abs/checkout/target/pr15e-b1/final --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /abs/worktrees/b1-b1b       --stage final \
  --out /abs/checkout/target/pr15e-b1/final --idle-confirmed
```

After each stage's second run, `<out>/comparison.json` and `<out>/comparison.md`
are published automatically. The private raw samples stay under
`<out>/runs/<source-sha>/<run-id>/` (inside the gitignored `target/` tree); only a
sanitized summary may be written into this directory.

## 5. Reporting rules already fixed

* Per lane: median-of-trial-medians, ratio B/A, the three paired trial ratios,
  trial dispersion, `n`/`class`/`k`/`regime`, oracle hits, source SHAs, tooling SHA,
  binary digest, corpus manifest SHA, host fingerprint.
* Verdict = sign consistency only (`B_FASTER` if all paired ratios `< 1.0`,
  `A_FASTER` if all `> 1.0`, otherwise `INCONCLUSIVE`). **No minimum speedup
  percentage exists.**
* A credible regression (`A_FASTER`) or an ambiguous lane is reported as such and
  escalated for human disposition; it is never averaged away or hidden.
* No comparison across hosts, corpora, lane sets or trial counts.

## 6. Limitations that must travel with any result

* In-process adapter samples include JSON transport but exclude build/index creation.
* Trial pairing is by trial index on one host; medians are not pooled across hosts.
* `engine_ns` is wall-clock only; CPU counters and allocations were not measured for
  B1 (no new `perf`/Heaptrack campaign was authorized or required).
* The workload is a synthetic exact-term `FsDirectory` lane; it says nothing about
  BM25-scored ranking, RustFS-backed indexes or distributed search.
* PR15E-A's samples remain process samples and cumulative allocation traffic, not
  wall-time baselines; they are not used as a B1 baseline.

## 7. What is deliberately NOT claimed

* `B1a_MEASURED`, `B1b_MEASURED`, `REVIEW_READY` performance acceptance.
* Any statement that B1a/B1b are faster, slower or neutral in wall time.
* Any comparison against Lucene or Tantivy.
