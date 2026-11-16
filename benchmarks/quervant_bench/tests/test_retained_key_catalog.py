"""CAT-01…CAT-04 and CLI-01 evidence for the retained-key reference catalog."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from quervant_bench import cli
from quervant_bench.analysis.profiles import read_analysis_profile
from quervant_bench.analysis.policy import read_policy_profile
from quervant_bench.config.codec import canonical_document_bytes, content_digest, load_document
from quervant_bench.config.contracts import load_experiment_bundle
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.execution.scenario import validate_scenario_document
from quervant_bench.migrations.retained_key import (
    REFERENCE_EXPERIMENT_ID,
    REQUIRED_CATALOG_FILES,
    load_reference_bundle,
    reference_catalog_root,
)
from quervant_bench.qualification.identity import (
    SOURCE_DIRECTORIES,
    compute_source_set_digest,
    source_roster,
)
from quervant_bench.tests.test_qualification_contracts import materialize_source_tree

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
CATALOG = EXPERIMENTS / REFERENCE_EXPERIMENT_ID
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "retained-key"
LEDGER = FIXTURES / "reference-expectations.v1.json"

ARMS = ["baseline", "linear", "prefilter", "exact-set"]
LANES = [
    "large-absent",
    "large-common",
    "large-medium",
    "large-rare",
    "small-absent",
    "small-common",
    "small-medium",
    "small-rare",
]
OLD_SMOKE_DIGESTS = {
    "experiment.yaml": "sha256:65c0f4863b4b88a3a6adb5b1414447682c0dd00f91bcd5e11dedc477676c3b3c",
    "workloads.yaml": "sha256:2cc648557b95a10beeb26ca19b107ba839b3a1fc0bfd563bd7331abb8fa1fee9",
    "protocol.yaml": "sha256:58068563b3977c5cee80417f94765dacd4471b9f3de77ae7688b21f60acc2015",
    "analysis-profile.v1.json": "sha256:1f8b4ae6fb7a2f1c632c235d096ed853151fb964e7db0c211766f753652a6af1",
    "policy-profile.v1.json": "sha256:d1e2c0b681ba90ea0f13e16acf9cd7bd5ff5f27b7445da04d4f72b034dab0e90",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class CatalogTests(unittest.TestCase):
    """CAT-01…CAT-04 and CLI-01."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_reference_bundle(EXPERIMENTS)
        cls.ledger = read_json(LEDGER)
        cls.scenario = read_json(CATALOG / "synthetic-scenario.v1.json")

    def test_cat_01_bundle_is_valid_exact_and_fully_digest_bound(self) -> None:
        self.assertEqual(self.bundle.experiment.experiment_id, REFERENCE_EXPERIMENT_ID)
        self.assertEqual(
            [arm.arm_id for arm in self.bundle.experiment.arms], ARMS
        )
        self.assertEqual(
            tuple(item.arm_id for item in self.bundle.protocol.arm_multiplicity),
            (
                "baseline",
                "linear",
                "prefilter",
                "exact-set",
            ),
        )
        self.assertEqual(
            [lane.lane_id for lane in self.bundle.workload.lanes], LANES
        )
        self.assertEqual(self.bundle.protocol.protocol_id, "retained-key-synthetic-protocol")
        self.assertEqual(
            self.bundle.protocol.workload_digest,
            content_digest(load_document(CATALOG / "workloads.yaml")),
        )
        analysis = read_analysis_profile(CATALOG, self.bundle)
        policy = read_policy_profile(CATALOG, self.bundle)
        self.assertEqual(
            self.bundle.experiment.analysis.analysis_digest, analysis.digest
        )
        self.assertEqual(self.bundle.experiment.policy.policy_digest, policy.digest)
        self.assertEqual(self.bundle.protocol.policy.policy_digest, policy.digest)
        self.assertEqual(
            sorted(entry.name for entry in CATALOG.iterdir()),
            sorted(REQUIRED_CATALOG_FILES),
        )
        for name in (
            "analysis-profile.v1.json",
            "policy-profile.v1.json",
            "resource-observations.v1.json",
            "synthetic-scenario.v1.json",
        ):
            payload = (CATALOG / name).read_bytes()
            self.assertEqual(
                payload, canonical_document_bytes(load_document(CATALOG / name))
            )

    def test_cat_02_altered_workload_or_profile_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "catalog"
            shutil.copytree(CATALOG, root / REFERENCE_EXPERIMENT_ID)
            workload = load_document(root / REFERENCE_EXPERIMENT_ID / "workloads.yaml")
            workload["lanes"][0]["params"]["corpus_size"] = 65
            write_json(root / REFERENCE_EXPERIMENT_ID / "workloads.yaml", workload)
            with self.assertRaises(BenchError) as raised:
                load_experiment_bundle(REFERENCE_EXPERIMENT_ID, root)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "catalog"
            shutil.copytree(CATALOG, root / REFERENCE_EXPERIMENT_ID)
            experiment = load_document(root / REFERENCE_EXPERIMENT_ID / "experiment.yaml")
            experiment["policy"]["policy_digest"] = "sha256:" + "1" * 64
            write_json(root / REFERENCE_EXPERIMENT_ID / "experiment.yaml", experiment)
            with self.assertRaises(BenchError) as raised:
                load_experiment_bundle(REFERENCE_EXPERIMENT_ID, root)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "catalog"
            shutil.copytree(CATALOG, root / REFERENCE_EXPERIMENT_ID)
            profile = read_json(root / REFERENCE_EXPERIMENT_ID / "analysis-profile.v1.json")
            profile["bootstrap"]["resamples"] = 999
            (root / REFERENCE_EXPERIMENT_ID / "analysis-profile.v1.json").write_bytes(
                canonical_document_bytes(profile)
            )
            with self.assertRaises(BenchError):
                read_analysis_profile(root / REFERENCE_EXPERIMENT_ID, self.bundle)

    def test_cat_03_literal_matrix_and_independent_effects(self) -> None:
        self.assertEqual(
            set(self.ledger),
            {
                "kind",
                "schema_version",
                "experiment_id",
                "evidence_origin",
                "qualification_scope",
                "arm_ids",
                "lane_ids",
                "schedule",
                "sample_values",
                "expected_effects",
                "expected_evidence_origin",
                "expected_qualification_scope",
            },
        )
        self.assertEqual(self.ledger["kind"], "simulated-retained-key-expectations")
        self.assertEqual(self.ledger["experiment_id"], REFERENCE_EXPERIMENT_ID)
        self.assertEqual(self.ledger["arm_ids"], ARMS)
        self.assertEqual(self.ledger["lane_ids"], LANES)
        self.assertEqual(
            self.ledger["schedule"],
            {
                "blocks": 4,
                "slots_per_block": 8,
                "slots_per_arm_per_block": 2,
                "controls": 1,
                "treatments": 2,
                "seed": 42,
            },
        )
        self.assertEqual(
            self.ledger["expected_effects"],
            {
                "linear": "0.940000000000",
                "prefilter": "0.790000000000",
                "exact-set": "0.815000000000",
            },
        )
        observed: dict[tuple[str, str], list[int]] = {}
        for sample in self.scenario["samples"]:
            observed[(sample["arm_id"], sample["lane_id"])] = list(sample["values"])
        for arm_id in ARMS:
            for lane_id in LANES:
                self.assertEqual(
                    observed[(arm_id, lane_id)],
                    self.ledger["sample_values"][arm_id],
                )
        baseline = self.ledger["sample_values"]["baseline"]
        baseline_median = Fraction(sorted(baseline)[1])
        for arm_id in ("linear", "prefilter", "exact-set"):
            values = self.ledger["sample_values"][arm_id]
            median = Fraction(sorted(values)[1])
            ratio = median / baseline_median
            self.assertEqual(
                Fraction(Decimal(self.ledger["expected_effects"][arm_id])), ratio
            )
        self.assertEqual(len(observed), len(ARMS) * len(LANES))

    def test_cat_04_invalid_scenario_samples_are_rejected(self) -> None:
        base = copy.deepcopy(self.scenario)
        mutations = []

        zero = copy.deepcopy(base)
        zero["samples"][0]["values"] = [0, 1, 2]
        mutations.append(zero)

        floating = copy.deepcopy(base)
        floating["samples"][0]["values"] = [1.0, 2, 3]
        mutations.append(floating)

        missing = copy.deepcopy(base)
        missing["samples"].pop()
        mutations.append(missing)

        duplicate = copy.deepcopy(base)
        duplicate["samples"].append(copy.deepcopy(duplicate["samples"][0]))
        mutations.append(duplicate)

        unknown = copy.deepcopy(base)
        unknown["samples"][0]["lane_id"] = "large-unknown"
        mutations.append(unknown)

        wrong_count = copy.deepcopy(base)
        wrong_count["samples"][0]["values"] = [1, 2]
        mutations.append(wrong_count)

        for document in mutations:
            with self.subTest(document=document["samples"][0]):
                with self.assertRaises(BenchError):
                    validate_scenario_document(document, bundle=self.bundle)

    def test_cat_05_inspect_keeps_the_original_outcome_contract(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = cli.main(["inspect", "--experiment", REFERENCE_EXPERIMENT_ID])
        self.assertEqual(status, 0)
        self.assertEqual(stderr.getvalue(), "")
        outcome = json.loads(stdout.getvalue())
        self.assertEqual(outcome["kind"], "outcome")
        self.assertEqual(outcome["schema_version"], 1)
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["data"]["kind"], "inspect-summary")
        self.assertEqual(outcome["data"]["experiment_id"], REFERENCE_EXPERIMENT_ID)
        self.assertEqual(outcome["data"]["arm_ids"], ARMS)
        self.assertEqual(outcome["data"]["lane_ids"], LANES)
        self.assertEqual(outcome["data"]["evidence_origin"], "synthetic")
        self.assertEqual(outcome["data"]["qualification_scope"], "simulated")

    def test_cat_06_existing_smoke_catalog_bytes_are_unchanged(self) -> None:
        smoke = EXPERIMENTS / "synthetic-analysis-smoke"
        for name, digest in OLD_SMOKE_DIGESTS.items():
            self.assertEqual(content_digest(load_document(smoke / name)), digest, name)
        self.assertEqual(reference_catalog_root(), EXPERIMENTS.resolve())


