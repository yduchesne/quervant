"""Closed current-baseline-v2 build policy for the retained-key study (BM-09).

The v2 rule is that independently compiled executables need not be byte-identical:
two builds of the same pinned revision from different directories legitimately
differ because Cargo derives each unit's ``-C metadata`` (and therefore symbol
hashes) from the absolute manifest path. What must be identical is the
*operator-controlled* compilation policy, and every actual executable must be
checked against its own observed build record before any index or query.

This module owns the single shared policy used by preparation and by every
campaign, plus the per-build own-artifact barrier and the v2 build-binding
record. The frozen historical v1 builder and verifier are never modified or
reimplemented here; ``official.retained_backend.legacy_runner().build`` remains
the only Cargo build operation.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import content_digest
from ..config.errors import BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from ..evidence.hashing import sha256_regular_file
from ..qualification.contracts import require_closed
from .operation_config import absolute_path
from .protocols import D3C_BASE_COMMIT, D3C_EXPERIMENT_COMMIT

POLICY_KIND = "current-v2-retained-build-policy"
POLICY_SCHEMA_VERSION = 2
BINDING_KIND = "current-v2-retained-premeasurement-binding"
BINDING_SCHEMA_VERSION = 2
BINDING_NAME = "official-premeasurement-binaries.json"

EXPERIMENT_FEATURE = "quervant-core/pr15i-d3c-experiment"
FROZEN_ARGV_PREFIX = ("cargo", "build", "--release", "--locked")
PATH_OPERANDS = ("--manifest-path", "--target-dir")
FEATURE_MATRIX = {"A": False, "B": EXPERIMENT_FEATURE}
BINARY_SUFFIX = ("release", "pr15d-quervant-adapter")
MAX_BINARY_BYTES = 536_870_912
TOOLCHAIN_TIMEOUT_SECONDS = 120

# Compiler/build settings that must never change per arm or per campaign. The v1
# runner already refuses the exact names below; v2 additionally refuses any
# prefixed override so a new Cargo knob cannot silently alter codegen.
_FORBIDDEN_EXACT = (
    "RUSTFLAGS",
    "CARGO_ENCODED_RUSTFLAGS",
    "RUSTC",
    "RUSTC_WRAPPER",
    "CARGO_INCREMENTAL",
    "SOURCE_DATE_EPOCH",
    "CARGO_UNSTABLE_",
)
_FORBIDDEN_PREFIXES = ("CARGO_PROFILE_", "CARGO_BUILD_", "CARGO_TARGET_")

_POLICY_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "toolchain",
        "target",
        "release_profile",
        "fixed_argv",
        "path_operands",
        "feature_matrix",
        "source_pins",
        "forbidden_environment",
    }
)
_TOOLCHAIN_KEYS = frozenset({"cargo_version", "rustc_version", "rustc_host", "rustc_release", "llvm_version"})
_BINDING_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "campaign",
        "control",
        "build_policy_digest",
        "source_base_sha",
        "source_experiment_sha",
        "toolchain",
        "builds",
        "query_operations_started",
    }
)
_BUILD_KEYS = frozenset({"arm", "source_sha", "feature", "argv", "binary", "sha256", "bytes"})


def _fail(message: str, field: str = "binary_manifest_digest") -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def require_closed_build_environment(environment: Mapping[str, Any]) -> None:
    """Reject any ambient or wrapper setting that could change compiler options."""

    for key in environment:
        name = str(key)
        if name in _FORBIDDEN_EXACT or name.startswith(_FORBIDDEN_PREFIXES):
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"the current-v2 build environment carries an unapproved setting: {name}",
                field_path="environment",
            )


def _parse_rustc_version(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        values[key.strip()] = value.strip()
    for key in ("release", "host", "LLVM version"):
        if key not in values:
            raise BenchError(BM_IDENTITY_INVALID, "the rustc identity could not be established", field_path="toolchain")
    version = text.splitlines()[0].strip() if text.strip() else ""
    if not version.startswith("rustc "):
        raise BenchError(BM_IDENTITY_INVALID, "the rustc identity could not be established", field_path="toolchain")
    return {
        "rustc_version": version.split(" ", 1)[1],
        "rustc_host": values["host"],
        "rustc_release": values["release"],
        "llvm_version": values["LLVM version"],
    }


def observe_toolchain(*, environment: Mapping[str, Any], cwd: Path) -> dict[str, str]:
    """Observe the actual compiler identity used for a build (no ambient flags)."""

    require_closed_build_environment(environment)
    env = {str(key): str(value) for key, value in environment.items()}
    observed: dict[str, str] = {}
    for key, argv in (("cargo", ("cargo", "--version")), ("rustc", ("rustc", "-vV"))):
        try:
            result = subprocess.run(
                list(argv),
                cwd=str(cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=TOOLCHAIN_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:  # pragma: no cover - defensive
            raise BenchError(
                BM_IDENTITY_INVALID, f"the {key} identity could not be observed", field_path="toolchain"
            ) from error
        text = result.stdout.decode("utf-8", "replace")
        if result.returncode != 0:
            raise BenchError(BM_IDENTITY_INVALID, f"the {key} identity could not be observed", field_path="toolchain")
        observed[key] = text
    cargo_line = observed["cargo"].strip().splitlines()[0] if observed["cargo"].strip() else ""
    if not cargo_line.startswith("cargo "):
        raise BenchError(BM_IDENTITY_INVALID, "the cargo identity could not be established", field_path="toolchain")
    parsed = _parse_rustc_version(observed["rustc"])
    parsed["cargo_version"] = cargo_line.split(" ", 1)[1]
    return parsed


def _profile_table(manifest: Path) -> dict[str, Any]:
    if not manifest.is_file():
        raise BenchError(BM_IDENTITY_INVALID, "a pinned Cargo manifest is missing", field_path="release_profile")
    document = tomllib.loads(manifest.read_text(encoding="utf-8"))
    profile = document.get("profile")
    if not isinstance(profile, dict):
        return {}
    # Only the tables/values that affect compiled code are relevant; Cargo's own
    # defaults are implied, so an empty table and an explicit default differ but
    # both are recorded verbatim and must stay stable across builds.
    return {name: table for name, table in sorted(profile.items()) if isinstance(table, dict)}


def release_profile_settings(source_root: Path) -> dict[str, str]:
    """Digest the operator-controlled release profile of the pinned sources."""

    root = Path(source_root)
    adapter = root / "benchmarks" / "pr15d" / "adapters" / "quervant" / "Cargo.toml"
    workspace = root / "Cargo.toml"
    return {
        "adapter": content_digest({"kind": "current-v2-release-profile", "manifest": "adapter", "profile": _profile_table(adapter)}),
        "workspace": content_digest({"kind": "current-v2-release-profile", "manifest": "workspace", "profile": _profile_table(workspace)}),
    }


def release_profile_settings_from_git(checkout: Path, revision: str) -> dict[str, str]:
    """Read the pinned release profile straight from a Git revision.

    Used for a projected replay working copy, which carries no ``compile-source``
    checkout: the measured revisions are read with ``git show`` so the profile is
    still taken from the exact source the campaign was built from.
    """

    profiles: dict[str, Any] = {}
    for label, relative in (("adapter", "benchmarks/pr15d/adapters/quervant/Cargo.toml"), ("workspace", "Cargo.toml")):
        completed = subprocess.run(
            ["git", "-C", str(checkout), "show", f"{revision}:{relative}"],
            capture_output=True, timeout=TOOLCHAIN_TIMEOUT_SECONDS, check=False,
        )
        if completed.returncode != 0:
            raise BenchError(BM_IDENTITY_INVALID, "a pinned Cargo manifest could not be read", field_path="release_profile")
        document = tomllib.loads(completed.stdout.decode("utf-8"))
        profile = document.get("profile")
        profiles[label] = {name: table for name, table in sorted(profile.items()) if isinstance(table, dict)} if isinstance(profile, dict) else {}
    return {
        label: content_digest({"kind": "current-v2-release-profile", "manifest": label, "profile": value})
        for label, value in profiles.items()
    }


def current_v2_build_policy(*, source_root: Path | None = None, toolchain: Mapping[str, Any],
                            release_profile: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return the one closed build policy for the whole current-v2 study."""

    identity = require_closed(dict(toolchain), "toolchain", _TOOLCHAIN_KEYS)
    if release_profile is None and source_root is None:
        raise BenchError(BM_IDENTITY_INVALID, "a build policy needs a source root or a release profile", field_path="release_profile")
    document = {
        "kind": POLICY_KIND,
        "schema_version": POLICY_SCHEMA_VERSION,
        "toolchain": {key: identity[key] for key in sorted(_TOOLCHAIN_KEYS)},
        "target": identity["rustc_host"],
        "release_profile": dict(release_profile) if release_profile is not None
        else release_profile_settings(Path(str(source_root))),
        "fixed_argv": list(FROZEN_ARGV_PREFIX),
        "path_operands": list(PATH_OPERANDS),
        "feature_matrix": dict(FEATURE_MATRIX),
        "source_pins": {"base": D3C_BASE_COMMIT, "experiment": D3C_EXPERIMENT_COMMIT},
        "forbidden_environment": sorted(
            [*_FORBIDDEN_EXACT, *[f"{prefix}*" for prefix in _FORBIDDEN_PREFIXES]]
        ),
    }
    return require_closed(document, "build-policy", _POLICY_KEYS)


