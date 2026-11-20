"""Production PR15D preparation and acquisition through the frozen primitives.

Preparation is untimed.  Acquisition never calls the legacy ``run`` entry point,
which rebuilds adapters after controls: it calls the unchanged lane/trial
primitives with the previously hashed executables.  A forked, bounded worker
owns the adapter process group and CPU; the controller owns a different CPU.
No public option injects samples, a readiness provider, or a backend.
"""

from __future__ import annotations

import contextlib
import importlib.util
import multiprocessing
import os
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import canonical_document_bytes, canonical_payload_bytes, content_digest
from ..config.errors import (
    BM_ACQUISITION_PROHIBITED, BM_EVIDENCE_UNAVAILABLE, BM_IDENTITY_INVALID,
    BM_PUBLICATION_CONFLICT, BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError,
)
from ..evidence.hashing import sha256_regular_file
from ..evidence.paths import require_safe_root
from ..evidence.provenance import repository_root, require_clean_head
from ..host.capabilities import LinuxCapabilityProvider, collect_host_capabilities
from ..host.readiness import ReadinessLimits
from .admission import _adapter_source_digest, pr15d_warm_lane_ids
from .acquisition import _finish_owned_worker, _run_owned_preparation, sanitized_environment
from .authorization import VerifiedOfficialAuthorization, require_verified_official_authorization
from .controls import (
    HostObservation, assess_cross_engine_control, assess_readiness, collect_real_readiness, require_control_pass,
    validate_readiness_record,
)
from .protocols import STUDY_CROSS_ENGINE, host_environment_matches, read_canonical_json, template_path, validate_template

PREPARED_NAME = "prepared-cross-engine.json"
PREPARED_SCHEMA = "official-cross-engine-prepared-v1"
ENGINES = ("quervant", "tantivy", "lucene")
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_FILES = 1024
_PREPARED_KEYS = frozenset({
    "schema", "source_sha", "source_root", "build_root", "corpus_dir",
    "adapter_source_digest", "binaries", "corpus_files", "corpus_manifest_digest",
    "adapter_metadata", "manifest_digest",
})


def _error(message: str, field: str = "prepared_manifest", code: str = BM_IDENTITY_INVALID) -> BenchError:
    return BenchError(code, message, field_path=field)


def _module(root: Path, relative: str) -> Any:
    if root.resolve() != repository_root().resolve():
        raise _error("the configured source must be the executing checkout", "source_root")
    path = root / relative
    spec = importlib.util.spec_from_file_location("official_" + path.stem, path)
    if spec is None or spec.loader is None:
        raise _error("the frozen backend module is unavailable", code=BM_EVIDENCE_UNAVAILABLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy(root: Path) -> Any:
    return _module(root, "benchmarks/pr15d/harness/run.py")


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_document_bytes(dict(value))
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _fresh(path: Path) -> Path:
    require_safe_root(path.parent)
    if os.path.lexists(path):
        raise _error("the owned output already exists; no retry or overwrite is permitted", "output_path", BM_PUBLICATION_CONFLICT)
    path.mkdir(mode=0o700)
    return require_safe_root(path)


def _head(root: Path) -> str:
    require_clean_head(root)
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, check=False, timeout=30)
    if result.returncode:
        raise _error("the clean source commit cannot be observed", "source_commit", BM_EVIDENCE_UNAVAILABLE)
    return result.stdout.decode("ascii").strip()


def _files(root: Path, paths: list[Path]) -> list[dict[str, Any]]:
    if not paths or len(paths) > MAX_FILES:
        raise _error("the prepared runtime member count is outside its bounds", code=BM_UNSAFE_INPUT)
    records = []
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        digest, length = sha256_regular_file(root, relative, max_bytes=MAX_FILE_BYTES)
        records.append({"path": relative, "size_bytes": length, "sha256": digest})
    return records


def _runtime_files(root: Path, engine: str, binary: Path) -> list[Path]:
    if engine != "lucene":
        return [binary]
    distribution = binary.parent.parent
    files = []
    for current, directories, names in os.walk(distribution, followlinks=False):
        for name in directories + names:
            path = Path(current) / name
            if path.is_symlink():
                raise _error("prepared runtime links are prohibited", code=BM_UNSAFE_INPUT)
        files.extend(Path(current) / name for name in names)
    if not any(path.suffix == ".jar" for path in files):
        raise _error("the Lucene installation has no runtime jars", code=BM_EVIDENCE_UNAVAILABLE)
    return files


