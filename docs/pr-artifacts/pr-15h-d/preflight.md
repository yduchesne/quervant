# PR 15H-D — preflight

**Branch:** `dev/pr15h-a-linear-term-candidates`
**C correction (required predecessor):** `d4b10c18a0a906f9f22f169c6437e3f82e796401`
**D tooling / A identity:** `c802f965a57d5038e98006bba581c4356654baaf`
**Measured candidate:** `0f97779191ad1969d00dd15988601ade0ab59522`
**D rollback:** `2ac85c7a936fe4e57fea78c54700d0a58a544acf`
**`main`:** `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078` (unchanged)

## Source and C reconciliation

- Branch/HEAD matched the plan's starting literals; worktree clean.
- The C source was verified byte-identical to `e8744d3` and all C seals
  verified read-only under the original pinned tooling.
- The frozen C contract explicitly prescribes the lower median
  (`sorted(d)[1]`); C-MEDIAN-LOWER applies. C gates/controller output were left
  unchanged. Nonsealed docs now label the lower median and add the informational
  conventional median; the sealed sanitized Markdown's historical “PR 15H-B”
  title was preserved and documented in `docs/pr-artifacts/pr-15h-c/CORRIGENDUM.md`.
- `C_CORRECTION_SHA` is an ancestor of `D_TOOLING_SHA` and all D commits.

## Source shape verified before edits

`execute_unified` resolved `SchemaAnalyzerBindings` + `CodecSchema`, computed the
cursor fingerprint, then called `unified_plan::compile`, which resolved the same
two values again. `select_keys` calls `compile` directly. `score::compute_stats`
was measured but not modified.

## Environment

WSL2 native ext4; `rustc 1.98.1`, MSRV `1.85.0`; host fingerprint
`4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f`;
frozen corpus `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`.

## Scope

Production changes only in `search/unified.rs` and `search/unified_plan.rs`.
No statistics/BM25/postings/codec/format/API/cache change. D tooling under
`benchmarks/pr15h_d/`; D evidence under `docs/pr-artifacts/pr-15h-d/`.
