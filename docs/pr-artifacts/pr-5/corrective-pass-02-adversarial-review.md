# PR 5 corrective pass 02 adversarial review

For each C6 invariant, a plausible *still-broken* implementation and the test
that catches it.

| INV | Plausible still-broken implementation | Catching test |
|---|---|---|
| C6-INV01 | Chunk loop requests `remaining` when `remaining < max_read_bytes` but `remaining` otherwise (dropping the min) | `c6_u01_requests_are_chunk_bounded`, `c6_baseline_oversized_read_reproducer` |
| C6-INV02 | `max_read_bytes == 0` treated as "unbounded" or looped forever | `c6_u05_zero_chunk_fails_before_read` |
| C6-INV03 | Advance by requested rather than returned bytes, so a short read leaves a hole | `c6_u06_single_byte_short_reads`, `c6_u07_variable_fragments` |
| C6-INV04 | Return a partially filled buffer when `read_at` returns 0; or slice `buf[..read]` trusting `read <= request` | `c6_u09_short_object_is_length_mismatch`, `c6_u10_io_error_is_propagated`, `c6_u11_total_size_cap_rejects_before_read` |
| C6-INV05 | Conflate `accepted_segment_bytes` with `max_read_bytes`, or skip the whole-file digest after chunking | `c6_u11`, `c6_u03`, golden + `verify_content_descriptor` regression |
| C6-INV06 | Keep duplicate detection but only for adjacent keys (miss non-adjacent duplicates) | `c6_u12_duplicate_object_key_rejected` |
| C6-INV07 | Add an index but forget the second `object_key` payload (the clone) in the charge | `c6_i04_public_retained_bytes_is_conservative`, `c6_u16_u19_u20_retained_budget_boundaries` |
| C6-INV08 | Check the budget only after pushing/allocating, so a budget-exceeding entry is briefly retained | `c6_u16_u19_u20_retained_budget_boundaries` (one-below rejects) |
| C6-INV09 | Refactor feature negotiation while changing retained accounting | `c6_i03_unknown_required_feature_fails_closed`, pass-01 manifest tests |
| C6-INV10 | Regenerate the golden fixture to hide an encoder drift | Golden SHA unchanged; `c6-G01` |

## Independent oracles

- **Read path:** the instrumented `ReadHandle` logs `(offset, requested_len)` and
  rejects oversized requests; expectations are compared to the original bytes,
  not to a copied read loop. Baseline red reproduced in a worktree.
- **Manifest path:** tests construct `Manifest` values independently and compare
  `decode(encode(m)) == m`; the budget boundary is derived from the public
  conservative `retained_bytes()`, which exceeds a naive string-only estimate.

## Residual risks

| Risk | Severity | Disposition |
|---|---|---|
| Whole-object buffer up to `accepted_segment_bytes` | Accepted PR 5 limitation | Documented; per-request chunking now enforced |
| `retained_bytes` is conservative, not exact | Low | Accepted |
| `max_section_decode_bytes` applied independently by schema and manifest decoders | Low | Documented; no wire/contract change; future work may unify a global decode budget |
| R5-I09 has no runtime failing-before (no baseline setter) | Low | Code-level discrepancy documented; deterministic fixed-tree boundary proven |
| No authenticated selective range reads | Medium | Deferred; separate decision |

No new STOP condition. No unresolved correctness failure.
