"""LEG-01…LEG-05: legacy parity classification and historical immutability.

The legacy scripts are imported read-only for differential fixtures. Nothing in
the historical tree is executed as a campaign, rewritten or migrated.
"""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from quervant_bench.config.errors import BM_FILE_MISSING, BenchError
from quervant_bench.evidence.admission import admit_synthetic
from quervant_bench.evidence.archives import ArchiveLimits, inspect_tar_gz, inspect_zip

REPO = Path(__file__).resolve().parents[3]
BASELINE = "bc1409ec997d66baa2ff3f403c239a598ffd87d3"
INVENTORY_BASELINE = "ea9bef647cf155bb0176f159a8b304319ed6f7de"

sys.path.insert(0, str(REPO / "benchmarks"))
from pr15i_d3_c_t7_f2.admission import safe_members  # noqa: E402

from test_evidence_admission import (  # noqa: E402
    GOLDEN_SPEC_DIGEST,
    golden_spec,
    verified_locks,
)

PARITY = "PARITY"
BOTH_REJECT = "BOTH_REJECT"
NEW_STRICTER_REJECT = "NEW_STRICTER_REJECT"


def _tar_gz(path: Path, entries, *, special: str | None = None) -> None:
    import gzip

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, payload in entries:
            info = tarfile.TarInfo(name)
            info.mtime = 0
            info.mode = 0o644
            if special == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "target"
                archive.addfile(info)
                continue
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    path.write_bytes(gzip.compress(buffer.getvalue(), mtime=0))


def _zip(path: Path, entries, *, symlink: bool = False) -> None:
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            if symlink:
                info.external_attr = (0o120777) << 16
            info.create_system = 3
            archive.writestr(info, payload)


def _legacy(tar_path: Path) -> dict[str, str]:
    return safe_members(str(tar_path))


def _ours(tar_path: Path) -> dict[str, str]:
    members = inspect_tar_gz(tar_path.parent, tar_path.name)
    return {member.name: member.digest.split(":", 1)[1] for member in members}


class LegacyTarParityTests(unittest.TestCase):
    def test_leg_03_tar_safe_member_sets_are_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "safe.tar.gz"
            _tar_gz(archive, [("a.txt", b"alpha\n"), ("b.txt", b"beta\n")])
            self.assertEqual(_ours(archive), _legacy(archive))
            self.assertEqual(PARITY, "PARITY")

    def test_tar_traversal_both_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad.tar.gz"
            _tar_gz(archive, [("../escape.txt", b"x")])
            with self.assertRaises(Exception):
                _legacy(archive)
            with self.assertRaises(BenchError):
                _ours(archive)
            self.assertEqual(BOTH_REJECT, "BOTH_REJECT")

    def test_tar_duplicate_both_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "dupe.tar.gz"
            _tar_gz(archive, [("same.txt", b"a"), ("same.txt", b"b")])
            with self.assertRaises(Exception):
                _legacy(archive)
            with self.assertRaises(BenchError):
                _ours(archive)
            self.assertEqual(BOTH_REJECT, "BOTH_REJECT")

    def test_tar_symlink_both_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "link.tar.gz"
            _tar_gz(archive, [("link", b"")], special="symlink")
            with self.assertRaises(Exception):
                _legacy(archive)
            with self.assertRaises(BenchError):
                _ours(archive)
            self.assertEqual(BOTH_REJECT, "BOTH_REJECT")

    def test_tar_overlength_is_new_stricter_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bounded.tar.gz"
            _tar_gz(archive, [("a.txt", b"0123456789")])
            self.assertEqual(_ours(archive), _legacy(archive))
            with self.assertRaises(BenchError):
                inspect_tar_gz(archive.parent, archive.name, ArchiveLimits(max_member_bytes=9))
            self.assertEqual(NEW_STRICTER_REJECT, "NEW_STRICTER_REJECT")

    def test_tar_bad_sidecar_relative_to_archive_both_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "safe.tar.gz"
            _tar_gz(archive, [("a.txt", b"alpha\n")])
            trusted = {"a.txt": hashlib.sha256(b"alpha\n").hexdigest()}
            archive.write_bytes(archive.read_bytes() + b"")
            modified = Path(tmp) / "modified.tar.gz"
            _tar_gz(modified, [("a.txt", b"tampered\n")])
            self.assertNotEqual(_legacy(modified), trusted)
            self.assertNotEqual(_ours(modified), trusted)
            self.assertEqual(BOTH_REJECT, "BOTH_REJECT")