def build_policy_digest(policy: Mapping[str, Any]) -> str:
    return content_digest(require_closed(dict(policy), "build-policy", _POLICY_KEYS))


def require_same_build_policy(authorised: Mapping[str, Any], observed: Mapping[str, Any]) -> str:
    """Fail closed unless the observed policy is the authorised one, exactly."""

    expected = build_policy_digest(authorised)
    actual = build_policy_digest(observed)
    if expected != actual:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the observed compiler/build policy differs from the authorised current-v2 policy",
            field_path="build_policy_digest",
        )
    return expected


def _expected_argv(manifest: Path, target: Path, feature: Any) -> list[str]:
    argv = [*FROZEN_ARGV_PREFIX, "--manifest-path", str(manifest), "--target-dir", str(target)]
    if feature is not False:
        argv += ["--features", str(feature)]
    return argv


def require_closed_argv(record: Mapping[str, Any], *, source_root: Path, target_dir: Path, feature: Any) -> None:
    """The frozen builder's argv may differ only in its two path operands and feature."""

    argv = record.get("argv")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise _fail("a current-v2 build record has no argv")
    if feature not in (False, EXPERIMENT_FEATURE):
        raise _fail("a current-v2 build requested an unapproved Cargo feature")
    manifest = Path(str(source_root)) / "benchmarks" / "pr15d" / "adapters" / "quervant" / "Cargo.toml"
    if argv != _expected_argv(manifest, Path(str(target_dir)), feature):
        raise _fail("a current-v2 build used options outside the closed build policy")


