# PR 5 corrective preflight

> **Status:** corrective fixup on `dev/segment-codecs`. No F01–F12 wire change,
> no golden-byte change, no merge. Baseline report only (not acceptance).

## 1. Branch and baseline reconciliation

| Fact | Value |
|---|---|
| Branch | `dev/segment-codecs` |
| Pre-correction HEAD | `b47861c5f5940ac60e815921fba3f39091473bba` (matches plan) |
| `origin/dev/segment-codecs` | `b47861c5f5940ac60e815921fba3f39091473bba` |
| `origin/main` | `a23cf25798e52fc181e93ac84505a07412f37463` |
| Merge base | `a23cf25798e52fc181e93ac84505a07412f37463` |
| `git status --short` | clean before edits |
| `git diff --stat origin/main...HEAD` | PR 5 implementation + artifacts |
| Rust | `rustc 1.85.0 (4d91de4e4 2025-02-17)`, `cargo 1.85.0` |

No divergence: the inspected baseline equals the plan's target. No later commits
required reconciliation.

## 2. Contracts inspected

`AGENTS.md`, `docs/TESTING.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`,
`docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md` (approved F01–F12),
`docs/pr-artifacts/pr-5/correctness-matrix.md`, the PR 5 implementation plan, and
the actual `crates/trawler-core/src/segment/*` source.

`docs/TESTING.md` conflict markers (lines 56–59) remain a pre-existing
documentation defect; not modified.

## 3. R5-I05 contract gate (group keys)

**Approved F07 wire (verbatim):** "per component: `type_tag u8`; then a state tag
`0x00 MISSING`, `0x01 NULL`, `0x02 VALUE` + value bytes". `EMPTY_MULTI` produces
no group key.

**Pre-correction code:** `GroupComponent::{Missing, Null, Value}` wrote the
state tag *before* the type tag and omitted the type tag entirely for
`Missing`/`Null` — nonconformant for **every** component.

**Resolution:** the approved contract is unambiguous; the type tag is the
component field's declared type and must be supplied by the caller. Group keys
are **not** persisted in the segment/golden bytes, so implementing the approved
bytes changes no F01–F12 persistent byte or golden fixture. Implemented
`Missing(FieldType)`/`Null(FieldType)`/`Value(&FieldValue)` emitting
`type_tag`, state, value. **No STOP required**; recorded here for review.

## 4. Resource-budget semantics gate

`max_single_allocation` is defined as a **conservative per-allocation upper
bound** (`count * size_of::<T>()` or an explicit byte count) checked **before**
`reserve`/`with_capacity`. `max_section_decode_bytes` is the **cumulative
decoded/retained byte** budget for one section/logical operation.
`max_decoded_entries` bounds entry counts. These do not alter F11 wire semantics.
No approved F11 contradiction found.

## 5. Baseline test/coverage (pre-correction)

| Gate | Command | Result |
|---|---|---|
| Tests | `cargo +1.85.0 test --workspace --all-targets` | PASS — 689 passed / 0 failed / 2 ignored |
| Coverage | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — 85.26% line |

## 6. Failing-before evidence (baseline worktree `b47861c`)

A temporary worktree of the baseline was run with three baseline-compatible
reproducers. All failed on baseline and pass after correction:

| Reproducer | Baseline result |
|---|---|
| Forged column `values_length = 0` | `ColumnReader::open` returned `Ok` (no geometry validation) |
| Forged column `state_offset = u64::MAX` | `ColumnReader::open` returned `Ok` |
| Manifest with unknown required per-segment feature `0xbeef` | `Manifest::decode` returned `Ok` |

Exact command: `cargo +1.85.0 test -p trawler-core --test baseline_repro`
→ `0 passed; 3 failed`. Baseline worktree removed after recording.

## 7. Gate outcome

PASS. Proceeding to corrections A–G. No STOP condition triggered.
