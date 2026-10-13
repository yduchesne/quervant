# Amendment 01 preflight — PR 5 format decisions

> **Status:** PREFLIGHT COMPLETE. Documentation-only amendment executed on
> `dev/segment-codecs`. No production codec, no F01–F12 approval, no merge.

## 1. Fresh-main and branch baseline

| Fact | Value |
|---|---|
| `git rev-parse HEAD` (pre-edit) | `98762ed051f166aa40de3cc85e9a03f6ba24d829` |
| Amendment baseline per instructions | `98762ed...` — **present** (`merge-base --is-ancestor` yes) |
| `git status --short` | clean |
| `origin/main` | `a23cf25798e52fc181e93ac84505a07412f37463` |
| `git merge-base HEAD origin/main` | `a23cf25798e52fc181e93ac84505a07412f37463` |
| PR 4 merge ancestry | `9bc042d` is an ancestor of `HEAD` — **merged** |
| `git diff origin/main...HEAD --stat` | 4 docs files, 1051 insertions (the prior proposal) |

The target branch contains the `98762ed` checkpoint and the prior proposal work;
no pre-existing uncommitted unrelated changes were present.

## 2. `docs/TESTING.md` conflict markers — independently checked

`grep -n '<<<<<<<\|>>>>>>>' docs/TESTING.md` returns lines **56, 57, 58, 59**
(four literal `<<<<<<< HEAD` markers, no matching `=======`/`>>>>>>>`). This is a
**pre-existing documentation defect on `main`**, unrelated to this amendment.
Per Amendment 01 §0, this amendment **does not** repair it. Disposition:
reported, out of scope.

## 3. Prior contracts inspected (actual checked-out source)

- `docs/decisions/PR02_CONTRACT_DECISIONS.md` A01–A25 (A04 field states, A07/A08
  IP/CIDR, A12 JSON ancestry, A13 timestamps, A14 geo, A15 sorting, A16 group-by,
  A20 budgets, A22 capabilities).
- `docs/decisions/PR03_STORAGE_CONTRACT_DECISIONS.md` S02/S03 (handles/sync),
  S10 (content identity `(length, SHA-256)`), S11 (SegmentStore vs SegmentCache).
- `docs/decisions/PR04_ANALYZER_PARAMETER_DECISIONS.md` + approval amendment;
  `PR04_PR05_DESIGN_GATE_APPROVAL.md`.
- `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `docs/TESTING.md`,
  `docs/ARCHITECTURE.md`, `docs/ROADMAP_V01.md`.

## 4. Source facts verified for the eight findings

| Finding | Verified source fact |
|---|---|
| R5-01 | `Token::new` rejects `position_increment == 0` and `position_length == 0` (`analysis/token.rs`); analyzer computes `increment = position.checked_sub(previous).filter(|i| *i > 0)` (`analysis/analyzer.rs`); `POSITION_GAP = 100`. Equal positions for the same term in one doc are impossible. |
| R5-02 | No existing columnar codec; PR 3 `ReadHandle::read_at` provides bounded positional reads. |
| R5-03 | `trawler_objectstore::digest::ContentDescriptor` = `(length, ContentDigest)` with `DigestAlgorithm::Sha256V1`; PR 3 S10 defines content identity. |
| R5-04 | `ReadHandle::len()` and `read_at(offset, buf)` exist; no seek-scan helper. |
| R5-05 | PR 2 `FieldValues::{Absent, ExplicitNull, Empty, Single, Multi}`; `Multi(vec![x])` is valid and distinct from `Single(x)`. |
| R5-06 | PR 2 A09/A10 truth tables; A13/A14 bound semantics. |
| R5-07 | PR 2 A20 budgets; PR 4 `HARD_MAX_TERM_BYTES = 4096`; storage key max. |
| R5-08 | PR 3 `SegmentDescriptor { object_key, content: ContentDescriptor }`. |

## 5. Dirty-source check

No code, `Cargo.toml`, `Cargo.lock`, roadmap status, earlier PR artifact
directory, or protected PR 2/3/4 contract file was modified. See
`amendment-01-report.md` for the final changed-file list.

## 6. STOP conditions checked

- No contract contradiction requiring a STOP was found for the eight findings.
- R5-03 selective trust: resolved by explicitly refusing to promise
  authentication without a trusted reference; Merkle ranges deferred as a
  separate human decision (not an agent scope expansion).
- R5-08 lifecycle: resolved by recommending omission with a reserved-zero
  alternative presented for human choice, rather than freezing PR 6 semantics.

## 7. Baseline QA context

Baseline QA was executed on the inspected tree (see
`docs/pr-artifacts/pr-5/preflight.md` and `amendment-01-report.md`): 639 passed /
0 failed / 1 ignored; fmt/Clippy/docs pass; 87.74% workspace line coverage. This
amendment is **documentation-only**, so these are baseline checks, not PR 5
codec acceptance.
