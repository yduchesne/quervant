# PR 14 — P2 batch governance preflight

- Branch: `dev/pagination`
- `main`: `7ca1b2ec59fec648602e0e4a52e8f903a596f106`
- Branch HEAD at preflight: `371c137fe5cc377fe5f28853a9cfe203abeb1547`; P2 edits uncommitted.
- Toolchains: stable `1.98.1`, MSRV `1.85.0`, `cargo-llvm-cov 0.9.1`.

## Charge-site inventory

| Site | Unit | Batch hook |
|---|---|---|
| `work::MixedWorkMeter::{charge_lexical,charge_typed,charge_scanned_postings}` | local total/typed/scanned | preflight + commit `BatchExecutionMeter` atomically |
| `execute::evaluate_lexical_with` per live doc | +1 typed (typed leaves) or +1 lexical | via the shared meter |
| `expand_query`/`compute_stats`/`build_leaf_data`/phrase | existing PR 7 units | via `SearchWork::shared(&mut MixedWorkMeter)` |
| typed `evaluate_query`/JSON/geo | `ScanGuard::charge` | via `ScanGuard::shared(TypedCharge)` |
| `batch::response_bytes` | key/score/field five-state payload + fixed overhead | `charge_response` cumulative |
| response retention | logical bytes | `reserve_memory` / `release_memory` |

`SearchWork::new`/`ScanGuard::new` remain only in standalone executors; the batch path uses the shared variants.

## Invariant → test matrix

| ID | Evidence |
|---|---|
| I01 work cumulative, zero-hit charged | `b01`, `b06_work_is_not_hit_count`, `batch_meter::work_exact...` |
| I02 atomic local+batch | `batch_meter::work_exact_limit_then_one_over_is_atomic` |
| I03 no class bypass | per-doc charge; `b01`, `b06`, `b21` |
| I04 memory peak | `batch_meter::memory_peak_tracks_simultaneous_reservations`; integration `b17` memory-kind |
| I06 response cumulative | `b14`, `b16`, `batch::response_bytes_are_cumulative_and_checked` |
| I08 budget kind origin | `b17`, `batch::error_mapping_preserves_contract_errors` |
| I09 envelope policy | `b19`, existing `b10`, `b13` |
| I10 F1/P1 unchanged | full suites |
| I11 checked arithmetic | `batch_meter::overflow_is_typed_not_wrapped` |
| I05/I07/B10–B13/peak release | partial (temporary query memory not wired to the batch meter) |
| B24 remote GET | BLOCKED (no RustFS) |
