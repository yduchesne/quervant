# PR 15H-A — source disposition

**Decision:** `PERFORMANCE_REJECTED_SAFE_ROLLBACK`.

## Candidate

`dce8f02405e6541d478c2072a0332af192ed2945` — linear single-term candidate
staging in `execute::evaluate_lexical_with`, with test-only witnesses and unit
tests, plus a real local integration suite.

## Revert commit

`3eae252f7777b551f2eaf0289ea067957b1f7c74` — restores
`crates/quervant-core/src/search/execute.rs` and
`crates/quervant-core/src/search/unified.rs` to the exact pinned baseline blobs.
The revert message records the qualified rejection and does not reopen the
implementation.

## Blob-equality proof

```
git diff --quiet ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078 HEAD -- crates/quervant-core/src/search
# exit code 0
```

The two restored files are byte-identical to the accepted baseline. No segment
codec, format, storage, reader, manifest, cache, remote, budget constant or
benchmark input was ever changed.

## Preserved after rollback

| Path | Reason |
|---|---|
| `benchmarks/pr15h_a/{run.py,test_run.py,README.md}` | reusable targeted controller and 21 qualifying tests |
| `crates/quervant-core/tests/pr15h_a_candidate_materialization.rs` | meaningful public-path regression coverage, passes on baseline behaviour |
| `target/pr15h-a/baseline-01`, `target/pr15h-a/paired-01` | sealed immutable raw evidence (ignored) |
| `docs/pr-artifacts/pr-15h-a/` | factual evidence set |
| `docs/BENCHMARKING.md`, `docs/PERF_OPTIMIZATION_PLAN.md` | measured facts and disposition |

## Mechanically removed on rollback

Restoring the two source files removed the `#[cfg(test)]` linear
counters/fault flags, the `linear_term_tests` module and the `h_a_*` unit tests
that referenced the rejected helper. Pre-existing historical tests were not
edited. This was a byte-for-byte restore, not a hand-edited partial revert.

## Not done

No new performance experiment, threshold change, lane substitution, sample-count
change or retry was performed after the qualified rejection.
