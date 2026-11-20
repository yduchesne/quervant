"""V2 lifecycle wiring without builds, services or timed measurements.

These tests substitute external preparation/acquisition boundaries and inspect
the real workflow/store ordering. They do not claim mock capabilities as real
qualification evidence; separate production-boundary tests cover that chain.
"""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import shutil
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.errors import BM_EVIDENCE_UNAVAILABLE, BM_IDENTITY_INVALID, BenchError
from quervant_bench.official import acquisition, protocols, workflow, transport
from quervant_bench.official.operation_config import OperationConfig
from quervant_bench.official.operation_store import create_directory, write_record
from quervant_bench.tests import official_support as support

RUN = "5fb9bd75-4cd6-4a58-9580-a4199ff8bb77"
BASELINE = "a9bcd6e3-0945-424c-9856-8d801df49e62"
DIGEST = "sha256:" + "a" * 64


class LiveDisclosureFactoryTests(unittest.TestCase):
    """D01-D08 use real capability factories over explicitly generated test data.

    Only external Git/host/prepared/runtime observations are substituted. G0's
    file reader, QA member reader, raw admission, original verifiers, independent
    Gate C, history catalog and disclosure reconstruction all execute normally.
    Nothing here is a measured benchmark or an authentic operator approval.
    """

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="test-live-baseline-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.case = cls._build_case("cross")

    @classmethod
    def _build_case(cls, family):
        from quervant_bench.official import admission, analysis, history, verification
        from quervant_bench.official.retained_backend import PreparedRetainedKey
        from quervant_bench.tests.test_official_admission import CurrentBaselineProductionAdmissionTests as production

        run = "11111111-1111-4111-8111-111111111111" if family == "cross" else "22222222-2222-4222-8222-222222222222"
        external = cls.root / family
        external.mkdir()
        if family == "retained":
            namespace = support.REPO_ROOT / "target/pr15i-d3-c"
            namespace.mkdir(parents=True, exist_ok=True)
            owned = tempfile.TemporaryDirectory(prefix="test-live-baseline-", dir=namespace)
            cls.addClassCleanup(owned.cleanup)
            directory = Path(owned.name) / run
            fixture = support.make_retained_key_fixture(directory, run_id=run)
            production._complete_retained_fixture(fixture)
            external_qa = external / "qa-evidence"
            shutil.move(str(fixture.qa_evidence_root), external_qa)
            fixture = replace(fixture, qa_evidence_root=external_qa)
            corpus = external / "corpus"
            corpus.mkdir()
        else:
            directory = external / "runs" / run
            fixture = support.make_cross_engine_fixture(directory, run_id=run)
            corpus = fixture.corpus_root
        template = protocols.read_canonical_json(protocols.template_path(fixture.freeze.study_id, version=2))
        if family == "cross":
            control = cls._complete_cross_control(fixture, template)
            fixture = replace(fixture, control=control)
        output = external / "qualified"
        output.mkdir()
        host = {"kind": "official-host-preflight", "schema_version": 1,
                "capabilities": {"environment": "wsl2"}, "adapter_cpu": 0, "controller_cpu": 1}
        runtime_path = external / "runtime.json"
        runtime_bytes = canonical_document_bytes({"kind": "test-only-external-runtime", "family": family})
        runtime_path.write_bytes(runtime_bytes)
        runtime_digest = "sha256:" + hashlib.sha256(runtime_bytes).hexdigest()
        freeze = replace(fixture.freeze, profile_version=2, design_digest=content_digest(template),
            acceptance_profile="current-baseline-v2", baseline_id=BASELINE,
            preservation_root_identity=str(cls.root / "benchmark-results/baselines" / BASELINE),
            runtime_freeze_digest=runtime_digest if family == "retained" else None,
            host_preflight_digest=content_digest(host), approved_output_root_identity=str(output),
            policy_digest=analysis.policy_profile_digest(template["study_id"], template["policy"]["policy_chain"]))
        authorization, observed = production._authorize(freeze, external / "g0")
        prepared_path = external / "prepared.json"
        prepared_bytes = canonical_document_bytes({"kind": "test-only-external-prepared", "family": family})
        prepared_path.write_bytes(prepared_bytes)
        if family == "retained":
            manifest = support.read_json(fixture.raw_root / protocols.D3C_CAMPAIGN_NAMES[0] / "manifest.json")
            binaries = {label: {"sha256": manifest["arms"][arm]["binary_sha256"],
                                "bytes": manifest["arms"][arm]["binary_bytes"],
                                "source_sha": manifest["arms"][arm]["source_sha"]}
                        for label, arm in (("A", "A"), ("B", "L"))}
            prepared = PreparedRetainedKey(prepared_path, support.REPO_ROOT, corpus,
                                          {"binaries": binaries}, freeze.binary_manifest_digest)
        else:
            prepared = SimpleNamespace(manifest_path=prepared_path, corpus_dir=corpus,
                                       binary_digest=freeze.binary_manifest_digest)
        for name, document in (("framework-qa.json", fixture.framework_qa), ("source-qa.json", fixture.source_qa),
                               ("host-preflight.json", host)):
            support.write_json(directory / name, document)
        history_root = external / "history"
        history_root.mkdir()
        candidates = []
        if family == "cross":
            aggregate = history_root / "pr15d-qualified.json"
            shutil.copyfile(support.REPO_ROOT / "benchmarks/reports/pr15d/pr15d-qualified.json", aggregate)
            candidates.append({"family": "cross-engine", "input_role": "pr15d-aggregate", "path": aggregate.name,
                "source_identity": history.PR15D_AGGREGATE_RUN,
                "expected_digest": "sha256:c9e8ed722aefc4fef43837a5511c2c88575287497b449f68f82f7ea0c251b257"})
        inventory = history_root / "inventory.json"
        support.write_json(inventory, {"kind": "official-baseline-history-inputs", "schema_version": 1, "candidates": candidates})
        config = {"kind": "official-operation-config", "schema_version": 2,
            "source_root": str(support.REPO_ROOT), "workspace": str(directory.parent), "output_base": str(output),
            "authorization_path": str(authorization.authorization_path), "approval_source_root": str(authorization._approval_source_root),
            "approval_source_identity": authorization.approval_source_identity,
            "prepared_manifest": str(prepared_path), "corpus_dir": str(corpus),
            "framework_qa": str(directory / "framework-qa.json"), "source_qa": str(directory / "source-qa.json"),
            "qa_evidence_root": str(fixture.qa_evidence_root), "adapter_cpu": 0, "controller_cpu": 1,
            "policy_inputs": None, "acceptance_profile": "current-baseline-v2",
            "baseline": {"baseline_id": BASELINE, "evidence_root": freeze.preservation_root_identity,
                         "history_inventory": str(inventory), "runtime_freeze_path": str(runtime_path) if family == "retained" else None}}
        config_path = external / "operation-config.json"
        support.write_json(config_path, config)
        case = SimpleNamespace(family=family, external=external, directory=directory, fixture=fixture, template=template,
            authorization=authorization, observed=observed, prepared=prepared, prepared_path=prepared_path,
            prepared_bytes=prepared_bytes, runtime_path=runtime_path, runtime_bytes=runtime_bytes,
            runtime_digest=runtime_digest, host=host, config=config, config_path=config_path, output=output, inventory=inventory)
        with cls._environment(case):
            operation = workflow._open(OperationConfig(config), template, directory)
            admitted = workflow._admit(operation)
            derived, policy = analysis.analyze_official_study(admitted=admitted.record, template=template)
            assessment = verification.verify_official_study(admitted=admitted.record, admission=admitted,
                authorization=authorization, analysis=derived, policy=policy, template=template,
                source_root=support.REPO_ROOT, observed=observed)
            for name, document in (("analysis.json", derived), ("policy.json", policy), ("verification-assessment.json", assessment)):
                support.write_json(directory / name, document)
            case.admitted = admitted
            case.context = history.write_baseline_disclosures(operation_root=directory, config_path=config_path,
                authorization=authorization, admission=admitted)
        case.originals = {path: path.read_bytes() for path in (config_path, prepared_path, runtime_path, inventory,
            authorization.authorization_path, authorization._approval_source_root / "test-only-v2.approval.json",
            directory / "framework-qa.json", directory / "source-qa.json", directory / "host-preflight.json",
            directory / "analysis.json", directory / "policy.json", directory / "verification-assessment.json",
            directory / "history-report.json", directory / "relative-effects.json")}
        return case

    @staticmethod
    def _complete_cross_control(fixture, template):
        from quervant_bench.official import cross_engine_backend as backend
        from quervant_bench.official.controls import assess_cross_engine_control

        legacy = backend._legacy(support.REPO_ROOT)
        _manifest, corpus_rows = legacy.oracle.load_and_verify(str(fixture.corpus_root))
        warm = [lane for lane in legacy.lane_descriptors() if lane["regime"] == "warm"]
        answers = {lane["id"]: legacy.oracle.expected(corpus_rows[lane["n"]], lane["field"], lane["term"], lane["k"]) for lane in warm}
        limits = {key: template["host_requirements"][key] for key in ("min_interval_ms", "max_interval_ms",
                  "max_busy_permille", "max_median_busy_permille", "max_steal_permille", "min_intervals")}
        ready = {"schema": "official-host-readiness-v1", "study_id": template["study_id"],
            "host_fingerprint": DIGEST, "adapter_cpu": 0, "controller_cpu": 1, "environment": "wsl2",
            "limits": limits, "status": "READY", "reasons": [], "observations": [
                {"elapsed_ms": 1000, "ticks": {"0": [0] * 8, "1": [0] * 8}, "adapter_busy_permille": 0,
                 "adapter_steal_permille": 0, "controller_busy_permille": 0, "controller_steal_permille": 0} for _ in range(6)]}
        slots = []
        for number in range(1, 49):
            block, position = divmod(number - 1, 4)
            slot = {"slot": number, "block": block + 1, "position": position + 1,
                "arm": template["schedule"]["control_order"][block][position], "engine": "quervant", "adapter_cpu": 0, "lanes": []}
            for lane in warm:
                answer = answers[lane["id"]]
                slot["lanes"].append({**lane, "lane_id": lane["id"], "warmups": 5,
                    "warmup_ids": [f"{lane['id']}:warmup:{i}" for i in range(5)], "samples_ns": [1000] * 20,
                    "summary_ns": legacy.summarize([1000] * 20), "oracle_ok": True,
                    "contention": {"pre": "clear", "post": "clear"}, **answer,
                    "expected_total_hits": answer["total_hits"], "expected_doc_ids": answer["doc_ids"]})
            directory = fixture.raw_root / "control/slots" / f"slot-{number:02d}"
            support.write_json(directory / "slot.json", slot)
            for side in ("pre", "post"):
                support.write_json(directory / f"readiness-{side}.json", ready)
            slots.append(slot)
        assessment = assess_cross_engine_control(slots=slots, warm_lane_ids=[lane["id"] for lane in warm])
        support.write_json(fixture.raw_root / "control/control.json", assessment)
        return assessment

    @staticmethod
    def _environment(case):
        """Substitute only independently tested external observation owners."""
        from quervant_bench.official import cross_engine_backend, retained_backend, runtime_freeze

        stack = ExitStack()

        def prepared(*args, **kwargs):
            if case.prepared_path.read_bytes() != case.prepared_bytes:
                raise BenchError(BM_IDENTITY_INVALID, "test external prepared observation changed", field_path="prepared_manifest")
            return case.prepared

        def runtime(*args, **kwargs):
            if case.runtime_path.read_bytes() != case.runtime_bytes:
                raise BenchError(BM_IDENTITY_INVALID, "test external runtime observation changed", field_path="runtime_freeze_digest")
            return SimpleNamespace(digest=case.runtime_digest)

        def observed(config, template, **kwargs):
            result = dict(case.observed)
            result["output_root_identity"] = str(config.path("output_base"))
            result["baseline_id"] = config.document["baseline"]["baseline_id"]
            result["preservation_root_identity"] = config.document["baseline"]["evidence_root"]
            return result

        def source(root, digest):
            if Path(root) != support.REPO_ROOT or not Path(root).is_dir() or digest != case.authorization.freeze.source_file_set_digest:
                raise BenchError(BM_IDENTITY_INVALID, "test external Git observation changed", field_path="source_root")
            return digest

        stack.enter_context(patch.object(workflow, "_preservation_root", return_value=Path(case.authorization.freeze.preservation_root_identity)))
        stack.enter_context(patch.object(workflow, "_prepared", side_effect=prepared))
        stack.enter_context(patch.object(cross_engine_backend, "verify_prepared", side_effect=prepared))
        stack.enter_context(patch.object(retained_backend, "load_prepared_retained_key", side_effect=prepared))
        stack.enter_context(patch.object(workflow, "observe_identities", side_effect=observed))
        stack.enter_context(patch.object(workflow, "observe_host", return_value=case.host))
        stack.enter_context(patch.object(workflow, "legacy_runner", return_value=SimpleNamespace(cpus=lambda: (0, 1))))
        stack.enter_context(patch.object(runtime_freeze, "open_current_runtime_freeze", side_effect=runtime))
        stack.enter_context(patch.object(runtime_freeze, "require_runtime_for_freeze", side_effect=runtime))
        stack.enter_context(patch("quervant_bench.qualification.identity.verify_source_identity", side_effect=source))
        return stack

    def setUp(self):
        self.environment = self._environment(self.case)
        self.addCleanup(self.environment.close)
        self.addCleanup(self._restore, self.case)

    @staticmethod
    def _restore(case):
        for path, payload in case.originals.items():
            path.write_bytes(payload)

    def _open(self, case=None, **overrides):
        from quervant_bench.official import history

        case = self.case if case is None else case
        arguments = dict(operation_root=case.directory, config_path=case.config_path,
                         authorization=case.authorization, admission=case.admitted)
        arguments.update(overrides)
        return history.open_verified_baseline_disclosures(**arguments)

    def _qualify(self, *, publish=True, context=None):
        from quervant_bench.official import coordinator

        case = self.case
        return coordinator.qualify_official_study(authorization=case.authorization, template=case.template,
            admitted=case.admitted, framework_qa=case.fixture.framework_qa, source_qa=case.fixture.source_qa,
            output_base=case.output, qa_evidence_root=case.fixture.qa_evidence_root,
            source_root=support.REPO_ROOT, publish=publish, observed=case.observed,
            baseline_context=case.context if context is None else context)

    def _expect_error(self, function, *, code=None, field=None):
        with self.assertRaises(BenchError) as raised:
            function()
        if code is not None:
            self.assertEqual(raised.exception.code, code)
        if field is not None:
            self.assertEqual(raised.exception.field_path, field)
        return raised.exception

    def _forged_effects(self):
        from quervant_bench.official import relative_effects

        path = self.case.directory / "relative-effects.json"
        document = support.read_json(path)
        document["rows"][0].update(ratio="0.5", gain_percent="50")
        document["comparisons"][0].update(current_row_digest=content_digest(document["rows"][0]),
            comparability="COMPARABLE", context_changes=[], effect_change_percentage_points="0")
        # This is a structurally valid, internally coherent false assertion.
        self.assertEqual(relative_effects.validate_disclosure(document), document)
        support.write_json(path, document)
        return document

    def test_d01_live_unchanged_pair_reopens_through_actual_owners(self):
        from quervant_bench.official import admission, authorization, history

        self.assertIs(type(self.case.authorization), authorization.VerifiedOfficialAuthorization)
        self.assertFalse(self.case.authorization.fixture_only)
        self.assertIs(type(self.case.admitted), admission.VerifiedOfficialAdmission)
        self.assertFalse(self.case.admitted.record.fixture_only)
        before = {path: path.read_bytes() for path in self.case.originals}
        reopened = self._open()
        self.assertIs(type(reopened), history.VerifiedBaselineDisclosures)
        self.assertEqual(reopened, self.case.context)
        self.assertEqual(history.reverify_baseline_disclosures(reopened), reopened)
        self.assertEqual({path: path.read_bytes() for path in self.case.originals}, before)
        effects = support.read_json(self.case.directory / "relative-effects.json")
        self.assertEqual((len(effects["rows"]), len(effects["comparisons"])), (32, 32))
        self.assertTrue(all(row["comparability"] == "NOT_COMPARABLE" for row in effects["comparisons"]))

    def test_d02_exact_capability_type_family_fixture_and_replace_guards(self):
        from dataclasses import fields
        from quervant_bench.config.errors import BM_UNSAFE_INPUT
        from quervant_bench.official import admission, authorization, history

        context = self.case.context
        class Subclass(history.VerifiedBaselineDisclosures):
            pass

        subclass = Subclass(**{item.name: getattr(context, item.name) for item in fields(context)})
        for label, value in (("mapping", vars(context)), ("plain-object", object()), ("subclass", subclass)):
            with self.subTest(case=label):
                self._expect_error(lambda: history.reverify_baseline_disclosures(value),
                                   code=BM_UNSAFE_INPUT, field="baseline_context")
        for label, changes in (
            ("wrong-family", {"study_id": protocols.STUDY_RETAINED_KEY}),
            ("changed-run", {"run_id": "33333333-3333-4333-8333-333333333333"}),
            ("wrong-typed-run", {"run_id": []}),
            ("changed-effect-digest", {"relative_effects_digest": "sha256:" + "f" * 64}),
        ):
            with self.subTest(case=label):
                self._expect_error(lambda: history.reverify_baseline_disclosures(replace(context, **changes)),
                                   code=BM_IDENTITY_INVALID, field="baseline_context")
        for field, value in (("authorization", vars(self.case.authorization)), ("admission", vars(self.case.admitted)),
                             ("authorization", replace(self.case.authorization, fixture_only=True))):
            with self.subTest(boundary=field, value=type(value).__name__):
                self._expect_error(lambda: self._open(**{field: value}), code=BM_UNSAFE_INPUT, field=field)
        forged = copy.copy(self.case.admitted)
        object.__setattr__(forged, "_record", replace(forged.record, fixture_only=True))
        self._expect_error(lambda: self._open(admission=forged), code=BM_UNSAFE_INPUT, field="admission")
        for field, target in (("authorization", authorization.VerifiedOfficialAuthorization),
                              ("admission", admission.VerifiedOfficialAdmission)):
            class Derived(target):
                pass
            original = getattr(self.case, "admitted" if field == "admission" else field)
            value = Derived(**{item.name: getattr(original, item.name) for item in fields(original)})
            with self.subTest(boundary=field, case="subclass"):
                self._expect_error(lambda: self._open(**{field: value}), code=BM_UNSAFE_INPUT, field=field)
        for field in ("current_raw_digest", "authorization_digest", "admission_index_digest", "analysis_digest",
                      "policy_digest", "verification_digest", "history_inventory_digest", "history_report_digest", "relative_effects_digest"):
            with self.subTest(case="wrong-typed-digest", field=field):
                self._expect_error(lambda: replace(context, **{field: None}), code=BM_IDENTITY_INVALID, field=field)

    def test_d03_coherent_current_effect_comparison_and_hash_forgery_rejects(self):
        from quervant_bench.official import history, relative_effects

        path = self.case.directory / "relative-effects.json"
        for label in ("ratio-gain-and-comparison", "comparison-only", "replaced-capability-digest"):
            with self.subTest(case=label):
                self._restore(self.case)
                if label == "comparison-only":
                    forged = support.read_json(path)
                    forged["comparisons"][0].update(current_row_digest=content_digest(forged["rows"][0]),
                        comparability="COMPARABLE", context_changes=[], effect_change_percentage_points="0")
                    self.assertEqual(relative_effects.validate_disclosure(forged), forged)
                    support.write_json(path, forged)
                else:
                    forged = self._forged_effects()
                if label == "replaced-capability-digest":
                    context = replace(self.case.context, relative_effects_digest=content_digest(forged))
                    operation = lambda: history.reverify_baseline_disclosures(context)
                else:
                    operation = self._open
                self._expect_error(operation, code=BM_IDENTITY_INVALID, field="relative-effects.json")

    def test_d04_historical_summary_identity_and_level_are_reconstructed(self):
        path = self.case.directory / "history-report.json"
        changes = (
            ("role", lambda entry: entry.update(input_role="pr15d-archive")),
            ("digest", lambda entry: entry.update(input_digest="sha256:" + "f" * 64)),
            ("source", lambda entry: entry["normalized_rows"][0].update(source_commit="f" * 40)),
            ("run", lambda entry: entry["normalized_rows"][0].update(run_id="another-run")),
            ("method", lambda entry: entry["normalized_rows"][0].update(method_id="cross-engine-three-trial-effects-v1")),
            ("as-reported", lambda entry: entry["normalized_rows"][0].update(evidence_level="RECOMPUTED")),
        )
        for label, change in changes:
            with self.subTest(case=label):
                self._restore(self.case)
                report = support.read_json(path)
                self.assertEqual(report["entries"][0]["status"], "FOUND")
                self.assertEqual(len(report["entries"][0]["normalized_rows"]), 32)
                change(report["entries"][0])
                support.write_json(path, report)
                self._expect_error(self._open, code=BM_IDENTITY_INVALID)

    def test_d05_dependencies_changed_or_absent_stop_before_publication(self):
        from quervant_bench.official import publication

        case = self.case
        approval = case.authorization._approval_source_root / "test-only-v2.approval.json"
        for label, path, change in (
            ("configuration", case.config_path, lambda document: document.update(output_base=str(case.external / "other-output"))),
            ("prepared", case.prepared_path, lambda document: document.update(family="changed")),
            ("framework-qa", case.directory / "framework-qa.json", lambda document: document["checks"][0].update(failed=1)),
            ("approval", approval, lambda document: document.update(approved_authorization_digest="sha256:" + "f" * 64)),
            ("source-missing", case.config_path, lambda document: document.update(source_root=str(case.external / "absent-source"))),
        ):
            with self.subTest(case=label):
                self._restore(case)
                document = support.read_json(path)
                change(document)
                support.write_json(path, document)
                with patch.object(publication, "publish_validated_members_atomic") as writer:
                    self._expect_error(self._qualify)
                    writer.assert_not_called()
                self.assertEqual(list(case.output.iterdir()), [])

    def test_d06_mutation_after_gate_d_or_at_publication_never_reaches_writer(self):
        from quervant_bench.official import coordinator, publication

        for label, owner, name in (("gate-d-to-qa-barrier", coordinator, "_derive_bundle"),
                                   ("publication-before-context-refresh", publication, "_validate_bundle_semantics")):
            with self.subTest(boundary=label):
                self._restore(self.case)
                actual = getattr(owner, name)
                events = []

                def mutate_after_real_boundary(*args, **kwargs):
                    result = actual(*args, **kwargs)
                    events.append("real-boundary-completed")
                    self._forged_effects()
                    return result

                with patch.object(owner, name, side_effect=mutate_after_real_boundary), \
                        patch.object(publication, "publish_validated_members_atomic") as writer:
                    self._expect_error(self._qualify, code=BM_IDENTITY_INVALID, field="relative-effects.json")
                    writer.assert_not_called()
                self.assertEqual(events, ["real-boundary-completed"])
                self.assertEqual(list(self.case.output.iterdir()), [])

    def test_d07_postpublication_and_standalone_load_reverify_live_context(self):
        from quervant_bench.official import history, publication

        case = self.case
        actual_load = publication.load_official_bundle
        try:
            with patch.object(publication, "load_official_bundle", wraps=actual_load) as loader:
                result = self._qualify()
            self.assertEqual(loader.call_count, 1)
            forwarded = loader.call_args.kwargs
            self.assertIs(forwarded["authorization"], case.authorization)
            self.assertEqual(forwarded["observed"], case.observed)
            self.assertIs(type(forwarded["baseline_context"]), history.VerifiedBaselineDisclosures)
            arguments = dict(output_base=case.output, study_id=case.authorization.study_id,
                run_id=case.authorization.run_id, anchors=result.anchors, authorization=case.authorization,
                observed=case.observed, baseline_context=case.context)
            loaded = actual_load(**arguments)
            self.assertEqual(loaded.manifest_digest, result.manifest_digest)
            self._forged_effects()
            with patch.object(publication, "official_destination_state", side_effect=AssertionError("destination read before authority")):
                self._expect_error(lambda: actual_load(**arguments), code=BM_IDENTITY_INVALID, field="relative-effects.json")
        finally:
            shutil.rmtree(case.output)
            case.output.mkdir()

    def test_d08_json_alias_deleted_swapped_and_private_path_rejections(self):
        from quervant_bench.config.errors import BM_SCHEMA_INVALID
        from quervant_bench.official import history

        case = self.case
        effects_path, history_path = case.directory / "relative-effects.json", case.directory / "history-report.json"
        for label in ("duplicate-key", "numeric-schema-alias", "numeric-ratio-token", "deleted", "swapped"):
            with self.subTest(case=label):
                self._restore(case)
                if label == "duplicate-key":
                    payload = effects_path.read_bytes()
                    effects_path.write_bytes(b'{"schema_version":1,' + payload[1:])
                elif label == "deleted":
                    effects_path.unlink()
                elif label == "swapped":
                    effects_path.write_bytes(history_path.read_bytes())
                    history_path.write_bytes(case.originals[effects_path])
                else:
                    document = support.read_json(effects_path)
                    if label == "numeric-schema-alias":
                        document["schema_version"] = 1.0
                    else:
                        document["rows"][0]["ratio"] = 0.5
                        document["rows"][0]["gain_percent"] = "50"
                    support.write_json(effects_path, document)
                self._expect_error(self._open)
        self._restore(case)
        for name, replacement in (("_operation_root", case.external / "not-the-approved-run"),
                                  ("_config_path", case.external / "missing-config.json"),
                                  ("_history_inventory_path", case.external / "another-inventory.json")):
            with self.subTest(private_path=name):
                self._expect_error(lambda: history.reverify_baseline_disclosures(replace(case.context, **{name: replacement})))


