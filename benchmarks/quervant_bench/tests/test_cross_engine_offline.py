"""CLI/REU/REG evidence: the two-family read-only offline surface."""

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
    BM_UNSAFE_INPUT,
)
from quervant_bench.migrations import offline
from quervant_bench.migrations.cross_engine import (
    REFERENCE_EXPERIMENT_ID as CROSS_ENGINE_EXPERIMENT_ID,
)
from quervant_bench.migrations.retained_key import (
    REFERENCE_EXPERIMENT_ID as RETAINED_KEY_EXPERIMENT_ID,
)
from quervant_bench.tests.cross_engine_support import (
    CatalogEditor,
    copy_catalog,
    copy_workspace,
    read_json,
    snapshot,
    write_canonical,
)
from quervant_bench.tests.test_retained_key_synthetic import (
    ReferenceWorkspace,
    load_reference_bundle,
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


class TwoFamilyOfflineTests(unittest.TestCase):
    """CLI-01…CLI-10 across both registered families."""

    @classmethod
    def setUpClass(cls) -> None:
        from quervant_bench.tests.cross_engine_support import cached_workspace

        cls.cross = cached_workspace(checked_in_anchors=True)
        cls.retained = ReferenceWorkspace(checked_in_anchors=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.retained.close()

    def _stage(
        self, verb: str, workspace: Path, run_id: str
    ) -> tuple[dict[str, Any], bytes]:
        status, stdout, stderr = invoke([verb, "--run", run_id, "--offline"], workspace)
        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        document = json.loads(stdout)
        self.assertEqual(stdout.encode("utf-8"), canonical_document_bytes(document))
        return document, stdout.encode("utf-8")

    def test_cli_01_every_verb_reads_each_family(self) -> None:
        cross = self.cross
        retained = self.retained
        for verb in VERBS:
            with self.subTest(family="cross-engine", verb=verb):
                document, _payload = self._stage(
                    verb, cross.workspace, cross.run_id
                )
                self.assertIsInstance(document, dict)
            with self.subTest(family="retained-key", verb=verb):
                document, _payload = self._stage(
                    verb, retained.workspace, retained.run_id
                )
                self.assertIsInstance(document, dict)

    def test_cli_02_cross_engine_stage_views_are_the_committed_documents(self) -> None:
        cross = self.cross
        validate = self._stage("validate", cross.workspace, cross.run_id)[0]
        self.assertEqual(validate, cross.documents["admission-index.json"])
        verify = self._stage("verify", cross.workspace, cross.run_id)[0]
        self.assertEqual(verify, cross.documents["verification-assessment.json"])
        accept = self._stage("accept", cross.workspace, cross.run_id)[0]
        self.assertEqual(accept, cross.documents["acceptance-summary.json"])

    def test_cli_03_cross_engine_views_are_closed_and_simulated(self) -> None:
        cross = self.cross
        analyze = self._stage("analyze", cross.workspace, cross.run_id)[0]
        self.assertEqual(set(analyze), set(offline._ANALYSIS_VIEW_KEYS))
        self.assertEqual(analyze["kind"], offline.ANALYSIS_VIEW_KIND)
        self.assertEqual(analyze["evidence_origin"], "synthetic")
        self.assertEqual(analyze["qualification_scope"], "simulated")
        self.assertEqual(analyze["analysis"], cross.documents["analysis.json"])
        self.assertEqual(analyze["policy"], cross.documents["policy.json"])
        report = self._stage("report", cross.workspace, cross.run_id)[0]
        self.assertEqual(set(report), set(offline._REPORT_VIEW_KEYS))
        self.assertEqual(report["kind"], offline.REPORT_VIEW_KIND)
        self.assertEqual(
            report["attestation_receipt_id"],
            cross.documents["attestation.json"]["receipt_id"],
        )

    def test_cli_04_reads_do_not_write_either_workspace(self) -> None:
        for workspace, run_id in (
            (self.cross.workspace, self.cross.run_id),
            (self.retained.workspace, self.retained.run_id),
        ):
            before = snapshot(workspace)
            for verb in VERBS:
                self._stage(verb, workspace, run_id)
            self.assertEqual(snapshot(workspace), before)

    def test_cli_05_views_never_execute_derive_verify_or_publish(self) -> None:
        from quervant_bench.qualification import coordinator

        cross = self.cross
        with mock.patch(
            "quervant_bench.execution.controller.execute_synthetic",
            side_effect=AssertionError("acquired"),
        ), mock.patch(
            "quervant_bench.analysis.derive.analyze_synthetic_run",
            side_effect=AssertionError("derived"),
        ), mock.patch(
            "quervant_bench.verification.verify.verify_synthetic_run",
            side_effect=AssertionError("verified"),
        ), mock.patch.object(
            coordinator, "qualify_synthetic_run", side_effect=AssertionError("qualified")
        ), mock.patch.object(
            coordinator, "publish_bundle", side_effect=AssertionError("published")
        ):
            for verb in VERBS:
                document, _payload = self._stage(
                    verb, cross.workspace, cross.run_id
                )
                self.assertIsInstance(document, dict)

    def test_cli_06_foreign_family_is_not_implemented(self) -> None:
        temporary, root = copy_workspace(self.cross.workspace)
        self.addCleanup(temporary.cleanup)
        source = root / "qualified" / CROSS_ENGINE_EXPERIMENT_ID / self.cross.run_id
        foreign = root / "qualified" / "synthetic-third-family" / self.cross.run_id
        foreign.parent.mkdir()
        shutil.copytree(source, foreign)
        shutil.rmtree(source)
        status, stdout, stderr = invoke(
            ["validate", "--run", self.cross.run_id, "--offline"], root
        )
        self.assertEqual(status, 69)
        self.assertEqual(stdout, "")
        self.assertEqual(error_code(stderr), BM_NOT_IMPLEMENTED)

    def test_cli_07_ambiguous_uuid_across_families_is_rejected(self) -> None:
        temporary, root = copy_workspace(self.cross.workspace)
        self.addCleanup(temporary.cleanup)
        source = root / "qualified" / CROSS_ENGINE_EXPERIMENT_ID / self.cross.run_id
        duplicate = root / "qualified" / RETAINED_KEY_EXPERIMENT_ID / self.cross.run_id
        duplicate.parent.mkdir()
        shutil.copytree(source, duplicate)
        status, stdout, stderr = invoke(
            ["validate", "--run", self.cross.run_id, "--offline"], root
        )
        self.assertEqual(status, 65)
        self.assertEqual(stdout, "")
        self.assertEqual(error_code(stderr), BM_IDENTITY_INVALID)

    def test_cli_08_missing_symlinked_and_unsafe_workspaces_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._expect_failure(
                Path(directory) / "missing", BM_EVIDENCE_UNAVAILABLE
            )
        self._expect_failure("", BM_UNSAFE_INPUT)
        self._expect_failure("relative/workspace", BM_UNSAFE_INPUT)

        temporary, root = copy_workspace(self.cross.workspace)
        self.addCleanup(temporary.cleanup)
        target = root / "qualified" / CROSS_ENGINE_EXPERIMENT_ID / self.cross.run_id
        shutil.rmtree(target)
        os.symlink(
            root / "qualified" / RETAINED_KEY_EXPERIMENT_ID / self.retained.run_id,
            target,
        )
        self._expect_failure(root, BM_UNSAFE_INPUT)

    def test_cli_09_run_is_prohibited_before_touching_the_workspace(self) -> None:
        poison = Path("/nonexistent/quervant-offline-workspace")
        with mock.patch.object(
            offline, "dispatch_stage", side_effect=AssertionError("offline")
        ), tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            status, stdout, stderr = invoke(
                [
                    "run",
                    "--experiment",
                    CROSS_ENGINE_EXPERIMENT_ID,
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

    def test_cli_10_both_family_loaders_are_consulted(self) -> None:
        calls = {"cross": 0, "retained": 0}
        real_cross = offline.validate_cross_engine_reference
        real_retained = offline.load_reference_bundle

        def cross(*args: Any, **kwargs: Any):
            calls["cross"] += 1
            return real_cross(*args, **kwargs)

        def retained(*args: Any, **kwargs: Any):
            calls["retained"] += 1
            return real_retained(*args, **kwargs)

        with mock.patch.object(
            offline, "validate_cross_engine_reference", side_effect=cross
        ), mock.patch.object(
            offline, "load_reference_bundle", side_effect=retained
        ):
            self._stage("validate", self.cross.workspace, self.cross.run_id)
            self._stage("validate", self.retained.workspace, self.retained.run_id)
        # The cross-engine companion verifier is consulted before *and* after the
        # BM-06 committed-bundle read, so a mid-read ledger change fails closed.
        self.assertEqual(calls, {"cross": 2, "retained": 1})

    def _expect_failure(self, workspace: Path | str | None, code: str) -> None:
        status, stdout, stderr = invoke(
            ["validate", "--run", self.cross.run_id, "--offline"], workspace
        )
        self.assertNotEqual(status, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(error_code(stderr), code)


class LedgerRevalidationTests(unittest.TestCase):
    """REU-02/REU-04 and CLI fail-closed ledger revalidation."""

    @classmethod
    def setUpClass(cls) -> None:
        from quervant_bench.tests.cross_engine_support import cached_workspace

        cls.cross = cached_workspace(checked_in_anchors=True)

    def test_reu_04_changed_cross_engine_ledger_fails_the_offline_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(catalog)
            editor.documents["semantic-comparability.v1.json"]["excluded_classes"][0][
                "status"
            ] = "COMPARABLE"
            editor.write()
            with mock.patch.object(
                offline, "cross_engine_catalog_root", return_value=catalog
            ):
                status, stdout, stderr = invoke(
                    ["validate", "--run", self.cross.run_id, "--offline"],
                    self.cross.workspace,
                )
        self.assertNotEqual(status, 0)
        self.assertEqual(stdout, "")
        self.assertIn(
            error_code(stderr),
            {BM_IDENTITY_INVALID, BM_UNSAFE_INPUT},
        )

    def test_reu_05_changed_retained_key_catalog_is_never_consulted(self) -> None:
        # The retained-key family keeps its own unchanged catalog; a cross-engine
        # workspace must never be opened by the retained-key branch.
        with tempfile.TemporaryDirectory() as temporary:
            catalog = copy_catalog(Path(temporary) / "catalog")
            with mock.patch.object(
                offline, "cross_engine_catalog_root", return_value=catalog
            ), mock.patch.object(
                offline,
                "load_reference_bundle",
                side_effect=AssertionError("retained-key loader used"),
            ):
                status, _stdout, stderr = invoke(
                    ["validate", "--run", self.cross.run_id, "--offline"],
                    self.cross.workspace,
                )
        self.assertEqual(status, 0, stderr)


class RetainedKeyRegressionTests(unittest.TestCase):
    """REG-01…REG-04: the existing BM-07 family stays byte-identical."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.retained = ReferenceWorkspace(checked_in_anchors=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.retained.close()

    def test_reg_01_retained_key_views_are_unchanged(self) -> None:
        for verb in VERBS:
            status, stdout, stderr = invoke(
                [verb, "--run", self.retained.run_id, "--offline"],
                self.retained.workspace,
            )
            self.assertEqual(status, 0, stderr)
            self.assertEqual(stderr, "")
            document = json.loads(stdout)
            self.assertEqual(stdout.encode("utf-8"), canonical_document_bytes(document))
            if verb == "validate":
                self.assertEqual(document, self.retained.documents["admission-index.json"])
            if verb == "verify":
                self.assertEqual(
                    document, self.retained.documents["verification-assessment.json"]
                )
            if verb == "accept":
                self.assertEqual(
                    document, self.retained.documents["acceptance-summary.json"]
                )

    def test_reg_02_retained_key_family_survives_cross_engine_registry(self) -> None:
        experiment, _directory = offline.resolve_qualified_run(
            self.retained.workspace, self.retained.run_id
        )
        self.assertEqual(experiment, RETAINED_KEY_EXPERIMENT_ID)
        self.assertIn(RETAINED_KEY_EXPERIMENT_ID, offline.FAMILY_LOADERS)
        self.assertIn(CROSS_ENGINE_EXPERIMENT_ID, offline.FAMILY_LOADERS)
        bundle = load_reference_bundle(
            Path(__file__).resolve().parents[2] / "experiments"
        )
        self.assertEqual(
            bundle.experiment.experiment_id, RETAINED_KEY_EXPERIMENT_ID
        )

    def test_reg_03_retained_key_workspace_is_not_written(self) -> None:
        before = snapshot(self.retained.workspace)
        for verb in VERBS:
            invoke(
                [verb, "--run", self.retained.run_id, "--offline"],
                self.retained.workspace,
            )
        self.assertEqual(snapshot(self.retained.workspace), before)

    def test_reg_04_family_map_is_a_frozen_literal(self) -> None:
        self.assertEqual(
            set(offline.FAMILY_LOADERS),
            {RETAINED_KEY_EXPERIMENT_ID, CROSS_ENGINE_EXPERIMENT_ID},
        )
        self.assertIs(offline.FAMILY_LOADERS[RETAINED_KEY_EXPERIMENT_ID], offline.load_reference_bundle)
        self.assertIs(
            offline.FAMILY_LOADERS[CROSS_ENGINE_EXPERIMENT_ID],
            offline.validate_cross_engine_reference,
        )


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
