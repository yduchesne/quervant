"""AN-BOOT-01…11: deterministic paired-block bootstrap intervals.

The expected values here are hand-derived. The production interval function is
never used to construct its own expected answer, and the frozen index stream is
verified against a checked-in golden plus a standalone reference script that does
not import ``quervant_bench``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from decimal import Decimal

from quervant_bench.analysis.bootstrap import (
    ALGORITHM_LEGACY_RANDOM,
    ALGORITHM_SHA256_REJECTION,
    DOMAIN_PREFIX,
    binding_payload,
    bootstrap_interval,
    domain_key,
    index_stream,
    legacy_bootstrap_interval,
    legacy_percentile_indexes,
    legacy_t7_seed,
    percentile_indexes,
)
from quervant_bench.analysis.contracts import format_effect
from quervant_bench.analysis.profiles import require_draw_budget
from quervant_bench.config.errors import BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.tests.analysis_support import (
    ANALYSIS_FIXTURES,
    ZERO_DIGEST,
    load_bundle,
    make_analysis_profile,
)

ZERO_PROTOCOL = "sha256:" + "0" * 64


def d(value: str) -> Decimal:
    return Decimal(value)


def kwargs(**overrides):
    payload = {
        "seed": 42,
        "protocol_digest": ZERO_PROTOCOL,
        "campaign_index": 0,
        "lane_id": "rare-query",
        "candidate_id": "candidate",
        "baseline_id": "baseline",
        "estimator_id": "median-paired-ratios-v1",
        "resamples": 1000,
        "confidence_basis_points": 9500,
        "direction": "lower-is-better",
    }
    payload.update(overrides)
    return payload


class FrozenStreamTests(unittest.TestCase):
    """AN-BOOT-03, AN-BOOT-04 and the §19 golden."""

    def test_an_boot_03_domain_key_and_first_sixteen_indexes_match_the_golden(self) -> None:
        golden = json.loads(
            (ANALYSIS_FIXTURES / "bootstrap-index-golden.v1.json").read_text(encoding="utf-8")
        )
        payload = binding_payload(
            seed=golden["binding"]["seed"],
            protocol_digest=golden["binding"]["protocol_digest"],
            campaign_index=golden["binding"]["campaign_index"],
            lane_id=golden["binding"]["lane_id"],
            candidate_id=golden["binding"]["candidate_id"],
            baseline_id=golden["binding"]["baseline_id"],
            estimator_id=golden["binding"]["estimator_id"],
        )
        key = domain_key(payload)
        self.assertEqual(key.hex(), golden["domain_key"])
        self.assertEqual(
            list(index_stream(key, golden["block_count"], 16)), golden["indexes"]
        )

    def test_an_boot_03_standalone_reference_reproduces_the_golden(self) -> None:
        golden = json.loads(
            (ANALYSIS_FIXTURES / "bootstrap-index-golden.v1.json").read_text(encoding="utf-8")
        )
        script = ANALYSIS_FIXTURES / "bootstrap-index-reference.py"
        completed = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        reference = json.loads(completed.stdout)
        self.assertEqual(reference["domain_key"], golden["domain_key"])
        self.assertEqual(reference["indexes"], golden["indexes"])

    def test_an_boot_03_domain_prefix_is_the_frozen_literal(self) -> None:
        self.assertEqual(DOMAIN_PREFIX, b"quervant-bench/paired-bootstrap/v1\x00")

    def test_an_boot_04_percentile_indexes_are_frozen(self) -> None:
        self.assertEqual(percentile_indexes(1000), (24, 974))
        self.assertEqual(percentile_indexes(10_000), (249, 9749))
        self.assertEqual(legacy_percentile_indexes(10_000), (249, 9749))

    def test_an_boot_04_resample_budget_is_enforced(self) -> None:
        for count in (99, 20_001):
            with self.subTest(count=count):
                with self.assertRaises(BenchError) as caught:
                    percentile_indexes(count)
                self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)


class IntervalTests(unittest.TestCase):
    """AN-BOOT-01, AN-BOOT-02, AN-BOOT-04 and AN-BOOT-07."""

    def test_an_boot_01_constant_ratio_has_degenerate_endpoints(self) -> None:
        # Distinct block magnitudes with an identical 0.8 ratio per block. An
        # implementation that drew the two arms independently would mix blocks and
        # produce a spread instead of exactly 0.800000000000.
        rows = (
            (1, d("10"), d("8")),
            (2, d("20"), d("16")),
            (3, d("30"), d("24")),
            (4, d("40"), d("32")),
        )
        for seed in (0, 1, 42, 1592524801):
            with self.subTest(seed=seed):
                interval = bootstrap_interval(rows, **kwargs(seed=seed))
                self.assertEqual(format_effect(interval.low), "0.800000000000")
                self.assertEqual(format_effect(interval.high), "0.800000000000")
                self.assertEqual(interval.paired_block_count, 4)
                self.assertEqual(interval.algorithm_id, ALGORITHM_SHA256_REJECTION)
                self.assertEqual(interval.estimator_id, "median-paired-ratios-v1")
                self.assertEqual(interval.confidence_basis_points, 9500)
                self.assertTrue(interval.stream_digest.startswith("sha256:"))
                self.assertEqual(len(interval.stream_digest), len(ZERO_DIGEST))

    def test_an_boot_02_unit_ratio_has_unit_endpoints(self) -> None:
        rows = (
            (1, d("10"), d("10")),
            (2, d("20"), d("20")),
            (3, d("30"), d("30")),
            (4, d("40"), d("40")),
        )
        interval = bootstrap_interval(rows, **kwargs(seed=7))
        self.assertEqual(format_effect(interval.low), "1.000000000000")
        self.assertEqual(format_effect(interval.high), "1.000000000000")

    def test_an_boot_01_reversed_arms_and_direction_invert_orientation(self) -> None:
        forward = bootstrap_interval(
            ((1, d("10"), d("8")), (2, d("20"), d("16"))), **kwargs(seed=3)
        )
        reversed_arms = bootstrap_interval(
            ((1, d("8"), d("10")), (2, d("16"), d("20"))),
            **kwargs(seed=3, direction="higher-is-better"),
        )
        self.assertEqual(format_effect(forward.low), "0.800000000000")
        self.assertEqual(format_effect(reversed_arms.low), "0.800000000000")

    def test_an_boot_04_resample_count_controls_the_index_pair(self) -> None:
        rows = (
            (1, d("10"), d("8")),
            (2, d("20"), d("16")),
            (3, d("30"), d("24")),
            (4, d("40"), d("32")),
        )
        thousand = bootstrap_interval(rows, **kwargs(resamples=1000))
        ten_thousand = bootstrap_interval(rows, **kwargs(resamples=10_000))
        self.assertEqual(thousand.resamples, 1000)
        self.assertEqual(ten_thousand.resamples, 10_000)
        self.assertEqual(thousand.stream_digest, ten_thousand.stream_digest)

    def test_an_boot_07_pruning_changes_the_interval_per_the_frozen_rules(self) -> None:
        # Three blocks share the exact 0.8 ratio; the fourth is an extreme outlier.
        rows = (
            (1, d("10"), d("8")),
            (2, d("20"), d("16")),
            (3, d("30"), d("24")),
            (4, d("10"), d("100")),
        )
        unpruned = bootstrap_interval(rows, **kwargs(seed=11, resamples=1000))
        self.assertEqual(unpruned.paired_block_count, 4)
        # A four-row replicate median is the mean of the two middle effects, so an
        # interval that keeps the outlier can never be degenerate at 0.8.
        self.assertEqual(format_effect(unpruned.low), "0.800000000000")
        self.assertGreater(unpruned.high, d("0.8"))
        pruned = bootstrap_interval(rows[:3], **kwargs(seed=11, resamples=1000))
        self.assertEqual(pruned.paired_block_count, 3)
        self.assertEqual(format_effect(pruned.low), "0.800000000000")
        self.assertEqual(format_effect(pruned.high), "0.800000000000")
        self.assertNotEqual(
            (unpruned.low, unpruned.high), (pruned.low, pruned.high)
        )


class StreamIdentityTests(unittest.TestCase):
    """AN-BOOT-05, AN-BOOT-06, AN-BOOT-08."""

    ROWS = (
        (1, d("10"), d("8")),
        (2, d("20"), d("16")),
        (3, d("30"), d("24")),
    )

    def test_an_boot_05_binding_changes_the_stream_identity(self) -> None:
        base = bootstrap_interval(self.ROWS, **kwargs())
        variants = [
            kwargs(seed=43),
            kwargs(campaign_index=1),
            kwargs(lane_id="common-query"),
            kwargs(candidate_id="treatment"),
            kwargs(baseline_id="reference"),
            kwargs(protocol_digest="sha256:" + "1" * 64),
        ]
        digests = {base.stream_digest}
        for variant in variants:
            with self.subTest(variant=variant):
                other = bootstrap_interval(self.ROWS, **variant)
                self.assertNotEqual(other.stream_digest, base.stream_digest)
                digests.add(other.stream_digest)
        self.assertEqual(len(digests), len(variants) + 1)

    def test_an_boot_06_arms_are_drawn_from_one_shared_block_identity(self) -> None:
        # A test-local "independent draw" oracle: it pairs a candidate value from
        # one block with a baseline value from another. It must NOT reproduce the
        # constant 0.8 ratio, which proves the production estimator is paired.
        import statistics

        key = domain_key(
            binding_payload(
                seed=42,
                protocol_digest=ZERO_PROTOCOL,
                campaign_index=0,
                lane_id="rare-query",
                candidate_id="candidate",
                baseline_id="baseline",
                estimator_id="median-paired-ratios-v1",
            )
        )
        rows = (
            (1, d("10"), d("8")),
            (2, d("20"), d("16")),
            (3, d("30"), d("24")),
        )
        draws = list(index_stream(key, 3, 1000 * 3))
        independent: list[Decimal] = []
        paired: list[Decimal] = []
        for replicate in range(1000):
            selected = draws[replicate * 3 : replicate * 3 + 3]
            baseline_values = [rows[index][1] for index in selected]
            shifted = selected[1:] + selected[:1]
            mixed = [rows[shifted[position]][2] for position in range(3)]
            paired.append(
                Decimal(statistics.median([rows[i][2] / rows[i][1] for i in selected]))
            )
            independent.append(
                Decimal(statistics.median(
                    [mixed[p] / baseline_values[p] for p in range(3)]
                ))
            )
        self.assertEqual(set(paired), {d("0.8")})
        self.assertGreater(len(set(independent)), 1)
        interval = bootstrap_interval(rows, **kwargs())
        self.assertEqual(format_effect(interval.low), "0.800000000000")
        self.assertEqual(format_effect(interval.high), "0.800000000000")

    def test_an_boot_08_permutations_cannot_change_the_point_estimate(self) -> None:
        import itertools

        from quervant_bench.analysis.arithmetic import median_paired_ratios

        rows = (
            (1, d("10"), d("8")),
            (2, d("20"), d("45")),
            (3, d("100"), d("50")),
        )
        # Effects are 0.8, 2.25 and 0.5, so the median is exactly 0.8.
        expected = d("0.8")
        for permutation in itertools.permutations(rows):
            with self.subTest(permutation=permutation):
                self.assertEqual(
                    median_paired_ratios(list(permutation), "lower-is-better"), expected
                )
        with self.assertRaises(BenchError) as caught:
            bootstrap_interval(
                (rows[1], rows[0], rows[2]), **kwargs()
            )
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)


class AlternativeEstimatorAndLegacyTests(unittest.TestCase):
    """AN-BOOT-10 and AN-BOOT-11."""

    ROWS = (
        (1, d("10"), d("10")),
        (2, d("20"), d("50")),
        (3, d("100"), d("50")),
    )

    def test_an_boot_10_ratio_of_arm_medians_is_selectable_and_distinct(self) -> None:
        paired = bootstrap_interval(
            self.ROWS, **kwargs(estimator_id="median-paired-ratios-v1")
        )
        alternative = bootstrap_interval(
            self.ROWS, **kwargs(estimator_id="ratio-of-arm-medians-v1")
        )
        self.assertEqual(paired.estimator_id, "median-paired-ratios-v1")
        self.assertEqual(alternative.estimator_id, "ratio-of-arm-medians-v1")
        self.assertNotEqual(paired.stream_digest, alternative.stream_digest)
        # The two *point* estimators are not interchangeable on this sample.
        from quervant_bench.analysis.arithmetic import (
            median_paired_ratios,
            ratio_of_arm_medians,
        )

        self.assertEqual(
            format_effect(median_paired_ratios(self.ROWS, "lower-is-better")),
            "1.000000000000",
        )
        self.assertEqual(
            format_effect(ratio_of_arm_medians(self.ROWS, "lower-is-better")),
            "2.500000000000",
        )
        with self.assertRaises(BenchError):
            bootstrap_interval(self.ROWS, **kwargs(estimator_id="invented-v1"))

    def test_an_boot_11_legacy_randrange_mode_is_isolated(self) -> None:
        interval = legacy_bootstrap_interval(
            self.ROWS, seed=legacy_t7_seed("sha", "series", "lane", "P", "A"), resamples=1000
        )
        self.assertEqual(interval.algorithm_id, ALGORITHM_LEGACY_RANDOM)
        self.assertEqual(interval.estimator_id, "ratio-of-arm-medians-v1")
        repeat = legacy_bootstrap_interval(
            self.ROWS, seed=legacy_t7_seed("sha", "series", "lane", "P", "A"), resamples=1000
        )
        self.assertEqual(
            (interval.low, interval.high, interval.stream_digest),
            (repeat.low, repeat.high, repeat.stream_digest),
        )
        # The historical seed identity is a SHA-256 prefix of the frozen string.
        import hashlib

        expected = int.from_bytes(
            hashlib.sha256(b"sha|series|lane|P/A").digest()[:8], "big"
        )
        self.assertEqual(
            legacy_t7_seed("sha", "series", "lane", "P", "A"), expected
        )
        # A new profile can never select the historical algorithm.
        from quervant_bench.analysis.profiles import validate_analysis_profile
        from quervant_bench.tests.analysis_support import (
            analysis_profile_document,
            load_bundle,
        )

        document = analysis_profile_document()
        document["bootstrap"]["algorithm_id"] = ALGORITHM_LEGACY_RANDOM
        with self.assertRaises(BenchError):
            validate_analysis_profile(document, load_bundle())


class DrawBudgetTests(unittest.TestCase):
    """AN-BOOT-09: over-budget derivations reject before any resampling."""

    def test_an_boot_09_draw_budget_is_preflighted(self) -> None:
        bundle = load_bundle()
        affordable = make_analysis_profile(resamples=1000)
        self.assertEqual(require_draw_budget(affordable, bundle), 16_000)
        over = make_analysis_profile(resamples=20_000)
        # 20000 x 4 blocks x 4 comparisons = 320000 <= 2000000, so still fine.
        self.assertEqual(require_draw_budget(over, bundle), 320_000)

    def test_an_boot_09_over_budget_profile_rejects(self) -> None:
        from types import SimpleNamespace

        from quervant_bench.analysis import profiles as profiles_module
        from quervant_bench.analysis.profiles import BootstrapContract

        bundle = load_bundle()
        affordable = make_analysis_profile(resamples=1000)
        self.assertEqual(profiles_module.require_draw_budget(affordable, bundle), 16_000)
        expensive = make_analysis_profile(resamples=20_000)
        # 20000 resamples x 4 blocks x 4 comparisons = 320000, still affordable.
        self.assertEqual(
            profiles_module.require_draw_budget(expensive, bundle), 320_000
        )
        # A duck-typed maximum-size bundle: 8 candidates x 64 lanes x 8 treatment
        # campaigns x 256 blocks x 20000 resamples is far above 2,000,000.
        wide = SimpleNamespace(
            experiment=SimpleNamespace(
                arms=tuple(
                    SimpleNamespace(arm_id=f"arm-{index}") for index in range(9)
                )
            ),
            workload=SimpleNamespace(
                lanes=tuple(
                    SimpleNamespace(lane_id=f"lane-{index}") for index in range(64)
                )
            ),
            protocol=SimpleNamespace(schedule=SimpleNamespace(blocks=256)),
            protocol_document={
                "campaigns": {
                    "required_controls": 1,
                    "required_treatments": 8,
                    "control_contract_id": "synthetic-exact-equality",
                },
                "measurement": {"clock_contract_id": "synthetic-logical-clock"},
            },
        )
        self.assertIsInstance(expensive.bootstrap, BootstrapContract)
        with self.assertRaises(BenchError) as caught:
            profiles_module.require_draw_budget(expensive, wide)  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    unittest.main()
