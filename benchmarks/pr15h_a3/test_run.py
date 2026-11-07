#!/usr/bin/env python3
"""PR 15H-A3 controller tests (A3-B01 … A3-B28).

Deterministic synthetic fixtures only: no live timing, no network, no
performance verdicts. Each negative case changes exactly one field wherever
practical so the refusal is attributable.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
import unittest
from unittest import mock

RUN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.py")
_spec = importlib.util.spec_from_file_location("pr15h_a3_run_under_test", RUN_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load {RUN_PATH}")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

BASE_SHA = m.A_SHA
CAND_SHA = m.B_SHA
VARIANT_SHA = "c" * 40
TOOLING_SHA = "d" * 40
ENV = "e" * 64
CORPUS = "f" * 64
IDX = {"10000": "1" * 64, "100000": "2" * 64}
BINARY = {"A": "3" * 64, "A_PRIME": "4" * 64, "B": "5" * 64, "V": "6" * 64}
EXPECTED = {
    m.LANE_IDS[0]: 0,
    m.LANE_IDS[1]: 1,
    m.LANE_IDS[2]: 1,
    m.LANE_IDS[3]: 100,
}


def _blocked(callable_):
    try:
        callable_()
    except m.RunBlocked as error:
        return error
    raise AssertionError("expected RunBlocked")


def _record(lane, median, *, oracle=True, total_hits=None, doc_ids=None):
    samples = [median] * m.SAMPLES
    expected_hits = EXPECTED[lane["id"]] if total_hits is None else total_hits
    docs = ["d0"] if doc_ids is None else list(doc_ids)
    return {
        "id": lane["id"],
        "n": lane["n"],
        "class": lane["class"],
        "field": lane["field"],
        "term": lane["term"],
        "k": lane["k"],
        "regime": m.ha.REGIME,
        "warmups": m.WARMUPS,
        "samples_ns": samples,
        "summary_ns": m.ha.base.pr15d_run.summarize(samples),
        "total_hits": expected_hits,
        "doc_ids": docs,
        "expected_doc_ids": list(docs),
        "oracle_ok": oracle,
    }


def _trial(lanes, medians, *, before="clear", after="clear"):
    return {
        "index": 1,
        "contention_before": {"state": before},
        "contention_after": {"state": after},
        "lanes": [_record(lane, medians[lane["id"]]) for lane in lanes],
    }


def _arms(stage, *, src_a=BASE_SHA, src_b=CAND_SHA, src_v=VARIANT_SHA, idx=None):
    idx = idx or IDX
    if stage == "aa":
        return {
            "A": {"source_sha": src_a, "binary_sha256": BINARY["A"], "index_digests": idx},
            "A_PRIME": {
                "source_sha": src_a,
                "binary_sha256": BINARY["A_PRIME"],
                "index_digests": idx,
            },
        }
    if stage == "ab":
        return {
            "A": {"source_sha": src_a, "binary_sha256": BINARY["A"], "index_digests": idx},
            "B": {"source_sha": src_b, "binary_sha256": BINARY["B"], "index_digests": idx},
        }
    return {
        "B": {"source_sha": src_b, "binary_sha256": BINARY["B"], "index_digests": idx},
        "V": {"source_sha": src_v, "binary_sha256": BINARY["V"], "index_digests": idx},
    }


def _manifest(stage, arms=None, *, env=ENV, corpus=CORPUS):
    arms = arms or _arms(stage)
    return {
        "schema": m.SCHEMA_MANIFEST,
        "stage": stage,
        "tooling_sha": TOOLING_SHA,
        "environment_fingerprint": env,
        "corpus_manifest_sha256": corpus,
        "lanes": list(m.LANE_IDS),
        "expected_by_lane": dict(EXPECTED),
        "schedule": [list(order) for order in m._schedule(stage)],
        "arms": arms,
    }


def _slot(stage, number, block, arm, arms, medians, *, before="clear", after="clear"):
    meta = arms[arm]
    return {
        "schema": m.SCHEMA_SLOT,
        "stage": stage,
        "slot": number,
        "block": block,
        "arm": arm,
        "source_sha": meta["source_sha"],
        "binary_sha256": meta["binary_sha256"],
        "index_digests": meta["index_digests"],
        "trial": _trial(m.frozen_lanes(), medians, before=before, after=after),
    }


def _build_slots(stage, per_arm, arms):
    slots = []
    number = 0
    for block, order in enumerate(m._schedule(stage), start=1):
        for arm in order:
            number += 1
            slots.append(_slot(stage, number, block, arm, arms, per_arm[arm][block]))
    return slots


def _uniform(median):
    return {lane_id: median for lane_id in m.LANE_IDS}


def _aa_slots(median_a=1000, median_p=1000, arms=None):
    arms = arms or _arms("aa")
    return _build_slots(
        "aa",
        {
            "A": {1: _uniform(median_a), 2: _uniform(median_a)},
            "A_PRIME": {1: _uniform(median_p), 2: _uniform(median_p)},
        },
        arms,
    )


def _ab_slots(a_values, b_values, arms=None):
    arms = arms or _arms("ab")
    return _build_slots(
        "ab",
        {
            "A": {block: dict(values) for block, values in enumerate(a_values, start=1)},
            "B": {block: dict(values) for block, values in enumerate(b_values, start=1)},
        },
        arms,
    )


def _variant_slots(stage, b_values, v_values, arms=None):
    arms = arms or _arms(stage)
    return _build_slots(
        stage,
        {
            "B": {block: dict(values) for block, values in enumerate(b_values, start=1)},
            "V": {block: dict(values) for block, values in enumerate(v_values, start=1)},
        },
        arms,
    )


def _write_campaign(root, stage, slots, manifest):
    os.makedirs(root)
    m.ha.write_exclusive_json(
        os.path.join(root, "authorization.json"),
        {"schema": m.SCHEMA_AUTHORIZATION, "stage": stage, "operator_idle_authorized_by_user": True},
    )
    m.ha.write_exclusive_json(os.path.join(root, "manifest.json"), manifest)
    for slot in slots:
        m.ha.write_exclusive_json(
            os.path.join(root, "raw", "slots", f"slot-{slot['slot']:02d}.json"), slot
        )
    m.write_seal(root, stage)
    kind, report, markdown = m.DERIVERS[stage](manifest, slots)
    m.publish_report(root, kind, report, markdown)
    return kind, report, markdown


class LaneAndPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pr15h-a3-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_b01_four_exact_lanes_in_order(self):
        lanes = m.frozen_lanes()
        self.assertEqual([lane["id"] for lane in lanes], list(m.LANE_IDS))
        self.assertTrue(all(lane["regime"] == "warm" for lane in lanes))

    def test_b02_fifth_or_reordered_lane_rejected(self):
        original = m.LANE_IDS
        try:
            for mutated in (
                original + ("pr15d_v1/10000/absent/k100",),
                (original[1], original[0], original[2], original[3]),
            ):
                m.LANE_IDS = mutated
                self.assertEqual(_blocked(m.frozen_lanes).rule, "X_LANE_SET")
        finally:
            m.LANE_IDS = original

    def test_b03_process_cold_lane_rejected(self):
        original = m.ha.base.pr15d_run.lane_descriptors

        def cold():
            return [dict(lane, regime="process_cold") for lane in original()]

        with mock.patch.object(m.ha.base.pr15d_run, "lane_descriptors", cold):
            self.assertEqual(_blocked(m.frozen_lanes).rule, "X_LANE_SET")

    def test_b26_duplicate_keys_symlink_and_traversal(self):
        root = os.path.join(self.tmp, "target", "pr15h-a3")
        fresh = os.path.join(root, "campaign-01")
        self.assertEqual(m.validate_out_path(fresh, self.tmp), os.path.realpath(fresh))
        os.makedirs(fresh)
        self.assertEqual(
            _blocked(lambda: m.validate_out_path(fresh, self.tmp)).rule, "X_OUT_EXISTS"
        )
        outside = os.path.join(self.tmp, "elsewhere")
        self.assertEqual(
            _blocked(lambda: m.validate_out_path(outside, self.tmp)).rule, "X_PATH"
        )
        link = os.path.join(root, "link-01")
        os.symlink(fresh, link)
        self.assertEqual(
            _blocked(lambda: m.validate_out_path(link, self.tmp)).rule, "X_SYMLINK"
        )
        duplicate = os.path.join(self.tmp, "duplicate.json")
        with open(duplicate, "w", encoding="utf-8") as handle:
            handle.write('{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            m.ha.read_json_strict(duplicate)
        symlink = os.path.join(self.tmp, "file-link.json")
        os.symlink(duplicate, symlink)
        self.assertEqual(
            _blocked(lambda: m.ha.read_json_strict(symlink)).rule, "X11_SYMLINK"
        )

    def test_b28_acceptance_claim_and_silent_retry_rejected(self):
        self.assertEqual(
            _blocked(lambda: m.reject_acceptance_claim({"verdict": "PERFORMANCE_ACCEPTED"})).rule,
            "X_ACCEPTANCE",
        )
        self.assertEqual(
            _blocked(lambda: m.reject_acceptance_claim({"x": "OPTIMIZATION_RETAINED"})).rule,
            "X_ACCEPTANCE",
        )
        m.reject_acceptance_claim({"verdict": "NOT_APPLICABLE_DIAGNOSTIC_ONLY"})


class ScheduleAndControlTests(unittest.TestCase):
    def test_b04_aa_exact_schedule_accepted(self):
        slots = _aa_slots()
        manifest = _manifest("aa")
        kind, report, _ = m.derive_aa(manifest, slots)
        self.assertEqual(kind, "qualified")
        self.assertEqual(report["qualification"], "AA_QUALIFIED")
        self.assertEqual(report["slot_count"], 4)
        self.assertEqual(report["timed_samples"], 320)
        self.assertEqual(report["contention_probes"], 8)

    def test_b05_aa_candidate_substituted_rejected(self):
        arms = _arms("aa", src_a=BASE_SHA)
        arms["A_PRIME"]["source_sha"] = CAND_SHA
        slots = _aa_slots(arms=arms)
        kind, report, _ = m.derive_aa(_manifest("aa", arms=arms), slots)
        self.assertEqual(kind, "blocked")
        self.assertEqual(report["reason"], "MEASUREMENT_BLOCKED_AA_CONTROL")

    def test_b06_ab_exact_eight_slot_schedule_accepted(self):
        a_values = [_uniform(1000)] * 4
        b_values = [
            {m.LANE_IDS[0]: 1700, m.LANE_IDS[1]: 1700, m.LANE_IDS[2]: 1300, m.LANE_IDS[3]: 900}
        ] * 4
        slots = _ab_slots(a_values, b_values)
        kind, report, _ = m.derive_ab(_manifest("ab"), slots)
        self.assertEqual(kind, "qualified")
        self.assertEqual(report["slot_count"], 8)
        self.assertEqual(report["lane_record_count"], 32)
        self.assertEqual(report["timed_samples"], 640)
        self.assertEqual(report["reproduction"], "REPRODUCED")

    def test_b07_wrong_ab_arm_or_block_rejected(self):
        slots = _ab_slots([_uniform(1000)] * 4, [_uniform(900)] * 4)
        swapped = [dict(slot) for slot in slots]
        swapped[0]["arm"] = "B"
        self.assertEqual(_blocked(lambda: m.validate_schedule(swapped, "ab")).rule, "X_SCHEDULE")
        duplicate = [dict(slot) for slot in slots]
        duplicate[1]["block"] = 2
        self.assertEqual(_blocked(lambda: m.validate_schedule(duplicate, "ab")).rule, "X_SCHEDULE")
        wrong_block = [dict(slot) for slot in slots]
        wrong_block[0]["block"] = 5
        self.assertEqual(_blocked(lambda: m.validate_schedule(wrong_block, "ab")).rule, "X_SCHEDULE")

    def test_b08_variant_schedules_and_wrong_arms(self):
        for stage in ("bv2", "bv3"):
            slots = _variant_slots(stage, [_uniform(1000)] * 2, [_uniform(900)] * 2)
            self.assertEqual(m.validate_schedule(slots, stage), None)
            wrong = [dict(slot) for slot in slots]
            wrong[0]["arm"] = "A"
            self.assertEqual(_blocked(lambda: m.validate_schedule(wrong, stage)).rule, "X_SCHEDULE")

    def test_b09_missing_or_extra_slot_rejected(self):
        slots = _ab_slots([_uniform(1000)] * 4, [_uniform(900)] * 4)
        self.assertEqual(_blocked(lambda: m.validate_schedule(slots[:-1], "ab")).rule, "X_SCHEDULE")
        self.assertEqual(
            _blocked(lambda: m.validate_schedule(slots + [slots[-1]], "ab")).rule, "X_SCHEDULE"
        )


class SampleAndOracleTests(unittest.TestCase):
    def setUp(self):
        self.lanes = m.frozen_lanes()
        self.lane = self.lanes[0]

    def test_b10_exact_samples_warmups_and_summary_accepted(self):
        record = _record(self.lane, 1000)
        summary = m.ha.validate_lane_record(record, self.lane, "b10")
        self.assertEqual(summary["count"], 20)
        self.assertEqual(record["warmups"], 5)

    def test_b11_altered_summary_rejected(self):
        record = _record(self.lane, 1000)
        record["summary_ns"] = dict(record["summary_ns"], median=999)
        self.assertEqual(
            _blocked(lambda: m.ha.validate_lane_record(record, self.lane, "b11")).rule,
            "X16_SUMMARY",
        )
        record = _record(self.lane, 1000)
        record["summary_ns"] = dict(record["summary_ns"], p99=1)
        self.assertEqual(
            _blocked(lambda: m.ha.validate_lane_record(record, self.lane, "b11")).rule,
            "X16_SUMMARY",
        )

    def test_b12_bad_sample_values_rejected(self):
        record = _record(self.lane, 1000)
        for bad in (True, 1.0, 0, -1):
            mutated = dict(record)
            samples = [1000] * 20
            samples[4] = bad
            mutated["samples_ns"] = samples
            mutated["summary_ns"] = m.ha.base.pr15d_run.summarize([1000] * 20)
            self.assertEqual(
                _blocked(lambda: m.ha.validate_lane_record(mutated, self.lane, "b12")).rule,
                "X15_LANE_RECORD",
            )
        for count in (19, 21):
            mutated = dict(record)
            mutated["samples_ns"] = [1000] * count
            mutated["summary_ns"] = m.ha.base.pr15d_run.summarize(mutated["samples_ns"])
            self.assertEqual(
                _blocked(lambda: m.ha.validate_lane_record(mutated, self.lane, "b12")).rule,
                "X15_LANE_RECORD",
            )

    def test_b13_bad_oracle_blocks_campaign(self):
        slots = _ab_slots([_uniform(1000)] * 4, [_uniform(900)] * 4)
        bad = [dict(slot) for slot in slots]
        first = dict(bad[0])
        trial = dict(first["trial"])
        records = [dict(record) for record in trial["lanes"]]
        records[0]["oracle_ok"] = False
        trial["lanes"] = records
        first["trial"] = trial
        bad[0] = first
        kind, report, _ = m.derive_ab(_manifest("ab"), bad)
        self.assertEqual(kind, "blocked")

        wrong_hits = [dict(slot) for slot in slots]
        first = dict(wrong_hits[0])
        trial = dict(first["trial"])
        records = [dict(record) for record in trial["lanes"]]
        records[0]["total_hits"] = 999
        trial["lanes"] = records
        first["trial"] = trial
        wrong_hits[0] = first
        kind, report, _ = m.derive_ab(_manifest("ab"), wrong_hits)
        self.assertEqual(kind, "blocked")

        wrong_docs = [dict(slot) for slot in slots]
        first = dict(wrong_docs[0])
        trial = dict(first["trial"])
        records = [dict(record) for record in trial["lanes"]]
        records[0]["doc_ids"] = ["different"]
        trial["lanes"] = records
        first["trial"] = trial
        wrong_docs[0] = first
        kind, _, _ = m.derive_ab(_manifest("ab"), wrong_docs)
        self.assertEqual(kind, "blocked")


class IdentityAndDriftTests(unittest.TestCase):
    def test_b14_index_digest_altered_blocks(self):
        arms = _arms("ab")
        arms["B"]["index_digests"] = {"10000": IDX["10000"], "100000": "9" * 64}
        slots = _ab_slots([_uniform(1000)] * 4, [_uniform(900)] * 4, arms=arms)
        kind, report, _ = m.derive_ab(_manifest("ab", arms=arms), slots)
        self.assertEqual(kind, "blocked")

    def test_b15_corpus_change_detected_by_verify(self):
        with tempfile.TemporaryDirectory(prefix="pr15h-a3-verify-") as tmp:
            tmp = os.path.realpath(tmp)
            root = os.path.join(tmp, "target", "pr15h-a3", "campaign")
            slots = _aa_slots()
            manifest = _manifest("aa")
            _write_campaign(root, "aa", slots, manifest)
            manifest["corpus_manifest_sha256"] = "0" * 64
            os.remove(os.path.join(root, "manifest.json"))
            m.ha.write_exclusive_json(os.path.join(root, "manifest.json"), manifest)
            # The seal now disagrees first; rewriting the seal with the changed
            # manifest must still be caught by report recomputation.
            os.remove(os.path.join(root, "raw", "seal.json"))
            m.write_seal(root, "aa")
            from types import SimpleNamespace

            self.assertEqual(
                _blocked(
                    lambda: m.verify_campaign(
                        SimpleNamespace(checkout_root=tmp, campaign=root)
                    )
                ).rule,
                "X_REPORT_DRIFT",
            )

    def test_b16_host_fingerprint_mismatch_blocks(self):
        manifest = _manifest("ab")
        with self.assertRaises(m.RunBlocked) as caught:
            m._same_corpus_and_host(manifest, {"x": 1})
        self.assertEqual(caught.exception.rule, "X_HOST")

    def test_b17_b18_aa_cap_exact_and_above(self):
        # 100K cap 1.15, 10K cap 1.20.
        arms = _arms("aa")
        per_arm = {
            "A": {1: {lane: 1000 for lane in m.LANE_IDS}, 2: {lane: 1000 for lane in m.LANE_IDS}},
            "A_PRIME": {
                1: {m.LANE_IDS[0]: 1150, m.LANE_IDS[1]: 1150, m.LANE_IDS[2]: 1200, m.LANE_IDS[3]: 1150},
                2: {m.LANE_IDS[0]: 1150, m.LANE_IDS[1]: 1150, m.LANE_IDS[2]: 1200, m.LANE_IDS[3]: 1150},
            },
        }
        slots = _build_slots("aa", per_arm, arms)
        kind, report, _ = m.derive_aa(_manifest("aa", arms=arms), slots)
        self.assertEqual(kind, "qualified")

        over = dict(per_arm)
        over["A_PRIME"] = {
            1: {lane: (1151 if lane != m.LANE_IDS[2] else 1200) for lane in m.LANE_IDS},
            2: {lane: (1151 if lane != m.LANE_IDS[2] else 1200) for lane in m.LANE_IDS},
        }
        slots = _build_slots("aa", over, arms)
        kind, report, _ = m.derive_aa(_manifest("aa", arms=arms), slots)
        self.assertEqual(kind, "blocked")
        self.assertEqual(report["reason"], "MEASUREMENT_BLOCKED_AA_CONTROL")

    def test_b19_b20_drift_caps_exact_and_above(self):
        self.assertFalse(m._drift([1000, 1250], 100000, m.DRIFT_CAPS)["violated"])
        self.assertTrue(m._drift([1000, 1251], 100000, m.DRIFT_CAPS)["violated"])
        self.assertFalse(m._drift([1000, 1500], 10000, m.DRIFT_CAPS)["violated"])
        self.assertTrue(m._drift([1000, 1501], 10000, m.DRIFT_CAPS)["violated"])

    def test_b21_nonclear_probe_blocks(self):
        arms = _arms("ab")
        slots = _ab_slots([_uniform(1000)] * 4, [_uniform(900)] * 4, arms=arms)
        first = dict(slots[0])
        trial = dict(first["trial"])
        trial["contention_before"] = {"state": "busy"}
        first["trial"] = trial
        broken = [first] + slots[1:]
        kind, report, _ = m.derive_ab(_manifest("ab", arms=arms), broken)
        self.assertEqual(kind, "blocked")


class VerdictTests(unittest.TestCase):
    def test_b22_reproduced(self):
        a_values = [_uniform(1000)] * 4
        b_values = [
            {m.LANE_IDS[0]: 1700, m.LANE_IDS[1]: 1700, m.LANE_IDS[2]: 1300, m.LANE_IDS[3]: 900}
        ] * 4
        slots = _ab_slots(a_values, b_values)
        kind, report, _ = m.derive_ab(_manifest("ab"), slots)
        self.assertEqual(kind, "qualified")
        self.assertEqual(report["reproduction"], "REPRODUCED")
        for lane in report["lanes"]:
            if lane["id"] == m.LANE_IDS[3]:
                self.assertEqual(lane["verdict"], "B_FASTER")
            else:
                self.assertEqual(lane["verdict"], "B_SLOWER")

    def test_b23_inconclusive(self):
        a_values = [_uniform(1000)] * 4
        b_values = [
            {m.LANE_IDS[0]: 1700, m.LANE_IDS[1]: 1700, m.LANE_IDS[2]: 1300, m.LANE_IDS[3]: 1000}
        ] * 4
        slots = _ab_slots(a_values, b_values)
        kind, report, _ = m.derive_ab(_manifest("ab"), slots)
        self.assertEqual(kind, "qualified")
        self.assertEqual(report["reproduction"], "REPRODUCTION_INCONCLUSIVE")
        self.assertEqual(
            next(lane for lane in report["lanes"] if lane["id"] == m.LANE_IDS[3])["verdict"],
            "INCONCLUSIVE",
        )

        one_opposite = [{lane: 1100 for lane in m.LANE_IDS} for _ in range(4)]
        one_opposite[2][m.LANE_IDS[0]] = 950
        slots = _ab_slots(a_values, one_opposite)
        kind, report, _ = m.derive_ab(_manifest("ab"), slots)
        self.assertEqual(report["reproduction"], "REPRODUCTION_INCONCLUSIVE")

    def test_variant_effect_boundary(self):
        b_values = [_uniform(1000)] * 2
        v_values = [
            {m.LANE_IDS[0]: 940, m.LANE_IDS[1]: 940, m.LANE_IDS[2]: 940, m.LANE_IDS[3]: 1050}
        ] * 2
        for stage in ("bv2", "bv3"):
            slots = _variant_slots(stage, b_values, v_values)
            kind, report, _ = m.derive_variant(_manifest(stage), slots)
            self.assertEqual(kind, "qualified")
            self.assertEqual(report["outcome"], f"{stage[1:].upper()}_EFFECT_PRESENT")
            self.assertEqual(report["confidence"], "SUPPORTING_ONLY")
        v_slow = [
            {m.LANE_IDS[0]: 950, m.LANE_IDS[1]: 950, m.LANE_IDS[2]: 950, m.LANE_IDS[3]: 1050}
        ] * 2
        slots = _variant_slots("bv2", b_values, v_slow)
        kind, report, _ = m.derive_variant(_manifest("bv2"), slots)
        self.assertEqual(report["outcome"], "V2_EFFECT_NOT_ESTABLISHED")


class SealAndVerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pr15h-a3-seal-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _campaign(self, name="campaign"):
        root = os.path.join(self.tmp, "target", "pr15h-a3", name)
        slots = _aa_slots()
        _write_campaign(root, "aa", slots, _manifest("aa"))
        return root

    def test_b24_tampered_seal_refused(self):
        root = self._campaign()
        with open(os.path.join(root, "raw", "slots", "slot-01.json"), "ab") as handle:
            handle.write(b" ")
        self.assertEqual(_blocked(lambda: m.verify_seal(root, "aa")).rule, "X_SEAL")

    def test_b25_tampered_report_refused(self):
        root = self._campaign()
        path = os.path.join(root, "sanitized", "qualified.json")
        with open(path, "rb") as handle:
            payload = bytearray(handle.read())
        payload[0] = ord("[")
        with open(path, "wb") as handle:
            handle.write(payload)
        from types import SimpleNamespace

        self.assertEqual(
            _blocked(
                lambda: m.verify_campaign(SimpleNamespace(checkout_root=self.tmp, campaign=root))
            ).rule,
            "X_REPORT_DRIFT",
        )

    def test_b27_both_report_pairs_refused(self):
        root = self._campaign()
        kind, report, markdown = m.derive_aa(_manifest("aa"), _aa_slots())
        with self.assertRaises(m.RunBlocked) as caught:
            m.publish_report(root, kind, report, markdown)
        self.assertEqual(caught.exception.rule, "X_REPORT_EXISTS")

    def test_verify_accepts_valid_campaign(self):
        root = self._campaign()
        from types import SimpleNamespace

        self.assertEqual(
            m.verify_campaign(SimpleNamespace(checkout_root=self.tmp, campaign=root)), 0
        )


if __name__ == "__main__":
    unittest.main()
