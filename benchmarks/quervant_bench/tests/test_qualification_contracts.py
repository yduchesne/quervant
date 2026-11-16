"""CONTRACT-01…10 — closed v1 qualification records and canonical encoding.

This module also hosts the small shared test-only helpers used by the other BM-06
test modules (numbered cases stay in their own module). Nothing here asserts that
a synthetic QA fixture is real CI evidence; the fixtures are reviewed synthetic
assertions of the qualification mechanism.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

from quervant_bench.config.codec import (
    canonical_document_bytes,
    canonical_payload_bytes,
    content_digest,
    loads_json,
)
from quervant_bench.config.contracts import validate_receipt
from quervant_bench.config.errors import (
    BM_DUPLICATE_KEY,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCHEMA_UNSUPPORTED,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.qualification import load_qualified_synthetic_run, qualify_synthetic_run
from quervant_bench.qualification.admission import validate_admission_index
from quervant_bench.qualification.contracts import (
    FRAMEWORK_QA_ROSTER,
    FRAMEWORK_TOOLCHAIN_ID,
    FREEZE_MEMBERS,
    MANIFEST_MEMBERS,
    MAX_DOCUMENT_BYTES,
    MEMBER_NAMES,
    SOURCE_QA_ROSTER,
    SOURCE_TOOLCHAIN_ID,
    bound_payload,
    validate_acceptance_summary,
    validate_freeze_snapshot,
    validate_manifest,
    validate_profile,
    validate_qa_check_record,
    validate_qa_evidence,
    validate_verification_assessment,
)
from quervant_bench.qualification import qa as qualification_qa
from quervant_bench.qualification.identity import (
    EXTRA_SOURCE_FILES,
    SCHEMA_DIRECTORY,
    SOURCE_DIRECTORIES,
    compute_source_set_digest,
    require_repository_root,
    source_roster,
    verify_source_identity,
)
from quervant_bench.qualification.profiles import (
    default_profile_path,
    read_qualification_profile,
)
from quervant_bench.tests.analysis_support import SealedRun, experiment_root

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "qualification"
TRUST_ANCHOR_NAME = "trust-anchors.v1.json"

_CACHE: dict[str, Any] = {}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def trust_anchors() -> dict[str, Any]:
    return read_json(FIXTURES / TRUST_ANCHOR_NAME)


def profile_document() -> dict[str, Any]:
    return read_json(default_profile_path())


def profile_digest() -> str:
    return content_digest(profile_document())


def sealed_run() -> SealedRun:
    if "run" not in _CACHE:
        import atexit

        run = SealedRun()
        _CACHE["run"] = run
        atexit.register(run.close)
    return _CACHE["run"]


def qualification_kwargs(output_base: Path) -> dict[str, Any]:
    anchors = trust_anchors()
    run = sealed_run()
    return {
        "bundle": run.bundle,
        "run_dir": run.run_dir,
        "scenario_root": run.evidence,
        "profiles_root": experiment_root(),
        "resources_root": experiment_root(),
        "qualification_profile_path": default_profile_path(),
        "qa_evidence_root": FIXTURES,
        "expected_profile_digest": anchors["profile_digest"],
        "expected_framework_qa_digest": anchors["framework_qa_digest"],
        "expected_source_qa_digest": anchors["source_qa_digest"],
        "source_root": REPO_ROOT,
        "expected_source_set_digest": anchors["source_set_digest"],
        "output_base": output_base,
    }


def qualified_once() -> tuple[Path, Any]:
    """Publish one real qualification per test process and cache it."""

    if "qualification" not in _CACHE:
        temporary = tempfile.TemporaryDirectory()
        _CACHE["qualification_tmp"] = temporary
        base = Path(temporary.name) / "results"
        base.mkdir()
        result = qualify_synthetic_run(**qualification_kwargs(base))
        _CACHE["qualification"] = (base, result)
    return _CACHE["qualification"]


def committed_documents() -> dict[str, dict[str, Any]]:
    if "documents" not in _CACHE:
        base, result = qualified_once()
        directory = result.output_directory
        _CACHE["documents"] = {
            name: read_json(directory / name) for name in MEMBER_NAMES
        }
    return copy.deepcopy(_CACHE["documents"])


def load_committed(output_base: Path, **overrides: Any) -> Any:
    arguments = qualification_kwargs(output_base)
    arguments.update(overrides)
    return load_qualified_synthetic_run(**arguments)


def write_canonical(path: Path, document: dict[str, Any]) -> None:
    path.write_bytes(canonical_document_bytes(document))


def rewrite_receipt_self_id(document: dict[str, Any]) -> dict[str, Any]:
    """Mechanically recompute a receipt's own content ID (test helper only)."""

    payload = {key: value for key, value in document.items() if key != "receipt_id"}
    document["receipt_id"] = content_digest(payload)
    validate_receipt(document)
    return document


