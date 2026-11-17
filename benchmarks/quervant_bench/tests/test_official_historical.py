"""O09-HIS: read-only historical parity and legacy byte identity."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BenchError,
)
from quervant_bench.official import historical
from quervant_bench.tests import official_support as support


class LegacyIdentityTests(unittest.TestCase):
    def test_o09_his_01_frozen_legacy_sources_match_the_checked_in_manifest(self) -> None:
        digest = historical.verify_legacy_sources_unchanged(
            support.legacy_manifest(), support.REPO_ROOT
        )
        self.assertTrue(digest.startswith("sha256:"))

    def test_o09_his_02_changed_legacy_source_is_rejected(self) -> None:
        manifest = support.legacy_manifest()
        manifest["files"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(BenchError) as raised:
            historical.verify_legacy_sources_unchanged(manifest, support.REPO_ROOT)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_his_03_manifest_path_set_is_checked(self) -> None:
        manifest = support.legacy_manifest()
        manifest["files"] = manifest["files"][:-1]
        with self.assertRaises(BenchError):
            historical.verify_legacy_sources_unchanged(manifest, support.REPO_ROOT)

    def test_o09_his_04_manifest_duplicate_path_is_rejected(self) -> None:
        manifest = support.legacy_manifest()
        manifest["files"] = manifest["files"] + [dict(manifest["files"][0])]
        with self.assertRaises(BenchError):
            historical.verify_legacy_sources_unchanged(manifest, support.REPO_ROOT)

    def test_o09_his_05_generated_manifest_is_deterministic(self) -> None:
        first = historical.build_legacy_manifest(support.REPO_ROOT)
        second = historical.build_legacy_manifest(support.REPO_ROOT)
        self.assertEqual(first, second)
        self.assertNotIn("benchmarks/pr15d/harness/run.py.bak", [entry["path"] for entry in first["files"]])

    def test_o09_his_06_legacy_manifest_is_committed_and_matches(self) -> None:
        committed = json.loads(
            (support.REPO_ROOT / historical.LEGACY_MANIFEST_PATH).read_text(encoding="utf-8")
        )
        self.assertEqual(
            historical.build_legacy_manifest(support.REPO_ROOT),
            committed,
        )


class ParityAssessmentTests(unittest.TestCase):
    def test_o09_his_07_missing_retained_key_archive_is_unavailable(self) -> None:
        assessment = historical.assess_required_historical_parity(
            study_id="retained-key-topk-real-v1",
            archive_root=Path("/nonexistent/archive-root"),
            reviewer_approval_id="reviewer",
            rows=[support.parity_row()],
            legacy_manifest=support.legacy_manifest(),
        )
        self.assertEqual(assessment["status"], "EVIDENCE_UNAVAILABLE")
        self.assertIn("authentic-retained-key-archive-root-unavailable", assessment["reasons"])

    def test_o09_his_08_cross_engine_without_archive_is_unavailable(self) -> None:
        assessment = historical.assess_required_historical_parity(
            study_id="cross-engine-keyword-real-v1",
            reviewer_approval_id="reviewer",
            rows=[support.parity_row()],
            legacy_manifest=support.legacy_manifest(),
        )
        self.assertEqual(assessment["status"], "EVIDENCE_UNAVAILABLE")

    def test_o09_his_09_no_rows_is_not_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, expected = support.approved_archive(Path(temporary) / "archive")
            assessment = historical.assess_required_historical_parity(
                study_id="cross-engine-keyword-real-v1",
                archive_root=root,
                cross_engine_expected=expected,
                reviewer_approval_id="reviewer",
                mapping_status="NON_EQUIVALENT_CONTRACT",
                rows=[],
                legacy_manifest=support.legacy_manifest(),
            )
        self.assertNotEqual(assessment["status"], "PASS")
        self.assertIn("no-parity-rows-executed", assessment["reasons"])

    def test_o09_his_10_failed_row_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, expected = support.approved_archive(Path(temporary) / "archive")
            row = support.parity_row()
            row["status"] = "FAILED"
            assessment = historical.assess_required_historical_parity(
                study_id="cross-engine-keyword-real-v1",
                archive_root=root,
                cross_engine_expected=expected,
                reviewer_approval_id="reviewer",
                mapping_status="NON_EQUIVALENT_CONTRACT",
                rows=[row],
                legacy_manifest=support.legacy_manifest(),
            )
        self.assertEqual(assessment["status"], "FAILED")

    def test_o09_his_11_non_equivalent_row_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, expected = support.approved_archive(Path(temporary) / "archive")
            row = support.parity_row()
            row["status"] = "NON_EQUIVALENT_CONTRACT"
            assessment = historical.assess_required_historical_parity(
                study_id="cross-engine-keyword-real-v1",
                archive_root=root,
                cross_engine_expected=expected,
                reviewer_approval_id="reviewer",
                mapping_status="NON_EQUIVALENT_CONTRACT",
                rows=[row],
                legacy_manifest=support.legacy_manifest(),
            )
        self.assertEqual(assessment["status"], "NON_EQUIVALENT_CONTRACT")

    def test_o09_his_12_approved_mapping_passes_in_test_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, expected = support.approved_archive(Path(temporary) / "archive")
            assessment = historical.assess_required_historical_parity(
                study_id="cross-engine-keyword-real-v1",
                archive_root=root,
                cross_engine_expected=expected,
                reviewer_approval_id="reviewer",
                mapping_status="NON_EQUIVALENT_CONTRACT",
                rows=[support.parity_row()],
                legacy_manifest=support.legacy_manifest(),
            )
        self.assertEqual(assessment["status"], "PASS")
        self.assertEqual(
            (assessment["evidence_origin"], assessment["qualification_scope"]),
            ("real", "historical_replay"),
        )
        self.assertEqual(len(assessment["authenticated_archives"]), 1)

    def test_o09_his_13_pass_requires_authenticated_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, expected = support.approved_archive(Path(temporary) / "archive")
            (root / "notes.txt").write_text("changed", encoding="utf-8")
            assessment = historical.assess_required_historical_parity(
                study_id="cross-engine-keyword-real-v1",
                archive_root=root,
                cross_engine_expected=expected,
                reviewer_approval_id="reviewer",
                mapping_status="NON_EQUIVALENT_CONTRACT",
                rows=[support.parity_row()],
                legacy_manifest=support.legacy_manifest(),
            )
        self.assertNotEqual(assessment["status"], "PASS")

    def test_o09_his_14_retained_key_needs_authentic_policy_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            assessment = historical.assess_required_historical_parity(
                study_id="retained-key-topk-real-v1",
                archive_root=Path(temporary),
                reviewer_approval_id="reviewer",
                rows=[support.parity_row()],
                policy_inputs_available=False,
                mapping_status="PASS",
                legacy_manifest=support.legacy_manifest(),
            )
        self.assertNotEqual(assessment["status"], "PASS")
        self.assertEqual(assessment["policy_inputs_status"], "EVIDENCE_UNAVAILABLE")

    def test_o09_his_14b_parity_requires_scoped_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, expected = support.approved_archive(Path(temporary) / "archive")
            assessment = historical.assess_required_historical_parity(
                study_id="cross-engine-keyword-real-v1",
                archive_root=root,
                cross_engine_expected=expected,
                reviewer_approval_id="reviewer",
                mapping_status="NON_EQUIVALENT_CONTRACT",
                rows=[support.parity_row()],
                legacy_manifest=support.legacy_manifest(),
            )
            assessment["qualification_scope"] = "official"
            with self.assertRaises(BenchError):
                historical.validate_parity_assessment(assessment)

    def test_o09_his_14c_passing_row_without_tolerance_is_rejected(self) -> None:
        row = support.parity_row()
        row["approved_tolerance"] = None
        with self.assertRaises(BenchError):
            historical.validate_parity_row(row)

    def test_o09_his_14d_passing_assessment_needs_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, expected = support.approved_archive(Path(temporary) / "archive")
            assessment = historical.assess_required_historical_parity(
                study_id="cross-engine-keyword-real-v1",
                archive_root=root,
                cross_engine_expected=expected,
                reviewer_approval_id="reviewer",
                mapping_status="NON_EQUIVALENT_CONTRACT",
                rows=[support.parity_row()],
                legacy_manifest=support.legacy_manifest(),
            )
            assessment["reviewer_approval_id"] = None
            with self.assertRaises(BenchError) as raised:
                historical.validate_parity_assessment(assessment)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


class RetainedKeyArchiveTests(unittest.TestCase):
    def test_o09_his_15_real_archive_root_is_not_modified(self) -> None:
        root = historical.historical_archive_root()
        if not root.is_dir():  # pragma: no cover - authenticated history unavailable
            self.skipTest("no authentic retained-key archive root on this host")
        before = sorted(
            (path.name, path.stat().st_size, path.stat().st_mtime_ns)
            for path in root.iterdir()
        )
        try:
            historical.audit_retained_key_archive(root, "d3c-v3r3-base-aa-01")
        except BenchError:
            pass
        after = sorted(
            (path.name, path.stat().st_size, path.stat().st_mtime_ns)
            for path in root.iterdir()
        )
        self.assertEqual(before, after)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
