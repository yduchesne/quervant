"""O09-SCOPE / O09-ANA contract tests for the official closed records."""

from __future__ import annotations

from quervant_bench.official import protocols

import copy
import unittest

from quervant_bench.config.codec import content_digest
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCOPE_MISMATCH,
    BenchError,
)
from quervant_bench.official import contracts


def _subject() -> dict[str, str]:
    return {
        "experiment_id": "cross-engine-keyword-real-v1",
        "run_id": "11111111-1111-4111-8111-111111111111",
        "protocol_digest": "sha256:" + "a" * 64,
        "workload_digest": "sha256:" + "b" * 64,
    }


class ScopeTests(unittest.TestCase):
    """O09-SCOPE-01..05: the real/official pair is the only admitted scope."""

    def test_o09_scope_01_official_scope_accepts_only_real_official(self) -> None:
        self.assertEqual(
            contracts.require_official_scope("real", "official"), ("real", "official")
        )
        self.assertEqual(
            contracts.require_official_scope(
                {"evidence_origin": "real", "qualification_scope": "official"}
            ),
            ("real", "official"),
        )

    def test_o09_scope_02_synthetic_scope_is_rejected(self) -> None:
        with self.assertRaises(BenchError) as raised:
            contracts.require_official_scope("synthetic", "simulated")
        self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)

    def test_o09_scope_03_historical_scope_is_rejected_by_official_intake(self) -> None:
        with self.assertRaises(BenchError) as raised:
            contracts.require_official_scope("real", "historical_replay")
        self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)
        self.assertEqual(
            contracts.require_historical_scope("real", "historical_replay"),
            ("real", "historical_replay"),
        )

    def test_o09_scope_04_missing_scope_is_rejected(self) -> None:
        with self.assertRaises(BenchError) as raised:
            contracts.require_official_scope({"evidence_origin": "real"})
        self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)

    def test_o09_scope_05_history_scope_rejects_official(self) -> None:
        with self.assertRaises(BenchError) as raised:
            contracts.require_historical_scope("real", "official")
        self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)


class ProfileTests(unittest.TestCase):
    def _profile(self) -> dict:
        return {
            "kind": contracts.OFFICIAL_PROFILE_KIND,
            "schema_version": 1,
            "evidence_origin": "real",
            "qualification_scope": "official",
            "profile_id": contracts.PROFILE_ID,
            "profile_version": contracts.PROFILE_VERSION,
            "required_gates": list(contracts.OFFICIAL_GATE_ORDER),
            "required_verifier_checks": list(contracts.VERIFIER_CHECK_IDS),
            "framework_qa_roster": list(contracts.FRAMEWORK_QA_ROSTER),
            "source_qa_roster": list(contracts.SOURCE_QA_ROSTER),
            "max_document_bytes": contracts.MAX_DOCUMENT_BYTES,
        }

    def test_valid_profile_is_accepted(self) -> None:
        self.assertEqual(
            contracts.validate_official_profile(self._profile())["profile_id"],
            contracts.PROFILE_ID,
        )

    def test_unknown_profile_field_is_rejected(self) -> None:
        profile = self._profile()
        profile["extra"] = True
        with self.assertRaises(BenchError) as raised:
            contracts.validate_official_profile(profile)
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

    def test_profile_roster_drift_is_rejected(self) -> None:
        profile = self._profile()
        profile["source_qa_roster"] = profile["source_qa_roster"][:-1]
        with self.assertRaises(BenchError) as raised:
            contracts.validate_official_profile(profile)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


