"""Closed synthetic scenario fixture validation."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.codec import canonical_document_bytes
from quervant_bench.config.contracts import load_experiment_bundle
from quervant_bench.config.errors import (
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_NOT_IMPLEMENTED,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.execution.scenario import (
    SYNTHETIC_READINESS_LIMITS,
    load_synthetic_scenario,
    validate_scenario_document,
)

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
SCENARIO_NAME = "synthetic-scenario.v1.json"


def load_bundle():
    return load_experiment_bundle("synthetic-execution-smoke", EXPERIMENTS)


class ScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.path = self.evidence / SCENARIO_NAME
        shutil.copy(FIXTURES / SCENARIO_NAME, self.path)
        self.bundle = load_bundle()

    def document(self) -> dict:
        """Return a fresh copy of the pristine fixture, never a mutated file."""

        return json.loads((FIXTURES / SCENARIO_NAME).read_bytes())

    def rewrite(self, document: dict) -> None:
        self.path.write_bytes(canonical_document_bytes(document))

    def load(self):
        return load_synthetic_scenario(self.evidence, bundle=self.bundle)

    def assert_rejected(self, code: str = BM_IDENTITY_INVALID) -> None:
        with self.assertRaises(BenchError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, code)

    def test_scenario_loads_with_exact_declared_values(self) -> None:
        scenario = self.load()
        self.assertEqual(scenario.scenario_id, "synthetic-execution-smoke")
        self.assertEqual(scenario.control_source_arm_id, "baseline")
        self.assertEqual(scenario.metric_unit, "nanoseconds")
        self.assertEqual(scenario.clock_contract_id, "synthetic-logical-clock")
        self.assertEqual(
            scenario.values_for("baseline", "rare-query"),
            (1000000, 1050000, 950000),
        )
        self.assertEqual(
            scenario.values_for("candidate", "common-query"),
            (1000000, 1020000, 980000),
        )
        self.assertEqual(
            [(sample.arm_id, sample.lane_id) for sample in scenario.samples],
            sorted((sample.arm_id, sample.lane_id) for sample in scenario.samples),
        )
        observations = scenario.readiness_for("control", 0)
        self.assertEqual(len(observations), 2)
        self.assertEqual(SYNTHETIC_READINESS_LIMITS.min_intervals, 2)
        self.assertTrue(scenario.scenario_digest.startswith("sha256:"))

    def test_unknown_top_level_key_is_rejected(self) -> None:
        document = self.document()
        document["host_fingerprint"] = "not-declared"
        self.rewrite(document)
        self.assert_rejected()

    def test_unsorted_sample_records_are_rejected(self) -> None:
        document = self.document()
        document["samples"] = list(reversed(document["samples"]))
        self.rewrite(document)
        self.assert_rejected()

    def test_missing_arm_lane_pair_is_rejected(self) -> None:
        document = self.document()
        document["samples"] = document["samples"][:-1]
        self.rewrite(document)
        self.assert_rejected()

    def test_duplicate_arm_lane_pair_is_rejected(self) -> None:
        document = self.document()
        document["samples"][1] = dict(document["samples"][0])
        self.rewrite(document)
        self.assert_rejected()

    def test_wrong_sample_count_is_rejected(self) -> None:
        document = self.document()
        document["samples"][0]["values"] = document["samples"][0]["values"][:2]
        self.rewrite(document)
        self.assert_rejected()

    def test_non_positive_or_non_integer_samples_are_rejected(self) -> None:
        for bad in (0, -1, 1.5, True, "10", 9_223_372_036_854_775_808):
            document = self.document()
            document["samples"][0]["values"][0] = bad
            self.rewrite(document)
            self.assert_rejected()

    def test_other_metric_units_are_not_executable(self) -> None:
        document = self.document()
        document["metric_unit"] = "operations-per-second"
        self.rewrite(document)
        self.assert_rejected(BM_NOT_IMPLEMENTED)

    def test_wrong_experiment_identity_is_rejected(self) -> None:
        document = self.document()
        document["experiment_id"] = "synthetic-contract-smoke"
        self.rewrite(document)
        self.assert_rejected()

    def test_undeclared_control_source_arm_is_rejected(self) -> None:
        document = self.document()
        document["control_source_arm_id"] = "control-left"
        self.rewrite(document)
        self.assert_rejected()

    def test_non_canonical_bytes_are_rejected(self) -> None:
        self.path.write_text(json.dumps(self.document(), indent=2), encoding="utf-8")
        self.assert_rejected(BM_UNSAFE_INPUT)

    def test_oversized_scenario_is_rejected_before_parsing(self) -> None:
        self.path.write_bytes(b'{"kind":"synthetic-scenario"}' + b" " * 1_048_576)
        self.assert_rejected(BM_UNSAFE_INPUT)

    def test_missing_and_symlinked_scenarios_are_rejected(self) -> None:
        self.path.unlink()
        with self.assertRaises(BenchError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, BM_FILE_MISSING)

        target = self.root / "elsewhere.json"
        shutil.copy(FIXTURES / SCENARIO_NAME, target)
        os.symlink(target, self.path)
        with self.assertRaises(BenchError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

    def test_readiness_campaign_set_must_be_exact(self) -> None:
        document = self.document()
        document["readiness"] = document["readiness"][:-1]
        self.rewrite(document)
        self.assert_rejected()

        document = self.document()
        document["readiness"][2]["campaign_index"] = 0
        self.rewrite(document)
        self.assert_rejected()

        document = self.document()
        document["readiness"][1]["campaign_kind"] = "control"
        self.rewrite(document)
        self.assert_rejected()

    def test_observation_records_are_closed(self) -> None:
        document = self.document()
        document["readiness"][0]["observations"][0]["extra"] = 1
        self.rewrite(document)
        self.assert_rejected()

        document = self.document()
        document["readiness"][0]["observations"] = []
        self.rewrite(document)
        self.assert_rejected()

    def test_loaded_scenario_is_immutable(self) -> None:
        scenario = self.load()
        with self.assertRaises(Exception):
            scenario.scenario_id = "other"  # type: ignore[misc]
        with self.assertRaises(BenchError):
            scenario.values_for("baseline", "unknown-lane")
        with self.assertRaises(BenchError):
            scenario.readiness_for("treatment", 7)

    def test_validate_scenario_document_accepts_the_declared_fixture(self) -> None:
        scenario = validate_scenario_document(self.document(), bundle=self.bundle)
        self.assertEqual(scenario.scenario_id, "synthetic-execution-smoke")


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
