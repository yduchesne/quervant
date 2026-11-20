"""Offline retained bridge checks; fake builds never execute a toolchain/engine."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.host.capabilities import collect_host_capabilities
from quervant_bench.official import cross_engine_backend, protocols
from quervant_bench.official import retained_acquisition as backend
from quervant_bench.official import retained_backend
from quervant_bench.official.authorization import _open_fixture_authorization
from quervant_bench.official.retained_backend import PreparedRetainedKey, legacy_runner
from quervant_bench.tests import official_support
from quervant_bench.tests.test_official_operation_identity import HostProvider


class RetainedOuterHostBoundaryTests(unittest.TestCase):
    """Exercise the outer retained entrypoint through its real shared CPU check."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.root.mkdir()
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir(mode=0o700)
        self.directory = self.root / "target" / "pr15i-d3-c" / "attempt" / protocols.D3C_CONTROL_NAME
        self.directory.parent.mkdir(parents=True)
        self.template = protocols.read_canonical_json(protocols.template_path(protocols.STUDY_RETAINED_KEY))
        self.template_path = protocols.template_path(protocols.STUDY_RETAINED_KEY, self.root)
        self.template_path.parent.mkdir(parents=True)
        self.prepared = SimpleNamespace(manifest_path=self.root / "prepared.json",
            binary_digest="sha256:" + "a" * 64, manifest={"corpus_digest": "sha256:" + "b" * 64})
        self.runner = SimpleNamespace(require_freeze=Mock(), cpus=Mock(return_value=(0, 1)))

    def exercise(self, environment, selector, *, accepted):
        self.template["host_requirements"]["environment"] = selector
        self.template_path.write_bytes(canonical_document_bytes(self.template))
        provider = HostProvider(environment)
        preflight = {"kind": "official-host-preflight", "schema_version": 1,
            "capabilities": collect_host_capabilities(provider), "adapter_cpu": 0, "controller_cpu": 1}
        freeze = SimpleNamespace(profile_version=1, binary_manifest_digest=self.prepared.binary_digest,
            corpus_manifest_digest=self.prepared.manifest["corpus_digest"],
            design_digest=content_digest(self.template), host_preflight_digest=content_digest(preflight))
        reached = RuntimeError("test stops after the real CPU check, before filesystem creation or a worker")
        real_cpu_check = cross_engine_backend._verify_cpu_pair

        def verify_then_stop(*args, **kwargs):
            real_cpu_check(*args, **kwargs)
            raise reached

        with ExitStack() as stack:
            stack.enter_context(patch.object(backend, "require_verified_official_authorization", return_value=freeze))
            stack.enter_context(patch.object(backend, "repository_root", return_value=self.root))
            stack.enter_context(patch.object(backend, "load_prepared_retained_key", return_value=self.prepared))
            stack.enter_context(patch.object(backend, "legacy_runner", return_value=self.runner))
            stack.enter_context(patch.object(cross_engine_backend, "LinuxCapabilityProvider", return_value=provider))
            checked = stack.enter_context(patch.object(backend, "_verify_cpu_pair", side_effect=verify_then_stop))
            fresh = stack.enter_context(patch.object(backend, "_fresh"))
            worker_context = stack.enter_context(patch.object(backend.multiprocessing, "get_context"))
            worker = stack.enter_context(patch.object(backend, "_worker"))
            with self.assertRaises(RuntimeError if accepted else BenchError) as raised:
                backend.acquire_retained_campaign(object(), root=self.root, directory=self.directory,
                    campaign=protocols.D3C_CONTROL_NAME, prepared=self.prepared, observed={}, official_home=self.home)
            if accepted:
                self.assertIs(raised.exception, reached)
            else:
                self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_UNSAFE_INPUT, "cpu_pair"))
            checked.assert_called_once()
            self.assertEqual(checked.call_args.kwargs["template"]["study_id"], protocols.STUDY_RETAINED_KEY)
            self.assertEqual(checked.call_args.kwargs["template"]["host_requirements"]["environment"], selector)
            fresh.assert_not_called()
            worker_context.assert_not_called()
            worker.assert_not_called()
        self.assertFalse(self.directory.exists())
        self.assertFalse((self.directory.parent / "official-worker-records").exists())

    def test_retained_outer_entry_uses_its_reviewed_template_for_both_hosts(self):
        for environment in ("native-linux", "wsl2"):
            with self.subTest(environment=environment):
                self.exercise(environment, "native-linux-or-wsl2", accepted=True)

    def test_retained_outer_entry_preserves_literal_host_restrictions(self):
        for environment, selector in (("wsl2", "native-linux"), ("native-linux", "wsl2")):
            with self.subTest(environment=environment, selector=selector):
                self.exercise(environment, selector, accepted=False)

    def test_current_receipt_rejected_by_direct_v1_outer_before_original_helper_or_worker(self):
        from quervant_bench.official import runtime_freeze
        receipt = self.root / runtime_freeze.BACKEND_RECEIPT
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(canonical_document_bytes({"receipt_origin": "current-baseline-v2"}))
        freeze = SimpleNamespace(profile_version=1, binary_manifest_digest=self.prepared.binary_digest,
            corpus_manifest_digest=self.prepared.manifest["corpus_digest"])
        with patch.object(backend, "require_verified_official_authorization", return_value=freeze), \
                patch.object(backend, "repository_root", return_value=self.root), \
                patch.object(backend, "load_prepared_retained_key", return_value=self.prepared), \
                patch.object(backend, "legacy_runner", return_value=self.runner), \
                patch.object(backend, "_fresh") as fresh, patch.object(backend.multiprocessing, "get_context") as process:
            with self.assertRaises(BenchError) as raised:
                backend.acquire_retained_campaign(object(), root=self.root, directory=self.directory,
                    campaign=protocols.D3C_CONTROL_NAME, prepared=self.prepared, observed={}, official_home=self.home)
            self.assertEqual(raised.exception.field_path, "t6_freeze_receipt")
            self.runner.require_freeze.assert_not_called()
            self.runner.cpus.assert_not_called()
            fresh.assert_not_called()
            process.assert_not_called()

    def test_worker_reopens_v2_binding_before_execute_or_affinity(self):
        receipts = self.root / "worker-records"
        receipts.mkdir()
        binding = {"envelope_path": str(self.root / "missing-runtime.json"), "digest": "sha256:" + "a" * 64, "profile_version": 2}
        with patch.object(backend, "load_prepared_retained_key", return_value=self.prepared), \
                patch.object(backend.os, "setsid"), patch.object(backend.os, "dup2"), \
                patch.object(backend.os, "sched_setaffinity") as pin, \
                patch.dict(os.environ, dict(os.environ), clear=True), \
                patch.object(backend.traceback, "print_exc") as traceback, \
                patch.object(backend, "_execute_campaign") as execute:
            with self.assertRaises(BenchError):
                backend._worker(self.directory, protocols.D3C_CONTROL_NAME, self.prepared.manifest_path,
                    self.root, {"PATH": os.environ.get("PATH", "")}, receipts, binding)
            execute.assert_not_called()
            pin.assert_not_called()
            traceback.assert_called_once()


