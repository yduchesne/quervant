#!/usr/bin/env python3
"""PR 15F reopen campaign tests (T08, T09, T10 subset)."""

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

ERRORS = (pq.Pr15fError, pq.eprofile.Pr15eError, campaign.CampaignError)


def _stage(**overrides):
    stage = {
        "fs_directory_open_ns": 100,
        "index_open_ns": 200,
        "snapshot_acquire_ns": 50,
        "reopen_core_ns": 250,
        "reopen_total_ns": 350,
        "documents": 10000,
        "segments": 1,
        "generation": 1,
    }
    stage.update(overrides)
    return stage


def _payload(n=10000, iterations=1):
    samples = [_stage(documents=n) for _ in range(iterations)]
    return {
        "schema": pq.PROBE_SCHEMA,
        "mode": "single" if iterations == 1 else "loop",
        "n": n,
        "iteration_count": iterations,
        "documents_verified": n,
        "segments_verified": 1,
        "generation": 1,
        "iterations": samples,
        "stage_totals_ns": {
            "fs_directory_open_ns": 100 * iterations,
            "index_open_ns": 200 * iterations,
            "snapshot_acquire_ns": 50 * iterations,
            "reopen_core_ns": 250 * iterations,
            "reopen_total_ns": 350 * iterations,
            "sample_count": iterations,
        },
    }


class StageValidationTests(unittest.TestCase):
    def test_valid_stage_and_checked_sums(self):
        campaign.validate_stage(_stage())
        for mutation in (
            {"index_open_ns": 0},
            {"snapshot_acquire_ns": -1},
            {"fs_directory_open_ns": True},
            {"reopen_core_ns": 999},
            {"reopen_total_ns": 999},
        ):
            with self.assertRaises(ERRORS, msg=str(mutation)):
                campaign.validate_stage(_stage(**mutation))

    def test_each_of_the_five_timed_fields_is_required(self):
        for field in (
            "fs_directory_open_ns",
            "index_open_ns",
            "snapshot_acquire_ns",
            "reopen_core_ns",
            "reopen_total_ns",
        ):
            broken = _stage()
            del broken[field]
            with self.assertRaises(ERRORS, msg=field):
                campaign.validate_stage(broken)

    def test_single_and_loop_payloads(self):
        self.assertEqual(
            len(campaign.validate_probe_payload(_payload(), "single", 10000, 1)), 1
        )
        self.assertEqual(
            len(campaign.validate_probe_payload(_payload(100000, 128), "loop", 100000, 128)),
            128,
        )
        for payload, mode, n, iterations in (
            (_payload(), "loop", 10000, 1),
            (_payload(), "single", 100000, 1),
            (_payload(), "single", 10000, 2),
            (_payload(n=10000, iterations=64), "single", 10000, 64),
        ):
            with self.assertRaises(ERRORS, msg=str((mode, n, iterations))):
                campaign.validate_probe_payload(payload, mode, n, iterations)

    def test_wrong_counts_and_generation_are_rejected(self):
        for mutation in (
            {"documents_verified": 9999},
            {"segments_verified": 0},
            {"generation": 0},
            {"iteration_count": 2},
            {"iterations": []},
        ):
            payload = {**_payload(), **mutation}
            with self.assertRaises(ERRORS, msg=str(mutation)):
                campaign.validate_probe_payload(payload, "single", 10000, 1)


