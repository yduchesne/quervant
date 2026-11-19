"""BM09-CURRENT-BASELINE-1 T01-T03: proportional relative effects."""

from __future__ import annotations

import unittest

from quervant_bench.config.errors import BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.official import relative_effects as effects

DIGEST = "sha256:" + "1" * 64


def _row(**overrides):
    values = dict(
        study_id="retained-key-topk-real-v1",
        run_id="11111111-1111-4111-8111-111111111111",
        campaign_id="d3c-v3r3-strategies-01",
        lane_id="u07/n10000_s4/common/k10",
        metric="latency",
        unit="ns",
        regime="warm",
        direction="lower",
        baseline="A",
        treatment="L",
        method_id=effects.RETAINED_METHOD_ID,
        ratio="1.200000",
        uncertainty={"low": "1.1", "high": "1.3", "seed": 9},
        decision=effects.RETAINED_DECISION,
        evidence_level=effects.EVIDENCE_RECOMPUTED,
        source_commit="a" * 40,
        host_environment="wsl2",
        host_identity="coding-host",
        input_digest=DIGEST,
        uncertainty_method="paired-slot-bootstrap-v1",
    )
    values.update(overrides)
    return effects.effect_row(**values)


class GainTests(unittest.TestCase):
    def test_t01_latency_reduction_is_not_a_reciprocal_speedup(self) -> None:
        self.assertEqual(effects.gain_percent("1.2", "lower"), "-20.000000")
        # 1/1.2 throughput gain is +20%, not the 16.67% latency reduction.
        self.assertEqual(effects.gain_percent("1.2", "higher"), "20.000000")
        self.assertEqual(effects.gain_percent("0.833333", "lower"), "16.666700")

    def test_t01_gain_direction_and_exact_signs(self) -> None:
        self.assertEqual(effects.gain_percent("1", "lower"), "0.000000")
        self.assertEqual(effects.gain_percent("0.75", "lower"), "25.000000")
        self.assertEqual(effects.gain_percent("0.75", "higher"), "-25.000000")

    def test_t01_invalid_ratios_are_rejected(self) -> None:
        for value in (0, -1, "0", "NaN", "Infinity", True, None, [1]):
            with self.subTest(value=value):
                with self.assertRaises(BenchError) as raised:
                    effects.gain_percent(value, "lower")
                self.assertIn(raised.exception.code, (BM_UNSAFE_INPUT, BM_SCHEMA_INVALID))
        with self.assertRaises(BenchError):
            effects.gain_percent("1.1", "sideways")

    def test_t01_canonical_decimal_is_fixed_precision(self) -> None:
        self.assertEqual(effects.canonical_decimal(effects.decimal_value("2", "r") / 3), "0.666667")
        self.assertEqual(effects.canonical_decimal(effects.signed_decimal("-0.0000004", "r")), "0.000000")


class EffectChangeTests(unittest.TestCase):
    def test_t02_twenty_to_ten_percent_is_ten_points_of_narrowing(self) -> None:
        historical = effects.gain_percent("1.2", "lower")  # -20 % latency change
        current = effects.gain_percent("1.1", "lower")  # -10 %
        self.assertEqual(
            effects.effect_change_percentage_points(current, historical), "10.000000"
        )
        self.assertEqual(
            effects.effect_change_percentage_points(historical, current), "-10.000000"
        )

    def test_t02_scale_change_preserves_the_effect(self) -> None:
        # Multiplying both arms by the same factor leaves the ratio, and therefore
        # the effect, unchanged: effects are scale-invariant.
        self.assertEqual(
            effects.effect_change_percentage_points(
                effects.gain_percent("1.20", "lower"),
                effects.gain_percent("1.20", "lower"),
            ),
            "0.000000",
        )

    def test_t02_comparison_rows_never_carry_absolute_times(self) -> None:
        historical = _row(source_commit="b" * 40, host_identity="historical-host")
        current = _row(ratio="1.100000")
        comparison = effects.compare_effect_rows(
            historical_rows=[historical], current_rows=[current]
        )[0]
        effects.validate_comparison(comparison)
        self.assertEqual(set(comparison), set(effects.COMPARISON_KEYS))
        self.assertFalse(
            any("ns" in str(key) or "median" in str(key) for key in comparison)
        )
        self.assertEqual(comparison["comparability"], "CONTEXT_CHANGED")
        self.assertEqual(comparison["effect_change_percentage_points"], "10.000000")
        self.assertIn("host-identity", comparison["context_changes"])
        self.assertIn("source-commit", comparison["context_changes"])


class ComparabilityTests(unittest.TestCase):
    def test_t03_different_platform_is_context_not_rejection(self) -> None:
        historical = _row(host_environment="native-linux", host_identity="linux-host")
        current = _row(host_environment="wsl2", host_identity="wsl-host")
        comparison = effects.compare_effect_rows(
            historical_rows=[historical], current_rows=[current]
        )[0]
        self.assertEqual(comparison["comparability"], "CONTEXT_CHANGED")
        self.assertEqual(comparison["effect_change_percentage_points"], "0.000000")

    def test_t03_identical_context_is_comparable(self) -> None:
        row = _row()
        comparison = effects.compare_effect_rows(
            historical_rows=[row], current_rows=[row]
        )[0]
        self.assertEqual(comparison["comparability"], "COMPARABLE")
        self.assertEqual(comparison["context_changes"], [])
        self.assertEqual(comparison["effect_change_percentage_points"], "0.000000")

    def test_t03_changed_semantics_are_not_comparable(self) -> None:
        for change in (
            {"metric": "throughput", "direction": "higher", "unit": "ops/s"},
            {"method_id": effects.CROSS_ENGINE_METHOD_ID},
            {"baseline": "L", "treatment": "A"},
            {"lane_id": "u07/n100000_s4/common/k10"},
            {"regime": "process_cold"},
        ):
            with self.subTest(change=change):
                historical = _row(**change)
                comparison = effects.compare_effect_rows(
                    historical_rows=[historical], current_rows=[_row()]
                )[0]
                self.assertEqual(comparison["comparability"], "NOT_COMPARABLE")
                self.assertIsNone(comparison["effect_change_percentage_points"])
                self.assertIsNone(comparison["current_row_digest"])

    def test_t03_missing_current_row_is_not_comparable(self) -> None:
        comparison = effects.compare_effect_rows(
            historical_rows=[_row(lane_id="u07/n1_s4/rare/k1")], current_rows=[_row()]
        )[0]
        self.assertEqual(comparison["comparability"], "NOT_COMPARABLE")
        self.assertEqual(comparison["context_changes"], ["no-current-row"])


