#!/usr/bin/env python3
"""PR 15B strict qualification validator and aggregator.

Subcommands
-----------
``trial``
    Parse a Criterion 0.7 output tree plus an independent fixture-metadata file,
    emit one source-locked trial manifest, and reject any incomplete or
    unqualified trial.
``aggregate``
    Aggregate at least three independently qualified, source-identical trial
    manifests into a small checked-in summary. No metric is invented.
``self-test``
    Build a synthetic valid manifest and assert every required rejection class
    and the aggregation rules. Standard library only.

The validator never manufactures benchmark values and never repairs a bad run.
Exit codes: 0 accepted, 1 invalid, 3 unqualified (structurally valid but not
published), 64 CLI usage.
"""
import argparse
import datetime
import json
import math
import re
import statistics
import sys
import tempfile
from pathlib import Path

WORKLOAD_VERSION = "pr15b_v1"
TRIAL_SCHEMA = "pr15b-trial-v1"
QUALIFIED_SCHEMA = "pr15b-qualified-v1"
FIXTURE_SCHEMA = "quervant-pr15b-fixture-v1"
CANONICAL_SHA = "104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087"
MIN_SAMPLES = 20

REQUIRED_LANES = [
    "pr15b_v1/u01/n2000_s4/k100/absent",
    "pr15b_v1/u01/n10000_s4/k100/absent",
    "pr15b_v1/u01/n100000_s4/k100/absent",
    "pr15b_v1/u02/n2000_s4/k100/rare",
    "pr15b_v1/u02/n10000_s4/k100/rare",
    "pr15b_v1/u02/n100000_s4/k100/rare",
    "pr15b_v1/u03/n2000_s4/k100/medium",
    "pr15b_v1/u03/n10000_s4/k100/medium",
    "pr15b_v1/u03/n100000_s4/k100/medium",
    "pr15b_v1/u04/n2000_s4/k100/common-mixed",
    "pr15b_v1/u04/n10000_s4/k100/common-mixed",
    "pr15b_v1/u04/n100000_s4/k100/common-mixed",
    "pr15b_v1/u05/n10000_s4/k100/cidr-time",
    "pr15b_v1/u06/n10000_s4/k100/json-scalar",
    "pr15b_v1/u07/n10000_s4/k10/sort-n",
    "pr15b_v1/u07/n10000_s4/k100/sort-n",
    "pr15b_v1/u07/n10000_s4/k1000/sort-n",
    "pr15b_v1/u08/n10000_s4/k100/source",
    "pr15b_v1/u08/n10000_s4/k100/fields-host-n",
    "pr15b_v1/u09/n10000_s4/k100/aggregate-host",
    "pr15b_v1/u10/n10000_s4/k100/serial-batch",
    "pr15b_v1/u11/n10000_s1/k100/rare",
    "pr15b_v1/u11/n10000_s1/k100/common-mixed",
    "pr15b_v1/u11/n10000_s4/k100/rare",
    "pr15b_v1/u11/n10000_s4/k100/common-mixed",
    "pr15b_v1/u11/n10000_s16/k100/rare",
    "pr15b_v1/u11/n10000_s16/k100/common-mixed",
    "pr15b_v1/u12/n10000_s4/k100/page-1",
    "pr15b_v1/u12/n10000_s4/k100/page-2",
    "pr15b_v1/u13/geo_n8_s1/k100/geo-bbox",
]

REQUIRED_CORPORA = {
    "n2000_s4",
    "n10000_s1",
    "n10000_s4",
    "n10000_s16",
    "n100000_s4",
    "geo_n8_s1",
}

LANE_RE = re.compile(
    r"^pr15b_v1/(u\d{2})/(?:n(\d+)_s(\d+)|geo_n(\d+)_s(\d+))/k(\d+)/([A-Za-z0-9-]+)$"
)
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
NON_NATIVE_FS = {"drvfs", "9p", "v9fs", "cifs"}


