"""Reusable, fail-closed BM-10 build/index preparation (not benchmark evidence).

Only configuration JSON and result JSON are durable benchmark artifacts.
This ephemeral cache lives under target/bm10/prepared. A content mismatch
requires a new preparation, not a source/evidence attestation or approval.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .artifacts import ArtifactError, load_configuration
from .configuration import STRING_SORT_CONTRACT, lanes_for, validate_configuration
from . import runtime

CACHE_SCHEMA = "bm10-prepared-inputs-v1"
RESULT_PATH = re.compile(r"benchmarks/studies/[^/]+/[^/]+/results/[^/]+\.json\Z")
ENV_KEYS = {"PATH", "CC", "CXX", "RUSTFLAGS", "RUSTDOCFLAGS",
            "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "GRADLE_OPTS"}
ENV_PREFIXES = ("CARGO_", "RUSTUP_", "RUSTC_", "RUST_", "JAVA_", "GRADLE_", "QUERVANT_")
# Only checked-out build/runner source affects executable/index preparation.
# Generated test output, untracked results and unrelated notes may coexist.
SOURCE_PATHS = (
    "crates", "benchmarks/pr15d", "benchmarks/quervant_bench",
    "benchmarks/pyproject.toml", "Cargo.toml", "Cargo.lock",
    ".cargo", "rust-toolchain.toml",
)


def _json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _seconds(start: int) -> int:
    return max(1, time.monotonic_ns() - start)


def _clean_source(root: Path) -> str:
    """Allow new untracked benchmark results; refuse uncommitted source changes."""
    sha = runtime._git(root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise runtime.MeasurementBlocked("preparation source revision is not a Git SHA")
    lines = runtime._git(root, "status", "--porcelain=v1",
                         "--untracked-files=all", "--", *SOURCE_PATHS)
    for line in lines.splitlines():
        if not line:
            continue
        if line.startswith("?? ") and RESULT_PATH.fullmatch(line[3:]):
            continue
        raise runtime.MeasurementBlocked(
            "preparation cache requires a committed clean source tree "
            "(untracked benchmark result JSON is permitted)")
    return sha


def source_identity(root: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    """Cache relevant Git source trees rather than unrelated result-only commits.

    Every included input is read from a committed, clean worktree. A commit
    which only adds result JSON or documentation can therefore reuse the same
    compiled executables and indexes; changing a source tree cannot.
    """
    _clean_source(root)
    arm_revisions: dict[str, str] = {}
    if config["family"] in ("perf-02", "perf-05", "perf-06"):
        arm_ids = ("B",) if config["family"] == "perf-05" else ("A", "B")
        for arm_id in arm_ids:
            revision = config["arms"][arm_id]["revision"]
            # The config validator already requires full 40-hex commit IDs;
            # reject missing/ambiguous objects before any build/index writes.
            try:
                kind = runtime._git(root, "cat-file", "-t", revision)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                raise runtime.MeasurementBlocked(
                    f"{config['family']} arm {arm_id} pinned revision unavailable") from error
            if kind != "commit":
                raise runtime.MeasurementBlocked(
                    f"{config['family']} arm {arm_id} revision does not identify a Git commit")
            arm_revisions[arm_id] = revision
    source_objects: dict[str, str] = {}
    for path in SOURCE_PATHS:
        row = runtime._git(root, "ls-tree", "HEAD", "--", path)
        if not row:
            source_objects[path] = "ABSENT"
            continue
        lines = row.splitlines()
        if len(lines) != 1 or "\t" not in lines[0]:
            raise runtime.MeasurementBlocked("ambiguous preparation source object")
        head, actual_path = lines[0].split("\t", 1)
        fields = head.split()
        if (actual_path != path or len(fields) != 3
                or fields[1] not in ("tree", "blob")
                or not re.fullmatch(r"[0-9a-f]{40}", fields[2])):
            raise runtime.MeasurementBlocked("invalid preparation source tree identity")
        source_objects[path] = fields[2]
    selected = {k: v for k, v in os.environ.items()
                if k in ENV_KEYS or k.startswith(ENV_PREFIXES)}
    # Never write actual environment values (which might contain credentials).
    env_sha = _digest(selected)
    info = {
        "build_source_objects": source_objects,
        "arm_source_revisions": arm_revisions,
        "checkout_root": str(root.resolve()),
        "config_sha256": _digest(config),
        "toolchains": {
            "rustc": runtime._tool(["rustc", "--version"]),
            "cargo": runtime._tool(["cargo", "--version"]),
            "java": (runtime._tool(["java", "--version"])
                     if config["family"] == "cross-engine" else "NOT_REQUIRED"),
        },
        "platform": platform.platform(),
        "host_node": platform.node(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "environment_sha256": env_sha,
    }
    if any(v == "UNAVAILABLE" for v in info["toolchains"].values()):
        raise runtime.MeasurementBlocked("preparation toolchain identity unavailable")
    return info


@contextmanager
def _preparation_lock(directory: Path) -> Iterator[None]:
    """One cache-directory inode lock prevents partial publication and races."""
    if directory.is_symlink():
        raise runtime.MeasurementBlocked("preparation root cannot be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(directory, flags)
    except OSError as error:
        raise runtime.MeasurementBlocked(f"cannot lock preparation directory: {error}") from error
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _artifact_paths(cache_dir: Path, programs: Mapping[str, Sequence[str]]) -> list[Path]:
    """Hash only required executables/distribution, corpora and index files.

    Cargo/Gradle intermediates are not consulted during reuse and can be large.
    """
    selected: set[Path] = set()
    for name in ("corpus", "indexes"):
        base = cache_dir / name
        if not base.is_dir() or base.is_symlink():
            raise runtime.MeasurementBlocked(f"prepared {name} directory missing or symlinked")
        selected.update(path for path in base.rglob("*") if path.is_file() or path.is_symlink())
    for command in programs.values():
        if not isinstance(command, (list, tuple)) or not command:
            raise runtime.MeasurementBlocked("prepared adapter command is empty")
        binary = Path(command[0])
        if not binary.is_absolute() or not binary.is_relative_to(cache_dir):
            raise runtime.MeasurementBlocked("prepared adapter must live inside its cache entry")
        selected.add(binary)
        if "lucene" in binary.parts:
            # Include the whole installDist, not just its launcher: the Java
            # adapter needs distribution JARs and launcher scripts at runtime.
            distribution = binary.parent.parent
            selected.update(path for path in distribution.rglob("*")
                            if path.is_file() or path.is_symlink())
    if not selected:
        raise runtime.MeasurementBlocked("prepared inputs are empty")
    return sorted(selected)


def _fingerprints(cache_dir: Path, programs: Mapping[str, Sequence[str]]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for path in _artifact_paths(cache_dir, programs):
        if (not path.is_file() or
                not path.resolve().is_relative_to(cache_dir.resolve()) or
                any(parent.is_symlink() for parent in (path, *path.parents)
                    if parent == cache_dir or cache_dir in parent.parents)):
            raise runtime.MeasurementBlocked(f"prepared artifact unavailable or symlinked: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        entries[path.relative_to(cache_dir).as_posix()] = {
            "sha256": digest.hexdigest(), "bytes": path.stat().st_size,
        }
    return entries


def _commands_from_cache(cache_dir: Path, config: Mapping[str, Any]) -> dict[str, list[str]]:
    commands: dict[str, list[str]] = {}
    for arm, spec in config["arms"].items():
        engine = spec["engine"]
        if engine in ("quervant", "tantivy"):
            root = ("baseline" if arm == "A" and config["family"] == "retained-key"
                    else f"quervant-{arm.lower()}" if config["family"] in ("perf-02", "perf-05", "perf-06")
                    else engine)
            binary = cache_dir / "build" / root / "release" / f"pr15d-{engine}-adapter"
            commands[arm] = [str(binary)]
        elif engine == "lucene":
            commands[arm] = [str(cache_dir / "build" / "lucene" / "install"
                                  / "pr15d-lucene-adapter" / "bin" / "pr15d-lucene-adapter")]
        else:
            raise runtime.MeasurementBlocked(f"unknown adapter engine: {engine}")
    return commands


def _verify_oracles(config: Mapping[str, Any], programs: Mapping[str, list[str]],
                    indexes: Mapping[str, Mapping[int, Path]], cpu: int | None) -> None:
    """Untimed oracle smoke for every declared lane, including every reused index."""
    lanes = lanes_for(config)
    for arm_id, arm in config["arms"].items():
        by_group: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for lane in lanes:
            _env, marker = runtime._strategy(config, arm_id, lane)
            by_group.setdefault((lane["n"], marker or "default"), []).append(lane)
        for (size, _marker), group in by_group.items():
            env, marker = runtime._strategy(config, arm_id, group[0])
            reqs = [{
                "request_id": f"preparation:{arm_id}:{lane['id']}",
                "op": "query", "field": lane["field"], "term": lane["term"],
                "k": lane["k"], "mode": "warm",
            } for lane in group]
            command = [*programs[arm_id], "--index-dir", str(indexes[arm_id][size])]
            done = runtime._run_pinned(command, cpu, env=env,
                                       input_text="".join(json.dumps(r) + "\n" for r in reqs),
                                       timeout=900)
            replies = runtime._decode_responses(done, reqs, engine=arm["engine"])
            runtime._check_marker(done, marker, engine=arm["engine"])
            for lane, reply in zip(group, replies):
                expected = runtime.expected_answer(size, lane["field"], lane["term"], lane["k"])
                runtime.validate_reply(reply, lane, expected)


def _existing_inputs(cache_dir: Path, config: Mapping[str, Any]) -> tuple[
        dict[str, list[str]], dict[str, dict[int, Path]]]:
    programs = _commands_from_cache(cache_dir, config)
    indexes = {arm: {n: cache_dir / "indexes" / arm / f"n{n}"
                     for n in config["workload"]["sizes"]} for arm in config["arms"]}
    return programs, indexes


def _load_cache(cache_dir: Path, identity: Mapping[str, Any],
                config: Mapping[str, Any]) -> dict[str, Any] | None:
    manifest = cache_dir / "prepared.json"
    if cache_dir.is_symlink():
        raise runtime.MeasurementBlocked("prepared cache entry must not be a symlink")
    if not manifest.is_file() or manifest.is_symlink():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("schema") != CACHE_SCHEMA
                or data.get("identity") != identity or
                data.get("config_name") != config["name"] or
                data.get("config_id") != config["configuration_id"]):
            return None
        programs, indexes = _existing_inputs(cache_dir, config)
        if data.get("file_fingerprints") != _fingerprints(cache_dir, programs):
            return None
        if not isinstance(data.get("index_metrics"), dict) or not isinstance(data.get("build_info"), dict):
            return None
        for arm in config["arms"]:
            for n in config["workload"]["sizes"]:
                metric = data["index_metrics"].get(arm, {}).get(str(n), {})
                if (not isinstance(metric, dict) or
                        any(isinstance(metric.get(x), bool) or
                            not isinstance(metric.get(x), int) or metric[x] <= 0
                            for x in ("index_ns", "commit_ns", "reopen_ns", "index_bytes"))):
                    return None
        return data
    except (OSError, ValueError, UnicodeError, KeyError, TypeError, RuntimeError,
            runtime.MeasurementBlocked):
        return None


def stage_inputs(config_path: Path, *, root: Path, scratch_root: Path | None = None,
                 check_host: bool = True, cpu: int | None = None) -> dict[str, Any]:
    """Stage or reuse complete inputs, rechecking actual search oracles each time.

    No benchmark treatment/A-A query measurements or result JSON are created.
    Uses committed build-source tree objects, configuration, toolchains, host
    and ordinary local file checksums purely for cache reuse. Interrupted incomplete staging is rebuilt; corrupt
    previously published staging blocks reuse and never deletes an entry while
    a concurrent measured run may still be using it.
    """
    config = load_configuration(config_path)
    validate_configuration(config)
    if config["family"] == "perf-05":
        # The immutable historical A identity is verified before the first B
        # build or index write, never after timed acquisition has begun.
        from .perf05 import verify_historical_reference
        verify_historical_reference(root, config)
    if (config["family"] == "cross-engine"
            and config["build"].get("sort_contract") != STRING_SORT_CONTRACT):
        raise runtime.MeasurementBlocked(
            "legacy cross-engine numeric-ordinal configuration cannot be staged; "
            "use a new native doc_id string-sort configuration")
    scratch = scratch_root or root / "target" / "bm10"
    if scratch.is_symlink():
        raise runtime.MeasurementBlocked("benchmark scratch directory must not be a symlink")
    scratch = scratch.resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    readiness_advisory = (
        config["family"] in ("perf-06", "cross-engine") and
        config["policy"]["readiness"].get("mode", "blocking") == "advisory")
    if check_host:
        host = runtime.host_context(scratch, check=True)
        if cpu is None:
            cpu = host["physical_core_candidates"][1][0]
    start = time.monotonic_ns()
    identity = source_identity(root, config)
    key = _digest(identity)
    cache_root = scratch / "prepared"
    cache_dir = cache_root / key
    timings: dict[str, int] = {}
    prepare_host: dict[str, Any] = {}
    with _preparation_lock(cache_root):
        cache_start = time.monotonic_ns()
        existing = _load_cache(cache_dir, identity, config) if cache_dir.exists() else None
        timings["lookup_ns"] = _seconds(cache_start)
        state = "HIT" if existing is not None else "BUILT"
        if existing is None:
            if cache_dir.is_symlink():
                raise runtime.MeasurementBlocked("prepared cache entry must not be a symlink")
            if cache_dir.exists():
                if (cache_dir / "prepared.json").exists():
                    # Never delete a previously completed cache that another
                    # concurrent measured run may still have open. An invalid
                    # published cache is a fail-closed operator intervention.
                    raise runtime.MeasurementBlocked(
                        "existing prepared cache failed validation; stop and "
                        "retire it only after all benchmark runs are complete")
                # No completed manifest: an earlier interrupted stage may be
                # rebuilt while holding the exclusive preparation lock.
                shutil.rmtree(cache_dir)
            cache_dir.mkdir()
            try:
                build_start = time.monotonic_ns()
                programs, build_info = runtime.build_programs(config, root, cache_dir)
                timings["build_ns"] = _seconds(build_start)
                corpus_start = time.monotonic_ns()
                (cache_dir / "corpus").mkdir()
                for n in config["workload"]["sizes"]:
                    runtime.create_corpus(cache_dir / "corpus" / f"keyword-n{n}.tsv", n)
                timings["corpus_ns"] = _seconds(corpus_start)
                if check_host:
                    readiness = config["policy"]["readiness"]
                    probe = runtime.observe_readiness(cpu, readiness, advisory=readiness_advisory)
                    prepare_host["readiness_index_pre"] = probe
                    if readiness_advisory:
                        prepare_host["readiness_mode"] = "advisory"
                    if probe["status"] != "clear" and not readiness_advisory:
                        raise runtime.MeasurementBlocked("host contention before indexing staged inputs")
                index_start = time.monotonic_ns()
                indexes = {}
                metrics = {}
                for arm_id, arm in config["arms"].items():
                    indexes[arm_id] = {}
                    metrics[arm_id] = {}
                    for n in config["workload"]["sizes"]:
                        target = cache_dir / "indexes" / arm_id / f"n{n}"
                        metrics[arm_id][str(n)] = runtime.build_index(
                            programs[arm_id], engine=arm["engine"],
                            corpus_path=cache_dir / "corpus" / f"keyword-n{n}.tsv",
                            target=target, n=n, cpu=cpu)
                        indexes[arm_id][n] = target
                timings["index_ns"] = _seconds(index_start)
                # No cached data is published until correctness passes.
                oracle_start = time.monotonic_ns()
                _verify_oracles(config, programs, indexes, cpu)
                timings["oracle_ns"] = _seconds(oracle_start)
                files = _fingerprints(cache_dir, programs)
                manifest = {
                    "schema": CACHE_SCHEMA,
                    "identity": identity,
                    "config_id": config["configuration_id"],
                    "config_name": config["name"],
                    "prepared_utc": _stamp(),
                    "index_metrics": metrics,
                    "build_info": build_info,
                    "file_fingerprints": files,
                    "host_checks": prepare_host,
                    "phase_durations_ns": dict(timings),
                }
                (cache_dir / "prepared.json").write_text(_json(manifest) + "\n", encoding="utf-8")
                existing = manifest
            except BaseException:
                shutil.rmtree(cache_dir)
                raise
        else:
            programs, indexes = _existing_inputs(cache_dir, config)
            oracle_start = time.monotonic_ns()
            _verify_oracles(config, programs, indexes, cpu)
            timings["oracle_ns"] = _seconds(oracle_start)
    if existing is None:
        raise runtime.MeasurementBlocked("preparation failed to publish required inputs")
    programs, indexes = _existing_inputs(cache_dir, config)
    return {
        "state": state,
        "key": key,
        "cache_dir": str(cache_dir),
        "programs": programs,
        "indexes": indexes,
        "index_metrics": existing["index_metrics"],
        "build_info": existing["build_info"],
        "prepared_utc": existing["prepared_utc"],
        "host_checks": existing["host_checks"],
        "phase_durations_ns": timings,
        "total_ns": _seconds(start),
    }
