"""ORA/WIR/SRC evidence: independent exact-term oracle, wire projections, sources."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from quervant_bench.config.codec import content_digest, load_document
from quervant_bench.config.contracts import Lane
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.migrations.cross_engine import (
    REFERENCE_EXPERIMENT_ID,
    validate_cross_engine_reference,
)
from quervant_bench.migrations.cross_engine_contract import (
    DECLARED_ENGINE_VERSIONS,
    ENGINE_IDS,
    SOURCE_FILE_ALLOWLIST,
    compute_oracle_row,
    expected_lane_ids,
    oracle_row_for_lane,
    validate_engine_source_bindings,
    validate_keyword_reply_projection,
    validate_oracle_golden,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENTS = REPO_ROOT / "benchmarks" / "experiments"
CATALOG = EXPERIMENTS / REFERENCE_EXPERIMENT_ID
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cross-engine"
EXPECTATIONS = json.loads((FIXTURES / "reference-expectations.v1.json").read_text())
HISTORICAL_ORACLE = REPO_ROOT / "benchmarks" / "pr15d" / "corpus" / "oracle.py"

CLASSES = ("absent", "rare", "medium", "common")
CORPUS_SIZES = (10000, 100000)
TOP_K_VALUES = (10, 100)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def lane_id_for(corpus_size: int, selectivity_class: str, top_k: int) -> str:
    """Independent restatement of the frozen lane identifier format."""

    return "n%06d-%s-k%03d-warm" % (corpus_size, selectivity_class, top_k)


def independent_formula(corpus_size: int, selectivity_class: str) -> tuple[int, list[str]]:
    """Independent restatement of the frozen PR15D corpus membership formula."""

    rows = []
    for index in range(corpus_size):
        doc_id = "d%08d" % index
        key = "singleton" if index == 0 else "common" if index % 2 == 0 else "other"
        group = "medium" if index % 8 == 0 else "different"
        rows.append((doc_id, key, group))
    field = "group" if selectivity_class == "medium" else "key"
    term = {
        "absent": "never",
        "rare": "singleton",
        "medium": "medium",
        "common": "common",
    }[selectivity_class]
    position = 2 if field == "group" else 1
    matches = [row[0] for row in rows if row[position] == term]
    return len(matches), matches


def load_historical_oracle() -> Any:
    """Load the read-only historical corpus oracle module (test-only import)."""

    spec = importlib.util.spec_from_file_location(
        "bm08_historical_pr15d_oracle", HISTORICAL_ORACLE
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise AssertionError("the historical oracle module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OracleTests(unittest.TestCase):
    """ORA-01…ORA-08."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle, cls.digests = validate_cross_engine_reference(EXPERIMENTS, REPO_ROOT)
        cls.bundle_lanes = {lane.lane_id: lane for lane in cls.bundle.workload.lanes}

    def test_ora_01_exact_hit_cardinality_and_ids_for_the_frozen_matrix(self) -> None:
        expected_totals = {
            (10000, "absent"): 0,
            (10000, "rare"): 1,
            (10000, "medium"): 1250,
            (10000, "common"): 4999,
            (100000, "absent"): 0,
            (100000, "rare"): 1,
            (100000, "medium"): 12500,
            (100000, "common"): 49999,
        }
        for (corpus_size, selectivity_class), total in expected_totals.items():
            with self.subTest(corpus_size=corpus_size, selectivity_class=selectivity_class):
                computed_total, computed_ids = independent_formula(
                    corpus_size, selectivity_class
                )
                self.assertEqual(computed_total, total)
                for top_k in TOP_K_VALUES:
                    row = compute_oracle_row(corpus_size, selectivity_class, top_k)
                    self.assertEqual(row["total_hits"], total)
                    self.assertEqual(
                        row["doc_ids"], computed_ids[: min(top_k, total)]
                    )
                    self.assertEqual(
                        row["lane_id"], lane_id_for(corpus_size, selectivity_class, top_k)
                    )

    def test_ora_02_oracle_ids_match_the_original_read_only_oracle_module(self) -> None:
        oracle = load_historical_oracle()
        for corpus_size in CORPUS_SIZES:
            rows = oracle.build_row_formula(corpus_size)
            for selectivity_class, field, term in oracle.CLASSES:
                historical = oracle.expected(rows, field, term, 100)
                production = compute_oracle_row(corpus_size, selectivity_class, 100)
                self.assertEqual(production["total_hits"], historical["total_hits"])
                self.assertEqual(production["doc_ids"], historical["doc_ids"])
                self.assertEqual(production["field"], field)
                self.assertEqual(production["term"], term)

    def test_ora_03_every_declared_lane_matches_its_golden_row(self) -> None:
        golden = validate_oracle_golden(read_json(CATALOG / "oracle-golden.v1.json"))
        by_lane = {row["lane_id"]: row for row in golden}
        self.assertEqual(tuple(by_lane), expected_lane_ids())
        for lane_id, lane in self.bundle_lanes.items():
            row = oracle_row_for_lane(lane)
            self.assertEqual(row, by_lane[lane_id])
            self.assertEqual(
                len(row["doc_ids"]), min(row["top_k"], row["total_hits"])
            )

    def test_ora_04_missing_extra_and_duplicate_ids_are_rejected(self) -> None:
        base = read_json(CATALOG / "oracle-golden.v1.json")
        mutations = []
        missing = copy.deepcopy(base)
        missing["rows"][4]["doc_ids"] = missing["rows"][4]["doc_ids"][:-1]
        mutations.append(missing)
        extra = copy.deepcopy(base)
        extra["rows"][4]["doc_ids"] = extra["rows"][4]["doc_ids"] + ["d99999998"]
        mutations.append(extra)
        duplicate = copy.deepcopy(base)
        duplicate["rows"][4]["doc_ids"] = [
            duplicate["rows"][4]["doc_ids"][0]
        ] + duplicate["rows"][4]["doc_ids"][:-1]
        mutations.append(duplicate)
        for document in mutations:
            with self.subTest(row=document["rows"][4]["lane_id"]):
                with self.assertRaises(BenchError) as raised:
                    validate_oracle_golden(document)
                self.assertIn(raised.exception.code, {BM_IDENTITY_INVALID, BM_SCHEMA_INVALID})

    def test_ora_05_reversed_order_is_rejected(self) -> None:
        base = read_json(CATALOG / "oracle-golden.v1.json")
        reversed_row = copy.deepcopy(base)
        target = next(
            row for row in reversed_row["rows"] if row["lane_id"] == "n010000-common-k010-warm"
        )
        target["doc_ids"] = list(reversed(target["doc_ids"]))
        with self.assertRaises(BenchError) as raised:
            validate_oracle_golden(reversed_row)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_ora_06_count_only_matches_are_rejected(self) -> None:
        base = read_json(CATALOG / "oracle-golden.v1.json")
        target = next(
            row for row in base["rows"] if row["lane_id"] == "n100000-medium-k010-warm"
        )
        target["doc_ids"] = [
            target["doc_ids"][0],
            target["doc_ids"][2],
            target["doc_ids"][1],
        ] + target["doc_ids"][3:]
        # Same cardinality, wrong ordered content: never an acceptable match.
        self.assertEqual(len(target["doc_ids"]), 10)
        with self.assertRaises(BenchError) as raised:
            validate_oracle_golden(base)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_ora_07_wrong_field_or_term_is_rejected(self) -> None:
        base = read_json(CATALOG / "oracle-golden.v1.json")
        wrong_field = copy.deepcopy(base)
        wrong_field["rows"][0]["field"] = "body"
        with self.assertRaises(BenchError):
            validate_oracle_golden(wrong_field)
        wrong_term = copy.deepcopy(base)
        wrong_term["rows"][1]["term"] = "common"
        with self.assertRaises(BenchError):
            validate_oracle_golden(wrong_term)

    def test_ora_08_bad_types_and_out_of_matrix_cells_are_rejected(self) -> None:
        base = read_json(CATALOG / "oracle-golden.v1.json")
        boolean_k = copy.deepcopy(base)
        boolean_k["rows"][0]["top_k"] = True
        with self.assertRaises(BenchError) as raised:
            validate_oracle_golden(boolean_k)
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

        bad_corpus = copy.deepcopy(base)
        bad_corpus["rows"][0]["corpus_size"] = 12345
        with self.assertRaises(BenchError):
            validate_oracle_golden(bad_corpus)

        bad_class = copy.deepcopy(base)
        bad_class["rows"][0]["selectivity_class"] = "scoring"
        with self.assertRaises(BenchError):
            validate_oracle_golden(bad_class)

        float_total = copy.deepcopy(base)
        float_total["rows"][0]["total_hits"] = 0.0
        with self.assertRaises(BenchError) as raised:
            validate_oracle_golden(float_total)
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

        unknown_field = copy.deepcopy(base)
        unknown_field["rows"][0]["engine_ns"] = 1
        with self.assertRaises(BenchError) as raised:
            validate_oracle_golden(unknown_field)
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

        with self.assertRaises(BenchError):
            compute_oracle_row(10000, "absent", 0)
        with self.assertRaises(BenchError):
            compute_oracle_row(10000, "absent", 1)