class MigrationSourceRosterTests(unittest.TestCase):
    """ANC-03: the new migrations package is hashed and unsafe entries fail closed."""

    def test_anc_03_migration_modules_are_hashed_and_unsafe_entries_rejected(self) -> None:
        self.assertIn("benchmarks/quervant_bench/migrations", SOURCE_DIRECTORIES)
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_source_tree(Path(temporary) / "source")
            roster = source_roster(root)
            for name in (
                "__init__.py",
                "historical_retained_key.py",
                "offline.py",
                "retained_key.py",
            ):
                self.assertIn(
                    f"benchmarks/quervant_bench/migrations/{name}", roster
                )
            digest = compute_source_set_digest(root)

            untracked = (
                root / "benchmarks/quervant_bench/migrations/untracked.py"
            )
            untracked.write_text("# untracked\n", encoding="utf-8")
            with self.assertRaises(BenchError) as raised:
                source_roster(root)
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            untracked.unlink()

            tracked = root / "benchmarks/quervant_bench/migrations/retained_key.py"
            original = tracked.read_bytes()
            tracked.unlink()
            os.symlink(
                root / "benchmarks/quervant_bench/migrations/offline.py", tracked
            )
            with self.assertRaises(BenchError) as raised:
                source_roster(root)
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            tracked.unlink()
            tracked.write_bytes(original)
            self.assertEqual(compute_source_set_digest(root), digest)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
