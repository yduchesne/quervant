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

## ExactSet memory accounting (fixup)

ExactSet now charges its auxiliary `HashSet` through the existing
`CandidateBudget` and batch `SlotMemoryScope`:

- table charge = actual `HashSet::capacity() * 40`;
- retained-key charge = sum of live owned key UTF-8 lengths;
- replacement peak includes table delta, incoming key bytes and a temporary
  evicted-key clone;
- combined peak is preflighted with the heap entry before mutation;
- old-key and transient charges are released exactly once after eviction;
- failed preflight leaves heap, set and ledgers unchanged.

Unit tests:
`fx_h_table_charge_rejects_before_mutation`,
`fx_h_key_charges_track_insert_and_replacement`,
`fx_h_1024_byte_key_and_one_under_table_budget`,
`fx_p2_has_no_h_aux_table_charge`.
Default P2 carries no H aux charges.

Fixup FX-C1: evicted-key cloning now happens only after combined preflight and
charge commit; preflight inspects the heap key by reference. FX-C2: accounting
tests use one CandidateBudget/SlotMemoryScope for construction and admission.

Final QA: 2,526 all-feature workspace tests pass, Clippy both modes pass,
coverage 92.41% lines. Pinned configurable batch and explicit H batch
failure-then-success acceptance remain outstanding.

No benchmark, microbenchmark, or acquisition measurement was run. R3/T6/T7
evidence is unchanged.
