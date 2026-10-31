#!/usr/bin/env python3
"""Deterministic tests for PR 15E-A evidence verification (T31-T47)."""

from __future__ import annotations

import contextlib
import copy
import gzip
import importlib
import importlib.util
import json
import io
import os
import re
import shutil
import sys
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
VERIFY_PATH = os.path.join(HERE, "verify.py")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VERIFY = _load(VERIFY_PATH, "pr15e_verify_tests")
PROFILE = VERIFY.profile

try:  # unittest discovery puts this directory on sys.path
    TEST_PROFILE = importlib.import_module("test_profile")
except ImportError:  # pragma: no cover - direct invocation fallback
    TEST_PROFILE = _load(os.path.join(HERE, "test_profile.py"), "test_profile_fallback")

TARGET_ROOT = PROFILE.TARGET_ROOT

PERF_REPORT = """# Total Lost Samples: 0
#
# Samples: 500  of event 'cycles:Pu'
# Event count (approx.): 1000000
#
# Overhead  Shared Object             Symbol
# ........ ........................  ...................................
#
    42.00%  pr15d-quervant-adapter  [.] quervant_core::search::execute::evaluate_lexical_with
    12.50%  pr15d-quervant-adapter  [.] quervant_core::search::execute::collect_matches
     5.00%  libc.so.6               [.] malloc
"""

HEAPTRACK_REPORT = """MOST CALLS TO ALLOCATION FUNCTIONS
---------------------------------
250 calls to allocation functions with 1.20M peak consumption from
quervant_core::search::execute::evaluate_lexical_with
  in execute.rs:1900
100 calls to allocation functions with 512.00K peak consumption from
BTreeSet::insert
  in execute.rs:1920
PEAK MEMORY CONSUMERS
calls to allocation functions: 350 (1000/s)
total memory leaked: 0
"""


