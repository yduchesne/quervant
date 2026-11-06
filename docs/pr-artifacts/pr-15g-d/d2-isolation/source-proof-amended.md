# D2-only source proof — approved exact-edit identity

**Rule supersession:** `APPROVED_EXACT_EDIT_IDENTITY`
**Original hard stop:** `VALID_PLAN_DEFECT`
**A:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**Historical D1:** `1d2a6b0f08bf68994699e1f3e37f163347492cd1`
**Historical D1+D2:** `dae598758a433ecdc0d9af37e15194e948bbc788`
**X:** `53e41df1fd5e91c7c2a67a3fcfbba4abf62bd4f6`
**X parent:** `ca065a212987284144d8901aa5c54de093d6dbfc`

The maintainer withdrew only the `git patch-id --stable` equality gate. The
replacement proof uses exact added/removed edit sequences per file.

## Proof command

```sh
python3 target/pr15g-d-d2-isolation/verify_exact_d2_edits.py
```

Output:

```text
DX-SOURCE-ID: PASS; exact two-file D2 edits, test bytes, A parent, no D1
```

## Results

| Check | Result |
|---|---|
| X immediate parent is A | PASS |
| Changed files = two authorized search files | PASS |
| Exact per-file added/removed edit sequence vs historical D1→D2 | PASS |
| Edit totals | 58 added, 1 deleted |
| Original D2 test bytes identical | PASS |
| D1 `charge_absent_exact_term_segment` absent | PASS |
| D1 `absent_term_candidate` absent | PASS |
| D1 `gd_test_observation` absent | PASS |
| D2 optimized membership branch present | PASS |
| D2 test-only membership counter present | PASS |
| A and X worktrees clean and pinned | PASS |

## Historical patch hashes (diagnostic only)

| Comparison | Stable patch hash |
|---|---|
| A→X | `5183cdb29d05aa650c35e6a29de5be8dd6640966` |
| D1→D2 | `dc827b20f1e6af0116ca38c03262cc46ab5d1277` |

These hashes differ because Git patch-ID hashes diff context, not because the
substantive edits differ. All 58 added lines are byte-identical.

## Candidate test

`cargo test -p quervant-core gd_u20_u21_u22_d2_removes_only_membership_binary_search`
at X: **1 passed**, 931 filtered.
