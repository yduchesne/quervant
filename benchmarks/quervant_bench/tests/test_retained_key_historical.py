"""PAR-01…PAR-04 and LEG-01/02: read-only historical non-equivalence evidence."""

from __future__ import annotations

import hashlib
import json
import statistics
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.codec import load_document
from quervant_bench.migrations import historical_retained_key as historical

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "retained-key"
LEDGER = FIXTURES / "historical-compatibility.v1.json"
PROTOCOL = REPO_ROOT / "benchmarks/pr15i_d3_c/protocol_v3r3.json"
EXTERNAL_ARCHIVE = REPO_ROOT / "target/pr15i-d3-c"
FROZEN_HASHES = {
    "benchmarks/pr15i_d3_c/protocol_v3r3.json": "c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c",
    "benchmarks/pr15i_d3_c/verify.py": "54e91d999ac923cf9e33289207d5a567786a7b318dbc46c5f24ed276f07fa2cd",
    "benchmarks/pr15i_d3_c/analysis_v3.py": "a028de728c44f553924faf8ab78b1f73da50d11e7bcc88ce9254c8c87d0d9603",
    "benchmarks/pr15i_d3_c/policy.py": "79674459d14ea41f6dcc9a9e3dec995bcab6cf8588d94b73b7e4212c331ed4bc",
    "benchmarks/pr15i_d3_c_t7/analysis.py": "212b0f9cadb6a11aede4eeabce382aecf438d195267aa6f67e0cf87ad85a2555",
    "benchmarks/pr15i_d3_c_t7/policy.py": "bcbdf13b6c466dc80002fa39204f9f110d39dadba14d755f2508bef47b80b440",
    "benchmarks/pr15i_d3_c_t7/verify_derived.py": "9c12b74caa8a657ef9a0b7ff8ad7aa3bc3872d160c84d15b144d6f457e51badc",
    "benchmarks/pr15i_d3_c_t7_f2/oracle.py": "66d3ef0224042c7d44e24b53d12c90d53218b0b5d570bb247a71290482708725",
    "benchmarks/pr15i_d3_c_t7_f2/verify_policy.py": "85097a82c2e65f304f45a00d1ec9ab1fd16cd59f343ffb23f79ab485ecf59ab5",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class HistoricalCompatibilityTests(unittest.TestCase):
    """PAR-01…PAR-04."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = read_json(LEDGER)

    def test_par_01_ledger_is_closed_and_matches_frozen_classes(self) -> None:
        self.assertEqual(
            set(self.ledger), {"kind", "schema_version", "rows"}
        )
        self.assertEqual(self.ledger["kind"], "retained-key-historical-compatibility")
        self.assertEqual(self.ledger["schema_version"], 1)
        rows = self.ledger["rows"]
        self.assertEqual([row["id"] for row in rows], [f"H{index:02d}" for index in range(1, 9)])
        for row in rows:
            self.assertEqual(
                set(row),
                {
                    "id",
                    "legacy_component",
                    "new_component",
                    "equivalence_class",
                    "required_input",
                    "expected_comparison",
                    "disposition_if_missing",
                    "notes",
                },
            )
            self.assertIn(row["equivalence_class"], historical.PARITY_CLASSES)
            self.assertEqual(
                row["equivalence_class"], historical.HISTORICAL_CLASSES[row["id"]]
            )
            self.assertTrue(row["required_input"])
            self.assertTrue(row["expected_comparison"])
            self.assertTrue(row["notes"])
        self.assertEqual(historical.HISTORICAL_CLASSES["H04"], historical.PARITY_NON_EQUIVALENT)
        self.assertEqual(historical.HISTORICAL_CLASSES["H05"], historical.PARITY_NON_EQUIVALENT)
        self.assertEqual(
            historical.HISTORICAL_CLASSES["H08"], historical.PARITY_EVIDENCE_UNAVAILABLE
        )

    def test_par_02_missing_or_empty_archive_is_unavailable(self) -> None:
        result = historical.assess_historical_evidence(
            archive_root=None, protocol_path=PROTOCOL
        )
        self.assertEqual(result["historical_archive"], historical.ARCHIVE_UNAVAILABLE)
        self.assertEqual(
            result["historical_numeric_parity"], historical.PARITY_NOT_EXECUTED
        )
        self.assertEqual(
            result["historical_decision_parity"], historical.PARITY_NOT_EXECUTED
        )
        self.assertEqual(
            result["historical_acceptance_gate"],
            historical.HISTORICAL_ACCEPTANCE_GATE_BLOCKED,
        )
        self.assertEqual(result["legacy_paths_retired"], "NO")
        self.assertEqual(result["protocol_sha256"], historical.PINNED_PROTOCOL_SHA256)

        with tempfile.TemporaryDirectory() as temporary:
            stub = Path(temporary) / "archive"
            stub.mkdir()
            empty = historical.assess_historical_evidence(
                archive_root=stub, protocol_path=PROTOCOL
            )
        self.assertEqual(empty["historical_archive"], historical.ARCHIVE_UNAVAILABLE)
        self.assertEqual(
            empty["historical_numeric_parity"], historical.PARITY_NOT_EXECUTED
        )

        if EXTERNAL_ARCHIVE.exists():
            current = historical.assess_historical_evidence(
                archive_root=EXTERNAL_ARCHIVE, protocol_path=PROTOCOL
            )
            self.assertEqual(
                current["historical_archive"], historical.ARCHIVE_UNAVAILABLE
            )

    def test_par_03_lower_middle_of_four_is_not_an_exact_median(self) -> None:
        def median4(values: list[int]) -> int:
            return sorted(values)[1]

        values = [1, 2, 100, 200]
        self.assertEqual(median4(values), 2)
        self.assertEqual(statistics.median(values), 51)
        self.assertNotEqual(median4(values), statistics.median(values))
        source = (REPO_ROOT / "benchmarks/pr15i_d3_c/verify.py").read_text(encoding="utf-8")
        self.assertIn("def median4(v): return sorted(v)[1]", source)
        self.assertEqual(
            historical.HISTORICAL_CLASSES["H04"], historical.PARITY_NON_EQUIVALENT
        )

    def test_par_04_threshold_filter_and_memory_contracts_differ(self) -> None:
        policy_source = (REPO_ROOT / "benchmarks/pr15i_d3_c/analysis_v3.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("within_arm_exclusion_cap_100k_medium_common", policy_source)
        self.assertIn("within_arm_exclusion_cap_other", policy_source)
        historical_protocol = load_document(PROTOCOL)
        self.assertEqual(historical_protocol["n_values"], [10000, 100000])
        self.assertEqual(historical_protocol["blocks"], 12)
        self.assertEqual(historical_protocol["classes"], ["absent", "rare", "medium", "common"])
        self.assertEqual(historical_protocol["k_values"], [1, 10, 32, 64, 100, 128, 256, 512, 1024])
        new_policy = load_document(
            REPO_ROOT
            / "benchmarks/experiments/synthetic-retained-key-reference/policy-profile.v1.json"
        )
        self.assertEqual(
            [rule["arm_id"] for rule in new_policy["resource_rules"]],
            ["exact-set", "linear", "prefilter"],
        )
        self.assertEqual(
            {rule["resource_id"] for rule in new_policy["resource_rules"]},
            {"aux-memory-bytes"},
        )
        self.assertEqual(
            historical.HISTORICAL_CLASSES["H05"], historical.PARITY_NON_EQUIVALENT
        )

    def test_par_05_synthetic_stand_in_cannot_authenticate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            root.mkdir()
            (root / "synthetic-scenario.v1.json").write_bytes(
                (REPO_ROOT / "benchmarks/experiments/synthetic-retained-key-reference/synthetic-scenario.v1.json").read_bytes()
            )
            result = historical.assess_historical_evidence(
                archive_root=root, protocol_path=PROTOCOL
            )
        self.assertEqual(result["historical_archive"], historical.ARCHIVE_UNAVAILABLE)
        self.assertEqual(
            result["historical_numeric_parity"], historical.PARITY_NOT_EXECUTED
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            root.mkdir()
            for campaign in historical.REQUIRED_CAMPAIGNS:
                (root / campaign).mkdir()
                (root / campaign / "manifest.json").write_text(
                    json.dumps(
                        {
                            "schema": "pr15i-d3c-manifest-v1",
                            "campaign": campaign,
                            "kind": "control" if campaign == historical.REQUIRED_CONTROL_CAMPAIGN else "four_arm",
                            "protocol_sha256": "0" * 64,
                            "source_base_sha": historical.PINNED_BASE_SHA,
                            "source_experiment_sha": historical.PINNED_EXPERIMENT_SHA,
                        }
                    ),
                    encoding="utf-8",
                )
                (root / campaign / "authorization.json").write_text("{}", encoding="utf-8")
            result = historical.assess_historical_evidence(
                archive_root=root, protocol_path=PROTOCOL
            )
        self.assertEqual(
            result["historical_archive"], historical.ARCHIVE_FAILED_AUTHENTICATION
        )
        self.assertEqual(
            result["historical_numeric_parity"], historical.PARITY_NOT_EXECUTED
        )


class LegacyPreservationTests(unittest.TestCase):
    """LEG-01/LEG-02."""

    def test_leg_01_historical_sources_remain_byte_identical(self) -> None:
        for relative, digest in FROZEN_HASHES.items():
            self.assertEqual(sha256(REPO_ROOT / relative), digest, relative)

    def test_leg_02_assessor_does_not_mutate_historical_roots(self) -> None:
        before = {relative: sha256(REPO_ROOT / relative) for relative in FROZEN_HASHES}
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            archive.mkdir()
            historical.assess_historical_evidence(
                archive_root=archive, protocol_path=PROTOCOL
            )
        after = {relative: sha256(REPO_ROOT / relative) for relative in FROZEN_HASHES}
        self.assertEqual(before, after)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
