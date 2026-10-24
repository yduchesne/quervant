# PR 14C — P0 baseline inventory

**Status:** PREFLIGHT RECORDED — all acceptance rows remain `PENDING`.
This document is the §1.7 preflight output for PR 14C. It records the baseline,
source inventory, historic-vs-current status, known gaps and the proposed
acceptance matrix **before** any claim of PASS. No test result in this file is an
acceptance claim; executed evidence is recorded in `validation-report.md`,
`benchmark-report.md` and the reconciliation documents.

Baseline date: 2026-10-24 (UTC). Prepared by the coding agent for human review.

## 1. Preflight commands and results

| Step | Command | Result |
|---|---|---|
| Fetch | `git fetch origin --prune` | exit 0; pruned stale `origin/pr48-merge`; advanced `origin/dev/pr14b-real-rustfs-qualification` |
| Local `main` | `git rev-parse main` | `376023b53b557a30367097f29a41328c798188d4` |
| Remote `main` | `git rev-parse origin/main` | `376023b53b557a30367097f29a41328c798188d4` |
| Working tree | `git status --porcelain` | empty (clean) |
| Work branch | `git switch -c dev/pr14c-acceptance-closeout` | created from `main` at the verified SHA |
| PR #60 ancestry | `git merge-base --is-ancestor 7a86059 HEAD` | YES |
| PR #61 ancestry | `git merge-base --is-ancestor 376023b HEAD` | YES |
| Previous local branch | `dev/pr-14-acceptance` | also at `376023b`, zero commits ahead of `main`; abandoned in favour of the prescribed branch name |

E01 applied: baseline `main` equals the verified merge SHA, so the work branch
was created without further reconciliation. No commit has been made on the work
branch yet; this document is the first addition.

## 2. Source SHAs