class ValidationError(Exception):
    """Structural or qualification rejection."""


def fail(message):
    raise ValidationError(message)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle, parse_constant=_reject_constant)
    except ValidationError:
        raise
    except Exception as error:  # noqa: BLE001
        fail(f"cannot read JSON {path}: {error}")


def _reject_constant(value):
    fail(f"non-finite JSON constant {value}")


def require(condition, message):
    if not condition:
        fail(message)


def is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def parse_lane_id(lane_id):
    match = LANE_RE.match(lane_id)
    require(match is not None, f"invalid lane id {lane_id!r}")
    case_id = match.group(1)
    if match.group(2) is not None:
        n = int(match.group(2))
        s = int(match.group(3))
        corpus_label = f"n{n}_s{s}"
    else:
        n = int(match.group(4))
        s = int(match.group(5))
        corpus_label = f"geo_n{n}_s{s}"
    return {
        "lane_id": lane_id,
        "case_id": case_id,
        "n": n,
        "s": s,
        "k": int(match.group(6)),
        "variant": match.group(7),
        "corpus_label": corpus_label,
    }


def read_env_file(path):
    env = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if "=" in line:
                    key, value = line.rstrip("\n").split("=", 1)
                    env[key.strip()] = value.strip()
    except OSError as error:
        fail(f"cannot read environment file {path}: {error}")
    return env


def read_criterion_lanes(criterion_dir):
    root = Path(criterion_dir)
    require(root.is_dir(), f"criterion directory does not exist: {criterion_dir}")
    lanes = []
    seen = {}
    for estimates_path in sorted(root.rglob("estimates.json")):
        if estimates_path.parent.name != "new":
            continue
        benchmark_path = estimates_path.parent / "benchmark.json"
        sample_path = estimates_path.parent / "sample.json"
        benchmark = read_json(benchmark_path)
        full_id = benchmark.get("full_id")
        if not isinstance(full_id, str) or not full_id.startswith("pr15b_v1/"):
            continue
        parsed = parse_lane_id(full_id)
        if full_id in seen:
            fail(f"duplicate Criterion lane {full_id}")
        seen[full_id] = True
        estimates = read_json(estimates_path)
        sample = read_json(sample_path)
        iters = sample.get("iters")
        require(isinstance(iters, list), f"{full_id}: missing sample iters")
        mean = estimates.get("mean", {})
        median = estimates.get("median", {})
        std_dev = estimates.get("std_dev", {})
        interval = mean.get("confidence_interval", {})
        lane = dict(parsed)
        lane.update(
            {
                "sample_count": len(iters),
                "estimate_ns": mean.get("point_estimate"),
                "median_ns": median.get("point_estimate"),
                "std_dev_ns": std_dev.get("point_estimate"),
                "ci_lower_ns": interval.get("lower_bound"),
                "ci_upper_ns": interval.get("upper_bound"),
            }
        )
        lanes.append(lane)
    lanes.sort(key=lambda lane: lane["lane_id"])
    require(lanes, "criterion tree contains no pr15b_v1 lanes")
    return lanes