class RetainedLiveDisclosureFactoryTests(LiveDisclosureFactoryTests):
    """One expensive retained positive; original verifier is never substituted.

    Run this selector on the full host: the frozen verifier checks every raw
    oracle again on each required capability refresh. Cross negatives are not
    inherited/repeated against the expensive retained tree.
    """

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="test-retained-live-baseline-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.case = cls._build_case("retained")

    # Disable inherited cross-only selectors: the separate test below exercises
    # retained success and its family-specific coherent interval attack once.
    test_d01_live_unchanged_pair_reopens_through_actual_owners = None
    test_d02_exact_capability_type_family_fixture_and_replace_guards = None
    test_d03_coherent_current_effect_comparison_and_hash_forgery_rejects = None
    test_d04_historical_summary_identity_and_level_are_reconstructed = None
    test_d05_dependencies_changed_or_absent_stop_before_publication = None
    test_d06_mutation_after_gate_d_or_at_publication_never_reaches_writer = None
    test_d07_postpublication_and_standalone_load_reverify_live_context = None
    test_d08_json_alias_deleted_swapped_and_private_path_rejections = None

    def test_d01_d03_retained_actual_factory_and_coherent_ci_forgery(self):
        from quervant_bench.official import history, relative_effects

        context = self.case.context  # writer returned its actual production opener.
        self.assertIs(type(context), history.VerifiedBaselineDisclosures)
        self.assertFalse(self.case.authorization.fixture_only)
        self.assertFalse(self.case.admitted.record.fixture_only)
        self.case.runtime_path.write_bytes(self.case.runtime_bytes + b" ")
        try:
            self._expect_error(lambda: history.reverify_baseline_disclosures(context),
                               code=BM_IDENTITY_INVALID, field="runtime_freeze_digest")
        finally:
            self.case.runtime_path.write_bytes(self.case.runtime_bytes)
        path = self.case.directory / "relative-effects.json"
        document = support.read_json(path)
        self.assertEqual(len(document["rows"]), 864)
        document["rows"][0]["uncertainty"]["low"] = "0.1"
        document["rows"][0]["uncertainty"]["high"] = "2"
        document["rows"][0]["uncertainty"]["seed"] = 42
        self.assertEqual(relative_effects.validate_disclosure(document), document)
        support.write_json(path, document)
        replaced = replace(context, relative_effects_digest=content_digest(document))
        self._expect_error(lambda: history.reverify_baseline_disclosures(replaced),
                           code=BM_IDENTITY_INVALID, field="relative-effects.json")



