#!/usr/bin/env python3
"""A6 read-only artifact verification; no query, build, test, or artifact writes.

Run from repository root with the same environment as acquisition:
PYTHONPATH=benchmarks python /path/to/verify_a6_results.py \
  RUNNER_SHA SCRATCH_ROOT RETENTION_CONFIG RETENTION_RESULT \
  CUMULATIVE_CONFIG CUMULATIVE_RESULT

Only pass COMPLETE results here. An incomplete result is retained and reported
without attempting to manufacture a complete analysis.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

from quervant_bench.lean.artifacts import load_configuration, load_result
from quervant_bench.lean.configuration import lanes_for, validate_configuration
from quervant_bench.lean.statistics import analyze
from quervant_bench.lean import preparation

A0 = "2a74017958c8ac61948f931e8745bf8134827025"
E = "b70f624fffe0329def62701b61e997c4e303e167"
F = "3bb232f868cb556ce9b4273d902164c65416af0f"
POLICY = {
    "blocks": 12, "slots_per_arm": 2, "warmups": 5, "samples": 20,
    "bootstrap_resamples": 10000, "seed": 20261122, "min_blocks": 4,
    "min_gain_percent": 0, "max_regression_percent": 0,
    "max_aa_gain_percent": 15, "exclude_blocks": {}, "control_arms": [],
    "readiness": {
        "intervals": 4, "interval_ms": 250,
        "max_busy_percent": 25, "max_steal_percent": 2,
    },
}
PRIMARY = {
    "100000/medium/k10/warm", "100000/medium/k100/warm",
    "100000/common/k10/warm", "100000/common/k100/warm",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def verify_one(
    config_path: Path,
    result_path: Path,
    *,
    baseline: str,
    name: str,
    runner_sha: str,
    scratch_root: Path,
) -> dict:
    config_before = hashlib.sha256(config_path.read_bytes()).hexdigest()
    result_before = hashlib.sha256(result_path.read_bytes()).hexdigest()
    config = load_configuration(config_path)
    validate_configuration(config)
    result = load_result(result_path)
    require(config["family"] == "perf-06", "wrong family")
    require(config["name"] == name, "wrong campaign name")
    require(config["workload"] == {
        "id": "pr15d-exact-keyword-v1", "sizes": [10000, 100000],
        "classes": ["absent", "rare", "medium", "common"],
        "top_k": [10, 100], "regimes": ["warm"],
        "query_semantics": "exact-keyword-total-hits-and-ordered-doc-ids",
        "timed_operation": "exact-term-search-plus-topk-projection",
    }, "frozen workload changed")
    require(config["policy"] == POLICY, "frozen policy changed")
    require(config["arms"] == {
        "A": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": baseline},
        "B": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": F},
    }, "arm sources or modes changed")
    require(config["build"] == {
        "release": True, "locked": True, "baseline_ref": None,
        "prefilter_profile": "P2", "quervant_feature": None,
    }, "build settings changed")
    require(config["baseline"] == "A", "wrong baseline")
    require(config["control"] == {
        "enabled": True, "baseline": "AA", "equivalent": "AA2",
    }, "control roles changed")
    expected_lanes = lanes_for(config)
    require(len(expected_lanes) == 16, "wrong lane count")
    require(result["schema"] == "benchmark-result-v1", "wrong result schema")
    require(result["family"] == "perf-06", "wrong result family")
    require(result["configuration"] == config, "embedded configuration changed")
    require(result["configuration_id"] == config["configuration_id"], "wrong configuration UUID")
    require(result["configuration_file"] == config_path.name, "wrong configuration filename")
    require(result["configuration_name"] == name, "wrong result campaign")
    require(result_path.parent.resolve() == (config_path.parent.parent / "results").resolve(),
            "result outside canonical sibling directory")
    require(result["sequence"] == 1, "unexpected additional acquisition sequence")
    require(result["status"] == "COMPLETE", "result is not COMPLETE")
    require(result["errors"] == [], "result has errors")
    require(result["lanes"] == expected_lanes, "lane descriptors changed")
    context = result["context"]
    require(context["source_revision"] == runner_sha, "unexpected runner source")
    require(context["build"]["arm_source_revisions"] == {"A": baseline, "B": F},
            "wrong compiled arm sources")
    require(context["build"]["compiler_options"] == "cargo --release --locked",
            "wrong compiler options")
    require(context["build"]["quervant_strategy_feature_enabled"] is False,
            "experiment feature unexpectedly enabled")
    require(context["controller_cpu"] != context["adapter_cpu"], "CPU affinity collided")
    for cpu_key in ("controller_cpu", "adapter_cpu"):
        cpu = context[cpu_key]
        require(isinstance(cpu, int) and not isinstance(cpu, bool) and cpu >= 0,
                "missing CPU affinity identity")
    prep = context["preparation"]
    require(prep["verified_oracles"] is True, "preparation oracles unverified")
    require(prep["cache_status"] in ("BUILT", "HIT"), "unknown preparation state")
    require(prep["index_metrics_provenance"] == "preparation stage (not the current query window)",
            "index metric timing scope changed")
    require(re.fullmatch(r"[0-9a-f]{64}", prep["cache_key"]) is not None, "invalid cache key")
    controls = result["controls"]
    for key in ("readiness_index_pre", "readiness_pre", "readiness_treatment", "readiness_post"):
        require(controls[key]["status"] == "clear", f"{key} did not pass")
        require(controls[key]["cpu"] == context["adapter_cpu"], f"{key} CPU differs")
    require(controls["readiness_index_source"] == "preparation stage",
            "index readiness provenance changed")
    lane_ids = {lane["id"] for lane in expected_lanes}
    for label, rows, arms in (
        ("control", controls["raw_samples"], {"AA", "AA2"}),
        ("treatment", result["raw_samples"], {"A", "B"}),
    ):
        require(len(rows) == 768, f"{label}: wrong record count")
        require(Counter(row["lane_id"] for row in rows) == Counter({lane: 48 for lane in lane_ids}),
                f"{label}: wrong per-lane record count")
        require(Counter(row["arm_id"] for row in rows) == Counter({arm: 384 for arm in arms}),
                f"{label}: wrong arm record count")
        for row in rows:
            require(row["warmups"] == 5 and row["oracle_ok"] is True,
                    f"{label}: invalid warmups or oracle")
            require(row["strategy_marker"] is None, f"{label}: unexpected strategy override")
            require(len(row["samples_ns"]) == 20 and
                    all(positive_integer(x) for x in row["samples_ns"]),
                    f"{label}: missing or invalid timed samples")
    aa_policy = dict(config["policy"], control_arms=["AA2"])
    control_replay = analyze(
        controls["raw_samples"], arms=["AA", "AA2"], baseline="AA",
        lanes=result["lanes"], policy=aa_policy,
    )
    treatment_replay = analyze(
        result["raw_samples"], arms=["A", "B"], baseline="A",
        lanes=result["lanes"], policy=config["policy"],
    )
    require(control_replay == controls["analysis"], "A/A analysis differs on replay")
    require(treatment_replay == result["analysis"], "A/B analysis differs on replay")
    for lane in lane_ids:
        require(control_replay["lanes"][lane]["comparisons"]["AA2"]["status"] == "PASS",
                "A/A lane did not pass")
        for phase in (control_replay, treatment_replay):
            row = phase["lanes"][lane]
            require(row["raw_blocks"] == 12 and row["retained_blocks"] == 12
                    and row["excluded_blocks"] == [], "missing/pruned blocks")
        comp = treatment_replay["lanes"][lane]["comparisons"]["B"]
        require(comp["status"] in ("IMPROVED", "REGRESSED", "INCONCLUSIVE"),
                "uncomputable comparison")
        require(comp["bootstrap_resamples"] == 10000 and
                len(comp["retained_paired_ratios"]) == 12, "wrong bootstrap inputs")
    cache_dir = scratch_root.resolve() / "prepared" / prep["cache_key"]
    # Read-only native cache verification; no stage(), queries, or rebuilds.
    identity = preparation.source_identity(Path.cwd(), config)
    cached = preparation._load_cache(cache_dir, identity, config)
    require(cached is not None, "prepared input identity/fingerprint no longer verifies")
    require(cached["index_metrics"] == result["index_metrics"], "index metrics differ")
    require(cached["build_info"] == context["build"], "cached build identity differs")
    require(cached["prepared_utc"] == prep["prepared_utc"], "preparation timestamp differs")
    for arm in ("A", "B"):
        for n in ("10000", "100000"):
            metrics = result["index_metrics"][arm][n]
            for key in ("index_ns", "commit_ns", "reopen_ns", "index_bytes"):
                require(positive_integer(metrics[key]), "invalid index metric")
            require(metrics["segment_count"] == 1, "unexpected benchmark segment count")
    require(hashlib.sha256(config_path.read_bytes()).hexdigest() == config_before,
            "configuration changed during verification")
    require(hashlib.sha256(result_path.read_bytes()).hexdigest() == result_before,
            "result changed during verification")
    return result


def classify(result: dict, *, retention: bool) -> list[dict]:
    decisions = []
    for lane, row in result["analysis"]["lanes"].items():
        comp = row["comparisons"]["B"]
        gain = comp["gain_percent"]
        lower, upper = comp["gain_ci_95_percent"]
        if retention:
            category = "A5_RETENTION"
            passed = gain >= -2.0 and lower >= -5.0
        elif lane in PRIMARY:
            category = "CUMULATIVE_PRIMARY"
            passed = comp["status"] == "IMPROVED" and gain >= 5.0 and lower > 0.0
        else:
            category = "CUMULATIVE_GUARD"
            passed = gain >= -10.0 and lower >= -10.0
        decisions.append({
            "lane": lane, "category": category, "gain_percent": gain,
            "gain_ci_95_percent": [lower, upper], "analyzer_status": comp["status"],
            "gate": "MET" if passed else "NOT_MET",
        })
    return decisions


if __name__ == "__main__":
    require(len(sys.argv) == 7, "expected runner SHA, scratch root, and two config/result pairs")
    runner, scratch, rcfg, rres, ccfg, cres = sys.argv[1:]
    require(re.fullmatch(r"[0-9a-f]{40}", runner) is not None, "invalid runner SHA")
    r = verify_one(
        Path(rcfg), Path(rres), baseline=E,
        name="quervant-perf06a6-adaptive-warm", runner_sha=runner, scratch_root=Path(scratch),
    )
    c = verify_one(
        Path(ccfg), Path(cres), baseline=A0,
        name="quervant-perf06a6-cumulative-warm", runner_sha=runner, scratch_root=Path(scratch),
    )
    require(r["configuration_id"] != c["configuration_id"], "campaign UUID reused")
    require(r["run_id"] != c["run_id"], "run UUID reused")
    require(r["context"]["controller_cpu"] == c["context"]["controller_cpu"] and
            r["context"]["adapter_cpu"] == c["context"]["adapter_cpu"], "campaign CPUs differ")
    # Both current-F builds must produce the same complete-index bytes at each size.
    for n in ("10000", "100000"):
        require(r["index_metrics"]["B"][n]["index_bytes"] ==
                c["index_metrics"]["B"][n]["index_bytes"],
                "independently built F index sizes disagree")
    print(json.dumps({
        "verification": "PASS",
        "retention": classify(r, retention=True),
        "cumulative": classify(c, retention=False),
    }, indent=2, sort_keys=True, allow_nan=False))

