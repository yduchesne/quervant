# PR 15I-D3-B-F1.1 — design and invariants

F1.1 is a **tooling/verifier fixup plus prospective measurement**, not a
production redesign. The optimization candidate, corpus, oracle, index format,
metrics, thresholds and schedule are unchanged.

## Prescribed changes

1. **Isolated namespace.** `benchmarks/pr15i_d3_b_f1_1/` is a plain copy of the
   F1 `run.py`, `verify.py`, `test_run.py`, `test_verify.py`, `README.md`, plus
   new `replay.py`, `test_replay.py`, `protocol_v1.json`,
   `tooling_manifest.json`. Historical F1/T0 directories are untouched.
2. **Protocol delta.** Exactly six top-level changes from the F1 protocol:
   `schema`, `study_type`, `comparisons` key (`d3bf11-base`), `tooling_directory`,
   `target_subroot`, `evidence_root_relative`. Everything else is recursively
   equal (gates, A/A, drift, lanes, schedule, corpus/hit counts, source policy,
   sentinels, `canonical_build`).
3. **F11-R1 inventory fix (verifier only).** Top-level `compile-source/` is
   excluded from the evidence inventory with explicit root-only logic; a root
   `compile-source` symlink or ordinary file is rejected, sealing any
   `compile-source/*` path is rejected, nested `compile-source` names are **not**
   exempt, all other unlisted members are rejected, and absence is allowed for
   archive-form verification.
4. **F11-R2 fingerprint split.** `preflight_host_fingerprint(environment)` keeps
   F1's preflight inputs (`allowed_cpus`). `host_fingerprint(attestation)` uses
   only sealed attestation fields and consumes `allowed_cpus_before_pin` under
   the canonical serialized key `allowed_cpus`, with strict shape validation.
   The independent verifier keeps its own implementation and must produce the
   identical digest for valid attestations.
5. **Rehearsal-only publication guard.** `publish` refuses fixtures with
   `rehearsal_only: true` or an exact `rehearsal`/`rehearsal-cases` path
   component, emitting `D3B_REHEARSAL_PUBLISH_FORBIDDEN` without writing bytes.
6. **Synthetic full-verifier rehearsal.** `replay.py` copies only the sealed
   members of the blocked F1 control, transforms identity/attestation metadata
   deterministically, reseals, and invokes the real F1.1 verifier as an external
   process for one positive and fifteen negative/invariance cases.

## Invariants → implementation → tests

| ID | Implementation | Tests |
|---|---|---|
| I01 | No edits under `benchmarks/pr15i_d3_b`, `benchmarks/pr15i_d3_b_f1` | preflight/postflight `git diff --exit-code`; T47 |
| I02 | replay never writes to the original F1 control; inventory before/after | T47, `replay.py` original-file audit |
| I03 | fixed BASE/candidate SHAs and Git blob checks | verifier `verify_sources`/`verify_frozen_inputs_for_revision`; T38 |
| I04 | no Rust/Cargo changes; source proof forbids rejected designs | `git diff`, T38 |
| I05 | one `compile-source` per campaign, sequential builds | F1 `build_provenance_failures`; T20? (rehearsal), I03/I04 |
| I06 | A/A two real builds, identical binaries | provenance verifier; T13, I05 |
| I07 | A/B same path, distinct binaries/sources | provenance verifier; T36/T38 |
| I08 | new F1.1 names/paths/protocol/tooling SHA only | T31, T36, T37 |
| I09 | root-only `compile-source` exemption; all else rejected | T21–T29 |
| I10 | `compile-source` never sealed/published/trusted | T25, T29, archive `_archive_members` |
| I11 | campaign fingerprint uses exact sealed CPU list | T01–T11, T20 |
| I12 | preflight fingerprint separate, keeps `allowed_cpus` | T18, T19 |
| I13 | controller/verifier identical digest | T01, T04, T20, T31 |
| I14 | verifier does not import `run.py` | import audit test |
| I15 | protocol/tooling digests verified from committed bytes | T37, T45/R15 |
| I16 | synthetic fixtures cannot publish | T45, T46 |
| I17 | rehearsal uses every original sample/oracle intact | R01–R03, T40 |
| I18 | oracle/seal/slot/affinity/provenance corruption rejects | R02–R15 |
| I19 | A/A/A-B thresholds unchanged | T32–T35 |
| I20 | P00–P08 unchanged | T33, T39–T44 |
| I21 | index/corpus sentinels unchanged | T35, control evidence |
| I22 | 16 slots × 9 lanes × 20 samples × 5 warmups × 2 probes, ABBA schedule | T34, I05 |
| I23 | affinity + native FS roles unchanged | R10–R12, F1 host tests |
| I24 | status comes from the independent verifier | I06/I08/I10 receipts |
| I25 | no claim from blocked/synthetic/single campaign | T43–T46, docs |
| I26 | K10/low-hit gates on both A/B runs | T33, T39–T42 |
| I27 | qualified rejection → additive rollback | §7 procedure; rollback tests |
| I28 | structural block leaves candidate intact | T42, decision register |
| I29 | idle assumption never replaces contention evidence | I05 + verifier probes |
| I30 | immutable exclusive evidence | T45/T46, publish tests |
| I31 | post-T2 tooling drift blocks timing | `assert_tooling_clean` + T37 |
| I32 | ≥85% Rust coverage and real boundaries | `qa.md` |

## Non-authorization

No algorithm change, no corpus/oracle/index/metric/threshold change, no new
dependency, no Rust flag change, no production edit unless a fully qualified
paired campaign rejects performance (additive BASE restore per §7).

## Independent oracle

Frozen PR15D generator/spec/oracle, imported read-only and checked by frozen
SHA-256; the verifier regenerates the corpus and recomputes IDs/hit counts. The
rehearsal reuses historical *samples* as synthetic data only; its metadata is
explicitly labelled `SYNTHETIC_REHEARSAL_ONLY`.
