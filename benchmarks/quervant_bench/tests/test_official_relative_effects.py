"""BM09-CURRENT-BASELINE-1-F1 N01-N16: exact decimals and closed effect rows."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from itertools import permutations
import json
import unittest

from quervant_bench.config.codec import content_digest
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.official import relative_effects as effects

SHA = "sha256:" + "1" * 64
HOST = "sha256:" + "2" * 64
RUN = "11111111-1111-4111-8111-111111111111"
COMMIT = "a" * 40
CAMPAIGN = "d3c-v3r3-strategies-01"
BASELINE = "33333333-3333-4333-8333-333333333333"

# Independent workload/source-field oracle from the approved Step 1 contract.
# These synthetic projection inputs are not authenticated measurement evidence.
CROSS_STUDY = "cross-engine-keyword-real-v1"
RETAINED_STUDY = "retained-key-topk-real-v1"
N = (10000, 100000)
CLASSES = ("absent", "rare", "medium", "common")
CROSS_K = (10, 100)
RETAINED_K = (1, 10, 32, 64, 100, 128, 256, 512, 1024)
CAMPAIGNS = ("d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02")
PAIR_ORACLE = (
    ("R_L_A", "CI_L_A", "A", "L", "0.8", "20"),
    ("R_P_A", "CI_P_A", "A", "P", "0.6", "40"),
    ("R_H_A", "CI_H_A", "A", "H", "0.3", "70"),
    ("R_P_L", "CI_P_L", "L", "P", "0.75", "25"),
    ("R_H_L", "CI_H_L", "L", "H", "0.375", "62.5"),
    ("R_H_P", "CI_H_P", "P", "H", "0.5", "50"),
)
CROSS_ORACLE = (
    ("lucene", "1.068173", "-6.8173"),
    ("tantivy", "0.045566", "95.4434"),
)


def _literal_lanes(k_values):
    return tuple(
        f"pr15d_v1/{n}/{class_name}/k{k}"
        for n in N
        for class_name in CLASSES
        for k in k_values
    )


def _literal_coordinates(study_id):
    if study_id == CROSS_STUDY:
        return {
            ("three-trial-backend", lane, "quervant", comparator)
            for lane in _literal_lanes(CROSS_K)
            for comparator, _ratio, _gain in CROSS_ORACLE
        }
    if study_id == RETAINED_STUDY:
        return {
            (campaign, lane, baseline, treatment)
            for campaign in CAMPAIGNS
            for lane in _literal_lanes(RETAINED_K)
            for _ratio_field, _ci_field, baseline, treatment, _ratio, _gain in PAIR_ORACLE
        }
    raise AssertionError(f"unknown test family: {study_id}")


def _cross_source_lanes():
    return [
        {
            "lane_id": lane,
            "comparisons": [
                {"comparator": comparator, "ratio": ratio}
                for comparator, ratio, _gain in CROSS_ORACLE
            ],
        }
        for lane in _literal_lanes(CROSS_K)
    ]


def _retained_source_lanes():
    lanes = {}
    for lane in _literal_lanes(RETAINED_K):
        campaigns = {}
        for campaign in CAMPAIGNS:
            record = {
                "latency": {"A": 100, "L": 80, "P": 60, "H": 30},
                "filter_sensitive": False,
            }
            for ratio_field, ci_field, _baseline, _treatment, ratio, _gain in PAIR_ORACLE:
                record[ratio_field] = Decimal(ratio)
                record[ci_field] = {
                    "low": Decimal(ratio), "high": Decimal(ratio), "seed": 11,
                }
            campaigns[campaign] = record
        lanes[lane] = {"id": lane, "campaigns": campaigns}
    return lanes


def _project_cross_rows():
    return effects.cross_engine_effect_rows(
        study_id=CROSS_STUDY,
        run_id=RUN,
        analysis_lanes=_cross_source_lanes(),
        input_digest=SHA,
        source_commit=COMMIT,
        host_environment="wsl2",
        host_identity=HOST,
    )


def _project_retained_rows():
    return effects.retained_effect_rows(
        study_id=RETAINED_STUDY,
        run_id=RUN,
        lanes=_retained_source_lanes(),
        input_digest=SHA,
        source_commit=COMMIT,
        host_environment="wsl2",
        host_identity=HOST,
    )


def _disclosure(study_id, rows, comparisons=()):
    return effects.disclosure_payload(
        baseline_id=BASELINE,
        study_id=study_id,
        source_commit=COMMIT,
        current_raw_digest=SHA,
        rows=rows,
        comparisons=comparisons,
    )


def _coordinate(row):
    return (row["campaign_id"], row["lane_id"], row["baseline"], row["treatment"])


def _fraction_decimal(value: Fraction) -> str:
    """Independent finite-decimal oracle using only integer/Fraction arithmetic."""
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        twos += 1
        denominator //= 2
    while denominator % 5 == 0:
        fives += 1
        denominator //= 5
    if denominator != 1:
        raise AssertionError("test oracle requires a terminating decimal")
    places = max(twos, fives)
    scaled = abs(value.numerator) * 2 ** (places - twos) * 5 ** (places - fives)
    whole, fraction = divmod(scaled, 10 ** places)
    tail = str(fraction).rjust(places, "0").rstrip("0") if places else ""
    return ("-" if value < 0 else "") + str(whole) + ("." + tail if tail else "")


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
        expected = {
            (baseline, treatment): (ratio, gain)
            for _ratio_field, _ci_field, baseline, treatment, ratio, gain in PAIR_ORACLE
        }
        rows = _project_retained_rows()
        self.assertEqual(len(rows), 864)
        self.assertEqual(effects.unique_rows(rows), rows)
        self.assertEqual({_coordinate(row) for row in rows}, _literal_coordinates(RETAINED_STUDY))
        for row in rows:
            with self.subTest(coordinate=_coordinate(row)):
                self.assertEqual(
                    (row["ratio"], row["gain_percent"]),
                    expected[(row["baseline"], row["treatment"])],
                )
                self.assertEqual(row["decision"], "DESCRIPTIVE_EFFECT_ONLY")

    def test_cross_engine_projection_uses_quervant_as_baseline(self) -> None:
        rows = _project_cross_rows()
        self.assertEqual(len(rows), 32)
        self.assertEqual(effects.unique_rows(rows), rows)
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


class CompleteFamilyTests(unittest.TestCase):
    """S1-A01: the disclosure is the complete current family grid."""

    def _cross_rows(self):
        return _project_cross_rows()

    def test_cross_family_roundtrip_and_grid(self) -> None:
        document = effects.disclosure_payload(
            baseline_id="33333333-3333-4333-8333-333333333333",
            study_id=effects.STUDY_CROSS_ENGINE,
            source_commit=COMMIT,
            current_raw_digest=SHA,
            rows=self._cross_rows(),
        )
        validated = effects.validate_disclosure(document)
        self.assertEqual(len(validated["rows"]), 32)
        grid = {
            (row["campaign_id"], row["lane_id"], row["baseline"], row["treatment"])
            for row in validated["rows"]
        }
        self.assertEqual(grid, _literal_coordinates(CROSS_STUDY))
        roundtrip = effects.validate_disclosure(json.loads(json.dumps(validated)))
        self.assertEqual(roundtrip, validated)

    def test_incomplete_or_duplicated_grid_rejects(self) -> None:
        rows = self._cross_rows()
        base = dict(
            baseline_id="33333333-3333-4333-8333-333333333333",
            study_id=effects.STUDY_CROSS_ENGINE,
            source_commit=COMMIT,
            current_raw_digest=SHA,
        )
        for mutated in (rows[:-1], rows + [rows[0]]):
            with self.subTest(count=len(mutated)):
                document = effects.disclosure_payload(rows=mutated, **base)
                with self.assertRaises(BenchError):
                    effects.validate_disclosure(document)
        # A second current run for one study is a mixed-run error.
        other = [
            dict(row, run_id="22222222-2222-4222-8222-222222222222") if index == 0 else row
            for index, row in enumerate(rows)
        ]
        with self.assertRaises(BenchError) as raised:
            effects.validate_disclosure(effects.disclosure_payload(rows=other, **base))
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)
        # Mixed measured host contexts in one current run is rejected.
        mixed = [dict(row, host_identity="sha256:" + "9" * 64) if index == 0 else row
                 for index, row in enumerate(rows)]
        with self.assertRaises(BenchError):
            effects.validate_disclosure(effects.disclosure_payload(rows=mixed, **base))

    def test_header_identities_are_validated(self) -> None:
        rows = self._cross_rows()
        for override in (
            {"baseline_id": "not-a-uuid"},
            {"source_commit": "abc"},
            {"current_raw_digest": "sha256:XYZ"},
            {"study_id": "unknown-study"},
        ):
            with self.subTest(override=override):
                kwargs = dict(
                    baseline_id="33333333-3333-4333-8333-333333333333",
                    study_id=effects.STUDY_CROSS_ENGINE,
                    source_commit=COMMIT,
                    current_raw_digest=SHA,
                    rows=rows,
                )
                kwargs.update(override)
                with self.assertRaises(BenchError):
                    effects.disclosure_payload(**kwargs)
                document = effects.disclosure_payload(
                    baseline_id="33333333-3333-4333-8333-333333333333",
                    study_id=effects.STUDY_CROSS_ENGINE,
                    source_commit=COMMIT,
                    current_raw_digest=SHA,
                    rows=rows,
                )
                document.update(override)
                with self.assertRaises(BenchError):
                    effects.validate_disclosure(document)


class AmbientContextTests(unittest.TestCase):
    """S1-A12: hostile ambient Decimal settings cannot change evidence numbers."""

    def test_hostile_ambient_context(self) -> None:
        from decimal import ROUND_DOWN, getcontext, localcontext

        original_context = getcontext()
        with localcontext() as ambient:
            ambient.prec = 3
            ambient.Emax = 9
            ambient.Emin = -9
            ambient.rounding = ROUND_DOWN
            for signal in ambient.traps:
                ambient.traps[signal] = True
            self.assertEqual(effects.gain_percent("1.2", "lower"), "-20")
            self.assertEqual(effects.normalize_ratio(4 / 3), "1.3333333333333333")
            self.assertEqual(effects.gain_percent(4 / 3, "lower"), "-33.33333333333333")
            self.assertEqual(
                effects.effect_change_percentage_points("10", "20"), "-10"
            )
            self.assertEqual(effects.render_six("1.2345675"), "1.234568")
        self.assertIs(getcontext(), original_context)


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
            effects.validate_disclosure(document)  # incomplete family grid

    def test_rows_from_another_study_or_raw_series_are_rejected(self) -> None:
        document = _disclosure(CROSS_STUDY, _project_cross_rows())
        self.assertEqual(effects.validate_disclosure(document), document)
        for case, row in (
            ("another-study", _row()),
            ("another-raw-series", dict(document["rows"][0], input_digest="sha256:" + "9" * 64)),
            ("another-source", dict(document["rows"][0], source_commit="b" * 40)),
        ):
            with self.subTest(case=case):
                broken = deepcopy(document)
                broken["rows"][0] = row
                # This row is valid in its own family: the envelope must reject it.
                self.assertEqual(effects.validate_row(row), row)
                with self.assertRaises(BenchError) as raised:
                    effects.validate_disclosure(broken)
                self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)
                self.assertEqual(raised.exception.field_path, "rows")


class Step1FixupTests(unittest.TestCase):
    """S1F-T01..T06: Step 1 fixup effects corrections."""

    def _cross(self, **overrides):
        values = dict(
            study_id=CROSS_STUDY,
            method_id="cross-engine-three-trial-effects-v1",
            campaign_id="three-trial-backend",
            lane_id="pr15d_v1/10000/absent/k10",
            uncertainty=None,
            baseline="quervant",
            treatment="lucene",
            decision="INCONCLUSIVE",
        )
        values.update(overrides)
        return _row(**values)

    def _assert_error(self, operation, code, field):
        with self.assertRaises(BenchError) as raised:
            operation()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.field_path, field)

    def test_s1f_t01_historical_context(self) -> None:
        current = _row()
        for case, environment, identity in (
            ("windows-original-identity", "windows", "original-host-id"),
            ("unknown-context", None, None),
        ):
            with self.subTest(case=case):
                historical = _row(
                    run_id=CAMPAIGN,
                    evidence_level="AS_REPORTED",
                    source_commit=None,
                    host_environment=environment,
                    host_identity=identity,
                )
                pristine = deepcopy(historical)
                self.assertEqual(effects.validate_row(historical, current=False), pristine)
                self.assertEqual(historical, pristine)
                comparison = effects.compare_effect_rows(
                    historical_rows=[historical], current_rows=[current]
                )[0]
                self.assertEqual(
                    comparison,
                    {
                        "historical_row_digest": content_digest(pristine),
                        "current_row_digest": content_digest(current),
                        "comparability": "CONTEXT_CHANGED",
                        "context_changes": [
                            "source-commit", "host-environment", "host-identity", "as-reported",
                        ],
                        "effect_change_percentage_points": "0",
                    },
                )
        for environment in ("native-linux", "wsl2"):
            with self.subTest(case="current-supported", environment=environment):
                row = _row(host_environment=environment, host_identity=HOST)
                self.assertEqual(effects.validate_row(row), row)
        with self.subTest(case="current-windows-rejected"):
            self._assert_error(
                lambda: effects.validate_row(_row(host_environment="windows")),
                BM_SCHEMA_INVALID,
                "host_environment",
            )

    def test_s1f_t02_mandatory_comparison_references(self) -> None:
        rows = _project_cross_rows()
        self.assertEqual(len(rows), 32)
        current = rows[0]
        historical = dict(current, run_id="previous-run")
        cases = (
            ("COMPARABLE", historical, []),
            (
                "CONTEXT_CHANGED",
                dict(historical, source_commit="b" * 40),
                ["source-commit"],
            ),
            (
                "NOT_COMPARABLE",
                dict(historical, method_id="historical-three-trial-python-round6-v1"),
                ["no-current-row"],
            ),
        )
        boundaries = (
            ("comparison", effects.validate_comparison),
            (
                "complete32-disclosure",
                lambda comparison: effects.validate_disclosure(
                    _disclosure(CROSS_STUDY, rows, [comparison])
                ),
            ),
        )
        for state, historical_row, changes in cases:
            comparison = effects.compare_effect_rows(
                historical_rows=[historical_row], current_rows=rows
            )[0]
            expected = {
                "historical_row_digest": content_digest(historical_row),
                "current_row_digest": (
                    None if state == "NOT_COMPARABLE" else content_digest(current)
                ),
                "comparability": state,
                "context_changes": changes,
                "effect_change_percentage_points": None if state == "NOT_COMPARABLE" else "0",
            }
            with self.subTest(state=state, case="valid-control"):
                self.assertEqual(comparison, expected)
                self.assertEqual(effects.validate_comparison(comparison), expected)
                document = _disclosure(CROSS_STUDY, rows, [comparison])
                self.assertEqual(effects.validate_disclosure(document), document)

            for case, digest in (("null-history", None), ("malformed-history", "sha256:XYZ")):
                broken = dict(comparison, historical_row_digest=digest)
                for boundary, validate in boundaries:
                    with self.subTest(state=state, case=case, boundary=boundary):
                        self._assert_error(
                            lambda: validate(broken), BM_IDENTITY_INVALID, "historical_row_digest"
                        )

            if state == "NOT_COMPARABLE":
                for case, overrides in (
                    ("nonnull-current", {"current_row_digest": content_digest(current)}),
                    ("nonnull-change", {"effect_change_percentage_points": "0"}),
                ):
                    broken = dict(comparison, **overrides)
                    for boundary, validate in boundaries:
                        with self.subTest(state=state, case=case, boundary=boundary):
                            self._assert_error(
                                lambda: validate(broken), BM_SCHEMA_INVALID, "comparability"
                            )
            else:
                for case, digest in (("null-current", None), ("malformed-current", "sha256:XYZ")):
                    broken = dict(comparison, current_row_digest=digest)
                    for boundary, validate in boundaries:
                        with self.subTest(state=state, case=case, boundary=boundary):
                            self._assert_error(
                                lambda: validate(broken), BM_IDENTITY_INVALID, "current_row_digest"
                            )
                with self.subTest(state=state, case="unknown-current-membership"):
                    unknown = "sha256:" + "9" * 64
                    self.assertNotIn(unknown, {content_digest(row) for row in rows})
                    broken = dict(comparison, current_row_digest=unknown)
                    self.assertEqual(effects.validate_comparison(broken), broken)
                    self._assert_error(
                        lambda: effects.validate_disclosure(_disclosure(CROSS_STUDY, rows, [broken])),
                        BM_SCHEMA_INVALID,
                        "comparisons",
                    )

    def test_s1f_t03_method_typing(self) -> None:
        interval = {"low": "0.7", "high": "0.9", "seed": 3}
        self.assertEqual(
            effects._uncertainty(interval, "paired-slot-bootstrap-v1"),
            {**interval, "method": "paired-slot-bootstrap-v1"},
        )
        for method in (float("nan"), None, True, [], {}):
            with self.subTest(method=repr(method)):
                with self.assertRaises(BenchError) as raised:
                    effects._uncertainty(interval, method)
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                self.assertEqual(raised.exception.field_path, "uncertainty.method")
        self.assertIsNone(effects._uncertainty(None, "paired-slot-bootstrap-v1"))

    def test_s1f_t04_independent_grid_roundtrip(self) -> None:
        expected_retained = {
            (baseline, treatment): (ratio, gain)
            for _ratio_field, _ci_field, baseline, treatment, ratio, gain in PAIR_ORACLE
        }
        expected_cross = {
            ("quervant", comparator): (ratio, gain)
            for comparator, ratio, gain in CROSS_ORACLE
        }
        for study, rows, count, expected_pairs in (
            (CROSS_STUDY, _project_cross_rows(), 32, expected_cross),
            (RETAINED_STUDY, _project_retained_rows(), 864, expected_retained),
        ):
            with self.subTest(family=study, case="complete-grid-and-json-replay"):
                self.assertEqual(len(rows), count)
                self.assertEqual(
                    {_coordinate(row) for row in rows}, _literal_coordinates(study)
                )
                document = _disclosure(study, rows)
                pristine = deepcopy(document)
                validated = effects.validate_disclosure(document)
                self.assertEqual(validated, pristine)
                self.assertEqual(document, pristine)
                original_digests = [content_digest(row) for row in pristine["rows"]]
                self.assertEqual(
                    [effects.row_digest(row) for row in validated["rows"]], original_digests
                )
                roundtrip = effects.validate_disclosure(json.loads(json.dumps(validated)))
                self.assertEqual(roundtrip, pristine)
                self.assertEqual(
                    [effects.row_digest(row) for row in roundtrip["rows"]], original_digests
                )
            for row in rows:
                with self.subTest(family=study, case="literal-pair-effect", coordinate=_coordinate(row)):
                    ratio, gain = expected_pairs[(row["baseline"], row["treatment"])]
                    self.assertEqual((row["ratio"], row["gain_percent"]), (ratio, gain))
                    if study == RETAINED_STUDY:
                        self.assertEqual(
                            row["uncertainty"],
                            {"low": ratio, "high": ratio, "seed": 11,
                             "method": "paired-slot-bootstrap-v1"},
                        )
                        self.assertEqual(row["decision"], "DESCRIPTIVE_EFFECT_ONLY")
                    else:
                        self.assertIsNone(row["uncertainty"])
                        self.assertEqual(row["decision"], "INCONCLUSIVE")

    def test_s1f_t04_grid_counterexamples(self) -> None:
        cross_rows = _project_cross_rows()
        retained_rows = _project_retained_rows()
        for study, rows in ((CROSS_STUDY, cross_rows), (RETAINED_STUDY, retained_rows)):
            self.assertEqual(effects.validate_disclosure(_disclosure(study, rows))["rows"], rows)
            for case, broken_rows in (
                ("missing-coordinate", rows[:-1]),
                ("duplicate-replaces-coordinate", rows[:-1] + [deepcopy(rows[0])]),
            ):
                with self.subTest(family=study, case=case):
                    self._assert_error(
                        lambda: effects.validate_disclosure(_disclosure(study, broken_rows)),
                        BM_SCHEMA_INVALID,
                        "rows",
                    )
        with self.subTest(case="retained32-incomplete-family"):
            self.assertEqual(len(retained_rows[:32]), 32)
            self._assert_error(
                lambda: effects.validate_disclosure(_disclosure(RETAINED_STUDY, retained_rows[:32])),
                BM_SCHEMA_INVALID,
                "rows",
            )
        with self.subTest(case="cross32-copies-under32-uuids"):
            repeated = [
                dict(cross_rows[0], run_id=f"{index + 1:08x}-1111-4111-8111-111111111111")
                for index in range(32)
            ]
            self.assertEqual(len(repeated), 32)
            self.assertEqual(len({row["run_id"] for row in repeated}), 32)
            self.assertEqual(len({_coordinate(row) for row in repeated}), 1)
            # Each row is independently valid, so the run-consistency guard is decisive.
            for row in repeated:
                self.assertEqual(effects.validate_row(row), row)
            self._assert_error(
                lambda: effects.validate_disclosure(_disclosure(CROSS_STUDY, repeated)),
                BM_SCHEMA_INVALID,
                "run_id",
            )
        with self.subTest(case="mixed-current-host"):
            mixed = deepcopy(cross_rows)
            mixed[0]["host_identity"] = "sha256:" + "9" * 64
            self.assertEqual({_coordinate(row) for row in mixed}, _literal_coordinates(CROSS_STUDY))
            self.assertEqual(effects.validate_row(mixed[0]), mixed[0])
            self._assert_error(
                lambda: effects.validate_disclosure(_disclosure(CROSS_STUDY, mixed)),
                BM_SCHEMA_INVALID,
                "rows",
            )

    def test_s1f_t05_identity_boundary(self) -> None:
        for current in (True, False):
            valid = self._cross(run_id=RUN if current else "previous-run")
            self.assertEqual(effects.validate_row(valid, current=current), valid)
            for case, field, value, code in (
                ("null-input-digest", "input_digest", None, BM_IDENTITY_INVALID),
                ("list-lane", "lane_id", [], BM_SCHEMA_INVALID),
                ("object-study", "study_id", {}, BM_SCHEMA_INVALID),
            ):
                with self.subTest(current=current, case=case):
                    row = dict(valid)
                    row[field] = value
                    self._assert_error(
                        lambda: effects.validate_row(row, current=current), code, field
                    )

    def test_s1f_t05_disclosure_headers_and_containers(self) -> None:
        rows = _project_cross_rows()
        document = _disclosure(CROSS_STUDY, rows)
        self.assertEqual(effects.validate_disclosure(document), document)
        for field in ("baseline_id", "current_raw_digest"):
            broken = deepcopy(document)
            broken[field] = None
            with self.subTest(case="null-header", field=field, boundary="validator"):
                self._assert_error(
                    lambda: effects.validate_disclosure(broken), BM_IDENTITY_INVALID, field
                )
            arguments = {
                "baseline_id": BASELINE,
                "study_id": CROSS_STUDY,
                "source_commit": COMMIT,
                "current_raw_digest": SHA,
                "rows": rows,
            }
            arguments[field] = None
            with self.subTest(case="null-header", field=field, boundary="builder"):
                self._assert_error(
                    lambda: effects.disclosure_payload(**arguments), BM_IDENTITY_INVALID, field
                )
        for field in ("rows", "comparisons"):
            with self.subTest(case="non-list-container", field=field):
                broken = deepcopy(document)
                broken[field] = {}
                # The existing joint collection guard reports its owning rows boundary.
                self._assert_error(
                    lambda: effects.validate_disclosure(broken), BM_SCHEMA_INVALID, "rows"
                )

    def test_s1f_t05_registered_semantics(self) -> None:
        current = self._cross()
        historical_method = dict(current, method_id="historical-three-trial-python-round6-v1")
        with self.subTest(case="historical-method-on-current"):
            self.assertEqual(
                effects.validate_row(historical_method, current=False), historical_method
            )
            self._assert_error(
                lambda: effects.validate_row(historical_method), BM_SCHEMA_INVALID, "method_id"
            )
        with self.subTest(case="wrong-retained-ci-method"):
            retained = _row()
            self.assertEqual(effects.validate_row(retained), retained)
            retained["uncertainty"]["method"] = "other-method"
            self._assert_error(
                lambda: effects.validate_row(retained), BM_SCHEMA_INVALID, "uncertainty"
            )
        with self.subTest(case="historical-higher-latency"):
            retained = _row(direction="higher")
            self.assertEqual(retained["gain_percent"], "-20")
            self._assert_error(
                lambda: effects.validate_row(retained, current=False), BM_SCHEMA_INVALID, "direction"
            )
        with self.subTest(case="distinct-registered-methods-not-comparable"):
            comparison = effects.compare_effect_rows(
                historical_rows=[historical_method], current_rows=[current]
            )[0]
            self.assertEqual(
                comparison,
                {
                    "historical_row_digest": content_digest(historical_method),
                    "current_row_digest": None,
                    "comparability": "NOT_COMPARABLE",
                    "context_changes": ["no-current-row"],
                    "effect_change_percentage_points": None,
                },
            )
            self.assertEqual(effects.validate_comparison(comparison), comparison)

    def test_s1f_t06_arithmetic_preserved(self) -> None:
        self.assertEqual(effects.gain_percent("1.2", "lower"), "-20")
        self.assertEqual(effects.normalize_ratio(4 / 3), "1.3333333333333333")
        self.assertEqual(effects.gain_percent(4 / 3, "lower"), "-33.33333333333333")
        self.assertEqual(effects.effect_change_percentage_points("10", "20"), "-10")


class FixupNumericalMatrixTests(unittest.TestCase):
    """Executed N/R ledger additions; expected arithmetic is independent."""

    def _reject(self, function, code, field):
        with self.assertRaises(BenchError) as raised:
            function()
        self.assertEqual((raised.exception.code, raised.exception.field_path), (code, field))
        return raised.exception

    def test_n01_n04_constructor_json_roundtrips_and_orientation(self):
        vectors = (
            (4 / 3, "1.3333333333333333", "-33.33333333333333"),
            (1e-7, "0.0000001", "99.99999"),
            ("0.123456789012345678901234567890123456789",
             "0.123456789012345678901234567890123456789",
             "87.6543210987654321098765432109876543211"),
            ("1.2", "1.2", "-20"),
            (1, "1", "0"),
        )
        for source, ratio, gain in vectors:
            with self.subTest(source=str(source)):
                row = _row(ratio=source, uncertainty={"low": source, "high": source, "seed": 0})
                self.assertEqual((row["ratio"], row["gain_percent"]), (ratio, gain))
                reopened = effects.validate_row(json.loads(json.dumps(row)))
                self.assertEqual(reopened, row)
                self.assertEqual(content_digest(reopened), content_digest(row))
                self.assertEqual(Fraction(gain), 100 * (1 - Fraction(str(source))))
        for source, lower, higher in (("0.8", "20", "-20"), ("1.2", "-20", "20"), (1, "0", "0")):
            with self.subTest(source=source):
                self.assertEqual(effects.gain_percent(source, "lower"), lower)
                self.assertEqual(effects.gain_percent(source, "higher"), higher)
        # A latency ratio of 1.2 is not the reciprocal-speedup percentage.
        self.assertNotEqual(Fraction(effects.gain_percent("1.2", "lower")), 100 * (Fraction(1, 1) / Fraction(6, 5) - 1))

    def test_n05_exact_resource_boundaries(self):
        valid = (
            ("significand-at-128", "1." + "7" * 127, "1." + "7" * 127),
            ("adjusted-high-at-128", "1e128", "1" + "0" * 128),
            ("adjusted-low-at-minus128", "1e-128", "0." + "0" * 127 + "1"),
            ("token-at-1024", "0" * 1023 + "1", "1"),
            ("raw-coefficient-at-1024", Decimal((0, (1,) + (0,) * 1023, -1023)), "1"),
            ("finite-large-float", 1e40, "1" + "0" * 40),
            ("largest-adjusted-integer", 10 ** 128, "1" + "0" * 128),
        )
        for name, value, expected in valid:
            with self.subTest(case=name):
                self.assertEqual(effects.normalize_ratio(value), expected)
                self.assertEqual(Fraction(effects.stored_ratio(expected)), Fraction(expected))
        invalid = (
            ("significand-129", "1." + "7" * 128),
            ("adjusted-high-129", "1e129"),
            ("adjusted-low-minus129", "1e-129"),
            ("token-1025", "0" * 1024 + "1"),
            ("raw-coefficient-1025", Decimal((0, (1,) + (0,) * 1024, -1024))),
        )
        for name, value in invalid:
            with self.subTest(case=name):
                self._reject(lambda: effects.normalize_ratio(value), BM_UNSAFE_INPUT, "ratio")
        # The 1,800-bit resource boundary exceeds the separately permitted value
        # range: at-limit reaches that numeric guard, one-over fails before str().
        at_limit, over_limit = 1 << 1799, 1 << 1800
        self.assertEqual((at_limit.bit_length(), over_limit.bit_length()), (1800, 1801))
        self.assertEqual(self._reject(lambda: effects.normalize_ratio(at_limit), BM_UNSAFE_INPUT, "ratio").message,
                         "number is outside the declared decimal bounds")
        self.assertEqual(self._reject(lambda: effects.normalize_ratio(over_limit), BM_UNSAFE_INPUT, "ratio").message,
                         "integer exceeds its input budget")
        for exponent in ("1024", "-1024", "+1024", "0000"):
            with self.subTest(exponent=exponent, case="explicit-at-limit-zero"):
                self.assertEqual(effects.normalize_derived("0e" + exponent), "0")
        for exponent in ("1025", "-1025", "+1025", "00000"):
            with self.subTest(exponent=exponent, case="explicit-over-limit"):
                self._reject(lambda: effects.normalize_derived("0e" + exponent), BM_UNSAFE_INPUT, "gain_percent")
        for value, expected in (
            ("1." + "7" * 511, "1." + "7" * 511),
            ("1e-256", "0." + "0" * 255 + "1"),
            ("1e131", "1" + "0" * 131),
            (Decimal("-0E-999999"), "0"),
        ):
            with self.subTest(case="derived-at-limit", value=str(value)[:20]):
                self.assertEqual(effects.normalize_derived(value), expected)
        for value in ("1." + "7" * 512, "1e-257", "1e132"):
            with self.subTest(case="derived-one-over", value=value[:20]):
                self._reject(lambda: effects.normalize_derived(value), BM_UNSAFE_INPUT, "gain_percent")

    def test_n05_invalid_numeric_types_and_literals_are_typed(self):
        class IntegerSubclass(int):
            pass

        class FloatSubclass(float):
            pass

        class DecimalSubclass(Decimal):
            pass

        class TextSubclass(str):
            pass

        invalid = (
            False, True, None, [], {}, (), object(), IntegerSubclass(1), FloatSubclass(1),
            DecimalSubclass("1"), TextSubclass("1"), Fraction(1, 1), complex(1, 0),
            0, -1, -0.0, "0", "-0", Decimal("-0"), "NaN", "sNaN", "+Infinity", "-Infinity",
            float("nan"), float("inf"), float("-inf"), Decimal("NaN"), Decimal("sNaN"),
            Decimal("Infinity"), Decimal("-Infinity"), " 1", "1 ", "1\n", "1_0", "1,2", "١", "",
        )
        for value in invalid:
            with self.subTest(type=type(value).__name__, value=str(value)[:20]):
                self._reject(lambda: effects.normalize_ratio(value), BM_UNSAFE_INPUT, "ratio")

    def test_n06_producer_normalization_and_stored_alias_rejection(self):
        for value in (1, 1.0, Decimal("1"), "+1", "01", "1.0", "1.", "1e0", "1E+0"):
            with self.subTest(value=str(value), type=type(value).__name__):
                self.assertEqual(effects.normalize_ratio(value), "1")
                self._reject(lambda: effects.stored_ratio(value), BM_SCHEMA_INVALID, "ratio")
        for value in (0, 0.0, Decimal("0"), "-0", "+0", "0.0", "00", "0e0", "0."):
            with self.subTest(derived=value):
                self.assertEqual(effects.normalize_derived(value), "0")
                self._reject(lambda: effects.stored_derived(value), BM_SCHEMA_INVALID, "gain_percent")
        for source, expected in (("+1.200000E+0", "1.2"), (".00000010", "0.0000001")):
            self.assertEqual(effects.normalize_ratio(source), expected)
            self.assertEqual(Fraction(effects.stored_ratio(expected)), Fraction(expected))

    def test_n07_n08_fraction_49_grid_with_hostile_contexts(self):
        from decimal import ROUND_DOWN, ROUND_UP, getcontext, localcontext

        literals = tuple(f"{coefficient}e{exponent}" for coefficient in (1, 2, 3, 7, 99, 1000001, 1234567)
                         for exponent in (-120, -30, -7, 0, 7, 30, 120))
        self.assertEqual(len(literals), 49)
        original = getcontext()
        for rounding in (ROUND_DOWN, ROUND_UP):
            with localcontext() as ambient:
                ambient.prec, ambient.Emin, ambient.Emax, ambient.rounding = 1, -1, 1, rounding
                ambient.clamp = 1
                for signal in ambient.traps:
                    ambient.traps[signal] = True
                initial_flags = dict(ambient.flags)
                for index, literal in enumerate(literals):
                    rational = Fraction(literal)
                    following = Fraction(literals[(index + 1) % len(literals)])
                    for direction, sign in (("lower", -1), ("higher", 1)):
                        with self.subTest(rounding=rounding, literal=literal, direction=direction):
                            expected_gain = 100 * sign * (rational - 1)
                            next_gain = 100 * sign * (following - 1)
                            ratio = effects.normalize_ratio(literal)
                            gain = effects.gain_percent(literal, direction)
                            self.assertEqual(ratio, _fraction_decimal(rational))
                            self.assertEqual(gain, _fraction_decimal(expected_gain))
                            self.assertEqual(Fraction(effects.stored_ratio(ratio)), rational)
                            self.assertEqual(Fraction(effects.stored_derived(gain)), expected_gain)
                            self.assertEqual(effects.effect_change_percentage_points(
                                _fraction_decimal(next_gain), gain), _fraction_decimal(next_gain - expected_gain))
                self.assertEqual(ambient.flags, initial_flags)
                self.assertEqual(effects.render_six("1.2345675"), "1.234568")
                self.assertEqual(effects.interval_endpoints("1.0000003", "1.0000004"),
                                 {"low": "1.0000003", "high": "1.0000004"})
        self.assertIs(getcontext(), original)

    def test_n09_n10_full_interval_contract(self):
        for seed in (0, 18446744073709551615):
            with self.subTest(seed=seed):
                source = {"low": "1.0000003", "high": "1.0000004", "seed": seed}
                expected = {**source, "method": "paired-slot-bootstrap-v1"}
                row = _row(ratio="1.00000035", uncertainty=source)
                self.assertEqual(row["uncertainty"], expected)
                self.assertEqual(effects.validate_row(json.loads(json.dumps(row))), row)
                self.assertEqual(effects._stored_uncertainty(expected), expected)
        self.assertEqual(effects.render_six("1.0000003"), effects.render_six("1.0000004"))
        self._reject(lambda: effects.interval_endpoints("1.0000004", "1.0000003"), BM_SCHEMA_INVALID, "uncertainty")
        source = {"low": "0.8", "high": "0.9", "seed": 0}
        stored = {**source, "method": "paired-slot-bootstrap-v1"}
        for boundary, valid, validate in (
            ("producer", source, lambda value: effects._uncertainty(value, "paired-slot-bootstrap-v1")),
            ("persisted", stored, effects._stored_uncertainty),
        ):
            for key in valid:
                with self.subTest(boundary=boundary, missing=key):
                    invalid = {name: value for name, value in valid.items() if name != key}
                    self._reject(lambda: validate(invalid), BM_SCHEMA_INVALID, "uncertainty")
            with self.subTest(boundary=boundary, extra=True):
                self._reject(lambda: validate({**valid, "extra": 0}), BM_SCHEMA_INVALID, "uncertainty")
            for seed in (True, False, -1, 0.0, 1.0, 18446744073709551616):
                with self.subTest(boundary=boundary, seed=seed):
                    self._reject(lambda: validate({**valid, "seed": seed}), BM_IDENTITY_INVALID, "uncertainty.seed")
        for endpoint in ("low", "high"):
            for value in (0.8, "0.8000", "+0.8", "8e-1", "00.8"):
                with self.subTest(endpoint=endpoint, value=value):
                    self._reject(lambda: effects._stored_uncertainty({**stored, endpoint: value}),
                                 BM_SCHEMA_INVALID, "uncertainty." + endpoint)

    def test_n11_n14_proportional_changes_scale_and_presentation(self):
        for current, historical, expected in (("0.9", "0.8", "-10"), ("1.1", "1.2", "10"),
                                               ("0.9", "1", "10"), ("1", "0.8", "-20"),
                                               ("0.999999996", "0.999999997", "0.0000001")):
            with self.subTest(current=current, historical=historical):
                current_row = _row(ratio=current)
                historical_row = _row(ratio=historical, run_id="historical-measured-run")
                result = effects.compare_effect_rows(historical_rows=[historical_row], current_rows=[current_row])[0]
                self.assertEqual(result["effect_change_percentage_points"], expected)
                self.assertEqual(result["historical_row_digest"], content_digest(historical_row))
                self.assertEqual(result["current_row_digest"], content_digest(current_row))
        tiny = [_row(ratio=value) for value in ("0.999999996", "0.999999997")]
        saved = deepcopy(tiny)
        digests = [content_digest(row) for row in tiny]
        self.assertEqual([effects.render_six(row["gain_percent"]) for row in tiny], ["0.000000", "0.000000"])
        self.assertEqual([row["gain_percent"] for row in tiny], ["0.0000004", "0.0000003"])
        self.assertNotEqual(*digests)
        self.assertEqual(tiny, saved)
        self.assertEqual([content_digest(row) for row in tiny], digests)
        for factor in (Fraction(1, 10**12), Fraction(1, 10), Fraction(1), Fraction(7), Fraction(10**12)):
            with self.subTest(scale=factor):
                # Raw measurements are used only to derive their own within-run ratio.
                baseline, treatment = Fraction(100) * factor, Fraction(80) * factor
                self.assertEqual(effects.gain_percent(_fraction_decimal(treatment / baseline), "lower"), "20")
                current = _row(ratio=_fraction_decimal(Fraction(90, 100)), source_commit="b" * 40)
                old = _row(ratio=_fraction_decimal(treatment / baseline), run_id="old-scale-context")
                comparison = effects.compare_effect_rows(historical_rows=[old], current_rows=[current])[0]
                self.assertEqual(comparison["effect_change_percentage_points"], "-10")
                self.assertNotIn("absolute", " ".join(comparison))
        for value, expected in (("1.2345665", "1.234566"), ("1.2345675", "1.234568"),
                                ("-1.2345665", "-1.234566"), ("-1.2345675", "-1.234568"),
                                ("-0.0000005", "0.000000"), ("-0.0000004", "0.000000")):
            with self.subTest(tie=value):
                self.assertEqual(effects.render_six(value), expected)

    def test_n15_n16_projection_keeps_supplied_statistic_and_source_data(self):
        # These intentionally disagreeing absolute estimates catch a projection
        # that silently replaces the existing rounded comparator string.
        lanes = sorted(_cross_source_lanes(), key=lambda row: row["lane_id"])
        for lane in lanes:
            lane["per_engine"] = {"quervant": {"median_ns": 100}, "lucene": {"median_ns": 50}, "tantivy": {"median_ns": 200}}
        source = {"statistics": {"lanes": lanes}, "descriptive_process_cold": ["process-cold-original"],
                  "raw_build_ns": [101, 202], "raw_throughput": [303, 404]}
        before = deepcopy(source)
        rows = effects.cross_engine_effect_rows(study_id=CROSS_STUDY, run_id=RUN,
            analysis_lanes=source["statistics"]["lanes"], input_digest=SHA, source_commit=COMMIT,
            host_environment="native-linux", host_identity=HOST)
        self.assertEqual(source, before)
        self.assertEqual(len(rows), 32)
        self.assertEqual({_coordinate(row) for row in rows}, _literal_coordinates(CROSS_STUDY))
        expected = {comparator: (ratio, gain) for comparator, ratio, gain in CROSS_ORACLE}
        for row in rows:
            with self.subTest(lane=row["lane_id"], treatment=row["treatment"]):
                self.assertEqual((row["ratio"], row["gain_percent"]), expected[row["treatment"]])
                self.assertEqual((row["regime"], row["decision"], row["uncertainty"]), ("warm", "INCONCLUSIVE", None))
        retained = _project_retained_rows()
        self.assertEqual(len(retained), 864)
        expected_pairs = {(baseline, treatment): (ratio, gain) for _r, _ci, baseline, treatment, ratio, gain in PAIR_ORACLE}
        for row in retained:
            self.assertEqual((row["ratio"], row["gain_percent"]), expected_pairs[(row["baseline"], row["treatment"])])

    def test_r01_every_field_missing_null_wrong_type_and_unknown(self):
        expected_fields = {
            "study_id", "run_id", "campaign_id", "lane_id", "metric", "unit", "regime", "direction",
            "baseline", "treatment", "method_id", "ratio", "gain_percent", "uncertainty", "decision",
            "evidence_level", "source_commit", "host_environment", "host_identity", "input_digest",
        }
        row = _row()
        self.assertEqual(set(row), expected_fields)
        identity_fields = {"run_id", "source_commit", "host_identity", "input_digest"}
        for field in sorted(expected_fields):
            missing = {key: value for key, value in row.items() if key != field}
            with self.subTest(field=field, case="missing"):
                self._reject(lambda: effects.validate_row(missing), BM_SCHEMA_INVALID, "row")
            for label, value in (("null", None), ("wrong-type", []), ("unknown", "unknown")):
                expected_field = "metric" if field in ("unit", "regime") else field
                if field == "treatment" and label == "unknown":
                    expected_field = "baseline"
                expected_code = BM_IDENTITY_INVALID if field in identity_fields else BM_SCHEMA_INVALID
                if field == "ratio" and label == "unknown":
                    expected_code = BM_UNSAFE_INPUT
                with self.subTest(field=field, case=label):
                    self._reject(lambda: effects.validate_row({**row, field: value}),
                                 expected_code, expected_field)
        self._reject(lambda: effects.validate_row({**row, "extra": "unknown"}), BM_SCHEMA_INVALID, "row")

    def test_r02_r04_ambiguity_and_identity_only_historical_runs(self):
        first = _row(ratio="0.9")
        second = _row(ratio="1.1")
        for rows in permutations((first, second)):
            with self.subTest(ratios=[row["ratio"] for row in rows]):
                self._reject(lambda: effects.current_index(rows), BM_SCHEMA_INVALID, "rows")
        self._reject(lambda: effects.unique_rows([first, dict(first)], current=False), BM_SCHEMA_INVALID, "rows")
        # Identity-only synthetic maps are not authentic catalog/history evidence.
        keys = ("study_id", "run_id", "campaign_id", "lane_id", "metric", "unit", "regime", "baseline", "treatment", "method_id")
        old1 = {key: first[key] for key in keys}
        old2 = {**old1, "run_id": "second-synthetic-historical-run"}
        self.assertNotEqual(effects.checked_key(old1, keys), effects.checked_key(old2, keys))
        self.assertEqual(effects.checked_key(old1, tuple(key for key in keys if key != "run_id")),
                         effects.checked_key(old2, tuple(key for key in keys if key != "run_id")))
        multi_run = [first, _row(run_id="22222222-2222-4222-8222-222222222222", lane_id="pr15d_v1/10000/common/k32")]
        for rows in permutations(multi_run):
            self._reject(lambda: effects.compare_effect_rows(historical_rows=[first], current_rows=rows), BM_SCHEMA_INVALID, "run_id")
        for field in ("method_id", "baseline", "treatment"):
            with self.subTest(missing_meaning=field):
                self._reject(lambda: effects.compare_effect_rows(historical_rows=[first], current_rows=[{**first, field: None}]),
                             BM_SCHEMA_INVALID, field)

    def test_r05_r08_context_and_comparison_permutations(self):
        rows = sorted(_project_cross_rows(), key=lambda row: (row["lane_id"], row["treatment"]))
        current = rows[:3]
        historical = [dict(row, run_id="prior-" + str(index), evidence_level="AS_REPORTED",
                           source_commit=None, host_environment=None, host_identity=None)
                      for index, row in enumerate(current)]
        keys = ("study_id", "run_id", "campaign_id", "lane_id", "metric", "unit", "regime", "baseline", "treatment", "method_id")
        ordered = sorted(historical, key=lambda row: tuple(row[key] for key in keys))
        original = deepcopy(historical)
        expected = [{"historical_row_digest": content_digest(old), "current_row_digest": content_digest(now),
                     "comparability": "CONTEXT_CHANGED",
                     "context_changes": ["source-commit", "host-environment", "host-identity", "as-reported"],
                     "effect_change_percentage_points": "0"}
                    for old, now in zip(ordered, current)]
        for old_order in permutations(historical):
            for current_order in permutations(current):
                with self.subTest(historical=[row["run_id"] for row in old_order],
                                  current=[row["lane_id"] + row["treatment"] for row in current_order]):
                    self.assertEqual(effects.compare_effect_rows(historical_rows=old_order, current_rows=current_order), expected)
        self.assertEqual(historical, original)
        self.assertTrue(all(row["evidence_level"] == "AS_REPORTED" for row in historical))
        self.assertTrue(all(row["source_commit"] == COMMIT and row["input_digest"] == SHA for row in current))
        source = _retained_source_lanes()
        reversed_source = {lane: {**record, "campaigns": dict(reversed(tuple(record["campaigns"].items())))}
                           for lane, record in reversed(tuple(source.items()))}
        retained = effects.retained_effect_rows(study_id=RETAINED_STUDY, run_id=RUN, lanes=reversed_source,
            input_digest=SHA, source_commit=COMMIT, host_environment="wsl2", host_identity=HOST)
        expected_order = [(campaign, lane, baseline, treatment) for lane in sorted(_literal_lanes(RETAINED_K))
                          for campaign in sorted(CAMPAIGNS) for _r, _ci, baseline, treatment, _ratio, _gain in PAIR_ORACLE]
        self.assertEqual([_coordinate(row) for row in retained], expected_order)
        self.assertEqual(retained, _project_retained_rows())
        self.assertEqual([_coordinate(row) for row in rows],
                         [("three-trial-backend", lane, "quervant", comparator)
                          for lane in sorted(_literal_lanes(CROSS_K)) for comparator in ("lucene", "tantivy")])

    def test_r06_r07_missing_coordinate_has_no_current_digest_or_numeric_change(self):
        current = _project_cross_rows()[0]
        historical = {**current, "run_id": "previous-measured-run", "lane_id": "pr15d_v1/100000/common/k100"}
        self.assertEqual(effects.validate_row(historical, current=False), historical)
        expected = {"historical_row_digest": content_digest(historical), "current_row_digest": None,
                    "comparability": "NOT_COMPARABLE", "context_changes": ["no-current-row"],
                    "effect_change_percentage_points": None}
        self.assertEqual(effects.compare_effect_rows(historical_rows=[historical], current_rows=[current]), [expected])
        self.assertEqual(effects.validate_comparison(expected), expected)
        for field in ("lane_id", "method_id", "baseline", "treatment"):
            with self.subTest(field=field):
                self._reject(lambda: effects.compare_effect_rows(historical_rows=[{**historical, field: None}],
                                                                current_rows=[current]), BM_SCHEMA_INVALID, field)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
