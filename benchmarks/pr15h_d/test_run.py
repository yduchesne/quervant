#!/usr/bin/env python3
"""PR 15H-C controller tests (C-derived; HC-T IDs). Deterministic, no live timing."""

from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
import unittest
from unittest import mock

RUN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.py")
_spec = importlib.util.spec_from_file_location("pr15h_d_run_under_test", RUN_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load {RUN_PATH}")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

BASE = m.ARM_A_SHA
CAND = "c" * 40
TOOLING = "d" * 40
ENV = "e" * 64
CORPUS = "f" * 64
IDX = {"10000": "1" * 64, "100000": "2" * 64}
BIN = {"A": "3" * 64, "B": "4" * 64}
MS = 1_000_000


def _blocked(callable_):
    try:
        callable_()
    except m.RunBlocked as error:
        return error
    raise AssertionError("expected RunBlocked")


def _uniform(value):
    return {lane_id: value for lane_id in m.LANE_IDS}


def _record(lane, median):
    samples = [median] * m.SAMPLES
    return {
        "id": lane["id"],
        "n": lane["n"],
        "class": lane["class"],
        "field": lane["field"],
        "term": lane["term"],
        "k": lane["k"],
        "regime": m.REGIME,
        "warmups": m.WARMUPS,
        "samples_ns": samples,
        "summary_ns": m.ha.base.pr15d_run.summarize(samples),
        "total_hits": 1,
        "doc_ids": ["d0"],
        "expected_doc_ids": ["d0"],
        "oracle_ok": True,
    }


def _trial(lanes, medians, *, before="clear", after="clear"):
    return {
        "index": 1,
        "contention_before": {"state": before},
        "contention_after": {"state": after},
        "lanes": [_record(lane, medians[lane["id"]]) for lane in lanes],
    }


def _arms():
    return {
        "A": {"source_sha": BASE, "binary_sha256": BIN["A"], "index_digests": IDX},
        "B": {"source_sha": CAND, "binary_sha256": BIN["B"], "index_digests": IDX},
    }


def _manifest(*, env=ENV, corpus=CORPUS, arms=None):
    arms = arms or _arms()
    return {
        "schema": m.SCHEMA_MANIFEST,
        "stage": "paired",
        "phase": m.PHASE,
        "base_source_sha": BASE,
        "candidate_source_sha": CAND,
        "tooling_sha": TOOLING,
        "environment_fingerprint": env,
        "corpus_manifest_sha256": corpus,
        "lanes": list(m.LANE_IDS),
        "expected_by_lane": {lane_id: 1 for lane_id in m.LANE_IDS},
        "schedule": [list(order) for order in m.BLOCK_SCHEDULE],
        "arms": arms,
    }


def _slot(number, block, arm, arms, medians, *, before="clear", after="clear"):
    meta = arms[arm]
    return {
        "schema": m.SCHEMA_SLOT,
        "stage": "paired",
        "slot": number,
        "block": block,
        "arm": arm,
        "source_sha": meta["source_sha"],
        "binary_sha256": meta["binary_sha256"],
        "index_digests": meta["index_digests"],
        "trial": _trial(m.frozen_lanes(), medians, before=before, after=after),
    }


def _paired_slots(a_values, b_values, arms=None):
    arms = arms or _arms()
    slots = []
    number = 0
    for block, order in enumerate(m.BLOCK_SCHEDULE, 1):
        for arm in order:
            number += 1
            source = a_values if arm == "A" else b_values
            slots.append(_slot(number, block, arm, arms, source[block - 1]))
    return slots


def _accepted_values():
    a = [_uniform(50 * MS) for _ in range(4)]
    b = []
    for _ in range(4):
        values = {lane_id: 50 * MS for lane_id in m.LANE_IDS}
        values[m.P1] = 50 * MS - 2_500_000
        values[m.P2] = 50 * MS - 2_500_000
        values[m.P3] = 50 * MS - 500_000
        values[m.G1] = 50 * MS - 300_000
        values[m.G2] = 50 * MS + 200_000
        values[m.G3] = 50 * MS + 200_000
        b.append(values)
    return a, b


def _baseline_manifest():
    return {
        "schema": m.SCHEMA_MANIFEST,
        "stage": "baseline",
        "phase": m.PHASE,
        "base_source_sha": BASE,
        "tooling_sha": TOOLING,
        "environment_fingerprint": ENV,
        "corpus_manifest_sha256": CORPUS,
        "lanes": list(m.LANE_IDS),
        "expected_by_lane": {lane_id: 1 for lane_id in m.LANE_IDS},
    }


class LaneAndPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pr15h-d-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_b01_six_exact_lanes(self):
        lanes = m.frozen_lanes()
        self.assertEqual([lane["id"] for lane in lanes], list(m.LANE_IDS))
        self.assertEqual(len(lanes), 6)
        self.assertTrue(all(lane["regime"] == "warm" for lane in lanes))

    def test_b01_extra_missing_or_reordered_lane_rejected(self):
        original = m.LANE_IDS
        try:
            for mutated in (
                original + ["pr15d_v1/10000/absent/k100"],
                original[:-1],
                [original[1], original[0]] + original[2:],
            ):
                m.LANE_IDS = mutated
                self.assertEqual(_blocked(m.frozen_lanes).rule, "X_LANE_SET")
        finally:
            m.LANE_IDS = original

    def test_b08_native_and_mounted_paths(self):
        root = os.path.join(self.tmp, "target", "pr15h-d")
        fresh = os.path.join(root, "baseline-01")
        self.assertEqual(m.validate_out_path(fresh, self.tmp), os.path.realpath(fresh))
        os.makedirs(fresh)
        self.assertEqual(_blocked(lambda: m.validate_out_path(fresh, self.tmp)).rule, "X_OUT_EXISTS")
        outside = os.path.join(self.tmp, "elsewhere")
        self.assertEqual(_blocked(lambda: m.validate_out_path(outside, self.tmp)).rule, "X_PATH")
        symlink = os.path.join(root, "link-01")
        os.symlink(fresh, symlink)
        self.assertEqual(_blocked(lambda: m.validate_out_path(symlink, self.tmp)).rule, "X_SYMLINK")
        mounted = "/mnt/c/not-native"
        self.assertEqual(_blocked(lambda: m.validate_out_path(mounted, self.tmp)).rule, "X_PATH")

    def test_b21_duplicate_json_keys(self):
        path = os.path.join(self.tmp, "duplicate.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            m.ha.read_json_strict(path)


class ScheduleTests(unittest.TestCase):
    def test_b05_b06_b07_schedule(self):
        a, b = _accepted_values()
        slots = _paired_slots(a, b)
        self.assertEqual(m.validate_schedule(slots), None)
        self.assertEqual(_blocked(lambda: m.validate_schedule(slots[:-1])).rule, "X_SCHEDULE")
        swapped = [dict(slot) for slot in slots]
        swapped[0]["arm"] = "B"
        self.assertEqual(_blocked(lambda: m.validate_schedule(swapped)).rule, "X_SCHEDULE")
        duplicate = [dict(slot) for slot in slots]
        duplicate[1]["slot"] = 1
        self.assertEqual(_blocked(lambda: m.validate_schedule(duplicate)).rule, "X_SCHEDULE")

    def test_b06_missing_sample_or_oracle_rejected(self):
        a, b = _accepted_values()
        slots = _paired_slots(a, b)
        first = dict(slots[0])
        trial = dict(first["trial"])
        records = [dict(record) for record in trial["lanes"]]
        records[0]["samples_ns"] = records[0]["samples_ns"][:-1]
        trial["lanes"] = records
        first["trial"] = trial
        self.assertEqual(
            _blocked(lambda: m.validate_slot(first, m.frozen_lanes(), "paired")).rule,
            "X15_LANE_RECORD",
        )
        records[0]["samples_ns"] = [1000] * m.SAMPLES
        records[0]["summary_ns"] = dict(records[0]["summary_ns"], median=1)
        trial["lanes"] = records
        first["trial"] = trial
        self.assertEqual(
            _blocked(lambda: m.validate_slot(first, m.frozen_lanes(), "paired")).rule,
            "X16_SUMMARY",
        )


class GateMathTests(unittest.TestCase):
    def test_d_primary_and_guard_boundaries(self):
        self.assertTrue(m.primary_lane_gate([2 * MS] * 4)["strong_pass"])
        self.assertFalse(m.primary_lane_gate([1_999_999] * 4)["strong_pass"])
        self.assertTrue(m.primary_lane_gate([3 * MS, 3 * MS, 3 * MS, -1 * MS])["strong_pass"])
        self.assertFalse(m.primary_lane_gate([2 * MS, 2 * MS, 0, 0])["strong_pass"])
        self.assertTrue(m.primary_lane_gate([500_000] * 4)["support_pass"])
        self.assertTrue(m.primary_lane_gate([-750_000] * 4)["support_pass"])
        self.assertFalse(m.primary_lane_gate([-750_001] * 4)["support_pass"])
        self.assertFalse(
            m.primary_lane_gate([2 * MS, 2 * MS, 2 * MS, -2_000_001])["support_pass"]
        )
        self.assertTrue(m.guard_lane_gate([-750_000] * 4, m.D_G1_MIN_NS)["passes"])
        self.assertFalse(m.guard_lane_gate([-750_001] * 4, m.D_G1_MIN_NS)["passes"])
        self.assertTrue(m.guard_lane_gate([-250_000] * 4, m.D_SPARSE_MIN_NS)["passes"])
        self.assertFalse(m.guard_lane_gate([-250_001] * 4, m.D_SPARSE_MIN_NS)["passes"])
        self.assertFalse(
            m.guard_lane_gate([-1_000_001, 0, 0, 0], m.D_SPARSE_MIN_NS)["passes"]
        )
        self.assertEqual(m.median_of_four([1, 2, 3, 4]), 2)
        self.assertEqual(m.conventional_median_of_four([1, 2, 3, 4]), 2.5)


class PairedDecisionTests(unittest.TestCase):
    def test_d_accepted(self):
        a, b = _accepted_values()
        slots = _paired_slots(a, b)
        kind, report, _ = m.derive_paired(_manifest(), slots, _baseline_manifest())
        self.assertEqual(kind, "performance")
        self.assertEqual(report["decision"], "D_PASSED")
        self.assertTrue(all(value == "PASS" for value in report["gates"].values()))
        self.assertEqual(report["slot_count"], 8)
        self.assertEqual(report["lane_record_count"], 48)
        self.assertEqual(report["timed_samples"], 960)
        self.assertEqual(report["warmups"], 240)
        self.assertEqual(report["contention_probes"], 16)
        self.assertEqual(report["oracle_validations"], 48)

    def test_d_primary_below_2ms_rejected(self):
        a, b = _accepted_values()
        for index in range(4):
            b[index][m.P2] = a[index][m.P2] - 1_999_999
        kind, report, _ = m.derive_paired(_manifest(), _paired_slots(a, b), _baseline_manifest())
        self.assertEqual(report["decision"], "D_FAILED")
        self.assertEqual(report["gates"]["D-P01"], "FAIL")

    def test_d_p3_support_floor_rejected(self):
        a, b = _accepted_values()
        for index in range(4):
            b[index][m.P3] = a[index][m.P3] + 750_001
        kind, report, _ = m.derive_paired(_manifest(), _paired_slots(a, b), _baseline_manifest())
        self.assertEqual(report["decision"], "D_FAILED")
        self.assertEqual(report["gates"]["D-P01"], "FAIL")

    def test_d_p3_block_floor_rejected(self):
        a, b = _accepted_values()
        b[0][m.P3] = a[0][m.P3] + 2_000_001
        kind, report, _ = m.derive_paired(_manifest(), _paired_slots(a, b), _baseline_manifest())
        self.assertEqual(report["decision"], "D_FAILED")
        self.assertEqual(report["gates"]["D-P01"], "FAIL")

    def test_d_g1_exact_floor(self):
        a, b = _accepted_values()
        for index in range(4):
            b[index][m.G1] = a[index][m.G1] + 750_000
        kind, report, _ = m.derive_paired(_manifest(), _paired_slots(a, b), _baseline_manifest())
        self.assertEqual(report["decision"], "D_PASSED")
        for index in range(4):
            b[index][m.G1] = a[index][m.G1] + 750_001
        kind, report, _ = m.derive_paired(_manifest(), _paired_slots(a, b), _baseline_manifest())
        self.assertEqual(report["gates"]["D-P02"], "FAIL")

    def test_d_sparse_floors(self):
        a, b = _accepted_values()
        for index in range(4):
            b[index][m.G2] = a[index][m.G2] + 250_000
            b[index][m.G3] = a[index][m.G3] + 250_000
        kind, report, _ = m.derive_paired(_manifest(), _paired_slots(a, b), _baseline_manifest())
        self.assertEqual(report["decision"], "D_PASSED")
        for index in range(4):
            b[index][m.G2] = a[index][m.G2] + 250_001
        kind, report, _ = m.derive_paired(_manifest(), _paired_slots(a, b), _baseline_manifest())
        self.assertEqual(report["gates"]["D-P02"], "FAIL")
        b[0][m.G2] = a[0][m.G2] - 1_000_001
        kind, report, _ = m.derive_paired(_manifest(), _paired_slots(a, b), _baseline_manifest())
        self.assertEqual(report["gates"]["D-P02"], "FAIL")

    def test_d_nonclear_probe_blocks(self):
        a, b = _accepted_values()
        slots = _paired_slots(a, b)
        first = dict(slots[0])
        trial = dict(first["trial"])
        trial["contention_before"] = {"state": "busy"}
        first["trial"] = trial
        kind, report, _ = m.derive_paired(_manifest(), [first] + slots[1:], _baseline_manifest())
        self.assertEqual(kind, "blocked")
        self.assertEqual(report["performance_verdict"], "NOT_EVALUATED")

    def test_d_identity_mismatch_blocks(self):
        a, b = _accepted_values()
        slots = _paired_slots(a, b)
        for manifest in (_manifest(env="0" * 64), _manifest(corpus="0" * 64)):
            kind, _, _ = m.derive_paired(manifest, slots, _baseline_manifest())
            self.assertEqual(kind, "blocked")
        arms = _arms()
        arms["B"]["index_digests"] = {"10000": IDX["10000"], "100000": "9" * 64}
        kind, _, _ = m.derive_paired(
            _manifest(arms=arms), _paired_slots(a, b, arms=arms), _baseline_manifest()
        )
        self.assertEqual(kind, "blocked")


def _write_baseline(root):
    os.makedirs(root)
    lanes = m.frozen_lanes()
    m.ha.write_exclusive_json(
        os.path.join(root, "authorization.json"), {"schema": m.SCHEMA_AUTHORIZATION}
    )
    m.ha.write_exclusive_json(os.path.join(root, "manifest.json"), _baseline_manifest())
    for index in range(1, m.TRIALS + 1):
        m.ha.write_exclusive_json(
            os.path.join(root, "raw", f"trial-{index:02d}.json"),
            _trial(lanes, _uniform(50 * MS)),
        )
    m.write_seal(root, "baseline")


class SealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pr15h-d-seal-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_b04_b22_seal_and_verify(self):
        root = os.path.join(self.tmp, "target", "pr15h-d", "paired-01")
        baseline_root = os.path.join(self.tmp, "target", "pr15h-d", "baseline-01")
        _write_baseline(baseline_root)
        os.makedirs(root)
        a, b = _accepted_values()
        slots = _paired_slots(a, b)
        manifest = _manifest()
        m.ha.write_exclusive_json(os.path.join(root, "authorization.json"), {"schema": m.SCHEMA_AUTHORIZATION})
        m.ha.write_exclusive_json(os.path.join(root, "manifest.json"), manifest)
        for slot in slots:
            m.ha.write_exclusive_json(os.path.join(root, "raw", "slots", f"slot-{slot['slot']:02d}.json"), slot)
        m.write_seal(root, "paired")
        kind, report, markdown = m.derive_paired(manifest, slots, _baseline_manifest())
        m.publish_report(root, kind, report, markdown)
        from types import SimpleNamespace

        args = SimpleNamespace(
            checkout_root=self.tmp,
            campaign=root,
            baseline=baseline_root,
            confirmation_of=None,
        )
        self.assertEqual(m.verify_campaign(args), 0)
        # Tamper one raw byte.
        with open(os.path.join(root, "raw", "slots", "slot-01.json"), "ab") as handle:
            handle.write(b" ")
        self.assertEqual(_blocked(lambda: m.verify_seal(root, "paired")).rule, "X_SEAL")

    def test_b21_b27_report_overwrite_refused(self):
        root = os.path.join(self.tmp, "target", "pr15h-d", "paired-02")
        os.makedirs(root)
        a, b = _accepted_values()
        slots = _paired_slots(a, b)
        manifest = _manifest()
        m.ha.write_exclusive_json(os.path.join(root, "authorization.json"), {"schema": m.SCHEMA_AUTHORIZATION})
        m.ha.write_exclusive_json(os.path.join(root, "manifest.json"), manifest)
        for slot in slots:
            m.ha.write_exclusive_json(os.path.join(root, "raw", "slots", f"slot-{slot['slot']:02d}.json"), slot)
        m.write_seal(root, "paired")
        kind, report, markdown = m.derive_paired(manifest, slots, _baseline_manifest())
        m.publish_report(root, kind, report, markdown)
        with self.assertRaises(m.RunBlocked) as caught:
            m.publish_report(root, kind, report, markdown)
        self.assertEqual(caught.exception.rule, "X_REPORT_EXISTS")


class ScopeAndSanitizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pr15h-d-scope-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_b19_scope_allowlist(self):
        self.assertIn("crates/quervant-core/src/search/unified.rs", m.A_ALLOWED_CHANGED_EXACT)
        self.assertNotIn("crates/quervant-core/src/search/execute.rs", m.A_ALLOWED_CHANGED_EXACT)
        self.assertNotIn("crates/quervant-core/src/search/score.rs", m.A_ALLOWED_CHANGED_EXACT)
        self.assertEqual(
            tuple(m.A_ALLOWED_CHANGED_PREFIXES),
            ("benchmarks/pr15h_d/", "docs/pr-artifacts/pr-15h-d/"),
        )

    def test_b27_sanitizer_refuses_private_material(self):
        self.assertEqual(
            _blocked(lambda: m.ha.assert_report_sanitized({"path": "/home/x"})).rule,
            "X42_SENSITIVE_REPORT",
        )
        m.ha.assert_report_sanitized({"lane": m.P1})

    def test_b20_existing_campaign_dir_refused(self):
        root = os.path.join(self.tmp, "target", "pr15h-d")
        os.makedirs(root)
        existing = os.path.join(root, "baseline-01")
        os.makedirs(existing)
        self.assertEqual(_blocked(lambda: m.validate_out_path(existing, self.tmp)).rule, "X_OUT_EXISTS")


class FixupToolingIdentityTests(unittest.TestCase):
    """BF-T01 … BF-T07 — sealed tooling identity enforcement."""

    def test_bf_t01_matching_tooling_accepted(self):
        self.assertIsNone(m.require_same_tooling(TOOLING, _baseline_manifest()))

    def test_bf_t02_different_tooling_rejected(self):
        self.assertEqual(
            _blocked(lambda: m.require_same_tooling("a" * 40, _baseline_manifest())).rule,
            "X_TOOLING_SHA",
        )

    def test_bf_t03_missing_or_malformed_tooling_rejected(self):
        for value in (None, 42, "", "a" * 39, "A" * 40):
            self.assertEqual(
                _blocked(lambda: m.require_same_tooling(value, _baseline_manifest())).rule,
                "X_TOOLING_SHA",
            )
        baseline = _baseline_manifest()
        del baseline["tooling_sha"]
        self.assertEqual(
            _blocked(lambda: m.require_same_tooling(TOOLING, baseline)).rule,
            "X_TOOLING_SHA",
        )
        baseline = _baseline_manifest()
        baseline["tooling_sha"] = "not-a-sha"
        self.assertEqual(
            _blocked(lambda: m.require_same_tooling(TOOLING, baseline)).rule,
            "X_TOOLING_SHA",
        )

    def test_bf_t04_derive_rejects_mismatched_paired_tooling(self):
        a, b = _accepted_values()
        manifest = _manifest()
        manifest["tooling_sha"] = "a" * 40
        self.assertEqual(
            _blocked(
                lambda: m.derive_paired(manifest, _paired_slots(a, b), _baseline_manifest())
            ).rule,
            "X_TOOLING_SHA",
        )

    def test_bf_t05_derive_rejects_mismatched_or_missing_baseline_tooling(self):
        a, b = _accepted_values()
        slots = _paired_slots(a, b)
        baseline = _baseline_manifest()
        baseline["tooling_sha"] = "a" * 40
        self.assertEqual(
            _blocked(lambda: m.derive_paired(_manifest(), slots, baseline)).rule,
            "X_TOOLING_SHA",
        )
        missing = _baseline_manifest()
        del missing["tooling_sha"]
        self.assertEqual(
            _blocked(lambda: m.derive_paired(_manifest(), slots, missing)).rule,
            "X_TOOLING_SHA",
        )

    def test_bf_t06_matching_campaign_still_accepted(self):
        a, b = _accepted_values()
        kind, report, _ = m.derive_paired(_manifest(), _paired_slots(a, b), _baseline_manifest())
        self.assertEqual(kind, "performance")
        self.assertEqual(report["decision"], "D_PASSED")

    def test_bf_t07_run_paired_blocks_before_output_creation(self):
        baseline = _baseline_manifest()
        with (
            mock.patch.object(m.ha, "_assert_clean_tooling", return_value={"sha": "b" * 40}),
            mock.patch.object(m, "validate_out_path", return_value="/tmp/a3-out"),
            mock.patch.object(m, "validate_sealed_dir", return_value="/tmp/a3-baseline"),
            mock.patch.object(m.ha, "read_json_strict", return_value=baseline),
            mock.patch.object(m, "verify_seal", return_value={}),
            mock.patch.object(m.os, "makedirs") as makedirs,
        ):
            args = type(
                "Args",
                (),
                {
                    "idle_confirmed": True,
                    "out": "/tmp/a3-out",
                    "checkout_root": "/tmp/root",
                    "baseline": "/tmp/a3-baseline",
                    "base_tree": "/tmp/source-a",
                    "candidate_tree": "/tmp/source-b",
                    "confirmation_of": None,
                },
            )()
            self.assertEqual(_blocked(lambda: m.run_paired(args)).rule, "X_TOOLING_SHA")
            makedirs.assert_not_called()


class FixupSourceScopeTests(unittest.TestCase):
    """D source allowlist: only the two search files and D docs/tooling."""

    def test_d_actual_prefix_accepted(self):
        with mock.patch.object(
            m.ha.base, "git", return_value="docs/pr-artifacts/pr-15h-d/performance.md\n"
        ):
            self.assertTrue(m._source_scope_ok("/unused", BASE, CAND))

    def test_d_typo_prefix_rejected(self):
        with mock.patch.object(
            m.ha.base, "git", return_value="docs/pr-artifacts/pr15h-d/performance.md\n"
        ):
            self.assertFalse(m._source_scope_ok("/unused", BASE, CAND))

    def test_d_permitted_file_does_not_mask_forbidden(self):
        output = (
            "crates/quervant-core/src/search/unified.rs\n"
            "docs/pr-artifacts/pr-15h-a/performance.md\n"
        )
        with mock.patch.object(m.ha.base, "git", return_value=output):
            self.assertFalse(m._source_scope_ok("/unused", BASE, CAND))

    def test_d_forbidden_roots_rejected(self):
        for path in (
            "crates/quervant-core/src/segment/column.rs",
            "crates/quervant-core/src/segment/reader.rs",
            "crates/quervant-core/src/search/typed_compare.rs",
            "crates/quervant-core/src/search/execute.rs",
            "crates/quervant-core/src/search/score.rs",
            "Cargo.toml",
            ".github/workflows/ci.yml",
        ):
            with mock.patch.object(m.ha.base, "git", return_value=path + "\n"):
                self.assertFalse(m._source_scope_ok("/unused", BASE, CAND), path)

    def test_d_permitted_paths_accepted(self):
        for path in (
            "crates/quervant-core/src/search/unified.rs",
            "crates/quervant-core/src/search/unified_plan.rs",
            "benchmarks/pr15h_d/run.py",
            "docs/pr-artifacts/pr-15h-d/performance.md",
        ):
            with mock.patch.object(m.ha.base, "git", return_value=path + "\n"):
                self.assertTrue(m._source_scope_ok("/unused", BASE, CAND), path)


class CMedianClarificationTests(unittest.TestCase):
    """C-MEDIAN-LOWER: lower median gates; conventional median is informational."""

    def test_hc_median_lower_vs_conventional(self):
        cases = [
            ([-4_480_000, -4_273_000, 1_059_000, -1_642_000], -4_273_000, -2_957_500.0),
            ([-4_241_000, -954_000, 2_601_000, 1_644_000], -954_000, 345_000.0),
            ([-5_891_000, -4_067_000, 5_397_000, 583_000], -4_067_000, -1_742_000.0),
            ([-947_000, -822_000, 281_000, -293_000], -822_000, -557_500.0),
            ([-52_000, 1_000, 62_000, -37_000], -37_000, -18_000.0),
            ([-37_000, -20_000, 35_000, -26_000], -26_000, -23_000.0),
        ]
        for deltas, lower, conventional in cases:
            self.assertEqual(m.median_of_four(deltas), lower)
            self.assertEqual(m.conventional_median_of_four(deltas), conventional)
        # P2 is the decisive example: the two statistics have different signs.
        self.assertLess(m.median_of_four([-4_241_000, -954_000, 2_601_000, 1_644_000]), 0)
        self.assertGreater(
            m.conventional_median_of_four([-4_241_000, -954_000, 2_601_000, 1_644_000]), 0
        )


class CDThresholdTests(unittest.TestCase):
    """D-T01 … D-T20 controller coverage."""

    def test_dt01_lanes(self):
        self.assertEqual([lane["id"] for lane in m.frozen_lanes()], list(m.LANE_IDS))

    def test_dt02_schedule(self):
        a, b = _accepted_values()
        slots = _paired_slots(a, b)
        self.assertIsNone(m.validate_schedule(slots))
        self.assertEqual(_blocked(lambda: m.validate_schedule(slots[:-1])).rule, "X_SCHEDULE")

    def test_dt03_samples(self):
        lane = m.frozen_lanes()[0]
        record = _record(lane, 1000)
        self.assertEqual(m.ha.validate_lane_record(record, lane, "d")["count"], 20)
        broken = dict(record)
        broken["samples_ns"] = [1000] * 19
        broken["summary_ns"] = m.ha.base.pr15d_run.summarize([1000] * 19)
        self.assertEqual(
            _blocked(lambda: m.ha.validate_lane_record(broken, lane, "d")).rule,
            "X15_LANE_RECORD",
        )

    def test_dt04_dt05_tooling(self):
        self.assertIsNone(m.require_same_tooling("e" * 40, {"tooling_sha": "e" * 40}))
        for value in (None, "f" * 40, "E" * 40, ""):
            self.assertEqual(
                _blocked(lambda: m.require_same_tooling(value, {"tooling_sha": "e" * 40})).rule,
                "X_TOOLING_SHA",
            )

    def test_dt06_index_or_corpus(self):
        a, b = _accepted_values()
        arms = _arms()
        arms["B"]["index_digests"] = {"10000": IDX["10000"], "100000": "9" * 64}
        kind, _, _ = m.derive_paired(
            _manifest(arms=arms), _paired_slots(a, b, arms=arms), _baseline_manifest()
        )
        self.assertEqual(kind, "blocked")
        kind, _, _ = m.derive_paired(
            _manifest(corpus="0" * 64), _paired_slots(a, b), _baseline_manifest()
        )
        self.assertEqual(kind, "blocked")

    def test_dt07_host(self):
        a, b = _accepted_values()
        kind, _, _ = m.derive_paired(
            _manifest(env="0" * 64), _paired_slots(a, b), _baseline_manifest()
        )
        self.assertEqual(kind, "blocked")

    def test_dt08_oracle(self):
        a, b = _accepted_values()
        slots = _paired_slots(a, b)
        first = dict(slots[0])
        trial = dict(first["trial"])
        records = [dict(record) for record in trial["lanes"]]
        records[0]["total_hits"] = 999
        trial["lanes"] = records
        first["trial"] = trial
        kind, _, _ = m.derive_paired(_manifest(), [first] + slots[1:], _baseline_manifest())
        self.assertEqual(kind, "blocked")

    def test_dt09_probe(self):
        a, b = _accepted_values()
        slots = _paired_slots(a, b)
        first = dict(slots[0])
        trial = dict(first["trial"])
        trial["contention_before"] = {"state": "busy"}
        first["trial"] = trial
        kind, _, _ = m.derive_paired(_manifest(), [first] + slots[1:], _baseline_manifest())
        self.assertEqual(kind, "blocked")

    def test_dt10_dt11_primary_boundary(self):
        self.assertTrue(m.primary_lane_gate([2 * MS] * 4)["strong_pass"])
        self.assertFalse(m.primary_lane_gate([1_999_999] * 4)["strong_pass"])

    def test_dt12_positive_block_count(self):
        self.assertTrue(m.primary_lane_gate([2 * MS, 2 * MS, 2 * MS, 0])["strong_pass"])
        self.assertFalse(m.primary_lane_gate([2 * MS, 2 * MS, 0, 0])["strong_pass"])

    def test_dt13_dt14_dt15_floors(self):
        self.assertFalse(m.primary_lane_gate([-750_001] * 4)["support_pass"])
        self.assertTrue(m.primary_lane_gate([-750_000] * 4)["support_pass"])
        self.assertTrue(m.guard_lane_gate([-750_000] * 4, m.D_G1_MIN_NS)["passes"])
        self.assertFalse(m.guard_lane_gate([-750_001] * 4, m.D_G1_MIN_NS)["passes"])
        self.assertTrue(m.guard_lane_gate([-250_000] * 4, m.D_SPARSE_MIN_NS)["passes"])
        self.assertFalse(m.guard_lane_gate([-250_001] * 4, m.D_SPARSE_MIN_NS)["passes"])

    def test_dt16_guard_block_floor(self):
        self.assertFalse(
            m.guard_lane_gate([-1_000_001, 0, 0, 0], m.D_SPARSE_MIN_NS)["passes"]
        )

    def test_dt17_scope_prefixes(self):
        self.assertEqual(
            tuple(m.A_ALLOWED_CHANGED_PREFIXES),
            ("benchmarks/pr15h_d/", "docs/pr-artifacts/pr-15h-d/"),
        )

    def test_dt18_forbidden_paths(self):
        for path in (
            "crates/quervant-core/src/search/execute.rs",
            "crates/quervant-core/src/search/score.rs",
            "crates/quervant-core/src/segment/reader.rs",
            "Cargo.toml",
            ".github/workflows/ci.yml",
        ):
            with mock.patch.object(m.ha.base, "git", return_value=path + "\n"):
                self.assertFalse(m._source_scope_ok("/unused", BASE, CAND), path)

    def test_dt19_seal_and_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="pr15h-d-t19-") as tmp:
            tmp = os.path.realpath(tmp)
            root = os.path.join(tmp, "target", "pr15h-d", "paired-01")
            baseline_root = os.path.join(tmp, "target", "pr15h-d", "baseline-01")
            _write_baseline(baseline_root)
            os.makedirs(root)
            a, b = _accepted_values()
            slots = _paired_slots(a, b)
            manifest = _manifest()
            m.ha.write_exclusive_json(
                os.path.join(root, "authorization.json"), {"schema": m.SCHEMA_AUTHORIZATION}
            )
            m.ha.write_exclusive_json(os.path.join(root, "manifest.json"), manifest)
            for slot in slots:
                m.ha.write_exclusive_json(
                    os.path.join(root, "raw", "slots", f"slot-{slot['slot']:02d}.json"), slot
                )
            m.write_seal(root, "paired")
            kind, report, markdown = m.derive_paired(manifest, slots, _baseline_manifest())
            m.publish_report(root, kind, report, markdown)
            with self.assertRaises(m.RunBlocked):
                m.publish_report(root, kind, report, markdown)
            with open(os.path.join(root, "raw", "slots", "slot-01.json"), "ab") as handle:
                handle.write(b" ")
            self.assertEqual(_blocked(lambda: m.verify_seal(root, "paired")).rule, "X_SEAL")

    def test_dt20_verify_only_read_only(self):
        with tempfile.TemporaryDirectory(prefix="pr15h-d-t20-") as tmp:
            tmp = os.path.realpath(tmp)
            root = os.path.join(tmp, "target", "pr15h-d", "paired-01")
            baseline_root = os.path.join(tmp, "target", "pr15h-d", "baseline-01")
            _write_baseline(baseline_root)
            os.makedirs(root)
            a, b = _accepted_values()
            slots = _paired_slots(a, b)
            manifest = _manifest()
            m.ha.write_exclusive_json(
                os.path.join(root, "authorization.json"), {"schema": m.SCHEMA_AUTHORIZATION}
            )
            m.ha.write_exclusive_json(os.path.join(root, "manifest.json"), manifest)
            for slot in slots:
                m.ha.write_exclusive_json(
                    os.path.join(root, "raw", "slots", f"slot-{slot['slot']:02d}.json"), slot
                )
            m.write_seal(root, "paired")
            kind, report, markdown = m.derive_paired(manifest, slots, _baseline_manifest())
            m.publish_report(root, kind, report, markdown)
            before = {}
            for directory, _dirs, files in os.walk(root):
                for name in files:
                    full = os.path.join(directory, name)
                    before[os.path.relpath(full, root)] = m.ha.sha256_file(full)
            from types import SimpleNamespace

            self.assertEqual(
                m.verify_campaign(
                    SimpleNamespace(
                        checkout_root=tmp,
                        campaign=root,
                        baseline=baseline_root,
                    )
                ),
                0,
            )
            after = {}
            for directory, _dirs, files in os.walk(root):
                for name in files:
                    full = os.path.join(directory, name)
                    after[os.path.relpath(full, root)] = m.ha.sha256_file(full)
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
