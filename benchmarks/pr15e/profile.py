#!/usr/bin/env python3
"""PR 15E-A exact-workload CPU and heap-allocation profiling driver.

Standard library only. This module is the *only* PR 15E-A orchestration code. It
reuses the frozen PR 15D v1 corpus, the independent oracle and the validated
Quervant adapter/harness helpers; it never re-implements query evaluation, never
edits a frozen fixture, and never emits an engine response of its own.

Fixed CLI::

    python3 benchmarks/pr15e/profile.py prepare --out target/pr15e/<run-id>
    python3 benchmarks/pr15e/profile.py capture --run target/pr15e/<run-id> \\
        --n 100000 --class common --k 100 --tool perf --seconds 60 --idle-confirmed

Nothing outside ``target/pr15e/`` may be written. Evidence integrity, report
publication and attribution validation live in ``verify.py``.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import hashlib
import importlib.util
import json
import os
import platform
import re
import selectors
import shutil
import socket
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Repository layout and frozen PR 15D prerequisites
# ---------------------------------------------------------------------------

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
PR15D_ROOT = os.path.join(REPO_ROOT, "benchmarks", "pr15d")
TARGET_ROOT = os.path.join(REPO_ROOT, "target", "pr15e")

FROZEN_FILES = {
    "spec": "benchmarks/pr15d/spec/pr15d_v1.json",
    "oracle": "benchmarks/pr15d/corpus/oracle.py",
    "generator": "benchmarks/pr15d/corpus/generate.py",
    "protocol": "benchmarks/pr15d/protocol/schema.json",
    "harness_run": "benchmarks/pr15d/harness/run.py",
    "adapter_source": "benchmarks/pr15d/adapters/quervant/src/main.rs",
    "adapter_manifest": "benchmarks/pr15d/adapters/quervant/Cargo.toml",
    "adapter_lock": "benchmarks/pr15d/adapters/quervant/Cargo.lock",
    "canonical_report": "benchmarks/reports/pr15d/pr15d-qualified.json",
}
DEFAULT_CANONICAL_REPORT = os.path.join(REPO_ROOT, FROZEN_FILES["canonical_report"])

SCHEMA_PREPARE = "pr15e-prepare-v1"
SCHEMA_PREPARE_FAILED = "pr15e-prepare-failed-v1"
SCHEMA_CAPTURE = "pr15e-capture-v1"
SCHEMA_CAPTURE_FAILURE = "pr15e-capture-failure-v1"
SCHEMA_VERIFICATION = "pr15e-verification-v1"
SCHEMA_ATTRIBUTION = "pr15e-attribution-v1"
SCHEMA_PROFILE_MANIFEST = "pr15e-profile-manifest-v1"
SCHEMA_ATTESTATION = "pr15e-attestation-v1"

ADAPTER_SCHEMA = "pr15d-adapter-v1"
ENGINE = "quervant"
SYMBOL_NAME = "pr15d-quervant-adapter"
ANALYZER = "keyword-exact"

WORKLOAD = "pr15d_v1"
CLASSES = (
    ("absent", "key", "never"),
    ("rare", "key", "singleton"),
    ("medium", "group", "medium"),
    ("common", "key", "common"),
)
CLASS_NAMES = tuple(entry[0] for entry in CLASSES)
N_VALUES = (10000, 100000)
K_VALUES = (10, 100)
PRIMARY_K = 100
SECONDARY_K = 10
REGIME = "warm"

TOOLS = ("perf", "heaptrack")
WARMUPS = 5
MIN_PROFILED_REQUESTS = 5
MAX_RESPONSE_BYTES = 1024 * 1024
RESPONSE_TIMEOUT_SECONDS = 30.0
PROFILER_EXIT_GRACE_SECONDS = 30.0
ATTESTATION_SLACK_SECONDS = 120
MIN_PERF_SAMPLES = 100
ADAPTER_PID_DISCOVERY_SECONDS = 10.0
MAX_PROFILED_REQUESTS = 10_000_000

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BLOCKED = 3
EXIT_FAILED = 4
EXIT_HARD_STOP = 5
EXIT_UNSAFE = 6

ATTRIBUTION_CATEGORIES = (
    "adapter_protocol",
    "snapshot_and_reader",
    "query_validation_and_plan",
    "live_doc_and_stats",
    "postings_and_candidate_membership",
    "bm25_scoring",
    "sort_and_top_k",
    "projection_and_materialization",
    "allocator_or_runtime",
    "unknown",
)
ATTRIBUTION_KINDS = {
    "self_cpu_percent": "percent",
    "inclusive_stack_percent": "percent",
    "allocation_count": "allocations",
    "allocated_bytes": "bytes",
    "unknown": "not_measured",
}
ATTRIBUTION_INTERPRETATIONS = ("MEASURED_EVIDENCE", "HYPOTHESIS", "UNRESOLVED")
FORBIDDEN_EVIDENCE_KEYS = (
    "sum_inclusive_cpu_percent",
    "inferred_stage_ns",
)

# New files this PR is allowed to add; every other tracked path is protected.
PR15E_ALLOWED_PREFIXES = (
    "benchmarks/pr15e/",
    "benchmarks/reports/pr15e-a/",
    "docs/pr-artifacts/pr-15e-a/",
)
PR15E_ALLOWED_FILES = ("benchmarks/README.md", "docs/BENCHMARKING.md")


class Pr15eError(Exception):
    """A typed, fail-closed classification of an affected capture or stage."""

    def __init__(self, status: str, code: str, detail: str, extra: dict | None = None):
        super().__init__(f"{status}/{code}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail
        self.extra = extra or {}


def blocked(code: str, detail: str, extra: dict | None = None) -> Pr15eError:
    return Pr15eError("BLOCKED", code, detail, extra)


def failed(code: str, detail: str, extra: dict | None = None) -> Pr15eError:
    return Pr15eError("FAILED", code, detail, extra)


def hard_stop(code: str, detail: str, extra: dict | None = None) -> Pr15eError:
    return Pr15eError("HARD_STOP", code, detail, extra)


def unsafe(code: str, detail: str, extra: dict | None = None) -> Pr15eError:
    return Pr15eError("UNSAFE", code, detail, extra)


def usage_error(detail: str) -> Pr15eError:
    return Pr15eError("USAGE", "invalid_invocation", detail)


EXIT_BY_STATUS = {
    "USAGE": EXIT_USAGE,
    "BLOCKED": EXIT_BLOCKED,
    "FAILED": EXIT_FAILED,
    "HARD_STOP": EXIT_HARD_STOP,
    "UNSAFE": EXIT_UNSAFE,
}


# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------


def _load_module(module_name: str, path: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


run = _load_module("pr15e_pr15d_run", os.path.join(PR15D_ROOT, "harness", "run.py"))
oracle = _load_module("pr15e_pr15d_oracle", os.path.join(PR15D_ROOT, "corpus", "oracle.py"))
generate = _load_module(
    "pr15e_pr15d_generate", os.path.join(PR15D_ROOT, "corpus", "generate.py")
)


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


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def format_utc(moment: datetime.datetime) -> str:
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(text) -> datetime.datetime:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("expected an ISO-8601 UTC timestamp")
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    moment = datetime.datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        raise ValueError("timestamp must carry an explicit UTC offset")
    return moment.astimezone(datetime.timezone.utc)


def _invoke(argv, *, timeout=None, env=None, cwd=None):
    return subprocess.run(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        env=env,
        cwd=cwd,
        check=False,
    )


def first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def _reject_dotdot(raw: str) -> None:
    if not isinstance(raw, str) or not raw.strip():
        raise usage_error("a non-empty path is required")
    if "\x00" in raw:
        raise unsafe("X28_UNSAFE_PATH", "NUL byte in path")
    for part in re.split(r"[\\/]+", raw):
        if part == "..":
            raise unsafe("X28_UNSAFE_PATH", f"parent traversal is refused: {raw!r}")


def _real(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def _assert_no_symlinks_below(base: str, target: str) -> None:
    base_abs = os.path.abspath(base)
    target_abs = os.path.abspath(target)
    try:
        relative = os.path.relpath(target_abs, base_abs)
    except ValueError:  # pragma: no cover - different drives
        raise unsafe("X28_UNSAFE_PATH", f"{target!r} is not below {base!r}")
    if relative == "." or relative.startswith(".."):
        return
    current = base_abs
    for part in relative.split(os.sep):
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise unsafe("X29_SYMLINK", f"symlink in path: {rel_path(current, base_abs)}")


def resolve_under(root: str, raw: str, *, label: str, base: str | None = None) -> str:
    _reject_dotdot(raw)
    candidate = raw if os.path.isabs(raw) else os.path.join(base or REPO_ROOT, raw)
    _assert_no_symlinks_below(root, os.path.abspath(candidate))
    resolved = _real(candidate)
    root_real = _real(root)
    try:
        common = os.path.commonpath([resolved, root_real])
    except ValueError:  # pragma: no cover - different drives
        raise unsafe("X28_UNSAFE_PATH", f"{label} is not inside {root!r}")
    if common != root_real:
        raise unsafe("X28_UNSAFE_PATH", f"{label} escapes {root!r}: {raw!r}")
    if resolved == root_real:
        raise unsafe("X28_UNSAFE_PATH", f"{label} may not be {root!r} itself")
    _assert_no_symlinks_below(root_real, resolved)
    return resolved


def resolve_run_dir(raw: str, *, must_exist: bool | None) -> str:
    resolved = resolve_under(TARGET_ROOT, raw, label="run directory")
    if must_exist is True and not os.path.isdir(resolved):
        raise usage_error(f"run directory does not exist: {raw!r}")
    if must_exist is False and os.path.exists(resolved):
        if not os.path.isdir(resolved):
            raise unsafe("X28_UNSAFE_PATH", f"run path is not a directory: {raw!r}")
        if os.listdir(resolved):
            raise unsafe(
                "X28_DESTINATION_EXISTS", f"run directory is not empty: {raw!r}"
            )
    return resolved


def iter_symlinks(path: str) -> list[str]:
    """Return every symlink found at or below ``path`` (relative, sorted)."""
    found: list[str] = []
    if os.path.islink(path):
        found.append(".")
    for root, directories, files in os.walk(path, followlinks=False):
        for name in sorted(directories):
            full = os.path.join(root, name)
            if os.path.islink(full):
                found.append(rel_path(full, path))
        for name in sorted(files):
            full = os.path.join(root, name)
            if os.path.islink(full):
                found.append(rel_path(full, path))
    return sorted(found)


# ---------------------------------------------------------------------------
# Fixed matrix (no other combination is authorized)
# ---------------------------------------------------------------------------


def class_descriptor(class_name: str) -> dict:
    for name, field, term in CLASSES:
        if name == class_name:
            return {"class": name, "field": field, "term": term}
    raise usage_error(f"unknown class {class_name!r}; expected one of {CLASS_NAMES}")


def lane_descriptor(n: int, class_name: str, k: int) -> dict:
    if isinstance(n, bool) or not isinstance(n, int) or n not in N_VALUES:
        raise usage_error(f"unsupported N {n!r}; the fixed matrix is {list(N_VALUES)}")
    if isinstance(k, bool) or not isinstance(k, int) or k not in K_VALUES:
        raise usage_error(f"unsupported K {k!r}; the fixed matrix is {list(K_VALUES)}")
    descriptor = class_descriptor(class_name)
    if k == SECONDARY_K and n != 100000:
        raise usage_error(
            "the K=10 control lane exists only for N=100000; "
            f"refusing N={n}"
        )
    descriptor.update({"n": n, "k": k})
    descriptor["lane_id"] = lane_id(n, class_name, k)
    return descriptor


def lane_id(n: int, class_name: str, k: int) -> str:
    return f"pr15e/n{n}/{class_name}/k{k}"


def capture_id(n: int, class_name: str, k: int, tool: str) -> str:
    return f"{lane_id(n, class_name, k)}/{tool}"


def capture_rel_dir(n: int, class_name: str, k: int, tool: str) -> str:
    return f"captures/n{n}/{class_name}/k{k}/{tool}"


def lane_seconds(n: int, class_name: str) -> int:
    if n == 10000:
        return 20
    if class_name == "common":
        return 60
    return 30


def lane_required_tools(n: int, class_name: str, k: int) -> tuple[str, ...]:
    if n == 10000 and k == PRIMARY_K:
        return TOOLS
    if n == 100000 and k == PRIMARY_K:
        return TOOLS
    if n == 100000 and k == SECONDARY_K:
        return ("perf",)
    return ()


def required_captures() -> list[dict]:
    """Return the fixed 20 captures in the prescribed execution order."""
    entries: list[dict] = []
    ordered_lanes = (
        [(10000, name, PRIMARY_K) for name in CLASS_NAMES]
        + [(100000, name, PRIMARY_K) for name in CLASS_NAMES]
        + [(100000, name, SECONDARY_K) for name in CLASS_NAMES]
    )
    for n, class_name, k in ordered_lanes:
        for tool in lane_required_tools(n, class_name, k):
            descriptor = lane_descriptor(n, class_name, k)
            entries.append(
                {
                    **descriptor,
                    "tool": tool,
                    "seconds": lane_seconds(n, class_name),
                    "capture_id": capture_id(n, class_name, k, tool),
                    "rel_dir": capture_rel_dir(n, class_name, k, tool),
                }
            )
    return entries


def required_capture_keys() -> set[str]:
    return {entry["capture_id"] for entry in required_captures()}


def primary_lane_ids() -> list[str]:
    return [lane_id(100000, name, PRIMARY_K) for name in CLASS_NAMES]


def validate_capture_args(n, class_name, k, tool, seconds) -> dict:
    for label, value in (("n", n), ("k", k), ("seconds", seconds)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise usage_error(f"{label} must be an integer, got {value!r}")
    if tool not in TOOLS:
        raise usage_error(f"unknown tool {tool!r}; expected one of {list(TOOLS)}")
    descriptor = lane_descriptor(n, class_name, k)
    authorized = lane_required_tools(n, class_name, k)
    if tool not in authorized:
        raise usage_error(
            f"{capture_id(n, class_name, k, tool)} is outside the authorized matrix"
        )
    prescribed = lane_seconds(n, class_name)
    if seconds != prescribed:
        raise usage_error(
            f"{lane_id(n, class_name, k)} requires --seconds {prescribed}, "
            f"got {seconds}"
        )
    descriptor.update(
        {
            "tool": tool,
            "seconds": prescribed,
            "capture_id": capture_id(n, class_name, k, tool),
            "rel_dir": capture_rel_dir(n, class_name, k, tool),
        }
    )
    return descriptor


# ---------------------------------------------------------------------------
# Frozen-source validation (P0 prerequisites)
# ---------------------------------------------------------------------------


def frozen_file_paths() -> dict[str, str]:
    return {name: os.path.join(REPO_ROOT, path) for name, path in FROZEN_FILES.items()}


def check_15d_prerequisites(canonical_report: str | None = None) -> dict:
    """Fail closed unless the merged PR 15D-B contract is present and corrected."""
    paths = frozen_file_paths()
    paths["canonical_report"] = canonical_report or DEFAULT_CANONICAL_REPORT
    missing = [name for name, path in paths.items() if not os.path.isfile(path)]
    if missing:
        raise hard_stop(
            "X01_PR15D_MISSING", f"missing frozen PR 15D files: {sorted(missing)}"
        )

    adapter_source = read_text(paths["adapter_source"])
    harness_source = read_text(paths["harness_run"])
    if adapter_source.count("struct QuerySession") != 1:
        raise hard_stop("X05_PR15D_DIVERGED", "adapter QuerySession shape changed")
    if adapter_source.count("session = Some(QuerySession::open(path)?);") != 1:
        raise hard_stop(
            "X05_PR15D_DIVERGED",
            "adapter must open exactly one QuerySession per process",
        )
    if adapter_source.count("if session.is_none()") != 1:
        raise hard_stop(
            "X05_PR15D_DIVERGED", "adapter no longer reuses one session per process"
        )
    if "One query session per process" not in adapter_source:
        raise hard_stop(
            "X05_PR15D_DIVERGED", "adapter lost the one-snapshot-per-process contract"
        )
    for required in ("def build_index(", "class AdapterProcess", "def check_contention("):
        if required not in harness_source:
            raise hard_stop("X05_PR15D_DIVERGED", f"run.py is missing {required!r}")

    spec = read_json(paths["spec"])
    if spec.get("status") != "FROZEN" or spec.get("workload") != WORKLOAD:
        raise hard_stop("X05_PR15D_DIVERGED", "frozen spec is not FROZEN/pr15d_v1")
    if spec.get("corpus", {}).get("sizes") != list(N_VALUES):
        raise hard_stop("X05_PR15D_DIVERGED", "frozen corpus sizes changed")
    declared_classes = [
        (entry.get("name"), entry.get("field"), entry.get("term"))
        for entry in spec.get("classes", [])
    ]
    if declared_classes != list(CLASSES):
        raise hard_stop("X05_PR15D_DIVERGED", "frozen query classes changed")
    matrix = spec.get("matrix", {})
    if matrix.get("warmups_per_warm_lane") != WARMUPS:
        raise hard_stop("X05_PR15D_DIVERGED", "frozen warmup count changed")
    if sorted(matrix.get("k_values", [])) != sorted(K_VALUES):
        raise hard_stop("X05_PR15D_DIVERGED", "frozen K values changed")
    if spec.get("score_comparison") != "NOT_APPLICABLE":
        raise hard_stop("X05_PR15D_DIVERGED", "scored lane is no longer excluded")

    report = read_json(paths["canonical_report"])
    if report.get("schema") != "pr15d-aggregate-v1" or report.get("status") != "QUALIFIED":
        raise hard_stop(
            "X01_PR15D_NOT_QUALIFIED", "canonical PR 15D report is not QUALIFIED"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", str(report.get("source_sha", ""))):
        raise hard_stop("X01_PR15D_NOT_QUALIFIED", "canonical report source_sha invalid")
    if "materialisation" not in str(report.get("timing_boundary", "")):
        raise hard_stop(
            "X05_PR15D_DIVERGED", "canonical report timing boundary is not corrected"
        )
    return {"spec": spec, "report": report, "paths": paths}


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def source_lock() -> dict:
    lock = {}
    for name, path in frozen_file_paths().items():
        relative = FROZEN_FILES[name]
        lock[name] = {
            "path": relative,
            "bytes": os.path.getsize(path),
            "sha256": sha256_file(path),
        }
    return lock


# ---------------------------------------------------------------------------
# Git / host probes
# ---------------------------------------------------------------------------


def _git(*args) -> str | None:
    result = _invoke(["git", *args], cwd=REPO_ROOT)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_head_sha() -> str:
    value = _git("rev-parse", "HEAD")
    if not value or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise blocked("BLOCKED_ENVIRONMENT", "cannot resolve the git HEAD SHA")
    return value


def git_tree_clean() -> bool:
    value = _git("status", "--porcelain=v1")
    return value is not None and value == ""


def git_ref_sha(ref: str) -> str | None:
    value = _git("rev-parse", ref)
    if value and re.fullmatch(r"[0-9a-f]{40}", value):
        return value
    return None


def hostname() -> str:
    return socket.gethostname()


def cpu_model() -> str | None:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:  # pragma: no cover - /proc absent
        return None
    return None


def filesystem_type(path: str) -> str | None:
    """Resolve the backing filesystem type without requiring privileges."""
    target = _real(path)
    best_mount = None
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                fields = line.split()
                if len(fields) < 3:
                    continue
                mount_point = fields[1].replace("\\040", " ")
                if target == mount_point or target.startswith(mount_point.rstrip("/") + "/"):
                    if best_mount is None or len(mount_point) > len(best_mount[0]):
                        best_mount = (mount_point, fields[2])
    except OSError:  # pragma: no cover - /proc absent
        best_mount = None
    if best_mount is not None:
        kind = best_mount[1]
        if kind in ("ext2/ext3", "ext2", "ext3"):
            return "ext4"
        return kind
    result = _invoke(["stat", "-f", "-c", "%T", path])
    if result.returncode != 0:
        return None
    kind = first_line(result.stdout) or None
    if kind in ("ext2/ext3", "ext2", "ext3"):
        return "ext4"
    return kind


def is_wsl() -> bool:
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="replace") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:  # pragma: no cover - /proc absent
        return False


def host_environment() -> dict:
    return {
        "kernel": platform.release(),
        "machine": platform.machine(),
        "wsl": is_wsl(),
        "filesystem": filesystem_type(REPO_ROOT),
        "cpu_model": cpu_model(),
        "python": platform.python_version(),
    }


def host_fingerprint(environment: dict) -> str:
    return sha256_bytes(canonical_json_bytes(environment))


# ---------------------------------------------------------------------------
# Profiler discovery (never installs, never escalates)
# ---------------------------------------------------------------------------


def _probe_tool(argv: list[str], pattern: str) -> dict | None:
    try:
        result = _invoke(argv, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        return None
    match = re.search(pattern, output)
    if not match:
        return None
    return {"version": match.group(0), "raw": first_line(output)}


def discover_perf() -> dict:
    """Locate a usable ``perf``; nothing is installed, created or shimmed (X12)."""
    diagnostics: list[dict] = []
    candidates: list[tuple[str, str]] = []
    on_path = shutil.which("perf")
    if on_path:
        candidates.append((on_path, "path"))
    for match in sorted(glob.glob("/usr/lib/linux-tools/*/perf")):
        candidates.append((match, "versioned"))
    for path, origin in candidates:
        if not (os.path.isfile(path) and os.access(path, os.X_OK)):
            diagnostics.append({"path": path, "origin": origin, "error": "not executable"})
            continue
        probe = _probe_tool([path, "--version"], r"(?m)^perf version .*$")
        if probe is None:
            result = _invoke([path, "--version"], timeout=30)
            diagnostics.append(
                {
                    "path": path,
                    "origin": origin,
                    "returncode": result.returncode,
                    "stderr": first_line(result.stderr),
                }
            )
            continue
        return {
            "path": path,
            "real_path": os.path.realpath(path),
            "origin": origin,
            "version": probe["raw"],
            "kernel": platform.release(),
            "diagnostics": diagnostics,
            "fallback": origin == "versioned",
        }
    raise blocked(
        "X13_PERF_UNAVAILABLE",
        "no usable perf binary found (wrapper and versioned fallbacks failed)",
        {"diagnostics": diagnostics},
    )


def discover_heaptrack() -> dict:
    path = shutil.which("heaptrack")
    if not path:
        raise blocked("X11_HEAPTRACK_UNAVAILABLE", "heaptrack is not installed")
    probe = _probe_tool([path, "--version"], r"(?m)^heaptrack \d+.*$")
    if probe is None:
        raise blocked("X11_HEAPTRACK_UNAVAILABLE", "heaptrack --version failed")
    return {"path": path, "version": probe["raw"]}


def discover_heaptrack_print() -> dict:
    path = shutil.which("heaptrack_print")
    if not path:
        raise blocked("X11_HEAPTRACK_PRINT_UNAVAILABLE", "heaptrack_print is not installed")
    probe = _probe_tool([path, "--version"], r"(?m)^heaptrack_print \d+.*$")
    if probe is None:
        raise blocked("X11_HEAPTRACK_PRINT_UNAVAILABLE", "heaptrack_print --version failed")
    return {"path": path, "version": probe["raw"]}


def resolve_tool(tool: str, deps: "Deps") -> dict:
    if tool == "perf":
        return deps.perf_probe()
    if tool == "heaptrack":
        return deps.heaptrack_probe()
    raise usage_error(f"unknown tool {tool!r}")


# ---------------------------------------------------------------------------
# Index-file inventory
# ---------------------------------------------------------------------------


def index_inventory(index_dir: str) -> dict:
    if not os.path.isdir(index_dir):
        raise failed("X24_INDEX_MISSING", f"index directory is missing: {index_dir}")
    symlinks = iter_symlinks(index_dir)
    if symlinks:
        raise unsafe("X29_SYMLINK", f"index tree contains symlinks: {symlinks[:5]}")
    entries = []
    for root, directories, files in os.walk(index_dir, followlinks=False):
        directories.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            if os.path.islink(full) or not os.path.isfile(full):
                raise unsafe("X29_SYMLINK", f"unexpected index entry: {full}")
            entries.append(
                {
                    "path": rel_path(full, index_dir),
                    "bytes": os.path.getsize(full),
                    "sha256": sha256_file(full),
                }
            )
    entries.sort(key=lambda entry: entry["path"])
    if not entries:
        raise failed("X24_INDEX_EMPTY", f"index directory is empty: {index_dir}")
    digest = sha256_bytes(canonical_json_bytes(entries))
    return {"entries": entries, "sha256": digest, "file_count": len(entries),
            "bytes": sum(entry["bytes"] for entry in entries)}


def compare_index_inventory(index_dir: str, recorded: dict) -> list[str]:
    violations: list[str] = []
    try:
        actual = index_inventory(index_dir)
    except Pr15eError as error:
        return [f"{error.code}: {error.detail}"]
    if actual["sha256"] != recorded.get("sha256"):
        violations.append(
            "X24_INDEX_CHANGED: index inventory digest differs from prepare.json"
        )
    if actual["file_count"] != recorded.get("file_count"):
        violations.append("X24_INDEX_CHANGED: index file count differs")
    if actual["bytes"] != recorded.get("bytes"):
        violations.append("X24_INDEX_CHANGED: index byte total differs")
    return violations


# ---------------------------------------------------------------------------
# Oracle helpers
# ---------------------------------------------------------------------------


def expected_digest(expected: dict) -> str:
    return sha256_bytes(canonical_json_bytes(expected))


def recompute_expected(rows_by_n: dict, descriptor: dict) -> dict:
    return oracle.expected(
        rows_by_n[descriptor["n"]],
        descriptor["field"],
        descriptor["term"],
        descriptor["k"],
    )


def load_corpus(run_dir: str) -> tuple[dict, dict[int, list]]:
    corpus_dir = os.path.join(run_dir, "corpus")
    try:
        return oracle.load_and_verify(corpus_dir)
    except oracle.CorpusError as error:
        raise failed("X24_CORPUS_INVALID", f"{error.code}: {error.detail}")


def validate_response_against_oracle(response: dict, descriptor: dict, expected: dict) -> None:
    engine_ns = response.get("engine_ns")
    if isinstance(engine_ns, bool) or not isinstance(engine_ns, int) or engine_ns <= 0:
        raise hard_stop(
            "X22_PROTOCOL", f"{descriptor['lane_id']}: invalid engine_ns {engine_ns!r}"
        )
    if response.get("total_hits") != expected["total_hits"]:
        raise hard_stop(
            "X23_ORACLE",
            f"{descriptor['lane_id']}: total_hits {response.get('total_hits')!r} "
            f"!= oracle {expected['total_hits']!r}",
            {"response": _redact_response(response)},
        )
    if response.get("doc_ids") != expected["doc_ids"]:
        raise hard_stop(
            "X23_ORACLE",
            f"{descriptor['lane_id']}: doc_ids differ from the independent oracle",
            {"response": _redact_response(response)},
        )


def _redact_response(response: dict) -> dict:
    keys = ("schema", "engine", "request_id", "status", "total_hits", "doc_ids")
    return {key: response.get(key) for key in keys if key in response}


# ---------------------------------------------------------------------------
# Attestation
# ---------------------------------------------------------------------------


def load_attestation(run_dir: str, seconds: int, deps: "Deps") -> dict:
    path = os.path.join(run_dir, "attestation.json")
    if not os.path.isfile(path):
        raise blocked(
            "BLOCKED_ATTESTATION",
            "no operator attestation at <run>/attestation.json; a passed flag is not evidence",
        )
    try:
        attestation = read_json(path)
    except (OSError, ValueError) as error:
        raise blocked("BLOCKED_ATTESTATION", f"unreadable attestation: {error}")
    if attestation.get("schema", SCHEMA_ATTESTATION) != SCHEMA_ATTESTATION:
        raise blocked("BLOCKED_ATTESTATION", "attestation schema mismatch")
    statement = attestation.get("operator_statement")
    if not isinstance(statement, str) or "15E-A" not in statement:
        raise blocked(
            "BLOCKED_ATTESTATION",
            "attestation must contain the verbatim operator statement naming PR 15E-A",
        )
    host = attestation.get("host")
    current_host = deps.hostname()
    if not isinstance(host, str) or host != current_host:
        raise blocked(
            "BLOCKED_ATTESTATION", f"attestation host {host!r} != current host"
        )
    try:
        start = parse_utc(attestation.get("start_utc"))
        end = parse_utc(attestation.get("end_utc"))
    except (ValueError, TypeError) as error:
        raise blocked("BLOCKED_ATTESTATION", f"invalid attestation window: {error}")
    if end <= start:
        raise blocked("BLOCKED_ATTESTATION", "attestation window is empty")
    now = deps.now_utc()
    if not (start <= now <= end):
        raise blocked(
            "BLOCKED_ATTESTATION",
            f"current UTC {format_utc(now)} is outside the attested window",
        )
    remaining = (end - now).total_seconds()
    if remaining < seconds + ATTESTATION_SLACK_SECONDS:
        raise blocked(
            "BLOCKED_ATTESTATION",
            f"only {remaining:.0f}s of the attested window remain; "
            f"{seconds + ATTESTATION_SLACK_SECONDS}s are required",
        )
    return {
        "host": host,
        "start_utc": format_utc(start),
        "end_utc": format_utc(end),
        "operator_statement": statement,
    }


def recheck_window(attestation: dict, deps: "Deps") -> None:
    now = deps.now_utc()
    try:
        end = parse_utc(attestation["end_utc"])
    except (ValueError, KeyError) as error:  # pragma: no cover - validated earlier
        raise blocked("BLOCKED_ATTESTATION", f"invalid attestation end: {error}")
    if now > end:
        raise blocked(
            "OUTSIDE_WINDOW",
            f"the attested window ended at {attestation['end_utc']}; capture not qualified",
        )


# ---------------------------------------------------------------------------
# Dependencies (explicit seams for deterministic tests; production defaults)
# ---------------------------------------------------------------------------


class Deps:
    """Production dependencies, overridable per test without touching the engine."""

    def __init__(
        self,
        *,
        repo_root: str | None = None,
        target_root: str | None = None,
        head_sha=None,
        tree_clean=None,
        hostname_probe=None,
        now_utc=None,
        perf_probe=None,
        heaptrack_probe=None,
        heaptrack_print_probe=None,
        contention_probe=None,
        canonical_report: str | None = None,
        loop_seconds=None,
    ):
        self.repo_root = repo_root or REPO_ROOT
        self.target_root = target_root or TARGET_ROOT
        self.head_sha = head_sha or git_head_sha
        self.tree_clean = tree_clean or git_tree_clean
        self.hostname = hostname_probe or hostname
        self.now_utc = now_utc or utcnow
        self.perf_probe = perf_probe or discover_perf
        self.heaptrack_probe = heaptrack_probe or discover_heaptrack
        self.heaptrack_print_probe = heaptrack_print_probe or discover_heaptrack_print
        self.contention_probe = contention_probe or run.check_contention
        self.canonical_report = canonical_report or DEFAULT_CANONICAL_REPORT
        self.loop_seconds = loop_seconds or (lambda prescribed: float(prescribed))


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------


def required_adapter_evidence_keys() -> tuple[str, ...]:
    return (
        "adapter_binary_sha256",
        "release_profile",
        "documents_indexed",
        "documents_verified",
        "oracle_ok",
        "index_backend",
        "analyzer",
    )


def assert_real_adapter_evidence(record: dict) -> None:
    """Reject mocked/synthetic engine output as integration evidence (T10)."""
    if not isinstance(record, dict):
        raise failed("X30_MOCK_EVIDENCE", "adapter evidence must be a mapping")
    if record.get("adapter") in ("mock", "fake", "synthetic") or record.get(
        "source"
    ) in ("mock", "fake"):
        raise failed("X30_MOCK_EVIDENCE", "mocked adapter output is not evidence")
    missing = [key for key in required_adapter_evidence_keys() if not record.get(key)]
    if missing:
        raise failed("X30_MOCK_EVIDENCE", f"adapter evidence is incomplete: {missing}")
    if record.get("documents_indexed") != record.get("documents_verified"):
        raise failed(
            "X30_MOCK_EVIDENCE", "indexed and reopened document counts disagree"
        )
    if record.get("index_backend") != "FsDirectory":
        raise failed("X30_MOCK_EVIDENCE", "index backend is not the real FsDirectory")
    if record.get("analyzer") != ANALYZER:
        raise failed("X30_MOCK_EVIDENCE", f"analyzer is not {ANALYZER!r}")


def classify_diff_paths(paths) -> list[str]:
    """Return the changed paths that PR 15E-A is not allowed to touch (T01)."""
    violations = []
    for path in paths:
        normalized = str(path).replace(os.sep, "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized in PR15E_ALLOWED_FILES:
            continue
        if any(normalized.startswith(prefix) for prefix in PR15E_ALLOWED_PREFIXES):
            continue
        violations.append(normalized)
    return sorted(violations)


def _prepare_environment_note() -> list[str]:
    return [
        "CPU samples include adapter startup, JSONL protocol and warmup requests.",
        "Index construction, commit and reopen happen outside the profiled process.",
        "Instrumented captures are never compared with uninstrumented PR 15D-B latencies.",
        "WSL2 perf/kernel mismatch and synthetic corpus limits are disclosed in the dossier.",
    ]


def _rel_to_run(run_dir: str, path: str) -> str:
    return rel_path(path, run_dir)


def build_adapter(run_dir: str) -> dict:
    manifest_path = os.path.join(
        REPO_ROOT, FROZEN_FILES["adapter_manifest"]
    )
    build_dir = os.path.join(run_dir, "build")
    log_dir = os.path.join(run_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    environment = dict(os.environ)
    environment["CARGO_PROFILE_RELEASE_DEBUG"] = "1"
    argv = [
        "cargo",
        "build",
        "--release",
        "--locked",
        "--manifest-path",
        manifest_path,
        "--target-dir",
        build_dir,
    ]
    result = _invoke(argv, env=environment, cwd=REPO_ROOT)
    log_path = os.path.join(log_dir, "build.log")
    with open(log_path, "w", encoding="utf-8") as handle:
        handle.write(" ".join(argv) + "\n\n")
        handle.write(result.stdout or "")
        handle.write(result.stderr or "")
    if result.returncode != 0:
        raise failed(
            "X29_BUILD_FAILED",
            "Quervant adapter release build failed; see logs/build.log",
            {"returncode": result.returncode},
        )
    binary = os.path.join(build_dir, "release", SYMBOL_NAME)
    if not os.path.isfile(binary):
        raise failed("X29_BUILD_OUTPUT", f"adapter binary missing at {binary}")
    rustc = _invoke(["rustc", "--version"])
    cargo = _invoke(["cargo", "--version"])
    return {
        "command": argv,
        "env": {"CARGO_PROFILE_RELEASE_DEBUG": "1"},
        "binary_path": _rel_to_run(run_dir, binary),
        "binary_bytes": os.path.getsize(binary),
        "binary_sha256": sha256_file(binary),
        "release_profile": True,
        "rustc_version": first_line(rustc.stdout),
        "cargo_version": first_line(cargo.stdout),
        "log_path": _rel_to_run(run_dir, log_path),
        "log_sha256": sha256_file(log_path),
    }


def build_indexes(run_dir: str, binary: str, corpus_paths: dict[int, str]) -> dict:
    indexes = {}
    for n in N_VALUES:
        index_dir = os.path.join(run_dir, "indexes", f"n{n}")
        if os.path.exists(index_dir):
            raise unsafe(
                "X28_DESTINATION_EXISTS",
                f"index destination already exists; refusing to delete: {index_dir}",
            )
        os.makedirs(os.path.dirname(index_dir), exist_ok=True)
        try:
            metrics = run.build_index(
                "quervant", binary, corpus_paths[n], index_dir, n
            )
        except run.RunBlocked as error:
            raise failed("X29_INDEX_BUILD", f"N={n}: {error}")
        inventory = index_inventory(index_dir)
        indexes[str(n)] = {
            "path": _rel_to_run(run_dir, index_dir),
            "documents_indexed": metrics["documents_indexed"],
            "documents_verified": metrics["documents_verified"],
            "expected_documents": metrics["expected_documents"],
            "index_bytes": metrics["index_bytes"],
            "segment_count": metrics.get("segment_count"),
            "index_ns": metrics["index_ns"],
            "commit_ns": metrics["commit_ns"],
            "reopen_ns": metrics["reopen_ns"],
            "inventory": inventory,
        }
    return indexes


def oracle_lane_expectations(rows_by_n: dict) -> list[dict]:
    lanes = []
    for n, class_name, k in (
        [(10000, name, PRIMARY_K) for name in CLASS_NAMES]
        + [(100000, name, PRIMARY_K) for name in CLASS_NAMES]
        + [(100000, name, SECONDARY_K) for name in CLASS_NAMES]
    ):
        descriptor = lane_descriptor(n, class_name, k)
        expected = recompute_expected(rows_by_n, descriptor)
        lanes.append(
            {
                **descriptor,
                "regime": REGIME,
                "expected_total_hits": expected["total_hits"],
                "expected_doc_ids": expected["doc_ids"],
                "expected_digest": expected_digest(expected),
                "tools": list(lane_required_tools(n, class_name, k)),
                "seconds": lane_seconds(n, class_name),
            }
        )
    return lanes


def smoke_lanes(binary: str, run_dir: str, lanes: list[dict], rows_by_n: dict) -> None:
    """Validate one query per lane against the real release adapter."""
    for n in N_VALUES:
        index_dir = os.path.join(run_dir, "indexes", f"n{n}")
        process = run.AdapterProcess(
            ENGINE, run._adapter_command(ENGINE, binary, index_dir)
        )
        try:
            for lane in lanes:
                if lane["n"] != n:
                    continue
                expected = recompute_expected(rows_by_n, lane)
                response = process.request(
                    {
                        "request_id": f"{lane['lane_id']}:smoke",
                        "op": "query",
                        "field": lane["field"],
                        "term": lane["term"],
                        "k": lane["k"],
                        "mode": REGIME,
                    }
                )
                try:
                    run.validate_query_response(response, lane, expected)
                except run.RunBlocked as error:
                    raise hard_stop(
                        "X23_ORACLE", f"{lane['lane_id']}: {error.detail}"
                    )
                lane["adapter_smoke"] = {
                    "request_id": response.get("request_id"),
                    "total_hits": response.get("total_hits"),
                    "doc_ids_sha256": sha256_bytes(
                        canonical_json_bytes(response.get("doc_ids"))
                    ),
                    "oracle_ok": True,
                }
        finally:
            process.close()


def prepare(args, deps: Deps | None = None) -> int:
    deps = deps or Deps()
    run_dir = resolve_run_dir(args.out, must_exist=False)
    os.makedirs(run_dir, exist_ok=True)
    try:
        if not deps.tree_clean():
            raise failed(
                "X08_DIRTY_TREE", "the tracked working tree must be clean before prepare"
            )
        head = deps.head_sha()
        prerequisites = check_15d_prerequisites(deps.canonical_report)
        lock = source_lock()
        for name, entry in lock.items():
            if name == "canonical_report" and deps.canonical_report:
                entry["sha256"] = sha256_file(deps.canonical_report)
                entry["bytes"] = os.path.getsize(deps.canonical_report)

        corpus_dir = os.path.join(run_dir, "corpus")
        corpus_manifest_path = os.path.join(corpus_dir, oracle.manifest_filename())
        if os.path.exists(corpus_manifest_path):
            raise unsafe("X28_DESTINATION_EXISTS", "corpus already prepared in this run")
        corpus_summary = generate.generate(corpus_dir)
        manifest, rows_by_n = load_corpus(run_dir)
        corpus_manifest_sha = sha256_bytes(canonical_json_bytes(manifest))
        corpus = {
            "path": _rel_to_run(run_dir, corpus_dir),
            "manifest_sha256": corpus_manifest_sha,
            "manifest_bytes": os.path.getsize(corpus_manifest_path),
            "corpora": {
                str(entry["n"]): {
                    "file": entry["path"],
                    "rows": entry["rows"],
                    "bytes": entry["bytes"],
                    "sha256": entry["sha256"],
                }
                for entry in manifest["corpora"]
            },
            "generator_summary": corpus_summary,
        }

        build = build_adapter(run_dir)
        binary = os.path.join(run_dir, build["binary_path"])
        if sha256_file(binary) != build["binary_sha256"]:
            raise failed("X24_BINARY_CHANGED", "adapter binary digest changed after build")

        corpus_paths = {
            n: os.path.join(corpus_dir, oracle.corpus_filename(n)) for n in N_VALUES
        }
        indexes = build_indexes(run_dir, binary, corpus_paths)
        lanes = oracle_lane_expectations(rows_by_n)
        smoke_lanes(binary, run_dir, lanes, rows_by_n)
        try:
            metadata = run.read_adapter_metadata(ENGINE, binary)
        except run.RunBlocked as error:
            raise failed("X29_ADAPTER_METADATA", f"{error.rule}: {error.detail}")
        evidence_lane = indexes[str(max(N_VALUES))]
        adapter_evidence = {
            "adapter_binary_sha256": build["binary_sha256"],
            "release_profile": True,
            "documents_indexed": evidence_lane["documents_indexed"],
            "documents_verified": evidence_lane["documents_verified"],
            "oracle_ok": all(
                lane.get("adapter_smoke", {}).get("oracle_ok") for lane in lanes
            ),
            "index_backend": metadata.get("index_backend"),
            "analyzer": metadata.get("analyzer"),
            "engine_version": metadata.get("engine_version"),
            "adapter_version": metadata.get("adapter_version"),
        }
        assert_real_adapter_evidence(adapter_evidence)

        environment = host_environment()
        tools = {}
        for tool, probe in (
            ("perf", deps.perf_probe),
            ("heaptrack", deps.heaptrack_probe),
            ("heaptrack_print", deps.heaptrack_print_probe),
        ):
            try:
                tools[tool] = {"status": "AVAILABLE", **probe()}
            except Pr15eError as error:
                tools[tool] = {
                    "status": error.status,
                    "code": error.code,
                    "detail": error.detail,
                }

        payload = {
            "schema": SCHEMA_PREPARE,
            "status": "PREPARED",
            "source": {
                "head_sha": head,
                "origin_main_sha": git_ref_sha("origin/main"),
                "merge_base": _git("merge-base", "HEAD", "origin/main"),
                "tracked_tree_clean": True,
            },
            "workload": WORKLOAD,
            "regime": REGIME,
            "warmups": WARMUPS,
            "min_profiled_requests": MIN_PROFILED_REQUESTS,
            "classes": [class_descriptor(name) for name in CLASS_NAMES],
            "matrix": {
                "n_values": list(N_VALUES),
                "k_values": list(K_VALUES),
                "captures": required_captures(),
            },
            "source_lock": lock,
            "corpus": corpus,
            "build": build,
            "adapter_evidence": adapter_evidence,
            "indexes": indexes,
            "lanes": lanes,
            "tools": tools,
            "environment": environment,
            "host_fingerprint": host_fingerprint(environment),
            "canonical_report_status": prerequisites["report"]["status"],
            "limitations": _prepare_environment_note(),
        }
        payload["prepared_digest"] = sha256_bytes(canonical_json_bytes(payload))
        prepare_path = os.path.join(run_dir, "prepare.json")
        if os.path.exists(prepare_path):
            raise unsafe("X28_DESTINATION_EXISTS", "prepare.json already exists")
        write_json(prepare_path, payload)
    except Pr15eError as error:
        _write_prepare_failure(run_dir, error)
        raise
    except (OSError, ValueError, KeyError) as error:
        _write_prepare_failure(run_dir, failed("X99_UNEXPECTED", str(error)))
        raise failed("X99_UNEXPECTED", str(error))
    print(
        canonical_json_bytes(
            {
                "status": "PREPARED",
                "run": rel_path(run_dir, REPO_ROOT),
                "source_sha": head,
                "captures": len(required_captures()),
                "prepare_sha256": sha256_file(os.path.join(run_dir, "prepare.json")),
            }
        ).decode("utf-8")
    )
    return EXIT_OK


def _write_prepare_failure(run_dir: str, error: Pr15eError) -> None:
    try:
        if not os.path.isdir(run_dir) or os.path.islink(run_dir):
            return
        path = os.path.join(run_dir, "prepare-failed.json")
        if os.path.exists(os.path.join(run_dir, "prepare.json")):
            return
        write_json(
            path,
            {
                "schema": SCHEMA_PREPARE_FAILED,
                "status": "NOT_PREPARED",
                "code": error.code,
                "detail": error.detail,
                "classification": error.status,
            },
        )
    except OSError:  # pragma: no cover - best effort failure record
        return


# ---------------------------------------------------------------------------
# Profiled child transport
# ---------------------------------------------------------------------------


class ProfiledTransport:
    """Bounded JSONL transport around the *profiled* adapter child process.

    Small on purpose: the profiler must wrap the adapter process, so the driver
    speaks the frozen pr15d-adapter-v1 protocol directly. It never evaluates a
    query and never fabricates a reply.
    """

    def __init__(self, process: subprocess.Popen, *, label: str):
        self.process = process
        self.label = label
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout.fileno(), selectors.EVENT_READ)
        self.buffer = b""
        self.last_line: str | None = None

    def request(self, payload: dict) -> dict:
        line = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            self.process.stdin.write(line + b"\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise failed(
                "X27_CHILD_DEATH", f"{self.label}: adapter pipe closed: {error}"
            )
        raw = self.readline()
        self.last_line = raw
        try:
            response = json.loads(raw)
        except json.JSONDecodeError:
            raise hard_stop(
                "X22_PROFILER_NOT_RELAYING",
                f"{self.label}: non-JSON line on the adapter stdout stream "
                f"(the profiler is not transparently relaying JSONL)",
                {"raw_line": raw[:2048]},
            )
        if not isinstance(response, dict):
            raise hard_stop(
                "X22_PROFILER_NOT_RELAYING", f"{self.label}: reply is not a JSON object"
            )
        if response.get("schema") != ADAPTER_SCHEMA:
            raise hard_stop(
                "X22_PROTOCOL",
                f"{self.label}: adapter schema {response.get('schema')!r} is not "
                f"{ADAPTER_SCHEMA!r}",
                {"raw_line": raw[:2048]},
            )
        if response.get("engine") != ENGINE:
            raise hard_stop(
                "X22_PROTOCOL",
                f"{self.label}: adapter engine {response.get('engine')!r} is not "
                f"{ENGINE!r}",
                {"raw_line": raw[:2048]},
            )
        if response.get("status") != "ok":
            raise failed(
                "X27_ADAPTER_ERROR",
                f"{self.label}: adapter returned an error status",
                {"error": response.get("error")},
            )
        return response

    def readline(self) -> str:
        deadline = time.monotonic() + RESPONSE_TIMEOUT_SECONDS
        fd = self.process.stdout.fileno()
        while True:
            index = self.buffer.find(b"\n")
            if index >= 0:
                line = self.buffer[:index]
                self.buffer = self.buffer[index + 1 :]
                try:
                    return line.decode("utf-8")
                except UnicodeDecodeError:
                    raise hard_stop(
                        "X22_PROTOCOL", f"{self.label}: adapter reply is not UTF-8"
                    )
            if len(self.buffer) > MAX_RESPONSE_BYTES:
                raise hard_stop(
                    "X22_PROTOCOL",
                    f"{self.label}: reply line exceeds {MAX_RESPONSE_BYTES} bytes",
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise failed(
                    "X26_RESPONSE_TIMEOUT",
                    f"{self.label}: no reply within {RESPONSE_TIMEOUT_SECONDS:.0f}s",
                )
            if not self.selector.select(timeout=remaining):
                raise failed(
                    "X26_RESPONSE_TIMEOUT",
                    f"{self.label}: no reply within {RESPONSE_TIMEOUT_SECONDS:.0f}s",
                )
            try:
                chunk = os.read(fd, 65536)
            except OSError as error:
                raise failed("X27_CHILD_DEATH", f"{self.label}: read failed: {error}")
            if not chunk:
                raise failed(
                    "X27_CHILD_DEATH",
                    f"{self.label}: adapter/profiler stdout closed before replying",
                )
            self.buffer += chunk

    def close_stdin(self) -> None:
        try:
            self.process.stdin.close()
        except (BrokenPipeError, OSError):  # pragma: no cover - defensive
            pass

    def close(self) -> None:
        try:
            self.selector.close()
        except OSError:  # pragma: no cover - defensive
            pass
        for stream in (self.process.stdin, self.process.stdout):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except OSError:  # pragma: no cover - defensive
                pass


def terminate_group(process: subprocess.Popen, *, grace: float = 10.0) -> None:
    """Terminate the whole profiler process group without orphaning the engine."""
    if process.poll() is not None:
        return
    for signal_name in ("terminate", "kill"):
        try:
            if signal_name == "terminate":
                os.killpg(os.getpgid(process.pid), 15)
                try:
                    process.wait(timeout=grace)
                    return
                except subprocess.TimeoutExpired:
                    continue
            os.killpg(os.getpgid(process.pid), 9)
        except (ProcessLookupError, PermissionError, OSError):  # pragma: no cover
            try:
                process.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:  # pragma: no cover
                continue
    try:  # pragma: no cover - last resort
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# Process-tree attribution (proves the profiled child is the Quervant adapter)
# ---------------------------------------------------------------------------


def _proc_ppid(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            data = handle.read().decode("utf-8", "replace")
    except OSError:
        return None
    try:
        tail = data[data.index(")") + 2 :].split()
        return int(tail[1])
    except (ValueError, IndexError):
        return None


def _proc_cmdline(pid: int) -> list[str]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            raw = handle.read()
    except OSError:
        return []
    return [part.decode("utf-8", "replace") for part in raw.split(b"\x00") if part]


def descendants(root_pid: int) -> list[int]:
    parents: dict[int, int] = {}
    try:
        names = os.listdir("/proc")
    except OSError:  # pragma: no cover - /proc absent
        return []
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        ppid = _proc_ppid(pid)
        if ppid is not None:
            parents[pid] = ppid
    children: dict[int, list[int]] = {}
    for pid, ppid in parents.items():
        children.setdefault(ppid, []).append(pid)
    found: list[int] = []
    stack = [root_pid]
    while stack:
        current = stack.pop()
        for child in children.get(current, []):
            found.append(child)
            stack.append(child)
    return found


def wait_for_adapter_pid(
    process: subprocess.Popen, binary_path: str, *, timeout: float = 10.0
) -> list[int]:
    """Bounded wait for the profiled child to appear (bounded startup only)."""
    deadline = time.monotonic() + timeout
    while True:
        pids = adapter_pids(process.pid, binary_path)
        if pids or process.poll() is not None or time.monotonic() >= deadline:
            return pids
        time.sleep(0.05)


def adapter_pids(root_pid: int, binary_path: str) -> list[int]:
    expected = os.path.basename(binary_path)
    found = []
    for pid in descendants(root_pid):
        argv = _proc_cmdline(pid)
        if not argv:
            continue
        if os.path.basename(argv[0]) == expected or any(
            expected and expected in part for part in argv[:2]
        ):
            found.append(pid)
    return sorted(set(found))


# ---------------------------------------------------------------------------
# Profiler argv construction (only the authorized forms)
# ---------------------------------------------------------------------------


def profiler_argv(tool: str, tool_info: dict, binary: str, index_dir: str,
                  capture_dir: str) -> list[str]:
    if tool == "perf":
        return [
            tool_info["path"],
            "record",
            "-g",
            "--call-graph",
            "dwarf",
            "-o",
            os.path.join(capture_dir, "perf.data"),
            "--",
            binary,
            "--index-dir",
            index_dir,
        ]
    if tool == "heaptrack":
        return [
            tool_info["path"],
            "-o",
            os.path.join(capture_dir, "heaptrack"),
            binary,
            "--index-dir",
            index_dir,
        ]
    raise usage_error(f"unknown tool {tool!r}")


def validate_argv_target(argv: list[str], binary: str) -> None:
    """The profiler must wrap the prepared Quervant adapter, never a driver."""
    if tool_tail(argv) != [binary, "--index-dir"]:
        raise hard_stop(
            "X22_PROFILER_TARGET",
            "profiler argv does not target the prepared Quervant adapter",
        )


def tool_tail(argv: list[str]) -> list[str]:
    if "--" in argv:
        index = argv.index("--")
        return argv[index + 1 : index + 3]
    return argv[-3:-1]


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


def _capture_dir(run_dir: str, descriptor: dict) -> str:
    return os.path.join(run_dir, *descriptor["rel_dir"].split("/"))


def _verify_prepared_state(run_dir: str, deps: Deps) -> dict:
    prepare_path = os.path.join(run_dir, "prepare.json")
    if not os.path.isfile(prepare_path):
        raise blocked("BLOCKED_PREPARE", "prepare.json is missing for this run")
    prepared = read_json(prepare_path)
    if prepared.get("schema") != SCHEMA_PREPARE or prepared.get("status") != "PREPARED":
        raise failed("X33_PREPARE_INVALID", "prepare.json is not a PREPARED record")
    recorded = prepared.get("prepared_digest")
    payload = {key: value for key, value in prepared.items() if key != "prepared_digest"}
    if recorded != sha256_bytes(canonical_json_bytes(payload)):
        raise failed("X33_PREPARE_INVALID", "prepare.json digest does not re-derive")

    head = deps.head_sha()
    if head != prepared["source"]["head_sha"]:
        raise hard_stop(
            "X24_SOURCE_CHANGED",
            f"HEAD {head} != prepared source {prepared['source']['head_sha']}",
        )
    if not deps.tree_clean():
        raise failed("X08_DIRTY_TREE", "capture requires a clean tracked tree")

    for name, entry in prepared["source_lock"].items():
        path = (
            deps.canonical_report
            if name == "canonical_report"
            else os.path.join(REPO_ROOT, FROZEN_FILES[name])
        )
        if not os.path.isfile(path):
            raise failed("X24_SOURCE_CHANGED", f"frozen file disappeared: {name}")
        if sha256_file(path) != entry["sha256"]:
            raise hard_stop(
                "X24_SOURCE_CHANGED", f"frozen file digest changed: {entry['path']}"
            )

    binary = os.path.join(run_dir, prepared["build"]["binary_path"])
    if not os.path.isfile(binary):
        raise failed("X24_BINARY_CHANGED", "prepared adapter binary is missing")
    if sha256_file(binary) != prepared["build"]["binary_sha256"]:
        raise hard_stop("X24_BINARY_CHANGED", "prepared adapter binary digest changed")

    corpus_dir = os.path.join(run_dir, "corpus")
    if not os.path.isdir(corpus_dir):
        raise failed("X24_CORPUS_INVALID", "prepared corpus directory is missing")
    try:
        manifest, rows_by_n = oracle.load_and_verify(corpus_dir)
    except oracle.CorpusError as error:
        raise hard_stop("X24_CORPUS_INVALID", f"{error.code}: {error.detail}")
    if sha256_bytes(canonical_json_bytes(manifest)) != prepared["corpus"]["manifest_sha256"]:
        raise hard_stop("X24_CORPUS_INVALID", "corpus manifest digest changed")
    for entry in manifest["corpora"]:
        recorded = prepared["corpus"]["corpora"][str(entry["n"])]
        if entry["sha256"] != recorded["sha256"] or entry["bytes"] != recorded["bytes"]:
            raise hard_stop("X24_CORPUS_INVALID", f"N={entry['n']}: corpus bytes changed")

    for n in N_VALUES:
        recorded = prepared["indexes"][str(n)]
        index_dir = os.path.join(run_dir, recorded["path"])
        violations = compare_index_inventory(index_dir, recorded.get("inventory", {}))
        if violations:
            raise hard_stop("X24_INDEX_CHANGED", "; ".join(violations))
    return prepared


def _capture_lane_expectation(prepared: dict, descriptor: dict, rows_by_n: dict) -> dict:
    for lane in prepared["lanes"]:
        if lane["lane_id"] == descriptor["lane_id"]:
            expected = recompute_expected(rows_by_n, descriptor)
            if expected_digest(expected) != lane["expected_digest"]:
                raise hard_stop(
                    "X23_ORACLE", "prepared oracle expectation no longer re-derives"
                )
            return expected
    raise hard_stop("X33_PREPARE_INVALID", f"{descriptor['lane_id']} is not prepared")


def _run_profiled_capture(
    *, run_dir: str, capture_dir: str, descriptor: dict, prepared: dict,
    tool_info: dict, attestation: dict, expected: dict, deps: Deps,
) -> dict:
    binary = os.path.join(run_dir, prepared["build"]["binary_path"])
    index_dir = os.path.join(run_dir, prepared["indexes"][str(descriptor["n"])]["path"])
    argv = profiler_argv(descriptor["tool"], tool_info, binary, index_dir, capture_dir)
    validate_argv_target(argv, binary)
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
            raise blocked(
                "BLOCKED_PROFILER", f"cannot launch {descriptor['tool']}: {error}"
            )

    transport = ProfiledTransport(process, label=descriptor["capture_id"])
    evidence: dict = {
        "adapter_pid_samples": [],
        "warmups": 0,
        "profiled_queries": 0,
        "command": argv,
    }
    try:
        lane_expected = expected

        def note_adapter_pids() -> None:
            pids = wait_for_adapter_pid(
                process, binary, timeout=ADAPTER_PID_DISCOVERY_SECONDS
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
        for index in range(WARMUPS):
            response = transport.request(
                {
                    "request_id": f"{descriptor['lane_id']}:warmup:{index}",
                    "op": "query",
                    "field": descriptor["field"],
                    "term": descriptor["term"],
                    "k": descriptor["k"],
                    "mode": REGIME,
                }
            )
            validate_response_against_oracle(response, descriptor, lane_expected)
            evidence["warmups"] += 1

        recheck_window(attestation, deps)
        note_adapter_pids()
        window_start = deps.now_utc()
        budget = deps.loop_seconds(descriptor["seconds"])
        deadline = time.monotonic() + budget
        profiled = 0
        while profiled < MAX_PROFILED_REQUESTS:
            if time.monotonic() >= deadline:
                break
            response = transport.request(
                {
                    "request_id": f"{descriptor['lane_id']}:profiled:{profiled}",
                    "op": "query",
                    "field": descriptor["field"],
                    "term": descriptor["term"],
                    "k": descriptor["k"],
                    "mode": REGIME,
                }
            )
            validate_response_against_oracle(response, descriptor, lane_expected)
            profiled += 1
        evidence["profiled_queries"] = profiled
        evidence["profiled_window_seconds"] = round(time.monotonic() - (deadline - budget), 3)
        window_end = deps.now_utc()
        evidence["window_start_utc"] = format_utc(window_start)
        evidence["window_end_utc"] = format_utc(window_end)
        profile_end = parse_utc(attestation["end_utc"])
        if window_end > profile_end:
            raise blocked(
                "OUTSIDE_WINDOW", "the attested window ended during the capture"
            )
        note_adapter_pids()

        transport.request(
            {
                "request_id": f"{descriptor['lane_id']}:shutdown",
                "op": "shutdown",
            }
        )
        transport.close_stdin()
        try:
            returncode = process.wait(timeout=PROFILER_EXIT_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            terminate_group(process)
            raise failed(
                "X27_PROFILER_TIMEOUT",
                "profiler did not exit within the bounded grace period",
            )
        evidence["profiler_returncode"] = returncode
        if returncode != 0:
            raise failed(
                "X20_PROFILER_FAILED",
                f"{descriptor['tool']} exited with {returncode}",
            )
    except BaseException:
        terminate_group(process)
        raise
    finally:
        transport.close()

    pids = sorted(set(evidence["adapter_pid_samples"]))
    if len(pids) != 1:
        raise hard_stop(
            "X22_PROFILER_TARGET", f"adapter PID set is not a single process: {pids}"
        )
    evidence["adapter_pid"] = pids[0]
    if evidence["warmups"] != WARMUPS:
        raise failed("X23_WARMUPS", f"completed {evidence['warmups']} warmups")
    if evidence["profiled_queries"] < MIN_PROFILED_REQUESTS:
        raise blocked(
            "X26_INSUFFICIENT_SAMPLES",
            f"only {evidence['profiled_queries']} profiled queries completed",
        )
    return evidence


# ---------------------------------------------------------------------------
# Tool report extraction
# ---------------------------------------------------------------------------


_PERF_COUNT = r"(\d+(?:\.\d+)?)\s*([KMG]?)"


def _scale_count(value: str, suffix: str) -> int:
    multiplier = {"": 1, "K": 1000, "M": 1000 * 1000, "G": 1000 * 1000 * 1000}[suffix]
    return int(round(float(value) * multiplier))


def parse_perf_samples(text: str) -> int | None:
    """Parse perf's sample-count header, including its K/M/G abbreviations."""
    match = re.search(r"#\s*Samples:\s*" + _PERF_COUNT + r"\s+of event", text)
    if match:
        return _scale_count(match.group(1), match.group(2))
    match = re.search(r"#\s*Samples:\s*" + _PERF_COUNT + r"\b", text)
    if match:
        return _scale_count(match.group(1), match.group(2))
    return None


