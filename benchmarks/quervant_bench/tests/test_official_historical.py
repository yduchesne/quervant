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

    def test_o09_his_12_approved_mapping_is_computed_pending_review_only(self) -> None:
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
        self.assertEqual(assessment["status"], "COMPARISON_COMPUTED_PENDING_REVIEW")
        self.assertEqual(
            (assessment["evidence_origin"], assessment["qualification_scope"]),
            ("real", "historical_replay"),
        )
        self.assertEqual(len(assessment["authenticated_archives"]), 1)
        with self.assertRaises(BenchError):
            historical.require_parity_pass(assessment)

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
        document = {
            "kind": historical.PARITY_KIND,
            "schema_version": 1,
            "evidence_origin": "real",
            "qualification_scope": "historical_replay",
            "study_id": "cross-engine-keyword-real-v1",
            "status": "PASS",
            "rows": [support.parity_row()],
            "authenticated_archives": [
                {
                    "campaign": "cross-engine-archive",
                    "archive_digest": "sha256:" + "a" * 64,
                    "member_count": 2,
                }
            ],
            "policy_inputs_status": "NON_EQUIVALENT_CONTRACT",
            "reviewer_approval_id": "reviewer",
            "reasons": ["fixture"],
        }
        self.assertEqual(historical.validate_parity_assessment(document)["status"], "PASS")
        document["reviewer_approval_id"] = None
        with self.assertRaises(BenchError) as raised:
            historical.validate_parity_assessment(document)
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


class IndependentParityTests(unittest.TestCase):
    """RF09-03 / HPF: parity needs recomputation and an external approval record."""

    def _assessment(self, root: Path, **overrides):
        row = support.parity_row()
        arguments = {
            "study_id": "cross-engine-keyword-real-v1",
            "archive_root": root,
            "cross_engine_expected": support.approved_archive(root)[1],
            "reviewer_approval_id": "caller-label",
            "mapping_status": "NON_EQUIVALENT_CONTRACT",
            "rows": [row],
            "legacy_manifest": support.legacy_manifest(),
        }
        arguments.update(overrides)
        return historical.assess_required_historical_parity(**arguments)

    def test_hpf_01_caller_pass_row_and_label_never_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _expected = support.approved_archive(Path(temporary) / "archive")
            assessment = self._assessment(root)
        self.assertNotEqual(assessment["status"], "PASS")
        with self.assertRaises(BenchError):
            historical.require_parity_pass(assessment)

    def test_hpf_02_authentic_archive_without_approved_mapping_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _expected = support.approved_archive(Path(temporary) / "archive")
            assessment = self._assessment(root, rows=[])
        self.assertIn(
            assessment["status"], ("BLOCKED", "EVIDENCE_UNAVAILABLE")
        )

    def test_hpf_13_verified_parity_requires_an_approval_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(BenchError):
                historical.open_verified_historical_parity(
                    study_id="cross-engine-keyword-real-v1",
                    archive_root=root,
                    mapping_path=root / "mapping.json",
                    independently_approved_mapping_digest="sha256:" + "a" * 64,
                    approval_source_root=root / "absent-approvals",
                    approval_source_identity="review-1",
                )

    def test_hpf_15_fixture_parity_is_not_production(self) -> None:
        fixture = support.fixture_historical_parity("cross-engine-keyword-real-v1")
        self.assertIs(fixture.fixture_only, True)
        with self.assertRaises(BenchError):
            historical.require_verified_historical_parity(
                fixture, study_id="cross-engine-keyword-real-v1"
            )


class CompleteCoverageParityTests(unittest.TestCase):
    """RF09-10 / HPC: the historical matrix must be complete and re-derived."""

    def test_hpc_02_approved_single_row_mapping_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row = support.parity_row()
            with self.assertRaises(BenchError):
                support.historical_parity_sandbox(root)
            assessment = historical.assess_required_historical_parity(
                study_id="cross-engine-keyword-real-v1",
                archive_root=root / "history" / "archive",
                cross_engine_expected=support.approved_archive(root / "history" / "archive")[1],
                reviewer_approval_id="reviewer",
                mapping_status="NON_EQUIVALENT_CONTRACT",
                rows=[row],
                legacy_manifest=support.legacy_manifest(),
            )
        self.assertNotEqual(assessment["status"], "PASS")

    def test_hpc_10_process_cold_regime_is_accepted_by_the_locator_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder = support.full_historical_parity_sandbox(root)
            parity = builder.open()
        self.assertIn("process_cold", support.REGIMES)
        self.assertIsNotNone(parity)

    def test_hpc_11_zero_hit_absent_rows_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder = support.full_historical_parity_sandbox(root)
            parity = builder.open()
        self.assertEqual(
            builder.zero_hit_rows(),
            len(support.ENGINES)
            * len(support.TRIALS)
            * len(support.N_VALUES)
            * len(support.TOP_K)
            * len(support.REGIMES),
        )
        self.assertIsNotNone(parity)


