# PR 14B — deterministic fault and recovery matrix

All faults were exercised against the pinned real RustFS 1.0.1 service through
the existing test-only HTTP fault proxy
(`crates/quervant-objectstore/tests/support/mod.rs`, `Fault` at line 25,
`Rule` at line 49) and the separate-process crash checkpoints. No production
code, production bucket or shared object was modified to create a fault.

## Fault location → expected result → durable state

| ID | Fault stage / injection | Expected observable | Expected published generation | Allowed error | Durable data after fault | Test |
|---|---|---|---|---|---|---|
| F01 | Interrupted segment GET / manifest staging: `Return503` on the first `index/segments` GET | Open either retries to success or fails typed; never a partial index | Previous committed generation unchanged (generation 1) | Retryable `IndexError::Storage` (bounded) | Last committed generation queryable; healthy reopen equals oracle | `pr14_storage_faults::f01_segment_get_transient_failure` (line 345) |
| F01b | Interrupted manifest/CURRENT read: `Return503` on `index/CURRENT` | Open fails closed | Previous committed generation unchanged | `IndexError::Storage` | Healthy reopen equals oracle | `f04_manifest_read_interrupted` (line 402) |
| F02 | Conditional `CURRENT` publication: CAS applied but response dropped (`ForwardThenDrop`) | Writer reconciles the applied CAS; exactly generation 1 is durable | Generation 1 | None on reconciled success | Cold reader sees generation 1 and the inserted document | `pr13_remote_proxy::h10_cas_applied_response_dropped_reconciles` (line 339) |
| F02b | CAS blocked then timeout (never reaches RustFS) | Fail closed; no false durable acknowledgement; writer terminal | Previous committed generation (none beyond base) | `IndexError::RecoveryRequired` | A fresh authoritative reopen is required; no fabricated generation | `pr13_remote_proxy::h11_cas_blocked_then_timeout_requires_recovery` (line 372) |
| F02c | Crash after manifest before `CURRENT` CAS | No new generation visible | Previous committed generation | Process killed (SIGKILL) | `CURRENT` still names the previous generation; healthy reopen works | `pr13_crash_rustfs::k03_crash_after_manifest_before_current` (line 364) |
| F02d | Crash after CAS before acknowledgement | Candidate `CURRENT` is authoritative | The CAS-published generation | Process killed (SIGKILL) | Reopen observes the published generation; no torn state | `pr13_crash_rustfs::k04_crash_after_cas_before_ack` (line 380) |
| F03 | Truncated downloaded segment (`TruncateBodyAfter(16)`) | Reject; never return partial hits | Previous committed generation | `IndexError::Storage` / digest mismatch | Refetch/reopen after restoring health equals oracle | `f02_truncated_segment_transfer` (line 364) |
| F03b | `206` rewritten to `200` with `Content-Range` removed | Ranged-read contract refuses | Previous committed generation | `IndexError::Storage` | Healthy reopen equals oracle | `f03_corrupt_content_range_rejected` (line 383) |
| F03c | Nontransient `403` | No retry; typed failure | Previous committed generation | `IndexError::Storage` with exactly 1 GET | Healthy reopen equals oracle | `pr13_remote_proxy::h08_nontransient_403_is_not_retried` (line 443) |
| F04 | Remote unavailability during cold bootstrap (`Return503` every segment GET) | Bounded retries then failure; no partial ready index | Previous committed generation | `IndexError::Storage` after 3 attempts | Subsequent healthy retry opens the committed generation | `f07_retry_exhaustion_is_bounded_and_recoverable` (line 421) |
| F05 | Cancellation during mixed work / aggregation | Typed cancellation; no successful continuation for the aborted slot; prior successes remain ordered | Unchanged snapshot | `Cancelled{ClientCancellation}` | No partial response emitted | `real::r10_r11_real_remote_budget_exact_and_one_over` (cancellation block) and existing `pr14a_public_cursor::t13` |
| F05b | Cancellation during remote transfer (`DelayUntil`, 250 ms timeout) | Bounded cancellation; nothing published | Previous committed generation | Timeout/`IndexError::Storage` | Workspace removed; healthy reopen equals oracle | `f06_cancellation_during_transfer_is_bounded` (line 495) |
| F05c | Delayed GET cancelled before publication | Publishes nothing | No new generation | Cancellation | No committed change | `pr13_remote_proxy::h09_cancel_during_delayed_get_publishes_nothing` (line 487) |
| F06 | Interrupted cache fill + separate-process crash at the download checkpoint (`BlockBeforeCheckpoint`) | No invalid cache promoted to authoritative; immutable digests stable | Previous committed generation | Child killed | Healthy reopen refetches and equals oracle | `f08_crash_at_download_checkpoint` (line 700) |
| F06b | Crash during partial ranged download | No torn object becomes readable | Previous committed generation | Child killed | Healthy reopen equals oracle | `pr13_crash_rustfs::k05_crash_during_partial_ranged_download` (line 590) |
| F06c | Crash before state / before manifest | No generation becomes visible | Previous committed generation | Child killed | Healthy reopen equals oracle | `k01` (line 332), `k02` (line 348) |
| F06d | Concurrent old reader + new commit | Old snapshot unchanged; fresh reader sees new generation | New generation for fresh reader; old pinned view stable | None | Both views are internally complete | `f05_concurrent_old_reader_and_new_commit` (line 440) |

## Execution evidence

| Suite | Invocation | Result |
|---|---|---|
| `pr14_storage_faults` f01–f09_f10 | each case `--ignored --exact --test-threads=1` | **9/9 PASS**; each case runs 10 unique-prefix iterations |
| `pr13_remote_proxy` h06–h12 | each case individually | **7/7 PASS** |
| `pr13_crash_rustfs` k01–k05 | each case individually | **5/5 PASS** |
| Critical repeats | k03, k04, h10, h11 run 3 end-to-end cycles | **3/3 PASS each** |

The proxy forwards the exact request bytes (including `Host`) so SigV4 remains
valid and observes the real upstream response; it never fabricates a successful
conditional PUT. `ForwardThenDrop` forwards fully, reads the real response, then
closes the client connection without delivering it. The proxy records sanitized
method/key/status counts only — no credentials, signatures or document bytes.

## Things that did **not** change

- No production fault hook was added.
- No ObjectStore API, conditional-write guarantee, cache authority or manifest
  format was changed.
- Test-only wrappers use the existing `ObjectStore`/HTTP boundary.
- Remote fault cleanup touches only the case-owned prefix/workspace.

## Open items

- CI has not executed the `rustfs` job for this branch/SHA, so these results are
  local real-provider evidence, not CI evidence.
- No fault produced a false durable acknowledgement, a partial/corrupt visible
  generation, or an unbounded retry in the observed runs.
