# PR 15B decision record

Every entry names the plan rule, the observable fact, the action and its scope.
No rule was invented and no gate was waived. Unmatched situations would have
been X99 hard stops; none occurred.

| Rule | Observable fact | Action | Scope |
|---|---|---|---|
| X01 | PR15A `pr15a_v1.json` exists on fresh main with SHA-256 `104d5ef0…d087` | Reused unchanged; digest asserted before every run | Fixture and oracle |
| X03 | Repository already uses explicit Criterion 0.7.0 `harness=false` targets | Added exactly one new target `unified_diagnostics` in the existing style | `crates/quervant-core/Cargo.toml` |
| X04 | Default `IndexLimits` pending bounds reject 25K-document range commits before query | Used documented fixture-only builders (`max_pending_docs`, `max_pending_bytes`, `max_snapshot_bytes`, `max_segments_per_commit`); search limits and production defaults untouched | Fixture build |
| X06 | `QUERVANT_PR15B_LARGE` and `QUERVANT_PR15B_SEG64` are not enabled for the published campaign | U14 is `NOT RUN (OPTIONAL)` and excluded from the required aggregate | U14 |
| X09 | Canonical golden fixture and the new generator formula agree with the static table | Benchmark and test oracle gates execute | All lanes |
| X12 | `UnifiedSearcher::search` and `execute_batch_pinned` directly express every required lane | Used unchanged; no adapter or alternate executor | U01–U12 |
| X13 | `Projection::None` is absent from the approved public contract | U08 runs `Source` and `Fields(host,n)`; the `None` variant is `NOT RUN`; no API was added | U08 |
| X16 | Shared helper imports are compatible, so one benchmark-only module is shared by bench, test and example via `#[path]` | `benches/unified_diag_common/mod.rs` is the single generator/oracle implementation | Fixture/oracle |
| X17 | Example can include the benchmark-only helper by explicit path | `examples/pr15b_profile.rs` shares the exact request constructors and fixture | Profiling driver |
| X18/X20 | The unified executor has no existing private diagnostic seam that can count `segments_visited`, `candidates_examined`, `documents_decoded`, `sort_comparisons`, `group_updates` or `logical_memory_peak_bytes` without changing private signatures or adding TLS/globals | Those fields are `NOT INSTRUMENTED` (`None`), never zero | Counter slice |
| X19 | `selected_hits` and `projection_fields` are directly observable from the authoritative production response vectors | Implemented as test-only, compile-out counters in `src/search/diagnostics.rs` behind `#![cfg(test)]`; adversarial unit tests pass | Mandatory minimum counters |
| X22 | `perf`, `cargo-flamegraph` and `heaptrack` are all absent | Wrapper returns nonzero `UNAVAILABLE` for each mode; exact commands/status recorded | Profiling |
| X25 | Implementation is uncommitted before the qualification campaign would start | Qualification is run only from a clean commit; a dirty-tree trial is retained only as diagnostic evidence | Qualification |
| X26/X41 | Contention/unknown or missing idle attestation prevents qualification | Runner/validator reject such a trial from the aggregate | Qualification |
| X29 | Approved contention detector exists | Reused `benchmarks/scripts/check-pr07-contention.py`; no second detector was written | Qualification |
| X38 | Only documentation/report files change after a qualified campaign | Executable/content hashes are unchanged; docs-only follow-up does not invalidate the trial source lock | Qualification |
| X39 | Timings expose apparent full-corpus scaling, segment-topology effects and top-K cost | Recorded only as PR15C candidates; no production source was changed | Analysis |
| X42 | U01 absent query returns zero hits | Total `0` and empty hit vector preserved; no positive result invented | U01 |
| X43 | Criterion 0.7 writes `full_id` in `benchmark.json` but sanitizes directory names | Validator reads the authoritative `full_id` and requires the pinned 0.7 field set; self-test covers parsing | Qualification |
| X44 | Profilers unavailable but Rust tests and Criterion run | Continued Rust/Criterion work; external profiler harness reported unavailable | Profiling |
| X45 | Benchmark target is built through `cargo bench` | Release bench profile confirmed; no debug/test timing is published | Timing |
| X49 | One U09 response emits multiple host groups | Group cardinality (global exact-distinct host) and per-group count/sum are reported separately | U09 |

## Contract-preservation decisions

1. **Half-open time range.** The plan's U05 prose says "inclusive time range".
   The approved production contract is half-open `[start, end)`. The workload
   uses the production contract and the independent oracle uses `i >= N/4 &&
   i < N/2`. No production semantic was changed. A future inclusive contract
   would require a separate approved semantic change and a new workload version.
2. **Typed identity `n == 0`.** `Query::Term` on `n` is a typed rejection
   (`term_on_non_lexical_field`), so U02 uses the existing typed `Query::In`
   form. The logical predicate and exact one-hit oracle are unchanged.
3. **U09 global distinct.** `ExactDistinct` is a per-group metric in the public
   aggregation contract. The global exact-distinct host count is the grouped
   response's cardinality, which is independently known to be 3. It is reported
   as a separate validation value rather than mislabelling a per-group metric.
4. **Branch name.** The reused branch is `dev/pr15b-unified-search-diags` at the
   exact verified main commit rather than the plan's illustrative
   `test/pr15b-unified-diagnostics`. No `main` commit was made.
