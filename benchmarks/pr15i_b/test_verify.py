"""Adversarial tests for the PR 15I-B verifier (synthetic + sealed real)."""

import hashlib
import importlib.util
import json
import os
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = load("pr15i_b_run_for_verify", os.path.join(HERE, "run.py"))
verify = load("pr15i_b_verify_under_test", os.path.join(HERE, "verify.py"))


def campaign(name):
    return os.path.join(ROOT, "target", "pr15i-b", "campaigns", name)


class RealCampaignTests(unittest.TestCase):
    @unittest.skipUnless(os.path.isdir(campaign("zstd-01")), "sealed campaign absent")
    def test_real_rejection_verifies_read_only(self):
        path = campaign("zstd-01")
        seal = os.path.join(path, "raw", "seal.json")
        before = verify.sha(seal)
        receipt = verify.verify_campaign(ROOT, path)
        self.assertEqual(receipt["decision"], "B_CANDIDATE_INELIGIBLE")
        self.assertEqual(receipt["codec"], "zstd1")
        self.assertEqual(receipt["raw_files_verified"], 26)
        self.assertEqual(before, verify.sha(seal))

    @unittest.skipUnless(os.path.isdir(campaign("lz4-05")), "sealed campaign absent")
    def test_real_lz4_rejection_verifies(self):
        receipt = verify.verify_campaign(ROOT, campaign("lz4-05"))
        self.assertEqual(receipt["decision"], "B_CANDIDATE_INELIGIBLE")
        self.assertEqual(receipt["codec"], "lz4")

    @unittest.skipUnless(os.path.isdir(campaign("zstd-01")), "sealed campaign absent")
    def test_tampered_copy_is_rejected(self):
        source = campaign("zstd-01")
        target = os.path.join(ROOT, "target", "pr15i-b", "campaigns", "unit-tamper")
        if os.path.isdir(target):
            shutil.rmtree(target)
        os.makedirs(os.path.join(target, "setup"))
        shutil.copytree(os.path.join(source, "raw"), os.path.join(target, "raw"))
        for part in ("corpus", "slots", "blocks"):
            shutil.copytree(os.path.join(source, "setup", part), os.path.join(target, "setup", part))
        try:
            path = os.path.join(target, "raw", "sizes.json")
            with open(path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            value["B"]["100000"][0]["layout"]["stored_bytes"] += 1
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(value, handle)
            with self.assertRaises(verify.VerifyError):
                verify.verify_campaign(ROOT, target)
        finally:
            shutil.rmtree(target, ignore_errors=True)


class UnitTests(unittest.TestCase):
    def test_gate_boundaries(self):
        self.assertTrue(verify._gate([1.10] * 4, 1.10, 1.30))
        self.assertFalse(verify._gate([1.10, 1.10, 1.10, 1.31], 1.10, 1.30))

    def test_unsafe_seal_paths_rejected(self):
        with self.assertRaises(verify.VerifyError):
            verify._safe("../escape.json")

    def test_codec_identity_rejects_wrong_codec(self):
        sizes = {"A": {"10000": [{"attempt": 1, "layout": {"stored_bytes": 1, "committed_index_bytes": 10, "stored_version": 1, "codec_id": None, "required_features": []}}],
                       "100000": [{"attempt": 1, "layout": {"stored_bytes": 10, "committed_index_bytes": 100, "stored_version": 1, "codec_id": None, "required_features": []}}]},
                 "B": {"10000": [{"attempt": 1, "layout": {"stored_bytes": 1, "committed_index_bytes": 10, "stored_version": 2, "codec_id": 2, "required_features": [[13, 1]]}}],
                       "100000": [{"attempt": 1, "layout": {"stored_bytes": 10, "committed_index_bytes": 100, "stored_version": 2, "codec_id": 2, "required_features": [[13, 1]]}}]}}
        measurements = {"size_ratios": {}}
        with self.assertRaises(verify.VerifyError):
            verify.validate_sizes(sizes, measurements, "lz4")


if __name__ == "__main__":
    unittest.main()
