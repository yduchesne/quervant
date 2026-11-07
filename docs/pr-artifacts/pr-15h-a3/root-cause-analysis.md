# PR 15H-A3 — root-cause analysis

## Terminal classification

**`MEASUREMENT_BLOCKED`** (A3 §13, first matching row).

The A/A environment control failed its frozen caps even though both arms were
built from the same source and produced byte-identical binaries. Per the
precedence rule, no source-performance verdict or causal classification is
permitted, and A/B/BV2/BV3 timings were stopped.

## Supported facts

1. **Source identity.** A2 B differs from accepted A only in `execute.rs`
   (helper + one constant + dispatch + test-only additions) and in
   `unified.rs` `#[cfg(test)]` tests. Helper/scorer region hashes match the
   historical 15H-A candidate exactly. No scorer, ledger, codec or
   `collect_mixed` mutation.
2. **Sparse source path.** Below `H_A2_MIN_POSTINGS = 8_192` the exact original
   eligible loop runs. The gate adds a shape match, one `postings.len()` read and
   one comparison; no extra loop/allocation/decoder/statistics/callback.
3. **Route behavior.** Untimed candidate tests reconfirm 0/1/4,999 postings → 0
   linear invocations; 8,192+ → 1. All behavior, score-bit, cursor, budget and
   cancellation differentials pass.
4. **Machine code.** B's `evaluate_lexical_with` is 713 vs A's 693 instructions,
   contains `cmpq $0x2000` and a call to the helper, and the helper adds 716
   instructions; binary `.text` grows by 14,384 bytes.
5. **Measurement control.** A/A failed with ratios 1.277/1.370 (100K absent),
   1.074/1.226 (100K rare) and 1.134/1.155 (100K common) against 1.15 caps; the
   10K rare lane passed. Both A binaries had the same SHA-256.
6. **Profiler.** `perf` is unavailable for this WSL kernel; no counter or stack
   attribution exists.

## Hypotheses (unproven)

- **E1 Executed extra work:** contradicted for sparse cardinalities by source and
  route witnesses; no additional sparse operation was found.
- **E2 Compiler layout / helper reachability:** the optimized code differs, but
  the failed A/A control cannot separate a codegen effect from host noise.
- **E3 Measurement instability:** the A/A result itself shows that this session
  varies by up to ~1.37× on the same binary and lane, which overlaps the
  magnitude of the historical A2 sparse "regression".

None of these is promoted to a cause. In particular, the A2 sparse regression is
**not** confirmed as a source or codegen effect by A3, and it is not dismissed as
noise either; this session simply could not resolve it.

## Residual risk

- The 100K sparse lanes and common lane are sensitive to host/session
  variability at the frozen AA caps.
- Without `perf`, no instruction/branch/cache attribution is possible in this
  environment.
- Cross-session A2 evidence was not pooled: only the sealed A2 verdict is cited,
  not re-derived.

## Smallest next step (requires a separate approved plan)

Before any future sparse-path optimization is judged, establish a tighter A/A
control on the target host — e.g. more blocks, longer sample windows, CPU affinity
/ isolated core, and a pre-registered AA cap based on measured same-binary
variance. Only after A/A qualifies should the A/B reproduction and V2/V3
interventions be attempted again.
