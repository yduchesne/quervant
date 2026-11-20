"""BM09-CURRENT-BASELINE-1 T04: bounded historical inputs and disclosures."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from decimal import Decimal
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import zipfile

from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE, BM_FILE_MISSING, BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError,
)
from quervant_bench.official import history
from quervant_bench.official.policy_inputs import HISTORICAL_ARCHIVE_DIGESTS

DIGEST = "sha256:" + "1" * 64
BASELINE = "33333333-3333-4333-8333-333333333333"
STUDY = "retained-key-topk-real-v1"

# Independent source/oracle literals: do not derive these from production grids or
# pair mappings. These synthetic records are never authenticated as old evidence.
PAIR_ORACLE = (
    ("R_L_A", "CI_L_A", "A", "L", "0.8", "20"),
    ("R_P_A", "CI_P_A", "A", "P", "0.6", "40"),
    ("R_H_A", "CI_H_A", "A", "H", "0.3", "70"),
    ("R_P_L", "CI_P_L", "L", "P", "0.75", "25"),
    ("R_H_L", "CI_H_L", "L", "H", "0.375", "62.5"),
    ("R_H_P", "CI_H_P", "P", "H", "0.5", "50"),
)
RETAINED_CAMPAIGN_ORACLE = (
    "d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02",
)
F1_PATH_ORACLE = (
    "benchmarks/pr15i_d3_c_t7/analysis.py",
    "benchmarks/pr15i_d3_c_t7/policy.py",
    "benchmarks/pr15i_d3_c_t7/verify_derived.py",
    "benchmarks/pr15i_d3_c_t7/freeze.py",
)


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class InventoryTests(unittest.TestCase):
    def _inventory(self, candidates):
        return {"kind": history.INVENTORY_KIND, "schema_version": 1, "candidates": candidates}

    def _candidate(self, **overrides):
        values = {
            "family": "retained-key",
            "input_role": "retained-micro",
            "path": "micro.json",
            "source_identity": "micro-05",
            "expected_digest": None,
        }
        values.update(overrides)
        return values

    def test_valid_inventory_roundtrip(self) -> None:
        document = self._inventory([self._candidate()])
        self.assertEqual(history.validate_inventory(document)["candidates"][0]["path"], "micro.json")

    def test_invalid_inventories_are_rejected(self) -> None:
        cases = [
            ({"kind": "other", "schema_version": 1, "candidates": []}, BM_SCHEMA_INVALID),
            ({"kind": history.INVENTORY_KIND, "schema_version": 2, "candidates": []}, BM_SCHEMA_INVALID),
            ({"kind": history.INVENTORY_KIND, "schema_version": True, "candidates": []}, BM_SCHEMA_INVALID),
            ({"kind": history.INVENTORY_KIND, "schema_version": 1, "candidates": {}}, BM_SCHEMA_INVALID),
            (self._inventory([self._candidate(family="other")]), BM_SCHEMA_INVALID),
            (self._inventory([self._candidate(input_role="unknown")]), BM_SCHEMA_INVALID),
            (self._inventory([self._candidate(family="cross-engine")]), BM_IDENTITY_INVALID),
            (self._inventory([self._candidate(expected_digest="deadbeef")]), BM_IDENTITY_INVALID),

            (
                self._inventory([self._candidate(), self._candidate()]),
                BM_SCHEMA_INVALID,
            ),
            (
                self._inventory([self._candidate(extra=True)]),
                BM_SCHEMA_INVALID,
            ),
        ]
        for document, code in cases:
            with self.subTest(document=document):
                with self.assertRaises(BenchError) as raised:
                    history.validate_inventory(document)
                self.assertEqual(raised.exception.code, code)


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _inventory(self, *candidates):
        return {"kind": history.INVENTORY_KIND, "schema_version": 1, "candidates": list(candidates)}

    def test_t04_genuine_pr15d_positive_does_not_mutate_the_catalog(self) -> None:
        from quervant_bench.tests import official_support as support

        before = dict(history.SUPPORTED_SOURCES)
        entry = history.classify_candidate(
            support.REPO_ROOT / "benchmarks",
            {
                "family": "cross-engine",
                "input_role": "pr15d-aggregate",
                "path": "reports/pr15d/pr15d-qualified.json",
                "source_identity": history.PR15D_AGGREGATE_RUN,
                "expected_digest": history.SUPPORTED_SOURCES[("pr15d-aggregate", history.PR15D_AGGREGATE_RUN)],
            },
        )
        self.assertEqual(entry["status"], history.STATUS_FOUND)
        self.assertEqual(len(entry["normalized_rows"]), 32)
        self.assertEqual(dict(history.SUPPORTED_SOURCES), before)
        with self.assertRaises(TypeError):
            history.SUPPORTED_SOURCES[("pr15d-aggregate", "x")] = "sha256:" + "0" * 64

    def test_t04_unsupported_identity_cannot_be_promoted_by_a_caller_hash(self) -> None:
        payload = b"arbitrary-bytes"
        (self.root / "anything.tar.gz").write_bytes(payload)
        entries = history.build_entries(
            self.root,
            self._inventory(
                {
                    "family": "retained-key",
                    "input_role": "retained-archive",
                    "path": "anything.tar.gz",
                    "source_identity": "d3c-v3r3-not-a-campaign",
                    "expected_digest": _sha(payload),
                }
            ),
        )
        self.assertEqual(entries[0]["status"], history.STATUS_UNVERIFIED)
        self.assertEqual(entries[0]["reason"], "unsupported-source-identity")
        self.assertEqual(entries[0]["normalized_rows"], [])

    def test_t04_declared_digest_conflicting_with_the_anchor_is_invalid(self) -> None:
        campaign = sorted(HISTORICAL_ARCHIVE_DIGESTS)[0]
        (self.root / f"{campaign}.tar.gz").write_bytes(b"whatever")
        entries = history.build_entries(
            self.root,
            self._inventory(
                {
                    "family": "retained-key",
                    "input_role": "retained-archive",
                    "path": f"{campaign}.tar.gz",
                    "source_identity": campaign,
                    "expected_digest": "sha256:" + "7" * 64,
                }
            ),
        )
        self.assertEqual(entries[0]["status"], history.STATUS_INVALID)
        self.assertEqual(
            entries[0]["reason"], "declared-digest-conflicts-with-independent-anchor"
        )

    def test_t04_frozen_digest_mismatch_is_invalid_not_found(self) -> None:
        campaign = sorted(HISTORICAL_ARCHIVE_DIGESTS)[0]
        (self.root / f"{campaign}.tar.gz").write_bytes(b"wrong-bytes")
        entries = history.build_entries(
            self.root,
            self._inventory(
                {
                    "family": "retained-key",
                    "input_role": "retained-archive",
                    "path": f"{campaign}.tar.gz",
                    "source_identity": campaign,
                    "expected_digest": HISTORICAL_ARCHIVE_DIGESTS[campaign],
                }
            ),
        )
        self.assertEqual(entries[0]["status"], history.STATUS_INVALID)
        self.assertEqual(entries[0]["reason"], "digest-mismatch")
        self.assertEqual(history.comparable_pairs(entries), [])

    def test_t04_missing_input_is_recorded_and_does_not_raise(self) -> None:
        entries = history.build_entries(
            self.root,
            self._inventory(
                {
                    "family": "cross-engine",
                    "input_role": "pr15d-archive",
                    "path": "absent.zip",
                    "source_identity": "20261031T005545Z-40a9c26a",
                    "expected_digest": DIGEST,
                }
            ),
        )
        self.assertEqual(entries[0]["status"], history.STATUS_UNAVAILABLE)
        self.assertIsNone(entries[0]["input_digest"])

    def test_t04_unsupported_summary_identity_stays_unverified(self) -> None:
        payload = b'{"decision":"INCONCLUSIVE"}'
        (self.root / "aggregate.json").write_bytes(payload)
        entries = history.build_entries(
            self.root,
            self._inventory(
                {
                    "family": "cross-engine",
                    "input_role": "pr15d-aggregate",
                    "path": "aggregate.json",
                    "source_identity": "pr15d-corrected",
                    "expected_digest": _sha(payload),
                }
            ),
        )
        self.assertEqual(entries[0]["status"], history.STATUS_UNVERIFIED)
        self.assertEqual(entries[0]["reason"], "unsupported-source-identity")
        self.assertEqual(entries[0]["normalized_rows"], [])

    def test_t04_authentic_pr15d_rows_with_golden_values(self) -> None:
        from quervant_bench.tests import official_support as support

        aggregate = support.REPO_ROOT / "benchmarks/reports/pr15d/pr15d-qualified.json"
        digest = history.raw_digest(aggregate)
        self.assertEqual(
            digest,
            history.SUPPORTED_SOURCES[("pr15d-aggregate", history.PR15D_AGGREGATE_RUN)],
        )
        entries = history.build_entries(
            support.REPO_ROOT / "benchmarks",
            self._inventory(
                {
                    "family": "cross-engine",
                    "input_role": "pr15d-aggregate",
                    "path": "reports/pr15d/pr15d-qualified.json",
                    "source_identity": history.PR15D_AGGREGATE_RUN,
                    "expected_digest": digest,
                }
            ),
        )
        entry = entries[0]
        self.assertEqual(entry["status"], history.STATUS_FOUND)
        self.assertEqual(entry["reason"], "authenticated-as-reported-summary")
        rows = entry["normalized_rows"]
        self.assertEqual(len(rows), 32)
        effects = {
            (row["lane_id"], row["treatment"]): row for row in rows
        }
        tantivy = effects[("pr15d_v1/10000/absent/k10", "tantivy")]
        lucene = effects[("pr15d_v1/10000/absent/k10", "lucene")]
        self.assertEqual((tantivy["ratio"], tantivy["gain_percent"]), ("0.045566", "95.4434"))
        self.assertEqual((lucene["ratio"], lucene["gain_percent"]), ("1.068173", "-6.8173"))
        self.assertEqual(tantivy["evidence_level"], "AS_REPORTED")
        self.assertEqual(tantivy["method_id"], "historical-three-trial-python-round6-v1")
        self.assertEqual(tantivy["run_id"], history.PR15D_AGGREGATE_RUN)
        self.assertEqual(tantivy["source_commit"], history.PR15D_AGGREGATE_SOURCE)
        self.assertIsNone(tantivy["host_environment"])
        self.assertTrue(tantivy["host_identity"].startswith("sha256:"))
        self.assertEqual(tantivy["input_digest"], digest)
        self.assertEqual({row["regime"] for row in rows}, {"warm"})
        self.assertEqual(len({(row["lane_id"], row["treatment"]) for row in rows}), 32)

    def test_t04_pr15d_negative_cases_are_typed(self) -> None:
        import copy
        import json

        from quervant_bench.tests import official_support as support

        document = history._parse(
            (support.REPO_ROOT / "benchmarks/reports/pr15d/pr15d-qualified.json").read_bytes(),
            "aggregate",
            decimals=True,
        )
        digest = history.SUPPORTED_SOURCES[("pr15d-aggregate", history.PR15D_AGGREGATE_RUN)]
        cases = [
            ("schema", {"schema": "pr15d-aggregate-v2"}),
            ("run_id", {"run_id": "20261030T220025Z-c9e982f"}),
            ("source_sha", {"source_sha": "0" * 40}),
            ("status", {"status": "UNQUALIFIED"}),
            ("trials", {"trials": 2}),
        ]
        for field, override in cases:
            with self.subTest(field=field):
                broken = copy.deepcopy(document)
                broken.update(override)
                with self.assertRaises(BenchError):
                    history.pr15d_aggregate_rows(broken, input_digest=digest)
        broken = copy.deepcopy(document)
        broken["latency"] = broken["latency"][:-1]
        with self.assertRaises(BenchError):
            history.pr15d_aggregate_rows(broken, input_digest=digest)
        broken = copy.deepcopy(document)
        broken["latency"][0] = dict(broken["latency"][0], class_="absent")
        broken["latency"][0].pop("class")
        with self.assertRaises(BenchError):
            history.pr15d_aggregate_rows(broken, input_digest=digest)
        broken = copy.deepcopy(document)
        broken["latency"][0]["comparisons"]["lucene"]["engine_over_quervant_ratio"] = "NaN"
        with self.assertRaises(BenchError):
            history.pr15d_aggregate_rows(broken, input_digest=digest)
        # A summary row can never be relabelled as recomputed.
        rows = history.pr15d_aggregate_rows(
            history._parse(
                (support.REPO_ROOT / "benchmarks/reports/pr15d/pr15d-qualified.json").read_bytes(),
                "aggregate",
                decimals=True,
            ),
            input_digest=digest,
        )
        relabelled = dict(rows[0], evidence_level="RECOMPUTED")
        with self.assertRaises(BenchError):
            history.validate_entry(
                {
                    "input_role": "pr15d-aggregate",
                    "source_identity": history.PR15D_AGGREGATE_RUN,
                    "input_digest": digest,
                    "status": history.STATUS_FOUND,
                    "reason": "authenticated-as-reported-summary",
                    "normalized_rows": [relabelled],
                }
            )

    def test_t04_unverified_without_independent_digest(self) -> None:
        (self.root / "micro.json").write_bytes(b"micro")
        entries = history.build_entries(
            self.root,
            self._inventory(
                {
                    "family": "retained-key",
                    "input_role": "retained-micro",
                    "path": "micro.json",
                    "source_identity": "micro-05",
                    "expected_digest": None,
                }
            ),
        )
        self.assertEqual(entries[0]["status"], history.STATUS_INVALID)

    def test_unsafe_paths_and_symlinks_are_invalid(self) -> None:
        (self.root / "real.json").write_bytes(b"x")
        os.symlink(self.root / "real.json", self.root / "link.json")
        entries = history.build_entries(
            self.root,
            self._inventory(
                {
                    "family": "retained-key",
                    "input_role": "retained-micro",
                    "path": "../escape.json",
                    "source_identity": "escape",
                    "expected_digest": None,
                },
                {
                    "family": "retained-key",
                    "input_role": "retained-micro",
                    "path": "link.json",
                    "source_identity": "symlink",
                    "expected_digest": None,
                },
                {
                    "family": "retained-key",
                    "input_role": "retained-micro",
                    "path": ".",
                    "source_identity": "directory",
                    "expected_digest": None,
                },
            ),
        )
        self.assertEqual(
            [entry["status"] for entry in entries],
            [history.STATUS_INVALID] * 3,
            [entry["reason"] for entry in entries],
        )
        self.assertTrue(entries[0]["reason"].startswith("unsafe-path"))
        self.assertTrue(entries[1]["reason"].startswith("unsafe-input:"))
        self.assertTrue(entries[2]["reason"].startswith("unsafe-path"))


class RetainedAnalysisAdapterTests(unittest.TestCase):
    """Schema-level projection test; this is not an authenticated historical positive."""

    def _document(self):
        lanes = {}
        coordinates = (
            (n, class_name, k)
            for n in (10000, 100000)
            for class_name in ("absent", "rare", "medium", "common")
            for k in (1, 10, 32, 64, 100, 128, 256, 512, 1024)
        )
        for n, class_name, k in coordinates:
            lane_id = f"pr15d_v1/{n}/{class_name}/k{k}"
            campaigns = {}
            for campaign in RETAINED_CAMPAIGN_ORACLE:
                record = {
                    "retained": [1, 2, 3, 4],
                    "excluded": [
                        {"block": block, "within": {"A": 1.0, "L": 1.0, "P": 1.0, "H": 1.6},
                         "arms": ["H"]}
                        for block in range(5, 13)
                    ],
                    "cap": 1.25 if n == 100_000 and class_name in ("medium", "common") else 1.5,
                    "retained_count": 4,
                    "latency": {"A": 100, "L": 80, "P": 60, "H": 30},
                    "raw_latency": {"A": 100, "L": 80, "P": 60, "H": 30},
                    "raw_ratio": {"L": 0.8, "P": 0.6, "H": 0.3},
                    "filter_sensitive": False,
                }
                for ratio_field, ci_field, _baseline, _treatment, ratio, _gain in PAIR_ORACLE:
                    record[ratio_field] = float(ratio)
                    record[ci_field] = {"low": float(ratio), "high": float(ratio), "seed": 11}
                campaigns[campaign] = record
            lanes[lane_id] = {
                "id": lane_id, "n": n, "class": class_name, "k": k, "campaigns": campaigns,
            }
        return {
            "schema": "pr15i-d3c-t7-analysis-v1",
            "protocol_sha256": "c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c",
            "series": list(RETAINED_CAMPAIGN_ORACLE),
            "lanes": lanes,
        }

    def test_projection_yields_864_as_reported_rows(self) -> None:
        rows = history.retained_analysis_rows(
            history._parse(
                __import__("json").dumps(self._document()).encode(), "a", decimals=True
            ),
            input_digest="sha256:" + "5" * 64,
        )
        self.assertEqual(len(rows), 864)
        first = rows[0]
        self.assertEqual(first["evidence_level"], "AS_REPORTED")
        self.assertEqual(first["method_id"], "retained-key-paired-slot-effects-v1")
        self.assertEqual(first["source_commit"], history.RETAINED_EXPERIMENT)
        self.assertIsNone(first["host_identity"])
        self.assertEqual(first["run_id"], history.RETAINED_CAMPAIGNS[0])
        self.assertEqual(first["uncertainty"]["method"], "paired-slot-bootstrap-v1")
        self.assertEqual(len({(row["lane_id"], row["campaign_id"], row["baseline"], row["treatment"]) for row in rows}), 864)

    def test_retained_negative_cases_are_typed(self) -> None:
        digest = "sha256:" + "5" * 64
        for mutate in (
            lambda doc: doc.update({"schema": "other"}),
            lambda doc: doc.update({"series": list(reversed(history.RETAINED_CAMPAIGNS))}),
            lambda doc: doc["lanes"].pop(sorted(doc["lanes"])[0]),
            lambda doc: doc["lanes"][sorted(doc["lanes"])[0]]["campaigns"].pop(
                history.RETAINED_CAMPAIGNS[0]
            ),
            lambda doc: doc["lanes"][sorted(doc["lanes"])[0]]["campaigns"][
                history.RETAINED_CAMPAIGNS[0]
            ].pop("CI_L_A"),
            lambda doc: doc["lanes"][sorted(doc["lanes"])[0]]["campaigns"][
                history.RETAINED_CAMPAIGNS[0]
            ].update({"retained": [1, 2]}),
        ):
            with self.subTest(mutate=mutate):
                document = self._document()
                mutate(document)
                with self.assertRaises(BenchError):
                    history.retained_analysis_rows(
                        history._parse(
                            __import__("json").dumps(document).encode(), "a", decimals=True
                        ),
                        input_digest=digest,
                    )


class InventoryBoundsTests(unittest.TestCase):
    def test_candidate_budget_and_provider_absence(self) -> None:
        candidates = [
            {
                "family": "retained-key",
                "input_role": "retained-micro",
                "path": f"micro-{index}.json",
                "source_identity": "micro-05",
                "expected_digest": None,
            }
            for index in range(history.MAX_CANDIDATES + 1)
        ]
        with self.assertRaises(BenchError) as raised:
            history.validate_inventory(
                {"kind": history.INVENTORY_KIND, "schema_version": 1, "candidates": candidates}
            )
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)
        missing = Path(tempfile.mkdtemp()) / "absent-root"
        entries = history.build_entries(
            missing,
            {
                "kind": history.INVENTORY_KIND,
                "schema_version": 1,
                "candidates": [
                    {
                        "family": "cross-engine",
                        "input_role": "pr15d-aggregate",
                        "path": "x.json",
                        "source_identity": history.PR15D_AGGREGATE_RUN,
                        "expected_digest": None,
                    }
                ],
            },
        )
        self.assertEqual(entries[0]["status"], history.STATUS_UNAVAILABLE)

    def test_wrong_typed_fields_are_schema_errors(self) -> None:
        for candidate in (
            {"family": ["cross-engine"], "input_role": "pr15d-aggregate", "path": "x", "source_identity": "y", "expected_digest": None},
            {"family": "cross-engine", "input_role": {"role": "pr15d-aggregate"}, "path": "x", "source_identity": "y", "expected_digest": None},
            {"family": "cross-engine", "input_role": "pr15d-aggregate", "path": 1, "source_identity": "y", "expected_digest": None},
            {"family": "cross-engine", "input_role": "pr15d-aggregate", "path": "x", "source_identity": True, "expected_digest": None},
        ):
            with self.subTest(candidate=candidate):
                with self.assertRaises(BenchError) as raised:
                    history.validate_inventory(
                        {"kind": history.INVENTORY_KIND, "schema_version": 1, "candidates": [candidate]}
                    )
                self.assertIn(raised.exception.code, (BM_SCHEMA_INVALID, BM_IDENTITY_INVALID))


class SafeObservationFaultTests(unittest.TestCase):
    """S1-A05/A07/A11: real descriptor, link, parsing and budget faults."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _cross_candidate(self, path: str, digest: str | None = None):
        return {
            "family": "cross-engine",
            "input_role": "pr15d-aggregate",
            "path": path,
            "source_identity": history.PR15D_AGGREGATE_RUN,
            "expected_digest": digest
            if digest is not None
            else history.SUPPORTED_SOURCES[("pr15d-aggregate", history.PR15D_AGGREGATE_RUN)],
        }

    def _status(self, candidate):
        return history.classify_candidate(self.root, candidate)

    def test_hardlink_fifo_parent_symlink_and_dangling_provider(self) -> None:
        payload = b"{}"
        anchor = history.SUPPORTED_SOURCES[("pr15d-aggregate", history.PR15D_AGGREGATE_RUN)]
        (self.root / "real.json").write_bytes(payload)
        os.link(self.root / "real.json", self.root / "hard.json")
        os.mkfifo(self.root / "pipe.json")
        os.symlink(self.root / "real.json", self.root / "leaf.json")
        (self.root / "nested").mkdir()
        (self.root / "nested" / "real.json").write_bytes(payload)
        os.symlink(self.root / "nested", self.root / "parent-link")
        dangling = Path(self.temporary.name) / "dangling"
        os.symlink(self.root / "missing-dir", dangling)
        expectations = {
            ("hard.json", self.root): history.STATUS_INVALID,
            ("pipe.json", self.root): history.STATUS_INVALID,
            ("leaf.json", self.root): history.STATUS_INVALID,
            ("parent-link/real.json", self.root): history.STATUS_INVALID,
        }
        for (path, provider), expected in expectations.items():
            with self.subTest(path=path):
                candidate = self._cross_candidate(path, anchor)
                entry = history.classify_candidate(provider, candidate)
                self.assertEqual(entry["status"], expected, entry["reason"])
        entry = history.classify_candidate(dangling, self._cross_candidate("real.json", anchor))
        self.assertEqual(entry["status"], history.STATUS_INVALID)
        self.assertIn("BM_UNSAFE_INPUT", entry["reason"])

    def test_replacement_with_identical_bytes_is_rejected(self) -> None:
        from quervant_bench.tests import official_support as support

        payload = (
            support.REPO_ROOT / "benchmarks/reports/pr15d/pr15d-qualified.json"
        ).read_bytes()
        target = self.root / "real.json"
        target.write_bytes(payload)
        original = history._observe_file

        calls = {"count": 0}

        def replace_after_first(root, relative, *, max_bytes, capture=False):
            result = original(root, relative, max_bytes=max_bytes, capture=capture)
            calls["count"] += 1
            if calls["count"] == 1:
                target.unlink()
                target.write_bytes(payload)
            return result

        anchor = history.SUPPORTED_SOURCES[("pr15d-aggregate", history.PR15D_AGGREGATE_RUN)]
        original_observe = history._observe_file
        history._observe_file = replace_after_first
        try:
            entry = history.classify_candidate(
                self.root, self._cross_candidate("real.json", anchor)
            )
        finally:
            history._observe_file = original_observe
        self.assertEqual(entry["status"], history.STATUS_INVALID)
        self.assertIn("changed-during-read", entry["reason"])

    def test_strict_parsing_and_budgets(self) -> None:
        cases = {
            b'{"a":1,"a":2}': "duplicate",
            b'\xef\xbb\xbf{"a":1}': "BOM",
            b'{"a":\xff}': "UTF-8",
            b'{"a":NaN}': "non-finite",
            b'{"a":1e400}': "out-of-range",
            b'[1,2,3]': "object root",
        }
        for payload, label in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(BenchError):
                    history._parse(payload, "doc", decimals=False)
        deep = b'{"a":' * 65 + b'0' + b'}' * 65
        with self.assertRaises(BenchError):
            history._parse(deep, "doc", decimals=False)
        wide = ('{"a":[' + ",".join("0" for _ in range(100_001)) + ']}').encode()
        with self.assertRaises(BenchError):
            history._parse(wide, "doc", decimals=False)
        ok = b'{"a":1}'
        (self.root / "ok.json").write_bytes(ok)
        with self.assertRaises(BenchError):
            history._observe_file(self.root, "ok.json", max_bytes=len(ok) - 1)
        self.assertEqual(
            history._observe_file(self.root, "ok.json", max_bytes=len(ok))[0].digest[:7], "sha256:"
        )
        exact = b'{"ratio":0.123456789012345678901234567890123456789,"cold":1}'
        document = history._parse(exact, "doc", decimals=True)
        self.assertEqual(str(document["ratio"]), "0.123456789012345678901234567890123456789")
        self.assertEqual(document["cold"], 1)

    def test_disclosure_reader_round_trip_and_faults(self) -> None:
        from quervant_bench.official import relative_effects as effects

        baseline = "33333333-3333-4333-8333-333333333333"
        digest = "sha256:" + "6" * 64
        lanes = [
            {
                "lane_id": lane,
                "comparisons": [
                    {"comparator": "lucene", "ratio": "1.05"},
                    {"comparator": "tantivy", "ratio": "0.95"},
                ],
            }
            for lane in effects.lane_ids(effects.STUDY_CROSS_ENGINE)
        ]
        rows = effects.cross_engine_effect_rows(
            study_id=effects.STUDY_CROSS_ENGINE,
            run_id="11111111-1111-4111-8111-111111111111",
            analysis_lanes=lanes,
            input_digest=digest,
            source_commit="a" * 40,
            host_environment="wsl2",
            host_identity="sha256:" + "4" * 64,
        )
        report = history.report_payload(
            baseline_id=baseline,
            study_id=effects.STUDY_CROSS_ENGINE,
            source_commit="a" * 40,
            current_raw_digest=digest,
            entries=[
                {
                    "input_role": "pr15d-aggregate",
                    "source_identity": history.PR15D_AGGREGATE_RUN,
                    "input_digest": None,
                    "status": history.STATUS_UNAVAILABLE,
                    "reason": "not-found",
                    "normalized_rows": [],
                }
            ],
        )
        disclosure = effects.disclosure_payload(
            baseline_id=baseline,
            study_id=effects.STUDY_CROSS_ENGINE,
            source_commit="a" * 40,
            current_raw_digest=digest,
            rows=rows,
        )
        (self.root / "history-report.json").write_text(json.dumps(report))
        (self.root / "relative-effects.json").write_text(json.dumps(disclosure))
        before = {
            name: (self.root / name).read_bytes()
            for name in ("history-report.json", "relative-effects.json")
        }
        observed = history._open_baseline_disclosure_documents(
            operation_root=self.root,
            baseline_id=baseline,
            study_id=effects.STUDY_CROSS_ENGINE,
            source_commit="a" * 40,
            current_raw_digest=digest,
        )
        self.assertEqual(observed["statuses"], [history.STATUS_UNAVAILABLE])
        for name, content in before.items():
            self.assertEqual((self.root / name).read_bytes(), content)

        duplicate = self.root / "relative-effects.json"
        duplicate.write_text('{"kind":"a","kind":"b"}')
        with self.assertRaises(BenchError):
            history._open_baseline_disclosure_documents(
                operation_root=self.root,
                baseline_id=baseline,
                study_id=effects.STUDY_CROSS_ENGINE,
                source_commit="a" * 40,
                current_raw_digest=digest,
            )
        duplicate.write_bytes(before["relative-effects.json"])
        hard = self.root / "hard-report.json"
        os.link(self.root / "history-report.json", hard)
        os.replace(hard, self.root / "history-report.json")
        with self.assertRaises(BenchError):
            history._open_baseline_disclosure_documents(
                operation_root=self.root,
                baseline_id=baseline,
                study_id=effects.STUDY_CROSS_ENGINE,
                source_commit="a" * 40,
                current_raw_digest=digest,
            )


