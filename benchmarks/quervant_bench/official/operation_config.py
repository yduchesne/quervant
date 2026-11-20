"""Closed local configuration for the official operator workflow.

Configuration locates inputs. It never supplies an authorization, an observed
digest, a successful gate, an executable command, or a retry policy. Every such
identity is obtained again from its owning reader before a stage can run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config.errors import BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError
from ..config.identity import validate_semantic_id, validate_uuid4
from ..evidence.paths import require_safe_root
from ..qualification.contracts import require_closed
from .contracts import CURRENT_BASELINE_PROFILE, require_profile_version
from .protocols import read_canonical_json

CONFIG_KIND = "official-operation-config"
_PATHS = (
    "source_root", "workspace", "output_base", "authorization_path",
    "approval_source_root", "prepared_manifest", "corpus_dir", "framework_qa",
    "source_qa", "qa_evidence_root",
)
CONFIG_KEYS = frozenset({
    "kind", "schema_version", *_PATHS, "approval_source_identity",
    "adapter_cpu", "controller_cpu", "policy_inputs", "historical_parity",
})
CONFIG_KEYS_V2 = (CONFIG_KEYS - {"historical_parity"}) | {"acceptance_profile", "baseline"}
_BASELINE_KEYS = frozenset({"baseline_id", "evidence_root", "history_inventory", "runtime_freeze_path"})
_POLICY_KEYS = frozenset({"micro_json", "expected_micro_sha256", "f1_receipt"})
_PARITY_KEYS = frozenset({
    "archive_root", "mapping_path", "approval_source_root", "approval_source_identity",
})


def absolute_path(value: object, field: str) -> Path:
    """Validate a literal absolute path, including every existing ancestor."""

    if not isinstance(value, str) or not value or "\x00" in value:
        raise BenchError(BM_SCHEMA_INVALID, "a path must be a nonempty string", field_path=field)
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or str(path) != value:
        raise BenchError(BM_UNSAFE_INPUT, "paths must be normalized and absolute", field_path=field)
    for part in reversed((path, *path.parents)):
        if part.is_symlink():
            raise BenchError(BM_UNSAFE_INPUT, "paths must not traverse a symlink", field_path=field)
        if os.path.lexists(part) and part != path and not part.is_dir():
            raise BenchError(BM_UNSAFE_INPUT, "a path ancestor is not a directory", field_path=field)
    return path


@dataclass(frozen=True)
class OperationConfig:
    """Validated locations and CPU selection; not a production capability."""

    document: Mapping[str, Any]

    def path(self, name: str) -> Path:
        return absolute_path(self.document[name], name)

    @property
    def adapter_cpu(self) -> int:
        return self.document["adapter_cpu"]

    @property
    def controller_cpu(self) -> int:
        return self.document["controller_cpu"]

    @property
    def profile_version(self) -> int:
        return require_profile_version(self.document["schema_version"])


def load_operation_config(path: Path) -> OperationConfig:
    location = absolute_path(str(Path(path).absolute()), "config")
    # Operator configuration is human-editable input, not a signed receipt.
    candidate = read_canonical_json(location, require_canonical=False)
    if not isinstance(candidate, Mapping):
        raise BenchError(BM_SCHEMA_INVALID, "official operation configuration must be an object")
    version = require_profile_version(candidate.get("schema_version"))
    document = require_closed(candidate, "operation-config", CONFIG_KEYS if version == 1 else CONFIG_KEYS_V2)
    if document["kind"] != CONFIG_KIND:
        raise BenchError(BM_SCHEMA_INVALID, "unsupported official operation configuration")
    for field in _PATHS:
        absolute_path(document[field], field)
    source = require_safe_root(Path(document["source_root"]))
    for field in ("workspace", "output_base"):
        target = Path(document[field])
        if target == source or target in source.parents:
            raise BenchError(BM_UNSAFE_INPUT, "an output must not contain the source repository", field_path=field)
        allowed = [source / "benchmark-results"]
        if field == "workspace":
            # The frozen D3-C backend deliberately enforces this namespace.
            allowed.append(source / "target" / "pr15i-d3-c")
        if source in target.parents and not any(base == target or base in target.parents for base in allowed):
            raise BenchError(BM_UNSAFE_INPUT, "the output is outside the permitted operation namespaces", field_path=field)
    workspace, output = (Path(document[name]) for name in ("workspace", "output_base"))
    if workspace == output or workspace in output.parents or output in workspace.parents:
        raise BenchError(BM_UNSAFE_INPUT, "raw and qualified output roots must be separate", field_path="workspace")
    validate_semantic_id(document["approval_source_identity"], "approval_source_identity")
    for field in ("adapter_cpu", "controller_cpu"):
        if type(document[field]) is not int or document[field] < 0:
            raise BenchError(BM_SCHEMA_INVALID, "CPU identifiers must be nonnegative integers", field_path=field)
    if document["adapter_cpu"] == document["controller_cpu"]:
        raise BenchError(BM_UNSAFE_INPUT, "adapter and controller require separate CPUs", field_path="controller_cpu")
    if document["policy_inputs"] is not None:
        item = require_closed(document["policy_inputs"], "policy_inputs", _POLICY_KEYS)
        for field in ("micro_json", "f1_receipt"):
            absolute_path(item[field], "policy_inputs." + field)
        digest = item["expected_micro_sha256"]
        from ..config.identity import validate_digest
        validate_digest(digest, "policy_inputs.expected_micro_sha256")
    if version == 1 and document["historical_parity"] is not None:
        item = require_closed(document["historical_parity"], "historical_parity", _PARITY_KEYS)
        for field in ("archive_root", "mapping_path", "approval_source_root"):
            absolute_path(item[field], "historical_parity." + field)
        validate_semantic_id(item["approval_source_identity"], "historical_parity.approval_source_identity")
    if version == 2:
        if type(document["acceptance_profile"]) is not str or document["acceptance_profile"] != CURRENT_BASELINE_PROFILE:
            raise BenchError(BM_SCHEMA_INVALID, "unsupported current-baseline profile", field_path="acceptance_profile")
        baseline = require_closed(document["baseline"], "baseline", _BASELINE_KEYS)
        baseline_id = validate_uuid4(baseline["baseline_id"], "baseline.baseline_id")
        evidence_root = absolute_path(baseline["evidence_root"], "baseline.evidence_root")
        if evidence_root.parts[-3:] != ("benchmark-results", "baselines", baseline_id):
            raise BenchError(BM_UNSAFE_INPUT, "baseline evidence must use its exact committable namespace", field_path="baseline.evidence_root")
        absolute_path(baseline["history_inventory"], "baseline.history_inventory")
        if baseline["runtime_freeze_path"] is not None:
            absolute_path(baseline["runtime_freeze_path"], "baseline.runtime_freeze_path")
    return OperationConfig(dict(document))