def validate_fixture(fixture):
    require(isinstance(fixture, dict), "fixture metadata must be an object")
    require(fixture.get("schema") == FIXTURE_SCHEMA, "invalid fixture schema")
    require(fixture.get("workload_version") == WORKLOAD_VERSION, "invalid fixture workload_version")
    require(fixture.get("canonical_sha256") == CANONICAL_SHA, "canonical fixture digest mismatch")
    require(fixture.get("oracle_gate") == "PASS", "fixture oracle gate is not PASS")
    corpora = fixture.get("corpora")
    require(isinstance(corpora, list) and corpora, "fixture corpora must be a non-empty list")
    by_label = {}
    for entry in corpora:
        require(isinstance(entry, dict), "fixture corpus entry must be an object")
        label = entry.get("label")
        require(isinstance(label, str) and label, "fixture corpus label is required")
        require(label not in by_label, f"duplicate fixture corpus label {label}")
        n = entry.get("n")
        s = entry.get("s")
        require(isinstance(n, int) and n > 0, f"{label}: invalid n")
        require(isinstance(s, int) and s > 0, f"{label}: invalid s")
        require(
            entry.get("physical_segments") == s,
            f"{label}: physical_segments must equal s",
        )
        require(
            entry.get("document_count") == n,
            f"{label}: document_count must equal n",
        )
        require(
            isinstance(entry.get("rows_sha256"), str)
            and HEX_RE.match(entry["rows_sha256"]),
            f"{label}: invalid rows digest",
        )
        require(
            isinstance(entry.get("corpus_sha256"), str)
            and HEX_RE.match(entry["corpus_sha256"]),
            f"{label}: invalid corpus digest",
        )
        by_label[label] = entry
    missing = REQUIRED_CORPORA - set(by_label)
    require(not missing, f"fixture metadata missing corpora: {sorted(missing)}")
    return by_label


def validate_lane(lane, corpora):
    require(isinstance(lane, dict), "lane must be an object")
    lane_id = lane.get("lane_id")
    require(isinstance(lane_id, str), "lane_id is required")
    parsed = parse_lane_id(lane_id)
    for field in ("case_id", "n", "s", "k", "variant"):
        require(
            lane.get(field) == parsed[field],
            f"{lane_id}: {field} does not match its lane id",
        )
    require(
        parsed["corpus_label"] in corpora,
        f"{lane_id}: corpus {parsed['corpus_label']} absent from fixture metadata",
    )
    corpus = corpora[parsed["corpus_label"]]
    require(
        corpus["n"] == parsed["n"] and corpus["s"] == parsed["s"],
        f"{lane_id}: fixture corpus topology mismatch",
    )
    sample_count = lane.get("sample_count")
    require(
        isinstance(sample_count, int) and sample_count >= MIN_SAMPLES,
        f"{lane_id}: sample_count {sample_count!r} < {MIN_SAMPLES}",
    )
    for field in (
        "estimate_ns",
        "median_ns",
        "std_dev_ns",
        "ci_lower_ns",
        "ci_upper_ns",
    ):
        require(is_number(lane.get(field)), f"{lane_id}: {field} must be finite numeric")
    require(lane["estimate_ns"] > 0, f"{lane_id}: estimate_ns must be positive")
    require(lane["median_ns"] > 0, f"{lane_id}: median_ns must be positive")
    require(lane["std_dev_ns"] >= 0, f"{lane_id}: std_dev_ns must be nonnegative")
    require(
        lane["ci_lower_ns"] <= lane["estimate_ns"] <= lane["ci_upper_ns"],
        f"{lane_id}: confidence interval must bracket estimate_ns",
    )


