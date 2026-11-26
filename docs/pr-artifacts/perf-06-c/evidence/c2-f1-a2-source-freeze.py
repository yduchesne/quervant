#!/usr/bin/env python3
"""Exact A2 checks: START TESTED [FINAL_HEAD], or --worktree-final START."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

if not __debug__:
    raise SystemExit("Do not run this verifier with -O or PYTHONOPTIMIZE.")

READER = "crates/quervant-core/src/segment/reader.rs"
STORED = "crates/quervant-core/src/segment/stored_blocks.rs"
UNIFIED = "crates/quervant-core/src/search/unified.rs"
EXECUTE = "crates/quervant-core/src/search/execute.rs"
F1_START = "46ccab0a606a56a8b9034ab4db5c9c4df969d098"
A1_START = "2bf9539cd2f53838ad1aca406ca4e67a34229ff6"
OLD_DECL = "#[cfg(test)]\npub(crate) static CERTIFICATE_BUILDS: std::sync::atomic::AtomicU64 =\n    std::sync::atomic::AtomicU64::new(0);\n\n"
TLS_LINE = "    static CERTIFICATE_BUILDS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };\n"
HELPERS = """#[cfg(test)]
pub(crate) fn record_certificate_build() {
    CERTIFICATE_BUILDS.with(|value| value.set(value.get() + 1));
}

#[cfg(test)]
pub(crate) fn certificate_builds() -> u64 {
    CERTIFICATE_BUILDS.with(std::cell::Cell::get)
}

"""
OLD_SITE = "        #[cfg(test)]\n        super::stored_blocks::CERTIFICATE_BUILDS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);\n"
NEW_SITE = "        #[cfg(test)]\n        super::stored_blocks::record_certificate_build();\n"
OLD_COMMENT = "    /// PERF-06-C2-F1: this segment's only key-identity attempt was refused, so the\n    /// accepted owned B2 key handler ran for it.\n"
NEW_COMMENT = "    /// PERF-06-C2-F1-A1: record selection of the accepted owned B2 key handler.\n    /// Refusal and ExactSet bypass are distinguished by config and B3 counters.\n"
SITE_A = "                    #[cfg(test)]\n                    if matches!(key_binder, KeyBinder::Fallback) {\n                        c2_observation::record_owned_key_fallback_segment(segment_index);\n                    }\n"
SITE_B = "        #[cfg(test)]\n        c2_observation::record_collected_segment(segment_index, heap.len(), *total_hits);\n"


A2_START = "cdffd5b486ce46312abf4c45c80b9d33ecbf657d"
SOURCE_PATHS = [".", ":(top,exclude)docs/**"]
DOC_ROOT = "docs/pr-artifacts/perf-06-c/"
A2_PLAN = DOC_ROOT + "PERF06C2F1_A2_CLOSEOUT_PLAN.md"
A2_REPORT = DOC_ROOT + "PERF06C2F1_A2_EXECUTION_REPORT.md"
EVIDENCE_ROOT = DOC_ROOT + "evidence/"
EVIDENCE_PREFIX = EVIDENCE_ROOT + "c2-f1-a2-"
OLD_REPORTS = [
    DOC_ROOT + "PERF06C2_EXECUTION_REPORT.md",
    DOC_ROOT + "PERF06C2F1_EXECUTION_REPORT.md",
    DOC_ROOT + "PERF06C2F1_A1_EXECUTION_REPORT.md",
]
SERIES = "docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md"
ROADMAP = "docs/PERF_OPTIMIZATION_ROADMAP.md"
APPEND_ONLY = [*OLD_REPORTS, SERIES]
EDITABLE_DOCS = {A2_PLAN, A2_REPORT, *APPEND_ONLY, ROADMAP}
FOREIGN_DOC = "docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt"
TEST_FIRST = "    #[test]\n    fn certificate_retains_flat_offsets_and_hot_path_is_direct() {"
TEST_FOLLOWING = "    #[test]\n    fn unselected_corruption_blocks_certificate() {"
DECOMPRESSED_TLS = "    static DECOMPRESSED_BLOCKS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };\n"
DECOMPRESSED_GETTER = "#[cfg(test)]\npub(crate) fn decompressed_blocks() -> u64 {\n    DECOMPRESSED_BLOCKS.with(std::cell::Cell::get)\n}\n\n"
RED_HELPERS = """#[cfg(test)]
pub(crate) fn record_certificate_build() {
    CERTIFICATE_BUILDS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
}

#[cfg(test)]
pub(crate) fn certificate_builds() -> u64 {
    CERTIFICATE_BUILDS.load(std::sync::atomic::Ordering::SeqCst)
}

