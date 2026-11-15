"""SCHED-01…SCHED-10: frozen schedule compilation and independent oracles."""

from __future__ import annotations

import json
import random
import time
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from unittest import mock

from quervant_bench.config.codec import content_digest
from quervant_bench.config.contracts import (
    ArmMultiplicity,
    load_experiment_bundle,
)
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BenchError
from quervant_bench.config.identity import validate_uint64
from quervant_bench.protocol.schedule import (
    ALGORITHM_BALANCED,
    ALGORITHM_EXPLICIT,
    ScheduleSpec,
    _compile_spec,
    compile_schedule,
    schedule_document,
    validate_schedule_document,
)

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
GOLDEN = json.loads((FIXTURES / "golden-schedule.v1.json").read_text(encoding="utf-8"))
PROTOCOL_DIGEST = "sha256:" + "0" * 64


def load_bundle():
    return load_experiment_bundle("synthetic-execution-smoke", EXPERIMENTS)


def spec(
    multiplicities,
    blocks,
    slots_per_block,
    *,
    seed: int = 42,
    mode: str = "seeded-balanced",
    explicit=None,
):
    return ScheduleSpec(
        schedule_id="synthetic-execution-balanced",
        mode=mode,
        blocks=blocks,
        slots_per_block=slots_per_block,
        seed=seed,
        multiplicities=tuple(
            ArmMultiplicity(arm_id=arm_id, slots_per_block=count)
            for arm_id, count in multiplicities
        ),
        explicit_orders=explicit,
        protocol_digest=PROTOCOL_DIGEST,
    )


def rows(schedule) -> list[list[str]]:
    grid: dict[int, dict[int, str]] = {}
    for slot in schedule.slots:
        grid.setdefault(slot.block, {})[slot.position] = slot.arm_id
    return [
        [grid[block][position] for position in sorted(grid[block])]
        for block in sorted(grid)
    ]


