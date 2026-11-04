# PR 15G-C fixup qualification

**Status:** `FIXUP_PERFORMANCE_REJECTED_SAFE_ROLLBACK`
**Pre-C Arm A:** `018fdd768d0898d6709baeb8661998ee1a82947c`
**Fixup candidate (historical):** `0a55119b1d47ab4bbd7d9205ad1d84a636d96c2f`
**Final source:** B production search source `97d7ce1`.
**Umbrella PR:** #86 — open, not merged.

## Gates

| Gate | Status | Evidence |
|---|---|---|
| GF-A00 identity/preflight | PASS | `preflight.md` |
| GF-A01 B carryover | PASS | `gc_br01a–e`, `gc_br02a/b` |
| GF-A02 investigation/design | PASS | `investigation.md`, `design-verification.md` |
| GF-A03 two-pass semantics | PASS before rollback | focused/unit/integration tests |
| GF-A04 mandatory adversarial tests | PASS before rollback | GF-U05/U06/U15/U16/U21/U22/U23/U25/U31 |
| GF-A05 local/real services | PASS before rollback | local FS, C/A/B RustFS, fault suites |
| GF-A06 local QA | PASS before and after rollback | stable/MSRV, coverage, scripts |
| GF-A07 performance | **FAIL** | GF-P01 and GF-P04 |
| GF-A08 hosted CI | pending final rollback HEAD |
| GF-A09 independent review | NOT STARTED | human-owned |
| GF-A10 safe rollback | PASS | byte-equality to `97d7ce1`; QA/RustFS pass |

## Mandatory test evidence before rollback

- Two postings opens for nonempty term; absent term no second decode.
- Invalid nonwinner score returns `InvalidScore`.
- Later invalid score outranks earlier candidate-admission error.
- First candidate error is returned after the full score pass when later scores
  are valid.
- `u32::MAX + 1` frequency reaches the scorer as `u64` with distinct score bits.
- Candidate entry and byte limits match legacy exact/one-under boundaries.
- Test-only pass-count mismatch fails closed and the next query recovers.

## Performance failure and rollback

The fixup improved some high-hit lanes (100K common/K10 PASS, medium
INCONCLUSIVE, common/K100 INCONCLUSIVE) but failed GF-P01 (100K common/K100 not
`B_FASTER`) and GF-P04 (10K/100K absent and rare `A_FASTER`). Per the plan, C
production search was rolled back to B source. C is **NOT ACCEPTED**.

## Post-rollback QA

Stable/MSRV fmt, Clippy default/all-features, workspace tests, coverage 92.72%,
docs/bench build, scripts, Python suites and real RustFS/fault tests pass. C
integration and B carryover tests remain green. Details in `rollback.md`.

## Remaining

- Exact final-HEAD CI must be observed after the additive rollback push.
- Independent human review remains pending.
- No merge/self-approval occurred.
