#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import re
import sys

PIN = "1107c78e330559d8631882fc815a2d78dd0cc901e8517fcb32487c4663e545c4"
F1_START = "ee77917d303b060b0d38ab88e5d9ae73625f6676"
F1_TESTED = "8f82f8290f838547dfc7d490f44ba8c0c8798d24"
SCHEMA = "quervant-perf06-c3-f1-receipt-contract-v1"
MARKER = "C3 F2 U02 plain-batch aggregation=none normal+legacy"
LABELS = set("""
fin_s01 fin_u02 fin_u04 fin_u05 fin_u09 fin_i02
fin_list_c2u fin_list_c2p fin_list_c2_broad fin_list_c3 fin_list_integration
fin_suite_c3_t1 fin_suite_c3_t8 fin_suite_c3_msrv_af
fin_suite_c2u_t1 fin_suite_c2u_t8 fin_suite_c2p_t1 fin_suite_c2p_t8
fin_suite_integration fin_suite_score fin_suite_reader
fin_suite_b1_lib fin_suite_b2_lib fin_suite_b3_lib
fin_suite_b1_int fin_suite_b2_int fin_suite_b3_int
fin_suite_pr15h_a fin_suite_pr15h_a2
qa_fmt_198 qa_fmt_185 qa_clippy_198 qa_clippy_198_af qa_clippy_185 qa_clippy_185_af
qa_test_198 qa_test_198_af qa_test_185 qa_test_185_af
qa_cov_198 qa_cov_198_af qa_doc_198 qa_doc_198_af qa_bench_norun qa_bench_scripts
""".split())
BASE_LABELS = {"base_s01", "base_u02", "base_u04", "base_u05", "base_u09", "base_i02"}


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(old_bytes, tested):
    require(sha(old_bytes) == PIN, "F1 command contract hash mismatch")
    require(re.fullmatch(r"[0-9a-f]{40}", tested) is not None, "bad F2_TESTED SHA")
    require(tested not in (F1_START, F1_TESTED), "historical revision cannot be F2_TESTED")
    require(len(LABELS) == 45, "bad embedded final label count")
    old = json.loads(old_bytes)
    require(set(old) == {"schema", "receipts"} and old["schema"] == SCHEMA,
            "unexpected F1 contract schema")
    require(len(old["receipts"]) == 51, "wrong F1 total row count")
    baseline, final = [], []
    for row in old["receipts"]:
        require(set(row) == {"path", "label", "argv", "commit", "classification", "check"},
                "unexpected row fields")
        label = row["label"]
        if row["classification"] == "BASELINE":
            require(label in BASE_LABELS and row["path"] == f"baseline/{label}.json"
                    and row["commit"] == F1_START, "bad historical baseline row")
            baseline.append(label)
            continue
        require(row["classification"] == "PASS" and row["commit"] == F1_TESTED,
                "bad historical final row")
        require(label.startswith("f1_") and row["path"] == f"final/{label}.json",
                "bad final label/path")
        require(label[3:] in LABELS, "unexpected final label")
        # The parsed row is newly allocated from the immutable input bytes.
        # Preserve every other field exactly as a JSON value.
        row["label"] = "f2_" + label[3:]
        row["path"] = f'final/{row["label"]}.json'
        row["commit"] = tested
        if label == "f1_fin_u02":
            required = row["check"]["required_text"]
            require(MARKER not in required, "F2 marker unexpectedly present in F1")
            required.append(MARKER)
        final.append(row)
    require(len(baseline) == 6 and set(baseline) == BASE_LABELS, "baseline inventory drift")
    require(len(final) == 45 and {r["label"][3:] for r in final} == LABELS,
            "final inventory drift")
    return {"schema": SCHEMA, "receipts": final}


def main():
    require(len(sys.argv) == 4, "usage: F1_CONTRACT F2_TESTED OUTPUT")
    src, tested, dst = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    require(not dst.exists(), "output exists")
    result = build(src.read_bytes(), tested)
    with dst.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": "PASS", "receipt_count": 45,
                      "sha256": sha(dst.read_bytes()), "tested": tested}, sort_keys=True))


if __name__ == "__main__":
    main()
