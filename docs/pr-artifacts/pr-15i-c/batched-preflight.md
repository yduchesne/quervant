# PR 15I-C batched-noise follow-up — preflight

Status: `PREFLIGHT_COMPLETE`
Recorded: 2026-11-08

## 1. Repository and identities

| Item | Value |
|---|---|
| Branch | `dev/pr15i-c-postings` |
| HEAD at start (`BRANCH_START`) | `60344aba822e93bb64fe16b95805d9478b7b0100` |
| `origin/main` (`BASE`) | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` (merged PR #90) |
| Historical rejected physical candidate (`OLD_C`) | `395e05c629c5929f0164764c51c5a1b60b8acd1c` |
| Historical generic out-of-line control (`OLD_G`) | `50b56e9fe7b22bb266ca7b0d9e209500dfc785ff` |
| Working tree | clean |

```
git merge-base --is-ancestor BASE HEAD            -> 0
git merge-base --is-ancestor BRANCH_START HEAD    -> 0
git cat-file -e {BASE,BRANCH_START,OLD_C,OLD_G}^{commit}  -> all present
git diff --quiet BASE HEAD -- crates/quervant-core/src crates/quervant-core/Cargo.toml \
  Cargo.lock benchmarks/pr15d benchmarks/pr15i_a benchmarks/pr15i_b .github/workflows/ci.yml
  -> empty
```

## 2. Frozen fixtures and toolchain

| Item | Value |
|---|---|
| `benchmarks/pr15i_c/protocol.json` (frozen acceptance) | `5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e` |
| `benchmarks/pr15i_c/noise_protocol_v2.json` (read-only history) | `f99ecce69db5815ac798aed826c8c9e0e11ab75a1c68840f3e887488fcd8203d` |
| Frozen PR15D adapter `src/main.rs` blob at `BASE` | `42d2858ec406aa01b2556504a07907e1b2bc9891d596c684b1a9ba99ede78a63` |
| Frozen corpus manifest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| `rustc` / `cargo` / MSRV | `1.98.1` / `1.98.1` / `1.85.0` |
| `python3` | 3.12.3 |
| CPUs allowed by the cgroup/cpuset | `0..11` (12) |
| `taskset` | `/usr/bin/taskset` (util-linux 2.39.3), pinning probe succeeds |
| Native filesystem | `ext4` |
| Container runtime | absent → `REAL_RUSTFS_BLOCKED` |

Predeclared CPU affinity for the whole series (`NC-D91`): `PINNED`, adapter on
logical CPU 0, controller on logical CPU 1; frequency/governor files recorded as
observations only (never modified).

## 3. Source symbol verification

| Symbol | Location | Verified |
|---|---|---|
| `UnifiedSearcher::search_impl` | `search/unified.rs:408` at `BASE` | yes |
| `UnifiedSearcher::execute_unified` | `search/unified.rs:439` at `BASE` | yes |
| `UnifiedSearcher::collect_mixed` | `search/unified.rs:571` at `BASE`, body SHA `00c5a1c8…`, no inline attribute | yes |
| `UnifiedSearcher::exact_term_physical_eligible` | `search/unified.rs:582` at `OLD_C` | yes |
| `execute::for_each_exact_term_score_with` | `search/execute.rs:2157` at `OLD_C` | yes |
| `consider_borrowed_keyword_candidate` | `search/unified.rs:1454` at `OLD_C` | yes |
| Frozen adapter `QuerySession`, `search`, `handle_query` | `benchmarks/pr15d/adapters/quervant/src/main.rs` at `BASE` | pinned by blob SHA and per-function normalized hashes in the patcher |

Harness CLIs verified from source: `run.py`/`verify.py`
(`--checkout-root --baseline-sha --candidate-sha --out [--idle-confirmed]` /
`--checkout-root --campaign [--verify-only] [--no-receipt]`), unchanged.

## 4. Baseline targeted QA

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 check --locked -p quervant-core` | PASS |
| `cargo test --locked -p quervant-core --lib search::unified` | 52 passed |
| `cargo test --locked -p quervant-core --lib search::execute` | 40 passed |
| `python3 -m unittest discover -s benchmarks/pr15i_c` | 150 passed (pre-tooling) |
| `python3 -m unittest discover -s benchmarks/pr15d/harness` | 139 passed |
| `bash benchmarks/scripts/test-scripts.sh` | 108 passed |
| `git diff --check` | clean |

Known historical exception: `benchmarks/pr15i_a::RealCampaignTests` 1F/3E,
reproduced at merged `BASE` with the same raw data → `SOURCE_BOUND_HISTORICAL_ONLY`
(`NC-D12`, `NC-D14`, `NC-D80`), not edited and not counted green.

## 5. Admitted evidence gap (declared, not resolved)

The earlier PR 15I-C report admitted that a synthetic `InvalidScore` (`df > n`)
fixture needs a test-only constructor inside `search/score.rs`. This plan (§5.6)
authorises exactly one `#[cfg(test)]` helper; it is **not** yet present, so the gap
remains open until P3 implements it. It is not described as resolved here.

## 6. Next transition

`PREFLIGHT_COMPLETE` → P1-A: author, test and commit the batched diagnostic
protocol, derived-adapter patcher, controller, independent verifier and the
B-V adversarial matrix **before** the first sample (`NC-D17`).
