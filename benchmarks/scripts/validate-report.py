#!/usr/bin/env python3
"""Validate a Quervant benchmark report.

Modes
-----
``--historical``
    Accept a legacy ``quervant-bench-v1`` report **only** as historical,
    unqualified evidence. It must carry ``status == "historical_unqualified"``
    (or ``report_qualification``) and is never certified as a qualified baseline.

default (v2)
    Require ``quervant-bench-v2`` and ``--fixture-metadata PATH``. Every
    search/phrase row's semantic count is cross-checked against the independently
    generated fixture metadata. Missing/duplicate/extra workload rows, fabricated
    zero hit counts for positive-hit queries, unqualified numbers and false
    qualification all fail.

Standard library only. Exits 0 with ``VALID: ...`` or 1 with ``INVALID: ...``.
"""
import argparse
import json
import math
import sys

V1_REQUIRED_TOP = [
    "schema", "run_id", "timestamp_utc", "git_sha", "dirty", "toolchain",
    "os_kernel", "wsl2", "cpu_model", "filesystem_type", "fixture_version",
    "seed", "criterion_version", "correctness_passed", "profiler_status", "results",
]

V2_REQUIRED_TOP = [f for f in V1_REQUIRED_TOP if f != "dataset_sha256"] + [
    "environment_qualification",
]

REQUIRED_RESULT = [
    "workload_key", "query_id", "doc_count", "segments", "top_k",
    "actual_hits", "hit_count_applicable", "estimate_ns", "ci_lower_ns",
    "ci_upper_ns", "sample_count", "status",
]

QUALIFIED_STATES = {"qualified", "unqualified_contention", "unqualified_unknown", "diagnostic"}
CONTENTION_STATES = {"clear", "suspected", "unknown"}


def invalid(reason):
    print(f"INVALID: {reason}", file=sys.stderr)
    sys.exit(1)


def reject_constant(value):
    raise ValueError(f"non-finite JSON constant {value}")


def load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle, parse_constant=reject_constant)
    except Exception as error:  # noqa: BLE001
        invalid(f"cannot read {path}: {error}")


def require_fields(obj, fields, label):
    if not isinstance(obj, dict):
        invalid(f"{label} must be an object")
    for field in fields:
        if field not in obj:
            invalid(f"{label} missing field {field}")


def check_numeric(value, label, *, positive=False, nonnegative=False):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        invalid(f"{label} must be numeric")
    if math.isnan(value) or math.isinf(value):
        invalid(f"{label} must be finite")
    if positive and value <= 0:
        invalid(f"{label} must be positive")
    if nonnegative and value < 0:
        invalid(f"{label} must be nonnegative")


def validate_historical(doc):
    if doc.get("schema") != "quervant-bench-v1":
        invalid("historical validation requires schema quervant-bench-v1")
    if doc.get("status") not in ("historical_unqualified",) and doc.get("report_qualification") not in ("historical_unqualified",):
        invalid("historical report must be explicitly marked historical_unqualified")
    for field in V1_REQUIRED_TOP:
        if field not in doc:
            invalid(f"missing top-level field {field}")
    results = doc.get("results")
    if not isinstance(results, list) or not results:
        invalid("results must be a non-empty list")
    print(f"VALID: historical/unqualified, {len(results)} results (not a qualified baseline)")


