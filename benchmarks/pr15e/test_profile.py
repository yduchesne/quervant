#!/usr/bin/env python3
"""Deterministic tests for the PR 15E-A profiling driver (T01-T39).

Fake *process boundaries* (a JSONL script adapter and script profilers) are used
only where a profiler must wrap a child; every fake artifact is labelled
``TEST_FIXTURE`` and can never be published as measurement. The real Quervant
adapter/index/oracle path is exercised by ``RealAdapterIntegrationTest``, which
is opt-in via ``PR15E_RUN_REAL_INTEGRATION=1`` and must actually be executed for
G03 acceptance evidence.
"""

from __future__ import annotations

import argparse
import datetime
import gzip
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_PATH = os.path.join(HERE, "profile.py")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PROFILE = _load(PROFILE_PATH, "pr15e_profile_tests")
TARGET_ROOT = PROFILE.TARGET_ROOT

FAKE_ADAPTER = '''#!/usr/bin/env python3
"""TEST_FIXTURE: deterministic JSONL adapter used only inside unit tests."""
import json
import os
import sys
import time


def main():
    index_dir = None
    argv = sys.argv[1:]
    index = 0
    while index < len(argv):
        if argv[index] == "--index-dir":
            index_dir = argv[index + 1]
            index += 2
        else:
            index += 1
    if not index_dir:
        return 2
    config_path = os.environ.get("PR15E_FIXTURE_ADAPTER_CONFIG")
    if not config_path:
        return 3
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    responses = config["responses"]
    behavior = config.get("behavior", {})
    served = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        request_id = request["request_id"]
        if request["op"] == "shutdown":
            print(json.dumps({"schema": "pr15d-adapter-v1", "engine": "quervant",
                              "request_id": request_id, "status": "ok"}), flush=True)
            return 0
        key = "%s|%s|%d" % (request["field"], request["term"], request["k"])
        base = responses[key]
        profiled = "profiled" in request_id
        if profiled and behavior.get("profiled_delay_ms"):
            time.sleep(behavior["profiled_delay_ms"] / 1000.0)
        body = {
            "schema": "pr15d-adapter-v1",
            "engine": "quervant",
            "request_id": request_id,
            "status": "ok",
            "engine_ns": 1000,
            "total_hits": base["total_hits"],
            "doc_ids": list(base["doc_ids"]),
        }
        if behavior.get("wrong_warmup") is not None and request_id.endswith(
            "warmup:%d" % behavior["wrong_warmup"]
        ):
            body["total_hits"] = int(body["total_hits"]) + 1
        if profiled and behavior.get("wrong_total"):
            body["total_hits"] = int(body["total_hits"]) + 1
        if profiled and behavior.get("wrong_ids"):
            body["doc_ids"] = list(reversed(body["doc_ids"]))
        if profiled and behavior.get("error_status"):
            body = {"schema": "pr15d-adapter-v1", "engine": "quervant",
                    "request_id": request_id, "status": "error",
                    "error": {"kind": "fixture", "message": "forced"}}
        print(json.dumps(body), flush=True)
        served += 1
        if behavior.get("exit_after") is not None and served >= behavior["exit_after"]:
            return 0
    return 0


sys.exit(main())
'''


def fake_profiler_source(kind: str) -> str:
    if kind == "perf":
        return '''#!/usr/bin/env python3
"""TEST_FIXTURE: script perf boundary (record/report only)."""
import os
import subprocess
import sys

MODE = os.environ.get("FAKE_PERF_MODE", "ok")
argv = sys.argv[1:]
if not argv:
    sys.exit(2)
if argv[0] == "record":
    out = None
    index = 1
    while index < len(argv):
        if argv[index] == "-o":
            out = argv[index + 1]
            index += 2
            continue
        if argv[index] == "--":
            index += 1
            break
        index += 1
    child = argv[index:]
    rc = subprocess.call(child)
    if out and MODE != "no-data" and rc == 0:
        with open(out, "wb") as handle:
            handle.write(b"fixture-perf-data" * 64)
    if MODE == "record-exit":
        sys.exit(3)
    sys.exit(rc)
if argv[0] == "report":
    if MODE == "report-exit":
        sys.exit(5)
    if MODE == "no-symbols":
        sys.stdout.write("# Samples: 500  of event 'cycles:Pu'\\n"
                         "  99.00%  python3  [.] _PyEval_EvalFrameDefault\\n")
        sys.exit(0)
    if MODE == "few-samples":
        sys.stdout.write("# Samples: 7  of event 'cycles:Pu'\\n"
                         "  50.00%  x  [.] quervant_core::run\\n")
        sys.exit(0)
    sys.stdout.write(
        "# Total Lost Samples: 0\\n"
        "# Samples: 500  of event 'cycles:Pu'\\n"
        "# Event count (approx.): 1000\\n"
        "#\\n"
        "# Overhead  Shared Object  Symbol\\n"
        "    42.00%  pr15d-quervant-adapter  [.] quervant_core::search::execute::evaluate_lexical_with\\n"
        "    12.50%  pr15d-quervant-adapter  [.] quervant_core::search::execute::collect\\n"
        "     5.00%  libc.so.6  [.] malloc\\n")
    sys.exit(0)
sys.exit(2)
'''
    return '''#!/usr/bin/env python3
"""TEST_FIXTURE: script heaptrack boundary (optionally noisy like 1.5.0)."""
import gzip
import os
import subprocess
import sys

MODE = os.environ.get("FAKE_HEAPTRACK_MODE", "ok")
argv = sys.argv[1:]
prefix = None
index = 0
while index < len(argv):
    if argv[index] == "-o":
        prefix = argv[index + 1]
        index += 2
        continue
    break
child = argv[index:]
if MODE == "banner":
    sys.stdout.write('heaptrack output will be written to "%s.gz"\\n' % prefix)
    sys.stdout.write("starting application, this might take some time...\\n")
    sys.stdout.flush()
rc = subprocess.call(child)
if prefix and MODE != "no-raw":
    names = ["%s.gz" % prefix]
    if MODE == "two-raw":
        names = ["%s.1.gz" % prefix, "%s.2.gz" % prefix]
    for name in names:
        with gzip.open(name, "wb") as handle:
            handle.write(b'{"fixture": true}')
if MODE == "record-exit":
    sys.exit(4)
sys.exit(rc)
'''


