"""AN-BIND-01…05 and AN-CAN-01…06, AN-CAN-08: profile bindings and canonical bytes.

Input contracts are exercised against the real frozen companion profiles, then
mutated in every way that must reject. Output canonicalisation is exercised on the
single process-wide real derivation.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from quervant_bench.analysis.contracts import (
    ANALYSIS_KIND,
    require_bounded_document,
    validate_analysis_result,
)
from quervant_bench.analysis.policy import (
    read_policy_profile,
    read_resource_observations,
    validate_policy_profile,
    validate_resource_observations,
)
from quervant_bench.analysis.profiles import (
    read_analysis_profile,
    validate_analysis_profile,
)
from quervant_bench.config.codec import (
    canonical_document_bytes,
    canonical_payload_bytes,
    content_digest,
    loads_json,
)
from quervant_bench.config.errors import (
    BM_DUPLICATE_KEY,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCHEMA_UNSUPPORTED,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.tests.analysis_support import (
    analysis_profile_document,
    cached_derivation,
    experiment_root,
    load_bundle,
    policy_profile_document,
    resource_document,
    write_canonical,
)


class ProfileBindingTests(unittest.TestCase):
    """AN-BIND-01…05."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_bundle()

    def test_an_bind_01_analysis_profile_matches_the_experiment_binding(self) -> None:
        profile = read_analysis_profile(experiment_root(), self.bundle)
        binding = self.bundle.experiment.analysis
        self.assertEqual(profile.analysis_id, binding.analysis_id)
        self.assertEqual(profile.analysis_version, binding.analysis_version)
        self.assertEqual(profile.digest, binding.analysis_digest)
        self.assertEqual(profile.digest, content_digest(analysis_profile_document()))
        self.assertEqual(profile.estimator_id, self.bundle.protocol_document["statistics"]["method_id"])
        self.assertEqual(
            profile.bootstrap.resamples,
            self.bundle.protocol_document["statistics"]["resamples"],
        )
        self.assertEqual(
            profile.bootstrap.interval_id,
            self.bundle.protocol_document["statistics"]["interval_id"],
        )
        self.assertEqual(
            profile.exclusion.minimum_retained_blocks,
            self.bundle.protocol_document["exclusion"]["minimum_retained_blocks"],
        )

    def test_an_bind_02_policy_profile_matches_both_bindings(self) -> None:
        profile = read_policy_profile(experiment_root(), self.bundle)
        policy_binding = self.bundle.experiment.policy
        protocol_binding = self.bundle.protocol.policy
        for binding in (policy_binding, protocol_binding):
            self.assertEqual(profile.policy_id, binding.policy_id)
            self.assertEqual(profile.policy_version, binding.policy_version)
            self.assertEqual(profile.digest, binding.policy_digest)
        self.assertEqual(profile.digest, content_digest(policy_profile_document()))
        self.assertEqual(
            profile.metric_direction,
            self.bundle.adapter.measurement_envelope.direction,
        )
        self.assertEqual(profile.candidate_order, ("candidate",))
        self.assertEqual(profile.selection.ranking_lanes, ("common-query", "rare-query"))

    def test_an_bind_03_mutated_profile_bytes_reject(self) -> None:
        document = analysis_profile_document()
        document["bootstrap"]["resamples"] = 1001
        with self.assertRaises(BenchError) as caught:
            validate_analysis_profile(document, self.bundle)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "bootstrap.resamples")

        policy = policy_profile_document()
        policy["selection"]["tie_relative_delta"] = "0.040000000000"
        with self.assertRaises(BenchError) as policy_caught:
            validate_policy_profile(policy, self.bundle)
        self.assertEqual(policy_caught.exception.code, BM_IDENTITY_INVALID)

    def test_an_bind_03_mutated_analysis_id_rejects(self) -> None:
        document = analysis_profile_document()
        document["analysis_id"] = "paired-block-analysis-two"
        with self.assertRaises(BenchError) as caught:
            validate_analysis_profile(document, self.bundle)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_an_bind_04_non_canonical_profile_bytes_reject(self) -> None:
        source = experiment_root() / "analysis-profile.v1.json"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pretty = json.dumps(
                analysis_profile_document(), indent=2, sort_keys=True
            ).encode("utf-8")
            (root / "analysis-profile.v1.json").write_bytes(pretty)
            with self.assertRaises(BenchError) as caught:
                read_analysis_profile(root, self.bundle)
            self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)
            self.assertNotEqual(pretty, source.read_bytes())

    def test_an_bind_04_non_canonical_resource_bytes_reject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "resource-observations.v1.json").write_bytes(
                json.dumps(resource_document(), indent=2).encode("utf-8")
            )
            with self.assertRaises(BenchError) as caught:
                read_resource_observations(root, self.bundle)
            self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

    def test_an_bind_05_schema_extras_and_wrong_types_reject(self) -> None:
        cases = {
            "extra-top-level-key": lambda doc: doc.update({"surprise": True}),
            "extra-bootstrap-key": lambda doc: doc["bootstrap"].update({"extra": 1}),
            "missing-exclusion-key": lambda doc: doc["exclusion"].pop("ruleset_id"),
            "float-cap": lambda doc: doc["exclusion"]["per_lane_caps"][0].update(
                {"max_within_arm_ratio": 1.5}
            ),
            "bool-confidence": lambda doc: doc["bootstrap"].update(
                {"confidence_basis_points": True}
            ),
            "unknown-estimator": lambda doc: doc.update(
                {"estimator_id": "invented-estimator-v1"}
            ),
            "unsupported-version": lambda doc: doc.update({"schema_version": 2}),
            "duplicate-lane-cap": lambda doc: doc["exclusion"]["per_lane_caps"].append(
                dict(doc["exclusion"]["per_lane_caps"][0])
            ),
            "missing-lane-cap": lambda doc: doc["exclusion"]["per_lane_caps"].pop(),
            "cap-below-one": lambda doc: doc["exclusion"]["per_lane_caps"][0].update(
                {"max_within_arm_ratio": "0.900000000000"}
            ),
            "cap-above-hundred": lambda doc: doc["exclusion"]["per_lane_caps"][0].update(
                {"max_within_arm_ratio": "100.000000000001"}
            ),
            "resamples-too-small": lambda doc: doc["bootstrap"].update({"resamples": 99}),
            "resamples-too-large": lambda doc: doc["bootstrap"].update({"resamples": 20001}),
            "precision-mismatch": lambda doc: doc.update(
                {"output_precision_decimal_places": 10}
            ),
            "asymmetric-exclusion": lambda doc: doc["exclusion"].update(
                {"symmetric_by_lane_and_block": False}
            ),
            "scope-promotion": lambda doc: doc.update(
                {"evidence_origin": "real", "qualification_scope": "official"}
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                document = copy.deepcopy(analysis_profile_document())
                mutate(document)
                with self.assertRaises(BenchError) as caught:
                    validate_analysis_profile(document, self.bundle)
                self.assertIn(
                    caught.exception.code,
                    {BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BM_SCHEMA_UNSUPPORTED},
                )

    def test_an_bind_05_duplicate_json_keys_reject(self) -> None:
        with self.assertRaises(BenchError) as caught:
            loads_json('{"a":1,"a":2}')
        self.assertEqual(caught.exception.code, BM_DUPLICATE_KEY)

    def test_an_bind_05_missing_profile_file_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(BenchError) as caught:
                read_analysis_profile(Path(temporary), self.bundle)
            self.assertIn(
                caught.exception.code,
                {BM_FILE_MISSING, BM_SCHEMA_INVALID, BM_UNSAFE_INPUT},
            )


class CanonicalOutputTests(unittest.TestCase):
    """AN-CAN-01…06 and AN-CAN-08."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.analysis, cls.policy = cached_derivation()

    def test_an_can_01_outputs_are_canonical_and_sorted(self) -> None:
        payload = canonical_payload_bytes(self.analysis)
        document = loads_json(payload.decode("utf-8"))
        self.assertEqual(document, self.analysis)
        self.assertEqual(canonical_document_bytes(document), payload + b"\n")
        self.assertNotIn(b", ", payload)
        # Keys are serialised in ascending order, arrays keep their declared order.
        raw = payload.decode("utf-8")
        self.assertTrue(raw.startswith('{"algorithm_id":"sha256-rejection-paired-block-v1"'))
        self.assertLess(raw.index('"analysis_id"'), raw.index('"baseline_arm_id"'))
        self.assertEqual(self.analysis["candidate_ids"], ["candidate"])
        self.assertEqual(self.analysis["lane_ids"], ["rare-query", "common-query"])

    def test_an_can_02_duplicate_keys_and_non_finite_numbers_reject(self) -> None:
        for text in (
            '{"seed":1,"seed":2}',
            '{"seed":NaN}',
            '{"seed":Infinity}',
        ):
            with self.subTest(text=text):
                with self.assertRaises(BenchError):
                    loads_json(text)

    def test_an_can_03_changed_policy_changes_or_rejects(self) -> None:
        bundle = load_bundle()
        document = policy_profile_document()
        document["targets"][0]["point_upper"] = "0.940000000000"
        with self.assertRaises(BenchError) as caught:
            validate_policy_profile(document, bundle)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertNotEqual(
            content_digest(document), bundle.experiment.policy.policy_digest
        )

    def test_an_can_04_changed_resources_change_the_digest(self) -> None:
        document = resource_document()
        baseline_digest = content_digest(document)
        document["records"][0]["value_bytes"] = 1048577
        self.assertNotEqual(content_digest(document), baseline_digest)
        self.assertEqual(
            self.policy["resource_observations_digest"], baseline_digest
        )

    def test_an_can_05_output_digests_are_stable_for_same_inputs(self) -> None:
        analysis, policy = cached_derivation()
        self.assertEqual(canonical_document_bytes(analysis), canonical_document_bytes(self.analysis))
        self.assertEqual(canonical_document_bytes(policy), canonical_document_bytes(self.policy))
        self.assertEqual(
            policy["analysis_digest"], content_digest(self.analysis)
        )

    def test_an_can_06_serialization_is_process_independent(self) -> None:
        expected = content_digest(self.analysis)
        script = (
            "import json,sys\n"
            "from quervant_bench.config.codec import content_digest\n"
            "document = json.load(sys.stdin)\n"
            "print(content_digest(document))\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            input=json.dumps(self.analysis),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), expected)

    def test_an_can_08_no_float_or_non_finite_values_in_outputs(self) -> None:
        def walk(value, path):
            if isinstance(value, dict):
                for key, child in value.items():
                    walk(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{path}[{index}]")
            elif isinstance(value, bool):
                return
            elif isinstance(value, float):
                self.fail(f"{path} is a JSON float")
            elif isinstance(value, int):
                return
            elif isinstance(value, str):
                return
            elif value is None:
                return
            else:  # pragma: no cover - defensive
                self.fail(f"{path} has an unsupported type {type(value)!r}")

        walk(self.analysis, "analysis")
        walk(self.policy, "policy")
        with self.assertRaises(BenchError):
            canonical_payload_bytes({"value": float("nan")})

    def test_an_can_08_output_budget_is_enforced(self) -> None:
        require_bounded_document(self.analysis, ANALYSIS_KIND)
        oversized = {"payload": "x" * (1024 * 1024 + 1)}
        with self.assertRaises(BenchError) as caught:
            require_bounded_document(oversized, "oversized")
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

    def test_an_can_01_reading_the_profile_from_a_copy_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy(
                experiment_root() / "analysis-profile.v1.json",
                root / "analysis-profile.v1.json",
            )
            profile = read_analysis_profile(root, load_bundle())
            self.assertEqual(profile.digest, content_digest(analysis_profile_document()))
            write_canonical(root / "analysis-profile.v1.json", analysis_profile_document())
            self.assertEqual(
                read_analysis_profile(root, load_bundle()).digest, profile.digest
            )


class CampaignAndBlockInventoryTests(unittest.TestCase):
    """FX04-INV-01…04, FX04-INV-08…12: protocol-declared inventory is mandatory."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_bundle()
        cls.analysis, cls.policy = cached_derivation()
        cls.profile = read_analysis_profile(experiment_root(), cls.bundle)

    def validate(self, document):
        return validate_analysis_result(
            document, self.bundle, self.profile, self.analysis["source_seal_digest"]
        )

    def truncate_blocks(self, document, count: int) -> None:
        for campaign in document["campaigns"]:
            for lane in campaign["lanes"]:
                lane["blocks_total"] = count
                lane["exclusion_ledger"] = [
                    row for row in lane["exclusion_ledger"] if row["block"] <= count
                ]
                lane["retained_blocks"] = [
                    block for block in lane["retained_blocks"] if block <= count
                ]
                lane["excluded_blocks"] = [
                    block for block in lane["excluded_blocks"] if block <= count
                ]
                for candidate in lane["candidates"]:
                    candidate["raw_block_effects"] = [
                        entry
                        for entry in candidate["raw_block_effects"]
                        if entry["block"] <= count
                    ]
                    candidate["retained_block_effects"] = [
                        entry
                        for entry in candidate["retained_block_effects"]
                        if entry["block"] <= count
                    ]

    def test_fx04_inv_01_two_treatment_campaigns_validate(self) -> None:
        self.assertEqual(len(self.analysis["campaigns"]), 2)
        self.validate(copy.deepcopy(self.analysis))

    def test_fx04_inv_02_missing_final_campaign_rejects(self) -> None:
        document = copy.deepcopy(self.analysis)
        document["campaigns"].pop()
        with self.assertRaises(BenchError) as caught:
            self.validate(document)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "campaigns")

    def test_fx04_inv_03_empty_campaign_inventory_rejects(self) -> None:
        document = copy.deepcopy(self.analysis)
        document["campaigns"] = []
        with self.assertRaises(BenchError) as caught:
            self.validate(document)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "campaigns")

    def test_fx04_inv_04_extra_campaign_rejects(self) -> None:
        document = copy.deepcopy(self.analysis)
        extra = copy.deepcopy(document["campaigns"][-1])
        extra["campaign_index"] = 2
        document["campaigns"].append(extra)
        with self.assertRaises(BenchError) as caught:
            self.validate(document)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "campaigns")

    def test_fx04_inv_08_declared_block_count_validates(self) -> None:
        for campaign in self.analysis["campaigns"]:
            for lane in campaign["lanes"]:
                self.assertEqual(lane["blocks_total"], self.bundle.protocol.schedule.blocks)
        self.validate(copy.deepcopy(self.analysis))

    def test_fx04_inv_09_shorter_blocks_total_rejects(self) -> None:
        document = copy.deepcopy(self.analysis)
        document["campaigns"][0]["lanes"][0]["blocks_total"] = 3
        with self.assertRaises(BenchError) as caught:
            self.validate(document)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_fx04_inv_10_longer_blocks_total_rejects(self) -> None:
        document = copy.deepcopy(self.analysis)
        document["campaigns"][1]["lanes"][1]["blocks_total"] = 5
        with self.assertRaises(BenchError) as caught:
            self.validate(document)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_fx04_inv_11_internally_consistent_three_block_inventory_rejects(self) -> None:
        document = copy.deepcopy(self.analysis)
        self.truncate_blocks(document, 3)
        # The truncated document is fully self-consistent, so only the frozen
        # protocol block count can reject it.
        lane = document["campaigns"][0]["lanes"][0]
        self.assertEqual(lane["blocks_total"], 3)
        self.assertEqual([row["block"] for row in lane["exclusion_ledger"]], [1, 2, 3])
        self.assertEqual(lane["retained_blocks"], [1, 2, 3])
        self.assertEqual(
            [entry["block"] for entry in lane["candidates"][0]["raw_block_effects"]],
            [1, 2, 3],
        )
        with self.assertRaises(BenchError) as caught:
            self.validate(document)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(
            caught.exception.field_path, "campaigns[0].lanes[0].blocks_total"
        )

    def test_fx04_inv_12_zero_block_inventory_rejects(self) -> None:
        document = copy.deepcopy(self.analysis)
        self.truncate_blocks(document, 0)
        with self.assertRaises(BenchError) as caught:
            self.validate(document)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_fx04_inv_policy_campaign_count_uses_the_protocol(self) -> None:
        from quervant_bench.analysis.contracts import validate_policy_decision
        from quervant_bench.analysis.policy import (
            read_policy_profile,
            read_resource_observations,
        )

        profile = read_policy_profile(experiment_root(), self.bundle)
        resources = read_resource_observations(experiment_root(), self.bundle)
        validate_policy_decision(
            copy.deepcopy(self.policy),
            self.bundle,
            profile,
            content_digest(self.analysis),
            resources.digest,
        )
        truncated = copy.deepcopy(self.policy)
        truncated["candidate_results"][0]["campaign_results"].pop()
        with self.assertRaises(BenchError) as caught:
            validate_policy_decision(
                truncated,
                self.bundle,
                profile,
                content_digest(self.analysis),
                resources.digest,
            )
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    unittest.main()
