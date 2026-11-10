# PR 15I-C fixup (`15IC-FIXUP-CODEGEN-01`) — preflight and source reconciliation

Status: `BASE_RECONCILED`
Recorded: 2026-11-08

## 1. Repository and identity

| Item | Value |
|---|---|
| Branch | `dev/pr15i-c-postings` |
| Starting HEAD (`PREV_REJECTION_HEAD`) | `a3a502cd3aeea3e2d6d1b2d95eb0baf8d19b79ed` |
| `origin/main` = merged PR #90 (`MERGED_15IB_A_SHA`) | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| Pre-merge content SHA (frozen protocol `baseline_source`) | `f70cde62e709383d82693ad548a8c69c7f772bef` |
| `PREV_C_EXPERIMENT_SHA` | `395e05c629c5929f0164764c51c5a1b60b8acd1c` |
| Rollback commit | `acc10d004e8f963112433e9f7be0aeed0abdd504` |
| Working tree at preflight | clean (`git status --porcelain -uall` empty) |

Checks:

```
git cat-file -t 6f6463cb… -> commit
git cat-file -t 395e05c…  -> commit
git cat-file -t acc10d0…  -> commit
git merge-base --is-ancestor 6f6463cb… HEAD -> 0 (ancestor)
git merge-base --is-ancestor 395e05c…  HEAD -> 0 (ancestor)
git diff --name-status 6f6463cb… HEAD -- crates/quervant-core/src \
  crates/quervant-core/Cargo.toml Cargo.lock .github/workflows/ci.yml \
  benchmarks/pr15d benchmarks/pr15i_a benchmarks/pr15i_b
  -> (empty)
git diff --check -> clean
```

`origin/main` equals `6f6463cb…`; there is no newer main to reconcile
(`FX-D03`). Production, Cargo, lock and CI are byte-identical to merged PR 15I-B,
so `FX-D01` applies and this branch is continued additively (`FX-D05`: no unsafe
commits after `a3a502…`).

## 2. Toolchain, host and frozen fixtures

| Item | Value |
|---|---|
| `rustc --version` | `rustc 1.98.1 (48a229cea 2026-09-01)` |
| `cargo --version` | `cargo 1.98.1 (797e8a9bc 2026-08-05)` |
| `cargo +1.85.0 --version` | `cargo 1.85.0 (d73d2caf9 2024-12-31)` |
| `python3 --version` | `Python 3.12.3` |
| CPU count | 12 |
| Native filesystem | `ext4` (`findmnt -n -o FSTYPE -T .`) |
| Frozen protocol SHA-256 (`benchmarks/pr15i_c/protocol.json`) | `5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e` |
| Frozen corpus manifest SHA-256 (`pr15d-corpus-v1`) | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Diagnostic tools present | `nm`, `objdump`, `perf` (`/usr/bin/…`) |

### Historical negative evidence

`target/pr15i-c/campaigns/paired-01` and
`target/pr15i-c/reviews/paired-01-verification.json` are present locally
(`FX-D11`). They are used **read-only** as the historical comparator; they are
never re-sealed, patched or numerically blended into a new campaign.

## 3. Baseline QA (pre-change)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 check --locked -p quervant-core` | PASS |
| `cargo test --locked -p quervant-core --lib search::unified::phase4_tests` | 8 passed |
| `cargo test --locked -p quervant-core --lib search::unified::b_tests` | 6 passed |
| `cargo test --locked -p quervant-core --lib search::execute::budget_tests` | 40 passed |
| `python3 -m unittest discover -s benchmarks/pr15i_c` | 41 passed (pre-fixup tooling) |
| `python3 -m unittest discover -s benchmarks/pr15d/harness` | 139 passed |
| `bash benchmarks/scripts/test-scripts.sh` | 108 passed, 0 failed |
| `git diff --check` | clean |

### Historical source-bound classification (`FX-D17`)

`python3 -m unittest discover -s benchmarks/pr15i_a` → 87 tests,
`FAILED (failures=1, errors=3)`, all in
`test_verify.RealCampaignTests` (`test_ft_a49/a50/a51/a53`). Identical to the
result previously reproduced on a clean checkout of the merged base; these tests
assert that `main`'s production tree equals the historical PR15I-A measured
source, so they are `SOURCE_BOUND_HISTORICAL_ONLY` and are neither edited nor
counted as PR 15I-C evidence.

## 4. Pre-existing source facts used by this fixup

| Symbol | Location | Verified |
|---|---|---|
| `UnifiedSearcher::collect_mixed` | `search/unified.rs:571` (pre-change) | body SHA-256 `00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994` at `6f6463cb…` |
| `UnifiedSearcher::execute_unified` call site | `search/unified.rs:474` | single `self.collect_mixed(...)` call, after plan compilation |
| `execute::evaluate_lexical_with` | `search/execute.rs` | unchanged generic per-segment evaluator |
| `benchmarks/pr15i_c/{run.py,verify.py}` | frozen tooling | reused unchanged for the authoritative campaign |
| `benchmarks/pr15e_b1/run_targeted.py` helpers | frozen | `prepare_corpus`, `stage_lanes`, `contention_for`, `require_native_filesystem`, `resolve_source_tree`, `verify_frozen_files` all present with the expected signatures (`FX-D22`) |

No `FX-D23`/`FX-D08` symbol mismatch was found.

## 5. Next state transition

`BASE_RECONCILED` → F-01 (generic `#[inline(never)]` control) executed
automatically per `FX-D15`/`FX-D18`.
