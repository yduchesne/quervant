#!/usr/bin/env python3
"""Read-only, deterministic legacy benchmark contract inventory.

The inventory is derived exclusively from a pinned git baseline commit
(``git ls-tree`` / ``git show``), never from the working tree. It never executes a
benchmark runner, profiler or historical verifier.

Usage::

    python benchmarks/scripts/bm-contract-inventory.py \
        --baseline <commit> --out <new-path>
    python benchmarks/scripts/bm-contract-inventory.py \
        --baseline <commit> --check <existing-file>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

INVENTORY_VERSION = 1
SCOPES: tuple[str, ...] = (
    "benchmarks/",
    "crates/quervant-core/benches/",
    ".github/workflows/ci.yml",
)

KINDS: tuple[str, ...] = (
    "runner",
    "verifier",
    "protocol",
    "adapter",
    "corpus_oracle",
    "analysis",
    "policy",
    "admission",
    "acceptance",
    "attestation",
    "report_schema",
    "evidence",
    "profiling",
    "criterion",
    "fixture",
    "test",
    "launcher",
    "documentation",
    "other_related",
)

DISPOSITIONS: tuple[str, ...] = (
    "retain_live",
    "read_only_adapter_later",
    "preserve_archive",
    "candidate_migrate_later",
    "external_not_present",
)

DISPOSITION_BY_KIND: dict[str, str] = {
    "runner": "retain_live",
    "verifier": "retain_live",
    "protocol": "read_only_adapter_later",
    "adapter": "retain_live",
    "corpus_oracle": "candidate_migrate_later",
    "analysis": "candidate_migrate_later",
    "policy": "candidate_migrate_later",
    "admission": "candidate_migrate_later",
    "acceptance": "candidate_migrate_later",
    "attestation": "candidate_migrate_later",
    "report_schema": "read_only_adapter_later",
    "evidence": "preserve_archive",
    "profiling": "retain_live",
    "criterion": "retain_live",
    "fixture": "retain_live",
    "test": "retain_live",
    "launcher": "retain_live",
    "documentation": "preserve_archive",
    "other_related": "preserve_archive",
}

#: Directory token -> historical family (documented, deterministic table).
FAMILY_BY_TOKEN: dict[str, str] = {
    "reports": "historical-report",
    "datasets": "historical-workload",
    "workloads": "historical-workload",
    "scripts": "historical-tooling",
    "pr15d": "cross-engine-comparison",
    "pr15e": "profiling",
    "pr15e_b1": "profiling",
    "pr15f": "profiling",
    "pr15g_a": "storage-retained-key",
    "pr15g_b": "storage-retained-key",
    "pr15g_c": "storage-retained-key",
    "pr15g_d": "storage-retained-key",
    "pr15g_e": "storage-retained-key",
    "pr15h_a": "storage-retained-key",
    "pr15h_a2": "storage-retained-key",
    "pr15h_a3": "storage-retained-key",
    "pr15h_b": "storage-retained-key",
    "pr15h_c": "storage-retained-key",
    "pr15h_d": "storage-retained-key",
    "pr15h_e": "storage-retained-key",
    "pr15i_0": "retained-key-dedup",
    "pr15i_a": "retained-key-dedup",
    "pr15i_b": "retained-key-dedup",
    "pr15i_c": "retained-key-dedup",
    "pr15i_d0": "retained-key-dedup",
    "pr15i_d1_f": "retained-key-dedup",
    "pr15i_d2a": "retained-key-dedup",
    "pr15i_d3_b": "retained-key-dedup",
    "pr15i_d3_b_f1": "retained-key-dedup",
    "pr15i_d3_b_f1_1": "retained-key-dedup",
    "pr15i_d3_b_f1_2": "retained-key-dedup",
    "pr15i_d3_c": "retained-key-dedup",
    "pr15i_d3_c_t7": "retained-key-dedup",
    "pr15i_d3_c_t7_f2": "retained-key-dedup",
    "pr15i_d3a": "retained-key-dedup",
    "pr15i_d3a_review": "retained-key-dedup",
}

_SCHEMA_KEY_RE = re.compile(r'"schema"\s*:\s*"([A-Za-z0-9][A-Za-z0-9._-]*)"')
_PY_SCHEMA_DICT_RE = re.compile(
    r"""["']schema["']\s*:\s*["']([A-Za-z0-9][A-Za-z0-9._-]*)["']"""
)
_PY_CONST_RE = re.compile(
    r"""SCHEMA_[A-Z0-9_]+\s*=\s*["']([A-Za-z0-9][A-Za-z0-9._-]*)["']"""
)
_JSON_ID_RE = re.compile(r'"\$id"\s*:\s*"([^"]+)"')
_VERSION_SEGMENT_RE = re.compile(r"^v(\d+)(?:r\d+)?$")

