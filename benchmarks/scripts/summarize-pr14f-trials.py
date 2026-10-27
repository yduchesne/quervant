#!/usr/bin/env python3
"""Read-only Markdown summary of three qualified `pr14_p4_v1` trial CSVs.

Percentiles use the runner convention: sort the samples, then take index
``round((n - 1) * p)`` with half-away-from-zero rounding (Rust ``f64::round``),
clamped to the last sample. Cold/warm and local/remote lanes are never pooled.
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

PAIRS = [
    ("local-cold", "W09"),
    ("local-warm", "W02"),
    ("local-warm", "W03"),
    ("local-warm", "W04"),
    ("local-warm", "W05"),
    ("local-warm", "W06"),
    ("local-warm", "W07"),
    ("remote-cold", "W01"),
    ("remote-warm", "W02"),
    ("remote-warm", "W03"),
    ("remote-warm", "W04"),
    ("remote-warm", "W05"),
    ("remote-warm", "W06"),
    ("remote-warm", "W07"),
]


def percentile(sorted_values, pct):
    if not sorted_values:
        raise ValueError("no samples")
    rank = math.floor((len(sorted_values) - 1) * pct + 0.5)
    return sorted_values[min(rank, len(sorted_values) - 1)]


def median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def ms(micros):
    return f"{micros / 1000.0:.3f}"


def load(report_path, root):
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    raw = Path(report["raw_csv"])
    if not raw.is_absolute():
        raw = root / raw
    samples = {}
    with open(raw, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pair = (row["lane"], row["workload"])
            samples.setdefault(pair, []).append(float(row["micros"]))
    for pair in PAIRS:
        values = samples.get(pair)
        if values is None:
            raise SystemExit(f"{report_path}: missing {pair[0]}/{pair[1]}")
        if len(values) != report["samples"]:
            raise SystemExit(f"{report_path}: {pair[0]}/{pair[1]} has {len(values)} samples")
    return {"trial": report["trial"], "sha": report["sha"], "samples": samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs=3, help="three sanitized trial JSON reports")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent.parent
    trials = [load(path, root) for path in args.reports]
    if len({trial["trial"] for trial in trials}) != 3:
        raise SystemExit("trial ids are not distinct")
    if len({trial["sha"] for trial in trials}) != 1:
        raise SystemExit("source SHAs are not identical")

    print("### Per-trial lane percentiles (milliseconds)\n")
    print("| Lane | Workload | Trial | n | p50 | p95 | p99 |")
    print("|---|---|---|---:|---:|---:|---:|")
    per_pair = {pair: [] for pair in PAIRS}
    for trial in trials:
        for pair in PAIRS:
            values = sorted(trial["samples"][pair])
            p50 = percentile(values, 0.50)
            p95 = percentile(values, 0.95)
            p99 = percentile(values, 0.99)
            per_pair[pair].append((p50, p95, p99))
            print(
                f"| {pair[0]} | {pair[1]} | {trial['trial']} | {len(values)} | "
                f"{ms(p50)} | {ms(p95)} | {ms(p99)} |"
            )

    print("\n### Median-of-trial percentiles and observed range (milliseconds)\n")
    print("| Lane | Workload | Trials | Median p50 | Median p95 | Median p99 | p50 range | p95 range | p99 range |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for pair in PAIRS:
        values = per_pair[pair]
        medians = [median([value[index] for value in values]) for index in range(3)]
        ranges = [
            (min(value[index] for value in values), max(value[index] for value in values))
            for index in range(3)
        ]
        print(
            f"| {pair[0]} | {pair[1]} | {len(values)} | "
            f"{ms(medians[0])} | {ms(medians[1])} | {ms(medians[2])} | "
            f"{ms(ranges[0][0])}–{ms(ranges[0][1])} | "
            f"{ms(ranges[1][0])}–{ms(ranges[1][1])} | "
            f"{ms(ranges[2][0])}–{ms(ranges[2][1])} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
