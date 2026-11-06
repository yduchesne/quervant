# PR 15H-A2 — performance qualification and disposition

## Qualification

| Requirement | Result |
|---|---|
| Sealed pre-optimization baseline before production edits | PASS |
| Baseline `--verify-only` byte reproduction | PASS |
| Candidate descendant of A2 base | PASS |
| Clean, detached, pinned source worktrees | PASS |
| Same A2 tooling revision for baseline and paired | PASS |
| Frozen PR15D/PR15E inputs unchanged | PASS |
| Same host fingerprint | PASS |
| Byte-identical query-only corpus/index digests | PASS |
| 8-slot mirrored schedule, 56 lane records | PASS |
| 1,120 samples, 280 warmups, 16 clear probes, 56 oracles | PASS |
| Frozen nearest-rank summaries recomputed | PASS |
| Cross-session and within-arm drift caps | PASS |

No `MEASUREMENT_BLOCKED` condition occurred.

## Frozen verdict: `PERFORMANCE_REJECTED`

- HA2-P01/P02 PASS: both 100K common lanes are `B_FASTER`.
- HA2-P03 PASS: 100K medium is INCONCLUSIVE.
- HA2-P04 **FAIL**: 10K rare, 100K rare and 100K absent are `A_FASTER` on all
  four paired ratios.

The plan's frozen rule rejects the candidate even though the high-cardinality
targets improved. No threshold tuning, lane substitution, rerun or alternative
statistic was applied.

## Source disposition

`PERFORMANCE_REJECTED_SAFE_ROLLBACK`.

`execute.rs` and `unified.rs` were restored byte-for-byte to `7a136f7`:

```
git diff --quiet 7a136f7 HEAD -- crates/quervant-core/src/search   → exit 0
```

Preserved: `benchmarks/pr15h_a2/` controller (26 tests), the independent
public-path integration suite `crates/quervant-core/tests/pr15h_a2_dispatch.rs`
(8 tests), sealed raw evidence and this artifact set. Test-only code that
referenced the rejected helper was removed mechanically by the source restore;
no pre-existing historical test was edited. A later test-only lint fix in the
preserved integration suite (raw digest bytes instead of a hex string) does not
affect production or the measured adapter binary.

## Not done

No new performance experiment, threshold change, lane change or retry after the
qualified rejection. Hosted CI was not run because the branch was not pushed.