class PolicyTests(unittest.TestCase):
    def _policy(self) -> dict:
        return {
            "kind": contracts.POLICY_KIND,
            "schema_version": 1,
            "evidence_origin": "real",
            "qualification_scope": "official",
            "subject": _subject(),
            "study_id": "cross-engine-keyword-real-v1",
            "policy_digest": "sha256:" + "c" * 64,
            "analysis_digest": "sha256:" + "d" * 64,
            "decision_status": contracts.DECISION_INCONCLUSIVE,
            "selected_arm_id": None,
            "candidate_statuses": {"quervant": "INCONCLUSIVE"},
            "reasons": ["no-significance-claim"],
            "performance_claim_allowed": False,
        }

    def test_o09_ana_17_inconclusive_selection_is_rejected(self) -> None:
        policy = self._policy()
        policy["selected_arm_id"] = "quervant"
        with self.assertRaises(BenchError) as raised:
            contracts.validate_official_policy(policy)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ana_18_claim_without_resolved_decision_is_rejected(self) -> None:
        policy = self._policy()
        policy["performance_claim_allowed"] = True
        with self.assertRaises(BenchError) as raised:
            contracts.validate_official_policy(policy)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ana_19_selected_arm_must_be_eligible(self) -> None:
        policy = self._policy()
        policy["decision_status"] = contracts.DECISION_SELECTED
        policy["selected_arm_id"] = "quervant"
        policy["performance_claim_allowed"] = True
        with self.assertRaises(BenchError) as raised:
            contracts.validate_official_policy(policy)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        policy["candidate_statuses"] = {"quervant": "ELIGIBLE"}
        validated = contracts.validate_official_policy(policy)
        self.assertTrue(validated["performance_claim_allowed"])

    def test_o09_ana_20_unknown_decision_status_is_rejected(self) -> None:
        policy = self._policy()
        policy["decision_status"] = "FASTEST"
        with self.assertRaises(BenchError) as raised:
            contracts.validate_official_policy(policy)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


class AnalysisRecordTests(unittest.TestCase):
    def _analysis(self) -> dict:
        lane = {
            "lane_id": "pr15d_v1/10000/absent/k10",
            "per_engine": {
                engine: {
                    "trial_medians_ns": [10, 15, 20],
                    "median_ns": 15,
                    "min_ns": 10,
                    "max_ns": 20,
                    "dispersion": "2.000000",
                }
                for engine in ("lucene", "quervant", "tantivy")
            },
            "comparisons": [
                {
                    "comparator": "lucene",
                    "ratio": "1.000000",
                    "dispersion_ok": False,
                    "ranges_overlap": True,
                    "inconclusive": True,
                }
            ],
        }
        return {
            "kind": contracts.ANALYSIS_KIND,
            "schema_version": 1,
            "evidence_origin": "real",
            "qualification_scope": "official",
            "subject": _subject(),
            "study_id": "cross-engine-keyword-real-v1",
            "raw_series_root_digest": "sha256:" + "e" * 64,
            "analysis_profile_digest": "sha256:" + "f" * 64,
            "statistics_method_id": contracts.STATISTICS_CROSS_ENGINE,
            "eligible_lane_ids": ["pr15d_v1/10000/absent/k10"],
            "excluded_lane_classes": list(contracts.EXCLUDED_LANE_CLASSES),
            "control_result_digest": "sha256:" + "1" * 64,
            "campaigns": [
                {
                    "campaign_id": "separate-aa-control",
                    "slot_count": 48,
                    "lane_count": 16,
                    "sample_count": 15_360,
                    "control": True,
                    "descriptive_process_cold": [],
                }
            ],
            "statistics": {
                "method_id": contracts.STATISTICS_CROSS_ENGINE,
                "unit": contracts.OFFICIAL_UNIT,
                "engines": ["lucene", "quervant", "tantivy"],
                "lanes": [lane],
            },
            "uncertainty": {
                "method_id": "pr15d-three-trial-discrete-range-v1",
                "dispersion_limit": "1.100000",
                "overlap_rule": True,
                "significance_claim": "none",
            },
            "limitations": ["no-significance-claim"],
        }

    def test_valid_analysis_is_accepted(self) -> None:
        self.assertEqual(
            contracts.validate_official_analysis(self._analysis())["statistics_method_id"],
            contracts.STATISTICS_CROSS_ENGINE,
        )

    def test_o09_ana_05_excluded_classes_are_exact(self) -> None:
        analysis = self._analysis()
        analysis["excluded_lane_classes"] = ["process_cold"]
        with self.assertRaises(BenchError) as raised:
            contracts.validate_official_analysis(analysis)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ana_06_unsorted_lane_ids_are_rejected(self) -> None:
        analysis = self._analysis()
        analysis["eligible_lane_ids"] = [
            "pr15d_v1/10000/rare/k10",
            "pr15d_v1/10000/absent/k10",
        ]
        with self.assertRaises(BenchError) as raised:
            contracts.validate_official_analysis(analysis)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ana_07_float_ratio_is_rejected(self) -> None:
        analysis = self._analysis()
        analysis["statistics"]["lanes"][0]["comparisons"][0]["ratio"] = 1.0
        with self.assertRaises(BenchError) as raised:
            contracts.validate_official_analysis(analysis)
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

    def test_o09_ana_08_unknown_method_is_rejected(self) -> None:
        analysis = self._analysis()
        analysis["statistics_method_id"] = "invented-method"
        with self.assertRaises(BenchError) as raised:
            contracts.validate_official_analysis(analysis)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


