"""O09-ACQ / O09-SAFE: bounded legacy backend invocation restrictions."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_PUBLICATION_CONFLICT,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.official import acquisition, protocols
from quervant_bench.tests import official_support as support


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

    def test_o09_acq_10_invocation_order_is_the_frozen_sequence(self) -> None:
        freeze = support.make_freeze(study_id=protocols.STUDY_RETAINED_KEY)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / acquisition.D3C_T6_RECEIPT).parent.mkdir(parents=True)
            (root / acquisition.D3C_T6_RECEIPT).write_text("{}", encoding="utf-8")
            invocations = acquisition.retained_key_invocations(
                freeze,
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
        freeze = support.make_freeze(study_id=protocols.STUDY_RETAINED_KEY)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / acquisition.D3C_T6_RECEIPT).parent.mkdir(parents=True)
            (root / acquisition.D3C_T6_RECEIPT).write_text("{}", encoding="utf-8")
            invocations = acquisition.retained_key_invocations(
                freeze,
                root=root,
                series_root=root / "series",
                official_home=root / "home",
                timeout_seconds=60,
            )
        control = invocations["control"]
        self.assertEqual(control.campaign, protocols.D3C_CONTROL_NAME)
        self.assertIn("--idle-confirmed", control.argv)

    def test_o09_acq_12_cross_engine_requires_exactly_three_trials(self) -> None:
        freeze = support.make_freeze(study_id=protocols.STUDY_CROSS_ENGINE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invocations = acquisition.cross_engine_invocations(
                freeze,
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
