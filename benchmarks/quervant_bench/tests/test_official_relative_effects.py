"""BM09-CURRENT-BASELINE-1-F1 N01-N16: exact decimals and closed effect rows."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
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


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