class MemberRecordTests(unittest.TestCase):
    def test_o09_rec_duplicate_paths_are_rejected(self) -> None:
        members = [
            {"path": "a.json", "byte_length": 1, "digest": "sha256:" + "a" * 64},
            {"path": "a.json", "byte_length": 1, "digest": "sha256:" + "a" * 64},
        ]
        with self.assertRaises(BenchError) as raised:
            contracts.validate_member_records(members, "members", (), allow_relative=True)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_rec_boolean_byte_length_is_rejected(self) -> None:
        members = [
            {"path": "a.json", "byte_length": True, "digest": "sha256:" + "a" * 64}
        ]
        with self.assertRaises(BenchError):
            contracts.validate_member_records(members, "members", (), allow_relative=True)

    def test_o09_rec_traversal_path_is_rejected(self) -> None:
        members = [
            {"path": "../a.json", "byte_length": 1, "digest": "sha256:" + "a" * 64}
        ]
        with self.assertRaises(BenchError):
            contracts.validate_member_records(members, "members", (), allow_relative=True)

    def test_o09_rec_member_record_matches_canonical_bytes(self) -> None:
        document = {"kind": "x", "schema_version": 1}
        record = contracts.member_record("a.json", document)
        self.assertEqual(record["digest"], content_digest(document))
        self.assertGreater(record["byte_length"], 0)


DIGEST = "sha256:" + "a" * 64
BASELINE = "22222222-2222-4222-8222-222222222222"
PROFILE = "current-baseline-v2"
PAIRS = (("L", "A"), ("P", "A"), ("H", "A"), ("P", "L"), ("H", "L"), ("H", "P"))

def slot_payload():
    lanes = {}
    for n in (10_000, 100_000):
        for name in ("absent", "rare", "medium", "common"):
            for k in (1, 10, 32, 64, 100, 128, 256, 512, 1024):
                lane_id = f"pr15d_v1/{n}/{name}/k{k}"
                campaigns = {}
                for campaign in ("d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02"):
                    record = {"retained": list(range(1, 13)), "retained_count": 12,
                              "latency": {"A": 100, "L": 80, "P": 60, "H": 30},
                              "raw_latency": {"A": 100, "L": 80, "P": 60, "H": 30},
                              "filter_sensitive": False}
                    for (num, den), ratio in zip(PAIRS, (0.8, 0.6, 0.3, 0.75, 0.375, 0.5)):
                        record[f"R_{num}_{den}"] = ratio
                        record[f"CI_{num}_{den}"] = {"low": ratio, "high": ratio, "seed": 11}
                    campaigns[campaign] = record
                lanes[lane_id] = {"id": lane_id, "n": n, "class": name, "k": k, "campaigns": campaigns}
    return {"method_id": "retained-key-paired-slot-effects-v1", "lanes": lanes}

