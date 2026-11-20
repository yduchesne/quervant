"""Observe G0 identities from the actual checkout, inputs, binaries and host.

The authorization document is deliberately not an input to this module. A caller
cannot make an observation true by copying a digest from a candidate approval.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import content_digest
from ..config.errors import BM_EVIDENCE_UNAVAILABLE, BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from ..evidence.hashing import sha256_regular_file
from ..evidence.provenance import require_clean_head, repository_root
from ..host.capabilities import LinuxCapabilityProvider, collect_host_capabilities
from ..qualification.identity import compute_source_set_digest, require_repository_root
from .admission import _adapter_source_digest, load_pr15d_oracle
from .analysis import policy_profile_digest
from .operation_config import OperationConfig
from .protocols import CURRENT_BASELINE_PROFILE, STUDY_CROSS_ENGINE, host_environment_matches, read_canonical_json, validate_template, verify_backend_protocol


def git_identity(root: Path) -> tuple[str, str]:
    require_repository_root(root)
    require_clean_head(root)
    values = []
    for ref in ("HEAD", "HEAD^{tree}"):
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", ref],
            capture_output=True, check=False, timeout=30,
        )
        if result.returncode:
            raise BenchError(BM_EVIDENCE_UNAVAILABLE, "the frozen source identity is unavailable")
        values.append(result.stdout.decode("ascii").strip())
    return values[0], content_digest({"kind": "official-git-tree", "schema_version": 1, "git_tree": values[1]})


def observe_host(config: OperationConfig, template: Mapping[str, Any]) -> dict[str, Any]:
    capabilities = collect_host_capabilities(LinuxCapabilityProvider())
    if (not host_environment_matches(template["host_requirements"]["environment"], capabilities["environment"])
            or capabilities["missing_fields"]):
        raise BenchError(BM_EVIDENCE_UNAVAILABLE, "official execution requires complete capabilities matching the reviewed host environment", field_path="host")
    allowed = capabilities["allowed_cpus"]
    cpus = (config.adapter_cpu, config.controller_cpu)
    if any(type(cpu) is not int or cpu not in allowed for cpu in cpus):
        raise BenchError(BM_UNSAFE_INPUT, "the selected CPU pair is outside the allowed affinity", field_path="cpu_pair")
    topology = {row["cpu"]: (row["package_id"], row["core_id"]) for row in capabilities["cpu_topology"]}
    if topology[cpus[0]] == topology[cpus[1]]:
        raise BenchError(BM_UNSAFE_INPUT, "the selected CPUs share a physical core", field_path="cpu_pair")
    return {
        "kind": "official-host-preflight", "schema_version": 1,
        "capabilities": capabilities, "adapter_cpu": cpus[0], "controller_cpu": cpus[1],
    }


def observe_identities(
    config: OperationConfig, template: Mapping[str, Any], *, binary_manifest_digest: str,
) -> dict[str, Any]:
    """Compute the complete observation set; binary loader has already rehashed files."""

    template = validate_template(template)
    if config.profile_version != template["schema_version"]:
        raise BenchError(BM_IDENTITY_INVALID, "configuration and template versions differ", field_path="schema_version")
    root = config.path("source_root")
    if root.resolve() != repository_root().resolve():
        raise BenchError(BM_IDENTITY_INVALID, "the operator must execute from the configured checkout", field_path="source_root")
    commit, tree = git_identity(root)
    backend = verify_backend_protocol(template, root)
    oracle = load_pr15d_oracle()
    corpus_manifest, _rows = oracle.load_and_verify(str(config.path("corpus_dir")))
    corpus_digest = "sha256:" + oracle.sha256_bytes(oracle.canonical_json_bytes(corpus_manifest))
    verifier = "benchmarks/pr15d/harness/validate.py" if template["study_id"] == STUDY_CROSS_ENGINE else "benchmarks/pr15i_d3_c/verify.py"
    verifier_digest, _ = sha256_regular_file(root, verifier, max_bytes=8_388_608)
    schedule = template["schedule"]
    control_schedule = {key: value for key, value in schedule.items() if key.startswith("control_")}
    treatment_schedule = {key: value for key, value in schedule.items() if not key.startswith("control_")}
    observations = {
        "design_digest": content_digest(dict(template)),
        "backend_protocol_digest": backend["raw_digest"],
        "source_commit": commit,
        "source_file_set_digest": compute_source_set_digest(root),
        "source_tree_sha": tree,
        "adapter_source_manifest_digest": _adapter_source_digest(root),
        "binary_manifest_digest": binary_manifest_digest,
        "corpus_manifest_digest": corpus_digest,
        "original_reference_verifier_digest": verifier_digest,
        "host_preflight_digest": content_digest(observe_host(config, template)),
        "control_schedule_digest": content_digest(control_schedule),
        "treatment_schedule_digest": content_digest(treatment_schedule),
        "qa_source_digest": content_digest(read_canonical_json(config.path("source_qa"))),
        "qa_framework_digest": content_digest(read_canonical_json(config.path("framework_qa"))),
        "policy_digest": policy_profile_digest(template["study_id"], template["policy"]["policy_chain"]),
        "output_root_identity": str(config.path("output_base")),
    }
    if config.profile_version == 2:
        baseline = config.document["baseline"]
        runtime_digest = None
        if template["study_id"] != STUDY_CROSS_ENGINE:
            from .runtime_freeze import open_current_runtime_freeze

            runtime = open_current_runtime_freeze(config=config, template=template)
            if runtime.document["binary_manifest_digest"] != binary_manifest_digest:
                raise BenchError(BM_IDENTITY_INVALID, "runtime binaries differ from the observed preparation", field_path="binary_manifest_digest")
            runtime_digest = runtime.digest
        elif baseline["runtime_freeze_path"] is not None or config.document["policy_inputs"] is not None:
            raise BenchError(BM_UNSAFE_INPUT, "cross-engine cannot consume retained-only inputs", field_path="baseline.runtime_freeze_path")
        observations.update({
            "acceptance_profile": CURRENT_BASELINE_PROFILE,
            "baseline_id": baseline["baseline_id"],
            "preservation_root_identity": baseline["evidence_root"],
            "runtime_freeze_digest": runtime_digest,
        })
    return observations
