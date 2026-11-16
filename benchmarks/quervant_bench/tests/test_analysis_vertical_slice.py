"""AN-ING-01…05, AN-INT-01…05, AN-LIMIT-01…09, AN-SCOPE-01…06, AN-CAN-07.

The vertical slice uses the **real** BM-03 controller, adapter, store and replayer
in an external temporary root. Nothing here mocks the controller, and mutation
tests copy the sealed run before tampering so the original fixture is untouched.
"""

from __future__ import annotations

import ast
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quervant_bench.analysis.aggregation import (
    read_treatment_samples,
    require_synthetic_scope,
)
from quervant_bench.analysis.contracts import (
    MAX_ANALYSIS_RECORDS,
    require_bounded_document,
    validate_analysis_result,
    validate_policy_decision,
)
from quervant_bench.analysis.derive import analyze_synthetic_run
from quervant_bench.analysis.policy import (
    read_resource_observations,
    validate_policy_profile,
)
from quervant_bench.analysis.profiles import require_draw_budget
from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.contracts import BuildIdentity
from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCOPE_MISMATCH,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.execution.recorder import lane_relative_path
from quervant_bench.tests.analysis_support import (
    ANALYSIS_FIXTURES,
    EXECUTION_FIXTURES,
    SCENARIO_NAME,
    SealedRun,
    analysis_profile_document,
    cached_derivation,
    cached_sealed_run,
    experiment_root,
    load_analysis_profile,
    load_bundle,
    load_policy_profile,
    load_resource_observations,
    policy_profile_document,
    resource_document,
    write_canonical,
)

ANALYSIS_DIR = Path(__file__).resolve().parents[1] / "analysis"


def derive(run: SealedRun, **overrides):
    arguments = {
        "bundle": run.bundle,
        "run_dir": run.run_dir,
        "scenario_root": run.evidence,
        "profiles_root": experiment_root(),
        "resources_root": experiment_root(),
    }
    arguments.update(overrides)
    return analyze_synthetic_run(**arguments)


