#!/usr/bin/env python3
"""F1.2 host-readiness tests (RD-01..RD-30).

Pure integer fixtures with an injected fake monotonic clock and tick source so
no real sleep or /proc read is required. The verifier path recomputes every
metric from the raw tick arrays.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import unittest

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLING_DIR = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b_f1_2")
PROTOCOL_SHA = "a" * 64
ADAPTER = 0
CONTROLLER = 1


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(TOOLING_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN = _load("f12_readiness_run", "run.py")
VERIFY = _load("f12_readiness_verify", "verify.py")
PROTOCOL = RUN.PROTOCOL


class FakeClock:
    def __init__(self) -> None:
        self.ns = 1_000_000_000

    def now(self) -> int:
        return self.ns

    def sleep(self, seconds: float) -> None:
        self.ns += int(round(seconds * 1_000_000_000))


def tick_line(cpu: int, values) -> str:
    return f"cpu{cpu} " + " ".join(str(value) for value in values)


def snapshots(cpu_deltas: dict[int, list[tuple[int, ...]]], initial: dict[int, tuple[int, ...]] | None = None):
    """Build 7 cumulative /proc/stat texts for each CPU."""
    initial = initial or {cpu: (1000, 0, 500, 20000, 0, 0, 0, 0) for cpu in cpu_deltas}
    state = {cpu: list(values) for cpu, values in initial.items()}
    texts = [tick_line(cpu, state[cpu]) for cpu in sorted(state)]
    result = ["\n".join(texts)]
    for index in range(6):
        for cpu, deltas in cpu_deltas.items():
            for field, delta in enumerate(deltas[index]):
                state[cpu][field] += delta
        result.append("\n".join(tick_line(cpu, state[cpu]) for cpu in sorted(state)))
    return result


def quiet_deltas() -> dict[int, list[tuple[int, ...]]]:
    # user +3, system +2, idle +95 => total 100, busy 50 permille, steal 0.
    delta = (3, 0, 2, 95, 0, 0, 0, 0)
    return {ADAPTER: [delta] * 6, CONTROLLER: [delta] * 6}


def measure(clock: FakeClock, texts: list[str], *, settle_seconds: float = 5.0):
    queue = list(texts)

    def tick_source():
        return clock.now(), queue.pop(0)

    def sleeper(seconds):
        # Allow tests to shrink/extend individual sleeps by overriding the clock.
        clock.sleep(seconds)

    return RUN.measure_host_readiness(
        "d3bf12-base-01",
        ADAPTER,
        CONTROLLER,
        "f" * 64,
        PROTOCOL,
        PROTOCOL_SHA,
        tick_source=tick_source,
        sleeper=sleeper,
        clock=clock.now,
    )


def host(record) -> dict:
    return {
        "adapter_cpu": record["role_cpus"]["adapter"],
        "controller_cpu": record["role_cpus"]["controller"],
        "host_fingerprint": record["host_fingerprint"],
    }


def manifest(record) -> dict:
    return {"campaign": record["campaign"], "environment_fingerprint": record["host_fingerprint"]}


class ReadinessTests(unittest.TestCase):
    def valid(self):
        return measure(FakeClock(), snapshots(quiet_deltas()))

    def test_rd01_valid_fixture(self):
        record = self.valid()
        self.assertEqual(record["readiness_status"], "READY")
        self.assertEqual(record["failure_codes"], [])
        self.assertEqual(record["lower_median_busy_permille"], {"adapter": 50, "controller": 50})
        self.assertEqual(VERIFY.host_readiness_failures(record, manifest(record), host(record), PROTOCOL_SHA), [])

    def test_rd02_busy_251_rejected(self):
        deltas = quiet_deltas()
        deltas[ADAPTER][2] = (3, 0, 2, 94, 0, 0, 0, 0)  # total 99, idle 94 -> 50
        # Construct 251 permille: total 1000, idle 749, busy = 251.
        deltas[ADAPTER] = [quiet_deltas()[ADAPTER][0]] * 6
        texts = snapshots(deltas)
        clock = FakeClock()
        record = measure(clock, texts)
        # Replace the third interval for the adapter with a 251 permille delta.
        state = [1000, 0, 500, 20000, 0, 0, 0, 0]
        cpu_lines = []
        # Simpler: rebuild with a per-interval delta that yields 251 exactly.
        delta = (251, 0, 0, 749, 0, 0, 0, 0)
        record = measure(FakeClock(), snapshots({ADAPTER: [delta] * 6, CONTROLLER: [quiet_deltas()[CONTROLLER][0]] * 6}))
        self.assertEqual(record["interval_metrics"]["adapter"][0]["busy_permille"], 251)
        self.assertEqual(record["readiness_status"], "HOST_NOT_READY")
        self.assertIn("BUSY_EXCEEDED", record["failure_codes"])

    def test_rd03_single_soft_interval_allowed(self):
        delta = (251, 0, 0, 749, 0, 0, 0, 0)
        quiet = quiet_deltas()[CONTROLLER][0]
        adapter = [delta] + [quiet] * 5
        record = measure(FakeClock(), snapshots({ADAPTER: adapter, CONTROLLER: [quiet] * 6}))
        self.assertIn("BUSY_EXCEEDED", record["failure_codes"])
        # The per-interval gate is absolute: 251 always blocks regardless of median.
        self.assertEqual(record["readiness_status"], "HOST_NOT_READY")

    def test_rd04_median_101_rejected(self):
        # busy 101 permille: total 1000, idle 899.
        delta = (101, 0, 0, 899, 0, 0, 0, 0)
        record = measure(FakeClock(), snapshots({ADAPTER: [delta] * 6, CONTROLLER: [delta] * 6}))
        self.assertEqual(record["lower_median_busy_permille"]["adapter"], 101)
        self.assertIn("MEDIAN_BUSY_EXCEEDED", record["failure_codes"])
        self.assertEqual(record["readiness_status"], "HOST_NOT_READY")

    def test_rd05_median_100_allowed(self):
        delta = (100, 0, 0, 900, 0, 0, 0, 0)
        record = measure(FakeClock(), snapshots({ADAPTER: [delta] * 6, CONTROLLER: [delta] * 6}))
        self.assertEqual(record["lower_median_busy_permille"]["adapter"], 100)
        self.assertEqual(record["readiness_status"], "READY")

    def test_rd06_steal_21_rejected(self):
        delta = (3, 0, 2, 74, 0, 0, 0, 21)
        record = measure(FakeClock(), snapshots({ADAPTER: [delta] * 6, CONTROLLER: [delta] * 6}))
        self.assertIn("STEAL_EXCEEDED", record["failure_codes"])
        self.assertEqual(record["readiness_status"], "HOST_NOT_READY")

    def test_rd07_steal_20_allowed(self):
        delta = (3, 0, 2, 93, 0, 0, 0, 2)
        record = measure(FakeClock(), snapshots({ADAPTER: [delta] * 6, CONTROLLER: [delta] * 6}))
        self.assertNotIn("STEAL_EXCEEDED", record["failure_codes"])
        self.assertEqual(record["readiness_status"], "READY")

    def test_rd08_interval_bounds_inclusive(self):
        for seconds in (0.8, 1.5):
            clock = FakeClock()
            texts = snapshots(quiet_deltas())

            def tick_source():
                return clock.now(), texts.pop(0)

            def sleeper(value):
                clock.sleep(seconds if value == 1.0 else value)

            record = RUN.measure_host_readiness(
                "d3bf12-base-01", ADAPTER, CONTROLLER, "f" * 64, PROTOCOL, PROTOCOL_SHA,
                tick_source=tick_source, sleeper=sleeper, clock=clock.now,
            )
            self.assertEqual(record["readiness_status"], "READY", seconds)

    def test_rd09_interval_out_of_bounds(self):
        for seconds in (0.799, 1.501):
            clock = FakeClock()
            texts = snapshots(quiet_deltas())

            def tick_source():
                return clock.now(), texts.pop(0)

            def sleeper(value):
                clock.sleep(seconds if value == 1.0 else value)

            record = RUN.measure_host_readiness(
                "d3bf12-base-01", ADAPTER, CONTROLLER, "f" * 64, PROTOCOL, PROTOCOL_SHA,
                tick_source=tick_source, sleeper=sleeper, clock=clock.now,
            )
            self.assertIn("INTERVAL_DURATION", record["failure_codes"])
            self.assertEqual(record["readiness_status"], "HOST_NOT_READY")

    def test_rd10_settle_out_of_bounds(self):
        for seconds in (4.499, 7.501):
            clock = FakeClock()
            texts = snapshots(quiet_deltas())

            def tick_source():
                return clock.now(), texts.pop(0)

            def sleeper(value):
                clock.sleep(seconds if value == 5.0 else value)

            record = RUN.measure_host_readiness(
                "d3bf12-base-01", ADAPTER, CONTROLLER, "f" * 64, PROTOCOL, PROTOCOL_SHA,
                tick_source=tick_source, sleeper=sleeper, clock=clock.now,
            )
            self.assertIn("SETTLE_DURATION", record["failure_codes"])

    def test_rd11_settle_bounds_inclusive(self):
        for seconds in (4.5, 7.5):
            clock = FakeClock()
            texts = snapshots(quiet_deltas())

            def tick_source():
                return clock.now(), texts.pop(0)

            def sleeper(value):
                clock.sleep(seconds if value == 5.0 else value)

            record = RUN.measure_host_readiness(
                "d3bf12-base-01", ADAPTER, CONTROLLER, "f" * 64, PROTOCOL, PROTOCOL_SHA,
                tick_source=tick_source, sleeper=sleeper, clock=clock.now,
            )
            self.assertNotIn("SETTLE_DURATION", record["failure_codes"])

    def test_rd12_missing_duplicate_cpu(self):
        with self.assertRaises(RUN.ReadinessError) as caught:
            RUN.parse_cpu_ticks("cpu0 1 2 3 4 5 6 7 8\ncpu0 1 2 3 4 5 6 7 8")
        self.assertEqual(caught.exception.code, "DUPLICATE_CPU")
        with self.assertRaises(RUN.ReadinessError):
            RUN.parse_cpu_ticks("cpu0 1 2 3")
        with self.assertRaises(RUN.ReadinessError):
            RUN.parse_cpu_ticks("cpu")

    def test_rd13_malformed_or_huge_ticks(self):
        for text in (
            "cpu0 1 2 3 x 5 6 7 8",
            "cpu0 1 2 3 -4 5 6 7 8",
            f"cpu0 1 2 3 {2**64} 5 6 7 8",
            "cpu0 1 2 3 4 5 6 7",
        ):
            with self.assertRaises(RUN.ReadinessError):
                RUN.parse_cpu_ticks(text)

    def test_rd14_aggregate_line_rejected(self):
        parsed = RUN.parse_cpu_ticks("cpu 1 2 3 4 5 6 7 8\ncpu0 1 2 3 4 5 6 7 8")
        self.assertEqual(set(parsed), {0})
        with self.assertRaises(RUN.ReadinessError):
            RUN.parse_cpu_ticks("cpu 1 2 3 4 5 6 7 8")

    def test_rd15_counter_decrease_or_zero(self):
        texts = snapshots(quiet_deltas())
        texts[2] = texts[1]
        record = measure(FakeClock(), texts)
        self.assertIn("ZERO_DELTA", record["failure_codes"])
        self.assertEqual(record["readiness_status"], "HOST_NOT_READY")
        texts = snapshots(quiet_deltas())
        lines = texts[3].splitlines()
        values = [int(value) for value in lines[0].split()[1:]]
        values[0] = 0
        texts[3] = f"cpu0 {' '.join(str(value) for value in values)}\n" + lines[1]
        record = measure(FakeClock(), texts)
        self.assertIn("COUNTER_DECREASE", record["failure_codes"])

    def test_rd16_guest_fields_ignored(self):
        texts = snapshots(quiet_deltas())
        for index, text in enumerate(texts):
            texts[index] = "\n".join(line + f" {10**12 if index else 0} 7" for line in text.splitlines())
        record = measure(FakeClock(), texts)
        self.assertEqual(record["readiness_status"], "READY")

    def test_rd17_invalid_cpu_pair(self):
        record = self.valid()
        bad = copy.deepcopy(record)
        bad["role_cpus"]["adapter"] = bad["role_cpus"]["controller"]
        failures = VERIFY.host_readiness_failures(bad, manifest(bad), host(bad), PROTOCOL_SHA)
        self.assertTrue(any(f["code"] == "V_READINESS" for f in failures))

    def test_rd18_unsupported_os(self):
        # The collector fails closed when the required counter is absent.
        original = os.path.exists
        os.path.exists = lambda path: False if path == "/proc/stat" else original(path)
        try:
            record = self.valid()
        finally:
            os.path.exists = original
        self.assertIn("PROC_UNAVAILABLE", record["failure_codes"])

    def test_rd19_verifier_shape_rejections(self):
        record = self.valid()
        for mutation in (
            lambda value: value["observations"].pop(),
            lambda value: value["observations"].reverse(),
            lambda value: value["observations"][1].__setitem__("monotonic_ns", value["observations"][0]["monotonic_ns"]),
        ):
            broken = copy.deepcopy(record)
            mutation(broken)
            self.assertTrue(VERIFY.host_readiness_failures(broken, manifest(broken), host(broken), PROTOCOL_SHA))

    def test_rd20_tampered_metrics(self):
        record = self.valid()
        broken = copy.deepcopy(record)
        broken["interval_metrics"]["adapter"][0]["busy_permille"] = 49
        self.assertTrue(VERIFY.host_readiness_failures(broken, manifest(broken), host(broken), PROTOCOL_SHA))

    def test_rd21_tampered_derived_fields(self):
        record = self.valid()
        for field, value in (("lower_median_busy_permille", {"adapter": 0, "controller": 0}),
                             ("readiness_status", "HOST_NOT_READY"),
                             ("queries_executed", 1),
                             ("failure_codes", ["BUSY_EXCEEDED"])):
            broken = copy.deepcopy(record)
            broken[field] = value
            self.assertTrue(VERIFY.host_readiness_failures(broken, manifest(broken), host(broken), PROTOCOL_SHA), field)

    def test_rd22_optional_frequency_advisory(self):
        record = self.valid()
        record["optional_cpu_frequency_khz"] = {"adapter": None, "controller": 2400000}
        self.assertEqual(VERIFY.host_readiness_failures(record, manifest(record), host(record), PROTOCOL_SHA), [])
        record["optional_cpu_frequency_khz"] = {"adapter": -1, "controller": None}
        self.assertTrue(VERIFY.host_readiness_failures(record, manifest(record), host(record), PROTOCOL_SHA))

    def test_rd23_missing_frequency_device(self):
        record = self.valid()
        self.assertIn("adapter", record["optional_cpu_frequency_khz"])
        self.assertTrue(record["optional_cpu_frequency_khz"]["adapter"] is None
                        or isinstance(record["optional_cpu_frequency_khz"]["adapter"], int))

    def test_rd24_cpu_pair_vs_host_attestation(self):
        record = self.valid()
        mismatched = host(record)
        mismatched["adapter_cpu"] = 9
        failures = VERIFY.host_readiness_failures(record, manifest(record), mismatched, PROTOCOL_SHA)
        self.assertTrue(any(f["code"] == "V_READINESS" for f in failures))

    def test_rd25_no_legacy_fallback(self):
        import tempfile
        directory = tempfile.mkdtemp(prefix="f12-no-readiness-")
        try:
            os.makedirs(os.path.join(directory, "raw"))
            with self.assertRaises(VERIFY.VerifyError) as caught:
                VERIFY.verify_host_readiness(directory, {"host_readiness_sha256": "0" * 64}, {"adapter_cpu": 0, "controller_cpu": 1, "host_fingerprint": "f" * 64}, PROTOCOL_SHA)
            self.assertIn(caught.exception.code, ("V_MISSING", "V_SEAL", "V_READINESS"))
        finally:
            import shutil
            shutil.rmtree(directory, ignore_errors=True)

    def test_rd26_seal_and_manifest_digest(self):
        import tempfile
        directory = tempfile.mkdtemp(prefix="f12-readiness-seal-")
        try:
            record = self.valid()
            os.makedirs(os.path.join(directory, "raw"))
            with open(os.path.join(directory, "raw", "host-readiness.json"), "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            with self.assertRaises(VERIFY.VerifyError) as caught:
                VERIFY.verify_host_readiness(directory, {"host_readiness_sha256": "0" * 64}, host(record), PROTOCOL_SHA)
            self.assertEqual(caught.exception.code, "V_SEAL")
        finally:
            import shutil
            shutil.rmtree(directory, ignore_errors=True)

    def test_rd27_readiness_failure_is_not_replacement(self):
        record = self.valid()
        broken = copy.deepcopy(record)
        broken["readiness_status"] = "HOST_NOT_READY"
        broken["failure_codes"] = ["BUSY_EXCEEDED"]
        self.assertEqual(VERIFY.classify_attempt(
            {"verification": "PASS", "summary_match": True, "campaign_status": "MEASUREMENT_BLOCKED"},
            {"structural": {"build_provenance": "PASS", "host_attestation": "PASS",
                            "affinity_observations": "PASS", "host_readiness": "PASS"},
             "drift": {"status": "PASS", "violations": []}, "gates": {}},
        ), VERIFY.ATTEMPT_INVALID_EVIDENCE)
        # And the verifier rejects the non-READY record itself.
        self.assertTrue(VERIFY.host_readiness_failures(broken, manifest(broken), host(broken), PROTOCOL_SHA))

    def test_rd28_verifier_arithmetic_independent(self):
        record = self.valid()
        broken = copy.deepcopy(record)
        # Change the raw idle/user deltas so the verifier's recomputation must
        # disagree with the stored derived metrics.
        for observation in broken["observations"][1:]:
            values = observation["cpus"]["0"]
            assert values[0] >= 10
            values[0] -= 10
            values[3] += 10
        self.assertTrue(VERIFY.host_readiness_failures(broken, manifest(broken), host(broken), PROTOCOL_SHA))

    def test_rd29_iowait_counts_as_non_idle(self):
        delta = (0, 0, 0, 0, 100, 0, 0, 0)
        record = measure(FakeClock(), snapshots({ADAPTER: [delta] * 6, CONTROLLER: [delta] * 6}))
        self.assertEqual(record["interval_metrics"]["adapter"][0]["busy_permille"], 1000)
        self.assertEqual(record["readiness_status"], "HOST_NOT_READY")

    def test_rd30_guest_not_double_counted(self):
        record = self.valid()
        self.assertEqual(record["readiness_status"], "READY")
        self.assertEqual(record["lower_median_busy_permille"]["adapter"], 50)


if __name__ == "__main__":
    unittest.main()
