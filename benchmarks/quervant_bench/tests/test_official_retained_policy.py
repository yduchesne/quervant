"""Untimed migration tests for raw-input T7/F2 policy and historical mappings."""

from __future__ import annotations

import copy
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.official import analysis, contracts, historical, policy_inputs, policy_reference, retained_policy, verification
from quervant_bench.official.admission import AdmittedRetainedKey
from quervant_bench.official.protocols import STUDY_RETAINED_KEY
from quervant_bench.tests import official_support as support

DIGEST = "sha256:" + "a" * 64


def micro_table(memory_excluded: bool = False) -> dict:
    records = []
    for variant in ("linear", "P0", "P1", "P2", "exact_set"):
        for k in policy_inputs.KS:
            for length in (8, 32, 128, 1024):
                for trace in ("miss_stable", "duplicate_retained", "churn", "evicted_revisit", "collision_distinct"):
                    records.append({"variant": variant, "k": k, "key_len": length, "trace": trace,
                                    "rounds": [1, 1, 1, 1, 1], "set_len": k, "set_capacity": k + 1,
                                    "key_bytes": 3_000_000 if memory_excluded else k * length})
    return {"schema": "pr15i-d3c-micro-v1", "selected_profile": "P2",
            "source_experiment_sha": policy_inputs.EXPERIMENT_COMMIT, "records": records}


def raw_model(*, p: int = 900, h: int = 950, mixed: bool = False) -> AdmittedRetainedKey:
    slots = {}
    for campaign in policy_inputs.CAMPAIGNS:
        campaign_slots = []
        for block in range(1, 13):
            for position, arm in enumerate(("A", "L", "P", "H", "H", "P", "L", "A"), 1):
                rows = []
                for k in policy_inputs.KS:
                    for lane_id in retained_policy.required_lanes(k):
                        values = {"A": 1000, "L": 990, "P": p, "H": h}
                        if mixed and k != 1:
                            values["P"], values["H"] = h, p
                        value = values[arm]
                        rows.append({"id": lane_id, "samples_ns": [value] * 20,
                                     "summary_ns": {"median": value}})
                campaign_slots.append({"block": block, "position": position, "arm": arm, "lanes": rows})
        slots[campaign] = tuple(campaign_slots)
    return AdmittedRetainedKey(raw_root=Path("/nonexistent-policy-fixture"), campaigns={}, slots=slots,
        control_assessment={}, inventory=(), raw_series_root_digest=DIGEST, comparability_digest=DIGEST,
        admission_index={}, original_verifier={}, fixture_only=True)


