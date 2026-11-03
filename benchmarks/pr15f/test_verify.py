#!/usr/bin/env python3
"""PR 15F verification/publication tests (T13, T14, T16 subset)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import profile_queries as pq  # noqa: E402
import run as campaign  # noqa: E402
import verify as verification  # noqa: E402

HISTORIC_REPORT_SHA = "384c02904cdd9fefecc2050472553b392962e6aa11f254adfa3a321a7c381096"


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


def _preflight_fixture(root: str, source_sha: str = "a" * 40) -> dict:
    probe = os.path.join(root, "probe.bin")
    with open(probe, "wb") as handle:
        handle.write(b"probe")
    preflight = {
        "source_sha": source_sha,
        "origin_main_sha": "d5f3c0563f352123ce4136d6dbd45a6091cc7aeb",
        "probe": {
            "binary_rel": "probe.bin",
            "binary_sha256": pq.sha256_file(probe),
            "source_sha256": "c" * 64,
            "lock_sha256": "e" * 64,
        },
        "protected_tree": {"tree_sha256": "f" * 64},
        "anchors": {
            "warm_100k_quervant_k100": {"absent": {"median_ns": 1}},
            "index_bytes_100k": 1,
            "build_phase_reopen_ns_100k": 1,
        },
        "source_lock": {},
        "tool_module_lock": {},
        "prepared_sha256": "b" * 64,
        "authorization_basis": pq.AUTHORIZATION_BASIS,
        "index_inventory_sha256": {},
    }
    preflight["preflight_digest"] = pq.sha256_bytes(
        pq.canonical_json_bytes(preflight)
    )
    pq.write_json(os.path.join(root, "preflight.json"), preflight)
    return preflight


def _prepared_fixture(root: str) -> str:
    prepared = os.path.join(root, "prepared")
    os.makedirs(prepared, exist_ok=True)
    pq.write_json(
        os.path.join(prepared, "prepare.json"),
        {
            "workload": "pr15d_v1",
            "regime": "warm",
            "corpus": {"manifest_sha256": "1" * 64},
            "build": {"binary_sha256": "2" * 64},
        },
    )
    return prepared


def _evaluate_with_fakes(root: str):
    prepared = _prepared_fixture(root)
    _preflight_fixture(root)
    with open(os.path.join(root, "p0-execution.md"), "w", encoding="utf-8") as handle:
        handle.write("external QA is reported here as PASS\n")
    captured = {}

    def fake_build_summary(*args, **kwargs):
        captured["gates"] = args[10]
        return {"status": "STUB", "gates": args[10]}

    with (
        mock.patch.object(
            verification,
            "verify_source",
            return_value={"measured_source_sha": "a" * 40, "head_sha": "a" * 40, "changed": []},
        ),
        mock.patch.object(
            verification,
            "verify_query",
            return_value={
                "status": "QUALIFIED",
                "required": 9,
                "captured": 9,
                "lanes": [],
                "unexpected_captures": [],
            },
        ),
        mock.patch.object(
            verification,
            "verify_reopen_single",
            return_value={"status": "QUALIFIED", "fresh_processes_total": 42, "n": {}},
        ),
        mock.patch.object(
            verification,
            "verify_reopen_perf",
            return_value={"status": "QUALIFIED", "captures": {}},
        ),
        mock.patch.object(
            verification,
            "verify_inventory",
            return_value={"status": "QUALIFIED", "indexes": {}},
        ),
        mock.patch.object(
            verification,
            "verify_allocation",
            return_value={"status": "QUALIFIED", "captures": {}, "code": None, "detail": None},
        ),
        mock.patch.object(verification, "build_summary", side_effect=fake_build_summary),
    ):
        verification.evaluate(prepared, root, None)
    return captured["gates"]


class ExternalQaProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pr15f-evaluate-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_f15f_01_evaluate_does_not_attest_external_qa(self):
        gates = _evaluate_with_fakes(self.root)
        self.assertEqual(gates["C10"]["status"], verification.NOT_MEASURED)
        self.assertEqual(gates["C11"]["status"], verification.NOT_MEASURED)
        self.assertIn("not executed or independently attested", gates["C10"]["detail"])
        self.assertIn("not executed or independently attested", gates["C11"]["detail"])
        self.assertNotEqual(gates["C10"]["status"], verification.PASS)
        self.assertNotEqual(gates["C11"]["status"], verification.PASS)
        # A documented-QA file in the run directory is not read as evidence.
        self.assertTrue(os.path.isfile(os.path.join(self.root, "p0-execution.md")))

    def test_f15f_02_external_gates_and_sanitizer_semantics_are_unchanged(self):
        gates = _evaluate_with_fakes(self.root)
        self.assertEqual(gates["C09"]["status"], verification.PASS)
        self.assertEqual(gates["C12"]["status"], verification.BLOCKED)
        self.assertEqual(gates["C14"]["status"], verification.BLOCKED)
        self.assertEqual(gates["C08"]["status"], verification.NOT_MEASURED)

    def test_profiling_readiness_is_independent_of_external_qa(self):
        prepared = _prepared_fixture(self.root)
        preflight = _preflight_fixture(self.root)
        gates = {
            **{name: {"status": verification.PASS, "detail": ""} for name in (
                "C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08"
            )},
            "C10": {
                "status": verification.NOT_MEASURED,
                "detail": "external test execution not attested",
            },
            "C11": {
                "status": verification.NOT_MEASURED,
                "detail": "external repository QA not attested",
            },
            "C12": {"status": verification.BLOCKED, "detail": "hosted CI not run"},
            "C14": {"status": verification.BLOCKED, "detail": "reviewer pending"},
        }
        summary = verification.build_summary(
            prepared,
            self.root,
            preflight,
            {"measured_source_sha": "a" * 40, "head_sha": "a" * 40},
            {"status": "QUALIFIED", "required": 9, "captured": 9, "lanes": [], "unexpected_captures": []},
            {"status": "QUALIFIED", "fresh_processes_total": 42, "n": {}},
            {"status": "QUALIFIED", "captures": {}},
            {"status": "QUALIFIED", "indexes": {}},
            {"status": "QUALIFIED", "captures": {}},
            None,
            gates,
            [],
        )
        # Profiling readiness is not merge approval: C12/C14 remain blocked.
        self.assertEqual(summary["status"], verification.STATUS_QUALIFIED)
        self.assertEqual(summary["gates"]["C12"]["status"], verification.BLOCKED)
        self.assertEqual(summary["gates"]["C14"]["status"], verification.BLOCKED)


class SourceBoundaryTests(unittest.TestCase):
    def _verify(self, changed: str):
        def fake_git(*args):
            if args and args[0] == "rev-parse":
                return "a" * 40
            if args and args[0] == "diff":
                return changed
            return None

        preflight = {
            "source_sha": "a" * 40,
            "protected_tree": {"tree_sha256": "f" * 64},
        }
        gates = {}
        with (
            mock.patch.object(verification, "_git", side_effect=fake_git),
            mock.patch.object(
                campaign,
                "protected_tree_hash",
                return_value={"tree_sha256": "f" * 64},
            ),
            mock.patch.object(pq, "source_lock", return_value={}),
        ):
            verification.verify_source("/unused", preflight, gates)
        return gates

    def test_f15f_04_verifier_edit_breaks_historic_source_binding(self):
        gates = self._verify("benchmarks/pr15f/verify.py\n")
        self.assertEqual(gates["C01"]["status"], verification.FAILED)
        gates = self._verify("benchmarks/pr15f/test_verify.py\n")
        self.assertEqual(gates["C01"]["status"], verification.FAILED)

    def test_f15f_04_docs_only_delta_preserves_source_binding(self):
        gates = self._verify("docs/pr-artifacts/pr-15f/p0-review-fixup.md\n")
        self.assertEqual(gates["C01"]["status"], verification.PASS)
        self.assertEqual(gates["C02"]["status"], verification.PASS)


class HistoricalImmutabilityTests(unittest.TestCase):
    def test_f15f_05_published_report_remains_byte_identical(self):
        self.assertEqual(pq.sha256_file(verification.PUBLISH_PATH), HISTORIC_REPORT_SHA)
        self.assertEqual(
            os.path.basename(verification.PUBLISH_PATH), "p0-profile-summary.json"
        )


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
