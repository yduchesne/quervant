# PR 14G — maintainer decisions (CW-041 and CW-127)

**Status: `DECIDED (attributed transcription) — CW-041 SUPERSEDED WITH EVIDENCE,
CW-127 ACCEPTED FOR PR 14 ONLY`.** The maintainer recorded both decisions in a
comment on PR #70. This document transcribes that authorization verbatim and
records its bounded scope. It is **not** PR 14G merge authorization, **not** PR 14
acceptance and **not** v0.1 release authorization.

| CW | Historical row | State after decision | Authority |
|---|---|---|---|
| 041 | §4.6 `X01–X13` per-ID oracle matrix | **SUPERSEDED WITH EVIDENCE** (option X-B) | maintainer comment on PR #70 |
| 127 | §8 item 7 `R-14A-JSON-MEM` JSON temporary memory | **PASS** (bounded PR 14 risk acceptance) | maintainer comment on PR #70 |
| 087 | §6 `14G final gates, CI, docs` (see `acceptance-crosswalk.md`) | **BLOCKED** | not decided by this authorization |

## 0. Recorded authorization (verbatim source)

| Item | Value |
|---|---|
| Source | PR #70 maintainer comment, `https://github.com/yduchesne/quervant/pull/70#issuecomment-6458408816` |
| Comment id | `6458408816` |
| Author | `yduchesne` (`author_association: OWNER`) |
| Comment created (UTC) | `2026-10-28T01:43:43Z` |
| Decision date stated by the maintainer | `2026-10-27` |
| Title | "Maintainer decision authorization — PR 14G CW-041 and CW-127 (2026-10-27)" |
| Scope | PR 14G evidence transcription; **not** PR merge authorization and **not** v0.1 release authorization |

Authorized text transcribed exactly (quotation; block quotes are the maintainer's
own words, with only the list bullets re-indented for Markdown):

> The maintainer explicitly approved **both recommended dispositions** in the planning
> discussion. This comment records that authorization; it is **not** PR merge
> authorization or v0.1 release authorization.
>
> **CW-041 — approve option X-B (family-level supersession).** The undefined
> historical grouped `X01–X13` requirement is **SUPERSEDED WITH EVIDENCE** by the
> executed local, FakeObjectStore, and real-RustFS oracle families described in
> `docs/pr-artifacts/pr-14g/maintainer-decisions.md` and preceding PR14D/14F
> evidence. Preserve the literal historical grouped row and distinguish this
> family-level supersession from a false claim that 13 individually specified
> tests passed. Do not invent definitions.
>
> **CW-127 — approve ACCEPT RESIDUAL RISK FOR PR14 ONLY**, following merged PR14D
> JSON-sort reservation/admission correction. This is a bounded **PR 14
> acceptance** decision only, **not** a physical-memory safety guarantee, a
> blanket production risk waiver, or approval to release v0.1. Explicit
> acknowledged limitations:
>
> - `BatchMemoryBytes` is a logical reservation ledger, **not RSS or an actual
>   physical allocator cap**.
> - One decoded `JsonOccurrence` and the legacy walker/path stack remain
>   structurally bounded, **uncharged** pre-admission transients.
> - Post-fix logical thresholds at 1/128/4096 occurrences: **387 / 45,726 /
>   1,462,302 bytes**. Test-only tracked allocator-window peaks: **33,547 /
>   110,392 / 2,518,968 bytes**. Cancellation: **7,397 bytes**. These test-only
>   WSL2/debug figures are not a universal memory bound.
> - Structural guards include JSON-path depth 128, occurrences per document
>   65,536, occurrences per segment 8,000,000, member bytes 65,535, section
>   bytes 256 MiB.
> - Operational mitigations relied on: retain configured `BatchMemoryBytes`
>   policy and per-batch budget limits, preserve typed budget rejection and
>   cancellation, and monitor budget failures and memory behavior. Those
>   mitigations are acceptance rationale, not claims that operational telemetry
>   was newly implemented by PR14G.
>
> Coding agent: transcribe these authorized decisions, source/decision date, and
> bounded rationale into the PR14G additive records; update CW-041 to SUPERSEDED
> WITH EVIDENCE and CW-127 to PASS, preserving 127 distinct row identities and
> immutable historical files. CW-087 remains BLOCKED until current-head CI,
> independent acceptance review, and explicit maintainer final PR14/merge
> authorization. Revalidate derived counts (expected **112 PASS / 12 SUPERSEDED /
> 2 N/A / 1 BLOCKED**); do not self-approve CW-087, merge, start PR15, or release
> v0.1. After evidence commits, verify CI at the **new** exact PR head. For
> unforeseen conditions, HARD STOP under the approved plan.

**Transcription compliance.** The agent did not select an option, sign, date or
widen the scope: the text above is the maintainer's authorization, attributed to
its immutable source, and the derived row states match the authorized expectations
exactly (`112 / 12 / 2 / 1`, sum `127`).

---

## 1. CW-041 — historical `X01–X13` (dossier D-16)

### 1.0 Decision applied

