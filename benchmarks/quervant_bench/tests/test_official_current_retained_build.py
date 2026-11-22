"""BM-09 current-v2: closed build policy, per-build barrier and v2 verifier.

These tests exercise the *current-v2* rule that independently compiled
executables need not be byte-identical while every actual artifact is still
attributed to its own build, its pinned source revision, its approved feature
selection and one shared compiler policy.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.codec import canonical_document_bytes
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.official import current_retained_build as build_policy

TOOLCHAIN = {
    "cargo_version": "1.98.1 (abcdef 2026-01-01)",
    "rustc_version": "1.98.1 (abcdef 2026-01-01)",
    "rustc_host": "x86_64-unknown-linux-gnu",
    "rustc_release": "1.98.1",
    "llvm_version": "21.0.0",
}
BASE = "39dbd9f571a58bea8cc03d5a406533298e809bfe"
EXPERIMENT = "3ad6c5184fbe9c011abb731415a007e3f19d21de"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _source(root: Path, profile: str = "") -> Path:
    _write(root / "Cargo.toml", "[workspace]\nmembers = []\n" + profile)
    _write(
        root / "benchmarks/pr15d/adapters/quervant/Cargo.toml",
        '[package]\nname = "pr15d-quervant-adapter"\nversion = "0.1.0"\n' + profile,
    )
    return root


class ClosedBuildPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_rk_t01_policy_is_stable_and_names_the_approved_controls(self) -> None:
        source = _source(self.root / "source")
        first = build_policy.current_v2_build_policy(source_root=source, toolchain=TOOLCHAIN)
        second = build_policy.current_v2_build_policy(source_root=source, toolchain=TOOLCHAIN)
        self.assertEqual(build_policy.build_policy_digest(first), build_policy.build_policy_digest(second))
        self.assertEqual(first["fixed_argv"], ["cargo", "build", "--release", "--locked"])
        self.assertEqual(first["feature_matrix"], {"A": False, "B": build_policy.EXPERIMENT_FEATURE})
        self.assertEqual(first["source_pins"], {"base": BASE, "experiment": EXPERIMENT})
        self.assertEqual(first["target"], TOOLCHAIN["rustc_host"])

    def test_rk_t02_a_different_toolchain_is_a_different_policy(self) -> None:
        source = _source(self.root / "source")
        authorised = build_policy.current_v2_build_policy(source_root=source, toolchain=TOOLCHAIN)
        drifted = dict(TOOLCHAIN, rustc_release="1.99.0", rustc_version="1.99.0 (abcdef 2026-02-01)")
        observed = build_policy.current_v2_build_policy(source_root=source, toolchain=drifted)
        with self.assertRaises(BenchError) as raised:
            build_policy.require_same_build_policy(authorised, observed)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "build_policy_digest")

    def test_rk_t03_a_changed_release_profile_is_a_different_policy(self) -> None:
        plain = _source(self.root / "plain")
        optimised = _source(self.root / "optimised", '\n[profile.release]\nopt-level = 3\n')
        first = build_policy.current_v2_build_policy(source_root=plain, toolchain=TOOLCHAIN)
        second = build_policy.current_v2_build_policy(source_root=optimised, toolchain=TOOLCHAIN)
        self.assertNotEqual(build_policy.build_policy_digest(first), build_policy.build_policy_digest(second))

    def test_rk_t04_ambient_compiler_settings_are_rejected(self) -> None:
        for name in (
            "RUSTFLAGS",
            "CARGO_ENCODED_RUSTFLAGS",
            "RUSTC",
            "RUSTC_WRAPPER",
            "CARGO_INCREMENTAL",
            "SOURCE_DATE_EPOCH",
            "CARGO_PROFILE_RELEASE_OPT_LEVEL",
            "CARGO_BUILD_RUSTFLAGS",
            "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER",
        ):
            with self.assertRaises(BenchError) as raised:
                build_policy.require_closed_build_environment({"PATH": "/usr/bin", name: "1"})
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            self.assertEqual(raised.exception.field_path, "environment")
        build_policy.require_closed_build_environment({"PATH": "/usr/bin", "LANG": "C.UTF-8"})

    def test_rk_t05_policy_record_rejects_unknown_keys(self) -> None:
        source = _source(self.root / "source")
        policy = build_policy.current_v2_build_policy(source_root=source, toolchain=TOOLCHAIN)
        with self.assertRaises(BenchError):
            build_policy.build_policy_digest({**policy, "skip_equality": True})


class PerBuildBarrierTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.source = _source(self.root / "campaign" / "compile-source")
        self.policy = build_policy.current_v2_build_policy(source_root=self.source, toolchain=TOOLCHAIN)
        self.policy_digest = build_policy.build_policy_digest(self.policy)
        self.target = self.root / "campaign" / "build" / "A"
        self.target.mkdir(parents=True)
        self.binary = self.target / "release" / "pr15d-quervant-adapter"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b"first independent build")

    def _record(self, **overrides: object) -> dict[str, object]:
        import hashlib

        digest = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        record: dict[str, object] = {
            "arm": "A",
            "source_sha": BASE,
            "feature": False,
            "argv": [
                "cargo",
                "build",
                "--release",
                "--locked",
                "--manifest-path",
                str(self.source / "benchmarks/pr15d/adapters/quervant/Cargo.toml"),
                "--target-dir",
                str(self.target),
            ],
            "binary": str(self.binary),
            "sha256": digest,
            "bytes": self.binary.stat().st_size,
        }
        record.update(overrides)
        return record

    def _check(self, **overrides: object) -> str:
        record = self._record(**overrides)
        return build_policy.require_current_v2_build(
            record,
            arm="A",
            expected_source_sha=BASE,
            expected_feature=False,
            root=self.root,
            policy_digest=self.policy_digest,
            expected_policy_digest=self.policy_digest,
        )

    def test_rk_t06_a_valid_build_binds_its_own_bytes(self) -> None:
        digest = self._check()
        self.assertTrue(digest.startswith("sha256:"))
        self.assertTrue(digest.endswith(__import__("hashlib").sha256(self.binary.read_bytes()).hexdigest()))

    def test_rk_t07_independent_builds_may_differ(self) -> None:
        """Two different executables each bind to their own record."""

        other_target = self.root / "campaign-b" / "build" / "A"
        other_target.mkdir(parents=True)
        other = other_target / "release" / "pr15d-quervant-adapter"
        other.parent.mkdir(parents=True)
        other.write_bytes(b"second independent build with other bytes")
        import hashlib

        second = {
            "arm": "A",
            "source_sha": BASE,
            "feature": False,
            "argv": [
                "cargo",
                "build",
                "--release",
                "--locked",
                "--manifest-path",
                str(self.source / "benchmarks/pr15d/adapters/quervant/Cargo.toml"),
                "--target-dir",
                str(other_target),
            ],
            "binary": str(other),
            "sha256": hashlib.sha256(other.read_bytes()).hexdigest(),
            "bytes": other.stat().st_size,
        }
        first_digest = self._check()
        second_digest = build_policy.require_current_v2_build(
            second,
            arm="A",
            expected_source_sha=BASE,
            expected_feature=False,
            root=self.root,
            policy_digest=self.policy_digest,
            expected_policy_digest=self.policy_digest,
        )
        self.assertNotEqual(first_digest, second_digest)

    def test_rk_t08_mutated_bytes_after_build_are_rejected(self) -> None:
        record = self._record()
        self.binary.write_bytes(b"mutated after the build record was written")
        with self.assertRaises(BenchError) as raised:
            build_policy.require_current_v2_build(
                record,
                arm="A",
                expected_source_sha=BASE,
                expected_feature=False,
                root=self.root,
                policy_digest=self.policy_digest,
                expected_policy_digest=self.policy_digest,
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "binary_manifest_digest")

    def test_rk_t09_wrong_source_or_feature_is_rejected(self) -> None:
        for overrides, field in (
            ({"source_sha": EXPERIMENT}, "source_sha"),
            ({"feature": True}, "feature"),
        ):
            with self.assertRaises(BenchError) as raised:
                self._check(**overrides)
            self.assertEqual(raised.exception.field_path, field)

    def test_rk_t10_extra_build_options_are_rejected(self) -> None:
        argv = list(self._record()["argv"]) + ["--config", "build.rustflags=[\"-Cstrip=symbols\"]"]
        with self.assertRaises(BenchError) as raised:
            self._check(argv=argv)
        self.assertEqual(raised.exception.field_path, "binary_manifest_digest")

    def test_rk_t11_an_unapproved_feature_is_rejected(self) -> None:
        argv = list(self._record()["argv"]) + ["--features", "quervant-core/some-other-experiment"]
        with self.assertRaises(BenchError):
            build_policy.require_closed_argv(
                {"argv": argv}, source_root=self.source, target_dir=self.target, feature=True
            )

    def test_rk_t12_symlinked_or_hardlinked_executables_are_rejected(self) -> None:
        link = self.binary.with_name("linked")
        link.symlink_to(self.binary)
        with self.assertRaises(BenchError):
            self._check(binary=str(link))
        link.unlink()
        hard = self.binary.with_name("hard")
        os.link(self.binary, hard)
        with self.assertRaises(BenchError) as raised:
            self._check(binary=str(hard))
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_rk_t13_executables_outside_the_root_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as far:
            outside = Path(far) / "release" / "pr15d-quervant-adapter"
            outside.parent.mkdir(parents=True)
            outside.write_bytes(self.binary.read_bytes())
            with self.assertRaises(BenchError):
                self._check(binary=str(outside))

    def test_rk_t14_wrong_policy_digest_is_rejected(self) -> None:
        with self.assertRaises(BenchError) as raised:
            build_policy.require_current_v2_build(
                self._record(),
                arm="A",
                expected_source_sha=BASE,
                expected_feature=False,
                root=self.root,
                policy_digest="sha256:" + "0" * 64,
                expected_policy_digest=self.policy_digest,
            )
        self.assertEqual(raised.exception.field_path, "build_policy_digest")


class BuildBindingRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.policy_digest = "sha256:" + "a" * 64

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _builds(self) -> dict[str, dict[str, object]]:
        return {
            "A": {"arm": "A", "source_sha": BASE, "feature": False, "argv": ["cargo"], "binary": "/b/A",
                   "sha256": "a" * 64, "bytes": 10},
            "B": {"arm": "B", "source_sha": BASE, "feature": False, "argv": ["cargo"], "binary": "/b/B",
                   "sha256": "b" * 64, "bytes": 11},
            "__toolchain__": dict(TOOLCHAIN),
        }

    def test_rk_t15_binding_is_written_before_measurement_and_round_trips(self) -> None:
        document = build_policy.build_binding_document(
            campaign="d3c-v3r3-base-aa-01", control=True, policy_digest=self.policy_digest, builds=self._builds()
        )
        self.assertIs(document["query_operations_started"], False)
        path = self.root / "raw" / build_policy.BINDING_NAME
        path.parent.mkdir(parents=True)
        path.write_bytes(canonical_document_bytes(document))
        restored = build_policy.read_build_binding(path)
        self.assertEqual(restored["campaign"], "d3c-v3r3-base-aa-01")
        self.assertEqual(set(restored["builds"]), {"A", "B"})

    def test_rk_t16_a_binding_written_after_a_query_is_rejected(self) -> None:
        document = build_policy.build_binding_document(
            campaign="d3c-v3r3-base-aa-01", control=True, policy_digest=self.policy_digest, builds=self._builds()
        )
        document["query_operations_started"] = True
        path = self.root / "raw" / build_policy.BINDING_NAME
        path.parent.mkdir(parents=True)
        path.write_bytes(canonical_document_bytes(document))
        with self.assertRaises(BenchError):
            build_policy.read_build_binding(path)

    def test_rk_t17_an_arm_that_does_not_match_its_binding_is_rejected(self) -> None:
        document = build_policy.build_binding_document(
            campaign="d3c-v3r3-base-aa-01", control=True, policy_digest=self.policy_digest, builds=self._builds()
        )
        arms = {
            "A": {"binary_sha256": "a" * 64, "binary_bytes": 10, "source_sha": BASE, "feature": False},
            "B": {"binary_sha256": "c" * 64, "binary_bytes": 11, "source_sha": BASE, "feature": False},
        }
        with self.assertRaises(BenchError) as raised:
            build_policy.require_binding_matches_arms(document, arms=arms, expected_policy_digest=self.policy_digest)
        self.assertEqual(raised.exception.field_path, "binary_manifest_digest")
        arms["B"]["binary_sha256"] = "b" * 64
        build_policy.require_binding_matches_arms(document, arms=arms, expected_policy_digest=self.policy_digest)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
