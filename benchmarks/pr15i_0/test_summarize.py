#!/usr/bin/env python3
"""Deterministic tests for ``benchmarks/pr15i_0/summarize.py``.

The calculator is tested against synthetic campaign trees only. It must compute
every published ratio from the current qualified manifests, never mix historical
values into a current ratio, and never convert an inclusive CPU share into a
latency estimate.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import summarize  # noqa: E402  (module under test)


def load_fixtures():
    spec = importlib.util.spec_from_file_location(
        "pr15i0_verify_fixtures", os.path.join(HERE, "test_verify.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIXTURES = load_fixtures()


def build_tree(source: str = FIXTURES.SOURCE):
    root, paths = FIXTURES.build_root(source=source)
    verification = {
        "schema": "pr15i-0-verification-v1",
        "controller_version": "pr15i-0-controller-1",
        "source_sha": source,
        "protocol": {"sha256": "a" * 64},
        "qualified": True,
        "overall_status": "15I0_QUALIFIED_REVIEW_READY",
        "gates": {
            gate: {"status": "PASS"} for gate in ("I0-P00", "I0-P03", "I0-P05", "I0-P08")
        },
    }
    verification_path = os.path.join(root, "target", "pr15i-0", "verification-02.json")
    FIXTURES.write_json(verification_path, verification)
    return root, paths, verification_path, verification


class TreeTestCase(unittest.TestCase):
    def setUp(self):
        self.root, self.paths, self.verification_path, self.verification = build_tree()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_summary(self, verification=None):
        payload = verification or self.verification
        if verification is not None:
            FIXTURES.write_json(self.verification_path, payload)
        argv = [
            "--root",
            self.root,
            "--verification",
            self.verification_path,
            "--pr15d-run",
            self.paths["pr15d"],
            "--pr15f-run",
            self.paths["pr15f"],
            "--pr15f-prepared",
            self.paths["prepared"],
            "--mutation-run",
            self.paths["mutation"],
            "--out-json",
            os.path.join(self.root, "benchmarks/reports/pr15i-0/pr15i-0-summary.json"),
            "--out-md",
            os.path.join(self.root, "docs/pr-artifacts/pr-15i-0/measurements.md"),
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            return summarize.run(parse(argv))

    def read(self, relative):
        return summarize.read_json(os.path.join(self.root, relative))


class Args:
    def __init__(self, values):
        self.__dict__.update(values)


def parse(argv):
    values = {}
    index = 0
    while index < len(argv):
        key = argv[index].lstrip("-").replace("-", "_")
        values[key] = argv[index + 1]
        index += 2
    return Args(values)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class HelperTests(unittest.TestCase):
    def test_median_is_lower_middle_for_even_samples(self):
        self.assertEqual(summarize.median_int([3, 1, 2]), 2)
        self.assertEqual(summarize.median_int([4, 1, 3, 2]), 3)

    def test_median_rejects_empty(self):
        with self.assertRaises(summarize.SummaryError):
            summarize.median_int([])

    def test_ratio_returns_none_on_zero_denominator(self):
        self.assertIsNone(summarize.ratio(1, 0))
        self.assertIsNone(summarize.ratio(None, 1))

    def test_rounded_uses_three_places_but_keeps_precision_upstream(self):
        self.assertEqual(summarize.rounded(1.23456), 1.235)
        self.assertEqual(summarize.rounded(2.0 / 3.0), 0.667)
        self.assertIsNone(summarize.rounded(None))

    def test_not_comparable_shape(self):
        self.assertEqual(summarize.not_comparable("reason")["status"], "NOT_COMPARABLE")
        self.assertEqual(summarize.not_comparable("reason")["reason"], "reason")

    def test_canonical_json_is_sorted_and_compact(self):
        data = summarize.canonical_json_bytes({"b": 1, "a": [2, 3]})
        self.assertEqual(data, b'{"a":[2,3],"b":1}\n')


# ---------------------------------------------------------------------------
# Derived formulas
# ---------------------------------------------------------------------------


class DerivationTests(TreeTestCase):
    def setUp(self):
        super().setUp()
        self.derived = summarize.derive(
            self.verification,
            self.paths["pr15d"],
            self.paths["pr15f"],
            self.paths["mutation"],
        )

    def test_index_bytes_are_the_trial_median_not_a_historical_value(self):
        # Fixture trials write index_bytes = 1000 * n + len(engine).
        for n in (10000, 100000):
            self.assertEqual(
                self.derived["index_bytes"][str(n)]["bytes"]["quervant"], 1000 * n + 8
            )
            self.assertEqual(
                self.derived["index_bytes"][str(n)]["bytes"]["tantivy"], 1000 * n + 7
            )
        self.assertNotEqual(
            self.derived["index_bytes"]["100000"]["bytes"]["quervant"],
            summarize.HISTORICAL["index_bytes_100000"],
        )

    def test_index_ratio_is_quervant_over_comparison(self):
        ratios = self.derived["index_bytes"]["100000"]["ratio_quervant_over"]
        expected = (100000 * 1000 + 8) / (100000 * 1000 + 7)
        self.assertEqual(ratios["tantivy"], summarize.rounded(expected))
        self.assertEqual(
            self.derived["index_bytes"]["100000"]["caveat"],
            "PHYSICAL_SEGMENT_SCHEMA_DIFFERS",
        )

    def test_process_cold_ratio_is_not_comparable(self):
        cold = [
            lane
            for lane in self.derived["latency"].values()
            if lane["regime"] == "process_cold"
        ]
        self.assertTrue(cold)
        for lane in cold:
            self.assertEqual(
                lane["ratio_quervant_over_tantivy"]["status"], "NOT_COMPARABLE"
            )

    def test_warm_ratio_is_computed(self):
        warm = [
            lane
            for lane in self.derived["latency"].values()
            if lane["regime"] == "warm"
        ]
        self.assertEqual(len(warm), 16)
        self.assertTrue(all(isinstance(lane["ratio_quervant_over_tantivy"], float) for lane in warm))

    def test_physical_sort_caveat_is_attached_to_every_lane(self):
        for lane in self.derived["latency"].values():
            self.assertEqual(lane["physical_sort_caveat"], "PHYSICAL_SORT_ENCODING_DIFFERS")

    def test_section_shares_use_the_committed_index_total(self):
        summary = dict(self.derived)
        summarize.attach_sections(summary, self.paths["pr15f"])
        entry = summary["sections"]["100000"]
        total = entry["total_file_bytes"]
        for kind, section in entry["sections"].items():
            self.assertEqual(section["bytes"], {"Stored": 10, "Postings": 5}[kind])
            self.assertAlmostEqual(
                section["share_of_index_percent"], round(100.0 * section["bytes"] / total, 4)
            )

    def test_sidecar_shares_use_the_sidecar_file_size(self):
        for n in ("10000", "100000"):
            entry = self.derived["mutation"][n]
            total = entry["sidecar_file_bytes"]
            for name, share in entry["component_share_percent"].items():
                expected = round(100.0 * entry["component_bytes"][name] / total, 4)
                self.assertAlmostEqual(share, expected)
            self.assertEqual(
                entry["saved_bytes_upper_bound_label"], "PHYSICAL_ZERO_BYTE_CEILING_ONLY"
            )

    def test_batch_detail_label_survives_derivation(self):
        for n in ("10000", "100000"):
            self.assertEqual(
                self.derived["mutation"][n]["batch_replay_detail"], "NOT_APPLICABLE"
            )

    def test_unknown_cpu_bucket_is_preserved(self):
        for lane in self.derived["quervant_profile"]["lanes"].values():
            self.assertEqual(lane["unknown_exclusive_percent"], 60.0)

    def test_allocation_captures_are_collected_in_both_shapes(self):
        os.makedirs(os.path.join(self.paths["pr15f"], "allocation"), exist_ok=True)
        FIXTURES.write_json(
            os.path.join(self.paths["pr15f"], "allocation", "summary.json"),
            {
                "schema": "pr15f-allocation-campaign-v1",
                "status": "QUALIFIED",
                "captures": {
                    "n100000/rare": {
                        "capture_id": "a",
                        "status": "CAPTURED",
                        "heaptrack_version": "heaptrack 1.5.0",
                    },
                    "n100000/common": {"capture_id": "b", "status": "CAPTURED"},
                },
            },
        )
        derived = summarize.derive(
            self.verification,
            self.paths["pr15d"],
            self.paths["pr15f"],
            self.paths["mutation"],
        )
        allocation = derived["quervant_profile"]["allocation"]
        self.assertEqual(allocation["status"], "QUALIFIED")
        self.assertEqual(len(allocation["captured"]), 2)
        self.assertEqual(allocation["heaptrack_version"], "heaptrack 1.5.0")

    def test_missing_allocation_is_not_zero(self):
        allocation = self.derived["quervant_profile"]["allocation"]
        self.assertEqual(allocation["status"], "ALLOCATION_NOT_MEASURED")
        self.assertEqual(allocation["captured"], [])

    def test_reopen_ratio_uses_trial_medians(self):
        self.assertEqual(
            self.derived["reopen"]["100000"]["reopen_ns"]["quervant"], 30
        )
        self.assertAlmostEqual(
            self.derived["reopen"]["100000"]["ratio_quervant_over_tantivy"], 1.0
        )


class IncompleteGateTests(TreeTestCase):
    def test_ratios_are_not_comparable_when_three_engine_gate_fails(self):
        verification = json.loads(json.dumps(self.verification))
        verification["gates"]["I0-P03"]["status"] = "FAIL"
        verification["qualified"] = False
        derived = summarize.derive(
            verification,
            self.paths["pr15d"],
            self.paths["pr15f"],
            self.paths["mutation"],
        )
        self.assertEqual(
            derived["index_bytes"]["10000"]["ratio_quervant_over"]["status"],
            "NOT_COMPARABLE",
        )
        for lane in derived["latency"].values():
            self.assertEqual(
                lane["ratio_quervant_over_tantivy"]["status"], "NOT_COMPARABLE"
            )


# ---------------------------------------------------------------------------
# Publication and privacy
# ---------------------------------------------------------------------------


class PublicationTests(TreeTestCase):
    def test_summary_writes_json_markdown_and_privacy_scan(self):
        self.assertEqual(self.run_summary(), 0)
        summary = self.read("benchmarks/reports/pr15i-0/pr15i-0-summary.json")
        self.assertEqual(summary["schema"], summarize.SCHEMA_SUMMARY)
        self.assertIn("index_bytes", summary)
        self.assertIn("mutation", summary)
        with open(
            os.path.join(self.root, "docs/pr-artifacts/pr-15i-0/measurements.md"),
            encoding="utf-8",
        ) as handle:
            markdown = handle.read()
        self.assertIn("PR 15I-0 — measured baseline", markdown)
        self.assertIn("HISTORICAL", markdown)
        scan = self.read("benchmarks/reports/pr15i-0/privacy-scan.json")
        self.assertEqual(scan["status"], "PASS")
        self.assertTrue(scan["files"])

    def test_historical_context_is_separate(self):
        self.assertEqual(self.run_summary(), 0)
        historical = self.read("benchmarks/reports/pr15i-0/historical-context.json")
        self.assertEqual(historical["schema"], "pr15i-0-historical-context-v1")
        self.assertEqual(
            historical["mixing_policy"],
            "historical values are never combined with current samples",
        )
        summary = self.read("benchmarks/reports/pr15i-0/pr15i-0-summary.json")
        self.assertNotIn("historical", json.dumps(summary["index_bytes"]))
        self.assertEqual(
            summary["index_bytes"]["100000"]["bytes"]["quervant"], 100000 * 1000 + 8
        )

    def test_all_nine_profile_lanes_are_present(self):
        self.assertEqual(self.run_summary(), 0)
        summary = self.read("benchmarks/reports/pr15i-0/pr15i-0-summary.json")
        self.assertEqual(len(summary["quervant_profile"]["lanes"]), 9)

    def test_privacy_scan_detects_a_host_path(self):
        os.makedirs(os.path.join(self.root, "docs/pr-artifacts/pr-15i-0"), exist_ok=True)
        with open(
            os.path.join(self.root, "docs/pr-artifacts/pr-15i-0/measurements.md"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("# leak /home/someone/secret\n")
        os.makedirs(os.path.join(self.root, "benchmarks/reports/pr15i-0"), exist_ok=True)
        scan = summarize.scan_reports(self.root)
        self.assertEqual(scan["status"], "FAIL")
        self.assertTrue(scan["problems"])

    def test_privacy_scan_is_idempotent(self):
        self.assertEqual(self.run_summary(), 0)
        first = self.read("benchmarks/reports/pr15i-0/privacy-scan.json")
        self.assertEqual(self.run_summary(), 0)
        second = self.read("benchmarks/reports/pr15i-0/privacy-scan.json")
        self.assertEqual(first["files"], second["files"])


if __name__ == "__main__":
    unittest.main()
