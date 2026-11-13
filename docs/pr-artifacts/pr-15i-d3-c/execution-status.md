# PR 15I-D3-C — execution status

**T4 FROZEN at `cb3f3c8`; official A/A control BLOCKED (17 drift violations, retries=0). No campaigns/policy.**

**Current checkpoint:** HEAD `8f6e353b16386e570b63833ea830026de98fdea9`
(+ this docs/policy checkpoint). Source integration I01–I12 is closed except
U24/U25/U40; I11 RustFS m1/m2 PASS. T4 is **NOT FROZEN**; no official A/A or
campaign has run. See `session-correctness-closure.md`.

**Disposition: `D3C_NOT_EXECUTED` (implementation, micro/P2, preflight, dry-proof and a partial synthetic rehearsal; T4 not frozen, no measurement).**

This is **not** one of the plan's complete dispositions. The study was not
executed to completion, and no D3-C performance or policy claim exists.

| Item | State |
|---|---|
| Branch / start HEAD | `dev/pr15i-d3b-retained-key-prefilter` / `99652d75…` |
| BASE / rejected D3-B / rollback | `39dbd9f5…` / `48d9abf3…` / `5d3bf1f7…` |
| Experimental source | `f2565509f75472cac8a6b380ea29791036a46f0c` (WIP); not T4 |
| Cargo change | empty non-default `pr15i-d3c-experiment` feature only |
| Default behavior | unchanged BASE linear path; default and all-feature tests pass |
| Strategy correctness | 24 targeted unit tests PASS; full prescribed U01–U42 incomplete |
| Micro grid / profile | PASS (192 records, 5 rounds); **P2 selected** by the frozen rule |
| D3-C tooling / T4 | controller/verifier/policy/replay draft; `preflight` and `dry-proof` pass; rehearsal 3 positive + 5 negatives pass; V/M/P/RH tests and manifest missing; **T4 NOT FROZEN** |
| Rehearsal / control / campaigns / policy | NOT RUN |
| Historical evidence | unchanged (T0–T3 diffs empty); F1.2 verdict untouched |
| `disk-cleanup.sh` | preserved untouched |
| CI / review / PR | `CI_PENDING` / `REVIEW_PENDING` / `PR_NOT_CREATED` |

## Why execution stopped

The plan requires, before any official timing:

1. a new 72-lane, 4-arm controller, independent verifier, policy tool and
   synthetic rehearsal (~3,000 lines) with exact mode-marker, readiness,
   succession and sealing semantics; and
2. two complete four-arm campaigns plus a 72-lane A/A control (32 + 32 + 16
   slots; 46,080 + 46,080 + 23,040 timed samples, ~6,900 adapter processes),
   with microdiagnostics and T4 freeze.

Progress since the first stop: the strategy source and 24 unit tests pass, the
full micro grid ran and selected P2, and `run.py preflight` proved the
feature-enabled build works (distinct BASE/experiment binaries). The remaining
items (policy/replay/tests/manifest, T4, rehearsal, 72-lane A/A control and two
four-arm campaigns) are still outstanding. Dependent official measurement was
not started because the freeze/rehearsal gates are not met. No partial
or fabricated policy is reported.

## Smallest required human decision

Authorize a dedicated execution session (or split the plan) to complete
S2–S5: micro grid + profile freeze, the 72-lane controller/verifier/policy/
rehearsal, T4, the fresh 72-lane A/A control, both four-arm campaigns and the
policy output. The current experimental source must be reviewed and pinned as
the D3-C source commit before that session's T4; it is not yet a frozen study
identity.
