"""HOST-01…HOST-05: injected, read-only host capability snapshots."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from quervant_bench import host
from quervant_bench.host.capabilities import (
    collect_host_capabilities,
    validate_host_capabilities,
)

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "evidence-admission"
    / "raw"
    / "environment.json"
)

_NATIVE_PROC_VERSION = (
    "Linux version 6.8.0-synthetic (synthetic@build) #1 SMP\n"
)


class FakeProvider:
    def __init__(
        self,
        *,
        system: str = "Linux",
        machine: str = "x86_64",
        kernel: str = "6.8.0-synthetic",
        cpus: tuple[int, ...] = (2, 0),
        proc_version: str | None = _NATIVE_PROC_VERSION,
        topology: dict[int, tuple[str | None, str | None, str | None]] | None = None,
    ) -> None:
        self._system = system
        self._machine = machine
        self._kernel = kernel
        self._cpus = cpus
        self._proc_version = proc_version
        self._topology = topology or {
            0: ("0", "0", "0"),
            2: ("0", "1", "2"),
        }
        self.calls: list[str] = []

    def read_text(self, relative_system_path: str) -> str | None:
        self.calls.append(relative_system_path)
        if relative_system_path == "/proc/version":
            return self._proc_version
        if relative_system_path.startswith("/sys/devices/system/cpu/cpu"):
            import re

            match = re.search(r"/cpu(\d+)/", relative_system_path)
            assert match is not None
            cpu = int(match.group(1))
            field = relative_system_path.rsplit("/", 1)[1]
            values = self._topology.get(cpu)
            if values is None:
                return None
            index = {
                "physical_package_id": 0,
                "core_id": 1,
                "thread_siblings_list": 2,
            }[field]
            return values[index]
        return None

    def allowed_cpu_ids(self) -> tuple[int, ...]:
        return self._cpus

    def platform_record(self) -> tuple[str, str, str]:
        return (self._system, self._machine, self._kernel)


class HostCapabilityTests(unittest.TestCase):
    def test_host_01_native_linux_snapshot_matches_golden(self) -> None:
        snapshot = collect_host_capabilities(FakeProvider())
        self.assertEqual(snapshot["environment"], "native-linux")
        self.assertEqual(snapshot["allowed_cpus"], [0, 2])
        self.assertEqual(
            [entry["core_id"] for entry in snapshot["cpu_topology"]], [0, 1]
        )
        self.assertEqual(snapshot["missing_fields"], [])
        validate_host_capabilities(snapshot)
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(snapshot, golden)
        self.assertEqual(
            collect_host_capabilities(FakeProvider()), snapshot
        )

    def test_host_02_wsl2_is_detected_and_tagged(self) -> None:
        provider = FakeProvider(
            kernel="5.15.90.1-microsoft-standard-WSL2",
            proc_version="Linux version 5.15.90.1-microsoft-standard-WSL2\n",
        )
        snapshot = collect_host_capabilities(provider)
        self.assertEqual(snapshot["environment"], "wsl2")
        self.assertEqual(snapshot["allowed_cpus"], [0, 2])
        self.assertEqual(snapshot["cpu_topology"], collect_host_capabilities(FakeProvider())["cpu_topology"])

    def test_host_03_unsupported_or_missing_topology(self) -> None:
        unsupported = collect_host_capabilities(
            FakeProvider(system="Windows", machine="AMD64", kernel="10.0")
        )
        self.assertEqual(unsupported["environment"], "unsupported")
        self.assertEqual(unsupported["allowed_cpus"], [0, 2])

        missing = collect_host_capabilities(
            FakeProvider(cpus=(), topology={})
        )
        self.assertIn("allowed_cpus", missing["missing_fields"])
        self.assertEqual(missing["cpu_topology"], [])

        partial = collect_host_capabilities(
            FakeProvider(cpus=(0,), topology={0: ("0", None, None)})
        )
        self.assertEqual(partial["cpu_topology"], [])
        self.assertIn("cpu_topology.cpu0.core_id", partial["missing_fields"])
        self.assertIn("cpu_topology.cpu0.siblings", partial["missing_fields"])

        bad_topology = collect_host_capabilities(
            FakeProvider(
                cpus=(0,),
                topology={0: ("not-an-int", "1", "0")},
            )
        )
        self.assertEqual(bad_topology["cpu_topology"], [])
        self.assertIn(
            "cpu_topology.cpu0.package_id", bad_topology["missing_fields"]
        )

    def test_host_04_unordered_cpus_are_sorted_without_affinity_changes(self) -> None:
        with mock.patch.object(
            host.capabilities.os,
            "sched_setaffinity",
            side_effect=AssertionError("affinity must not be mutated"),
            create=True,
        ):
            snapshot = collect_host_capabilities(
                FakeProvider(cpus=(8, 0, 4, 0))
            )
        self.assertEqual(snapshot["allowed_cpus"], [0, 4, 8])
        validate_host_capabilities(snapshot)

    def test_host_05_no_clock_or_subprocess_is_consulted(self) -> None:
        with mock.patch("time.time", side_effect=AssertionError("no clock")), mock.patch(
            "time.perf_counter", side_effect=AssertionError("no clock")
        ), mock.patch(
            "subprocess.run", side_effect=AssertionError("no subprocess")
        ):
            snapshot = collect_host_capabilities(FakeProvider())
        self.assertEqual(snapshot["environment"], "native-linux")

    def test_host_closed_shape_rejects_mutation(self) -> None:
        snapshot = collect_host_capabilities(FakeProvider())
        tampered = dict(snapshot)
        tampered["authorized"] = True
        with self.assertRaises(Exception):
            validate_host_capabilities(tampered)
        tampered = dict(snapshot)
        tampered["allowed_cpus"] = [2, 0]
        with self.assertRaises(Exception):
            validate_host_capabilities(tampered)


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
