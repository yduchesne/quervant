#!/usr/bin/env python3
"""Unit tests for the PR 15E-B1 targeted benchmark runner.

Standard library only. These tests never build a Rust adapter, never generate a
100K corpus and never time a query: they exercise the runner's validation,
refusal, lane-selection, summary and comparison logic with synthetic records, so
they are fast and deterministic in CI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_targeted as runner  # noqa: E402

GIT_AVAILABLE = shutil.which("git") is not None


def git(tree, *args):
    result = subprocess.run(
        ["git", "-C", tree, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def init_repo(path):
    git(path, "init", "-q")
    git(path, "config", "user.email", "tests@quervant.local")
    git(path, "config", "user.name", "quervant tests")
    with open(os.path.join(path, "tracked.txt"), "w", encoding="utf-8") as handle:
        handle.write("one\n")
    git(path, "add", "tracked.txt")
    git(path, "commit", "-q", "-m", "initial")


def lane_record(lane_id, medians, hits=5):
    return {
        "id": lane_id,
        "n": 100000,
        "class": "common",
        "k": 100,
        "regime": "warm",
        "total_hits": hits,
        "trial_medians_ns": medians,
    }


def synthetic_summary(
    stage="b1a",
    source_sha="a" * 40,
    commit_time=1000,
    corpus="c" * 64,
    fingerprint="f" * 64,
    lanes=None,
    trial_ratios=None,
    contention="clear",
):
    lanes = lanes or [
        lane_record("pr15d_v1/100000/absent/k100", [100, 102, 101]),
        lane_record("pr15d_v1/100000/common/k100", [1000, 1005, 1010]),
    ]
    if trial_ratios is not None:
        lanes = [
            lane_record(lane["id"], trial_ratios[index])
            for index, lane in enumerate(lanes)
        ]
    return {
        "schema": runner.SCHEMA_SOURCE,
        "stage": stage,
        "source_sha": source_sha,
        "source_commit_time": commit_time,
        "tooling_sha": "b" * 40,
        "tooling_root": runner.TOOLING_ROOT,
        "binary_sha256": "d" * 64,
        "binary_bytes": 1,
        "corpus_manifest_sha256": corpus,
        "corpora": {},
        "environment": {},
        "environment_fingerprint": fingerprint,
        "lanes": [
            {
                **lane,
                "trial_p95_ns": [value + 1 for value in lane["trial_medians_ns"]],
                "trial_p99_ns": [value + 2 for value in lane["trial_medians_ns"]],
                "median_of_medians_ns": sorted(lane["trial_medians_ns"])[1],
                "dispersion_ns": {
                    "min": min(lane["trial_medians_ns"]),
                    "max": max(lane["trial_medians_ns"]),
                },
                "samples_ns": [[value] * 20 for value in lane["trial_medians_ns"]],
            }
            for lane in lanes
        ],
        "trials": [
            {
                "index": index,
                "started_utc": "2026-01-01T00:00:00Z",
                "ended_utc": "2026-01-01T00:01:00Z",
                "contention_before": contention,
                "contention_after": contention,
            }
            for index in range(1, 4)
        ],
        "measured_utc": "2026-01-01T00:02:00Z",
    }


class StageLaneTests(unittest.TestCase):
    def test_stage_matrices_are_frozen_warm_lanes(self):
        expected_counts = {"b1a": 6, "b1b": 5, "final": 9}
        for stage, count in expected_counts.items():
            lanes = runner.stage_lanes(stage)
            self.assertEqual(len(lanes), count, stage)
            self.assertEqual(
                len({lane["id"] for lane in lanes}), count, f"{stage} duplicate lane"
            )
            for lane in lanes:
                self.assertEqual(lane["regime"], "warm")
                self.assertIn(lane["n"], (10000, 100000))

    def test_stage_lane_tables_match_frozen_descriptors(self):
        for stage in runner.STAGES:
            selected = {
                (lane["n"], lane["class"], lane["k"]) for lane in runner.stage_lanes(stage)
            }
            self.assertEqual(selected, set(runner.STAGE_LANES[stage]), stage)

    def test_final_stage_includes_the_k10_control_lane(self):
        lanes = runner.stage_lanes("final")
        k10 = [lane for lane in lanes if lane["k"] == 10]
        self.assertEqual(len(k10), 1)
        self.assertEqual(k10[0]["class"], "common")
        self.assertEqual(k10[0]["n"], 100000)

    def test_unknown_stage_is_blocked(self):
        with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
            runner.stage_lanes("b1c")
        self.assertEqual(caught.exception.rule, "X32_STAGE")


class OutPathTests(unittest.TestCase):
    def test_accepts_gitignored_target_subtree(self):
        out = os.path.join(runner.TOOLING_ROOT, "target", "pr15e-b1", "b1a")
        self.assertEqual(runner.validate_out_path(out), os.path.realpath(out))

    def test_rejects_relative_path(self):
        with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
            runner.validate_out_path("target/pr15e-b1/b1a")
        self.assertEqual(caught.exception.rule, "X19_PATH_ESCAPE")

    def test_rejects_outside_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(runner.pr15d_run.RunBlocked):
                runner.validate_out_path(temporary)

    def test_rejects_traversal_out_of_target(self):
        escape = os.path.join(
            runner.TOOLING_ROOT, "target", "pr15e-b1", "..", "..", "..", "tmp"
        )
        with self.assertRaises(runner.pr15d_run.RunBlocked):
            runner.validate_out_path(escape)


@unittest.skipUnless(GIT_AVAILABLE, "git is required")
class SourceTreeTests(unittest.TestCase):
    def test_clean_worktree_resolves_with_sha_and_commit_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            tree = os.path.realpath(temporary)
            init_repo(tree)
            source = runner.resolve_source_tree(tree)
            self.assertEqual(source["tree"], tree)
            self.assertEqual(len(source["sha"]), 40)
            self.assertIsInstance(source["commit_time"], int)
            self.assertGreater(source["commit_time"], 0)

    def test_dirty_tracked_tree_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            tree = os.path.realpath(temporary)
            init_repo(tree)
            with open(os.path.join(tree, "tracked.txt"), "w", encoding="utf-8") as handle:
                handle.write("changed\n")
            with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
                runner.resolve_source_tree(tree)
            self.assertEqual(caught.exception.rule, "X27_SOURCE")
            self.assertIn("uncommitted tracked changes", caught.exception.detail)

    def test_untracked_files_alone_do_not_dirty_the_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            tree = os.path.realpath(temporary)
            init_repo(tree)
            with open(os.path.join(tree, "untracked.txt"), "w", encoding="utf-8") as handle:
                handle.write("scratch\n")
            self.assertEqual(runner.resolve_source_tree(tree)["tree"], tree)

    def test_non_git_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
                runner.resolve_source_tree(os.path.realpath(temporary))
            self.assertEqual(caught.exception.rule, "X27_SOURCE")

    def test_relative_source_tree_is_refused(self):
        with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
            runner.resolve_source_tree("benchmarks")
        self.assertEqual(caught.exception.rule, "X27_SOURCE")

    def test_subdirectory_of_a_worktree_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            tree = os.path.realpath(temporary)
            init_repo(tree)
            nested = os.path.join(tree, "nested")
            os.makedirs(nested)
            with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
                runner.resolve_source_tree(nested)
            self.assertEqual(caught.exception.rule, "X27_SOURCE")


class FrozenFileTests(unittest.TestCase):
    def test_frozen_pr15d_artifacts_match_the_pinned_hashes(self):
        runner.verify_frozen_files(runner.TOOLING_ROOT)

    def test_drift_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            relative = "benchmarks/pr15d/spec/pr15d_v1.json"
            target = os.path.join(temporary, relative)
            os.makedirs(os.path.dirname(target))
            with open(target, "wb") as handle:
                handle.write(b"{}\n")
            with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
                runner.verify_frozen_files(temporary, {relative: "0" * 64})
            self.assertEqual(caught.exception.rule, "X30_FROZEN_DRIFT")

    def test_missing_frozen_artifact_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
                runner.verify_frozen_files(temporary, {"missing/file": "0" * 64})
            self.assertEqual(caught.exception.rule, "X30_FROZEN_DRIFT")


class IdleGateTests(unittest.TestCase):
    def test_missing_idle_confirmation_blocks_without_timing(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = os.path.join(runner.TOOLING_ROOT, "target", "pr15e-b1", "gate-test")
            code = runner.main(
                ["--source-tree", temporary, "--stage", "b1a", "--out", out]
            )
            self.assertEqual(code, 3)
            self.assertFalse(os.path.exists(os.path.join(out, "runs")))

    def test_confirmed_flag_still_validates_the_source_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = os.path.join(runner.TOOLING_ROOT, "target", "pr15e-b1", "gate-test2")
            code = runner.main(
                [
                    "--source-tree",
                    os.path.realpath(temporary),
                    "--stage",
                    "b1a",
                    "--out",
                    out,
                    "--idle-confirmed",
                ]
            )
            self.assertEqual(code, 3)
            self.assertFalse(os.path.exists(os.path.join(out, "runs")))


class VerdictTests(unittest.TestCase):
    def test_sign_consistent_improvement_is_b_faster(self):
        self.assertEqual(runner.lane_verdict([0.9, 0.95, 0.92]), "B_FASTER")

    def test_sign_consistent_regression_is_a_faster(self):
        self.assertEqual(runner.lane_verdict([1.1, 1.05, 1.2]), "A_FASTER")

    def test_mixed_signs_are_inconclusive(self):
        self.assertEqual(runner.lane_verdict([0.9, 1.1, 0.95]), "INCONCLUSIVE")
        self.assertEqual(runner.lane_verdict([1.0, 1.0, 1.0]), "INCONCLUSIVE")

    def test_paired_ratios_use_trial_index_pairing(self):
        a = {"trial_medians_ns": [100, 200, 300]}
        b = {"trial_medians_ns": [50, 100, 150]}
        self.assertEqual(runner._trial_ratios(a, b), [0.5, 0.5, 0.5])


class CompareTests(unittest.TestCase):
    def compare(self, a, b):
        return runner.compare_summaries(a, b)

    def test_comparable_pair_reports_per_lane_ratios(self):
        a = synthetic_summary(source_sha="a" * 40, commit_time=1000)
        b = synthetic_summary(
            source_sha="b" * 40,
            commit_time=2000,
            trial_ratios=[[50, 51, 50], [500, 502, 505]],
        )
        comparison = self.compare(a, b)
        self.assertEqual(comparison["schema"], runner.SCHEMA_COMPARISON)
        abs_lane, common_lane = comparison["lanes"]
        self.assertEqual(abs_lane["verdict"], "B_FASTER")
        self.assertEqual(common_lane["verdict"], "B_FASTER")
        self.assertAlmostEqual(abs_lane["median_ratio"], 50 / 101, places=6)
        self.assertEqual(comparison["arm_a"]["label"], "original main")
        self.assertEqual(comparison["arm_b"]["label"], "B1a")

    def test_regression_lane_is_reported_as_a_faster(self):
        a = synthetic_summary(source_sha="a" * 40)
        b = synthetic_summary(
            source_sha="b" * 40, trial_ratios=[[200, 210, 205], [2000, 2000, 2000]]
        )
        comparison = self.compare(a, b)
        self.assertTrue(all(lane["verdict"] == "A_FASTER" for lane in comparison["lanes"]))

    def test_different_corpus_is_incomparable(self):
        a = synthetic_summary(source_sha="a" * 40)
        b = synthetic_summary(source_sha="b" * 40, corpus="e" * 64)
        with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
            self.compare(a, b)
        self.assertEqual(caught.exception.rule, "X37_INCOMPARABLE")
        self.assertIn("corpus", caught.exception.detail)

    def test_different_host_fingerprint_is_incomparable(self):
        a = synthetic_summary(source_sha="a" * 40)
        b = synthetic_summary(source_sha="b" * 40, fingerprint="9" * 64)
        with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
            self.compare(a, b)
        self.assertIn("host fingerprint", caught.exception.detail)

    def test_contended_trial_is_incomparable(self):
        a = synthetic_summary(source_sha="a" * 40)
        b = synthetic_summary(source_sha="b" * 40, contention="suspected")
        with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
            self.compare(a, b)
        self.assertIn("contention", caught.exception.detail)

    def test_same_source_sha_is_incomparable(self):
        a = synthetic_summary(source_sha="a" * 40)
        b = synthetic_summary(source_sha="a" * 40, commit_time=1001)
        with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
            self.compare(a, b)
        self.assertIn("same source SHA", caught.exception.detail)

    def test_missing_trial_is_incomparable(self):
        a = synthetic_summary(source_sha="a" * 40)
        b = synthetic_summary(source_sha="b" * 40)
        b["trials"] = b["trials"][:2]
        with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
            self.compare(a, b)
        self.assertIn("3 trials", caught.exception.detail)

    def test_lane_set_mismatch_is_incomparable(self):
        a = synthetic_summary(source_sha="a" * 40)
        b = synthetic_summary(source_sha="b" * 40)
        b["lanes"] = b["lanes"][:1]
        with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
            self.compare(a, b)
        self.assertIn("lane set", caught.exception.detail)


class PublishTests(unittest.TestCase):
    def test_single_summary_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(runner.publish_comparison(temporary, [synthetic_summary()]))

    def test_two_summaries_publish_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            a = synthetic_summary(source_sha="a" * 40, commit_time=1000)
            b = synthetic_summary(source_sha="b" * 40, commit_time=2000)
            comparison = runner.publish_comparison(temporary, [b, a])
            self.assertIsNotNone(comparison)
            with open(os.path.join(temporary, "comparison.json"), encoding="utf-8") as handle:
                published = json.load(handle)
            self.assertEqual(published["arm_a"]["source_sha"], "a" * 40)
            self.assertEqual(published["arm_b"]["source_sha"], "b" * 40)
            with open(os.path.join(temporary, "comparison.md"), encoding="utf-8") as handle:
                markdown = handle.read()
            self.assertIn("stage `b1a`", markdown)
            self.assertIn("INCONCLUSIVE", markdown)

    def test_three_summaries_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            summaries = [
                synthetic_summary(source_sha=char * 40, commit_time=index)
                for index, char in enumerate(("a", "b", "c"), start=1000)
            ]
            with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
                runner.publish_comparison(temporary, summaries)
            self.assertEqual(caught.exception.rule, "X38_EXTRA_ARMS")

    def test_collect_summaries_reads_nested_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = os.path.join(temporary, "runs", "a" * 40, "run1")
            os.makedirs(run_dir)
            summary = synthetic_summary()
            with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
                json.dump(summary, handle)
            collected = runner.collect_summaries(temporary)
            self.assertEqual(len(collected), 1)
            self.assertEqual(collected[0]["stage"], "b1a")


class AdapterInvocationTests(unittest.TestCase):
    def test_argv_shape_puts_the_binary_first(self):
        engine, argv = runner._adapter_invocation("/tmp/adapter", "/tmp/index")
        self.assertEqual(engine, "quervant")
        self.assertEqual(argv, ["/tmp/adapter", "--index-dir", "/tmp/index"])
        # The frozen AdapterProcess treats argv[0] as the executable; an argv that
        # starts with a flag fails with FileNotFoundError at measurement time.
        self.assertFalse(argv[0].startswith("-"))


class DigestTests(unittest.TestCase):
    def test_directory_digest_changes_with_content_and_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = os.path.join(temporary, "one")
            os.makedirs(first)
            with open(os.path.join(first, "a"), "w", encoding="utf-8") as handle:
                handle.write("x")
            before = runner.directory_digest(first)
            self.assertEqual(before, runner.directory_digest(first))
            with open(os.path.join(first, "a"), "w", encoding="utf-8") as handle:
                handle.write("y")
            self.assertNotEqual(before, runner.directory_digest(first))
            changed = runner.directory_digest(first)
            with open(os.path.join(first, "b"), "w", encoding="utf-8") as handle:
                handle.write("y")
            self.assertNotEqual(changed, runner.directory_digest(first))


class SummaryTests(unittest.TestCase):
    def test_contended_trial_refuses_before_measuring(self):
        record = {"state": "suspected", "reason_codes": ["run_queue"]}
        with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
            runner._require_clear(record, "trial 1 before")
        self.assertEqual(caught.exception.rule, "X34_CONTENTION")
        self.assertIn("run_queue", caught.exception.detail)

    def test_contention_probe_returns_a_state_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            record = runner.contention_for(os.path.join(temporary, "probe.json"))
            self.assertIn("state", record)
            self.assertIn("reason_codes", record)

    def test_clear_contention_is_accepted(self):
        runner._require_clear({"state": "clear"}, "trial 1 before")

    def test_unknown_contention_state_is_not_clear(self):
        with self.assertRaises(runner.pr15d_run.RunBlocked):
            runner._require_clear(
                {"state": "unknown", "reason_codes": ["probe_failed"]}, "trial 1"
            )

    def test_summarize_source_rejects_short_sample_lists(self):
        lanes = [
            {"id": "lane", "n": 1, "class": "c", "k": 1, "regime": "warm"}
        ]
        trial_lane = {
            "id": "lane",
            "samples_ns": [1] * 19,
            "oracle_ok": True,
            "summary_ns": {"median": 1, "p95": 1, "p99": 1},
            "total_hits": 0,
        }
        trials = [
            {"index": index, "lanes": [trial_lane]} for index in range(1, 4)
        ]
        with self.assertRaises(runner.pr15d_run.RunBlocked) as caught:
            runner.summarize_source(
                "b1a",
                {"sha": "a" * 40, "commit_time": 1},
                {"binary_sha256": "b" * 64, "binary_bytes": 1},
                {"manifest_sha256": "c" * 64, "corpora": {}},
                {"filesystem": "ext4"},
                lanes,
                trials,
            )
        self.assertEqual(caught.exception.rule, "X33_SAMPLE_COUNT")


if __name__ == "__main__":
    unittest.main()
