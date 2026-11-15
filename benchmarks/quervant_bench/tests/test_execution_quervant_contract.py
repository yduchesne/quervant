"""Quervant adapter-contract proof without real timing.

This module demonstrates that the frozen BM-01 ``BenchmarkAdapter`` seam can
represent a Quervant-style search lane and its correctness oracle, using only the
public dataclasses. It is an adapter-contract proof: no real adapter binary, no
Criterion harness, no timed query and no subprocess is invoked. The genuine
untimed Rust semantic regression (``cargo test -p quervant-core --test pr15i_d3_c``)
is run separately by the local QA gate, not from a Python unit test.
"""

from __future__ import annotations

import time
import unittest
import uuid
from dataclasses import dataclass
from unittest import mock

from quervant_bench.config.contracts import (
    ADAPTER_STATUSES,
    AdapterContext,
    BenchmarkAdapter,
    Lane,
    MeasurementResult,
    OracleResult,
    PreparedFixture,
    WarmupResult,
)

SYNTHETIC = "synthetic"
SIMULATED = "simulated"


@dataclass(frozen=True)
class ExpectedHits:
    """Declared expected result shape for one synthetic query lane."""

    document_ids: tuple[int, ...]
    top_k: int


class FakeQuervantSearchAdapter:
    """In-process model of a Quervant search lane using frozen BM-01 dataclasses.

    ``prepare`` records the declared expected hit set, ``check_oracle`` compares the
    adapter's observed hit set against it and ``measure`` replays declared integer
    nanosecond values. No clock, process or engine is consulted.
    """

    def __init__(
        self,
        expected: ExpectedHits,
        observed: tuple[int, ...],
        samples: tuple[int, ...] = (1000, 1100, 900),
    ) -> None:
        self._expected = expected
        self._observed = observed
        self._samples = samples
        self.oracle_calls = 0

    def prepare(self, context: AdapterContext) -> PreparedFixture:
        return PreparedFixture(
            fixture_id="synthetic-fixture",
            digest="sha256:" + "2" * 64,
            status="prepared",
            evidence_origin=SYNTHETIC,
            qualification_scope=SIMULATED,
        )

    def check_oracle(
        self, context: AdapterContext, prepared: PreparedFixture
    ) -> OracleResult:
        self.oracle_calls += 1
        status = "pass" if self._hits_match() else "fail"
        return OracleResult(
            oracle_id="synthetic-contract-oracle",
            oracle_version=1,
            status=status,
            evidence_origin=SYNTHETIC,
            qualification_scope=SIMULATED,
        )

    def warmup(
        self, context: AdapterContext, prepared: PreparedFixture, lane: Lane
    ) -> WarmupResult:
        return WarmupResult(
            lane_id=lane.lane_id,
            status="pass",
            evidence_origin=SYNTHETIC,
            qualification_scope=SIMULATED,
        )

    def measure(
        self, context: AdapterContext, prepared: PreparedFixture, lane: Lane
    ) -> MeasurementResult:
        return MeasurementResult(
            lane_id=lane.lane_id,
            unit="nanoseconds",
            direction="lower-is-better",
            status="pass",
            samples=self._samples,
            evidence_origin=SYNTHETIC,
            qualification_scope=SIMULATED,
        )

    def cleanup(self, context: AdapterContext, prepared: PreparedFixture) -> None:
        return None

    def _hits_match(self) -> bool:
        expected = tuple(sorted(self._expected.document_ids))
        observed = tuple(sorted(self._observed))
        if len(observed) != min(self._expected.top_k, len(expected)):
            return False
        return observed == expected[: self._expected.top_k]


def context() -> AdapterContext:
    return AdapterContext(
        experiment_id="synthetic-execution-smoke",
        run_id=str(uuid.uuid4()),
        lane_ids=("rare-query", "common-query"),
        evidence_origin=SYNTHETIC,
        qualification_scope=SIMULATED,
    )


def lane() -> Lane:
    return Lane(
        lane_id="rare-query",
        operation="search",
        cache_regime="warm",
        params={"top_k": 3},
    )


class QuervantContractTests(unittest.TestCase):
    def test_fake_adapter_satisfies_the_frozen_benchmark_adapter_protocol(self) -> None:
        adapter = FakeQuervantSearchAdapter(ExpectedHits((1, 2, 3), 3), (1, 2, 3))
        self.assertIsInstance(adapter, BenchmarkAdapter)
        for name in ("prepare", "check_oracle", "warmup", "measure", "cleanup"):
            self.assertTrue(callable(getattr(adapter, name)))
        for status in ("prepared", "pass", "fail", "error", "skipped"):
            self.assertIn(status, ADAPTER_STATUSES)

    def test_oracle_accepts_an_exact_hit_set(self) -> None:
        adapter = FakeQuervantSearchAdapter(ExpectedHits((1, 2, 3), 3), (3, 1, 2))
        adapter_context = context()
        prepared = adapter.prepare(adapter_context)
        oracle = adapter.check_oracle(adapter_context, prepared)
        self.assertEqual(oracle.status, "pass")
        self.assertEqual(oracle.oracle_id, "synthetic-contract-oracle")
        self.assertEqual(adapter.oracle_calls, 1)

    def test_oracle_rejects_a_missing_hit(self) -> None:
        adapter = FakeQuervantSearchAdapter(ExpectedHits((1, 2, 3), 3), (1, 2))
        adapter_context = context()
        prepared = adapter.prepare(adapter_context)
        self.assertEqual(adapter.check_oracle(adapter_context, prepared).status, "fail")

    def test_oracle_rejects_an_incorrect_hit(self) -> None:
        adapter = FakeQuervantSearchAdapter(ExpectedHits((1, 2, 3), 3), (1, 2, 4))
        adapter_context = context()
        prepared = adapter.prepare(adapter_context)
        self.assertEqual(adapter.check_oracle(adapter_context, prepared).status, "fail")

    def test_oracle_rejects_a_too_short_hit_list(self) -> None:
        adapter = FakeQuervantSearchAdapter(ExpectedHits((1, 2, 3), 2), (1, 2, 3))
        adapter_context = context()
        prepared = adapter.prepare(adapter_context)
        self.assertEqual(adapter.check_oracle(adapter_context, prepared).status, "fail")

    def test_full_envelope_round_trip_uses_no_timer(self) -> None:
        adapter = FakeQuervantSearchAdapter(ExpectedHits((7, 8), 2), (7, 8))
        adapter_context = context()

        def forbidden(*_args, **_kwargs):
            raise AssertionError("a real timer was consulted")

        with (
            mock.patch.object(time, "time", forbidden),
            mock.patch.object(time, "perf_counter", forbidden),
            mock.patch.object(time, "monotonic", forbidden),
        ):
            prepared = adapter.prepare(adapter_context)
            oracle = adapter.check_oracle(adapter_context, prepared)
            warmup = adapter.warmup(adapter_context, prepared, lane())
            measurement = adapter.measure(adapter_context, prepared, lane())
            self.assertIsNone(adapter.cleanup(adapter_context, prepared))
        self.assertEqual(oracle.status, "pass")
        self.assertEqual(warmup.status, "pass")
        self.assertEqual(measurement.unit, "nanoseconds")
        self.assertEqual(measurement.direction, "lower-is-better")
        self.assertEqual(measurement.samples, (1000, 1100, 900))

if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