class RowShapeTests(unittest.TestCase):
    def test_rows_have_the_exact_closed_shape(self) -> None:
        row = _row()
        self.assertEqual(set(row), set(effects.ROW_KEYS))
        self.assertEqual(row["ratio"], "1.200000")
        self.assertEqual(row["gain_percent"], "-20.000000")
        self.assertEqual(row["uncertainty"]["method"], "paired-slot-bootstrap-v1")
        effects.validate_row(row)

    def test_tampered_gain_is_rejected(self) -> None:
        row = _row()
        row["gain_percent"] = "-19.000000"
        with self.assertRaises(BenchError) as raised:
            effects.validate_row(row)
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

    def test_duplicate_coordinates_are_rejected(self) -> None:
        row = _row()
        with self.assertRaises(BenchError) as raised:
            effects.unique_rows([row, dict(row)])
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

    def test_bad_evidence_level_and_interval_are_rejected(self) -> None:
        with self.assertRaises(BenchError):
            _row(evidence_level="GUESSED")
        with self.assertRaises(BenchError):
            _row(uncertainty={"low": "1.3", "high": "1.1", "seed": 1})
        with self.assertRaises(BenchError):
            _row(uncertainty={"low": "1.1", "high": "1.3", "seed": True})


class ProjectionTests(unittest.TestCase):
    def _lanes(self) -> dict:
        lanes = {}
        for index in range(72):
            lane_id = f"u07/n{10000 if index % 2 else 100000}_s4/class{index % 4}/k{index + 1}"
            lanes[lane_id] = {
                "id": lane_id,
                "campaigns": {
                    "d3c-v3r3-strategies-01": {
                        f"R_{num}_{den}": "1.100000"
                        for num, den in effects.RETAINED_COMPARISONS
                    },
                    "d3c-v3r3-strategies-02": {
                        f"R_{num}_{den}": "1.200000"
                        for num, den in effects.RETAINED_COMPARISONS
                    },
                },
            }
            for campaign in lanes[lane_id]["campaigns"].values():
                for num, den in effects.RETAINED_COMPARISONS:
                    campaign[f"CI_{num}_{den}"] = {"low": "1.0", "high": "1.3", "seed": 3}
        return lanes

    def test_retained_projection_emits_every_paired_effect(self) -> None:
        rows = effects.retained_effect_rows(
            study_id="retained-key-topk-real-v1",
            run_id="11111111-1111-4111-8111-111111111111",
            lanes=self._lanes(),
            input_digest=DIGEST,
            source_commit="a" * 40,
            host_environment="wsl2",
            host_identity="host",
        )
        self.assertEqual(len(rows), 72 * 2 * 6)
        effects.unique_rows(rows)
        pairs = {(row["baseline"], row["treatment"]) for row in rows}
        self.assertEqual(
            pairs, {(den, num) for num, den in effects.RETAINED_COMPARISONS}
        )
        self.assertTrue(all(row["direction"] == "lower" for row in rows))
        self.assertTrue(all(row["decision"] == effects.RETAINED_DECISION for row in rows))

    def test_cross_engine_projection_uses_quervant_as_baseline(self) -> None:
        analysis_lanes = [
            {
                "lane_id": f"u07/n10000_s4/class{index}/k10",
                "comparisons": [
                    {"comparator": "lucene", "ratio": "1.050000"},
                    {"comparator": "tantivy", "ratio": "0.950000"},
                ],
            }
            for index in range(16)
        ]
        rows = effects.cross_engine_effect_rows(
            study_id="cross-engine-keyword-real-v1",
            run_id="22222222-2222-4222-8222-222222222222",
            analysis_lanes=analysis_lanes,
            input_digest=DIGEST,
            source_commit="a" * 40,
            host_environment="wsl2",
            host_identity="host",
        )
        self.assertEqual(len(rows), 32)
        self.assertTrue(all(row["baseline"] == "quervant" for row in rows))
        self.assertEqual({row["treatment"] for row in rows}, {"lucene", "tantivy"})
        self.assertTrue(all(row["decision"] == effects.CROSS_ENGINE_DECISION for row in rows))
        self.assertTrue(all(row["uncertainty"] is None for row in rows))

    def test_disclosure_roundtrip_and_binding(self) -> None:
        document = effects.disclosure_payload(
            baseline_id="33333333-3333-4333-8333-333333333333",
            study_id="retained-key-topk-real-v1",
            source_commit="a" * 40,
            current_raw_digest=DIGEST,
            rows=[_row()],
            comparisons=[
                effects.compare_effect_rows(historical_rows=[_row()], current_rows=[_row()])[0]
            ],
        )
        self.assertEqual(effects.validate_disclosure(document)["rows"][0]["ratio"], "1.200000")
        document["rows"][0]["ratio"] = "9.999999"
        with self.assertRaises(BenchError):
            effects.validate_disclosure(document)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
