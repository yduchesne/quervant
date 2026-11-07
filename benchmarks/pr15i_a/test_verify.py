"""Adversarial tests for the PR 15I-A read-only verifier.

Synthetic campaign directories live under the ignored
``target/pr15i-a/campaigns`` tree and are removed after each test. No
production benchmark evidence is created or modified.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load("pr15i_a_run_for_verify_tests", os.path.join(HERE, "run.py"))
verify = _load("pr15i_a_verify_under_test", os.path.join(HERE, "verify.py"))
test_run = _load("pr15i_a_run_test_helpers", os.path.join(HERE, "test_run.py"))


def _write(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _seal(campaign: str, files: list[str]) -> dict:
    return {
        "schema": run.SEAL_SCHEMA,
        "files": {
            relative: run.sha256_file(os.path.join(campaign, "raw", relative))
            for relative in files
        },
    }


def make_campaign(tag: str, a=None, b=None, tamper=None) -> tuple[str, str]:
    a = a or test_run.synthetic_arm()
    b = b or test_run.synthetic_arm(sidecar=4_800_090, total=29_416_770, sha="b" * 40)
    report, _ = run.derive(a, b)
    campaign = os.path.join(
        ROOT, "target", "pr15i-a", "campaigns", f"unit-{tag}-{os.getpid()}"
    )
    if os.path.isdir(campaign):
        shutil.rmtree(campaign)
    os.makedirs(os.path.join(campaign, "raw", "slots"))
    _write(
        os.path.join(campaign, "raw", "manifest.json"),
        {
            "schema": run.SCHEMA,
            "sources": {"A": a["source_sha"], "B": b["source_sha"]},
            "binary_sha256": {
                "A": {
                    "adapter": a["adapter_sha256"],
                    "reopen": a["reopen_sha256"],
                    "remote": a["remote_sha256"],
                },
                "B": {
                    "adapter": b["adapter_sha256"],
                    "reopen": b["reopen_sha256"],
                    "remote": b["remote_sha256"],
                },
            },
            "sizes": report["sizes"],
        },
    )
    _write(os.path.join(campaign, "raw", "measurements.json"), report)
    _write(
        os.path.join(campaign, "raw", "blocks.json"),
        {
            "A": a["blocks"],
            "B": b["blocks"],
            "block_arm_order": [list(order) for order in run.BLOCK_ARM_ORDER],
        },
    )
    queues = {
        "A": {block: [] for block in range(1, run.BLOCKS + 1)},
        "B": {block: [] for block in range(1, run.BLOCKS + 1)},
    }
    for arm, data in (("A", a), ("B", b)):
        for entry in data["warm"]:
            queues[arm][entry["block"]].append(entry)
    slot_index = 0
    for block, order in enumerate(run.SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            slot_index += 1
            entry = queues[arm][block].pop(0)
            record = {
                "slot_index": slot_index,
                "block": block,
                "position": position,
                "arm": arm,
                "source_sha": (a if arm == "A" else b)["source_sha"],
                "binary_sha256": (a if arm == "A" else b)["adapter_sha256"],
                "trial": entry["trial"],
            }
            _write(os.path.join(campaign, "raw", "slots", f"slot-{slot_index:02d}.json"), record)
    sealed = ["manifest.json", "measurements.json", "blocks.json"] + [
        f"slots/slot-{index:02d}.json" for index in range(1, 17)
    ]
    _write(os.path.join(campaign, "raw", "seal.json"), _seal(campaign, sealed))
    _write(os.path.join(campaign, "sanitized", "results.json"), report)
    _write(
        os.path.join(campaign, "sanitized", "decision.json"),
        {"schema": run.SCHEMA, "decision": report["decision"], "gates": report["gates"]},
    )
    if tamper is not None:
        tamper(campaign)
    return campaign, report["decision"]


class VerifyTests(unittest.TestCase):
    def tearDown(self):
        pass

    def test_valid_campaign_verifies(self):
        campaign, decision = make_campaign("valid")
        try:
            result = verify.verify_campaign(ROOT, campaign)
            self.assertEqual(result["decision"], decision)
            self.assertEqual(result["files"], 19)
        finally:
            shutil.rmtree(campaign, ignore_errors=True)

    def test_tampered_sealed_file_is_rejected(self):
        campaign, _ = make_campaign("tamper-file")
        try:
            path = os.path.join(campaign, "raw", "slots", "slot-01.json")
            with open(path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            value["trial"]["lanes"][0]["samples_ns"] = [1]
            _write(path, value)
            with self.assertRaises(verify.VerifyError):
                verify.verify_campaign(ROOT, campaign)
        finally:
            shutil.rmtree(campaign, ignore_errors=True)

    def test_missing_sealed_file_is_rejected(self):
        campaign, _ = make_campaign("missing-file")
        try:
            os.unlink(os.path.join(campaign, "raw", "slots", "slot-05.json"))
            with self.assertRaises(verify.VerifyError):
                verify.verify_campaign(ROOT, campaign)
        finally:
            shutil.rmtree(campaign, ignore_errors=True)

    def test_swapped_arm_in_schedule_is_rejected(self):
        def tamper(campaign):
            path = os.path.join(campaign, "raw", "slots", "slot-01.json")
            with open(path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            value["arm"] = "B"
            _write(path, value)
            seal = _seal(
                campaign,
                ["manifest.json", "measurements.json", "blocks.json"]
                + [f"slots/slot-{index:02d}.json" for index in range(1, 17)],
            )
            _write(os.path.join(campaign, "raw", "seal.json"), seal)

        campaign, _ = make_campaign("swapped-arm", tamper=tamper)
        try:
            with self.assertRaises(verify.VerifyError):
                verify.verify_campaign(ROOT, campaign)
        finally:
            shutil.rmtree(campaign, ignore_errors=True)

    def test_decision_mismatch_is_rejected(self):
        def tamper(campaign):
            measurements = os.path.join(campaign, "raw", "measurements.json")
            with open(measurements, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            value["decision"] = "A_PERF_REJECTED_SAFE_ROLLBACK"
            _write(measurements, value)
            seal = _seal(
                campaign,
                ["manifest.json", "measurements.json", "blocks.json"]
                + [f"slots/slot-{index:02d}.json" for index in range(1, 17)],
            )
            _write(os.path.join(campaign, "raw", "seal.json"), seal)

        campaign, _ = make_campaign("decision-mismatch", tamper=tamper)
        try:
            with self.assertRaises(verify.VerifyError):
                verify.verify_campaign(ROOT, campaign)
        finally:
            shutil.rmtree(campaign, ignore_errors=True)

    def test_baseline_sentinel_mismatch_is_rejected(self):
        a = test_run.synthetic_arm(total=30_000_000)
        b = test_run.synthetic_arm(sidecar=4_800_090, total=29_416_770, sha="b" * 40)
        campaign, _ = make_campaign("sentinel", a=a, b=b)
        try:
            with self.assertRaises(verify.VerifyError) as context:
                verify.verify_campaign(ROOT, campaign)
            self.assertIn("sentinel", context.exception.detail)
        finally:
            shutil.rmtree(campaign, ignore_errors=True)

    def test_outside_campaign_path_is_blocked(self):
        with self.assertRaises(verify.VerifyError):
            verify.verify_campaign(ROOT, "/tmp/not-a-campaign")


class IntegerGateTests(unittest.TestCase):
    def _report(self, sidecar: int, total: int) -> dict:
        a = test_run.synthetic_arm()
        b = test_run.synthetic_arm(sidecar=sidecar, total=total, sha="b" * 40)
        report, _ = run.derive(a, b)
        return report

    def test_exact_boundary_passes(self):
        report = self._report(9_600_180 * 3 // 4, 30_965_025 * 19 // 20)
        verify._check_integer_size_gates(report)

    def test_one_byte_over_boundary_fails(self):
        report = self._report(9_600_180 * 3 // 4 + 1, 30_965_025 * 19 // 20)
        with self.assertRaises(verify.VerifyError):
            verify._check_integer_size_gates(report)


if __name__ == "__main__":
    unittest.main()
