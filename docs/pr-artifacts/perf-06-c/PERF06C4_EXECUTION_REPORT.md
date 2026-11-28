# PERF-06-C4 — Integrated C-series paired warm qualification

**Repository:** `yduchesne/quervant` · **Branch:** `dev/perf06-c4` ·
**Plan:** [`PERF06C4_DETAILED_QUALIFICATION_PLAN.md`](PERF06C4_DETAILED_QUALIFICATION_PLAN.md) ·
**Date (UTC):** 2026-11-27 · **Type:** measurement and documentation only (no source changes)

**Disposition:** `PERF06_C4_QUALIFIED_TARGETS_NOT_MET_REVIEW_REQUIRED`

One native `perf-06/warm` acquisition ran to `COMPLETE`. Native A/A passed 16/16.
Treatment: **1/4 primary** targets met and **12/12 guard** lanes within tolerance
(low-hit subset 8/8). This is a valid, complete measurement whose pre-declared
primary thresholds were missed; it is not an `INCOMPLETE` run. Independent review
and the adoption decision remain with the maintainer.

---

## 1. Identity, scope and admission

| Role | Immutable full commit SHA |
| --- | --- |
| Arm A — merged PERF-06-B4 (accepted A+B, PR #129, merged 2026-11-25T23:22:15Z) | `8c9f51f311afa5b327f70432e32c0f6f5c205eab` |
| Arm B — merged C3/F1/F2 (PR #132, merged 2026-11-27T21:39:34Z), also runner checkout `HEAD` | `f169fbba93e10d174cad8ab3bca55cdb7ae6aa03` |
| B Git tree (matches plan pin) | `be6f2a3f000ebbcab80e2985a34316401524c614` |

- Plan path: `docs/pr-artifacts/perf-06-c/PERF06C4_DETAILED_QUALIFICATION_PLAN.md`
  (byte-identical copy, SHA-256 `6c5adfdf7d7e02a10e0f705d06a5d7e40183f0ebecd1490622ad07776a30ecab`).
- Configuration: `benchmarks/studies/perf-06/warm/configurations/quervant-perf06c4-paired-warm-2026-11-27.json`,
  UUID `0e7980c4-a3d9-469e-94fd-716ee4f6890e`, created `2026-11-27T21:59:00Z`.
- Result: `benchmarks/studies/perf-06/warm/results/quervant-perf06c4-paired-warm-2026-11-27-001.json`,
  run ID `1331bb4d-fdd9-47e2-8784-fd4b94470bed`, sequence `1`, executed `2026-11-27T21:59:18Z`,
  native status `COMPLETE`, `errors=[]`.
- Build: `cargo --release --locked`, compiled independently per arm from detached
  worktrees with separate target dirs; `quervant_strategy_feature_enabled=false`;
  `compiler_options="cargo --release --locked"`; arm revisions recorded
  `{"A":"8c9f51f…","B":"f169fbb…"}`; runner `source_revision=f169fbb…`.
- Host: Linux (WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`), `x86_64`, `ext4`,
  12 logical CPUs; controller CPU `0`, adapter CPU `2` (distinct physical cores);
  toolchains `rustc 1.98.1`, `cargo 1.98.1`, `python 3.12.3` (Rust 1.98.1 pinned for
  both arms via `RUSTUP_TOOLCHAIN`). Java is present on the host but unused by
  `perf-06`.
- Source verification before timing: all 17 §1.3 anchor blobs matched the plan at B;
  `origin/main == B`; `A` and `B` are commits and `A` is an ancestor of `B`;
  `git diff --name-status A B -- . ':(exclude)docs/**'` listed exactly the six
  expected non-document paths (`search/execute.rs`, `search/score.rs`,
  `search/unified.rs`, `segment/reader.rs`, `segment/stored_blocks.rs`, added
  `tests/perf06_c2_physical.rs`); the tooling diff (`benchmarks`, `Cargo.*`, `.cargo`,
  `rust-toolchain.toml`, `.github`) was empty; `e4816c5…→B` was docs-only.
- No build/profile override was present (`RUSTFLAGS`, `CARGO_ENCODED_RUSTFLAGS`,
  `CARGO_PROFILE_*` empty; `.cargo/config.toml` contains only a `sweep` alias);
  `QUERVANT_PR15I_D3C_*` strategy variables unset. The known unrelated untracked note
  `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` was preserved untouched.

**Admission observation (recorded for the reviewer).** `dev/perf06-c4` already
existed locally at admission, created from `HEAD` at 2026-11-27T21:40:26Z (before
this plan was delivered), at exactly B with **zero commits** and **no** C4
configuration, result, pull request, scratch directory or prior run. No C4
acquisition artifact existed, so nothing was reused as new, renamed, deleted or
overwritten. The single acquisition ran on that empty task branch at HEAD=B.

### 1.1 Worksheet answers (§3.2)

1. **A/B meaning:** A is merged B4 accepted A+B; B is merged C3 after C2/F1/F2. No
   pre-B1 or C2-only baseline; one paired A/B measures integrated C, not individual
   C2/C3 attribution.
2. **No historical B-only:** the B4 candidate is pre-B4-merge and from another
   session, so it offers no same-session interval; `perf-06` provides exactly the two
   pinned arms and `perf-05` is not a generic B-only alternative.
3. **Low-hit lanes:** PR 15I-C had low-hit codegen/layout regressions despite
   favorable common queries; `M=0`/`M=1 ≤ K+1` stays Legacy and must retain acceptable
   warm latency, and C3 entry growth can affect non-deferred paths.
4. **Independent counts:** `N`, exact corpus formula, `M`, lexicographically ordered
   fixed-width `doc_id`s and `min(M,K)`; expected keys are never derived from results
   and the same oracle gates warmups and samples.
5. **Measured:** actual search plus owned Top-K projected `doc_id`s; index
   construction/open, external oracle and JSON serialization excluded. No throughput,
   RSS, cold-start or compaction claim.
6. **Non-blocking checks:** CPU-readiness `clear`/`busy`/`unavailable`. A/A remains
   binding; compiler/build/index/oracle/schema/sample errors remain real failures.
7. **Policy:** four primary lanes, twelve guards, all 12 paired blocks per lane, no
   pruning; native `COMPLETE` is distinct from the threshold verdict; historical
   comparisons are reported separately with no multiplication of gains.

---

## 2. Waivers and non-waived controls

- **General Rust/Python QA: `NOT RUN — USER-AUTHORIZED C4 WAIVER`.** No
  `cargo test`, `pytest`, `cargo clippy`, `cargo fmt`, `cargo llvm-cov`, `cargo doc`,
  `cargo bench --no-run`, `test-scripts.sh`, adapter unit tests, RustFS harnesses or
  coverage were executed; none are claimed as PASS. Prior C3/F1/F2 correctness and CI
  evidence is referenced as historical, not rerun here.
- **Hosted CI is not a gate.** No workflow was changed; CI was not initiated,
  duplicated, waited on, rerun, cancelled or used to gate the acquisition or delivery.
- **Host readiness is advisory only.** `policy.readiness.mode="advisory"`;
  the runner collected four observations at its normal checkpoints. All four were
  `status="clear"` with `busy_percent=0.0` and `steal_percent=0.0` on adapter CPU 2
  (`readiness_index_pre`, `readiness_pre`, `readiness_treatment`, `readiness_post`).
  These observations were recorded, not used to select, prune or rerun anything.
- **Not waived:** benchmark configuration validation, real release-adapter
  compilation, index creation/reopen/count/byte checks, per-lane and per-query
  independent oracles, the built-in A/A control, and read-only analysis of the actual
  acquisition. All ran and passed.

---

## 3. Execution

| Step | Command (abridged) | Outcome |
| --- | --- | --- |
| Configuration | `python3 -m quervant_bench prepare --family perf-06 --regime warm --name quervant-perf06c4-paired-warm … --readiness-advisory` | created one file; `validate` → `VALID` |
| Config policy check | `python3 $W/verify_c4.py config "$CONFIG"` | `VALID`; 16 lanes, 4 primaries, 12 guards, advisory |
| Acquisition | `python3 -m quervant_bench run --config "$CONFIG" --scratch-root "$W/scratch"` | exit `0`; one `COMPLETE` result; `RESULT_JSON` printed |
| Reanalysis | `python3 -m quervant_bench analyze --result "$RESULT"` | matched stored native analysis exactly |
| Verdict | `python3 $W/verify_c4.py result "$CONFIG" "$RESULT" "$W/native-analysis.json"` | `PERF06_C4_QUALIFIED_TARGETS_NOT_MET_REVIEW_REQUIRED` |
| Render | `python3 -m quervant_bench report --result "$RESULT"` | Markdown rendered from stored values |

- **One invocation, no `stage` call, no retry/resume/pruning.** Preparation ran
  automatically inside `run` and reported `cache_status="BUILT"`, cache key
  `1080c2577384d490b60e7361415e79b694542f00e1f05c86428c3ab3487a7bbc`, prepared
  `2026-11-27T22:00:13Z`.
- **Observation totals (actual):** A/A 768 lane/slot records = 3,840 warmups +
  15,360 timed samples; treatment 768 records = 3,840 warmups + 15,360 timed
  samples; 32 untimed preparation oracles. Total 1,536 records, 7,680 warmups,
  30,720 timed samples and 38,432 planned query calls. Every warmup/sample was
  validated by the independent oracle; all rows carry `oracle_ok=true` and no
  strategy-marker override.
- A/A: all 16 lanes `PASS`; per-lane A/A point gains ranged from `-2.060%` to
  `+1.102%`, inside the `±15%` bound. Binding treatment gate was therefore satisfied.
- Schedule: exact seeded 12-block × 4-slot (2 per arm) position-balanced schedule,
  all 16 lanes, no duplicate slots, no excluded blocks.

---

## 4. Sixteen-lane treatment result

Display is rounded; decisions used the unrounded native values. A and B are the
arm's mean-of-two-slot-medians within each block (native `arm_absolute`). Gain is
`100·(1−B/A)`; positive means B faster. The "A/A" column is point gain with 95%
interval and `PASS` status.

| Lane | N | Class | K | A block median (ns) | B block median (ns) | B/A | Gain % | 95% gain CI | Native status | A/A point [CI] / status | Policy / verdict |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| `10000/absent/k10/warm` | 10,000 | absent | 10 | 31,888.000 | 31,900.500 | 1.005990 | -0.599% | [-6.150, +1.639]% | INCONCLUSIVE | -2.060% [-10.134, +0.829]% / PASS | guard / PASS |
| `10000/absent/k100/warm` | 10,000 | absent | 100 | 31,050.375 | 31,287.750 | 1.006861 | -0.686% | [-2.518, +1.357]% | INCONCLUSIVE | +0.161% [-1.368, +1.240]% / PASS | guard / PASS |
| `10000/rare/k10/warm` | 10,000 | rare | 10 | 40,263.000 | 39,375.500 | 0.982261 | +1.774% | [-0.036, +3.356]% | INCONCLUSIVE | +0.870% [-0.903, +2.538]% / PASS | guard / PASS |
| `10000/rare/k100/warm` | 10,000 | rare | 100 | 40,013.250 | 39,050.500 | 0.978029 | +2.197% | [+0.219, +3.139]% | IMPROVED | +1.102% [+0.314, +2.788]% / PASS | guard / PASS |
| `10000/medium/k10/warm` | 10,000 | medium | 10 | 833,810.375 | 810,861.000 | 0.977888 | +2.211% | [-0.036, +5.029]% | INCONCLUSIVE | +0.169% [-1.675, +1.167]% / PASS | guard / PASS |
| `10000/medium/k100/warm` | 10,000 | medium | 100 | 931,336.875 | 908,837.250 | 0.987193 | +1.281% | [+0.705, +3.923]% | IMPROVED | +0.311% [-0.604, +2.221]% / PASS | guard / PASS |
| `10000/common/k10/warm` | 10,000 | common | 10 | 1,869,412.750 | 1,741,822.875 | 0.939130 | +6.087% | [+4.593, +7.245]% | IMPROVED | +0.494% [-0.109, +2.028]% / PASS | guard / PASS |
| `10000/common/k100/warm` | 10,000 | common | 100 | 1,928,813.375 | 1,823,174.750 | 0.949165 | +5.083% | [+4.248, +6.532]% | IMPROVED | +0.444% [-0.746, +1.960]% / PASS | guard / PASS |
| `100000/absent/k10/warm` | 100,000 | absent | 10 | 160,726.875 | 159,064.625 | 0.992883 | +0.712% | [-2.724, +2.331]% | INCONCLUSIVE | +0.144% [-0.932, +1.752]% / PASS | guard / PASS |
| `100000/absent/k100/warm` | 100,000 | absent | 100 | 152,889.500 | 151,902.000 | 0.987023 | +1.298% | [-0.833, +4.293]% | INCONCLUSIVE | +0.018% [-1.313, +2.126]% / PASS | guard / PASS |
| `100000/rare/k10/warm` | 100,000 | rare | 10 | 166,652.125 | 164,739.500 | 0.987477 | +1.252% | [+0.355, +1.920]% | IMPROVED | +0.574% [-0.607, +1.230]% / PASS | guard / PASS |
| `100000/rare/k100/warm` | 100,000 | rare | 100 | 159,502.250 | 163,402.250 | 1.007336 | -0.734% | [-4.176, +0.370]% | INCONCLUSIVE | -0.344% [-1.284, +1.136]% / PASS | guard / PASS |
| `100000/medium/k10/warm` | 100,000 | medium | 10 | 8,125,462.125 | 7,914,880.000 | 0.973251 | +2.675% | [+1.786, +3.155]% | IMPROVED | -0.264% [-1.289, +1.554]% / PASS | primary / FAIL: gain below +5% |
| `100000/medium/k100/warm` | 100,000 | medium | 100 | 8,094,811.250 | 7,967,944.875 | 0.986300 | +1.370% | [+0.468, +3.601]% | IMPROVED | +0.078% [-0.858, +0.388]% / PASS | primary / FAIL: gain below +5% |
| `100000/common/k10/warm` | 100,000 | common | 10 | 18,520,067.250 | 17,460,217.250 | 0.942771 | +5.723% | [+4.283, +6.930]% | IMPROVED | -0.023% [-0.821, +0.812]% / PASS | primary / PASS |
| `100000/common/k100/warm` | 100,000 | common | 100 | 18,072,178.875 | 17,248,155.750 | 0.958057 | +4.194% | [+2.851, +5.360]% | IMPROVED | -0.460% [-1.154, +0.324]% / PASS | primary / FAIL: gain below +5% |

**Tallies:** primaries **1/4 PASS** (`100000/common/k10/warm`); guards **12/12 PASS**;
low-hit subset **8/8 PASS**. Worst guard point gain `-0.734%`
(`100000/rare/k100/warm`); worst guard gain-CI lower `-6.150%`
(`10000/absent/k10/warm`); both comfortably inside the pre-declared `-10%` bound.

**Primary failures (exact rule):** all three are `gain below +5.0%` with a strictly
positive CI lower bound, i.e. genuine measured improvements that do not reach the
pre-declared primary threshold:

| Primary lane | Gain | 95% CI | Native status | Miss |
| --- | ---: | --- | --- | --- |
| `100000/medium/k10/warm` | +2.675% | [+1.786, +3.155]% | IMPROVED | gain < +5.0% |
| `100000/medium/k100/warm` | +1.370% | [+0.468, +3.601]% | IMPROVED | gain < +5.0% |
| `100000/common/k100/warm` | +4.194% | [+2.851, +5.360]% | IMPROVED | gain < +5.0% |

No lane was `REGRESSED`; the three `INCONCLUSIVE` guard/primary-free lanes are
reported as-is, not relabelled. The `10000/*/common` and `10000/medium/k100` guards
showed improvements of `+5.1%` to `+6.1%`.

---

## 5. Untimed descriptive metrics

Indexing/commit/reopen are reported by the preparation stage; they are not part of
`engine_ns` and were not added to warm latency. No isolated compaction, RSS,
throughput, index-opening-latency or cold-start qualification is claimed.

| Arm | N | Insert (`index_ns`) | Commit | Reopen | Index bytes | Segments |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 10,000 | 19.235 ms | 107.488 ms | 22.303 ms | 1,406,726 | 1 |
| B | 10,000 | 19.725 ms | 110.738 ms | 20.155 ms | 1,406,726 | 1 |
| A | 100,000 | 219.338 ms | 1,090.788 ms | 212.729 ms | 14,312,375 | 1 |
| B | 100,000 | 217.654 ms | 1,092.840 ms | 213.632 ms | 14,312,375 | 1 |

Index size ratio `B/A = 1.000000` with absolute delta `0` bytes at both corpus sizes
(the C-series adds no persisted bytes to this workload).

**Phase durations (wall clock):** host preflight 0.103 s; preparation 55.167 s
(build 49.262 s, corpus 0.089 s, indexing 3.698 s, oracles 0.971 s); A/A acquisition
93.386 s; A/A analysis 0.762 s; treatment acquisition 90.816 s; treatment analysis
0.746 s; total before save 244.040 s (≈4.1 min).

---

## 6. Historical series context (separate effects, not cumulative)

These are **already published within-run effects** from different sessions and
different treatments. They are not contemporaneous with C4, are not summed or
composed, and no direct pre-A1→C effect is measured here.

| Study | Result file | Measured A → B | medium K10 | medium K100 | common K10 | common K100 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| A6 cumulative | `quervant-perf06a6-cumulative-warm-2026-11-24-001.json` | `2a74017…` → `3bb232f…` | +3.129% [2.732, 3.425] | +3.365% [2.421, 3.995] | +6.235% [5.427, 6.708] | +5.428% [4.984, 6.143] |
| B4 paired | `quervant-perf06b4-paired-warm-2026-11-25-001.json` | `480a77e…` → `d660ca9…` | +35.819% [35.411, 36.430] | +35.409% [35.041, 36.505] | +25.363% [24.843, 26.167] | +24.873% [24.414, 25.243] |
| **C4 (this run)** | `quervant-perf06c4-paired-warm-2026-11-27-001.json` | `8c9f51f…` → `f169fbb…` | +2.675% [1.786, 3.155] | +1.370% [0.468, 3.601] | +5.723% [4.283, 6.930] | +4.194% [2.851, 5.360] |

A6 did not meet all four 5% primaries and is not relabelled. B4 met 4/4 primaries and
12/12 guards. C4 measures **incremental C2+C3 over accepted A+B**; the cumulative
pre-A1→final-C effect is **NOT MEASURED** by this plan and would require a separately
authorized study. No historical benchmark was rerun.

---

## 7. Disposition, gates and handoff

**Disposition:** `PERF06_C4_QUALIFIED_TARGETS_NOT_MET_REVIEW_REQUIRED` (D17).
The run is native `COMPLETE` with valid provenance, schedule, oracles, control and
reanalysis; the fixed §5.2 policy is simply not met. Per the plan this is a valid
result, not an incomplete run.

- **Recommendation:** do **not** promote the integrated C-series as a performance
  improvement on this evidence. No automatic rollback of already-merged C
  (correctness-qualified and merged) is performed or authorized; no retuning, subset
  selection or second acquisition is performed.
- **Applied decision rules:** D07 (advisory readiness observed clear, non-blocking),
  D10 (automatic preparation valid, BUILT), D13 (single uniquely matching result
  read), D17 (valid `COMPLETE`, targets missed → report, no retune/retry/rollback),
  D22 (CI not gated), D23 (draft, unmerged, review open). Admission note in §1.
- **Unresolved:** independent review and maintainer acceptance/adoption remain open;
  any follow-up C performance work needs a separately approved design.

| Gate | State |
| --- | --- |
| C4-P0 source & scope | PASS — pinned exact A/B, ancestor verified, adapter/runner unchanged, allowed files only, worksheet complete |
| C4-P1 config | PASS — native `prepare`/`validate`, exact prospective values, one new config, no prior C4 acquisition |
| C4-P2 benchmark correctness | PASS — release builds, commit/reopen/size checks, 32 untimed oracles, every warmup/sample validated |
| C4-P3 measurement validity | PASS — `COMPLETE`, A/A 16/16 PASS, 768+768 records, no pruning, reanalysis matches, one run |
| C4-P4 performance decision | FAIL (targets) — 1/4 primaries, 12/12 guards, 8/8 low-hit; valid measured result |
| C4-P5 publication | PASS — config, result, this report, dated doc notes, draft PR (identity in live handoff) |
| Maintainer review / adoption | OPEN — executor cannot accept, merge or promote |
| General Rust/Python QA, coverage, real-service regression suites | `NOT RUN — USER-AUTHORIZED C4 WAIVER` |
| Hosted CI | Informational only; not initiated or gated by the executor |

**No production, adapter, framework, Cargo, workflow or test source changed.** The
only repository writes are this report, the verbatim plan copy, the CLI-generated
configuration, the runner-published result, and dated append-only status notes in
`docs/PERF_OPTIMIZATION_ROADMAP.md`,
`docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` and
`docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md`.
