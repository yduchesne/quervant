# PR 15B final acceptance report

**Result state:** IMPLEMENTED / QUALIFIED / AWAITING INDEPENDENT SOURCE REVIEW AND
MAINTAINER ACCEPTANCE. PR 15B is **not DONE**. v0.1 is **NOT RELEASED**.

## 1. Source base and validated head

| Item | Value |
|---|---|
| Required base | fresh `main` at `e3e989e0bf3736a8a2d6f2493b240209e008b2be` (PR 15A/#72) |
| Validated executable source | `e8ca1b03420e1ffe8cb19fafac06b2fe8082866b` |
| Profiling amendment base | `5668d6ef285fdff72b01072327f46a449ed104f2` (adds only `install.sh`) |
| Branch | `dev/pr15b-unified-search-diags` |
| Later changes | profiling script correction (P4-X11) plus documentation/report summaries; executable benchmark/search source unchanged |
| Working tree at final local gates | clean before the evidence-only amendment commit |

The three-trial Criterion campaign ran from the clean `e8ca1b0` commit. The
profiling amendment measured the same executable benchmark/example source and
did not rerun or overwrite the qualified Criterion trials. The final PR head
adds only the profiling-script fix, concise evidence and PR artifact documents.

## 2. Phase status

| Phase | Status |
|---|---|
| P0 freshness/feasibility preflight | IMPLEMENTED, EXECUTED, VERIFIED |
| P1 synthetic generator and independent oracle | IMPLEMENTED, EXECUTED, VERIFIED |
| P2 Criterion unified whole-query benchmark | IMPLEMENTED, EXECUTED, VERIFIED |
| P3 counter feasibility and safe minimal hooks | IMPLEMENTED (minimum met); broader stage counters `NOT INSTRUMENTED` and scoped |
| P4 profiler wrapper and qualification harness | IMPLEMENTED, EXECUTED; qualification QUALIFIED; profiling amendment **MEASURED** CPU/allocation evidence |
| P5 analysis, documentation, submission | ANALYSIS/DOCS COMPLETE; external CI/review `PENDING` |

## 3. Files changed

Production `src/` changes (test-only instrumentation; no search semantics):

- `crates/quervant-core/src/search/diagnostics.rs` (new, test-only module)
- `crates/quervant-core/src/search/mod.rs` (`#[cfg(test)] mod diagnostics;`)

Benchmark/test/example/script/documentation changes:

- `crates/quervant-core/Cargo.toml` (one new `unified_diagnostics` bench target)
- `crates/quervant-core/benches/unified_diagnostics.rs` (new)
- `crates/quervant-core/benches/unified_diag_common/mod.rs` (new)
- `crates/quervant-core/tests/pr15b_diagnostics.rs` (new)
- `crates/quervant-core/examples/pr15b_profile.rs` (new)
- `benchmarks/scripts/run-pr15b.sh` (new)
- `benchmarks/scripts/profile-pr15b.sh` (new; profiling-amendment P4-X11 correction for flamegraph debuginfo and isolated perf.data)
- `benchmarks/scripts/validate-pr15b.py` (new)
- `benchmarks/workloads/pr15b_v1.md` (new)
- `benchmarks/README.md` (PR 15B section)
- `benchmarks/reports/pr15b-v1-e8ca1b0-*.json/.md` (new summaries)
- `docs/pr-artifacts/pr-15b/*.md` (new acceptance dossier)

No `Cargo.lock`, dependency, public contract, codec, manifest, budget or search
semantics change.

## 4. Fixture provenance and topology

| Corpus | Rows SHA-256 | Corpus SHA-256 | Physical S | Documents |
|---|---|---|---|---|
| `n2000_s4` | `0974a1d9…609d4` | `1dc740a0…299a1` | 4 | 2000 |
| `n10000_s1` | `0d88e80f…0f755` | `12c4b0f8…1de5` | 1 | 10000 |
| `n10000_s4` | `0d88e80f…0f755` | `b0b2a796…62fb` | 4 | 10000 |
| `n10000_s16` | `0d88e80f…0f755` | `e7b4a7af…1996` | 16 | 10000 |
| `n100000_s4` | `6397dc25…18fef` | `79c588f5…9fe32` | 4 | 100000 |
| `geo_n8_s1` | `588b32aa…2efa2` | `588b32aa…2efa2` | 1 | 8 |

Full digests are in `benchmarks/reports/pr15b-v1-e8ca1b0-qualified.json` and each
trial manifest. The canonical `pr15a_v1` digest
`104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087`
was asserted in every run.

## 5. Oracle gates

| ID | Status | Evidence |
|---|---|---|
| B-T01 canonical digest + row constants | PASS | `pr15b_diagnostics` |
| B-T02 deterministic generator digests | PASS | row/corpus digest repeat and sensitivity |
| B-T03 exact N/S physical topology + invalid inputs | PASS | 2K 1/4/16 segment builds; invalid shapes rejected |
| B-T04 absent/rare/medium/mixed + wrong-set rejection | PASS | exact formula totals and negative gate |
| B-T05 CIDR/time/JSON + family boundary | PASS | exact ordered prefix; `/0` ≠ `/24`; IPv6 excluded |
| B-T06 sort K=10/100/1000 + host ties | PASS | exact prefix and host tie order; shuffled expectation rejected |
| B-T07 projection states + unstored error | PASS | exact null/absent/empty; typed `UnstoredProjection` |
| B-T08 group count/sum/distinct + zero-match | PASS | exact groups; empty groups on absent query |
| B-T09 3-slot batch + invalid middle slot | PASS | standalone equality; sibling success preserved |
| B-T10 pinned pages + wrong PIT/expired deadline | PASS | full concatenation; typed rejections |
| B-T11 geo oracle + outside bbox | PASS | real geo query, exact set, empty outside |
| B-T12 counter positive control + test-only | PASS | 7 inline unit tests; no public symbol |
| B-T13 validator self-test | PASS | all rejection classes + aggregation rules |
| B-T14 profiling CLI contract | PASS | all 7 workload names; invalid workload/seconds rejected |
| B-T15 historical targets remain | PASS | all 9 pre-existing bench targets + new target compile |
| B-T16 oracle precedes timing/metadata | PASS | gate runs before groups; wrong set rejected |

## 6. Benchmark cases

U01–U13 all executed as required at their specified `N/S/K`; 30 required lanes.
U13 is the separate `geo_n8_s1` provenance lane. U14 was **NOT RUN (OPTIONAL)**
because `QUERVANT_PR15B_LARGE` and `QUERVANT_PR15B_SEG64` were not enabled.

Exact values and dispersion: `benchmarks/reports/pr15b-v1-e8ca1b0-qualified.json`
and `.md`. Workload contract: `benchmarks/workloads/pr15b_v1.md`.

## 7. Three qualified trials

| Trial | Source SHA | Clean | Contention | Idle attestation | Oracle | Lanes | Samples |
|---|---|---|---:|---|---|---:|---:|
| trial-1 | `e8ca1b0…` | yes | clear | yes | PASS | 30 | 20 |
| trial-2 | `e8ca1b0…` | yes | clear | yes | PASS | 30 | 20 |
| trial-3 | `e8ca1b0…` | yes | clear | yes | PASS | 30 | 20 |

Validator: `validate-pr15b.py trial` + `aggregate`; aggregate qualified, same
source SHA, same fixture digests, no missing lane. Median dispersion across lanes:
1.005–1.092. Raw Criterion output is preserved under ignored `target/pr15b/` and
is not committed.

## 8. Release build confirmation

- `cargo +stable bench -p quervant-core --bench unified_diagnostics --no-run`
  compiled the **bench (release-optimized)** profile.
- `cargo +stable bench --workspace --no-run` compiled all ten pre-existing/new
  targets in the bench profile.
- The profiling example was built with
  `CARGO_PROFILE_RELEASE_DEBUG=1 cargo build --release -p quervant-core --example pr15b_profile`.
- No debug/test timing is published.

## 9. Profilers, profiling evidence and counters

| Profiler | Original state | Amendment state | Evidence |
|---|---|---|---|
| perf | UNAVAILABLE (not installed) | **MEASURED** via installed `perf 6.8.12`; `/usr/bin/perf` wrapper fails for the WSL kernel | 20 s `perf record -g --call-graph dwarf`, ~80K samples per workload; `absent` repeat 82.75/82.83% SHA-256 self |
| cargo-flamegraph | UNAVAILABLE (not installed) | **MEASURED** (`flamegraph 0.6.14`) | SVG artifacts for absent/rare/mixed/sort/aggregation; small lost-chunk counts recorded |
| heaptrack | UNAVAILABLE (not installed) | **MEASURED** (`heaptrack 1.5.0`) | allocation counts, cumulative allocated bytes, peak live heap, temporary allocations |

CPU and allocation attribution is now **MEASURED** for the supported priority
workloads at 10K/4. The dominant measured result is that every query re-opens
and re-verifies every segment: SHA-256 envelope verification is 55.53%–82.75% of
self CPU samples, and the segment JSON-path/reader-open path dominates repeated
allocations. The 100K and `medium`/`common` lexical lanes have **no approved
profiling entrypoint** and remain unprofiled. Full details, limitations and
artifact paths: `profile-attempts.md`; concise source-locked summary:
`benchmarks/reports/pr15b-profiling-e8ca1b0.json`.

The profiling amendment does **not** convert the unavailable stage counters into
measured counters:

| Counter | Status |
|---|---|
| `selected_hits` | MEASURED from the authoritative response vector |
| `projection_fields` | MEASURED from the authoritative projected field entries |
| `segments_visited`, `candidates_examined`, `documents_decoded`, `sort_comparisons`, `group_updates`, `logical_memory_peak_bytes` | NOT INSTRUMENTED (`None`) — no existing private seam; X18 signature/global change would be required. `perf`/`heaptrack` provide external attribution, not exact stage counters. |

Mandatory minimum counters are met. The broader stage-counter architecture is a
documented scoped limitation, not a success claim. See `instrumentation.md` and
`profile-attempts.md`.

## 10. Ranked PR 15C candidates (summary)

1. **Per-query segment re-open, envelope re-verification and JSON-path
   re-decode** — `MEASURED` root cause: 55.53%–82.75% SHA-256 self CPU,
   ~23,750 allocations/query in the segment-open path, ~2 GiB cumulative
   allocation traffic per 20 s. Highest impact; highest correctness risk.
2. **Superlinear 100K lexical top-K** — `HYPOTHESIS` /
   `INSUFFICIENT EVIDENCE`: no approved 100K or `medium` profiling entrypoint.
   The prior explanation is weakened as a standalone cause because the measured
   per-query segment-open/hash cost exists at every N.
3. **Top-K materialization above K=100** — Criterion contribution `MEASURED`;
   CPU cause `SUPPORTED HYPOTHESIS` (`MixedEntry` 1.84% self / 6.10% inclusive,
   sort tuple 0.75% self / 2.53% inclusive at K=100; K=1000 not profiled).
4. **Aggregation group-state/staging** — Criterion contribution `MEASURED`;
   CPU cause `SUPPORTED HYPOTHESIS` (`visit_aggregate` 1.95% self, 17.55%
   inclusive in its branch; ~970K staging allocations per site at 10K/4).
5. **JSON scalar path** — Criterion contribution `MEASURED`; CPU/allocation
   `UNAVAILABLE` (not profiled; not in priority table).
6. **Serial batch cross-slot reuse** — neutral Criterion effect `MEASURED`;
   CPU/allocation `UNAVAILABLE` (batch workload not profiled).
7. **Eager error-string formatting** in `parse_container`
   (`segment/format.rs:885`) — `MEASURED` allocation inefficiency
   (15,960 allocations per absent run, ~40/query, 100% temporary); small
   wall-time impact, low-risk cleanup.
8. **Projection width at K=100** — `INSUFFICIENT EVIDENCE`; no action.
9. **Pinned page 2** — `MEASURED` no action.
10. **Geo** — `INSUFFICIENT EVIDENCE`; separate corpus.

Full evidence, confidence, risks and proposed measurements:
`bottleneck-dossier.md`. No candidate is authorized for implementation by this
report.

## 11. Local gate results

| Gate | Command | Result |
|---|---|---|
| Formatting (stable) | `cargo +stable fmt --all -- --check` | PASS |
| Clippy stable all-features | `cargo +stable clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| Clippy MSRV all-features | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| Tests stable default | `cargo +stable test --workspace --all-targets` | PASS: 2095 passed, 0 failed, 10 ignored |
| Tests stable all-features | `cargo +stable test --workspace --all-targets --all-features` | PASS: 2099 passed, 0 failed, 75 ignored |
| Tests MSRV all-features | `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS: 2099 passed, 0 failed, 75 ignored |
| Coverage | `cargo +stable llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS: 91.42% lines, 91.98% regions, 87.45% functions |
| Documentation | `cargo +stable doc --workspace --all-features --no-deps` | PASS |
| Benchmark build | `cargo +stable bench --workspace --no-run` | PASS: all targets |
| Validator self-test | `python3 benchmarks/scripts/validate-pr15b.py self-test` | PASS |
| Whitespace | `git diff --check` | PASS |
| PR15A regression/compatibility | `cargo +stable test -p quervant-core --test pr15a_regression --test pr15a_compatibility` | PASS: 14 + 3 |
| Real RustFS local campaign | not re-run | REUSED/BLOCKED: no production/provider path changed; exact-head `rustfs` CI still required |

Ignored tests are the pre-existing real-service/provider gates (RustFS/S3), not
PR 15B skips.

## 12. Adversarial review of I01–I11

| Invariant | Review outcome |
|---|---|
| I01 frozen provenance | Canonical digest pinned and asserted; generated corpora have independent digests. |
| I02 independent oracle | Arithmetic oracle over static templates; no production evaluator used to derive truth. Lexical top-100 order beyond eight rows is explicitly not independently scored. |
| I03 physical snapshots | Physical segment/document count asserted; mismatch aborts the process. |
| I04 no measured setup | Build/commit/reopen/oracle/metadata/cursor discovery are outside `b.iter`. |
| I05 no default semantic change | Only a `#[cfg(test)]` module and additive benchmark/test/example files; PR15A suites green. |
| I06 qualified source-identical trials | Three clean, idle-attested, clear-contention trials at one SHA and fixture digest. |
| I07 correct profile/run mode | Release Criterion profile confirmed; profiling example built with release+debuginfo. `perf`/flamegraph/heaptrack measured the same executable source. |
| I08 no fabricated counters | Two measured response counters; all others `NOT INSTRUMENTED`, never zero. Profilers are external attribution, not substituted counters. |
| I09 no fabricated profiler | Original UNAVAILABLE attempts preserved. Amendment measured real samples: perf smoke verified, ~80K CPU samples/workload, heaptrack 1.5.0, flamegraph SVG. The perf wrapper/kernel mismatch is disclosed. |
| I10 honest cross-run comparison | Criterion estimates/CI and trial dispersion reported; no p99 or SLA relabel. |
| I11 no unauthorized optimization | `src` diff is test-only; all latency observations are candidates. |

### Residual risks

- The dominant segment-open/hash root cause is `MEASURED` at 10K/4, but the
  exact wall-time recoverable by a PR 15C change is not measured.
- No 100K or `medium`/`common` profiling entrypoint exists; the 100K
  superlinear lexical explanation remains insufficient evidence.
- K=1000, JSON and batch CPU/allocation lanes are not profiled.
- The working perf binary (6.8.12) does not match the WSL 6.18 kernel; samples
  are usable but carry a reproducibility caveat.
- Cargo-flamegraph reported small lost-chunk counts; 20K samples remained.
- Lexical ranking for 2K+ corpora is not independently scored; only count and
  set membership are gated.
- WSL2 contention detection cannot see the Windows host or other guests; `clear`
  is best-effort.
- RustFS real-provider tests are inherited from CI and were not re-run locally.
- Absolute timings are host-specific and must not be compared across machines.

## 13. Decision rules exercised

X01, X03, X04, X06, X09, X12, X13, X16, X17, X18, X19, X20, X22, X25, X26,
X29, X38, X39, X41, X42, X43, X44, X45, X49; amendment rules P4-X01, P4-X02,
P4-X03, P4-X05, P4-X06, P4-X09, P4-X10, P4-X11, P4-X12, P4-X14, P4-X15.
See `decisions.md` for the exact fact/action/scope record. No X99/P4-X99 hard
stop occurred.

## 14. Outstanding human decisions

1. Independent source review of the generator/oracle independence, `b.iter`
   boundaries, release profile and validator negative tests.
2. Push/open a PR. Exact next operations:
   `git push -u origin dev/pr15b-unified-search-diags` and open a PR against
   `main` with the title/body suggested in the execution plan.
3. Exact-head `rust`, `msrv` and `rustfs` CI must pass at the final PR head.
   Current status: **PENDING (branch not pushed)**.
4. Maintainer acceptance of this dossier.
5. A separate approved PR 15C plan selecting at most a bounded candidate subset.
   PR 15B does not authorize optimization.

**PR 15B is not DONE until independently accepted. v0.1 is NOT RELEASED.**

### Profiling-amendment verification (after the evidence-only changes)

These commands were rerun after the profiling-script correction and document
updates. No production search/API/format/dependency source changed.

| Gate | Command | Result |
|---|---|---|
| Profiling script syntax | `bash -n benchmarks/scripts/profile-pr15b.sh` | PASS |
| Formatting | `cargo +stable fmt --all -- --check` | PASS |
| Clippy | `cargo +stable clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| PR15B diagnostic tests | `cargo +stable test -p quervant-core --test pr15b_diagnostics` | PASS: 16 passed, 0 failed |
| Benchmark build | `cargo +stable bench -p quervant-core --bench unified_diagnostics --no-run` | PASS |
| Validator self-test | `python3 benchmarks/scripts/validate-pr15b.py self-test` | PASS |
| Whitespace | `git diff --check` | PASS |
| Original qualified reports | `git diff` on `benchmarks/reports/pr15b-v1-e8ca1b0-*` | unchanged |
| Canonical PR15A fixture | `git diff -- benchmarks/datasets/pr15a_v1.json` | unchanged |
| Search algorithm / public API / index format / dependencies | `git diff --stat -- crates/*/src Cargo.lock` | unchanged (no diff) |
| Profiling provenance | profile artifacts under ignored `target/pr15b/profiles/`; docs record executable source `e8ca1b0` | PASS |
| Unavailable measurements | 100K/`medium`/K=1000/JSON/batch CPU lanes explicitly marked unprofiled | PASS (honest status) |
