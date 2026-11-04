# PR 15G-A qualification and blocked gates

**Status:** `QA_PASS_PERF_BLOCKED_OPERATOR`
**Code HEAD:** `73cbc78441ae9e97f58942a72ccdc4276db4590d` (docs follow-up only after this)
**Performance:** P01–P04 **BLOCKED_OPERATOR**
**Real RustFS:** GA-I07/GA-I08 **BLOCKED**
**Exact-head hosted CI:** **BLOCKED / NOT OBSERVED**

## Performance qualification (P01–P04)

No timed A/B measurement was performed. The plan requires an explicit,
operator-provided idle-window confirmation; the implementation request ("assume
the host is idle") is not a substitute for that attestation, and PR 15F approval
cannot be reused.

The runner's negative authorization gate was executed as the only authorized
performance action:

```text
$ python3 benchmarks/pr15g_a/run.py \
    --source-tree /tmp/nonexistent-baseline \
    --out /tmp/nonexistent-out
runner_exit=3
PERF_BLOCKED_OPERATOR: a real operator idle confirmation is required
(--idle-confirmed); this runner never synthesizes one and no timing was performed.
```

Evidence: `target/pr15g-a/qa/runner-unauthorized.err`.

| Gate | Status | Reason |
|---|---|---|
| P01 same-host 3-trial nine-lane A/B | BLOCKED_OPERATOR | no genuine operator idle confirmation |
| P02 100K absent/K100 `B_FASTER` | NOT MEASURED | prerequisite P01 blocked |
| P03 10K absent/K100 `B_FASTER` | NOT MEASURED | prerequisite P01 blocked |
| P04 no other-lane `A_FASTER` | NOT MEASURED | prerequisite P01 blocked |
| P05 no byte/codec/correctness/memory-cap change | PASS locally | format and budget semantics unchanged; QA above |
| P06 report 100K/10K context without promising speedup | UNAVAILABLE | no measurement exists |

The runner and its deterministic tests are ready for an authorized campaign. No
verdict, ratio, trial median or speedup is claimed.

## Required topology for a future authorized campaign

1. Two read-only clean Git worktrees on a native Linux filesystem (not
   `/mnt/c`), one at the pinned baseline `f44d7f4...` and one at a committed
   descendant containing this implementation.
2. Separate Cargo target directories; corpus generation, deterministic index
   builds and oracle checks outside timed windows.
3. Operator-provided `--idle-confirmed`, then three independently qualified
   trials per arm; every trial must report `clear` contention before and after.
4. The runner publishes only the sanitized comparison under the chosen stage
   root beneath `target/pr15g-a/`.

## Real RustFS and integration gates

`docker` is not installed on this host and no pinned RustFS service or
credentials are available. No fake adapter or local substitute is offered as
acceptance evidence.

| Gate | Status |
|---|---|
| GA-I01 memory index/query/column parity | PASS |
| GA-I02 real `FsDirectory` commit/reopen | PASS |
| GA-I03 PIT vs delete/insert/commit | PASS |
| GA-I04 concurrent snapshot readers | PASS |
| GA-I05 small metadata cap fallback | PASS |
| GA-I06 corrupt column geometry | PASS |
| GA-I07 real RustFS empty-cache bootstrap/query/reread | BLOCKED — no RustFS service |
| GA-I08 fault proxy/restart/interrupted download | BLOCKED — no RustFS service |
| Hosted `rust`, `msrv`, `rustfs` jobs at exact PR HEAD | BLOCKED / NOT OBSERVED |

## Gate summary

| Gate | Status |
|---|---|
| A00 exact base/preflight | PASS |
| A01 borrowed immutable geometry, no reparse on admitted hit | PASS locally |
| A02 exact allowance/charge, zero-cap and cap-rejection fallback | PASS locally |
| A03 typed errors/value/validation parity | PASS locally |
| A04 concurrent/guard/PIT/refresh identity | PASS locally |
| A05 no format/bytes/forbidden production change | PASS locally |
| A06 real local writer/commit/reopen | PASS; real RustFS BLOCKED |
| A07 nine-lane A/B qualification | BLOCKED_OPERATOR |
| A08 stable/MSRV/coverage/scripts/docs | PASS locally |
| A09 exact-final-HEAD hosted CI | BLOCKED / NOT OBSERVED |
| A10 independent review/approval | NOT STARTED |

## Residual risks

- The performance hypothesis (G03 column-setup CPU share) remains unproven as
  recoverable wall-clock time until an authorized A/B campaign runs.
- Retained geometry increases the measured metadata charge by the actual
  `Vec<ColumnMeta>` capacity; candidate admission is the only gate, and rejected
  candidates retain nothing. This was verified locally but not RSS-profiled.
- No real RustFS cold-reader or provider-fault acceptance was executed here.
