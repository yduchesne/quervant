"""BM-09 current-v2 replay projection: build-binding survival and validation.

These tests exercise one retained-key campaign end to end through the *versioned*
current-v2 verifier and through the replay projection step — the two places where
the new ``raw/official-premeasurement-binaries.json`` member must survive, be
inventoried, and stay valid. They deliberately use a single campaign rather than
the nineteen-pass integration case, so this defect class fails in seconds.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.codec import canonical_document_bytes
from quervant_bench.config.errors import BM_EVIDENCE_UNAVAILABLE, BM_IDENTITY_INVALID, BenchError
from quervant_bench.official import admission, transport
from quervant_bench.official import current_retained_build as build_policy
from quervant_bench.official import current_retained_verifier as v2_verifier
from quervant_bench.tests import official_support as support
from quervant_bench.tests.test_official_admission import CurrentBaselineProductionAdmissionTests as Completion

CAMPAIGN = admission.D3C_CONTROL_NAME
BINDING = build_policy.BINDING_NAME


class RetainedReplayProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        namespace = support.REPO_ROOT / "target/pr15i-d3-c"
        namespace.mkdir(parents=True, exist_ok=True)
        cls.owned = tempfile.TemporaryDirectory(prefix="test-v2-projection-", dir=namespace)
        cls.addClassCleanup(cls.owned.cleanup)
        fixture = support.make_retained_key_fixture(Path(cls.owned.name) / "fixture")
        Completion._complete_retained_fixture(fixture)
        cls.fixture = fixture
        cls.campaign = fixture.raw_root / CAMPAIGN

    # ------------------------------------------------------------------ helpers
    def _binding_path(self, campaign: Path | None = None) -> Path:
        return (campaign or self.campaign) / "raw" / BINDING

    @staticmethod
    def _reseal(campaign: Path) -> None:
        """Re-seal a deliberately tampered campaign so a deeper check is exercised.

        Without this the campaign seal rejects the tamper first — correct, but it
        would not prove that the binding-specific validation also fails closed.
        """

        seal = support.read_json(campaign / "raw/seal.json")
        files = dict(seal["files"])
        for relative in admission.walk_raw_members(
            campaign, exclude_any_dir=("build", "indexes", "corpus", "compile-source")
        ):
            if relative in ("raw/seal.json", "verification.json"):
                continue
            files[relative] = support.hashlib.sha256((campaign / relative).read_bytes()).hexdigest()
        support.write_json(campaign / "raw/seal.json", {**seal, "files": files})

    def _policy_digest(self) -> str:
        return build_policy.read_build_binding(self._binding_path())["build_policy_digest"]

    def _project(self, original: Path | None = None) -> tuple[Path, transport.WorkingCopyProjection]:
        """Project one campaign into a fresh, confined working root.

        The projection API requires the working campaign root to live beneath the
        executing checkout's ``target/pr15i-d3-c`` namespace and to not exist yet,
        so each call owns a fresh temporary directory there and removes it after
        the test (only test-owned files are touched).
        """

        namespace = support.REPO_ROOT / "target/pr15i-d3-c"
        namespace.mkdir(parents=True, exist_ok=True)
        owned = tempfile.TemporaryDirectory(prefix="test-v2-projection-work-", dir=namespace)
        self.addCleanup(owned.cleanup)
        origin = original or self.campaign
        working_campaign = Path(owned.name) / origin.name
        projection = transport.project_retained_working_copy(
            original_campaign_root=origin,
            working_campaign_root=working_campaign,
            replay_checkout=support.REPO_ROOT,
        )
        return working_campaign, projection

    # ----------------------------------------------------------------- projection
    def test_projection_carries_the_build_binding(self) -> None:
        """The binding survives projection with its build identity intact.

        The projection relocates the argv path operands exactly as it relocates the
        build provenance they describe (the working copy has its own checkout and
        build directory), so the file is not byte-identical by construction. Every
        identity field must be preserved and the seal must record the new bytes.
        """

        working, projection = self._project()
        self.assertTrue(self._binding_path().is_file(), "the fixture carries no binding to project")
        copied = working / "raw" / BINDING
        self.assertTrue(copied.is_file(), "the current-v2 build binding did not survive projection")
        original = build_policy.read_build_binding(self._binding_path())
        restored = build_policy.read_build_binding(copied)
        for field in ("campaign", "control", "build_policy_digest", "source_base_sha",
                      "source_experiment_sha", "toolchain", "query_operations_started"):
            self.assertEqual(restored[field], original[field], f"projection changed {field}")
        self.assertEqual(set(restored["builds"]), set(original["builds"]))
        for arm, entry in original["builds"].items():
            projected_entry = restored["builds"][arm]
            for field in ("source_sha", "feature", "sha256", "bytes", "binary"):
                self.assertEqual(projected_entry[field], entry[field], f"projection changed builds.{arm}.{field}")
            self.assertNotEqual(projected_entry["argv"], entry["argv"],
                                "the projected argv must describe the projected checkout and build dir")
            self.assertEqual(projected_entry["argv"][:5], entry["argv"][:5])
        seal = support.read_json(working / "raw/seal.json")
        self.assertEqual(seal["files"][f"raw/{BINDING}"],
                         support.hashlib.sha256(copied.read_bytes()).hexdigest())
        self.assertTrue(projection.working_inventory_digest.startswith("sha256:"))

    def test_binding_is_part_of_the_retained_evidence_inventory(self) -> None:
        members = admission.retained_key_member_paths(self.fixture.raw_root)
        self.assertIn(f"{CAMPAIGN}/raw/{BINDING}", members)
        sealed = support.read_json(self.campaign / "raw/seal.json")["files"]
        self.assertIn(f"raw/{BINDING}", sealed)
        records, _total = admission.hash_raw_members(
            self.fixture.raw_root, admission.retained_key_member_paths(self.fixture.raw_root)
        )
        record = next(row for row in records if row["path"] == f"{CAMPAIGN}/raw/{BINDING}")
        self.assertEqual(record["digest"], "sha256:" + support.hashlib.sha256(self._binding_path().read_bytes()).hexdigest())

    # --------------------------------------------------------------- verification
    def test_one_campaign_passes_the_versioned_verifier(self) -> None:
        report = v2_verifier.verify_campaign_v2(self.campaign, expected_policy_digest=self._policy_digest())
        self.assertEqual(report["verification"], "PASS")
        self.assertEqual(report["verifier"], v2_verifier.VERIFIER_IDENTITY)
        self.assertEqual(report["build_policy_digest"], self._policy_digest())
        self.assertEqual(report["kind"], "control")

    def test_all_three_projected_campaigns_pass_the_versioned_verifier(self) -> None:
        """The replay-shaped path: project every campaign, then verify each."""

        for campaign in (admission.D3C_CONTROL_NAME, *admission.D3C_CAMPAIGN_NAMES):
            with self.subTest(campaign=campaign):
                working, _projection = self._project(self.fixture.raw_root / campaign)
                report = v2_verifier.verify_campaign_v2(
                    working, expected_policy_digest=self._policy_digest(), source_basis="pinned-git"
                )
                self.assertEqual(report["verification"], "PASS")
                self.assertEqual(report["campaign"], campaign)
                self.assertTrue((working / "raw" / BINDING).is_file())

    def test_production_and_replay_bases_differ_only_for_the_checkout(self) -> None:
        """Production demands its checkout; replay derives from pinned revisions."""

        working, _projection = self._project()
        self.assertFalse((working / "compile-source").is_dir(), "a projected copy must not carry a checkout")
        report = v2_verifier.verify_campaign_v2(
            working, expected_policy_digest=self._policy_digest(), source_basis="pinned-git"
        )
        self.assertEqual(report["verification"], "PASS")
        with self.assertRaises(v2_verifier.V2VerificationError) as raised:
            v2_verifier.verify_campaign_v2(
                working, expected_policy_digest=self._policy_digest(), source_basis="checkout"
            )
        self.assertEqual(raised.exception.code, "V2_POLICY")
        # A production campaign that does have its checkout verifies on that basis.
        self.assertEqual(
            v2_verifier.verify_campaign_v2(
                self.campaign, expected_policy_digest=self._policy_digest(), source_basis="checkout"
            )["verification"],
            "PASS",
        )
        with self.assertRaises(v2_verifier.V2VerificationError):
            v2_verifier.verify_campaign_v2(self.campaign, source_basis="unknown")
        # The admission gateway reports the same failure as a typed outcome with
        # the verifier's own diagnostic, and admission raises on the FAIL status.
        outcome = admission.CurrentV2RetainedVerifier(source_basis="checkout").verify_retained_key_campaign(working)
        self.assertEqual(outcome.status, "FAIL")
        self.assertIn("no compilation checkout", outcome.detail)
        with self.assertRaises(BenchError):
            admission.CurrentV2RetainedVerifier(source_basis="unknown")
        self.assertEqual(
            admission.CurrentV2RetainedVerifier(source_basis="pinned-git").verify_retained_key_campaign(working).status,
            "ACQUIRED_VERIFIED",
        )

    def test_a_missing_binding_is_rejected_by_the_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / CAMPAIGN
            shutil.copytree(self.campaign, campaign, symlinks=True)
            self._binding_path(campaign).unlink()
            with self.assertRaises(BenchError) as raised:
                v2_verifier.verify_campaign_v2(campaign, expected_policy_digest=self._policy_digest())
            # A missing required document is an availability failure (the shared
            # reader sets no field path); nothing about it is "invalid evidence".
            self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def test_a_missing_binding_is_rejected_by_admission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / CAMPAIGN
            shutil.copytree(self.campaign, campaign, symlinks=True)
            self._binding_path(campaign).unlink()
            with self.assertRaises(BenchError) as raised:
                admission._verify_retained_key_slots(
                    campaign,
                    campaign=CAMPAIGN,
                    plan=[],
                    manifest=support.read_json(campaign / "manifest.json"),
                    template=self.fixture.template,
                    profile_version=2,
                )
            self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def test_an_invalid_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / CAMPAIGN
            shutil.copytree(self.campaign, campaign, symlinks=True)
            document = support.read_json(self._binding_path(campaign))
            document["query_operations_started"] = True
            self._binding_path(campaign).write_bytes(canonical_document_bytes(document))
            with self.assertRaises(BenchError) as raised:
                v2_verifier.verify_campaign_v2(campaign, expected_policy_digest=self._policy_digest())
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_an_arm_that_does_not_match_the_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / CAMPAIGN
            shutil.copytree(self.campaign, campaign, symlinks=True)
            manifest = support.read_json(campaign / "manifest.json")
            manifest["arms"]["A"]["binary_sha256"] = "0" * 64
            support.write_json(campaign / "manifest.json", manifest)
            self._reseal(campaign)
            with self.assertRaises(BenchError) as raised:
                v2_verifier.verify_campaign_v2(campaign, expected_policy_digest=self._policy_digest())
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_a_tampered_binding_policy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / CAMPAIGN
            shutil.copytree(self.campaign, campaign, symlinks=True)
            document = support.read_json(self._binding_path(campaign))
            document["builds"]["A"]["sha256"] = "1" * 64
            self._binding_path(campaign).write_bytes(canonical_document_bytes(document))
            self._reseal(campaign)
            with self.assertRaises(BenchError) as raised:
                v2_verifier.verify_campaign_v2(campaign, expected_policy_digest=self._policy_digest())
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
