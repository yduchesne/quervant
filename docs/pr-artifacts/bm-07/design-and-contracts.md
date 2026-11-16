# BM-07 pre-implementation correctness gate

Status: **PASS (design recorded before production edits).**

This document is the mandatory pre-implementation gate required by the BM-07
execution contract. It records the observed repository state, the mapping from
R01–R20 to executable evidence, the threat model, and the false-PASS
counterexamples that must be rejected. It is descriptive only: no production
behaviour is defined here.

## 1. Observed baseline (recorded before implementation)

| Fact | Observed value |
|---|---|
| Reviewed BM-06 fixup commit | `314cafdbcdd78774a037de609d47b8427b0717db` |
| Actual `main` merge commit | `b6de92d0fb6cc6ac9b9fe718bc3f6a1ebe909c60` (`Merge pull request #107`) |
| `git merge-base --is-ancestor 314cafd main` | success |
| BM-07 branch | `dev/pr-bm07` from actual `main` |
| Working tree at start | clean |
| Existing Python suite (baseline) | 772 tests, 1 established skip, PASS |
| Existing qualification suite (baseline) | 109 tests, PASS |
| BM-06 source-set digest before BM-07 | `sha256:d8f782f3db1cacbc22deead7717e984027ca1039795bd22b42471c9a94b15da4` |
| Qualification profile digest | `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c` |
| Checked-in framework QA anchor | `sha256:de486da134604edf53746375af66d2f1a22efff0c940c4238e4b5deeb8cc646e` |
| Checked-in source QA anchor | `sha256:e86ef1a692915a0ce9208f812774d1d8f9ff7fc3251c42a058f44d314806151a` |
| D3-C frozen protocol SHA-256 | `c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c` |
| External D3-C archive `target/pr15i-d3-c` | directory stub, no entries |
| Python | 3.12.3 |
| PyYAML / jsonschema | 6.0.1 / 4.10.3 (CI installs the pinned versions) |

### Capability classification

| Capability | Classification | Evidence |
|---|---|---|
| BM-01 catalog/CLI/inspect/`run` exit 77 | DONE + VERIFIED | baseline `test_cli.py`, `test_schemas.py` |
| BM-02 safe paths/hashing | DONE + VERIFIED | baseline evidence suites |
| BM-03 synthetic execution/replay | DONE + VERIFIED | baseline execution suites |
| BM-04 derivation/policy | DONE + VERIFIED | baseline analysis suites |
| BM-05 independent verification | DONE + VERIFIED | baseline verification suites |
| BM-06 A–E qualification/publication/reuse | DONE + VERIFIED | baseline qualification suites |
| New retained-key synthetic catalog | NOT STARTED | this PR |
| Offline five-verb CLI views | NOT STARTED | this PR |
| Historical parity evidence | BLOCKED | external archive absent (`EVIDENCE_UNAVAILABLE`) |

No existing BM-03/BM-04/BM-05/BM-06 algorithm, receipt, publisher or public v1
schema is changed by this design. The only existing production edit is the single
`qualification/identity.py::SOURCE_DIRECTORIES` tuple entry authorising the new
`benchmarks/quervant_bench/migrations` package.

## 2. R01–R20 traceability

