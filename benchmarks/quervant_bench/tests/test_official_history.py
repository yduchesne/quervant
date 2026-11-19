"""BM09-CURRENT-BASELINE-1 T04: bounded historical inputs and disclosures."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BenchError
from quervant_bench.official import history
from quervant_bench.official.policy_inputs import HISTORICAL_ARCHIVE_DIGESTS

DIGEST = "sha256:" + "1" * 64
BASELINE = "33333333-3333-4333-8333-333333333333"
STUDY = "retained-key-topk-real-v1"


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
        self.assertEqual(entries[0]["status"], history.STATUS_UNVERIFIED)
        self.assertEqual(entries[0]["reason"], "no-independent-raw-digest")

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
        from quervant_bench.official import relative_effects as effects

        lanes = {}
        for lane_id in effects.lane_ids(effects.STUDY_RETAINED_KEY):
            _prefix, n_text, class_name, k_text = lane_id.split("/")
            n, k = int(n_text), int(k_text[1:])
            campaigns = {}
            for campaign in history.RETAINED_CAMPAIGNS:
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
                for ratio_field, ci_field, _baseline, _treatment in effects.RETAINED_FIELDS:
                    record[ratio_field] = 0.8
                    record[ci_field] = {"low": 0.7, "high": 0.9, "seed": 11}
                campaigns[campaign] = record
            lanes[lane_id] = {
                "id": lane_id, "n": n, "class": class_name, "k": k, "campaigns": campaigns,
            }
        return {
            "schema": history.RETAINED_ANALYSIS_SCHEMA,
            "protocol_sha256": "sha256:" + history.RETAINED_PROTOCOL,
            "series": list(history.RETAINED_CAMPAIGNS),
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
        self.assertEqual(entry["status"], history.STATUS_UNAVAILABLE)
        self.assertEqual(entry["reason"], "not-found")

    def test_replacement_with_identical_bytes_is_rejected(self) -> None:
        payload = b'{"schema":"x"}'
        target = self.root / "real.json"
        target.write_bytes(payload)
        original = history._observe

        calls = {"count": 0}

        def replace_after_first(root, relative, *, max_bytes):
            result = original(root, relative, max_bytes=max_bytes)
            calls["count"] += 1
            if calls["count"] == 1:
                target.unlink()
                target.write_bytes(payload)
            return result

        anchor = history.SUPPORTED_SOURCES[("pr15d-aggregate", history.PR15D_AGGREGATE_RUN)]
        original_observe = history._observe
        history._observe = replace_after_first
        try:
            entry = history.classify_candidate(
                self.root, self._cross_candidate("real.json", anchor)
            )
        finally:
            history._observe = original_observe
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
            history._observe(self.root, "ok.json", max_bytes=len(ok) - 1)
        self.assertEqual(history._observe(self.root, "ok.json", max_bytes=len(ok))[1][:7], "sha256:")
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
        observed = history.open_verified_baseline_disclosures(
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
            history.open_verified_baseline_disclosures(
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
            history.open_verified_baseline_disclosures(
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
        history._read_t6(receipt, digest, history.record_for("retained-t6-receipt", history.RETAINED_T6))
        for field, value in (
            ("schema", "other"),
            ("protocol_sha256", "0" * 64),
            ("t6_commit", "0" * 40),
            ("control_name", "other"),
            ("campaign_names", list(reversed(history.RETAINED_CAMPAIGNS))),
            ("tooling_manifest_sha256", "0" * 64),
            ("protected_files", {"../escape": "a" * 64}),
            ("receipt_origin", "current-baseline-v2"),
        ):
            with self.subTest(field=field):
                broken = dict(receipt)
                broken[field] = value
                with self.assertRaises(BenchError):
                    history._read_t6(
                        broken,
                        digest,
                        history.record_for("retained-t6-receipt", history.RETAINED_T6),
                    )

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
            history._read_micro({"schema": "pr15i-d3c-micro-v1"})

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
        observed = history.open_verified_baseline_disclosures(
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
                    history.open_verified_baseline_disclosures(**kwargs)
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_missing_disclosure_is_unavailable(self) -> None:
        self._write()
        (self.root / "relative-effects.json").unlink()
        with self.assertRaises(BenchError) as raised:
            history.open_verified_baseline_disclosures(
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
            history.open_verified_baseline_disclosures(
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


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
