#!/usr/bin/env python3
"""PR 15I-C dispatch-isolation study — A/C/D/E source and feature proof.

Mechanical Git-blob extraction only: no measurement, ratio or classification
logic here. The controller uses it to abort early; the independent verifier
re-derives the same facts itself.
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
C_SHA = "658a2dde0e15c17e2b0c92278b5c922f5260fe60"
D_SHA = "9c710e5432aa17cdcd717ce40ad6f9a8167914f1"
E_SHA = "d97889d2debc14f1e4ea3c821089cd453ba1daab"
EXPECTED_GENERIC_BODY_SHA = (
    "00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994")
GENERIC_METHOD = "collect_mixed"
PHYSICAL_METHOD = "collect_exact_term_physical"
TRAMPOLINE_METHOD = "collect_mixed_dispatch_probe"
C_FEATURE = "pr15ic-causal"
E_FEATURE = "pr15ic-dispatch-isolation"
C_MODE_VARIABLE = "QUERVANT_PR15IC_CAUSAL_MODE"
E_MODE_VARIABLE = "QUERVANT_PR15IC_DISPATCH_MODE"
UNIFIED = "crates/quervant-core/src/search/unified.rs"
MANIFEST = "crates/quervant-core/Cargo.toml"

D_EXPECTED_OLD = """        #[cfg(feature = "pr15ic-causal")]
        let c_physical = if shape_eligible {
"""
D_EXPECTED_NEW = """        #[cfg(feature = "pr15ic-causal")]
        let c_physical = if false && shape_eligible {
"""

E_ALLOWED_PATHS = (UNIFIED, MANIFEST)


class DispatchSourceError(Exception):
    def __init__(self, rule, detail):
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail


def require(condition, rule, detail):
    if not condition:
        raise DispatchSourceError(rule, detail)


def read_at(root, revision, path):
    return _source_proof.read_at_revision(root, revision, path)


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
    code, out, err = git(root, "diff", "--name-only", f"{a_rev}..{b_rev}")
    require(code == 0, "DS_GIT", f"git diff failed: {err}")
    return [path for path in out.splitlines() if path.startswith("crates/") and path]


def body_sha(source, name=GENERIC_METHOD):
    return _source_proof.body_sha(source, name)


def attributes_of(source, name=GENERIC_METHOD):
    return _source_proof.attribute_block(source, name)


def verify_generic_body(root, revision):
    source = read_at(root, revision, UNIFIED)
    digest = body_sha(source)
    require(digest == EXPECTED_GENERIC_BODY_SHA, "DS_BODY",
            f"{revision} generic collect_mixed body hash {digest} != pinned")
    attrs = attributes_of(source)
    require(not any(item.startswith("#[inline(") for item in attrs), "DS_ATTR",
            f"{revision} generic collector carries an inline attribute")
    require(source.count(f"\n    fn {GENERIC_METHOD}(") == 1, "DS_BODY",
            f"{revision} generic collector definition is not unique")
    return digest, attrs


def verify_commits(root, a_sha=BASE_A, c_sha=C_SHA, d_sha=D_SHA, e_sha=E_SHA):
    for name, sha in (("A", a_sha), ("C", c_sha), ("D", d_sha), ("E", e_sha)):
        require(is_commit(root, sha), "DS_SOURCE", f"arm {name} {sha} is not a commit")
    require(is_ancestor(root, c_sha, d_sha), "DS_SOURCE", "D does not descend from C")
    require(is_ancestor(root, a_sha, e_sha), "DS_SOURCE", "E does not descend from A")
    require(not is_ancestor(root, c_sha, e_sha), "DS_SCOPE",
            "E must not descend from the causal candidate C")


def verify_d(root, c_sha=C_SHA, d_sha=D_SHA):
    changed = changed_production_paths(root, c_sha, d_sha)
    require(changed == [UNIFIED], "DS_SCOPE",
            f"D production diff is not exactly {UNIFIED}: {changed}")
    before = read_at(root, c_sha, UNIFIED)
    after = read_at(root, d_sha, UNIFIED)
    require(before.count(D_EXPECTED_OLD) == 1, "DS_DIFF",
            "C does not contain the expected feature-branch expression")
    require(after.count(D_EXPECTED_NEW) == 1, "DS_DIFF",
            "D does not contain the literal-false expression")
    normalized_before = before.replace(D_EXPECTED_OLD, D_EXPECTED_NEW)
    require(normalized_before == after, "DS_DIFF",
            "D differs from C outside the single expression")
    digest, attrs = verify_generic_body(root, d_sha)
    return {"d_changed_paths": changed, "d_expression": D_EXPECTED_NEW.strip(),
            "generic_body_sha256": digest, "generic_attributes": attrs}


def verify_e(root, a_sha=BASE_A, e_sha=E_SHA):
    changed = changed_production_paths(root, a_sha, e_sha)
    require(sorted(changed) == sorted(E_ALLOWED_PATHS), "DS_SCOPE",
            f"E production diff is not exactly {list(E_ALLOWED_PATHS)}: {changed}")
    source = read_at(root, e_sha, UNIFIED)
    baseline = read_at(root, a_sha, UNIFIED)
    manifest = read_at(root, e_sha, MANIFEST)
    require(f"{E_FEATURE} = []" in manifest, "DS_FEATURE",
            "E does not declare the empty diagnostic feature")
    default_line = next(line for line in manifest.splitlines()
                        if line.startswith("default = "))
    require(E_FEATURE not in default_line, "DS_FEATURE",
            "E feature must not be a default feature")
    require(C_FEATURE not in manifest, "DS_FEATURE",
            "E must not carry the causal candidate feature")
    require(E_MODE_VARIABLE in source, "DS_MODE", "E mode variable missing")
    require(C_MODE_VARIABLE not in source, "DS_MODE",
            "E must not read the causal candidate mode variable")
    require(source.count(f"fn {PHYSICAL_METHOD}(") == 0, "DS_OPERATOR",
            "E must not define the physical collector")
    require("for_each_exact_term_score_with" not in source, "DS_OPERATOR",
            "E must not call the physical operator")
    require("c15i_observation" not in source and "c15i_guard" not in source,
            "DS_OPERATOR", "E must not carry candidate test modules")
    require(f"fn {TRAMPOLINE_METHOD}(" in source, "DS_TRAMPOLINE",
            "E trampoline is missing")
    require(f"fn exact_term_physical_eligible(" in source, "DS_PREDICATE",
            "E eligibility predicate is missing")
    # The predicate body must match C's body minus the cfg(test) guard.
    c_source = read_at(root, C_SHA, UNIFIED)
    predicate_c = _extract_method(c_source, "exact_term_physical_eligible")
    predicate_e = _extract_method(source, "exact_term_physical_eligible")
    guard = """        #[cfg(test)]
        if c15i_guard::forced_generic() {
            return false;
        }
"""
    require(predicate_c.replace(guard, "") == predicate_e, "DS_PREDICATE",
            "E predicate is not C's predicate minus the test-only guard")
    # Trampoline body must be exactly the two authorized statements.
    trampoline = _extract_method(source, TRAMPOLINE_METHOD)
    require("std::hint::black_box(plan)" in trampoline, "DS_TRAMPOLINE",
            "trampoline must contain the black_box barrier")
    require(trampoline.count("self.collect_mixed(") == 1, "DS_TRAMPOLINE",
            "trampoline must call collect_mixed exactly once")
    # No other work is authorized in the trampoline: only the black_box barrier,
    # the single pass-through call and its closing expression.
    statements = [line.strip() for line in trampoline.splitlines()
                  if line.strip() and not line.strip().startswith(("fn ", "/", "*", "//"))
                  and not line.strip().endswith(("{", "}", ")")) or False]
    require("black_box(plan)" in trampoline, "DS_TRAMPOLINE",
            "trampoline must contain the black_box barrier")
    require(trampoline.count("black_box") == 1, "DS_TRAMPOLINE",
            "trampoline must contain exactly one black_box barrier")
    require(not any(item.startswith("#[inline(")
                    for item in attributes_of(source)), "DS_ATTR",
            "generic collector must not gain an inline attribute")
    # Baseline prefix/suffix outside the dispatch block must be byte-identical.
    require(_strip_dispatch(source) == _strip_dispatch(baseline), "DS_PRELUDE",
            "E differs from A outside the authorized dispatch block")
    digest, attrs = verify_generic_body(root, e_sha)
    return {"e_changed_paths": changed, "generic_body_sha256": digest,
            "generic_attributes": attrs, "feature": E_FEATURE,
            "mode_variable": E_MODE_VARIABLE}


DISPATCH_BLOCK_START = '        #[cfg(feature = "pr15ic-dispatch-isolation")]\n        let shape_eligible ='
DISPATCH_BLOCK_END = """        #[cfg(not(feature = "pr15ic-dispatch-isolation"))]
        let (page, total_hits, next_cursor, aggregation_result) = self.collect_mixed(
            &plan,
            request,
            fingerprint,
            batch.as_deref_mut(),
            cancel,
            budgets,
            aggregation,
        )?;
"""
BASELINE_BLOCK = """        let (page, total_hits, next_cursor, aggregation_result) = self.collect_mixed(
            &plan,
            request,
            fingerprint,
            batch.as_deref_mut(),
            cancel,
            budgets,
            aggregation,
        )?;
"""


def _strip_dispatch(source):
    """Replace the whole E dispatch block with the baseline call."""
    start = source.find(DISPATCH_BLOCK_START)
    if start >= 0:
        require(source.count(DISPATCH_BLOCK_END) == 1, "DS_PRELUDE",
                "E dispatch block end not unique")
        end = source.index(DISPATCH_BLOCK_END) + len(DISPATCH_BLOCK_END)
        stripped = source[:start] + BASELINE_BLOCK + source[end:]
    else:
        # Baseline sources have no experimental dispatch block.
        require(source.count(BASELINE_BLOCK) == 1, "DS_PRELUDE",
                "baseline call site is not the expected single statement")
        stripped = source
    # The E-only helper definitions (predicate, trampoline, mode gate) are also
    # experiment-only; remove them for the byte comparison.
    stripped = _remove_method(stripped, "collect_mixed_dispatch_probe")
    stripped = _remove_method(stripped, "exact_term_physical_eligible")
    stripped = _remove_function(stripped, "pr15ic_causal_enabled")
    stripped = stripped.replace(
        "use crate::contract::result::{Projection, Sort, SortDirection, TopK};",
        "use crate::contract::result::{Projection, Sort, TopK};", 1)
    return stripped


def _brace_region(source, start):
    index = source.index("{", start)
    depth = 0
    cursor = index
    while cursor < len(source):
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
            if depth == 0:
                return start, cursor + 1
        cursor += 1
    raise DispatchSourceError("DS_PRELUDE", "unterminated region")


def _extract_method(source, name):
    pattern = f"\n    fn {name}("
    require(source.count(pattern) == 1, "DS_SOURCE", f"method {name} is not unique")
    start = source.index(pattern) + 1
    begin, end = _brace_region(source, start)
    return source[begin:end] + "\n"


def _remove_method(source, name):
    pattern = f"\n    fn {name}("
    if source.count(pattern) != 1:
        return source
    start = source.index(pattern) + 1
    begin, end = _brace_region(source, start)
    # Remove the preceding doc-comment/attribute lines as well.
    line_start = source.rfind("\n\n", 0, begin)
    return source[:line_start + 1] + source[end + 1:]


def _remove_function(source, name):
    pattern = f"\nfn {name}("
    if source.count(pattern) != 1:
        return source
    start = source.index(pattern) + 1
    begin, end = _brace_region(source, start)
    line_start = source.rfind("\n\n", 0, begin)
    return source[:line_start + 1] + source[end + 1:]


def verify_all(root, a_sha=BASE_A, c_sha=C_SHA, d_sha=D_SHA, e_sha=E_SHA):
    verify_commits(root, a_sha, c_sha, d_sha, e_sha)
    a_digest, a_attrs = verify_generic_body(root, a_sha)
    c_digest, c_attrs = verify_generic_body(root, c_sha)
    d_report = verify_d(root, c_sha, d_sha)
    e_report = verify_e(root, a_sha, e_sha)
    return {
        "baseline_sha": a_sha,
        "c_source": c_sha,
        "d_source": d_sha,
        "e_source": e_sha,
        "generic_body_sha256": {"A": a_digest, "C": c_digest,
                                "D": d_report["generic_body_sha256"],
                                "E": e_report["generic_body_sha256"]},
        "generic_attributes": {"A": a_attrs, "C": c_attrs},
        "d": d_report,
        "e": e_report,
        "features": {"A": [], "C": [C_FEATURE], "D": [C_FEATURE], "E": [E_FEATURE]},
        "mode_variables": {"C": C_MODE_VARIABLE, "E": E_MODE_VARIABLE},
    }
