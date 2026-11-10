#!/usr/bin/env python3
"""PR 15I-C dispatch-isolation — source-proof, codegen and controller tests.

Covers DC-V05..V12 (source/feature/mode), DC-V13..V16 (binary identity),
DC-U01..U12 (arm mode truth tables against the real built adapters),
DC-V21..V24 (median/pair arithmetic) and DC-V29..V32 (codegen/trampoline).
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

_CACHE = {}


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proof = load("pr15i_c_dispatch_source_proof_t", "dispatch_source_proof.py")
causal = load("pr15i_c_dispatch_run_t", "dispatch_run.py")
codegen = load("pr15i_c_dispatch_codegen_t", "dispatch_codegen_capture.py")


def worktree(sha, tag):
    path = os.path.join(ROOT, "target", "pr15i-c", "worktrees", f"dispatchtest-{tag}")
    if os.path.isdir(path):
        subprocess.run(["git", "-C", ROOT, "worktree", "remove", "--force", path],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(path, ignore_errors=True)
    subprocess.run(["git", "-C", ROOT, "worktree", "add", "--detach", path, sha],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def adapter(arm):
    """Build the arm's single-query adapter once and build a fixture index."""
    if arm in _CACHE:
        return _CACHE[arm]
    tree = worktree(proof.BASE_A if arm == "A" else proof.__dict__[f"{arm}_SHA"],
                    f"build-{arm}")
    arm_dir = os.path.join(ROOT, "target", "pr15i-c", "dispatchtest-build", arm)
    feature = causal.ARM_FEATURES[arm]
    if feature:
        manifest = os.path.join(tree, "benchmarks", "pr15d", "adapters", "quervant",
                                "Cargo.toml")
        command = ["cargo", "build", "--release", "--offline", "--manifest-path",
                   manifest, "--features", f"quervant-core/{feature}",
                   "--target-dir", os.path.join(arm_dir, "build")]
    else:
        manifest = os.path.join(tree, "benchmarks", "pr15d", "adapters", "quervant",
                                "Cargo.toml")
        command = ["cargo", "build", "--release", "--offline", "--manifest-path",
                   manifest, "--target-dir", os.path.join(arm_dir, "build")]
    os.makedirs(os.path.join(arm_dir, "build"), exist_ok=True)
    result = subprocess.run(command, cwd=os.path.dirname(manifest),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(f"{arm} build failed: {result.stdout[-800:]}")
    binary = os.path.join(arm_dir, "build", "release", "pr15d-quervant-adapter")
    index_dir = build_index(binary, arm)
    _CACHE[arm] = (binary, index_dir)
    return _CACHE[arm]


def build_index(binary, arm):
    directory = os.path.join(ROOT, "target", "pr15i-c", "dispatchtest-fixture", arm)
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
                            stderr=subprocess.PIPE, text=True,
                            env=causal.arm_environment(arm), check=False)
    if result.returncode != 0:
        raise AssertionError(f"{arm} fixture build failed: {result.stderr[-400:]}")
    return index_dir


def query(arm, mode_override="default"):
    binary, index_dir = adapter(arm)
    env = causal.arm_environment(arm)
    if mode_override == "default":
        pass
    elif mode_override == "absent":
        for variable in causal.ARM_MODE_VARIABLES.values():
            if variable:
                env.pop(variable, None)
    else:
        variable = causal.ARM_MODE_VARIABLES[arm]
        if variable is None:
            env[f"QUERVANT_PR15IC_{mode_override.upper()}"] = "enabled"
        else:
            env[variable] = mode_override
    request = json.dumps({"request_id": "q", "op": "query", "field": "key",
                          "term": "common", "k": 10, "mode": "warm"}) + "\n"
    result = subprocess.run([binary, "--index-dir", index_dir], input=request,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env, check=False)
    return json.loads(result.stdout.strip().splitlines()[-1])


