#!/usr/bin/env python3
"""Validate a `quervant-bench-v1` benchmark report manifest.

Exits 0 and prints `VALID: ...` on success; exits 1 with `INVALID: <reason>` on
any missing, contradictory or malformed field. Standard library only.
"""
import json
import sys

REQUIRED_TOP = [
    "schema",
    "run_id",
    "timestamp_utc",
    "git_sha",
    "dirty",
    "toolchain",
    "os_kernel",
    "wsl2",
    "cpu_model",
    "filesystem_type",
    "fixture_version",
    "seed",
    "criterion_version",
    "correctness_passed",
    "profiler_status",
    "results",
]

REQUIRED_RESULT = [
    "workload_id",
    "doc_count",
    "segments",
    "query_type",
    "selectivity",
    "actual_hits",
    "top_k",
    "estimate_ns",
    "ci_lower_ns",
    "ci_upper_ns",
    "sample_count",
    "status",
]


def invalid(reason):
    print(f"INVALID: {reason}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        invalid("usage: validate-report.py <manifest.json>")
    try:
        with open(sys.argv[1], encoding="utf-8") as handle:
            doc = json.load(handle)
    except Exception as error:  # noqa: BLE001 - report any parse failure
        invalid(f"not valid JSON: {error}")

    if doc.get("schema") != "quervant-bench-v1":
        invalid("schema must be quervant-bench-v1")
    for key in REQUIRED_TOP:
        if key not in doc:
            invalid(f"missing top-level field {key}")
    if doc["correctness_passed"] is not True:
        invalid("correctness_passed must be true")
    if doc["dirty"] is True and doc.get("status", "publishable") == "publishable":
        invalid("dirty runs cannot be published as clean baselines")
    digest = doc.get("dataset_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        invalid("dataset_sha256 must be a 64-character hex digest")
    try:
        int(digest, 16)
    except ValueError:
        invalid("dataset_sha256 must be hexadecimal")

    results = doc.get("results")
    if not isinstance(results, list) or not results:
        invalid("results must be a non-empty list")
    for index, result in enumerate(results):
        for key in REQUIRED_RESULT:
            if key not in result:
                invalid(f"results[{index}] missing {key}")
        if not isinstance(result["estimate_ns"], (int, float)) or result["estimate_ns"] <= 0:
            invalid(f"results[{index}].estimate_ns must be positive")
        if result["ci_lower_ns"] > result["estimate_ns"]:
            invalid(f"results[{index}].ci_lower_ns must not exceed the estimate")
        if result["ci_upper_ns"] < result["estimate_ns"]:
            invalid(f"results[{index}].ci_upper_ns must not be below the estimate")
        if result["doc_count"] < 0 or result["segments"] < 0 or result["actual_hits"] < 0:
            invalid(f"results[{index}] contains negative numeric data")
    print(f"VALID: {len(results)} results")


if __name__ == "__main__":
    main()
