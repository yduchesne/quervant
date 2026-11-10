# PR 15I-C fixup — invariant traceability

Status: **F0 rejected**; the F1/F2 invariants were never exercised because the
generic-boundary precondition failed. Nothing below is claimed as executed unless
it says so.

| ID | Invariant | Status in this fixup |
|---|---|---|
| FX-I01 | Generic `collect_mixed` statement body source-equivalent to merged 15I-B (only `#[inline(never)]` may differ) | **ENFORCED AND PROVEN** at `G_CONTROL_SHA`: body SHA-256 `00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994` identical to `6f6463cb…` (`source_proof.py`, `test_layout_diag.py`, `verify_layout_diag.py` step 3, FX-U01-equivalent). |
| FX-I02 | All input/sort/top-K/projection/cursor/plan validation stays at its established position | NOT EXERCISED (no dispatcher introduced). Production byte-identical to merged base at the final tip. |
| FX-I03 | Eligibility is exactly prior `C-EXACT-ONE` | NOT EXERCISED (no eligibility predicate restored). |
| FX-I04 | Generic fallback selected before segment execution; no retry after errors | NOT EXERCISED (no dispatch). |
| FX-I05 | Exact `total_hits`, keys, sort tuples, physical ids, projection, cursor | NOT EXERCISED for a refactor; the baseline itself is unmodified. |
| FX-I06 | Bit-identical BM25; complete scoring errors before key/sort | NOT EXERCISED for a refactor; `search/score.rs` never changed. |
| FX-I07 | Legacy work/scanned and virtual matched/scored admission checkpoints | NOT EXERCISED for a refactor; `search/execute.rs` never changed. |
| FX-I08 | Canonical Keyword comparator, no key/column shortcut | NOT EXERCISED (no fast method). |
| FX-I09 | Generic path structurally executable for every other shape | Baseline unchanged; PR15E/PR15H-B suites pass at the final tip. |
| FX-I10 | No new reader/format/codec/index/public API/remote I/O | **HELD**: no production file other than `search/unified.rs` was ever touched, and it is restored. `Cargo.lock` unchanged. |
| FX-I11 | LZ4 STORED v2 `(0x000D,1)`, V3 `(0x000C,1)`, PIT, generations unchanged | **PROVEN** for the diagnostic builds: both arms produce LZ4 STORED v2 with required feature `[13,1]`, byte-identical layouts and segment digests, 100K sentinel 15 747 551 / 1 661 455. |
| FX-I12 | Profile/machine-code work is diagnostic only | **HELD**: `codegen_capture.py` writes only under `target/pr15i-c/layout-diagnostics/`; no `RUSTFLAGS`/opt-level/target changes; no profiler dependency. |
| FX-I13 | Frozen nine lanes, 16 slots, original corpus/oracle, frozen thresholds | **HELD**: `benchmarks/pr15i_c/protocol.json` untouched (SHA-256 `5464144…`); the diagnostic has its own identity and is explicitly not acceptance. |
| FX-I14 | Benchmarks may run on the assumed idle host with real contamination checks | **HELD**: contention clear before/after every one of the 32 slots in both valid runs. |
| FX-I15 | Prior raw/receipts/SHAs/reports immutable; new attempts use fresh IDs | **HELD**: `paired-01` untouched and re-verified read-only; new IDs `generic-boundary-01..04` and `codegen-01..03`. |
| FX-I16 | On failure, additive rollback with production equal to merged base | **EXECUTED** (see `fixup-execution-status.md`). |
| FX-I17 | Hosted CI, real RustFS, review and merge are separate facts | **HELD**: reported separately; no merge claim. |
| FX-I18 | Unknown condition is a HARD STOP | **HELD**: no unlisted condition was resolved by invention; see `fixup-decision-log.md`. |