"""

APPROVED_TEST = '    #[test]\n    fn certificate_retains_flat_offsets_and_hot_path_is_direct() {\n        use crate::segment::stored::test_observation;\n        use crate::segment::stored_blocks::certificate_builds;\n        let _serial = serial();\n        let bytes = v2_bytes(300);\n        let (state, _budget) = admitted_state(bytes.clone());\n        let reader = SegmentReader::from_shared(Arc::clone(&state));\n        test_observation::reset();\n        let builds_before = certificate_builds();\n\n        let sibling_delta = std::thread::scope(|scope| {\n            scope\n                .spawn(move || {\n                    // The parent holds serial(); the worker must not acquire it.\n                    let (sibling_state, _sibling_budget) = admitted_state(bytes);\n                    let sibling_reader = SegmentReader::from_shared(Arc::clone(&sibling_state));\n                    let sibling_before = certificate_builds();\n                    let selected = sibling_reader\n                        .stored_docs_selected(&[0, 299])\n                        .expect("sibling first access");\n                    assert_eq!(selected.len(), 2);\n                    assert_eq!(sibling_state.stored_blocks_offset_len(), Some(300 + 3));\n                    let sibling_after = certificate_builds();\n                    assert_eq!(sibling_after - sibling_before, 1);\n                    sibling_after - sibling_before\n                })\n                .join()\n                .expect("sibling certificate build")\n        });\n        assert_eq!(sibling_delta, 1);\n        assert_eq!(\n            certificate_builds() - builds_before,\n            0,\n            "a different thread\'s real certificate build must not change this thread\'s count"\n        );\n\n        let first = reader.stored_docs_selected(&[0, 299]).expect("first");\n        assert_eq!(first.len(), 2);\n        assert_eq!(state.stored_blocks_offset_len(), Some(300 + 3));\n        let builds_after = certificate_builds();\n        assert_eq!(builds_after - builds_before, 1);\n        // Warm direct access: one touched block, one selected record, no full scan.\n        test_observation::reset();\n        reader.stored_docs_selected(&[0]).expect("one");\n        assert_eq!(test_observation::direct_records(), 1);\n        assert_eq!(test_observation::hot_block_lookups(), 1);\n        assert_eq!(test_observation::full_scan_records(), 0);\n        assert_eq!(test_observation::local_id_reservations(), 0);\n        assert_eq!(test_observation::extra_outer_allocations(), 0);\n        assert_eq!(test_observation::selected_boundary_checks(), 1);\n        assert_eq!(test_observation::full_offset_pair_checks(), 0);\n        // Same block: one inflation, two direct records, one lookup.\n        test_observation::reset();\n        reader.stored_docs_selected(&[1, 2]).expect("same block");\n        assert_eq!(test_observation::direct_records(), 2);\n        assert_eq!(test_observation::hot_block_lookups(), 1);\n        assert_eq!(test_observation::local_id_reservations(), 1);\n        assert_eq!(test_observation::extra_outer_allocations(), 0);\n        assert_eq!(test_observation::selected_boundary_checks(), 2);\n        // Two blocks: two direct records, two lookups.\n        test_observation::reset();\n        reader.stored_docs_selected(&[0, 200]).expect("two blocks");\n        assert_eq!(test_observation::direct_records(), 2);\n        assert_eq!(test_observation::hot_block_lookups(), 2);\n        assert_eq!(test_observation::extra_outer_allocations(), 1);\n        assert_eq!(test_observation::local_id_reservations(), 0);\n        assert_eq!(test_observation::selected_boundary_checks(), 2);\n        // Empty selection after certification does no work.\n        test_observation::reset();\n        assert!(reader.stored_docs_selected(&[]).expect("empty").is_empty());\n        assert_eq!(test_observation::direct_records(), 0);\n        assert_eq!(test_observation::hot_block_lookups(), 0);\n        assert_eq!(test_observation::full_scan_records(), 0);\n        assert_eq!(\n            certificate_builds(),\n            builds_after,\n            "warm selected access must reuse the existing certificate"\n        );\n    }\n\n'


def git(*args):
    return subprocess.check_output(["git", "--no-pager", "-c", "color.ui=false", *args])


def paths(raw):
    return {item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item}


def blob_bytes(rev, path):
    return git("show", f"{rev}:{path}")


def blob(rev, path):
    return blob_bytes(rev, path).decode("utf-8")


def replace_once(text, token, replacement):
    assert text.count(token) == 1, ("unique literal required", token)
    return text.replace(token, replacement, 1)


def remove_once(text, token):
    return replace_once(text, token, "")


def region(text, first, following):
    assert text.count(first) == text.count(following) == 1
    a, b = text.index(first), text.index(following)
    assert a < b
    return a, b


def remove_region(text, first, following):
    a, b = region(text, first, following)
    return text[:a] + text[b:]


def without_c2_tail(text):
    first, last = "#[cfg(test)]\nmod c2_tests {", "// C2_TESTS_CLOSE_MARKER"
    assert text.count(first) == text.count(last) == 1
    a, b = text.index(first), text.index(last) + len(last)
    assert a < b and not text[b:].strip()
    return text[:a]


def compare_reader(old, new):
    a, b = region(old, TEST_FIRST, TEST_FOLLOWING)
    expected = old[:a] + APPROVED_TEST + old[b:]
    expected = replace_once(expected, OLD_SITE, NEW_SITE)
    assert new == expected, "reader must contain exactly the approved test and original-site helper substitution"


def expected_stored(old, red):
    assert old.count(OLD_DECL) == 1
    if red:
        return replace_once(old, DECOMPRESSED_GETTER, DECOMPRESSED_GETTER + RED_HELPERS)
    expected = remove_once(old, OLD_DECL)
    expected = replace_once(expected, DECOMPRESSED_TLS, DECOMPRESSED_TLS + TLS_LINE)
    return replace_once(expected, DECOMPRESSED_GETTER, DECOMPRESSED_GETTER + HELPERS)


def compare_stored(old, new):
    assert new == expected_stored(old, False), "stored_blocks must contain the exact TLS replacement at the prescribed anchors"


def compare_red(old_reader, red_reader, old_stored, red_stored):
    compare_reader(old_reader, red_reader)
    assert red_stored == expected_stored(old_stored, True), "RED must retain the global AtomicU64 and use exactly its prescribed helpers"


def normal_execute(text):
    return remove_region(text, "#[cfg(test)]\nmod c2_physical_tests {", "#[cfg(test)]\nmod budget_tests {")


def normal_unified(text, remove_sites):
    text = without_c2_tail(text)
    text = remove_region(text, "#[cfg(test)]\npub(crate) mod c2_observation {", "#[cfg(test)]\n#[allow(clippy::needless_option_as_deref)]\nmod tests {")
    if remove_sites:
        text = remove_once(remove_once(text, SITE_A), SITE_B)
    return text


def allowed_document(path):
    return path in EDITABLE_DOCS or path.startswith(EVIDENCE_PREFIX)


def changed_paths(start, end, *pathspec):
    return paths(git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", start, end, "--", *pathspec))


def tree_paths(rev):
    return paths(git("ls-tree", "-r", "--name-only", "-z", rev))


def check_range(start, end, require_source):
    changed = changed_paths(start, end)
    outside_docs = {path for path in changed if not path.startswith("docs/")}
    expected_source = {READER, STORED} if require_source else set()
    assert outside_docs == expected_source, ("unapproved source/build-input change", outside_docs)
    assert all(path in expected_source or allowed_document(path) for path in changed), ("path outside the closed allowlist", changed)
    old_paths, new_paths = tree_paths(start), tree_paths(end)
    assert not (old_paths - new_paths), ("file deletion is not authorized", old_paths - new_paths)
    for path in old_paths:
        if path.startswith(EVIDENCE_ROOT):
            assert blob_bytes(start, path) == blob_bytes(end, path), ("historical evidence bytes changed", path)
    for path in APPEND_ONLY:
        assert blob_bytes(end, path).startswith(blob_bytes(start, path)), ("append-only document prefix changed", path)
    if A2_PLAN in old_paths:
        assert blob_bytes(start, A2_PLAN) == blob_bytes(end, A2_PLAN), "the supplied A2 plan changed"
    for path in new_paths - old_paths:
        assert path in {A2_PLAN, A2_REPORT} or path.startswith(EVIDENCE_PREFIX), ("new file outside A2 artifacts", path)
    return changed


def check_inherited(unified, execute):
    assert blob_bytes(A1_START, EXECUTE) == execute
    old_u = remove_once(without_c2_tail(blob(A1_START, UNIFIED)), OLD_COMMENT)
    new_u = remove_once(without_c2_tail(unified), NEW_COMMENT)
    assert old_u == new_u
    assert normal_execute(blob(F1_START, EXECUTE)) == normal_execute(execute.decode("utf-8"))
    assert normal_unified(blob(F1_START, UNIFIED), False) == normal_unified(unified, True)


def worktree_final(start):
    assert start == A2_START, ("unexpected A2 START", start)
    root = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
    assert Path.cwd().resolve() == root
    head = git("rev-parse", "HEAD").decode().strip()
    git("merge-base", "--is-ancestor", start, head)
    untracked = paths(git("ls-files", "--others", "--exclude-standard", "-z"))
    assert all(allowed_document(path) or path == FOREIGN_DOC for path in untracked), ("unapproved untracked path", untracked)
    for config in [".cargo/config", ".cargo/config.toml"]:
        if os.path.lexists(root / config):
            assert paths(git("ls-files", "-z", "--", config)) == {config}, ("untracked Cargo configuration, including ignored files", config)
    changed = paths(git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", start))
    changed |= untracked - {FOREIGN_DOC}
    outside_docs = {path for path in changed if not path.startswith("docs/")}
    assert outside_docs == {READER, STORED}, ("unapproved source/build-input change", outside_docs)
    assert all(path in {READER, STORED} or allowed_document(path) for path in changed), ("path outside the closed allowlist", changed)
    old_paths = tree_paths(start)
    for path in old_paths:
        assert (root / path).exists(), ("file deletion is not authorized", path)
        if path.startswith(EVIDENCE_ROOT):
            assert blob_bytes(start, path) == (root / path).read_bytes(), ("historical evidence bytes changed", path)
    for path in APPEND_ONLY:
        assert (root / path).read_bytes().startswith(blob_bytes(start, path)), ("append-only document prefix changed", path)
    compare_reader(blob(start, READER), (root / READER).read_bytes().decode("utf-8"))
    compare_stored(blob(start, STORED), (root / STORED).read_bytes().decode("utf-8"))
    check_inherited((root / UNIFIED).read_bytes().decode("utf-8"), (root / EXECUTE).read_bytes())
    patch = git("diff", "--no-ext-diff", "--no-textconv", "--binary", start, "--", *SOURCE_PATHS)
    import base64
    print(json.dumps({"result": "PASS", "mode": "worktree-final", "A2_START": start,
        "worktree_HEAD": head, "normal_build_source_equal": True,
        "other_source_build_inputs_and_old_evidence_unchanged": True,
        "A1_and_original_F1_checks": "PASS", "changed_paths": sorted(changed),
        "source_patch_sha256": hashlib.sha256(patch).hexdigest(),
        "source_patch_base64": base64.b64encode(patch).decode("ascii"),
        "roadmap_scope": "MANUAL_C2_NOTE_REVIEW_REQUIRED" if ROADMAP in changed else "UNCHANGED"}, indent=2))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--worktree-final":
        worktree_final(sys.argv[2])
        return
    assert len(sys.argv) in {3, 4}, "usage: script A2_START A2_TESTED [FINAL_HEAD]"
    start, tested = sys.argv[1:3]
    final = sys.argv[3] if len(sys.argv) == 4 else tested
    assert all(re.fullmatch(r"[0-9a-f]{40}", rev) for rev in [start, tested, final])
    assert start == A2_START, ("unexpected A2 START", start)
    git("merge-base", "--is-ancestor", start, tested)
    git("merge-base", "--is-ancestor", tested, final)
    changed_tested = check_range(start, tested, True)
    compare_reader(blob(start, READER), blob(tested, READER))
    compare_stored(blob(start, STORED), blob(tested, STORED))
    check_inherited(blob(tested, UNIFIED), blob_bytes(tested, EXECUTE))
    changed_final = check_range(tested, final, False)
    check_range(start, final, True)
    identities = []
    for rev in dict.fromkeys([start, tested, final]):
        for path in [READER, STORED, UNIFIED, EXECUTE]:
            raw = blob_bytes(rev, path)
            identities.append({"revision": rev, "path": path,
                "git_blob": git("rev-parse", f"{rev}:{path}").decode().strip(),
                "sha256": hashlib.sha256(raw).hexdigest()})
    roadmap_changed = ROADMAP in changed_tested | changed_final
    print(json.dumps({"result": "PASS", "A2_START": start, "A2_TESTED": tested,
        "FINAL_HEAD": final, "normal_build_source_equal": True,
        "other_source_build_inputs_and_old_evidence_unchanged": True,
        "tested_to_final_docs_only": True, "A1_and_original_F1_checks": "PASS",
        "roadmap_scope": "MANUAL_C2_NOTE_REVIEW_REQUIRED" if roadmap_changed else "UNCHANGED",
        "changed_at_tested": sorted(changed_tested), "changed_after_tested": sorted(changed_final),
        "identities": identities}, indent=2))


if __name__ == "__main__":
    main()
