"""O09-SCOPE isolation across synthetic, official and historical domains."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.codec import content_digest
from quervant_bench.config.contracts import validate_receipt
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCOPE_MISMATCH,
    BenchError,
)
from quervant_bench.official import contracts, publication, receipts
from quervant_bench.qualification import contracts as synthetic_contracts
from quervant_bench.tests import official_support as support


class CrossScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.result, cls.fixture, cls.admitted, cls.analysis, cls.policy = (
            support.published_cross_engine(cls.root)
        )
        cls.bundle = publication.load_official_bundle(
            output_base=cls.root / "output",
            study_id=cls.result.study_id,
            run_id=cls.result.run_id,
            anchors=cls.result.anchors,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_o09_scope_06_synthetic_validators_reject_official_documents(self) -> None:
        accepted_codes = {BM_SCHEMA_INVALID, BM_SCOPE_MISMATCH}
        for validator, name in (
            (synthetic_contracts.validate_admission_index, "admission-index.json"),
            (synthetic_contracts.validate_manifest, "manifest.json"),
            (synthetic_contracts.validate_acceptance_summary, "acceptance-summary.json"),
            (synthetic_contracts.validate_verification_assessment, "verification-assessment.json"),
        ):
            with self.assertRaises(BenchError) as raised:
                validator(self.bundle.documents[name])
            self.assertIn(raised.exception.code, accepted_codes, name)

    def test_o09_scope_06b_synthetic_profile_rejects_official_scope(self) -> None:
        profile = {
            "kind": synthetic_contracts.PROFILE_KIND,
            "schema_version": 1,
            "profile_id": synthetic_contracts.PROFILE_ID,
            "profile_version": synthetic_contracts.PROFILE_VERSION,
            "evidence_origin": "real",
            "qualification_scope": "official",
            "required_gates": list(synthetic_contracts.GATE_ORDER),
            "required_verifier_checks": list(synthetic_contracts.VERIFIER_CHECK_IDS),
            "framework_qa_roster": list(synthetic_contracts.FRAMEWORK_QA_ROSTER),
            "source_qa_roster": list(synthetic_contracts.SOURCE_QA_ROSTER),
            "max_document_bytes": synthetic_contracts.MAX_DOCUMENT_BYTES,
        }
        with self.assertRaises(BenchError) as raised:
            synthetic_contracts.validate_profile(profile)
        self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)

    def test_o09_scope_07_official_validators_reject_synthetic_documents(self) -> None:
        synthetic_receipt = {
            "kind": "receipt",
            "schema_version": 1,
            "gate": "admission",
            "status": "pass",
            "evidence_origin": "synthetic",
            "qualification_scope": "simulated",
            "subject": dict(self.result.anchors.subject),
            "validator": {
                "validator_id": "synthetic-admission",
                "validator_version": 1,
                "source_digest": "sha256:" + "a" * 64,
            },
            "inputs": [],
            "dependencies": [],
            "outputs": [],
        }
        synthetic_receipt["receipt_id"] = content_digest(synthetic_receipt)
        with self.assertRaises(BenchError) as raised:
            publication.validate_official_member("admission.json", synthetic_receipt)
        self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)

        synthetic_index = {
            "kind": synthetic_contracts.ADMISSION_INDEX_KIND,
            "schema_version": 1,
            "evidence_origin": "synthetic",
            "qualification_scope": "simulated",
        }
        with self.assertRaises(BenchError):
            contracts.validate_official_evidence_index(synthetic_index)

    def test_o09_scope_08_historical_documents_are_not_official(self) -> None:
        from quervant_bench.official import historical

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
        with self.assertRaises(BenchError) as raised:
            contracts.require_official_scope(assessment)
        self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)

    def test_o09_scope_09_official_receipts_cannot_be_relabelled_synthetic(self) -> None:
        document = dict(self.bundle.documents["analysis.json"])
        document["qualification_scope"] = "simulated"
        with self.assertRaises(BenchError):
            contracts.validate_official_analysis(document)
        document["evidence_origin"] = "synthetic"
        with self.assertRaises(BenchError) as raised:
            contracts.require_official_scope(document)
        self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)

    def test_o09_scope_10_manifest_kind_must_be_official(self) -> None:
        manifest = dict(self.bundle.documents["manifest.json"])
        manifest["kind"] = synthetic_contracts.MANIFEST_KIND
        with self.assertRaises(BenchError) as raised:
            contracts.validate_official_manifest(manifest)
        self.assertEqual(raised.exception.code, "BM_SCHEMA_INVALID")

    def test_o09_scope_11_receipt_v1_shape_is_unchanged(self) -> None:
        receipt = validate_receipt(self.bundle.documents["admission.json"])
        self.assertEqual(
            set(receipt.subject.__dataclass_fields__),
            {"experiment_id", "run_id", "protocol_digest", "workload_digest"},
        )
        self.assertEqual(receipts.receipt_digest(self.bundle.documents["admission.json"]), receipt.receipt_id)

    def test_o09_scope_12_official_member_validation_covers_every_durable_name(self) -> None:
        for name in contracts.MEMBER_NAMES:
            publication.validate_official_member(name, self.bundle.documents[name])
        with self.assertRaises(BenchError):
            publication.validate_official_member("extra.json", {"kind": "x"})

    def test_o09_scope_13_real_historical_receipt_is_rejected_by_official_verifier(self) -> None:
        document = dict(self.bundle.documents["admission.json"])
        document["qualification_scope"] = "historical_replay"
        document["receipt_id"] = content_digest(
            {key: value for key, value in document.items() if key != "receipt_id"}
        )
        with self.assertRaises(BenchError) as raised:
            receipts.verify_official_receipt(
                document,
                gate="admission",
                subject=self.result.anchors.subject,
                source_set_digest=self.result.anchors.source_set_digest,
                inputs={entry["name"]: entry["digest"] for entry in document["inputs"]},
                outputs={entry["name"]: entry["digest"] for entry in document["outputs"]},
            )
        self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)


class ReportTests(unittest.TestCase):
    def test_o09_doc_01_closeout_requires_every_predicate(self) -> None:
        from quervant_bench.official import report

        status, missing = report.closeout_status(report.CloseoutInputs())
        self.assertEqual(status, report.CLOSEOUT_BLOCKED)
        self.assertEqual(len(missing), 12)

    def test_o09_doc_02_complete_inputs_are_ready(self) -> None:
        from quervant_bench.official import report

        inputs = report.CloseoutInputs(
            l1_pass=True,
            l2_pass=True,
            g0_approved_both=True,
            host_readiness_and_controls_pass=True,
            retained_key_full_series_pass=True,
            cross_engine_full_series_pass=True,
            real_gates_pass=True,
            historical_parity_pass=True,
            attestation_reopen_pass=True,
            final_ci_success=True,
            independent_review_accepted=True,
            no_unresolved_findings=True,
        )
        status, missing = report.closeout_status(inputs)
        self.assertEqual(status, report.CLOSEOUT_READY)
        self.assertEqual(missing, ())

    def test_o09_doc_03_missing_parity_blocks_closeout(self) -> None:
        from quervant_bench.official import report

        inputs = report.CloseoutInputs(
            l1_pass=True,
            l2_pass=True,
            g0_approved_both=True,
            host_readiness_and_controls_pass=True,
            retained_key_full_series_pass=True,
            cross_engine_full_series_pass=True,
            real_gates_pass=True,
            historical_parity_pass=False,
            attestation_reopen_pass=True,
            final_ci_success=True,
            independent_review_accepted=True,
            no_unresolved_findings=True,
        )
        status, missing = report.closeout_status(inputs)
        self.assertEqual(status, report.CLOSEOUT_BLOCKED)
        self.assertIn("historical_parity_pass", missing)

    def test_o09_doc_04_report_is_sanitized_and_closed(self) -> None:
        from quervant_bench.official import report

        document = report.build_report(
            branch="dev/bm09-real-qualification",
            planning_main_sha="a" * 40,
            actual_main_base_sha="a" * 40,
            implementation_sha="b" * 40,
            gates=[
                {"gate_id": "implementation", "status": "PASS", "evidence_digest": None},
                {"gate_id": "real-acquisition", "status": "BLOCKED", "evidence_digest": None},
            ],
            real_series=[],
            historical_parity_status="BLOCKED",
            closeout_ready=False,
        )
        self.assertEqual(
            document["disposition"], report.DISPOSITION_IMPLEMENTATION_ONLY
        )
        text = str(document)
        self.assertNotIn("/home/", text)
        self.assertNotIn("/mnt/", text)

    def test_o09_doc_05_unknown_disposition_and_gate_status_are_rejected(self) -> None:
        from quervant_bench.official import report

        document = report.build_report(
            branch="dev/bm09-real-qualification",
            planning_main_sha="a" * 40,
            actual_main_base_sha="a" * 40,
            implementation_sha="b" * 40,
            gates=[{"gate_id": "implementation", "status": "PASS", "evidence_digest": None}],
            real_series=[],
            historical_parity_status="BLOCKED",
            closeout_ready=False,
        )
        for mutation in (
            {"disposition": "DONE"},
            {"gates": [{"gate_id": "implementation", "status": "DONE", "evidence_digest": None}]},
        ):
            candidate = dict(document, **mutation)
            with self.assertRaises(BenchError):
                report.validate_report(candidate)

    def test_o09_doc_06_report_digest_is_stable(self) -> None:
        from quervant_bench.official import report

        document = report.build_report(
            branch="dev/bm09-real-qualification",
            planning_main_sha="a" * 40,
            actual_main_base_sha="a" * 40,
            implementation_sha="b" * 40,
            gates=[],
            real_series=[],
            historical_parity_status="BLOCKED",
            closeout_ready=False,
        )
        self.assertEqual(report.report_digest(document), report.report_digest(document))
        self.assertTrue(report.report_digest(document).startswith("sha256:"))


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
