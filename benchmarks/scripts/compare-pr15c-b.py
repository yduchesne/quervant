#!/usr/bin/env python3
"""PR 15C-B strict before/after comparator for qualified PR 15B aggregates.

Subcommands
-----------
``compare``
    Compare a *before* (pre-PR-15C-A) and an *after* (PR-15C-B head) set of
    qualified PR 15B measurement artifacts lane by lane, emit a small
    machine-readable report and a human-readable report. A comparison is labelled
    ``QUALIFIED`` **only** when every provenance, qualification, host, corpus,
    workload and lane-integrity check passes. Anything less is labelled
    ``UNQUALIFIED`` with the precise reasons and is never published as a speedup
    claim.
``self-test``
    Build synthetic qualified manifest fixtures, assert the schema/semantics
    rejection classes and assert the simple descriptive ratios.

Design constraints (PR 15C-B plan §S4)
-------------------------------------
- Standard library only.
- The frozen ``validate-pr15b.py`` validator and its PR 15B schema are **not**
  edited. This tool *imports* the validator and reuses ``validate_trial`` and
  ``REQUIRED_LANES`` so schema knowledge is never duplicated or drifted.
- An aggregate does not expose trial-level qualification facts (correctness,
  idle attestation, contention, profiler evidence). Where the aggregate is silent,
  the source trial manifests are required and validated directly; no field is ever
  invented or interpolated.
- No statistical significance claim is made. Confidence/noise handling is a
  predeclared descriptive heuristic documented in ``LIMITATIONS``.
"""
import argparse
import importlib.util
import json
import math
import statistics
import sys
from pathlib import Path

COMPARISON_SCHEMA = "pr15c-b-comparison-v1"
QUALIFIED_SCHEMA = "pr15b-qualified-v1"
TRIAL_SCHEMA = "pr15b-trial-v1"
WORKLOAD_VERSION = "pr15b_v1"

#: Full 40-hex git SHA required: a shortened SHA is not acceptable provenance for
#: a causal before/after claim.
FULL_SHA_RE = __import__("re").compile(r"^[0-9a-f]{40}$")

#: The exact pre-PR-15C-A source proven at S0 from the PR 15C-A merge history
#: (first parent of merge commit 93a9980, i.e. PR #75's merge).
PRE_15C_A_SHA = "42b19445dd79a90d8701b4306e305c6e4e44cd57"

MIN_TRIALS = 3

#: Descriptive noise heuristic: a lane whose per-side trial-median spread
#: (max/min) exceeds this is reported INCONCLUSIVE. This is a predeclared
#: descriptive rule, not a significance test.
NOISE_DISPERSION_RATIO = 1.10

#: Descriptive effect-size heuristic: |delta_pct| below this is INCONCLUSIVE.
MIN_INTERPRETABLE_DELTA_PCT = 3.0

ENVIRONMENT_FIELDS = (
    "cpu_model",
    "os_kernel",
    "wsl2",
    "filesystem",
    "logical_cpus",
    "mem_total",
    "criterion_version",
)
TOOLCHAIN_FIELDS = ("rustc", "cargo")

#: Predeclared descriptive groups (plan §S4). Lanes stay visible individually.
LANE_GROUPS = (
    ("U01/U02 no/rare hits", ("u01", "u02")),
    ("U03/U04 lexical mixed", ("u03", "u04")),
    ("U05-U10 typed/JSON/sort/projection/aggregation/batch", ("u05", "u06", "u07", "u08", "u09", "u10")),
    ("U11 segment topology", ("u11",)),
    ("U12 PIT pages", ("u12",)),
    ("U13 geo", ("u13",)),
)

LIMITATIONS = [
    "Per-lane ratios are descriptive medians of three independent trial medians.",
    "Independent trials do not estimate production request p95 or p99 latency.",
    "No cross-lane arithmetic average of speedups is computed or published.",
    "Group figures are descriptive medians and ranges over visible lanes only.",
    "INCONCLUSIVE means the predeclared noise/effect heuristics cannot separate "
    "the measured difference from trial-to-trial dispersion; it is not a "
    "significance test and not evidence of no effect.",
    "Criterion estimates are microbenchmark iteration distributions, not an SLA.",
]


class ComparisonError(Exception):
    """Structural rejection that prevents any comparison table."""


def fail(message):
    raise ComparisonError(message)