FAKE_HEAPTRACK_PRINT = '''#!/usr/bin/env python3
"""TEST_FIXTURE: script heaptrack_print boundary."""
import os
import sys

MODE = os.environ.get("FAKE_HEAPTRACK_PRINT_MODE", "ok")
if MODE == "exit":
    sys.exit(6)
if MODE == "empty":
    sys.exit(0)
sys.stdout.write(
    "MOST CALLS TO ALLOCATION FUNCTIONS\\n"
    "---------------------------------\\n"
    "250 calls to allocation functions with 1.20M peak consumption from\\n"
    "quervant_core::search::execute::evaluate_lexical_with\\n"
    "  in execute.rs:1900\\n"
    "100 calls to allocation functions with 512.00K peak consumption from\\n"
    "BTreeSet::insert\\n"
    "  in execute.rs:1920\\n"
    "PEAK MEMORY CONSUMERS\\n"
    "calls to allocation functions: 350 (1000/s)\\n"
    "total memory leaked: 0\\n")
'''

_CORPUS_CACHE: dict[str, str] = {}


def _shared_corpus() -> str:
    if "path" in _CORPUS_CACHE:
        return _CORPUS_CACHE["path"]
    destination = os.path.join(TARGET_ROOT, "_test-corpus-cache")
    if not os.path.isfile(os.path.join(destination, PROFILE.oracle.manifest_filename())):
        os.makedirs(destination, exist_ok=True)
        PROFILE.generate.generate(destination)
    _CORPUS_CACHE["path"] = destination
    return destination


