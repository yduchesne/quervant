# PR 15C-B acceptance report

Status: **IMPLEMENTATION COMPLETE AND LOCALLY VERIFIED; PERFORMANCE COMPARISON
`UNQUALIFIED`/`DIAGNOSTIC`; CI AND REAL-RUSTFS GATES PENDING AT THE FINAL HEAD;
NOT MERGED.**

## 1. Implementation status

| Deliverable | Status |
|---|---|
| Test-only per-thread FST build counter (`crates/quervant-core/src/search/term_fst.rs`) | **DONE** — global `AtomicU64` replaced with `#[cfg(test)] thread_local! Cell<u64>`; both preflight tests and their `== 0` assertions preserved; new deterministic cross-thread-isolation witness added |
| Strict before/after comparator (`benchmarks/scripts/compare-pr15c-b.py`) | **DONE** — `compare` + `self-test`, standard library only, imports the frozen validator instead of copying it |
| Qualified before/after measurement | **BLOCKED** — `STOP-15CB-01` (see `decisions.md`); a same-host, 3-trial-per-side diagnostic series was executed instead |
| Untimed causal diagnostics | **DONE** — `perf` + `heaptrack` on `absent`/`rare`/`mixed` for both sources |
| Evidence bundle | **DONE** — `preflight.md`, `gates.md`, `comparison.md`/`.json`, `diagnostics.md`, `decisions.md`, `trials/` |
| Production search/planner/scoring/segment-cache change | **NONE** (out of scope and forbidden by the plan) |
| Frozen PR 15B corpus, lanes, oracles, reports, CI threshold, timing region | **UNCHANGED** (`benchmarks/` subtree identical to `origin/main`) |

No optimisation was performed. `Reviewer requires production optimizer changes` is
recorded as a future PR 15C-C candidate, not implemented (rule X35).

## 2. The FST test-only correction and the original CI failure