_PROFILE_RE = re.compile(r"benchmarks/(pr\d+[a-z0-9_]*)")


class InventoryError(RuntimeError):
    """Raised when the baseline cannot be inspected deterministically."""


# ---------------------------------------------------------------------------
# Git plumbing (argv arrays only, no shell)
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: str | None = None) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise InventoryError(
            "git command failed: "
            + " ".join(["git", *args])
            + ": "
            + completed.stderr.decode("utf-8", errors="replace").strip()
        )
    return completed.stdout


def tracked_entries(baseline: str, cwd: str | None = None) -> dict[str, str]:
    """Return ``path -> blob object id`` for the pinned baseline scopes."""

    output = _git(
        ["ls-tree", "-r", "-z", baseline, "--", *SCOPES],
        cwd=cwd,
    )
    entries: dict[str, str] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        header, _, raw_path = record.partition(b"\t")
        fields = header.split()
        if len(fields) != 3:  # pragma: no cover - defensive
            raise InventoryError("unexpected git ls-tree record")
        _mode, object_type, object_id = fields
        path = raw_path.decode("utf-8")
        if object_type != b"blob":  # pragma: no cover - submodule guard
            raise InventoryError(f"non-blob tracked entry: {path}")
        entries[path] = object_id.decode("ascii")
    return entries


