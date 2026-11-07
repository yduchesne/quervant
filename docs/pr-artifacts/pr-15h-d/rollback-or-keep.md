# PR 15H-D — rollback / keep

**Disposition: `PERFORMANCE_REJECTED_SAFE_ROLLBACK`.**

The qualified campaign produced primary conventional medians D-P1 +0.306 ms,
D-P2 +0.298 ms and D-P3 +0.866 ms — none reached the required +2.000 ms — so
D-P01 failed while both guards passed.

## Rollback

`2ac85c7a936fe4e57fea78c54700d0a58a544acf` restores only
`crates/quervant-core/src/search/unified.rs` and
`crates/quervant-core/src/search/unified_plan.rs` to the exact
`c802f965a57d5038e98006bba581c4356654baaf` blobs:

```
git diff --quiet c802f96 HEAD -- crates/quervant-core/src/search/unified.rs crates/quervant-core/src/search/unified_plan.rs
# exit 0
```

That source equals the accepted C rollback (`e8744d3`) search. D-only tests
(`d_tests`, `compile_with_resolved` usage) were removed mechanically by the
restore.

## Preserved

- `benchmarks/pr15h_d/` controller, 49 tests and README.
- Sealed `target/pr15h-d/baseline-01` and `paired-01` raw evidence.
- The D evidence documents and the machine-readable summary.
- Historical A/A2/A3/B/C/15G-C evidence untouched.

No push, PR, merge, self-approval or post-rejection retiming.
