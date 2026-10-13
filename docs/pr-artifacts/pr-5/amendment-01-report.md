# Amendment 01 report — PR 5 format decisions

> **Status:** Amendment documentation COMPLETE. Documentation-only change on
> `dev/segment-codecs`. No production codec, no F01–F12 approval, no merge.

## 1. Summary

This amendment addresses the eight independent-review findings R5-01–R5-08 in a
single coherent revision of the PR 5 byte-level format proposal. All changes are
documentation. F01–F12 remain **PROPOSED — AWAITING HUMAN APPROVAL**; the
approval table is empty.

## 2. Changed files

Modified:

1. `docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md` — revised F01–F12; header,
   fixed trailer, integrity/trust model, postings seek contract, addressable
   columns, five-state vocabulary, partial-presence bounds, three limit classes,
   manifest integrity/lifecycle.
2. `docs/pr-artifacts/pr-5/format-decision-review.md` — revised recommendations,
   R5-01–R5-08 summary, tradeoffs, human choices.
3. `docs/pr-artifacts/pr-5/correctness-matrix.md` — INV13/INV14 added; P5-A01–A20
   planned and mapped; new counterexamples.

Added:

4. `docs/pr-artifacts/pr-5/amendment-01-preflight.md`.
5. `docs/pr-artifacts/pr-5/amendment-01-consistency-matrix.md`.
6. `docs/pr-artifacts/pr-5/amendment-01-report.md` (this file).

No code, `Cargo.toml`, `Cargo.lock`, roadmap status, earlier PR artifact
directory, or protected PR 2/3/4 decision file was modified. `docs/TESTING.md`'s
pre-existing conflict markers were **not** touched.

## 3. Findings disposition

| Finding | Decision(s) | Resolution | Status |
|---|---|---|---|
| R5-01 | F05 | Added binding `next`/`advance` behavior (monotone, idempotent, never backward), explicit "sequential, not sublinear without skips", lazy/bounded decode + cancellation, and source-validated strict positive position deltas (PR 4 `Token`/analyzer). Skip section reserved, not v1. | RESOLVED in proposal |
| R5-02 | F07 | Replaced unindexed per-doc records with uniform `block_docs` blocks and a bounded block directory; `FIXED_SINGLE`/`VARIABLE_MULTI` layouts; O(1) directory arithmetic, doc N touches one block; offset-table monotonicity + sentinel validation. | RESOLVED in proposal |
| R5-03 | F01/F02/F07/F12 | Added F02.1: full verification against a trusted PR 3 `ContentDescriptor` vs selective access (structurally checked, **not** independently authenticated); SHA-256 authenticity requires a trusted reference; Merkle ranges deferred as a separate decision; `read_at` trailer/footer read plan. | RESOLVED in proposal |
| R5-04 | F02 | Replaced backward magic scan with a fixed 64-byte EOF trailer with exact offsets; checked subtraction; exact footer consumption; no undeclared bytes. | RESOLVED in proposal |
| R5-05 | F06/F07 | One shared state vocabulary `ABSENT/EXPLICIT_NULL/EMPTY_MULTI/SINGLE/MULTI`; stored source uses a presence bitmap (absence explicit); `MULTI >= 1`; group keys carry MISSING/NULL/VALUE; empty multi non-groupable. | RESOLVED in proposal |
| R5-06 | F08 | Presence metadata (`UNKNOWN/NO_VALUES/SOME_VALUES/ALL`) + conservative pruning applicability truth table (positive, negated, `IS NULL`/missing, OR/AND, unlisted). | RESOLVED in proposal |
| R5-07 | F11 | Split wire representability, decoder safety budgets and operational policy; 256 MiB is a preferred encoder target, not a wire ceiling; configurable accepted-size. | RESOLVED in proposal |
| R5-08 | F10/F02 | Named three distinct digest roles (manifest envelope, per-segment content descriptor, future PR 6 lifecycle); prohibited payload duplication of the envelope digest; lifecycle fields omitted (recommended) or reserved-zero (alternative). | RESOLVED in proposal (one human choice open) |

## 4. Decisions requiring approval (all 12)

F01 one-file container; F02 fixed trailer + envelope digest + trust model; F03
canonical field identity + fingerprint; F04 dense ids/refs; F05 varint postings +
sequential advance; F06 semantic stored source + five states; F07 addressable
typed columns + group keys; F08 partial-presence bounds + applicability; F09
deterministic remap; F10 manifest integrity/lifecycle; F11 three limit classes;
F12 compatibility/evolution.

Materially changed by Amendment 01: **F02, F05, F06, F07, F08, F10, F11, F12**
(F01/F03/F04/F09 clarified only).

## 5. Still-open alternatives for human decision

1. F01 one-file vs multi-file.
2. F05 varint vs fixed-width v1 postings; confirm no v1 skip index.
3. F06 semantic vs byte-for-byte source (byte-for-byte would be a PR 2 STOP).
4. F07 block layout/`block_docs` policy.
5. F08 applicability truth-table confirmation.
6. F10 omit vs reserved-zero lifecycle fields.
7. F11 safety-budget defaults; accepted-size policy.
8. F12 conservative minor-version rejection.
9. F02.1 whether to pursue an authenticated selective-read scheme now (separate
   decision) or keep selective reads structurally checked only.

## 6. Explicit STOPs

- No STOP triggered: no PR 2/3/4 contract was changed and no unapproved
  dependency/scope was introduced.
- Implementation remains STOPPED at the F01–F12 gate. No production codec,
  CURRENT/publication, writer, refresh, PIT, query, remote ObjectStore/RustFS, or
  vector work was performed.
- R5-03's authenticated-range question is presented as a separate human decision,
  not silently expanded into scope.

## 7. Validation evidence (documentation-only change)

Commands run from the workspace root, `cargo +1.85.0` (MSRV)
`rustc 1.85.0 (4d91de4e4 2025-02-17)`. These are **baseline checks**, not PR 5
codec acceptance, because the delta is documentation only.

| Gate | Exact command | Exit | Result |
|---|---|---|---|
| Whitespace | `git diff --check` | 0 | clean |
| Path existence | referenced-file existence loop | 0 | all referenced paths exist |
| Check | `cargo +1.85.0 check --workspace --all-targets` | 0 | PASS |
| Tests | `cargo +1.85.0 test --workspace --all-targets` | 0 | PASS — 639 passed / 0 failed / 1 ignored |
| Format | `cargo +1.85.0 fmt --all -- --check` | 0 | PASS |
| Lint | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| Docs | `cargo +1.85.0 doc --workspace --no-deps` | 0 | PASS |
| Coverage | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | 0 | PASS — TOTAL 87.74% line / 91.19% function / 94.63% region |

No PR 5 codec test was executed or claimed; all P5-A01–A20 remain PLANNED.

## 8. Pre-existing failures / environment notes

- `docs/TESTING.md` literal conflict markers (lines 56–59) remain a pre-existing
  documentation defect on `main`; not repaired here (out of scope).
- One ignored test is the pre-existing RustFS/S3 harness SKIP; a SKIP is not a
  pass and the real S3 adapter remains PR 13.

## 9. Final state

- Amendment documentation committed on `dev/segment-codecs` (SHA recorded in the
  execution summary / next commit); not pushed, not merged.
- F01–F12 approval table remains **pending**.
- Phases A–E **not started**.
