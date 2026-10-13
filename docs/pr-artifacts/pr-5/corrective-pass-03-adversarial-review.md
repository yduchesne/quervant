# PR 5 corrective pass 03 adversarial review

## Plausible still-broken implementations and catching tests

| INV | Still-broken implementation | Catching test / audit |
|---|---|---|
| C7-INV01 | `try_reserve_exact` before the cumulative reserve | Source audit `:151`→`:164`→`:167`; `c7_u02` one-below |
| C7-INV02 | `to_owned()`/`insert(clone)` before the per-entry reserve | Source audit `:193`→`:194`→`:195`, `:210`/`:211`→`:218`→`:219`/`:220`; `c7_stage_prefixes...` (`segment_id`, `object_key` stages) |
| C7-INV03 | Decode required features, then check after; or charge only required not optional | `c7_stage_prefixes...` (`required_features`, `optional_features`); `c7_u17` oracle |
| C7-INV04 | Charge both manifest vectors only after building both | `c7_stage_prefixes...` (`manifest_required_features`, `manifest_optional_features`) |
| C7-INV05 | Saturating/checked arithmetic that lets exact-limit pass but one-below not fail | `c7_u02`, each stage prefix |
| C7-INV06 | Adjacent-only duplicate detection; ID comparison `>` instead of `>=` | `c7_u15` (nonadjacent a,b,a), `c7_u16` (b,a) |
| C7-INV07 | `retained_bytes` omits the second key payload or feature vectors | `c7_u17` independent oracle + `debug_assert` |
| C7-INV08 | Skip borrowed UTF-8/grammar validation to avoid "temporary" allocations | `c7_u18`, `c7_u20`, `c7_u21` |
| C7-INV09 | Change encoder/golden while touching decode | Golden SHA unchanged; `c6`/`segment_golden` regression |
| C7-INV10 | Leave a partially built `segments` vector observable | `c7_i05` |
| C7-INV11 | Document the charge as a heap/RSS cap | `retained_bytes` doc review |
| C7-INV12 | Skip stable Clippy because MSRV passed | Both `+1.85.0` and stable Clippy executed |

## Allocation-order evidence

The plan's §10 forbids introducing a custom `#[global_allocator]` (a STOP
condition), so no allocation-count red was run. Instead:

1. Baseline source defect is documented with exact lines (`manifest.rs:177`,
   `:192`, `:226`/`:228`, `:247`/`:249` allocate before `:244`/`:261` check).
2. Post-fix audit shows each charged allocation preceded by an individual and a
   cumulative check (`manifest.rs:151/164/167`, `193/194/195`, `210/211/218/219/220`,
   `387/388/389`).
3. Stage-prefix tests assert the reported `LimitExceeded.requested` equals the
   cumulative prefix of the failing stage, exercising every charged stage.

This is a candid audit, not a fabricated red.

## Independent oracle

The expected charge is computed from fixture inputs (`retained_bytes` only as a
second assertion). No production accumulation loop is reused to derive
expectations.

## Residual risks

| Risk | Severity | Disposition |
|---|---|---|
| Modeled charge ≠ physical heap/RSS | Medium if misrepresented | Documented explicitly; not claimed as a heap cap |
| Temporary ID/key validation clones | Reduced to zero via borrowed `validate_key` | Resolved for ID/key; container/schema temporaries remain separate |
| `BTreeSet` node overhead is an estimate (`+32`) | Low | Accepted under modeled contract |
| No allocation-count red | Low | Plan forbids custom allocator; source audit provided |
| Schema/manifest budgets independent | Medium for total-container budgeting | Deferred; explicitly out of pass 03 |
| Whole-object segment buffering | Existing PR 5 limitation | Out of scope |

No new STOP condition. No unresolved correctness failure.
