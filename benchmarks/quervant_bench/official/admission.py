"""Gate A: real raw-evidence admission for both official families.

Admission never trusts a legacy ``QUALIFIED``/``ACQUIRED_VERIFIED`` string. It
re-opens the complete measured series, checks the original backend's shape and
identities, verifies every lane answer against an independent oracle, re-runs the
original validator/verifier, and hashes a closed inventory before and after the
read. A mismatch anywhere is terminal for the attempt.
"""

from __future__ import annotations

import importlib.util
import os
from functools import lru_cache
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..config.codec import content_digest, decode_text, loads_json
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id
from ..evidence.hashing import sha256_regular_file
from ..evidence.paths import require_safe_root
from ..qualification.contracts import bound_payload, document_digest, require_closed, require_uint
from .controls import (
    assess_retained_key_control,
    control_digest,
    require_control_pass,
    validate_readiness_record,
)
from .authorization import (
    VerifiedOfficialAuthorization,
    require_verified_official_authorization,
)
from .protocols import (
    D3C_CAMPAIGN_NAMES,
    D3C_CONTROL_NAME,
    STUDY_CROSS_ENGINE,
    STUDY_RETAINED_KEY,
    OfficialFreeze,
    require_freeze,
)

MAX_RAW_MEMBER_BYTES = 64 * 1024 * 1024
MAX_RAW_MEMBERS = 8_192
MAX_RAW_TOTAL_BYTES = 512 * 1024 * 1024

PR15D_WORKLOAD = "pr15d_v1"
PR15D_ENGINES: tuple[str, ...] = ("quervant", "tantivy", "lucene")
PR15D_N_VALUES: tuple[int, ...] = (10_000, 100_000)
PR15D_CLASSES: tuple[str, ...] = ("absent", "rare", "medium", "common")
PR15D_K_VALUES: tuple[int, ...] = (10, 100)
PR15D_REGIMES: tuple[str, ...] = ("process_cold", "warm")
PR15D_WARMUPS = 5
PR15D_MEASURED = 20
PR15D_THROUGHPUT_REQUESTS = 100
PR15D_TRIALS = 3
PR15D_TRIAL_ORDER: dict[int, tuple[str, ...]] = {
    1: ("quervant", "tantivy", "lucene"),
    2: ("tantivy", "lucene", "quervant"),
    3: ("lucene", "quervant", "tantivy"),
}
PR15D_ADAPTER_SOURCE_FILES: dict[str, tuple[str, ...]] = {
    "quervant": ("Cargo.toml", "Cargo.lock", "src/main.rs"),
    "tantivy": ("Cargo.toml", "Cargo.lock", "src/main.rs"),
    "lucene": (
        "build.gradle",
        "settings.gradle",
        "gradlew",
        "gradlew.bat",
        "A1-CHECKSUMS.sha256",
        "gradle/wrapper/gradle-wrapper.properties",
        "gradle/wrapper/gradle-wrapper.jar",
        "src/main/java/org/quervant/bench/Adapter.java",
    ),
}
PR15D_ADAPTER_DIRS = {
    "quervant": "benchmarks/pr15d/adapters/quervant",
    "tantivy": "benchmarks/pr15d/adapters/tantivy",
    "lucene": "benchmarks/pr15d/adapters/lucene",
}

D3C_CLASSES: tuple[str, ...] = ("absent", "rare", "medium", "common")
D3C_N_VALUES: tuple[int, ...] = (10_000, 100_000)
D3C_K_VALUES: tuple[int, ...] = (1, 10, 32, 64, 100, 128, 256, 512, 1024)
D3C_BLOCKS = 12
D3C_SAMPLES = 20
D3C_WARMUPS = 5
D3C_MODE_MARKERS: dict[str, str | None] = {
    "A": None,
    "B": None,
    "L": "PR15I_D3C_MODE=v1:linear:none",
    "P": "PR15I_D3C_MODE=v1:prefilter:P2",
    "H": "PR15I_D3C_MODE=v1:exact_set:none",
}


