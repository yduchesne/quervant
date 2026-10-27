#!/usr/bin/env python3
"""Unit tests for the read-only PR 14F trial auditor.

These fixtures never substitute for live provider qualification: they only prove
that malformed, stale, duplicated or contradictory evidence is rejected.
"""
import copy
import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib.util

spec = importlib.util.spec_from_file_location(
    "audit_pr14f_trials", Path(__file__).resolve().parent / "audit-pr14f-trials.py"
)
audit_pr14f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_pr14f)

SHA = "a" * 40
DIGEST = "b" * 64
SAMPLES = 20


def rows():
    out = []
    for (lane, workload), hits in audit_pr14f.REQUIRED.items():
        for sample in range(SAMPLES):
            out.append([lane, workload, sample, "1000.0", hits, "4096"])
    return out


class AuditFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.qual = self.root / "target" / "pr14-p4" / "qualification" / SHA
        self.qual.mkdir(parents=True)
        self.reports = []
        for index in (1, 2, 3):
            self.reports.append(self._make_trial(index, rows()))

    def tearDown(self):
        self._tmp.cleanup()

    def _write_csv(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(audit_pr14f.HEADER)
            writer.writerows(data)

    def _make_trial(self, index, data, csv_name=None, **overrides):
        csv_path = self.root / "raw" / (csv_name or f"pr14-p4-t{index}.csv")
        self._write_csv(csv_path, data)
        report = {
            "workload": "pr14_p4_v1",
            "trial": f"t{index}",
            "sha": SHA,
            "corpus_docs": 20000,
            "corpus_digest": DIGEST,
            "warmups": 3,
            "samples": SAMPLES,
            "qualified": True,
            "idle_confirmed": True,
            "contention": "clear",
            "dirty": False,
            "raw_csv": str(csv_path),
            "summary": ["ok"],
        }
        report.update(overrides)
        report_path = self.root / "reports" / f"pr14-p4-t{index}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report), encoding="utf-8")
        contention = self.qual / f"pr14-p4-contention-t{index}.json"
        contention.write_text(json.dumps({"state": "clear"}), encoding="utf-8")
        return report_path

    def audit(self, reports=None):
        reports = [str(path) for path in (reports or self.reports)]
        return audit_pr14f.audit(reports, SHA, DIGEST, self.root)

    def rewrite(self, index, data):
        self.reports[index] = self._make_trial(index + 1, data)

    def assert_rejected(self, reports=None):
        errors = self.audit(reports)
        self.assertTrue(errors, "malformed fixture was accepted")

    def test_complete_fixture_passes(self):
        self.assertEqual(self.audit(), [])

    def test_bad_or_stale_sha_is_rejected(self):
        self.reports[2] = self._make_trial(3, rows(), sha="ab9b2d7da066ec80190dcee70a8cebfd81481b80")
        self.assert_rejected()

    def test_mismatched_digest_is_rejected(self):
        self.reports[1] = self._make_trial(2, rows(), corpus_digest="c" * 64)
        self.assert_rejected()

    def test_missing_digest_is_rejected(self):
        self.reports[0] = self._make_trial(1, rows(), corpus_digest=None)
        self.assert_rejected()

    def test_duplicate_trial_id_is_rejected(self):
        self.reports[1] = self._make_trial(1, rows())
        self.assert_rejected()

    def test_unqualified_report_is_rejected(self):
        self.reports[2] = self._make_trial(3, rows(), qualified=False)
        self.assert_rejected()

    def test_contention_not_clear_is_rejected(self):
        self.reports[0] = self._make_trial(1, rows(), contention="suspected")
        self.assert_rejected()

    def test_duplicate_sample_is_rejected(self):
        data = rows()
        data[1][2] = 0
        self.rewrite(0, data)
        self.assert_rejected()

    def test_missing_lane_is_rejected(self):
        data = [row for row in rows() if (row[0], row[1]) != ("local-warm", "W05")]
        self.rewrite(1, data)
        self.assert_rejected()

    def test_wrong_hit_count_is_rejected(self):
        data = rows()
        data[0][4] = 9999
        self.rewrite(2, data)
        self.assert_rejected()

    def test_wrong_sample_index_is_rejected(self):
        data = rows()
        data[5][2] = SAMPLES
        self.rewrite(0, data)
        self.assert_rejected()

    def test_nonfinite_duration_is_rejected(self):
        data = rows()
        data[3][3] = str(math.inf)
        self.rewrite(1, data)
        self.assert_rejected()

    def test_nan_duration_is_rejected(self):
        data = rows()
        data[3][3] = "nan"
        self.rewrite(1, data)
        self.assert_rejected()

    def test_negative_duration_is_rejected(self):
        data = rows()
        data[7][3] = "-1"
        self.rewrite(2, data)
        self.assert_rejected()

    def test_zero_duration_is_rejected(self):
        data = rows()
        data[7][3] = "0"
        self.rewrite(2, data)
        self.assert_rejected()

    def test_w08_lane_is_rejected(self):
        data = rows() + [["local-warm", "W08", 0, "1.0", 10000, "4096"]]
        self.rewrite(0, data)
        self.assert_rejected()

    def test_unknown_lane_is_rejected(self):
        data = rows() + [["remote-hot", "W02", 0, "1.0", 10000, "4096"]]
        self.rewrite(1, data)
        self.assert_rejected()

    def test_short_csv_is_rejected(self):
        data = [row for row in rows() if row[2] < SAMPLES - 1]
        self.rewrite(2, data)
        self.assert_rejected()

    def test_missing_csv_is_rejected(self):
        path = Path(json.loads(self.reports[0].read_text())["raw_csv"])
        path.unlink()
        self.assert_rejected()

    def test_shared_csv_is_rejected(self):
        raw = json.loads(self.reports[0].read_text())["raw_csv"]
        report = json.loads(self.reports[1].read_text())
        report["raw_csv"] = raw
        self.reports[1].write_text(json.dumps(report), encoding="utf-8")
        self.assert_rejected()

    def test_missing_contention_record_is_rejected(self):
        (self.qual / "pr14-p4-contention-t2.json").unlink()
        self.assert_rejected()

    def test_contention_record_with_unknown_state_is_rejected(self):
        (self.qual / "pr14-p4-contention-t3.json").write_text(
            json.dumps({"state": "unknown"}), encoding="utf-8"
        )
        self.assert_rejected()

    def test_wrong_header_is_rejected(self):
        path = Path(json.loads(self.reports[0].read_text())["raw_csv"])
        path.write_text("lane,workload,micros\nlocal-warm,W02,1.0\n", encoding="utf-8")
        self.assert_rejected()

    def test_too_few_reports_are_rejected(self):
        self.assert_rejected(self.reports[:2])

    def test_audit_does_not_mutate_inputs(self):
        before = copy.deepcopy([path.read_bytes() for path in self.reports])
        self.assertEqual(self.audit(), [])
        after = [path.read_bytes() for path in self.reports]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
