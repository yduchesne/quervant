# PR 10 Amendment 02 — Adversarial Review (pre-implementation)

**Date:** 2026-10-14
**Branch:** `dev/temporal-retrieval`
**Baseline HEAD:** `a132325fef9df49b05bff7f0ed0bb086fcf72ee5`
**Merge-base against `main`:** `2ecbbe2bb3ca1b9fe0e33827c94d03df0a6874a7`
**Tree:** clean at start.

## Defect (acceptance finding A1)

The exact aggregation engine bounds **retained** state through
`AggregationEngine.state_bytes`/`reserve`, but materializes per-document
temporary vectors and sets outside that budget:

- `crates/quervant-core/src/search/typed.rs::visit_aggregate` clones metric
  values into `owned_metrics`, frequency values into `frequency_values`, and
  group values into `group_lists`, and requests owned decoded `FieldValues`
  from `ColumnAccess::value` before any admission check.
- `crates/quervant-core/src/search/analytics.rs::add_document` builds
  `distinct_frequencies` and `emitted` and clones group values into `components`
  during `expand`, all uncharged.
- `analytics.rs::finish` allocates result groups, frequency sorting vectors and
  re-encoded result keys while retained state still exists.

An aggregation can therefore allocate transient memory beyond
`max_aggregate_state_bytes` without a typed rejection.

## Budget scope

The fix enforces a **conservative logical memory-admission budget** for owned
aggregation allocations introduced by those paths, combined with retained
state under one `limit_bytes`. It is **not** a claim to bound allocator metadata,
`Vec` capacity slack, decoded column buffers outside the listed paths, storage
cache allocations or total process RSS. Over-estimation is allowed; omission of
a listed owned value is not.

## Counterexamples considered

1. **One huge keyword** used as a group field, metric input and frequency field:
   the decoded value, its clone into `group_lists`, its canonical key and its
   `emitted`/frequency copies are each separately live at peak.
2. **Many distinct multi-values** in one group field: Cartesian expansion and
   the `emitted` key set grow together, and canonical dedup bytes are owned while
   the decoded value is still live.
3. **Cartesian expansion** across two/three multi group fields: product bounded
   by `max_group_expansion_per_document` before allocation, plus the `components`
   clone stack.
4. **Repeated metric references** to one field (`SUM`, `AVG`, `MIN`, `MAX`,
   `ExactDistinct`): naive per-metric clones multiply transient memory; the fix
   decodes once and borrows the cached value for every metric reference.
5. **Simultaneous retained/transient peak**: a request whose retained groups fit
   and whose transient staging fits, but whose combined peak exceeds the limit,
   must be rejected.
6. **Arithmetic overflow**: near-`u64::MAX` byte counts must fail with a typed
   error, never wrap or clamp.
7. **Error/cancellation release**: an error during the second group/metric, or
   cancellation during expansion, must leave the transient counter released and
   return no partial response.
8. **Pre-decode allocation**: a decoding seam must expose a trustworthy
   upper bound from column metadata before `ColumnReader::value` allocates. The
   encoded value span plus a bounded per-element term is such a bound, so this is
   **not** a STOP condition.

## Invariant → test mapping

| ID | Invariant | Tests |
|---|---|---|
| A2-I01 | `retained + transient <= limit` at every admitted allocation | A2-T01 |
| A2-I02 | Checked arithmetic; no wrap/clamp | A2-T02 |
| A2-I03 | Every per-document owned clone/encoded key is pre-admitted | A2-T03 |
| A2-I04 | Repeated metrics reuse one decoded field; values exact | A2-T04 |
| A2-I05 | Exact multivalue/frequency dedup; one-over transient set fails | A2-T05 |
| A2-I06 | Cartesian expansion and `emitted` keys bounded | A2-T06 |
| A2-I07 | Retained and transient compete for one shared limit | A2-T07 |
| A2-I08 | Error/cancellation release transient charges | A2-T08 |
| A2-I09 | Finalization cannot exceed the budget | A2-T09 |
| A2-I10 | Result semantics/order/PIT unchanged | A2-T10, existing PR 10 suites |
| A2-I11 | Exact-at-limit and one-over deterministic | A2-T11 |
| A2-I12 | No public API, codec, lexical or snapshot changes | A2-T12, diff audit + workspace/MSRV gates |

## Pre-decode admission seam

`crates/quervant-core/src/segment/column.rs` will gain a **read-only,
`pub(crate)`** accessor returning the encoded value state, span and element count
for one `(field, doc)` without decoding. `ColumnAccess::decoded_value_bound`
converts that to a conservative logical byte bound. This is an internal
admission seam, not a wire-format, public-API or `ColumnReader` behavior change.

## Baseline source locations

| Path | Symbol |
|---|---|
| `search/analytics.rs` | `AggregationEngine::{new,add_document,expand,apply_group,apply_frequency,ensure_global_group,finish}`, `expand_field_values`, `reserve`, `account_group` |
| `search/typed.rs` | `visit_aggregate`, `aggregate_limits` |
| `search/typed_compare.rs` | `ColumnAccess::{open,value}`, `canonical_scalar_bytes` |
| `search/limits.rs` | `SearchLimits::max_aggregate_state_bytes` |
| `segment/column.rs` | `ColumnReader::value` |

## STOP-gate decision

- Branch/baseline/tree verified; implementation matches the plan. **Go.**
- A trustworthy pre-decode bound exists (encoded span + bounded element count). **Go.**
- Retained/transient transfer is implementable with a single ledger and explicit
  per-document release. **Go.**
- Existing `SearchError::ResourceLimit` represents the required errors; no public
  API/error-model change needed. **Go.**

**Decision: GO.**

## Post-implementation outcome

Implemented exactly as planned, with the shared ledger owned by
`AggregationEngine` (`AggregateMemory { limit_bytes, retained_bytes,
transient_bytes }`; `state_bytes` removed). Every listed path is pre-admitted:

- `visit_aggregate` decodes each distinct referenced field once with a
  conservative `decoded_value_bound` admission before `ColumnAccess::value`, then
  borrows the cached value for every metric and frequency reference (no per-metric
  clones).
- Group expansion (`expand_field_values_charged`), the `emitted` key set, the
  recursive `components` stack and the frequency dedup staging are all charged by
  `add_document` against a conservative per-document bound computed before any of
  them is created and released on both success and error.
- `finish` reserves a transient output bound while retained state still exists.
- `column.rs` exposes a read-only `pub(crate) encoded_value_shape` used only for
  admission; `value` behavior is unchanged.

### Residual risks (accepted)

- The budget is a conservative logical bound, not a hard OS heap cap.
- Conservative over-estimation can reject a very large fan-out slightly earlier
  than byte-exact accounting would; this is deterministic and fail-closed.
- The 1M benchmark fixture remains blocked by the PR 9 mutation-state byte
  ceiling (documented nonblocking constraint).

No semantic conflict, unapproved deviation or STOP condition was encountered.