def _binary_records(legacy: Any, build_root: Path) -> dict[str, Any]:
    records = {}
    for engine in ENGINES:
        binary = Path(legacy.adapter_binary(engine, str(build_root)))
        if not os.access(binary, os.X_OK):
            raise _error(f"{engine} entry point is not executable", code=BM_EVIDENCE_UNAVAILABLE)
        records[engine] = {
            "entrypoint": binary.relative_to(build_root).as_posix(),
            "files": _files(build_root, _runtime_files(build_root, engine, binary)),
        }
    return records


def _binary_digest(records: Mapping[str, Any]) -> str:
    return content_digest({"kind": "official-cross-engine-binaries", "schema_version": 1, "engines": dict(records)})


@dataclass(frozen=True)
class PreparedCrossEngine:
    manifest_path: Path
    source_root: Path
    build_root: Path
    corpus_dir: Path
    binaries: Mapping[str, Path]
    metadata: Mapping[str, Any]
    manifest: Mapping[str, Any]
    binary_digest: str
    corpus_digest: str


def prepare_cross_engine(*, root: Path, build_root: Path, corpus_dir: Path) -> PreparedCrossEngine:
    """Prepare once under the frozen timeout, then rehash the worker's files."""
    root = require_safe_root(Path(root)).resolve()
    build_root, corpus_dir = Path(build_root).absolute(), Path(corpus_dir).absolute()
    _head(root)
    _run_owned_preparation(study_id=STUDY_CROSS_ENGINE, root=root, build_root=build_root, corpus_dir=corpus_dir)
    return load_prepared(build_root / PREPARED_NAME, root=root)


def _prepare_cross_engine_body(*, root: Path, build_root: Path, corpus_dir: Path) -> PreparedCrossEngine:
    """Build pinned adapters and execute the existing untimed two-size smoke.

    Existing corpus bytes are verified, never regenerated. A missing corpus is
    generated once into a fresh directory by the unchanged deterministic source.
    All preparation products exist before a G0 candidate can bind their hashes.
    """
    root = require_safe_root(Path(root)).resolve()
    build_root = Path(build_root).absolute()
    corpus_dir = Path(corpus_dir).absolute()
    source = _head(root)
    legacy = _legacy(root)
    _fresh(build_root)
    _write(build_root / "preparation-state.json", {"status": "RUNNING", "source_sha": source})
    try:
        adapters = legacy.preflight_adapters()
        blockers = legacy.preflight_blockers(adapters)
        if blockers:
            raise _error(f"pinned adapter prerequisites are unavailable: {blockers}", "adapters", BM_EVIDENCE_UNAVAILABLE)
        if not corpus_dir.exists():
            _fresh(corpus_dir)
            _module(root, "benchmarks/pr15d/corpus/generate.py").generate(str(corpus_dir))
        require_safe_root(corpus_dir)
        corpus, _rows = legacy.oracle.load_and_verify(str(corpus_dir))
        builds = legacy.build_adapters(str(build_root))
        _write(build_root / "build-receipts.json", builds)
        metadata = {engine: legacy.read_adapter_metadata(engine, builds[engine]["binary"]) for engine in ENGINES}
        # This is the existing correctness-only smoke, not a performance run.
        command = [sys.executable, str(root / "benchmarks/pr15d/harness/smoke.py"),
                   "--corpus", str(corpus_dir), "--quervant-bin", builds["quervant"]["binary"],
                   "--tantivy-bin", builds["tantivy"]["binary"], "--lucene-command",
                   __import__("shlex").quote(builds["lucene"]["binary"]), "--sizes", "10000,100000"]
        with (build_root / "smoke.stdout.log").open("xb") as out, (build_root / "smoke.stderr.log").open("xb") as err:
            result = subprocess.run(command, cwd=root, stdout=out, stderr=err, check=False, timeout=1800)
        _write(build_root / "smoke-receipt.json", {"argv": command, "exit_code": result.returncode, "sizes": [10000, 100000]})
        if result.returncode:
            raise _error("the existing full-size adapter correctness smoke failed", "correctness", BM_ACQUISITION_PROHIBITED)
        if _head(root) != source:
            raise _error("source changed during preparation", "source_commit")
        document = {
            "schema": PREPARED_SCHEMA, "source_sha": source, "source_root": str(root),
            "build_root": str(build_root), "corpus_dir": str(corpus_dir),
            "adapter_source_digest": _adapter_source_digest(root),
            "binaries": _binary_records(legacy, build_root), "adapter_metadata": metadata,
            "corpus_files": _files(corpus_dir, [corpus_dir / legacy.oracle.manifest_filename(),
                *(corpus_dir / legacy.oracle.corpus_filename(n) for n in legacy.N_VALUES)]),
            "corpus_manifest_digest": "sha256:" + legacy.oracle.sha256_bytes(legacy.oracle.canonical_json_bytes(corpus)),
        }
        document["manifest_digest"] = content_digest(document)
        _write(build_root / PREPARED_NAME, document)
        prepared = load_prepared(build_root / PREPARED_NAME, root=root)
        _write(build_root / "preparation-state.json", {"status": "COMPLETE", "manifest_digest": document["manifest_digest"]})
        return prepared
    except BaseException as exc:
        _write(build_root / "preparation-state.json", {"status": "STOPPED_PRESERVED", "error": str(exc)})
        raise


