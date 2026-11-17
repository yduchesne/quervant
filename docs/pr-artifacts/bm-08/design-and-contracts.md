# BM-08 design and contracts

## Dominant invariant

A cross-engine study is eligible for a numeric comparison only for a frozen common
semantic lane, under correctly bound corpus/query/sort/cache/source identities. A
synthetic execution proves orchestration only, and no source or response projection
can be promoted to actual measured engine parity.

## Ownership (no new scheduler, statistics, verifier or publisher)

```
PR15D immutable spec / original adapter source files
          |                         |
 pure exact-term oracle      raw-byte source binding
          |                         |
   oracle-golden.v1.json  engine-source-bindings.v1.json
          \                        /
        semantic-comparability.v1.json   (16 legacy lane dispositions)
                      |
        workload.dataset.digest = canonical ledger digest
                      |
        synthetic-cross-engine-reference/ (8 BM-01 files + 3 companions)
                      |
        BM-03 SyntheticAdapter + seeded schedule + logical clock
                      |
        BM-04 analyze -> BM-05 verify -> BM-06 15-file A-E graph
                      |
        BM-07 shared read-only offline CLI (now two families)
```

`cross_engine.py` owns only: `REFERENCE_EXPERIMENT_ID`, the eleven-file registry,
`load_cross_engine_reference`, `validate_cross_engine_reference` and
`qualify_cross_engine_synthetic`. It contains no scheduling, statistics, policy,
verification, issuance or CLI logic.

## Validation order (producer)

1. `load_experiment_bundle` (frozen BM-01 loader) over the eleven-file catalog.
2. Exact file-set check: no missing, extra, symlinked or non-regular entries.
3. Bounded canonical read of the three companions.
4. `validate_oracle_golden` — recompute all 16 rows from the frozen arithmetic
   formula and compare hit counts *and* ordered `doc_id` lists.
5. `validate_engine_source_bindings` — stream every allowlisted adapter source file,
   verify byte length and SHA-256, and re-assert the literal version pins.
6. `validate_semantic_comparability` — closed ledger, exact digest chain, exact
   16 comparable lane IDs, exact three-row excluded-class table.
7. BM-01 workload/protocol/adapter identity checks and lane cross-checks against the
   reviewed golden.
8. Catalog-resident analysis/policy/resource profiles and scenario validated through
   the unchanged BM-04/BM-03 readers.

`qualify_cross_engine_synthetic` then runs exactly: scenario load → BM-03
`execute_synthetic` → require `status == "sealed"` → BM-06
`qualify_synthetic_run` → revalidate the companion digest tuple → return the
unchanged `QualificationResult`. A changed ledger during qualification is a typed
failure, never a pass.

## Validation order (offline reader)

safe workspace → unique UUID directory → allowlisted family → independent workspace
trust anchors → BM-01 bundle (+ cross-engine companion/source check) → BM-06
`load_qualified_synthetic_run` → second committed `load_bundle` with
digest/receipt/directory comparison → cross-engine companion **recheck** → existing
stage/view document.

## Falsifiable invariants and their counterexamples

| ID | Property | Positive test | Negative test |
|---|---|---|---|
| CE01 | Frozen source/family/engine IDs | `CAT-01` | `CAT-02` foreign identifier / extra arm |
| CE02 | Ledger binds goldens and sources | `BND-01` | `BND-02`, `BND-03` |
| CE03 | Only 16 warm keyword lanes analyzed | `CMP-01` | `CMP-02` cold/scored injection |
| CE04 | Frozen corpus formula for hits and IDs | `ORA-01`–`ORA-03` | `ORA-04`–`ORA-08` |
| CE05 | Closed untimed wire projection | `WIR-01`, `WIR-08` | `WIR-02`–`WIR-07` |
| CE06 | Source bytes/pins verified, no binary claim | `SRC-01` | `SRC-02`–`SRC-06` |
| CE07 | Only the synthetic simulator executes | `SIM-01`, `SIM-05` | `SIM-05` forged bundle |
| CE08 | Balanced reproducible schedule | `SCH-01` | `SCH-02`, `SCH-03` |
| CE09 | Effects/CIs independently known, non-performance | `ANA-01`–`ANA-03` | `ANA-04` |
| CE10 | BM-05 verifies derived candidates independently | `VER-01`, `VER-03` | `VER-02` |
| CE11 | 15 members, 7 receipt gates | `E2E-01` | `E2E-03`, `E2E-04` |
| CE12 | Never promoted to real/official | `SCOPE-01` | `SCOPE-02` |
| CE13 | Reuse verifies every identity | `REU-01` | `REU-02`, `REU-03` |
| CE14 | Offline selects exactly one of two families | `CLI-01`, `CLI-10` | `CLI-06`, `CLI-07` |
| CE15 | Offline verbs never derive/write/launch | `CLI-04`, `CLI-05` | `CLI-09` |
| CE16 | BM-07 retained-key CLI unchanged | `REG-01`–`REG-04` | `REG-03` |
| CE17 | Original PR15D bytes unchanged | `HIST-01`, `HIST-02` | recorded byte digests |
| CE18 | Excluded classes never contribute numerically | `CMP-03`, `ANA-05` | `CMP-04` |
| CE19 | New modules invalidate old anchors; final chain passes | `ANC-01`, anchored chain | `ANC-03` |
| CE20 | No real timed acquisition | `SAFE-01`–`SAFE-04` | static source scan |
| CE21 | Nofollow/publication failpoints | `CLI-08`, `CAT-04` | symlink mutations |
| CE22 | Implementation and correctness recorded separately | this artifact set | deviations listed below |

## Recorded plan deviations (reviewed decisions required before merge)

1. **Lane `field`/`term` are carried by `oracle-golden.v1.json`, not by BM-01 lane
   `params`.** The frozen `workload.v1.schema.json` declares
   `params.additionalProperties = false` with only `corpus_size`, `top_k`,
   `selectivity_class`, `query_id`, `batch_size`, `segment_count`. Adding `field`
   and `term` would require changing a frozen public v1 schema, which the plan
   prohibits. The reviewed oracle golden is the *stronger* authority: it is
   digest-bound into the ledger, and `validate_cross_engine_reference` cross-checks
   each lane's `(field, term, total_hits, doc_ids)` against it.
2. **`schedule.blocks = 6` instead of the prescribed 4.** The frozen
   `balanced-cyclic-v1` generator computes `tile_size = slots_per_block / gcd(counts)`
   = `6 / 2 = 3` and requires `blocks % tile_size == 0`; the control contract also
   requires even blocks. Four blocks are therefore unrepresentable: the controller
   raises `BM_IDENTITY_INVALID: schedule.blocks must be divisible by the balanced
   tile size 3` (reproduced for blocks 3/4/6/8/12). Six blocks is the smallest
   even multiple of three, so the observed slice is 12 control slots + 72 treatment
   slots = 84 slots, 1344 lane envelopes and 4032 synthetic samples. The plan's
   56/896/2688 values are recorded here as inapplicable rather than forced by
   changing controller arithmetic.
