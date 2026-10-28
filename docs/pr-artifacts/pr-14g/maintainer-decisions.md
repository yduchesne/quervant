# PR 14G — maintainer decision packet (CW-041 and CW-127)

**Status: `AWAITING HUMAN DECISION`.** Nothing in this document is a decision.
Both items are **unsigned, unapproved dossiers** prepared by the coding agent so a
maintainer can choose with the facts in front of them. The agent may not elect an
option, write a signature, date a consent, or convert either row to a success.

Rows governed here:

| CW | Historical row | State | Owner |
|---|---|---|---|
| 041 | §4.6 `X01–X13` per-ID oracle matrix | `BLOCKED` | maintainer decision (D-16) |
| 127 | §8 item 7 `R-14A-JSON-MEM` JSON temporary memory | `BLOCKED` | maintainer risk closure (D-18) |

Both rows are **independent of each other** and of Phases A/B, which are already
closed with executed evidence (`phase-a-zero-get.md`, `phase-b-physical-identity.md`).
Either row may be decided alone; neither is required to keep the rest of PR 14G's
evidence valid. PR 14G is **not** accepted while either row remains `BLOCKED`, and
CW-087 (final gates, CI, docs, acceptance) depends on both.

---

## 1. CW-041 — historical `X01–X13` (dossier D-16)

### 1.1 Recovered facts (objective, reproduceable)

| Item | Finding |
|---|---|
| Current disposition | `BLOCKED` in PR 14C §4.6, PR 14E and PR 14G; carried unchanged |
| Historical obligation text | "Independent local / `FakeObjectStore` / real-RustFS oracles, per ID" |
| Only surviving description | `docs/pr-artifacts/pr-14/test-traceability.md:63`: "X01–X13 independent local/FakeObjectStore/real-RustFS oracles: local oracles only; FakeObjectStore/RustFS verticals not executed." |
| Conflicting reuse | `docs/pr-artifacts/pr-14/corrective-test-traceability.md:17` uses `X01` for mixed Boolean equivalence (`I01`); `:24` uses `X01–X10` for RustFS oracle equivalence (`I14`) |
| Git history search | `git log --all -S"X01" -- docs/` → `fa82db7`, `d0c445a`, `e0e1dcb`; no commit contains an `X01…X13` definition table (`git show`/`git ls-tree` inspected for `d0c445a`) |
| Repository-wide search | no per-ID definitions exist anywhere under `docs/` |
| Per-ID tests | none exist and none were fabricated in Phase A/B (Phase A/B add family-level `a01…a06` and `g_b01…g_b05` evidence under new IDs, never claiming `X01…X13`) |

**Consequence:** no agent can mark CW-041 `PASS` today without inventing a mapping,
which would violate the plan's "never invent a missing invariant/test oracle" rule
and AGENTS.md. Only the maintainer can supply or authorize the missing semantics.

### 1.2 Three mutually exclusive options (exactly as recorded in D-16)

**Option X-A — recovered definitions.**

- Maintainer supplies the original authoritative `X01…X13` per-ID table (from an
  external record or a prior document), including each ID's obligation and its
  intended evidence class (local / FakeObjectStore / real RustFS).
- A later reconciliation PR must then produce a per-ID test mapping and executed
  evidence for every ID before CW-041 can move to `PASS`.
- **CW-041 remains `BLOCKED` until that evidence exists.** Supplying definitions
  alone does not close the row.

**Option X-B — documented family-level supersession.**

- Maintainer explicitly approves replacing the undefined historical per-ID claims
  with the *independently executed* family evidence already recorded: local
  oracle/engine tests, deterministic `FakeObjectStore` tests, and the gated real
  RustFS verticals (PR 14B/14D/14F immutable evidence plus PR 14G Phase A).
- The historical literal `X01–X13` stays **one** row with its original ID and is
  marked `SUPERSEDED WITH EVIDENCE` **only after** a dated, named approval that
  cites the evidence being accepted.
- The record must **not** say "X01–X13 per-ID tests passed". It says the grouped
  family claim is superseded by named family-level evidence.
- Under this option, no new per-ID tests are commissioned, and CW-041 may move
  from `BLOCKED` to `SUPERSEDED WITH EVIDENCE` on the maintainer's dated approval.

**Option X-C — new versioned contract.**

- Define an entirely new, explicitly versioned prospective oracle matrix (for
  example an `Xv2-*` namespace) in a **future separate PR**, with its own design,
  tests and acceptance criteria.
