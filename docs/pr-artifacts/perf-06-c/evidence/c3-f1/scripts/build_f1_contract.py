#!/usr/bin/env python3
"""Build the author-frozen F1 receipt contract; never execute its commands."""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

START = "ee77917d303b060b0d38ab88e5d9ae73625f6676"
OLD = "docs/pr-artifacts/perf-06-c/evidence/c3/"
MANIFEST_SHA = "2f7478a2dc72fe955a8d245bade407b28194429aad33709166573bcc45b264ac"
ARGV = {
    'fin_s01': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::score::tests::c3_s01_certificate_matrix', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_u02': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c3_u02_dispatch_and_count_matrix', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_u04': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c3_u04_corruption_precedence', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_u05': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c3_u05_native_later_segment_boundary', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_u09': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c3_u09_logical_budget_edges', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_i02': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_c2_physical', 'c3_i02_real_pit_update_merge_and_paging', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_list_c2u': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c2_u', '--', '--list', '--format', 'terse'],
    'fin_list_c2p': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::execute::c2_physical_tests::c2_p', '--', '--list', '--format', 'terse'],
    'fin_list_c2_broad': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'c2_', '--', '--list', '--format', 'terse'],
    'fin_list_c3': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'c3_', '--', '--list', '--format', 'terse'],
    'fin_list_integration': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_c2_physical', '--', '--list', '--format', 'terse'],
    'fin_suite_b1_int': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_b1_ordinals'],
    'fin_suite_b1_lib': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'b1_'],
    'fin_suite_b2_int': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_b2_ordinals'],
    'fin_suite_b2_lib': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'b2_'],
    'fin_suite_b3_int': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_b3_keys'],
    'fin_suite_b3_lib': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'b3_'],
    'fin_suite_c2p_t1': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::execute::c2_physical_tests::c2_p', '--', '--test-threads=1'],
    'fin_suite_c2p_t8': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::execute::c2_physical_tests::c2_p', '--', '--test-threads=8'],
    'fin_suite_c2u_t1': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c2_u', '--', '--test-threads=1'],
    'fin_suite_c2u_t8': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c2_u', '--', '--test-threads=8'],
    'fin_suite_c3_msrv_af': ['cargo', '+1.85.0', 'test', '-p', 'quervant-core', '--lib', '--all-features', 'c3_', '--', '--test-threads=8'],
    'fin_suite_c3_t1': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'c3_', '--', '--test-threads=1'],
    'fin_suite_c3_t8': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'c3_', '--', '--test-threads=8'],
    'fin_suite_integration': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_c2_physical', '--', '--test-threads=1'],
    'fin_suite_pr15h_a': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'pr15h_a_candidate_materialization'],
    'fin_suite_pr15h_a2': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'pr15h_a2_dispatch'],
    'fin_suite_reader': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'segment::reader::stored_blocks_reader_tests::', '--', '--test-threads=8'],
    'fin_suite_score': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::score::tests::', '--', '--test-threads=1'],
    'qa_bench_norun': ['cargo', '+1.98.1', 'bench', '--workspace', '--no-run'],
    'qa_bench_scripts': ['bash', 'benchmarks/scripts/test-scripts.sh'],
    'qa_clippy_185': ['cargo', '+1.85.0', 'clippy', '--workspace', '--all-targets', '--', '-D', 'warnings'],
    'qa_clippy_185_af': ['cargo', '+1.85.0', 'clippy', '--workspace', '--all-targets', '--all-features', '--', '-D', 'warnings'],
    'qa_clippy_198': ['cargo', '+1.98.1', 'clippy', '--workspace', '--all-targets', '--', '-D', 'warnings'],
    'qa_clippy_198_af': ['cargo', '+1.98.1', 'clippy', '--workspace', '--all-targets', '--all-features', '--', '-D', 'warnings'],
    'qa_cov_198': ['cargo', '+1.98.1', 'llvm-cov', '--workspace', '--all-targets', '--fail-under-lines', '85'],
    'qa_cov_198_af': ['cargo', '+1.98.1', 'llvm-cov', '--workspace', '--all-targets', '--all-features', '--fail-under-lines', '85'],
    'qa_doc_198': ['cargo', '+1.98.1', 'doc', '--workspace', '--no-deps'],
    'qa_doc_198_af': ['cargo', '+1.98.1', 'doc', '--workspace', '--all-features', '--no-deps'],
    'qa_fmt_185': ['cargo', '+1.85.0', 'fmt', '--all', '--', '--check'],
    'qa_fmt_198': ['cargo', '+1.98.1', 'fmt', '--all', '--', '--check'],
    'qa_test_185': ['cargo', '+1.85.0', 'test', '--workspace', '--all-targets'],
    'qa_test_185_af': ['cargo', '+1.85.0', 'test', '--workspace', '--all-targets', '--all-features'],
    'qa_test_198': ['cargo', '+1.98.1', 'test', '--workspace', '--all-targets'],
    'qa_test_198_af': ['cargo', '+1.98.1', 'test', '--workspace', '--all-targets', '--all-features'],
}
FOCUSED = ['fin_s01', 'fin_u02', 'fin_u04', 'fin_u05', 'fin_u09', 'fin_i02']
INVENTORIES = {'fin_list_c2u': 24, 'fin_list_c2p': 5, 'fin_list_c2_broad': 52, 'fin_list_c3': 26, 'fin_list_integration': 12}
COUNTS = {'fin_suite_b1_lib': 65, 'fin_suite_b2_lib': 31, 'fin_suite_b2_int': 8, 'fin_suite_b3_lib': 32, 'fin_suite_b3_int': 8, 'fin_suite_c2p_t1': 5, 'fin_suite_c2p_t8': 5, 'fin_suite_c2u_t1': 24, 'fin_suite_c2u_t8': 24, 'fin_suite_c3_msrv_af': 26, 'fin_suite_c3_t1': 26, 'fin_suite_c3_t8': 26, 'fin_suite_integration': 12, 'fin_suite_pr15h_a': 6, 'fin_suite_pr15h_a2': 8, 'fin_suite_reader': 9, 'fin_suite_score': 19}
MARKERS = {'fin_s01': 'C3 F1 S01 rows=24 isolated-df-rows=2', 'fin_u02': 'C3 F1 U02 matrix-rows=25 certified=5 legacy=20 split-c3=10 ineligible-result-rows=6', 'fin_u04': 'C3 F1 U04 rows=9 isolated-C29=true unarmed-synthetic-snapshot=C3', 'fin_u05': 'C3 F1 U05 rows=4 recoveries=4 literal-reference-errors=3', 'fin_u09': 'C3 F1 U09 rows=12 failed-rows=7 recoveries=7 fixed-projection-failure=13056/13160/100', 'fin_i02': 'C3 F1 I02 phases=5 checked-hits=198 old-pages=14 new-pages=13'}
BENCH_SMOKE = {'benches/bm25.rs': 1, 'benches/dictionary.rs': 6, 'benches/geo.rs': 2, 'benches/merge.rs': 3, 'benches/phrase.rs': 6, 'benches/postings.rs': 3, 'benches/search.rs': 18, 'benches/typed_analytics.rs': 3, 'benches/unified_diagnostics.rs': 30, 'benches/writer_mutation.rs': 2}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_git(path):
    return subprocess.check_output(["git", "show", f"{START}:{path}"], stderr=subprocess.STDOUT)