def update_member_record(
    records: list[dict[str, Any]], name: str, document: dict[str, Any]
) -> None:
    """Update exactly one manifest/snapshot member record (test helper only)."""

    matches = [record for record in records if record["path"] == name]
    if len(matches) != 1:  # test-fixture guard, never production behavior
        raise AssertionError(f"expected exactly one member record for {name!r}")
    matches[0]["digest"] = content_digest(document)
    matches[0]["byte_length"] = len(canonical_document_bytes(document))


def write_bundle_documents(
    output_base: Path,
    experiment_id: str,
    run_id: str,
    documents: dict[str, dict[str, Any]],
) -> Path:
    """Write one synthetic committed-style directory for adversarial load tests."""

    if set(documents) != set(MEMBER_NAMES):  # test-fixture guard
        raise AssertionError("the forged bundle must contain exactly the 15 members")
    directory = output_base / experiment_id / run_id
    directory.mkdir(parents=True, exist_ok=True)
    for name in MEMBER_NAMES:
        write_canonical(directory / name, documents[name])
    return directory


def rehash_gate_e(documents: dict[str, dict[str, Any]]) -> None:
    """Mechanically rebind attestation + manifest after a freeze-snapshot change."""

    manifest = documents["manifest.json"]
    attestation = documents["attestation.json"]
    freeze_digest = content_digest(manifest["freeze_snapshot"])
    for collection in ("inputs", "outputs"):
        for entry in attestation[collection]:
            if entry["name"] == "freeze-snapshot":
                entry["digest"] = freeze_digest
    rewrite_receipt_self_id(attestation)
    manifest["attestation_digest"] = content_digest(attestation)
    update_member_record(manifest["members"], "attestation.json", attestation)


def rehash_gate_d(documents: dict[str, dict[str, Any]]) -> None:
    """Mechanically rebind every descendant of a changed acceptance summary."""

    summary = documents["acceptance-summary.json"]
    acceptance = documents["acceptance.json"]
    attestation = documents["attestation.json"]
    manifest = documents["manifest.json"]

    summary_digest = content_digest(summary)
    for entry in acceptance["outputs"]:
        if entry["name"] == "acceptance-summary":
            entry["digest"] = summary_digest
    rewrite_receipt_self_id(acceptance)

    for entry in attestation["dependencies"]:
        if entry["name"] == "acceptance":
            entry["receipt_id"] = acceptance["receipt_id"]
            entry["digest"] = content_digest(acceptance)

    snapshot = manifest["freeze_snapshot"]
    update_member_record(snapshot["members"], "acceptance-summary.json", summary)
    update_member_record(snapshot["members"], "acceptance.json", acceptance)
    freeze_digest = content_digest(snapshot)
    for collection in ("inputs", "outputs"):
        for entry in attestation[collection]:
            if entry["name"] == "freeze-snapshot":
                entry["digest"] = freeze_digest
    rewrite_receipt_self_id(attestation)

    manifest["attestation_digest"] = content_digest(attestation)
    for name in ("acceptance-summary.json", "acceptance.json", "attestation.json"):
        update_member_record(manifest["members"], name, documents[name])


