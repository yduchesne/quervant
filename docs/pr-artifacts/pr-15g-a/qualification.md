# PR 15G-A qualification and blocked gates

**Status:** `FIXUP_IMPLEMENTED_LOCAL_QA_PASS_PERF_BLOCKED_OPERATOR_CI_PENDING`
**Original implementation SHA:** `73cbc78441ae9e97f58942a72ccdc4276db4590d`
**Reviewed starting SHA:** `b120f9f8d63901cd4bdc9bb83fb4462a5b11d6ad`
**Fixup commit:** recorded in the final report/PR metadata after commit.
**Performance:** P01–P04 **BLOCKED_OPERATOR**
**Real RustFS:** GA-I07/GA-I08 **EXECUTED LOCALLY PASS** on the pinned image
**Exact-head hosted CI:** **BLOCKED_CREDENTIALS / NOT OBSERVED**

## Performance qualification (P01–P04)

No timed A/B measurement was performed. The plan requires an explicit,
operator-provided idle-window confirmation; "assume the host is idle" in the
implementation request is not a substitute for that attestation, and PR 15F
approval cannot be reused.

The runner's negative authorization gate was re-executed on the fixup tree as
the only authorized performance action:

```text
$ python3 benchmarks/pr15g_a/run.py \
    --source-tree /tmp/nonexistent-baseline \
    --out /tmp/nonexistent-out
runner_exit=3
PERF_BLOCKED_OPERATOR: a real operator idle confirmation is required
(--idle-confirmed); this runner never synthesizes one and no timing was performed.
```

Evidence: `target/pr15g-a/fixup/runner-unauthorized.err`.

| Gate | Status | Reason |
|---|---|---|
| P01 same-host 3-trial nine-lane A/B | BLOCKED_OPERATOR | no genuine operator idle confirmation |
| P02 100K absent/K100 `B_FASTER` | NOT MEASURED | prerequisite P01 blocked |
| P03 10K absent/K100 `B_FASTER` | NOT MEASURED | prerequisite P01 blocked |
| P04 no other-lane `A_FASTER` | NOT MEASURED | prerequisite P01 blocked |
| P05 no byte/codec/correctness/memory-cap change | PASS locally | format and budget semantics unchanged; QA below |
| P06 report 100K/10K context without promising speedup | UNAVAILABLE | no measurement exists |

The runner and its deterministic tests are ready for an authorized campaign. No
verdict, ratio, trial median or speedup is claimed.

## Required topology for a future authorized campaign

1. Two read-only clean Git worktrees on a native Linux filesystem (not
   `/mnt/c`), one at the pinned baseline `f44d7f4...` and one at the committed
   fixup descendant.
2. Separate Cargo target directories; corpus generation, deterministic index
   builds and oracle checks outside timed windows.
3. Operator-provided `--idle-confirmed`, then three independently qualified
   trials per arm; every trial must report `clear` contention before and after.
4. The runner publishes only the sanitized comparison under the chosen stage
   root beneath `target/pr15g-a/`.

## Real RustFS and integration gates

The pinned RustFS image
`rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
was already present locally and was run in a disposable local container with the
CI-equivalent test credentials. No fake adapter or substitute was used, and no
production credential or external port was created outside localhost.

| Gate | Status |
|---|---|
| GA-I01 memory index/query/column parity | PASS |
| GA-I02 real `FsDirectory` commit/reopen | PASS |
| GA-I03 PIT vs delete/insert/commit | PASS |
| GA-I04 concurrent snapshot readers | PASS |
| GA-I05 reduced public limit + private observable fallback | PASS — three complementary witnesses |
| GA-I06 corrupt column geometry | PASS — standalone and metered constructors |
| GA-I07 real RustFS empty-cache bootstrap/typed/sort/warm reread | PASS locally (hosted exact-head pending) |
| GA-I08 fault proxy/restart/interrupted download | PASS locally — H06/H07/H09, K01–K05, K05 10x (hosted exact-head pending) |
| Hosted `rust`, `msrv`, `rustfs` jobs at exact PR HEAD | BLOCKED_CREDENTIALS / NOT OBSERVED |

GA-I07 execution: `ga_i07_real_rustfs_cold_bootstrap_typed_sort_and_warm_reread`
passed against the pinned image. GA-I08 execution: `pr13_remote_proxy` 7 passed;
`pr13_crash_rustfs k0` 5 passed; `pr13_crash_rustfs k05` passed 10/10 repeated
runs. Logs are under `target/pr15g-a/fixup/`.

## Gate summary

| Gate | Status |
|---|---|
| A00 exact base/preflight | PASS |
| A01 borrowed immutable geometry, no reparse on admitted hit | PASS locally |
| A02 exact allowance/charge, zero-cap and cap-rejection fallback | PASS locally |
| A03 typed errors/value/validation parity | PASS locally |
| A04 concurrent/guard/PIT/refresh identity | PASS locally |
| A05 no format/bytes/forbidden production change | PASS locally |
| A06 real local writer/commit/reopen | PASS locally |
| A07 nine-lane A/B qualification | BLOCKED_OPERATOR |
| A08 stable/MSRV/coverage/scripts/docs | PASS locally |
| A09 exact-final-HEAD hosted CI | BLOCKED_CREDENTIALS / NOT OBSERVED |
| A10 independent review/approval | NOT STARTED |

Fixup-specific evidence: FX-A00 PASS; FX-A01 PASS; FX-A02 PASS; FX-A03 PASS;
FX-A04 PASS locally / hosted pending; FX-A05 PASS locally / hosted pending;
FX-A06 PASS; FX-A07 PASS; FX-A08 BLOCKED_OPERATOR; FX-A09 BLOCKED; FX-A10 NOT
STARTED.

## Residual risks

- The performance hypothesis (G03 column-setup CPU share) remains unproven as
  recoverable wall-clock time until an authorized A/B campaign runs.
- Retained geometry increases the measured metadata charge by the actual
  `Vec<ColumnMeta>` capacity; candidate admission is the only gate, and rejected
  candidates retain nothing. This was verified locally but not RSS-profiled.
- Local real-RustFS execution is strong supporting evidence, but hosted
  `rustfs` acceptance at the exact final PR HEAD must still run before merge.
- The fixup exercised existing remote fault/crash harnesses; it did not add new
  fault-injection behavior.
