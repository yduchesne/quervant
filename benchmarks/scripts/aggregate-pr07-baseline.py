#!/usr/bin/env python3
"""Aggregate three or more independently qualified v2 trials.

Refuses to run unless every trial reports ``environment_qualification.state ==
"qualified"`` and shares the same fixture metadata. Produces a median/min/max
across trials per workload; the per-trial Criterion confidence intervals do not
constitute an across-trial confidence interval and are reported as raw values.
"""
import argparse
import json
import os
import statistics
import sys


def fail(reason):
    print(f"AGGREGATE FAILED: {reason}", file=sys.stderr)
    sys.exit(1)


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser(description="Aggregate qualified benchmark trials.")
    parser.add_argument("--fixture-metadata", required=True)
    parser.add_argument("--trial-report", action="append", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args()

    if len(args.trial_report) < 3:
        fail(f"need at least 3 qualified trials, got {len(args.trial_report)}")
    fixture = load(args.fixture_metadata)
    fixture_version = fixture.get("fixture_version")
    metadata = {record["workload_key"]: record for record in fixture["records"]}

    reports = [load(path) for path in args.trial_report]
    run_ids = []
    per_key = {}
    for report in reports:
        qualification = report.get("environment_qualification", {})
        if qualification.get("state") != "qualified":
            fail(f"trial {report.get('run_id')} is not qualified ({qualification.get('state')})")
        if report.get("fixture_version") != fixture_version:
            fail(f"trial {report.get('run_id')} fixture version mismatch")
        run_ids.append(report["run_id"])
        for row in report["results"]:
            key = row["workload_key"]
            if key not in metadata:
                fail(f"trial {report['run_id']} has unknown workload {key}")
            per_key.setdefault(key, []).append(row)

    results = []
    for key, record in metadata.items():
        rows = per_key.get(key)
        if rows is None or len(rows) != len(reports):
            fail(f"workload {key} missing from some trial")
        estimates = [row["estimate_ns"] for row in rows]
        results.append(
            {
                "workload_key": key,
                "query_id": record["query_id"],
                "operation": record["operation"],
                "doc_count": record["doc_count"],
                "segments": record["segments"],
                "top_k": record["top_k"],
                "actual_hits": record["actual_hits"],
                "hit_count_applicable": record["hit_count_applicable"],
                "dataset_sha256": record["dataset_sha256"],
                "estimate_ns_median": statistics.median(estimates),
                "estimate_ns_min": min(estimates),
                "estimate_ns_max": max(estimates),
                "trials": [
                    {
                        "run_id": report["run_id"],
                        "estimate_ns": row["estimate_ns"],
                        "ci_lower_ns": row["ci_lower_ns"],
                        "ci_upper_ns": row["ci_upper_ns"],
                        "sample_count": row["sample_count"],
                    }
                    for report, row in zip(reports, rows)
                ],
            }
        )

    qualified = {
        "schema": "quervant-bench-v2-qualified",
        "trials": run_ids,
        "trial_count": len(reports),
        "fixture_version": fixture_version,
        "dataset_sha256_by_size": reports[0].get("dataset_sha256_by_size"),
        "results": results,
        "note": "Median/min/max across trials; per-trial CIs are not an across-trial CI.",
    }
    with open(args.out_json, "w", encoding="utf-8") as handle:
        json.dump(qualified, handle, indent=2)
        handle.write("\n")

    with open(args.out_md, "w", encoding="utf-8") as handle:
        handle.write("# PR 7 Amendment 04 qualified baseline\n\n")
        handle.write(f"Trials ({len(reports)}): {', '.join(run_ids)}\n\n")
        handle.write("| workload | doc_count | median ns | min ns | max ns |\n")
        handle.write("|---|---:|---:|---:|---:|\n")
        for row in results:
            handle.write(
                f"| {row['workload_key']} | {row['doc_count']} | "
                f"{row['estimate_ns_median']:.1f} | {row['estimate_ns_min']:.1f} | "
                f"{row['estimate_ns_max']:.1f} |\n"
            )
    print(f"WROTE: {args.out_json} and {args.out_md}")


if __name__ == "__main__":
    main()
