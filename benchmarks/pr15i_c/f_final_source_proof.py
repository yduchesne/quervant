#!/usr/bin/env python3
"""PR 15I-C-F — mechanical source proof for the F diagnostic/release arms.

Git-blob extraction only; no measurement or classification logic.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

_spec = importlib.util.spec_from_file_location(
    "pr15i_c_source_proof", os.path.join(HERE, "source_proof.py"))
_source_proof = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_source_proof)

BASE_A = "6f6463cb26bcf28340cc9d4afd4dfeb040281898"
CAUSAL_PARENT = "658a2dde0e15c17e2b0c92278b5c922f5260fe60"
RELEASE_PARENT = "b32523b9bb182190cb8260b00c3a81645314837f"
F_DIAG = "5f74bb691420673bde1181603d0a19a8a4114ec8"
EXPECTED_GENERIC_BODY = (
    "00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994")
GENERIC = "collect_mixed"
PHYSICAL = "collect_exact_term_physical"
UNIFIED = "crates/quervant-core/src/search/unified.rs"
MANIFEST = "crates/quervant-core/Cargo.toml"
SEVEN_FILES = (
    "crates/quervant-core/Cargo.toml",
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/score.rs",
    "crates/quervant-core/src/search/diagnostics.rs",
    "crates/quervant-core/src/search/mod.rs",
    "crates/quervant-core/tests/pr15i_c_physical.rs",
)

ATTR_OLD = '''    #[allow(clippy::needless_option_as_deref)]
    #[allow(clippy::too_many_arguments, clippy::type_complexity)]
    fn collect_mixed('''
ATTR_NEW = '''    #[allow(clippy::needless_option_as_deref)]
    #[allow(clippy::too_many_arguments, clippy::type_complexity)]
    #[inline(never)]
    fn collect_mixed('''
COMMENT_OLD = '''    /// N-U34: the generic collector body contains no eligibility branch and no
    /// inline attribute, and there is exactly one definition of it. The'''
COMMENT_NEW = '''    /// N-U34: the generic collector body contains no eligibility branch, has
    /// exactly one `#[inline(never)]` attribute (the F-final out-of-line generic
    /// boundary), and there is exactly one definition of it. The'''
ASSERT_OLD = '''        assert!(
            !attribute_block.contains("#[inline("),
            "no inline attribute on the generic collector"
        );'''
ASSERT_NEW = '''        assert_eq!(
            attribute_block.matches("#[inline(never)]").count(),
            1,
            "generic collector must have exactly one out-of-line attribute"
        );
        assert_eq!(
            attribute_block.matches("#[inline(").count(),
            1,
            "generic collector must not have any additional inline attribute"
        );'''


class FSourceError(Exception):
    def __init__(self, rule, detail):
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail


def require(condition, rule, detail):
    if not condition:
        raise FSourceError(rule, detail)


def read_at(root, revision, path):
    return _source_proof.read_at_revision(root, revision, path)


def body_sha(source, name=GENERIC):
    return _source_proof.body_sha(source, name)


def attributes(source, name=GENERIC):
    return _source_proof.attribute_block(source, name)


def git(root, *args):
    result = subprocess.run(["git", "-C", root, *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, check=False)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def is_commit(root, revision):
    code, out, _err = git(root, "cat-file", "-t", revision)
    return code == 0 and out == "commit"


def is_ancestor(root, ancestor, descendant):
    code, _out, _err = git(root, "merge-base", "--is-ancestor", ancestor, descendant)
    return code == 0


def changed_paths(root, a_rev, b_rev):
    """Production (`crates/`) paths differing between two revisions."""
    code, out, err = git(root, "diff", "--name-only", f"{a_rev}..{b_rev}", "--",
                         "crates/")
    require(code == 0, "FS_GIT", f"git diff failed: {err}")
    return [path for path in out.splitlines() if path]


def expected_transformed(source):
    """Apply exactly the three authorized replacements."""
    require(source.count(ATTR_OLD) == 1, "FS_ATTRIBUTE",
            "generic collector attribute anchor is not unique")
    require(source.count(COMMENT_OLD) == 1, "FS_TEST",
            "n_u34 doc-comment anchor is not unique")
    require(source.count(ASSERT_OLD) == 1, "FS_TEST",
            "n_u34 assertion anchor is not unique")
    transformed = source.replace(ATTR_OLD, ATTR_NEW, 1)
    transformed = transformed.replace(COMMENT_OLD, COMMENT_NEW, 1)
    transformed = transformed.replace(ASSERT_OLD, ASSERT_NEW, 1)
    return transformed


def reverse_transformed(source):
    """Undo the three authorized replacements."""
    require(source.count(ATTR_NEW) == 1, "FS_ATTRIBUTE",
            "F collector does not carry exactly one inline attribute")
    reversed_source = source.replace(ATTR_NEW, ATTR_OLD, 1)
    reversed_source = reversed_source.replace(COMMENT_NEW, COMMENT_OLD, 1)
    reversed_source = reversed_source.replace(ASSERT_NEW, ASSERT_OLD, 1)
    return reversed_source


def verify_boundary_arm(root, parent_sha, candidate_sha, label):
    """Verify `candidate = parent + exactly the three authorized edits`."""
    require(is_commit(root, parent_sha), "FS_SOURCE", f"{label} parent not a commit")
    require(is_commit(root, candidate_sha), "FS_SOURCE", f"{label} not a commit")
    require(is_ancestor(root, parent_sha, candidate_sha), "FS_SOURCE",
            f"{label} does not descend from its parent")
    changed = changed_paths(root, parent_sha, candidate_sha)
    require(changed == [UNIFIED], "FS_SCOPE",
            f"{label} changes paths outside unified.rs: {changed}")
    parent_source = read_at(root, parent_sha, UNIFIED)
    candidate_source = read_at(root, candidate_sha, UNIFIED)
    require(reverse_transformed(candidate_source) == parent_source, "FS_DIFF",
            f"{label} differs from its parent outside the three authorized edits")
    digest = body_sha(candidate_source)
    require(digest == EXPECTED_GENERIC_BODY, "FS_BODY",
            f"{label} generic collector body hash drifted: {digest}")
    attrs = attributes(candidate_source)
    require(attrs[-1] == "#[inline(never)]", "FS_BOUNDARY",
            f"{label} generic collector lacks the trailing #[inline(never)]")
    require(sum(1 for item in attrs if item.startswith("#[inline(")) == 1,
            "FS_BOUNDARY", f"{label} carries more than one inline attribute")
    require(candidate_source.count("#[inline(never)]\n    fn collect_mixed(") == 1,
            "FS_BOUNDARY", f"{label} attribute placement is not unique")
    require(candidate_source.count("\n    fn collect_mixed(") == 1, "FS_BODY",
            f"{label} generic collector definition is not unique")
    return {
        "label": label,
        "parent_sha": parent_sha,
        "candidate_sha": candidate_sha,
        "changed_paths": changed,
        "generic_body_sha256": digest,
        "generic_attributes": attrs,
        "reverse_equals_parent": True,
    }


def verify_physical_unchanged(root, parent_sha, candidate_sha):
    parent_source = read_at(root, parent_sha, UNIFIED)
    candidate_source = read_at(root, candidate_sha, UNIFIED)
    require(body_sha(parent_source, PHYSICAL) == body_sha(candidate_source, PHYSICAL),
            "FS_PHYSICAL", "physical collector body drifted")


def verify_f_diag(root, f_diag=F_DIAG):
    report = verify_boundary_arm(root, CAUSAL_PARENT, f_diag, "F_DIAG")
    verify_physical_unchanged(root, CAUSAL_PARENT, f_diag)
    manifest = read_at(root, f_diag, MANIFEST)
    require("pr15ic-causal = []" in manifest, "FS_FEATURE",
            "F_DIAG lost the non-default pr15ic-causal feature")
    source = read_at(root, f_diag, UNIFIED)
    require("QUERVANT_PR15IC_CAUSAL_MODE" in source, "FS_FEATURE",
            "F_DIAG lost the diagnostic mode gate")
    report["physical_body_sha256"] = body_sha(source, PHYSICAL)
    return report


def verify_f_release(root, f_release):
    report = verify_boundary_arm(root, RELEASE_PARENT, f_release, "F_RELEASE")
    verify_physical_unchanged(root, RELEASE_PARENT, f_release)
    for path in SEVEN_FILES:
        if path == UNIFIED:
            continue
        actual = hashlib.sha256(read_at(root, f_release, path).encode()).hexdigest()
        expected = hashlib.sha256(read_at(root, RELEASE_PARENT, path).encode()).hexdigest()
        require(actual == expected, "FS_SCOPE",
                f"F_RELEASE {path} differs from RELEASE_PARENT")
    source = read_at(root, f_release, UNIFIED)
    manifest = read_at(root, f_release, MANIFEST)
    for needle in ("pr15ic-causal", "QUERVANT_PR15IC_CAUSAL_MODE",
                   "pr15ic_causal_enabled"):
        require(needle not in source and needle not in manifest, "FS_RELEASE",
                f"F_RELEASE still references the diagnostic gate: {needle}")
    report["physical_body_sha256"] = body_sha(source, PHYSICAL)
    report["no_diagnostic_gate"] = True
    return report
