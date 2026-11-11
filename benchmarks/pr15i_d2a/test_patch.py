#!/usr/bin/env python3
"""Tests for the D2A source materializer (no Rust build required)."""

from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"d0_{name}", os.path.join(HERE, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


patcher = _load("patch_source")

BASE_FILES = {
    patcher.UNIFIED: "crates/quervant-core/src/search/unified.rs",
    patcher.EXECUTE: "crates/quervant-core/src/search/execute.rs",
    patcher.SEARCH_MOD: "crates/quervant-core/src/search/mod.rs",
    patcher.CORE_CARGO: "crates/quervant-core/Cargo.toml",
    patcher.ADAPTER: "benchmarks/pr15d/adapters/quervant/src/main.rs",
}


def base_texts() -> dict[str, str]:
    return {
        relative: open(os.path.join(REPO_ROOT, relative), "rb").read().decode("utf-8")
        for relative in BASE_FILES
    }


class PatcherTests(unittest.TestCase):
    def setUp(self):
        self.texts = base_texts()

    def test_exact_insertions_are_additive_only(self):
        for relative, text in self.texts.items():
            derivative, insertions = patcher.apply_edits(text, relative)
            self.assertGreater(insertions, [])
            # Removing exactly the recorded inserted fragments restores BASE.
            pieces = []
            cursor = 0
            for insertion in sorted(insertions, key=lambda item: item["byte_offset"]):
                self.assertEqual(
                    derivative[insertion["byte_offset"] : insertion["byte_offset"] + insertion["inserted_len"]],
                    insertion["text"],
                )
                pieces.append(derivative[cursor : insertion["byte_offset"]])
                cursor = insertion["byte_offset"] + insertion["inserted_len"]
            pieces.append(derivative[cursor:])
            self.assertEqual("".join(pieces), text)

    def test_duplicate_anchor_is_refused(self):
        text = self.texts[patcher.UNIFIED]
        start = text.index("    fn collect_mixed(")
        stop = text.index("\n}\n\nimpl std::fmt::Debug for UnifiedSearcher<'_>")
        region = text[start:stop]
        duplicated = region.replace(
            "let mut guards = Vec::new();",
            "let mut guards = Vec::new();\n        let mut guards = Vec::new();",
            1,
        )
        text = text[:start] + duplicated + text[stop:]
        with self.assertRaises(patcher.PatchError) as context:
            patcher.apply_edits(text, patcher.UNIFIED)
        self.assertEqual(context.exception.code, "D2A_PATCH_ANCHOR")

    def test_missing_anchor_is_refused(self):
        text = self.texts[patcher.UNIFIED].replace(
            "let scored = execute::evaluate_lexical_with(",
            "let scored = execute::evaluate_with(",
            1,
        )
        with self.assertRaises(patcher.PatchError) as context:
            patcher.apply_edits(text, patcher.UNIFIED)
        self.assertEqual(context.exception.code, "D2A_PATCH_ANCHOR")

    def test_region_requires_unique_delimiters(self):
        delimiter = "pub(crate) fn evaluate_lexical_with<"
        text = self.texts[patcher.EXECUTE].replace(delimiter, delimiter + delimiter, 1)
        with self.assertRaises(patcher.PatchError) as context:
            patcher.apply_edits(text, patcher.EXECUTE)
        self.assertEqual(context.exception.code, "D2A_PATCH_REGION")

    def test_feature_is_non_default_and_module_is_gated(self):
        cargo, _ = patcher.apply_edits(self.texts[patcher.CORE_CARGO], patcher.CORE_CARGO)
        self.assertIn("pr15id2a-probe = []", cargo)
        self.assertIn('default = ["stored-lz4"]', cargo)
        module, _ = patcher.apply_edits(self.texts[patcher.SEARCH_MOD], patcher.SEARCH_MOD)
        self.assertIn('#[cfg(feature = "pr15id2a-probe")]\npub mod d2a_probe;', module)
        self.assertIn("#[cfg(test)]\nmod diagnostics;", module)

    def test_adapter_query_probe_arm_is_unique(self):
        adapter, _ = patcher.apply_edits(self.texts[patcher.ADAPTER], patcher.ADAPTER)
        self.assertEqual(adapter.count('"query_probe" =>'), 1)
        self.assertEqual(adapter.count('"query" =>'), 1)

    def test_existing_derivative_is_refused(self):
        root = tempfile.mkdtemp(prefix="patch-")
        try:
            for relative in BASE_FILES:
                path = os.path.join(root, relative)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(self.texts[relative])
            # A feature declaration already present is ambiguous.
            cargo_path = os.path.join(root, patcher.CORE_CARGO)
            text = open(cargo_path, encoding="utf-8").read()
            with open(cargo_path, "w", encoding="utf-8") as handle:
                handle.write(text.replace("[features]\n", "[features]\npr15id2a-probe = []\n"))
            with self.assertRaises(patcher.PatchError) as context:
                patcher.check_derivative_absent(root)
            self.assertEqual(context.exception.code, "D2A_PATCH_EXISTS")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_present_probe_module_is_refused(self):
        root = tempfile.mkdtemp(prefix="patch-")
        try:
            for relative in BASE_FILES:
                path = os.path.join(root, relative)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(self.texts[relative])
            path = os.path.join(root, patcher.D2A_PROBE)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").write("// already present")
            with self.assertRaises(patcher.PatchError) as context:
                patcher.check_derivative_absent(root)
            self.assertEqual(context.exception.code, "D2A_PATCH_EXISTS")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_non_insertion_change_is_refused(self):
        base = self.texts[patcher.EXECUTE]
        mutated = base.replace(
            "let mut matched: BTreeSet<u64> = BTreeSet::new();",
            "let mut matched_now: BTreeSet<u64> = BTreeSet::new();",
            1,
        )
        with self.assertRaises(patcher.PatchError) as context:
            patcher.diff_insertions(base, mutated, patcher.EXECUTE)
        self.assertEqual(context.exception.code, "D2A_REVERSE_EDIT")


if __name__ == "__main__":
    unittest.main()
