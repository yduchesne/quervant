# D2-only source proof

**A:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**X:** `53e41df1fd5e91c7c2a67a3fcfbba4abf62bd4f6`
**X parent:** `ca065a212987284144d8901aa5c54de093d6dbfc`

## File allowlist

```text
crates/quervant-core/src/search/execute.rs
crates/quervant-core/src/search/unified.rs
```

`git diff --name-only A X` reports exactly these two files. No Cargo,
CI, segment, writer, schema, API, cache, dependency or benchmark-input file
changed.

## Delta identity

| Comparison | Stable patch hash |
|---|---|
| A→X, two search files | `5183cdb29d05aa650c35e6a29de5be8dd6640966` |
| Historical D1→D2, two search files | `dc827b20f1e6af0116ca38c03262cc46ab5d1277` |

The patch hashes differ because `git patch-id` hashes hunk context. The
complete set of 58 added lines is identical between the two diffs; only hunk
headers and the final test insertion context differ. The historical D2 test
followed a D1-only test absent from A; the approved helper appends the original
test at the end of A's module.

## Required source properties

| Check | Result |
|---|---|
| X immediate parent is A | PASS |
| Exactly two authorized files differ | PASS |
| `if postings_candidate_eligible { true }` branch present | PASS |
| `#[cfg(test)]` membership-search counter present | PASS |
| Historical D2 test present verbatim | PASS |
| D1 `charge_absent_exact_term_segment` absent | PASS |
| D1 `absent_term_candidate` absent | PASS |
| D1 `gd_test_observation` absent | PASS |
| A→X added lines equal D1→D2 added lines | PASS — 58/58 |
| Stable patch hash equality required by plan | **FAIL** |

## Disposition

The candidate was **not benchmarked**. This is a source-identity gate failure,
not a correctness or performance failure. No shared production source changed.
