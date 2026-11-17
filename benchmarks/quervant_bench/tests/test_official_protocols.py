"""O09-PRO: reviewed design templates and independent G0 authorization."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.official import protocols
from quervant_bench.tests import official_support as support


def _authorization_document(study_id: str) -> dict:
    freeze = support.make_freeze(study_id=study_id)
    return {
        "kind": protocols.AUTHORIZATION_KIND,
        "schema_version": 1,
        "study_id": study_id,
        "run_id": freeze.run_id,
        "evidence_origin": "real",
        "qualification_scope": "official",
        "design_digest": freeze.design_digest,
        "backend_protocol_digest": freeze.backend_protocol_digest,
        "source_commit": freeze.source_commit,
        "source_file_set_digest": freeze.source_file_set_digest,
        "source_tree_sha": freeze.source_tree_sha,
        "adapter_source_manifest_digest": freeze.adapter_source_manifest_digest,
        "binary_manifest_digest": freeze.binary_manifest_digest,
        "corpus_manifest_digest": freeze.corpus_manifest_digest,
        "original_reference_verifier_digest": freeze.original_reference_verifier_digest,
        "host_preflight_digest": freeze.host_preflight_digest,
        "control_schedule_digest": freeze.control_schedule_digest,
        "treatment_schedule_digest": freeze.treatment_schedule_digest,
        "qa_source_digest": freeze.qa_source_digest,
        "qa_framework_digest": freeze.qa_framework_digest,
        "operator_approval_id": freeze.operator_approval_id,
        "independent_protocol_review_id": freeze.independent_protocol_review_id,
        "approved_at_utc": freeze.approved_at_utc,
        "approved_output_root_identity": freeze.approved_output_root_identity,
        "policy_digest": freeze.policy_digest,
        "permitted_campaign_order": list(freeze.permitted_campaign_order),
        "measurement_retries": 0,
    }


class TemplateTests(unittest.TestCase):
    def test_o09_pro_01_both_reviewed_templates_validate(self) -> None:
        for study_id, digest in (
            (protocols.STUDY_RETAINED_KEY, support.RETAINED_KEY_TEMPLATE_DIGEST),
            (protocols.STUDY_CROSS_ENGINE, support.CROSS_ENGINE_TEMPLATE_DIGEST),
        ):
            template, observed = protocols.read_approved_template(
                protocols.template_path(study_id, support.REPO_ROOT), digest
            )
            self.assertEqual(observed, digest)
            self.assertEqual(template["study_id"], study_id)

    def test_o09_pro_02_wrong_candidate_digest_is_rejected(self) -> None:
        with self.assertRaises(BenchError) as raised:
            protocols.read_approved_template(
                protocols.template_path(
                    protocols.STUDY_CROSS_ENGINE, support.REPO_ROOT
                ),
                "sha256:" + "0" * 64,
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_pro_03_retained_key_template_records_the_diagnostic_flag(self) -> None:
        template, _ = protocols.read_approved_template(
            protocols.template_path(protocols.STUDY_RETAINED_KEY, support.REPO_ROOT),
            support.RETAINED_KEY_TEMPLATE_DIGEST,
        )
        self.assertIs(template["backend_diagnostic_flag"], True)
        self.assertEqual(
            template["outer_protocol_mapping"],
            {
                "diagnostic_only_disclosed": True,
                "historical_protocol_unmodified": True,
                "new_execution_required": True,
                "reviewed": True,
            },
        )

    def test_o09_pro_04_backend_protocol_and_schedule_are_cross_checked(self) -> None:
        for study_id, digest in (
            (protocols.STUDY_RETAINED_KEY, support.RETAINED_KEY_TEMPLATE_DIGEST),
            (protocols.STUDY_CROSS_ENGINE, support.CROSS_ENGINE_TEMPLATE_DIGEST),
        ):
            template, _ = protocols.read_approved_template(
                protocols.template_path(study_id, support.REPO_ROOT), digest
            )
            observed = protocols.verify_backend_protocol(template, support.REPO_ROOT)
            self.assertEqual(
                observed["raw_digest"], template["backend_protocol_identity"]["raw_sha256"]
            )

    def test_o09_pro_05_mismatched_schedule_seed_is_rejected(self) -> None:
        template, _ = protocols.read_approved_template(
            protocols.template_path(protocols.STUDY_RETAINED_KEY, support.REPO_ROOT),
            support.RETAINED_KEY_TEMPLATE_DIGEST,
        )
        forged = copy_template(template)
        forged["schedule"]["schedule_seeds"]["campaign_01"] += 1
        with self.assertRaises(BenchError) as raised:
            protocols.verify_backend_protocol(forged, support.REPO_ROOT)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_pro_06_relabelled_diagnostic_flag_is_rejected(self) -> None:
        template, _ = protocols.read_approved_template(
            protocols.template_path(protocols.STUDY_RETAINED_KEY, support.REPO_ROOT),
            support.RETAINED_KEY_TEMPLATE_DIGEST,
        )
        forged = copy_template(template)
        forged["backend_diagnostic_flag"] = False
        with self.assertRaises(BenchError) as raised:
            protocols.validate_template(forged)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_pro_07_reduced_schedule_is_rejected(self) -> None:
        template, _ = protocols.read_approved_template(
            protocols.template_path(protocols.STUDY_RETAINED_KEY, support.REPO_ROOT),
            support.RETAINED_KEY_TEMPLATE_DIGEST,
        )
        forged = copy_template(template)
        forged["schedule"]["control_order"] = forged["schedule"]["control_order"][:6]
        with self.assertRaises(BenchError) as raised:
            protocols.validate_template(forged)
        self.assertIn(raised.exception.code, (BM_IDENTITY_INVALID, "BM_SCHEMA_INVALID"))

    def test_o09_pro_08_cross_engine_cannot_select_a_winner(self) -> None:
        template, _ = protocols.read_approved_template(
            protocols.template_path(protocols.STUDY_CROSS_ENGINE, support.REPO_ROOT),
            support.CROSS_ENGINE_TEMPLATE_DIGEST,
        )
        forged = copy_template(template)
        forged["statistics"]["selected_arm_id"] = "quervant"
        with self.assertRaises(BenchError) as raised:
            protocols.validate_template(forged)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


def copy_template(template: dict) -> dict:
    import copy

    return copy.deepcopy(template)


class AuthorizationTests(unittest.TestCase):
    def _write(self, document: dict) -> tuple[Path, Path]:
        temporary = tempfile.mkdtemp()
        path = Path(temporary) / "authorization.v1.json"
        path.write_bytes(canonical_document_bytes(document))
        return path, Path(temporary)

    def test_o09_pro_09_authorization_requires_an_independent_digest(self) -> None:
        study = protocols.STUDY_CROSS_ENGINE
        document = _authorization_document(study)
        path, _root = self._write(document)
        approved = content_digest(document)
        observations = {
            name: document[name] for name in protocols.OBSERVED_IDENTITY_FIELDS
        }
        observations["output_root_identity"] = document["approved_output_root_identity"]
        freeze = protocols.verify_g0_authorization(path, approved, observations)
        self.assertEqual(freeze.study_id, study)
        self.assertEqual(freeze.authorization_digest, approved)

    def test_o09_pro_10_self_derived_but_wrong_digest_is_rejected(self) -> None:
        document = _authorization_document(protocols.STUDY_CROSS_ENGINE)
        path, _root = self._write(document)
        observations = {
            name: document[name] for name in protocols.OBSERVED_IDENTITY_FIELDS
        }
        observations["output_root_identity"] = document["approved_output_root_identity"]
        with self.assertRaises(BenchError) as raised:
            protocols.verify_g0_authorization(path, "sha256:" + "9" * 64, observations)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_pro_11_changed_observed_source_is_rejected(self) -> None:
        document = _authorization_document(protocols.STUDY_CROSS_ENGINE)
        path, _root = self._write(document)
        digest = content_digest(document)
        observations = {
            name: document[name] for name in protocols.OBSERVED_IDENTITY_FIELDS
        }
        observations["output_root_identity"] = document["approved_output_root_identity"]
        observations["source_file_set_digest"] = "sha256:" + "7" * 64
        with self.assertRaises(BenchError) as raised:
            protocols.verify_g0_authorization(path, digest, observations)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_pro_12_missing_observation_is_typed_unavailable(self) -> None:
        document = _authorization_document(protocols.STUDY_CROSS_ENGINE)
        path, _root = self._write(document)
        with self.assertRaises(BenchError) as raised:
            protocols.verify_g0_authorization(path, content_digest(document), {})
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def test_o09_pro_12b_missing_authorization_is_typed_unavailable(self) -> None:
        with self.assertRaises(BenchError) as raised:
            protocols.verify_g0_authorization(
                Path("/nonexistent/authorization.v1.json"), "sha256:" + "1" * 64, {}
            )
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def test_o09_pro_12c_noncanonical_authorization_is_rejected(self) -> None:
        document = _authorization_document(protocols.STUDY_CROSS_ENGINE)
        temporary = tempfile.mkdtemp()
        path = Path(temporary) / "authorization.v1.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(BenchError) as raised:
            protocols.verify_g0_authorization(path, content_digest(document), {})
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_pro_12d_boolean_retry_count_is_rejected(self) -> None:
        document = _authorization_document(protocols.STUDY_CROSS_ENGINE)
        document["measurement_retries"] = False
        with self.assertRaises(BenchError):
            protocols.validate_authorization(document)

    def test_o09_pro_12e_unknown_authorization_field_is_rejected(self) -> None:
        document = _authorization_document(protocols.STUDY_CROSS_ENGINE)
        document["approved_by_agent"] = True
        with self.assertRaises(BenchError):
            protocols.validate_authorization(document)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
