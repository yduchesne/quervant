# PR 15H-A — Preflight and frozen evidence

**Plan:** `QUERVANT_PR15H_A_DETAILED_IMPLEMENTATION_PLAN.md` v1.0
**Plan inspected `main` SHA:** `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078`
**Executed `main` SHA (fresh fetch):** `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078`
**Baseline SHA (`H_A_BASE_SHA`):** `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078`
**Working branch:** `dev/pr15h-a-linear-term-candidates`

## Freshness / ancestry check

- `git fetch origin main` returned `origin/main = ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078`.
- `git merge-base --is-ancestor main HEAD` succeeded for the new branch created from that exact SHA.
- `main` did **not** move relative to the inspected SHA (HA-D01 not triggered).
- No pre-existing accepted 15H-A implementation exists at the affected paths (HA-D03 not triggered).

## Working tree

- `git status --porcelain` was empty at preflight.
- Branch `dev/pr15h-a-linear-term-candidates` created from `H_A_BASE_SHA` (no cherry-pick of 15G-C/D/E).

## Source file identities at `H_A_BASE_SHA`

| Path | SHA-256 |
|---|---|
| `crates/quervant-core/src/search/execute.rs` | `b49d49f7d8104f10e98bea82e7a30b80652dd87b5b78c083bf9f1384ea8edb55` |
| `crates/quervant-core/src/search/unified.rs` | `b810fe68e23f0efb0bdb09a074dd4fdc90d0f9358a7b5668443175b1afeb1e2d` |
| `crates/quervant-core/src/search/score.rs` | `f03712ec16822a343002346a1bf596f292ed7884411fc1a4b0dbe7ba911caf16` |

## Frozen benchmark input identities at `H_A_BASE_SHA`

These match the frozen PR15D/PR15E constants, so the measurement inputs are unchanged.

| Path | SHA-256 |
|---|---|
| `benchmarks/pr15d/spec/pr15d_v1.json` | `ec6c0db865845184ba867fca97add3196bd62a3e88f2cf2c8042a1c594dce466` |
| `benchmarks/pr15d/corpus/oracle.py` | `4c37a72251b6b16e972161070297436c18b96421b09acd2665bce5c65abd20b2` |
| `benchmarks/pr15d/corpus/generate.py` | `d0bfd0ac7f63509f20454dd8ab96dcb50075a5293235fe894b14b60e5b86851d` |
| `benchmarks/pr15d/harness/run.py` | `8be6c21e5a2ac41a3dc12c17ab8bc5e91080c689323f7f05015919c01ff31243` |
| `benchmarks/pr15e_b1/run_targeted.py` | `ae92ad31ced37112a924474f2a58ddd921dc447cf2fae91c52473f1a07e99a7c` |
| `benchmarks/pr15g_c/run.py` | `767a67e5fd030105ee5fa1d75fc97e0f86f1634fb7256ce90b30d68e78c27926` |

## Environment

| Fact | Value |
|---|---|
| Rust (stable) | `rustc 1.98.1 (48a229cea 2026-09-01)` / `cargo 1.98.1 (797e8a9bc 2026-08-05)` |
| Rust (MSRV) | `cargo 1.85.0 (d73d2caf9 2024-12-31)` |
| Workspace `rust-version` | `1.85`, edition `2024` |
| Native filesystem for measurement root | `ext4` |
| Logical CPUs | 12 |
| Memory | ~31 GiB |

## Baseline smoke (S0 step 5)

| Command | Result |
|---|---|
| `cargo test -p quervant-core --lib search::unified` | PASS — 46 passed, 0 failed |
| `cargo test -p quervant-core --lib search::execute` | PASS — 40 passed, 0 failed |

## Branch and baseline sequence

1. Benchmark-only harness committed as `HA-HARNESS` **before** any Rust production edit.
2. Pre-optimization baseline campaign executed against a clean detached worktree at `H_A_BASE_SHA` and sealed.
3. Only then were production Rust edits made on the branch.