def expected(passed, ignored=0):
    return dict(passed=passed, failed=0, ignored=ignored)


def make(mode):
    require(mode == "BASELINE" or re.fullmatch(r"[0-9a-f]{40}", mode), "mode must be BASELINE or F1_TESTED SHA")
    raw = read_git(OLD + "manifest.json")
    require(hashlib.sha256(raw).hexdigest() == MANIFEST_SHA, "original manifest mismatch")
    manifest = json.loads(raw)
    old_rows = {row["label"]: row for row in manifest["receipts"]}
    original = {}
    for label, argv in ARGV.items():
        row = old_rows[label]
        path = OLD + "receipts/" + label + ".json"
        require(row["path"] == path and row["argv"] == argv and row["classification"] == "PASS", "original command contract mismatch")
        receipt = json.loads(read_git(path))
        out = base64.b64decode(receipt["combined_output_base64"], validate=True)
        require(receipt["argv"] == argv and receipt["command_exit_code"] == 0, "original command/exit mismatch")
        require(hashlib.sha256(out).hexdigest() == receipt["combined_output_sha256"] == row["output_sha256"], "original raw hash mismatch")
        require(len(out) == receipt["combined_output_size"] == row["output_size"], "original raw size mismatch")
        original[label] = out.decode("utf-8")
    rows = []
    for label in FOCUSED:
        name = ARGV[label][ARGV[label].index("--") - 1]
        new_label = "base_" + label.removeprefix("fin_")
        rows.append(dict(path="baseline/" + new_label + ".json", label=new_label,
                         argv=ARGV[label], commit=START, classification="BASELINE",
                         check=dict(kind="exact", name=name, expected=expected(1))))
    if mode == "BASELINE":
        require(len(rows) == 6, "baseline cardinality")
        return dict(schema="quervant-perf06-c3-f1-receipt-contract-v1", receipts=rows)
    for label, argv in ARGV.items():
        if label in FOCUSED:
            check = dict(kind="exact", name=argv[argv.index("--") - 1], expected=expected(1), required_text=[MARKERS[label]])
        elif label in INVENTORIES:
            names = sorted(re.findall(r"^([^\r\n]+): test$", original[label], re.M))
            require(len(names) == len(set(names)) == INVENTORIES[label], "original inventory cardinality")
            check = dict(kind="inventory", names=names)
        elif label in COUNTS:
            check = dict(kind="summary", expected=expected(COUNTS[label]))
        elif label == "fin_suite_b1_int":
            check = dict(kind="workspace", targets=1, expected=expected(9, 2), bench_smoke={})
        elif label.startswith("qa_test_"):
            af = label.endswith("_af")
            check = dict(kind="workspace", targets=146,
                         expected=expected(2794 if af else 2749, 100 if af else 16),
                         bench_smoke=BENCH_SMOKE)
        elif label.startswith("qa_cov_"):
            check = dict(kind="coverage")
        elif label.startswith("qa_fmt_"):
            check = dict(kind="plain", empty=True)
        elif label == "qa_bench_scripts":
            check = dict(kind="plain", required_text=["script tests: 108 passed, 0 failed"])
        else:
            require(label.startswith(("qa_clippy_", "qa_doc_")) or label == "qa_bench_norun", "unknown command class")
            check = dict(kind="plain")
        new_label = "f1_" + label
        rows.append(dict(path="final/" + new_label + ".json", label=new_label,
                         argv=argv, commit=mode, classification="PASS", check=check))
    require(len(rows) == 51, "final cardinality")
    return dict(schema="quervant-perf06-c3-f1-receipt-contract-v1", receipts=rows)


if __name__ == "__main__":
    require(len(sys.argv) == 3, "usage: BASELINE_OR_F1_TESTED_SHA NEW_OUTPUT.json")
    result = make(sys.argv[1])
    output = Path(sys.argv[2]).resolve()
    require(not output.exists(), "contract output must be new")
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(dict(receipts=len(result["receipts"]), output=str(output)), sort_keys=True))
