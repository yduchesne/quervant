# Historical equivalence matrix (BM-09)

Read-only assessment. No historical file, archive or report was created, moved,
rewritten or re-pinned by this work.

Legend: `EXACT` — same canonical algorithm and inputs; `SEMANTIC` — different
schema with an independently proven equivalent conclusion; `NON_EQUIVALENT` —
genuinely different arithmetic; `EVIDENCE_UNAVAILABLE` — authentic original data
missing; `FAILED` — mismatch.

| # | Legacy source identity | Archived input | Legacy verifier | Original result | New verified result | Comparison scope | Expected equivalence | Computed comparison | Approved tolerance | Status | Reviewer approval |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `benchmarks/pr15d/harness/{run,validate,aggregate}.py` @ `a5a8303` | PR15D trial manifests (`run.json` + 9 trial manifests) | `validate.py` (pr15d-validation-v1) | historic 3-trial descriptive `INCONCLUSIVE` | none (no authenticated archive on host) | warm exact-keyword lanes | SEMANTIC (logical order equivalent, physical sort not claimed) | not executed | NONE | **EVIDENCE_UNAVAILABLE** | none |
| 2 | `benchmarks/pr15d/corpus/oracle.py` | generated 10K/100K TSV + manifest | `oracle.load_and_verify` | historic corpus digests | independent row-formula recomputation implemented (`official.verification.ref_cross_engine_answers`) | exact-keyword answer sets | EXACT | unit tests agree | NONE | IMPLEMENTED, HISTORICAL ROW BLOCKED | none |
| 3 | `benchmarks/pr15i_d3_c/verify.py` | historical `pr15i-d3-c-v3r3` archives (3 archives + sidecars present) | `verify.py` (`pr15i-d3c-verification-v1`) | historic `ACQUIRED_VERIFIED` (self-reported) | archive audit implemented (`official.historical.audit_retained_key_archive`) | 12-block/72-lane statistics | SEMANTIC (four-value lower-middle median preserved) | archive digests verified read-only; numeric replay not executed | NONE | **BLOCKED** | none |
| 4 | `benchmarks/pr15i_d3_c/protocol_v3r3.json` | protocol raw bytes | frozen SHA-256 | `diagnostic_only=true` | re-hashed and required equal | protocol identity | EXACT | PASS | NONE | PASS (identity only) | not required for identity |
| 5 | `benchmarks/pr15i_d3_c_t7` + `_t7_f2` policy chain | T7-F2 micro/F1/policy inputs | `verify_policy.py` | historic nine-K decision | not runnable (no authentic micro/F1 inputs) | nine-K policy rows | NON_EQUIVALENT vs generic medians | not executed | NONE | **EVIDENCE_UNAVAILABLE** | none |
| 6 | BM-07 retained-key synthetic result | synthetic fixtures | BM-07 offline validator | simulated | unchanged, re-run green | n/a | n/a | n/a | n/a | NOT APPLICABLE to real parity | n/a |
| 7 | BM-08 cross-engine synthetic result | synthetic catalog | BM-08 offline validator | simulated | unchanged, re-run green | n/a | n/a | n/a | n/a | NOT APPLICABLE to real parity | n/a |

## Notes

- The D3-C four-value median `sorted[1]` is preserved verbatim; it is **not** the
  ordinary median of four (`official.analysis.lower_median`). Averaging the middle
  values to force parity is forbidden.
- PR15D three-trial descriptive `INCONCLUSIVE` is not a confidence-bound
  significance result and must not be presented as one.
- A synthetic BM-07/BM-08 result cannot satisfy a historical parity row.
- Row 3 stays `BLOCKED` even though archives exist: an authentic numeric replay plus
  an approved mapping and reviewer ID is required, and the reviewer artifact does
  not exist. Row 1/5 stay unavailable because the authentic material is absent.

---

# RF09-F1 addendum

The parity gate was hardened. `official.historical.assess_required_historical_parity`
is now read-only and can no longer return `PASS`: caller-supplied rows plus a
reviewer label produce at most `COMPARISON_COMPUTED_PENDING_REVIEW`, and
`require_parity_pass` / Gate D reject that.

A separate `VerifiedHistoricalParity` capability is created only by
`open_verified_historical_parity(...)`, which requires:

- a versioned `official-historical-parity-mapping` approved by an external
  `official-historical-parity-approval` record whose approved digest matches;
- an authentic archive whose declared member digests match its bytes exactly and
  whose member set contains nothing undeclared;
- the frozen original verifier digest matching the actual repository file;
- independently recomputed row metrics (lower-middle median, nearest-rank p95/p99,
  total hits, ordered doc IDs) that match the approved expected values within the
  approved tolerance.

`require_verified_historical_parity(...)` re-reads the approval and mapping,
re-audits the archive and re-recomputes the row digest before Gate D, so a
post-review archive or mapping change invalidates previously computed parity.

Rows 1, 3 and 5 of the matrix above therefore remain **BLOCKED**: no authentic
PR15D archive, no authentic T7/F2 policy inputs and no reviewer-approved mapping
exist on this host. The comparator and approval reader are implemented and covered
by fixture-only sandbox tests; that is not historical parity evidence.