def validate_trial(manifest):
    require(isinstance(manifest, dict), "trial manifest must be an object")
    require(manifest.get("schema") == TRIAL_SCHEMA, "invalid trial schema")
    require(manifest.get("workload_version") == WORKLOAD_VERSION, "invalid workload version")
    require(manifest.get("profile") == "release", "trial must use the release bench profile")
    source_sha = manifest.get("source_sha")
    require(
        isinstance(source_sha, str) and SHA_RE.match(source_sha),
        "source_sha must be a hexadecimal git SHA",
    )
    qualification = manifest.get("qualification")
    require(isinstance(qualification, dict), "qualification section is required")
    require(qualification.get("clean_tree") is True, "trial tree is not clean")
    require(
        qualification.get("operator_idle_confirmed") is True,
        "operator idle attestation missing",
    )
    require(
        qualification.get("contention_state") == "clear",
        "contention is not clear",
    )
    require(
        qualification.get("correctness_passed") is True,
        "benchmark correctness gate did not pass",
    )
    profiler_status = qualification.get("profiler_status")
    require(profiler_status in {"AVAILABLE", "UNAVAILABLE"}, "invalid profiler_status")
    if profiler_status == "AVAILABLE":
        evidence = qualification.get("profiler_evidence")
        require(
            isinstance(evidence, str) and evidence,
            "AVAILABLE profiler status requires captured evidence",
        )
    environment = manifest.get("environment")
    require(isinstance(environment, dict), "environment section is required")
    filesystem = environment.get("filesystem")
    require(isinstance(filesystem, str) and filesystem, "filesystem is required")
    require(
        filesystem not in NON_NATIVE_FS and not filesystem.startswith("smb"),
        f"filesystem {filesystem!r} is not a native Linux filesystem",
    )
    corpora = validate_fixture(manifest.get("fixture"))
    lanes = manifest.get("lanes")
    require(isinstance(lanes, list) and lanes, "lanes must be a non-empty list")
    by_id = {}
    for lane in lanes:
        validate_lane(lane, corpora)
        if lane["lane_id"] in by_id:
            fail(f"duplicate lane {lane['lane_id']}")
        by_id[lane["lane_id"]] = lane
    missing = set(REQUIRED_LANES) - set(by_id)
    require(not missing, f"missing required lanes: {sorted(missing)[:3]}")
    for lane_id in by_id:
        if lane_id in REQUIRED_LANES:
            continue
        lane = by_id[lane_id]
        optional = (
            lane["case_id"] == "u14"
            or (lane["n"] == 1_000_000 and lane["s"] == 4)
            or (lane["n"] == 100_000 and lane["s"] == 64)
        )
        require(optional, f"unexpected extra lane {lane_id}")
    return by_id


def build_trial(args):
    fixture = read_json(args.fixture_metadata)
    corpora = validate_fixture(fixture)
    lanes = read_criterion_lanes(args.criterion_dir)
    for lane in lanes:
        validate_lane(lane, corpora)
    env = read_env_file(args.env_file)
    require(
        env.get("git_sha") == args.source_sha,
        "environment git_sha does not match --source-sha",
    )
    clean_tree = (not args.source_dirty) and env.get("git_dirty") == "false"
    profiler_paths = [
        env.get("perf_path", "UNAVAILABLE"),
        env.get("cargo-flamegraph_path", "UNAVAILABLE"),
        env.get("heaptrack_path", "UNAVAILABLE"),
    ]
    profiler_status = (
        "UNAVAILABLE" if all(path == "UNAVAILABLE" for path in profiler_paths) else "AVAILABLE"
    )
    manifest = {
        "schema": TRIAL_SCHEMA,
        "workload_version": WORKLOAD_VERSION,
        "run_id": args.run_id,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "source_sha": args.source_sha,
        "source_dirty": bool(args.source_dirty) or env.get("git_dirty") != "false",
        "profile": "release",
        "toolchain": {
            "rustc": env.get("rustc", "unknown"),
            "cargo": env.get("cargo", "unknown"),
        },
        "environment": {
            "os_kernel": env.get("uname", "unknown"),
            "wsl2": env.get("wsl2", "unknown"),
            "cpu_model": env.get("cpu_model", "unknown"),
            "logical_cpus": env.get("logical_cpus", "unknown"),
            "mem_total": env.get("mem_total", "unknown"),
            "filesystem": env.get("filesystem", "unknown"),
            "criterion_version": env.get("criterion_version", "unknown"),
        },
        "qualification": {
            "clean_tree": clean_tree,
            "operator_idle_confirmed": bool(args.idle_confirmed),
            "contention_state": args.contention_state,
            "correctness_passed": bool(args.correctness_passed),
            "profiler_status": profiler_status,
            "profiler_evidence": args.profiler_evidence or None,
        },
        "fixture": fixture,
        "lanes": lanes,
    }
    errors = []
    try:
        validate_trial(manifest)
    except ValidationError as error:
        errors.append(str(error))
    manifest["qualified"] = not errors
    manifest["rejection_reasons"] = errors
    write_json(args.out, manifest)
    if errors:
        print(f"UNQUALIFIED: {args.out}: {errors[0]}", file=sys.stderr)
        return 3
    print(f"QUALIFIED: {args.out}: {len(lanes)} lanes")
    return 0


