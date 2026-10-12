# PR 4 review fixup — incremental work accounting and cancellation boundaries

Supersedes the pre-fixup `v4-work-cancellation-budget-design.md` execution model. The approved
limits themselves are unchanged (T07): 1 MiB per source value, 100,000 emitted tokens **per
value**, 4 KiB per term, 8,000,000 work units **per call**.

## Charge model (deterministic, incremental)

| Operation | Charge |
|---|---|
| Whitespace tokenizer scanning one scalar | `1` per scalar (including skipped whitespace) |
| Unicode-word tokenizer advancing to one word | skipped scalars since the previous word + that word's scalars |
| Keyword tokenizer | the whole value's scalar count, once (the value is a single token) |
| Each ordered token filter per token | `1 + term.len()` bytes (`stopword` lookup charges `1`) |
| Regex parse proxy (`prepare_regex`) | `pattern.chars().count()`, before the opaque parser |
| Regex AST walk | `1 + current.len()` per literal/class check |
| Domain UTS #46 / ToUnicode / PSL / skeleton stages | `intermediate.len()` charged after each stage |

All counters use `u64::checked_add` (or saturating conversion from `usize`); exceeding the budget
returns `AnalysisError::WorkBudgetExceeded`. No saturating positions.

## Cancellation boundaries (deterministic)

- `WorkBudget::charge` polls `Cancellation::is_cancelled` whenever consumed work crosses a
  multiple of `CANCELLATION_POLL_INTERVAL = 1024`.
- Explicit checkpoints: cursor construction, each value start, before every token-filter pass,
  and between the domain UTS #46 / ToUnicode / PSL / skeleton stages.
- Because tokenization is now lazy and charges per scanned scalar, a large value with few tokens
  still polls cancellation while scanning rather than after a single large charge.
- **Opaque calls cannot be preempted**: the UTS #46, ToUnicode, PSL lookup and UTS #39 skeleton
  calls are third-party and uninterruptible. They are wrapped by pre/post charges and polls, and
  the 1 MiB per-value input bound is enforced before they run. This is documented, not silently
  assumed away.

> **Amendment 02 update (2026-10-12).**
> * Keyword tokenization now charges **one unit per scalar** instead of one whole-value charge,
>   so cancellation is polled during the scan (A2-T16).
> * `unicode_segmentation::UnicodeWordIndices::next()` is **atomic per UAX #29 segment**: the
>   pinned library API exposes no intra-segment checkpoint. Cancellation is polled before each
>   segment; a single segment scan is bounded by the 1 MiB per-value ceiling. The earlier blanket
>   "poll every 1024 units" claim is therefore scoped to keyword/whitespace per-scalar charging
>   and does not hold inside one word segment.
> See `review-amendment-02-work-boundaries.md` (in `review-amendment-02-report.md`) and A2-T16..21.

## Terminal semantics

`AnalysisCursor::next_token` returns `Err` on terminal failure without producing a partial token.
`collect_tokens` returns `Err` (no partial `Vec` success). A streaming caller must discard any
tokens it already received when a terminal error occurs; the cursor never signals completion
after a terminal error.

## Deterministic proof tests

- `F4-19`: requesting the first token of a 100,000-token value performs ≤8 cancellation polls
  (eager whole-value scanning would perform ~100), proving lazy scan.
- `F4-20`: cancellation at start, mid-scan (crossing the 1024 poll interval) and after a token.
- `F4-21`: a 3-work-unit input passes at exactly `max_work_units = 3` and fails typed at `2`.
- `F4-16`/`F4-17`: two values each exactly at the per-value token cap pass; one value at cap+1
  fails typed.
