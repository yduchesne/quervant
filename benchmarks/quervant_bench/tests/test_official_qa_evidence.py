"""RF09-09 / QAE: every mandated QA check needs its executed artifact and log."""

from __future__ import annotations

import copy
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.config.codec import content_digest
from quervant_bench.official import contracts, qa_evidence
from quervant_bench.tests import official_support as support


class ExecutedQaEvidenceTests(unittest.TestCase):
    """The reader validates 33 check records and 33 raw logs, twice."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.bundle = support.qa_evidence_sandbox(cls.root)
        cls.freeze = cls.bundle.freeze

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _verify(self, *, root: Path | None = None, framework=None, source=None):
        return qa_evidence.verify_executed_qa_evidence(
            qa_evidence_root=root or self.bundle.root,
            framework_summary=framework or self.bundle.framework_summary,
            source_summary=source or self.bundle.source_summary,
            freeze=self.freeze,
            output_root=self.root / "output",
            raw_root=self.bundle.raw_root,
        )

    def test_qae_01_complete_evidence_verifies_and_returns_66_member_snapshot(self) -> None:
        snapshot = self._verify()
        self.assertEqual(len(snapshot), 66)
        self.assertEqual(
            list(snapshot), sorted(snapshot)
        )

    def test_qae_02_missing_roster_record_is_rejected(self) -> None:
        path = self.bundle.root / "framework-qa" / "python-full-suite.json"
        original = path.read_bytes()
        try:
            path.unlink()
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
        finally:
            path.write_bytes(original)

    def test_qae_04_missing_check_record_blocks(self) -> None:
        path = self.bundle.root / "source-qa" / "rust-coverage-85.json"
        original = path.read_bytes()
        try:
            path.unlink()
            with self.assertRaises(BenchError):
                self._verify()
        finally:
            path.write_bytes(original)

    def test_qae_05_changed_check_record_is_rejected(self) -> None:
        path = self.bundle.root / "framework-qa" / "python-mutations.json"
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document["job_name"] = "rust"
            support.write_json(path, document)
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            path.write_bytes(original)

    def test_qae_07_empty_log_is_rejected(self) -> None:
        path = self.bundle.root / "logs" / "framework-qa" / "python-full-suite.log"
        original = path.read_bytes()
        try:
            path.write_bytes(b"")
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
        finally:
            path.write_bytes(original)

    def test_qae_08_symlinked_log_is_rejected(self) -> None:
        path = self.bundle.root / "logs" / "source-qa" / "rust-doc.log"
        original = path.read_bytes()
        target = self.root.parent / "outside-qa-root.log"
        target.write_bytes(original)
        try:
            path.unlink()
            os.symlink(target, path)
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
        finally:
            path.unlink()
            path.write_bytes(original)
            target.unlink()

    def test_qae_09_changed_log_bytes_are_rejected(self) -> None:
        path = self.bundle.root / "logs" / "framework-qa" / "benchmark-scripts.log"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"tampered\n")
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            path.write_bytes(original)

    def test_qae_10_coherently_rehashed_record_and_log_still_fail_the_pin(self) -> None:
        record_path = self.bundle.root / "framework-qa" / "cross-engine-l2.json"
        log_path = self.bundle.root / "logs" / "framework-qa" / "cross-engine-l2.log"
        record_original = record_path.read_bytes()
        log_original = log_path.read_bytes()
        try:
            log_path.write_bytes(log_original + b"coherent tamper\n")
            record = support.read_json(record_path)
            record["log_raw_sha256"] = (
                "sha256:" + __import__("hashlib").sha256(log_path.read_bytes()).hexdigest()
            )
            support.write_json(record_path, record)
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            record_path.write_bytes(record_original)
            log_path.write_bytes(log_original)

    def test_qae_13_wrong_job_identity_is_rejected(self) -> None:
        path = self.bundle.root / "source-qa" / "rust-fmt-msrv.json"
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document["job_name"] = "rust"
            support.write_json(path, document)
            with self.assertRaises(BenchError):
                self._verify()
        finally:
            path.write_bytes(original)

    def test_qae_14_nonzero_exit_code_is_rejected(self) -> None:
        path = self.bundle.root / "framework-qa" / "python-compileall.json"
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document["command_exit_code"] = 1
            support.write_json(path, document)
            with self.assertRaises(BenchError):
                self._verify()
        finally:
            path.write_bytes(original)

    def test_qae_15_boolean_flag_is_rejected(self) -> None:
        path = self.bundle.root / "framework-qa" / "retained-key-l2.json"
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document["failed"] = False
            support.write_json(path, document)
            with self.assertRaises(BenchError):
                self._verify()
        finally:
            path.write_bytes(original)

    def test_qae_18_unapproved_summary_pin_is_rejected(self) -> None:
        document = copy.deepcopy(dict(self.bundle.framework_summary))
        document["checks"][0]["evidence_digest"] = "sha256:" + "9" * 64
        with self.assertRaises(BenchError) as raised:
            self._verify(framework=document)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_qae_19_reverify_detects_post_gate_change(self) -> None:
        snapshot = self._verify()
        path = self.bundle.root / "logs" / "source-qa" / "rust-test-stable-default.log"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"late\n")
            with self.assertRaises(BenchError) as raised:
                qa_evidence.reverify_executed_qa_evidence(
                    qa_evidence_root=self.bundle.root,
                    expected_snapshot=snapshot,
                    framework_summary=self.bundle.framework_summary,
                    source_summary=self.bundle.source_summary,
                    freeze=self.freeze,
                    output_root=self.root / "output",
                    raw_root=self.bundle.raw_root,
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            path.write_bytes(original)

    def test_f3_qae_20_in_repository_root_is_unsafe(self) -> None:
        self.assertTrue(support.REPO_ROOT.is_dir())
        with self.assertRaises(BenchError) as raised:
            self._verify(root=support.REPO_ROOT)
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_f3_qae_20b_in_repository_benchmarks_root_is_unsafe(self) -> None:
        root = support.REPO_ROOT / "benchmarks"
        self.assertTrue(root.is_dir())
        with self.assertRaises(BenchError) as raised:
            self._verify(root=root)
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_f3_qae_20c_absent_evidence_root_is_missing(self) -> None:
        missing = self.root / "definitely-absent-f3-qa-root"
        self.assertFalse(missing.exists())
        with self.assertRaises(BenchError) as raised:
            self._verify(root=missing)
        self.assertEqual(raised.exception.code, BM_FILE_MISSING)


class RosterMappingTests(unittest.TestCase):
    def test_qae_21_job_map_covers_both_rosters_exactly(self) -> None:
        mapping = qa_evidence.GATE_CHECK_EXECUTORS
        framework = {key for (gate, key) in mapping if gate == "framework-qa"}
        source = {key for (gate, key) in mapping if gate == "source-qa"}
        self.assertEqual(framework, set(contracts.FRAMEWORK_QA_ROSTER))
        self.assertEqual(source, set(contracts.SOURCE_QA_ROSTER))
        self.assertEqual(len(framework), 15)
        self.assertEqual(len(source), 18)


FRAMEWORK_QA_IDS = (
    "benchmark-scripts",
    "bm-contract-inventory",
    "cross-engine-l2",
    "installed-console",
    "official-authorization-boundary",
    "official-control-boundary",
    "official-data-integrity",
    "official-deterministic",
    "official-independent-verification",
    "official-real-correctness",
    "official-source-set",
    "python-compileall",
    "python-full-suite",
    "python-mutations",
    "retained-key-l2",
)


class QaRosterBoundaryTests(unittest.TestCase):
    """C-F01: source QA regression coverage replaces the run-specific cycle."""

    def test_c_t01_framework_roster_is_the_exact_source_regression_roster(self) -> None:
        self.assertEqual(contracts.FRAMEWORK_QA_ROSTER, FRAMEWORK_QA_IDS)
        self.assertEqual(len(contracts.FRAMEWORK_QA_ROSTER), 15)
        self.assertEqual(len(contracts.SOURCE_QA_ROSTER), 18)
        mapping = qa_evidence.GATE_CHECK_EXECUTORS
        framework = {key for (gate, key) in mapping if gate == "framework-qa"}
        source = {key for (gate, key) in mapping if gate == "source-qa"}
        self.assertEqual(framework, set(FRAMEWORK_QA_IDS))
        self.assertEqual(source, set(contracts.SOURCE_QA_ROSTER))

    def test_c_t02_new_boundary_checks_require_the_hosted_python_contracts_job(self) -> None:
        for check_id in ("official-authorization-boundary", "official-control-boundary"):
            with self.subTest(check_id=check_id):
                self.assertEqual(
                    qa_evidence.GATE_CHECK_EXECUTORS[("framework-qa", check_id)],
                    ("hosted-ci", "python-contracts"),
                )

    def test_c_t03_old_operator_checks_cannot_satisfy_the_roster(self) -> None:
        for old in ("official-g0-review", "official-real-aa"):
            with self.subTest(check_id=old):
                self.assertNotIn(old, contracts.FRAMEWORK_QA_ROSTER)
                self.assertNotIn(("framework-qa", old), qa_evidence.GATE_CHECK_EXECUTORS)
        substituted = tuple(
            "official-g0-review" if item == "official-authorization-boundary" else item
            for item in FRAMEWORK_QA_IDS
        )
        self.assertNotEqual(list(substituted), list(contracts.FRAMEWORK_QA_ROSTER))


class CoherentRosterForgeTests(unittest.TestCase):
    """C-T02: a coherently rehashed operator record still fails the roster pin."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_c_t02_operator_attested_boundary_record_is_rejected(self) -> None:
        from quervant_bench.config.codec import canonical_document_bytes
        from quervant_bench.official import contracts as official_contracts

        for check_id in ("official-authorization-boundary", "official-control-boundary"):
            with self.subTest(check_id=check_id):
                root = Path(tempfile.mkdtemp(dir=self._temporary.name))
                bundle = support.qa_evidence_sandbox(root / "qa")
                record_path = bundle.root / qa_evidence.check_record_relative(
                    "framework-qa", check_id
                )
                record = support.read_json(record_path)
                record["executor"] = "operator-attested"
                record["job_name"] = "operator-local"
                record["execution_reference"] = "operator-attested-run"
                record_digest = support.write_json(record_path, record)
                summary = copy.deepcopy(bundle.framework_summary)
                for row in summary["checks"]:
                    if row["check_id"] == check_id:
                        row["evidence_digest"] = record_digest
                self.assertEqual(
                    summary["qa_roster_digest"],
                    content_digest(
                        {
                            "kind": "official-qa-roster",
                            "schema_version": 1,
                            "framework": list(official_contracts.FRAMEWORK_QA_ROSTER),
                            "source": list(official_contracts.SOURCE_QA_ROSTER),
                        }
                    ),
                )
                freeze = unpack_freeze(bundle.freeze, summary)
                with self.assertRaises(BenchError) as raised:
                    qa_evidence.verify_executed_qa_evidence(
                        qa_evidence_root=bundle.root,
                        framework_summary=summary,
                        source_summary=bundle.source_summary,
                        freeze=freeze,
                        output_root=root / "output",
                        raw_root=bundle.raw_root,
                    )
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                self.assertEqual(raised.exception.field_path, check_id)

    def test_c_t03_complete_new_roster_positive_succeeds(self) -> None:
        root = Path(tempfile.mkdtemp(dir=self._temporary.name))
        bundle = support.qa_evidence_sandbox(root / "qa")
        snapshot = qa_evidence.verify_executed_qa_evidence(
            qa_evidence_root=bundle.root,
            framework_summary=bundle.framework_summary,
            source_summary=bundle.source_summary,
            freeze=bundle.freeze,
            output_root=root / "output",
            raw_root=bundle.raw_root,
        )
        self.assertEqual(len(snapshot), 66)
        self.assertEqual(
            sorted(
                Path(member).name
                for member in snapshot
                if member.startswith("framework-qa/")
            ).count("official-authorization-boundary.json"),
            1,
        )


