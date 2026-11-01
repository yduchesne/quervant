#!/usr/bin/env python3
"""PR 15E-B1 targeted Quervant-only benchmark runner.

This is deliberately narrow: it measures **one** engine (the frozen PR15D
Quervant adapter) on a small, stage-selected set of PR15D lanes so that the two
approved B1 micro-optimizations can be attributed separately:

* ``b1a``  — original ``main`` vs the B1a commit (direct live-bitmap iteration)
* ``b1b``  — the B1a commit vs the B1b commit (sorted-postings binary search)
* ``final`` — original ``main`` vs the final B1 commit (compact 9-lane control)

It is not a general-purpose benchmark driver, it has no query DSL, and it never
builds, runs or reads the Lucene/Tantivy adapters. All corpus and measurement
semantics come from the frozen, unmodified PR15D modules (``corpus/oracle.py``,
``corpus/generate.py``, ``harness/run.py``); this file only supplies the source
tree to build, the lane subset, trial orchestration and comparison math.

Usage (the runner refuses to time anything without a real operator attestation)::

    python3 benchmarks/pr15e_b1/run_targeted.py \\
      --source-tree /abs/clean/git/worktree \\
      --stage b1a|b1b|final \\
      --out /abs/checkout/target/pr15e-b1/<stage> \\
      --idle-confirmed

``--out`` is the *stage root*; each invocation writes a unique, never-overwritten
run directory ``<out>/runs/<source-sha>/<run-id>/`` and, once two source runs
exist for the stage, ``<out>/comparison.json`` + ``<out>/comparison.md``.

Fail-closed classification: every refusal raises ``run.RunBlocked`` with a rule
code; the CLI exits 3 for a blocked run (``PERF_BLOCKED_*``) and 2 for a
rejected-but-not-blocking validation error. Measurements are never fabricated,
never resumed from a partial run, and never silently downgraded.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone

TOOLING_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, os.path.join(TOOLING_ROOT, "benchmarks/pr15d/harness"))
sys.path.insert(0, os.path.join(TOOLING_ROOT, "benchmarks/pr15d/corpus"))

import run as pr15d_run  # noqa: E402  (frozen PR15D harness helpers)
import oracle  # noqa: E402  (frozen PR15D engine-neutral oracle)
import generate  # noqa: E402  (frozen PR15D corpus generator)

SCHEMA_SOURCE = "pr15e-b1-source-v1"
SCHEMA_COMPARISON = "pr15e-b1-comparison-v1"
SCHEMA_IDLE = "pr15e-b1-idle-confirmation-v1"

STAGES = ("b1a", "b1b", "final")
TRIALS = 3
REGIME = "warm"

# Frozen PR15D artefacts this runner depends on. A drift in any of these means
# the measurement is no longer comparable with the accepted PR15D baseline, so
# the run is refused rather than reinterpreted.
FROZEN_FILES = {
    "benchmarks/pr15d/spec/pr15d_v1.json":
        "ec6c0db865845184ba867fca97add3196bd62a3e88f2cf2c8042a1c594dce466",
    "benchmarks/pr15d/corpus/oracle.py":
        "4c37a72251b6b16e972161070297436c18b96421b09acd2665bce5c65abd20b2",
    "benchmarks/pr15d/corpus/generate.py":
        "d0bfd0ac7f63509f20454dd8ab96dcb50075a5293235fe894b14b60e5b86851d",
    "benchmarks/pr15d/harness/run.py":
        "8be6c21e5a2ac41a3dc12c17ab8bc5e91080c689323f7f05015919c01ff31243",
    "benchmarks/pr15d/adapters/quervant/Cargo.toml":
        "9a25d5c42a04e0bcc00b32d22b0b67e1a7fcf0b921c3de044851235adcaf37f2",
    "benchmarks/pr15d/adapters/quervant/Cargo.lock":
        "050f9d751f978277e02057a0002d1b87d6f0166d73dcadab93f4e78e26cb817d",
    "benchmarks/pr15d/adapters/quervant/src/main.rs":
        "42d2858ec406aa01b2556504a07907e1b2bc9891d596c684b1a9ba99ede78a63",
}

# Fixed stage lane matrix: (n, class, k), always ``regime=warm``.
STAGE_LANES = {
    "b1a": [
        (100000, "absent", 100),
        (100000, "rare", 100),
        (100000, "medium", 100),
        (100000, "common", 100),
        (10000, "absent", 100),
        (10000, "common", 100),
    ],
    "b1b": [
        (100000, "medium", 100),
        (100000, "common", 100),
        (100000, "absent", 100),
        (100000, "rare", 100),
        (10000, "common", 100),
    ],
    "final": [
        (10000, "absent", 100),
        (10000, "rare", 100),
        (10000, "medium", 100),
        (10000, "common", 100),
        (100000, "absent", 100),
        (100000, "rare", 100),
        (100000, "medium", 100),
        (100000, "common", 100),
        (100000, "common", 10),
    ],
}

# Which commit pair each stage attributes (earlier commit = arm A).
STAGE_ARMS = {
    "b1a": ("original main", "B1a"),
    "b1b": ("B1a", "B1b"),
    "final": ("original main", "B1 final"),
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_digest(path: str) -> str:
    """Order-independent content digest of a directory tree."""
    entries = []
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            if os.path.islink(full):
                continue
            relative = os.path.relpath(full, path).replace(os.sep, "/")
            entries.append(f"{relative}\0{os.path.getsize(full)}\0{sha256_file(full)}")
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def git(tree: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", tree, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise pr15d_run.RunBlocked(
            "X27_SOURCE", f"git {' '.join(args)} failed in {tree}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def resolve_source_tree(path: str) -> dict:
    """Validate an absolute, clean, real Git worktree and return its identity."""
    if not os.path.isabs(path):
        raise pr15d_run.RunBlocked("X27_SOURCE", f"--source-tree must be absolute: {path!r}")
    tree = os.path.realpath(path)
    if not os.path.isdir(tree):
        raise pr15d_run.RunBlocked("X27_SOURCE", f"--source-tree does not exist: {path!r}")
    if not os.path.isdir(os.path.join(tree, ".git")) and not os.path.isfile(
        os.path.join(tree, ".git")
    ):
        raise pr15d_run.RunBlocked("X27_SOURCE", f"--source-tree is not a Git worktree: {tree}")
    toplevel = git(tree, "rev-parse", "--show-toplevel")
    if os.path.realpath(toplevel) != tree:
        raise pr15d_run.RunBlocked(
            "X27_SOURCE", f"--source-tree must be the worktree root (got {toplevel})"
        )
    status = git(tree, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise pr15d_run.RunBlocked(
            "X27_SOURCE", f"--source-tree has uncommitted tracked changes:\n{status}"
        )
    sha = git(tree, "rev-parse", "HEAD")
    if len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha):
        raise pr15d_run.RunBlocked("X27_SOURCE", f"unrecognized Git source SHA: {sha!r}")
    commit_time = int(git(tree, "show", "-s", "--format=%ct", "HEAD"))
    return {"tree": tree, "sha": sha, "commit_time": commit_time}


def validate_out_path(out: str) -> str:
    """Accept only a fresh stage root under this checkout's ignored target tree."""
    if not os.path.isabs(out):
        raise pr15d_run.RunBlocked("X19_PATH_ESCAPE", f"--out must be absolute: {out!r}")
    allowed = os.path.realpath(os.path.join(TOOLING_ROOT, "target", "pr15e-b1"))
    candidate = os.path.realpath(out)
    if candidate != allowed and not candidate.startswith(allowed + os.sep):
        raise pr15d_run.RunBlocked(
            "X19_PATH_ESCAPE",
            f"--out must live under the gitignored {allowed} (got {candidate})",
        )
    return candidate