def file_bytes(baseline: str, path: str, cwd: str | None = None) -> bytes:
    """Return the exact committed bytes of ``path`` at ``baseline``."""

    return _git(["show", f"{baseline}:{path}"], cwd=cwd)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def historical_family(path: str) -> str:
    """Derive a deterministic historical family label for ``path``."""

    if path.startswith("crates/quervant-core/benches/"):
        return "criterion-suite"
    if path == ".github/workflows/ci.yml":
        return "ci"
    if path == "benchmarks/README.md":
        return "documentation"
    match = _PROFILE_RE.match(path)
    if match:
        return FAMILY_BY_TOKEN.get(match.group(1), "historical-other")
    for token, family in FAMILY_BY_TOKEN.items():
        if path.startswith(f"benchmarks/{token}/"):
            return family
    return "historical-other"


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def classify(path: str) -> tuple[str, str]:
    """Return ``(kind, note)`` for one tracked path, with a specific rationale."""

    name = _basename(path)
    lower = name.lower()

    if path == ".github/workflows/ci.yml":
        return "launcher", "CI entrypoint that consumes benchmark scripts and compile-only checks"
    if path.startswith("crates/quervant-core/benches/"):
        if "/common/" in path or "/unified_diag_common/" in path:
            return "fixture", "shared deterministic Criterion fixture module"
        return "criterion", "native Criterion benchmark target"
    if path.startswith("benchmarks/reports/"):
        return "evidence", "frozen historical benchmark report/evidence record"
    if path.startswith("benchmarks/datasets/"):
        return "fixture", "checked-in historical dataset descriptor"
    if path.startswith("benchmarks/workloads/"):
        return "protocol", "versioned historical workload contract"
    if path.startswith("benchmarks/scripts/"):
        if lower.endswith(".sh"):
            return "launcher", "historical shell launcher or wrapper"
        if lower.startswith("test") or lower.startswith("validate"):
            return "test", "historical deterministic validator/script test"
        return "launcher", "historical tooling entrypoint"
    if path == "benchmarks/README.md":
        return "documentation", "benchmark directory documentation"

    if lower.endswith(".md"):
        return "documentation", "historical benchmark narrative documentation"
    if lower.endswith(".sha256"):
        return "adapter", "checked-in checksum provenance for an external-engine adapter artifact"
    if lower == "__init__.py":
        return "other_related", "Python package marker for a historical analysis package"
    if lower == "constants.py":
        return "other_related", "shared historical constants module; behavior owned by sibling modules"
    if lower == "fixture_factory.py":
        return "fixture", "deterministic historical fixture factory"
    if lower.endswith(".gitignore"):
        return "other_related", "ignore rules for transient benchmark output; not a contract artifact"
    if lower.endswith((".jar", ".bat")) or lower in {
        "gradlew",
        "build.gradle",
        "settings.gradle",
        "gradle-wrapper.properties",
    }:
        return "adapter", "external-engine adapter build wrapper"
    if lower.endswith(".java"):
        return "adapter", "external-engine adapter source"
    if lower in {"cargo.toml", "cargo.lock"}:
        return "other_related", "auxiliary probe crate manifest/lockfile; build metadata only"
    if lower.endswith(".rs"):
        if "_probe" in path or "_lab" in path:
            return "profiling", "auxiliary probe crate exercising a historical measurement path"
        return "fixture", "auxiliary Rust benchmark fixture/source"
    if lower.startswith("test_") or lower.startswith("test-") or lower in {"smoke.py"}:
        return "test", "historical deterministic test module"

    if lower.startswith("verify") and lower.endswith(".py"):
        return "verifier", "historical independent verifier"
    if lower.startswith("validate") and lower.endswith(".py"):
        return "verifier", "historical validation/verification helper"
    if lower in {"run.py", "run_mutation.py", "confirm.py", "isolate_d2.py"} or lower.endswith(
        "_run.py"
    ):
        return "runner", "historical experiment controller"
    if lower == "replay.py":
        return "runner", "historical read-only replay controller"
    if path.endswith("protocol/schema.json"):
        return "report_schema", "JSON Schema for a historical protocol report"
    if "protocol" in path.lower() and lower.endswith(".json"):
        return "protocol", "versioned historical protocol declaration"
    if lower.endswith(".json"):
        return "fixture", "historical machine manifest/fixture"
    if lower in {"generate.py"} or "/corpus/" in path:
        return "corpus_oracle", "deterministic corpus/oracle generator"
    if lower in {"oracle.py"}:
        return "corpus_oracle", "declarative correctness oracle implementation"
    if lower in {
        "analysis.py",
        "analysis_v3.py",
        "analyze_control.py",
        "summarize.py",
        "aggregate.py",
    } or lower.endswith("_summary.py"):
        return "analysis", "historical statistical derivation"
    if lower in {"policy.py"} or lower.startswith("verify_policy"):
        return "policy", "historical typed policy evaluation/verification"
    if lower in {"admission.py", "freeze.py", "freeze_gate.py", "package_evidence.py"}:
        return "admission", "historical admission/freeze evidence logic"
    if lower in {"acceptance_gate.py"}:
        return "acceptance", "historical acceptance gate"
    if lower in {
        "attribution.py",
        "profile.py",
        "profile_queries.py",
        "run_targeted.py",
        "diagnose_e.py",
        "host_topology.py",
        "stability_diagnostic.py",
        "noise_diag.py",
        "layout_diag.py",
        "noise_probe.py",
        "source_proof.py",
        "dispatch_source_proof.py",
        "f_final_source_proof.py",
        "patch_source.py",
        "patch_instrumented_source.py",
        "codegen_capture.py",
        "dispatch_codegen_capture.py",
        "replay_matrix.py",
        "batched_noise.py",
        "batched_adapter_patch.py",
        "resource_probe.py",
    }:
        return "profiling", "historical profiling, attribution or source-proof diagnostic"
    if lower.endswith("_source_proof.py") or lower == "source_proof.py":
        return "profiling", "historical profiling/source-proof capture"
    if lower == "generate_v3_schedule.py":
        return "protocol", "historical schedule generator for a versioned protocol"
    if lower == "extract_order.py":
        return "analysis", "historical residual-order extraction for analysis"
    if lower.endswith(".py"):
        return "other_related", "historical Python tooling without a narrower role rule"
    return "other_related", "tracked historical artifact without a narrower role rule"


