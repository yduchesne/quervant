# BM-02 acceptance matrix

All rows execute in the Python L1 suite:

```sh
python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py' -v
```

No row uses a real timed benchmark, a live readiness sample, a network call or a
privileged operation.

## 1. Invariant traceability

| Invariant | Required behavior | Primary tests |
| --- | --- | --- |
| INV-01 Contract immutability | Six BM-01 v1 schemas, canonical encoding, IDs, error codes and CLI rules remain byte-compatible | `test_con_01_six_bm01_schemas_and_public_apis_are_intact`, `test_con_02_origin_scope_matrix_and_error_table_unchanged`, `test_cli_01…`, `test_cli_02…` (all in `test_evidence_admission.py`) |
| INV-02 Trusted binding | A PASS receipt requires an external independently pinned spec; a self-declared digest is not a trust anchor | `test_adm_02_wrong_anchor_rejects_before_output`, `test_adm_08_no_self_signed_trust_convenience_exists`, `test_scope_10_pass_without_external_expected_spec_is_rejected`, `test_verify_rejects_wrong_anchor` |
| INV-03 Raw byte integrity | Every declared file/archive/member matches expected length and SHA-256; no hidden/extra evidence | `test_adm_03_changed_raw_byte_is_rejected`, `test_adm_07_archive_with_changed_bytes_is_rejected`, `test_adm_09_changed_archive_or_member_declaration_is_rejected`, `test_hash_01…`, `test_hash_02…`, `test_arc_01…`, `test_arc_02…`, `test_arc_06…`, `test_arc_07…` |
| INV-04 Path safety | No absolute/traversing, symlink, escaped-root or nonregular input is read | `test_path_01…` through `test_path_07…`, `test_arc_03…`, `test_arc_04…`, `test_arc_05…` |
| INV-05 Bounded archives | Streaming inspection refuses duplicate, nonregular, dangerous or over-limit members; no extraction | `test_arc_01…` through `test_arc_11…`, `test_zip_*`, `test_tar_*` |
| INV-06 Source/build identity | Pinned commit/tree/blob/validator/binary identities verified against actual bytes | `test_prov_01…`, `test_prov_02…`, `test_prov_03_and_04…`, `test_prov_05…`, `test_prov_06…`, `test_prov_07…`, `test_prov_08…`, `test_prov_09…` |
| INV-07 Complete dependency binding | Receipt inputs bind trusted spec, subject, validator, policy, QA, five locks and every observed artifact | `test_adm_01_synthetic_admission_exact_index_and_receipt`, `test_build_reproduces_the_committed_receipt`, `test_verify_accepts_the_committed_receipt`, `test_verify_rejects_incomplete_inputs`, `test_verify_rejects_extra_inputs` |
| INV-08 Safe reuse | Unchanged evidence is fully revalidated; any changed dependency forbids reuse | `test_reuse_01…` through `test_reuse_10…`, `test_vertical_slice_admit_then_reuse_then_mutate` |
| INV-09 Exclusive publication | Exclusive creation, no overwrite, partial publication never counts as PASS | `test_store_01…` through `test_store_08…`, `test_store_noncanonical_committed_bytes_are_rejected` |
| INV-10 Scope isolation | Only synthetic/simulated can receive a new admission PASS | `test_scope_01…` through `test_scope_10…` |
| INV-11 No live authorization from metadata | Host data is diagnostic; readiness `clear` never authorizes acquisition | `test_host_01…` through `test_host_09…`, `test_host_closed_shape_rejects_mutation` |
| INV-12 Historical immutability | No tracked legacy bytes or BM-01 schema/CLI files are modified | `test_leg_01_historical_tracked_files_are_unmodified`, `test_leg_02_bm01_inventory_regenerates_byte_identically`, `test_con_01…`, `test_con_02…` |
| INV-13 No time acquisition | No controller, timer, profiler or `run` invocation | `test_cli_01_run_is_prohibited_before_side_effects`, `test_scope_06_no_run_measure_or_clock_spy_is_invoked`, `test_host_05_no_clock_or_subprocess_is_consulted` |
| INV-14 Fail closed | Unknown formats, changed validator/schema/source, incomplete authority or unexpected state never become PASS | `test_adm_04…`, `test_adm_05…`, `test_scope_08…`, `test_reuse_08…`, `test_reuse_09…`, `test_require_verified_locks_is_closed`, `test_index_rejects_*` |

## 2. Test-ID coverage map

| Plan ID | Test method(s) |
| --- | --- |
| CON-01/02 | `ContractImmutabilityTests.*` |
| CLI-01/02 | `CliRestrictionTests.*` |
| HASH-01…04 | `HashingTests.*` (`test_evidence_provenance.py`) |
| PATH-01…07 | `PathValidationTests.*` |
| ARC-01…11 | `TarInspectionTests.*`, `ZipInspectionTests.*` |
| PROV-01…09 | `GitProvenanceTests.*`, `BuildAndValidatorIdentityTests.*` |
| HOST-01…05 | `HostCapabilityTests.*` |
| HOST-06…09 | `ReadinessTests.*` |
| ADM-01…09 | `AdmissionVerticalSliceTests.*` |
| REUSE-01…10 | `ReuseInvalidationTests.*`, `ReceiptVerificationTests.*` |
| STORE-01…08 | `PublicationTests.*` |
| SCOPE-01…10 | `ScopeIsolationTests.*` |
| LEG-01…05 | `HistoricalImmutabilityTests.*`, `Legacy*ParityTests.*` |

## 3. Vertical slice

`test_vertical_slice_admit_then_reuse_then_mutate` executes the complete synthetic
path once:

strict spec parse → external anchor → five-lock verification (including Git
source and validator source bytes) → fd-confined raw hashing → TAR.GZ/ZIP member
verification → second input hash → canonical admission index → `receipt.v1` →
exclusive publication → independently anchored revalidation → idempotent
`REUSED_VERIFIED` → one changed evidence byte rejected.

`test_adm_06_mid_flight_input_change_is_rejected` mutates an input between the two
full hashes and asserts no output root is created.

## 4. Evidence quality rules applied

* Every rejection asserts a typed BM-01 error code or an explicit typed disposition.
* Rejected admission asserts that no output directory was created.
* Rejected reuse asserts committed receipt bytes are unchanged.
* Archive tests assert no extraction artifacts appear beside the archive.
* The synthetic golden anchor is a literal in test code, never recomputed from
  the fixture under test.
* Mutation tests compute a test-controlled anchor for the *mutated* spec only to
  exercise dependency mismatch; they never use that construction for the golden
  admission path.
