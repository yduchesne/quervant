#!/usr/bin/env python3
"""Controller tests for the PR 15I-C-F diagnostic campaign."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import f_final_run as fr  # noqa: E402


class ProtocolTests(unittest.TestCase):
    def test_frozen_protocol_loads(self):
        protocol = fr.load_f_final_protocol(ROOT)
        self.assertEqual(protocol["schema"], fr.PROTOCOL_SCHEMA)
        self.assertEqual(protocol["f_diagnostic_source"], fr.F_DIAG)
        self.assertEqual(tuple(protocol["arm_order_by_block"]), fr.SCHEDULE)

    def test_schedule_is_balanced(self):
        for block in fr.SCHEDULE:
            self.assertEqual(len(block), fr.SLOTS_PER_BLOCK)
            for arm in fr.ARMS:
                self.assertEqual(block.count(arm), 2)

    def test_campaign_list_is_frozen(self):
        protocol = fr.load_f_final_protocol(ROOT)
        self.assertEqual(tuple(protocol["campaigns"]),
                         tuple(name for name, _ in fr.CAMPAIGNS))

    def test_placeholder_sha_is_rejected(self):
        with self.assertRaises(fr.RunBlocked) as caught:
            fr.require_sha("COMMITTED_F_DIAG", "F_DIAG")
        self.assertEqual(caught.exception.rule, "FF_PROTOCOL")

    def test_protocol_placeholder_fails_closed(self):
        protocol = fr.read_json(os.path.join(ROOT, fr.PROTOCOL_REL))
        protocol["f_diagnostic_source"] = "COMMITTED_F_DIAG_SHA"
        with mock.patch.object(fr, "read_json", return_value=protocol):
            with self.assertRaises(fr.RunBlocked):
                fr.load_f_final_protocol(ROOT)

    def test_threshold_drift_is_rejected(self):
        protocol = fr.read_json(os.path.join(ROOT, fr.PROTOCOL_REL))
        protocol["F_generic_aggregate_max"] = 1.2
        with mock.patch.object(fr, "read_json", return_value=protocol):
            with self.assertRaises(fr.RunBlocked) as caught:
                fr.load_f_final_protocol(ROOT)
        self.assertEqual(caught.exception.rule, "FF_PROTOCOL")


class ArmTests(unittest.TestCase):
    def test_mode_mapping(self):
        self.assertEqual({arm: fr.arm_mode(arm) for arm in fr.ARMS},
                         {"A": None, "C": "disabled", "G": "disabled",
                          "P": "enabled"})

    def test_environment_clears_inherited_mode(self):
        with mock.patch.dict(os.environ, {fr.MODE_VARIABLE: "enabled"}):
            self.assertNotIn(fr.MODE_VARIABLE, fr.arm_environment("A"))
            self.assertEqual(fr.arm_environment("G")[fr.MODE_VARIABLE], "disabled")
            self.assertEqual(fr.arm_environment("P")[fr.MODE_VARIABLE], "enabled")

    def test_environment_strips_build_overrides(self):
        with mock.patch.dict(os.environ, {"RUSTFLAGS": "-C target-cpu=native",
                                          "RUST_LOG": "debug"}):
            env = fr.arm_environment("C")
        self.assertNotIn("RUSTFLAGS", env)
        self.assertNotIn("RUST_LOG", env)

    def test_g_and_p_differ_only_by_mode(self):
        self.assertEqual(fr.arm_source("G"), fr.arm_source("P"))
        self.assertNotEqual(fr.arm_mode("G"), fr.arm_mode("P"))


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ffinal-ctl-")
        self.allowed = os.path.join(self.root, "target", "pr15i-c",
                                    "f-final-diagnostic-v1")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_relative_output_is_rejected(self):
        with self.assertRaises(fr.RunBlocked) as caught:
            fr.validate_output(self.root, "target/pr15i-c/x")
        self.assertEqual(caught.exception.rule, "FF_PATH")

    def test_escaping_output_is_rejected(self):
        with self.assertRaises(fr.RunBlocked):
            fr.validate_output(self.root, os.path.join(self.root, "elsewhere"))

    def test_preexisting_output_is_rejected(self):
        target = os.path.join(self.allowed, "unbatched-01")
        os.makedirs(target)
        with self.assertRaises(fr.RunBlocked) as caught:
            fr.validate_output(self.root, target)
        self.assertEqual(caught.exception.rule, "FF_EXISTS")

    def test_fresh_output_is_accepted(self):
        target = os.path.join(self.allowed, "unbatched-01")
        self.assertEqual(fr.validate_output(self.root, target),
                         os.path.realpath(target))

    def test_unknown_campaign_name_is_rejected(self):
        os.makedirs(os.path.join(self.root, os.path.dirname(fr.PROTOCOL_REL)),
                    exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, fr.PROTOCOL_REL),
                        os.path.join(self.root, fr.PROTOCOL_REL))
        argv = ["--checkout-root", self.root, "--baseline-sha", fr.BASE_A,
                "--c-sha", fr.CAUSAL, "--f-diag-sha", fr.F_DIAG,
                "--regime", "unbatched",
                "--out", os.path.join(self.allowed, "unknown-01"),
                "--idle-confirmed"]
        self.assertEqual(fr.main(argv), 3)

    def test_missing_idle_authorization_blocks(self):
        argv = ["--checkout-root", self.root, "--baseline-sha", fr.BASE_A,
                "--c-sha", fr.CAUSAL, "--f-diag-sha", fr.F_DIAG,
                "--regime", "unbatched",
                "--out", os.path.join(self.allowed, "unbatched-01")]
        self.assertEqual(fr.main(argv), 3)
        self.assertFalse(os.path.exists(self.allowed))

    def test_source_sha_mismatch_blocks(self):
        os.makedirs(os.path.join(self.root, os.path.dirname(fr.PROTOCOL_REL)),
                    exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, fr.PROTOCOL_REL),
                        os.path.join(self.root, fr.PROTOCOL_REL))
        argv = ["--checkout-root", self.root, "--baseline-sha", fr.BASE_A,
                "--c-sha", "0" * 40, "--f-diag-sha", fr.F_DIAG,
                "--regime", "unbatched",
                "--out", os.path.join(self.allowed, "unbatched-01"),
                "--idle-confirmed"]
        self.assertEqual(fr.main(argv), 3)


class AffinityTests(unittest.TestCase):
    def test_unpinnable_cpu_is_rejected(self):
        with mock.patch.object(fr.os, "sched_getaffinity", return_value={5, 6}):
            with self.assertRaises(fr.RunBlocked) as caught:
                fr.resolve_affinity()
        self.assertEqual(caught.exception.rule, "FF_AFFINITY")

    def test_missing_taskset_is_rejected(self):
        with mock.patch.object(fr.shutil, "which", return_value=None):
            with self.assertRaises(fr.RunBlocked):
                fr.resolve_affinity()


class LaneTests(unittest.TestCase):
    def context(self):
        return {"affinity": {"adapter_cpu": 0}, "binary": "/bin/false",
                "index_dirs": {10_000: {"dir": "/tmp"}, 100_000: {"dir": "/tmp"}},
                "metadata": {"analyzer": {"tokenizer": "unicode_word"}},
                "source_sha": fr.F_DIAG, "feature": fr.F_FEATURE}

    def lane(self, lane_id="pr15d_v1/100000/common/k100"):
        return {"id": lane_id, "n": 100_000, "class": "common", "field": "text",
                "term": "t", "k": 100, "regime": "bm25"}

    def expected(self):
        return {"total_hits": 3, "doc_ids": ["a", "b", "c"]}

    def adapter(self, script):
        directory = tempfile.mkdtemp(prefix="ffinal-adapter-")
        path = os.path.join(directory, "adapter")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return path

    @mock.patch.object(fr.base.pr15d_run, "validate_query_response",
                       return_value=None)
    def test_rejects_batch_fields_in_unbatched_reply(self, _validate):
        binary = self.adapter(
            "#!/usr/bin/env python3\n"
            "import json,sys\n"
            "for line in sys.stdin:\n"
            "    print(json.dumps({'schema':'pr15d-adapter-v1','status':'ok',"
            "'batch_ns':5,'total_hits':3,'doc_ids':['a','b','c']}),flush=True)\n")
        with self.assertRaises(fr.RunBlocked) as caught:
            fr.measure_f_lane("A", dict(self.context(), binary=binary),
                              self.lane(), self.expected(), False)
        self.assertEqual(caught.exception.rule, "FF_UNITS")
        shutil.rmtree(os.path.dirname(binary), ignore_errors=True)

    @mock.patch.object(fr.base.pr15d_run, "validate_query_response",
                       return_value=None)
    def test_rejects_engine_fields_in_batched_reply(self, _validate):
        binary = self.adapter(
            "#!/usr/bin/env python3\n"
            "import json,sys\n"
            "for line in sys.stdin:\n"
            "    print(json.dumps({'schema':'pr15d-adapter-v1','status':'ok',"
            "'engine_ns':5,'total_hits':3,'doc_ids':['a','b','c']}),flush=True)\n")
        with self.assertRaises(fr.RunBlocked) as caught:
            fr.measure_f_lane("G", dict(self.context(), binary=binary),
                              self.lane(), self.expected(), True)
        self.assertEqual(caught.exception.rule, "FF_UNITS")
        shutil.rmtree(os.path.dirname(binary), ignore_errors=True)

    @mock.patch.object(fr.base.pr15d_run, "validate_query_response",
                       return_value=None)
    def test_rejects_bad_repeat_count(self, _validate):
        binary = self.adapter(
            "#!/usr/bin/env python3\n"
            "import json,sys\n"
            "for line in sys.stdin:\n"
            "    print(json.dumps({'schema':'pr15d-adapter-v1','status':'ok',"
            "'batch_ns':5,'repeat_count':1,'total_hits':3,'doc_ids':['a','b','c']}),flush=True)\n")
        with self.assertRaises(fr.RunBlocked) as caught:
            fr.measure_f_lane("P", dict(self.context(), binary=binary),
                              self.lane("pr15d_v1/100000/absent/k100"),
                              self.expected(), True)
        self.assertEqual(caught.exception.rule, "FF_UNITS")
        shutil.rmtree(os.path.dirname(binary), ignore_errors=True)

    @mock.patch.object(fr.base.pr15d_run, "validate_query_response",
                       return_value=None)
    def test_rejects_failed_adapter_reply(self, _validate):
        binary = self.adapter(
            "#!/usr/bin/env python3\n"
            "import json,sys\n"
            "for line in sys.stdin:\n"
            "    print(json.dumps({'schema':'pr15d-adapter-v1','status':'error',"
            "'error':{'kind':'boom'}}),flush=True)\n")
        with self.assertRaises(fr.RunBlocked) as caught:
            fr.measure_f_lane("A", dict(self.context(), binary=binary),
                              self.lane(), self.expected(), False)
        self.assertEqual(caught.exception.rule, "FF_PROCESS")
        shutil.rmtree(os.path.dirname(binary), ignore_errors=True)

    def test_repeat_count_marks_low_match_lanes(self):
        self.assertEqual(fr.repeat_count_for("pr15d_v1/10000/absent/k100"),
                         fr.REPEAT_SHORT)
        self.assertEqual(fr.repeat_count_for("pr15d_v1/100000/common/k100"),
                         fr.REPEAT_OTHER)


class RatioDerivationTests(unittest.TestCase):
    def slots(self, base=1000, c=1500, g=1000, p=950, drift=1.0):
        slots = []
        index = 0
        for block, order in enumerate(fr.SCHEDULE, start=1):
            for position, arm in enumerate(order, start=1):
                index += 1
                value = {"A": base, "C": c, "G": g, "P": p}[arm]
                if arm == "A" and position == order.rindex("A") + 1:
                    value = int(value * drift)
                slots.append({"slot_index": index, "block": block,
                              "position": position, "arm": arm,
                              "lanes": [{"id": lane_id,
                                         "summary_ns": {"median": value}}
                                        for lane_id in fr.LANE_IDS]})
        return slots

    def test_block_means_and_ratios(self):
        ratios = fr.derive_f_block_ratios(self.slots())
        entry = ratios[fr.LANE_IDS[0]]
        self.assertAlmostEqual(entry["C/A"][0], 1.5)
        self.assertAlmostEqual(entry["G/A"][0], 1.0)
        self.assertAlmostEqual(entry["P/A"][0], 0.95)
        self.assertAlmostEqual(entry["P/G"][0], 0.95)
        self.assertAlmostEqual(entry["a_drift_median"], 1.0)
        self.assertEqual(entry["a_drift_outliers"], 0)

    def test_drift_is_detected(self):
        ratios = fr.derive_f_block_ratios(self.slots(drift=1.4))
        entry = ratios[fr.LANE_IDS[0]]
        self.assertEqual(entry["a_drift_outliers"], fr.BLOCKS)

    def test_missing_slot_is_rejected(self):
        slots = self.slots()
        slots.pop()
        with self.assertRaises(fr.RunBlocked) as caught:
            fr.derive_f_block_ratios(slots)
        self.assertEqual(caught.exception.rule, "FF_GATE")

    def test_zero_denominator_is_rejected(self):
        slots = self.slots()
        for record in slots:
            for lane in record["lanes"]:
                if record["arm"] == "A":
                    lane["summary_ns"]["median"] = 0
        with self.assertRaises(fr.RunBlocked):
            fr.derive_f_block_ratios(slots)


class SealTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ffinal-seal-")
        self.output = os.path.join(self.root, "campaign")
        os.makedirs(os.path.join(self.output, "raw", "slots"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_missing_raw_file_blocks_sealing(self):
        with self.assertRaises(fr.RunBlocked) as caught:
            fr.seal_f_campaign(self.output)
        self.assertEqual(caught.exception.rule, "FF_SEAL")

    def test_complete_raw_seals(self):
        for relative in fr.REQUIRED_RAW:
            path = os.path.join(self.output, "raw", relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{}")
        fr.seal_f_campaign(self.output)
        seal = json.load(open(os.path.join(self.output, "raw", "seal.json"),
                              encoding="utf-8"))
        self.assertEqual(set(seal["files"]), set(fr.REQUIRED_RAW))
        self.assertEqual(seal["schema"], fr.SEAL_SCHEMA)


class SourceGateTests(unittest.TestCase):
    def test_f_diag_proof_passes_on_committed_source(self):
        report = fr.proof.verify_f_diag(ROOT, fr.F_DIAG)
        self.assertEqual(report["changed_paths"],
                         ["crates/quervant-core/src/search/unified.rs"])
        self.assertEqual(report["generic_attributes"][-1], "#[inline(never)]")
        self.assertEqual(report["generic_body_sha256"],
                         "00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994")

    def test_wrong_f_diag_sha_fails_proof(self):
        with self.assertRaises(fr.proof.FSourceError):
            fr.proof.verify_f_diag(ROOT, fr.CAUSAL)


if __name__ == "__main__":
    unittest.main()
