"""Adversarial mutation matrix for BM-05 (V-MUT / V-IO)."""

from __future__ import annotations

import copy
import dataclasses
import decimal
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quervant_bench.analysis.contracts import validate_policy_decision
from quervant_bench.config.codec import (
    canonical_document_bytes,
    content_digest,
    decode_text,
    loads_json,
)
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCOPE_MISMATCH,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.tests.analysis_support import (
    EXPERIMENT_ID,
    SealedRun,
    build_isolated_catalog,
    cached_derivation,
    cached_sealed_run,
    experiment_root,
    load_policy_profile,
    load_resource_observations,
)
from quervant_bench.verification import reference_input, verify_synthetic_run
from quervant_bench.verification.contracts import CHECK_IDS
from quervant_bench.verification.reference_input import raw_digest

THREE_ARM_VALUES = {
    ("baseline", "common-query"): (1_000_000, 1_000_000, 1_000_000),
    ("baseline", "rare-query"): (1_000_000, 1_000_000, 1_000_000),
    ("alpha", "common-query"): (1_050_000, 1_050_000, 1_050_000),
    ("alpha", "rare-query"): (900_000, 900_000, 900_000),
    ("beta", "common-query"): (900_000, 900_000, 900_000),
    ("beta", "rare-query"): (800_000, 800_000, 800_000),
}


