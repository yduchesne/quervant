# PR 14 — F1 hardening adversarial review

| Claim | Evidence | Verdict |
|---|---|---|
| One authoritative mixed work counter | `MixedWorkMeter` owned by `collect_internal`; `SearchWork`/`ScanGuard` `Shared` modes own no counter | PASS |
| Aggregate exhaustion fires when lexical+typed each fit alone | `work::aggregate_exhaustion_blocks_typed_after_lexical` | PASS |
| Rejected charge cannot partially execute / mutate counters | `work::rejected_typed_charge_does_not_mutate_counters` | PASS |
| Scanned-posting units preserved (`1+freq` + independent scanned ceiling) | `work::scanned_charges_add_one_plus_freq` | PASS |
| Zero-match expensive scan still charges | `w04_zero_match_scan_charges_work` | PASS |
| Cancellation observed in the mixed lexical/typed loop | `w06_mixed_cancellation` | PASS |
| No overlapping mutable meter borrows | scoped `SearchWork::shared` for leaf build; callback receives meter; scoped `TypedCharge` per typed evaluation | PASS (compiler + review) |
| No `Rc<RefCell>`/unsafe/global state/post-hoc reconciliation | source review: only `&mut dyn` adapters | PASS |
| Standalone lexical/typed budgets unchanged | `SearchWork::new`/`ScanGuard::new` Owned paths unchanged; PR 7/10 suites green | PASS |
| Mixed BM25 bit-identical | S01–S03, S05 | PASS |
| Sort validation before I/O | V01–V05 | PASS |
| Mixed geo sort | G01–G03 | PASS |
| Physical projection current version | P02 | PASS |
| No persisted/public-contract changes | diff limited to `search/*` + tests | PASS |

## Residual risks
1. M-series exact/one-over bytes and G04/G05 multivalue/tie geo are only partially covered
   (shared comparator and existing PR 10 suites supply the rest).
2. Real RustFS and final-SHA CI remain blocked.
3. `MixedWorkMeter::charge` checks before commit (stricter than the legacy `SearchWork`, which
   committed the counter before returning the limit error). Observable behavior on the success
   path and the returned error are unchanged.
