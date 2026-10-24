# PR 14C — `R-14A-JSON-MEM` resource-risk disposition

**Status: `REQUIRE SEPARATE CORRECTION` — DECISION RECORDED.** The human
maintainer selected Option 2 on 2026-10-24 (literal instruction: "proceed with
option 2"). Under AD-14C-06/E18 this means:

- PR 14C delivers truthful **INCOMPLETE / BLOCKED** acceptance documents;
- PR 14 is **not** DONE and is **not** accepted;
- a separately designed and approved correction must land before PR 14
  acceptance can resume;
- the coding agent must not implement that correction in PR 14C.

Owner of the corrective work: to be assigned in the follow-up PR. Named
maintainer signature is still required at merge signoff (C-T15/C-T16).
Prepared by the coding agent on 2026-10-24 against baseline
`376023b53b557a30367097f29a41328c798188d4`.

## 1. Risk statement

`search::typed::json_sort_value` (`crates/quervant-core/src/search/typed.rs:2465`)
evaluates an indexed JSON-path sort field by calling:

```rust
let (occurrences, _bytes) = json.occurrences(field_id, doc_id, guard, None)?;
// crates/quervant-core/src/search/typed.rs:2478
```

The `None` memory sink means the temporary `Vec<JsonOccurrence>` and its owned
contents are **not charged** to `SlotMemoryScope` / cumulative `BatchMemoryBytes`
and are **not released/accounted incrementally**. The path is shared by the
public pinned batch path: PR 14A Correction 02 made `search/unified.rs` call the
same `pub(crate) json_sort_value` from the per-hit `collect_mixed` loop.

By contrast, the typed predicate call sites already pass a memory sink
(`crates/quervant-core/src/search/typed.rs:1268,1293,1322,1347`).

Existing bounds (`crates/quervant-core/src/segment/json_paths.rs:25–33`):

| Limit | Value |
|---|---|
| `MAX_JSON_PATH_DEPTH` | 128 |
| `MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT` | 65,536 |
| `MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT` | 8,000,000 |
| `MAX_JSON_PATH_MEMBER_BYTES` | 65,535 |
| `MAX_JSON_PATH_SECTION_BYTES` | 256 MiB |

## 2. Measurements executed in P1 (reproduction of PR 14B B20/B21)

Command:

```sh
cargo test -p quervant-core --all-features --test pr14b_json_memory \
  -- --nocapture --test-threads=1
```

Result: 1 passed, 1 ignored (child entrypoint), baseline `376023b`.

| Occurrences | Logical `BatchMemoryBytes` boundary | Tracked peak, exact limit | Tracked peak, one-under (typed failure) | Tracked peak, cancellation |
|---:|---:|---:|---:|---:|
| 1 | 112 B | 33,675 B | 33,104 B | 7,397 B |
| 128 | 112 B | 110,392 B | 41,233 B | 7,397 B |
| 4,096 | 112 B | **2,518,968 B** (≈2.4 MiB) | 303,121 B | 7,397 B |

These reproduce the PR 14B figures byte-for-byte. Reported as **allocator/
process-heap observations inside explicit child-process measurement windows**,
not RSS, not allocator capacity, and not a physical memory cap. Rust 1.98.1,
debug profile, WSL2 Linux host; absolute values are indicative, the scaling
relation and the logical/heap divergence are the material findings.

## 3. Interpretive limits (from the PR #61 independent review)

- **Q1:** the tracking allocator records allocation activity within explicit
  windows; it is not a measurement of process RSS, allocator capacity, a global
  maximum allocation, or a hard upper bound. The data show a **missing
  transient-allocation charge**, not proof of unbounded memory.
- **Q2:** `R-14A-JSON-MEM` remains OPEN even though 14B tests and real-RustFS
  fault suites passed. Test/evidence qualification does not accept the risk.
- Occurrence growth is **linear** and bounded by the JSON limits above, so a
  near-limit document can allocate materially more transient heap than the
  configured `BatchMemoryBytes` suggests (≈22,500× at 4,096 occurrences).
- A one-under budget failure still incurs the transient allocation before the
  typed `BudgetExceeded{BatchMemoryBytes}` is produced; changing the logical
  budget does not bound the temporary allocation.
- Cancellation is typed and avoids the occurrence walk on the measured path.

## 4. Options presented to the human decision maker

The agent must not select among these.

### Option 1 — `ACCEPT WITH EXPLICIT LIMITATIONS`

Accept that transient JSON-sort occurrence memory is bounded by the JSON limits
but is not charged to `BatchMemoryBytes`, and document operational limits.

- Consequence: PR 14 can be accepted if **all other** gates pass, with a
  recorded, scoped limitation; the divergence is a known v0.1 characteristic.
- Requires the human to state: affected paths (JSON-path sort in typed and
  unified/pinned batch), the numeric bounds relied upon, that transient
  occurrences are **not** charged to the logical batch meter, that
  `BatchMemoryBytes` is **not** a physical memory cap, operational mitigations
  (for example per-document occurrence limits, monitoring, admission control),
  decision scope (PR 14 acceptance vs v0.1 release) and the date.
- Must **not** be described as "RSS-bounded", "physical cap", "resolved", or
  "measured pass".

### Option 2 — `REQUIRE SEPARATE CORRECTION`

Authorize a separately designed, reviewed fix shared by the typed and unified
sort paths. Minimum content of that future correction:

- pass a real memory sink to `JsonAccess::occurrences` at
  `typed.rs:2478` (or an equivalent bounded/streaming accessor);
- charge occurrence memory to the per-slot/cumulative scope with the same
  exact/one-under semantics as other meters;
- keep existing JSON occurrence/depth/member limits unchanged;
- add exact-limit, one-over, sibling-rollback and cancellation tests plus a
  re-measured B20/B21 characterization;
- no format, manifest, API or distributed change unless separately approved.

- Consequence: PR 14C must deliver truthful **INCOMPLETE/BLOCKED** documents and
  must not mark PR 14 DONE. Acceptance resumes in a later PR.

### Option 3 — `REJECT / BLOCK`

Reject the release qualification until the risk is fixed by Option 2 or an
equivalent approved design.

- Consequence: same documentary outcome as Option 2, with an explicit release
  block rather than a scheduled correction.

## 5. Human decision record (recorded)

```
Decision:            REQUIRE SEPARATE CORRECTION
Literal instruction: "proceed with option 2"
Decision maker:      repository maintainer (human session operator);
                     named signature required at merge signoff
Date (UTC):          2026-10-24
Scope:               PR 14 acceptance (blocked until corrected)
Accepted bounds:     NONE — the risk is not accepted
Known limitation:    transient JSON-sort occurrence memory is not charged to
                     BatchMemoryBytes; the logical meter is not a physical
                     memory cap; tracked peaks reach 2,518,968 B at 4,096
                     occurrences against a 112 B logical boundary
Operational mitigation: none recorded as sufficient; correction required
Corrective work:     separate design-approved PR, minimum scope in §4 Option 2
                     (real memory sink at typed.rs:2478, charging, exact/one-over
                     and cancellation tests, re-measured B20/B21)
Release implication: PR 14 stays BLOCKED; PR 15D cannot release v0.1 while
                     this gate is open
```

The decision is `REQUIRE SEPARATE CORRECTION`; it is **not** an acceptance of
the residual risk. No agent may reword this record into
`ACCEPT WITH EXPLICIT LIMITATIONS`.

## 6. Current gate state

| Gate | State |
|---|---|
| Risk identified and measured | DONE (B20/B21 reproduced in P1) |
| Human disposition | **RECORDED — `REQUIRE SEPARATE CORRECTION`** |
| Operational mitigations recorded | NONE — not accepted |
| Corrective work authorized | YES (scope in §4 Option 2); not implemented |
| PR 14 acceptance | **BLOCKED / NOT ACCEPTED** |
| PR 14 DONE | **NO** |
| v0.1 release | **NOT CLAIMED** |