class IncompleteMatrixTests(unittest.TestCase):
    """Deliberately incomplete or malformed mappings must never PASS."""

    def _open(self, root: Path, **kwargs):
        builder = support.full_historical_parity_sandbox(root, **kwargs)
        return builder.open()

    def test_hpc_03_one_missing_row_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(BenchError) as raised:
                self._open(
                    Path(temporary),
                    row_filter=lambda row: row["row_id"]
                    != "quervant-t1-n10000-absent-k10-wm-med",
                )
        self.assertEqual(raised.exception.code, "BM_IDENTITY_INVALID")

    def test_hpc_04_duplicate_coordinate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(BenchError):
                self._open(Path(temporary), duplicate_row=True)

    def test_hpc_07_reversed_row_order_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(BenchError):
                self._open(Path(temporary), reverse_rows=True)

    def test_hpc_08_warm_only_subset_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(BenchError):
                self._open(
                    Path(temporary),
                    row_filter=lambda row: row["locator"]["regime"] == "warm",
                )

    def test_hpc_12_zero_duration_is_rejected(self) -> None:
        from quervant_bench.official import historical

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder = support.full_historical_parity_sandbox(root)
            mapping = support.read_json(builder.mapping_path)
            target = next(
                row for row in mapping["rows"] if row["metric"] == "lane-median-ns"
            )
            target["expected"] = 0
            self._reapprove(builder, mapping)
            with self.assertRaises(BenchError):
                builder.open()

    def test_hpc_13_boolean_count_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder = support.full_historical_parity_sandbox(root)
            mapping = support.read_json(builder.mapping_path)
            target = next(row for row in mapping["rows"] if row["metric"] == "total-hits")
            target["expected"] = True
            self._reapprove(builder, mapping)
            with self.assertRaises(BenchError):
                builder.open()

    def test_hpc_15_semantic_forgery_with_rehashed_mapping_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder = support.full_historical_parity_sandbox(root)
            mapping = support.read_json(builder.mapping_path)
            target = next(
                row for row in mapping["rows"] if row["metric"] == "lane-median-ns"
            )
            target["expected"] = target["expected"] + 1
            self._reapprove(builder, mapping)
            with self.assertRaises(BenchError) as raised:
                builder.open()
        self.assertEqual(raised.exception.code, "BM_IDENTITY_INVALID")

    def test_hpc_19_changed_archive_after_review_is_rejected(self) -> None:
        from quervant_bench.official import historical

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder = support.full_historical_parity_sandbox(root)
            parity = builder.open()
            path = builder.archive / "trials" / "trial-1" / "quervant.json"
            document = support.read_json(path)
            document["lanes"][0]["samples_ns"][0] += 1
            support.write_json(path, document)
            with self.assertRaises(BenchError):
                historical.require_verified_historical_parity(
                    parity, study_id="cross-engine-keyword-real-v1"
                )

    def test_hpc_21_retained_key_full_matrix_is_unavailable(self) -> None:
        from quervant_bench.official import historical

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(BenchError) as raised:
                historical.open_verified_historical_parity(
                    study_id="retained-key-topk-real-v1",
                    archive_root=Path(temporary),
                    mapping_path=Path(temporary) / "mapping.json",
                    independently_approved_mapping_digest="sha256:" + "a" * 64,
                    approval_source_root=Path(temporary) / "approvals",
                    approval_source_identity="review",
                )
        self.assertEqual(raised.exception.code, "BM_EVIDENCE_UNAVAILABLE")

    @staticmethod
    def _reapprove(builder, mapping) -> None:
        import hashlib

        from quervant_bench.official import historical as official_historical

        digest = support.write_json(builder.mapping_path, mapping)
        approval = {
            "kind": official_historical.PARITY_APPROVAL_KIND,
            "schema_version": 1,
            "study_id": "cross-engine-keyword-real-v1",
            "approved_mapping_digest": digest,
            "independent_review_id": "test-only-parity-review",
            "approved_at_utc": "2026-01-01T00:00:00Z",
        }
        support.write_json(
            builder.approval_root
            / f"{builder.approval_identity}{official_historical.PARITY_APPROVAL_SUFFIX}",
            approval,
        )
        object.__setattr__(builder, "mapping_digest", digest)
        del hashlib
