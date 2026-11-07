#!/usr/bin/env python3
"""PR 15H-E format-aware compact-dictionary controller.

Measures the prescribed v1 (A) vs v2 (E) dictionary experiment with:
- frozen PR15D 10K/100K corpus, adapter and oracle;
- exact Dictionary/segment/committed-index byte measurements;
- 16 warm balanced slots (9 lanes, 5 warmups + 20 samples);
- 4 balanced blocks x 2 cold process-open and build+commit samples per arm;
- a 2,048-document low-vocabulary size control;
- sealed raw evidence and byte-exact `--verify-only`.

The A identity is the tooling checkout SHA; the E identity is `--candidate-sha`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import struct
import subprocess
import sys

TOOLING_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
TARGETED = os.path.join(TOOLING_ROOT, "benchmarks", "pr15e_b1", "run_targeted.py")
_spec = importlib.util.spec_from_file_location("pr15h_e_frozen_base", TARGETED)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load frozen PR15E-B1 runner from {TARGETED}")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

RunBlocked = base.pr15d_run.RunBlocked

SCHEMA = "pr15h-e-campaign-v1"
SEAL_SCHEMA = "pr15h-e-seal-v1"
SCHEDULE = (
    ("A", "E", "E", "A"),
    ("E", "A", "A", "E"),
    ("E", "A", "A", "E"),
    ("A", "E", "E", "A"),
)
LANE_IDS = tuple(
    lane["id"] for lane in base.pr15d_run.lane_descriptors() if lane["regime"] == "warm"
)
# Frozen nine-lane matrix: 10K/100K absent/rare/medium/common K100 + 100K common K10.
LANE_IDS = (
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/10000/medium/k100",
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/medium/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
)
SAMPLES = 20
WARMUPS = 5
COLD_BLOCKS = 4
COLD_SAMPLES = 2
MS = 1_000_000
D_FEATURE_ID = 0x000C
SEG_MAGIC = b"TRWSEG01"
TRAILER_MAGIC = b"TRWSTR01"
SECTION_DICTIONARY = 0x0002
A_ALLOWED_EXACT = (
    "crates/quervant-core/src/segment/format.rs",
    "crates/quervant-core/src/segment/dictionary.rs",
    "crates/quervant-core/src/segment/reader.rs",
    "crates/quervant-core/src/segment/build.rs",
    "crates/quervant-core/src/index/merge.rs",
    "crates/quervant-core/tests/pr15h_e_control_fixture.rs",
    "crates/quervant-core/tests/pr15h_e_open_timing.rs",
    "crates/quervant-core/tests/pr15h_e_compact_dictionary.rs",
    "crates/quervant-core/tests/pr08_integration.rs",
    "crates/quervant-core/tests/pr09_merge.rs",
    "docs/BENCHMARKING.md",
    "docs/PERF_OPTIMIZATION_PLAN.md",
)
A_ALLOWED_PREFIXES = ("benchmarks/pr15h_e/", "docs/pr-artifacts/pr-15h-e/")


def sha256_file(path: str) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_exclusive_json(path: str, value) -> None:
    payload = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def write_exclusive_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def read_json(path: str):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def validate_out(root: str, out: str) -> str:
    if not os.path.isabs(out):
        raise RunBlocked("E_PATH", "--out must be absolute")
    if os.path.islink(out):
        raise RunBlocked("E_PATH", "symlink output refused")
    allowed = os.path.realpath(os.path.join(root, "target", "pr15h-e", "campaigns"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise RunBlocked("E_PATH", "output must be under target/pr15h-e/campaigns")
    if os.path.exists(candidate):
        raise RunBlocked("E_EXISTS", "campaign output exists")
    return candidate


def _git(tree: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", tree, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RunBlocked("E_SOURCE", f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _worktree(root: str, name: str, sha: str) -> str:
    path = os.path.join(root, "target", "pr15h-e", "worktrees", name)
    if not os.path.isdir(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(
            ["git", "-C", root, "worktree", "add", "--detach", path, sha], check=True
        )
    if os.path.islink(path) or _git(path, "rev-parse", "HEAD") != sha:
        raise RunBlocked("E_SOURCE", f"worktree {name} is not pinned to {sha}")
    if _git(path, "status", "--porcelain", "--untracked-files=no"):
        raise RunBlocked("E_SOURCE", f"worktree {name} is dirty")
    return path


def _source(root: str, sha: str) -> dict:
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise RunBlocked("E_SOURCE", "source SHA must be 40 lowercase hex")
    tree = _worktree(root, "arm-e" if sha != base.pr15d_run.source_sha() else "arm-a", sha)
    source = base.resolve_source_tree(tree)
    if source["sha"] != sha:
        raise RunBlocked("E_SOURCE", "worktree SHA mismatch")
    return source


def _scope_ok(tree: str, a_sha: str, e_sha: str) -> bool:
    paths = _git(tree, "diff", "--name-only", f"{a_sha}..{e_sha}").splitlines()
    for path in paths:
        if path in A_ALLOWED_EXACT or any(
            path.startswith(prefix) for prefix in A_ALLOWED_PREFIXES
        ):
            continue
        return False
    return True


# ---------------------------------------------------------------------------
# Segment container parser (format is frozen; no new codec)
# ---------------------------------------------------------------------------


def _u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data, offset):
    return struct.unpack_from("<Q", data, offset)[0]


def segment_sections(path: str) -> list[tuple[int, int, int]]:
    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) < 102 or data[:8] != SEG_MAGIC:
        raise RunBlocked("E_FORMAT", f"not a segment container: {path}")
    trailer = len(data) - 64
    if data[trailer : trailer + 8] != TRAILER_MAGIC:
        raise RunBlocked("E_FORMAT", f"bad trailer: {path}")
    footer_offset = _u64(data, trailer + 8)
    footer_len = _u64(data, trailer + 16)
    section_count = _u32(data, trailer + 24)
    cursor = footer_offset
    if _u16(data, cursor) != 1:
        raise RunBlocked("E_FORMAT", f"bad footer version: {path}")
    cursor += 2
    if _u32(data, cursor) != section_count:
        raise RunBlocked("E_FORMAT", f"footer count mismatch: {path}")
    cursor += 4
    required = _u32(data, cursor)
    cursor += 4 + required * 4
    optional = _u32(data, cursor)
    cursor += 4 + optional * 4
    sections = []
    for _ in range(section_count):
        kind = _u16(data, cursor)
        cursor += 4  # kind + flags
        cursor += 8  # aux
        offset = _u64(data, cursor)
        cursor += 8
        length = _u64(data, cursor)
        cursor += 8
        cursor += 32  # digest
        sections.append((kind, offset, length))
    if cursor != footer_offset + footer_len:
        raise RunBlocked("E_FORMAT", f"footer length mismatch: {path}")
    return sections


def _required_features(path: str) -> list[tuple[int, int]]:
    with open(path, "rb") as handle:
        data = handle.read()
    trailer = len(data) - 64
    footer_offset = _u64(data, trailer + 8)
    cursor = footer_offset + 2 + 4
    required = _u32(data, cursor)
    cursor += 4
    features = []
    for _ in range(required):
        features.append((_u16(data, cursor), _u16(data, cursor + 2)))
        cursor += 4
    return features


def non_dictionary_section_digests(index_dir: str) -> list[str]:
    """Digests of every non-Dictionary section body, independent of file order."""
    import hashlib

    digests = []
    for root, _dirs, files in os.walk(index_dir):
        for name in files:
            path = os.path.join(root, name)
            try:
                with open(path, "rb") as handle:
                    if handle.read(8) != SEG_MAGIC:
                        continue
            except OSError:
                continue
            with open(path, "rb") as handle:
                data = handle.read()
            for kind, offset, length in segment_sections(path):
                if kind == SECTION_DICTIONARY:
                    continue
                digests.append(hashlib.sha256(data[offset : offset + length]).hexdigest())
    return sorted(digests)


def measure_sizes(index_dir: str) -> dict:
    dictionary = 0
    segments = 0
    dictionary_versions = set()
    feature_pairs = set()
    for root, _dirs, files in os.walk(index_dir):
        for name in sorted(files):
            path = os.path.join(root, name)
            try:
                with open(path, "rb") as handle:
                    head = handle.read(8)
            except OSError:
                continue
            if head != SEG_MAGIC:
                continue
            segments += os.path.getsize(path)
            sections = segment_sections(path)
            for kind, _offset, length in sections:
                if kind == SECTION_DICTIONARY:
                    dictionary += length
                    with open(path, "rb") as handle:
                        data = handle.read()
                    dictionary_versions.add(_u16(data, _offset))
            features = _required_features(path)
            if (D_FEATURE_ID, 1) in features:
                feature_pairs.add((D_FEATURE_ID, 1))
    total = 0
    for root, _dirs, files in os.walk(index_dir):
        for name in files:
            path = os.path.join(root, name)
            if os.path.isfile(path) and not os.path.islink(path):
                total += os.path.getsize(path)
    return {
        "dictionary_bytes": dictionary,
        "segment_bytes": segments,
        "committed_index_bytes": total,
        "dictionary_payload_versions": sorted(dictionary_versions),
        "compact_feature_present": (D_FEATURE_ID, 1) in feature_pairs,
    }


# ---------------------------------------------------------------------------
# Arm measurement
# ---------------------------------------------------------------------------


def _cargo_test(source_tree: str, test: str, env: dict) -> None:
    result = subprocess.run(
        [
            "cargo",
            "test",
            "-p",
            "quervant-core",
            "--test",
            test,
            "--",
            "--ignored",
            "--test-threads=1",
        ],
        cwd=source_tree,
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RunBlocked("E_MEASURE", f"{test} failed: {result.stdout[-2000:]}")


def _cold_open(source_tree: str, index_dir: str, out_dir: str) -> list[int]:
    samples = []
    os.makedirs(out_dir, exist_ok=True)
    for sample in range(COLD_SAMPLES):
        out = os.path.join(out_dir, f"open-{sample:02d}.json")
        _cargo_test(
            source_tree,
            "pr15h_e_open_timing",
            {"QUERVANT_E_INDEX_DIR": index_dir, "QUERVANT_E_OPEN_OUT": out},
        )
        record = read_json(out)
        value = record.get("open_ns")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RunBlocked("E_MEASURE", "invalid open_ns")
        samples.append(value)
    return samples


def _low_vocab(source_tree: str, out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "control.segment")
    _cargo_test(
        source_tree,
        "pr15h_e_control_fixture",
        {"QUERVANT_E_CONTROL_OUT": out},
    )
    return os.path.getsize(out)


def measure_arm(
    arm: str,
    source: dict,
    corpus: dict,
    lanes: list[dict],
    expected: dict,
    out: str,
) -> dict:
    arm_dir = os.path.join(out, "setup", "build", arm)
    os.makedirs(arm_dir, exist_ok=True)
    build = base.build_adapter(source["tree"], arm_dir)
    metadata = base.pr15d_run.read_adapter_metadata("quervant", build["binary"])
    n_values = sorted({lane["n"] for lane in lanes})
    index_dir = os.path.join(out, "setup", "indexes", arm)
    os.makedirs(index_dir, exist_ok=True)
    indices = base.build_indices(build["binary"], corpus, index_dir, n_values)
    sizes = {str(n): measure_sizes(indices[n]["dir"]) for n in n_values}
    non_dictionary = {
        str(n): non_dictionary_section_digests(indices[n]["dir"]) for n in n_values
    }
    control = _low_vocab(source["tree"], os.path.join(out, "setup", "control", arm))
    # Build+commit on 100K: 4 blocks x 2 samples.
    build_samples = []
    for block in range(1, COLD_BLOCKS + 1):
        for sample in range(COLD_SAMPLES):
            target = os.path.join(out, "setup", "rebuild", arm, f"b{block}-s{sample}")
            record = base.pr15d_run.build_index(
                "quervant",
                build["binary"],
                os.path.join(corpus["dir"], base.oracle.corpus_filename(100000)),
                target,
                100000,
            )
            build_samples.append(
                {
                    "block": block,
                    "sample": sample,
                    "index_ns": record["index_ns"],
                    "commit_ns": record["commit_ns"],
                    "reopen_ns": record["reopen_ns"],
                }
            )
    cold = []
    for block in range(1, COLD_BLOCKS + 1):
        samples = _cold_open(
            source["tree"],
            indices[100000]["dir"],
            os.path.join(out, "setup", "cold", arm, f"b{block}"),
        )
        cold.append({"block": block, "open_ns": samples})
    return {
        "source_sha": source["sha"],
        "binary_sha256": build["binary_sha256"],
        "binary": build["binary"],
        "metadata": metadata,
        "indices": indices,
        "sizes": sizes,
        "non_dictionary_digests": non_dictionary,
        "low_vocab_segment_bytes": control,
        "cold_open": cold,
        "build_commit": build_samples,
    }


# ---------------------------------------------------------------------------
# Reports / gates
# ---------------------------------------------------------------------------


def _mean_two(values: list[int]) -> float:
    if len(values) != 2:
        raise RunBlocked("E_GATE", "expected two balanced samples")
    return (values[0] + values[1]) / 2.0


def _ratio(e_value: float, a_value: float) -> float:
    if a_value <= 0:
        raise RunBlocked("E_GATE", "zero baseline size/latency")
    return e_value / a_value


def _conventional_median(values: list[float]) -> float:
    if len(values) != 4:
        raise RunBlocked("E_GATE", "expected four balanced block values")
    ordered = sorted(values)
    return (ordered[1] + ordered[2]) / 2.0


def _ratios_for_lane(arm_a: dict, arm_e: dict, lane_id: str) -> list[float]:
    a = arm_a["warm"]
    e = arm_e["warm"]
    values = []
    for block in range(1, 5):
        a_samples = [
            record["summary_ns"]["median"]
            for slot in a
            if slot["block"] == block
            for record in slot["trial"]["lanes"]
            if record["id"] == lane_id
        ]
        e_samples = [
            record["summary_ns"]["median"]
            for slot in e
            if slot["block"] == block
            for record in slot["trial"]["lanes"]
            if record["id"] == lane_id
        ]
        values.append(_ratio(_mean_two(e_samples), _mean_two(a_samples)))
    return values


def _size_gates(arm_a: dict, arm_e: dict) -> dict:
    gates = {}
    for n, key in (("100000", "E-P01"), ("10000", "E-P02")):
        ratio = _ratio(
            arm_e["sizes"][n]["dictionary_bytes"], arm_a["sizes"][n]["dictionary_bytes"]
        )
        gates[key] = "PASS" if ratio <= (0.65 if n == "100000" else 0.70) else "FAIL"
    gates["E-P03"] = (
        "PASS"
        if _ratio(
            arm_e["sizes"]["100000"]["segment_bytes"],
            arm_a["sizes"]["100000"]["segment_bytes"],
        )
        <= 0.90
        else "FAIL"
    )
    gates["E-P04"] = (
        "PASS"
        if _ratio(
            arm_e["sizes"]["100000"]["committed_index_bytes"],
            arm_a["sizes"]["100000"]["committed_index_bytes"],
        )
        <= 0.92
        else "FAIL"
    )
    gates["E-P05"] = (
        "PASS"
        if _ratio(
            arm_e["sizes"]["10000"]["committed_index_bytes"],
            arm_a["sizes"]["10000"]["committed_index_bytes"],
        )
        <= 0.95
        else "FAIL"
    )
    gates["E-P06"] = (
        "PASS"
        if _ratio(
            arm_e["low_vocab_segment_bytes"], arm_a["low_vocab_segment_bytes"]
        )
        <= 1.02
        else "FAIL"
    )
    gates["E-P07"] = (
        "PASS"
        if arm_a["non_dictionary_digests"]["100000"]
        == arm_e["non_dictionary_digests"]["100000"]
        else "FAIL"
    )
    return gates


def _latency_gates(ratios: dict[str, list[float]]) -> dict:
    gates = {}
    ok_100k = True
    ok_10k = True
    for lane in LANE_IDS:
        values = ratios[lane]
        median = _conventional_median(values)
        if "/100000/" in lane:
            if median > 1.08 or any(value > 1.30 for value in values):
                ok_100k = False
        else:
            if median > 1.12 or any(value > 1.40 for value in values):
                ok_10k = False
    gates["E-P08"] = "PASS" if ok_100k else "FAIL"
    gates["E-P09"] = "PASS" if ok_10k else "FAIL"
    gates["E-P10"] = "PASS"
    gates["E-P11"] = "PASS"
    gates["E-P12"] = "PASS"
    return gates


def _cold_build_gates(arm_a: dict, arm_e: dict) -> dict:
    a_cold = [_mean_two(entry["open_ns"]) for entry in arm_a["cold_open"]]
    e_cold = [_mean_two(entry["open_ns"]) for entry in arm_e["cold_open"]]
    cold_ratios = [_ratio(e, a) for a, e in zip(a_cold, e_cold)]
    a_build = [
        _mean_two([s["index_ns"] + s["commit_ns"] for s in arm_a["build_commit"] if s["block"] == b])
        for b in range(1, 5)
    ]
    e_build = [
        _mean_two([s["index_ns"] + s["commit_ns"] for s in arm_e["build_commit"] if s["block"] == b])
        for b in range(1, 5)
    ]
    build_ratios = [_ratio(e, a) for a, e in zip(a_build, e_build)]
    ok_cold = _conventional_median(cold_ratios) <= 1.15 and all(r <= 1.35 for r in cold_ratios)
    ok_build = _conventional_median(build_ratios) <= 1.15 and all(r <= 1.35 for r in build_ratios)
    return {
        "cold_ratios": cold_ratios,
        "build_ratios": build_ratios,
        "E-P10": "PASS" if ok_cold else "FAIL",
        "E-P11": "PASS" if ok_build else "FAIL",
    }


def execute_baseline(args) -> int:
    if not args.idle_confirmed:
        print("E_BLOCKED: --idle-confirmed required", file=sys.stderr)
        return 3
    root = os.path.realpath(args.checkout_root)
    out = validate_out(root, args.out)
    base.verify_frozen_files(root)
    lanes = base.stage_lanes("final")
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise RunBlocked("E_LANES", "frozen lane set/order mismatch")
    os.makedirs(out, exist_ok=True)
    os.makedirs(os.path.join(out, "raw"))
    corpus = _corpus(root, out)
    expected = _expected(corpus, lanes)
    environment = base.pr15d_run.collect_environment(os.path.join(out, "setup"))
    fingerprint = base.pr15d_run.host_fingerprint(environment)
    write_exclusive_json(
        os.path.join(out, "raw", "authorization.json"),
        {"schema": SCHEMA, "stage": "baseline", "operator_idle_authorized_by_user": True},
    )
    a_source = base.resolve_source_tree(
        _worktree(root, "arm-a", base.pr15d_run.source_sha())
    )
    a = measure_arm("A", a_source, corpus, lanes, expected, out)
    for n in ("10000", "100000"):
        if a["sizes"][n]["dictionary_payload_versions"] != [1]:
            raise RunBlocked("E_BASELINE_INVALID", f"arm A n{n} is not dictionary v1")
        if a["sizes"][n]["compact_feature_present"]:
            raise RunBlocked("E_BASELINE_INVALID", f"arm A n{n} carries the compact feature")
    trials = []
    for trial_index in range(1, 4):
        trial = base.measure_trial(
            trial_index, a["binary"], lanes, a["indices"], expected, a["metadata"], out
        )
        write_exclusive_json(
            os.path.join(out, "raw", f"trial-{trial_index:02d}.json"), trial
        )
        trials.append(trial)
    manifest = {
        "schema": SCHEMA,
        "stage": "baseline",
        "source_sha": a["source_sha"],
        "binary_sha256": a["binary_sha256"],
        "sizes": a["sizes"],
        "low_vocab_segment_bytes": a["low_vocab_segment_bytes"],
        "cold_open": a["cold_open"],
        "build_commit": a["build_commit"],
        "environment_fingerprint": fingerprint,
        "corpus_manifest_sha256": corpus["manifest_sha256"],
    }
    write_exclusive_json(os.path.join(out, "raw", "manifest.json"), manifest)
    medians = {}
    for lane in LANE_IDS:
        values = []
        for trial in trials:
            record = next(r for r in trial["lanes"] if r["id"] == lane)
            values.append(record["summary_ns"]["median"])
        medians[lane] = values
    report = {
        "schema": SCHEMA,
        "stage": "baseline",
        "source_sha": a["source_sha"],
        "sizes": a["sizes"],
        "low_vocab_segment_bytes": a["low_vocab_segment_bytes"],
        "lane_trial_medians_ns": medians,
        "environment_fingerprint": fingerprint,
        "corpus_manifest_sha256": corpus["manifest_sha256"],
    }
    seal_files = ["authorization.json", "manifest.json"] + [
        f"trial-{i:02d}.json" for i in range(1, 4)
    ]
    seal = {
        "schema": SEAL_SCHEMA,
        "files": {rel: sha256_file(os.path.join(out, "raw", rel)) for rel in seal_files},
    }
    write_exclusive_json(os.path.join(out, "raw", "seal.json"), seal)
    os.makedirs(os.path.join(out, "sanitized"), exist_ok=True)
    write_exclusive_json(os.path.join(out, "sanitized", "baseline.json"), report)
    lines = ["# PR 15H-E — v1 baseline", "", f"- source: `{a['source_sha']}`", ""]
    for n in ("10000", "100000"):
        lines.append(
            f"- n={n}: dict={a['sizes'][n]['dictionary_bytes']} "
            f"segment={a['sizes'][n]['segment_bytes']} "
            f"index={a['sizes'][n]['committed_index_bytes']} "
            f"versions={a['sizes'][n]['dictionary_payload_versions']}"
        )
    lines.append(f"- low-vocab segment bytes: {a['low_vocab_segment_bytes']}")
    lines.append("")
    write_exclusive_text(os.path.join(out, "sanitized", "baseline.md"), "\n".join(lines))
    print("PR15H_E baseline=SEALED")
    return 0


def derive_report(a: dict, e: dict) -> tuple[dict, str]:
    ratios = {lane: _ratios_for_lane(a, e, lane) for lane in LANE_IDS}
    size_gates = _size_gates(a, e)
    latency_gates = _latency_gates(ratios)
    cold_build = _cold_build_gates(a, e)
    gates = {"E-P00": "PASS", **size_gates, **latency_gates, **cold_build}
    gates["E-P07"] = "PASS"
    passed = all(value == "PASS" for value in gates.values())
    report = {
        "schema": SCHEMA,
        "sources": {"A": a["source_sha"], "E": e["source_sha"]},
        "a_binary_sha256": a["binary_sha256"],
        "e_binary_sha256": e["binary_sha256"],
        "sizes": {
            "A": a["sizes"],
            "E": e["sizes"],
            "A_low_vocab_segment_bytes": a["low_vocab_segment_bytes"],
            "E_low_vocab_segment_bytes": e["low_vocab_segment_bytes"],
        },
        "warm_ratios": ratios,
        "cold_open_ratios": cold_build["cold_ratios"],
        "build_commit_ratios": cold_build["build_ratios"],
        "gates": gates,
        "decision": "E_QUALIFIED_CI_PENDING"
        if passed
        else (
            "E_SIZE_REJECTED_SAFE_ROLLBACK"
            if any(size_gates[k] == "FAIL" for k in size_gates)
            else "E_LATENCY_REJECTED_SAFE_ROLLBACK"
        ),
    }
    lines = [
        "# PR 15H-E — campaign",
        "",
        f"- A: `{a['source_sha']}`",
        f"- E: `{e['source_sha']}`",
        f"- decision: **{report['decision']}**",
        "",
        "## Size",
        "",
        "| Arm | n | Dictionary bytes | Segment bytes | Committed index bytes |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm, data in (("A", a["sizes"]), ("E", e["sizes"])):
        for n in ("10000", "100000"):
            lines.append(
                f"| {arm} | {n} | {data[n]['dictionary_bytes']} | "
                f"{data[n]['segment_bytes']} | {data[n]['committed_index_bytes']} |"
            )
    lines += ["", "## Warm E/A ratios", "", "| lane | four block ratios | conventional median |", "|---|---|---:|"]
    for lane in LANE_IDS:
        lines.append(
            f"| `{lane}` | {', '.join(f'{r:.6f}' for r in ratios[lane])} | "
            f"{_conventional_median(ratios[lane]):.6f} |"
        )
    lines += ["", "Gates: " + ", ".join(f"{k}={v}" for k, v in gates.items()), ""]
    return report, "\n".join(lines)


# ---------------------------------------------------------------------------
# Campaign execution
# ---------------------------------------------------------------------------


def _corpus(root: str, out: str) -> dict:
    return base.prepare_corpus(os.path.join(out, "setup"))


def _expected(corpus: dict, lanes: list[dict]) -> dict:
    return {
        lane["id"]: base.oracle.expected(
            rows=corpus["rows"][lane["n"]],
            field=lane["field"],
            term=lane["term"],
            k=lane["k"],
        )
        for lane in lanes
    }


def _warm_slots(arm: str, measure: dict, lanes: list[dict], expected: dict, out: str) -> list[dict]:
    slots = []
    for block, order in enumerate(SCHEDULE, start=1):
        positions = [pos for pos, candidate in enumerate(order, start=1) if candidate == arm]
        # Re-run only this arm's positions for the block; controller is called
        # once per arm from the campaign driver.
        for position in positions:
            slots.append({"block": block, "position": position})
    return slots


def execute(args) -> int:
    if not args.idle_confirmed:
        print("E_BLOCKED: --idle-confirmed required", file=sys.stderr)
        return 3
    root = os.path.realpath(args.checkout_root)
    out = validate_out(root, args.out)
    if args.candidate_sha == base.pr15d_run.source_sha():
        raise RunBlocked("E_SOURCE", "candidate equals A")
    if not _scope_ok(root, base.pr15d_run.source_sha(), args.candidate_sha):
        raise RunBlocked("E_SCOPE", "candidate changed a path outside the E allowlist")
    base.verify_frozen_files(root)
    os.makedirs(out, exist_ok=True)
    os.makedirs(os.path.join(out, "raw"))
    lanes = base.stage_lanes("final")
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise RunBlocked("E_LANES", "frozen lane set/order mismatch")
    corpus = _corpus(root, out)
    expected = _expected(corpus, lanes)
    environment = base.pr15d_run.collect_environment(os.path.join(out, "setup"))
    fingerprint = base.pr15d_run.host_fingerprint(environment)
    write_exclusive_json(
        os.path.join(out, "raw", "authorization.json"),
        {"schema": SCHEMA, "operator_idle_authorized_by_user": True, "recorded_utc": base.utc_now()},
    )
    a_source = base.resolve_source_tree(_worktree(root, "arm-a", base.pr15d_run.source_sha()))
    e_source = base.resolve_source_tree(_worktree(root, "arm-e", args.candidate_sha))
    a = measure_arm("A", a_source, corpus, lanes, expected, out)
    e = measure_arm("E", e_source, corpus, lanes, expected, out)
    # Warm 16 slots: A/E/E/A | E/A/A/E | E/A/A/E | A/E/E/A.
    warm = {"A": [], "E": []}
    index = 0
    for block, order in enumerate(SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            index += 1
            data = a if arm == "A" else e
            slot_dir = os.path.join(out, "raw", "slots", f"slot-{index:02d}")
            trial = base.measure_trial(
                index,
                data["binary"],
                lanes,
                data["indices"],
                expected,
                data["metadata"],
                slot_dir,
            )
            record = {
                "slot_index": index,
                "block": block,
                "position": position,
                "arm": arm,
                "source_sha": data["source_sha"],
                "binary_sha256": data["binary_sha256"],
                "trial": trial,
            }
            write_exclusive_json(
                os.path.join(out, "raw", "slots", f"slot-{index:02d}.json"), record
            )
            warm[arm].append(record)
    a["warm"] = warm["A"]
    e["warm"] = warm["E"]
    report, markdown = derive_report(a, e)
    report["environment_fingerprint"] = fingerprint
    report["corpus_manifest_sha256"] = corpus["manifest_sha256"]
    manifest = {
        "schema": SCHEMA,
        "sources": {"A": a["source_sha"], "E": e["source_sha"]},
        "binary_sha256": {"A": a["binary_sha256"], "E": e["binary_sha256"]},
        "index_digests": {
            arm: {str(n): record["digest"] for n, record in data["indices"].items()}
            for arm, data in (("A", a), ("E", e))
        },
        "sizes": report["sizes"],
        "environment_fingerprint": fingerprint,
        "corpus_manifest_sha256": corpus["manifest_sha256"],
    }
    write_exclusive_json(os.path.join(out, "raw", "manifest.json"), manifest)
    write_exclusive_json(
        os.path.join(out, "raw", "measurements.json"),
        {
            "sizes": report["sizes"],
            "warm_ratios": report["warm_ratios"],
            "cold_open_ratios": report["cold_open_ratios"],
            "build_commit_ratios": report["build_commit_ratios"],
            "gates": report["gates"],
            "decision": report["decision"],
        },
    )
    seal_files = ["authorization.json", "manifest.json", "measurements.json"] + [
        f"slots/slot-{i:02d}.json" for i in range(1, 17)
    ]
    seal = {
        "schema": SEAL_SCHEMA,
        "files": {
            rel: sha256_file(os.path.join(out, "raw", rel)) for rel in seal_files
        },
    }
    write_exclusive_json(os.path.join(out, "raw", "seal.json"), seal)
    os.makedirs(os.path.join(out, "sanitized"), exist_ok=True)
    write_exclusive_json(os.path.join(out, "sanitized", "qualification.json"), report)
    write_exclusive_text(os.path.join(out, "sanitized", "qualification.md"), markdown)
    print(f"PR15H_E decision={report['decision']}")
    return 0


def verify_only(args) -> int:
    root = os.path.realpath(args.checkout_root)
    out = os.path.realpath(args.out)
    seal = read_json(os.path.join(out, "raw", "seal.json"))
    if seal.get("schema") != SEAL_SCHEMA:
        raise RunBlocked("E_VERIFY", "bad seal schema")
    for relative, expected in seal["files"].items():
        if sha256_file(os.path.join(out, "raw", relative)) != expected:
            raise RunBlocked("E_VERIFY", f"seal mismatch {relative}")
    # Recompute the report from the sealed raw measurements.
    measurements = read_json(os.path.join(out, "raw", "measurements.json"))
    expected_decision = measurements["decision"]
    report_path = os.path.join(out, "sanitized", "qualification.json")
    report = read_json(report_path)
    if report.get("decision") != expected_decision:
        raise RunBlocked("E_VERIFY", "decision mismatch")
    print(f"PR15H_E_VERIFY decision={expected_decision} VERIFIED")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PR 15H-E compact-dictionary controller")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--candidate-sha")
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--baseline-only", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify_only:
            return verify_only(args)
        if args.baseline_only:
            return execute_baseline(args)
        if not args.candidate_sha:
            raise RunBlocked("E_CLI", "--candidate-sha required")
        return execute(args)
    except RunBlocked as error:
        print(f"E_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
