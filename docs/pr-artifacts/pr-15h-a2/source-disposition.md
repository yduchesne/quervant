# PR 15H-A2 — source disposition

**Decision:** `PERFORMANCE_REJECTED_SAFE_ROLLBACK`.

| Identity | SHA |
|---|---|
| A2 base (accepted production search) | `7a136f7f299c2f460401b9d92dcef37d219ea98c` |
| A2 harness-only (`H_A2_TOOLING_SHA`) | `9aff92b6b1a12ee323ed7994a177f88949c736fd` |
| A2 measured candidate | `569132dace8d92c103dfdebd5d24167d65c0c0c0` |
| Additive rollback | `29f2a372fdc1b4b3316409fc7ff218fb761ba5fb` |

## Rollback proof

```
git diff --quiet 7a136f7f299c2f460401b9d92dcef37d219ea98c HEAD -- crates/quervant-core/src/search
# exit 0 — production search byte-identical to the A2 base
```

Both `execute.rs` and `unified.rs` are the exact `7a136f7` blobs. Accepted main's
search (`ddcbe778`) is identical to that base, so the final production search is
the accepted merged implementation.

## Preserved after rollback

| Path | Reason |
|---|---|
| `benchmarks/pr15h_a2/{run.py,test_run.py,README.md}` | reusable A2 controller + 26 tests |
| `crates/quervant-core/tests/pr15h_a2_dispatch.rs` | 8 public-path regression tests, compile and pass on baseline behaviour |
| `target/pr15h-a2/{baseline-01,paired-01,diagnostics}` | sealed raw evidence (ignored) |
| `docs/pr-artifacts/pr-15h-a2/` | this evidence set |
| `docs/BENCHMARKING.md`, `docs/PERF_OPTIMIZATION_PLAN.md` | measured facts and disposition |
| All historical `benchmarks/pr15h_a/` and `docs/pr-artifacts/pr-15h-a/` | untouched negative evidence |

## Mechanically removed on rollback

The restored source files removed the transplanted historical H-A helper, its
test-only witnesses, the `linear_term_tests` modules, the A2 dispatch guard and
the A2 unit tests in `execute.rs`/`unified.rs`. The independent integration suite
does not reference crate-private helpers and was kept. No historical test was
edited.

## Not done

No merge, push, retry, threshold change or unapproved experiment.
