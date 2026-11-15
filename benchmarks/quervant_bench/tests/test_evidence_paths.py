"""PATH-01…PATH-07: root-confined, no-symlink evidence file access."""

from __future__ import annotations

import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quervant_bench.config.errors import (
    BM_NOT_IMPLEMENTED,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.evidence import paths


class PathValidationTests(unittest.TestCase):
    def test_path_01_reads_nested_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "a" / "b.json").write_bytes(b'{"ok":true}\n')
            with paths.open_regular_beneath(root, "a/b.json") as handle:
                self.assertEqual(handle.read(), b'{"ok":true}\n')

    def test_path_02_rejects_unsafe_names(self) -> None:
        unsafe = [
            "/absolute",
            "../escape",
            "./relative",
            "a//b",
            "a\\b",
            "C:/windows",
            "a\u0000b",
            "a\u0001b",
            "a/",
            "",
            "a/../b",
        ]
        for name in unsafe:
            with self.subTest(name=name):
                with self.assertRaises(BenchError) as raised:
                    paths.validate_relative_member(name)
                self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_path_02b_resource_bounds(self) -> None:
        too_many = "/".join(f"c{index}" for index in range(33))
        with self.assertRaises(BenchError):
            paths.validate_relative_member(too_many)
        too_long = "a" * 4097
        with self.assertRaises(BenchError):
            paths.validate_relative_member(too_long)

    def test_path_03_symlink_leaf_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "target.txt").write_bytes(b"secret")
            os.symlink(root / "target.txt", root / "link.txt")
            with self.assertRaises(BenchError) as raised:
                paths.open_regular_beneath(root, "link.txt")
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_path_03b_symlink_intermediate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            (outside / "file.txt").write_bytes(b"x")
            os.symlink(outside, root / "inside")
            with self.assertRaises(BenchError) as raised:
                paths.open_regular_beneath(root, "inside/file.txt")
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_path_03c_symlink_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real"
            real.mkdir()
            (real / "file.txt").write_bytes(b"x")
            alias = root / "alias"
            os.symlink(real, alias)
            with self.assertRaises(BenchError):
                paths.open_regular_beneath(alias, "file.txt")
            with self.assertRaises(BenchError):
                paths.open_regular_beneath(alias / "sub", "file.txt")

    def test_path_04_fifo_directory_and_socket_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fifo = root / "pipe"
            os.mkfifo(fifo)
            with self.assertRaises(BenchError):
                paths.open_regular_beneath(root, "pipe")
            (root / "directory").mkdir()
            with self.assertRaises(BenchError):
                paths.open_regular_beneath(root, "directory")
            socket_path = root / "socket"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(socket_path))
                with self.assertRaises(BenchError):
                    paths.open_regular_beneath(root, "socket")
            finally:
                server.close()

    def test_path_05_leaf_replaced_with_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            leaf = root / "leaf.txt"
            leaf.write_bytes(b"original")
            paths.validate_relative_member("leaf.txt")
            leaf.unlink()
            os.symlink("/etc/passwd", leaf)
            with self.assertRaises(BenchError) as raised:
                paths.open_regular_beneath(root, "leaf.txt")
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_path_06_case_distinct_names_and_duplicate_declarations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "A.txt").write_bytes(b"upper")
            (root / "a.txt").write_bytes(b"lower")
            with paths.open_regular_beneath(root, "A.txt") as handle:
                self.assertEqual(handle.read(), b"upper")
            with paths.open_regular_beneath(root, "a.txt") as handle:
                self.assertEqual(handle.read(), b"lower")
            self.assertEqual(
                paths.list_declared_files_beneath(root, ["b", "a"]), ("a", "b")
            )
            with self.assertRaises(BenchError) as raised:
                paths.list_declared_files_beneath(root, ["a", "a"])
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_path_07_unsupported_platform_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_bytes(b"x")
            with mock.patch.object(paths, "_O_NOFOLLOW", None):
                with self.assertRaises(BenchError) as raised:
                    paths.open_regular_beneath(root, "file.txt")
            self.assertEqual(raised.exception.code, BM_NOT_IMPLEMENTED)
            with mock.patch.object(paths, "_O_NOFOLLOW", None):
                with self.assertRaises(BenchError) as raised:
                    paths.list_directory_beneath(root, ".")
            self.assertEqual(raised.exception.code, BM_NOT_IMPLEMENTED)




class PublicationRootPolicyTests(unittest.TestCase):
    def _repo_fixture(self, root: Path) -> Path:
        repo = root / "repo"
        (repo / "benchmark-results" / "scratch").mkdir(parents=True)
        (repo / "benchmarks").mkdir()
        (repo / "benchmarks-old").mkdir()
        (repo / "docs").mkdir()
        (repo / "target").mkdir()
        return repo

    def test_root_11_componentwise_publication_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo_fixture(root)
            external = root / "external"
            external.mkdir()
            sibling = root / "repo-other"
            sibling.mkdir()

            for allowed in (
                repo / "benchmark-results",
                repo / "benchmark-results" / "scratch",
                external,
                sibling,
            ):
                with self.subTest(allowed=str(allowed)):
                    self.assertEqual(
                        paths.require_publication_base(allowed, repo),
                        allowed.resolve(strict=True),
                    )

            for rejected in (
                repo,
                repo / "benchmarks",
                repo / "benchmarks-old",
                repo / "docs",
                repo / "target",
                root,
            ):
                with self.subTest(rejected=str(rejected)):
                    with self.assertRaises(BenchError) as raised:
                        paths.require_publication_base(rejected, repo)
                    self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_disjoint_admission_roots_componentwise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo_fixture(root)
            evidence = root / "evidence"
            evidence.mkdir()
            output = root / "output"
            output.mkdir()
            (evidence / "nested").mkdir()
            (output / "nested").mkdir()

            resolved_evidence, resolved_output = paths.require_disjoint_admission_roots(
                evidence, output, repo
            )
            self.assertEqual(resolved_evidence, evidence.resolve(strict=True))
            self.assertEqual(resolved_output, output.resolve(strict=True))

            for evidence_root, output_base in (
                (evidence, evidence),
                (evidence, evidence / "nested"),
                (output / "nested", output),
            ):
                with self.subTest(evidence=str(evidence_root), output=str(output_base)):
                    with self.assertRaises(BenchError) as raised:
                        paths.require_disjoint_admission_roots(
                            evidence_root, output_base, repo
                        )
                    self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