def parse_perf_lost_samples(text: str) -> int:
    total = 0
    for match in re.finditer(r"#\s*Total Lost Samples:\s*(\d+)", text):
        total += int(match.group(1))
    for match in re.finditer(r"lost chunks?:\s*(\d+)", text, re.I):
        total += int(match.group(1))
    return total


def symbolized_frames(text: str) -> dict:
    quervant = len(re.findall(r"quervant", text, re.I))
    rust_demangled = len(re.findall(r"\[\.\]\s+\S*::\S*", text))
    return {"quervant_mentions": quervant, "rust_symbols": rust_demangled}


def generate_perf_reports(tool_info: dict, capture_dir: str) -> dict:
    raw = os.path.join(capture_dir, "perf.data")
    if not os.path.isfile(raw) or os.path.getsize(raw) == 0:
        raise blocked("X19_PERF_EMPTY", "perf.data is missing or empty")
    self_report = os.path.join(capture_dir, "perf-self.txt")
    calltree_report = os.path.join(capture_dir, "perf-calltree.txt")
    self_result = _invoke(
        [
            tool_info["path"],
            "report",
            "--stdio",
            "--no-children",
            "--sort",
            "dso,symbol",
            "--percent-limit",
            "0.5",
            "-i",
            raw,
        ],
        timeout=600,
    )
    calltree_result = _invoke(
        [tool_info["path"], "report", "--stdio", "-i", raw], timeout=600
    )
    with open(self_report, "w", encoding="utf-8") as handle:
        handle.write(self_result.stdout or "")
        if self_result.stderr:
            handle.write("\n# stderr\n" + self_result.stderr)
    with open(calltree_report, "w", encoding="utf-8") as handle:
        handle.write(calltree_result.stdout or "")
        if calltree_result.stderr:
            handle.write("\n# stderr\n" + calltree_result.stderr)
    for name, result in (("self", self_result), ("calltree", calltree_result)):
        if result.returncode != 0:
            raise blocked(
                "X19_PERF_REPORT", f"perf report ({name}) exited {result.returncode}"
            )
    self_text = read_text(self_report)
    calltree_text = read_text(calltree_report)
    if len(self_text.strip()) < 32 or len(calltree_text.strip()) < 32:
        raise blocked("X19_PERF_REPORT", "perf report output is empty")
    samples = parse_perf_samples(self_text)
    if samples is None:
        raise blocked(
            "X19_PERF_REPORT", "perf report does not expose a recognizable sample count"
        )
    if samples < MIN_PERF_SAMPLES:
        raise blocked(
            "X19_PERF_SAMPLES",
            f"only {samples} CPU samples captured; at least {MIN_PERF_SAMPLES} are required",
        )
    symbols = symbolized_frames(self_text)
    if symbols["quervant_mentions"] < 1:
        raise blocked(
            "X19_PERF_SYMBOLS", "perf report contains no symbolized Quervant/Rust frames"
        )
    lost = parse_perf_lost_samples(self_text) + parse_perf_lost_samples(calltree_text)
    return {
        "sample_count": samples,
        "lost_samples": lost,
        "sampled_with_loss": lost > 0,
        "symbolization": symbols,
        "reports": ["perf-self.txt", "perf-calltree.txt"],
        "raw_bytes": os.path.getsize(raw),
    }