class VerifyFixture(TEST_PROFILE.RunFixture):
    """Adds synthetic, complete capture evidence to the base run fixture."""

    def add_capture(self, entry: dict, **overrides) -> dict:
        capture_dir = os.path.join(self.run_dir, *entry["rel_dir"].split("/"))
        os.makedirs(capture_dir, exist_ok=True)
        PROFILE.write_json(
            os.path.join(capture_dir, "contention-before.json"),
            {"state": "clear", "reason_codes": []},
        )
        PROFILE.write_json(
            os.path.join(capture_dir, "contention-after.json"),
            {"state": "clear", "reason_codes": []},
        )
        with open(os.path.join(capture_dir, "profiler-stderr.txt"), "w", encoding="utf-8") as handle:
            handle.write("TEST_FIXTURE profiler diagnostics\n")

        if entry["tool"] == "perf":
            with open(os.path.join(capture_dir, "perf.data"), "wb") as handle:
                handle.write(b"TEST_FIXTURE perf data" * 32)
            with open(os.path.join(capture_dir, "perf-self.txt"), "w", encoding="utf-8") as handle:
                handle.write(PERF_REPORT)
            with open(
                os.path.join(capture_dir, "perf-calltree.txt"), "w", encoding="utf-8"
            ) as handle:
                handle.write(PERF_REPORT)
            tool_evidence = {
                "sample_count": 500,
                "lost_samples": 0,
                "sampled_with_loss": False,
                "symbolization": {"quervant_mentions": 4, "rust_symbols": 2},
                "reports": ["perf-self.txt", "perf-calltree.txt"],
                "raw_bytes": 640,
            }
        else:
            with gzip.open(os.path.join(capture_dir, "heaptrack.gz"), "wb") as handle:
                handle.write(b'{"fixture": true}')
            with open(
                os.path.join(capture_dir, "heaptrack-report.txt"), "w", encoding="utf-8"
            ) as handle:
                handle.write(HEAPTRACK_REPORT)
            with open(
                os.path.join(capture_dir, "heaptrack-print-stderr.txt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("")
            tool_evidence = {
                "raw_path": "heaptrack.gz",
                "raw_bytes": 22,
                "report": "heaptrack-report.txt",
                "records": {
                    "total_allocations": 350,
                    "allocation_sites": 2,
                    "temporary_section": 0,
                    "has_calls_section": True,
                },
            }

        expected = PROFILE.oracle.expected(
            self.rows_by_n[entry["n"]],
            entry["field"],
            entry["term"],
            entry["k"],
        )
        manifest = {
            "schema": PROFILE.SCHEMA_CAPTURE,
            "status": "CAPTURED_RAW",
            "capture_id": entry["capture_id"],
            "lane_id": entry["lane_id"],
            "tool": entry["tool"],
            "n": entry["n"],
            "class": entry["class"],
            "field": entry["field"],
            "term": entry["term"],
            "k": entry["k"],
            "regime": PROFILE.REGIME,
            "seconds": entry["seconds"],
            "profiled_window_seconds": float(entry["seconds"]),
            "warmups": PROFILE.WARMUPS,
            "profiled_query_count": 12,
            "warmup_in_capture": True,
            "perf_includes_protocol": True,
            "adapter_pid": 4242,
            "adapter_pid_sample_count": 3,
            "first_utc": "2030-01-01T12:00:00Z",
            "last_utc": "2030-01-01T12:00:20Z",
            "source_sha": self.source_sha,
            "prepared_digest": self.prepared["prepared_digest"],
            "corpus_manifest_sha256": self.prepared["corpus"]["manifest_sha256"],
            "corpus_sha256": {
                str(key): value["sha256"]
                for key, value in self.prepared["corpus"]["corpora"].items()
            },
            "index_inventory_sha256": self.prepared["indexes"][str(entry["n"])][
                "inventory"
            ]["sha256"],
            "binary_sha256": self.prepared["build"]["binary_sha256"],
            "adapter_binary": self.prepared["build"]["binary_path"],
            "command": ["fixture"],
            "tool_version": "fixture",
            "tool_path": "fixture",
            "tool_origin": "test_fixture",
            "tool_diagnostics": [],
            "profiler_fallback": False,
            "expected_total_hits": expected["total_hits"],
            "expected_doc_ids": expected["doc_ids"],
            "expected_digest": PROFILE.expected_digest(expected),
            "attestation": {
                "host": self.host,
                "start_utc": "2030-01-01T11:00:00Z",
                "end_utc": "2030-01-01T13:00:00Z",
                "operator_statement": "TEST_FIXTURE statement",
            },
            "contention_before": "clear",
            "contention_after": "clear",
            "tool_evidence": tool_evidence,
            "files": [],
            "limitations": PROFILE._prepare_environment_note(),
            "test_fixture": True,
        }
        manifest.update(overrides)
        manifest["files"] = PROFILE.artifact_manifest(capture_dir)
        PROFILE.write_json(os.path.join(capture_dir, "capture.json"), manifest)
        return manifest

    def add_all_captures(self) -> None:
        for entry in PROFILE.required_captures():
            self.add_capture(entry)

    def capture_dir_for(self, entry: dict) -> str:
        return os.path.join(self.run_dir, *entry["rel_dir"].split("/"))

    def capture_entry(self, n=100000, class_name="common", k=100, tool="perf") -> dict:
        for entry in PROFILE.required_captures():
            if (
                entry["n"] == n
                and entry["class"] == class_name
                and entry["k"] == k
                and entry["tool"] == tool
            ):
                return entry
        raise KeyError((n, class_name, k, tool))

    def refresh_prepare(self) -> None:
        prepared = self.prepared
        prepared.pop("prepared_digest", None)
        prepared["prepared_digest"] = PROFILE.sha256_bytes(
            PROFILE.canonical_json_bytes(prepared)
        )
        PROFILE.write_json(os.path.join(self.run_dir, "prepare.json"), prepared)


def verify_args(run_dir: str, *, analysis: str | None = None, publish: bool = False):
    return VERIFY.build_parser().parse_args(
        [
            "--run",
            run_dir,
            *(["--analysis", analysis] if analysis else []),
            *(["--publish-manifest"] if publish else []),
        ]
    )


class VerifyTestCase(unittest.TestCase):
    def setUp(self):
        os.makedirs(TARGET_ROOT, exist_ok=True)
        self.fixture = VerifyFixture().build()
        self.addCleanup(self.fixture.cleanup)

    def evaluate(self):
        return VERIFY.evaluate(self.fixture.run_dir, self.fixture.deps())

    def verification(self, *, analysis=None) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            code = VERIFY.verify(
                verify_args(self.fixture.run_dir, analysis=analysis), self.fixture.deps()
            )
        payload = PROFILE.read_json(
            os.path.join(self.fixture.run_dir, "verification.json")
        )
        payload["exit_code"] = code
        return payload


# ---------------------------------------------------------------------------
# T31-T34: integrity
# ---------------------------------------------------------------------------


class IntegrityTests(VerifyTestCase):
    def test_complete_evidence_reaches_evidence_complete(self):
        self.fixture.add_all_captures()
        payload = self.verification()
        self.assertEqual(payload["status"], "EVIDENCE_COMPLETE", payload["gates"])
        self.assertEqual(payload["counts"]["passed"], 20)
        self.assertEqual(payload["gates"]["g05_perf"], "PASS")
        self.assertEqual(payload["gates"]["g06_heaptrack"], "PASS")
        self.assertEqual(payload["gates"]["g09_attribution"], "PASS")
        self.assertEqual(payload["exit_code"], PROFILE.EXIT_OK)

    def test_t31_truncated_artifact_fails(self):
        self.fixture.add_capture(self.fixture.capture_entry(tool="perf"))
        path = os.path.join(
            self.fixture.capture_dir_for(self.fixture.capture_entry(tool="perf")),
            "perf-self.txt",
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")
        payload = self.verification()
        self.assertEqual(payload["status"], "FAILED")
        entry = next(
            capture
            for capture in payload["captures"]
            if capture["capture_id"] == "pr15e/n100000/common/k100/perf"
        )
        self.assertEqual(entry["status"], "FAILED")
        self.assertTrue(
            any(reason.startswith("artifact_empty") for reason in entry["reasons"])
        )

    def test_t32_edited_artifact_after_manifest_fails(self):
        entry = self.fixture.capture_entry(tool="perf")
        self.fixture.add_capture(entry)
        path = os.path.join(self.fixture.capture_dir_for(entry), "perf-self.txt")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("    99.00%  pr15d-quervant-adapter  [.] quervant_core::fake\n")
        payload = self.verification()
        self.assertEqual(payload["status"], "FAILED")
        captured = next(
            capture
            for capture in payload["captures"]
            if capture["capture_id"] == entry["capture_id"]
        )
        self.assertTrue(
            any(reason.startswith("artifact_digest") for reason in captured["reasons"])
        )

    def test_t33_mutated_prepare_fails(self):
        self.fixture.add_all_captures()
        prepared = PROFILE.read_json(
            os.path.join(self.fixture.run_dir, "prepare.json")
        )
        prepared["corpus"]["manifest_sha256"] = "0" * 64
        PROFILE.write_json(os.path.join(self.fixture.run_dir, "prepare.json"), prepared)
        payload = self.verification()
        self.assertEqual(payload["status"], "FAILED")
        self.assertIn(
            "prepare_digest: prepare.json digest does not re-derive",
            payload["prepare_violations"],
        )

    def test_t34_modified_canonical_report_fails(self):
        report_copy = os.path.join(self.fixture.run_dir, "canonical-report.json")
        shutil.copyfile(PROFILE.DEFAULT_CANONICAL_REPORT, report_copy)
        self.fixture.prepared["source_lock"]["canonical_report"]["sha256"] = (
            PROFILE.sha256_file(report_copy)
        )
        self.fixture.prepared["source_lock"]["canonical_report"]["bytes"] = os.path.getsize(
            report_copy
        )
        self.fixture.refresh_prepare()
        deps = self.fixture.deps(canonical_report=report_copy)
        evaluation = VERIFY.evaluate(self.fixture.run_dir, deps)
        self.assertFalse(
            any(
                "canonical_report" in violation
                for violation in evaluation["prepared"]["violations"]
            ),
            evaluation["prepared"]["violations"],
        )
        with open(report_copy, "a", encoding="utf-8") as handle:
            handle.write("\n")
        evaluation = VERIFY.evaluate(self.fixture.run_dir, deps)
        self.assertTrue(
            any(
                "pr15d-qualified.json" in violation
                for violation in evaluation["prepared"]["violations"]
            ),
            evaluation["prepared"]["violations"],
        )

    def test_unlisted_or_duplicate_capture_is_reported(self):
        self.fixture.add_all_captures()
        entry = self.fixture.capture_entry(tool="perf")
        duplicate = os.path.join(self.fixture.run_dir, "captures", "n100000", "common", "k100", "extra")
        os.makedirs(duplicate)
        PROFILE.write_json(os.path.join(duplicate, "capture.json"), {"schema": "x"})
        payload = self.verification()
        self.assertEqual(payload["status"], "FAILED")
        self.assertTrue(
            any("unexpected_capture" in item for item in payload["prepare_violations"]),
            payload["prepare_violations"],
        )


# ---------------------------------------------------------------------------
# T40-T42, T44: matrix completeness and determinism
# ---------------------------------------------------------------------------


class MatrixTests(VerifyTestCase):
    def test_t40_missing_capture_yields_partial(self):
        self.fixture.add_all_captures()
        entry = self.fixture.capture_entry(n=10000, class_name="rare", tool="perf")
        shutil.rmtree(self.fixture.capture_dir_for(entry))
        payload = self.verification()
        self.assertEqual(payload["status"], "PARTIAL")
        self.assertEqual(payload["counts"]["missing"], 1)
        self.assertEqual(payload["gates"]["g05_perf"], "FAILED")
        self.assertNotEqual(payload["exit_code"], PROFILE.EXIT_OK)

    def test_t41_wrong_labeled_capture_fails(self):
        entry = self.fixture.capture_entry(tool="perf")
        self.fixture.add_capture(entry, tool="heaptrack")
        payload = self.verification()
        self.assertEqual(payload["status"], "FAILED")
        captured = next(
            capture
            for capture in payload["captures"]
            if capture["capture_id"] == entry["capture_id"]
        )
        self.assertTrue(
            any(reason.startswith("mislabeled_capture") for reason in captured["reasons"])
        )

    def test_t42_verification_is_byte_identical_on_replay(self):
        self.fixture.add_all_captures()
        path = os.path.join(self.fixture.run_dir, "verification.json")
        self.verification()
        first = open(path, "rb").read()
        self.verification()
        second = open(path, "rb").read()
        self.assertEqual(first, second)
        text = first.decode("utf-8")
        self.assertIsNone(
            re.search(r"""[\"']/(?:home|Users|root|mnt|tmp)/""", text),
            "verification.json must never contain an absolute home path",
        )
        self.assertNotIn(VERIFY._current_host(), text)

    def test_t44_sample_count_claim_must_match_the_report(self):
        entry = self.fixture.capture_entry(tool="perf")
        self.fixture.add_capture(entry)
        capture_dir = self.fixture.capture_dir_for(entry)
        with open(os.path.join(capture_dir, "perf-self.txt"), "w", encoding="utf-8") as handle:
            handle.write(PERF_REPORT.replace("# Samples: 500", "# Samples: 0"))
        manifest_path = os.path.join(capture_dir, "capture.json")
        manifest = PROFILE.read_json(manifest_path)
        manifest["files"] = PROFILE.artifact_manifest(capture_dir)
        PROFILE.write_json(manifest_path, manifest)
        payload = self.verification()
        captured = next(
            capture
            for capture in payload["captures"]
            if capture["capture_id"] == entry["capture_id"]
        )
        self.assertEqual(captured["status"], "FAILED")
        self.assertTrue(
            any(reason.startswith("perf_samples") for reason in captured["reasons"])
        )


# ---------------------------------------------------------------------------
# T45-T47: attribution honesty
# ---------------------------------------------------------------------------


class AttributionTests(VerifyTestCase):
    def _analysis(self, entries) -> str:
        path = os.path.join(self.fixture.run_dir, "analysis.json")
        PROFILE.write_json(
            path,
            {
                "schema": PROFILE.SCHEMA_ATTRIBUTION,
                "source_sha": self.fixture.source_sha,
                "entries": entries,
            },
        )
        return path

    def _entry(self, entry: dict, **overrides) -> dict:
        capture_dir = os.path.join(self.fixture.run_dir, *entry["rel_dir"].split("/"))
        if entry["tool"] == "heaptrack":
            raw = os.path.join(capture_dir, "heaptrack-report.txt")
            line = (
                "250 calls to allocation functions with 1.20M peak consumption from\n"
                "quervant_core::search::execute::evaluate_lexical_with"
            )
            symbol = "quervant_core::search::execute::evaluate_lexical_with"
            kind = "allocation_count"
            value = 250
            unit = "allocations"
        else:
            raw = os.path.join(capture_dir, "perf-self.txt")
            line = (
                "    42.00%  pr15d-quervant-adapter  [.] "
                "quervant_core::search::execute::evaluate_lexical_with"
            )
            symbol = "quervant_core::search::execute::evaluate_lexical_with"
            kind = "self_cpu_percent"
            value = 42
            unit = "percent"
        payload = {
            "lane_id": entry["lane_id"],
            "tool": entry["tool"],
            "category": "live_doc_and_stats",
            "kind": kind,
            "value": value,
            "unit": unit,
            "raw_path": f"{entry['rel_dir']}/"
            + ("heaptrack-report.txt" if entry["tool"] == "heaptrack" else "perf-self.txt"),
            "raw_sha256": PROFILE.sha256_file(raw),
            "verbatim_source_line": line,
            "symbol": symbol,
            "interpretation": "MEASURED_EVIDENCE",
        }
        payload.update(overrides)
        return payload

    def test_valid_analysis_is_accepted(self):
        self.fixture.add_all_captures()
        entries = [
            self._entry(self.fixture.capture_entry(tool="perf")),
            self._entry(self.fixture.capture_entry(tool="heaptrack")),
        ]
        payload = self.verification(analysis=self._analysis(entries))
        self.assertIs(payload["analysis_valid"], True, payload["analysis"])
        self.assertEqual(payload["status"], "EVIDENCE_COMPLETE")

    def test_t45_unsupported_measurement_is_rejected(self):
        self.fixture.add_all_captures()
        entry = self.fixture.capture_entry(tool="perf")
        broken = self._entry(entry, symbol="a_symbol_that_is_not_there")
        payload = self.verification(analysis=self._analysis([broken]))
        self.assertIs(payload["analysis_valid"], False)
        self.assertTrue(
            any("symbol is not present" in item for item in payload["analysis"]["errors"])
        )

    def test_t45_missing_symbolization_marks_attribution_unresolved(self):
        entry = self.fixture.capture_entry(tool="perf")
        self.fixture.add_capture(entry)
        capture_dir = self.fixture.capture_dir_for(entry)
        with open(os.path.join(capture_dir, "perf-self.txt"), "w", encoding="utf-8") as handle:
            handle.write(
                "# Samples: 500  of event 'cycles:Pu'\n"
                "  99.00%  python3  [.] _PyEval_EvalFrameDefault\n"
            )
        manifest_path = os.path.join(capture_dir, "capture.json")
        manifest = PROFILE.read_json(manifest_path)
        manifest["files"] = PROFILE.artifact_manifest(capture_dir)
        PROFILE.write_json(manifest_path, manifest)
        payload = self.verification()
        captured = next(
            capture
            for capture in payload["captures"]
            if capture["capture_id"] == entry["capture_id"]
        )
        self.assertEqual(captured["status"], "PASS")
        self.assertEqual(captured["attribution"], "ATTRIBUTION_UNRESOLVED")
        self.assertEqual(payload["gates"]["g09_attribution"], "FAILED")

    def test_t46_summed_inclusive_percent_is_rejected(self):
        self.fixture.add_all_captures()
        entry = self.fixture.capture_entry(tool="perf")
        analysis = {
            "schema": PROFILE.SCHEMA_ATTRIBUTION,
            "source_sha": self.fixture.source_sha,
            "sum_inclusive_cpu_percent": 71.5,
            "entries": [self._entry(entry)],
        }
        path = os.path.join(self.fixture.run_dir, "analysis.json")
        PROFILE.write_json(path, analysis)
        payload = self.verification(analysis=path)
        self.assertIs(payload["analysis_valid"], False)
        self.assertTrue(
            any("forbidden_key" in item for item in payload["analysis"]["errors"])
        )

    def test_t36_units_and_inferred_stage_ns_are_rejected(self):
        self.fixture.add_all_captures()
        entry = self.fixture.capture_entry(tool="perf")
        bad_unit = self._entry(entry, unit="ms", kind="self_cpu_percent")
        payload = self.verification(analysis=self._analysis([bad_unit]))
        self.assertIs(payload["analysis_valid"], False)
        self.assertTrue(
            any("unit" in item for item in payload["analysis"]["errors"])
        )

        good = self._entry(entry)
        good["inferred_stage_ns"] = 1234
        payload = self.verification(analysis=self._analysis([good]))
        self.assertIs(payload["analysis_valid"], False)
        self.assertTrue(
            any("inferred_stage_ns" in item for item in payload["analysis"]["errors"])
        )

    def test_t47_missing_common_100k_lane_blocks_attribution(self):
        for entry in PROFILE.required_captures():
            if entry["lane_id"] == "pr15e/n100000/common/k100":
                continue
            self.fixture.add_capture(entry)
        payload = self.verification()
        self.assertEqual(payload["gates"]["g09_attribution"], "FAILED")
        self.assertNotEqual(payload["status"], "EVIDENCE_COMPLETE")
        self.assertFalse(
            payload["gates"]["g09_lanes"]["pr15e/n100000/common/k100"]["complete"]
        )


# ---------------------------------------------------------------------------
# T43, T35: publication and metric conflation guards
# ---------------------------------------------------------------------------


class PublicationTests(VerifyTestCase):
    def test_t43_publication_refuses_sensitive_content(self):
        self.fixture.prepared["limitations"] = [
            "raw evidence kept at " + os.path.expanduser("~") + "/secret"
        ]
        self.fixture.refresh_prepare()
        self.fixture.add_all_captures()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = VERIFY.verify(
                verify_args(self.fixture.run_dir, publish=True), self.fixture.deps()
            )
        summary = json.loads(buffer.getvalue().strip().splitlines()[-1])
        self.assertFalse(os.path.exists(VERIFY.PUBLISH_PATH))
        payload = PROFILE.read_json(os.path.join(self.fixture.run_dir, "verification.json"))
        self.assertEqual(payload["status"], "EVIDENCE_COMPLETE")
        self.assertEqual(code, PROFILE.EXIT_OK)
        self.assertFalse(summary["publication"]["written"])
        self.assertIn("X31", summary["publication"]["code"])
        # The sanitizer itself is deterministic and catches the marker.
        self.assertTrue(
            VERIFY.sensitive_hits("path " + os.path.expanduser("~") + "/x", host="h")
        )

    def test_t43_publish_from_incomplete_evidence_is_refused(self):
        self.fixture.add_capture(self.fixture.capture_entry(tool="perf"))
        VERIFY.verify(
            verify_args(self.fixture.run_dir, publish=True), self.fixture.deps()
        )
        self.assertFalse(os.path.exists(VERIFY.PUBLISH_PATH))

    def test_t43_test_fixtures_can_never_be_published(self):
        self.fixture.add_all_captures()
        evaluation = self.evaluate()
        with self.assertRaises(VERIFY.VerificationError) as context:
            VERIFY.publish_manifest(
                self.fixture.run_dir,
                evaluation["prepared"],
                evaluation["captures"],
                {"g05_perf": "PASS"},
            )
        self.assertEqual(context.exception.code, "X31_TEST_FIXTURE")
        self.assertFalse(os.path.exists(VERIFY.PUBLISH_PATH))

    def test_t35_published_manifest_carries_no_latency_or_inferred_metrics(self):
        self.fixture.add_all_captures()
        evaluation = self.evaluate()
        payload = VERIFY.build_publish_manifest(
            self.fixture.run_dir,
            evaluation["prepared"],
            evaluation["captures"],
            {"g05_perf": "PASS"},
        )
        keys = {key for _location, key in VERIFY._iter_keys(payload)}
        forbidden = {
            "engine_ns",
            "latency",
            "p50_ns",
            "p95_ns",
            "p99_ns",
            "speedup",
            "stage_ns",
            "inferred_stage_ns",
            "sum_inclusive_cpu_percent",
        }
        self.assertEqual(keys & forbidden, set())
        self.assertEqual(payload["raw_evidence_access"], "PRIVATE_PENDING_REVIEW")
        text = json.dumps(payload, sort_keys=True)
        self.assertIsNone(re.search(r"""[\"']/(?:home|Users|root|mnt|tmp)/""", text))
        self.assertNotIn(VERIFY._current_host(), text)

    def test_t43_publication_is_written_by_a_separate_explicit_mode(self):
        self.fixture.add_all_captures()
        destination = os.path.join(self.fixture.run_dir, "published", "manifest.json")
        evaluation = self.evaluate()
        for capture in evaluation["captures"].values():
            capture["test_fixture"] = False
        result = VERIFY.publish_manifest(
            self.fixture.run_dir,
            evaluation["prepared"],
            evaluation["captures"],
            {"g05_perf": "PASS"},
            dest=destination,
        )
        self.assertTrue(result["written"])
        self.assertTrue(os.path.isfile(destination))
        again = VERIFY.publish_manifest(
            self.fixture.run_dir,
            evaluation["prepared"],
            evaluation["captures"],
            {"g05_perf": "PASS"},
            dest=destination,
        )
        self.assertFalse(again["written"])
        self.assertEqual(result["sha256"], again["sha256"])


if __name__ == "__main__":
    unittest.main()
