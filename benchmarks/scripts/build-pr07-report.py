#!/usr/bin/env python3
"""Assemble a ``quervant-bench-v2`` report from real Criterion artifacts.

Reads ``<criterion-dir>/<group>[/<function>]/<param>/new/{estimates.json,sample.json}``
plus the independent fixture metadata, the runner environment file and the
per-check contention JSON records. Joins on ``workload_key`` and fails closed on
any missing, duplicate or extra workload. Writes atomically (temp file +
``os.replace``); never fabricates estimates or sample counts.
"""
import argparse
import json
import os
import sys


def fail(reason):
    print(f"BUILD FAILED: {reason}", file=sys.stderr)
    sys.exit(1)


def reject_constant(value):
    raise ValueError(f"non-finite JSON constant {value}")


def load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle, parse_constant=reject_constant)
    except Exception as error:  # noqa: BLE001
        fail(f"cannot read {path}: {error}")


def load_env(path):
    env = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key] = value
    return env


def estimate_for(estimates):
    for name in ("slope", "median", "mean"):
        entry = estimates.get(name)
        if not isinstance(entry, dict):
            continue  # e.g. Criterion writes "slope": null for flat/very fast benches
        interval = entry.get("confidence_interval")
        if not isinstance(interval, dict):
            continue
        return (
            float(entry["point_estimate"]),
            float(interval["lower_bound"]),
            float(interval["upper_bound"]),
            name,
        )
    fail("estimates.json has no usable slope/median/mean estimate")
    return (0.0, 0.0, 0.0, "")  # unreachable


def collect_estimates(criterion_dir):
    found = {}
    for root, _dirs, files in os.walk(criterion_dir):
        if "estimates.json" not in files or os.path.basename(root) != "new":
            continue
        relative = os.path.relpath(root, criterion_dir)
        if not relative.endswith(os.sep + "new"):
            continue
        key = os.path.dirname(relative).replace(os.sep, "/")
        if not key:
            continue
        if key in found:
            fail(f"ambiguous Criterion estimate for {key}")
        est = load_json(os.path.join(root, "estimates.json"))
        sample_path = os.path.join(root, "sample.json")
        if not os.path.exists(sample_path):
            fail(f"missing sample.json for {key}")
        sample = load_json(sample_path)
        sample_count = len(sample.get("iters", []))
        if sample_count <= 0:
            fail(f"non-positive sample count for {key}")
        value, lower, upper, source = estimate_for(est)
        found[key] = {
            "estimate_ns": value,
            "ci_lower_ns": lower,
            "ci_upper_ns": upper,
            "sample_count": sample_count,
            "estimate_source": source,
        }
    return found


def load_checks(paths):
    checks = []
    for path in paths:
        record = load_json(path)
        checks.append(
            {
                "name": os.path.basename(path),
                "state": record.get("state"),
                "reason_codes": record.get("reason_codes", []),
                "cpu_busy_fraction": record.get("cpu_busy_fraction"),
                "competing_process_count": record.get("competing_process_count", 0),
                "timestamp_utc": record.get("timestamp_utc"),
            }
        )
    return checks


def throughput_unit(operation):
    return {
        "search": "searches",
        "phrase": "phrase-queries",
        "dictionary": "lookups",
        "postings": "postings",
        "bm25-control": "bm25-evaluations",
    }.get(operation, "operations")


def main():
    parser = argparse.ArgumentParser(description="Assemble a quervant-bench-v2 report.")
    parser.add_argument("--criterion-dir", required=True)
    parser.add_argument("--fixture-metadata", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--environment-state", required=True)
    parser.add_argument("--profiler-status", default="UNAVAILABLE")
    parser.add_argument("--operator-idle-confirmed", action="store_true")
    parser.add_argument("--correctness-passed", action="store_true")
    parser.add_argument("--check", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    fixture = load_json(args.fixture_metadata)
    env = load_env(args.env_file)
    metadata = {record["workload_key"]: record for record in fixture["records"]}
    estimates = collect_estimates(args.criterion_dir)

    missing = set(metadata) - set(estimates)
    if missing:
        fail(f"missing Criterion estimates for {len(missing)} workloads: {sorted(missing)[:3]}")
    extra = set(estimates) - set(metadata)
    if extra:
        fail(f"Criterion produced {len(extra)} unexpected workloads: {sorted(extra)[:3]}")

    results = []
    digests_by_size = {}
    for key, record in metadata.items():
        est = estimates[key]
        results.append(
            {
                "workload_key": key,
                "query_id": record["query_id"],
                "operation": record["operation"],
                "doc_count": record["doc_count"],
                "segments": record["segments"],
                "top_k": record["top_k"],
                "actual_hits": record["actual_hits"],
                "selectivity_ratio": record["selectivity_ratio"],
                "hit_count_applicable": record["hit_count_applicable"],
                "dataset_sha256": record["dataset_sha256"],
                "fixture_version": record["fixture_version"],
                "posting_doc_count": record.get("posting_doc_count"),
                "dictionary_doc_freq": record.get("dictionary_doc_freq"),
                "estimate_ns": est["estimate_ns"],
                "ci_lower_ns": est["ci_lower_ns"],
                "ci_upper_ns": est["ci_upper_ns"],
                "estimate_source": est["estimate_source"],
                "sample_count": est["sample_count"],
                "throughput_unit": throughput_unit(record["operation"]),
                "status": "measured",
            }
        )
        if record["doc_count"] > 0:
            digests_by_size[f"{record['doc_count']}-{record['segments']}seg"] = record["dataset_sha256"]

    dirty = env.get("git_dirty") == "true"
    report = {
        "schema": "quervant-bench-v2",
        "run_id": args.run_id,
        "timestamp_utc": env.get("timestamp_utc", ""),
        "git_sha": env.get("git_sha", ""),
        "dirty": dirty,
        "toolchain": env.get("rustc", ""),
        "os_kernel": env.get("uname", ""),
        "wsl2": env.get("wsl2") == "true",
        "cpu_model": env.get("cpu_model", ""),
        "filesystem_type": env.get("filesystem", ""),
        "fixture_version": fixture.get("fixture_version"),
        "seed": fixture.get("seed"),
        "dataset_sha256": digests_by_size.get("2000-4seg"),
        "dataset_sha256_by_size": digests_by_size,
        "criterion_version": env.get("criterion_version", ""),
        "correctness_passed": bool(args.correctness_passed),
        "profiler_status": args.profiler_status,
        "environment_qualification": {
            "state": args.environment_state,
            "operator_idle_confirmed": bool(args.operator_idle_confirmed),
            "git_dirty": dirty,
            "check_results": load_checks(args.check),
            "reason_codes": [],
        },
        "results": results,
    }
    if report["dataset_sha256"] is None:
        report.pop("dataset_sha256", None)

    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, args.out)
    print(f"WROTE: {args.out} ({len(results)} results, env {args.environment_state})")


if __name__ == "__main__":
    main()