class WireProjectionTests(unittest.TestCase):
    """WIR-01…WIR-10."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle, _digests = validate_cross_engine_reference(EXPERIMENTS, REPO_ROOT)
        cls.lanes = list(cls.bundle.workload.lanes)
        cls.rows = {row["lane_id"]: row for row in (
            oracle_row_for_lane(lane) for lane in cls.lanes
        )}

    def _projection(self, lane: Lane, engine_id: str) -> dict[str, Any]:
        row = self.rows[lane.lane_id]
        return {
            "schema": "pr15d-adapter-v1",
            "engine": engine_id,
            "request_id": "query-" + lane.lane_id,
            "status": "ok",
            "total_hits": row["total_hits"],
            "doc_ids": list(row["doc_ids"]),
        }

    def test_wir_01_all_48_projections_validate(self) -> None:
        validated = 0
        for engine_id in ENGINE_IDS:
            for lane in self.lanes:
                validate_keyword_reply_projection(
                    lane, engine_id, self._projection(lane, engine_id), self.rows[lane.lane_id]
                )
                validated += 1
        self.assertEqual(validated, 48)

    def test_wir_02_timed_and_extra_fields_are_rejected(self) -> None:
        lane = self.lanes[4]
        for field, value in (
            ("engine_ns", 1),
            ("wall_ns", 1),
            ("duration", 1),
            ("benchmark_result", {}),
            ("score", 1.0),
            ("build_identity", "source-and-binary"),
        ):
            with self.subTest(field=field):
                projection = self._projection(lane, "quervant")
                projection[field] = value
                with self.assertRaises(BenchError) as raised:
                    validate_keyword_reply_projection(
                        lane, "quervant", projection, self.rows[lane.lane_id]
                    )
                self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

        missing = self._projection(lane, "quervant")
        missing.pop("status")
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(
                lane, "quervant", missing, self.rows[lane.lane_id]
            )

    def test_wir_03_wrong_engine_schema_and_request_id_are_rejected(self) -> None:
        lane = self.lanes[2]
        row = self.rows[lane.lane_id]
        wrong_engine = self._projection(lane, "tantivy")
        wrong_engine["engine"] = "quervant"
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "tantivy", wrong_engine, row)
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "opensearch", self._projection(lane, "tantivy"), row)

        wrong_schema = self._projection(lane, "lucene")
        wrong_schema["schema"] = "pr15d-adapter-v2"
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "lucene", wrong_schema, row)

        wrong_request = self._projection(lane, "lucene")
        wrong_request["request_id"] = "query-n010000-absent-k010-warm"
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "lucene", wrong_request, row)

        bad_status = self._projection(lane, "lucene")
        bad_status["status"] = "error"
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "lucene", bad_status, row)

    def test_wir_04_bad_total_hits_are_rejected(self) -> None:
        lane = self.lanes[6]
        row = self.rows[lane.lane_id]
        for value in (True, -1, 1.0, "10"):
            with self.subTest(value=value):
                projection = self._projection(lane, "quervant")
                projection["total_hits"] = value
                with self.assertRaises(BenchError):
                    validate_keyword_reply_projection(lane, "quervant", projection, row)
        off_by_one = self._projection(lane, "quervant")
        off_by_one["total_hits"] = row["total_hits"] + 1
        with self.assertRaises(BenchError) as raised:
            validate_keyword_reply_projection(lane, "quervant", off_by_one, row)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_wir_05_doc_id_mismatch_order_and_length_are_rejected(self) -> None:
        lane = self.lanes[5]
        row = self.rows[lane.lane_id]
        self.assertGreater(len(row["doc_ids"]), 3)

        wrong_order = self._projection(lane, "quervant")
        wrong_order["doc_ids"] = list(reversed(row["doc_ids"]))
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "quervant", wrong_order, row)

        too_short = self._projection(lane, "quervant")
        too_short["doc_ids"] = row["doc_ids"][:-1]
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "quervant", too_short, row)

        wrong_id = self._projection(lane, "quervant")
        wrong_id["doc_ids"] = row["doc_ids"][:-1] + ["d99999999"]
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "quervant", wrong_id, row)

        upper = self._projection(lane, "quervant")
        upper["doc_ids"] = [value.upper() for value in row["doc_ids"]]
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "quervant", upper, row)

    def test_wir_06_count_only_projection_is_rejected(self) -> None:
        lane = self.lanes[7]
        row = self.rows[lane.lane_id]
        count_only = self._projection(lane, "quervant")
        count_only["doc_ids"] = []
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "quervant", count_only, row)

    def test_wir_07_non_mappings_and_foreign_oracle_rows_are_rejected(self) -> None:
        lane = self.lanes[0]
        row = self.rows[lane.lane_id]
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "quervant", ["not", "a", "map"], row)
        foreign = dict(row)
        foreign["lane_id"] = "n010000-absent-k100-warm"
        with self.assertRaises(BenchError):
            validate_keyword_reply_projection(lane, "quervant", self._projection(lane, "quervant"), foreign)

    def test_wir_08_projection_is_derived_only_from_the_reviewed_oracle(self) -> None:
        # The projection generator is fed the reviewed oracle row, never a live
        # adapter response and never another engine's reply.
        for engine_id in ENGINE_IDS:
            for lane in self.lanes:
                projection = self._projection(lane, engine_id)
                self.assertEqual(projection["doc_ids"], self.rows[lane.lane_id]["doc_ids"])
                self.assertEqual(
                    projection["total_hits"], self.rows[lane.lane_id]["total_hits"]
                )


class SourceBindingTests(unittest.TestCase):
    """SRC-01…SRC-06."""

    def setUp(self) -> None:
        self.document = read_json(CATALOG / "engine-source-bindings.v1.json")

    def test_src_01_source_bytes_and_versions_are_bound(self) -> None:
        digest = validate_engine_source_bindings(REPO_ROOT, self.document)
        self.assertEqual(digest, content_digest(self.document))
        engines = {entry["engine_id"]: entry for entry in self.document["engines"]}
        self.assertEqual(tuple(engines), ENGINE_IDS)
        for engine_id, entry in engines.items():
            self.assertEqual(entry["declared_engine_version"], DECLARED_ENGINE_VERSIONS[engine_id])
            self.assertEqual(entry["source_qualification"], "SOURCE_ONLY_NOT_BUILT")
            self.assertEqual(entry["adapter_schema"], "pr15d-adapter-v1")
            self.assertEqual(entry["analyzer"], "keyword-exact")
            paths = tuple(item["path"] for item in entry["source_files"])
            self.assertEqual(paths, SOURCE_FILE_ALLOWLIST[engine_id])
            for item in entry["source_files"]:
                payload = (REPO_ROOT / item["path"]).read_bytes()
                self.assertEqual(item["byte_length"], len(payload))
                self.assertEqual(
                    item["sha256"], "sha256:" + hashlib.sha256(payload).hexdigest()
                )

    def test_src_02_mutated_source_or_pin_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for engine_id, paths in SOURCE_FILE_ALLOWLIST.items():
                for relative in paths:
                    destination = root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes((REPO_ROOT / relative).read_bytes())
            # Baseline: the copied tree is identical.
            validate_engine_source_bindings(root, self.document)

            changed = root / "benchmarks/pr15d/adapters/tantivy/src/main.rs"
            changed.write_bytes(changed.read_bytes() + b"\n")
            with self.assertRaises(BenchError) as raised:
                validate_engine_source_bindings(root, self.document)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_src_03_changed_pin_inside_identical_bytes_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for paths in SOURCE_FILE_ALLOWLIST.values():
                for relative in paths:
                    destination = root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes((REPO_ROOT / relative).read_bytes())
            pin = root / "benchmarks/pr15d/adapters/tantivy/Cargo.toml"
            payload = pin.read_bytes().replace(b'tantivy = "=0.22.1"', b'tantivy = "0.22.1"')
            pin.write_bytes(payload)

            document = copy.deepcopy(self.document)
            for entry in document["engines"]:
                for item in entry["source_files"]:
                    if item["path"] == "benchmarks/pr15d/adapters/tantivy/Cargo.toml":
                        item["byte_length"] = len(payload)
                        item["sha256"] = "sha256:" + hashlib.sha256(payload).hexdigest()
            with self.assertRaises(BenchError) as raised:
                validate_engine_source_bindings(root, document)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_src_04_binary_identity_claims_and_extra_engines_are_rejected(self) -> None:
        claimed = copy.deepcopy(self.document)
        claimed["engines"][0]["source_qualification"] = "SOURCE_AND_BINARY_VERIFIED"
        with self.assertRaises(BenchError):
            validate_engine_source_bindings(REPO_ROOT, claimed)

        extra = copy.deepcopy(self.document)
        extra["engines"].append(copy.deepcopy(extra["engines"][0]))
        extra["engines"][-1]["engine_id"] = "opensearch"
        with self.assertRaises(BenchError):
            validate_engine_source_bindings(REPO_ROOT, extra)

        wrong_version = copy.deepcopy(self.document)
        wrong_version["engines"][1]["declared_engine_version"] = "quervant-core 0.2.0"
        with self.assertRaises(BenchError):
            validate_engine_source_bindings(REPO_ROOT, wrong_version)

    def test_src_05_filesystem_escape_is_rejected(self) -> None:
        escaped = copy.deepcopy(self.document)
        escaped["engines"][0]["source_files"][0]["path"] = "../outside.rs"
        with self.assertRaises(BenchError):
            validate_engine_source_bindings(REPO_ROOT, escaped)
        absolute = copy.deepcopy(self.document)
        absolute["engines"][0]["source_files"][0]["path"] = "/etc/passwd"
        with self.assertRaises(BenchError):
            validate_engine_source_bindings(REPO_ROOT, absolute)

    def test_src_06_symlinked_source_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for paths in SOURCE_FILE_ALLOWLIST.values():
                for relative in paths:
                    destination = root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes((REPO_ROOT / relative).read_bytes())
            target = root / "benchmarks/pr15d/adapters/quervant/src/main.rs"
            original = target.read_bytes()
            target.unlink()
            outside = root / "outside.rs"
            outside.write_bytes(original)
            import os

            os.symlink(outside, target)
            with self.assertRaises(BenchError) as raised:
                validate_engine_source_bindings(root, self.document)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


class ForgedOracleRowTests(unittest.TestCase):
    """WFX-01…WFX-08: RF08-01 caller-supplied oracle rows are untrusted."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle, _digests = validate_cross_engine_reference(EXPERIMENTS, REPO_ROOT)
        cls.lanes = {lane.lane_id: lane for lane in cls.bundle.workload.lanes}
        cls.rows = {
            row["lane_id"]: row for row in validate_oracle_golden(
                read_json(CATALOG / "oracle-golden.v1.json")
            )
        }

    def _rare_lane(self) -> Lane:
        return self.lanes["n010000-rare-k010-warm"]

    def _row(self, lane: Lane) -> dict[str, Any]:
        return dict(self.rows[lane.lane_id])

    def _reply(self, lane: Lane, row: dict[str, Any], engine: str = "quervant") -> dict[str, Any]:
        return {
            "schema": "pr15d-adapter-v1",
            "engine": engine,
            "request_id": "query-" + lane.lane_id,
            "status": "ok",
            "total_hits": row["total_hits"],
            "doc_ids": list(row["doc_ids"]),
        }

    def _expect_rejection(self, lane: Lane, row: dict[str, Any], code: str, field: str) -> None:
        with self.assertRaises(BenchError) as raised:
            validate_keyword_reply_projection(
                lane, "quervant", self._reply(lane, row), row
            )
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.field_path, field)

    def test_wfx_01_all_48_engine_lane_projections_validate(self) -> None:
        validated = 0
        for engine_id in ENGINE_IDS:
            for lane in self.lanes.values():
                row = self._row(lane)
                validate_keyword_reply_projection(
                    lane, engine_id, self._reply(lane, row, engine_id), row
                )
                validated += 1
        self.assertEqual(validated, 48)

    def test_wfx_02_forged_count_and_ids_are_rejected(self) -> None:
        lane = self._rare_lane()
        row = self._row(lane)
        row["total_hits"] = 2
        row["doc_ids"] = ["d00000000", "d00000001"]
        self._expect_rejection(lane, row, BM_IDENTITY_INVALID, "oracle_row.total_hits")

    def test_wfx_03_forged_singleton_id_is_rejected(self) -> None:
        lane = self._rare_lane()
        row = self._row(lane)
        self.assertEqual(row["total_hits"], 1)
        row["doc_ids"] = ["d00000001"]
        self._expect_rejection(lane, row, BM_IDENTITY_INVALID, "oracle_row.doc_ids")

    def test_wfx_04_forged_field_with_matching_counts_is_rejected(self) -> None:
        lane = self._rare_lane()
        row = self._row(lane)
        row["field"] = "group"
        self._expect_rejection(lane, row, BM_IDENTITY_INVALID, "oracle_row.field")

        wrong_term = self._row(lane)
        wrong_term["term"] = "common"
        self._expect_rejection(
            lane, wrong_term, BM_IDENTITY_INVALID, "oracle_row.term"
        )

    def test_wfx_05_bool_total_hits_is_rejected(self) -> None:
        lane = self._rare_lane()
        row = self._row(lane)
        self.assertEqual(row["total_hits"], 1)
        row["total_hits"] = True  # True == 1 in Python; must not be accepted
        self._expect_rejection(lane, row, BM_SCHEMA_INVALID, "oracle_row.total_hits")

        bool_top_k = self._row(lane)
        bool_top_k["top_k"] = True
        self._expect_rejection(lane, bool_top_k, BM_SCHEMA_INVALID, "oracle_row.top_k")

    def test_wfx_06_closed_row_and_malformed_ids_are_rejected(self) -> None:
        lane = self._rare_lane()
        missing = self._row(lane)
        missing.pop("term")
        self._expect_rejection(lane, missing, BM_SCHEMA_INVALID, "oracle_row")

        extra = self._row(lane)
        extra["engine_ns"] = 1
        self._expect_rejection(lane, extra, BM_SCHEMA_INVALID, "oracle_row")

        not_a_list = self._row(lane)
        not_a_list["doc_ids"] = "d00000000"
        self._expect_rejection(lane, not_a_list, BM_SCHEMA_INVALID, "oracle_row.doc_ids")

        malformed = self._row(lane)
        malformed["doc_ids"] = ["D00000000"]
        self._expect_rejection(lane, malformed, BM_IDENTITY_INVALID, "oracle_row.doc_ids")

        descending = self._row(self.lanes["n010000-medium-k010-warm"])
        descending["doc_ids"] = list(reversed(descending["doc_ids"]))
        self._expect_rejection(
            self.lanes["n010000-medium-k010-warm"],
            descending,
            BM_IDENTITY_INVALID,
            "oracle_row.doc_ids",
        )

    def test_wfx_07_empty_answer_and_k_truncation(self) -> None:
        absent = self.lanes["n100000-absent-k100-warm"]
        absent_row = self._row(absent)
        self.assertEqual(absent_row["total_hits"], 0)
        validate_keyword_reply_projection(
            absent, "lucene", self._reply(absent, absent_row, "lucene"), absent_row
        )

        medium = self.lanes["n100000-medium-k010-warm"]
        medium_row = self._row(medium)
        self.assertEqual(len(medium_row["doc_ids"]), 10)
        self.assertGreater(medium_row["total_hits"], 10)
        validate_keyword_reply_projection(
            medium, "tantivy", self._reply(medium, medium_row, "tantivy"), medium_row
        )

        count_only = self._reply(medium, medium_row, "tantivy")
        count_only["doc_ids"] = medium_row["doc_ids"][:1]
        with self.assertRaises(BenchError) as raised:
            validate_keyword_reply_projection(
                medium, "tantivy", count_only, medium_row
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "doc_ids")

    def test_wfx_08_timed_or_extra_reply_fields_are_rejected(self) -> None:
        lane = self._rare_lane()
        row = self._row(lane)
        for field, value in (
            ("engine_ns", 1),
            ("score", 1.0),
            ("build_identity", "source-and-binary"),
        ):
            with self.subTest(field=field):
                reply = self._reply(lane, row)
                reply[field] = value
                with self.assertRaises(BenchError) as raised:
                    validate_keyword_reply_projection(lane, "quervant", reply, row)
                self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

        foreign = self._reply(lane, row)
        with self.assertRaises(BenchError) as raised:
            validate_keyword_reply_projection(lane, "opensearch", foreign, row)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
