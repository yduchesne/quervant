# PR 14C — adversarial review

**Status: `BLOCKED / NOT ACCEPTED`.** This file records the falsifying checks
that were actually executed, the failure classifications, the credibility limits
of the test harness, and the known gaps that an independent reviewer should
challenge. It does not assert acceptance.

## 1. Falsifying checks executed (not merely present in source)

| Challenge | How it could falsify the claim | Observed |
|---|---|---|
| Score order is not key order | `real::b02` chooses survivors `zfew,aonce` while key order is `aonce,zfew`, and asserts descending scores | PASS on real RustFS |
| Pagination is not a key-only scan | 14A `t02`–`t05` compare resumed pages to the full unpaginated order; `t04` compares score bits | PASS |
| Cursor cannot be reused across handles/queries | Wrong handle → `ConflictingPit`; changed query/sort → `CursorSortMismatch`; expired at exactly `expires_at` → `ExpiredCursor` (`real::b06_b07`, 14A `t06/t07/t10`) | PASS |
| Budgets are not silently reset | `pr14_batch_memory` b12e/b12f/b11a; `real::r10_r11` exact-then-one-under for memory/response/work | PASS |
| Failed slot does not erase siblings | Three-slot S/F/S in `pr14_batch` b11/b13, 14A `t08/t13`, `real::r08_r09_r15` | PASS |
| Old pinned generation is not mutated | `real::r05` retains a `PitHandle` across upsert+delete+commit and cold reopen | PASS |
| Cold reader has no writer-local state | `real::r01` separate process with a deleted workspace; `real::r12` empty cache | PASS |
| Corrupt bytes are not reinterpreted | `b18_b19`: flipped payload byte rejected; major version 2 → `UnsupportedFormatVersion` | PASS |
| Faults never publish partial state | F01–F10 × 10 iterations; proxy `h06`–`h12`; crash `k01`–`k05` | PASS |
| Memory meter is not a physical cap | B20/B21 records 112 B logical against up to 2,518,968 B tracked heap | Confirmed divergence (risk open) |
| Benchmark validator rejects bad reports | `validate-pr14-p4.py --self-test` (missing rows, bad digest, <3 trials, dirty tree, missing idle, non-clear contention, <20 samples, <3 warmups, missing/invalid W08 exemption) | PASS |
| W08 is not being smuggled in as measured | Validator requires the approved exemption manifest; W08 is labelled N/A everywhere | PASS |

## 2. Failed or unqualified attempts

| Attempt | Outcome | Classification |
|---|---|---|
| PR 14B baseline run of `real::r08_r09_r15_real_batch_aggregation_and_cursor` (historical) | Panicked on `PinnedContextRequired` because the ignored test predated the PR 14A fail-closed contract | **DETERMINISTIC PRE-EXISTING** test defect; corrected test-only in PR #61; **passes now** |
| Qualified P4 trials in PR 14C | Not attempted — no operator `--idle-confirmed` attestation; acceptance blocked anyway | **DEFERRED / BLOCKED**, not a failure of the code |
| Diagnostic benchmark run | Not performed | N/A — could not qualify |
| Any fix to production code | Not attempted (out of scope) | N/A |

No run was relabelled from diagnostic/unqualified to qualified. No ignored test
was quietly executed as a substitute for a parent case, and no parent case was
replaced by a fake.

## 3. Test-harness credibility

- **Real provider, not a fake:** every real-boundary assertion ran against the
  pinned image digest `sha256:1803faef…6a3c` (`rustfs:1.0.1`), verified with
  `podman image inspect`, health-checked before execution.
- **Independent oracles:** expected keys, counts, groups and orders are
  enumerated in-test or hand-derived in `pr14_p4_v1`; production comparators are
  not used to compute expectations.
- **Process isolation:** B20/B21 (allocator windows), `r01` (cold bootstrap) and
  `f08` (SIGKILL) run in spawned children so parent-process state cannot leak in.
- **Fault injection is at the HTTP boundary** in front of the real service
  (`ForwardThenDrop`, `Return503`, `TruncateBodyAfter`, range rewrite, blocked
  checkpoint); no production fault hook exists.
- **Negative self-tests** of the benchmark validator run on the same machine and
  reject malformed reports.

Limits: the fault proxy is test-only code; the allocator probe measures tracked
heap inside windows, not RSS; the WSL2 host is not a bare-metal reference.

## 4. Known limitations and uncovered areas

| Item | Status | Impact on PR 14 |
|---|---|---|
| `R-14A-JSON-MEM` | `REQUIRE SEPARATE CORRECTION` | **Blocks acceptance**; unmetered transient JSON-sort occurrence memory |
| Zero query-time remote GET (I13 / corrective I12 / final-design I13) | No instrumentation | **BLOCKED** — claim cannot be made |
| Exact physical hit identity (`HitRef`) | No public assertion | **BLOCKED** for corrective I07 / final-design I8 |
| Legacy JSON fallback J14/J15 | No dedicated PR 14 test | **BLOCKED** |
| Original U/G/R/X matrices | Per-ID definitions not recoverable from the repository | **BLOCKED** (family-level evidence only); no invented mapping |
| W08 eviction/reload | Approved Option 2 v0.1 exception | Not measured by contract |
| Fresh P4 benchmarks | 0 of 3 qualified trials | **BLOCKED** |
| Final-SHA CI | No PR run; `gh` token invalid | **BLOCKED** |
| Independent reviewer | Not yet performed | **PENDING** |
| JSON cross-version migration | No older supported wire version exists | Not claimed; out of scope |

## 5. Failure classification summary

| Class | Occurrences in PR 14C |
|---|---|
| INTRODUCED REGRESSION | 0 |
| FEATURE DEFECT | 0 discovered (no production code changed) |
| DETERMINISTIC PRE-EXISTING | 1 historical test-only defect (fixed before PR 14C, passes now) |
| NONDETERMINISTIC / FLAKY | 0 observed in this run |
| ENVIRONMENT / HARNESS | 0 failures; benchmark and CI gates blocked by missing human attestation/CI, not by harness failure |

## 6. Reviewer prompts

A reviewer should independently try to falsify:

1. That every `BLOCKED` row in
   [acceptance-reconciliation.md](acceptance-reconciliation.md) is genuinely
   unmapped rather than conveniently omitted.
2. That the historical `ab9b2d7` benchmark numbers are never presented as
   current-branch measurements.
3. That `execute_batch` still rejects PIT/cursor-bearing requests
   (`batch.rs:61`) while `execute_batch_pinned` is the only supported pinned
   path.
4. That no file outside `docs/pr-artifacts/pr-14c/` and the additive supersession
   notes was modified.
5. That the `R-14A-JSON-MEM` decision is recorded as
   `REQUIRE SEPARATE CORRECTION` and not softened into acceptance.
6. That coverage (91.27 % lines) is measured over all workspace production code
   with no new exclusions.

No acceptance is claimed by this review.
