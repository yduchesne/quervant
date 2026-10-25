# PR 14D — resource characterization

**No RSS or physical-cap claim is made.** All values are logical reservations or
test-only allocator-window observations.

## 1. B20/B21 pre-fix baseline (`2cb91be`)

| Occurrences | Logical `BatchMemoryBytes` | Tracked peak (exact) | Tracked peak (one-under) | Tracked peak (cancelled) |
|---:|---:|---:|---:|---:|
| 1 | 112 | 33,675 | 33,104 | 7,397 |
| 128 | 112 | 110,392 | 41,233 | 7,397 |
| 4,096 | 112 | 2,518,968 | 303,121 | 7,397 |

The logical meter was occurrence-independent because the occurrence vector and
owned payloads were not charged; constrained budgets could not prevent the
transient peak.

## 2. B20/B21 post-fix (`d0e1bbb`)

Same child-process probe, same labels, same machine/profile:

| Occurrences | Logical `BatchMemoryBytes` | Tracked peak (exact) | Tracked peak (one-under) | Tracked peak (cancelled) |
|---:|---:|---:|---:|---:|
| 1 | **387** | 33,547 | 33,547 | 7,397 |
| 128 | **45,726** | 110,392 | 110,392 | 7,397 |
| 4,096 | **1,462,302** | 2,518,968 | 2,518,968 | 7,397 |

Observations:

- The charged threshold now **grows with occurrence demand** (387 → 45,726 →
  1,462,302), i.e. ~3,779× from 1 to 4,096 occurrences, instead of the old
  constant 112.
- One-under still rejects with the typed
  `BudgetExceeded(BatchMemoryBytes)` and its tracked window does not exceed the
  exact-limit window at these counts.
- Cancellation remains typed at 7,397 B and does not retain a partial success.
- The tracked peak is still larger than the **logical** threshold because a
  logical reservation ledger is not a physical allocator bound: allocator
  overhead, the bounded per-occurrence decode transient, and non-JSON batch
  structures are outside the charged occurrence/winner buffers. This is expected
  and is not presented as a hard RSS cap.

## 3. What is charged (and what is not)

| Allocation | Charged before growth? | Notes |
|---|---|---|
| Occurrence vector capacity | YES | `push_occurrence`, delta reconciled to actual capacity |
| Path component array (owned clone) | YES (before retain) | `retained_owned_bytes` |
| Member-string payloads | YES (before retain) | counted per `Member` |
| Node string payload | YES (before retain) | counted per `String` node |
| Winning scalar string | YES (before clone/replace) | `Winner` ledger, released before heap charge |
| One decoded `JsonOccurrence` (indexed) | NO — bounded transient | exists from `next_occurrence` until its own admission; bounded by JSON depth/member/section limits |
| Walker path/stack (legacy) | NO — bounded transient | one reusable path + depth-bounded frame stack; pre-existing segment limits |
| Candidate heap / retained tuple | YES — existing accounting | unchanged; charged after sort |

## 4. Interpretation and limits

- The measured divergence between logical and tracked heap is **not** evidence of
  unbounded memory: occurrence growth is bounded by
  `MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT` (65,536),
  `MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT` (8,000,000), depth 128, member 65,535 B
  and section 256 MiB.
- The logical meter is a **reservation ledger for covered allocations**, not a
  process memory cap. A budget-sufficient workload can still use allocator
  overhead and one bounded decode transient beyond the logical figure.
- Results are from one host/profile; absolute bytes are indicative. The
  threshold-growth and typed-rejection relationships are the material findings.
- No new public meter, knob, or physical-memory guarantee was introduced.
