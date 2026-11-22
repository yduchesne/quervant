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
from . import current_retained_build as current_build
from .acquisition import _run_owned_preparation, sanitized_environment
from .operation_config import absolute_path
from .operation_store import create_directory, write_record
from .protocols import D3C_BASE_COMMIT, D3C_EXPERIMENT_COMMIT, D3C_PROTOCOL_RAW_SHA256, STUDY_RETAINED_KEY, read_canonical_json

KIND = "official-retained-key-prepared-v1"
KIND_V2 = "official-retained-key-prepared-v2"


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


def prepare_retained_key(*, root: Path, build_root: Path, corpus_dir: Path,
                         profile_version: int = 1) -> PreparedRetainedKey:
    """Prepare once under the frozen timeout, then rehash the worker's files."""
    require_clean_head(root)
    require_retained_namespace(root, build_root)
    _run_owned_preparation(study_id=STUDY_RETAINED_KEY, root=root, build_root=build_root,
                           corpus_dir=corpus_dir, profile_version=profile_version)
    return load_prepared_retained_key(build_root / "prepared-retained-key.json", root=root)


def _prepare_retained_key_body(*, root: Path, build_root: Path, corpus_dir: Path,
                               profile_version: int = 1) -> PreparedRetainedKey:
    """Build the two historical adapters and corpus; execute no measurement."""

    require_clean_head(root)
    require_retained_namespace(root, build_root)
    create_directory(build_root, exclusive=True)
    runner = legacy_runner()
    protocol, protocol_sha = runner.load_protocol()
    if "sha256:" + protocol_sha != D3C_PROTOCOL_RAW_SHA256:
        raise BenchError(BM_IDENTITY_INVALID, "the retained backend protocol changed")
    source = runner.worktree(str(build_root), D3C_BASE_COMMIT)
    base_profile = current_build.release_profile_settings(Path(source)) if profile_version == 2 else None
    base = runner.build(source, str(build_root / "build" / "A"), False)
    runner.switch(source, D3C_BASE_COMMIT, D3C_EXPERIMENT_COMMIT)
    policy: dict[str, Any] | None = None
    toolchain: dict[str, Any] | None = None
    policy_digest: str | None = None
    if profile_version == 2:
        experiment_profile = current_build.release_profile_settings(Path(source))
        if experiment_profile != base_profile:
            raise BenchError(
                BM_IDENTITY_INVALID,
                "the pinned revisions select different release profile settings",
                field_path="release_profile",
            )
        toolchain = current_build.observe_toolchain(
            environment=sanitized_environment(None), cwd=Path(source)
        )
        policy = current_build.current_v2_build_policy(source_root=Path(source), toolchain=toolchain)
        policy_digest = current_build.build_policy_digest(policy)
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
    document: dict[str, Any] = {
        "schema": KIND, "source_root": str(root), "corpus_dir": str(corpus_dir),
        "protocol_digest": D3C_PROTOCOL_RAW_SHA256, "corpus_digest": corpus_digest,
        "binaries": {"A": base, "B": experiment},
    }
    if profile_version == 2:
        assert policy is not None and toolchain is not None and policy_digest is not None
        for arm, record, expected_sha, expected_feature in (
            ("A", base, D3C_BASE_COMMIT, False),
            ("B", experiment, D3C_EXPERIMENT_COMMIT, current_build.EXPERIMENT_FEATURE),
        ):
            current_build.require_closed_argv(
                record,
                source_root=Path(source),
                target_dir=Path(build_root) / "build" / arm,
                feature=expected_feature,
            )
            current_build.require_current_v2_build(
                {**record, "arm": arm},
                arm=arm,
                expected_source_sha=expected_sha,
                expected_feature=expected_feature,
                root=Path(build_root),
                policy_digest=policy_digest,
                expected_policy_digest=policy_digest,
            )
        document = {
            "schema": KIND_V2,
            "source_root": str(root),
            "corpus_dir": str(corpus_dir),
            "protocol_digest": D3C_PROTOCOL_RAW_SHA256,
            "corpus_digest": corpus_digest,
            "binaries": {"A": base, "B": experiment},
            "build_policy": policy,
            "build_policy_digest": policy_digest,
            "toolchain": toolchain,
        }
    path = build_root / "prepared-retained-key.json"
    write_record(build_root, path.name, document)
    return load_prepared_retained_key(path, root=root)