def load_prepared(manifest_path: Path, *, root: Path) -> PreparedCrossEngine:
    """Rehash the real executables, Lucene jars, corpus and pinned source inputs."""
    root = require_safe_root(Path(root)).resolve()
    path = Path(manifest_path).absolute()
    document = read_canonical_json(path)
    if set(document) != _PREPARED_KEYS or document.get("schema") != PREPARED_SCHEMA:
        raise _error("the prepared manifest has an unknown shape", code=BM_SCHEMA_INVALID)
    unsigned = {key: value for key, value in document.items() if key != "manifest_digest"}
    if content_digest(unsigned) != document["manifest_digest"]:
        raise _error("the prepared manifest digest changed")
    build_root = require_safe_root(Path(document["build_root"]))
    corpus_dir = require_safe_root(Path(document["corpus_dir"]))
    if path != build_root / PREPARED_NAME or document["source_root"] != str(root):
        raise _error("the prepared manifest root binding differs")
    if document["source_sha"] != _head(root) or document["adapter_source_digest"] != _adapter_source_digest(root):
        raise _error("prepared source bytes differ from the executing checkout", "source_commit")
    legacy = _legacy(root)
    binaries = _binary_records(legacy, build_root)
    if canonical_payload_bytes(binaries) != canonical_payload_bytes(document["binaries"]):
        raise _error("an executable or runtime file changed", "binary_manifest_digest")
    corpus, _rows = legacy.oracle.load_and_verify(str(corpus_dir))
    actual_files = _files(corpus_dir, [corpus_dir / legacy.oracle.manifest_filename(),
        *(corpus_dir / legacy.oracle.corpus_filename(n) for n in legacy.N_VALUES)])
    digest = "sha256:" + legacy.oracle.sha256_bytes(legacy.oracle.canonical_json_bytes(corpus))
    if actual_files != document["corpus_files"] or digest != document["corpus_manifest_digest"]:
        raise _error("the corpus changed after preparation", "corpus_manifest_digest")
    if set(document["adapter_metadata"]) != set(ENGINES):
        raise _error("prepared metadata must cover all three engines")
    return PreparedCrossEngine(path, root, build_root, corpus_dir,
        {engine: build_root / binaries[engine]["entrypoint"] for engine in ENGINES},
        document["adapter_metadata"], document, _binary_digest(binaries), digest)


def verify_prepared(prepared: PreparedCrossEngine, *, root: Path) -> PreparedCrossEngine:
    if type(prepared) is not PreparedCrossEngine:
        raise _error("an actual prepared cross-engine record is required", code=BM_UNSAFE_INPUT)
    fresh = load_prepared(prepared.manifest_path, root=root)
    if (fresh != prepared or canonical_payload_bytes(dict(fresh.manifest)) != canonical_payload_bytes(dict(prepared.manifest))
            or canonical_payload_bytes(dict(fresh.metadata)) != canonical_payload_bytes(dict(prepared.metadata))):
        raise _error("the supplied prepared record differs from its persisted authority")
    return fresh


