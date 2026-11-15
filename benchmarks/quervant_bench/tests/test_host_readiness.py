"""HOST-06…HOST-09: pure readiness diagnostics over supplied observations."""

from __future__ import annotations

import unittest

from quervant_bench.config.errors import BM_UNSAFE_INPUT, BenchError
from quervant_bench.host.readiness import (
    ReadinessDiagnostic,
    ReadinessLimits,
    ReadinessObservation,
    evaluate_readiness,
)


def _limits(**overrides: int) -> ReadinessLimits:
    values = {
        "min_interval_ms": 100,
        "max_interval_ms": 200,
        "max_busy_permille": 500,
        "max_median_busy_permille": 400,
        "max_steal_permille": 50,
        "min_intervals": 3,
    }
    values.update(overrides)
    return ReadinessLimits(**values)


class ReadinessTests(unittest.TestCase):
    def test_host_06_exact_limits_are_clear_but_not_authorizing(self) -> None:
        observations = (
            ReadinessObservation(100, 400, 10),
            ReadinessObservation(200, 500, 50),
            ReadinessObservation(150, 300, 0),
        )
        diagnostic = evaluate_readiness(_limits(), observations)
        self.assertEqual(diagnostic, ReadinessDiagnostic("clear", ()))
        self.assertEqual(set(diagnostic.__dataclass_fields__), {"status", "reasons"})
        self.assertFalse(hasattr(diagnostic, "authorized"))
        self.assertFalse(hasattr(diagnostic, "token"))
        self.assertFalse(hasattr(diagnostic, "expires"))

    def test_host_07_one_over_limit_reasons(self) -> None:
        cases = {
            "busy-exceeded": (
                _limits(),
                (
                    ReadinessObservation(100, 501, 10),
                    ReadinessObservation(150, 100, 10),
                    ReadinessObservation(150, 100, 10),
                ),
            ),
            "steal-exceeded": (
                _limits(),
                (
                    ReadinessObservation(100, 100, 51),
                    ReadinessObservation(150, 100, 10),
                    ReadinessObservation(150, 100, 10),
                ),
            ),
            "interval-out-of-range": (
                _limits(),
                (
                    ReadinessObservation(99, 100, 10),
                    ReadinessObservation(150, 100, 10),
                    ReadinessObservation(150, 100, 10),
                ),
            ),
            "median-busy-exceeded": (
                _limits(),
                (
                    ReadinessObservation(100, 500, 10),
                    ReadinessObservation(150, 500, 10),
                    ReadinessObservation(150, 100, 10),
                ),
            ),
            "insufficient-intervals": (
                _limits(),
                (ReadinessObservation(100, 100, 10), ReadinessObservation(150, 100, 10)),
            ),
        }
        for expected_reason, (limits, observations) in cases.items():
            with self.subTest(reason=expected_reason):
                diagnostic = evaluate_readiness(limits, observations)
                self.assertEqual(diagnostic.status, "blocked")
                self.assertIn(expected_reason, diagnostic.reasons)
                self.assertEqual(diagnostic.reasons, tuple(sorted(diagnostic.reasons)))

    def test_host_07b_reasons_are_sorted_and_complete(self) -> None:
        diagnostic = evaluate_readiness(
            _limits(),
            (
                ReadinessObservation(99, 501, 51),
                ReadinessObservation(150, 500, 10),
                ReadinessObservation(150, 500, 10),
            ),
        )
        self.assertEqual(
            diagnostic.reasons,
            ("busy-exceeded", "interval-out-of-range", "median-busy-exceeded", "steal-exceeded"),
        )

    def test_host_08_invalid_observations_and_limits_are_rejected(self) -> None:
        invalid_observations = [
            (True, 10, 10),
            (-1, 10, 10),
            (100, 1001, 10),
            (100, 10, 1001),
            (100, -1, 10),
        ]
        for elapsed, busy, steal in invalid_observations:
            with self.subTest(elapsed=elapsed, busy=busy, steal=steal):
                with self.assertRaises(BenchError) as raised:
                    ReadinessObservation(elapsed, busy, steal)  # type: ignore[arg-type]
                self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

        invalid_limits = [
            {"min_interval_ms": 0},
            {"min_interval_ms": 300, "max_interval_ms": 200},
            {"min_intervals": 0},
            {"min_intervals": 257},
            {"max_busy_permille": 1001},
            {"max_steal_permille": -1},
            {"max_median_busy_permille": True},
        ]
        for overrides in invalid_limits:
            with self.subTest(overrides=overrides):
                with self.assertRaises(BenchError) as raised:
                    _limits(**overrides)
                self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_host_08b_out_of_domain_observation_sequence_is_rejected(self) -> None:
        with self.assertRaises(BenchError) as raised:
            ReadinessObservation(-1, 100, 10)
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
        with self.assertRaises(BenchError):
            evaluate_readiness(_limits(), [{"elapsed_ms": 100}])  # type: ignore[list-item]

    def test_host_09_repeated_clear_diagnostics_remain_inert(self) -> None:
        observations = (
            ReadinessObservation(100, 0, 0),
            ReadinessObservation(100, 0, 0),
            ReadinessObservation(100, 0, 0),
        )
        first = evaluate_readiness(_limits(), observations)
        second = evaluate_readiness(_limits(), observations)
        self.assertEqual(first, second)
        self.assertEqual(first.status, "clear")
        self.assertEqual(first.reasons, ())
        self.assertEqual(observations, tuple(observations))


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
