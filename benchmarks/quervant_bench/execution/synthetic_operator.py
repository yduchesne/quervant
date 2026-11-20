"""Configured synthetic operation through the existing BM-03/BM-06 engines.

This module owns paths and the public lifecycle only. The logical controller,
analysis, verification, QA checks and atomic qualification publisher remain the
existing implementations. A synthetic operation can never select an official
backend or promote its resulting scope.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..config.codec import canonical_document_bytes, content_digest, decode_text, loads_json
from ..config.contracts import ExperimentBundle, build_outcome
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_OK,
    BM_PUBLICATION_CONFLICT,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BM_USAGE,
    BenchError,
)
from ..config.identity import validate_digest, validate_uuid4
from ..evidence.paths import open_regular_beneath, require_publication_base, require_safe_root
from ..evidence.provenance import repository_root
from ..migrations.cross_engine import validate_cross_engine_reference
from ..migrations.retained_key import load_reference_bundle
from ..qualification.contracts import require_bundle_scope, require_closed, require_synthetic_scope
from ..qualification.coordinator import load_qualified_synthetic_run, qualify_synthetic_run
from ..qualification.identity import verify_source_identity
from ..qualification.profiles import read_qualification_profile
from ..qualification.publication import OsPublicationIO, load_bundle
from ..qualification.qa import read_qa_evidence
from .clock import LogicalClock
from .controller import ScenarioReadinessProvider, SimulatedCapabilityProvider, execute_synthetic
from .operator import (
    STAGE_VERBS,
    SYNTHETIC_CONFIG_KIND,
    SYNTHETIC_EXPERIMENTS,
    execute_stages,
    read_operation_document,
)
from .scenario import load_synthetic_scenario
from .synthetic import synthetic_adapter_factory

_PATH_FIELDS = (
    "source_root", "catalog_root", "scenario_root", "output_root",
    "qualification_profile_path", "qa_evidence_root",
)
_DIGEST_FIELDS = (
    "expected_profile_digest", "expected_framework_qa_digest",
    "expected_source_qa_digest", "expected_source_set_digest",
)
_CONFIG_KEYS = frozenset({
    "kind", "schema_version", "evidence_origin", "qualification_scope",
    "experiment_id", "run_id", *_PATH_FIELDS, *_DIGEST_FIELDS,
})
_STAGE_MEMBERS = {
    "validate": ("admission.json",),
    "analyze": ("analysis.json", "policy.json", "analysis-receipt.json"),
    "verify": ("verification.json", "verification-assessment.json"),
    "accept": ("acceptance.json", "acceptance-summary.json"),
    "report": ("policy.json", "attestation.json"),
}


def _identity(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def _absolute_path(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise BenchError(BM_SCHEMA_INVALID, "an absolute local path is required", field_path=field)
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise BenchError(BM_UNSAFE_INPUT, "operation paths must be absolute without parent traversal", field_path=field)
    return path


def read_synthetic_operation(config_path: Path) -> dict[str, Any]:
    """Validate the closed configuration without inventing any QA anchor."""

    document = read_operation_document(config_path)
    require_closed(document, "config", _CONFIG_KEYS)
    if document["kind"] != SYNTHETIC_CONFIG_KIND:
        raise BenchError(BM_SCHEMA_INVALID, "synthetic operation configuration required", field_path="kind")
    require_synthetic_scope(document)
    if document["experiment_id"] not in SYNTHETIC_EXPERIMENTS:
        raise BenchError(BM_SCHEMA_INVALID, "unsupported synthetic experiment", field_path="experiment_id")
    validate_uuid4(document["run_id"], "run_id")
    for field in _PATH_FIELDS:
        _absolute_path(document[field], field)
    for field in _DIGEST_FIELDS:
        validate_digest(document[field], field)
    return document


def _load_catalog(config: Mapping[str, Any]) -> tuple[ExperimentBundle, object]:
    catalog = require_safe_root(Path(config["catalog_root"]))
    source = require_safe_root(Path(config["source_root"]))
    if config["experiment_id"] == SYNTHETIC_EXPERIMENTS[0]:
        bundle, companions = validate_cross_engine_reference(catalog, source)
    else:
        bundle, companions = load_reference_bundle(catalog), None
    require_bundle_scope(bundle)
    identity = (
        content_digest(bundle.experiment_document),
        content_digest(bundle.workload_document),
        content_digest(bundle.protocol_document),
        content_digest(bundle.adapter_document),
        companions,
    )
    return bundle, identity


def _preflight_inputs(config: Mapping[str, Any]) -> tuple[ExperimentBundle, object, Any]:
    bundle, identity = _load_catalog(config)
    source_digest = verify_source_identity(
        Path(config["source_root"]), config["expected_source_set_digest"]
    )
    _profile, profile_digest = read_qualification_profile(
        Path(config["qualification_profile_path"]), config["expected_profile_digest"]
    )
    for gate, field in (
        ("framework-qa", "expected_framework_qa_digest"),
        ("source-qa", "expected_source_qa_digest"),
    ):
        read_qa_evidence(
            qa_evidence_root=Path(config["qa_evidence_root"]),
            gate=gate,
            expected_document_digest=config[field],
            profile_digest=profile_digest,
            source_set_digest=source_digest,
        )
    scenario = load_synthetic_scenario(Path(config["scenario_root"]), bundle=bundle)
    return bundle, identity, scenario


def _require_unchanged(config_path: Path, config: Mapping[str, Any], identity: object) -> None:
    if content_digest(read_synthetic_operation(config_path)) != content_digest(config):
        raise _identity("operation configuration changed during execution", "config")
    _bundle, fresh_identity = _load_catalog(config)
    if fresh_identity != identity:
        raise _identity("catalog or source bindings changed during operation", "catalog")
    verify_source_identity(Path(config["source_root"]), config["expected_source_set_digest"])


def _require_new_output(config: Mapping[str, Any], config_path: Path, out: Path) -> Path:
    output = Path(config["output_root"])
    if out.absolute() != output:
        raise _identity("--out does not match the operation configuration", "output_root")
    require_safe_root(output.parent)
    if output.exists() or output.is_symlink():
        raise BenchError(BM_PUBLICATION_CONFLICT, "operation output must be a new directory", field_path="output_root")
    repository = repository_root().absolute()
    if output == repository or output in repository.parents:
        raise BenchError(BM_UNSAFE_INPUT, "operation output cannot contain the repository", field_path="output_root")
    if repository in output.parents:
        allowed = repository / "benchmark-results"
        if output != allowed and allowed not in output.parents:
            raise BenchError(BM_UNSAFE_INPUT, "repository output is restricted to benchmark-results", field_path="output_root")
    roots = [Path(config[key]) for key in ("catalog_root", "scenario_root", "qa_evidence_root")]
    roots.append(Path(config["qualification_profile_path"]).parent)
    for root in roots:
        require_safe_root(root)
        if output == root or output in root.parents or root in output.parents:
            raise BenchError(BM_UNSAFE_INPUT, "operation output overlaps an input root", field_path="output_root")
    config_file = config_path.absolute()
    if output == config_file or output in config_file.parents:
        raise BenchError(BM_UNSAFE_INPUT, "operation output contains its configuration", field_path="output_root")
    return output


def _write_exclusive(path: Path, document: Mapping[str, Any]) -> None:
    io = OsPublicationIO()
    require_safe_root(path.parent)
    descriptor = io.create_exclusive(path)
    try:
        io.write_all(descriptor, canonical_document_bytes(document))
        io.fsync_file(descriptor)
    finally:
        io.close(descriptor)
    io.fsync_dir(path.parent)


def _operation_identity(config: Mapping[str, Any], bundle: ExperimentBundle) -> dict[str, Any]:
    return {
        "kind": "synthetic-operation-identity",
        "schema_version": 1,
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "experiment_id": config["experiment_id"],
        "run_id": config["run_id"],
        "operation_config_digest": content_digest(config),
        "protocol_digest": bundle.protocol_digest,
        "source_set_digest": config["expected_source_set_digest"],
    }


def _qualification_arguments(config: Mapping[str, Any], bundle: ExperimentBundle) -> dict[str, Any]:
    output = Path(config["output_root"])
    experiment = config["experiment_id"]
    return {
        "bundle": bundle,
        "run_dir": output / "runs" / experiment / config["run_id"],
        "scenario_root": Path(config["scenario_root"]),
        "profiles_root": Path(config["catalog_root"]) / experiment,
        "resources_root": Path(config["catalog_root"]) / experiment,
        "qualification_profile_path": Path(config["qualification_profile_path"]),
        "qa_evidence_root": Path(config["qa_evidence_root"]),
        "source_root": Path(config["source_root"]),
        "output_base": output / "qualified",
        **{field: config[field] for field in _DIGEST_FIELDS},
    }


def run_synthetic(experiment: str, protocol_path: Path, out: Path, config_path: Path) -> dict[str, Any]:
    """Execute logical acquisition and qualification once into a new workspace."""

    config = read_synthetic_operation(config_path)
    if experiment != config["experiment_id"]:
        raise _identity("experiment does not match the operation configuration", "experiment_id")
    expected_protocol = Path(config["catalog_root"]) / experiment / "protocol.yaml"
    if protocol_path.absolute() != expected_protocol:
        raise _identity("--protocol must identify the validated catalog member", "protocol")
    output = _require_new_output(config, config_path, out)
    context: dict[str, Any] = {}
    pending_events: list[dict[str, Any]] = []
    output_ready = False

    def flush_events() -> None:
        while pending_events:
            event = pending_events[0]
            _write_exclusive(output / "journal" / f"{event['sequence']:04d}.json", event)
            pending_events.pop(0)

    def on_event(event: dict[str, Any]) -> None:
        pending_events.append(event)
        if output_ready:
            flush_events()

    def prepare() -> None:
        nonlocal output_ready
        bundle, identity, scenario = _preflight_inputs(config)
        _require_unchanged(config_path, config, identity)
        _require_new_output(config, config_path, out)
        io = OsPublicationIO()
        try:
            io.create_directory(output)
        except FileExistsError as error:
            raise BenchError(BM_PUBLICATION_CONFLICT, "operation output already exists") from error
        require_publication_base(output, repository_root())
        for name in ("runs", "qualified", "journal"):
            io.create_directory(output / name)
        _write_exclusive(output / "operation.json", _operation_identity(config, bundle))
        context.update(bundle=bundle, identity=identity, scenario=scenario)
        output_ready = True
        flush_events()

    def acquisition() -> Any:
        _require_unchanged(config_path, config, context["identity"])
        execution = execute_synthetic(
            bundle=context["bundle"],
            scenario=context["scenario"],
            run_id=config["run_id"],
            evidence_root=Path(config["scenario_root"]),
            output_base=output / "runs",
            adapter_factory=synthetic_adapter_factory(context["bundle"]),
            capability_provider=SimulatedCapabilityProvider(),
            readiness_provider=ScenarioReadinessProvider(context["scenario"]),
            clock=LogicalClock(),
        )
        if execution.status != "sealed":
            raise _identity("synthetic acquisition did not seal", "execution.status")
        return execution

    def qualification() -> Any:
        result = qualify_synthetic_run(**_qualification_arguments(config, context["bundle"]))
        _require_unchanged(config_path, config, context["identity"])
        return result

    results = execute_stages(
        "synthetic-qualification",
        {"prepare": prepare, "acquisition": acquisition, "qualification": qualification},
        on_event=on_event,
    )
    result = results["qualification"]
    return build_outcome("ok", BM_OK, "Synthetic logical acquisition and qualification completed.", {
        "kind": "synthetic-operation-result",
        "schema_version": 1,
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "disposition": result.disposition,
        "experiment_id": result.experiment_id,
        "run_id": result.run_id,
        "manifest_digest": result.manifest_digest,
        "attestation_receipt_id": result.attestation_receipt_id,
        "output_directory": str(result.output_directory),
    })


def dispatch_synthetic_stage(verb: str, run_id: str, config_path: Path) -> dict[str, Any]:
    """Read a stage only after full committed-bundle and input re-verification."""

    if verb not in STAGE_VERBS:
        raise BenchError(BM_USAGE, "unsupported synthetic stage", field_path="verb")
    config = read_synthetic_operation(config_path)
    if validate_uuid4(run_id, "run_id") != config["run_id"]:
        raise _identity("run does not match the operation configuration", "run_id")
    bundle, identity, _scenario = _preflight_inputs(config)
    output = require_publication_base(Path(config["output_root"]), repository_root())
    with open_regular_beneath(output, "operation.json") as stream:
        payload = stream.read(65_537)
    if len(payload) > 65_536:
        raise BenchError(BM_UNSAFE_INPUT, "operation identity exceeds its byte budget")
    persisted = loads_json(decode_text(payload))
    if payload != canonical_document_bytes(persisted):
        raise BenchError(BM_UNSAFE_INPUT, "operation identity must be canonical")
    if payload != canonical_document_bytes(_operation_identity(config, bundle)):
        raise _identity("operation identity does not match current configuration", "operation")
    result = load_qualified_synthetic_run(**_qualification_arguments(config, bundle))
    committed = load_bundle(
        output_base=output / "qualified",
        experiment_id=config["experiment_id"],
        run_id=run_id,
    )
    if committed.manifest_digest != result.manifest_digest:
        raise _identity("committed manifest changed during stage replay", "manifest")
    _require_unchanged(config_path, config, identity)
    return build_outcome("ok", BM_OK, "Synthetic stage re-verified from committed evidence.", {
        "kind": "synthetic-operation-stage",
        "schema_version": 1,
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "stage": verb,
        "experiment_id": config["experiment_id"],
        "run_id": run_id,
        "manifest_digest": result.manifest_digest,
        "attestation_receipt_id": result.attestation_receipt_id,
        "documents": {name: dict(committed.documents[name]) for name in _STAGE_MEMBERS[verb]},
    })


__all__ = ["dispatch_synthetic_stage", "read_synthetic_operation", "run_synthetic"]
