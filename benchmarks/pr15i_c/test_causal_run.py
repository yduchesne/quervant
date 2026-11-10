#!/usr/bin/env python3
"""PR 15I-C causal controller tests: protocol, schedule, units, mode truth table.

`CM-U01..04` (mode routing) run against the real experimental adapter built from
the committed candidate source, in separate processes, because the Rust gate
resolves the mode once per process.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CANDIDATE_SHA = "658a2dde0e15c17e2b0c92278b5c922f5260fe60"

_CACHE = {}


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


causal = load("pr15i_c_causal_run", "causal_run.py")
proof = load("pr15i_c_causal_proof", "causal_source_proof.py")


def candidate_tree():
    """Read-only worktree of the committed candidate source (cached)."""
    if "tree" in _CACHE:
        return _CACHE["tree"]
    path = os.path.join(ROOT, "target", "pr15i-c", "causal-test-worktree")
    if os.path.isdir(path):
        subprocess.run(["git", "-C", ROOT, "worktree", "remove", "--force", path],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(path, ignore_errors=True)
    subprocess.run(["git", "-C", ROOT, "worktree", "add", "--detach", path,
                    CANDIDATE_SHA], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    _CACHE["tree"] = path
    return path


def causal_adapter():
    """Build the experimental adapter once; cached for the test run."""
    if "adapter" in _CACHE:
        return _CACHE["adapter"]
    tree = candidate_tree()
    arm_dir = os.path.join(ROOT, "target", "pr15i-c", "causal-test-build")
    record = causal.build_causal_adapter(tree, arm_dir)
    index_dir = build_fixture_index(record["binary"])
    _CACHE["adapter"] = (record["binary"], index_dir)
    return _CACHE["adapter"]


def build_fixture_index(binary):
    if "index" in _CACHE:
        return _CACHE["index"]
    directory = os.path.join(ROOT, "target", "pr15i-c", "causal-test-index")
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory, exist_ok=True)
    corpus = os.path.join(directory, "corpus.tsv")
    with open(corpus, "w", encoding="utf-8") as handle:
        handle.write("doc_id\tkey\tgroup\tbody\tpayload\n")
        for position in range(40):
            handle.write(f"d{position:04}\tcommon\tg\tbody{position}\tp{position}\n")
        for position in range(40, 80):
            handle.write(f"d{position:04}\tother\tg\tbody{position}\tp{position}\n")
    index_dir = os.path.join(directory, "index")
    payload = json.dumps({"request_id": "build", "op": "build",
                          "corpus_path": corpus, "index_dir": index_dir}) + "\n"
    result = subprocess.run([binary], input=payload, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(f"fixture build failed: {result.stderr[-500:]}")
    _CACHE["index"] = index_dir
    return index_dir


def tearDownModule():
    _CACHE.clear()


class ProtocolTests(unittest.TestCase):
    def test_frozen_protocol_loads(self):
        protocol = causal.load_protocol(ROOT)
        self.assertEqual(protocol["schema"], "pr15i-c-causal-v1")
        self.assertEqual(protocol["arm_order_by_block"],
                         ["ABCCBA", "BCAACB", "CABBAC", "ACBBCA"])
        self.assertEqual(protocol["final_pr15ic_acceptance_changed"], False)

    def test_protocol_hash_is_recorded_and_stable(self):
        first = causal.protocol_digest(ROOT)
        self.assertEqual(first, causal.protocol_digest(ROOT))
        self.assertEqual(len(first), 64)

    def test_schedule_and_counts_match_the_plan(self):
        self.assertEqual(causal.SLOTS, 24)
        self.assertEqual(causal.SLOTS * len(causal.LANE_IDS) * causal.UNBATCHED_SAMPLES, 4320)
        self.assertEqual(causal.SLOTS * len(causal.LANE_IDS) * causal.BATCHED_SAMPLES, 2160)
        self.assertEqual(causal.SLOTS * 10 * (4 * 100 + 5 * 1), 97200)
        self.assertEqual(causal.SLOTS * len(causal.LANE_IDS) * causal.WARMUPS, 1080)
        for order in causal.ARM_ORDER_BY_BLOCK:
            self.assertEqual(sorted(order), sorted("AABBCC"))

    def test_protocol_drift_is_rejected(self):
        for key, value in (("arm_order_by_block", ["AAAAAA"]),
                           ("slots_per_campaign", 23),
                           ("classification_uses_unbatched_only", False),
                           ("final_pr15ic_acceptance_changed", True),
                           ("short_lane_repeat_count", 200)):
            with tempfile.TemporaryDirectory() as directory:
                root = os.path.join(directory, "root")
                os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
                with open(os.path.join(ROOT, causal.PROTOCOL_REL), encoding="utf-8") as handle:
                    protocol = json.load(handle)
                protocol[key] = value
                with open(os.path.join(root, causal.PROTOCOL_REL), "w",
                          encoding="utf-8") as handle:
                    json.dump(protocol, handle)
                with self.assertRaises(causal.RunBlocked):
                    causal.load_protocol(root)

    def test_original_acceptance_protocol_is_untouched(self):
        self.assertEqual(
            causal.sha256_file(os.path.join(ROOT, "benchmarks", "pr15i_c", "protocol.json")),
            "5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e")


class PathAndCliTests(unittest.TestCase):
    def test_idle_confirmation_is_required(self):
        args = causal.build_parser().parse_args([
            "--checkout-root", ROOT, "--baseline-sha", causal.BASELINE_SHA,
            "--candidate-sha", CANDIDATE_SHA, "--regime", "unbatched",
            "--out", os.path.join(ROOT, "target", "never-created")])
        self.assertEqual(causal.execute(args), 3)

    def test_path_guards(self):
        with self.assertRaises(causal.RunBlocked):
            causal.validate_output(ROOT, "target/pr15i-c/causal-campaigns-v1/x")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(causal.RunBlocked):
                causal.validate_output(ROOT, os.path.join(directory, "x"))
            existing = os.path.join(directory, "target", "pr15i-c",
                                    "causal-campaigns-v1", "causal-unbatched-01")
            os.makedirs(existing)
            with self.assertRaises(causal.RunBlocked):
                causal.validate_output(directory, existing)

    def test_unknown_campaign_name_is_rejected(self):
        args = causal.build_parser().parse_args([
            "--checkout-root", ROOT, "--baseline-sha", causal.BASELINE_SHA,
            "--candidate-sha", CANDIDATE_SHA, "--regime", "unbatched",
            "--out", os.path.join(ROOT, "target", "pr15i-c", "causal-campaigns-v1",
                                  "wrong-name"), "--idle-confirmed"])
        with self.assertRaises(causal.RunBlocked):
            causal.execute(args)

    def test_campaign_order_is_frozen(self):
        self.assertEqual([name for name, _ in causal.CAMPAIGN_IDS],
                         ["causal-unbatched-01", "causal-batched-01",
                          "causal-unbatched-02", "causal-batched-02"])


class ModeEnvironmentTests(unittest.TestCase):
    def test_child_environments_are_exactly_one_allowlisted_variable(self):
        enabled = causal.child_environment("B")
        disabled = causal.child_environment("C")
        plain = causal.child_environment("A")
        self.assertEqual(enabled[causal.MODE_VARIABLE], "enabled")
        self.assertEqual(disabled[causal.MODE_VARIABLE], "disabled")
        self.assertNotIn(causal.MODE_VARIABLE, plain)
        for env in (enabled, disabled, plain):
            for key in ("RUSTFLAGS", "RUST_LOG", "LLVM_PROFILE_FILE"):
                self.assertNotIn(key, env)

    def test_adapter_command_pinning(self):
        pinned = {"mode": "PINNED", "adapter_cpu": 3, "controller_cpu": 4}
        command = causal.adapter_command("/bin/a", "/tmp/i", pinned)
        self.assertEqual(command[:4], ["taskset", "-c", "3", "/bin/a"])
        self.assertEqual(causal.adapter_command("/bin/a", "/tmp/i", {"mode": "UNPINNED"}),
                         ["/bin/a", "--index-dir", "/tmp/i"])

    def test_environ_is_never_mutated(self):
        before = dict(os.environ)
        causal.child_environment("B")
        causal.child_environment("C")
        self.assertEqual(dict(os.environ), before)


class CMU01to04ModeTruthTable(unittest.TestCase):
    """Mode routing and typed error per process, against the real adapter."""

    def probe(self, env_mode):
        binary, index_dir = causal_adapter()
        env = dict(os.environ)
        env.pop(causal.MODE_VARIABLE, None)
        if env_mode is not None:
            env[causal.MODE_VARIABLE] = env_mode
        request = json.dumps({"request_id": "p", "op": "query", "field": "key",
                              "term": "common", "k": 10, "mode": "warm"}) + "\n"
        result = subprocess.run([binary, "--index-dir", index_dir], input=request,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env, check=False)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_cm_u01_feature_build_accepts_enabled(self):
        reply = self.probe("enabled")
        self.assertEqual(reply["status"], "ok")
        self.assertEqual(reply["total_hits"], 40)

    def test_cm_u02_feature_build_accepts_disabled(self):
        reply = self.probe("disabled")
        self.assertEqual(reply["status"], "ok")
        self.assertEqual(reply["total_hits"], 40)

    def test_cm_u03_missing_mode_is_a_typed_error(self):
        reply = self.probe(None)
        self.assertEqual(reply["status"], "error")
        self.assertIn("invalid PR15IC causal experiment mode",
                      json.dumps(reply["error"]))

    def test_cm_u04_malformed_mode_is_a_typed_error(self):
        for value in ("enabledish", "ENABLED", "", "1"):
            reply = self.probe(value)
            self.assertEqual(reply["status"], "error", value)
            self.assertIn("invalid PR15IC causal experiment mode",
                          json.dumps(reply["error"]))

    def test_cm_u04_ineligible_shape_is_generic_in_both_modes(self):
        # A descending sort is never eligible, so both modes must agree exactly.
        binary, index_dir = causal_adapter()
        outputs = []
        for mode in ("enabled", "disabled"):
            env = dict(os.environ)
            env[causal.MODE_VARIABLE] = mode
            request = json.dumps({"request_id": "p", "op": "query", "field": "key",
                                  "term": "common", "k": 5, "mode": "warm"}) + "\n"
            result = subprocess.run([binary, "--index-dir", index_dir], input=request,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, env=env, check=False)
            reply = json.loads(result.stdout.strip().splitlines()[-1])
            outputs.append((reply["doc_ids"], reply["total_hits"]))
        self.assertEqual(outputs[0], outputs[1])


class CMU33to36SourceAndBinary(unittest.TestCase):
    def test_cm_u33_generic_body_digest_and_attributes(self):
        report = proof.verify_causal_source(ROOT, CANDIDATE_SHA)
        self.assertEqual(report["generic_body_sha256"],
                         proof.EXPECTED_GENERIC_BODY_SHA)
        self.assertFalse(any(item.startswith("#[inline(")
                             for item in report["generic_attributes"]))

    def test_cm_u34_experimental_feature_is_not_default(self):
        source = proof.read_at(ROOT, CANDIDATE_SHA,
                               "crates/quervant-core/Cargo.toml")
        default_line = next(line for line in source.splitlines()
                            if line.startswith("default = "))
        self.assertNotIn("pr15ic-causal", default_line)
        self.assertIn("pr15ic-causal = []", source)

    def test_cm_u35_gate_is_behind_the_feature(self):
        unified = proof.read_at(ROOT, CANDIDATE_SHA,
                                "crates/quervant-core/src/search/unified.rs")
        gate_index = unified.index("fn pr15ic_causal_enabled(")
        preceding = unified[:gate_index]
        self.assertIn('#[cfg(feature = "pr15ic-causal")]', preceding[-400:])
        self.assertIn("OnceLock", unified)
        self.assertEqual(unified.count("QUERVANT_PR15IC_CAUSAL_MODE"), 2)

    def test_cm_u36_b_and_c_share_one_adapter_path(self):
        # The controller must build one BC adapter and hand the same path to B and C.
        with open(os.path.join(HERE, "causal_run.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertEqual(source.count("build_causal_adapter("), 2)  # definition + call
        self.assertIn('"B": {"binary": bc["adapter"]["binary"]', source)
        self.assertIn('"C": {"binary": bc["adapter"]["binary"]', source)


class RatioArithmeticTests(unittest.TestCase):
    def synthetic_slots(self, ba, ca, unit="unbatched"):
        samples = causal.BATCHED_SAMPLES if unit == "batched" else causal.UNBATCHED_SAMPLES
        slots = []
        for block in range(1, causal.BLOCKS + 1):
            for position in range(1, causal.SLOTS_PER_BLOCK + 1):
                arm = causal.ARM_ORDER_BY_BLOCK[block - 1][position - 1]
                lanes = []
                for lane_id in causal.LANE_IDS:
                    factor = 1.0
                    if lane_id in causal.LOW_MATCH_LANES:
                        factor = {"A": 1.0, "B": ba, "C": ca}[arm]
                    value = int(10_000_000 * factor)
                    values = [value] * samples
                    lanes.append({
                        "id": lane_id,
                        "summary_ns": {"median": causal.base.pr15d_run.summarize(
                            values)["median"]},
                        "samples_ns": values,
                    })
                slots.append({"block": block, "arm": arm, "lanes": lanes})
        return slots

    def test_ratios_and_medians(self):
        slots = self.synthetic_slots(1.7, 1.0)
        ratios = causal.derive_causal_ratios(slots, causal.LANE_IDS)
        lane = causal.LOW_MATCH_LANES[0]
        self.assertAlmostEqual(ratios[lane]["campaign_medians"]["B/A"], 1.7, places=6)
        self.assertAlmostEqual(ratios[lane]["campaign_medians"]["C/A"], 1.0, places=6)
        self.assertAlmostEqual(ratios[lane]["campaign_medians"]["B/C"], 1.7, places=6)
        other = causal.LANE_IDS[2]
        self.assertAlmostEqual(ratios[other]["campaign_medians"]["B/A"], 1.0, places=6)

    def test_a_drift_sentinel_is_neutral(self):
        slots = self.synthetic_slots(1.0, 1.0)
        drift = causal.a_drift_sentinel(slots, causal.LANE_IDS)
        for lane_id in causal.LANE_IDS:
            self.assertAlmostEqual(drift[lane_id]["campaign_median"], 1.0, places=12)

    def test_missing_slot_sample_is_rejected(self):
        slots = self.synthetic_slots(1.0, 1.0)
        slots[0]["lanes"] = [lane for lane in slots[0]["lanes"]
                             if lane["id"] != causal.LANE_IDS[0]]
        with self.assertRaises(causal.RunBlocked):
            causal.derive_causal_ratios(slots, causal.LANE_IDS)


if __name__ == "__main__":
    unittest.main()
