#!/usr/bin/env python3
"""PR 15F P0 benchmark-only query profiler (no production changes).

This driver reuses the frozen PR 15D corpus/adapter/oracle and the PR 15E-A
profiler transport, contention, report-extraction and prepared-state helpers.
It deliberately does **not** call PR 15E-A ``capture()`` or its attestation
machinery: PR 15F has its own capture schema and its own fixed lane matrix.
Idle is assumed only because the maintainer approved this plan for execution;
every timed capture still performs a real before/after contention probe.

Fixed CLI::

    python3 benchmarks/pr15f/profile_queries.py \\
        --prepared-run <absolute target/pr15e/...> \\
        --out <absolute target/pr15f/run-XX/queries/<lane>> \\
        --n 100000 --class common --k 100 --tool perf --seconds 60 \\
        --idle-confirmed
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
PR15E_PROFILE_PATH = os.path.join(REPO_ROOT, "benchmarks", "pr15e", "profile.py")
PR15E_VERIFY_PATH = os.path.join(REPO_ROOT, "benchmarks", "pr15e", "verify.py")
PR15D_RUN_PATH = os.path.join(REPO_ROOT, "benchmarks", "pr15d", "harness", "run.py")
PR15D_ADAPTER_PATH = os.path.join(
    REPO_ROOT, "benchmarks", "pr15d", "adapters", "quervant", "src", "main.rs"
)
PR15F_TARGET_ROOT = os.path.join(REPO_ROOT, "target", "pr15f")
PR15E_TARGET_ROOT = os.path.join(REPO_ROOT, "target", "pr15e")

PROBE_SCHEMA = "pr15f-reopen-probe-v1"
SCHEMA_CAPTURE = "pr15f-query-capture-v1"
SCHEMA_CAPTURE_FAILURE = "pr15f-query-capture-failure-v1"
AUTHORIZATION_BASIS = "operator_approved_assumed_idle_for_pr15f"

ENGINE = "quervant"
REGIME = "warm"
MIN_PERF_SAMPLES = 1000
ALLOWED_ZERO_LOST = 0
MAX_PROFILED_REQUESTS = 10_000_000

# Immutable evidence anchors. Recomputing these before publication proves the
# benchmark-only tooling did not silently change the frozen inputs or the
# profiler/transport semantics it reuses.
FROZEN_SOURCE_SHA256 = {
    "benchmarks/pr15d/adapters/quervant/src/main.rs": (
        "42d2858ec406aa01b2556504a07907e1b2bc9891d596c684b1a9ba99ede78a63"
    ),
    "benchmarks/pr15d/harness/run.py": (
        "8be6c21e5a2ac41a3dc12c17ab8bc5e91080c689323f7f05015919c01ff31243"
    ),
    "benchmarks/pr15d/corpus/oracle.py": (
        "4c37a72251b6b16e972161070297436c18b96421b09acd2665bce5c65abd20b2"
    ),
    "benchmarks/pr15e/profile.py": (
        "96eb5904b72024f0b19468f0e3bcc130b2b7e348faeb014fdabcce6ec7a5a2da"
    ),
    "benchmarks/pr15e/verify.py": (
        "ee86d6e19ff5619b817b571d45335a6b0d4177cbadd5f3df351d3601212348bd"
    ),
    "benchmarks/reports/pr15e-b1/optimized-three-engine-pr15d.json": (
        "7a726bf41fe52bfcd5763f7992f050045c76493abdbb9573e216d8aacd6974cd"
    ),
    "benchmarks/reports/pr15e-b1/cumulative-closeout.json": (
        "4ee745f9deb3a27030a7aac567ff6768e1dd674e11d471dde7cdd8dad389ee22"
    ),
}


def _load_module(module_name: str, path: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


eprofile = _load_module("pr15f_pr15e_profile", PR15E_PROFILE_PATH)
# Loaded for its side-effect-free constants only; the contention probe is reached
# through eprofile's own default dependency, never re-implemented here.
_load_module("pr15f_pr15d_run", PR15D_RUN_PATH)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BLOCKED = 3
EXIT_FAILED = 4
EXIT_HARD_STOP = 5
EXIT_UNSAFE = 6

# The nine mandatory warm perf lanes and their frozen capture windows.
PERF_LANES = (
    (10000, "absent", 100, 20),
    (10000, "rare", 100, 20),
    (10000, "medium", 100, 20),
    (10000, "common", 100, 20),
    (100000, "absent", 100, 30),
    (100000, "rare", 100, 30),
    (100000, "medium", 100, 30),
    (100000, "common", 100, 60),
    (100000, "common", 10, 60),
)

# Supplementary allocation captures (never a substitute for the perf matrix).
ALLOCATION_LANES = (
    (100000, "rare", 100, 30),
    (100000, "common", 100, 60),
)


class Pr15fError(Exception):
    """Typed, fail-closed classification of an affected capture or stage."""

    def __init__(self, status: str, code: str, detail: str, extra: dict | None = None):
        super().__init__(f"{status}/{code}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail
        self.extra = extra or {}


def blocked(code: str, detail: str, extra: dict | None = None) -> Pr15fError:
    return Pr15fError("BLOCKED", code, detail, extra)


def failed(code: str, detail: str, extra: dict | None = None) -> Pr15fError:
    return Pr15fError("FAILED", code, detail, extra)


def hard_stop(code: str, detail: str, extra: dict | None = None) -> Pr15fError:
    return Pr15fError("HARD_STOP", code, detail, extra)


def unsafe(code: str, detail: str, extra: dict | None = None) -> Pr15fError:
    return Pr15fError("UNSAFE", code, detail, extra)


def usage_error(detail: str) -> Pr15fError:
    return Pr15fError("USAGE", "invalid_invocation", detail)


EXIT_BY_STATUS = {
    "USAGE": EXIT_USAGE,
    "BLOCKED": EXIT_BLOCKED,
    "FAILED": EXIT_FAILED,
    "HARD_STOP": EXIT_HARD_STOP,
    "UNSAFE": EXIT_UNSAFE,
}


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------


def canonical_json_bytes(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: str, value) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_json(path: str):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def rel_path(path: str, root: str) -> str:
    return os.path.relpath(os.path.abspath(path), os.path.abspath(root)).replace(
        os.sep, "/"
    )


def source_lock() -> dict:
    """Recompute the SHA-256 of every frozen input this PR depends on."""
    observed = {}
    for relative, expected in FROZEN_SOURCE_SHA256.items():
        path = os.path.join(REPO_ROOT, relative)
        if not os.path.isfile(path):
            raise hard_stop("X01_FROZEN_MISSING", f"frozen input is missing: {relative}")
        digest = sha256_file(path)
        observed[relative] = {"sha256": digest, "expected": expected}
        if digest != expected:
            raise hard_stop(
                "X02_FROZEN_DRIFT",
                f"frozen input digest changed: {relative}",
                {"observed": digest, "expected": expected},
            )
    return observed


def tool_module_lock() -> dict:
    """Record the exact benchmark-only modules used for a capture."""
    paths = {
        "profile_queries": os.path.join(_THIS_DIR, "profile_queries.py"),
        "reopen_probe_manifest": os.path.join(
            _THIS_DIR, "reopen_probe", "Cargo.toml"
        ),
        "reopen_probe_lock": os.path.join(_THIS_DIR, "reopen_probe", "Cargo.lock"),
        "reopen_probe_source": os.path.join(_THIS_DIR, "reopen_probe", "src", "main.rs"),
    }
    return {
        name: {"bytes": os.path.getsize(path), "sha256": sha256_file(path)}
        for name, path in paths.items()
        if os.path.isfile(path)
    }


# ---------------------------------------------------------------------------
# Fixed lane matrix
# ---------------------------------------------------------------------------


def lane_id(n: int, class_name: str, k: int) -> str:
    return f"pr15f/n{n}/{class_name}/k{k}"


def lane_descriptor(n: int, class_name: str, k: int, tool: str, seconds: int) -> dict:
    if isinstance(n, bool) or not isinstance(n, int):
        raise usage_error(f"--n must be an integer, got {n!r}")
    if isinstance(k, bool) or not isinstance(k, int):
        raise usage_error(f"--k must be an integer, got {k!r}")
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise usage_error(f"--seconds must be an integer, got {seconds!r}")
    if class_name not in eprofile.CLASS_NAMES:
        raise usage_error(
            f"unknown class {class_name!r}; expected one of {eprofile.CLASS_NAMES}"
        )
    descriptor = eprofile.lane_descriptor(n, class_name, k)
    pr15f_id = lane_id(n, class_name, k)
    if tool == "perf":
        authorized = PERF_LANES
    elif tool == "heaptrack":
        authorized = ALLOCATION_LANES
    else:
        raise usage_error(f"unknown tool {tool!r}; expected perf or heaptrack")
    for entry in authorized:
        if entry == (n, class_name, k, seconds):
            descriptor.update(
                {
                    "tool": tool,
                    "seconds": seconds,
                    "pr15f_lane_id": pr15f_id,
                    "capture_id": f"{pr15f_id}/{tool}",
                    "rel_dir": (
                        f"queries/n{n}/{class_name}/k{k}/{tool}"
                        if tool == "perf"
                        else f"allocation/n{n}/{class_name}/k{k}/{tool}"
                    ),
                }
            )
            return descriptor
    raise usage_error(
        f"{tool} lane ({n}, {class_name}, {k}, {seconds}s) is outside the fixed "
        "PR 15F matrix"
    )


def perf_lane_descriptors() -> list[dict]:
    return [
        lane_descriptor(n, class_name, k, "perf", seconds)
        for n, class_name, k, seconds in PERF_LANES
    ]


def allocation_lane_descriptors() -> list[dict]:
    return [
        lane_descriptor(n, class_name, k, "heaptrack", seconds)
        for n, class_name, k, seconds in ALLOCATION_LANES
    ]


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def resolve_prepared_run(raw: str) -> str:
    resolved = eprofile.resolve_under(
        PR15E_TARGET_ROOT, raw, label="prepared run", base=REPO_ROOT
    )
    if not os.path.isdir(resolved):
        raise usage_error(f"prepared run does not exist: {raw!r}")
    if eprofile.iter_symlinks(resolved):
        raise unsafe("X29_SYMLINK", "prepared run contains symlinks")
    return resolved


def resolve_run_dir(raw: str, *, must_exist: bool) -> str:
    resolved = eprofile.resolve_under(
        PR15F_TARGET_ROOT, raw, label="PR 15F run directory", base=REPO_ROOT
    )
    if must_exist and not os.path.isdir(resolved):
        raise usage_error(f"run directory does not exist: {raw!r}")
    if not must_exist and os.path.exists(resolved):
        if not os.path.isdir(resolved):
            raise usage_error(f"run path is not a directory: {raw!r}")
    return resolved


def resolve_capture_dir(raw: str) -> str:
    """Capture directories are always created fresh under the PR 15F run root."""
    resolved = eprofile.resolve_under(
        PR15F_TARGET_ROOT, raw, label="capture directory", base=REPO_ROOT
    )
    parts = rel_path(resolved, PR15F_TARGET_ROOT).split("/")
    if len(parts) < 3 or parts[1] not in ("queries", "allocation"):
        raise unsafe(
            "X28_UNSAFE_PATH",
            "capture output must be <run>/queries/... or <run>/allocation/...",
        )
    if os.path.exists(resolved):
        raise unsafe(
            "X28_DESTINATION_EXISTS",
            f"capture directory already exists and is never overwritten: {raw!r}",
        )
    return resolved


# ---------------------------------------------------------------------------
# Prepared-state validation and oracle expectations
# ---------------------------------------------------------------------------


def verify_prepared_state(prepared_run: str, deps=None) -> dict:
    deps = deps or eprofile.Deps()
    prepared = eprofile._verify_prepared_state(prepared_run, deps)
    source_lock()
    return prepared


def lane_expectation(prepared: dict, descriptor: dict, rows_by_n: dict) -> dict:
    return eprofile._capture_lane_expectation(prepared, descriptor, rows_by_n)


# ---------------------------------------------------------------------------
# Profiled child transport
# ---------------------------------------------------------------------------


def _run_profiled_capture(
    *,
    run_dir: str,
    capture_dir: str,
    descriptor: dict,
    prepared: dict,
    tool_info: dict,
    expected: dict,
    deps,
) -> dict:
    binary = os.path.join(run_dir, prepared["build"]["binary_path"])
    index_dir = os.path.join(run_dir, prepared["indexes"][str(descriptor["n"])]["path"])
    argv = eprofile.profiler_argv(
        descriptor["tool"], tool_info, binary, index_dir, capture_dir
    )
    eprofile.validate_argv_target(argv, binary)
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        raise failed("X29_BUILD_OUTPUT", "prepared adapter binary is not executable")

    stderr_path = os.path.join(capture_dir, "profiler-stderr.txt")
    with open(stderr_path, "wb") as stderr_handle:
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_handle,
                bufsize=0,
                start_new_session=True,
                cwd=run_dir,
            )
        except OSError as error:
            raise blocked("BLOCKED_PROFILER", f"cannot launch profiler: {error}")

    evidence: dict = {
        "adapter_pid_samples": [],
        "warmups": 0,
        "profiled_queries": 0,
        "command": argv,
        "heaptrack_startup_preamble": None,
    }
    preamble_authorized = eprofile.preamble_applies(
        descriptor["tool"], tool_info.get("version")
    )
    if descriptor["tool"] == "heaptrack" and not preamble_authorized:
        evidence["heaptrack_startup_preamble"] = {
            "path": None,
            "lines": 0,
            "bytes": 0,
            "sha256": None,
            "heaptrack_version": eprofile.heaptrack_version(tool_info.get("version")),
            "reason": "profiler version is not 1.5.0; strict JSONL parsing applies",
        }

    def _record_preamble(raw: bytes) -> None:
        path = os.path.join(capture_dir, eprofile.HEAPTRACK_PREAMBLE_ARTIFACT)
        with open(path, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        evidence["heaptrack_startup_preamble"] = {
            "path": eprofile.HEAPTRACK_PREAMBLE_ARTIFACT,
            "lines": 2,
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
            "heaptrack_version": eprofile.heaptrack_version(tool_info.get("version")),
        }

    transport = eprofile.ProfiledTransport(
        process,
        label=descriptor["capture_id"],
        preamble_capture_dir=capture_dir if preamble_authorized else None,
        preamble_sink=_record_preamble if preamble_authorized else None,
    )
    try:

        def note_adapter_pids() -> None:
            pids = eprofile.wait_for_adapter_pid(
                process, binary, timeout=eprofile.ADAPTER_PID_DISCOVERY_SECONDS
            )
            if not pids:
                raise hard_stop(
                    "X22_PROFILER_TARGET",
                    "no descendant process matches the prepared Quervant adapter",
                )
            if len(pids) > 1:
                raise hard_stop(
                    "X22_PROFILER_TARGET",
                    f"multiple candidate adapter children: {pids}",
                )
            evidence["adapter_pid_samples"].append(pids[0])

        note_adapter_pids()
        for index in range(eprofile.WARMUPS):
            response = transport.request(
                {
                    "request_id": f"{descriptor['pr15f_lane_id']}:warmup:{index}",
                    "op": "query",
                    "field": descriptor["field"],
                    "term": descriptor["term"],
                    "k": descriptor["k"],
                    "mode": REGIME,
                }
            )
            eprofile.validate_response_against_oracle(response, descriptor, expected)
            evidence["warmups"] += 1

        note_adapter_pids()
        window_start = deps.now_utc()
        budget = float(descriptor["seconds"])
        deadline = time.monotonic() + budget
        profiled = 0
        while profiled < MAX_PROFILED_REQUESTS:
            if time.monotonic() >= deadline:
                break
            response = transport.request(
                {
                    "request_id": f"{descriptor['pr15f_lane_id']}:profiled:{profiled}",
                    "op": "query",
                    "field": descriptor["field"],
                    "term": descriptor["term"],
                    "k": descriptor["k"],
                    "mode": REGIME,
                }
            )
            eprofile.validate_response_against_oracle(response, descriptor, expected)
            profiled += 1
        evidence["profiled_queries"] = profiled
        evidence["profiled_window_seconds"] = round(time.monotonic() - (deadline - budget), 3)
        evidence["window_start_utc"] = eprofile.format_utc(window_start)
        evidence["window_end_utc"] = eprofile.format_utc(deps.now_utc())
        note_adapter_pids()

        transport.request(
            {"request_id": f"{descriptor['pr15f_lane_id']}:shutdown", "op": "shutdown"}
        )
        transport.close_stdin()
        try:
            returncode = process.wait(timeout=eprofile.PROFILER_EXIT_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            eprofile.terminate_group(process)
            raise failed(
                "X27_PROFILER_TIMEOUT",
                "profiler did not exit within the bounded grace period",
            )
        evidence["profiler_returncode"] = returncode
        if returncode != 0:
            raise failed(
                "X20_PROFILER_FAILED", f"{descriptor['tool']} exited with {returncode}"
            )
    except BaseException:
        eprofile.terminate_group(process)
        raise
    finally:
        transport.close()

    pids = sorted(set(evidence["adapter_pid_samples"]))
    if len(pids) != 1:
        raise hard_stop(
            "X22_PROFILER_TARGET", f"adapter PID set is not a single process: {pids}"
        )
    evidence["adapter_pid"] = pids[0]
    if evidence["warmups"] != eprofile.WARMUPS:
        raise failed("X23_WARMUPS", f"completed {evidence['warmups']} warmups")
    if evidence["profiled_queries"] < eprofile.MIN_PROFILED_REQUESTS:
        raise blocked(
            "X26_INSUFFICIENT_REQUESTS",
            f"only {evidence['profiled_queries']} profiled queries completed",
        )
    return evidence


# ---------------------------------------------------------------------------
# Artifact manifest and failure record
# ---------------------------------------------------------------------------


def artifact_manifest(capture_dir: str) -> list[dict]:
    entries = []
    for root, directories, files in os.walk(capture_dir, followlinks=False):
        directories.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            relative = rel_path(full, capture_dir)
            if relative in ("capture.json", "failure.json"):
                continue
            if os.path.islink(full) or not os.path.isfile(full):
                raise unsafe("X29_SYMLINK", f"unexpected capture artifact: {relative}")
            entries.append(
                {
                    "path": relative,
                    "bytes": os.path.getsize(full),
                    "sha256": sha256_file(full),
                }
            )
    entries.sort(key=lambda entry: entry["path"])
    if not entries:
        raise failed("X26_EMPTY_CAPTURE", "capture produced no artifacts")
    return entries


def _write_capture_failure(capture_dir: str, descriptor: dict, error: Pr15fError) -> None:
    payload = {
        "schema": SCHEMA_CAPTURE_FAILURE,
        "status": error.status,
        "code": error.code,
        "detail": error.detail,
        "capture_id": descriptor.get("capture_id"),
        "lane_id": descriptor.get("pr15f_lane_id"),
        "tool": descriptor.get("tool"),
        "n": descriptor.get("n"),
        "class": descriptor.get("class"),
        "k": descriptor.get("k"),
        "extra": error.extra,
    }
    try:
        write_json(os.path.join(capture_dir, "failure.json"), payload)
    except OSError:  # pragma: no cover - best effort
        pass


# ---------------------------------------------------------------------------
# Single capture
# ---------------------------------------------------------------------------


def _as_pr15f(error) -> "Pr15fError":
    return Pr15fError(
        getattr(error, "status", "FAILED"),
        getattr(error, "code", "X99"),
        getattr(error, "detail", str(error)),
        getattr(error, "extra", {}),
    )


def capture(args, deps=None) -> int:
    try:
        return _capture(args, deps)
    except eprofile.Pr15eError as error:
        raise _as_pr15f(error) from error


def _capture(args, deps=None) -> int:
    deps = deps or eprofile.Deps()
    if not getattr(args, "idle_confirmed", False):
        raise blocked(
            "BLOCKED_AUTHORIZATION",
            "--idle-confirmed is required; plan approval is the authorization basis",
        )
    descriptor = lane_descriptor(
        args.n, args.class_name, args.k, args.tool, args.seconds
    )
    prepared_run = resolve_prepared_run(args.prepared_run)
    capture_dir = resolve_capture_dir(args.out)
    prepared = verify_prepared_state(prepared_run, deps)
    _, rows_by_n = eprofile.load_corpus(prepared_run)
    expected = lane_expectation(prepared, descriptor, rows_by_n)

    tool_info = eprofile.resolve_tool(descriptor["tool"], deps)
    print_info = None
    if descriptor["tool"] == "heaptrack":
        print_info = deps.heaptrack_print_probe()

    os.makedirs(capture_dir)
    try:
        before = deps.contention_probe(
            os.path.join(capture_dir, "contention-before.json")
        )
        if before.get("state") != "clear":
            raise blocked(
                "X18_CONTENTION",
                f"contention before capture is {before.get('state')!r}",
                {"contention": before},
            )
        evidence = _run_profiled_capture(
            run_dir=prepared_run,
            capture_dir=capture_dir,
            descriptor=descriptor,
            prepared=prepared,
            tool_info=tool_info,
            expected=expected,
            deps=deps,
        )
        after = deps.contention_probe(
            os.path.join(capture_dir, "contention-after.json")
        )
        if after.get("state") != "clear":
            raise blocked(
                "X18_CONTENTION",
                f"contention after capture is {after.get('state')!r}",
                {"contention": after},
            )
        if descriptor["tool"] == "perf":
            tool_evidence = eprofile.generate_perf_reports(tool_info, capture_dir)
            validate_perf_evidence(tool_evidence)
        else:
            tool_evidence = eprofile.generate_heaptrack_report(
                tool_info, print_info, capture_dir
            )
        files = artifact_manifest(capture_dir)
        manifest = {
            "schema": SCHEMA_CAPTURE,
            "status": "CAPTURED",
            "capture_id": descriptor["capture_id"],
            "lane_id": descriptor["pr15f_lane_id"],
            "tool": descriptor["tool"],
            "n": descriptor["n"],
            "class": descriptor["class"],
            "field": descriptor["field"],
            "term": descriptor["term"],
            "k": descriptor["k"],
            "regime": REGIME,
            "seconds": descriptor["seconds"],
            "profiled_window_seconds": evidence["profiled_window_seconds"],
            "warmups": evidence["warmups"],
            "profiled_query_count": evidence["profiled_queries"],
            "warmup_in_capture": True,
            "perf_includes_protocol": True,
            "adapter_pid": evidence["adapter_pid"],
            "adapter_pid_sample_count": len(evidence["adapter_pid_samples"]),
            "first_utc": evidence["window_start_utc"],
            "last_utc": evidence["window_end_utc"],
            "source_sha": prepared["source"]["head_sha"],
            "prepared_digest": prepared["prepared_digest"],
            "authorization_basis": AUTHORIZATION_BASIS,
            "corpus_manifest_sha256": prepared["corpus"]["manifest_sha256"],
            "corpus_sha256": {
                str(key): value["sha256"]
                for key, value in prepared["corpus"]["corpora"].items()
            },
            "index_inventory_sha256": prepared["indexes"][str(descriptor["n"])][
                "inventory"
            ]["sha256"],
            "binary_sha256": prepared["build"]["binary_sha256"],
            "adapter_binary": prepared["build"]["binary_path"],
            "command": evidence["command"],
            "tool_version": tool_info["version"],
            "tool_path": tool_info["path"],
            "tool_origin": tool_info.get("origin", "path"),
            "tool_diagnostics": tool_info.get("diagnostics", []),
            "profiler_fallback": tool_info.get("fallback", False),
            "expected_total_hits": expected["total_hits"],
            "expected_doc_ids": expected["doc_ids"],
            "expected_digest": eprofile.expected_digest(expected),
            "contention_before": before.get("state"),
            "contention_after": after.get("state"),
            "tool_evidence": tool_evidence,
            "heaptrack_startup_preamble": evidence["heaptrack_startup_preamble"],
            "frozen_source_lock": source_lock(),
            "tool_module_lock": tool_module_lock(),
            "files": files,
            "test_fixture": False,
            "limitations": [
                "CPU samples include adapter startup, JSONL protocol and warmups.",
                "Instrumented captures are never compared with uninstrumented PR 15D-B latencies.",
                "Assumed-idle is the plan-approval authorization basis, not a measured host fact.",
                "Warm lanes reuse one adapter process; this is not an OS-cold page-cache claim.",
            ],
        }
        write_json(os.path.join(capture_dir, "capture.json"), manifest)
    except Pr15fError as error:
        _write_capture_failure(capture_dir, descriptor, error)
        raise
    except (OSError, ValueError, KeyError) as error:
        wrapped = failed("X99_UNEXPECTED", str(error))
        _write_capture_failure(capture_dir, descriptor, wrapped)
        raise wrapped

    print(
        canonical_json_bytes(
            {
                "status": "CAPTURED",
                "capture_id": descriptor["capture_id"],
                "tool": descriptor["tool"],
                "profiled_queries": evidence["profiled_queries"],
                "sample_count": tool_evidence.get("sample_count"),
                "lost_samples": tool_evidence.get("lost_samples"),
                "capture_sha256": sha256_file(
                    os.path.join(capture_dir, "capture.json")
                ),
            }
        ).decode("utf-8")
    )
    return EXIT_OK


def validate_perf_evidence(tool_evidence: dict) -> None:
    samples = tool_evidence.get("sample_count")
    if isinstance(samples, bool) or not isinstance(samples, int):
        raise blocked("X19_PERF_SAMPLES", "perf sample count is not an integer")
    if samples < MIN_PERF_SAMPLES:
        raise blocked(
            "X19_PERF_SAMPLES",
            f"only {samples} CPU samples captured; at least {MIN_PERF_SAMPLES} are required",
        )
    lost = tool_evidence.get("lost_samples")
    if isinstance(lost, bool) or not isinstance(lost, int):
        raise blocked("X19_PERF_SAMPLES", "perf lost-sample count is not an integer")
    if lost != ALLOWED_ZERO_LOST:
        raise blocked(
            "X19_PERF_LOST_SAMPLES",
            f"{lost} lost samples; zero lost samples are required",
        )
    if tool_evidence.get("symbolization", {}).get("quervant_mentions", 0) < 1:
        raise blocked("X19_PERF_SYMBOLS", "no symbolized Quervant frames")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profile_queries.py",
        description="PR 15F P0 benchmark-only query/allocation profiler.",
        allow_abbrev=False,
    )
    parser.add_argument("--prepared-run", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--class", dest="class_name", required=True)
    parser.add_argument("--k", type=int, required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--seconds", type=int, required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return capture(args)
    except Pr15fError as error:
        print(
            canonical_json_bytes(
                {"status": error.status, "code": error.code, "detail": error.detail}
            ).decode("utf-8")
        )
        print(f"{error.status} {error.code}: {error.detail}", file=sys.stderr)
        return EXIT_BY_STATUS.get(error.status, EXIT_FAILED)


if __name__ == "__main__":
    raise SystemExit(main())