def roles_for(path: str, kind: str) -> list[str]:
    """Derive the producer/consumer roles a tracked file participates in."""

    roles = {kind}
    name = _basename(path).lower()
    for token, role in (
        ("run", "runner"),
        ("verify", "verifier"),
        ("protocol", "protocol"),
        ("adapter", "adapter"),
        ("oracle", "corpus_oracle"),
        ("analysis", "analysis"),
        ("policy", "policy"),
        ("admission", "admission"),
        ("acceptance", "acceptance"),
        ("attestation", "attestation"),
        ("freeze", "admission"),
        ("report", "report_schema"),
        ("profile", "profiling"),
        ("bench", "criterion"),
        ("fixture", "fixture"),
        ("test", "test"),
        ("launch", "launcher"),
    ):
        if token in name:
            roles.add(role)
    return sorted(roles)


def is_format_id(value: str) -> bool:
    """Return whether ``value`` looks like a versioned machine format identifier."""

    if not value or value.lower() != value:
        return False
    return any(_VERSION_SEGMENT_RE.fullmatch(segment) for segment in value.split("-"))


def legacy_version_of(format_id: str) -> int:
    """Return the numeric version embedded in a format identifier."""

    for segment in format_id.split("-"):
        match = _VERSION_SEGMENT_RE.fullmatch(segment)
        if match:
            return int(match.group(1))
    raise InventoryError(f"format id has no version segment: {format_id!r}")


def discover_schema_ids(text: str, suffix: str) -> list[str]:
    """Extract explicit, verbatim machine schema identifiers from a source file."""

    if suffix not in {".py", ".json", ".yaml", ".yml"}:
        return []
    candidates: set[str] = set()
    if suffix == ".py":
        candidates.update(_PY_SCHEMA_DICT_RE.findall(text))
        candidates.update(_PY_CONST_RE.findall(text))
    else:
        candidates.update(_SCHEMA_KEY_RE.findall(text))
        candidates.update(_JSON_ID_RE.findall(text))
    return sorted(candidate for candidate in candidates if is_format_id(candidate))


def unresolved_dependency_notes(text: str) -> list[str]:
    """Flag references to untracked local evidence roots without inventing members."""

    notes: list[str] = []
    if re.search(r"(?<![A-Za-z0-9_])target/", text):
        notes.append("references the untracked target/ evidence root")
    if ".synth/" in text:
        notes.append("references the untracked .synth/ evidence root")
    return notes


# ---------------------------------------------------------------------------
# Inventory construction
# ---------------------------------------------------------------------------