class BaselineResultContractTests(unittest.TestCase):
    def test_v09_complete_paired_slot_contract_and_exact_counterexamples(self):
        payload = slot_payload()
        self.assertEqual(contracts.validate_retained_slot_statistics(payload), payload)
        lane = next(iter(payload["lanes"]))
        for label, mutate in (
            ("missing-lane", lambda value: value["lanes"].pop(lane)),
            ("bool-coordinate", lambda value: value["lanes"][lane].update(k=True)),
            ("missing-campaign", lambda value: value["lanes"][lane]["campaigns"].pop("d3c-v3r3-strategies-02")),
            ("fewer-than-four", lambda value: value["lanes"][lane]["campaigns"]["d3c-v3r3-strategies-01"].update(retained=[1, 2, 3], retained_count=3)),
            ("string-ratio", lambda value: value["lanes"][lane]["campaigns"]["d3c-v3r3-strategies-01"].update(R_L_A="0.8")),
            ("nonfinite-ratio", lambda value: value["lanes"][lane]["campaigns"]["d3c-v3r3-strategies-01"].update(R_L_A=float("inf"))),
            ("reversed-ci", lambda value: value["lanes"][lane]["campaigns"]["d3c-v3r3-strategies-01"]["CI_L_A"].update(low=2.0)),
            ("seed-alias", lambda value: value["lanes"][lane]["campaigns"]["d3c-v3r3-strategies-01"]["CI_L_A"].update(seed=True)),
            ("seed-overflow", lambda value: value["lanes"][lane]["campaigns"]["d3c-v3r3-strategies-01"]["CI_L_A"].update(seed=2**64)),
        ):
            with self.subTest(case=label):
                wrong = copy.deepcopy(payload)
                mutate(wrong)
                with self.assertRaises(BenchError):
                    contracts.validate_retained_slot_statistics(wrong)

    def assessment(self, study=protocols.STUDY_RETAINED_KEY, evaluated=False):
        return {"kind": "official-verification-assessment", "schema_version": 2,
                "evidence_origin": "real", "qualification_scope": "official",
                "subject": {"experiment_id": study, "run_id": "11111111-1111-4111-8111-111111111111", "protocol_digest": DIGEST, "workload_digest": DIGEST},
                "study_id": study, "status": "VERIFIED_CURRENT_BASELINE", "raw_series_root_digest": DIGEST,
                "analysis_digest": DIGEST, "policy_digest": DIGEST, "reference_id": "official-independent-reference-v1",
                "check_ids": [check for check in contracts.VERIFIER_CHECK_IDS if evaluated or check != "RV-08-POLICY"],
                "verified_claims": ["policy-decision"] if evaluated else [],
                "verification_scope": PROFILE, "policy_verification_status": "PASS" if evaluated else "NOT_EVALUATED",
                "not_evaluated_checks": [] if evaluated else ["RV-08-POLICY"]}

    def test_v09_v10_baseline_verification_excludes_only_absent_retained_policy(self):
        for study, evaluated in ((protocols.STUDY_RETAINED_KEY, False), (protocols.STUDY_RETAINED_KEY, True), (protocols.STUDY_CROSS_ENGINE, True)):
            with self.subTest(study=study, evaluated=evaluated):
                value = self.assessment(study, evaluated)
                self.assertEqual(contracts.validate_official_verification(value), value)
        for label, change in (
            ("old-pass-status", {"status": "VERIFIED_REAL"}),
            ("extra-exemption", {"not_evaluated_checks": ["RV-08-POLICY", "RV-04-ORACLE"]}),
            ("missing-oracle", {"check_ids": [check for check in contracts.VERIFIER_CHECK_IDS if check not in ("RV-04-ORACLE", "RV-08-POLICY")]}),
            ("false-policy-claim", {"verified_claims": ["policy-decision"]}),
            ("false-pass-policy", {"policy_verification_status": "PASS"}),
            ("wrong-scope", {"verification_scope": "official-v1"}),
            ("v1-with-v2-fields", {"schema_version": 1}),
        ):
            with self.subTest(case=label):
                with self.assertRaises(BenchError):
                    contracts.validate_official_verification({**self.assessment(), **change})
        with self.assertRaises(BenchError):
            contracts.validate_official_verification(self.assessment(protocols.STUDY_CROSS_ENGINE, False))

    def test_v12_acceptance2_replaces_parity_without_relabelling_verification(self):
        subject = self.assessment()["subject"]
        value = {"kind": "official-acceptance-summary", "schema_version": 2, "evidence_origin": "real", "qualification_scope": "official",
                 "subject": subject, "approved_design_digest": DIGEST, "authorization_digest": DIGEST, "source_set_digest": DIGEST,
                 "gate_receipt_ids": {gate: DIGEST for gate in ("admission", "analysis", "framework-qa", "source-qa", "verification")},
                 "policy_decision_status": "POLICY_NOT_DERIVABLE", "history_report_digest": DIGEST, "baseline_id": BASELINE,
                 "baseline_verification_status": "VERIFIED_CURRENT_BASELINE", "policy_verification_status": "NOT_EVALUATED",
                 "required_control_status": "PASS", "qa_status": "PASS", "admission_status": "PASS", "decision_scope": "real-current-baseline-v2"}
        self.assertEqual(contracts.validate_official_acceptance(value), value)
        for label, change in (("old-parity", {"historical_parity_status": "PASS"}), ("old-scope", {"decision_scope": "real-official-v1"}),
                              ("old-pass", {"baseline_verification_status": "VERIFIED_REAL"}), ("bad-baseline", {"baseline_id": "other"}),
                              ("bool-version", {"schema_version": True}), ("v1-with-v2-fields", {"schema_version": 1})):
            with self.subTest(case=label):
                with self.assertRaises(BenchError):
                    contracts.validate_official_acceptance({**value, **change})

if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
