# PR 15I-C dispatch-isolation — arms, source and binary proof

| Arm | Git SHA | Build feature | Process variable | Audited source delta |
|---|---|---|---|---|
| A | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` | none | none | merged baseline |
| C | `658a2dde0e15c17e2b0c92278b5c922f5260fe60` | `pr15ic-causal` | `QUERVANT_PR15IC_CAUSAL_MODE=disabled` | historical causal candidate |
| D | `9c710e5432aa17cdcd717ce40ad6f9a8167914f1` | `pr15ic-causal` | `QUERVANT_PR15IC_CAUSAL_MODE=disabled` (ignored) | C + `if false && shape_eligible` |
| E | `d97889d2debc14f1e4ea3c821089cd453ba1daab` | `pr15ic-dispatch-isolation` | `QUERVANT_PR15IC_DISPATCH_MODE=disabled` | A + copied predicate + gate + trampoline |

## Generic collector identity (all four arms)

`collect_mixed` normalized body SHA-256 is
`00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994` in A, C, D and
E, with the baseline attribute pair `#[allow(clippy::needless_option_as_deref)]`
and `#[allow(clippy::too_many_arguments, clippy::type_complexity)]` and **no**
inline attribute. No arm edits `execute_unified`'s own attributes.

## D proof (one expression)

`git diff C..D --name-only -- 'crates/**'` → `crates/quervant-core/src/search/unified.rs`
only, and the whole-file diff normalizes to exactly:

```diff
         #[cfg(feature = "pr15ic-causal")]
-        let c_physical = if shape_eligible {
+        let c_physical = if false && shape_eligible {
             pr15ic_causal_enabled()?
         } else {
             false
         };
```

No other byte differs. D does not use `black_box`, so the compiler is free to
remove the physical call (and did: see `dispatch-isolation-codegen.md`).

## E proof (two files, no operator)

`git diff A..E --name-only -- 'crates/**'` → `crates/quervant-core/Cargo.toml` and
`crates/quervant-core/src/search/unified.rs` only.

* `Cargo.toml`: adds the empty non-default feature `pr15ic-dispatch-isolation`;
  dependencies and lock unchanged.
* `unified.rs`: adds `exact_term_physical_eligible` copied from C **minus** its
  `#[cfg(test)]` forced-generic guard (normalized-body equality verified), the
  `OnceLock` gate reading `QUERVANT_PR15IC_DISPATCH_MODE`, the
  `#[inline(never)] collect_mixed_dispatch_probe` pass-through
  (`black_box(plan)` then `self.collect_mixed(...)`), and the feature-gated
  dispatch at the original call site.
* Removing those additions and the dispatch block restores A's file **byte for
  byte** (verified by `dispatch_source_proof.py`).
* E contains no `collect_exact_term_physical`, no
  `for_each_exact_term_score_with`, no `c15i_observation`/`c15i_guard`, no
  `search/diagnostics.rs` restoration and no `pr15ic-causal` feature.

One mechanical addition beyond the literal contract was required to compile the
copied predicate: `SortDirection` in the existing `contract::result` import line of
`unified.rs`. It is inside the authorized file and adds no behavior.

## Mode truth tables (executed against the real adapters, separate processes)

| Arm | unset | `enabled` | `disabled` | invalid | result equality |
|---|---|---|---|---|---|
| A | ok | ok (ignored) | ok (ignored) | ok (ignored) | identical keys/count |
| C | typed error | ok (physical) | ok (generic) | typed error | enabled == disabled on the measured lane |
| D | ok | ok | ok | ok | all identical to C-disabled |
| E | typed error | ok (trampoline) | ok (generic) | typed error | enabled == disabled |

## Binaries (per campaign, distinct per arm)

Each campaign records the four adapter SHA-256 values in `raw/binaries.json` and
`raw/manifest.json`; they are re-hashed after the campaign and after verification.
The four values are always distinct. Per-arm score probes are built with the same
feature configuration and are launched with the same mode environment, so the
score-bit comparison is made on the arm's own generic path.
