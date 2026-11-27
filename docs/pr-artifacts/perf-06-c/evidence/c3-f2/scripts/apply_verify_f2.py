#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

START = "051104724125ba95d49a6d94b61500f974a3599f"
SOURCE = "crates/quervant-core/src/search/unified.rs"
SOURCE_BLOB = "eb1d1f31d7554bb99d030858e99b3d3d2946c2f7"
D = "docs/pr-artifacts/perf-06-c"
E1 = D + "/evidence/c3-f1"
E2 = D + "/evidence/c3-f2"
CONTRACT_SHA = "1107c78e330559d8631882fc815a2d78dd0cc901e8517fcb32487c4663e545c4"
FUNCTIONS = ("c3_u02_dispatch_and_count_matrix", "c3_u09_logical_budget_edges")
APPEND = {
    D + "/PERF06C3F1_EXECUTION_REPORT.md",
    "docs/PERF_OPTIMIZATION_ROADMAP.md",
    "docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md",
    "docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md",
}
NEW_DOCS = {
    D + "/PERF06C3F2_DETAILED_FIXUP_PLAN.md",
    D + "/PERF06C3F2_EXECUTION_REPORT.md",
}
FIXED_EVIDENCE = {
    "scripts/apply_verify_f2.py", "scripts/build_f2_contract.py",
    "contracts/command-contract.json", "verification.json",
    "historical-f1-verification.json", "audits/preflight.json",
    "audits/worktree-freeze.json", "audits/tested-freeze.json",
    "audits/post-local-qa-freeze.json", "audits/tested-diff.json",
    "summaries/case-output.txt", "summaries/metrics.json",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.STDOUT)


def blob(ref, path):
    if ref == "WORKTREE":
        p = Path(path)
        require(p.is_file() and not p.is_symlink(), f"missing/unsafe file: {path}")
        return p.read_bytes()
    return git("show", f"{ref}:{path}")


def mode(ref, path):
    if ref == "WORKTREE":
        p = Path(path)
        require(p.is_file() and not p.is_symlink(), f"missing/unsafe file: {path}")
        return "100755" if p.stat().st_mode & 0o111 else "100644"
    entry = git("ls-tree", ref, "--", path).decode("utf-8").strip()
    require(entry and "\t" in entry, f"missing tree mode: {path}")
    return entry.split()[0]


def diff_names(base, current, only_deleted=False):
    args = ["diff", "--name-only", "-z", "--no-renames"]
    if only_deleted:
        args.append("--diff-filter=D")
    args.append(base)
    if current != "WORKTREE":
        args.append(current)
    args.append("--")
    return {p.decode("utf-8") for p in git(*args).split(b"\0") if p}


def region(data, name):
    lines = data.splitlines(keepends=True)
    prefix = b"    fn " + name.encode("ascii") + b"("
    positions = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    require(len(positions) == 1, f"missing/duplicate function: {name}")
    start = positions[0]
    end = next((i + 1 for i in range(start + 1, len(lines))
                if lines[i] == b"    }\n"), None)
    require(end is not None, f"function close missing: {name}")
    return b"".join(lines[start:end])


def mask(data):
    for name in FUNCTIONS:
        old = region(data, name)
        require(data.count(old) == 1, f"ambiguous region: {name}")
        data = data.replace(old, ("<F2:" + name + ">\n").encode("ascii"), 1)
    return data


def replace_once(data, old, new, label):
    require(data.count(old) == 1, f"anchor not unique: {label}")
    return data.replace(old, new, 1)


