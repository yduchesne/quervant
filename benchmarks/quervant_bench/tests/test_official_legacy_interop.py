"""Compatibility with the actual frozen writer shapes, without acquisition."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quervant_bench.config.errors import BM_IDENTITY_INVALID, BenchError
from quervant_bench.official import admission, protocols
from quervant_bench.official.legacy_readiness import validate_retained_readiness
from quervant_bench.official.retained_backend import legacy_runner
from quervant_bench.tests import official_support as support


class LegacyReadinessInteropTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = legacy_runner()
        self.protocol, _ = self.runner.load_protocol()
        self.template = protocols.read_canonical_json(protocols.template_path(protocols.STUDY_RETAINED_KEY))
        # Execute only the old record construction, with all clocks, sleeps and
        # proc reads substituted. No adapter is constructed or queried.
        counters = [(6_000_000_000 + i * 1_000_000_000, {0: (i, 0, 0, i * 99, 0, 0, 0, 0), 1: (i, 0, 0, i * 99, 0, 0, 0, 0)}) for i in range(7)]
        with patch.object(self.runner.time, "sleep"), patch.object(self.runner.time, "monotonic_ns", side_effect=[0, 6_000_000_000]), patch.object(self.runner, "read_ticks", side_effect=counters):
            self.record = self.runner.readiness(self.protocol, 0, 1, "a" * 64)
        self.record["campaign"] = protocols.D3C_CONTROL_NAME

    def check(self, document):
        return validate_retained_readiness(document, campaign=protocols.D3C_CONTROL_NAME, requirements=self.template["host_requirements"])

    def test_actual_writer_record_is_accepted_without_conversion(self) -> None:
        original = copy.deepcopy(self.record)
        self.assertEqual(self.check(self.record), self.record)
        self.assertEqual(self.record, original)
        self.assertEqual(self.record["queries_executed"], 0)

    def test_ready_label_cannot_hide_changed_raw_counters(self) -> None:
        for item in self.record["observations"][1:]:
            item["cpus"]["0"][0] *= 100
        with self.assertRaises(BenchError) as failure:
            self.check(self.record)
        self.assertEqual(failure.exception.code, BM_IDENTITY_INVALID)

    def test_edited_metrics_settling_and_duration_are_rejected(self) -> None:
        for field in ("metric", "settle", "duration", "queries"):
            changed = copy.deepcopy(self.record)
            if field == "metric":
                changed["interval_metrics"]["controller"][0]["busy_permille"] = 0
            elif field == "settle":
                changed["settle_monotonic_end_ns"] = 1
            elif field == "duration":
                changed["observations"][-1]["monotonic_ns"] += 1_000_000_000
            else:
                changed["queries_executed"] = True
            with self.subTest(field=field), self.assertRaises(BenchError):
                self.check(changed)


class LegacySummaryInteropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.template = protocols.read_canonical_json(protocols.template_path(protocols.STUDY_RETAINED_KEY))
        source = cls.template["source_requirements"]
        support.make_retained_key_campaign(root=cls.root, campaign=protocols.D3C_CONTROL_NAME,
            template=cls.template, base_commit=source["base_commit"], experiment_commit=source["experiment_commit"],
            sentinel=source["index_100k_committed_sentinel"])
        cls.manifest = support.read_json(cls.root / "manifest.json")
        cls.plan = admission._frozen_schedule(cls.template, protocols.D3C_CONTROL_NAME)[:1]
        cls.path = cls.root / "raw" / "slots" / "slot-01.json"
        cls.original = support.read_json(cls.path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def verify(self, document):
        support.write_json(self.path, document)
        return admission._verify_retained_key_slots(self.root, campaign=protocols.D3C_CONTROL_NAME,
            plan=self.plan, manifest=self.manifest, template=self.template)

    def test_frozen_count_and_median_only_shape_is_supported(self) -> None:
        document = copy.deepcopy(self.original)
        for lane in document["lanes"]:
            lane["summary_ns"] = {"count": 20, "median": sorted(lane["samples_ns"])[9]}
        self.assertEqual(self.verify(document)[0], document)

    def test_optional_extrema_and_numeric_alias_are_checked(self) -> None:
        for field, value in (("min", 0), ("max", 1), ("median", float(self.original["lanes"][0]["summary_ns"]["median"]))):
            document = copy.deepcopy(self.original)
            document["lanes"][0]["summary_ns"][field] = value
            with self.subTest(field=field), self.assertRaises(BenchError) as raised:
                self.verify(document)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


if __name__ == "__main__":
    unittest.main()
