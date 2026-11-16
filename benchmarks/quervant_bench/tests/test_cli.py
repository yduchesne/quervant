"""CLI contract tests: determinism, safe inspection and fail-closed verbs.

Covers CLI-01..CLI-11.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quervant_bench import cli
from quervant_bench.config.codec import content_digest, load_document
from quervant_bench.config.contracts import validate_outcome
from quervant_bench.config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_EVIDENCE_UNAVAILABLE,
    BM_FILE_MISSING,
    BM_INTERNAL_ERROR,
    BM_NOT_IMPLEMENTED,
    BM_UNSAFE_INPUT,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "synthetic-contract-smoke"
EXPERIMENT_ID = "synthetic-contract-smoke"
FIXTURE_FILES = ("experiment.yaml", "workloads.yaml", "protocol.yaml", "adapter.yaml")
RUN_ID = "00000000-0000-4000-8000-000000000001"
RESERVED = ("validate", "analyze", "verify", "accept", "report")


def _golden() -> str:
    return (FIXTURES / "inspect.golden.json").read_text(encoding="utf-8")


def _write_tree(root: Path, mutate=None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    documents = {name: load_document(FIXTURES / name) for name in FIXTURE_FILES}
    if mutate is not None:
        mutate(documents)
    for name, document in documents.items():
        (root / name).write_text(json.dumps(document, indent=2), encoding="utf-8")
    return root


class CliContractTests(unittest.TestCase):
    def run_cli(self, argv) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def assertErrorEnvelope(self, stderr: str, expected_code: str) -> dict:
        payload = json.loads(stderr)
        validate_outcome(payload)
        self.assertEqual(payload["code"], expected_code)
        self.assertEqual(payload["data"]["kind"], "error-detail")
        self.assertNotIn("Traceback", stderr)
        return payload

    # -- CLI-01 / CLI-02 ---------------------------------------------------

    def test_cli_01_inspect_is_byte_deterministic(self) -> None:
        first = self.run_cli(["inspect", "--experiment", EXPERIMENT_ID, "--format", "json"])
        second = self.run_cli(["inspect", "--experiment", EXPERIMENT_ID, "--format", "json"])
        self.assertEqual(first[0], 0)
        self.assertEqual(second[0], 0)
        self.assertEqual(first[1], _golden())
        self.assertEqual(second[1], first[1])
        self.assertEqual(first[2], "")
        validate_outcome(json.loads(first[1]))
        self.assertFalse(Path("benchmark-results").exists())

    def test_cli_01_summary_is_derived_from_validated_documents(self) -> None:
        code, stdout, _stderr = self.run_cli(["inspect", "--experiment", EXPERIMENT_ID])
        self.assertEqual(code, 0)
        summary = json.loads(stdout)["data"]
        protocol = load_document(FIXTURES / "protocol.yaml")
        workload = load_document(FIXTURES / "workloads.yaml")
        experiment = load_document(FIXTURES / "experiment.yaml")
        self.assertEqual(summary["protocol_digest"], content_digest(protocol))
        self.assertEqual(summary["workload_id"], workload["workload_id"])
        self.assertEqual(
            summary["lane_ids"], [lane["lane_id"] for lane in workload["lanes"]]
        )
        self.assertEqual(
            summary["arm_ids"], [arm["arm_id"] for arm in experiment["arms"]]
        )
        self.assertEqual(summary["evidence_origin"], "synthetic")
        self.assertEqual(summary["qualification_scope"], "simulated")

    def test_cli_02_help_and_version_are_safe(self) -> None:
        code, stdout, stderr = self.run_cli(["--version"])
        self.assertEqual((code, stderr), (0, ""))
        self.assertIn("quervant-bench", stdout)
        self.assertIn("0.1.0", stdout)

        code, stdout, stderr = self.run_cli(["--help"])
        self.assertEqual((code, stderr), (0, ""))
        for verb in ("inspect", "validate", "run", "analyze", "verify", "accept", "report"):
            self.assertIn(verb, stdout)

    def test_cli_02_module_entrypoint_matches_console_contract(self) -> None:
        module = subprocess.run(
            [sys.executable, "-m", "quervant_bench", "inspect", "--experiment", EXPERIMENT_ID],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(module.returncode, 0, module.stderr)
        self.assertEqual(module.stdout, _golden())

        scripts_dir = Path(sysconfig.get_path("scripts")) / "quervant-bench"
        if not scripts_dir.exists():
            self.skipTest("console script is not installed in this interpreter")
        console = subprocess.run(
            [str(scripts_dir), "inspect", "--experiment", EXPERIMENT_ID],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(console.returncode, 0, console.stderr)
        self.assertEqual(console.stdout, _golden())

    # -- CLI-03 ------------------------------------------------------------

    def test_cli_03_run_is_prohibited_before_any_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                with (
                    mock.patch.object(
                        cli.contracts,
                        "load_experiment_bundle",
                        side_effect=AssertionError("protocol/source was opened"),
                    ),
                    mock.patch(
                        "pathlib.Path.read_bytes",
                        side_effect=AssertionError("file was read"),
                    ),
                    mock.patch(
                        "pathlib.Path.write_bytes",
                        side_effect=AssertionError("file was written"),
                    ),
                    mock.patch(
                        "pathlib.Path.mkdir", side_effect=AssertionError("mkdir happened")
                    ),
                    mock.patch(
                        "subprocess.Popen", side_effect=AssertionError("child started")
                    ),
                    mock.patch(
                        "subprocess.run", side_effect=AssertionError("child started")
                    ),
                    mock.patch(
                        "time.monotonic", side_effect=AssertionError("clock touched")
                    ),
                    mock.patch("time.time", side_effect=AssertionError("clock touched")),
                ):
                    code, stdout, stderr = self.run_cli(
                        [
                            "run",
                            "--experiment",
                            EXPERIMENT_ID,
                            "--protocol",
                            "protocol.yaml",
                            "--out",
                            "benchmark-results/out",
                        ]
                    )
                self.assertEqual(code, 77)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    self.assertErrorEnvelope(stderr, BM_ACQUISITION_PROHIBITED)["status"],
                    "blocked",
                )
                self.assertFalse(Path("benchmark-results").exists())
            finally:
                os.chdir(previous)

    # -- CLI-04 / CLI-05 / CLI-06 / CLI-07 ---------------------------------

    def test_cli_04_reserved_verbs_are_typed_unimplemented(self) -> None:
        for verb in RESERVED:
            code, stdout, stderr = self.run_cli([verb, "--run", RUN_ID])
            self.assertEqual(code, 69, verb)
            self.assertEqual(stdout, "", verb)
            payload = self.assertErrorEnvelope(stderr, BM_NOT_IMPLEMENTED)
            self.assertEqual(payload["status"], "blocked")
            self.assertFalse(Path("benchmark-results").exists())

    def test_cli_05_malformed_commands_return_usage(self) -> None:
        for argv in (
            [],
            ["bogus"],
            ["inspect"],
            ["inspect", "--experiment", EXPERIMENT_ID, "--format", "yaml"],
            ["validate"],
            ["run", "--experiment", EXPERIMENT_ID],
        ):
            code, stdout, stderr = self.run_cli(argv)
            self.assertEqual(code, 64, argv)
            self.assertEqual(stdout, "", argv)
            self.assertEqual(json.loads(stderr)["code"], "BM_USAGE")

    def test_cli_06_unknown_experiment_returns_missing_input(self) -> None:
        code, stdout, stderr = self.run_cli(
            ["inspect", "--experiment", "no-such-experiment"]
        )
        self.assertEqual((code, stdout), (66, ""))
        payload = self.assertErrorEnvelope(stderr, BM_FILE_MISSING)
        self.assertEqual(payload["data"]["reason"], "missing-input")

    def test_cli_07_changed_input_fails_closed(self) -> None:
        def mutate(documents):
            documents["protocol.yaml"]["workload_digest"] = "sha256:" + "0" * 64

        with tempfile.TemporaryDirectory() as tmp:
            experiments = Path(tmp) / "experiments"
            _write_tree(experiments / EXPERIMENT_ID, mutate)
            with mock.patch.object(cli, "_experiments_root", return_value=experiments):
                code, stdout, stderr = self.run_cli(
                    ["inspect", "--experiment", EXPERIMENT_ID]
                )
        self.assertEqual((code, stdout), (65, ""))
        self.assertEqual(json.loads(stderr)["code"], "BM_IDENTITY_INVALID")

    # -- CLI-08 / CLI-09 / CLI-10 / CLI-11 ---------------------------------

    def test_cli_08_traversal_and_symlinks_fail_closed(self) -> None:
        code, _stdout, stderr = self.run_cli(["inspect", "--experiment", "../escape"])
        self.assertEqual(code, 65)
        self.assertEqual(json.loads(stderr)["code"], "BM_IDENTITY_INVALID")

        with tempfile.TemporaryDirectory() as tmp:
            experiments = Path(tmp) / "experiments"
            root = experiments / EXPERIMENT_ID
            _write_tree(root)
            original = root / "workloads.yaml"
            target = Path(tmp) / "workloads.yaml"
            target.write_bytes(original.read_bytes())
            original.unlink()
            original.symlink_to(target)
            with mock.patch.object(cli, "_experiments_root", return_value=experiments):
                code, _stdout, stderr = self.run_cli(
                    ["inspect", "--experiment", EXPERIMENT_ID]
                )
        self.assertEqual(code, 65)
        self.assertEqual(json.loads(stderr)["code"], BM_UNSAFE_INPUT)

        with tempfile.TemporaryDirectory() as tmp:
            experiments = Path(tmp) / "experiments"
            experiments.mkdir()
            real = Path(tmp) / "real-experiment"
            _write_tree(real)
            (experiments / EXPERIMENT_ID).symlink_to(real)
            with mock.patch.object(cli, "_experiments_root", return_value=experiments):
                code, _stdout, stderr = self.run_cli(
                    ["inspect", "--experiment", EXPERIMENT_ID]
                )
        self.assertEqual(code, 65)
        self.assertEqual(json.loads(stderr)["code"], BM_UNSAFE_INPUT)

    def test_cli_09_errors_leak_no_secrets_or_tracebacks(self) -> None:
        secret = "supersecret-environment-value"
        os.environ["QUERVANT_FAKE_SECRET"] = secret
        try:
            _code, _stdout, stderr = self.run_cli(
                ["inspect", "--experiment", "no-such-experiment"]
            )
            self.assertNotIn(secret, stderr)
            self.assertNotIn("Traceback", stderr)
            self.assertNotIn(os.getcwd(), stderr)

            with mock.patch.object(
                cli.contracts,
                "load_experiment_bundle",
                side_effect=RuntimeError(f"boom {secret}"),
            ):
                code, _stdout, stderr = self.run_cli(
                    ["inspect", "--experiment", EXPERIMENT_ID]
                )
            self.assertEqual(code, 70)
            self.assertFalse(stderr.strip() == "")
            payload = json.loads(stderr)
            self.assertEqual(payload["code"], BM_INTERNAL_ERROR)
            self.assertNotIn(secret, stderr)
            self.assertNotIn("boom", stderr)
            self.assertNotIn("Traceback", stderr)
        finally:
            del os.environ["QUERVANT_FAKE_SECRET"]

    def test_cli_10_offline_flag_requires_a_safe_workspace(self) -> None:
        for verb in RESERVED:
            code, stdout, stderr = self.run_cli([verb, "--run", RUN_ID])
            self.assertEqual((code, stdout), (69, ""), verb)
            self.assertEqual(json.loads(stderr)["code"], BM_NOT_IMPLEMENTED)
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            with mock.patch.dict(
                os.environ,
                {"QUERVANT_BENCH_OFFLINE_WORKSPACE": str(missing)},
                clear=False,
            ):
                for verb in RESERVED:
                    code, stdout, stderr = self.run_cli(
                        [verb, "--run", RUN_ID, "--offline"]
                    )
                    self.assertEqual((code, stdout), (69, ""), verb)
                    self.assertEqual(
                        json.loads(stderr)["code"], BM_EVIDENCE_UNAVAILABLE
                    )
        code, _stdout, stderr = self.run_cli(
            ["inspect", "--experiment", EXPERIMENT_ID, "--offline"]
        )
        self.assertEqual(code, 64)
        self.assertEqual(json.loads(stderr)["code"], "BM_USAGE")

    def test_cli_11_inspect_never_creates_a_results_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                code, _stdout, _stderr = self.run_cli(
                    ["inspect", "--experiment", EXPERIMENT_ID]
                )
                self.assertEqual(code, 0)
                self.assertEqual(sorted(os.listdir(tmp)), [])
            finally:
                os.chdir(previous)

    def test_error_outcomes_validate_against_the_outcome_schema(self) -> None:
        for argv, expected in (
            (["run", "--experiment", EXPERIMENT_ID, "--protocol", "p", "--out", "o"], 77),
            (["validate", "--run", RUN_ID], 69),
            (["bogus"], 64),
            (["inspect", "--experiment", "missing-one"], 66),
        ):
            code, _stdout, stderr = self.run_cli(argv)
            self.assertEqual(code, expected)
            validate_outcome(json.loads(stderr))


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
