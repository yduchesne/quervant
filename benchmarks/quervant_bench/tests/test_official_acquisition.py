"""O09-ACQ / O09-SAFE: bounded legacy backend invocation restrictions."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from quervant_bench.config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_INTERNAL_ERROR,
    BM_PUBLICATION_CONFLICT,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.official import acquisition, protocols
from quervant_bench.tests import official_support as support


class IsolatedToolchainEnvironmentTests(unittest.TestCase):
    def test_original_default_toolchain_homes_survive_archive_home_isolation(self):
        with patch.dict(os.environ, {"HOME": "/original/operator", "PATH": "/tools/bin", "SECRET_TOKEN": "not-forwarded"}, clear=True):
            observed = acquisition.sanitized_environment(Path("/owned/run/home"))
        self.assertEqual(observed["HOME"], "/owned/run/home")
        self.assertEqual(observed["XDG_DATA_HOME"], "/owned/run/home/.local/share")
        self.assertEqual(observed["CARGO_HOME"], "/original/operator/.cargo")
        self.assertEqual(observed["RUSTUP_HOME"], "/original/operator/.rustup")
        self.assertNotIn("SECRET_TOKEN", observed)

    def test_explicit_toolchain_roots_are_preserved_without_new_environment_keys(self):
        with patch.dict(os.environ, {"HOME": "/original/operator", "CARGO_HOME": "/tools/cargo", "RUSTUP_HOME": "/tools/rustup", "RUSTFLAGS": "unapproved"}, clear=True):
            isolated = acquisition.sanitized_environment(Path("/owned/run/home"))
            ordinary = acquisition.sanitized_environment()
        self.assertEqual(isolated["CARGO_HOME"], "/tools/cargo")
        self.assertEqual(isolated["RUSTUP_HOME"], "/tools/rustup")
        self.assertNotIn("RUSTFLAGS", isolated)
        self.assertNotIn("HOME", ordinary)


class OwnedBackendProcessTests(unittest.TestCase):
    def invocation(self):
        return acquisition.BackendInvocation(("python3", "owned.py"), Path("/owned"),
            {"PATH": "/tools"}, 123, Path("/owned/out"), None)

    def test_session_and_bounded_success_capture(self):
        process = Mock(pid=31415, returncode=3)
        process.communicate.return_value = (b"out", b"err")
        with patch.object(acquisition.subprocess, "Popen", return_value=process) as start, \
                patch.object(acquisition.os, "killpg") as kill:
            result = acquisition.run_backend(self.invocation())
        self.assertEqual((result.returncode, result.stdout_tail, result.stderr_tail), (3, "out", "err"))
        self.assertTrue(start.call_args.kwargs["start_new_session"])
        self.assertFalse(start.call_args.kwargs["shell"])
        process.communicate.assert_called_once_with(timeout=123)
        kill.assert_called_once_with(31415, signal.SIGKILL)

    def test_timeout_stops_owned_group_and_retains_captured_cause(self):
        timeout = subprocess.TimeoutExpired(["python3", "owned.py"], 123, b"partial", b"partial error")
        process = Mock(pid=31415, returncode=-15)
        process.communicate.side_effect = [timeout, (b"all output", b"all errors")]
        with patch.object(acquisition.subprocess, "Popen", return_value=process), \
                patch.object(acquisition.os, "killpg") as kill, self.assertRaises(BenchError) as failure:
            acquisition.run_backend(self.invocation())
        self.assertEqual(failure.exception.code, BM_ACQUISITION_PROHIBITED)
        self.assertEqual(failure.exception.field_path, "timeout")
        self.assertIs(failure.exception.__cause__, timeout)
        self.assertEqual(timeout.output, b"all output")
        self.assertEqual(timeout.stderr, b"all errors")
        self.assertEqual([call.args for call in kill.call_args_list],
            [(31415, signal.SIGTERM), (31415, signal.SIGKILL)])
        self.assertEqual([call.kwargs for call in process.communicate.call_args_list],
            [{"timeout": 123}, {"timeout": 10}])

    def test_ignoring_term_escalates_to_owned_group_kill_with_bounded_waits(self):
        process = Mock(pid=31415, returncode=-9)
        process.communicate.side_effect = [subprocess.TimeoutExpired("owned", 123),
            subprocess.TimeoutExpired("owned", 10), (b"final", b"stopped")]
        with patch.object(acquisition.subprocess, "Popen", return_value=process), \
                patch.object(acquisition.os, "killpg") as kill, self.assertRaises(BenchError):
            acquisition.run_backend(self.invocation())
        self.assertEqual([call.args for call in kill.call_args_list],
            [(31415, signal.SIGTERM), (31415, signal.SIGKILL), (31415, signal.SIGKILL)])
        self.assertEqual([call.kwargs["timeout"] for call in process.communicate.call_args_list], [123, 10, 10])

    def test_interrupt_cleans_descendants_then_preserves_interrupt(self):
        process = Mock(pid=31415, returncode=-15)
        process.communicate.side_effect = [KeyboardInterrupt(), (b"", b"")]
        with patch.object(acquisition.subprocess, "Popen", return_value=process), \
                patch.object(acquisition.os, "killpg") as kill, self.assertRaises(KeyboardInterrupt):
            acquisition.run_backend(self.invocation())
        self.assertEqual([call.args[0] for call in kill.call_args_list], [31415, 31415])

    def test_inherited_open_pipe_cannot_make_cleanup_unbounded(self):
        process = Mock(pid=31415, returncode=-9)
        process.communicate.side_effect = [subprocess.TimeoutExpired("owned", 123),
            subprocess.TimeoutExpired("owned", 10), subprocess.TimeoutExpired("owned", 10, b"last", b"error")]
        with patch.object(acquisition.subprocess, "Popen", return_value=process), \
                patch.object(acquisition.os, "killpg"), self.assertRaises(BenchError) as failure:
            acquisition.run_backend(self.invocation())
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()
        process.wait.assert_called_once_with(timeout=10)
        self.assertEqual(failure.exception.__cause__.output, b"last")

    def test_exited_fork_worker_still_cleans_its_adapter_group(self):
        process = Mock(pid=31415)
        process.is_alive.return_value = False
        with patch.object(acquisition.os, "killpg") as kill:
            acquisition._finish_owned_worker(process)
        kill.assert_called_once_with(31415, signal.SIGKILL)
        process.join.assert_not_called()

    def test_fork_worker_cleanup_escalates_and_never_joins_without_bound(self):
        process = Mock(pid=31415)
        process.is_alive.side_effect = [True, True, False]
        with patch.object(acquisition.os, "killpg") as kill:
            acquisition._finish_owned_worker(process)
        self.assertEqual([call.args for call in process.join.call_args_list], [(10,), (10,)])
        self.assertEqual([call.args for call in kill.call_args_list],
            [(31415, signal.SIGTERM), (31415, signal.SIGKILL), (31415, signal.SIGKILL)])

    def test_unreapable_fork_worker_is_typed_failure(self):
        process = Mock(pid=31415)
        process.is_alive.return_value = True
        with patch.object(acquisition.os, "killpg"), self.assertRaises(BenchError) as failure:
            acquisition._finish_owned_worker(process)
        self.assertEqual(failure.exception.field_path, "backend_cleanup")


class OwnedPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.build = self.root / "build"
        self.corpus = self.root / "corpus"
        self.receiver, self.sender = Mock(), Mock()
        self.receiver.poll.return_value = True
        self.receiver.recv_bytes.return_value = b'{"status":"COMPLETE"}'
        self.process = Mock(pid=31415, exitcode=0)
        self.process.is_alive.return_value = False
        self.context = Mock()
        self.context.Pipe.return_value = (self.receiver, self.sender)
        self.context.Process.return_value = self.process
        protocol = patch.object(acquisition, "read_canonical_json", return_value={"stopping": {"backend_timeout_seconds": 123}})
        protocol.start()
        self.addCleanup(protocol.stop)

    def run_mocked(self):
        with patch.object(acquisition.multiprocessing, "get_context", return_value=self.context), \
                patch.object(acquisition, "_finish_owned_worker") as cleanup:
            try:
                acquisition._run_owned_preparation(study_id=protocols.STUDY_CROSS_ENGINE,
                    root=self.root, build_root=self.build, corpus_dir=self.corpus)
            finally:
                cleanup.assert_called_once_with(self.process)

    def receipt(self):
        return json.loads((self.root / "build.preparation-records/result.json").read_text())

    def test_complete_preparation_uses_frozen_timeout_fixed_worker_and_bounded_frame(self):
        self.run_mocked()
        self.process.start.assert_called_once()
        self.process.join.assert_called_once_with(123)
        self.context.Pipe.assert_called_once_with(duplex=False)
        self.assertIs(self.context.Process.call_args.kwargs["target"], acquisition._preparation_worker_entry)
        self.assertEqual(self.context.Process.call_args.kwargs["args"][:4],
            (protocols.STUDY_CROSS_ENGINE, self.root, self.build, self.corpus))
        self.receiver.recv_bytes.assert_called_once_with(maxlength=4096)
        self.receiver.close.assert_called_once()
        self.assertEqual(self.receipt()["status"], "COMPLETE")

    def test_timeout_preserves_partial_files_cleans_once_and_does_not_read_result(self):
        self.process.is_alive.return_value = True
        def partial():
            self.build.mkdir()
            (self.build / "partial.bin").write_bytes(b"unlaunched partial build")
        self.process.start.side_effect = partial
        with self.assertRaises(BenchError) as failure:
            self.run_mocked()
        self.assertEqual((failure.exception.code, failure.exception.field_path), (BM_ACQUISITION_PROHIBITED, "timeout"))
        self.process.start.assert_called_once()
        self.receiver.recv_bytes.assert_not_called()
        self.assertEqual((self.build / "partial.bin").read_bytes(), b"unlaunched partial build")
        self.assertEqual(self.receipt()["status"], "STOPPED_PRESERVED")
        self.assertFalse(self.receipt()["retry_allowed"])

    def test_typed_child_failure_is_preserved_after_owned_cleanup(self):
        self.process.exitcode = 1
        self.receiver.recv_bytes.return_value = json.dumps({"status": "STOPPED_PRESERVED",
            "code": BM_IDENTITY_INVALID, "message": "fixture binary mismatch",
            "field_path": "binary_manifest_digest", "reference": "build-receipts.json"}).encode()
        with self.assertRaises(BenchError) as failure:
            self.run_mocked()
        self.assertEqual(failure.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(failure.exception.field_path, "binary_manifest_digest")
        self.assertEqual(failure.exception.reference, "build-receipts.json")
        self.assertEqual(self.receipt()["status"], "STOPPED_PRESERVED")

    def test_missing_or_oversized_frame_is_a_failure_never_success(self):
        for case in ("missing", "oversized"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                self.root = Path(temporary)
                self.build = self.root / "build"
                self.receiver.poll.return_value = case != "missing"
                self.receiver.recv_bytes.side_effect = OSError("oversized private frame") if case == "oversized" else None
                with self.assertRaises(BenchError) as failure:
                    self.run_mocked()
                self.assertEqual(failure.exception.code, BM_INTERNAL_ERROR)
                self.assertEqual(self.receipt()["status"], "STOPPED_PRESERVED")

    def test_parent_interruption_cleans_worker_and_retains_stopped_receipt(self):
        self.process.join.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_mocked()
        self.assertEqual(self.receipt()["status"], "STOPPED_PRESERVED")
        self.receiver.recv_bytes.assert_not_called()

    def test_real_private_pipe_transfers_typed_error_from_mocked_body_without_building(self):
        from quervant_bench.official import cross_engine_backend
        failure = BenchError(BM_IDENTITY_INVALID, "fixture failure before any build", field_path="binary_manifest_digest")
        with patch.object(cross_engine_backend, "_prepare_cross_engine_body", side_effect=failure), self.assertRaises(BenchError) as raised:
            acquisition._run_owned_preparation(study_id=protocols.STUDY_CROSS_ENGINE,
                root=self.root, build_root=self.build, corpus_dir=self.corpus)
        self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_IDENTITY_INVALID, "binary_manifest_digest"))
        self.assertFalse(self.build.exists())
        self.assertEqual(self.receipt()["exit_code"], 1)
        self.assertEqual(self.receipt()["status"], "STOPPED_PRESERVED")
        self.assertIn("fixture failure before any build", (self.root / "build.preparation-records/stderr.log").read_text())

    def test_existing_preparation_or_receipts_cannot_be_retried(self):
        self.build.mkdir()
        with patch.object(acquisition.multiprocessing, "get_context") as context, self.assertRaises(BenchError) as failure:
            acquisition._run_owned_preparation(study_id=protocols.STUDY_CROSS_ENGINE,
                root=self.root, build_root=self.build, corpus_dir=self.corpus)
        self.assertEqual(failure.exception.code, BM_PUBLICATION_CONFLICT)
        context.assert_not_called()


class TransitionTests(unittest.TestCase):
    def test_o09_acq_01_forward_transitions_are_legal(self) -> None:
        self.assertEqual(
            acquisition.require_transition("AUTHORIZED", "CONTROL_RUNNING"),
            "CONTROL_RUNNING",
        )
        self.assertEqual(
            acquisition.require_transition("TREATMENT_RUNNING", "REAL_EVIDENCE_SEALED"),
            "REAL_EVIDENCE_SEALED",
        )

    def test_o09_acq_02_skipping_or_reversing_is_prohibited(self) -> None:
        for current, target in (
            ("AUTHORIZED", "REAL_ACCEPTED"),
            ("CONTROL_RUNNING", "AUTHORIZED"),
            ("IMPLEMENTING", "CONTROL_RUNNING"),
        ):
            with self.assertRaises(BenchError) as raised:
                acquisition.require_transition(current, target)
            self.assertEqual(raised.exception.code, BM_ACQUISITION_PROHIBITED)

    def test_o09_acq_03_unknown_state_is_rejected(self) -> None:
        with self.assertRaises(BenchError) as raised:
            acquisition.require_transition("DONE", "CLOSEOUT_READY")
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


class RetainedKeyInvocationTests(unittest.TestCase):
    def test_o09_acq_09_missing_t6_freeze_blocks_the_family(self) -> None:
        freeze = support.make_freeze(study_id=protocols.STUDY_RETAINED_KEY)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(BenchError) as raised:
                acquisition.require_retained_key_preconditions(freeze, Path(temporary))
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def _production_authorization(self, root: Path, study_id: str):
        freeze = support.make_freeze(study_id=study_id)
        return (
            support.production_shaped_authorization(freeze, sandbox=root / "sandbox"),
            support.authorization_observations(freeze),
        )

    def test_o09_acq_10_invocation_order_is_the_frozen_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / acquisition.D3C_T6_RECEIPT).parent.mkdir(parents=True)
            (root / acquisition.D3C_T6_RECEIPT).write_text("{}", encoding="utf-8")
            authorization, observed = self._production_authorization(
                root, protocols.STUDY_RETAINED_KEY
            )
            invocations = acquisition.retained_key_invocations(
                authorization,
                observed=observed,
                root=root,
                series_root=root / "series",
                official_home=root / "home",
                timeout_seconds=60,
            )
        names = list(invocations)
        self.assertEqual(
            names,
            [
                "preflight",
                "readiness-control",
                "control",
                "verify-control",
                "publish-control",
                "readiness-d3c-v3r3-strategies-01",
                "campaign-1",
                "verify-d3c-v3r3-strategies-01",
                "publish-d3c-v3r3-strategies-01",
                "readiness-d3c-v3r3-strategies-02",
                "campaign-2",
                "verify-d3c-v3r3-strategies-02",
                "publish-d3c-v3r3-strategies-02",
                "verify-series",
            ],
        )
        for invocation in invocations.values():
            self.assertNotIn("--allow-contended", invocation.argv)
            self.assertEqual(invocation.timeout_seconds, 60)
            self.assertEqual(invocation.env["HOME"], str(Path(temporary) / "home"))

    def test_o09_acq_11_control_uses_the_frozen_campaign_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / acquisition.D3C_T6_RECEIPT).parent.mkdir(parents=True)
            (root / acquisition.D3C_T6_RECEIPT).write_text("{}", encoding="utf-8")
            authorization, observed = self._production_authorization(
                root, protocols.STUDY_RETAINED_KEY
            )
            invocations = acquisition.retained_key_invocations(
                authorization,
                observed=observed,
                root=root,
                series_root=root / "series",
                official_home=root / "home",
                timeout_seconds=60,
            )
        control = invocations["control"]
        self.assertEqual(control.campaign, protocols.D3C_CONTROL_NAME)
        self.assertIn("--idle-confirmed", control.argv)

    def test_o09_acq_12_cross_engine_requires_exactly_three_trials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "raw").mkdir()
            authorization, observed = self._production_authorization(
                root, protocols.STUDY_CROSS_ENGINE
            )
            invocations = acquisition.cross_engine_invocations(
                authorization,
                observed=observed,
                root=support.REPO_ROOT,
                raw_root=root / "raw",
                corpus_dir=root / "corpus",
                timeout_seconds=60,
            )
        argv = list(invocations["run"].argv)
        self.assertIn("--trials", argv)
        self.assertEqual(argv[argv.index("--trials") + 1], "3")
        self.assertIn("--idle-confirmed", argv)
        self.assertNotIn("--allow-contended", argv)
        self.assertEqual(argv[argv.index("--corpus") + 1], str(Path(temporary) / "corpus"))


class SafePathTests(unittest.TestCase):
    def test_o09_acq_13_existing_output_path_is_never_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "campaign").write_text("existing", encoding="utf-8")
            with self.assertRaises(BenchError) as raised:
                acquisition.require_fresh_output(root, label="campaign")
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)

    def test_o09_acq_14_isolated_home_is_probed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            home.mkdir(mode=0o700)
            result = acquisition.probe_isolated_home(home=home)
            self.assertEqual(result["home"], str(home))
            self.assertTrue(result["archive_root"].endswith("benchmark-evidence"))

    def test_o09_acq_14b_isolated_home_mode_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            home.mkdir(mode=0o755)
            os.chmod(home, 0o755)
            with self.assertRaises(BenchError) as raised:
                acquisition.probe_isolated_home(home=home)
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_acq_14c_symlinked_home_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            real = Path(temporary) / "real"
            real.mkdir(mode=0o700)
            link = Path(temporary) / "link"
            os.symlink(real, link)
            with self.assertRaises(BenchError) as raised:
                acquisition.probe_isolated_home(home=link)
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_acq_15_contended_flag_is_refused_before_execution(self) -> None:
        invocation = acquisition.BackendInvocation(
            argv=("python3", "x.py", "--allow-contended"),
            cwd=Path("."),
            env={},
            timeout_seconds=1,
            output_path=Path("."),
            campaign=None,
        )
        with self.assertRaises(BenchError) as raised:
            acquisition.run_backend(invocation)
        self.assertEqual(raised.exception.code, BM_ACQUISITION_PROHIBITED)

    def test_o09_acq_16_bounded_backend_result_is_recorded(self) -> None:
        invocation = acquisition.BackendInvocation(
            argv=("python3", "-c", "print('measured'); raise SystemExit(3)"),
            cwd=Path("."),
            env=acquisition.sanitized_environment(),
            timeout_seconds=30,
            output_path=Path("."),
            campaign=None,
        )
        result = acquisition.run_backend(invocation)
        self.assertEqual(result.returncode, 3)
        self.assertIn("measured", result.stdout_tail)
        with self.assertRaises(BenchError) as raised:
            acquisition.require_backend_success(result, gate="fixture")
        self.assertEqual(raised.exception.code, BM_ACQUISITION_PROHIBITED)

    def test_o09_acq_16b_non_python_backend_is_refused(self) -> None:
        invocation = acquisition.BackendInvocation(
            argv=("/bin/sh", "-c", "true"),
            cwd=Path("."),
            env={},
            timeout_seconds=1,
            output_path=Path("."),
            campaign=None,
        )
        with self.assertRaises(BenchError) as raised:
            acquisition.run_backend(invocation)
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_acq_16c_raw_member_budget_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "member.json").write_text("{\"a\":1}", encoding="utf-8")
            self.assertTrue(
                acquisition.read_existing_raw(root, "member.json", max_bytes=64).startswith(b"{")
            )
            with self.assertRaises(BenchError) as raised:
                acquisition.read_existing_raw(root, "member.json", max_bytes=1)
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_acq_16d_status_record_shape_is_validated(self) -> None:
        record = {
            "state": "CONTROL_ACCEPTED",
            "study_id": "cross-engine-keyword-real-v1",
            "run_id": "11111111-1111-4111-8111-111111111111",
            "campaigns": ["control"],
            "failed_gate": None,
            "reasons": [],
        }
        self.assertEqual(acquisition.inspect_status(record)["state"], "CONTROL_ACCEPTED")
        record["state"] = "DONE"
        with self.assertRaises(BenchError):
            acquisition.inspect_status(record)

    def test_o09_acq_16e_preserved_partial_file_mode_is_not_modified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "partial.bin"
            path.write_bytes(b"partial")
            before = path.stat().st_mode & 0o777
            with self.assertRaises(BenchError):
                acquisition.require_fresh_output(Path(temporary), label="partial.bin")
            self.assertEqual(path.read_bytes(), b"partial")
            self.assertEqual(path.stat().st_mode & 0o777, before)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()


class G0AuthorityAcquisitionTests(unittest.TestCase):
    """G0F-02: production factories require a verified authorization capability."""

    def test_g0f_02_bare_freeze_is_rejected_by_the_retained_key_factory(self) -> None:
        freeze = support.make_freeze(study_id=protocols.STUDY_RETAINED_KEY)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / acquisition.D3C_T6_RECEIPT).parent.mkdir(parents=True)
            (root / acquisition.D3C_T6_RECEIPT).write_text("{}", encoding="utf-8")
            with self.assertRaises(BenchError) as raised:
                acquisition.retained_key_invocations(
                    freeze,
                    root=root,
                    series_root=root / "series",
                    official_home=root / "home",
                    timeout_seconds=60,
                )
            self.assertEqual(raised.exception.field_path, "authorization")

    def test_g0f_02b_bare_freeze_is_rejected_by_the_cross_engine_factory(self) -> None:
        freeze = support.make_freeze(study_id=protocols.STUDY_CROSS_ENGINE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "raw").mkdir()
            with self.assertRaises(BenchError) as raised:
                acquisition.cross_engine_invocations(
                    freeze,
                    root=support.REPO_ROOT,
                    raw_root=root / "raw",
                    corpus_dir=root / "corpus",
                    timeout_seconds=60,
                )
            self.assertEqual(raised.exception.field_path, "authorization")


class BackendLayoutTests(unittest.TestCase):
    """RF09-04 / LAY-01..09: the PR15D backend root is exactly ``raw_root/backend``."""

    def _invocations(self, root: Path):
        freeze = support.make_freeze(study_id=protocols.STUDY_CROSS_ENGINE)
        authorization = support.production_shaped_authorization(
            freeze, sandbox=root / "sandbox"
        )
        return acquisition.cross_engine_invocations(
            authorization,
            root=support.REPO_ROOT,
            raw_root=root / "raw",
            corpus_dir=root / "corpus",
            timeout_seconds=60,
            observed=support.authorization_observations(freeze),
        )

    def test_lay_01_factory_uses_the_backend_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "raw").mkdir()
            invocations = self._invocations(root)
        backend = root / "raw" / "backend"
        run_argv = list(invocations["run"].argv)
        validate_argv = list(invocations["validate"].argv)
        self.assertEqual(run_argv[run_argv.index("--out") + 1], str(backend))
        self.assertEqual(validate_argv[validate_argv.index("--run") + 1], str(backend))
        self.assertEqual(
            validate_argv[validate_argv.index("--out") + 1],
            str(backend / "validation.json"),
        )
        self.assertEqual(invocations["run"].output_path, backend)
        self.assertEqual(
            invocations["validate"].output_path, backend / "validation.json"
        )

    def test_lay_02_no_process_is_launched_by_the_factory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "raw").mkdir()
            self._invocations(root)
            self.assertFalse((root / "raw" / "backend").exists())

    def test_lay_04_existing_backend_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "raw" / "backend").mkdir(parents=True)
            (root / "raw" / "backend" / "keep.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(BenchError) as raised:
                self._invocations(root)
            self.assertEqual(raised.exception.code, "BM_PUBLICATION_CONFLICT")
            self.assertEqual(
                (root / "raw" / "backend" / "keep.txt").read_text(encoding="utf-8"), "keep"
            )

    def test_lay_05_symlinked_backend_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "raw").mkdir()
            (root / "elsewhere").mkdir()
            os.symlink(root / "elsewhere", root / "raw" / "backend")
            with self.assertRaises(BenchError) as raised:
                self._invocations(root)
            self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")

    def test_lay_09_factory_never_runs_before_verified_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises((TypeError, BenchError)):
                acquisition.cross_engine_invocations(
                    object(),
                    root=support.REPO_ROOT,
                    raw_root=root / "raw",
                    corpus_dir=root / "corpus",
                    timeout_seconds=60,
                )