def _snapshot(*roots: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                snapshot[str(path)] = path.read_bytes()
    return snapshot


def _clone(run: SealedRun, root: Path) -> Path:
    target = root / run.run_dir.name
    shutil.copytree(run.run_dir, target)
    return target


def _verify(run: SealedRun, analysis: dict, policy: dict, *, run_dir: Path | None = None):
    return verify_synthetic_run(
        bundle=run.bundle,
        run_dir=run.run_dir if run_dir is None else run_dir,
        scenario_root=run.evidence,
        profiles_root=experiment_root(),
        resources_root=experiment_root(),
        analysis_document=analysis,
        policy_document=policy,
    )


class MutationMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sealed = cached_sealed_run()
        cls.analysis, cls.policy = cached_derivation()

    def _assert_rejected(self, code: str, *, run_dir: Path | None = None, analysis=None, policy=None):
        with self.assertRaises(BenchError) as caught:
            _verify(
                self.sealed,
                self.analysis if analysis is None else analysis,
                self.policy if policy is None else policy,
                run_dir=run_dir,
            )
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_v_mut_01_untouched_valid_pair_is_verified(self) -> None:
        assessment = _verify(self.sealed, self.analysis, self.policy)
        self.assertEqual(assessment.status, "verified-synthetic")
        self.assertEqual(assessment.check_ids, CHECK_IDS)
        self.assertEqual(assessment.analysis_digest, content_digest(self.analysis))
        self.assertEqual(assessment.policy_digest, content_digest(self.policy))
        self.assertEqual(
            assessment.source_seal_digest, self.analysis["source_seal_digest"]
        )

    def test_v_mut_02_repeat_invocation_is_idempotent_and_read_only(self) -> None:
        before = _snapshot(self.sealed.run_dir, self.sealed.evidence, experiment_root())
        first = _verify(self.sealed, self.analysis, self.policy)
        second = _verify(self.sealed, self.analysis, self.policy)
        self.assertEqual(first, second)
        self.assertEqual(
            _snapshot(self.sealed.run_dir, self.sealed.evidence, experiment_root()),
            before,
        )

    def test_v_mut_03_ambient_decimal_context_cannot_change_the_outcome(self) -> None:
        context = decimal.getcontext()
        original = (context.prec, context.rounding)
        try:
            baseline = _verify(self.sealed, self.analysis, self.policy)
            context.prec = 7
            context.rounding = decimal.ROUND_DOWN
            perturbed = _verify(self.sealed, self.analysis, self.policy)
        finally:
            context.prec, context.rounding = original
        self.assertEqual(baseline, perturbed)

    def test_v_mut_04_missing_treatment_envelope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _clone(self.sealed, Path(temporary))
            target = next(run_dir.glob("slots/treatment-*/block-*/slot-*/*.json"))
            target.unlink()
            self._assert_rejected(BM_IDENTITY_INVALID, run_dir=run_dir)

    def test_v_mut_05_extra_unsealed_treatment_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _clone(self.sealed, Path(temporary))
            target = next(run_dir.glob("slots/treatment-*/block-*/slot-*"))
            (target / "extra.json").write_bytes(b"{}\n")
            self._assert_rejected(BM_UNSAFE_INPUT, run_dir=run_dir)

    def test_v_mut_06_treatment_byte_alteration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _clone(self.sealed, Path(temporary))
            target = next(run_dir.glob("slots/treatment-*/block-*/slot-*/*.json"))
            target.write_bytes(target.read_bytes() + b" ")
            self._assert_rejected(BM_IDENTITY_INVALID, run_dir=run_dir)

    def test_v_mut_06b_post_read_integrity_detects_a_race(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _clone(self.sealed, Path(temporary))
            evidence = reference_input.collect_reference_evidence(
                bundle=self.sealed.bundle,
                run_dir=run_dir,
                scenario_root=self.sealed.evidence,
            )
            target = run_dir / evidence.consumed[0][0]
            target.write_bytes(target.read_bytes() + b" ")
            with self.assertRaises(BenchError) as caught:
                reference_input.verify_consumed_files(run_dir, evidence.consumed)
            self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_v_mut_07_altered_envelope_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _clone(self.sealed, Path(temporary))
            relative = sorted(
                run_dir.glob("slots/treatment-*/block-*/slot-*/*.json")
            )[0].relative_to(run_dir).as_posix()
            document = loads_json(decode_text((run_dir / relative).read_bytes()))
            document["arm_id"] = "candidate" if document["arm_id"] == "baseline" else "baseline"
            payload = canonical_document_bytes(document)
            (run_dir / relative).write_bytes(payload)
            seal_document = loads_json(
                decode_text((run_dir / "seal.json").read_bytes())
            )
            for entry in seal_document["files"]:
                if entry["path"] == relative:
                    entry["digest"] = raw_digest(payload)
                    entry["byte_length"] = len(payload)
            (run_dir / "seal.json").write_bytes(
                canonical_document_bytes(seal_document)
            )
            self._assert_rejected(BM_IDENTITY_INVALID, run_dir=run_dir)

    def test_v_mut_08_wrong_profile_binding_is_rejected(self) -> None:
        forged = copy.deepcopy(self.analysis)
        forged["analysis_profile_digest"] = "sha256:" + "9" * 64
        self._assert_rejected(BM_IDENTITY_INVALID, analysis=forged)
        missing = copy.deepcopy(self.analysis)
        del missing["analysis_profile_digest"]
        self._assert_rejected(BM_SCHEMA_INVALID, analysis=missing)
        policy_forged = copy.deepcopy(self.policy)
        policy_forged["policy_profile_digest"] = "sha256:" + "8" * 64
        self._assert_rejected(BM_IDENTITY_INVALID, policy=policy_forged)

    def test_v_mut_09_forged_raw_point_is_rejected(self) -> None:
        forged = copy.deepcopy(self.analysis)
        forged["campaigns"][0]["lanes"][0]["candidates"][0]["raw_point_effect"] = (
            "0.799999999999"
        )
        self._assert_rejected(BM_IDENTITY_INVALID, analysis=forged)

    def test_v_mut_10_internally_consistent_forged_ci_is_rejected(self) -> None:
        forged = copy.deepcopy(self.analysis)
        candidate = forged["campaigns"][0]["lanes"][0]["candidates"][0]
        value = decimal.Decimal(candidate["ci_high"]) + decimal.Decimal("0.000000000001")
        candidate["ci_high"] = format(value, "f")
        self._assert_rejected(BM_IDENTITY_INVALID, analysis=forged)

    def test_v_mut_10b_forged_stream_digest_is_rejected(self) -> None:
        forged = copy.deepcopy(self.analysis)
        forged["campaigns"][0]["lanes"][0]["candidates"][0][
            "bootstrap_stream_digest"
        ] = "sha256:" + "7" * 64
        self._assert_rejected(BM_IDENTITY_INVALID, analysis=forged)

    def test_v_mut_11_forged_exclusion_ledger_is_rejected(self) -> None:
        forged = copy.deepcopy(self.analysis)
        forged["campaigns"][0]["lanes"][0]["exclusion_ledger"][0]["arm_spreads"][0][
            "spread"
        ] = "1.000000000001"
        self._assert_rejected(BM_IDENTITY_INVALID, analysis=forged)
        inconsistent = copy.deepcopy(self.analysis)
        inconsistent["campaigns"][0]["lanes"][0]["exclusion_ledger"][0]["status"] = (
            "excluded"
        )
        self._assert_rejected(BM_IDENTITY_INVALID, analysis=inconsistent)

    def test_v_mut_12_changed_policy_outcome_is_rejected(self) -> None:
        forged = copy.deepcopy(self.policy)
        lane = forged["candidate_results"][0]["campaign_results"][0]["lanes"][0]
        lane["status"] = "unproven"
        lane["reasons"] = ["TARGET_UNPROVEN"]
        self._assert_rejected(BM_IDENTITY_INVALID, policy=forged)
        limit = copy.deepcopy(self.policy)
        limit["candidate_results"][0]["campaign_results"][0]["lanes"][0][
            "ci_limit"
        ] = "1.050000000000"
        self._assert_rejected(BM_IDENTITY_INVALID, policy=limit)

    def test_v_mut_13_coherent_forged_resource_decision_is_rejected(self) -> None:
        forged = copy.deepcopy(self.policy)
        for candidate in forged["candidate_results"]:
            candidate["status"] = "INCONCLUSIVE"
            candidate["worst_campaign_gm"] = None
            for campaign in candidate["campaign_results"]:
                campaign["status"] = "INCONCLUSIVE"
        forged["ranking"] = []
        forged["selected_arm_id"] = None
        forged["decision_status"] = "INCONCLUSIVE"
        forged["reasons"] = [
            {
                "candidate_arm_id": "candidate",
                "campaign_index": index,
                "lane_id": None,
                "code": "MISSING_RESOURCE",
            }
            for index in (0, 1)
        ]
        validate_policy_decision(
            forged,
            self.sealed.bundle,
            load_policy_profile(),
            content_digest(self.analysis),
            load_resource_observations().digest,
        )
        self._assert_rejected(BM_IDENTITY_INVALID, policy=forged)

    def test_v_mut_17_symlink_and_oversize_inputs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _clone(self.sealed, Path(temporary))
            target = sorted(run_dir.glob("slots/treatment-*/block-*/slot-*/*.json"))[0]
            other = target.with_name("other.json")
            other.write_bytes(b"{}\n")
            target.unlink()
            target.symlink_to(other)
            self._assert_rejected(BM_UNSAFE_INPUT, run_dir=run_dir)
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _clone(self.sealed, Path(temporary))
            target = sorted(run_dir.glob("slots/treatment-*/block-*/slot-*/*.json"))[0]
            target.write_bytes(b"x" * 1_048_577)
            self._assert_rejected(BM_UNSAFE_INPUT, run_dir=run_dir)

    def test_v_mut_18_scope_promotion_is_refused_before_reads(self) -> None:
        promoted = dataclasses.replace(
            self.sealed.bundle,
            adapter_document={
                **dict(self.sealed.bundle.adapter_document),
                "evidence_origin": "official",
                "qualification_scope": "official",
            },
        )
        with self.assertRaises(BenchError) as caught:
            verify_synthetic_run(
                bundle=promoted,
                run_dir=self.sealed.run_dir,
                scenario_root=self.sealed.evidence,
                profiles_root=experiment_root(),
                resources_root=experiment_root(),
                analysis_document=self.analysis,
                policy_document=self.policy,
            )
        self.assertEqual(caught.exception.code, BM_SCOPE_MISMATCH)

    def test_v_mut_16_deterministic_race_through_the_io_primitive_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _clone(self.sealed, Path(temporary))
            target = sorted(run_dir.glob("slots/treatment-*/block-*/slot-*/*.json"))[
                0
            ].relative_to(run_dir).as_posix()
            original = reference_input._read_bounded
            reads = {"count": 0}

            def racing(root: Path, relative: str, limit: int) -> bytes:
                if relative == target:
                    reads["count"] += 1
                    if reads["count"] == 2:
                        (root / relative).write_bytes((root / relative).read_bytes() + b" ")
                return original(root, relative, limit)

            with mock.patch.object(reference_input, "_read_bounded", racing):
                self._assert_rejected(BM_IDENTITY_INVALID, run_dir=run_dir)
            self.assertEqual(reads["count"], 2)

    def test_no_persistent_state_or_new_file_on_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _clone(self.sealed, Path(temporary))
            before = _snapshot(run_dir)
            forged = copy.deepcopy(self.analysis)
            forged["campaigns"][0]["lanes"][0]["candidates"][0]["raw_point_effect"] = (
                "0.799999999999"
            )
            self._assert_rejected(BM_IDENTITY_INVALID, run_dir=run_dir, analysis=forged)
            self.assertEqual(_snapshot(run_dir), before)


class MultiCandidateForgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        root = Path(cls._temporary.name)
        cls.catalog = build_isolated_catalog(
            root,
            experiment_id=EXPERIMENT_ID,
            arms=("alpha", "baseline", "beta"),
            baseline_arm_id="baseline",
            candidate_order=("alpha", "beta"),
            tie_preference=("alpha", "beta"),
            scenario_values=THREE_ARM_VALUES,
            blocks=6,
        )
        cls.sealed_run = SealedRun(bundle=cls.catalog["bundle"], source_root=cls.catalog["experiment_root"])
        from quervant_bench.analysis.derive import analyze_synthetic_run

        cls.analysis, cls.policy = analyze_synthetic_run(
            bundle=cls.catalog["bundle"],
            run_dir=cls.sealed_run.run_dir,
            scenario_root=cls.sealed_run.evidence,
            profiles_root=cls.catalog["experiment_root"],
            resources_root=cls.catalog["experiment_root"],
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.sealed_run.close()
        cls._temporary.cleanup()

    def test_v_mut_14_15_rewritten_ranking_and_selection_are_rejected(self) -> None:
        forged = copy.deepcopy(self.policy)
        forged["candidate_results"][0]["worst_campaign_gm"] = "0.500000000000"
        forged["candidate_results"][1]["worst_campaign_gm"] = "0.900000000000"
        forged["ranking"] = [
            {"arm_id": "alpha", "worst_campaign_gm": "0.500000000000"},
            {"arm_id": "beta", "worst_campaign_gm": "0.900000000000"},
        ]
        forged["selected_arm_id"] = "alpha"
        forged["decision_status"] = "SELECTED_ELIGIBLE_SYNTHETIC"
        from quervant_bench.analysis.policy import (
            read_policy_profile,
            read_resource_observations,
        )

        profile = read_policy_profile(self.catalog["experiment_root"], self.catalog["bundle"])
        resources = read_resource_observations(
            self.catalog["experiment_root"], self.catalog["bundle"]
        )
        validate_policy_decision(
            forged,
            self.catalog["bundle"],
            profile,
            content_digest(self.analysis),
            resources.digest,
        )
        with self.assertRaises(BenchError) as caught:
            verify_synthetic_run(
                bundle=self.catalog["bundle"],
                run_dir=self.sealed_run.run_dir,
                scenario_root=self.sealed_run.evidence,
                profiles_root=self.catalog["experiment_root"],
                resources_root=self.catalog["experiment_root"],
                analysis_document=self.analysis,
                policy_document=forged,
            )
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
