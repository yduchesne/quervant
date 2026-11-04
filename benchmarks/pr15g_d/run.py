#!/usr/bin/env python3
"""PR 15G-D retained-compiled-exact-term benchmark runner.

This runner measures exactly one engine (the frozen PR15D Quervant adapter) on
the existing nine frozen warm lanes:

* 10K  {absent, rare, medium, common} / K100
* 100K {absent, rare, medium, common} / K100
* 100K common / K10

It compares one operator-authorized pair of committed source trees: the pinned
shared-branch pre-C baseline ``ARM_A_SHA`` and a committed descendant containing
the C fused sorted single-term streaming. All corpus, adapter, oracle and
statistical semantics come from the frozen, read-only PR15D / PR15E-B1 modules;
this file supplies stage identity, strict source pinning, output isolation and a
privacy-sanitized comparison report.

Usage (never invoke ``--idle-confirmed`` without a real operator attestation)::

    python3 benchmarks/pr15g_d/run.py \\
      --source-tree /abs/clean/git/worktree \\
      --out /abs/checkout/target/pr15g-d/qualified-pair-01 \\
      --idle-confirmed

Without ``--idle-confirmed`` the runner exits 3 with ``PERF_BLOCKED_OPERATOR``
before creating any index or starting any benchmark subprocess. It never
fabricates authorization and never resumes a partial run.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import os
import sys

TOOLING_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
TARGETED_PATH = os.path.join(
    TOOLING_ROOT, "benchmarks", "pr15e_b1", "run_targeted.py"
)

# Load the frozen PR15E-B1 runner under a distinct module name. It imports the
# frozen PR15D harness/oracle itself; this runner must not modify those modules.
_spec = importlib.util.spec_from_file_location(
    "pr15e_b1_run_targeted_readonly", TARGETED_PATH
)
if _spec is None or _spec.loader is None:  # pragma: no cover - import failure
    raise ImportError(f"cannot load frozen PR15E-B1 runner from {TARGETED_PATH}")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

SCHEMA_SOURCE = "pr15g-d-source-v1"
SCHEMA_COMPARISON = "pr15g-d-comparison-v1"
SCHEMA_SETUP = "pr15g-d-setup-v1"
STAGE = "g_d"
PHASE = "compiled-exact-term"
ARM_A_SHA = "ca065a212987284144d8901aa5c54de093d6dbfc"
ARM_A_LABEL = "D_BASE (post-C-rollback accepted B)"
ARM_B_LABEL = "D candidate"
TRIALS = 3
REGIME = "warm"
EXPERIMENTS = ("d1", "d2")

# The single approved lane matrix, in fixed order. It must be exactly the
# frozen PR15E-B1 ``final`` stage; nothing may be added or dropped.
LANE_IDS = [
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/10000/medium/k100",
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/medium/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
]

FORBIDDEN_REPORT_NAMES = (
    "summary.json",
    "setup.json",
    "trial-",
    "build.log",
    "idle-confirmation",
    "operator",
    "idle-confirmed",
    "corpus/",
    "target/pr15g-d",
    "/home/",
    "/mnt/",
    "/tmp/",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_run_id() -> str:
    """UTC microsecond identifier; collisions are rejected, never overwritten."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def validate_out_path(out: str) -> str:
    """Accept only a fresh stage root strictly beneath this checkout's target."""
    if not os.path.isabs(out):
        raise base.pr15d_run.RunBlocked("X19_PATH_ESCAPE", f"--out must be absolute: {out!r}")
    allowed = os.path.realpath(os.path.join(TOOLING_ROOT, "target", "pr15g-d"))
    candidate = os.path.realpath(out)
    try:
        within = os.path.commonpath([candidate, allowed]) == allowed
    except ValueError:
        within = False
    if not within or candidate == allowed:
        raise base.pr15d_run.RunBlocked(
            "X19_PATH_ESCAPE",
            f"--out must be strictly beneath {allowed} (got {candidate})",
        )
    return candidate


