# PR 15I-D3-C — micro diagnostics and profile selection

The in-crate `d3c_micro_grid` (ignored, release) ran 5 independent rounds over
P0/P1/P2 × K {100,256,512,1024} × key lengths {8,32,128,1024} × traces
{miss_stable, duplicate_retained, churn, evicted_revisit}: 192 records, raw
`median_ns_per_op`, `rescan_fraction` and per-round values.

## Selection (frozen rule, before any E2E timing)

Maximum `miss_stable` exact-rescan fraction per profile:

| Profile | K100 | K256 | K512 | K1024 |
|---|---:|---:|---:|---:|
| P0 | 0.0323 | 1.0 | 1.0 | 1.0 |
| P1 | 0.0025 | 0.0139 | 0.0508 | 1.0 |
| P2 | 0.0009 | 0.0039 | 0.0139 | 0.0493 |

P0 and P1 exceed the 0.10 ceiling at K1024; P2 meets it at every required K.
**Selected profile: P2** (8192 bits, 1024 bytes, cap 2048 admissions).

This is a diagnostic fixture result, not a production claim and not an E2E
measurement. The fixed `[u64; 128]` state means P0 carries a larger stack
footprint than historical D3-B; that difference is documented.
