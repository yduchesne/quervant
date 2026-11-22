"""Real filesystem boundaries for preservation and closed offline projections.

Small projection/manifest fixtures below are data-only and never authenticate a
benchmark, G0, historical source or production capability.
"""
from __future__ import annotations

import copy
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.errors import (BM_EVIDENCE_UNAVAILABLE, BM_IDENTITY_INVALID,
    BM_PUBLICATION_CONFLICT, BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError)
from quervant_bench.evidence.provenance import repository_root
from quervant_bench.official import history, transport
from quervant_bench.tests import official_support as support

BASELINE = "44444444-4444-4444-8444-444444444444"
RUN = "33333333-3333-4333-8333-333333333333"
DIGEST = "sha256:" + "a" * 64
SOURCE = "a" * 40


def sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class TransportFilesystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        parent = repository_root() / "target" / "pr15i-d3-c"
        parent.mkdir(parents=True, exist_ok=True)
        self.working = Path(tempfile.mkdtemp(prefix="transport-unit-", dir=parent))
        self.addCleanup(shutil.rmtree, self.working)

    def assert_error(self, code, callable, *args, **kwargs):
        try:
            callable(*args, **kwargs)
        except BenchError as error:
            self.assertEqual(error.code, code)
            return error
        self.fail("the operation accepted invalid evidence")

    def campaign(self):
        root = self.root / transport.D3C_CONTROL_NAME
        (root / "raw").mkdir(parents=True)
        documents = {
            "raw/build-provenance.json": {"canonical_source_path": "/producer/tree/compile-source",
                "events": [{"canonical_source": "/producer/tree/compile-source", "source_sha": SOURCE, "mode": "base"}],
                "source": SOURCE, "other": {"keep": [1, 2, 3]}},
            "manifest.json": {"campaign": root.name, "source": SOURCE},
        }
        provenance = json.dumps(documents["raw/build-provenance.json"], indent=2).encode()
        (root / "raw/build-provenance.json").write_bytes(provenance)
        documents["manifest.json"]["build_provenance_sha256"] = hashlib.sha256(provenance).hexdigest()
        (root / "manifest.json").write_bytes(json.dumps(documents["manifest.json"], indent=2).encode())
        (root / "raw/samples.json").write_bytes(b'{"samples":[5,7,11],"source":"unchanged"}\n')
        members = ("manifest.json", "raw/build-provenance.json", "raw/samples.json")
        seal = {"files": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in members}, "kind": "original-seal"}
        (root / "raw/seal.json").write_bytes(json.dumps(seal, indent=2).encode())
        return root

    def test_retained_projection_changes_only_closed_fields_and_preserves_originals(self):
        original = self.campaign()
        before = {name: (original / name).read_bytes() for name in transport._walk(original)}
        working = self.working / original.name
        result = transport.project_retained_working_copy(original_campaign_root=original,
            working_campaign_root=working, replay_checkout=repository_root())
        self.assertEqual({name: (original / name).read_bytes() for name in before}, before)
        self.assertEqual((working / "raw/samples.json").read_bytes(), before["raw/samples.json"])
        old = json.loads(before["raw/build-provenance.json"])
        expected = copy.deepcopy(old)
        expected["canonical_source_path"] = str(working / "compile-source")
        expected["events"][0]["canonical_source"] = str(working / "compile-source")
        self.assertEqual(json.loads((working / "raw/build-provenance.json").read_bytes()), expected)
        self.assertEqual(len(result.relocations), 5)
        self.assertEqual({(row["path"], row["json_pointer"]) for row in result.relocations}, {
            ("raw/build-provenance.json", "/canonical_source_path"),
            ("raw/build-provenance.json", "/events/0/canonical_source"),
            ("manifest.json", "/build_provenance_sha256"),
            ("raw/seal.json", "/files/raw~1build-provenance.json"),
            ("raw/seal.json", "/files/manifest.json")})
        for row in result.relocations:
            self.assertEqual(row["original_sha256"], sha(before[row["path"]]))
            self.assertEqual(row["working_sha256"], sha((working / row["path"]).read_bytes()))
        self.assertFalse((working / "compile-source").exists())
        self.assertNotEqual(result.original_inventory_digest, result.working_inventory_digest)
        transport.validate_recorded_relocations(result.relocations, study_id=transport.STUDY_RETAINED_KEY)

    def test_projector_rejects_wrong_checkout_outside_root_and_existing_destination(self):
        original = self.campaign()
        destination = self.working / original.name
        for label, checkout, target, code in (
            ("foreign-checkout", self.root, destination, BM_IDENTITY_INVALID),
            ("outside-root", repository_root(), self.root / "outside" / original.name, BM_UNSAFE_INPUT),
        ):
            with self.subTest(label=label):
                self.assert_error(code, transport.project_retained_working_copy,
                    original_campaign_root=original, working_campaign_root=target, replay_checkout=checkout)
                self.assertFalse(target.exists())
        destination.mkdir()
        self.assert_error(BM_PUBLICATION_CONFLICT, transport.project_retained_working_copy,
            original_campaign_root=original, working_campaign_root=destination, replay_checkout=repository_root())

    def test_original_seal_failure_has_no_working_effect(self):
        original = self.campaign()
        (original / "raw/samples.json").write_bytes(b"tampered")
        target = self.working / original.name
        self.assert_error(BM_IDENTITY_INVALID, transport.project_retained_working_copy,
            original_campaign_root=original, working_campaign_root=target, replay_checkout=repository_root())
        self.assertFalse(target.exists())

    def test_projection_cleanup_owned_only_on_write_failure(self):
        original = self.campaign()
        unrelated = self.working / "unrelated"
        unrelated.write_bytes(b"keep")
        target = self.working / original.name
        with patch.object(transport, "_write_payload", side_effect=OSError("injected write failure")):
            with self.assertRaises(OSError):
                transport.project_retained_working_copy(original_campaign_root=original,
                    working_campaign_root=target, replay_checkout=repository_root())
        self.assertFalse(target.exists())
        self.assertEqual(unrelated.read_bytes(), b"keep")
        self.assertTrue(original.exists())

    def test_cross_engine_projection_only_changes_corpus_path(self):
        original = self.root / "backend"
        original.mkdir()
        run = {"corpus_dir": "/old/corpus", "run_id": RUN, "source_sha": SOURCE,
            "statistics": {"ratio": "0.7"}, "host": "original"}
        (original / "run.json").write_bytes(json.dumps(run, indent=2).encode())
        (original / "samples.json").write_bytes(b'[11,13,17]\n')
        corpus = self.working / "corpus"
        corpus.mkdir()
        result = transport.project_cross_engine_working_copy(original_run_root=original,
            working_run_root=self.working / "backend", replay_checkout=repository_root(), corpus_dir=corpus)
        self.assertEqual(json.loads((self.working / "backend/run.json").read_bytes()), {**run, "corpus_dir": str(corpus)})
        self.assertEqual((self.working / "backend/samples.json").read_bytes(), b'[11,13,17]\n')
        self.assertEqual(len(result.relocations), 1)
        self.assertEqual(result.relocations[0]["json_pointer"], "/corpus_dir")
        self.assertEqual(json.loads((original / "run.json").read_bytes()), run)

    def test_stream_copy_exact_reuse_and_immutable_conflict(self):
        source = self.root / "source"
        source.mkdir()
        (source / "data.json").write_bytes(b'{"complete":true}\n')
        observed, _ = transport._observe(source, "data.json", 1024)
        target = self.root / "target"
        transport._copy_observed(observed, target, "nested/data.json")
        before = (target / "nested/data.json").stat().st_mtime_ns
        transport._copy_observed(observed, target, "nested/data.json")
        self.assertEqual((target / "nested/data.json").stat().st_mtime_ns, before)
        (target / "nested/data.json").write_bytes(b"conflict")
        self.assert_error(BM_PUBLICATION_CONFLICT, transport._copy_observed, observed, target, "nested/data.json")
        self.assertEqual((target / "nested/data.json").read_bytes(), b"conflict")

    def test_stream_copy_rejects_changed_observation_without_partial_output(self):
        (self.root / "input").write_bytes(b"before")
        observed, _ = transport._observe(self.root, "input", 1024)
        (self.root / "input").write_bytes(b"after")
        target = self.root / "copy"
        self.assert_error(BM_IDENTITY_INVALID, transport._copy_observed, observed, target, "input")
        self.assertFalse((target / "input").exists())

    def test_preservation_refuses_links_and_special_files(self):
        source = self.root / "source"
        source.mkdir()
        (source / "plain").write_bytes(b"x")
        for mode in ("symlink", "hardlink", "fifo"):
            name = source / mode
            if mode == "symlink":
                name.symlink_to(source / "plain")
            elif mode == "hardlink":
                os.link(source / "plain", name)
            else:
                os.mkfifo(name)
            try:
                with self.subTest(mode=mode):
                    self.assert_error(BM_UNSAFE_INPUT, transport._observe, source, mode, 100)
            finally:
                name.unlink()

    def test_tar_and_zip_regular_member_copy_no_extractall(self):
        with tarfile.open(self.root / "data.tar.gz", "w:gz") as archive:
            info = tarfile.TarInfo("nested/data.json")
            payload = b'{"value":17}\n'
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        with zipfile.ZipFile(self.root / "data.zip", "w") as archive:
            archive.writestr("nested/data.json", payload)
        for name in ("data.tar.gz", "data.zip"):
            with self.subTest(name=name), patch.object(tarfile.TarFile, "extractall", side_effect=AssertionError("prohibited")), patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("prohibited")):
                destination = self.root / (name + "-copy")
                rows = transport._materialize_archive(provider_root=self.root, relative=name, destination=destination)
                self.assertEqual(rows, ({"path": "nested/data.json", "size_bytes": len(payload), "sha256": sha(payload)},))
                self.assertEqual((destination / "nested/data.json").read_bytes(), payload)

    def test_archive_traversal_and_links_reject_before_copy(self):
        for name, type_ in (("../escape", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)):
            path = self.root / "unsafe.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                info = tarfile.TarInfo(name)
                info.type = type_
                if type_ == tarfile.SYMTYPE:
                    info.linkname = "/tmp/escape"
                archive.addfile(info)
            destination = self.root / "copy"
            with self.subTest(name=name):
                self.assert_error(BM_UNSAFE_INPUT, transport._materialize_archive,
                    provider_root=self.root, relative=path.name, destination=destination)
                self.assertFalse(destination.exists())

    def test_inventory_strict_types_and_owning_bounds(self):
        ordinary = {"path": "data.json", "size_bytes": 1, "sha256": DIGEST, "role": "raw"}
        for name, mutation, code in (
            ("bool-size", {"size_bytes": True}, BM_UNSAFE_INPUT),
            ("negative", {"size_bytes": -1}, BM_UNSAFE_INPUT),
            ("extra", {"unknown": 1}, BM_SCHEMA_INVALID),
            ("unknown-role", {"role": "executable"}, BM_SCHEMA_INVALID),
            ("ordinary-bound", {"size_bytes": 64 * 1024**2 + 1}, BM_UNSAFE_INPUT),
            ("qa-check-bound", {"path": "qa/check.json", "role": "qa", "size_bytes": 65537}, BM_UNSAFE_INPUT),
            ("policy-bound", {"role": "policy-input", "size_bytes": 4 * 1024**2 + 1}, BM_UNSAFE_INPUT),
            ("archive-bound", {"path": "input.zip", "size_bytes": 4 * 1024**3 + 1}, BM_UNSAFE_INPUT),
        ):
            with self.subTest(name=name):
                self.assert_error(code, transport._validate_member_records, [{**ordinary, **mutation}])
        for rows in ([ordinary, dict(ordinary)], [ordinary, {**ordinary, "path": "DATA.JSON"}]):
            self.assert_error(BM_UNSAFE_INPUT, transport._validate_member_records, rows)
        self.assertEqual(transport._validate_member_records([ordinary]), [ordinary])

    def test_no_synthetic_or_direct_baseline_capability(self):
        with patch("quervant_bench.official.workflow._open", side_effect=AssertionError("must reject first")):
            error = self.assert_error(BM_UNSAFE_INPUT, history.open_verified_baseline_disclosures,
                operation_root=self.root, config_path=self.root / "missing", authorization=object(), admission=object())
            self.assertEqual(error.field_path, "authorization")
        self.assert_error(BM_UNSAFE_INPUT, history.require_verified_baseline_disclosures, object())
        fields = dict(zip(history._BASELINE_IDENTITIES, ("current-baseline-v2", BASELINE, transport.STUDY_CROSS_ENGINE,
            RUN, SOURCE, *([DIGEST] * 9))))
        self.assert_error(BM_UNSAFE_INPUT, history.VerifiedBaselineDisclosures, **fields,
            _operation_root=self.root, _config_path=self.root / "config", _history_inventory_path=self.root / "history",
            _authorization=None, _admission=None, _policy_inputs=None, _sentinel=object())
        self.assert_error(BM_UNSAFE_INPUT, transport.VerifiedBaselineEvidence, baseline_id=BASELINE, source_commit=SOURCE,
            source_file_set_digest=DIGEST, manifest_digest=DIGEST, evidence_commit=None, replay_checkout_identity=None,
            status="REPLAY_VERIFIED", _root=self.root, _sentinel=object())

    def test_missing_families_cannot_finalize(self):
        baseline = self.root / BASELINE
        baseline.mkdir()
        self.assertFalse(transport.baseline_ready_for_finalization(baseline_root=baseline))
        error = self.assert_error(BM_EVIDENCE_UNAVAILABLE, transport.finalize_baseline_evidence, baseline_root=baseline)
        self.assertEqual(error.field_path, "study_runs")
        self.assertFalse((baseline / "baseline-manifest.json").exists())

    def test_manifest_member_tamper_missing_and_undeclared_fail(self):
        root = self.root / "baseline"
        root.mkdir()
        (root / "member.json").write_bytes(b"{}\n")
        members = [{"path": "member.json", "size_bytes": 3, "sha256": sha(b"{}\n"), "role": "raw"}]
        manifest = {"members": members}
        transport._authenticate_members(root, manifest, manifest_present=False)
        (root / "extra").write_bytes(b"x")
        self.assert_error(BM_IDENTITY_INVALID, transport._authenticate_members, root, manifest, manifest_present=False)
        (root / "extra").unlink()
        (root / "member.json").write_bytes(b"[]\n")
        self.assert_error(BM_IDENTITY_INVALID, transport._authenticate_members, root, manifest, manifest_present=False)
        (root / "member.json").unlink()
        self.assert_error(BM_IDENTITY_INVALID, transport._authenticate_members, root, manifest, manifest_present=False)

    def test_closed_relocations_reject_new_pointer_and_conflicting_type(self):
        row = {"path": "backend/run.json", "json_pointer": "/corpus_dir", "old_value": "/old",
            "new_value": "/new", "original_sha256": DIGEST, "working_sha256": DIGEST}
        transport.validate_recorded_relocations([row], study_id=transport.STUDY_CROSS_ENGINE)
        for change in ({"json_pointer": "/source_sha"}, {"path": "different.json"}):
            self.assert_error(BM_UNSAFE_INPUT, transport.validate_recorded_relocations, [{**row, **change}], study_id=transport.STUDY_CROSS_ENGINE)
        self.assert_error(BM_SCHEMA_INVALID, transport.validate_recorded_relocations, [{**row, "old_value": 7}], study_id=transport.STUDY_CROSS_ENGINE)
        self.assert_error(BM_SCHEMA_INVALID, transport.validate_recorded_relocations, [row, row], study_id=transport.STUDY_CROSS_ENGINE)

    def test_portable_real_summary_ignores_original_provider_and_preserves_negative_observation(self):
        aggregate = repository_root() / "benchmarks/reports/pr15d/pr15d-qualified.json"
        digest = history.record_for("pr15d-aggregate", history.PR15D_RUN).digest
        archive_digest = history.record_for("pr15d-archive", history.PR15D_RUN).digest
        original_provider = self.root / "producer"
        original_provider.mkdir()
        (original_provider / "summary.json").write_bytes(aggregate.read_bytes())
        candidates = [
            {"family": "cross-engine", "input_role": "pr15d-aggregate", "path": "summary.json", "source_identity": history.PR15D_RUN, "expected_digest": digest},
            {"family": "cross-engine", "input_role": "pr15d-archive", "path": history.PR15D_RUN + ".zip", "source_identity": history.PR15D_RUN, "expected_digest": archive_digest},
        ]
        inventory = {"kind": history.INVENTORY_KIND, "schema_version": 1, "candidates": candidates}
        entries = history.build_entries(original_provider, inventory, source_root=repository_root())
        self.assertEqual([row["status"] for row in entries], ["FOUND", "UNAVAILABLE"])
        report = history.report_payload(baseline_id=BASELINE, study_id=transport.STUDY_CROSS_ENGINE,
            source_commit=SOURCE, current_raw_digest=DIGEST, entries=entries)
        baseline = self.root / "preserved"
        transport._write_payload(baseline, f"history/inventories/{transport.STUDY_CROSS_ENGINE}.json", canonical_document_bytes(inventory))
        fixed = f"history/inputs/pr15d-aggregate/{history.PR15D_RUN}/pr15d-qualified.json"
        transport._write_payload(baseline, fixed, aggregate.read_bytes())
        shutil.rmtree(original_provider)
        real = history._observe_file
        def denied(root, relative, **kwargs):
            self.assertNotEqual(Path(root), original_provider, "offline reopened original provider")
            return real(root, relative, **kwargs)
        with patch.object(history, "_observe_file", side_effect=denied):
            observed = transport._portable_history(root=baseline, study=transport.STUDY_CROSS_ENGINE,
                original_report=report, checkout=repository_root())
        self.assertEqual(observed, entries)
        self.assertEqual(len(observed[0]["normalized_rows"]), 32)
        self.assertEqual(observed[1]["status"], "UNAVAILABLE")
        (baseline / fixed).unlink()
        with self.assertRaises(BenchError):
            transport._portable_history(root=baseline, study=transport.STUDY_CROSS_ENGINE,
                original_report=report, checkout=repository_root())

    def test_conflicting_fixed_destination_rejects_without_overwrite(self):
        (self.root / "one").write_bytes(b"one")
        (self.root / "two").write_bytes(b"two")
        records = {}
        transport._add_export(records, self.root, "one", "history/fixed.json", "history")
        self.assert_error(BM_IDENTITY_INVALID, transport._add_export, records, self.root, "two", "history/fixed.json", "history")
        self.assertEqual(records["history/fixed.json"].observation.digest, sha(b"one"))

    def test_external_qa_restoration_reads_all_66_original_members_and_cleans_up(self):
        from quervant_bench.official import qa_evidence
        qa = support.qa_evidence_sandbox(self.root / "external-original-qa")
        prefix = "studies/test/run"
        baseline = self.working / "qa-baseline"
        copied = baseline / prefix / "qa/records"
        shutil.copytree(qa.root, copied)
        for gate, document in (("framework-qa", qa.framework_summary), ("source-qa", qa.source_summary)):
            support.write_json(baseline / prefix / ("qa/summaries/" + gate + "-evidence.json"), document)
        raw, output = baseline / "raw", baseline / "qualified"
        raw.mkdir()
        output.mkdir()
        self.assert_error(BM_UNSAFE_INPUT, qa_evidence.verify_executed_qa_evidence,
            qa_evidence_root=copied, framework_summary=qa.framework_summary, source_summary=qa.source_summary,
            freeze=qa.freeze, output_root=output, raw_root=raw)
        directories = []
        real_mkdtemp = tempfile.mkdtemp
        def temporary_directory(*args, **kwargs):
            value = real_mkdtemp(*args, **kwargs)
            directories.append(Path(value))
            return value
        with patch.object(transport.tempfile, "mkdtemp", side_effect=temporary_directory), \
             patch("quervant_bench.official.authorization.open_verified_official_authorization", side_effect=AssertionError("offline must not issue live G0")):
            transport._restore_qa(baseline_root=baseline, prefix=prefix, freeze=qa.freeze,
                output_root=output, raw_root=raw)
        self.assertEqual(len(transport._walk(copied)), 66)
        self.assertEqual(len(directories), 1)
        self.assertFalse(directories[0].exists())
        member = copied / qa_evidence.check_log_relative("framework-qa", "benchmark-scripts")
        original = member.read_bytes()
        member.write_bytes(original + b"tamper\n")
        with patch.object(transport.tempfile, "mkdtemp", side_effect=temporary_directory):
            self.assert_error(BM_IDENTITY_INVALID, transport._restore_qa,
                baseline_root=baseline, prefix=prefix, freeze=qa.freeze, output_root=output, raw_root=raw)
        self.assertFalse(directories[-1].exists())

    def test_public_safe_export_rejects_fixed_credentials_without_modifying_originals(self):
        for label, payload in (("assignment", b"AWS_SECRET_ACCESS_KEY=unredacted-value\n"),
            ("header", b"Authorization: Bearer unredacted-value\n"),
            ("json-nested", b'{"nested":{"access_token":{"value":"unredacted"}}}\n'),
            ("boundary", b"x" * (1_048_576 - 7) + b"\nGH_TOKEN=unredacted-value\n")):
            path = self.root / (label + (".json" if label == "json-nested" else ".log"))
            path.write_bytes(payload)
            observed, _ = transport._observe(self.root, path.name, 8 * 1_048_576)
            with self.subTest(label=label):
                error = self.assert_error(BM_UNSAFE_INPUT, transport._require_public_safe_member, observed)
                self.assertEqual(error.reference, path.name)
                self.assertEqual(path.read_bytes(), payload)
        for value in ("[REDACTED]", "<redacted>", "***", "", None):
            with self.subTest(redacted=value):
                payload = canonical_document_bytes({"secret_key": value, "performance": {"ratio": 1.2}})
                path = self.root / "safe.json"
                path.write_bytes(payload)
                observed, _ = transport._observe(self.root, path.name, 1024)
                transport._require_public_safe_member(observed)
                self.assertEqual(path.read_bytes(), payload)

    def test_original_prepared_nested_types_fail_without_opening_producer_paths(self):
        from quervant_bench.official.cross_engine_backend import PREPARED_SCHEMA
        from quervant_bench.official.retained_backend import KIND as RETAINED_KIND
        from quervant_bench.official.protocols import D3C_BASE_COMMIT, D3C_EXPERIMENT_COMMIT
        cross = {"schema": PREPARED_SCHEMA, "source_sha": SOURCE, "source_root": "/producer/source",
            "build_root": "/producer/build", "corpus_dir": "/producer/corpus", "adapter_source_digest": DIGEST,
            "binaries": {engine: {"entrypoint": engine, "files": [{"path": engine, "size_bytes": 9, "sha256": DIGEST}]}
                for engine in ("quervant", "tantivy", "lucene")},
            "corpus_files": [{"path": "corpus.tsv", "size_bytes": 1, "sha256": DIGEST}],
            "corpus_manifest_digest": DIGEST, "adapter_metadata": {engine: {} for engine in ("quervant", "tantivy", "lucene")},
            "manifest_digest": DIGEST}
        retained = {"schema": RETAINED_KIND, "source_root": "/producer/source", "corpus_dir": "/producer/corpus",
            "protocol_digest": DIGEST, "corpus_digest": DIGEST, "binaries": {
                arm: {"binary": "/producer/bin/" + arm, "sha256": hex_ * 64, "bytes": 12,
                    "argv": ["cargo", "build"], "feature": arm == "B", "source_sha": source}
                for arm, hex_, source in (("A", "a", D3C_BASE_COMMIT), ("B", "b", D3C_EXPERIMENT_COMMIT))}}
        with patch("builtins.open", side_effect=AssertionError("data-only validator opened a producer location")):
            for study, valid in ((transport.STUDY_CROSS_ENGINE, cross), (transport.STUDY_RETAINED_KEY, retained)):
                transport._validate_original_prepared_data(valid, study=study)
                for label, value in (("list", []), ("bool", True), ("string", "bin")):
                    with self.subTest(study=study, label=label):
                        self.assert_error(BM_SCHEMA_INVALID, transport._validate_original_prepared_data,
                            {**valid, "binaries": value}, study=study)
                bad = copy.deepcopy(valid)
                key = "quervant" if study == transport.STUDY_CROSS_ENGINE else "A"
                bad["binaries"][key] = []
                self.assert_error(BM_SCHEMA_INVALID, transport._validate_original_prepared_data, bad, study=study)
            for field, value in (("files", {}), ("files", [None])):
                bad = copy.deepcopy(cross)
                bad["binaries"]["quervant"][field] = value
                self.assert_error(BM_SCHEMA_INVALID, transport._validate_original_prepared_data, bad, study=transport.STUDY_CROSS_ENGINE)
            for field, value in (("bytes", True), ("argv", "cargo build"), ("sha256", [])):
                bad = copy.deepcopy(retained)
                bad["binaries"]["A"][field] = value
                self.assert_error(BM_SCHEMA_INVALID, transport._validate_original_prepared_data, bad, study=transport.STUDY_RETAINED_KEY)

    def test_public_offline_dispatch_namespace_and_before_effect_guards(self):
        from quervant_bench.config.errors import BM_FILE_MISSING, BM_USAGE
        from quervant_bench.migrations import offline
        from quervant_bench.tests.test_retained_key_offline_cli import invoke, error_code
        workspace = self.root / "offline-workspace"
        baseline = workspace / "baselines" / BASELINE
        baseline.mkdir(parents=True)
        forbidden = ("quervant_bench.official.operation_config.load_operation_config",
            "quervant_bench.official.authorization.open_verified_official_authorization",
            "quervant_bench.official.workflow.run_official",
            "quervant_bench.official.cross_engine_backend.acquire_cross_engine_treatment")
        with ExitStack() as guards:
            for name in forbidden:
                guards.enter_context(patch(name, side_effect=AssertionError("offline invoked a live owner")))
            status, stdout, stderr = invoke(["verify", "--run", BASELINE, "--offline"], workspace)
            self.assertNotEqual(status, 0)
            self.assertEqual((stdout, error_code(stderr)), ("", BM_FILE_MISSING))
            for verb in ("validate", "analyze", "accept"):
                with self.subTest(verb=verb), patch.object(transport, "open_verified_baseline_evidence", side_effect=AssertionError("verb guard too late")):
                    status, stdout, stderr = invoke([verb, "--run", BASELINE, "--offline"], workspace)
                    self.assertNotEqual(status, 0)
                    self.assertEqual((stdout, error_code(stderr)), ("", BM_USAGE))
            with patch.object(offline, "dispatch_stage", side_effect=AssertionError("config guard too late")):
                status, stdout, stderr = invoke(["verify", "--run", BASELINE, "--offline", "--config", "/producer/config.json"], workspace)
                self.assertNotEqual(status, 0)
                self.assertEqual((stdout, error_code(stderr)), ("", BM_USAGE))
            synthetic = workspace / "qualified/test-experiment" / BASELINE
            synthetic.mkdir(parents=True)
            with patch.object(transport, "open_verified_baseline_evidence", side_effect=AssertionError("ambiguous namespace selected")):
                status, stdout, stderr = invoke(["verify", "--run", BASELINE, "--offline"], workspace)
                self.assertNotEqual(status, 0)
                self.assertEqual((stdout, error_code(stderr)), ("", BM_IDENTITY_INVALID))
            shutil.rmtree(workspace / "qualified")
            baseline.rmdir()
            baseline.symlink_to(self.root)
            status, stdout, stderr = invoke(["report", "--run", BASELINE, "--offline"], workspace)
            self.assertNotEqual(status, 0)
            self.assertEqual((stdout, error_code(stderr)), ("", BM_UNSAFE_INPUT))
            baseline.unlink()
            baseline.mkdir()
            primary = BenchError(BM_IDENTITY_INVALID, "explicit replay rejection", field_path="manifest")
            with patch.object(transport, "replay_baseline_evidence", side_effect=primary) as replay:
                status, stdout, stderr = invoke(["verify", "--run", BASELINE, "--offline"], workspace)
                self.assertEqual((stdout, error_code(stderr)), ("", BM_IDENTITY_INVALID))
                replay.assert_called_once_with(baseline_root=baseline)
            with patch.object(transport, "open_verified_baseline_evidence", side_effect=primary) as reopened, \
                 patch.object(transport, "_json", side_effect=AssertionError("report read before independent replay")):
                status, stdout, stderr = invoke(["report", "--run", BASELINE, "--offline"], workspace)
                self.assertEqual((stdout, error_code(stderr)), ("", BM_IDENTITY_INVALID))
                reopened.assert_called_once_with(baseline_root=baseline)


