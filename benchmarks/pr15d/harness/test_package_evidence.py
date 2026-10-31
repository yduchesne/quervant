#!/usr/bin/env python3
"""Deterministic tests for the PR15D evidence packager (standard library only).

All fixtures are synthetic and live in temporary directories. The real campaign
evidence under `target/pr15d/runs/` is never read, written or mutated here.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import package_evidence as package  # noqa: E402

ENGINES = ("quervant", "tantivy", "lucene")
TRIALS = (1, 2, 3)
SIZES = (10000, 100000)
PHASES = ("pre", "post", "final")
SOURCE_SHA = "a" * 40


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(json.dumps(payload, sort_keys=True).encode("utf-8") + b"\n")


def build_run(
    root,
    *,
    status="complete",
    qualified=True,
    validation_status="QUALIFIED",
    source_sha=SOURCE_SHA,
    omit_trial=None,
    omit_contention=None,
    sensitive=False,
    resource=False,
    extra_files=None,
    symlink_trial=None,
):
    """Create a minimal but structurally complete synthetic run directory."""
    corpus_dir = "/home/ci-runner/target/pr15d/corpus" if sensitive else "target/pr15d/corpus"
    _write_json(
        os.path.join(root, "run.json"),
        {
            "schema": "pr15d-run-v1",
            "run_id": os.path.basename(root),
            "source_sha": source_sha,
            "workload": "pr15d_v1",
            "corpus_dir": corpus_dir,
            "corpus_manifest_sha256": "b" * 64,
            "host_fingerprint": "c" * 64,
            "trials": len(TRIALS),
            "status": status,
            "qualified": qualified,
            "environment": {"kernel": "test"},
        },
    )
    _write_json(
        os.path.join(root, "validation.json"),
        {"schema": "pr15d-validation-v1", "status": validation_status, "errors": [], "unqualified": []},
    )
    for trial in TRIALS:
        for engine in ENGINES:
            relative = os.path.join(root, "trials", f"trial-{trial}", f"{engine}.json")
            if omit_trial == (trial, engine):
                continue
            contention = [
                {"phase": phase, "n": size, "state": "clear"}
                for size in SIZES
                for phase in PHASES
            ]
            _write_json(
                relative,
                {
                    "schema": "pr15d-trial-v1",
                    "trial": trial,
                    "engine": engine,
                    "source_sha": source_sha,
                    "qualified": True,
                    "contention": contention,
                },
            )
            for size in SIZES:
                for phase in PHASES:
                    path = os.path.join(
                        root, "contention", f"trial-{trial}", engine, f"n{size}-{phase}.json"
                    )
                    if omit_contention == (trial, engine, size, phase):
                        continue
                    _write_json(path, {"state": "clear", "n": size, "phase": phase})
    if resource:
        _write_json(
            os.path.join(root, "resource-probe.json"),
            {"schema": "pr15d-resource-probe-v1", "status": "MEASURED", "probes": []},
        )
    for relative, payload in (extra_files or {}).items():
        _write_json(os.path.join(root, relative), payload)
    if symlink_trial is not None:
        trial, engine, target = symlink_trial
        path = os.path.join(root, "trials", f"trial-{trial}", f"{engine}.json")
        os.remove(path)
        os.symlink(target, path)
    return root


class PackagingTests(unittest.TestCase):
    def _package(self, root, out_dir, *, require_resources=False):
        out = os.path.join(out_dir, "evidence.zip")
        manifest_path = os.path.join(out_dir, "b-evidence-manifest.json")
        manifest = package.package(
            root, out, manifest_path, require_resources=require_resources
        )
        return out, manifest_path, manifest

    def test_archive_is_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root)
            first, _, _ = self._package(root, os.path.join(out, "a"))
            second, _, _ = self._package(root, os.path.join(out, "b"))
            with open(first, "rb") as handle:
                left = handle.read()
            with open(second, "rb") as handle:
                right = handle.read()
            self.assertEqual(left, right)

    def test_manifest_lists_every_required_member_with_hashes(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root)
            archive_path, manifest_path, manifest = self._package(root, out)
            self.assertEqual(manifest["schema"], package.SCHEMA_MANIFEST)
            self.assertEqual(manifest["source_sha"], SOURCE_SHA)
            self.assertEqual(len(manifest["raw_manifests"]), 9)
            self.assertEqual(len(manifest["contention_records"]), 54)
            self.assertEqual(manifest["disposition"], package.DISPOSITION_CLEAN)
            self.assertEqual(manifest["resources"], None)
            self.assertEqual(manifest["validation"]["path"], "validation.json")
            self.assertIn("README.md", manifest["members"])
            self.assertIn("SHA256SUMS", manifest["members"])
            with open(archive_path, "rb") as handle:
                payload = handle.read()
            import hashlib

            self.assertEqual(manifest["package"]["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(manifest["package"]["bytes"], len(payload))
            self.assertTrue(os.path.isfile(manifest_path))

    def test_zip_is_stored_with_fixed_timestamps_and_unique_names(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root)
            archive_path, _, _ = self._package(root, out)
            with zipfile.ZipFile(archive_path) as archive:
                names = [info.filename for info in archive.infolist()]
                self.assertEqual(len(names), len(set(names)))
                for info in archive.infolist():
                    self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertNotIn("\\", info.filename)
                sums = archive.read("SHA256SUMS").decode("utf-8").splitlines()
                self.assertEqual(len(sums), len(names) - 1)
                listed = sorted(line.split("  ", 1)[1] for line in sums)
                self.assertEqual(listed, sorted(n for n in names if n != "SHA256SUMS"))

    def test_sha256sums_matches_member_bytes(self):
        import hashlib

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root)
            archive_path, _, _ = self._package(root, out)
            with zipfile.ZipFile(archive_path) as archive:
                sums = archive.read("SHA256SUMS").decode("utf-8").splitlines()
                for line in sums:
                    digest, name = line.split("  ", 1)
                    self.assertEqual(
                        digest, hashlib.sha256(archive.read(name)).hexdigest(), name
                    )

    def test_indexes_tsvs_and_binaries_are_never_included(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(
                root,
                extra_files={
                    "indexes/trial-1/tantivy/n10000/meta.json": {"segment": 1},
                    "corpus/pr15d_v1_N10000.tsv": {"not": "json"},
                },
            )
            _, _, manifest = self._package(root, out)
            joined = " ".join(manifest["members"])
            self.assertNotIn("indexes/", joined)
            self.assertNotIn(".tsv", joined)

    def test_incomplete_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root, status="running")
            with self.assertRaises(package.PackageError) as raised:
                self._package(root, out)
            self.assertEqual(raised.exception.code, "run_incomplete")

    def test_unqualified_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root, qualified=False)
            with self.assertRaises(package.PackageError) as raised:
                self._package(root, out)
            self.assertEqual(raised.exception.code, "run_unqualified")

    def test_non_qualified_validation_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root, validation_status="INVALID")
            with self.assertRaises(package.PackageError) as raised:
                self._package(root, out)
            self.assertEqual(raised.exception.code, "validation_not_qualified")

    def test_missing_trial_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root, omit_trial=(2, "tantivy"))
            with self.assertRaises(package.PackageError) as raised:
                self._package(root, out)
            self.assertEqual(raised.exception.code, "missing_file")

    def test_missing_contention_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root, omit_contention=(3, "lucene", 100000, "final"))
            with self.assertRaises(package.PackageError) as raised:
                self._package(root, out)
            self.assertEqual(raised.exception.code, "missing_file")

    def test_mismatched_source_sha_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root)
            path = os.path.join(root, "trials", "trial-2", "quervant.json")
            with open(path, "rb") as handle:
                manifest = json.loads(handle.read())
            manifest["source_sha"] = "d" * 40
            _write_json(path, manifest)
            with self.assertRaises(package.PackageError) as raised:
                self._package(root, out)
            self.assertEqual(raised.exception.code, "source_sha_inconsistent")

    def test_symlinked_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            outside = os.path.join(out, "outside.json")
            _write_json(outside, {"trial": 1, "engine": "quervant", "qualified": True})
            build_run(root, symlink_trial=(1, "quervant", outside))
            with self.assertRaises(package.PackageError) as raised:
                self._package(root, out)
            self.assertEqual(raised.exception.code, "symlink_member")

    def test_missing_resources_can_be_blocked_explicitly(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root)
            with self.assertRaises(package.PackageError) as raised:
                self._package(root, out, require_resources=True)
            self.assertEqual(raised.exception.code, "resources_missing")
            self.assertEqual(
                package.main(["--run", root, "--out", os.path.join(out, "e.zip"),
                              "--manifest", os.path.join(out, "m.json"),
                              "--require-resources"]),
                3,
            )

    def test_resource_report_is_included_when_present(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root, resource=True)
            _, _, manifest = self._package(root, out, require_resources=True)
            self.assertEqual(manifest["resources"]["path"], "resource-probe.json")
            self.assertGreater(manifest["resources"]["bytes"], 0)

    def test_sensitive_content_is_reported_not_rewritten(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root, sensitive=True)
            archive_path, _, manifest = self._package(root, out)
            self.assertEqual(manifest["disposition"], package.DISPOSITION_SENSITIVE)
            self.assertTrue(
                any(f["rule"] == "absolute_home_path" for f in manifest["sensitive_findings"])
            )
            with open(os.path.join(root, "run.json"), "rb") as handle:
                self.assertIn(b"/home/ci-runner", handle.read())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn(b"/home/ci-runner", archive.read("run.json"))

    def test_clean_run_has_no_sensitive_findings(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root)
            _, _, manifest = self._package(root, out)
            self.assertEqual(manifest["sensitive_findings"], [])
            self.assertEqual(manifest["disposition"], package.DISPOSITION_CLEAN)

    def test_tampered_member_is_detected_by_stored_sums(self):
        import hashlib

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root)
            archive_path, _, manifest = self._package(root, out)
            recorded = {
                entry["path"]: entry["sha256"]
                for entry in manifest["raw_manifests"] + manifest["contention_records"]
            }
            path = os.path.join(root, "trials", "trial-1", "quervant.json")
            with open(path, "rb") as handle:
                payload = json.loads(handle.read())
            payload["qualified"] = True
            payload["note"] = "tampered"
            _write_json(path, payload)
            with open(path, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
            self.assertNotEqual(digest, recorded["trials/trial-1/quervant.json"])
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn(
                    recorded["trials/trial-1/quervant.json"],
                    archive.read("SHA256SUMS").decode("utf-8"),
                )

    def test_cli_rejects_and_reports_codes(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            build_run(root, omit_trial=(1, "lucene"))
            code = package.main(
                [
                    "--run",
                    root,
                    "--out",
                    os.path.join(out, "e.zip"),
                    "--manifest",
                    os.path.join(out, "m.json"),
                ]
            )
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
