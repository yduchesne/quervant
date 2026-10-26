# PR 14E — resource-risk reconciliation (`R-14A-JSON-MEM`)

**No RSS, allocator-capacity or physical-memory-cap claim is made anywhere in this
document.** All numbers are either logical reservation-ledger thresholds or
test-only allocator-window observations inside spawned child processes.

This document is an **additive** current-state note. It does not modify the PR 14C
decision record (`docs/pr-artifacts/pr-14c/resource-risk-disposition.md`), which
remains the governing human decision, and it does not close the risk.

## 1. Governing human decision (unchanged)

| Item | Value |
|---|---|
| Risk | `search::typed::json_sort_value` extracted JSON-path occurrences without charging the temporary `Vec<JsonOccurrence>` (and owned payloads) to `SlotMemoryScope` / cumulative `BatchMemoryBytes` |
| Decision | `REQUIRE SEPARATE CORRECTION` |
| Literal instruction | "proceed with option 2" |
| Date (UTC) | 2026-10-24 |
| Decision maker | repository maintainer (named signature still required at signoff) |
| Accepted bounds | **NONE** — the risk is not accepted |
| Recorded scope | PR 14 acceptance (blocked until corrected) |
| Record | `docs/pr-artifacts/pr-14c/resource-risk-disposition.md` §5 |

PR 14E does not reword, soften or supersede this decision. It records what has
since been merged and verified.

## 2. Corrective implementation (merged)

| Item | Value |
|---|---|
| Design | `docs/pr-artifacts/pr-14d/design-and-ownership.md` |
| Implementation commit | `d0e1bbbd841feff6615d7824dd3261a2418511f7` |
| Admission-order fixup (SR-14D-01) | `3f82284` — `fix(pr14d): admit JSON sort winner memory before cloning` |
| Evidence commits | `9f9371c`, `635c7f4` |
| PR | #64 (merged `true`, merge commit `6d18ebed4c2a8c7d73ca9e5078019d50546cb675`) |
| Reviewed/final head | `635c7f4a89c5e2e9478da23c2a533e8dc1f80e09` |
| Final-head CI | `rust`, `msrv`, `rustfs` — all `completed/success` (run `actions/runs/40326618997`) |

What the correction does (source inspection at `dc506f6`):

- `push_occurrence` preflights capacity growth and charges the occurrence vector
  before the retaining push, reconciling to actual capacity afterwards.
- Owned path components, member strings and node string payloads are charged
  before retention (`retained_owned_bytes`).
- Candidates are compared as **borrowed** `&JsonNode` values with canonical
  ordering (`json_sort_scalar_rank` / `json_sort_scalar_cmp`,
  `f64::total_cmp`, UTF-8 byte order for strings); no losing string is cloned.
- The winner is materialized exactly once, **after** `JsonSortBuffer::Winner`
  admission (`materialize_json_sort_winner`); a `#[cfg(test)]` probe increments
  only after admission.
- The occurrence reservation stays alive until the buffer is dropped; the typed
  error is preserved on cleanup and cancellation paths; `sort_scratch.finish()`
  handoff and the public API/cursor/format contracts are unchanged.

## 3. B20/B21 characterization — pre-fix vs post-fix

Same child-process probe, same labels, same host/profile.

| Occurrences | Logical boundary **pre-fix** | Logical boundary **post-fix** | Tracked peak (exact) pre → post | Tracked peak (one-under) pre → post | Cancelled pre → post |
|---:|---:|---:|---|---|---|
| 1 | 112 B | **387 B** | 33,675 → 33,547 B | 33,104 → 33,547 B | 7,397 → 7,397 B |
| 128 | 112 B | **45,726 B** | 110,392 → 110,392 B | 41,233 → 110,392 B | 7,397 → 7,397 B |
| 4,096 | 112 B | **1,462,302 B** | 2,518,968 → 2,518,968 B | 303,121 → 2,518,968 B | 7,397 → 7,397 B |

Interpretation, exactly as scoped by PR 14D:

- The logical threshold now **grows with occurrence demand** (≈3,779× from 1 to
  4,096 occurrences) instead of being the constant `112 B`.
- One-under budgets still reject with typed `BudgetExceeded(BatchMemoryBytes)`;
  their tracked window no longer exceeds the exact-limit window at these counts.