def _identity(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def _schema(message: str, field: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field)


# ---------------------------------------------------------------------------
# Lane and oracle helpers (independent of official.analysis)
# ---------------------------------------------------------------------------


def pr15d_lane_id(n: int, class_name: str, k: int) -> str:
    return f"{PR15D_WORKLOAD}/{n}/{class_name}/k{k}"


def pr15d_lane_keys() -> list[tuple[int, str, int, str]]:
    return [
        (n, class_name, k, regime)
        for n in PR15D_N_VALUES
        for class_name in PR15D_CLASSES
        for k in PR15D_K_VALUES
        for regime in PR15D_REGIMES
    ]


def pr15d_warm_lane_ids() -> list[str]:
    return [
        pr15d_lane_id(n, class_name, k)
        for n in PR15D_N_VALUES
        for class_name in PR15D_CLASSES
        for k in PR15D_K_VALUES
    ]


def pr15d_lane_field(class_name: str) -> tuple[str, str]:
    from .protocols import PR15D_ENGINE_PINS  # noqa: F401  (documentation anchor)

    if class_name == "absent":
        return "key", "never"
    if class_name == "rare":
        return "key", "singleton"
    if class_name == "medium":
        return "group", "medium"
    return "key", "common"


def d3c_lane_keys() -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for n in D3C_N_VALUES:
        for class_name in D3C_CLASSES:
            field, term = pr15d_lane_field(class_name)
            for k in D3C_K_VALUES:
                lanes.append(
                    {
                        "lane_id": pr15d_lane_id(n, class_name, k),
                        "n": n,
                        "class": class_name,
                        "field": field,
                        "term": term,
                        "k": k,
                    }
                )
    return lanes


def d3c_lane_ids() -> list[str]:
    return [lane["lane_id"] for lane in d3c_lane_keys()]


def _retained_key_identifiers(n: int, class_name: str) -> tuple[str, ...]:
    if class_name == "absent":
        return ()
    if class_name == "rare":
        return ("d00000000",)
    if class_name == "medium":
        return tuple(f"d{index:08}" for index in range(0, n, 8))
    if class_name == "common":
        return tuple(f"d{index:08}" for index in range(2, n, 2))
    raise _identity("unknown retained-key class", "class")


@lru_cache(maxsize=None)
def _cached_identifiers(n: int, class_name: str) -> tuple[str, ...]:
    return _retained_key_identifiers(n, class_name)


def retained_key_oracle(n: int, class_name: str, k: int) -> dict[str, Any]:
    """Return the closed-form retained-key answer set (D3-C lane semantics)."""

    identifiers = _cached_identifiers(n, class_name)
    return {"total_hits": len(identifiers), "doc_ids": list(identifiers[:k])}


# ---------------------------------------------------------------------------
# Legacy module loading (read-only)
# ---------------------------------------------------------------------------


def _load_module(name: str, relative: str) -> Any:
    from ..evidence.provenance import repository_root

    path = repository_root() / relative
    if not path.is_file():
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "a required legacy backend module is unavailable",
            reference=relative,
        )
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise BenchError(BM_EVIDENCE_UNAVAILABLE, "a legacy backend module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_pr15d_validator() -> Any:
    return _load_module("official_pr15d_validate", "benchmarks/pr15d/harness/validate.py")


def load_pr15d_oracle() -> Any:
    return _load_module("official_pr15d_oracle", "benchmarks/pr15d/corpus/oracle.py")


# ---------------------------------------------------------------------------
# Safe raw-evidence inventory
# ---------------------------------------------------------------------------


def _reject_unsafe(path: Path) -> os.stat_result:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise BenchError(BM_UNSAFE_INPUT, "raw evidence must not contain symbolic links")
    if not stat.S_ISREG(info.st_mode):
        raise BenchError(BM_UNSAFE_INPUT, "raw evidence entries must be regular files")
    if info.st_nlink != 1:
        raise BenchError(BM_UNSAFE_INPUT, "raw evidence entries must not be hard links")
    return info


def walk_raw_members(
    root: Path,
    *,
    exclude_top_level: Sequence[str] = (),
    exclude_any_dir: Sequence[str] = (),
) -> list[str]:
    """Return the sorted relative member list beneath ``root`` (bounded)."""

    safe_root = require_safe_root(root)
    excluded_roots = set(exclude_top_level)
    excluded_dirs = set(exclude_any_dir)
    members: list[str] = []
    for current, dirnames, filenames in os.walk(safe_root, followlinks=False):
        current_path = Path(current)
        relative_dir = "" if current_path == safe_root else str(current_path.relative_to(safe_root))
        if relative_dir == "":
            dirnames[:] = sorted(name for name in dirnames if name not in excluded_roots)
        else:
            dirnames[:] = sorted(name for name in dirnames if name not in excluded_dirs)
        for name in sorted(dirnames):
            candidate = current_path / name
            if candidate.is_symlink():
                raise BenchError(
                    BM_UNSAFE_INPUT,
                    "raw evidence directories must not contain symbolic links",
                    reference=str(candidate.relative_to(safe_root)),
                )
        for name in sorted(filenames):
            candidate = current_path / name
            _reject_unsafe(candidate)
            relative = str(candidate.relative_to(safe_root)).replace(os.sep, "/")
            members.append(relative)
            if len(members) > MAX_RAW_MEMBERS:
                raise BenchError(BM_UNSAFE_INPUT, "raw evidence exceeds the member budget")
    return sorted(members)


def hash_raw_members(
    root: Path, members: Sequence[str]
) -> tuple[list[dict[str, Any]], int]:
    """Hash an explicit member set with bounded streaming reads."""

    safe_root = require_safe_root(root)
    records: list[dict[str, Any]] = []
    total = 0
    seen: set[str] = set()
    for relative in members:
        if relative in seen:
            raise _identity("raw evidence members must be unique", "members")
        seen.add(relative)
        digest, length = sha256_regular_file(safe_root, relative, max_bytes=MAX_RAW_MEMBER_BYTES)
        total += length
        if total > MAX_RAW_TOTAL_BYTES:
            raise BenchError(BM_UNSAFE_INPUT, "raw evidence exceeds the total byte budget")
        records.append({"path": relative, "byte_length": length, "digest": digest})
    records.sort(key=lambda entry: entry["path"])
    return records, total


def cross_engine_member_paths(raw_root: Path) -> list[str]:
    """Return the exact cross-engine evidence member list beneath ``raw_root``."""

    raw = require_safe_root(raw_root)
    control_members = walk_raw_members(
        raw, exclude_top_level=("backend",), exclude_any_dir=("indexes", "build")
    )
    backend_root = raw / "backend"
    backend_members = walk_raw_members(backend_root, exclude_any_dir=("indexes", "build"))
    return sorted(set(control_members) | {f"backend/{item}" for item in backend_members})


def retained_key_member_paths(raw_root: Path) -> list[str]:
    """Return the exact retained-key evidence member list beneath ``raw_root``."""

    raw = require_safe_root(raw_root)
    members: list[str] = []
    for campaign in (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES):
        directory = raw / campaign
        if not directory.is_dir():
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                f"the required campaign directory {campaign!r} is missing",
                field_path="campaigns",
            )
        members.extend(
            f"{campaign}/{item}"
            for item in walk_raw_members(
                directory, exclude_any_dir=("build", "indexes", "corpus", "compile-source")
            )
        )
    return sorted(members)


def cross_engine_inventory_digest(raw_root: Path) -> str:
    """Return the canonical inventory digest of a cross-engine raw root."""

    records, _total = hash_raw_members(raw_root, cross_engine_member_paths(raw_root))
    return inventory_digest(records)


def retained_key_inventory_digest(raw_root: Path) -> str:
    """Return the canonical inventory digest of a retained-key raw root."""

    records, _total = hash_raw_members(raw_root, retained_key_member_paths(raw_root))
    return inventory_digest(records)


def admitted_inventory_digest(admitted: Any) -> str:
    """Return the reference inventory digest for one admitted family."""

    if isinstance(admitted, AdmittedCrossEngine):
        return cross_engine_inventory_digest(admitted.raw_root)
    if isinstance(admitted, AdmittedRetainedKey):
        return retained_key_inventory_digest(admitted.raw_root)
    raise BenchError(BM_UNSAFE_INPUT, "admitted evidence has an unknown family")


def inventory_digest(members: Sequence[Mapping[str, Any]]) -> str:
    """Return the canonical digest of a sorted member inventory."""

    return content_digest(
        {
            "kind": "official-raw-inventory",
            "schema_version": 1,
            "members": [dict(member) for member in members],
        }
    )


def _read_json_member(root: Path, relative: str, *, label: str) -> tuple[dict[str, Any], str]:
    safe_root = require_safe_root(root)
    digest, _length = sha256_regular_file(safe_root, relative, max_bytes=MAX_RAW_MEMBER_BYTES)
    from ..evidence.paths import open_regular_beneath

    handle = open_regular_beneath(safe_root, relative)
    with handle:
        payload = handle.read(MAX_RAW_MEMBER_BYTES + 1)
    if len(payload) > MAX_RAW_MEMBER_BYTES:
        raise BenchError(BM_UNSAFE_INPUT, f"{label} exceeds the raw member budget")
    document = loads_json(decode_text(payload))
    if not isinstance(document, Mapping):
        raise _schema(f"{label} must be a JSON object", label)
    return dict(document), digest