class RetainedPolicyArithmeticTests(unittest.TestCase):
    def compare(self, record, memory=None):
        memory = memory or policy_inputs.validate_micro_table(micro_table())
        actual = retained_policy.derive_retained_policy(record, memory, DIGEST)
        expected = policy_reference.reference_retained_policy(record, memory, DIGEST)
        self.assertEqual(actual, expected)
        self.assertEqual([row["k"] for row in actual["rows"]], list(policy_inputs.KS))
        self.assertEqual(len(actual["rows"]), 9)
        return actual

    def test_positive_selection_from_raw_slots_and_micro_memory(self):
        result = self.compare(raw_model(), policy_inputs.validate_micro_table(micro_table(True)))
        self.assertTrue(all(row["selected_strategy"] == "P" and row["decision_status"] == "SELECTED_ELIGIBLE" for row in result["rows"]))
        self.assertTrue(all(row["P_status"] == "ELIGIBLE" and row["H_status"] == "INELIGIBLE" for row in result["rows"]))
        self.assertEqual(contracts.retained_policy_decisions(result)["decision_status"], contracts.DECISION_SELECTED)

    def test_tie_preference_makes_no_speed_claim(self):
        result = self.compare(raw_model(p=900, h=900))
        self.assertTrue(all(row["decision_status"] == "P_TIEBREAKER_NOT_PROVEN_FASTER" for row in result["rows"]))
        summary = contracts.retained_policy_decisions(result)
        self.assertEqual(summary["decision_status"], contracts.DECISION_TIE_PREFERENCE)
        self.assertIs(summary["performance_claim_allowed"], False)

    def test_exact_three_percent_is_not_tie_and_uses_gm_confirmation(self):
        self.assertFalse(policy_reference.within_three_percent(Fraction(1), Fraction(103, 100) ** 8))
        result = self.compare(raw_model(p=900, h=927))
        self.assertTrue(all(row["decision_status"] == "SELECTED_GM_CONFIRMED" for row in result["rows"]))

    def test_both_decisively_ineligible_retains_baseline(self):
        result = self.compare(raw_model(p=1000, h=1000))
        self.assertTrue(all(row["selected_strategy"] == "LINEAR_BASE" for row in result["rows"]))
        summary = contracts.retained_policy_decisions(result)
        self.assertEqual(summary["decision_status"], contracts.DECISION_BASELINE_ONLY)
        self.assertIs(summary["performance_claim_allowed"], False)

    def test_mixed_k_winners_remain_explicit(self):
        result = self.compare(raw_model(p=850, h=950, mixed=True))
        self.assertEqual([row["selected_strategy"] for row in result["rows"]], ["P"] + ["H"] * 8)
        summary = contracts.retained_policy_decisions(result)
        self.assertEqual(summary["decision_status"], contracts.DECISION_PER_K_RESOLVED)
        self.assertIsNone(summary["selected_arm_id"])
        self.assertFalse(summary["performance_claim_allowed"])

    def test_symmetric_filter_preserves_filter_sensitive_inconclusive(self):
        record = raw_model(p=800, h=850)
        lane_id = retained_policy.required_lanes(1)[0]
        for slot in record.slots[policy_inputs.CAMPAIGNS[0]]:
            if slot["block"] > 4 and slot["arm"] in ("P", "H"):
                lane = next(row for row in slot["lanes"] if row["id"] == lane_id)
                value = 900 if slot["arm"] == "H" else 400 if slot["position"] == 3 else 1550
                lane["samples_ns"] = [value] * 20
                lane["summary_ns"]["median"] = value
        result = self.compare(record)
        row = result["rows"][0]
        self.assertTrue(row["filter_sensitive"])
        self.assertEqual(row["decision_status"], "K_INCONCLUSIVE_FILTER_SENSITIVE")
        stats, _ = retained_policy.derive_slot_statistics(record)
        self.assertEqual(stats[lane_id]["campaigns"][policy_inputs.CAMPAIGNS[0]]["retained"], [1, 2, 3, 4])

    def test_nonconstant_bootstrap_and_even_median_match_independent_reference(self):
        record = raw_model()
        lane_id = retained_policy.required_lanes(1)[0]
        for slot in record.slots[policy_inputs.CAMPAIGNS[0]]:
            if slot["arm"] == "P":
                lane = next(row for row in slot["lanes"] if row["id"] == lane_id)
                value = 850 + slot["block"] * 2
                lane["samples_ns"] = [value] * 20
                lane["summary_ns"]["median"] = value
        primary, _ = retained_policy.derive_slot_statistics(record)
        reference, _ = policy_reference.reference_slot_statistics(record)
        self.assertEqual(primary, reference)
        row = primary[lane_id]["campaigns"][policy_inputs.CAMPAIGNS[0]]
        self.assertEqual(row["latency"]["P"], 863.0)
        self.assertLess(row["CI_P_A"]["low"], row["CI_P_A"]["high"])

    def test_insufficient_symmetric_blocks_never_invents_ratios(self):
        record = raw_model()
        for slot in record.slots[policy_inputs.CAMPAIGNS[0]]:
            if slot["block"] > 3 and slot["arm"] == "P" and slot["position"] == 3:
                lane = slot["lanes"][0]
                lane["samples_ns"] = [5000] * 20
                lane["summary_ns"]["median"] = 5000
        with self.assertRaises(BenchError):
            retained_policy.derive_retained_policy(record, policy_inputs.validate_micro_table(micro_table()), DIGEST)
        with self.assertRaises(BenchError):
            policy_reference.reference_retained_policy(record, policy_inputs.validate_micro_table(micro_table()), DIGEST)

    def test_reference_does_not_call_primary_helpers(self):
        with patch.object(retained_policy, "derive_slot_statistics", side_effect=AssertionError("primary called")):
            result = policy_reference.reference_retained_policy(raw_model(), policy_inputs.validate_micro_table(micro_table()), DIGEST)
        self.assertEqual(len(result["rows"]), 9)