def unpack_freeze(freeze, summary):
    import dataclasses

    return dataclasses.replace(
        freeze, qa_framework_digest=content_digest(summary)
    )


class BranchPushWorkflowTests(unittest.TestCase):
    """C-F03: the branch push run proves the exact authorized source."""

    WORKFLOW = support.REPO_ROOT / ".github" / "workflows" / "ci.yml"

    def _workflow(self) -> dict:
        return yaml.load(self.WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    def _script(self) -> str:
        workflow = self._workflow()
        scripts = set()
        for job in workflow["jobs"].values():
            steps = job["steps"]
            self.assertEqual(steps[0]["uses"], "actions/checkout@v4")
            identity = steps[1]
            self.assertEqual(identity["name"], "Record tested source identity")
            self.assertEqual(identity["shell"], "bash")
            self.assertNotIn("if", identity)
            self.assertNotIn("continue-on-error", identity)
            self.assertEqual(
                identity["env"],
                {
                    "BM09_EVENT_NAME": "${{ github.event_name }}",
                    "BM09_EVENT_SHA": "${{ github.sha }}",
                    "BM09_PR_HEAD_SHA": "${{ github.event.pull_request.head.sha || '' }}",
                },
            )
            self.assertNotIn("ref", steps[0].get("with", {}) or {})
            scripts.add(identity["run"])
        self.assertEqual(len(scripts), 1)
        return scripts.pop()

    def test_c_t10_branch_push_binds_the_actual_checkout(self) -> None:
        workflow = self._workflow()
        self.assertEqual(set(workflow["on"]), {"push", "pull_request"})
        self.assertEqual(
            workflow["on"]["push"]["branches"], ["main", "dev/bm09-real-qualification"]
        )
        self.assertEqual(set(workflow["on"]["push"]), {"branches"})
        self.assertEqual(
            set(workflow["jobs"]),
            {"rust", "msrv", "rustfs", "python-contracts"},
        )
        script = self._script()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=support.REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=support.REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        def run(**values):
            environment = dict(os.environ)
            environment.update(values)
            return subprocess.run(
                ["bash", "-c", script],
                cwd=support.REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )

        exact = run(BM09_EVENT_NAME="push", BM09_EVENT_SHA=head, BM09_PR_HEAD_SHA="")
        self.assertEqual(exact.returncode, 0, exact.stderr)
        self.assertIn(f"checkout_sha={head}", exact.stdout)
        self.assertIn(f"checkout_tree={tree}", exact.stdout)

        wrong = run(
            BM09_EVENT_NAME="push", BM09_EVENT_SHA="0" * 40, BM09_PR_HEAD_SHA=""
        )
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn(f"checkout_sha={head}", wrong.stdout)

        merge = run(
            BM09_EVENT_NAME="pull_request",
            BM09_EVENT_SHA=head,
            BM09_PR_HEAD_SHA="1" * 40,
        )
        self.assertEqual(merge.returncode, 0, merge.stderr)
        self.assertIn(f"pr_head_sha={'1' * 40}", merge.stdout)
        self.assertIn(f"checkout_sha={head}", merge.stdout)

        missing = run(
            BM09_EVENT_NAME="push", BM09_EVENT_SHA="", BM09_PR_HEAD_SHA=""
        )
        self.assertNotEqual(missing.returncode, 0)

    def test_c_t10b_workflow_differs_from_the_migration_baseline_only_by_c_f03(self) -> None:
        import subprocess as sp

        baseline = sp.run(
            ["git", "show", "bff24340ed3e8f86ea0df87e3192fa0a5cd608f2:.github/workflows/ci.yml"],
            cwd=support.REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        current = self._workflow()
        baseline_document = yaml.load(baseline, Loader=yaml.BaseLoader)
        baseline_document["on"]["push"]["branches"] = [
            "main",
            "dev/bm09-real-qualification",
        ]
        for job in baseline_document["jobs"].values():
            job["steps"].insert(
                1,
                {
                    "name": "Record tested source identity",
                    "shell": "bash",
                    "env": current["jobs"]["rust"]["steps"][1]["env"],
                    "run": current["jobs"]["rust"]["steps"][1]["run"],
                },
            )
        self.assertEqual(current, baseline_document)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()


class ExecutedQaProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.bundle = support.qa_evidence_sandbox(cls.root / "qa")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _verify(self, *, root: Path | None = None):
        return qa_evidence.verify_executed_qa_evidence(
            qa_evidence_root=root or self.bundle.root,
            framework_summary=self.bundle.framework_summary,
            source_summary=self.bundle.source_summary,
            freeze=self.bundle.freeze,
            output_root=self.root / "output",
            raw_root=self.bundle.raw_root,
        )

    def _mutate(self, relative: str, field: str, value):
        path = self.bundle.root / relative
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document[field] = value
            support.write_json(path, document)
            with self.assertRaises(BenchError) as raised:
                self._verify()
            return raised.exception.code
        finally:
            path.write_bytes(original)

    def test_qae_12_wrong_source_commit_is_rejected(self) -> None:
        code = self._mutate("framework-qa/python-full-suite.json", "source_commit", "b" * 40)
        self.assertEqual(code, BM_IDENTITY_INVALID)

    def test_qae_12b_wrong_source_set_is_rejected(self) -> None:
        code = self._mutate(
            "framework-qa/python-full-suite.json", "source_set_digest", "sha256:" + "3" * 64
        )
        self.assertEqual(code, BM_IDENTITY_INVALID)

    def test_qae_13b_fake_hosted_url_is_rejected(self) -> None:
        code = self._mutate(
            "framework-qa/benchmark-scripts.json",
            "execution_reference",
            "https://github.com/yduchesne/quervant/actions/runs/0",
        )
        self.assertEqual(code, BM_IDENTITY_INVALID)

    def test_qae_13c_operator_check_labelled_hosted_is_rejected(self) -> None:
        code = self._mutate(
            "source-qa/host-capability-readiness.json", "executor", "hosted-ci"
        )
        self.assertEqual(code, BM_IDENTITY_INVALID)

    def test_qae_15b_non_executed_check_is_rejected(self) -> None:
        code = self._mutate("framework-qa/python-mutations.json", "executed", 1)
        self.assertIn(code, (BM_IDENTITY_INVALID, "BM_SCHEMA_INVALID"))

    def test_qae_17_reverify_accepts_an_unchanged_snapshot(self) -> None:
        snapshot = self._verify()
        qa_evidence.reverify_executed_qa_evidence(
            qa_evidence_root=self.bundle.root,
            expected_snapshot=snapshot,
            framework_summary=self.bundle.framework_summary,
            source_summary=self.bundle.source_summary,
            freeze=self.bundle.freeze,
            output_root=self.root / "output",
            raw_root=self.bundle.raw_root,
        )