def parse_heaptrack_records(text: str) -> dict:
    total_match = re.search(r"calls to allocation functions:\s*(\d+)", text)
    sites = len(re.findall(r"(?m)^\d+ calls to allocation functions with", text))
    temporary = text.count("MOST TEMPORARY ALLOCATIONS")
    return {
        "total_allocations": int(total_match.group(1)) if total_match else 0,
        "allocation_sites": sites,
        "temporary_section": temporary,
        "has_calls_section": "MOST CALLS TO ALLOCATION FUNCTIONS" in text,
    }


def locate_heaptrack_raw(capture_dir: str) -> str:
    candidates = sorted(glob.glob(os.path.join(capture_dir, "heaptrack*.gz")))
    candidates = [path for path in candidates if os.path.isfile(path)]
    if len(candidates) != 1:
        raise blocked(
            "X20_HEAPTRACK_RAW",
            f"expected exactly one heaptrack.*.gz artifact, found {len(candidates)}",
        )
    if os.path.getsize(candidates[0]) == 0:
        raise blocked("X20_HEAPTRACK_RAW", "heaptrack raw artifact is empty")
    return candidates[0]


def generate_heaptrack_report(tool_info: dict, print_info: dict, capture_dir: str) -> dict:
    raw = locate_heaptrack_raw(capture_dir)
    report_path = os.path.join(capture_dir, "heaptrack-report.txt")
    stderr_path = os.path.join(capture_dir, "heaptrack-print-stderr.txt")
    try:
        result = _invoke(
            [print_info["path"], "-f", raw, "-p", "-a", "-T"], timeout=1800
        )
    except subprocess.TimeoutExpired:
        raise blocked("X20_HEAPTRACK_REPORT", "heaptrack_print timed out")
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(result.stdout or "")
    with open(stderr_path, "w", encoding="utf-8") as handle:
        handle.write(result.stderr or "")
    if result.returncode != 0:
        raise blocked(
            "X20_HEAPTRACK_REPORT",
            f"heaptrack_print exited {result.returncode}",
        )
    text = read_text(report_path)
    if len(text.strip()) < 64:
        raise blocked("X20_HEAPTRACK_REPORT", "heaptrack_print report is empty")
    records = parse_heaptrack_records(text)
    if not records["has_calls_section"] or records["allocation_sites"] < 1:
        raise blocked(
            "X20_HEAPTRACK_REPORT", "no parseable allocation records in the report"
        )
    return {
        "raw_path": rel_path(raw, capture_dir),
        "raw_bytes": os.path.getsize(raw),
        "report": "heaptrack-report.txt",
        "records": records,
    }


