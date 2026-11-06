# PR 15H-A — performance qualification and disposition

## Campaign qualification

| Requirement | Result |
|---|---|
| Immutable baseline sealed before production edits | PASS |
| Baseline `--verify-only` byte-for-byte reproduction | PASS |
| Candidate descendant of sealed baseline | PASS |
| Clean, detached pinned source worktrees | PASS |
| Frozen PR15D/PR15E file hashes | PASS |
| Same host fingerprint across baseline and paired | PASS |
| Byte-identical query-only corpus/index digests | PASS |
| Four mirrored blocks / 8 slots / 56 lane records | PASS |
| 1,120 timed samples, 280 warmups | PASS |
| 16 clear before/after contention probes | PASS |
| 56 independent oracle validations | PASS |
| Frozen nearest-rank summaries recomputed | PASS |
| Cross-session and within-arm drift caps | PASS |

No `MEASUREMENT_BLOCKED` condition occurred.

## Frozen verdict

`PERFORMANCE_REJECTED`.

- HA-P01 and HA-P02 (`B_FASTER`) PASS on 100K common K100/K10.
- HA-P03 PASS: 100K medium K100 is INCONCLUSIVE, not `A_FASTER`.
- HA-P04 **FAIL**: 10K rare, 100K rare and 100K absent are all `A_FASTER` on all
  four paired ratios. The low-hit eligible path — where per-match tree
  materialization was already cheap — is materially slower with the linear
  staging candidate.

The plan's frozen rule converts a qualified guard regression into rejection; no
threshold tuning, lane substitution, rerun or alternative statistic is applied.

## Disposition

Production search was restored byte-for-byte to the pinned baseline
`ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078`:

```
git diff --quiet ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078 HEAD -- crates/quervant-core/src/search
# exit 0 — identical
```

Preserved:

- `benchmarks/pr15h_a/` controller, its 21 tests and README;
- sealed raw baseline/paired evidence under `target/pr15h-a/`;
- the real local integration suite
  `crates/quervant-core/tests/pr15h_a_candidate_materialization.rs`;
- this evidence set and the roadmap/benchmarking notes.

Removed by the restore (mechanical, because they referenced the rejected helper):
the `#[cfg(test)]` linear counters/fault flags and the `linear_term_tests`
module in `execute.rs`, and the `h_a_*` unit tests added to `unified.rs`. The
old pre-existing tests were not edited.
