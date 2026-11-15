# BM-03 design and contracts

BM-03 delivers the reusable mechanics for a frozen, declarative benchmark
protocol: compile a schedule, freeze every binding, execute a synthetic
campaign series through one controller, publish exact immutable evidence, and
replay it structurally. Nothing here measures a real system.

## 1. Modules and import direction

```text
benchmarks/quervant_bench/
  protocol/schedule.py    balanced-cyclic-v1 / explicit-v1 compilation + schedule record
  protocol/controls.py    synthetic A/A schedule, frozen control contract, campaign declarations
  protocol/freeze.py      closed synthetic-freeze payload, synthetic source/build markers
  execution/contracts.py  frozen budgets, RunState, StopReason, FaultPoint, internal records
  execution/clock.py      LogicalClock
  execution/scenario.py   closed synthetic scenario fixture + scenario validation
  execution/synthetic.py  SyntheticAdapter (frozen BM-01 BenchmarkAdapter seam)
  execution/recorder.py   closed record builders/validators + append-only recorder
  execution/store.py      exclusive descriptor-relative publication (ExecutionStore)
  execution/controller.py the single execution state machine
  execution/replay.py     read-only structural replay
```

`execution/contracts.py` is the single owner of the simulator budgets and is
imported by the protocol compiler, the controller, the store and the replayer, so
validation can never disagree about a limit. `protocol` and `execution` expose
their public names through lazy package `__getattr__`, which keeps
`protocol ↔ execution` imports acyclic.

## 2. Schedule compilation

`protocol/schedule.py` owns three identities:

* `balanced-cyclic-v1` — the seeded, exactly balanced block schedule;
* `explicit-v1` — a declared order that must still be position balanced;
* the closed `synthetic-schedule` record.

Admission conditions (`_compile_spec`): `2 ≤ arms ≤ 16`, each multiplicity `≥ 1`,
`slots_per_block ≤ 16`, `sum(multiplicity) = slots_per_block`, `1 ≤ blocks ≤ 256`.

With `arms` sorted lexicographically, `m[a]` the declared multiplicity,
`S = slots_per_block`, `B = blocks`, `g = gcd(m[0..])` and `T = S / g`, the
seeded algorithm requires `B % T == 0` and then

```python
rng = random.Random(seed)
for _cycle in range(B // T):
    tile = [a for a in sorted_arms for _ in range(m[a] // g)]   # exactly T entries
    rng.shuffle(tile)
    rotations = list(range(T)); rng.shuffle(rotations)
    for rotation in rotations:
        blocks_out.append(tuple(tile[(p + rotation) % T] for p in range(S)))
```

Guarantees, re-validated twice (compile time and read time):

* every block contains exactly `m[a]` occurrences of arm `a`;
* across all blocks every position contains arm `a` exactly `(B * m[a]) / S`
  times, which is integral for every accepted geometry;
* fixed seed + fixed declarations reproduce identical rows and bytes. The seed is
  part of the canonical payload, so a different seed always changes the binding
  digest even when the row permutation coincides.

Declaration order cannot change the randomized rows because the tile is built
from sorted arm identities; a declaration order that changes the canonical
protocol payload (and therefore `protocol_digest`) still changes the schedule
binding digest.

`explicit-v1` uses the declared rows unchanged, requires exactly `B` rows of `S`
entries, exact per-block multiplicities, declared arm identities and the same
integral per-position count. It never edits a historical file; it accepts one
only if that order is genuinely position balanced.

The stored record is `{"kind": "synthetic-schedule", "schema_version": 1,
algorithm_id, schedule_id, protocol_digest, seed, blocks, slots_per_block,
slots: [{block, position, ordinal, arm_id}]}` with row-major ordinals from 1 and
`schedule_digest = content_digest(document)` (digest not embedded in itself).

## 3. Control (A/A) contract

The v1 protocol declares only `control_contract_id`; it does not declare A/A arm
identities, thresholds or selection policy. BM-03 therefore implements exactly
one **simulation-only** policy, `synthetic-exact-equality`:

* `required_controls == 0` → the closed `not-required` control-schedule record
  (`campaign_count = 0`, `slots = []`); no control is invented;
* `required_controls > 0` → the contract id must be `synthetic-exact-equality`,
  `blocks` must be even, and a two-alias schedule (`control-left`,
  `control-right`, multiplicity 1 each, same seed and `protocol_digest`) is
  compiled by the **same** `_compile_spec` core;
* both aliases map to the declared `control_source_arm_id`; no candidate sample
  enters A/A;
* after each control campaign the controller compares the raw sample tuples of
  `control-left` and `control-right` for every block and lane. Any inequality is
  `CONTROL_MISMATCH`, persisted as a terminal event, with zero treatment slots.

`checked_pairs = blocks × lanes`. A PASS produces exactly one
`controls/control-NNNN.json` record; a mismatch produces no PASS record.

