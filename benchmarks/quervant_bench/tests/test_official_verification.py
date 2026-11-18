"""O09-VER: independent Gate C recomputation and forged-input rejection."""

from __future__ import annotations

import copy
import inspect
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.codec import content_digest
from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.official import admission, analysis, verification
from quervant_bench.official.contracts import validate_official_analysis
from quervant_bench.tests import official_support as support


class ReferencePrimitiveTests(unittest.TestCase):
    def test_o09_ver_01_reference_median_and_percentiles_are_recomputed(self) -> None:
        values = [index for index in range(1, 21)]
        self.assertEqual(verification.ref_lower_median(values), 10)
        self.assertEqual(verification.ref_percentile(values, 95), 19)
        self.assertEqual(verification.ref_percentile(values, 99), 20)
        self.assertEqual(verification.ref_percentile(values, 50), 10)

    def test_o09_ver_02_reference_decimal_is_six_places(self) -> None:
        from fractions import Fraction

        self.assertEqual(verification.ref_decimal(Fraction(1, 3)), "0.333333")
        self.assertEqual(verification.ref_decimal(Fraction(3, 2)), "1.500000")

    def test_o09_ver_03_reference_does_not_import_the_primary_analysis(self) -> None:
        source = inspect.getsource(verification)
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        joined = "\n".join(import_lines)
        self.assertNotIn("from .analysis", joined)
        self.assertNotIn("official.analysis import", joined)
        self.assertNotIn("import analysis", joined)

    def test_o09_ver_04_reference_control_rule_boundaries(self) -> None:
        from fractions import Fraction

        self.assertTrue(
            verification.ref_control_lane_pass([Fraction(1, 1)] * 12, exempt=False)
        )
        self.assertFalse(
            verification.ref_control_lane_pass(
                [Fraction(1, 1)] * 11 + [Fraction(3, 2)], exempt=False
            )
        )

    def test_o09_ver_05_reference_answer_sets_match_the_two_independent_forms(self) -> None:
        from quervant_bench.official.admission import retained_key_oracle

        for n in (10_000, 100_000):
            for class_name in ("absent", "rare", "medium", "common"):
                for k in (1, 64, 1024):
                    self.assertEqual(
                        verification.ref_retained_key_answer(n, class_name, k),
                        retained_key_oracle(n, class_name, k),
                    )

    def test_o09_ver_06_reference_cross_engine_answers_are_ordered(self) -> None:
        answers = verification.ref_cross_engine_answers(10_000)
        for _key, value in answers.items():
            self.assertEqual(value["doc_ids"], sorted(value["doc_ids"]))
            self.assertLessEqual(len(value["doc_ids"]), value["total_hits"])


class CrossEngineVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.fixture = support.make_cross_engine_fixture(cls.root)
        cls.admitted = support.admit_fixture_cross_engine(cls.fixture)
        cls.analysis, cls.policy = analysis.analyze_official_study(
            admitted=cls.admitted, template=cls.fixture.template
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _verify(self, analysis_document=None, policy_document=None):
        return verification.verify_official_study(
            admitted=self.admitted,
            template=self.fixture.template,
            authorization=support.fixture_authorization(
                "retained-key-topk-real-v1", freeze=self.fixture.freeze
            ),
            analysis=analysis_document or self.analysis,
            policy=policy_document or self.policy,
        )

    def test_o09_ver_07_valid_cross_engine_series_is_verified(self) -> None:
        assessment = self._verify()
        self.assertEqual(assessment["status"], "VERIFIED_REAL")
        self.assertEqual(assessment["check_ids"], list(verification.VERIFIER_CHECK_IDS))

    def test_o09_ver_08_forged_ratio_is_rejected_even_when_rehashed(self) -> None:
        forged = copy.deepcopy(self.analysis)
        forged["statistics"]["lanes"][0]["comparisons"][0]["ratio"] = "0.500000"
        forged = validate_official_analysis(forged)
        with self.assertRaises(BenchError) as raised:
            self._verify(analysis_document=forged)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ver_09_forged_median_is_rejected(self) -> None:
        forged = copy.deepcopy(self.analysis)
        forged["statistics"]["lanes"][3]["per_engine"]["quervant"]["median_ns"] += 7
        forged = validate_official_analysis(forged)
        with self.assertRaises(BenchError) as raised:
            self._verify(analysis_document=forged)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ver_10_forged_dispersion_is_rejected(self) -> None:
        forged = copy.deepcopy(self.analysis)
        forged["statistics"]["lanes"][2]["per_engine"]["lucene"]["dispersion"] = "9.000000"
        forged = validate_official_analysis(forged)
        with self.assertRaises(BenchError):
            self._verify(analysis_document=forged)

    def test_o09_ver_11_policy_status_forgery_is_rejected(self) -> None:
        from quervant_bench.official.contracts import validate_official_policy

        forged = copy.deepcopy(self.policy)
        forged["decision_status"] = "SELECTED_ELIGIBLE_REAL"
        forged["selected_arm_id"] = "quervant"
        forged["candidate_statuses"] = {"quervant": "ELIGIBLE"}
        forged["performance_claim_allowed"] = True
        forged = validate_official_policy(forged)
        with self.assertRaises(BenchError) as raised:
            self._verify(policy_document=forged)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ver_12_raw_sample_mutation_after_analysis_is_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "trials" / "trial-1" / "quervant.json"
        original = path.read_bytes()
        document = support.read_json(path)
        document["lanes"][0]["samples_ns"][0] += 1
        document["lanes"][0]["summary_ns"]["min"] += 1
        support.write_json(path, document)
        try:
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            path.write_bytes(original)

    def test_o09_ver_13_identity_anchor_mismatch_is_rejected(self) -> None:
        freeze = support.make_freeze(
            study_id="cross-engine-keyword-real-v1",
            corpus_manifest_digest=self.fixture.freeze.corpus_manifest_digest,
            original_verifier_digest=self.fixture.freeze.original_reference_verifier_digest,
            design_digest="sha256:" + "8" * 64,
        )
        with self.assertRaises(BenchError):
            verification.verify_official_study(
                admitted=self.admitted,
                template=self.fixture.template,
                authorization=support.fixture_authorization(
                    "cross-engine-keyword-real-v1", freeze=freeze
                ),
                analysis=self.analysis,
                policy=self.policy,
            )

    def test_o09_ver_14_control_digest_binding_is_checked(self) -> None:
        forged = copy.deepcopy(self.analysis)
        forged["control_result_digest"] = content_digest({"forged": True})
        forged = validate_official_analysis(forged)
        with self.assertRaises(BenchError) as raised:
            self._verify(analysis_document=forged)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


class RetainedKeyVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.fixture = support.make_retained_key_fixture(cls.root)
        cls.admitted = support.admit_fixture_retained_key(cls.fixture)
        cls.analysis, cls.policy = analysis.analyze_official_study(
            admitted=cls.admitted, template=cls.fixture.template
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _verify(self, analysis_document=None, policy_document=None):
        return verification.verify_official_study(
            admitted=self.admitted,
            template=self.fixture.template,
            authorization=support.fixture_authorization(
                "retained-key-topk-real-v1", freeze=self.fixture.freeze
            ),
            analysis=analysis_document or self.analysis,
            policy=policy_document or self.policy,
        )

    def test_o09_ver_15_underivable_policy_yields_a_typed_block(self) -> None:
        assessment = self._verify()
        self.assertEqual(assessment["status"], "BLOCKED")
        self.assertNotIn("RV-08-POLICY", assessment["check_ids"])
        self.assertNotIn("policy-decision", assessment["verified_claims"])

    def test_o09_ver_16_forged_block_median_is_rejected(self) -> None:
        forged = copy.deepcopy(self.analysis)
        forged["statistics"]["lanes"][0]["arms"]["base"]["block_medians_ns"][0] = 1
        forged = validate_official_analysis(forged)
        with self.assertRaises(BenchError):
            self._verify(analysis_document=forged)

    def test_o09_ver_17_forged_retained_block_is_rejected(self) -> None:
        forged = copy.deepcopy(self.analysis)
        lane = forged["statistics"]["lanes"][0]["arms"]["base"]
        removed = lane["retained_block_indices"].pop()
        lane["excluded_block_indices"] = sorted(
            lane["excluded_block_indices"] + [removed]
        )
        forged = validate_official_analysis(forged)
        with self.assertRaises(BenchError):
            self._verify(analysis_document=forged)

    def test_o09_ver_18_forged_lane_answer_is_rejected(self) -> None:
        path = self.fixture.raw_root / admission.D3C_CAMPAIGN_NAMES[0] / "raw" / "slots" / "slot-01.json"
        original = path.read_bytes()
        document = support.read_json(path)
        document["lanes"][9]["doc_ids"] = []
        support.write_json(path, document)
        try:
            with self.assertRaises(BenchError):
                self._verify()
        finally:
            path.write_bytes(original)


class BlockedAssessmentTests(unittest.TestCase):
    def test_o09_ver_18b_blocked_helper_raises_typed_error(self) -> None:
        with self.assertRaises(BenchError) as raised:
            verification.blocked_assessment(
                subject={},
                study_id="cross-engine-keyword-real-v1",
                raw_series_root_digest="sha256:" + "a" * 64,
                reason_field="policy",
            )
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()


class StandaloneGateCProvenanceTests(unittest.TestCase):
    """RF09-11 / F3-GC: Gate C must consume freshly re-admitted evidence."""

    @classmethod
    def setUpClass(cls) -> None:
        from quervant_bench.official import analysis as official_analysis

        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.fixture = support.make_cross_engine_fixture(cls.root / "fixture")
        cls.capability, cls.authorization = support.admit_production_shaped_cross_engine(
            cls.fixture, sandbox=cls.root / "sandbox"
        )
        cls.record = cls.capability.record
        cls.observed = support.authorization_observations(cls.fixture.freeze)
        cls.analysis, cls.policy = official_analysis.analyze_official_study(
            admitted=cls.record, template=cls.fixture.template
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _verify(
        self,
        *,
        candidate=None,
        analysis_document=None,
        policy_document=None,
        admission_capability="default",
        authorization="default",
        source_root="default",
    ):
        return verification.verify_official_study(
            admitted=self.record if candidate is None else candidate,
            template=self.fixture.template,
            authorization=self.authorization if authorization == "default" else authorization,
            analysis=self.analysis if analysis_document is None else analysis_document,
            policy=self.policy if policy_document is None else policy_document,
            source_root=(
                support.REPO_ROOT if source_root == "default" else source_root
            ),
            observed=self.observed,
            admission=(
                self.capability
                if admission_capability == "default"
                else admission_capability
            ),
        )

    def _mutated_lane_candidate(self):
        import copy

        from quervant_bench.official import analysis as official_analysis

        candidate = copy.deepcopy(self.record)
        matches = [
            lane
            for lane in candidate.trials[(1, "quervant")]["lanes"]
            if (lane["n"], lane["class"], lane["k"], lane["regime"])
            == (10_000, "rare", 10, "warm")
        ]
        self.assertEqual(len(matches), 1)
        lane = matches[0]
        lane["samples_ns"] = [value + 100_000 for value in lane["samples_ns"]]
        lane["summary_ns"] = support.summary(lane["samples_ns"])
        candidate_analysis, candidate_policy = official_analysis.analyze_official_study(
            admitted=candidate, template=self.fixture.template
        )
        return candidate, candidate_analysis, candidate_policy

    def test_f3_gc_01_authentic_record_is_verified(self) -> None:
        assessment = self._verify()
        self.assertEqual(assessment["status"], "VERIFIED_REAL")
        self.assertEqual(assessment["check_ids"], list(verification.VERIFIER_CHECK_IDS))
        self.assertFalse((self.root / "output").exists())

    def test_f3_gc_02_in_memory_tampered_record_is_rejected(self) -> None:
        candidate, candidate_analysis, candidate_policy = self._mutated_lane_candidate()
        self.assertNotEqual(candidate_analysis, self.analysis)
        # The on-disk evidence is untouched, so the raw digest still matches.
        from quervant_bench.official import admission as official_admission

        self.assertEqual(
            official_admission.admitted_inventory_digest(candidate),
            self.record.raw_series_root_digest,
        )
        with self.assertRaises(BenchError) as raised:
            self._verify(
                candidate=candidate,
                analysis_document=candidate_analysis,
                policy_document=candidate_policy,
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "admission")

    def test_f3_gc_03_non_statistical_field_change_is_rejected(self) -> None:
        import copy

        candidate = copy.deepcopy(self.record)
        candidate.run_json["run_id"] = "tampered-run-id"
        with self.assertRaises(BenchError) as raised:
            self._verify(candidate=candidate)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "admission")

    def test_f3_gc_04_control_metadata_change_is_rejected(self) -> None:
        import copy

        candidate = copy.deepcopy(self.record)
        self.assertEqual(candidate.control["block_count"], 12)
        candidate.control["block_count"] = 11
        with self.assertRaises(BenchError) as raised:
            self._verify(candidate=candidate)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "admission")

    def test_f3_gc_05_missing_capability_is_rejected(self) -> None:
        for value in (None, self.record):
            with self.assertRaises(BenchError) as raised:
                self._verify(admission_capability=value)
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            self.assertEqual(raised.exception.field_path, "admission")

    def test_f3_gc_06_retained_key_equality_helper_rejects_slot_change(self) -> None:
        import copy

        from quervant_bench.official import admission as official_admission

        fixture = support.make_retained_key_fixture(self.root / "retained-fixture")
        fresh = support.admit_fixture_retained_key(fixture)
        candidate = copy.deepcopy(fresh)
        candidate.slots[official_admission.D3C_CONTROL_NAME][0]["lanes"][0]["samples_ns"][0] += 1
        with self.assertRaises(BenchError) as raised:
            verification._require_exact_admitted_record(candidate, fresh)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "admission")
        verification._require_exact_admitted_record(copy.deepcopy(fresh), fresh)

    def test_f3_gc_07_equality_helper_rejects_campaign_change_and_cross_family(self) -> None:
        import copy

        from quervant_bench.official import admission as official_admission

        fixture = support.make_retained_key_fixture(self.root / "retained-fixture-2")
        fresh = support.admit_fixture_retained_key(fixture)
        candidate = copy.deepcopy(fresh)
        self.assertEqual(
            candidate.campaigns[official_admission.D3C_CONTROL_NAME]["manifest"][
                "host_fingerprint"
            ],
            "fixture-d3c-host",
        )
        candidate.campaigns[official_admission.D3C_CONTROL_NAME]["manifest"][
            "host_fingerprint"
        ] = "tampered-fixture-host"
        with self.assertRaises(BenchError) as raised:
            verification._require_exact_admitted_record(candidate, fresh)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        with self.assertRaises(BenchError):
            verification._require_exact_admitted_record(self.record, fresh)
        verification._require_exact_admitted_record(copy.deepcopy(self.record), self.record)

    def test_f3_gc_08_production_record_cannot_be_relabelled_fixture(self) -> None:
        import dataclasses

        candidate = dataclasses.replace(self.record, fixture_only=True)
        with self.assertRaises(BenchError) as raised:
            self._verify(candidate=candidate)
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
        self.assertEqual(raised.exception.field_path, "admission")

    def test_f3_gc_09_fixture_authorization_cannot_cover_production_record(self) -> None:
        with self.assertRaises(BenchError) as raised:
            self._verify(
                authorization=support.fixture_authorization(
                    "cross-engine-keyword-real-v1", freeze=self.fixture.freeze
                )
            )
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
        self.assertEqual(raised.exception.field_path, "admission")

    def test_f3_gc_11_missing_source_root_is_typed_unavailable(self) -> None:
        with self.assertRaises(BenchError) as raised:
            self._verify(source_root=None)
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def test_f3_gc_12_raw_file_mutation_is_still_rejected(self) -> None:
        path = self.fixture.raw_root / "backend" / "trials" / "trial-1" / "quervant.json"
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document["lanes"][0]["samples_ns"][0] += 1
            support.write_json(path, document)
            with self.assertRaises(BenchError):
                self._verify()
        finally:
            path.write_bytes(original)
