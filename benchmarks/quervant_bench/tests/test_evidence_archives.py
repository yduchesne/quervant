"""ARC-01…ARC-11: bounded streaming TAR.GZ/ZIP inspection without extraction."""

from __future__ import annotations

import gzip
import io
import os
import stat
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from quervant_bench.config.errors import (
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.evidence.archives import (
    ArchiveLimits,
    MemberDigest,
    inspect_tar_gz,
    inspect_zip,
)
from quervant_bench.evidence.hashing import sha256_regular_file


def _write_tar_gz(path: Path, entries: list[tuple[str, bytes]]) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, payload in entries:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(payload))
    path.write_bytes(gzip.compress(buffer.getvalue(), mtime=0))


def _write_tar_special(path: Path, kind: str, name: str) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        info = tarfile.TarInfo(name)
        info.mtime = 0
        info.mode = 0o777
        if kind == "symlink":
            info.type = tarfile.SYMTYPE
            info.linkname = "target"
        elif kind == "hardlink":
            info.type = tarfile.LNKTYPE
            info.linkname = "target"
        elif kind == "directory":
            info.type = tarfile.DIRTYPE
        elif kind == "fifo":
            info.type = tarfile.FIFOTYPE
        elif kind == "chardev":
            info.type = tarfile.CHRTYPE
        else:  # pragma: no cover - test helper guard
            raise AssertionError(kind)
        archive.addfile(info)
    path.write_bytes(gzip.compress(buffer.getvalue(), mtime=0))


def _write_zip(
    path: Path,
    entries: list[tuple[str, bytes]],
    *,
    compression: int = zipfile.ZIP_STORED,
    mode: int = 0o644,
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, mode="w", compression=compression) as archive:
            for name, payload in entries:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = compression
                info.external_attr = (mode << 16) if mode else 0
                info.create_system = 3
                archive.writestr(info, payload)


