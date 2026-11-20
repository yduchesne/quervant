"""O09-PUB / O09-REU: exclusive durable publication and strict reuse."""

from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.codec import canonical_document_bytes
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_PUBLICATION_CONFLICT,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.official import contracts, publication
from quervant_bench.qualification.publication import OsPublicationIO
from quervant_bench.tests import official_support as support


class FailingIO(OsPublicationIO):
    """Fault-injecting publication backend for one chosen seam."""

    def __init__(self, seam: str) -> None:
        self.seam = seam
        self.calls: list[str] = []

    def fsync_file(self, descriptor: int) -> None:
        self.calls.append("fsync_file")
        if self.seam == "fsync_file":
            raise OSError(5, "injected fsync failure")
        super().fsync_file(descriptor)

    def hardlink_no_replace(self, source: Path, destination: Path) -> None:
        self.calls.append("hardlink")
        if self.seam == "hardlink":
            raise OSError(5, "injected link failure")
        super().hardlink_no_replace(source, destination)

    def fsync_dir(self, directory: Path) -> None:
        self.calls.append("fsync_dir")
        if self.seam == "fsync_dir" and self.calls.count("fsync_dir") == 1:
            raise OSError(5, "injected directory sync failure")
        super().fsync_dir(directory)

    def unlink_pending(self, path: Path) -> None:
        self.calls.append("unlink")
        if self.seam == "unlink":
            raise OSError(5, "injected unlink failure")
        super().unlink_pending(path)