class VersionBoundaryTests(unittest.TestCase):
    def test_config_template_version_cross_product_before_output_or_build(self):
        for study in protocols.OFFICIAL_STUDIES:
            for config_version in (1, 2):
                for template_version in (1, 2):
                    with self.subTest(study=study, config=config_version, template=template_version):
                        config = OperationConfig({"schema_version": config_version, "source_root": str(support.REPO_ROOT),
                            "policy_inputs": None, "baseline": {"runtime_freeze_path": None if study == protocols.STUDY_CROSS_ENGINE else "/abs/runtime.json"}})
                        path = protocols.template_path(study, support.REPO_ROOT, version=template_version)
                        with patch.object(workflow, "create_directory") as create, patch.object(workflow, "_prepared") as prepare:
                            if config_version == template_version:
                                self.assertEqual(workflow._template(study, path, config)["schema_version"], config_version)
                            else:
                                with self.assertRaises(BenchError) as raised:
                                    workflow._template(study, path, config)
                                self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_IDENTITY_INVALID, "schema_version"))
                            create.assert_not_called()
                            prepare.assert_not_called()

    def test_mixed_g0_profile_rejects_before_qa_or_output(self):
        for study in protocols.OFFICIAL_STUDIES:
            for version, g0_version in ((1, 2), (2, 1)):
                with self.subTest(study=study, config=version, g0=g0_version), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    config = OperationConfig({"schema_version": version, "source_root": str(root), "workspace": str(root / "runs"),
                        "authorization_path": str(root / "g0.json"), "approval_source_root": str(root / "approvals"),
                        "approval_source_identity": "external-review"})
                    template = protocols.read_canonical_json(protocols.template_path(study, version=version))
                    cap = SimpleNamespace(study_id=study, run_id=RUN, freeze=SimpleNamespace(profile_version=g0_version))
                    with ExitStack() as stack:
                        stack.enter_context(patch.object(workflow, "_preservation_root"))
                        stack.enter_context(patch.object(workflow, "_prepared", return_value=SimpleNamespace(binary_digest=DIGEST)))
                        stack.enter_context(patch.object(workflow, "observe_identities", return_value={}))
                        stack.enter_context(patch.object(workflow.authorization, "read_approval_record", return_value=({"approved_authorization_digest": DIGEST}, "unused")))
                        stack.enter_context(patch.object(workflow.authorization, "open_verified_official_authorization", return_value=cap))
                        stack.enter_context(patch("quervant_bench.official.runtime_freeze.open_current_runtime_freeze", return_value=object()))
                        qa = stack.enter_context(patch.object(workflow.coordinator, "_require_qa"))
                        create = stack.enter_context(patch.object(workflow, "create_directory"))
                        with self.assertRaises(BenchError) as raised:
                            workflow._open(config, template, root / "runs" / RUN)
                        self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_IDENTITY_INVALID, "schema_version"))
                        qa.assert_not_called()
                        create.assert_not_called()
                    self.assertFalse((root / "runs").exists())