def allocate_run_dir(stage_root: str, source_sha: str, run_id: str | None = None) -> str:
    """Create an exclusive, never-overwritten ``runs/<sha>/<utc>`` directory."""
    run_id = run_id or utc_run_id()
    run_dir = os.path.join(stage_root, "runs", source_sha, run_id)
    try:
        os.makedirs(run_dir, exist_ok=False)
    except FileExistsError as error:
        raise base.pr15d_run.RunBlocked(
            "X39_RUN_DIR", f"run directory already exists: {run_dir}"
        ) from error
    return run_dir


def stage_lanes() -> list[dict]:
    """Resolve the frozen nine-lane warm matrix and reject any drift."""
    lanes = base.stage_lanes("final")
    if [lane["id"] for lane in lanes] != LANE_IDS:
        raise base.pr15d_run.RunBlocked(
            "X32_STAGE", "the frozen PR15D final lane set no longer matches PR 15G-D"
        )
    if any(lane["regime"] != REGIME for lane in lanes):
        raise base.pr15d_run.RunBlocked("X32_STAGE", "every PR 15G-D lane must be warm")
    return lanes


def verify_frozen_inputs(tree: str) -> None:
    """Refuse a source tree whose frozen measurement inputs have drifted."""
    base.verify_frozen_files(tree)


def source_arm(source: dict) -> str:
    """Classify one clean source tree as pinned arm A or a descendant arm B."""
    if source["sha"] == ARM_A_SHA:
        return "A"
    try:
        descendant = base.is_ancestor(source["tree"], ARM_A_SHA)
    except base.pr15d_run.RunBlocked as error:
        # An unknown ancestor is a source-pin refusal, not a generic git error.
        if error.rule == "X27_SOURCE":
            descendant = False
        else:  # pragma: no cover - defensive
            raise
    if descendant:
        return "B"
    raise base.pr15d_run.RunBlocked(
        "X41_SOURCE_PIN",
        f"source {source['sha']} is neither the pinned baseline {ARM_A_SHA} "
        "nor a committed descendant of it",
    )


def authorization_blocked(args) -> bool:
    """True when no genuine operator idle confirmation was supplied."""
    return not args.idle_confirmed


# ---------------------------------------------------------------------------
# Privacy-sanitized publication
# ---------------------------------------------------------------------------


def assert_report_sanitized(report) -> None:
    """Fail closed on report content that could leak local/session material."""
    markers = list(FORBIDDEN_REPORT_NAMES)
    try:
        host = os.uname().nodename
    except AttributeError:  # pragma: no cover - non-POSIX
        host = ""
    if host:
        markers.append(host)
    try:
        import getpass

        user = getpass.getuser()
    except Exception:  # pragma: no cover - environment without a user
        user = ""
    if user:
        markers.append(user)
    markers.append(TOOLING_ROOT)
    markers.append(os.path.expanduser("~"))
    for value in _walk_strings(report):
        lowered = value.lower()
        for marker in markers:
            if marker and marker.lower() in lowered:
                raise base.pr15d_run.RunBlocked(
                    "X42_SENSITIVE_REPORT",
                    "comparison report contains local or session-specific material",
                )
        if value.startswith("/") or value.startswith("\\"):
            raise base.pr15d_run.RunBlocked(
                "X42_SENSITIVE_REPORT", "comparison report contains an absolute path"
            )


