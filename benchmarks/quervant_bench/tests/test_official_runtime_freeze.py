"""Untimed current-runtime boundaries with real Git, bytes and legacy checks.

The temporary executables are inert bytes and never run. Only external host/CPU
observation is substituted; production readers, roster, Git blobs, corpus,
binary hashes, exclusive writers and original require_freeze remain real.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_PUBLICATION_CONFLICT, BM_UNSAFE_INPUT, BenchError
from quervant_bench.official import acquisition, operation_identity, protocols, runtime_freeze as runtime
from quervant_bench.official.operation_config import OperationConfig
from quervant_bench.official.retained_backend import load_prepared_retained_key
from quervant_bench.qualification.identity import EXTRA_SOURCE_FILES, SOURCE_DIRECTORIES, source_roster
from quervant_bench.tests import official_support as support
from quervant_bench.tests.test_official_operation_identity import HostProvider

BASELINE_ID = "a9bcd6e3-0945-424c-9856-8d801df49e62"


class RuntimeReadBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "runtime.json"
        self.payload = b'{"kind":"descriptor-test"}\n'
        self.path.write_bytes(self.payload)

    def read_with_fault(self, *, failure=None, close_failure=None, limit=None):
        """Keep real safe opens/fds; inject only the named descriptor operation."""
        original_open = runtime.open_regular_beneath
        original_fstat = os.fstat
        handles = []
        self.handles = handles
        primary = OSError(5, "injected " + str(failure))
        self.primary_error = primary
        self.fstat_calls = 0

        class Handle:
            def __init__(self, real):
                self.real = real
                self.fd = real.fileno()
                self.close_calls = 0

            def fileno(self):
                return self.real.fileno()

            def read(self, amount):
                if failure == "read":
                    raise primary
                return self.real.read(amount)

            def close(self):
                self.close_calls += 1
                self.real.close()
                if close_failure is not None:
                    raise close_failure

            def __enter__(self):
                return self

            def __exit__(self, *_exception):
                self.close()

        def opener(root, relative):
            handle = Handle(original_open(root, relative))
            handles.append(handle)
            return handle

        def fstat(fd):
            if handles and not handles[-1].real.closed and fd == handles[-1].fd:
                self.fstat_calls += 1
                if (failure == "fstat-before" and self.fstat_calls == 1
                        or failure == "fstat-after" and self.fstat_calls == 2):
                    raise primary
            return original_fstat(fd)

        with patch.object(runtime, "open_regular_beneath", side_effect=opener), \
                patch.object(runtime.os, "fstat", side_effect=fstat):
            return runtime._read(self.path, limit=len(self.payload) if limit is None else limit)

    def assert_closed_once(self):
        self.assertEqual(len(self.handles), 1)
        self.assertTrue(self.handles[0].real.closed)
        self.assertEqual(self.handles[0].close_calls, 1)

    def test_real_descriptor_read_and_both_fstat_failures_are_typed(self):
        for failure in ("read", "fstat-before", "fstat-after"):
            with self.subTest(failure=failure):
                with self.assertRaises(Exception) as raised:
                    self.read_with_fault(failure=failure)
                self.assertIs(type(raised.exception), BenchError)
                self.assertEqual((raised.exception.code, raised.exception.field_path),
                                 (BM_UNSAFE_INPUT, "runtime_freeze"))
                self.assertIs(raised.exception.__cause__, self.primary_error)
                self.assert_closed_once()

    def test_close_failure_after_success_is_typed(self):
        secondary = OSError(5, "injected close")
        with self.assertRaises(Exception) as raised:
            self.read_with_fault(close_failure=secondary)
        self.assertIs(type(raised.exception), BenchError)
        self.assertEqual((raised.exception.code, raised.exception.field_path),
                         (BM_UNSAFE_INPUT, "runtime_freeze"))
        self.assertIs(raised.exception.__cause__, secondary)
        self.assert_closed_once()

    def test_primary_io_failure_survives_secondary_close_failure(self):
        for failure in ("read", "fstat-before", "fstat-after"):
            with self.subTest(failure=failure):
                secondary = OSError(5, "injected secondary close")
                with self.assertRaises(Exception) as raised:
                    self.read_with_fault(failure=failure, close_failure=secondary)
                self.assertIs(type(raised.exception), BenchError)
                self.assertEqual((raised.exception.code, raised.exception.field_path),
                                 (BM_UNSAFE_INPUT, "runtime_freeze"))
                self.assertIs(raised.exception.__cause__, self.primary_error)
                self.assert_closed_once()

    def test_bounded_input_bencherror_survives_secondary_close_failure(self):
        original_fail = runtime._fail
        created = []

        def record_failure(*args, **kwargs):
            failure = original_fail(*args, **kwargs)
            created.append(failure)
            return failure

        with patch.object(runtime, "_fail", side_effect=record_failure):
            with self.assertRaises(Exception) as raised:
                self.read_with_fault(limit=len(self.payload) - 1,
                                     close_failure=OSError(5, "injected secondary close"))
        self.assertIs(type(raised.exception), BenchError)
        self.assertEqual(len(created), 1)
        self.assertIs(raised.exception, created[0])
        self.assertEqual((raised.exception.code, raised.exception.field_path),
                         (BM_UNSAFE_INPUT, "runtime_freeze"))
        self.assertIn("bounded single-link", raised.exception.message)
        self.assertIsNone(raised.exception.__cause__)
        self.assert_closed_once()

    def test_successful_bounded_read_keeps_both_observations(self):
        self.assertEqual(self.read_with_fault(), self.payload)
        self.assertEqual(len(self.handles), 2)
        self.assertTrue(all(handle.real.closed and handle.close_calls == 1 for handle in self.handles))
        self.assertEqual(self.fstat_calls, 4)


class CurrentRuntimeFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus_temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.corpus_temporary.cleanup)
        cls.corpus = support.make_corpus(Path(cls.corpus_temporary.name) / "corpus")

    def git(self, *arguments):
        completed = subprocess.run(["git", "-C", str(self.root), *arguments], capture_output=True, check=True, timeout=30)
        return completed.stdout.decode().strip()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.root.mkdir()
        self.git("init", "-q")
        (self.root / ".gitignore").write_text("target/\n__pycache__/\n")
        for relative in SOURCE_DIRECTORIES:
            directory = self.root / relative
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "__init__.py").write_text('"""Runtime boundary fixture source."""\n')
        (self.root / "benchmarks/quervant_bench/config/schemas").mkdir()
        (self.root / "benchmarks/quervant_bench/config/schemas/frozen.json").write_text('{}\n')
        for relative in sorted(set(EXTRA_SOURCE_FILES).union(runtime.EXTRA_PROTECTED)):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(support.REPO_ROOT / relative, target)
        self.git("add", ".")
        self.git("-c", "user.name=Runtime test", "-c", "user.email=runtime-test@example.invalid", "commit", "-qm", "runtime test source")
        self.git("checkout", "--detach", "-q", "HEAD")
        self.commit = self.git("rev-parse", "HEAD")
        self.build = self.root / "target/prepared"
        self.build.mkdir(parents=True)
        binaries = {}
        for arm, feature, commit in (("A", False, protocols.D3C_BASE_COMMIT), ("B", True, protocols.D3C_EXPERIMENT_COMMIT)):
            path = self.build / arm
            payload = ("inert " + arm).encode()
            path.write_bytes(payload)
            binaries[arm] = {"binary": str(path), "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload), "argv": [], "feature": feature, "source_sha": commit}
        manifest = {"schema": "official-retained-key-prepared-v1", "source_root": str(self.root),
            "corpus_dir": str(self.corpus["dir"]), "protocol_digest": protocols.D3C_PROTOCOL_RAW_SHA256,
            "corpus_digest": "sha256:" + self.corpus["manifest_sha"], "binaries": binaries}
        self.manifest_path = self.build / "prepared-retained-key.json"
        self.manifest_path.write_bytes(canonical_document_bytes(manifest))
        self.prepared = load_prepared_retained_key(self.manifest_path, root=self.root)
        self.envelope = self.root / "target/runtime/envelope.json"
        self.config = OperationConfig({"schema_version": 2, "acceptance_profile": protocols.CURRENT_BASELINE_PROFILE,
            "source_root": str(self.root), "prepared_manifest": str(self.manifest_path),
            "output_base": str(Path(self.temporary.name) / "qualified"), "adapter_cpu": 0, "controller_cpu": 1,
            "baseline": {"baseline_id": BASELINE_ID, "runtime_freeze_path": str(self.envelope)}})
        self.template = protocols.read_canonical_json(protocols.template_path(protocols.STUDY_RETAINED_KEY, self.root, version=2))
        spec = importlib.util.spec_from_file_location("runtime_frozen_test_runner", self.root / "benchmarks/pr15i_d3_c/run.py")
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        for active in (
            patch.object(runtime, "repository_root", return_value=self.root),
            patch.object(runtime, "legacy_runner", return_value=self.runner),
            patch.object(self.runner, "cpus", return_value=(0, 1)),
            patch.object(operation_identity, "LinuxCapabilityProvider", return_value=HostProvider("native-linux")),
        ):
            active.start()
            self.addCleanup(active.stop)

    def create(self):
        return runtime.prepare_current_runtime_freeze(config=self.config, template=self.template, prepared=self.prepared)

    def reopen(self):
        return runtime.open_current_runtime_freeze(config=self.config, template=self.template)

    def write(self, path, document):
        path.write_bytes(canonical_document_bytes(document))

    def test_complete_current_receipt_and_twenty_field_envelope_reopen_without_qa(self):
        with patch.object(operation_identity, "observe_identities", side_effect=AssertionError("runtime must not read QA")):
            cap = self.create()
            self.assertEqual(self.reopen().digest, cap.digest)
            self.assertEqual(self.create().digest, cap.digest)
        receipt = json.loads((self.root / runtime.BACKEND_RECEIPT).read_text())
        self.assertEqual(set(receipt), runtime.RECEIPT_KEYS)
        self.assertEqual(receipt["t6_commit"], self.commit)
        self.assertEqual(receipt["receipt_origin"], "current-baseline-v2")
        self.assertEqual(list(receipt["protected_files"]), sorted(set(source_roster(self.root)).union(runtime.EXTRA_PROTECTED)))
        self.assertEqual(set(cap.document), runtime.ENVELOPE_KEYS)
        self.assertEqual(len(cap.document), 20)
        self.assertEqual(cap.digest, "sha256:" + hashlib.sha256(self.envelope.read_bytes()).hexdigest())
        self.assertEqual(cap.document["prepared_manifest_digest"], "sha256:" + hashlib.sha256(self.manifest_path.read_bytes()).hexdigest())
        self.assertNotEqual(cap.document["prepared_manifest_digest"], content_digest(self.prepared.manifest))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(runtime.reverify_current_runtime_freeze(cap).digest, cap.digest)
        with self.assertRaises(TypeError):
            cap.document["origin"] = "historical"

    def test_empty_subset_extra_and_numeric_alias_rosters_are_rejected(self):
        self.create()
        path = self.root / runtime.BACKEND_RECEIPT
        original = json.loads(path.read_text())
        variants = ({}, dict(list(original["protected_files"].items())[1:]),
                    {**original["protected_files"], "extra.py": "a" * 64})
        for roster in variants:
            with self.subTest(roster_size=len(roster)):
                self.write(path, {**original, "protected_files": roster})
                with self.assertRaises(BenchError):
                    self.reopen()
        self.write(path, original)
        envelope = json.loads(self.envelope.read_text())
        self.write(self.envelope, {**envelope, "adapter_cpu": 0.0})
        with self.assertRaises(BenchError):
            self.reopen()

    def test_prepared_binary_and_current_source_changes_fail(self):
        self.create()
        binary = self.build / "A"
        original = binary.read_bytes()
        binary.write_bytes(b"changed")
        with self.assertRaises(BenchError) as raised:
            self.reopen()
        self.assertEqual(raised.exception.field_path, "binaries")
        binary.write_bytes(original)
        source = self.root / "benchmarks/quervant_bench/official/__init__.py"
        source.write_text("# changed source\n")
        with self.assertRaises(BenchError) as raised:
            self.reopen()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_host_cpu_root_and_baseline_are_observed_again(self):
        cap = self.create()
        with patch.object(operation_identity, "LinuxCapabilityProvider", return_value=HostProvider("wsl2")), self.assertRaises(BenchError):
            self.reopen()
        with patch.object(self.runner, "cpus", return_value=(1, 0)), self.assertRaises(BenchError):
            self.reopen()
        for field, changed in (("output_base", str(Path(self.temporary.name) / "other")),):
            config = dataclasses.replace(self.config, document={**self.config.document, field: changed})
            with self.assertRaises(BenchError):
                runtime.open_current_runtime_freeze(config=config, template=self.template)
        forged = dataclasses.replace(cap, document=MappingProxyType({**cap.document, "origin": "historical"}))
        with self.assertRaises(BenchError):
            runtime.reverify_current_runtime_freeze(forged)

    def test_partial_pair_never_repairs_or_overwrites(self):
        self.create()
        receipt = self.root / runtime.BACKEND_RECEIPT
        original = receipt.read_bytes()
        self.envelope.unlink()
        with self.assertRaises(BenchError) as raised:
            self.create()
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
        self.assertEqual(receipt.read_bytes(), original)
        self.assertFalse(self.envelope.exists())

    def test_worker_requires_outer_digest_and_never_relabels_current_receipt_as_v1(self):
        cap = self.create()
        opened = runtime.open_worker_runtime_freeze(root=self.root, envelope_path=self.envelope,
            prepared_manifest=self.manifest_path, expected_digest=cap.digest, profile_version=2)
        self.assertEqual(opened.digest, cap.digest)
        with self.assertRaises(BenchError):
            runtime.open_worker_runtime_freeze(root=self.root, envelope_path=self.envelope,
                prepared_manifest=self.manifest_path, expected_digest="sha256:" + "a" * 64, profile_version=2)
        with self.assertRaises(BenchError) as raised:
            runtime.reject_current_receipt_for_v1(self.root)
        self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_IDENTITY_INVALID, "t6_freeze_receipt"))

    def test_link_hardlink_fifo_and_parent_symlink_reject_without_blocking(self):
        self.create()
        payload = self.envelope.read_bytes()
        for case in ("leaf", "hardlink", "fifo", "parent"):
            with self.subTest(case=case):
                parent = self.envelope.parent
                sibling = parent.with_name("runtime-original")
                self.envelope.unlink()
                try:
                    if case == "leaf":
                        self.envelope.symlink_to(self.manifest_path)
                    elif case == "hardlink":
                        os.link(self.manifest_path, self.envelope)
                    elif case == "fifo":
                        os.mkfifo(self.envelope)
                    else:
                        parent.rename(sibling)
                        (sibling / self.envelope.name).write_bytes(payload)
                        parent.symlink_to(sibling, target_is_directory=True)
                    with self.assertRaises(BenchError) as raised:
                        self.reopen()
                    self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
                finally:
                    if case == "parent":
                        if parent.is_symlink():
                            parent.unlink()
                        if sibling.exists():
                            sibling.rename(parent)
                    elif os.path.lexists(self.envelope):
                        self.envelope.unlink()
                    self.envelope.write_bytes(payload)

    def test_branch_checkout_cannot_be_used_as_current_execution_root(self):
        self.git("checkout", "-q", "-b", "ordinary-branch")
        with self.assertRaises(BenchError) as raised:
            self.create()
        self.assertEqual(raised.exception.field_path, "source_root")
        self.assertFalse(self.envelope.exists())


class CurrentLifecycleTests(unittest.TestCase):
    def test_v2_only_forward_neighbors_and_v1_unchanged(self):
        for version, order in ((1, acquisition.STATE_ORDER), (2, acquisition.STATE_ORDER_V2)):
            for index, current in enumerate(order):
                for target_index, target in enumerate(order):
                    with self.subTest(version=version, current=current, target=target):
                        if target_index == index + 1:
                            self.assertEqual(acquisition.require_transition(current, target, profile_version=version), target)
                        else:
                            with self.assertRaises(BenchError):
                                acquisition.require_transition(current, target, profile_version=version)
        for invalid in (True, False, 0, 3, "2", 2.0, None):
            with self.subTest(invalid=invalid), self.assertRaises(BenchError):
                acquisition.require_transition("IMPLEMENTING", "SOURCE_FROZEN", profile_version=invalid)
        with self.assertRaises(BenchError):
            acquisition.require_transition("REAL_ATTESTED", "HISTORICAL_PARITY_PENDING", profile_version=2)

