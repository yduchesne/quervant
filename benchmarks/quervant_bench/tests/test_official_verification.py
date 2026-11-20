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


class CurrentBaselineVerificationTests(unittest.TestCase):
    """V2 arithmetic/verification using declared fixture evidence, never live authority."""

    @classmethod
    def setUpClass(cls) -> None:
        import dataclasses
        import json
        from quervant_bench.official import protocols

        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.cases = {}
        for family, factory, admit in (
            ("cross", support.make_cross_engine_fixture, support.admit_fixture_cross_engine),
            ("retained", support.make_retained_key_fixture, support.admit_fixture_retained_key),
        ):
            original = factory(cls.root / family)
            template = json.loads(protocols.template_path(original.freeze.study_id, support.REPO_ROOT, version=2).read_text())
            freeze = dataclasses.replace(
                original.freeze, design_digest=content_digest(template), profile_version=2,
                acceptance_profile="current-baseline-v2",
                baseline_id="44444444-4444-4444-8444-444444444444",
                preservation_root_identity=str(cls.root / "benchmark-results/baselines/44444444-4444-4444-8444-444444444444"),
                runtime_freeze_digest=support.DIGEST_A if family == "retained" else None,
                approved_output_root_identity=str(cls.root / "output"),
                policy_digest=analysis.policy_profile_digest(template["study_id"], template["policy"]["policy_chain"]),
            )
            fixture = dataclasses.replace(original, template=template, freeze=freeze)
            record = admit(fixture)
            derived, policy = analysis.analyze_official_study(admitted=record, template=template)
            cls.cases[family] = (fixture, record, derived, policy)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _baseline_verify(self, family, *, analysis_document=None, policy_document=None, policy_inputs=None):
        fixture, record, derived, policy = self.cases[family]
        return verification.verify_official_study(
            admitted=record, template=fixture.template,
            authorization=support.fixture_authorization(freeze=fixture.freeze),
            analysis=derived if analysis_document is None else analysis_document,
            policy=policy if policy_document is None else policy_document,
            policy_inputs=policy_inputs,
        )

    def test_cb_v09_null_policy_is_positive_narrow_retained_verification(self) -> None:
        fixture, record, derived, policy = self.cases["retained"]
        self.assertEqual(derived["schema_version"], 2)
        self.assertEqual(policy["schema_version"], 1)
        self.assertEqual(policy["decision_status"], "POLICY_NOT_DERIVABLE")
        self.assertIsNone(policy["selected_arm_id"])
        self.assertIs(policy["performance_claim_allowed"], False)
        self.assertEqual(policy["reasons"], ["authentic-policy-inputs-unavailable", "no-fallback-arm-selection", "policy-chain-not-rerun"])
        assessment = self._baseline_verify("retained")
        self.assertEqual(assessment["status"], "VERIFIED_CURRENT_BASELINE")
        self.assertEqual(assessment["verification_scope"], "current-baseline-v2")
        self.assertEqual(assessment["policy_verification_status"], "NOT_EVALUATED")
        self.assertEqual(assessment["not_evaluated_checks"], ["RV-08-POLICY"])
        self.assertEqual(assessment["check_ids"], [
            "RV-01-SCOPE", "RV-02-G0", "RV-03-RAW-INVENTORY", "RV-04-ORACLE",
            "RV-05-SCHEDULE", "RV-06-HOST-CONTROLS", "RV-07-STATISTICS",
            "RV-09-IDENTITY", "RV-10-POST-READ-INTEGRITY",
        ])
        self.assertNotIn("policy-decision", assessment["verified_claims"])
        self.assertEqual(assessment["analysis_digest"], content_digest(derived))
        self.assertEqual(assessment["policy_digest"], content_digest(policy))

    def test_cb_v09_cross_engine_keeps_all_checks_and_schema_one_analysis(self) -> None:
        _fixture, _record, derived, policy = self.cases["cross"]
        self.assertEqual(derived["schema_version"], 1)
        self.assertNotIn("retained_slot_statistics", derived)
        self.assertEqual(policy["decision_status"], "INCONCLUSIVE")
        assessment = self._baseline_verify("cross")
        self.assertEqual(assessment["status"], "VERIFIED_CURRENT_BASELINE")
        self.assertEqual(assessment["policy_verification_status"], "PASS")
        self.assertEqual(assessment["not_evaluated_checks"], [])
        self.assertEqual(assessment["check_ids"], list(verification.VERIFIER_CHECK_IDS))
        self.assertIn("policy-decision", assessment["verified_claims"])

    def test_cb_v09_paired_payload_has_complete_independent_grid_and_six_pairs(self) -> None:
        from quervant_bench.config.codec import canonical_payload_bytes
        from quervant_bench.official.policy_reference import reference_slot_statistics

        _fixture, record, derived, _policy = self.cases["retained"]
        payload = derived["retained_slot_statistics"]
        self.assertEqual(set(payload), {"method_id", "lanes"})
        self.assertEqual(payload["method_id"], "retained-key-paired-slot-effects-v1")
        lanes = payload["lanes"]
        self.assertEqual(set(lanes), {
            f"pr15d_v1/{n}/{name}/k{k}"
            for n in (10000, 100000) for name in ("absent", "rare", "medium", "common")
            for k in (1, 10, 32, 64, 100, 128, 256, 512, 1024)
        })
        pairs = (("L", "A"), ("P", "A"), ("H", "A"), ("P", "L"), ("H", "L"), ("H", "P"))
        count = 0
        for lane_id, lane in lanes.items():
            self.assertEqual(lane["id"], lane_id)
            self.assertEqual(set(lane["campaigns"]), {"d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02"})
            for campaign in lane["campaigns"].values():
                self.assertEqual(set(campaign), {
                    "retained", "retained_count", "latency", "raw_latency", "filter_sensitive",
                    "R_L_A", "CI_L_A", "R_P_A", "CI_P_A", "R_H_A", "CI_H_A",
                    "R_P_L", "CI_P_L", "R_H_L", "CI_H_L", "R_H_P", "CI_H_P",
                })
                for numerator, denominator in pairs:
                    self.assertEqual(campaign[f"R_{numerator}_{denominator}"], campaign["latency"][numerator] / campaign["latency"][denominator])
                    self.assertEqual(set(campaign[f"CI_{numerator}_{denominator}"]), {"low", "high", "seed"})
                    count += 1
        self.assertEqual(count, 864)
        expected, internal = reference_slot_statistics(record)
        self.assertEqual(canonical_payload_bytes(lanes), canonical_payload_bytes(expected))
        self.assertEqual(len(internal), 144)
        self.assertNotIn("authenticated_slots", derived)

    def test_cb_v09_each_paired_statistic_is_checked_independently(self) -> None:
        fixture, _record, original, original_policy = self.cases["retained"]
        mutations = [
            (name, lambda record, name=name: record.__setitem__(name, record[name] * 1.01))
            for name in ("R_L_A", "R_P_A", "R_H_A", "R_P_L", "R_H_L", "R_H_P")
        ] + [
            (name, lambda record, name=name: record[name].__setitem__("seed", record[name]["seed"] ^ 1))
            for name in ("CI_L_A", "CI_P_A", "CI_H_A", "CI_P_L", "CI_H_L", "CI_H_P")
        ] + [
            ("filtered", lambda record: record["latency"].__setitem__("A", record["latency"]["A"] + 1)),
            ("unfiltered", lambda record: record["raw_latency"].__setitem__("H", record["raw_latency"]["H"] + 1)),
            ("sensitivity", lambda record: record.__setitem__("filter_sensitive", not record["filter_sensitive"])),
            ("retained", lambda record: (record["retained"].pop(), record.__setitem__("retained_count", record["retained_count"] - 1))),
        ]
        for label, mutate in mutations:
            with self.subTest(field=label):
                forged = copy.deepcopy(original)
                record = forged["retained_slot_statistics"]["lanes"]["pr15d_v1/10000/rare/k10"]["campaigns"]["d3c-v3r3-strategies-01"]
                mutate(record)
                forged = validate_official_analysis(forged)
                policy = dict(original_policy, analysis_digest=content_digest(forged))
                with self.assertRaises(BenchError) as raised:
                    self._baseline_verify("retained", analysis_document=forged, policy_document=policy)
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                self.assertEqual(raised.exception.field_path, "retained_slot_statistics")

    def test_cb_v09_descriptive_policy_cannot_launder_reasons_or_candidates(self) -> None:
        for family in ("retained", "cross"):
            for field in ("reasons", "candidate_statuses"):
                with self.subTest(family=family, field=field):
                    policy = copy.deepcopy(self.cases[family][3])
                    policy[field] = ["invented-reason"] if field == "reasons" else {"invented-arm": "INCONCLUSIVE"}
                    with self.assertRaises(BenchError) as raised:
                        self._baseline_verify(family, policy_document=policy)
                    self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                    self.assertEqual(raised.exception.field_path, field)

    def test_cb_v10_authenticated_policy_requires_all_ten_checks(self) -> None:
        from quervant_bench.official import policy_inputs
        from quervant_bench.tests.test_official_retained_policy import micro_table

        fixture, record, _derived, _policy = self.cases["retained"]
        inputs = policy_inputs._open_fixture_retained_policy_inputs(admitted=record, micro=micro_table())
        derived, policy = analysis.analyze_official_study(admitted=record, template=fixture.template, policy_inputs=inputs)
        assessment = self._baseline_verify("retained", analysis_document=derived, policy_document=policy, policy_inputs=inputs)
        self.assertEqual(policy["schema_version"], 2)
        self.assertEqual(len(policy["retained_key_policy"]["rows"]), 9)
        self.assertEqual(assessment["policy_verification_status"], "PASS")
        self.assertEqual(assessment["not_evaluated_checks"], [])
        self.assertEqual(assessment["check_ids"], list(verification.VERIFIER_CHECK_IDS))
        inputs._fixture_micro["records"][0]["key_bytes"] += 1
        with self.assertRaises(BenchError):
            self._baseline_verify("retained", analysis_document=derived, policy_document=policy, policy_inputs=inputs)

    def test_cb_v10_supplied_invalid_policy_never_becomes_absence(self) -> None:
        for family in ("cross", "retained"):
            with self.subTest(family=family):
                fixture, record, _derived, _policy = self.cases[family]
                with self.assertRaises(BenchError):
                    analysis.analyze_official_study(admitted=record, template=fixture.template, policy_inputs=object())
                with self.assertRaises(BenchError):
                    self._baseline_verify(family, policy_inputs=object())

    def test_cb_v11_insufficient_symmetric_blocks_stop_without_partial_analysis(self) -> None:
        fixture, admitted, _derived, _policy = self.cases["retained"]
        broken = copy.deepcopy(admitted)
        for block in range(1, 10):
            candidates = [slot for slot in broken.slots["d3c-v3r3-strategies-01"] if slot["block"] == block and slot["arm"] == "A"]
            self.assertEqual(len(candidates), 2)
            lane = next(row for row in candidates[-1]["lanes"] if row["id"] == "pr15d_v1/10000/rare/k10")
            lane["samples_ns"] = [value * 2 for value in lane["samples_ns"]]
            lane["summary_ns"] = support.summary(lane["samples_ns"])
        with self.assertRaises(BenchError) as raised:
            analysis.analyze_official_study(admitted=broken, template=fixture.template)
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
        self.assertEqual(raised.exception.field_path, "retained_slot_statistics")

    def test_cb_v11_other_pairing_failures_are_not_absence(self) -> None:
        from unittest.mock import patch

        fixture, record, _derived, _policy = self.cases["retained"]
        for message in (
            "retained policy slot summary differs from its raw samples",
            "fewer than four symmetric retained blocks for invented-campaign/invented-lane",
        ):
            with self.subTest(message=message):
                failure = BenchError(BM_IDENTITY_INVALID, message, field_path="retained_key_policy")
                with patch("quervant_bench.official.retained_policy.derive_slot_statistics", side_effect=failure):
                    with self.assertRaises(BenchError) as raised:
                        analysis.analyze_official_study(admitted=record, template=fixture.template)
                self.assertIs(raised.exception, failure)


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
        self.assertEqual(raised.exception.field_path, "admission")
        for submitted, authoritative in (
            (self.record, fresh),
            (fresh, self.record),
        ):
            with self.subTest(
                submitted_type=type(submitted).__name__,
                authoritative_type=type(authoritative).__name__,
            ):
                with self.assertRaises(BenchError) as raised:
                    verification._require_exact_admitted_record(submitted, authoritative)
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                self.assertEqual(raised.exception.field_path, "admission")
        verification._require_exact_admitted_record(copy.deepcopy(self.record), self.record)
        verification._require_exact_admitted_record(copy.deepcopy(fresh), fresh)

        # Public orientation: a retained-key record submitted with the valid
        # cross-engine capability must fail at the shared admission guard.
        import dataclasses

        wrong_family = dataclasses.replace(
            fresh,
            fixture_only=False,
            raw_series_root_digest=self.capability.raw_series_root_digest,
            admission_index=copy.deepcopy(self.record.admission_index),
        )
        with self.assertRaises(BenchError) as raised:
            self._verify(candidate=wrong_family)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "admission")

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

    def test_f4_gc_01_capability_control_alias_is_rejected(self) -> None:
        import copy

        from quervant_bench.official import admission as official_admission
        from quervant_bench.official import analysis as official_analysis

        record = self.capability.record
        saved_control = copy.deepcopy(record.control)
        control_path = self.fixture.raw_root / "control" / "control.json"
        saved_bytes = control_path.read_bytes()
        saved_inventory = official_admission.admitted_inventory_digest(record)
        try:
            record.control["block_count"] = 11
            candidate_analysis, candidate_policy = official_analysis.analyze_official_study(
                admitted=record, template=self.fixture.template
            )
            self.assertEqual(control_path.read_bytes(), saved_bytes)
            self.assertEqual(
                official_admission.admitted_inventory_digest(record), saved_inventory
            )
            with self.assertRaises(BenchError) as raised:
                self._verify(
                    candidate=record,
                    analysis_document=candidate_analysis,
                    policy_document=candidate_policy,
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertEqual(raised.exception.field_path, "control")
            self.assertEqual(control_path.read_bytes(), saved_bytes)
            self.assertEqual(
                official_admission.admitted_inventory_digest(record), saved_inventory
            )
        finally:
            record.control.clear()
            record.control.update(saved_control)

    def test_f4_gc_02_submitted_numeric_alias_is_rejected(self) -> None:
        import copy

        from quervant_bench.config.codec import canonical_payload_bytes

        candidate = copy.deepcopy(self.record)
        candidate.control["block_count"] = 12.0
        self.assertEqual(candidate, self.record)  # Python dataclass equality hides it
        self.assertNotEqual(
            canonical_payload_bytes(dict(candidate.control)),
            canonical_payload_bytes(dict(self.record.control)),
        )
        with self.assertRaises(BenchError) as raised:
            self._verify(candidate=candidate)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "admission")

    def test_f4b_gc_01_helper_rejects_cross_engine_numeric_alias(self) -> None:
        import copy

        from quervant_bench.config.codec import canonical_payload_bytes

        candidate = copy.deepcopy(self.record)
        candidate.control["block_count"] = 12.0
        self.assertEqual(candidate, self.record)
        self.assertNotEqual(
            canonical_payload_bytes(dict(candidate.control)),
            canonical_payload_bytes(dict(self.record.control)),
        )
        with self.assertRaises(BenchError) as raised:
            verification._require_exact_admitted_record(candidate, self.record)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "admission")

    def test_f4_gc_03_equivalent_copy_and_repetition_are_verified(self) -> None:
        import copy

        candidate = copy.deepcopy(self.record)
        reordered = {
            key: candidate.control[key] for key in reversed(list(candidate.control))
        }
        candidate.control.clear()
        candidate.control.update(reordered)
        first = self._verify(candidate=candidate)
        second = self._verify(candidate=candidate)
        self.assertEqual(first["status"], "VERIFIED_REAL")
        self.assertEqual(second["status"], "VERIFIED_REAL")
        self.assertEqual(first["check_ids"], list(verification.VERIFIER_CHECK_IDS))
        self.assertEqual(first["analysis_digest"], second["analysis_digest"])
        self.assertFalse((self.root / "output").exists())

    def test_f4_gc_04_copied_control_with_coherent_analysis_is_rejected(self) -> None:
        import copy

        from quervant_bench.official import admission as official_admission
        from quervant_bench.official import analysis as official_analysis

        control_path = self.fixture.raw_root / "control" / "control.json"
        saved_bytes = control_path.read_bytes()
        saved_inventory = official_admission.admitted_inventory_digest(self.record)
        candidate = copy.deepcopy(self.record)
        candidate.control["block_count"] = 11
        candidate_analysis, candidate_policy = official_analysis.analyze_official_study(
            admitted=candidate, template=self.fixture.template
        )
        with self.assertRaises(BenchError) as raised:
            self._verify(
                candidate=candidate,
                analysis_document=candidate_analysis,
                policy_document=candidate_policy,
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(raised.exception.field_path, "admission")
        self.assertEqual(control_path.read_bytes(), saved_bytes)
        self.assertEqual(
            official_admission.admitted_inventory_digest(self.record), saved_inventory
        )
