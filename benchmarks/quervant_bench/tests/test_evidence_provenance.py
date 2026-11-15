"""HASH-01…04 and PROV-01…09: raw-byte hashing and pinned provenance."""

from __future__ import annotations

import hashlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.evidence import provenance
from quervant_bench.evidence.hashing import (
    CHUNK_BYTES,
    sha256_regular_file,
    sha256_stream,
    source_file_set_digest,
)
from quervant_bench.evidence.provenance import (
    VALIDATOR_SOURCE_PATHS,
    require_clean_head,
    verify_build_file,
    verify_git_commit,
    verify_validator_source,
)


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.decode("utf-8")


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "synthetic@example.invalid")
    _git(repo, "config", "user.name", "Synthetic")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "alpha.txt").write_bytes(b"alpha\n")
    (repo / "beta.txt").write_bytes(b"beta\n")
    _git(repo, "add", "alpha.txt", "beta.txt")
    _git(repo, "commit", "-q", "-m", "synthetic")
    return repo, _git(repo, "rev-parse", "HEAD").strip()


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class HashingTests(unittest.TestCase):
    def test_hash_01_raw_byte_digests_match_reference(self) -> None:
        samples = [b"", b"x", b"a\x00b\xff", '{"ü":"✓"}\n'.encode("utf-8")]
        for payload in samples:
            with self.subTest(payload=payload):
                digest, length = sha256_stream(io.BytesIO(payload), max_bytes=1024)
                self.assertEqual(digest, _sha(payload))
                self.assertEqual(length, len(payload))

    def test_hash_02_changed_truncated_and_over_budget_inputs(self) -> None:
        original = b"abcdef"
        changed = b"abcdeg"
        self.assertNotEqual(_sha(original), _sha(changed))
        self.assertEqual(len(original), len(changed))
        with self.assertRaises(BenchError):
            sha256_stream(io.BytesIO(original), max_bytes=len(original) - 1)
        truncated, length = sha256_stream(
            io.BytesIO(original[:-1]), max_bytes=len(original)
        )
        self.assertNotEqual(truncated, _sha(original))
        self.assertEqual(length, len(original) - 1)

    def test_hash_03_caller_order_does_not_change_source_set_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_bytes(b"a\n")
            (root / "b.py").write_bytes(b"b\n")
            first = source_file_set_digest(root, ["a.py", "b.py"])
            second = source_file_set_digest(root, ["a.py", "b.py"])
            self.assertEqual(first, second)
            with self.assertRaises(BenchError):
                source_file_set_digest(root, ["b.py", "a.py"])

    def test_hash_04_changed_or_extra_source_changes_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_bytes(b"a\n")
            before = source_file_set_digest(root, ["a.py"])
            (root / "a.py").write_bytes(b"b\n")
            after = source_file_set_digest(root, ["a.py"])
            self.assertNotEqual(before, after)
            (root / "extra.py").write_bytes(b"extra\n")
            with_extra = source_file_set_digest(root, ["a.py", "extra.py"])
            self.assertNotEqual(after, with_extra)

    def test_hash_regular_file_detects_length_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.bin").write_bytes(b"12345")
            digest, length = sha256_regular_file(root, "file.bin", max_bytes=10)
            self.assertEqual(digest, _sha(b"12345"))
            self.assertEqual(length, 5)


