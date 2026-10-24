# PR 14B — correctness traceability (B01–B21, G01–G03)

Every assertion below is test-owned. The production comparator/aggregator is
never used to compute an expected result. "Real" means the case ran against the
pinned RustFS 1.0.1 service documented in
[environment-and-commands.md](environment-and-commands.md); "Local" means real
`FsDirectory`/`MemoryDirectory` with the real engine.

| ID | Invariant | Test symbol | Independent assertion | Topology | Outcome |
|---|---|---|---|---|---|
| B01 | Local and real-RustFS are logically equivalent for an identical committed corpus/query | `real::r02_r04_r06_real_cold_compound_equivalence` | `assert_unified_equal` plus explicit `n`-ascending keys `d0,d1,d3,d5`, `total_hits=4`, host groups `h1=3/90`, `h2=1/40`; cold reader opens generation 2 with no writer-local files | Real + local | PASS |
| B02 | Mixed lexical/JSON/IP/geo nested Boolean and score semantics | `real::b02_real_mixed_boolean_and_relevance_order` | Two survivors only; order `zfew,aonce`; key order is `aonce,zfew`; scores descending; local == remote | Real + local | PASS |
| B03 | Five-state projection, tie ordering and JSON-path numeric sort | `b03_local_json_path_sort_and_projection_table`, extended `r07_local_states_and_tie_order` | `$.k` descending `d5,d4,d3,d2,d1,d0`; ExplicitNull/Multi/Empty/Absent projections; stable repeat | Local (real engine) | PASS |
| B04 | Remote cold bootstrap with no writer-local state | `real::r01_separate_process_cold_bootstrap` + `p4_child_bootstrap` | Separate process reopens only the committed prefix, sees generation 2, reruns the exact oracle; workspace removed first | Real, separate process | PASS |
| B05 | No adjacent-prefix/generation substitution | `real::r03_wrong_generation_is_not_substituted` | Prefix A generation 2 / 6 docs vs prefix B generation 1 / 1 doc; each reader sees only its own committed data | Real | PASS |
| B06 | Public PIT pagination returns each key exactly once in deterministic order | `real::b06_b07_real_pinned_batch_search_after` | Page sizes 1 and 2 both concatenate to `d0..d5`; terminal cursor `None`; page count `ceil(6/page_size)`; aggregation identical on every page | Real, live `PitHandle` | PASS |
| B07 | Stale/expired/wrong-PIT and changed query/sort fail typed | same test | Wrong handle → `InvalidBatch(ConflictingPit)`; `now == expires_at` → `ExpiredCursor`; changed query/sort → `InvalidQuery(CursorSortMismatch)`; failures emit no cursor | Real | PASS |
| B08 | Old pinned generation is unaffected by mutation/refresh/commit/reopen | `real::r05_real_mutation_old_and_new_snapshot` | Retained old pin reports the same ordered 6 keys (including `d2`) after upsert+delete+commit and after a cold reopen | Real | PASS |
| B09 | A newly pinned reader sees the new committed generation | same test | New pin after cold reopen reports 5 keys and excludes `d2`; old pin still reports 6 | Real | PASS |
| B10 | Aggregation and ordered batch outcomes are preserved remotely | `real::r08_r09_r15_real_batch_aggregation_and_cursor` | Local == remote slot outcomes, `total_hits`, aggregation and hit order; slot 0 aggregation present with `≤1` hit | Real + local | PASS |
| B11 | A failing middle slot does not erase siblings | `real::r08_r09_r15...`, `real::b06_b07...`, `real::r10_r11...` | Positional `Success/Failure/Success` is preserved; slot 2 equals slot 0's page | Real | PASS |
| B12 | Exact logical ceilings succeed for all three batch kinds | `real::r10_r11_real_remote_budget_exact_and_one_over` | Binary-searched exact `BatchMemoryBytes`, `BatchResponseBytes`, `BatchAggregate` limits all succeed, plain and pinned-cursor paths | Real | PASS |
| B13 | One-under fails typed and does not leak; cancellation is typed | same test | One-under fails with the matching `BudgetExceeded{kind}`; cancellation after a prior success yields `Cancelled{ClientCancellation}` for later slots with ordered sibling outcomes | Real | PASS |
| B14 | Cache is disposable; warm/cold reopen equivalent | `real::r13_r14_warm_evict_and_pinned_reader` | Warm reopen equals the first read; reload after releasing pins equals the original hits | Real | PASS |
| B15 | Pinned bytes are not unsafely evicted; tiny cache fails closed | same test | A cache capacity that cannot hold pinned bytes makes the open fail (`is_err`) rather than evict; reopen succeeds after pin release | Real | PASS |
| B16 | Publication/recovery never exposes a wrong/partial generation | `pr13_remote_proxy::h10/h11`, `pr13_crash_rustfs::k03/k04` | Dropped CAS response reconciles to the applied generation; blocked CAS → `RecoveryRequired` and terminal writer; crash before/after CAS leaves the last committed generation readable | Real + fault proxy/checkpoints | PASS (3 repeats for h10/h11/k03/k04) |
| B17 | Faults are typed and a clean retry succeeds | `pr14_storage_faults::f01..f09_f10`, `pr13_remote_proxy::h06..h09`, `pr13_crash_rustfs::k01/k02/k05` | Transient GET retried; persistent 503 bounded; 403 not retried; truncated/corrupt range rejected; interrupted fill never promoted; healthy reopen equals the oracle | Real + HTTP fault proxy / SIGKILL | PASS (10 unique-prefix iterations per case) |
| B18 | Supported historical JSON format retains query semantics | `b18_b19_historical_json_segment_compatibility`, `real::b18_real_historical_json_remote` | Frozen PR 11 golden (`0528a62c…a02f`) opens; current writer reproduces it byte-for-byte; `$.v` exists/equals table `a,b` / `b`; stored projections `{"v":1}`,`{"v":2}`; remote authoritative object is the same bytes | Local + real | PASS (see [compatibility-evidence.md](compatibility-evidence.md)) |
| B19 | Corrupt/unsupported formats reject typed, no silent reinterpretation | `b18_b19_historical_json_segment_compatibility` | A flipped payload byte is rejected; major version 2 → `UnsupportedFormatVersion{major:2,minor:0}` | Local (real codec) | PASS |
| B20 | High-occurrence JSON temporary allocation is measured, not misrepresented | `pr14b_json_memory::b20_b21_json_occurrence_memory_characterization` | Occurrences 1/128/4096: logical `BatchMemoryBytes` constant at 112; tracked heap peak 33675 / 110392 / 2518968 bytes | Local, child process | PASS (characterization) |
| B21 | Constrained JSON budget stays typed while transient heap is observed separately | same test | One-under fails `BatchMemoryBytes` typed while tracked peak is 33104 / 41233 / 303121 bytes and still grows with occurrences; tracked exact peak > logical boundary at 4096 | Local, child process | PASS (risk open, see [resource-risk.md](resource-risk.md)) |
| G01 | Tests ran against a pinned RustFS, not a fake | Provider inventory + health | Image digest `sha256:1803faef…6a3c`; `/health` reports `1.0.1`; all real cases listed individually in [environment-and-commands.md](environment-and-commands.md) | Real | PASS |
| G02 | Accepted/code SHA is recorded | This evidence set | Code/test commit `556621a5414673d3355e57fb2b2f4fb09135c54b`; gates in [implementation-evidence.md](implementation-evidence.md) | Process | PASS |
| G03 | Skipped/ignored reconciliation | Case inventory | Default suite: 10 ignored; all-features: 71 ignored; every required provider case executed individually with `--ignored --exact`; children only via parents; no required case left unexecuted | Process | PASS locally; **CI run open** |

## Negative and failure-state coverage

- Naked `execute_batch` with any PIT/cursor → typed
  `InvalidBatch(PinnedContextRequired)` (preserved negative regression).
- Wrong handle vs shared PIT → `ConflictingPit`.
- Expired cursor at exactly `expires_at` → `ExpiredCursor`; deadline admission
  is enforced before slots.
- Changed query or sort against a cursor → `CursorSortMismatch`.
- One-under memory/response/aggregate → typed `BudgetExceeded{kind}`.
- Cancellation → `Cancelled{ClientCancellation}` with prior siblings preserved.
- Corrupt segment byte / unsupported format version → typed codec rejection.
- Truncated/corrupt remote transfer → no partial index; healthy retry equals the
  committed oracle.

## Provider-vs-local distinction

| Class | Cases |
|---|---|
| Real provider required | B01, B02, B04–B11 (where marked Real), B12–B17 fault/recovery, B18 remote |
| Local real engine | B03, B18 local, B19, B20, B21 |
| Supplemental fault probe (not a substitute) | HTTP fault proxy (`support::Proxy`) in front of real RustFS, and the tracking allocator in the B20/B21 child |

No mandatory real-boundary assertion is satisfied only by a fake or mock.
