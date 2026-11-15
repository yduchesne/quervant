"""HASH-01…04 and PROV-01…09: raw-byte hashing and pinned provenance."""

from __future__ import annotations

import hashlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.evidence.hashing import (
    sha256_regular_file,
    sha256_stream,
    source_file_set_digest,
)
from quervant_bench.evidence.provenance import (
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


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
