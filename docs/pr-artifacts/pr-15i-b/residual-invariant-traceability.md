# PR 15I-B residual — invariant traceability

| Invariant | Tests / evidence |
|---|---|
| INV-01 v2 wire and v1 block bytes unchanged | restored `pr15i_b_stored` geometry/feature/parity tests; campaign size sentinels |
| INV-02 full validation once with shared budget | `validate_all_blocks` capture tests; reader certificate tests; RES-U26/U27/U28 |
| INV-03 certificate owned by one verified state | reader distinct-state/concurrency tests; RES-U35/U36 |
| INV-04 selected-only boundary checks, no 128-pair hot scan | `validate_certified_selected_slice`; `res_u14_u17`, `res_u22_u25`; hot counters |
| INV-05 singleton no local heap/outer vector | `res_u14_u17` counters; reader `certificate_retains…` |
| INV-06 typed errors/no panic | `res_u22_u25`, `dr_u19_dr_u22`, reader fallback tests |
| INV-07 zero/no budget full fallback | reader `zero_metadata_cap…`, `plain_reader…` |
| INV-08 query/PIT/compaction semantics | `pr15i_b_stored` 20 tests; PR15I-A regression suite |
| INV-09 frozen gates/schedule | `protocol.json` hash; controller/verifier unchanged |
| INV-10 historical evidence immutable | old seals untouched; legacy-negative Python tests |
| INV-11 order/absolute diagnosis | `residual/diagnostics/*-order/order-analysis.json` |
| INV-12 rollback byte parity | `git diff P0 HEAD -- core/Cargo/CI` empty |

## Counterexamples resolved before coding

- Forged **selected** boundary: rejected by O(k) selected checks (`res_u22_u25`).
- Forged **unselected interior** table: impossible to publish because the table is
  built only by full validation; a corrupted unselected record fails certificate
  creation (`unselected_corruption_blocks_certificate`). The hot helper deliberately
  does not rescan 128 pairs.
- `[127,128]`: block 1 starts at flat index `128+1`; exact cross-block tests.
- Duplicate/descending/out-of-range IDs: rejected before decompression.
- No budget: full validating fallback every request.
- Warmup/snapshot renewal: existing adapter session reuses one `ReaderSnapshot`;
  counters show certificate delta zero on hot reads.
