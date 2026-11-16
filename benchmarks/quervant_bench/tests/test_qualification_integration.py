"""E2E-01…12, POLICY-01…04, REUSE-01…10, SCOPE-01/02, BOUND-01/02.

The vertical slice runs the real production coordinator over a real BM-03 sealed
synthetic run, the real BM-04 derivation, the real BM-05 independent verifier, the
pinned synthetic QA fixtures and the real filesystem publisher. Nothing here is a
real timed benchmark or an official qualification.
"""

from __future__ import annotations

import copy
import dataclasses
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from quervant_bench.analysis.contracts import (
    DECISION_STATUSES,
    validate_analysis_result,
    validate_policy_decision,
)
from quervant_bench.analysis.derive import analyze_synthetic_run
from quervant_bench.analysis.policy import evaluate_policy
from quervant_bench.analysis.policy import (
    read_policy_profile,
    read_resource_observations,
)
from quervant_bench.analysis.profiles import read_analysis_profile
from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_NOT_IMPLEMENTED,
    BM_PUBLICATION_CONFLICT,
    BM_SCHEMA_INVALID,
    BM_SCOPE_MISMATCH,
    BenchError,
)
from quervant_bench.qualification import (
    admission,
    contracts as qualification_contracts,
    coordinator,
    qa,
)
from quervant_bench.qualification.contracts import (
    MEMBER_NAMES,
    validate_acceptance_summary,
    validate_verification_assessment,
)
from quervant_bench.qualification.identity import compute_source_set_digest
from quervant_bench.qualification.receipts import (
    build_stage_receipt,
    validator_identity,
    verify_stage_receipt,
)
from quervant_bench.verification.verify import verify_synthetic_run
from quervant_bench.tests.analysis_support import (
    SealedRun,
    analysis_document,
    default_campaigns,
    experiment_root,
    make_policy_profile,
    make_resources,
)
from quervant_bench.tests.test_qualification_contracts import (
    FIXTURES,
    REPO_ROOT,
    committed_documents,
    load_committed,
    materialize_source_tree,
    profile_digest,
    qualified_once,
    qualification_kwargs,
    read_json,
    sealed_run,
    trust_anchors,
    write_canonical,
)

ZERO = "sha256:" + "0" * 64
PASSING = ("0.800000000000", "0.800000000000", "0.800000000000", "0.800000000000", "analyzed")


def _fresh_qualification(temporary: Path) -> tuple[Any, Path, Any]:
    run = SealedRun()
    base = temporary / "results"
    base.mkdir(parents=True, exist_ok=True)
    arguments = qualification_kwargs(base)
    arguments.update(
        {"bundle": run.bundle, "run_dir": run.run_dir, "scenario_root": run.evidence}
    )
    try:
        result = coordinator.qualify_synthetic_run(**arguments)
    except BaseException:
        run.close()
        raise
    return run, base, result


