# PR 15G-D D2-only isolation preflight

**Status:** `SOURCE_IDENTITY_BLOCKED_REVIEW_REQUIRED`
**Shared branch:** `dev/pr15g-a-retained-column-geometry`
**Umbrella PR:** #86
**Inspected/start HEAD:** `f0039e12d678564e584b704c4dda39ce83301e53`
**Current `main`:** `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc` (ancestor of the shared branch)
**A:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**Historical D1:** `1d2a6b0f08bf68994699e1f3e37f163347492cd1`
**Historical D1+D2:** `dae598758a433ecdc0d9af37e15194e948bbc788`
**Constructed isolated X:** `53e41df1fd5e91c7c2a67a3fcfbba4abf62bd4f6`

## Checks completed

- Shared worktree clean and exactly at the inspected HEAD before source work.
- `main` is an ancestor of the shared branch.
- A, historical D1 and historical D2 are present locally.
- A/X detached worktrees created only under ignored
  `target/pr15g-d-d2-isolation/worktrees/`.
- X is a new commit whose immediate parent is A.
- X changes exactly the two authorized search files.
- X contains zero D1 dictionary-miss/`gd_test_observation` symbols.
- The original D2 in-module differential test extracts and passes at X:
  `gd_u20_u21_u22_d2_removes_only_membership_binary_search` (1 passed).
- No shared production source was modified.

## Blocking discrepancy

The plan requires the A→X patch hash to equal the historical D1→D2 patch hash.
The two stable patch IDs are:

- A→X: `5183cdb29d05aa650c35e6a29de5be8dd6640966`
- D1→D2: `dc827b20f1e6af0116ca38c03262cc46ab5d1277`

All 58 added lines are byte-identical. The difference is hunk context and line
offsets: the historical D2 test was inserted after a D1-only test that does not
exist in A, while the prescribed helper appends the same test after A's final
test. `git patch-id` includes context, so the plan's exact patch-ID gate cannot
be satisfied by its own mandated helper.

This is a **HARD STOP under DX-D11**. Per the plan, no manual patch, cherry-pick,
three-way merge, test relocation, benchmark campaign, or production disposition
was performed.

## Consequence

- Exactly one 16-slot A/X campaign was **not** run.
- No performance verdict is claimed.
- Shared production source remains the existing D1+D2 source at the inspected
  HEAD, unchanged.
- Human maintainer/reviewer decision is required: amend the source-identity
  gate to compare the added delta while allowing test-context relocation, or
  provide a revised candidate-construction procedure.
