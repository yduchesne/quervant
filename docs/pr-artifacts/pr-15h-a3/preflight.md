# PR 15H-A3 — preflight

**Plan:** `QUERVANT_PR15H_A3_DETAILED_INVESTIGATION_PLAN.md`
**Branch:** `dev/pr15h-a3-sparse-regression-investigation`
**Branch base / final A2 HEAD:** `d398af5e2dc354f19b209ce53df62f78d12e26f8`

## 1. Commit graph (verified locally, same object database)

```
git cat-file -e 7a136f7…^{commit}   present
git cat-file -e 569132d…^{commit}   present
git cat-file -e dce8f02…^{commit}   present
git cat-file -e 9aff92b…^{commit}   present
git cat-file -e d398af5…^{commit}   present
git merge-base --is-ancestor 7a136f7… 569132d…   exit 0
```

| Identity | SHA |
|---|---|
| Accepted source A | `7a136f7f299c2f460401b9d92dcef37d219ea98c` |
| Rejected A2 candidate B | `569132dace8d92c103dfdebd5d24167d65c0c0c0` |
| Original 15H-A candidate (context only) | `dce8f02405e6541d478c2072a0332af192ed2945` |
| A2 historical tooling | `9aff92b6b1a12ee323ed7994a177f88949c736fd` |
| A2 final HEAD | `d398af5e2dc354f19b209ce53df62f78d12e26f8` |
| A3 harness-only tooling (`A3_TOOLING_SHA`) | `7e23335ef1862d27801b198965ebc4a4804becde` |

A3-D01/D03/D05 all satisfied. No reconstruction or cherry-pick of A1 was used.

## 2. Accepted-search equality

```
git diff --quiet 7a136f7… d398af5… -- crates/quervant-core/src/search   exit 0
git diff --quiet 7a136f7… A3_TOOLING_SHA  -- crates/quervant-core/src/search   exit 0
```

A2 final production search is byte-identical to accepted `ddcbe778` search via
`7a136f7` (A3-D04/D06/D70).

## 3. A2 source reconciliation

- `569132d` differs from `7a136f7` only in `execute.rs` and `unified.rs`.
- `unified.rs` production code is unchanged; the diff adds the historical
  `#[cfg(test)]` tests and A2 route tests.
- `execute.rs` adds the historical helper, the single constant
  `const H_A2_MIN_POSTINGS: usize = 8_192;`, the dispatch guard
  `single_term_posting_count`/count comparison, and test-only witnesses/tests.
- Helper region hashes (independently re-extracted from `569132d`):

| Region | SHA-256 |
|---|---|
| `evaluate_single_term_linear` | `966554bccc5d5d5a852c53713ec566122981de480a40157e92b7e6be100f1592` |
| `score_single_term_linear` | `9b811a609f4be3d16543b10a811325f1f2c417021d750966d559d5a2a4cf40ac` |

  They match the same regions at `dce8f02` (A3-D07/D12). No unreported scorer,
  ledger, codec or `collect_mixed` mutation was found (A3-D08).

## 4. A2 historical seal verification (read-only)

Using the A2 tooling checkout at `9aff92b` and the original sealed directories:

| Campaign | `verify-only` | Seal SHA-256 |
|---|---|---|
| `baseline-01` | PASS | `14836343626f35642e2eae472aac47af73b8b567f99811ea3d50d8e5ddebf2ec` |
| `paired-01` | PASS | `aac028d5107c085872226edaf4756a80cb31ee5e047678a7abac3f8c0c0bbd2b` |

The A2 verdict was `PERFORMANCE_REJECTED` (HA2-P04 guard failure) and remains
unchanged (A3-D10). No raw A2 evidence was rewritten.

## 5. Toolchain / environment

| Fact | Value |
|---|---|
| `rustc` | `1.98.1 (48a229cea 2026-09-01)` |
| `cargo` | `1.98.1 (797e8a9bc 2026-08-05)` |
| MSRV `cargo` | `1.85.0 (d73d2caf9 2024-12-31)` |
| Python | `3.12.3` |
| Filesystem | ext4 (native) |
| `objdump` / `readelf` / `nm` | GNU binutils 2.42 |
| `llvm-objdump` | absent |
| `perf` | **not available** (`perf not found for kernel 6.18.33.2-microsoft`; `perf_event_paranoid=2`) |
| Profiling | `PROFILE_UNAVAILABLE` (A3-D44); no packages installed |

## 6. Pre-implementation counterexample challenge

| Invariant | Counterexample considered | Resolution |
|---|---|---|
| I03/I04 | B or helper text inferred from the A2 report rather than the object DB | Re-extracted from `git show 569132d`; hashes match; no report-only assumption |
| I05 | Sparse route might still call the helper despite the gate | A2 unit witnesses (`phase15h_a2_tests`) reconfirmed in the candidate worktree: 0/1/4,999 → 0 helper calls; 8,192+ → 1 |
| I08 | A fifth or process-cold lane could be substituted | Controller has a canonical four-lane tuple and rejects drift (A3-B01/B02/B03) |
| I09–I11 | A tampered summary or oracle could pass | Strict record validation, nearest-rank recomputation and expected-hit/doc-ID checks |
| I12–I15 | A blocked A/A could be mistaken for an A/B result | AA and AB are separate stages; AA failure emits `MEASUREMENT_BLOCKED_AA_CONTROL` and stops later stages |
| I16/I19 | Disassembly difference interpreted as a cause | `MEASUREMENT_BLOCKED` precedence; codegen recorded as observation only |
| I17 | V2/V3 edits could drift | Controller checks the exact one-line/one-attribute diff; variants not created because A/B was not authorized after AA blocked |

## 7. Frozen experiment

Four warm lanes in fixed order (`absent/100K`, `rare/100K`, `rare/10K`,
`common/100K`); AA=4 slots, AB=8 slots, BV2/BV3=4 slots; 5 warmups/20 samples;
AA caps 1.15 (100K)/1.20 (10K); drift caps 1.25/1.50; reproduction requires
S1/S2/S3 `B_SLOWER` and C1 `B_FASTER`.