def prescribed_raw(start):
    u02 = region(start, FUNCTIONS[0])
    a = replace_once(
        u02,
        b"        // contracts. Every document has one `grp` token, so n = df = avgdl = 24.\n",
        b"        // contracts. Every document has one `grp` token, so n = df = 24 and\n"
        b"        // avgdl = 1.\n",
        "U02 comment",
    )
    a = replace_once(
        a,
        b'            assert_ineligible_observation("batch");\n',
        b'            assert_ineligible_observation("batch");\n'
        b'            assert!(response.aggregation.is_none(), "batch: no aggregation");\n',
        "U02 normal batch None",
    )
    a = replace_once(
        a,
        b'            assert_eq!(c2_observation::legacy_routes(), 1, "batch legacy route");\n'
        b'            c3_assert_full_response(&response, &reference, "batch legacy parity");\n'
        b'            result_rows.push("batch");\n',
        b'            assert_eq!(c2_observation::legacy_routes(), 1, "batch legacy route");\n'
        b'            assert!(reference.aggregation.is_none(), "batch reference: no aggregation");\n'
        b'            c3_assert_full_response(&response, &reference, "batch legacy parity");\n'
        b'            eprintln!("C3 F2 U02 plain-batch aggregation=none normal+legacy");\n'
        b'            result_rows.push("batch");\n',
        "U02 reference None and marker",
    )
    u09 = region(start, FUNCTIONS[1])
    helper = b'''        /// Same-snapshot recovery with the generous limits of the `-G` row for this
        /// `M`; the complete response must equal the independently executed control.
        #[allow(clippy::too_many_arguments)]
        fn recover_at(
            fixture: &Fixture,
            request: &UnifiedRequest,
            m: usize,
            k: usize,
            entries: u64,
            bytes: u64,
            control: &UnifiedResponse,
            expected_keys: &[String],
            config: TopKDuplicateConfig,
            label: &str,
        ) {
            c3_reset_all();
            let recovered = run_with(fixture, request, limits(entries, bytes), config)
                .expect("same-snapshot generous recovery");
            c3_assert_certified(m, k, 1);
            assert_eq!(recovered.total_hits, m as u64, "{label}: recovery total");
            assert_eq!(
                keys(&recovered),
                expected_keys,
                "{label}: recovery literal keys"
            );
            assert!(recovered.next_cursor.is_some(), "{label}: recovery cursor");
            c3_assert_full_response(&recovered, control, label);
        }

'''
    b = replace_once(u09, helper, b"", "U09 suppressed recovery helper")
    call = b'''                        recover_at(
                            &fixture,
                            &request,
                            m,
                            k,
                            peak_entries,
                            generous_bytes,
                            &control,
                            &expected_keys,
                            config,
                            id,
                        );
'''
    inline = b'''                        // Same-snapshot recovery under the generous G-row limits.
                        c3_reset_all();
                        let recovered = run_with(
                            &fixture,
                            &request,
                            limits(peak_entries, generous_bytes),
                            config,
                        )
                        .expect("same-snapshot generous recovery");
                        c3_assert_certified(m, k, 1);
                        assert_eq!(recovered.total_hits, m as u64, "{id}: recovery total");
                        assert_eq!(
                            keys(&recovered),
                            expected_keys,
                            "{id}: recovery literal keys"
                        );
                        assert!(recovered.next_cursor.is_some(), "{id}: recovery cursor");
                        c3_assert_full_response(&recovered, &control, id);
'''
    b = replace_once(b, call, inline, "U09 recovery call")
    require(b"recover_at(" not in b and b"#[allow(clippy::too_many_arguments)]" not in b,
            "U09 helper/suppression remains")
    result = replace_once(start, u02, a, "U02 region")
    result = replace_once(result, u09, b, "U09 region")
    require(mask(start) == mask(result), "raw transformation changed protected bytes")
    return result