def aggregate_trials(trials):
    require(len(trials) >= 3, "aggregation requires at least three trials")
    validated = []
    for manifest in trials:
        validate_trial(manifest)
        require(manifest.get("qualified") is True, "trial is not qualified")
        validated.append(manifest)
    base = validated[0]
    for manifest in validated[1:]:
        require(
            manifest["source_sha"] == base["source_sha"],
            "trials have different source SHAs",
        )
        require(
            manifest["fixture"] == base["fixture"],
            "trials have different fixture metadata",
        )
        require(
            manifest["workload_version"] == base["workload_version"],
            "trials have different workload versions",
        )
    lane_sets = [set(lane["lane_id"] for lane in manifest["lanes"]) for manifest in validated]
    common_lanes = set.intersection(*lane_sets)
    missing = set(REQUIRED_LANES) - common_lanes
    require(not missing, f"common lane set is missing required lanes: {sorted(missing)[:3]}")
    summary = []
    for lane_id in sorted(common_lanes):
        rows = []
        for manifest in validated:
            row = next(lane for lane in manifest["lanes"] if lane["lane_id"] == lane_id)
            rows.append(row)
        medians = [row["median_ns"] for row in rows]
        estimates = [row["estimate_ns"] for row in rows]
        low = min(medians)
        high = max(medians)
        summary.append(
            {
                "lane_id": lane_id,
                "case_id": rows[0]["case_id"],
                "n": rows[0]["n"],
                "s": rows[0]["s"],
                "k": rows[0]["k"],
                "variant": rows[0]["variant"],
                "trial_median_ns": medians,
                "trial_estimate_ns": estimates,
                "median_of_medians_ns": statistics.median(medians),
                "min_median_ns": low,
                "max_median_ns": high,
                "dispersion_ratio": (high / low) if low > 0 else None,
            }
        )
    return {
        "schema": QUALIFIED_SCHEMA,
        "workload_version": base["workload_version"],
        "source_sha": base["source_sha"],
        "profile": "release",
        "trials": len(validated),
        "trial_run_ids": [manifest["run_id"] for manifest in validated],
        "fixture": base["fixture"],
        "environment": base["environment"],
        "qualified": True,
        "lanes": summary,
    }


def write_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(target)


