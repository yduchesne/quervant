"""HIST-01…HIST-05: frozen PR15D semantics and legacy-compatibility boundary."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
from typing import Any

from quervant_bench.config.codec import content_digest, load_document
from quervant_bench.migrations.cross_engine import (
    REFERENCE_EXPERIMENT_ID,
    validate_cross_engine_reference,
)
from quervant_bench.migrations.cross_engine_contract import (
    compute_oracle_row,
    expected_lane_ids,
    validate_oracle_golden,
)
from quervant_bench.tests.cross_engine_support import (
    CATALOG,
    EXPERIMENTS,
    LEGACY_MATRIX,
    REPO_ROOT,
    read_json,
)

SPEC = REPO_ROOT / "benchmarks" / "pr15d" / "spec" / "pr15d_v1.json"
HISTORICAL_ORACLE = REPO_ROOT / "benchmarks" / "pr15d" / "corpus" / "oracle.py"

MATRIX_KEYS = {
    "id",
    "legacy_component",
    "new_component",
    "equivalence_class",
    "required_input",
    "expected_comparison",
    "disposition_if_missing",
    "notes",
}
EXPECTED_ROWS = {
    "X01": "SEMANTIC",
    "X02": "SEMANTIC",
    "X03": "NON_EQUIVALENT_CONTRACT",
    "X04": "NON_EQUIVALENT_CONTRACT",
    "X05": "SEMANTIC",
    "X06": "NON_EQUIVALENT_CONTRACT",
    "X07": "SEMANTIC",
    "X08": "EVIDENCE_UNAVAILABLE",
}


def load_historical_oracle() -> Any:
    spec = importlib.util.spec_from_file_location(
        "bm08_hist_oracle_parity", HISTORICAL_ORACLE
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise AssertionError("the historical oracle module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HistoricalByteTests(unittest.TestCase):
    """HIST-01: original PR15D sources remain byte-for-byte unchanged."""

    def test_hist_01_original_paths_are_byte_identical(self) -> None:
        recorded = LEGACY_MATRIX["historical_sources"]
        self.assertGreaterEqual(len(recorded), 19)
        for relative, digest in recorded.items():
            with self.subTest(path=relative):
                payload = (REPO_ROOT / relative).read_bytes()
                self.assertEqual(
                    "sha256:" + hashlib.sha256(payload).hexdigest(), digest
                )
        # The frozen spec identity did not change either.
        self.assertEqual(recorded["benchmarks/pr15d/spec/pr15d_v1.json"], given_digest())

    def test_hist_02_original_adapter_query_paths_remain_timed(self) -> None:
        # This is the rationale for prohibiting a live op=query in BM-08.
        quervant = (
            REPO_ROOT / "benchmarks/pr15d/adapters/quervant/src/main.rs"
        ).read_text(encoding="utf-8")
        tantivy = (
            REPO_ROOT / "benchmarks/pr15d/adapters/tantivy/src/main.rs"
        ).read_text(encoding="utf-8")
        lucene = (
            REPO_ROOT
            / "benchmarks/pr15d/adapters/lucene/src/main/java/org/quervant/bench/Adapter.java"
        ).read_text(encoding="utf-8")
        self.assertIn("use std::time::Instant;", quervant)
        self.assertIn("Instant::now()", quervant)
        self.assertIn("use std::time::Instant;", tantivy)
        self.assertIn("Instant::now()", tantivy)
        self.assertIn("System.nanoTime()", lucene)


def given_digest() -> str:
    return LEGACY_MATRIX["historical_sources"][
        "benchmarks/pr15d/spec/pr15d_v1.json"
    ]


class HistoricalOracleParityTests(unittest.TestCase):
    """HIST-02: independent oracle parity against the read-only historical module."""

    def test_hist_03_independent_oracle_parity_for_all_sixteen_rows(self) -> None:
        oracle = load_historical_oracle()
        golden = validate_oracle_golden(read_json(CATALOG / "oracle-golden.v1.json"))
        self.assertEqual(tuple(row["lane_id"] for row in golden), expected_lane_ids())
        for row in golden:
            rows = oracle.build_row_formula(row["corpus_size"])
            historical = oracle.expected(
                rows, row["field"], row["term"], row["top_k"]
            )
            self.assertEqual(row["total_hits"], historical["total_hits"])
            self.assertEqual(row["doc_ids"], historical["doc_ids"])
            self.assertEqual(
                row, compute_oracle_row(row["corpus_size"], row["selectivity_class"], row["top_k"])
            )


class HistoricalBoundaryTests(unittest.TestCase):
    """HIST-04/HIST-05: excluded semantics and the blocked historical gate."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_document(SPEC)
        cls.bundle, _digests = validate_cross_engine_reference(EXPERIMENTS, REPO_ROOT)

    def test_hist_04_scored_and_process_cold_semantics_stay_excluded(self) -> None:
        self.assertEqual(self.spec["score_comparison"], "NOT_APPLICABLE")
        self.assertIn("process_cold", self.spec["matrix"]["regimes"])
        self.assertEqual(
            self.spec["scored_lane"]["status"],
            "SEMANTICALLY_NONCOMPARABLE_UNTIL_PROVEN",
        )
        regimes = {lane.cache_regime for lane in self.bundle.workload.lanes}
        self.assertEqual(regimes, {"warm"})
        ledger = read_json(CATALOG / "semantic-comparability.v1.json")
        excluded = {entry["class_id"]: entry for entry in ledger["excluded_classes"]}
        self.assertEqual(excluded["process-cold"]["status"], "DEFERRED")
        self.assertEqual(excluded["scored-bm25"]["status"], "NONCOMPARABLE")
        self.assertEqual(excluded["index-throughput"]["status"], "DEFERRED")

    def test_hist_05_legacy_equivalence_matrix_is_exact_and_blocked(self) -> None:
        self.assertEqual(
            set(LEGACY_MATRIX),
            {
                "kind",
                "schema_version",
                "evidence_origin",
                "qualification_scope",
                "historical_status",
                "historical_sources",
                "rows",
            },
        )
        self.assertEqual(
            LEGACY_MATRIX["kind"], "cross-engine-legacy-equivalence-matrix"
        )
        self.assertEqual(LEGACY_MATRIX["evidence_origin"], "synthetic")
        self.assertEqual(LEGACY_MATRIX["qualification_scope"], "simulated")
        self.assertEqual(
            LEGACY_MATRIX["historical_status"],
            {
                "HISTORICAL_NUMERIC_PARITY": "NOT_EXECUTED",
                "HISTORICAL_DECISION_PARITY": "NOT_EXECUTED",
                "HISTORICAL_ACCEPTANCE_GATE": "BLOCKED",
                "LEGACY_PATHS_RETIRED": "NO",
            },
        )
        self.assertEqual(
            {row["id"]: row["equivalence_class"] for row in LEGACY_MATRIX["rows"]},
            EXPECTED_ROWS,
        )
        for row in LEGACY_MATRIX["rows"]:
            self.assertEqual(set(row), MATRIX_KEYS)
            for value in row.values():
                self.assertIsInstance(value, str)
                self.assertTrue(value)
        self.assertEqual(
            [row["id"] for row in LEGACY_MATRIX["rows"]],
            list(EXPECTED_ROWS),
        )

    def test_hist_06_no_historical_numeric_value_enters_synthetic_samples(self) -> None:
        scenario = read_json(CATALOG / "synthetic-scenario.v1.json")
        values = {tuple(sample["values"]) for sample in scenario["samples"]}
        self.assertEqual(values, {(990000, 1000000, 1010000)})
        self.assertEqual(len(scenario["samples"]), 3 * 16)
        # No historical measured number is present in the equivalence matrix.
        serialized = json.dumps(LEGACY_MATRIX)
        for needle in ("index_ns", "engine_ns", "p95", "qps"):
            self.assertNotIn(needle, serialized)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