class ReopenSummaryTests(unittest.TestCase):
    def test_median_p95_and_mad_are_deterministic(self):
        samples = [
            _stage(
                fs_directory_open_ns=value,
                index_open_ns=value * 2,
                snapshot_acquire_ns=value,
                reopen_core_ns=value * 3,
                reopen_total_ns=value * 4,
            )
            for value in (50, 10, 40, 20, 30)
        ]
        summary = campaign.summarize_reopen(samples)
        self.assertEqual(summary["fs_directory_open_ns"]["median"], 30)
        self.assertEqual(summary["fs_directory_open_ns"]["p95"], 50)
        self.assertEqual(summary["fs_directory_open_ns"]["min"], 10)
        self.assertEqual(summary["fs_directory_open_ns"]["max"], 50)
        self.assertEqual(summary["fs_directory_open_ns"]["median_absolute_deviation"], 10)
        self.assertEqual(summary["reopen_total_ns"]["median"], 120)

    def test_fixed_rotation_has_21_fresh_processes_per_n(self):
        sequence = campaign.reopen_launch_sequence()
        self.assertEqual(len(sequence), 42)
        self.assertEqual(sum(1 for item in sequence if item["n"] == 10000), 21)
        self.assertEqual(sum(1 for item in sequence if item["n"] == 100000), 21)
        block1 = [item["n"] for item in sequence if item["block"] == "block1"]
        block2 = [item["n"] for item in sequence if item["block"] == "block2"]
        self.assertEqual(block1[0], 10000)
        self.assertEqual(block1[1], 100000)
        self.assertEqual(block2[0], 100000)
        self.assertEqual(block2[1], 10000)
        self.assertEqual([item["position"] for item in sequence if item["block"] == "block1"], list(range(21)))

    def test_stdout_parser_rejects_banner_or_multiple_objects(self):
        good = json.dumps({"a": 1})
        self.assertEqual(campaign._parse_probe_stdout(good + "\n"), {"a": 1})
        for stdout in ("", good + "\n" + good + "\n", "not json\n", "[1]\n"):
            with self.assertRaises(ERRORS):
                campaign._parse_probe_stdout(stdout)


class RunDirectoryTests(unittest.TestCase):
    def setUp(self):
        os.makedirs(pq.PR15F_TARGET_ROOT, exist_ok=True)
        self.root = tempfile.mkdtemp(prefix="_test-runs-", dir=pq.PR15F_TARGET_ROOT)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_suffix_ladder_moves_to_the_first_free_run(self):
        base = os.path.join(self.root, "run-01")
        os.makedirs(base)
        with open(os.path.join(base, "preflight.json"), "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        chosen, relocated = campaign.choose_run_dir(base)
        self.assertEqual(chosen, os.path.join(self.root, "run-02"))
        self.assertEqual(relocated, chosen)
        self.assertTrue(os.path.isdir(chosen))

    def test_all_occupied_suffixes_are_a_hard_stop(self):
        for suffix in range(1, 6):
            path = os.path.join(self.root, f"run-{suffix:02d}")
            os.makedirs(path)
            with open(os.path.join(path, "keep.json"), "w", encoding="utf-8") as handle:
                handle.write("{}\n")
        with self.assertRaises(ERRORS) as raised:
            campaign.choose_run_dir(os.path.join(self.root, "run-01"))
        self.assertEqual(raised.exception.status, "HARD_STOP")


class FileDigestTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pr15f-digests-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_digests_are_stable_and_symlinks_are_rejected(self):
        path = os.path.join(self.root, "index")
        os.makedirs(path)
        with open(os.path.join(path, "CURRENT"), "wb") as handle:
            handle.write(b"current")
        first = campaign.file_digests(self.root)
        second = campaign.file_digests(self.root)
        self.assertEqual(first, second)
        self.assertEqual(first["index/CURRENT"]["bytes"], 7)
        os.symlink(os.path.join(path, "CURRENT"), os.path.join(path, "link"))
        with self.assertRaises(ERRORS):
            campaign.file_digests(self.root)


class InventorySummaryTests(unittest.TestCase):
    def test_byte_categories_must_reconcile(self):
        record = {
            "total_file_bytes": 100,
            "segment_file_bytes": 70,
            "manifest_file_bytes": 10,
            "mutation_state_file_bytes": 15,
            "metadata_file_bytes": 5,
            "segment_section_bytes_total": 69,
            "segment_nonsection_bytes_total": 1,
            "section_bytes": {"Stored": 40, "DocKeys": 29},
        }
        classified = (
            record["segment_file_bytes"]
            + record["manifest_file_bytes"]
            + record["mutation_state_file_bytes"]
            + record["metadata_file_bytes"]
        )
        self.assertEqual(classified, record["total_file_bytes"])
        self.assertEqual(
            record["segment_section_bytes_total"]
            + record["segment_nonsection_bytes_total"],
            record["segment_file_bytes"],
        )
        self.assertEqual(sum(record["section_bytes"].values()), 69)


if __name__ == "__main__":
    unittest.main()
