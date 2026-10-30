#!/usr/bin/env python3
"""PR15D comparative qualification runner (engine-neutral orchestration only).

This module is the only qualified-run orchestrator. It never edits or optimizes
production code, never fabricates a sample and never treats a missing toolchain
as success. When a pinned adapter or host toolchain is unavailable it writes a
precise blocker record and exits nonzero.

Pure helpers (lane matrix, nearest-rank statistics, path confinement, frozen
path classification) are importable by ``test_pr15d.py`` without a JVM, a
Tantivy build or a real benchmark host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

SCHEMA_ADAPTER = "pr15d-adapter-v1"
SCHEMA_CORPUS = "pr15d-corpus-v1"
SCHEMA_RUN = "pr15d-run-v1"
SCHEMA_TRIAL = "pr15d-trial-v1"
SCHEMA_VALIDATION = "pr15d-validation-v1"
SCHEMA_AGGREGATE = "pr15d-aggregate-v1"

WORKLOAD = "pr15d_v1"
N_VALUES = (10000, 100000)
K_VALUES = (10, 100)
CLASSES = (
    ("absent", "key", "never"),
    ("rare", "key", "singleton"),
    ("medium", "group", "medium"),
    ("common", "key", "common"),
)
REGIMES = ("process_cold", "warm")
ENGINES = ("quervant", "tantivy", "lucene")
WARMUPS = 5
MEASURED = 20
THROUGHPUT_REQUESTS = 100
REQUIRED_TRIALS = 3
ANALYZER = "keyword-exact"
NATIVE_FILESYSTEMS = frozenset({"ext4", "xfs", "btrfs"})
TRIAL_ORDER = {
    1: ("quervant", "tantivy", "lucene"),
    2: ("tantivy", "lucene", "quervant"),
    3: ("lucene", "quervant", "tantivy"),
}
FROZEN_PREFIXES = (
    "crates/",
    "benchmarks/datasets/",
    "benchmarks/workloads/",
    "benchmarks/reports/pr15b-",
    "benchmarks/reports/pr15c-b/",
    "benchmarks/reports/pr07-",
    "benchmarks/reports/pr14",
    "docs/pr-artifacts/pr-7/",
    "docs/pr-artifacts/pr-13/",
    "docs/pr-artifacts/pr-14",
    "docs/pr-artifacts/pr-15b",
    "docs/pr-artifacts/pr-15c",
)
PR15D_ALLOWED_PREFIXES = (
    "benchmarks/pr15d/",
    "benchmarks/reports/pr15d/",
    "docs/pr-artifacts/pr-15d/",
)
ALLOWED_EXISTING_EDITS = ("benchmarks/README.md", ".github/workflows/ci.yml")
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
ADAPTER_DIRS = {
    "quervant": os.path.join(REPO_ROOT, "benchmarks/pr15d/adapters/quervant"),
    "tantivy": os.path.join(REPO_ROOT, "benchmarks/pr15d/adapters/tantivy"),
    "lucene": os.path.join(REPO_ROOT, "benchmarks/pr15d/adapters/lucene"),
}

sys.path.insert(0, os.path.join(REPO_ROOT, "benchmarks/pr15d/corpus"))
import oracle  # noqa: E402  (engine-neutral, standard-library only)


class RunBlocked(Exception):
    """A precise, classified blocker that must never be converted to success."""

    def __init__(self, rule: str, detail: str):
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail


# ---------------------------------------------------------------------------
# Lane matrix and deterministic statistics
# ---------------------------------------------------------------------------


def lane_id(n: int, class_name: str, k: int) -> str:
    return f"{WORKLOAD}/{n}/{class_name}/k{k}"


def lane_descriptors() -> list[dict]:
    lanes = []
    for n in N_VALUES:
        for class_name, field, term in CLASSES:
            for k in K_VALUES:
                for regime in REGIMES:
                    lanes.append(
                        {
                            "id": lane_id(n, class_name, k),
                            "n": n,
                            "class": class_name,
                            "field": field,
                            "term": term,
                            "k": k,
                            "regime": regime,
                        }
                    )
    return lanes


def lane_key(lane: dict) -> tuple:
    return (lane["n"], lane["class"], lane["k"], lane["regime"])


def nearest_rank_index(count: int, percentile: int) -> int:
    """Nearest-rank index for percentile in {50, 95, 99} over ``count`` samples."""
    if count <= 0:
        raise ValueError("count must be positive")
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in (0, 100]")
    return (percentile * count + 99) // 100 - 1


def summarize(samples_ns) -> dict:
    """Deterministic integer summary of a measured sample list."""
    if not samples_ns:
        raise ValueError("no samples")
    for value in samples_ns:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("samples must be integers")
        if value <= 0:
            raise ValueError("samples must be positive")
    values = sorted(samples_ns)
    count = len(values)
    return {
        "count": count,
        "median": values[nearest_rank_index(count, 50)],
        "p95": values[nearest_rank_index(count, 95)],
        "p99": values[nearest_rank_index(count, 99)],
        "min": values[0],
        "max": values[-1],
    }


def canonical_json_bytes(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def write_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(canonical_json_bytes(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_json(path: str):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Path confinement and frozen-path policy
# ---------------------------------------------------------------------------


def confined_path(root: str, *parts: str) -> str:
    """Join ``parts`` under ``root`` and refuse traversal or symlink escape."""
    root_real = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root_real, *parts))
    if candidate != root_real and not candidate.startswith(root_real + os.sep):
        raise RunBlocked("X19_PATH_ESCAPE", f"{candidate} escapes {root_real}")
    return candidate


def classify_changed_paths(paths) -> list[str]:
    """Return violations for a list of repo-relative changed paths (T22)."""
    violations = []
    for path in paths:
        normalized = path.replace(os.sep, "/")
        if normalized.startswith(PR15D_ALLOWED_PREFIXES):
            continue
        if normalized in ALLOWED_EXISTING_EDITS:
            continue
        if normalized.startswith(FROZEN_PREFIXES):
            violations.append(normalized)
            continue
        violations.append(normalized)
    return sorted(violations)


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------


def _run_text(command, cwd=None) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _first_line(command, cwd=None) -> str | None:
    text = _run_text(command, cwd=cwd)
    return text.splitlines()[0] if text else None


def _read_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def _git(*args) -> str | None:
    return _run_text(["git", *args], cwd=REPO_ROOT)


def source_sha() -> str:
    sha = _git("rev-parse", "HEAD")
    if not sha:
        raise RunBlocked("X27_SOURCE", "cannot read the Git source SHA")
    return sha


def tracked_tree_clean() -> bool:
    status = _git("status", "--porcelain", "--untracked-files=no")
    if status is None:
        raise RunBlocked("X27_SOURCE", "cannot read the Git worktree status")
    return status == ""


def filesystem_type(path: str) -> str | None:
    text = _run_text(["findmnt", "-n", "-o", "FSTYPE", "-T", path])
    if not text:
        return None
    return text.splitlines()[0].strip() or None


def _os_release() -> dict:
    text = _read_file("/etc/os-release") or ""
    fields = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip().strip('"')
    return fields


def _wsl() -> bool:
    text = (_read_file("/proc/version") or "").lower()
    return "microsoft" in text or "wsl" in text


def _mem_total_bytes() -> int | None:
    text = _read_file("/proc/meminfo") or ""
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            try:
                return int(parts[1]) * 1024
            except (IndexError, ValueError):
                return None
    return None


def _cpu_model() -> str | None:
    text = _read_file("/proc/cpuinfo") or ""
    for line in text.splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return None


def _cgroup_limits() -> dict:
    return {
        "memory_max": (_read_file("/sys/fs/cgroup/memory.max") or "").strip() or None,
        "cpu_max": (_read_file("/sys/fs/cgroup/cpu.max") or "").strip() or None,
    }


def collect_toolchains() -> dict:
    def probe(name, command):
        version = _first_line(command)
        return {"present": version is not None, "version": version}

    return {
        "rustc": probe("rustc", ["rustc", "--version"]),
        "cargo": probe("cargo", ["cargo", "--version"]),
        "java": probe("java", ["java", "-version"]),
        "javac": probe("javac", ["javac", "-version"]),
        "gradle": probe("gradle", ["gradle", "--version"]),
        "python3": probe("python3", ["python3", "--version"]),
        "git": probe("git", ["git", "--version"]),
        "sha256sum": probe("sha256sum", ["sha256sum", "--version"]),
        "findmnt": probe("findmnt", ["findmnt", "--version"]),
        "time": {"present": os.path.exists("/usr/bin/time"), "version": None},
    }


def collect_environment(target_path: str) -> dict:
    filesystem = filesystem_type(target_path)
    uname = platform.uname()
    return {
        "kernel": uname.release,
        "machine": uname.machine,
        "os_release": _os_release(),
        "wsl": _wsl(),
        "cpu_model": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "mem_total_bytes": _mem_total_bytes(),
        "cgroup": _cgroup_limits(),
        "filesystem": filesystem,
        "native_filesystem": filesystem in NATIVE_FILESYSTEMS,
        "toolchains": collect_toolchains(),
    }


def host_fingerprint(environment: dict) -> str:
    selected = {
        "kernel": environment.get("kernel"),
        "machine": environment.get("machine"),
        "cpu_model": environment.get("cpu_model"),
        "cpu_count": environment.get("cpu_count"),
        "mem_total_bytes": environment.get("mem_total_bytes"),
        "filesystem": environment.get("filesystem"),
        "os_release": environment.get("os_release"),
        "wsl": environment.get("wsl"),
    }
    return hashlib.sha256(canonical_json_bytes(selected)).hexdigest()


# ---------------------------------------------------------------------------
# Adapter preflight
# ---------------------------------------------------------------------------


def adapter_files(engine: str) -> list[str]:
    if engine == "quervant":
        return ["Cargo.toml", "Cargo.lock", "src/main.rs"]
    if engine == "tantivy":
        return ["Cargo.toml", "Cargo.lock", "src/main.rs"]
    if engine == "lucene":
        return [
            "build.gradle",
            "settings.gradle",
            "gradlew",
            "gradlew.bat",
            "A1-CHECKSUMS.sha256",
            "gradle/wrapper/gradle-wrapper.properties",
            "gradle/wrapper/gradle-wrapper.jar",
            "src/main/java/org/quervant/bench/Adapter.java",
        ]
    raise RunBlocked("X99_UNKNOWN_ENGINE", engine)


def preflight_adapters() -> dict:
    """Return per-engine availability and precise blocker classifications."""
    report = {}
    for engine in ENGINES:
        directory = ADAPTER_DIRS[engine]
        missing = [
            relative
            for relative in adapter_files(engine)
            if not os.path.isfile(os.path.join(directory, relative))
        ]
        entry = {"directory": directory, "missing": missing, "blockers": []}
        if engine == "tantivy":
            manifest = os.path.join(directory, "Cargo.toml")
            text = _read_file(manifest)
            lock = _read_file(os.path.join(directory, "Cargo.lock"))
            if text is None:
                entry["blockers"].append(
                    {
                        "rule": "X15_HARD_STOP",
                        "code": "TANTIVY_PIN_UNRESOLVABLE",
                        "detail": "Tantivy adapter Cargo.toml is missing",
                    }
                )
            elif 'tantivy = "=0.22.1"' not in text:
                entry["blockers"].append(
                    {
                        "rule": "X15_HARD_STOP",
                        "code": "TANTIVY_PIN_DRIFT",
                        "detail": "Tantivy adapter does not declare the A1 =0.22.1 pin",
                    }
                )
            elif lock is None or 'name = "tantivy"' not in lock:
                entry["blockers"].append(
                    {
                        "rule": "X15_HARD_STOP",
                        "code": "TANTIVY_LOCK_MISSING",
                        "detail": "Standalone Tantivy Cargo.lock is missing",
                    }
                )
            elif 'version = "0.22.1"' not in lock:
                entry["blockers"].append(
                    {
                        "rule": "X15_HARD_STOP",
                        "code": "TANTIVY_LOCK_DRIFT",
                        "detail": "Tantivy Cargo.lock does not pin 0.22.1",
                    }
                )
        if engine == "lucene":
            toolchains = collect_toolchains()
            for tool in ("java", "javac"):
                if not toolchains[tool]["present"]:
                    entry["blockers"].append(
                        {
                            "rule": "X14_DEFER_ENVIRONMENT",
                            "code": f"LUCENE_TOOLCHAIN_MISSING_{tool.upper()}",
                            "detail": (
                                f"{tool} is not available; JDK 21 is required and "
                                "must not be installed ad hoc"
                            ),
                        }
                    )
            mismatches = verify_checksum_manifest(directory, "A1-CHECKSUMS.sha256")
            if mismatches:
                entry["blockers"].append(
                    {
                        "rule": "X16_HARD_STOP",
                        "code": "GRADLE_WRAPPER_UNVERIFIED",
                        "detail": "; ".join(mismatches),
                    }
                )
        if missing and engine != "tantivy" and engine != "lucene":
            entry["blockers"].append(
                {
                    "rule": "X99_HARD_STOP",
                    "code": "ADAPTER_SOURCE_MISSING",
                    "detail": f"{engine} adapter source is incomplete: {missing}",
                }
            )
        report[engine] = entry
    return report


def verify_checksum_manifest(directory: str, manifest_name: str) -> list[str]:
    """Verify `sha256sum`-format entries inside an adapter directory."""
    path = os.path.join(directory, manifest_name)
    text = _read_file(path)
    if text is None:
        return [f"missing checksum manifest: {path}"]
    problems = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            problems.append(f"malformed checksum line: {line!r}")
            continue
        expected, relative = parts[0], parts[1].lstrip("*")
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            problems.append(f"malformed checksum value: {expected!r}")
            continue
        candidate = os.path.realpath(os.path.join(directory, relative))
        root = os.path.realpath(directory)
        if not candidate.startswith(root + os.sep):
            problems.append(f"checksum path escapes adapter root: {relative}")
            continue
        try:
            with open(candidate, "rb") as handle:
                digest = hashlib.sha256()
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            problems.append(f"cannot hash {relative}: {error}")
            continue
        if digest.hexdigest() != expected:
            problems.append(
                f"checksum mismatch for {relative}: {digest.hexdigest()} != {expected}"
            )
    return problems


def preflight_blockers(adapters: dict) -> list[dict]:
    blockers = []
    for engine in ENGINES:
        for blocker in adapters[engine]["blockers"]:
            blockers.append({"engine": engine, **blocker})
    return blockers


# ---------------------------------------------------------------------------
# Adapter process plumbing (executed only on a fully qualified host)
# ---------------------------------------------------------------------------


class AdapterProcess:
    def __init__(self, engine: str, command: list[str], cwd: str | None = None):
        self.engine = engine
        self.command = command
        self.process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def request(self, payload: dict) -> dict:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()
        reply = self.process.stdout.readline()
        if not reply:
            stderr = ""
            if self.process.stderr is not None:
                stderr = self.process.stderr.read()
            raise RunBlocked(
                "X28_PROCESS_DEATH",
                f"{self.engine} adapter died before replying: {stderr.strip()}",
            )
        try:
            response = json.loads(reply)
        except json.JSONDecodeError as error:
            raise RunBlocked(
                "X19_MALFORMED_JSON", f"{self.engine} adapter reply: {error}"
            ) from error
        if response.get("schema") != SCHEMA_ADAPTER:
            raise RunBlocked("X19_MALFORMED_JSON", "adapter schema mismatch")
        if response.get("engine") != self.engine:
            raise RunBlocked("X19_MALFORMED_JSON", "adapter engine mismatch")
        if response.get("status") != "ok":
            raise RunBlocked(
                "X28_ADAPTER_ERROR",
                json.dumps(response.get("error"), sort_keys=True),
            )
        return response

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            self.process.kill()
            self.process.wait(timeout=10)


def adapter_binary(engine: str, target_root: str) -> str:
    target_dir = confined_path(target_root, "build", engine)
    if engine == "quervant":
        return os.path.join(target_dir, "release", "pr15d-quervant-adapter")
    if engine == "tantivy":
        return os.path.join(target_dir, "release", "pr15d-tantivy-adapter")
    if engine == "lucene":
        return confined_path(
            target_root,
            "build",
            "lucene",
            "install",
            "pr15d-lucene-adapter",
            "bin",
            "pr15d-lucene-adapter",
        )
    raise RunBlocked("X99_UNKNOWN_ENGINE", engine)


def build_adapters(target_root: str) -> dict:
    """Build every adapter outside all timed regions."""
    outputs = {}
    for engine in ENGINES:
        directory = ADAPTER_DIRS[engine]
        if engine in ("quervant", "tantivy"):
            target_dir = confined_path(target_root, "build", engine)
            result = subprocess.run(
                [
                    "cargo",
                    "build",
                    "--release",
                    "--locked",
                    "--manifest-path",
                    os.path.join(directory, "Cargo.toml"),
                    "--target-dir",
                    target_dir,
                ],
                cwd=directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        elif engine == "lucene":
            gradle = os.path.join(directory, "gradlew")
            command = [gradle] if os.path.isfile(gradle) else ["gradle"]
            environment = dict(os.environ)
            environment["PR15D_LUCENE_BUILD_DIR"] = confined_path(
                target_root, "build", "lucene"
            )
            result = subprocess.run(
                [
                    *command,
                    "--no-daemon",
                    "--project-dir",
                    directory,
                    "installDist",
                ],
                cwd=directory,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        else:  # pragma: no cover - unreachable
            raise RunBlocked("X99_UNKNOWN_ENGINE", engine)
        if result.returncode != 0:
            raise RunBlocked(
                "X15_BUILD_FAILED", f"{engine} adapter build failed:\n{result.stdout[-4000:]}"
            )
        binary = adapter_binary(engine, target_root)
        if not os.path.isfile(binary):
            raise RunBlocked("X28_BUILD_OUTPUT", f"{engine} binary not found at {binary}")
        outputs[engine] = {
            "binary": binary,
            "command": command_line(result.args),
            "log_tail": result.stdout[-2000:],
        }
    return outputs


def command_line(args) -> str:
    if isinstance(args, str):
        return args
    return " ".join(args)


# ---------------------------------------------------------------------------
# Resource and corpus helpers
# ---------------------------------------------------------------------------


def directory_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(root, name)
            if os.path.islink(full):
                continue
            try:
                total += os.path.getsize(full)
            except OSError:
                continue
    return total


def read_vm_hwm(pid: int) -> int | None:
    text = _read_file(f"/proc/{pid}/status")
    if not text:
        return None
    for line in text.splitlines():
        if line.startswith("VmHWM:"):
            parts = line.split()
            try:
                return int(parts[1]) * 1024
            except (IndexError, ValueError):
                return None
    return None


def check_contention(out_path: str) -> dict:
    script = os.path.join(REPO_ROOT, "benchmarks/scripts/check-pr07-contention.py")
    result = subprocess.run(
        [
            sys.executable,
            script,
            "--out",
            out_path,
            "--sample-seconds",
            "2.0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    try:
        record = read_json(out_path)
    except (OSError, json.JSONDecodeError):
        record = {
            "state": "unknown",
            "reason_codes": ["probe_failed"],
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    return record


# ---------------------------------------------------------------------------
# Measurement orchestration
# ---------------------------------------------------------------------------


def read_adapter_metadata(engine: str, binary: str) -> dict:
    process = AdapterProcess(engine, [binary])
    try:
        response = process.request({"request_id": "metadata:0", "op": "metadata"})
    finally:
        process.close()
    for field in ("engine_version", "adapter_version", "analyzer"):
        if not response.get(field):
            raise RunBlocked(
                "X09_ENGINE_VERSION", f"{engine} metadata missing {field}"
            )
    if response["analyzer"] != ANALYZER:
        raise RunBlocked(
            "X40_ANALYZER",
            f"{engine} declares analyzer {response['analyzer']!r}, expected {ANALYZER!r}",
        )
    return response


def build_index(
    engine: str, binary: str, corpus_path: str, index_dir: str, expected_rows: int
) -> dict:
    if os.path.exists(index_dir):
        shutil.rmtree(index_dir)
    os.makedirs(index_dir, exist_ok=True)
    process = AdapterProcess(engine, [binary])
    try:
        response = process.request(
            {
                "request_id": f"build:{engine}:{os.path.basename(index_dir)}",
                "op": "build",
                "corpus_path": corpus_path,
                "index_dir": index_dir,
            }
        )
    finally:
        process.close()
    if response.get("documents_indexed") != expected_rows:
        raise RunBlocked(
            "X28_DOCUMENT_COUNT",
            f"{engine}: indexed {response.get('documents_indexed')} != {expected_rows}",
        )
    if response.get("documents_verified") != expected_rows:
        raise RunBlocked(
            "X28_DOCUMENT_COUNT",
            f"{engine}: reopened reader verified {response.get('documents_verified')}",
        )
    for field in ("index_ns", "commit_ns", "reopen_ns"):
        value = response.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RunBlocked("X07_DURATION", f"{engine} build {field}={value!r}")
    measured_bytes = directory_bytes(index_dir)
    if response.get("index_bytes") != measured_bytes:
        raise RunBlocked(
            "X28_INDEX_BYTES",
            f"{engine}: adapter index_bytes {response.get('index_bytes')} != measured {measured_bytes}",
        )
    return {
        "documents_indexed": response["documents_indexed"],
        "documents_verified": response["documents_verified"],
        "expected_documents": expected_rows,
        "index_ns": response["index_ns"],
        "commit_ns": response["commit_ns"],
        "reopen_ns": response["reopen_ns"],
        "index_bytes": measured_bytes,
        "segment_count": response.get("segment_count"),
        "verified": True,
    }


def _adapter_command(engine: str, binary: str, index_dir: str) -> list[str]:
    if engine == "lucene":
        return [binary, "--index-dir", index_dir]
    return [binary, "--index-dir", index_dir]


def measure_lane(
    engine: str,
    binary: str,
    index_dir: str,
    lane: dict,
    expected: dict,
    adapter_metadata: dict,
    contention: dict,
) -> dict:
    """Measure one (N, class, K, regime) lane, validating every sample."""
    samples = []
    warmup_responses = []
    if lane["regime"] == "warm":
        process = AdapterProcess(engine, _adapter_command(engine, binary, index_dir))
        try:
            for warmup in range(WARMUPS):
                response = process.request(
                    {
                        "request_id": f"{lane['id']}:warmup:{warmup}",
                        "op": "query",
                        "field": lane["field"],
                        "term": lane["term"],
                        "k": lane["k"],
                        "mode": lane["regime"],
                    }
                )
                warmup_responses.append(response)
            for sample in range(MEASURED):
                response = process.request(
                    {
                        "request_id": f"{lane['id']}:sample:{sample}",
                        "op": "query",
                        "field": lane["field"],
                        "term": lane["term"],
                        "k": lane["k"],
                        "mode": lane["regime"],
                    }
                )
                validate_query_response(response, lane, expected)
                samples.append(response["engine_ns"])
        finally:
            process.close()
    else:
        for sample in range(MEASURED):
            process = AdapterProcess(engine, _adapter_command(engine, binary, index_dir))
            try:
                response = process.request(
                    {
                        "request_id": f"{lane['id']}:sample:{sample}",
                        "op": "query",
                        "field": lane["field"],
                        "term": lane["term"],
                        "k": lane["k"],
                        "mode": lane["regime"],
                    }
                )
                validate_query_response(response, lane, expected)
                samples.append(response["engine_ns"])
            finally:
                process.close()
    if len(samples) != MEASURED:
        raise RunBlocked("X33_SAMPLE_COUNT", f"{lane['id']} collected {len(samples)}")
    summary = summarize(samples)
    return {
        "id": lane["id"],
        "n": lane["n"],
        "class": lane["class"],
        "field": lane["field"],
        "term": lane["term"],
        "k": lane["k"],
        "regime": lane["regime"],
        "warmups": WARMUPS if lane["regime"] == "warm" else 0,
        "warmup_ids": [response["request_id"] for response in warmup_responses],
        "samples_ns": samples,
        "summary_ns": summary,
        "total_hits": expected["total_hits"],
        "doc_ids": expected["doc_ids"],
        "expected_total_hits": expected["total_hits"],
        "expected_doc_ids": expected["doc_ids"],
        "oracle_ok": True,
        "analyzer": adapter_metadata["analyzer"],
        "contention": contention,
        "rss_peak_bytes": None,
        "cpu_ns": None,
        "allocations": "NOT_MEASURED",
    }


def validate_query_response(response: dict, lane: dict, expected: dict) -> None:
    engine_ns = response.get("engine_ns")
    if isinstance(engine_ns, bool) or not isinstance(engine_ns, int) or engine_ns <= 0:
        raise RunBlocked("X07_DURATION", f"{lane['id']}: invalid engine_ns {engine_ns!r}")
    if response.get("total_hits") != expected["total_hits"]:
        raise RunBlocked(
            "X29_ORACLE",
            f"{lane['id']}: total_hits {response.get('total_hits')} != {expected['total_hits']}",
        )
    if response.get("doc_ids") != expected["doc_ids"]:
        raise RunBlocked("X29_ORACLE", f"{lane['id']}: doc_ids differ from oracle")


def throughput_window(
    engine: str, binary: str, index_dir: str, lane: dict
) -> dict:
    process = AdapterProcess(engine, _adapter_command(engine, binary, index_dir))
    try:
        for warmup in range(WARMUPS):
            process.request(
                {
                    "request_id": f"throughput:warmup:{warmup}",
                    "op": "query",
                    "field": lane["field"],
                    "term": lane["term"],
                    "k": lane["k"],
                    "mode": "warm",
                }
            )
        started = time.monotonic_ns()
        for index in range(THROUGHPUT_REQUESTS):
            process.request(
                {
                    "request_id": f"throughput:{index}",
                    "op": "query",
                    "field": lane["field"],
                    "term": lane["term"],
                    "k": lane["k"],
                    "mode": "warm",
                }
            )
        wall_ns = time.monotonic_ns() - started
    finally:
        process.close()
    if wall_ns <= 0:
        raise RunBlocked("X07_DURATION", "throughput wall duration is not positive")
    return {
        "n": lane["n"],
        "lane_id": lane["id"],
        "requests": THROUGHPUT_REQUESTS,
        "wall_ns": wall_ns,
        "serial_ops_per_second": round(THROUGHPUT_REQUESTS * 1_000_000_000 / wall_ns, 6),
        "label": "serial_ops_per_second",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_blocked_record(run_dir: str, environment: dict, adapters: dict, blockers: list) -> dict:
    return {
        "schema": SCHEMA_RUN,
        "run_id": os.path.basename(os.path.abspath(run_dir)),
        "source_sha": source_sha(),
        "workload": WORKLOAD,
        "environment": environment,
        "host_fingerprint": host_fingerprint(environment),
        "adapters": adapters,
        "status": "blocked",
        "blockers": blockers,
        "trials": 0,
        "qualified": False,
    }


def run(args) -> int:
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    environment = collect_environment(out_dir)
    adapters = preflight_adapters()
    blockers = preflight_blockers(adapters)

    if not args.idle_confirmed:
        blockers.append(
            {
                "engine": "host",
                "rule": "X24_DEFER_ATTESTATION",
                "code": "IDLE_ATTESTATION_MISSING",
                "detail": "the actual operator must supply --idle-confirmed",
            }
        )
    if not tracked_tree_clean():
        blockers.append(
            {
                "engine": "host",
                "rule": "X27_HARD_STOP",
                "code": "DIRTY_TRACKED_TREE",
                "detail": "Git tracked tree is not clean; refusing to time",
            }
        )
    if not environment["native_filesystem"]:
        blockers.append(
            {
                "engine": "host",
                "rule": "X23_DEFER_ENVIRONMENT",
                "code": "NON_NATIVE_FILESYSTEM",
                "detail": f"filesystem is {environment['filesystem']!r}, not ext4/xfs/btrfs",
            }
        )
    if args.trials != REQUIRED_TRIALS:
        blockers.append(
            {
                "engine": "host",
                "rule": "X32_DEFER_QUALIFICATION",
                "code": "TRIAL_COUNT",
                "detail": f"--trials must be {REQUIRED_TRIALS} for qualification",
            }
        )

    if blockers:
        record = build_blocked_record(out_dir, environment, adapters, blockers)
        if args.allow_contended:
            record["status"] = "diagnostic"
        write_json(confined_path(out_dir, "run.json"), record)
        print(
            "BLOCKED: " + "; ".join(f"{b['rule']}:{b['code']}" for b in blockers),
            file=sys.stderr,
        )
        return 4

    # Everything below is reachable only on a fully provisioned, clean host with
    # all three pinned adapters. The plan's S5 gate additionally requires the
    # operator to run from an unmodified frozen source lock.
    corpus_dir = os.path.abspath(args.corpus)
    manifest, rows_by_n = oracle.load_and_verify(corpus_dir)
    source = source_sha()
    fingerprint = host_fingerprint(environment)
    run_record = {
        "schema": SCHEMA_RUN,
        "run_id": os.path.basename(out_dir),
        "source_sha": source,
        "workload": WORKLOAD,
        "corpus_dir": corpus_dir,
        "corpus_manifest_sha256": oracle.sha256_bytes(
            oracle.canonical_json_bytes(manifest)
        ),
        "corpus_digests": {
            str(entry["n"]): entry["sha256"] for entry in manifest["corpora"]
        },
        "environment": environment,
        "host_fingerprint": fingerprint,
        "adapters": adapters,
        "idle_attested": True,
        "native_filesystem": environment["native_filesystem"],
        "filesystem": environment["filesystem"],
        "trials": args.trials,
        "status": "running",
        "qualified": False,
        "blockers": [],
        "scored_lane": {
            "status": "SEMANTICALLY_NONCOMPARABLE",
            "reason": "no verified cross-engine BM25 k1/b/length/tie contract",
        },
    }
    write_json(confined_path(out_dir, "run.json"), run_record)

    binaries = build_adapters(out_dir)
    metadata = {
        engine: read_adapter_metadata(engine, binaries[engine]["binary"])
        for engine in ENGINES
    }
    run_record["adapter_metadata"] = metadata
    write_json(confined_path(out_dir, "run.json"), run_record)

    any_unqualified = False
    for trial in range(1, args.trials + 1):
        for engine in TRIAL_ORDER[trial]:
            trial_manifest = measure_engine_trial(
                engine=engine,
                trial=trial,
                source=source,
                fingerprint=fingerprint,
                environment=environment,
                manifest=manifest,
                rows_by_n=rows_by_n,
                corpus_dir=corpus_dir,
                out_dir=out_dir,
                binary=binaries[engine]["binary"],
                adapter_metadata=metadata[engine],
                allow_contended=args.allow_contended,
            )
            write_json(
                confined_path(out_dir, "trials", f"trial-{trial}", f"{engine}.json"),
                trial_manifest,
            )
            if not trial_manifest["qualified"]:
                any_unqualified = True

    run_record["status"] = "complete"
    run_record["qualified"] = not any_unqualified
    write_json(confined_path(out_dir, "run.json"), run_record)
    return 0 if run_record["qualified"] else 3


def measure_engine_trial(
    *,
    engine: str,
    trial: int,
    source: str,
    fingerprint: str,
    environment: dict,
    manifest: dict,
    rows_by_n: dict,
    corpus_dir: str,
    out_dir: str,
    binary: str,
    adapter_metadata: dict,
    allow_contended: bool,
) -> dict:
    reasons = []
    contention_records = []
    build_metrics = {}
    lanes = []
    throughput = []
    for n in N_VALUES:
        corpus_path = confined_path(corpus_dir, oracle.corpus_filename(n))
        index_dir = confined_path(out_dir, "indexes", f"trial-{trial}", engine, f"n{n}")
        build_metrics[str(n)] = build_index(
            engine, binary, corpus_path, index_dir, expected_rows=n
        )
        pre_path = confined_path(
            out_dir, "contention", f"trial-{trial}", engine, f"n{n}-pre.json"
        )
        os.makedirs(os.path.dirname(pre_path), exist_ok=True)
        pre = check_contention(pre_path)
        contention_records.append({"phase": "pre", "n": n, **pre})
        if pre.get("state") != "clear":
            reasons.append(f"pre-contention:{pre.get('state')}")
        if pre.get("state") != "clear" and not allow_contended:
            raise RunBlocked("X26_CONTENTION", json.dumps(pre, sort_keys=True))

        for descriptor in lane_descriptors():
            if descriptor["n"] != n:
                continue
            expected = oracle.expected(
                rows_by_n[n], descriptor["field"], descriptor["term"], descriptor["k"]
            )
            lanes.append(
                measure_lane(
                    engine,
                    binary,
                    index_dir,
                    descriptor,
                    expected,
                    adapter_metadata,
                    {"pre": pre.get("state"), "post": None},
                )
            )
        post_path = confined_path(
            out_dir, "contention", f"trial-{trial}", engine, f"n{n}-post.json"
        )
        post = check_contention(post_path)
        contention_records.append({"phase": "post", "n": n, **post})
        if post.get("state") != "clear":
            reasons.append(f"post-contention:{post.get('state')}")
        for lane in lanes:
            if lane["n"] == n:
                lane["contention"]["post"] = post.get("state")
        throughput.append(
            throughput_window(
                engine,
                binary,
                index_dir,
                {
                    "id": lane_id(n, "medium", 10),
                    "n": n,
                    "class": "medium",
                    "field": "group",
                    "term": "medium",
                    "k": 10,
                    "regime": "warm",
                },
            )
        )
        final_path = confined_path(
            out_dir, "contention", f"trial-{trial}", engine, f"n{n}-final.json"
        )
        final = check_contention(final_path)
        contention_records.append({"phase": "final", "n": n, **final})
        if final.get("state") != "clear":
            reasons.append(f"final-contention:{final.get('state')}")

    return {
        "schema": SCHEMA_TRIAL,
        "trial": trial,
        "engine": engine,
        "engine_version": adapter_metadata["engine_version"],
        "adapter_version": adapter_metadata["adapter_version"],
        "source_sha": source,
        "release_build": True,
        "host_fingerprint": fingerprint,
        "filesystem": environment["filesystem"],
        "native_filesystem": environment["native_filesystem"],
        "operator_idle_attested": True,
        "corpus_manifest_sha256": oracle.sha256_bytes(
            oracle.canonical_json_bytes(manifest)
        ),
        "corpus_digests": {
            str(entry["n"]): entry["sha256"] for entry in manifest["corpora"]
        },
        "analyzer_map": {
            "doc_id": ANALYZER,
            "key": ANALYZER,
            "group": ANALYZER,
        },
        "build": build_metrics,
        "lanes": lanes,
        "throughput": throughput,
        "contention": contention_records,
        "status": "ok" if not reasons else "unqualified",
        "qualified": not reasons,
        "unqualified_reasons": reasons,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run PR15D comparative qualification.")
    parser.add_argument("--trials", type=int, default=REQUIRED_TRIALS)
    parser.add_argument("--idle-confirmed", action="store_true")
    parser.add_argument("--allow-contended", action="store_true")
    parser.add_argument("--out", required=True)
    parser.add_argument("--corpus", default=os.path.join(REPO_ROOT, "target/pr15d/corpus"))
    args = parser.parse_args(argv)
    try:
        return run(args)
    except RunBlocked as error:
        print(f"{error.rule}: {error.detail}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
