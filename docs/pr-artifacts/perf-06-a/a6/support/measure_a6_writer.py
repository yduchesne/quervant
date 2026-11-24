#!/usr/bin/env python3
"""Four fixed E/F index-build resource observations; no query timing or QA.

Run from repository root, after both paired acquisitions, with the same frozen
environment and LC_ALL=C:
PYTHONPATH=benchmarks python /path/to/measure_a6_writer.py \
  RETENTION_CONFIG RETENTION_RESULT SCRATCH_ROOT NEW_DIAGNOSTIC_DIRECTORY

This program creates four fresh indexes. It reuses the measured E/F release
executables and frozen corpora. It never changes or rebuilds a prepared cache.
Each case executes once. An exception stops the remaining cases and preserves
every file already written. Do not rerun against another output directory.
"""
from __future__ import annotations

import csv
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from quervant_bench.lean.artifacts import load_configuration, load_result
from quervant_bench.lean import preparation, runtime

E = "b70f624fffe0329def62701b61e997c4e303e167"
F = "3bb232f868cb556ce9b4273d902164c65416af0f"
GNU_TIME = Path("/usr/bin/time")
TIME_FORMAT = (
    "user_seconds=%U\nsystem_seconds=%S\nmax_rss_kib=%M\n"
    "elapsed_seconds=%e\nexit_status=%x"
)
CASES = (
    (1, "E", "A", 10000),
    (2, "F", "B", 10000),
    (3, "F", "B", 100000),
    (4, "E", "A", 100000),
)
FIELDS = (
    "order", "label", "source_revision", "documents", "adapter_cpu",
    "adapter_sha256", "index_ns", "commit_ns", "reopen_ns", "index_bytes",
    "segment_count", "user_seconds", "system_seconds", "cpu_seconds",
    "max_rss_kib", "elapsed_seconds", "exit_status", "resource_file",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_resources(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    rows = [line.split("=", 1) for line in text.splitlines()]
    require(len(rows) == 5 and all(len(row) == 2 for row in rows),
            "unexpected GNU time output")
    fields = dict(rows)
    require(len(fields) == 5 and set(fields) == {
        "user_seconds", "system_seconds", "max_rss_kib",
        "elapsed_seconds", "exit_status",
    }, "missing or duplicate resource fields")
    for field in ("user_seconds", "system_seconds", "elapsed_seconds"):
        require(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", fields[field]) is not None,
                "invalid resource duration")
    for field in ("max_rss_kib", "exit_status"):
        require(re.fullmatch(r"[0-9]+", fields[field]) is not None,
                "invalid resource integer")
    user = Decimal(fields["user_seconds"])
    system = Decimal(fields["system_seconds"])
    elapsed = Decimal(fields["elapsed_seconds"])
    rss = int(fields["max_rss_kib"])
    status = int(fields["exit_status"])
    require(user >= 0 and system >= 0 and user + system > 0,
            "CPU observation unavailable or rounded to zero")
    require(elapsed > 0 and rss > 0 and status == 0,
            "invalid resource values or unsuccessful adapter")
    return {
        "user_seconds": str(user), "system_seconds": str(system),
        "cpu_seconds": str(user + system), "max_rss_kib": rss,
        "elapsed_seconds": str(elapsed), "exit_status": status,
    }


def main() -> None:
    require(len(sys.argv) == 5,
            "expected retention config, retention result, scratch root, and new output directory")
    config_path, result_path, scratch_root, output_root = map(Path, sys.argv[1:])
    require(os.environ.get("LC_ALL") == "C", "run with frozen LC_ALL=C")
    require(GNU_TIME.is_file() and os.access(GNU_TIME, os.X_OK),
            "/usr/bin/time unavailable; no substitute is authorized")
    time_identity = subprocess.run(
        [str(GNU_TIME), "--version"], check=True, capture_output=True,
        text=True, timeout=15,
    ).stdout
    require("gnu" in time_identity.lower(), "GNU time identity not established")
    require(not output_root.exists() and not output_root.is_symlink(),
            "diagnostic output already exists; do not repeat resource acquisition")
    require(not scratch_root.is_symlink(), "scratch root must not be a symlink")
    require(not output_root.resolve().is_relative_to(scratch_root.resolve() / "prepared"),
            "resource output must remain outside all prepared caches")
    config_before, result_before = digest(config_path), digest(result_path)
    config = load_configuration(config_path)
    result = load_result(result_path)
    require(config["name"] == "quervant-perf06a6-adaptive-warm"
            and config["family"] == "perf-06", "wrong source campaign")
    require(result["status"] == "COMPLETE" and result["errors"] == [],
            "resource acquisition requires the complete retained campaign")
    require(result["configuration"] == config, "configuration mismatch")
    require(config["arms"]["A"]["revision"] == E
            and config["arms"]["B"]["revision"] == F, "wrong E/F source pins")
    require(result["context"]["build"]["arm_source_revisions"] == {"A": E, "B": F},
            "wrong compiled sources")
    cpu = result["context"]["adapter_cpu"]
    require(isinstance(cpu, int) and not isinstance(cpu, bool) and cpu >= 0,
            "adapter CPU unavailable")
    key = result["context"]["preparation"]["cache_key"]
    require(re.fullmatch(r"[0-9a-f]{64}", key) is not None, "invalid cache key")
    cache_dir = scratch_root.resolve() / "prepared" / key
    identity = preparation.source_identity(Path.cwd(), config)
    cached = preparation._load_cache(cache_dir, identity, config)
    require(cached is not None, "prepared cache identity or fingerprints failed")
    require(cached["index_metrics"] == result["index_metrics"],
            "prepared metrics no longer match acquisition")
    programs, _indexes = preparation._existing_inputs(cache_dir, config)
    for arm in ("A", "B"):
        require(len(programs[arm]) == 1, "unexpected adapter command shape")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(exist_ok=False)
    metadata = {
        "scope": "whole index-build adapter process; includes corpus parse, insert, commit, close, reopen and size enumeration",
        "interpretation": "single descriptive observation per source and corpus; no confidence interval or performance acceptance gate",
        "retention_configuration_id": config["configuration_id"],
        "retention_run_id": result["run_id"],
        "configuration_sha256": config_before,
        "result_sha256": result_before,
        "cache_key": key,
        "gnu_time_identity": time_identity.strip(),
        "adapter_cpu": cpu,
        "cases": [{"order": order, "label": label, "arm": arm, "documents": n}
                  for order, label, arm, n in CASES],
    }
    (output_root / "scope.txt").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    with (output_root / "writer.tsv").open("x", encoding="utf-8", newline="") as table, \
         (output_root / "raw-times.txt").open("x", encoding="utf-8") as raw:
        writer = csv.DictWriter(table, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        table.flush()
        os.fsync(table.fileno())
        for order, label, arm, n in CASES:
            case_dir = output_root / f"{order:02d}-{label}-n{n}"
            case_dir.mkdir(exist_ok=False)
            resource_path = case_dir / "resources.txt"
            adapter = Path(programs[arm][0])
            adapter_hash = digest(adapter)
            corpus = cache_dir / "corpus" / f"keyword-n{n}.tsv"
            wrapped = [
                str(GNU_TIME), "-o", str(resource_path),
                "-f", TIME_FORMAT, *programs[arm],
            ]
            # The native helper supplies taskset, JSONL build request, timeout,
            # expected document counts, positive timing checks and disk-size check.
            metrics = runtime.build_index(
                wrapped, engine="quervant", corpus_path=corpus,
                target=case_dir / "index", n=n, cpu=cpu,
            )
            resources = parse_resources(resource_path)
            require(metrics["segment_count"] == 1, "unexpected segment count")
            require(metrics["index_bytes"] == result["index_metrics"][arm][str(n)]["index_bytes"],
                    "fresh diagnostic index size differs from the same source's staged index")
            require(digest(adapter) == adapter_hash, "adapter changed during observation")
            row = {
                "order": order, "label": label,
                "source_revision": E if arm == "A" else F,
                "documents": n, "adapter_cpu": cpu, "adapter_sha256": adapter_hash,
                **metrics, **resources,
                "resource_file": str(resource_path.relative_to(output_root)),
            }
            writer.writerow(row)
            table.flush()
            os.fsync(table.fileno())
            raw.write(f"[{order:02d} {label} n={n}]\n")
            raw.write(resource_path.read_text(encoding="utf-8"))
            raw.write("\n")
            raw.flush()
            os.fsync(raw.fileno())
            print(json.dumps({"case": order, "label": label, "documents": n,
                              "status": "RECORDED"}, sort_keys=True), flush=True)
    require(digest(config_path) == config_before and digest(result_path) == result_before,
            "protected campaign artifact changed")
    after = preparation._load_cache(cache_dir, identity, config)
    require(after is not None and after == cached,
            "prepared cache changed during resource observations")
    print("A6_WRITER_DIAGNOSTICS_RECORDED=4", flush=True)


if __name__ == "__main__":
    main()