class GitProvenanceTests(unittest.TestCase):
    def test_prov_01_pinned_commit_and_blobs_verify_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, commit = _make_repo(Path(tmp))
            expected = {
                "alpha.txt": _sha(b"alpha\n"),
                "beta.txt": _sha(b"beta\n"),
            }
            identity = verify_git_commit(repo, commit, expected_paths=expected)
            self.assertEqual(identity.commit, commit)
            self.assertEqual([blob.path for blob in identity.files], ["alpha.txt", "beta.txt"])
            self.assertEqual(identity.files[0].sha256, expected["alpha.txt"])
            self.assertEqual(_git(repo, "status", "--porcelain").strip(), "")

    def test_prov_02_wrong_absent_commit_and_changed_blob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, commit = _make_repo(Path(tmp))
            with self.assertRaises(BenchError) as raised:
                verify_git_commit(
                    repo, "0" * 40, expected_paths={"alpha.txt": _sha(b"alpha\n")}
                )
            self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
            with self.assertRaises(BenchError) as raised:
                verify_git_commit(
                    repo, commit, expected_paths={"missing.txt": _sha(b"x")}
                )
            self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
            with self.assertRaises(BenchError) as raised:
                verify_git_commit(
                    repo, commit, expected_paths={"alpha.txt": _sha(b"changed")}
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_prov_03_and_04_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, commit = _make_repo(Path(tmp))
            (repo / "alpha.txt").write_bytes(b"dirty\n")
            (repo / "untracked.txt").write_bytes(b"untracked\n")
            identity = verify_git_commit(
                repo, commit, expected_paths={"alpha.txt": _sha(b"alpha\n")}
            )
            self.assertEqual(identity.commit, commit)
            with self.assertRaises(BenchError) as raised:
                require_clean_head(repo)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_prov_08_unsafe_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, commit = _make_repo(Path(tmp))
            with self.assertRaises(BenchError) as raised:
                verify_git_commit(
                    repo, commit, expected_paths={"../escape": _sha(b"x")}
                )
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            with self.assertRaises(BenchError) as raised:
                verify_git_commit(repo, "deadbeef", expected_paths={"alpha.txt": _sha(b"x")})
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_prov_09_shell_metacharacters_are_not_shell_interpreted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _commit = _make_repo(root)
            weird = "a;b $(touch pwned).txt"
            (repo / weird).write_bytes(b"weird\n")
            _git(repo, "add", weird)
            _git(repo, "commit", "-q", "-m", "weird")
            commit = _git(repo, "rev-parse", "HEAD").strip()
            identity = verify_git_commit(
                repo, commit, expected_paths={weird: _sha(b"weird\n")}
            )
            self.assertEqual(identity.files[0].path, weird)
            self.assertFalse((root / "pwned").exists())
            with self.assertRaises(BenchError):
                verify_git_commit(repo, "deadbeef;touch x", expected_paths={})


class BuildAndValidatorIdentityTests(unittest.TestCase):
    def test_prov_05_benign_file_is_hashed_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = b"\x7fELF-not-really"
            (root / "artifact.bin").write_bytes(payload)
            identity = verify_build_file(root, "artifact.bin", _sha(payload))
            self.assertEqual(identity.digest, _sha(payload))
            self.assertEqual(identity.byte_length, len(payload))
            self.assertEqual((root / "artifact.bin").read_bytes(), payload)

    def test_prov_06_same_length_binary_change_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "artifact.bin").write_bytes(b"AAAA")
            with self.assertRaises(BenchError) as raised:
                verify_build_file(root, "artifact.bin", _sha(b"BBBB"))
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_prov_07_changed_validator_source_invalidates_the_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "one.py").write_bytes(b"one\n")
            (root / "two.py").write_bytes(b"two\n")
            expected = source_file_set_digest(root, ["one.py", "two.py"])
            self.assertEqual(
                verify_validator_source(root, ["one.py", "two.py"], expected), expected
            )
            (root / "one.py").write_bytes(b"changed\n")
            with self.assertRaises(BenchError) as raised:
                verify_validator_source(root, ["one.py", "two.py"], expected)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_prov_08_missing_validator_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(BenchError) as raised:
                verify_validator_source(root, ["missing.py"], _sha(b"x"))
            self.assertEqual(raised.exception.code, BM_FILE_MISSING)




PACKAGE_ROOT = Path(__file__).resolve().parents[1]

_EXPECTED_VALIDATOR_SOURCE_PATHS = (
    "__init__.py",
    "config/__init__.py",
    "config/codec.py",
    "config/contracts.py",
    "config/errors.py",
    "config/identity.py",
    "config/profiles.py",
    "config/schemas.py",
    "evidence/__init__.py",
    "evidence/admission.py",
    "evidence/archives.py",
    "evidence/hashing.py",
    "evidence/manifests.py",
    "evidence/paths.py",
    "evidence/provenance.py",
    "evidence/publication.py",
    "evidence/receipts.py",
    "host/__init__.py",
    "host/capabilities.py",
    "host/readiness.py",
)