This is a synthetic mechanical oracle. It is not a stability qualification, a
confidence threshold or a Gate A–E receipt.

## 4. Synthetic scenario

Exactly one checked-in scenario (`tests/fixtures/execution/synthetic-scenario.v1.json`,
canonical bytes, ≤ 1 MiB) with the closed keys

```text
kind, schema_version, scenario_id, experiment_id, evidence_origin,
qualification_scope, control_source_arm_id, metric_unit, clock_contract_id,
samples[], readiness[]
```

* `samples` is sorted by `(arm_id, lane_id)`, exactly one record per declared arm ×
  lane, and each vector holds exactly `samples_per_lane_slot` positive integers
  `≤ 2^63 - 1`. Sorted order is validated, never silently imposed.
* `readiness` holds exactly one batch per required control/treatment campaign,
  sorted by `(campaign_kind, campaign_index)`, each observation exactly
  `{elapsed_ms, busy_permille, steal_permille}`.
* the frozen simulator limits are
  `ReadinessLimits(10, 20, 200, 150, 20, 2)`; the historical T7/F2 thresholds are
  **not** defaults;
* only `nanoseconds` + `lower-is-better` is executable. Another valid BM-01 unit
  stays inspect-valid but execution stops with `BM_NOT_IMPLEMENTED` before output.

Loading uses the BM-02 no-follow `open_regular_beneath` helper, the BM-01
duplicate-key-safe parser and requires canonical stored bytes. The loaded record
carries `scenario_digest = content_digest(document)` and is reopened immediately
before sealing.

## 5. No-time guarantee

* `LogicalClock` is a counter of simulated nanoseconds. It never reads wall time,
  thread/process time, a monotonic OS clock, Python `random`, or sleeps. Cap:
  `2^63 - 1`; `advance_ns` rejects booleans, negatives and overflow.
* Only the controller advances it: exactly `1` tick per warmup call and the sum of
  the validated sample values per measurement.
* The synthetic adapter returns declared values; it performs no timing.
* A mandated test (`test_scope_03_successful_paths_never_touch_clocks_processes_or_the_host`)
  patches `time.time`, `time.perf_counter`, `time.monotonic`, `subprocess.Popen`,
  `subprocess.run`, `os.system`, the BM-02 native `LinuxCapabilityProvider`
  methods and `cli.dispatch` with failure spies, then executes a full sealed run
  and replays it.

## 6. State machine and journal

`RunState`: `planned → frozen → ready → acquiring → completed → sealed`, with
`stopped`/`failed` terminal. Allowed transitions are frozen in
`execution/contracts.py::ALLOWED_TRANSITIONS`:

| From | To | Reason | Marker |
| --- | --- | --- | --- |
| `none` | `planned` | `new-run` | `events/00000001.json` |
| `planned` | `frozen` | `freeze-published` | one transition event |
| `frozen` | `ready` | `readiness-clear` | one transition event |
| `ready` | `acquiring` | `slot-acquiring` | one transition event |
| `acquiring` | `ready` | `readiness-clear` | one transition event, fresh readiness only |
| `acquiring` | `completed` | `campaigns-complete` | one transition event |
| `completed` | `sealed` | — | **only** `store.commit_seal()`; no event |
| any non-terminal | `stopped` | a `StopReason` value | terminal event, no seal |
| any non-terminal | `failed` | `unexpected-failure` | terminal event, no seal |

`StopReason` values are internal journal values, not new BM-01 error codes:
`freeze-missing`, `freeze-mismatch`, `host-not-ready`, `control-mismatch`,
`oracle-failed`, `adapter-failure`, `invalid-measurement`, `missing-slot`,
`duplicate-slot`, `missing-campaign`, `output-conflict`, `input-mutated`,
`unsafe-artifact`, `crash-interrupted`, `unexpected-failure`.

The state event is written **before** the in-memory state changes; a failed event
write is a typed failure, not a successful transition. Sequence numbers are
monotone from 1 with no gaps and no writes after the seal. A hard kill leaves the
last durable record; replay classifies the run as `crash-interrupted` and never
repairs it. A second use of the same `run_id` is `BM_PUBLICATION_CONFLICT` even
if the first run is incomplete.

The default fixture produces exactly nine state events (`2 + 2 × campaigns + 1`).

## 7. Slot execution order

For control **and** treatment campaigns alike:

```text
require committed freeze + fresh campaign readiness
-> create one fresh adapter instance through the injected factory
-> prepare(context), validate the PreparedFixture
-> check_oracle(context, prepared), require PASS
-> for each declared lane, in declared order:
      W warmups (validate PASS, advance 1 tick each)
      one measure call, validate exactly N positive integer samples
      advance the sum of the samples, commit exactly one lane envelope
-> cleanup(context, prepared) exactly once
-> commit exactly one slot-complete record referencing the lane digests
```

