# PR 15I-B residual — source and diagnosis

## Implemented source changes (R1–R3)

- **R1:** `validate_certified_selected_slice` checks table length, O(1) first/last
  endpoints and only the selected record pairs after certification. Full
  monotonicity remains in `validate_offset_slice` during certificate creation and
  the uncached fallback.
- **R2:** `decode_certified_block` uses a stack `[u64;1]` local ID for a singleton
  group and a reused, fallibly reserved scratch vector for 2+ IDs.
- **R3:** `decode_selected_with_offsets` returns the decoder-owned result vector
  directly when every selected ID is in one block; only multi-block selections
  allocate the outer result.

Wire format, producers, certificate ownership/metering, full validation and the
uncached fallback are unchanged.

## Structural counters (test-only, asserted)

For a certified singleton read: `hot_lookups=1`, `direct_records=1`,
`full_scan_records=0`, `local_id_reservations=0`, `extra_outer_allocations=0`,
`selected_boundary_checks=1`, `full_offset_pair_checks=0`. Two IDs in one block:
one lookup, one reservation, no outer allocation. Two blocks: two lookups, one
outer allocation, no local reservation for singleton groups.

## Order diagnostic (old direct campaigns, read-only)

`benchmarks/pr15i_b/residual/extract_order.py` recomputed the 16 sealed slot
records. LZ4 10K rare showed an ABBA/BAAB association (ABBA mean 1.2292, BAAB
1.0762, gap 0.1531, `ORDER_ASSOCIATION_OBSERVED`); Zstd showed gap 0.0425
(`NOT_ESTABLISHED`). The official four-block gate was not changed.

## Micro-profile and 8-block paired diagnostic

`residual_microtests` and the same-codec 8-block `paired_diag.py` were **not
executed** in this window. They are diagnostic-only and never acceptance; the
frozen 16-slot campaigns are the authoritative qualification. Residual overhead
attribution beyond the structural counters is therefore partial.
