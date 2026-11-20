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




    def test_f4_co_01_capability_control_mutation_blocks_coordinator(self) -> None:
        import copy

        from quervant_bench.official import admission as official_admission

        record = self.admitted.record
        saved_control = copy.deepcopy(record.control)
        control_path = self.fixture.raw_root / "control" / "control.json"
        saved_bytes = control_path.read_bytes()
        saved_inventory = official_admission.admitted_inventory_digest(record)
        output = self.root / "co01-output"
        try:
            record.control["block_count"] = 11
            self.assertEqual(control_path.read_bytes(), saved_bytes)
            with self.assertRaises(BenchError) as raised:
                self._qualify(publish=False, output_base=output)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertEqual(raised.exception.field_path, "control")
            self.assertFalse(output.exists())
            self.assertEqual(control_path.read_bytes(), saved_bytes)
            self.assertEqual(
                official_admission.admitted_inventory_digest(record), saved_inventory
            )
        finally:
            record.control.clear()
            record.control.update(saved_control)


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


class CurrentBaselineCoordinatorTests(unittest.TestCase):
    """Gate wiring with a narrowly substituted disclosure boundary, no live authority."""

    @classmethod
    def setUpClass(cls) -> None:
        from dataclasses import replace
        from types import SimpleNamespace
        from quervant_bench.config.codec import content_digest
        from quervant_bench.official import analysis, protocols, verification

        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        original = support.make_cross_engine_fixture(cls.root / "fixture")
        template = support.read_json(protocols.template_path(original.freeze.study_id, support.REPO_ROOT, version=2))
        cls.freeze = replace(
            original.freeze, design_digest=content_digest(template), profile_version=2,
            acceptance_profile="current-baseline-v2", baseline_id="44444444-4444-4444-8444-444444444444",
            preservation_root_identity=str(cls.root / "benchmark-results/baselines/44444444-4444-4444-8444-444444444444"),
            runtime_freeze_digest=None, approved_output_root_identity=str(cls.root / "output"),
            policy_digest=analysis.policy_profile_digest(template["study_id"], template["policy"]["policy_chain"]),
        )
        cls.fixture = replace(original, template=template, freeze=cls.freeze)
        cls.record = support.admit_fixture_cross_engine(cls.fixture)
        cls.authorization = support.fixture_authorization(freeze=cls.freeze)
        derived, policy = analysis.analyze_official_study(admitted=cls.record, template=template)
        assessment = verification.verify_official_study(
            admitted=cls.record, template=template, authorization=cls.authorization,
            analysis=derived, policy=policy,
        )
        cls.context = SimpleNamespace(
            acceptance_profile="current-baseline-v2", baseline_id=cls.freeze.baseline_id,
            study_id=cls.freeze.study_id, run_id=cls.freeze.run_id, source_commit=cls.freeze.source_commit,
            current_raw_digest=cls.record.raw_series_root_digest, authorization_digest=cls.freeze.authorization_digest,
            admission_index_digest=content_digest(cls.record.admission_index), analysis_digest=content_digest(derived),
            policy_digest=content_digest(policy), verification_digest=content_digest(assessment),
            history_inventory_digest=support.DIGEST_A, history_report_digest=support.DIGEST_B,
            relative_effects_digest=support.DIGEST_C,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _derive(self, context):
        from unittest.mock import patch

        with patch("quervant_bench.official.history.reverify_baseline_disclosures", return_value=context) as refresh:
            with patch.object(coordinator.official_historical, "require_verified_historical_parity", side_effect=AssertionError("v1 parity was reached")):
                result = coordinator._derive_bundle(
                    freeze=self.freeze, template=self.fixture.template, admitted=self.record,
                    framework_qa=self.fixture.framework_qa, source_qa=self.fixture.source_qa,
                    historical_parity=None, source_root=None, fixture_only=True,
                    authorization=self.authorization, baseline_context=context,
                )
        refresh.assert_called_once_with(context)
        return result

    def test_cb_v12_gate_d_uses_disclosures_and_exact_versioned_graph(self) -> None:
        from quervant_bench.official import publication

        derived = self._derive(self.context)
        acceptance = derived.documents["acceptance-summary.json"]
        self.assertEqual(acceptance["schema_version"], 2)
        self.assertEqual(acceptance["decision_scope"], "real-current-baseline-v2")
        self.assertNotIn("historical_parity_status", acceptance)
        self.assertEqual(acceptance["history_report_digest"], self.context.history_report_digest)
        self.assertEqual(acceptance["baseline_verification_status"], "VERIFIED_CURRENT_BASELINE")
        self.assertEqual(acceptance["policy_verification_status"], "PASS")
        self.assertIs(type(derived.anchors), publication.OfficialBaselineAnchors)
        names = {item["name"] for item in derived.documents["acceptance.json"]["inputs"]}
        self.assertEqual(names, {"admission-index", "analysis", "authorization", "control-assessment", "framework-qa-evidence", "history-report", "policy", "relative-effects", "source-qa-evidence", "source-set", "verification-assessment"})
        for gate, name in publication.GATE_RECEIPT_NAMES.items():
            receipt = derived.documents[name]
            self.assertEqual(receipt["schema_version"], 1, gate)
            self.assertEqual(receipt["validator"]["validator_version"], 2, gate)
        self.assertEqual(len(derived.documents), 14)
        self.assertEqual(len(derived.manifest["members"]), 14)

    def test_cb_v12_disclosure_must_match_coordinator_owned_results(self) -> None:
        from types import SimpleNamespace

        for field in ("current_raw_digest", "admission_index_digest", "analysis_digest", "policy_digest", "verification_digest", "source_commit", "run_id", "baseline_id"):
            with self.subTest(field=field):
                altered = dict(vars(self.context))
                altered[field] = "different"
                with self.assertRaises(BenchError) as raised:
                    self._derive(SimpleNamespace(**altered))
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                self.assertEqual(raised.exception.field_path, field)

    def test_cb_v09_old_blocked_assessment_is_never_promoted(self) -> None:
        from unittest.mock import patch

        with patch.object(coordinator, "verify_official_study", return_value={"schema_version": 1, "status": "BLOCKED"}):
            with self.assertRaises(BenchError) as raised:
                self._derive(self.context)
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
        self.assertEqual(raised.exception.field_path, "verification_status")

    def test_cb_p07_pure_bundle_checker_never_requires_live_capability(self) -> None:
        from unittest.mock import patch
        from quervant_bench.official import publication

        derived = self._derive(self.context)
        members = [(name, derived.documents[name]) for name in contracts.MEMBER_NAMES[:14]]
        with patch("quervant_bench.official.history.reverify_baseline_disclosures", side_effect=AssertionError("live disclosure path")):
            with patch.object(publication, "require_verified_official_authorization", side_effect=AssertionError("live G0 path")):
                payloads = publication._validate_bundle_semantics(
                    study_id=self.freeze.study_id, run_id=self.freeze.run_id,
                    members=members, manifest=derived.manifest, anchors=derived.anchors, profile_version=2,
                )
        self.assertEqual(len(payloads), 14)
        with self.assertRaises(BenchError):
            publication._validate_bundle_semantics(
                study_id=self.freeze.study_id, run_id=self.freeze.run_id,
                members=members, manifest=derived.manifest, anchors=derived.anchors,
            )

    def test_cb_v12_reuse_rejects_missing_context_before_destination_probe(self) -> None:
        from unittest.mock import patch
        from quervant_bench.config.errors import BM_UNSAFE_INPUT
        from quervant_bench.official import publication

        derived = self._derive(self.context)
        with patch.object(coordinator, "require_verified_official_authorization", return_value=self.freeze):
            with patch.object(publication, "official_destination_state", side_effect=AssertionError("destination reached")):
                with self.assertRaises(BenchError) as raised:
                    coordinator.reuse_or_conflict(
                        output_base=self.root / "output", study_id=self.freeze.study_id, run_id=self.freeze.run_id,
                        anchors=derived.anchors, authorization=object(), baseline_context=None,
                    )
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
        self.assertEqual(raised.exception.field_path, "baseline_context")
        self.assertFalse((self.root / "output").exists())

    def test_cb_v15_lifecycle_wrapper_uses_the_selected_profile(self) -> None:
        from quervant_bench.config.errors import BM_ACQUISITION_PROHIBITED, BM_SCHEMA_INVALID

        states = ("IMPLEMENTING", "SOURCE_FROZEN", "AUTHORIZATION_PENDING", "AUTHORIZED",
                  "CONTROL_RUNNING", "CONTROL_ACCEPTED", "TREATMENT_RUNNING", "REAL_EVIDENCE_SEALED",
                  "REAL_ACCEPTED", "REAL_ATTESTED", "BASELINE_PRESERVED", "BASELINE_REPLAY_VERIFIED", "CLOSEOUT_READY")
        for before, after in zip(states, states[1:]):
            with self.subTest(before=before, after=after):
                self.assertEqual(coordinator.require_gate_order(before, after, profile_version=2), after)
        self.assertEqual(coordinator.require_gate_order("REAL_ATTESTED", "HISTORICAL_PARITY_PENDING"),
                         "HISTORICAL_PARITY_PENDING")
        for before, after, code in (
            ("REAL_ATTESTED", "HISTORICAL_PARITY_PENDING", BM_IDENTITY_INVALID),
            ("REAL_ATTESTED", "CLOSEOUT_READY", BM_ACQUISITION_PROHIBITED),
            ("BASELINE_REPLAY_VERIFIED", "BASELINE_PRESERVED", BM_ACQUISITION_PROHIBITED),
        ):
            with self.subTest(before=before, after=after):
                with self.assertRaises(BenchError) as raised:
                    coordinator.require_gate_order(before, after, profile_version=2)
                self.assertEqual((raised.exception.code, raised.exception.field_path), (code, "state"))
        for value in (True, 2.0, 0, 3):
            with self.subTest(profile=value):
                with self.assertRaises(BenchError) as raised:
                    coordinator.require_gate_order("IMPLEMENTING", "SOURCE_FROZEN", profile_version=value)
                self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_SCHEMA_INVALID, "profile_version"))


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