def _template(root: Path, *, version: int = 1, design_digest: str | None = None) -> dict[str, Any]:
    template = validate_template(read_canonical_json(template_path(STUDY_CROSS_ENGINE, root, version=version)))
    if design_digest is not None and content_digest(template) != design_digest:
        raise _error("selected control template differs from G0", "design_digest")
    return template


def _authorize(authorization: VerifiedOfficialAuthorization, prepared: PreparedCrossEngine,
               root: Path, observed: Mapping[str, Any]) -> tuple[Any, PreparedCrossEngine]:
    freeze = require_verified_official_authorization(authorization, study_id=STUDY_CROSS_ENGINE,
                                                    for_production=True, observed=observed)
    fresh = verify_prepared(prepared, root=root)
    if (fresh.binary_digest != freeze.binary_manifest_digest or fresh.corpus_digest != freeze.corpus_manifest_digest
            or fresh.manifest["source_sha"] != freeze.source_commit
            or fresh.manifest["adapter_source_digest"] != freeze.adapter_source_manifest_digest):
        raise _error("prepared execution inputs differ from the G0 authorization", "prepared_manifest")
    return freeze, fresh


def _verify_cpu_pair(freeze: Any, adapter_cpu: int, controller_cpu: int, *, template: Mapping[str, Any]) -> None:
    capabilities = collect_host_capabilities(LinuxCapabilityProvider())
    pair = (adapter_cpu, controller_cpu)
    if (any(type(cpu) is not int for cpu in pair) or pair[0] == pair[1]
            or not host_environment_matches(template["host_requirements"]["environment"], capabilities["environment"])
            or capabilities["missing_fields"]
            or any(cpu not in capabilities["allowed_cpus"] for cpu in pair)):
        raise _error("the actual host/CPU pair cannot satisfy the frozen host contract", "cpu_pair", BM_UNSAFE_INPUT)
    topology = {row["cpu"]: (row["package_id"], row["core_id"]) for row in capabilities["cpu_topology"]}
    if topology[pair[0]] == topology[pair[1]]:
        raise _error("the selected CPUs share a physical core", "cpu_pair", BM_UNSAFE_INPUT)
    observed = {"kind": "official-host-preflight", "schema_version": 1,
                "capabilities": capabilities, "adapter_cpu": adapter_cpu, "controller_cpu": controller_cpu}
    if content_digest(observed) != freeze.host_preflight_digest:
        raise _error("the actual host/CPU pair differs from G0", "host_preflight_digest")


def _readiness(root: Path, output: Path, adapter_cpu: int, controller_cpu: int,
               *, template: Mapping[str, Any] | None = None) -> dict[str, Any]:
    host = (_template(root) if template is None else validate_template(template))["host_requirements"]
    fields = ("min_interval_ms", "max_interval_ms", "max_busy_permille",
              "max_median_busy_permille", "max_steal_permille", "min_intervals")
    record = collect_real_readiness(study_id=STUDY_CROSS_ENGINE, adapter_cpu=adapter_cpu,
        controller_cpu=controller_cpu, limits=ReadinessLimits(**{name: host[name] for name in fields}),
        intervals=host["min_intervals"], interval_ms=1000)
    _write(output, record)
    if (record["status"] != "READY"
            or not host_environment_matches(host["environment"], record["environment"])):
        raise _error("the frozen real readiness gate is not clear; no retry", "readiness", BM_ACQUISITION_PROHIBITED)
    return record


@contextlib.contextmanager
def _controller_affinity(adapter_cpu: int, controller_cpu: int):
    if any(isinstance(cpu, bool) or not isinstance(cpu, int) for cpu in (adapter_cpu, controller_cpu)):
        raise _error("CPU identifiers must be integers", "cpu_pair", BM_UNSAFE_INPUT)
    if not hasattr(os, "sched_getaffinity") or not hasattr(os, "sched_setaffinity"):
        raise _error("native process affinity is unavailable", "cpu_pair", BM_EVIDENCE_UNAVAILABLE)
    previous = os.sched_getaffinity(0)
    if adapter_cpu == controller_cpu or not {adapter_cpu, controller_cpu} <= previous:
        raise _error("the selected CPU pair is not distinct and available", "cpu_pair", BM_UNSAFE_INPUT)
    try:
        os.sched_setaffinity(0, {controller_cpu})
        if os.sched_getaffinity(0) != {controller_cpu}:
            raise _error("controller affinity did not take effect", "cpu_pair")
        yield
    finally:
        os.sched_setaffinity(0, previous)


