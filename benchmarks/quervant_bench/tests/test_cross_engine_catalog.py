"""CAT/BND/CMP/ANC evidence for the cross-engine reference catalog."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.codec import (
    canonical_document_bytes,
    content_digest,
    load_document,
)
from quervant_bench.config.errors import (
    BM_DUPLICATE_KEY,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.migrations.cross_engine import (
    EXPECTED_CATALOG_RAW_SHA256,
    EXPECTED_PROTOCOL_CONTENT_DIGEST,
    REFERENCE_EXPERIMENT_ID,
    REQUIRED_CATALOG_FILES,
    load_cross_engine_reference,
    validate_cross_engine_reference,
)
from quervant_bench.migrations.cross_engine_contract import (
    ARM_IDS,
    BASELINE_ARM_ID,
    CANDIDATE_ORDER,
    EXCLUDED_CLASSES,
    expected_lane_ids,
    validate_engine_source_bindings,
    validate_oracle_golden,
    validate_semantic_comparability,
)
from quervant_bench.qualification.identity import (
    SOURCE_DIRECTORIES,
    source_roster,
)
from quervant_bench.tests.cross_engine_support import (
    CATALOG,
    EXPERIMENTS,
    EXPECTATIONS,
    REPO_ROOT,
    CatalogEditor,
    copy_catalog,
    read_json,
    write_canonical,
)
from quervant_bench.tests.test_qualification_contracts import materialize_source_tree

ARMS = EXPECTATIONS["arm_ids"]
LANES = EXPECTATIONS["lane_ids"]


def expect_code(test: unittest.TestCase, code: str, callable_) -> BenchError:
    with test.assertRaises(BenchError) as raised:
        callable_()
    test.assertEqual(raised.exception.code, code, raised.exception.message)
    return raised.exception


class CatalogTests(unittest.TestCase):
    """CAT-01…CAT-04."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle, cls.digests = validate_cross_engine_reference(EXPERIMENTS, REPO_ROOT)

    def test_cat_01_bundle_identity_matrix_and_digests_are_exact(self) -> None:
        self.assertEqual(self.bundle.experiment.experiment_id, REFERENCE_EXPERIMENT_ID)
        self.assertEqual([arm.arm_id for arm in self.bundle.experiment.arms], ARMS)
        self.assertEqual(
            [lane.lane_id for lane in self.bundle.workload.lanes], LANES
        )
        self.assertEqual(
            self.bundle.workload.workload_id, "cross-engine-synthetic-keyword"
        )
        self.assertEqual(
            self.bundle.protocol.protocol_id, "cross-engine-synthetic-paired"
        )
        self.assertEqual(self.bundle.adapter.adapter_id, "synthetic-execution")
        self.assertEqual(self.bundle.adapter.engine_id, "synthetic")
        self.assertEqual(self.bundle.adapter.build_identity.kind, "synthetic")
        self.assertEqual(
            self.bundle.protocol.workload_digest,
            content_digest(load_document(CATALOG / "workloads.yaml")),
        )
        self.assertEqual(
            sorted(entry.name for entry in CATALOG.iterdir()),
            sorted(REQUIRED_CATALOG_FILES),
        )
        self.assertEqual(len(REQUIRED_CATALOG_FILES), 11)
        for name in REQUIRED_CATALOG_FILES:
            payload = (CATALOG / name).read_bytes()
            self.assertEqual(
                payload,
                canonical_document_bytes(load_document(CATALOG / name)),
                name,
            )

    def test_cat_02_foreign_identifiers_and_extra_arms_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(root)
            experiment = editor.documents["experiment.yaml"]
            experiment["arms"].append(
                {
                    "arm_id": "opensearch",
                    "adapter_id": "synthetic-execution",
                    "variant": "opensearch",
                }
            )
            protocol = editor.documents["protocol.yaml"]
            protocol["arm_multiplicity"].append(
                {"arm_id": "opensearch", "slots_per_block": 2}
            )
            protocol["schedule"]["slots_per_block"] = 8
            editor.write()
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            experiment_path = root / REFERENCE_EXPERIMENT_ID / "experiment.yaml"
            document = read_json(experiment_path)
            document["experiment_id"] = "synthetic-foreign-experiment"
            write_canonical(experiment_path, document)
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )

    def test_cat_03_lane_matrix_is_exactly_the_frozen_sixteen(self) -> None:
        self.assertEqual(tuple(LANES), expected_lane_ids())
        self.assertEqual(len(LANES), 16)
        for lane in self.bundle.workload.lanes:
            self.assertEqual(lane.operation, "search")
            self.assertEqual(lane.cache_regime, "warm")
            self.assertEqual(
                set(lane.params),
                {"corpus_size", "top_k", "selectivity_class", "query_id"},
            )
            self.assertEqual(lane.params["query_id"], lane.lane_id)
            self.assertIn(lane.params["corpus_size"], (10000, 100000))
            self.assertIn(lane.params["top_k"], (10, 100))
            self.assertIn(
                lane.params["selectivity_class"], ("absent", "rare", "medium", "common")
            )

    def test_cat_04_missing_extra_unsafe_and_unknown_entries_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            (root / REFERENCE_EXPERIMENT_ID / "oracle-golden.v1.json").unlink()
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            write_canonical(
                root / REFERENCE_EXPERIMENT_ID / "unexpected.v1.json", {"kind": "no"}
            )
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            target = root / REFERENCE_EXPERIMENT_ID / "semantic-comparability.v1.json"
            original = target.read_bytes()
            target.unlink()
            outside = root / "ledger.json"
            outside.write_bytes(original)
            os.symlink(outside, target)
            expect_code(
                self,
                BM_UNSAFE_INPUT,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            target = root / REFERENCE_EXPERIMENT_ID / "oracle-golden.v1.json"
            target.write_bytes(b"{not canonical json}\n")
            # Reviewed raw-byte pins precede JSON decoding: any byte change is an
            # identity violation, not a tolerable schema repair.
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            target = root / REFERENCE_EXPERIMENT_ID / "semantic-comparability.v1.json"
            document = read_json(target)
            document["kind"] = "cross-engine-semantic-comparability"
            target.write_bytes(
                json.dumps(document, sort_keys=True, indent=2).encode() + b"\n"
            )
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            target = root / REFERENCE_EXPERIMENT_ID / "semantic-comparability.v1.json"
            payload = target.read_text(encoding="utf-8").rstrip("\n")
            self.assertTrue(payload.endswith("}"))
            target.write_text(
                payload[:-1] + ',"kind":"duplicate-kind"}\n', encoding="utf-8"
            )
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(root)
            editor.documents["engine-source-bindings.v1.json"]["engines"][0][
                "unexpected"
            ] = "field"
            editor.write()
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )
            with self.assertRaises(BenchError) as shaped:
                validate_engine_source_bindings(
                    REPO_ROOT,
                    editor.documents["engine-source-bindings.v1.json"],
                )
            self.assertEqual(shaped.exception.code, BM_SCHEMA_INVALID)