def _suffix(path: str) -> str:
    name = _basename(path)
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def build_inventory(baseline: str, cwd: str | None = None) -> dict[str, Any]:
    """Build the complete deterministic inventory document for ``baseline``."""

    entries = tracked_entries(baseline, cwd=cwd)
    rows: list[dict[str, Any]] = []
    by_kind: dict[str, int] = {kind: 0 for kind in KINDS}
    by_disposition: dict[str, int] = {disposition: 0 for disposition in DISPOSITIONS}
    format_ids: dict[str, set[str]] = {}
    external_roots: set[str] = set()

    for path in sorted(entries):
        blob_sha = entries[path]
        data = file_bytes(baseline, path, cwd=cwd)
        digest = hashlib.sha256(data).hexdigest()
        suffix = _suffix(path)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        schema_ids = discover_schema_ids(text, suffix)
        for schema_id in schema_ids:
            format_ids.setdefault(schema_id, set()).add(path)
        if re.search(r"(?<![A-Za-z0-9_])target/", text):
            external_roots.add("target/")
        if ".synth/" in text:
            external_roots.add(".synth/")

        kind, note = classify(path)
        if kind not in KINDS:  # pragma: no cover - table guard
            raise InventoryError(f"unclassified kind for {path}")
        disposition = DISPOSITION_BY_KIND[kind]
        by_kind[kind] += 1
        by_disposition[disposition] += 1

        extra_notes = unresolved_dependency_notes(text)
        rendered_note = "; ".join([note, *extra_notes])
        rows.append(
            {
                "path": path,
                "kind": kind,
                "historical_family": historical_family(path),
                "schema_ids": schema_ids,
                "producer_consumers": roles_for(path, kind),
                "source_baseline_sha": baseline,
                "blob_sha": blob_sha,
                "sha256": digest,
                "disposition": disposition,
                "compatibility": "legacy_original_only",
                "notes": rendered_note,
            }
        )

    for root in sorted(external_roots):
        by_kind["evidence"] += 1
        by_disposition["external_not_present"] += 1
        rows.append(
            {
                "path": root,
                "kind": "evidence",
                "historical_family": "historical-report",
                "schema_ids": [],
                "producer_consumers": [],
                "source_baseline_sha": baseline,
                "blob_sha": None,
                "sha256": None,
                "disposition": "external_not_present",
                "compatibility": "external_not_present",
                "notes": (
                    "Untracked local evidence root referenced by historical tooling; "
                    "not present in the pinned tree and never fabricated here"
                ),
                "external_present": False,
            }
        )

    counts = {
        "tracked_paths": len(entries),
        "external_roots": len(external_roots),
        "legacy_format_ids": len(format_ids),
        "by_kind": by_kind,
        "by_disposition": by_disposition,
    }

    document = {
        "inventory_version": INVENTORY_VERSION,
        "source_baseline_sha": baseline,
        "scopes": list(SCOPES),
        "classification_contract": {
            "kinds": list(KINDS),
            "dispositions": list(DISPOSITIONS),
            "format_id_rule": (
                "explicit 'schema'/'$id'/SCHEMA_* literal values with a v<N>[-r<N>] "
                "version segment; recorded verbatim"
            ),
            "historical_counts_note": (
                "docs/benchmarking/BENCHMARKING_MIGRATION.md reported 32 PR15 benchmark "
                "directories, 26 run.py and 15 verify.py files. Those three counts are "
                "reproduced on this pinned baseline; the inventory additionally records "
                "30 *_run.py controllers and 23 verify*.py modules, which the three "
                "headline numbers do not cover."
            ),
        },
        "counts": counts,
        "paths": rows,
        "format_ids": [
            {
                "legacy_format_id": format_id,
                "legacy_version": legacy_version_of(format_id),
                "source_paths": sorted(format_ids[format_id]),
            }
            for format_id in sorted(format_ids)
        ],
    }
    validate_inventory(document)
    return document