class SourceProofTests(unittest.TestCase):
    def test_dv05_all_arm_sources_and_ancestry(self):
        report = proof.verify_all(ROOT)
        self.assertEqual(set(report["generic_body_sha256"]), {"A", "C", "D", "E"})
        for value in report["generic_body_sha256"].values():
            self.assertEqual(value, proof.EXPECTED_GENERIC_BODY_SHA)

    def test_dv06_generic_body_and_attributes_pinned(self):
        for sha in (proof.BASE_A, proof.C_SHA, proof.D_SHA, proof.E_SHA):
            digest, attrs = proof.verify_generic_body(ROOT, sha)
            self.assertEqual(digest, proof.EXPECTED_GENERIC_BODY_SHA)
            self.assertFalse(any(item.startswith("#[inline(") for item in attrs))

    def test_dv07_d_one_expression_diff(self):
        report = proof.verify_d(ROOT)
        self.assertEqual(report["d_changed_paths"], [proof.UNIFIED])

    def test_dv08_e_two_file_scope(self):
        report = proof.verify_e(ROOT)
        self.assertEqual(sorted(report["e_changed_paths"]),
                         sorted([proof.UNIFIED, proof.MANIFEST]))

    def test_dv09_feature_flags(self):
        report = proof.verify_all(ROOT)
        self.assertEqual(report["features"], {"A": [], "C": ["pr15ic-causal"],
                                              "D": ["pr15ic-causal"],
                                              "E": ["pr15ic-dispatch-isolation"]})

    def test_dv10_e_has_no_physical_operator(self):
        source = proof.read_at(ROOT, proof.E_SHA, proof.UNIFIED)
        self.assertNotIn("fn collect_exact_term_physical(", source)
        self.assertNotIn("for_each_exact_term_score_with", source)

    def test_dv11_d_literal_false_is_present(self):
        source = proof.read_at(ROOT, proof.D_SHA, proof.UNIFIED)
        self.assertIn("if false && shape_eligible", source)

    def test_dv12_e_predicate_matches_c_minus_guard(self):
        report = proof.verify_e(ROOT)
        self.assertEqual(report["generic_body_sha256"],
                         proof.EXPECTED_GENERIC_BODY_SHA)

    def test_non_descendant_arm_is_rejected(self):
        # The historical G control is not a descendant of C.
        with self.assertRaises(proof.DispatchSourceError):
            proof.verify_commits(ROOT, proof.BASE_A, proof.C_SHA,
                                 "50b56e9fe7b22bb266ca7b0d9e209500dfc785ff")
        # E must not descend from the causal candidate C.
        with self.assertRaises(proof.DispatchSourceError):
            proof.verify_commits(ROOT, proof.BASE_A, proof.C_SHA, proof.D_SHA,
                                 proof.C_SHA)

    def test_unknown_commit_is_rejected(self):
        with self.assertRaises(proof._source_proof.SourceProofError):
            proof.verify_generic_body(ROOT, "0" * 40)


class ModeTruthTableTests(unittest.TestCase):
    """DC-U01..U12: each arm's real adapter, separate processes."""

    def test_dv13_a_ignores_experiment_variables(self):
        baseline = query("A")
        self.assertEqual(baseline["status"], "ok")
        self.assertEqual(query("A", "enabled")["doc_ids"], baseline["doc_ids"])
        self.assertEqual(query("A", "bogus")["status"], "ok")

    def test_dv14_c_disabled_matches_enabled_and_errors_on_invalid(self):
        disabled = query("C", "disabled")
        enabled = query("C", "enabled")
        self.assertEqual(disabled["status"], "ok")
        self.assertEqual(disabled["doc_ids"], enabled["doc_ids"])
        self.assertEqual(disabled["total_hits"], enabled["total_hits"])
        for mode in ("absent", "bogus"):
            reply = query("C", mode)
            self.assertEqual(reply["status"], "error")
            self.assertIn("invalid PR15IC causal experiment mode",
                          json.dumps(reply["error"]))

    def test_dv15_d_ignores_every_mode_value(self):
        baseline = query("D", "disabled")
        self.assertEqual(baseline["status"], "ok")
        for mode in ("enabled", "absent", "bogus"):
            reply = query("D", mode)
            self.assertEqual(reply["status"], "ok", mode)
            self.assertEqual(reply["doc_ids"], baseline["doc_ids"], mode)

    def test_dv16_e_modes(self):
        disabled = query("E", "disabled")
        enabled = query("E", "enabled")
        self.assertEqual(disabled["status"], "ok")
        self.assertEqual(enabled["status"], "ok")
        self.assertEqual(disabled["doc_ids"], enabled["doc_ids"])
        for mode in ("absent", "bogus"):
            reply = query("E", mode)
            self.assertEqual(reply["status"], "error")
            self.assertIn("invalid PR15IC dispatch isolation mode",
                          json.dumps(reply["error"]))

    def test_dv17_cross_arm_equal_results(self):
        baseline = query("A")["doc_ids"]
        for arm, mode in (("C", "disabled"), ("D", "disabled"), ("E", "disabled")):
            self.assertEqual(query(arm, mode)["doc_ids"], baseline, arm)


