#!/usr/bin/env python3
"""Deterministic tests for the PR15D resource probe (standard library only).

Every fixture is synthetic: `/proc` text, tick sequences and clocks are injected.
No real adapter is launched and no real measurement is claimed here.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import resource_probe as probe  # noqa: E402


def proc_stat(comm="pr15d-quervant-adapter", state="R", utime=100, stime=50, starttime=1234):
    """Build a /proc/<pid>/stat line with 52 fields."""
    fields = [state] + ["0"] * 49
    fields[11] = str(utime)
    fields[12] = str(stime)
    if len(fields) > 19:
        fields[19] = str(starttime)
    return f"4242 ({comm}) " + " ".join(fields) + "\n"


class ProcParsingTests(unittest.TestCase):
    def test_parses_utime_stime_and_starttime(self):
        parsed = probe.parse_proc_stat(proc_stat(utime=111, stime=222))
        self.assertEqual(parsed["utime"], 111)
        self.assertEqual(parsed["stime"], 222)
        self.assertEqual(parsed["starttime"], 1234)
        self.assertEqual(parsed["comm"], "pr15d-quervant-adapter")

    def test_comm_with_spaces_and_parentheses(self):
        parsed = probe.parse_proc_stat(proc_stat(comm="weird (name) here", utime=7, stime=8))
        self.assertEqual(parsed["comm"], "weird (name) here")
        self.assertEqual(parsed["utime"], 7)
        self.assertEqual(parsed["stime"], 8)

    def test_malformed_stat_is_rejected(self):
        for text in ("", "no parens here", "4242 (missing-close", "4242 (x) R 1 2 3"):
            with self.subTest(text=text):
                with self.assertRaises(probe.ResourceError) as raised:
                    probe.parse_proc_stat(text)
                self.assertEqual(raised.exception.rule, "proc_stat_malformed")

    def test_status_vmhwm_units(self):
        text = "Name:\tjava\nVmHWM:\t  20480 kB\nVmRSS:\t 1024 kB\n"
        self.assertEqual(probe.parse_status(text)["vmhwm_kb"], 20480)

    def test_status_missing_vmhwm_is_none(self):
        self.assertIsNone(probe.parse_status("Name:\tjava\n")["vmhwm_kb"])

    def test_status_wrong_units_are_rejected(self):
        with self.assertRaises(probe.ResourceError) as raised:
            probe.parse_status("VmHWM:\t20480 MB\n")
        self.assertEqual(raised.exception.rule, "proc_status_units")

    def test_status_zero_vmhwm_is_rejected(self):
        with self.assertRaises(probe.ResourceError) as raised:
            probe.parse_status("VmHWM:\t0 kB\n")
        self.assertEqual(raised.exception.rule, "proc_status_vmhwm")

    def test_non_numeric_vmhwm_is_rejected(self):
        with self.assertRaises(probe.ResourceError) as raised:
            probe.parse_status("VmHWM:\tabc kB\n")
        self.assertEqual(raised.exception.rule, "proc_status_malformed")


class TickMathTests(unittest.TestCase):
    def test_ticks_to_ns_uses_integer_arithmetic(self):
        self.assertEqual(probe.cpu_ns_from_ticks(100, 100), 1_000_000_000)
        self.assertEqual(probe.cpu_ns_from_ticks(1, 250), 4_000_000)

    def test_zero_or_invalid_clk_tck_is_rejected(self):
        for bad in (0, -1, True, "100", None):
            with self.subTest(bad=bad):
                with self.assertRaises(probe.ResourceError) as raised:
                    probe.cpu_ns_from_ticks(1, bad)
                self.assertEqual(raised.exception.rule, "clk_tck_invalid")

    def test_negative_or_non_integer_delta_is_rejected(self):
        with self.assertRaises(probe.ResourceError) as raised:
            probe.cpu_ns_from_ticks(-1, 100)
        self.assertEqual(raised.exception.rule, "ticks_negative")
        with self.assertRaises(probe.ResourceError) as raised:
            probe.cpu_ns_from_ticks(1.5, 100)
        self.assertEqual(raised.exception.rule, "ticks_invalid")


class ProbeLoopTests(unittest.TestCase):
    def _drive(self, tick_sequence, clock_sequence, limits=None):
        ticks = iter(tick_sequence)
        clock = iter(clock_sequence)
        state = {"ticks": next(ticks)}

        def cpu_ticks():
            return state["ticks"]

        def request():
            # Each request advances the synthetic CPU ticks.
            state["ticks"] = next(ticks)

        kwargs = {"request": request, "cpu_ticks": cpu_ticks, "clock_ns": lambda: next(clock)}
        if limits is not None:
            kwargs["limits"] = limits
        return probe.probe_loop(**kwargs)

    def test_stops_when_cpu_target_reached(self):
        # CLK_TCK is 100 on this host assumption; compute ticks for 0.5s.
        clk = probe.clock_ticks()
        target = probe.TARGET_CPU_NS
        step = max(1, -(-target // (1_000_000_000 // clk)))
        result = self._drive([0] + [step] * 20, [0] * 40)
        self.assertEqual(result["stop_reason"], "cpu_target")
        self.assertGreaterEqual(result["cpu_ns"], target)

    def test_stops_on_wall_cap(self):
        result = self._drive(
            [0] * 200,
            [index * (probe.MAX_WALL_NS // 4) for index in range(200)],
        )
        self.assertEqual(result["stop_reason"], "wall_cap")

    def test_stops_on_request_cap(self):
        result = self._drive([0] * (probe.MAX_REQUESTS + 5), [0] * (probe.MAX_REQUESTS + 5))
        self.assertEqual(result["stop_reason"], "request_cap")
        self.assertEqual(result["requests"], probe.MAX_REQUESTS)

    def test_zero_ticks_is_below_resolution(self):
        result = self._drive(
            [0] * 10,
            [0, probe.MAX_WALL_NS],
        )
        status = probe.classify_probe(
            cpu_ns=result["cpu_ns"],
            delta_ticks=result["ticks_after"] - result["ticks_before"],
            stop_reason=result["stop_reason"],
        )
        self.assertEqual(status, probe.STATUS_BELOW_RESOLUTION)

    def test_not_reaching_target_is_diagnostic_limit(self):
        # Force the wall cap while CPU ticks stay positive but far below target.
        result = self._drive(
            [0] + [1] * 40,
            list(range(0, 80, 2)),
            limits=(probe.TARGET_CPU_NS, 10, probe.MAX_REQUESTS),
        )
        self.assertEqual(result["stop_reason"], "wall_cap")
        self.assertGreater(result["cpu_ns"], 0)
        self.assertLess(result["cpu_ns"], probe.TARGET_CPU_NS)
        status = probe.classify_probe(
            cpu_ns=result["cpu_ns"],
            delta_ticks=result["ticks_after"] - result["ticks_before"],
            stop_reason=result["stop_reason"],
        )
        self.assertEqual(status, probe.STATUS_DIAGNOSTIC_LIMIT)


class IdentityTests(unittest.TestCase):
    def test_rust_engines_accept_the_adapter_process(self):
        for engine in ("quervant", "tantivy"):
            with self.subTest(engine=engine):
                comm = f"pr15d-{engine}-adapter"[:15]
                self.assertIsNone(
                    probe.identity_problem(
                        engine, comm, f"/tmp/build/{engine}/pr15d-{engine}-adapter --index-dir /i"
                    )
                )

    def test_shell_parent_is_rejected(self):
        for comm in probe.SHELL_COMMS:
            with self.subTest(comm=comm):
                self.assertIsNotNone(
                    probe.identity_problem("quervant", comm, "/tmp/pr15d-quervant-adapter")
                )

    def test_wrong_binary_is_rejected(self):
        self.assertIsNotNone(
            probe.identity_problem("quervant", "pr15d-quervant-", "/bin/other --index-dir /i")
        )

    def test_lucene_requires_java_with_adapter_classpath(self):
        self.assertIsNone(
            probe.identity_problem(
                "lucene", "java", "/usr/bin/java -cp /x/pr15d-lucene-adapter/lib.jar org.quervant.bench.Adapter"
            )
        )
        self.assertIsNotNone(probe.identity_problem("lucene", "java", "/usr/bin/java -version"))
        self.assertIsNotNone(
            probe.identity_problem("lucene", "gradlew", "/x/pr15d-lucene-adapter -p /i")
        )


class IdentitySettleTests(unittest.TestCase):
    """The launcher->engine exec transition must be tolerated, but only that."""

    @staticmethod
    def _reader(sequence):
        state = {"index": 0}

        def read(pid):
            value = sequence[min(state["index"], len(sequence) - 1)]
            state["index"] += 1
            return value

        return read

    def _await(self, engine, sequence):
        ticks = {"now": 0.0}

        def clock():
            ticks["now"] += 0.001
            return ticks["now"]

        return probe.await_process_identity(
            engine,
            4242,
            identity_reader=self._reader(sequence),
            clock=clock,
            sleep=lambda _: None,
            timeout_s=1.0,
        )

    def test_launcher_exec_transition_is_accepted(self):
        comm, cmdline = self._await(
            "lucene",
            [
                ("pr15d-lucene-ad", "/inst/pr15d-lucene-adapter/bin/pr15d-lucene-adapter --index-dir /i"),
                ("pr15d-lucene-ad", "/inst/pr15d-lucene-adapter/bin/pr15d-lucene-adapter --index-dir /i"),
                ("java", "/usr/bin/java -cp /x/pr15d-lucene-adapter/lib/pr15d-lucene-adapter.jar org.quervant.bench.Adapter"),
            ],
        )
        self.assertEqual(comm, "java")
        self.assertIn("pr15d-lucene-adapter", cmdline)

    def test_never_execing_launcher_is_rejected(self):
        with self.assertRaises(probe.ResourceError) as raised:
            self._await(
                "lucene",
                [("pr15d-lucene-ad", "/inst/bin/pr15d-lucene-adapter --index-dir /i")],
            )
        self.assertEqual(raised.exception.rule, "X32_PID_IDENTITY")

    def test_java_without_adapter_classpath_is_rejected(self):
        with self.assertRaises(probe.ResourceError) as raised:
            self._await("lucene", [("java", "/usr/bin/java -version")])
        self.assertEqual(raised.exception.rule, "X32_PID_IDENTITY")

    def test_rust_engine_identity_is_immediate(self):
        comm, _ = self._await(
            "tantivy", [("pr15d-tantivy-", "/x/pr15d-tantivy-adapter --index-dir /i")]
        )
        self.assertEqual(comm, "pr15d-tantivy-")

    def test_disappeared_pid_is_rejected(self):
        def read(_pid):
            raise FileNotFoundError("gone")

        with self.assertRaises(probe.ResourceError) as raised:
            probe.await_process_identity(
                "lucene", 4242, identity_reader=read, clock=lambda: 0.0, sleep=lambda _: None
            )
        self.assertEqual(raised.exception.rule, "X32_PID_IDENTITY")


class PreconditionTests(unittest.TestCase):
    def _run_dir(self, **overrides):
        directory = tempfile.mkdtemp(prefix="pr15d-probe-")
        record = {
            "schema": "pr15d-run-v1",
            "run_id": "fixture",
            "source_sha": "a" * 40,
            "status": "complete",
            "qualified": True,
            "corpus_manifest_sha256": "b" * 64,
        }
        record.update(overrides)
        with open(os.path.join(directory, "run.json"), "wb") as handle:
            handle.write(json.dumps(record).encode() + b"\n")
        with open(os.path.join(directory, "validation.json"), "wb") as handle:
            handle.write(b'{"status":"QUALIFIED"}\n')
        for trial in (1, 2, 3):
            for engine in probe.ENGINES:
                path = os.path.join(directory, "trials", f"trial-{trial}", f"{engine}.json")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(b"{}\n")
        return directory

    @staticmethod
    def _source_sha():
        import run as runner

        return runner.source_sha()

    def _ready(self, directory, **kwargs):
        return probe.verify_run_ready(
            directory, idle_confirmed=True, tree_clean=lambda: True, **kwargs
        )

    def test_missing_attestation_is_a_deferral(self):
        directory = self._run_dir()
        with self.assertRaises(probe.ResourceError) as raised:
            probe.verify_run_ready(directory, idle_confirmed=False, tree_clean=lambda: True)
        self.assertIn("ATTESTATION", raised.exception.rule)

    def test_dirty_tree_is_rejected(self):
        directory = self._run_dir(source_sha=self._source_sha())
        with self.assertRaises(probe.ResourceError) as raised:
            probe.verify_run_ready(directory, idle_confirmed=True, tree_clean=lambda: False)
        self.assertEqual(raised.exception.rule, "X29_SOURCE_DIRTY")

    def test_incomplete_run_is_rejected(self):
        directory = self._run_dir(status="running", source_sha=self._source_sha())
        with self.assertRaises(probe.ResourceError) as raised:
            self._ready(directory)
        self.assertEqual(raised.exception.rule, "X40_RUN_STATE")

    def test_source_mismatch_is_rejected(self):
        directory = self._run_dir()
        with self.assertRaises(probe.ResourceError) as raised:
            self._ready(directory)
        self.assertEqual(raised.exception.rule, "X40_SOURCE_MISMATCH")

    def test_non_qualified_validation_is_rejected(self):
        directory = self._run_dir(source_sha=self._source_sha())
        with open(os.path.join(directory, "validation.json"), "wb") as handle:
            handle.write(b'{"status":"INVALID"}\n')
        with self.assertRaises(probe.ResourceError) as raised:
            self._ready(directory)
        self.assertEqual(raised.exception.rule, "X40_VALIDATION")

    def test_missing_trial_manifest_is_rejected(self):
        directory = self._run_dir(source_sha=self._source_sha())
        os.remove(os.path.join(directory, "trials", "trial-2", "tantivy.json"))
        with self.assertRaises(probe.ResourceError) as raised:
            self._ready(directory)
        self.assertEqual(raised.exception.rule, "X40_MISSING_TRIAL")

    def test_complete_ready_run_is_accepted(self):
        directory = self._run_dir(source_sha=self._source_sha())
        record = self._ready(directory)
        self.assertEqual(record["status"], "complete")


class MeasuredPathDriftTests(unittest.TestCase):
    """Tooling may drift; measured paths may not (X44)."""

    MEASURED_SHA = "40a9c26a57aa23640904075e77be956ee52718bc"

    def test_same_sha_has_no_drift(self):
        self.assertEqual(probe.measured_path_drift(self.MEASURED_SHA, self.MEASURED_SHA), [])

    def test_measured_paths_are_unchanged_since_the_measured_commit(self):
        self.assertEqual(probe.measured_path_drift(self.MEASURED_SHA, "HEAD"), [])

    def test_a_different_source_shows_measured_drift(self):
        drift = probe.measured_path_drift(
            "8caca7682cc23c7b595fba049608e7fd843cd4dd", "HEAD"
        )
        self.assertTrue(drift)
        self.assertTrue(any(path.startswith("benchmarks/pr15d/adapters") for path in drift))

    def test_unknown_source_sha_fails_closed(self):
        with self.assertRaises(probe.ResourceError) as raised:
            probe.measured_path_drift("0" * 40, "HEAD")
        self.assertEqual(raised.exception.rule, "X40_SOURCE_MISMATCH")


class SummaryTests(unittest.TestCase):
    def test_summary_reports_min_median_max_and_allocations_not_measured(self):
        probes = [
            {
                "engine": "quervant",
                "n": 10000,
                "cpu_ns_per_request": value,
                "peak_rss_bytes": rss,
                "status": probe.STATUS_MEASURED,
            }
            for value, rss in ((100, 1000), (200, 2000), (300, 3000))
        ]
        summary = probe.summarize(probes)["quervant"]["10000"]
        self.assertEqual(summary["cpu_ns_per_request"]["min"], 100)
        self.assertEqual(summary["cpu_ns_per_request"]["median"], 200)
        self.assertEqual(summary["cpu_ns_per_request"]["max"], 300)
        self.assertEqual(summary["peak_rss_bytes"]["max"], 3000)
        self.assertEqual(summary["allocations"], "NOT_MEASURED")

    def test_missing_engine_is_blocked_not_zero(self):
        summary = probe.summarize([])["tantivy"]["100000"]
        self.assertEqual(summary["status"], probe.STATUS_BLOCKED_ENVIRONMENT)
        self.assertNotIn("cpu_ns_per_request", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