def _require_closed_argv_for_record(record: Mapping[str, Any], *, path: Path, feature: Any) -> None:
    """Validate the recorded argv against the closed policy shape.

    Only the two path operands and the approved experimental feature may vary;
    the executable's own directory must be the recorded ``--target-dir``.
    """

    argv = record.get("argv")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise _fail("a current-v2 build record has no argv")
    if feature not in (False, EXPERIMENT_FEATURE):
        raise _fail("a current-v2 build requested an unapproved Cargo feature")
    if len(argv) != (8 if feature is False else 10):
        raise _fail("a current-v2 build used options outside the closed build policy")
    if tuple(argv[:4]) != FROZEN_ARGV_PREFIX:
        raise _fail("a current-v2 build used options outside the closed build policy")
    if argv[4] != "--manifest-path" or argv[6] != "--target-dir":
        raise _fail("a current-v2 build used options outside the closed build policy")
    manifest = Path(argv[5])
    target = Path(argv[7])
    if not manifest.is_absolute() or manifest.name != "Cargo.toml":
        raise _fail("a current-v2 build used an unexpected manifest operand")
    if not target.is_absolute():
        raise _fail("a current-v2 build used an unexpected target operand")
    if path.parent.parent != target:
        raise _fail("a current-v2 executable is outside its recorded target directory", "binary")
    if feature is not False and (argv[8] != "--features" or argv[9] != feature):
        raise _fail("a current-v2 build used an unapproved feature selection", "feature")