def qa_workspace(
    root: Path,
    *,
    source_set_digest: str | None = None,
    profile: str | None = None,
    mutate_evidence: Callable[[str, dict[str, Any]], None] | None = None,
) -> tuple[Path, dict[str, str]]:
    """Materialize a synthetic QA evidence tree for tests.

    The digests returned are recomputed from the generated tree. This is a test
    fixture builder, never an authenticity mechanism: production code always
    compares against independently pinned anchors.
    """

    anchors = trust_anchors()
    source_digest = source_set_digest or anchors["source_set_digest"]
    profile_value = profile or anchors["profile_digest"]
    root.mkdir(parents=True, exist_ok=True)
    document_digests: dict[str, str] = {}
    for gate, roster, toolchain in (
        ("framework-qa", FRAMEWORK_QA_ROSTER, FRAMEWORK_TOOLCHAIN_ID),
        ("source-qa", SOURCE_QA_ROSTER, SOURCE_TOOLCHAIN_ID),
    ):
        gate_dir = root / gate
        gate_dir.mkdir(parents=True, exist_ok=True)
        checks = []
        for check_id in roster:
            record = {
                "kind": "synthetic-qa-check",
                "schema_version": 1,
                "qa_gate": gate,
                "check_id": check_id,
                "evidence_origin": "synthetic",
                "qualification_scope": "simulated",
                "source_set_digest": source_digest,
                "toolchain_id": toolchain,
                "executed": True,
                "status": "pass",
                "failed": 0,
                "mandatory_skipped": 0,
            }
            write_canonical(gate_dir / f"{check_id}.json", record)
            checks.append(
                {
                    "check_id": check_id,
                    "executed": True,
                    "status": "pass",
                    "failed": 0,
                    "mandatory_skipped": 0,
                    "evidence_digest": content_digest(record),
                }
            )
        evidence = {
            "kind": "synthetic-qa-evidence",
            "schema_version": 1,
            "evidence_origin": "synthetic",
            "qualification_scope": "simulated",
            "qa_gate": gate,
            "profile_digest": profile_value,
            "source_set_digest": source_digest,
            "toolchain_id": toolchain,
            "checks": checks,
        }
        if mutate_evidence is not None:
            mutate_evidence(gate, evidence)
        write_canonical(root / f"{gate}-evidence.json", evidence)
        document_digests[gate] = content_digest(evidence)
    return root, {
        "framework_qa_digest": document_digests["framework-qa"],
        "source_qa_digest": document_digests["source-qa"],
    }


def materialize_source_tree(root: Path) -> Path:
    """Copy the exact selected source roster into a disposable git repository."""

    origin = REPO_ROOT
    for directory in SOURCE_DIRECTORIES:
        base = origin / directory
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            destination = root / path.relative_to(origin)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    for extra in EXTRA_SOURCE_FILES:
        destination = root / extra
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin / extra, destination)
    schema_root = origin / SCHEMA_DIRECTORY
    for path in sorted(schema_root.glob("*.json")):
        destination = root / SCHEMA_DIRECTORY / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "user.email=bm06@example.invalid",
        "-c",
        "user.name=BM06 Test",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    return root


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _expect(test: unittest.TestCase, code: str, callable_: Callable[[], Any]) -> None:
    with test.assertRaises(BenchError) as raised:
        callable_()
    test.assertEqual(raised.exception.code, code)


