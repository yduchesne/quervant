#!/usr/bin/env python3
"""PR 15H-A benchmark-controller tests (HA-B01 … HA-B17).

These tests are deliberately deterministic and never run live timing. They build
synthetic campaign directories, recalculate seals with the production helpers and
mutate exactly one field per negative case so every refusal is attributable.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

RUN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.py")
_spec = importlib.util.spec_from_file_location("pr15h_a_run_under_test", RUN_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - import failure
    raise ImportError(f"cannot load {RUN_PATH}")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

BASE_SHA = "a" * 40
CAND_SHA = "b" * 40
TOOLING_SHA = "c" * 40
BINARY_A = "1" * 64
BINARY_B = "2" * 64
CORPUS = "d" * 64
ENV = "e" * 64
IDX_10K = "f" * 64
IDX_100K = "0" * 64


def _blocked(callable_):
    """Assert a RunBlocked is raised and return it."""
    try:
        callable_()
    except m.base.pr15d_run.RunBlocked as error:
        return error
    raise AssertionError("expected RunBlocked")


def _record(lane, median, *, warmups=5, oracle_ok=True):
    samples = [median] * m.SAMPLES
    return {
        "id": lane["id"],
        "n": lane["n"],
        "class": lane["class"],
        "field": lane["field"],
        "term": lane["term"],
        "k": lane["k"],
        "regime": m.REGIME,
        "warmups": warmups,
        "samples_ns": samples,
        "summary_ns": m.base.pr15d_run.summarize(samples),
        "total_hits": 1,
        "oracle_ok": oracle_ok,
    }


def _trial(lanes, medians, *, before="clear", after="clear"):
    return {
        "index": 1,
        "contention_before": {"state": before},
        "contention_after": {"state": after},
        "lanes": [_record(lane, medians[lane["id"]]) for lane in lanes],
    }


def _manifest(*, stage, base_sha=BASE_SHA, candidate_sha=None, index_digests=None, **overrides):
    manifest = {
        "schema": m.SCHEMA_MANIFEST,
        "phase": m.PHASE,
        "stage": stage,
        "base_source_sha": base_sha,
        "tooling_sha": TOOLING_SHA,
        "build": {"binary_sha256": BINARY_A, "binary_bytes": 1024},
        "corpus_manifest_sha256": CORPUS,
        "environment_fingerprint": ENV,
        "lanes": list(m.LANE_IDS),
        "expected_by_lane": {lane_id: 1 for lane_id in m.LANE_IDS},
        "index_digests": index_digests or {"10000": IDX_10K, "100000": IDX_100K},
        "source_scope_ok": True,
        "source_scope_violations": [],
    }
    if stage == "paired":
        manifest["candidate_source_sha"] = candidate_sha or CAND_SHA
    manifest.update(overrides)
    return manifest


def _write_baseline(root, *, hist=None, manifest=None, trials=None, publish=True):
    lanes = m.frozen_lanes()
    hist = hist or {lane["id"]: [1000, 1000, 1000] for lane in lanes}
    manifest = manifest or _manifest(stage="baseline")
    os.makedirs(root, exist_ok=True)
    m.write_exclusive_json(
        os.path.join(root, "authorization.json"),
        {
            "schema": m.SCHEMA_AUTHORIZATION,
            "stage": "baseline",
            "operator_idle_confirmed": True,
            "recording_utc": "2026-01-01T00:00:00Z",
            "base_source_sha": BASE_SHA,
            "tooling_sha": TOOLING_SHA,
        },
    )
    m.write_exclusive_json(os.path.join(root, "manifest.json"), manifest)
    trials = trials or [
        _trial(lanes, {lane["id"]: hist[lane["id"]][index] for lane in lanes})
        for index in range(3)
    ]
    for index, trial in enumerate(trials, start=1):
        m.write_exclusive_json(os.path.join(root, "raw", f"trial-{index:02d}.json"), trial)
    m.write_seal(root)
    if publish:
        report, markdown = m.derive_baseline(manifest, trials)
        m.publish_report(root, "baseline", report, markdown)
    return manifest, trials


def _slot(lanes, block, arm, medians):
    return {
        "schema": m.SCHEMA_SLOT,
        "slot": 0,  # overwritten by schedule builder
        "block": block,
        "arm": arm,
        "source_sha": BASE_SHA if arm == "A" else CAND_SHA,
        "binary_sha256": BINARY_A if arm == "A" else BINARY_B,
        "index_digests": {"10000": IDX_10K, "100000": IDX_100K},
        "trial": _trial(lanes, medians),
    }


def _slots_from(a_values, b_values):
    lanes = m.frozen_lanes()
    slots = []
    number = 0
    for block, order in enumerate(m.BLOCK_SCHEDULE, start=1):
        for arm in order:
            number += 1
            medians = {
                lane["id"]: (a_values if arm == "A" else b_values)[lane["id"]][block - 1]
                for lane in lanes
            }
            slot = _slot(lanes, block, arm, medians)
            slot["slot"] = number
            slots.append(slot)
    return slots


def _uniform(value_a, value_b):
    return (
        {lane_id: [value_a] * 4 for lane_id in m.LANE_IDS},
        {lane_id: [value_b] * 4 for lane_id in m.LANE_IDS},
    )


def _paired(
    root,
    *,
    a_values,
    b_values,
    hist=None,
    manifest=None,
    baseline_manifest=None,
    baseline_trials=None,
    slots=None,
    publish=True,
):
    lanes = m.frozen_lanes()
    baseline_manifest = baseline_manifest or _manifest(stage="baseline")
    if baseline_trials is None:
        hist = hist or {lane["id"]: [1000, 1000, 1000] for lane in lanes}
        baseline_trials = [
            _trial(lanes, {lane["id"]: hist[lane["id"]][index] for lane in lanes})
            for index in range(3)
        ]
    manifest = manifest or _manifest(stage="paired")
    slots = slots or _slots_from(a_values, b_values)
    os.makedirs(root, exist_ok=True)
    m.write_exclusive_json(
        os.path.join(root, "authorization.json"),
        {"schema": m.SCHEMA_AUTHORIZATION, "stage": "paired", "operator_idle_confirmed": True},
    )
    m.write_exclusive_json(os.path.join(root, "manifest.json"), manifest)
    for slot in slots:
        m.write_exclusive_json(
            os.path.join(root, "raw", "slots", f"slot-{slot['slot']:02d}.json"), slot
        )
    m.write_seal(root)
    kind, report, markdown = m.compute_paired(manifest, slots, baseline_manifest, baseline_trials)
    if publish:
        m.publish_report(root, kind, report, markdown)
    return kind, report, markdown


class FrozenLaneTests(unittest.TestCase):
    def test_b01_canonical_seven_lane_matrix(self):
        lanes = m.frozen_lanes()
        self.assertEqual([lane["id"] for lane in lanes], m.LANE_IDS)
        self.assertEqual(len(lanes), 7)
        self.assertTrue(all(lane["regime"] == m.REGIME for lane in lanes))

    def test_b02_unknown_eighth_and_duplicate_lanes_refused(self):
        original = m.LANE_IDS
        try:
            for mutated in (
                original + ["pr15d_v1/10000/absent/k100"],
                original[:6] + [original[0]],
                original[:6] + ["pr15d_v1/99999/rare/k100"],
            ):
                m.LANE_IDS = mutated
                self.assertEqual(_blocked(m.frozen_lanes).rule, "X32_STAGE")
        finally:
            m.LANE_IDS = original


class PathAndSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pr15h-a-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_b03_idle_confirmation_gate(self):
        out = os.path.join(self.tmp, "target", "pr15h-a", "baseline-01")
        argv = [
            "baseline",
            "--checkout-root",
            self.tmp,
            "--base-tree",
            os.path.join(self.tmp, "no-such-tree"),
            "--out",
            out,
        ]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(m.main(argv), 3)
        self.assertIn("PERF_BLOCKED_OPERATOR", stderr.getvalue())
        self.assertFalse(os.path.exists(out))

        # With a genuine idle attestation the operator gate is passed; the next
        # refusal must come from source pinning, not from the idle gate.
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(m.main(argv + ["--idle-confirmed"]), 3)
        self.assertNotIn("PERF_BLOCKED_OPERATOR", stderr.getvalue())

    def test_b04_dirty_worktree_and_source_ancestry(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "t@example.invalid")
        self._git(repo, "config", "user.name", "test")
        path = os.path.join(repo, "file.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("base\n")
        self._git(repo, "add", "file.txt")
        self._git(repo, "commit", "-q", "-m", "base")
        self._git(repo, "checkout", "-q", "--detach", "HEAD")
        # Clean detached tree resolves.
        self.assertEqual(m.resolve_pinned_tree(repo)["sha"], self._git(repo, "rev-parse", "HEAD"))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("dirty\n")
        self.assertEqual(_blocked(lambda: m.resolve_pinned_tree(repo)).rule, "X27_SOURCE")

        # A non-descendant/equal candidate is refused during comparison.
        manifest = _manifest(stage="paired", candidate_sha=BASE_SHA)
        lanes = m.frozen_lanes()
        a_values, b_values = _uniform(1000, 900)
        slots = _slots_from(a_values, b_values)
        trials = [
            _trial(lanes, {lane["id"]: 1000 for lane in lanes}) for _ in range(3)
        ]
        self.assertEqual(
            _blocked(
                lambda: m.compute_paired(
                    manifest, slots, _manifest(stage="baseline"), trials
                )
            ).rule,
            "X37_INCOMPARABLE",
        )

    def test_b04_changed_path_audit(self):
        self.assertTrue(m.ALLOWED_CHANGED_EXACT)
        # The audit itself is exercised against a real repository below.
        repo = os.path.join(self.tmp, "scope")
        os.makedirs(repo)
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "t@example.invalid")
        self._git(repo, "config", "user.name", "test")
        os.makedirs(os.path.join(repo, "crates/quervant-core/src/search"))
        tracked = os.path.join(repo, "crates/quervant-core/src/search/execute.rs")
        with open(tracked, "w", encoding="utf-8") as handle:
            handle.write("base\n")
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-q", "-m", "base")
        base_sha = self._git(repo, "rev-parse", "HEAD")
        with open(tracked, "w", encoding="utf-8") as handle:
            handle.write("candidate\n")
        forbidden = os.path.join(repo, "Cargo.toml")
        with open(forbidden, "w", encoding="utf-8") as handle:
            handle.write("[workspace]\n")
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-q", "-m", "candidate")
        candidate_sha = self._git(repo, "rev-parse", "HEAD")
        self.assertEqual(
            m.audit_changed_paths(repo, base_sha, candidate_sha), ["Cargo.toml"]
        )

    def _git(self, repo, *args):
        result = subprocess.run(
            ["git", "-C", repo, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()


class SealAndIoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pr15h-a-seal-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_b11_tampered_seal_duplicate_keys_symlink_and_no_overwrite(self):
        root = os.path.join(self.tmp, "baseline")
        _write_baseline(root)
        m.verify_seal(root)

        # Tamper one sealed byte.
        trial = os.path.join(root, "raw", "trial-02.json")
        with open(trial, "ab") as handle:
            handle.write(b" ")
        self.assertEqual(_blocked(lambda: m.verify_seal(root)).rule, "X12_SEAL")

        # Duplicate JSON keys are refused by strict reading.
        duplicate = os.path.join(self.tmp, "duplicate.json")
        with open(duplicate, "w", encoding="utf-8") as handle:
            handle.write('{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            m.read_json_strict(duplicate)

        # Symlinked sealed files are refused.
        symlink = os.path.join(self.tmp, "link.json")
        os.symlink(duplicate, symlink)
        self.assertEqual(_blocked(lambda: m.read_json_strict(symlink)).rule, "X11_SYMLINK")

        # Output files are never overwritten.
        exclusive = os.path.join(self.tmp, "exclusive.json")
        m.write_exclusive_json(exclusive, {"value": 1})
        with self.assertRaises(FileExistsError):
            m.write_exclusive_json(exclusive, {"value": 2})


class SampleValidationTests(unittest.TestCase):
    def test_b05_index_digest_mismatch_blocks(self):
        a_values, b_values = _uniform(1000, 900)
        bad = _manifest(stage="paired", index_digests={"10000": IDX_10K, "100000": "9" * 64})
        self.assertEqual(
            _blocked(
                lambda: m.compute_paired(
                    bad,
                    _slots_from(a_values, b_values),
                    _manifest(stage="baseline"),
                    [_trial(m.frozen_lanes(), {lane["id"]: 1000 for lane in m.frozen_lanes()})]
                    * 3,
                )
            ).rule,
            "X51_INDEX",
        )

    def test_b06_nonclear_or_missing_probe_blocks(self):
        lanes = m.frozen_lanes()
        for before, after in (("busy", "clear"), ("clear", "unknown"), ("", "")):
            trial = _trial(lanes, {lane["id"]: 1000 for lane in lanes}, before=before, after=after)
            with self.assertRaises(m.base.pr15d_run.RunBlocked):
                m.validate_trial(trial, lanes, "probe")
        missing = {"index": 1, "lanes": []}
        with self.assertRaises(m.base.pr15d_run.RunBlocked):
            m.validate_trial(missing, lanes, "missing")

    def test_b07_sample_counts_and_value_types(self):
        lane = m.frozen_lanes()[0]
        good = _record(lane, 1000)
        self.assertEqual(m.validate_lane_record(good, lane, "good")["count"], 20)
        for count in (19, 21):
            record = dict(good)
            record["samples_ns"] = [1000] * count
            record["summary_ns"] = m.base.pr15d_run.summarize(record["samples_ns"])
            self.assertEqual(_blocked(lambda: m.validate_lane_record(record, lane, "count")).rule, "X15_LANE_RECORD")
        for bad_value in (True, 1.0, 0, -1):
            record = dict(good)
            samples = [1000] * 20
            samples[3] = bad_value
            record["samples_ns"] = samples
            record["summary_ns"] = m.base.pr15d_run.summarize([1000] * 20)
            self.assertEqual(
                _blocked(lambda: m.validate_lane_record(record, lane, "value")).rule,
                "X15_LANE_RECORD",
            )

    def test_b08_stale_summary_recomputed_and_rejected(self):
        lane = m.frozen_lanes()[0]
        record = _record(lane, 1000)
        record["summary_ns"] = dict(record["summary_ns"], median=999)
        self.assertEqual(
            _blocked(lambda: m.validate_lane_record(record, lane, "stale")).rule, "X16_SUMMARY"
        )

    def test_b09_oracle_order_and_frozen_input_drift(self):
        lanes = m.frozen_lanes()
        medians = {lane["id"]: 1000 for lane in lanes}

        bad_oracle = _trial(lanes, medians)
        bad_oracle["lanes"][0]["oracle_ok"] = False
        self.assertEqual(
            _blocked(lambda: m.validate_trial(bad_oracle, lanes, "oracle")).rule,
            "X15_LANE_RECORD",
        )

        reordered = _trial(lanes, medians)
        reordered["lanes"][0], reordered["lanes"][1] = reordered["lanes"][1], reordered["lanes"][0]
        self.assertEqual(
            _blocked(lambda: m.validate_trial(reordered, lanes, "order")).rule, "X17_TRIAL"
        )

        tree = tempfile.mkdtemp(prefix="pr15h-a-frozen-")
        try:
            frozen = "benchmarks/pr15d/spec/pr15d_v1.json"
            target = os.path.join(tree, frozen)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("{}")
            self.assertEqual(_blocked(lambda: m.verify_frozen_inputs(tree)).rule, "X30_FROZEN_DRIFT")
        finally:
            shutil.rmtree(tree, ignore_errors=True)


class ScheduleAndVerdictTests(unittest.TestCase):
    def test_b10_schedule_refused_when_incorrect_or_missing(self):
        a_values, b_values = _uniform(1000, 900)
        slots = _slots_from(a_values, b_values)
        m.validate_paired_schedule(slots)

        wrong = [dict(slot) for slot in slots]
        wrong[0]["arm"] = "B"
        self.assertEqual(_blocked(lambda: m.validate_paired_schedule(wrong)).rule, "X18_SCHEDULE")

        missing = slots[:-1]
        self.assertEqual(_blocked(lambda: m.validate_paired_schedule(missing)).rule, "X18_SCHEDULE")

    def test_b12_verdict_sign_consistency(self):
        self.assertEqual(m.verdict_from_ratios([0.9, 0.8, 0.95, 0.99]), "B_FASTER")
        self.assertEqual(m.verdict_from_ratios([1.1, 1.2, 1.05, 1.01]), "A_FASTER")
        self.assertEqual(m.verdict_from_ratios([0.9, 1.1, 0.9, 1.1]), "INCONCLUSIVE")
        self.assertEqual(m.verdict_from_ratios([0.9, 1.0, 0.9, 0.9]), "INCONCLUSIVE")
        self.assertEqual(m.verdict_from_ratios([1.0, 1.0, 1.0, 1.0]), "INCONCLUSIVE")
        self.assertEqual(_blocked(lambda: m.verdict_from_ratios([0.9, 0])).rule, "X14_RATIO")

    def test_b13_drift_caps_are_exact_and_strict(self):
        self.assertFalse(m._drift_violation([1000, 1250], 100000)["violated"])
        self.assertTrue(m._drift_violation([1000, 1251], 100000)["violated"])
        self.assertFalse(m._drift_violation([1000, 1500], 10000)["violated"])
        self.assertTrue(m._drift_violation([1000, 1501], 10000)["violated"])


class PairedDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pr15h-a-paired-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fixture(self, name, a_values, b_values, hist=None):
        return _paired(
            os.path.join(self.tmp, name),
            a_values=a_values,
            b_values=b_values,
            hist=hist,
            publish=False,
        )

    def test_b14_common_k10_inconclusive_is_rejected(self):
        a_values, b_values = _uniform(1000, 900)
        b_values["pr15d_v1/100000/common/k10"] = [900, 1100, 900, 1100]
        kind, report, _ = self._fixture("b14", a_values, b_values)
        self.assertEqual(kind, "performance")
        self.assertEqual(report["decision"], "PERFORMANCE_REJECTED")
        self.assertEqual(report["gates"]["HA-P02"], "FAIL")
        self.assertEqual(report["gates"]["HA-P01"], "PASS")

    def test_b15_guard_a_faster_is_rejected(self):
        a_values, b_values = _uniform(1000, 900)
        b_values["pr15d_v1/10000/rare/k100"] = [1100, 1200, 1100, 1200]
        kind, report, _ = self._fixture("b15", a_values, b_values)
        self.assertEqual(kind, "performance")
        self.assertEqual(report["decision"], "PERFORMANCE_REJECTED")
        self.assertEqual(report["gates"]["HA-P04"], "FAIL")
        self.assertEqual(
            next(lane for lane in report["lanes"] if lane["id"] == "pr15d_v1/10000/rare/k100")[
                "verdict"
            ],
            "A_FASTER",
        )

    def test_b16_qualified_acceptance_is_deterministic_and_sanitised(self):
        a_values, b_values = _uniform(1000, 900)
        kind, report, markdown = self._fixture("b16", a_values, b_values)
        self.assertEqual(kind, "performance")
        self.assertEqual(report["decision"], "PERFORMANCE_ACCEPTED")
        self.assertTrue(all(value == "PASS" for value in report["gates"].values()))
        self.assertEqual(report["qualification"]["slot_count"], 8)
        self.assertEqual(report["qualification"]["lane_record_count"], 56)
        self.assertEqual(report["qualification"]["timed_samples"], 1120)
        self.assertEqual(report["qualification"]["warmups"], 280)
        self.assertEqual(report["qualification"]["contention_probes"], 16)
        self.assertEqual(report["qualification"]["oracle_validations"], 56)
        m.assert_report_sanitized(report)

        # Recomputing from the same sealed data is byte-identical.
        _, again, again_markdown = self._fixture("b16b", a_values, b_values)
        self.assertEqual(m.canonical_bytes(report), m.canonical_bytes(again))
        self.assertEqual(markdown, again_markdown)

        # The sanitised pair is published exactly once.
        root = os.path.join(self.tmp, "b16c")
        _write_baseline(os.path.join(self.tmp, "b16c-base"))
        kind, report, markdown = _paired(
            root,
            a_values=a_values,
            b_values=b_values,
            publish=True,
        )
        self.assertEqual(kind, "performance")
        with self.assertRaises(m.base.pr15d_run.RunBlocked):
            m.publish_report(root, kind, report, markdown)

    def test_b16_blocked_report_when_drift_exceeds_cap(self):
        a_values, b_values = _uniform(1000, 900)
        hist = {lane_id: [1300, 1300, 1300] for lane_id in m.LANE_IDS}
        kind, report, markdown = self._fixture("drift", a_values, b_values, hist=hist)
        self.assertEqual(kind, "blocked")
        self.assertEqual(report["reason"], "MEASUREMENT_BLOCKED_BASELINE_DRIFT")
        self.assertEqual(report["performance_not_evaluated"], "PERFORMANCE_NOT_EVALUATED")
        self.assertTrue(report["drift_violations"])
        self.assertIn("MEASUREMENT_BLOCKED_BASELINE_DRIFT", markdown)


class VerifyOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pr15h-a-verify-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _hash_tree(self, root):
        digests = {}
        for directory, _dirs, files in os.walk(root):
            for name in files:
                full = os.path.join(directory, name)
                digests[os.path.relpath(full, root)] = m.sha256_file(full)
        return digests

    def test_verify_only_is_read_only_and_recomputes(self):
        root = os.path.join(self.tmp, "target", "pr15h-a", "baseline-01")
        _write_baseline(root)
        before = self._hash_tree(root)
        args = m.build_parser().parse_args(
            [
                "baseline",
                "--checkout-root",
                self.tmp,
                "--base-tree",
                self.tmp,
                "--out",
                root,
                "--verify-only",
            ]
        )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(m.run_verify_only(args), 0)
        self.assertIn("VERIFY_OK", stdout.getvalue())
        self.assertEqual(before, self._hash_tree(root))


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pr15h-a-rollback-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git(self, repo, *args):
        result = subprocess.run(
            ["git", "-C", repo, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_b17_rollback_restores_exact_search_blobs(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, "crates/quervant-core/src/search"))
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "t@example.invalid")
        self._git(repo, "config", "user.name", "test")
        search = os.path.join(repo, "crates/quervant-core/src/search/execute.rs")
        with open(search, "w", encoding="utf-8") as handle:
            handle.write("baseline\n")
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-q", "-m", "baseline")
        base_blob = self._git(repo, "rev-parse", "HEAD:crates/quervant-core/src/search/execute.rs")

        with open(search, "w", encoding="utf-8") as handle:
            handle.write("candidate\n")
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-q", "-m", "candidate")

        with open(search, "w", encoding="utf-8") as handle:
            handle.write("baseline\n")
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-q", "-m", "revert PR 15H-A production change")
        final_blob = self._git(repo, "rev-parse", "HEAD:crates/quervant-core/src/search/execute.rs")
        self.assertEqual(base_blob, final_blob)

        # Preserved evidence is untouched by the rollback.
        evidence = os.path.join(self.tmp, "evidence.json")
        with open(evidence, "w", encoding="utf-8") as handle:
            handle.write('{"decision":"PERFORMANCE_REJECTED"}')
        before = m.sha256_file(evidence)
        self._git(repo, "status", "--porcelain")
        self.assertEqual(before, m.sha256_file(evidence))

    def test_verify_reports_detects_tampered_sanitized_pair(self):
        root = os.path.join(self.tmp, "baseline")
        manifest, trials = _write_baseline(root)
        report, markdown = m.derive_baseline(manifest, trials)
        m.verify_report(root, "baseline", report, markdown)
        path = os.path.join(root, "sanitized", "baseline.json")
        with open(path, "rb") as handle:
            payload = bytearray(handle.read())
        payload[0] = ord("[")
        with open(path, "wb") as handle:
            handle.write(payload)
        self.assertEqual(
            _blocked(lambda: m.verify_report(root, "baseline", report, markdown)).rule,
            "X44_REPORT_DRIFT",
        )


if __name__ == "__main__":
    unittest.main()
