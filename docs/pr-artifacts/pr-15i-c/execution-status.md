# PR 15I-C — Execution status

## Disposition

**`15IC_PERFORMANCE_REJECTED_SAFE_ROLLBACK`**

The candidate was implemented exactly to the plan, passed every executed
correctness/source/provenance gate and improved all three primary common lanes,
but failed the frozen non-primary performance gate `C-P09`. Per `C-D65` the
production change was rolled back additively and the full negative result was
preserved. Nothing is merged, pushed or released.

Independent external statuses remain separate: `HOSTED_CI_PENDING`,
`REVIEW_PENDING`, `NOT_PUSHED`, `NOT_MERGED`, and `REAL_RUSTFS_BLOCKED` (no
container runtime on the host).

## Commit identities

| Role | Commit |
|---|---|
| Effective merged-15I-B base (`BASE_CONTENT_SHA` content) | `f70cde62e709383d82693ad548a8c69c7f772bef` |
| Effective checkout at start | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| `C_TOOLING_SHA` (controller + verifier + probes frozen before measurement) | `395e05c629c5929f0164764c51c5a1b60b8acd1c` |
| `C_MEASURED_SHA` (= `C_IMPLEMENTATION_SHA`) | `395e05c629c5929f0164764c51c5a1b60b8acd1c` |
| Rollback commit (`C_FINAL_CODE_SHA`) | `acc10d004e8f963112433e9f7be0aeed0abdd504` |

`git diff --quiet BASE HEAD -- crates/quervant-core/src crates/quervant-core/Cargo.toml
Cargo.lock benchmarks/pr15d benchmarks/pr15i_a benchmarks/pr15i_b
.github/workflows/ci.yml` → **empty** after the rollback commit.

## Gate matrix

| Gate | Status | Evidence |
|---|---|---|
| C-P00 source identity | PASS | `preflight.md`; merged 15I-B tree byte-identical to base |
| C-P01 design questions + pre-implementation trace | PASS (implementation) / **DIAGNOSTIC_PENDING** | `invariant-traceability.md`; baseline-side stage probe structurally impossible (§4 of `diagnostic-stage-profile.md`) |
| C-P02 eligibility/fallback matrix | PASS | `C-U01..C-U03`, `C-U12`, `C-U26`, `C-U30`, `C-U33`, `C-U39` |
| C-P03 exact scores/keys/totals/sort/projection/cursor | PASS | `C-U05`, `C-U08`, `C-U09`, `C-U10`, `C-U11`, `C-U34`, `C-U37`, `C-I01..C-I04`, raw `score_parity.json` |
| C-P04 work/scanned/cancellation/first-error precedence | PASS with declared gap | `C-U13..C-U22`, `C-U31`, `C-U38`, `C-U40`, `C-I21` |
| C-P05 no matched/scored trees, bounded heap, no persistent memory | PASS | `C-U04`, `C-U29`, `C-U40` |
| C-P06 10K common/K100 ≤0.90 | **PASS** (0.8920) | `raw/measurements.json` |
| C-P07 100K common/K100 ≤0.90 | **PASS** (0.8476) | `raw/measurements.json` |
| C-P08 100K common/K10 ≤0.90 | **PASS** (0.7854) | `raw/measurements.json` |
| C-P09 six non-primary lanes ≤1.05 | **FAIL** (1.2575, 1.3783, 1.7193, 1.7162 fail; 0.9246, 0.9144 pass) | `raw/measurements.json`, independent receipt |
| C-P10 16 slots / 9 lanes / 720 warmups / 2880 samples / clear contention / native FS | PASS | verifier `validate_slot_matrix`, `inventory`, `verify_seal` |
| C-P11 12 rebuilds, A/B layout+segment digest parity, LZ4 v2 | PASS | verifier `verify_sizes` |
| C-P12 SHA-bound source, adapter + score-probe binaries, corpus, seal | PASS | verifier `verify_source`, `verify_binaries`, `verify_corpus_and_slots` |
| C-P13 real local/PIT/compaction/delete/reopen + pinned RustFS + PR13 fault path | **PARTIAL / BLOCKED** | local, PIT, compaction, delete+reopen and two-segment paths executed; RustFS blocked (no container runtime) |
| C-P14 stable/MSRV fmt, clippy, tests, ≥85% lines, doc, bench no-run, scripts | PASS | §"Final QA" below |
| C-P15 independent verifier reconstructs all gates and agrees | PASS | `target/pr15i-c/reviews/paired-01-verification.json` |

## Final QA on the settled rollback tree (`acc10d0`)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS (135 test binaries, 0 failed) |
| `cargo test --workspace --all-targets --all-features` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — `TOTAL` lines **92.68%**, regions 87.48%, functions 91.96% |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108 passed) |
| `python3 -m unittest discover -s benchmarks/pr15d/harness` | PASS (139) |
| `python3 -m unittest discover -s benchmarks/pr15i_b` | PASS (10) |
| `python3 -m unittest discover -s benchmarks/pr15i_c` | PASS (41) |
| `git diff --check` | CLEAN |

### Pre-existing failure classification

`python3 -m unittest discover -s benchmarks/pr15i_a` reports 87 tests with
1 failure + 3 errors, all in `test_verify.RealCampaignTests`:
`test_ft_a49_real_campaign_verifies`, `test_ft_a50_real_campaign_is_read_only`,
`test_ft_a51_real_production_tree_unchanged`,
`test_ft_a53_statuses_are_separate`.

Classification: **`DETERMINISTIC_PREEXISTING` / `SOURCE_BOUND_HISTORICAL_ONLY`**
(`C-D72`). Reproduced identically in a detached worktree at the merged-15I-B base
with the same campaign directory copied in (1 failure + 3 errors). They assert
that `main`'s production tree still equals the historical PR15I-A measured source,
which is not true of any later branch; they were not weakened, and they are not
counted as PR 15I-C acceptance.

## Preserved artefacts

* `target/pr15i-c/campaigns/paired-01/` — complete sealed campaign
  (`raw/` inventory + `seal.json`, `setup/` worktrees, 12 index rebuilds, 16 slot
  records, corpus, contention probes).
* `target/pr15i-c/reviews/paired-01-verification.json` — independent receipt.
* `target/pr15i-c/diag/out/` — candidate stage-probe samples.
* `benchmarks/pr15i_c/` — frozen protocol, controller, verifier, adversarial
  tests, stage and score probes.
* This artifact directory.

## Residual risks

1. The low-match regression's root cause is a codegen/inlining cliff in
   `collect_mixed`, not the operator's work. It is reproducible and was shown to
   appear with any data-dependent call in that position. A future experiment must
   restructure `collect_mixed` first and re-measure with a real A/B stage probe.
2. The baseline-side stage profile is structurally unavailable with the current
   opt-in-feature approach; a future plan needs a probe design that exists at the
   baseline commit (for example, a separate instrumentation-only branch).
3. `C-U19`'s synthetic `InvalidScore` fixture requires a test seam in the
   protected `search/score.rs`; it was declared as a gap rather than manufactured.
4. Real RustFS/proxy acceptance was not executed on this host.