class BindingTests(unittest.TestCase):
    """BND-01…BND-03."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle, cls.digests = validate_cross_engine_reference(EXPERIMENTS, REPO_ROOT)

    def test_bnd_01_digest_chain_binds_ledger_golden_and_sources(self) -> None:
        ledger = read_json(CATALOG / "semantic-comparability.v1.json")
        golden = read_json(CATALOG / "oracle-golden.v1.json")
        bindings = read_json(CATALOG / "engine-source-bindings.v1.json")
        workload = load_document(CATALOG / "workloads.yaml")
        protocol = load_document(CATALOG / "protocol.yaml")
        self.assertEqual(workload["dataset"]["digest"], content_digest(ledger))
        self.assertEqual(ledger["oracle_golden_digest"], content_digest(golden))
        self.assertEqual(
            ledger["engine_source_bindings_digest"], content_digest(bindings)
        )
        self.assertEqual(protocol["workload_digest"], content_digest(workload))
        self.assertEqual(
            self.digests.semantic_comparability_digest,
            self.bundle.workload.dataset.digest,
        )
        self.assertEqual(self.digests.oracle_golden_digest, content_digest(golden))
        self.assertEqual(
            self.digests.engine_source_bindings_digest, content_digest(bindings)
        )

    def test_bnd_02_mutating_one_document_without_rebinding_is_rejected(self) -> None:
        for name in (
            "oracle-golden.v1.json",
            "engine-source-bindings.v1.json",
            "semantic-comparability.v1.json",
        ):
            with self.subTest(document=name):
                with tempfile.TemporaryDirectory() as temporary:
                    root = copy_catalog(Path(temporary) / "catalog")
                    target = root / REFERENCE_EXPERIMENT_ID / name
                    document = read_json(target)
                    local_digest = content_digest(document)
                    document["schema_version"] = 1
                    document["_local_hash"] = local_digest
                    write_canonical(target, document)
                    # The reviewed raw-byte pin is the first barrier and rejects
                    # any unapproved member bytes.
                    with self.assertRaises(BenchError) as raised:
                        validate_cross_engine_reference(root, REPO_ROOT)
                    self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                    self.assertEqual(
                        raised.exception.field_path, f"catalog.{name}"
                    )
                    # The closed-shape companion validator still rejects too.
                    if name == "oracle-golden.v1.json":
                        with self.assertRaises(BenchError) as shaped:
                            validate_oracle_golden(document)
                    elif name == "engine-source-bindings.v1.json":
                        with self.assertRaises(BenchError) as shaped:
                            validate_engine_source_bindings(REPO_ROOT, document)
                    else:
                        with self.assertRaises(BenchError) as shaped:
                            validate_semantic_comparability(
                                document,
                                workload_lane_ids=LANES,
                                oracle_golden_digest=content_digest(
                                    read_json(
                                        root
                                        / REFERENCE_EXPERIMENT_ID
                                        / "oracle-golden.v1.json"
                                    )
                                ),
                                engine_source_bindings_digest="sha256:" + "1" * 64,
                                reference_spec_digest="sha256:" + "2" * 64,
                            )
                    self.assertEqual(shaped.exception.code, BM_SCHEMA_INVALID)

    def test_bnd_03_coherent_but_unauthorized_rehash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(root)
            row = next(
                item
                for item in editor.documents["oracle-golden.v1.json"]["rows"]
                if item["lane_id"] == "n010000-common-k010-warm"
            )
            row["doc_ids"] = list(reversed(row["doc_ids"]))
            editor.rebind()
            # The digest chain is now internally coherent; the independent exact
            # formula still rejects the altered golden.
            write = json.loads(
                canonical_document_bytes(editor.documents["semantic-comparability.v1.json"])
            )
            self.assertEqual(
                write["oracle_golden_digest"],
                content_digest(editor.documents["oracle-golden.v1.json"]),
            )
            editor.write()
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(root)
            editor.documents["workloads.yaml"]["dataset"]["digest"] = "sha256:" + "0" * 64
            editor.write()
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )


class ComparabilityTests(unittest.TestCase):
    """CMP-01…CMP-04."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle, cls.digests = validate_cross_engine_reference(EXPERIMENTS, REPO_ROOT)

    def test_cmp_01_only_sixteen_warm_keyword_lanes_are_admitted(self) -> None:
        ledger = read_json(CATALOG / "semantic-comparability.v1.json")
        self.assertEqual(ledger["comparable_lane_ids"], LANES)
        self.assertEqual(
            [lane.lane_id for lane in self.bundle.workload.lanes], LANES
        )
        self.assertTrue(
            all(lane.cache_regime == "warm" for lane in self.bundle.workload.lanes)
        )
        self.assertTrue(
            all(lane.operation == "search" for lane in self.bundle.workload.lanes)
        )

    def test_cmp_02_process_cold_and_scored_lanes_are_rejected(self) -> None:
        from quervant_bench.config.contracts import Lane, validate_workload
        from quervant_bench.migrations.cross_engine_contract import oracle_row_for_lane

        # Every catalog byte change is first refused by the reviewed raw pin; the
        # semantic exclusion remains enforced independently below.
        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(root)
            target = next(
                lane
                for lane in editor.documents["workloads.yaml"]["lanes"]
                if lane["lane_id"] == "n010000-medium-k010-warm"
            )
            target["cache_regime"] = "process-cold"
            editor.rebind()
            editor.write()
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )
            mutated = read_json(
                root / REFERENCE_EXPERIMENT_ID / "workloads.yaml"
            )
            lane_document = next(
                lane
                for lane in mutated["lanes"]
                if lane["lane_id"] == "n010000-medium-k010-warm"
            )
            with self.assertRaises(BenchError) as cold:
                oracle_row_for_lane(
                    Lane(
                        lane_id=lane_document["lane_id"],
                        operation=lane_document["operation"],
                        cache_regime=lane_document["cache_regime"],
                        params=dict(lane_document["params"]),
                    )
                )
            self.assertEqual(cold.exception.code, BM_IDENTITY_INVALID)

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(root)
            target = next(
                lane
                for lane in editor.documents["workloads.yaml"]["lanes"]
                if lane["lane_id"] == "n010000-medium-k010-warm"
            )
            target["params"]["scoring"] = "bm25"
            editor.rebind()
            editor.write()
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )
            mutated = read_json(
                root / REFERENCE_EXPERIMENT_ID / "workloads.yaml"
            )
            with self.assertRaises(BenchError) as scored:
                validate_workload(mutated)
            self.assertEqual(scored.exception.code, BM_SCHEMA_INVALID)

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(root)
            editor.documents["workloads.yaml"]["lanes"].append(
                {
                    "lane_id": "n010000-scored-k010-warm",
                    "operation": "search",
                    "cache_regime": "warm",
                    "params": {
                        "corpus_size": 10000,
                        "top_k": 10,
                        "selectivity_class": "absent",
                        "query_id": "n010000-scored-k010-warm",
                    },
                }
            )
            editor.rebind()
            editor.write()
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )
            mutated = read_json(
                root / REFERENCE_EXPERIMENT_ID / "workloads.yaml"
            )
            mutated_ids = [lane["lane_id"] for lane in mutated["lanes"]]
            self.assertIn("n010000-scored-k010-warm", mutated_ids)
            golden = read_json(
                root / REFERENCE_EXPERIMENT_ID / "oracle-golden.v1.json"
            )
            bindings = read_json(
                root / REFERENCE_EXPERIMENT_ID / "engine-source-bindings.v1.json"
            )
            with self.assertRaises(BenchError) as promoted:
                validate_semantic_comparability(
                    editor.documents["semantic-comparability.v1.json"],
                    workload_lane_ids=mutated_ids,
                    oracle_golden_digest=content_digest(golden),
                    engine_source_bindings_digest=content_digest(bindings),
                    reference_spec_digest=content_digest(
                        read_json(REPO_ROOT / "benchmarks/pr15d/spec/pr15d_v1.json")
                    ),
                )
            self.assertEqual(promoted.exception.code, BM_IDENTITY_INVALID)

    def test_cmp_03_excluded_classes_are_exact_and_absent_from_selection(self) -> None:
        ledger = read_json(CATALOG / "semantic-comparability.v1.json")
        self.assertEqual(ledger["excluded_classes"], list(EXCLUDED_CLASSES))
        excluded_ids = [entry["class_id"] for entry in ledger["excluded_classes"]]
        self.assertEqual(excluded_ids, ["index-throughput", "process-cold", "scored-bm25"])
        policy = read_json(CATALOG / "policy-profile.v1.json")
        named = (
            [rule["lane_id"] for rule in policy["targets"]]
            + [rule["lane_id"] for rule in policy["guardrails"]]
            + list(policy["selection"]["ranking_lanes"])
        )
        for lane_id in named:
            self.assertIn(lane_id, LANES)
            self.assertNotIn(lane_id, excluded_ids)
        for excluded in excluded_ids:
            self.assertNotIn(excluded, LANES)

    def test_cmp_04_promoting_an_excluded_class_by_rehash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(root)
            ledger = editor.documents["semantic-comparability.v1.json"]
            promoted = copy.deepcopy(ledger["excluded_classes"])
            for entry in promoted:
                if entry["class_id"] == "scored-bm25":
                    entry["status"] = "COMPARABLE"
                    entry["reason"] = "promoted-without-approval"
            ledger["excluded_classes"] = promoted
            editor.rebind()
            editor.write()
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(root)
            ledger = editor.documents["semantic-comparability.v1.json"]
            ledger["comparable_lane_ids"] = sorted(
                ledger["comparable_lane_ids"]
                + ["n010000-scored-k010-warm"]
            )
            editor.rebind()
            editor.write()
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            )

    def test_cmp_05_ledger_rejects_foreign_workload_lane_ids(self) -> None:
        ledger = read_json(CATALOG / "semantic-comparability.v1.json")
        golden = read_json(CATALOG / "oracle-golden.v1.json")
        bindings = read_json(CATALOG / "engine-source-bindings.v1.json")
        spec = read_json(REPO_ROOT / "benchmarks/pr15d/spec/pr15d_v1.json")
        with self.assertRaises(BenchError):
            validate_semantic_comparability(
                ledger,
                workload_lane_ids=list(LANES[:-1]),
                oracle_golden_digest=content_digest(golden),
                engine_source_bindings_digest=content_digest(bindings),
                reference_spec_digest=content_digest(spec),
            )


