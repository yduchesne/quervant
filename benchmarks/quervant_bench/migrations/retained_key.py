"""Thin read-only locator for the one BM-07 synthetic retained-key reference.

This module does not implement a controller, statistics, a policy or an oracle.
It only freezes the public experiment identifier and the exact checked-in catalog
file layout, and delegates validation to the existing BM-01 loader.
"""

from __future__ import annotations

from pathlib import Path

from ..config.contracts import ExperimentBundle, load_experiment_bundle
from ..config.errors import BM_UNSAFE_INPUT, BenchError
from ..evidence.provenance import repository_root

#: Public semantic experiment identifier for the BM-07 synthetic reference study.
REFERENCE_EXPERIMENT_ID = "synthetic-retained-key-reference"

#: Exact checked-in catalog file layout; the checked-in bytes are the authority.
REQUIRED_CATALOG_FILES: tuple[str, ...] = (
    "analysis-profile.v1.json",
    "adapter.yaml",
    "experiment.yaml",
    "policy-profile.v1.json",
    "protocol.yaml",
    "resource-observations.v1.json",
    "synthetic-scenario.v1.json",
    "workloads.yaml",
)


def reference_catalog_root(repo_root: Path | None = None) -> Path:
    """Return the catalog root that contains the reference experiment."""

    root = repository_root() if repo_root is None else repo_root
    return Path(root) / "benchmarks" / "experiments"


def load_reference_bundle(catalog_root: Path) -> ExperimentBundle:
    """Load the retained-key reference bundle through the frozen BM-01 loader."""

    if not isinstance(catalog_root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "catalog_root must be a Path",
            field_path="catalog_root",
        )
    return load_experiment_bundle(REFERENCE_EXPERIMENT_ID, catalog_root)


__all__ = [
    "REFERENCE_EXPERIMENT_ID",
    "REQUIRED_CATALOG_FILES",
    "load_reference_bundle",
    "reference_catalog_root",
]