def _worker_entry(root: Path, request: dict[str, Any], output: Path, cpu: int) -> None:
    """Private fork target; reachable from the authorized controller only."""
    os.setsid()
    environment = sanitized_environment()
    os.environ.clear()
    os.environ.update(environment)
    with (output.parent / "worker.stdout.log").open("xb") as out, (output.parent / "worker.stderr.log").open("xb") as err:
        os.dup2(out.fileno(), 1)
        os.dup2(err.fileno(), 2)
        try:
            os.sched_setaffinity(0, {cpu})
            if os.sched_getaffinity(0) != {cpu}:
                raise _error("adapter worker affinity did not take effect", "cpu_pair")
            legacy = _legacy(root)
            prepared = load_prepared(Path(request["prepared_manifest"]), root=root)
            engine = "quervant" if request["kind"] == "control" else request["engine"]
            actual_metadata = legacy.read_adapter_metadata(engine, str(prepared.binaries[engine]))
            if canonical_payload_bytes(actual_metadata) != canonical_payload_bytes(dict(prepared.metadata[engine])):
                raise _error("adapter metadata changed after preparation", "adapter_metadata")
            corpus, rows = legacy.oracle.load_and_verify(str(prepared.corpus_dir))
            if request["kind"] == "control":
                slot = {key: request[key] for key in ("slot", "block", "position", "arm")}
                slot.update({"engine": "quervant", "lanes": [], "adapter_cpu": cpu})
                _write(output, slot)
                for n in legacy.N_VALUES:
                    index = output.parent / "indexes" / str(n)
                    if index.exists():
                        raise _error("control index output already exists", "output_path", BM_PUBLICATION_CONFLICT)
                    legacy.build_index("quervant", str(prepared.binaries["quervant"]),
                        str(prepared.corpus_dir / legacy.oracle.corpus_filename(n)), str(index), n)
                    for lane in legacy.lane_descriptors():
                        if lane["n"] != n or lane["regime"] != "warm":
                            continue
                        expected = legacy.oracle.expected(rows[n], lane["field"], lane["term"], lane["k"])
                        measured = legacy.measure_lane("quervant", str(prepared.binaries["quervant"]),
                            str(index), lane, expected, dict(prepared.metadata["quervant"]),
                            {"pre": "clear", "post": None})
                        measured["lane_id"] = lane["id"]
                        slot["lanes"].append(measured)
                        _write(output, slot)
            elif request["kind"] == "treatment":
                trial = legacy.measure_engine_trial(engine=request["engine"], trial=request["trial"],
                    source=request["source"], fingerprint=request["fingerprint"], environment=request["environment"],
                    manifest=corpus, rows_by_n=rows, corpus_dir=str(prepared.corpus_dir), out_dir=request["backend_root"],
                    binary=str(prepared.binaries[request["engine"]]), adapter_metadata=dict(prepared.metadata[request["engine"]]),
                    allow_contended=False)
                _write(output, trial)
            else:
                raise _error("unknown internal acquisition operation", code=BM_UNSAFE_INPUT)
        except BaseException:
            traceback.print_exc()
            raise


