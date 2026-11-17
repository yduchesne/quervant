"""O09-ADM / O09-ACQ: Gate A raw-evidence admission and archive security."""

from __future__ import annotations

import copy
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.evidence.archives import ArchiveLimits, inspect_tar_gz
from quervant_bench.official import admission, historical
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
            "freeze": self.fixture.freeze,
            "template": self.fixture.template,
            "corpus_dir": self.fixture.corpus_root,
            "control_document": self.fixture.control,
            "original_verifier": support.StubVerifier(),
        }
        arguments.update(overrides)
        return admission.admit_cross_engine_real(**arguments)

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
        with self.assertRaises(BenchError) as raised:
            self._admit(freeze=freeze)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_adm_15b_cross_engine_verifier_anchor_mismatch_is_rejected(self) -> None:
        freeze = support.make_freeze(
            study_id="cross-engine-keyword-real-v1",
            corpus_manifest_digest=self.fixture.freeze.corpus_manifest_digest,
            original_verifier_digest="sha256:" + "6" * 64,
        )
        with self.assertRaises(BenchError) as raised:
            self._admit(freeze=freeze)
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
            "freeze": self.fixture.freeze,
            "template": self.fixture.template,
            "original_verifier": support.StubVerifier(),
        }
        arguments.update(overrides)
        return admission.admit_retained_key_real(**arguments)

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