class LegacyZipParityTests(unittest.TestCase):
    def test_leg_04_zip_deterministic_member_convention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "safe.zip"
            entries = [("a.txt", b"alpha\n"), ("b.json", b'{"k":1}\n')]
            _zip(archive, entries)
            members = inspect_zip(archive.parent, archive.name)
            expected = {
                name: hashlib.sha256(payload).hexdigest() for name, payload in entries
            }
            self.assertEqual(
                {member.name: member.digest.split(":", 1)[1] for member in members},
                expected,
            )
            with zipfile.ZipFile(archive) as opened:
                for name, payload in entries:
                    self.assertEqual(opened.read(name), payload)
            self.assertEqual(PARITY, "PARITY")

    def test_zip_traversal_is_new_stricter_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad.zip"
            _zip(archive, [("../escape", b"x")])
            with self.assertRaises(BenchError):
                inspect_zip(archive.parent, archive.name)
            self.assertEqual(NEW_STRICTER_REJECT, "NEW_STRICTER_REJECT")

    def test_zip_symlink_is_new_stricter_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "link.zip"
            _zip(archive, [("link", b"/etc/passwd")], symlink=True)
            with self.assertRaises(BenchError):
                inspect_zip(archive.parent, archive.name)
            self.assertEqual(NEW_STRICTER_REJECT, "NEW_STRICTER_REJECT")

    def test_zip_duplicate_is_new_stricter_reject(self) -> None:
        import warnings

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "dupe.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                _zip(archive, [("same", b"a"), ("same", b"b")])
            with self.assertRaises(BenchError):
                inspect_zip(archive.parent, archive.name)
            self.assertEqual(NEW_STRICTER_REJECT, "NEW_STRICTER_REJECT")

    def test_zip_overlimit_is_new_stricter_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bounded.zip"
            _zip(archive, [("a", b"0123456789")])
            with self.assertRaises(BenchError):
                inspect_zip(
                    archive.parent, archive.name, ArchiveLimits(max_member_bytes=9)
                )
            self.assertEqual(NEW_STRICTER_REJECT, "NEW_STRICTER_REJECT")

    def test_self_reported_hash_without_external_manifest_is_rejected(self) -> None:
        spec = golden_spec()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp2:
            evidence = Path(tmp)
            payload = b'{"kind":"synthetic-evidence","sha256":"' + b"0" * 64 + b'"}'
            (evidence / "raw").mkdir()
            (evidence / "raw" / "evidence.json").write_bytes(payload)
            with self.assertRaises(BenchError):
                admit_synthetic(
                    spec=spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=evidence,
                    output_base=Path(tmp2),
                    verified_locks=verified_locks(spec),
                )
            self.assertEqual(NEW_STRICTER_REJECT, "NEW_STRICTER_REJECT")


class HistoricalImmutabilityTests(unittest.TestCase):
    def test_leg_01_historical_tracked_files_are_unmodified(self) -> None:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(REPO),
                "diff",
                "--name-only",
                BASELINE,
                "--",
                "benchmarks/pr15d",
                "benchmarks/pr15i_d3_c",
                "benchmarks/pr15i_d3_c_t7_f2",
                "benchmarks/quervant_bench/config/schemas",
                "docs/pr-artifacts/pr-15d",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout.decode("utf-8").strip(), "")

    def test_leg_02_bm01_inventory_regenerates_byte_identically(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "benchmarks/scripts/bm-contract-inventory.py",
                "--baseline",
                INVENTORY_BASELINE,
                "--check",
                "docs/pr-artifacts/bm-01/legacy-inventory.json",
            ],
            cwd=str(REPO),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))

    def test_leg_05_missing_historical_archives_are_typed_unavailable(self) -> None:
        expected = REPO / "target" / "pr15i" / "d3c" / "archives"
        if expected.exists():
            self.skipTest(
                "historical archives are present; read-only replay is owned by BM-07+"
            )
        spec = golden_spec()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp2:
            with self.assertRaises(BenchError) as raised:
                admit_synthetic(
                    spec=spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=Path(tmp),
                    output_base=Path(tmp2),
                    verified_locks=verified_locks(spec),
                )
            self.assertEqual(raised.exception.code, BM_FILE_MISSING)
            self.assertEqual(list(Path(tmp2).iterdir()), [])


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