def _walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def sanitize_comparison(comparison: dict) -> dict:
    """Keep only source-bound, aggregate measurement facts."""
    sanitized = {
        "schema": SCHEMA_COMPARISON,
        "phase": PHASE,
        "stage": STAGE,
        "experiment": comparison["experiment"],
        "arm_a": {
            "label": comparison["arm_a"]["label"],
            "source_sha": comparison["arm_a"]["source_sha"],
            "tooling_sha": comparison["arm_a"]["tooling_sha"],
            "binary_sha256": comparison["arm_a"]["binary_sha256"],
        },
        "arm_b": {
            "label": comparison["arm_b"]["label"],
            "source_sha": comparison["arm_b"]["source_sha"],
            "tooling_sha": comparison["arm_b"]["tooling_sha"],
            "binary_sha256": comparison["arm_b"]["binary_sha256"],
        },
        "corpus_manifest_sha256": comparison["corpus_manifest_sha256"],
        "lanes": [
            {
                "id": lane["id"],
                "n": lane["n"],
                "class": lane["class"],
                "k": lane["k"],
                "regime": lane["regime"],
                "a_median_of_medians_ns": lane["a_median_of_medians_ns"],
                "b_median_of_medians_ns": lane["b_median_of_medians_ns"],
                "median_ratio": lane["median_ratio"],
                "paired_trial_ratios": lane["paired_trial_ratios"],
                "verdict": lane["verdict"],
                "a_total_hits": lane["a_total_hits"],
                "b_total_hits": lane["b_total_hits"],
            }
            for lane in comparison["lanes"]
        ],
        "experiment": comparison["experiment"],
        "gd_p_gates": comparison["gd_p_gates"],
        "trial_qualification": comparison["trial_qualification"],
        "verdict_rule": comparison["verdict_rule"],
        "limitations": comparison["limitations"],
    }
    assert_report_sanitized(sanitized)
    return sanitized