def verify_frozen_files(root: str, files=FROZEN_FILES) -> None:
    for relative, expected in files.items():
        full = os.path.join(root, relative)
        try:
            actual = sha256_file(full)
        except OSError as error:
            raise pr15d_run.RunBlocked(
                "X30_FROZEN_DRIFT", f"{root}: cannot read {relative}: {error}"
            ) from error
        if actual != expected:
            raise pr15d_run.RunBlocked(
                "X30_FROZEN_DRIFT",
                f"{root}: {relative} is {actual}, expected frozen {expected}",
            )


def require_native_filesystem(path: str) -> str:
    filesystem = pr15d_run.filesystem_type(path)
    if filesystem not in pr15d_run.NATIVE_FILESYSTEMS:
        raise pr15d_run.RunBlocked(
            "X31_FILESYSTEM",
            f"{path} is on {filesystem!r}; a native filesystem is required",
        )
    return filesystem


def stage_lanes(stage: str) -> list[dict]:
    """Resolve the fixed stage matrix against the frozen PR15D descriptors."""
    if stage not in STAGE_LANES:
        raise pr15d_run.RunBlocked("X32_STAGE", f"unknown stage {stage!r}")
    frozen = {pr15d_run.lane_key(lane): lane for lane in pr15d_run.lane_descriptors()}
    selected = []
    for n, class_name, k in STAGE_LANES[stage]:
        key = (n, class_name, k, REGIME)
        lane = frozen.get(key)
        if lane is None:
            raise pr15d_run.RunBlocked(
                "X32_STAGE", f"stage {stage} references an unknown frozen lane {key}"
            )
        selected.append(dict(lane))
    if len({lane["id"] for lane in selected}) != len(selected):
        raise pr15d_run.RunBlocked("X32_STAGE", f"stage {stage} selects a duplicate lane")
    return selected


