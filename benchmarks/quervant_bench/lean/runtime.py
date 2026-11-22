"""Actual adapter execution with direct raw-sample capture.

No source attestations, seals or evidence receipts. The only durable benchmark
output is one result JSON; prepared input caches under target/ are disposable,
and their local cache metadata is not benchmark evidence.
All subprocess work is bounded and can be replaced with mocks in unit tests.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import time
import json
import os
import platform
import select
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from .artifacts import ArtifactError, load_configuration, publish_result, result_directory
from .configuration import CLASSES, lanes_for, now_utc, validate_configuration
from .statistics import analyze, schedule

ADAPTER_SCHEMA = "pr15d-adapter-v1"
HEADER = "doc_id\tkey\tgroup\tbody\tpayload\n"


class MeasurementBlocked(ArtifactError):
    """Real acquisition cannot continue; preserve observations already collected."""


def _run(argv: Sequence[str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None,
         timeout: int = 1800, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        done = subprocess.run(list(argv), cwd=cwd, env=env, input=input_text, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              shell=False, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MeasurementBlocked(f"subprocess failed: {argv[0]}: {error}") from error
    if done.returncode != 0:
        raise MeasurementBlocked(f"subprocess exit {done.returncode}: {argv[0]}: {done.stderr[-1500:]}")
    return done


def _tool(argv: Sequence[str]) -> str:
    try:
        return _run(argv, timeout=15).stdout.strip().splitlines()[0]
    except (MeasurementBlocked, IndexError):
        return "UNAVAILABLE"


def _git(root: Path, *args: str) -> str:
    return _run(["git", "-C", str(root), *args], timeout=30).stdout.strip()


def _filesystem(path: Path) -> str:
    return _tool(["findmnt", "-n", "-o", "FSTYPE", "-T", str(path)])


def _core_ids() -> list[tuple[int, int, int]]:
    """Identify different physical cores among CPUs available to this process."""
    if not hasattr(os, "sched_getaffinity"):
        return []
    found: list[tuple[int, int, int]] = []
    for cpu in sorted(os.sched_getaffinity(0)):
        base = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        try:
            package = int((base / "physical_package_id").read_text().strip())
            core = int((base / "core_id").read_text().strip())
        except (OSError, ValueError):
            return []
        if (package, core) not in {(x[1], x[2]) for x in found}:
            found.append((cpu, package, core))
    return found


def _cpu_ticks(cpu: int) -> tuple[int, int, int]:
    """Read Linux CPU busy/total/steal ticks without an evidence hash or token."""
    try:
        with open("/proc/stat", "r", encoding="ascii") as stream:
            fields = next((line.split() for line in stream if line.startswith(f"cpu{cpu} ")), None)
    except OSError as error:
        raise MeasurementBlocked(f"host CPU observation unavailable: {error}") from error
    if fields is None or len(fields) < 9:
        raise MeasurementBlocked(f"host CPU {cpu} observation missing")
    try:
        counts = [int(value) for value in fields[1:]]
    except ValueError as error:
        raise MeasurementBlocked("malformed /proc/stat CPU counters") from error
    if any(value < 0 for value in counts):
        raise MeasurementBlocked("negative /proc/stat CPU counter")
    idle = counts[3] + counts[4]
    return sum(counts), sum(counts) - idle, counts[7]


def assess_readiness(cpu: int, *, intervals: int = 4, interval_seconds: float = 0.25,
                     max_busy_percent: float = 25.0, max_steal_percent: float = 2.0) -> dict[str, Any]:
    """Acquire simple predeclared contention observations; no retries or approvals."""
    start = _cpu_ticks(cpu)
    readings: list[dict[str, float]] = []
    for _ in range(intervals):
        time.sleep(interval_seconds)
        end = _cpu_ticks(cpu)
        total = end[0] - start[0]
        busy = end[1] - start[1]
        steal = end[2] - start[2]
        if total <= 0 or busy < 0 or steal < 0 or busy > total or steal > total:
            raise MeasurementBlocked("invalid CPU counter delta during host readiness")
        readings.append({"busy_percent": round(100 * busy / total, 3),
                         "steal_percent": round(100 * steal / total, 3)})
        start = end
    maximum_busy = max(item["busy_percent"] for item in readings)
    maximum_steal = max(item["steal_percent"] for item in readings)
    return {"cpu":cpu, "observations":readings, "max_busy_percent":max_busy_percent,
            "max_steal_percent":max_steal_percent,
            "status":"clear" if maximum_busy <= max_busy_percent and maximum_steal <= max_steal_percent else "busy"}


@contextmanager
def pinned_controller(cpu: int | None):
    """Keep controller and engine process on distinct CPUs during timing."""
    if cpu is None:
        yield
        return
    if not hasattr(os, "sched_setaffinity"):
        raise MeasurementBlocked("CPU affinity API unavailable")
    original = os.sched_getaffinity(0)
    try:
        os.sched_setaffinity(0, {cpu})
        yield
    except OSError as error:
        raise MeasurementBlocked(f"cannot pin controller to CPU {cpu}: {error}") from error
    finally:
        os.sched_setaffinity(0, original)


def host_context(scratch: Path, *, check: bool = True) -> dict[str, Any]:
    """Real host capability check, never a time-bound authorization token."""
    cores = _core_ids()
    fs = _filesystem(scratch)
    uname = platform.uname()
    info = {"system": uname.system, "kernel": uname.release,
            "architecture": uname.machine, "cpu": platform.processor(),
            "physical_core_candidates": cores, "filesystem": fs,
            "wsl": "microsoft" in uname.release.lower() or "wsl" in uname.release.lower(),
            "toolchains": {"rustc": _tool(["rustc", "--version"]),
                           "cargo": _tool(["cargo", "--version"]),
                           "java": _tool(["java", "--version"]),
                           "python": platform.python_version()}}
    if check:
        if uname.system != "Linux":
            raise MeasurementBlocked("real benchmark runs require Linux or WSL2")
        if fs not in ("ext4", "xfs", "btrfs"):
            raise MeasurementBlocked(f"benchmark scratch must use a native Linux filesystem (found {fs})")
        if len(cores) < 2:
            raise MeasurementBlocked("two distinct available physical CPU cores are required")
        if shutil.which("taskset") is None:
            raise MeasurementBlocked("taskset is required for adapter CPU affinity")
        if info["toolchains"]["rustc"] == "UNAVAILABLE":
            raise MeasurementBlocked("Rust toolchain unavailable")
    return info


def _run_pinned(argv: Sequence[str], cpu: int | None, *, env: Mapping[str, str] | None,
                input_text: str, timeout: int) -> subprocess.CompletedProcess[str]:
    command = (["taskset", "-c", str(cpu)] if cpu is not None else []) + list(argv)
    return _run(command, env=env, timeout=timeout, input_text=input_text)


def _build_rust(root: Path, target: Path, *, engine: str, feature: bool,
                source_root: Path | None = None) -> list[str]:
    work = source_root or root
    manifest = work / "benchmarks" / "pr15d" / "adapters" / engine / "Cargo.toml"
    if not manifest.is_file():
        raise MeasurementBlocked(f"adapter manifest unavailable: {manifest}")
    cmd = ["cargo", "build", "--release", "--locked", "--manifest-path", str(manifest),
           "--target-dir", str(target)]
    if feature:
        cmd.extend(["--features", "quervant-core/pr15i-d3c-experiment"])
    _run(cmd, cwd=manifest.parent)
    binary = target / "release" / f"pr15d-{engine}-adapter"
    if not binary.is_file():
        raise MeasurementBlocked(f"built executable is missing: {binary}")
    return [str(binary)]


def _build_lucene(root: Path, target: Path) -> list[str]:
    work = root / "benchmarks" / "pr15d" / "adapters" / "lucene"
    wrapper = work / "gradlew"
    if not wrapper.is_file():
        raise MeasurementBlocked("Lucene Gradle wrapper unavailable")
    env = dict(os.environ, PR15D_LUCENE_BUILD_DIR=str(target))
    _run(["sh", str(wrapper), "--no-daemon", "installDist"], cwd=work, env=env)
    binary = target / "install" / "pr15d-lucene-adapter" / "bin" / "pr15d-lucene-adapter"
    if not binary.is_file():
        raise MeasurementBlocked("Lucene installDist executable missing")
    return [str(binary)]


def build_programs(config: Mapping[str, Any], root: Path, scratch: Path) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """Build shared current release adapters and optional baseline source revision."""
    family = config["family"]
    command: dict[str, list[str]] = {}
    build = scratch / "build"
    # The cross-engine reference is the released production Quervant default:
    # never enable the historical strategy-override experiment for that build.
    # The retained-key diagnostic still needs explicit L/P/H variants.
    diagnostic_feature = family == "retained-key"
    log: dict[str, Any] = {
        "source_revision": _git(root, "rev-parse", "HEAD"),
        "compiler_options": "cargo --release --locked",
        "quervant_strategy_feature_enabled": diagnostic_feature,
    }
    q = _build_rust(root, build / "quervant", engine="quervant", feature=diagnostic_feature)
    if family == "retained-key":
        ref = config["build"].get("baseline_ref")
        if not isinstance(ref, str) or not ref:
            raise MeasurementBlocked("retained-key A requires a pinned baseline source ref")
        checkout = scratch / "baseline-source"
        _run(["git", "-C", str(root), "worktree", "add", "--detach", str(checkout), ref], timeout=180)
        try:
            command["A"] = _build_rust(root, build / "baseline", engine="quervant",
                                        feature=False, source_root=checkout)
        finally:
            _run(["git", "-C", str(root), "worktree", "remove", "--force", str(checkout)], timeout=180)
        for arm in ("L", "P", "H"):
            command[arm] = q
        log["baseline_ref"] = ref
    else:
        command["Q"] = q
        command["T"] = _build_rust(root, build / "tantivy", engine="tantivy", feature=False)
        command["J"] = _build_lucene(root, build / "lucene")
    return command, log


def row_values(i: int) -> tuple[str, str, str, str, str]:
    """Reviewed independent PR15D formula; does not load frozen manifest digests."""
    key = "singleton" if i == 0 else ("common" if i % 2 == 0 else "other")
    return (f"d{i:08d}", key, "medium" if i % 8 == 0 else "different",
            "alpha beta" if i % 2 == 0 else "gamma delta", f"payload-{i:08d}")


def create_corpus(path: Path, n: int) -> None:
    if n not in (10_000, 100_000):
        raise MeasurementBlocked("unsupported corpus size")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(HEADER)
        for i in range(n):
            stream.write("\t".join(row_values(i)) + "\n")


def expected_answer(n: int, field: str, term: str, k: int) -> tuple[int, list[str]]:
    if (field, term) not in CLASSES.values() or n not in (10_000, 100_000) or k < 1:
        raise MeasurementBlocked("unknown exact-term lane")
    if (field, term) == CLASSES["absent"]:
        ids: list[int] = []
    elif (field, term) == CLASSES["rare"]:
        ids = [0]
    elif (field, term) == CLASSES["medium"]:
        ids = list(range(0, n, 8))
    else:
        ids = list(range(2, n, 2))
    return len(ids), [f"d{i:08d}" for i in ids[:k]]


def _index_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def _decode_responses(done: subprocess.CompletedProcess[str], requests: list[dict[str, Any]],
                      *, engine: str) -> list[dict[str, Any]]:
    try:
        lines = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
    except (ValueError, TypeError) as error:
        raise MeasurementBlocked("malformed adapter JSON reply") from error
    if len(lines) != len(requests):
        raise MeasurementBlocked(f"adapter reply count differs from request count ({engine})")
    for request, reply in zip(requests, lines):
        if (not isinstance(reply, dict) or reply.get("schema") != ADAPTER_SCHEMA or
                reply.get("engine") != engine or reply.get("request_id") != request["request_id"] or
                reply.get("status") != "ok"):
            raise MeasurementBlocked(f"adapter reply disagrees with request/schema/status: {engine}")
    return lines


def _strategy(config: Mapping[str, Any], arm_id: str, lane: Mapping[str, Any]) -> tuple[dict[str, str], str | None]:
    """Experiment-specific runtime flags, not cryptographic build identity."""
    arm = config["arms"].get(arm_id)
    if arm is None:  # controls use the current or reference arm
        arm = config["arms"][config["baseline"]]
    mode = arm["mode"]
    env = dict(os.environ)
    # "by-top-k" describes the accepted *production* dispatch (currently
    # linear below K=32, P2 prefilter at and above K=32). Do not force
    # historical experiment environment overrides: the binary itself owns
    # this policy via TopKDuplicateConfig::default().
    if mode in ("BASE", "default", "by-top-k"):
        env.pop("QUERVANT_PR15I_D3C_STRATEGY", None)
        env.pop("QUERVANT_PR15I_D3C_PREFILTER_PROFILE", None)
        return env, None
    env["QUERVANT_PR15I_D3C_STRATEGY"] = mode
    if mode == "prefilter":
        env["QUERVANT_PR15I_D3C_PREFILTER_PROFILE"] = "P2"
    else:
        env.pop("QUERVANT_PR15I_D3C_PREFILTER_PROFILE", None)
    return env, f"PR15I_D3C_MODE=v1:{mode}:{'P2' if mode == 'prefilter' else 'none'}"


def _check_marker(done: subprocess.CompletedProcess[str], marker: str | None, *, engine: str) -> None:
    if engine != "quervant":
        return
    observed = [line.strip() for line in done.stderr.splitlines() if "PR15I_D3C_MODE=" in line]
    if marker is not None and not any(marker in line for line in observed):
        raise MeasurementBlocked(f"strategy P2/linear/exact_set was not demonstrated (expected {marker})")
    if marker is None and observed:
        raise MeasurementBlocked("default/baseline Quervant emitted an unexpected strategy override marker")
    if marker is not None and any(marker not in line for line in observed):
        raise MeasurementBlocked("unexpected strategy marker in adapter stderr")


def build_index(command: Sequence[str], *, engine: str, corpus_path: Path,
                target: Path, n: int, cpu: int | None = None) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=False)
    request = {"request_id": "build", "op": "build", "corpus_path": str(corpus_path), "index_dir": str(target)}
    done = _run_pinned(command, cpu, env=None, input_text=json.dumps(request) + "\n", timeout=900)
    response = _decode_responses(done, [request], engine=engine)[0]
    if response.get("documents_indexed") != n or response.get("documents_verified") != n:
        raise MeasurementBlocked("index build did not index and reopen the expected document count")
    for metric in ("index_ns", "commit_ns", "reopen_ns", "index_bytes"):
        x = response.get(metric)
        if isinstance(x, bool) or not isinstance(x, int) or x <= 0:
            raise MeasurementBlocked(f"invalid index build metric: {metric}")
    size = _index_size(target)
    if size != response["index_bytes"]:
        raise MeasurementBlocked("index byte count does not agree with on-disk index")
    return {metric: response[metric] for metric in ("index_ns", "commit_ns", "reopen_ns", "index_bytes", "segment_count")}


def validate_reply(reply: Mapping[str, Any], lane: Mapping[str, Any], expected: tuple[int, list[str]]) -> int:
    total, doc_ids = expected
    if reply.get("total_hits") != total or reply.get("doc_ids") != doc_ids:
        raise MeasurementBlocked(f"independent oracle disagreement in {lane['id']}")
    duration = reply.get("engine_ns")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
        raise MeasurementBlocked(f"invalid measured engine duration in {lane['id']}")
    return duration


def collect_throughput(command: Sequence[str], *, engine: str, index_dir: Path,
                       lane: Mapping[str, Any], config: Mapping[str, Any], arm_id: str,
                       cpu: int | None, requests: int = 100) -> dict[str, Any]:
    """One real, warm, *steady-session* serial wall-clock throughput window.

    Adapter process and index/reader initialization occur before the timed
    window. Warmups are fully completed first. Each timed request is answered
    before the next is sent (no concurrency). Response decoding is transport
    overhead, identical for all three adapters. All replies are oracle-checked.
    """
    env, marker = _strategy(config, arm_id, lane)
    command_line = (["taskset", "-c", str(cpu)] if cpu is not None else []) + [*command, "--index-dir", str(index_dir)]
    try:
        process = subprocess.Popen(command_line, stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,text=True,bufsize=1,env=env)
    except OSError as error:
        raise MeasurementBlocked(f"cannot launch throughput adapter {engine}: {error}") from error
    responses: list[dict[str, Any]] = []
    error_message = ""
    try:
        if process.stdin is None or process.stdout is None:
            raise MeasurementBlocked("adapter has no JSONL request/response pipes")

        def request(request_id: str) -> dict[str, Any]:
            message = {"request_id":request_id,"op":"query","field":lane["field"],
                       "term":lane["term"],"k":lane["k"],"mode":"warm"}
            line = json.dumps(message, separators=(",",":")) + "\n"
            try:
                process.stdin.write(line)
                process.stdin.flush()
            except (OSError, BrokenPipeError) as error:
                raise MeasurementBlocked("throughput adapter request pipe closed") from error
            # One request at a time: no unread buffered response is possible.
            readable, _, _ = select.select([process.stdout], [], [], 60)
            if not readable:
                raise MeasurementBlocked(f"throughput adapter response timed out: {engine}")
            answer = process.stdout.readline()
            if not answer:
                raise MeasurementBlocked(f"throughput adapter exited before response: {engine}")
            try:
                response = json.loads(answer)
            except (TypeError, ValueError) as error:
                raise MeasurementBlocked("malformed throughput adapter JSON reply") from error
            if (not isinstance(response,dict) or response.get("schema") != ADAPTER_SCHEMA or
                    response.get("engine") != engine or response.get("request_id") != request_id or
                    response.get("status") != "ok"):
                raise MeasurementBlocked("throughput adapter reply mismatch")
            return response

        for index in range(config["policy"]["warmups"]):
            response = request(f"warmup:{index}")
            validate_reply(response,lane,expected_answer(lane["n"],lane["field"],lane["term"],lane["k"]))
        started = time.monotonic_ns()
        for index in range(requests):
            responses.append(request(f"sample:{index}"))
        elapsed = time.monotonic_ns() - started
        if elapsed <= 0:
            raise MeasurementBlocked("nonpositive throughput wall duration")
        expected = expected_answer(lane["n"],lane["field"],lane["term"],lane["k"])
        for response in responses:
            validate_reply(response,lane,expected)
    finally:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stderr is not None:
            error_message = process.stderr.read()[-4000:]
            process.stderr.close()
        if process.stdout is not None:
            process.stdout.close()
    if process.returncode != 0:
        raise MeasurementBlocked(f"throughput adapter exit {process.returncode}: {error_message[:1000]}")
    _check_marker(subprocess.CompletedProcess(command_line,process.returncode,"",error_message),marker,engine=engine)
    return {"lane_id":lane["id"],"requests":requests,"warmups":config["policy"]["warmups"],
            "wall_ns":elapsed,"serial_ops_per_second":round(requests * 1_000_000_000 / elapsed,6),
            "status":"MEASURED", "timing_scope":"serial session, JSONL transport included; process start excluded"}


def collect_cold_start(command: Sequence[str], *, engine: str, index_dir: Path,
                       lane: Mapping[str, Any], config: Mapping[str, Any],
                       arm_id: str, cpu: int | None, request_id: str,
                       timeout: int = 120) -> tuple[int, int, int]:
    """Measure process launch to the first complete JSONL reply, not shutdown.

    This is *not* pure executable startup: it includes loading the index,
    opening a reader, query execution, and JSONL transport. On the first query,
    the adapter MUST report its own independently timed index_open_ns and
    query-only engine_ns. Neither adapter timer includes the other operation.
    """
    env, marker = _strategy(config, arm_id, lane)
    request = {"request_id": request_id, "op": "query", "field": lane["field"],
               "term": lane["term"], "k": lane["k"], "mode": "process_cold"}
    argv = (["taskset", "-c", str(cpu)] if cpu is not None else []) + [
        *command, "--index-dir", str(index_dir)]
    started = time.monotonic_ns()
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=env, bufsize=0)
    except OSError as error:
        raise MeasurementBlocked(f"cannot launch cold-start adapter {engine}: {error}") from error
    try:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise MeasurementBlocked("cold-start adapter has no JSONL pipes")
        try:
            process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
            process.stdin.flush()
        except (OSError, BrokenPipeError) as error:
            raise MeasurementBlocked("cold-start adapter request pipe closed") from error
        finally:
            process.stdin.close()
            process.stdin = None
        deadline = time.monotonic() + timeout
        output = bytearray()
        while b"\n" not in output:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MeasurementBlocked(f"cold-start first reply timed out: {engine}")
            try:
                ready, _, _ = select.select([process.stdout], [], [], remaining)
                if not ready:
                    raise MeasurementBlocked(f"cold-start first reply timed out: {engine}")
                chunk = os.read(process.stdout.fileno(), 65536)
            except OSError as error:
                raise MeasurementBlocked(f"cannot read cold-start reply: {engine}: {error}") from error
            if not chunk:
                raise MeasurementBlocked(f"cold-start adapter closed before first reply: {engine}")
            output.extend(chunk)
            if len(output) > 1048576:
                raise MeasurementBlocked("cold-start adapter reply exceeds 1 MiB")
        elapsed = time.monotonic_ns() - started
        if elapsed <= 0:
            raise MeasurementBlocked("nonpositive cold-start wall duration")
        try:
            remainder, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired as error:
            raise MeasurementBlocked(f"cold-start adapter did not terminate: {engine}") from error
        try:
            decoded = (bytes(output) + remainder).decode("utf-8")
            diagnostics = stderr.decode("utf-8")
        except UnicodeDecodeError as error:
            raise MeasurementBlocked("invalid UTF-8 cold-start adapter reply") from error
        done = subprocess.CompletedProcess(argv, process.returncode, decoded, diagnostics)
        if process.returncode != 0:
            raise MeasurementBlocked(
                f"cold-start adapter exit {process.returncode}: {diagnostics[-1000:]}")
        response = _decode_responses(done, [request], engine=engine)[0]
        _check_marker(done, marker, engine=engine)
        engine_ns = validate_reply(response, lane, expected_answer(
            lane["n"], lane["field"], lane["term"], lane["k"]))
        index_open_ns = response.get("index_open_ns")
        if (isinstance(index_open_ns, bool) or not isinstance(index_open_ns, int)
                or index_open_ns <= 0):
            raise MeasurementBlocked("cold-start adapter must report positive index_open_ns")
        if index_open_ns + engine_ns > elapsed:
            raise MeasurementBlocked(
                "cold-start index opening plus query exceeds launch-to-reply wall time")
        return elapsed, index_open_ns, engine_ns
    finally:
        if process.poll() is None:
            process.kill()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if process.stdout is not None and not process.stdout.closed:
            process.stdout.close()
        if process.stderr is not None and not process.stderr.closed:
            process.stderr.close()


def collect_slot(config: Mapping[str, Any], arm_id: str, lanes: Sequence[dict[str, Any]],
                 command: Sequence[str], indexes: Mapping[int, Path], *,
                 block: int, position: int, cpu: int | None) -> list[dict[str, Any]]:
    """Run an arm in one slot, verifying every warmup and measured query.

    Cold-start runs measure process launch to first response for their single
    declared lane, including index/reader open and JSONL transport. Warm runs
    keep one process per corpus/strategy group and use engine_ns only.
    """
    engine = config["arms"].get(arm_id, config["arms"][config["baseline"]])["engine"]
    policy = config["policy"]
    output: list[dict[str, Any]] = []
    # Group by corpus/cache regime/explicit experiment override. Production
    # by-top-k dispatch is performed within the engine for each requested K;
    # Quervant Q can share a session across K=10 and K=100.
    groups: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
    for lane in lanes:
        _, marker = _strategy(config, arm_id, lane)
        groups.setdefault((lane["n"], lane["cache_regime"], marker or "default"), []).append(lane)
    for (n, regime, _), group in groups.items():
        env, marker = _strategy(config, arm_id, group[0])
        for lane in group:
            if _strategy(config, arm_id, lane)[1] != marker:
                raise MeasurementBlocked("mixed strategy environments within one adapter session")
        if regime == "warm":
            requests: list[dict[str, Any]] = []
            for lane in group:
                for phase, count in (("warmup", policy["warmups"]), ("sample", policy["samples"])):
                    for i in range(count):
                        requests.append({"request_id": f"{lane['id']}:{phase}:{i}", "op": "query",
                                         "field": lane["field"], "term": lane["term"],
                                         "k": lane["k"], "mode": "warm"})
            done = _run_pinned([*command, "--index-dir", str(indexes[n])], cpu,
                               env=env, input_text="".join(json.dumps(req) + "\n" for req in requests), timeout=900)
            replies = _decode_responses(done, requests, engine=engine)
            _check_marker(done, marker, engine=engine)
            offset = 0
            for lane in group:
                expected = expected_answer(n, lane["field"], lane["term"], lane["k"])
                warmups = replies[offset:offset + policy["warmups"]]
                offset += policy["warmups"]
                samples = replies[offset:offset + policy["samples"]]
                offset += policy["samples"]
                for reply in warmups:
                    validate_reply(reply, lane, expected)
                values = [validate_reply(reply, lane, expected) for reply in samples]
                output.append({"block": block, "position": position, "arm_id": arm_id,
                               "lane_id": lane["id"], "warmups": len(warmups),
                               "samples_ns": values, "oracle_ok": True, "strategy_marker": marker})
        elif regime == "process-cold":
            if len(group) != 1 or len(lanes) != 1:
                raise MeasurementBlocked("cold-start study requires exactly one lane")
            for lane in group:
                wall_samples: list[int] = []
                open_samples: list[int] = []
                engine_samples: list[int] = []
                for i in range(policy["samples"]):
                    wall_ns, index_open_ns, engine_ns = collect_cold_start(
                        command, engine=engine, index_dir=indexes[n], lane=lane,
                        config=config, arm_id=arm_id, cpu=cpu,
                        request_id=f"{lane['id']}:cold:{block}:{position}:{i}")
                    wall_samples.append(wall_ns)
                    open_samples.append(index_open_ns)
                    engine_samples.append(engine_ns)
                output.append({"block": block, "position": position, "arm_id": arm_id,
                               "lane_id": lane["id"], "warmups": 0,
                               "samples_ns": wall_samples,
                               "index_open_samples_ns": open_samples,
                               "engine_samples_ns": engine_samples,
                               "other_overhead_samples_ns": [
                                   wall - opened - engine
                                   for wall, opened, engine
                                   in zip(wall_samples, open_samples, engine_samples)],
                               "timing_scope": "process launch through first complete JSONL reply",
                               "oracle_ok": True, "strategy_marker": marker})
        else:
            raise MeasurementBlocked("unrecognized cache regime")
    return output


def _control_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """A/A uses two identical implementations with distinct role labels."""
    baseline = config["baseline"]
    arm = config["arms"][baseline]
    control = dict(config)
    control["arms"] = {"AA": arm, "AA2": arm}
    control["baseline"] = "AA"
    control["source_arm"] = baseline
    control["policy"] = dict(config["policy"], control_arms=["AA2"])
    return control


def _phase(config: Mapping[str, Any], lanes: Sequence[dict[str, Any]],
           binaries: Mapping[str, list[str]], indexes: Mapping[str, Mapping[int, Path]],
           *, cpu: int | None, on_slot: Callable[[list[dict[str, Any]]], None]) -> list[dict[str, Any]]:
    arms = list(config["arms"])
    policy = config["policy"]
    rows = schedule(arms, blocks=policy["blocks"], slots_per_arm=policy["slots_per_arm"], seed=policy["seed"])
    captured: list[dict[str, Any]] = []
    for row in rows:
        arm_id = str(row["arm_id"])
        base = config.get("source_arm", config["baseline"]) if arm_id.startswith("AA") else arm_id
        new = collect_slot(config, arm_id, lanes, binaries[base], indexes[base],
                           block=int(row["block"]), position=int(row["position"]), cpu=cpu)
        captured.extend(new)
        on_slot(new)
    return captured


def _run_status(analysis: Mapping[str, Any]) -> str:
    outcomes = [c["status"] for lane in analysis.get("lanes", {}).values()
                for c in lane.get("comparisons", {}).values()]
    if not outcomes:
        return "INCONCLUSIVE"
    if any(x in ("FAIL", "NOT_COMPARABLE", "NON_COMPARABLE", "NOT_COMPUTABLE") for x in outcomes):
        return "INCONCLUSIVE"
    return "COMPLETE"


def run_benchmark(config_path: Path, result_dir: Path | None = None, *, root: Path,
                  scratch_root: Path | None = None,
                  programs: Mapping[str, list[str]] | None = None,
                  check_host: bool = True,
                  invoke_phase: Callable[..., list[dict[str, Any]]] | None = None,
                  index_builder: Callable[..., dict[str, Any]] | None = None) -> tuple[Path, dict[str, Any]]:
    """Automatically Prepare→Validate→Measure→Analyze→Save.

    Dependencies may be injected for bounded deterministic tests. Real execution
    uses compiled adapters. A failure publishes one INCOMPLETE result with
    collected samples and diagnostics rather than a separate evidence artifact.
    """
    config = load_configuration(config_path)
    validate_configuration(config)
    expected_results = result_directory(config_path)
    if result_dir is not None and Path(result_dir) != expected_results:
        raise ArtifactError(f"result directory must be {expected_results}")
    result_dir = expected_results
    lanes = lanes_for(config)
    run_id = str(uuid4())
    directory = scratch_root or root / "target" / "bm10"
    directory.mkdir(parents=True, exist_ok=True)
    scratch = directory / run_id
    scratch.mkdir(exist_ok=False)
    report: dict[str, Any] = {
        "schema": "benchmark-result-v1", "family": config["family"],
        "configuration_id": config["configuration_id"], "run_id": run_id,
        "executed_utc": now_utc(), "status": "INCOMPLETE", "configuration": config,
        "lanes": lanes, "raw_samples": [], "analysis": {}, "controls": {},
        "index_metrics": {}, "context": {}, "errors": [],
        "phase_durations_ns": {},
        "notes": "No historical performance comparison is implied.",
    }
    run_started = time.monotonic_ns()
    try:
        started = time.monotonic_ns()
        report["context"]["host"] = host_context(scratch, check=check_host)
        report["phase_durations_ns"]["host_preflight_ns"] = max(1, time.monotonic_ns() - started)
        report["context"]["source_revision"] = _git(root, "rev-parse", "HEAD") if programs is None else "MOCKED"
        host_cores = report["context"]["host"]["physical_core_candidates"] if check_host else []
        controller_cpu = host_cores[0][0] if host_cores else None
        adapter_cpu = host_cores[1][0] if len(host_cores) >= 2 else None
        report["context"]["controller_cpu"] = controller_cpu
        report["context"]["adapter_cpu"] = adapter_cpu
        readiness = config["policy"]["readiness"]

        def observe() -> dict[str, Any]:
            return assess_readiness(adapter_cpu, intervals=readiness["intervals"],
                                    interval_seconds=readiness["interval_ms"] / 1000,
                                    max_busy_percent=readiness["max_busy_percent"],
                                    max_steal_percent=readiness["max_steal_percent"])

        indexes: dict[str, dict[int, Path]] = {}
        if programs is None:
            # Production runs always use the same prepared input stage as the
            # standalone 'stage' command. A matching cache is verified and
            # reused; otherwise compile and index before A/A acquisition.
            from .preparation import stage_inputs
            prepared = stage_inputs(config_path, root=root, scratch_root=directory,
                                    check_host=check_host, cpu=adapter_cpu)
            binaries = prepared["programs"]
            indexes = prepared["indexes"]
            report["index_metrics"] = prepared["index_metrics"]
            report["context"]["build"] = prepared["build_info"]
            report["context"]["preparation"] = {
                "cache_status": prepared["state"], "cache_key": prepared["key"],
                "prepared_utc": prepared["prepared_utc"],
                "index_metrics_provenance": "preparation stage (not the current query window)",
                "verified_oracles": True,
            }
            if "readiness_index_pre" in prepared["host_checks"]:
                report["controls"]["readiness_index_pre"] = prepared["host_checks"]["readiness_index_pre"]
                report["controls"]["readiness_index_source"] = "preparation stage"
            report["phase_durations_ns"]["preparation_ns"] = prepared["total_ns"]
            report["phase_durations_ns"].update({
                "preparation_" + name: value for name, value
                in prepared["phase_durations_ns"].items()
            })
        else:
            # Explicit test seam: continue using mocked programs/index builders
            # without consulting real toolchains or persistent caches.
            binaries = dict(programs)
            report["context"]["build"] = {"mode": "INJECTED_TEST"}
            started = time.monotonic_ns()
            corpus_paths = {}
            for n in config["workload"]["sizes"]:
                corpus = scratch / f"keyword-n{n}.tsv"
                create_corpus(corpus, n)
                corpus_paths[n] = corpus
            report["phase_durations_ns"]["corpus_ns"] = max(1, time.monotonic_ns() - started)
            # Preserve targeted readiness/indexing boundary tests.
            if check_host:
                report["controls"]["readiness_index_pre"] = observe()
                if report["controls"]["readiness_index_pre"]["status"] != "clear":
                    raise MeasurementBlocked("host contention before indexing; index measurements invalid")
            started = time.monotonic_ns()
            for arm_id, arm in config["arms"].items():
                indexes[arm_id] = {}
                for n in config["workload"]["sizes"]:
                    target = scratch / "indexes" / arm_id / f"n{n}"
                    report["index_metrics"].setdefault(arm_id, {})[str(n)] = (index_builder or build_index)(
                        binaries[arm_id], engine=arm["engine"], corpus_path=corpus_paths[n],
                        target=target, n=n, cpu=adapter_cpu)
                    indexes[arm_id][n] = target
            report["phase_durations_ns"]["index_ns"] = max(1, time.monotonic_ns() - started)
        controller = invoke_phase or _phase
        control = _control_config(config)
        control_policy = control["policy"]
        with pinned_controller(controller_cpu):
            if check_host:
                report["controls"]["readiness_pre"] = observe()
                if report["controls"]["readiness_pre"]["status"] != "clear":
                    raise MeasurementBlocked("host contention before A/A; control invalid")
            started = time.monotonic_ns()
            control_raw = controller(control, lanes, binaries, indexes, cpu=adapter_cpu,
                                     on_slot=lambda rows: report["controls"].setdefault("raw_samples", []).extend(rows))
            report["phase_durations_ns"]["aa_acquisition_ns"] = max(1, time.monotonic_ns() - started)
            started = time.monotonic_ns()
            control_stats = analyze(control_raw, arms=list(control["arms"]), baseline="AA",
                                    lanes=lanes, policy=control_policy)
            report["phase_durations_ns"]["aa_analysis_ns"] = max(1, time.monotonic_ns() - started)
            report["controls"]["analysis"] = control_stats
            if any(c.get("status") != "PASS" for lane in control_stats["lanes"].values()
                   for c in lane["comparisons"].values()):
                raise MeasurementBlocked("A/A control is unstable; comparative acquisition is blocked")
            if check_host:
                report["controls"]["readiness_treatment"] = observe()
                if report["controls"]["readiness_treatment"]["status"] != "clear":
                    raise MeasurementBlocked("host contention before treatment; run invalid")
            started = time.monotonic_ns()
            observed = controller(config, lanes, binaries, indexes, cpu=adapter_cpu,
                                  on_slot=lambda rows: report["raw_samples"].extend(rows))
            report["phase_durations_ns"]["treatment_acquisition_ns"] = max(1, time.monotonic_ns() - started)
            started = time.monotonic_ns()
            report["analysis"] = analyze(observed, arms=list(config["arms"]),
                                         baseline=config["baseline"], lanes=lanes, policy=config["policy"])
            report["phase_durations_ns"]["treatment_analysis_ns"] = max(1, time.monotonic_ns() - started)
            if check_host:
                report["controls"]["readiness_post"] = observe()
                if report["controls"]["readiness_post"]["status"] != "clear":
                    raise MeasurementBlocked("host contention after treatment; preserve samples but invalidate run")
            if (config["family"] == "cross-engine"
                    and config["workload"]["regimes"] == ["warm"]
                    and invoke_phase is None):
                # Throughput is another timed phase: qualify it separately
                # from the already completed treatment search measurements.
                if check_host:
                    report["controls"]["readiness_throughput_pre"] = observe()
                    if report["controls"]["readiness_throughput_pre"]["status"] != "clear":
                        raise MeasurementBlocked("host contention before throughput; throughput invalid")
                metric = next((lane for lane in lanes if lane["n"] == 10000 and
                               lane["class"] == "medium" and lane["k"] == 10 and
                               lane["cache_regime"] == "warm"), None)
                if metric is None:
                    raise MeasurementBlocked("mandatory cross-engine throughput lane unavailable")
                report["throughput_metrics"] = {}
                started = time.monotonic_ns()
                for arm in config["arms"]:
                    report["throughput_metrics"][arm] = collect_throughput(
                        binaries[arm], engine=config["arms"][arm]["engine"],
                        index_dir=indexes[arm][10000],lane=metric,config=config,arm_id=arm,
                        cpu=adapter_cpu)
                report["phase_durations_ns"]["throughput_acquisition_ns"] = max(1, time.monotonic_ns() - started)
                if check_host:
                    report["controls"]["readiness_throughput_post"] = observe()
                    if report["controls"]["readiness_throughput_post"]["status"] != "clear":
                        raise MeasurementBlocked("host contention after throughput; preserve samples but invalidate run")
            report["status"] = _run_status(report["analysis"])
    except KeyboardInterrupt:
        # Operator interruption must not discard already captured measurements.
        report["errors"].append("interrupted by operator; partial observations preserved")
        report["status"] = "INCOMPLETE"
    except (ArtifactError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report["errors"].append(str(error)[:1500])
        report["status"] = "INCOMPLETE"
    finally:
        report["phase_durations_ns"]["run_before_save_ns"] = max(1, time.monotonic_ns() - run_started)
    saved = publish_result(config_path, result_dir, report)
    return saved, report
