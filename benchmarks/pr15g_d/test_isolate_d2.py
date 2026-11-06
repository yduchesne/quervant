#!/usr/bin/env python3
"""Deterministic tests for the PR 15G-D isolated D2 A/X controller."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "pr15g_d_isolate_under_test", os.path.join(HERE, "isolate_d2.py")
)
iso = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(iso)


def make_lane_record(lane_id, ns):
    samples = [int(ns)] * iso.SAMPLES
    reference = iso._expected_lanes()[lane_id]
    return {
        "id": lane_id,
        "n": reference["n"],
        "class": reference["class"],
        "field": reference["field"],
        "term": reference["term"],
        "k": reference["k"],
        "regime": reference["regime"],
        "warmups": iso.WARMUPS,
        "warmup_ids": [f"{lane_id}:warmup:{index}" for index in range(iso.WARMUPS)],
        "samples_ns": samples,
        "summary_ns": iso.BASE.pr15d_run.summarize(samples),
        "total_hits": 1,
        "expected_total_hits": 1,
        "doc_ids": ["d1"],
        "expected_doc_ids": ["d1"],
        "oracle_ok": True,
    }


def fake_campaign(a_ns=100, x_ns=90, overrides=None):
    overrides = overrides or {}
    manifest = {
        "schema": iso.SCHEMA,
        "sources": {"A": {"sha": iso.ARM_A}, "X": {"sha": "x" * 40}},
        "binary_sha256": {"A": "a" * 64, "X": "b" * 64},
        "corpus_manifest_sha256": "c" * 64,
        "environment_fingerprint": "d" * 64,
        "index_digests": {
            "A": {"10000": "e" * 64, "100000": "f" * 64},
            "X": {"10000": "e" * 64, "100000": "f" * 64},
        },
        "schedule": iso.SCHEDULE,
        "lanes": list(iso.LANE_IDS),
    }
    slots = []
    for index, arm in enumerate(iso.flat_schedule(), start=1):
        lanes = []
        for lane_id in iso.LANE_IDS:
            base = a_ns if arm == "A" else x_ns
            ns = overrides.get((arm, lane_id, index), base)
            lanes.append(make_lane_record(lane_id, ns))
        slots.append({
            "slot_index": index,
            "block": 1 + (index - 1) // 4,
            "position": 1 + (index - 1) % 4,
            "arm": arm,
            "source_sha": manifest["sources"][arm]["sha"],
            "binary_sha256": manifest["binary_sha256"][arm],
            "corpus_manifest_sha256": manifest["corpus_manifest_sha256"],
            "index_digests": manifest["index_digests"][arm],
            "environment_fingerprint": manifest["environment_fingerprint"],
            "trial": {
                "index": index,
                "lanes": lanes,
                "contention_before": {"state": "clear"},
                "contention_after": {"state": "clear"},
            },
        })
    return manifest, slots


def set_lane_ns(slots, arm, block, position, lane_index, ns):
    index = (block - 1) * 4 + position
    slot = next(slot for slot in slots if slot["slot_index"] == index and slot["arm"] == arm)
    slot["trial"]["lanes"][lane_index] = make_lane_record(iso.LANE_IDS[lane_index], ns)


class ScheduleTests(unittest.TestCase):
    def test_literal_schedule_and_balance(self):
        self.assertEqual(
            iso.SCHEDULE,
            (
                ("A", "X", "X", "A"),
                ("X", "A", "A", "X"),
                ("X", "A", "A", "X"),
                ("A", "X", "X", "A"),
            ),
        )
        self.assertEqual(len(iso.flat_schedule()), 16)
        self.assertEqual(iso.flat_schedule().count("A"), 8)
        self.assertEqual(iso.flat_schedule().count("X"), 8)

    def test_raw_validation_rejects_partial_sample_and_contention(self):
        manifest, slots = fake_campaign()
        iso.validate_raw(manifest, slots)
        with self.assertRaises(Exception):
            iso.validate_raw(manifest, slots[:-1])
        slots[0]["trial"]["lanes"][0]["samples_ns"] = [1] * 19
        with self.assertRaises(Exception):
            iso.validate_raw(manifest, slots)
        manifest, slots = fake_campaign()
        slots[0]["trial"]["contention_after"]["state"] = "busy"
        with self.assertRaises(Exception):
            iso.validate_raw(manifest, slots)

    def test_raw_validation_rejects_lane_reorder(self):
        manifest, slots = fake_campaign()
        lanes = slots[0]["trial"]["lanes"]
        lanes[0], lanes[1] = lanes[1], lanes[0]
        with self.assertRaises(Exception):
            iso.validate_raw(manifest, slots)

    def test_raw_validation_rejects_manifest_identity_and_warmups(self):
        manifest, slots = fake_campaign()
        slots[0]["binary_sha256"] = "0" * 64
        with self.assertRaises(Exception):
            iso.validate_raw(manifest, slots)
        manifest, slots = fake_campaign()
        slots[0]["trial"]["lanes"][0]["warmups"] = 4
        with self.assertRaises(Exception):
            iso.validate_raw(manifest, slots)


class SummaryTests(unittest.TestCase):
    def test_nearest_rank_summary_is_authoritative(self):
        lane = make_lane_record(iso.LANE_IDS[0], 1)
        lane["samples_ns"] = list(range(1, 21))
        lane["summary_ns"] = iso.BASE.pr15d_run.summarize(lane["samples_ns"])
        self.assertEqual(
            lane["summary_ns"],
            {"count": 20, "median": 10, "p95": 19, "p99": 20, "min": 1, "max": 20},
        )
        manifest, slots = fake_campaign()
        slots[0]["trial"]["lanes"][0] = lane
        iso.validate_raw(manifest, slots)

    def test_tampered_summary_is_rejected(self):
        manifest, slots = fake_campaign()
        lane = slots[0]["trial"]["lanes"][0]
        lane["summary_ns"]["median"] = 10.5
        with self.assertRaises(Exception):
            iso.validate_raw(manifest, slots)
        manifest, slots = fake_campaign()
        lane = slots[0]["trial"]["lanes"][0]
        lane["summary_ns"]["p95"] += 1
        with self.assertRaises(Exception):
            iso.validate_raw(manifest, slots)
        manifest, slots = fake_campaign()
        del slots[0]["trial"]["lanes"][0]["summary_ns"]["min"]
        with self.assertRaises(Exception):
            iso.validate_raw(manifest, slots)

    def test_invalid_sample_types_are_rejected(self):
        for bad in (True, 1.5, 0, -1):
            manifest, slots = fake_campaign()
            slots[0]["trial"]["lanes"][0]["samples_ns"][0] = bad
            with self.assertRaises(Exception):
                iso.validate_raw(manifest, slots)


class ArithmeticTests(unittest.TestCase):
    def test_block_medians_and_ratios(self):
        manifest, slots = fake_campaign(a_ns=100, x_ns=90)
        self.assertEqual(iso.block_medians(slots, "A", iso.LANE_IDS[0]), [100.0] * 4)
        self.assertEqual(iso.block_medians(slots, "X", iso.LANE_IDS[0]), [90.0] * 4)
        self.assertEqual(iso.pair_ratios(slots, iso.LANE_IDS[0]), [0.9] * 4)
        self.assertEqual(iso.lane_verdict([0.9] * 4), "X_FASTER")

    def test_arithmetic_median_of_two_slots(self):
        manifest, slots = fake_campaign()
        lane = iso.LANE_IDS[0]
        set_lane_ns(slots, "A", 1, 1, 0, 80)
        set_lane_ns(slots, "A", 1, 4, 0, 100)
        self.assertEqual(iso.block_medians(slots, "A", lane)[0], 90.0)

    def test_verdict_equality_and_mixed_signs(self):
        self.assertEqual(iso.lane_verdict([1.0, 0.9, 0.9, 0.9]), "INCONCLUSIVE")
        self.assertEqual(iso.lane_verdict([0.9, 1.01, 0.9, 0.9]), "INCONCLUSIVE")
        self.assertEqual(iso.lane_verdict([1.1, 1.2, 1.05, 1.0]), "INCONCLUSIVE")
        self.assertEqual(iso.lane_verdict([1.1, 1.2, 1.05, 1.01]), "A_FASTER")

    def test_drift_boundaries_and_violations(self):
        manifest, slots = fake_campaign()
        lane_index = 4
        set_lane_ns(slots, "A", 1, 1, lane_index, 80)
        set_lane_ns(slots, "A", 1, 4, lane_index, 100)
        drift, violations = iso.compute_drift_diagnostics(slots)
        self.assertEqual(violations, [])
        self.assertAlmostEqual(
            drift["A"][iso.LANE_IDS[lane_index]]["baseline_cross_block"], 10.0 / 9.0
        )
        set_lane_ns(slots, "A", 1, 4, lane_index, 101)
        drift, violations = iso.compute_drift_diagnostics(slots)
        self.assertTrue(any(v["lane"] == iso.LANE_IDS[lane_index] for v in violations))
        with self.assertRaises(Exception):
            iso.drift_report(slots)


class GateTests(unittest.TestCase):
    def test_both_common_lanes_required(self):
        verdicts = {
            "pr15d_v1/100000/common/k100": "X_FASTER",
            "pr15d_v1/100000/common/k10": "X_FASTER",
        }
        lanes = [{"id": lane, "verdict": verdicts.get(lane, "INCONCLUSIVE")} for lane in iso.LANE_IDS]
        gates = iso.gate_verdicts(lanes)
        self.assertEqual(gates["DX-P01"], "PASS")
        self.assertEqual(gates["DX-P02"], "PASS")
        self.assertEqual(gates["status"], "ACCEPT_D2_ONLY")
        verdicts["pr15d_v1/100000/common/k10"] = "INCONCLUSIVE"
        lanes = [{"id": lane, "verdict": verdicts.get(lane, "INCONCLUSIVE")} for lane in iso.LANE_IDS]
        self.assertEqual(iso.gate_verdicts(lanes)["DX-P01"], "FAIL")

    def test_guardrail_blocks_acceptance(self):
        verdicts = {
            "pr15d_v1/100000/common/k100": "X_FASTER",
            "pr15d_v1/100000/common/k10": "X_FASTER",
            "pr15d_v1/10000/rare/k100": "A_FASTER",
        }
        lanes = [{"id": lane, "verdict": verdicts.get(lane, "INCONCLUSIVE")} for lane in iso.LANE_IDS]
        gates = iso.gate_verdicts(lanes)
        self.assertEqual(gates["DX-P02"], "FAIL")
        self.assertEqual(gates["status"], "D2_ONLY_PERFORMANCE_REJECTED")


class OutputTests(unittest.TestCase):
    def test_out_must_be_inside_campaign_tree(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(Exception):
                iso.validate_out(root, os.path.join(root, "elsewhere"))
            target = os.path.join(root, "target", "pr15g-d-d2-isolation", "campaigns", "x")
            self.assertEqual(iso.validate_out(root, target), os.path.realpath(target))

    def test_sanitizer_rejects_absolute_paths(self):
        with self.assertRaises(Exception):
            iso._clean("/home/x")

    def test_blocked_report_has_no_performance_table(self):
        manifest, slots = fake_campaign()
        set_lane_ns(slots, "A", 1, 1, 4, 80)
        set_lane_ns(slots, "A", 1, 4, 4, 101)
        drift, violations = iso.compute_drift_diagnostics(slots)
        report = iso.sanitize_blocked(manifest, drift, violations)
        data = iso.render_json(report)
        text = iso.render_blocked_markdown(report)
        self.assertEqual(report["status"], "MEASUREMENT_BLOCKED")
        self.assertEqual(report["performance_verdict"], "NOT_EVALUATED")
        self.assertNotIn(b"DX-P01", data)
        self.assertIn(b"NO PERFORMANCE VERDICT", text)

    def test_render_json_and_markdown_are_canonical_bytes(self):
        report = {
            "schema": iso.SCHEMA,
            "source_shas": {"A": iso.ARM_A, "X": "x" * 40},
            "lanes": [{"id": lane, "verdict": "INCONCLUSIVE"} for lane in iso.LANE_IDS],
            "comparisons": {
                lane: {
                    "a_block_medians_ns": [1.0] * 4,
                    "x_block_medians_ns": [1.0] * 4,
                    "ratios": [1.0] * 4,
                    "verdict": "INCONCLUSIVE",
                }
                for lane in iso.LANE_IDS
            },
            "drift": {},
            "gates": {"status": "D2_ONLY_PERFORMANCE_REJECTED"},
        }
        self.assertTrue(iso.render_json(report).endswith(b"\n"))
        self.assertEqual(iso.render_json(report), iso.render_json(report))
        self.assertIn(b"PR 15G-D D2-only", iso.render_markdown(report))


class SealTests(unittest.TestCase):
    def _write_campaign(self, root, blocked):
        out = os.path.join(root, "campaign")
        raw = os.path.join(out, "raw")
        os.makedirs(os.path.join(raw, "slots"))
        manifest, slots = fake_campaign()
        if blocked:
            set_lane_ns(slots, "A", 1, 1, 4, 80)
            set_lane_ns(slots, "A", 1, 4, 4, 101)
        for name, value in (("authorization.json", {"basis": "test"}), ("manifest.json", manifest)):
            iso.write_json_exclusive(os.path.join(raw, name), value)
        for slot in slots:
            iso.write_json_exclusive(
                os.path.join(raw, "slots", f"slot-{slot['slot_index']:02d}.json"), slot
            )
        iso.seal_complete_acquisition(out)
        drift, violations = iso.compute_drift_diagnostics(slots)
        os.makedirs(os.path.join(out, "sanitized"))
        if violations:
            report = iso.sanitize_blocked(manifest, drift, violations)
            iso.write_bytes_exclusive(os.path.join(out, "sanitized", "blocked.json"), iso.render_json(report))
            iso.write_bytes_exclusive(os.path.join(out, "sanitized", "blocked.md"), iso.render_blocked_markdown(report))
        else:
            lanes = iso.lane_results(slots)
            gates = iso.gate_verdicts(lanes)
            gates["DX-P03"] = "PASS"
            report = iso.sanitize({
                "a_sha": manifest["sources"]["A"]["sha"],
                "x_sha": manifest["sources"]["X"]["sha"],
                "lanes": lanes,
                "drift": drift,
                "gates": gates,
            })
            iso.write_bytes_exclusive(os.path.join(out, "sanitized", "confirmation.json"), iso.render_json(report))
            iso.write_bytes_exclusive(os.path.join(out, "sanitized", "performance.md"), iso.render_markdown(report))
        return out

    def test_blocked_seal_and_verify(self):
        with tempfile.TemporaryDirectory() as root:
            out = self._write_campaign(root, blocked=True)
            self.assertEqual(iso.verify_only(types.SimpleNamespace(out=out)), 0)

    def test_qualified_seal_and_verify(self):
        with tempfile.TemporaryDirectory() as root:
            out = self._write_campaign(root, blocked=False)
            self.assertEqual(iso.verify_only(types.SimpleNamespace(out=out)), 0)

    def test_tampered_slot_and_report_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            out = self._write_campaign(root, blocked=True)
            slot = os.path.join(out, "raw", "slots", "slot-01.json")
            with open(slot, "ab") as handle:
                handle.write(b" ")
            with self.assertRaises(Exception):
                iso.verify_only(types.SimpleNamespace(out=out))
        with tempfile.TemporaryDirectory() as root:
            out = self._write_campaign(root, blocked=True)
            md = os.path.join(out, "sanitized", "blocked.md")
            with open(md, "ab") as handle:
                handle.write(b" ")
            with self.assertRaises(Exception):
                iso.verify_only(types.SimpleNamespace(out=out))

    def test_legacy_unsealed_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "campaign")
            os.makedirs(os.path.join(out, "raw"))
            iso.write_json_exclusive(os.path.join(out, "raw", "manifest.json"), {})
            with self.assertRaises(Exception):
                iso._load_campaign(out)


class SourceProofTests(unittest.TestCase):
    def test_real_local_a_x_exact_edits(self):
        root = os.path.dirname(os.path.dirname(HERE))
        iso._assert_exact_d2_edits(root, iso.ARM_A, "53e41df1fd5e91c7c2a67a3fcfbba4abf62bd4f6")
        added, removed = iso._diff_edits(
            root, iso.ARM_A, "53e41df1fd5e91c7c2a67a3fcfbba4abf62bd4f6", iso.SEARCH_FILES[0]
        )
        self.assertEqual((len(added), len(removed)), (15, 0))


if __name__ == "__main__":
    unittest.main()


class HxExactSourceMutationTests(unittest.TestCase):
    def _git(self, repo, *args):
        subprocess.run(["git", "-C", repo, *args], check=True, stdout=subprocess.PIPE)

    def _commit(self, repo, message):
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "--allow-empty", "-m", message)

    def _fixture(self, root):
        self._git(root, "init", "-q")
        self._git(root, "config", "user.name", "fixture")
        self._git(root, "config", "user.email", "fixture@example.invalid")
        execute = os.path.join(root, iso.SEARCH_FILES[0])
        unified = os.path.join(root, iso.SEARCH_FILES[1])
        os.makedirs(os.path.dirname(execute), exist_ok=True)
        os.makedirs(os.path.dirname(unified), exist_ok=True)
        stable = "\n".join(f"// stable {i}" for i in range(10)) + "\n"
        open(execute, "w").write(stable)
        open(unified, "w").write(stable + "let matched = old;\nmod tests {\n}\n")
        self._commit(root, "A")
        a = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
        open(unified, "w").write(
            stable + "let matched = old;\nmod tests {\n    #[test]\n    fn d1_only() {}\n}\n"
        )
        self._commit(root, "D1")
        d1 = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
        added = (
            "#[cfg(test)]\nfn term_membership_searches() {}\n"
            "fn record_term_membership_search() {}\n"
            + "".join(f"// d2 execute {i}\n" for i in range(12))
        )
        open(execute, "w").write(stable + added)
        test_lines = "".join(f"    // d2 test {i}\n" for i in range(41))
        open(unified, "w").write(
            stable
            + "let matched = if postings_candidate_eligible { true } else { old };\nmod tests {\n    #[test]\n    fn d1_only() {}\n"
            + test_lines
            + "    fn gd_u20_u21_u22_d2_removes_only_membership_binary_search() {}\n}\n"
        )
        self._commit(root, "D2")
        d2 = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
        self._git(root, "checkout", "-q", a)
        open(execute, "w").write(stable + added)
        open(unified, "w").write(
            stable
            + "let matched = if postings_candidate_eligible { true } else { old };\nmod tests {\n"
            + test_lines
            + "    fn gd_u20_u21_u22_d2_removes_only_membership_binary_search() {}\n}\n"
        )
        self._commit(root, "X")
        x = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
        return a, d1, d2, x, execute, unified, stable

    def test_hx_exact_source_edit_mutations(self):
        import unittest.mock
        with tempfile.TemporaryDirectory() as root:
            a, d1, d2, x, execute, unified, stable = self._fixture(root)
            with unittest.mock.patch.object(iso, "ARM_A", a), \
                 unittest.mock.patch.object(iso, "HISTORICAL_D1", d1), \
                 unittest.mock.patch.object(iso, "HISTORICAL_D2", d2):
                iso._assert_exact_d2_edits(root, a, x)
                iso.validate_source_identity({
                    "checkout_root": root,
                    "sources": {"A": {"sha": a}, "X": {"sha": x}},
                })
                with self.assertRaises(iso.BASE.pr15d_run.RunBlocked):
                    open(execute, "a").write("// extra\n")
                    self._commit(root, "extra")
                    x_bad = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
                    iso._assert_exact_d2_edits(root, a, x_bad)
                self._git(root, "reset", "-q", "--hard", x)
                open(execute, "w").write(stable)
                self._commit(root, "missing additions")
                x_bad = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
                self.assertRaises(iso.BASE.pr15d_run.RunBlocked, iso._assert_exact_d2_edits, root, a, x_bad)
                self._git(root, "reset", "-q", "--hard", x)
                open(unified, "a").write("// safety\n")
                self._commit(root, "unexpected test")
                x_bad = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
                self.assertRaises(iso.BASE.pr15d_run.RunBlocked, iso._assert_exact_d2_edits, root, a, x_bad)
                self._git(root, "reset", "-q", "--hard", x)
                self._git(root, "checkout", "-q", d1)
                self._commit(root, "wrong parent")
                x_bad = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
                self.assertRaises(
                    iso.BASE.pr15d_run.RunBlocked,
                    iso.validate_source_identity,
                    {"checkout_root": root, "sources": {"A": {"sha": a}, "X": {"sha": x_bad}}},
                )

    def test_hx_report_pair_coexistence(self):
        import types
        with tempfile.TemporaryDirectory() as root:
            out = SealTests()._write_campaign(root, blocked=True)
            self.assertEqual(iso.verify_only(types.SimpleNamespace(out=out)), 0)
            with open(os.path.join(out, "sanitized", "confirmation.json"), "wb") as handle:
                handle.write(b"{}")
            with self.assertRaises(iso.BASE.pr15d_run.RunBlocked):
                iso.verify_only(types.SimpleNamespace(out=out))
        with tempfile.TemporaryDirectory() as root:
            out = SealTests()._write_campaign(root, blocked=False)
            with open(os.path.join(out, "sanitized", "blocked.json"), "wb") as handle:
                handle.write(b"{}")
            with self.assertRaises(iso.BASE.pr15d_run.RunBlocked):
                iso.verify_only(types.SimpleNamespace(out=out))
