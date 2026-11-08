"""Deterministic unit tests for the PR 15I-B controller gate math."""

import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = load("pr15i_b_run_under_test", os.path.join(HERE, "run.py"))


def arm(factor=1.0, rare_factor=1.0, stored=1_000_000, total=10_000_000):
    sizes = {
        "layouts": {
            "10000": {"stored_bytes": stored // 10, "committed_index_bytes": total // 10,
                      "stored_version": 2 if stored == 1_000_000 else 1, "codec_id": 1,
                      "required_features": [[1, 1], [13, 1]]},
            "100000": {"stored_bytes": stored, "committed_index_bytes": total,
                       "stored_version": 2, "codec_id": 1,
                       "required_features": [[1, 1], [13, 1]]},
        }
    }
    blocks = {}
    for kind, metric in (("reopen", "open_ns"), ("build_commit", "index_ns"), ("remote", "open_ns")):
        entries = []
        for block in range(1, 5):
            samples = []
            for sample in range(2):
                value = int(1_000_000_000 * factor)
                samples.append({
                    "block": block, "sample": sample, metric: value,
                    "commit_ns": value, "maxrss_bytes": 100_000_000,
                    "documents_indexed": 100_000, "documents_verified": 100_000,
                    "index_bytes": 1, "measured_index_bytes": 1, "documents": 100_000,
                    "open_ns": value,
                })
            entries.append({"block": block, "samples": samples})
        blocks[kind] = entries
    selected = []
    for block in range(1, 5):
        samples = []
        for sample in range(2):
            samples.append({str(k): {"selected_ns": int(1_000_000 * factor)} for k in (1, 10, 100)})
        selected.append({"block": block, "samples": samples})
    blocks["selected"] = selected
    warm = []
    for block in range(1, 5):
        for _ in range(2):
            warm.append({"block": block, "trial": {"lanes": [
                {"id": lane, "summary_ns": {"median": int(1_000_000 * (rare_factor if "/rare/" in lane or "/medium/" in lane else factor))}}
                for lane in run.LANE_IDS]}})
    return {"source_sha": "a" * 40, "sizes": sizes, "blocks": blocks, "warm": warm}


class GateTests(unittest.TestCase):
    def test_improving_candidate_is_eligible(self):
        a = arm(stored=9_662_513, total=23_748_601)
        b = arm(stored=1_661_455, total=15_748_601)
        report = run.derive(a, b, "lz4")
        self.assertEqual(report["decision"], "B_CANDIDATE_QUALIFIED")
        self.assertLess(report["combined_cost"], 1.0)

    def test_rare_regression_is_ineligible(self):
        a = arm(stored=9_662_513, total=23_748_601)
        b = arm(stored=1_661_455, total=15_748_601, rare_factor=1.6)
        report = run.derive(a, b, "lz4")
        self.assertEqual(report["gates"]["B-P06"], "FAIL")
        self.assertEqual(report["decision"], "B_CANDIDATE_INELIGIBLE")

    def test_storage_failure_is_ineligible(self):
        a = arm(stored=9_662_513, total=23_748_601)
        b = arm(stored=9_000_000, total=23_000_000)
        report = run.derive(a, b, "lz4")
        self.assertEqual(report["gates"]["B-P03"], "FAIL")
        self.assertEqual(report["decision"], "B_CANDIDATE_INELIGIBLE")

    def test_protocol_matches_controller(self):
        protocol = run.load_protocol(os.path.dirname(os.path.dirname(HERE)))
        self.assertEqual(protocol["gate_limits"], run.LIMITS)
        self.assertEqual(protocol["selected_k"], list(run.SELECTED_K))


if __name__ == "__main__":
    unittest.main()