| Item | Value |
|---|---|
| Selected option | **X-B — documented family-level supersession** |
| Date | `2026-10-27` (as stated by the maintainer) |
| Authority | PR #70 comment `6458408816` (§0) |
| Effect | grouped historical row `PR14C:§4.6:X01–X13` set to **SUPERSEDED WITH EVIDENCE** |
| Not claimed | no per-ID `X01…X13` test exists or "passed"; no definitions were invented; the literal grouped row and its ID are preserved |
| Evidence accepted | executed local, `FakeObjectStore` and real-RustFS oracle families (`phase-a-zero-get.md`, `phase-b-physical-identity.md`, PR 14D/14E/14F verticals) |

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

### 1.2 Three mutually exclusive options (historical pre-decision record)

> The maintainer selected **X-B** on 2026-10-27 (see §0). The options below are
> retained verbatim as the pre-decision dossier and are not a live choice.

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

### 1.3 Applied action (X-B)

| Step | Executed |
|---|---|
| Record attributed quotation, decision date and cited evidence | yes (§0) |
| Set the grouped `PR14C:§4.6:X01–X13` row to `SUPERSEDED WITH EVIDENCE` | yes (`acceptance-crosswalk.md`) |
| Preserve the literal grouped row, its ID and the row unit | yes (no row added, split or renumbered; still 127 rows) |
| Avoid claiming per-ID tests | yes — the crosswalk states family-level supersession only |
| Derived counts | `112 PASS / 12 SUPERSEDED / 2 N/A / 1 BLOCKED` |

---

## 2. CW-127 — `R-14A-JSON-MEM` (dossier D-18)

### 2.0 Decision applied

| Item | Value |
|---|---|
| Selected outcome | **ACCEPT RESIDUAL RISK FOR PR14 ONLY** |
| Date | `2026-10-27` (as stated by the maintainer) |
| Authority | PR #70 comment `6458408816` (§0) |
| Effect | `PR14C:§8:7. JSON temp memory` set to **PASS** on that dated, scoped acceptance |
| Scope limit | PR 14 acceptance only — not a physical-memory guarantee, not a global risk waiver, not a v0.1 release authorization |
| Historical decision preserved | `REQUIRE SEPARATE CORRECTION` (2026-10-24) remains in `pr-14c/resource-risk-disposition.md`; it is not rewritten |
| Conditions transcribed | corrected charging, logical thresholds, allocator-window limitations, uncharged bounded transients, structural guards, operational mitigations (§0, §2.3, §2.4) |

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

### 2.5 Two mutually exclusive outcomes (historical pre-decision record)

> The maintainer selected **ACCEPT RESIDUAL RISK FOR PR14 ONLY** on 2026-10-27
> (see §0). The outcomes below are retained as the pre-decision dossier.

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

| Maintainer selected | Agent action (executed) |
|---|---|
| **127-ACCEPT** with the six elements | recorded the attributed quotation, decision date and bounded scope (§0); CW-127 set to `PASS` on that dated acceptance only; historical decision file untouched |
| 127-REJECT | not selected |
| no answer | not applicable — an authorization was supplied |

No agent may supply any of these elements on the maintainer's behalf, and CI
success alone is explicitly **not** sufficient to close this row.

---

## 3. Consolidated request (answered)

The single combined request was:

> 1. For CW-041 (`X01–X13`), which option do you select: **X-A** (supply the
>    authoritative per-ID definitions), **X-B** (approve family-level supersession
>    by the executed local/FakeObjectStore/real-RustFS evidence, `SUPERSEDED WITH
>    EVIDENCE`), or **X-C** (commission a new versioned matrix in a future PR, row
>    stays `BLOCKED`)?
> 2. For CW-127 (`R-14A-JSON-MEM`), do you **ACCEPT RESIDUAL RISK FOR PR14 ONLY**
>    or **REJECT / REQUIRE MORE CORRECTION**? If accepting, please include the six
>    elements in §2.5.

**Record of answers:** both answered by the maintainer in PR #70 comment
`6458408816` (2026-10-28T01:43:43Z, decision date `2026-10-27`): CW-041 → **X-B**,
CW-127 → **ACCEPT RESIDUAL RISK FOR PR14 ONLY**. The exact text is transcribed in
§0. No agent-authored signature, date or approval exists in this repository.

## 3a. Remaining gate (not decided here)

`CW-087` (`14G final gates, CI, docs`) remains **BLOCKED** and is explicitly
excluded from this authorization: it requires current-head CI, independent
acceptance review and explicit maintainer PR 14/merge authorization. The agent does
not self-approve it, does not merge PR #70, does not start PR 15 and does not
release v0.1.

## 4. Provenance of this packet

- Facts above are reproduced from the immutable predecessor artefacts
  (`pr-14c/resource-risk-disposition.md`,
  `pr-14d/design-and-ownership.md`, `pr-14d/resource-characterization.md`,
  `pr-14e/blocked-row-dossiers.md`, `pr-14e/resource-risk-reconciliation.md`) and
  re-verified against the current source tree.
- No prior decision file was edited.
- This document is additive evidence only; it changes no test, code or format.