# ---------------------------------------------------------------------------
# Setup (all outside every timed region)
# ---------------------------------------------------------------------------


def build_adapter(source_tree: str, run_dir: str) -> dict:
    manifest = os.path.join(
        source_tree, "benchmarks/pr15d/adapters/quervant/Cargo.toml"
    )
    target_dir = os.path.join(run_dir, "build")
    result = subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            manifest,
            "--target-dir",
            target_dir,
        ],
        cwd=os.path.join(source_tree, "benchmarks/pr15d/adapters/quervant"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        with open(os.path.join(run_dir, "build.log"), "w", encoding="utf-8") as handle:
            handle.write(result.stdout)
        raise pr15d_run.RunBlocked(
            "X33_ADAPTER_BUILD", f"quervant adapter build failed; see {run_dir}/build.log"
        )
    with open(os.path.join(run_dir, "build.log"), "w", encoding="utf-8") as handle:
        handle.write(result.stdout)
    binary = os.path.join(target_dir, "release", "pr15d-quervant-adapter")
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        raise pr15d_run.RunBlocked("X33_ADAPTER_BUILD", f"release adapter missing: {binary}")
    return {
        "binary": binary,
        "binary_sha256": sha256_file(binary),
        "binary_bytes": os.path.getsize(binary),
        "manifest_path": manifest,
        "cargo": subprocess.run(
            ["cargo", "--version"], stdout=subprocess.PIPE, text=True, check=False
        ).stdout.strip(),
    }


def prepare_corpus(run_dir: str) -> dict:
    corpus_dir = os.path.join(run_dir, "corpus")
    summary = generate.generate(corpus_dir)
    manifest, rows = oracle.load_and_verify(corpus_dir)
    return {
        "dir": corpus_dir,
        "rows": rows,
        "manifest": manifest,
        "manifest_sha256": summary["manifest"]["sha256"],
        "corpora": {
            str(entry["n"]): {
                "sha256": entry["sha256"],
                "bytes": entry["bytes"],
                "rows": entry["rows"],
            }
            for entry in manifest["corpora"]
        },
    }


def build_indices(binary: str, corpus: dict, run_dir: str, n_values) -> dict:
    indices = {}
    for n in sorted(set(n_values)):
        index_dir = os.path.join(run_dir, "indexes", f"n{n}")
        record = pr15d_run.build_index(
            "quervant",
            binary,
            os.path.join(corpus["dir"], oracle.corpus_filename(n)),
            index_dir,
            n,
        )
        indices[n] = {
            "dir": index_dir,
            "digest": directory_digest(index_dir),
            "build": record,
        }
    return indices


def write_idle_confirmation(run_dir: str, confirmed: bool) -> dict:
    record = {
        "schema": SCHEMA_IDLE,
        "operator_idle_confirmed": bool(confirmed),
        "host": _hostname(),
        "recorded_utc": utc_now(),
        "statement": (
            "Operator asserted the measurement host was otherwise idle for the "
            "duration of this run. This file records a real operator action via "
            "--idle-confirmed; it is never generated by the coding agent on the "
            "operator's behalf."
        ),
    }
    pr15d_run.write_json(os.path.join(run_dir, "idle-confirmation.json"), record)
    return record


def _hostname() -> str:
    try:
        return os.uname().nodename
    except AttributeError:  # pragma: no cover - non-POSIX
        return "unknown"


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def contention_for(path: str) -> dict:
    """Probe contention, creating the probe's parent directory first.

    The frozen probe writes its JSON to ``--out`` and does not create parents; a
    missing directory would surface as ``unknown``/``probe_failed`` (correctly
    fail-closed, but for the wrong reason). Creating the directory keeps the
    refusal meaningful.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return pr15d_run.check_contention(path)


def _require_clear(contention: dict, label: str) -> None:
    state = contention.get("state")
    if state != "clear":
        raise pr15d_run.RunBlocked(
            "X34_CONTENTION",
            f"{label}: contention state {state!r} is not clear "
            f"(reasons {contention.get('reason_codes')})",
        )


def _adapter_invocation(binary: str, index_dir: str):
    """The frozen PR15D adapter argv shape: binary first, then its flags."""
    return "quervant", [binary, "--index-dir", index_dir]


def check_oracle_untimed(binary: str, index_dir: str, lane: dict, expected: dict) -> None:
    """One independent, untimed oracle response per lane (never timed)."""
    process = pr15d_run.AdapterProcess(*_adapter_invocation(binary, index_dir))
    try:
        response = process.request(
            {
                "request_id": f"{lane['id']}:oracle-check",
                "op": "query",
                "field": lane["field"],
                "term": lane["term"],
                "k": lane["k"],
                "mode": lane["regime"],
            }
        )
    finally:
        process.close()
    pr15d_run.validate_query_response(response, lane, expected)


def measure_trial(
    index: int,
    binary: str,
    lanes: list[dict],
    indices: dict,
    expected_by_lane: dict,
    adapter_metadata: dict,
    run_dir: str,
) -> dict:
    trial_dir = os.path.join(run_dir, "contention")
    before = contention_for(os.path.join(trial_dir, f"trial{index}-before.json"))
    _require_clear(before, f"trial {index} before")
    started = utc_now()
    results = []
    for lane in lanes:
        index_dir = indices[lane["n"]]["dir"]
        expected = expected_by_lane[lane["id"]]
        check_oracle_untimed(binary, index_dir, lane, expected)
        record = pr15d_run.measure_lane(
            "quervant", binary, index_dir, lane, expected, adapter_metadata, before
        )
        results.append(record)
    after = contention_for(os.path.join(trial_dir, f"trial{index}-after.json"))
    _require_clear(after, f"trial {index} after")
    return {
        "index": index,
        "started_utc": started,
        "ended_utc": utc_now(),
        "contention_before": before,
        "contention_after": after,
        "lanes": results,
    }


def summarize_source(
    stage: str,
    source: dict,
    build: dict,
    corpus: dict,
    environment: dict,
    lanes: list[dict],
    trials: list[dict],
) -> dict:
    if len(trials) != TRIALS:
        raise pr15d_run.RunBlocked(
            "X35_TRIAL_COUNT", f"expected {TRIALS} trials, collected {len(trials)}"
        )
    by_lane: dict[str, list[dict]] = {lane["id"]: [] for lane in lanes}
    for trial in trials:
        if sorted(record["id"] for record in trial["lanes"]) != sorted(by_lane):
            raise pr15d_run.RunBlocked("X36_LANE_SET", f"trial {trial['index']} lane set differs")
        for record in trial["lanes"]:
            if len(record["samples_ns"]) != pr15d_run.MEASURED:
                raise pr15d_run.RunBlocked(
                    "X33_SAMPLE_COUNT",
                    f"{record['id']} trial {trial['index']} has "
                    f"{len(record['samples_ns'])} samples",
                )
            if record["oracle_ok"] is not True:
                raise pr15d_run.RunBlocked("X29_ORACLE", f"{record['id']} oracle not ok")
            by_lane[record["id"]].append(record)
    lane_summaries = []
    for lane in lanes:
        records = by_lane[lane["id"]]
        medians = [record["summary_ns"]["median"] for record in records]
        lane_summaries.append(
            {
                "id": lane["id"],
                "n": lane["n"],
                "class": lane["class"],
                "k": lane["k"],
                "regime": lane["regime"],
                "total_hits": records[0]["total_hits"],
                "trial_medians_ns": medians,
                "trial_p95_ns": [record["summary_ns"]["p95"] for record in records],
                "trial_p99_ns": [record["summary_ns"]["p99"] for record in records],
                "median_of_medians_ns": sorted(medians)[len(medians) // 2],
                "dispersion_ns": {"min": min(medians), "max": max(medians)},
                "samples_ns": [record["samples_ns"] for record in records],
            }
        )
    return {
        "schema": SCHEMA_SOURCE,
        "stage": stage,
        "source_sha": source["sha"],
        "source_commit_time": source["commit_time"],
        "tooling_sha": pr15d_run.source_sha(),
        "tooling_root": TOOLING_ROOT,
        "binary_sha256": build["binary_sha256"],
        "binary_bytes": build["binary_bytes"],
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"],
        "environment": environment,
        "environment_fingerprint": pr15d_run.host_fingerprint(environment),
        "lanes": lane_summaries,
        "trials": [
            {
                "index": trial["index"],
                "started_utc": trial["started_utc"],
                "ended_utc": trial["ended_utc"],
                "contention_before": trial["contention_before"]["state"],
                "contention_after": trial["contention_after"]["state"],
            }
            for trial in trials
        ],
        "measured_utc": utc_now(),
    }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _trial_ratios(lane_a: dict, lane_b: dict) -> list[float]:
    return [
        b / a
        for a, b in zip(lane_a["trial_medians_ns"], lane_b["trial_medians_ns"], strict=True)
    ]


def lane_verdict(ratios: list[float]) -> str:
    """Sign-consistency only: no invented speedup threshold."""
    if all(ratio < 1.0 for ratio in ratios):
        return "B_FASTER"
    if all(ratio > 1.0 for ratio in ratios):
        return "A_FASTER"
    return "INCONCLUSIVE"


def compare_summaries(summary_a: dict, summary_b: dict) -> dict:
    """Compare the two source runs of one stage; refuse incomparable data."""
    problems = []

    def require(condition: bool, code: str, detail: str) -> None:
        if not condition:
            problems.append({"code": code, "detail": detail})

    require(summary_a["stage"] == summary_b["stage"], "stage", "stage differs")
    require(
        summary_a["corpus_manifest_sha256"] == summary_b["corpus_manifest_sha256"],
        "corpus",
        "corpus manifest SHA differs",
    )
    require(
        summary_a["environment_fingerprint"] == summary_b["environment_fingerprint"],
        "host",
        "host fingerprint differs; samples from different hosts are never compared",
    )
    require(
        [lane["id"] for lane in summary_a["lanes"]]
        == [lane["id"] for lane in summary_b["lanes"]],
        "lanes",
        "lane set differs",
    )
    require(len(summary_a["trials"]) == TRIALS, "trials", "arm A does not have 3 trials")
    require(len(summary_b["trials"]) == TRIALS, "trials", "arm B does not have 3 trials")
    for summary, label in ((summary_a, "A"), (summary_b, "B")):
        for trial in summary["trials"]:
            require(
                trial["contention_before"] == "clear" and trial["contention_after"] == "clear",
                "contention",
                f"arm {label} trial {trial['index']} contention is not clear",
            )
    require(
        summary_a["source_sha"] != summary_b["source_sha"],
        "source",
        "both arms measured the same source SHA",
    )
    if problems:
        raise pr15d_run.RunBlocked(
            "X37_INCOMPARABLE", f"refusing to compare: {problems}"
        )

    lanes = []
    for lane_a, lane_b in zip(summary_a["lanes"], summary_b["lanes"], strict=True):
        ratios = _trial_ratios(lane_a, lane_b)
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
                "a_trial_medians_ns": lane_a["trial_medians_ns"],
                "b_trial_medians_ns": lane_b["trial_medians_ns"],
                "a_dispersion_ns": lane_a["dispersion_ns"],
                "b_dispersion_ns": lane_b["dispersion_ns"],
                "verdict": lane_verdict(ratios),
                "a_total_hits": lane_a["total_hits"],
                "b_total_hits": lane_b["total_hits"],
            }
        )
    arm_a, arm_b = STAGE_ARMS[summary_a["stage"]]
    return {
        "schema": SCHEMA_COMPARISON,
        "stage": summary_a["stage"],
        "arm_a": {
            "label": arm_a,
            "source_sha": summary_a["source_sha"],
            "tooling_sha": summary_a["tooling_sha"],
            "binary_sha256": summary_a["binary_sha256"],
        },
        "arm_b": {
            "label": arm_b,
            "source_sha": summary_b["source_sha"],
            "tooling_sha": summary_b["tooling_sha"],
            "binary_sha256": summary_b["binary_sha256"],
        },
        "corpus_manifest_sha256": summary_a["corpus_manifest_sha256"],
        "environment_fingerprint": summary_a["environment_fingerprint"],
        "lanes": lanes,
        "verdict_rule": (
            "B_FASTER only if every paired trial ratio is < 1.0; A_FASTER only if "
            "every paired trial ratio is > 1.0; otherwise INCONCLUSIVE. No speedup "
            "threshold is asserted."
        ),
        "limitations": [
            "in-process adapter samples include JSON transport but exclude build and index creation",
            "trial pairing is by trial index on one host; medians are not pooled across hosts",
            "reported ratios are wall-clock engine_ns only; CPU/allocations are not measured here",
        ],
        "compared_utc": utc_now(),
    }


def render_comparison_markdown(comparison: dict) -> str:
    lines = [
        f"# PR 15E-B1 targeted comparison — stage `{comparison['stage']}`",
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
    lines.append("Limitations:")
    for limitation in comparison["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


def publish_comparison(stage_root: str, summaries: list[dict]) -> dict | None:
    """Publish the stage comparison once exactly two source runs exist."""
    if len(summaries) < 2:
        return None
    if len(summaries) > 2:
        raise pr15d_run.RunBlocked(
            "X38_EXTRA_ARMS",
            f"{stage_root} holds {len(summaries)} source runs; exactly two are comparable",
        )
    ordered = sorted(summaries, key=lambda summary: summary["source_commit_time"])
    comparison = compare_summaries(ordered[0], ordered[1])
    pr15d_run.write_json(os.path.join(stage_root, "comparison.json"), comparison)
    with open(
        os.path.join(stage_root, "comparison.md"), "w", encoding="utf-8"
    ) as handle:
        handle.write(render_comparison_markdown(comparison))
    return comparison


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
                summaries.append(pr15d_run.read_json(path))
    return summaries


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def execute(args) -> int:
    if not args.idle_confirmed:
        print(
            "PERF_BLOCKED_OPERATOR: a real operator idle confirmation is required "
            "(--idle-confirmed); this runner never synthesizes one and no timing "
            "was performed.",
            file=sys.stderr,
        )
        return 3
    stage_root = validate_out_path(args.out)
    source = resolve_source_tree(args.source_tree)
    verify_frozen_files(TOOLING_ROOT)
    verify_frozen_files(source["tree"])
    filesystem = require_native_filesystem(stage_root if os.path.isdir(stage_root) else TOOLING_ROOT)
    lanes = stage_lanes(args.stage)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = os.path.join(stage_root, "runs", source["sha"], run_id)
    if os.path.exists(run_dir):
        raise pr15d_run.RunBlocked("X39_RUN_DIR", f"run directory already exists: {run_dir}")
    os.makedirs(run_dir)
    write_idle_confirmation(run_dir, True)

    environment = pr15d_run.collect_environment(run_dir)
    environment["filesystem"] = filesystem
    n_values = sorted({lane["n"] for lane in lanes})
    for n in n_values:
        if n not in oracle.N_VALUES:
            raise pr15d_run.RunBlocked("X32_STAGE", f"stage references unsupported N={n}")

    build = build_adapter(source["tree"], run_dir)
    corpus = prepare_corpus(run_dir)
    expected_by_lane = {
        lane["id"]: oracle.expected(rows=corpus["rows"][lane["n"]], field=lane["field"],
                                    term=lane["term"], k=lane["k"])
        for lane in lanes
    }
    adapter_metadata = pr15d_run.read_adapter_metadata("quervant", build["binary"])
    indices = build_indices(build["binary"], corpus, run_dir, n_values)

    trials = []
    for trial_index in range(1, TRIALS + 1):
        # Immutable index bytes are reused across trials and re-verified each time.
        for n, record in indices.items():
            if directory_digest(record["dir"]) != record["digest"]:
                raise pr15d_run.RunBlocked(
                    "X40_INDEX_MUTATED", f"index n{n} changed between trials"
                )
        trials.append(
            measure_trial(
                trial_index,
                build["binary"],
                lanes,
                indices,
                expected_by_lane,
                adapter_metadata,
                run_dir,
            )
        )
        pr15d_run.write_json(os.path.join(run_dir, f"trial-{trial_index}.json"), trials[-1])

    summary = summarize_source(
        args.stage, source, build, corpus, environment, lanes, trials
    )
    pr15d_run.write_json(os.path.join(run_dir, "summary.json"), summary)
    pr15d_run.write_json(
        os.path.join(run_dir, "setup.json"),
        {
            "schema": "pr15e-b1-setup-v1",
            "stage": args.stage,
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
        f"PR15E_B1_STAGE={args.stage} SOURCE_SHA={source['sha']} "
        f"RUN_DIR={run_dir} COMPARISON={'yes' if comparison else 'pending-second-arm'}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure one PR 15E-B1 source tree on the fixed targeted lanes."
    )
    parser.add_argument("--source-tree", required=True, help="absolute clean Git worktree")
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument(
        "--out", required=True, help="fresh stage root under <checkout>/target/pr15e-b1"
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
    except pr15d_run.RunBlocked as error:
        print(f"PERF_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
