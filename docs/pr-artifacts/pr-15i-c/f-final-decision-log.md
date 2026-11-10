# PR 15I-C-F — decision log

Chronological, one entry per decision point. No threshold, lane, schedule or
protocol value was changed at any point.

| # | Event | Decision | Evidence |
| --- | --- | --- | --- |
| 1 | Preflight: clean tree, protected paths identical, `fmt`/`check` green, 382 `pr15i_c` tests pass, frozen protocol unchanged | continue | `f-final-preflight.md` |
| 2 | `F_DIAG` built from `CAUSAL_PARENT` plus exactly one attribute and the prescribed test update | commit `5f74bb69…` | source proof `FS_SCOPE`/`FS_DIFF`/`FS_BODY` |
| 3 | Diagnostic binary carries standalone `collect_mixed`, `collect_exact_term_physical` and `execute_unified` symbols plus the mode gate | G and P differ only by environment | codegen capture |
| 4 | Protocol and tooling frozen (four campaigns, 4×8 slots, fixed gates) | commit `956a553d…` = first `F_TOOLING_SHA` | `f_final_protocol_v1.json` |
| 5 | Attempt 01 aborted before any timed sample: size builds indexed by a non-existent `F` arm key | fix within contract, preserve attempt, restart | `attempt-01-unbatched-01/INVALID.json` |
| 6 | Attempt 02 aborted before any timed sample: size records never attached to arm contexts | fix within contract, preserve attempt, restart | `attempt-02-unbatched-01.json` |
| 7 | Full dry run of controller + verifier (no evidence) exposed harness-contract mismatches (contention `state`, corpus inventory, codegen payload, zero-hit lanes, gate binary per arm) | fix within contract, freeze new tooling SHA `3119c408…` | dry run, then attempts 01/02 preserved |
| 8 | Attempt 03 measured all 32 slots, then aborted because the codegen capture directory was repository-scoped and collided with a stale capture | treated as the single authorized **post-sampling** defect: invalidate, preserve 32 slots, scope capture to the campaign, run capture before the first timed slot, restart the whole series | `attempt-03-unbatched-01/INVALID.json` (5 760 samples preserved, no seal, no receipt) |
| 9 | Tooling revision `89244ece…` frozen; complete four-campaign series run from zero | no further tooling changes | `unbatched-01`, `batched-01`, `unbatched-02`, `batched-02` |
| 10 | A/A stable in all four campaigns | continue to C reproduction | receipts |
| 11 | C reproduces on all eight low-match cells | continue to G neutrality | receipts |
| 12 | Four lanes exceed both G/A ceilings in both unbatched campaigns | `F_GENERIC_BOUNDARY_REJECTED`; do not build `F_RELEASE`, do not run the frozen campaign, roll back additively | receipts + series receipt |
| 13 | Rollback: seven files restored to `BASE_A`, physical test file removed | production byte-identical to merged PR 15I-B | `git diff 6f6463cb… -- crates/` empty |

## Deviations from the plan and their authorization

| Deviation | Authorization | Effect on evidence |
| --- | --- | --- |
| Three aborted attempts (01, 02, 03) preserved outside the sealed series | §8.6 allows pre-sampling fixes and one post-sampling restart with prior raw untouched | no sample from an aborted attempt enters any statistic; attempt 03 raw is preserved but excluded |
| Codegen capture moved before the slot loop | mechanical ordering only; adapters are hash-checked before and after the campaign | identical binaries, identical measurement code |
| Verifier aggregate accepts already-written per-campaign receipts after recomputing them from raw data and rejecting any mismatch | receipt immutability | no statistic taken from a receipt |

## Non-authorizations

No push, no PR, no merge, no protocol/threshold change, no lane change, no
corpus change, no re-run for a favourable result, no `F_RELEASE` build, no
frozen-campaign run, no claim that PR 15I-C is accepted.
