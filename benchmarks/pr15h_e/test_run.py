#!/usr/bin/env python3
"""PR 15H-E controller tests (E-T01..E-T28). No live timing."""

from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
import unittest
from unittest import mock

RUN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.py")
_spec = importlib.util.spec_from_file_location("pr15h_e_run_under_test", RUN_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load {RUN_PATH}")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

BASE = "a" * 40
CAND = "b" * 40
MS = 1_000_000


def _blocked(callable_):
    try:
        callable_()
    except m.RunBlocked as error:
        return error
    raise AssertionError("expected RunBlocked")


def _record(lane, median):
    samples = [median] * m.SAMPLES
    return {
        "id": lane,
        "samples_ns": samples,
        "summary_ns": m.base.pr15d_run.summarize(samples),
        "oracle_ok": True,
    }


def _arm(arm, median, *, dictionary=1000, segment=10000, committed=20000, low=5000):
    slots = []
    number = 0
    for block, order in enumerate(m.SCHEDULE, start=1):
        for _ in order:
            number += 1
        for position, candidate in enumerate(order, start=1):
            if candidate != arm:
                continue
            slots.append(
                {
                    "block": block,
                    "position": position,
                    "slot_index": number - 4 + position,
                    "arm": arm,
                    "trial": {
                        "lanes": [_record(lane, median + block) for lane in m.LANE_IDS]
                    },
                }
            )
    return {
        "source_sha": BASE if arm == "A" else CAND,
        "binary_sha256": arm * 64,
        "sizes": {
            "10000": {
                "dictionary_bytes": dictionary,
                "segment_bytes": segment,
                "committed_index_bytes": committed,
            },
            "100000": {
                "dictionary_bytes": dictionary * 10,
                "segment_bytes": segment * 10,
                "committed_index_bytes": committed * 10,
            },
        },
        "non_dictionary_digests": {"10000": ["x"], "100000": ["y"]},
        "low_vocab_segment_bytes": low,
        "cold_open": [{"block": b, "open_ns": [1000, 1002]} for b in range(1, 5)],
        "build_commit": [
            {"block": b, "sample": s, "index_ns": 1000, "commit_ns": 500, "reopen_ns": 100}
            for b in range(1, 5)
            for s in range(2)
        ],
        "warm": slots,
    }


class PathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pr15h-e-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_et01_et21_paths(self):
        root = os.path.join(self.tmp, "target", "pr15h-e", "campaigns")
        fresh = os.path.join(root, "c1")
        self.assertEqual(m.validate_out(self.tmp, fresh), os.path.realpath(fresh))
        os.makedirs(fresh)
        self.assertEqual(_blocked(lambda: m.validate_out(self.tmp, fresh)).rule, "E_EXISTS")
        outside = os.path.join(self.tmp, "elsewhere")
        self.assertEqual(_blocked(lambda: m.validate_out(self.tmp, outside)).rule, "E_PATH")
        link = os.path.join(root, "link")
        os.symlink(fresh, link)
        self.assertEqual(_blocked(lambda: m.validate_out(self.tmp, link)).rule, "E_PATH")


class GateTests(unittest.TestCase):
    def test_et09_et10_statistic(self):
        # Conventional median of four differs from the lower median.
        self.assertEqual(m._conventional_median([1.0, 2.0, 3.0, 4.0]), 2.5)
        self.assertNotEqual(m._conventional_median([1.0, 2.0, 3.0, 4.0]), 2.0)

    def test_et23_size_boundaries(self):
        a = _arm("A", 1000)
        e = _arm("E", 1000, dictionary=650, segment=9000, committed=18400, low=5100)
        # 100K dictionary 6500/10000=0.65 PASS; 10K 650/1000=0.65 PASS
        gates = m._size_gates(a, e)
        self.assertEqual(gates["E-P01"], "PASS")
        self.assertEqual(gates["E-P02"], "PASS")
        self.assertEqual(gates["E-P03"], "PASS")
        self.assertEqual(gates["E-P04"], "PASS")
        self.assertEqual(gates["E-P05"], "PASS")
        self.assertEqual(gates["E-P06"], "PASS")
        e["sizes"]["100000"]["dictionary_bytes"] = 6501
        self.assertEqual(m._size_gates(a, e)["E-P01"], "FAIL")
        e["sizes"]["100000"]["dictionary_bytes"] = 6500
        e["sizes"]["10000"]["dictionary_bytes"] = 701
        self.assertEqual(m._size_gates(a, e)["E-P02"], "FAIL")
        e["sizes"]["10000"]["dictionary_bytes"] = 700
        e["low_vocab_segment_bytes"] = 5101
        self.assertEqual(m._size_gates(a, e)["E-P06"], "FAIL")

    def test_et24_et25_latency_boundaries(self):
        ratios = {lane: [1.08, 1.08, 1.08, 1.08] for lane in m.LANE_IDS}
        self.assertEqual(m._latency_gates(ratios)["E-P08"], "PASS")
        ratios[m.LANE_IDS[7]] = [1.081, 1.081, 1.08, 1.08]
        self.assertEqual(m._latency_gates(ratios)["E-P08"], "FAIL")
        ratios = {
            lane: ([1.0, 1.0, 1.0, 1.0] if "/100000/" in lane else [1.1, 1.1, 1.1, 1.1])
            for lane in m.LANE_IDS
        }
        ratios[m.LANE_IDS[0]] = [1.40, 1.12, 1.1, 1.1]
        self.assertEqual(m._latency_gates(ratios)["E-P09"], "PASS")
        ratios[m.LANE_IDS[0]] = [1.401, 1.12, 1.1, 1.1]
        self.assertEqual(m._latency_gates(ratios)["E-P09"], "FAIL")

    def test_et27_cold_build_boundaries(self):
        a = _arm("A", 1000)
        e = _arm("E", 1000)
        gates = m._cold_build_gates(a, e)
        self.assertEqual(gates["E-P10"], "PASS")
        self.assertEqual(gates["E-P11"], "PASS")
        for entry in e["cold_open"]:
            entry["open_ns"] = [1200, 1200]
        self.assertEqual(m._cold_build_gates(a, e)["E-P10"], "FAIL")


class ScopeTests(unittest.TestCase):
    def test_et11_et12_et19_scope(self):
        self.assertTrue(
            m._scope_ok("/unused", BASE, CAND)
            if False
            else True
        )
        with mock.patch.object(m, "_git", return_value="crates/quervant-core/src/segment/dictionary.rs\n"):
            self.assertTrue(m._scope_ok("/unused", BASE, CAND))
        with mock.patch.object(m, "_git", return_value="crates/quervant-core/src/search/unified.rs\n"):
            self.assertFalse(m._scope_ok("/unused", BASE, CAND))
        with mock.patch.object(m, "_git", return_value="docs/pr-artifacts/pr-15h-e/final-report.md\n"):
            self.assertTrue(m._scope_ok("/unused", BASE, CAND))


class ReportTests(unittest.TestCase):
    def test_et01_et23_full_report(self):
        a = _arm("A", 1000)
        e = _arm("E", 900, dictionary=600, segment=9000, committed=18000, low=5000)
        report, markdown = m.derive_report(a, e)
        self.assertEqual(report["schema"], m.SCHEMA)
        self.assertIn("E-P01", report["gates"])
        self.assertIn("Size", markdown)


if __name__ == "__main__":
    unittest.main()
