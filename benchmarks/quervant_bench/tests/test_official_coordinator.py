"""O09-E2E lifecycle and gate-wiring behaviour of the official coordinator."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BenchError,
)
from quervant_bench.official import admission, coordinator, contracts, historical
from quervant_bench.tests import official_support as support


class CoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.fixture = support.make_cross_engine_fixture(cls.root / "fixture")
        cls.admitted = admission.admit_cross_engine_real(
            raw_root=cls.fixture.raw_root,
            freeze=cls.fixture.freeze,
            template=cls.fixture.template,
            corpus_dir=cls.fixture.corpus_root,
            control_document=cls.fixture.control,
            original_verifier=support.StubVerifier(),
        )
        cls.parity = support.cross_engine_parity(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _qualify(self, *, publish: bool = False, **overrides):
        arguments = {
            "freeze": self.fixture.freeze,
            "template": self.fixture.template,
            "admitted": self.admitted,
            "framework_qa": support.qa_evidence("framework-qa", self.fixture.freeze),
            "source_qa": support.qa_evidence("source-qa", self.fixture.freeze),
            "historical_parity": self.parity,
            "output_base": self.root / f"out-{len(list(self.root.glob('out-*')))}",
            "publish": publish,
        }
        arguments.update(overrides)
        output = arguments["output_base"]
        if publish and not Path(output).exists():
            Path(output).mkdir(parents=True)
        return coordinator.qualify_official_study(**arguments)

    def test_o09_e2e_01_in_memory_qualification_passes_all_gates(self) -> None:
        result = self._qualify()
        self.assertEqual(result.disposition, "VERIFIED_NOT_PUBLISHED")
        self.assertIsNotNone(result.anchors)

    def test_o09_e2e_02_published_qualification_is_reopened_and_accepted(self) -> None:
        result = self._qualify(publish=True)
        self.assertEqual(result.disposition, "REAL_OFFICIAL_QUALIFIED")
        self.assertEqual(
            sorted(path.name for path in result.output_directory.iterdir()),
            sorted(contracts.MEMBER_NAMES),
        )

    def test_o09_e2e_03_unapproved_design_digest_is_rejected(self) -> None:
        freeze = support.make_freeze(
            study_id="cross-engine-keyword-real-v1",
            corpus_manifest_digest=self.fixture.freeze.corpus_manifest_digest,
            original_verifier_digest=self.fixture.freeze.original_reference_verifier_digest,
            design_digest="sha256:" + "4" * 64,
        )
        with self.assertRaises(BenchError) as raised:
            self._qualify(freeze=freeze)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_e2e_04_study_mismatch_is_rejected(self) -> None:
        freeze = support.make_freeze(study_id="retained-key-topk-real-v1")
        with self.assertRaises(BenchError):
            self._qualify(freeze=freeze)

    def test_o09_qa_01_qa_evidence_from_another_source_set_blocks_gate_d(self) -> None:
        evidence = support.qa_evidence("framework-qa", self.fixture.freeze)
        evidence["source_set_digest"] = "sha256:" + "8" * 64
        with self.assertRaises(BenchError) as raised:
            self._qualify(framework_qa=evidence)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_qa_02_qa_scope_is_enforced(self) -> None:
        evidence = support.qa_evidence("source-qa", self.fixture.freeze)
        evidence["evidence_origin"] = "synthetic"
        evidence["qualification_scope"] = "simulated"
        with self.assertRaises(BenchError):
            self._qualify(source_qa=evidence)

    def test_o09_qa_03_wrong_qa_gate_is_rejected(self) -> None:
        evidence = support.qa_evidence("source-qa", self.fixture.freeze)
        with self.assertRaises(BenchError):
            self._qualify(framework_qa=evidence)

    def test_o09_qa_04_mandatory_skip_is_rejected(self) -> None:
        evidence = support.qa_evidence("framework-qa", self.fixture.freeze)
        evidence["checks"][0]["mandatory_skipped"] = 1
        with self.assertRaises(BenchError):
            self._qualify(framework_qa=evidence)

    def test_o09_qa_05_not_executed_check_is_rejected(self) -> None:
        evidence = support.qa_evidence("framework-qa", self.fixture.freeze)
        evidence["checks"][0]["executed"] = False
        with self.assertRaises(BenchError):
            self._qualify(framework_qa=evidence)

    def test_o09_his_10_blocked_parity_blocks_gate_d(self) -> None:
        parity = copy.deepcopy(self.parity)
        parity["status"] = "BLOCKED"
        with self.assertRaises(BenchError) as raised:
            self._qualify(historical_parity=parity)
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def test_o09_his_10b_parity_without_reviewer_is_blocked(self) -> None:
        assessment = historical.assess_required_historical_parity(
            study_id="cross-engine-keyword-real-v1",
            archive_root=self.root / "fixture" / "archive",
            cross_engine_expected=support.approved_archive(self.root / "fixture" / "archive")[1],
            reviewer_approval_id=None,
            mapping_status="NON_EQUIVALENT_CONTRACT",
            rows=[support.parity_row()],
            legacy_manifest=support.legacy_manifest(),
        )
        self.assertEqual(assessment["status"], "BLOCKED")
        self.assertIn("independent-reviewer-approval-missing", assessment["reasons"])
        with self.assertRaises(BenchError):
            historical.require_parity_pass(assessment)

    def test_o09_his_11_parity_for_another_study_is_rejected(self) -> None:
        parity = copy.deepcopy(self.parity)
        parity["study_id"] = "retained-key-topk-real-v1"
        with self.assertRaises(BenchError):
            self._qualify(historical_parity=parity)

    def test_o09_e2e_05_retained_key_underivable_policy_blocks_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = support.make_retained_key_fixture(root / "fixture")
            admitted = admission.admit_retained_key_real(
                raw_root=fixture.raw_root,
                freeze=fixture.freeze,
                template=fixture.template,
                original_verifier=support.StubVerifier(),
            )
            with self.assertRaises(BenchError) as raised:
                coordinator.qualify_official_study(
                    freeze=fixture.freeze,
                    template=fixture.template,
                    admitted=admitted,
                    framework_qa=support.qa_evidence("framework-qa", fixture.freeze),
                    source_qa=support.qa_evidence("source-qa", fixture.freeze),
                    historical_parity=support.cross_engine_parity(root),
                    output_base=root / "out",
                    publish=False,
                )
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def test_o09_e2e_06_reuse_returns_the_verified_bundle(self) -> None:
        result = self._qualify(publish=True)
        bundle = coordinator.reuse_or_conflict(
            output_base=result.output_directory.parent.parent,
            study_id=result.study_id,
            run_id=result.run_id,
            anchors=result.anchors,
        )
        self.assertEqual(bundle.disposition, "REUSED_VERIFIED")
        self.assertEqual(bundle.manifest_digest, result.manifest_digest)

    def test_o09_e2e_06b_reuse_of_absent_destination_is_unavailable(self) -> None:
        (self.root / "out-absent").mkdir(exist_ok=True)
        with self.assertRaises(BenchError) as raised:
            coordinator.reuse_or_conflict(
                output_base=self.root / "out-absent",
                study_id=self.fixture.freeze.study_id,
                run_id=self.fixture.freeze.run_id,
                anchors=self._qualify().anchors,
            )
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def test_o09_reg_01_gate_order_is_frozen(self) -> None:
        self.assertEqual(
            contracts.OFFICIAL_GATE_ORDER,
            (
                "admission",
                "analysis",
                "verification",
                "framework-qa",
                "source-qa",
                "acceptance",
                "attestation",
            ),
        )
        self.assertEqual(coordinator.require_gate_order("AUTHORIZED", "CONTROL_RUNNING"), "CONTROL_RUNNING")


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
