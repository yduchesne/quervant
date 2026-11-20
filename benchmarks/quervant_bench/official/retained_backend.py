"""Preparation and provenance checks for the retained frozen D3-C backend.

The original controller remains the measurement implementation. Preparation
builds its two pinned revisions without calling a timing entrypoint. Acquisition
uses the existing closed invocation factory; each completed campaign is checked
against the prepared binaries before its evidence may advance.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import content_digest
from ..config.errors import BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from ..evidence.hashing import sha256_regular_file
from ..evidence.provenance import require_clean_head
from ..qualification.contracts import require_closed
from .admission import _load_module, load_pr15d_oracle
from .acquisition import _run_owned_preparation
from .operation_config import absolute_path
from .operation_store import create_directory, write_record
from .protocols import D3C_BASE_COMMIT, D3C_EXPERIMENT_COMMIT, D3C_PROTOCOL_RAW_SHA256, STUDY_RETAINED_KEY, read_canonical_json

KIND = "official-retained-key-prepared-v1"


@dataclass(frozen=True)
class PreparedRetainedKey:
    manifest_path: Path
    source_root: Path
    corpus_dir: Path
    manifest: Mapping[str, Any]
    binary_digest: str


def legacy_runner() -> Any:
    return _load_module("official_retained_measurement_backend", "benchmarks/pr15i_d3_c/run.py")


def require_retained_namespace(root: Path, path: Path) -> None:
    absolute_path(str(path), "retained_output")
    base = root / "target" / "pr15i-d3-c"
    if base not in path.parents:
        raise BenchError(BM_UNSAFE_INPUT, "the frozen retained-key backend requires output beneath target/pr15i-d3-c", field_path="workspace")


def prepare_retained_key(*, root: Path, build_root: Path, corpus_dir: Path) -> PreparedRetainedKey:
    """Prepare once under the frozen timeout, then rehash the worker's files."""
    require_clean_head(root)
    require_retained_namespace(root, build_root)
    _run_owned_preparation(study_id=STUDY_RETAINED_KEY, root=root, build_root=build_root, corpus_dir=corpus_dir)
    return load_prepared_retained_key(build_root / "prepared-retained-key.json", root=root)


def _prepare_retained_key_body(*, root: Path, build_root: Path, corpus_dir: Path) -> PreparedRetainedKey:
    """Build the two historical adapters and corpus; execute no measurement."""

    require_clean_head(root)
    require_retained_namespace(root, build_root)
    create_directory(build_root, exclusive=True)
    runner = legacy_runner()
    protocol, protocol_sha = runner.load_protocol()
    if "sha256:" + protocol_sha != D3C_PROTOCOL_RAW_SHA256:
        raise BenchError(BM_IDENTITY_INVALID, "the retained backend protocol changed")
    source = runner.worktree(str(build_root), D3C_BASE_COMMIT)
    base = runner.build(source, str(build_root / "build" / "A"), False)
    runner.switch(source, D3C_BASE_COMMIT, D3C_EXPERIMENT_COMMIT)
    experiment = runner.build(source, str(build_root / "build" / "B"), True)
    if base["sha256"] == experiment["sha256"]:
        raise BenchError(BM_IDENTITY_INVALID, "retained-key BASE and experiment binaries are identical")
    if not corpus_dir.exists():
        runner.prepare_corpus(protocol, str(corpus_dir))
    oracle = load_pr15d_oracle()
    corpus, _ = oracle.load_and_verify(str(corpus_dir))
    corpus_digest = "sha256:" + oracle.sha256_bytes(oracle.canonical_json_bytes(corpus))
    if corpus_digest != "sha256:" + protocol["corpus_manifest_sha256"]:
        raise BenchError(BM_IDENTITY_INVALID, "the prepared corpus differs from the frozen retained-key corpus")
    document = {
        "schema": KIND, "source_root": str(root), "corpus_dir": str(corpus_dir),
        "protocol_digest": D3C_PROTOCOL_RAW_SHA256, "corpus_digest": corpus_digest,
        "binaries": {"A": base, "B": experiment},
    }
    path = build_root / "prepared-retained-key.json"
    write_record(build_root, path.name, document)
    return load_prepared_retained_key(path, root=root)


def load_prepared_retained_key(manifest_path: Path, *, root: Path) -> PreparedRetainedKey:
    document = require_closed(read_canonical_json(manifest_path), "retained-prepared", {
        "schema", "source_root", "corpus_dir", "protocol_digest", "corpus_digest", "binaries",
    })
    if document["schema"] != KIND or document["source_root"] != str(root) or document["protocol_digest"] != D3C_PROTOCOL_RAW_SHA256:
        raise BenchError(BM_IDENTITY_INVALID, "prepared retained-key identity differs")
    binaries = require_closed(document["binaries"], "binaries", {"A", "B"})
    for arm, source in (("A", D3C_BASE_COMMIT), ("B", D3C_EXPERIMENT_COMMIT)):
        item = require_closed(binaries[arm], f"binaries.{arm}", {"binary", "sha256", "bytes", "argv", "feature", "source_sha"})
        binary = absolute_path(item["binary"], "binary")
        digest, size = sha256_regular_file(binary.parent, binary.name, max_bytes=536_870_912)
        if digest != "sha256:" + item["sha256"] or type(item["bytes"]) is not int or size != item["bytes"] or item["source_sha"] != source:
            raise BenchError(BM_IDENTITY_INVALID, "a prepared retained-key binary changed", field_path="binaries")
        if item["feature"] is not (arm == "B"):
            raise BenchError(BM_IDENTITY_INVALID, "a retained-key binary feature differs")
    if binaries["A"]["sha256"] == binaries["B"]["sha256"]:
        raise BenchError(BM_IDENTITY_INVALID, "retained-key BASE and experiment binaries are identical")
    corpus_dir = absolute_path(document["corpus_dir"], "corpus_dir")
    oracle = load_pr15d_oracle()
    corpus, _ = oracle.load_and_verify(str(corpus_dir))
    if "sha256:" + oracle.sha256_bytes(oracle.canonical_json_bytes(corpus)) != document["corpus_digest"]:
        raise BenchError(BM_IDENTITY_INVALID, "the prepared retained-key corpus changed")
    digest = content_digest({"kind": "official-retained-key-binaries", "schema_version": 1, "binaries": binaries})
    return PreparedRetainedKey(manifest_path, root, corpus_dir, dict(document), digest)


def verify_campaign_binaries(directory: Path, prepared: PreparedRetainedKey, *, control: bool) -> None:
    """Bind the original controller's build output to the actual G0-prepared bytes."""

    fresh = load_prepared_retained_key(prepared.manifest_path, root=prepared.source_root)
    if fresh.binary_digest != prepared.binary_digest:
        raise BenchError(BM_IDENTITY_INVALID, "prepared binaries changed during acquisition")
    manifest = read_canonical_json(directory / "manifest.json")
    expected_arms = {"A", "B"} if control else {"A", "L", "P", "H"}
    arms = manifest.get("arms")
    if not isinstance(arms, dict) or set(arms) != expected_arms:
        raise BenchError(BM_IDENTITY_INVALID, "the completed campaign does not contain the full arm set")
    for arm, item in arms.items():
        expected = fresh.manifest["binaries"]["A" if control or arm == "A" else "B"]
        if item.get("binary_sha256") != expected["sha256"] or item.get("binary_bytes") != expected["bytes"] or item.get("source_sha") != expected["source_sha"]:
            raise BenchError(BM_IDENTITY_INVALID, "a campaign used a binary outside the approved preparation", field_path="binary_manifest_digest")