The oracle precedes the first warmup of the slot: a failed oracle produces zero
warmup and zero measurement calls. A failure in any lane forbids the
slot-complete record but preserves already published lane envelopes. Cleanup is
required once a fixture was prepared, even after a failure; if cleanup itself
fails the slot stays incomplete and the campaign stops. There are no retries.

## 8. Evidence layout and records

```text
<output_base>/<experiment_id>/<uuidv4>/
  schedule.json  control-schedule.json  freeze.json
  events/00000001.json …
  readiness/{control|treatment}-NNNN.json
  slots/{kind}-NNNN/block-BBBB/slot-PPPP/<lane_id>.json
  slots/{kind}-NNNN/block-BBBB/slot-PPPP/complete.json
  controls/control-NNNN.json
  seal.json        # last artifact; absent for stopped/failed runs
```

The slot directory name is the **position within the block**; the campaign
ordinal lives in the JSON `slot.ordinal`. Every record is canonical BM-01 bytes
plus one trailing newline, with a closed field set validated on write and on read
and bounded by `MAX_CANONICAL_RECORD_BYTES`.

Lane envelope logical arithmetic is exact:
`logical_end_ns == logical_start_ns + warmup_calls + sum(samples)`, and replay
requires consecutive envelopes to be contiguous in logical time.

## 9. Publication

`ExecutionStore.create()` calls BM-02 `require_disjoint_admission_roots` and
`require_publication_base`, then `mkdir`s the per-run directory; `EEXIST` is
`BM_PUBLICATION_CONFLICT` with no repair or resume. Writes are
descriptor-relative with `O_CREAT | O_EXCL | O_NOFOLLOW`, each file is fsynced and
its parent directory is fsynced. `write_new` refuses `seal.json`;
`commit_seal()` is the only seal path and re-validates the seal record first.
Unsupported fsync semantics are `BM_NOT_IMPLEMENTED`, never a weaker fallback.

Before sealing, the controller verifies that no expected record is missing, that
no unexpected record exists, that every record still parses canonically, and that
every raw byte digest/length is recorded in `seal.files` (sorted POSIX relative
paths, excluding `seal.json`, digests over **raw stored bytes**).

Known limitation: `ExecutionStore` is a deterministic simulator store, not a
general production evidence backend. Its source/build authorization and crash
guarantees must be revisited in the BM-09 qualification design; changing an origin
string does not promote it.

## 10. Replay

`replay_sealed_synthetic(run_dir, bundle, scenario_root)` is strictly read-only:

1. require a safe root, refuse a missing seal with `BM_EVIDENCE_UNAVAILABLE` and a
   `crash-interrupted` diagnostic;
2. recompile the schedule and control schedule **from the declared bundle**,
   reopen the declared scenario, and rebuild the expected file inventory;
3. compare the actual inventory and the seal file list exactly (no missing,
   extra, duplicate, symlinked, FIFO or non-regular entry);
4. verify every raw byte digest and length, then parse every record canonically;
5. verify schedule bytes/digest, control schedule, freeze bindings, the state
   event chain, readiness diagnostics (re-evaluated with the BM-02 evaluator),
   lane envelopes (declared values, IDs, ordinals, warmup count, logical
   contiguity), slot completion lane digests, control equality from raw samples,
   and every seal count including `last_logical_ns`;
6. return `StructuralReplayResult(status="verified-synthetic-structure", …)`.

Replay never imports controller state, never calls a controller completeness
predicate, never writes/repairs, and never issues a statistical or gate decision.

## 11. Budgets

Defined once in `execution/contracts.py`:

```text
MAX_ARMS 16, MAX_LANES 64, MAX_BLOCKS 256, MAX_SLOTS_PER_BLOCK 16,
MAX_CONTROL_CAMPAIGNS 4, MAX_TREATMENT_CAMPAIGNS 8,
MAX_WARMUPS_PER_LANE_SLOT 32, MAX_SAMPLES_PER_LANE_SLOT 256,
MAX_TOTAL_LANE_SLOTS 50_000, MAX_SYNTHETIC_SAMPLE_NS 2^63-1,
MAX_CANONICAL_RECORD_BYTES 1 MiB, MAX_SCENARIO_BYTES 1 MiB,
MAX_EVENT_RECORDS 150_000, MAX_LOGICAL_NS 2^63-1
```

Products are computed with Python integers before any allocation; an
over-budget geometry is rejected with `BM_IDENTITY_INVALID` before any output.

## 12. Default fixture arithmetic

`required_controls=1`, `required_treatments=2`, `blocks=4`,
`slots_per_block=2`, `lanes=2`, `W=2`, `N=3`:

```text
control campaigns 1, control slots 8; treatment campaigns 2, treatment slots 16
all slots 24; lane envelopes 48; synthetic samples 144
warmups 96; oracle/prepare/cleanup invocations 24 each
readiness observations 6; A/A checked pairs 8; state events 9
```

These numbers are asserted from the hand-constructed
`tests/fixtures/execution/golden-structural-summary.v1.json`, not recomputed from
production formulas.