class ContractTests(unittest.TestCase):
    """CONTRACT-01…10."""

    def test_contract_01_profile_is_canonical_and_anchored(self) -> None:
        anchors = trust_anchors()
        self.assertEqual(
            set(anchors),
            {
                "kind",
                "schema_version",
                "profile_digest",
                "source_set_digest",
                "framework_qa_digest",
                "source_qa_digest",
            },
        )
        self.assertEqual(anchors["kind"], "synthetic-qualification-test-anchors")
        self.assertEqual(anchors["schema_version"], 1)
        document, digest = read_qualification_profile(
            default_profile_path(), anchors["profile_digest"]
        )
        self.assertEqual(digest, anchors["profile_digest"])
        self.assertEqual(digest, profile_digest())
        self.assertEqual(
            default_profile_path().read_bytes(), canonical_document_bytes(document)
        )
        self.assertTrue(default_profile_path().read_bytes().endswith(b"\n"))
        self.assertEqual(
            digest, "sha256:" + __import__("hashlib").sha256(
                canonical_payload_bytes(document)
            ).hexdigest()
        )

    def test_contract_02_profile_rejects_missing_extra_and_unknown_version(self) -> None:
        base = profile_document()
        missing = copy.deepcopy(base)
        del missing["required_gates"]
        _expect(self, BM_SCHEMA_INVALID, lambda: validate_profile(missing))
        extra = copy.deepcopy(base)
        extra["unexpected"] = True
        _expect(self, BM_SCHEMA_INVALID, lambda: validate_profile(extra))
        newer = copy.deepcopy(base)
        newer["schema_version"] = 2
        _expect(self, BM_SCHEMA_UNSUPPORTED, lambda: validate_profile(newer))
        boolean = copy.deepcopy(base)
        boolean["schema_version"] = True
        _expect(self, BM_SCHEMA_INVALID, lambda: validate_profile(boolean))

    def test_contract_03_profile_rejects_altered_rosters_and_checks(self) -> None:
        for mutate in (
            lambda doc: doc.__setitem__("required_gates", list(reversed(doc["required_gates"]))),
            lambda doc: doc.__setitem__(
                "required_verifier_checks", doc["required_verifier_checks"][:-1]
            ),
            lambda doc: doc.__setitem__(
                "framework_qa_roster", doc["framework_qa_roster"] + ["python-extra"]
            ),
            lambda doc: doc.__setitem__(
                "source_qa_roster", doc["source_qa_roster"][:-1]
            ),
            lambda doc: doc.__setitem__("max_document_bytes", 2097152),
            lambda doc: doc.__setitem__("profile_id", "other-profile"),
        ):
            document = copy.deepcopy(profile_document())
            mutate(document)
            with self.assertRaises(BenchError) as raised:
                validate_profile(document)
            self.assertIn(
                raised.exception.code, {BM_IDENTITY_INVALID, BM_SCHEMA_INVALID}
            )

    def test_contract_04_admission_index_rejects_bool_duplicates_and_extra(self) -> None:
        index = committed_documents()["admission-index.json"]
        validate_admission_index(index)
        boolean = copy.deepcopy(index)
        boolean["counts"]["slots_completed"] = True
        _expect(self, BM_SCHEMA_INVALID, lambda: validate_admission_index(boolean))
        duplicate = copy.deepcopy(index)
        duplicate["files"].append(copy.deepcopy(duplicate["files"][0]))
        _expect(self, BM_IDENTITY_INVALID, lambda: validate_admission_index(duplicate))
        unsorted = copy.deepcopy(index)
        unsorted["files"] = list(reversed(unsorted["files"]))
        _expect(self, BM_IDENTITY_INVALID, lambda: validate_admission_index(unsorted))
        extra = copy.deepcopy(index)
        extra["counts"]["unknown"] = 0
        _expect(self, BM_SCHEMA_INVALID, lambda: validate_admission_index(extra))

    def test_contract_05_qa_evidence_rejects_nonpassing_or_unordered_checks(self) -> None:
        evidence = read_json(FIXTURES / "framework-qa-evidence.json")
        validate_qa_evidence(evidence, "framework-qa")
        for mutate in (
            lambda doc: doc["checks"][0].__setitem__("executed", False),
            lambda doc: doc["checks"][0].__setitem__("status", "fail"),
            lambda doc: doc["checks"][0].__setitem__("failed", 1),
            lambda doc: doc["checks"][0].__setitem__("mandatory_skipped", 1),
            lambda doc: doc["checks"].reverse(),
            lambda doc: doc["checks"].append(
                {
                    "check_id": "python-extra",
                    "executed": True,
                    "status": "pass",
                    "failed": 0,
                    "mandatory_skipped": 0,
                    "evidence_digest": "sha256:" + "a" * 64,
                }
            ),
            lambda doc: doc.__setitem__("toolchain_id", "python-3-13"),
            lambda doc: doc.__setitem__("qa_gate", "source-qa"),
        ):
            document = copy.deepcopy(evidence)
            mutate(document)
            with self.assertRaises(BenchError) as raised:
                validate_qa_evidence(document, "framework-qa")
            self.assertIn(
                raised.exception.code, {BM_IDENTITY_INVALID, BM_SCHEMA_INVALID}
            )

    def test_contract_06_qa_check_record_rejects_identity_mismatch(self) -> None:
        record = read_json(FIXTURES / "framework-qa" / "python-contracts.json")
        validate_qa_check_record(record, "framework-qa", "python-contracts")
        for mutate in (
            lambda doc: doc.__setitem__("check_id", "python-vertical"),
            lambda doc: doc.__setitem__("qa_gate", "source-qa"),
            lambda doc: doc.__setitem__("executed", False),
            lambda doc: doc.__setitem__("status", "blocked"),
            lambda doc: doc.__setitem__("toolchain_id", "rust-1-85-and-1-98"),
        ):
            document = copy.deepcopy(record)
            mutate(document)
            _expect(
                self,
                BM_IDENTITY_INVALID,
                lambda document=document: validate_qa_check_record(
                    document, "framework-qa", "python-contracts"
                ),
            )

    def test_contract_07_assessment_requires_exact_check_registry(self) -> None:
        assessment = committed_documents()["verification-assessment.json"]
        validate_verification_assessment(assessment)
        truncated = copy.deepcopy(assessment)
        truncated["check_ids"] = truncated["check_ids"][:-1]
        _expect(
            self, BM_IDENTITY_INVALID, lambda: validate_verification_assessment(truncated)
        )
        wrong_kind = copy.deepcopy(assessment)
        wrong_kind["kind"] = "other"
        _expect(
            self, BM_SCHEMA_INVALID, lambda: validate_verification_assessment(wrong_kind)
        )
        promoted = copy.deepcopy(assessment)
        promoted["status"] = "verified-official"
        _expect(
            self, BM_IDENTITY_INVALID, lambda: validate_verification_assessment(promoted)
        )

    def test_contract_08_acceptance_summary_requires_exact_gate_ids(self) -> None:
        summary = committed_documents()["acceptance-summary.json"]
        validate_acceptance_summary(summary)
        missing = copy.deepcopy(summary)
        del missing["gate_receipt_ids"]["source-qa"]
        _expect(self, BM_SCHEMA_INVALID, lambda: validate_acceptance_summary(missing))
        extra = copy.deepcopy(summary)
        extra["gate_receipt_ids"]["attestation"] = "sha256:" + "a" * 64
        _expect(self, BM_SCHEMA_INVALID, lambda: validate_acceptance_summary(extra))
        unknown = copy.deepcopy(summary)
        unknown["policy_decision_status"] = "PASS"
        _expect(self, BM_IDENTITY_INVALID, lambda: validate_acceptance_summary(unknown))

    def test_contract_09_manifest_rejects_self_reference_and_bindings(self) -> None:
        manifest = committed_documents()["manifest.json"]
        validate_manifest(manifest)
        with_self = copy.deepcopy(manifest)
        with_self["members"].append(
            {"path": "manifest.json", "byte_length": 1, "digest": "sha256:" + "a" * 64}
        )
        with_self["members"].sort(key=lambda member: member["path"])
        _expect(self, BM_IDENTITY_INVALID, lambda: validate_manifest(with_self))
        swapped = copy.deepcopy(manifest)
        swapped["freeze_snapshot"]["subject"]["run_id"] = (
            "00000000-0000-4000-8000-000000000001"
        )
        _expect(self, BM_IDENTITY_INVALID, lambda: validate_manifest(swapped))
        extra = copy.deepcopy(manifest)
        extra["manifest_digest"] = "sha256:" + "a" * 64
        _expect(self, BM_SCHEMA_INVALID, lambda: validate_manifest(extra))
        snapshot = copy.deepcopy(manifest["freeze_snapshot"])
        snapshot["members"].append(
            {"path": "attestation.json", "byte_length": 1, "digest": "sha256:" + "a" * 64}
        )
        snapshot["members"].sort(key=lambda member: member["path"])
        _expect(self, BM_IDENTITY_INVALID, lambda: validate_freeze_snapshot(snapshot))

    def test_contract_10_canonical_encoding_and_budget(self) -> None:
        document = profile_document()
        payload = canonical_document_bytes(document)
        self.assertEqual(payload[-1:], b"\n")
        self.assertEqual(
            content_digest(document),
            "sha256:" + __import__("hashlib").sha256(payload[:-1]).hexdigest(),
        )
        self.assertEqual(
            canonical_document_bytes(loads_json(payload.decode("utf-8"))), payload
        )
        with self.assertRaises(BenchError) as duplicate:
            loads_json('{"a":1,"a":2}')
        self.assertEqual(duplicate.exception.code, BM_DUPLICATE_KEY)
        oversized = {"kind": "x", "schema_version": 1, "blob": "a" * MAX_DOCUMENT_BYTES}
        _expect(self, BM_UNSAFE_INPUT, lambda: bound_payload(oversized, "oversize"))
        self.assertEqual(FREEZE_MEMBERS, tuple(sorted(MEMBER_NAMES[:13])))
        self.assertEqual(MANIFEST_MEMBERS, tuple(sorted(MEMBER_NAMES[:14])))