class TarInspectionTests(unittest.TestCase):
    def test_arc_01_safe_tar_members_are_sorted_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tar_gz(
                root / "safe.tar.gz",
                [("b.txt", b"second\n"), ("a.txt", b"first\n")],
            )
            members = inspect_tar_gz(root, "safe.tar.gz")
            self.assertEqual([m.name for m in members], ["a.txt", "b.txt"])
            self.assertIsInstance(members[0], MemberDigest)
            self.assertEqual(members[0].byte_length, 6)
            self.assertEqual(members[1].byte_length, 7)
            self.assertTrue(members[0].digest.startswith("sha256:"))
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["safe.tar.gz"])

    def test_arc_03_unsafe_tar_names_are_rejected(self) -> None:
        unsafe_names = ["../evil", "/absolute", "a\\b", "a/./b", "a//b"]
        for name in unsafe_names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write_tar_gz(root / "bad.tar.gz", [(name, b"x")])
                with self.assertRaises(BenchError) as raised:
                    inspect_tar_gz(root, "bad.tar.gz")
                self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_arc_04_nonregular_tar_members_are_rejected(self) -> None:
        for kind in ("symlink", "hardlink", "directory", "fifo", "chardev"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write_tar_special(root / "special.tar.gz", kind, "member")
                with self.assertRaises(BenchError) as raised:
                    inspect_tar_gz(root, "special.tar.gz")
                self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_arc_06_duplicate_tar_members_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tar_gz(
                root / "dupe.tar.gz",
                [("same.txt", b"a"), ("same.txt", b"b")],
            )
            with self.assertRaises(BenchError) as raised:
                inspect_tar_gz(root, "dupe.tar.gz")
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_arc_07_bad_archive_digest_and_length(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tar_gz(root / "safe.tar.gz", [("a.txt", b"first\n")])
            digest, length = sha256_regular_file(
                root, "safe.tar.gz", max_bytes=1024 * 1024
            )
            self.assertNotEqual(digest, "sha256:" + "0" * 64)
            self.assertGreater(length, 0)

    def test_arc_08_limits_under_exact_and_over(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tar_gz(
                root / "bounded.tar.gz",
                [("a.txt", b"0123456789"), ("b.txt", b"0123456789")],
            )
            size = (root / "bounded.tar.gz").stat().st_size
            self.assertEqual(
                len(inspect_tar_gz(root, "bounded.tar.gz", ArchiveLimits(max_member_bytes=10))),
                2,
            )
            self.assertEqual(
                len(inspect_tar_gz(root, "bounded.tar.gz", ArchiveLimits(max_member_bytes=11))),
                2,
            )
            with self.assertRaises(BenchError):
                inspect_tar_gz(root, "bounded.tar.gz", ArchiveLimits(max_member_bytes=9))
            self.assertEqual(
                len(
                    inspect_tar_gz(
                        root, "bounded.tar.gz", ArchiveLimits(max_total_uncompressed_bytes=20)
                    )
                ),
                2,
            )
            with self.assertRaises(BenchError):
                inspect_tar_gz(
                    root, "bounded.tar.gz", ArchiveLimits(max_total_uncompressed_bytes=19)
                )
            self.assertEqual(
                len(inspect_tar_gz(root, "bounded.tar.gz", ArchiveLimits(max_members=2))), 2
            )
            with self.assertRaises(BenchError):
                inspect_tar_gz(root, "bounded.tar.gz", ArchiveLimits(max_members=1))
            self.assertEqual(
                len(inspect_tar_gz(root, "bounded.tar.gz", ArchiveLimits(max_archive_bytes=size))),
                2,
            )
            with self.assertRaises(BenchError):
                inspect_tar_gz(
                    root, "bounded.tar.gz", ArchiveLimits(max_archive_bytes=size - 1)
                )

    def test_arc_09_truncated_tar_gz_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tar_gz(root / "safe.tar.gz", [("a.txt", b"first\n")])
            payload = (root / "safe.tar.gz").read_bytes()
            (root / "truncated.tar.gz").write_bytes(payload[: len(payload) // 2])
            with self.assertRaises(BenchError) as raised:
                inspect_tar_gz(root, "truncated.tar.gz")
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_arc_11_many_members_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [(f"m{index:04d}.txt", b"x") for index in range(1000)]
            _write_tar_gz(root / "many.tar.gz", entries)
            members = inspect_tar_gz(root, "many.tar.gz")
            self.assertEqual(len(members), 1000)
            self.assertEqual(members, tuple(sorted(members, key=lambda m: m.name)))

    def test_arc_unsupported_archive_extension_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "archive.tar").write_bytes(b"not a gzip stream")
            with self.assertRaises(BenchError) as raised:
                inspect_tar_gz(root, "archive.tar")
            self.assertEqual(raised.exception.code, "BM_NOT_IMPLEMENTED")


class ZipInspectionTests(unittest.TestCase):
    def test_arc_02_safe_zip_stored_and_deflated(self) -> None:
        for compression, label in (
            (zipfile.ZIP_STORED, "stored"),
            (zipfile.ZIP_DEFLATED, "deflated"),
        ):
            with self.subTest(compression=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write_zip(
                    root / "safe.zip",
                    [("b.txt", b"second\n"), ("a.txt", b"first\n")],
                    compression=compression,
                )
                members = inspect_zip(root, "safe.zip")
                self.assertEqual([m.name for m in members], ["a.txt", "b.txt"])
                self.assertEqual(members[0].byte_length, 6)
                self.assertEqual(sorted(p.name for p in root.iterdir()), ["safe.zip"])

    def test_arc_03_unsafe_zip_names_are_rejected(self) -> None:
        for name in ("../evil", "/absolute", "a\\b", "a/./b", "a//b"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write_zip(root / "bad.zip", [(name, b"x")])
                with self.assertRaises(BenchError) as raised:
                    inspect_zip(root, "bad.zip")
                self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_arc_05_zip_symlink_directory_encryption_and_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_zip(
                root / "symlink.zip",
                [("link", b"/etc/passwd")],
                mode=stat.S_IFLNK | 0o777,
            )
            with self.assertRaises(BenchError):
                inspect_zip(root, "symlink.zip")

            _write_zip(root / "dir.zip", [("dir/", b"")])
            with self.assertRaises(BenchError):
                inspect_zip(root, "dir.zip")

            _write_zip(root / "bzip2.zip", [("a.txt", b"x" * 64)], compression=zipfile.ZIP_BZIP2)
            with self.assertRaises(BenchError):
                inspect_zip(root, "bzip2.zip")

            _write_zip(root / "encrypted.zip", [("a.txt", b"x")])
            payload = bytearray((root / "encrypted.zip").read_bytes())
            central = payload.index(b"PK\x01\x02")
            payload[central + 8] |= 0x1
            local = payload.index(b"PK\x03\x04")
            payload[local + 6] |= 0x1
            (root / "encrypted.zip").write_bytes(bytes(payload))
            with self.assertRaises(BenchError):
                inspect_zip(root, "encrypted.zip")

    def test_arc_06_duplicate_zip_members_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_zip(root / "dupe.zip", [("same.txt", b"a"), ("same.txt", b"b")])
            with self.assertRaises(BenchError) as raised:
                inspect_zip(root, "dupe.zip")
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_arc_09_corrupt_zip_crc_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_zip(root / "safe.zip", [("a.txt", b"0123456789")])
            payload = bytearray((root / "safe.zip").read_bytes())
            index = payload.index(b"0123456789")
            payload[index] = ord("X")
            (root / "corrupt.zip").write_bytes(bytes(payload))
            with self.assertRaises(BenchError) as raised:
                inspect_zip(root, "corrupt.zip")
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_arc_10_advertised_size_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_zip(root / "safe.zip", [("a.txt", b"0123456789")])
            payload = bytearray((root / "safe.zip").read_bytes())
            central = payload.index(b"PK\x01\x02")
            observed = int.from_bytes(payload[central + 24 : central + 28], "little")
            payload[central + 24 : central + 28] = (observed + 5).to_bytes(4, "little")
            (root / "forged.zip").write_bytes(bytes(payload))
            with self.assertRaises(BenchError) as raised:
                inspect_zip(root, "forged.zip")
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_arc_08_zip_member_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_zip(root / "safe.zip", [("a.txt", b"x" * 10)])
            self.assertEqual(
                len(inspect_zip(root, "safe.zip", ArchiveLimits(max_member_bytes=10))), 1
            )
            with self.assertRaises(BenchError):
                inspect_zip(root, "safe.zip", ArchiveLimits(max_member_bytes=9))


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
