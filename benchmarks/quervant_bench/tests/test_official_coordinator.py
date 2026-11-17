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
        cls.admitted, cls.authorization = support.admit_production_shaped_cross_engine(
            cls.fixture, sandbox=cls.root / "sandbox"
        )
        cls.parity = support.full_historical_parity_sandbox(cls.root / "history-full").open()
        cls.observed = support.authorization_observations(cls.fixture.freeze)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _qualify(self, *, publish: bool = False, **overrides):
        arguments = {
            "authorization": self.authorization,
            "template": self.fixture.template,
            "admitted": self.admitted,
            "framework_qa": self.fixture.framework_qa,
            "source_qa": self.fixture.source_qa,
            "historical_parity": self.parity,
            "output_base": self.root / f"out-{len(list(self.root.glob('out-*')))}",
            "qa_evidence_root": self.fixture.qa_evidence_root,
            "source_root": support.REPO_ROOT,
            "publish": publish,
            "observed": self.observed,
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
        template = dict(self.fixture.template, study_id=self.fixture.template["study_id"])
        template["limitations"] = sorted(set(template["limitations"] + ["tampered-design"]))
        with self.assertRaises(BenchError) as raised:
            self._qualify(template=template)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_e2e_04_study_mismatch_is_rejected(self) -> None:
        with self.assertRaises(BenchError):
            coordinator.qualify_official_study(
                authorization=support.fixture_authorization("retained-key-topk-real-v1"),
                template=self.fixture.template,
                admitted=self.admitted,
                framework_qa=self.fixture.framework_qa,
                source_qa=self.fixture.source_qa,
                historical_parity=self.parity,
                output_base=self.root / "study-mismatch",
                qa_evidence_root=self.fixture.qa_evidence_root,
                source_root=support.REPO_ROOT,
            )

    def test_o09_qa_01_qa_evidence_from_another_source_set_blocks_gate_d(self) -> None:
        evidence = dict(self.fixture.framework_qa)
        evidence["source_set_digest"] = "sha256:" + "8" * 64
        with self.assertRaises(BenchError) as raised:
            self._qualify(framework_qa=evidence)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_qa_02_qa_scope_is_enforced(self) -> None:
        evidence = dict(self.fixture.source_qa)
        evidence["evidence_origin"] = "synthetic"
        evidence["qualification_scope"] = "simulated"
        with self.assertRaises(BenchError):
            self._qualify(source_qa=evidence)

    def test_o09_qa_03_wrong_qa_gate_is_rejected(self) -> None:
        evidence = dict(self.fixture.source_qa)
        with self.assertRaises(BenchError):
            self._qualify(framework_qa=evidence)

    def test_o09_qa_04_mandatory_skip_is_rejected(self) -> None:
        evidence = copy.deepcopy(dict(self.fixture.framework_qa))
        evidence["checks"][0]["mandatory_skipped"] = 1
        with self.assertRaises(BenchError):
            self._qualify(framework_qa=evidence)

    def test_o09_qa_05_not_executed_check_is_rejected(self) -> None:
        evidence = copy.deepcopy(dict(self.fixture.framework_qa))
        evidence["checks"][0]["executed"] = False
        with self.assertRaises(BenchError):
            self._qualify(framework_qa=evidence)

    def test_o09_his_10_blocked_parity_blocks_gate_d(self) -> None:
        # A caller-constructed assessment document is never parity evidence.
        caller_rows = support.cross_engine_parity(self.root)
        with self.assertRaises(BenchError) as raised:
            self._qualify(historical_parity=caller_rows)
        self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")

    def test_o09_his_10b_parity_without_reviewer_is_blocked(self) -> None:
        root, expected = support.approved_archive(self.root / "fixture" / "archive")
        assessment = historical.assess_required_historical_parity(
            study_id="cross-engine-keyword-real-v1",
            archive_root=root,
            cross_engine_expected=expected,
            reviewer_approval_id=None,
            mapping_status="NON_EQUIVALENT_CONTRACT",
            rows=[support.parity_row()],
            legacy_manifest=support.legacy_manifest(),
        )
        self.assertNotEqual(assessment["status"], "PASS")
        self.assertIn("independent-reviewer-approval-missing", assessment["reasons"])
        with self.assertRaises(BenchError):
            historical.require_parity_pass(assessment)

    def test_o09_his_11_parity_for_another_study_is_rejected(self) -> None:
        parity = support.fixture_historical_parity("retained-key-topk-real-v1")
        with self.assertRaises(BenchError):
            self._qualify(historical_parity=parity)

    def test_o09_e2e_05_retained_key_underivable_policy_blocks_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = support.make_retained_key_fixture(root / "fixture")
            admitted = support.admit_fixture_retained_key(fixture)
            with self.assertRaises(BenchError) as raised:
                coordinator.qualify_fixture_graph_in_memory(
                    authorization=support.fixture_authorization(
                        "retained-key-topk-real-v1", freeze=fixture.freeze
                    ),
                    template=fixture.template,
                    admitted=admitted,
                    framework_qa=fixture.framework_qa,
                    source_qa=fixture.source_qa,
                    historical_parity=support.fixture_historical_parity(
                        "retained-key-topk-real-v1"
                    ),
                )
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def test_o09_e2e_06_reuse_returns_the_verified_bundle(self) -> None:
        result = self._qualify(publish=True)
        bundle = coordinator.reuse_or_conflict(
            output_base=result.output_directory.parent.parent,
            study_id=result.study_id,
            run_id=result.run_id,
            anchors=result.anchors,
            authorization=support.reopen_authorization(self.root / "sandbox"),
            observed=self.observed,
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
                authorization=self.authorization,
                observed=self.observed,
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


class VerifiedAuthorizationBoundaryTests(unittest.TestCase):
    """RF09-01 / G0F: production qualification requires a verified capability."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.fixture = support.make_cross_engine_fixture(cls.root / "fixture")
        cls.admitted = support._admit_fixture_cross_engine_with_verifier(
            raw_root=cls.fixture.raw_root,
            authorization=support.fixture_authorization(
                "cross-engine-keyword-real-v1", freeze=cls.fixture.freeze
            ),
            template=cls.fixture.template,
            corpus_dir=cls.fixture.corpus_root,
            control_document=cls.fixture.control,
            original_verifier=support.StubVerifier(),
        )
        cls.parity = support.fixture_historical_parity("cross-engine-keyword-real-v1")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _qa(self, gate: str) -> dict:
        return (
            dict(self.fixture.framework_qa)
            if gate == "framework-qa"
            else dict(self.fixture.source_qa)
        )

    def test_g0f_01_bare_freeze_is_rejected_by_the_coordinator(self) -> None:
        with self.assertRaises((TypeError, BenchError)):
            coordinator.qualify_official_study(
                freeze=self.fixture.freeze,
                template=self.fixture.template,
                admitted=self.admitted,
                framework_qa=self._qa("framework-qa"),
                source_qa=self._qa("source-qa"),
                historical_parity=self.parity,
                output_base=self.root / "g0f01",
                publish=False,
            )

    def test_g0f_07_fixture_graph_is_never_officially_qualified(self) -> None:
        result = coordinator.qualify_fixture_graph_in_memory(
            authorization=support.fixture_authorization(
                "cross-engine-keyword-real-v1", freeze=self.fixture.freeze
            ),
            template=self.fixture.template,
            admitted=self.admitted,
            framework_qa=self._qa("framework-qa"),
            source_qa=self._qa("source-qa"),
            historical_parity=self.parity,
        )
        self.assertEqual(result.disposition, "TEST_ONLY_GRAPH_VERIFIED")
        self.assertFalse((self.root / "g0f07").exists())

    def test_qaf_02_framework_qa_digest_must_match_the_g0_pin(self) -> None:
        evidence = self._qa("framework-qa")
        evidence["checks"][0]["evidence_digest"] = "sha256:" + "5" * 64
        with self.assertRaises(BenchError):
            coordinator.qualify_fixture_graph_in_memory(
                authorization=support.fixture_authorization(
                "cross-engine-keyword-real-v1", freeze=self.fixture.freeze
            ),
                template=self.fixture.template,
                admitted=self.admitted,
                framework_qa=evidence,
                source_qa=self._qa("source-qa"),
                historical_parity=self.parity,
            )

    def test_qaf_03_source_qa_digest_must_match_the_g0_pin(self) -> None:
        evidence = self._qa("source-qa")
        evidence["checks"][0]["evidence_digest"] = "sha256:" + "6" * 64
        with self.assertRaises(BenchError):
            coordinator.qualify_fixture_graph_in_memory(
                authorization=support.fixture_authorization(
                "cross-engine-keyword-real-v1", freeze=self.fixture.freeze
            ),
                template=self.fixture.template,
                admitted=self.admitted,
                framework_qa=self._qa("framework-qa"),
                source_qa=evidence,
                historical_parity=self.parity,
            )

    def test_hpf_12_fixture_parity_never_opens_production_gate_d(self) -> None:
        production = support.fixture_historical_parity(
            "cross-engine-keyword-real-v1", fixture_only=False
        )
        with self.assertRaises(BenchError):
            coordinator.qualify_official_study(
                authorization=support.fixture_authorization(
                "cross-engine-keyword-real-v1", freeze=self.fixture.freeze
            ),
                template=self.fixture.template,
                admitted=self.admitted,
                framework_qa=self._qa("framework-qa"),
                source_qa=self._qa("source-qa"),
                historical_parity=production,
                output_base=self.root / "hpf12",
                qa_evidence_root=self.fixture.qa_evidence_root,
                source_root=support.REPO_ROOT,
                publish=False,
            )


class PackagingMetadataTests(unittest.TestCase):
    """RF09-07 / PKG: generated editable-install metadata is not part of the PR."""

    def test_pkg_01_no_egg_info_files_are_tracked(self) -> None:
        import subprocess

        completed = subprocess.run(
            ["git", "-C", str(support.REPO_ROOT), "ls-files", "benchmarks/quervant_bench.egg-info/*"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.stdout.strip(), "")

    def test_pkg_02_generated_metadata_is_ignored(self) -> None:
        text = (support.REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("**/*.egg-info/", text)

    def test_pkg_03_no_stray_packaging_artifacts_are_tracked(self) -> None:
        import subprocess

        completed = subprocess.run(
            ["git", "-C", str(support.REPO_ROOT), "ls-files", "*.egg-info/*", "*/build/lib/*"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.stdout.strip(), "")
