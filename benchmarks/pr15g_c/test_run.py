#!/usr/bin/env python3
"""Unit tests for the PR 15G-C benchmark runner.

Standard library only. These tests never build a Rust adapter, generate a 100K
corpus or time a query. They exercise source pinning, output isolation, lane
identity, qualification, ratio math and report sanitization with deterministic
synthetic summaries and temporary Git repositories. Process/clock behaviour is
stubbed at those boundaries only; result correctness is never faked.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_spec = importlib.util.spec_from_file_location(
    "pr15g_c_run_under_test", os.path.join(HERE, "run.py")
)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

RunBlocked = runner.base.pr15d_run.RunBlocked
GIT_AVAILABLE = shutil.which("git") is not None
MEASURED = runner.base.pr15d_run.MEASURED
TRIALS = runner.TRIALS


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
    return result.stdout.strip()


def init_repo(path):
    git(path, "init", "-q")
    git(path, "config", "user.email", "tests@quervant.local")
    git(path, "config", "user.name", "quervant tests")
    with open(os.path.join(path, "tracked.txt"), "w", encoding="utf-8") as handle:
        # Include the repo name so unrelated temporary repos never share a commit
        # identity by accident.
        handle.write(f"one-{os.path.basename(path)}\n")
    git(path, "add", "tracked.txt")
    git(path, "commit", "-q", "-m", "initial")
    return git(path, "rev-parse", "HEAD")


def add_commit(path, text="two"):
    with open(os.path.join(path, "tracked.txt"), "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    git(path, "add", "tracked.txt")
    git(path, "commit", "-q", "-m", text)
    return git(path, "rev-parse", "HEAD")


def assert_blocked(testcase, call, rule=None):
    try:
        call()
    except RunBlocked as error:
        if rule is not None:
            testcase.assertEqual(error.rule, rule, error.detail)
        return error
    testcase.fail("expected RunBlocked")


def lane_record(lane_id, medians, hits=7):
    return {
        "id": lane_id,
        "n": int(lane_id.split("/")[1]),
        "class": lane_id.split("/")[2],
        "k": int(lane_id.split("/")[3][1:]),
        "regime": "warm",
        "total_hits": hits,
        "trial_medians_ns": list(medians),
        "median_of_medians_ns": sorted(medians)[len(medians) // 2],
        "samples_ns": [[median] * MEASURED for median in medians],
    }


def synthetic_summary(
    *,
    source_sha,
    arm_role,
    medians=100,
    hits=7,
    fingerprint="f" * 64,
    trials=TRIALS,
    samples=MEASURED,
    contention="clear",
    descendant=True,
):
    lanes = [
        lane_record(lane_id, [medians, medians + 1, medians + 2], hits)
        for lane_id in runner.LANE_IDS
    ]
    if samples != MEASURED:
        for lane in lanes:
            lane["samples_ns"] = [series[:samples] for series in lane["samples_ns"]]
    return {
        "schema": runner.SCHEMA_SOURCE,
        "phase": runner.PHASE,
        "stage": runner.STAGE,
        "source_sha": source_sha,
        "arm_role": arm_role,
        "is_descendant_of_baseline": descendant,
        "tooling_sha": "c" * 40,
        "binary_sha256": "d" * 64,
        "corpus_manifest_sha256": "e" * 64,
        "environment_fingerprint": fingerprint,
        "lanes": lanes,
        "trials": [
            {
                "index": index,
                "contention_before": contention,
                "contention_after": contention,
            }
            for index in range(1, trials + 1)
        ],
    }


class AuthorizationTests(unittest.TestCase):
    # GC-B01 — only a real operator flag satisfies the authorization gate.
    def test_b01_operator_flag_is_required(self):
        confirmed = runner.build_parser().parse_args(
            ["--source-tree", "/x", "--out", "/y", "--idle-confirmed"]
        )
        unconfirmed = runner.build_parser().parse_args(
            ["--source-tree", "/x", "--out", "/y"]
        )
        self.assertFalse(runner.authorization_blocked(confirmed))
        self.assertTrue(runner.authorization_blocked(unconfirmed))

    # GC-B13 — an unauthorized invocation exits 3 before creating anything.
    def test_b13_no_measurement_without_operator(self):
        out = os.path.join(tempfile.gettempdir(), "pr15g-c-never-created")
        if os.path.exists(out):
            shutil.rmtree(out)
        args = argparse.Namespace(
            source_tree="/does/not/exist", out=out, idle_confirmed=False
        )
        self.assertEqual(runner.execute(args), 3)
        self.assertFalse(os.path.exists(out))


@unittest.skipUnless(GIT_AVAILABLE, "git is required for source-pinning tests")
class SourcePinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="pr15g-c-src-")
        self.repo = os.path.join(self.temp, "repo")
        os.makedirs(self.repo)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    # GC-B02 — a source that is not the pinned baseline or a descendant is refused.
    def test_b02_source_a_not_pinned(self):
        init_repo(self.repo)
        source = runner.base.resolve_source_tree(self.repo)
        assert_blocked(self, lambda: runner.source_arm(source), "X41_SOURCE_PIN")

    # GC-B03 — arm B must be a distinct committed descendant of arm A.
    def test_b03_arm_b_must_be_distinct_descendant(self):
        first = init_repo(self.repo)
        saved = runner.ARM_A_SHA
        try:
            runner.ARM_A_SHA = first
            self.assertEqual(runner.source_arm(runner.base.resolve_source_tree(self.repo)), "A")
            second = add_commit(self.repo)
            self.assertNotEqual(first, second)
            self.assertEqual(
                runner.source_arm(runner.base.resolve_source_tree(self.repo)), "B"
            )
            other = os.path.join(self.temp, "other")
            os.makedirs(other)
            init_repo(other)
            assert_blocked(
                self,
                lambda: runner.source_arm(runner.base.resolve_source_tree(other)),
                "X41_SOURCE_PIN",
            )
        finally:
            runner.ARM_A_SHA = saved

    # GC-B04 — a dirty measured tree is refused.
    def test_b04_dirty_tree_is_rejected(self):
        init_repo(self.repo)
        with open(os.path.join(self.repo, "tracked.txt"), "w", encoding="utf-8") as handle:
            handle.write("dirty\n")
        assert_blocked(
            self,
            lambda: runner.base.resolve_source_tree(self.repo),
            "X27_SOURCE",
        )

    # GC-B05 — frozen measurement input drift is refused.
    def test_b05_frozen_input_drift_is_rejected(self):
        init_repo(self.repo)
        assert_blocked(
            self, lambda: runner.verify_frozen_inputs(self.repo), "X30_FROZEN_DRIFT"
        )


class OutputIsolationTests(unittest.TestCase):
    # GC-B06 — output must be an exclusive path strictly beneath target/pr15g-c.
    def test_b06_output_escape_is_rejected(self):
        outside = tempfile.mkdtemp(prefix="pr15g-c-out-")
        try:
            assert_blocked(
                self, lambda: runner.validate_out_path(outside), "X19_PATH_ESCAPE"
            )
            root = os.path.join(runner.TOOLING_ROOT, "target", "pr15g-c")
            assert_blocked(
                self, lambda: runner.validate_out_path(root), "X19_PATH_ESCAPE"
            )
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    # GC-B11 — an existing run directory is never reused or overwritten.
    def test_b11_run_directory_collision_is_rejected(self):
        stage_root = tempfile.mkdtemp(
            prefix="pr15g-c-run-", dir=os.path.join(runner.TOOLING_ROOT, "target", "pr15g-c")
        )
        try:
            first = runner.allocate_run_dir(stage_root, "a" * 40, "20260101T000000000000Z")
            self.assertTrue(os.path.isdir(first))
            assert_blocked(
                self,
                lambda: runner.allocate_run_dir(
                    stage_root, "a" * 40, "20260101T000000000000Z"
                ),
                "X39_RUN_DIR",
            )
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)


class LaneAndComparisonTests(unittest.TestCase):
    def summary(self, **overrides):
        values = {
            "source_sha": runner.ARM_A_SHA,
            "arm_role": "A",
            "medians": 100,
        }
        values.update(overrides)
        return synthetic_summary(**values)

    def baseline(self, **overrides):
        return self.summary(**overrides)

    def candidate(self, **overrides):
        values = {
            "source_sha": "b" * 40,
            "arm_role": "B",
            "medians": 90,
            "descendant": True,
        }
        values.update(overrides)
        return synthetic_summary(**values)

    # GC-B07 — exactly the nine frozen warm descriptors are selected.
    def test_b07_exactly_nine_lanes(self):
        lanes = runner.stage_lanes()
        self.assertEqual([lane["id"] for lane in lanes], runner.LANE_IDS)
        self.assertEqual(len(lanes), 9)
        self.assertEqual(len(set(runner.LANE_IDS)), 9)
        self.assertTrue(all(lane["regime"] == "warm" for lane in lanes))

    # GC-B08 — fewer than three trials or non-20 sample lanes are refused.
    def test_b08_trial_and_sample_counts_are_enforced(self):
        assert_blocked(
            self,
            lambda: runner.compare_summaries(
                self.baseline(), self.candidate(trials=2)
            ),
            "X37_INCOMPARABLE",
        )
        assert_blocked(
            self,
            lambda: runner.compare_summaries(
                self.baseline(), self.candidate(samples=MEASURED - 1)
            ),
            "X37_INCOMPARABLE",
        )

    # GC-B09 — unknown/busy contention and inconsistent lane/oracle identity fail.
    def test_b09_contention_and_oracle_identity_are_enforced(self):
        for state in ("busy", "unknown"):
            assert_blocked(
                self,
                lambda state=state: runner.compare_summaries(
                    self.baseline(), self.candidate(contention=state)
                ),
                "X37_INCOMPARABLE",
            )
        changed = self.candidate()
        changed["lanes"][0]["total_hits"] += 1
        assert_blocked(
            self,
            lambda: runner.compare_summaries(self.baseline(), changed),
            "X37_INCOMPARABLE",
        )

    # GC-B10 — sign consistency only; no invented speedup threshold.
    def test_b10_sign_consistency(self):
        self.assertEqual(runner.base.lane_verdict([0.9, 0.8, 0.95]), "B_FASTER")
        self.assertEqual(runner.base.lane_verdict([1.1, 1.2, 1.05]), "A_FASTER")
        self.assertEqual(runner.base.lane_verdict([0.9, 1.1, 1.0]), "INCONCLUSIVE")

    # GC-B15 — mixed paired signs are INCONCLUSIVE even if the median improves.
    def test_b15_mixed_signs_are_inconclusive(self):
        self.assertEqual(
            runner.base.lane_verdict([0.90, 0.95, 1.05]), "INCONCLUSIVE"
        )
        self.assertEqual(
            runner.base.lane_verdict([1.10, 1.05, 0.98]), "INCONCLUSIVE"
        )

    # GC-B16 — rare-lane and regression gates match GC-P01–P03.
    def test_b16_gc_p_gates(self):
        def lane(lane_id, verdict, a_hits=10, b_hits=10):
            return {
                "id": lane_id,
                "a_median_of_medians_ns": 100,
                "b_median_of_medians_ns": 90,
                "verdict": verdict,
                "a_total_hits": a_hits,
                "b_total_hits": b_hits,
            }

        lanes = [
            lane(lane_id, "INCONCLUSIVE")
            for lane_id in runner.LANE_IDS
        ]
        by_id = {entry["id"]: entry for entry in lanes}
        by_id["pr15d_v1/100000/common/k100"]["verdict"] = "B_FASTER"
        by_id["pr15d_v1/100000/common/k10"]["verdict"] = "B_FASTER"
        gates = runner.gc_gate_verdicts(lanes)
        self.assertEqual(gates["GC-P01"], "PASS")
        self.assertEqual(gates["GC-P02"], "PASS")
        self.assertEqual(gates["GC-P03"], "PASS")
        self.assertEqual(gates["GC-P04"], "PASS")
        self.assertEqual(gates["overall"], "PASS")

        by_id["pr15d_v1/100000/medium/k100"]["verdict"] = "A_FASTER"
        self.assertEqual(runner.gc_gate_verdicts(lanes)["GC-P03"], "FAIL")
        self.assertEqual(runner.gc_gate_verdicts(lanes)["overall"], "FAIL")

        by_id["pr15d_v1/100000/medium/k100"]["verdict"] = "INCONCLUSIVE"
        by_id["pr15d_v1/100000/common/k100"]["verdict"] = "INCONCLUSIVE"
        self.assertEqual(runner.gc_gate_verdicts(lanes)["GC-P01"], "FAIL")
        self.assertEqual(runner.gc_gate_verdicts(lanes)["overall"], "FAIL")

    # GC-B14 — different host fingerprints are never compared.
    def test_b14_host_fingerprint_mismatch_is_rejected(self):
        assert_blocked(
            self,
            lambda: runner.compare_summaries(
                self.baseline(), self.candidate(fingerprint="0" * 64)
            ),
            "X37_INCOMPARABLE",
        )

    # A valid pair produces the expected comparison shape and verdicts.
    def test_valid_pair_comparison_shape(self):
        comparison = runner.compare_summaries(self.baseline(), self.candidate())
        self.assertEqual(comparison["schema"], runner.SCHEMA_COMPARISON)
        self.assertEqual(comparison["phase"], runner.PHASE)
        self.assertEqual(len(comparison["lanes"]), 9)
        self.assertTrue(all(lane["verdict"] == "B_FASTER" for lane in comparison["lanes"]))
        self.assertEqual(comparison["arm_a"]["source_sha"], runner.ARM_A_SHA)
        self.assertEqual(comparison["arm_b"]["source_sha"], "b" * 40)


class ReportSanitizerTests(unittest.TestCase):
    # GC-B12 — reports may not leak local paths, hosts, users or raw filenames.
    def test_b12_sensitive_report_material_is_rejected(self):
        for report in (
            {"detail": "/home/someone/worktree"},
            {"detail": os.path.join(runner.TOOLING_ROOT, "x")},
            {"detail": "summary.json"},
            {"detail": "trial-1.json"},
            {"detail": os.uname().nodename},
        ):
            assert_blocked(
                self,
                lambda report=report: runner.assert_report_sanitized(report),
                "X42_SENSITIVE_REPORT",
            )
        runner.assert_report_sanitized(
            {
                "schema": runner.SCHEMA_COMPARISON,
                "arm_a": {"source_sha": "a" * 40},
                "verdict": "B_FASTER",
            }
        )

    # The published comparison contains only aggregate, source-bound fields.
    def test_sanitized_comparison_drops_raw_material(self):
        comparison = runner.compare_summaries(
            synthetic_summary(source_sha=runner.ARM_A_SHA, arm_role="A"),
            synthetic_summary(
                source_sha="b" * 40, arm_role="B", medians=90, descendant=True
            ),
        )
        sanitized = runner.sanitize_comparison(comparison)
        self.assertNotIn("samples_ns", repr(sanitized))
        runner.assert_report_sanitized(sanitized)
        markdown = runner.render_comparison_markdown(sanitized)
        self.assertIn("PR 15G-C", markdown)
        self.assertNotIn(runner.TOOLING_ROOT, markdown)


if __name__ == "__main__":
    unittest.main()
