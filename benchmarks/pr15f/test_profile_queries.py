#!/usr/bin/env python3
"""PR 15F profiler/CLI adversarial tests (T01-T07, T13 subset)."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import profile_queries as pq  # noqa: E402

ERRORS = (pq.Pr15fError, pq.eprofile.Pr15eError)


class FixedMatrixTests(unittest.TestCase):
    def test_exactly_nine_perf_lanes_and_two_optional_allocation_lanes(self):
        lanes = pq.perf_lane_descriptors()
        self.assertEqual(len(lanes), 9)
        self.assertEqual(
            [entry["capture_id"] for entry in lanes],
            [
                "pr15f/n10000/absent/k100/perf",
                "pr15f/n10000/rare/k100/perf",
                "pr15f/n10000/medium/k100/perf",
                "pr15f/n10000/common/k100/perf",
                "pr15f/n100000/absent/k100/perf",
                "pr15f/n100000/rare/k100/perf",
                "pr15f/n100000/medium/k100/perf",
                "pr15f/n100000/common/k100/perf",
                "pr15f/n100000/common/k10/perf",
            ],
        )
        allocation = pq.allocation_lane_descriptors()
        self.assertEqual(len(allocation), 2)
        self.assertEqual(
            [entry["capture_id"] for entry in allocation],
            [
                "pr15f/n100000/rare/k100/heaptrack",
                "pr15f/n100000/common/k100/heaptrack",
            ],
        )

    def test_duplicate_unexpected_and_wrong_durations_are_rejected(self):
        for arguments in (
            (10000, "absent", 100, "perf", 30),
            (100000, "common", 10, "perf", 30),
            (100000, "common", 100, "perf", 59),
            (10000, "common", 10, "perf", 20),
            (100000, "absent", 100, "heaptrack", 30),
            (99999, "absent", 100, "perf", 20),
            (10000, "absent", 100, "perf", 20.0),
        ):
            with self.assertRaises(ERRORS, msg=str(arguments)):
                pq.lane_descriptor(*arguments)
        with self.assertRaises(ERRORS):
            pq.lane_descriptor(10000, "absent", 100, "valgrind", 20)

    def test_legacy_attestation_flags_are_rejected(self):
        for argv in (
            ["--attestation", "attestation.json"],
            ["--accepted-attestation", "x"],
            ["--allow-contended"],
        ):
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stderr(io.StringIO()):
                    pq.main(argv)


class PathConfinementTests(unittest.TestCase):
    def setUp(self):
        os.makedirs(pq.PR15F_TARGET_ROOT, exist_ok=True)
        self.root = tempfile.mkdtemp(prefix="_test-paths-", dir=pq.PR15F_TARGET_ROOT)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_relative_and_parent_traversal_are_rejected(self):
        with self.assertRaises(ERRORS):
            pq.resolve_capture_dir("run-01/queries/x")
        with self.assertRaises(ERRORS):
            pq.resolve_capture_dir(
                os.path.join(self.root, "..", "escape", "n1", "absent", "k100", "perf")
            )

    def test_capture_must_live_under_queries_or_allocation(self):
        candidate = os.path.join(self.root, "n10000", "absent", "k100", "perf")
        with self.assertRaises(ERRORS):
            pq.resolve_capture_dir(candidate)

    def test_existing_capture_directory_is_never_reused(self):
        candidate = os.path.join(
            self.root, "queries", "n10000", "absent", "k100", "perf"
        )
        os.makedirs(candidate)
        with self.assertRaises(ERRORS) as raised:
            pq.resolve_capture_dir(candidate)
        self.assertEqual(raised.exception.code, "X28_DESTINATION_EXISTS")


class SamplingAndEvidenceTests(unittest.TestCase):
    def test_sample_floor_lost_samples_and_symbols_fail_closed(self):
        good = {
            "sample_count": 1000,
            "lost_samples": 0,
            "symbolization": {"quervant_mentions": 1},
        }
        pq.validate_perf_evidence(good)
        for mutation in (
            {"sample_count": 999},
            {"sample_count": 0},
            {"sample_count": -1},
            {"sample_count": 1001, "lost_samples": 1},
            {"lost_samples": -1},
            {"symbolization": {"quervant_mentions": 0}},
            {"sample_count": "1000"},
        ):
            broken = {**good, **mutation}
            with self.assertRaises(ERRORS, msg=str(mutation)):
                pq.validate_perf_evidence(broken)

    def test_missing_idle_confirmation_blocks_before_any_work(self):
        args = argparse.Namespace(
            prepared_run="/nonexistent",
            out="/nonexistent",
            n=10000,
            class_name="absent",
            k=100,
            tool="perf",
            seconds=20,
            idle_confirmed=False,
        )
        with self.assertRaises(ERRORS) as raised:
            pq.capture(args)
        self.assertEqual(raised.exception.code, "BLOCKED_AUTHORIZATION")

    def test_source_lock_and_tool_module_lock_recompute(self):
        lock = pq.source_lock()
        self.assertEqual(len(lock), len(pq.FROZEN_SOURCE_SHA256))
        for name, entry in lock.items():
            self.assertEqual(entry["sha256"], entry["expected"], name)
        modules = pq.tool_module_lock()
        self.assertIn("profile_queries", modules)
        self.assertIn("reopen_probe_source", modules)


class _Sink:
    def __init__(self):
        self.buffer = b""
        self.closed = False

    def write(self, data):
        self.buffer += data

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _Reader:
    def __init__(self, fd):
        self.fd = fd
        self.closed = False

    def fileno(self):
        return self.fd

    def close(self):
        if not self.closed:
            os.close(self.fd)
            self.closed = True


class _FakeProcess:
    def __init__(self, payload: bytes):
        read_fd, write_fd = os.pipe()
        os.write(write_fd, payload)
        os.close(write_fd)
        self.stdout = _Reader(read_fd)
        self.stdin = _Sink()


def _transport(payload: bytes):
    process = _FakeProcess(payload)
    return pq.eprofile.ProfiledTransport(process, label="test"), process


class JsonlAndOracleTests(unittest.TestCase):
    descriptor = {
        "lane_id": "pr15f/n10000/absent/k100",
        "field": "key",
        "term": "never",
        "k": 100,
    }
    expected = {"total_hits": 0, "doc_ids": []}

    def test_valid_reply_is_relayed_and_oracle_checked(self):
        response = {
            "schema": "pr15d-adapter-v1",
            "engine": "quervant",
            "request_id": "r0",
            "status": "ok",
            "engine_ns": 1234,
            "total_hits": 0,
            "doc_ids": [],
        }
        transport, _ = _transport((json.dumps(response) + "\n").encode())
        try:
            reply = transport.request({"request_id": "r0"})
            pq.eprofile.validate_response_against_oracle(
                reply, self.descriptor, self.expected
            )
        finally:
            transport.close()

    def test_wrong_hits_total_hits_and_corrupt_json_are_hard_stops(self):
        for payload, code in (
            (
                {
                    "schema": "pr15d-adapter-v1",
                    "engine": "quervant",
                    "request_id": "r0",
                    "status": "ok",
                    "engine_ns": 1,
                    "total_hits": 1,
                    "doc_ids": [],
                },
                "X23_ORACLE",
            ),
            (
                {
                    "schema": "pr15d-adapter-v1",
                    "engine": "quervant",
                    "request_id": "r0",
                    "status": "ok",
                    "engine_ns": 1,
                    "total_hits": 0,
                    "doc_ids": ["d00000001"],
                },
                "X23_ORACLE",
            ),
        ):
            with self.assertRaises(ERRORS) as raised:
                pq.eprofile.validate_response_against_oracle(
                    payload, self.descriptor, self.expected
                )
            self.assertEqual(raised.exception.code, code)

        transport, _ = _transport(b"not json\n")
        try:
            with self.assertRaises(ERRORS) as raised:
                transport.request({"request_id": "r0"})
            self.assertEqual(raised.exception.code, "X22_PROFILER_NOT_RELAYING")
        finally:
            transport.close()

    def test_wrong_engine_schema_and_error_status_are_rejected(self):
        for payload in (
            {
                "schema": "pr15d-adapter-v1",
                "engine": "tantivy",
                "status": "ok",
                "engine_ns": 1,
                "total_hits": 0,
                "doc_ids": [],
            },
            {
                "schema": "other",
                "engine": "quervant",
                "status": "ok",
                "engine_ns": 1,
                "total_hits": 0,
                "doc_ids": [],
            },
            {
                "schema": "pr15d-adapter-v1",
                "engine": "quervant",
                "status": "error",
                "error": {"kind": "search"},
            },
        ):
            transport, _ = _transport((json.dumps(payload) + "\n").encode())
            try:
                with self.assertRaises(ERRORS):
                    transport.request({"request_id": "r0"})
            finally:
                transport.close()

    def test_extra_stdout_line_is_a_protocol_failure(self):
        payload = {
            "schema": "pr15d-adapter-v1",
            "engine": "quervant",
            "status": "ok",
            "engine_ns": 1,
            "total_hits": 0,
            "doc_ids": [],
        }
        transport, _ = _transport((json.dumps(payload) + "\n" + "extra\n").encode())
        try:
            transport.request({"request_id": "r0"})
            with self.assertRaises(ERRORS):
                transport.request({"request_id": "r1"})
        finally:
            transport.close()


class ContentionTests(unittest.TestCase):
    def test_non_clear_probe_blocks_the_capture(self):
        # The capture driver records the failure and writes failure.json; the
        # status is BLOCKED, never a diagnostic acceptance.
        error = pq.blocked("X18_CONTENTION", "state=blocked")
        self.assertEqual(error.status, "BLOCKED")
        self.assertEqual(pq.EXIT_BY_STATUS[error.status], pq.EXIT_BLOCKED)


if __name__ == "__main__":
    unittest.main()