# ---------------------------------------------------------------------------
# Original verifier gateways
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OriginalVerifierOutcome:
    """The observed outcome of the original backend verifier."""

    status: str
    detail: str
    report: Mapping[str, Any]


class OriginalVerifier:
    """Production gateway to the original legacy verifier (read-only).

    The default implementation launches the *unmodified* backend verifier in a
    bounded subprocess. Injection of an alternative gateway exists for
    deterministic unit tests only; the coordinator never injects one.
    """

    def verify_cross_engine(self, run_root: Path, *, corpus_dir: Path | None = None) -> OriginalVerifierOutcome:
        validator = load_pr15d_validator()
        report = dict(validator.validate_run(str(run_root)))
        return OriginalVerifierOutcome(
            status=str(report.get("status")),
            detail=f"{len(report.get('errors', []))} errors",
            report=report,
        )

    def verify_retained_key_campaign(self, campaign_dir: Path) -> OriginalVerifierOutcome:
        from ..evidence.provenance import repository_root

        verifier = repository_root() / "benchmarks/pr15i_d3_c/verify.py"
        completed = subprocess.run(
            [sys.executable, str(verifier), "--campaign-dir", str(campaign_dir)],
            capture_output=True,
            timeout=900,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            return OriginalVerifierOutcome(
                status="FAIL",
                detail=completed.stdout.decode("utf-8", errors="replace")[-512:],
                report={},
            )
        report = loads_json(completed.stdout.decode("utf-8"))
        return OriginalVerifierOutcome(
            status=str(report.get("measurement_status")),
            detail=str(report.get("verification")),
            report=dict(report),
        )

    def verify_retained_key_series(self, series_root: Path) -> OriginalVerifierOutcome:
        from ..evidence.provenance import repository_root

        verifier = repository_root() / "benchmarks/pr15i_d3_c/verify.py"
        completed = subprocess.run(
            [sys.executable, str(verifier), "--series-root", str(series_root)],
            capture_output=True,
            timeout=900,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            return OriginalVerifierOutcome(
                status="FAIL",
                detail=completed.stdout.decode("utf-8", errors="replace")[-512:],
                report={},
            )
        report = loads_json(completed.stdout.decode("utf-8"))
        return OriginalVerifierOutcome(
            status="PASS" if report.get("verification") == "PASS" else "FAIL",
            detail=str(report.get("full_series")),
            report=dict(report),
        )


# ---------------------------------------------------------------------------
# Cross-engine admission
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdmittedCrossEngine:
    """The complete, authenticated cross-engine raw series."""

    raw_root: Path
    corpus_dir: Path
    run_json: Mapping[str, Any]
    trials: Mapping[tuple[int, str], Mapping[str, Any]]
    validation: Mapping[str, Any]
    control: Mapping[str, Any]
    inventory: tuple[Mapping[str, Any], ...]
    raw_series_root_digest: str
    comparability_digest: str
    admission_index: Mapping[str, Any]
    original_verifier: Mapping[str, Any]
    fixture_only: bool = False
    fixture_only: bool = False

    def lane(self, trial: int, engine: str, key: tuple[int, str, int, str]) -> Mapping[str, Any]:
        """Return the exact raw lane record for one trial/engine/lane key."""

        manifest = self.trials[(trial, engine)]
        n, class_name, k, regime = key
        matches = [
            lane
            for lane in manifest["lanes"]
            if (lane.get("n"), lane.get("class"), lane.get("k"), lane.get("regime"))
            == (n, class_name, k, regime)
        ]
        if len(matches) != 1:
            raise _identity("the raw trial does not hold exactly one matching lane", "lanes")
        return matches[0]


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _identity(f"{field} must be a positive integer", field)
    return value


def _require_positive_number(value: object, field: str) -> float:
    """Accept a positive finite integer/float (the legacy rate is a float)."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _identity(f"{field} must be a positive number", field)
    if not value > 0 or value != value or value in (float("inf"), float("-inf")):
        raise _identity(f"{field} must be a positive finite number", field)
    return float(value)


def _require_plain_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _identity(f"{field} must be a non-negative integer", field)
    return value


def _verify_engine_pins(metadata: Mapping[str, Any]) -> None:
    from .protocols import PR15D_ENGINE_PINS

    for engine in PR15D_ENGINES:
        entry = metadata.get(engine)
        if not isinstance(entry, Mapping):
            raise _identity("the run does not record every engine's adapter metadata", "adapters")
        version = entry.get("engine_version")
        if not isinstance(version, str) or not version:
            raise _identity("an adapter engine version is missing", "engine_version")
        if engine == "tantivy" and "0.22.1" not in version:
            raise _identity("the Tantivy engine version is not the frozen 0.22.1", "engine_version")
        if engine == "lucene" and "9.12.3" not in version:
            raise _identity("the Lucene engine version is not the frozen 9.12.3", "engine_version")
        pin = PR15D_ENGINE_PINS[engine]
        if pin == "workspace":
            continue
        if pin.lstrip("=") not in version:  # pragma: no cover - covered above
            raise _identity("the adapter engine version is not pinned", "engine_version")


def _adapter_source_digest(root: Path) -> str:
    """Hash the exact pinned adapter source/lock file set."""

    records: list[dict[str, Any]] = []
    for engine in PR15D_ENGINES:
        base = PR15D_ADAPTER_DIRS[engine]
        for relative in PR15D_ADAPTER_SOURCE_FILES[engine]:
            path = f"{base}/{relative}"
            digest, length = sha256_regular_file(
                root, path, max_bytes=MAX_RAW_MEMBER_BYTES
            )
            records.append({"path": path, "digest": digest, "byte_length": length})
    return content_digest(
        {"kind": "official-adapter-source-manifest", "schema_version": 1, "files": records}
    )


def admit_cross_engine_real(
    *,
    raw_root: Path,
    authorization: VerifiedOfficialAuthorization,
    template: Mapping[str, Any],
    corpus_dir: Path,
    control_document: Mapping[str, Any],
    source_root: Path | None = None,
    observed: Mapping[str, Any] | None = None,
) -> AdmittedCrossEngine:
    """Gate A: authenticate the complete PR15D raw series (production entry point).

    The original verifier is instantiated internally and its source digest is
    checked against the verified G0 identity before it runs. A caller-supplied
    verifier is never accepted here.
    """

    freeze = require_verified_official_authorization(
        authorization,
        study_id=STUDY_CROSS_ENGINE,
        for_production=True,
        observed=observed,
    )
    return _admit_cross_engine_core(
        raw_root=raw_root,
        freeze=freeze,
        template=template,
        corpus_dir=corpus_dir,
        control_document=control_document,
        source_root=source_root,
        original_verifier=OriginalVerifier(),
        for_production=True,
    )


def _admit_cross_engine_core(
    *,
    raw_root: Path,
    freeze: OfficialFreeze,
    template: Mapping[str, Any],
    corpus_dir: Path,
    control_document: Mapping[str, Any],
    source_root: Path | None,
    original_verifier: Any,
    for_production: bool,
) -> AdmittedCrossEngine:
    """Internal Gate A derivation shared by production and fixture-only tests."""

    require_freeze(freeze, STUDY_CROSS_ENGINE)
    if template.get("study_id") != STUDY_CROSS_ENGINE:
        raise _identity("the template is for a different study", "study_id")
    raw = require_safe_root(Path(raw_root))
    corpus = require_safe_root(Path(corpus_dir))
    verifier = original_verifier

    require_control_pass(control_document)
    control = dict(control_document)
    if control.get("schema") != "official-cross-engine-control-assessment-v1":
        raise _schema("the control assessment schema is not the official schema", "schema")
    if control.get("slot_count") != 48:
        raise _identity("the control assessment must cover 48 slots", "slot_count")
    if [str(item) for item in control.get("lanes", [])] != pr15d_warm_lane_ids():
        raise _identity("the control lanes are not the sixteen warm lanes", "lanes")

    members_before = cross_engine_member_paths(raw)
    records_before, _total = hash_raw_members(raw, members_before)

    run_json, run_digest = _read_json_member(raw, "backend/run.json", label="run.json")
    if run_json.get("schema") != "pr15d-run-v1":
        raise _schema("run.json schema is not the frozen PR15D run schema", "schema")
    if run_json.get("status") != "complete" or run_json.get("qualified") is not True:
        raise _identity("the backend run is not complete and qualified", "status")
    if run_json.get("source_sha") != freeze.source_commit:
        raise _identity("the backend run source commit differs from the authorized source", "source_sha")
    if run_json.get("idle_attested") is not True:
        raise _identity("the backend run has no idle attestation", "idle_attested")
    if run_json.get("native_filesystem") is not True:
        raise _identity("the backend run did not use a native filesystem", "native_filesystem")
    if run_json.get("trials") != PR15D_TRIALS:
        raise _identity("the backend run trial count is not three", "trials")
    if source_root is not None:
        verify_authorized_source(Path(source_root), freeze)
    _verify_engine_pins(run_json.get("adapters") or {})
    _verify_engine_pins(run_json.get("adapter_metadata") or {})

    oracle = load_pr15d_oracle()
    manifest_document, rows_by_n = oracle.load_and_verify(str(corpus))
    corpus_manifest_sha = oracle.sha256_bytes(oracle.canonical_json_bytes(manifest_document))
    if run_json.get("corpus_manifest_sha256") != corpus_manifest_sha:
        raise _identity(
            "the corpus manifest digest differs from the measured run",
            "corpus_manifest_sha256",
        )
    if _digest_string(corpus_manifest_sha) != freeze.corpus_manifest_digest:
        raise _identity(
            "the observed corpus manifest digest differs from the authorized corpus",
            "corpus_manifest_digest",
        )
    expected_corpus_digests = {
        str(entry["n"]): entry["sha256"] for entry in manifest_document["corpora"]
    }
    if run_json.get("corpus_digests") != expected_corpus_digests:
        raise _identity("the per-corpus TSV digests differ from the measured run", "corpus_digests")

    trials: dict[tuple[int, str], dict[str, Any]] = {}
    for trial in range(1, PR15D_TRIALS + 1):
        for engine in PR15D_TRIAL_ORDER[trial]:
            relative = f"backend/trials/trial-{trial}/{engine}.json"
            manifest, _digest = _read_json_member(raw, relative, label=relative)
            _verify_cross_engine_trial(
                manifest,
                trial=trial,
                engine=engine,
                freeze=freeze,
                rows_by_n=rows_by_n,
                oracle=oracle,
                corpus_manifest_sha=corpus_manifest_sha,
                expected_corpus_digests=expected_corpus_digests,
                run_fingerprint=str(run_json.get("host_fingerprint") or ""),
            )
            trials[(trial, engine)] = manifest

    validation, _digest = _read_json_member(raw, "backend/validation.json", label="validation.json")
    if validation.get("schema") != "pr15d-validation-v1":
        raise _schema("validation.json schema is not the frozen validator schema", "schema")
    if validation.get("status") != "QUALIFIED":
        raise _identity("the original backend validator did not report QUALIFIED", "status")
    if validation.get("errors") or validation.get("unqualified"):
        raise _identity("the original backend validator reported findings", "status")

    outcome = verifier.verify_cross_engine(raw / "backend", corpus_dir=corpus)
    if outcome.status != "QUALIFIED":  # pragma: no cover - defensive duplication
        raise _identity("the original validator did not accept the raw series", "original-verifier")

    records_after, _total = hash_raw_members(raw, members_before)
    if records_after != records_before:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "raw evidence changed while it was being admitted",
            field_path="raw-series-root",
        )

    raw_series_root_digest = inventory_digest(records_before)
    comparability = content_digest(
        {
            "kind": "official-comparability",
            "schema_version": 1,
            "eligible_regime": "warm",
            "excluded_lane_classes": ["process_cold", "scored_bm25", "throughput"],
            "unit": "nanoseconds",
            "physical_sort_equivalence": "NOT_CLAIMED",
        }
    )
    admission_index = _build_admission_index(
        freeze=freeze,
        study_id=STUDY_CROSS_ENGINE,
        template_digest=content_digest(dict(template)),
        corpus_manifest_digest=freeze.corpus_manifest_digest,
        original_verifier_digest=_verified_verifier_digest(
            "benchmarks/pr15d/harness/validate.py", freeze
        ),
        raw_series_root_digest=raw_series_root_digest,
        comparability_digest=comparability,
        records=records_before,
    )
    return AdmittedCrossEngine(
        raw_root=raw,
        corpus_dir=corpus,
        run_json=run_json,
        trials=trials,
        validation=validation,
        control=control,
        inventory=tuple(records_before),
        raw_series_root_digest=raw_series_root_digest,
        comparability_digest=comparability,
        admission_index=admission_index,
        original_verifier={"status": outcome.status, "detail": outcome.detail},
        fixture_only=not for_production,
    )


def _verified_verifier_digest(relative: str, freeze: OfficialFreeze) -> str:
    """Hash the original verifier source and require the authorized identity."""

    from ..evidence.provenance import repository_root

    observed, _length = sha256_regular_file(
        repository_root(), relative, max_bytes=MAX_RAW_MEMBER_BYTES
    )
    if observed != freeze.original_reference_verifier_digest:
        raise _identity(
            "the original verifier source differs from the authorized identity",
            "original_reference_verifier_digest",
        )
    return observed


def verify_authorized_source(source_root: Path, freeze: OfficialFreeze) -> str:
    """Re-hash the reviewed source roster and require the authorized identity."""

    from ..qualification.identity import verify_source_identity

    return verify_source_identity(Path(source_root), freeze.source_file_set_digest)


def _digest_string(value: str) -> str:
    """Return a ``sha256:``-prefixed digest for a bare legacy hex digest."""

    if value.startswith("sha256:"):
        return validate_digest(value, "digest")
    return validate_digest("sha256:" + value, "digest")


def _verify_cross_engine_trial(
    manifest: Mapping[str, Any],
    *,
    trial: int,
    engine: str,
    freeze: OfficialFreeze,
    rows_by_n: Mapping[int, Any],
    oracle: Any,
    corpus_manifest_sha: str,
    expected_corpus_digests: Mapping[str, str],
    run_fingerprint: str,
) -> None:
    if manifest.get("schema") != "pr15d-trial-v1":
        raise _schema("a trial manifest schema is not the frozen PR15D trial schema", "schema")
    if manifest.get("trial") != trial or manifest.get("engine") != engine:
        raise _identity("a trial manifest identity does not match its path", "trial")
    if manifest.get("source_sha") != freeze.source_commit:
        raise _identity("a trial manifest records a different source commit", "source_sha")
    fingerprint = manifest.get("host_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise _identity("a trial manifest has no host fingerprint", "host_fingerprint")
    if fingerprint != run_fingerprint:
        raise _identity("a trial manifest records a different host fingerprint", "host_fingerprint")
    if manifest.get("qualified") is not True or manifest.get("status") != "ok":
        raise _identity("a trial manifest is not qualified", "status")
    if manifest.get("corpus_manifest_sha256") != corpus_manifest_sha:
        raise _identity("a trial manifest corpus digest differs", "corpus_manifest_sha256")
    if manifest.get("corpus_digests") != dict(expected_corpus_digests):
        raise _identity("a trial manifest corpus TSV digests differ", "corpus_digests")

    lanes = manifest.get("lanes")
    if not isinstance(lanes, list) or len(lanes) != 32:
        raise _identity("each trial must hold exactly 32 lane descriptors", "lanes")
    expected_keys = pr15d_lane_keys()
    observed_keys: list[tuple[int, str, int, str]] = []
    for index, lane in enumerate(lanes):
        key = (lane.get("n"), lane.get("class"), lane.get("k"), lane.get("regime"))
        observed_keys.append(key)  # type: ignore[arg-type]
        if key not in expected_keys:
            raise _identity("a trial lane is not part of the frozen lane matrix", "lanes")
        if lane.get("id") != pr15d_lane_id(key[0], key[1], key[2]):
            raise _identity("a trial lane id does not match its coordinates", "id")
        n, class_name, k, regime = key
        field, term = pr15d_lane_field(class_name)
        if lane.get("field") != field or lane.get("term") != term:
            raise _identity("a trial lane does not use the frozen field/term", "field")
        samples = lane.get("samples_ns")
        if not isinstance(samples, list) or len(samples) != PR15D_MEASURED:
            raise _identity("a trial lane must hold exactly twenty samples", "samples_ns")
        for sample in samples:
            _require_positive_int(sample, "samples_ns")
        warmups = lane.get("warmups")
        expected_warmups = PR15D_WARMUPS if regime == "warm" else 0
        if warmups != expected_warmups:
            raise _identity("a trial lane warmup count differs from the frozen count", "warmups")
        if regime == "warm":
            ids = lane.get("warmup_ids")
            if not isinstance(ids, list) or len(ids) != PR15D_WARMUPS:
                raise _identity("a warm lane must record five warmup ids", "warmup_ids")
        if lane.get("oracle_ok") is not True:
            raise _identity("a trial lane did not pass its original oracle check", "oracle_ok")
        expected = oracle.expected(rows_by_n[n], field, term, k)
        if lane.get("total_hits") != expected["total_hits"]:
            raise _identity("a trial lane total_hits differs from the independent oracle", "total_hits")
        if list(lane.get("doc_ids") or []) != list(expected["doc_ids"]):
            raise _identity("a trial lane doc_ids differ from the independent oracle", "doc_ids")
        if lane.get("expected_total_hits") != expected["total_hits"]:
            raise _identity("a trial lane expected_total_hits differs", "expected_total_hits")
        if list(lane.get("expected_doc_ids") or []) != list(expected["doc_ids"]):
            raise _identity("a trial lane expected_doc_ids differ", "expected_doc_ids")
        summary = lane.get("summary_ns")
        if not isinstance(summary, Mapping):
            raise _schema("a trial lane summary is missing", "summary_ns")
        ordered = sorted(samples)
        if summary.get("count") != PR15D_MEASURED:
            raise _identity("a trial lane summary count differs", "summary_ns")
        if summary.get("median") != ordered[9]:
            raise _identity("a trial lane median is not the frozen even-N median", "summary_ns")
        if summary.get("p95") != ordered[18] or summary.get("p99") != ordered[18]:
            raise _identity("a trial lane p95/p99 is not the nearest-rank value", "summary_ns")
        if summary.get("min") != ordered[0] or summary.get("max") != ordered[-1]:
            raise _identity(
                "a trial lane summary min/max does not match its raw samples", "summary_ns"
            )
        contention = lane.get("contention")
        if not isinstance(contention, Mapping) or contention.get("pre") != "clear" or contention.get("post") != "clear":
            raise _identity("a trial lane records contention around the measurement", "contention")
    if sorted(observed_keys) != sorted(expected_keys):
        raise _identity("a trial manifest does not cover the exact 32-lane matrix", "lanes")

    build = manifest.get("build")
    if not isinstance(build, Mapping) or set(build) != {"10000", "100000"}:
        raise _identity("a trial manifest must record both corpus builds", "build")
    for n in PR15D_N_VALUES:
        record = build[str(n)]
        if not isinstance(record, Mapping):
            raise _schema("a build record must be an object", "build")
        if record.get("documents_indexed") != n or record.get("documents_verified") != n:
            raise _identity(
                "a build record document count differs from the committed count", "build"
            )
        for name in ("index_ns", "commit_ns", "reopen_ns", "index_bytes", "segment_count"):
            _require_positive_int(record.get(name), f"build.{n}.{name}")

    throughput = manifest.get("throughput")
    if not isinstance(throughput, list) or len(throughput) != 2:
        raise _identity("a trial manifest must record both throughput windows", "throughput")
    window_sizes: set[int] = set()
    for window in throughput:
        if window.get("requests") != PR15D_THROUGHPUT_REQUESTS:
            raise _identity("a throughput window does not hold 100 requests", "requests")
        if window.get("answered") != PR15D_THROUGHPUT_REQUESTS:
            raise _identity("a throughput window did not answer every request", "answered")
        window_sizes.add(_require_plain_int(window.get("n"), "throughput.n"))
        wall_ns = _require_positive_int(window.get("wall_ns"), "throughput.wall_ns")
        observed_rate = _require_positive_number(
            window.get("serial_ops_per_second"), "throughput.serial_ops_per_second"
        )
        expected_rate = round(PR15D_THROUGHPUT_REQUESTS * 1_000_000_000 / wall_ns, 6)
        if observed_rate != expected_rate:
            raise _identity(
                "a throughput window rate is not derived from its wall time", "throughput"
            )
    if window_sizes != set(PR15D_N_VALUES):
        raise _identity("the throughput windows do not cover both corpus sizes", "throughput")

    contention = manifest.get("contention")
    if not isinstance(contention, list) or not contention:
        raise _schema("a trial manifest must record contention probes", "contention")
    for probe in contention:
        if probe.get("state") != "clear":
            raise _identity("a trial contention probe was not clear", "contention")

    # Every scored/BM25 claim remains semantically non-comparable.
    scored = manifest.get("scored_lane")
    if scored is not None and not isinstance(scored, Mapping):
        raise _schema("scored_lane must be an object when present", "scored_lane")


# ---------------------------------------------------------------------------
# Retained-key admission
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdmittedRetainedKey:
    """The complete, authenticated retained-key raw series."""

    raw_root: Path
    campaigns: Mapping[str, Mapping[str, Any]]
    slots: Mapping[str, tuple[Mapping[str, Any], ...]]
    control_assessment: Mapping[str, Any]
    inventory: tuple[Mapping[str, Any], ...]
    raw_series_root_digest: str
    comparability_digest: str
    admission_index: Mapping[str, Any]
    original_verifier: Mapping[str, Any]
    fixture_only: bool = False


def _frozen_schedule(
    template: Mapping[str, Any], campaign: str
) -> list[dict[str, Any]]:
    schedule = template["schedule"]
    if campaign == D3C_CONTROL_NAME:
        rows = schedule["control_order"]
        width = 4
    elif campaign == D3C_CAMPAIGN_NAMES[0]:
        rows = schedule["campaign_01_order"]
        width = 8
    elif campaign == D3C_CAMPAIGN_NAMES[1]:
        rows = schedule["campaign_02_order"]
        width = 8
    else:  # pragma: no cover - guarded by the frozen campaign list
        raise _identity("unknown retained-key campaign", "campaign")
    if len(rows) != D3C_BLOCKS:
        raise _identity("the frozen schedule does not hold twelve blocks", "schedule")
    plan: list[dict[str, Any]] = []
    for block, row in enumerate(rows, start=1):
        if len(row) != width:  # pragma: no cover - validated by the template
            raise _identity("a frozen schedule row has the wrong width", "schedule")
        for position, arm in enumerate(row, start=1):
            plan.append(
                {
                    "slot": (block - 1) * width + position,
                    "block": block,
                    "position": position,
                    "arm": str(arm),
                }
            )
    return plan


def admit_retained_key_real(
    *,
    raw_root: Path,
    authorization: VerifiedOfficialAuthorization,
    template: Mapping[str, Any],
    source_root: Path | None = None,
    observed: Mapping[str, Any] | None = None,
) -> AdmittedRetainedKey:
    """Gate A: authenticate the complete D3-C control and treatment campaigns."""

    freeze = require_verified_official_authorization(
        authorization,
        study_id=STUDY_RETAINED_KEY,
        for_production=True,
        observed=observed,
    )
    return _admit_retained_key_core(
        raw_root=raw_root,
        freeze=freeze,
        template=template,
        source_root=source_root,
        original_verifier=OriginalVerifier(),
        for_production=True,
    )


def _admit_retained_key_core(
    *,
    raw_root: Path,
    freeze: OfficialFreeze,
    template: Mapping[str, Any],
    source_root: Path | None,
    original_verifier: Any,
    for_production: bool,
) -> AdmittedRetainedKey:
    """Internal Gate A derivation shared by production and fixture-only tests."""

    require_freeze(freeze, STUDY_RETAINED_KEY)
    if template.get("study_id") != STUDY_RETAINED_KEY:
        raise _identity("the template is for a different study", "study_id")
    raw = require_safe_root(Path(raw_root))
    verifier = original_verifier
    if source_root is not None:
        verify_authorized_source(Path(source_root), freeze)

    campaigns = [D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES]
    members_before = retained_key_member_paths(raw)
    records_before, _total = hash_raw_members(raw, members_before)

    campaign_documents: dict[str, dict[str, Any]] = {}
    slot_records: dict[str, tuple[Mapping[str, Any], ...]] = {}
    host_fingerprints: set[str] = set()
    for campaign in campaigns:
        directory = raw / campaign
        manifest, _ = _read_json_member(directory, "manifest.json", label="manifest.json")
        authorization, _ = _read_json_member(directory, "authorization.json", label="authorization.json")
        seal, _ = _read_json_member(directory, "raw/seal.json", label="raw/seal.json")
        summary, summary_digest = _read_json_member(
            directory, "sanitized/summary.json", label="sanitized/summary.json"
        )
        readiness, _ = _read_json_member(
            directory, "raw/host-readiness.json", label="raw/host-readiness.json"
        )
        host, _ = _read_json_member(
            directory, "raw/host-attestation.json", label="raw/host-attestation.json"
        )
        validate_readiness_record(readiness)
        if readiness["status"] != "READY":
            raise _identity("a campaign was measured on a not-ready host", "status")
        host_fingerprints.add(str(host.get("host_fingerprint")))
        if manifest.get("schema") != "pr15i-d3c-manifest-v1":
            raise _schema("a campaign manifest schema is not the frozen D3-C schema", "schema")
        if manifest.get("protocol_sha256") != "c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c":
            raise _identity("a campaign records a different frozen protocol digest", "protocol_sha256")
        if authorization.get("rehearsal_only") is True:
            raise _identity("a rehearsal campaign is not admissible real evidence", "rehearsal_only")
        expected_kind = "control" if campaign == D3C_CONTROL_NAME else "four_arm"
        if manifest.get("kind") != expected_kind:
            raise _identity("a campaign manifest kind is not the expected kind", "kind")
        if manifest.get("campaign") != campaign:
            raise _identity("a campaign manifest name does not match its directory", "campaign")
        if manifest.get("source_base_sha") != template["source_requirements"]["base_commit"]:
            raise _identity("a campaign records a different base source commit", "source_base_sha")
        if expected_kind == "four_arm":
            if manifest.get("source_experiment_sha") != template["source_requirements"]["experiment_commit"]:
                raise _identity(
                    "a treatment campaign records a different experiment source commit",
                    "source_experiment_sha",
                )
        elif manifest.get("source_experiment_sha") is not None:
            raise _identity("the control campaign must be BASE-only", "source_experiment_sha")
        _verify_seal(directory, seal)
        plan = _frozen_schedule(template, campaign)
        slots = _verify_retained_key_slots(
            directory, campaign=campaign, plan=plan, manifest=manifest, template=template
        )
        slot_records[campaign] = tuple(slots)
        campaign_documents[campaign] = {
            "manifest": manifest,
            "authorization": authorization,
            "seal": seal,
            "summary": summary,
            "summary_digest": summary_digest,
            "readiness": readiness,
            "host": host,
            "kind": expected_kind,
        }
        outcome = verifier.verify_retained_key_campaign(directory)
        if outcome.status != "ACQUIRED_VERIFIED":
            raise _identity(
                "the original D3-C verifier did not report ACQUIRED_VERIFIED",
                "original-verifier",
            )
    if len(host_fingerprints) != 1:
        raise _identity("the campaign host fingerprints differ across the series", "host_fingerprint")

    series_outcome = verifier.verify_retained_key_series(raw)
    if series_outcome.status != "PASS":
        raise _identity("the original D3-C series verifier did not PASS", "original-verifier")

    control_assessment = assess_retained_key_control(
        slots=slot_records[D3C_CONTROL_NAME],
        lane_ids=d3c_lane_ids(),
        windows=template["controls"]["windows"],
    )
    require_control_pass(control_assessment)
    summary_control = campaign_documents[D3C_CONTROL_NAME]["summary"]
    reported = summary_control.get("a_a", {}).get("passes")
    if reported is not True:
        raise _identity(
            "the recorded control summary does not report a passing A/A",
            "control_summary",
        )

    records_after, _total = hash_raw_members(raw, members_before)
    if records_after != records_before:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "raw evidence changed while it was being admitted",
            field_path="raw-series-root",
        )

    raw_series_root_digest = inventory_digest(records_before)
    comparability = content_digest(
        {
            "kind": "official-comparability",
            "schema_version": 1,
            "eligible_regime": "warm",
            "excluded_lane_classes": ["process_cold", "scored_bm25", "throughput"],
            "unit": "nanoseconds",
            "profile": template["statistics"]["prefilter_profile"],
        }
    )
    admission_index = _build_admission_index(
        freeze=freeze,
        study_id=STUDY_RETAINED_KEY,
        template_digest=content_digest(dict(template)),
        corpus_manifest_digest=freeze.corpus_manifest_digest,
        original_verifier_digest=_verified_verifier_digest(
            "benchmarks/pr15i_d3_c/verify.py", freeze
        ),
        raw_series_root_digest=raw_series_root_digest,
        comparability_digest=comparability,
        records=records_before,
    )
    return AdmittedRetainedKey(
        raw_root=raw,
        campaigns=campaign_documents,
        slots=slot_records,
        control_assessment=control_assessment,
        inventory=tuple(records_before),
        raw_series_root_digest=raw_series_root_digest,
        comparability_digest=comparability,
        admission_index=admission_index,
        original_verifier={
            "campaigns": "ACQUIRED_VERIFIED",
            "series": series_outcome.status,
        },
        fixture_only=not for_production,
    )


def _verify_seal(directory: Path, seal: Mapping[str, Any]) -> None:
    files = seal.get("files")
    if not isinstance(files, Mapping) or not files:
        raise _schema("the campaign seal does not declare its files", "files")
    declared = sorted(files)
    for relative in declared:
        if relative.startswith("/") or ".." in relative.split("/"):
            raise BenchError(BM_UNSAFE_INPUT, "the campaign seal declares an unsafe path")
    actual = [
        item
        for item in walk_raw_members(
            directory, exclude_any_dir=("build", "indexes", "corpus", "compile-source")
        )
        if item
        not in (
            "raw/seal.json",
            "verification.json",
        )
    ]
    if sorted(actual) != declared:
        raise _identity("the campaign seal does not match the actual member set", "files")
    for relative, digest in files.items():
        observed, _length = sha256_regular_file(
            directory, relative, max_bytes=MAX_RAW_MEMBER_BYTES
        )
        if _digest_string(observed) != _digest_string(str(digest)):
            raise _identity("a sealed campaign member digest differs", "files")


def _verify_retained_key_slots(
    directory: Path,
    *,
    campaign: str,
    plan: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    template: Mapping[str, Any],
) -> list[dict[str, Any]]:
    arms = manifest.get("arms")
    if not isinstance(arms, Mapping):
        raise _schema("a campaign manifest must declare its arms", "arms")
    expected_arms = {"A", "B"} if campaign == D3C_CONTROL_NAME else {"A", "L", "P", "H"}
    if set(arms) != expected_arms:
        raise _identity("a campaign manifest arm set is not the frozen set", "arms")
    if campaign == D3C_CONTROL_NAME:
        if arms["A"].get("binary_sha256") != arms["B"].get("binary_sha256"):
            raise _identity("the A/A control used two different binaries", "arms")
    else:
        experimental = arms["L"].get("binary_sha256")
        for arm in ("P", "H"):
            if arms[arm].get("binary_sha256") != experimental:
                raise _identity("the experimental arms used different binaries", "arms")
        if arms["A"].get("binary_sha256") == experimental:
            raise _identity("the experimental binary equals BASE", "arms")
    index_digests: dict[int, set[str]] = {}
    for arm, info in arms.items():
        indexes = info.get("indexes")
        if not isinstance(indexes, Mapping):
            raise _schema("each arm must declare its indexes", "indexes")
        for n in D3C_N_VALUES:
            layout = indexes.get(str(n))
            if not isinstance(layout, Mapping):
                raise _schema("each arm must declare both index layouts", "indexes")
            _require_positive_int(layout.get("bytes"), "indexes.bytes")
            index_digests.setdefault(n, set()).add(str(layout.get("digest")))
            if n == 100_000 and layout.get("bytes") != template["source_requirements"]["index_100k_committed_sentinel"]:
                raise _identity("the 100K committed index sentinel differs", "indexes")
    if any(len(values) != 1 for values in index_digests.values()):
        raise _identity("the arms' index digests differ within one corpus size", "indexes")

    lanes = d3c_lane_keys()
    slots: list[dict[str, Any]] = []
    for entry in plan:
        relative = f"raw/slots/slot-{entry['slot']:02d}.json"
        slot, _ = _read_json_member(directory, relative, label=relative)
        if slot.get("schema") != "pr15i-d3c-slot-v1":
            raise _schema("a slot schema is not the frozen D3-C slot schema", "schema")
        if (slot.get("slot"), slot.get("block"), slot.get("position"), slot.get("arm")) != (
            entry["slot"],
            entry["block"],
            entry["position"],
            entry["arm"],
        ):
            raise _identity("a slot address does not match the frozen schedule", "slots")
        arm = str(entry["arm"])
        arm_info = arms[arm]
        if slot.get("binary_sha256") != arm_info.get("binary_sha256"):
            raise _identity("a slot records a different binary", "binary_sha256")
        if slot.get("source_sha") != arm_info.get("source_sha"):
            raise _identity("a slot records a different source commit", "source_sha")
        expected_index = {
            str(n): arm_info["indexes"][str(n)]["digest"] for n in D3C_N_VALUES
        }
        if slot.get("index_digests") != expected_index:
            raise _identity("a slot records different index digests", "index_digests")
        for tag in ("before", "after"):
            probe = slot.get(f"contention_{tag}")
            if not isinstance(probe, Mapping) or probe.get("state") not in ("clear", "busy"):
                raise _identity("a slot does not record its contention probe", "contention")
        records = slot.get("lanes")
        if not isinstance(records, list) or len(records) != len(lanes):
            raise _identity("a slot must hold exactly 72 lane records", "lanes")
        if [record.get("id") for record in records] != [lane["lane_id"] for lane in lanes]:
            raise _identity("a slot lane order is not the frozen order", "lanes")
        marker = D3C_MODE_MARKERS[arm]
        observed: list[dict[str, Any]] = []
        for lane, record in zip(lanes, records):
            expected = retained_key_oracle(lane["n"], lane["class"], lane["k"])
            if record.get("total_hits") != expected["total_hits"]:
                raise _identity("a retained-key lane total_hits differs from the oracle", "total_hits")
            if list(record.get("doc_ids") or []) != list(expected["doc_ids"]):
                raise _identity("a retained-key lane doc_ids differ from the oracle", "doc_ids")
            samples = record.get("samples_ns")
            if not isinstance(samples, list) or len(samples) != D3C_SAMPLES:
                raise _identity("a retained-key lane must hold twenty samples", "samples_ns")
            for sample in samples:
                _require_positive_int(sample, "samples_ns")
            summary = record.get("summary_ns")
            ordered = sorted(samples)
            if not isinstance(summary, Mapping):
                raise _schema("a retained-key lane summary is missing", "summary_ns")
            if summary.get("median") != ordered[9]:
                raise _identity("a retained-key lane median is not sorted[9]", "summary_ns")
            if summary.get("count") != D3C_SAMPLES:
                raise _identity("a retained-key lane summary count differs", "summary_ns")
            if summary.get("min") != ordered[0] or summary.get("max") != ordered[-1]:
                raise _identity(
                    "a retained-key lane summary min/max does not match its raw samples",
                    "summary_ns",
                )
            if record.get("mode_marker") != marker:
                raise _identity("a retained-key lane mode marker differs from the arm", "mode_marker")
            observed.append(record)
        slot = dict(slot)
        slot["lanes"] = observed
        slots.append(slot)
    return slots


# ---------------------------------------------------------------------------
# Admission index
# ---------------------------------------------------------------------------


def _build_admission_index(
    *,
    freeze: OfficialFreeze,
    study_id: str,
    template_digest: str,
    corpus_manifest_digest: str,
    original_verifier_digest: str,
    raw_series_root_digest: str,
    comparability_digest: str,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    document = {
        "kind": "official-evidence-admission-index",
        "schema_version": 1,
        "evidence_origin": "real",
        "qualification_scope": "official",
        "subject": {
            "experiment_id": study_id,
            "run_id": freeze.run_id,
            "protocol_digest": freeze.design_digest,
            "workload_digest": freeze.backend_protocol_digest,
        },
        "study_id": study_id,
        "approved_design_digest": freeze.design_digest,
        "authorization_digest": freeze.authorization_digest,
        "source_set_digest": freeze.source_file_set_digest,
        "host_identity_digest": freeze.host_preflight_digest,
        "binary_manifest_digest": freeze.binary_manifest_digest,
        "corpus_manifest_digest": corpus_manifest_digest,
        "original_verifier_digest": original_verifier_digest,
        "raw_series_root_digest": raw_series_root_digest,
        "series_status": "ADMITTED_REAL",
        "members": [dict(record) for record in records],
        "required_inventory": [record["path"] for record in records],
        "comparability_digest": comparability_digest,
    }
    from .contracts import validate_official_evidence_index

    index = validate_official_evidence_index(document)
    bound_payload(index, "admission-index")
    return index


def admission_inventory_digest(study_root: Path, *, exclude_top_level: Sequence[str] = ()) -> str:
    """Re-hash a raw evidence root and return its inventory digest."""

    members = walk_raw_members(study_root, exclude_top_level=exclude_top_level)
    records, _total = hash_raw_members(study_root, members)
    return inventory_digest(records)


def recompute_control_digest(control: Mapping[str, Any]) -> str:
    """Return the canonical digest of a control assessment document."""

    return control_digest(control)


__all__ = [
    "AdmittedCrossEngine",
    "AdmittedRetainedKey",
    "D3C_CAMPAIGN_NAMES",
    "D3C_CONTROL_NAME",
    "D3C_SAMPLES",
    "D3C_WARMUPS",
    "MAX_RAW_MEMBER_BYTES",
    "OriginalVerifier",
    "OriginalVerifierOutcome",
    "PR15D_CLASSES",
    "PR15D_ENGINES",
    "PR15D_K_VALUES",
    "PR15D_MEASURED",
    "PR15D_N_VALUES",
    "PR15D_REGIMES",
    "PR15D_TRIAL_ORDER",
    "PR15D_TRIALS",
    "PR15D_WARMUPS",
    "_admit_cross_engine_core",
    "_admit_retained_key_core",
    "admit_cross_engine_real",
    "admitted_inventory_digest",
    "cross_engine_inventory_digest",
    "cross_engine_member_paths",
    "admit_retained_key_real",
    "admission_inventory_digest",
    "d3c_lane_ids",
    "d3c_lane_keys",
    "hash_raw_members",
    "inventory_digest",
    "load_pr15d_oracle",
    "load_pr15d_validator",
    "pr15d_lane_field",
    "pr15d_lane_id",
    "pr15d_lane_keys",
    "pr15d_warm_lane_ids",
    "recompute_control_digest",
    "retained_key_inventory_digest",
    "retained_key_member_paths",
    "retained_key_oracle",
    "verify_authorized_source",
    "walk_raw_members",
]
