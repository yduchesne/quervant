# PR 15I-C-F — source and code generation

Diagnostic only. No acceptance decision is taken from this document.

## 1. Arm sources

| Arm | Commit | Production content | Feature | Runtime mode |
| --- | --- | --- | --- | --- |
| A | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` | merged PR 15I-B | none | none |
| C | `658a2dde0e15c17e2b0c92278b5c922f5260fe60` | historical causal candidate | `pr15ic-causal` | `disabled` |
| F | `5f74bb691420673bde1181603d0a19a8a4114ec8` (`F_DIAG`) | C + `#[inline(never)]` on `collect_mixed` | `pr15ic-causal` | `disabled` (G) / `enabled` (P) |

`F_DIAG` is a child of `CAUSAL_PARENT`; `git diff CAUSAL_PARENT..F_DIAG -- crates/`
contains exactly one path, `crates/quervant-core/src/search/unified.rs`, and the
tree equals `CAUSAL_PARENT` after reversing the three authorized edits:

1. `#[inline(never)]` inserted immediately above `fn collect_mixed(`;
2. the `n_u34` doc comment;
3. the `n_u34` assertion (exactly one out-of-line attribute, no additional
   inline attribute).

The source proof (`benchmarks/pr15i_c/f_final_source_proof.py`) recomputes this
mechanically for every campaign and is re-run by the verifier.

## 2. Body hashes

| Symbol | SHA-256 of normalized body | A | C | F |
| --- | --- | --- | --- | --- |
| `collect_mixed` | `00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994` | identical | identical | identical |
| `collect_exact_term_physical` | `522f6600f0efa24fbe26e9af2644fbc4cc8b8f3f45558d5ed3c9b78ce5a62f1a` | absent | identical | identical |

Attribute block on the generic collector at `F_DIAG`:

```text
'#[allow(clippy::needless_option_as_deref)]'
'#[allow(clippy::too_many_arguments, clippy::type_complexity)]'
'#[inline(never)]'
```

## 3. Emitted symbols (per campaign capture)

Captured with `benchmarks/pr15i_c/dispatch_codegen_capture.py` into
`<campaign>/setup/codegen/dispatch-codegen.json`; the derived booleans are
recorded in `raw/codegen.json` and re-derived by the verifier.

| Symbol | A | C | F (G and P) |
| --- | --- | --- | --- |
| `execute_unified` | present | present | present |
| `collect_mixed` | inlined / not present | inlined / not present | **present (out of line)** |
| `collect_exact_term_physical` | absent | present | present |

The structural facts for the campaign are therefore:

- `f_physical_present` — the physical collector exists in the F binary;
- `f_generic_out_of_line` — `#[inline(never)]` produced a real, non-empty
  `collect_mixed` symbol that is absent in A and C;
- `f_execute_present`, `a_execute_present`, `c_execute_present`,
  `e_execute_present` — the unified search entry point is emitted in every arm.

No cycle, cache, branch-prediction or kernel-bypass claim is made: `perf` is
unavailable on this host (`PERF_UNAVAILABLE`), so the capture is symbol presence
and instruction/byte counts only.

## 4. Codegen gate before sampling

The diagnostic adapter built from `F_DIAG` with
`--features quervant-core/pr15ic-causal` carries standalone symbols for
`collect_mixed`, `execute_unified` and `collect_exact_term_physical`, and the
`QUERVANT_PR15IC_CAUSAL_MODE` gate string. G and P therefore differ only by the
child-process environment value, which is what the truth-table probe
(`raw/mode-proof.json`) verifies per campaign.

## 5. Release variant

Not built. The §8.5 gate failed, so `F_RELEASE` was never constructed and the
frozen 16-slot campaign was not run. Production source was restored to
`BASE_A` byte-for-byte.