def write_markdown(path, summary):
    lines = [
        f"# PR 15B qualified summary — {summary['source_sha']}",
        "",
        f"- Workload version: `{summary['workload_version']}`",
        f"- Source SHA: `{summary['source_sha']}`",
        f"- Qualified trials: {summary['trials']}",
        f"- Canonical fixture: `{CANONICAL_SHA}`",
        "- Criterion estimates are microbenchmark iteration distributions, not request p99 or a production SLA.",
        "",
        "| lane | trials | median-of-medians ns | min median ns | max median ns | dispersion |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for lane in summary["lanes"]:
        dispersion = lane["dispersion_ratio"]
        lines.append(
            "| `{}` | {} | {:.1f} | {:.1f} | {:.1f} | {} |".format(
                lane["lane_id"],
                summary["trials"],
                lane["median_of_medians_ns"],
                lane["min_median_ns"],
                lane["max_median_ns"],
                "n/a" if dispersion is None else f"{dispersion:.3f}",
            )
        )
    lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def build_aggregate(args):
    trials = [read_json(path) for path in args.trial]
    summary = aggregate_trials(trials)
    write_json(args.out, summary)
    if args.out_md:
        write_markdown(args.out_md, summary)
    print(f"QUALIFIED SUMMARY: {args.out}: {summary['trials']} trials, {len(summary['lanes'])} lanes")
    return 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def synthetic_fixture():
    corpora = []
    for label, n, s in [
        ("n2000_s4", 2000, 4),
        ("n10000_s1", 10000, 1),
        ("n10000_s4", 10000, 4),
        ("n10000_s16", 10000, 16),
        ("n100000_s4", 100000, 4),
        ("geo_n8_s1", 8, 1),
    ]:
        corpora.append(
            {
                "label": label,
                "n": n,
                "s": s,
                "rows_sha256": "a" * 64,
                "corpus_sha256": "b" * 64,
                "physical_segments": s,
                "document_count": n,
            }
        )
    return {
        "schema": FIXTURE_SCHEMA,
        "workload_version": WORKLOAD_VERSION,
        "canonical_sha256": CANONICAL_SHA,
        "oracle_gate": "PASS",
        "corpora": corpora,
    }


def synthetic_lane(lane_id):
    parsed = parse_lane_id(lane_id)
    lane = dict(parsed)
    lane.update(
        {
            "sample_count": 20,
            "estimate_ns": 1000.0,
            "median_ns": 990.0,
            "std_dev_ns": 10.0,
            "ci_lower_ns": 950.0,
            "ci_upper_ns": 1050.0,
        }
    )
    return lane


def synthetic_trial(run_id="trial-1", source_sha="a" * 40):
    return {
        "schema": TRIAL_SCHEMA,
        "workload_version": WORKLOAD_VERSION,
        "run_id": run_id,
        "timestamp_utc": "2026-01-01T00:00:00Z",
        "source_sha": source_sha,
        "source_dirty": False,
        "profile": "release",
        "toolchain": {"rustc": "rustc test", "cargo": "cargo test"},
        "environment": {
            "os_kernel": "Linux test",
            "wsl2": "true",
            "cpu_model": "test cpu",
            "logical_cpus": "12",
            "mem_total": "32 GB",
            "filesystem": "ext4",
            "criterion_version": "0.7.0",
        },
        "qualification": {
            "clean_tree": True,
            "operator_idle_confirmed": True,
            "contention_state": "clear",
            "correctness_passed": True,
            "profiler_status": "UNAVAILABLE",
            "profiler_evidence": None,
        },
        "fixture": synthetic_fixture(),
        "lanes": [synthetic_lane(lane_id) for lane_id in REQUIRED_LANES],
        "qualified": True,
        "rejection_reasons": [],
    }


def expect_reject(manifest, label):
    try:
        validate_trial(manifest)
    except ValidationError:
        return
    raise AssertionError(f"self-test: {label} was accepted but must be rejected")


def clone(value):
    return json.loads(json.dumps(value))


def self_test():
    valid = synthetic_trial()
    validate_trial(valid)

    broken = clone(valid)
    broken["lanes"] = broken["lanes"][:-1]
    expect_reject(broken, "missing lane")

    broken = clone(valid)
    broken["source_dirty"] = True
    broken["qualification"]["clean_tree"] = False
    expect_reject(broken, "dirty tree")

    broken = clone(valid)
    broken["qualification"]["contention_state"] = "suspected"
    expect_reject(broken, "contended trial")

    broken = clone(valid)
    broken["qualification"]["operator_idle_confirmed"] = False
    expect_reject(broken, "missing idle attestation")

    broken = clone(valid)
    broken["fixture"]["canonical_sha256"] = "0" * 64
    expect_reject(broken, "bad canonical digest")

    broken = clone(valid)
    broken["fixture"]["oracle_gate"] = "FAIL"
    expect_reject(broken, "oracle gate not PASS")

    broken = clone(valid)
    broken["lanes"].append(clone(broken["lanes"][0]))
    expect_reject(broken, "duplicate lane")

    broken = clone(valid)
    broken["lanes"][0]["sample_count"] = MIN_SAMPLES - 1
    expect_reject(broken, "too few samples")

    broken = clone(valid)
    broken["lanes"][0]["estimate_ns"] = -1.0
    expect_reject(broken, "negative estimate")

    broken = clone(valid)
    broken["lanes"][0]["n"] = 2001
    expect_reject(broken, "lane topology mismatch")

    broken = clone(valid)
    broken["qualification"]["profiler_status"] = "AVAILABLE"
    expect_reject(broken, "profiler claimed without evidence")

    broken = clone(valid)
    broken["environment"]["filesystem"] = "drvfs"
    expect_reject(broken, "non-native filesystem")

    summary = aggregate_trials(
        [
            valid,
            synthetic_trial("trial-2"),
            synthetic_trial("trial-3"),
        ]
    )
    assert summary["qualified"] is True
    assert summary["trials"] == 3
    assert len(summary["lanes"]) == len(REQUIRED_LANES)
    assert all(lane["dispersion_ratio"] == 1.0 for lane in summary["lanes"])

    try:
        aggregate_trials([valid, synthetic_trial("trial-2")])
    except ValidationError:
        pass
    else:
        raise AssertionError("self-test: aggregation accepted fewer than three trials")

    mismatched = synthetic_trial("trial-3", source_sha="b" * 40)
    try:
        aggregate_trials([valid, synthetic_trial("trial-2"), mismatched])
    except ValidationError:
        pass
    else:
        raise AssertionError("self-test: aggregation accepted source-mismatched trials")

    # Criterion parsing round-trip on a synthetic on-disk tree.
    with tempfile.TemporaryDirectory() as tmp:
        criterion = Path(tmp) / "criterion"
        for lane_id in REQUIRED_LANES[:2]:
            lane_dir = criterion.joinpath(*lane_id.split("/")) / "new"
            lane_dir.mkdir(parents=True)
            write_json(
                lane_dir / "benchmark.json",
                {
                    "full_id": lane_id,
                    "title": lane_id,
                },
            )
            write_json(
                lane_dir / "sample.json",
                {"sampling_mode": "Linear", "iters": [1.0] * 20, "times": [1.0] * 20},
            )
            write_json(
                lane_dir / "estimates.json",
                {
                    "mean": {
                        "point_estimate": 1000.0,
                        "confidence_interval": {
                            "lower_bound": 900.0,
                            "upper_bound": 1100.0,
                        },
                    },
                    "median": {"point_estimate": 990.0},
                    "std_dev": {"point_estimate": 10.0},
                },
            )
        parsed = read_criterion_lanes(criterion)
        assert len(parsed) == 2
        assert parsed[0]["sample_count"] == 20
        assert parsed[0]["estimate_ns"] == 1000.0

    print("SELF-TEST OK")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Validate PR 15B qualification artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    trial = subparsers.add_parser("trial", help="build and validate one trial manifest")
    trial.add_argument("--criterion-dir", required=True)
    trial.add_argument("--fixture-metadata", required=True)
    trial.add_argument("--env-file", required=True)
    trial.add_argument("--out", required=True)
    trial.add_argument("--run-id", required=True)
    trial.add_argument("--source-sha", required=True)
    trial.add_argument("--contention-state", required=True, choices=["clear", "suspected", "unknown"])
    trial.add_argument("--source-dirty", action="store_true")
    trial.add_argument("--idle-confirmed", action="store_true")
    trial.add_argument("--correctness-passed", action="store_true")
    trial.add_argument(
        "--profiler-evidence",
        default=None,
        help="non-empty record of genuinely captured profiler evidence; required by "
        "validation whenever profiler_status is AVAILABLE",
    )

    aggregate = subparsers.add_parser("aggregate", help="aggregate qualified trials")
    aggregate.add_argument("--trial", action="append", required=True)
    aggregate.add_argument("--out", required=True)
    aggregate.add_argument("--out-md")

    subparsers.add_parser("self-test", help="run negative and positive self-tests")

    args = parser.parse_args()
    try:
        if args.command == "trial":
            return build_trial(args)
        if args.command == "aggregate":
            return build_aggregate(args)
        return self_test()
    except ValidationError as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
