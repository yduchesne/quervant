# PR 4 — MSRV let-chain compatibility fixup

**Gate:** resolves the previously BLOCKED V1 / D-GATE-1 workspace-level Rust 1.85 build.
**Authority:** Option A approved by the Trawler owner — replace Rust 1.88 let-chain syntax with
equivalent Rust 1.85-compatible constructs; preserve MSRV 1.85.
**Branch:** `dev/analyzer-contract`.
**Scope:** **10** `if let … && …` let-chain expressions in the five PR 2 contract files only.
No public contract, error type, constant, or unrelated behavior changed.

## 1. Why the workspace failed on Rust 1.85

`if let PATTERN = SCRUTINEE && CONDITION { … }` (a "let chain") is only stable from Rust 1.88
(edition 2024). The workspace declares `rust-version = "1.85"` and CI runs on `stable`
(currently 1.99), so the incompatibility was latent. `cargo +1.85.0 test -p trawler-core`
produced `error[E0658]: let expressions in this position are unstable` for these expressions.

## 2. Transformation applied

Each let-chain was rewritten to a nested `if let { if cond { … } }` form. This is semantically
identical because Rust evaluates the scrutinee first and only evaluates the trailing condition
when the pattern matches (i.e. it short-circuits exactly like the nested form). No condition or
body was reordered, duplicated, or moved across a `?`/`return`.

### `contract/batch.rs` (1)

```rust
// before
if let Some(own) = &query.pit
    && own != shared
{
    return Err(InvalidBatchReason::ConflictingPit.into());
}
// after
if let Some(own) = &query.pit {
    if own != shared {
        return Err(InvalidBatchReason::ConflictingPit.into());
    }
}
```

### `contract/aggregation.rs` (3)

`BudgetKind::GroupKeyFields`, `BudgetKind::DistinctKeys` (`max == 0`), and the
`time_bucket.width_micros <= 0` checks were rewritten the same way, e.g.:

```rust
// before
if let Some(max) = budgets.get(BudgetKind::GroupKeyFields)
    && u64::try_from(group_by.keys.len()).unwrap_or(u64::MAX) > max
{
    return Err(QueryError::BudgetExceeded { kind: BudgetKind::GroupKeyFields });
}
// after
if let Some(max) = budgets.get(BudgetKind::GroupKeyFields) {
    if u64::try_from(group_by.keys.len()).unwrap_or(u64::MAX) > max {
        return Err(QueryError::BudgetExceeded { kind: BudgetKind::GroupKeyFields });
    }
}
```

### `contract/result.rs` (1)

`BudgetKind::ResultWindow` limit check rewritten to the nested form.

### `contract/schema.rs` (4)

`BudgetKind::Fields`, `BudgetKind::DocumentBytes`, `BudgetKind::ArrayElements`, and
`BudgetKind::JsonDepth` checks rewritten to the nested form. The `JsonDepth` case was already
inside `if let FieldValue::Json(json) = value`; only the inner let-chain was nested further.

### `contract/query.rs` (1)

`BudgetKind::QueryDepth` check rewritten to the nested form.

## 3. Verification that no let-chains remain

```text
rg -U "if let[^\n]*\n\s*&&|while let[^\n]*\n\s*&&" crates --glob '*.rs'
# NONE  (0 matches across crates/, including tests/)
```

No other MSRV incompatibility was encountered. If one had appeared, work would have stopped and
been reported (per the fixup instruction), rather than expanding scope.

## 4. Before/after gate evidence

| Check | Before fixup | After fixup |
|---|---|---|
| `cargo +1.85.0 test --workspace --all-targets` | **BLOCKED** (`E0658` let-chains) | **PASS — 342 passed; 0 failed; 1 ignored** |
| `cargo test --workspace --all-targets` (stable) | PASS — 342 passed | **PASS — 342 passed; 0 failed; 1 ignored** |
| `cargo fmt --all -- --check` | PASS | **PASS** |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS | **PASS** |
| `cargo doc --workspace --no-deps` | PASS | **PASS** |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | 94.04% lines | **PASS — 94.00% lines** (90.87% functions, 93.90% regions) |

The small coverage delta is line-count noise from the rewrite (one nested `if` closes on its own
line); it remains well above the 85% floor and no behavior is uncovered.

## 5. Confirmations

- Workspace MSRV remains `rust-version = "1.85"` (unchanged in `Cargo.toml`).
- Only the 10 let-chain expressions in the five files were modified; no public contract changed.
- Existing tests (including PR 2/PR 3 suites and the new PR 4 A4/I4 suites) all pass unchanged,
  which is the behavioral regression check for the rewrite.
- No merge performed.
