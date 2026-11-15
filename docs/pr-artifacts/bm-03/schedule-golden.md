# BM-03 schedule goldens and boundaries

Algorithm version: `balanced-cyclic-v1` (seeded) and `explicit-v1`.
Reference implementation: `benchmarks/quervant_bench/protocol/schedule.py`.
Machine-readable goldens: `benchmarks/quervant_bench/tests/fixtures/execution/golden-schedule.v1.json`.

## 1. Literal two-arm vector

Seed `42`, arms `baseline` and `candidate` with multiplicity 1 each,
`slots_per_block = 2`, `blocks = 4` (so `S = 2`, `g = 1`, `T = 2`, `B / T = 2`
cycles):

```json
[["baseline","candidate"],
 ["candidate","baseline"],
 ["candidate","baseline"],
 ["baseline","candidate"]]
```

This vector is asserted literally by
`test_protocol_schedule.py::test_sched_01_two_arm_seeded_sequence_is_the_literal_golden`
and by the experiment fixture path (`compile_schedule(load_experiment_bundle(...))`).
It is a hand-written reference, not generated from the implementation under test.

Per-position counts (`B * m / S = 4 * 1 / 2 = 2`): `baseline` appears twice at
position 1 and twice at position 2; `candidate` likewise.

## 2. Historical-shaped four-arm geometry

Arms `alpha`, `beta`, `gamma`, `delta`, multiplicity 2 each, `S = 8`, `B = 12`:
`g = 2`, `T = 4`, `B % T == 0`.

Independently measured structural properties
(`test_sched_02_four_arm_geometry_is_position_balanced`):

| Property | Expected |
| --- | --- |
| slots | 96 |
| occurrences per arm | 24 |
| occurrences per block per arm | 2 |
| occurrences per arm per position | `B * m / S = 12 * 2 / 8 = 3` |
| unknown arm ids | 0 |

The structural oracle is used deliberately: BM-03 does **not** claim that new
schedule bytes equal the frozen historical `pr15i_d3_c` campaign order. Supporting
the 12×8 geometry structurally is the requirement.

## 3. Explicit orders

`explicit-v1` preserves the declared row order exactly, but the same arithmetic
must hold: exactly `B` rows, `S` entries per row, exact per-block multiplicities,
declared arm identities and an integral per-position count of `B * m / S`.

* individually balanced but position-unbalanced rows are rejected
  (`test_sched_04_position_unbalanced_explicit_orders_are_rejected`);
* unknown arm ids and wrong per-block multiplicity are rejected
  (`test_sched_03_explicit_orders_are_preserved_byte_for_byte`);
* no historical protocol file is edited by this path.

## 4. Seed domain

`validate_uint64` (BM-01) governs the seed: `0 … 2^64 - 1`, rejecting booleans,
floats and strings. Determinism is asserted for `0`, `1`, `42`, `0x5EEDB001`,
`2^32 - 1` and `2^64 - 1`; `2^64` and `true` are rejected.

The seed is part of the canonical schedule payload, so:

* a changed seed always changes the schedule binding digest;
* a changed seed does **not** have to produce different rows — coincident row
  permutations are mathematically possible and are accepted, because the seed
  binding still differs.

## 5. Digest method

```python
document = {
  "kind": "synthetic-schedule", "schema_version": 1,
  "algorithm_id": "balanced-cyclic-v1",
  "schedule_id": <declared schedule id>,
  "protocol_digest": "sha256:<64 lower-case hex>"  # BM-01 canonical protocol digest,
  "seed": <uint64>, "blocks": <int>, "slots_per_block": <int>,
  "slots": [{"block": b, "position": p, "ordinal": o, "arm_id": a}, ...],
}
schedule_digest = content_digest(document)   # sha256 over canonical payload bytes
```

Stored bytes are `canonical_document_bytes(document)` (canonical payload + one
trailing newline); the newline is storage form, not digest input. No timestamp,
absolute path, RNG object or process identity enters the payload. Slots are stored
row-major with `ordinal = (block - 1) * slots_per_block + position`.

Recomputation on read (`validate_schedule_document`) re-validates the closed key
set, ordinals, block/position ordering, per-block multiplicities and per-position
balance, and returns `schedule_digest = content_digest(stored document)`.

## 6. Boundaries

| Condition | Result |
| --- | --- |
| `blocks = 256`, `slots_per_block = 16`, multiplicities 8/8 | accepted, 4096 slots, 128 occurrences per arm per position |
| `blocks = 257` | rejected (`MAX_BLOCKS`) |
| `slots_per_block = 17` | rejected (`MAX_SLOTS_PER_BLOCK`) |
| `blocks % T != 0` | rejected, `field_path = "schedule.blocks"` |
| `arms < 2` or `arms > 16` | rejected |
| multiplicity `< 1` or `sum ≠ slots_per_block` | rejected |
| stored slot row/ordinal/block count tampered | rejected by `validate_schedule_document` |
| stored seed or `protocol_digest` tampered | structural validation passes but the recomputed digest differs from the recompiled schedule, so replay rejects |

Cross-version note: CI runs CPython 3.12 and BM-03's byte-level goldens are
defined for that interpreter (`random.Random` Fisher–Yates draws). Local 3.11
execution is supported but a byte-level golden difference between 3.11 and 3.12
would be a hard stop for algorithm-version review; none was observed (see the
verification report).