| Item | SHA |
|---|---|
| Verified baseline / PR 14C base | `376023b53b557a30367097f29a41328c798188d4` (merge of GitHub PR #61) |
| PR 14A merge (GitHub PR #60) | `7a860590fe5ba4fde3cfeee235e8a33751019522` |
| Original PR 14 implementation merge (GitHub PR #41) | `f1efd5f` (`Merge pull request #41 from yduchesne/dev/pagination`) |
| PR 14A corrected head referenced by 14B | `9fb90418f89cc0a67370124b78a6ad8306cc3bbd` (Correction 02) |
| PR 14B qualified code/test commit | `556621a5414673d3355e57fb2b2f4fb09135c54b` |
| Historical P4 benchmark source SHA | `ab9b2d7da066ec80190dcee70a8cebfd81481b80` (ancestor of baseline; **138 commits behind HEAD**) |

Both required predecessor merges are ancestors of the baseline, satisfying
preflight step 2.

## 3. Current implementation facts (verified on baseline)

Verified by inspection only; no source was modified.

| Fact | Evidence |
|---|---|
| `execute_batch` rejects any PIT/cursor-bearing request before running slots | `crates/quervant-core/src/search/batch.rs:42`; typed `InvalidBatch(PinnedContextRequired)` at line 61 |
| `execute_batch_pinned` takes the live `PitHandle` as the only snapshot authority | `crates/quervant-core/src/search/batch.rs:75` |
| Public `Cursor` carries an optional crate-private continuation (`CursorContinuationV1`) | `crates/quervant-core/src/contract/result.rs:280,289,294` |
| Unified JSON-path sort ordering is implemented through the shared typed evaluator | `crates/quervant-core/src/search/unified.rs` (Correction 02), tuple installed in `collect_mixed` |
| Cursor accounting and batch meters exist | `search/batch_cursor.rs`, `search/batch_meter.rs`, `search/unified_cursor.rs` |
| Workspace has three crates: core, objectstore, distributed | root `Cargo.toml` (`resolver = "3"`, `rust-version = "1.85"`, edition 2024) |
| No uncommitted or untracked change besides this file | `git status --porcelain` |

## 4. Historic vs current status of the PR 14 acceptance corpus

The historical reports are **contemporaneous and partly superseded**. Historical
`NOT READY` wording is preserved; supersession is additive.

| Artifact | Historical status (recorded at the time) | Current meaning (baseline) |
|---|---|---|
| `pr-14/final-acceptance-gate.md` | NOT READY; S1 (mixed execution) and S2 (public sorted pagination) open; 14F blocked; no final-SHA CI; I01/I13/I15 incomplete | S1 and S2 are implemented by later merges (PR #41 corrective/final-design passes, PR #60 14A). I13 has no dedicated zero-GET instrumentation; needs adjudication |
| `pr-14/preimplementation-correctness-gate.md` | S1/S2 TRIGGERED-UNRESOLVED; S3/S4/S5 resolved | S1/S2 resolved by merged code + 14A/14B oracle tests; S3–S5 unchanged |
| `pr-14/test-traceability.md` | T01–B10 PASS; U/J14/J15/G/R/X gaps | Local matrices stand; gaps now map to 14B real-provider evidence and current local suites |
| `pr-14/remaining-final-acceptance.md` | NOT READY; P2/P3 not implemented; RustFS blocked | P2 (shared batch meter) and P3 (compound aggregation + typed batch result) exist in merged code; RustFS qualified by 14B locally |
| `pr-14/final-design-acceptance.md` | NOT READY; D2/D5/D6/D7 gaps | D2 resolved by 14A `execute_batch_pinned`; D5/D6 resolved by merged meters (needs current-oracle recheck); D7 resolved by `contract::batch` aggregation |
| `pr-14/corrective-final-acceptance.md` | NOT READY; C1/C3/C4/C6/C8 STOPs | Resolved by merged cursor/meter/aggregation/policy work; needs evidence mapping |
| `pr-14/p4-rustfs-acceptance.md` | PARTIAL → P4 accepted on `0d005ab` | Real verticals/faults/benchmarks executed in the P4 pass; historical benchmark SHA is 138 commits behind baseline (fresh trials required by 14C) |
| `pr-14/p4-final-acceptance.md` | P4 ACCEPTED on `0d005ab`; PR 14 NOT READY (no final-SHA CI) | P4 historical provenance only; **not** a current-branch measurement |
| `pr-14/p4-w08-stop.md` | BLOCKED, resolved by approved **Option 2** | W08 remains **NOT APPLICABLE (APPROVED)** for v0.1; must not be reported as measured/pass |
| `pr-14/p4-benchmark-report.md` | 3 qualified trials at `ab9b2d7` | Historical provenance only; 14C requires fresh qualified trials |
| `pr-14a/implementation-evidence.md` | IMPLEMENTED, locally qualified; CI/human pending | Merged via PR #60; local qualification exists; CI still unobserved |
| `pr-14a/test-traceability.md` | T01–T13, J01–J12 PASS | Current suite `pr14a_public_cursor` lists 26 tests (see §5) |
| `pr-14a/adversarial-review.md` | residual risk `R-14A-JSON-MEM` open | **Remains OPEN** (see §7) |
| `pr-14b/implementation-evidence.md` | LOCALLY EXECUTED + REAL-RUSTFS QUALIFIED; CI NO; HUMAN ACCEPTED NO | Qualification host was WSL2; CI unobserved; 14C inherits the open risk |
| `pr-14b/{fault-matrix,compatibility-evidence,environment-and-commands,test-traceability}.md` | B01–B21, F01–F10, G01–G03 PASS locally | Historical evidence; 14C must re-execute the required provider cases |
| `pr-14b/resource-risk.md` | OPEN, no disposition | **OPEN** — human decision required; agent may not decide |

No historical artifact has been rewritten. No preauthorized mapping (plan §4
items 1–7) has been adjudicated yet; all rows are `PENDING` in
`acceptance-reconciliation.md`.

## 5. Test inventory (verified with `--list` on baseline)

Commands: `cargo test -p quervant-core --all-features --test <suite> -- --list`.

| Suite | Listed | Local (non-ignored) | Ignored |
|---|---:|---:|---:|
| `pr14_storage_vertical` | 17 | 5 | 12 (11 `real::*` provider cases + `p4_child_bootstrap` child entrypoint) |
| `pr14a_public_cursor` | 26 | 26 | 0 |
| `pr14b_json_memory` | 2 | 1 (`b20_b21_...` parent) | 1 (`b20_child_json_memory_probe`, child entrypoint) |
| `pr14_storage_faults` | 10 | 0 | 10 (9 fault cases + `p4_fault_child_open` child entrypoint) |
| `pr14_bench_remote` | 1 | 0 | 1 (`pr14_p4_benchmark`) |

`pr14_storage_vertical` provider symbols (11, each executed individually with
`--ignored --exact` under 14B and to be re-executed in 14C):

`real::b02_real_mixed_boolean_and_relevance_order`,
`real::b06_b07_real_pinned_batch_search_after`,
`real::b18_real_historical_json_remote`,
`real::r01_separate_process_cold_bootstrap`,
`real::r02_r04_r06_real_cold_compound_equivalence`,
`real::r03_wrong_generation_is_not_substituted`,
`real::r05_real_mutation_old_and_new_snapshot`,
`real::r08_r09_r15_real_batch_aggregation_and_cursor`,
`real::r10_r11_real_remote_budget_exact_and_one_over`,
`real::r12_empty_cache_no_writer_state`,
`real::r13_r14_warm_evict_and_pinned_reader`.

Internal child entrypoints (`p4_child_bootstrap`, `p4_fault_child_open`,
`b20_child_json_memory_probe`) must never be invoked as standalone acceptance
cases; their parents spawn them (E08).

Other PR 14 local suites present and relevant to C01–C04: `pr14_batch.rs`,
`pr14_batch_memory.rs`, `pr14_batch_governance.rs`, `pr14_unified_cursor.rs`,
`pr14_unified_mixed.rs`, `pr14_compound_aggregation.rs`, `pr14_aggregation.rs`,
`pr14_json.rs`, `pr14_projection.rs`, `pr14_typed_predicates.rs`,
`pr14_f1_hardening.rs`, `pr14_common/`. Their execution status is `PENDING` for
14C.

## 6. Environment and tooling (as observed at P0)

| Item | Value |
|---|---|
| Host | WSL2 (`Linux MSI 6.18.33.2-microsoft-standard-WSL2`, x86-64) |
| Repository filesystem | `/dev/sdd` (ext4 per `findmnt`) mounted at `/` — Linux filesystem inside WSL2, **not** `/mnt/c` |
| Stable toolchain | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1` |
| MSRV toolchain | `rustc/cargo 1.85.0` installed and invocable via `cargo +1.85.0` |
| Coverage tool | `cargo-llvm-cov 0.9.1` |
| Container runtime | `podman 4.9.3` (rootless) |
| RustFS image | present locally: `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` (image ID `f6b22807f10d`) |
| RustFS container | `quervant-pr14b-rustfs` exists but is **not running** (status `Created`, created 4 h before preflight) |
| Ports 9000/9001 | nothing listening |
| `QUERVANT_RUSTFS_*` | **not set** in this shell |
| Python | `3.12.3`; `validate-pr14-p4.py --self-test` → PASS |
| Benchmark wrapper | `benchmarks/scripts/run-pr14-p4.sh`; qualified mode requires `--idle-confirmed`, a clean tracked tree, the four `QUERVANT_RUSTFS_*` variables, contention `clear`, and validates `benchmarks/reports/pr14-p4-t{1,2,3}.json` (optionally `--w08-exemption`) |
| GitHub CLI | `gh` installed but the configured token is **invalid**; `gh auth status` fails |

Consequences recorded now:

- Provider infrastructure exists but must be started, digest-verified, given
  disposable credentials via environment, and health-checked before C-T02.
- Qualified benchmarking additionally requires **human** attestation that the
  host is idle (`--idle-confirmed`). WSL2 is the host used by 14B; the plan's
  "native Linux filesystem" condition is satisfied for the repository path but
  host contention must still be confirmed by the operator (E12/E23).
- The four benchmarks of record in `benchmarks/reports/` were produced at
  `ab9b2d7` (138 commits behind baseline) and are **historical provenance only**.

## 7. Known gaps and blockers at baseline

| ID | Gap | Status at P0 | Governing rule |
|---|---|---|---|
| G1 | `R-14A-JSON-MEM` has no human disposition | **OPEN — BLOCKING** | AD-14C-06, E16–E18; agent cannot decide |
| G2 | No final-SHA CI observed on the PR 14C head (no PR exists yet) | OPEN | E19/E22; `gh` token invalid is an additional tooling obstacle |
| G3 | Fresh P4 qualified trials not run on this baseline | OPEN | AD-14C-03/04, E13; requires provider + idle attestation |
| G4 | Real-RustFS suite not re-executed on baseline | OPEN | C-T02; provider stopped, env unset |
| G5 | Historical benchmark SHA is 138 commits behind; old metrics cannot be reused as current | RECORDED | AD-14C-03; plan §7 |
| G6 | W08 has no measured result by contract | RECORDED, correctly N/A | AD-14C-03, E14 |
| G7 | JSON compatibility is v1-wire only; no cross-version migration exists | RECORDED | E15; no migration may be invented |
| G8 | `gh` authentication invalid → CI job IDs cannot be read with the CLI | OPEN | must be resolved or CI evidence obtained another way |
| G9 | Historical obligation crosswalk (I/U/J/T/P/A/B/G/R/X, 14A–14G, P4 V/R/F/B/W) not yet mapped | PENDING | §4 of the plan |

No production correctness defect has been discovered during P0. Inspection was
limited to verifying that the documented interfaces exist; behavioural claims are
deferred to executed evidence.

## 8. Proposed acceptance matrix (all `PENDING`)

| ID | Proposed evidence source | Status |
|---|---|---|
| C01 | `pr14_unified_mixed`, `pr14a_public_cursor::j06`, `real::b02` | PENDING |
| C02 | `pr14_aggregation`, `pr14_compound_aggregation`, `real::b06_b07`, `real::r08_r09_r15` | PENDING |
| C03 | `pr14a_public_cursor` T/J sets, `real::b06_b07` | PENDING |
| C04 | `pr14_batch_memory`, `pr14_batch_governance`, `real::r10_r11`, `t10_expiry_boundaries_and_no_renewal` | PENDING |
| C05 | `real::r05`, `real::r12`, `real::r13_r14`, `pr13_*` fault suites | PENDING |
| C06 | `b18_b19_historical_json_segment_compatibility`, `real::b18` | PENDING |
| C07 | `pr14_storage_faults` F01–F09, `pr13_remote_proxy`, `pr13_crash_rustfs` | PENDING |
| C08 | `validate-pr14-p4.py --self-test`, 3 fresh qualified trials, W08 exemption | PENDING |
| C09 | stable/MSRV fmt/clippy/tests, coverage ≥85 %, final-SHA CI | PENDING |
| C10 | `resource-risk-disposition.md` with literal human decision | PENDING — BLOCKING |
| C11 | `acceptance-reconciliation.md` one row per historical obligation | PENDING |
| C12 | `git diff` scope audit (docs + approved harness only) | PENDING |

Full gate-by-gate mapping (I01–I16; U/J/T/P/A/B/G/R/X; phases 14A–14G; P4
V01–V14, R01–R15, F01–F10, B01–B04, W01–W09; S1–S5; P2B/remaining/final-design
gates) is `PENDING` in `acceptance-reconciliation.md` per plan §4.

## 9. Next actions (P1 onward)

1. Execute local PR 14A/14B/golden/oracle suites and record counts (C-T01,
   C-T03, C-T06, C-T07).
2. Start and digest-verify the pinned RustFS service, then execute each of the
   11 provider symbols individually plus the fault suites (C-T02, C-T04, C-T05).
3. Freeze B20/B21 measurements and draft `resource-risk-disposition.md` as
   `PENDING — BLOCKED`, requesting the human decision. Do not choose it.
4. Only after operator idle attestation and provider availability, run three
   qualified P4 trials and validate them (C-T10, C-T11).
5. Run stable/MSRV gates, coverage, docs and bench build (C-T12, C-T13).
6. Write the eight PR 14C evidence files; keep `final-acceptance.md` BLOCKED
   until the human risk decision and all gates pass.

No acceptance is claimed by this inventory.
