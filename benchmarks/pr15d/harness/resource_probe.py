#!/usr/bin/env python3
"""Supplemental process-level CPU and peak-RSS qualification for PR15D.

These are **separate representative process diagnostics**. They never enter
`engine_ns`, the relative latency ratios or the 20-sample time series, and they
are never a substitute for an allocation measurement. Allocations remain
`NOT_MEASURED`.

The probe reuses the existing runner (`run.AdapterProcess`, `run.adapter_binary`,
`run._adapter_command`, `run.check_contention`, `run.validate_query_response`) and
the independent oracle. It never rebuilds, mutates or re-times an index.

Standard library only. Linux `/proc` is required; a missing or unreadable `/proc`
is `BLOCKED_ENVIRONMENT`, never a zero measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "corpus"))

import oracle  # noqa: E402
import run  # noqa: E402

SCHEMA_PROBE = "pr15d-resource-probe-v1"
ENGINES = ("quervant", "tantivy", "lucene")
PROBE_ROUNDS = 3
WARMUP_REQUESTS = 5
TARGET_CPU_NS = 500_000_000
MAX_WALL_NS = 60_000_000_000
MAX_REQUESTS = 50_000
# Fixed representative lanes: one sparse/small and one dense/large workload.
PROBE_LANES = {
    10000: {"n": 10000, "class": "rare", "field": "key", "term": "singleton", "k": 10, "regime": "warm"},
    100000: {"n": 100000, "class": "medium", "field": "group", "term": "medium", "k": 10, "regime": "warm"},
}
ROTATION = (
    ("quervant", "tantivy", "lucene"),
    ("tantivy", "lucene", "quervant"),
    ("lucene", "quervant", "tantivy"),
)
IDENTITY_MARKERS = {
    "quervant": ("pr15d-quervant-adapter",),
    "tantivy": ("pr15d-tantivy-adapter",),
    "lucene": ("pr15d-lucene-adapter", "org.quervant.bench.Adapter"),
}
SHELL_COMMS = {"sh", "bash", "dash", "zsh", "gradlew", "env"}

STATUS_MEASURED = "MEASURED"
STATUS_BELOW_RESOLUTION = "BELOW_RESOLUTION"
STATUS_DIAGNOSTIC_LIMIT = "DIAGNOSTIC_RESOLUTION_LIMIT"
STATUS_BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"


class ResourceError(Exception):
    def __init__(self, rule: str, detail: str):
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail


# ---------------------------------------------------------------------------
# Pure helpers (directly unit tested with synthetic /proc text)
# ---------------------------------------------------------------------------


def parse_proc_stat(text: str) -> dict:
    """Parse `/proc/<pid>/stat` around the final ')' of a possibly-spaced comm."""
    closing = text.rfind(")")
    if closing < 0:
        raise ResourceError("proc_stat_malformed", "missing ')' in stat")
    opening = text.find("(")
    if opening < 0 or opening > closing:
        raise ResourceError("proc_stat_malformed", "missing '(' in stat")
    comm = text[opening + 1 : closing]
    fields = text[closing + 2 :].split()
    # After ')' the first remaining field is state (field 3). utime/stime are
    # fields 14 and 15, i.e. offsets 11 and 12 in this list.
    if len(fields) < 13:
        raise ResourceError("proc_stat_malformed", f"only {len(fields)} trailing fields")
    try:
        utime = int(fields[11])
        stime = int(fields[12])
        starttime = int(fields[19]) if len(fields) > 19 else 0
    except ValueError as error:
        raise ResourceError("proc_stat_malformed", str(error)) from error
    if utime < 0 or stime < 0:
        raise ResourceError("proc_stat_negative", f"{utime}/{stime}")
    return {
        "comm": comm,
        "state": fields[0],
        "utime": utime,
        "stime": stime,
        "starttime": starttime,
    }


def parse_status(text: str) -> dict:
    """Return `vmhwm_kb` (or None) from `/proc/<pid>/status`."""
    vmhwm = None
    for line in text.splitlines():
        if line.startswith("VmHWM:"):
            parts = line.split()
            if len(parts) < 2:
                raise ResourceError("proc_status_malformed", line)
            try:
                vmhwm = int(parts[1])
            except ValueError as error:
                raise ResourceError("proc_status_malformed", line) from error
            if parts[-1] != "kB":
                raise ResourceError("proc_status_units", line)
    if vmhwm is not None and vmhwm <= 0:
        raise ResourceError("proc_status_vmhwm", f"VmHWM={vmhwm}")
    return {"vmhwm_kb": vmhwm}


def cpu_ns_from_ticks(delta_ticks: int, clk_tck: int) -> int:
    if not isinstance(clk_tck, int) or isinstance(clk_tck, bool) or clk_tck <= 0:
        raise ResourceError("clk_tck_invalid", repr(clk_tck))
    if not isinstance(delta_ticks, int) or isinstance(delta_ticks, bool):
        raise ResourceError("ticks_invalid", repr(delta_ticks))
    if delta_ticks < 0:
        raise ResourceError("ticks_negative", repr(delta_ticks))
    return delta_ticks * 1_000_000_000 // clk_tck


def identity_problem(engine: str, comm: str, cmdline: str) -> str | None:
    """Fail closed unless the observed PID is the actual engine process."""
    if engine not in IDENTITY_MARKERS:
        return f"unknown engine {engine!r}"
    comm = (comm or "").strip()
    if not comm:
        return "empty comm"
    if comm in SHELL_COMMS:
        return f"observed PID comm is a shell/wrapper ({comm!r})"
    if engine == "lucene":
        if comm != "java":
            return f"lucene PID comm is {comm!r}, expected 'java'"
        if not any(marker in (cmdline or "") for marker in IDENTITY_MARKERS[engine]):
            return "lucene java cmdline does not identify the adapter"
        return None
    if comm != engine and engine not in comm:
        # comm is truncated to 15 chars by the kernel, so compare on the prefix.
        if not comm.startswith(engine):
            return f"{engine} PID comm is {comm!r}"
    if not any(marker in (cmdline or "") for marker in IDENTITY_MARKERS[engine]):
        return f"{engine} cmdline does not identify the adapter binary"
    return None


def probe_stop_reason(
    cpu_ns: int,
    wall_ns: int,
    requests: int,
    limits=(TARGET_CPU_NS, MAX_WALL_NS, MAX_REQUESTS),
) -> str | None:
    target_cpu_ns, max_wall_ns, max_requests = limits
    if cpu_ns >= target_cpu_ns:
        return "cpu_target"
    if wall_ns >= max_wall_ns:
        return "wall_cap"
    if requests >= max_requests:
        return "request_cap"
    return None


def classify_probe(*, cpu_ns: int, delta_ticks: int, stop_reason: str) -> str:
    if delta_ticks <= 0 or cpu_ns <= 0:
        return STATUS_BELOW_RESOLUTION
    if stop_reason != "cpu_target":
        return STATUS_DIAGNOSTIC_LIMIT
    return STATUS_MEASURED


def probe_loop(*, request, cpu_ticks, clock_ns, limits=(TARGET_CPU_NS, MAX_WALL_NS, MAX_REQUESTS)) -> dict:
    """Drive serial requests until the CPU target, wall cap or request cap."""
    before = cpu_ticks()
    started = clock_ns()
    requests = 0
    ticks_after = before
    cpu_ns = 0
    wall_ns = 0
    stop_reason = None
    while True:
        request()
        requests += 1
        ticks_after = cpu_ticks()
        wall_ns = clock_ns() - started
        cpu_ns = cpu_ns_from_ticks(ticks_after - before, clock_ticks())
        stop_reason = probe_stop_reason(cpu_ns, wall_ns, requests, limits)
        if stop_reason is not None:
            break
    return {
        "requests": requests,
        "wall_ns": wall_ns,
        "cpu_ns": cpu_ns,
        "ticks_before": before,
        "ticks_after": ticks_after,
        "stop_reason": stop_reason,
    }


def clock_ticks() -> int:
    try:
        value = os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError) as error:
        raise ResourceError("clk_tck_unavailable", str(error)) from error
    if not isinstance(value, int) or value <= 0:
        raise ResourceError("clk_tck_invalid", repr(value))
    return value


# ---------------------------------------------------------------------------
# /proc readers
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as error:
        raise ResourceError(STATUS_BLOCKED_ENVIRONMENT, f"{path}: {error}") from error


def read_cpu_ticks(pid: int) -> int:
    stat = parse_proc_stat(_read(f"/proc/{pid}/stat"))
    return stat["utime"] + stat["stime"]


def read_rss_bytes(pid: int) -> int | None:
    vmhwm = parse_status(_read(f"/proc/{pid}/status"))["vmhwm_kb"]
    return None if vmhwm is None else vmhwm * 1024


IDENTITY_SETTLE_TIMEOUT_S = 15.0
IDENTITY_POLL_S = 0.01


def await_process_identity(
    engine: str,
    pid: int,
    *,
    identity_reader=None,
    clock=time.monotonic,
    sleep=time.sleep,
    timeout_s: float = IDENTITY_SETTLE_TIMEOUT_S,
    poll_s: float = IDENTITY_POLL_S,
) -> tuple[str, str]:
    """Wait for a launcher script to ``exec`` the real engine, then verify it.

    The Lucene install distribution is a shell script whose final statement is
    ``exec "$JAVACMD" "$@"``; the PID is the same before and after the exec, but
    ``comm`` only becomes ``java`` once the exec has happened. Polling briefly is
    therefore required and is *not* a waiver: if the PID never becomes the real
    engine process, the probe still fails closed with X32.
    """
    reader = process_identity if identity_reader is None else identity_reader
    deadline = clock() + timeout_s
    problem = "no identity sample"
    while True:
        try:
            comm, cmdline = reader(pid)
        except ResourceError:
            raise
        except OSError as error:
            raise ResourceError("X32_PID_IDENTITY", f"pid {pid} disappeared: {error}") from error
        problem = identity_problem(engine, comm, cmdline)
        if problem is None:
            return comm, cmdline
        if clock() >= deadline:
            break
        sleep(poll_s)
    raise ResourceError("X32_PID_IDENTITY", problem)


def process_identity(pid: int) -> tuple[str, str]:
    stat = parse_proc_stat(_read(f"/proc/{pid}/stat"))
    cmdline = _read(f"/proc/{pid}/cmdline").replace("\x00", " ")
    return stat["comm"], cmdline


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Paths whose content determines the measured timings. Tooling that only
# *observes* a run (this probe) may drift, but these may not.
MEASURED_PATHS = (
    "benchmarks/pr15d/adapters",
    "benchmarks/pr15d/harness/run.py",
    "benchmarks/pr15d/harness/validate.py",
    "benchmarks/pr15d/harness/aggregate.py",
    "benchmarks/pr15d/corpus",
    "benchmarks/pr15d/spec",
    "benchmarks/pr15d/protocol",
)


def measured_path_drift(run_sha: str, head_sha: str) -> list[str]:
    """Files that changed between the measured source and HEAD (measured paths only)."""
    if run_sha == head_sha:
        return []
    completed = subprocess.run(
        ["git", "diff", "--name-only", run_sha, head_sha, "--", *MEASURED_PATHS],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(HERE))),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ResourceError(
            "X40_SOURCE_MISMATCH",
            f"cannot compare measured source {run_sha} with HEAD: {completed.stderr.strip()}",
        )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def verify_run_ready(run_dir: str, *, idle_confirmed: bool, tree_clean=None) -> dict:
    """Fail closed on any state that cannot produce an honest resource record."""
    if not idle_confirmed:
        raise ResourceError(
            "X38_DEFER_ATTESTATION",
            "the human operator must supply --idle-confirmed for this window",
        )
    is_clean = run.tracked_tree_clean if tree_clean is None else tree_clean
    if not is_clean():
        raise ResourceError("X29_SOURCE_DIRTY", "tracked tree is not clean")
    run_record = run.read_json(os.path.join(run_dir, "run.json"))
    if run_record.get("status") != "complete" or run_record.get("qualified") is not True:
        raise ResourceError("X40_RUN_STATE", "run.json is not complete+qualified")
    measured_sha = run_record.get("source_sha")
    head_sha = run.source_sha()
    drift = measured_path_drift(measured_sha, head_sha)
    if drift:
        raise ResourceError(
            "X40_SOURCE_MISMATCH",
            f"measured source {measured_sha} differs from HEAD {head_sha} in {drift}",
        )
    validation = run.read_json(os.path.join(run_dir, "validation.json"))
    if validation.get("status") != "QUALIFIED":
        raise ResourceError("X40_VALIDATION", "validation.json is not QUALIFIED")
    for trial in range(1, run.REQUIRED_TRIALS + 1):
        for engine in ENGINES:
            path = os.path.join(run_dir, "trials", f"trial-{trial}", f"{engine}.json")
            if not os.path.isfile(path):
                raise ResourceError("X40_MISSING_TRIAL", path)
    return run_record


def _index_dir(run_dir: str, round_index: int, engine: str, n: int) -> str:
    return os.path.join(
        run_dir, "indexes", f"trial-{round_index}", engine, f"n{n}"
    )


def _manifest_digests(run_dir: str) -> dict:
    digests = {}
    for trial in range(1, run.REQUIRED_TRIALS + 1):
        for engine in ENGINES:
            path = os.path.join(run_dir, "trials", f"trial-{trial}", f"{engine}.json")
            digests[f"trials/trial-{trial}/{engine}.json"] = sha256_file(path)
    return digests


# ---------------------------------------------------------------------------
# Probe execution
# ---------------------------------------------------------------------------


def probe_once(
    *, engine: str, binary: str, index_dir: str, lane: dict, expected: dict
) -> dict:
    if not os.path.isdir(index_dir):
        raise ResourceError("X40_MISSING_INDEX", index_dir)
    process = run.AdapterProcess(engine, run._adapter_command(engine, binary, index_dir))
    try:
        pid = process.process.pid
        comm, cmdline = await_process_identity(engine, pid)

        def issue():
            response = process.request(
                {
                    "request_id": f"resource:{lane['n']}:{lane['class']}:k{lane['k']}",
                    "op": "query",
                    "field": lane["field"],
                    "term": lane["term"],
                    "k": lane["k"],
                    "mode": lane["regime"],
                }
            )
            run.validate_query_response(response, lane, expected)

        for _ in range(WARMUP_REQUESTS):
            issue()
        if process.process.poll() is not None:
            raise ResourceError("X28_PROCESS_DEATH", f"{engine} died before probing")

        ticks_before = read_cpu_ticks(pid)
        rss_before = read_rss_bytes(pid)
        result = probe_loop(
            request=issue, cpu_ticks=lambda: read_cpu_ticks(pid), clock_ns=time.monotonic_ns
        )
        rss_after = read_rss_bytes(pid)
        if process.process.poll() is not None:
            raise ResourceError("X28_PROCESS_DEATH", f"{engine} died during probing")
        peak_rss = rss_after if rss_before is None else max(rss_before, rss_after or 0)
        status = classify_probe(
            cpu_ns=result["cpu_ns"],
            delta_ticks=result["ticks_after"] - result["ticks_before"],
            stop_reason=result["stop_reason"],
        )
        return {
            "engine": engine,
            "n": lane["n"],
            "class": lane["class"],
            "k": lane["k"],
            "regime": lane["regime"],
            "index_dir": index_dir,
            "process_identity": {"comm": comm, "cmdline_sha256": hashlib.sha256(cmdline.encode()).hexdigest()},
            "warmups": WARMUP_REQUESTS,
            "requests": result["requests"],
            "wall_ns": result["wall_ns"],
            "ticks_before": result["ticks_before"],
            "ticks_after": result["ticks_after"],
            "clk_tck": clock_ticks(),
            "cpu_ns": result["cpu_ns"],
            "cpu_ns_per_request": result["cpu_ns"] // result["requests"] if result["requests"] else None,
            "rss_before_bytes": rss_before,
            "peak_rss_bytes": peak_rss,
            "vmhwm_kb": None if peak_rss is None else peak_rss // 1024,
            "stop_reason": result["stop_reason"],
            "status": status,
            "allocations": "NOT_MEASURED",
        }
    finally:
        process.close()


def _contention(run_dir: str, label: str) -> dict:
    path = os.path.join(run_dir, "contention", "resource-probe", f"{label}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return run.check_contention(path)


def execute(run_dir: str, *, idle_confirmed: bool) -> dict:
    run_record = verify_run_ready(run_dir, idle_confirmed=idle_confirmed)
    corpus_dir = run_record.get("corpus_dir")
    if not corpus_dir or not os.path.isdir(corpus_dir):
        raise ResourceError("X40_CORPUS", f"corpus_dir unavailable: {corpus_dir!r}")
    manifest, rows_by_n = oracle.load_and_verify(corpus_dir)
    manifest_sha = oracle.sha256_bytes(oracle.canonical_json_bytes(manifest))
    if manifest_sha != run_record.get("corpus_manifest_sha256"):
        raise ResourceError("X40_CORPUS_DIGEST", "corpus digest differs from run.json")

    binaries = {engine: run.adapter_binary(engine, run_dir) for engine in ENGINES}
    for engine, binary in binaries.items():
        if not os.path.isfile(binary):
            raise ResourceError("X40_MISSING_BINARY", binary)

    before_digests = _manifest_digests(run_dir)
    probes = []
    for round_index in range(1, PROBE_ROUNDS + 1):
        order = ROTATION[round_index - 1]
        for engine in order:
            for n in (10000, 100000):
                lane = dict(PROBE_LANES[n])
                expected = oracle.expected(rows_by_n[n], lane["field"], lane["term"], lane["k"])
                pre = _contention(run_dir, f"r{round_index}-{engine}-n{n}-pre")
                if pre.get("state") != "clear":
                    raise ResourceError("X36_CONTENTION", json.dumps(pre, sort_keys=True))
                record = probe_once(
                    engine=engine,
                    binary=binaries[engine],
                    index_dir=_index_dir(run_dir, round_index, engine, n),
                    lane=lane,
                    expected=expected,
                )
                record["round"] = round_index
                post = _contention(run_dir, f"r{round_index}-{engine}-n{n}-post")
                record["contention"] = {"pre": pre.get("state"), "post": post.get("state")}
                if post.get("state") != "clear":
                    raise ResourceError("X36_CONTENTION", json.dumps(post, sort_keys=True))
                probes.append(record)

    after_digests = _manifest_digests(run_dir)
    if before_digests != after_digests:
        raise ResourceError("X41_EVIDENCE_MUTATED", "trial manifests changed during probing")

    return {
        "schema": SCHEMA_PROBE,
        "run_id": run_record.get("run_id"),
        "source_sha": run_record.get("source_sha"),
        "observation_head_sha": run.source_sha(),
        "measured_path_drift": measured_path_drift(
            run_record.get("source_sha"), run.source_sha()
        ),
        "host_fingerprint": run_record.get("host_fingerprint"),
        "corpus_manifest_sha256": manifest_sha,
        "measurement": "process-level CPU and peak RSS; separate from engine_ns",
        "allocations": "NOT_MEASURED",
        "target_cpu_ns": TARGET_CPU_NS,
        "max_wall_ns": MAX_WALL_NS,
        "max_requests": MAX_REQUESTS,
        "warmups": WARMUP_REQUESTS,
        "rotation": [list(order) for order in ROTATION],
        "lane_selection": {str(n): PROBE_LANES[n] for n in PROBE_LANES},
        "probes": probes,
        "summary": summarize(probes),
        "trial_manifest_digests": after_digests,
    }


def summarize(probes: list[dict]) -> dict:
    """Min/median/max of CPU-per-request and peak RSS per engine and corpus."""
    summary = {}
    for engine in ENGINES:
        summary[engine] = {}
        for n in (10000, 100000):
            selected = [p for p in probes if p["engine"] == engine and p["n"] == n]
            if not selected:
                summary[engine][str(n)] = {"status": STATUS_BLOCKED_ENVIRONMENT}
                continue
            cpu = [p["cpu_ns_per_request"] for p in selected if p["cpu_ns_per_request"]]
            rss = [p["peak_rss_bytes"] for p in selected if p["peak_rss_bytes"]]
            statuses = [p["status"] for p in selected]
            summary[engine][str(n)] = {
                "probes": len(selected),
                "status": (
                    STATUS_MEASURED
                    if all(status == STATUS_MEASURED for status in statuses)
                    else STATUS_DIAGNOSTIC_LIMIT
                ),
                "cpu_ns_per_request": {
                    "values": cpu,
                    "min": min(cpu) if cpu else None,
                    "median": sorted(cpu)[len(cpu) // 2] if cpu else None,
                    "max": max(cpu) if cpu else None,
                },
                "peak_rss_bytes": {
                    "values": rss,
                    "min": min(rss) if rss else None,
                    "median": sorted(rss)[len(rss) // 2] if rss else None,
                    "max": max(rss) if rss else None,
                },
                "allocations": "NOT_MEASURED",
            }
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PR15D supplemental CPU/RSS probe.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = execute(os.path.abspath(args.run), idle_confirmed=args.idle_confirmed)
    except ResourceError as error:
        print(f"RESOURCE PROBE BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 4 if "ATTESTATION" in error.rule else 3
    run.write_json(args.out, report)
    print(
        json.dumps(
            {
                "status": "COMPLETE",
                "probes": len(report["probes"]),
                "allocations": report["allocations"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
