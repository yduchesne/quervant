"""CON/CLI/ADM/SCOPE/REUSE: admission vertical slice and fail-closed mutations."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quervant_bench import cli
from quervant_bench.config import contracts, schemas
from quervant_bench.config.codec import (
    canonical_document_bytes,
    content_digest,
    loads_json,
)
from quervant_bench.config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_PUBLICATION_CONFLICT,
    BM_SCHEMA_INVALID,
    BM_SCOPE_MISMATCH,
    BM_UNSAFE_INPUT,
    CODE_TABLE,
    BenchError,
)
from quervant_bench.evidence import admission as admission_module
from quervant_bench.evidence.admission import (
    AdmissionResult,
    admit_synthetic,
    reverify_admission,
)
from quervant_bench.evidence.hashing import source_file_set_digest
from quervant_bench.evidence.manifests import load_trusted_spec
from quervant_bench.evidence.provenance import VALIDATOR_SOURCE_PATHS
from quervant_bench.evidence.publication import load_committed_admission
from quervant_bench.evidence.receipts import verify_admission_receipt

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "evidence-admission"

#: Independently pinned canonical digest of the checked-in golden trusted spec.
#: Regenerated only through an explicit fixture review; never derived at runtime.
GOLDEN_SPEC_DIGEST = "sha256:5a8b6a3f8a301c2f096d8f7c7d096085a6d4b4bf59b7c1cc69dd1450d5aad229"

_LOCK_RECORD = {
    "adapter-lock": "record-adapter",
    "analysis-lock": "record-analysis",
    "build-lock": "record-build",
    "schema-registry": "record-schema",
    "source-lock": "record-source",
}


def golden_spec():
    return load_trusted_spec(
        (FIXTURE / "trusted-spec.json").read_bytes(),
        expected_spec_digest=GOLDEN_SPEC_DIGEST,
    )


def verified_locks(spec, root: Path = FIXTURE) -> dict[str, str]:
    locks: dict[str, str] = {}
    for lock_name, record_name in _LOCK_RECORD.items():
        entry = next(item for item in spec.files if item.name == record_name)
        document = loads_json((root / entry.path).read_text(encoding="utf-8"))
        locks[lock_name] = content_digest(document)
    return locks


def spec_document() -> dict:
    return loads_json((FIXTURE / "trusted-spec.json").read_text(encoding="utf-8"))


def mutated_spec(mutator):
    document = spec_document()
    mutator(document)
    payload = canonical_document_bytes(document)
    anchor = content_digest(document)
    return load_trusted_spec(payload, expected_spec_digest=anchor), anchor


def copy_evidence(destination: Path) -> Path:
    shutil.copytree(FIXTURE, destination)
    return destination


def _recompute_receipt_id(document: dict) -> dict:
    payload = {key: value for key, value in document.items() if key != "receipt_id"}
    document["receipt_id"] = content_digest(payload)
    return document


def _append_byte(path: Path) -> None:
    path.write_bytes(path.read_bytes() + b" ")


class ContractImmutabilityTests(unittest.TestCase):
    def test_con_01_six_bm01_schemas_and_public_apis_are_intact(self) -> None:
        self.assertEqual(
            schemas.supported_kinds(),
            {
                "adapter": (1,),
                "experiment": (1,),
                "outcome": (1,),
                "protocol": (1,),
                "receipt": (1,),
                "workload": (1,),
            },
        )
        self.assertEqual(len(schemas.check_all_schemas()), 6)
        from quervant_bench.config import codec

        for name in (
            "load_document",
            "loads_json",
            "loads_yaml",
            "canonical_document_bytes",
            "content_digest",
            "sha256_prefix",
        ):
            self.assertTrue(hasattr(codec, name))
        for name in ("validate_receipt", "validate_origin_scope"):
            self.assertTrue(hasattr(contracts, name))

    def test_con_02_origin_scope_matrix_and_error_table_unchanged(self) -> None:
        self.assertEqual(
            contracts.ALLOWED_ORIGIN_SCOPES,
            {
                ("synthetic", "simulated"),
                ("real", "official"),
                ("real", "historical_replay"),
            },
        )
        self.assertEqual(
            set(CODE_TABLE),
            {
                "BM_OK",
                "BM_USAGE",
                "BM_SCHEMA_INVALID",
                "BM_SCHEMA_UNSUPPORTED",
                "BM_DUPLICATE_KEY",
                "BM_IDENTITY_INVALID",
                "BM_SCOPE_MISMATCH",
                "BM_UNSAFE_INPUT",
                "BM_FILE_MISSING",
                "BM_NOT_IMPLEMENTED",
                "BM_EVIDENCE_UNAVAILABLE",
                "BM_PUBLICATION_CONFLICT",
                "BM_ACQUISITION_PROHIBITED",
                "BM_INTERNAL_ERROR",
            },
        )
        self.assertIn("admission", contracts.GATES)


class CliRestrictionTests(unittest.TestCase):
    def test_cli_01_run_is_prohibited_before_side_effects(self) -> None:
        stderr = io.StringIO()
        with mock.patch("os.mkdir", side_effect=AssertionError("mkdir")), mock.patch(
            "time.time", side_effect=AssertionError("clock")
        ), mock.patch(
            "subprocess.run", side_effect=AssertionError("subprocess")
        ), contextlib.redirect_stderr(stderr):
            status = cli.main(
                ["run", "--experiment", "x", "--protocol", "p", "--out", "o"]
            )
        self.assertEqual(status, 77)
        outcome = loads_json(stderr.getvalue())
        self.assertEqual(outcome["code"], BM_ACQUISITION_PROHIBITED)

    def test_cli_02_inspect_golden_and_reserved_verbs(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = cli.main(
                ["inspect", "--experiment", "synthetic-contract-smoke", "--format", "json"]
            )
        self.assertEqual(status, 0)
        outcome = loads_json(stdout.getvalue())
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["data"]["evidence_origin"], "synthetic")
        for verb in cli.RESERVED_VERBS:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = cli.main([verb, "--run", "x"])
            self.assertEqual(status, 69)
            self.assertEqual(loads_json(stderr.getvalue())["code"], "BM_NOT_IMPLEMENTED")


class AdmissionVerticalSliceTests(unittest.TestCase):
    def test_adm_01_synthetic_admission_exact_index_and_receipt(self) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            result = admit_synthetic(
                spec=spec,
                spec_expected_digest=GOLDEN_SPEC_DIGEST,
                evidence_root=FIXTURE,
                output_base=Path(tmp),
                verified_locks=locks,
            )
            self.assertIsInstance(result, AdmissionResult)
            self.assertEqual(result.disposition, "ADMITTED_SYNTHETIC")
            index, receipt_document = load_committed_admission(
                Path(tmp), spec.subject.experiment_id, spec.subject.run_id
            )
            self.assertEqual(receipt_document["gate"], "admission")
            self.assertEqual(receipt_document["status"], "pass")
            self.assertEqual(receipt_document["evidence_origin"], "synthetic")
            self.assertEqual(receipt_document["qualification_scope"], "simulated")
            self.assertEqual(receipt_document["dependencies"], [])
            self.assertEqual(len(receipt_document["outputs"]), 1)
            self.assertEqual(
                receipt_document["outputs"][0],
                {"name": "admission-index", "digest": content_digest(index)},
            )
            self.assertEqual(len(receipt_document["inputs"]), 21)
            names = [entry["name"] for entry in receipt_document["inputs"]]
            self.assertEqual(names, sorted(names))
            for required in (
                "trusted-spec",
                "protocol-lock",
                "workload-lock",
                "validator-lock",
                "policy-lock",
                "qa-roster-lock",
                "adapter-lock",
                "analysis-lock",
                "build-lock",
                "schema-registry",
                "source-lock",
            ):
                self.assertIn(required, names)
            self.assertEqual([lock["name"] for lock in index["locks"]], sorted(_LOCK_RECORD))
            self.assertEqual(len(index["files"]), 8)
            self.assertEqual(len(index["archives"]), 2)
            self.assertEqual(result.admission_index_digest, content_digest(index))

    def test_adm_02_wrong_anchor_rejects_before_output(self) -> None:
        spec = golden_spec()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with self.assertRaises(BenchError) as raised:
                admit_synthetic(
                    spec=spec,
                    spec_expected_digest="sha256:" + "0" * 64,
                    evidence_root=FIXTURE,
                    output_base=output,
                    verified_locks=verified_locks(spec),
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertEqual(list(output.iterdir()), [])

    def test_adm_03_changed_raw_byte_is_rejected(self) -> None:
        spec = golden_spec()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp2:
            evidence = copy_evidence(Path(tmp) / "evidence")
            _append_byte(evidence / "raw" / "evidence.json")
            with self.assertRaises(BenchError) as raised:
                admit_synthetic(
                    spec=spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=evidence,
                    output_base=Path(tmp2),
                    verified_locks=verified_locks(spec),
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertEqual(list(Path(tmp2).iterdir()), [])

    def test_adm_04_incomplete_specs_are_rejected(self) -> None:
        def remove_lock(document):
            document["locks"] = [lock for lock in document["locks"] if lock["name"] != "build-lock"]

        def remove_required_file(document):
            document["files"] = [item for item in document["files"] if item["name"] != "record-qa"]

        def remove_archive(document):
            document["archives"] = [item for item in document["archives"] if item["name"] != "synthetic-zip"]

        def remove_policy(document):
            document.pop("policy_digest")

        for mutator in (remove_lock, remove_policy):
            with self.subTest(mutator=mutator.__name__):
                document = spec_document()
                mutator(document)
                with self.assertRaises(BenchError):
                    load_trusted_spec(
                        canonical_document_bytes(document),
                        expected_spec_digest=content_digest(document),
                    )
        for mutator in (remove_required_file, remove_archive):
            with self.subTest(mutator=mutator.__name__):
                spec, anchor = mutated_spec(mutator)
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(BenchError) as raised:
                        admit_synthetic(
                            spec=spec,
                            spec_expected_digest=anchor,
                            evidence_root=FIXTURE,
                            output_base=Path(tmp),
                            verified_locks=verified_locks(spec),
                        )
                    self.assertIn(
                        raised.exception.code,
                        {BM_IDENTITY_INVALID, BM_SCHEMA_INVALID},
                    )
                    self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_adm_05_extra_fields_and_duplicates_are_rejected(self) -> None:
        with self.assertRaises(BenchError) as raised:
            load_trusted_spec(
                canonical_document_bytes(
                    {**spec_document(), "unexpected": True}
                ),
                expected_spec_digest="sha256:" + "1" * 64,
            )
        self.assertEqual(raised.exception.code, BM_SCHEMA_INVALID)

        def duplicate_file(document):
            document["files"].append(dict(document["files"][0]))

        with self.assertRaises(BenchError) as raised:
            mutated_spec(duplicate_file)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

        def duplicate_path(document):
            document["files"][1]["path"] = document["files"][0]["path"]

        with self.assertRaises(BenchError) as raised:
            mutated_spec(duplicate_path)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_adm_06_mid_flight_input_change_is_rejected(self) -> None:
        spec = golden_spec()
        original = admission_module._validate_dependencies

        def mutate_then_validate(spec_arg, root, locks):
            original(spec_arg, root, locks)
            target = Path(root) / "raw" / "evidence.json"
            payload = target.read_bytes()
            target.write_bytes(payload.replace(b'"simulated"', b'"simulatex"'))

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp2:
            evidence = copy_evidence(Path(tmp) / "evidence")
            with mock.patch.object(
                admission_module,
                "_validate_dependencies",
                side_effect=mutate_then_validate,
            ):
                with self.assertRaises(BenchError):
                    admit_synthetic(
                        spec=spec,
                        spec_expected_digest=GOLDEN_SPEC_DIGEST,
                        evidence_root=evidence,
                        output_base=Path(tmp2),
                        verified_locks=verified_locks(spec),
                    )
            self.assertEqual(list(Path(tmp2).iterdir()), [])

    def test_adm_07_archive_with_changed_bytes_is_rejected(self) -> None:
        spec = golden_spec()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp2:
            evidence = copy_evidence(Path(tmp) / "evidence")
            _append_byte(evidence / "archives" / "synthetic.tar.gz")
            with self.assertRaises(BenchError) as raised:
                admit_synthetic(
                    spec=spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=evidence,
                    output_base=Path(tmp2),
                    verified_locks=verified_locks(spec),
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_adm_09_changed_archive_or_member_declaration_is_rejected(self) -> None:
        def change_member(document):
            document["archives"][0]["members"][0]["digest"] = "sha256:" + "aa" * 32

        def change_archive(document):
            document["archives"][0]["digest"] = "sha256:" + "bb" * 32

        for mutator in (change_member, change_archive):
            with self.subTest(mutator=mutator.__name__):
                spec, anchor = mutated_spec(mutator)
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(BenchError) as raised:
                        admit_synthetic(
                            spec=spec,
                            spec_expected_digest=anchor,
                            evidence_root=FIXTURE,
                            output_base=Path(tmp),
                            verified_locks=verified_locks(spec),
                        )
                    self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                    self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_adm_08_no_self_signed_trust_convenience_exists(self) -> None:
        import inspect

        signature = inspect.signature(load_trusted_spec)
        self.assertIn("expected_spec_digest", signature.parameters)
        self.assertEqual(
            signature.parameters["expected_spec_digest"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        with self.assertRaises(TypeError):
            load_trusted_spec((FIXTURE / "trusted-spec.json").read_bytes())
        self.assertFalse(hasattr(load_trusted_spec, "from_evidence_root"))
        self.assertNotIn("admit_official", dir(admission_module))

    def test_vertical_slice_admit_then_reuse_then_mutate(self) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp2:
            evidence = copy_evidence(Path(tmp) / "evidence")
            output = Path(tmp2)
            first = admit_synthetic(
                spec=spec,
                spec_expected_digest=GOLDEN_SPEC_DIGEST,
                evidence_root=evidence,
                output_base=output,
                verified_locks=locks,
            )
            self.assertEqual(first.disposition, "ADMITTED_SYNTHETIC")
            second = admit_synthetic(
                spec=spec,
                spec_expected_digest=GOLDEN_SPEC_DIGEST,
                evidence_root=evidence,
                output_base=output,
                verified_locks=locks,
            )
            self.assertEqual(second.disposition, "REUSED_VERIFIED")
            self.assertEqual(first.receipt.receipt_id, second.receipt.receipt_id)
            _append_byte(evidence / "raw" / "source-lock.json")
            with self.assertRaises(BenchError):
                reverify_admission(
                    spec=spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=evidence,
                    output_base=output,
                    verified_locks=locks,
                )


class ScopeIsolationTests(unittest.TestCase):
    def _scope_spec(self, origin: str, scope: str):
        def mutate(document):
            document["evidence_origin"] = origin
            document["qualification_scope"] = scope

        return mutated_spec(mutate)

    def _attempt(self, origin: str, scope: str) -> BenchError:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                spec, anchor = self._scope_spec(origin, scope)
            except BenchError as error:
                self.assertEqual(list(Path(tmp).iterdir()), [])
                return error
            with self.assertRaises(BenchError) as raised:
                admit_synthetic(
                    spec=spec,
                    spec_expected_digest=anchor,
                    evidence_root=FIXTURE,
                    output_base=Path(tmp),
                    verified_locks=verified_locks(spec),
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])
            return raised.exception

    def test_scope_01_only_synthetic_simulated_is_admitted(self) -> None:
        spec = golden_spec()
        self.assertEqual(
            (spec.evidence_origin, spec.qualification_scope),
            ("synthetic", "simulated"),
        )

    def test_scope_02_illegal_pairs_are_scope_mismatch(self) -> None:
        for origin, scope in (
            ("synthetic", "official"),
            ("synthetic", "historical_replay"),
            ("real", "simulated"),
        ):
            with self.subTest(origin=origin, scope=scope):
                self.assertEqual(
                    self._attempt(origin, scope).code, BM_SCOPE_MISMATCH
                )

    def test_scope_03_real_official_is_prohibited(self) -> None:
        self.assertEqual(
            self._attempt("real", "official").code, BM_ACQUISITION_PROHIBITED
        )

    def test_scope_04_real_historical_replay_gets_no_new_pass(self) -> None:
        self.assertEqual(
            self._attempt("real", "historical_replay").code, BM_SCOPE_MISMATCH
        )

    def test_scope_05_relabelled_receipt_is_rejected(self) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            admit_synthetic(
                spec=spec,
                spec_expected_digest=GOLDEN_SPEC_DIGEST,
                evidence_root=FIXTURE,
                output_base=Path(tmp),
                verified_locks=locks,
            )
            index, receipt = load_committed_admission(
                Path(tmp), spec.subject.experiment_id, spec.subject.run_id
            )
            forged = json.loads(json.dumps(receipt))
            forged["evidence_origin"] = "real"
            forged["qualification_scope"] = "official"
            _recompute_receipt_id(forged)
            with self.assertRaises(BenchError):
                verify_admission_receipt(
                    forged, index, spec, GOLDEN_SPEC_DIGEST, locks
                )

    def test_scope_06_no_run_measure_or_clock_spy_is_invoked(self) -> None:
        spec = golden_spec()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            cli, "main", side_effect=AssertionError("cli must not run")
        ), mock.patch("time.time", side_effect=AssertionError("no clock")), mock.patch(
            "time.perf_counter", side_effect=AssertionError("no clock")
        ):
            admit_synthetic(
                spec=spec,
                spec_expected_digest=GOLDEN_SPEC_DIGEST,
                evidence_root=FIXTURE,
                output_base=Path(tmp),
                verified_locks=verified_locks(spec),
            )

    def test_scope_07_gate_claims_outside_admission_are_rejected(self) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            admit_synthetic(
                spec=spec,
                spec_expected_digest=GOLDEN_SPEC_DIGEST,
                evidence_root=FIXTURE,
                output_base=Path(tmp),
                verified_locks=locks,
            )
            index, receipt = load_committed_admission(
                Path(tmp), spec.subject.experiment_id, spec.subject.run_id
            )
            for gate in ("source-qa", "analysis", "acceptance"):
                with self.subTest(gate=gate):
                    forged = json.loads(json.dumps(receipt))
                    forged["gate"] = gate
                    _recompute_receipt_id(forged)
                    with self.assertRaises(BenchError):
                        verify_admission_receipt(
                            forged, index, spec, GOLDEN_SPEC_DIGEST, locks
                        )

    def test_scope_08_unknown_origin_scope_fails_closed(self) -> None:
        self.assertEqual(
            self._attempt("production", "simulated").code, BM_SCOPE_MISMATCH
        )

    def test_scope_09_self_declared_qualified_is_not_authorization(self) -> None:
        spec = golden_spec()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp2:
            evidence = copy_evidence(Path(tmp) / "evidence")
            target = evidence / "raw" / "evidence.json"
            document = loads_json(target.read_text(encoding="utf-8"))
            document["qualified"] = True
            target.write_bytes(canonical_document_bytes(document))
            with self.assertRaises(BenchError):
                admit_synthetic(
                    spec=spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=evidence,
                    output_base=Path(tmp2),
                    verified_locks=verified_locks(spec),
                )
            self.assertEqual(list(Path(tmp2).iterdir()), [])

    def test_scope_10_pass_without_external_expected_spec_is_rejected(self) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            admit_synthetic(
                spec=spec,
                spec_expected_digest=GOLDEN_SPEC_DIGEST,
                evidence_root=FIXTURE,
                output_base=Path(tmp),
                verified_locks=locks,
            )
            index, receipt = load_committed_admission(
                Path(tmp), spec.subject.experiment_id, spec.subject.run_id
            )
            with self.assertRaises(BenchError):
                verify_admission_receipt(
                    receipt, index, spec, "sha256:" + "9" * 64, locks
                )


class ReuseInvalidationTests(unittest.TestCase):
    def _admitted(self, base: Path, evidence: Path, spec, locks):
        return admit_synthetic(
            spec=spec,
            spec_expected_digest=GOLDEN_SPEC_DIGEST,
            evidence_root=evidence,
            output_base=base,
            verified_locks=locks,
        )

    def test_reuse_01_unchanged_evidence_is_reused_without_rewrites(self) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            evidence = copy_evidence(Path(tmp) / "evidence")
            output = Path(tmp) / "output"
            output.mkdir()
            first = self._admitted(output, evidence, spec, locks)
            run_dir = first.output_root
            before = {
                path.name: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
                for path in run_dir.iterdir()
            }
            second = self._admitted(output, evidence, spec, locks)
            after = {
                path.name: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
                for path in run_dir.iterdir()
            }
            self.assertEqual(second.disposition, "REUSED_VERIFIED")
            self.assertEqual(second.receipt.receipt_id, first.receipt.receipt_id)
            self.assertEqual(before, after)

    def test_reuse_02_changed_source_lock_rejects(self) -> None:
        self._mutated_record_rejects("raw/source-lock.json")

    def test_reuse_03_changed_locks_and_bindings_reject(self) -> None:
        for relative in (
            "raw/adapter-lock.json",
            "raw/analysis-lock.json",
            "raw/build-lock.json",
            "raw/schema-registry.json",
        ):
            with self.subTest(relative=relative):
                self._mutated_record_rejects(relative)

        for field in ("protocol_digest", "workload_digest"):
            with self.subTest(field=field):
                spec, anchor = mutated_spec(
                    lambda document, field=field: document["subject"].__setitem__(
                        field, "sha256:" + "ab" * 32
                    )
                )
                self._variant_rejects(spec, anchor)

        spec, anchor = mutated_spec(
            lambda document: document.__setitem__("policy_digest", "sha256:" + "1" * 64)
        )
        self._variant_rejects(spec, anchor)

    def test_reuse_04_changed_validator_source_or_version_rejects(self) -> None:
        spec, anchor = mutated_spec(
            lambda document: document["validator"].__setitem__("source_digest", "sha256:" + "2" * 64)
        )
        self._variant_rejects(spec, anchor)

        spec, anchor = mutated_spec(
            lambda document: document["validator"].__setitem__("validator_version", 2)
        )
        self._variant_rejects(spec, anchor)

    def test_reuse_05_changed_qa_roster_or_schema_registry_rejects(self) -> None:
        spec, anchor = mutated_spec(
            lambda document: document.__setitem__("qa_roster_digest", "sha256:" + "3" * 64)
        )
        self._variant_rejects(spec, anchor)

        def change_schema_lock(document):
            for lock in document["locks"]:
                if lock["name"] == "schema-registry":
                    lock["digest"] = "sha256:" + "4" * 64

        spec, anchor = mutated_spec(change_schema_lock)
        self._variant_rejects(spec, anchor)

    def test_reuse_06_changed_raw_evidence_keeps_old_receipt_bytes(self) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            evidence = copy_evidence(Path(tmp) / "evidence")
            output = Path(tmp) / "output"
            output.mkdir()
            first = self._admitted(output, evidence, spec, locks)
            receipt_path = first.output_root / "admission.json"
            before = receipt_path.read_bytes()
            _append_byte(evidence / "raw" / "evidence.json")
            with self.assertRaises(BenchError):
                reverify_admission(
                    spec=spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=evidence,
                    output_base=output,
                    verified_locks=locks,
                )
            self.assertEqual(receipt_path.read_bytes(), before)

    def test_reuse_07_forged_receipt_fields_are_rejected(self) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            self._admitted(Path(tmp), FIXTURE, spec, locks)
            index, receipt = load_committed_admission(
                Path(tmp), spec.subject.experiment_id, spec.subject.run_id
            )
            forged_id = json.loads(json.dumps(receipt))
            forged_id["receipt_id"] = "sha256:" + "e" * 64
            with self.assertRaises(BenchError):
                verify_admission_receipt(forged_id, index, spec, GOLDEN_SPEC_DIGEST, locks)

            dependency = json.loads(json.dumps(receipt))
            dependency["dependencies"] = [
                {
                    "name": "framework-qa",
                    "digest": "sha256:" + "d" * 64,
                    "gate": "framework-qa",
                    "receipt_id": "sha256:" + "d" * 64,
                }
            ]
            _recompute_receipt_id(dependency)
            with self.assertRaises(BenchError):
                verify_admission_receipt(dependency, index, spec, GOLDEN_SPEC_DIGEST, locks)

            output = json.loads(json.dumps(receipt))
            output["outputs"][0]["digest"] = "sha256:" + "f" * 64
            _recompute_receipt_id(output)
            with self.assertRaises(BenchError):
                verify_admission_receipt(output, index, spec, GOLDEN_SPEC_DIGEST, locks)

    def test_reuse_08_old_pass_for_new_run_or_scope_is_rejected(self) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            self._admitted(Path(tmp), FIXTURE, spec, locks)
            variant, anchor = mutated_spec(
                lambda document: document["subject"].__setitem__(
                    "run_id", "00000000-0000-4000-8000-000000000003"
                )
            )
            with self.assertRaises(BenchError) as raised:
                reverify_admission(
                    spec=variant,
                    spec_expected_digest=anchor,
                    evidence_root=FIXTURE,
                    output_base=Path(tmp),
                    verified_locks=locks,
                )
            self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)

            index, receipt = load_committed_admission(
                Path(tmp), spec.subject.experiment_id, spec.subject.run_id
            )
            relabelled = json.loads(json.dumps(receipt))
            relabelled["evidence_origin"] = "real"
            relabelled["qualification_scope"] = "historical_replay"
            _recompute_receipt_id(relabelled)
            with self.assertRaises(BenchError):
                verify_admission_receipt(
                    relabelled, index, spec, GOLDEN_SPEC_DIGEST, locks
                )

    def test_reuse_09_deleted_evidence_is_rejected(self) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            evidence = copy_evidence(Path(tmp) / "evidence")
            output = Path(tmp) / "output"
            output.mkdir()
            self._admitted(output, evidence, spec, locks)
            (evidence / "raw" / "qa-roster.json").unlink()
            with self.assertRaises(BenchError) as raised:
                reverify_admission(
                    spec=spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=evidence,
                    output_base=output,
                    verified_locks=locks,
                )
            self.assertEqual(raised.exception.code, BM_FILE_MISSING)

    def test_reuse_10_changed_index_with_unchanged_receipt_is_rejected(self) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            self._admitted(Path(tmp), FIXTURE, spec, locks)
            index, receipt = load_committed_admission(
                Path(tmp), spec.subject.experiment_id, spec.subject.run_id
            )
            tampered = json.loads(json.dumps(index))
            tampered["files"][0]["digest"] = "sha256:" + "a" * 64
            with self.assertRaises(BenchError):
                verify_admission_receipt(
                    receipt, tampered, spec, GOLDEN_SPEC_DIGEST, locks
                )

    def _mutated_record_rejects(self, relative: str) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            evidence = copy_evidence(Path(tmp) / "evidence")
            output = Path(tmp) / "output"
            output.mkdir()
            self._admitted(output, evidence, spec, locks)
            _append_byte(evidence / relative)
            with self.assertRaises(BenchError):
                reverify_admission(
                    spec=spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=evidence,
                    output_base=output,
                    verified_locks=locks,
                )

    def _variant_rejects(self, spec, anchor: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            output.mkdir()
            self._admitted(output, FIXTURE, golden_spec(), verified_locks(golden_spec()))
            with self.assertRaises(BenchError):
                reverify_admission(
                    spec=spec,
                    spec_expected_digest=anchor,
                    evidence_root=FIXTURE,
                    output_base=output,
                    verified_locks=verified_locks(golden_spec()),
                )




PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _clone_validator_sources(destination: Path) -> Path:
    for relative in VALIDATOR_SOURCE_PATHS:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((PACKAGE_ROOT / relative).read_bytes())
    return destination


def _snapshot(root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            snapshot[str(path.relative_to(root))] = path.read_bytes()
        elif path.is_dir():
            snapshot[str(path.relative_to(root)) + "/"] = b""
    return snapshot


class ValidatorSourceClosureAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = golden_spec()
        cls.locks = verified_locks(cls.spec)
        cls._temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls._temporary.name)
        cls.first = admit_synthetic(
            spec=cls.spec,
            spec_expected_digest=GOLDEN_SPEC_DIGEST,
            evidence_root=FIXTURE,
            output_base=cls.output,
            verified_locks=cls.locks,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_vs_02_golden_admission_and_reuse(self) -> None:
        second = admit_synthetic(
            spec=self.spec,
            spec_expected_digest=GOLDEN_SPEC_DIGEST,
            evidence_root=FIXTURE,
            output_base=self.output,
            verified_locks=self.locks,
        )
        self.assertEqual(second.disposition, "REUSED_VERIFIED")
        self.assertEqual(second.receipt.receipt_id, self.first.receipt.receipt_id)
        _index, receipt = load_committed_admission(
            self.output, self.spec.subject.experiment_id, self.spec.subject.run_id
        )
        self.assertEqual(len(receipt["inputs"]), 21)

    def test_vs_03_and_04_imported_module_mutation_invalidates_reuse(self) -> None:
        for target in ("config/profiles.py", "host/capabilities.py"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                clone = _clone_validator_sources(Path(tmp) / "pkg")
                self.assertEqual(
                    source_file_set_digest(clone, VALIDATOR_SOURCE_PATHS),
                    self.spec.validator.source_digest,
                )
                module = clone / target
                module.write_bytes(module.read_bytes() + b"\n# synthetic mutation\n")
                before = _snapshot(self.first.output_root)
                with mock.patch.object(
                    admission_module, "_package_root", return_value=clone
                ):
                    with self.assertRaises(BenchError) as raised:
                        reverify_admission(
                            spec=self.spec,
                            spec_expected_digest=GOLDEN_SPEC_DIGEST,
                            evidence_root=FIXTURE,
                            output_base=self.output,
                            verified_locks=self.locks,
                        )
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                self.assertEqual(_snapshot(self.first.output_root), before)
                self.assertEqual(
                    sorted(path.name for path in self.first.output_root.iterdir()),
                    ["admission-index.json", "admission.json"],
                )

    def test_vs_05_changed_validator_digest_cannot_bypass_pinned_anchor(self) -> None:
        document = spec_document()
        document["validator"]["source_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(BenchError) as raised:
            load_trusted_spec(
                canonical_document_bytes(document),
                expected_spec_digest=GOLDEN_SPEC_DIGEST,
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

        spec, anchor = mutated_spec(
            lambda doc: doc["validator"].__setitem__(
                "source_digest", "sha256:" + "0" * 64
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(BenchError) as raised:
                admit_synthetic(
                    spec=spec,
                    spec_expected_digest=anchor,
                    evidence_root=FIXTURE,
                    output_base=Path(tmp),
                    verified_locks=verified_locks(spec),
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class AdmissionRootGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = golden_spec()
        self.locks = verified_locks(self.spec)

    def test_root_01_equal_evidence_and_output_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = copy_evidence(Path(tmp) / "evidence")
            before = _snapshot(evidence)
            with self.assertRaises(BenchError) as raised:
                admit_synthetic(
                    spec=self.spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=evidence,
                    output_base=evidence,
                    verified_locks=self.locks,
                )
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            self.assertEqual(_snapshot(evidence), before)

    def test_root_02_output_nested_beneath_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = copy_evidence(Path(tmp) / "evidence")
            nested = evidence / "output"
            nested.mkdir()
            before = _snapshot(nested)
            with self.assertRaises(BenchError) as raised:
                admit_synthetic(
                    spec=self.spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=evidence,
                    output_base=nested,
                    verified_locks=self.locks,
                )
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            self.assertEqual(_snapshot(nested), before)

    def test_root_03_evidence_nested_beneath_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            output.mkdir()
            evidence = output / "evidence"
            evidence.mkdir()
            with self.assertRaises(BenchError) as raised:
                admit_synthetic(
                    spec=self.spec,
                    spec_expected_digest=GOLDEN_SPEC_DIGEST,
                    evidence_root=evidence,
                    output_base=output,
                    verified_locks=self.locks,
                )
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            self.assertEqual(sorted(path.name for path in output.iterdir()), ["evidence"])

    def test_root_04_reverify_rejects_overlap_before_revalidation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = copy_evidence(Path(tmp) / "evidence")
            with mock.patch.object(
                admission_module,
                "_revalidate",
                side_effect=AssertionError("revalidation must not start"),
            ) as revalidate:
                with self.assertRaises(BenchError) as raised:
                    reverify_admission(
                        spec=self.spec,
                        spec_expected_digest=GOLDEN_SPEC_DIGEST,
                        evidence_root=evidence,
                        output_base=evidence,
                        verified_locks=self.locks,
                    )
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
            revalidate.assert_not_called()

    def test_root_05_disjoint_external_roots_still_admit_and_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = copy_evidence(Path(tmp) / "evidence")
            output = Path(tmp) / "output"
            output.mkdir()
            first = admit_synthetic(
                spec=self.spec,
                spec_expected_digest=GOLDEN_SPEC_DIGEST,
                evidence_root=evidence,
                output_base=output,
                verified_locks=self.locks,
            )
            self.assertEqual(first.disposition, "ADMITTED_SYNTHETIC")
            second = reverify_admission(
                spec=self.spec,
                spec_expected_digest=GOLDEN_SPEC_DIGEST,
                evidence_root=evidence,
                output_base=output,
                verified_locks=self.locks,
            )
            self.assertEqual(second.disposition, "REUSED_VERIFIED")
            self.assertEqual(
                second.admission_index_digest, first.admission_index_digest
            )


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