def validate_v2(doc, fixture_path):
    if doc.get("schema") != "quervant-bench-v2":
        invalid("v2 validation requires schema quervant-bench-v2 (use --historical for v1)")
    for field in V2_REQUIRED_TOP:
        if field not in doc:
            invalid(f"missing top-level field {field}")
    if doc["correctness_passed"] is not True:
        invalid("correctness_passed must be true")
    digests = []
    if doc.get("dataset_sha256") is not None:
        digests.append(("dataset_sha256", doc["dataset_sha256"]))
    by_size = doc.get("dataset_sha256_by_size")
    if by_size is not None:
        if not isinstance(by_size, dict) or not by_size:
            invalid("dataset_sha256_by_size must be a non-empty object")
        for key, value in by_size.items():
            digests.append((f"dataset_sha256_by_size[{key}]", value))
    if not digests:
        invalid("report requires dataset_sha256 or dataset_sha256_by_size")
    for label, digest in digests:
        if not isinstance(digest, str) or len(digest) != 64:
            invalid(f"{label} must be a 64-character hex digest")
        try:
            int(digest, 16)
        except ValueError:
            invalid(f"{label} must be hexadecimal")

    fixture = load_json(fixture_path)
    if fixture.get("schema") != "quervant-fixture-metadata-v1":
        invalid("fixture metadata schema must be quervant-fixture-metadata-v1")
    fixture_records = fixture.get("records")
    if not isinstance(fixture_records, list) or not fixture_records:
        invalid("fixture metadata records must be a non-empty list")
    meta = {}
    for index, record in enumerate(fixture_records):
        key = record.get("workload_key")
        if not isinstance(key, str) or not key:
            invalid(f"fixture metadata record[{index}] missing workload_key")
        if key in meta:
            invalid(f"duplicate fixture workload_key {key}")
        meta[key] = record

    results = doc.get("results")
    if not isinstance(results, list) or not results:
        invalid("results must be a non-empty list")
    seen = {}
    for index, row in enumerate(results):
        label = f"results[{index}]"
        if not isinstance(row, dict):
            invalid(f"{label} must be an object")
        for field in REQUIRED_RESULT:
            if field not in row:
                invalid(f"{label} missing {field}")
        key = row["workload_key"]
        if not isinstance(key, str) or not key:
            invalid(f"{label}.workload_key must be a non-empty string")
        if key in seen:
            invalid(f"duplicate result workload_key {key}")
        seen[key] = row
        if key not in meta:
            invalid(f"{label} workload_key {key} not present in fixture metadata")
        expected = meta[key]

        for field in ("query_id", "doc_count", "segments", "top_k", "dataset_sha256", "fixture_version"):
            if row[field] != expected[field]:
                invalid(f"{label}.{field}={row[field]!r} does not match fixture metadata {expected[field]!r}")
        applicable = expected["hit_count_applicable"]
        if row["hit_count_applicable"] != applicable:
            invalid(f"{label}.hit_count_applicable does not match fixture metadata")

        check_numeric(row["estimate_ns"], f"{label}.estimate_ns", positive=True)
        check_numeric(row["ci_lower_ns"], f"{label}.ci_lower_ns", nonnegative=True)
        check_numeric(row["ci_upper_ns"], f"{label}.ci_upper_ns", nonnegative=True)
        if row["ci_lower_ns"] > row["estimate_ns"] or row["ci_upper_ns"] < row["estimate_ns"]:
            invalid(f"{label} CI must bracket estimate_ns")
        if not isinstance(row["sample_count"], int) or isinstance(row["sample_count"], bool) or row["sample_count"] <= 0:
            invalid(f"{label}.sample_count must be a positive integer")

        if applicable:
            hits = row["actual_hits"]
            if not isinstance(hits, int) or isinstance(hits, bool) or hits < 0:
                invalid(f"{label}.actual_hits must be a nonnegative integer")
            if hits != expected["actual_hits"]:
                invalid(
                    f"{label}.actual_hits={hits} does not match independent oracle "
                    f"{expected['actual_hits']} for {key}"
                )
            ratio = row.get("selectivity_ratio", expected.get("selectivity_ratio"))
            if ratio is None or row.get("selectivity_ratio") is None:
                invalid(f"{label}.selectivity_ratio is required for hit-count-applicable rows")
            expected_ratio = expected.get("selectivity_ratio")
            if expected_ratio is None or abs(ratio - expected_ratio) > 1e-12:
                invalid(f"{label}.selectivity_ratio does not match fixture metadata")
            if not (0.0 <= ratio <= 1.0):
                invalid(f"{label}.selectivity_ratio must be within [0, 1]")
        else:
            if row["actual_hits"] is not None:
                invalid(f"{label}.actual_hits must be null for non-query microbenchmarks")
            if row.get("selectivity_ratio") is not None:
                invalid(f"{label}.selectivity_ratio must be null for non-query microbenchmarks")

    missing = set(meta) - set(seen)
    if missing:
        invalid(f"report is missing {len(missing)} fixture workloads, e.g. {sorted(missing)[:3]}")

    qualification = doc["environment_qualification"]
    require_fields(qualification, ["state", "operator_idle_confirmed", "check_results", "git_dirty"], "environment_qualification")
    if qualification["state"] not in QUALIFIED_STATES:
        invalid(f"unknown environment qualification state {qualification['state']!r}")
    checks = qualification["check_results"]
    if not isinstance(checks, list) or not checks:
        invalid("environment_qualification.check_results must be a non-empty list")
    for check in checks:
        if check.get("state") not in CONTENTION_STATES:
            invalid(f"invalid contention state {check.get('state')!r}")
    if qualification["state"] == "qualified":
        if qualification["operator_idle_confirmed"] is not True:
            invalid("qualified report requires operator_idle_confirmed=true")
        if qualification["git_dirty"] is not False:
            invalid("qualified report requires a clean git tree")
        if any(check["state"] != "clear" for check in checks):
            invalid("qualified report requires every contention check to be clear")
    print(f"VALID: {len(results)} results, environment {qualification['state']}")


def main():
    parser = argparse.ArgumentParser(description="Validate a Quervant benchmark report.")
    parser.add_argument("--historical", action="store_true", help="accept a v1 report only as historical/unqualified")
    parser.add_argument("--fixture-metadata", help="fixture metadata JSON (required for v2)")
    parser.add_argument("report")
    args = parser.parse_args()

    doc = load_json(args.report)
    if args.historical:
        validate_historical(doc)
        return
    if doc.get("schema") == "quervant-bench-v1":
        invalid("v1 reports are legacy; pass --historical to accept them as unqualified")
    if not args.fixture_metadata:
        invalid("--fixture-metadata is required for v2 validation")
    validate_v2(doc, args.fixture_metadata)


if __name__ == "__main__":
    main()
