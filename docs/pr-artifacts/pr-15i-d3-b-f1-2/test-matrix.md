# PR 15I-D3-B-F1.2 — test matrix

## Readiness RD-01..RD-30 — 30/30 PASS

`test_readiness.py` uses an injected fake monotonic clock/tick source and direct
integer arithmetic; no real sleep or `/proc` read in unit tests.

| IDs | Coverage |
|---|---|
| RD-01..05 | valid fixture, 251‰ floor, single soft interval, median 101/100 |
| RD-06..07 | steal 21‰ rejection / 20‰ acceptance |
| RD-08..11 | interval 800/1500 ms and settle 4500/7500 ms inclusive bounds; 799/1501 and 4499/7501 reject |
| RD-12..17 | missing/duplicate/malformed/huge counters, aggregate-line rejection, decrease/zero delta, guest fields, bad CPU pair |
| RD-18 | unsupported/missing `/proc` fail-closed |
| RD-19..28 | verifier shape, tampered metrics/derived fields, frequency advisory, CPU-pair vs host attestation, no legacy fallback, seal/manifest digest, readiness failure is not a replacement, independent arithmetic |
| RD-29..30 | iowait non-idle, guest not double counted |

## Succession SC-01..SC-36 — 20 test methods, all rows covered

`test_succession.py` asserts both `run.decide_next_attempt` and the independent
`verify.succession_next`, plus `classify_attempt`, `plan_attempt_succession`,
`verify_succession` and `_archive_identity`.

| IDs | Coverage |
|---|---|
| SC-01..16 | full ordered state table (empty, P/D/R prefixes, replacements, terminals) |
| SC-17..22 | invalid evidence, readiness failure, non-drift structural block, drift PASS without violations, unexpected drift gate, P03-only rejection |
| SC-23..25 | third attempt after two passes, suffix gaps/unknown 04, third after no drift |
| SC-26..29 | predecessor hash/control/host/name/duplicate/absent succession |
| SC-30..32 | drift + P03 diagnostic, multiple drift violations = one attempt, changed predecessor source |
| SC-33 | missing/mismatched archive sidecar |
| SC-34..35 | `EMBEDDED_ONLY` scope (full-series scope proven by rehearsal) |
| SC-36 | chronology, not performance-order selection |

## Rehearsal RH-01..RH-16 — 16/16 expected

See `rehearsal.md`. Positive control, paired and series; replacement chain;
missing/tampered readiness; wrong CPU; predecessor tamper; two drift-only
attempts; P03 rejection; extra attempt; hidden file; original integrity; publish
guard.

## Integration IN-01..IN-18

| ID | Result |
|---|---|
| IN-01 | official preflight PASS on pinned BASE/candidate |
| IN-02 | control: two real same-path BASE builds, identical binary SHA/size |
| IN-03 | campaign: same-path BASE→candidate builds, distinct binaries |
| IN-04 | synthetic control external verifier PASS with readiness |
| IN-05 | synthetic two-campaign series P08 PASS (`FULL_SERIES`) |
| IN-06 | synthetic drift+two-pass replacement series P08 PASS, one excluded |
| IN-07 | controller refuses 03 after two passes (SC-23) |
| IN-08 | controller refuses 02 after qualified P03 rejection (state machine) |
| IN-09 | readiness failure is not a drift replacement (RD-27/SC-18) |
| IN-10 | readiness collected after builds/indexes, before first slot; failure leaves no slots/seal |
| IN-11 | control archive extracted without build/index/corpus/compile-source: verifier PASS, `UNAVAILABLE_ARCHIVE` |
| IN-12 | predecessor archive-sidecar mismatch is rejected (SC-33) |
| IN-13 | altered sealed slot without reseal → `V_SEAL` (F1.2 inherited `test_f11_t29`) |
| IN-14 | resealed synthetic sample changes are rederived; official evidence untouched |
| IN-15 | wrong 100K bytes/sentinels → structural failure (`V_INDEX`, inherited tests) |
| IN-16 | F1.2 verifier on an F1.1 directory → rejected (`V_PATH`), no fallback |
| IN-17 | F1.1 verifier on an F1.2 directory → rejected (`V_PATH`), no fallback |
| IN-18 | RustFS harness started and health-checked; production adapter exercised separately by the pre-existing m1/m2 real RustFS tests |

Inherited suites: F1.2 193 tests, F1.1 143, F1 95, D3-B 61, PR15D harness 83 (3
skipped), all PASS.