_PREPARED_KEYS = {"schema", "source_root", "corpus_dir", "protocol_digest", "corpus_digest", "binaries"}
_PREPARED_KEYS_V2 = _PREPARED_KEYS | {"build_policy", "build_policy_digest", "toolchain"}


def load_prepared_retained_key(manifest_path: Path, *, root: Path) -> PreparedRetainedKey:
    raw = read_canonical_json(manifest_path)
    schema = raw.get("schema") if isinstance(raw, dict) else None
    keys = _PREPARED_KEYS_V2 if schema == KIND_V2 else _PREPARED_KEYS
    document = require_closed(raw, "retained-prepared", keys)
    if document["schema"] not in (KIND, KIND_V2) or document["source_root"] != str(root) or document["protocol_digest"] != D3C_PROTOCOL_RAW_SHA256:
        raise BenchError(BM_IDENTITY_INVALID, "prepared retained-key identity differs")
    if document["schema"] == KIND_V2:
        if current_build.build_policy_digest(document["build_policy"]) != document["build_policy_digest"]:
            raise BenchError(BM_IDENTITY_INVALID, "the prepared build policy digest does not match its record")
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
    """Check a completed campaign's own executables against the approved policy.

    Current-v2 binds every arm to the campaign's own premeasurement record: two
    independent builds of one revision are allowed to differ in bytes, so the
    preparation binaries are authority for *inputs and recipe*, not for the exact
    output of a later build. Historical v1 keeps its original byte equality.
    """

    fresh = load_prepared_retained_key(prepared.manifest_path, root=prepared.source_root)
    if fresh.binary_digest != prepared.binary_digest:
        raise BenchError(BM_IDENTITY_INVALID, "prepared binaries changed during acquisition")
    manifest = read_canonical_json(directory / "manifest.json")
    expected_arms = {"A", "B"} if control else {"A", "L", "P", "H"}
    arms = manifest.get("arms")
    if not isinstance(arms, dict) or set(arms) != expected_arms:
        raise BenchError(BM_IDENTITY_INVALID, "the completed campaign does not contain the full arm set")
    if fresh.manifest["schema"] == KIND_V2:
        policy_digest = fresh.manifest["build_policy_digest"]
        binding = current_build.read_build_binding(Path(directory) / "raw" / current_build.BINDING_NAME)
        current_build.require_binding_matches_arms(binding, arms=arms, expected_policy_digest=policy_digest)
        for arm, item in arms.items():
            experiment_arm = not control and arm != "A"
            expected_sha = D3C_EXPERIMENT_COMMIT if experiment_arm else D3C_BASE_COMMIT
            expected_feature = current_build.EXPERIMENT_FEATURE if experiment_arm else False
            if item.get("source_sha") != expected_sha:
                raise BenchError(BM_IDENTITY_INVALID, "a campaign arm used the wrong source revision", field_path="source_sha")
            current_build.require_current_v2_build(
                {**binding["builds"][arm], "arm": arm},
                arm=arm,
                expected_source_sha=expected_sha,
                expected_feature=expected_feature,
                root=Path(prepared.source_root) / "target" / "pr15i-d3-c",
                policy_digest=policy_digest,
                expected_policy_digest=policy_digest,
            )
        return
    for arm, item in arms.items():
        expected = fresh.manifest["binaries"]["A" if control or arm == "A" else "B"]
        if item.get("binary_sha256") != expected["sha256"] or item.get("binary_bytes") != expected["bytes"] or item.get("source_sha") != expected["source_sha"]:
            raise BenchError(BM_IDENTITY_INVALID, "a campaign used a binary outside the approved preparation", field_path="binary_manifest_digest")