def validate_inventory(document: Any) -> None:
    """Validate the structural and accounting invariants of an inventory."""

    if not isinstance(document, dict):
        raise InventoryError("inventory must be an object")
    if document.get("inventory_version") != INVENTORY_VERSION:
        raise InventoryError("unexpected inventory_version")
    baseline = document.get("source_baseline_sha")
    if not isinstance(baseline, str) or not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise InventoryError("source_baseline_sha must be a 40-character commit")
    paths = document.get("paths")
    if not isinstance(paths, list) or not paths:
        raise InventoryError("inventory must list paths")

    seen_paths: set[str] = set()
    tracked_rows = 0
    external_rows = 0
    by_kind = {kind: 0 for kind in KINDS}
    by_disposition = {disposition: 0 for disposition in DISPOSITIONS}
    row_by_path: dict[str, dict[str, Any]] = {}
    ordered: list[str] = []
    for index, row in enumerate(paths):
        if not isinstance(row, dict):
            raise InventoryError(f"paths[{index}] must be an object")
        path = row.get("path")
        if not isinstance(path, str) or not path:
            raise InventoryError(f"paths[{index}].path must be a non-empty string")
        if path in seen_paths:
            raise InventoryError(f"duplicate inventory path: {path}")
        seen_paths.add(path)
        ordered.append(path)
        row_by_path[path] = row
        kind = row.get("kind")
        disposition = row.get("disposition")
        if kind not in KINDS:
            raise InventoryError(f"unclassified kind for {path}: {kind!r}")
        if disposition not in DISPOSITIONS:
            raise InventoryError(f"unknown disposition for {path}: {disposition!r}")
        by_kind[kind] += 1
        by_disposition[disposition] += 1
        roles = row.get("producer_consumers")
        if not isinstance(roles, list) or any(role not in KINDS for role in roles):
            raise InventoryError(f"unknown producer/consumer role for {path}")
        schema_ids = row.get("schema_ids")
        if not isinstance(schema_ids, list):
            raise InventoryError(f"schema_ids must be a list for {path}")
        for schema_id in schema_ids:
            if not is_format_id(schema_id):
                raise InventoryError(f"invalid schema id for {path}: {schema_id!r}")
        blob_sha = row.get("blob_sha")
        sha256 = row.get("sha256")
        compatibility = row.get("compatibility")
        if disposition == "external_not_present":
            external_rows += 1
            if blob_sha is not None or sha256 is not None:
                raise InventoryError(
                    f"external root {path} must not carry invented digests"
                )
            if compatibility != "external_not_present":
                raise InventoryError(f"external root {path} has wrong compatibility")
        else:
            tracked_rows += 1
            if not isinstance(blob_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", blob_sha):
                raise InventoryError(f"invalid blob object id for {path}")
            if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
                raise InventoryError(f"invalid content digest for {path}")
            if compatibility != "legacy_original_only":
                raise InventoryError(f"unexpected compatibility claim for {path}")

    if ordered != sorted(ordered):
        raise InventoryError("inventory paths must be sorted deterministically")

    formats = document.get("format_ids")
    if not isinstance(formats, list):
        raise InventoryError("format_ids must be a list")
    seen_formats: set[str] = set()
    for index, entry in enumerate(formats):
        if not isinstance(entry, dict):
            raise InventoryError(f"format_ids[{index}] must be an object")
        format_id = entry.get("legacy_format_id")
        version = entry.get("legacy_version")
        if not isinstance(format_id, str) or not is_format_id(format_id):
            raise InventoryError(f"format_ids[{index}] has an invalid identifier")
        if format_id in seen_formats:
            raise InventoryError(f"duplicate registered format id: {format_id}")
        seen_formats.add(format_id)
        if legacy_version_of(format_id) != version:
            raise InventoryError(f"format version mismatch for {format_id}")
        sources = entry.get("source_paths")
        if not isinstance(sources, list) or not sources:
            raise InventoryError(f"format {format_id} has no source paths")
        for source in sources:
            if source not in row_by_path:
                raise InventoryError(
                    f"format {format_id} references an unclassified path: {source}"
                )
            if format_id not in row_by_path[source]["schema_ids"]:
                raise InventoryError(
                    f"format {format_id} is not recorded on {source}"
                )

    for row in paths:
        for schema_id in row["schema_ids"]:
            if schema_id not in seen_formats:
                raise InventoryError(
                    f"unregistered schema id {schema_id} on {row['path']}"
                )

    counts = document.get("counts")
    if not isinstance(counts, dict):
        raise InventoryError("counts must be an object")
    if counts.get("tracked_paths") != tracked_rows:
        raise InventoryError("counts.tracked_paths does not match the path rows")
    if counts.get("external_roots") != external_rows:
        raise InventoryError("counts.external_roots does not match the path rows")
    if counts.get("legacy_format_ids") != len(seen_formats):
        raise InventoryError("counts.legacy_format_ids does not match the registry")
    if counts.get("by_kind") != by_kind:
        raise InventoryError("counts.by_kind does not match the path rows")
    if counts.get("by_disposition") != by_disposition:
        raise InventoryError("counts.by_disposition does not match the path rows")


def canonical_bytes(document: Any) -> bytes:
    """Deterministic serialization used for byte-for-byte inventory comparison."""

    return (
        json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bm-contract-inventory.py",
        description="Read-only legacy benchmark contract inventory for a pinned commit.",
    )
    parser.add_argument("--baseline", required=True, metavar="<commit>")
    parser.add_argument("--out", metavar="<new-path>")
    parser.add_argument("--check", metavar="<existing-file>")
    arguments = parser.parse_args(list(argv))
    if bool(arguments.out) == bool(arguments.check):
        parser.error("exactly one of --out or --check is required")
    return arguments


def main(argv: Iterable[str] | None = None) -> int:
    arguments = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        document = build_inventory(arguments.baseline)
    except InventoryError as error:
        print(f"inventory error: {error}", file=sys.stderr)
        return 2
    payload = canonical_bytes(document)
    if arguments.check:
        try:
            existing = Path(arguments.check).read_bytes()
        except FileNotFoundError:
            print(f"inventory check failed: {arguments.check} is missing", file=sys.stderr)
            return 2
        if existing != payload:
            print(
                "inventory check failed: regenerated inventory differs from "
                f"{arguments.check}",
                file=sys.stderr,
            )
            return 1
        return 0
    output = Path(arguments.out)
    if output.exists():
        print(f"inventory error: refusing to overwrite {output}", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
