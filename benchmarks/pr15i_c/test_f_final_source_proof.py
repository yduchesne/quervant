#!/usr/bin/env python3
"""Source-proof tests for the PR 15I-C-F diagnostic/release arms."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import f_final_source_proof as proof  # noqa: E402

ANCHORS = (
    "\n"
    + "    /// N-U34: the generic collector body contains no eligibility branch and no\n"
    + "    /// inline attribute, and there is exactly one definition of it. The\n"
    + "    fn n_u34_generic_collector_is_structurally_untouched() {\n"
    + "        assert!(\n"
    + "            !attribute_block.contains(\"#[inline(\"),\n"
    + "            \"no inline attribute on the generic collector\"\n"
    + "        );\n"
    + "    }\n"
)


class BoundaryTransformTests(unittest.TestCase):
    def parent_source(self):
        return (
            "impl S {\n"
            "    #[allow(clippy::needless_option_as_deref)]\n"
            "    #[allow(clippy::too_many_arguments, clippy::type_complexity)]\n"
            "    fn collect_mixed(a: u8) -> u8 { a }\n"
            "}\n"
            + ANCHORS
        )

    def transformed(self):
        return proof.expected_transformed(self.parent_source())

    def test_attribute_is_the_only_production_edit(self):
        transformed = self.transformed()
        self.assertEqual(
            transformed.count("#[inline(never)]\n    fn collect_mixed("), 1)
        attribute_only = transformed.replace(proof.ASSERT_NEW, proof.ASSERT_OLD, 1)
        attribute_only = attribute_only.replace(proof.COMMENT_NEW, proof.COMMENT_OLD, 1)
        self.assertEqual(attribute_only, self.parent_source().replace(
            "    fn collect_mixed(", "    #[inline(never)]\n    fn collect_mixed(", 1))

    def test_reverse_transform_restores_parent(self):
        self.assertEqual(proof.reverse_transformed(self.transformed()),
                         self.parent_source())

    def test_missing_attribute_anchor_is_rejected(self):
        with self.assertRaises(proof.FSourceError) as caught:
            proof.expected_transformed("fn collect_mixed() {}\n")
        self.assertEqual(caught.exception.rule, "FS_ATTRIBUTE")

    def test_double_attribute_is_rejected(self):
        source = self.transformed().replace(
            "    #[inline(never)]\n", "    #[inline(never)]\n    #[inline(never)]\n")
        with self.assertRaises(proof.FSourceError) as caught:
            proof.reverse_transformed(source)
        self.assertEqual(caught.exception.rule, "FS_ATTRIBUTE")

    def test_extra_body_edit_is_rejected(self):
        source = self.transformed().replace("{ a }", "{ a + 1 }")
        self.assertNotEqual(proof.reverse_transformed(source), self.parent_source())


class FakeRepository:
    """In-memory git facade so negative cases need no real commits."""

    def __init__(self, unified, parent=None, revision="f" * 40, changed=None):
        self.unified = unified
        self.parent_unified = (
            parent if parent is not None else proof.reverse_transformed(unified))
        self.revision = revision
        self.changed = changed if changed is not None else [proof.UNIFIED]

    def install(self, module=proof):
        originals = {}
        module.EXPECTED_GENERIC_BODY = proof.body_sha(self.unified)
        module.read_at = lambda root, revision, path: (
            self.unified if revision == self.revision else self.parent_unified)
        module.is_commit = lambda root, revision: True
        module.is_ancestor = lambda root, a, b: True
        module.changed_paths = lambda root, a, b: list(self.changed)
        return originals


class VerifyBoundaryArmTests(unittest.TestCase):
    def setUp(self):
        self.parent = (
            "mod x {\n"
            "    #[allow(clippy::needless_option_as_deref)]\n"
            "    #[allow(clippy::too_many_arguments, clippy::type_complexity)]\n"
            "    fn collect_mixed(a: u8) -> u8 { a }\n"
            "    fn collect_exact_term_physical(a: u8) -> u8 { a }\n"
            "}\n"
            + ANCHORS
        )

    def install(self, unified=None, changed=None, parent=None):
        fake = FakeRepository(unified or proof.expected_transformed(self.parent),
                              parent=parent, revision="a" * 40, changed=changed)
        self._saved = {name: getattr(proof, name) for name in
                       ("read_at", "is_commit", "is_ancestor", "changed_paths",
                        "EXPECTED_GENERIC_BODY")}
        fake.install()

    def tearDown(self):
        for name, value in getattr(self, "_saved", {}).items():
            setattr(proof, name, value)

    def test_valid_boundary_arm_passes(self):
        self.install()
        report = proof.verify_boundary_arm(".", "b" * 40, "a" * 40, "F_DIAG")
        self.assertEqual(report["changed_paths"], [proof.UNIFIED])
        self.assertTrue(report["reverse_equals_parent"])

    def test_scope_violation_is_rejected(self):
        self.install(changed=[proof.UNIFIED, "crates/quervant-core/src/lib.rs"])
        with self.assertRaises(proof.FSourceError) as caught:
            proof.verify_boundary_arm(".", "b" * 40, "a" * 40, "F_DIAG")
        self.assertEqual(caught.exception.rule, "FS_SCOPE")

    def test_body_drift_is_rejected(self):
        self.install(unified=proof.expected_transformed(
            self.parent).replace("{ a }", "{ a + 1 }", 1), parent=self.parent)
        with self.assertRaises(proof.FSourceError) as caught:
            proof.verify_boundary_arm(".", "b" * 40, "a" * 40, "F_DIAG")
        self.assertIn(caught.exception.rule, {"FS_DIFF", "FS_BODY"})

    def test_non_descendant_revision_is_rejected(self):
        self.install()
        proof.is_ancestor = lambda root, a, b: False
        with self.assertRaises(proof.FSourceError) as caught:
            proof.verify_boundary_arm(".", "b" * 40, "a" * 40, "F_DIAG")
        self.assertEqual(caught.exception.rule, "FS_SOURCE")


@unittest.skipUnless(os.path.isdir(os.path.join(
    os.path.dirname(os.path.dirname(HERE)), ".git")), "needs the repository")
class CommittedRevisionTests(unittest.TestCase):
    """Read-only proof against the committed diagnostic and baseline trees."""

    def test_f_diag_changes_only_unified_rs(self):
        report = proof.verify_f_diag(os.path.dirname(os.path.dirname(HERE)))
        self.assertEqual(report["changed_paths"], [proof.UNIFIED])
        self.assertEqual(report["generic_body_sha256"],
                         proof.EXPECTED_GENERIC_BODY)
        self.assertEqual(report["generic_attributes"][-1], "#[inline(never)]")

    def test_f_diag_feature_and_mode_gate_present(self):
        root = os.path.dirname(os.path.dirname(HERE))
        manifest = proof.read_at(root, proof.F_DIAG, proof.MANIFEST)
        self.assertIn("pr15ic-causal = []", manifest)
        source = proof.read_at(root, proof.F_DIAG, proof.UNIFIED)
        self.assertIn("QUERVANT_PR15IC_CAUSAL_MODE", source)

    def test_baseline_has_no_physical_collector(self):
        root = os.path.dirname(os.path.dirname(HERE))
        source = proof.read_at(root, proof.BASE_A, proof.UNIFIED)
        self.assertNotIn("fn collect_exact_term_physical", source)
        self.assertEqual(proof.body_sha(source), proof.EXPECTED_GENERIC_BODY)

    def test_release_parent_carries_no_diagnostic_gate(self):
        root = os.path.dirname(os.path.dirname(HERE))
        source = proof.read_at(root, proof.RELEASE_PARENT, proof.UNIFIED)
        self.assertNotIn("QUERVANT_PR15IC_CAUSAL_MODE", source)
        self.assertEqual(proof.body_sha(source), proof.EXPECTED_GENERIC_BODY)


if __name__ == "__main__":
    unittest.main()