class ValidatorSourceClosureTests(unittest.TestCase):
    def test_vs_01_validator_source_list_is_the_frozen_closure(self) -> None:
        self.assertEqual(
            VALIDATOR_SOURCE_PATHS, _EXPECTED_VALIDATOR_SOURCE_PATHS
        )
        self.assertEqual(len(VALIDATOR_SOURCE_PATHS), 20)
        self.assertEqual(
            list(VALIDATOR_SOURCE_PATHS), sorted(set(VALIDATOR_SOURCE_PATHS))
        )
        for relative in VALIDATOR_SOURCE_PATHS:
            path = PACKAGE_ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertFalse(path.is_symlink(), relative)
        for required in (
            "config/profiles.py",
            "host/capabilities.py",
            "host/readiness.py",
            "__init__.py",
            "host/__init__.py",
        ):
            self.assertIn(required, VALIDATOR_SOURCE_PATHS)


class _FakeGitProcess:
    """Minimal faithful fake for the Popen operations used by the verifier."""

    def __init__(
        self, payload: bytes, exit_on_wait: int | None = 0
    ) -> None:
        self.stdout = io.BytesIO(payload)
        self._code: int | None = None
        self._exit_on_wait = exit_on_wait
        self.killed = False
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        return self._code

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self._code is None:
            if self._exit_on_wait is None:  # pragma: no cover - hangs forever
                raise subprocess.TimeoutExpired("git", timeout or 0)
            self._code = self._exit_on_wait
        return self._code

    def kill(self) -> None:
        self.killed = True
        self._code = -9


class _SelectivePopen:
    """Route only blob-stream spawns to a fake; metadata keeps real Popen."""

    def __init__(self, fake) -> None:
        self._fake = fake
        self._original = subprocess.Popen

    def __call__(self, arguments, **kwargs):
        if isinstance(arguments, (list, tuple)) and "blob" in arguments:
            return self._fake
        return self._original(arguments, **kwargs)