def _run_worker(root: Path, request: dict[str, Any], output: Path, adapter_cpu: int,
                controller_cpu: int, timeout: float) -> None:
    if timeout <= 0:
        raise _error("the frozen backend deadline elapsed", "timeout", BM_ACQUISITION_PROHIBITED)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write(output.parent / "worker-request.json", request)
    started = time.time_ns()
    process = multiprocessing.get_context("fork").Process(target=_worker_entry, args=(root, request, output, adapter_cpu))
    timed_out = False
    completed = False
    try:
        with _controller_affinity(adapter_cpu, controller_cpu):
            process.start()
            process.join(timeout)
            if process.is_alive():
                timed_out = True
                raise _error("the frozen backend deadline elapsed", "timeout", BM_ACQUISITION_PROHIBITED)
            completed = process.exitcode == 0
    finally:
        try:
            _finish_owned_worker(process)
        finally:
            _write(output.parent / "worker-receipt.json", {"kind": request["kind"], "start_time_ns": started,
                "end_time_ns": time.time_ns(), "exit_code": process.exitcode, "timeout": timed_out,
                "status": "COMPLETE" if completed else "STOPPED_PRESERVED", "retry_allowed": False,
                "adapter_cpu": adapter_cpu, "controller_cpu": controller_cpu})
    if process.exitcode != 0:
        raise _error("the actual adapter worker failed; partial outputs are preserved", "backend", BM_ACQUISITION_PROHIBITED)


def acquire_cross_engine_control(authorization: VerifiedOfficialAuthorization, *, root: Path,
    raw_root: Path, prepared: PreparedCrossEngine, observed: Mapping[str, Any],
    adapter_cpu: int, controller_cpu: int) -> dict[str, Any]:
    """Execute the frozen 12×4 same-Quervant control; preserve every slot."""
    freeze, prepared = _authorize(authorization, prepared, root, observed)
    template = _template(root, version=freeze.profile_version, design_digest=freeze.design_digest)
    _verify_cpu_pair(freeze, adapter_cpu, controller_cpu, template=template)
    raw = require_safe_root(raw_root)
    control = _fresh(raw / "control")
    deadline = time.monotonic() + template["stopping"]["backend_timeout_seconds"]
    _write(control / "execution.json", {"status": "RUNNING", "run_id": freeze.run_id})
    try:
        slots = []
        for block, order in enumerate(template["schedule"]["control_order"], 1):
            for position, arm in enumerate(order, 1):
                number = (block - 1) * 4 + position
                directory = control / "slots" / f"slot-{number:02d}"
                directory.mkdir(parents=True)
                _authorize(authorization, prepared, root, observed)
                _readiness(root, directory / "readiness-pre.json", adapter_cpu, controller_cpu, template=template)
                request = {"kind": "control", "prepared_manifest": str(prepared.manifest_path),
                           "slot": number, "block": block, "position": position, "arm": arm}
                _run_worker(root, request, directory / "slot.json", adapter_cpu, controller_cpu, deadline - time.monotonic())
                _readiness(root, directory / "readiness-post.json", adapter_cpu, controller_cpu, template=template)
                slot = read_canonical_json(directory / "slot.json")
                for lane in slot["lanes"]:
                    lane["contention"]["post"] = "clear"
                _write(directory / "slot.json", slot)
                slots.append(slot)
        assessment = assess_cross_engine_control(slots=slots, warm_lane_ids=pr15d_warm_lane_ids())
        _write(control / "control.json", assessment)
        verify_cross_engine_control(raw_root=raw, prepared=prepared, root=root, template=template)
        _write(control / "execution.json", {"status": "COMPLETE", "run_id": freeze.run_id})
        require_control_pass(assessment)
        return assessment
    except BaseException as exc:
        _write(control / "execution.json", {"status": "STOPPED_PRESERVED", "run_id": freeze.run_id, "error": str(exc)})
        raise


