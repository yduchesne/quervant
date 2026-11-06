# PR 15G-E index-size disclosure correction

The sanitized campaign JSON contains an `index_bytes` object with values
`4096` for each arm/N. Those values are **not valid index sizes**: the runner
summed only files directly in the index directory, while segment objects live
in nested directories. The field did not participate in any performance gate.

Actual on-disk totals from the preserved raw campaign setup:

| Arm | N | bytes |
|---|---:|---:|
| A (v1.0) | 10,000 | 3,090,037 |
| E (v1.1) | 10,000 | 3,250,281 |
| A (v1.0) | 100,000 | 30,965,025 |
| E (v1.1) | 100,000 | 32,565,269 |

Observed E overhead: **160,244 bytes** at 10K and **1,600,244 bytes** at 100K,
consistent with two `50 + 8*(N+1)` directories plus section-directory growth.
The E format was rejected on latency before any size acceptance decision; this
correction preserves the measured campaign and does not alter its verdict.
