# PR 15I-C follow-up (`15IC-NOISE-OUTSIDE-DISPATCH-v1`) — preflight

Status: `PREFLIGHT_COMPLETE`
Recorded: 2026-11-08

## 1. Repository identity

| Item | Value |
|---|---|
| Branch | `dev/pr15i-c-postings` |
| HEAD at start (`BRANCH_START`) | `fe069b9ec5b2ccbd1da583e26ff8ede10b295b6c` |
| `origin/main` (`BASE`) | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| Historical rejected physical candidate (`OLD_C`) | `395e05c629c5929f0164764c51c5a1b60b8acd1c` |
| Historical F0 generic control (`OLD_G`) | `50b56e9fe7b22bb266ca7b0d9e209500dfc785ff` |
| Working tree | clean (`git status --porcelain -uall` empty) |

Checks (all satisfied):

```
branch == dev/pr15i-c-postings
git merge-base --is-ancestor BASE HEAD              -> 0
git merge-base --is-ancestor BRANCH_START HEAD      -> 0
git cat-file -e {BASE,BRANCH_START,OLD_C,OLD_G}^{commit}  -> all present
git diff --quiet BASE HEAD -- crates/quervant-core/src crates/quervant-core/Cargo.toml \
    Cargo.lock benchmarks/pr15d benchmarks/pr15i_a benchmarks/pr15i_b .github/workflows/ci.yml
    -> empty (production/Cargo/CI byte-identical to merged PR 15I-B)
git diff --check -> clean
```

`origin/main` equals `BASE`; no newer main exists (`NC-D03`). Branch HEAD is the
previous safe-rollback commit whose extra content is diagnostics and PR 15I-C
reports only (`NC-D05`).

## 2. Toolchain, host and frozen fixtures

| Item | Value |
|---|---|
| `rustc --version` | `rustc 1.98.1 (48a229cea 2026-09-01)` |
| `cargo --version` | `cargo 1.98.1 (797e8a9bc 2026-08-05)` |
| `cargo +1.85.0 --version` | `cargo 1.85.0 (d73d2caf9 2024-12-31)` |
| `python3 --version` | `Python 3.12.3` |
| CPU count | 12 |
| Native filesystem | `ext4` (`findmnt -n -o FSTYPE -T .`) |
| Frozen 15I-C protocol | `benchmarks/pr15i_c/protocol.json`, SHA-256 `5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e` (unchanged) |
| Frozen corpus manifest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Pinned real RustFS image (CI) | `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` |
| Container runtime | **absent** (`docker`/`podman` not installed) → `REAL_RUSTFS_BLOCKED` unless a later check finds one |

## 3. Source symbol verification (required by P0)

| Symbol | Location | Verified |
|---|---|---|
| `UnifiedSearcher::search_impl` | `search/unified.rs:408` at `BASE` | yes |
| `UnifiedSearcher::execute_unified` | `search/unified.rs:439` at `BASE` | yes |
| `UnifiedSearcher::collect_mixed` | `search/unified.rs:571` at `BASE`, attributes `#[allow(needless_option_as_deref)]`, `#[allow(too_many_arguments, type_complexity)]`, **no inline attribute** | yes |
| `UnifiedSearcher::keyword_sort_late_eligible` | `search/unified.rs:544` at `BASE` | yes |
| `UnifiedSearcher::exact_term_physical_eligible` | `search/unified.rs:582` at `OLD_C` | yes |
| `execute::for_each_exact_term_score_with` | `search/execute.rs:2157` at `OLD_C` | yes |
| `consider_borrowed_keyword_candidate` | `search/unified.rs:1454` at `OLD_C` | yes |
| F0 control attributes | `OLD_G` has exactly one added `#[inline(never)]` before `fn collect_mixed` (line 575 context) | yes |

`collect_mixed` normalized body SHA-256 at `BASE`
(`benchmarks/pr15i_c/source_proof.py`): `00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994`.

Harness CLIs verified from the checked-in source:

```
run.py     --checkout-root --baseline-sha --candidate-sha --out [--idle-confirmed]
verify.py  --checkout-root --campaign [--verify-only] [--no-receipt]
```

`benchmarks/pr15i_c/run.py` exposes `prepare_arm`, `size_builds`,
`build_adapter_offline`, `measure_layout`, `segment_digest`, `write_exclusive_json`
and the shared `base` (= `benchmarks/pr15e_b1/run_targeted.py`) module. The 32-slot
7-lane measurement primitive with 5 warmups + 10 measured samples already exists as
`benchmarks/pr15i_c/layout_diag.py::measure_slot`; the noise controller reuses it
rather than forking the canonical adapter/query executor (§3.2 authorizes reuse of
existing machinery only).

## 4. Baseline targeted QA

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 check --locked -p quervant-core` | PASS |
| `cargo test --locked -p quervant-core --lib search::unified` | 52 passed |
| `cargo test --locked -p quervant-core --lib search::execute` | 40 passed |
| `python3 -m unittest discover -s benchmarks/pr15i_c` | 90 passed |
| `bash benchmarks/scripts/test-scripts.sh` | 108 passed, 0 failed |
| `git diff --check` | clean |

Known historical exception: `benchmarks/pr15i_a::RealCampaignTests` reports
1 failure + 3 errors. Reproduced identically at merged `BASE` in earlier sessions
with the same raw campaign present; classified `SOURCE_BOUND_HISTORICAL_ONLY`
(`NC-D12`, `NC-D14`) and not edited.

## 5. Admitted evidence gaps carried forward

The original PR 15I-C admitted that a synthetic `InvalidScore` (`df > n`) fixture
cannot be constructed without a test-only constructor inside the protected
`search/score.rs`. That gap is **not** resolved by this follow-up and is not
presented as resolved: `N-U32`/`N-F08` remain an `EVIDENCE_BLOCKED` item unless a
narrowly scoped test-seam amendment is granted (`NC-D56`).

## 6. Next state transition

`PREFLIGHT_COMPLETE` → P1-A: author and commit the prospective noise protocol,
controller, independent verifier and adversarial tests **before** the first new
sample (`NC-D17`).