def verify_cross_engine_control(*, raw_root: Path, prepared: PreparedCrossEngine, root: Path,
                                template: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Rederive control assessment and exact answers from persisted raw slots."""
    prepared = verify_prepared(prepared, root=root)
    selected = _template(root) if template is None else validate_template(template)
    return _verify_persisted_cross_engine_control(raw_root=raw_root, corpus_dir=prepared.corpus_dir,
                                                root=root, template=selected)


def _verify_persisted_cross_engine_control(*, raw_root: Path, corpus_dir: Path,
                                         root: Path, template: Mapping[str, Any]) -> dict[str, Any]:
    """Data-only control/oracle checks after live or offline input authentication."""
    template = validate_template(template)
    registered = _template(root, version=template["schema_version"])
    if template["study_id"] != STUDY_CROSS_ENGINE or canonical_payload_bytes(template) != canonical_payload_bytes(registered):
        raise _error("persisted control template is not the registered design", "design_digest")
    legacy = _legacy(root)
    _corpus, rows = legacy.oracle.load_and_verify(str(corpus_dir))
    control = require_safe_root(Path(raw_root) / "control")
    expected_names = {f"slot-{i:02d}" for i in range(1, 49)}
    if {path.name for path in (control / "slots").iterdir()} != expected_names:
        raise _error("control slots do not match the frozen 48-slot set", "slots")
    slots = []
    warm = [lane for lane in legacy.lane_descriptors() if lane["regime"] == "warm"]
    host = template["host_requirements"]
    limit_fields = ("min_interval_ms", "max_interval_ms", "max_busy_permille",
                    "max_median_busy_permille", "max_steal_permille", "min_intervals")
    frozen_limits = {key: host[key] for key in limit_fields}
    host_identity = None
    for number in range(1, 49):
        directory = control / "slots" / f"slot-{number:02d}"
        slot = read_canonical_json(directory / "slot.json")
        block, position = divmod(number - 1, 4)
        if any(slot.get(key) != value for key, value in {
            "slot": number, "block": block + 1, "position": position + 1,
            "arm": template["schedule"]["control_order"][block][position], "engine": "quervant",
        }.items()):
            raise _error("control slot identity differs from the frozen schedule", "slots")
        for side in ("pre", "post"):
            readiness = validate_readiness_record(read_canonical_json(directory / f"readiness-{side}.json"))
            observed_host = (readiness["environment"], readiness["host_fingerprint"], readiness["adapter_cpu"], readiness["controller_cpu"])
            if host_identity is None:
                host_identity = observed_host
            observations = [HostObservation(adapter_cpu=readiness["adapter_cpu"], controller_cpu=readiness["controller_cpu"],
                **{**row, "ticks": {key: tuple(value) for key, value in row["ticks"].items()}})
                for row in readiness["observations"]]
            if (readiness["status"] != "READY"
                    or not host_environment_matches(host["environment"], readiness["environment"])
                    or readiness["study_id"] != STUDY_CROSS_ENGINE or readiness["limits"] != frozen_limits
                    or slot.get("adapter_cpu") != readiness["adapter_cpu"] or observed_host != host_identity
                    or assess_readiness(limits=ReadinessLimits(**frozen_limits), observations=observations).status != "clear"):
                raise _error("a control slot has no passing live readiness record", "readiness")
        if len(slot.get("lanes", [])) != len(warm):
            raise _error("the control slot does not contain all sixteen warm lanes", "lanes")
        for recorded, lane in zip(slot["lanes"], warm):
            expected = legacy.oracle.expected(rows[lane["n"]], lane["field"], lane["term"], lane["k"])
            if any(recorded.get(key) != value for key, value in lane.items()):
                raise _error("a control lane differs from the frozen descriptor", "lanes")
            if (recorded.get("lane_id") != lane["id"] or recorded.get("warmups") != 5
                    or recorded.get("warmup_ids") != [f"{lane['id']}:warmup:{i}" for i in range(5)]
                    or recorded.get("oracle_ok") is not True or recorded.get("contention") != {"pre": "clear", "post": "clear"}
                    or recorded.get("doc_ids") != expected["doc_ids"] or recorded.get("total_hits") != expected["total_hits"]
                    or recorded.get("expected_doc_ids") != expected["doc_ids"] or recorded.get("expected_total_hits") != expected["total_hits"]):
                raise _error("a control lane's correctness/warmup evidence differs", "lanes")
            samples = recorded.get("samples_ns")
            if not isinstance(samples, list) or len(samples) != 20 or any(type(value) is not int or value <= 0 for value in samples):
                raise _error("control samples are not twenty positive integers", "samples_ns")
            if recorded.get("summary_ns") != legacy.summarize(samples):
                raise _error("control summary differs from its raw samples", "summary_ns")
        slots.append(slot)
    assessment = assess_cross_engine_control(slots=slots, warm_lane_ids=pr15d_warm_lane_ids())
    stored = read_canonical_json(control / "control.json")
    if canonical_payload_bytes(assessment) != canonical_payload_bytes(stored):
        raise _error("control assessment differs from the persisted raw slots", "control")
    return assessment


def acquire_cross_engine_treatment(authorization: VerifiedOfficialAuthorization, *, root: Path,
    raw_root: Path, prepared: PreparedCrossEngine, observed: Mapping[str, Any],
    adapter_cpu: int, controller_cpu: int) -> Path:
    """Execute all nine original trial primitives using G0-bound binaries."""
    freeze, prepared = _authorize(authorization, prepared, root, observed)
    template = _template(root, version=freeze.profile_version, design_digest=freeze.design_digest)
    _verify_cpu_pair(freeze, adapter_cpu, controller_cpu, template=template)
    require_control_pass(verify_cross_engine_control(raw_root=raw_root, prepared=prepared, root=root, template=template))
    backend = _fresh(require_safe_root(raw_root) / "backend")
    legacy = _legacy(root)
    environment = legacy.collect_environment(str(backend))
    if not environment["native_filesystem"]:
        raise _error("PR15D requires its frozen native filesystem", "filesystem", BM_ACQUISITION_PROHIBITED)
    fingerprint = legacy.host_fingerprint(environment)
    corpus, _rows = legacy.oracle.load_and_verify(str(prepared.corpus_dir))
    adapters = legacy.preflight_adapters()
    # The frozen availability record has paths/blockers but no engine_version.
    # Gate A also requires an observed pin in this map. Bind that additional
    # field to preparation's actual metadata response, never a configured pin.
    adapters = {engine: {**adapters[engine], "engine_version": prepared.metadata[engine]["engine_version"]}
                for engine in ENGINES}
    record = {"schema": legacy.SCHEMA_RUN, "run_id": backend.name, "source_sha": freeze.source_commit,
        "workload": legacy.WORKLOAD, "corpus_dir": str(prepared.corpus_dir),
        "corpus_manifest_sha256": prepared.corpus_digest.removeprefix("sha256:"),
        "corpus_digests": {str(entry["n"]): entry["sha256"] for entry in corpus["corpora"]},
        "environment": environment, "host_fingerprint": fingerprint,
        "adapters": adapters, "adapter_metadata": dict(prepared.metadata),
        "idle_attested": True, "native_filesystem": True, "filesystem": environment["filesystem"],
        "trials": 3, "status": "running", "qualified": False, "blockers": [],
        "scored_lane": {"status": "SEMANTICALLY_NONCOMPARABLE", "reason": "no verified cross-engine BM25 k1/b/length/tie contract"}}
    _write(backend / "run.json", record)
    deadline = time.monotonic() + template["stopping"]["backend_timeout_seconds"]
    try:
        for trial in range(1, 4):
            for engine in legacy.TRIAL_ORDER[trial]:
                _authorize(authorization, prepared, root, observed)
                receipt_dir = backend / "official-receipts" / f"trial-{trial}" / engine
                receipt_dir.mkdir(parents=True)
                _readiness(root, receipt_dir / "readiness-pre.json", adapter_cpu, controller_cpu, template=template)
                request = {"kind": "treatment", "prepared_manifest": str(prepared.manifest_path),
                    "engine": engine, "trial": trial, "source": freeze.source_commit, "fingerprint": fingerprint,
                    "environment": environment, "backend_root": str(backend)}
                _run_worker(root, request, receipt_dir / "trial.json", adapter_cpu, controller_cpu, deadline - time.monotonic())
                _readiness(root, receipt_dir / "readiness-post.json", adapter_cpu, controller_cpu, template=template)
                measured = read_canonical_json(receipt_dir / "trial.json")
                _write(backend / "trials" / f"trial-{trial}" / f"{engine}.json", measured)
                if measured.get("qualified") is not True:
                    raise _error("the original trial primitive reported an unqualified trial", "backend", BM_ACQUISITION_PROHIBITED)
        record.update(status="complete", qualified=True)
        _write(backend / "run.json", record)
        report = _module(root, "benchmarks/pr15d/harness/validate.py").validate_run(str(backend))
        _write(backend / "validation.json", report)
        if report.get("status") != "QUALIFIED":
            raise _error("the original PR15D validator rejected the measured series", "backend", BM_ACQUISITION_PROHIBITED)
        _authorize(authorization, prepared, root, observed)
        return backend
    except BaseException as exc:
        record.update(status="stopped", qualified=False)
        record["blockers"].append({"rule": "OFFICIAL_STOPPED_PRESERVED", "detail": str(exc)})
        _write(backend / "run.json", record)
        raise