# ---------------------------------------------------------------------------
# Evidence manifests
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


def _write_capture_failure(capture_dir: str, descriptor: dict, error: Pr15eError) -> None:
    payload = {
        "schema": SCHEMA_CAPTURE_FAILURE,
        "status": error.status,
        "code": error.code,
        "detail": error.detail,
        "capture_id": descriptor.get("capture_id"),
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


def capture(args, deps: Deps | None = None) -> int:
    deps = deps or Deps()
    run_dir = resolve_run_dir(args.run, must_exist=True)
    descriptor = validate_capture_args(
        args.n, args.class_name, args.k, args.tool, args.seconds
    )
    try:
        prepared = _verify_prepared_state(run_dir, deps)
        _, rows_by_n = load_corpus(run_dir)
        expected = _capture_lane_expectation(prepared, descriptor, rows_by_n)
        attestation = load_attestation(run_dir, descriptor["seconds"], deps)
        if not getattr(args, "idle_confirmed", False):
            raise blocked(
                "BLOCKED_ATTESTATION",
                "--idle-confirmed is required in addition to the operator attestation",
            )
        capture_dir = _capture_dir(run_dir, descriptor)
        if os.path.exists(capture_dir):
            raise unsafe(
                "X28_DESTINATION_EXISTS",
                f"capture already exists and is never overwritten: {descriptor['rel_dir']}",
            )
        os.makedirs(capture_dir)
        try:
            tool_info = resolve_tool(descriptor["tool"], deps)
            print_info = None
            if descriptor["tool"] == "heaptrack":
                print_info = deps.heaptrack_print_probe()
        except Pr15eError as error:
            _write_capture_failure(capture_dir, descriptor, error)
            raise
    except Pr15eError:
        raise
    except (OSError, ValueError, KeyError) as error:
        raise failed("X99_UNEXPECTED", str(error))

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
            run_dir=run_dir,
            capture_dir=capture_dir,
            descriptor=descriptor,
            prepared=prepared,
            tool_info=tool_info,
            attestation=attestation,
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
            tool_evidence = generate_perf_reports(tool_info, capture_dir)
        else:
            tool_evidence = generate_heaptrack_report(
                tool_info, print_info, capture_dir
            )

        files = artifact_manifest(capture_dir)
        manifest = {
            "schema": SCHEMA_CAPTURE,
            "status": "CAPTURED_RAW",
            "capture_id": descriptor["capture_id"],
            "lane_id": descriptor["lane_id"],
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
            "expected_digest": expected_digest(expected),
            "attestation": {
                "host": attestation["host"],
                "start_utc": attestation["start_utc"],
                "end_utc": attestation["end_utc"],
                "operator_statement": attestation["operator_statement"],
            },
            "contention_before": before.get("state"),
            "contention_after": after.get("state"),
            "tool_evidence": tool_evidence,
            "files": files,
            "limitations": _prepare_environment_note(),
            "test_fixture": False,
        }
        write_json(os.path.join(capture_dir, "capture.json"), manifest)
    except Pr15eError as error:
        _write_capture_failure(capture_dir, descriptor, error)
        raise
    except (OSError, ValueError, KeyError) as error:
        wrapped = failed("X99_UNEXPECTED", str(error))
        _write_capture_failure(capture_dir, descriptor, wrapped)
        raise wrapped

    print(
        canonical_json_bytes(
            {
                "status": "CAPTURED_RAW",
                "capture_id": descriptor["capture_id"],
                "tool": descriptor["tool"],
                "profiled_queries": evidence["profiled_queries"],
                "capture_sha256": sha256_file(
                    os.path.join(capture_dir, "capture.json")
                ),
            }
        ).decode("utf-8")
    )
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profile.py",
        description="PR 15E-A exact-workload CPU/allocation profiling driver.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser(
        "prepare", help="create corpus, adapter binary and indexes; verify the oracle"
    )
    prepare_parser.add_argument("--out", required=True)

    capture_parser = subparsers.add_parser(
        "capture", help="capture one authorized warm profiling lane"
    )
    capture_parser.add_argument("--run", required=True)
    capture_parser.add_argument("--n", type=int, required=True)
    capture_parser.add_argument("--class", dest="class_name", required=True)
    capture_parser.add_argument("--k", type=int, required=True)
    capture_parser.add_argument("--tool", required=True)
    capture_parser.add_argument("--seconds", type=int, required=True)
    capture_parser.add_argument("--idle-confirmed", action="store_true")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            return prepare(args)
        if args.command == "capture":
            return capture(args)
        raise usage_error(f"unknown command {args.command!r}")  # pragma: no cover
    except Pr15eError as error:
        print(
            canonical_json_bytes(
                {
                    "status": error.status,
                    "code": error.code,
                    "detail": error.detail,
                }
            ).decode("utf-8")
        )
        print(f"{error.status} {error.code}: {error.detail}", file=sys.stderr)
        return EXIT_BY_STATUS.get(error.status, EXIT_FAILED)


if __name__ == "__main__":
    raise SystemExit(main())