class IngestionTests(unittest.TestCase):
    """AN-ING-01…05."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sealed = cached_sealed_run()

    def test_an_ing_01_controls_are_not_analyzed(self) -> None:
        analysis, _policy = cached_derivation()
        indices = [campaign["campaign_index"] for campaign in analysis["campaigns"]]
        self.assertEqual(indices, [0, 1])
        self.assertEqual(self.sealed.bundle.protocol_document["campaigns"]["required_controls"], 1)
        # No control-only lane identity is ever imported into the analysis rows.
        documents = json.dumps(analysis)
        self.assertNotIn("control-left", documents)
        self.assertNotIn("control-right", documents)

    def test_an_ing_02_every_treatment_slot_is_read_exactly_once(self) -> None:
        import hashlib

        payload = (self.sealed.run_dir / "seal.json").read_bytes()
        seal = json.loads(payload)
        samples = read_treatment_samples(
            run_dir=self.sealed.run_dir, bundle=self.sealed.bundle, seal_document=seal
        )
        paths = [path for path, _digest, _length in samples.consumed]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(len(paths), 2 * 8 * 2)
        self.assertEqual(len(samples.records), 32)
        self.assertEqual(samples.campaign_indices, (0, 1))
        for _path, digest, length in samples.consumed:
            self.assertTrue(digest.startswith("sha256:"))
            self.assertGreater(length, 0)
        self.assertEqual(
            hashlib.sha256(b"").hexdigest(),
            hashlib.sha256(b"").hexdigest(),
        )

    def test_an_ing_03_extra_or_missing_records_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mutated = Path(temporary) / self.sealed.run_dir.name
            shutil.copytree(self.sealed.run_dir, mutated)
            relative = lane_relative_path("treatment", 0, 1, 1, "rare-query")
            (mutated / "extra.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(BenchError):
                analyze_synthetic_run(
                    bundle=self.sealed.bundle,
                    run_dir=mutated,
                    scenario_root=self.sealed.evidence,
                    profiles_root=experiment_root(),
                    resources_root=experiment_root(),
                )
            self.assertTrue((mutated / relative).exists())

    def test_an_ing_04_seal_hashes_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mutated = Path(temporary) / self.sealed.run_dir.name
            shutil.copytree(self.sealed.run_dir, mutated)
            relative = lane_relative_path("treatment", 1, 3, 2, "common-query")
            document = json.loads((mutated / relative).read_bytes())
            document["samples"] = [1, 1, 1]
            write_canonical(mutated / relative, document)
            with self.assertRaises(BenchError) as caught:
                analyze_synthetic_run(
                    bundle=self.sealed.bundle,
                    run_dir=mutated,
                    scenario_root=self.sealed.evidence,
                    profiles_root=experiment_root(),
                    resources_root=experiment_root(),
                )
            self.assertIn(
                caught.exception.code,
                {BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BM_EVIDENCE_UNAVAILABLE},
            )

    def test_an_ing_04_wrong_arm_in_a_lane_envelope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mutated = Path(temporary) / self.sealed.run_dir.name
            shutil.copytree(self.sealed.run_dir, mutated)
            relative = lane_relative_path("treatment", 0, 1, 1, "rare-query")
            document = json.loads((mutated / relative).read_bytes())
            document["arm_id"] = "candidate" if document["arm_id"] == "baseline" else "baseline"
            write_canonical(mutated / relative, document)
            seal = json.loads((mutated / "seal.json").read_bytes())
            self.assertIsInstance(seal, dict)
            with self.assertRaises(BenchError):
                analyze_synthetic_run(
                    bundle=self.sealed.bundle,
                    run_dir=mutated,
                    scenario_root=self.sealed.evidence,
                    profiles_root=experiment_root(),
                    resources_root=experiment_root(),
                )

    def test_an_ing_05_the_structural_replayer_is_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mutated = Path(temporary) / self.sealed.run_dir.name
            shutil.copytree(self.sealed.run_dir, mutated)
            (mutated / "seal.json").unlink()
            with self.assertRaises(BenchError) as caught:
                analyze_synthetic_run(
                    bundle=self.sealed.bundle,
                    run_dir=mutated,
                    scenario_root=self.sealed.evidence,
                    profiles_root=experiment_root(),
                    resources_root=experiment_root(),
                )
            self.assertEqual(caught.exception.code, BM_EVIDENCE_UNAVAILABLE)


class VerticalSliceTests(unittest.TestCase):
    """AN-INT-01…05 and AN-CAN-07."""

    def test_an_int_01_full_fixture_matches_the_frozen_arithmetic(self) -> None:
        analysis, policy = cached_derivation()
        replay = cached_sealed_run().replay()
        self.assertEqual(replay.slots_completed, 24)
        self.assertEqual(replay.lane_envelopes, 48)
        self.assertEqual(replay.synthetic_samples, 144)
        self.assertEqual(replay.controls_completed, 1)
        self.assertEqual(replay.treatments_completed, 2)

        expected = {
            "rare-query": ("0.800000000000", "0.800000000000"),
            "common-query": ("0.833333333333", "0.833333333333"),
        }
        self.assertEqual(len(analysis["campaigns"]), 2)
        for campaign in analysis["campaigns"]:
            for lane in campaign["lanes"]:
                self.assertEqual(lane["blocks_total"], 4)
                self.assertEqual(lane["retained_blocks"], [1, 2, 3, 4])
                self.assertEqual(lane["excluded_blocks"], [])
                candidate = lane["candidates"][0]
                point, endpoint = expected[lane["lane_id"]]
                self.assertEqual(candidate["raw_point_effect"], point)
                self.assertEqual(candidate["retained_point_effect"], point)
                self.assertEqual(candidate["ci_low"], endpoint)
                self.assertEqual(candidate["ci_high"], endpoint)
                self.assertEqual(candidate["status"], "analyzed")
        self.assertEqual(policy["selected_arm_id"], "candidate")
        self.assertEqual(policy["decision_status"], "SELECTED_ELIGIBLE_SYNTHETIC")
        self.assertEqual(policy["ranking"][0]["arm_id"], "candidate")
        self.assertEqual(policy["ranking"][0]["worst_campaign_gm"], "0.816496580928")
        self.assertEqual(analysis["status"], "derived-synthetic")
        self.assertEqual(policy["status"], "derived-synthetic")

    def test_an_int_02_official_or_relabelled_input_rejects_before_reading(self) -> None:
        run = cached_sealed_run()
        real_adapter = copy.copy(run.bundle.adapter)
        object.__setattr__(
            real_adapter,
            "build_identity",
            BuildIdentity(
                kind="source-and-binary",
                source_digest="sha256:" + "1" * 64,
                executable_digest="sha256:" + "2" * 64,
            ),
        )
        real_bundle = copy.copy(run.bundle)
        object.__setattr__(real_bundle, "adapter", real_adapter)
        with self.assertRaises(BenchError) as caught:
            derive(run, bundle=real_bundle)
        self.assertEqual(caught.exception.code, BM_SCOPE_MISMATCH)

        with self.assertRaises(BenchError) as direct:
            require_synthetic_scope(real_bundle)
        self.assertEqual(direct.exception.code, BM_SCOPE_MISMATCH)

        relabelled = copy.copy(run.bundle)
        object.__setattr__(
            relabelled,
            "adapter_document",
            dict(run.bundle.adapter_document, qualification_scope="official"),
        )
        with self.assertRaises(BenchError) as relabelled_caught:
            require_synthetic_scope(relabelled)
        self.assertEqual(relabelled_caught.exception.code, BM_SCOPE_MISMATCH)

    def test_an_int_03_corrupt_or_changed_sealed_inputs_reject(self) -> None:
        run = cached_sealed_run()
        cases = {}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("corrupt-seal", "changed-sample", "absent-lane"):
                target = root / name
                shutil.copytree(run.run_dir, target)
                cases[name] = target
            (cases["corrupt-seal"] / "seal.json").write_text("{not json", encoding="utf-8")
            relative = lane_relative_path("treatment", 0, 1, 1, "rare-query")
            document = json.loads((cases["changed-sample"] / relative).read_bytes())
            document["samples"] = [int(value) + 1 for value in document["samples"]]
            write_canonical(cases["changed-sample"] / relative, document)
            (cases["absent-lane"] / relative).unlink()

            for name, target in cases.items():
                with self.subTest(name=name):
                    with self.assertRaises(BenchError):
                        analyze_synthetic_run(
                            bundle=run.bundle,
                            run_dir=target,
                            scenario_root=run.evidence,
                            profiles_root=experiment_root(),
                            resources_root=experiment_root(),
                        )

    def test_an_int_03_changed_frozen_protocol_rejects(self) -> None:
        run = cached_sealed_run()
        protocol_document = copy.deepcopy(run.bundle.protocol_document)
        protocol_document["statistics"]["resamples"] = 2000
        mutated = copy.copy(run.bundle)
        object.__setattr__(mutated, "protocol_document", protocol_document)
        with self.assertRaises(BenchError) as caught:
            derive(run, bundle=mutated)
        self.assertIn(
            caught.exception.code, {BM_IDENTITY_INVALID, BM_UNSAFE_INPUT}
        )

    def test_an_int_04_changed_input_during_derivation_returns_no_outputs(self) -> None:
        run = cached_sealed_run()
        with tempfile.TemporaryDirectory() as temporary:
            mutated = Path(temporary) / run.run_dir.name
            shutil.copytree(run.run_dir, mutated)
            relative = lane_relative_path("treatment", 1, 4, 1, "common-query")
            original = (mutated / relative).read_bytes()
            real_bootstrap = __import__(
                "quervant_bench.analysis.derive", fromlist=["bootstrap_interval"]
            ).bootstrap_interval
            state = {"fired": False}

            def tampering(*args, **kwargs):
                if not state["fired"]:
                    state["fired"] = True
                    document = json.loads(original)
                    document["samples"] = [value + 7 for value in document["samples"]]
                    write_canonical(mutated / relative, document)
                return real_bootstrap(*args, **kwargs)

            result = None
            with mock.patch(
                "quervant_bench.analysis.derive.bootstrap_interval", side_effect=tampering
            ):
                with self.assertRaises(BenchError) as caught:
                    result = analyze_synthetic_run(
                        bundle=run.bundle,
                        run_dir=mutated,
                        scenario_root=run.evidence,
                        profiles_root=experiment_root(),
                        resources_root=experiment_root(),
                    )
            self.assertTrue(state["fired"])
            self.assertIsNone(result)
            self.assertIn(
                caught.exception.code,
                {BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BM_EVIDENCE_UNAVAILABLE},
            )
            # The tampering is visible; BM-04 wrote nothing of its own.
            self.assertNotEqual((mutated / relative).read_bytes(), original)
            self.assertFalse((mutated / "analysis.json").exists())
            self.assertFalse((mutated / "policy.json").exists())
            self.assertFalse((experiment_root() / "analysis.json").exists())
            self.assertFalse((experiment_root() / "policy.json").exists())

    def test_an_int_05_two_derivations_are_byte_identical(self) -> None:
        run = cached_sealed_run()
        first = derive(run)
        second = derive(run)
        self.assertEqual(
            canonical_document_bytes(first[0]), canonical_document_bytes(second[0])
        )
        self.assertEqual(
            canonical_document_bytes(first[1]), canonical_document_bytes(second[1])
        )

    def test_an_int_05_canonical_outputs_are_strictly_validated(self) -> None:
        run = cached_sealed_run()
        analysis, policy = cached_derivation()
        analysis_profile = load_analysis_profile()
        policy_profile = load_policy_profile()
        observations = load_resource_observations()
        validate_analysis_result(
            analysis, run.bundle, analysis_profile, analysis["source_seal_digest"]
        )
        validate_policy_decision(
            policy,
            run.bundle,
            policy_profile,
            content_digest(analysis),
            observations.digest,
        )

    def test_an_can_07_nested_output_shapes_are_closed(self) -> None:
        run = cached_sealed_run()
        analysis, policy = cached_derivation()
        analysis_profile = load_analysis_profile()
        policy_profile = load_policy_profile()
        observations = load_resource_observations()
        seal_digest = analysis["source_seal_digest"]

        def mutate_analysis(mutator) -> None:
            document = copy.deepcopy(analysis)
            mutator(document)
            with self.assertRaises(BenchError):
                validate_analysis_result(document, run.bundle, analysis_profile, seal_digest)

        lane = lambda doc: doc["campaigns"][0]["lanes"][0]
        candidate = lambda doc: lane(doc)["candidates"][0]
        mutate_analysis(lambda doc: lane(doc).pop("blocks_total"))
        mutate_analysis(lambda doc: lane(doc).update({"retained_blocks": [1, 2]}))
        mutate_analysis(lambda doc: lane(doc).update({"excluded_blocks": [1]}))
        mutate_analysis(lambda doc: lane(doc)["exclusion_ledger"].pop())
        mutate_analysis(
            lambda doc: lane(doc)["exclusion_ledger"][0].update({"reason": "within-arm-spread"})
        )
        mutate_analysis(
            lambda doc: lane(doc)["exclusion_ledger"][0].update({"trigger_arms": ["candidate"]})
        )
        mutate_analysis(lambda doc: candidate(doc).update({"ci_low": "0.900000000000", "ci_high": "0.800000000000"}))
        mutate_analysis(lambda doc: candidate(doc).update({"ci_low": None}))
        mutate_analysis(lambda doc: candidate(doc).update({"retained_point_effect": None}))
        mutate_analysis(
            lambda doc: candidate(doc).update({"bootstrap_stream_digest": "not-a-digest"})
        )
        mutate_analysis(lambda doc: candidate(doc).update({"status": "inconclusive-insufficient-blocks"}))
        mutate_analysis(lambda doc: candidate(doc).update({"comparison_direction": "higher-is-better"}))
        mutate_analysis(lambda doc: candidate(doc)["raw_block_effects"].pop())
        mutate_analysis(lambda doc: candidate(doc)["raw_block_effects"][0].update({"extra": 1}))
        mutate_analysis(lambda doc: candidate(doc).update({"raw_point_effect": 0.8}))
        mutate_analysis(lambda doc: doc["candidate_ids"].append("baseline"))
        mutate_analysis(lambda doc: doc.update({"lane_ids": ["common-query", "rare-query"]}))
        mutate_analysis(lambda doc: doc.update({"source_seal_digest": "sha256:" + "0" * 64}))
        mutate_analysis(lambda doc: doc.update({"analysis_profile_digest": "sha256:" + "0" * 64}))
        mutate_analysis(lambda doc: doc.update({"status": "derived-real"}))
        mutate_analysis(lambda doc: doc["campaigns"].reverse())

        def mutate_policy(mutator) -> None:
            document = copy.deepcopy(policy)
            mutator(document)
            with self.assertRaises(BenchError):
                validate_policy_decision(
                    document,
                    run.bundle,
                    policy_profile,
                    content_digest(analysis),
                    observations.digest,
                )

        mutate_policy(lambda doc: doc.update({"decision_status": "ACCEPTED"}))
        mutate_policy(lambda doc: doc.update({"selected_arm_id": None}))
        mutate_policy(lambda doc: doc.update({"selected_arm_id": "baseline"}))
        mutate_policy(lambda doc: doc.update({"selected_arm_id": "ghost-agent"}))
        def unsorted_reasons(doc) -> None:
            doc["reasons"].extend(
                [
                    {
                        "candidate_arm_id": "candidate",
                        "campaign_index": 1,
                        "lane_id": "rare-query",
                        "code": "TARGET_UNPROVEN",
                    },
                    {
                        "candidate_arm_id": "candidate",
                        "campaign_index": 0,
                        "lane_id": "common-query",
                        "code": "GUARDRAIL_UNPROVEN",
                    },
                ]
            )

        mutate_policy(unsorted_reasons)
        mutate_policy(lambda doc: doc["ranking"][0].update({"worst_campaign_gm": "not-a-number"}))
        mutate_policy(lambda doc: doc["candidate_results"][0].update({"status": "MAYBE"}))
        mutate_policy(
            lambda doc: doc["candidate_results"][0]["campaign_results"][0]["lanes"][0].update(
                {"ci_operator": "eq"}
            )
        )
        mutate_policy(
            lambda doc: doc["candidate_results"][0]["campaign_results"][0]["lanes"][0].update(
                {"kind": "attribution"}
            )
        )
        mutate_policy(
            lambda doc: doc["candidate_results"][0]["campaign_results"][0].update(
                {"status": "MAYBE"}
            )
        )
        mutate_policy(lambda doc: doc.update({"policy_id": "other-policy"}))
        mutate_policy(lambda doc: doc.update({"policy_version": 2}))
        mutate_policy(lambda doc: doc["ranking"].append({"arm_id": "candidate", "worst_campaign_gm": "0.900000000000"}))

    def test_an_can_07_closed_output_record_sets_reject_extra_and_missing_fields(self) -> None:
        run = cached_sealed_run()
        analysis, policy = cached_derivation()
        analysis_profile = load_analysis_profile()
        policy_profile = load_policy_profile()
        observations = load_resource_observations()

        extra = copy.deepcopy(analysis)
        extra["approved"] = True
        with self.assertRaises(BenchError):
            validate_analysis_result(
                extra, run.bundle, analysis_profile, analysis["source_seal_digest"]
            )
        missing = copy.deepcopy(analysis)
        del missing["estimator_id"]
        with self.assertRaises(BenchError):
            validate_analysis_result(
                missing, run.bundle, analysis_profile, analysis["source_seal_digest"]
            )

        policy_extra = copy.deepcopy(policy)
        policy_extra["attestation"] = "official"
        with self.assertRaises(BenchError):
            validate_policy_decision(
                policy_extra,
                run.bundle,
                policy_profile,
                content_digest(analysis),
                observations.digest,
            )
        policy_wrong = copy.deepcopy(policy)
        policy_wrong["analysis_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(BenchError):
            validate_policy_decision(
                policy_wrong,
                run.bundle,
                policy_profile,
                content_digest(analysis),
                observations.digest,
            )
        policy_resources = copy.deepcopy(policy)
        policy_resources["resource_observations_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(BenchError):
            validate_policy_decision(
                policy_resources,
                run.bundle,
                policy_profile,
                content_digest(analysis),
                observations.digest,
            )


class LimitTests(unittest.TestCase):
    """AN-LIMIT-01…09: bounded reads, work and roots."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sealed = cached_sealed_run()

    def test_an_limit_01_profile_size_boundary(self) -> None:
        from quervant_bench.analysis.profiles import read_analysis_profile

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "analysis-profile.v1.json").write_bytes(b" " * (1024 * 1024 + 1))
            with self.assertRaises(BenchError) as caught:
                read_analysis_profile(root, self.sealed.bundle)
            self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)
            (root / "analysis-profile.v1.json").write_bytes(b" " * (1024 * 1024))
            with self.assertRaises(BenchError) as exact:
                read_analysis_profile(root, self.sealed.bundle)
            self.assertEqual(exact.exception.code, BM_SCHEMA_INVALID)

    def test_an_limit_02_output_size_boundary(self) -> None:
        require_bounded_document({"payload": "x" * 1024}, "small")
        with self.assertRaises(BenchError) as caught:
            require_bounded_document({"payload": "x" * (1024 * 1024)}, "large")
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

    def test_an_limit_03_invalid_sample_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mutated = Path(temporary) / self.sealed.run_dir.name
            shutil.copytree(self.sealed.run_dir, mutated)
            relative = lane_relative_path("treatment", 0, 2, 1, "rare-query")
            document = json.loads((mutated / relative).read_bytes())
            document["samples"] = [0, 1, 2]
            write_canonical(mutated / relative, document)
            with self.assertRaises(BenchError):
                analyze_synthetic_run(
                    bundle=self.sealed.bundle,
                    run_dir=mutated,
                    scenario_root=self.sealed.evidence,
                    profiles_root=experiment_root(),
                    resources_root=experiment_root(),
                )

    def test_an_limit_04_candidate_lane_campaign_and_block_budgets(self) -> None:
        from types import SimpleNamespace

        from quervant_bench.analysis import profiles as profiles_module

        profile = load_analysis_profile()
        bundle = self.sealed.bundle

        def wide(**overrides) -> SimpleNamespace:
            base = {
                "arms": tuple(
                    SimpleNamespace(arm_id=f"arm-{index}") for index in range(2)
                ),
                "lanes": tuple(
                    SimpleNamespace(lane_id=f"lane-{index}") for index in range(2)
                ),
                "treatments": 1,
                "blocks": 4,
            }
            base.update(overrides)
            return SimpleNamespace(
                experiment=SimpleNamespace(arms=base["arms"]),
                workload=SimpleNamespace(lanes=base["lanes"]),
                protocol=SimpleNamespace(schedule=SimpleNamespace(blocks=base["blocks"])),
                protocol_document={
                    "campaigns": {
                        "required_controls": 1,
                        "required_treatments": base["treatments"],
                        "control_contract_id": "synthetic-exact-equality",
                    },
                    "measurement": {"clock_contract_id": "synthetic-logical-clock"},
                },
            )

        self.assertEqual(require_draw_budget(profile, bundle), 16_000)
        for overrides in (
            {"arms": tuple(SimpleNamespace(arm_id=f"arm-{i}") for i in range(10))},
            {"lanes": tuple(SimpleNamespace(lane_id=f"lane-{i}") for i in range(65))},
            {"treatments": 9},
            {"blocks": 257},
        ):
            with self.subTest(overrides=list(overrides)):
                with self.assertRaises(BenchError) as caught:
                    profiles_module.require_draw_budget(profile, wide(**overrides))
                self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_an_limit_05_excessive_draw_budget_rejects_before_work(self) -> None:
        from quervant_bench.analysis.profiles import require_draw_budget

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = analysis_profile_document()
            document["bootstrap"]["resamples"] = 20_000
            write_canonical(root / "analysis-profile.v1.json", document)
            from quervant_bench.analysis.profiles import read_analysis_profile

            # The profile digest no longer matches, so the binding rejects first.
            with self.assertRaises(BenchError):
                read_analysis_profile(root, self.sealed.bundle)
        # A syntactically affordable profile still passes the preflight.
        self.assertEqual(require_draw_budget(load_analysis_profile(), self.sealed.bundle), 16_000)

    def test_an_limit_06_bad_roots_and_symlinks_reject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing"
            with self.assertRaises(BenchError) as absent:
                derive(self.sealed, profiles_root=missing)
            self.assertEqual(absent.exception.code, BM_FILE_MISSING)
            link = root / "link"
            link.symlink_to(experiment_root())
            with self.assertRaises(BenchError) as symlinked:
                derive(self.sealed, profiles_root=link)
            self.assertEqual(symlinked.exception.code, BM_UNSAFE_INPUT)
            with self.assertRaises(BenchError) as overlap:
                derive(self.sealed, profiles_root=self.sealed.run_dir)
            self.assertEqual(overlap.exception.code, BM_UNSAFE_INPUT)
            with self.assertRaises(BenchError):
                derive(self.sealed, run_dir=root / "no-run-dir")

    def test_an_limit_07_resource_document_size_boundary(self) -> None:
        from quervant_bench.analysis.policy import read_resource_observations

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "resource-observations.v1.json").write_bytes(
                b" " * (1024 * 1024 + 1)
            )
            with self.assertRaises(BenchError) as caught:
                read_resource_observations(root, self.sealed.bundle)
            self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

    def test_an_limit_08_record_budget_is_enforced(self) -> None:
        run = cached_sealed_run()
        with mock.patch("quervant_bench.analysis.derive.MAX_ANALYSIS_RECORDS", 1):
            with self.assertRaises(BenchError) as caught:
                derive(run)
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)
        self.assertGreater(MAX_ANALYSIS_RECORDS, 1)

    def test_an_limit_09_resource_value_bound(self) -> None:
        from quervant_bench.analysis.policy import validate_resource_observations

        document = resource_document()
        document["records"][0]["value_bytes"] = 2**63
        with self.assertRaises(BenchError):
            validate_resource_observations(document, self.sealed.bundle)
        document["records"][0]["value_bytes"] = 2**63 - 1
        validate_resource_observations(document, self.sealed.bundle)


