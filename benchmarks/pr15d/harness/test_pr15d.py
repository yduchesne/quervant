#!/usr/bin/env python3
"""Deterministic PR15D tests (standard library only).

Real Tantivy/Lucene adapter smoke is gated on the exact pins and toolchains; a
missing gate is reported as SKIP, never as PASS. Every pure test runs without a
JVM, a Tantivy build or a qualified benchmark host.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(os.path.dirname(HERE), "corpus")
sys.path.insert(0, HERE)
sys.path.insert(0, CORPUS_DIR)

import aggregate  # noqa: E402
import generate  # noqa: E402
import smoke  # noqa: E402
import oracle  # noqa: E402
import run  # noqa: E402
import validate  # noqa: E402

SESSION = None


def setUpModule():
    global SESSION
    SESSION = tempfile.mkdtemp(prefix="pr15d-tests-")
    generate.generate(os.path.join(SESSION, "corpus"))
    SESSION_CORPUS = os.path.join(SESSION, "corpus")
    SESSION_MANIFEST, SESSION_ROWS = oracle.load_and_verify(SESSION_CORPUS)
    globals()["CORPUS"] = SESSION_CORPUS
    globals()["MANIFEST"] = SESSION_MANIFEST
    globals()["ROWS"] = SESSION_ROWS


def tearDownModule():
    if SESSION:
        shutil.rmtree(SESSION, ignore_errors=True)


def _manifest_sha(manifest):
    return oracle.sha256_bytes(oracle.canonical_json_bytes(manifest))


def _samples(base, seed):
    return [base + seed + index for index in range(run.MEASURED)]


def _make_lane(descriptor, rows, base):
    expected = oracle.expected(
        rows[descriptor["n"]],
        descriptor["field"],
        descriptor["term"],
        descriptor["k"],
    )
    samples = _samples(base, descriptor["k"])
    return {
        "id": descriptor["id"],
        "n": descriptor["n"],
        "class": descriptor["class"],
        "field": descriptor["field"],
        "term": descriptor["term"],
        "k": descriptor["k"],
        "regime": descriptor["regime"],
        "warmups": run.WARMUPS if descriptor["regime"] == "warm" else 0,
        "warmup_ids": [],
        "samples_ns": samples,
        "summary_ns": run.summarize(samples),
        "total_hits": expected["total_hits"],
        "doc_ids": expected["doc_ids"],
        "expected_total_hits": expected["total_hits"],
        "expected_doc_ids": expected["doc_ids"],
        "oracle_ok": True,
        "analyzer": run.ANALYZER,
        "contention": {"pre": "clear", "post": "clear"},
        "rss_peak_bytes": None,
        "cpu_ns": None,
        "allocations": "NOT_MEASURED",
    }


def _make_trial(engine, trial, base):
    lanes = [_make_lane(descriptor, ROWS, base) for descriptor in run.lane_descriptors()]
    build = {
        str(n): {
            "documents_indexed": n,
            "documents_verified": n,
            "expected_documents": n,
            "index_ns": 1_000_000 + n,
            "commit_ns": 500_000 + n,
            "reopen_ns": 400_000 + n,
            "index_bytes": 100_000 + n * (1 + run.ENGINES.index(engine)),
            "segment_count": 1,
            "verified": True,
        }
        for n in run.N_VALUES
    }
    throughput = [
        {
            "n": n,
            "lane_id": run.lane_id(n, "medium", 10),
            "requests": run.THROUGHPUT_REQUESTS,
            "wall_ns": 500_000_000,
            "serial_ops_per_second": 200.0,
            "label": "serial_ops_per_second",
        }
        for n in run.N_VALUES
    ]
    return {
        "schema": run.SCHEMA_TRIAL,
        "trial": trial,
        "engine": engine,
        "engine_version": f"{engine}-1.0",
        "adapter_version": "0.1.0",
        "source_sha": "a" * 40,
        "release_build": True,
        "host_fingerprint": "b" * 64,
        "filesystem": "ext4",
        "native_filesystem": True,
        "operator_idle_attested": True,
        "corpus_manifest_sha256": _manifest_sha(MANIFEST),
        "corpus_digests": {str(entry["n"]): entry["sha256"] for entry in MANIFEST["corpora"]},
        "analyzer_map": {"doc_id": run.ANALYZER, "key": run.ANALYZER, "group": run.ANALYZER},
        "build": build,
        "lanes": lanes,
        "throughput": throughput,
        "contention": [],
        "status": "ok",
        "qualified": True,
        "unqualified_reasons": [],
    }


BASE_NS = {"quervant": 1_000, "tantivy": 2_000, "lucene": 3_000}


def create_run(root, *, run_overrides=None, trial_mutator=None, drop_trial=None):
    os.makedirs(root, exist_ok=True)
    run_record = {
        "schema": run.SCHEMA_RUN,
        "run_id": os.path.basename(root),
        "source_sha": "a" * 40,
        "workload": run.WORKLOAD,
        "corpus_dir": CORPUS,
        "corpus_manifest_sha256": _manifest_sha(MANIFEST),
        "corpus_digests": {str(entry["n"]): entry["sha256"] for entry in MANIFEST["corpora"]},
        "environment": {},
        "host_fingerprint": "b" * 64,
        "filesystem": "ext4",
        "native_filesystem": True,
        "idle_attested": True,
        "trials": run.REQUIRED_TRIALS,
        "status": "complete",
        "qualified": True,
        "scored_lane": {
            "status": "SEMANTICALLY_NONCOMPARABLE",
            "reason": "test fixture",
        },
    }
    if run_overrides:
        run_record.update(run_overrides)
    run.write_json(os.path.join(root, "run.json"), run_record)
    for trial in range(1, run.REQUIRED_TRIALS + 1):
        for engine in run.ENGINES:
            manifest = _make_trial(engine, trial, BASE_NS[engine])
            if trial_mutator is not None:
                trial_mutator(engine, trial, manifest)
            if drop_trial and drop_trial(engine, trial):
                continue
            run.write_json(
                os.path.join(root, "trials", f"trial-{trial}", f"{engine}.json"),
                manifest,
            )
    return root


def freshness(root):
    path = os.path.join(root, "trials", "trial-1", "quervant.json")
    with open(path, "rb") as handle:
        return handle.read()


class CorpusTests(unittest.TestCase):
    # T01
    def test_t01_generator_is_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = generate.generate(first)
            b = generate.generate(second)
            self.assertEqual(a, b)
            for name in os.listdir(first):
                with open(os.path.join(first, name), "rb") as left:
                    with open(os.path.join(second, name), "rb") as right:
                        self.assertEqual(left.read(), right.read(), name)

    # T02
    def test_t02_exact_truth_table(self):
        expected = {
            "absent": 0,
            "rare": 1,
            "medium": {10000: 1250, 100000: 12500},
            "common": {10000: 4999, 100000: 49999},
        }
        for n in run.N_VALUES:
            rows = ROWS[n]
            for class_name, field, term in run.CLASSES:
                for k in run.K_VALUES:
                    result = oracle.expected(rows, field, term, k)
                    if class_name in ("absent", "rare"):
                        self.assertEqual(result["total_hits"], expected[class_name])
                    else:
                        self.assertEqual(result["total_hits"], expected[class_name][n])
                    self.assertEqual(
                        result["doc_ids"], sorted(result["doc_ids"])[:k]
                    )
        self.assertEqual(
            oracle.expected(ROWS[100000], "key", "singleton", 10)["doc_ids"],
            ["d00000000"],
        )

    # T03
    def test_t03_tampered_corpus_is_rejected_before_adapters(self):
        with tempfile.TemporaryDirectory() as directory:
            generate.generate(directory)
            path = os.path.join(directory, oracle.corpus_filename(10000))
            with open(path, "rb") as handle:
                payload = bytearray(handle.read())
            payload[100] = ord("X") if payload[100] != ord("X") else ord("Y")
            with open(path, "wb") as handle:
                handle.write(payload)
            with self.assertRaises(oracle.CorpusError) as caught:
                oracle.load_and_verify(directory)
            self.assertEqual(caught.exception.code, "corpus_digest_mismatch")

            # Missing row / duplicate ID are rejected by the strict parser.
            with self.assertRaises(oracle.CorpusError) as caught:
                oracle.parse_tsv_text(
                    oracle.HEADER
                    + "\n"
                    + "d00000000\tcommon\tdifferent\talpha beta\tp\n"
                    + "d00000000\tcommon\tdifferent\talpha beta\tp\n"
                )
            self.assertIn(caught.exception.code, {"duplicate_doc_id", "doc_id_not_increasing"})
            with self.assertRaises(oracle.CorpusError) as caught:
                oracle.parse_tsv_text(oracle.HEADER + "\nsingle\n")
            self.assertEqual(caught.exception.code, "row_arity")

            # Wrong manifest digest, recomputed oracle mismatch.
            with tempfile.TemporaryDirectory() as clean:
                generate.generate(clean)
                manifest, _ = oracle.load_and_verify(clean)
                tampered = copy.deepcopy(manifest)
                tampered["queries"][0]["total_hits"] = 1
                errors = oracle.verify_corpus(clean, tampered)
                self.assertTrue(any(e["code"] == "oracle_count_mismatch" for e in errors))


class ValidatorTests(unittest.TestCase):
    def assert_invalid(self, root, code):
        report = validate.validate_run(root)
        self.assertEqual(report["status"], "INVALID", report)
        self.assertIn(code, [error["code"] for error in report["errors"]], report)
        return report

    def assert_unqualified(self, root, code):
        report = validate.validate_run(root)
        self.assertEqual(report["status"], "UNQUALIFIED", report)
        self.assertIn(code, [error["code"] for error in report["unqualified"]], report)
        return report

    def test_valid_run_is_qualified_and_aggregates(self):
        with tempfile.TemporaryDirectory() as root:
            create_run(root)
            report = validate.validate_run(root)
            self.assertEqual(report["status"], "QUALIFIED", report)
            payload, markdown = aggregate.aggregate_bytes(root)
            self.assertEqual(
                json.loads(payload)["status"],
                "QUALIFIED",
            )
            self.assertIn(b"PR 15D comparative qualification", markdown)

    # T05
    def test_t05_analyzer_map_and_ordering_are_enforced(self):
        def mutate(engine, trial, manifest):
            if engine == "quervant" and trial == 1:
                manifest["analyzer_map"]["key"] = "standard"
                for lane in manifest["lanes"]:
                    if len(lane["doc_ids"]) > 1:
                        lane["doc_ids"] = list(reversed(lane["doc_ids"]))
                        lane["analyzer"] = "standard"
                        break

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=mutate)
            report = self.assert_invalid(root, "analyzer_map_mismatch")
            codes = [error["code"] for error in report["errors"]]
            self.assertIn("ordering", codes)

    # T06
    def test_t06_off_by_one_total_invalidates_before_timing(self):
        def mutate(engine, trial, manifest):
            if engine == "tantivy" and trial == 2:
                manifest["lanes"][0]["total_hits"] += 1

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=mutate)
            self.assert_invalid(root, "oracle_mismatch")

    # T07
    def test_t07_nonpositive_durations_rejected(self):
        for bad in (0, -1, 1.5, None):
            def mutate(engine, trial, manifest, bad=bad):
                if engine == "lucene" and trial == 1:
                    manifest["lanes"][0]["samples_ns"][0] = bad

            with tempfile.TemporaryDirectory() as root:
                create_run(root, trial_mutator=mutate)
                self.assert_invalid(root, "nonpositive_duration")
        with self.assertRaises(ValueError):
            run.summarize([1, 2, 0])

    # T08
    def test_t08_missing_duplicate_and_unexpected_lanes_rejected(self):
        def missing(engine, trial, manifest):
            if engine == "quervant" and trial == 1:
                manifest["lanes"].pop()

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=missing)
            self.assert_invalid(root, "missing_lane")

        def duplicate(engine, trial, manifest):
            if engine == "quervant" and trial == 1:
                manifest["lanes"].append(copy.deepcopy(manifest["lanes"][0]))

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=duplicate)
            self.assert_invalid(root, "duplicate_lane")

        def wrong_k(engine, trial, manifest):
            if engine == "quervant" and trial == 1:
                manifest["lanes"][0]["k"] = 7

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=wrong_k)
            self.assert_invalid(root, "unexpected_lane")

        def wrong_mode(engine, trial, manifest):
            if engine == "quervant" and trial == 1:
                manifest["lanes"][0]["regime"] = "cold"

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=wrong_mode)
            self.assert_invalid(root, "wrong_regime_label")

    # T09
    def test_t09_engine_version_source_and_host_are_required(self):
        def no_version(engine, trial, manifest):
            if engine == "tantivy" and trial == 1:
                manifest.pop("engine_version")

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=no_version)
            self.assert_invalid(root, "engine_version_missing")

        def mixed_host(engine, trial, manifest):
            if engine == "lucene" and trial == 2:
                manifest["host_fingerprint"] = "c" * 64

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=mixed_host)
            self.assert_invalid(root, "mixed_host")

        def wrong_source(engine, trial, manifest):
            if engine == "quervant" and trial == 3:
                manifest["source_sha"] = "d" * 40

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=wrong_source)
            self.assert_invalid(root, "source_sha_mismatch")

    # T10
    def test_t10_attestation_and_contention_are_unqualified(self):
        with tempfile.TemporaryDirectory() as root:
            create_run(root, run_overrides={"idle_attested": False})
            self.assert_unqualified(root, "idle_attestation_missing")

        def contended(engine, trial, manifest):
            if engine == "quervant" and trial == 1:
                manifest["lanes"][0]["contention"]["post"] = "suspected"

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=contended)
            self.assert_unqualified(root, "contention_not_clear")

        def no_attestation(engine, trial, manifest):
            if engine == "tantivy" and trial == 1:
                manifest["operator_idle_attested"] = False

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=no_attestation)
            self.assert_unqualified(root, "idle_attestation_missing")

    # T11
    def test_t11_three_trials_and_twenty_samples_are_enforced(self):
        with tempfile.TemporaryDirectory() as root:
            create_run(root, drop_trial=lambda engine, trial: trial == 3)
            self.assert_invalid(root, "trial_count_below_minimum")

        def nineteen(engine, trial, manifest):
            if engine == "quervant" and trial == 2:
                manifest["lanes"][0]["samples_ns"] = manifest["lanes"][0]["samples_ns"][:19]
                manifest["lanes"][0]["summary_ns"] = run.summarize(
                    manifest["lanes"][0]["samples_ns"]
                )

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=nineteen)
            self.assert_invalid(root, "sample_count")

    # T12
    def test_t12_nearest_rank_statistics(self):
        summary = run.summarize(list(range(1, 21)))
        self.assertEqual(
            summary,
            {"count": 20, "median": 10, "p95": 19, "p99": 20, "min": 1, "max": 20},
        )
        self.assertEqual(run.nearest_rank_index(20, 50), 9)
        self.assertEqual(run.nearest_rank_index(20, 95), 18)
        self.assertEqual(run.nearest_rank_index(20, 99), 19)
        wide = run.summarize([100 * index for index in range(1, 21)])
        self.assertEqual(wide["median"], 1000)
        self.assertEqual(wide["p95"], 1900)
        self.assertEqual(wide["p99"], 2000)

    # T13
    def test_t13_tampered_cached_aggregate_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            create_run(root)
            path = os.path.join(root, "pr15d-qualified.json")
            payload, _ = aggregate.aggregate_bytes(root)
            with open(path, "wb") as handle:
                handle.write(payload)
            self.assertEqual(aggregate.verify_aggregate(root, path), [])
            value = json.loads(payload)
            value["latency"][0]["engines"]["quervant"]["median_ns"] += 1
            with open(path, "wb") as handle:
                handle.write(run.canonical_json_bytes(value) + b"\n")
            mismatches = aggregate.verify_aggregate(root, path)
            self.assertEqual(mismatches[0]["code"], "aggregate_tampered")

    # T14
    def test_t14_failed_build_commit_or_reopen_is_an_error(self):
        def failed_reopen(engine, trial, manifest):
            if engine == "quervant" and trial == 1:
                manifest["build"]["10000"]["documents_verified"] = 0

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=failed_reopen)
            self.assert_invalid(root, "commit_or_reopen_failed")

        def missing_build(engine, trial, manifest):
            if engine == "tantivy" and trial == 2:
                manifest.pop("build")

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=missing_build)
            self.assert_invalid(root, "build_failed")

    # T15
    def test_t15_process_cold_is_not_os_cold_and_warmups_are_excluded(self):
        def os_cold(engine, trial, manifest):
            if engine == "quervant" and trial == 1:
                manifest["lanes"][0]["regime"] = "os_cold"

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=os_cold)
            self.assert_invalid(root, "wrong_regime_label")

        def warmup_leak(engine, trial, manifest):
            if engine == "quervant" and trial == 1:
                for lane in manifest["lanes"]:
                    if lane["regime"] == "warm":
                        lane["samples_ns"] = lane["samples_ns"] + [1] * run.WARMUPS
                        lane["summary_ns"] = run.summarize(lane["samples_ns"])

        with tempfile.TemporaryDirectory() as root:
            create_run(root, trial_mutator=warmup_leak)
            self.assert_invalid(root, "sample_count")
        with tempfile.TemporaryDirectory() as fresh:
            create_run(fresh)
            aggregate_value = aggregate.build_aggregate(fresh)
        self.assertNotIn("os_cold", aggregate_value["regimes"])
        self.assertEqual(set(aggregate_value["regimes"]), set(run.REGIMES))

    # T16
    def test_t16_only_matching_lane_and_host_comparisons(self):
        with tempfile.TemporaryDirectory() as root:
            create_run(root)
            value = aggregate.build_aggregate(root)
            for lane in value["latency"]:
                for engine in ("tantivy", "lucene"):
                    self.assertIn("engine_over_quervant_ratio", lane["comparisons"][engine])
            self.assertEqual(value["host_fingerprint"], "b" * 64)

            def mixed(engine, trial, manifest):
                if engine == "lucene" and trial == 1:
                    manifest["host_fingerprint"] = "e" * 64

            mixed_root = tempfile.mkdtemp()
            create_run(mixed_root, trial_mutator=mixed)
            report = validate.validate_run(mixed_root)
            self.assertEqual(report["status"], "INVALID")
            with self.assertRaises(aggregate.AggregateError):
                aggregate.build_aggregate(mixed_root)

    # T17
    def test_t17_scored_lane_without_proof_is_noncomparable(self):
        with tempfile.TemporaryDirectory() as root:
            create_run(root)
            value = aggregate.build_aggregate(root)
            self.assertEqual(value["scored_lane"]["status"], "SEMANTICALLY_NONCOMPARABLE")
            self.assertEqual(value["scored_ratios"], [])
            self.assertEqual(value["score_comparison"], "NOT_APPLICABLE")

        with tempfile.TemporaryDirectory() as root:
            create_run(
                root,
                run_overrides={"scored_lane": {"status": "QUALIFIED"}},
            )
            self.assert_invalid(root, "scored_lane_invalid")

    # T19
    def test_t19_output_paths_are_confined(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(run.confined_path(root, "a", "b").startswith(os.path.realpath(root)))
            with self.assertRaises(run.RunBlocked):
                run.confined_path(root, "..", "escape.json")
            outside = tempfile.mkdtemp()
            link = os.path.join(root, "link")
            os.symlink(outside, link)
            with self.assertRaises(run.RunBlocked):
                run.confined_path(root, "link", "file.json")

    # T20
    def test_t20_slower_quervant_is_reported_without_threshold_failure(self):
        with tempfile.TemporaryDirectory() as root:
            def slower(engine, trial, manifest):
                if engine == "quervant":
                    for lane in manifest["lanes"]:
                        lane["samples_ns"] = [value * 5 for value in lane["samples_ns"]]
                        lane["summary_ns"] = run.summarize(lane["samples_ns"])

            create_run(root, trial_mutator=slower)
            value = aggregate.build_aggregate(root)
            self.assertEqual(value["status"], "QUALIFIED")
            self.assertFalse(value["performance_threshold_failure"])
            ratio = value["latency"][0]["comparisons"]["tantivy"]["engine_over_quervant_ratio"]
            self.assertGreater(ratio, 0)
            self.assertLess(ratio, 1)  # Tantivy faster than a 5x-slower Quervant

    # T21
    def test_t21_raw_manifests_reproduce_checked_in_summary(self):
        with tempfile.TemporaryDirectory() as root:
            create_run(root)
            first, first_md = aggregate.aggregate_bytes(root)
            second, second_md = aggregate.aggregate_bytes(root)
            self.assertEqual(first, second)
            self.assertEqual(first_md, second_md)
            out = os.path.join(root, "aggregate.json")
            md = os.path.join(root, "qualification.md")
            self.assertEqual(
                aggregate.main(["--run", root, "--out", out, "--md", md]), 0
            )
            self.assertEqual(aggregate.verify_aggregate(root, out), [])

    # T22
    def test_t22_frozen_and_production_paths_are_classified(self):
        violations = run.classify_changed_paths(
            [
                "crates/quervant-core/src/lib.rs",
                "benchmarks/workloads/pr15b_v1.md",
                "benchmarks/reports/pr15c-b/pr15c-b-qualified-comparison.json",
            ]
        )
        self.assertEqual(len(violations), 3)
        self.assertEqual(
            run.classify_changed_paths(
                [
                    "benchmarks/pr15d/harness/run.py",
                    "benchmarks/reports/pr15d/pr15d-qualified.json",
                    "docs/pr-artifacts/pr-15d/preflight.md",
                    "benchmarks/README.md",
                ]
            ),
            [],
        )

    # T11b: measurement modes and labelling are explicit.
    def test_measurement_regimes_are_exactly_frozen(self):
        self.assertEqual(run.REGIMES, ("process_cold", "warm"))
        self.assertEqual(run.MEASURED, 20)
        self.assertEqual(run.WARMUPS, 5)
        self.assertEqual(run.THROUGHPUT_REQUESTS, 100)
        self.assertEqual(len(run.lane_descriptors()), 32)
        for descriptor in run.lane_descriptors():
            self.assertIn(descriptor["regime"], run.REGIMES)


ADAPTER_ENV = {
    "quervant": "PR15D_QUERVANT_BIN",
    "tantivy": "PR15D_TANTIVY_BIN",
}


def adapter_binary(engine):
    candidates = [
        os.environ.get(ADAPTER_ENV[engine]),
        os.path.join(
            run.REPO_ROOT,
            f"target/pr15d/build/{engine}/release/pr15d-{engine}-adapter",
        ),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class AdapterSmokeTests(unittest.TestCase):
    """T04/T18 + A1: only run when the exact adapter pin and toolchain exist."""

    def _binary(self, engine):
        return adapter_binary(engine)

    def _adapter_smoke(self, engine):
        binary = self._binary(engine)
        if binary is None:
            self.skipTest(
                f"SKIP (not PASS): prebuilt {engine} adapter binary is absent; "
                f"set {ADAPTER_ENV[engine]} or build target/pr15d/build/{engine}"
            )
        with tempfile.TemporaryDirectory() as root:
            sample = os.path.join(root, "sample16.tsv")
            with open(sample, "w", encoding="utf-8", newline="") as handle:
                handle.write(oracle.build_tsv_text(16))
            index_dir = os.path.join(root, "index")
            requests = [
                {"request_id": "build", "op": "build", "corpus_path": sample, "index_dir": index_dir},
            ]
            rows = oracle.load_tsv(sample, expected_n=16)
            for class_name, field, term in run.CLASSES:
                for k in run.K_VALUES:
                    requests.append(
                        {
                            "request_id": f"{class_name}-{k}",
                            "op": "query",
                            "field": field,
                            "term": term,
                            "k": k,
                            "mode": "process_cold",
                        }
                    )
            requests.append({"request_id": "bye", "op": "shutdown"})
            payload = "".join(
                json.dumps(request, sort_keys=True) + "\n" for request in requests
            )
            completed = subprocess.run(
                [binary],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            responses = [json.loads(line) for line in completed.stdout.splitlines()]
            build = responses[0]
            self.assertEqual(build["status"], "ok")
            self.assertEqual(build["documents_indexed"], 16)
            self.assertEqual(build["documents_verified"], 16)
            by_id = {response["request_id"]: response for response in responses[1:]}
            for class_name, field, term in run.CLASSES:
                for k in run.K_VALUES:
                    expected = oracle.expected(rows, field, term, k)
                    response = by_id[f"{class_name}-{k}"]
                    self.assertEqual(response["total_hits"], expected["total_hits"])
                    self.assertEqual(response["doc_ids"], expected["doc_ids"])
                    self.assertGreater(response["engine_ns"], 0)

    def test_t04_quervant_adapter_smoke(self):
        self._adapter_smoke("quervant")

    def test_a1_tantivy_adapter_smoke(self):
        self._adapter_smoke("tantivy")

    def test_t18_tantivy_and_lucene_smoke_are_gated_not_faked(self):
        toolchains = run.collect_toolchains()
        adapters = run.preflight_adapters()
        self.assertFalse(
            any(blocker["rule"] == "X15_HARD_STOP" for blocker in adapters["tantivy"]["blockers"]),
            adapters["tantivy"]["blockers"],
        )
        if not toolchains["java"]["present"]:
            self.assertTrue(
                any(
                    blocker["rule"] == "X14_DEFER_ENVIRONMENT"
                    for blocker in adapters["lucene"]["blockers"]
                )
            )


class A1DependencyTests(unittest.TestCase):
    def test_a1_tantivy_pin_is_exact_and_locked(self):
        directory = run.ADAPTER_DIRS["tantivy"]
        with open(os.path.join(directory, "Cargo.toml"), encoding="utf-8") as handle:
            manifest = handle.read()
        self.assertRegex(manifest, r'(?m)^tantivy = "=0\.22\.1"$')
        self.assertNotRegex(manifest, r'(?m)^tantivy = "=0\.22\.0"$')
        self.assertNotRegex(manifest, r'(?m)^tantivy = "0\.22"$')
        with open(os.path.join(directory, "Cargo.lock"), encoding="utf-8") as handle:
            lock = handle.read()
        self.assertRegex(lock, r'name = "tantivy"\nversion = "0.22\.1"')
        self.assertIn('version = "1.85"', manifest)
        self.assertIn('resolver = "3"', manifest)

    def test_a1_quervant_adapter_lock_exists(self):
        lock_path = os.path.join(run.ADAPTER_DIRS["quervant"], "Cargo.lock")
        self.assertTrue(os.path.isfile(lock_path))

    def test_a1_gradle_wrapper_checksums_and_pins(self):
        directory = run.ADAPTER_DIRS["lucene"]
        self.assertEqual(run.verify_checksum_manifest(directory, "A1-CHECKSUMS.sha256"), [])
        jar = os.path.join(directory, "gradle/wrapper/gradle-wrapper.jar")
        with open(jar, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(
            digest,
            "7d3a4ac4de1c32b59bc6a4eb8ecb8e612ccd0cf1ae1e99f66902da64df296172",
        )
        with open(
            os.path.join(directory, "gradle/wrapper/gradle-wrapper.properties"),
            encoding="utf-8",
        ) as handle:
            properties = handle.read()
        self.assertIn("gradle-8.14.3-bin.zip", properties)
        self.assertIn(
            "distributionSha256Sum=bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531",
            properties,
        )
        with open(
            os.path.join(directory, "A1-GRADLE-PROVENANCE.json"), encoding="utf-8"
        ) as handle:
            provenance = json.load(handle)
        self.assertEqual(provenance["gradle_version"], "8.14.3")
        self.assertEqual(provenance["jdk"], "21")
        self.assertEqual(provenance["lucene"], "9.12.3")

    def test_a1_checksum_manifest_rejects_tamper_and_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = os.path.join(directory, "artifact.bin")
            with open(payload, "wb") as handle:
                handle.write(b"official")
            digest = hashlib.sha256(b"official").hexdigest()
            manifest = os.path.join(directory, "CHECKSUMS.sha256")
            with open(manifest, "w", encoding="utf-8") as handle:
                handle.write(f"{digest}  artifact.bin\n")
            self.assertEqual(run.verify_checksum_manifest(directory, "CHECKSUMS.sha256"), [])
            with open(payload, "wb") as handle:
                handle.write(b"tampered")
            problems = run.verify_checksum_manifest(directory, "CHECKSUMS.sha256")
            self.assertTrue(any("checksum mismatch" in problem for problem in problems))
            with open(manifest, "w", encoding="utf-8") as handle:
                handle.write(f"{digest}  ../escape.bin\n")
            problems = run.verify_checksum_manifest(directory, "CHECKSUMS.sha256")
            self.assertTrue(any("escapes adapter root" in problem for problem in problems))

    def test_a1_smoke_command_parsing_rejects_unsafe_input(self):
        with self.assertRaises(smoke.SmokeError):
            smoke._parse_command("echo hi; rm -rf /", "lucene")
        with self.assertRaises(smoke.SmokeError):
            smoke._parse_command("relative-binary", "lucene")
        with self.assertRaises(smoke.SmokeError):
            smoke._parse_command("echo $(id)", "lucene")

    def test_a1_smoke_runs_two_available_engines(self):
        quervant = adapter_binary("quervant")
        tantivy = adapter_binary("tantivy")
        if quervant is None or tantivy is None:
            self.skipTest(
                "SKIP (not PASS): both adapter binaries are required for the A1 smoke subset"
            )
        corpus_path = os.path.join(CORPUS, oracle.corpus_filename(10000))
        rows = ROWS[10000]
        for engine, binary in (("quervant", quervant), ("tantivy", tantivy)):
            result = smoke._run_engine(engine, [binary], corpus_path, rows, 300)
            self.assertEqual(result["queries_checked"], 8)
            self.assertEqual(result["documents"], 10000)


class SmokeSizeSelectionTests(unittest.TestCase):
    """PR15D-B A1/T12: `--sizes` is a bounded, frozen-corpus selector only."""

    def test_sizes_default_is_the_existing_10k_smoke(self):
        self.assertEqual(smoke.parse_sizes(None), [10000])

    def test_sizes_accepts_the_frozen_10k_100k_pair(self):
        self.assertEqual(smoke.parse_sizes("10000,100000"), [10000, 100000])
        self.assertEqual(smoke.parse_sizes(" 10000 , 100000 "), [10000, 100000])
        self.assertEqual(smoke.parse_sizes("100000"), [100000])

    def test_sizes_rejects_unknown_size(self):
        with self.assertRaises(smoke.SmokeError) as raised:
            smoke.parse_sizes("16")
        self.assertEqual(raised.exception.code, "sizes_unknown")
        with self.assertRaises(smoke.SmokeError) as raised:
            smoke.parse_sizes("10000,1000")
        self.assertEqual(raised.exception.code, "sizes_unknown")

    def test_sizes_rejects_empty_selection(self):
        for empty in ("", "   ", "10000,", ",100000", "10000,,100000"):
            with self.assertRaises(smoke.SmokeError) as raised:
                smoke.parse_sizes(empty)
            self.assertEqual(raised.exception.code, "sizes_empty", empty)

    def test_sizes_rejects_duplicates(self):
        with self.assertRaises(smoke.SmokeError) as raised:
            smoke.parse_sizes("10000,10000")
        self.assertEqual(raised.exception.code, "sizes_duplicate")

    def test_sizes_rejects_malformed_input(self):
        for malformed in ("1e5", "-10000", "10_000", "abc", "10000;100000", "10.0"):
            with self.assertRaises(smoke.SmokeError) as raised:
                smoke.parse_sizes(malformed)
            self.assertEqual(raised.exception.code, "sizes_malformed", malformed)

    def test_sizes_rejects_non_text(self):
        with self.assertRaises(smoke.SmokeError) as raised:
            smoke.parse_sizes(10000)
        self.assertEqual(raised.exception.code, "sizes_invalid")

    def test_sizes_match_the_frozen_oracle_matrix(self):
        self.assertEqual(tuple(smoke.SIZES), oracle.N_VALUES)
        self.assertEqual(smoke.SIZES, (10000, 100000))


WORKFLOW_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(CORPUS_DIR))),
    ".github",
    "workflows",
)
STANDARD_WORKFLOW = os.path.join(WORKFLOW_DIR, "ci.yml")
COMPARATIVE_WORKFLOW = os.path.join(WORKFLOW_DIR, "comparative-adapters.yml")


def _workflow_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _job_names(text):
    """Return the top-level job names, scoped to the `jobs:` block."""
    marker = "\njobs:\n"
    start = text.index(marker) + len(marker)
    return re.findall(r"(?m)^  ([A-Za-z0-9_-]+):$", text[start:])


def _job_block(text, name):
    """Return one top-level key block (job or trigger), or '' when absent."""
    marker = f"\n  {name}:\n"
    try:
        start = text.index(marker) + 1
    except ValueError:
        return ""
    remainder = text[start:]
    following = [
        match.start()
        for match in re.finditer(r"(?m)^ {0,2}[A-Za-z0-9_-]+:$", remainder)
        if match.start() > 0
    ]
    end = start + (following[0] if following else len(remainder))
    return text[start:end]


class ComparativeWorkflowContractTests(unittest.TestCase):
    """PR15D-B T01/T02/T03/T06/T12/T23: CI split is provable without a run."""

    def test_t01_standard_ci_keeps_only_the_required_jobs(self):
        text = _workflow_text(STANDARD_WORKFLOW)
        self.assertEqual(_job_names(text), ["rust", "msrv", "rustfs"])
        self.assertNotIn("pr15d", text)
        self.assertNotIn("comparative", text)

    def test_t01_standard_ci_required_gates_are_unchanged(self):
        rust = _job_block(_workflow_text(STANDARD_WORKFLOW), "rust")
        self.assertIn("cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85", rust)
        self.assertIn("cargo fmt --all -- --check", rust)
        self.assertIn("bash benchmarks/scripts/test-scripts.sh", rust)
        msrv = _job_block(_workflow_text(STANDARD_WORKFLOW), "msrv")
        self.assertIn("cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings", msrv)
        rustfs = _job_block(_workflow_text(STANDARD_WORKFLOW), "rustfs")
        self.assertIn("rustfs/rustfs@sha256:", rustfs)

    def test_comparative_workflow_declares_exactly_two_jobs(self):
        text = _workflow_text(COMPARATIVE_WORKFLOW)
        self.assertEqual(
            _job_names(text), ["comparative-smoke", "comparative-full-correctness"]
        )
        self.assertIn("name: Comparative Adapters", text)

    def test_t02_t03_trigger_paths_are_exactly_the_authorized_set(self):
        text = _workflow_text(COMPARATIVE_WORKFLOW)
        pull_request = _job_block(text, "pull_request")
        self.assertTrue(pull_request, "pull_request trigger is missing")
        paths = re.findall(r"(?m)^      - '([^']+)'$", pull_request)
        self.assertEqual(
            paths,
            ["benchmarks/pr15d/**", ".github/workflows/comparative-adapters.yml"],
        )
        self.assertNotIn("benchmarks/README.md", text)

    def test_manual_dispatch_exposes_a_typed_full_correctness_switch(self):
        text = _workflow_text(COMPARATIVE_WORKFLOW)
        dispatch = _job_block(text, "workflow_dispatch")
        self.assertTrue(dispatch, "workflow_dispatch trigger is missing")
        self.assertIn("full_correctness:", dispatch)
        self.assertIn("type: boolean", dispatch)
        self.assertIn("default: false", dispatch)
        self.assertIn(
            "Execute full 10K/100K three-engine oracle validation "
            "(never performance measurement)",
            dispatch,
        )

    def test_t04_t05_job_guards_match_the_closed_decision_matrix(self):
        text = _workflow_text(COMPARATIVE_WORKFLOW)
        smoke_job = _job_block(text, "comparative-smoke")
        full_job = _job_block(text, "comparative-full-correctness")
        self.assertIn(
            "if: github.event_name == 'pull_request' || "
            "(github.event_name == 'workflow_dispatch' && inputs.full_correctness == false)",
            smoke_job,
        )
        self.assertIn(
            "if: github.event_name == 'workflow_dispatch' && inputs.full_correctness == true",
            full_job,
        )

    def test_t06_no_workflow_can_measure_or_self_attest(self):
        for path in (STANDARD_WORKFLOW, COMPARATIVE_WORKFLOW):
            text = _workflow_text(path)
            self.assertNotIn("run.py", text, path)
            self.assertNotIn("idle-confirmed", text, path)
            self.assertNotIn("idle_confirmed", text, path)
            self.assertNotIn("pr15d-qualified", text, path)

    def test_t12_full_gate_covers_10k_and_100k_for_all_engines(self):
        full_job = _job_block(_workflow_text(COMPARATIVE_WORKFLOW), "comparative-full-correctness")
        self.assertIn("--sizes 10000,100000", full_job)
        self.assertIn("--corpus", full_job)
        for flag in ("--quervant-bin", "--tantivy-bin", "--lucene-command"):
            self.assertIn(flag, full_job)
        self.assertIn("corpus/oracle.py --corpus", full_job)

    def test_t12_smoke_gate_stays_on_the_existing_10k_default(self):
        smoke_job = _job_block(_workflow_text(COMPARATIVE_WORKFLOW), "comparative-smoke")
        self.assertIn("harness/smoke.py", smoke_job)
        self.assertNotIn("--sizes", smoke_job)

    def test_t07_checksum_verification_precedes_every_java_invocation(self):
        text = _workflow_text(COMPARATIVE_WORKFLOW)
        for job in ("comparative-smoke", "comparative-full-correctness"):
            block = _job_block(text, job)
            checksum_at = block.find("sha256sum -c A1-CHECKSUMS.sha256")
            gradle_at = block.find("./gradlew --no-daemon classes installDist")
            self.assertGreaterEqual(checksum_at, 0, job)
            self.assertGreaterEqual(gradle_at, 0, job)
            self.assertLess(checksum_at, gradle_at, job)
            self.assertIn("PR15D_LUCENE_BUILD_DIR", block)

    def test_comparative_workflow_is_read_only(self):
        text = _workflow_text(COMPARATIVE_WORKFLOW)
        self.assertIn("permissions:\n  contents: read\n", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("pull-requests: write", text)
        self.assertNotIn("secrets.", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
