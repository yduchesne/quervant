#!/usr/bin/env python3
"""Targeted controller/protocol/archive tests for PR 15I-D3-A."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name):
    path = os.path.join(ROOT, "benchmarks", "pr15i_d3a", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"d3a_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load("run")
verify = _load("verify")


class ProtocolTests(unittest.TestCase):
    """VT-01 and the frozen protocol contract."""

    def test_frozen_protocol_matches_both_literals(self):
        path = os.path.join(ROOT, "benchmarks", "pr15i_d3a", "protocol_v1.json")
        with open(path, encoding="utf-8") as handle:
            protocol = json.load(handle)
        self.assertEqual(protocol, run.EXPECTED_PROTOCOL)
        self.assertEqual(protocol, verify.EXPECTED_PROTOCOL)
        self.assertEqual(protocol["base_sha"], verify.BASE_SHA)

    def test_protocol_has_the_exact_stage_and_counter_schema(self):
        protocol, _ = run.load_protocol()
        self.assertEqual(len(protocol["stages"]), 25)
        self.assertEqual(len(protocol["counters"]), 15)
        self.assertEqual(protocol["stages"][0], "plan_ns")
        self.assertEqual(protocol["stages"][-1], "candidate_heap_ns")
        self.assertEqual(protocol["counters"][-1], "candidate_samples_key")

    def test_nine_lane_matrix_is_exact(self):
        protocol, _ = run.load_protocol()
        self.assertEqual(
            protocol["lane_ids"],
            [
                "pr15d_v1/10000/absent/k100",
                "pr15d_v1/10000/rare/k100",
                "pr15d_v1/10000/medium/k100",
                "pr15d_v1/10000/common/k100",
                "pr15d_v1/100000/absent/k100",
                "pr15d_v1/100000/rare/k100",
                "pr15d_v1/100000/medium/k100",
                "pr15d_v1/100000/common/k100",
                "pr15d_v1/100000/common/k10",
            ],
        )

    def test_paired_and_control_schedules_are_frozen(self):
        protocol, _ = run.load_protocol()
        paired = run.slot_plan(protocol)
        self.assertEqual(len(paired), 24)
        self.assertEqual(
            [entry["arm"] for entry in paired[:6]], list("AQPPQA")
        )
        control = run.control_plan(protocol)
        self.assertEqual(len(control), 16)
        self.assertEqual([entry["arm"] for entry in control[:4]], ["A1", "A2", "A2", "A1"])


class HostTests(unittest.TestCase):
    """VT-18: contention and affinity gates."""

    def test_clear_probe_passes(self):
        module = mock.Mock()
        module.check_contention.return_value = {"state": "clear", "reason_codes": []}
        record = run.contention_probe(module, "/tmp/unused.json")
        self.assertEqual(record["state"], "clear")

    def test_nonclear_probe_blocks(self):
        module = mock.Mock()
        module.check_contention.return_value = {"state": "busy", "reason_codes": ["x"]}
        with self.assertRaises(run.D3ABlocked):
            run.contention_probe(module, "/tmp/unused.json")

    def test_single_allowed_cpu_blocks(self):
        with mock.patch.object(run.os, "sched_getaffinity", return_value={0}):
            with self.assertRaises(run.D3ABlocked):
                run.affinity_plan()

    def test_two_cpus_pin_controller_second_adapter_first(self):
        with mock.patch.object(run.os, "sched_getaffinity", return_value={1, 3}):
            with mock.patch.object(run.shutil, "which", return_value="/usr/bin/taskset"):
                self.assertEqual(run.affinity_plan(), (3, 1))


class PathAndWriteTests(unittest.TestCase):
    """VT-23/VT-25 support: exclusive writes and traversal refusal."""

    def test_exclusive_write_refuses_existing_and_preserves_bytes(self):
        root = tempfile.mkdtemp(prefix="d3a-write-")
        try:
            path = os.path.join(root, "evidence.json")
            run.write_json_exclusive(path, {"value": 1})
            with open(path, "rb") as handle:
                before = handle.read()
            with self.assertRaises(run.D3AError):
                run.write_json_exclusive(path, {"value": 2})
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), before)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(run.D3AError):
            run.confined("/tmp/d3a-root", "/tmp/d3a-root/../escape", "out")


class ArchiveTests(unittest.TestCase):
    """VT-23, VT-24 and VT-25."""

    def _campaign(self):
        root = tempfile.mkdtemp(prefix="d3a-archive-")
        files = {
            "raw/a.json": b'{"a":1}\n',
            "setup/contention/c.json": b'{"state":"clear"}\n',
            "setup/indexes/x/segment": b"excluded",
            "sanitized/summary.json": b'{"summary":1}\n',
        }
        for relative, payload in files.items():
            path = os.path.join(root, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(payload)
        return root

    def test_archive_members_exclude_indexes(self):
        protocol, _ = run.load_protocol()
        root = self._campaign()
        try:
            members = run._archive_members(root, protocol)
            self.assertIn("raw/a.json", members)
            self.assertIn("setup/contention/c.json", members)
            self.assertNotIn("setup/indexes/x/segment", members)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_archive_round_trip_and_member_tamper_is_rejected(self):
        protocol, _ = run.load_protocol()
        root = self._campaign()
        archive_dir = tempfile.mkdtemp(prefix="d3a-archive-out-")
        try:
            members = run._archive_members(root, protocol)
            archive = os.path.join(archive_dir, "campaign.tar.gz")
            inventory = run._write_archive(root, archive, members)
            with self.assertRaises(run.D3ABlocked):
                run._verify_archive(archive, {"raw/a.json": inventory["raw/a.json"]})
            inventory["raw/a.json"] = "0" * 64
            with self.assertRaises(run.D3ABlocked):
                run._verify_archive(archive, inventory)
            inventory = run._write_archive(root, archive + ".2", members)
            sidecar = archive + ".2.sha256"
            with open(sidecar, "w", encoding="utf-8") as handle:
                handle.write(
                    f"{run.sha256_file(archive + '.2')}  {os.path.basename(archive + '.2')}\n"
                )
            run.verify_archive_bundle(archive + ".2", sidecar, inventory)
            with open(sidecar, "w", encoding="utf-8") as handle:
                handle.write(f"{'0' * 64}  {os.path.basename(archive + '.2')}\n")
            with self.assertRaises(run.D3ABlocked):
                run.verify_archive_bundle(archive + ".2", sidecar, inventory)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(archive_dir, ignore_errors=True)

    def test_symlink_member_is_rejected(self):
        protocol, _ = run.load_protocol()
        root = self._campaign()
        try:
            os.symlink(
                os.path.join(root, "raw/a.json"), os.path.join(root, "raw/link.json")
            )
            with self.assertRaises(run.D3AError):
                run._archive_members(root, protocol)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_safe_member_rejects_traversal_and_absolute_paths(self):
        for bad in ("../escape", "/absolute", "a/../../b"):
            with self.assertRaises(verify.VerifyError):
                verify.safe_member(bad)
        self.assertEqual(verify.safe_member("raw/a.json"), "raw/a.json")


class ResponseValidationTests(unittest.TestCase):
    """VT-06 and VT-07 helper contracts."""

    def test_engine_ns_and_oracle_are_checked(self):
        lane = {"id": "pr15d_v1/10000/absent/k100"}
        expected = {"total_hits": 0, "doc_ids": []}
        run._validate_response(
            {"request_id": "r", "engine_ns": 1, "total_hits": 0, "doc_ids": []},
            lane, expected, "r",
        )
        for bad in (
            {"request_id": "r", "engine_ns": 0, "total_hits": 0, "doc_ids": []},
            {"request_id": "r", "engine_ns": -1, "total_hits": 0, "doc_ids": []},
            {"request_id": "r", "engine_ns": True, "total_hits": 0, "doc_ids": []},
            {"request_id": "r", "engine_ns": 1, "total_hits": 1, "doc_ids": []},
            {"request_id": "r", "engine_ns": 1, "total_hits": 0, "doc_ids": ["x"]},
        ):
            with self.assertRaises(run.D3AInvalid):
                run._validate_response(bad, lane, expected, "r")


if __name__ == "__main__":
    unittest.main()