- Cancellation stays typed at 7,397 B and retains no partial success.
- The tracked peak **remains larger** than the logical threshold. That divergence
  is expected and is **not** evidence of unbounded memory: a logical reservation
  ledger is not a physical allocator bound.
- The fixup targets allocation **ordering**, not a guaranteed allocator-peak
  reduction; the numeric winner peaks are unchanged by design.

PR 14E re-executed the characterization test at current head to confirm the cited
thresholds still describe merged code (`pr14b_json_memory`: 1 passed, 1 ignored
child entrypoint). See `validation-report.md`.

## 4. Limits that must accompany every citation

| Limit | Statement |
|---|---|
| Measurement class | Test-only tracking `#[global_allocator]` inside explicit child-process windows. Not RSS, not allocator capacity, not a global maximum, not a hard bound |
| Charged vs uncharged | Occurrence vector, owned path/member/node payloads and the winner buffer are charged; one decoded `JsonOccurrence` and the legacy walker path/stack remain bounded, **uncharged** pre-admission transients |
| Structural bounds | `MAX_JSON_PATH_DEPTH` 128, `MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT` 65,536, `MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT` 8,000,000, `MAX_JSON_PATH_MEMBER_BYTES` 65,535, `MAX_JSON_PATH_SECTION_BYTES` 256 MiB |
| Scope of the meter | `BatchMemoryBytes` is a reservation ledger for covered allocations; a budget-sufficient workload can still exceed the logical figure through allocator overhead and the bounded decode transient |
| Environment | One host/profile (WSL2, debug profile). Absolute bytes are indicative; the threshold-growth and typed-rejection relations are the material findings |
| Legacy JSON-sort fixture | The legacy batch-sort path has unit-level evidence (`t09_legacy_extraction_rejects_before_retained_growth`) and the PR 11 legacy suites; there is no dedicated legacy JSON-**sort** integration fixture (recorded PR 14D limitation, unchanged) |

PR 14E adds no new measurement and makes no claim narrower or broader than the
above.

## 5. Source-drift check (why the 14D provider evidence still applies)

PR 14E did not re-run a provider. To decide whether PR 14D's qualified provider
evidence still describes merged code, the trees were compared:

```
$ git diff --stat 3f82284..dc506f6 -- crates/ Cargo.toml Cargo.lock benchmarks/ .github/
   (empty)
$ git diff --stat 635c7f4..dc506f6
   README.md                                | 38 ++++++++++++++----------------
   docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md | 24 ++++++++++++++++++++
```

Between the corrected implementation (`3f82284`, on which the PR 14D provider
re-run and workspace gates were executed) and current `main` (`dc506f6`) there is
**no change to `crates/**`, `Cargo.*`, `benchmarks/**` or `.github/**`** — only
documentation commits. Therefore:

- PR 14D's real-RustFS verticals/faults remain applicable to the current code
  tree; they are cited as `REUSE-14D` and were **not** re-executed in PR 14E.
- The final-head CI at `635c7f4` and at `dc506f6` covers the same code.

If a future PR changes the JSON-sort, occurrence-decoding, batch-meter or
provider paths, this conclusion lapses and the affected rows become `BLOCKED`
pending a controlled re-run (§8 of the execution plan).

## 6. Remaining caveats and status flags

| Item | State |
|---|---|
| Correction implemented | YES |
| Correction merged (`6d18ebe`) | YES |
| Correction CI-verified (`635c7f4`, `dc506f6`) | YES |
| Independent source review of the correction | **PENDING** |
| Human risk-closure acceptance | **NOT RECORDED** — risk remains unaccepted |
| Physical/RSS cap claimed | **NO** — never |
| `R-14A-JSON-MEM` gate | **BLOCKED** at the crosswalk row (CW-127) |
| PR 14 acceptance | **NOT ACCEPTED** |
| v0.1 release | **NOT CLAIMED** |

## 7. What the maintainer must record to close the risk

A dated, named decision that states: the affected paths (typed and
unified/pinned JSON-path sort), the corrected charging behaviour, the numeric
limits relied upon, that the logical meter is **not** a physical memory cap and
that bounded transients remain uncharged, operational mitigations (if any), the
decision scope (PR 14 acceptance vs v0.1 release), and the residual limitation.

Until that record exists, no agent may convert this evidence into acceptance
(EAD-15, decisions X20 and X26).