class RoleAdapterTests(unittest.TestCase):
    """S1-A10: fixed dispatch for the metadata roles and fake-FOUND rejection."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_t6_receipt_adapter_valid_and_malformed(self) -> None:
        receipt = {
            "schema": "pr15i-d3c-freeze-v1",
            "protocol_sha256": history.RETAINED_PROTOCOL,
            "control_name": history.RETAINED_CONTROL,
            "campaign_names": list(history.RETAINED_CAMPAIGNS),
            "t6_commit": history.RETAINED_T6,
            "tooling_manifest_sha256": history.T6_TOOLING_MANIFEST_RAW,
            "protected_files": {"benchmarks/pr15i_d3_c/run.py": "a" * 64},
            "receipt_origin": "historical",
        }
        digest = history.SUPPORTED_SOURCES[("retained-t6-receipt", history.RETAINED_T6)]
        self.assertEqual(digest, history.SUPPORTED_SOURCES[("retained-t6-receipt", history.RETAINED_T6)])
        history._t6_known_fields(receipt)
        for field, value in (
            ("schema", "other"),
            ("protocol_sha256", "0" * 64),
            ("t6_commit", "0" * 40),
            ("control_name", "other"),
            ("campaign_names", list(reversed(history.RETAINED_CAMPAIGNS))),
            ("tooling_manifest_sha256", "0" * 64),
            ("protected_files", {"../escape": "a" * 64}),
            ("protected_files", {"a//b": "a" * 64}),
            ("t6_commit", 44),
        ):
            with self.subTest(field=field):
                broken = dict(receipt)
                broken[field] = value
                with self.assertRaises(BenchError):
                    history._t6_known_fields(broken)

    def test_policy_adapter_valid_and_malformed(self) -> None:
        rows = [
            {
                "k": k,
                "selected_strategy": "LINEAR_BASE",
                "decision_status": "LINEAR_BASE",
                "P_status": "INCONCLUSIVE",
                "H_status": "INCONCLUSIVE",
                "P_reasons": [],
                "H_reasons": [],
                "filter_sensitive": False,
                "H_memory": None,
            }
            for k in history.RETAINED_K_VALUES
        ]
        document = {
            "schema": "pr15i-d3c-t7f2-policy-v1",
            "protocol_sha256": history.RETAINED_PROTOCOL,
            "status": history.POLICY_STATUS,
            "rows": rows,
        }
        history._read_policy(document)
        for mutate in (
            lambda doc: doc.update({"schema": "other"}),
            lambda doc: doc.update({"status": "SELECTED"}),
            lambda doc: doc.update({"rows": rows[:-1]}),
            lambda doc: doc["rows"][0].update({"k": 99}),
            lambda doc: doc["rows"][0].update({"selected_strategy": "B"}),
            lambda doc: doc["rows"][0].update({"filter_sensitive": 1}),
            lambda doc: doc["rows"][0].update({"H_memory": -1}),
        ):
            with self.subTest(mutate=mutate):
                broken = {
                    "schema": document["schema"],
                    "protocol_sha256": document["protocol_sha256"],
                    "status": document["status"],
                    "rows": [dict(row) for row in rows],
                }
                mutate(broken)
                with self.assertRaises(BenchError):
                    history._read_policy(broken)

    def test_micro_rejects_malformed_table(self) -> None:
        with self.assertRaises(BenchError):
            history._read_micro(b'{"schema":"pr15i-d3c-micro-v1"}', "micro")

    def test_fake_found_and_foreign_rows_are_rejected(self) -> None:
        digest = "sha256:" + "7" * 64
        with self.assertRaises(BenchError):
            history.validate_entry(
                {
                    "input_role": "pr15d-aggregate",
                    "source_identity": "unknown-run",
                    "input_digest": digest,
                    "status": history.STATUS_FOUND,
                    "reason": "authenticated",
                    "normalized_rows": [],
                }
            )
        with self.assertRaises(BenchError):
            history.validate_entry(
                {
                    "input_role": "retained-policy",
                    "source_identity": history.RETAINED_T6,
                    "input_digest": digest,
                    "status": history.STATUS_UNVERIFIED,
                    "reason": "x",
                    "normalized_rows": [
                        {
                            "study_id": "retained-key-topk-real-v1",
                            "run_id": "d3c-v3r3-strategies-01",
                            "campaign_id": "d3c-v3r3-strategies-01",
                            "lane_id": "pr15d_v1/10000/absent/k1",
                            "metric": "latency",
                            "unit": "ns",
                            "regime": "warm",
                            "direction": "lower",
                            "baseline": "A",
                            "treatment": "L",
                            "method_id": "retained-key-paired-slot-effects-v1",
                            "ratio": "0.8",
                            "gain_percent": "20",
                            "uncertainty": {
                                "low": "0.7",
                                "high": "0.9",
                                "method": "paired-slot-bootstrap-v1",
                                "seed": 1,
                            },
                            "decision": "DESCRIPTIVE_EFFECT_ONLY",
                            "evidence_level": "AS_REPORTED",
                            "source_commit": "a" * 40,
                            "host_environment": None,
                            "host_identity": None,
                            "input_digest": digest,
                        }
                    ],
                }
            )


class DisclosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _write(self, entries=None) -> None:
        from quervant_bench.official import relative_effects as effects

        lanes = [
            {
                "lane_id": lane,
                "comparisons": [
                    {"comparator": "lucene", "ratio": "1.05"},
                    {"comparator": "tantivy", "ratio": "0.95"},
                ],
            }
            for lane in effects.lane_ids(effects.STUDY_CROSS_ENGINE)
        ]
        rows = effects.cross_engine_effect_rows(
            study_id=effects.STUDY_CROSS_ENGINE,
            run_id="11111111-1111-4111-8111-111111111111",
            analysis_lanes=lanes,
            input_digest=DIGEST,
            source_commit="a" * 40,
            host_environment="wsl2",
            host_identity="sha256:" + "4" * 64,
        )
        report = history.report_payload(
            baseline_id=BASELINE,
            study_id=effects.STUDY_CROSS_ENGINE,
            source_commit="a" * 40,
            current_raw_digest=DIGEST,
            entries=entries
            or [
                {
                    "input_role": "pr15d-aggregate",
                    "source_identity": history.PR15D_AGGREGATE_RUN,
                    "input_digest": None,
                    "status": history.STATUS_UNAVAILABLE,
                    "reason": "not-found",
                    "normalized_rows": [],
                }
            ],
        )
        disclosure = effects.disclosure_payload(
            baseline_id=BASELINE,
            study_id=effects.STUDY_CROSS_ENGINE,
            source_commit="a" * 40,
            current_raw_digest=DIGEST,
            rows=rows,
        )
        (self.root / "history-report.json").write_text(json.dumps(report))
        (self.root / "relative-effects.json").write_text(json.dumps(disclosure))

    def test_open_returns_both_bound_digests(self) -> None:
        self._write()
        observed = history._open_baseline_disclosure_documents(
            operation_root=self.root,
            baseline_id=BASELINE,
            study_id="cross-engine-keyword-real-v1",
            source_commit="a" * 40,
            current_raw_digest=DIGEST,
        )
        self.assertEqual(observed["statuses"], [history.STATUS_UNAVAILABLE])
        self.assertTrue(observed["history_report_digest"].startswith("sha256:"))
        self.assertNotEqual(observed["history_report_digest"], observed["relative_effects_digest"])

    def test_wrong_identity_binding_is_rejected(self) -> None:
        self._write()
        for field, value in (
            ("baseline_id", "44444444-4444-4444-8444-444444444444"),
            ("study_id", "retained-key-topk-real-v1"),
            ("source_commit", "b" * 40),
            ("current_raw_digest", "sha256:" + "9" * 64),
        ):
            with self.subTest(field=field):
                kwargs = {
                    "operation_root": self.root,
                    "baseline_id": BASELINE,
                    "study_id": "cross-engine-keyword-real-v1",
                    "source_commit": "a" * 40,
                    "current_raw_digest": DIGEST,
                }
                kwargs[field] = value
                with self.assertRaises(BenchError) as raised:
                    history._open_baseline_disclosure_documents(**kwargs)
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_missing_disclosure_is_unavailable(self) -> None:
        self._write()
        (self.root / "relative-effects.json").unlink()
        with self.assertRaises(BenchError) as raised:
            history._open_baseline_disclosure_documents(
                operation_root=self.root,
                baseline_id=BASELINE,
                study_id="cross-engine-keyword-real-v1",
                source_commit="a" * 40,
                current_raw_digest=DIGEST,
            )
        self.assertEqual(raised.exception.code, "BM_EVIDENCE_UNAVAILABLE")

    def test_symlinked_disclosure_is_rejected(self) -> None:
        self._write()
        target = self.root / "history-report.real.json"
        (self.root / "history-report.json").rename(target)
        os.symlink(target, self.root / "history-report.json")
        with self.assertRaises(BenchError):
            history._open_baseline_disclosure_documents(
                operation_root=self.root,
                baseline_id=BASELINE,
                study_id=STUDY,
                source_commit="a" * 40,
                current_raw_digest=DIGEST,
            )

    def test_found_entry_without_digest_is_rejected(self) -> None:
        with self.assertRaises(BenchError) as raised:
            history.validate_entry(
                {
                    "input_role": "retained-micro",
                    "source_identity": "micro-05",
                    "input_digest": None,
                    "status": history.STATUS_FOUND,
                    "reason": "authenticated",
                    "normalized_rows": [],
                }
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_unusable_input_cannot_contribute_rows(self) -> None:
        with self.assertRaises(BenchError):
            history.validate_entry(
                {
                    "input_role": "retained-micro",
                    "source_identity": "micro-05",
                    "input_digest": DIGEST,
                    "status": history.STATUS_INVALID,
                    "reason": "digest-mismatch",
                    "normalized_rows": [{"study_id": "s"}],
                }
            )


class Step1FixupTests(unittest.TestCase):
    """S1F-T07..T24: Step 1 fixup reader corrections."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _aggregate(self) -> Path:
        from quervant_bench.tests import official_support as support

        return support.REPO_ROOT / "benchmarks/reports/pr15d/pr15d-qualified.json"

    def test_s1f_t07_token_parsing(self) -> None:
        for decimals in (False, True):
            with self.subTest(view="exact" if decimals else "ordinary"):
                parsed = history._parse(b'{"a":1.25,"b":1e-7}', "document", decimals=decimals)
                self.assertEqual(parsed["a"], Decimal("1.25") if decimals else 1.25)
                self.assertEqual(parsed["b"], Decimal("1e-7") if decimals else 1e-7)
                self.assertIs(type(parsed["a"]), Decimal if decimals else float)
        exact = history._parse(
            b'{"ratio":0.123456789012345678901234567890123456789}',
            "document", decimals=True,
        )
        self.assertEqual(effects_gain(exact["ratio"]), "87.6543210987654321098765432109876543211")
        malformed = {
            "nan": b'{"a":NaN}', "infinity": b'{"a":Infinity}',
            "negative-infinity": b'{"a":-Infinity}', "overflow": b'{"a":1e400}',
            "duplicate": b'{"a":1,"a":2}', "bom": b'\xef\xbb\xbf{"a":1}',
            "utf8": b'{"a":\xff}', "array-root": b'[1]', "null-root": b'null',
        }
        for label, payload in malformed.items():
            for decimals in (False, True):
                with self.subTest(case=label, decimals=decimals):
                    with self.assertRaises(BenchError) as raised:
                        history._parse(payload, "document", decimals=decimals)
                    self.assertEqual(raised.exception.code, "BM_SCHEMA_INVALID")
                    self.assertEqual(raised.exception.field_path, "document")
        # Real cold records go through the complete source adapter as Decimal leaves.
        document = history._parse(self._aggregate().read_bytes(), "aggregate", decimals=True)
        cold = [lane for lane in document["latency"] if lane["regime"] == "process_cold"]
        self.assertEqual(len(cold), 16)
        rows = history.pr15d_aggregate_rows(document, input_digest=_sha(self._aggregate().read_bytes()))
        self.assertEqual(len(rows), 32)
        self.assertTrue(all(row["regime"] == "warm" for row in rows))

    def test_s1f_t08_exact_budgets(self) -> None:
        for decimals in (False, True):
            for kind in ("integer", "fractional"):
                for trailing_key in (False, True):
                    for length in (1024, 1025):
                        token = b"1" * length if kind == "integer" else b"0." + b"1" * (length - 2)
                        payload = b'{"value":' + token + (b',"later":0}' if trailing_key else b'}')
                        with self.subTest(kind=kind, length=length, trailing_key=trailing_key, decimals=decimals):
                            if length == 1024:
                                value = history._parse(payload, "document", decimals=decimals)["value"]
                                self.assertGreater(value, 0)
                            else:
                                with self.assertRaises(BenchError) as raised:
                                    history._parse(payload, "document", decimals=decimals)
                                self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")
        for depth in (64, 65):
            with self.subTest(depth=depth):
                payload = b'{"a":' * depth + b'0' + b'}' * depth
                if depth == 64:
                    self.assertIsInstance(history._parse(payload, "document", decimals=False), dict)
                else:
                    with self.assertRaises(BenchError) as raised:
                        history._parse(payload, "document", decimals=False)
                    self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")
        # Root object + array + its scalar elements are the counted nodes.
        for nodes in (100000, 100001):
            with self.subTest(nodes=nodes):
                payload = ('{"a":[' + ','.join('0' for _ in range(nodes - 2)) + ']}').encode()
                if nodes == 100000:
                    self.assertEqual(len(history._parse(payload, "document", decimals=False)["a"]), nodes - 2)
                else:
                    with self.assertRaises(BenchError) as raised:
                        history._parse(payload, "document", decimals=False)
                    self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")
        many_small = ('{"a":[' + ','.join('1' for _ in range(600)) + ']}').encode()
        self.assertEqual(len(history._parse(many_small, "document", decimals=False)["a"]), 600)
        self.assertEqual(history._parse(b'{"a":1}' + b' ' * 1100, "document", decimals=True), {"a": 1})
        payload = b"0123456789"
        (self.root / "small.bin").write_bytes(payload)
        observed, captured = history._observe_file(self.root, "small.bin", max_bytes=10, capture=True)
        self.assertEqual((observed.byte_length, captured, observed.digest), (10, payload, _sha(payload)))
        with self.assertRaises(BenchError) as raised:
            history._observe_file(self.root, "small.bin", max_bytes=9)
        self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")
        self.assertEqual(raised.exception.field_path, "path")

    def test_s1f_t09_absence_vs_unsafe_ancestry(self) -> None:
        payload = self._aggregate().read_bytes()
        actual = self.root / "actual"
        actual.mkdir()
        (actual / "aggregate.json").write_bytes(payload)
        candidate = {"family": "cross-engine", "input_role": "pr15d-aggregate",
                     "path": "aggregate.json", "source_identity": history.PR15D_AGGREGATE_RUN,
                     "expected_digest": _sha(payload)}
        self.assertEqual(history.classify_candidate(actual, candidate)["status"], "FOUND")
        (self.root / "leaf.json").symlink_to(actual / "aggregate.json")
        (self.root / "parent").symlink_to(actual, target_is_directory=True)
        (self.root / "provider").symlink_to(actual, target_is_directory=True)
        (self.root / "dangling-parent").symlink_to(self.root / "gone", target_is_directory=True)
        (self.root / "dangling-provider").symlink_to(self.root / "gone", target_is_directory=True)
        cases = (
            ("missing-provider", self.root / "absent", "aggregate.json", "UNAVAILABLE"),
            ("missing-member", actual, "missing.json", "UNAVAILABLE"),
            ("leaf", self.root, "leaf.json", "INVALID"),
            ("parent", self.root, "parent/aggregate.json", "INVALID"),
            ("provider", self.root / "provider", "aggregate.json", "INVALID"),
            ("dangling-parent", self.root, "dangling-parent/aggregate.json", "INVALID"),
            ("dangling-provider", self.root / "dangling-provider", "aggregate.json", "INVALID"),
            ("linked-parent-missing-leaf", self.root, "parent/missing.json", "INVALID"),
        )
        catalog = history.CATALOG
        for label, provider, member, expected in cases:
            for surface in ("direct", "inventory"):
                with self.subTest(case=label, surface=surface):
                    entry_candidate = dict(candidate, path=member)
                    if surface == "direct":
                        entry = history.classify_candidate(provider, entry_candidate)
                    else:
                        entry = history.build_entries(provider, {
                            "kind": "official-baseline-history-inputs", "schema_version": 1,
                            "candidates": [entry_candidate],
                        })[0]
                    self.assertEqual(entry["status"], expected)
                    self.assertEqual(entry["normalized_rows"], [])
                    if expected == "UNAVAILABLE":
                        self.assertEqual(entry["reason"], "not-found")
                        self.assertIsNone(entry["input_digest"])
                    else:
                        self.assertIn("BM_UNSAFE_INPUT", entry["reason"])
        self.assertEqual((actual / "aggregate.json").read_bytes(), payload)
        self.assertIs(history.CATALOG, catalog)

    def test_s1f_t10_raw_digest_no_follow(self) -> None:
        payload = b"regular owned input"
        (self.root / "regular.bin").write_bytes(payload)
        (self.root / "link.bin").symlink_to(self.root / "regular.bin")
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            for relative in (False, True):
                with self.subTest(relative=relative, kind="regular"):
                    path = Path("regular.bin") if relative else self.root / "regular.bin"
                    self.assertEqual(history.raw_digest(path), _sha(payload))
                with self.subTest(relative=relative, kind="symlink"):
                    path = Path("link.bin") if relative else self.root / "link.bin"
                    with self.assertRaises(BenchError) as raised:
                        history.raw_digest(path)
                    self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")
        finally:
            os.chdir(previous)
        os.link(self.root / "regular.bin", self.root / "hard.bin")
        (self.root / "directory").mkdir()
        os.mkfifo(self.root / "fifo")
        for name in ("hard.bin", "directory", "fifo"):
            with self.subTest(kind=name):
                with self.assertRaises(BenchError) as raised:
                    history.raw_digest(self.root / name)
                self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")

    def test_s1f_t11_operation_bracketed_observations(self) -> None:
        from unittest.mock import patch

        authentic = self._aggregate().read_bytes()
        target = self.root / "aggregate.json"
        candidate = {"family": "cross-engine", "input_role": "pr15d-aggregate",
                     "path": target.name, "source_identity": history.PR15D_AGGREGATE_RUN,
                     "expected_digest": _sha(authentic)}
        for owner in ("_parse", "pr15d_aggregate_rows"):
            for mutation in ("changed-bytes", "new-inode", "disappearance"):
                with self.subTest(owner=owner, mutation=mutation):
                    target.write_bytes(authentic)
                    original = getattr(history, owner)
                    fired = []
                    def mutate_after_owner(*args, **kwargs):
                        result = original(*args, **kwargs)
                        if not fired:
                            fired.append(True)
                            if mutation == "changed-bytes":
                                target.write_bytes(b'{"changed":true}')
                            elif mutation == "new-inode":
                                replacement = self.root / "replacement.json"
                                replacement.write_bytes(authentic)
                                os.replace(replacement, target)
                            else:
                                target.unlink()
                        return result
                    with patch.object(history, owner, mutate_after_owner):
                        entry = history.classify_candidate(self.root, candidate)
                    self.assertEqual(fired, [True])
                    self.assertEqual(entry["status"], "INVALID")
                    self.assertEqual(entry["reason"], "changed-during-read:BM_IDENTITY_INVALID")
                    self.assertEqual(entry["normalized_rows"], [])
        self.assertEqual(self._aggregate().read_bytes(), authentic)

    def test_s1f_t12_io_failure_is_typed(self) -> None:
        from unittest.mock import patch

        (self.root / "io.json").write_bytes(b"{}")
        real_open, real_fstat = history.open_regular_beneath, os.fstat
        modes = ("normal", "read", "fstat-before", "fstat-after", "close", "read-and-close",
                 "typed-and-close", "interrupt", "interrupt-and-close")
        for mode in modes:
            with self.subTest(fault=mode):
                handles, fstat_calls = [], []
                read_error = OSError("injected-read-error")
                close_error = OSError("injected-close-error")
                typed_error = BenchError("BM_IDENTITY_INVALID", "original typed error", field_path="original")
                interrupt = KeyboardInterrupt("injected-interruption")
                class ForwardingHandle:
                    def __init__(self, handle):
                        self.handle = handle
                        self.fd = handle.fileno()
                    def fileno(self):
                        return self.fd
                    def read(self, size):
                        if mode in ("read", "read-and-close"):
                            raise read_error
                        if mode == "typed-and-close":
                            raise typed_error
                        if mode in ("interrupt", "interrupt-and-close"):
                            raise interrupt
                        return self.handle.read(size)
                    def close(self):
                        self.handle.close()
                        if mode in ("close", "read-and-close", "typed-and-close", "interrupt-and-close"):
                            raise close_error
                def forwarding_open(*args, **kwargs):
                    wrapped = ForwardingHandle(real_open(*args, **kwargs))
                    handles.append(wrapped)
                    return wrapped
                def forwarding_fstat(fd):
                    if handles and fd == handles[-1].fd:
                        fstat_calls.append(fd)
                        if (mode == "fstat-before" and len(fstat_calls) == 1) or (mode == "fstat-after" and len(fstat_calls) == 2):
                            raise OSError("injected-fstat-error")
                    return real_fstat(fd)
                with patch.object(history, "open_regular_beneath", forwarding_open), patch.object(os, "fstat", forwarding_fstat):
                    if mode == "normal":
                        observed, captured = history._observe_file(self.root, "io.json", max_bytes=10, capture=True)
                        self.assertEqual((observed.digest, captured), (_sha(b"{}"), b"{}"))
                    elif mode.startswith("interrupt"):
                        with self.assertRaises(KeyboardInterrupt) as raised:
                            history._observe_file(self.root, "io.json", max_bytes=10)
                        self.assertIs(raised.exception, interrupt)
                    else:
                        with self.assertRaises(BenchError) as raised:
                            history._observe_file(self.root, "io.json", max_bytes=10)
                        if mode == "typed-and-close":
                            self.assertIs(raised.exception, typed_error)
                        else:
                            self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")
                            self.assertEqual(raised.exception.field_path, "path")
                            if mode == "read-and-close":
                                self.assertIs(raised.exception.__cause__, read_error)
                self.assertEqual(len(handles), 1)
                self.assertTrue(handles[0].handle.closed)
        # Unsafe replacement retains the path owner's unsafe classification.
        before, _ = history._observe_file(self.root, "io.json", max_bytes=10)
        (self.root / "io.json").rename(self.root / "original.json")
        (self.root / "io.json").symlink_to(self.root / "original.json")
        with self.assertRaises(BenchError) as raised:
            history._require_same_observation(before)
        self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")

    def test_s1f_t13_streaming_budgets(self) -> None:
        from unittest.mock import patch

        payload = b"x" * 100
        target = self.root / "blob.bin"
        target.write_bytes(payload)
        observed, captured = history._observe_file(self.root, target.name, max_bytes=4 * 1024**3)
        self.assertIsNone(captured)
        self.assertEqual((observed.byte_length, observed.digest), (100, _sha(payload)))
        json_bytes = b'{"a":1}'
        (self.root / "small.json").write_bytes(json_bytes)
        _observed, captured = history._observe_file(self.root, "small.json", max_bytes=4 * 1024**2, capture=True)
        self.assertEqual(captured, json_bytes)
        real_open = history.open_regular_beneath
        for growing in (False, True):
            with self.subTest(growing=growing):
                target.write_bytes(b"0123456789")
                requests, totals = [], [0]
                class CountingHandle:
                    def __init__(self, handle):
                        self.handle = handle
                    def fileno(self):
                        return self.handle.fileno()
                    def read(inner, size):
                        self.assertLessEqual(size, min(1048576, 10 - totals[0] + 1))
                        if growing and not requests:
                            with target.open("ab") as writer:
                                writer.write(b"x")
                        requests.append(size)
                        chunk = inner.handle.read(size)
                        totals[0] += len(chunk)
                        return chunk
                    def close(self):
                        self.handle.close()
                with patch.object(history, "open_regular_beneath", lambda *a, **k: CountingHandle(real_open(*a, **k))):
                    if growing:
                        with self.assertRaises(BenchError) as raised:
                            history._observe_file(self.root, target.name, max_bytes=10)
                        self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")
                        self.assertEqual(requests, [11])
                    else:
                        history._observe_file(self.root, target.name, max_bytes=10)
                        self.assertEqual(requests, [11, 1])
        target.write_bytes(payload)
        actual_observe, calls = history._observe_file, []
        def forwarding_observe(root, relative, *, max_bytes, capture=False):
            calls.append((max_bytes, capture))
            return actual_observe(root, relative, max_bytes=max_bytes, capture=capture)
        with patch.object(history, "_observe_file", forwarding_observe):
            self.assertEqual(history.raw_digest(target), _sha(payload))
        self.assertEqual(calls, [(64 * 1024**2, False), (64 * 1024**2, False)])
        for role in ("retained-archive", "pr15d-archive"):
            with self.subTest(role=role):
                record = next(item for item in history.CATALOG if item.role == role)
                calls.clear()
                with patch.object(history, "_observe_file", forwarding_observe):
                    entry = history.classify_candidate(self.root, {
                        "family": "retained-key" if role == "retained-archive" else "cross-engine",
                        "input_role": role, "path": target.name,
                        "source_identity": record.identity, "expected_digest": record.digest,
                    })
                self.assertEqual(calls, [(4 * 1024**3, False)])
                self.assertEqual(entry["status"], "INVALID")
                self.assertEqual(entry["reason"], "digest-mismatch")

    def test_s1f_t14_disclosure_reader_faults(self) -> None:
        from unittest.mock import patch
        from quervant_bench.official import relative_effects as effects

        def write_disclosures(root):
            kwargs = dict(operation_root=root, baseline_id="33333333-3333-4333-8333-333333333333",
                          study_id="cross-engine-keyword-real-v1", source_commit="a" * 40,
                          current_raw_digest="sha256:" + "6" * 64)
            lanes = [{"lane_id": f"pr15d_v1/{n}/{name}/k{k}", "comparisons": [
                {"comparator": "lucene", "ratio": "1.05"}, {"comparator": "tantivy", "ratio": "0.95"}
            ]} for n in (10000, 100000) for name in ("absent", "rare", "medium", "common") for k in (10, 100)]
            rows = effects.cross_engine_effect_rows(
                study_id=kwargs["study_id"], run_id="11111111-1111-4111-8111-111111111111",
                analysis_lanes=lanes, input_digest=kwargs["current_raw_digest"],
                source_commit=kwargs["source_commit"], host_environment="wsl2", host_identity="sha256:" + "4" * 64)
            header = {key: value for key, value in kwargs.items() if key != "operation_root"}
            documents = {"history-report.json": history.report_payload(entries=[], **header),
                         "relative-effects.json": effects.disclosure_payload(rows=rows, **header)}
            payloads = {name: json.dumps(document).encode() for name, document in documents.items()}
            for name, payload in payloads.items():
                (root / name).write_bytes(payload)
            return kwargs, payloads
        kwargs, payloads = write_disclosures(self.root)
        observed = history._open_baseline_disclosure_documents(**kwargs)
        self.assertEqual(set(observed), {"history_report_digest", "relative_effects_digest",
                                        "history_report_path", "relative_effects_path", "statuses"})
        for name, payload in payloads.items():
            self.assertEqual((self.root / name).read_bytes(), payload)
        for name in payloads:
            for fault in ("missing", "symlink", "hardlink", "duplicate-json"):
                with self.subTest(file=name, fault=fault), tempfile.TemporaryDirectory(dir=self.root) as tmp:
                    root = Path(tmp)
                    kwargs, _ = write_disclosures(root)
                    target = root / name
                    if fault == "missing":
                        target.unlink()
                    elif fault == "symlink":
                        target.rename(root / "original.json")
                        target.symlink_to(root / "original.json")
                    elif fault == "hardlink":
                        os.link(target, root / "extra-link.json")
                    else:
                        target.write_bytes(b'{"kind":"a","kind":"b"}')
                    with self.assertRaises(BenchError) as raised:
                        history._open_baseline_disclosure_documents(**kwargs)
                    expected = {"missing": "BM_EVIDENCE_UNAVAILABLE", "symlink": "BM_UNSAFE_INPUT",
                                "hardlink": "BM_UNSAFE_INPUT", "duplicate-json": "BM_SCHEMA_INVALID"}[fault]
                    self.assertEqual(raised.exception.code, expected)
                    if fault == "missing":
                        self.assertEqual(raised.exception.field_path, name)
        for validator_owner, validator_name in ((history, "validate_report"), (effects, "validate_disclosure")):
            for name in payloads:
                for mutation in ("changed-bytes", "new-inode", "disappearance", "unsafe-replacement"):
                    with self.subTest(validator=validator_name, file=name, mutation=mutation), tempfile.TemporaryDirectory(dir=self.root) as tmp:
                        root = Path(tmp)
                        kwargs, original_bytes = write_disclosures(root)
                        target = root / name
                        real_validate, fired = getattr(validator_owner, validator_name), []
                        def mutate_during_second_validation(document):
                            result = real_validate(document)
                            fired.append(True)
                            if mutation == "changed-bytes":
                                target.write_bytes(b'{"changed":true}')
                            elif mutation == "new-inode":
                                replacement = root / "replacement.json"
                                replacement.write_bytes(original_bytes[name])
                                os.replace(replacement, target)
                            elif mutation == "unsafe-replacement":
                                target.rename(root / "original.json")
                                target.symlink_to(root / "original.json")
                            else:
                                target.unlink()
                            return result
                        with patch.object(validator_owner, validator_name, mutate_during_second_validation):
                            with self.assertRaises(BenchError) as raised:
                                history._open_baseline_disclosure_documents(**kwargs)
                        self.assertEqual(fired, [True])
                        self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT" if mutation == "unsafe-replacement" else "BM_IDENTITY_INVALID")
        dangling = self.root / "dangling-provider"
        dangling.symlink_to(self.root / "absent-provider", target_is_directory=True)
        kwargs["operation_root"] = dangling
        with self.assertRaises(BenchError) as raised:
            history._open_baseline_disclosure_documents(**kwargs)
        self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")


    def _role_error(self, code, field, call, *args, **kwargs):
        with self.assertRaises(BenchError) as raised:
            call(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.field_path, field)
        return raised.exception

    def _role_owner_faults(self, namespace, name, invoke, expected_args, expected_members):
        """Negative-only owner injection; no invented authenticated result."""
        for fault in (OSError("injected owner I/O failure"), TypeError("injected owner programming error"),
                      KeyError("injected owner programming error"), MemoryError("injected owner allocation failure"),
                      KeyboardInterrupt("injected owner interruption")):
            with self.subTest(case="owning-reader-fault", owner=name, error=type(fault).__name__):
                observations = []
                with patch.object(namespace, name, side_effect=fault) as called:
                    if isinstance(fault, OSError):
                        error = self._role_error(BM_UNSAFE_INPUT, "path", invoke, observations)
                        self.assertIs(error.__cause__, fault)
                    else:
                        with self.assertRaises(type(fault)) as raised:
                            invoke(observations)
                        self.assertIs(raised.exception, fault)
                self.assertEqual(called.call_count, 1)
                self.assertEqual(called.call_args.args, expected_args)
                self.assertEqual(tuple(item.relative for item in observations), expected_members)
                # The wrapper raised before any result/capability could be
                # returned, while all real preobservations remain unchanged.
                history._recheck(observations)

    def test_s1f_t18_owner_io_and_interruption_boundary(self) -> None:
        from quervant_bench.official import policy_inputs

        source = self.root / "source"
        _document, payload, before = self._role_f1_files(source)
        def invoke(observations):
            observations.append(before)
            return history._read_f1(self.root, "f1.json", payload, before, source, observations)
        self._role_owner_faults(policy_inputs, "_f1_identity", invoke,
                                (self.root / "f1.json", source), ("f1.json",) + F1_PATH_ORACLE)
        self.assertEqual(history.raw_digest(self.root / "f1.json"), before.digest)

    def test_s1f_t19_owner_io_and_interruption_boundary(self) -> None:
        from quervant_bench.tests import official_support as support

        member = "20261031T005545Z-40a9c26a57aa23640904075e77be956ee52718bc.zip"
        with zipfile.ZipFile(self.root / member, "w") as archive:
            archive.writestr("synthetic.txt", b"negative owner seam only")
        before, captured = history._observe_file(self.root, member, max_bytes=4 * 1024 ** 3)
        self.assertIsNone(captured)
        def invoke(observations):
            observations.append(before)
            return history._read_pr15d_archive(self.root, member, before, support.REPO_ROOT, observations)
        self._role_owner_faults(history, "inspect_zip", invoke,
                                (self.root, member, history.ArchiveLimits()),
                                (member, "docs/pr-artifacts/pr-15d/b-evidence-manifest.json"))
        self.assertEqual(history.raw_digest(self.root / member), before.digest)

    def test_s1f_t20_owner_io_and_interruption_boundary(self) -> None:
        from quervant_bench.official import historical

        campaign = "d3c-v3r3-base-aa-01"
        member = f"nested/{campaign}.tar.gz"
        (self.root / "nested").mkdir()
        (self.root / member).write_bytes(b"negative archive seam only")
        sidecar = self.root / (member + ".sha256")
        sidecar.write_bytes(json.dumps({"members": {"member.json": "a" * 64}}).encode())
        before, captured = history._observe_file(self.root, member, max_bytes=4 * 1024 ** 3)
        self.assertIsNone(captured)
        record = history.record_for("retained-archive", campaign)
        def invoke(observations):
            observations.append(before)
            return history._read_archive(self.root, member, record, observations)
        self._role_owner_faults(historical, "audit_retained_key_archive", invoke,
                                (self.root / "nested", campaign),
                                (member, f"{campaign}.tar.gz.sha256"))
        self.assertEqual(history.raw_digest(self.root / member), before.digest)

    def _role_candidate(self, **changes):
        return {
            "family": "cross-engine", "input_role": "pr15d-aggregate",
            "path": "aggregate.json", "source_identity": history.PR15D_RUN,
            "expected_digest": "sha256:c9e8ed722aefc4fef43837a5511c2c88575287497b449f68f82f7ea0c251b257",
        } | changes

    def _role_retained(self):
        # The fixture's numeric JSON is parsed exactly as a real source document;
        # Decimal values are never serialized as quoted strings.
        payload = json.dumps(RetainedAnalysisAdapterTests()._document()).encode()
        return history._parse(payload, "analysis", decimals=True)

    def _role_policy(self, version):
        rows = [
            {
                "k": k, "selected_strategy": "LINEAR_BASE", "decision_status": "LINEAR_BASE",
                "P_status": "INCONCLUSIVE", "H_status": "INCONCLUSIVE",
                "P_reasons": [], "H_reasons": [], "filter_sensitive": False, "H_memory": None,
            }
            for k in (1, 10, 32, 64, 100, 128, 256, 512, 1024)
        ]
        if version == "F1":
            for row in rows:
                row.update(P_gm=[1.0, 2], H_gm=[3.5, 4.5])
        return {
            "schema": "pr15i-d3c-t7-policy-v1" if version == "F1" else "pr15i-d3c-t7f2-policy-v1",
            "protocol_sha256": "c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c",
            "status": "T7_POLICY_DERIVED_PENDING_INDEPENDENT_VERIFICATION", "rows": rows,
        }

    def _role_f1_files(self, root):
        files = {}
        for index, relative in enumerate(F1_PATH_ORACLE):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = f"# synthetic F1 dependency {index}\n".encode()
            path.write_bytes(payload)
            files[path.name] = hashlib.sha256(payload).hexdigest()
        document = {
            "t7_commit": "38a937fdf0b09f1330f26423dabb311399c8a4cf", "files": files,
        }
        payload = json.dumps(document).encode()
        (self.root / "f1.json").write_bytes(payload)
        before, captured = history._observe_file(self.root, "f1.json", max_bytes=4 * 1024 * 1024, capture=True)
        self.assertEqual(captured, payload)
        return document, payload, before

    def _role_disclosures(self, entries):
        from quervant_bench.official import relative_effects as effects

        # This is a synthetic current control, never a current measurement claim.
        lanes = [
            {"lane_id": f"pr15d_v1/{n}/{class_name}/k{k}", "comparisons": [
                {"comparator": "lucene", "ratio": "1.05"},
                {"comparator": "tantivy", "ratio": "0.95"},
            ]}
            for n in (10000, 100000)
            for class_name in ("absent", "rare", "medium", "common")
            for k in (10, 100)
        ]
        kwargs = dict(baseline_id=BASELINE, study_id="cross-engine-keyword-real-v1",
                      source_commit="a" * 40, current_raw_digest="sha256:" + "6" * 64)
        rows = effects.cross_engine_effect_rows(
            study_id=kwargs["study_id"], run_id="11111111-1111-4111-8111-111111111111",
            analysis_lanes=lanes, input_digest=kwargs["current_raw_digest"],
            source_commit=kwargs["source_commit"], host_environment="wsl2",
            host_identity="sha256:" + "4" * 64,
        )
        old_rows = [row for entry in entries for row in entry["normalized_rows"]]
        comparisons = effects.compare_effect_rows(historical_rows=old_rows, current_rows=rows)
        report = history.report_payload(**kwargs, entries=entries)
        disclosure = effects.disclosure_payload(**kwargs, rows=rows, comparisons=comparisons)
        for name, document in (("history-report.json", report), ("relative-effects.json", disclosure)):
            (self.root / name).write_bytes(json.dumps(document, sort_keys=True).encode())
        return report, disclosure, dict(operation_root=self.root, **kwargs)

    def test_s1f_t15_reachable_micro_owner(self) -> None:
        from quervant_bench.official import policy_inputs
        from quervant_bench.tests.test_official_retained_policy import micro_table

        table = micro_table()
        self.assertEqual(len(table["records"]), 900)
        payload = json.dumps(table).encode()
        path = self.root / "micro.json"
        path.write_bytes(payload)
        candidate = self._role_candidate(
            family="retained-key", input_role="retained-micro", path="micro.json",
            source_identity="micro-05", expected_digest=None,
        )
        catalog_before = tuple(history.CATALOG)
        owner = policy_inputs.validate_micro_table
        for label, declared in (("null-declaration", None), ("matching-untrusted-declaration", _sha(payload))):
            with self.subTest(case=label):
                with patch.object(policy_inputs, "validate_micro_table", wraps=owner) as called:
                    entry = history.classify_candidate(self.root, candidate | {"expected_digest": declared})
                self.assertEqual(called.call_count, 1)
                self.assertEqual(called.call_args.args[0], table)
                self.assertEqual((entry["status"], entry["reason"]), ("UNVERIFIED", "no-independent-raw-digest"))
                self.assertEqual(entry["input_digest"], _sha(payload))
                self.assertEqual(entry["normalized_rows"], [])
        for label, content, reason in (
            ("malformed-json", b"{", "BM_SCHEMA_INVALID:micro.json"),
            ("incomplete-grid", json.dumps(dict(table, records=table["records"][:-1])).encode(), "BM_IDENTITY_INVALID:micro"),
        ):
            with self.subTest(case=label):
                path.write_bytes(content)
                entry = history.classify_candidate(self.root, candidate)
                self.assertEqual((entry["status"], entry["reason"]), ("INVALID", reason))
                self.assertEqual(entry["normalized_rows"], [])
        path.write_bytes(payload)
        with self.subTest(case="conflicting-untrusted-declaration"):
            entry = history.classify_candidate(self.root, candidate | {"expected_digest": "sha256:" + "0" * 64})
            self.assertEqual((entry["status"], entry["reason"]), ("INVALID", "digest-mismatch"))
            self.assertEqual(entry["normalized_rows"], [])
        with self.subTest(case="unknown-identity-cannot-be-promoted"):
            entry = history.classify_candidate(self.root, candidate | {"source_identity": "unknown-micro", "expected_digest": _sha(payload)})
            self.assertEqual((entry["status"], entry["reason"]), ("UNVERIFIED", "unsupported-source-identity"))
            self.assertEqual(entry["normalized_rows"], [])
        self.assertEqual(tuple(history.CATALOG), catalog_before)
        self.assertEqual(path.read_bytes(), payload)

    def test_s1f_t16_t6_known_fields(self) -> None:
        receipt = {
            "schema": "pr15i-d3c-freeze-v1",
            "protocol_sha256": "c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c",
            "control_name": "d3c-v3r3-base-aa-01",
            "campaign_names": ["d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02"],
            "t6_commit": "44ccd9e027071cf12777610abae5e6ab5f03177f",
            "tooling_manifest_sha256": "62911a324f63398383323eadebf3acb73120ddb42a9d27300fc924c3c38732f3",
            "protected_files": {"benchmarks/pr15i_d3_c/run.py": "a" * 64},
        }
        before = copy.deepcopy(receipt)
        history._t6_known_fields(receipt)
        history._t6_known_fields(dict(receipt, extra_original_metadata={"note": "kept"}, receipt_origin=None))
        self.assertEqual(receipt, before)
        for field in receipt:
            with self.subTest(case="missing-required", field=field):
                broken = dict(receipt)
                del broken[field]
                self._role_error(BM_SCHEMA_INVALID, field, history._t6_known_fields, broken)
        for field in ("schema", "protocol_sha256", "control_name", "t6_commit", "tooling_manifest_sha256"):
            for label, value in (("wrong-string", "wrong"), ("null", None), ("bool", True), ("list", []), ("mapping", {})):
                with self.subTest(case=label, field=field):
                    self._role_error(BM_IDENTITY_INVALID, field, history._t6_known_fields, receipt | {field: value})
        for label, value in (("reversed", receipt["campaign_names"][::-1]), ("string", "d3c-v3r3-strategies-01"),
                             ("tuple", tuple(receipt["campaign_names"])), ("null", None), ("wrong-type-leaf", [True, {}])):
            with self.subTest(case=label, field="campaign_names"):
                self._role_error(BM_IDENTITY_INVALID, "campaign_names", history._t6_known_fields, receipt | {"campaign_names": value})
        for label, value in (("empty", {}), ("list", []), ("null", None), ("nonstring-key", {1: "a" * 64}),
                             ("short-hash", {"safe": "a"}), ("uppercase-hash", {"safe": "A" * 64}),
                             ("nonstring-hash", {"safe": 7}), ("nonhex-hash", {"safe": "z" * 64})):
            with self.subTest(case=label, field="protected_files"):
                self._role_error(BM_SCHEMA_INVALID, "protected_files", history._t6_known_fields, receipt | {"protected_files": value})
        for path in ("a//b", "a/./b", "../b", "a\\b", "/absolute", "a/../b"):
            with self.subTest(case="unsafe-protected-name", path=path):
                self._role_error(BM_UNSAFE_INPUT, None, history._t6_known_fields, receipt | {"protected_files": {path: "a" * 64}})
        for value in (None, [], True):
            with self.subTest(case="nonmapping-receipt", value=value):
                self._role_error(BM_SCHEMA_INVALID, "receipt", history._t6_known_fields, value)

    def test_s1f_t17_both_policy_schemas(self) -> None:
        for version in ("F1", "F2"):
            original = self._role_policy(version)
            before = copy.deepcopy(original)
            history._read_policy(original)
            self.assertEqual(original, before)
            cases = [
                ("bool-k", ("rows", 0, "k"), True, BM_IDENTITY_INVALID, "rows"),
                ("float-k", ("rows", 0, "k"), 1.0, BM_IDENTITY_INVALID, "rows"),
                ("wrong-k-order", ("rows", 0, "k"), 10, BM_IDENTITY_INVALID, "rows"),
                ("bool-filter", ("rows", 0, "filter_sensitive"), 1, BM_SCHEMA_INVALID, "filter_sensitive"),
                ("negative-memory", ("rows", 0, "H_memory"), -1, BM_SCHEMA_INVALID, "H_memory"),
                ("bool-memory", ("rows", 0, "H_memory"), True, BM_SCHEMA_INVALID, "H_memory"),
                ("float-memory", ("rows", 0, "H_memory"), 0.0, BM_SCHEMA_INVALID, "H_memory"),
                ("nonmapping-row", ("rows", 0), None, BM_SCHEMA_INVALID, "rows"),
                ("missing-row", ("rows",), original["rows"][:-1], BM_IDENTITY_INVALID, "rows"),
                ("non-list-rows", ("rows",), {}, BM_IDENTITY_INVALID, "rows"),
                ("wrong-protocol", ("protocol_sha256",), "0" * 64, BM_IDENTITY_INVALID, "protocol_sha256"),
                ("wrong-status", ("status",), "PASS", BM_IDENTITY_INVALID, "status"),
            ]
            for field in ("selected_strategy", "decision_status", "P_status", "H_status"):
                for label, value in (("null", None), ("list", []), ("mapping", {}), ("bool", True)):
                    cases.append((label + "-label-" + field, ("rows", 0, field), value, BM_SCHEMA_INVALID, field))
            for field in ("P_reasons", "H_reasons"):
                for label, value in (("string", "reason"), ("nonstring-member", [1]), ("null", None)):
                    cases.append((label + "-" + field, ("rows", 0, field), value, BM_SCHEMA_INVALID, field))
            for label, path, value, code, field in cases:
                with self.subTest(version=version, case=label):
                    document = copy.deepcopy(original)
                    parent = document
                    for component in path[:-1]:
                        parent = parent[component]
                    parent[path[-1]] = value
                    self._role_error(code, field, history._read_policy, document)
            for field in ("P_gm", "H_gm"):
                with self.subTest(version=version, case="wrong-gm-presence", field=field):
                    document = copy.deepcopy(original)
                    if version == "F1":
                        del document["rows"][0][field]
                    else:
                        document["rows"][0][field] = [1.0, 2.0]
                    self._role_error(BM_SCHEMA_INVALID, "rows", history._read_policy, document)
            selected = copy.deepcopy(original)
            selected["rows"][0]["decision_status"] = "SELECTED_GM_CONFIRMED"
            with self.subTest(version=version, case="confirmed-is-f2-only"):
                if version == "F1":
                    self._role_error(BM_IDENTITY_INVALID, "rows", history._read_policy, selected)
                else:
                    history._read_policy(selected)
        class IntAlias(int):
            pass
        class FloatAlias(float):
            pass
        for field in ("P_gm", "H_gm"):
            for label, value in (("bool", True), ("string", "1"), ("zero", 0), ("negative", -1),
                                 ("nan", float("nan")), ("infinity", float("inf")),
                                 ("decimal", Decimal("1")), ("int-subclass", IntAlias(1)),
                                 ("float-subclass", FloatAlias(1.0)), ("container", [])):
                with self.subTest(case="invalid-gm-number", field=field, value=label):
                    document = self._role_policy("F1")
                    document["rows"][0][field][0] = value
                    self._role_error(BM_SCHEMA_INVALID, field, history._read_policy, document)
            for label, value in (("null", None), ("string", "1,2"), ("short", [1]), ("long", [1, 2, 3])):
                with self.subTest(case="invalid-gm-array", field=field, value=label):
                    document = self._role_policy("F1")
                    document["rows"][0][field] = value
                    self._role_error(BM_SCHEMA_INVALID, field, history._read_policy, document)

    def test_s1f_t18_fixed_f1_file_map_and_owner_wiring(self) -> None:
        from quervant_bench.official import policy_inputs
        from quervant_bench.tests import official_support as support

        source = self.root / "source"
        document, payload, before = self._role_f1_files(source)
        self.assertEqual(history._f1_file_map(document), F1_PATH_ORACLE)
        for label, broken, code, field in (
            ("null-root", None, BM_SCHEMA_INVALID, "receipt"),
            ("list-root", [], BM_SCHEMA_INVALID, "receipt"),
            ("wrong-commit", document | {"t7_commit": "0" * 40}, BM_IDENTITY_INVALID, "t7_commit"),
            ("bool-commit", document | {"t7_commit": True}, BM_IDENTITY_INVALID, "t7_commit"),
            ("missing-files", {"t7_commit": document["t7_commit"]}, BM_SCHEMA_INVALID, "files"),
            ("list-files", document | {"files": []}, BM_SCHEMA_INVALID, "files"),
            ("extra-file", document | {"files": document["files"] | {"extra.py": "a" * 64}}, BM_SCHEMA_INVALID, "files"),
        ):
            with self.subTest(case=label):
                self._role_error(code, field, history._f1_file_map, broken)
        for name in ("analysis.py", "policy.py", "verify_derived.py", "freeze.py"):
            with self.subTest(case="missing-source-entry", name=name):
                files = dict(document["files"])
                del files[name]
                self._role_error(BM_SCHEMA_INVALID, "files", history._f1_file_map, document | {"files": files})
            for label, value in (("non-string", 7), ("short", "a"), ("uppercase", "A" * 64),
                                 ("prefixed", "sha256:" + "a" * 64), ("nonhex", "g" * 64)):
                with self.subTest(case="malformed-source-digest", name=name, value=label):
                    self._role_error(BM_SCHEMA_INVALID, "files", history._f1_file_map,
                                     document | {"files": document["files"] | {name: value}})
        # Invoke the real owner, which must reject these unpinned synthetic bytes.
        # This proves dependency/root wiring, not authentic F1 acceptance.
        owner = policy_inputs._f1_identity
        for label, configured, expected_root in (("explicit-source", source, source),
                                                 ("repository-fallback", None, support.REPO_ROOT)):
            with self.subTest(case=label):
                observations = [before]
                with patch.object(policy_inputs, "_f1_identity", wraps=owner) as called:
                    self._role_error(BM_IDENTITY_INVALID, "f1_receipt", history._read_f1,
                                     self.root, "f1.json", payload, before, configured, observations)
                self.assertEqual(called.call_count, 1)
                self.assertEqual(called.call_args.args, (self.root / "f1.json", expected_root))
                self.assertEqual(tuple(item.relative for item in observations[1:]), F1_PATH_ORACLE)
                self.assertTrue(all(item.root == expected_root for item in observations[1:]))
                self.assertTrue(all(item.max_bytes == 4 * 1024 * 1024 for item in observations[1:]))
                history._recheck(observations)
        missing = history.classify_candidate(self.root, self._role_candidate(
            family="retained-key", input_role="retained-f1-receipt", path="authentic-f1-absent.json",
            source_identity="38a937fdf0b09f1330f26423dabb311399c8a4cf",
            expected_digest="sha256:80f21e8fb7c9a76d466d749b0253f50bf8955112db0214386abbfcb9a9532ee1"))
        self.assertEqual((missing["status"], missing["reason"]), ("UNAVAILABLE", "not-found"))
        self.assertEqual(missing["normalized_rows"], [])

    def test_s1f_t18_dependency_absence_mutation_and_owner_failure(self) -> None:
        from quervant_bench.official import policy_inputs

        source = self.root / "source"
        for index, missing_relative in enumerate(F1_PATH_ORACLE):
            with self.subTest(case="first-observation-missing", source=missing_relative):
                _document, payload, before = self._role_f1_files(source)
                (source / missing_relative).unlink()
                observations = [before]
                with patch.object(policy_inputs, "_f1_identity", wraps=policy_inputs._f1_identity) as called:
                    with self.assertRaises(history._DependencyUnavailable) as raised:
                        history._read_f1(self.root, "f1.json", payload, before, source, observations)
                self.assertEqual(raised.exception.kind, "source")
                self.assertEqual(called.call_count, 0)
                self.assertEqual(tuple(item.relative for item in observations[1:]), F1_PATH_ORACLE[:index])
                history._recheck(observations)
                # A tentative missing-dependency result must still recheck the
                # original candidate. This is the private status seam, not FOUND.
                tentative = {"input_role": "retained-f1-receipt", "source_identity": history.RETAINED_F1,
                             "input_digest": before.digest, "status": "UNVERIFIED",
                             "reason": "owning-reader-source-unavailable", "normalized_rows": []}
                self.assertEqual(history._finalise(tentative, observations), tentative)
                (self.root / "f1.json").write_bytes(payload + b" ")
                result = history._finalise(tentative, observations)
                self.assertEqual((result["status"], result["reason"]),
                                 ("INVALID", "changed-during-read:BM_IDENTITY_INVALID"))
        for label, owner_code in (("owner-file-missing", BM_FILE_MISSING),
                                  ("owner-evidence-unavailable", BM_EVIDENCE_UNAVAILABLE)):
            with self.subTest(case=label):
                _document, payload, before = self._role_f1_files(source)
                observations = [before]
                calls = []
                def disappear_at_owner(receipt_path, source_root):
                    calls.append((receipt_path, source_root))
                    self.assertEqual(tuple(item.relative for item in observations[1:]), F1_PATH_ORACLE)
                    (source / F1_PATH_ORACLE[-1]).unlink()
                    raise BenchError(owner_code, "injected post-observation source disappearance", field_path="f1_receipt")
                with patch.object(policy_inputs, "_f1_identity", side_effect=disappear_at_owner):
                    self._role_error(BM_IDENTITY_INVALID, "path", history._read_f1,
                                     self.root, "f1.json", payload, before, source, observations)
                self.assertEqual(calls, [(self.root / "f1.json", source)])
                self._role_error(BM_IDENTITY_INVALID, "path", history._recheck, observations)
        for label in ("changed-content", "same-bytes-new-inode", "disappearance"):
            with self.subTest(case="dependency-recheck", mutation=label):
                _document, _payload, before = self._role_f1_files(source)
                observations = [before] + [history._observe_file(source, name, max_bytes=4 * 1024 * 1024)[0]
                                           for name in F1_PATH_ORACLE]
                target = source / F1_PATH_ORACLE[1]
                if label == "changed-content":
                    target.write_bytes(target.read_bytes() + b"changed")
                elif label == "same-bytes-new-inode":
                    replacement = self.root / "replacement.py"
                    replacement.write_bytes(target.read_bytes())
                    os.replace(replacement, target)
                else:
                    target.unlink()
                self._role_error(BM_IDENTITY_INVALID, "path", history._recheck, observations)

    def test_s1f_t19_pr15d_manifest_api_binding(self) -> None:
        from quervant_bench.evidence.archives import ArchiveLimits, MemberDigest, inspect_zip
        from quervant_bench.tests import official_support as support

        manifest_path = support.REPO_ROOT / "docs/pr-artifacts/pr-15d/b-evidence-manifest.json"
        payload = manifest_path.read_bytes()
        self.assertEqual(_sha(payload), "sha256:bdc8308d1b0279959395a0dd1e0b375da6efd4154b0fadf216b80fbd80a95c6f")
        manifest = history._parse(payload, "manifest", decimals=False)
        self.assertEqual((len(manifest["members"]), len(manifest["raw_manifests"]),
                          len(manifest["contention_records"])), (68, 9, 54))
        self.assertIs(type(manifest["resources"]), dict)
        self.assertIs(type(manifest["validation"]), dict)
        published = manifest["raw_manifests"] + manifest["contention_records"] + [manifest["resources"], manifest["validation"]]
        self.assertEqual(len(published), 65)
        self.assertEqual(set(manifest["members"]) - {item["path"] for item in published},
                         {"README.md", "SHA256SUMS", "run.json"})
        members = [MemberDigest(item["path"], "sha256:" + item["sha256"], item["bytes"]) for item in published]
        members += [MemberDigest(name, _sha(b""), 0) for name in ("README.md", "SHA256SUMS", "run.json")]
        package = dict(archive_digest="sha256:426dff2920b55ff63766da284421cf698f9950011da409b88a33be5d6d4e7bab",
                       archive_bytes=502566)
        # Pure schema/API binding only: these synthetic inspection records never
        # enter classify_candidate and do not authenticate an archive.
        history._pr15d_binding(manifest, members, **package)
        with self.subTest(case="coherent-unpublished-replacement"):
            document = copy.deepcopy(manifest)
            document["members"] = ["other.txt" if name == "README.md" else name for name in document["members"]]
            inspected = [MemberDigest("other.txt", item.digest, item.byte_length) if item.name == "README.md" else item
                         for item in members]
            self._role_error(BM_IDENTITY_INVALID, "members", history._pr15d_binding, document, inspected, **package)
        for label, path in (("duplicate-published", manifest["raw_manifests"][1]["path"]),
                            ("case-collision-published", manifest["raw_manifests"][1]["path"].upper())):
            with self.subTest(case=label):
                document = copy.deepcopy(manifest)
                document["raw_manifests"][0]["path"] = path
                self._role_error(BM_SCHEMA_INVALID, "raw_manifests", history._pr15d_binding, document, members, **package)
        with self.subTest(case="published-path-outside-full-set"):
            document = copy.deepcopy(manifest)
            document["raw_manifests"][0]["path"] = "unexpected/member.json"
            self._role_error(BM_IDENTITY_INVALID, "members", history._pr15d_binding, document, members, **package)
        for label, doc, inspected, overrides, code, field in (
            ("missing-readme", manifest, [m for m in members if m.name != "README.md"], {}, BM_IDENTITY_INVALID, "archive"),
            ("duplicate-inspected", manifest, members + [members[0]], {}, BM_SCHEMA_INVALID, "archive"),
            ("case-collision-inspected", manifest, members + [MemberDigest(members[0].name.upper(), members[0].digest, members[0].byte_length)], {}, BM_SCHEMA_INVALID, "archive"),
            ("nonsequence-inspected", manifest, None, {}, BM_SCHEMA_INVALID, "archive"),
            ("nonmember-inspected", manifest, [None], {}, BM_SCHEMA_INVALID, "archive"),
            ("wrong-package-bytes", manifest, members, {"archive_bytes": 502567}, BM_IDENTITY_INVALID, "package"),
            ("wrong-package-digest", manifest, members, {"archive_digest": "sha256:" + "0" * 64}, BM_IDENTITY_INVALID, "package"),
            ("nonmapping-manifest", None, members, {}, BM_SCHEMA_INVALID, "manifest"),
            ("wrong-run", manifest | {"run_id": "other"}, members, {}, BM_IDENTITY_INVALID, "manifest"),
            ("wrong-source", manifest | {"source_sha": "0" * 40}, members, {}, BM_IDENTITY_INVALID, "manifest"),
        ):
            with self.subTest(case=label):
                self._role_error(code, field, history._pr15d_binding, doc, inspected, **(package | overrides))
        first = members[0]
        for label, replacement in (
            ("published-length", MemberDigest(first.name, first.digest, first.byte_length + 1)),
            ("published-hash", MemberDigest(first.name, "sha256:" + "0" * 64, first.byte_length)),
        ):
            with self.subTest(case=label):
                self._role_error(BM_IDENTITY_INVALID, first.name, history._pr15d_binding,
                                 manifest, [replacement] + members[1:], **package)
        for label, replacement in (
            ("nonstring-name", MemberDigest(None, first.digest, first.byte_length)),
            ("float-length", MemberDigest(first.name, first.digest, float(first.byte_length))),
            ("bool-length", MemberDigest(first.name, first.digest, True)),
            ("negative-length", MemberDigest(first.name, first.digest, -1)),
            ("nondigest", MemberDigest(first.name, None, first.byte_length)),
        ):
            with self.subTest(case=label):
                self._role_error(BM_SCHEMA_INVALID, "archive", history._pr15d_binding,
                                 manifest, [replacement] + members[1:], **package)
        for field in ("resources", "validation"):
            with self.subTest(case="list-valued-singleton", field=field):
                self._role_error(BM_SCHEMA_INVALID, field, history._pr15d_binding,
                                 manifest | {field: [manifest[field]]}, members, **package)
        for field in ("raw_manifests", "contention_records"):
            for label, value, code in (("nonlist", {}, BM_SCHEMA_INVALID),
                                       ("truncated", manifest[field][:-1], BM_IDENTITY_INVALID)):
                with self.subTest(case=label, field=field):
                    self._role_error(code, field, history._pr15d_binding, manifest | {field: value}, members, **package)
        for label, value, code in (("null-members", None, BM_SCHEMA_INVALID),
                                   ("truncated-members", manifest["members"][:-1], BM_IDENTITY_INVALID),
                                   ("nonstr-member", [None] + manifest["members"][1:], BM_SCHEMA_INVALID),
                                   ("duplicate-declared", [manifest["members"][1]] + manifest["members"][1:], BM_IDENTITY_INVALID),
                                   ("case-collision-declared", [manifest["members"][1].upper()] + manifest["members"][1:], BM_IDENTITY_INVALID)):
            with self.subTest(case=label):
                self._role_error(code, "members", history._pr15d_binding, manifest | {"members": value}, members, **package)
        for label, value, code in (
            ("null-package", None, BM_SCHEMA_INVALID),
            ("wrong-basename", manifest["package"] | {"path": "/historical/other.zip"}, BM_IDENTITY_INVALID),
            ("nonstring-package-path", manifest["package"] | {"path": None}, BM_SCHEMA_INVALID),
            ("float-package-bytes", manifest["package"] | {"bytes": 502566.0}, BM_SCHEMA_INVALID),
            ("bool-package-bytes", manifest["package"] | {"bytes": True}, BM_SCHEMA_INVALID),
            ("wrong-package-hash", manifest["package"] | {"sha256": "0" * 64}, BM_IDENTITY_INVALID),
            ("extra-package-field", manifest["package"] | {"extra": 0}, BM_SCHEMA_INVALID),
        ):
            with self.subTest(case=label):
                self._role_error(code, "package", history._pr15d_binding, manifest | {"package": value}, members, **package)
        for field, value in (("path", None), ("bytes", True), ("bytes", 1.0), ("bytes", -1),
                             ("sha256", None), ("sha256", "G" * 64)):
            with self.subTest(case="published-record-schema", field=field, value=repr(value)):
                document = copy.deepcopy(manifest)
                document["raw_manifests"][0][field] = value
                self._role_error(BM_SCHEMA_INVALID, "raw_manifests", history._pr15d_binding, document, members, **package)
        # Exercise inspect_zip's real dataclass API with a tiny real ZIP. This
        # archive has no claim to match the independently pinned PR15D package.
        archive = self.root / "synthetic-api.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("tiny/data.txt", b"real inspector bytes")
        inspected = inspect_zip(self.root, archive.name, ArchiveLimits())
        self.assertEqual(inspected, (MemberDigest("tiny/data.txt", _sha(b"real inspector bytes"), 20),))
        self.assertEqual(manifest_path.read_bytes(), payload)

    def test_s1f_t20_retained_archive_paths_sidecars_and_owner_wiring(self) -> None:
        from quervant_bench.official import historical

        campaigns = ("d3c-v3r3-base-aa-01", "d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02")
        for campaign in campaigns:
            for parent in (Path(), Path("nested") / campaign):
                with self.subTest(case="pure-route", campaign=campaign, parent=str(parent)):
                    member = str(parent / f"{campaign}.tar.gz")
                    self.assertEqual(history._retained_archive_paths(self.root, member, campaign),
                                     (self.root / parent, f"{campaign}.tar.gz", f"{campaign}.tar.gz.sha256"))
            with self.subTest(case="wrong-basename", campaign=campaign):
                self._role_error(BM_IDENTITY_INVALID, "path", history._retained_archive_paths,
                                 self.root, "nested/wrong.tar.gz", campaign)
        for value in (None, [], {}, True, "other-campaign"):
            with self.subTest(case="wrong-campaign", value=repr(value)):
                self._role_error(BM_IDENTITY_INVALID, "campaign", history._retained_archive_paths,
                                 self.root, "archive.tar.gz", value)
        for member in ("../escape.tar.gz", "/absolute.tar.gz", "a//b.tar.gz", "a\\b.tar.gz"):
            with self.subTest(case="unsafe-member", member=member):
                self._role_error(BM_UNSAFE_INPUT, None, history._retained_archive_paths,
                                 self.root, member, campaigns[0])
        for campaign in campaigns:
            parent = self.root / "nested" / campaign
            parent.mkdir(parents=True)
            basename = f"{campaign}.tar.gz"
            member = f"nested/{campaign}/{basename}"
            archive = parent / basename
            archive.write_bytes(b"synthetic archive candidate; no authentication claim")
            before, captured = history._observe_file(self.root, member, max_bytes=4 * 1024 ** 3)
            self.assertIsNone(captured)
            record = history.record_for("retained-archive", campaign)
            self.assertIsNotNone(record)
            with self.subTest(case="first-sidecar-absence", campaign=campaign):
                observations = [before]
                with self.assertRaises(history._DependencyUnavailable) as raised:
                    history._read_archive(self.root, member, record, observations)
                self.assertEqual(raised.exception.kind, "sidecar")
                self.assertEqual(observations, [before])
                tentative = {"input_role": "retained-archive", "source_identity": campaign,
                             "input_digest": before.digest, "status": "UNVERIFIED",
                             "reason": "owning-reader-sidecar-unavailable", "normalized_rows": []}
                self.assertEqual(history._finalise(tentative, observations), tentative)
            sidecar = parent / (basename + ".sha256")
            for label, document, code, field in (
                ("missing-members", {}, BM_SCHEMA_INVALID, "sidecar"),
                ("empty-members", {"members": {}}, BM_SCHEMA_INVALID, "sidecar"),
                ("list-members", {"members": []}, BM_SCHEMA_INVALID, "sidecar"),
                ("doubled-slash", {"members": {"a//b": "a" * 64}}, BM_UNSAFE_INPUT, None),
                ("dot-component", {"members": {"a/./b": "a" * 64}}, BM_UNSAFE_INPUT, None),
                ("traversal", {"members": {"../b": "a" * 64}}, BM_UNSAFE_INPUT, None),
                ("case-collision", {"members": {"A": "a" * 64, "a": "b" * 64}}, BM_IDENTITY_INVALID, "sidecar"),
            ):
                with self.subTest(case=label, campaign=campaign):
                    sidecar.write_bytes(json.dumps(document).encode())
                    self._role_error(code, field, history._read_archive, self.root, member, record, [before])
            sidecar_payload = json.dumps({"members": {"nested/member.json": "a" * 64}}).encode()
            for owner_code in (BM_FILE_MISSING, BM_EVIDENCE_UNAVAILABLE):
                with self.subTest(case="post-observation-owner-disappearance", campaign=campaign, code=owner_code):
                    sidecar.write_bytes(sidecar_payload)
                    observations = [before]
                    calls = []
                    def failing_owner(archive_parent, actual_campaign, *, limits):
                        calls.append((archive_parent, actual_campaign, limits))
                        self.assertEqual(len(observations), 2)
                        self.assertEqual(observations[-1].relative, basename + ".sha256")
                        self.assertEqual(observations[-1].root, parent)
                        self.assertEqual(observations[-1].max_bytes, 4 * 1024 * 1024)
                        sidecar.unlink()
                        raise BenchError(owner_code, "injected disappearance after sidecar observation")
                    with patch.object(historical, "audit_retained_key_archive", side_effect=failing_owner):
                        self._role_error(BM_IDENTITY_INVALID, "path", history._read_archive,
                                         self.root, member, record, observations)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0][:2], (parent, campaign))
                    self.assertEqual((calls[0][2].max_archive_bytes, calls[0][2].max_members,
                                      calls[0][2].max_member_bytes, calls[0][2].max_total_uncompressed_bytes),
                                     (4 * 1024 ** 3, 5000, 256 * 1024 ** 2, 4 * 1024 ** 3))
            for label in ("leaf-symlink", "hardlink", "fifo"):
                with self.subTest(case="unsafe-sidecar", campaign=campaign, kind=label):
                    sidecar.unlink(missing_ok=True)
                    target = parent / "sidecar-target.json"
                    target.write_bytes(sidecar_payload)
                    try:
                        if label == "leaf-symlink":
                            sidecar.symlink_to(target)
                        elif label == "hardlink":
                            os.link(target, sidecar)
                        else:
                            os.mkfifo(sidecar)
                        with self.assertRaises(BenchError) as raised:
                            history._read_archive(self.root, member, record, [before])
                        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
                        self.assertEqual(raised.exception.field_path, "path" if label == "hardlink" else None)
                    finally:
                        sidecar.unlink(missing_ok=True)
                        target.unlink(missing_ok=True)
            # Candidate absence is exercised through the actual public classifier;
            # the deliberately unpinned synthetic archive is never made FOUND.
            archive.unlink()
            candidate = self._role_candidate(family="retained-key", input_role="retained-archive",
                                             path=member, source_identity=campaign, expected_digest=record.digest)
            entry = history.classify_candidate(self.root, candidate)
            self.assertEqual((entry["status"], entry["reason"]), ("UNAVAILABLE", "not-found"))
            self.assertEqual(entry["normalized_rows"], [])

        self._role_authentic_archives_if_available()

    def _role_authentic_archives_if_available(self) -> None:
        from quervant_bench.official import historical

        # Availability is not acceptance. Mandatory synthetic routing/negative
        # controls above always execute. No fake owner or anchor replacement is
        # used to manufacture the optional authenticated positive below.
        recorded_root = historical.historical_archive_root()
        campaigns = ("d3c-v3r3-base-aa-01", "d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02")
        for campaign in campaigns:
            archive = recorded_root / f"{campaign}.tar.gz"
            sidecar = recorded_root / f"{campaign}.tar.gz.sha256"
            if not archive.is_file() or not sidecar.is_file():
                continue  # Explicitly unavailable optional positive; never a skip/PASS claim of authenticity.
            with self.subTest(case="authentic-nested-owner", campaign=campaign):
                self.assertEqual(history.raw_digest(archive), history.SUPPORTED_SOURCES[("retained-archive", campaign)])
                nested = self.root / "authentic" / campaign
                nested.mkdir(parents=True)
                copied_archive, copied_sidecar = nested / archive.name, nested / sidecar.name
                shutil.copyfile(archive, copied_archive)
                shutil.copyfile(sidecar, copied_sidecar)
                before = {path: history.raw_digest(path) for path in (copied_archive, copied_sidecar)}
                entry = history.classify_candidate(self.root, self._role_candidate(
                    family="retained-key", input_role="retained-archive", path=str(copied_archive.relative_to(self.root)),
                    source_identity=campaign, expected_digest=history.SUPPORTED_SOURCES[("retained-archive", campaign)]))
                self.assertEqual((entry["status"], entry["reason"]),
                                 ("FOUND", "authenticated-archive"))
                self.assertEqual(entry["normalized_rows"], [])
                self.assertEqual({path: history.raw_digest(path) for path in before}, before)

    def test_s1f_t21_exact_summary_schemas(self) -> None:
        aggregate = history._parse(self._aggregate().read_bytes(), "aggregate", decimals=True)
        digest = "sha256:c9e8ed722aefc4fef43837a5511c2c88575287497b449f68f82f7ea0c251b257"
        self.assertEqual(len(history.pr15d_aggregate_rows(aggregate, input_digest=digest)), 32)
        cases = [
            ("null-latency", ("latency",), None, BM_SCHEMA_INVALID, "latency"),
            ("mapping-latency", ("latency",), {}, BM_SCHEMA_INVALID, "latency"),
            ("null-lane", ("latency", 0), None, BM_SCHEMA_INVALID, "latency"),
            ("decimal-n", ("latency", 0, "n"), Decimal("10000.0"), BM_SCHEMA_INVALID, "n"),
            ("decimal-k", ("latency", 0, "k"), Decimal("10.0"), BM_SCHEMA_INVALID, "k"),
            ("bool-n", ("latency", 0, "n"), True, BM_SCHEMA_INVALID, "n"),
            ("list-id", ("latency", 0, "id"), [], BM_SCHEMA_INVALID, "id"),
            ("wrong-coordinate", ("latency", 0, "n"), 100001, BM_IDENTITY_INVALID, "id"),
        ]
        for field in ("class", "regime", "field", "term"):
            cases.append(("nonstring-" + field, ("latency", 0, field), None, BM_SCHEMA_INVALID, field))
        for value_label, value in (("null", None), ("list", [])):
            for field in ("engines", "comparisons"):
                cases.append((value_label + "-" + field, ("latency", 0, field), value, BM_SCHEMA_INVALID, field))
            cases.append((value_label + "-engine-record", ("latency", 0, "engines", "quervant"), value, BM_SCHEMA_INVALID, "engines"))
            cases.append((value_label + "-comparison-record", ("latency", 0, "comparisons", "lucene"), value, BM_SCHEMA_INVALID, "comparisons"))
        for field in ("trial_medians_ns", "trial_p95_ns", "trial_p99_ns"):
            cases.append(("short-" + field, ("latency", 0, "engines", "quervant", field), [1, 2], BM_SCHEMA_INVALID, field))
            cases.append(("bool-" + field, ("latency", 0, "engines", "quervant", field, 0), True, BM_SCHEMA_INVALID, field))
            cases.append(("float-" + field, ("latency", 0, "engines", "quervant", field, 0), 1.0, BM_SCHEMA_INVALID, field))
        cases += [
            ("bool-median", ("latency", 0, "engines", "quervant", "median_ns"), True, BM_SCHEMA_INVALID, "median_ns"),
            ("zero-median", ("latency", 0, "engines", "quervant", "median_ns"), 0, BM_SCHEMA_INVALID, "median_ns"),
            ("string-dispersion", ("latency", 0, "engines", "quervant", "dispersion_max_over_min"), "1.0", BM_SCHEMA_INVALID, "dispersion_max_over_min"),
            ("nan-dispersion", ("latency", 0, "engines", "quervant", "dispersion_max_over_min"), Decimal("NaN"), BM_SCHEMA_INVALID, "dispersion_max_over_min"),
            ("bool-inconclusive", ("latency", 0, "comparisons", "lucene", "inconclusive"), 1, BM_SCHEMA_INVALID, "inconclusive"),
            ("bool-overlap", ("latency", 0, "comparisons", "lucene", "trial_median_range_overlap"), 0, BM_SCHEMA_INVALID, "trial_median_range_overlap"),
            ("nonstr-note", ("latency", 0, "comparisons", "lucene", "note"), None, BM_SCHEMA_INVALID, "note"),
        ]
        for field in ("engine_over_quervant_ratio", "quervant_over_engine_speedup"):
            for label, value in (("str", "0.7"), ("bool", True), ("zero", 0), ("float", 0.7), ("nan", Decimal("NaN"))):
                cases.append((label + "-" + field, ("latency", 0, "comparisons", "lucene", field), value, BM_SCHEMA_INVALID, field))
        for label, path, value, code, field in cases:
            with self.subTest(family="cross-engine", case=label):
                document = copy.deepcopy(aggregate)
                parent = document
                for component in path[:-1]:
                    parent = parent[component]
                parent[path[-1]] = value
                self._role_error(code, field, history.pr15d_aggregate_rows, document, input_digest=digest)
        # Cold records are validated even though no cold row is emitted.
        cold_index = next(index for index, lane in enumerate(aggregate["latency"]) if lane["regime"] == "process_cold")
        document = copy.deepcopy(aggregate)
        document["latency"][cold_index]["comparisons"]["lucene"]["engine_over_quervant_ratio"] = "0.5"
        self._role_error(BM_SCHEMA_INVALID, "engine_over_quervant_ratio", history.pr15d_aggregate_rows, document, input_digest=digest)

        retained = self._role_retained()
        lanes = [f"pr15d_v1/{n}/{class_name}/k{k}"
                 for n in (10000, 100000)
                 for class_name in ("absent", "rare", "medium", "common")
                 for k in (1, 10, 32, 64, 100, 128, 256, 512, 1024)]
        rows = history.retained_analysis_rows(retained, input_digest=DIGEST)
        expected_keys = {(lane, campaign, baseline, treatment)
                         for lane in lanes for campaign in RETAINED_CAMPAIGN_ORACLE
                         for _r, _ci, baseline, treatment, _ratio, _gain in PAIR_ORACLE}
        keyed = {(row["lane_id"], row["campaign_id"], row["baseline"], row["treatment"]): row for row in rows}
        self.assertEqual(len(rows), 864)
        self.assertEqual(set(keyed), expected_keys)
        for lane in lanes:
            for campaign in RETAINED_CAMPAIGN_ORACLE:
                for _ratio_field, _ci_field, baseline, treatment, ratio, gain in PAIR_ORACLE:
                    with self.subTest(case="independent-six-pair-golden", lane=lane, campaign=campaign, pair=f"{baseline}->{treatment}"):
                        row = keyed[(lane, campaign, baseline, treatment)]
                        self.assertEqual((row["ratio"], row["gain_percent"]), (ratio, gain))
                        self.assertEqual(row["uncertainty"], {"low": ratio, "high": ratio, "seed": 11, "method": "paired-slot-bootstrap-v1"})
                        self.assertEqual((row["evidence_level"], row["run_id"], row["source_commit"]),
                                         ("AS_REPORTED", campaign, "3ad6c5184fbe9c011abb731415a007e3f19d21de"))
        lane = "pr15d_v1/10000/absent/k1"
        record_path = ("lanes", lane, "campaigns", "d3c-v3r3-strategies-01")
        cases = [
            ("null-series", ("series",), None, BM_SCHEMA_INVALID, "series"),
            ("reversed-series", ("series",), list(reversed(RETAINED_CAMPAIGN_ORACLE)), BM_IDENTITY_INVALID, "series"),
            ("null-lanes", ("lanes",), None, BM_SCHEMA_INVALID, "lanes"),
            ("null-lane", ("lanes", lane), None, BM_SCHEMA_INVALID, "lanes"),
            ("bool-k", ("lanes", lane, "k"), True, BM_SCHEMA_INVALID, "k"),
            ("decimal-k", ("lanes", lane, "k"), Decimal("1.0"), BM_SCHEMA_INVALID, "k"),
            ("decimal-n", ("lanes", lane, "n"), Decimal("10000.0"), BM_SCHEMA_INVALID, "n"),
            ("null-class", ("lanes", lane, "class"), None, BM_SCHEMA_INVALID, "class"),
            ("wrong-coordinate", ("lanes", lane, "n"), 100001, BM_IDENTITY_INVALID, "lanes"),
            ("null-campaigns", ("lanes", lane, "campaigns"), None, BM_SCHEMA_INVALID, "campaigns"),
            ("null-record", record_path, None, BM_SCHEMA_INVALID, "campaigns"),
            ("string-cap", record_path + ("cap",), "1.5", BM_SCHEMA_INVALID, "cap"),
            ("float-cap", record_path + ("cap",), 1.5, BM_SCHEMA_INVALID, "cap"),
            ("nan-cap", record_path + ("cap",), Decimal("NaN"), BM_SCHEMA_INVALID, "cap"),
            ("wrong-cap", record_path + ("cap",), Decimal("1.25"), BM_IDENTITY_INVALID, "cap"),
            ("bool-retained", record_path + ("retained", 0), True, BM_SCHEMA_INVALID, "retained"),
            ("float-retained", record_path + ("retained", 0), 1.0, BM_SCHEMA_INVALID, "retained"),
            ("wrong-retained-count", record_path + ("retained_count",), 5, BM_IDENTITY_INVALID, "retained_count"),
            ("bool-retained-count", record_path + ("retained_count",), True, BM_IDENTITY_INVALID, "retained_count"),
            ("null-excluded", record_path + ("excluded",), None, BM_SCHEMA_INVALID, "excluded"),
            ("null-excluded-record", record_path + ("excluded", 0), None, BM_SCHEMA_INVALID, "excluded"),
            ("bool-excluded-id", record_path + ("excluded", 0, "block"), True, BM_SCHEMA_INVALID, "excluded"),
            ("float-excluded-id", record_path + ("excluded", 0, "block"), 5.0, BM_SCHEMA_INVALID, "excluded"),
            ("wrong-complement", record_path + ("excluded", 0, "block"), 6, BM_IDENTITY_INVALID, "excluded"),
            ("null-within", record_path + ("excluded", 0, "within"), None, BM_SCHEMA_INVALID, "within"),
            ("string-within", record_path + ("excluded", 0, "within", "H"), "1.6", BM_SCHEMA_INVALID, "within"),
            ("wrong-arms", record_path + ("excluded", 0, "arms"), ["L", "H"], BM_IDENTITY_INVALID, "arms"),
            ("empty-arms", record_path + ("excluded", 0, "arms"), [], BM_IDENTITY_INVALID, "arms"),
            ("null-latency", record_path + ("latency",), None, BM_SCHEMA_INVALID, "latency"),
            ("nonnumeric-latency", record_path + ("latency", "A"), "100", BM_SCHEMA_INVALID, "latency"),
            ("null-raw-latency", record_path + ("raw_latency",), None, BM_SCHEMA_INVALID, "raw_latency"),
            ("null-raw-ratio", record_path + ("raw_ratio",), None, BM_SCHEMA_INVALID, "raw_ratio"),
            ("bool-filter", record_path + ("filter_sensitive",), 0, BM_SCHEMA_INVALID, "filter_sensitive"),
            ("string-ratio", record_path + ("R_L_A",), "0.8", BM_SCHEMA_INVALID, "R_L_A"),
            ("null-ci", record_path + ("CI_L_A",), None, BM_SCHEMA_INVALID, "CI_L_A"),
            ("string-low", record_path + ("CI_L_A", "low"), "0.8", BM_SCHEMA_INVALID, "CI_L_A"),
            ("string-high", record_path + ("CI_L_A", "high"), "0.8", BM_SCHEMA_INVALID, "CI_L_A"),
            ("nonfinite-low", record_path + ("CI_L_A", "low"), Decimal("NaN"), BM_SCHEMA_INVALID, "CI_L_A"),
            ("inverted-ci", record_path + ("CI_L_A", "low"), Decimal("0.9"), BM_SCHEMA_INVALID, "uncertainty"),
            ("bool-seed", record_path + ("CI_L_A", "seed"), True, BM_SCHEMA_INVALID, "CI_L_A"),
            ("negative-seed", record_path + ("CI_L_A", "seed"), -1, BM_IDENTITY_INVALID, "uncertainty.seed"),
            ("overflow-seed", record_path + ("CI_L_A", "seed"), 2 ** 64, BM_IDENTITY_INVALID, "uncertainty.seed"),
            ("wrong-protocol", ("protocol_sha256",), "0" * 64, BM_IDENTITY_INVALID, "protocol_sha256"),
            ("prefixed-protocol", ("protocol_sha256",), "sha256:" + retained["protocol_sha256"], BM_IDENTITY_INVALID, "protocol_sha256"),
            ("nonstring-protocol", ("protocol_sha256",), True, BM_SCHEMA_INVALID, "protocol_sha256"),
        ]
        for label, path, value, code, field in cases:
            with self.subTest(family="retained", case=label):
                document = copy.deepcopy(retained)
                parent = document
                for component in path[:-1]:
                    parent = parent[component]
                parent[path[-1]] = value
                self._role_error(code, field, history.retained_analysis_rows, document, input_digest=DIGEST)
        for field in ("CI_L_A", "R_L_A", "cap"):
            with self.subTest(case="missing-campaign-field", field=field):
                document = copy.deepcopy(retained)
                del document["lanes"][lane]["campaigns"][RETAINED_CAMPAIGN_ORACLE[0]][field]
                self._role_error(BM_SCHEMA_INVALID, "campaigns", history.retained_analysis_rows, document, input_digest=DIGEST)
        class IntAlias(int):
            pass
        class DecimalAlias(Decimal):
            pass
        for value in (IntAlias(1), DecimalAlias("0.8")):
            with self.subTest(case="exact-source-number-subclass", kind=type(value).__name__):
                document = copy.deepcopy(retained)
                document["lanes"][lane]["campaigns"][RETAINED_CAMPAIGN_ORACLE[0]]["R_L_A"] = value
                self._role_error(BM_SCHEMA_INVALID, "R_L_A", history.retained_analysis_rows, document, input_digest=DIGEST)

    def test_s1f_t22_fixed_historical_row_binding(self) -> None:
        (self.root / "aggregate.json").write_bytes(self._aggregate().read_bytes())
        entry = history.classify_candidate(self.root, self._role_candidate())
        self.assertEqual(entry["status"], "FOUND")
        self.assertEqual(history.validate_entry(entry), entry)
        rows = entry["normalized_rows"]
        for field, value in (("run_id", "11111111-1111-4111-8111-111111111111"),
                             ("source_commit", "b" * 40),
                             ("method_id", "cross-engine-three-trial-effects-v1"),
                             ("input_digest", "sha256:" + "2" * 64),
                             ("evidence_level", "RECOMPUTED")):
            with self.subTest(family="cross-engine", field=field):
                broken = copy.deepcopy(entry)
                broken["normalized_rows"][0][field] = value
                self._role_error(BM_IDENTITY_INVALID, "normalized_rows", history.validate_entry, broken)
        self._role_error(BM_SCHEMA_INVALID, "rows", history.validate_entry,
                         entry | {"normalized_rows": rows + [copy.deepcopy(rows[0])]})
        # This synthetic retained entry is a structural boundary fixture only.
        # Its fixed catalog metadata is not sent through classify_candidate.
        retained_digest = "sha256:2c3854e4ff02f5acc9d7837d0267ae40101180df01c7db088705451bc8df3065"
        retained_rows = history.retained_analysis_rows(self._role_retained(), input_digest=retained_digest)
        retained_entry = {
            "input_role": "retained-analysis", "source_identity": "a59fdfc0230aa15b71aaf11566960bc47f7c7723",
            "input_digest": retained_digest, "status": "FOUND", "reason": "synthetic-structural-boundary-only",
            "normalized_rows": retained_rows,
        }
        self.assertEqual(history.validate_entry(retained_entry), retained_entry)
        for field, value in (("run_id", "d3c-v3r3-strategies-02"), ("source_commit", "b" * 40),
                             ("input_digest", "sha256:" + "2" * 64), ("evidence_level", "RECOMPUTED")):
            with self.subTest(family="retained", field=field):
                broken = copy.deepcopy(retained_entry)
                broken["normalized_rows"][0][field] = value
                self._role_error(BM_IDENTITY_INVALID, "normalized_rows", history.validate_entry, broken)
        self._role_error(BM_SCHEMA_INVALID, "rows", history.validate_entry,
                         retained_entry | {"normalized_rows": retained_rows + [copy.deepcopy(retained_rows[0])]})
        for label, control in (("cross-subset", entry), ("retained-subset", retained_entry)):
            with self.subTest(case=label):
                subset = control | {"normalized_rows": control["normalized_rows"][:1]}
                self.assertEqual(history.validate_entry(subset), subset)

    def test_s1f_t23_classification_transitions(self) -> None:
        payload = self._aggregate().read_bytes()
        (self.root / "aggregate.json").write_bytes(payload)
        base = self._role_candidate()
        for label, candidate, expected in (
            ("null-pinned-declaration", base | {"expected_digest": None}, ("INVALID", "declared-digest-conflicts-with-independent-anchor")),
            ("conflicting-pinned-declaration", base | {"expected_digest": "sha256:" + "0" * 64}, ("INVALID", "declared-digest-conflicts-with-independent-anchor")),
            ("unknown-identity", base | {"source_identity": "unknown-run"}, ("UNVERIFIED", "unsupported-source-identity")),
            ("missing-candidate", base | {"path": "missing.json"}, ("UNAVAILABLE", "not-found")),
        ):
            with self.subTest(case=label):
                entry = history.classify_candidate(self.root, candidate)
                self.assertEqual((entry["status"], entry["reason"]), expected)
                self.assertEqual(entry["normalized_rows"], [])
        (self.root / "tampered.json").write_bytes(payload + b" ")
        entry = history.classify_candidate(self.root, base | {"path": "tampered.json"})
        self.assertEqual((entry["status"], entry["reason"]), ("INVALID", "digest-mismatch"))
        self.assertEqual(entry["normalized_rows"], [])
        found = history.classify_candidate(self.root, base)
        self.assertEqual(found["status"], "FOUND")
        self._role_error(BM_IDENTITY_INVALID, "source_identity", history.validate_entry, found | {"source_identity": "unknown-run"})
        self._role_error(BM_IDENTITY_INVALID, "input_digest", history.validate_entry, found | {"input_digest": "sha256:" + "0" * 64})
        self._role_error(BM_IDENTITY_INVALID, "normalized_rows", history.validate_entry, found | {"status": "UNVERIFIED"})
        metadata = {
            "input_role": "retained-f1-receipt", "source_identity": "38a937fdf0b09f1330f26423dabb311399c8a4cf",
            "input_digest": "sha256:80f21e8fb7c9a76d466d749b0253f50bf8955112db0214386abbfcb9a9532ee1",
            "status": "FOUND", "reason": "structural-negative-only", "normalized_rows": found["normalized_rows"][:1],
        }
        self._role_error(BM_IDENTITY_INVALID, "normalized_rows", history.validate_entry, metadata)
        foreign = history.report_payload(baseline_id=BASELINE, study_id="retained-key-topk-real-v1",
                                         source_commit="a" * 40, current_raw_digest=DIGEST, entries=[found])
        self._role_error(BM_IDENTITY_INVALID, "entries", history.validate_report, foreign)
        # The optional F1/archive pins cannot be forged to reach their public
        # classifier branches. Exercise the shared typed-failure classification
        # on genuine PR15D bytes after the actual adapter has run instead.
        adapter = history.pr15d_aggregate_rows
        for code, reason in ((BM_UNSAFE_INPUT, "BM_UNSAFE_INPUT:path"),
                             (BM_IDENTITY_INVALID, "changed-during-read:BM_IDENTITY_INVALID")):
            with self.subTest(case="typed-owner-failure-keeps-candidate-digest", code=code):
                calls = []
                def fail_after_real_adapter(*args, **kwargs):
                    rows = adapter(*args, **kwargs)
                    self.assertEqual(len(rows), 32)
                    calls.append(True)
                    raise BenchError(code, "injected typed owner failure", field_path="path")
                with patch.object(history, "pr15d_aggregate_rows", side_effect=fail_after_real_adapter):
                    entry = history.classify_candidate(self.root, base)
                self.assertEqual(calls, [True])
                self.assertEqual((entry["status"], entry["reason"]), ("INVALID", reason))
                self.assertEqual(entry["input_digest"], _sha(payload))
                self.assertEqual(entry["normalized_rows"], [])
        for error in (TypeError("injected programmer error"), KeyError("injected programmer error"), MemoryError("injected programmer error")):
            with self.subTest(case="programmer-error-not-absence", error=type(error).__name__):
                with patch.object(history, "pr15d_aggregate_rows", side_effect=error):
                    with self.assertRaises(type(error)) as raised:
                        history.classify_candidate(self.root, base)
                self.assertIs(raised.exception, error)

    def test_s1f_t24_genuine_vertical_slice(self) -> None:
        from quervant_bench.config.codec import content_digest
        from quervant_bench.official import relative_effects as effects

        original = self._aggregate()
        authentic_bytes = original.read_bytes()
        candidate_path = self.root / "aggregate.json"
        candidate_path.write_bytes(authentic_bytes)
        catalog_before = tuple(history.CATALOG)
        entry = history.classify_candidate(self.root, self._role_candidate())
        self.assertEqual((entry["status"], entry["reason"]), ("FOUND", "authenticated-as-reported-summary"))
        self.assertEqual(history.validate_entry(entry), entry)
        rows = entry["normalized_rows"]
        self.assertEqual(len(rows), 32)
        expected_keys = {(f"pr15d_v1/{n}/{class_name}/k{k}", treatment)
                         for n in (10000, 100000) for class_name in ("absent", "rare", "medium", "common")
                         for k in (10, 100) for treatment in ("lucene", "tantivy")}
        keyed = {(row["lane_id"], row["treatment"]): row for row in rows}
        self.assertEqual(set(keyed), expected_keys)
        for row in rows:
            self.assertEqual((row["regime"], row["evidence_level"], row["method_id"]),
                             ("warm", "AS_REPORTED", "historical-three-trial-python-round6-v1"))
            self.assertEqual(row["run_id"], "20261031T005545Z-40a9c26a57aa23640904075e77be956ee52718bc")
            self.assertEqual(row["source_commit"], "40a9c26a57aa23640904075e77be956ee52718bc")
            self.assertEqual(row["input_digest"], "sha256:c9e8ed722aefc4fef43837a5511c2c88575287497b449f68f82f7ea0c251b257")
        for treatment, ratio, gain in (("tantivy", "0.045566", "95.4434"), ("lucene", "1.068173", "-6.8173")):
            self.assertEqual((keyed[("pr15d_v1/10000/absent/k10", treatment)]["ratio"],
                              keyed[("pr15d_v1/10000/absent/k10", treatment)]["gain_percent"]), (ratio, gain))
        report, disclosure, kwargs = self._role_disclosures([entry])
        self.assertEqual(history.validate_report(report), report)
        self.assertEqual(effects.validate_disclosure(disclosure), disclosure)
        self.assertEqual(len(disclosure["comparisons"]), 32)
        self.assertTrue(all(item["comparability"] == "NOT_COMPARABLE" for item in disclosure["comparisons"]))
        self.assertTrue(all(item["effect_change_percentage_points"] is None for item in disclosure["comparisons"]))
        files_before = {name: (self.root / name).read_bytes() for name in ("aggregate.json", "history-report.json", "relative-effects.json")}
        reopened = history._open_baseline_disclosure_documents(**kwargs)
        self.assertEqual(reopened, {
            "history_report_digest": content_digest(report), "relative_effects_digest": content_digest(disclosure),
            "history_report_path": self.root / "history-report.json", "relative_effects_path": self.root / "relative-effects.json",
            "statuses": ["FOUND"],
        })
        parsed_report = json.loads(files_before["history-report.json"])
        parsed_disclosure = json.loads(files_before["relative-effects.json"])
        self.assertEqual(history.validate_report(parsed_report), report)
        self.assertEqual(effects.validate_disclosure(parsed_disclosure), disclosure)
        self.assertEqual([effects.row_digest(row) for row in parsed_report["entries"][0]["normalized_rows"]],
                         [effects.row_digest(row) for row in rows])
        self.assertEqual({name: (self.root / name).read_bytes() for name in files_before}, files_before)
        self.assertEqual(original.read_bytes(), authentic_bytes)
        self.assertEqual(tuple(history.CATALOG), catalog_before)


def effects_gain(ratio) -> str:
    from quervant_bench.official import relative_effects

    return relative_effects.gain_percent(ratio, "lower")


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