class CurrentBaselinePublicationContractTests(unittest.TestCase):
    def _anchors(self):
        fields = {
            "subject": {"experiment_id": "cross-engine-keyword-real-v1", "run_id": "11111111-1111-4111-8111-111111111111", "protocol_digest": support.DIGEST_A, "workload_digest": support.DIGEST_B},
            **{name: support.DIGEST_A for name in (
                "approved_design_digest", "authorization_digest", "backend_protocol_digest",
                "source_set_digest", "binary_manifest_digest", "corpus_manifest_digest",
                "host_preflight_digest", "original_verifier_digest", "policy_digest",
                "qa_roster_digest", "control_assessment_digest", "history_report_digest", "relative_effects_digest",
            )},
            "acceptance_profile": "current-baseline-v2",
            "baseline_id": "44444444-4444-4444-8444-444444444444",
        }
        return publication.OfficialBaselineAnchors(**fields)

    def test_cb_v12_baseline_anchor_contract_is_exact_and_not_a_v1_subclass(self) -> None:
        from dataclasses import fields, replace

        anchors = self._anchors()
        self.assertEqual({field.name for field in fields(anchors)}, {
            "subject", "approved_design_digest", "authorization_digest", "backend_protocol_digest",
            "source_set_digest", "binary_manifest_digest", "corpus_manifest_digest", "host_preflight_digest",
            "original_verifier_digest", "policy_digest", "qa_roster_digest", "control_assessment_digest",
            "acceptance_profile", "baseline_id", "history_report_digest", "relative_effects_digest",
        })
        self.assertNotIsInstance(anchors, publication.OfficialAnchors)
        self.assertIs(publication._require_anchors(anchors, profile_version=2), anchors)
        with self.assertRaises(BenchError):
            publication._require_anchors(anchors)
        for field, value in (("acceptance_profile", "real-official-v1"), ("baseline_id", "not-a-uuid"), ("history_report_digest", None), ("relative_effects_digest", "bad-digest")):
            with self.subTest(field=field):
                with self.assertRaises(BenchError):
                    replace(anchors, **{field: value})
        class CopiedAnchors(publication.OfficialBaselineAnchors):
            pass
        copied = CopiedAnchors(**anchors.__dict__)
        with self.assertRaises(BenchError):
            publication._require_anchors(copied, profile_version=2)
        for version in (True, False, 0, 3, "2", None):
            with self.subTest(version=version):
                with self.assertRaises(BenchError):
                    publication._require_anchors(anchors, profile_version=version)

    def test_cb_v12_exact_eleven_acceptance_inputs_preserve_other_rosters(self) -> None:
        from quervant_bench.official import receipts

        anchors = self._anchors()
        documents = {name: {"fixture": name} for name in contracts.MEMBER_NAMES[:14]}
        documents["admission-index.json"]["raw_series_root_digest"] = support.DIGEST_B
        documents["analysis.json"]["raw_series_root_digest"] = support.DIGEST_B
        for name in ("framework-qa-evidence.json", "source-qa-evidence.json"):
            documents[name]["toolchain_id"] = "fixture-toolchain"
        snapshot = receipts.build_official_freeze_snapshot(
            subject=anchors.subject, approved_design_digest=anchors.approved_design_digest,
            authorization_digest=anchors.authorization_digest, source_set_digest=anchors.source_set_digest,
            members=[receipts.member_record(name, documents[name]) for name in sorted(contracts.FREEZE_MEMBERS)],
        )
        documents["manifest.json"] = {"freeze_snapshot": snapshot}
        result = publication._expected_inputs(documents, anchors, profile_version=2)
        self.assertEqual(set(result["acceptance"]), {
            "admission-index", "analysis", "authorization", "control-assessment", "framework-qa-evidence",
            "history-report", "policy", "relative-effects", "source-qa-evidence", "source-set", "verification-assessment",
        })
        self.assertEqual(result["acceptance"]["history-report"], anchors.history_report_digest)
        self.assertEqual(result["acceptance"]["relative-effects"], anchors.relative_effects_digest)
        common = {name: value for name, value in anchors.__dict__.items() if name not in {"acceptance_profile", "baseline_id", "history_report_digest", "relative_effects_digest"}}
        old = publication.OfficialAnchors(**common, historical_parity_digest=support.DIGEST_C)
        previous = publication._expected_inputs(documents, old)
        self.assertEqual(set(previous["acceptance"]), set(result["acceptance"]) - {"history-report", "relative-effects"} | {"historical-parity"})
        for gate in ("admission", "analysis", "verification", "framework-qa", "source-qa", "attestation"):
            self.assertEqual(result[gate], previous[gate])

    def test_cb_v12_live_baseline_read_rejects_missing_authority_before_io(self) -> None:
        from unittest.mock import patch
        from quervant_bench.config.errors import BM_EVIDENCE_UNAVAILABLE

        anchors = self._anchors()
        with patch.object(publication, "require_publication_base", side_effect=AssertionError("filesystem was reached")):
            with self.assertRaises(BenchError) as raised:
                publication.load_official_bundle(
                    output_base=Path("/not-a-real-baseline"),
                    study_id=anchors.subject["experiment_id"], run_id=anchors.subject["run_id"],
                    anchors=anchors,
                )
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
        self.assertEqual(raised.exception.field_path, "authorization")


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        (
            cls.result,
            cls.fixture,
            cls.admitted,
            cls.analysis,
            cls.policy,
        ) = support.published_cross_engine(cls.root)
        cls.output = cls.root / "output"
        cls.authorization = support.reopen_authorization(cls.root / "sandbox")
        cls.observed = support.authorization_observations(cls.fixture.freeze)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _members(self) -> list[tuple[str, dict]]:
        bundle = publication.load_official_bundle(
            output_base=self.output,
            study_id=self.result.study_id,
            run_id=self.result.run_id,
            anchors=self.result.anchors,
        )
        names = [name for name in contracts.MEMBER_NAMES[:14]]
        return [(name, dict(bundle.documents[name])) for name in names]

    def test_o09_pub_01_exactly_fifteen_files_are_committed(self) -> None:
        names = sorted(path.name for path in self.result.output_directory.iterdir())
        self.assertEqual(names, sorted(contracts.MEMBER_NAMES))
        self.assertNotIn(contracts.PENDING_NAME, names)

    def test_o09_pub_02_reopen_verifies_marker_and_members(self) -> None:
        bundle = publication.load_official_bundle(
            output_base=self.output,
            study_id=self.result.study_id,
            run_id=self.result.run_id,
            anchors=self.result.anchors,
        )
        self.assertEqual(bundle.disposition, publication.REUSED_VERIFIED)
        self.assertEqual(bundle.manifest_digest, self.result.manifest_digest)

    def test_o09_pub_03_republishing_the_same_destination_is_a_conflict(self) -> None:
        with self.assertRaises(BenchError) as raised:
            publication.publish_official_bundle(
                output_base=self.output,
                study_id=self.result.study_id,
                run_id=self.result.run_id,
                members=self._members(),
                manifest=dict(
                    publication.load_official_bundle(
                        output_base=self.output,
                        study_id=self.result.study_id,
                        run_id=self.result.run_id,
                        anchors=self.result.anchors,
                    ).documents["manifest.json"]
                ),
                anchors=self.result.anchors,
            authorization=self.authorization,
            observed=self.observed,
            )
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)

    def test_o09_pub_04_member_byte_mutation_is_rejected_on_reopen(self) -> None:
        target = self.result.output_directory / "analysis.json"
        original = target.read_bytes()
        document = support.read_json(target)
        document["limitations"] = sorted(set(document["limitations"] + ["tampered-limit"]))
        target.write_bytes(canonical_document_bytes(document))
        try:
            with self.assertRaises(BenchError):
                publication.load_official_bundle(
                    output_base=self.output,
                    study_id=self.result.study_id,
                    run_id=self.result.run_id,
                    anchors=self.result.anchors,
                )
        finally:
            target.write_bytes(original)

    def test_o09_pub_05_noncanonical_member_is_rejected(self) -> None:
        target = self.result.output_directory / "policy.json"
        original = target.read_bytes()
        target.write_bytes(b'{"kind": "official-policy-decision"}')
        try:
            with self.assertRaises(BenchError):
                publication.load_official_bundle(
                    output_base=self.output,
                    study_id=self.result.study_id,
                    run_id=self.result.run_id,
                    anchors=self.result.anchors,
                )
        finally:
            target.write_bytes(original)

    def test_o09_pub_06_incomplete_destination_is_never_reused(self) -> None:
        target = self.result.output_directory / "attestation.json"
        original = target.read_bytes()
        target.unlink()
        try:
            with self.assertRaises(BenchError) as raised:
                publication.load_official_bundle(
                    output_base=self.output,
                    study_id=self.result.study_id,
                    run_id=self.result.run_id,
                    anchors=self.result.anchors,
                )
            self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
        finally:
            target.write_bytes(original)

    def test_o09_pub_07_wrong_anchor_rejects_the_committed_bundle(self) -> None:
        anchors = copy.copy(self.result.anchors)
        object.__setattr__(anchors, "source_set_digest", "sha256:" + "9" * 64)
        with self.assertRaises(BenchError) as raised:
            publication.load_official_bundle(
                output_base=self.output,
                study_id=self.result.study_id,
                run_id=self.result.run_id,
                anchors=anchors,
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_pub_08_qa_roster_pin_mismatch_is_rejected(self) -> None:
        anchors = copy.copy(self.result.anchors)
        object.__setattr__(anchors, "qa_roster_digest", "sha256:" + "9" * 64)
        with self.assertRaises(BenchError):
            publication.load_official_bundle(
                output_base=self.output,
                study_id=self.result.study_id,
                run_id=self.result.run_id,
                anchors=anchors,
            )

    def test_o09_pub_09_fsync_fault_leaves_no_commit_marker(self) -> None:
        target = self.root / "fault-output"
        target.mkdir()
        with self.assertRaises(BenchError):
            publication.publish_official_bundle(
                output_base=target,
                study_id=self.result.study_id,
                run_id=self.result.run_id,
                members=self._members(),
                manifest=dict(
                    publication.load_official_bundle(
                        output_base=self.output,
                        study_id=self.result.study_id,
                        run_id=self.result.run_id,
                        anchors=self.result.anchors,
                    ).documents["manifest.json"]
                ),
                anchors=self.result.anchors,
                io=FailingIO("fsync_file"),
            authorization=self.authorization,
            observed=self.observed,
            )
        run_dir = target / self.result.study_id / self.result.run_id
        self.assertTrue(run_dir.is_dir())
        self.assertFalse((run_dir / contracts.MANIFEST_NAME).exists())
        self.assertEqual(
            publication.official_destination_state(
                target, self.result.study_id, self.result.run_id
            ),
            publication.INCOMPLETE,
        )

    def test_o09_pub_10_hardlink_fault_leaves_no_commit_marker(self) -> None:
        target = self.root / "link-output"
        target.mkdir()
        with self.assertRaises(BenchError):
            publication.publish_official_bundle(
                output_base=target,
                study_id=self.result.study_id,
                run_id=self.result.run_id,
                members=self._members(),
                manifest=dict(
                    publication.load_official_bundle(
                        output_base=self.output,
                        study_id=self.result.study_id,
                        run_id=self.result.run_id,
                        anchors=self.result.anchors,
                    ).documents["manifest.json"]
                ),
                anchors=self.result.anchors,
                io=FailingIO("hardlink"),
            authorization=self.authorization,
            observed=self.observed,
            )
        run_dir = target / self.result.study_id / self.result.run_id
        self.assertTrue((run_dir / contracts.PENDING_NAME).exists())
        self.assertFalse((run_dir / contracts.MANIFEST_NAME).exists())

    def test_o09_pub_11_partial_destination_is_never_repaired(self) -> None:
        target = self.root / "partial-output"
        run_dir = target / self.result.study_id / self.result.run_id
        run_dir.mkdir(parents=True)
        (run_dir / "foreign.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(BenchError) as raised:
            publication.publish_official_bundle(
                output_base=target,
                study_id=self.result.study_id,
                run_id=self.result.run_id,
                members=self._members(),
                manifest=dict(
                    publication.load_official_bundle(
                        output_base=self.output,
                        study_id=self.result.study_id,
                        run_id=self.result.run_id,
                        anchors=self.result.anchors,
                    ).documents["manifest.json"]
                ),
                anchors=self.result.anchors,
            authorization=self.authorization,
            observed=self.observed,
            )
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
        self.assertTrue((run_dir / "foreign.json").exists())

    def test_o09_reu_01_reuse_is_read_only(self) -> None:
        before = {
            path.name: (path.stat().st_mtime_ns, path.read_bytes())
            for path in self.result.output_directory.iterdir()
        }
        publication.load_official_bundle(
            output_base=self.output,
            study_id=self.result.study_id,
            run_id=self.result.run_id,
            anchors=self.result.anchors,
        )
        after = {
            path.name: (path.stat().st_mtime_ns, path.read_bytes())
            for path in self.result.output_directory.iterdir()
        }
        self.assertEqual(before, after)

    def test_o09_reu_02_symlinked_destination_is_rejected(self) -> None:
        target = self.root / "link-root"
        target.mkdir()
        experiment = target / self.result.study_id
        experiment.mkdir()
        os.symlink(self.result.output_directory, experiment / self.result.run_id)
        with self.assertRaises(BenchError) as raised:
            publication.official_destination_state(
                target, self.result.study_id, self.result.run_id
            )
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_reu_03_missing_destination_is_unavailable(self) -> None:
        with self.assertRaises(BenchError):
            publication.load_official_bundle(
                output_base=self.root / "absent",
                study_id=self.result.study_id,
                run_id=self.result.run_id,
                anchors=self.result.anchors,
            )

    def test_o09_reu_04_missing_anchors_are_rejected(self) -> None:
        with self.assertRaises(BenchError):
            publication.load_official_bundle(
                output_base=self.output,
                study_id=self.result.study_id,
                run_id=self.result.run_id,
                anchors=None,  # type: ignore[arg-type]
            )

    def test_o09_pub_12_duplicate_member_order_is_rejected(self) -> None:
        members = self._members()
        with self.assertRaises(BenchError):
            publication.publish_official_bundle(
                output_base=self.root / "order-output",
                study_id=self.result.study_id,
                run_id=self.result.run_id,
                members=list(reversed(members)),
                manifest=dict(
                    publication.load_official_bundle(
                        output_base=self.output,
                        study_id=self.result.study_id,
                        run_id=self.result.run_id,
                        anchors=self.result.anchors,
                    ).documents["manifest.json"]
                ),
                anchors=self.result.anchors,
            authorization=self.authorization,
            observed=self.observed,
            )


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()


class PreflightAnchorTests(unittest.TestCase):
    """RF09-05 / PUBF: external anchors are validated BEFORE any durable write."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        (
            cls.result,
            cls.fixture,
            cls.admitted,
            cls.analysis,
            cls.policy,
        ) = support.published_cross_engine(cls.root)
        cls.output = cls.root / "output"
        cls.authorization = support.reopen_authorization(cls.root / "sandbox")
        cls.observed = support.authorization_observations(cls.fixture.freeze)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _bundle_documents(self) -> tuple[list[tuple[str, dict]], dict]:
        bundle = publication.load_official_bundle(
            output_base=self.output,
            study_id=self.result.study_id,
            run_id=self.result.run_id,
            anchors=self.result.anchors,
        )
        names = list(contracts.MEMBER_NAMES[:14])
        return (
            [(name, dict(bundle.documents[name])) for name in names],
            dict(bundle.documents["manifest.json"]),
        )

    def test_pubf_01_missing_anchors_write_nothing(self) -> None:
        members, manifest = self._bundle_documents()
        target = self.root / "pubf01"
        target.mkdir()
        with self.assertRaises(BenchError):
            publication.publish_official_bundle(
                output_base=target,
                study_id=self.result.study_id,
                run_id="aaaaaaa1-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
                members=members,
                manifest=manifest,
                anchors=None,  # type: ignore[arg-type]
                 authorization=self.authorization,
                 observed=self.observed,
            )
        self.assertFalse((target / self.result.study_id).exists())

    def test_pubf_02_wrong_anchor_digest_writes_nothing(self) -> None:
        members, manifest = self._bundle_documents()
        anchors = copy.copy(self.result.anchors)
        object.__setattr__(anchors, "historical_parity_digest", "sha256:" + "8" * 64)
        target = self.root / "pubf02"
        target.mkdir()
        with self.assertRaises(BenchError):
            publication.publish_official_bundle(
                output_base=target,
                study_id=self.result.study_id,
                run_id="aaaaaaa2-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
                members=members,
                manifest=manifest,
                anchors=anchors,
                authorization=support.fixture_authorization("cross-engine-keyword-real-v1"),
            )
        self.assertFalse((target / self.result.study_id).exists())

    def test_pubf_03_manifest_derived_anchors_without_g0_record_write_nothing(self) -> None:
        members, manifest = self._bundle_documents()
        target = self.root / "pubf03"
        target.mkdir()
        with self.assertRaises(BenchError):
            publication.publish_official_bundle(
                output_base=target,
                study_id=self.result.study_id,
                run_id="aaaaaaa3-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
                members=members,
                manifest=manifest,
                anchors=self.result.anchors,
                authorization=self.authorization,
                observed=self.observed,
            )
        self.assertFalse((target / self.result.study_id).exists())

    def test_pubf_06_writer_is_never_reached_for_invalid_anchors(self) -> None:
        members, manifest = self._bundle_documents()
        target = self.root / "pubf06"
        target.mkdir()
        with self.assertRaises(BenchError):
            publication.publish_official_bundle(
                output_base=target,
                study_id=self.result.study_id,
                run_id="aaaaaaa6-aaaa-4aaa-8aaa-aaaaaaaaaaa6",
                members=members,
                manifest=manifest,
                anchors=None,  # type: ignore[arg-type]
                io=FailingIO("fsync_file"),
            authorization=self.authorization,
            observed=self.observed,
            )
        self.assertFalse((target / self.result.study_id).exists())

    def test_pubf_07_in_memory_dry_run_never_persists(self) -> None:
        members, manifest = self._bundle_documents()
        target = self.root / "pubf07"
        report = publication.validate_official_bundle_in_memory(
            output_base=target,
            study_id=self.result.study_id,
            run_id=self.result.run_id,
            members=members,
            manifest=manifest,
            anchors=self.result.anchors,
            authorization=self.authorization,
        )
        self.assertEqual(report["disposition"], "TEST_ONLY_GRAPH_VERIFIED")
        self.assertFalse(target.exists())
