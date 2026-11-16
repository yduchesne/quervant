"""PAR-01…PAR-04 and LEG-01/02: read-only historical non-equivalence evidence."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import statistics
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest import mock

from quervant_bench.config.codec import load_document
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.migrations import historical_retained_key as historical

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "retained-key"
LEDGER = FIXTURES / "historical-compatibility.v1.json"
PROTOCOL = REPO_ROOT / "benchmarks/pr15i_d3_c/protocol_v3r3.json"
EXTERNAL_ARCHIVE = REPO_ROOT / "target/pr15i-d3-c"
FROZEN_HASHES = {
    "benchmarks/pr15i_d3_c/protocol_v3r3.json": "c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c",
    "benchmarks/pr15i_d3_c/verify.py": "54e91d999ac923cf9e33289207d5a567786a7b318dbc46c5f24ed276f07fa2cd",
    "benchmarks/pr15i_d3_c/analysis_v3.py": "a028de728c44f553924faf8ab78b1f73da50d11e7bcc88ce9254c8c87d0d9603",
    "benchmarks/pr15i_d3_c/policy.py": "79674459d14ea41f6dcc9a9e3dec995bcab6cf8588d94b73b7e4212c331ed4bc",
    "benchmarks/pr15i_d3_c_t7/analysis.py": "212b0f9cadb6a11aede4eeabce382aecf438d195267aa6f67e0cf87ad85a2555",
    "benchmarks/pr15i_d3_c_t7/policy.py": "bcbdf13b6c466dc80002fa39204f9f110d39dadba14d755f2508bef47b80b440",
    "benchmarks/pr15i_d3_c_t7/verify_derived.py": "9c12b74caa8a657ef9a0b7ff8ad7aa3bc3872d160c84d15b144d6f457e51badc",
    "benchmarks/pr15i_d3_c_t7_f2/oracle.py": "66d3ef0224042c7d44e24b53d12c90d53218b0b5d570bb247a71290482708725",
    "benchmarks/pr15i_d3_c_t7_f2/verify_policy.py": "85097a82c2e65f304f45a00d1ec9ab1fd16cd59f343ffb23f79ab485ecf59ab5",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class HistoricalCompatibilityTests(unittest.TestCase):
    """PAR-01…PAR-04."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = read_json(LEDGER)

    def test_par_01_ledger_is_closed_and_matches_frozen_classes(self) -> None:
        self.assertEqual(
            set(self.ledger), {"kind", "schema_version", "rows"}
        )
        self.assertEqual(self.ledger["kind"], "retained-key-historical-compatibility")
        self.assertEqual(self.ledger["schema_version"], 1)
        rows = self.ledger["rows"]
        self.assertEqual([row["id"] for row in rows], [f"H{index:02d}" for index in range(1, 9)])
        for row in rows:
            self.assertEqual(
                set(row),
                {
                    "id",
                    "legacy_component",
                    "new_component",
                    "equivalence_class",
                    "required_input",
                    "expected_comparison",
                    "disposition_if_missing",
                    "notes",
                },
            )
            self.assertIn(row["equivalence_class"], historical.PARITY_CLASSES)
            self.assertEqual(
                row["equivalence_class"], historical.HISTORICAL_CLASSES[row["id"]]
            )
            self.assertTrue(row["required_input"])
            self.assertTrue(row["expected_comparison"])
            self.assertTrue(row["notes"])
        self.assertEqual(historical.HISTORICAL_CLASSES["H04"], historical.PARITY_NON_EQUIVALENT)
        self.assertEqual(historical.HISTORICAL_CLASSES["H05"], historical.PARITY_NON_EQUIVALENT)
        self.assertEqual(
            historical.HISTORICAL_CLASSES["H08"], historical.PARITY_EVIDENCE_UNAVAILABLE
        )

    def test_par_02_missing_or_empty_archive_is_unavailable(self) -> None:
        result = historical.assess_historical_evidence(
            archive_root=None, protocol_path=PROTOCOL
        )
        self.assertEqual(result["historical_archive"], historical.ARCHIVE_UNAVAILABLE)
        self.assertEqual(
            result["historical_numeric_parity"], historical.PARITY_NOT_EXECUTED
        )
        self.assertEqual(
            result["historical_decision_parity"], historical.PARITY_NOT_EXECUTED
        )
        self.assertEqual(
            result["historical_acceptance_gate"],
            historical.HISTORICAL_ACCEPTANCE_GATE_BLOCKED,
        )
        self.assertEqual(result["legacy_paths_retired"], "NO")
        self.assertEqual(result["protocol_sha256"], historical.PINNED_PROTOCOL_SHA256)

        with tempfile.TemporaryDirectory() as temporary:
            stub = Path(temporary) / "archive"
            stub.mkdir()
            empty = historical.assess_historical_evidence(
                archive_root=stub, protocol_path=PROTOCOL
            )
        self.assertEqual(empty["historical_archive"], historical.ARCHIVE_UNAVAILABLE)
        self.assertEqual(
            empty["historical_numeric_parity"], historical.PARITY_NOT_EXECUTED
        )

        if EXTERNAL_ARCHIVE.exists():
            current = historical.assess_historical_evidence(
                archive_root=EXTERNAL_ARCHIVE, protocol_path=PROTOCOL
            )
            self.assertEqual(
                current["historical_archive"], historical.ARCHIVE_UNAVAILABLE
            )

    def test_par_03_lower_middle_of_four_is_not_an_exact_median(self) -> None:
        def median4(values: list[int]) -> int:
            return sorted(values)[1]

        values = [1, 2, 100, 200]
        self.assertEqual(median4(values), 2)
        self.assertEqual(statistics.median(values), 51)
        self.assertNotEqual(median4(values), statistics.median(values))
        source = (REPO_ROOT / "benchmarks/pr15i_d3_c/verify.py").read_text(encoding="utf-8")
        self.assertIn("def median4(v): return sorted(v)[1]", source)
        self.assertEqual(
            historical.HISTORICAL_CLASSES["H04"], historical.PARITY_NON_EQUIVALENT
        )

    def test_par_04_threshold_filter_and_memory_contracts_differ(self) -> None:
        policy_source = (REPO_ROOT / "benchmarks/pr15i_d3_c/analysis_v3.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("within_arm_exclusion_cap_100k_medium_common", policy_source)
        self.assertIn("within_arm_exclusion_cap_other", policy_source)
        historical_protocol = load_document(PROTOCOL)
        self.assertEqual(historical_protocol["n_values"], [10000, 100000])
        self.assertEqual(historical_protocol["blocks"], 12)
        self.assertEqual(historical_protocol["classes"], ["absent", "rare", "medium", "common"])
        self.assertEqual(historical_protocol["k_values"], [1, 10, 32, 64, 100, 128, 256, 512, 1024])
        new_policy = load_document(
            REPO_ROOT
            / "benchmarks/experiments/synthetic-retained-key-reference/policy-profile.v1.json"
        )
        self.assertEqual(
            [rule["arm_id"] for rule in new_policy["resource_rules"]],
            ["exact-set", "linear", "prefilter"],
        )
        self.assertEqual(
            {rule["resource_id"] for rule in new_policy["resource_rules"]},
            {"aux-memory-bytes"},
        )
        self.assertEqual(
            historical.HISTORICAL_CLASSES["H05"], historical.PARITY_NON_EQUIVALENT
        )

    def test_par_05_synthetic_stand_in_cannot_authenticate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            root.mkdir()
            (root / "synthetic-scenario.v1.json").write_bytes(
                (REPO_ROOT / "benchmarks/experiments/synthetic-retained-key-reference/synthetic-scenario.v1.json").read_bytes()
            )
            result = historical.assess_historical_evidence(
                archive_root=root, protocol_path=PROTOCOL
            )
        self.assertEqual(result["historical_archive"], historical.ARCHIVE_UNAVAILABLE)
        self.assertEqual(
            result["historical_numeric_parity"], historical.PARITY_NOT_EXECUTED
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            root.mkdir()
            for campaign in historical.REQUIRED_CAMPAIGNS:
                (root / campaign).mkdir()
                (root / campaign / "manifest.json").write_text(
                    json.dumps(
                        {
                            "schema": "pr15i-d3c-manifest-v1",
                            "campaign": campaign,
                            "kind": "control" if campaign == historical.REQUIRED_CONTROL_CAMPAIGN else "four_arm",
                            "protocol_sha256": "0" * 64,
                            "source_base_sha": historical.PINNED_BASE_SHA,
                            "source_experiment_sha": historical.PINNED_EXPERIMENT_SHA,
                        }
                    ),
                    encoding="utf-8",
                )
                (root / campaign / "authorization.json").write_text("{}", encoding="utf-8")
            result = historical.assess_historical_evidence(
                archive_root=root, protocol_path=PROTOCOL
            )
        self.assertEqual(
            result["historical_archive"], historical.ARCHIVE_FAILED_AUTHENTICATION
        )
        self.assertEqual(
            result["historical_numeric_parity"], historical.PARITY_NOT_EXECUTED
        )


class LegacyPreservationTests(unittest.TestCase):
    """LEG-01/LEG-02."""

    def test_leg_01_historical_sources_remain_byte_identical(self) -> None:
        for relative, digest in FROZEN_HASHES.items():
            self.assertEqual(sha256(REPO_ROOT / relative), digest, relative)

    def test_leg_02_assessor_does_not_mutate_historical_roots(self) -> None:
        before = {relative: sha256(REPO_ROOT / relative) for relative in FROZEN_HASHES}
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            archive.mkdir()
            historical.assess_historical_evidence(
                archive_root=archive, protocol_path=PROTOCOL
            )
        after = {relative: sha256(REPO_ROOT / relative) for relative in FROZEN_HASHES}
        self.assertEqual(before, after)

# ---------------------------------------------------------------------------
# RF07-01/RF07-02 adversarial authentication tests (HF07-01…21)
# ---------------------------------------------------------------------------

_HEADER_MANIFEST_SCHEMA = "pr15i-d3c-manifest-v1"
_HEADER_AUTH_SCHEMA = "pr15i-d3c-authorization-v1"


def _valid_manifest(campaign: str) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema": _HEADER_MANIFEST_SCHEMA,
        "campaign": campaign,
        "kind": (
            "control"
            if campaign == historical.REQUIRED_CONTROL_CAMPAIGN
            else "four_arm"
        ),
        "protocol_sha256": historical.PINNED_PROTOCOL_SHA256,
        "source_base_sha": historical.PINNED_BASE_SHA,
    }
    if campaign != historical.REQUIRED_CONTROL_CAMPAIGN:
        manifest["source_experiment_sha"] = historical.PINNED_EXPERIMENT_SHA
    return manifest


def _valid_authorization() -> dict[str, Any]:
    return {
        "schema": _HEADER_AUTH_SCHEMA,
        "protocol_sha256": historical.PINNED_PROTOCOL_SHA256,
        "rehearsal_only": False,
    }


def _compact_json(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def write_campaign_headers(
    root: Path,
    *,
    corrupt: Mapping[str, str] | None = None,
    extra_raw: bool = False,
) -> None:
    """Create a deliberately unsealed three-campaign header-only fixture."""

    corrupt = dict(corrupt or {})
    root.mkdir(parents=True, exist_ok=True)
    for campaign in historical.REQUIRED_CAMPAIGNS:
        directory = root / campaign
        directory.mkdir()
        key = corrupt.get(campaign, "")
        manifest = _valid_manifest(campaign)
        authorization = _valid_authorization()
        if key == "manifest_protocol":
            manifest["protocol_sha256"] = "0" * 64
        elif key == "manifest_base":
            manifest["source_base_sha"] = "1" * 40
        elif key == "manifest_experiment":
            manifest["source_experiment_sha"] = "2" * 40
        elif key == "manifest_campaign":
            manifest["campaign"] = "wrong-campaign"
        elif key == "manifest_kind":
            manifest["kind"] = "four_arm" if manifest["kind"] == "control" else "control"
        elif key == "manifest_control_experiment":
            manifest["source_experiment_sha"] = "3" * 40
        elif key == "auth_empty":
            authorization = {}
        elif key == "auth_protocol":
            authorization["protocol_sha256"] = "4" * 64
        elif key == "auth_schema":
            authorization["schema"] = "other-authorization"
        elif key == "auth_rehearsal_true":
            authorization["rehearsal_only"] = True
        elif key == "auth_rehearsal_nonbool":
            authorization["rehearsal_only"] = "false"

        if key != "manifest_missing":
            if key == "manifest_malformed":
                payload = b"{bad json\n"
            elif key == "manifest_duplicate":
                payload = b'{"a":1,"a":2}\n'
            elif key == "manifest_array":
                payload = b"[]\n"
            elif key == "manifest_null":
                payload = b"null\n"
            elif key == "manifest_utf8":
                payload = b"\xff\xfe\n"
            else:
                payload = _compact_json(manifest)
            (directory / "manifest.json").write_bytes(payload)

        if key != "auth_missing":
            if key == "auth_malformed":
                payload = b"{bad json\n"
            elif key == "auth_duplicate":
                payload = b'{"a":1,"a":2}\n'
            elif key == "auth_array":
                payload = b"[]\n"
            elif key == "auth_null":
                payload = b"null\n"
            elif key == "auth_utf8":
                payload = b"\xff\xfe\n"
            else:
                payload = _compact_json(authorization)
            (directory / "authorization.json").write_bytes(payload)

        if extra_raw:
            (directory / "raw").mkdir()
            (directory / "raw" / "stub.txt").write_text("not evidence\n", encoding="utf-8")


def _state(result: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        result["historical_archive"],
        result["historical_verifier"],
        result["historical_numeric_parity"],
        result["historical_decision_parity"],
        result["historical_acceptance_gate"],
    )


class HistoricalAuthenticationFixupTests(unittest.TestCase):
    """RF07-01/RF07-02: header matching is not authentication."""

    def _assess(self, root: Path | None) -> dict[str, Any]:
        return historical.assess_historical_evidence(
            archive_root=root, protocol_path=PROTOCOL
        )

    def _present(self, *, corrupt: Mapping[str, str] | None = None, extra_raw: bool = False) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            write_campaign_headers(root, corrupt=corrupt, extra_raw=extra_raw)
            return self._assess(root)

    def test_hf07_01_header_compatible_without_seal_is_not_authentic(self) -> None:
        result = self._present()
        self.assertEqual(result["historical_archive"], "PRESENT_UNVERIFIED")
        self.assertNotEqual(result["historical_archive"], "AUTHENTIC")
        self.assertEqual(
            _state(result),
            (
                "PRESENT_UNVERIFIED",
                "NOT_EXECUTED",
                "NOT_EXECUTED",
                "NOT_EXECUTED",
                "BLOCKED",
            ),
        )

    def test_hf07_02_empty_authorization_is_failed_authentication(self) -> None:
        result = self._present(
            corrupt={"d3c-v3r3-strategies-01": "auth_empty"}
        )
        self.assertEqual(result["historical_archive"], "FAILED_AUTHENTICATION")
        self.assertEqual(result["historical_verifier"], "FAILED")

    def test_hf07_03_wrong_authorization_protocol_is_failed(self) -> None:
        result = self._present(
            corrupt={"d3c-v3r3-strategies-02": "auth_protocol"}
        )
        self.assertEqual(result["historical_archive"], "FAILED_AUTHENTICATION")

    def test_hf07_04_wrong_authorization_schema_or_rehearsal_is_failed(self) -> None:
        for mutation in (
            "auth_schema",
            "auth_rehearsal_true",
            "auth_rehearsal_nonbool",
        ):
            with self.subTest(mutation=mutation):
                result = self._present(
                    corrupt={"d3c-v3r3-base-aa-01": mutation}
                )
                self.assertEqual(
                    result["historical_archive"], "FAILED_AUTHENTICATION"
                )

    def test_hf07_05_wrong_manifest_identity_is_failed(self) -> None:
        for mutation in (
            "manifest_protocol",
            "manifest_base",
            "manifest_experiment",
            "manifest_campaign",
            "manifest_kind",
        ):
            with self.subTest(mutation=mutation):
                campaign = (
                    "d3c-v3r3-base-aa-01"
                    if mutation in ("manifest_protocol", "manifest_base", "manifest_kind")
                    else "d3c-v3r3-strategies-01"
                )
                result = self._present(corrupt={campaign: mutation})
                self.assertEqual(
                    result["historical_archive"], "FAILED_AUTHENTICATION"
                )

    def test_hf07_06_present_malformed_json_is_failed_not_unavailable(self) -> None:
        for mutation in (
            "manifest_malformed",
            "manifest_duplicate",
            "manifest_array",
            "manifest_null",
            "manifest_utf8",
            "auth_malformed",
            "auth_duplicate",
            "auth_array",
            "auth_null",
            "auth_utf8",
        ):
            with self.subTest(mutation=mutation):
                result = self._present(
                    corrupt={"d3c-v3r3-strategies-01": mutation}
                )
                self.assertEqual(
                    result["historical_archive"], "FAILED_AUTHENTICATION"
                )
                self.assertNotEqual(result["historical_archive"], "EVIDENCE_UNAVAILABLE")

    def test_hf07_07_unrelated_raw_stub_does_not_promote(self) -> None:
        result = self._present(extra_raw=True)
        self.assertEqual(result["historical_archive"], "PRESENT_UNVERIFIED")
        self.assertNotEqual(result["historical_archive"], "AUTHENTIC")

    def test_hf07_08_missing_or_empty_archive_is_unavailable(self) -> None:
        self.assertEqual(
            self._assess(None)["historical_archive"], "EVIDENCE_UNAVAILABLE"
        )
        with tempfile.TemporaryDirectory() as temporary:
            empty = Path(temporary) / "empty"
            empty.mkdir()
            self.assertEqual(
                self._assess(empty)["historical_archive"], "EVIDENCE_UNAVAILABLE"
            )
        missing_protocol = Path(tempfile.gettempdir()) / "no-such-bm07-protocol.json"
        result = historical.assess_historical_evidence(
            archive_root=None, protocol_path=missing_protocol
        )
        self.assertEqual(result["historical_archive"], "EVIDENCE_UNAVAILABLE")

    def test_hf07_09_missing_campaign_or_required_file_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            write_campaign_headers(root)
            shutil.rmtree(root / historical.REQUIRED_TREATMENT_CAMPAIGNS[0])
            self.assertEqual(
                self._assess(root)["historical_archive"], "EVIDENCE_UNAVAILABLE"
            )

        for name in ("manifest.json", "authorization.json"):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "archive"
                write_campaign_headers(root)
                (root / historical.REQUIRED_TREATMENT_CAMPAIGNS[0] / name).unlink()
                result = self._assess(root)
                self.assertEqual(
                    result["historical_archive"], "EVIDENCE_UNAVAILABLE"
                )
                self.assertEqual(result["historical_numeric_parity"], "NOT_EXECUTED")

    def test_hf07_10_no_seal_build_host_or_slots_still_present_unverified(self) -> None:
        result = self._present()
        self.assertEqual(result["historical_archive"], "PRESENT_UNVERIFIED")
        self.assertEqual(result["historical_verifier"], "NOT_EXECUTED")

    def test_hf07_11_every_nonunsafe_state_blocks_parity_and_retirement(self) -> None:
        states = [
            self._present(),
            self._present(corrupt={"d3c-v3r3-strategies-01": "auth_empty"}),
            self._assess(None),
        ]
        for result in states:
            self.assertEqual(
                result["historical_acceptance_gate"], "BLOCKED"
            )
            self.assertEqual(result["legacy_paths_retired"], "NO")
            self.assertEqual(result["historical_numeric_parity"], "NOT_EXECUTED")
            self.assertEqual(result["historical_decision_parity"], "NOT_EXECUTED")

    def test_hf07_12_no_authentic_or_qualified_decision_is_exposed(self) -> None:
        result = self._present()
        encoded = json.dumps(result, sort_keys=True)
        for forbidden in ("AUTHENTIC", "QUALIFIED", "EXACT", "PASS"):
            self.assertNotIn(forbidden, encoded)
        self.assertIn("PRESENT_UNVERIFIED", encoded)

    def test_hf07_13_unsafe_entries_and_bounds_are_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            write_campaign_headers(root)
            target = root / historical.REQUIRED_TREATMENT_CAMPAIGNS[0]
            moving = root / "moving-campaign"
            target.rename(moving)
            os.symlink(moving, target)
            with self.assertRaises(BenchError) as raised:
                self._assess(root)
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            write_campaign_headers(root)
            target = root / historical.REQUIRED_TREATMENT_CAMPAIGNS[0] / "manifest.json"
            target.unlink()
            os.symlink(
                root / historical.REQUIRED_CONTROL_CAMPAIGN / "manifest.json",
                target,
            )
            with self.assertRaises(BenchError) as raised:
                self._assess(root)
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            write_campaign_headers(root)
            target = root / historical.REQUIRED_TREATMENT_CAMPAIGNS[0] / "manifest.json"
            target.unlink()
            target.mkdir()
            with self.assertRaises(BenchError) as raised:
                self._assess(root)
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            write_campaign_headers(root)
            target = root / historical.REQUIRED_TREATMENT_CAMPAIGNS[0] / "manifest.json"
            target.write_bytes(b" " * (historical.MAX_MANIFEST_BYTES + 1))
            with self.assertRaises(BenchError) as raised:
                self._assess(root)
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            write_campaign_headers(root)
            for index in range(254):
                (root / f"extra-{index:03d}.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(BenchError) as raised:
                self._assess(root)
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_hf07_14_assessor_does_not_write_fixture_or_legacy_paths(self) -> None:
        before_legacy = {relative: sha256(REPO_ROOT / relative) for relative in FROZEN_HASHES}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            write_campaign_headers(root)
            before_fixture = {
                str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(root.rglob("*"))
                if path.is_file()
            }
            self._assess(root)
            after_fixture = {
                str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(root.rglob("*"))
                if path.is_file()
            }
        after_legacy = {relative: sha256(REPO_ROOT / relative) for relative in FROZEN_HASHES}
        self.assertEqual(before_fixture, after_fixture)
        self.assertEqual(before_legacy, after_legacy)

    def test_hf07_15_no_subprocess_or_legacy_execution(self) -> None:
        source = Path(historical.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        with mock.patch("subprocess.run", side_effect=AssertionError("subprocess")):
            result = self._present()
        self.assertEqual(result["historical_archive"], "PRESENT_UNVERIFIED")

    def test_hf07_16_original_historical_hashes_are_unchanged(self) -> None:
        for relative, digest in FROZEN_HASHES.items():
            self.assertEqual(sha256(REPO_ROOT / relative), digest, relative)

    def test_hf07_17_source_and_qa_anchor_chain_matches_final_tree(self) -> None:
        from quervant_bench.config.codec import content_digest
        from quervant_bench.qualification.identity import compute_source_set_digest
        from quervant_bench.tests.test_qualification_contracts import (
            FIXTURES as QUALIFICATION_FIXTURES,
            trust_anchors,
        )

        anchors = trust_anchors()
        self.assertEqual(
            compute_source_set_digest(REPO_ROOT), anchors["source_set_digest"]
        )
        for gate, anchor_field in (
            ("framework-qa", "framework_qa_digest"),
            ("source-qa", "source_qa_digest"),
        ):
            evidence = read_json(QUALIFICATION_FIXTURES / f"{gate}-evidence.json")
            self.assertEqual(content_digest(evidence), anchors[anchor_field])
            self.assertEqual(
                evidence["source_set_digest"], anchors["source_set_digest"]
            )
            for check in evidence["checks"]:
                record = read_json(
                    QUALIFICATION_FIXTURES / gate / f"{check['check_id']}.json"
                )
                self.assertEqual(content_digest(record), check["evidence_digest"])
                self.assertEqual(
                    record["source_set_digest"], anchors["source_set_digest"]
                )

    def test_hf07_18_stale_source_and_altered_qa_are_rejected(self) -> None:
        from quervant_bench.qualification import qa as qualification_qa
        from quervant_bench.qualification.identity import verify_source_identity
        from quervant_bench.tests.test_qualification_contracts import (
            FIXTURES as QUALIFICATION_FIXTURES,
            trust_anchors,
        )

        pre_fixup_source = "sha256:a8af53867f04bca986f1f64d076ec2e037d36e4160145432fdea305d93deee97"
        anchors = trust_anchors()
        with self.assertRaises(BenchError) as raised:
            verify_source_identity(REPO_ROOT, pre_fixup_source)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

        with tempfile.TemporaryDirectory() as temporary:
            qa_root = Path(temporary) / "qualification"
            shutil.copytree(QUALIFICATION_FIXTURES, qa_root)
            record = qa_root / "framework-qa" / "python-contracts.json"
            record.write_bytes(record.read_bytes() + b" ")
            with self.assertRaises(BenchError):
                qualification_qa.read_qa_evidence(
                    qa_evidence_root=qa_root,
                    gate="framework-qa",
                    expected_document_digest=anchors["framework_qa_digest"],
                    profile_digest=anchors["profile_digest"],
                    source_set_digest=anchors["source_set_digest"],
                )

    def test_hf07_19_mixed_malformed_and_missing_prefers_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "archive"
            write_campaign_headers(
                root,
                corrupt={"d3c-v3r3-strategies-01": "manifest_malformed"},
            )
            shutil.rmtree(root / historical.REQUIRED_TREATMENT_CAMPAIGNS[1])
            result = self._assess(root)
        self.assertEqual(result["historical_archive"], "FAILED_AUTHENTICATION")
        self.assertNotEqual(result["historical_archive"], "EVIDENCE_UNAVAILABLE")

    def test_hf07_20_control_with_nonnull_experiment_sha_is_failed(self) -> None:
        result = self._present(
            corrupt={"d3c-v3r3-base-aa-01": "manifest_control_experiment"}
        )
        self.assertEqual(result["historical_archive"], "FAILED_AUTHENTICATION")

    def test_hf07_21_public_surface_preserves_old_enums_and_exports_new_state(self) -> None:
        self.assertEqual(
            getattr(historical, "ARCHIVE_PRESENT_UNVERIFIED", None),
            "PRESENT_UNVERIFIED",
        )
        self.assertIn("ARCHIVE_PRESENT_UNVERIFIED", historical.__all__)
        self.assertEqual(historical.ARCHIVE_AUTHENTIC, "AUTHENTIC")
        for name in (
            "PARITY_EXACT",
            "PARITY_NUMERIC_TOLERANCE",
            "PARITY_SEMANTIC",
            "PARITY_NON_EQUIVALENT",
            "PARITY_EVIDENCE_UNAVAILABLE",
            "PARITY_FAILED",
            "ARCHIVE_AUTHENTIC",
            "ARCHIVE_FAILED_AUTHENTICATION",
            "ARCHIVE_UNAVAILABLE",
        ):
            self.assertTrue(hasattr(historical, name), name)
        signature = inspect.signature(historical.assess_historical_evidence)
        self.assertEqual(
            list(signature.parameters), ["archive_root", "protocol_path"]
        )
        source = inspect.getsource(historical.assess_historical_evidence)
        self.assertNotIn("ARCHIVE_AUTHENTIC", source)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