class PolicyInputTests(unittest.TestCase):
    def test_complete_micro_grid_and_memory_accounting(self):
        memory = policy_inputs.validate_micro_table(micro_table())
        self.assertEqual(memory["1024"], 1025 * 40 + 1024 * 1024)
        self.assertEqual(set(memory), {str(k) for k in policy_inputs.KS})

    def test_micro_alias_missing_duplicate_and_nonfinite_rejected(self):
        for mutation in ("missing", "duplicate", "alias", "nonfinite"):
            with self.subTest(mutation=mutation):
                data = micro_table()
                if mutation == "missing": data["records"].pop()
                if mutation == "duplicate": data["records"][-1] = copy.deepcopy(data["records"][0])
                if mutation == "alias": data["records"][0]["k"] = True
                if mutation == "nonfinite": data["records"][0]["rounds"][0] = float("inf")
                with self.assertRaises(BenchError):
                    policy_inputs.validate_micro_table(data)

    def test_fixture_capability_is_detached_and_cannot_be_relabelled_real(self):
        record, micro = raw_model(), micro_table()
        capability = policy_inputs._open_fixture_retained_policy_inputs(admitted=record, micro=micro)
        micro["records"][0]["set_capacity"] += 1
        policy_inputs.reverify_retained_policy_inputs(capability, admitted=record, for_production=False)
        for candidate in (capability, replace(capability, fixture_only=False), replace(capability, fixture_only=False, scope="historical_replay")):
            with self.subTest(scope=candidate.scope, fixture=candidate.fixture_only), self.assertRaises(BenchError):
                policy_inputs.reverify_retained_policy_inputs(candidate, for_production=True)

    def test_coherent_in_memory_slot_forgery_fails_input_binding(self):
        record = raw_model()
        capability = policy_inputs._open_fixture_retained_policy_inputs(admitted=record, micro=micro_table())
        lane = record.slots[policy_inputs.CAMPAIGNS[0]][0]["lanes"][0]
        lane["samples_ns"] = [2000] * 20
        lane["summary_ns"]["median"] = 2000
        with self.assertRaises(BenchError) as raised:
            policy_inputs.reverify_retained_policy_inputs(capability, admitted=record, for_production=False)
        self.assertEqual(raised.exception.field_path, "admission")

    def test_strict_disk_reader_rejects_duplicate_json_and_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "micro.json"
            path.write_bytes(b'{"key":1,"key":2}')
            with self.assertRaises(BenchError): policy_inputs._read_input(path)
            path.write_bytes(b'{"key":1}')
            data, digest = policy_inputs._read_input(path)
            self.assertEqual(data, {"key": 1})
            self.assertEqual(digest, "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())
            link = root / "link.json"
            link.symlink_to(path)
            with self.assertRaises(BenchError): policy_inputs._read_input(link)

    def test_f1_receipt_cannot_be_a_caller_declared_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            path.write_text(json.dumps({"status": "PASS", "t7_commit": policy_inputs.F1_COMMIT}))
            with self.assertRaises(BenchError) as raised:
                policy_inputs._f1_identity(path, support.REPO_ROOT)
            self.assertEqual(raised.exception.field_path, "f1_receipt")


class PublicRetainedPolicyGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.fixture = support.make_retained_key_fixture(Path(cls.temporary.name))
        cls.admitted = support.admit_fixture_retained_key(cls.fixture)
        cls.inputs = policy_inputs._open_fixture_retained_policy_inputs(admitted=cls.admitted, micro=micro_table())
        cls.analysis, cls.policy = analysis.analyze_official_study(admitted=cls.admitted, template=cls.fixture.template, policy_inputs=cls.inputs)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def verify(self, policy, inputs):
        return verification.verify_official_study(admitted=self.admitted, template=self.fixture.template,
            authorization=support.fixture_authorization(STUDY_RETAINED_KEY, freeze=self.fixture.freeze),
            analysis=self.analysis, policy=policy, policy_inputs=inputs)

    def test_complete_derived_policy_opens_rv08(self):
        self.assertEqual(self.policy["schema_version"], 2)
        result = self.verify(self.policy, self.inputs)
        self.assertEqual(result["status"], "VERIFIED_REAL")
        self.assertIn("RV-08-POLICY", result["check_ids"])
        self.assertEqual(self.policy["decision_status"], contracts.DECISION_BASELINE_ONLY)

    def test_policy_without_its_verified_inputs_is_rejected(self):
        with self.assertRaises(BenchError): self.verify(self.policy, None)

    def test_rehashed_nine_k_forgery_is_rejected_by_independent_reference(self):
        forged = copy.deepcopy(self.policy)
        forged["retained_key_policy"]["rows"][0]["H_memory"] += 1
        forged = contracts.validate_official_policy(forged)
        with self.assertRaises(BenchError) as raised:
            self.verify(forged, self.inputs)
        self.assertEqual(raised.exception.field_path, "retained_key_policy")

    def test_missing_inputs_preserve_typed_underivable_v1(self):
        _, old_policy = analysis.analyze_official_study(admitted=self.admitted, template=self.fixture.template)
        self.assertEqual(old_policy["schema_version"], 1)
        self.assertEqual(old_policy["decision_status"], contracts.DECISION_POLICY_NOT_DERIVABLE)


class RetainedHistoricalMappingTests(unittest.TestCase):
    def mapping(self):
        payload = retained_policy.derive_retained_policy(raw_model(), policy_inputs.validate_micro_table(micro_table()), DIGEST)
        return {"kind": historical.PARITY_MAPPING_KIND, "schema_version": 2, "study_id": STUDY_RETAINED_KEY,
                "original_verifier_digest": DIGEST, "tolerance_identity": "retained-key-nine-k-exact-v1",
                "archive_digests": dict(policy_inputs.HISTORICAL_ARCHIVE_DIGESTS),
                "historical_inputs": {"series_root": "series", "micro_json": "inputs/micro.json",
                                      "f1_receipt": "inputs/f1.json", "micro_digest": DIGEST},
                "policy_inputs_digest": payload["inputs_digest"], "raw_series_root_digest": payload["raw_series_root_digest"],
                "statistics_digest": payload["statistics_digest"], "rows": payload["rows"]}

    def test_nine_k_mapping_has_concrete_supported_schema(self):
        mapping = self.mapping()
        self.assertEqual(historical._validate_mapping(mapping), mapping)

    def test_partial_repeated_or_unapproved_mapping_fails(self):
        for change in ("partial", "repeat", "escape", "archive", "tolerance"):
            with self.subTest(change=change):
                mapping = self.mapping()
                if change == "partial": mapping["rows"].pop()
                if change == "repeat": mapping["rows"][-1] = copy.deepcopy(mapping["rows"][0])
                if change == "escape": mapping["historical_inputs"]["series_root"] = "../current-series"
                if change == "archive": mapping["archive_digests"].pop(next(iter(mapping["archive_digests"])))
                if change == "tolerance": mapping["tolerance_identity"] = "close-enough"
                with self.assertRaises(BenchError): historical._validate_mapping(mapping)

    def test_missing_authentic_material_is_unavailable_not_unconditional_family_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(BenchError) as raised:
                historical.open_verified_historical_parity(study_id=STUDY_RETAINED_KEY, archive_root=root,
                    mapping_path=root / "missing.json", independently_approved_mapping_digest=DIGEST,
                    approval_source_root=root / "approvals", approval_source_identity="review")
        self.assertEqual(raised.exception.code, "BM_EVIDENCE_UNAVAILABLE")
        self.assertEqual(raised.exception.field_path, "historical_parity")

    def test_historical_filesystem_replay_positive_reopen_and_tamper(self):
        """Use real JSON paths/math; archive authentication and old verifier are test doubles."""

        from quervant_bench.official import admission

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = support.make_retained_key_fixture(root)
            micro_path = root / "micro.json"
            micro_path.write_bytes(canonical_document_bytes(micro_table()))
            micro_digest = "sha256:" + hashlib.sha256(micro_path.read_bytes()).hexdigest()
            f1_path = root / "f1.json"
            f1_path.write_bytes(canonical_document_bytes({
                "t7_commit": policy_inputs.F1_COMMIT,
                "files": {name: hashlib.sha256((support.REPO_ROOT / "benchmarks/pr15i_d3_c_t7" / name).read_bytes()).hexdigest()
                          for name in ("analysis.py", "policy.py", "verify_derived.py", "freeze.py")},
            }))
            receipt_digest = "sha256:" + hashlib.sha256(f1_path.read_bytes()).hexdigest()
            audits = {}
            for campaign, digest in policy_inputs.HISTORICAL_ARCHIVE_DIGESTS.items():
                directory = fixture.raw_root / campaign
                members = {name: admission.sha256_regular_file(directory, name, max_bytes=admission.MAX_RAW_MEMBER_BYTES)[0].removeprefix("sha256:")
                           for name in admission.walk_raw_members(directory)}
                sidecar = root / f"{campaign}.tar.gz.sha256"
                sidecar.write_bytes(canonical_document_bytes({"members": members}))
                audits[campaign] = historical.ArchiveAudit(campaign, digest, len(members), policy_inputs.PROTOCOL_SHA256, DIGEST)
            report = {"verification": "PASS", "full_series": True, "provenance_consistent": True,
                      "control": "ACQUIRED_VERIFIED", "campaigns": ["ACQUIRED_VERIFIED", "ACQUIRED_VERIFIED"]}
            verifier = admission.OriginalVerifierOutcome("PASS", "deterministic-test-double", report)
            with patch.object(policy_inputs, "F1_RECEIPT_DIGEST", receipt_digest), \
                 patch.object(historical, "audit_retained_key_archive", side_effect=lambda _root, campaign: audits[campaign]), \
                 patch.object(admission.OriginalVerifier, "verify_retained_key_series", return_value=verifier):
                inputs = policy_inputs.open_historical_retained_policy_inputs(
                    series_root=fixture.raw_root, archive_root=root, micro_json=micro_path,
                    expected_micro_sha256=micro_digest, f1_receipt=f1_path, source_root=support.REPO_ROOT)
                self.assertEqual(inputs.scope, "historical_replay")
                with self.assertRaises(BenchError):
                    policy_inputs.reverify_retained_policy_inputs(inputs, for_production=True)
                admitted, memory = policy_inputs.reverify_retained_policy_inputs(inputs, for_production=False)
                expected = policy_reference.reference_retained_policy(admitted, memory, inputs.inputs_digest)
                mapping = self.mapping()
                mapping.update(policy_inputs_digest=inputs.inputs_digest,
                               raw_series_root_digest=admitted.raw_series_root_digest,
                               statistics_digest=expected["statistics_digest"], rows=expected["rows"],
                               original_verifier_digest=support.verifier_digest("benchmarks/pr15i_d3_c/verify.py"))
                mapping["historical_inputs"] = {"series_root": "raw", "micro_json": "micro.json",
                                                 "f1_receipt": "f1.json", "micro_digest": micro_digest}
                candidate = root / "candidate"
                candidate.mkdir()
                mapping_path = candidate / "mapping.json"
                mapping_path.write_bytes(canonical_document_bytes(mapping))
                approved = content_digest(mapping)
                approvals = root / "approvals"
                approvals.mkdir()
                (approvals / "review.parity-approval.json").write_bytes(canonical_document_bytes({
                    "kind": historical.PARITY_APPROVAL_KIND, "schema_version": 1, "study_id": STUDY_RETAINED_KEY,
                    "approved_mapping_digest": approved, "independent_review_id": "fixture-independent-review",
                    "approved_at_utc": "2026-01-01T00:00:00Z",
                }))
                parity = historical.open_verified_historical_parity(study_id=STUDY_RETAINED_KEY,
                    archive_root=root, mapping_path=mapping_path, independently_approved_mapping_digest=approved,
                    approval_source_root=approvals, approval_source_identity="review", repo_root=support.REPO_ROOT)
                self.assertFalse(parity.fixture_only)
                self.assertEqual(historical.require_verified_historical_parity(parity, study_id=STUDY_RETAINED_KEY), parity)
                raw_slot = fixture.raw_root / policy_inputs.CAMPAIGNS[0] / "raw/slots/slot-01.json"
                pristine = raw_slot.read_bytes()
                try:
                    changed = json.loads(pristine)
                    changed["lanes"][0]["samples_ns"][0] += 1
                    raw_slot.write_bytes(canonical_document_bytes(changed))
                    with self.assertRaises(BenchError) as raised:
                        historical.require_verified_historical_parity(parity, study_id=STUDY_RETAINED_KEY)
                    self.assertEqual(raised.exception.field_path, "archive")
                finally:
                    raw_slot.write_bytes(pristine)