def _write_script(path: str, source: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    os.chmod(path, 0o755)


class RunFixture:
    """A synthetic (TEST_FIXTURE) run directory with real corpus and digests."""

    def __init__(self, *, source_sha: str = "a" * 40, host: str = "testhost"):
        self.run_dir = os.path.join(
            TARGET_ROOT, f"selftest-{uuid.uuid4().hex[:12]}"
        )
        self.source_sha = source_sha
        self.host = host
        self.now = datetime.datetime(2030, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        self.binary = os.path.join(
            self.run_dir, "build", "release", PROFILE.SYMBOL_NAME
        )
        self.scripts = {
            "heaptrack_print": os.path.join(self.run_dir, "fixtures", "heaptrack_print.py")
        }
        self.prepared: dict = {}
        self.rows_by_n: dict = {}

    # -- construction -----------------------------------------------------
    def build(self) -> "RunFixture":
        os.makedirs(self.run_dir, exist_ok=False)
        corpus_dir = os.path.join(self.run_dir, "corpus")
        os.makedirs(corpus_dir)
        shared = _shared_corpus()
        for name in os.listdir(shared):
            if name.endswith(".tsv") or name.endswith(".json"):
                shutil.copyfile(os.path.join(shared, name), os.path.join(corpus_dir, name))
        manifest, rows_by_n = PROFILE.oracle.load_and_verify(corpus_dir)
        self.rows_by_n = rows_by_n

        self.config_path = os.path.join(self.run_dir, "fixtures", "adapter-config.json")
        fixtures_dir = os.path.join(self.run_dir, "fixtures")
        os.makedirs(fixtures_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.binary), exist_ok=True)
        _write_script(self.binary, FAKE_ADAPTER)
        _write_script(os.path.join(fixtures_dir, "perf.py"), fake_profiler_source("perf"))
        _write_script(
            os.path.join(fixtures_dir, "heaptrack.py"), fake_profiler_source("heaptrack")
        )
        _write_script(self.scripts["heaptrack_print"], FAKE_HEAPTRACK_PRINT)
        self.scripts["perf"] = os.path.join(fixtures_dir, "perf.py")
        self.scripts["heaptrack"] = os.path.join(fixtures_dir, "heaptrack.py")

        lanes = PROFILE.oracle_lane_expectations(rows_by_n)
        indexes = {}
        for n in PROFILE.N_VALUES:
            index_dir = os.path.join(self.run_dir, "indexes", f"n{n}")
            payload_dir = os.path.join(index_dir, "index")
            os.makedirs(payload_dir, exist_ok=True)
            with open(os.path.join(payload_dir, "CURRENT"), "w", encoding="utf-8") as handle:
                handle.write(f"generation=1\nn={n}\n")
            with open(os.path.join(payload_dir, "segment.seg"), "wb") as handle:
                handle.write((f"fixture-segment-{n}-" * 8).encode("utf-8"))
            responses = {}
            for lane in lanes:
                if lane["n"] != n:
                    continue
                responses[f"{lane['field']}|{lane['term']}|{lane['k']}"] = {
                    "total_hits": lane["expected_total_hits"],
                    "doc_ids": lane["expected_doc_ids"],
                }
            PROFILE.write_json(
                self.config_path,
                {"responses": responses, "behavior": {}},
            )
            inventory = PROFILE.index_inventory(index_dir)
            indexes[str(n)] = {
                "path": f"indexes/n{n}",
                "documents_indexed": n,
                "documents_verified": n,
                "expected_documents": n,
                "index_bytes": inventory["bytes"],
                "segment_count": 1,
                "index_ns": 1,
                "commit_ns": 1,
                "reopen_ns": 1,
                "inventory": inventory,
            }

        corpus_block = {
            "path": "corpus",
            "manifest_sha256": PROFILE.sha256_bytes(
                PROFILE.canonical_json_bytes(manifest)
            ),
            "manifest_bytes": os.path.getsize(
                os.path.join(corpus_dir, PROFILE.oracle.manifest_filename())
            ),
            "corpora": {
                str(entry["n"]): {
                    "file": entry["path"],
                    "rows": entry["rows"],
                    "bytes": entry["bytes"],
                    "sha256": entry["sha256"],
                }
                for entry in manifest["corpora"]
            },
            "generator_summary": {"fixture": True},
        }
        environment = {
            "kernel": "fixture-kernel",
            "machine": "x86_64",
            "wsl": True,
            "filesystem": "ext4",
            "cpu_model": "fixture-cpu",
            "python": "3.12",
        }
        log_path = os.path.join(self.run_dir, "logs", "build.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("TEST_FIXTURE build log\n")
        prepared = {
            "schema": PROFILE.SCHEMA_PREPARE,
            "status": "PREPARED",
            "source": {
                "head_sha": self.source_sha,
                "origin_main_sha": self.source_sha,
                "merge_base": self.source_sha,
                "tracked_tree_clean": True,
            },
            "workload": PROFILE.WORKLOAD,
            "regime": PROFILE.REGIME,
            "warmups": PROFILE.WARMUPS,
            "min_profiled_requests": PROFILE.MIN_PROFILED_REQUESTS,
            "classes": [PROFILE.class_descriptor(name) for name in PROFILE.CLASS_NAMES],
            "matrix": {"n_values": list(PROFILE.N_VALUES), "k_values": list(PROFILE.K_VALUES)},
            "source_lock": PROFILE.source_lock(),
            "corpus": corpus_block,
            "build": {
                "command": ["cargo", "build", "--release"],
                "env": {"CARGO_PROFILE_RELEASE_DEBUG": "1"},
                "binary_path": "build/release/" + PROFILE.SYMBOL_NAME,
                "binary_bytes": os.path.getsize(self.binary),
                "binary_sha256": PROFILE.sha256_file(self.binary),
                "release_profile": True,
                "rustc_version": "fixture",
                "cargo_version": "fixture",
                "log_path": "logs/build.log",
                "log_sha256": PROFILE.sha256_file(log_path),
            },
            "adapter_evidence": {
                "adapter_binary_sha256": PROFILE.sha256_file(self.binary),
                "release_profile": True,
                "documents_indexed": max(PROFILE.N_VALUES),
                "documents_verified": max(PROFILE.N_VALUES),
                "oracle_ok": True,
                "index_backend": "FsDirectory",
                "analyzer": PROFILE.ANALYZER,
            },
            "indexes": indexes,
            "lanes": lanes,
            "tools": {
                "perf": {"status": "AVAILABLE", "version": "perf version fixture"},
                "heaptrack": {"status": "AVAILABLE", "version": "heaptrack fixture"},
                "heaptrack_print": {
                    "status": "AVAILABLE",
                    "version": "heaptrack_print fixture",
                },
            },
            "environment": environment,
            "host_fingerprint": PROFILE.host_fingerprint(environment),
            "canonical_report_status": "QUALIFIED",
            "limitations": PROFILE._prepare_environment_note(),
            "test_fixture": True,
        }
        prepared["prepared_digest"] = PROFILE.sha256_bytes(
            PROFILE.canonical_json_bytes(prepared)
        )
        PROFILE.write_json(os.path.join(self.run_dir, "prepare.json"), prepared)
        self.prepared = prepared
        self._previous_config_env = os.environ.get("PR15E_FIXTURE_ADAPTER_CONFIG")
        os.environ["PR15E_FIXTURE_ADAPTER_CONFIG"] = self.config_path
        self.write_attestation()
        return self

    def write_attestation(self, **overrides) -> None:
        start = (self.now - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = (self.now + datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {
            "schema": PROFILE.SCHEMA_ATTESTATION,
            "host": self.host,
            "start_utc": start,
            "end_utc": end,
            "operator_statement": (
                "Host testhost is idle from %s to %s; I authorize PR 15E-A CPU and "
                "heap allocation profiling for the frozen PR 15D workload." % (start, end)
            ),
        }
        payload.update(overrides)
        PROFILE.write_json(
            os.path.join(self.run_dir, "attestation.json"), payload
        )

    def behavior(self, n: int, **behavior) -> None:
        payload = PROFILE.read_json(self.config_path)
        payload["behavior"] = behavior
        PROFILE.write_json(self.config_path, payload)

    def deps(self, **overrides):
        now = self.now

        def clear_contention(path: str) -> dict:
            record = {"state": "clear", "reason_codes": []}
            PROFILE.write_json(path, record)
            return record

        values = {
            "head_sha": lambda: self.source_sha,
            "tree_clean": lambda: True,
            "hostname_probe": lambda: self.host,
            "now_utc": lambda: now,
            "perf_probe": lambda: {
                "path": self.scripts["perf"],
                "version": "perf version fixture",
                "origin": "test_fixture",
                "diagnostics": [],
            },
            "heaptrack_probe": lambda: {
                "path": self.scripts["heaptrack"],
                "version": "heaptrack fixture",
                "origin": "test_fixture",
            },
            "heaptrack_print_probe": lambda: {
                "path": self.scripts["heaptrack_print"],
                "version": "heaptrack_print fixture",
            },
            "contention_probe": clear_contention,
            "loop_seconds": lambda prescribed: 0.6,
        }
        values.update(overrides)
        return PROFILE.Deps(**values)

    def capture_args(self, n=10000, class_name="rare", k=100, tool="perf", seconds=None):
        return argparse.Namespace(
            run=self.run_dir,
            n=n,
            class_name=class_name,
            k=k,
            tool=tool,
            seconds=seconds if seconds is not None else PROFILE.lane_seconds(n, class_name),
            idle_confirmed=True,
        )

    def capture_dir(self, n=10000, class_name="rare", k=100, tool="perf") -> str:
        return os.path.join(
            self.run_dir, *PROFILE.capture_rel_dir(n, class_name, k, tool).split("/")
        )

    def cleanup(self) -> None:
        if getattr(self, "_previous_config_env", None) is None:
            os.environ.pop("PR15E_FIXTURE_ADAPTER_CONFIG", None)
        else:
            os.environ["PR15E_FIXTURE_ADAPTER_CONFIG"] = self._previous_config_env
        if os.path.isdir(self.run_dir):
            shutil.rmtree(self.run_dir, ignore_errors=True)


class FixtureTestCase(unittest.TestCase):
    def setUp(self):
        os.makedirs(TARGET_ROOT, exist_ok=True)
        self.fixture = RunFixture().build()
        self.addCleanup(self.fixture.cleanup)

    def assert_capture_failed(
        self, args, deps, *, status=None, code=None, expect_record=True
    ) -> dict | None:
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(args, deps)
        error = context.exception
        if status is not None:
            self.assertEqual(error.status, status, error)
        if code is not None:
            self.assertEqual(error.code, code, error)
        capture_dir = self.fixture.capture_dir(
            args.n, args.class_name, args.k, args.tool
        )
        self.assertFalse(
            os.path.isfile(os.path.join(capture_dir, "capture.json")),
            "a refused capture must never write capture.json",
        )
        failure_path = os.path.join(capture_dir, "failure.json")
        if expect_record:
            self.assertTrue(
                os.path.isfile(failure_path), "failure.json must be preserved"
            )
            return PROFILE.read_json(failure_path)
        self.assertFalse(os.path.exists(capture_dir))
        return None


# ---------------------------------------------------------------------------
# T01-T05: scope and oracle semantics
# ---------------------------------------------------------------------------


class ScopeAndOracleTests(unittest.TestCase):
    def test_t01_diff_allowlist_rejects_protected_paths(self):
        allowed = [
            "benchmarks/pr15e/profile.py",
            "benchmarks/pr15e/test_profile.py",
            "docs/pr-artifacts/pr-15e-a/investigation.md",
            "benchmarks/reports/pr15e-a/profile-manifest.json",
            "benchmarks/README.md",
            "docs/BENCHMARKING.md",
        ]
        self.assertEqual(PROFILE.classify_diff_paths(allowed), [])
        protected = [
            "crates/quervant-core/src/search/execute.rs",
            "benchmarks/pr15d/harness/run.py",
            "benchmarks/pr15d/spec/pr15d_v1.json",
            "benchmarks/reports/pr15d/pr15d-qualified.json",
            ".github/workflows/ci.yml",
            "Cargo.toml",
            "Cargo.lock",
            "benchmarks/scripts/profile-pr15b.sh",
            "docs/ARCHITECTURE.md",
        ]
        self.assertEqual(PROFILE.classify_diff_paths(protected), sorted(protected))

    def test_t02_absent_lane_has_zero_hits(self):
        rows = PROFILE.oracle.build_row_formula(10000)
        expected = PROFILE.oracle.expected(rows, "key", "never", 100)
        self.assertEqual(expected, {"total_hits": 0, "doc_ids": []})
        descriptor = PROFILE.lane_descriptor(10000, "absent", 100)
        self.assertEqual(descriptor["field"], "key")

    def test_t03_rare_lane_has_single_hit(self):
        rows = PROFILE.oracle.build_row_formula(100000)
        expected = PROFILE.oracle.expected(rows, "key", "singleton", 100)
        self.assertEqual(expected, {"total_hits": 1, "doc_ids": ["d00000000"]})

    def test_t04_medium_matches_n_over_eight(self):
        rows = PROFILE.oracle.build_row_formula(100000)
        expected = PROFILE.oracle.expected(rows, "group", "medium", 10)
        self.assertEqual(expected["total_hits"], 100000 // 8)
        self.assertEqual(len(expected["doc_ids"]), 10)
        self.assertEqual(expected["doc_ids"][0], "d00000000")
        self.assertEqual(expected["doc_ids"][1], "d00000008")
        wide = PROFILE.oracle.expected(rows, "group", "medium", 100)
        self.assertEqual(len(wide["doc_ids"]), 100)
        self.assertEqual(wide["doc_ids"][:10], expected["doc_ids"])
        for doc_id in wide["doc_ids"]:
            self.assertEqual(int(doc_id[1:]) % 8, 0)

    def test_t05_common_matches_n_over_two_minus_one(self):
        rows = PROFILE.oracle.build_row_formula(100000)
        for k in (10, 100):
            expected = PROFILE.oracle.expected(rows, "key", "common", k)
            self.assertEqual(expected["total_hits"], 100000 // 2 - 1)
            self.assertEqual(len(expected["doc_ids"]), k)
            self.assertEqual(expected["doc_ids"][0], "d00000002")
            self.assertEqual(expected["doc_ids"], sorted(expected["doc_ids"]))

    def test_perf_sample_count_parsing_handles_abbreviations(self):
        for text, expected in (
            ("# Samples: 500  of event 'cycles:Pu'", 500),
            ("# Samples: 11K of event 'cycles:Pu'", 11000),
            ("# Samples: 1.5K of event 'cycles:Pu'", 1500),
            ("# Samples: 2M of event 'cpu-clock'", 2_000_000),
            ("# Samples: 7", 7),
            ("no header here", None),
        ):
            self.assertEqual(PROFILE.parse_perf_samples(text), expected, text)

    def test_perf_lost_sample_parsing(self):
        self.assertEqual(
            PROFILE.parse_perf_lost_samples("# Total Lost Samples: 3\n"), 3
        )
        self.assertEqual(
            PROFILE.parse_perf_lost_samples("lost chunks: 4\n"), 4
        )
        self.assertEqual(PROFILE.parse_perf_lost_samples("clean"), 0)

    def test_fixed_matrix_has_twenty_captures(self):
        captures = PROFILE.required_captures()
        self.assertEqual(len(captures), 20)
        perf = [entry for entry in captures if entry["tool"] == "perf"]
        heaptrack = [entry for entry in captures if entry["tool"] == "heaptrack"]
        self.assertEqual(len(perf), 12)
        self.assertEqual(len(heaptrack), 8)
        self.assertEqual(
            len({entry["capture_id"] for entry in captures}), 20
        )
        for entry in captures:
            self.assertEqual(entry["seconds"], PROFILE.lane_seconds(entry["n"], entry["class"]))


# ---------------------------------------------------------------------------
# T15-T19: argument and argv guards
# ---------------------------------------------------------------------------


class ArgumentTests(FixtureTestCase):
    def test_t15_invalid_enum_values_are_typed(self):
        for n, class_name, k, tool in (
            (20000, "rare", 100, "perf"),
            (10000, "bogus", 100, "perf"),
            (10000, "rare", 25, "perf"),
            (10000, "rare", 100, "bogus"),
            (True, "rare", 100, "perf"),
        ):
            with self.assertRaises(PROFILE.Pr15eError) as context:
                PROFILE.validate_capture_args(
                    n, class_name, k, tool, PROFILE.lane_seconds(10000, "rare")
                )
            self.assertEqual(context.exception.status, "USAGE")

    def test_t15_cli_returns_usage_exit_code(self):
        code = PROFILE.main(
            [
                "capture",
                "--run",
                self.fixture.run_dir,
                "--n",
                "20000",
                "--class",
                "rare",
                "--k",
                "100",
                "--tool",
                "perf",
                "--seconds",
                "20",
                "--idle-confirmed",
            ]
        )
        self.assertEqual(code, PROFILE.EXIT_USAGE)

    def test_t16_k10_control_is_100k_only(self):
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.validate_capture_args(10000, "rare", 10, "perf", 20)
        self.assertIn("K=10 control", context.exception.detail)
        descriptor = PROFILE.validate_capture_args(100000, "rare", 10, "perf", 30)
        self.assertEqual(descriptor["tool"], "perf")
        with self.assertRaises(PROFILE.Pr15eError):
            PROFILE.validate_capture_args(100000, "rare", 10, "heaptrack", 30)

    def test_t17_wrong_seconds_are_rejected(self):
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.validate_capture_args(100000, "common", 100, "perf", 20)
        self.assertEqual(context.exception.status, "USAGE")
        self.assertIn("--seconds 60", context.exception.detail)
        with self.assertRaises(PROFILE.Pr15eError):
            PROFILE.validate_capture_args(10000, "absent", 100, "perf", 0)

    def test_t18_unknown_cli_option_is_rejected(self):
        with self.assertRaises(SystemExit) as context:
            PROFILE.main(
                [
                    "capture",
                    "--run",
                    self.fixture.run_dir,
                    "--n",
                    "10000",
                    "--class",
                    "rare",
                    "--k",
                    "100",
                    "--tool",
                    "perf",
                    "--seconds",
                    "20",
                    "--allow-contended",
                ]
            )
        self.assertEqual(context.exception.code, 2)

    def test_t19_profiler_must_target_the_prepared_adapter(self):
        fixture = self.fixture
        tool_info = {"path": fixture.scripts["perf"], "version": "fixture"}
        capture_dir = os.path.join(fixture.run_dir, "captures-probe")
        argv = PROFILE.profiler_argv(
            "perf", tool_info, fixture.binary, "/tmp/index", capture_dir
        )
        PROFILE.validate_argv_target(argv, fixture.binary)
        python_argv = PROFILE.profiler_argv(
            "perf", tool_info, sys.executable, "/tmp/index", capture_dir
        )
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.validate_argv_target(python_argv, fixture.binary)
        self.assertEqual(context.exception.code, "X22_PROFILER_TARGET")
        heaptrack_argv = PROFILE.profiler_argv(
            "heaptrack",
            {"path": fixture.scripts["heaptrack"], "version": "fixture"},
            fixture.binary,
            "/tmp/index",
            capture_dir,
        )
        PROFILE.validate_argv_target(heaptrack_argv, fixture.binary)
        self.assertNotIn("--", heaptrack_argv)


# ---------------------------------------------------------------------------
# T11-T14, T28-T30: source lock, corpus/index identity and path safety
# ---------------------------------------------------------------------------


class SourceLockTests(FixtureTestCase):
    def test_t11_changed_corpus_is_refused(self):
        corpus = os.path.join(
            self.fixture.run_dir, "corpus", PROFILE.oracle.corpus_filename(10000)
        )
        with open(corpus, "ab") as handle:
            handle.write(b"tampered\n")
        self.assert_capture_failed(
            self.fixture.capture_args(), self.fixture.deps(), status="HARD_STOP",
            code="X24_CORPUS_INVALID", expect_record=False,
        )

    def test_t12_changed_adapter_binary_is_refused(self):
        with open(self.fixture.binary, "ab") as handle:
            handle.write(b"\n# tampered\n")
        self.assert_capture_failed(
            self.fixture.capture_args(), self.fixture.deps(), status="HARD_STOP",
            code="X24_BINARY_CHANGED", expect_record=False,
        )

    def test_t13_changed_source_sha_is_refused(self):
        deps = self.fixture.deps(head_sha=lambda: "b" * 40)
        self.assert_capture_failed(
            self.fixture.capture_args(), deps, status="HARD_STOP",
            code="X24_SOURCE_CHANGED", expect_record=False,
        )

    def test_t14_changed_or_missing_index_is_never_rebuilt(self):
        index_dir = os.path.join(self.fixture.run_dir, "indexes", "n10000")
        segment = os.path.join(index_dir, "index", "segment.seg")
        with open(segment, "ab") as handle:
            handle.write(b"tampered")
        before = PROFILE.index_inventory(index_dir)["sha256"]
        self.assert_capture_failed(
            self.fixture.capture_args(), self.fixture.deps(), status="HARD_STOP",
            code="X24_INDEX_CHANGED", expect_record=False,
        )
        after = PROFILE.index_inventory(index_dir)["sha256"]
        self.assertEqual(before, after, "the driver must never rebuild or repair an index")
        shutil.rmtree(index_dir)
        self.assert_capture_failed(
            self.fixture.capture_args(), self.fixture.deps(), code="X24_INDEX_CHANGED",
            expect_record=False,
        )

    def test_t28_path_traversal_is_rejected_before_writing(self):
        for raw in (
            "target/pr15e/../pr15e/escape",
            "../escape",
            "target/pr15e",
            "/etc/escape",
            "target/pr15e/sub/../../escape",
        ):
            with self.assertRaises(PROFILE.Pr15eError):
                PROFILE.resolve_run_dir(raw, must_exist=False)
        outside = os.path.join(PROFILE.REPO_ROOT, "escape-dir")
        self.assertFalse(os.path.exists(outside))

    def test_t29_symlink_inside_run_tree_is_rejected(self):
        target = os.path.join(self.fixture.run_dir, "linked")
        os.symlink(os.path.join(self.fixture.run_dir, "corpus"), target)
        self.assertIn("linked", PROFILE.iter_symlinks(self.fixture.run_dir))
        link = os.path.join(TARGET_ROOT, f"selftest-link-{uuid.uuid4().hex[:8]}")
        os.symlink(self.fixture.run_dir, link)
        self.addCleanup(os.unlink, link)
        try:
            with self.assertRaises(PROFILE.Pr15eError) as context:
                PROFILE.resolve_run_dir(
                    os.path.join("target", "pr15e", os.path.basename(link)),
                    must_exist=True,
                )
            self.assertEqual(context.exception.status, "UNSAFE")
        finally:
            pass
        # An index directory replaced by a symlink must fail closed as well.
        index_dir = os.path.join(self.fixture.run_dir, "indexes", "n10000")
        shutil.rmtree(index_dir)
        os.symlink(os.path.join(self.fixture.run_dir, "corpus"), index_dir)
        self.assert_capture_failed(
            self.fixture.capture_args(), self.fixture.deps(), code="X24_INDEX_CHANGED",
            expect_record=False,
        )

    def test_t30_destinations_are_never_overwritten(self):
        occupied = os.path.join(TARGET_ROOT, f"selftest-occupied-{uuid.uuid4().hex[:8]}")
        os.makedirs(occupied)
        with open(os.path.join(occupied, "existing.txt"), "w", encoding="utf-8") as handle:
            handle.write("preserve me\n")
        self.addCleanup(shutil.rmtree, occupied, True)
        args = argparse.Namespace(out=occupied)
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.prepare(args, PROFILE.Deps(tree_clean=lambda: True))
        self.assertEqual(context.exception.code, "X28_DESTINATION_EXISTS")
        self.assertEqual(os.listdir(occupied), ["existing.txt"])

        capture_args = self.fixture.capture_args()
        deps = self.fixture.deps()
        self.assertEqual(PROFILE.capture(capture_args, deps), PROFILE.EXIT_OK)
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(capture_args, deps)
        self.assertEqual(context.exception.code, "X28_DESTINATION_EXISTS")

    def test_prepare_refuses_a_dirty_tree(self):
        run_dir = os.path.join(TARGET_ROOT, f"selftest-dirty-{uuid.uuid4().hex[:8]}")
        args = argparse.Namespace(out=run_dir)
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.prepare(args, PROFILE.Deps(tree_clean=lambda: False))
        self.assertEqual(context.exception.code, "X08_DIRTY_TREE")
        self.assertTrue(
            os.path.isfile(os.path.join(run_dir, "prepare-failed.json"))
        )
        self.assertFalse(os.path.isfile(os.path.join(run_dir, "prepare.json")))
        shutil.rmtree(run_dir, True)


# ---------------------------------------------------------------------------
# T06-T09, T20-T27: capture semantics through the profiled process boundary
# ---------------------------------------------------------------------------


class CaptureTests(FixtureTestCase):
    def test_t06_t08_one_adapter_process_per_capture(self):
        first = PROFILE.capture(self.fixture.capture_args(), self.fixture.deps())
        self.assertEqual(first, PROFILE.EXIT_OK)
        manifest_one = PROFILE.read_json(
            os.path.join(self.fixture.capture_dir(), "capture.json")
        )
        self.assertEqual(manifest_one["adapter_pid_sample_count"], 3)
        self.assertGreater(manifest_one["profiled_query_count"], 0)
        self.assertEqual(manifest_one["warmups"], PROFILE.WARMUPS)

        # A second capture in a fresh process must record a different adapter PID.
        second_args = self.fixture.capture_args(class_name="absent")
        self.assertEqual(PROFILE.capture(second_args, self.fixture.deps()), PROFILE.EXIT_OK)
        manifest_two = PROFILE.read_json(
            os.path.join(self.fixture.capture_dir(class_name="absent"), "capture.json")
        )
        self.assertNotEqual(manifest_one["adapter_pid"], manifest_two["adapter_pid"])
        self.assertFalse(manifest_two["test_fixture"])

    def test_t09_real_adapter_evidence_is_required(self):
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.assert_real_adapter_evidence({"adapter": "mock"})
        self.assertEqual(context.exception.code, "X30_MOCK_EVIDENCE")
        with self.assertRaises(PROFILE.Pr15eError):
            PROFILE.assert_real_adapter_evidence(
                {
                    "adapter_binary_sha256": "x",
                    "release_profile": True,
                    "documents_indexed": 1,
                    "documents_verified": 2,
                    "oracle_ok": True,
                    "index_backend": "FsDirectory",
                    "analyzer": PROFILE.ANALYZER,
                }
            )
        PROFILE.assert_real_adapter_evidence(
            {
                "adapter_binary_sha256": "x",
                "release_profile": True,
                "documents_indexed": 100000,
                "documents_verified": 100000,
                "oracle_ok": True,
                "index_backend": "FsDirectory",
                "analyzer": PROFILE.ANALYZER,
            }
        )
        PROFILE.assert_real_adapter_evidence(self.fixture.prepared["adapter_evidence"])

    def test_t20_perf_empty_data_is_not_captured_raw(self):
        args = self.fixture.capture_args()
        with self._env({"FAKE_PERF_MODE": "no-data"}):
            with self.assertRaises(PROFILE.Pr15eError) as context:
                PROFILE.capture(args, self.fixture.deps())
        self.assertEqual(context.exception.status, "BLOCKED")
        self.assertEqual(context.exception.code, "X19_PERF_EMPTY")
        self.assertFalse(
            os.path.isfile(os.path.join(self.fixture.capture_dir(), "capture.json"))
        )
        self.assertTrue(
            os.path.isfile(os.path.join(self.fixture.capture_dir(), "failure.json"))
        )

    def test_t20b_perf_nonzero_exit_is_failed(self):
        args = self.fixture.capture_args()
        with self._env({"FAKE_PERF_MODE": "record-exit"}):
            with self.assertRaises(PROFILE.Pr15eError) as context:
                PROFILE.capture(args, self.fixture.deps())
        self.assertEqual(context.exception.status, "FAILED")
        self.assertEqual(context.exception.code, "X20_PROFILER_FAILED")

    def test_t20c_perf_report_failures_are_blocked(self):
        for mode, code in (
            ("report-exit", "X19_PERF_REPORT"),
            ("few-samples", "X19_PERF_SAMPLES"),
            ("no-symbols", "X19_PERF_SYMBOLS"),
        ):
            fixture = RunFixture().build()
            self.addCleanup(fixture.cleanup)
            with self._env({"FAKE_PERF_MODE": mode}):
                with self.assertRaises(PROFILE.Pr15eError) as context:
                    PROFILE.capture(fixture.capture_args(), fixture.deps())
            self.assertEqual(context.exception.status, "BLOCKED", mode)
            self.assertEqual(context.exception.code, code, mode)

    def test_t21_heaptrack_raw_artifacts_must_be_unambiguous(self):
        for mode, expected in (("no-raw", "X20_HEAPTRACK_RAW"), ("two-raw", "X20_HEAPTRACK_RAW")):
            fixture = RunFixture().build()
            self.addCleanup(fixture.cleanup)
            with self._env({"FAKE_HEAPTRACK_MODE": mode}):
                with self.assertRaises(PROFILE.Pr15eError) as context:
                    PROFILE.capture(
                        fixture.capture_args(tool="heaptrack"), fixture.deps()
                    )
            self.assertEqual(context.exception.status, "BLOCKED", mode)
            self.assertEqual(context.exception.code, expected, mode)

    def test_t22_profiler_banner_is_a_hard_stop_with_preserved_raw(self):
        args = self.fixture.capture_args(tool="heaptrack")
        with self._env({"FAKE_HEAPTRACK_MODE": "banner"}):
            with self.assertRaises(PROFILE.Pr15eError) as context:
                PROFILE.capture(args, self.fixture.deps())
        self.assertEqual(context.exception.status, "HARD_STOP")
        self.assertEqual(context.exception.code, "X22_PROFILER_NOT_RELAYING")
        capture_dir = self.fixture.capture_dir(tool="heaptrack")
        self.assertFalse(os.path.isfile(os.path.join(capture_dir, "capture.json")))
        self.assertTrue(os.path.isfile(os.path.join(capture_dir, "failure.json")))
        self.assertTrue(os.path.isfile(os.path.join(capture_dir, "profiler-stderr.txt")))

    def test_t23_incomplete_warmups_are_refused(self):
        self.fixture.behavior(10000, wrong_warmup=3)
        failure = self.assert_capture_failed(
            self.fixture.capture_args(), self.fixture.deps(), status="HARD_STOP",
            code="X23_ORACLE",
        )
        self.assertEqual(failure["capture_id"], "pr15e/n10000/rare/k100/perf")
        self.assertFalse(
            os.path.isfile(os.path.join(self.fixture.capture_dir(), "capture.json"))
        )

    def test_t24_insufficient_profiled_requests_are_not_qualified(self):
        self.fixture.behavior(10000, profiled_delay_ms=1000)
        args = self.fixture.capture_args()
        deps = self.fixture.deps(loop_seconds=lambda prescribed: 1.2)
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(args, deps)
        self.assertEqual(context.exception.status, "BLOCKED")
        self.assertEqual(context.exception.code, "X26_INSUFFICIENT_SAMPLES")
        self.assertFalse(
            os.path.isfile(os.path.join(self.fixture.capture_dir(), "capture.json"))
        )

    def test_t25_altered_total_hits_aborts(self):
        self.fixture.behavior(10000, wrong_total=True)
        self.assert_capture_failed(
            self.fixture.capture_args(), self.fixture.deps(), status="HARD_STOP",
            code="X23_ORACLE",
        )

    def test_t26_altered_doc_ids_aborts(self):
        self.fixture.behavior(10000, wrong_ids=True)
        self.assert_capture_failed(
            self.fixture.capture_args(class_name="medium"), self.fixture.deps(),
            status="HARD_STOP", code="X23_ORACLE",
        )

    def test_t27_child_death_cleans_the_process_group(self):
        self.fixture.behavior(10000, exit_after=2)
        args = self.fixture.capture_args()
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(args, self.fixture.deps())
        self.assertEqual(context.exception.status, "FAILED")
        self.assertIn(context.exception.code, ("X27_CHILD_DEATH", "X26_RESPONSE_TIMEOUT"))
        capture_dir = self.fixture.capture_dir()
        self.assertFalse(os.path.isfile(os.path.join(capture_dir, "capture.json")))
        self.assertTrue(os.path.isfile(os.path.join(capture_dir, "failure.json")))

    def test_adapter_error_status_fails_the_capture(self):
        self.fixture.behavior(10000, error_status=True)
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(self.fixture.capture_args(), self.fixture.deps())
        self.assertEqual(context.exception.code, "X27_ADAPTER_ERROR")

    def test_t37_missing_perf_is_blocked(self):
        args = self.fixture.capture_args()

        def absent():
            raise PROFILE.blocked("X13_PERF_UNAVAILABLE", "perf is not usable")

        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(args, self.fixture.deps(perf_probe=absent))
        self.assertEqual(context.exception.status, "BLOCKED")
        self.assertEqual(context.exception.code, "X13_PERF_UNAVAILABLE")
        self.assertFalse(
            os.path.isfile(os.path.join(self.fixture.capture_dir(), "capture.json"))
        )

    def test_t38_missing_heaptrack_print_is_blocked(self):
        args = self.fixture.capture_args(tool="heaptrack")

        def absent():
            raise PROFILE.blocked(
                "X11_HEAPTRACK_PRINT_UNAVAILABLE", "heaptrack_print is missing"
            )

        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(args, self.fixture.deps(heaptrack_print_probe=absent))
        self.assertEqual(context.exception.code, "X11_HEAPTRACK_PRINT_UNAVAILABLE")

    def test_heaptrack_happy_path_records_allocation_evidence(self):
        args = self.fixture.capture_args(tool="heaptrack")
        self.assertEqual(PROFILE.capture(args, self.fixture.deps()), PROFILE.EXIT_OK)
        manifest = PROFILE.read_json(
            os.path.join(self.fixture.capture_dir(tool="heaptrack"), "capture.json")
        )
        records = manifest["tool_evidence"]["records"]
        self.assertEqual(records["allocation_sites"], 2)
        self.assertEqual(records["total_allocations"], 350)
        self.assertTrue(records["has_calls_section"])

    def _env(self, values):
        class _Env:
            def __enter__(self_inner):
                self_inner.saved = {key: os.environ.get(key) for key in values}
                os.environ.update(values)

            def __exit__(self_inner, *exc):
                for key, value in self_inner.saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                return False

        return _Env()


# ---------------------------------------------------------------------------
# T39: attestation, window and contention gates
# ---------------------------------------------------------------------------


class AttestationTests(FixtureTestCase):
    def test_t39_missing_attestation_is_blocked(self):
        os.remove(os.path.join(self.fixture.run_dir, "attestation.json"))
        args = self.fixture.capture_args()
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(args, self.fixture.deps())
        self.assertEqual(context.exception.code, "BLOCKED_ATTESTATION")
        self.assertFalse(
            os.path.isfile(os.path.join(self.fixture.capture_dir(), "capture.json"))
        )
        self.assertFalse(os.path.isdir(self.fixture.capture_dir()))

    def test_t39_flag_alone_is_not_evidence(self):
        os.remove(os.path.join(self.fixture.run_dir, "attestation.json"))
        args = self.fixture.capture_args()
        args.idle_confirmed = True
        with self.assertRaises(PROFILE.Pr15eError):
            PROFILE.capture(args, self.fixture.deps())

    def test_t39_idle_flag_is_required(self):
        args = self.fixture.capture_args()
        args.idle_confirmed = False
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(args, self.fixture.deps())
        self.assertEqual(context.exception.code, "BLOCKED_ATTESTATION")

    def test_t39_expired_window_is_blocked(self):
        later = self.fixture.now + datetime.timedelta(hours=5)
        args = self.fixture.capture_args()
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(args, self.fixture.deps(now_utc=lambda: later))
        self.assertEqual(context.exception.code, "BLOCKED_ATTESTATION")

    def test_t39_short_window_is_blocked(self):
        end = (self.fixture.now + datetime.timedelta(seconds=60)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        self.fixture.write_attestation(end_utc=end)
        args = self.fixture.capture_args()
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(args, self.fixture.deps())
        self.assertEqual(context.exception.code, "BLOCKED_ATTESTATION")

    def test_t39_wrong_host_is_blocked(self):
        args = self.fixture.capture_args()
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(
                args, self.fixture.deps(hostname_probe=lambda: "other-host")
            )
        self.assertEqual(context.exception.code, "BLOCKED_ATTESTATION")

    def test_t39_statement_without_pr_label_is_blocked(self):
        self.fixture.write_attestation(operator_statement="just do it")
        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(self.fixture.capture_args(), self.fixture.deps())
        self.assertEqual(context.exception.code, "BLOCKED_ATTESTATION")

    def test_t39_contention_is_blocked(self):
        def suspect(path):
            record = {"state": "suspect", "reason_codes": ["fixture"]}
            PROFILE.write_json(path, record)
            return record

        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(
                self.fixture.capture_args(),
                self.fixture.deps(contention_probe=suspect),
            )
        self.assertEqual(context.exception.code, "X18_CONTENTION")
        self.assertEqual(context.exception.status, "BLOCKED")

    def test_t39_window_end_during_capture_is_outside_window(self):
        moments = [self.fixture.now, self.fixture.now, self.fixture.now + datetime.timedelta(hours=6)]
        calls = {"index": 0}

        def advancing_now():
            value = moments[min(calls["index"], len(moments) - 1)]
            calls["index"] += 1
            return value

        with self.assertRaises(PROFILE.Pr15eError) as context:
            PROFILE.capture(
                self.fixture.capture_args(),
                self.fixture.deps(now_utc=advancing_now),
            )
        self.assertEqual(context.exception.code, "OUTSIDE_WINDOW")


# ---------------------------------------------------------------------------
# Real Quervant adapter/index/oracle integration (G03)
# ---------------------------------------------------------------------------


class RealAdapterIntegrationTest(unittest.TestCase):
    """Opt-in real-boundary test: real cargo build, FsDirectory, real oracle."""

    @unittest.skipUnless(
        os.environ.get("PR15E_RUN_REAL_INTEGRATION") == "1",
        "set PR15E_RUN_REAL_INTEGRATION=1 to execute the real-adapter integration",
    )
    def test_real_prepare_and_session(self):
        run_dir = os.path.join(TARGET_ROOT, f"it-real-{uuid.uuid4().hex[:8]}")
        self.addCleanup(shutil.rmtree, run_dir, True)
        args = argparse.Namespace(out=run_dir)
        deps = PROFILE.Deps(tree_clean=lambda: True)
        started = time.monotonic()
        self.assertEqual(PROFILE.prepare(args, deps), PROFILE.EXIT_OK)
        elapsed = time.monotonic() - started
        prepared = PROFILE.read_json(os.path.join(run_dir, "prepare.json"))
        for n in PROFILE.N_VALUES:
            index = prepared["indexes"][str(n)]
            self.assertEqual(index["documents_indexed"], n)
            self.assertEqual(index["documents_verified"], n)
            self.assertGreater(index["inventory"]["bytes"], 0)
            self.assertGreaterEqual(index["inventory"]["file_count"], 2)
        self.assertEqual(len(prepared["lanes"]), 12)
        for lane in prepared["lanes"]:
            self.assertTrue(lane["adapter_smoke"]["oracle_ok"])
        PROFILE.assert_real_adapter_evidence(prepared["adapter_evidence"])
        self.assertLess(elapsed, 1800, "prepare must finish in a bounded time")

        # The real adapter must serve the whole warm session from one process.
        binary = os.path.join(run_dir, prepared["build"]["binary_path"])
        index_dir = os.path.join(run_dir, prepared["indexes"]["10000"]["path"])
        _, rows_by_n = PROFILE.load_corpus(run_dir)
        process = subprocess.Popen(
            [binary, "--index-dir", index_dir],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
        )
        transport = PROFILE.ProfiledTransport(process, label="real-integration")
        try:
            for cycle in range(2):
                for class_name in PROFILE.CLASS_NAMES:
                    descriptor = PROFILE.lane_descriptor(10000, class_name, 100)
                    expected = PROFILE.recompute_expected(rows_by_n, descriptor)
                    response = transport.request(
                        {
                            "request_id": f"it:{cycle}:{class_name}",
                            "op": "query",
                            "field": descriptor["field"],
                            "term": descriptor["term"],
                            "k": descriptor["k"],
                            "mode": PROFILE.REGIME,
                        }
                    )
                    PROFILE.validate_response_against_oracle(response, descriptor, expected)
            self.assertIn(process.pid, PROFILE.adapter_pids(os.getpid(), binary))
        finally:
            transport.request({"request_id": "it:shutdown", "op": "shutdown"})
            transport.close_stdin()
            self.assertEqual(process.wait(timeout=60), 0)
            transport.close()

        self.assertTrue(os.path.isfile(os.path.join(run_dir, "prepare.json")))


if __name__ == "__main__":
    unittest.main()