The failing assertion in
[run 40917513631, job 123601575771](https://github.com/yduchesne/quervant/actions/runs/40917513631/job/123601575771)
was `build_invocations() == 1` in
`search::term_fst::tests::preflight_work_limit_prevents_build`, which asserts `0`.
Mechanism, established from source rather than from a lucky repro: the counter was
a **process-global** `AtomicU64` that two tests reset and then assert, while the
library test binary runs tests in parallel and every `TermFst::build` anywhere in
the process incremented it. That is a genuine cross-test race, not a flake with an
unknown cause.

Fix: `#[cfg(test)] thread_local! { static BUILD_INVOCATIONS: Cell<u64> = const { Cell::new(0) }; }`.
Both tracked builds are synchronous on the calling test thread, so a per-thread
count is an exact witness. `TermFst::build`, its work limits, `preflight_build`,
the two assertions and the rejection behaviour are unchanged.

New deterministic witness `build_invocations_are_thread_local` proves per-thread
isolation instead of relying on scheduler luck: the parent builds one real FST and
observes 1; a spawned thread resets, observes 0, builds a real FST and observes 1;
after `join` the parent still observes 1; the parent then resets and observes 0.

Explicitly **not** done: serialising the suite, weakening assertions, sleeps,
retry-until-green, test exclusion, or any change to FST construction/work limits.
Per rule X09, three green coverage runs do **not** prove the original failure was
flaky; they prove the race is removed.

## 3. Test execution (exact commands and results)

All commands were run by the agent on the host in `preflight.md`. Full matrix and
per-command evidence pointers are in `gates.md`.

| Command | Exit | Result |
|---|---|---|
| `cargo fmt --all -- --check` | 0 | PASS |
| `cargo +1.85.0 fmt --all -- --check` | 0 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| `cargo +1.85.0 check -p quervant-core` | 0 | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `cargo test --workspace --all-features` | 0 | 2173 passed / 0 failed / 75 ignored |
| `cargo +1.85.0 test --workspace --all-features` | 0 | 2173 passed / 0 failed / 75 ignored |
| `cargo test --workspace --all-targets` | 0 | 2169 passed / 0 failed / 10 ignored |
| `cargo test -p quervant-core --test pr15b_diagnostics` | 0 | 16 passed / 0 failed |
| `cargo test -p quervant-core --test pr15c_a_segment_state` | 0 | 5 passed / 0 failed |
| `cargo test -p quervant-core --release --lib` | 0 | 840 passed / 0 failed / 1 ignored |
| `cargo test -p quervant-core --lib search::term_fst::tests::` | 0 | 16 passed / 0 failed |
| `cargo test -p quervant-core --lib index::snapshot::verified_state_cache::` | 0 | 38 passed / 0 failed |
| `cargo doc --workspace --no-deps` | 0 | PASS, 0 warnings |
| `cargo doc --workspace --all-features --no-deps` | 0 | PASS, 0 warnings |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` ×3 | 0,0,0 | **91.81 % lines** each run (51738 lines / 4236–4237 missed) |
| `python3 benchmarks/scripts/validate-pr15b.py self-test` | 0 | `SELF-TEST OK` |
| `python3 benchmarks/scripts/compare-pr15c-b.py self-test` | 0 | `COMPARATOR SELF-TEST OK`, 16 rejection classes |
| `bash benchmarks/scripts/test-scripts.sh` | 0 | 62 passed / 0 failed |
| `git diff --check` | 0 | PASS |

Measured line coverage **91.81 %** ≥ the mandatory 85 % floor. No exclusion, no
lowered threshold, no omitted crate.

## 4. Benchmark qualification — `UNQUALIFIED`, and why

Two clean, detached worktrees on one host (`ext4`, Intel i7-10750H, 12 logical
CPUs, 32 GiB, WSL2) at `42b19445dd79a90d8701b4306e305c6e4e44cd57` (before) and
`b4682d0fdebaa691b55bb29b32f3499781a8fc04` (after), using the **unmodified**
`benchmarks/scripts/run-pr15b.sh --trials 3`, blocks executed **A then B** (order
fixed before measurement).

- 30/30 frozen `pr15b_v1` lanes present in all six trials.
- Correctness oracle gate PASS before timing in all six trials.
- Contention `clear` in all 18 pre/post/final samples.
- Criterion `sample_size(20)`, 3 s warm-up, 5 s measurement.
- Canonical fixture `104d5ef0…` re-verified by the runner.
- Clean trees in both worktrees; no generated data committed.

Two independent reasons prevent a `QUALIFIED` label:

1. **No operator idle attestation** was given (X18: never self-supply it). The
   runner therefore recorded `operator_idle_confirmation = absent`.
2. **`STOP-15CB-01`**: the frozen `validate-pr15b.py` requires a non-empty
   `profiler_evidence` whenever a profiling tool is on `PATH`, and the frozen
   `run-pr15b.sh` never writes one. Profilers were installed on this host after
   the PR 15B qualification, so every trial is structurally unqualified here even
   with the idle attestation supplied (proved in `decisions.md`).

Consequently `comparison.md` is labelled `UNQUALIFIED` and no speedup is claimed.
The three-trial medians are nevertheless real, same-host, same-harness, and
causally attributable because `42b1944 → b4682d0` changes only PR 15C-A production
code and adds no benchmark/CI/manifest change.

## 5. Historical PR 15B result — context only

`benchmarks/reports/pr15b-v1-e8ca1b0-qualified.json` (`source_sha = e8ca1b0…`) is
preserved untouched and is cited only as **historical, separate-run context**.
Its host fingerprint matches this host, but it is a different qualification run and
its latencies are **not** treated as a matched baseline (rule X33). No causal claim
in this PR uses it.

## 6. Comparator evidence

`benchmarks/scripts/compare-pr15c-b.py`:

- Imports `validate-pr15b.py` and reuses `REQUIRED_LANES` and `validate_trial`
  instead of duplicating schema knowledge, so the frozen validator stays
  authoritative and unedited.
- Labels a comparison `QUALIFIED` only on: ≥3 source-identical qualified trials per
  side, real correctness/idle/contention/clean-tree/profiler facts from the trial
  manifests (the aggregate does not expose them, so they are read from source
  trials rather than invented), two distinct full 40-hex SHAs matching the pinned
  before/after revisions, identical host + toolchain + canonical/per-corpus
  digests, the exact 30 lane IDs with matching `N`/`S`/`K`/variant, finite positive
  medians, and aggregate `trial_median_ns` equal to the source trial medians.
- Otherwise emits `UNQUALIFIED` with explicit reasons and no speedup claim.
- Per lane: `speedup = before_MoM / after_MoM`, `delta_pct = 100·(after−before)/before`,
  raw three-trial medians, per-side dispersion, and a predeclared descriptive
  classification (`IMPROVEMENT`/`REGRESSION`/`INCONCLUSIVE`) driven by
  overlap of the trial-median ranges, a 1.10 × dispersion threshold and a 3 %
  effect-size threshold. These are stated heuristics, **not** significance tests.
- Reports every lane grouped by the plan's U01/U02, U03/U04, U05–U10, U11, U12,
  U13 descriptors with group median and range. **No cross-lane arithmetic average**
  and no overall "total speedup" figure is produced.
- Does not auto-fail a slower lane; a regression is reviewer territory.
- `self-test` asserts 16 rejection classes (missing lane, duplicate lane, wrong
  after SHA, wrong before SHA, identical before/after SHA, wrong host, missing
  trial, mismatched corpus digest, corrupted oracle gate, NaN, Infinity,
  nonpositive latency, unqualified aggregate, tampered aggregate medians, fewer
  than three trials, historical-only input) and the ratio identity
  200 ns vs 100 ns ⇒ speedup 2.0, delta −50 %.

## 7. Measurement results (30/30 lanes, DIAGNOSTIC — not a publication claim)

| lane | before MoM (ms) | after MoM (ms) | speedup | delta % | class |
|---|---:|---:|---:|---:|---|
| `pr15b_v1/u01/n100000_s4/k100/absent` | 230.995 | 3.906 | 59.141 | -98.31 | IMPROVEMENT |
| `pr15b_v1/u01/n10000_s4/k100/absent` | 23.356 | 0.442 | 52.849 | -98.11 | IMPROVEMENT |
| `pr15b_v1/u01/n2000_s4/k100/absent` | 4.777 | 0.121 | 39.497 | -97.47 | IMPROVEMENT |
| `pr15b_v1/u02/n100000_s4/k100/rare` | 326.020 | 39.186 | 8.320 | -87.98 | IMPROVEMENT |
| `pr15b_v1/u02/n10000_s4/k100/rare` | 32.298 | 3.535 | 9.138 | -89.06 | IMPROVEMENT |
| `pr15b_v1/u02/n2000_s4/k100/rare` | 6.585 | 0.759 | 8.673 | -88.47 | IMPROVEMENT |
| `pr15b_v1/u03/n100000_s4/k100/medium` | 669.264 | 378.641 | 1.768 | -43.42 | IMPROVEMENT |
| `pr15b_v1/u03/n10000_s4/k100/medium` | 36.933 | 8.067 | 4.578 | -78.16 | IMPROVEMENT |
| `pr15b_v1/u03/n2000_s4/k100/medium` | 8.840 | 1.875 | 4.716 | -78.79 | IMPROVEMENT |
| `pr15b_v1/u04/n100000_s4/k100/common-mixed` | 743.932 | 456.926 | 1.628 | -38.58 | IMPROVEMENT |
| `pr15b_v1/u04/n10000_s4/k100/common-mixed` | 37.622 | 8.560 | 4.395 | -77.25 | IMPROVEMENT |
| `pr15b_v1/u04/n2000_s4/k100/common-mixed` | 7.192 | 1.403 | 5.125 | -80.49 | IMPROVEMENT |
| `pr15b_v1/u05/n10000_s4/k100/cidr-time` | 33.687 | 4.633 | 7.271 | -86.25 | IMPROVEMENT |
| `pr15b_v1/u06/n10000_s4/k100/json-scalar` | 38.432 | 9.533 | 4.032 | -75.20 | IMPROVEMENT |
| `pr15b_v1/u07/n10000_s4/k10/sort-n` | 34.526 | 5.780 | 5.973 | -83.26 | IMPROVEMENT |
| `pr15b_v1/u07/n10000_s4/k100/sort-n` | 37.107 | 8.264 | 4.490 | -77.73 | IMPROVEMENT |
| `pr15b_v1/u07/n10000_s4/k1000/sort-n` | 67.367 | 37.472 | 1.798 | -44.38 | IMPROVEMENT |
| `pr15b_v1/u08/n10000_s4/k100/fields-host-n` | 37.028 | 8.197 | 4.517 | -77.86 | IMPROVEMENT |
| `pr15b_v1/u08/n10000_s4/k100/source` | 36.872 | 8.164 | 4.516 | -77.86 | IMPROVEMENT |
| `pr15b_v1/u09/n10000_s4/k100/aggregate-host` | 43.895 | 15.261 | 2.876 | -65.23 | IMPROVEMENT |
| `pr15b_v1/u10/n10000_s4/k100/serial-batch` | 116.960 | 28.637 | 4.084 | -75.52 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s1/k100/common-mixed` | 74.485 | 29.142 | 2.556 | -60.88 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s1/k100/rare` | 57.349 | 11.439 | 5.014 | -80.05 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s16/k100/common-mixed` | 29.517 | 4.618 | 6.392 | -84.35 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s16/k100/rare` | 26.661 | 1.835 | 14.532 | -93.12 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s4/k100/common-mixed` | 37.301 | 8.688 | 4.293 | -76.71 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s4/k100/rare` | 32.393 | 3.539 | 9.154 | -89.08 | IMPROVEMENT |
| `pr15b_v1/u12/n10000_s4/k100/page-1` | 36.933 | 8.211 | 4.498 | -77.77 | IMPROVEMENT |
| `pr15b_v1/u12/n10000_s4/k100/page-2` | 37.094 | 8.282 | 4.479 | -77.67 | IMPROVEMENT |
| `pr15b_v1/u13/geo_n8_s1/k100/geo-bbox` | 0.051 | 0.010 | 5.146 | -80.57 | IMPROVEMENT |

All 30 lanes are classified `IMPROVEMENT`; no lane regressed. Per-side dispersion
(`max/min` of the three trial medians) is ≤ 1.064 on every lane, so no lane trips
the predeclared noise threshold. Group descriptors (descriptive medians/ranges,
individual lanes visible above):

| group | lanes | speedup median | speedup min | speedup max |
|---|---:|---:|---:|---:|
| U01/U02 no/rare hits | 6 | 24.317 | 8.320 | 59.141 |
| U03/U04 lexical mixed | 6 | 4.487 | 1.628 | 5.125 |
| U05–U10 typed/JSON/sort/projection/aggregation/batch | 9 | 4.490 | 1.798 | 7.271 |
| U11 segment topology | 6 | 5.703 | 2.556 | 14.532 |
| U12 PIT pages | 2 | 4.488 | 4.479 | 4.498 |
| U13 geo | 1 | 5.146 | 5.146 | 5.146 |

Interpretation limits (mandatory):

- An `UNQUALIFIED` comparison **must not** be quoted as a speedup claim. The
  numbers above are descriptive medians of three independent trials on one WSL2
  host; they are not production p95/p99, not an SLA, and not extrapolable.
- The two slowest-improving lanes are the 100 K selective/quasi-selective lexical
  lanes (U03 −43.4 %, U04 −38.6 %) and `sort-n k1000` (−44.4 %), i.e. the lanes
  where residual postings traversal/scoring dominates after verification is
  removed. They remain large improvements and none regressed.
- `U11 n10000_s1` remains the slowest `common-mixed` topology after the change
  (29.1 ms vs 8.7 ms at S=4). Recorded as an observation and a PR 15C-C candidate;
  **not** investigated or optimised here.

## 8. Instrumented causal evidence (summary; details in `diagnostics.md`)

- **Before**, `absent`: `UnifiedSearcher::search` → `collect_mixed` →
  `ReaderSnapshot::open_segment_reader` (96.37 % inclusive) → `SegmentReader::open`
  (95.28 %) → `format::parse_container` (81.91 %) → `sha2` compress **82.65 % of
  self time**. Whole-segment re-verification per reader acquisition dominates.
- **After**, the same three frames do not appear in the profile report at all;
  the flat leaders are residual column reads (13.3 %), lexical evaluation (13.0 %)
  and column open (12.6 %).
- The residual 4.79 % `sha2` in the after profile is
  `analysis::registry::AnalyzerDefinition::fingerprint` during query planning, not
  segment verification.
- `heaptrack`, normalised per query (the fixed 20 s loop completes far more
  iterations after the change, so absolute totals are not comparable):
  allocation calls/query `absent` 54 006 → 1 318 (−97.6 %), `rare` 93 660 →
  27 641 (−70.5 %), `mixed` 122 410 → 55 612 (−54.6 %); temporary
  allocations/query `absent` 25 229 → 121 (−99.5 %), `rare` 31 951 → 526
  (−98.4 %), `mixed` 45 448 → 13 737 (−69.8 %).
- Peak heap 16.03 M → 15.88 M; the 544 B pre-existing leak is unchanged. Retained
  memory did not grow, consistent with the VSR-G2 charge-release contract.

## 9. CI, RustFS and reviewer status

| Gate | Status |
|---|---|
| Local `rust`-equivalent gate set (fmt, clippy default+all-features, tests default+all-features, coverage ≥85 %, docs, bench build, script tests, whitespace) | **PASS** |
| Local `msrv`-equivalent gate set (fmt, clippy all-features, all-features tests at 1.85.0) | **PASS** |
| GitHub Actions `rust` at the final head | **NOT RUN — BLOCKED-EXTERNAL** (agent cannot push) |
| GitHub Actions `msrv` at the final head | **NOT RUN — BLOCKED-EXTERNAL** |
| GitHub Actions `rustfs` (real RustFS) at the final head | **BLOCKED-ENVIRONMENT** locally; **NOT RUN** in CI. Not a pass. |
| Reviewer acceptance | **NOT GIVEN** |
| Merge / roadmap DONE | **NOT UPDATED** — no merge, no release, no roadmap DONE claim |

## 10. Residual risks and limitations

1. **`STOP-15CB-01`** — no qualified aggregate is obtainable with the frozen
   runner/validator pair on a profiler-equipped host. Until amended, PR 15C-B's
   performance evidence stays diagnostic.
2. **No operator idle attestation** — the series is diagnostic even independently
   of (1). Contention detection is best-effort and cannot observe Windows-host or
   other WSL guests.
3. **Single host, WSL2** — CPU frequency/thermal behaviour under WSL2 is not
   controlled; absolute latencies are host-specific.
4. **`perf` version mismatch** — the working user-space binary is 6.8.12 against a
   6.18 kernel; attribution is usable but reproducibility is caveated.
5. **Optional reverse-order paired series not executed** — order sensitivity is
   untested; the A→B order was fixed before measurement and is recorded.
6. **No cache-hit ratio, no universal SHA/decode counters, no cold-acquisition
   lane, no RustFS cost measurement** — all recorded as `NOT MEASURED` rather than
   approximated.
7. **`docs/TESTING.md` still contains pre-existing merge-conflict markers** at
   lines 56–59 (predates this branch). Deliberately not repaired per the plan.
8. **CI and real-RustFS must pass at the final head** before any merge decision.

## 11. PR 15C-C candidates (recommendations only — not implemented)

1. Authorise an amendment resolving `STOP-15CB-01` so a qualified aggregate can be
   produced on a profiler-equipped host.
2. Re-evaluate whether `profiler_status` should describe the *qualification host*
   rather than the tool probe, and record real profiler artifact paths.
3. Investigate residual per-query column open/read cost (`ColumnReader::open_with_doc_count`
   ~12.6 %, `read_u64_at` ~13.3 % of after self time).
4. Investigate per-request analyzer-fingerprint hashing in query planning
   (residual 4.79 % SHA-256 self time).
5. Investigate the `S=1` `common-mixed` topology outlier (29.1 ms at S=1 vs 8.7 ms
   at S=4 after the change).
6. Investigate the residual live-doc `BTreeSet` materialisation/teardown (7.4 %).

## 12. Draft PR description

> **PR 15C-B — verified segment-state reuse performance qualification + FST test
> isolation**
>
> **What this does**
>
> 1. **Test-only fix (`crates/quervant-core/src/search/term_fst.rs`).** The
>    preflight build counter was a process-global `AtomicU64` reset and asserted by
>    two tests while the parallel test binary incremented it from other tests —
>    the cross-test race behind the post-merge CI failure
>    `build_invocations() == 1` in `preflight_work_limit_prevents_build`. It is now
>    a `#[cfg(test)] thread_local! Cell<u64>`; both tests and their `== 0`
>    assertions are unchanged, and a new deterministic witness
>    (`build_invocations_are_thread_local`) proves per-thread isolation. No
>    production counter, no serialisation, no weakened assertions, no test
>    exclusion. Verified by three independent runs of
>    `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85`
>    (91.81 % lines, ≥ 85 % floor).
> 2. **Strict comparator (`benchmarks/scripts/compare-pr15c-b.py`).** Standard
>    library only; imports the frozen `validate-pr15b.py` rather than editing it.
>    Refuses to label a comparison `QUALIFIED` without ≥3 source-identical
>    qualified trials per side, exact 30-lane/metadata equality, matching host and
>    toolchain fingerprints, matching canonical/corpus digests, two distinct full
>    SHAs matching the pinned before/after revisions, and trial-derived
>    correctness/qualification facts. `self-test` covers 16 rejection classes plus
>    the 200 ns/100 ns ratio identity. No cross-lane average, no significance
>    claim.
> 3. **Evidence bundle (`docs/pr-artifacts/pr-15c-b/`).** Preflight/provenance,
>    full gate log, `UNQUALIFIED` comparison report + machine-readable JSON,
>    instrumented diagnostics, decision log, six source-locked trial manifests,
>    and this acceptance report.
>
> **Exact sources**
>
> - Before (pre-PR-15C-A): `42b19445dd79a90d8701b4306e305c6e4e44cd57` — first
>   parent of the PR 15C-A merge `93a9980`; `SegmentSnapshot::open_reader` clones
>   the segment bytes and re-enters `SegmentReader::open` per acquisition there.
> - After: `b4682d0fdebaa691b55bb29b32f3499781a8fc04` (executable tree
>   `eb49bd4c…`; `crates/` `ad1a756c…`, `benchmarks/` `56eaf9cf…`).
> - **Source-hash workload invariant:** `git diff --stat 42b1944 b4682d0 --
>   benchmarks/ crates/quervant-core/benches crates/quervant-core/examples
>   Cargo.toml Cargo.lock` is **empty**, so both sources run the byte-identical
>   frozen `pr15b_v1` harness, lanes, oracle and timing region.
>
> **Qualification result — `UNQUALIFIED` (no speedup claim)**
>
> Six trials (3 per side), 30/30 lanes, correctness PASS, contention `clear` in
> all 18 samples. Two independent blockers: no operator idle attestation was
> available, and `STOP-15CB-01` — the frozen `validate-pr15b.py` requires
> `profiler_evidence` when a profiler is on `PATH` while the frozen
> `run-pr15b.sh` never records it, so no qualified aggregate can be produced on
> this host. All raw evidence retained. Diagnostic medians show 30/30 lanes
> improving, no regressions (full 30-lane table in
> `docs/pr-artifacts/pr-15c-b/acceptance.md`, with per-trial medians and
> dispersion).
>
> **Instrumented attribution.** Before: `open_segment_reader` 96.4 % (absent),
> `parse_container` 81.9 %, `sha2` 82.7 % of self time — whole-segment
> re-verification per reader acquisition. After: those frames are absent from the
> profile; the residual SHA-256 is analyzer fingerprinting in query planning.
> Allocations per query drop 97.6 %/70.5 %/54.6 % (`absent`/`rare`/`mixed`);
> peak heap is flat at ~15.9 M.
>
> **Frozen artifacts untouched:** no change to `pr15b_v1`, the 30 lane IDs, the
> oracle fixtures, `benchmarks/reports/pr15b-*`, the CI coverage threshold or the
> benchmark timing region; `benchmarks/` is identical to `origin/main`.
>
> **Gates:** local `rust` and `msrv` equivalent gate sets PASS (incl. 91.81 % line
> coverage, 3 independent runs). GitHub `rust`/`msrv`/`rustfs` at the final head
> are **not yet run** and are required before merge.
>
> **Residual risks / not measured:** `STOP-15CB-01`; no idle attestation; single
> WSL2 host; `perf` 6.8.12 vs kernel 6.18; no engine-wide cache-hit ratio, no
> universal SHA counters, no cold-acquisition lane, no RustFS cost claim; optional
> reverse-order series not executed; pre-existing `docs/TESTING.md` conflict
> markers left untouched.
>
> **Not merged, not released, roadmap not marked DONE.**
