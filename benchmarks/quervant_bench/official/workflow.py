"""Supported operator entrypoints for migrated official benchmark families.

``prepare`` builds inputs without measurement. ``run`` requires external G0 and
seals a complete raw series. Later verbs re-open that series, derive analysis and
verification, and invoke the existing A--E coordinator. The operator journal is
never used as authority; every read reconstructs capabilities from their inputs.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import content_digest, canonical_payload_bytes
from ..config.contracts import build_outcome
from ..config.errors import BM_EVIDENCE_UNAVAILABLE, BM_IDENTITY_INVALID, BM_OK, BM_PUBLICATION_CONFLICT, BM_UNSAFE_INPUT, BM_USAGE, BenchError
from ..config.identity import validate_uuid4
from ..execution.operator import execute_stages
from ..host.readiness import ReadinessLimits
from . import acquisition, admission, analysis, authorization, controls, coordinator, historical, publication, verification
from .operation_config import OperationConfig, absolute_path, load_operation_config
from .operation_identity import observe_identities, observe_host, git_identity
from .operation_store import EventJournal, create_directory, write_record
from .protocols import CURRENT_BASELINE_PROFILE, STUDY_CROSS_ENGINE, STUDY_RETAINED_KEY, D3C_CAMPAIGN_NAMES, D3C_CONTROL_NAME, host_environment_matches, read_canonical_json, template_path, validate_template, verify_backend_protocol
from .retained_backend import load_prepared_retained_key, prepare_retained_key, legacy_runner, require_retained_namespace, verify_campaign_binaries


@dataclass(frozen=True)
class Operation:
    config: OperationConfig
    template: Mapping[str, Any]
    authorization: authorization.VerifiedOfficialAuthorization
    prepared: Any
    observed: Mapping[str, Any]
    directory: Path
    runtime_context: Any = None
    config_path: Path | None = None
    host_preflight: Mapping[str, Any] | None = None

    @property
    def raw_root(self) -> Path:
        return self.directory / "raw"


def _template(experiment: str, protocol_path: Path, config: OperationConfig) -> dict[str, Any]:
    if experiment not in (STUDY_CROSS_ENGINE, STUDY_RETAINED_KEY):
        raise BenchError(BM_USAGE, "unknown official experiment", field_path="experiment")
    path = Path(protocol_path)
    if not path.is_absolute():
        path = config.path("source_root") / path
    document = validate_template(read_canonical_json(path))
    if document["schema_version"] != config.profile_version:
        raise BenchError(BM_IDENTITY_INVALID, "operation and template profiles differ", field_path="schema_version")
    if document["study_id"] != experiment:
        raise BenchError(BM_IDENTITY_INVALID, "the requested experiment differs from its protocol", field_path="study_id")
    checked_in = validate_template(read_canonical_json(template_path(experiment, config.path("source_root"), version=config.profile_version)))
    if content_digest(document) != content_digest(checked_in):
        raise BenchError(BM_IDENTITY_INVALID, "the protocol must equal this checkout's registered design", field_path="design_digest")
    verify_backend_protocol(document, config.path("source_root"))
    if config.profile_version == 2:
        baseline = config.document["baseline"]
        if experiment == STUDY_CROSS_ENGINE and (baseline["runtime_freeze_path"] is not None or config.document["policy_inputs"] is not None):
            raise BenchError(BM_UNSAFE_INPUT, "cross-engine cannot consume retained-only runtime/policy inputs", field_path="baseline.runtime_freeze_path")
        if experiment == STUDY_RETAINED_KEY and baseline["runtime_freeze_path"] is None:
            raise BenchError(BM_UNSAFE_INPUT, "retained v2 requires a current runtime envelope path", field_path="baseline.runtime_freeze_path")
    return document


def _preservation_root(config: OperationConfig) -> Path | None:
    if config.profile_version == 1:
        return None
    from .transport import validate_baseline_evidence_root
    baseline = config.document["baseline"]
    root = absolute_path(baseline["evidence_root"], "baseline.evidence_root")
    validate_baseline_evidence_root(evidence_root=root, baseline_id=baseline["baseline_id"],
                                    source_root=config.path("source_root"))
    return root


def _prepared(config: OperationConfig, study_id: str) -> Any:
    if study_id == STUDY_CROSS_ENGINE:
        from .cross_engine_backend import load_prepared
        prepared = load_prepared(config.path("prepared_manifest"), root=config.path("source_root"))
    else:
        prepared = load_prepared_retained_key(config.path("prepared_manifest"), root=config.path("source_root"))
    if prepared.corpus_dir != config.path("corpus_dir"):
        raise BenchError(BM_IDENTITY_INVALID, "the configured corpus is not the prepared corpus", field_path="corpus_dir")
    return prepared


def _open(config: OperationConfig, template: Mapping[str, Any], directory: Path,
          *, config_path: Path | None = None) -> Operation:
    if config.profile_version != template["schema_version"]:
        raise BenchError(BM_IDENTITY_INVALID, "operation and template profiles differ", field_path="schema_version")
    _preservation_root(config)
    prepared = _prepared(config, template["study_id"])
    runtime_context = None
    if config.profile_version == 2 and template["study_id"] == STUDY_RETAINED_KEY:
        from .runtime_freeze import open_current_runtime_freeze
        runtime_context = open_current_runtime_freeze(config=config, template=template, prepared=prepared)
    observed = observe_identities(config, template, binary_manifest_digest=prepared.binary_digest)
    approval, _ = authorization.read_approval_record(
        approval_source_root=config.path("approval_source_root"),
        approval_source_identity=config.document["approval_source_identity"],
    )
    capability = authorization.open_verified_official_authorization(
        authorization_path=config.path("authorization_path"),
        independently_approved_digest=approval["approved_authorization_digest"],
        actual_observations=observed,
        approval_source_identity=config.document["approval_source_identity"],
        approval_source_root=config.path("approval_source_root"),
    )
    if capability.study_id != template["study_id"]:
        raise BenchError(BM_IDENTITY_INVALID, "the approval belongs to another experiment")
    if capability.freeze.profile_version != config.profile_version:
        raise BenchError(BM_IDENTITY_INVALID, "G0 and operation profiles differ", field_path="schema_version")
    if directory != config.path("workspace") / capability.run_id:
        raise BenchError(BM_IDENTITY_INVALID, "--out must be workspace/<approved-run-uuid>", field_path="out")
    # Refuse missing/stale executed QA before any timing; the coordinator repeats
    # this check at acceptance and publication to detect later changes.
    from .qa_evidence import verify_executed_qa_evidence
    framework_summary = read_canonical_json(config.path("framework_qa"))
    source_summary = read_canonical_json(config.path("source_qa"))
    for gate, summary in (("framework-qa", framework_summary), ("source-qa", source_summary)):
        coordinator._require_qa(summary, gate=gate, freeze=capability.freeze, roster_digest=coordinator.qa_roster_digest())
    verify_executed_qa_evidence(qa_evidence_root=config.path("qa_evidence_root"), framework_summary=framework_summary,
        source_summary=source_summary, freeze=capability.freeze, output_root=config.path("output_base"), raw_root=directory / "raw")
    if template["study_id"] == STUDY_RETAINED_KEY:
        require_retained_namespace(config.path("source_root"), directory)
        acquisition.require_retained_key_preconditions(capability.freeze, config.path("source_root"), runtime_context=runtime_context)
        pair = legacy_runner().cpus()
        if pair != (config.adapter_cpu, config.controller_cpu):
            raise BenchError(BM_IDENTITY_INVALID, "the configured CPU pair differs from the frozen backend selection", field_path="cpu_pair")
    host_preflight = None
    if config.profile_version == 2:
        host_preflight = observe_host(config, template)
        if content_digest(host_preflight) != capability.freeze.host_preflight_digest:
            raise BenchError(BM_IDENTITY_INVALID, "host changed during authorization", field_path="host_preflight_digest")
    return Operation(config, template, capability, prepared, observed, directory, runtime_context, config_path, host_preflight)


def _operation_record(operation: Operation) -> dict[str, Any]:
    document = {
        "kind": "official-operation", "schema_version": operation.config.profile_version,
        "study_id": operation.authorization.study_id, "run_id": operation.authorization.run_id,
        "authorization_digest": operation.authorization.freeze.authorization_digest,
        "design_digest": content_digest(dict(operation.template)),
        "observed_identity_digest": content_digest(dict(operation.observed)),
    }
    if operation.config.profile_version == 2:
        document.update(acceptance_profile=CURRENT_BASELINE_PROFILE,
                        baseline_id=operation.authorization.freeze.baseline_id)
    return document


def _outcome(operation: Operation, stage: str, data: Mapping[str, Any]) -> dict[str, Any]:
    baseline_fields = {} if operation.config.profile_version == 1 else {
        "acceptance_profile": CURRENT_BASELINE_PROFILE,
        "baseline_id": operation.authorization.freeze.baseline_id,
        "policy_verification_status": None, "complete_baseline_preserved": False,
        "clean_checkout_replay_verified": False,
    }
    return build_outcome("ok", BM_OK, f"official {stage} completed", {
        "kind": "official-operation-result", "schema_version": operation.config.profile_version,
        "study_id": operation.authorization.study_id, "run_id": operation.authorization.run_id,
        "evidence_origin": "real", "qualification_scope": "official", "stage": stage,
        "status": "UNVERIFIED", "raw_series_root_digest": None, "admission_digest": None,
        "analysis_digest": None, "policy_digest": None, "decision_status": None,
        "verification_status": None, "manifest_digest": None,
        "attestation_reopened": False, "accepted": False, **baseline_fields, **dict(data),
    })


def prepare_official(experiment: str, protocol_path: Path, out: Path, config_path: Path) -> dict[str, Any]:
    """Build once, then finalize identities after genuine source QA is available.

    Missing QA preserves a completed preparation without authorizing it. A later
    invocation may rehash that exact preparation, but never rebuild or repair an
    incomplete one. No invocation executes a timed adapter operation.
    """

    config = load_operation_config(Path(config_path))
    template = _template(experiment, Path(protocol_path), config)
    _preservation_root(config)
    target = absolute_path(str(Path(out).absolute()), "out")
    source = config.path("source_root")
    from ..evidence.provenance import repository_root
    if source.resolve() != repository_root().resolve():
        raise BenchError(BM_IDENTITY_INVALID, "preparation must use the executing checkout", field_path="source_root")
    source_commit, source_tree = git_identity(source)
    observe_host(config, template)
    if target == source or target in source.parents or (source in target.parents and source / "target" not in target.parents):
        raise BenchError(BM_UNSAFE_INPUT, "build preparation belongs in target or an external task directory", field_path="out")
    corpus = config.path("corpus_dir")
    if not corpus.exists() and (corpus == source or corpus in source.parents or (source in corpus.parents and source / "target" not in corpus.parents)):
        raise BenchError(BM_UNSAFE_INPUT, "new corpora belong in target or an external task directory", field_path="corpus_dir")
    filename = "prepared-cross-engine.json" if experiment == STUDY_CROSS_ENGINE else "prepared-retained-key.json"
    if config.path("prepared_manifest") != target / filename:
        raise BenchError(BM_IDENTITY_INVALID, "prepared_manifest must name the fixed manifest beneath --out", field_path="prepared_manifest")
    existed = os.path.lexists(target)
    if existed:
        if not config.path("prepared_manifest").is_file() or not (target / "preparation-inputs.json").is_file():
            raise BenchError(BM_PUBLICATION_CONFLICT,
                "an incomplete preparation cannot be resumed or rebuilt; preserve it and use a fresh path",
                field_path="out")
        prepared = _prepared(config, experiment)
    else:
        create_directory(target.parent)
        if experiment == STUDY_CROSS_ENGINE:
            from .cross_engine_backend import prepare_cross_engine
            prepared = prepare_cross_engine(root=source, build_root=target, corpus_dir=corpus)
        else:
            prepared = prepare_retained_key(root=source, build_root=target, corpus_dir=corpus)
    if git_identity(source) != (source_commit, source_tree):
        raise BenchError(BM_IDENTITY_INVALID, "source changed during preparation", field_path="source_commit")
    inputs = {
        "kind": "official-preparation-inputs", "schema_version": config.profile_version,
        "study_id": experiment, "source_root": str(source), "source_commit": source_commit,
        "source_tree_sha": source_tree, "design_digest": content_digest(dict(template)),
        "corpus_dir": str(corpus), "prepared_manifest": str(config.path("prepared_manifest")),
        "binary_manifest_digest": prepared.binary_digest,
    }
    if existed:
        if canonical_payload_bytes(read_canonical_json(target / "preparation-inputs.json")) != canonical_payload_bytes(inputs):
            raise BenchError(BM_IDENTITY_INVALID, "completed preparation inputs changed", field_path="preparation")
    else:
        write_record(target, "preparation-inputs.json", inputs)
    if config.profile_version == 2 and experiment == STUDY_RETAINED_KEY:
        from .runtime_freeze import prepare_current_runtime_freeze
        prepare_current_runtime_freeze(config=config, template=template, prepared=prepared)
    observations = _preparation_qa_observations(config, template, prepared.binary_digest)
    document = {
        "kind": "official-authorization-inputs", "schema_version": config.profile_version,
        "evidence_origin": "real", "qualification_scope": "official",
        "study_id": experiment, "status": "AWAITING_INDEPENDENT_G0_REVIEW",
        "observations": observations, "measurement_executed": False,
    }
    write_record(target, "authorization-inputs.json", document, reuse=True)
    return build_outcome("ok", BM_OK, "untimed preparation complete; independent G0 review is required", document)


def _preparation_qa_observations(config: OperationConfig, template: Mapping[str, Any], binary_digest: str) -> dict[str, Any]:
    """Check source QA identities without constructing authorization capabilities.

    The production opener still verifies all 66 members and their raw logs
    against G0. This preauthorization check prevents finalizing inputs with stale
    source summaries/check records and allows builds to precede their QA records.
    """

    from ..evidence.paths import require_safe_root
    from .contracts import validate_official_qa, FRAMEWORK_QA_ROSTER, SOURCE_QA_ROSTER
    from .qa_evidence import check_record_relative, MAX_CHECK_RECORD_BYTES
    try:
        summaries = {
            gate: validate_official_qa(read_canonical_json(config.path(field)), gate)
            for gate, field in (("framework-qa", "framework_qa"), ("source-qa", "source_qa"))
        }
        observed = observe_identities(config, template, binary_manifest_digest=binary_digest)
        root = require_safe_root(config.path("qa_evidence_root"))
        for gate, roster, pin in (
            ("framework-qa", FRAMEWORK_QA_ROSTER, "qa_framework_digest"),
            ("source-qa", SOURCE_QA_ROSTER, "qa_source_digest"),
        ):
            summary = summaries[gate]
            if summary["source_set_digest"] != observed["source_file_set_digest"] or summary["qa_roster_digest"] != coordinator.qa_roster_digest():
                raise BenchError(BM_IDENTITY_INVALID, "QA summary belongs to a different source or roster", field_path=gate)
            if content_digest(summary) != observed[pin]:
                raise BenchError(BM_IDENTITY_INVALID, "QA summary changed during preparation finalization", field_path=gate)
            for check_id, check in zip(roster, summary["checks"]):
                record = read_canonical_json(root / check_record_relative(gate, check_id), max_bytes=MAX_CHECK_RECORD_BYTES)
                if (record.get("source_commit") != observed["source_commit"]
                        or record.get("source_set_digest") != observed["source_file_set_digest"]
                        or record.get("qa_gate") != gate or record.get("check_id") != check_id
                        or content_digest(record) != check["evidence_digest"]):
                    raise BenchError(BM_IDENTITY_INVALID, "executed QA check differs from its source-bound summary", field_path=check_id)
        return observed
    except BenchError as error:
        if error.code == BM_UNSAFE_INPUT:
            raise
        raise BenchError(BM_EVIDENCE_UNAVAILABLE,
            "prepared inputs are preserved; complete current-source QA, then repeat prepare to finalize without rebuilding",
            field_path="qa_evidence") from error


def _readiness(operation: Operation) -> dict[str, Any]:
    requirements = operation.template["host_requirements"]
    limits = ReadinessLimits(**{name: requirements[name] for name in (
        "min_interval_ms", "max_interval_ms", "max_busy_permille",
        "max_median_busy_permille", "max_steal_permille", "min_intervals",
    )})
    record = controls.collect_real_readiness(
        study_id=operation.authorization.study_id,
        adapter_cpu=operation.config.adapter_cpu, controller_cpu=operation.config.controller_cpu,
        limits=limits, intervals=limits.min_intervals, interval_ms=1000,
    )
    write_record(operation.directory, "host-readiness.json", record)
    if (record["status"] != "READY"
            or not host_environment_matches(requirements["environment"], record["environment"])):
        raise BenchError(BM_EVIDENCE_UNAVAILABLE, "host readiness failed; this run is stopped and preserved", field_path="host_readiness")
    return record


def _invoke(operation: Operation, name: str, invocation: acquisition.BackendInvocation) -> None:
    if (operation.config.profile_version == 2 and operation.authorization.study_id == STUDY_RETAINED_KEY
            and (name.startswith("readiness-") or name.startswith("publish-"))):
        from .runtime_freeze import require_runtime_for_freeze
        freeze = authorization.require_verified_official_authorization(operation.authorization,
            study_id=STUDY_RETAINED_KEY, for_production=True, observed=operation.observed)
        require_runtime_for_freeze(operation.runtime_context, freeze, root=operation.config.path("source_root"))
    try:
        result = acquisition.run_backend(invocation)
    except BaseException as error:
        cause = error.__cause__
        captured_out = getattr(cause, "stdout", b"") or b""
        captured_err = getattr(cause, "stderr", b"") or b""
        if isinstance(captured_out, str):
            captured_out = captured_out.encode("utf-8", errors="replace")
        if isinstance(captured_err, str):
            captured_err = captured_err.encode("utf-8", errors="replace")
        write_record(operation.directory / "backend-records", name + ".json", {
            "kind": "official-backend-result", "schema_version": 1, "stage": name,
            "returncode": None, "invocation": invocation.summary(),
            "error_code": error.code if isinstance(error, BenchError) else "BM_INTERNAL_ERROR",
            "status": "STOPPED_PRESERVED",
            "stdout_tail": acquisition._truncate(captured_out),
            "stderr_tail": acquisition._truncate(captured_err),
        })
        raise
    write_record(operation.directory / "backend-records", name + ".json", {
        "kind": "official-backend-result", "schema_version": 1, "stage": name,
        "returncode": result.returncode, "invocation": invocation.summary(),
        "stdout_tail": result.stdout_tail, "stderr_tail": result.stderr_tail,
    })
    acquisition.require_backend_success(result, gate=name)


def _admit(operation: Operation) -> admission.VerifiedOfficialAdmission:
    common = {
        "raw_root": operation.raw_root, "authorization": operation.authorization,
        "template": operation.template, "source_root": operation.config.path("source_root"),
        "observed": operation.observed,
    }
    if operation.authorization.study_id == STUDY_CROSS_ENGINE:
        from .cross_engine_backend import verify_cross_engine_control
        control = verify_cross_engine_control(raw_root=operation.raw_root, prepared=operation.prepared,
            root=operation.config.path("source_root"), template=operation.template)
        capability = admission.admit_cross_engine_real(
            **common, corpus_dir=operation.config.path("corpus_dir"), control_document=control,
        )
    else:
        for campaign in (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES):
            verify_campaign_binaries(operation.raw_root / campaign, operation.prepared, control=campaign == D3C_CONTROL_NAME)
        capability = admission.admit_retained_key_real(**common)
    return capability


def run_official(experiment: str, protocol_path: Path, out: Path, config_path: Path) -> dict[str, Any]:
    """Acquire one complete authorized series, with no retries or path reuse."""

    config = load_operation_config(Path(config_path))
    template = _template(experiment, Path(protocol_path), config)
    directory = absolute_path(str(Path(out).absolute()), "out")
    state: dict[str, Any] = {}

    def authorize() -> Operation:
        operation = _open(config, template, directory, config_path=Path(config_path))
        create_directory(directory, exclusive=True)
        create_directory(config.path("output_base"))
        for name in ("raw", "backend-records", "events", "home"):
            create_directory(directory / name)
        os.chmod(directory / "home", 0o700)
        write_record(directory, "operation.json", _operation_record(operation))
        if operation.host_preflight is not None:
            write_record(directory, "host-preflight.json", operation.host_preflight)
            write_record(directory, "observed-identities.json", operation.observed)
        state["operation"] = operation
        state["journal"] = EventJournal(directory / "events")
        # Readiness and the isolated-home probe may fail before a raw campaign
        # starts. Their original G0/host/diagnostic bytes still need a STOPPED
        # preservation checkpoint; this assignment does not start a campaign.
        state["current_unit"] = "control" if experiment == STUDY_CROSS_ENGINE else D3C_CONTROL_NAME
        if experiment == STUDY_RETAINED_KEY:
            acquisition.probe_isolated_home(home=directory / "home")
            state["invocations"] = acquisition.retained_key_invocations(
                operation.authorization, root=config.path("source_root"), series_root=operation.raw_root,
                official_home=directory / "home", timeout_seconds=template["stopping"]["backend_timeout_seconds"], observed=operation.observed,
                runtime_context=operation.runtime_context,
            )
        return operation

    def checkpoint(unit: str, *, status: str = "COMPLETE") -> None:
        if config.profile_version == 2:
            from .transport import preserve_baseline_checkpoint
            preserve_baseline_checkpoint(config_path=Path(config_path), operation_root=directory, unit=unit, status=status)

    def control() -> Any:
        operation = state["operation"]
        state["current_unit"] = "control" if experiment == STUDY_CROSS_ENGINE else D3C_CONTROL_NAME
        if experiment == STUDY_CROSS_ENGINE:
            from .cross_engine_backend import acquire_cross_engine_control
            result = acquire_cross_engine_control(operation.authorization, root=config.path("source_root"), raw_root=operation.raw_root,
                prepared=operation.prepared, observed=operation.observed, adapter_cpu=config.adapter_cpu, controller_cpu=config.controller_cpu)
            checkpoint("control")
            return result
        for name in ("preflight", "readiness-control"):
            _invoke(operation, name, state["invocations"][name])
        from .retained_acquisition import acquire_retained_campaign
        acquire_retained_campaign(operation.authorization, root=config.path("source_root"),
            directory=operation.raw_root / D3C_CONTROL_NAME, campaign=D3C_CONTROL_NAME,
            prepared=operation.prepared, observed=operation.observed, official_home=directory / "home",
            runtime_context=operation.runtime_context)
        checkpoint(D3C_CONTROL_NAME)
        verify_campaign_binaries(operation.raw_root / D3C_CONTROL_NAME, operation.prepared, control=True)
        return None

    def control_verify() -> Any:
        operation = state["operation"]
        if experiment == STUDY_CROSS_ENGINE:
            from .cross_engine_backend import verify_cross_engine_control
            return verify_cross_engine_control(raw_root=operation.raw_root, prepared=operation.prepared,
                root=config.path("source_root"), template=template)
        for name in ("verify-control", "publish-control"):
            _invoke(operation, name, state["invocations"][name])
        return None

    def treatment() -> Any:
        operation = state["operation"]
        if experiment == STUDY_CROSS_ENGINE:
            state["current_unit"] = "treatment"
            from .cross_engine_backend import acquire_cross_engine_treatment
            result = acquire_cross_engine_treatment(operation.authorization, root=config.path("source_root"), raw_root=operation.raw_root,
                prepared=operation.prepared, observed=operation.observed, adapter_cpu=config.adapter_cpu, controller_cpu=config.controller_cpu)
            checkpoint("treatment")
            return result
        for campaign in D3C_CAMPAIGN_NAMES:
            state["current_unit"] = campaign
            name = "readiness-" + campaign
            _invoke(operation, name, state["invocations"][name])
            from .retained_acquisition import acquire_retained_campaign
            acquire_retained_campaign(operation.authorization, root=config.path("source_root"),
                directory=operation.raw_root / campaign, campaign=campaign,
                prepared=operation.prepared, observed=operation.observed, official_home=directory / "home",
                runtime_context=operation.runtime_context)
            checkpoint(campaign)
            verify_campaign_binaries(operation.raw_root / campaign, operation.prepared, control=False)
            for name in ("verify-" + campaign, "publish-" + campaign):
                _invoke(operation, name, state["invocations"][name])
        _invoke(operation, "verify-series", state["invocations"]["verify-series"])
        return None

    def admit() -> admission.VerifiedOfficialAdmission:
        value = _admit(state["operation"])
        write_record(directory, "admission-index.json", value.record.admission_index)
        return value

    callbacks = {"authorize": authorize, "readiness": lambda: _readiness(state["operation"]),
        "control": control, "control-verify": control_verify, "treatment": treatment, "admission": admit}
    try:
        results = execute_stages("official-acquisition", callbacks, on_event=lambda event: state["journal"](event) if "journal" in state else None)
    except BaseException as primary:
        if "operation" in state:
            try:
                write_record(directory, "stopped.json", {"kind": "official-operation-stopped", "schema_version": 1, "retry_allowed": False})
                if "current_unit" in state:
                    checkpoint(state["current_unit"], status="STOPPED")
            except BaseException as preservation_error:
                # Do not replace the actual acquisition/verifier failure with a
                # secondary filesystem/export failure. Both remain observable.
                try:
                    write_record(directory, "preservation-failure.json", {
                        "kind": "official-preservation-failure", "schema_version": 1,
                        "error_code": preservation_error.code if isinstance(preservation_error, BenchError) else "BM_INTERNAL_ERROR",
                        "primary_error_preserved": True,
                    })
                except BaseException:
                    pass
        raise
    operation = state["operation"]
    raw_digest = results["admission"].record.raw_series_root_digest
    write_record(directory, "sealed.json", {"kind": "official-raw-series-sealed", "schema_version": 1, "raw_series_root_digest": raw_digest})
    return _outcome(operation, "run", {"status": "REAL_EVIDENCE_SEALED", "raw_series_root_digest": raw_digest, "accepted": False})


def _policy_inputs(operation: Operation, admitted: admission.VerifiedOfficialAdmission) -> Any:
    spec = operation.config.document["policy_inputs"]
    if operation.authorization.study_id != STUDY_RETAINED_KEY or spec is None:
        return None
    from .policy_inputs import open_retained_policy_inputs
    return open_retained_policy_inputs(admitted=admitted, authorization=operation.authorization,
        template=operation.template, source_root=operation.config.path("source_root"),
        micro_json=Path(spec["micro_json"]), expected_micro_sha256=spec["expected_micro_sha256"],
        f1_receipt=Path(spec["f1_receipt"]), observed=operation.observed)


def _parity(operation: Operation) -> historical.VerifiedHistoricalParity:
    spec = operation.config.document["historical_parity"]
    if spec is None:
        raise BenchError(BM_EVIDENCE_UNAVAILABLE, "acceptance requires independently approved historical parity", field_path="historical_parity")
    approval, _ = historical._read_parity_approval(approval_source_root=Path(spec["approval_source_root"]), identity=spec["approval_source_identity"])
    return historical.open_verified_historical_parity(study_id=operation.authorization.study_id,
        archive_root=Path(spec["archive_root"]), mapping_path=Path(spec["mapping_path"]),
        independently_approved_mapping_digest=approval["approved_mapping_digest"],
        approval_source_root=Path(spec["approval_source_root"]), approval_source_identity=spec["approval_source_identity"],
        repo_root=operation.config.path("source_root"))


def dispatch_official_stage(verb: str, run_id: str, config_path: Path) -> dict[str, Any]:
    """Re-admit persisted raw bytes for every stage, then derive rather than trust."""

    if verb not in ("validate", "analyze", "verify", "accept", "report"):
        raise BenchError(BM_USAGE, "unknown official stage")
    run = validate_uuid4(run_id, "run_id")
    config = load_operation_config(Path(config_path))
    directory = config.path("workspace") / run
    declaration = read_canonical_json(directory / "operation.json")
    experiment = declaration.get("study_id")
    template = _template(experiment, template_path(experiment, config.path("source_root"), version=config.profile_version), config)
    state: dict[str, Any] = {}

    def authorize() -> Operation:
        operation = _open(config, template, directory, config_path=Path(config_path))
        if canonical_payload_bytes(declaration) != canonical_payload_bytes(_operation_record(operation)):
            raise BenchError(BM_IDENTITY_INVALID, "operation inputs changed since acquisition", field_path="operation")
        if (directory / "stopped.json").exists():
            raise BenchError(BM_EVIDENCE_UNAVAILABLE, "a stopped acquisition cannot be resumed", field_path="operation")
        state["operation"] = operation
        return operation

    def admit() -> Any:
        capability = _admit(state["operation"])
        seal = read_canonical_json(directory / "sealed.json")
        if seal.get("raw_series_root_digest") != capability.record.raw_series_root_digest:
            raise BenchError(BM_IDENTITY_INVALID, "raw bytes differ from the sealed series", field_path="raw_series_root_digest")
        write_record(directory, "admission-index.json", capability.record.admission_index, reuse=True)
        state["admitted"] = capability
        return capability

    def analyze() -> tuple[dict[str, Any], dict[str, Any]]:
        operation = state["operation"]
        policy_inputs = _policy_inputs(operation, state["admitted"])
        if (config.profile_version == 1 and operation.authorization.study_id == STUDY_RETAINED_KEY
                and policy_inputs is None):
            # A placeholder v1 policy cannot later be replaced by the complete
            # v2 policy in this append-only operation directory. Keep the sealed
            # raw run usable when the authentic policy inputs arrive instead of
            # committing a permanently underivable analysis attempt.
            raise BenchError(BM_EVIDENCE_UNAVAILABLE,
                "retained-key analysis requires authentic policy inputs; the sealed run is preserved",
                field_path="policy_inputs")
        state["policy_inputs"] = policy_inputs
        try:
            documents = analysis.analyze_official_study(admitted=state["admitted"].record, template=template, policy_inputs=policy_inputs)
        except BenchError as error:
            if (config.profile_version == 2 and error.code == BM_EVIDENCE_UNAVAILABLE
                    and error.field_path == "retained_slot_statistics"
                    and error.message == "current baseline has insufficient symmetric retained blocks"):
                write_record(directory, "analysis-blocked.json", {
                    "kind": "official-baseline-analysis-blocked", "schema_version": 2,
                    "status": "BLOCKED", "study_id": experiment, "run_id": run,
                    "raw_series_root_digest": state["admitted"].record.raw_series_root_digest,
                    "error_code": error.code, "field_path": error.field_path,
                    "reason": error.message, "measurement_retry_allowed": False,
                }, reuse=True)
            raise
        for name, document in zip(("analysis.json", "policy.json"), documents):
            write_record(directory, name, document, reuse=True)
        state["analysis"], state["policy"] = documents
        return documents

    def verify() -> dict[str, Any]:
        operation = state["operation"]
        assessment = verification.verify_official_study(admitted=state["admitted"].record, template=template,
            authorization=operation.authorization, analysis=state["analysis"], policy=state["policy"],
            source_root=config.path("source_root"), observed=operation.observed, admission=state["admitted"], policy_inputs=state["policy_inputs"])
        write_record(directory, "verification-assessment.json", assessment, reuse=True)
        state["assessment"] = assessment
        expected_status = "VERIFIED_CURRENT_BASELINE" if config.profile_version == 2 else "VERIFIED_REAL"
        if assessment["status"] != expected_status:
            raise BenchError(BM_EVIDENCE_UNAVAILABLE, "the real verification gate is blocked", field_path="verification_status")
        if config.profile_version == 2:
            from .history import write_baseline_disclosures
            state["baseline_context"] = write_baseline_disclosures(operation_root=directory,
                config_path=Path(config_path), authorization=operation.authorization,
                admission=state["admitted"], policy_inputs=state["policy_inputs"])
        return assessment

    def accept() -> coordinator.OfficialQualificationResult:
        operation = state["operation"]
        parity = _parity(operation) if config.profile_version == 1 else None
        result = coordinator.qualify_official_study(authorization=operation.authorization, template=template,
            admitted=state["admitted"], framework_qa=read_canonical_json(config.path("framework_qa")),
            source_qa=read_canonical_json(config.path("source_qa")), historical_parity=parity,
            output_base=config.path("output_base"), qa_evidence_root=config.path("qa_evidence_root"),
            source_root=config.path("source_root"), observed=operation.observed, publish=verb == "accept", policy_inputs=state["policy_inputs"],
            baseline_context=state.get("baseline_context"))
        state["qualification"] = result
        return result

    def attest() -> publication.OfficialBundle:
        result = state["qualification"]
        operation = state["operation"]
        reopen_inputs = {} if config.profile_version == 1 else {
            "authorization": operation.authorization, "observed": operation.observed,
            "baseline_context": state["baseline_context"],
        }
        bundle = publication.load_official_bundle(output_base=config.path("output_base"), study_id=experiment,
            run_id=run, anchors=result.anchors, **reopen_inputs)
        if bundle.manifest_digest != result.manifest_digest:
            raise BenchError(BM_IDENTITY_INVALID, "the published bundle differs from the independently rederived result", field_path="manifest_digest")
        if config.profile_version == 2 and verb == "accept":
            from .transport import preserve_baseline_checkpoint, baseline_ready_for_finalization, finalize_baseline_evidence
            preserve_baseline_checkpoint(config_path=Path(config_path), operation_root=directory,
                unit="qualification", baseline_context=state["baseline_context"])
            baseline_root = Path(config.document["baseline"]["evidence_root"])
            if baseline_ready_for_finalization(baseline_root=baseline_root):
                state["preserved"] = finalize_baseline_evidence(baseline_root=baseline_root)
        return bundle

    callbacks = {"authorize": authorize, "admission": admit, "analysis": analyze, "verification": verify, "acceptance": accept, "attestation": attest}
    if verb == "validate":
        # Validation uses the same authorization/admission pair, without requiring
        # policy inputs or acceptance material that may arrive later.
        result = execute_stages("official-validation", {"authorize": authorize, "admission": admit})["admission"]
        return _outcome(state["operation"], verb, {"status": "ADMITTED_REAL", "admission_digest": content_digest(result.record.admission_index)})
    plan = "official-analysis" if verb == "analyze" else "official-verification" if verb == "verify" else "official-acceptance"
    selected = ("authorize", "admission", "analysis") if verb == "analyze" else ("authorize", "admission", "analysis", "verification") if verb == "verify" else tuple(callbacks)
    results = execute_stages(plan, {name: callbacks[name] for name in selected})
    if verb == "analyze":
        data = {"status": "ANALYZED_REAL", "analysis_digest": content_digest(state["analysis"]),
                "policy_digest": content_digest(state["policy"]), "decision_status": state["policy"]["decision_status"]}
    elif verb == "verify":
        data = {"status": results["verification"]["status"], "verification_status": results["verification"]["status"],
                "analysis_digest": content_digest(state["analysis"]), "policy_digest": content_digest(state["policy"]),
                "decision_status": state["policy"]["decision_status"]}
    else:
        result = results["attestation"]
        data = {"status": "CURRENT_BASELINE_QUALIFIED" if config.profile_version == 2 else "REAL_OFFICIAL_QUALIFIED", "manifest_digest": result.manifest_digest,
                "attestation_reopened": True, "accepted": True, "policy_digest": content_digest(state["policy"]),
                "decision_status": state["policy"]["decision_status"], "verification_status": state["assessment"]["status"]}
    if config.profile_version == 2:
        data.update(acceptance_profile=CURRENT_BASELINE_PROFILE,
                    baseline_id=config.document["baseline"]["baseline_id"],
                    policy_verification_status=state.get("assessment", {}).get("policy_verification_status"),
                    complete_baseline_preserved="preserved" in state,
                    clean_checkout_replay_verified=False)
    return _outcome(state["operation"], verb, data)