class AnchorRosterTests(unittest.TestCase):
    """ANC-01/ANC-03: new modules join the frozen source roster."""

    def test_anc_01_cross_engine_modules_are_in_the_source_roster(self) -> None:
        self.assertIn("benchmarks/quervant_bench/migrations", SOURCE_DIRECTORIES)
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_source_tree(Path(temporary) / "source")
            roster = source_roster(root)
            for name in (
                "cross_engine.py",
                "cross_engine_contract.py",
                "offline.py",
            ):
                self.assertIn(
                    f"benchmarks/quervant_bench/migrations/{name}", roster
                )
            for name in (
                "test_cross_engine_catalog.py",
                "test_cross_engine_semantics.py",
                "cross_engine_support.py",
            ):
                self.assertIn(
                    f"benchmarks/quervant_bench/tests/{name}", roster
                )

    def test_anc_03_untracked_or_symlinked_new_module_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_source_tree(Path(temporary) / "source")
            untracked = (
                root / "benchmarks/quervant_bench/migrations/cross_engine_extra.py"
            )
            untracked.write_text("# untracked\n", encoding="utf-8")
            expect_code(self, BM_UNSAFE_INPUT, lambda: source_roster(root))
            untracked.unlink()

            tracked = root / "benchmarks/quervant_bench/migrations/cross_engine.py"
            original = tracked.read_bytes()
            tracked.unlink()
            os.symlink(
                root / "benchmarks/quervant_bench/migrations/offline.py", tracked
            )
            expect_code(self, BM_UNSAFE_INPUT, lambda: source_roster(root))
            tracked.unlink()
            tracked.write_bytes(original)