class TransportEndToEndTests(unittest.TestCase):
    """Generated raw data traverse real preservation and independent replay.

    The external prepared-binary/host observations are test data. No timing,
    historical authentication, real operator approval or complete BM-09 result
    is claimed by these successful production-boundary regression exercises.
    """

    def test_cross_engine_checkpoint_finalization_and_complete_study_replay(self):
        self._exercise_family("cross")

    def test_retained_checkpoint_finalization_and_complete_study_replay(self):
        self._exercise_family("retained")

    def _exercise_family(self, family):
        from quervant_bench.official import admission, analysis, coordinator, protocols, verification, workflow
        from quervant_bench.official.cross_engine_backend import PREPARED_SCHEMA, _binary_digest
        from quervant_bench.official.operation_config import OperationConfig
        from quervant_bench.qualification.identity import compute_source_set_digest, source_roster
        from quervant_bench.official import runtime_freeze
        from quervant_bench.official.retained_backend import KIND as RETAINED_PREPARED_KIND
        from quervant_bench.tests.test_official_current_baseline import LiveDisclosureFactoryTests
        from quervant_bench.tests.test_official_admission import CurrentBaselineProductionAdmissionTests

        temporary = tempfile.TemporaryDirectory(prefix="transport-end-to-end-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        builder = type("TransportFixtureBuilder", (LiveDisclosureFactoryTests,), {})
        builder.root = root
        builder.addClassCleanup = staticmethod(self.addCleanup)
        case = self._new_case(root, family, builder)
        study = case.template["study_id"]
        checkout = root / "ordinary-checkout"
        subprocess.run(["git", "clone", "--shared", "--quiet", str(repository_root()), str(checkout)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(checkout), "switch", "-c", "transport-test"], check=True, capture_output=True)
        evidence = checkout / "benchmark-results/baselines" / case.seed_freeze.baseline_id
        source = transport._git(repository_root(), "rev-parse", "HEAD")
        tree = transport._git(repository_root(), "rev-parse", source + "^{tree}")
        source_digest = compute_source_set_digest(repository_root())
        qa = support.qa_evidence_sandbox(root / "complete-qa", source_commit=source, study_id=study)
        if family == "retained":
            support.make_corpus(case.prepared.corpus_dir)
        corpus_root = case.prepared.corpus_dir
        oracle = admission.load_pr15d_oracle()
        corpus_manifest, _rows = oracle.load_and_verify(str(corpus_root))
        corpus_digest = "sha256:" + oracle.sha256_bytes(oracle.canonical_json_bytes(corpus_manifest))
        if family == "cross":
            binaries = {engine: {"entrypoint": engine, "files": [{"path": engine, "size_bytes": 9,
                "sha256": sha(b"TEST ONLY")}]} for engine in admission.PR15D_ENGINES}
            binary_digest = _binary_digest(binaries)
            prepared_document = {"schema": PREPARED_SCHEMA, "source_sha": source,
                "source_root": str(repository_root()), "build_root": str(root / "test-only-build"),
                "corpus_dir": str(corpus_root), "adapter_source_digest": admission._adapter_source_digest(repository_root()),
                "binaries": binaries, "corpus_files": sorted([
                    *[{"path": row["path"], "size_bytes": row["bytes"], "sha256": "sha256:" + row["sha256"]} for row in corpus_manifest["corpora"]],
                    {"path": oracle.manifest_filename(), "size_bytes": (corpus_root / oracle.manifest_filename()).stat().st_size,
                     "sha256": sha((corpus_root / oracle.manifest_filename()).read_bytes())}], key=lambda row: row["path"]),
                "corpus_manifest_digest": corpus_digest, "adapter_metadata": case.fixture.run_json["adapters"]}
            prepared_document["manifest_digest"] = content_digest(prepared_document)
            case.prepared.binary_digest = binary_digest
        else:
            binaries = {arm: {**item, "binary": str(root / "test-only-build" / arm),
                "argv": ["cargo", "build"], "feature": arm == "B"}
                for arm, item in case.prepared.manifest["binaries"].items()}
            binary_digest = content_digest({"kind": "official-retained-key-binaries", "schema_version": 1, "binaries": binaries})
            prepared_document = {"schema": RETAINED_PREPARED_KIND, "source_root": str(repository_root()),
                "corpus_dir": str(corpus_root), "protocol_digest": protocols.D3C_PROTOCOL_RAW_SHA256,
                "corpus_digest": corpus_digest, "binaries": binaries}
            case.prepared = replace(case.prepared, manifest=prepared_document, binary_digest=binary_digest)
        case.prepared_bytes = canonical_document_bytes(prepared_document)
        case.prepared_path.write_bytes(case.prepared_bytes)
        schedule = case.template["schedule"]
        freeze = replace(case.seed_freeze, source_commit=source, source_file_set_digest=source_digest,
            source_tree_sha=content_digest({"kind": "official-git-tree", "schema_version": 1, "git_tree": tree}),
            adapter_source_manifest_digest=admission._adapter_source_digest(repository_root()),
            binary_manifest_digest=binary_digest, corpus_manifest_digest=corpus_digest,
            control_schedule_digest=content_digest({key: value for key, value in schedule.items() if key.startswith("control_")}),
            treatment_schedule_digest=content_digest({key: value for key, value in schedule.items() if not key.startswith("control_")}),
            qa_framework_digest=content_digest(qa.framework_summary), qa_source_digest=content_digest(qa.source_summary),
            preservation_root_identity=str(evidence))
        if family == "retained":
            receipt = {"schema": "pr15i-d3c-freeze-v1", "protocol_sha256": runtime_freeze.PROTOCOL_SHA256,
                "control_name": protocols.D3C_CONTROL_NAME, "campaign_names": list(protocols.D3C_CAMPAIGN_NAMES),
                "t6_commit": source, "tooling_manifest_sha256": support.verifier_digest("benchmarks/pr15i_d3_c/tooling_manifest.json").removeprefix("sha256:"),
                "protected_files": {name: support.verifier_digest(name).removeprefix("sha256:")
                    for name in sorted(set(source_roster(repository_root())) | set(runtime_freeze.EXTRA_PROTECTED))},
                "receipt_origin": transport.PROFILE}
            backend_receipt = case.directory.parent / "owned-runtime-backend.json"
            support.write_json(backend_receipt, receipt)
            # This external preparation-path substitution avoids overwriting the
            # fixed production receipt belonging to another operation.
            backend_relative = backend_receipt.relative_to(repository_root()).as_posix()
            runtime = {"kind": "official-current-runtime-freeze", "schema_version": 2, "origin": "current",
                "baseline_id": freeze.baseline_id, "study_id": study, "source_commit": source,
                "source_tree_sha": freeze.source_tree_sha, "source_file_set_digest": source_digest,
                "design_digest": freeze.design_digest, "backend_protocol_digest": freeze.backend_protocol_digest,
                "backend_receipt_digest": sha(backend_receipt.read_bytes()), "prepared_manifest_digest": sha(case.prepared_bytes),
                "binary_manifest_digest": binary_digest, "corpus_manifest_digest": corpus_digest,
                "host_preflight_digest": freeze.host_preflight_digest, "adapter_cpu": 0, "controller_cpu": 1,
                "control_schedule_digest": freeze.control_schedule_digest, "treatment_schedule_digest": freeze.treatment_schedule_digest,
                "approved_output_root_identity": freeze.approved_output_root_identity}
            case.runtime_bytes = canonical_document_bytes(runtime)
            case.runtime_path.write_bytes(case.runtime_bytes)
            case.runtime_digest = sha(case.runtime_bytes)
            freeze = replace(freeze, runtime_freeze_digest=case.runtime_digest)
        case.authorization, case.observed = CurrentBaselineProductionAdmissionTests._authorize(freeze, root / "complete-g0")
        case.fixture = replace(case.fixture, freeze=case.authorization.freeze,
            qa_evidence_root=qa.root, framework_qa=qa.framework_summary, source_qa=qa.source_summary)

        def change_source(document):
            if isinstance(document, dict):
                return {key: source if key == "source_sha" else change_source(value) for key, value in document.items()}
            if isinstance(document, list):
                return [change_source(value) for value in document]
            return document

        if family == "cross":
            for relative in admission.cross_engine_member_paths(case.fixture.raw_root):
                if relative.startswith("backend/") and relative.endswith(".json"):
                    support.write_json(case.fixture.raw_root / relative,
                        change_source(support.read_json(case.fixture.raw_root / relative)))
        else:
            self._publish_retained_test_archives(case)
        case.config.update(authorization_path=str(case.authorization.authorization_path),
            approval_source_root=str(case.authorization._approval_source_root),
            qa_evidence_root=str(qa.root))
        case.config["baseline"]["evidence_root"] = str(evidence)
        support.write_json(case.config_path, case.config)
        support.write_json(case.directory / "framework-qa.json", qa.framework_summary)
        support.write_json(case.directory / "source-qa.json", qa.source_summary)
        for name in ("history-report.json", "relative-effects.json"):
            (case.directory / name).unlink(missing_ok=True)
        with builder._environment(case) as environment:
            if family == "retained":
                environment.enter_context(patch.object(runtime_freeze, "BACKEND_RECEIPT", backend_relative))
            operation = workflow._open(OperationConfig(case.config), case.template, case.directory)
            admitted = workflow._admit(operation)
            derived, policy = analysis.analyze_official_study(admitted=admitted.record, template=case.template)
            assessment = verification.verify_official_study(admitted=admitted.record, admission=admitted,
                authorization=case.authorization, analysis=derived, policy=policy, template=case.template,
                source_root=repository_root(), observed=case.observed)
            for name, document in (("operation.json", workflow._operation_record(operation)),
                ("observed-identities.json", case.observed), ("admission-index.json", admitted.record.admission_index),
                ("analysis.json", derived), ("policy.json", policy), ("verification-assessment.json", assessment)):
                support.write_json(case.directory / name, document)
            context = history.write_baseline_disclosures(operation_root=case.directory, config_path=case.config_path,
                authorization=case.authorization, admission=admitted)
            result = coordinator.qualify_official_study(authorization=case.authorization, template=case.template,
                admitted=admitted, framework_qa=qa.framework_summary, source_qa=qa.source_summary,
                output_base=case.output, qa_evidence_root=qa.root, source_root=repository_root(),
                observed=case.observed, publish=True, baseline_context=context)
            self.assertFalse(result.fixture_only)
            self.assertEqual(support.read_json(result.output_directory / "verification-assessment.json")["status"], "VERIFIED_CURRENT_BASELINE")
            # Early readiness failure still preserves the fixed originals with
            # no campaign bytes, and its STOPPED checkpoint is never overwritten.
            absent_raw = case.directory.with_name(case.directory.name + "-saved-raw")
            case.fixture.raw_root.rename(absent_raw)
            try:
                stopped = transport.preserve_baseline_checkpoint(config_path=case.config_path,
                    operation_root=case.directory, unit="control" if family == "cross" else protocols.D3C_CONTROL_NAME, status="STOPPED")
                self.assertFalse(any("/raw/" in row["path"] for row in stopped["members"]))
            finally:
                absent_raw.rename(case.fixture.raw_root)
            units = ("control", "treatment") if family == "cross" else (protocols.D3C_CONTROL_NAME, *protocols.D3C_CAMPAIGN_NAMES)
            for unit in (*units, "qualification"):
                transport.preserve_baseline_checkpoint(config_path=case.config_path, operation_root=case.directory,
                    unit=unit, baseline_context=context if unit == "qualification" else None)
        self.assertFalse(transport.baseline_ready_for_finalization(baseline_root=evidence))
        preserved = transport.finalize_baseline_evidence(baseline_root=evidence, status="STOPPED")
        self.assertEqual(preserved.status, "PRESERVED")
        manifest = preserved.document
        self.assertEqual(manifest["study_runs"][study]["status"], "COMPLETE")
        transport._require_checkpoint_graph(evidence, manifest)
        parent = repository_root() / "target/pr15i-d3-c"
        parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix="transport-replay-integration-", dir=parent))
        self.addCleanup(shutil.rmtree, scratch)
        before = {row["path"]: transport._observe(evidence, row["path"], transport._member_limit(row["path"], row["role"]))[0].digest
            for row in manifest["members"]}
        replayed = transport._replay_study(root=evidence, manifest=manifest, study=study,
            checkout=repository_root(), scratch=scratch)
        self.assertEqual(replayed["original_raw_digest"], admitted.raw_series_root_digest)
        self.assertEqual(len(replayed["relocations"]), 1 if family == "cross" else 22)
        self.assertNotEqual(replayed["working_raw_digest"], replayed["original_raw_digest"])
        self.assertEqual({row["path"]: transport._observe(evidence, row["path"], transport._member_limit(row["path"], row["role"]))[0].digest
            for row in manifest["members"]}, before)
        # Terminal reuse is read-only and requires exactly the original inputs.
        unit = units[0]
        with builder._environment(case) as environment:
            if family == "retained":
                environment.enter_context(patch.object(runtime_freeze, "BACKEND_RECEIPT", backend_relative))
            reused = transport.preserve_baseline_checkpoint(config_path=case.config_path,
                operation_root=case.directory, unit=unit)
            self.assertEqual((reused["unit"], reused["status"]), (unit, "COMPLETE"))
            relative = "control/control.json" if family == "cross" else unit + "/authorization.json"
            raw_member = case.fixture.raw_root / relative
            saved = raw_member.read_bytes()
            raw_member.write_bytes(saved + b" ")
            try:
                with self.assertRaises(BenchError) as conflict:
                    transport.preserve_baseline_checkpoint(config_path=case.config_path,
                        operation_root=case.directory, unit=unit)
                self.assertEqual(conflict.exception.code, BM_PUBLICATION_CONFLICT)
            finally:
                raw_member.write_bytes(saved)
        self.assertEqual({row["path"]: transport._observe(evidence, row["path"], transport._member_limit(row["path"], row["role"]))[0].digest
            for row in manifest["members"]}, before)
        changed = copy.deepcopy(manifest)
        changed["design_digests"][study] = DIGEST
        with self.assertRaises(BenchError) as graph:
            transport._require_checkpoint_graph(evidence, changed)
        self.assertEqual((graph.exception.code, graph.exception.field_path), (BM_IDENTITY_INVALID, "design_digests"))
        for value in ([], {}, True):
            with self.subTest(checkpoint_item=value), self.assertRaises(BenchError) as malformed:
                transport._validate_manifest({**manifest, "checkpoints": [value]})
            self.assertEqual(malformed.exception.code, BM_SCHEMA_INVALID)
        # The actual offline original loader rejects malformed nested prepared
        # data and well-typed wrong pins before any working replay output.
        prefix = f"studies/{study}/{case.authorization.run_id}"
        prepared_original = evidence / prefix / "provenance/prepared.json"
        original_prepared_bytes = prepared_original.read_bytes()
        for label, mutation, code, field in (
            ("nested-type", {"binaries": []}, BM_SCHEMA_INVALID, "binaries"),
            ("corpus-pin", {"corpus_manifest_digest" if family == "cross" else "corpus_digest": DIGEST}, BM_IDENTITY_INVALID, "corpus_manifest_digest"),
        ):
            changed_prepared = {**prepared_document, **mutation}
            if family == "cross":
                changed_prepared["manifest_digest"] = content_digest({key: value for key, value in changed_prepared.items() if key != "manifest_digest"})
            prepared_original.write_bytes(canonical_document_bytes(changed_prepared))
            try:
                with self.subTest(label=label), self.assertRaises(BenchError) as malformed:
                    transport._plain_original_freeze(root=evidence, prefix=prefix, manifest=manifest, checkout=repository_root())
                self.assertEqual((malformed.exception.code, malformed.exception.field_path), (code, field))
            finally:
                prepared_original.write_bytes(original_prepared_bytes)
        # A single completed family cannot be promoted to whole-baseline replay.
        with self.assertRaises(BenchError) as stopped:
            transport.open_verified_baseline_evidence(baseline_root=evidence)
        self.assertEqual((stopped.exception.code, stopped.exception.field_path), (BM_EVIDENCE_UNAVAILABLE, "study_runs"))

    @staticmethod
    def _publish_retained_test_archives(case):
        from quervant_bench.official.acquisition import D3C_EVIDENCE_RELATIVE
        from quervant_bench.official.admission import _load_module

        # Use the frozen publisher's own member selection: it excludes
        # build/indexes/corpus/compile-source and keeps the sealed evidence
        # members (including raw/seal.json and verification.json), which is
        # exactly what the replay reader re-derives from the raw campaign.
        publisher = _load_module("test_only_frozen_d3c_publisher", "benchmarks/pr15i_d3_c/run.py")
        destination = case.directory / "home/.local/share/quervant" / D3C_EVIDENCE_RELATIVE
        destination.mkdir(parents=True)
        for campaign in (transport.D3C_CONTROL_NAME, *transport.D3C_CAMPAIGN_NAMES):
            raw = case.fixture.raw_root / campaign
            archive_path = destination / (campaign + ".tar.gz")
            paths = publisher.archive_members(str(raw))
            with tarfile.open(archive_path, "w:gz") as archive:
                for name in paths:
                    payload = (raw / name).read_bytes()
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            support.write_json(archive_path.with_name(archive_path.name + ".sha256"), {
                "schema": "pr15i-d3c-archive-v1", "campaign": campaign,
                "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                "member_count": len(paths), "members": {name: hashlib.sha256((raw / name).read_bytes()).hexdigest() for name in paths}})

    def _new_case(self, root, family, builder):
        """Build only generated input bytes; every authority is issued later.

        This avoids deriving a throwaway full retained result before the actual
        test pins its Git/corpus/runtime identities and runs the owning chain.
        """
        from quervant_bench.official import analysis, protocols
        from quervant_bench.official.retained_backend import PreparedRetainedKey
        from quervant_bench.tests.test_official_admission import CurrentBaselineProductionAdmissionTests
        external = root / family
        external.mkdir()
        run = RUN
        if family == "retained":
            parent = repository_root() / "target/pr15i-d3-c"
            parent.mkdir(parents=True, exist_ok=True)
            owned = tempfile.TemporaryDirectory(prefix="transport-generated-retained-", dir=parent)
            self.addCleanup(owned.cleanup)
            directory = Path(owned.name) / run
            fixture = support.make_retained_key_fixture(directory, run_id=run)
            CurrentBaselineProductionAdmissionTests._complete_retained_fixture(fixture)
            qa_root = external / "original-qa"
            shutil.move(str(fixture.qa_evidence_root), qa_root)
            fixture = replace(fixture, qa_evidence_root=qa_root)
            corpus = external / "corpus"
            corpus.mkdir()
        else:
            directory = external / "runs" / run
            fixture = support.make_cross_engine_fixture(directory, run_id=run)
            corpus = fixture.corpus_root
        template = protocols.read_canonical_json(protocols.template_path(fixture.freeze.study_id, version=2))
        if family == "cross":
            fixture = replace(fixture, control=builder._complete_cross_control(fixture, template))
        output = external / "qualified"
        output.mkdir()
        host = {"kind": "official-host-preflight", "schema_version": 1,
            "capabilities": {"environment": "wsl2"}, "adapter_cpu": 0, "controller_cpu": 1}
        seed_freeze = replace(fixture.freeze, profile_version=2, design_digest=content_digest(template),
            acceptance_profile=transport.PROFILE, baseline_id=BASELINE,
            preservation_root_identity=str(root / "benchmark-results/baselines" / BASELINE),
            runtime_freeze_digest=DIGEST if family == "retained" else None, host_preflight_digest=content_digest(host),
            approved_output_root_identity=str(output),
            policy_digest=analysis.policy_profile_digest(template["study_id"], template["policy"]["policy_chain"]))
        prepared_path, runtime_path = external / "prepared.json", external / "runtime.json"
        if family == "cross":
            prepared = SimpleNamespace(manifest_path=prepared_path, corpus_dir=corpus, binary_digest=DIGEST)
        else:
            manifest = support.read_json(fixture.raw_root / transport.D3C_CAMPAIGN_NAMES[0] / "manifest.json")
            binaries = {label: {"sha256": manifest["arms"][arm]["binary_sha256"], "bytes": manifest["arms"][arm]["binary_bytes"],
                "source_sha": manifest["arms"][arm]["source_sha"]} for label, arm in (("A", "A"), ("B", "L"))}
            prepared = PreparedRetainedKey(prepared_path, repository_root(), corpus, {"binaries": binaries}, DIGEST)
        inventory = external / "history/inventory.json"
        candidates = []
        if family == "cross":
            aggregate = inventory.parent / "pr15d-qualified.json"
            aggregate.parent.mkdir()
            shutil.copyfile(repository_root() / "benchmarks/reports/pr15d/pr15d-qualified.json", aggregate)
            candidates.append({"family": "cross-engine", "input_role": "pr15d-aggregate", "path": aggregate.name,
                "source_identity": history.PR15D_AGGREGATE_RUN, "expected_digest": None})
        support.write_json(inventory, {"kind": history.INVENTORY_KIND, "schema_version": 1, "candidates": candidates})
        config = {"kind": "official-operation-config", "schema_version": 2, "source_root": str(repository_root()),
            "workspace": str(directory.parent), "output_base": str(output),
            "authorization_path": str(external / "pending-g0.json"), "approval_source_root": str(external / "pending-approval"),
            "approval_source_identity": "test-only-v2", "prepared_manifest": str(prepared_path), "corpus_dir": str(corpus),
            "framework_qa": str(directory / "framework-qa.json"), "source_qa": str(directory / "source-qa.json"),
            "qa_evidence_root": str(fixture.qa_evidence_root), "adapter_cpu": 0, "controller_cpu": 1, "policy_inputs": None,
            "acceptance_profile": transport.PROFILE, "baseline": {"baseline_id": BASELINE,
                "evidence_root": seed_freeze.preservation_root_identity, "history_inventory": str(inventory),
                "runtime_freeze_path": str(runtime_path) if family == "retained" else None}}
        support.write_json(directory / "host-preflight.json", host)
        return SimpleNamespace(family=family, external=external, directory=directory, fixture=fixture, template=template,
            seed_freeze=seed_freeze, prepared=prepared, prepared_path=prepared_path,
            runtime_path=runtime_path, runtime_bytes=b"", runtime_digest=DIGEST,
            host=host, config=config, config_path=external / "operation-config.json", output=output, inventory=inventory)


class TransportGitIdentityTests(unittest.TestCase):
    """Real Git C→D source/member boundaries, without benchmark authentication.

    These data-only manifests exercise the source-link owner directly. No G0,
    raw-result replay, timing or complete baseline capability is fabricated.
    """

    def setUp(self):
        from quervant_bench.official.historical import FROZEN_LEGACY_PATHS
        from quervant_bench.qualification.identity import (
            EXTRA_SOURCE_FILES, SCHEMA_DIRECTORY, SOURCE_DIRECTORIES,
            compute_source_set_digest, source_roster,
        )

        temporary = tempfile.TemporaryDirectory(prefix="transport-git-boundary-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / "ordinary"
        self.checkout.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Transport boundary test")
        self.git("config", "user.email", "transport-boundary@example.invalid")
        (self.checkout / ".gitignore").write_text("target/\n__pycache__/\n")
        for relative in SOURCE_DIRECTORIES:
            directory = self.checkout / relative
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "__init__.py").write_text('"""Git source identity fixture."""\n')
        schemas = self.checkout / SCHEMA_DIRECTORY
        schemas.mkdir(parents=True)
        (schemas / "fixture.json").write_bytes(b"{}\n")
        for relative in sorted(set(EXTRA_SOURCE_FILES) | set(FROZEN_LEGACY_PATHS)):
            destination = self.checkout / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(support.REPO_ROOT / relative, destination)
        self.commit("measured source C")
        self.source_commit = self.git("rev-parse", "HEAD")
        self.branch = self.git("symbolic-ref", "--short", "HEAD")
        self.source = self.root / "execution-C"
        self.git("worktree", "add", "--detach", "--quiet", str(self.source), self.source_commit)
        self.source_digest = compute_source_set_digest(self.source)
        self.protected = sorted(set(source_roster(self.source)) | set(FROZEN_LEGACY_PATHS))
        self.baseline = self.checkout / "benchmark-results/baselines" / BASELINE
        self.baseline.mkdir(parents=True)
        self.member = "raw/samples.json"
        payload = b'{"fixture_only":true,"samples":[11,13,17]}\n'
        (self.baseline / self.member).parent.mkdir()
        (self.baseline / self.member).write_bytes(payload)
        self.manifest = {
            "baseline_id": BASELINE, "source_commit": self.source_commit,
            "source_file_set_digest": self.source_digest,
            "members": [{"path": self.member, "size_bytes": len(payload), "sha256": sha(payload), "role": "raw"}],
        }
        (self.baseline / "baseline-manifest.json").write_bytes(canonical_document_bytes(self.manifest))
        (self.checkout / "docs").mkdir()
        (self.checkout / "docs/replay.md").write_text("Evidence commit D; measured source unchanged.\n")
        self.commit("docs and results D")
        self.evidence_commit = self.git("rev-parse", "HEAD")
        active = patch.object(transport, "repository_root", return_value=self.checkout)
        active.start()
        self.addCleanup(active.stop)

    def git(self, *arguments, root=None, check=True):
        result = subprocess.run(["git", "-C", str(self.checkout if root is None else root), *arguments],
            capture_output=True, check=check, timeout=30)
        return result.stdout.decode().strip() if check else result

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", message)

    def source_link(self, manifest=None):
        return transport._verify_source_link(self.baseline, self.manifest if manifest is None else manifest, self.checkout)

    def destination(self, source=None):
        return transport.validate_baseline_evidence_root(evidence_root=self.baseline, baseline_id=BASELINE,
            source_root=self.source if source is None else source)

    def assert_rejected(self, code, field, action):
        with self.assertRaises(Exception) as raised:
            action()
        self.assertIs(type(raised.exception), BenchError)
        self.assertEqual((raised.exception.code, raised.exception.field_path), (code, field))

    def test_docs_results_only_descendant_preserves_actual_source_and_member_identities(self):
        from quervant_bench.qualification.identity import compute_source_set_digest

        self.assertNotEqual(self.source_commit, self.evidence_commit)
        self.git("merge-base", "--is-ancestor", self.source_commit, self.evidence_commit)
        self.assertEqual(self.git("symbolic-ref", "--quiet", "HEAD", root=self.source, check=False).returncode, 1)
        self.assertEqual(self.destination(), self.checkout)
        self.assertEqual(compute_source_set_digest(self.checkout), self.source_digest)
        for relative in self.protected:
            with self.subTest(protected=relative):
                self.assertEqual(self.git("rev-parse", self.source_commit + ":" + relative),
                                 self.git("hash-object", "--", relative))
        commit, identity = self.source_link()
        self.assertEqual(commit, self.evidence_commit)
        self.assertEqual(identity, content_digest({"kind": "official-replay-checkout", "schema_version": 1,
            "commit": self.evidence_commit, "source_file_set_digest": self.source_digest, "path": str(self.checkout)}))
        self.assertEqual(self.git("status", "--porcelain=v1", "--untracked-files=all"), "")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.evidence_commit)

    def test_detached_preservation_destination_is_rejected_before_writes(self):
        self.git("checkout", "--detach", "--quiet", self.evidence_commit)
        before = (self.baseline / "baseline-manifest.json").read_bytes()
        self.assert_rejected(BM_UNSAFE_INPUT, "evidence_root", self.destination)
        self.assertEqual((self.baseline / "baseline-manifest.json").read_bytes(), before)
        self.assertEqual(self.git("status", "--porcelain=v1"), "")

    def test_ignored_baseline_path_is_rejected_even_if_current_files_are_tracked(self):
        exclude = self.checkout / ".git/info/exclude"
        with exclude.open("a") as handle:
            handle.write("\nbenchmark-results/\n")
        self.assertTrue(self.git("check-ignore", "--no-index", "--", "benchmark-results/baselines/" + BASELINE))
        self.assert_rejected(BM_UNSAFE_INPUT, "evidence_root", self.destination)
        self.assertEqual(self.git("status", "--porcelain=v1"), "")

    def test_committed_source_template_and_legacy_changes_reject_both_boundaries(self):
        relatives = (
            "benchmarks/quervant_bench/official/__init__.py",
            "benchmarks/official-protocols/cross-engine-keyword-v2.json",
            "benchmarks/official-protocols/retained-key-topk-v2.json",
            "benchmarks/pr15i_d3_c/verify.py",
        )
        for relative in relatives:
            with self.subTest(changed=relative):
                path = self.checkout / relative
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"\n")
                    self.commit("change protected source")
                    self.assertEqual(self.git("status", "--porcelain=v1"), "")
                    self.assert_rejected(BM_IDENTITY_INVALID, "source_commit", self.destination)
                    self.assert_rejected(BM_IDENTITY_INVALID, "source_commit", self.source_link)
                finally:
                    path.write_bytes(original)
                    self.commit("restore protected source")

    def test_clean_git_status_cannot_hide_changed_protected_working_blobs(self):
        relatives = (
            "benchmarks/quervant_bench/official/__init__.py",
            "benchmarks/official-protocols/cross-engine-keyword-v2.json",
            "benchmarks/official-protocols/retained-key-topk-v2.json",
            "benchmarks/pr15i_d3_c/verify.py",
        )
        for relative in relatives:
            with self.subTest(changed=relative):
                path = self.checkout / relative
                original = path.read_bytes()
                self.git("update-index", "--assume-unchanged", "--", relative)
                try:
                    path.write_bytes(original + b"\n")
                    self.assertEqual(self.git("status", "--porcelain=v1", "--untracked-files=all"), "")
                    self.assert_rejected(BM_IDENTITY_INVALID, relative, self.source_link)
                finally:
                    path.write_bytes(original)
                    self.git("update-index", "--no-assume-unchanged", "--", relative)

    def test_every_preserved_member_and_manifest_must_match_its_committed_blob(self):
        for member in (self.member, "baseline-manifest.json"):
            with self.subTest(member=member):
                path = self.baseline / member
                relative = path.relative_to(self.checkout).as_posix()
                original = path.read_bytes()
                self.git("update-index", "--assume-unchanged", "--", relative)
                try:
                    path.write_bytes(original + b"\n")
                    self.assertEqual(self.git("status", "--porcelain=v1", "--untracked-files=all"), "")
                    self.assert_rejected(BM_IDENTITY_INVALID, member, self.source_link)
                finally:
                    path.write_bytes(original)
                    self.git("update-index", "--no-assume-unchanged", "--", relative)

    def test_dirty_or_untracked_replay_checkout_is_rejected(self):
        tracked = self.checkout / "docs/replay.md"
        original = tracked.read_bytes()
        for mode in ("tracked-dirty", "untracked"):
            with self.subTest(mode=mode):
                path = tracked if mode == "tracked-dirty" else self.checkout / "docs/untracked.md"
                try:
                    path.write_bytes(b"changed checkout\n")
                    self.assertTrue(self.git("status", "--porcelain=v1", "--untracked-files=all"))
                    self.assert_rejected(BM_UNSAFE_INPUT, "replay_checkout", self.source_link)
                finally:
                    if mode == "tracked-dirty":
                        path.write_bytes(original)
                    else:
                        path.unlink()

    def test_missing_measured_commit_object_cannot_be_substituted_by_a_digest(self):
        missing = "f" * 40
        self.assertNotEqual(self.git("cat-file", "-e", missing + "^{commit}", check=False).returncode, 0)
        document = {**self.manifest, "source_commit": missing}
        self.assert_rejected(BM_EVIDENCE_UNAVAILABLE, "git", lambda: self.source_link(document))

    def test_present_nonancestor_source_commit_rejects_replay_and_destination(self):
        tree = self.git("rev-parse", self.source_commit + "^{tree}")
        unrelated = self.git("commit-tree", tree, "-m", "separate root with identical source bytes")
        self.assertEqual(self.git("cat-file", "-t", unrelated), "commit")
        self.assertEqual(self.git("merge-base", "--is-ancestor", unrelated, self.evidence_commit, check=False).returncode, 1)
        document = {**self.manifest, "source_commit": unrelated}
        self.assert_rejected(BM_EVIDENCE_UNAVAILABLE, "git", lambda: self.source_link(document))
        source = self.root / "nonancestor-source"
        self.git("worktree", "add", "--detach", "--quiet", str(source), unrelated)
        self.assert_rejected(BM_EVIDENCE_UNAVAILABLE, "git", lambda: self.destination(source))

    def test_present_ignored_member_absent_from_commit_is_rejected(self):
        path = self.baseline / self.member
        relative = path.relative_to(self.checkout).as_posix()
        with (self.checkout / ".git/info/exclude").open("a") as handle:
            handle.write("\n/" + relative + "\n")
        original = path.read_bytes()
        self.git("rm", "--cached", "--quiet", "--", relative)
        self.commit("omit member from evidence commit")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.git("status", "--porcelain=v1", "--untracked-files=all"), "")
        self.assertNotEqual(self.git("rev-parse", "--verify", "HEAD:" + relative, check=False).returncode, 0)
        self.assert_rejected(BM_EVIDENCE_UNAVAILABLE, "git", self.source_link)

    def _prepare_public_issuance_fixture(self):
        """Real Git/manifest graph; benchmark semantics belong to replay tests."""
        (self.baseline / "baseline-manifest.json").unlink()
        raw = (self.baseline / self.member).read_bytes()
        raw_member = {"path": self.member, "size_bytes": len(raw), "sha256": sha(raw), "role": "raw"}
        for index, study in enumerate(transport.STUDIES):
            run = RUN if index == 0 else "55555555-5555-4555-8555-555555555555"
            prefix = f"studies/{study}/{run}"
            corpus_path = prefix + "/provenance/corpus-manifest.json"
            corpus_payload = canonical_document_bytes({"fixture_only": True})
            transport._write_payload(self.baseline, corpus_path, corpus_payload)
            corpus = {"generator": "benchmarks/pr15d/corpus/generate.py",
                "generator_digest": sha((self.checkout / "benchmarks/pr15d/corpus/generate.py").read_bytes()),
                "manifest_path": corpus_path, "manifest_digest": sha(corpus_payload),
                "files": [{"path": "documents-10000.tsv", "size_bytes": 11, "sha256": DIGEST},
                    {"path": "documents-100000.tsv", "size_bytes": 13, "sha256": DIGEST}]}
            members = sorted([raw_member, {"path": corpus_path, "size_bytes": len(corpus_payload),
                "sha256": sha(corpus_payload), "role": "provenance"}], key=lambda row: row["path"])
            units = ("control", "treatment") if study == transport.STUDY_CROSS_ENGINE else (
                transport.D3C_CONTROL_NAME, *transport.D3C_CAMPAIGN_NAMES)
            for unit in (*units, "qualification"):
                checkpoint = {"kind": "official-baseline-checkpoint", "schema_version": 1,
                    "baseline_id": BASELINE, "profile": transport.PROFILE, "study_id": study,
                    "run_id": run, "source_commit": self.source_commit,
                    "source_file_set_digest": self.source_digest, "design_digest": DIGEST,
                    "unit": unit, "status": "COMPLETE", "members": members, "corpus": corpus,
                    "qualification_manifest_digest": DIGEST if unit == "qualification" else None}
                transport._write_payload(self.baseline, prefix + f"/checkpoints/{unit}-complete.json",
                    canonical_document_bytes(checkpoint))
        preserved = transport.finalize_baseline_evidence(baseline_root=self.baseline)
        self.assertEqual(preserved.status, "PRESERVED")
        self.manifest = dict(preserved.document)
        self.commit("complete structural baseline for issuance-boundary tests")
        self.evidence_commit = self.git("rev-parse", "HEAD")
        self.assertEqual(self.git("status", "--porcelain=v1", "--untracked-files=all"), "")

    def _assert_public_replay_rejects_late_checkout_change(self, mode):
        self._prepare_public_issuance_fixture()
        calls = []
        changed = self.checkout / ("unexpected.txt" if mode == "untracked" else
            "benchmarks/quervant_bench/config/__init__.py")

        def replay_hook(**kwargs):
            calls.append(kwargs["study"])
            if len(calls) == 1:
                changed.write_bytes(b"changed after source-link preflight\n")
                self.assertEqual(self.git("rev-parse", "HEAD"), self.evidence_commit)
            return {"study_id": kwargs["study"], "fixture_only": True}

        # Only the expensive per-study semantics are substituted. Manifest,
        # checkpoints, member observations, Git checks and receipt issuance run.
        with patch.object(transport, "_replay_study", side_effect=replay_hook):
            self.assert_rejected(BM_UNSAFE_INPUT, "replay_checkout",
                lambda: transport.replay_baseline_evidence(baseline_root=self.baseline))
        self.assertEqual(calls, list(transport.STUDIES))
        self.assertTrue(changed.exists())
        self.assertTrue(self.git("status", "--porcelain=v1", "--untracked-files=all"))
        self.assertEqual(self.git("rev-parse", "HEAD"), self.evidence_commit)
        self.assertFalse((self.checkout / "benchmark-results/replays").exists())
        self.assertEqual(list((self.checkout / "target/pr15i-d3-c").glob("baseline-replay-*")), [])

    def test_public_replay_rechecks_untracked_files_before_issuing_receipt(self):
        self._assert_public_replay_rejects_late_checkout_change("untracked")

    def test_public_replay_rechecks_tracked_source_before_issuing_receipt(self):
        self._assert_public_replay_rejects_late_checkout_change("tracked")

    def test_public_replay_unchanged_checkout_passes_issuance_boundary(self):
        self._prepare_public_issuance_fixture()
        before = (self.baseline / "baseline-manifest.json").read_bytes()
        calls = []

        def replay_hook(**kwargs):
            calls.append(kwargs["study"])
            return {"study_id": kwargs["study"], "fixture_only": True}

        with patch.object(transport, "_replay_study", side_effect=replay_hook):
            receipt = transport.replay_baseline_evidence(baseline_root=self.baseline)
        self.assertEqual(calls, list(transport.STUDIES))
        self.assertEqual(receipt["status"], "REPLAY_VERIFIED")
        self.assertEqual(receipt["evidence_commit"], self.evidence_commit)
        self.assertEqual(receipt["measured_source_commit"], self.source_commit)
        self.assertEqual(receipt["baseline_manifest_digest"], content_digest(self.manifest))
        self.assertEqual((self.baseline / "baseline-manifest.json").read_bytes(), before)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.evidence_commit)
        written = self.checkout / "benchmark-results/replays" / BASELINE / (receipt["replay_id"] + ".json")
        self.assertEqual(json.loads(written.read_bytes()), receipt)
        self.assertEqual(list((self.checkout / "target/pr15i-d3-c").glob("baseline-replay-*")), [])


if __name__ == "__main__":
    unittest.main()