class BoundedGitBlobTests(unittest.TestCase):
    def test_git_01_oversized_blob_is_rejected_before_stream_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, _commit = _make_repo(Path(tmp))
            (repo / "large.bin").write_bytes(b"x" * 1024)
            _git(repo, "add", "large.bin")
            _git(repo, "commit", "-q", "-m", "large")
            commit = _git(repo, "rev-parse", "HEAD").strip()
            original_popen = subprocess.Popen

            def forbidden(arguments, **kwargs):
                if isinstance(arguments, (list, tuple)) and "blob" in arguments:
                    raise AssertionError("blob stream must not spawn")
                return original_popen(arguments, **kwargs)

            with mock.patch.object(provenance, "_MAX_GIT_BLOB_BYTES", 512), mock.patch.object(
                provenance.subprocess,
                "Popen",
                side_effect=forbidden,
            ):
                with self.assertRaises(BenchError) as raised:
                    verify_git_commit(
                        repo,
                        commit,
                        expected_paths={"large.bin": _sha(b"x" * 1024)},
                    )
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_git_02_large_blob_streams_multiple_bounded_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, _commit = _make_repo(Path(tmp))
            size = 2 * CHUNK_BYTES + 17
            pattern = b"0123456789abcdef"
            payload = (pattern * (size // len(pattern) + 1))[:size]
            (repo / "large.bin").write_bytes(payload)
            _git(repo, "add", "large.bin")
            _git(repo, "commit", "-q", "-m", "large")
            commit = _git(repo, "rev-parse", "HEAD").strip()
            expected = "sha256:" + hashlib.sha256(payload).hexdigest()
            identity = verify_git_commit(
                repo, commit, expected_paths={"large.bin": expected}
            )
            self.assertEqual(identity.files[0].sha256, expected)

    def test_git_03_blob_content_uses_streaming_popen_not_git_show(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, commit = _make_repo(Path(tmp))
            events: list[tuple[str, tuple[str, ...]]] = []
            original_run = provenance._run_git
            original_popen = provenance.subprocess.Popen

            def run_spy(repo_root, arguments):
                events.append(("run", tuple(arguments)))
                return original_run(repo_root, arguments)

            def popen_spy(arguments, **kwargs):
                events.append(("popen", tuple(arguments)))
                return original_popen(arguments, **kwargs)

            with mock.patch.object(provenance, "_run_git", side_effect=run_spy), mock.patch.object(
                provenance.subprocess, "Popen", side_effect=popen_spy
            ):
                identity = verify_git_commit(
                    repo,
                    commit,
                    expected_paths={"alpha.txt": _sha(b"alpha\n")},
                )
            self.assertEqual(identity.files[0].path, "alpha.txt")
            run_arguments = [arguments for kind, arguments in events if kind == "run"]
            self.assertFalse(
                any("show" in arguments for arguments in run_arguments)
            )
            size_positions = [
                index
                for index, arguments in enumerate(run_arguments)
                if "cat-file" in arguments and "-s" in arguments
            ]
            self.assertTrue(size_positions)
            popen_positions = [
                index for index, (kind, _args) in enumerate(events) if kind == "popen"
            ]
            stream_position = events.index(
                (
                    "popen",
                    ("git", "-C", str(repo), "cat-file", "blob", f"{commit}:alpha.txt"),
                )
            )
            self.assertLess(
                [index for index, (kind, _args) in enumerate(events) if kind == "run"][size_positions[0]],
                stream_position,
            )
            self.assertTrue(popen_positions)

    def test_git_04_and_05_missing_and_wrong_blob_identities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, commit = _make_repo(Path(tmp))
            with self.assertRaises(BenchError) as raised:
                verify_git_commit(
                    repo, commit, expected_paths={"missing.txt": _sha(b"x")}
                )
            self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
            with self.assertRaises(BenchError) as raised:
                verify_git_commit(
                    repo, commit, expected_paths={"alpha.txt": _sha(b"wrong")}
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_git_06_nonzero_child_exit_is_typed_and_reaped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, commit = _make_repo(Path(tmp))
            fake = _FakeGitProcess(b"alpha\n", exit_on_wait=1)
            with mock.patch.object(
                provenance, "_declared_blob_size", return_value=6
            ), mock.patch.object(
                provenance.subprocess, "Popen", new=_SelectivePopen(fake)
            ):
                with self.assertRaises(BenchError) as raised:
                    verify_git_commit(
                        repo,
                        commit,
                        expected_paths={"alpha.txt": _sha(b"alpha\n")},
                    )
            self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
            self.assertTrue(fake.stdout.closed)
            self.assertTrue(fake.wait_calls)

    def test_git_07_oversized_and_truncated_streams_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, commit = _make_repo(Path(tmp))
            oversize = _FakeGitProcess(b"0123456789")
            with mock.patch.object(
                provenance, "_MAX_GIT_BLOB_BYTES", 8
            ), mock.patch.object(
                provenance, "_declared_blob_size", return_value=4
            ), mock.patch.object(
                provenance.subprocess, "Popen", new=_SelectivePopen(oversize)
            ):
                with self.assertRaises(BenchError) as raised:
                    verify_git_commit(
                        repo,
                        commit,
                        expected_paths={"alpha.txt": _sha(b"alpha\n")},
                    )
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            self.assertTrue(oversize.stdout.closed)
            self.assertTrue(oversize.killed)

            truncated = _FakeGitProcess(b"alp")
            with mock.patch.object(
                provenance, "_declared_blob_size", return_value=6
            ), mock.patch.object(
                provenance.subprocess, "Popen", new=_SelectivePopen(truncated)
            ):
                with self.assertRaises(BenchError) as raised:
                    verify_git_commit(
                        repo,
                        commit,
                        expected_paths={"alpha.txt": _sha(b"alpha\n")},
                    )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertTrue(truncated.stdout.closed)

    def test_git_08_shell_metacharacter_path_still_literal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _commit = _make_repo(root)
            weird = "a;b $(touch pwned).txt"
            (repo / weird).write_bytes(b"weird\n")
            _git(repo, "add", weird)
            _git(repo, "commit", "-q", "-m", "weird")
            commit = _git(repo, "rev-parse", "HEAD").strip()
            identity = verify_git_commit(
                repo, commit, expected_paths={weird: _sha(b"weird\n")}
            )
            self.assertEqual(identity.files[0].path, weird)
            self.assertFalse((root / "pwned").exists())


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