def format_source(data):
    # unified.rs has no out-of-line module declarations at the pinned source.
    # stdin means rustfmt does not write a repository file. Preserve all diagnostics
    # on failure, and do not change config or use an alternate toolchain.
    result = subprocess.run(
        ["rustfmt", "+1.98.1", "--edition", "2024", "--emit", "stdout"],
        cwd=Path(SOURCE).resolve().parent,
        input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0 or result.stderr:
        sys.stderr.buffer.write(result.stderr)
        raise ValueError(f"pinned rustfmt failed or emitted diagnostics: {result.returncode}")
    require(result.stdout, "pinned rustfmt emitted no source")
    return result.stdout


def exact_expected():
    require(git("rev-parse", f"{START}:{SOURCE}").decode().strip() == SOURCE_BLOB,
            "START source Git blob mismatch")
    before = blob(START, SOURCE)
    raw = prescribed_raw(before)
    require(format_source(before) == before, "pinned START rustfmt roundtrip mismatch")
    expected = format_source(raw)
    require(mask(before) == mask(expected), "formatter changed protected bytes")
    for name in FUNCTIONS:
        original = region(before, name)
        updated = region(expected, name)
        require(original != updated, f"expected region unchanged: {name}")
        # No new lint attributes. Existing unrelated allow attributes, if any, in
        # either function must be a subset of START, not fabricated by formatter.
        old_attrs = re.findall(rb"#\s*\[\s*allow\s*\([^\]]*\)\s*\]", original)
        new_attrs = re.findall(rb"#\s*\[\s*allow\s*\([^\]]*\)\s*\]", updated)
        for attr in new_attrs:
            require(attr in old_attrs, f"new allow attribute in {name}")
            old_attrs.remove(attr)
    require(b"#[allow(clippy::too_many_arguments)]" not in region(expected, FUNCTIONS[1]),
            "U09 suppression survives")
    require(b"recover_at(" not in region(expected, FUNCTIONS[1]), "U09 helper survives")
    return before, raw, expected


def final_docs_paths():
    old_contract = blob(START, E1 + "/contracts/command-contract.json")
    require(sha(old_contract) == CONTRACT_SHA, "F1 contract changed")
    items = json.loads(old_contract)["receipts"]
    rows = [item for item in items if item["classification"] == "PASS"]
    require(len(rows) == 45, "wrong F1 final row count")
    receipts = set()
    for row in rows:
        label = row["label"]
        require(label.startswith("f1_") and row["path"] == f"final/{label}.json",
                "unexpected F1 receipt label/path")
        new_label = "f2_" + label[3:]
        receipts.add(E2 + "/receipts/final/" + new_label + ".json")
    require(len(receipts) == 45, "duplicate receipt labels")
    evidence = {E2 + "/" + p for p in FIXED_EVIDENCE} | receipts
    return APPEND | NEW_DOCS | evidence


def assert_sha(ref):
    require(re.fullmatch(r"[0-9a-f]{40}", ref) is not None,
            "immutable full SHA required")
    require(git("rev-parse", ref).decode().strip() == ref, "unresolved revision")


def verify(current, tested=None):
    if current != "WORKTREE":
        assert_sha(current)
    before, raw, expected = exact_expected()
    require(blob(current, SOURCE) == expected, "actual source differs from exact F2 design")
    require(mode(current, SOURCE) == mode(START, SOURCE) == "100644",
            "source file mode changed")
    paths = diff_names(START, current)
    require(not diff_names(START, current, only_deleted=True), "deleted tracked path")
    if tested is None:
        require(paths == {SOURCE}, f"source-only path set mismatch: {sorted(paths)}")
        if current != "WORKTREE":
            require(git("rev-parse", current + "^").decode().strip() == START,
                    "tested commit not direct child of START")
    else:
        assert_sha(tested)
        require(git("rev-parse", tested + "^").decode().strip() == START,
                "tested commit not direct child of START")
        require(diff_names(START, tested) == {SOURCE}, "tested source scope mismatch")
        require(blob(tested, SOURCE) == expected, "tested source differs from exact design")
        docs = final_docs_paths()
        require(paths == {SOURCE} | docs, f"final scope mismatch: {sorted(paths ^ ({SOURCE} | docs))}")
        require(diff_names(tested, current) == docs, "post-test path set mismatch")
        if current == "WORKTREE":
            # Call final-mode worktree verification only after explicit staging.
            require(git("rev-parse", "HEAD").decode().strip() == tested,
                    "staging HEAD not F2_TESTED")
            require(not git("diff", "--name-only", "-z", "--"),
                    "unstaged tracked modifications after explicit stage")
        else:
            git("merge-base", "--is-ancestor", tested, current)
        for path in sorted(docs):
            if path in APPEND:
                require(blob(current, path).startswith(blob(START, path)),
                        f"historical doc prefix changed: {path}")
                require(blob(current, path) != blob(START, path), f"missing erratum: {path}")
                require(mode(current, path) == mode(START, path), f"doc mode changed: {path}")
            else:
                require(not git("ls-tree", START, "--", path), f"new path already existed: {path}")
                require(mode(current, path) == "100644", f"new path must be regular 0644: {path}")
                require(blob(current, path), f"empty new artifact: {path}")
    return {
        "status": "PASS", "start": START, "current": current, "tested": tested,
        "changed_paths": sorted(paths), "source_blob_at_start": SOURCE_BLOB,
        "source_before_sha256": sha(before), "raw_prescribed_sha256": sha(raw),
        "formatted_prescribed_sha256": sha(expected),
        "actual_source_sha256": sha(blob(current, SOURCE)),
        "protected_bytes_sha256": sha(mask(before)),
        "authorized_functions": list(FUNCTIONS),
        "formatter_argv": ["rustfmt", "+1.98.1", "--edition", "2024", "--emit", "stdout"],
        "normal_build_source_equal": True, "all_other_test_bytes_equal": True,
        "no_new_lint_suppression": True,
        "tested_to_final_docs_only": bool(tested),
        "checker_sha256": sha(Path(__file__).read_bytes()),
    }


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("apply")
    check = sub.add_parser("verify")
    check.add_argument("current")
    check.add_argument("--tested")
    args = parser.parse_args()
    try:
        root = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
        require(Path.cwd().resolve() == root, "run from workspace root")
        if args.mode == "apply":
            require(git("rev-parse", "HEAD").decode().strip() == START, "HEAD is not START")
            require(not git("status", "--porcelain=v1", "--untracked-files=no"),
                    "tracked worktree/index not clean")
            before, raw, expected = exact_expected()
            require(blob("WORKTREE", SOURCE) == before, "worktree source not START")
            Path(SOURCE).write_bytes(expected)
            result = verify("WORKTREE")
        else:
            result = verify(args.current, args.tested)
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "detail": str(exc)}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
