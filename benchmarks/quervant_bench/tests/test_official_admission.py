"""O09-ADM / O09-ACQ: Gate A raw-evidence admission and archive security."""

from __future__ import annotations

import copy
import dataclasses
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quervant_bench.config.codec import canonical_document_bytes, content_digest

from quervant_bench.config.errors import (
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.evidence.archives import ArchiveLimits, inspect_tar_gz
from quervant_bench.official import admission, analysis, authorization, historical, protocols, verification
from quervant_bench.official import controls as official_controls
from quervant_bench.tests import official_support as support


class CrossEngineAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.fixture = support.make_cross_engine_fixture(self.root)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _admit(self, **overrides):
        arguments = {
            "raw_root": self.fixture.raw_root,
            "authorization": support.fixture_authorization(
                "cross-engine-keyword-real-v1", freeze=self.fixture.freeze
            ),
            "template": self.fixture.template,
            "corpus_dir": self.fixture.corpus_root,
            "control_document": self.fixture.control,
            "original_verifier": support.StubVerifier(),
        }
        arguments.update(overrides)
        return support._admit_fixture_cross_engine_with_verifier(**arguments)

    def test_o09_adm_01_complete_series_is_admitted(self) -> None:
        admitted = self._admit()
        self.assertEqual(admitted.admission_index["series_status"], "ADMITTED_REAL")
        self.assertEqual(len(admitted.trials), 9)
        self.assertEqual(len(admitted.inventory), len(admitted.admission_index["members"]))

    def test_o09_acq_01_missing_trial_manifest_is_rejected(self) -> None:
        (self.fixture.raw_root / "backend" / "trials" / "trial-2" / "lucene.json").unlink()
        with self.assertRaises(BenchError):
            self._admit()

    def test_o09_acq_02_nineteen_samples_are_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "trials" / "trial-1" / "quervant.json"
        document = support.read_json(path)
        document["lanes"][0]["samples_ns"] = document["lanes"][0]["samples_ns"][1:]
        support.write_json(path, document)
        with self.assertRaises(BenchError) as raised:
            self._admit()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_acq_03_wrong_regime_set_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "trials" / "trial-1" / "quervant.json"
        document = support.read_json(path)
        for lane in document["lanes"]:
            lane["regime"] = "warm"
            lane["warmups"] = 5
            lane["warmup_ids"] = [f"{lane['id']}:warmup:{index}" for index in range(5)]
        support.write_json(path, document)
        with self.assertRaises(BenchError) as raised:
            self._admit()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_acq_04_wrong_trial_order_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "trials" / "trial-1" / "tantivy.json"
        document = support.read_json(path)
        document["trial"] = 2
        support.write_json(path, document)
        with self.assertRaises(BenchError) as raised:
            self._admit()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_acq_05_missing_build_record_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "trials" / "trial-3" / "tantivy.json"
        document = support.read_json(path)
        del document["build"]["100000"]
        support.write_json(path, document)
        with self.assertRaises(BenchError):
            self._admit()

    def test_o09_acq_06_short_throughput_window_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "trials" / "trial-2" / "quervant.json"
        document = support.read_json(path)
        document["throughput"][0]["requests"] = 99
        support.write_json(path, document)
        with self.assertRaises(BenchError) as raised:
            self._admit()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_acq_07_wrong_corpus_digest_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "run.json"
        document = support.read_json(path)
        document["corpus_manifest_sha256"] = "0" * 64
        support.write_json(path, document)
        with self.assertRaises(BenchError) as raised:
            self._admit()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_acq_07b_engine_version_drift_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "run.json"
        document = support.read_json(path)
        document["adapters"]["tantivy"]["engine_version"] = "0.20.0"
        support.write_json(path, document)
        with self.assertRaises(BenchError):
            self._admit()

    def test_o09_acq_08_contended_trial_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "trials" / "trial-1" / "lucene.json"
        document = support.read_json(path)
        document["contention"][0]["state"] = "busy"
        support.write_json(path, document)
        with self.assertRaises(BenchError):
            self._admit()

    def test_o09_adm_02_unqualified_run_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "run.json"
        document = support.read_json(path)
        document["qualified"] = False
        support.write_json(path, document)
        with self.assertRaises(BenchError):
            self._admit()

    def test_o09_adm_03_unqualified_validation_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "validation.json"
        support.write_json(path, {"schema": "pr15d-validation-v1", "status": "UNQUALIFIED", "errors": [], "unqualified": []})
        with self.assertRaises(BenchError):
            self._admit()

    def test_o09_adm_03b_original_validator_rejection_is_rejected(self) -> None:
        class Rejecting(support.StubVerifier):
            def verify_cross_engine(self, run_root, *, corpus_dir=None):
                from quervant_bench.official.admission import OriginalVerifierOutcome

                return OriginalVerifierOutcome(status="UNQUALIFIED", detail="stub", report={})

        with self.assertRaises(BenchError):
            self._admit(original_verifier=Rejecting())

    def test_o09_adm_04_failing_control_blocks_admission(self) -> None:
        control = copy.deepcopy(self.fixture.control)
        control["a_a"] = {"passes": False, "lanes": control["a_a"]["lanes"]}
        with self.assertRaises(BenchError) as raised:
            self._admit(control_document=control)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_adm_04b_control_lane_set_drift_is_rejected(self) -> None:
        control = copy.deepcopy(self.fixture.control)
        control["lanes"] = control["lanes"][:-1]
        with self.assertRaises(BenchError):
            self._admit(control_document=control)

    def test_o09_adm_09_last_sample_mutation_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "trials" / "trial-1" / "quervant.json"
        document = support.read_json(path)
        document["lanes"][0]["samples_ns"][19] = 1
        support.write_json(path, document)
        with self.assertRaises(BenchError) as raised:
            self._admit()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_adm_09b_non_positive_sample_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "trials" / "trial-1" / "quervant.json"
        document = support.read_json(path)
        document["lanes"][0]["samples_ns"][0] = 0
        support.write_json(path, document)
        with self.assertRaises(BenchError) as raised:
            self._admit()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_adm_10_reversed_doc_ids_are_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "trials" / "trial-1" / "quervant.json"
        document = support.read_json(path)
        target = next(lane for lane in document["lanes"] if len(lane["doc_ids"]) > 1)
        target["doc_ids"] = list(reversed(target["doc_ids"]))
        support.write_json(path, document)
        with self.assertRaises(BenchError) as raised:
            self._admit()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_adm_11_required_trial_removal_is_rejected(self) -> None:
        shutil.rmtree(self.fixture.raw_root / "backend" / "trials" / "trial-3")
        with self.assertRaises(BenchError):
            self._admit()

    def test_o09_adm_13_unexpected_file_is_reported_by_the_inventory(self) -> None:
        admitted = self._admit()
        extra = self.fixture.raw_root / "backend" / "unexpected.json"
        support.write_json(extra, {"unexpected": True})
        digest_after = admission.cross_engine_inventory_digest(self.fixture.raw_root)
        self.assertNotEqual(digest_after, admitted.raw_series_root_digest)
        extra.unlink()
        self.assertEqual(
            admission.cross_engine_inventory_digest(self.fixture.raw_root),
            admitted.raw_series_root_digest,
        )

    def test_o09_adm_15_cross_engine_corpus_anchor_mismatch_is_rejected(self) -> None:
        freeze = support.make_freeze(
            study_id="cross-engine-keyword-real-v1",
            corpus_manifest_digest="sha256:" + "5" * 64,
            original_verifier_digest=support.verifier_digest("benchmarks/pr15d/harness/validate.py"),
        )
        authorization = support.fixture_authorization(
            "cross-engine-keyword-real-v1", freeze=freeze
        )
        with self.assertRaises(BenchError) as raised:
            self._admit(authorization=authorization)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_adm_15b_cross_engine_verifier_anchor_mismatch_is_rejected(self) -> None:
        freeze = support.make_freeze(
            study_id="cross-engine-keyword-real-v1",
            corpus_manifest_digest=self.fixture.freeze.corpus_manifest_digest,
            original_verifier_digest="sha256:" + "6" * 64,
        )
        authorization = support.fixture_authorization(
            "cross-engine-keyword-real-v1", freeze=freeze
        )
        with self.assertRaises(BenchError) as raised:
            self._admit(authorization=authorization)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


class RetainedKeyAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.fixture = support.make_retained_key_fixture(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _admit(self, **overrides):
        arguments = {
            "raw_root": self.fixture.raw_root,
            "authorization": support.fixture_authorization(
                "retained-key-topk-real-v1", freeze=self.fixture.freeze
            ),
            "template": self.fixture.template,
            "original_verifier": support.StubVerifier(),
        }
        arguments.update(overrides)
        return support._admit_fixture_retained_key_with_verifier(**arguments)

    def test_o09_acq_09_full_series_is_admitted(self) -> None:
        admitted = self._admit()
        self.assertEqual(set(admitted.slots), set(admission.D3C_CAMPAIGN_NAMES) | {admission.D3C_CONTROL_NAME})
        self.assertEqual(len(admitted.slots[admission.D3C_CONTROL_NAME]), 48)
        self.assertEqual(len(admitted.slots[admission.D3C_CAMPAIGN_NAMES[0]]), 96)
        self.assertTrue(admitted.control_assessment["a_a"]["passes"])

    def test_o09_acq_10_missing_slot_is_rejected(self) -> None:
        slot = self.fixture.raw_root / admission.D3C_CAMPAIGN_NAMES[0] / "raw" / "slots" / "slot-12.json"
        original = slot.read_bytes()
        try:
            slot.unlink()
            with self.assertRaises(BenchError):
                self._admit()
        finally:
            slot.write_bytes(original)

    def test_o09_acq_11_wrong_mode_marker_is_rejected(self) -> None:
        path = self.fixture.raw_root / admission.D3C_CAMPAIGN_NAMES[0] / "raw" / "slots" / "slot-01.json"
        document = support.read_json(path)
        document["lanes"][0]["mode_marker"] = "PR15I_D3C_MODE=v1:wrong:none"
        support.write_json(path, document)
        try:
            with self.assertRaises(BenchError) as raised:
                self._admit()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            document["lanes"][0]["mode_marker"] = admission.D3C_MODE_MARKERS[document["arm"]]
            support.write_json(path, document)

    def test_o09_acq_12_changed_index_sentinel_is_rejected(self) -> None:
        path = self.fixture.raw_root / admission.D3C_CONTROL_NAME / "manifest.json"
        document = support.read_json(path)
        document["arms"]["A"]["indexes"]["100000"]["bytes"] += 1
        document["arms"]["B"]["indexes"]["100000"]["bytes"] += 1
        support.write_json(path, document)
        try:
            with self.assertRaises(BenchError) as raised:
                self._admit()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            document["arms"]["A"]["indexes"]["100000"]["bytes"] -= 1
            document["arms"]["B"]["indexes"]["100000"]["bytes"] -= 1
            support.write_json(path, document)

    def test_o09_acq_13_failed_original_verifier_is_rejected(self) -> None:
        with self.assertRaises(BenchError) as raised:
            self._admit(
                original_verifier=support.StubVerifier(campaign_status="ACQUISITION_INCOMPLETE")
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_acq_13b_failed_series_verifier_is_rejected(self) -> None:
        with self.assertRaises(BenchError):
            self._admit(original_verifier=support.StubVerifier(series_status="FAIL"))

    def test_o09_acq_14_control_summary_false_is_rejected(self) -> None:
        path = self.fixture.raw_root / admission.D3C_CONTROL_NAME / "sanitized" / "summary.json"
        original = path.read_bytes()
        document = support.read_json(path)
        document["a_a"] = {"passes": False}
        support.write_json(path, document)
        try:
            with self.assertRaises(BenchError) as raised:
                self._admit()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            path.write_bytes(original)

    def test_o09_acq_15_rehearsal_campaign_is_rejected(self) -> None:
        path = self.fixture.raw_root / admission.D3C_CONTROL_NAME / "authorization.json"
        original = path.read_bytes()
        document = support.read_json(path)
        document["rehearsal_only"] = True
        support.write_json(path, document)
        try:
            with self.assertRaises(BenchError) as raised:
                self._admit()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            path.write_bytes(original)

    def test_o09_acq_16_seal_mismatch_is_rejected(self) -> None:
        path = self.fixture.raw_root / admission.D3C_CAMPAIGN_NAMES[1] / "raw" / "seal.json"
        original = path.read_bytes()
        document = support.read_json(path)
        document["files"]["manifest.json"] = "0" * 64
        support.write_json(path, document)
        try:
            with self.assertRaises(BenchError) as raised:
                self._admit()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            path.write_bytes(original)

    def test_o09_acq_16b_unexpected_member_is_rejected_by_the_seal(self) -> None:
        extra = self.fixture.raw_root / admission.D3C_CONTROL_NAME / "raw" / "unexpected.json"
        support.write_json(extra, {"unexpected": True})
        try:
            with self.assertRaises(BenchError) as raised:
                self._admit()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            extra.unlink()


class ArchiveSecurityTests(unittest.TestCase):
    def test_o09_adm_05_traversal_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "evil.tar.gz"
            payload = root / "payload.bin"
            payload.write_bytes(b"x")
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(payload, arcname="../escape.bin")
            with self.assertRaises(BenchError) as raised:
                inspect_tar_gz(root, "evil.tar.gz")
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_adm_06_duplicate_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "duplicate.tar.gz"
            payload = root / "payload.bin"
            payload.write_bytes(b"x")
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(payload, arcname="member.bin")
                handle.add(payload, arcname="member.bin")
            with self.assertRaises(BenchError) as raised:
                inspect_tar_gz(root, "duplicate.tar.gz")
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_adm_07_symlink_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "link.tar.gz"
            payload = root / "payload.bin"
            payload.write_bytes(b"x")
            link = root / "link.bin"
            import os

            os.symlink(payload, link)
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(link, arcname="link.bin")
            with self.assertRaises(BenchError) as raised:
                inspect_tar_gz(root, "link.tar.gz")
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_adm_08_member_budget_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "budget.tar.gz"
            payload = root / "payload.bin"
            payload.write_bytes(b"x" * 32)
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(payload, arcname="member.bin")
            with self.assertRaises(BenchError) as raised:
                inspect_tar_gz(root, "budget.tar.gz", ArchiveLimits(max_member_bytes=8))
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)


class HistoricalArchiveAuditTests(unittest.TestCase):
    def test_o09_his_07_missing_archive_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(BenchError):
                historical.audit_retained_key_archive(Path(temporary), "d3c-v3r3-base-aa-01")

    def test_o09_his_08_declared_archive_digest_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, expected = support.approved_archive(Path(temporary) / "archive")
            self.assertEqual(len(historical.audit_declared_archive(root, expected)), 2)
            (root / "run.json").write_text('{"tampered":true}', encoding="utf-8")
            with self.assertRaises(BenchError) as raised:
                historical.audit_declared_archive(root, expected)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_his_09_extra_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, expected = support.approved_archive(Path(temporary) / "archive")
            (root / "extra.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(BenchError):
                historical.audit_declared_archive(root, expected)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()


class VerifierAuthorityTests(unittest.TestCase):
    """RF09-06 / VERF: production Gate A runs the pinned verifier, never a stub."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.fixture = support.make_cross_engine_fixture(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_g0f_03_bare_freeze_is_rejected_by_cross_engine_admission(self) -> None:
        # A parsed freeze is not an authorization: the production signature admits
        # only ``authorization=``, so a freeze keyword is a signature-level rejection.
        with self.assertRaises(TypeError):
            admission.admit_cross_engine_real(
                raw_root=self.fixture.raw_root,
                freeze=self.fixture.freeze,
                template=self.fixture.template,
                corpus_dir=self.fixture.corpus_root,
                control_document=self.fixture.control,
            )
        with self.assertRaises(BenchError) as raised:
            admission.admit_cross_engine_real(
                raw_root=self.fixture.raw_root,
                authorization=self.fixture.freeze,
                template=self.fixture.template,
                corpus_dir=self.fixture.corpus_root,
                control_document=self.fixture.control,
            )
        self.assertEqual(raised.exception.field_path, "authorization")

    def test_verf_01_injected_original_verifier_is_rejected(self) -> None:
        authorization = support.fixture_authorization(
            "cross-engine-keyword-real-v1", freeze=self.fixture.freeze
        )
        with self.assertRaises(TypeError):
            admission.admit_cross_engine_real(
                raw_root=self.fixture.raw_root,
                authorization=authorization,
                template=self.fixture.template,
                corpus_dir=self.fixture.corpus_root,
                control_document=self.fixture.control,
                original_verifier=support.StubVerifier(),
            )
        with self.assertRaises(BenchError) as raised:
            admission.admit_cross_engine_real(
                raw_root=self.fixture.raw_root,
                authorization=authorization,
                template=self.fixture.template,
                corpus_dir=self.fixture.corpus_root,
                control_document=self.fixture.control,
            )
        self.assertEqual(raised.exception.field_path, "authorization")

    def test_verf_02_fixture_record_is_not_official_eligible(self) -> None:
        admitted = support._admit_fixture_cross_engine_with_verifier(
            raw_root=self.fixture.raw_root,
            authorization=support.fixture_authorization(
                "cross-engine-keyword-real-v1", freeze=self.fixture.freeze
            ),
            template=self.fixture.template,
            corpus_dir=self.fixture.corpus_root,
            control_document=self.fixture.control,
            original_verifier=support.StubVerifier(),
        )
        self.assertIs(admitted.fixture_only, True)

    def test_verf_03_verifier_source_digest_is_checked_before_invocation(self) -> None:
        import dataclasses

        authorization = support.fixture_authorization(
            "cross-engine-keyword-real-v1",
            freeze=dataclasses.replace(
                self.fixture.freeze,
                original_reference_verifier_digest="sha256:" + "7" * 64,
            ),
        )
        with self.assertRaises(BenchError) as raised:
            support._admit_fixture_cross_engine_with_verifier(
                raw_root=self.fixture.raw_root,
                authorization=authorization,
                template=self.fixture.template,
                corpus_dir=self.fixture.corpus_root,
                control_document=self.fixture.control,
                original_verifier=support.StubVerifier(),
            )
        self.assertEqual(raised.exception.code, "BM_IDENTITY_INVALID")

    def test_verf_04_production_admission_requires_a_capability(self) -> None:
        for value in (None, self.fixture.freeze, object()):
            with self.assertRaises((TypeError, BenchError)):
                admission.admit_retained_key_real(
                    raw_root=self.root / "absent",
                    authorization=value,
                    template=self.fixture.template,
                )


class VerifiedAdmissionBoundaryTests(unittest.TestCase):
    """RF09-08 / ADMF: only a production-issued, re-admitted capability may pass."""

    @classmethod
    def setUpClass(cls) -> None:
        import dataclasses

        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.fixture = support.make_cross_engine_fixture(cls.root / "fixture")
        cls.authorization = support.production_shaped_authorization(
            cls.fixture.freeze, sandbox=cls.root / "sandbox"
        )
        cls.observed = support.authorization_observations(cls.fixture.freeze)
        cls.admitted = admission.admit_cross_engine_real(
            raw_root=cls.fixture.raw_root,
            authorization=cls.authorization,
            template=cls.fixture.template,
            corpus_dir=cls.fixture.corpus_root,
            control_document=cls.fixture.control,
            source_root=support.REPO_ROOT,
            observed=cls.observed,
        )
        cls.fixture_record = support.admit_fixture_cross_engine(cls.fixture)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_admf_01_public_admission_returns_a_verified_capability(self) -> None:
        from quervant_bench.official import admission as official_admission

        self.assertIsInstance(self.admitted, official_admission.VerifiedOfficialAdmission)
        self.assertEqual(self.admitted.study_id, "cross-engine-keyword-real-v1")
        self.assertEqual(
            self.admitted.raw_series_root_digest,
            self.admitted._record.raw_series_root_digest,
        )

    def test_admf_03_promoted_fixture_record_is_rejected_by_the_coordinator(self) -> None:
        import dataclasses

        from quervant_bench.official import coordinator

        promoted = dataclasses.replace(self.fixture_record, fixture_only=False)
        with self.assertRaises(BenchError) as raised:
            coordinator.qualify_official_study(
                authorization=self.authorization,
                template=self.fixture.template,
                admitted=promoted,
                framework_qa=self.fixture.framework_qa,
                source_qa=self.fixture.source_qa,
                historical_parity=support.fixture_historical_parity(
                    "cross-engine-keyword-real-v1"
                ),
                output_base=self.root / "admf03",
                qa_evidence_root=self.fixture.qa_evidence_root,
                source_root=support.REPO_ROOT,
                observed=self.observed,
            )
        self.assertIn(raised.exception.code, ("BM_UNSAFE_INPUT", "BM_EVIDENCE_UNAVAILABLE"))

    def test_admf_04_directly_constructed_capability_is_rejected(self) -> None:
        from quervant_bench.official import admission as official_admission

        with self.assertRaises((TypeError, BenchError)):
            official_admission.VerifiedOfficialAdmission(
                study_id="cross-engine-keyword-real-v1",
                authorization_digest=self.fixture_record.admission_index["authorization_digest"],
                raw_series_root_digest=self.fixture_record.raw_series_root_digest,
                admission_index_digest="sha256:" + "1" * 64,
                original_verifier_source_digest="sha256:" + "2" * 64,
                _record=self.fixture_record,
            )

    def test_admf_09_changed_raw_bytes_fail_re_admission(self) -> None:
        from quervant_bench.official import admission as official_admission

        path = self.fixture.raw_root / "backend" / "trials" / "trial-1" / "quervant.json"
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document["lanes"][0]["samples_ns"][0] += 1
            support.write_json(path, document)
            with self.assertRaises(BenchError):
                official_admission.reverify_official_admission(
                    self.admitted,
                    authorization=self.authorization,
                    template=self.fixture.template,
                    source_root=support.REPO_ROOT,
                    observed=self.observed,
                )
        finally:
            path.write_bytes(original)

    def test_admf_11_re_admission_leaves_raw_bytes_untouched(self) -> None:
        from quervant_bench.official import admission as official_admission

        before = {
            path.relative_to(self.fixture.raw_root): path.read_bytes()
            for path in sorted(self.fixture.raw_root.rglob("*"))
            if path.is_file()
        }
        official_admission.reverify_official_admission(
            self.admitted,
            authorization=self.authorization,
            template=self.fixture.template,
            source_root=support.REPO_ROOT,
            observed=self.observed,
        )
        after = {
            path.relative_to(self.fixture.raw_root): path.read_bytes()
            for path in sorted(self.fixture.raw_root.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(before, after)

    def test_admf_12_missing_source_root_blocks_production_admission(self) -> None:
        with self.assertRaises(BenchError) as raised:
            admission.admit_cross_engine_real(
                raw_root=self.fixture.raw_root,
                authorization=self.authorization,
                template=self.fixture.template,
                corpus_dir=self.fixture.corpus_root,
                control_document=self.fixture.control,
                observed=self.observed,
            )
        self.assertEqual(raised.exception.code, "BM_EVIDENCE_UNAVAILABLE")

    def test_admf_08_gate_c_requires_the_verified_capability(self) -> None:
        from quervant_bench.official import analysis as official_analysis
        from quervant_bench.official import verification

        record = self.admitted.record
        analysis_document, policy_document = official_analysis.analyze_official_study(
            admitted=record, template=self.fixture.template
        )
        with self.assertRaises(BenchError) as raised:
            verification.verify_official_study(
                admitted=record,
                template=self.fixture.template,
                authorization=self.authorization,
                analysis=analysis_document,
                policy=policy_document,
                source_root=support.REPO_ROOT,
                observed=self.observed,
            )
        self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")

    def test_admf_10_foreign_capability_is_rejected(self) -> None:
        from quervant_bench.official import admission as official_admission

        other = support.make_freeze(
            study_id="cross-engine-keyword-real-v1", run_id="99999999-9999-4999-8999-999999999999"
        )
        with self.assertRaises(BenchError):
            official_admission.reverify_official_admission(
                self.admitted,
                authorization=support.fixture_authorization(
                    "cross-engine-keyword-real-v1", freeze=other
                ),
                template=self.fixture.template,
                source_root=support.REPO_ROOT,
            )


class CrossEngineControlProvenanceTests(unittest.TestCase):
    """RF09-13 / F4-CP: the persisted canonical control is the only authority."""

    @classmethod
    def setUpClass(cls) -> None:
        import copy

        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.fixture = support.make_cross_engine_fixture(cls.root / "fixture")
        cls.control_path = cls.fixture.raw_root / "control" / "control.json"
        cls.pristine_bytes = cls.control_path.read_bytes()
        cls.pristine_control = copy.deepcopy(dict(cls.fixture.control))
        cls.capability, cls.authorization = support.admit_production_shaped_cross_engine(
            cls.fixture, sandbox=cls.root / "sandbox"
        )
        cls.observed = support.authorization_observations(cls.fixture.freeze)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.control_path.write_bytes(cls.pristine_bytes)
        cls._temporary.cleanup()

    def tearDown(self) -> None:
        self.control_path.write_bytes(self.pristine_bytes)

    def _admit(self, *, control_document):
        return admission.admit_cross_engine_real(
            raw_root=self.fixture.raw_root,
            authorization=self.authorization,
            template=self.fixture.template,
            corpus_dir=self.fixture.corpus_root,
            control_document=control_document,
            source_root=support.REPO_ROOT,
            observed=self.observed,
        )

    def admissible_record(self):
        """Return the fixture admission record used for inventory digests."""

        return self.capability.record

    def _control_variant(self, **changes):
        import copy

        variant = copy.deepcopy(self.pristine_control)
        variant.update(changes)
        return variant

    def test_f4_cp_01_canonical_control_is_admitted(self) -> None:
        capability = self._admit(control_document=dict(self.pristine_control))
        self.assertIsInstance(capability, admission.VerifiedOfficialAdmission)
        self.assertIs(capability.record.fixture_only, False)
        self.assertEqual(
            capability.record.control["block_count"],
            self.pristine_control["block_count"],
        )
        from quervant_bench.config.codec import canonical_payload_bytes

        self.assertEqual(
            canonical_payload_bytes(dict(capability.record.control)),
            canonical_payload_bytes(self.pristine_control),
        )
        self.assertEqual(self.control_path.read_bytes(), self.pristine_bytes)
        # A reordered (equivalent) mapping must be accepted.
        reordered = {key: self.pristine_control[key] for key in reversed(list(self.pristine_control))}
        capability2 = self._admit(control_document=reordered)
        self.assertEqual(
            canonical_payload_bytes(dict(capability2.record.control)),
            canonical_payload_bytes(self.pristine_control),
        )
        # Pristine re-admission succeeds with equivalent content.
        fresh = admission.reverify_official_admission(
            capability,
            authorization=self.authorization,
            template=self.fixture.template,
            source_root=support.REPO_ROOT,
            observed=self.observed,
        )
        self.assertEqual(fresh.raw_series_root_digest, capability.raw_series_root_digest)

    def test_f4_cp_02_supplied_control_mismatch_is_rejected(self) -> None:
        self.assertEqual(self.pristine_control["block_count"], 12)
        variant = self._control_variant(block_count=11)
        with self.assertRaises(BenchError) as raised:
            self._admit(control_document=variant)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "control")
        self.assertEqual(self.control_path.read_bytes(), self.pristine_bytes)

    def test_f4_cp_03_numeric_type_alias_is_rejected(self) -> None:
        from quervant_bench.config.codec import canonical_payload_bytes

        variant = self._control_variant(block_count=12.0)
        self.assertEqual(variant, self.pristine_control)  # Python equality hides the alias
        self.assertNotEqual(
            canonical_payload_bytes(variant),
            canonical_payload_bytes(self.pristine_control),
        )
        with self.assertRaises(BenchError) as raised:
            self._admit(control_document=variant)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "control")
        self.assertEqual(self.control_path.read_bytes(), self.pristine_bytes)

    def test_f4_cp_04_input_nested_mutation_does_not_alias_record(self) -> None:
        import copy

        supplied = copy.deepcopy(self.pristine_control)
        capability = self._admit(control_document=supplied)
        admitted_control = capability.record.control
        snapshot = copy.deepcopy(dict(admitted_control))
        first_lane = sorted(supplied["a_a"]["lanes"])[0]
        supplied["a_a"]["lanes"][first_lane]["block_ratios"][0] = "9.999999"
        self.assertEqual(dict(admitted_control), snapshot)
        self.assertEqual(self.control_path.read_bytes(), self.pristine_bytes)
        admission.reverify_official_admission(
            capability,
            authorization=self.authorization,
            template=self.fixture.template,
            source_root=support.REPO_ROOT,
            observed=self.observed,
        )

    def test_f4_cp_05_missing_control_file_is_rejected(self) -> None:
        self.control_path.unlink()
        try:
            with self.assertRaises(BenchError) as raised:
                self._admit(control_document=dict(self.pristine_control))
            self.assertEqual(raised.exception.code, BM_FILE_MISSING)
        finally:
            self.control_path.write_bytes(self.pristine_bytes)

    def test_f4_cp_06_noncanonical_control_file_is_rejected(self) -> None:
        import json

        from quervant_bench.config.codec import canonical_payload_bytes

        payload = canonical_payload_bytes(self.pristine_control)
        variants = (
            json.dumps(self.pristine_control, indent=2).encode() + b"\n",
            payload,
            payload + b"\n\n",
        )
        for index, raw in enumerate(variants):
            with self.subTest(variant=index):
                self.control_path.write_bytes(raw)
                with self.assertRaises(BenchError) as raised:
                    self._admit(control_document=dict(self.pristine_control))
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                self.assertEqual(raised.exception.field_path, "control")
                self.assertEqual(self.control_path.read_bytes(), raw)

    def test_f4_cp_07_malformed_control_file_is_rejected(self) -> None:
        from quervant_bench.config.codec import canonical_payload_bytes

        truncated = canonical_payload_bytes(self.pristine_control)[:40]
        self.control_path.write_bytes(truncated)
        with self.assertRaises(BenchError) as raised:
            self._admit(control_document=dict(self.pristine_control))
        self.assertEqual(raised.exception.code, "BM_SCHEMA_INVALID")

        self.control_path.write_bytes(b'[1,2,3]\n')
        with self.assertRaises(BenchError) as raised:
            self._admit(control_document=dict(self.pristine_control))
        self.assertEqual(raised.exception.code, "BM_SCHEMA_INVALID")

        payload = canonical_payload_bytes(self.pristine_control)
        self.control_path.write_bytes(
            payload.replace(b'"block_count":12', b'"block_count":12,"block_count":12', 1) + b"\n"
        )
        with self.assertRaises(BenchError) as raised:
            self._admit(control_document=dict(self.pristine_control))
        self.assertEqual(raised.exception.code, "BM_DUPLICATE_KEY")

    def test_f4_cp_08_unsafe_control_member_is_rejected(self) -> None:
        import copy
        import os
        import stat
        import tempfile

        initial_inventory = admission.admitted_inventory_digest(self.admissible_record())

        def restore_member() -> None:
            if os.path.lexists(self.control_path):
                self.control_path.unlink()
            self.control_path.write_bytes(self.pristine_bytes)

        def assert_restored() -> None:
            self.assertEqual(self.control_path.read_bytes(), self.pristine_bytes)
            self.assertEqual(
                admission.admitted_inventory_digest(self.admissible_record()),
                initial_inventory,
            )

        with self.subTest(case="leaf_symlink"):
            with tempfile.TemporaryDirectory(dir=self.root) as external:
                target = Path(external) / "control.json"
                target.write_bytes(self.pristine_bytes)
                member_removed = False
                try:
                    self.control_path.unlink()
                    member_removed = True
                    os.symlink(target, self.control_path)
                    self.assertTrue(self.control_path.is_symlink())
                    with self.assertRaises(BenchError) as raised:
                        self._admit(control_document=copy.deepcopy(self.pristine_control))
                    self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")
                    self.assertTrue(self.control_path.is_symlink())
                    self.assertEqual(target.read_bytes(), self.pristine_bytes)
                finally:
                    if member_removed:
                        restore_member()
            assert_restored()

        with self.subTest(case="hardlink"):
            with tempfile.TemporaryDirectory(dir=self.root) as external:
                target = Path(external) / "control.json"
                target.write_bytes(self.pristine_bytes)
                member_removed = False
                try:
                    self.control_path.unlink()
                    member_removed = True
                    os.link(target, self.control_path)
                    self.assertEqual(os.lstat(self.control_path).st_nlink, 2)
                    with self.assertRaises(BenchError) as raised:
                        self._admit(control_document=copy.deepcopy(self.pristine_control))
                    self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")
                    self.assertEqual(target.read_bytes(), self.pristine_bytes)
                    self.assertEqual(self.control_path.read_bytes(), self.pristine_bytes)
                finally:
                    if member_removed:
                        restore_member()
            assert_restored()

        with self.subTest(case="fifo"):
            with tempfile.TemporaryDirectory(dir=self.root):
                member_removed = False
                try:
                    self.control_path.unlink()
                    member_removed = True
                    os.mkfifo(self.control_path)
                    self.assertTrue(stat.S_ISFIFO(os.lstat(self.control_path).st_mode))
                    with self.assertRaises(BenchError) as raised:
                        self._admit(control_document=copy.deepcopy(self.pristine_control))
                    self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")
                    self.assertTrue(stat.S_ISFIFO(os.lstat(self.control_path).st_mode))
                finally:
                    if member_removed:
                        restore_member()
            assert_restored()

        with self.subTest(case="parent_symlink"):
            with tempfile.TemporaryDirectory(dir=self.root) as external:
                external_control = Path(external) / "control"
                external_control.mkdir()
                (external_control / "control.json").write_bytes(self.pristine_bytes)
                saved_dir = Path(external) / "saved-control"
                parent_moved = False
                parent_linked = False
                try:
                    self.control_path.parent.rename(saved_dir)
                    parent_moved = True
                    os.symlink(external_control, self.control_path.parent)
                    parent_linked = True
                    self.assertTrue(self.control_path.parent.is_symlink())
                    with self.assertRaises(BenchError) as raised:
                        self._admit(control_document=copy.deepcopy(self.pristine_control))
                    self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")
                    self.assertTrue(self.control_path.parent.is_symlink())
                    self.assertEqual(
                        (external_control / "control.json").read_bytes(),
                        self.pristine_bytes,
                    )
                finally:
                    if parent_linked:
                        self.control_path.parent.unlink()
                    if parent_moved:
                        saved_dir.rename(self.control_path.parent)
            assert_restored()

    def test_f4_cp_09_reverify_rejects_mutated_capability_control(self) -> None:
        capability = self._admit(control_document=dict(self.pristine_control))
        self.assertEqual(capability.record.control["block_count"], 12)
        capability.record.control["block_count"] = 11
        try:
            with self.assertRaises(BenchError) as raised:
                admission.reverify_official_admission(
                    capability,
                    authorization=self.authorization,
                    template=self.fixture.template,
                    source_root=support.REPO_ROOT,
                    observed=self.observed,
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertEqual(raised.exception.field_path, "control")
            self.assertEqual(self.control_path.read_bytes(), self.pristine_bytes)
        finally:
            capability.record.control["block_count"] = 12
        admission.reverify_official_admission(
            capability,
            authorization=self.authorization,
            template=self.fixture.template,
            source_root=support.REPO_ROOT,
            observed=self.observed,
        )

    def test_f4_cp_10_control_and_disk_mutation_cannot_rebind_capability(self) -> None:
        import copy

        capability = self._admit(control_document=dict(self.pristine_control))
        saved_control = copy.deepcopy(dict(capability.record.control))
        saved_bytes = self.control_path.read_bytes()
        saved_inventory = admission.admitted_inventory_digest(capability.record)
        changed = copy.deepcopy(self.pristine_control)
        changed["block_count"] = 11
        support.write_json(self.control_path, changed)
        capability.record.control["block_count"] = 11
        changed_bytes = self.control_path.read_bytes()
        changed_inventory = admission.admitted_inventory_digest(capability.record)
        try:
            with self.assertRaises(BenchError) as raised:
                admission.reverify_official_admission(
                    capability,
                    authorization=self.authorization,
                    template=self.fixture.template,
                    source_root=support.REPO_ROOT,
                    observed=self.observed,
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertEqual(raised.exception.field_path, "admission")
            self.assertEqual(self.control_path.read_bytes(), changed_bytes)
            self.assertEqual(
                admission.admitted_inventory_digest(capability.record), changed_inventory
            )
        finally:
            capability.record.control.clear()
            capability.record.control.update(saved_control)
            self.control_path.write_bytes(saved_bytes)
        self.assertEqual(
            admission.admitted_inventory_digest(capability.record), saved_inventory
        )
        self.assertEqual(self.control_path.read_bytes(), saved_bytes)

    def test_f4_cp_11_fixture_control_remains_in_memory(self) -> None:
        self.control_path.unlink()
        try:
            fixture_record = support.admit_fixture_cross_engine(self.fixture)
        finally:
            self.control_path.write_bytes(self.pristine_bytes)
        self.assertIs(fixture_record.fixture_only, True)
        self.assertEqual(fixture_record.control["block_count"], 12)

    def test_f4_cp_12_inventory_binding_requires_exact_member(self) -> None:
        records, _total = admission.hash_raw_members(
            self.fixture.raw_root, admission.cross_engine_member_paths(self.fixture.raw_root)
        )
        parsed = admission._read_bound_cross_engine_control(
            self.fixture.raw_root,
            supplied=self.pristine_control,
            inventory=records,
        )
        self.assertEqual(parsed["block_count"], 12)

        relative = "control/control.json"
        member = next(entry for entry in records if entry["path"] == relative)
        missing = [entry for entry in records if entry["path"] != relative]
        duplicate = records + [dict(member)]
        wrong_digest = [dict(entry) for entry in records]
        next(e for e in wrong_digest if e["path"] == relative)["digest"] = "sha256:" + "0" * 64
        wrong_length = [dict(entry) for entry in records]
        next(e for e in wrong_length if e["path"] == relative)["byte_length"] += 1
        for variant in (missing, duplicate, wrong_digest, wrong_length):
            with self.assertRaises(BenchError) as raised:
                admission._read_bound_cross_engine_control(
                    self.fixture.raw_root,
                    supplied=self.pristine_control,
                    inventory=variant,
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertEqual(raised.exception.field_path, "control")

    def test_f4_cp_13_changed_file_cannot_match_stale_inventory(self) -> None:
        import copy

        records, _total = admission.hash_raw_members(
            self.fixture.raw_root, admission.cross_engine_member_paths(self.fixture.raw_root)
        )
        changed = copy.deepcopy(self.pristine_control)
        changed["block_count"] = 11
        support.write_json(self.control_path, changed)
        try:
            with self.assertRaises(BenchError) as raised:
                admission._read_bound_cross_engine_control(
                    self.fixture.raw_root,
                    supplied=changed,
                    inventory=records,
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertEqual(raised.exception.field_path, "control")
            self.assertEqual(support.read_json(self.control_path)["block_count"], 11)
        finally:
            self.control_path.write_bytes(self.pristine_bytes)

    def test_f4_cp_14_post_bind_file_change_is_rejected(self) -> None:
        import copy
        from unittest import mock

        pristine = copy.deepcopy(self.pristine_control)
        original_verify = admission.OriginalVerifier.verify_cross_engine
        changed = copy.deepcopy(pristine)
        changed["block_count"] = 11

        def mutate_after_real_verify(verifier_self, run_root, *, corpus_dir=None):
            outcome = original_verify(verifier_self, run_root, corpus_dir=corpus_dir)
            self.assertEqual(outcome.status, "QUALIFIED")
            support.write_json(self.control_path, changed)
            return outcome

        try:
            with mock.patch.object(
                admission.OriginalVerifier,
                "verify_cross_engine",
                new=mutate_after_real_verify,
            ):
                with self.assertRaises(BenchError) as raised:
                    self._admit(control_document=dict(pristine))
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertEqual(raised.exception.field_path, "raw-series-root")
        finally:
            self.control_path.write_bytes(self.pristine_bytes)

    def test_f4_cp_15_strict_control_bounds_and_input_types_are_preserved(self) -> None:
        for value in (None, []):
            with self.assertRaises(BenchError) as raised:
                self._admit(control_document=value)  # type: ignore[arg-type]
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            self.assertEqual(raised.exception.field_path, "control")

        from quervant_bench.config.codec import MAX_DOCUMENT_BYTES

        cases = (
            (b"\xff\xfe\x00not-utf8\n", "BM_UNSAFE_INPUT"),
            (b"\xef\xbb\xbf{}\n", "BM_UNSAFE_INPUT"),
            (b'{"block_count":NaN}\n', "BM_UNSAFE_INPUT"),
            (b"{" + b" " * (MAX_DOCUMENT_BYTES + 1) + b"}\n", "BM_UNSAFE_INPUT"),
        )
        for raw, expected in cases:
            with self.subTest(expected=expected):
                self.control_path.write_bytes(raw)
                with self.assertRaises(BenchError) as raised:
                    self._admit(control_document=dict(self.pristine_control))
                self.assertEqual(raised.exception.code, expected)
                self.assertEqual(self.control_path.read_bytes(), raw)


class CurrentBaselineProductionAdmissionTests(unittest.TestCase):
    """Generated test data through the actual G0/Gate A/Gate C factories.

    Approval records and raw samples here are synthetic test evidence. The real
    original verifier executes; no engine, service, build or measurement runs.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.cases = {}
        retained_namespace = support.REPO_ROOT / "target/pr15i-d3-c"
        retained_namespace.mkdir(parents=True, exist_ok=True)
        cls.retained_temporary = tempfile.TemporaryDirectory(prefix="test-current-baseline-", dir=retained_namespace)
        cls.addClassCleanup(cls.retained_temporary.cleanup)
        for family, factory in (("cross", support.make_cross_engine_fixture),
                                ("retained", support.make_retained_key_fixture)):
            fixture_root = cls.root / family / "fixture" if family == "cross" else Path(cls.retained_temporary.name) / "fixture"
            fixture = factory(fixture_root)
            if family == "retained":
                cls._complete_retained_fixture(fixture)
            template = protocols.read_canonical_json(protocols.template_path(fixture.freeze.study_id, version=2))
            freeze = dataclasses.replace(
                fixture.freeze, design_digest=content_digest(template), profile_version=2,
                acceptance_profile="current-baseline-v2",
                baseline_id="22222222-2222-4222-8222-222222222222",
                preservation_root_identity=str(cls.root / "benchmark-results/baselines/22222222-2222-4222-8222-222222222222"),
                runtime_freeze_digest=support.DIGEST_A if family == "retained" else None,
                policy_digest=analysis.policy_profile_digest(template["study_id"], template["policy"]["policy_chain"]),
            )
            capability, observed = cls._authorize(freeze, cls.root / family / "g0-v2")
            first, observed_first = cls._authorize(fixture.freeze, cls.root / family / "g0-v1")
            cls.cases[family] = fixture, template, capability, observed, first, observed_first

    @staticmethod
    def _complete_retained_fixture(fixture):
        """Supply complete generated host/provenance records to the real verifier.

        The normal small fixture intentionally uses a stub verifier. This owned
        test tree satisfies the unchanged verifier's namespace and file contract;
        the records are synthetic inputs, not observed host/build evidence.
        """

        original = admission._load_module("test_only_current_baseline_verifier", "benchmarks/pr15i_d3_c/verify.py")
        protocol = support.read_json(support.REPO_ROOT / "benchmarks/pr15i_d3_c/protocol_v3r3.json")
        for campaign in (admission.D3C_CONTROL_NAME, *admission.D3C_CAMPAIGN_NAMES):
            directory = fixture.raw_root / campaign
            manifest = support.read_json(directory / "manifest.json")
            host = {
                "schema": "pr15i-d3c-host-attestation-v1", "protocol_sha256": original.PROTOCOL_SHA256,
                "host_fingerprint": "a" * 64, "adapter_cpu": 1, "controller_cpu": 2,
                "cpu_topology": {
                    "adapter": {"cpu": 1, "package_id": 0, "core_id": 1, "thread_siblings": "1"},
                    "controller": {"cpu": 2, "package_id": 0, "core_id": 2, "thread_siblings": "2"},
                },
                "filesystems": [{"role": role, "harness_fstype": "ext4", "findmnt_fstype": "ext4"}
                                for role in ("repository", "campaign_output", "compile_source", "build_A", "build_B", "corpus", "indexes")],
            }
            readiness = {
                "schema": "pr15i-d3c-host-readiness-v1", "protocol_sha256": original.PROTOCOL_SHA256,
                "campaign": campaign, "role_cpus": {"adapter": 1, "controller": 2}, "host_fingerprint": host["host_fingerprint"],
                "settle_monotonic_start_ns": 0, "settle_monotonic_end_ns": 5_000_000_000,
                "observations": [{"monotonic_ns": (6 + i) * 1_000_000_000,
                                  "cpus": {str(cpu): [0, 0, 0, 100 * (i + 1), 0, 0, 0, 0] for cpu in (1, 2)}} for i in range(7)],
                "interval_metrics": {role: [{"interval": i, "actual_ms": 1000, "busy_permille": 0, "steal_permille": 0} for i in range(1, 7)] for role in ("adapter", "controller")},
                "lower_median_busy_permille": {"adapter": 0, "controller": 0}, "readiness_status": "READY",
                "failure_codes": [], "optional_cpu_frequency_khz": {"adapter": None, "controller": None}, "queries_executed": 0,
            }
            source = str(directory / "compile-source")
            events = [{"arm": arm, "source_sha": record["source_sha"], "binary_sha256": record["binary_sha256"],
                       "binary_bytes": record["binary_bytes"], "canonical_source": source,
                       "feature": arm in ("L", "P", "H"),
                       "argv": ["cargo", "build"] + (["--features", "test-only-mode"] if arm in ("L", "P", "H") else [])}
                      for arm, record in manifest["arms"].items()]
            support.write_json(directory / "raw/host-attestation.json", host)
            support.write_json(directory / "raw/host-readiness.json", readiness)
            support.write_json(directory / "raw/build-provenance.json", {
                "schema": "pr15i-d3c-build-provenance-v1", "canonical_source_path": source, "events": events})
            manifest.update(host_fingerprint=host["host_fingerprint"], prefilter_profile=protocol["prefilter_profile"])
            for field, relative in (("host_attestation_sha256", "raw/host-attestation.json"),
                                    ("host_readiness_sha256", "raw/host-readiness.json"),
                                    ("build_provenance_sha256", "raw/build-provenance.json")):
                manifest[field] = admission.sha256_regular_file(directory, relative, max_bytes=admission.MAX_RAW_MEMBER_BYTES)[0].removeprefix("sha256:")
            support.write_json(directory / "manifest.json", manifest)
            slots = [support.read_json(path) for path in sorted((directory / "raw/slots").glob("slot-*.json"))]
            lanes = original.lanes(protocol)
            values = original.block_values(slots, lanes, protocol["blocks"])
            summary = (original.summary_control(protocol, values, lanes, protocol["blocks"], slots)
                       if manifest["kind"] == "control"
                       else original.summary_campaign(protocol, values, lanes, protocol["blocks"], campaign, slots, True))
            support.write_json(directory / "sanitized/summary.json", summary)
            sealed = {name: admission.sha256_regular_file(directory, name, max_bytes=admission.MAX_RAW_MEMBER_BYTES)[0].removeprefix("sha256:")
                      for name in admission.walk_raw_members(directory)
                      if name not in ("raw/seal.json", "verification.json")}
            support.write_json(directory / "raw/seal.json", {"files": sealed})

    @staticmethod
    def _authorize(freeze, root):
        document = support.authorization_document(freeze)
        if freeze.profile_version == 2:
            document.update(schema_version=2, acceptance_profile=freeze.acceptance_profile,
                            baseline_id=freeze.baseline_id,
                            preservation_root_identity=freeze.preservation_root_identity,
                            runtime_freeze_digest=freeze.runtime_freeze_digest)
        observed = {name: document[name] for name in protocols.OBSERVED_IDENTITY_FIELDS}
        observed["output_root_identity"] = freeze.approved_output_root_identity
        if freeze.profile_version == 2:
            observed.update({name: document[name] for name in (
                "acceptance_profile", "baseline_id", "preservation_root_identity", "runtime_freeze_digest")})
        candidate = root / "candidate" / "authorization.json"
        candidate.parent.mkdir(parents=True)
        candidate.write_bytes(canonical_document_bytes(document))
        approval_root = root / "independent-record"
        approval_root.mkdir()
        approval = {
            "kind": "official-g0-approval-record", "schema_version": 1,
            "study_id": freeze.study_id, "approved_authorization_digest": content_digest(document),
            "independent_review_id": "test-only-v2-review", "approved_at_utc": "2026-11-19T12:00:00Z",
        }
        (approval_root / "test-only-v2.approval.json").write_bytes(canonical_document_bytes(approval))
        capability = authorization.open_verified_official_authorization(
            authorization_path=candidate, independently_approved_digest=content_digest(document),
            actual_observations=observed, approval_source_identity="test-only-v2",
            approval_source_root=approval_root,
        )
        return capability, observed

    def _admit(self, family, *, template=None, capability=None, observed=None):
        fixture, selected, second, second_observed, _first, _first_observed = self.cases[family]
        kwargs = {
            "raw_root": fixture.raw_root, "authorization": second if capability is None else capability,
            "template": selected if template is None else template,
            "source_root": support.REPO_ROOT,
            "observed": second_observed if observed is None else observed,
        }
        if family == "cross":
            return admission.admit_cross_engine_real(
                **kwargs, corpus_dir=fixture.corpus_root, control_document=fixture.control)
        return admission.admit_retained_key_real(**kwargs)

    def _assert_production_positive(self, family):
        _fixture, template, capability, observed, _first, _first_observed = self.cases[family]
        self.assertIs(capability.fixture_only, False)
        self.assertEqual(capability.freeze.profile_version, 2)
        admitted = self._admit(family)
        self.assertIs(type(admitted), admission.VerifiedOfficialAdmission)
        self.assertIs(admitted.record.fixture_only, False)
        derived, policy = analysis.analyze_official_study(admitted=admitted.record, template=template)
        assessment = verification.verify_official_study(
            admitted=admitted.record, admission=admitted, template=template, authorization=capability,
            analysis=derived, policy=policy, source_root=support.REPO_ROOT, observed=observed,
        )
        self.assertEqual(assessment["schema_version"], 2)
        self.assertEqual(assessment["status"], "VERIFIED_CURRENT_BASELINE")
        self.assertEqual(assessment["verification_scope"], "current-baseline-v2")
        self.assertEqual(assessment["policy_verification_status"], "NOT_EVALUATED" if family == "retained" else "PASS")
        self.assertEqual(len(assessment["check_ids"]), 9 if family == "retained" else 10)

    def test_v09_cross_production_factories_verify_generated_raw_without_timing(self):
        self._assert_production_positive("cross")

    def test_v09_retained_production_factories_verify_generated_raw_without_policy_or_timing(self):
        self._assert_production_positive("retained")

    def test_v01_mixed_profile_rejects_before_source_verifier_or_raw_access(self):
        for family, case in self.cases.items():
            fixture, second_template, second, second_observed, first, first_observed = case
            for template, capability, observed in (
                (fixture.template, second, second_observed),
                (second_template, first, first_observed),
            ):
                with self.subTest(family=family, template=template["schema_version"], g0=capability.freeze.profile_version):
                    with patch.object(admission, "verify_authorized_source", side_effect=AssertionError("source read reached")), \
                         patch.object(admission, "OriginalVerifier", side_effect=AssertionError("verifier reached")), \
                         patch.object(admission, "require_safe_root", side_effect=AssertionError("raw read reached")):
                        with self.assertRaises(BenchError) as raised:
                            self._admit(family, template=template, capability=capability, observed=observed)
                    self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_IDENTITY_INVALID, "schema_version"))

    def test_v03_same_profile_wrong_design_rejects_before_source_access(self):
        for family, case in self.cases.items():
            _fixture, _template, capability, _observed, _first, _first_observed = case
            wrong_freeze = dataclasses.replace(capability.freeze, design_digest="sha256:" + "f" * 64)
            wrong, observed = self._authorize(wrong_freeze, self.root / family / "g0-wrong-design")
            with self.subTest(family=family), patch.object(admission, "verify_authorized_source", side_effect=AssertionError("source read reached")):
                with self.assertRaises(BenchError) as raised:
                    self._admit(family, capability=wrong, observed=observed)
            self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_IDENTITY_INVALID, "design_digest"))

    def test_v01_private_data_cores_use_the_same_profile_guard(self):
        for family, case in self.cases.items():
            fixture, _template, capability, _observed, _first, _first_observed = case
            kwargs = {"raw_root": fixture.raw_root, "freeze": capability.freeze,
                      "template": fixture.template, "source_root": None,
                      "original_verifier": support.StubVerifier(), "for_production": False}
            with self.subTest(family=family), patch.object(admission, "require_safe_root", side_effect=AssertionError("raw read reached")):
                with self.assertRaises(BenchError) as raised:
                    if family == "cross":
                        admission._admit_cross_engine_core(**kwargs, corpus_dir=fixture.corpus_root, control_document=fixture.control)
                    else:
                        admission._admit_retained_key_core(**kwargs)
            self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_IDENTITY_INVALID, "schema_version"))
