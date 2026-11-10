#!/usr/bin/env python3
"""Tests for the independent D0 source proof (no Rust build required)."""

from __future__ import annotations

import copy
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"d0_{name}", os.path.join(HERE, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proof = _load("source_proof")

EXISTING = (proof.UNIFIED, proof.EXECUTE, proof.SEARCH_MOD, proof.CORE_CARGO, proof.ADAPTER)


class SourceProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = {
            relative: open(os.path.join(REPO_ROOT, relative), "rb").read().decode("utf-8")
            for relative in EXISTING
        }
        cls.expected = proof.build_expected(cls.base)

    def clone(self):
        return {relative: payload for relative, payload in self.expected.items()}

    def test_expected_derivative_reverses_to_base(self):
        for relative in EXISTING:
            insertions = proof.reverse_insertions(
                self.base[relative], self.expected[relative].decode("utf-8"), relative
            )
            self.assertGreater(len(insertions), 0)
            self.assertTrue(
                all("text" in insertion for insertion in insertions)
            )

    def test_verify_derivative_accepts_the_approved_derivative(self):
        result = proof.verify_derivative(self.base, self.expected)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["checks"]["reverse_edit_restores_base"])
        self.assertTrue(result["checks"]["feature_non_default"])
        self.assertTrue(result["checks"]["no_added_inline_attributes"])
        self.assertTrue(result["checks"]["query_probe_adapter_only"])

    def test_extra_inline_attribute_is_rejected(self):
        actual = self.clone()
        text = actual[proof.UNIFIED].decode("utf-8").replace(
            "let _d0_plan = d0_probe::span(d0_probe::PLAN);",
            "#[inline(never)]\n        let _d0_plan = d0_probe::span(d0_probe::PLAN);",
            1,
        )
        actual[proof.UNIFIED] = text.encode("utf-8")
        with self.assertRaises(proof.ProofError) as context:
            proof.verify_derivative(self.base, actual)
        self.assertEqual(context.exception.code, "D0_PROOF_EXTRA")

    def test_extra_cache_or_feature_default_is_rejected(self):
        actual = self.clone()
        cargo = actual[proof.CORE_CARGO].decode("utf-8").replace(
            'default = ["stored-lz4"]', 'default = ["stored-lz4", "pr15id0-probe"]'
        )
        actual[proof.CORE_CARGO] = cargo.encode("utf-8")
        with self.assertRaises(proof.ProofError):
            proof.verify_derivative(self.base, actual)

    def test_preexisting_feature_is_rejected(self):
        base = dict(self.base)
        base[proof.CORE_CARGO] = base[proof.CORE_CARGO].replace(
            "[features]\n", "[features]\npr15id0-probe = []\n"
        )
        with self.assertRaises(proof.ProofError) as context:
            proof.verify_derivative(base, self.expected)
        self.assertIn(context.exception.code, {"D0_PROOF_EXTRA", "D0_PROOF_FEATURE"})

    def test_recorder_bytes_are_checked(self):
        actual = self.clone()
        actual[proof.D0_PROBE] = actual[proof.D0_PROBE] + b"\n// tampered\n"
        with self.assertRaises(proof.ProofError) as context:
            proof.verify_derivative(self.base, actual)
        self.assertEqual(context.exception.code, "D0_PROOF_EXTRA")

    def test_changed_path_allowlist_accepts_exactly_six(self):
        proof.verify_changed_paths(proof.DERIVATIVE_FILES)

    def test_changed_path_allowlist_rejects_cargo_lock(self):
        with self.assertRaises(proof.ProofError) as context:
            proof.verify_changed_paths(
                list(proof.DERIVATIVE_FILES) + ["Cargo.lock"]
            )
        self.assertEqual(context.exception.code, "D0_PROOF_EXTRA")

    def test_changed_path_allowlist_rejects_hidden_score_change(self):
        with self.assertRaises(proof.ProofError) as context:
            proof.verify_changed_paths(
                list(proof.DERIVATIVE_FILES) + ["crates/quervant-core/src/search/score.rs"]
            )
        self.assertEqual(context.exception.code, "D0_PROOF_EXTRA")

    def test_adapter_query_arm_must_remain_single(self):
        actual = self.clone()
        text = actual[proof.ADAPTER].decode("utf-8").replace(
            '"query_probe" => {', '"query_probe" => {\n            "query_probe" => {', 1
        )
        actual[proof.ADAPTER] = text.encode("utf-8")
        with self.assertRaises(proof.ProofError):
            proof.verify_derivative(self.base, actual)

    def test_base_text_is_required_for_every_existing_file(self):
        missing = dict(self.base)
        missing.pop(proof.EXECUTE)
        with self.assertRaises(proof.ProofError) as context:
            proof.build_expected(missing)
        self.assertEqual(context.exception.code, "D0_PROOF_INPUT")


if __name__ == "__main__":
    unittest.main()