class RetainedPreparationWrapperTests(unittest.TestCase):
    def test_parent_rehashes_manifest_after_the_bounded_worker_finishes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build, corpus = root / "target/pr15i-d3-c/prepare", root / "corpus"
            calls = []
            prepared = object()
            with patch.object(retained_backend, "require_clean_head"), \
                    patch.object(retained_backend, "_run_owned_preparation", side_effect=lambda **kwargs: calls.append(("worker", kwargs))), \
                    patch.object(retained_backend, "load_prepared_retained_key", side_effect=lambda *args, **kwargs: (calls.append(("reload", args)), prepared)[1]), \
                    patch.object(retained_backend, "_prepare_retained_key_body") as body:
                actual = retained_backend.prepare_retained_key(root=root, build_root=build, corpus_dir=corpus)
            self.assertIs(actual, prepared)
            self.assertEqual([call[0] for call in calls], ["worker", "reload"])
            self.assertEqual(calls[0][1]["study_id"], backend.STUDY_RETAINED_KEY)
            self.assertEqual(calls[1][1], (build / "prepared-retained-key.json",))
            body.assert_not_called()


class RetainedBinaryBarrierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original = legacy_runner()
        protocol_bytes = (Path(self.original.TOOLING_DIR) / "protocol_v3r3.json").read_bytes()
        self.protocol = json.loads(protocol_bytes)
        self.protocol_sha = hashlib.sha256(protocol_bytes).hexdigest()
        self.assertEqual(self.protocol_sha, self.original.PROTOCOL_SHA256)
        self.payloads = {False: b"base executable fixture; never launched\n",
                         True: b"experiment executable fixture; never launched\n"}
        self.expected = {arm: {"binary": str(self.root / "prepared" / arm),
            "sha256": hashlib.sha256(self.payloads[feature]).hexdigest(), "bytes": len(self.payloads[feature]),
            "argv": ["fixture-build-not-executed"], "feature": feature,
            "source_sha": self.original.EXPERIMENT_SHA if feature else self.original.BASE_SHA}
            for arm, feature in (("A", False), ("B", True))}
        self.prepared = PreparedRetainedKey(self.root / "prepared.json", self.root, self.root / "corpus",
            {"binaries": self.expected}, "sha256:" + "1" * 64)
        self.calls = []
        self.corrupt_build = None
        self.build_count = 0
        self.current_source = self.original.BASE_SHA

        def build(canonical, target, feature):
            self.build_count += 1
            self.calls.append(("build", self.build_count, feature, self.current_source))
            binary = Path(target) / "release/pr15d-quervant-adapter"
            binary.parent.mkdir(parents=True)
            # Returned metadata intentionally still claims the prepared bytes
            # when the on-disk build is corrupted. The barrier must hash it.
            binary.write_bytes(b"unapproved bytes" if self.build_count == self.corrupt_build else self.payloads[feature])
            return {**self.expected["B" if feature else "A"], "binary": str(binary)}

        def switch(canonical, previous, next_source):
            self.calls.append(("switch", previous, next_source))
            self.current_source = next_source

        def write(path, document, exclusive=False):
            self.calls.append(("write", Path(path).name))
            return self.original.wj(path, document, exclusive=exclusive)

        self.runner = SimpleNamespace(
            BASE_SHA=self.original.BASE_SHA, EXPERIMENT_SHA=self.original.EXPERIMENT_SHA,
            prepare_corpus=Mock(side_effect=lambda protocol, path: path),
            worktree=Mock(side_effect=lambda path, sha: str(Path(path) / "compile-source")),
            build=Mock(side_effect=build), switch=Mock(side_effect=switch), wj=write,
            load_protocol=lambda: (self.protocol, self.protocol_sha), require_freeze=Mock(), verified=Mock(),
            cpus=Mock(return_value=(2, 3)), harness=Mock(return_value=object()),
            oracle=Mock(return_value=SimpleNamespace(corpus_filename=lambda n: f"n{n}.tsv")),
            expected_for=lambda protocol, n: {lane["id"]: {"oracle": lane["id"]}
                for lane in self.original.lanes(protocol) if lane["n"] == n},
            build_index=Mock(side_effect=lambda harness, binary, corpus, path, n: {
                "dir": path, "layout": {"digest": "digest-" + str(n),
                    "bytes": self.protocol["index_100k_committed_sentinel"] if n == 100000 else 1}}),
            pin=Mock(), host_record=Mock(return_value={"host_fingerprint": "sha256:" + "2" * 64}),
            readiness=Mock(return_value={"readiness_status": "READY"}),
            lanes=self.original.lanes, control_schedule=self.original.control_schedule, schedule=self.original.schedule,
            allowed=Mock(return_value=[3]), probe=Mock(return_value={"status": "clear"}),
            measure_lane=Mock(side_effect=lambda protocol, arm, binary, index, cpu, lane, expected: {"id": lane["id"], "arm": arm}),
            build_provenance=self.original.build_provenance,
            summary_control=Mock(return_value={"status": "ACQUIRED_VERIFIED"}),
            summary_campaign=Mock(return_value={"status": "ACQUIRED_VERIFIED"}),
            sf=self.original.sf, write_evidence=Mock(side_effect=self.original.write_evidence),
        )

    def directory(self, campaign):
        path = self.root / campaign
        path.mkdir()
        return path

    def test_control_binds_both_actual_builds_to_prepared_base_before_query(self):
        directory = self.directory(self.protocol["control_name"])
        result = backend._build_bound_inputs(self.runner, self.protocol, directory, self.prepared, control=True)
        self.assertEqual(set(result[-1]), {"A", "B"})
        self.assertEqual([call.args[-1] for call in self.runner.build.call_args_list], [False, False])
        self.runner.switch.assert_not_called()
        receipt = json.loads((directory / "raw/official-premeasurement-binaries.json").read_text())
        self.assertFalse(receipt["query_operations_started"])
        self.assertEqual(receipt["actual_A"]["sha256"], receipt["actual_B"]["sha256"])
        self.assertEqual(receipt["binary_manifest_digest"], self.prepared.binary_digest)
        self.runner.build_index.assert_not_called()
        self.runner.measure_lane.assert_not_called()

    def test_treatment_preserves_the_base_then_experiment_build_sequence(self):
        directory = self.directory(self.protocol["campaign_names"][0])
        result = backend._build_bound_inputs(self.runner, self.protocol, directory, self.prepared, control=False)
        self.assertEqual(set(result[-1]), {"A", "L", "P", "H"})
        self.assertEqual([item[:3] for item in self.calls if item[0] in ("build", "switch")],
            [("build", 1, False), ("switch", self.original.BASE_SHA, self.original.EXPERIMENT_SHA), ("build", 2, True)])
        self.assertEqual(result[-1]["H"]["sha256"], self.expected["B"]["sha256"])

    def test_changed_base_bytes_stop_before_the_second_build_or_any_index(self):
        self.corrupt_build = 1
        directory = self.directory(self.protocol["control_name"])
        with patch.object(backend, "legacy_runner", return_value=self.runner), self.assertRaises(BenchError) as failure:
            backend._execute_campaign(directory, directory.name, self.prepared)
        self.assertEqual(failure.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(failure.exception.field_path, "binary_manifest_digest")
        self.assertEqual(self.runner.build.call_count, 1)
        self.runner.harness.assert_not_called()
        self.runner.build_index.assert_not_called()
        self.runner.measure_lane.assert_not_called()
        self.assertFalse((directory / "raw/official-premeasurement-binaries.json").exists())

    def test_changed_experiment_bytes_stop_before_any_index_even_if_metadata_claims_expected_hash(self):
        self.corrupt_build = 2
        directory = self.directory(self.protocol["campaign_names"][0])
        with patch.object(backend, "legacy_runner", return_value=self.runner), self.assertRaises(BenchError):
            backend._execute_campaign(directory, directory.name, self.prepared)
        self.assertEqual(self.runner.build.call_count, 2)
        self.runner.harness.assert_not_called()
        self.runner.build_index.assert_not_called()
        self.runner.measure_lane.assert_not_called()

    def test_campaign_two_uses_all_original_96_slots_72_lanes_and_published_predecessors(self):
        campaign = self.protocol["campaign_names"][1]
        directory = self.directory(campaign)
        with patch.object(backend, "legacy_runner", return_value=self.runner):
            backend._execute_campaign(directory, campaign, self.prepared)
        self.runner.require_freeze.assert_called_once_with(campaign)
        self.assertEqual([call.args[1:] for call in self.runner.verified.call_args_list],
            [("control", self.protocol["control_name"]), ("four_arm", self.protocol["campaign_names"][0])])
        plan = self.original.schedule(self.protocol, campaign)
        self.assertEqual(len(plan), 96)
        self.assertEqual(self.runner.build_index.call_count, 8)
        self.assertEqual(self.runner.measure_lane.call_count, 96 * 72)
        self.assertEqual(self.runner.probe.call_count, 192)
        for entry in plan:
            slot = json.loads((directory / "raw/slots" / f"slot-{entry['slot']:02d}.json").read_text())
            self.assertEqual({key: slot[key] for key in entry}, entry)
            self.assertEqual([lane["id"] for lane in slot["lanes"]],
                [lane["id"] for lane in self.original.lanes(self.protocol)])
        self.assertTrue(self.runner.summary_campaign.call_args.args[-1])
        self.runner.summary_control.assert_not_called()
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual((manifest["slots"], manifest["lanes_per_slot"], set(manifest["arms"])), (96, 72, {"A", "L", "P", "H"}))
        seal = json.loads((directory / "raw/seal.json").read_text())
        self.assertIn("raw/official-premeasurement-binaries.json", seal["files"])

    def test_fixture_authority_cannot_reach_any_build_or_worker(self):
        freeze = official_support.make_freeze(study_id=backend.STUDY_RETAINED_KEY)
        with patch.object(backend, "legacy_runner") as runner, \
                patch.object(backend.multiprocessing, "get_context") as worker, self.assertRaises(BenchError):
            backend.acquire_retained_campaign(_open_fixture_authorization(freeze), root=self.root,
                directory=self.root / self.protocol["control_name"], campaign=self.protocol["control_name"],
                prepared=self.prepared, observed={}, official_home=self.root / "home")
        runner.assert_not_called()
        worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