def require_current_v2_build(
    record: Mapping[str, Any],
    *,
    arm: str,
    expected_source_sha: str,
    expected_feature: Any,
    root: Path,
    policy_digest: str,
    expected_policy_digest: str,
) -> str:
    """Check one actual executable against its own observed build record (v2).

    No comparison with any other build is performed: independent builds may
    legitimately differ. The path, regular-file/single-link status, size budget,
    freshly rehashed bytes, source revision, feature selection and build policy
    must all agree with what this build just reported.
    """

    if policy_digest != expected_policy_digest:
        raise _fail("a current-v2 build was compiled under a different build policy", "build_policy_digest")
    record = require_closed(dict(record), "build-record", _BUILD_KEYS)
    if record["arm"] != arm:
        raise _fail("a current-v2 build record belongs to another arm", "arm")
    if record["source_sha"] != expected_source_sha:
        raise _fail("a current-v2 build used a different source revision", "source_sha")
    if record["feature"] is not expected_feature:
        raise _fail("a current-v2 build used the wrong feature selection", "feature")
    binary = absolute_path(str(record["binary"]), "binary")
    path = Path(binary)
    _require_closed_argv_for_record(record, path=path, feature=record["feature"])
    if path.is_symlink() or not path.is_file():
        raise _fail("a current-v2 executable is not a regular file", "binary")
    if path.name != BINARY_SUFFIX[-1] or path.parent.name != BINARY_SUFFIX[0]:
        raise _fail("a current-v2 executable is outside its fixed output path", "binary")
    root_path = Path(str(root)).resolve()
    if root_path not in path.resolve().parents:
        raise _fail("a current-v2 executable is outside the authorised root", "binary")
    if path.stat().st_nlink != 1:
        raise _fail("a current-v2 executable is hardlinked", "binary")
    digest, size = sha256_regular_file(path.parent, path.name, max_bytes=MAX_BINARY_BYTES)
    if type(record["bytes"]) is not int or size != record["bytes"] or size <= 0:
        raise _fail("a current-v2 executable changed size after its build", "binary_manifest_digest")
    if digest != "sha256:" + str(record["sha256"]):
        raise _fail("a current-v2 executable changed after its build", "binary_manifest_digest")
    return digest


def build_binding_document(
    *,
    campaign: str,
    control: bool,
    policy_digest: str,
    builds: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """The versioned v2 premeasurement record written before any index/query."""

    document = {
        "kind": BINDING_KIND,
        "schema_version": BINDING_SCHEMA_VERSION,
        "campaign": campaign,
        "control": bool(control),
        "build_policy_digest": policy_digest,
        "source_base_sha": D3C_BASE_COMMIT,
        "source_experiment_sha": D3C_EXPERIMENT_COMMIT,
        "toolchain": dict(builds["__toolchain__"]),
        "builds": {arm: dict(item) for arm, item in builds.items() if arm != "__toolchain__"},
        "query_operations_started": False,
    }
    return require_closed(document, "build-binding", _BINDING_KEYS)


def read_build_binding(path: Path) -> dict[str, Any]:
    from .protocols import read_canonical_json

    document = require_closed(read_canonical_json(Path(path)), "build-binding", _BINDING_KEYS)
    if document["kind"] != BINDING_KIND or document["schema_version"] != BINDING_SCHEMA_VERSION:
        raise _fail("the current-v2 build-binding record has an unexpected identity", "build_policy_digest")
    if document["query_operations_started"] is not False:
        raise _fail("the current-v2 build-binding record was written after a query started", "build_policy_digest")
    builds = document["builds"]
    if not isinstance(builds, dict) or not builds:
        raise _fail("the current-v2 build-binding record has no builds", "build_policy_digest")
    for arm, item in builds.items():
        entry = require_closed(dict(item), f"builds.{arm}", _BUILD_KEYS)
        if entry["arm"] != arm:
            raise _fail("a build-binding entry belongs to another arm", "build_policy_digest")
    return document


def require_binding_matches_arms(
    binding: Mapping[str, Any],
    *,
    arms: Mapping[str, Mapping[str, Any]],
    expected_policy_digest: str,
) -> None:
    """Bind every manifest arm to the actual executable recorded before measuring."""

    if binding["build_policy_digest"] != expected_policy_digest:
        raise _fail("the campaign build binding uses another build policy", "build_policy_digest")
    builds = binding["builds"]
    for arm, item in arms.items():
        recorded = builds.get(arm)
        if recorded is None:
            raise _fail("an arm is missing from the current-v2 build binding", "build_policy_digest")
        if (recorded["sha256"], recorded["bytes"], recorded["source_sha"], recorded["feature"]) != (
            item.get("binary_sha256"),
            item.get("binary_bytes"),
            item.get("source_sha"),
            item.get("feature", recorded["feature"]),
        ):
            raise _fail("a manifest arm does not match its own premeasurement executable", "binary_manifest_digest")


def os_environment(pairs: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Small test seam: a closed environment derived from ``os.environ`` by default."""

    source = os.environ if pairs is None else pairs
    return {str(key): str(value) for key, value in source.items()}
