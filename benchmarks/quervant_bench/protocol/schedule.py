"""Frozen schedule compilation for the synthetic execution core.

Three identities live here and nowhere else:

* ``balanced-cyclic-v1`` — the seeded, exactly balanced block schedule;
* ``explicit-v1`` — an already declared order that must still be position balanced;
* the closed ``synthetic-schedule`` record written to the evidence store.

The compiler never consults global entropy, a clock or the process environment.
It validates multiplicities, per-block counts and per-position counts *twice*:
once while compiling and once while re-reading stored bytes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import gcd
from random import Random
from typing import Any, Mapping

from ..config.codec import content_digest
from ..config.contracts import ArmMultiplicity, ExperimentBundle, validate_bundle
from ..config.errors import BM_IDENTITY_INVALID, BenchError
from ..config.identity import (
    validate_digest,
    validate_positive_int,
    validate_semantic_id,
    validate_uint64,
)
from ..execution.contracts import (
    INTERNAL_SCHEMA_VERSION,
    MAX_ARMS,
    MAX_BLOCKS,
    MAX_SLOTS_PER_BLOCK,
    require_positive_int,
)

ALGORITHM_BALANCED = "balanced-cyclic-v1"
ALGORITHM_EXPLICIT = "explicit-v1"
SEEDED_MODE = "seeded-balanced"
EXPLICIT_MODE = "explicit"
SCHEDULE_KIND = "synthetic-schedule"

_SCHEDULE_KEYS: frozenset[str] = frozenset(
    {
        "kind",
        "schema_version",
        "algorithm_id",
        "schedule_id",
        "protocol_digest",
        "seed",
        "blocks",
        "slots_per_block",
        "slots",
    }
)
_SLOT_KEYS: frozenset[str] = frozenset({"block", "position", "ordinal", "arm_id"})


def _fail(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


@dataclass(frozen=True)
class ScheduleSlot:
    """One compiled slot row. ``block`` and ``position`` are 1-based."""

    block: int
    position: int
    ordinal: int
    arm_id: str


@dataclass(frozen=True)
class CompiledSchedule:
    """A fully validated immutable schedule plus its canonical digest."""

    algorithm_id: str
    schedule_id: str
    protocol_digest: str
    seed: int
    blocks: int
    slots_per_block: int
    slots: tuple[ScheduleSlot, ...]
    schedule_digest: str


@dataclass(frozen=True)
class ScheduleSpec:
    """Private scheduling input carrier; not a second v1 protocol document."""

    schedule_id: str
    mode: str
    blocks: int
    slots_per_block: int
    seed: int
    multiplicities: tuple[ArmMultiplicity, ...]
    explicit_orders: tuple[tuple[str, ...], ...] | None
    protocol_digest: str


def rows_from_slots(slots: tuple[ScheduleSlot, ...]) -> tuple[tuple[str, ...], ...]:
    """Return the block/position grid implied by a slot tuple."""

    if not slots:  # pragma: no cover - guarded by callers
        return ()
    blocks = max(slot.block for slot in slots)
    width = max(slot.position for slot in slots)
    grid: list[list[str]] = [[""] * width for _ in range(blocks)]
    for slot in slots:
        grid[slot.block - 1][slot.position - 1] = slot.arm_id
    return tuple(tuple(row) for row in grid)


def _validate_multiplicities(
    multiplicities: tuple[ArmMultiplicity, ...], slots_per_block: int
) -> tuple[tuple[str, ...], dict[str, int]]:
    arms = tuple(sorted(item.arm_id for item in multiplicities))
    if len(set(arms)) != len(arms):
        raise _fail("arm multiplicities must be unique", "arm_multiplicity")
    if not 2 <= len(arms) <= MAX_ARMS:
        raise _fail(
            f"the schedule requires between 2 and {MAX_ARMS} arms",
            "arm_multiplicity",
        )
    counts: dict[str, int] = {}
    for item in multiplicities:
        arm_id = validate_semantic_id(item.arm_id, "arm_multiplicity[].arm_id")
        counts[arm_id] = require_positive_int(
            item.slots_per_block, "arm_multiplicity[].slots_per_block"
        )
    if slots_per_block > MAX_SLOTS_PER_BLOCK:
        raise _fail(
            f"slots_per_block exceeds the {MAX_SLOTS_PER_BLOCK} budget",
            "schedule.slots_per_block",
        )
    if sum(counts.values()) != slots_per_block:
        raise _fail(
            "arm multiplicities must sum to schedule.slots_per_block",
            "schedule.slots_per_block",
        )
    return arms, counts


def _verify_grid(
    rows: tuple[tuple[str, ...], ...],
    counts: Mapping[str, int],
    blocks: int,
    slots_per_block: int,
) -> None:
    """Independently re-check per-block and per-position counts."""

    if len(rows) != blocks:
        raise _fail("compiled schedule must contain exactly schedule.blocks blocks", "schedule.blocks")
    per_position: dict[tuple[int, str], int] = {}
    for index, row in enumerate(rows, start=1):
        if len(row) != slots_per_block:
            raise _fail(
                "each compiled block must contain schedule.slots_per_block slots",
                "schedule.slots_per_block",
            )
        if set(row) - set(counts):
            raise _fail("compiled block references an undeclared arm", "arm_multiplicity")
        block_counts = Counter(row)
        for arm_id, required in counts.items():
            if block_counts.get(arm_id, 0) != required:
                raise _fail(
                    "every block must contain the declared arm multiplicity",
                    "arm_multiplicity",
                )
        for position, arm_id in enumerate(row, start=1):
            key = (position, arm_id)
            per_position[key] = per_position.get(key, 0) + 1

    for arm_id, multiplicity in counts.items():
        numerator = blocks * multiplicity
        if numerator % slots_per_block != 0:
            raise _fail(
                "blocks * arm multiplicity must divide evenly across positions",
                "schedule.blocks",
            )
        expected = numerator // slots_per_block
        for position in range(1, slots_per_block + 1):
            observed = per_position.get((position, arm_id), 0)
            if observed != expected:
                raise _fail(
                    "the schedule is not exactly balanced for every position",
                    "schedule.blocks",
                )


def _balanced_rows(
    arms: tuple[str, ...], counts: Mapping[str, int], blocks: int, slots_per_block: int, seed: int
) -> tuple[tuple[str, ...], ...]:
    """Generate the frozen ``balanced-cyclic-v1`` block rows."""

    divisor = 0
    for arm_id in arms:
        divisor = gcd(divisor, counts[arm_id])
    tile_size = slots_per_block // divisor
    if blocks % tile_size != 0:
        raise _fail(
            f"schedule.blocks must be divisible by the balanced tile size {tile_size}",
            "schedule.blocks",
        )
    generator = Random(seed)
    rows: list[tuple[str, ...]] = []
    for _cycle in range(blocks // tile_size):
        tile = [arm_id for arm_id in arms for _ in range(counts[arm_id] // divisor)]
        generator.shuffle(tile)
        rotations = list(range(tile_size))
        generator.shuffle(rotations)
        for rotation in rotations:
            rows.append(
                tuple(
                    tile[(position + rotation) % tile_size]
                    for position in range(slots_per_block)
                )
            )
    return tuple(rows)


def _explicit_rows(
    orders: tuple[tuple[str, ...], ...] | None,
    counts: Mapping[str, int],
    blocks: int,
    slots_per_block: int,
) -> tuple[tuple[str, ...], ...]:
    if orders is None:
        raise _fail("explicit schedule mode requires explicit_orders", "schedule.explicit_orders")
    if len(orders) != blocks:
        raise _fail(
            "explicit_orders must declare exactly schedule.blocks blocks",
            "schedule.explicit_orders",
        )
    rows: list[tuple[str, ...]] = []
    for index, order in enumerate(orders):
        row = tuple(order)
        if len(row) != slots_per_block:
            raise _fail(
                "each explicit block must contain schedule.slots_per_block slots",
                f"schedule.explicit_orders[{index}]",
            )
        if set(row) - set(counts):
            raise _fail(
                "explicit block references an undeclared arm",
                f"schedule.explicit_orders[{index}]",
            )
        block_counts = Counter(row)
        for arm_id, required in counts.items():
            if block_counts.get(arm_id, 0) != required:
                raise _fail(
                    "explicit block arm counts must match arm_multiplicity",
                    f"schedule.explicit_orders[{index}]",
                )
        rows.append(row)
    return tuple(rows)


def _build_slots(
    rows: tuple[tuple[str, ...], ...], slots_per_block: int
) -> tuple[ScheduleSlot, ...]:
    slots: list[ScheduleSlot] = []
    ordinal = 1
    for block_index, row in enumerate(rows, start=1):
        for position, arm_id in enumerate(row, start=1):
            slots.append(
                ScheduleSlot(
                    block=block_index,
                    position=position,
                    ordinal=ordinal,
                    arm_id=arm_id,
                )
            )
            ordinal += 1
    return tuple(slots)


def schedule_document(schedule: CompiledSchedule) -> dict[str, Any]:
    """Return the closed canonical ``synthetic-schedule`` payload."""

    return {
        "kind": SCHEDULE_KIND,
        "schema_version": INTERNAL_SCHEMA_VERSION,
        "algorithm_id": schedule.algorithm_id,
        "schedule_id": schedule.schedule_id,
        "protocol_digest": schedule.protocol_digest,
        "seed": schedule.seed,
        "blocks": schedule.blocks,
        "slots_per_block": schedule.slots_per_block,
        "slots": [
            {
                "block": slot.block,
                "position": slot.position,
                "ordinal": slot.ordinal,
                "arm_id": slot.arm_id,
            }
            for slot in schedule.slots
        ],
    }


def _compile_spec(spec: ScheduleSpec) -> CompiledSchedule:
    """Compile one validated spec; the single core used by every caller."""

    if not isinstance(spec, ScheduleSpec):  # pragma: no cover - defensive
        raise _fail("compile core requires a ScheduleSpec", "schedule")
    schedule_id = validate_semantic_id(spec.schedule_id, "schedule.schedule_id")
    protocol_digest = validate_digest(spec.protocol_digest, "schedule.protocol_digest")
    seed = validate_uint64(spec.seed, "schedule.seed")
    blocks = validate_positive_int(spec.blocks, "schedule.blocks")
    slots_per_block = validate_positive_int(
        spec.slots_per_block, "schedule.slots_per_block"
    )
    if blocks > MAX_BLOCKS:
        raise _fail(
            f"schedule.blocks exceeds the {MAX_BLOCKS} budget", "schedule.blocks"
        )
    arms, counts = _validate_multiplicities(spec.multiplicities, slots_per_block)

    if spec.mode == SEEDED_MODE:
        algorithm_id = ALGORITHM_BALANCED
        rows = _balanced_rows(arms, counts, blocks, slots_per_block, seed)
    elif spec.mode == EXPLICIT_MODE:
        algorithm_id = ALGORITHM_EXPLICIT
        rows = _explicit_rows(spec.explicit_orders, counts, blocks, slots_per_block)
    else:  # pragma: no cover - guarded by BM-01 protocol validation
        raise _fail(f"unsupported schedule mode: {spec.mode!r}", "schedule.mode")

    _verify_grid(rows, counts, blocks, slots_per_block)
    slots = _build_slots(rows, slots_per_block)
    provisional = CompiledSchedule(
        algorithm_id=algorithm_id,
        schedule_id=schedule_id,
        protocol_digest=protocol_digest,
        seed=seed,
        blocks=blocks,
        slots_per_block=slots_per_block,
        slots=slots,
        schedule_digest="",
    )
    digest = content_digest(schedule_document(provisional))
    return CompiledSchedule(
        algorithm_id=algorithm_id,
        schedule_id=schedule_id,
        protocol_digest=protocol_digest,
        seed=seed,
        blocks=blocks,
        slots_per_block=slots_per_block,
        slots=slots,
        schedule_digest=digest,
    )


def _spec_from_bundle(bundle: ExperimentBundle) -> ScheduleSpec:
    schedule = bundle.protocol.schedule
    return ScheduleSpec(
        schedule_id=schedule.schedule_id,
        mode=schedule.mode,
        blocks=schedule.blocks,
        slots_per_block=schedule.slots_per_block,
        seed=schedule.seed,
        multiplicities=tuple(bundle.protocol.arm_multiplicity),
        explicit_orders=schedule.explicit_orders,
        protocol_digest=bundle.protocol_digest,
    )


def require_bundle_semantics(bundle: object) -> ExperimentBundle:
    """Re-run the complete BM-01 semantic bundle validation before compiling."""

    if not isinstance(bundle, ExperimentBundle):
        raise _fail("a validated ExperimentBundle is required", "bundle")
    validate_bundle(
        bundle.experiment,
        bundle.workload,
        bundle.protocol,
        bundle.adapter,
        bundle.workload_document,
    )
    declared = {arm.arm_id for arm in bundle.experiment.arms}
    multiplicity = {item.arm_id for item in bundle.protocol.arm_multiplicity}
    if multiplicity != declared:
        raise _fail(
            "protocol arm_multiplicity must cover exactly the experiment arms",
            "protocol.arm_multiplicity",
        )
    if len(declared) > MAX_ARMS:
        raise _fail(f"experiment exceeds the {MAX_ARMS}-arm budget", "arms")
    return bundle


def compile_schedule(bundle: ExperimentBundle) -> CompiledSchedule:
    """Compile the frozen schedule implied by one validated BM-01 bundle."""

    validated = require_bundle_semantics(bundle)
    return _compile_spec(_spec_from_bundle(validated))


def rows_from_compiled(schedule: CompiledSchedule) -> tuple[tuple[str, ...], ...]:
    """Return the compiled grid used by tests and structural replay."""

    return rows_from_slots(schedule.slots)


def validate_schedule_document(document: object) -> CompiledSchedule:
    """Re-validate stored ``synthetic-schedule`` bytes and recompute the digest."""

    doc = document
    if not isinstance(doc, Mapping):
        raise _fail("a schedule document must be an object", "schedule")
    if set(doc) != _SCHEDULE_KEYS:
        raise _fail(
            "a synthetic schedule must use the exact closed field set", "schedule"
        )
    if doc["kind"] != SCHEDULE_KIND or doc["schema_version"] != INTERNAL_SCHEMA_VERSION:
        raise _fail("schedule kind/version is invalid", "schedule.kind")
    algorithm_id = doc["algorithm_id"]
    if algorithm_id not in (ALGORITHM_BALANCED, ALGORITHM_EXPLICIT):
        raise _fail("schedule algorithm_id is not recognised", "schedule.algorithm_id")
    schedule_id = validate_semantic_id(doc["schedule_id"], "schedule.schedule_id")
    protocol_digest = validate_digest(doc["protocol_digest"], "schedule.protocol_digest")
    seed = validate_uint64(doc["seed"], "schedule.seed")
    blocks = require_positive_int(doc["blocks"], "schedule.blocks")
    slots_per_block = require_positive_int(
        doc["slots_per_block"], "schedule.slots_per_block"
    )
    if blocks > MAX_BLOCKS or slots_per_block > MAX_SLOTS_PER_BLOCK:
        raise _fail("stored schedule exceeds the frozen simulator budget", "schedule")

    raw_slots = doc["slots"]
    if not isinstance(raw_slots, list):
        raise _fail("schedule.slots must be an array", "schedule.slots")
    if len(raw_slots) != blocks * slots_per_block:
        raise _fail(
            "schedule.slots must contain exactly blocks x slots_per_block rows",
            "schedule.slots",
        )
    slots: list[ScheduleSlot] = []
    for index, raw_slot in enumerate(raw_slots):
        if not isinstance(raw_slot, Mapping) or set(raw_slot) != _SLOT_KEYS:
            raise _fail(
                "each schedule slot must use the exact closed field set",
                f"schedule.slots[{index}]",
            )
        block = raw_slot["block"]
        position = raw_slot["position"]
        ordinal = raw_slot["ordinal"]
        for name, value in (("block", block), ("position", position), ("ordinal", ordinal)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise _fail(
                    f"schedule slot {name} must be an integer",
                    f"schedule.slots[{index}].{name}",
                )
        expected_block = index // slots_per_block + 1
        expected_position = index % slots_per_block + 1
        if block != expected_block or position != expected_position:
            raise _fail(
                "schedule slots must be stored in block/position order",
                f"schedule.slots[{index}]",
            )
        if ordinal != index + 1:
            raise _fail(
                "schedule slot ordinals must be row-major from 1",
                f"schedule.slots[{index}].ordinal",
            )
        arm_id = raw_slot["arm_id"]
        if not isinstance(arm_id, str) or not arm_id:
            raise _fail(
                "schedule slot arm_id must be a non-empty string",
                f"schedule.slots[{index}].arm_id",
            )
        slots.append(
            ScheduleSlot(block=block, position=position, ordinal=ordinal, arm_id=arm_id)
        )

    rows = rows_from_slots(tuple(slots))
    counts = dict(Counter(rows[0])) if rows else {}
    _verify_grid(rows, counts, blocks, slots_per_block)
    return CompiledSchedule(
        algorithm_id=algorithm_id,
        schedule_id=schedule_id,
        protocol_digest=protocol_digest,
        seed=seed,
        blocks=blocks,
        slots_per_block=slots_per_block,
        slots=tuple(slots),
        schedule_digest=content_digest(doc),
    )
