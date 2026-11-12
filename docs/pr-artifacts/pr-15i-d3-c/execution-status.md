# PR 15I-D3-C — execution status

**Disposition: `D3C_NOT_EXECUTED` (implementation subset only; measurement not started).**

This is **not** one of the plan's complete dispositions. The study was not
executed to completion, and no D3-C performance or policy claim exists.

| Item | State |
|---|---|
| Branch / start HEAD | `dev/pr15i-d3b-retained-key-prefilter` / `99652d75…` |
| BASE / rejected D3-B / rollback | `39dbd9f5…` / `48d9abf3…` / `5d3bf1f7…` |
| Experimental source | additive WIP commit on this branch (see final report); **not T4** |
| Cargo change | empty non-default `pr15i-d3c-experiment` feature only |
| Default behavior | unchanged BASE linear path; default and all-feature tests pass |
| Strategy correctness | 24 targeted unit tests PASS; full prescribed U01–U42 incomplete |
| Micro grid / profile | NOT RUN |
| D3-C tooling / T4 | NOT IMPLEMENTED / NOT FROZEN |
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

That remaining work cannot be implemented and independently validated within
this execution session. Per C-60, dependent tooling/measurement was HARD
STOPPED and the additive, non-default experimental source preserved. No partial
or fabricated policy is reported.

## Smallest required human decision

Authorize a dedicated execution session (or split the plan) to complete
S2–S5: micro grid + profile freeze, the 72-lane controller/verifier/policy/
rehearsal, T4, the fresh 72-lane A/A control, both four-arm campaigns and the
policy output. The current experimental source must be reviewed and pinned as
the D3-C source commit before that session's T4; it is not yet a frozen study
identity.
