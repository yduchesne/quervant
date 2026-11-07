# PR 15I-A — invariant traceability and counterexamples

Every invariant below names the code owner and the falsifiable test that fails
if the property is broken. Counterexamples are the adversarial fixtures the
tests actually build.

| ID | Invariant | Owner | Tests | Concrete counterexample that must fail |
|---|---|---|---|---|
| IA-01 | Equal logical state plus equal V2-history mode encodes to byte-identical V3 files, independent of insertion order | `index/mutation_state.rs` | U01, U02, U03 | Two live rows sharing a segment inserted into the maps in opposite order; the test requires identical bytes and a one-entry table |
| IA-02 | Every V3 table ID is nonempty, valid UTF-8, unique, sorted by raw bytes and referenced by at least one live row | codec | U04–U12, U18, U43 | Crafted payloads with `["s-a","s-a"]`, `["s-b","s-a"]`, `[""]`, `[0xFF]`, an unreferenced second entry, or a live row with a missing pointer |
| IA-03 | Ordinals are zero based, canonical LEB128, `u32` representable and in-table; doc IDs are canonical unsigned `u64` varints | codec | U13–U20 | Crafted ordinal `D`, `D+1`, `u32::MAX+1`, `0x80 0x00`, and 11-byte continuations; doc ID `0xFF..0x02` overflow |
| IA-04 | V3 decodes to exactly the V1/V2 logical state for the same rows, tombstones, revisions, replay records and pointers | codec | U21–U25, I01, I02 | V1/V2/V3 encodings of the same state decoded and compared tuple-by-tuple; V2/V3 replay body suffixes compared byte-for-byte |
| IA-05 | V1 golden unchanged; V2 readable; V3 requires `0x000C/1`; older readers reject V3 before payload interpretation | codec/format/manifest | U26–U33, C02, I03 | Frozen V1 fixture SHA; V3 feature in optional-only; required V3 with a V1/V2 payload; unknown `0x7FFF` feature |
| IA-06 | New commits always write V3; inherited V2 history is retained; V3 is never silently downgraded | writer/merge | I04–I08 | Legacy V1/V2 generation is upgraded on a real commit; a later untokened commit keeps the V2 marker; no-op commit/compaction leaves generation and object count unchanged |
| IA-07 | No committed reader sees a partial sidecar; failed writes cannot advance `CURRENT`; old snapshots retain old objects | writer/Directory | F01–F07, R01–R04 | Injected sidecar create/partial-write failure, manifest failure after sidecar upload, `CURRENT` failure before/after replacement, withheld remote sidecar |
| IA-08 | Decoder enforces per-allocation, entry, retained-byte, encoded-sidecar and aggregate limits before allocation | codec/limits/index | U34–U41 | Small custom limits with crafted count headers; exact/one-over dictionary, usage-bitmap, row and aggregate budgets |
| IA-09 | Results, `total_hits`, winner visibility, revision and replay are unchanged across restart/compaction | index | I01–I08, R01–R04 | Upsert/delete followed by fresh-process reopen, PIT held across compaction, replay-heavy restart and tokened replay |
| IA-10 | Candidate reaches every frozen storage/performance threshold without cherry-picking | bench | `benchmarks/pr15i_a/run.py` + `verify.py` | Paired A/B campaign; every block must pass, not just the median |
| IA-11 | PR 15D/15I-0 seals, code and reports are unchanged | review | scope check in `run.py`; `git diff A..B` | Any changed path outside the allowlist is a hard `A_SCOPE` block |
| IA-12 | Required production/RustFS gates execute in their authoritative topology | QA/CI | I/F/R suites, workspace QA, hosted CI | A skipped `#[ignore]` RustFS run is reported as `BLOCKED`, never PASS |

## Physical subsumption recorded for U36

`size_of::<&str>()` (16 on the supported 64-bit targets) is larger than
`size_of::<u8>()` (1), so the dictionary-reference allocation check always binds
before the byte-per-entry usage bitmap for the same `D`. The decoder still calls
`check_alloc::<u8>(D)` and charges `D` bitmap bytes; U36 asserts that exact call
at its boundary and the traceability record documents why a decode-level
differential cannot make the bitmap the binding constraint.

## Faulty-V3 scenarios a naive round-trip test would miss

| Scenario | Refuting test |
|---|---|
| Unused dictionary entry smuggled into the table | U10 |
| Out-of-range ordinal silently wrapping | U15 |
| Required V3 marker missing or optional-only | U28, U29 |
| V3 payload interpreted by a pre-V3 reader | U33 |
| Replay corruption hidden by a successful key decode | U20, U22, U23, U40 |
| Stale pointer accepted after compaction | I07 |
| Decode-allocation preflight bypassed by a huge count header | U34, U39 |
| Sidecar/manifest feature disagreement | I03 |

## Independent-verifier invariants (review fixup)

| ID | Invariant | Test |
|---|---|---|
| IA-FI01 | `A-P10`/`A-P11` require exact V3 features/version and independent oracle agreement for every warm lane | FT-A32–A38, FT-A43, FT-A44 |
| IA-FI02 | `A-P12` requires all source, protocol, authorization, corpus, binary, contention, block and seal proofs | FT-A09–A27, FT-A42, FT-A54 |
| IA-FI03 | Exactly twenty safe sealed primary files plus 32 bound auxiliary probes; no extra/symlinked raw entries | FT-A02–A08c |
| IA-FI04 | 16 slots × 9 lanes × 5 warmups × 20 samples and four blocks × two samples match the frozen matrix | FT-A20–A31, FT-A34 |
| IA-FI05 | A/B source identities, ancestry and change allowlist match the frozen measured pair | FT-A09–A11, FT-A24, FT-A51 |
| IA-FI06 | Manifest, measurements, slots, build outputs and published reports reconcile | FT-A45, FT-A52 |
| IA-FI07 | A sidecar V1 and B sidecar V3 with exact required features and byte accounting | FT-A35–A41, FT-A43 |
| IA-FI08 | Verification leaves every original byte unchanged | FT-A50, FT-A46/A47 |
| IA-FI09 | Failures exit nonzero without any `VERIFIED` classification | FT-A02–A48 |
| IA-FI10 | Local QA, hosted CI and human review remain separate statuses | FT-A49, FT-A53 |

The authoritative verifier is `benchmarks/pr15i_a/verify.py`; the legacy
`run.py --verify-only` route is disabled (FT-A48).
