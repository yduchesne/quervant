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

    def test_t04_committed_pr15d_aggregate_is_an_authentic_reported_summary(self) -> None:
        from quervant_bench.tests import official_support as support

        aggregate = support.REPO_ROOT / "benchmarks/reports/pr15d/pr15d-qualified.json"
        if not aggregate.is_file():  # pragma: no cover - repository checkout only
            self.skipTest("committed PR15D aggregate not available")
        self.assertEqual(
            history.raw_digest(aggregate),
            history.SUPPORTED_SOURCES[("pr15d-aggregate", "20261031T005545Z-40a9c26a57aa23640904075e77be956ee52718bc")],
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
