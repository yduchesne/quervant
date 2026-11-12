#!/usr/bin/env python3
"""Targeted source-proof tests for PR 15I-D3-A (VT-01..VT-06)."""

from __future__ import annotations

import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE_ROOT = os.path.join(ROOT, "target", "pr15i-d3a", "sources", "base")


def _load(name):
    path = os.path.join(ROOT, "benchmarks", "pr15i_d3a", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"d3a_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proof = _load("source_proof")


class SourceProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(BASE_ROOT):
            raise unittest.SkipTest("D3-A pristine BASE worktree is unavailable")
        cls.base_texts = {}
        for relative in proof.EXISTING_FILES:
            with open(os.path.join(BASE_ROOT, relative), encoding="utf-8") as handle:
                cls.base_texts[relative] = handle.read()
        cls.expected = proof.build_expected(cls.base_texts)

    def test_01_base_identity_is_the_recorded_full_sha(self):
        self.assertEqual(proof.BASE_SHA, "409fb0fdf370bb4d4dade5ea507c6fa4518b5220")
        head = proof._git(BASE_ROOT, "rev-parse", "HEAD")
        self.assertEqual(head, proof.BASE_SHA)

    def test_02_insertion_only_derivative_reverses_to_base(self):
        result = proof.verify_derivative(self.base_texts, dict(self.expected))
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["checks"]["reverse_edit_restores_base"])

    def test_02_replacement_and_deletion_are_rejected(self):
        target = proof.UNIFIED
        original = self.expected[target].decode("utf-8")
        for tampered in (
            original.replace("let _d3a_plan =", "let _d3a_plan_x =", 1),
            original.replace("let _d3a_plan = d3a_probe::span(d3a_probe::PLAN);\n", "", 1),
        ):
            actual = dict(self.expected)
            actual[target] = tampered.encode("utf-8")
            with self.assertRaises(proof.ProofError):
                proof.verify_derivative(self.base_texts, actual)

    def test_03_unlisted_inline_attribute_or_public_item_is_rejected(self):
        target = proof.UNIFIED
        base_text = self.expected[target].decode("utf-8")
        for tampered in (
            base_text.replace("fn collect_mixed(", "#[inline]\n    fn collect_mixed(", 1),
            base_text.replace(
                "fn collect_mixed(", "pub fn collect_mixed(", 1
            ),
        ):
            actual = dict(self.expected)
            actual[target] = tampered.encode("utf-8")
            with self.assertRaises(proof.ProofError):
                proof.verify_derivative(self.base_texts, actual)

    def test_03_extra_unlisted_path_is_rejected(self):
        with self.assertRaises(proof.ProofError):
            proof.verify_changed_paths(
                set(proof.DERIVATIVE_FILES) | {"crates/quervant-core/src/search/extra.rs"}
            )

    def test_04_duplicate_or_missing_anchor_fails_closed(self):
        anchor = "let view = columns.keyword_sort_view(field_id, doc_id)?;"
        text = self.base_texts[proof.UNIFIED]
        duplicated = text.replace(anchor, anchor + "\n    " + anchor, 1)
        missing = text.replace(anchor, "", 1)
        with self.assertRaises(proof.ProofError):
            proof._apply(duplicated, proof.UNIFIED)
        with self.assertRaises(proof.ProofError):
            proof._apply(missing, proof.UNIFIED)

    def test_04_match_insert_anchors_are_exactly_two(self):
        execute = self.expected[proof.EXECUTE].decode("utf-8")
        self.assertEqual(execute.count("d3a_probe::match_insert_sample(matched.len())"), 2)
        self.assertEqual(execute.count("matched.insert(*doc_id);"), 1)
        self.assertEqual(execute.count("matched.insert(doc_id);"), 1)

    def test_05_query_probe_stays_adapter_only(self):
        for relative in (proof.UNIFIED, proof.EXECUTE, proof.SEARCH_MOD, proof.CORE_CARGO):
            self.assertNotIn("query_probe", self.expected[relative].decode("utf-8"))
        self.assertEqual(
            self.expected[proof.ADAPTER].decode("utf-8").count('"query_probe" =>'), 1
        )

    def test_05_probe_module_feature_is_scratch_only_and_gated(self):
        cargo = self.expected[proof.CORE_CARGO].decode("utf-8")
        self.assertEqual(cargo.count("pr15id3a-probe = []"), 1)
        self.assertNotIn("pr15id3a-probe", self.base_texts[proof.CORE_CARGO])
        search_mod = self.expected[proof.SEARCH_MOD].decode("utf-8")
        self.assertIn(
            '#[cfg(feature = "pr15id3a-probe")]\npub mod d3a_probe;', search_mod
        )

    def test_06_recorder_module_is_exact_scratch_bytes(self):
        bytes_ = self.expected[proof.D3A_PROBE]
        self.assertTrue(bytes_.startswith(b"//! Diagnostic-only, thread-local recorder"))
        self.assertIn(b"pub const NAMES: [&str; 25]", bytes_)
        self.assertIn(b"pub fn take()", bytes_)
        self.assertIn(b"candidate_samples_key", bytes_)


if __name__ == "__main__":
    unittest.main()
