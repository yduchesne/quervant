"""Offline execution-boundary tests. No adapters, builds, services or timing run."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.errors import BenchError, BM_IDENTITY_INVALID, BM_PUBLICATION_CONFLICT, BM_UNSAFE_INPUT
from quervant_bench.evidence.provenance import repository_root
from quervant_bench.official import cross_engine_backend as backend
from quervant_bench.official.controls import assess_cross_engine_control
from quervant_bench.official.admission import pr15d_warm_lane_ids
from quervant_bench.official.authorization import _open_fixture_authorization
from quervant_bench.tests import official_support


class PreparedInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.build = self.root / "build"
        self.corpus = self.root / "corpus"
        self.build.mkdir()
        self.corpus.mkdir()
        self.actual_legacy = backend._legacy(repository_root())
        manifest = {"corpora": [{"n": n, "sha256": "a" * 64} for n in (10000, 100000)]}
        self.oracle = SimpleNamespace(
            manifest_filename=lambda: "manifest.json", corpus_filename=lambda n: f"n{n}.tsv",
            load_and_verify=lambda _path: (manifest, {}),
            canonical_json_bytes=canonical_document_bytes,
            sha256_bytes=lambda value: hashlib.sha256(value).hexdigest(),
        )
        self.legacy = SimpleNamespace(adapter_binary=self.actual_legacy.adapter_binary, oracle=self.oracle, N_VALUES=(10000, 100000))
        for name in ("manifest.json", "n10000.tsv", "n100000.tsv"):
            (self.corpus / name).write_bytes(b"fixture corpus\n")
        for engine in backend.ENGINES:
            executable = Path(self.legacy.adapter_binary(engine, str(self.build)))
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"fixture executable: never launched\n")
            executable.chmod(0o700)
            if engine == "lucene":
                jar = executable.parent.parent / "lib" / "lucene.jar"
                jar.parent.mkdir()
                jar.write_bytes(b"fixture jar: never loaded\n")
        self.patches = [patch.object(backend, "_head", return_value="a" * 40),
                        patch.object(backend, "_adapter_source_digest", return_value="sha256:" + "b" * 64),
                        patch.object(backend, "_legacy", return_value=self.legacy)]
        for mocked in self.patches:
            mocked.start()
            self.addCleanup(mocked.stop)
        self.document = {
            "schema": backend.PREPARED_SCHEMA, "source_sha": "a" * 40, "source_root": str(self.root),
            "build_root": str(self.build), "corpus_dir": str(self.corpus),
            "adapter_source_digest": "sha256:" + "b" * 64,
            "binaries": backend._binary_records(self.legacy, self.build),
            "corpus_files": backend._files(self.corpus, list(self.corpus.iterdir())),
            "corpus_manifest_digest": "sha256:" + self.oracle.sha256_bytes(canonical_document_bytes(manifest)),
            "adapter_metadata": {engine: {"build_number": 12} for engine in backend.ENGINES},
        }
        self.document["manifest_digest"] = content_digest(self.document)
        backend._write(self.build / backend.PREPARED_NAME, self.document)

    def load(self):
        return backend.load_prepared(self.build / backend.PREPARED_NAME, root=self.root)

    def test_complete_runtime_inventory_and_read_only_revalidation(self):
        prepared = self.load()
        self.assertEqual(set(prepared.binaries), set(backend.ENGINES))
        self.assertEqual(len(prepared.manifest["binaries"]["lucene"]["files"]), 2)
        before = (self.build / backend.PREPARED_NAME).read_bytes()
        self.assertEqual(backend.verify_prepared(prepared, root=self.root), prepared)
        self.assertEqual((self.build / backend.PREPARED_NAME).read_bytes(), before)

    def test_changed_jar_cannot_remain_prepared(self):
        jar = next(self.build.rglob("*.jar"))
        jar.write_bytes(b"changed jar")
        with self.assertRaises(BenchError) as failure:
            self.load()
        self.assertEqual(failure.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(failure.exception.field_path, "binary_manifest_digest")

    def test_unlisted_extra_runtime_is_rejected(self):
        jar = next(self.build.rglob("*.jar"))
        (jar.parent / "unexpected.jar").write_bytes(b"extra")
        with self.assertRaises(BenchError):
            self.load()

    def test_symlinked_runtime_is_rejected_before_any_execution(self):
        jar = next(self.build.rglob("*.jar"))
        replacement = self.root / "outside.jar"
        jar.rename(replacement)
        jar.symlink_to(replacement)
        with self.assertRaises(BenchError) as failure:
            self.load()
        self.assertEqual(failure.exception.code, BM_UNSAFE_INPUT)

    def test_numeric_alias_in_capability_metadata_is_rejected(self):
        prepared = self.load()
        metadata = copy.deepcopy(prepared.metadata)
        metadata["quervant"]["build_number"] = 12.0
        forged = replace(prepared, metadata=metadata)
        self.assertEqual(prepared, forged)
        with self.assertRaises(BenchError):
            backend.verify_prepared(forged, root=self.root)

    def test_source_and_corpus_tamper_are_rejected(self):
        with patch.object(backend, "_head", return_value="c" * 40), self.assertRaises(BenchError):
            self.load()
        (self.corpus / "n10000.tsv").write_bytes(b"changed corpus")
        with self.assertRaises(BenchError):
            self.load()

    def test_fresh_output_never_reuses_an_attempt(self):
        with self.assertRaises(BenchError) as failure:
            backend._fresh(self.build)
        self.assertEqual(failure.exception.code, BM_PUBLICATION_CONFLICT)

    def test_fixture_authorization_cannot_reach_worker_or_preparation(self):
        authorization = _open_fixture_authorization(official_support.make_freeze(study_id=backend.STUDY_CROSS_ENGINE))
        with patch.object(backend, "_run_worker") as worker, self.assertRaises(BenchError):
            backend.acquire_cross_engine_control(authorization, root=self.root, raw_root=self.root,
                prepared=self.load(), observed={}, adapter_cpu=0, controller_cpu=1)
        worker.assert_not_called()


class PreparationWrapperTests(unittest.TestCase):
    def test_worker_finishes_before_the_parent_reopens_prepared_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build, corpus = root / "build", root / "corpus"
            calls = []
            prepared = object()
            with patch.object(backend, "_head", return_value="a" * 40), \
                    patch.object(backend, "_run_owned_preparation", side_effect=lambda **kwargs: calls.append(("worker", kwargs))), \
                    patch.object(backend, "load_prepared", side_effect=lambda *args, **kwargs: (calls.append(("reload", args)), prepared)[1]), \
                    patch.object(backend, "_prepare_cross_engine_body") as body:
                actual = backend.prepare_cross_engine(root=root, build_root=build, corpus_dir=corpus)
            self.assertIs(actual, prepared)
            self.assertEqual([call[0] for call in calls], ["worker", "reload"])
            self.assertEqual(calls[0][1], {"study_id": backend.STUDY_CROSS_ENGINE, "root": root, "build_root": build, "corpus_dir": corpus})
            self.assertEqual(calls[1][1], (build / backend.PREPARED_NAME,))
            body.assert_not_called()


class RawControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        original = backend._legacy(repository_root())
        self.template = backend._template(repository_root())
        self.prepared = SimpleNamespace(corpus_dir=self.root / "corpus")
        oracle = SimpleNamespace(load_and_verify=lambda _path: ({}, {10000: [], 100000: []}),
                                 expected=lambda rows, field, term, k: {"total_hits": 0, "doc_ids": []})
        self.legacy = SimpleNamespace(oracle=oracle, lane_descriptors=original.lane_descriptors, summarize=original.summarize)
        for mock in (patch.object(backend, "verify_prepared", return_value=self.prepared),
                     patch.object(backend, "_legacy", return_value=self.legacy),
                     patch.object(backend, "_template", return_value=self.template)):
            mock.start()
            self.addCleanup(mock.stop)
        limits = {key: self.template["host_requirements"][key] for key in (
            "min_interval_ms", "max_interval_ms", "max_busy_permille", "max_median_busy_permille", "max_steal_permille", "min_intervals")}
        self.readiness = {"schema": "official-host-readiness-v1", "study_id": backend.STUDY_CROSS_ENGINE,
            "host_fingerprint": "sha256:" + "a" * 64, "adapter_cpu": 0, "controller_cpu": 1,
            "environment": "native-linux", "limits": limits, "status": "READY", "reasons": [],
            "observations": [{"elapsed_ms": 1000, "ticks": {"0": [0] * 8, "1": [0] * 8},
                "adapter_busy_permille": 0, "adapter_steal_permille": 0,
                "controller_busy_permille": 0, "controller_steal_permille": 0} for _ in range(6)]}
        slots = []
        for number in range(1, 49):
            block, position = divmod(number - 1, 4)
            slot = {"slot": number, "block": block + 1, "position": position + 1,
                "arm": self.template["schedule"]["control_order"][block][position],
                "engine": "quervant", "adapter_cpu": 0, "lanes": []}
            for lane in original.lane_descriptors():
                if lane["regime"] != "warm":
                    continue
                slot["lanes"].append({**lane, "lane_id": lane["id"], "warmups": 5,
                    "warmup_ids": [f"{lane['id']}:warmup:{i}" for i in range(5)],
                    "samples_ns": [1000] * 20, "summary_ns": original.summarize([1000] * 20),
                    "oracle_ok": True, "contention": {"pre": "clear", "post": "clear"},
                    "total_hits": 0, "doc_ids": [], "expected_total_hits": 0, "expected_doc_ids": []})
            directory = self.raw / "control" / "slots" / f"slot-{number:02d}"
            backend._write(directory / "slot.json", slot)
            for side in ("pre", "post"):
                backend._write(directory / f"readiness-{side}.json", self.readiness)
            slots.append(slot)
        self.assessment = assess_cross_engine_control(slots=slots, warm_lane_ids=pr15d_warm_lane_ids())
        backend._write(self.raw / "control" / "control.json", self.assessment)

    def verify(self):
        return backend.verify_cross_engine_control(raw_root=self.raw, prepared=self.prepared, root=self.root)

    def test_raw_48_slot_control_is_recomputed_without_measurement(self):
        self.assertEqual(self.verify(), self.assessment)

    def test_v2_persisted_control_uses_selected_template_without_prepared_executables(self):
        from quervant_bench.official import protocols
        selected = protocols.read_canonical_json(protocols.template_path(protocols.STUDY_CROSS_ENGINE, version=2))
        with patch.object(backend, "_template", return_value=selected) as registered, \
                patch.object(backend, "verify_prepared", side_effect=AssertionError("offline control cannot require binaries")):
            for environment in ("native-linux", "wsl2"):
                with self.subTest(environment=environment):
                    self._set_control_environment(environment)
                    self.assertEqual(backend._verify_persisted_cross_engine_control(
                        raw_root=self.raw, corpus_dir=self.prepared.corpus_dir, root=self.root, template=selected), self.assessment)
                    self.assertEqual(registered.call_args.kwargs["version"], 2)

    def _set_control_environment(self, environment):
        for directory in (self.raw / "control" / "slots").iterdir():
            for side in ("pre", "post"):
                path = directory / f"readiness-{side}.json"
                record = json.loads(path.read_text())
                record["environment"] = environment
                backend._write(path, record)

    def test_complete_wsl2_control_is_accepted_without_relabelling(self):
        self._set_control_environment("wsl2")
        self.assertEqual(self.verify(), self.assessment)
        for directory in (self.raw / "control" / "slots").iterdir():
            for side in ("pre", "post"):
                self.assertEqual(json.loads((directory / f"readiness-{side}.json").read_text())["environment"], "wsl2")

    def test_control_rejects_mixed_environments_even_with_identical_fingerprint_and_cpus(self):
        for baseline, replacement in (("native-linux", "wsl2"), ("wsl2", "native-linux")):
            self._set_control_environment(baseline)
            for member in ("slot-01/readiness-post.json", "slot-48/readiness-pre.json"):
                with self.subTest(baseline=baseline, member=member):
                    path = self.raw / "control" / "slots" / member
                    pristine = json.loads(path.read_text())
                    changed = copy.deepcopy(pristine)
                    changed["environment"] = replacement
                    try:
                        backend._write(path, changed)
                        with self.assertRaises(BenchError) as raised:
                            self.verify()
                        self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_IDENTITY_INVALID, "readiness"))
                    finally:
                        backend._write(path, pristine)

    def test_literal_control_selector_still_rejects_the_other_host(self):
        for selector, environment in (("native-linux", "wsl2"), ("wsl2", "native-linux")):
            with self.subTest(selector=selector, environment=environment):
                self.template["host_requirements"]["environment"] = selector
                self._set_control_environment(environment)
                with self.assertRaises(BenchError) as raised:
                    self.verify()
                self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_IDENTITY_INVALID, "readiness"))

    def test_changed_schedule_position_is_rejected(self):
        path = self.raw / "control/slots/slot-01/slot.json"
        document = json.loads(path.read_text())
        document["arm"] = "B"
        backend._write(path, document)
        with self.assertRaises(BenchError):
            self.verify()

    def test_coherent_sample_and_summary_change_cannot_preserve_old_assessment(self):
        path = self.raw / "control/slots/slot-01/slot.json"
        document = json.loads(path.read_text())
        document["lanes"][0]["samples_ns"] = [2000] * 20
        document["lanes"][0]["summary_ns"] = self.legacy.summarize([2000] * 20)
        backend._write(path, document)
        with self.assertRaises(BenchError) as failure:
            self.verify()
        self.assertEqual(failure.exception.field_path, "control")

    def test_ready_label_cannot_hide_exceeded_frozen_limits(self):
        path = self.raw / "control/slots/slot-01/readiness-pre.json"
        document = copy.deepcopy(self.readiness)
        document["observations"][0]["adapter_busy_permille"] = 999
        backend._write(path, document)
        with self.assertRaises(BenchError) as failure:
            self.verify()
        self.assertEqual(failure.exception.field_path, "readiness")

    def test_missing_slot_is_not_an_acceptable_reduced_control(self):
        path = self.raw / "control/slots/slot-48"
        for child in path.iterdir():
            child.unlink()
        path.rmdir()
        with self.assertRaises(BenchError):
            self.verify()

    def _acquisition_boundaries(self, output: Path):
        output.mkdir()
        prepared = SimpleNamespace(corpus_dir=self.prepared.corpus_dir,
            manifest_path=self.root / "prepared.json", metadata={engine: {"engine_version": version} for engine, version in
                (("quervant", "workspace"), ("tantivy", "0.22.1"), ("lucene", "9.12.3"))},
            corpus_digest="sha256:" + "a" * 64)
        freeze = SimpleNamespace(run_id="fixture-unmeasured", source_commit="a" * 40,
            profile_version=1, design_digest=content_digest(self.template))
        def readiness(root, path, adapter_cpu, controller_cpu, *, template):
            self.assertEqual(template, self.template)
            backend._write(path, self.readiness)
            return self.readiness
        return prepared, freeze, readiness

    def test_control_orchestration_uses_exact_48_frozen_slots_and_no_build_api(self):
        output = self.root / "new-control-attempt"
        prepared, freeze, readiness = self._acquisition_boundaries(output)
        calls = []
        def worker(root, request, path, adapter_cpu, controller_cpu, timeout):
            self.assertGreater(timeout, 0)
            calls.append((request["slot"], request["block"], request["position"], request["arm"]))
            source = self.raw / "control/slots" / f"slot-{request['slot']:02d}" / "slot.json"
            backend._write(path, json.loads(source.read_text()))
        with patch.object(backend, "_authorize", return_value=(freeze, prepared)), \
             patch.object(backend, "_verify_cpu_pair"), patch.object(backend, "_readiness", side_effect=readiness), \
             patch.object(backend, "_run_worker", side_effect=worker):
            assessment = backend.acquire_cross_engine_control(object(), root=self.root, raw_root=output,
                prepared=prepared, observed={}, adapter_cpu=0, controller_cpu=1)
        expected = [((block - 1) * 4 + position, block, position, arm)
            for block, order in enumerate(self.template["schedule"]["control_order"], 1)
            for position, arm in enumerate(order, 1)]
        self.assertEqual(calls, expected)
        self.assertEqual(assessment, self.assessment)
        self.assertEqual(json.loads((output / "control/execution.json").read_text())["status"], "COMPLETE")

    def test_failed_control_worker_stops_once_and_preserves_completed_slot(self):
        output = self.root / "failed-control-attempt"
        prepared, freeze, readiness = self._acquisition_boundaries(output)
        calls = []
        def worker(root, request, path, adapter_cpu, controller_cpu, timeout):
            calls.append(request["slot"])
            if request["slot"] == 2:
                raise BenchError(BM_UNSAFE_INPUT, "fixture external process failure")
            source = self.raw / "control/slots/slot-01/slot.json"
            backend._write(path, json.loads(source.read_text()))
        with patch.object(backend, "_authorize", return_value=(freeze, prepared)), \
             patch.object(backend, "_verify_cpu_pair"), patch.object(backend, "_readiness", side_effect=readiness), \
             patch.object(backend, "_run_worker", side_effect=worker), self.assertRaises(BenchError):
            backend.acquire_cross_engine_control(object(), root=self.root, raw_root=output,
                prepared=prepared, observed={}, adapter_cpu=0, controller_cpu=1)
        self.assertEqual(calls, [1, 2])
        self.assertTrue((output / "control/slots/slot-01/slot.json").is_file())
        self.assertFalse((output / "control/control.json").exists())
        self.assertEqual(json.loads((output / "control/execution.json").read_text())["status"], "STOPPED_PRESERVED")

    def test_treatment_uses_nine_original_trial_primitives_in_frozen_order(self):
        output = self.root / "new-treatment-attempt"
        prepared, freeze, readiness = self._acquisition_boundaries(output)
        order = {1: ("quervant", "tantivy", "lucene"), 2: ("tantivy", "lucene", "quervant"),
                 3: ("lucene", "quervant", "tantivy")}
        legacy = SimpleNamespace(SCHEMA_RUN="pr15d-run-v1", WORKLOAD="pr15d_v1", TRIAL_ORDER=order,
            collect_environment=lambda path: {"native_filesystem": True, "filesystem": "ext4"},
            host_fingerprint=lambda env: "a" * 64,
            preflight_adapters=lambda: {engine: {"directory": "fixture", "missing": [], "blockers": []} for engine in backend.ENGINES},
            oracle=SimpleNamespace(load_and_verify=lambda path: ({"corpora": []}, {})))
        calls = []
        def worker(root, request, path, adapter_cpu, controller_cpu, timeout):
            self.assertEqual(request["kind"], "treatment")
            calls.append((request["trial"], request["engine"]))
            backend._write(path, {"qualified": True, "trial": request["trial"], "engine": request["engine"]})
        validator = SimpleNamespace(validate_run=lambda path: {"status": "QUALIFIED", "errors": []})
        with patch.object(backend, "_authorize", return_value=(freeze, prepared)), \
             patch.object(backend, "_verify_cpu_pair"), patch.object(backend, "_readiness", side_effect=readiness), \
             patch.object(backend, "verify_cross_engine_control", return_value=self.assessment), \
             patch.object(backend, "_legacy", return_value=legacy), patch.object(backend, "_module", return_value=validator), \
             patch.object(backend, "_run_worker", side_effect=worker):
            result = backend.acquire_cross_engine_treatment(object(), root=self.root, raw_root=output,
                prepared=prepared, observed={}, adapter_cpu=0, controller_cpu=1)
        self.assertEqual(calls, [(trial, engine) for trial in range(1, 4) for engine in order[trial]])
        self.assertEqual(len(list((result / "trials").glob("*/*.json"))), 9)
        self.assertEqual(json.loads((result / "run.json").read_text())["status"], "complete")
        from quervant_bench.official.admission import _verify_engine_pins
        _verify_engine_pins(json.loads((result / "run.json").read_text())["adapters"])


if __name__ == "__main__":
    unittest.main()
