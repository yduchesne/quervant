#!/usr/bin/env python3
"""PR 15H-A targeted Quervant-only benchmark controller.

This runner measures exactly one engine (the frozen PR15D Quervant adapter) on
the seven frozen warm lanes that PR 15H-A is allowed to time:

* P1  100K medium / K100
* P2  100K common / K100
* P3  100K common / K10
* G1   10K common / K100
* G2   10K rare   / K100
* G3  100K rare   / K100
* G4  100K absent / K100

Two subcommands exist and nothing else:

``baseline``  acquired *before* any production Rust edit and sealed immutable;
``paired``    acquired after a candidate correctness pass, using four mirrored
              two-slot A/B blocks against the sealed pre-optimization baseline.

All corpus, adapter, oracle and statistical semantics come from the frozen,
read-only PR15D / PR15E-B1 modules. This file supplies lane selection, source
pinning, output isolation, sealing, qualification and the frozen keep/reject
decision.  It never fabricates timing, never resumes a partial campaign, never
overwrites an existing output and never mixes hosts.

Usage (a real operator idle attestation is mandatory for any timing)::

    python3 benchmarks/pr15h_a/run.py baseline \\
      --checkout-root /ABS/CHECKOUT \\
      --base-tree /ABS/CLEAN/PINNED/MAIN/WORKTREE \\
      --out /ABS/CHECKOUT/target/pr15h-a/baseline-01 \\
      --idle-confirmed

    python3 benchmarks/pr15h_a/run.py paired \\
      --checkout-root /ABS/CHECKOUT \\
      --base-tree /ABS/CLEAN/PINNED/MAIN/WORKTREE \\
      --candidate-tree /ABS/CLEAN/PINNED/CANDIDATE/WORKTREE \\
      --baseline /ABS/CHECKOUT/target/pr15h-a/baseline-01 \\
      --out /ABS/CHECKOUT/target/pr15h-a/paired-01 \\
      --idle-confirmed

``--verify-only`` re-hashes every sealed file, recomputes the sanitized report
from sealed raw data and compares it byte-for-byte without writing anything.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
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
    "pr15e_b1_run_targeted_readonly_15h_a", TARGETED_PATH
)
if _spec is None or _spec.loader is None:  # pragma: no cover - import failure
    raise ImportError(f"cannot load frozen PR15E-B1 runner from {TARGETED_PATH}")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

SCHEMA_AUTHORIZATION = "pr15h-a-authorization-v1"
SCHEMA_MANIFEST = "pr15h-a-manifest-v1"
SCHEMA_BASELINE = "pr15h-a-baseline-v1"
SCHEMA_PERFORMANCE = "pr15h-a-performance-v1"
SCHEMA_BLOCKED = "pr15h-a-blocked-v1"
SCHEMA_SEAL = "pr15h-a-seal-v1"
SCHEMA_SLOT = "pr15h-a-slot-v1"
PHASE = "linear-single-term-candidates"
STAGE = "15h-a"
TRIALS = 3
REGIME = "warm"
SLOTS_PER_ARM = 4
TOTAL_SLOTS = 8
SAMPLES = 20
WARMUPS = 5

# The single approved lane matrix, in fixed order. Nothing may be added,
# dropped, reordered or reclassified after seeing a measurement.
LANE_IDS = [
    "pr15d_v1/100000/medium/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/absent/k100",
]

PRIMARY = {
    "P1": "pr15d_v1/100000/medium/k100",
    "P2": "pr15d_v1/100000/common/k100",
    "P3": "pr15d_v1/100000/common/k10",
}
GUARDS = {
    "G1": "pr15d_v1/10000/common/k100",
    "G2": "pr15d_v1/10000/rare/k100",
    "G3": "pr15d_v1/100000/rare/k100",
    "G4": "pr15d_v1/100000/absent/k100",
}

# Four mirrored blocks: (first arm, second arm).
BLOCK_SCHEDULE = (("A", "B"), ("B", "A"), ("B", "A"), ("A", "B"))

# Cross-session and cross-block drift caps by dataset size.
DRIFT_CAPS = {100000: 1.25, 10000: 1.50}

# Source paths the candidate commit may touch. Content-level review still
# distinguishes unified.rs production edits from tests-only edits.
ALLOWED_CHANGED_EXACT = (
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/tests/pr15h_a_candidate_materialization.rs",
    "docs/BENCHMARKING.md",
    "docs/PERF_OPTIMIZATION_PLAN.md",
)
ALLOWED_CHANGED_PREFIXES = (
    "benchmarks/pr15h_a/",
    "docs/pr-artifacts/pr-15h-a/",
)

FORBIDDEN_REPORT_MARKERS = (
    "/home/",
    "/mnt/",
    "/tmp/",
    "/abs/",
    "c:\\",
    "target/pr15h-a",
    "idle-confirmation",
    "build.log",
    "corpus/",
    "indexes/",
)


# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return base.utc_now()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value) -> bytes:
    return base.pr15d_run.canonical_json_bytes(value) + b"\n"


def _no_duplicate_keys(pairs):
    seen = set()
    for key, _value in pairs:
        if key in seen:
            raise ValueError(f"duplicate JSON key: {key!r}")
        seen.add(key)
    return dict(pairs)


def read_json_strict(path: str):
    _require_regular_file(path)
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"), object_pairs_hook=_no_duplicate_keys)


def _require_regular_file(path: str) -> None:
    if os.path.islink(path):
        raise base.pr15d_run.RunBlocked("X11_SYMLINK", f"refusing symlink: {path}")
    if not os.path.isfile(path):
        raise base.pr15d_run.RunBlocked("X11_MISSING", f"missing regular file: {path}")


def _require_real_dir(path: str) -> None:
    if os.path.islink(path):
        raise base.pr15d_run.RunBlocked("X11_SYMLINK", f"refusing symlink: {path}")
    if not os.path.isdir(path):
        raise base.pr15d_run.RunBlocked("X11_MISSING", f"missing directory: {path}")


def write_exclusive_json(path: str, value) -> None:
    """Create ``path`` exclusively; never overwrite, truncate or repair."""
    payload = canonical_bytes(value)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # Leave the exclusive file in place; a failed campaign is never resumed.
        raise


def write_exclusive_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _median_nearest_rank(values) -> float:
    return base.pr15d_run.summarize(list(values))["median"]


def _ratio(high, low) -> float:
    if low <= 0:
        raise base.pr15d_run.RunBlocked("X13_DURATION", "non-positive duration in drift check")
    return high / low


def verdict_from_ratios(ratios) -> str:
    """Sign consistency only; a single equal ratio is INCONCLUSIVE."""
    if not ratios:
        raise base.pr15d_run.RunBlocked("X14_NO_RATIOS", "no paired ratios to classify")
    for value in ratios:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise base.pr15d_run.RunBlocked("X14_RATIO", f"invalid ratio {value!r}")
        if not (value > 0.0) or value != value or value in (float("inf"),):
            raise base.pr15d_run.RunBlocked("X14_RATIO", f"invalid ratio {value!r}")
    if all(value < 1.0 for value in ratios):
        return "B_FASTER"
    if all(value > 1.0 for value in ratios):
        return "A_FASTER"
    return "INCONCLUSIVE"


# ---------------------------------------------------------------------------
# Frozen lane matrix
# ---------------------------------------------------------------------------


def frozen_lanes() -> list[dict]:
    """Resolve the seven approved warm lanes in fixed order; reject drift."""
    by_id = {lane["id"]: lane for lane in base.pr15d_run.lane_descriptors()}
    lanes = []
    for lane_id in LANE_IDS:
        lane = by_id.get(lane_id)
        if lane is None:
            raise base.pr15d_run.RunBlocked(
                "X32_STAGE", f"frozen PR15D lane is missing: {lane_id}"
            )
        if lane["regime"] != REGIME:
            raise base.pr15d_run.RunBlocked("X32_STAGE", f"lane is not warm: {lane_id}")
        lanes.append(dict(lane))
    if len(lanes) != 7 or len({lane["id"] for lane in lanes}) != 7:
        raise base.pr15d_run.RunBlocked("X32_STAGE", "the PR 15H-A lane set is not exactly seven")
    return lanes


# ---------------------------------------------------------------------------
# Paths and source pinning
# ---------------------------------------------------------------------------


def _target_root(checkout_root: str) -> str:
    if not os.path.isabs(checkout_root):
        raise base.pr15d_run.RunBlocked(
            "X19_PATH_ESCAPE", f"--checkout-root must be absolute: {checkout_root!r}"
        )
    root = os.path.realpath(os.path.join(checkout_root, "target", "pr15h-a"))
    return root


def validate_out_path(out: str, checkout_root: str) -> str:
    """Accept only a fresh directory strictly beneath the checkout target root."""
    if not os.path.isabs(out):
        raise base.pr15d_run.RunBlocked("X19_PATH_ESCAPE", f"--out must be absolute: {out!r}")
    if os.path.islink(out):
        raise base.pr15d_run.RunBlocked("X11_SYMLINK", f"--out is a symlink: {out!r}")
    allowed = _target_root(checkout_root)
    candidate = os.path.realpath(out)
    try:
        within = os.path.commonpath([candidate, allowed]) == allowed
    except ValueError:
        within = False
    if not within or candidate == allowed:
        raise base.pr15d_run.RunBlocked(
            "X19_PATH_ESCAPE", f"--out must be strictly beneath {allowed} (got {candidate})"
        )
    if os.path.exists(candidate):
        raise base.pr15d_run.RunBlocked(
            "X20_OUT_EXISTS", f"--out already exists (never overwritten): {candidate}"
        )
    return candidate


def validate_sealed_dir(path: str, checkout_root: str, label: str) -> str:
    """Accept an existing sealed campaign directory beneath the same target root."""
    if not os.path.isabs(path):
        raise base.pr15d_run.RunBlocked("X19_PATH_ESCAPE", f"{label} must be absolute: {path!r}")
    if os.path.islink(path):
        raise base.pr15d_run.RunBlocked("X11_SYMLINK", f"{label} is a symlink: {path!r}")
    _require_real_dir(path)
    allowed = _target_root(checkout_root)
    candidate = os.path.realpath(path)
    try:
        within = os.path.commonpath([candidate, allowed]) == allowed
    except ValueError:
        within = False
    if not within or candidate == allowed:
        raise base.pr15d_run.RunBlocked(
            "X19_PATH_ESCAPE", f"{label} must be strictly beneath {allowed}"
        )
    return candidate


def resolve_pinned_tree(path: str) -> dict:
    """Validate a clean, detached, non-symlinked Git worktree and pin its SHA."""
    if not os.path.isabs(path):
        raise base.pr15d_run.RunBlocked("X27_SOURCE", f"source tree must be absolute: {path!r}")
    if os.path.islink(path):
        raise base.pr15d_run.RunBlocked("X11_SYMLINK", f"refusing symlinked worktree: {path!r}")
    if os.path.realpath(path) != os.path.normpath(path):
        raise base.pr15d_run.RunBlocked(
            "X11_SYMLINK", f"source tree path contains a symlink: {path!r}"
        )
    source = base.resolve_source_tree(path)
    detached = _is_detached(source["tree"])
    if not detached:
        raise base.pr15d_run.RunBlocked(
            "X27_SOURCE", f"source tree must be detached, not on a branch: {source['tree']}"
        )
    return source


def _is_detached(tree: str) -> bool:
    import subprocess

    result = subprocess.run(
        ["git", "-C", tree, "symbolic-ref", "-q", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode != 0


def _assert_clean_tooling() -> dict:
    """The tooling checkout itself must hold no unstaged tracked change."""
    resolved = base.resolve_source_tree(TOOLING_ROOT)
    if resolved["sha"] != base.pr15d_run.source_sha():
        raise base.pr15d_run.RunBlocked("X27_SOURCE", "tooling checkout SHA is inconsistent")
    return resolved


def verify_frozen_inputs(tree: str) -> None:
    base.verify_frozen_files(tree)


# ---------------------------------------------------------------------------
# Seal / immutability
# ---------------------------------------------------------------------------


def seal_paths(root: str) -> list[str]:
    """The exact, ordered relative files covered by ``raw/seal.json``."""
    if os.path.isfile(os.path.join(root, "raw", "trial-01.json")):
        return [
            "authorization.json",
            "manifest.json",
            "raw/trial-01.json",
            "raw/trial-02.json",
            "raw/trial-03.json",
        ]
    return ["authorization.json", "manifest.json"] + [
        f"raw/slots/slot-{index:02d}.json" for index in range(1, TOTAL_SLOTS + 1)
    ]


def write_seal(root: str) -> dict:
    relative_paths = seal_paths(root)
    files = {}
    for relative in relative_paths:
        _require_regular_file(os.path.join(root, relative))
        files[relative] = sha256_file(os.path.join(root, relative))
    seal = {"schema": SCHEMA_SEAL, "files": files}
    write_exclusive_json(os.path.join(root, "raw", "seal.json"), seal)
    return seal


def verify_seal(root: str) -> dict:
    seal_file = os.path.join(root, "raw", "seal.json")
    seal = read_json_strict(seal_file)
    if seal.get("schema") != SCHEMA_SEAL:
        raise base.pr15d_run.RunBlocked("X12_SEAL", "unknown seal schema")
    expected_paths = seal_paths(root)
    files = seal.get("files")
    if not isinstance(files, dict) or list(files) != expected_paths:
        raise base.pr15d_run.RunBlocked(
            "X12_SEAL", f"seal file set is not exactly {expected_paths}"
        )
    for relative in expected_paths:
        full = os.path.join(root, relative)
        _require_regular_file(full)
        actual = sha256_file(full)
        if actual != files[relative]:
            raise base.pr15d_run.RunBlocked(
                "X12_SEAL", f"sealed file changed: {relative}"
            )
    return seal


# ---------------------------------------------------------------------------
# Raw-record validation (shared by baseline and paired)
# ---------------------------------------------------------------------------


def validate_lane_record(record: dict, lane: dict, context: str) -> dict:
    """Validate one measured lane record and return its frozen summary."""
    problems = []

    def require(condition, code, detail):
        if not condition:
            problems.append({"code": code, "detail": detail})

    require(record.get("id") == lane["id"], "lane", f"{context}: lane id differs")
    require(record.get("n") == lane["n"], "lane", f"{context}: n differs")
    require(record.get("class") == lane["class"], "lane", f"{context}: class differs")
    require(record.get("k") == lane["k"], "lane", f"{context}: k differs")
    require(record.get("regime") == REGIME, "lane", f"{context}: regime is not warm")
    require(record.get("warmups") == WARMUPS, "warmups", f"{context}: warmups != {WARMUPS}")
    require(record.get("oracle_ok") is True, "oracle", f"{context}: oracle not ok")
    samples = record.get("samples_ns")
    if not isinstance(samples, list) or len(samples) != SAMPLES:
        problems.append(
            {
                "code": "samples",
                "detail": f"{context}: expected {SAMPLES} samples",
            }
        )
        samples = []
    for index, value in enumerate(samples):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            problems.append(
                {
                    "code": "sample",
                    "detail": f"{context}: sample[{index}]={value!r} is not a positive int",
                }
            )
    if problems:
        raise base.pr15d_run.RunBlocked(
            "X15_LANE_RECORD", f"{context}: invalid lane record: {problems}"
        )
    summary = base.pr15d_run.summarize(samples)
    if record.get("summary_ns") != summary:
        raise base.pr15d_run.RunBlocked(
            "X16_SUMMARY",
            f"{context}: summary_ns does not equal the frozen nearest-rank summary",
        )
    return summary


def validate_trial(trial: dict, lanes: list[dict], context: str) -> list[dict]:
    """Validate one measurement trial/slot and return its lane summaries."""
    problems = []

    def require(condition, detail):
        if not condition:
            problems.append(detail)

    if trial.get("contention_before", {}).get("state") != "clear":
        problems.append("before contention probe is not clear")
    if trial.get("contention_after", {}).get("state") != "clear":
        problems.append("after contention probe is not clear")
    records = trial.get("lanes")
    if not isinstance(records, list) or len(records) != len(lanes):
        problems.append(f"expected {len(lanes)} lane records")
        records = []
    by_id = {}
    for record in records:
        lane_id = record.get("id")
        if lane_id in by_id:
            problems.append(f"duplicate lane record {lane_id}")
        by_id[lane_id] = record
    if [record.get("id") for record in records] != [lane["id"] for lane in lanes]:
        problems.append("lane record order differs from the frozen lane order")
    if problems:
        raise base.pr15d_run.RunBlocked("X17_TRIAL", f"{context}: {problems}")
    return [
        validate_lane_record(by_id[lane["id"]], lane, f"{context}:{lane['id']}")
        for lane in lanes
    ]


def _trial_lane_medians(trial_summaries: list[list[dict]]) -> dict:
    """Map lane id -> list of per-trial 20-sample medians."""
    medians: dict[str, list[int]] = {}
    for summaries in trial_summaries:
        for summary, lane_id in zip(summaries, LANE_IDS, strict=True):
            medians.setdefault(lane_id, []).append(summary["median"])
    return medians


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------


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


def assert_report_sanitized(report) -> None:
    markers = list(FORBIDDEN_REPORT_MARKERS)
    try:
        host = os.uname().nodename
    except AttributeError:  # pragma: no cover - non-POSIX
        host = ""
    if host:
        markers.append(host)
    try:
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    except Exception:  # pragma: no cover - defensive
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
                    "sanitized report contains local or session-specific material",
                )
        if value.startswith("/") or value.startswith("\\"):
            raise base.pr15d_run.RunBlocked(
                "X42_SENSITIVE_REPORT", "sanitized report contains an absolute path"
            )


# ---------------------------------------------------------------------------
# Baseline: derive + render
# ---------------------------------------------------------------------------


def derive_baseline(manifest: dict, trials: list[dict]) -> tuple[dict, str]:
    lanes = frozen_lanes()
    if len(trials) != TRIALS:
        raise base.pr15d_run.RunBlocked("X35_TRIAL_COUNT", f"baseline has {len(trials)} trials")
    summaries = []
    probes = []
    for expected_index, trial in enumerate(trials, start=1):
        context = f"baseline:trial-{expected_index:02d}"
        summaries.append(validate_trial(trial, lanes, context))
        probes.append(
            {
                "index": expected_index,
                "before": trial["contention_before"]["state"],
                "after": trial["contention_after"]["state"],
            }
        )
    medians = _trial_lane_medians(summaries)
    lane_report = []
    for lane in lanes:
        values = medians[lane["id"]]
        lane_report.append(
            {
                "id": lane["id"],
                "n": lane["n"],
                "class": lane["class"],
                "k": lane["k"],
                "regime": lane["regime"],
                "trial_medians_ns": values,
                "median_of_medians_ns": _median_nearest_rank(values),
                "total_hits": _expected_hits(manifest, lane),
            }
        )
    report = {
        "schema": SCHEMA_BASELINE,
        "phase": PHASE,
        "stage": STAGE,
        "base_source_sha": manifest["base_source_sha"],
        "tooling_sha": manifest["tooling_sha"],
        "binary_sha256": manifest["build"]["binary_sha256"],
        "corpus_manifest_sha256": manifest["corpus_manifest_sha256"],
        "environment_fingerprint": manifest["environment_fingerprint"],
        "lane_ids": list(LANE_IDS),
        "trial_count": TRIALS,
        "samples_per_lane": SAMPLES,
        "warmups_per_lane": WARMUPS,
        "contention_probes": probes,
        "lanes": lane_report,
    }
    assert_report_sanitized(report)
    return report, render_baseline_markdown(report)


def _expected_hits(manifest: dict, lane: dict) -> int:
    value = manifest["expected_by_lane"].get(lane["id"])
    if not isinstance(value, int):
        raise base.pr15d_run.RunBlocked("X29_ORACLE", f"no expected hits for {lane['id']}")
    return value


def render_baseline_markdown(report: dict) -> str:
    lines = [
        "# PR 15H-A — pre-optimization baseline (Quervant-only)",
        "",
        f"- baseline source: `{report['base_source_sha']}`",
        f"- tooling: `{report['tooling_sha']}`",
        f"- frozen corpus manifest: `{report['corpus_manifest_sha256']}`",
        f"- trials: {report['trial_count']} x {report['samples_per_lane']} samples "
        f"({report['warmups_per_lane']} warmups) per lane",
        "",
        "| lane | trial medians (ns) | median-of-medians (ns) |",
        "|---|---:|---:|",
    ]
    for lane in report["lanes"]:
        medians = ", ".join(str(value) for value in lane["trial_medians_ns"])
        lines.append(
            f"| `{lane['id']}` | {medians} | {lane['median_of_medians_ns']} |"
        )
    lines.append("")
    lines.append("Contention probes: " + ", ".join(
        f"trial {probe['index']} {probe['before']}/{probe['after']}"
        for probe in report["contention_probes"]
    ))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Paired: derive + render
# ---------------------------------------------------------------------------


def _load_slots_from_dir(root: str) -> list[dict]:
    slots = []
    for index in range(1, TOTAL_SLOTS + 1):
        path = os.path.join(root, "raw", "slots", f"slot-{index:02d}.json")
        slots.append(read_json_strict(path))
    return slots


def validate_paired_schedule(slots: list[dict]) -> None:
    if len(slots) != TOTAL_SLOTS:
        raise base.pr15d_run.RunBlocked("X18_SCHEDULE", f"expected {TOTAL_SLOTS} slots")
    expected = []
    for block, (first, second) in enumerate(BLOCK_SCHEDULE, start=1):
        expected.append((block, first))
        expected.append((block, second))
    observed = []
    for index, slot in enumerate(slots, start=1):
        if slot.get("schema") != SCHEMA_SLOT:
            raise base.pr15d_run.RunBlocked("X18_SCHEDULE", f"slot {index} schema differs")
        observed.append((slot.get("block"), slot.get("arm")))
        if slot.get("slot") != index:
            raise base.pr15d_run.RunBlocked(
                "X18_SCHEDULE", f"slot {index} is numbered {slot.get('slot')!r}"
            )
    if observed != expected:
        raise base.pr15d_run.RunBlocked(
            "X18_SCHEDULE", f"mirrored A/B schedule differs: {observed} != {expected}"
        )


def _slot_medians(slots: list[dict], arm: str) -> dict:
    lanes = frozen_lanes()
    by_arm = {}
    for slot in slots:
        if slot["arm"] != arm:
            continue
        summaries = validate_trial(
            slot["trial"], lanes, f"paired:slot-{slot['slot']:02d}:{arm}"
        )
        block = slot["block"]
        if block in by_arm:
            raise base.pr15d_run.RunBlocked("X18_SCHEDULE", f"duplicate block {block} arm {arm}")
        by_arm[block] = {
            lane["id"]: summary["median"]
            for lane, summary in zip(lanes, summaries, strict=True)
        }
    if sorted(by_arm) != [1, 2, 3, 4]:
        raise base.pr15d_run.RunBlocked("X18_SCHEDULE", f"arm {arm} blocks are {sorted(by_arm)}")
    return by_arm


def _drift_violation(values, n: int) -> dict:
    cap = DRIFT_CAPS[n]
    lowest = min(values)
    highest = max(values)
    ratio = _ratio(highest, lowest)
    return {
        "n": n,
        "cap": cap,
        "values": list(values),
        "min": lowest,
        "max": highest,
        "ratio": ratio,
        "violated": ratio > cap,
    }


def compute_paired(
    manifest: dict,
    slots: list[dict],
    baseline_manifest: dict,
    baseline_trials: list[dict],
) -> tuple[str, dict, str]:
    """Return ``(kind, report, markdown)`` where kind is performance|blocked."""
    validate_paired_schedule(slots)
    lanes = frozen_lanes()
    if manifest["base_source_sha"] != baseline_manifest["base_source_sha"]:
        raise base.pr15d_run.RunBlocked("X37_INCOMPARABLE", "baseline source SHA differs")
    if manifest["candidate_source_sha"] == manifest["base_source_sha"]:
        raise base.pr15d_run.RunBlocked("X37_INCOMPARABLE", "candidate equals baseline")
    if manifest["corpus_manifest_sha256"] != baseline_manifest["corpus_manifest_sha256"]:
        raise base.pr15d_run.RunBlocked("X37_INCOMPARABLE", "corpus manifest differs")
    if manifest["environment_fingerprint"] != baseline_manifest["environment_fingerprint"]:
        raise base.pr15d_run.RunBlocked("X37_INCOMPARABLE", "host fingerprint differs")

    arm_a = _slot_medians(slots, "A")
    arm_b = _slot_medians(slots, "B")

    # Validate and summarise the sealed baseline trials (3 x 20 samples).
    baseline_summaries = [
        validate_trial(trial, lanes, f"baseline:trial-{index:02d}")
        for index, trial in enumerate(baseline_trials, start=1)
    ]
    baseline_medians = _trial_lane_medians(baseline_summaries)

    # Index digests must be byte-identical for a query-only change.
    if manifest["index_digests"] != baseline_manifest["index_digests"]:
        raise base.pr15d_run.RunBlocked(
            "X51_INDEX", "index digests differ between baseline and candidate"
        )

    lanes_report = []
    drift_violations = []
    for lane in lanes:
        lane_id = lane["id"]
        a_values = [arm_a[block][lane_id] for block in (1, 2, 3, 4)]
        b_values = [arm_b[block][lane_id] for block in (1, 2, 3, 4)]
        historical = baseline_medians[lane_id]
        historical_median = _median_nearest_rank(historical)
        a_median = _median_nearest_rank(a_values)
        b_median = _median_nearest_rank(b_values)
        ratios = [_ratio(b_value, a_value) for a_value, b_value in zip(a_values, b_values)]

        cross = _drift_violation([historical_median, a_median], lane["n"])
        within_a = _drift_violation(a_values, lane["n"])
        within_b = _drift_violation(b_values, lane["n"])
        for label, check in (
            ("cross_session", cross),
            ("within_arm_a", within_a),
            ("within_arm_b", within_b),
        ):
            if check["violated"]:
                drift_violations.append({"lane": lane_id, "check": label, **check})

        lanes_report.append(
            {
                "id": lane_id,
                "n": lane["n"],
                "class": lane["class"],
                "k": lane["k"],
                "regime": lane["regime"],
                "baseline_historical_medians_ns": historical,
                "baseline_historical_median_ns": historical_median,
                "a_slot_medians_ns": a_values,
                "b_slot_medians_ns": b_values,
                "a_median_of_4_ns": a_median,
                "b_median_of_4_ns": b_median,
                "ratios_b_over_a": ratios,
                "verdict": verdict_from_ratios(ratios),
                "total_hits": _expected_hits(manifest, lane),
            }
        )

    qualification = {
        "slot_count": TOTAL_SLOTS,
        "lane_record_count": sum(len(slot["trial"]["lanes"]) for slot in slots),
        "timed_samples": sum(
            len(record["samples_ns"])
            for slot in slots
            for record in slot["trial"]["lanes"]
        ),
        "warmups": sum(
            record["warmups"]
            for slot in slots
            for record in slot["trial"]["lanes"]
        ),
        "contention_probes": sum(
            2 for slot in slots if slot["trial"]["contention_before"]["state"] == "clear"
            and slot["trial"]["contention_after"]["state"] == "clear"
        ),
        "oracle_validations": sum(
            1
            for slot in slots
            for record in slot["trial"]["lanes"]
            if record.get("oracle_ok") is True
        ),
    }
    if (
        qualification["slot_count"] != TOTAL_SLOTS
        or qualification["lane_record_count"] != TOTAL_SLOTS * len(lanes)
        or qualification["timed_samples"] != TOTAL_SLOTS * len(lanes) * SAMPLES
        or qualification["warmups"] != TOTAL_SLOTS * len(lanes) * WARMUPS
        or qualification["contention_probes"] != TOTAL_SLOTS * 2
        or qualification["oracle_validations"] != TOTAL_SLOTS * len(lanes)
    ):
        raise base.pr15d_run.RunBlocked(
            "X54_COMPLETENESS", f"paired campaign is incomplete: {qualification}"
        )

    by_id = {lane["id"]: lane for lane in lanes_report}
    p00 = not drift_violations
    p01 = by_id[PRIMARY["P2"]]["verdict"] == "B_FASTER"
    p02 = by_id[PRIMARY["P3"]]["verdict"] == "B_FASTER"
    p03 = by_id[PRIMARY["P1"]]["verdict"] != "A_FASTER"
    p04 = all(by_id[GUARDS[key]]["verdict"] != "A_FASTER" for key in GUARDS)
    # Oracle parity for every timed lane plus byte-identical query-only indexes.
    # Full semantic/error/ledger parity is recorded by the correctness artifacts;
    # this harness can only prove the independent oracle and index identity.
    p05 = all(
        record.get("oracle_ok") is True
        for slot in slots
        for record in slot["trial"]["lanes"]
    ) and manifest["index_digests"] == baseline_manifest["index_digests"]
    if manifest.get("source_scope_ok") is not True:
        raise base.pr15d_run.RunBlocked(
            "X60_SOURCE_SCOPE",
            f"candidate touches non-allowlisted paths: {manifest.get('source_scope_violations')}",
        )
    p06 = True
    gates = {
        "HA-P00": "PASS" if p00 else "FAIL",
        "HA-P01": "PASS" if p01 else "FAIL",
        "HA-P02": "PASS" if p02 else "FAIL",
        "HA-P03": "PASS" if p03 else "FAIL",
        "HA-P04": "PASS" if p04 else "FAIL",
        "HA-P05": "PASS" if p05 else "FAIL",
        "HA-P06": "PASS" if p06 else "FAIL",
    }

    if not p00:
        blocked = {
            "schema": SCHEMA_BLOCKED,
            "phase": PHASE,
            "stage": STAGE,
            "reason": "MEASUREMENT_BLOCKED_BASELINE_DRIFT",
            "performance_not_evaluated": "PERFORMANCE_NOT_EVALUATED",
            "base_source_sha": manifest["base_source_sha"],
            "candidate_source_sha": manifest["candidate_source_sha"],
            "environment_fingerprint": manifest["environment_fingerprint"],
            "gates": gates,
            "drift_violations": drift_violations,
            "qualification": qualification,
            "lane_verdicts": {lane["id"]: lane["verdict"] for lane in lanes_report},
        }
        assert_report_sanitized(blocked)
        return "blocked", blocked, render_blocked_markdown(blocked)

    decision = "PERFORMANCE_ACCEPTED" if all(value == "PASS" for value in gates.values()) else "PERFORMANCE_REJECTED"
    report = {
        "schema": SCHEMA_PERFORMANCE,
        "phase": PHASE,
        "stage": STAGE,
        "base_source_sha": manifest["base_source_sha"],
        "candidate_source_sha": manifest["candidate_source_sha"],
        "baseline_binary_sha256": baseline_manifest["build"]["binary_sha256"],
        "candidate_binary_sha256": manifest["build"]["binary_sha256"],
        "corpus_manifest_sha256": manifest["corpus_manifest_sha256"],
        "index_digests": manifest["index_digests"],
        "environment_fingerprint": manifest["environment_fingerprint"],
        "slot_schedule": [
            {"slot": slot["slot"], "block": slot["block"], "arm": slot["arm"]}
            for slot in slots
        ],
        "qualification": qualification,
        "lanes": lanes_report,
        "gates": gates,
        "gate_notes": {
            "HA-P05": (
                "oracle parity and byte-identical query-only indexes; full semantic, "
                "first-error and ledger parity is recorded in the correctness artifacts"
            ),
            "HA-P06": "source-scope audit passed before any timing",
        },
        "decision": decision,
        "verdict_rule": (
            "B_FASTER only if all four paired ratios are < 1.0; A_FASTER only if "
            "all four are > 1.0; otherwise INCONCLUSIVE. HA-P01/P02 require "
            "B_FASTER; HA-P03 requires not A_FASTER; HA-P04 requires no guard "
            "A_FASTER. No speedup percentage is asserted."
        ),
        "limitations": [
            "in-process adapter samples include JSON transport but exclude build and index creation",
            "paired blocks are mirrored on one host; medians are not pooled across hosts",
            "reported ratios are wall-clock engine_ns only; CPU/allocations are not measured here",
            "no index byte-size or reopen-time improvement is claimed by this comparison",
        ],
    }
    assert_report_sanitized(report)
    return "performance", report, render_performance_markdown(report)


def render_performance_markdown(report: dict) -> str:
    lines = [
        "# PR 15H-A — paired performance (Quervant-only)",
        "",
        f"- baseline: `{report['base_source_sha']}`",
        f"- candidate: `{report['candidate_source_sha']}`",
        f"- decision: **{report['decision']}**",
        "- verdict rule: " + report["verdict_rule"],
        "",
        "| lane | A slot medians (ns) | B slot medians (ns) | B/A ratios | verdict |",
        "|---|---:|---:|---|---|",
    ]
    for lane in report["lanes"]:
        a_values = ", ".join(str(value) for value in lane["a_slot_medians_ns"])
        b_values = ", ".join(str(value) for value in lane["b_slot_medians_ns"])
        ratios = ", ".join(f"{value:.3f}" for value in lane["ratios_b_over_a"])
        lines.append(
            f"| `{lane['id']}` | {a_values} | {b_values} | {ratios} | {lane['verdict']} |"
        )
    lines.append("")
    lines.append("Gates: " + ", ".join(f"{key}={value}" for key, value in report["gates"].items()))
    lines.append("")
    lines.append(
        f"Qualification: {report['qualification']['slot_count']} slots, "
        f"{report['qualification']['lane_record_count']} lane records, "
        f"{report['qualification']['timed_samples']} timed samples, "
        f"{report['qualification']['warmups']} warmups, "
        f"{report['qualification']['contention_probes']} clear probes, "
        f"{report['qualification']['oracle_validations']} oracle validations."
    )
    lines.append("")
    return "\n".join(lines)


def render_blocked_markdown(report: dict) -> str:
    lines = [
        "# PR 15H-A — performance measurement blocked",
        "",
        f"- reason: **{report['reason']}**",
        f"- disposition: **{report['performance_not_evaluated']}**",
        f"- baseline: `{report['base_source_sha']}`",
        f"- candidate: `{report['candidate_source_sha']}`",
        "",
        "Drift observations:",
    ]
    for violation in report["drift_violations"]:
        lines.append(
            f"- `{violation['lane']}` {violation['check']}: "
            f"n={violation['n']} ratio={violation['ratio']:.4f} cap={violation['cap']}"
        )
    lines.append("")
    return "\n".join(lines)


def _report_pair_paths(root: str, kind: str) -> tuple[str, str]:
    if kind == "baseline":
        return (
            os.path.join(root, "sanitized", "baseline.json"),
            os.path.join(root, "sanitized", "baseline.md"),
        )
    if kind == "performance":
        return (
            os.path.join(root, "sanitized", "performance.json"),
            os.path.join(root, "sanitized", "performance.md"),
        )
    return (
        os.path.join(root, "sanitized", "blocked.json"),
        os.path.join(root, "sanitized", "blocked.md"),
    )


def publish_report(root: str, kind: str, report: dict, markdown: str) -> None:
    json_path, md_path = _report_pair_paths(root, kind)
    if os.path.exists(json_path) or os.path.exists(md_path):
        raise base.pr15d_run.RunBlocked("X43_REPORT_IMMUTABLE", "a report pair already exists")
    write_exclusive_json(json_path, report)
    write_exclusive_text(md_path, markdown)


def verify_report(root: str, kind: str, report: dict, markdown: str) -> None:
    json_path, md_path = _report_pair_paths(root, kind)
    expected_json = canonical_bytes(report)
    with open(json_path, "rb") as handle:
        actual_json = handle.read()
    if actual_json != expected_json:
        raise base.pr15d_run.RunBlocked("X44_REPORT_DRIFT", "sanitized JSON does not recompute")
    with open(md_path, "rb") as handle:
        actual_md = handle.read().decode("utf-8")
    if actual_md != markdown:
        raise base.pr15d_run.RunBlocked("X44_REPORT_DRIFT", "sanitized markdown does not recompute")


# ---------------------------------------------------------------------------
# Source-scope audit
# ---------------------------------------------------------------------------


def audit_changed_paths(tree: str, base_sha: str, candidate_sha: str) -> list[str]:
    output = base.git(tree, "diff", "--name-only", f"{base_sha}..{candidate_sha}")
    violations = []
    for path in output.splitlines():
        path = path.strip()
        if not path:
            continue
        if path in ALLOWED_CHANGED_EXACT:
            continue
        if any(path.startswith(prefix) for prefix in ALLOWED_CHANGED_PREFIXES):
            continue
        violations.append(path)
    return sorted(violations)


# ---------------------------------------------------------------------------
# Campaign execution
# ---------------------------------------------------------------------------


def _load_baseline_campaign(root: str) -> tuple[dict, list[dict]]:
    verify_seal(root)
    manifest = read_json_strict(os.path.join(root, "manifest.json"))
    if manifest.get("schema") != SCHEMA_MANIFEST or manifest.get("stage") != "baseline":
        raise base.pr15d_run.RunBlocked("X21_MANIFEST", "baseline manifest differs")
    trials = [
        read_json_strict(os.path.join(root, "raw", f"trial-{index:02d}.json"))
        for index in range(1, TRIALS + 1)
    ]
    return manifest, trials


def _common_manifest(
    base_source: dict,
    build: dict,
    corpus: dict,
    indices: dict,
    adapter_metadata: dict,
    environment: dict,
    lanes: list[dict],
    expected_by_lane: dict,
) -> dict:
    return {
        "schema": SCHEMA_MANIFEST,
        "phase": PHASE,
        "base_source_sha": base_source["sha"],
        "tooling_sha": base.pr15d_run.source_sha(),
        "build": {key: value for key, value in build.items() if key != "binary"},
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"],
        "index_digests": {str(n): record["digest"] for n, record in sorted(indices.items())},
        "adapter_metadata": adapter_metadata,
        "environment": environment,
        "environment_fingerprint": base.pr15d_run.host_fingerprint(environment),
        "lanes": [lane["id"] for lane in lanes],
        "expected_by_lane": {
            lane_id: expected["total_hits"] for lane_id, expected in expected_by_lane.items()
        },
    }


def _build_expected(corpus: dict, lanes: list[dict]) -> dict:
    return {
        lane["id"]: base.oracle.expected(
            rows=corpus["rows"][lane["n"]],
            field=lane["field"],
            term=lane["term"],
            k=lane["k"],
        )
        for lane in lanes
    }


def _index_digests_ok(indices: dict) -> bool:
    return all(base.directory_digest(record["dir"]) == record["digest"] for record in indices.values())


def run_baseline(args) -> int:
    if not args.idle_confirmed:
        print(
            "PERF_BLOCKED_OPERATOR: --idle-confirmed is required; no timing was performed.",
            file=sys.stderr,
        )
        return 3
    tooling = _assert_clean_tooling()
    out = validate_out_path(args.out, args.checkout_root)
    base_source = resolve_pinned_tree(args.base_tree)
    verify_frozen_inputs(TOOLING_ROOT)
    verify_frozen_inputs(base_source["tree"])
    lanes = frozen_lanes()

    os.makedirs(out, exist_ok=False)
    filesystem = base.require_native_filesystem(out)
    environment = base.pr15d_run.collect_environment(out)
    environment["filesystem"] = filesystem

    authorization = {
        "schema": SCHEMA_AUTHORIZATION,
        "stage": "baseline",
        "operator_idle_confirmed": True,
        "recorded_utc": utc_now(),
        "base_source_sha": base_source["sha"],
        "tooling_sha": tooling["sha"],
    }
    write_exclusive_json(os.path.join(out, "authorization.json"), authorization)

    build = base.build_adapter(base_source["tree"], out)
    corpus = base.prepare_corpus(out)
    expected_by_lane = _build_expected(corpus, lanes)
    adapter_metadata = base.pr15d_run.read_adapter_metadata("quervant", build["binary"])
    n_values = sorted({lane["n"] for lane in lanes})
    indices = base.build_indices(build["binary"], corpus, out, n_values)

    manifest = _common_manifest(
        base_source, build, corpus, indices, adapter_metadata, environment, lanes, expected_by_lane
    )
    manifest["stage"] = "baseline"
    write_exclusive_json(os.path.join(out, "manifest.json"), manifest)

    trials = []
    for trial_index in range(1, TRIALS + 1):
        if not _index_digests_ok(indices):
            raise base.pr15d_run.RunBlocked("X40_INDEX_MUTATED", "index changed before a trial")
        trial = base.measure_trial(
            trial_index,
            build["binary"],
            lanes,
            indices,
            expected_by_lane,
            adapter_metadata,
            out,
        )
        write_exclusive_json(
            os.path.join(out, "raw", f"trial-{trial_index:02d}.json"), trial
        )
        trials.append(trial)
    if not _index_digests_ok(indices):
        raise base.pr15d_run.RunBlocked("X40_INDEX_MUTATED", "index changed during the campaign")

    write_seal(out)
    report, markdown = derive_baseline(manifest, trials)
    publish_report(out, "baseline", report, markdown)
    print(
        f"PR15H_A BASELINE_SHA={base_source['sha']} OUT={out} "
        f"SEALED=yes LANES={len(lanes)} TRIALS={TRIALS}"
    )
    return 0


def run_paired(args) -> int:
    if not args.idle_confirmed:
        print(
            "PERF_BLOCKED_OPERATOR: --idle-confirmed is required; no timing was performed.",
            file=sys.stderr,
        )
        return 3
    tooling = _assert_clean_tooling()
    out = validate_out_path(args.out, args.checkout_root)
    baseline_root = validate_sealed_dir(args.baseline, args.checkout_root, "--baseline")
    if os.path.realpath(baseline_root) == out:
        raise base.pr15d_run.RunBlocked("X19_PATH_ESCAPE", "--baseline and --out must differ")
    baseline_manifest, baseline_trials = _load_baseline_campaign(baseline_root)

    base_source = resolve_pinned_tree(args.base_tree)
    candidate_source = resolve_pinned_tree(args.candidate_tree)
    if base_source["sha"] != baseline_manifest["base_source_sha"]:
        raise base.pr15d_run.RunBlocked("X47_SOURCE_PIN", "--base-tree is not the sealed baseline SHA")
    if candidate_source["sha"] == base_source["sha"]:
        raise base.pr15d_run.RunBlocked("X47_SOURCE_PIN", "candidate equals baseline")
    if not base.is_ancestor(candidate_source["tree"], base_source["sha"]):
        raise base.pr15d_run.RunBlocked("X47_SOURCE_PIN", "candidate is not a descendant of baseline")
    verify_frozen_inputs(TOOLING_ROOT)
    verify_frozen_inputs(base_source["tree"])
    verify_frozen_inputs(candidate_source["tree"])
    lanes = frozen_lanes()

    violations = audit_changed_paths(
        candidate_source["tree"], base_source["sha"], candidate_source["sha"]
    )
    if violations:
        raise base.pr15d_run.RunBlocked(
            "X60_SOURCE_SCOPE",
            f"candidate touches non-allowlisted paths: {violations}",
        )
    source_scope_ok = True

    os.makedirs(out, exist_ok=False)
    filesystem = base.require_native_filesystem(out)
    environment = base.pr15d_run.collect_environment(out)
    environment["filesystem"] = filesystem
    if base.pr15d_run.host_fingerprint(environment) != baseline_manifest["environment_fingerprint"]:
        raise base.pr15d_run.RunBlocked(
            "X52_HOST", "host fingerprint differs from the sealed baseline"
        )

    authorization = {
        "schema": SCHEMA_AUTHORIZATION,
        "stage": "paired",
        "operator_idle_confirmed": True,
        "recorded_utc": utc_now(),
        "base_source_sha": base_source["sha"],
        "candidate_source_sha": candidate_source["sha"],
        "tooling_sha": tooling["sha"],
        "baseline_campaign": os.path.basename(baseline_root),
    }
    write_exclusive_json(os.path.join(out, "authorization.json"), authorization)

    base_build = base.build_adapter(base_source["tree"], os.path.join(out, "arm-a"))
    candidate_build = base.build_adapter(candidate_source["tree"], os.path.join(out, "arm-b"))
    corpus = base.prepare_corpus(out)
    expected_by_lane = _build_expected(corpus, lanes)
    base_metadata = base.pr15d_run.read_adapter_metadata("quervant", base_build["binary"])
    candidate_metadata = base.pr15d_run.read_adapter_metadata("quervant", candidate_build["binary"])
    if base_metadata != candidate_metadata:
        raise base.pr15d_run.RunBlocked("X49_ADAPTER", "adapter metadata differs between arms")

    n_values = sorted({lane["n"] for lane in lanes})
    base_indices = base.build_indices(
        base_build["binary"], corpus, os.path.join(out, "arm-a"), n_values
    )
    candidate_indices = base.build_indices(
        candidate_build["binary"], corpus, os.path.join(out, "arm-b"), n_values
    )
    base_digests = {str(n): record["digest"] for n, record in sorted(base_indices.items())}
    candidate_digests = {str(n): record["digest"] for n, record in sorted(candidate_indices.items())}
    if base_digests != candidate_digests:
        raise base.pr15d_run.RunBlocked(
            "X51_INDEX", "baseline and candidate indexes are not byte-identical"
        )

    manifest = _common_manifest(
        base_source,
        base_build,
        corpus,
        base_indices,
        base_metadata,
        environment,
        lanes,
        expected_by_lane,
    )
    manifest["stage"] = "paired"
    manifest["candidate_source_sha"] = candidate_source["sha"]
    manifest["candidate_build"] = {
        key: value for key, value in candidate_build.items() if key != "binary"
    }
    manifest["candidate_index_digests"] = candidate_digests
    manifest["source_scope_ok"] = source_scope_ok
    manifest["source_scope_violations"] = violations
    write_exclusive_json(os.path.join(out, "manifest.json"), manifest)

    arms = {
        "A": {
            "binary": base_build["binary"],
            "sha": base_source["sha"],
            "indices": base_indices,
            "binary_sha256": base_build["binary_sha256"],
        },
        "B": {
            "binary": candidate_build["binary"],
            "sha": candidate_source["sha"],
            "indices": candidate_indices,
            "binary_sha256": candidate_build["binary_sha256"],
        },
    }
    slots = []
    slot_number = 0
    for block, order in enumerate(BLOCK_SCHEDULE, start=1):
        for arm in order:
            slot_number += 1
            if not _index_digests_ok(arms["A"]["indices"]) or not _index_digests_ok(
                arms["B"]["indices"]
            ):
                raise base.pr15d_run.RunBlocked("X40_INDEX_MUTATED", "index changed before a slot")
            slot_dir = os.path.join(out, "raw", "slots", f"slot-{slot_number:02d}")
            trial = base.measure_trial(
                1,
                arms[arm]["binary"],
                lanes,
                arms[arm]["indices"],
                expected_by_lane,
                base_metadata,
                slot_dir,
            )
            slot = {
                "schema": SCHEMA_SLOT,
                "slot": slot_number,
                "block": block,
                "arm": arm,
                "source_sha": arms[arm]["sha"],
                "binary_sha256": arms[arm]["binary_sha256"],
                "index_digests": {
                    str(n): record["digest"]
                    for n, record in sorted(arms[arm]["indices"].items())
                },
                "trial": trial,
            }
            write_exclusive_json(
                os.path.join(out, "raw", "slots", f"slot-{slot_number:02d}.json"), slot
            )
            slots.append(slot)
        if not _index_digests_ok(arms["A"]["indices"]) or not _index_digests_ok(
            arms["B"]["indices"]
        ):
            raise base.pr15d_run.RunBlocked("X40_INDEX_MUTATED", "index changed during a block")

    write_seal(out)
    kind, report, markdown = compute_paired(
        manifest, slots, baseline_manifest, baseline_trials
    )
    publish_report(out, kind, report, markdown)
    print(
        f"PR15H_A PAIRED_BASE={base_source['sha']} CANDIDATE={candidate_source['sha']} "
        f"OUT={out} RESULT={kind}"
    )
    return 0


# ---------------------------------------------------------------------------
# Verify-only
# ---------------------------------------------------------------------------


def run_verify_only(args) -> int:
    if args.command == "baseline":
        root = validate_sealed_dir(args.out, args.checkout_root, "--out")
        manifest, trials = _load_baseline_campaign(root)
        report, markdown = derive_baseline(manifest, trials)
        verify_report(root, "baseline", report, markdown)
        print(f"PR15H_A VERIFY_OK baseline OUT={root}")
        return 0

    root = validate_sealed_dir(args.out, args.checkout_root, "--out")
    baseline_root = validate_sealed_dir(args.baseline, args.checkout_root, "--baseline")
    baseline_manifest, baseline_trials = _load_baseline_campaign(baseline_root)
    verify_seal(root)
    manifest = read_json_strict(os.path.join(root, "manifest.json"))
    if manifest.get("stage") != "paired":
        raise base.pr15d_run.RunBlocked("X21_MANIFEST", "paired manifest differs")
    slots = _load_slots_from_dir(root)
    kind, report, markdown = compute_paired(
        manifest, slots, baseline_manifest, baseline_trials
    )
    verify_report(root, kind, report, markdown)
    print(f"PR15H_A VERIFY_OK paired OUT={root} RESULT={kind}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PR 15H-A targeted benchmark controller")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(sub):
        sub.add_argument("--checkout-root", required=True, help="absolute checkout root")
        sub.add_argument("--out", required=True, help="absolute output directory")
        sub.add_argument(
            "--idle-confirmed",
            action="store_true",
            help="real operator assertion that the host was idle",
        )
        sub.add_argument(
            "--verify-only",
            action="store_true",
            help="re-hash seals and recompute sanitized reports without writing",
        )

    baseline = subparsers.add_parser("baseline")
    common(baseline)
    baseline.add_argument("--base-tree", required=True, help="absolute clean detached baseline worktree")

    paired = subparsers.add_parser("paired")
    common(paired)
    paired.add_argument("--base-tree", required=True, help="absolute clean detached baseline worktree")
    paired.add_argument(
        "--candidate-tree", required=True, help="absolute clean detached candidate worktree"
    )
    paired.add_argument("--baseline", required=True, help="sealed baseline campaign directory")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify_only:
            return run_verify_only(args)
        if args.command == "baseline":
            return run_baseline(args)
        return run_paired(args)
    except base.pr15d_run.RunBlocked as error:
        print(f"PERF_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