class SourceIdentityTests(unittest.TestCase):
    """SRC-01…03."""

    def test_src_01_real_roster_matches_the_pinned_anchor(self) -> None:
        anchors = trust_anchors()
        roster = source_roster(REPO_ROOT)
        self.assertEqual(list(roster), sorted(roster))
        self.assertIn(
            "benchmarks/quervant_bench/qualification/coordinator.py", roster
        )
        self.assertIn(
            "benchmarks/quervant_bench/tests/test_qualification_integration.py", roster
        )
        self.assertEqual(
            verify_source_identity(REPO_ROOT, anchors["source_set_digest"]),
            anchors["source_set_digest"],
        )
        self.assertEqual(compute_source_set_digest(REPO_ROOT), anchors["source_set_digest"])
        self.assertEqual(require_repository_root(REPO_ROOT), REPO_ROOT.resolve())

    def test_src_02_mutated_source_byte_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_source_tree(Path(temporary) / "source")
            digest = compute_source_set_digest(root)
            target = root / "benchmarks/quervant_bench/qualification/contracts.py"
            target.write_bytes(target.read_bytes() + b"\n# mutation\n")
            self.assertNotEqual(compute_source_set_digest(root), digest)
            with self.assertRaises(BenchError) as raised:
                verify_source_identity(root, digest)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_src_03_untracked_or_symlinked_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_source_tree(Path(temporary) / "source")
            untracked = root / "benchmarks/quervant_bench/qualification/untracked.py"
            untracked.write_text("# untracked\n", encoding="utf-8")
            with self.assertRaises(BenchError) as raised:
                source_roster(root)
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            untracked.unlink()

            tracked = root / "benchmarks/quervant_bench/qualification/contracts.py"
            original = tracked.read_bytes()
            tracked.unlink()
            os.symlink(
                root / "benchmarks/quervant_bench/qualification/profiles.py", tracked
            )
            with self.assertRaises(BenchError) as linked:
                source_roster(root)
            self.assertEqual(linked.exception.code, BM_UNSAFE_INPUT)
            tracked.unlink()
            tracked.write_bytes(original)


