# PR 15G-A decision log

Only rules from the approved matrix are recorded. No unrecognized condition was
resolved by inventing behavior.

| Rule | Trigger observed | Action taken | Verification / remaining gate |
|---|---|---|---|
| GA-D01 | clean `main` at `f44d7f4...`; source shape matched §3 | created `dev/pr15g-a-retained-column-geometry` and executed phases 0–5 | preflight identity; A00 PASS |
| GA-D04 | `ColumnMeta` primitive-only; existing parser uses `try_reserve_exact` | implemented owned/borrowed `ColumnGeometry` without cloning on hit | GA-U01/U02/U07/U12; A01 PASS locally |
| GA-D05 | `ColumnReader` callers unchanged | preserved public signatures; routed both parser entry points through one private body | workspace tests; A01/A03 PASS locally |
| GA-D06 | `meter` already present in `decode_metadata` | retained geometry only on the metered candidate; added allowance and measured capacity charge | GA-U08/U09/U10, `g5_01`; A02 PASS locally |
| GA-D07 | absent COLUMNS vs present zero-column section | preserved `None` vs `Some(empty geometry)` | GA-U04; A01/A03 PASS locally |
| GA-D08 | zero cap / candidate reservation failure | unchanged fully validating uncached fallback; no shared retention | GA-U08/U09 and `g5_01`; A02 PASS locally |
| GA-D09 | corrupt state tag/truncation/type mismatch | propagated the original typed validator error | GA-U05/U06/U14; A03 PASS locally |
| GA-D10 | metering/limits can reject before an underlying corruption is reached | fallback re-discovers the authoritative typed error; no admission error is reported as corruption | GA-U11 and snapshot fallback tests; A03 PASS locally |
| GA-D14 | borrow source is the same-state `Arc<VerifiedSegmentState>` | borrowed `&shared.column_geometry` and the same COLUMNS body slice into a query-local reader | GA-U12/U13 and `g5_01`; A01/A03 PASS locally |
| GA-D17 | no deterministic pre-existing baseline failures | no baseline failure was waived or reclassified | baseline logs in `target/pr15g-a/qa/baseline-*.log` |
| GA-D18 | two new tests failed only after implementation | fixed inside the approved model (expected block counter; rebuild container with valid envelope digest) and reran affected suites | column/reader/integration tests PASS |
| GA-D19 | no fix required a third production file | scope stayed within the two authorized production files plus snapshot test-only coverage | staged diff |
| GA-D20 | no explicit operator idle authorization | skipped timed comparison; recorded `PERF_BLOCKED_OPERATOR`; ran only the negative authorization test | P01–P04 BLOCKED; A07 BLOCKED |
| GA-D24 | hosted CI status not available from this session | no green CI claim; exact-head hosted acceptance remains blocked until pushed/observed | A09 BLOCKED / NOT OBSERVED |
| GA-D25 | RustFS service/image unavailable | kept local implementation and tests; did not substitute a fake for GA-I07/I08 | A06 real-RustFS portion BLOCKED |
| GA-D28 | all locally executable gates passed; no unclassified finding | prepared evidence and branch for independent review; did not self-approve or merge | status `QA_PASS_PERF_BLOCKED_OPERATOR`; A10 NOT STARTED |
| GA-D30 | routine phase completion | continued through implementation, tests, runner and documentation without gratuitous approval requests | phase log above |

## Scope and guardrail confirmations

- No `unsafe`, new dependency, lockfile change, public API change, segment
  format change, manifest change, storage-provider change or query-semantic
  change was introduced.
- `index/snapshot.rs` production logic, `segment/metadata.rs` semantics,
  `search/{unified,execute,typed_compare}.rs`, PR 15D/15E/15F benchmarks and
  reports were not modified.
- The only snapshot change is an additive test module covering the new
  geometry admission/fallback lifecycle.

## Acceptance fixup decision log (FX-D rules)

**Starting reviewed SHA:** `b120f9f8d63901cd4bdc9bb83fb4462a5b11d6ad`

| Rule | Trigger observed | Action taken | Verification / remaining gate |
|---|---|---|---|
| FX-D01 | Branch HEAD exactly `b120f9f...`; tree clean; expected symbols present | continued on the existing branch; no new PR/branch | preflight SHA/status; FX-A00 PASS |
| FX-D04 | `Index::open_existing` used defaults; `Index::open_with_limits` available | GA-I05 reopens with the saved cloned `IndexLimits` | `ga_i05_*` PASS; FX-A01 |
| FX-D05 | Public 64-KiB case cannot reveal an optional candidate miss | labelled it as limit/correctness proof; added private `g5_02`/`g5_03` observable fallback witnesses | slot/charge/verification assertions; FX-A02 |
| FX-D06 | `ReaderSnapshot` private `for_test`/counters still present | extended in-crate snapshot tests only; no public test API | `g5_02`/`g5_03` PASS; FX-A02 |
| FX-D08 | Valid-envelope bad-column fixture yields `FieldTypeMismatch` | asserted the same typed variant in standalone and metered constructors with zero budget and pristine retry | `u18_*` PASS; FX-A03 |
| FX-D09 | `ContainerBuilder` adds baseline `(1,1)`; original segment carries a duplicate baseline pair | skipped exactly one builder-supplied baseline occurrence and preserved every original tuple | exact feature equality assertion; FX-A03 |
| FX-D14 | Existing `pr13_oracle::real` / `pr13_remote::real` APIs matched | added one dedicated `pr15g_a_rustfs.rs` using the same public APIs | `--no-run` + real local execution; FX-A04 |
| FX-D17 | Valid pinned RustFS image available locally | executed GA-I07 once with `--test-threads=1` | 1 passed; FX-A04 local |
| FX-D19 | Existing CI `rustfs` job/service pinned as inspected | added exactly one invocation in the existing Core remote step | workflow diff; FX-A04/A09 |
| FX-D20 | Existing H06/H07/H09/K01–K05 harnesses present | ran proxy and crash suites against the pinned local service; no new proxy built | 7 proxy, 5 k0, 10× k05 PASS; FX-A05 local |
| FX-D22 | Two fixup tests initially failed from incorrect fixture/assertion assumptions, not production behavior | (1) observed committed generation after a required reopen instead of the created handle's pinned empty view; (2) preserved the original duplicate baseline feature while letting `ContainerBuilder` contribute one baseline | focused tests rerun PASS; FX-A01–A03 |
| FX-D24 | Local QA passed on the final fixup tree | prepared docs/commit/push with fresh logs | FX-A07 |
| FX-D27 | No fresh operator performance authorization | skipped timed A/B; ran only the negative authorization test | P01–P04 BLOCKED; FX-A08 |
| FX-D29 | `gh` credentials invalid | push branch only; report CI blocked and provide compare URL; no fabricated checks | FX-A09 blocked |
| FX-D31 | New RustFS test was executable locally but not in hosted CI at this point | recorded local PASS separately from hosted pending; no `--no-run` counted as acceptance | FX-A04 local / FX-A09 pending |

Not triggered: `FX-D02`/`D03` (branch/base matched), `FX-D07` (allowance
exceeded encoded resident bytes), `FX-D10`–`D13` (fixture/digest/budget/retry
all behaved as contracted), `FX-D15`/`D18` (remote oracle and warm request
count matched), `FX-D16` (pinned service was available), `FX-D23`/`D26`
(no production defect or forbidden-path need), `FX-D28` (no performance run),
`FX-D32` (frozen report unchanged), `FX-D34` (no benchmark measurement).
