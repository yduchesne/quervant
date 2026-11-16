"""AN-HIST-01…06: read-only historical D3-C/T7 separation.

The authentic external archive is absent from a clean checkout, so the honest
result is ``EVIDENCE_UNAVAILABLE``. These tests prove that the historical
arithmetic surfaces are separately identified, that the primary package never
imports them, and that no historical or official verdict is ever fabricated.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from quervant_bench.analysis.arithmetic import arm_block_value, median_paired_ratios
from quervant_bench.analysis.bootstrap import legacy_percentile_indexes
from quervant_bench.analysis.history import (
    ARCHIVE_RELATIVE_ROOT,
    LEGACY_ABSOLUTE_TOLERANCE,
    PARITY_NOT_EXECUTED,
    PARITY_NOT_YET_MIGRATED,
    STATUS_PRESENT,
    STATUS_UNAVAILABLE,
    arithmetic_only_ratio,
    decimal_from_historical,
    inspect_archive,
    legacy_floor_mean_slot_medians,
    legacy_t7_compatibility_calculate,
    legacy_within_tolerance,
    run_legacy_verifier,
)
from quervant_bench.config.errors import BM_SCHEMA_INVALID, BenchError
from quervant_bench.tests.analysis_support import experiment_root  # noqa: F401

ANALYSIS_DIR = Path(__file__).resolve().parents[1] / "analysis"
REPO_ROOT = Path(__file__).resolve().parents[4]


class ArchiveAvailabilityTests(unittest.TestCase):
    """AN-HIST-03, AN-HIST-04 and AN-HIST-05."""

    def test_an_hist_03_missing_archive_is_explicitly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            status = inspect_archive(Path(temporary) / "pr15i-d3-c")
        self.assertEqual(status.status, STATUS_UNAVAILABLE)
        self.assertFalse(status.available)
        lines = status.report_lines()
        self.assertIn("STATUS=EVIDENCE_UNAVAILABLE", lines)
        self.assertIn("HISTORICAL_SERIES_VERIFIED=NO", lines)
        self.assertIn(f"NUMERIC_PARITY={PARITY_NOT_EXECUTED}", lines)
        self.assertIn("REASON=required authentic external archive not present", lines)
        self.assertTrue(any("BM-07/BM-09" in line for line in lines))

    def test_an_hist_03_empty_archive_directory_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pr15i-d3-c"
            root.mkdir()
            status = inspect_archive(root)
        self.assertEqual(status.status, STATUS_UNAVAILABLE)
        self.assertEqual(status.entry_count, 0)

    def test_an_hist_03_present_archive_never_claims_verified_parity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pr15i-d3-c"
            root.mkdir()
            (root / "series-a").mkdir()
            status = inspect_archive(root)
            self.assertEqual(status.status, STATUS_PRESENT)
            self.assertNotIn("STATUS=PASS", status.report_lines())
            self.assertIn(
                "HISTORICAL_SERIES_VERIFIED=PENDING_ORIGINAL_VERIFIER",
                status.report_lines(),
            )

    def test_an_hist_04_no_forged_official_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            status = inspect_archive(Path(temporary) / "absent")
        rendered = json.dumps({"lines": list(status.report_lines())})
        for forbidden in ("ACCEPTED", "PASS", "OFFICIAL", "VERIFIED=YES"):
            self.assertNotIn(forbidden, rendered)

    def test_an_hist_05_verifier_is_never_invoked_without_an_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            outcome = run_legacy_verifier(
                Path(temporary) / "absent", repo_root=REPO_ROOT
            )
        self.assertEqual(outcome["status"], STATUS_UNAVAILABLE)
        self.assertIsNone(outcome["returncode"])

    def test_an_hist_05_archive_root_must_not_be_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "real"
            target.mkdir()
            link = Path(temporary) / "link"
            link.symlink_to(target)
            with self.assertRaises(BenchError):
                inspect_archive(link)

    def test_an_hist_archive_relative_root_is_the_documented_path(self) -> None:
        self.assertEqual(ARCHIVE_RELATIVE_ROOT, "target/pr15i-d3-c")


class LegacyArithmeticTests(unittest.TestCase):
    """AN-HIST-01 and AN-HIST-02."""

    def test_an_hist_01_floor_mean_differs_from_the_new_exact_mean(self) -> None:
        self.assertEqual(legacy_floor_mean_slot_medians([10, 15]), 12)
        self.assertEqual(arm_block_value([Decimal(10), Decimal(15)]), Decimal("12.5"))
        with self.assertRaises(BenchError) as caught:
            legacy_floor_mean_slot_medians([0])
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

    def test_an_hist_01_historical_ratio_is_ratio_of_arm_medians(self) -> None:
        board = {
            1: {"A": [10], "P": [10]},
            2: {"A": [20], "P": [50]},
            3: {"A": [100], "P": [50]},
        }
        result = legacy_t7_compatibility_calculate(
            board,
            cap=Decimal("1.5"),
            minimum_retained_blocks=1,
            historical_protocol_sha="f" * 64,
            campaign_name="series",
            lane_id="lane",
            numerator="P",
            denominator="A",
            resamples=1000,
        )
        self.assertEqual(result.retained_blocks, (1, 2, 3))
        self.assertEqual(format(result.ratio, "f"), "2.5")
        self.assertEqual(
            format(median_paired_ratios(
                (
                    (1, Decimal(10), Decimal(10)),
                    (2, Decimal(20), Decimal(50)),
                    (3, Decimal(100), Decimal(50)),
                ),
                "lower-is-better",
            ), "f"),
            "1",
        )
        self.assertNotEqual(result.ratio, median_paired_ratios(
            (
                (1, Decimal(10), Decimal(10)),
                (2, Decimal(20), Decimal(50)),
                (3, Decimal(100), Decimal(50)),
            ),
            "lower-is-better",
        ))
        self.assertEqual(
            legacy_percentile_indexes(result.resamples), (24, 974)
        )

    def test_an_hist_01_historical_seed_identity_and_exclusion(self) -> None:
        board = {
            1: {"A": [10, 10], "P": [10, 10]},
            2: {"A": [10, 16], "P": [10, 10]},
            3: {"A": [10, 10], "P": [10, 10]},
            4: {"A": [10, 10], "P": [10, 10]},
        }
        result = legacy_t7_compatibility_calculate(
            board,
            cap=Decimal("1.5"),
            minimum_retained_blocks=3,
            historical_protocol_sha="a" * 64,
            campaign_name="series",
            lane_id="lane",
            numerator="P",
            denominator="A",
            resamples=1000,
        )
        self.assertEqual(result.retained_blocks, (1, 3, 4))
        self.assertEqual(result.excluded_blocks, (2,))
        self.assertEqual(result.trigger_arms, ((2, ("A",)),))
        self.assertEqual(
            result.seed,
            int.from_bytes(
                hashlib.sha256(f"{'a' * 64}|series|lane|P/A".encode()).digest()[:8],
                "big",
            ),
        )
        document = result.to_document()
        self.assertEqual(document["arithmetic_id"], "legacy-t7-compatibility-v1")
        self.assertNotIn("PASS", json.dumps(document))
        self.assertNotIn("official", json.dumps(document).lower())

    def test_an_hist_01_historical_lane_below_the_minimum_rejects(self) -> None:
        board = {
            1: {"A": [10, 10], "P": [10, 10]},
            2: {"A": [10, 16], "P": [10, 10]},
        }
        with self.assertRaises(BenchError):
            legacy_t7_compatibility_calculate(
                board,
                cap=Decimal("1.5"),
                minimum_retained_blocks=3,
                historical_protocol_sha="a" * 64,
                campaign_name="series",
                lane_id="lane",
                numerator="P",
                denominator="A",
            )

    def test_an_hist_02_numeric_parity_tolerance_is_absolute_one_e_nine(self) -> None:
        self.assertEqual(LEGACY_ABSOLUTE_TOLERANCE, Decimal("0.000000001"))
        self.assertTrue(legacy_within_tolerance(0.8, "0.8000000005"))
        self.assertFalse(legacy_within_tolerance(0.8, "0.800000002"))
        self.assertTrue(legacy_within_tolerance(1, 1))
        self.assertEqual(decimal_from_historical(0.1), Decimal("0.1"))
        self.assertEqual(decimal_from_historical("1.25"), Decimal("1.25"))
        with self.assertRaises(BenchError):
            decimal_from_historical(True)
        with self.assertRaises(BenchError):
            decimal_from_historical(float("nan"))
        with self.assertRaises(BenchError):
            decimal_from_historical(object())

    def test_an_hist_02_arithmetic_only_ratio_never_applies_policy(self) -> None:
        self.assertEqual(
            format(arithmetic_only_ratio(80, 100, "lower-is-better"), "f"), "0.8"
        )
        self.assertEqual(
            format(arithmetic_only_ratio(125, 100, "higher-is-better"), "f"), "0.8"
        )
        with self.assertRaises(BenchError):
            arithmetic_only_ratio(0, 100)
        self.assertNotIn(
            "evaluate_policy",
            (ANALYSIS_DIR / "history.py").read_text(encoding="utf-8"),
        )


class HistoricalIsolationTests(unittest.TestCase):
    """AN-HIST-06: the primary package never routes through the history helper."""

    def test_an_hist_06_primary_modules_do_not_import_history(self) -> None:
        for name in (
            "derive.py",
            "policy.py",
            "profiles.py",
            "bootstrap.py",
            "pruning.py",
            "aggregation.py",
            "arithmetic.py",
            "contracts.py",
        ):
            source = (ANALYSIS_DIR / name).read_text(encoding="utf-8")
            with self.subTest(module=name):
                self.assertNotIn("from .history", source)
                self.assertNotIn("import history", source)
                self.assertNotIn("legacy_t7_compatibility_calculate", source)
        # ``bootstrap.py`` owns the isolated legacy helper by design, but the new
        # algorithm is the only one ``bootstrap_interval`` can produce.
        bootstrap_source = (ANALYSIS_DIR / "bootstrap.py").read_text(encoding="utf-8")
        interval_body = bootstrap_source[
            bootstrap_source.index("def bootstrap_interval(") :
            bootstrap_source.index("# Historical-only compatibility helper")
        ]
        self.assertIn("ALGORITHM_SHA256_REJECTION", interval_body)
        self.assertNotIn("ALGORITHM_LEGACY_RANDOM", interval_body)
        self.assertNotIn("Random(", interval_body)

    def test_an_hist_06_migration_status_is_explicit(self) -> None:
        self.assertIn("BM-07", PARITY_NOT_YET_MIGRATED)
        status = inspect_archive(REPO_ROOT / ARCHIVE_RELATIVE_ROOT)
        # The archive directory may exist but is empty in a clean checkout.
        self.assertIn(status.status, {STATUS_UNAVAILABLE, STATUS_PRESENT})
        self.assertIn("STATUS=EVIDENCE_UNAVAILABLE", status.report_lines())


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    unittest.main()
