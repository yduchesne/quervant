"""Shared lifecycle, configured CLI and logical synthetic integration contracts.

These tests never start a benchmark, engine, service or measured timer. Synthetic
integration uses the existing logical controller and an isolated source snapshot.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import shutil
import tempfile
import types
import unittest
import uuid
from pathlib import Path
from unittest import mock

from quervant_bench import cli
from quervant_bench.config.codec import canonical_document_bytes, content_digest, load_document
from quervant_bench.config.contracts import build_outcome, validate_outcome
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_INTERNAL_ERROR,
    BM_OK,
    BM_PUBLICATION_CONFLICT,
    BM_SCHEMA_INVALID,
    BM_SCHEMA_UNSUPPORTED,
    BM_SCOPE_MISMATCH,
    BM_UNSAFE_INPUT,
    BM_USAGE,
    BenchError,
)
from quervant_bench.execution import operator
from quervant_bench.execution.synthetic_operator import read_synthetic_operation
from quervant_bench.qualification.identity import compute_source_set_digest
from quervant_bench.qualification.profiles import default_profile_path
from quervant_bench.tests.cross_engine_support import snapshot
from quervant_bench.tests.test_qualification_contracts import materialize_source_tree, qa_workspace

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG = REPO_ROOT / "benchmarks" / "experiments"
RUN_ID = "00000000-0000-4000-8000-000000000001"


def invoke_cli(arguments: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli.main(arguments)
    return code, stdout.getvalue(), stderr.getvalue()


def write_json(path: Path, document: dict) -> None:
    path.write_bytes(canonical_document_bytes(document))


class OperatorStageTests(unittest.TestCase):
    def test_closed_plans_execute_once_in_order_and_record_scope(self) -> None:
        plans = {
            "official-acquisition": ("authorize", "readiness", "control", "control-verify", "treatment", "admission"),
            "official-validation": ("authorize", "admission"),
            "official-analysis": ("authorize", "admission", "analysis"),
            "official-verification": ("authorize", "admission", "analysis", "verification"),
            "official-acceptance": ("authorize", "admission", "analysis", "verification", "acceptance", "attestation"),
            "synthetic-qualification": ("prepare", "acquisition", "qualification"),
        }
        for plan, stages in plans.items():
            with self.subTest(plan=plan):
                calls, events = [], []

                def callback(stage: str) -> str:
                    calls.append(stage)
                    return stage + "-result"

                backend = {stage: lambda stage=stage: callback(stage) for stage in reversed(stages)}
                result = operator.execute_stages(plan, backend, on_event=events.append)
                self.assertEqual(calls, list(stages))
                self.assertEqual(result, {stage: stage + "-result" for stage in stages})
                self.assertEqual([event["sequence"] for event in events], list(range(1, len(stages) * 2 + 1)))
                self.assertEqual([(event["stage"], event["event"]) for event in events], [
                    (stage, event) for stage in stages for event in ("started", "completed")
                ])
                scope = ("synthetic", "simulated") if plan.startswith("synthetic") else ("real", "official")
                self.assertEqual({(event["evidence_origin"], event["qualification_scope"]) for event in events}, {scope})
                self.assertTrue(all(event["error_code"] is None for event in events))

    def test_plan_and_callback_mismatches_fail_before_effects(self) -> None:
        called = mock.Mock()
        cases = (
            ("arbitrary-plugin", {}, BM_USAGE),
            ("official-analysis", {"authorize": called}, BM_SCHEMA_INVALID),
            ("official-analysis", {"authorize": called, "admission": called, "analysis": called, "extra": called}, BM_SCHEMA_INVALID),
            ("official-analysis", {"authorize": called, "admission": None, "analysis": called}, BM_SCHEMA_INVALID),
        )
        for plan, backend, code in cases:
            with self.subTest(plan=plan, keys=list(backend)):
                with self.assertRaises(BenchError) as caught:
                    operator.execute_stages(plan, backend)
                self.assertEqual(caught.exception.code, code)
        called.assert_not_called()

    def test_failure_preserves_typed_error_and_stops_without_retry(self) -> None:
        failure = BenchError(BM_IDENTITY_INVALID, "private token must not enter journal", field_path="control")
        failing = mock.Mock(side_effect=failure)
        later = mock.Mock()
        events = []
        with self.assertRaises(BenchError) as caught:
            operator.execute_stages(
                "official-analysis",
                {"authorize": lambda: None, "admission": failing, "analysis": later},
                on_event=events.append,
            )
        self.assertIs(caught.exception, failure)
        failing.assert_called_once_with()
        later.assert_not_called()
        self.assertEqual(events[-1]["event"], "failed")
        self.assertEqual(events[-1]["error_code"], BM_IDENTITY_INVALID)
        self.assertNotIn("private token", json.dumps(events))

    def test_journal_write_failure_prevents_next_stage(self) -> None:
        later = mock.Mock()

        def writer(event: dict) -> None:
            if event["event"] == "completed":
                raise OSError("full disk")

        with self.assertRaises(OSError):
            operator.execute_stages(
                "official-analysis",
                {"authorize": lambda: None, "admission": later, "analysis": later},
                on_event=writer,
            )
        later.assert_not_called()

    def test_callback_failure_survives_failed_failure_journal(self) -> None:
        failure = BenchError(BM_IDENTITY_INVALID, "control failed")

        def writer(event: dict) -> None:
            if event["event"] == "failed":
                raise OSError("journal unavailable")

        with self.assertRaises(BenchError) as caught:
            operator.execute_stages(
                "official-analysis",
                {"authorize": mock.Mock(side_effect=failure), "admission": lambda: None, "analysis": lambda: None},
                on_event=writer,
            )
        self.assertIs(caught.exception, failure)

    def test_backend_is_snapshotted_and_interruption_never_advances(self) -> None:
        calls, events = [], []
        backend = {
            "authorize": lambda: backend.update(admission=lambda: calls.append("replacement")),
            "admission": lambda: calls.append("original"),
            "analysis": mock.Mock(side_effect=KeyboardInterrupt()),
        }
        with self.assertRaises(KeyboardInterrupt):
            operator.execute_stages("official-analysis", backend, on_event=events.append)
        self.assertEqual(calls, ["original"])
        self.assertEqual(events[-1]["event"], "interrupted")
        self.assertEqual(events[-1]["error_code"], BM_INTERNAL_ERROR)


class ConfiguredCliTests(unittest.TestCase):
    def test_backend_text_system_exit_is_nonzero_and_diagnostic_is_private(self) -> None:
        for exit_value in ("D3C_PRIVATE_DIAGNOSTIC", 0, 1, None):
            with self.subTest(exit_value=exit_value):
                with mock.patch.object(cli, "dispatch", side_effect=SystemExit(exit_value)):
                    code, stdout, stderr = invoke_cli(["inspect", "--experiment", operator.OFFICIAL_EXPERIMENTS[0]])
                self.assertEqual((code, stdout), (70, ""))
                self.assertEqual(json.loads(stderr)["code"], BM_INTERNAL_ERROR)
                self.assertNotIn("D3C_PRIVATE_DIAGNOSTIC", stderr)

    def test_official_inspect_is_candidate_only_and_deterministic(self) -> None:
        for experiment in operator.OFFICIAL_EXPERIMENTS:
            with self.subTest(experiment=experiment):
                first = invoke_cli(["inspect", "--experiment", experiment])
                self.assertEqual(first[0], 0, first[2])
                self.assertEqual(first, invoke_cli(["inspect", "--experiment", experiment]))
                data = json.loads(first[1])["data"]
                self.assertEqual(data["authorization_status"], "INDEPENDENT_G0_REQUIRED")
                self.assertTrue(data["operation_config_required"])
                self.assertEqual((data["evidence_origin"], data["qualification_scope"]), ("real", "official"))
                self.assertRegex(data["template_digest"], r"^sha256:[0-9a-f]{64}$")
                self.assertRegex(data["backend_protocol_digest"], r"^sha256:[0-9a-f]{64}$")

    def test_cli_forwards_fixed_operation_arguments(self) -> None:
        outcome = {"forwarded": True}
        for verb in ("run", "prepare"):
            with self.subTest(verb=verb), mock.patch.object(operator, "dispatch_" + verb, return_value=outcome) as dispatch:
                code, stdout, stderr = invoke_cli([
                    verb, "--experiment", operator.OFFICIAL_EXPERIMENTS[0],
                    "--protocol", "candidate.json", "--out", "new-output", "--config", "operation.json",
                ])
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(json.loads(stdout), outcome)
                dispatch.assert_called_once_with(operator.OFFICIAL_EXPERIMENTS[0], Path("candidate.json"), Path("new-output"), Path("operation.json"))
        for verb in operator.STAGE_VERBS:
            with self.subTest(verb=verb), mock.patch.object(operator, "dispatch_stage", return_value=outcome) as dispatch:
                code, stdout, stderr = invoke_cli([verb, "--run", RUN_ID, "--config", "operation.json"])
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(json.loads(stdout), outcome)
                dispatch.assert_called_once_with(verb, RUN_ID, Path("operation.json"))

    def test_offline_and_config_conflict_before_file_reads(self) -> None:
        with mock.patch.object(operator, "read_operation_document", side_effect=AssertionError("read forbidden")):
            for verb in operator.STAGE_VERBS:
                with self.subTest(verb=verb):
                    code, stdout, stderr = invoke_cli([verb, "--run", RUN_ID, "--offline", "--config", "missing.json"])
                    self.assertEqual((code, stdout), (64, ""))
                    self.assertEqual(json.loads(stderr)["code"], BM_USAGE)

    def test_dispatch_cannot_cross_scopes_or_name_an_arbitrary_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            for kind, experiment in (
                (operator.SYNTHETIC_CONFIG_KIND, operator.OFFICIAL_EXPERIMENTS[0]),
                (operator.OFFICIAL_CONFIG_KIND, operator.SYNTHETIC_EXPERIMENTS[0]),
            ):
                write_json(config, {"kind": kind, "schema_version": 1})
                with self.assertRaises(BenchError) as caught:
                    operator.dispatch_run(experiment, root / "protocol", root / "out", config)
                self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)
            write_json(config, {"kind": operator.SYNTHETIC_CONFIG_KIND, "schema_version": 1})
            with self.assertRaises(BenchError) as caught:
                operator.dispatch_prepare(operator.SYNTHETIC_EXPERIMENTS[0], root / "protocol", root / "out", config)
            self.assertEqual(caught.exception.code, BM_USAGE)
            write_json(config, {"kind": "python-import", "schema_version": 1, "module": "untrusted"})
            with self.assertRaises(BenchError) as caught:
                operator.read_operation_document(config)
            self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

    def test_official_dispatch_routes_to_only_known_workflow_functions(self) -> None:
        module = types.ModuleType("quervant_bench.official.workflow")
        module.run_official = mock.Mock(return_value={"stage": "run"})
        module.prepare_official = mock.Mock(return_value={"stage": "prepare"})
        module.dispatch_official_stage = mock.Mock(return_value={"stage": "verify"})
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict("sys.modules", {module.__name__: module}):
            root = Path(temporary)
            config = root / "config.json"
            write_json(config, {"kind": operator.OFFICIAL_CONFIG_KIND, "schema_version": 1})
            self.assertEqual(operator.dispatch_run(operator.OFFICIAL_EXPERIMENTS[0], root / "p", root / "o", config), {"stage": "run"})
            self.assertEqual(operator.dispatch_prepare(operator.OFFICIAL_EXPERIMENTS[0], root / "p", root / "o", config), {"stage": "prepare"})
            self.assertEqual(operator.dispatch_stage("verify", RUN_ID, config), {"stage": "verify"})
        module.run_official.assert_called_once()
        module.prepare_official.assert_called_once()
        module.dispatch_official_stage.assert_called_once_with("verify", RUN_ID, config)

    def test_config_reader_rejects_links_oversize_duplicates_and_bool_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            payloads = (
                b"x" * 65_537,
                b'{"kind":"synthetic-operation","kind":"official-operation-config","schema_version":1}',
                b'{"kind":"synthetic-operation","schema_version":true}',
            )
            for payload in payloads:
                with self.subTest(payload_length=len(payload)):
                    config.write_bytes(payload)
                    with self.assertRaises(BenchError):
                        operator.read_operation_document(config)
            write_json(config, {"kind": operator.SYNTHETIC_CONFIG_KIND, "schema_version": 1})
            link = root / "link.json"
            link.symlink_to(config)
            with self.assertRaises(BenchError) as caught:
                operator.read_operation_document(link)
            self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)


class OperatorOutcomeTests(unittest.TestCase):
    def official_result(self) -> dict:
        return {
            "kind": "official-operation-result",
            "schema_version": 1,
            "study_id": operator.OFFICIAL_EXPERIMENTS[0],
            "run_id": RUN_ID,
            "evidence_origin": "real",
            "qualification_scope": "official",
            "stage": "run",
            "status": "REAL_EVIDENCE_SEALED",
            "raw_series_root_digest": "sha256:" + "1" * 64,
            "admission_digest": None,
            "analysis_digest": None,
            "policy_digest": None,
            "decision_status": None,
            "verification_status": None,
            "manifest_digest": None,
            "attestation_reopened": False,
            "accepted": False,
        }

    def test_frozen_v1_schema_and_registry_remain_unchanged(self) -> None:
        from quervant_bench.config import schemas
        from quervant_bench.qualification.identity import EXTRA_SOURCE_FILES

        path = REPO_ROOT / "benchmarks/quervant_bench/config/schemas/outcome.v1.schema.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
            "8e7d575d8cb3e10e5ee20b19ff989e209999287d40b9130cd2c7a9f956fc51cc")
        self.assertEqual(schemas.supported_kinds()["outcome"], (1,))
        self.assertNotIn(("outcome", 2), schemas.registry())
        self.assertIn("benchmarks/quervant_bench/config/operator_schemas/outcome.v2.schema.json", EXTRA_SOURCE_FILES)

    def test_every_new_operator_payload_uses_v2_and_rejects_v1_downgrade(self) -> None:
        from quervant_bench.official.protocols import OBSERVED_IDENTITY_FIELDS
        from quervant_bench.config.operator_schema import OPERATOR_PAYLOAD_KINDS

        digest = "sha256:" + "1" * 64
        status, out, err = invoke_cli(["inspect", "--experiment", operator.OFFICIAL_EXPERIMENTS[0]])
        self.assertEqual((status, err), (0, ""))
        inspection = json.loads(out)
        self.assertEqual(inspection["schema_version"], 2)
        observed = {field: "1" * 40 if field == "source_commit" else digest for field in OBSERVED_IDENTITY_FIELDS}
        observed["output_root_identity"] = "/tmp/operator-output"
        payloads = [
            inspection["data"], self.official_result(),
            {"kind": "official-authorization-inputs", "schema_version": 1,
                "study_id": operator.OFFICIAL_EXPERIMENTS[0], "evidence_origin": "real",
                "qualification_scope": "official", "status": "AWAITING_INDEPENDENT_G0_REVIEW",
                "observations": observed, "measurement_executed": False},
            {"kind": "synthetic-operation-result", "schema_version": 1,
                "experiment_id": operator.SYNTHETIC_EXPERIMENTS[0], "run_id": RUN_ID,
                "evidence_origin": "synthetic", "qualification_scope": "simulated",
                "disposition": "SIMULATED_QUALIFIED", "manifest_digest": digest,
                "attestation_receipt_id": digest, "output_directory": "/tmp/operator-output"},
            {"kind": "synthetic-operation-stage", "schema_version": 1,
                "experiment_id": operator.SYNTHETIC_EXPERIMENTS[1], "run_id": RUN_ID,
                "evidence_origin": "synthetic", "qualification_scope": "simulated",
                "stage": "validate", "manifest_digest": digest, "attestation_receipt_id": digest,
                "documents": {"admission.json": {"evidence_origin": "synthetic", "qualification_scope": "simulated"}}},
        ]
        self.assertEqual({payload["kind"] for payload in payloads}, set(OPERATOR_PAYLOAD_KINDS))
        for payload in payloads:
            with self.subTest(kind=payload["kind"]):
                outcome = build_outcome("ok", BM_OK, "operator result", payload)
                self.assertEqual(outcome["schema_version"], 2)
                validate_outcome(outcome)
                downgraded = {**outcome, "schema_version": 1}
                with self.assertRaises(BenchError) as caught:
                    validate_outcome(downgraded)
                self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

    def test_ordinary_inspection_and_errors_preserve_v1_and_unknown_versions_fail(self) -> None:
        code, out, err = invoke_cli(["inspect", "--experiment", "synthetic-contract-smoke"])
        self.assertEqual((code, err), (0, ""))
        inspection = json.loads(out)
        self.assertEqual(inspection["schema_version"], 1)
        validate_outcome(inspection)
        error = build_outcome("error", BM_USAGE, "invalid command",
            {"kind": "error-detail", "reason": "invalid-cli-usage"})
        self.assertEqual(error["schema_version"], 1)
        validate_outcome(error)
        # v2 admits the same closed error shape, although the current CLI emits
        # its backward-compatible v1 errors regardless of the requested command.
        validate_outcome({**error, "schema_version": 2})
        for version, expected in ((0, BM_SCHEMA_UNSUPPORTED), (3, BM_SCHEMA_UNSUPPORTED),
                                  (99, BM_SCHEMA_UNSUPPORTED), (2.0, BM_SCHEMA_INVALID),
                                  (True, BM_SCHEMA_INVALID)):
            with self.subTest(version=version), self.assertRaises(BenchError) as caught:
                validate_outcome({**error, "schema_version": version})
            self.assertEqual(caught.exception.code, expected)
        with self.assertRaises(BenchError):
            validate_outcome({**inspection, "schema_version": 2})

    def test_official_summary_cannot_claim_acceptance_from_an_earlier_stage(self) -> None:
        good = build_outcome("ok", BM_OK, "sealed evidence", self.official_result())
        for update in (
            {"accepted": True},
            {"attestation_reopened": True},
            {"status": "REAL_OFFICIAL_QUALIFIED"},
            {"manifest_digest": "sha256:" + "2" * 64},
            {"raw_series_root_digest": None},
        ):
            with self.subTest(update=update):
                changed = copy.deepcopy(good)
                changed["data"].update(update)
                with self.assertRaises(BenchError) as caught:
                    validate_outcome(changed)
                self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_all_official_stage_summaries_require_their_exact_evidence_fields(self) -> None:
        digest = "sha256:" + "3" * 64
        rows = {
            "validate": {"status": "ADMITTED_REAL", "admission_digest": digest},
            "analyze": {"status": "ANALYZED_REAL", "analysis_digest": digest, "policy_digest": digest, "decision_status": "SELECTED"},
            "verify": {"status": "VERIFIED_REAL", "analysis_digest": digest, "policy_digest": digest, "decision_status": "SELECTED", "verification_status": "VERIFIED_REAL"},
            "accept": {"status": "REAL_OFFICIAL_QUALIFIED", "policy_digest": digest, "decision_status": "SELECTED", "verification_status": "VERIFIED_REAL", "manifest_digest": digest, "attestation_reopened": True, "accepted": True},
            "report": {"status": "REAL_OFFICIAL_QUALIFIED", "policy_digest": digest, "decision_status": "SELECTED", "verification_status": "VERIFIED_REAL", "manifest_digest": digest, "attestation_reopened": True, "accepted": True},
        }
        for stage, fields in rows.items():
            with self.subTest(stage=stage):
                data = {**self.official_result(), "raw_series_root_digest": None, "stage": stage, **fields}
                validate_outcome(build_outcome("ok", BM_OK, "completed", data))
                missing = copy.deepcopy(data)
                field = next(name for name in fields if name.endswith("_digest"))
                missing[field] = None
                with self.assertRaises(BenchError):
                    build_outcome("ok", BM_OK, "incomplete", missing)

    def test_preparation_cannot_self_approve_or_claim_measurements(self) -> None:
        from quervant_bench.official.protocols import OBSERVED_IDENTITY_FIELDS

        observed = {
            field: "1" * 40 if field == "source_commit" else "sha256:" + "2" * 64
            for field in OBSERVED_IDENTITY_FIELDS
        }
        observed["output_root_identity"] = "/tmp/operator-output"
        data = {
            "kind": "official-authorization-inputs", "schema_version": 1,
            "study_id": operator.OFFICIAL_EXPERIMENTS[0],
            "evidence_origin": "real", "qualification_scope": "official",
            "status": "AWAITING_INDEPENDENT_G0_REVIEW",
            "observations": observed, "measurement_executed": False,
        }
        build_outcome("ok", BM_OK, "candidate", data)
        for update in ({"measurement_executed": True}, {"approved": True}, {"status": "APPROVED"}):
            with self.subTest(update=update):
                with self.assertRaises(BenchError) as caught:
                    build_outcome("ok", BM_OK, "invalid candidate", {**data, **update})
                self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

    def test_current_baseline_schema_additions_preserve_existing_official_definitions(self) -> None:
        path = REPO_ROOT / "benchmarks/quervant_bench/config/operator_schemas/outcome.v2.schema.json"
        definitions = json.loads(path.read_text())["$defs"]
        self.assertEqual(content_digest(definitions["officialOperation"]), "sha256:225ed22d4b4b4b0186a35af2782680bf066b3d3d21933bc9eb3a5c27757f2ee7")
        self.assertEqual(content_digest(definitions["officialPreparation"]), "sha256:3eb58cc407769be8b380b3f8ae14b41fe3e3d4a667fd7b998b6beaa1fbb741e2")

    def test_current_baseline_preparation_requires_exact_twenty_typed_observations(self) -> None:
        from quervant_bench.official.protocols import OBSERVED_IDENTITY_FIELDS

        digest = "sha256:" + "2" * 64
        for study in ("cross-engine-keyword-real-v1", "retained-key-topk-real-v1"):
            observed = {field: "1" * 40 if field == "source_commit" else digest for field in OBSERVED_IDENTITY_FIELDS}
            observed.update(output_root_identity="/tmp/operator-output", acceptance_profile="current-baseline-v2",
                            baseline_id=RUN_ID, preservation_root_identity="/ordinary/benchmark-results/baselines/" + RUN_ID,
                            runtime_freeze_digest=None if study == "cross-engine-keyword-real-v1" else digest)
            data = {"kind": "official-authorization-inputs", "schema_version": 2, "study_id": study,
                    "evidence_origin": "real", "qualification_scope": "official", "status": "AWAITING_INDEPENDENT_G0_REVIEW",
                    "observations": observed, "measurement_executed": False}
            with self.subTest(study=study):
                self.assertEqual(len(observed), 20)
                build_outcome("ok", BM_OK, "candidate", data)
            for label, field, value in (
                ("runtime-family", "runtime_freeze_digest", digest if observed["runtime_freeze_digest"] is None else None),
                ("uuid", "baseline_id", "other"), ("profile", "acceptance_profile", "real-official-v1"),
                ("root", "preservation_root_identity", "/ordinary/../escape"), ("extra", "approved", True),
            ):
                with self.subTest(study=study, case=label), self.assertRaises(BenchError):
                    build_outcome("ok", BM_OK, "invalid candidate", {**data, "observations": {**observed, field: value}})
            for version in (1, True, 2.0, 3):
                with self.subTest(study=study, version=version), self.assertRaises(BenchError):
                    build_outcome("ok", BM_OK, "invalid candidate", {**data, "schema_version": version})

    def test_current_baseline_all_stage_outcomes_are_closed_and_stage_bound(self) -> None:
        digest = "sha256:" + "3" * 64
        rows = {
            "run": {"status": "REAL_EVIDENCE_SEALED", "raw_series_root_digest": digest},
            "validate": {"status": "ADMITTED_REAL", "admission_digest": digest},
            "analyze": {"status": "ANALYZED_REAL", "analysis_digest": digest, "policy_digest": digest, "decision_status": "POLICY_NOT_DERIVABLE"},
            "verify": {"status": "VERIFIED_CURRENT_BASELINE", "analysis_digest": digest, "policy_digest": digest, "decision_status": "POLICY_NOT_DERIVABLE", "verification_status": "VERIFIED_CURRENT_BASELINE", "policy_verification_status": "NOT_EVALUATED"},
            "accept": {"status": "CURRENT_BASELINE_QUALIFIED", "policy_digest": digest, "decision_status": "POLICY_NOT_DERIVABLE", "verification_status": "VERIFIED_CURRENT_BASELINE", "policy_verification_status": "NOT_EVALUATED", "manifest_digest": digest, "attestation_reopened": True, "accepted": True},
            "report": {"status": "CURRENT_BASELINE_QUALIFIED", "policy_digest": digest, "decision_status": "POLICY_NOT_DERIVABLE", "verification_status": "VERIFIED_CURRENT_BASELINE", "policy_verification_status": "NOT_EVALUATED", "manifest_digest": digest, "attestation_reopened": True, "accepted": True},
        }
        for stage, fields in rows.items():
            data = {**self.official_result(), "schema_version": 2, "raw_series_root_digest": None,
                    "study_id": "retained-key-topk-real-v1", "stage": stage,
                    "acceptance_profile": "current-baseline-v2", "baseline_id": RUN_ID,
                    "policy_verification_status": None, "complete_baseline_preserved": False,
                    "clean_checkout_replay_verified": False, **fields}
            with self.subTest(stage=stage):
                build_outcome("ok", BM_OK, "completed", data)
                cross = {**data, "study_id": "cross-engine-keyword-real-v1", "policy_verification_status": "PASS" if stage in ("verify", "accept", "report") else None}
                build_outcome("ok", BM_OK, "completed", cross)
            for field in ("acceptance_profile", "baseline_id", "policy_verification_status", "complete_baseline_preserved", "clean_checkout_replay_verified"):
                missing = dict(data)
                del missing[field]
                with self.subTest(stage=stage, missing=field), self.assertRaises(BenchError):
                    build_outcome("ok", BM_OK, "incomplete", missing)
            for change in ({"schema_version": 1}, {"schema_version": 2.0}, {"complete_baseline_preserved": 1},
                           {"clean_checkout_replay_verified": True}, {"policy_verification_status": None if stage in ("verify", "accept", "report") else "PASS"},
                           {"unknown": True}):
                with self.subTest(stage=stage, change=change), self.assertRaises(BenchError):
                    build_outcome("ok", BM_OK, "invalid stage", {**data, **change})

    def test_synthetic_stage_requires_exact_members_and_synthetic_scope(self) -> None:
        data = {
            "kind": "synthetic-operation-stage", "schema_version": 1,
            "experiment_id": operator.SYNTHETIC_EXPERIMENTS[1], "run_id": RUN_ID,
            "evidence_origin": "synthetic", "qualification_scope": "simulated",
            "stage": "validate", "manifest_digest": "sha256:" + "1" * 64,
            "attestation_receipt_id": "sha256:" + "2" * 64,
            "documents": {"admission.json": {"evidence_origin": "synthetic", "qualification_scope": "simulated"}},
        }
        build_outcome("ok", BM_OK, "view", data)
        for documents, code in (
            ({}, BM_SCHEMA_INVALID),
            ({"admission.json": {"evidence_origin": "real", "qualification_scope": "official"}}, BM_SCOPE_MISMATCH),
        ):
            with self.subTest(documents=documents):
                with self.assertRaises(BenchError) as caught:
                    build_outcome("ok", BM_OK, "invalid view", {**data, "documents": documents})
                self.assertEqual(caught.exception.code, code)


class SyntheticOperatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.source_temporary.cleanup)
        cls.source_root = materialize_source_tree(Path(cls.source_temporary.name) / "source")
        # Cross-engine reference validation reads the frozen adapter source and
        # protocol pins, not built executables. These copies are data only.
        for name in ("adapters", "spec"):
            destination = cls.source_root / "benchmarks" / "pr15d" / name
            shutil.copytree(REPO_ROOT / "benchmarks" / "pr15d" / name, destination)
        cls.source_digest = compute_source_set_digest(cls.source_root)

    def workspace(self, experiment: str) -> tuple[Path, Path, dict]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        scenario = root / "scenario"
        scenario.mkdir()
        shutil.copyfile(CATALOG / experiment / "synthetic-scenario.v1.json", scenario / "synthetic-scenario.v1.json")
        profile_digest = content_digest(load_document(default_profile_path()))
        _qa_root, digests = qa_workspace(root / "qa", source_set_digest=self.source_digest, profile=profile_digest)
        document = {
            "kind": operator.SYNTHETIC_CONFIG_KIND,
            "schema_version": 1,
            "evidence_origin": "synthetic",
            "qualification_scope": "simulated",
            "experiment_id": experiment,
            "run_id": str(uuid.uuid4()),
            "source_root": str(self.source_root),
            "catalog_root": str(CATALOG),
            "scenario_root": str(scenario),
            "output_root": str(root / "operation"),
            "qualification_profile_path": str(default_profile_path()),
            "qa_evidence_root": str(root / "qa"),
            "expected_profile_digest": profile_digest,
            "expected_framework_qa_digest": digests["framework_qa_digest"],
            "expected_source_qa_digest": digests["source_qa_digest"],
            "expected_source_set_digest": self.source_digest,
        }
        config = root / "config.json"
        write_json(config, document)
        return root, config, document

    def test_both_synthetic_families_run_and_replay_all_stages_without_writes(self) -> None:
        for experiment in operator.SYNTHETIC_EXPERIMENTS:
            with self.subTest(experiment=experiment):
                root, config, document = self.workspace(experiment)
                arguments = [
                    "run", "--experiment", experiment,
                    "--protocol", str(CATALOG / experiment / "protocol.yaml"),
                    "--out", document["output_root"], "--config", str(config),
                ]
                code, stdout, stderr = invoke_cli(arguments)
                self.assertEqual((code, stderr), (0, ""), stderr)
                result = json.loads(stdout)["data"]
                self.assertEqual(result["disposition"], "SIMULATED_QUALIFIED")
                self.assertEqual((result["evidence_origin"], result["qualification_scope"]), ("synthetic", "simulated"))
                events = [json.loads(path.read_bytes()) for path in sorted((root / "operation" / "journal").glob("*.json"))]
                self.assertEqual([(event["stage"], event["event"]) for event in events], [
                    (stage, event) for stage in ("prepare", "acquisition", "qualification") for event in ("started", "completed")
                ])
                before = snapshot(root)
                for verb in operator.STAGE_VERBS:
                    stage_code, stage_out, stage_error = invoke_cli([verb, "--run", document["run_id"], "--config", str(config)])
                    self.assertEqual((stage_code, stage_error), (0, ""), stage_error)
                    data = json.loads(stage_out)["data"]
                    self.assertEqual(data["stage"], verb)
                    self.assertEqual(data["manifest_digest"], result["manifest_digest"])
                    self.assertEqual(data["qualification_scope"], "simulated")
                    self.assertNotEqual(data["qualification_scope"], "official")
                self.assertEqual(snapshot(root), before)
                repeat_code, repeat_out, repeat_error = invoke_cli(arguments)
                self.assertEqual((repeat_code, repeat_out), (73, ""))
                self.assertEqual(json.loads(repeat_error)["code"], BM_PUBLICATION_CONFLICT)
                self.assertEqual(snapshot(root), before)

    def test_missing_qa_anchor_is_rejected_before_output_creation(self) -> None:
        _root, config, document = self.workspace(operator.SYNTHETIC_EXPERIMENTS[1])
        document["expected_framework_qa_digest"] = "sha256:" + "0" * 64
        write_json(config, document)
        with self.assertRaises(BenchError) as caught:
            operator.dispatch_run(document["experiment_id"], CATALOG / document["experiment_id"] / "protocol.yaml", Path(document["output_root"]), config)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertFalse(Path(document["output_root"]).exists())

    def test_synthetic_config_is_closed_scoped_and_absolute(self) -> None:
        _root, config, original = self.workspace(operator.SYNTHETIC_EXPERIMENTS[1])
        mutations = (
            ({"authorization_pass": True}, BM_SCHEMA_INVALID),
            ({"evidence_origin": "real", "qualification_scope": "official"}, BM_SCOPE_MISMATCH),
            ({"source_root": "relative/source"}, BM_UNSAFE_INPUT),
            ({"output_root": "/tmp/../escape"}, BM_UNSAFE_INPUT),
        )
        for update, expected in mutations:
            with self.subTest(update=update):
                write_json(config, {**original, **update})
                with self.assertRaises(BenchError) as caught:
                    read_synthetic_operation(config)
                self.assertEqual(caught.exception.code, expected)
                self.assertFalse(Path(original["output_root"]).exists())

    def test_protocol_and_output_mismatches_refuse_before_output(self) -> None:
        root, config, document = self.workspace(operator.SYNTHETIC_EXPERIMENTS[1])
        expected_protocol = CATALOG / document["experiment_id"] / "protocol.yaml"
        for protocol, output in ((root / "unrelated.json", Path(document["output_root"])), (expected_protocol, root / "wrong")):
            with self.subTest(protocol=protocol.name, output=output.name):
                with self.assertRaises(BenchError) as caught:
                    operator.dispatch_run(document["experiment_id"], protocol, output, config)
                self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
                self.assertFalse(Path(document["output_root"]).exists())

    def test_replay_refuses_configuration_relabel_and_evidence_tamper(self) -> None:
        root, config, document = self.workspace(operator.SYNTHETIC_EXPERIMENTS[1])
        operator.dispatch_run(document["experiment_id"], CATALOG / document["experiment_id"] / "protocol.yaml", Path(document["output_root"]), config)
        with self.assertRaises(BenchError) as caught:
            operator.dispatch_stage("report", str(uuid.uuid4()), config)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        identity = root / "operation" / "operation.json"
        original = identity.read_bytes()
        changed = json.loads(original)
        changed["qualification_scope"] = "official"
        write_json(identity, changed)
        with self.assertRaises(BenchError) as caught:
            operator.dispatch_stage("report", document["run_id"], config)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        identity.write_bytes(original)
        policy = root / "operation" / "qualified" / document["experiment_id"] / document["run_id"] / "policy.json"
        policy.write_bytes(policy.read_bytes() + b" ")
        with self.assertRaises(BenchError):
            operator.dispatch_stage("report", document["run_id"], config)


if __name__ == "__main__":
    unittest.main()