class FixupAnchorTests(unittest.TestCase):
    """F06-A-01/02 — reviewed trust re-freeze and stale-anchor rejection."""

    def test_f06_a_01_checked_in_anchors_match_the_final_fixture_chain(self) -> None:
        anchors = trust_anchors()
        self.assertEqual(compute_source_set_digest(REPO_ROOT), anchors["source_set_digest"])
        self.assertEqual(profile_digest(), anchors["profile_digest"])
        for gate, anchor_field in (
            ("framework-qa", "framework_qa_digest"),
            ("source-qa", "source_qa_digest"),
        ):
            document = read_json(FIXTURES / f"{gate}-evidence.json")
            self.assertEqual(content_digest(document), anchors[anchor_field])
            self.assertEqual(
                document["source_set_digest"], anchors["source_set_digest"]
            )
            self.assertEqual(
                document["profile_digest"], anchors["profile_digest"]
            )
            for check in document["checks"]:
                record = read_json(
                    FIXTURES / gate / f"{check['check_id']}.json"
                )
                self.assertEqual(
                    record["source_set_digest"], anchors["source_set_digest"]
                )
                self.assertEqual(
                    content_digest(record), check["evidence_digest"]
                )

    def test_f06_a_02_stale_anchor_rejects_changed_source_and_qa_bytes(self) -> None:
        anchors = trust_anchors()
        with tempfile.TemporaryDirectory() as temporary:
            root = materialize_source_tree(Path(temporary) / "source")
            victim = root / "benchmarks/quervant_bench/qualification/coordinator.py"
            victim.write_bytes(victim.read_bytes() + b"\n# stale-anchor probe\n")
            with self.assertRaises(BenchError) as raised:
                verify_source_identity(root, anchors["source_set_digest"])
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

        with tempfile.TemporaryDirectory() as temporary:
            qa_root = Path(temporary) / "qualification"
            shutil.copytree(FIXTURES, qa_root)
            record = qa_root / "framework-qa" / "python-contracts.json"
            record.write_bytes(record.read_bytes() + b" ")
            with self.assertRaises(BenchError) as raised:
                qualification_qa.read_qa_evidence(
                    qa_evidence_root=qa_root,
                    gate="framework-qa",
                    expected_document_digest=anchors["framework_qa_digest"],
                    profile_digest=anchors["profile_digest"],
                    source_set_digest=anchors["source_set_digest"],
                )
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
