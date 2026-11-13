import copy
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("d3c_policy", os.path.join(HERE, "policy.py"))
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

KS = [1, 10, 32, 64, 100, 128, 256, 512, 1024]
LENS = [8, 32, 128, 1024]
TRACES = ["miss_stable", "duplicate_retained", "churn", "evicted_revisit", "collision_distinct"]
VARIANTS = ["linear", "P0", "P1", "P2", "exact_set"]


def micro(cap1024=1792, key1024=1024 * 1024):
    records = []
    maxima = {}
    for variant in VARIANTS:
        for k in KS:
            cap = cap1024 if k == 1024 else k + 1
            key_bytes = key1024 if k == 1024 else 0
            for length in LENS:
                for trace in TRACES:
                    records.append({
                        "variant": variant, "k": k, "key_len": length, "trace": trace,
                        "median_ns_per_op": 1, "rescan_fraction": 0.0,
                        "rounds": [1, 1, 1, 1, 1],
                        "set_len": k, "set_capacity": cap, "key_bytes": key_bytes,
                    })
                    if variant == "exact_set":
                        maxima[k] = max(maxima.get(k, 0), cap * 40 + key_bytes)
    return {
        "schema": "pr15i-d3c-micro-v1", "records": records,
        "selected_profile": "P2",
        "exact_set_aux_bytes_estimate": {str(k): maxima[k] for k in KS},
        "memory_estimate_note": "test",
        "source_experiment_sha": policy.EXPERIMENT_SHA,
        "protocol_sha256": policy.PROTOCOL_SHA256,
    }


def protocol():
    return policy.load_protocol()


class PolicySelection(unittest.TestCase):
    def test_pm12_h_eligible_with_two_campaigns(self):
        p = protocol()
        ls = policy.lanes(p)
        rs = {}
        for arm in ("L", "P", "H"):
            rs[arm] = {}
            for lane in ls:
                fast = lane["n"] == 100000 and lane["class"] in ("medium", "common")
                ratio = 1.0 if arm == "L" else 0.95
                rs[arm][lane["id"]] = [ratio if fast else 1.0] * 4
        cams = [("synthetic-a", {}, rs), ("synthetic-b", {}, rs)]
        ok, reasons, gm = policy.evaluate_arm("H", 1024, cams, p, ls, 1_120_256)
        self.assertTrue(ok, reasons)
        self.assertTrue(gm)
        self.assertEqual(policy.choose_candidate(["P", "H"], {"P": [0.90], "H": [0.90]}), "P")
        self.assertEqual(policy.choose_candidate(["P", "H"], {"P": [0.95], "H": [0.90]}), "H")
        ok, reasons, _ = policy.evaluate_arm("H", 1024, cams, p, ls, 2_097_153)
        self.assertFalse(ok)
        self.assertTrue(any("EXCLUDED_MEMORY" in r for r in reasons))


class MemoryValidation(unittest.TestCase):
    def validate(self, m):
        return policy.validate_micro_memory(m, protocol(), policy.EXPERIMENT_SHA)

    def assert_not_derivable(self, m):
        with self.assertRaises(SystemExit) as ctx:
            self.validate(m)
        self.assertIn("POLICY_NOT_DERIVABLE", str(ctx.exception))

    def test_pm01_valid_full_grid(self):
        mem = self.validate(micro())
        self.assertEqual(mem["1024"], 1_120_256)
        self.assertLessEqual(mem["1024"], 2_097_152)

    def test_pm02_guard_boundary_inclusive(self):
        cap = 1792
        mem = self.validate(micro(cap1024=cap, key1024=2_097_152 - cap * 40))
        self.assertEqual(mem["1024"], 2_097_152)

    def test_pm03_guard_plus_one_excludes(self):
        cap = 1792
        m = micro(cap1024=cap, key1024=2_097_152 - cap * 40 + 1)
        self.assertEqual(self.validate(m)["1024"], 2_097_153)

    def test_pm04_missing_record_not_derivable(self):
        m = micro()
        m["records"].pop()
        self.assert_not_derivable(m)

    def test_pm05_duplicate_record_not_derivable(self):
        m = micro()
        m["records"].append(copy.deepcopy(m["records"][0]))
        self.assert_not_derivable(m)

    def test_pm06_invalid_integers_not_derivable(self):
        for field, value in (("key_bytes", True), ("set_capacity", -1), ("set_len", -2)):
            m = micro()
            m["records"][0][field] = value
            self.assert_not_derivable(m)

    def test_pm07_len_above_capacity_not_derivable(self):
        m = micro()
        m["records"][0]["set_len"] = m["records"][0]["set_capacity"] + 1
        self.assert_not_derivable(m)

    def test_pm08_map_mismatch_not_derivable(self):
        m = micro()
        m["exact_set_aux_bytes_estimate"]["1024"] += 1
        self.assert_not_derivable(m)

    def test_pm09_wrong_source_or_profile_not_derivable(self):
        m = micro()
        m["source_experiment_sha"] = "0" * 40
        self.assert_not_derivable(m)
        m = micro()
        m["selected_profile"] = "P1"
        self.assert_not_derivable(m)

    def test_pm11_no_official_series_not_derivable(self):
        micro_path = os.path.join(policy.TOOLING_ROOT, "target/pr15i-d3-c/micro-05/micro.json")
        if not os.path.isfile(micro_path):
            self.skipTest("fresh micro evidence unavailable")
        series = os.path.join(policy.TOOLING_ROOT, "target/pr15i-d3-c/empty-series")
        os.makedirs(series, exist_ok=True)
        out = os.path.join(policy.TOOLING_ROOT, "target/pr15i-d3-c/pm11-policy.json")
        with self.assertRaises(SystemExit) as ctx:
            policy.main(["--series-root", series, "--micro-json", micro_path, "--out", out])
        self.assertIn("POLICY_NOT_DERIVABLE", str(ctx.exception))
        self.assertFalse(os.path.exists(out))

    def test_pm10_exploratory_input_refused(self):
        path = os.path.join(policy.TOOLING_ROOT, "docs/pr-artifacts/pr-15i-d3-c/exploratory.md")
        with self.assertRaises(SystemExit) as ctx:
            policy.load_micro(path, protocol(), policy.EXPERIMENT_SHA)
        self.assertIn("POLICY_NOT_DERIVABLE", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