class EndToEndTests(unittest.TestCase):
    """E2E-01…12 and SCOPE-01/02."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.base, cls.result = qualified_once()
        cls.documents = committed_documents()

    def test_e2e_01_full_synthetic_chain_publishes_the_exact_bundle(self) -> None:
        self.assertEqual(self.result.disposition, "SIMULATED_QUALIFIED")
        directory = self.result.output_directory
        self.assertEqual(
            sorted(entry.name for entry in directory.iterdir()), sorted(MEMBER_NAMES)
        )
        index = self.documents["admission-index.json"]
        self.assertEqual(
            index["counts"],
            {
                "controls_completed": 1,
                "treatments_completed": 2,
                "slots_completed": 24,
                "lane_envelopes": 48,
                "synthetic_samples": 144,
            },
        )
        seal = read_json(sealed_run().run_dir / "seal.json")
        self.assertEqual(
            index["seal_raw_digest"],
            "sha256:" + __import__("hashlib").sha256(
                canonical_document_bytes(seal)
            ).hexdigest(),
        )
        self.assertEqual(
            index["files"],
            [
                {
                    "path": entry["path"],
                    "byte_length": entry["byte_length"],
                    "raw_digest": entry["digest"],
                }
                for entry in seal["files"]
            ],
        )
        assessment = self.documents["verification-assessment.json"]
        self.assertEqual(len(assessment["check_ids"]), 9)
        self.assertEqual(assessment["check_ids"][0], "VC-01-SCOPE")
        self.assertEqual(assessment["check_ids"][-1], "VC-09-POST-READ-INTEGRITY")
        self.assertEqual(
            assessment["analysis_digest"], content_digest(self.documents["analysis.json"])
        )
        self.assertEqual(
            assessment["policy_digest"], content_digest(self.documents["policy.json"])
        )
        self.assertIn(
            self.documents["acceptance-summary.json"]["policy_decision_status"],
            DECISION_STATUSES,
        )
        self.assertEqual(
            self.documents["attestation.json"]["evidence_origin"], "synthetic"
        )
        self.assertEqual(
            self.documents["manifest.json"]["qualification_scope"], "simulated"
        )
        self.assertTrue(
            (directory / "manifest.json").read_bytes().endswith(b"\n")
        )
        self.assertEqual(self.result.manifest_digest, content_digest(self.documents["manifest.json"]))
        self.assertEqual(
            self.result.attestation_receipt_id,
            self.documents["attestation.json"]["receipt_id"],
        )

    def test_e2e_02_identical_reuse_never_recomputes_and_changed_run_rejects(self) -> None:
        before = {name: (self.result.output_directory / name).read_bytes() for name in MEMBER_NAMES}
        with mock.patch.object(
            coordinator, "analyze_synthetic_run", side_effect=AssertionError("BM-04 called")
        ), mock.patch.object(
            coordinator, "verify_synthetic_run", side_effect=AssertionError("BM-05 called")
        ):
            reused = coordinator.qualify_synthetic_run(**qualification_kwargs(self.base))
            loaded = load_committed(self.base)
        self.assertEqual(reused.disposition, "REUSED_VERIFIED")
        self.assertEqual(loaded.disposition, "REUSED_VERIFIED")
        self.assertEqual(reused.manifest_digest, self.result.manifest_digest)
        self.assertEqual(loaded.manifest_digest, self.result.manifest_digest)
        after = {name: (self.result.output_directory / name).read_bytes() for name in MEMBER_NAMES}
        self.assertEqual(before, after)

        with tempfile.TemporaryDirectory() as temporary:
            run, base, result = _fresh_qualification(Path(temporary))
            try:
                self.assertEqual(result.disposition, "SIMULATED_QUALIFIED")
                seal = read_json(run.run_dir / "seal.json")
                victim = run.run_dir / seal["files"][0]["path"]
                victim.write_bytes(victim.read_bytes() + b" ")
                arguments = qualification_kwargs(base)
                arguments.update(
                    {"bundle": run.bundle, "run_dir": run.run_dir, "scenario_root": run.evidence}
                )
                with self.assertRaises(BenchError) as raised:
                    coordinator.load_qualified_synthetic_run(**arguments)
                self.assertIn(
                    raised.exception.code,
                    {BM_IDENTITY_INVALID, BM_EVIDENCE_UNAVAILABLE},
                )
            finally:
                run.close()

    def test_e2e_03_stage_failures_leave_no_partial_publication(self) -> None:
        cases = (
            ("analyze_synthetic_run", BenchError(BM_IDENTITY_INVALID, "injected B failure")),
            ("verify_synthetic_run", BenchError(BM_IDENTITY_INVALID, "injected C failure")),
        )
        for name, error in cases:
            with tempfile.TemporaryDirectory() as temporary:
                run = SealedRun()
                base = Path(temporary) / "results"
                base.mkdir()
                arguments = qualification_kwargs(base)
                arguments.update(
                    {
                        "bundle": run.bundle,
                        "run_dir": run.run_dir,
                        "scenario_root": run.evidence,
                    }
                )
                try:
                    with mock.patch.object(coordinator, name, side_effect=error):
                        with self.assertRaises(BenchError):
                            coordinator.qualify_synthetic_run(**arguments)
                    self.assertFalse((base / run.bundle.experiment.experiment_id / run.run_dir.name).exists())
                finally:
                    run.close()
        # A read-only qualification directory is reported as a conflict, never repaired.
        (self.base / self.result.experiment_id / self.result.run_id / "stale.json").write_text(
            "{}", encoding="utf-8"
        )
        try:
            with self.assertRaises(BenchError) as raised:
                coordinator.qualify_synthetic_run(**qualification_kwargs(self.base))
            self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
        finally:
            (self.base / self.result.experiment_id / self.result.run_id / "stale.json").unlink()

    def test_e2e_04_changed_seal_or_missing_record_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = SealedRun()
            try:
                base = Path(temporary) / "results"
                base.mkdir()
                arguments = qualification_kwargs(base)
                arguments.update(
                    {"bundle": run.bundle, "run_dir": run.run_dir, "scenario_root": run.evidence}
                )
                sealed_copy = Path(temporary) / run.run_dir.name
                shutil.copytree(run.run_dir, sealed_copy)
                seal_path = sealed_copy / "seal.json"
                seal = read_json(seal_path)
                seal["files"] = seal["files"][1:]
                seal_path.write_bytes(canonical_document_bytes(seal))
                arguments["run_dir"] = sealed_copy
                with self.assertRaises(BenchError) as raised:
                    coordinator.qualify_synthetic_run(**arguments)
                self.assertIn(
                    raised.exception.code, {BM_IDENTITY_INVALID, BM_EVIDENCE_UNAVAILABLE}
                )
            finally:
                run.close()

    def test_e2e_05_foreign_scenario_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "results"
            base.mkdir()
            scenario_root = Path(temporary) / "foreign-scenario"
            scenario_root.mkdir()
            scenario = read_json(
                experiment_root() / "synthetic-scenario.v1.json"
            )
            scenario["experiment_id"] = "synthetic-execution-smoke"
            write_canonical(
                scenario_root / "synthetic-scenario.v1.json", scenario
            )
            args = qualification_kwargs(base)
            args["scenario_root"] = scenario_root
            with self.assertRaises(BenchError) as raised:
                coordinator.qualify_synthetic_run(**args)
            self.assertIn(
                raised.exception.code,
                {BM_IDENTITY_INVALID, BM_EVIDENCE_UNAVAILABLE, BM_SCHEMA_INVALID},
            )
            self.assertEqual(list(base.iterdir()), [])

    def test_e2e_06_to_09_bad_or_missing_anchors_are_rejected_before_derivation(self) -> None:
        for override, code in (
            ({"expected_profile_digest": ZERO}, BM_IDENTITY_INVALID),
            ({"expected_framework_qa_digest": ZERO}, BM_IDENTITY_INVALID),
            ({"expected_source_qa_digest": ZERO}, BM_IDENTITY_INVALID),
            ({"expected_source_set_digest": ZERO}, BM_IDENTITY_INVALID),
            ({"expected_profile_digest": ""}, BM_EVIDENCE_UNAVAILABLE),
            ({"expected_source_set_digest": None}, BM_EVIDENCE_UNAVAILABLE),
        ):
            with tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary) / "results"
                base.mkdir()
                arguments = qualification_kwargs(base)
                arguments.update(override)
                with self.assertRaises(BenchError) as raised:
                    coordinator.qualify_synthetic_run(**arguments)
                self.assertEqual(raised.exception.code, code, override)
                self.assertEqual(list(base.iterdir()), [])

    def test_e2e_10_non_synthetic_scope_is_rejected_before_io(self) -> None:
        run = sealed_run()
        real_identity = dataclasses.replace(run.bundle.adapter.build_identity, kind="real")
        real_adapter = dataclasses.replace(run.bundle.adapter, build_identity=real_identity)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "results"
            base.mkdir()
            arguments = qualification_kwargs(base)
            arguments["bundle"] = dataclasses.replace(run.bundle, adapter=real_adapter)
            with self.assertRaises(BenchError) as raised:
                coordinator.qualify_synthetic_run(**arguments)
            self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)
            self.assertEqual(list(base.iterdir()), [])

        official_document = {
            **run.bundle.adapter_document,
            "evidence_origin": "real",
            "qualification_scope": "official",
        }
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "results"
            base.mkdir()
            arguments = qualification_kwargs(base)
            arguments["bundle"] = dataclasses.replace(
                run.bundle, adapter_document=official_document
            )
            with self.assertRaises(BenchError) as raised:
                coordinator.qualify_synthetic_run(**arguments)
            self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)
            self.assertEqual(list(base.iterdir()), [])

    def test_e2e_11_qa_failure_blocks_acceptance_without_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "results"
            base.mkdir()
            arguments = qualification_kwargs(base)
            with mock.patch.object(
                qa,
                "read_qa_evidence",
                side_effect=BenchError(BM_IDENTITY_INVALID, "injected QA failure"),
            ):
                with self.assertRaises(BenchError):
                    coordinator.qualify_synthetic_run(**arguments)
            self.assertEqual(list(base.iterdir()), [])


class ScopeIsolationTests(unittest.TestCase):
    """SCOPE-01/02 and E2E-12 guardrails."""

    def test_scope_01_real_build_identity_is_rejected_before_io(self) -> None:
        run = sealed_run()
        real_identity = dataclasses.replace(
            run.bundle.adapter.build_identity, kind="real"
        )
        bundle = dataclasses.replace(
            run.bundle,
            adapter=dataclasses.replace(run.bundle.adapter, build_identity=real_identity),
        )
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "results"
            base.mkdir()
            arguments = qualification_kwargs(base)
            arguments["bundle"] = bundle
            with self.assertRaises(BenchError) as raised:
                coordinator.qualify_synthetic_run(**arguments)
            self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)
            self.assertEqual(list(base.iterdir()), [])

    def test_scope_02_official_scope_relabel_is_rejected(self) -> None:
        run = sealed_run()
        bundle = dataclasses.replace(
            run.bundle,
            adapter_document={
                **run.bundle.adapter_document,
                "evidence_origin": "real",
                "qualification_scope": "official",
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "results"
            base.mkdir()
            arguments = qualification_kwargs(base)
            arguments["bundle"] = bundle
            with self.assertRaises(BenchError) as raised:
                coordinator.qualify_synthetic_run(**arguments)
            self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)

    def test_e2e_12_no_acquisition_or_hidden_writes(self) -> None:
        run = sealed_run()
        before = {
            path.relative_to(run.run_dir): path.read_bytes()
            for path in run.run_dir.rglob("*")
            if path.is_file()
        }
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "results"
            base.mkdir()
            arguments = qualification_kwargs(base)
            arguments.update(
                {"bundle": run.bundle, "run_dir": run.run_dir, "scenario_root": run.evidence}
            )
            result = coordinator.qualify_synthetic_run(**arguments)
            self.assertEqual(result.disposition, "SIMULATED_QUALIFIED")
            published = {path.name for path in (base / result.experiment_id / result.run_id).iterdir()}
            self.assertEqual(published, set(MEMBER_NAMES))
            self.assertEqual(
                sorted(entry.name for entry in base.iterdir()), [result.experiment_id]
            )
        after = {
            path.relative_to(run.run_dir): path.read_bytes()
            for path in run.run_dir.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        package = Path(coordinator.__file__).parent
        for name in (
            "coordinator.py",
            "admission.py",
            "qa.py",
            "receipts.py",
            "manifest.py",
            "publication.py",
            "contracts.py",
            "profiles.py",
        ):
            source = (package / name).read_text(encoding="utf-8")
            for forbidden in (
                "socket",
                "urllib",
                "requests",
                "subprocess",
                "time.time",
                "datetime.now",
                "uuid.uuid4",
                "pytest",
                "unittest",
            ):
                self.assertNotIn(forbidden, source, f"{name} must not reference {forbidden}")


class PolicySemanticsTests(unittest.TestCase):
    """POLICY-01…04."""

    def _summary(self, status: str) -> dict[str, Any]:
        summary = copy.deepcopy(committed_documents()["acceptance-summary.json"])
        summary["policy_decision_status"] = status
        return summary

    def _decision(self, **kwargs: Any) -> Any:
        return evaluate_policy(
            analysis_document(default_campaigns(**kwargs)),
            make_policy_profile(),
            make_resources(),
            minimum_retained_blocks=3,
        )

    def test_policy_01_eligible_status_is_preserved_without_performance_claims(self) -> None:
        decision = self._decision()
        self.assertEqual(decision.decision_status, "SELECTED_ELIGIBLE_SYNTHETIC")
        summary = self._summary(decision.decision_status)
        validate_acceptance_summary(summary)
        self.assertEqual(
            summary["policy_decision_status"], "SELECTED_ELIGIBLE_SYNTHETIC"
        )
        self.assertNotIn("PASS", summary["policy_decision_status"])
        committed = committed_documents()["acceptance-summary.json"]
        self.assertEqual(
            committed["policy_decision_status"],
            committed_documents()["policy.json"]["decision_status"],
        )

    def test_policy_02_inconclusive_is_a_legitimate_framework_qualification(self) -> None:
        decision = self._decision(
            common=("1.050000000000", "1.050000000000", "1.000000000000", "1.100000000001", "analyzed")
        )
        self.assertEqual(decision.decision_status, "INCONCLUSIVE")
        summary = self._summary(decision.decision_status)
        validate_acceptance_summary(summary)
        self.assertEqual(summary["policy_decision_status"], "INCONCLUSIVE")

    def test_policy_03_baseline_only_is_preserved(self) -> None:
        decision = self._decision(
            common=("1.200000000000", "1.200000000000", "1.150000000000", "1.300000000000", "analyzed")
        )
        self.assertEqual(decision.decision_status, "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE")
        summary = self._summary(decision.decision_status)
        validate_acceptance_summary(summary)
        self.assertEqual(
            summary["policy_decision_status"], "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE"
        )

    def test_policy_04_tie_and_relabel_are_rejected_or_preserved(self) -> None:
        for status in sorted(DECISION_STATUSES):
            validate_acceptance_summary(self._summary(status))
        policy = copy.deepcopy(committed_documents()["policy.json"])
        policy["decision_status"] = "SELECTED_ELIGIBLE_SYNTHETIC"
        if committed_documents()["policy.json"]["decision_status"] == (
            "SELECTED_ELIGIBLE_SYNTHETIC"
        ):
            policy["decision_status"] = "TIE_PREFERENCE_NOT_PROVEN_FASTER"
        bundle = sealed_run().bundle
        with self.assertRaises(BenchError):
            validate_policy_decision(
                policy,
                bundle,
                read_policy_profile(experiment_root(), bundle),
                content_digest(committed_documents()["analysis.json"]),
                read_resource_observations(experiment_root(), bundle).digest,
            )
        self.assertFalse(hasattr(qualification_contracts.QualificationResult, "winner"))
        self.assertNotIn("PASS", " ".join(sorted(DECISION_STATUSES)))


class ReuseInvalidationTests(unittest.TestCase):
    """REUSE-01…10."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.base, cls.result = qualified_once()

    def _load(self, **overrides: Any) -> Any:
        return load_committed(self.base, **overrides)

    def test_reuse_01_valid_reuse_returns_verified_without_new_files(self) -> None:
        before = sorted(entry.name for entry in self.result.output_directory.iterdir())
        again = self._load()
        self.assertEqual(again.disposition, "REUSED_VERIFIED")
        self.assertEqual(again.manifest_digest, self.result.manifest_digest)
        self.assertEqual(
            sorted(entry.name for entry in self.result.output_directory.iterdir()), before
        )

    def test_reuse_02_changed_sealed_bytes_reject_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy_root = Path(temporary) / sealed_run().run_dir.name
            shutil.copytree(sealed_run().run_dir, copy_root)
            seal = read_json(copy_root / "seal.json")
            victim = copy_root / seal["files"][1]["path"]
            victim.write_bytes(victim.read_bytes() + b" ")
            with self.assertRaises(BenchError) as raised:
                self._load(run_dir=copy_root)
            self.assertIn(
                raised.exception.code, {BM_IDENTITY_INVALID, BM_EVIDENCE_UNAVAILABLE}
            )

    def test_reuse_03_changed_protocol_binding_rejects_reuse(self) -> None:
        bundle = sealed_run().bundle
        changed = dataclasses.replace(
            bundle,
            protocol_document={
                **bundle.protocol_document,
                "protocol_id": "synthetic-protocol-drift",
            },
        )
        with self.assertRaises(BenchError) as raised:
            self._load(bundle=changed)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_reuse_04_changed_analysis_profile_rejects_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profiles = Path(temporary) / "profiles"
            shutil.copytree(experiment_root(), profiles)
            profile = read_json(profiles / "analysis-profile.v1.json")
            profile["bootstrap"]["resamples"] = 500
            write_canonical(profiles / "analysis-profile.v1.json", profile)
            with self.assertRaises(BenchError) as raised:
                self._load(profiles_root=profiles, resources_root=profiles)
            self.assertIn(
                raised.exception.code, {BM_IDENTITY_INVALID, "BM_SCHEMA_INVALID"}
            )

    def test_reuse_05_source_byte_change_rejects_reuse(self) -> None:
        anchors = trust_anchors()
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_source_tree(Path(temporary) / "source")
            self.assertEqual(
                compute_source_set_digest(root), anchors["source_set_digest"]
            )
            run, base, result = _fresh_qualification(Path(temporary) / "work")
            try:
                self.assertEqual(result.disposition, "SIMULATED_QUALIFIED")
                victim = root / "benchmarks/quervant_bench/qualification/contracts.py"
                victim.write_bytes(victim.read_bytes() + b"\n# source drift\n")
                arguments = qualification_kwargs(base)
                arguments.update(
                    {
                        "bundle": run.bundle,
                        "run_dir": run.run_dir,
                        "scenario_root": run.evidence,
                        "source_root": root,
                    }
                )
                with self.assertRaises(BenchError) as raised:
                    coordinator.load_qualified_synthetic_run(**arguments)
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            finally:
                run.close()

    def _qa_override(self, mutator: Any) -> dict[str, Any]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "qualification"
        root.mkdir()
        shutil.copytree(FIXTURES, root / "qa")
        qa_root = root / "qa"
        document = read_json(qa_root / "framework-qa-evidence.json")
        mutator(document)
        write_canonical(qa_root / "framework-qa-evidence.json", document)
        return {
            "qa_evidence_root": qa_root,
            "expected_framework_qa_digest": content_digest(document),
        }

    def test_reuse_06_framework_qa_not_executed_rejects_reuse(self) -> None:
        def mutate(document: dict[str, Any]) -> None:
            document["checks"][0]["executed"] = False

        with self.assertRaises(BenchError) as raised:
            self._load(**self._qa_override(mutate))
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_reuse_07_source_qa_skipped_rejects_reuse(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        qa_root = Path(temporary.name) / "qa"
        shutil.copytree(FIXTURES, qa_root)
        document = read_json(qa_root / "source-qa-evidence.json")
        document["checks"][0]["mandatory_skipped"] = 1
        write_canonical(qa_root / "source-qa-evidence.json", document)
        with self.assertRaises(BenchError) as raised:
            self._load(
                qa_evidence_root=qa_root,
                expected_source_qa_digest=content_digest(document),
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_reuse_08_changed_roster_profile_rejects_reuse(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "synthetic-framework.v1.json"
        profile = read_json(
            REPO_ROOT
            / "benchmarks/quervant_bench/qualification/profiles/synthetic-framework.v1.json"
        )
        profile["required_gates"] = profile["required_gates"][:-1]
        write_canonical(path, profile)
        with self.assertRaises(BenchError) as raised:
            self._load(
                qualification_profile_path=path,
                expected_profile_digest=content_digest(profile),
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_reuse_09_toolchain_drift_rejects_reuse(self) -> None:
        def mutate(document: dict[str, Any]) -> None:
            document["toolchain_id"] = "python-3-13"

        with self.assertRaises(BenchError) as raised:
            self._load(**self._qa_override(mutate))
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_reuse_10_alternate_run_receipt_is_rejected(self) -> None:
        documents = committed_documents()
        alternate = build_stage_receipt(
            gate="admission",
            subject={
                **documents["admission.json"]["subject"],
                "run_id": "00000000-0000-4000-8000-000000000099",
            },
            validator=validator_identity(
                "admission", trust_anchors()["source_set_digest"]
            ),
            inputs={
                entry["name"]: entry["digest"] for entry in documents["admission.json"]["inputs"]
            },
            outputs={
                entry["name"]: entry["digest"] for entry in documents["admission.json"]["outputs"]
            },
        )
        with self.assertRaises(BenchError) as raised:
            verify_stage_receipt(
                alternate,
                gate="admission",
                source_set_digest=trust_anchors()["source_set_digest"],
                expected_subject=documents["admission.json"]["subject"],
                inputs={
                    entry["name"]: entry["digest"]
                    for entry in documents["admission.json"]["inputs"]
                },
                outputs={
                    entry["name"]: entry["digest"]
                    for entry in documents["admission.json"]["outputs"]
                },
                dependencies=(),
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


class BoundAndCliTests(unittest.TestCase):
    """BOUND-01/02."""

    def test_bound_01_run_verb_still_exits_77_without_output(self) -> None:
        import contextlib
        import io

        from quervant_bench import cli

        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(
            io.StringIO()
        ):
            out = Path(temporary) / "out"
            code = cli.main(
                [
                    "run",
                    "--experiment",
                    "synthetic-contract-smoke",
                    "--protocol",
                    "protocol.yaml",
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 77)
            self.assertFalse(out.exists())
            for verb in ("validate", "analyze", "verify", "accept", "report"):
                self.assertEqual(
                    cli.main(
                        [verb, "--run", "00000000-0000-4000-8000-000000000030"]
                    ),
                    69,
                )
        self.assertEqual(
            cli.dispatch.__module__, "quervant_bench.cli"
        )
        self.assertEqual(
            cli.RESERVED_VERBS, ("validate", "analyze", "verify", "accept", "report")
        )
        self.assertNotIn("qualification", vars(cli))
        self.assertEqual(
            __import__("quervant_bench.qualification", fromlist=["__all__"]).__all__,
            ["QualificationResult", "load_qualified_synthetic_run", "qualify_synthetic_run"],
        )
        self.assertEqual(BM_ACQUISITION_PROHIBITED, "BM_ACQUISITION_PROHIBITED")
        self.assertEqual(BM_NOT_IMPLEMENTED, "BM_NOT_IMPLEMENTED")

    def test_bound_02_no_timed_acquisition_or_public_schema_change(self) -> None:
        from quervant_bench.config.contracts import GATES

        self.assertEqual(
            GATES,
            (
                "admission",
                "analysis",
                "verification",
                "acceptance",
                "attestation",
                "framework-qa",
                "source-qa",
            ),
        )
        schema_root = REPO_ROOT / "benchmarks/quervant_bench/config/schemas"
        self.assertEqual(
            sorted(path.name for path in schema_root.glob("*.json")),
            [
                "adapter.v1.schema.json",
                "experiment.v1.schema.json",
                "outcome.v1.schema.json",
                "protocol.v1.schema.json",
                "receipt.v1.schema.json",
                "workload.v1.schema.json",
            ],
        )
        import quervant_bench.qualification.coordinator as coordinator_module

        source = Path(coordinator_module.__file__).read_text(encoding="utf-8")
        for forbidden in ("subprocess", "socket", "time.sleep", "requests", "urllib"):
            self.assertNotIn(forbidden, source)
        self.assertEqual(profile_digest(), trust_anchors()["profile_digest"])


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()


class AdmissionTests(unittest.TestCase):
    """A-01…06 — sealed BM-03 structural admission."""

    def test_a_01_valid_replay_builds_the_canonical_index(self) -> None:
        run = sealed_run()
        index, receipt = admission.build_admission(
            bundle=run.bundle,
            run_dir=run.run_dir,
            scenario_root=run.evidence,
            profile_digest=trust_anchors()["profile_digest"],
            source_set_digest=trust_anchors()["source_set_digest"],
        )
        self.assertEqual(index["subject"]["run_id"], run.run_dir.name)
        self.assertEqual(index["files"], sorted(index["files"], key=lambda entry: entry["path"]))
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(receipt["gate"], "admission")
        self.assertEqual(receipt["dependencies"], [])
        sealed = admission.verify_sealed_bytes(run.run_dir, index)
        self.assertEqual(sealed, index)

    def _copied_run(self, temporary: Path) -> Path:
        run = sealed_run()
        copy_root = temporary / run.run_dir.name
        shutil.copytree(run.run_dir, copy_root)
        return copy_root

    def test_a_02_missing_envelope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy_root = self._copied_run(Path(temporary))
            victim = copy_root / "slots/treatment-0000/block-0001/slot-0001/common-query.json"
            victim.unlink()
            with self.assertRaises(BenchError) as raised:
                admission.build_admission_index(
                    bundle=sealed_run().bundle,
                    run_dir=copy_root,
                    scenario_root=sealed_run().evidence,
                    profile_digest=trust_anchors()["profile_digest"],
                    source_set_digest=trust_anchors()["source_set_digest"],
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_a_03_extra_seal_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy_root = self._copied_run(Path(temporary))
            (copy_root / "extra-record.json").write_bytes(b"{}\n")
            with self.assertRaises(BenchError) as raised:
                admission.build_admission_index(
                    bundle=sealed_run().bundle,
                    run_dir=copy_root,
                    scenario_root=sealed_run().evidence,
                    profile_digest=trust_anchors()["profile_digest"],
                    source_set_digest=trust_anchors()["source_set_digest"],
                )
            self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")

    def test_a_04_changed_seal_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy_root = self._copied_run(Path(temporary))
            seal_path = copy_root / "seal.json"
            seal = read_json(seal_path)
            seal["files"][0]["digest"] = "sha256:" + "a" * 64
            seal_path.write_bytes(canonical_document_bytes(seal))
            with self.assertRaises(BenchError) as raised:
                admission.build_admission_index(
                    bundle=sealed_run().bundle,
                    run_dir=copy_root,
                    scenario_root=sealed_run().evidence,
                    profile_digest=trust_anchors()["profile_digest"],
                    source_set_digest=trust_anchors()["source_set_digest"],
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_a_05_foreign_scenario_is_rejected(self) -> None:
        run = sealed_run()
        with tempfile.TemporaryDirectory() as temporary:
            scenario_root = Path(temporary) / "scenario"
            scenario_root.mkdir()
            scenario = read_json(experiment_root() / "synthetic-scenario.v1.json")
            scenario["experiment_id"] = "synthetic-execution-smoke"
            write_canonical(scenario_root / "synthetic-scenario.v1.json", scenario)
            with self.assertRaises(BenchError) as raised:
                admission.build_admission_index(
                    bundle=run.bundle,
                    run_dir=run.run_dir,
                    scenario_root=scenario_root,
                    profile_digest=trust_anchors()["profile_digest"],
                    source_set_digest=trust_anchors()["source_set_digest"],
                )
            self.assertIn(
                raised.exception.code, {BM_IDENTITY_INVALID, BM_EVIDENCE_UNAVAILABLE, BM_SCHEMA_INVALID}
            )

    def test_a_06_complete_campaign_counts_are_bound(self) -> None:
        index = committed_documents()["admission-index.json"]
        counts = index["counts"]
        self.assertEqual(
            counts["lane_envelopes"],
            counts["slots_completed"] * 2,
        )
        self.assertEqual(
            counts["synthetic_samples"],
            counts["slots_completed"] * 2 * 3,
        )
        self.assertEqual(counts["treatments_completed"], 2)
        self.assertEqual(counts["controls_completed"], 1)
        replayed = admission.build_admission_index(
            bundle=sealed_run().bundle,
            run_dir=sealed_run().run_dir,
            scenario_root=sealed_run().evidence,
            profile_digest=index["profile_digest"],
            source_set_digest=index["source_set_digest"],
        )
        self.assertEqual(replayed["counts"], counts)
        self.assertEqual(replayed["files"], index["files"])


class AnalysisAndVerificationTests(unittest.TestCase):
    """B-01…03 and C-01…03."""

    def test_b_01_existing_bm04_derivation_is_reproduced_exactly(self) -> None:
        run = sealed_run()
        analysis, policy = analyze_synthetic_run(
            bundle=run.bundle,
            run_dir=run.run_dir,
            scenario_root=run.evidence,
            profiles_root=experiment_root(),
            resources_root=experiment_root(),
        )
        documents = committed_documents()
        self.assertEqual(content_digest(analysis), content_digest(documents["analysis.json"]))
        self.assertEqual(content_digest(policy), content_digest(documents["policy.json"]))
        bundle = run.bundle
        validate_analysis_result(
            analysis,
            bundle,
            read_analysis_profile(experiment_root(), bundle),
            documents["admission-index.json"]["seal_raw_digest"],
        )
        validate_policy_decision(
            policy,
            bundle,
            read_policy_profile(experiment_root(), bundle),
            content_digest(analysis),
            read_resource_observations(experiment_root(), bundle).digest,
        )

    def test_b_02_swapped_policy_binding_is_rejected(self) -> None:
        documents = committed_documents()
        bundle = sealed_run().bundle
        policy = copy.deepcopy(documents["policy.json"])
        policy["analysis_digest"] = "sha256:" + "b" * 64
        with self.assertRaises(BenchError) as raised:
            validate_policy_decision(
                policy,
                bundle,
                read_policy_profile(experiment_root(), bundle),
                content_digest(documents["analysis.json"]),
                read_resource_observations(experiment_root(), bundle).digest,
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_b_03_changed_protocol_binding_is_rejected(self) -> None:
        documents = committed_documents()
        bundle = sealed_run().bundle
        analysis = copy.deepcopy(documents["analysis.json"])
        analysis["protocol_digest"] = "sha256:" + "c" * 64
        with self.assertRaises(BenchError) as raised:
            validate_analysis_result(
                analysis,
                bundle,
                read_analysis_profile(experiment_root(), bundle),
                documents["admission-index.json"]["seal_raw_digest"],
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_c_01_bm05_remote_assessment_is_reproduced_exactly(self) -> None:
        run = sealed_run()
        documents = committed_documents()
        assessment = verify_synthetic_run(
            bundle=run.bundle,
            run_dir=run.run_dir,
            scenario_root=run.evidence,
            profiles_root=experiment_root(),
            resources_root=experiment_root(),
            analysis_document=documents["analysis.json"],
            policy_document=documents["policy.json"],
        )
        self.assertEqual(assessment.status, "verified-synthetic")
        self.assertEqual(
            list(assessment.check_ids),
            documents["verification-assessment.json"]["check_ids"],
        )
        wrapper = {
            "kind": "synthetic-verification-assessment",
            "schema_version": 1,
            **dataclasses.asdict(assessment),
        }
        wrapper["check_ids"] = list(assessment.check_ids)
        self.assertEqual(wrapper, documents["verification-assessment.json"])

    def test_c_02_forged_analysis_is_rejected_by_bm05(self) -> None:
        run = sealed_run()
        documents = committed_documents()
        analysis = copy.deepcopy(documents["analysis.json"])
        analysis["campaigns"][0]["lanes"][0]["candidates"][0]["ci_low"] = "0.000000000000"
        with self.assertRaises(BenchError):
            verify_synthetic_run(
                bundle=run.bundle,
                run_dir=run.run_dir,
                scenario_root=run.evidence,
                profiles_root=experiment_root(),
                resources_root=experiment_root(),
                analysis_document=analysis,
                policy_document=documents["policy.json"],
            )

    def test_c_03_missing_or_different_vc_id_is_rejected(self) -> None:
        documents = committed_documents()
        assessment = copy.deepcopy(documents["verification-assessment.json"])
        for mutation in (
            lambda doc: doc["check_ids"].pop(),
            lambda doc: doc["check_ids"].__setitem__(0, "VC-99-UNKNOWN"),
            lambda doc: doc["check_ids"].append(doc["check_ids"][0]),
        ):
            tampered = copy.deepcopy(assessment)
            mutation(tampered)
            with self.assertRaises(BenchError):
                validate_verification_assessment(tampered)
        self.assertEqual(
            len(documents["verification-assessment.json"]["check_ids"]), 9
        )
