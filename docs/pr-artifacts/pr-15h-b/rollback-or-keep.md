# PR 15H-B — keep / rollback decision

**Decision: KEEP — `PERFORMANCE_ACCEPTED_LOCAL_QA_PASS`.**

No rollback is required: all qualified performance gates and correctness/QA
gates passed. The candidate remains on the required branch
`dev/pr15h-a-linear-term-candidates` at `ae7e416a…` for human review.

## Retained source

| File | Change |
|---|---|
| `crates/quervant-core/src/segment/column.rs` | `ColumnKeywordView` + `keyword_sort_view` (validated borrowed read only) |
| `crates/quervant-core/src/search/typed_compare.rs` | `ColumnAccess::keyword_sort_view`, borrowed comparator, owned materializer |
| `crates/quervant-core/src/search/unified.rs` | B eligibility, per-candidate fast path, charge, extracted heap admission, test witnesses/tests |
| `crates/quervant-core/tests/pr15h_b_sort_materialization.rs` | public-path integration suite |
| `benchmarks/pr15h_b/` | six-lane absolute-millisecond controller and tests |

Protected and unchanged: `execute.rs`, `score.rs`, segment codecs/format,
manifest/`CURRENT`, storage/cache/RustFS, Cargo manifests/lockfile, CI, public
APIs. Query-only index digests are byte-identical between arms.

## Rollback (not used)

If a future acceptance gate fails, the prescribed additive rollback is to restore
the three production files to the baseline `6e47eed` blobs, keep the benchmark,
tests and evidence, and verify:

```
git diff --quiet 6e47eed3f35a5fad8db6dab24c66f386567e95c0 HEAD -- crates/quervant-core/src/search crates/quervant-core/src/segment
```

No history rewrite, no evidence deletion and no self-approval.
