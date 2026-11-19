"""Untimed operator integration and fail-closed persistence tests.

No case calls a benchmark adapter, sleeps for readiness, starts a service, or
builds a measurement binary. The external acquisition boundary is substituted;
the shared lifecycle and actual filesystem journal are exercised directly.
"""

from __future__ import annotations

from contextlib import ExitStack
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.errors import BM_EVIDENCE_UNAVAILABLE, BM_IDENTITY_INVALID, BM_PUBLICATION_CONFLICT, BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.host.capabilities import LinuxCapabilityProvider
from quervant_bench.official import workflow, admission
from quervant_bench.official.protocols import OBSERVED_IDENTITY_FIELDS
from quervant_bench.tests import official_support as support
from quervant_bench.official.operation_config import CONFIG_KIND, OperationConfig, load_operation_config
from quervant_bench.official.operation_store import EventJournal, create_directory, write_record
from quervant_bench.official.protocols import STUDY_CROSS_ENGINE, STUDY_RETAINED_KEY, OBSERVED_IDENTITY_FIELDS

RUN = "5fb9bd75-4cd6-4a58-9580-a4199ff8bb77"
DIGEST = "sha256:" + "a" * 64


class OfficialOperationConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "source").mkdir()
        self.document = {
            "kind": CONFIG_KIND, "schema_version": 1,
            "source_root": str(self.root / "source"), "workspace": str(self.root / "runs"),
            "output_base": str(self.root / "qualified"), "authorization_path": str(self.root / "authorization.json"),
            "approval_source_root": str(self.root / "approvals"), "approval_source_identity": "external-review",
            "prepared_manifest": str(self.root / "prepared.json"), "corpus_dir": str(self.root / "corpus"),
            "framework_qa": str(self.root / "framework.json"), "source_qa": str(self.root / "source.json"),
            "qa_evidence_root": str(self.root / "qa"), "adapter_cpu": 0, "controller_cpu": 1,
            "policy_inputs": None, "historical_parity": None,
        }

    def load(self):
        path = self.root / "operation.json"
        path.write_bytes(canonical_document_bytes(self.document))
        return load_operation_config(path)

    def test_configuration_cannot_supply_observations_or_pass_flags(self) -> None:
        for field in ("observed", "fixture_only", "skip_control", "retry", "command", "allow_contended"):
            with self.subTest(field=field):
                self.document[field] = True
                with self.assertRaises(BenchError):
                    self.load()
                del self.document[field]

    def test_configuration_resolves_only_locations_and_cpu_pair(self) -> None:
        config = self.load()
        self.assertEqual(config.path("source_root"), self.root / "source")
        self.assertEqual((config.adapter_cpu, config.controller_cpu), (0, 1))
        self.assertFalse((self.root / "runs").exists())

    def test_configuration_rejects_boolean_cpu_and_shared_cpu(self) -> None:
        for cpu in (True, -1, 1):
            with self.subTest(cpu=cpu):
                self.document["adapter_cpu"] = cpu
                with self.assertRaises(BenchError):
                    self.load()

    def test_configuration_rejects_symlinked_parent(self) -> None:
        (self.root / "link").symlink_to(self.root / "source", target_is_directory=True)
        self.document["workspace"] = str(self.root / "link" / "runs")
        with self.assertRaises(BenchError) as raised:
            self.load()
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_configuration_rejects_qualification_inside_raw_root(self) -> None:
        self.document["output_base"] = str(self.root / "runs" / "qualified")
        with self.assertRaises(BenchError) as raised:
            self.load()
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)


