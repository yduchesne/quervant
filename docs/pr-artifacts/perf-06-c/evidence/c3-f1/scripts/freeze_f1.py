#!/usr/bin/env python3
"""Verify C3-F1's function-only delta and immutable post-test source."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

START = "ee77917d303b060b0d38ab88e5d9ae73625f6676"
FUNCTIONS = {
    "crates/quervant-core/src/search/score.rs": [
        ("c3_s01_certificate_matrix", 4)],
    "crates/quervant-core/src/search/unified.rs": [
        ("c3_u02_dispatch_and_count_matrix", 4),
        ("c3_u04_corruption_precedence", 4),
        ("c3_u05_native_later_segment_boundary", 4),
        ("c3_u09_logical_budget_edges", 4)],
    "crates/quervant-core/tests/perf06_c2_physical.rs": [
        ("collect_pages", 0), ("c3_i02_real_pit_update_merge_and_paging", 0)],
}
APPEND = {
    "docs/pr-artifacts/perf-06-c/PERF06C3_EXECUTION_REPORT.md",
    "docs/PERF_OPTIMIZATION_ROADMAP.md",
    "docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md",
    "docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md",
}
NEW_DOCS = {
    "docs/pr-artifacts/perf-06-c/PERF06C3F1_DETAILED_FIXUP_PLAN.md",
    "docs/pr-artifacts/perf-06-c/PERF06C3F1_EXECUTION_REPORT.md",
}
EVIDENCE = "docs/pr-artifacts/perf-06-c/evidence/c3-f1/"


def require(ok, detail):
    if not ok:
        raise ValueError(detail)


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.STDOUT)


def blob(ref, path):
    if ref == "WORKTREE":
        return Path(path).read_bytes()
    return git("show", f"{ref}:{path}")


def changed(base, current):
    args = ["diff", "--name-only", "-z", base]
    if current != "WORKTREE":
        args.append(current)
    args.append("--")
    return [p.decode("utf-8") for p in git(*args).split(b"\0") if p]


def mask(data, declarations):
    lines = data.splitlines(keepends=True)
    spans = []
    for name, indent in declarations:
        pattern = re.compile(rb"^" + b" " * indent + rb"fn " +
                             re.escape(name.encode()) + rb"[(<]")
        positions = [i for i, line in enumerate(lines) if pattern.match(line)]
        require(len(positions) == 1, f"ambiguous/missing function {name}")
        start = positions[0]
        end = next((i + 1 for i in range(start + 1, len(lines))
                    if lines[i].rstrip(b"\r\n") == b" " * indent + b"}"), None)
        require(end is not None, f"missing function terminator {name}")
        spans.append((start, end, name))
    spans.sort()
    require(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])),
            "overlapping function regions")
    for start, end, name in reversed(spans):
        lines[start:end] = [f"<C3-F1:{name}>\n".encode()]
    return b"".join(lines)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect(current, tested):
    paths = changed(START, current)
    require(set(FUNCTIONS) <= set(paths), "all three prescribed test files must change")
    source_rows = []
    for path, declarations in FUNCTIONS.items():
        before, after = blob(START, path), blob(current, path)
        a, b = mask(before, declarations), mask(after, declarations)
        require(a == b, f"protected bytes changed in {path}")
        source_rows.append(dict(path=path, before_sha256=digest(before),
                                after_sha256=digest(after), protected_sha256=digest(a),
                                authorized_functions=[n for n, _ in declarations]))
    for path in paths:
        if path in FUNCTIONS:
            continue
        if path in APPEND:
            require(blob(current, path).startswith(blob(START, path)),
                    f"historical document was rewritten: {path}")
            continue
        if path in NEW_DOCS or path.startswith(EVIDENCE):
            require(git("ls-tree", START, "--", path) == b"",
                    f"new-artifact path existed at START: {path}")
            continue
        raise ValueError(f"path outside F1 allowlist: {path}")
    post_test_paths = None
    if tested:
        require(re.fullmatch(r"[0-9a-f]{40}", tested), "tested must be immutable SHA")
        post_test_paths = changed(tested, current)
        require(all(p.startswith("docs/") for p in post_test_paths),
                "non-document change after F1_TESTED")
        for path in FUNCTIONS:
            require(blob(tested, path) == blob(current, path),
                    f"test source changed after F1_TESTED: {path}")
    return dict(status="PASS", start=START, current=current, tested=tested,
                changed_paths=paths, source_regions=source_rows,
                post_test_paths=post_test_paths,
                normal_build_source_equal=True,
                unapproved_test_bytes_equal=True,
                tested_to_final_docs_only=bool(tested))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("current")
    parser.add_argument("output")
    parser.add_argument("--tested")
    args = parser.parse_args()
    require(args.current == "WORKTREE" or
            re.fullmatch(r"[0-9a-f]{40}", args.current), "current must be SHA or WORKTREE")
    output = Path(args.output).resolve()
    repo = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
    require(repo not in output.parents, "write audit output outside checkout")
    require(not output.exists(), "audit output must be new")
    try:
        result = inspect(args.current, args.tested)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        result = dict(status="FAIL", detail=str(error))
    result["checker_sha256"] = digest(Path(__file__).read_bytes())
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