def render_comparison_markdown(comparison: dict) -> str:
    lines = [
        "# PR 15G-D compiled exact-term specialization — Quervant-only comparison",
        "",
        f"- arm A (**{comparison['arm_a']['label']}**): `{comparison['arm_a']['source_sha']}`",
        f"- arm B (**{comparison['arm_b']['label']}**): `{comparison['arm_b']['source_sha']}`",
        "- verdict rule: " + comparison["verdict_rule"],
        "",
        "| lane | A median (ns) | B median (ns) | ratio B/A | paired trial ratios | verdict |",
        "|---|---:|---:|---:|---|---|",
    ]
    for lane in comparison["lanes"]:
        paired = ", ".join(f"{ratio:.3f}" for ratio in lane["paired_trial_ratios"])
        lines.append(
            f"| `{lane['id']}` | {lane['a_median_of_medians_ns']} | "
            f"{lane['b_median_of_medians_ns']} | {lane['median_ratio']:.3f} | "
            f"{paired} | {lane['verdict']} |"
        )
    lines.append("")
    gates = comparison.get("gd_p_gates", {})
    lines.append(
        "GB gates: "
        + ", ".join(f"{key}={value}" for key, value in gates.items())
    )
    lines.append("")
    lines.append("Limitations:")
    for limitation in comparison["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _require(problems: list[dict], condition: bool, code: str, detail: str) -> None:
    if not condition:
        problems.append({"code": code, "detail": detail})


def _validate_arm_shape(summary: dict, label: str) -> list[dict]:
    problems: list[dict] = []
    _require(problems, summary.get("schema") == SCHEMA_SOURCE, "schema", f"arm {label} schema")
    _require(problems, summary.get("stage") == STAGE, "stage", f"arm {label} stage")
    _require(problems, summary.get("phase") == PHASE, "phase", f"arm {label} phase")
    _require(
        problems,
        [lane.get("id") for lane in summary.get("lanes", [])] == LANE_IDS,
        "lanes",
        f"arm {label} lane set",
    )
    _require(
        problems,
        len(summary.get("trials", [])) == TRIALS,
        "trials",
        f"arm {label} must have exactly {TRIALS} trials",
    )
    seconds = base.pr15d_run.MEASURED
    for lane in summary.get("lanes", []):
        samples = lane.get("samples_ns", [])
        _require(
            problems,
            len(samples) == TRIALS and all(len(series) == seconds for series in samples),
            "samples",
            f"arm {label} lane {lane.get('id')} must have {TRIALS} x {seconds} samples",
        )
    for trial in summary.get("trials", []):
        _require(
            problems,
            trial.get("contention_before") == "clear"
            and trial.get("contention_after") == "clear",
            "contention",
            f"arm {label} trial {trial.get('index')} contention is not clear",
        )
    return problems


def gd_gate_verdicts(experiment: str, lanes: list[dict]) -> dict:
    """Derive the binding GD-P gates for the selected D experiment."""
    by_id = {lane["id"]: lane for lane in lanes}
    if experiment == "d1":
        p01 = by_id.get("pr15d_v1/100000/absent/k100", {}).get("verdict") == "B_FASTER"
        p02 = all(lane["verdict"] != "A_FASTER" for lane in lanes if lane["id"] != "pr15d_v1/100000/absent/k100")
        p03 = True
        p04 = True
    elif experiment == "d2":
        medium = by_id.get("pr15d_v1/100000/medium/k100", {}).get("verdict") == "B_FASTER"
        common = by_id.get("pr15d_v1/100000/common/k100", {}).get("verdict") == "B_FASTER"
        p01 = True
        p02 = True
        p03 = medium or common
        winner = (
            "pr15d_v1/100000/medium/k100"
            if medium
            else "pr15d_v1/100000/common/k100"
        )
        p04 = all(
            lane["verdict"] != "A_FASTER"
            for lane in lanes
            if lane["id"] != winner or True
        )
    else:
        raise base.pr15d_run.RunBlocked("X32_EXPERIMENT", f"unknown experiment {experiment!r}")
    p05 = bool(lanes) and all(
        lane["a_total_hits"] == lane["b_total_hits"]
        and lane.get("a_median_of_medians_ns") is not None
        and lane.get("b_median_of_medians_ns") is not None
        for lane in lanes
    )
    return {
        "experiment": experiment,
        "GD-P01": "PASS" if p01 else "FAIL",
        "GD-P02": "PASS" if p02 else "FAIL",
        "GD-P03": "PASS" if p03 else "FAIL",
        "GD-P04": "PASS" if p04 else "FAIL",
        "GD-P05": "PASS" if p05 else "FAIL",
        "overall": "PASS" if all((p01, p02, p03, p04, p05)) else "FAIL",
    }

def compare_summaries(summary_a: dict, summary_b: dict) -> dict:
    """Compare the pinned baseline and one committed descendant; fail closed."""
    problems = _validate_arm_shape(summary_a, "A") + _validate_arm_shape(summary_b, "B")
    _require(problems, summary_a.get("experiment") == summary_b.get("experiment"), "experiment", "experiment differs between arms")
    _require(problems, summary_a.get("experiment") in EXPERIMENTS, "experiment", "unknown experiment")
    _require(problems, summary_a.get("source_sha") == ARM_A_SHA, "pin", "arm A is not the pinned baseline")
    _require(problems, summary_a.get("arm_role") == "A", "pin", "arm A role is not A")
    _require(problems, summary_b.get("arm_role") == "B", "pin", "arm B role is not B")
    _require(
        problems,
        summary_b.get("is_descendant_of_baseline") is True,
        "pin",
        "arm B is not a committed descendant of the pinned baseline",
    )
    _require(
        problems,
        summary_a.get("source_sha") != summary_b.get("source_sha"),
        "source",
        "both arms measured the same source SHA",
    )
    _require(
        problems,
        summary_a.get("corpus_manifest_sha256") == summary_b.get("corpus_manifest_sha256"),
        "corpus",
        "corpus manifest SHA differs",
    )
    _require(
        problems,
        summary_a.get("environment_fingerprint") == summary_b.get("environment_fingerprint"),
        "host",
        "host fingerprint differs; samples from different hosts are never compared",
    )
    for lane_a, lane_b in zip(summary_a.get("lanes", []), summary_b.get("lanes", []), strict=False):
        _require(
            problems,
            lane_a.get("total_hits") == lane_b.get("total_hits"),
            "oracle",
            f"lane {lane_a.get('id')} oracle hit count differs between arms",
        )
    if problems:
        raise base.pr15d_run.RunBlocked("X37_INCOMPARABLE", f"refusing to compare: {problems}")

    lanes = []
    for lane_a, lane_b in zip(summary_a["lanes"], summary_b["lanes"], strict=True):
        ratios = [
            b / a
            for a, b in zip(
                lane_a["trial_medians_ns"], lane_b["trial_medians_ns"], strict=True
            )
        ]
        lanes.append(
            {
                "id": lane_a["id"],
                "n": lane_a["n"],
                "class": lane_a["class"],
                "k": lane_a["k"],
                "regime": lane_a["regime"],
                "a_median_of_medians_ns": lane_a["median_of_medians_ns"],
                "b_median_of_medians_ns": lane_b["median_of_medians_ns"],
                "median_ratio": lane_b["median_of_medians_ns"]
                / lane_a["median_of_medians_ns"],
                "paired_trial_ratios": ratios,
                "verdict": base.lane_verdict(ratios),
                "a_total_hits": lane_a["total_hits"],
                "b_total_hits": lane_b["total_hits"],
            }
        )
    return {
        "schema": SCHEMA_COMPARISON,
        "phase": PHASE,
        "stage": STAGE,
        "experiment": summary_a["experiment"],
        "arm_a": {
            "label": ARM_A_LABEL,
            "source_sha": summary_a["source_sha"],
            "tooling_sha": summary_a["tooling_sha"],
            "binary_sha256": summary_a["binary_sha256"],
        },
        "arm_b": {
            "label": ARM_B_LABEL,
            "source_sha": summary_b["source_sha"],
            "tooling_sha": summary_b["tooling_sha"],
            "binary_sha256": summary_b["binary_sha256"],
        },
        "corpus_manifest_sha256": summary_a["corpus_manifest_sha256"],
        "lanes": lanes,
        "gd_p_gates": gd_gate_verdicts(summary_a["experiment"], lanes),
        "trial_qualification": [
            {
                "index": trial["index"],
                "contention_before": trial["contention_before"],
                "contention_after": trial["contention_after"],
            }
            for trial in summary_a["trials"] + summary_b["trials"]
        ],
        "verdict_rule": (
            "B_FASTER only if every paired trial ratio is < 1.0; A_FASTER only if "
            "every paired trial ratio is > 1.0; otherwise INCONCLUSIVE. No speedup "
            "threshold is asserted."
        ),
        "limitations": [
            "in-process adapter samples include JSON transport but exclude build and index creation",
            "trial pairing is by trial index on one host; medians are not pooled across hosts",
            "reported ratios are wall-clock engine_ns only; CPU/allocations are not measured here",
            "no index byte-size or reopen-time improvement is claimed by this comparison",
        ],
    }


def collect_summaries(stage_root: str) -> list[dict]:
    runs_root = os.path.join(stage_root, "runs")
    summaries = []
    if not os.path.isdir(runs_root):
        return summaries
    for source_sha in sorted(os.listdir(runs_root)):
        source_dir = os.path.join(runs_root, source_sha)
        if not os.path.isdir(source_dir):
            continue
        for run_id in sorted(os.listdir(source_dir)):
            path = os.path.join(source_dir, run_id, "summary.json")
            if os.path.isfile(path):
                summaries.append(base.pr15d_run.read_json(path))
    return summaries


def publish_comparison(stage_root: str, summaries: list[dict]) -> dict | None:
    if len(summaries) < 2:
        return None
    if len(summaries) > 2:
        raise base.pr15d_run.RunBlocked(
            "X38_EXTRA_ARMS",
            f"{stage_root} holds {len(summaries)} source runs; exactly two are comparable",
        )
    ordered = sorted(summaries, key=lambda summary: summary["arm_role"])
    comparison = sanitize_comparison(compare_summaries(ordered[0], ordered[1]))
    json_path = os.path.join(stage_root, "comparison.json")
    md_path = os.path.join(stage_root, "comparison.md")
    if os.path.exists(json_path) or os.path.exists(md_path):
        raise base.pr15d_run.RunBlocked(
            "X43_REPORT_IMMUTABLE", "a comparison report already exists in this stage root"
        )
    base.pr15d_run.write_json(json_path, comparison)
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(render_comparison_markdown(comparison))
    return comparison


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def execute(args) -> int:
    if authorization_blocked(args):
        print(
            "PERF_BLOCKED_OPERATOR: a real operator idle confirmation is required "
            "(--idle-confirmed); this runner never synthesizes one and no timing "
            "was performed.",
            file=sys.stderr,
        )
        return 3
    stage_root = validate_out_path(args.out)
    source = base.resolve_source_tree(args.source_tree)
    role = source_arm(source)
    verify_frozen_inputs(TOOLING_ROOT)
    verify_frozen_inputs(source["tree"])
    filesystem = base.require_native_filesystem(
        stage_root if os.path.isdir(stage_root) else TOOLING_ROOT
    )
    lanes = stage_lanes()

    run_dir = allocate_run_dir(stage_root, source["sha"])
    base.write_idle_confirmation(run_dir, True)

    environment = base.pr15d_run.collect_environment(run_dir)
    environment["filesystem"] = filesystem
    n_values = sorted({lane["n"] for lane in lanes})
    for n in n_values:
        if n not in base.oracle.N_VALUES:
            raise base.pr15d_run.RunBlocked("X32_STAGE", f"unsupported N={n}")

    build = base.build_adapter(source["tree"], run_dir)
    corpus = base.prepare_corpus(run_dir)
    expected_by_lane = {
        lane["id"]: base.oracle.expected(
            rows=corpus["rows"][lane["n"]],
            field=lane["field"],
            term=lane["term"],
            k=lane["k"],
        )
        for lane in lanes
    }
    adapter_metadata = base.pr15d_run.read_adapter_metadata("quervant", build["binary"])
    indices = base.build_indices(build["binary"], corpus, run_dir, n_values)

    trials = []
    for trial_index in range(1, TRIALS + 1):
        for n, record in indices.items():
            if base.directory_digest(record["dir"]) != record["digest"]:
                raise base.pr15d_run.RunBlocked(
                    "X40_INDEX_MUTATED", f"index n{n} changed between trials"
                )
        trials.append(
            base.measure_trial(
                trial_index,
                build["binary"],
                lanes,
                indices,
                expected_by_lane,
                adapter_metadata,
                run_dir,
            )
        )
        base.pr15d_run.write_json(
            os.path.join(run_dir, f"trial-{trial_index}.json"), trials[-1]
        )

    summary = base.summarize_source(
        STAGE, source, build, corpus, environment, lanes, trials
    )
    summary["schema"] = SCHEMA_SOURCE
    summary["stage"] = STAGE
    summary["phase"] = PHASE
    summary["experiment"] = args.experiment
    summary["arm_role"] = role
    summary["baseline_sha"] = ARM_A_SHA
    summary["is_descendant_of_baseline"] = role == "B" or source["sha"] == ARM_A_SHA
    base.pr15d_run.write_json(os.path.join(run_dir, "summary.json"), summary)
    base.pr15d_run.write_json(
        os.path.join(run_dir, "setup.json"),
        {
            "schema": SCHEMA_SETUP,
            "phase": PHASE,
            "stage": STAGE,
            "experiment": args.experiment,
            "arm_role": role,
            "baseline_sha": ARM_A_SHA,
            "source": source,
            "build": {key: value for key, value in build.items() if key != "binary"},
            "corpus_manifest_sha256": corpus["manifest_sha256"],
            "corpora": corpus["corpora"],
            "lanes": [lane["id"] for lane in lanes],
            "indices": {
                str(n): {"digest": record["digest"], "build": record["build"]}
                for n, record in indices.items()
            },
            "adapter_metadata": adapter_metadata,
            "environment": environment,
            "idle_confirmation": "idle-confirmation.json",
            "run_dir": run_dir,
        },
    )
    comparison = publish_comparison(stage_root, collect_summaries(stage_root))
    print(
        f"PR15G_D SOURCE_SHA={source['sha']} ARM={role} RUN_DIR={run_dir} "
        f"COMPARISON={'yes' if comparison else 'pending-second-arm'}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure one PR 15G-D source tree on the fixed nine warm lanes."
    )
    parser.add_argument(
        "--experiment", required=True, choices=EXPERIMENTS, help="D experiment stage (d1 or d2)"
    )
    parser.add_argument("--source-tree", required=True, help="absolute clean Git worktree")
    parser.add_argument(
        "--out", required=True, help="fresh stage root under <checkout>/target/pr15g-d"
    )
    parser.add_argument(
        "--idle-confirmed",
        action="store_true",
        help="real operator assertion that the host was idle",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return execute(args)
    except base.pr15d_run.RunBlocked as error:
        print(f"PERF_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
