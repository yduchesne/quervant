#!/usr/bin/env python3
"""PR 15F verification/publication tests (T13, T14, T16 subset)."""

from __future__ import annotations

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
import run as campaign  # noqa: E402
import verify as verification  # noqa: E402


def clean_summary() -> dict:
    return {
        "schema": verification.SCHEMA_SUMMARY,
        "status": verification.STATUS_QUALIFIED_NO_ALLOC,
        "measured_source_sha": "0" * 40,
        "campaigns": {"query": "QUALIFIED"},
        "non_additivity_warning": "inclusive is never summed",
        "privacy": {"sanitized": True},
    }


class SanitizerTests(unittest.TestCase):
    def test_clean_summary_publishes(self):
        text = verification.sanitize(clean_summary())
        self.assertIn("pr15f-p0-summary-v1", text)
        self.assertNotIn("adapter_pid", text)

    def test_absolute_paths_hostnames_and_tokens_are_refused(self):
        for mutation in (
            {"detail": "/home/someone/quervant/target/pr15f/run-01"},
            {"detail": "C:\\\\Users\\\\someone\\\\quervant"},
            {"detail": "pr15e-attestation-v1"},
            {"detail": "operator_statement"},
            {"detail": "adapter_pid"},
            {"detail": "perf.data"},
            {"detail": "profiler-stderr.txt"},
        ):
            summary = {**clean_summary(), **mutation}
            with self.assertRaises(verification.VerificationError):
                verification.sanitize(summary)

    def test_current_hostname_and_username_are_refused(self):
        import getpass
        import socket

        for value in (socket.gethostname(), getpass.getuser()):
            if not value or len(value) < 4:
                continue
            summary = {**clean_summary(), "leak": value}
            with self.assertRaises(verification.VerificationError):
                verification.sanitize(summary)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pr15f-publish-")
        self.path = os.path.join(self.root, "report.json")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_identical_report_is_idempotent_and_different_report_is_refused(self):
        text = verification.sanitize(clean_summary())
        first = verification.publish(text, self.path)
        second = verification.publish(text, self.path)
        self.assertTrue(first["written"])
        self.assertFalse(second["written"])
        with self.assertRaises(verification.VerificationError):
            verification.publish(text + " ", self.path)


class SourceGateTests(unittest.TestCase):
    def setUp(self):
        self.head = campaign._git("rev-parse", "HEAD")
        self.assertTrue(self.head)
        self.preflight = {
            "source_sha": self.head,
            "protected_tree": campaign.protected_tree_hash("HEAD"),
        }

    def test_matching_source_and_protected_tree_pass(self):
        gates = {}
        source = verification.verify_source("/unused", self.preflight, gates)
        self.assertEqual(gates["C01"]["status"], verification.PASS)
        self.assertEqual(gates["C02"]["status"], verification.PASS)
        self.assertEqual(source["measured_source_sha"], self.head)

    def test_changed_protected_tree_is_denied(self):
        preflight = {**self.preflight, "protected_tree": {"tree_sha256": "deadbeef"}}
        gates = {}
        verification.verify_source("/unused", preflight, gates)
        self.assertEqual(gates["C02"]["status"], verification.FAILED)

    def test_unknown_measured_source_is_denied(self):
        preflight = {**self.preflight, "source_sha": "f" * 40}
        with self.assertRaises(verification.VerificationError):
            verification.verify_source("/unused", preflight, {})


class HistoricalAnchorTests(unittest.TestCase):
    def test_published_anchors_are_reused_verbatim_and_not_thresholds(self):
        anchors = campaign.read_published_anchors()
        self.assertEqual(
            anchors["three_engine_source_sha"],
            "40ca10bae46f2d7df7804a0a129a99a4daf35ef0",
        )
        self.assertEqual(anchors["index_bytes_100k"], 30_965_025)
        self.assertEqual(set(anchors["warm_100k_quervant_k100"]), {"absent", "rare", "medium", "common"})
        for lane in anchors["warm_100k_quervant_k100"].values():
            self.assertIsInstance(lane["median_ns"], int)
        self.assertNotIn("speedup", json.dumps(anchors))

    def test_comparable_digest_is_order_independent(self):
        left = verification._comparable({"a": 1, "b": 2})
        right = verification._comparable({"b": 2, "a": 1})
        self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()
