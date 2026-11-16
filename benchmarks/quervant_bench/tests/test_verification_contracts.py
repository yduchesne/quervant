"""BM-05 public contract tests (V-IO / assessment shape)."""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path

import quervant_bench.verification as verification
from quervant_bench.analysis.history import (
    LEGACY_VERIFIER_RELATIVE,
    STATUS_UNAVAILABLE,
    inspect_archive,
)
from quervant_bench.verification.contracts import (
    CHECK_IDS,
    EVIDENCE_ORIGIN,
    QUALIFICATION_SCOPE,
    REFERENCE_ID,
    VERIFICATION_STATUS,
    VerificationAssessment,
)

PACKAGE = Path(verification.__file__).resolve().parent


class AssessmentContractTests(unittest.TestCase):
    def test_assessment_has_the_exact_frozen_field_set(self) -> None:
        self.assertEqual(
            [field.name for field in dataclasses.fields(VerificationAssessment)],
            [
                "status",
                "experiment_id",
                "run_id",
                "evidence_origin",
                "qualification_scope",
                "analysis_digest",
                "policy_digest",
                "source_seal_digest",
                "reference_id",
                "check_ids",
            ],
        )
        self.assertTrue(VerificationAssessment.__dataclass_params__.frozen)

    def test_assessment_is_immutable_and_has_no_publication_surface(self) -> None:
        assessment = VerificationAssessment(
            status=VERIFICATION_STATUS,
            experiment_id="synthetic-analysis-smoke",
            run_id="00000000-0000-4000-8000-000000000000",
            evidence_origin=EVIDENCE_ORIGIN,
            qualification_scope=QUALIFICATION_SCOPE,
            analysis_digest="sha256:" + "0" * 64,
            policy_digest="sha256:" + "1" * 64,
            source_seal_digest="sha256:" + "2" * 64,
            reference_id=REFERENCE_ID,
            check_ids=CHECK_IDS,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            assessment.status = "verified-synthetic"  # type: ignore[misc]
        for name in ("write", "publish", "attest", "receipt", "to_receipt"):
            self.assertFalse(hasattr(assessment, name), name)

    def test_check_registry_is_stable_and_ordered(self) -> None:
        self.assertEqual(
            CHECK_IDS,
            (
                "VC-01-SCOPE",
                "VC-02-PROFILE-BINDINGS",
                "VC-03-STRUCTURAL-REPLAY",
                "VC-04-SEALED-INPUT-INVENTORY",
                "VC-05-INDEPENDENT-STATISTICS",
                "VC-06-INDEPENDENT-BOOTSTRAP",
                "VC-07-INDEPENDENT-POLICY",
                "VC-08-OUTPUT-IDENTITY",
                "VC-09-POST-READ-INTEGRITY",
            ),
        )
        self.assertEqual(len(set(CHECK_IDS)), len(CHECK_IDS))

    def test_public_package_exports_only_the_entry_point_and_record(self) -> None:
        self.assertEqual(
            verification.__all__,
            ["VerificationAssessment", "verify_synthetic_run"],
        )

    def test_package_does_not_register_a_cli_verb(self) -> None:
        cli_path = PACKAGE.parent / "cli.py"
        text = cli_path.read_text(encoding="utf-8")
        self.assertNotIn("quervant_bench.verification", text)
        self.assertNotIn("verify_synthetic_run", text)

    def test_v_hist_01_empty_archive_is_reported_unavailable_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = {path.name: path.read_bytes() for path in root.iterdir()}
            status = inspect_archive(root)
            self.assertEqual(status.status, STATUS_UNAVAILABLE)
            self.assertFalse(status.available)
            lines = status.report_lines()
            self.assertIn("STATUS=EVIDENCE_UNAVAILABLE", lines)
            self.assertIn("NUMERIC_PARITY=NOT_EXECUTED", lines)
            self.assertIn("POLICY_VERDICT_PARITY=NOT_EXECUTED", lines)
            self.assertEqual(
                {path.name: path.read_bytes() for path in root.iterdir()}, before
            )

    def test_v_hist_02_checked_in_legacy_oracle_path_exists(self) -> None:
        legacy = Path(__file__).resolve().parents[3] / LEGACY_VERIFIER_RELATIVE
        self.assertTrue(legacy.is_file())
        text = legacy.read_text(encoding="utf-8")
        self.assertIn("Independent verifier", text)
        self.assertIn("no controller import", text)

    def test_package_contains_no_write_or_receipt_helpers(self) -> None:
        import ast

        forbidden_calls = {
            "write_text",
            "write_bytes",
            "mkdir",
            "unlink",
            "rename",
            "replace",
            "rmdir",
        }
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        self.assertNotEqual(node.func.id, "open", path.name)
                    if isinstance(node.func, ast.Attribute):
                        self.assertNotIn(node.func.attr, forbidden_calls, path.name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