class BaselineAcquisitionWiringTests(unittest.TestCase):
    def exercise(self, study, *, fail_at=None, export_fails=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        out = root / "runs" / RUN
        config = OperationConfig({"schema_version": 2, "source_root": str(root), "workspace": str(root / "runs"),
            "output_base": str(root / "qualified"), "adapter_cpu": 0, "controller_cpu": 1,
            "policy_inputs": None, "baseline": {"baseline_id": BASELINE, "evidence_root": str(root / "preserved")}})
        template = {"schema_version": 2, "study_id": study, "stopping": {"backend_timeout_seconds": 60}}
        cap = SimpleNamespace(study_id=study, run_id=RUN, freeze=SimpleNamespace(profile_version=2, authorization_digest=DIGEST, baseline_id=BASELINE))
        op = workflow.Operation(config, template, cap, object(), {"observed": "identity"}, out,
            runtime_context=object(), host_preflight={"kind": "observed-host"})
        admitted = SimpleNamespace(record=SimpleNamespace(admission_index={"kind": "test-index"}, raw_series_root_digest=DIGEST))
        events = []
        primary = BenchError(BM_IDENTITY_INVALID, "explicit external-boundary failure", field_path="test_boundary")

        def action(stage):
            events.append(stage)
            if fail_at == stage:
                raise primary

        def acquired(unit):
            action("acquire:" + unit)
            path = out / "raw" / unit / "samples.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"test_only":true}\n')

        def checkpoint(**kwargs):
            self.assertEqual(kwargs["operation_root"], out)
            self.assertTrue((out / "operation.json").is_file())
            stage = "checkpoint:" + kwargs["unit"] + ":" + kwargs.get("status", "COMPLETE")
            action(stage)
            if export_fails and kwargs.get("status") == "STOPPED":
                raise OSError("separate export failure")

        invocation_names = {"preflight", "readiness-control", "verify-control", "publish-control", "verify-series"}
        for campaign in protocols.D3C_CAMPAIGN_NAMES:
            invocation_names.update({"readiness-" + campaign, "verify-" + campaign, "publish-" + campaign})
        with ExitStack() as stack:
            for owner, name, value in ((workflow, "load_operation_config", config), (workflow, "_template", template),
                                        (workflow, "_open", op), (workflow, "_admit", admitted)):
                stack.enter_context(patch.object(owner, name, return_value=value))
            stack.enter_context(patch.object(workflow, "_readiness", side_effect=lambda _op: action("readiness")))
            stack.enter_context(patch.object(workflow, "_invoke", side_effect=lambda _op, name, inv: action(name)))
            stack.enter_context(patch.object(acquisition, "probe_isolated_home",
                side_effect=lambda **kwargs: action("home-probe") if fail_at == "home-probe" else None))
            stack.enter_context(patch.object(acquisition, "retained_key_invocations", return_value=dict.fromkeys(invocation_names)))
            stack.enter_context(patch.object(transport, "preserve_baseline_checkpoint", side_effect=checkpoint))
            stack.enter_context(patch.object(workflow, "verify_campaign_binaries", side_effect=lambda directory, *args, **kwargs: action("binaries:" + directory.name)))
            stack.enter_context(patch("quervant_bench.official.cross_engine_backend.acquire_cross_engine_control", side_effect=lambda *args, **kwargs: acquired("control")))
            stack.enter_context(patch("quervant_bench.official.cross_engine_backend.acquire_cross_engine_treatment", side_effect=lambda *args, **kwargs: acquired("treatment")))
            selected = stack.enter_context(patch("quervant_bench.official.cross_engine_backend.verify_cross_engine_control", side_effect=lambda **kwargs: action("verify-control")))
            retained = stack.enter_context(patch("quervant_bench.official.retained_acquisition.acquire_retained_campaign", side_effect=lambda *args, **kwargs: acquired(kwargs["campaign"])))
            if fail_at:
                with self.assertRaises(BenchError) as raised:
                    workflow.run_official(study, Path("template.json"), out, root / "config.json")
                self.assertIs(raised.exception, primary)
                self.assertFalse((out / "sealed.json").exists())
                self.assertTrue((out / "stopped.json").is_file())
                if export_fails:
                    self.assertTrue((out / "preservation-failure.json").is_file())
                    self.assertTrue(json.loads((out / "preservation-failure.json").read_text())["primary_error_preserved"])
            else:
                result = workflow.run_official(study, Path("template.json"), out, root / "config.json")
                self.assertEqual(result["data"]["status"], "REAL_EVIDENCE_SEALED")
                self.assertFalse(result["data"]["accepted"])
                self.assertTrue((out / "sealed.json").is_file())
            if study == protocols.STUDY_CROSS_ENGINE and selected.called:
                self.assertIs(selected.call_args.kwargs["template"], template)
            if retained.called:
                self.assertTrue(all(call.kwargs["runtime_context"] is op.runtime_context for call in retained.call_args_list))
        self.assertEqual(json.loads((out / "host-preflight.json").read_text()), op.host_preflight)
        self.assertEqual(json.loads((out / "observed-identities.json").read_text()), op.observed)
        return events, out

    def test_cross_control_and_treatment_checkpoint_before_later_verification(self):
        events, _ = self.exercise(protocols.STUDY_CROSS_ENGINE)
        self.assertEqual(events, ["readiness", "acquire:control", "checkpoint:control:COMPLETE",
                                  "verify-control", "acquire:treatment", "checkpoint:treatment:COMPLETE"])

    def test_retained_all_three_checkpoints_precede_binary_verify_and_publish(self):
        events, _ = self.exercise(protocols.STUDY_RETAINED_KEY)
        campaigns = (protocols.D3C_CONTROL_NAME, *protocols.D3C_CAMPAIGN_NAMES)
        for campaign in campaigns:
            index = events.index("acquire:" + campaign)
            self.assertEqual(events[index + 1:index + 3], ["checkpoint:" + campaign + ":COMPLETE", "binaries:" + campaign])
        self.assertLess(events.index("publish-control"), events.index("acquire:" + campaigns[1]))
        self.assertLess(events.index("publish-" + campaigns[1]), events.index("acquire:" + campaigns[2]))
        self.assertEqual(events[-1], "verify-series")

    def test_failure_after_each_completed_unit_preserves_raw_and_stops_without_retry(self):
        cases = [(protocols.STUDY_CROSS_ENGINE, "verify-control", "control"),
                 (protocols.STUDY_CROSS_ENGINE, "checkpoint:treatment:COMPLETE", "treatment")]
        cases += [(protocols.STUDY_RETAINED_KEY, "binaries:" + campaign, campaign)
                  for campaign in (protocols.D3C_CONTROL_NAME, *protocols.D3C_CAMPAIGN_NAMES)]
        for study, failure, unit in cases:
            with self.subTest(study=study, unit=unit):
                events, out = self.exercise(study, fail_at=failure)
                self.assertEqual(events[-1], "checkpoint:" + unit + ":STOPPED")
                self.assertEqual(events.count("acquire:" + unit), 1)
                self.assertEqual((out / "raw" / unit / "samples.json").read_bytes(), b'{"test_only":true}\n')

    def test_original_error_remains_primary_when_stopped_export_also_fails(self):
        events, _ = self.exercise(protocols.STUDY_CROSS_ENGINE, fail_at="verify-control", export_fails=True)
        self.assertEqual(events[-1], "checkpoint:control:STOPPED")

    def test_failure_before_first_campaign_preserves_stopped_provenance_without_acquiring(self):
        cases = ((protocols.STUDY_CROSS_ENGINE, "readiness", "control"),
                 (protocols.STUDY_RETAINED_KEY, "readiness", protocols.D3C_CONTROL_NAME),
                 (protocols.STUDY_RETAINED_KEY, "home-probe", protocols.D3C_CONTROL_NAME))
        for study, failure, unit in cases:
            with self.subTest(study=study, failure=failure):
                events, out = self.exercise(study, fail_at=failure)
                self.assertEqual(events, [failure, "checkpoint:" + unit + ":STOPPED"])
                self.assertEqual(list((out / "raw").iterdir()), [])
                self.assertTrue((out / "operation.json").is_file())
                self.assertTrue((out / "host-preflight.json").is_file())
                self.assertTrue((out / "observed-identities.json").is_file())


class BaselineStageWiringTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.out = self.root / "runs" / RUN
        create_directory(self.out)
        self.config = OperationConfig({"schema_version": 2, "source_root": str(support.REPO_ROOT),
            "workspace": str(self.out.parent), "policy_inputs": None,
            "baseline": {"baseline_id": BASELINE, "evidence_root": str(self.root / "preserved")}})
        self.template = {"schema_version": 2, "study_id": protocols.STUDY_RETAINED_KEY}
        self.cap = SimpleNamespace(study_id=protocols.STUDY_RETAINED_KEY, run_id=RUN,
            freeze=SimpleNamespace(profile_version=2, authorization_digest=DIGEST, baseline_id=BASELINE))
        self.op = workflow.Operation(self.config, self.template, self.cap, object(), {}, self.out)
        write_record(self.out, "operation.json", workflow._operation_record(self.op))
        write_record(self.out, "sealed.json", {"raw_series_root_digest": DIGEST})
        self.admitted = SimpleNamespace(record=SimpleNamespace(admission_index={"kind": "test-index"}, raw_series_root_digest=DIGEST))
        for name, value in (("load_operation_config", self.config), ("_template", self.template), ("_open", self.op), ("_admit", self.admitted)):
            active = patch.object(workflow, name, return_value=value)
            active.start()
            self.addCleanup(active.stop)

    def test_null_policy_can_analyze_v2_and_repeat_without_reacquisition(self):
        documents = ({"schema_version": 2, "retained_slot_statistics": "test-boundary"}, {"schema_version": 1, "decision_status": "POLICY_NOT_DERIVABLE"})
        with patch.object(workflow.analysis, "analyze_official_study", return_value=documents) as analyzed:
            first = workflow.dispatch_official_stage("analyze", RUN, self.root / "config.json")
            second = workflow.dispatch_official_stage("analyze", RUN, self.root / "config.json")
        self.assertEqual(first, second)
        self.assertEqual(first["data"]["decision_status"], "POLICY_NOT_DERIVABLE")
        self.assertTrue(all(call.kwargs["policy_inputs"] is None for call in analyzed.call_args_list))
        self.assertFalse((self.out / "stopped.json").exists())

    def test_insufficient_complete_result_preserves_seal_and_diagnostics(self):
        error = BenchError(BM_EVIDENCE_UNAVAILABLE, "current baseline has insufficient symmetric retained blocks", field_path="retained_slot_statistics")
        seal = (self.out / "sealed.json").read_bytes()
        with patch.object(workflow.analysis, "analyze_official_study", side_effect=error), self.assertRaises(BenchError) as raised:
            workflow.dispatch_official_stage("analyze", RUN, self.root / "config.json")
        self.assertIs(raised.exception, error)
        self.assertEqual((self.out / "sealed.json").read_bytes(), seal)
        blocked = json.loads((self.out / "analysis-blocked.json").read_text())
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertFalse(blocked["measurement_retry_allowed"])
        self.assertFalse((self.out / "analysis.json").exists())

    def test_mismatched_persisted_operation_version_rejects_before_admission(self):
        declaration = workflow._operation_record(self.op)
        declaration["schema_version"] = 1
        (self.out / "operation.json").write_bytes(canonical_document_bytes(declaration))
        with patch.object(workflow, "_admit") as admitted, self.assertRaises(BenchError) as raised:
            workflow.dispatch_official_stage("validate", RUN, self.root / "config.json")
        self.assertEqual(raised.exception.field_path, "operation")
        admitted.assert_not_called()


class BaselinePreparationAndRuntimeBarrierTests(unittest.TestCase):
    def test_complete_preparation_and_runtime_precede_qa_and_are_reused_after_missing_qa(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            output = source / "target" / "prepared"
            manifest = output / "prepared-retained-key.json"
            runtime_path = source / "target" / "runtime.json"
            config = OperationConfig({"schema_version": 2, "acceptance_profile": protocols.CURRENT_BASELINE_PROFILE,
                "source_root": str(source), "prepared_manifest": str(manifest), "corpus_dir": str(source / "target/corpus"),
                "output_base": str(root / "qualified"), "adapter_cpu": 0, "controller_cpu": 1,
                "baseline": {"baseline_id": BASELINE, "runtime_freeze_path": str(runtime_path)}})
            template = {"schema_version": 2, "study_id": protocols.STUDY_RETAINED_KEY}
            prepared = SimpleNamespace(binary_digest=DIGEST, corpus_dir=config.path("corpus_dir"))
            events = []
            observed = {name: DIGEST for name in protocols.OBSERVED_IDENTITY_FIELDS}
            observed.update(source_commit="a" * 40, output_root_identity=str(root / "qualified"),
                acceptance_profile=protocols.CURRENT_BASELINE_PROFILE, baseline_id=BASELINE,
                preservation_root_identity=str(root / "ordinary/benchmark-results/baselines" / BASELINE), runtime_freeze_digest=DIGEST)

            def build(**kwargs):
                events.append("build")
                output.mkdir(parents=True)
                write_record(output, manifest.name, {"kind": "test-only-preparation"})
                return prepared

            def runtime(**kwargs):
                events.append("runtime")
                self.assertTrue((output / "preparation-inputs.json").is_file())
                write_record(runtime_path.parent, runtime_path.name, {"kind": "test-only-runtime"}, reuse=True)

            available = [False]
            def qa(*args):
                events.append("qa")
                self.assertTrue(runtime_path.is_file())
                if not available[0]:
                    raise BenchError(BM_EVIDENCE_UNAVAILABLE, "actual QA not provided", field_path="qa_evidence")
                return observed

            for name, value in (("load_operation_config", config), ("_template", template),
                                ("git_identity", ("a" * 40, DIGEST)), ("observe_host", {}), ("_prepared", prepared)):
                stack.enter_context(patch.object(workflow, name, return_value=value))
            stack.enter_context(patch.object(workflow, "_preservation_root"))
            stack.enter_context(patch("quervant_bench.evidence.provenance.repository_root", return_value=source))
            builder = stack.enter_context(patch.object(workflow, "prepare_retained_key", side_effect=build))
            stack.enter_context(patch("quervant_bench.official.runtime_freeze.prepare_current_runtime_freeze", side_effect=runtime))
            stack.enter_context(patch.object(workflow, "_preparation_qa_observations", side_effect=qa))
            with self.assertRaises(BenchError):
                workflow.prepare_official(protocols.STUDY_RETAINED_KEY, Path("v2.json"), output, root / "config.json")
            before = (manifest.read_bytes(), runtime_path.read_bytes())
            self.assertFalse((output / "authorization-inputs.json").exists())
            self.assertEqual(events, ["build", "runtime", "qa"])
            available[0] = True
            result = workflow.prepare_official(protocols.STUDY_RETAINED_KEY, Path("v2.json"), output, root / "config.json")
            self.assertEqual(events, ["build", "runtime", "qa", "runtime", "qa"])
            builder.assert_called_once()
            self.assertEqual((manifest.read_bytes(), runtime_path.read_bytes()), before)
            self.assertEqual(result["data"]["schema_version"], 2)
            self.assertEqual(result["data"]["observations"], observed)
            self.assertFalse(result["data"]["measurement_executed"])

    def test_runtime_is_revalidated_before_every_readiness_and_publish_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            op = workflow.Operation(OperationConfig({"schema_version": 2, "source_root": str(root)}), {},
                SimpleNamespace(study_id=protocols.STUDY_RETAINED_KEY), object(), {}, root,
                runtime_context=object())
            error = BenchError(BM_IDENTITY_INVALID, "runtime changed", field_path="runtime_freeze")
            names = ["readiness-control", "publish-control"]
            for campaign in protocols.D3C_CAMPAIGN_NAMES:
                names += ["readiness-" + campaign, "publish-" + campaign]
            for name in names:
                with self.subTest(child=name), patch.object(workflow.authorization, "require_verified_official_authorization", return_value=object()), \
                        patch("quervant_bench.official.runtime_freeze.require_runtime_for_freeze", side_effect=error) as reverify, \
                        patch.object(acquisition, "run_backend") as child, patch.object(workflow, "write_record") as writer:
                    with self.assertRaises(BenchError) as raised:
                        workflow._invoke(op, name, object())
                    self.assertIs(raised.exception, error)
                    reverify.assert_called_once()
                    child.assert_not_called()
                    writer.assert_not_called()

