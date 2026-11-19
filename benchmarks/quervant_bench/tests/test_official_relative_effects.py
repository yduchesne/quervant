"""BM09-CURRENT-BASELINE-1-F1 N01-N16: exact decimals and closed effect rows."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
import unittest

from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.official import relative_effects as effects

SHA = "sha256:" + "1" * 64
HOST = "sha256:" + "2" * 64
RUN = "11111111-1111-4111-8111-111111111111"
COMMIT = "a" * 40
CAMPAIGN = "d3c-v3r3-strategies-01"


def _row(**overrides):
    values = dict(
        study_id=effects.STUDY_RETAINED_KEY,
        run_id=RUN,
        campaign_id=CAMPAIGN,
        lane_id="pr15d_v1/10000/common/k10",
        metric="latency",
        unit="ns",
        regime="warm",
        direction="lower",
        baseline="A",
        treatment="L",
        method_id=effects.RETAINED_METHOD_ID,
        ratio="0.8",
        uncertainty={"low": "0.75", "high": "0.85", "seed": 7},
        decision=effects.RETAINED_DECISION,
        evidence_level=effects.EVIDENCE_RECOMPUTED,
        source_commit=COMMIT,
        host_environment="wsl2",
        host_identity=HOST,
        input_digest=SHA,
    )
    values.update(overrides)
    return effects.effect_row(**values)


class ExactDecimalTests(unittest.TestCase):
    """N01/N02: every accepted value reopens unchanged and keeps its exact gain."""

    def test_n01_literal_vectors(self) -> None:
        vectors = (
            (4 / 3, "lower", "1.3333333333333333", "-33.33333333333333"),
            (4 / 3, "higher", "1.3333333333333333", "33.33333333333333"),
            ("0.0000001", "lower", "0.0000001", "99.99999"),
            (
                "0.123456789012345678901234567890123456789",
                "lower",
                "0.123456789012345678901234567890123456789",
                "87.6543210987654321098765432109876543211",
            ),
            ("0.8", "lower", "0.8", "20"),
            ("1.2", "lower", "1.2", "-20"),
            (1, "lower", "1", "0"),
            (Decimal("+1.200000E+0"), "higher", "1.2", "20"),
        )
        for ratio, direction, expected_ratio, expected_gain in vectors:
            with self.subTest(ratio=ratio, direction=direction):
                self.assertEqual(effects.normalize_ratio(ratio), expected_ratio)
                self.assertEqual(effects.gain_percent(ratio, direction), expected_gain)
                self.assertEqual(
                    effects.gain_percent(effects.stored_ratio(expected_ratio), direction),
                    expected_gain,
                )
                effects.stored_derived(expected_gain)
                rational = Fraction(str(ratio))
                oracle = (
                    Fraction(100) * (1 - rational)
                    if direction == "lower"
                    else Fraction(100) * (rational - 1)
                )
                self.assertEqual(Fraction(expected_gain), oracle)

    def test_n02_percentage_point_differences_are_exact(self) -> None:
        self.assertEqual(effects.effect_change_percentage_points("10", "20"), "-10")
        self.assertEqual(effects.effect_change_percentage_points("-10", "-20"), "10")
        self.assertEqual(
            effects.effect_change_percentage_points("0.0000004", "0.0000003"), "0.0000001"
        )
        self.assertNotEqual(
            effects.effect_change_percentage_points("0.0000004", "0.0000003"),
            effects.effect_change_percentage_points("0.000000", "0.000000"),
        )

    def test_n02_signed_zero_and_bounds(self) -> None:
        self.assertEqual(effects.normalize_derived(Decimal("0E-999999")), "0")
        self.assertEqual(effects.effect_change_percentage_points(Decimal("0E-999999"), "0"), "0")
        self.assertEqual(effects.normalize_ratio("1e128"), "1" + "0" * 128)
        self.assertEqual(effects.normalize_ratio("1e-128"), "0." + "0" * 127 + "1")
        self.assertEqual(
            Fraction(effects.gain_percent("1e128", "lower")), 100 * (1 - Fraction("1e128"))
        )

    def test_n03_invalid_producer_input_is_unsafe(self) -> None:
        for value in (
            False,
            True,
            0,
            -1,
            "0",
            "-0",
            "NaN",
            "Infinity",
            float("inf"),
            Decimal("sNaN"),
            [],
            None,
            " 1.2",
            "1_000",
            "1e129",
            "1e-129",
            "1e1000",
            "1." + "7" * 128,
            "1" * 1025,
            1 << 1801,
        ):
            with self.subTest(value=str(value)[:24]):
                with self.assertRaises(BenchError) as raised:
                    effects.normalize_ratio(value)
                self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_n04_stored_form_must_already_be_canonical(self) -> None:
        for value in (1, 1.2, "1.200000", "+1.2", "1.2e0", "01.2"):
            with self.subTest(value=value):
                with self.assertRaises(BenchError) as raised:
                    effects.stored_ratio(value)
                self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

    def test_n05_presentation_rounding_is_isolated(self) -> None:
        self.assertEqual(effects.render_six("1.2345665"), "1.234566")
        self.assertEqual(effects.render_six("1.2345675"), "1.234568")
        self.assertEqual(effects.render_six("-0.0000004"), "0.000000")


class IntervalTests(unittest.TestCase):
    """N02/N09/N10: original endpoints decide validity, not their rendering."""

    def test_n09_inverted_close_interval_is_rejected_before_rendering(self) -> None:
        with self.assertRaises(BenchError) as raised:
            effects.interval_endpoints("1.0000004", "1.0000003")
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)
        self.assertEqual(
            effects.interval_endpoints("1.0000003", "1.0000004"),
            {"low": "1.0000003", "high": "1.0000004"},
        )

    def test_n10_seed_bounds_and_round_trip(self) -> None:
        ci = effects._uncertainty(
            {"low": "0.8000000001", "high": "0.9000000002", "seed": 2**64 - 1},
            "paired-slot-bootstrap-v1",
        )
        self.assertEqual(
            ci,
            {
                "low": "0.8000000001",
                "high": "0.9000000002",
                "method": "paired-slot-bootstrap-v1",
                "seed": 18446744073709551615,
            },
        )
        self.assertEqual(effects._stored_uncertainty(ci), ci)
        for seed in (True, False, -1, 1.0, 2**64):
            with self.subTest(seed=seed):
                with self.assertRaises(BenchError) as raised:
                    effects._uncertainty({"low": "0.8", "high": "0.9", "seed": seed}, "m")
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


class RowContractTests(unittest.TestCase):
    def test_rows_have_the_closed_shape_and_exact_gain(self) -> None:
        row = _row()
        self.assertEqual(set(row), set(effects.ROW_KEYS))
        self.assertEqual(row["ratio"], "0.8")
        self.assertEqual(row["gain_percent"], "20")
        self.assertEqual(effects.validate_row(row)["uncertainty"], row["uncertainty"])

    def test_current_rows_require_real_identities(self) -> None:
        for overrides in (
            {"run_id": "not-a-uuid"},
            {"host_environment": None},
            {"host_environment": "native-linux-or-wsl2"},
            {"host_identity": "nickname"},
            {"source_commit": None},
            {"input_digest": "sha256:ABC"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(BenchError):
                    effects.validate_row(_row(**overrides))

    def test_unregistered_coordinates_are_rejected(self) -> None:
        for overrides in (
            {"lane_id": "u07/n10000_s4/class0/k10"},
            {"campaign_id": "d3c-v3r3-base-aa-01"},
            {"baseline": "B", "treatment": "H"},
            {"direction": "higher"},
            {"metric": "throughput", "unit": "ops/s"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(BenchError):
                    effects.validate_row(_row(**overrides))

    def test_tampered_gain_and_noncanonical_storage_are_rejected(self) -> None:
        row = _row()
        row["gain_percent"] = "21"
        with self.assertRaises(BenchError):
            effects.validate_row(row)
        row = _row()
        row["ratio"] = "0.80"
        with self.assertRaises(BenchError) as raised:
            effects.validate_row(row)
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

    def test_tampered_evidence_level_cannot_claim_recomputed(self) -> None:
        historical = _row(
            evidence_level=effects.EVIDENCE_AS_REPORTED,
            source_commit=None,
            host_environment=None,
            host_identity=None,
        )
        self.assertEqual(
            effects.validate_row(historical, current=False)["evidence_level"],
            effects.EVIDENCE_AS_REPORTED,
        )
        with self.assertRaises(BenchError):
            effects.validate_row(historical, current=True)

    def test_duplicate_identity_including_run_is_rejected(self) -> None:
        row = _row()
        with self.assertRaises(BenchError) as raised:
            effects.unique_rows([row, dict(row)])
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

    def test_ambiguous_current_coordinate_is_rejected_both_orders(self) -> None:
        first = _row(ratio="0.9", uncertainty={"low": "0.8", "high": "0.95", "seed": 1})
        second = _row(
            ratio="1.1",
            run_id="22222222-2222-4222-8222-222222222222",
            uncertainty={"low": "1.0", "high": "1.2", "seed": 2},
        )
        for rows in ([first, second], [second, first]):
            with self.subTest(order=[row["ratio"] for row in rows]):
                with self.assertRaises(BenchError):
                    effects.current_index(rows)


class RetainedOracleTests(unittest.TestCase):
    """N11: the literal A/L/P/H mapping, spelled out independently."""

    def test_literal_pairs_and_gains(self) -> None:
        # A=100, L=80, P=60, H=30 ns medians.
        arm = {"A": 100, "L": 80, "P": 60, "H": 30}
        expected = {
            ("A", "L"): "20",
            ("A", "P"): "40",
            ("A", "H"): "70",
            ("L", "P"): "25",
            ("L", "H"): "62.5",
            ("P", "H"): "50",
        }
        lanes = {}
        for index in range(72):
            lane_id = effects.lane_ids(effects.STUDY_RETAINED_KEY)[index]
            records = {}
            for campaign in ("d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02"):
                record = {}
                for ratio_field, ci_field, baseline, treatment in effects.RETAINED_FIELDS:
                    record[ratio_field] = str(
                        Decimal(arm[treatment]) / Decimal(arm[baseline])
                    )
                    record[ci_field] = {"low": "0.1", "high": "10", "seed": 5}
                record["filter_sensitive"] = False
                records[campaign] = record
            lanes[lane_id] = {"id": lane_id, "campaigns": records}
        rows = effects.retained_effect_rows(
            study_id=effects.STUDY_RETAINED_KEY,
            run_id=RUN,
            lanes=lanes,
            input_digest=SHA,
            source_commit=COMMIT,
            host_environment="wsl2",
            host_identity=HOST,
        )
        self.assertEqual(len(rows), 864)
        effects.unique_rows(rows)
        for row in rows:
            self.assertEqual(
                row["gain_percent"], expected[(row["baseline"], row["treatment"])]
            )
            self.assertEqual(row["decision"], effects.RETAINED_DECISION)

    def test_cross_engine_projection_uses_quervant_as_baseline(self) -> None:
        analysis_lanes = [
            {
                "lane_id": lane,
                "comparisons": [
                    {"comparator": "lucene", "ratio": "1.068173"},
                    {"comparator": "tantivy", "ratio": "0.045566"},
                ],
            }
            for lane in effects.lane_ids(effects.STUDY_CROSS_ENGINE)
        ]
        rows = effects.cross_engine_effect_rows(
            study_id=effects.STUDY_CROSS_ENGINE,
            run_id=RUN,
            analysis_lanes=analysis_lanes,
            input_digest=SHA,
            source_commit=COMMIT,
            host_environment="wsl2",
            host_identity=HOST,
        )
        self.assertEqual(len(rows), 32)
        effects.unique_rows(rows)
        tantivy = next(row for row in rows if row["treatment"] == "tantivy")
        lucene = next(row for row in rows if row["treatment"] == "lucene")
        self.assertEqual(tantivy["gain_percent"], "95.4434")
        self.assertEqual(lucene["gain_percent"], "-6.8173")
        self.assertTrue(all(row["uncertainty"] is None for row in rows))


class ComparisonTests(unittest.TestCase):
    def test_n12_identical_context_is_comparable(self) -> None:
        row = _row()
        comparison = effects.compare_effect_rows(historical_rows=[row], current_rows=[row])[0]
        self.assertEqual(comparison["comparability"], "COMPARABLE")
        self.assertEqual(comparison["context_changes"], [])
        self.assertEqual(comparison["effect_change_percentage_points"], "0")
        effects.validate_comparison(comparison)

    def test_n13_context_changes_keep_the_fixed_order(self) -> None:
        historical = _row(
            source_commit="b" * 40,
            host_environment="native-linux",
            host_identity="sha256:" + "3" * 64,
        )
        comparison = effects.compare_effect_rows(
            historical_rows=[historical], current_rows=[_row(ratio="0.75")]
        )[0]
        self.assertEqual(
            comparison["context_changes"],
            ["source-commit", "host-environment", "host-identity"],
        )
        self.assertEqual(comparison["comparability"], "CONTEXT_CHANGED")
        # 25 % current vs 20 % historical reduction is +5 points.
        self.assertEqual(comparison["effect_change_percentage_points"], "5")

    def test_n14_unknown_historical_context_is_flagged_not_invented(self) -> None:
        historical = _row(
            evidence_level=effects.EVIDENCE_AS_REPORTED,
            source_commit=None,
            host_environment=None,
            host_identity=None,
        )
        comparison = effects.compare_effect_rows(
            historical_rows=[historical], current_rows=[_row()]
        )[0]
        self.assertEqual(
            comparison["context_changes"],
            ["source-commit", "host-environment", "host-identity", "as-reported"],
        )

    def test_n15_different_method_is_not_comparable(self) -> None:
        historical = _row(
            method_id=effects.HISTORICAL_CROSS_METHOD_ID,
            study_id=effects.STUDY_CROSS_ENGINE,
            campaign_id="three-trial-backend",
            lane_id="pr15d_v1/10000/absent/k10",
            uncertainty=None,
            baseline="quervant",
            treatment="lucene",
            decision=effects.CROSS_ENGINE_DECISION,
            evidence_level=effects.EVIDENCE_AS_REPORTED,
        )
        current = _row(
            study_id=effects.STUDY_CROSS_ENGINE,
            method_id=effects.CROSS_ENGINE_METHOD_ID,
            campaign_id="three-trial-backend",
            lane_id="pr15d_v1/10000/absent/k10",
            uncertainty=None,
            baseline="quervant",
            treatment="lucene",
            decision=effects.CROSS_ENGINE_DECISION,
        )
        comparison = effects.compare_effect_rows(
            historical_rows=[historical], current_rows=[current]
        )[0]
        self.assertEqual(comparison["comparability"], "NOT_COMPARABLE")
        self.assertEqual(comparison["context_changes"], ["no-current-row"])
        self.assertIsNone(comparison["effect_change_percentage_points"])

    def test_n16_comparison_shape_is_closed(self) -> None:
        row = _row()
        comparison = effects.compare_effect_rows(historical_rows=[row], current_rows=[row])[0]
        self.assertEqual(set(comparison), set(effects.COMPARISON_KEYS))
        broken = dict(comparison)
        broken["context_changes"] = ["estimator"]
        broken["comparability"] = "CONTEXT_CHANGED"
        with self.assertRaises(BenchError):
            effects.validate_comparison(broken)
        broken = dict(comparison)
        broken["effect_change_percentage_points"] = "0.0"
        with self.assertRaises(BenchError):
            effects.validate_comparison(broken)


class DisclosureTests(unittest.TestCase):
    def test_envelope_has_eight_keys_and_binds_rows(self) -> None:
        document = effects.disclosure_payload(
            baseline_id="33333333-3333-4333-8333-333333333333",
            study_id=effects.STUDY_RETAINED_KEY,
            source_commit=COMMIT,
            current_raw_digest=SHA,
            rows=[],
        )
        self.assertEqual(len(document), 8)
        with self.assertRaises(BenchError):
            effects.validate_disclosure(document)  # incomplete row count

    def test_rows_from_another_study_or_raw_series_are_rejected(self) -> None:
        document = effects.disclosure_payload(
            baseline_id="33333333-3333-4333-8333-333333333333",
            study_id=effects.STUDY_CROSS_ENGINE,
            source_commit=COMMIT,
            current_raw_digest=SHA,
            rows=[],
        )
        document["rows"] = [
            _row(
                study_id=effects.STUDY_CROSS_ENGINE,
                campaign_id="three-trial-backend",
                lane_id="pr15d_v1/10000/absent/k10",
                uncertainty=None,
                baseline="quervant",
                treatment="lucene",
            )
        ] * 32
        with self.assertRaises(BenchError):
            effects.validate_disclosure(document)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
