"""Thin read-only BM-08 cross-engine reference and its synthetic qualification.

This module owns exactly four things:

1. the frozen public experiment identifier and the exact checked-in catalog
   layout (eleven regular files, no more and no fewer);
2. a validating loader that binds the three cross-engine companion documents to
   the BM-01 experiment/workload/protocol digests and to the original PR15D
   adapter source bytes;
3. one thin qualification wrapper that calls the *unchanged* BM-03 controller and
   the *unchanged* BM-06 coordinator in the prescribed order, revalidating the
   companion ledger before and after the run;
4. nothing else. There is no scheduler, statistics, verifier, publisher, CLI verb
   or timing harness here.

The ``quervant``/``tantivy``/``lucene`` arms are declared logical sample-stream
labels bound to the one BM-03 ``synthetic-execution`` simulator. They are never
real engines, builds or measured performance comparisons.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analysis.policy import (
    read_policy_profile,
    read_resource_observations,
)
from ..analysis.profiles import read_analysis_profile
from ..config.codec import (
    canonical_document_bytes,
    content_digest,
    decode_text,
    loads_json,
)
from ..config.contracts import ExperimentBundle, load_experiment_bundle
from ..config.errors import (
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..evidence.paths import open_regular_beneath, require_safe_root
from ..execution.controller import (
    ScenarioReadinessProvider,
    SimulatedCapabilityProvider,
    execute_synthetic,
)
from ..execution.clock import LogicalClock
from ..execution.scenario import load_synthetic_scenario, validate_scenario_document
from ..execution.synthetic import synthetic_adapter_factory
from ..qualification.coordinator import (
    QualificationResult,
    qualify_synthetic_run,
)
from .cross_engine_contract import (
    ARM_IDS,
    BASELINE_ARM_ID,
    CANDIDATE_ORDER,
    ENGINE_SOURCE_BINDINGS_NAME,
    LANE_PARAM_KEYS,
    ORACLE_GOLDEN_NAME,
    ORACLE_ID,
    ORACLE_VERSION,
    QUERY_SEMANTICS_ID,
    SEMANTIC_COMPARABILITY_NAME,
    expected_lane_ids,
    oracle_row_for_lane,
    validate_engine_source_bindings,
    validate_oracle_golden,
    validate_semantic_comparability,
)

#: Frozen public semantic experiment identifier for the BM-08 reference study.
REFERENCE_EXPERIMENT_ID = "synthetic-cross-engine-reference"

SYNTHETIC_ADAPTER_ID = "synthetic-execution"
SYNTHETIC_ENGINE_ID = "synthetic"
EXPECTED_WORKLOAD_ID = "cross-engine-synthetic-keyword"
EXPECTED_DATASET_ID = "cross-engine-semantic-ledger"
EXPECTED_FIXTURE_SCHEMA = "cross-engine-semantic-ledger"
EXPECTED_PROTOCOL_ID = "cross-engine-synthetic-paired"

#: Exact checked-in catalog file layout; the checked-in bytes are the authority.
REQUIRED_CATALOG_FILES: tuple[str, ...] = (
    "adapter.yaml",
    "analysis-profile.v1.json",
    "engine-source-bindings.v1.json",
    "experiment.yaml",
    "oracle-golden.v1.json",
    "policy-profile.v1.json",
    "protocol.yaml",
    "resource-observations.v1.json",
    "semantic-comparability.v1.json",
    "synthetic-scenario.v1.json",
    "workloads.yaml",
)

MAX_COMPANION_BYTES = 1_048_576
REFERENCE_SPEC_RELATIVE = "benchmarks/pr15d/spec/pr15d_v1.json"


def _schema(message: str, field_path: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


def _fail(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


@dataclass(frozen=True)
class CrossEngineCompanionDigests:
    """The immutable companion digest tuple binding one catalog revision."""

    reference_spec_digest: str
    oracle_golden_digest: str
    engine_source_bindings_digest: str
    semantic_comparability_digest: str


def reference_catalog_root(repo_root: Path | None = None) -> Path:
    """Return the catalog root that contains the cross-engine reference."""

    if repo_root is None:
        from ..evidence.provenance import repository_root

        root = repository_root()
    else:
        root = repo_root
    return Path(root) / "benchmarks" / "experiments"


def _require_exact_catalog_files(experiment_root: Path) -> None:
    """Reject any missing, extra, symlinked or non-regular catalog entry."""

    try:
        names = sorted(os.listdir(experiment_root))
    except FileNotFoundError as exc:
        raise BenchError(
            BM_FILE_MISSING,
            "the cross-engine reference catalog directory is missing",
            reference=REFERENCE_EXPERIMENT_ID,
        ) from exc
    except OSError as exc:  # pragma: no cover - defensive
        raise BenchError(
            BM_UNSAFE_INPUT, "the cross-engine reference catalog cannot be listed"
        ) from exc
    if tuple(names) != REQUIRED_CATALOG_FILES:
        extra = sorted(set(names) - set(REQUIRED_CATALOG_FILES))
        missing = sorted(set(REQUIRED_CATALOG_FILES) - set(names))
        raise _fail(
            "the cross-engine catalog must contain exactly the eleven frozen files "
            f"(missing={missing}, extra={extra})",
            "catalog",
        )
    for name in names:
        info = os.lstat(experiment_root / name)
        if stat.S_ISLNK(info.st_mode):
            raise BenchError(
                BM_UNSAFE_INPUT,
                "cross-engine catalog entries must not be symbolic links",
                reference=name,
            )
        if not stat.S_ISREG(info.st_mode):
            raise BenchError(
                BM_UNSAFE_INPUT,
                "cross-engine catalog entries must be regular files",
                reference=name,
            )


def _read_bounded_bytes(root: Path, relative: str, maximum: int) -> bytes:
    handle = open_regular_beneath(root, relative)
    with handle:
        payload = handle.read(maximum + 1)
    if len(payload) > maximum:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "a cross-engine document exceeds its bounded read budget",
            reference=relative,
        )
    return payload


def _read_canonical_document(root: Path, relative: str) -> Mapping[str, Any]:
    payload = _read_bounded_bytes(root, relative, MAX_COMPANION_BYTES)
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "cross-engine documents must be stored in canonical byte form",
            reference=relative,
        )
    if not isinstance(document, Mapping):
        raise _schema("a cross-engine document must be an object", relative)
    return document


def _read_reference_spec(repo_root: Path) -> Mapping[str, Any]:
    payload = _read_bounded_bytes(
        repo_root, REFERENCE_SPEC_RELATIVE, MAX_COMPANION_BYTES
    )
    document = loads_json(decode_text(payload))
    if not isinstance(document, Mapping):
        raise _schema("the frozen PR15D reference spec must be an object", "spec")
    if document.get("schema") != "pr15d-spec-v1":
        raise _fail("the frozen PR15D reference spec identity is unexpected", "spec")
    return document


def load_cross_engine_reference(catalog_root: Path) -> ExperimentBundle:
    """Load the cross-engine reference bundle through the frozen BM-01 loader."""

    if not isinstance(catalog_root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "catalog_root must be a Path",
            field_path="catalog_root",
        )
    require_safe_root(catalog_root)
    experiment_root = catalog_root / REFERENCE_EXPERIMENT_ID
    _require_exact_catalog_files(experiment_root)
    return load_experiment_bundle(REFERENCE_EXPERIMENT_ID, catalog_root)


def validate_cross_engine_reference(
    catalog_root: Path, repo_root: Path
) -> tuple[ExperimentBundle, CrossEngineCompanionDigests]:
    """Fully validate one catalog revision and its bounded digest chain.

    The returned bundle and digest tuple are the only accepted authority. This
    function never caches state and never repairs a digest.
    """

    bundle = load_cross_engine_reference(catalog_root)
    if not isinstance(repo_root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT, "repo_root must be a Path", field_path="repo_root"
        )
    require_safe_root(repo_root)
    experiment_root = catalog_root / REFERENCE_EXPERIMENT_ID

    golden = _read_canonical_document(experiment_root, ORACLE_GOLDEN_NAME)
    rows = validate_oracle_golden(golden)
    golden_by_lane = {row["lane_id"]: row for row in rows}

    bindings = _read_canonical_document(experiment_root, ENGINE_SOURCE_BINDINGS_NAME)
    engine_source_bindings_digest = validate_engine_source_bindings(repo_root, bindings)

    ledger = _read_canonical_document(experiment_root, SEMANTIC_COMPARABILITY_NAME)
    workload_lane_ids = [lane.lane_id for lane in bundle.workload.lanes]
    semantic_comparability_digest = validate_semantic_comparability(
        ledger,
        workload_lane_ids=workload_lane_ids,
        oracle_golden_digest=content_digest(dict(golden)),
        engine_source_bindings_digest=engine_source_bindings_digest,
        reference_spec_digest=content_digest(dict(_read_reference_spec(repo_root))),
    )

    # --- experiment identity -------------------------------------------------
    experiment = bundle.experiment
    if experiment.experiment_id != REFERENCE_EXPERIMENT_ID:
        raise _fail(
            "the loaded experiment is not the cross-engine reference",
            "experiment_id",
        )
    if tuple(arm.arm_id for arm in experiment.arms) != ARM_IDS:
        raise _fail(
            "the experiment arms must be exactly quervant, tantivy, lucene",
            "arms",
        )
    for arm in experiment.arms:
        if arm.adapter_id != SYNTHETIC_ADAPTER_ID or arm.variant != arm.arm_id:
            raise _fail(
                "every arm must bind the synthetic-execution simulator label",
                "arms",
            )

    # --- adapter: one simulator, never a real engine -------------------------
    adapter = bundle.adapter
    if (
        adapter.adapter_id != SYNTHETIC_ADAPTER_ID
        or adapter.engine_id != SYNTHETIC_ENGINE_ID
        or adapter.build_identity.kind != "synthetic"
    ):
        raise _fail(
            "the cross-engine reference may only declare the synthetic simulator",
            "adapter",
        )
    if tuple(adapter.operations) != ("search",):
        raise _fail("the synthetic simulator declares only search", "adapter.operations")
    if tuple(adapter.cache_regimes) != ("warm",):
        raise _fail(
            "the measured matrix is warm-only", "adapter.cache_regimes"
        )
    if adapter.oracle_semantics_id != QUERY_SEMANTICS_ID:
        raise _fail(
            "adapter oracle semantics must be the frozen exact-keyword contract",
            "adapter.oracle_semantics_id",
        )

    # --- workload: exact frozen matrix --------------------------------------
    workload = bundle.workload
    if workload.workload_id != EXPECTED_WORKLOAD_ID:
        raise _fail("unexpected cross-engine workload identity", "workload_id")
    if workload.query_semantics_id != QUERY_SEMANTICS_ID:
        raise _fail(
            "workload query semantics must be the frozen exact-keyword contract",
            "query_semantics_id",
        )
    if (
        workload.oracle_id != ORACLE_ID
        or workload.oracle_version != ORACLE_VERSION
    ):
        raise _fail("unexpected cross-engine oracle identity", "oracle_id")
    if (
        workload.dataset.dataset_id != EXPECTED_DATASET_ID
        or workload.dataset.fixture_schema != EXPECTED_FIXTURE_SCHEMA
    ):
        raise _fail(
            "the workload dataset must bind the semantic comparability ledger",
            "dataset",
        )
    if workload.dataset.digest != semantic_comparability_digest:
        raise _fail(
            "workload.dataset.digest must equal the semantic comparability digest",
            "dataset.digest",
        )

    if tuple(workload_lane_ids) != expected_lane_ids():
        raise _fail(
            "the workload must declare exactly the 16 sorted warm keyword lanes",
            "lanes",
        )
    for lane in workload.lanes:
        row = oracle_row_for_lane(lane)
        if dict(lane.params) != {
            key: row[key] if key != "query_id" else lane.lane_id
            for key in LANE_PARAM_KEYS
        }:
            raise _fail(
                "a lane declares parameters outside the frozen matrix", "lanes"
            )
        reviewed = golden_by_lane[lane.lane_id]
        for field in ("corpus_size", "top_k", "selectivity_class", "field", "term"):
            if row[field] != reviewed[field]:
                raise _fail(
                    "the declared lane disagrees with the reviewed oracle golden",
                    f"lanes[{lane.lane_id}].{field}",
                )
        if row["total_hits"] != reviewed["total_hits"]:
            raise _fail(
                "the declared lane total_hits disagrees with the oracle golden",
                "lanes",
            )
        if row["doc_ids"] != reviewed["doc_ids"]:
            raise _fail(
                "the declared lane doc_ids disagree with the oracle golden", "lanes"
            )

    # --- protocol identity and digest binding -------------------------------
    protocol = bundle.protocol
    if protocol.protocol_id != EXPECTED_PROTOCOL_ID:
        raise _fail("unexpected cross-engine protocol identity", "protocol_id")
    if protocol.workload_digest != content_digest(dict(bundle.workload_document)):
        raise _fail(
            "protocol.workload_digest must equal the canonical workload digest",
            "protocol.workload_digest",
        )

    # --- catalog-resident profiles and scenario must be digest-bound --------
    read_analysis_profile(experiment_root, bundle)
    read_policy_profile(experiment_root, bundle)
    read_resource_observations(experiment_root, bundle)
    scenario_document = _read_canonical_document(
        experiment_root, "synthetic-scenario.v1.json"
    )
    validate_scenario_document(dict(scenario_document), bundle=bundle)

    return bundle, CrossEngineCompanionDigests(
        reference_spec_digest=content_digest(dict(_read_reference_spec(repo_root))),
        oracle_golden_digest=content_digest(dict(golden)),
        engine_source_bindings_digest=engine_source_bindings_digest,
        semantic_comparability_digest=semantic_comparability_digest,
    )


def qualify_cross_engine_synthetic(
    *,
    catalog_root: Path,
    source_root: Path,
    run_id: str,
    scenario_root: Path,
    run_output_base: Path,
    qualification_output_base: Path,
    qualification_profile_path: Path,
    qa_evidence_root: Path,
    expected_profile_digest: str,
    expected_framework_qa_digest: str,
    expected_source_qa_digest: str,
    expected_source_set_digest: str,
) -> QualificationResult:
    """Execute and qualify one cross-engine synthetic run through existing APIs.

    The sequence is fixed: validate the catalog, load the scenario, execute the
    BM-03 synthetic simulator, require a sealed run, qualify with the unchanged
    BM-06 coordinator, then revalidate the identical companion digest tuple before
    returning anything. A failed post-publication revalidation is never reported
    as a pass.
    """

    bundle, digests = validate_cross_engine_reference(catalog_root, source_root)
    scenario = load_synthetic_scenario(scenario_root, bundle=bundle)
    execution = execute_synthetic(
        bundle=bundle,
        scenario=scenario,
        run_id=run_id,
        evidence_root=scenario_root,
        output_base=run_output_base,
        adapter_factory=synthetic_adapter_factory(bundle),
        capability_provider=SimulatedCapabilityProvider(),
        readiness_provider=ScenarioReadinessProvider(scenario),
        clock=LogicalClock(),
    )
    if execution.status != "sealed":
        raise _fail(
            f"the synthetic run did not seal ({execution.reason}); "
            "no qualification was published",
            "execution.status",
        )
    result = qualify_synthetic_run(
        bundle=bundle,
        run_dir=execution.run_dir,
        scenario_root=scenario_root,
        profiles_root=catalog_root / REFERENCE_EXPERIMENT_ID,
        resources_root=catalog_root / REFERENCE_EXPERIMENT_ID,
        qualification_profile_path=qualification_profile_path,
        qa_evidence_root=qa_evidence_root,
        expected_profile_digest=expected_profile_digest,
        expected_framework_qa_digest=expected_framework_qa_digest,
        expected_source_qa_digest=expected_source_qa_digest,
        source_root=source_root,
        expected_source_set_digest=expected_source_set_digest,
        output_base=qualification_output_base,
    )
    revalidated_bundle, revalidated = validate_cross_engine_reference(
        catalog_root, source_root
    )
    if revalidated != digests or (
        revalidated_bundle.experiment.experiment_id
        != bundle.experiment.experiment_id
    ):
        raise _fail(
            "the cross-engine ledger or source bindings changed during qualification",
            "semantic-comparability",
        )
    return result


__all__ = [
    "CrossEngineCompanionDigests",
    "REFERENCE_EXPERIMENT_ID",
    "REQUIRED_CATALOG_FILES",
    "load_cross_engine_reference",
    "qualify_cross_engine_synthetic",
    "reference_catalog_root",
    "validate_cross_engine_reference",
]
