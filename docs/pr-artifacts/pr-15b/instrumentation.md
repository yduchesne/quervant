# PR 15B diagnostic counter instrumentation

## Design result

The approved public contracts expose no `Diagnostics` API. Adding one, a new
Cargo feature, a TLS/global hook or a private execution-signature change is
explicitly outside the PR 15B authorization (X18). The implementation therefore
uses a **test-only, compile-out module**:

- File: `crates/quervant-core/src/search/diagnostics.rs`
- Declaration: `crates/quervant-core/src/search/mod.rs:35-36`
  (`#[cfg(test)] mod diagnostics;`)

In a normal `cargo build`/`cargo bench` compile of the library this module is
empty: there is no public symbol, no runtime branch, no global mutable state and
no additional memory or control-flow work. The benchmark target cannot access
it; counters are validated only by inline unit tests, exactly as the plan
requires.

## Field-by-field status

| Requested field | Status | Authoritative event / evidence |
|---|---|---|
| `segments_visited` | **NOT INSTRUMENTED** | The unified executor does not expose a per-segment visit count for mixed execution. `TypedScanDiagnostics` exists for the separate typed searcher, not for this path. Threading a counter would change private call signatures (X18). |
| `candidates_examined` | **NOT INSTRUMENTED** | No existing authoritative candidate-tested event is exposed outside the private executor loops. |
| `documents_decoded` | **NOT INSTRUMENTED** | Stored-record decode count is not exposed by the projection path; adding one requires private signature changes. |
| `selected_hits` | **MEASURED** | `diagnostics.rs:64`: exact length of the authoritative `UnifiedResponse.hits` vector returned by the real executor. |
| `projection_fields` | **MEASURED** | `diagnostics.rs:65-68`: exact sum of `ProjectedHit.fields.len()` for the authoritative response hits; every `(name, FieldValues)` entry is one emitted field event. |
| `sort_comparisons` | **NOT INSTRUMENTED** | The top-K comparator does not expose invocation counts; instrumenting it would require a hot-loop signature/state change. |
| `group_updates` | **NOT INSTRUMENTED** | The aggregation engine's internal group-update count is not returned by the public response. |
| `logical_memory_peak_bytes` | **NOT INSTRUMENTED** | The standalone unified path's local projection/batch logical meters are not returned. No physical RSS/memory cap is inferred from them. |

`None` is the sole representation of `NOT INSTRUMENTED`. It is never reported as
zero and never converted into an estimate. The plan's illustrative struct used
`u64` fields; `Option<u64>` is required to satisfy the normative rule "record the
field as NOT INSTRUMENTED, not zero". The measured fields remain exact integers.

## Mandatory minimum

The mandatory minimum (`selected_hits` and `projection_fields`) is met using the
authoritative production response events. The remaining requested counters are
transparently `NOT INSTRUMENTED` with the X18 blocker above. No counter can
influence control flow, memory charging, cancellation or result values.

## Adversarial unit tests

All tests execute the real `UnifiedSearcher::search` over an eight-row golden
fixture with two immutable segments:

| Test | Witness |
|---|---|
| `counter_absent_query_selects_zero` | absent query selects `0`, projects `0` |
| `counter_match_all_top_k_three_selects_exactly_three` | `total_hits=8`, selected `3`, source projection `3 × 6 = 18` field events |
| `counter_fields_projection_emits_exactly_four_events` | two hits × two requested stored fields = `4` events |
| `counter_repeated_query_is_deterministic` | repeated identical query returns identical counters |
| `counter_cancelled_query_is_not_a_completed_selection` | pre-cancelled query returns `Err(Cancelled)`; no selection is claimed |
| `counter_invalid_query_is_not_a_completed_selection` | invalid field returns a typed query error; no selection is claimed |
| `unavailable_counters_are_not_instrumented` | every unavailable field is `None`, never `0` |

B-T12 additionally asserts at source level that the module is declared behind
`#[cfg(test)]` and does not export a public `WorkCounters` symbol.

## Explicit limitation

A complete stage-counter architecture (candidate visits, decoded documents,
comparisons, memory peaks) requires maintainer-approved production design work.
PR 15B treats that as a scoped limitation, not a silent success. The mandatory
minimum is satisfied; the broader counter surface is not claimed.

## Profiling-amendment clarification

The later profiling amendment obtained usable `perf` and `heaptrack` data (see
`profile-attempts.md`). That does **not** convert any `NOT INSTRUMENTED` counter
into a measured stage counter:

- `perf` supplies sampled CPU stacks, not exact per-stage event counts. It
  cannot supply `candidates_examined`, `documents_decoded`, `sort_comparisons`,
  `group_updates` or `segments_visited` as exact counters.
- `heaptrack` supplies allocation counts, cumulative allocated bytes and peak
  live heap. It does not expose the executor's logical memory meter and cannot
  supply `logical_memory_peak_bytes` as the requested logical counter.
- The measured fields `selected_hits` and `projection_fields` remain the exact
  response-level counts from the test-only module. The profiler evidence is
  external attribution, not a replacement for those counters.
- No new public diagnostics API, feature, TLS/global state or hot-loop counter
  was introduced by the profiling amendment.