| ID | Exact test evidence | Affected source | Threat model |
|---|---|---|---|
| R01 | CAT-01, CAT-02 | new eight-file catalog | A semantic edit silently unbound from its declared digest |
| R02 | PRO-01, PRO-02 | new catalog + frozen schedule compiler | Missing/duplicated arm slot changes the study design |
| R03 | SIM-01, SIM-02, SIM-03 | BM-03 APIs only | Blocked readiness or failed oracle is bypassed |
| R04 | SAFE-01, SAFE-02 (`run` exit 77) | `cli.py` | A CLI path accidentally launches acquisition |
| R05 | CAT-03, CAT-04, `test_reference_expectations_are_literal` | new catalog + ledger | Non-synthetic/float/zero/unknown samples enter the study |
| R06 | ANA-01…ANA-04 | BM-04 unchanged | Policy/CI/memory boundaries are relaxed to force a pass |
| R07 | VER-01…VER-03 | BM-05 unchanged | Primary output is forged and only self-hashed |
| R08 | E2E-01 | BM-06 unchanged | A 15-file simulated attestation is incomplete |
| R09 | REU-01…REU-06 | BM-06 unchanged | Stale source/QA/seal is accepted on reuse |
| R10 | SCOPE-01, SCOPE-02 | catalog + qualification scope | Simulated evidence is relabelled official/historical |
| R11 | CLI-01…CLI-07 | `cli.py`, `migrations/offline.py` | Offline flag implicitly enabled or inspect semantics drift |
| R12 | CLI-08, CLI-09 | `migrations/offline.py` | Read-only display re-runs acquisition/derivation or writes |
| R13 | CLI-10, CLI-11 | `migrations/offline.py` | UUID collision or unbounded scan selects the wrong run |
| R14 | CLI-12, CLI-13 | BM-06 loader + offline adapter | A self-consistent forged bundle is displayed as trusted |
| R15 | LEG-01, LEG-02 | historical paths | A migration rewrites frozen historical source |
| R16 | PAR-01, PAR-02 | `migrations/historical_retained_key.py` | A synthetic stand-in is called authentic history |
| R17 | PAR-03, PAR-04 | historical ledger | A different arithmetic contract is massaged into a match |
| R18 | ANC-01, ANC-02, ANC-03 | `qualification/identity.py` + QA fixtures | New migration source is omitted from the trust root |
| R19 | REG-01, REG-02 | repository QA | A duplicate service or schema drift enters the PR |
| R20 | REP-01, REP-02 | PR artifacts | A stale/failed check is reported as accepted |

## 3. Mandatory false-PASS counterexamples

1. **Same valid self-hashes with an untrusted run.** A committed directory whose
   manifest and receipts are internally consistent but whose subject, scenario,
   seal or source set is foreign must be rejected by BM-06 reuse. Evidence:
   CLI-13 and REU-02…06.
2. **UUID ambiguity.** Two experiment directories containing the same run UUID
   must reject with `BM_IDENTITY_INVALID`; the resolver must never choose the
   first match. Evidence: CLI-11.
3. **Legacy median-of-four versus the paired statistic.** D3-C
   `median4(v) = sorted(v)[1]` is the lower-middle value of four ratios, while
   BM-04 uses slot medians, block means and paired-ratio medians. A literal
   counterexample (`[1, 2, 100, 200]`: 2 versus 51) proves that no tolerance can
   make H04/H05 exact. Evidence: PAR-03.
4. **Negative synthetic availability/scope.** A missing workspace, missing
   archive or relabelled scope must produce a typed refusal and empty stdout,
   never an implicit synthetic fallback. Evidence: CLI-11, SCOPE-02, PAR-02.
5. **Missing QA anchor.** The offline workspace anchor document is an independent
   caller trust root; it must not be derived from the candidate manifest. A
   missing/malformed anchor is rejected before BM-06 opening. Evidence: CLI-13.
6. **Source changes invalidating the BM-06 fixture digest.** Adding migration
   modules and tests changes the source-set digest. The checked-in QA fixtures
   must be re-frozen once from the final tracked source, and a stale anchor must
   fail. Evidence: ANC-01/02/03.
7. **`inspect` result accidentally output as a new success schema.** The five
   offline verbs return either an existing BM-06 stage document or one of the two
   closed internal views; `outcome.v1` success remains restricted to the inspect
   summary. Evidence: CLI-01…CLI-06.

## 4. Decision-matrix use

* D03: actual `main` equals the assumed merge commit; no drift.
* D06: new YAML declarations use JSON syntax, accepted by the existing safe YAML
  loader.
* D11: expected effects are literal constants in the checked-in ledger, not
  derived by running the producer.
* D17: local Python is available and imports work under `PYTHONPATH=benchmarks`;
  installed console entrypoint is CI-owned.
* D34/D35: `target/pr15i-d3-c` is a stub, so historical evidence is
  `EVIDENCE_UNAVAILABLE` and parity is `NOT_EXECUTED`.
* D43: the source roster changes and QA anchors will be re-frozen exactly once
  after all Python source and tests are final.
* D50: local RustFS is not required for this Python-only feature; real RustFS
  remains a CI-owned gate.
* D57: `cargo bench --no-run` is compile-only evidence, never timing.

## 5. Non-goals and safety boundaries

No real timed acquisition, no wall clock, no engine subprocess, no historical
controller/policy writer, no archive mutation, no legacy retirement, no new BM-01
schema, no new error code, and no duplicate statistics/policy/attestation
implementation. All synthetic samples remain declared integer nanoseconds.
