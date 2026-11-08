#!/usr/bin/env python3
"""PR 15I-B P1 — historical PR 15G-E rare-lane regression diagnosis.

Benchmark-only. Runs the pinned historical A (`ca065a2`) and rejected E
(`62d35c2`) adapters against the frozen PR15D corpus and records paired
rare/medium lane timings plus source-level work attribution.

The attribution is *not* inferred from timing ratios alone: the script also
extracts the exact `inspect_offset_directory` boundary loop and the
`stored_docs_selected -> persisted_directory_view` call site from the pinned E
source and records the deterministic `doc_count + 1` boundary-read count.

Standard library only; no production code is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BASE_RUNNER = os.path.join(ROOT, "benchmarks", "pr15e_b1", "run_targeted.py")
_spec = importlib.util.spec_from_file_location("pr15i_b_diag_base", BASE_RUNNER)
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

pr15d_run = base.pr15d_run
oracle = base.oracle
generate = base.generate

HIST_A = "ca065a212987284144d8901aa5c54de093d6dbfc"
HIST_E = "62d35c262fa667673ee6d8701ca9ef75daf17a53"
WORKTREES = {
    "A": os.path.join(ROOT, "target", "pr15i-b", "diagnose", "worktrees", "hist-A"),
    "E": os.path.join(ROOT, "target", "pr15i-b", "diagnose", "worktrees", "hist-E"),
}
BUILD = {
    "A": os.path.join(ROOT, "target", "pr15i-b", "diagnose", "build-hist-A"),
    "E": os.path.join(ROOT, "target", "pr15i-b", "diagnose", "build-hist-E"),
}
SCHEDULE = (
    ("A", "E", "E", "A"),
    ("E", "A", "A", "E"),
    ("E", "A", "A", "E"),
    ("A", "E", "E", "A"),
)
LANE_IDS = (
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/medium/k100",
)
SCHEMA = "pr15i-b-historical-diagnosis-v1"


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(sha: str, path: str) -> str:
    return subprocess.run(
        ["git", "-C", ROOT, "show", f"{sha}:{path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    ).stdout


def attribute_source() -> dict:
    offset = git(HIST_E, "crates/quervant-core/src/segment/offset_directory.rs")
    reader = git(HIST_E, "crates/quervant-core/src/segment/reader.rs")
    loop_line = None
    read_line = None
    for number, line in enumerate(offset.splitlines(), start=1):
        if "while index < entries" in line:
            loop_line = number
        if "offset directory boundary" in line and read_line is None:
            read_line = number
    if loop_line is None or read_line is None:
        raise SystemExit("H-E3 source fingerprint not found; STOP")
    selected_line = None
    for number, line in enumerate(reader.splitlines(), start=1):
        if "persisted_directory_view(" in line and number > 800:
            selected_line = number
            break
    if selected_line is None:
        raise SystemExit("persisted_directory_view call in stored_docs_selected not found; STOP")
    return {
        "rule": "H-E3",
        "source_sha": HIST_E,
        "offset_directory_file": "crates/quervant-core/src/segment/offset_directory.rs",
        "boundary_loop_line": loop_line,
        "boundary_read_line": read_line,
        "reader_call_site_line": selected_line,
        "boundary_reads_per_certified_query": {"10000": 10_001, "100000": 100_001},
        "expected_new_format_reads": "O(touched 128-doc blocks), independent of N",
        "sha256": {
            "offset_directory.rs": hashlib.sha256(offset.encode()).hexdigest(),
            "reader.rs": hashlib.sha256(reader.encode()).hexdigest(),
        },
        "limitation": (
            "Boundary-read counts are derived from the pinned source loop and call "
            "chain; no dynamic Rust counter was injected into the historical tree. "
            "Paired timing corroboration is recorded separately."
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PR 15I-B P1 historical diagnosis")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = os.path.realpath(args.out)
    allowed = os.path.realpath(os.path.join(ROOT, "target", "pr15i-b", "diagnose"))
    if os.path.commonpath([out, allowed]) != allowed or out == allowed:
        print("OUT must be under target/pr15i-b/diagnose", file=sys.stderr)
        return 3
    if os.path.exists(out):
        print("OUT already exists; use a fresh id", file=sys.stderr)
        return 3
    os.makedirs(out)
    os.makedirs(os.path.join(out, "raw"))
    environment = pr15d_run.collect_environment(os.path.join(out, "setup"))
    fingerprint = pr15d_run.host_fingerprint(environment)
    base.require_native_filesystem(out)
    before = base.contention_for(os.path.join(out, "setup", "contention-before.json"))
    base._require_clear(before, "P1 diagnostic before")

    corpus = base.prepare_corpus(os.path.join(out, "setup"))
    descriptors = {lane["id"]: lane for lane in pr15d_run.lane_descriptors()}
    lanes = [dict(descriptors[lane_id]) for lane_id in LANE_IDS]
    expected = {
        lane["id"]: oracle.expected(
            rows=corpus["rows"][lane["n"]],
            field=lane["field"],
            term=lane["term"],
            k=lane["k"],
        )
        for lane in lanes
    }
    binaries = {}
    metadata = {}
    indices = {}
    for arm in ("A", "E"):
        binary = os.path.join(BUILD[arm], "release", "pr15d-quervant-adapter")
        if not os.path.isfile(binary):
            print(f"missing historical adapter for {arm}: {binary}", file=sys.stderr)
            return 3
        binaries[arm] = {"path": binary, "sha256": sha256_file(binary)}
        metadata[arm] = pr15d_run.read_adapter_metadata("quervant", binary)
        indices[arm] = {}
        for n in (10_000, 100_000):
            target = os.path.join(out, "setup", "indexes", arm, f"n{n}")
            record = pr15d_run.build_index(
                "quervant",
                binary,
                os.path.join(corpus["dir"], oracle.corpus_filename(n)),
                target,
                n,
            )
            indices[arm][n] = {"dir": target, "index_bytes": record["index_bytes"]}

    blocks = []
    for block, order in enumerate(SCHEDULE, start=1):
        block_dir = os.path.join(out, "raw", f"block-{block:02d}")
        os.makedirs(block_dir, exist_ok=True)
        records = []
        for arm in order:
            contention_before = base.contention_for(
                os.path.join(block_dir, f"{arm}-before.json")
            )
            base._require_clear(contention_before, f"block {block} {arm} before")
            for lane in lanes:
                record = pr15d_run.measure_lane(
                    "quervant",
                    binaries[arm]["path"],
                    indices[arm][lane["n"]]["dir"],
                    lane,
                    expected[lane["id"]],
                    metadata[arm],
                    contention_before,
                )
                record["arm"] = arm
                record["block"] = block
                records.append(record)
            contention_after = base.contention_for(
                os.path.join(block_dir, f"{arm}-after.json")
            )
            base._require_clear(contention_after, f"block {block} {arm} after")
        blocks.append({"block": block, "order": list(order), "lanes": records})

    ratios = {}
    for lane_id in LANE_IDS:
        per_block = []
        for block in blocks:
            a_values = [
                record["summary_ns"]["median"]
                for record in block["lanes"]
                if record["id"] == lane_id and record["arm"] == "A"
            ]
            e_values = [
                record["summary_ns"]["median"]
                for record in block["lanes"]
                if record["id"] == lane_id and record["arm"] == "E"
            ]
            if len(a_values) != 2 or len(e_values) != 2:
                raise SystemExit("paired lane sample count drift")
            per_block.append(
                (sum(e_values) / len(e_values)) / (sum(a_values) / len(a_values))
            )
        ordered = sorted(per_block)
        ratios[lane_id] = {
            "block_ratios": per_block,
            "conventional_median": (ordered[1] + ordered[2]) / 2.0,
        }

    after = base.contention_for(os.path.join(out, "setup", "contention-after.json"))
    base._require_clear(after, "P1 diagnostic after")
    attribution = attribute_source()
    report = {
        "schema": SCHEMA,
        "sources": {"A": HIST_A, "E": HIST_E},
        "binaries": binaries,
        "indices": indices,
        "lanes": LANE_IDS,
        "ratios": ratios,
        "attribution": attribution,
        "environment_fingerprint": fingerprint,
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "contention": {"before": before, "after": after},
        "classification": "HISTORICAL_RARE_REGRESSION_ATTRIBUTED"
        if attribution["rule"] == "H-E3"
        else "P1_HISTORICAL_ATTRIBUTION_BLOCKED",
        "limitations": [
            "Historical timing is diagnostic only and is never mixed into PR 15I-B acceptance ratios.",
            "Dynamic Rust boundary counters were not injected; work attribution derives from the pinned source loop and call chain.",
        ],
    }
    payload = json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    report_path = os.path.join(out, "diagnosis.json")
    with open(report_path, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    seal = {
        "schema": "pr15i-b-diagnosis-seal-v1",
        "files": {"diagnosis.json": sha256_file(report_path)},
    }
    with open(os.path.join(out, "seal.json"), "w", encoding="utf-8") as handle:
        json.dump(seal, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        "PR15I_B_DIAGNOSIS "
        f"classification={report['classification']} "
        f"rule={attribution['rule']} "
        f"loop_line={attribution['boundary_loop_line']} "
        f"call_line={attribution['reader_call_site_line']}"
    )
    for lane_id, value in ratios.items():
        print(f"  {lane_id} median_E_over_A={value['conventional_median']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
