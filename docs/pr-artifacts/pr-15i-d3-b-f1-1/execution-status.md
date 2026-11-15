# PR 15I-D3-B-F1.1 — execution status

**Disposition: `D3BF11_MEASUREMENT_BLOCKED`.**

| Item | State |
|---|---|
| Branch | `dev/pr15i-d3b-retained-key-prefilter` |
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` |
| Candidate source | `48d9abf3eeefbccb480d89eac95f6e6911e078d5` |
| Historical D3-B T0 | `155ebafafa29fb0e6b6cbf953f89445f4880fd2f` (untouched) |
| Historical F1 T1 | `ac45c23fd5a8862898e4d4502a4bfc684e4dfc82` (untouched) |
| F1.1 T2 tooling freeze | `63b30a0be451357a5edaf8399ad2e4d336e6c45b` |
| F1.1 protocol SHA-256 | `ae1b7d8d9ab638e70cddb1e52d0b9dd063ccdffae74826ab67728db42a095b4c` |
| F1.1 tooling manifest SHA-256 | `f9134926cbe372b628f6248aa7f846a52455ebaedaa6b2a741f402796295e250` |
| Synthetic rehearsal | `SYNTHETIC_REHEARSAL_VERIFIER_PASS`, 16/16 expected cases |
| Control 01 | `CONTROL_QUALIFIED` (independently verified, archived) |
| Control 02 | NOT_RUN |
| Paired 01 | `MEASUREMENT_BLOCKED` (independent verifier PASS; structural drift failure) |
| Paired 02 | NOT_RUN (no paired retry authorized) |
| Series P08 | `MEASUREMENT_BLOCKED` / `FAIL` |
| Production diff | Candidate retained unmerged; **no rollback** (structural block, not a performance rejection) |
| Rust QA / coverage | PASS — 2,496 tests, 92.85% lines, stable and MSRV 1.85 |
| Python QA | PASS — 143 F1.1 tests, 95 F1 tests, 61 D3-B tests, 83 PR15D harness tests |
| RustFS | `RUSTFS_PENDING` |
| Hosted CI | `CI_PENDING` |
| Independent review | `REVIEW_PENDING` |
| PR | `PR_NOT_CREATED` |

## What was executed

1. Reconciled the pinned branch/BASE/candidate/T0/T1 identities, the original
   F1 control seal and the historical archive; confirmed the two defects by
   read-only inspection and wrote the preflight, design/invariant and test
   matrices before editing.
2. Created the isolated F1.1 namespace with the prescribed six-field protocol
   delta; fixed the root-only `compile-source` inventory exclusion and split the
   preflight/campaign fingerprint contracts with strict validation; added the
   rehearsal-only publish guard and a 48-test fixup matrix.
3. Ran the full synthetic rehearsal: the real F1.1 verifier accepted a
   deterministically transformed copy of the blocked F1 control
   (`SYNTHETIC_REHEARSAL_VERIFIER_PASS`) and rejected all fifteen adversarial
   mutations with the exact expected codes; the original F1 files were unchanged.
4. Froze T2 = `63b30a0b…` after two pre-T2 harness corrections (both failed
   rounds preserved) and ran the official 16-slot canonical A/A control. Two
   real builds from one path produced byte-identical binaries; the independent
   verifier PASSED with all nine A/A ratios in bounds, no drift, identical 100K
   indexes and 32/32 clear probes. The control was archived.
5. Ran paired campaign 01. Both sources/binaries were correctly distinct and
   all nine lanes/oracles were intact, but arm A block 2 `10K rare` had a
   within-block drift ratio of 1.503058 > 1.50. Per the frozen rules this is a
   structural qualification failure: campaign 01 is `MEASUREMENT_BLOCKED`,
   campaign 02 was not run, no performance verdict is authorized, and the
   candidate was not rolled back. The blocked evidence was independently
   verified and archived.

## Diagnostic observations (not an acceptance verdict)

On the structurally unqualified campaign 01, 100K common/K100 improved by a
median 10,114,578 ns and 100K medium/K100 by 2,437,975 ns, while 100K common/K10
was 540,643 ns slower (40,643 ns below the frozen −500,000 ns median floor).
These values are recorded for transparency only.

## Next human decision

Authorize a new plan/freeze with fresh campaign names and a host-noise strategy
that preserves the frozen thresholds, or abandon the candidate. The consumed
official names and the archived blocked evidence must not be re-used or
reclassified. No merge is authorized.
