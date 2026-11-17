"""CLI-01…CLI-13: bounded offline stage views over a committed synthetic bundle."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from quervant_bench import cli
from quervant_bench.config.codec import canonical_document_bytes
from quervant_bench.config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_NOT_IMPLEMENTED,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
)
from quervant_bench.migrations import offline
from quervant_bench.migrations.retained_key import REFERENCE_EXPERIMENT_ID
from quervant_bench.qualification import coordinator
from quervant_bench.qualification.contracts import subject_document
from quervant_bench.tests.test_qualification_contracts import (
    rehash_gate_d,
    write_bundle_documents,
)
from quervant_bench.tests.test_retained_key_synthetic import (
    EXPERIMENTS,
    MEMBER_NAMES,
    ReferenceWorkspace,
    load_reference_bundle,
    read_json,
    write_canonical,
)

ENV = offline.OFFLINE_WORKSPACE_ENV
VERBS = ("validate", "analyze", "verify", "accept", "report")


def invoke(arguments: list[str], workspace: Path | str | None) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with mock.patch.dict(os.environ, {}, clear=False):
        if workspace is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = str(workspace)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = cli.main(arguments)
    return status, stdout.getvalue(), stderr.getvalue()


def error_code(stderr: str) -> str:
    document = json.loads(stderr)
    assert document["kind"] == "outcome"
    return document["code"]


def snapshot(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            entries[relative] = "symlink:" + os.readlink(path)
        elif path.is_dir():
            entries[relative] = "dir"
        else:
            entries[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def copy_workspace(source: Path) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
    target = Path(temporary.name) / "workspace"
    shutil.copytree(source, target)
    return temporary, target


class OfflineCliTests(unittest.TestCase):
    """CLI-01…CLI-13."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = ReferenceWorkspace(checked_in_anchors=True)
        cls.root = cls.workspace.workspace
        cls.run_id = cls.workspace.run_id
        cls.bundle = load_reference_bundle(EXPERIMENTS)
        cls.documents = cls.workspace.documents

    @classmethod
    def tearDownClass(cls) -> None:
        cls.workspace.close()

    def _stage(self, verb: str) -> tuple[dict[str, Any], bytes]:
        status, stdout, stderr = invoke(
            [verb, "--run", self.run_id, "--offline"], self.root
        )
        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        document = json.loads(stdout)
        self.assertEqual(stdout.encode("utf-8"), canonical_document_bytes(document))
        return document, stdout.encode("utf-8")

    def _expect_failure(self, workspace: Path | str | None, code: str) -> None:
        status, stdout, stderr = invoke(
            ["validate", "--run", self.run_id, "--offline"], workspace
        )
        self.assertNotEqual(status, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(error_code(stderr), code)

    def test_cli_02_validate_returns_the_existing_admission_index(self) -> None:
        document, _payload = self._stage("validate")
        self.assertEqual(document, self.documents["admission-index.json"])

    def test_cli_03_analyze_returns_one_closed_simulated_view(self) -> None:
        document, _payload = self._stage("analyze")
        self.assertEqual(set(document), set(offline._ANALYSIS_VIEW_KEYS))
        self.assertEqual(document["kind"], offline.ANALYSIS_VIEW_KIND)
        self.assertEqual(document["evidence_origin"], "synthetic")
        self.assertEqual(document["qualification_scope"], "simulated")
        self.assertEqual(document["subject"], subject_document(self.bundle, self.run_id))
        self.assertEqual(document["manifest_digest"], self.workspace.result.manifest_digest)
        self.assertEqual(document["analysis"], self.documents["analysis.json"])
        self.assertEqual(document["policy"], self.documents["policy.json"])

    def test_cli_04_verify_returns_the_existing_assessment(self) -> None:
        document, _payload = self._stage("verify")
        self.assertEqual(document, self.documents["verification-assessment.json"])

    def test_cli_05_accept_returns_the_existing_acceptance_summary(self) -> None:
        document, _payload = self._stage("accept")
        self.assertEqual(document, self.documents["acceptance-summary.json"])

    def test_cli_06_report_returns_one_closed_simulated_report(self) -> None:
        document, _payload = self._stage("report")
        self.assertEqual(set(document), set(offline._REPORT_VIEW_KEYS))
        self.assertEqual(document["kind"], offline.REPORT_VIEW_KIND)
        self.assertEqual(document["evidence_origin"], "synthetic")
        self.assertEqual(document["qualification_scope"], "simulated")
        self.assertEqual(document["subject"], subject_document(self.bundle, self.run_id))
        self.assertEqual(document["manifest_digest"], self.workspace.result.manifest_digest)
        self.assertEqual(
            document["attestation_receipt_id"],
            self.documents["attestation.json"]["receipt_id"],
        )
        self.assertEqual(document["policy"], self.documents["policy.json"])

    def test_cli_07_nonoffline_verbs_and_run_never_touch_the_workspace(self) -> None:
        poison = Path("/nonexistent/quervant-offline-workspace")
        with mock.patch.object(offline, "dispatch_stage", side_effect=AssertionError("offline")):
            for verb in VERBS:
                status, stdout, stderr = invoke(
                    [verb, "--run", self.run_id], poison
                )
                self.assertEqual(status, 69)
                self.assertEqual(stdout, "")
                self.assertEqual(error_code(stderr), BM_NOT_IMPLEMENTED)
                outcome = json.loads(stderr)
                self.assertEqual(outcome["status"], "blocked")
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "out"
                status, stdout, stderr = invoke(
                    [
                        "run",
                        "--experiment",
                        REFERENCE_EXPERIMENT_ID,
                        "--protocol",
                        "protocol.yaml",
                        "--out",
                        str(output),
                    ],
                    poison,
                )
                self.assertEqual(status, 77)
                self.assertEqual(stdout, "")
                self.assertEqual(error_code(stderr), BM_ACQUISITION_PROHIBITED)
                self.assertFalse(output.exists())

    def test_cli_08_views_never_execute_derive_verify_or_publish(self) -> None:
        patches = (
            mock.patch(
                "quervant_bench.execution.controller.execute_synthetic",
                side_effect=AssertionError("acquired"),
            ),
            mock.patch(
                "quervant_bench.analysis.derive.analyze_synthetic_run",
                side_effect=AssertionError("derived"),
            ),
            mock.patch(
                "quervant_bench.verification.verify.verify_synthetic_run",
                side_effect=AssertionError("verified"),
            ),
            mock.patch.object(
                coordinator, "qualify_synthetic_run", side_effect=AssertionError("qualified")
            ),
            mock.patch.object(
                coordinator, "publish_bundle", side_effect=AssertionError("published")
            ),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            for verb in VERBS:
                document, _payload = self._stage(verb)
                self.assertIsInstance(document, dict)

    def test_cli_09_reads_do_not_write_the_workspace(self) -> None:
        before = snapshot(self.root)
        for verb in VERBS:
            self._stage(verb)
        after = snapshot(self.root)
        self.assertEqual(before, after)

    def test_cli_10_unique_run_is_resolved_within_the_workspace(self) -> None:
        experiment, directory = offline.resolve_qualified_run(self.root, self.run_id)
        self.assertEqual(experiment, REFERENCE_EXPERIMENT_ID)
        self.assertEqual(
            directory, self.root / "qualified" / REFERENCE_EXPERIMENT_ID / self.run_id
        )

    def test_cli_11_discovery_failures_are_typed_and_never_truncated(self) -> None:
        temporary, root = copy_workspace(self.root)
        self.addCleanup(temporary.cleanup)
        shutil.rmtree(root / "qualified" / REFERENCE_EXPERIMENT_ID / self.run_id)
        self._expect_failure(root, BM_EVIDENCE_UNAVAILABLE)

        temporary, root = copy_workspace(self.root)
        self.addCleanup(temporary.cleanup)
        source = root / "qualified" / REFERENCE_EXPERIMENT_ID / self.run_id
        duplicate = root / "qualified" / "other-experiment" / self.run_id
        shutil.copytree(source, duplicate)
        self._expect_failure(root, BM_IDENTITY_INVALID)

        temporary, root = copy_workspace(self.root)
        self.addCleanup(temporary.cleanup)
        source = root / "qualified" / REFERENCE_EXPERIMENT_ID / self.run_id
        original = source
        linked = root / "qualified" / "other-experiment" / self.run_id
        (root / "qualified" / "other-experiment").mkdir()
        os.symlink(original, linked)
        self._expect_failure(root, BM_UNSAFE_INPUT)

        temporary, root = copy_workspace(self.root)
        self.addCleanup(temporary.cleanup)
        for index in range(128):
            (root / "qualified" / f"experiment-{index:03d}").mkdir()
        self._expect_failure(root, BM_UNSAFE_INPUT)

        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            self._expect_failure(missing, BM_EVIDENCE_UNAVAILABLE)
        self._expect_failure("", BM_UNSAFE_INPUT)
        self._expect_failure("relative/workspace", BM_UNSAFE_INPUT)

        temporary, root = copy_workspace(self.root)
        self.addCleanup(temporary.cleanup)
        write_canonical(root / offline.ANCHOR_NAME, {})
        self._expect_failure(root, BM_SCHEMA_INVALID)

        temporary, root = copy_workspace(self.root)
        self.addCleanup(temporary.cleanup)
        (root / offline.ANCHOR_NAME).unlink()
        self._expect_failure(root, BM_EVIDENCE_UNAVAILABLE)

        temporary, root = copy_workspace(self.root)
        self.addCleanup(temporary.cleanup)
        source = root / "qualified" / REFERENCE_EXPERIMENT_ID / self.run_id
        other = root / "qualified" / "other-experiment" / self.run_id
        other.parent.mkdir()
        shutil.copytree(source, other)
        shutil.rmtree(source)
        self._expect_failure(root, BM_NOT_IMPLEMENTED)

    def test_cli_12_tampered_bundle_and_qa_are_rejected(self) -> None:
        temporary, root = copy_workspace(self.root)
        self.addCleanup(temporary.cleanup)
        manifest = (
            root / "qualified" / REFERENCE_EXPERIMENT_ID / self.run_id / "manifest.json"
        )
        manifest.write_bytes(manifest.read_bytes() + b" ")
        self._expect_failure(root, BM_UNSAFE_INPUT)

        temporary, root = copy_workspace(self.root)
        self.addCleanup(temporary.cleanup)
        record = root / "qa" / "framework-qa" / "python-contracts.json"
        record.write_bytes(record.read_bytes() + b" ")
        status, stdout, stderr = invoke(
            ["validate", "--run", self.run_id, "--offline"], root
        )
        self.assertNotEqual(status, 0)
        self.assertEqual(stdout, "")
        self.assertIn(
            error_code(stderr),
            {BM_UNSAFE_INPUT, BM_IDENTITY_INVALID, BM_EVIDENCE_UNAVAILABLE},
        )

    def test_cli_13_coherently_rehashed_foreign_summary_is_rejected(self) -> None:
        temporary, root = copy_workspace(self.root)
        self.addCleanup(temporary.cleanup)
        directory = root / "qualified" / REFERENCE_EXPERIMENT_ID / self.run_id
        documents = {name: read_json(directory / name) for name in MEMBER_NAMES}
        documents["acceptance-summary.json"]["subject"]["run_id"] = (
            "00000000-0000-4000-8000-000000000011"
        )
        rehash_gate_d(documents)
        write_bundle_documents(
            root / "qualified", REFERENCE_EXPERIMENT_ID, self.run_id, documents
        )
        status, stdout, stderr = invoke(
            ["validate", "--run", self.run_id, "--offline"], root
        )
        self.assertNotEqual(status, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(error_code(stderr), BM_IDENTITY_INVALID)

        temporary, root = copy_workspace(self.root)
        self.addCleanup(temporary.cleanup)
        anchors = read_json(root / offline.ANCHOR_NAME)
        anchors["source_set_digest"] = "sha256:" + "0" * 64
        write_canonical(root / offline.ANCHOR_NAME, anchors)
        self._expect_failure(root, BM_IDENTITY_INVALID)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