- The historical `X01–X13` row remains `BLOCKED` unless the maintainer separately
  authorizes a documented, scoped release exception; no agent-drafted new `X` IDs
  appear in PR 14G.

### 1.3 What the agent will do with each answer

| Maintainer selects | Agent action (mechanical, no reinterpretation) |
|---|---|
| X-A | record the supplied table verbatim in a successor dossier, keep CW-041 `BLOCKED`, and open the follow-up mapping work |
| X-B | record the attributed quotation + date + cited evidence, then set the grouped `X01–X13` row to `SUPERSEDED WITH EVIDENCE` (counts move: PASS unchanged, one row leaves `BLOCKED`) |
| X-C | record the decision, keep CW-041 `BLOCKED`, and note the future versioned-PR obligation |
| no answer | keep CW-041 `BLOCKED` and report it as the only unresolved item besides CW-127/CW-087 |

---

## 2. CW-127 — `R-14A-JSON-MEM` (dossier D-18)

### 2.1 Governing historical decision (unchanged, not overwritten)

| Item | Value |
|---|---|
| Risk | `search::typed::json_sort_value` extracted JSON-path occurrences without charging the temporary `Vec<JsonOccurrence>` (and owned payloads) to `SlotMemoryScope` / cumulative `BatchMemoryBytes` |
| Historical decision | `REQUIRE SEPARATE CORRECTION` |
| Literal instruction | "proceed with option 2" |
| Decision date (UTC) | 2026-10-24 |
| Decision maker | repository maintainer (named signature still required at signoff) |
| Accepted bounds | **NONE** — the risk was not accepted |
| Record | `docs/pr-artifacts/pr-14c/resource-risk-disposition.md` §5 |
| Current state | `BLOCKED`; PR 14E and PR 14G never reword or soften this decision |

### 2.2 Corrective implementation merged

| Item | Value |
|---|---|
| Design | `docs/pr-artifacts/pr-14d/design-and-ownership.md` |
| Implementation commit | `d0e1bbbd841feff6615d7824dd3261a2418511f7` |
| Admission-order fixup (SR-14D-01) | `3f82284` — "admit JSON sort winner memory before cloning" |
| Evidence commits | `9f9371c`, `635c7f4` |
| PR / merge | PR #64, merge `6d18ebed4c2a8c7d73ca9e5078019d50546cb675` |
| Reviewed/final head | `635c7f4a89c5e2e9478da23c2a533e8dc1f80e09` |
| Final-head CI at that time | `rust`, `msrv`, `rustfs` all `completed/success` |

Corrected behavior (source-verified at `dc506f6`): occurrence vectors and owned
path/member/node payloads are preflighted and charged before retention; losers are
compared as borrowed `&JsonNode` values; the winner is materialized exactly once
after `JsonSortBuffer::Winner` admission; the occurrence reservation stays alive
until buffer drop; typed errors and cancellation cleanup are preserved; public API,
cursor and format contracts are unchanged.

### 2.3 Measured characterization (B20/B21, same probe/host/profile)

| Occurrences | Logical boundary **pre-fix** | Logical boundary **post-fix** | Tracked peak (exact) pre → post | Tracked peak (one-under) pre → post | Cancelled pre → post |
|---:|---:|---:|---|---|---|
| 1 | 112 B | **387 B** | 33,675 → 33,547 B | 33,104 → 33,547 B | 7,397 → 7,397 B |
| 128 | 112 B | **45,726 B** | 110,392 → 110,392 B | 41,233 → 110,392 B | 7,397 → 7,397 B |
| 4,096 | 112 B | **1,462,302 B** | 2,518,968 → 2,518,968 B | 303,121 → 2,518,968 B | 7,397 → 7,397 B |

Material findings:

- the logical threshold now grows with occurrence demand (≈3,779× from 1 to 4,096
  occurrences) instead of a constant `112 B`;
- one-under budgets still reject with typed
  `BudgetExceeded(BatchMemoryBytes)`, and their tracked window no longer exceeds
  the exact-limit window at these counts;
- cancellation remains typed at `7,397 B` with no partial success;
- the tracked peak **remains larger** than the logical threshold. A logical
  reservation ledger is not a physical allocator bound, and the SR-14D-01 fixup
  targets admission ordering, not allocator-peak reduction.

### 2.4 Limits that must accompany any acceptance

