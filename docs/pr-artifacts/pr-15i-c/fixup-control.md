# PR 15I-C fixup — F0 generic-boundary control (`G_CONTROL_SHA`)

Purpose: falsify or confirm, **before** any fast-path source is restored, whether
putting the generic executor behind an out-of-line boundary is itself
performance-neutral.

## 1. The single production change

```diff
+    // 15IC-FIXUP-CODEGEN-01 (G control): exactly one compiler-layout annotation.
+    // The body of this method is byte-identical to the merged PR 15I-B body; the
+    // out-of-line boundary is the pretested generic-neutrality control.
+    #[inline(never)]
     #[allow(clippy::needless_option_as_deref)]
     #[allow(clippy::too_many_arguments, clippy::type_complexity)]
     fn collect_mixed(
```

Nothing else in `crates/quervant-core/src/search/unified.rs` differs from merged
PR 15I-B, and no other production file differs at all.

## 2. Source-body proof (`FX-D18`/`FX-D19`, FX-U01)

Brace-aware extraction of `fn collect_mixed` (attributes excluded) via
`benchmarks/pr15i_c/source_proof.py`:

| Source | Body SHA-256 |
|---|---|
| `6f6463cb…` (merged PR 15I-B) | `00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994` |
| `G_CONTROL_SHA` | `00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994` |

The candidate's attribute block is exactly
`["#[inline(never)]", "#[allow(clippy::needless_option_as_deref)]", "#[allow(clippy::too_many_arguments, clippy::type_complexity)]"]`
plus the explanatory comment: one and only one inline attribute was added
(`FX-D18`), the generic body is unchanged (`FX-D19`).

## 3. Static assertions

| Assertion | Result |
|---|---|
| Only `crates/quervant-core/src/search/unified.rs` changed in production | PASS |
| Exactly one `#[inline(never)]` inserted before `fn collect_mixed` | PASS |
| `fn collect_mixed` body byte-identical after normalization | PASS (equal hashes) |
| `execute_unified` still calls `self.collect_mixed` | PASS (call site untouched) |
| No C-EXACT-ONE operator, eligibility predicate or candidate import compiled | PASS (no candidate source restored yet) |
| Default release contains no probe symbol | PASS (probe feature absent from this control) |
| `cargo +1.85.0 check --locked -p quervant-core` | PASS |
| Baseline unified/execute unit tests | PASS |

## 4. Diagnostic harness added with this commit (tooling only)

| File | Purpose |
|---|---|
| `benchmarks/pr15i_c/source_proof.py` | brace-aware method extraction / body hashing |
| `benchmarks/pr15i_c/layout_diag.py` | 7-lane × 8-block generic-boundary controller |
| `benchmarks/pr15i_c/verify_layout_diag.py` | independent verifier for the diagnostic |
| `benchmarks/pr15i_c/codegen_capture.py` | diagnostic-only binary/symbol/disassembly/perf capture |
| `benchmarks/pr15i_c/test_layout_diag.py` | controller tests |
| `benchmarks/pr15i_c/test_verify_layout_diag.py` | adversarial verifier tests (FX-V*) |
| `benchmarks/pr15i_c/test_codegen_capture.py` | capture-wrapper tests |

The diagnostic has its own protocol identity
(`pr15i-c-layout-diag-v1` / `pr15i-c-layout-diagnostic-v1`), its own sealed output
tree (`target/pr15i-c/layout-diagnostics/…`) and its own receipt
(`target/pr15i-c/reviews/layout-…json`). It never edits
`benchmarks/pr15i_c/protocol.json`, the nine-lane authoritative campaign, or the
historical `paired-01` evidence.

## 5. Gate

`G_CONTROL_QUALIFIED` requires all seven lanes to have
`median B/A <= 1.05` and **every one of the eight blocks** `<= 1.15`, with exact
oracle responses and independently verified provenance. Any valid failure means
the boundary itself is unsafe: roll back the attribute, record
`15IC_GENERIC_BOUNDARY_REJECTED_SAFE_ROLLBACK`, and HARD STOP operator
restoration (`FX-D33`).