class ScheduleTests(unittest.TestCase):
    def test_sched_01_two_arm_seeded_sequence_is_the_literal_golden(self) -> None:
        compiled = _compile_spec(spec([("baseline", 1), ("candidate", 1)], 4, 2))
        self.assertEqual(compiled.algorithm_id, ALGORITHM_BALANCED)
        self.assertEqual(rows(compiled), GOLDEN["rows"])
        self.assertEqual(rows(compile_schedule(load_bundle())), GOLDEN["rows"])

        again = _compile_spec(spec([("baseline", 1), ("candidate", 1)], 4, 2))
        self.assertEqual(compiled.slots, again.slots)
        self.assertEqual(compiled.schedule_digest, again.schedule_digest)

    def test_sched_02_four_arm_geometry_is_position_balanced(self) -> None:
        arms = ("alpha", "beta", "gamma", "delta")
        compiled = _compile_spec(
            spec([(arm, 2) for arm in arms], 12, 8)
        )
        self.assertEqual(len(compiled.slots), 96)
        per_arm = Counter(slot.arm_id for slot in compiled.slots)
        self.assertEqual(set(per_arm), set(arms))
        for arm in arms:
            self.assertEqual(per_arm[arm], 24)
        per_position = Counter((slot.position, slot.arm_id) for slot in compiled.slots)
        for arm in arms:
            for position in range(1, 9):
                self.assertEqual(per_position[(position, arm)], 3)
        self.assertEqual(len(rows(compiled)), 12)
        for row in rows(compiled):
            self.assertEqual(Counter(row), {arm: 2 for arm in arms})

    def test_sched_03_explicit_orders_are_preserved_byte_for_byte(self) -> None:
        orders = tuple(tuple(row) for row in GOLDEN["rows"])
        explicit = _compile_spec(
            spec(
                [("baseline", 1), ("candidate", 1)],
                4,
                2,
                mode="explicit",
                explicit=orders,
            )
        )
        self.assertEqual(explicit.algorithm_id, ALGORITHM_EXPLICIT)
        self.assertEqual(rows(explicit), [list(row) for row in GOLDEN["rows"]])
        document = schedule_document(explicit)
        self.assertEqual(
            [slot["arm_id"] for slot in document["slots"]],
            [slot.arm_id for slot in explicit.slots],
        )

        bad_counts = (("baseline", "baseline"), ("candidate", "candidate"),
                      ("candidate", "baseline"), ("baseline", "candidate"))
        with self.assertRaises(BenchError) as caught:
            _compile_spec(
                spec(
                    [("baseline", 1), ("candidate", 1)],
                    4,
                    2,
                    mode="explicit",
                    explicit=bad_counts,
                )
            )
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

        unknown = tuple(("baseline", "gamma") for _ in range(4))
        with self.assertRaises(BenchError):
            _compile_spec(
                spec(
                    [("baseline", 1), ("candidate", 1)],
                    4,
                    2,
                    mode="explicit",
                    explicit=unknown,
                )
            )

    def test_sched_04_position_unbalanced_explicit_orders_are_rejected(self) -> None:
        unbalanced = tuple(("baseline", "candidate") for _ in range(2))
        with self.assertRaises(BenchError) as caught:
            _compile_spec(
                spec(
                    [("baseline", 1), ("candidate", 1)],
                    2,
                    2,
                    mode="explicit",
                    explicit=unbalanced,
                )
            )
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_sched_05_blocks_not_divisible_by_tile_is_rejected(self) -> None:
        with self.assertRaises(BenchError) as caught:
            _compile_spec(spec([("baseline", 1), ("candidate", 1)], 3, 2))
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "schedule.blocks")

    def test_sched_06_boundary_and_over_limit_geometries(self) -> None:
        boundary = _compile_spec(
            spec([("baseline", 8), ("candidate", 8)], 256, 16)
        )
        self.assertEqual(len(boundary.slots), 4096)
        per_position = Counter((slot.position, slot.arm_id) for slot in boundary.slots)
        self.assertEqual(per_position[(1, "baseline")], 128)
        self.assertEqual(per_position[(16, "candidate")], 128)

        with self.assertRaises(BenchError):
            _compile_spec(spec([("baseline", 8), ("candidate", 8)], 257, 16))
        with self.assertRaises(BenchError):
            _compile_spec(spec([("baseline", 8), ("candidate", 9)], 4, 17))
        with self.assertRaises(BenchError):
            _compile_spec(spec([("baseline", 1), ("candidate", 1)], 4, 17))

    def test_sched_07_seed_identity_is_validated_and_deterministic(self) -> None:
        for seed in (0, 1, 42, 0x5EEDB001, 2**32 - 1, 2**64 - 1):
            first = _compile_spec(spec([("baseline", 1), ("candidate", 1)], 4, 2, seed=seed))
            second = _compile_spec(spec([("baseline", 1), ("candidate", 1)], 4, 2, seed=seed))
            self.assertEqual(first.slots, second.slots)
            self.assertEqual(first.schedule_digest, second.schedule_digest)
            self.assertEqual(first.seed, seed)
        with self.assertRaises(BenchError):
            validate_uint64(2**64, "schedule.seed")
        with self.assertRaises(BenchError):
            validate_uint64(True, "schedule.seed")

    def test_sched_08_declaration_order_never_changes_randomized_rows(self) -> None:
        bundle = load_bundle()
        reordered = replace(
            bundle,
            experiment=replace(bundle.experiment, arms=tuple(reversed(bundle.experiment.arms))),
            protocol=replace(
                bundle.protocol,
                arm_multiplicity=tuple(reversed(bundle.protocol.arm_multiplicity)),
            ),
        )
        baseline = compile_schedule(bundle)
        self.assertEqual(compile_schedule(reordered).slots, baseline.slots)

        document = dict(bundle.protocol_document)
        document["arm_multiplicity"] = list(reversed(document["arm_multiplicity"]))
        rebound = compile_schedule(replace(bundle, protocol_document=document))
        self.assertEqual(rebound.slots, baseline.slots)
        self.assertNotEqual(rebound.protocol_digest, baseline.protocol_digest)
        self.assertNotEqual(rebound.schedule_digest, baseline.schedule_digest)

    def test_sched_09_tampered_schedule_documents_are_rejected(self) -> None:
        compiled = _compile_spec(spec([("baseline", 1), ("candidate", 1)], 4, 2))
        document = schedule_document(compiled)
        self.assertEqual(validate_schedule_document(document).slots, compiled.slots)

        unbalanced = json.loads(json.dumps(document))
        unbalanced["slots"][0]["arm_id"] = unbalanced["slots"][1]["arm_id"]
        with self.assertRaises(BenchError):
            validate_schedule_document(unbalanced)

        wrong_ordinal = json.loads(json.dumps(document))
        wrong_ordinal["slots"][2]["ordinal"] = 99
        with self.assertRaises(BenchError):
            validate_schedule_document(wrong_ordinal)

        wrong_count = json.loads(json.dumps(document))
        wrong_count["blocks"] = 8
        with self.assertRaises(BenchError):
            validate_schedule_document(wrong_count)

        changed_seed = json.loads(json.dumps(document))
        changed_seed["seed"] = 43
        reseeded = validate_schedule_document(changed_seed)
        self.assertEqual(reseeded.slots, compiled.slots)
        self.assertNotEqual(
            content_digest(changed_seed), compiled.schedule_digest
        )

        changed_digest = json.loads(json.dumps(document))
        changed_digest["protocol_digest"] = "sha256:" + "1" * 64
        rebound = validate_schedule_document(changed_digest)
        self.assertNotEqual(rebound.protocol_digest, compiled.protocol_digest)
        self.assertNotEqual(
            content_digest(changed_digest), compiled.schedule_digest
        )

    def test_sched_10_no_global_entropy_or_clock_is_consulted(self) -> None:
        def forbidden(*_args, **_kwargs):
            raise AssertionError("global entropy or clock was consulted")

        with (
            mock.patch.object(random, "seed", forbidden),
            mock.patch.object(time, "time", forbidden),
            mock.patch.object(time, "perf_counter", forbidden),
        ):
            compiled = _compile_spec(
                spec([("baseline", 1), ("candidate", 1)], 4, 2)
            )
        self.assertEqual(rows(compiled), GOLDEN["rows"])


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
