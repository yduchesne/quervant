#!/usr/bin/env python3
"""PR 15I-C causal experiment — mechanical source-identity proof.

Pure Git-object extraction and structural checks shared by the controller (early
abort) and the independent verifier. It contains **no** measurement, ratio or
classification logic.
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

BASELINE_SHA = "6f6463cb26bcf28340cc9d4afd4dfeb040281898"
HISTORICAL_CANDIDATE_SHA = "92a741876f6f6823d9d1792fc391dbb1bbecceb0"
EXPECTED_GENERIC_BODY_SHA = (
    "00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994")
GENERIC_METHOD = "collect_mixed"
PHYSICAL_METHOD = "collect_exact_term_physical"
CAUSAL_FEATURE = "pr15ic-causal"
CAUSAL_HELPER = "pr15ic_causal_enabled"
MODE_VARIABLE = "QUERVANT_PR15IC_CAUSAL_MODE"

RESTORED_FILES = (
    "crates/quervant-core/Cargo.toml",
    "crates/quervant-core/src/search/diagnostics.rs",
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/mod.rs",
    "crates/quervant-core/src/search/score.rs",
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/tests/pr15i_c_physical.rs",
)
# Files whose content must equal the historical candidate byte-for-byte.
IDENTICAL_TO_HISTORICAL = tuple(
    path for path in RESTORED_FILES
    if path not in ("crates/quervant-core/Cargo.toml",
                    "crates/quervant-core/src/search/unified.rs")
)
# The only production files the experiment may touch, relative to merged A.
ALLOWED_PRODUCTION_DELTA = RESTORED_FILES


class SourceProofError(Exception):
    """Raised when a source identity or structural expectation fails."""


def _require(condition, detail):
    if not condition:
        raise SourceProofError(detail)


def read_at(root, revision, path):
    return _source_proof.read_at_revision(root, revision, path)


def blob_sha_at(root, revision, path):
    return hashlib.sha256(read_at(root, revision, path).encode("utf-8")).hexdigest()


def body_sha(source, name):
    return _source_proof.body_sha(source, name)


def attribute_block(source, name):
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


def changed_production_paths(root, a_rev, b_rev):
    """Production paths (crates/**) that differ between two revisions."""
    code, out, err = git(root, "diff", "--name-only", f"{a_rev}..{b_rev}")
    _require(code == 0, f"git diff failed: {err}")
    return [path for path in out.splitlines()
            if path.startswith("crates/") and path]


def restored_matches_historical(root, candidate_sha):
    """Every restored file must equal the historical candidate blob."""
    mismatches = []
    for path in RESTORED_FILES:
        actual = blob_sha_at(root, candidate_sha, path)
        expected = blob_sha_at(root, HISTORICAL_CANDIDATE_SHA, path)
        if actual != expected:
            mismatches.append(path)
    return mismatches


def causal_delta(root, candidate_sha):
    """Files differing from the historical candidate: Cargo.toml + unified.rs."""
    return changed_production_paths(root, HISTORICAL_CANDIDATE_SHA, candidate_sha)


def verify_causal_source(root, candidate_sha, baseline_sha=None):
    """Full structural proof of the experimental source identity."""
    baseline_sha = baseline_sha or BASELINE_SHA
    _require(is_commit(root, baseline_sha), "baseline is not a Git commit")
    _require(is_commit(root, candidate_sha), "candidate is not a Git commit")
    _require(is_ancestor(root, baseline_sha, candidate_sha),
             "candidate does not descend from the baseline")

    production = changed_production_paths(root, baseline_sha, candidate_sha)
    unexpected = sorted(set(production) - set(ALLOWED_PRODUCTION_DELTA))
    _require(not unexpected,
             f"candidate changes production paths outside the allowlist: {unexpected}")

    mismatches = restored_matches_historical(root, HISTORICAL_CANDIDATE_SHA)
    _require(not mismatches,
             f"candidate differs from the historical candidate outside the gate: {mismatches}")

    delta = causal_delta(root, candidate_sha)
    _require(set(delta) == {"crates/quervant-core/Cargo.toml",
                            "crates/quervant-core/src/search/unified.rs"},
             f"causal delta is not exactly Cargo.toml + unified.rs: {delta}")

    baseline_source = read_at(root, baseline_sha, "crates/quervant-core/src/search/unified.rs")
    causal_source = read_at(root, candidate_sha, "crates/quervant-core/src/search/unified.rs")
    baseline_body = body_sha(baseline_source, GENERIC_METHOD)
    causal_body = body_sha(causal_source, GENERIC_METHOD)
    _require(baseline_body == EXPECTED_GENERIC_BODY_SHA,
             "merged baseline generic body hash is not the pinned value")
    _require(causal_body == EXPECTED_GENERIC_BODY_SHA,
             "candidate generic collect_mixed body differs from merged A")
    attributes = attribute_block(causal_source, GENERIC_METHOD)
    _require(not any(item.startswith("#[inline(") for item in attributes),
             "the generic collector must not carry an inline attribute")
    # Only the real definition is preceded by a newline and four-space indent;
    # string literals inside test modules are not.
    _require(causal_source.count("\n    fn collect_mixed(") == 1,
             "generic collector definition is not unique")
    _require(causal_source.count(f"fn {CAUSAL_HELPER}(") == 1,
             "causal gate helper is not defined exactly once")
    _require(f'feature = "{CAUSAL_FEATURE}"' in causal_source,
             "causal gate is not behind the experimental feature")
    _require(MODE_VARIABLE in causal_source,
             "causal gate does not read the allowlisted mode variable")

    manifest = read_at(root, candidate_sha, "crates/quervant-core/Cargo.toml")
    _require(f"{CAUSAL_FEATURE} = []" in manifest,
             "experimental feature is not declared as an empty feature")
    default_line = next((line for line in manifest.splitlines()
                         if line.startswith("default = ")), "")
    _require(CAUSAL_FEATURE not in default_line,
             "experimental feature must not be a default feature")
    baseline_manifest = read_at(root, baseline_sha, "crates/quervant-core/Cargo.toml")
    _require(CAUSAL_FEATURE not in baseline_manifest,
             "merged baseline must not contain the experimental feature")

    return {
        "baseline_sha": baseline_sha,
        "candidate_sha": candidate_sha,
        "changed_production_paths": production,
        "causal_delta": delta,
        "generic_body_sha256": causal_body,
        "baseline_generic_body_sha256": baseline_body,
        "generic_attributes": attributes,
        "feature": CAUSAL_FEATURE,
        "mode_variable": MODE_VARIABLE,
        "restored_files_identical_to_historical": True,
    }
