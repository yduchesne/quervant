"""Legacy inventory and format-registry contract tests.

Covers LEG-01..LEG-10. All git access is read-only.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from quervant_bench.legacy import registry_format_ids, validate_registry

REPO = Path(__file__).resolve().parents[3]
BENCH_ROOT = REPO / "benchmarks"
INVENTORY_PATH = REPO / "docs" / "pr-artifacts" / "bm-01" / "legacy-inventory.json"
SCRIPT_PATH = BENCH_ROOT / "scripts" / "bm-contract-inventory.py"

_spec = importlib.util.spec_from_file_location("bm_contract_inventory", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
inventory_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inventory_module)

INVENTORY = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
BASELINE = INVENTORY["source_baseline_sha"]

#: Existing files BM-01 is explicitly permitted to edit.
WHITELISTED_EDITS = frozenset({"benchmarks/README.md"})


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {completed.stderr}")
    return completed.stdout


def _tracked_paths() -> set[str]:
    output = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--name-only", BASELINE, "--", *inventory_module.SCOPES],
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout
    return {path.decode("utf-8") for path in output.split(b"\0") if path}


class InventoryConsistencyTests(unittest.TestCase):
    def test_leg_01_inventory_matches_pinned_git_tree_byte_for_byte(self) -> None:
        regenerated = inventory_module.build_inventory(BASELINE, cwd=str(REPO))
        self.assertEqual(
            inventory_module.canonical_bytes(regenerated),
            INVENTORY_PATH.read_bytes(),
        )
        recorded = {
            row["path"]
            for row in INVENTORY["paths"]
            if row["disposition"] != "external_not_present"
        }
        self.assertEqual(recorded, _tracked_paths())

    def test_leg_01_check_mode_is_byte_deterministic(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--baseline",
                BASELINE,
                "--check",
                str(INVENTORY_PATH),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_leg_01_check_mode_detects_a_difference(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write("{}\n")
            tampered = Path(handle.name)
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--baseline",
                    BASELINE,
                    "--check",
                    str(tampered),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            tampered.unlink()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("differs", completed.stderr)

    def test_leg_01_out_refuses_to_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "inventory.json"
            first = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--baseline", BASELINE, "--out", str(target)],
                cwd=REPO,
                capture_output=True,
                text=True,
                check=False,
            )
            second = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--baseline", BASELINE, "--out", str(target)],
                cwd=REPO,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 2)
        self.assertIn("refusing to overwrite", second.stderr)

    def test_leg_02_registry_covers_every_discovered_format_id(self) -> None:
        discovered = {
            entry["legacy_format_id"]: entry["legacy_version"]
            for entry in INVENTORY["format_ids"]
        }
        self.assertEqual(registry_format_ids(), discovered)
        self.assertEqual(INVENTORY["counts"]["legacy_format_ids"], len(discovered))

    def test_leg_03_roles_dispositions_and_order_are_allowlisted(self) -> None:
        paths = [row["path"] for row in INVENTORY["paths"]]
        self.assertEqual(paths, sorted(paths))
        self.assertEqual(len(paths), len(set(paths)))
        registry = json.loads(
            (BENCH_ROOT / "quervant_bench" / "legacy" / "legacy_formats.v1.json").read_text()
        )
        self.assertEqual(registry["source_baseline_sha"], BASELINE)
        known_roles = set(inventory_module.KINDS)
        for row in INVENTORY["paths"]:
            self.assertIn(row["kind"], inventory_module.KINDS, row["path"])
            self.assertIn(
                row["disposition"], inventory_module.DISPOSITIONS, row["path"]
            )
            self.assertTrue(row["notes"], row["path"])
            self.assertTrue(row["historical_family"], row["path"])
            self.assertTrue(set(row["producer_consumers"]) <= known_roles, row["path"])
            if row["disposition"] != "external_not_present":
                self.assertEqual(row["compatibility"], "legacy_original_only")
                self.assertTrue(row["producer_consumers"], row["path"])
        for entry in registry["formats"]:
            self.assertEqual(entry["reader_status"], "original_tool_only")
            self.assertIn(entry["future_disposition"], inventory_module.DISPOSITIONS)
            self.assertNotEqual(entry["new_equivalence_status"], "verified")
            self.assertTrue(entry["source_paths"])

    def test_leg_04_mutations_fail_inventory_validation(self) -> None:
        duplicate = copy.deepcopy(INVENTORY)
        duplicate["paths"].append(copy.deepcopy(duplicate["paths"][0]))
        with self.assertRaises(inventory_module.InventoryError):
            inventory_module.validate_inventory(duplicate)

        missing = copy.deepcopy(INVENTORY)
        missing["paths"] = missing["paths"][:-1]
        with self.assertRaises(inventory_module.InventoryError):
            inventory_module.validate_inventory(missing)

        inconsistent = copy.deepcopy(INVENTORY)
        inconsistent["paths"][0]["sha256"] = "not-a-digest"
        with self.assertRaises(inventory_module.InventoryError):
            inventory_module.validate_inventory(inconsistent)

        unclassified = copy.deepcopy(INVENTORY)
        unclassified["paths"][0]["kind"] = "mystery"
        with self.assertRaises(inventory_module.InventoryError):
            inventory_module.validate_inventory(unclassified)

        unregistered = copy.deepcopy(INVENTORY)
        for row in unregistered["paths"]:
            if row["schema_ids"]:
                row["schema_ids"] = row["schema_ids"] + ["unregistered-format-v1"]
                break
        with self.assertRaises(inventory_module.InventoryError):
            inventory_module.validate_inventory(unregistered)

    def test_leg_05_known_pr15d_and_d3c_format_literals_are_present(self) -> None:
        registered = registry_format_ids()
        for anchor in (
            "pr15d-run-v1",
            "pr15d-adapter-v1",
            "pr15d-trial-v1",
            "pr15d-spec-v1",
            "pr15i-d3c-strategy-evaluation-v1",
            "pr15i-d3c-summary-v1",
            "pr15i-d3c-verification-v1",
            "pr15i-d3c-t7f2-admission-v1",
            "pr15i-d3c-t7f2-policy-v1",
        ):
            self.assertIn(anchor, registered, anchor)

    def test_leg_06_historical_ids_are_absent_from_the_new_namespace(self) -> None:
        from quervant_bench.config import schemas

        new_ids = {schemas.schema_id(kind, version) for kind, version in schemas.registry()}
        self.assertEqual(len(new_ids), 6)
        for new_id in new_ids:
            self.assertTrue(new_id.startswith("urn:quervant-bench:contract:"))
            self.assertNotIn("pr15", new_id)
        for legacy_id in registry_format_ids():
            self.assertFalse(legacy_id.startswith("urn:quervant-bench:contract:"))

    def test_leg_07_frozen_historical_bytes_are_unchanged(self) -> None:
        changed = _git(
            "diff",
            "--name-only",
            "--diff-filter=MDR",
            BASELINE,
            "--",
            "benchmarks/",
            "crates/quervant-core/benches/",
        ).splitlines()
        self.assertEqual(set(changed) - WHITELISTED_EDITS, set())

        for row in INVENTORY["paths"]:
            if row["disposition"] == "external_not_present":
                self.assertIsNone(row["blob_sha"])
                self.assertIsNone(row["sha256"])
                continue
            data = subprocess.run(
                ["git", "show", f"{BASELINE}:{row['path']}"],
                cwd=REPO,
                capture_output=True,
                check=True,
            ).stdout
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"], row["path"])

    def test_leg_08_historical_families_are_present_and_counted(self) -> None:
        families = {row["historical_family"] for row in INVENTORY["paths"]}
        self.assertGreaterEqual(len(families), 8, families)
        self.assertIn("cross-engine-comparison", families)
        self.assertIn("retained-key-dedup", families)
        self.assertIn("criterion-suite", families)
        tracked = [
            row
            for row in INVENTORY["paths"]
            if row["disposition"] != "external_not_present"
        ]
        external = [
            row
            for row in INVENTORY["paths"]
            if row["disposition"] == "external_not_present"
        ]
        self.assertEqual(INVENTORY["counts"]["tracked_paths"], len(tracked))
        self.assertEqual(INVENTORY["counts"]["external_roots"], len(external))

    def test_leg_09_missing_external_archives_are_not_fabricated(self) -> None:
        external = [
            row
            for row in INVENTORY["paths"]
            if row["disposition"] == "external_not_present"
        ]
        self.assertEqual([row["path"] for row in external], ["target/"])
        tracked = _tracked_paths()
        for row in external:
            self.assertNotIn(row["path"], tracked)
            self.assertIsNone(row["blob_sha"])
            self.assertIsNone(row["sha256"])
            self.assertEqual(row["kind"], "evidence")
            self.assertIn("never fabricated", row["notes"])

    def test_leg_10_no_unverified_parity_is_claimed(self) -> None:
        registry = json.loads(
            (BENCH_ROOT / "quervant_bench" / "legacy" / "legacy_formats.v1.json").read_text()
        )
        for entry in registry["formats"]:
            self.assertIn(
                entry["new_equivalence_status"],
                ("not_verified", "evidence_unavailable"),
            )
        forged = copy.deepcopy(registry)
        forged["formats"][0]["new_equivalence_status"] = "verified"
        with self.assertRaises(Exception):
            validate_registry(forged)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
