# PR 4 — V4: deterministic work-unit accounting and cancellation design

**Gate:** V4 (amendment `PR04_ANALYZER_PARAMETER_APPROVAL_AMENDMENT.md`).
**Status:** design recorded before implementing the pull-based analyzer iterator.
**Scope:** synchronous, single-threaded tokenization. No Tokio, no async executor, no query
result streaming.

## 1. Deterministic work accounting

Every analysis invocation carries a `WorkBudget` (default `8_000_000` units, itself bounded by
a hard ceiling). A unit is charged only in deterministic, input-proportional places:

| Operation | Charge | Rationale |
|---|---|---|
| Scanning one input value for tokenization | `1` unit per Unicode scalar value (`chars().count()`) | Bounds tokenizer cost; independent of regex/backtracking because no regex is executed. |
| Emitting one raw token | `1` unit | Bounds token count overhead. |
| Applying one token filter to one token | `1` unit + `term.len()` bytes for length-changing filters (normalize, case-fold, ASCII-fold) | Bounds total character work; `term.len()` is already capped by `max_term_bytes`. |
| Stopword set membership | `1` unit | Bounds stopword lookup work. |
| Stemming one token | `1` unit + `term.len()` bytes | Bounds Snowball work. |

All charges use `u64::checked_add`; exceeding the budget returns
`AnalysisError::WorkBudgetExceeded`. No saturating arithmetic.

Work accounting is **per value** and does not depend on thread count or global state, so
identical input + limits + canceller state yields identical results (tests A4-09, A4-11,
A4-21).

## 2. Cancellation

- Public trait: `Cancellation { fn is_cancelled(&self) -> bool; }`.
- Provided implementations: `NeverCancel` (always `false`) and `CancellationFlag`
  (`AtomicBool`, thread-safe and lock-free).
- A cancellation poll occurs only when consumed work crosses a deterministic boundary:
  every `CANCELLATION_POLL_INTERVAL = 1024` charged work units, and at every value boundary.
  This gives a hard upper bound of 1024 work units between polls.
- On cancellation the current call returns `AnalysisError::Cancelled` and **emits no token**
  for the in-flight item. Already-yielded tokens from earlier values are valid and complete;
  the stream is never presented as complete success (spelling out the "no partial success"
  contract from the plan).
- Tests use a deterministic `CancelAfterChecks { remaining: Cell<u32> }` canceller (returns
  `false` a fixed number of polls, then `true`) plus a start-time `CancellationFlag`, so
  cancellation is reproducible rather than timing-dependent.

## 3. Interaction with other limits

Order of enforcement per value:

1. `max_input_bytes` (checked before any allocation proportional to input).
2. token count budget (`max_tokens`, across the whole call).
3. `max_term_bytes` (checked before storing token text; oversized transformed terms are a
   typed error, not truncation).
4. work budget and cancellation polling during tokenization/filtering.

All limits are "exact at the limit succeeds, one over fails" (A4-08). Limits can be lowered
by configuration but cannot exceed the hard ceilings without a separately approved extension
(T07).

## 4. Consequence for the cursor API

The primary API is a fallible pull cursor, `AnalysisCursor::next_token()`. It materializes at
most one source value's raw tokens at a time into a bounded queue; memory is therefore
`O(tokens remaining in the current value)` and never `O(document)`. A convenience
`collect_tokens` returns `Vec<Token>` under the same budgets.
