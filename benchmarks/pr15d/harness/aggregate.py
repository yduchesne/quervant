#!/usr/bin/env python3
"""PR15D aggregation.

Aggregation is derived only from validated raw trial manifests. Every displayed
statistic is recomputed from the 20 raw `samples_ns` values and cross-checked
against the stored summary; a tampered cached aggregate cannot be re-derived.

No competitive performance threshold exists. Quervant being slower is reported
honestly. A lane whose three-trial dispersion exceeds 1.10, or whose trial
median ranges overlap, is marked INCONCLUSIVE; no significance claim is made.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run  # noqa: E402
import validate  # noqa: E402

DISPERSION_LIMIT = 1.10


class AggregateError(Exception):
    def __init__(self, status: str, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def _trial_manifests(run_dir: str) -> dict:
    return {
        engine: {
            trial: run.read_json(
                os.path.join(run_dir, "trials", f"trial-{trial}", f"{engine}.json")
            )
            for trial in range(1, run.REQUIRED_TRIALS + 1)
        }
        for engine in run.ENGINES
    }


def _lane_index(manifest: dict) -> dict:
    return {
        (lane["n"], lane["class"], lane["k"], lane["regime"]): lane
        for lane in manifest["lanes"]
    }


def _median_of_three(values: list) -> int:
    return run.summarize(values)["median"]


def _dispersion(values: list) -> float:
    return round(max(values) / min(values), 6)


def build_aggregate(run_dir: str) -> dict:
    validation = validate.validate_run(run_dir)
    if validation["status"] != "QUALIFIED":
        raise AggregateError(
            validation["status"],
            f"{len(validation['errors'])} errors, {len(validation['unqualified'])} unqualified",
        )
    run_record = run.read_json(os.path.join(run_dir, "run.json"))
    manifests = _trial_manifests(run_dir)
    indexed = {
        engine: {trial: _lane_index(m) for trial, m in trials.items()}
        for engine, trials in manifests.items()
    }

    lanes = []
    for descriptor in run.lane_descriptors():
        key = run.lane_key(descriptor)
        per_engine = {}
        for engine in run.ENGINES:
            trials = indexed[engine]
            trial_medians = [trials[trial][key]["summary_ns"]["median"] for trial in sorted(trials)]
            per_engine[engine] = {
                "trial_medians_ns": trial_medians,
                "median_ns": _median_of_three(trial_medians),
                "dispersion_max_over_min": _dispersion(trial_medians),
                "trial_p95_ns": [
                    trials[trial][key]["summary_ns"]["p95"] for trial in sorted(trials)
                ],
                "trial_p99_ns": [
                    trials[trial][key]["summary_ns"]["p99"] for trial in sorted(trials)
                ],
            }

        base = per_engine["quervant"]
        comparisons = {}
        for engine in run.ENGINES:
            if engine == "quervant":
                continue
            other = per_engine[engine]
            base_range = [min(base["trial_medians_ns"]), max(base["trial_medians_ns"])]
            other_range = [min(other["trial_medians_ns"]), max(other["trial_medians_ns"])]
            overlap = not (
                base_range[1] < other_range[0] or other_range[1] < base_range[0]
            )
            inconclusive = (
                base["dispersion_max_over_min"] > DISPERSION_LIMIT
                or other["dispersion_max_over_min"] > DISPERSION_LIMIT
                or overlap
            )
            comparisons[engine] = {
                "engine_over_quervant_ratio": round(
                    other["median_ns"] / base["median_ns"], 6
                ),
                "quervant_over_engine_speedup": round(
                    base["median_ns"] / other["median_ns"], 6
                ),
                "trial_median_range_overlap": overlap,
                "inconclusive": inconclusive,
                "note": (
                    "INCONCLUSIVE: dispersion > 1.10 or overlapping trial medians"
                    if inconclusive
                    else "ratio reported without a significance claim"
                ),
            }

        lanes.append(
            {
                "id": descriptor["id"],
                "n": descriptor["n"],
                "class": descriptor["class"],
                "k": descriptor["k"],
                "regime": descriptor["regime"],
                "field": descriptor["field"],
                "term": descriptor["term"],
                "engines": per_engine,
                "comparisons": comparisons,
            }
        )

    indexing = {}
    for engine in run.ENGINES:
        indexing[engine] = {}
        for n in run.N_VALUES:
            entries = [manifests[engine][trial]["build"][str(n)] for trial in sorted(manifests[engine])]
            metrics = {}
            for field in ("index_ns", "commit_ns", "reopen_ns", "index_bytes", "segment_count"):
                values = [entry[field] for entry in entries]
                metrics[field] = {
                    "trial_values": values,
                    "median": _median_of_three(values),
                    "min": min(values),
                    "max": max(values),
                    "dispersion_max_over_min": _dispersion(values),
                }
            indexing[engine][str(n)] = metrics

    throughput = {}
    for engine in run.ENGINES:
        throughput[engine] = {}
        for n in run.N_VALUES:
            rates = [
                next(
                    entry["serial_ops_per_second"]
                    for entry in manifests[engine][trial]["throughput"]
                    if entry["n"] == n
                )
                for trial in sorted(manifests[engine])
            ]
            throughput[engine][str(n)] = {
                "trial_serial_ops_per_second": rates,
                "median_serial_ops_per_second": _median_of_three(rates)
                if all(isinstance(rate, int) for rate in rates)
                else round(sorted(rates)[1], 6),
                "dispersion_max_over_min": _dispersion(rates),
                "label": "serial_ops_per_second",
            }

    scored = run_record.get(
        "scored_lane",
        {
            "status": "SEMANTICALLY_NONCOMPARABLE",
            "reason": "no scored lane was measured",
        },
    )
    scored_ratios = []
    if scored.get("status") == "QUALIFIED" and scored.get("semantic_proof"):
        scored_ratios = []  # never mixed into exact-term results; separate approval required

    return {
        "schema": run.SCHEMA_AGGREGATE,
        "workload": run.WORKLOAD,
        "run_id": run_record.get("run_id"),
        "source_sha": run_record.get("source_sha"),
        "host_fingerprint": run_record.get("host_fingerprint"),
        "filesystem": run_record.get("filesystem"),
        "corpus_digests": run_record.get("corpus_digests"),
        "trials": run.REQUIRED_TRIALS,
        "samples_per_lane": run.MEASURED,
        "dispersion_limit": DISPERSION_LIMIT,
        "status": validation["status"],
        "performance_threshold_failure": False,
        "score_comparison": "NOT_APPLICABLE",
        "scored_lane": scored,
        "scored_ratios": scored_ratios,
        "regimes": list(run.REGIMES),
        "latency": lanes,
        "indexing": indexing,
        "throughput": throughput,
        "limitations": [
            "process_cold means a fresh process and unopened reader, never OS-cold page cache",
            "20-sample nearest-rank p95/p99 is a sample distribution, not a production SLA",
            "serial_ops_per_second is a single sustained serial window, not multi-thread QPS",
            "RSS/CPU/allocation metrics are NOT_MEASURED when no common method exists",
            "physical segment counts may differ by engine and are reported, never normalized",
            "index_bytes may differ across trials for engines whose segment layout is "
            "scheduling-dependent; all three observations, min, max and max/min are "
            "reported descriptively and are never used to accept or reject a trial",
        ],
    }


def render_markdown(aggregate: dict) -> str:
    lines = [
        "# PR 15D comparative qualification",
        "",
        f"- Workload: `{aggregate['workload']}`",
        f"- Source SHA: `{aggregate['source_sha']}`",
        f"- Host fingerprint: `{aggregate['host_fingerprint']}`",
        f"- Filesystem: `{aggregate['filesystem']}`",
        f"- Trials: {aggregate['trials']} x {aggregate['samples_per_lane']} samples/lane",
        f"- Status: **{aggregate['status']}**",
        f"- Score comparison: `{aggregate['score_comparison']}`",
        f"- Scored lane: `{aggregate['scored_lane'].get('status')}`",
        f"- Performance threshold failure: `{aggregate['performance_threshold_failure']}`",
        "",
        "## Exact-term latency (median of three trial medians, ns)",
        "",
        "| Lane | Regime | Quervant | Tantivy | Lucene | Tantivy/Quervant | Lucene/Quervant |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for lane in aggregate["latency"]:
        engines = lane["engines"]
        comparison = lane["comparisons"]
        tantivy = comparison.get("tantivy", {})
        lucene = comparison.get("lucene", {})
        lines.append(
            "| {id} | {regime} | {q} | {t} | {l} | {tr} | {lr} |".format(
                id=lane["id"],
                regime=lane["regime"],
                q=engines["quervant"]["median_ns"],
                t=engines["tantivy"]["median_ns"],
                l=engines["lucene"]["median_ns"],
                tr=(
                    f"{tantivy.get('engine_over_quervant_ratio')}"
                    + (" (INCONCLUSIVE)" if tantivy.get("inconclusive") else "")
                ),
                lr=(
                    f"{lucene.get('engine_over_quervant_ratio')}"
                    + (" (INCONCLUSIVE)" if lucene.get("inconclusive") else "")
                ),
            )
        )
    lines += ["", "## Indexing, commit, reopen and size", ""]
    for engine in run.ENGINES:
        lines.append(f"### {engine}")
        lines.append("")
        lines.append("| N | index_ns | commit_ns | reopen_ns | index_bytes | segments |")
        lines.append("|---:|---:|---:|---:|---:|---:|")
        for n in run.N_VALUES:
            entry = aggregate["indexing"][engine][str(n)]
            lines.append(
                "| {n} | {i} | {c} | {r} | {b} | {s} |".format(
                    n=n,
                    i=entry["index_ns"]["median"],
                    c=entry["commit_ns"]["median"],
                    r=entry["reopen_ns"]["median"],
                    b=entry["index_bytes"]["median"],
                    s=entry["segment_count"]["median"],
                )
            )
        lines.append("")
    lines += [
        "## Index artifact size variation (descriptive, never an equality invariant)",
        "",
        "Physical byte totals are reported per trial. Differing positive values do",
        "not invalidate a trial; they expose engine layout differences such as",
        "scheduling-dependent segment boundaries.",
        "",
        "| Engine | N | trial 1 | trial 2 | trial 3 | min | max | max/min |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for engine in run.ENGINES:
        for n in run.N_VALUES:
            sizes = aggregate["indexing"][engine][str(n)]["index_bytes"]
            values = sizes["trial_values"]
            lines.append(
                "| {e} | {n} | {t1} | {t2} | {t3} | {lo} | {hi} | {d} |".format(
                    e=engine,
                    n=n,
                    t1=values[0],
                    t2=values[1],
                    t3=values[2],
                    lo=sizes["min"],
                    hi=sizes["max"],
                    d=sizes["dispersion_max_over_min"],
                )
            )
    lines += [
        "",
        "## Serial throughput (`serial_ops_per_second`)",
        "",
        "| Engine | N | median ops/s | dispersion |",
        "|---|---:|---:|---:|",
    ]
    for engine in run.ENGINES:
        for n in run.N_VALUES:
            entry = aggregate["throughput"][engine][str(n)]
            lines.append(
                "| {e} | {n} | {r} | {d} |".format(
                    e=engine,
                    n=n,
                    r=entry["median_serial_ops_per_second"],
                    d=entry["dispersion_max_over_min"],
                )
            )
    lines += ["", "## Measurement limitations", ""]
    lines.extend(f"- {item}" for item in aggregate["limitations"])
    lines.append("")
    return "\n".join(lines)


def aggregate_bytes(run_dir: str) -> tuple[bytes, bytes]:
    aggregate = build_aggregate(run_dir)
    return run.canonical_json_bytes(aggregate) + b"\n", render_markdown(aggregate).encode("utf-8")


def verify_aggregate(run_dir: str, aggregate_path: str) -> list:
    """Re-derive the summary and reject a cached aggregate that disagrees."""
    expected_json, _ = aggregate_bytes(run_dir)
    try:
        with open(aggregate_path, "rb") as handle:
            actual = handle.read()
    except OSError as error:
        return [{"code": "missing_aggregate", "detail": str(error)}]
    if actual != expected_json:
        return [
            {
                "code": "aggregate_tampered",
                "detail": f"{aggregate_path} does not re-derive from raw trials",
            }
        ]
    return []


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate a validated PR15D run.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--md", required=True)
    args = parser.parse_args(argv)
    try:
        payload, markdown = aggregate_bytes(args.run)
    except AggregateError as error:
        print(f"AGGREGATION REFUSED ({error.status}): {error.detail}", file=sys.stderr)
        return 3
    run.write_json(args.out, json.loads(payload))
    os.makedirs(os.path.dirname(os.path.abspath(args.md)), exist_ok=True)
    with open(args.md, "wb") as handle:
        handle.write(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