class CatalogPinTests(unittest.TestCase):
    """CFX-01…CFX-05: reviewed v1 identity of all eleven catalog documents."""

    MUTATIONS: dict[str, str] = {
        name: name for name in REQUIRED_CATALOG_FILES
    }

    def _mutate(self, editor: CatalogEditor, name: str) -> None:
        """Apply one canonical, syntax-preserving edit to exactly one member."""

        documents = editor.documents
        if name == "adapter.yaml":
            documents[name]["provenance"]["notes"] += " Reviewed note. "
        elif name == "analysis-profile.v1.json":
            documents[name]["analysis_version"] = 2
        elif name == "engine-source-bindings.v1.json":
            documents[name]["engines"][0]["analyzer"] = "keyword-exact-v1"
        elif name == "experiment.yaml":
            documents[name]["description"] += " Reviewed revision. "
        elif name == "oracle-golden.v1.json":
            documents[name]["rows"][0]["term"] = "neverx"
        elif name == "policy-profile.v1.json":
            documents[name]["selection"]["tie_relative_delta"] = "0.040000000000"
        elif name == "protocol.yaml":
            documents[name]["schedule"]["seed"] = 43
        elif name == "resource-observations.v1.json":
            documents[name]["records"][0]["value_bytes"] = 1048577
        elif name == "semantic-comparability.v1.json":
            documents[name]["excluded_classes"][0]["reason"] = "changed"
        elif name == "synthetic-scenario.v1.json":
            documents[name]["scenario_id"] = "cross-engine-synthetic-scenario-rev"
        elif name == "workloads.yaml":
            documents[name]["provenance"]["notes"] += " Reviewed revision. "
        else:  # pragma: no cover - guarded by the exact member set
            raise AssertionError(name)

    def _expected_snapshot(self) -> str:
        members = [
            {"name": name, "sha256": "sha256:" + EXPECTED_CATALOG_RAW_SHA256[name]}
            for name in REQUIRED_CATALOG_FILES
        ]
        return content_digest(
            {
                "kind": "cross-engine-reviewed-catalog-snapshot",
                "schema_version": 1,
                "members": members,
            }
        )

    def test_cfx_01_reviewed_pins_and_snapshot_identity(self) -> None:
        self.assertEqual(len(EXPECTED_CATALOG_RAW_SHA256), 11)
        self.assertEqual(tuple(EXPECTED_CATALOG_RAW_SHA256), REQUIRED_CATALOG_FILES)
        self.assertEqual(
            EXPECTED_PROTOCOL_CONTENT_DIGEST,
            "sha256:d157326d84cb33280e3fd9f78ca12f0b8ef6e2e6c0ed3f926cf91f9d18fb91a1",
        )
        for name in REQUIRED_CATALOG_FILES:
            payload = (CATALOG / name).read_bytes()
            self.assertEqual(
                hashlib.sha256(payload).hexdigest(),
                EXPECTED_CATALOG_RAW_SHA256[name],
                name,
            )
        bundle, digests = validate_cross_engine_reference(EXPERIMENTS, REPO_ROOT)
        self.assertEqual(
            content_digest(dict(bundle.protocol_document)),
            EXPECTED_PROTOCOL_CONTENT_DIGEST,
        )
        self.assertEqual(digests.catalog_members_digest, self._expected_snapshot())
        _bundle, again = validate_cross_engine_reference(EXPERIMENTS, REPO_ROOT)
        self.assertEqual(again, digests)
        self.assertEqual(load_cross_engine_reference(EXPERIMENTS), bundle)

    def test_cfx_02_seed_change_is_rejected_at_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(root)
            self.assertEqual(editor.documents["protocol.yaml"]["schedule"]["seed"], 42)
            editor.documents["protocol.yaml"]["schedule"]["seed"] = 43
            editor.write()
            for call in (
                lambda: load_cross_engine_reference(root),
                lambda: validate_cross_engine_reference(root, REPO_ROOT),
            ):
                with self.assertRaises(BenchError) as raised:
                    call()
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                self.assertEqual(raised.exception.field_path, "catalog.protocol.yaml")
            self.assertFalse((Path(temporary) / "runs").exists())

    def test_cfx_03_each_member_is_individually_pinned(self) -> None:
        self.assertEqual(set(self.MUTATIONS), set(REQUIRED_CATALOG_FILES))
        for name in REQUIRED_CATALOG_FILES:
            with self.subTest(member=name):
                with tempfile.TemporaryDirectory() as temporary:
                    root = copy_catalog(Path(temporary) / "catalog")
                    editor = CatalogEditor(root)
                    self._mutate(editor, name)
                    editor.write()
                    mutated = (root / REFERENCE_EXPERIMENT_ID / name).read_bytes()
                    self.assertNotEqual(
                        hashlib.sha256(mutated).hexdigest(),
                        EXPECTED_CATALOG_RAW_SHA256[name],
                    )
                    with self.assertRaises(BenchError) as raised:
                        load_cross_engine_reference(root)
                    self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                    self.assertEqual(
                        raised.exception.field_path, f"catalog.{name}"
                    )

    def test_cfx_04_missing_extra_symlinked_directory_and_oversized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            (root / REFERENCE_EXPERIMENT_ID / "oracle-golden.v1.json").unlink()
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: load_cross_engine_reference(root),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            write_canonical(
                root / REFERENCE_EXPERIMENT_ID / "unexpected.v1.json", {"kind": "no"}
            )
            expect_code(
                self,
                BM_IDENTITY_INVALID,
                lambda: load_cross_engine_reference(root),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            target = root / REFERENCE_EXPERIMENT_ID / "workloads.yaml"
            original = target.read_bytes()
            target.unlink()
            outside = root / "workloads.json"
            outside.write_bytes(original)
            os.symlink(outside, target)
            expect_code(
                self,
                BM_UNSAFE_INPUT,
                lambda: load_cross_engine_reference(root),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            target = root / REFERENCE_EXPERIMENT_ID / "adapter.yaml"
            target.unlink()
            target.mkdir()
            expect_code(
                self,
                BM_UNSAFE_INPUT,
                lambda: load_cross_engine_reference(root),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            target = root / REFERENCE_EXPERIMENT_ID / "adapter.yaml"
            target.write_bytes(b"{" + b" " * (1_048_576 + 1) + b"}\n")
            expect_code(
                self,
                BM_UNSAFE_INPUT,
                lambda: load_cross_engine_reference(root),
            )

    def test_cfx_05_coherently_rehashed_v1_edit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            editor = CatalogEditor(root)
            editor.documents["workloads.yaml"]["provenance"]["notes"] = (
                "Internally coherent but unauthorized v1 workload revision."
            )
            editor.rebind()
            editor.write()
            changed = [
                name
                for name in REQUIRED_CATALOG_FILES
                if hashlib.sha256(
                    (root / REFERENCE_EXPERIMENT_ID / name).read_bytes()
                ).hexdigest()
                != EXPECTED_CATALOG_RAW_SHA256[name]
            ]
            self.assertTrue(changed)
            with self.assertRaises(BenchError) as raised:
                validate_cross_engine_reference(root, REPO_ROOT)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertEqual(raised.exception.field_path, f"catalog.{changed[0]}")


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