def load_validator():
    """Import the frozen PR 15B validator without editing or copying it."""
    path = Path(__file__).resolve().parent / "validate-pr15b.py"
    if not path.is_file():
        fail(f"frozen PR15B validator not found at {path}")
    spec = importlib.util.spec_from_file_location("pr15b_validator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path):
    validator = load_validator()
    try:
        return validator.read_json(path)
    except validator.ValidationError as error:
        raise ComparisonError(str(error)) from error


def write_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(target)


def is_finite_positive(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def require_full_sha(value, label):
    if not isinstance(value, str) or not FULL_SHA_RE.match(value):
        fail(f"{label} source_sha must be a full 40-hex git SHA, got {value!r}")
    return value


class Side:
    """One measured side: source SHA, trial manifests, aggregate and lanes."""

    def __init__(self, label):
        self.label = label
        self.sha = None
        self.trials = []
        self.aggregate = None
        self.aggregate_mode = "none"
        self.environment = {}
        self.toolchain = {}
        self.fixture = None
        self.lanes = {}
        self.reasons = []

    def note(self, message):
        self.reasons.append(f"{self.label}: {message}")

    @property
    def clean(self):
        return not self.reasons


def load_side(label, aggregate_path, trial_paths):
    validator = load_validator()
    side = Side(label)

    for path in trial_paths:
        manifest = read_json(path)
        side.trials.append((str(path), manifest))

    if not side.trials:
        side.note(
            "no source trial manifests supplied; an aggregate alone does not "
            "expose correctness, idle attestation, contention or profiler evidence"
        )

    if aggregate_path:
        aggregate = read_json(aggregate_path)
        side.aggregate = aggregate
        side.aggregate_mode = "aggregate+trials" if side.trials else "aggregate-only"

    # --- trial-level qualification (the only place these facts exist) --------
    for path, manifest in side.trials:
        if not isinstance(manifest, dict):
            side.note(f"trial {path} is not a JSON object")
            continue
        if manifest.get("schema") != TRIAL_SCHEMA:
            side.note(f"trial {path} schema is {manifest.get('schema')!r}, expected {TRIAL_SCHEMA}")
            continue
        if manifest.get("workload_version") != WORKLOAD_VERSION:
            side.note(f"trial {path} workload_version is not {WORKLOAD_VERSION}")
        try:
            validator.validate_trial(manifest)
        except validator.ValidationError as error:
            side.note(f"trial {path} is not structurally qualified: {error}")
        if manifest.get("qualified") is not True:
            side.note(f"trial {path} is marked unqualified: {manifest.get('rejection_reasons')}")

    qualified_trials = [manifest for _, manifest in side.trials if isinstance(manifest, dict)]
    if qualified_trials:
        shas = {manifest.get("source_sha") for manifest in qualified_trials}
        if len(shas) != 1:
            side.note(f"trials have {len(shas)} distinct source SHAs: {sorted(map(str, shas))}")
        side.sha = qualified_trials[0].get("source_sha")
        if len(qualified_trials) < MIN_TRIALS:
            side.note(
                f"only {len(qualified_trials)} trial manifest(s) supplied; "
                f"{MIN_TRIALS} independent qualified trials are required"
            )
        side.toolchain = dict(qualified_trials[0].get("toolchain") or {})
        side.fixture = qualified_trials[0].get("fixture")
        for other in qualified_trials[1:]:
            if other.get("fixture") != side.fixture:
                side.note("trials do not share byte-identical fixture metadata")
                break
        for other in qualified_trials[1:]:
            if (other.get("toolchain") or {}) != side.toolchain:
                side.note("trials do not share an identical toolchain fingerprint")
                break

    # --- aggregate-level qualification --------------------------------------
    if side.aggregate is not None:
        aggregate = side.aggregate
        if not isinstance(aggregate, dict):
            side.note("aggregate is not a JSON object")
        else:
            if aggregate.get("schema") != QUALIFIED_SCHEMA:
                side.note(
                    f"aggregate schema is {aggregate.get('schema')!r}, expected {QUALIFIED_SCHEMA}"
                )
            if aggregate.get("qualified") is not True:
                side.note("aggregate is not marked qualified")
            if aggregate.get("workload_version") != WORKLOAD_VERSION:
                side.note(f"aggregate workload_version is not {WORKLOAD_VERSION}")
            if aggregate.get("profile") != "release":
                side.note("aggregate profile is not the release bench profile")
            trials_count = aggregate.get("trials")
            if not isinstance(trials_count, int) or trials_count < MIN_TRIALS:
                side.note(f"aggregate trials field {trials_count!r} < {MIN_TRIALS}")
            aggregate_sha = aggregate.get("source_sha")
            require_full_sha(aggregate_sha, f"{label} aggregate")
            if side.sha is None:
                side.sha = aggregate_sha
            elif side.sha != aggregate_sha:
                side.note(
                    f"aggregate source_sha {aggregate_sha} does not match trial "
                    f"source_sha {side.sha}"
                )
            if side.fixture is None:
                side.fixture = aggregate.get("fixture")
            elif aggregate.get("fixture") != side.fixture:
                side.note("aggregate fixture metadata does not match the trial fixture metadata")
            side.environment = dict(aggregate.get("environment") or {})
            if side.trials and isinstance(trials_count, int) and trials_count != len(side.trials):
                side.note(
                    f"aggregate declares {trials_count} trials but {len(side.trials)} "
                    "trial manifest(s) were supplied"
                )

    if not side.environment and qualified_trials:
        side.environment = dict(qualified_trials[0].get("environment") or {})

    side.sha = require_full_sha(side.sha, f"{label}") if side.sha else None
    side.lanes = collect_lanes(side)
    return side


def collect_lanes(side):
    """Median-of-medians per lane, strictly from supplied three-trial medians."""
    if not side.trials:
        return {}
    per_lane = {}
    for path, manifest in side.trials:
        if not isinstance(manifest, dict):
            continue
        lanes = manifest.get("lanes")
        if not isinstance(lanes, list):
            side.note(f"trial {path} has no lanes list")
            continue
        seen = set()
        for lane in lanes:
            if not isinstance(lane, dict) or not isinstance(lane.get("lane_id"), str):
                side.note(f"trial {path} has a malformed lane entry")
                continue
            lane_id = lane["lane_id"]
            if lane_id in seen:
                side.note(f"trial {path} contains duplicate lane {lane_id}")
                continue
            seen.add(lane_id)
            per_lane.setdefault(lane_id, []).append(lane)

    validator = load_validator()
    required = set(validator.REQUIRED_LANES)
    present = set(per_lane)
    missing = sorted(required - present)
    unexpected = sorted(present - required)
    if missing:
        side.note(f"missing {len(missing)} required lane(s): {missing[:3]}")
    if unexpected:
        side.note(f"{len(unexpected)} unexpected lane(s): {unexpected[:3]}")
    if side.aggregate is not None and isinstance(side.aggregate, dict):
        aggregate_lanes = side.aggregate.get("lanes")
        if isinstance(aggregate_lanes, list):
            aggregate_ids = {
                lane.get("lane_id") for lane in aggregate_lanes if isinstance(lane, dict)
            }
            if aggregate_ids != present:
                side.note(
                    "aggregate lane set does not match the lane set of the supplied trials"
                )

    lanes = {}
    trial_count = len(side.trials)
    for lane_id, rows in per_lane.items():
        if len(rows) != trial_count:
            side.note(
                f"{lane_id}: present in {len(rows)} of {trial_count} trial manifest(s)"
            )
        medians = []
        for row in rows:
            value = row.get("median_ns")
            if not is_finite_positive(value):
                side.note(f"{lane_id}: median_ns {value!r} is not finite and positive")
                continue
            medians.append(float(value))
        if len(medians) < MIN_TRIALS:
            side.note(
                f"{lane_id}: only {len(medians)} finite positive trial median(s); "
                f"{MIN_TRIALS} required"
            )
        if side.aggregate is not None and isinstance(side.aggregate, dict):
            declared = next(
                (
                    lane
                    for lane in side.aggregate.get("lanes") or []
                    if isinstance(lane, dict) and lane.get("lane_id") == lane_id
                ),
                None,
            )
            if declared is not None:
                claimed = declared.get("trial_median_ns")
                if not isinstance(claimed, list) or len(claimed) != len(medians):
                    side.note(f"{lane_id}: aggregate trial_median_ns is missing or mis-sized")
                else:
                    for got, want in zip(medians, claimed):
                        if not isinstance(want, (int, float)) or abs(float(want) - got) > 1e-9:
                            side.note(
                                f"{lane_id}: aggregate trial median {want!r} does not "
                                f"match the source trial median {got!r}"
                            )
                            break
        row = rows[0]
        lanes[lane_id] = {
            "lane_id": lane_id,
            "case_id": row.get("case_id"),
            "n": row.get("n"),
            "s": row.get("s"),
            "k": row.get("k"),
            "variant": row.get("variant"),
            "corpus_label": row.get("corpus_label"),
            "trial_median_ns": medians,
            "median_of_medians_ns": statistics.median(medians) if medians else None,
            "dispersion_ratio": (
                (max(medians) / min(medians)) if len(medians) > 1 and min(medians) > 0 else None
            ),
        }
    return lanes


def compare_sides(before, after, expected_before_sha, expected_after_sha):
    """Return (reasons, lanes, groups, environment, fixture)."""
    reasons = list(before.reasons) + list(after.reasons)

    if before.sha is None or after.sha is None:
        reasons.append("a source SHA is missing on at least one side")
    else:
        if before.sha == after.sha:
            reasons.append(f"before and after are the same source SHA {before.sha}")
        if before.sha != expected_before_sha:
            reasons.append(
                f"before source_sha {before.sha} is not the verified pre-PR-15C-A "
                f"revision {expected_before_sha}"
            )
        if after.sha != expected_after_sha:
            reasons.append(
                f"after source_sha {after.sha} is not the measured PR-15C-B commit "
                f"{expected_after_sha}"
            )

    for field in ENVIRONMENT_FIELDS:
        if before.environment.get(field) != after.environment.get(field):
            reasons.append(
                f"host fingerprint mismatch on {field}: "
                f"{before.environment.get(field)!r} vs {after.environment.get(field)!r}"
            )
    for field in TOOLCHAIN_FIELDS:
        if before.toolchain.get(field) != after.toolchain.get(field):
            reasons.append(
                f"toolchain mismatch on {field}: "
                f"{before.toolchain.get(field)!r} vs {after.toolchain.get(field)!r}"
            )

    if before.fixture != after.fixture:
        reasons.append("canonical fixture metadata / corpus digests differ between sides")
    if isinstance(before.fixture, dict) and isinstance(after.fixture, dict):
        if before.fixture.get("canonical_sha256") != after.fixture.get(
            "canonical_sha256"
        ):
            reasons.append("canonical pr15a_v1 fixture digest differs between sides")

    before_ids = set(before.lanes)
    after_ids = set(after.lanes)
    if before_ids != after_ids:
        reasons.append(
            "lane sets differ: missing in after "
            f"{sorted(before_ids - after_ids)[:3]}, extra in after "
            f"{sorted(after_ids - before_ids)[:3]}"
        )

    lanes = []
    for lane_id in before_ids & after_ids:
        left = before.lanes[lane_id]
        right = after.lanes[lane_id]
        for field in ("case_id", "n", "s", "k", "variant", "corpus_label"):
            if left.get(field) != right.get(field):
                reasons.append(
                    f"{lane_id}: {field} differs ({left.get(field)!r} vs {right.get(field)!r})"
                )
        left_mom = left["median_of_medians_ns"]
        right_mom = right["median_of_medians_ns"]
        if left_mom is None or right_mom is None:
            reasons.append(f"{lane_id}: a median-of-medians is missing")
            continue
        speedup = left_mom / right_mom
        delta_pct = 100.0 * (right_mom - left_mom) / left_mom
        dispersions = [
            value
            for value in (left["dispersion_ratio"], right["dispersion_ratio"])
            if value is not None
        ]
        classification, note = classify(
            speedup, delta_pct, dispersions, left["trial_median_ns"], right["trial_median_ns"]
        )
        lanes.append(
            {
                "lane_id": lane_id,
                "case_id": left["case_id"],
                "n": left["n"],
                "s": left["s"],
                "k": left["k"],
                "variant": left["variant"],
                "corpus_label": left["corpus_label"],
                "before_trial_median_ns": left["trial_median_ns"],
                "after_trial_median_ns": right["trial_median_ns"],
                "before_median_of_medians_ns": left_mom,
                "after_median_of_medians_ns": right_mom,
                "before_dispersion_ratio": left["dispersion_ratio"],
                "after_dispersion_ratio": right["dispersion_ratio"],
                "speedup": speedup,
                "delta_pct": delta_pct,
                "classification": classification,
                "classification_note": note,
            }
        )

    lanes.sort(key=lambda lane: lane["lane_id"])
    if len(lanes) != len(set(lane["lane_id"] for lane in lanes)):
        reasons.append("duplicate lane present in the comparison table")

    groups = build_groups(lanes)
    return reasons, lanes, groups, before.environment, before.fixture


def classify(speedup, delta_pct, dispersions, before_medians, after_medians):
    """Predeclared descriptive classification (never a significance claim)."""
    if any(value > NOISE_DISPERSION_RATIO for value in dispersions):
        return (
            "INCONCLUSIVE",
            f"trial-median spread exceeds {NOISE_DISPERSION_RATIO:.2f}x on at least one side",
        )
    if before_medians and after_medians:
        before_low, before_high = min(before_medians), max(before_medians)
        after_low, after_high = min(after_medians), max(after_medians)
        if before_low <= after_high and after_low <= before_high:
            return (
                "INCONCLUSIVE",
                "before and after trial-median ranges overlap",
            )
    if abs(delta_pct) < MIN_INTERPRETABLE_DELTA_PCT:
        return (
            "INCONCLUSIVE",
            f"|delta_pct| < {MIN_INTERPRETABLE_DELTA_PCT:.1f}% effect-size threshold",
        )
    if speedup > 1.0:
        return ("IMPROVEMENT", "after is faster outside the predeclared noise bounds")
    return ("REGRESSION", "after is slower outside the predeclared noise bounds")


def build_groups(lanes):
    groups = []
    for name, case_ids in LANE_GROUPS:
        members = [
            lane
            for lane in lanes
            if isinstance(lane.get("case_id"), str) and lane["case_id"] in case_ids
        ]
        if not members:
            continue
        speedups = [lane["speedup"] for lane in members]
        groups.append(
            {
                "group": name,
                "case_ids": list(case_ids),
                "lane_count": len(members),
                "speedup_median": statistics.median(speedups),
                "speedup_min": min(speedups),
                "speedup_max": max(speedups),
                "lanes": [lane["lane_id"] for lane in members],
                "improvements": sum(1 for lane in members if lane["classification"] == "IMPROVEMENT"),
                "regressions": sum(1 for lane in members if lane["classification"] == "REGRESSION"),
                "inconclusive": sum(
                    1 for lane in members if lane["classification"] == "INCONCLUSIVE"
                ),
            }
        )
    return groups


def build_report(before, after, reasons, lanes, groups, environment, fixture):
    status = "QUALIFIED" if not reasons else "UNQUALIFIED"
    counts = {
        "lanes": len(lanes),
        "improvements": sum(1 for lane in lanes if lane["classification"] == "IMPROVEMENT"),
        "regressions": sum(1 for lane in lanes if lane["classification"] == "REGRESSION"),
        "inconclusive": sum(1 for lane in lanes if lane["classification"] == "INCONCLUSIVE"),
    }
    return {
        "schema": COMPARISON_SCHEMA,
        "status": status,
        "workload_version": WORKLOAD_VERSION,
        "unqualified_reasons": reasons,
        "before": {
            "source_sha": before.sha,
            "aggregate_mode": before.aggregate_mode,
            "trial_run_ids": [
                manifest.get("run_id") for _, manifest in before.trials if isinstance(manifest, dict)
            ],
            "trial_timestamps_utc": [
                manifest.get("timestamp_utc")
                for _, manifest in before.trials
                if isinstance(manifest, dict)
            ],
            "toolchain": before.toolchain,
            "environment": before.environment,
        },
        "after": {
            "source_sha": after.sha,
            "aggregate_mode": after.aggregate_mode,
            "trial_run_ids": [
                manifest.get("run_id") for _, manifest in after.trials if isinstance(manifest, dict)
            ],
            "trial_timestamps_utc": [
                manifest.get("timestamp_utc")
                for _, manifest in after.trials
                if isinstance(manifest, dict)
            ],
            "toolchain": after.toolchain,
            "environment": after.environment,
        },
        "canonical_fixture_sha256": (
            fixture.get("canonical_sha256") if isinstance(fixture, dict) else None
        ),
        "fixture": fixture,
        "counts": counts,
        "groups": groups,
        "lanes": lanes,
        "limitations": LIMITATIONS,
    }


def render_markdown(report):
    status = report["status"]
    lines = [
        f"# PR 15C-B before/after comparison — {status}",
        "",
        f"- Before source SHA: `{report['before']['source_sha']}`",
        f"- After source SHA: `{report['after']['source_sha']}`",
        f"- Workload version: `{report['workload_version']}`",
        f"- Canonical fixture: `{report['canonical_fixture_sha256']}`",
        f"- Before trials: {len(report['before']['trial_run_ids'])} "
        f"({report['before']['aggregate_mode']})",
        f"- After trials: {len(report['after']['trial_run_ids'])} "
        f"({report['after']['aggregate_mode']})",
        "",
    ]
    if status != "QUALIFIED":
        lines += [
            "> **UNQUALIFIED — no speedup claim is made.** Every published comparison",
            "> requires all of the following, and at least one failed:",
            ">",
        ]
        for reason in report["unqualified_reasons"]:
            lines.append(f"> - {reason}")
        lines.append("")
    lines += [
        "`speedup = before_median_of_medians / after_median_of_medians` "
        "(> 1 means the after build is faster). "
        "`delta_pct = 100 * (after - before) / before` (> 0 means a regression).",
        "",
        f"Lane classification counts: {report['counts']['improvements']} improvement, "
        f"{report['counts']['regressions']} regression, "
        f"{report['counts']['inconclusive']} inconclusive "
        f"of {report['counts']['lanes']} lanes.",
        "",
    ]

    if report["groups"]:
        lines += [
            "## Descriptor groups",
            "",
            "Descriptive only. Group figures are the median and range of the visible "
            "per-lane speedups; no cross-lane arithmetic average is computed.",
            "",
            "| group | lanes | speedup median | speedup min | speedup max | impr | regr | inconc |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for group in report["groups"]:
            lines.append(
                "| {} | {} | {:.4f} | {:.4f} | {:.4f} | {} | {} | {} |".format(
                    group["group"],
                    group["lane_count"],
                    group["speedup_median"],
                    group["speedup_min"],
                    group["speedup_max"],
                    group["improvements"],
                    group["regressions"],
                    group["inconclusive"],
                )
            )
        lines.append("")

    lines += [
        "## Lane detail",
        "",
        "Raw three-trial medians are preserved. `INCONCLUSIVE` reflects the "
        "predeclared dispersion/overlap/effect-size heuristics, not a significance test.",
        "",
        "| lane | N | S | K | before trials (ns) | after trials (ns) | before MoM | after MoM | speedup | delta % | classification |",
        "|---|---:|---:|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for lane in report["lanes"]:
        before_trials = ", ".join(f"{value:.1f}" for value in lane["before_trial_median_ns"])
        after_trials = ", ".join(f"{value:.1f}" for value in lane["after_trial_median_ns"])
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} | {:.1f} | {:.1f} | {:.4f} | {:+.2f} | {} |".format(
                lane["lane_id"],
                lane["n"],
                lane["s"],
                lane["k"],
                before_trials,
                after_trials,
                lane["before_median_of_medians_ns"],
                lane["after_median_of_medians_ns"],
                lane["speedup"],
                lane["delta_pct"],
                lane["classification"],
            )
        )
    lines += ["", "## Limitations", ""]
    for limitation in report["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


def build_comparison(before_aggregate, before_trials, after_aggregate, after_trials,
                     expected_before_sha, expected_after_sha):
    before = load_side("before", before_aggregate, before_trials)
    after = load_side("after", after_aggregate, after_trials)
    reasons, lanes, groups, environment, fixture = compare_sides(
        before, after, expected_before_sha, expected_after_sha
    )
    if not lanes:
        fail(
            "no comparable lane could be derived from the supplied artifacts; "
            "refusing to publish a report with invented values: " + "; ".join(reasons[:3])
        )
    return build_report(before, after, reasons, lanes, groups, environment, fixture)


def run_compare(args):
    report = build_comparison(
        args.before,
        args.before_trial or [],
        args.after,
        args.after_trial or [],
        args.expected_before_sha,
        args.expected_after_sha,
    )
    write_json(args.out_json, report)
    if args.out_md:
        Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_md).write_text(render_markdown(report), encoding="utf-8")
    print(
        f"{report['status']}: {args.out_json}: {report['counts']['lanes']} lanes, "
        f"{report['counts']['improvements']} improvement / "
        f"{report['counts']['regressions']} regression / "
        f"{report['counts']['inconclusive']} inconclusive"
    )
    if report["status"] != "QUALIFIED":
        for reason in report["unqualified_reasons"]:
            print(f"  UNQUALIFIED: {reason}", file=sys.stderr)
        return 3
    return 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def _write_side(directory, validator, sha, factor, run_prefix="t"):
    """Write three synthetic qualified trials and their aggregate."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    trials = []
    for index in range(1, 4):
        manifest = validator.synthetic_trial(f"{run_prefix}-{index}", source_sha=sha)
        for lane in manifest["lanes"]:
            lane["median_ns"] *= factor
            lane["estimate_ns"] *= factor
            lane["std_dev_ns"] *= factor
            lane["ci_lower_ns"] *= factor
            lane["ci_upper_ns"] *= factor
        path = directory / f"{run_prefix}-{index}.json"
        write_json(path, manifest)
        trials.append((path, manifest))
    aggregate = validator.aggregate_trials([manifest for _, manifest in trials])
    aggregate_path = directory / "aggregate.json"
    write_json(aggregate_path, aggregate)
    return aggregate_path, [path for path, _ in trials], aggregate


def _expect_unqualified(label, **kwargs):
    try:
        report = build_comparison(
            kwargs.get("before_aggregate"),
            kwargs.get("before_trials") or [],
            kwargs.get("after_aggregate"),
            kwargs.get("after_trials") or [],
            kwargs.get("expected_before_sha", PRE_15C_A_SHA),
            kwargs.get("expected_after_sha", "b" * 40),
        )
    except ComparisonError:
        return "rejected"
    if report["status"] == "QUALIFIED":
        raise AssertionError(f"self-test: {label} was labelled QUALIFIED but must not be")
    return "unqualified"


def _expect_qualified(label, report):
    if report["status"] != "QUALIFIED":
        raise AssertionError(
            f"self-test: {label} should be QUALIFIED, got {report['status']}: "
            f"{report['unqualified_reasons']}"
        )


def self_test():  # noqa: PLR0915 - a fixture matrix is intentionally explicit
    validator = load_validator()
    import tempfile

    before_sha = PRE_15C_A_SHA
    after_sha = "b" * 40

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # Baseline: before 200 ns, after 100 ns => speedup 2.0, delta -50%.
        before_agg, before_trials, _ = _write_side(tmp / "before", validator, before_sha, 200.0 / 990.0)
        after_agg, after_trials, _ = _write_side(tmp / "after", validator, after_sha, 100.0 / 990.0, "u")

        report = build_comparison(before_agg, before_trials, after_agg, after_trials,
                                  before_sha, after_sha)
        _expect_qualified("clean paired fixtures", report)
        assert report["counts"]["lanes"] == len(validator.REQUIRED_LANES)
        for lane in report["lanes"]:
            assert abs(lane["speedup"] - 2.0) < 1e-9, lane
            assert abs(lane["delta_pct"] + 50.0) < 1e-9, lane
            assert lane["classification"] == "IMPROVEMENT", lane
            assert len(lane["before_trial_median_ns"]) == 3
            assert len(lane["after_trial_median_ns"]) == 3
        assert len(report["groups"]) == len(LANE_GROUPS)
        assert all(abs(group["speedup_median"] - 2.0) < 1e-9 for group in report["groups"])
        markdown = render_markdown(report)
        assert "QUALIFIED" in markdown
        assert "| `pr15b_v1/u01/n2000_s4/k100/absent` |" in markdown

        # Equal builds => INCONCLUSIVE, never a claimed improvement.
        equal_before_agg, equal_before_trials, _ = _write_side(
            tmp / "equal-before", validator, before_sha, 100.0 / 990.0, "eb"
        )
        equal_agg, equal_trials, _ = _write_side(
            tmp / "equal", validator, after_sha, 100.0 / 990.0, "e"
        )
        equal_report = build_comparison(
            equal_before_agg, equal_before_trials, equal_agg, equal_trials, before_sha, after_sha
        )
        _expect_qualified("equal paired fixtures", equal_report)
        assert equal_report["counts"]["improvements"] == 0
        assert equal_report["counts"]["regressions"] == 0
        assert equal_report["counts"]["inconclusive"] == len(validator.REQUIRED_LANES)

        # ---- rejection classes -------------------------------------------
        results = {}

        # Missing aggregate + no trials at all.
        results["historical-only aggregate without trial files"] = _expect_unqualified(
            "historical-only",
            before_aggregate=before_agg,
            after_aggregate=after_agg,
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # Missing lane in the after trials and aggregate.
        missing_dir = tmp / "missing"
        missing_dir.mkdir()
        missing_trials = []
        for index, (path, manifest) in enumerate(
            zip(after_trials, [read_json(p) for p in after_trials]), start=1
        ):
            manifest["lanes"] = manifest["lanes"][:-1]
            new_path = missing_dir / f"t{index}.json"
            write_json(new_path, manifest)
            missing_trials.append(new_path)
        missing_agg = missing_dir / "aggregate.json"
        # The frozen aggregator legitimately refuses a lane-incomplete trial, so the
        # tampered trials are compared against the untampered aggregate here.
        write_json(missing_agg, read_json(after_agg))
        results["missing lane"] = _expect_unqualified(
            "missing lane",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=missing_agg,
            after_trials=missing_trials,
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # Duplicate lane.
        dup_dir = tmp / "dup"
        dup_dir.mkdir()
        dup_trials = []
        for index, path in enumerate(after_trials, start=1):
            manifest = read_json(path)
            manifest["lanes"].append(json.loads(json.dumps(manifest["lanes"][0])))
            new_path = dup_dir / f"t{index}.json"
            write_json(new_path, manifest)
            dup_trials.append(new_path)
        results["duplicate lane"] = _expect_unqualified(
            "duplicate lane",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=None,
            after_trials=dup_trials,
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # Wrong after SHA (not the measured commit).
        results["wrong after SHA"] = _expect_unqualified(
            "wrong sha",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=after_agg,
            after_trials=after_trials,
            expected_before_sha=before_sha,
            expected_after_sha="c" * 40,
        )

        # Wrong before SHA (not the verified pre-15C-A revision).
        results["wrong before SHA"] = _expect_unqualified(
            "wrong pre sha",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=after_agg,
            after_trials=after_trials,
            expected_before_sha="d" * 40,
            expected_after_sha=after_sha,
        )

        # Identical before/after SHA.
        same_agg, same_trials, _ = _write_side(
            tmp / "same", validator, before_sha, 100.0 / 990.0, "s"
        )
        results["identical before/after SHA"] = _expect_unqualified(
            "same sha",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=same_agg,
            after_trials=same_trials,
            expected_before_sha=before_sha,
            expected_after_sha=before_sha,
        )

        # Wrong host fingerprint.
        host_dir = tmp / "host"
        host_dir.mkdir()
        host_trials = []
        for index, path in enumerate(after_trials, start=1):
            manifest = read_json(path)
            manifest["environment"]["cpu_model"] = "some other cpu"
            new_path = host_dir / f"t{index}.json"
            write_json(new_path, manifest)
            host_trials.append(new_path)
        host_agg = host_dir / "aggregate.json"
        write_json(host_agg, validator.aggregate_trials([read_json(p) for p in host_trials]))
        results["wrong host fingerprint"] = _expect_unqualified(
            "wrong host",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=host_agg,
            after_trials=host_trials,
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # Missing trial (only two manifests for a three-trial aggregate).
        results["missing trial manifest"] = _expect_unqualified(
            "missing trial",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=after_agg,
            after_trials=after_trials[:2],
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # Mismatched corpus digest.
        corpus_dir = tmp / "corpus"
        corpus_dir.mkdir()
        corpus_trials = []
        for index, path in enumerate(after_trials, start=1):
            manifest = read_json(path)
            manifest["fixture"]["corpora"][0]["corpus_sha256"] = "c" * 64
            new_path = corpus_dir / f"t{index}.json"
            write_json(new_path, manifest)
            corpus_trials.append(new_path)
        corpus_agg = corpus_dir / "aggregate.json"
        # Keep the untampered aggregate so the mismatch is caught by the cross-check.
        write_json(corpus_agg, read_json(after_agg))
        results["mismatched corpus digest"] = _expect_unqualified(
            "corpus mismatch",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=corpus_agg,
            after_trials=corpus_trials,
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # Corrupted oracle gate.
        oracle_dir = tmp / "oracle"
        oracle_dir.mkdir()
        oracle_trials = []
        for index, path in enumerate(after_trials, start=1):
            manifest = read_json(path)
            manifest["fixture"]["oracle_gate"] = "FAIL"
            new_path = oracle_dir / f"t{index}.json"
            write_json(new_path, manifest)
            oracle_trials.append(new_path)
        results["corrupted oracle gate"] = _expect_unqualified(
            "oracle",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=after_agg,
            after_trials=oracle_trials,
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # NaN latency written as a bare JSON constant (not JSON-spec compliant).
        nan_dir = tmp / "nan"
        nan_dir.mkdir()
        nan_trials = []
        for index, path in enumerate(after_trials, start=1):
            manifest = read_json(path)
            manifest["lanes"][0]["median_ns"] = float("nan")
            new_path = nan_dir / f"t{index}.json"
            with open(new_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, indent=2, sort_keys=True, allow_nan=True)
            nan_trials.append(new_path)
        results["NaN latency"] = _expect_unqualified(
            "nan",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=None,
            after_trials=nan_trials,
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # Infinity latency.
        inf_dir = tmp / "inf"
        inf_dir.mkdir()
        inf_trials = []
        for index, path in enumerate(after_trials, start=1):
            manifest = read_json(path)
            manifest["lanes"][1]["median_ns"] = float("inf")
            new_path = inf_dir / f"t{index}.json"
            with open(new_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, indent=2, sort_keys=True, allow_nan=True)
            inf_trials.append(new_path)
        results["Infinity latency"] = _expect_unqualified(
            "inf",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=None,
            after_trials=inf_trials,
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # Nonpositive latency.
        zero_dir = tmp / "zero"
        zero_dir.mkdir()
        zero_trials = []
        for index, path in enumerate(after_trials, start=1):
            manifest = read_json(path)
            manifest["lanes"][2]["median_ns"] = 0.0
            new_path = zero_dir / f"t{index}.json"
            write_json(new_path, manifest)
            zero_trials.append(new_path)
        results["nonpositive latency"] = _expect_unqualified(
            "zero",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=None,
            after_trials=zero_trials,
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # Unqualified aggregate flag.
        flagged = read_json(after_agg)
        flagged["qualified"] = False
        flagged_path = tmp / "flagged.json"
        write_json(flagged_path, flagged)
        results["unqualified aggregate"] = _expect_unqualified(
            "flagged",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=flagged_path,
            after_trials=after_trials,
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # Fewer than three trials.
        results["fewer than three trials"] = _expect_unqualified(
            "two trials",
            before_aggregate=before_agg,
            before_trials=before_trials[:2],
            after_aggregate=after_agg,
            after_trials=after_trials[:2],
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # Aggregate declares a trial median that the trials do not contain.
        tampered = read_json(after_agg)
        tampered["lanes"][0]["trial_median_ns"] = [1.0, 1.0, 1.0]
        tampered_path = tmp / "tampered.json"
        write_json(tampered_path, tampered)
        results["tampered aggregate median"] = _expect_unqualified(
            "tampered",
            before_aggregate=before_agg,
            before_trials=before_trials,
            after_aggregate=tampered_path,
            after_trials=after_trials,
            expected_before_sha=before_sha,
            expected_after_sha=after_sha,
        )

        # A regression must be reported, not silently failed or hidden.
        slower_agg, slower_trials, _ = _write_side(
            tmp / "slower", validator, after_sha, 400.0 / 990.0, "r"
        )
        slower = build_comparison(before_agg, before_trials, slower_agg, slower_trials,
                                  before_sha, after_sha)
        _expect_qualified("regression fixtures are still qualified", slower)
        assert slower["counts"]["regressions"] == len(validator.REQUIRED_LANES)
        assert all(abs(lane["delta_pct"] - 100.0) < 1e-9 for lane in slower["lanes"])
        assert all(lane["classification"] == "REGRESSION" for lane in slower["lanes"])

        # Noisy overlap => INCONCLUSIVE even with a large nominal ratio.
        noisy_agg, noisy_trials, _ = _write_side(
            tmp / "noisy", validator, after_sha, 100.0 / 990.0, "n"
        )
        noisy_manifests = []
        for path in noisy_trials:
            manifest = read_json(path)
            for index, lane in enumerate(manifest["lanes"]):
                scale = 1.0 + 0.30 * ((index + int(path.stem[-1])) % 3)
                lane["median_ns"] *= scale
                lane["estimate_ns"] *= scale
                lane["ci_lower_ns"] *= scale
                lane["ci_upper_ns"] *= scale
            write_json(path, manifest)
            noisy_manifests.append(manifest)
        write_json(noisy_agg, validator.aggregate_trials(noisy_manifests))
        noisy = build_comparison(before_agg, before_trials, noisy_agg, noisy_trials,
                                 before_sha, after_sha)
        assert noisy["counts"]["inconclusive"] > 0
        assert noisy["counts"]["improvements"] < len(validator.REQUIRED_LANES)

        print("COMPARATOR SELF-TEST OK")
        for label, outcome in sorted(results.items()):
            print(f"  rejected-class: {label}: {outcome}")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Compare qualified PR 15B before/after aggregates for PR 15C-B."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare = subparsers.add_parser(
        "compare", help="compare a before and an after qualified measurement"
    )
    compare.add_argument("--before", help="qualified PR 15B aggregate JSON for the before source")
    compare.add_argument("--after", help="qualified PR 15B aggregate JSON for the after source")
    compare.add_argument(
        "--before-trial",
        action="extend",
        nargs="+",
        help="source trial manifest for the before side (repeatable; required when the "
        "aggregate does not expose qualification facts)",
    )
    compare.add_argument(
        "--after-trial",
        action="extend",
        nargs="+",
        help="source trial manifest for the after side (repeatable)",
    )
    compare.add_argument(
        "--expected-before-sha",
        default=PRE_15C_A_SHA,
        help=f"verified pre-PR-15C-A source SHA (default: {PRE_15C_A_SHA})",
    )
    compare.add_argument(
        "--expected-after-sha",
        required=True,
        help="the exact PR 15C-B commit that was measured",
    )
    compare.add_argument("--out-json", required=True)
    compare.add_argument("--out-md")

    subparsers.add_parser("self-test", help="run the rejection-class and ratio self-test")

    args = parser.parse_args()
    try:
        if args.command == "compare":
            return run_compare(args)
        return self_test()
    except ComparisonError as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
