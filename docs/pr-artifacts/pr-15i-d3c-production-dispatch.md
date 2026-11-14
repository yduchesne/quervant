# PR 15I-D3-C-P — production Top-K duplicate dispatch

- Branch: `dev/pr15i-d3c-prod-duplicate-dispatch`
- Baseline reviewed source: `bf0c0ee164b3b9782504f04f22453b741ca3ee14`
- Default: `TopKDuplicateConfig { min_top_k = 32, strategy = Prefilter (P2) }`
- Public API: `TopKDuplicateStrategy`, `TopKDuplicateConfig`,
  `UnifiedSearcher::with_topk_duplicate_config`.
- Public batch wrappers:
  `execute_batch_with_topk_duplicate_config`,
  `execute_batch_pinned_with_topk_duplicate_config`.
- Existing four-argument constructor and existing batch functions retain
  default behavior.
- D3-C algorithms now compile without `pr15i-d3c-experiment`; the feature only
  retains the historical environment-mode compatibility path.
- Permission `PD-I01`–`PD-I04`/`PD-I09` smoke tests added to
  `pr15i_d3_c.rs`: default K31/K32/K33 parity, custom threshold, ExactSet
  K1024 inclusive/K1025 typed `ResourceLimit`, Prefilter K1025 success, and
  explicit batch-config parity.

## QA executed

- `cargo fmt --all -- --check`: PASS
- `cargo clippy -p quervant-core --all-targets --all-features -- -D warnings`: PASS
- `cargo clippy -p quervant-core --all-targets -- -D warnings`: PASS
- `cargo test --workspace --all-targets`: 2,482 passed, 0 failed
- `cargo test --workspace --all-targets --all-features`: 2,522 passed, 0 failed
- `cargo test -p quervant-core --test pr15i_d3_c`: 18 passed (both feature modes)
- `cargo test -p quervant-core --features pr15i-d3c-experiment d3c_tests`:
  36 passed, 1 ignored
- `cargo llvm-cov --workspace --all-targets --fail-under-lines 85`:
  PASS, 92.46% line coverage

## Residual risk

ExactSet's auxiliary owned-key `HashSet` is bounded by `K <= 1024` but its
extra key-byte allocation is not separately charged to `CandidateBudget`.
The default P2 path has no owned-key duplication. ExactSet remains an explicit
non-default caller choice; production activation of ExactSet should be treated
as gated pending a dedicated memory-accounting decision. P2 default remains
safe within the existing candidate ledger.

No benchmark, microbenchmark, or acquisition measurement was run. R3/T6/T7
evidence is unchanged.
