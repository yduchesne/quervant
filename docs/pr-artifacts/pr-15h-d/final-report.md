# PR 15H-D — final report

1. **Branch/SHAs.** `dev/pr15h-a-linear-term-candidates`; C correction
   `d4b10c1`; D tooling/A `c802f96`; candidate `0f97779`; rollback `2ac85c7`;
   worktree clean; no push/PR/merge; CI pending.
2. **C corrigendum.** C-MEDIAN-LOWER: the frozen C contract prescribes the lower
   median, so C gates were unchanged. Nonsealed docs now label the lower median
   and add the informational conventional medians (P1 −2.9575, P2 +0.3450,
   P3 −1.7420, G1 −0.5575, G2 −0.0180, G3 −0.0230 ms). The sealed sanitized
   “PR 15H-B” title was preserved byte-for-byte and documented in
   `docs/pr-artifacts/pr-15h-c/CORRIGENDUM.md`. C correction precedes D.
3. **Source delta.** Only `search/unified_plan.rs` (new internal
   `compile_with_resolved`; `compile` delegates) and `search/unified.rs`
   (`execute_unified` passes its already-resolved bindings/codec). No
   statistics/scoring/posting/codec/format/API/cache change. Protected files
   byte-identical to A.
4. **Traceability.** `docs/pr-artifacts/pr-15h-d/invariant-traceability.md`
   maps D-K01–D-K12 to executed D-U/D-I/D-T evidence.
5. **Measurements.** Baseline seal `72c8d17d…`, paired seal `902d8432…`,
   sanitized `01a20620…`; 360 baseline samples, 960 paired samples, 240 warmups,
   16 clear probes, 48 oracle checks; byte-identical index digests.
   Conventional medians: P1 +0.306, P2 +0.298, P3 +0.866 ms; guards +0.101,
   +0.012, +0.001 ms.
6. **Gates.** D-P00 PASS, D-P01 FAIL, D-P02 PASS, D-P03 PASS.
7. **Disposition.** `PERFORMANCE_REJECTED_SAFE_ROLLBACK`; `unified.rs` and
   `unified_plan.rs` restored byte-for-byte to `c802f96`; D tooling/tests and
   sealed evidence retained; D-only tests removed by the restore.
8. **QA.** Stable 2,339/2,343 tests, coverage 92.70 %, MSRV 2,343, scripts 108,
   full real RustFS matrix PASS. Any nonpass? None; hosted CI pending.
9. **Residual risk.** One WSL2 host, six frozen lanes; the duplicate-resolution
   hypothesis saved <1 ms on the primaries, so it was rejected. No
   cross-engine claim and no statistics optimization was implemented.
10. **Next human action.** Review the evidence and, if authorized, push for
    exact-final-HEAD CI. Not merged or self-approved.
