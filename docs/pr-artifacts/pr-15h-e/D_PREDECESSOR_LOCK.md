# PR 15H-E — D predecessor lock (CI waiver)

## Verified D closeout

- D final HEAD: `b05216ee83430d4e15373912aeaf0bd18bd27d97`
- D closeout commit: `7878caaeed8ee7a3b9dfef3191a1f57e0bd3ffcd`
- D source rollback is byte-identical to `c802f96` for `search/unified.rs` and
  `search/unified_plan.rs`.
- D baseline seal `72c8d17d…` and paired seal `902d8432…` verify read-only.
- D controller: 49 tests PASS.
- D disposition: `PERFORMANCE_REJECTED_SAFE_ROLLBACK`.

## Explicit CI waiver

The user explicitly authorized proceeding with PR 15H-E from Stage E1 while
**waiving the D hosted-CI prerequisite**, overriding E-D00/E-D09 solely for the
CI dependency. Hosted CI remains `CI_PENDING / BLOCKED`; it is not claimed green
and does not block local E implementation, correctness, size or latency work.

This waiver changes only the hosted-CI prerequisite, not any technical
acceptance criterion, source-identity check, threshold, test or rollback rule.