class BinaryIdentityTests(unittest.TestCase):
    def test_dv18_four_distinct_binaries(self):
        hashes = {}
        for arm in causal.ARMS:
            binary, _index = adapter(arm)
            hashes[arm] = causal.sha256_file(binary)
        self.assertEqual(len(set(hashes.values())), 4)

    def test_dv19_mutated_binary_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "bin")
            with open(path, "wb") as handle:
                handle.write(b"elf")
            digest = causal.sha256_file(path)
            with open(path, "ab") as handle:
                handle.write(b"x")
            self.assertNotEqual(causal.sha256_file(path), digest)

    def test_dv20_arm_environment_is_exactly_one_variable(self):
        self.assertEqual(causal.arm_environment("A").get(
            causal.ARM_MODE_VARIABLES["C"]), None)
        self.assertEqual(causal.arm_environment("C")[causal.ARM_MODE_VARIABLES["C"]],
                         "disabled")
        self.assertEqual(causal.arm_environment("D")[causal.ARM_MODE_VARIABLES["D"]],
                         "disabled")
        self.assertEqual(causal.arm_environment("E")[causal.ARM_MODE_VARIABLES["E"]],
                         "disabled")
        self.assertNotIn(causal.ARM_MODE_VARIABLES["C"], causal.arm_environment("E"))


class ArithmeticTests(unittest.TestCase):
    def synthetic_slots(self, values, unit="unbatched"):
        samples = causal.BATCHED_SAMPLES if unit == "batched" else causal.UNBATCHED_SAMPLES
        slots = []
        index = 0
        for block in range(1, causal.BLOCKS + 1):
            for position in range(1, causal.SLOTS_PER_BLOCK + 1):
                index += 1
                arm = causal.SCHEDULE[block - 1][position - 1]
                lanes = []
                for lane_id in causal.LANE_IDS:
                    factor = values.get(lane_id, {}).get(arm, 1.0)
                    data = [int(10_000_000 * factor)] * samples
                    lanes.append({"id": lane_id, "samples_ns": data,
                                  "summary_ns": causal.base.pr15d_run.summarize(data)})
                slots.append({"slot_index": index, "block": block,
                              "position": position, "arm": arm, "lanes": lanes})
        return slots

    def test_dv21_ratios_from_block_means(self):
        values = {lane: {"C": 1.5, "D": 1.2, "E": 1.0} for lane in causal.LANE_IDS}
        ratios = causal.derive(self.synthetic_slots(values))
        lane = causal.LOW_MATCH_LANES[0]
        self.assertAlmostEqual(ratios[lane]["medians"]["C/A"], 1.5, places=6)
        self.assertAlmostEqual(ratios[lane]["medians"]["D/A"], 1.2, places=6)
        self.assertAlmostEqual(ratios[lane]["medians"]["E/A"], 1.0, places=6)
        self.assertAlmostEqual(ratios[lane]["a_drift_median"], 1.0, places=12)

    def test_dv22_nearest_rank_median_is_not_python_median(self):
        from benchmarks.pr15i_c.verify_dispatch import nearest_rank_median
        self.assertEqual(nearest_rank_median(list(range(1, 21))), 10)
        self.assertEqual(nearest_rank_median([1, 2, 3, 100]), 2)

    def test_dv23_missing_slot_sample_is_rejected(self):
        slots = self.synthetic_slots({})
        slots[0]["lanes"] = [lane for lane in slots[0]["lanes"]
                             if lane["id"] != causal.LANE_IDS[0]]
        with self.assertRaises(causal.RunBlocked):
            causal.derive(slots)

    def test_dv24_schedule_is_balanced(self):
        for block in causal.SCHEDULE:
            self.assertEqual(len(block), causal.SLOTS_PER_BLOCK)
            for arm in causal.ARMS:
                self.assertEqual(block.count(arm), 2)