| Limit | Statement |
|---|---|
| Measurement class | test-only tracking `#[global_allocator]` inside explicit child-process windows — **not** RSS, **not** a global allocator cap, **not** a physical-memory upper bound |
| Charged vs uncharged | occurrence vectors, owned path/member/node payloads and the winner buffer are charged; **one decoded `JsonOccurrence` and the legacy walker path/stack remain bounded, uncharged pre-admission transients** |
| Structural bounds | `MAX_JSON_PATH_DEPTH` 128, `MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT` 65,536, `MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT` 8,000,000, `MAX_JSON_PATH_MEMBER_BYTES` 65,535, `MAX_JSON_PATH_SECTION_BYTES` 256 MiB |
| Meter scope | `BatchMemoryBytes` is a reservation ledger for covered allocations; a budget-sufficient workload can still exceed the logical figure through allocator overhead and the bounded decode transient |
| Environment | one host/profile (WSL2, debug profile); absolute bytes are indicative, the threshold-growth and typed-rejection relations are the material findings |

### 2.5 Two mutually exclusive outcomes for the maintainer

**Outcome 127-ACCEPT — `ACCEPT RESIDUAL RISK FOR PR14 ONLY`.**

Acceptance must be dated, named, scope-limited to PR 14, and must state the
mitigations and the limits above. A decision record must contain at minimum:

1. the literal decision text (`ACCEPT RESIDUAL RISK FOR PR14 ONLY`);
2. decision date (UTC) and decision maker;
3. explicit acknowledgement that the meter is a logical reservation ledger, not
   RSS or a physical bound, and that one decoded `JsonOccurrence` plus the legacy
   walker stack remain uncharged bounded transients;
4. explicit acknowledgement of the post-fix logical thresholds
   (387 / 45,726 / 1,462,302 B), tracked peaks (33,547 / 110,392 / 2,518,968 B)
   and the cancellation figure (7,397 B);
5. the operational mitigations relied on (for example: bounded structural
   constants above, `BatchMemoryBytes` policy sizing, per-batch limits,
   monitoring/telemetry of budget rejections);
6. the acceptance scope (PR 14 only; not a general allocation-safety guarantee,
   not a v0.1 release authorization).

**Outcome 127-REJECT — `REJECT / REQUIRE MORE CORRECTION`.**

Keeps CW-127 `BLOCKED`, requires a new corrective design and executed evidence,
and blocks CW-087 until re-adjudicated. No accepted bound exists meanwhile.

| Maintainer selects | Agent action |
|---|---|
| 127-ACCEPT with the six elements above | record the decision as an attributed quotation with date/scope, close CW-127 (`PASS` on that dated acceptance only) |
| 127-REJECT | record the rejection, keep CW-127 `BLOCKED`, do not alter the historical decision record |
| no answer | keep CW-127 `BLOCKED` and report it as unresolved |

No agent may supply any of these elements on the maintainer's behalf, and CI
success alone is explicitly **not** sufficient to close this row.

---

## 3. Single consolidated request

For execution efficiency, the maintainer is asked **one** question covering both
items (the agent has completed all preparatory work):

> 1. For CW-041 (`X01–X13`), which option do you select: **X-A** (supply the
>    authoritative per-ID definitions), **X-B** (approve family-level supersession
>    by the executed local/FakeObjectStore/real-RustFS evidence, `SUPERSEDED WITH
>    EVIDENCE`), or **X-C** (commission a new versioned matrix in a future PR, row
>    stays `BLOCKED`)?
> 2. For CW-127 (`R-14A-JSON-MEM`), do you **ACCEPT RESIDUAL RISK FOR PR14 ONLY**
>    or **REJECT / REQUIRE MORE CORRECTION**? If accepting, please include the six
>    elements in §2.5.

**Current record of answers:** none received during PR 14G execution. Both rows
remain `BLOCKED`; no signature, date or approval is fabricated here.

## 4. Provenance of this packet

- Facts above are reproduced from the immutable predecessor artefacts
  (`pr-14c/resource-risk-disposition.md`,
  `pr-14d/design-and-ownership.md`, `pr-14d/resource-characterization.md`,
  `pr-14e/blocked-row-dossiers.md`, `pr-14e/resource-risk-reconciliation.md`) and
  re-verified against the current source tree.
- No prior decision file was edited.
- This document is additive evidence only; it changes no test, code or format.
