"""SCOPE-01…SCOPE-03 and CLI-01: synthetic/real isolation and no side effects."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest import mock

from quervant_bench import cli
from quervant_bench.config.contracts import BuildIdentity, load_experiment_bundle
from quervant_bench.config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_IDENTITY_INVALID,
    BenchError,
)
from quervant_bench.execution import (
    LogicalClock,
    ScenarioReadinessProvider,
    SimulatedCapabilityProvider,
    execute_synthetic,
    load_synthetic_scenario,
    replay_sealed_synthetic,
    synthetic_adapter_factory,
)
from quervant_bench.host import capabilities as host_capabilities

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
SCENARIO_NAME = "synthetic-scenario.v1.json"


def load_bundle():
    return load_experiment_bundle("synthetic-execution-smoke", EXPERIMENTS)


class ScopeTestBase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "out"
        self.output.mkdir()
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        shutil.copy(FIXTURES / SCENARIO_NAME, self.evidence / SCENARIO_NAME)
        self.bundle = load_bundle()
        self.scenario = load_synthetic_scenario(self.evidence, bundle=self.bundle)

    def run_default(self, **overrides):
        parameters = {
            "bundle": self.bundle,
            "scenario": self.scenario,
            "run_id": str(uuid.uuid4()),
            "evidence_root": self.evidence,
            "output_base": self.output,
            "adapter_factory": synthetic_adapter_factory(self.bundle),
            "capability_provider": SimulatedCapabilityProvider(),
            "readiness_provider": ScenarioReadinessProvider(self.scenario),
            "clock": LogicalClock(),
        }
        parameters.update(overrides)
        return execute_synthetic(**parameters)


class ScopeTests(ScopeTestBase):
    def test_scope_01_real_build_identity_is_refused_before_any_effect(self) -> None:
        real_bundle = replace(
            self.bundle,
            adapter=replace(
                self.bundle.adapter,
                build_identity=BuildIdentity(
                    kind="source-and-binary",
                    source_digest="sha256:" + "0" * 64,
                    executable_digest="sha256:" + "1" * 64,
                ),
            ),
        )
        calls = {"factory": 0, "readiness": 0, "capability": 0}

        def factory(assignment, slot, scenario):
            calls["factory"] += 1
            return synthetic_adapter_factory(self.bundle)(assignment, slot, scenario)

        class CountingReadiness(ScenarioReadinessProvider):
            def next_observations(self, campaign_kind, campaign_index):
                calls["readiness"] += 1
                return super().next_observations(campaign_kind, campaign_index)

        class CountingCapability(SimulatedCapabilityProvider):
            def platform_record(self):
                calls["capability"] += 1
                return super().platform_record()

        with mock.patch.object(os, "mkdir", wraps=os.mkdir) as guarded:
            with self.assertRaises(BenchError) as caught:
                self.run_default(
                    bundle=real_bundle,
                    adapter_factory=factory,
                    readiness_provider=CountingReadiness(self.scenario),
                    capability_provider=CountingCapability(),
                )
        self.assertEqual(caught.exception.code, BM_ACQUISITION_PROHIBITED)
        self.assertEqual(calls, {"factory": 0, "readiness": 0, "capability": 0})
        self.assertEqual(guarded.call_count, 0)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_scope_01_forged_official_scope_is_refused(self) -> None:
        forged = replace(self.scenario, qualification_scope="official")
        with self.assertRaises(BenchError) as caught:
            self.run_default(scenario=forged)
        self.assertEqual(caught.exception.code, BM_ACQUISITION_PROHIBITED)
        self.assertEqual(list(self.output.iterdir()), [])

        document = json.loads((FIXTURES / SCENARIO_NAME).read_bytes())
        document["evidence_origin"] = "real"
        document["qualification_scope"] = "official"
        from quervant_bench.config.codec import canonical_document_bytes

        (self.evidence / SCENARIO_NAME).write_bytes(canonical_document_bytes(document))
        with self.assertRaises(BenchError) as caught:
            load_synthetic_scenario(self.evidence, bundle=self.bundle)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_scope_02_relabelled_evidence_is_rejected_by_replay(self) -> None:
        result = self.run_default()
        self.assertEqual(result.status, "sealed")
        seal = json.loads((result.run_dir / "seal.json").read_bytes())
        seal["evidence_origin"] = "real"
        seal["qualification_scope"] = "official"
        from quervant_bench.config.codec import canonical_document_bytes

        (result.run_dir / "seal.json").write_bytes(canonical_document_bytes(seal))
        with self.assertRaises(BenchError):
            replay_sealed_synthetic(
                result.run_dir, bundle=self.bundle, scenario_root=self.evidence
            )

        freeze = json.loads((result.run_dir / "freeze.json").read_bytes())
        freeze["evidence_origin"] = "real"
        freeze["qualification_scope"] = "official"
        (result.run_dir / "freeze.json").write_bytes(canonical_document_bytes(freeze))
        with self.assertRaises(BenchError):
            replay_sealed_synthetic(
                result.run_dir, bundle=self.bundle, scenario_root=self.evidence
            )

    def test_scope_03_successful_paths_never_touch_clocks_processes_or_the_host(self) -> None:
        def forbidden(*_args, **_kwargs):
            raise AssertionError("a real clock, process or host probe was used")

        with (
            mock.patch.object(time, "time", forbidden),
            mock.patch.object(time, "perf_counter", forbidden),
            mock.patch.object(time, "monotonic", forbidden),
            mock.patch.object(subprocess, "Popen", forbidden),
            mock.patch.object(subprocess, "run", forbidden),
            mock.patch.object(os, "system", forbidden),
            mock.patch.object(host_capabilities.LinuxCapabilityProvider, "read_text", forbidden),
            mock.patch.object(
                host_capabilities.LinuxCapabilityProvider, "allowed_cpu_ids", forbidden
            ),
            mock.patch.object(
                host_capabilities.LinuxCapabilityProvider, "platform_record", forbidden
            ),
            mock.patch.object(cli, "dispatch", forbidden),
        ):
            result = self.run_default()
            self.assertEqual(result.status, "sealed")
            replay = replay_sealed_synthetic(
                result.run_dir, bundle=self.bundle, scenario_root=self.evidence
            )
            self.assertEqual(replay.slots_completed, 24)


class CliTests(ScopeTestBase):
    def test_cli_01_run_remains_unconditionally_prohibited(self) -> None:
        out = self.root / "never-created"
        arguments = [
            "run",
            "--experiment",
            "synthetic-execution-smoke",
            "--protocol",
            "protocol.yaml",
            "--out",
            str(out),
        ]
        stderr = io.StringIO()
        with (
            mock.patch.object(subprocess, "Popen", side_effect=AssertionError("spawned")),
            mock.patch.object(os, "system", side_effect=AssertionError("spawned")),
            mock.patch(
                "quervant_bench.config.codec.load_document",
                side_effect=AssertionError("read a document"),
            ),
            redirect_stderr(stderr),
        ):
            status = cli.main(arguments)
        self.assertEqual(status, 77)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["code"], BM_ACQUISITION_PROHIBITED)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["data"]["kind"], "error-detail")
        self.assertFalse(out.exists())

    def test_cli_01_help_and_version_remain_safe(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = cli.main(["--version"])
        self.assertEqual(status, 0)
        self.assertIn("quervant-bench", stdout.getvalue())


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
