"""Shared BM-08 test support: catalog editing and a real synthetic workspace.

Every helper here is test-only. Nothing in this module is imported by production
code, and nothing here executes a real engine, a timed query or a subprocess.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping

from quervant_bench.config.codec import (
    canonical_document_bytes,
    content_digest,
    load_document,
)
from quervant_bench.migrations.cross_engine import (
    REFERENCE_EXPERIMENT_ID,
    qualify_cross_engine_synthetic,
    validate_cross_engine_reference,
)
from quervant_bench.qualification.identity import compute_source_set_digest
from quervant_bench.qualification.profiles import default_profile_path
from quervant_bench.qualification.publication import load_bundle
from quervant_bench.tests.test_qualification_contracts import (
    FIXTURES as QUALIFICATION_FIXTURES,
    qa_workspace,
    trust_anchors,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
CATALOG = EXPERIMENTS / REFERENCE_EXPERIMENT_ID
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cross-engine"
EXPECTATIONS = json.loads((FIXTURES / "reference-expectations.v1.json").read_text())
LEGACY_MATRIX = json.loads((FIXTURES / "legacy-equivalence.v1.json").read_text())

YAML_FILES = ("adapter.yaml", "experiment.yaml", "protocol.yaml", "workloads.yaml")
JSON_COMPANIONS = (
    "oracle-golden.v1.json",
    "engine-source-bindings.v1.json",
    "semantic-comparability.v1.json",
)
PROFILE_FILES = (
    "analysis-profile.v1.json",
    "policy-profile.v1.json",
    "resource-observations.v1.json",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_canonical(path: Path, document: Mapping[str, Any]) -> None:
    path.write_bytes(canonical_document_bytes(dict(document)))


def snapshot(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            entries[relative] = "symlink:" + os.readlink(path)
        elif path.is_dir():
            entries[relative] = "dir"
        else:
            entries[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def copy_catalog(destination: Path) -> Path:
    """Copy the checked-in catalog into a disposable catalog root."""

    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(CATALOG, destination / REFERENCE_EXPERIMENT_ID)
    return destination


class CatalogEditor:
    """Edit one disposable catalog copy and keep the digest chain coherent."""

    def __init__(self, catalog_root: Path) -> None:
        self.root = catalog_root
        self.experiment_root = catalog_root / REFERENCE_EXPERIMENT_ID
        self.documents: dict[str, dict[str, Any]] = {}
        for name in YAML_FILES + JSON_COMPANIONS + PROFILE_FILES + (
            "synthetic-scenario.v1.json",
        ):
            self.documents[name] = read_json(self.experiment_root / name)

    def reference_spec_digest(self) -> str:
        return content_digest(
            read_json(REPO_ROOT / "benchmarks/pr15d/spec/pr15d_v1.json")
        )

    def rebind(self) -> None:
        """Recompute every digest a coherent edit must necessarily update."""

        ledger = self.documents["semantic-comparability.v1.json"]
        ledger["reference_spec_digest"] = self.reference_spec_digest()
        ledger["oracle_golden_digest"] = content_digest(
            self.documents["oracle-golden.v1.json"]
        )
        ledger["engine_source_bindings_digest"] = content_digest(
            self.documents["engine-source-bindings.v1.json"]
        )
        ledger_digest = content_digest(ledger)
        workload = self.documents["workloads.yaml"]
        workload["dataset"]["digest"] = ledger_digest
        workload_digest = content_digest(workload)
        self.documents["protocol.yaml"]["workload_digest"] = workload_digest

    def write(self) -> None:
        for name, document in self.documents.items():
            write_canonical(self.experiment_root / name, document)


def copy_workspace(source: Path) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
    target = Path(temporary.name) / "workspace"
    shutil.copytree(source, target)
    return temporary, target


class CrossEngineWorkspace:
    """One real BM-03 → BM-06 cross-engine synthetic workspace."""

    def __init__(
        self,
        *,
        checked_in_anchors: bool = False,
        catalog_root: Path | None = None,
        qualify: bool = True,
    ) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.catalog_root = EXPERIMENTS if catalog_root is None else catalog_root
        self.experiment_root = self.catalog_root / REFERENCE_EXPERIMENT_ID
        self.bundle, self.digests = validate_cross_engine_reference(
            self.catalog_root, REPO_ROOT
        )
        self.run_id = str(uuid.uuid4())
        self.scenario_root = (
            self.workspace / "scenarios" / REFERENCE_EXPERIMENT_ID / self.run_id
        )
        self.scenario_root.mkdir(parents=True)
        shutil.copyfile(
            self.experiment_root / "synthetic-scenario.v1.json",
            self.scenario_root / "synthetic-scenario.v1.json",
        )
        self.run_output_base = self.workspace / "runs"
        self.run_output_base.mkdir()
        self.qualification_output_base = self.workspace / "qualified"
        self.qualification_output_base.mkdir()
        self.run_dir = (
            self.run_output_base / REFERENCE_EXPERIMENT_ID / self.run_id
        )
        self.qa_root = self.workspace / "qa"
        if checked_in_anchors:
            self.qa_root.mkdir()
            for name in ("framework-qa-evidence.json", "source-qa-evidence.json"):
                shutil.copyfile(QUALIFICATION_FIXTURES / name, self.qa_root / name)
            for name in ("framework-qa", "source-qa"):
                shutil.copytree(QUALIFICATION_FIXTURES / name, self.qa_root / name)
            checked_in = trust_anchors()
            self.anchors = {
                "kind": "simulated-qualification-trust-anchors",
                "schema_version": 1,
                "profile_digest": checked_in["profile_digest"],
                "framework_qa_digest": checked_in["framework_qa_digest"],
                "source_qa_digest": checked_in["source_qa_digest"],
                "source_set_digest": checked_in["source_set_digest"],
            }
        else:
            source_digest = compute_source_set_digest(REPO_ROOT)
            _qa_root, qa_digests = qa_workspace(
                self.qa_root, source_set_digest=source_digest
            )
            self.anchors = {
                "kind": "simulated-qualification-trust-anchors",
                "schema_version": 1,
                "profile_digest": content_digest(load_document(default_profile_path())),
                "framework_qa_digest": qa_digests["framework_qa_digest"],
                "source_qa_digest": qa_digests["source_qa_digest"],
                "source_set_digest": source_digest,
            }
        write_canonical(self.workspace / "qualification-anchors.v1.json", self.anchors)
        self.result = self.qualify() if qualify else None
        self.committed = (
            load_bundle(
                output_base=self.qualification_output_base,
                experiment_id=REFERENCE_EXPERIMENT_ID,
                run_id=self.run_id,
            )
            if qualify
            else None
        )
        self.documents = self.committed.documents if qualify else {}

    def qualification_arguments(self) -> dict[str, Any]:
        return {
            "catalog_root": self.catalog_root,
            "source_root": REPO_ROOT,
            "run_id": self.run_id,
            "scenario_root": self.scenario_root,
            "run_output_base": self.run_output_base,
            "qualification_output_base": self.qualification_output_base,
            "qualification_profile_path": default_profile_path(),
            "qa_evidence_root": self.qa_root,
            "expected_profile_digest": self.anchors["profile_digest"],
            "expected_framework_qa_digest": self.anchors["framework_qa_digest"],
            "expected_source_qa_digest": self.anchors["source_qa_digest"],
            "expected_source_set_digest": self.anchors["source_set_digest"],
        }

    def qualify(self) -> Any:
        return qualify_cross_engine_synthetic(**self.qualification_arguments())

    def coordinator_arguments(self) -> dict[str, Any]:
        """Return the unchanged BM-06 coordinator arguments for this workspace."""

        return {
            "bundle": self.bundle,
            "run_dir": self.run_dir,
            "scenario_root": self.scenario_root,
            "profiles_root": self.experiment_root,
            "resources_root": self.experiment_root,
            "qualification_profile_path": default_profile_path(),
            "qa_evidence_root": self.qa_root,
            "expected_profile_digest": self.anchors["profile_digest"],
            "expected_framework_qa_digest": self.anchors["framework_qa_digest"],
            "expected_source_qa_digest": self.anchors["source_qa_digest"],
            "source_root": REPO_ROOT,
            "expected_source_set_digest": self.anchors["source_set_digest"],
            "output_base": self.qualification_output_base,
        }

    def close(self) -> None:
        self._temporary.cleanup()


_CACHE: dict[str, CrossEngineWorkspace] = {}


def cached_workspace(*, checked_in_anchors: bool = False) -> CrossEngineWorkspace:
    key = "checked-in" if checked_in_anchors else "generated"
    if key not in _CACHE:
        workspace = CrossEngineWorkspace(checked_in_anchors=checked_in_anchors)
        _CACHE[key] = workspace
        atexit.register(workspace.close)
    return _CACHE[key]


__all__ = [
    "CATALOG",
    "CatalogEditor",
    "CrossEngineWorkspace",
    "EXPERIMENTS",
    "EXPECTATIONS",
    "FIXTURES",
    "JSON_COMPANIONS",
    "LEGACY_MATRIX",
    "PROFILE_FILES",
    "REPO_ROOT",
    "YAML_FILES",
    "cached_workspace",
    "copy_catalog",
    "copy_workspace",
    "read_json",
    "snapshot",
    "write_canonical",
]