class CodegenCaptureTests(unittest.TestCase):
    def test_dv25_capture_records_hashes_and_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = os.path.join(directory, "adapter")
            with open(binary, "wb") as handle:
                handle.write(b"\x7fELF-synthetic")
            payload = codegen.capture({"A": binary}, os.path.join(directory, "out"))
            self.assertEqual(payload["schema"], codegen.SCHEMA)
            self.assertEqual(len(payload["arms"]), 4)
            arm_a = next(arm for arm in payload["arms"] if arm["arm"] == "A")
            self.assertEqual(arm_a["binary_sha256"], causal.sha256_file(binary))
            self.assertIn("perf_state", payload)

    def test_dv26_missing_binary_is_typed(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = codegen.capture({}, os.path.join(directory, "out"))
            states = {arm["arm"]: arm["state"] for arm in payload["arms"]}
            self.assertTrue(all(state == "BINARY_MISSING" for state in states.values()))

    def test_dv27_structural_checks_flags(self):
        payload = {"method_presence": {
            "A": {}, "C": {"collect_exact_term_physical": "PRESENT"},
            "D": {}, "E": {"collect_mixed_dispatch_probe": "PRESENT"}}}
        checks = codegen.structural_checks(payload)
        self.assertTrue(checks["e_trampoline_present"])
        self.assertTrue(checks["c_physical_present"])
        self.assertFalse(checks["d_physical_present"])
        self.assertTrue(checks["e_physical_absent"])

    def test_dv28_capture_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "out")
            codegen.capture({}, out)
            with self.assertRaises(SystemExit):
                codegen.capture({}, out)


class ProtocolGuardTests(unittest.TestCase):
    def test_dv29_protocol_loads_and_is_balanced(self):
        protocol = causal.load_protocol(ROOT)
        self.assertEqual(protocol["schema"], "pr15i-c-dispatch-isolation-v1")
        self.assertEqual(protocol["d_source"], proof.D_SHA)
        self.assertEqual(protocol["e_source"], proof.E_SHA)

    def test_dv30_placeholder_sha_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "root")
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
            with open(os.path.join(ROOT, causal.PROTOCOL_REL), encoding="utf-8") as handle:
                protocol = json.load(handle)
            protocol["d_source"] = "FROM_PINNED_D_SHA"
            with open(os.path.join(root, causal.PROTOCOL_REL), "w",
                      encoding="utf-8") as handle:
                json.dump(protocol, handle)
            with self.assertRaises(causal.RunBlocked):
                causal.load_protocol(root)

    def test_dv31_threshold_drift_is_rejected(self):
        for key, value in (("candidate_neutral_median_ceiling", 1.5),
                           ("A_A_within_campaign_lane_median_max", 1.5),
                           ("100k_committed_index_bytes", 1),
                           ("batched_repeat_count_absent_rare", 200)):
            with tempfile.TemporaryDirectory() as directory:
                root = os.path.join(directory, "root")
                os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
                with open(os.path.join(ROOT, causal.PROTOCOL_REL),
                          encoding="utf-8") as handle:
                    protocol = json.load(handle)
                protocol[key] = value
                with open(os.path.join(root, causal.PROTOCOL_REL), "w",
                          encoding="utf-8") as handle:
                    json.dump(protocol, handle)
                with self.assertRaises(causal.RunBlocked):
                    causal.load_protocol(root)

    def test_dv32_unbalanced_schedule_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "root")
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
            with open(os.path.join(ROOT, causal.PROTOCOL_REL), encoding="utf-8") as handle:
                protocol = json.load(handle)
            protocol["arm_order_by_block"][0] = "AAAAAAAA"
            with open(os.path.join(root, causal.PROTOCOL_REL), "w",
                      encoding="utf-8") as handle:
                json.dump(protocol, handle)
            with self.assertRaises(causal.RunBlocked):
                causal.load_protocol(root)


def tearDownModule():
    _CACHE.clear()


if __name__ == "__main__":
    unittest.main()