class OfficialOperationStoreTests(unittest.TestCase):
    def test_raw_inventory_excludes_builds_and_indexes_at_every_level(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("build/large-binary", "indexes/segment", "trial/build/cache", "trial/raw.json", "run.json"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"data")
            self.assertEqual(admission.walk_raw_members(root, exclude_any_dir=("build", "indexes")), ["run.json", "trial/raw.json"])
            (root / "trial" / "bad").symlink_to(root / "run.json")
            with self.assertRaises(BenchError) as raised:
                admission.walk_raw_members(root, exclude_any_dir=("build", "indexes"))
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_derived_bytes_can_only_be_reused_when_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(write_record(root, "analysis.json", {"value": 1}), "CREATED")
            self.assertEqual(write_record(root, "analysis.json", {"value": 1}, reuse=True), "REUSED_VERIFIED")
            before = (root / "analysis.json").read_bytes()
            for value in (2, 1.0):
                with self.subTest(value=value), self.assertRaises(BenchError) as raised:
                    write_record(root, "analysis.json", {"value": value}, reuse=True)
                self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
            self.assertEqual((root / "analysis.json").read_bytes(), before)

    def test_journal_never_replaces_previous_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal = EventJournal(root)
            journal({"event": "started"})
            journal({"event": "failed"})
            with self.assertRaises(BenchError):
                EventJournal(root)({"event": "completed"})
            self.assertEqual(json.loads((root / "event-0002.json").read_text()), {"event": "failed"})

    def test_exclusive_run_directory_preserves_prior_partial_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            create_directory(root, exclusive=True)
            (root / "partial").write_text("preserve me")
            with self.assertRaises(BenchError) as raised:
                create_directory(root, exclusive=True)
            self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
            self.assertEqual((root / "partial").read_text(), "preserve me")

    def test_linux_default_provider_permits_readiness_counter_source(self) -> None:
        with patch("builtins.open", unittest.mock.mock_open(read_data="cpu0 1 2 3 4 5 6 7 8\n")) as opened:
            self.assertEqual(LinuxCapabilityProvider().read_text("/proc/stat"), "cpu0 1 2 3 4 5 6 7 8\n")
            opened.assert_called_once_with("/proc/stat", "r", encoding="utf-8")
        self.assertIsNone(LinuxCapabilityProvider().read_text("/proc/self/environ"))


class OfficialPreparationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.source / "target" / "prepared"
        self.corpus = self.source / "target" / "corpus"
        self.template = {"study_id": STUDY_CROSS_ENGINE}
        self.config = OperationConfig({
            "source_root": str(self.source), "workspace": str(self.root / "runs"),
            "output_base": str(self.root / "qualified"), "corpus_dir": str(self.corpus),
            "prepared_manifest": str(self.output / "prepared-cross-engine.json"),
            "framework_qa": str(self.root / "framework.json"),
            "source_qa": str(self.root / "source.json"), "qa_evidence_root": str(self.root / "qa"),
        })
        self.prepared = SimpleNamespace(binary_digest=DIGEST, corpus_dir=self.corpus)
        self.observed = {field: DIGEST for field in OBSERVED_IDENTITY_FIELDS}
        self.observed.update(source_commit="a" * 40, output_root_identity=str(self.root / "qualified"))
        for location, value in (
            ("quervant_bench.official.workflow.load_operation_config", self.config),
            ("quervant_bench.official.workflow._template", self.template),
            ("quervant_bench.evidence.provenance.repository_root", self.source),
            ("quervant_bench.official.workflow.git_identity", ("a" * 40, DIGEST)),
            ("quervant_bench.official.workflow.observe_host", {}),
            ("quervant_bench.official.workflow.observe_identities", self.observed),
        ):
            active = patch(location, return_value=value)
            active.start()
            self.addCleanup(active.stop)
        build = patch("quervant_bench.official.cross_engine_backend.prepare_cross_engine", side_effect=self.build)
        self.builder = build.start()
        self.addCleanup(build.stop)
        reopen = patch.object(workflow, "_prepared", return_value=self.prepared)
        self.reopen = reopen.start()
        self.addCleanup(reopen.stop)

    def build(self, **_kwargs):
        create_directory(self.output, exclusive=True)
        write_record(self.output, "prepared-cross-engine.json", {"kind": "test-prepared"})
        return self.prepared

    def qa(self) -> None:
        from quervant_bench.tests.official_support import qa_evidence
        from quervant_bench.official.qa_evidence import check_record_relative
        for gate, field, pin in (("framework-qa", "framework_qa", "qa_framework_digest"),
                                 ("source-qa", "source_qa", "qa_source_digest")):
            summary = qa_evidence(gate, SimpleNamespace(source_file_set_digest=DIGEST))
            for check in summary["checks"]:
                # Source-identity fixtures for the preauthorization reader;
                # these deliberately do not assert executed/log QA acceptance.
                record = {"qa_gate": gate, "check_id": check["check_id"],
                    "source_commit": "a" * 40, "source_set_digest": DIGEST}
                path = self.config.path("qa_evidence_root") / check_record_relative(gate, check["check_id"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(canonical_document_bytes(record))
                check["evidence_digest"] = content_digest(record)
            self.config.path(field).write_bytes(canonical_document_bytes(summary))
            self.observed[pin] = content_digest(summary)

    def prepare(self):
        return workflow.prepare_official(STUDY_CROSS_ENGINE, Path("protocol.json"), self.output, Path("config.json"))

    def test_missing_qa_preserves_build_then_finalizes_same_preparation_without_rebuilding(self) -> None:
        with self.assertRaises(BenchError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
        self.assertEqual(raised.exception.field_path, "qa_evidence")
        self.builder.assert_called_once()
        self.reopen.assert_not_called()
        self.assertTrue(self.config.path("prepared_manifest").is_file())
        self.assertTrue((self.output / "preparation-inputs.json").is_file())
        self.assertFalse((self.output / "authorization-inputs.json").exists())
        prepared_bytes = self.config.path("prepared_manifest").read_bytes()
        self.qa()
        result = self.prepare()
        again = self.prepare()
        self.assertEqual(result, again)
        self.assertEqual(result["data"]["status"], "AWAITING_INDEPENDENT_G0_REVIEW")
        self.assertFalse(result["data"]["measurement_executed"])
        self.builder.assert_called_once()
        self.assertEqual(self.reopen.call_count, 2)
        self.assertEqual(self.config.path("prepared_manifest").read_bytes(), prepared_bytes)

    def test_incomplete_existing_preparation_is_never_rebuilt(self) -> None:
        create_directory(self.output)
        (self.output / "partial.log").write_text("preserved")
        with self.assertRaises(BenchError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
        self.builder.assert_not_called()
        self.reopen.assert_not_called()
        self.assertEqual((self.output / "partial.log").read_text(), "preserved")

    def test_stale_executed_qa_source_cannot_finalize_authorization_inputs(self) -> None:
        self.qa()
        path = self.config.path("qa_evidence_root") / "framework-qa" / "benchmark-scripts.json"
        record = json.loads(path.read_text())
        record["source_commit"] = "b" * 40
        path.write_bytes(canonical_document_bytes(record))
        # Rehash the tampered record into its summary so only the independently
        # observed source comparison, not a stale checksum, rejects this case.
        summary_path = self.config.path("framework_qa")
        summary = json.loads(summary_path.read_text())
        summary["checks"][0]["evidence_digest"] = content_digest(record)
        summary_path.write_bytes(canonical_document_bytes(summary))
        self.observed["qa_framework_digest"] = content_digest(summary)
        with self.assertRaises(BenchError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
        self.assertEqual(raised.exception.__cause__.code, BM_IDENTITY_INVALID)
        self.assertTrue(self.config.path("prepared_manifest").is_file())
        self.assertFalse((self.output / "authorization-inputs.json").exists())

    def test_changed_preparation_source_is_not_relabelled_on_finalization(self) -> None:
        with self.assertRaises(BenchError):
            self.prepare()
        self.qa()
        with patch.object(workflow, "git_identity", return_value=("b" * 40, DIGEST)), self.assertRaises(BenchError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "preparation")
        self.builder.assert_called_once()
        self.assertFalse((self.output / "authorization-inputs.json").exists())


class FirstRunQaOpenTests(unittest.TestCase):
    """C-F01/C-F02: the real opener needs source QA, not a pending run's A/A."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "exec"
        self.root.mkdir()
        self.external = Path(tempfile.mkdtemp(dir=self.temporary.name)) / "external"
        self.bundle = support.qa_evidence_sandbox(self.root / "qa")
        self.run_id = self.bundle.freeze.run_id
        self.summaries = {
            "framework": self.root / "qa-summaries" / "framework.json",
            "source": self.root / "qa-summaries" / "source.json",
        }
        self.summaries["framework"].parent.mkdir(parents=True, exist_ok=True)
        self.summaries["framework"].write_bytes(
            canonical_document_bytes(self.bundle.framework_summary)
        )
        self.summaries["source"].write_bytes(
            canonical_document_bytes(self.bundle.source_summary)
        )
        self.approvals = self.external / "approvals"
        self.approvals.mkdir(parents=True)
        (self.root / "source").mkdir()
        self.config = OperationConfig(
            {
                "source_root": str(self.root / "source"),
                "workspace": str(self.external / "runs"),
                "output_base": str(self.external / "qualified"),
                "authorization_path": str(self.root / "authorization.json"),
                "approval_source_root": str(self.approvals),
                "approval_source_identity": "external-review",
                "prepared_manifest": str(self.root / "prepared.json"),
                "corpus_dir": str(self.root / "corpus"),
                "framework_qa": str(self.summaries["framework"]),
                "source_qa": str(self.summaries["source"]),
                "qa_evidence_root": str(self.bundle.root),
                "adapter_cpu": 0,
                "controller_cpu": 1,
                "policy_inputs": None,
                "historical_parity": None,
            }
        )
        self.template = {"study_id": STUDY_CROSS_ENGINE}

    def _publish(self, document: dict, *, approval_digest: str | None = None) -> None:
        (self.root / "authorization.json").write_bytes(canonical_document_bytes(document))
        record = {
            "kind": "official-g0-approval-record",
            "schema_version": 1,
            "study_id": document["study_id"],
            "approved_authorization_digest": approval_digest
            or content_digest(document),
            "independent_review_id": "external-review",
            "approved_at_utc": "2026-11-18T00:00:00Z",
        }
        (self.approvals / "external-review.approval.json").write_bytes(
            canonical_document_bytes(record)
        )

    def _observed(self, document: dict) -> dict:
        observations = {
            name: document[name] for name in OBSERVED_IDENTITY_FIELDS
        }
        observations["output_root_identity"] = document["approved_output_root_identity"]
        return observations

    def _open(self):
        document = support.authorization_document(self.bundle.freeze)
        observed = self._observed(document)
        prepared = SimpleNamespace(corpus_dir=self.config.path("corpus_dir"), binary_digest=DIGEST)
        with patch.object(workflow, "_prepared", return_value=prepared), patch.object(
            workflow, "observe_identities", return_value=observed
        ):
            return workflow._open(
                self.config, self.template, self.config.path("workspace") / self.run_id
            )

    def test_c_t05_source_qa_opens_before_any_control_measurement(self) -> None:
        document = support.authorization_document(self.bundle.freeze)
        self._publish(document)
        run_directory = self.config.path("workspace") / self.run_id
        self.assertFalse(run_directory.exists())
        operation = self._open()
        self.assertEqual(operation.authorization.study_id, STUDY_CROSS_ENGINE)
        # No control artifact is requested or created by opening, and the absent
        # run directory is still absent: QA no longer depends on measured A/A.
        self.assertFalse(run_directory.exists())
        self.assertFalse((run_directory / "raw").exists())

    def test_c_t05b_absent_approval_still_refuses(self) -> None:
        document = support.authorization_document(self.bundle.freeze)
        (self.root / "authorization.json").write_bytes(canonical_document_bytes(document))
        with self.assertRaises(BenchError) as raised:
            self._open()
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def test_c_t09_invalid_campaign_order_is_rejected_before_any_effect(self) -> None:
        for study_id, order in (
            (STUDY_CROSS_ENGINE, ["treatment", "control"]),
            (STUDY_RETAINED_KEY, ["control", "treatment"]),
        ):
            with self.subTest(study=study_id):
                freeze = support.make_freeze(
                    study_id=study_id,
                    run_id=self.run_id,
                    qa_framework_digest=content_digest(
                        self.bundle.framework_summary
                    ),
                    qa_source_digest=content_digest(self.bundle.source_summary),
                    source_file_set_digest=self.bundle.freeze.source_file_set_digest,
                )
                document = support.authorization_document(freeze)
                document["permitted_campaign_order"] = list(order)
                self.template = {"study_id": study_id}
                self._publish(document, approval_digest=content_digest(document))
                run_directory = self.config.path("workspace") / self.run_id
                prepared = SimpleNamespace(
                    corpus_dir=self.config.path("corpus_dir"), binary_digest=DIGEST
                )
                with patch.object(workflow, "_readiness") as readiness, patch.object(
                    workflow, "load_operation_config", return_value=self.config
                ), patch.object(workflow, "_template", return_value=self.template), patch.object(
                    workflow, "_prepared", return_value=prepared
                ), patch.object(
                    workflow, "observe_identities", return_value=self._observed(document)
                ), patch(
                    "quervant_bench.official.cross_engine_backend.acquire_cross_engine_control"
                ) as control, patch(
                    "quervant_bench.official.cross_engine_backend.acquire_cross_engine_treatment"
                ) as treatment:
                    with self.assertRaises(BenchError) as raised:
                        workflow.run_official(
                            study_id,
                            Path("protocol.json"),
                            run_directory,
                            Path("config.json"),
                        )
                self.assertEqual(
                    raised.exception.code, BM_IDENTITY_INVALID, str(raised.exception)
                )
                self.assertEqual(
                    raised.exception.field_path,
                    "permitted_campaign_order",
                    str(raised.exception),
                )
                readiness.assert_not_called()
                control.assert_not_called()
                treatment.assert_not_called()
                self.assertFalse(run_directory.exists())
                self.assertFalse((run_directory / "operation.json").exists())


class OfficialAcquisitionWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = OperationConfig({
            "source_root": str(self.root), "workspace": str(self.root / "runs"),
            "output_base": str(self.root / "qualified"), "adapter_cpu": 0, "controller_cpu": 1,
        })
        self.output = self.root / "runs" / RUN
        self.template = {"study_id": STUDY_CROSS_ENGINE}
        capability = SimpleNamespace(study_id=STUDY_CROSS_ENGINE, run_id=RUN,
            freeze=SimpleNamespace(authorization_digest=DIGEST))
        self.operation = workflow.Operation(self.config, self.template, capability, object(), {}, self.output)
        for name, value in (("load_operation_config", self.config), ("_template", self.template), ("_open", self.operation)):
            active = patch.object(workflow, name, return_value=value)
            active.start()
            self.addCleanup(active.stop)

    def test_failed_readiness_stops_before_control_and_preserves_attempt(self) -> None:
        error = BenchError(BM_EVIDENCE_UNAVAILABLE, "host busy")
        with patch.object(workflow, "_readiness", side_effect=error), patch.object(workflow, "_admit") as admit:
            with self.assertRaises(BenchError) as raised:
                workflow.run_official(STUDY_CROSS_ENGINE, Path("protocol.json"), self.output, Path("config.json"))
            self.assertIs(raised.exception, error)
            admit.assert_not_called()
        self.assertTrue((self.output / "stopped.json").is_file())
        self.assertFalse((self.output / "sealed.json").exists())
        events = [json.loads(path.read_text()) for path in sorted((self.output / "events").glob("*.json"))]
        self.assertEqual(events[-1]["stage"], "readiness")
        self.assertEqual(events[-1]["event"], "failed")
        self.assertFalse(any(event["stage"] == "treatment" for event in events))

    def test_reused_output_is_rejected_before_readiness(self) -> None:
        create_directory(self.output)
        (self.output / "partial").write_text("original")
        with patch.object(workflow, "_readiness") as readiness, self.assertRaises(BenchError) as raised:
            workflow.run_official(STUDY_CROSS_ENGINE, Path("protocol.json"), self.output, Path("config.json"))
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
        readiness.assert_not_called()
        self.assertEqual((self.output / "partial").read_text(), "original")

    def test_missing_external_approval_creates_no_run_directory(self) -> None:
        error = BenchError(BM_EVIDENCE_UNAVAILABLE, "approval missing")
        with patch.object(workflow, "_open", side_effect=error), patch.object(workflow, "_readiness") as readiness:
            with self.assertRaises(BenchError) as raised:
                workflow.run_official(STUDY_CROSS_ENGINE, Path("protocol.json"), self.output, Path("config.json"))
            self.assertIs(raised.exception, error)
            readiness.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_complete_series_has_one_control_before_treatment_and_seals_only_after_admission(self) -> None:
        calls = []
        admitted = SimpleNamespace(record=SimpleNamespace(admission_index={"kind": "fixture-index"}, raw_series_root_digest=DIGEST))
        with ExitStack() as stack:
            stack.enter_context(patch.object(workflow, "_readiness", side_effect=lambda _op: calls.append("readiness")))
            for function, stage in (("acquire_cross_engine_control", "control"), ("verify_cross_engine_control", "control-verify"), ("acquire_cross_engine_treatment", "treatment")):
                stack.enter_context(patch("quervant_bench.official.cross_engine_backend." + function,
                    side_effect=lambda *args, _stage=stage, **kwargs: calls.append(_stage)))
            stack.enter_context(patch.object(workflow, "_admit", side_effect=lambda _op: (calls.append("admission"), admitted)[1]))
            result = workflow.run_official(STUDY_CROSS_ENGINE, Path("protocol.json"), self.output, Path("config.json"))
        self.assertEqual(calls, ["readiness", "control", "control-verify", "treatment", "admission"])
        self.assertEqual(result["data"]["status"], "REAL_EVIDENCE_SEALED")
        self.assertFalse(result["data"]["accepted"])
        self.assertEqual(json.loads((self.output / "sealed.json").read_text())["raw_series_root_digest"], DIGEST)
        self.assertFalse((self.output / "stopped.json").exists())

    def test_control_failure_prevents_treatment_and_raw_seal(self) -> None:
        error = BenchError(BM_IDENTITY_INVALID, "control rejected")
        with patch.object(workflow, "_readiness"), \
             patch("quervant_bench.official.cross_engine_backend.acquire_cross_engine_control", side_effect=error), \
             patch("quervant_bench.official.cross_engine_backend.acquire_cross_engine_treatment") as treatment:
            with self.assertRaises(BenchError) as raised:
                workflow.run_official(STUDY_CROSS_ENGINE, Path("protocol.json"), self.output, Path("config.json"))
        self.assertIs(raised.exception, error)
        treatment.assert_not_called()
        self.assertTrue((self.output / "stopped.json").exists())
        self.assertFalse((self.output / "sealed.json").exists())

    def test_missing_retained_policy_inputs_preserve_sealed_run_for_later_analysis(self) -> None:
        self.template["study_id"] = STUDY_RETAINED_KEY
        self.operation.authorization.study_id = STUDY_RETAINED_KEY
        self.config.document["policy_inputs"] = None
        create_directory(self.output)
        write_record(self.output, "operation.json", workflow._operation_record(self.operation))
        write_record(self.output, "sealed.json", {"raw_series_root_digest": DIGEST})
        admitted = SimpleNamespace(record=SimpleNamespace(
            admission_index={"kind": "fixture-index"}, raw_series_root_digest=DIGEST))
        seal_before = (self.output / "sealed.json").read_bytes()
        with patch.object(workflow, "_admit", return_value=admitted), \
             patch.object(workflow.analysis, "analyze_official_study") as analyze:
            # Validation does not need policy inputs and never freezes a partial
            # policy. Every downstream stage must stop before creating one.
            result = workflow.dispatch_official_stage("validate", RUN, Path("config.json"))
            self.assertEqual(result["data"]["status"], "ADMITTED_REAL")
            for verb in ("analyze", "verify", "accept", "report"):
                with self.subTest(verb=verb), self.assertRaises(BenchError) as raised:
                    workflow.dispatch_official_stage(verb, RUN, Path("config.json"))
                self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
                self.assertEqual(raised.exception.field_path, "policy_inputs")
                self.assertFalse((self.output / "analysis.json").exists())
                self.assertFalse((self.output / "policy.json").exists())
                self.assertFalse((self.output / "stopped.json").exists())
            analyze.assert_not_called()
            self.assertEqual((self.output / "sealed.json").read_bytes(), seal_before)
            # This test substitutes only the external authenticated input reader
            # and policy engine. The same run, immutable store and stage wiring
            # remain real and must progress without reacquiring any raw data.
            self.config.document["policy_inputs"] = {"available": True}
            policy_capability = object()
            analyze.return_value = ({"kind": "test-analysis"}, {"decision_status": "PER_K_POLICY_RESOLVED"})
            with patch.object(workflow, "_policy_inputs", return_value=policy_capability):
                result = workflow.dispatch_official_stage("analyze", RUN, Path("config.json"))
                replay = workflow.dispatch_official_stage("analyze", RUN, Path("config.json"))
            self.assertEqual(result, replay)
            self.assertEqual(result["data"]["status"], "ANALYZED_REAL")
            self.assertIs(analyze.call_args.kwargs["policy_inputs"], policy_capability)
            self.assertTrue((self.output / "analysis.json").is_file())
            self.assertTrue((self.output / "policy.json").is_file())
            self.assertEqual((self.output / "sealed.json").read_bytes(), seal_before)


if __name__ == "__main__":
    unittest.main()
