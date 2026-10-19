# PR 14 — P2B Phase B implementation (scoped memory API)

Phase A was **verified-existing** at HEAD `1041798` from source (`BatchExecutionMeter { work,
memory, response }`, `a01_disjoint_work_memory_borrows` passing). Phase B adds the scoped memory
API only; no query-execution integration (that is Phase C/E).

## Changed files

- `search/batch_meter.rs` (Phase A, verified): `BatchMemoryMeter::preflight_reserve`,
  `commit_reserve`, `reserve_memory`, checked `release_memory` (underflow → `CorruptIndex`).
- `search/memory.rs` (new):
  - `MemoryCharge` trait: `preflight`, `commit`, `release`.
  - `SlotMemoryScope<'m> { meter: &'m mut BatchMemoryMeter, temporary_bytes, finished }` with
    `reserve`, `release`, `temporary_bytes`, `finish_failure`, `finish_success(retained_bytes)`.
    `finish_success` requires `retained <= temporary`, keeps the retained bytes charged in the
    meter, releases the remainder. `release` validates against the scope before mutating the
    meter.
  - `Drop` fallback releases outstanding temporary bytes via the checked meter release; it
    `debug_assert!`s an invariant breach and never saturates or panics while unwinding.
- `search/mod.rs`: `#[allow(dead_code)] mod memory;` (staged ahead of Phase C/E wiring).

## Ownership proof

`SlotMemoryScope` owns the only mutable borrow of `BatchMemoryMeter`; `BatchWorkMeter` is borrowed
separately by `MixedWorkMeter`. No interior mutability, `unsafe`, globals, or duplicate meters.
`finish_success` performs a transfer (release `temporary - retained`) rather than
release-and-re-reserve, so retained bytes are never transiently uncharged.

## Tests (executed)

`search::memory` unit tests: `b01` exact/one-over, `b02` overflow atomicity, `b03` underflow no
mutation, `b04` explicit failure cleanup, `b05` drop cleanup, `b06` cancellation cleanup, `b07`
retained transfer, `b08` retained>temporary rejection, `b09` peak across scopes with retained
bytes, `b10` zero-byte reserve/release — **10 passed**.
