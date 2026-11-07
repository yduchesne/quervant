#!/usr/bin/env python3
"""Deterministic controller tests for ``benchmarks/pr15i_0/verify.py``.

Every fixture here is synthetic (``test_fixture: true``) and lives in a temporary
directory. Synthetic fixtures can prove a gate *rejects* bad evidence; they can
never qualify a real measurement campaign.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import verify  # noqa: E402  (module under test)

SOURCE = "0123456789abcdef0123456789abcdef01234567"
OTHER_SOURCE = "fedcba9876543210fedcba9876543210fedcba98"
CORPUS_MANIFEST = "1" * 64
CORPUS_DIGESTS = {"10000": "2" * 64, "100000": "3" * 64}


def canonical_json_bytes(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        + b"\n"
    )


def write_json(path: str, payload) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = canonical_json_bytes(payload)
    with open(path, "wb") as handle:
        handle.write(data)
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Campaign fixture
# ---------------------------------------------------------------------------


def pr15d_lanes(source=SOURCE, *, oracle_ok=True, contention="clear", engine=None):
    lanes = []
    for n in verify.PR15D_N:
        for class_name in verify.PR15D_CLASSES:
            for k in verify.PR15D_K:
                for regime in verify.PR15D_REGIMES:
                    lane_id = f"pr15d_v1/{n}/{class_name}/k{k}"
                    lanes.append(
                        {
                            "id": lane_id,
                            "n": n,
                            "class": class_name,
                            "k": k,
                            "regime": regime,
                            "field": "key" if class_name != "medium" else "group",
                            "analyzer": "keyword-exact",
                            "oracle_ok": oracle_ok,
                            "expected_total_hits": 0,
                            "expected_doc_ids": [],
                            "doc_ids": [],
                            "samples_ns": [1000 + index for index in range(20)],
                            "summary_ns": {
                                "count": 20,
                                "min": 1000,
                                "median": 1009,
                                "max": 1019,
                                "p95": 1018,
                                "p99": 1019,
                            },
                            "contention": {"pre": contention, "post": contention},
                            "allocations": "NOT_MEASURED",
                        }
                    )
    return lanes


def build_pr15d_run(root: str, *, source=SOURCE, **lane_overrides) -> str:
    run_dir = os.path.join(root, "target", "pr15d", "runs", "run-01")
    os.makedirs(run_dir, exist_ok=True)
    run = {
        "schema": "pr15d-run-v1",
        "run_id": "run-01",
        "source_sha": source,
        "workload": "pr15d_v1",
        "corpus_manifest_sha256": CORPUS_MANIFEST,
        "corpus_digests": dict(CORPUS_DIGESTS),
        "environment": {"filesystem": "ext4", "native_filesystem": True},
        "host_fingerprint": {"cpu_model": "fixture", "kernel": "fixture"},
        "adapters": {},
        "idle_attested": True,
        "native_filesystem": True,
        "filesystem": "ext4",
        "trials": 3,
        "status": "complete",
        "qualified": True,
        "blockers": [],
        "scored_lane": {"status": "SEMANTICALLY_NONCOMPARABLE", "reason": "fixture"},
    }
    write_json(os.path.join(run_dir, "run.json"), run)
    for trial in (1, 2, 3):
        for engine in verify.PR15D_ENGINES:
            manifest = {
                "schema": "pr15d-trial-v1",
                "trial": trial,
                "engine": engine,
                "engine_version": f"{engine}-fixture",
                "source_sha": source,
                "host_fingerprint": {"cpu_model": "fixture"},
                "filesystem": "ext4",
                "native_filesystem": True,
                "operator_idle_attested": True,
                "corpus_manifest_sha256": CORPUS_MANIFEST,
                "corpus_digests": dict(CORPUS_DIGESTS),
                "build": {
                    str(n): {
                        "documents_indexed": n,
                        "documents_verified": n,
                        "expected_documents": n,
                        "verified": True,
                        "index_bytes": 1000 * n + len(engine),
                        "index_ns": 10,
                        "commit_ns": 20,
                        "reopen_ns": 30,
                        "segment_count": 1,
                    }
                    for n in verify.PR15D_N
                },
                "lanes": pr15d_lanes(source, **lane_overrides),
                "throughput": [],
                "contention": [
                    {"phase": "pre", "n": n, "state": "clear"} for n in verify.PR15D_N
                ],
                "qualified": True,
                "unqualified_reasons": [],
            }
            write_json(
                os.path.join(run_dir, "trials", f"trial-{trial}", f"{engine}.json"), manifest
            )
    return run_dir


def build_prepared(root: str, *, source=SOURCE) -> str:
    prepared = os.path.join(root, "target", "pr15e", "prepared-01")
    os.makedirs(prepared, exist_ok=True)
    indexes = {}
    for n in verify.PR15D_N:
        index_root = os.path.join(prepared, "indexes", f"n{n}")
        state_bytes = f"state-{n}".encode()
        state_hash = hashlib.sha256(state_bytes).hexdigest()
        files = {
            "index/CURRENT": b"current",
            "index/manifests/g-0000000000000001.manifest": b"manifest",
            f"index/state/{state_hash}.state": state_bytes,
            "index/segments/segment.seg": b"segment",
        }
        entries = []
        for relative, payload in files.items():
            path = os.path.join(index_root, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(payload)
            entries.append(
                {
                    "path": relative,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        entries.sort(key=lambda entry: entry["path"])
        content = hashlib.sha256(canonical_json_bytes(entries)).hexdigest()
        indexes[str(n)] = {
            "path": f"indexes/n{n}",
            "index_bytes": sum(entry["bytes"] for entry in entries),
            "documents_indexed": n,
            "documents_verified": n,
            "index_ns": 10,
            "commit_ns": 20,
            "reopen_ns": 30,
            "segment_count": 1,
            "inventory": {
                "bytes": sum(entry["bytes"] for entry in entries),
                "file_count": len(entries),
                "entries": entries,
                "sha256": content,
            },
        }
    prepare = {
        "schema": "pr15e-prepare-v1",
        "status": "PREPARED",
        "source": {"head_sha": source, "tracked_tree_clean": True},
        "corpus": {
            "manifest_sha256": CORPUS_MANIFEST,
            "corpora": {
                key: {"sha256": value} for key, value in CORPUS_DIGESTS.items()
            },
        },
        "indexes": indexes,
        "lanes": [],
    }
    write_json(os.path.join(prepared, "prepare.json"), prepare)
    return prepared


def build_pr15f_run(root: str, prepared: str, *, source=SOURCE, query_status="CAPTURED"):
    run_dir = os.path.join(root, "target", "pr15f", "run-01")
    os.makedirs(run_dir, exist_ok=True)
    prepare = verify.read_json(os.path.join(prepared, "prepare.json"))
    write_json(
        os.path.join(run_dir, "preflight.json"),
        {
            "schema": "pr15f-prepare-v1",
            "status": "PREPARED",
            "source_sha": source,
            "prepared_digest": prepare.get("prepared_digest"),
            "environment": {"kernel": "fixture"},
        },
    )
    lanes = []
    for n, class_name, k in verify.PR15F_QUERY_LANES:
        lanes.append(
            {
                "capture_id": f"pr15f/n{n}/{class_name}/k{k}/perf",
                "lane_id": f"pr15f/n{n}/{class_name}/k{k}",
                "n": n,
                "class": class_name,
                "k": k,
                "tool": "perf",
                "seconds": 20,
                "status": query_status,
            }
        )
    write_json(
        os.path.join(run_dir, "query-campaign.json"),
        {
            "schema": "pr15f-query-campaign-v1",
            "status": "QUALIFIED" if query_status == "CAPTURED" else "BLOCKED",
            "required": len(verify.PR15F_QUERY_LANES),
            "captured": len(
                [lane for lane in lanes if lane["status"] == "CAPTURED"]
            ),
            "hard_stop": None,
            "lanes": lanes,
        },
    )
    query_frames = {}
    for n, class_name, k in verify.PR15F_QUERY_LANES:
        lane_id = f"pr15f/n{n}/{class_name}/k{k}"
        query_frames[lane_id] = {
            "lane_id": lane_id,
            "source_sha": source,
            "n": n,
            "class": class_name,
            "k": k,
            "sample_count": 5000,
            "lost_samples": 0,
            "warmups": 5,
            "contention_before": "clear",
            "contention_after": "clear",
            "exclusive_percent": {"G01": 10.0, "G05": 30.0, "G08": 60.0},
            "allocated_exclusive_percent": {"G01": 10.0, "G05": 30.0},
            "inclusive_percent": {"G01": 20.0, "G05": 90.0},
            "unknown_exclusive_percent": 60.0,
            "unparsed_remainder_percent": 5.0,
            "groups": {"G08": "unclassified"},
            "rank": {"classification": "UNRESOLVED"},
        }
    write_json(
        os.path.join(run_dir, "analysis.json"),
        {
            "schema": "pr15f-attribution-v1",
            "measured_source_sha": source,
            "query": query_frames,
            "reopen": {},
            "layout": {},
            "ranking_rules": {},
        },
    )
    samples = [
        {
            "documents": 10000,
            "fs_directory_open_ns": 1,
            "index_open_ns": 2,
            "reopen_core_ns": 3,
            "reopen_total_ns": 4,
            "snapshot_acquire_ns": 5,
            "generation": 1,
            "segments": 1,
        }
        for _ in range(verify.PR15F_REOPEN_PER_N)
    ]
    write_json(
        os.path.join(run_dir, "reopen", "single", "summary.json"),
        {
            "schema": "pr15f-reopen-single-v1",
            "status": "QUALIFIED",
            "fresh_processes_total": verify.PR15F_REOPEN_PROCESSES,
            "launches_per_n": verify.PR15F_REOPEN_PER_N,
            "failures": [],
            "contention": {
                "block1_before": "clear",
                "block1_after": "clear",
                "block2_before": "clear",
                "block2_after": "clear",
            },
            "n": {
                "10000": {"sample_count": verify.PR15F_REOPEN_PER_N, "samples_ns": samples},
                "100000": {"sample_count": verify.PR15F_REOPEN_PER_N, "samples_ns": samples},
            },
        },
    )
    write_json(
        os.path.join(run_dir, "reopen", "perf", "summary.json"),
        {
            "schema": "pr15f-reopen-perf-v1",
            "status": "QUALIFIED",
            "captures": {
                "10000": {
                    "status": "CAPTURED",
                    "iterations": 128,
                    "perf_origin": "versioned",
                    "tool_evidence": {"lost_samples": 0, "sample_count": 1000},
                },
                "100000": {
                    "status": "CAPTURED",
                    "iterations": 64,
                    "perf_origin": "versioned",
                    "tool_evidence": {"lost_samples": 0, "sample_count": 1000},
                },
            },
        },
    )
    prepare = verify.read_json(os.path.join(prepared, "prepare.json"))
    for n in verify.PR15D_N:
        index_root = os.path.join(prepared, "indexes", f"n{n}")
        files = []
        for relative, _dirs, names in os.walk(index_root):
            for name in sorted(names):
                path = os.path.join(relative, name)
                with open(path, "rb") as handle:
                    payload = handle.read()
                files.append(
                    {
                        "path": os.path.relpath(path, index_root).replace(os.sep, "/"),
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
        files.sort(key=lambda entry: entry["path"])
        total = sum(entry["bytes"] for entry in files)
        state_entry = [entry for entry in files if entry["path"].startswith("index/state/")][0]
        inventory = {
            "schema": "pr15f-index-inventory-v1",
            "n": n,
            "read_only": True,
            "documents_verified": n,
            "file_count": len(files),
            "files": files,
            "total_file_bytes": total,
            "segment_file_bytes": total - state_entry["bytes"],
            "manifest_file_bytes": 0,
            "metadata_file_bytes": 0,
            "mutation_state_file_bytes": state_entry["bytes"],
            "segment_sections_plus_overhead": total - state_entry["bytes"],
            "reconciliation": {
                "bytes_reconciled": True,
                "segments_reconciled": True,
                "classified_file_bytes": total,
                "total_file_bytes": total,
                "segment_file_bytes": total - state_entry["bytes"],
                "segment_sections_plus_overhead": total - state_entry["bytes"],
            },
            "section_bytes": {"Stored": 10, "Postings": 5},
            "section_counts": {"Stored": 1, "Postings": 1},
            "bytes_before_sha256": "a" * 64,
            "bytes_after_sha256": "a" * 64,
            "content_sha256": prepare["indexes"][str(n)]["inventory"]["sha256"],
        }
        write_json(os.path.join(run_dir, "inventory", f"n{n}.json"), inventory)
    return run_dir


def build_mutation_run(root: str, prepared: str, pr15f_run: str, *, source=SOURCE):
    mutation = os.path.join(root, "target", "pr15i-0", "mutation-01")
    os.makedirs(mutation, exist_ok=True)
    observations = {}
    for n in verify.PR15D_N:
        inventory = verify.read_json(os.path.join(pr15f_run, "inventory", f"n{n}.json"))
        state_entry = [
            entry for entry in inventory["files"] if entry["path"].startswith("index/state/")
        ][0]
        components = {
            "state_header_bytes": 6,
            "row_key_prefix_bytes": 2,
            "row_key_bytes": 4,
            "row_revision_bytes": 8,
            "row_status_bytes": 1,
            "live_pointer_prefix_bytes": 2,
            "live_pointer_id_bytes": 3,
            "live_doc_id_bytes": 8,
            "replay_header_bytes": 4,
            "replay_token_prefix_bytes": 0,
            "replay_token_bytes": 0,
            "replay_fingerprint_bytes": 0,
            "replay_key_prefix_bytes": 0,
            "replay_key_bytes": 0,
            "replay_intent_bytes": 0,
            "replay_revision_bytes": 0,
            "batch_replay_opaque_bytes": 0,
        }
        payload = sum(components.values())
        file_bytes = state_entry["bytes"]
        breakdown = {
            "schema": "pr15i-0-mutation-breakdown-v1",
            "source_sha": source,
            "qualified": True,
            "active_state_key": state_entry["path"],
            "sidecar_sha256": state_entry["sha256"],
            "sidecar_file_bytes": file_bytes,
            "payload_bytes": payload,
            "container_overhead_bytes": file_bytes - payload,
            "payload_version": 1,
            "row_count": 1,
            "live_count": 1,
            "deleted_count": 0,
            "replay_count": 0,
            "batch_replay_detail": "NOT_APPLICABLE",
            "component_bytes": components,
        }
        write_json(os.path.join(mutation, f"n{n}.json"), breakdown)
        observations[str(n)] = {"active_state_entry": state_entry}
    write_json(
        os.path.join(mutation, "manifest.json"),
        {
            "schema": "pr15i-0-mutation-run-v1",
            "source_sha": source,
            "read_only": True,
            "n": observations,
        },
    )
    return mutation


def build_root(
    *,
    source=SOURCE,
    corpus_manifest=CORPUS_MANIFEST,
    lanes_overrides=None,
    query_status="CAPTURED",
) -> tuple[str, dict]:
    root = tempfile.mkdtemp(prefix="pr15i0-verify-")
    with open(os.path.join(root, "Cargo.toml"), "w", encoding="utf-8") as handle:
        handle.write("[workspace]\n")
    with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as handle:
        handle.write("target/\n")
    os.makedirs(os.path.join(root, "benchmarks", "pr15i_0"), exist_ok=True)
    with open(
        os.path.join(root, verify.PROTOCOL_REL), "wb"
    ) as handle:
        handle.write(canonical_json_bytes(verify.FROZEN_PROTOCOL))
    spec_dir = os.path.join(root, "benchmarks", "pr15d", "spec")
    os.makedirs(spec_dir, exist_ok=True)
    write_json(
        os.path.join(spec_dir, "pr15d_v1.json"),
        {"schema": "pr15d-spec-v1", "status": "FROZEN", "workload": "pr15d_v1"},
    )
    pr15d = build_pr15d_run(root, source=source, **(lanes_overrides or {}))
    if corpus_manifest != CORPUS_MANIFEST:
        run = verify.read_json(os.path.join(pr15d, "run.json"))
        run["corpus_manifest_sha256"] = corpus_manifest
        write_json(os.path.join(pr15d, "run.json"), run)
    prepared = build_prepared(root, source=source)
    pr15f = build_pr15f_run(root, prepared, source=source, query_status=query_status)
    mutation = build_mutation_run(root, prepared, pr15f, source=source)
    paths = {
        "root": root,
        "pr15d": pr15d,
        "prepared": prepared,
        "pr15f": pr15f,
        "mutation": mutation,
        "out": os.path.join(root, "target", "pr15i-0", "verification-01.json"),
    }
    return root, paths


class FakeGit:
    """Minimal deterministic stand-in for the git probes."""

    def __init__(self, head=SOURCE, dirty=False, diff_exit=0):
        self.head = head
        self.dirty = dirty
        self.diff_exit = diff_exit

    def __call__(self, root, *args):
        if args[:2] == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, self.head + "\n", "")
        if args[:2] == ("status", "--porcelain=v1"):
            return subprocess.CompletedProcess(
                args, 0, " M crates/x.rs\n" if self.dirty else "", ""
            )
        if args[:2] == ("diff", "--exit-code"):
            return subprocess.CompletedProcess(
                args, self.diff_exit, "diff --git a/crates b/crates\n" if self.diff_exit else "", ""
            )
        return subprocess.CompletedProcess(args, 0, "", "")


def fake_run_command(*_args, **_kwargs):
    command = _args[0] if _args else _kwargs.get("argv")
    text = json.dumps(command)
    if "validate.py" in text:
        out = command[command.index("--out") + 1]
        write_json(
            out,
            {
                "schema": "pr15d-validation-v1",
                "status": "QUALIFIED",
                "errors": [],
                "source_sha": SOURCE,
            },
        )
    return {"argv": list(command), "exit_code": 0, "stdout": "ok", "stderr": ""}


class VerifierTestCase(unittest.TestCase):
    def setUp(self):
        self.saved_git = verify.git
        self.saved_run = verify.run_command
        verify.git = FakeGit()
        verify.run_command = fake_run_command
        self.fixtures = []

    def tearDown(self):
        verify.git = self.saved_git
        verify.run_command = self.saved_run
        import shutil

        for root in self.fixtures:
            shutil.rmtree(root, ignore_errors=True)

    def make(self, **kwargs):
        root, paths = build_root(**kwargs)
        self.fixtures.append(root)
        return root, paths

    def run_verify(self, paths, source=SOURCE, out=None):
        out = out or paths["out"]
        argv = [
            "--root",
            paths["root"],
            "--source-sha",
            source,
            "--pr15d-run",
            paths["pr15d"],
            "--pr15f-run",
            paths["pr15f"],
            "--pr15f-prepared",
            paths["prepared"],
            "--mutation-run",
            paths["mutation"],
            "--out",
            out,
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            code = verify.verification_main(argv)
        payload = verify.read_json(out) if os.path.isfile(out) else None
        return code, payload

    def seal_all(self, paths, status="QUALIFIED"):
        for label in ("pr15d", "prepared", "pr15f", "mutation"):
            directory = paths[label]
            verify.seal_campaign(
                directory,
                SOURCE,
                status,
                {"protocol_sha256": sha_of_protocol(paths["root"])},
            )


def sha_of_protocol(root: str) -> str:
    return verify.sha256_file(os.path.join(root, verify.PROTOCOL_REL))


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ProtocolTests(unittest.TestCase):
    def test_accepts_frozen_protocol(self):
        root = tempfile.mkdtemp(prefix="pr15i0-proto-")
        try:
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_0"), exist_ok=True)
            with open(os.path.join(root, verify.PROTOCOL_REL), "wb") as handle:
                handle.write(canonical_json_bytes(verify.FROZEN_PROTOCOL))
            loaded = verify.load_protocol(root)
            self.assertEqual(loaded["value"], verify.FROZEN_PROTOCOL)
            self.assertEqual(len(loaded["sha256"]), 64)
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_rejects_drifted_lane_counts(self):
        root = tempfile.mkdtemp(prefix="pr15i0-proto-")
        try:
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_0"), exist_ok=True)
            drifted = json.loads(json.dumps(verify.FROZEN_PROTOCOL))
            drifted["quervant_profile"]["warm_query_lanes"] = 8
            with open(os.path.join(root, verify.PROTOCOL_REL), "wb") as handle:
                handle.write(canonical_json_bytes(drifted))
            with self.assertRaises(verify.VerificationError) as context:
                verify.load_protocol(root)
            self.assertEqual(context.exception.code, "X02_PROTOCOL")
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_rejects_synthetic_fixture_protocol(self):
        root = tempfile.mkdtemp(prefix="pr15i0-proto-")
        try:
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_0"), exist_ok=True)
            fixture = json.loads(json.dumps(verify.FROZEN_PROTOCOL))
            fixture["test_fixture"] = True
            with open(os.path.join(root, verify.PROTOCOL_REL), "wb") as handle:
                handle.write(canonical_json_bytes(fixture))
            with self.assertRaises(verify.VerificationError) as context:
                verify.load_protocol(root)
            self.assertEqual(context.exception.code, "X30_FIXTURE")
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_rejects_malformed_json(self):
        root = tempfile.mkdtemp(prefix="pr15i0-proto-")
        try:
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_0"), exist_ok=True)
            with open(os.path.join(root, verify.PROTOCOL_REL), "w", encoding="utf-8") as handle:
                handle.write("{not json")
            with self.assertRaises(verify.VerificationError) as context:
                verify.load_protocol(root)
            self.assertEqual(context.exception.code, "X02_PROTOCOL")
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# Path hygiene
# ---------------------------------------------------------------------------


class PathTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pr15i0-path-")
        os.makedirs(os.path.join(self.root, "target", "pr15i-0"), exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def test_rejects_relative_path(self):
        with self.assertRaises(verify.VerificationError) as context:
            verify.require_plain_path(self.root, "target/pr15i-0/x", "label")
        self.assertEqual(context.exception.code, "X19_PATH")

    def test_rejects_path_outside_allowed_roots(self):
        os.makedirs(os.path.join(self.root, "docs"))
        with self.assertRaises(verify.VerificationError) as context:
            verify.require_plain_path(self.root, os.path.join(self.root, "docs"), "label")
        self.assertEqual(context.exception.code, "X19_PATH")

    def test_rejects_symlink(self):
        real = os.path.join(self.root, "target", "pr15i-0", "real")
        os.makedirs(real)
        link = os.path.join(self.root, "target", "pr15i-0", "link")
        os.symlink(real, link)
        with self.assertRaises(verify.VerificationError) as context:
            verify.require_plain_path(self.root, link, "label")
        self.assertEqual(context.exception.code, "X19_PATH")

    def test_accepts_plain_path_in_allowed_root(self):
        directory = os.path.join(self.root, "target", "pr15i-0", "ok")
        os.makedirs(directory)
        self.assertEqual(
            verify.require_plain_path(self.root, directory, "label"),
            os.path.realpath(directory),
        )

    def test_require_regular_files_rejects_symlink_in_tree(self):
        directory = os.path.join(self.root, "target", "pr15i-0", "tree")
        os.makedirs(directory)
        target = os.path.join(directory, "file")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("x")
        os.symlink(target, os.path.join(directory, "link"))
        with self.assertRaises(verify.VerificationError):
            verify.require_regular_files(directory)


# ---------------------------------------------------------------------------
# Seals
# ---------------------------------------------------------------------------


class SealTests(VerifierTestCase):
    def test_seal_round_trip_and_one_byte_tamper(self):
        _root, paths = self.make()
        result = verify.seal_campaign(
            paths["mutation"], SOURCE, "QUALIFIED", {"protocol_sha256": "a" * 64}
        )
        self.assertTrue(os.path.isfile(result["path"]))
        gates = verify.Gates()
        seal = verify.verify_seal(
            paths["mutation"], SOURCE, "a" * 64, gates, "mutation"
        )
        self.assertIsNotNone(seal)
        self.assertNotEqual(gates.get("I0-P09")["status"], "FAIL")

        target = os.path.join(paths["mutation"], "n10000.json")
        with open(target, "r+b") as handle:
            first = handle.read(1)
            handle.seek(0)
            handle.write(bytes([first[0] ^ 0x01]))
        gates = verify.Gates()
        self.assertIsNone(verify.verify_seal(paths["mutation"], SOURCE, "a" * 64, gates, "mutation"))
        self.assertEqual(gates.get("I0-P09")["status"], "FAIL")

    def test_seal_rejects_extra_and_missing_files(self):
        _root, paths = self.make()
        verify.seal_campaign(
            paths["mutation"], SOURCE, "PARTIAL", {"protocol_sha256": "a" * 64}
        )
        with open(os.path.join(paths["mutation"], "extra.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        gates = verify.Gates()
        self.assertIsNone(verify.verify_seal(paths["mutation"], SOURCE, "a" * 64, gates, "mutation"))
        self.assertEqual(gates.get("I0-P09")["status"], "FAIL")

    def test_seal_rejects_bad_schema_and_source(self):
        _root, paths = self.make()
        verify.seal_campaign(
            paths["mutation"], SOURCE, "PARTIAL", {"protocol_sha256": "a" * 64}
        )
        seal_path = os.path.join(paths["mutation"], "seal.json")
        seal = verify.read_json(seal_path)
        seal["schema"] = "pr15i-0-seal-v0"
        write_json(seal_path, seal)
        gates = verify.Gates()
        self.assertIsNone(verify.verify_seal(paths["mutation"], SOURCE, "a" * 64, gates, "m"))
        self.assertEqual(gates.get("I0-P09")["status"], "FAIL")

        seal["schema"] = verify.SCHEMA_SEAL
        seal["source_sha"] = OTHER_SOURCE
        write_json(seal_path, seal)
        gates = verify.Gates()
        self.assertIsNone(verify.verify_seal(paths["mutation"], SOURCE, "a" * 64, gates, "m"))
        self.assertEqual(gates.get("I0-P09")["status"], "FAIL")

    def test_seal_is_exclusive(self):
        _root, paths = self.make()
        verify.seal_campaign(
            paths["mutation"], SOURCE, "PARTIAL", {"protocol_sha256": "a" * 64}
        )
        with self.assertRaises(FileExistsError):
            verify.seal_campaign(
                paths["mutation"], SOURCE, "PARTIAL", {"protocol_sha256": "a" * 64}
            )


# ---------------------------------------------------------------------------
# End-to-end driver
# ---------------------------------------------------------------------------


class DriverTests(VerifierTestCase):
    def test_qualified_campaign(self):
        _root, paths = self.make()
        self.seal_all(paths)
        code, payload = self.run_verify(paths)
        statuses = {gate: entry["status"] for gate, entry in payload["gates"].items()}
        self.assertEqual(statuses["I0-P00"], "PASS")
        self.assertEqual(statuses["I0-P01"], "PASS")
        self.assertEqual(statuses["I0-P02"], "PASS")
        self.assertEqual(statuses["I0-P03"], "PASS")
        self.assertEqual(statuses["I0-P05"], "PASS")
        self.assertEqual(statuses["I0-P06"], "PASS")
        self.assertEqual(statuses["I0-P07"], "PASS")
        self.assertEqual(statuses["I0-P08"], "PASS")
        self.assertEqual(statuses["I0-P09"], "PASS")
        self.assertEqual(statuses["I0-P11"], "BLOCKED")
        self.assertEqual(statuses["I0-P12"], "NOT_MEASURED")
        self.assertEqual(code, 1)
        self.assertEqual(payload["overall_status"], "15I0_PARTIAL_EVIDENCE")

    def test_output_is_append_only(self):
        _root, paths = self.make()
        self.seal_all(paths)
        code, _payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        digest_before = verify.sha256_file(paths["out"])
        second = self.run_verify(paths)
        self.assertEqual(second[0], 2)
        self.assertEqual(verify.sha256_file(paths["out"]), digest_before)

    def test_source_sha_mismatch_fails_provenance(self):
        _root, paths = self.make()
        self.seal_all(paths)
        code, payload = self.run_verify(paths, source=OTHER_SOURCE)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P09"]["status"], "FAIL")
        self.assertEqual(payload["overall_status"], "15I0_NOT_QUALIFIED")

    def test_malformed_source_sha_fails_source_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        code, payload = self.run_verify(paths, source="ABCDEF")
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P00"]["status"], "FAIL")
        self.assertEqual(payload["overall_status"], "15I0_BLOCKED_SOURCE")

    def test_dirty_tree_fails_source_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        verify.git = FakeGit(dirty=True)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P00"]["status"], "FAIL")

    def test_protected_path_change_fails_source_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        verify.git = FakeGit(diff_exit=1)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P00"]["status"], "FAIL")

    def test_changed_corpus_digest_fails_input_gate(self):
        _root, paths = self.make(corpus_manifest="9" * 64)
        self.seal_all(paths)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P01"]["status"], "FAIL")

    def test_missing_query_lane_blocks_cpu_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        campaign_path = os.path.join(paths["pr15f"], "query-campaign.json")
        campaign = verify.read_json(campaign_path)
        campaign["lanes"] = campaign["lanes"][:-1]
        write_json(campaign_path, campaign)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P05"]["status"], "FAIL")

    def test_blocked_query_lanes_report_blocked(self):
        _root, paths = self.make(query_status="BLOCKED")
        self.seal_all(paths, status="PARTIAL")
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P05"]["status"], "BLOCKED")

    def test_wrong_engine_fails_pr15d_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        path = os.path.join(paths["pr15d"], "trials", "trial-2", "tantivy.json")
        manifest = verify.read_json(path)
        manifest["engine"] = "quervant"
        write_json(path, manifest)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P03"]["status"], "FAIL")

    def test_oracle_mismatch_fails_pr15d_gate(self):
        _root, paths = self.make(lanes_overrides={"oracle_ok": False})
        self.seal_all(paths)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P03"]["status"], "FAIL")

    def test_false_clear_probe_fails_pr15d_gate(self):
        _root, paths = self.make(lanes_overrides={"contention": "busy"})
        self.seal_all(paths)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P03"]["status"], "FAIL")

    def test_partial_trial_count_fails_pr15d_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        run_path = os.path.join(paths["pr15d"], "run.json")
        run = verify.read_json(run_path)
        run["trials"] = 2
        write_json(run_path, run)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P03"]["status"], "FAIL")

    def test_invalid_numeric_type_fails_pr15d_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        path = os.path.join(paths["pr15d"], "trials", "trial-1", "quervant.json")
        manifest = verify.read_json(path)
        manifest["build"]["10000"]["index_bytes"] = "10000"
        write_json(path, manifest)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P03"]["status"], "FAIL")

    def test_sidecar_accounting_off_by_one_fails_state_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        path = os.path.join(paths["mutation"], "n100000.json")
        breakdown = verify.read_json(path)
        breakdown["component_bytes"]["row_key_bytes"] += 1
        write_json(path, breakdown)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P08"]["status"], "FAIL")

    def test_sidecar_with_invented_v2_batch_fails_state_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        path = os.path.join(paths["mutation"], "n10000.json")
        breakdown = verify.read_json(path)
        breakdown["payload_version"] = 1
        breakdown["batch_replay_detail"] = "SEMANTIC_BATCH_DETAIL_NOT_VERIFIED"
        write_json(path, breakdown)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P08"]["status"], "FAIL")

    def test_genuine_unknown_attribution_is_preserved(self):
        _root, paths = self.make()
        self.seal_all(paths)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        quality = payload["gates"]["I0-P05"]["evidence"]
        self.assertTrue(any(entry["unknown_exclusive_percent"] == 60.0 for entry in quality))

    def test_inclusive_share_is_never_added_to_exclusive(self):
        _root, paths = self.make()
        self.seal_all(paths)
        _code, payload = self.run_verify(paths)
        quality = payload["gates"]["I0-P05"]["evidence"]
        for entry in quality:
            self.assertLessEqual(entry["exclusive_total_percent"], 100.02)

    def test_missing_inventory_blocks_layout_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        os.remove(os.path.join(paths["pr15f"], "inventory", "n10000.json"))
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P07"]["status"], "BLOCKED")

    def test_inventory_mutation_detection_fails_layout_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        path = os.path.join(paths["pr15f"], "inventory", "n10000.json")
        inventory = verify.read_json(path)
        inventory["bytes_after_sha256"] = "b" * 64
        write_json(path, inventory)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P07"]["status"], "FAIL")

    def test_reopen_loop_iteration_mismatch_blocks_reopen_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        path = os.path.join(paths["pr15f"], "reopen", "perf", "summary.json")
        summary = verify.read_json(path)
        summary["captures"]["100000"]["iterations"] = 32
        write_json(path, summary)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P06"]["status"], "BLOCKED")

    def test_reopen_loop_lost_samples_blocks_reopen_gate(self):
        _root, paths = self.make()
        self.seal_all(paths)
        path = os.path.join(paths["pr15f"], "reopen", "perf", "summary.json")
        summary = verify.read_json(path)
        summary["captures"]["10000"]["tool_evidence"]["lost_samples"] = 12
        write_json(path, summary)
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P06"]["status"], "BLOCKED")

    def test_allocation_capture_is_recognised_in_both_shapes(self):
        _root, paths = self.make()
        self.seal_all(paths)
        os.makedirs(os.path.join(paths["pr15f"], "allocation"), exist_ok=True)
        write_json(
            os.path.join(paths["pr15f"], "allocation", "summary.json"),
            {
                "schema": "pr15f-allocation-campaign-v1",
                "status": "QUALIFIED",
                "captures": {
                    "n100000/rare": {"capture_id": "a", "status": "CAPTURED"},
                    "n100000/common": {"capture_id": "b", "status": "CAPTURED"},
                },
            },
        )
        code, payload = self.run_verify(paths)
        self.assertEqual(code, 1)
        self.assertEqual(payload["gates"]["I0-P12"]["status"], "PASS")

    def test_missing_allocation_is_not_measured(self):
        _root, paths = self.make()
        self.seal_all(paths)
        _code, payload = self.run_verify(paths)
        self.assertEqual(payload["gates"]["I0-P12"]["status"], "NOT_MEASURED")

    def test_privacy_gate_blocks_before_reports_exist(self):
        _root, paths = self.make()
        self.seal_all(paths)
        _code, payload = self.run_verify(paths)
        self.assertEqual(payload["gates"]["I0-P10"]["status"], "BLOCKED")

    def test_reverification_is_read_only_and_repeatable(self):
        root, paths = self.make()
        self.seal_all(paths)
        before = {}
        for label in ("pr15d", "prepared", "pr15f", "mutation"):
            before[label] = verify.sha256_file(os.path.join(paths[label], "seal.json"))
        out2 = os.path.join(root, "target", "pr15i-0", "verification-02.json")
        self.run_verify(paths)
        self.run_verify(paths, out=out2)
        after = {}
        for label in ("pr15d", "prepared", "pr15f", "mutation"):
            after[label] = verify.sha256_file(os.path.join(paths[label], "seal.json"))
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# QA record gate
# ---------------------------------------------------------------------------


class QaGateTests(unittest.TestCase):
    def _gates(self):
        return verify.Gates()

    def _record(self, root, **overrides):
        path = os.path.join(root, "target", "pr15i-0", "qa")
        os.makedirs(path, exist_ok=True)
        record = {
            "schema": verify.SCHEMA_QA,
            "commands": [
                {"id": "fmt", "required": True, "status": "PASS"},
                {"id": "test", "required": True, "status": "PASS"},
            ],
            "coverage_percent": 86.5,
        }
        record.update(overrides)
        write_json(os.path.join(path, "workspace-qa.json"), record)

    def test_qa_gate_passes_with_coverage(self):
        root = tempfile.mkdtemp(prefix="pr15i0-qa-")
        try:
            self._record(root)
            gates = self._gates()
            verify.check_qa(gates, root)
            self.assertEqual(gates.get("I0-P11")["status"], "PASS")
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_qa_gate_fails_below_floor(self):
        root = tempfile.mkdtemp(prefix="pr15i0-qa-")
        try:
            self._record(root, coverage_percent=84.99)
            gates = self._gates()
            verify.check_qa(gates, root)
            self.assertEqual(gates.get("I0-P11")["status"], "FAIL")
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_qa_gate_fails_on_required_failure(self):
        root = tempfile.mkdtemp(prefix="pr15i0-qa-")
        try:
            self._record(
                root,
                commands=[{"id": "test", "required": True, "status": "FAIL"}],
            )
            gates = self._gates()
            verify.check_qa(gates, root)
            self.assertEqual(gates.get("I0-P11")["status"], "FAIL")
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_qa_gate_blocked_without_record(self):
        root = tempfile.mkdtemp(prefix="pr15i0-qa-")
        try:
            gates = self._gates()
            verify.check_qa(gates, root)
            self.assertEqual(gates.get("I0-P11")["status"], "BLOCKED")
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
