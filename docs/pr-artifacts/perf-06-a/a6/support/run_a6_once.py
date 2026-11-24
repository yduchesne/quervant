#!/usr/bin/env python3
"""Invoke one frozen A6 campaign at most once, using the unmodified native CLI.

This is an invocation guard and log capture only. It does not measure queries,
change the native framework, retry a run, or replace native result publication.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from quervant_bench.lean.artifacts import load_configuration, load_result
from quervant_bench.lean.configuration import validate_configuration
from verify_a6_results import A0, E, F, POLICY, classify, require, verify_one

RETENTION = "quervant-perf06a6-adaptive-warm"
CUMULATIVE = "quervant-perf06a6-cumulative-warm"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_exclusive(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    require(len(sys.argv) == 5, "expected repository, scratch, acquisition evidence, configuration")
    repo, scratch, evidence, config_path = map(lambda x: Path(x).resolve(), sys.argv[1:])
    require(Path.cwd().resolve() == repo, "run from the verified controller repository root")
    require(scratch == repo / "target" / "perf06-a6", "unexpected scratch root")
    require(evidence == repo / "docs/pr-artifacts/perf-06-a/a6/acquisition",
            "unexpected acquisition evidence root")
    require(config_path.parent == repo / "benchmarks/studies/perf-06/warm/configurations",
            "configuration outside the approved study")
    require(os.environ.get("RUSTUP_TOOLCHAIN") == "1.98.1", "toolchain not frozen")
    require(os.environ.get("LC_ALL") == "C", "locale not frozen")
    for name in ("QUERVANT_PR15I_D3C_STRATEGY", "QUERVANT_PR15I_D3C_PREFILTER_PROFILE"):
        require(name not in os.environ, "forbidden experiment override")
    config = load_configuration(config_path)
    validate_configuration(config)
    name = config["name"]
    require(name in (RETENTION, CUMULATIVE), "unapproved acquisition name")
    baseline = E if name == RETENTION else A0
    require(config["policy"] == POLICY, "frozen policy changed")
    require(config["workload"] == {
        "id": "pr15d-exact-keyword-v1", "sizes": [10000, 100000],
        "classes": ["absent", "rare", "medium", "common"],
        "top_k": [10, 100], "regimes": ["warm"],
        "query_semantics": "exact-keyword-total-hits-and-ordered-doc-ids",
        "timed_operation": "exact-term-search-plus-topk-projection",
    }, "frozen workload changed")
    require(config["arms"] == {
        "A": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": baseline},
        "B": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": F},
    }, "frozen arm sources changed")
    require(config["build"] == {
        "release": True, "locked": True, "baseline_ref": None,
        "prefilter_profile": "P2", "quervant_feature": None,
    }, "frozen build settings changed")
    require(config["baseline"] == "A" and config["control"] == {
        "enabled": True, "baseline": "AA", "equivalent": "AA2",
    }, "frozen arm/control roles changed")
    evidence.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    runner = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    with (scratch / "acquisition.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = evidence / (name + ".started.txt")
        log_path = evidence / (name + ".run.log")
        reference = evidence / (name + ".result-reference.txt")
        require(not marker.exists() and not log_path.exists() and not reference.exists(),
                "campaign evidence already exists; invocation is not repeatable")
        result_dir = config_path.parent.parent / "results"
        require(not list(result_dir.glob(name + "-*.json")), "a result already exists")
        if name == RETENTION:
            require(not (evidence / (CUMULATIVE + ".started.txt")).exists(),
                    "C already has invocation history; do not start R")
        prior_verification = None
        if name == CUMULATIVE:
            prior_marker = evidence / (RETENTION + ".started.txt")
            prior_reference = evidence / (RETENTION + ".result-reference.txt")
            require(prior_marker.is_file() and prior_reference.is_file(),
                    "R has no complete prior invocation record")
            prior = json.loads(prior_marker.read_text(encoding="utf-8"))
            r_config = Path(prior["configuration_path"])
            r_result = Path(prior_reference.read_text(encoding="utf-8").strip())
            require(prior["runner_sha"] == runner, "controller changed between campaigns")
            require(sha(r_config) == prior["configuration_sha256"], "R configuration changed")
            # Mandatory R-only validity/replay before consuming C's invocation.
            # A valid numerical NOT_MET outcome does not stop C.
            r = verify_one(r_config, r_result, baseline=E, name=RETENTION,
                           runner_sha=runner, scratch_root=scratch)
            prior_verification = {
                "result_path": str(r_result), "result_sha256": sha(r_result),
                "configuration_sha256": sha(r_config), "status": "PASS",
                "retention": classify(r, retention=True),
            }
            print(json.dumps({"pre_c_r_verification": "PASS",
                              "retention": classify(r, retention=True)},
                             sort_keys=True, allow_nan=False), flush=True)
        payload = {
            "campaign": name,
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "runner_sha": runner,
            "configuration_path": str(config_path),
            "configuration_id": config["configuration_id"],
            "configuration_sha256": sha(config_path),
            "invocation_budget_consumed": True,
            "pre_c_r_verification": prior_verification,
        }
        # Marker is durable before any native acquisition process can start.
        write_exclusive(marker, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        argv = [sys.executable, "-m", "quervant_bench", "run",
                "--config", str(config_path), "--scratch-root", str(scratch)]
        with log_path.open("x", encoding="utf-8") as log:
            log.write("NATIVE_ARGV=" + json.dumps(argv) + "\n")
            log.flush()
            os.fsync(log.fileno())
            done = subprocess.run(argv, cwd=repo, stdout=log, stderr=subprocess.STDOUT,
                                  check=False)
            log.write("\nNATIVE_EXIT=" + str(done.returncode) + "\n")
            log.flush()
            os.fsync(log.fileno())
        require(sha(config_path) == payload["configuration_sha256"],
                "configuration changed during acquisition")
        lines = log_path.read_text(encoding="utf-8").splitlines()
        paths = [line.removeprefix("RESULT_JSON=") for line in lines
                 if line.startswith("RESULT_JSON=")]
        require(len(paths) <= 1, "unexpected multiple result publications")
        if paths:
            result_path = Path(paths[0]).resolve()
            require(result_path.parent == result_dir, "published result outside approved directory")
            result = load_result(result_path)
            require(result["configuration_id"] == config["configuration_id"],
                    "published result has wrong configuration")
            write_exclusive(reference, str(result_path) + "\n")
            print("RESULT_JSON=" + str(result_path), flush=True)
            print("NATIVE_RESULT_STATUS=" + str(result["status"]), flush=True)
        else:
            print("NO_RESULT_REFERENCE_PUBLISHED; started marker remains consumed", flush=True)
        print("NATIVE_EXIT=" + str(done.returncode), flush=True)
        return done.returncode if done.returncode >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
