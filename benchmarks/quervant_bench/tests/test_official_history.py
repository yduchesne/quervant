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
            (self._inventory([self._candidate(expected_digest="deadbeef")]), BM_SCHEMA_INVALID),
            (
                self._inventory([self._candidate(input_role="retained-archive", expected_digest=None)]),
                BM_IDENTITY_INVALID,
            ),
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

    def test_t04_authenticated_archive_is_found(self) -> None:
        campaign = sorted(HISTORICAL_ARCHIVE_DIGESTS)[0]
        payload = b"authentic-archive"
        digest = _sha(payload)
        (self.root / f"{campaign}.tar.gz").write_bytes(payload)
        original = HISTORICAL_ARCHIVE_DIGESTS[campaign]
        HISTORICAL_ARCHIVE_DIGESTS[campaign] = digest
        try:
            entries = history.build_entries(
                self.root,
                self._inventory(
                    {
                        "family": "retained-key",
                        "input_role": "retained-archive",
                        "path": f"{campaign}.tar.gz",
                        "source_identity": campaign,
                        "expected_digest": digest,
                    }
                ),
            )
        finally:
            HISTORICAL_ARCHIVE_DIGESTS[campaign] = original
        self.assertEqual(entries[0]["status"], history.STATUS_FOUND)
        self.assertEqual(entries[0]["input_digest"], digest)

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

        document = json.loads(
            (support.REPO_ROOT / "benchmarks/reports/pr15d/pr15d-qualified.json").read_text()
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
            json.loads(
                (support.REPO_ROOT / "benchmarks/reports/pr15d/pr15d-qualified.json").read_text()
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
        self.assertEqual(entries[0]["reason"], "unsupported-source-identity")

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
        self.assertEqual(entries[0]["reason"], "unsafe-path")
        self.assertTrue(entries[1]["reason"].startswith("unsafe-read:"))
        self.assertEqual(entries[2]["reason"], "unsafe-path")


class RetainedAnalysisAdapterTests(unittest.TestCase):
    """Schema-level projection test; this is not an authenticated historical positive."""

    def _document(self):
        from quervant_bench.official import relative_effects as effects

        lanes = {}
        for lane_id in effects.lane_ids(effects.STUDY_RETAINED_KEY):
            campaigns = {}
            for campaign in history.RETAINED_CAMPAIGNS:
                record = {"retained": [1, 2, 3, 4], "retained_count": 4}
                for ratio_field, ci_field, _baseline, _treatment in effects.RETAINED_FIELDS:
                    record[ratio_field] = "0.8"
                    record[ci_field] = {"low": "0.7", "high": "0.9", "seed": 11}
                campaigns[campaign] = record
            lanes[lane_id] = {"id": lane_id, "campaigns": campaigns}
        return {
            "schema": history.RETAINED_ANALYSIS_SCHEMA,
            "series": list(history.RETAINED_CAMPAIGNS),
            "lanes": lanes,
        }

    def test_projection_yields_864_as_reported_rows(self) -> None:
        rows = history.retained_analysis_rows(
            self._document(), input_digest="sha256:" + "5" * 64
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
                    history.retained_analysis_rows(document, input_digest=digest)


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
                    "input_role": "retained-micro",
                    "source_identity": "micro-05",
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
