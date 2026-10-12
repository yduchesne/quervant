# PR 4 review amendment 03 — preflight and reproductions

**Branch:** `dev/analyzer-contract`
**Reviewed/starting HEAD:** `66cfb5fb8182fa40d408c6609e6ff38d0d827304` (matches `origin/dev/analyzer-contract`)
**`origin/main`:** `040b6a945e9e02c26bbf13660744ddceed177797`
**Merge base:** `040b6a945e9e02c26bbf13660744ddceed177797` (PR 4 analysis is feature-only)
**Working tree at preflight:** clean. Toolchains: stable 1.99.0, MSRV cargo 1.85.0.
**`regex-syntax`:** 0.8.11 (parser-only; supports both `\u{0301}` and `\u0301` escapes).

## 1. Baseline

| Command | Result |
|---|---|
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 401 passed; 0 failed; 1 ignored |
| `cargo test --workspace --all-targets` | PASS — 401 passed; 0 failed; 1 ignored |

Prior Amendment 02 evidence (R4/A2 findings) is preserved; this amendment adds to it.

## 2. Reproduction evidence (targeted tests against unmodified `66cfb5f`)

New file `crates/trawler-core/tests/analysis_review_amendment_03.rs` was added and run against
`66cfb5f`: **20 passed; 7 failed**. Every failure is the reviewed cross-boundary defect; no
alleged defect was disproven, so no STOP is required.

| Failing test | Observed at baseline |
|---|---|
| `a3_t02_combining_mark_at_group_start_is_rejected` | `e(?:\u{0301})` (and escaped forms) accepted unchanged; indexed NFC term is `é`. |
| `a3_t03_combining_mark_at_capture_group_start_is_rejected` | `e(\u{0301})` accepted. |
| `a3_t10_unsafe_alternation_branch_at_group_start_is_rejected` | `e(?:\u{0301}|x)` accepted. |
| `a3_t12_quantified_group_starting_with_combining_mark_is_rejected` | `e(?:\u{0301})+` accepted. |
| `a3_t18_nfkc_boundary_combining_mark_is_rejected` | same under NFKC. |
| `a3_t20_nested_groups_and_alternations_do_not_panic` | `a(?:b(?:\u{0301}))` accepted. |
| `a3_i01_real_nfc_pipeline_and_boundary_rejection` | production NFC analyzer emits `é` for `e\u{0301}` while the group-boundary regex is accepted. |

## 3. Existing successful controls (baseline, confirmed)

- `e\u{0301}` (adjacent literal run) → `é`; `(?:e\u{0301})` → `(?:é)`.
- `(?:e)\u{0301}` and `e(?:x)\u{0301}` already rejected by the existing preceded-run check.
- `ab(?:cd)`, `(a|b)c`, `^ab(c|d)[0-9]{2,4}$` accepted unchanged.
- `Straße` → `strasse`; `ß+` rejected; `[0-9]`, `[a-z]`, `\d`, `\w`, `\s` accepted; `[A-Z]` rejected.

## 4. Scope/classification

| Capability | Classification |
|---|---|
| Literal-run NFC composition within one concatenation | DONE (Amendment 02), rerun |
| Quantified literal expansion guard | DONE (Amendment 02), rerun |
| Combining-mark safety across nested groups/alternations/repetitions | PARTIAL → fixed here |
| Real regex query execution | NOT STARTED / out of PR 4 scope (PR 8) |

No STOP condition applied: the fix is a bounded, fail-closed AST boundary check within the
existing grammar, no new dependency, no MSRV/CI change, and no approved safe-pattern case is
rejected (see the test doc for the full acceptance matrix).

## 5. Semantic policy chosen

- Only a **composing normalization** (`NFC`/`NFKC`) can join a combining mark to a preceding
  starter; under `NFD`/`NFKD`/`None` the same patterns are safe and remain accepted.
- In a concatenation, a node (or literal run) at index > 0 that can begin with a combining mark
  after the configured transforms is rejected. A node with no preceding sibling (index 0, or a
  standalone group) is safe and accepted.
- The check is computed from **transformed** first-scalar combining class, so a literal that
  normalizes into a leading combining mark is caught, not just a source combining mark.
- Character classes are governed by the separate class-stability policy; the boundary analysis
  treats them conservatively (documented limitation).
- Work budget/cancellation/nesting limits are unchanged; the added traversal calls
  `check_cancelled` and reuses `apply_pattern_transforms` for charging.
