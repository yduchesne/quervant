# PR 15I-D1-F — execution status

**Disposition: `D1F_C2_PERFORMANCE_REJECTED_ROLLED_BACK`.**

| Item | State |
|---|---|
| BASE | `a53ee021acbe5f30db2b3298a11fcd99e72c2945` (`STACKED_ON_D0_COMPAT_BASE`) |
| F0 frozen tooling | `5eac5caff04dd2974f3ffd7553faa270b2c50927` |
| F1 postmortem docs | `422fd91` |
| Measured C2 (rejected) | `b328b83cdb6ea53af08b7591a0c1bd6128ba0dcf` |
| Additive C2 rollback | `051c3193159b97dd5723e431e21ac2222bd2963e` |
| Final production source | byte-identical to BASE (`git diff BASE..rollback -- crates/` empty) |
| Historical C1 | `2360172…`, still `D1_C1_PERFORMANCE_REJECTED` |
| C1 cause finding | `CODEGEN_DIFFERENCE_OBSERVED_CAUSALITY_UNPROVEN` |
| A/A control | `c2-base-aa-01` — `CONTROL_QUALIFIED`, archived |
| Paired campaign 01 | `c2-base-01` — `CAMPAIGN_REJECTED` (FC2-P01), archived |
| Paired campaign 02 | not run (FDX-23 stop rule) |
| RustFS | `RUSTFS_PENDING` |
| Hosted CI | `CI_PENDING` |
| Independent review | `REVIEW_PENDING` |
| PR | `PR_NOT_CREATED` |

## What was executed

1. **Preflight:** verified BASE, the frozen production blobs, the D0 lock and
   two locked adapter builds; audited every historical C1 archive/sidecar and
   re-ran the frozen D1 verifier (all PASS, original statuses preserved).
2. **F1 postmortem:** proved the C1 K10 source bypass and the corresponding
   legacy-scan branch in the exact historical binary. Classified the measured
   K10 delta as codegen-difference-observed with causality unproven. The
   original C1 rejection is unchanged and no C1 code was fixed or re-measured.
3. **F2 C2:** implemented `doc_key_view` over the existing validated,
   snapshot-shared DOC_KEYS offsets and a private `CandidateKey` that owns only
   on admission/legacy fallback; added K01–K16 tests. Correctness, formatting
   and Clippy were clean at F2.
4. **Measurement:** one qualified A/A control (two independent builds of the
   same BASE tree, identical binaries) and one sealed `c2-base-01` campaign.
   `c2-base-01` was structurally valid but failed `FC2-P01`: 100K common/K100
   was slower by 841,226 ns and 100K common/K10 improved by only 1,570,665 ns
   (below the 2,000,000 ns primary win). All guards passed; 100K medium/K100
   improved by 3,397,628 ns.
5. **Rollback:** published negative evidence, restored both production files to
   exact BASE bytes and removed the C2 test file. `c2-base-02` was not run.

## Decision-matrix log

| ID | Observation | Action |
|---|---|---|
| FDX-01 | BASE exists, frozen blobs match, two locked builds pass | Pinned BASE |
| FDX-02 | Historical C1/T0 commits and archives verify | Performed F1 audit; no historical mutation |
| FDX-05 | C1 source contains the K10 `heap_limit <= 32` fallback on all candidate paths | Recorded source-level bypass only |
| FDX-07 | Exact historical binaries available and match seals; rebuilt BASE is not byte-identical | Inspected the historical binaries; labelled rebuilt binaries `REBUILT_FOR_INSPECTION` |
| FDX-09/10/11/12 | Valid offsets / missing budget / single-hit / legacy fallback | Implemented and tested exactly (K01–K05, K09, K11) |
| FDX-13/14/15 | Duplicate retained key / losing candidate / winning candidate | Literal scan preserved; no ownership for losers; one owned key at admission |
| FDX-21/22 | First A/A attempt was drift-blocked and disclosed a two-worktree binary discrepancy | Published nothing; after complete quiescence ran the one authorized retry with independent builds of the same BASE tree; it qualified and was archived |
| FDX-23 | `c2-base-01` failed a valid FC2 gate | Published negative evidence, stopped campaign 02, rolled back additively |
| FDX-26 | RustFS unavailable; no CI/PR credentials assumed | Recorded `RUSTFS_PENDING`, `CI_PENDING`, `PR_NOT_CREATED` |
| FDX-27 | Both user timers active+enabled | Paused for measurement, restored to exact original state |

No post-F0 tooling defect was found; no benchmark command or threshold was
changed after F0.

## Residual risks

- The exact cause of the historical C1 K10 block remains unproven; no causal
  share is claimed.
- A duplicate retained key cannot be injected through the public writer; the
  unchanged literal scan plus existing corruption suites cover fail-closed
  behaviour, with residual review risk.
- Evidence archives share the repository's virtual disk and are not an off-host
  backup.
- Real RustFS and hosted CI remain unexecuted.

## Final state

Production is byte-identical to BASE; no optimization from this experiment is
shipped. The historical C1 rejection is preserved, and the C2 negative result
is documented with complete sealed evidence.