class ScopeBoundaryTests(unittest.TestCase):
    """AN-SCOPE-01…06."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sealed = cached_sealed_run()

    def test_an_scope_01_run_still_exits_77_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = sorted(p.name for p in root.iterdir())
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "quervant_bench",
                    "run",
                    "--experiment",
                    "synthetic-analysis-smoke",
                    "--protocol",
                    "protocol.yaml",
                    "--out",
                    "benchmark-results/out",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(root),
                env={"PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(completed.returncode, 77, completed.stdout + completed.stderr)
            self.assertEqual(sorted(p.name for p in root.iterdir()), before)

    def test_an_scope_02_no_clock_process_or_network_in_primary_modules(self) -> None:
        forbidden = {"time", "datetime", "socket", "subprocess", "requests", "urllib"}
        primary = [
            "contracts.py",
            "profiles.py",
            "arithmetic.py",
            "pruning.py",
            "bootstrap.py",
            "aggregation.py",
            "policy.py",
            "derive.py",
        ]
        for name in primary:
            source = (ANALYSIS_DIR / name).read_text(encoding="utf-8")
            tree = ast.parse(source)
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            with self.subTest(module=name):
                self.assertEqual(imported & forbidden, set())
                self.assertNotIn("os.system", source)

    def test_an_scope_03_no_new_cli_verb(self) -> None:
        from quervant_bench import cli

        source = Path(cli.__file__).read_text(encoding="utf-8")
        for verb in ("analyze", "derive", "analysis", "policy"):
            self.assertNotIn(f"add_parser(\"{verb}\"", source)
            self.assertNotIn(f"add_parser('{verb}'", source)
        self.assertIn('"run"', source)
        self.assertIn('"inspect"', source)

    def test_an_scope_04_no_receipt_or_attestation_fields(self) -> None:
        from quervant_bench.config.contracts import validate_receipt

        _analysis, policy = cached_derivation()
        for forbidden in ("receipt_id", "attestation", "approved", "release", "gate"):
            self.assertNotIn(forbidden, policy)
        with self.assertRaises(BenchError):
            validate_receipt(policy)

    def test_an_scope_05_no_output_inside_the_sealed_run(self) -> None:
        run = cached_sealed_run()
        before = {
            path.relative_to(run.run_dir).as_posix(): path.read_bytes()
            for path in sorted(run.run_dir.rglob("*"))
            if path.is_file()
        }
        derive(run)
        after = {
            path.relative_to(run.run_dir).as_posix(): path.read_bytes()
            for path in sorted(run.run_dir.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertNotIn("analysis.json", after)
        self.assertNotIn("policy.json", after)

    def test_an_scope_06_no_acquisition_entrypoint(self) -> None:
        source = (ANALYSIS_DIR / "derive.py").read_text(encoding="utf-8")
        for forbidden in (
            "cargo bench",
            "subprocess",
            "execute_synthetic",
            "synthetic_adapter_factory",
            "open(\"w\"",
            "commit_seal",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("ExecutionStore", source)

    def test_an_scope_fixture_files_are_read_only_inputs(self) -> None:
        # The BM-03 originals must remain byte-identical to their shipped fixtures.
        for name in ("synthetic-scenario.v1.json", "golden-structural-summary.v1.json"):
            path = EXECUTION_FIXTURES / name
            self.assertTrue(path.is_file())
        self.assertTrue((ANALYSIS_FIXTURES / "bootstrap-index-golden.v1.json").is_file())
        self.assertTrue((experiment_root() / SCENARIO_NAME).is_file())

    def test_an_scope_policy_profile_is_independently_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = policy_profile_document()
            document["selection"]["tie_relative_delta"] = "0.050000000000"
            write_canonical(root / "policy-profile.v1.json", document)
            with self.assertRaises(BenchError):
                validate_policy_profile(document, self.sealed.bundle)
            shutil.copy(
                experiment_root() / "policy-profile.v1.json",
                root / "policy-profile.v1.json",
            )
            from quervant_bench.analysis.policy import read_policy_profile

            self.assertEqual(
                read_policy_profile(root, self.sealed.bundle).digest,
                content_digest(policy_profile_document()),
            )


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    unittest.main()
