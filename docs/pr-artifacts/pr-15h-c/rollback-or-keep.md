# PR 15H-C — rollback / keep disposition

**Decision: `PERFORMANCE_REJECTED_SAFE_ROLLBACK`.**

The qualified C campaign failed HC-P01/P02/P03 (P1 −4.273 ms, P2 −0.954 ms,
P3 −4.067 ms lower-median deltas). Per the frozen plan, no threshold or lane was
changed and no retry was run.

## Rollback

`dd68fcbf4e6f33f214dd2cf9d0a5ed4811980909` restores only
`crates/quervant-core/src/search/unified.rs` to the exact
`e8744d3fe16ee858c7d587aaf3b10d393059b809` blob:

```
git diff --quiet e8744d3fe16ee858c7d587aaf3b10d393059b809 HEAD -- crates/quervant-core/src/search/unified.rs
# exit 0
```

C-only tests/witnesses (`c_tests`, `c_observation`, `cached_doc_key_ref`) were
removed mechanically by the restore; B's fixup tests and the B production code are
byte-identical. No other production file changed at any point.

## Preserved

- `benchmarks/pr15h_c/{run.py,test_run.py,README.md}` (50 tests).
- Sealed `target/pr15h-c/baseline-01` and `paired-01` raw evidence.
- The C evidence documents in this directory.
- Historical B/A2/A3/15G-C evidence untouched.

## Not done

No push, PR, merge, self-approval or new timed campaign after the rejection.
