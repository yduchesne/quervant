# PERF-02-B — Bounded warm sort-path profiling: diagnostic report

Measurement-only PR. **No production Quervant search code, algorithm selection, codec, index
format, adapter, benchmark statistics or Compiler/feature configuration was modified.**

**Reviewer summary:** the diagnostic *measurements* succeeded (all 16 warm baseline lanes and all
four 800-query profile streams are oracle-clean, and four CPU captures with 1385–3036 samples each
were acquired). The **CPU-share attribution required by the plan could not be computed**, because
Linux `perf` 6.8.12 on this host cannot demangle Rust **v0** symbols and the only demangler available
(`c++filt`) emits `crate[hash]::` and `<Type>::method` forms that cannot contain the plan's fixed
demangled literals (`UnifiedSearcher::search`, `quervant_core::search::unified::`,
`quervant_core::search::execute::`). Under the fixed non-overlapping classification rule every
primary profile is therefore `INSUFFICIENT_VISIBILITY` and `sort_cpu_samples` is `0` **as an artifact
of symbol rendering, not as a measurement of sort cost**.

Consequently the terminal disposition is `PERF02B_BLOCKED`. **No materiality decision is made, and no
CPU percentage is reported or implied.** A one-line amendment to the fixed marker rule (§6 below) is
required from the maintainer; the raw captures are preserved precisely so that amendment needs no new
campaign.

---

## 1. Disposition and scope

| Field | Value |
| --- | --- |
| Terminal disposition | **`PERF02B_BLOCKED`** |
| `PRODUCTION_OPTIMIZATION_IMPLEMENTED` | **NO** |
| `FULL_A_B_CAMPAIGN` | **NOT_RUN** (`quervant-bench run` was never invoked) |
| `CROSS_ENGINE_CAMPAIGN` | **NOT_RUN** (Tantivy/Lucene untouched) |
| Candidate A/B configuration created | **NO** (no candidate source revision exists) |
| `benchmark-result-v1` evidence produced | **NO** (diagnostic summaries are explicitly unqualified) |
| Roadmap updated | **NO** (only after accepted completion; `PERF-02-A` remains `DONE` unchanged) |
| Artifact schema added | **NO** (one bench-only Python module + tests + this report) |

Scope executed: source/fixture inspection; one new diagnostic-only Python module with deterministic
tests; one `validate` + one `stage`; one short uninstrumented 16-lane warm diagnostic; one four-lane
CPU-sampling campaign; read-only analysis; this report.

## 2. Provenance

| Item | Value |
| --- | --- |
| Branch | `dev/perf02b-sort-path-profiling` (from `main`) |
| Base `main` at branch time | `8514320648257eaf4da91174515629accf77786b` |
| PR HEAD (all measurements + this report's data) | `3d3552d3fa4b999fba45558975140edee8321d5a` |
| Accepted engine revision executed (both arms) | `b79b1278a6f9e43fe6e9a760ee714e4f0a76dd51` |
| Baseline immutability check | `git diff --name-status b79b127 HEAD -- crates/quervant-core/src/search crates/quervant-core/src/segment/column.rs benchmarks/pr15d/adapters/quervant` → **empty** |
| Configuration | `benchmarks/studies/perf-02/warm/configurations/quervant-sort-processing-equal-build-2026-11-22.json` |
| Configuration UUID | `7cabee34-656c-4c1d-83e5-885a100daa5a` |
| Arms | `A` and `B` both `engine=quervant`, `mode=by-top-k`, `source=pinned`, `revision=b79b127…dd51`; `build.quervant_feature=null`, `prefilter_profile=P2` |
| Production defaults confirmed | `TopKDuplicateConfig::default()` = `min_top_k=32`, `Prefilter` ⇒ K10 linear, K100 P2 (`crates/quervant-core/src/search/unified.rs:173-180`) |
| `quervant-bench validate` | `VALID` |
| `quervant-bench stage` | `PREPARATION=BUILT`, key `60782c93bf12aaeb4e9dc3e22f33f478eea344c035a1fba0a74f52a11102bb52` (previous cache `bf44ea13…` was stale for this branch's source identity; rebuilt per D05), prepared `2026-11-22T23:01:43Z`, **32 untimed lane/arm oracle checks PASS** |
| Adapter executed | `target/bm10/prepared/60782c93…/build/quervant-a/release/pr15d-quervant-adapter` (`cargo build --release --locked`, strategy feature **disabled**) |
| Indexes executed | `target/bm10/prepared/60782c93…/indexes/A/n10000` (1,560,111 B), `…/A/n100000` (15,747,551 B), 1 segment each |
| Host | `Linux 6.18.33.2-microsoft-standard-WSL2`, x86_64, Intel Core i7-10750H @ 2.60 GHz, 6 cores / 12 threads, ext4, 31 GiB RAM, idle (`readiness=clear`, 0.0 % busy/steal) |
| CPU affinity | adapter pinned to **CPU 2** (`taskset -c 2`; `physical_core_candidates[1][0]`, as `stage` selects) |
| Profiler | `/usr/lib/linux-tools-6.8.0-149/perf`, **perf version 6.8.12** (`/usr/bin/perf` wrapper cannot resolve a WSL-kernel-matched build; the installed Linux perf binary was used directly — same profiler, no substitution, no system/kernel/permission change) |
| `kernel.perf_event_paranoid` | `2` (unchanged; user-space `cpu-clock:u` sampling only) |
| Toolchains | `rustc 1.98.1` / `cargo 1.98.1` (stable), `rustc/cargo 1.85.0` (MSRV), Python 3.12.3 |
| Campaign mode | warm, serial, one adapter process per stream, `engine_ns` from the adapter (query only) |
| UTC capture window | `2026-11-22T23:01:51Z` (inputs) → `2026-11-22T23:05:04Z` (summary) |

Commands (abridged; exact argument lists reproducible from §8):

```sh
quervant-bench validate --config "$CONFIG"
quervant-bench stage --config "$CONFIG"
python -m quervant_bench.lean.perf02b_diagnostics inputs --config "$CONFIG" --output-dir "$OUT"
taskset -c 2 "$BIN" --index-dir "$INDEX10"  < "$OUT/requests/baseline-n10000.jsonl"  > "$OUT/responses/baseline-n10000.jsonl"
taskset -c 2 "$BIN" --index-dir "$INDEX100" < "$OUT/requests/baseline-n100000.jsonl" > "$OUT/responses/baseline-n100000.jsonl"
python -m quervant_bench.lean.perf02b_diagnostics verify --config "$CONFIG" … --output "$OUT/validated/<name>.json"
perf record -e cpu-clock -F 99 --call-graph dwarf -o "$OUT/<slug>.perf.data" -- \
  taskset -c 2 "$BIN" --index-dir "$INDEX100" < "$OUT/requests/profile-n100000-<slug>.jsonl" \
  > "$OUT/responses/profile-n100000-<slug>.jsonl"                      # 4 ×, fixed order
perf script -i "$OUT/<slug>.perf.data" -F comm,pid,tid,time,event,ip,sym,dso > "$OUT/<slug>.perf-script.txt"
perf report -i "$OUT/<slug>.perf.data" --stdio --children --sort symbol --percent-limit 0 > "$OUT/<slug>.perf-report.txt"
python -m quervant_bench.lean.perf02b_diagnostics summarize --config "$CONFIG" --output-dir "$OUT"
```

## 3. Whole-query warm baseline (diagnostic context, **not** a benchmark result)

Exactly two adapter launches, 10 warmups per lane then 50 timed diagnostics per lane, serial, CPU 2.
Every reply was checked against the independent `runtime.expected_answer` oracle (`total_hits` **and**
ordered `doc_ids`); `engine_ns` is query-only and excludes adapter/index initialization. These values
establish the millisecond-scale denominator only: **no confidence interval, cross-run ratio, candidate
gain or optimization verdict is derived from them, and they must not be published as BM-10 results.**

| Lane | K | `total_hits` | median ms | p90 ms | samples | Oracle |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `10000/absent/k10/warm` | 10 | 0 | 0.0313 | 0.0322 | 50 | PASS |
| `10000/absent/k100/warm` | 100 | 0 | 0.0313 | 0.0319 | 50 | PASS |
| `10000/rare/k10/warm` | 10 | 1 | 0.0392 | 0.0406 | 50 | PASS |
| `10000/rare/k100/warm` | 100 | 1 | 0.0391 | 0.0912 | 50 | PASS |
| `10000/medium/k10/warm` | 10 | 1,250 | 1.4567 | 1.5680 | 50 | PASS |
| `10000/medium/k100/warm` | 100 | 1,250 | 1.5650 | 1.7246 | 50 | PASS |
| `10000/common/k10/warm` | 10 | 4,999 | 3.2020 | 3.4830 | 50 | PASS |
| `10000/common/k100/warm` | 100 | 4,999 | 3.2113 | 3.5176 | 50 | PASS |
| `100000/absent/k10/warm` | 10 | 0 | 0.2311 | 0.2596 | 50 | PASS |
| `100000/absent/k100/warm` | 100 | 0 | 0.2302 | 0.2867 | 50 | PASS |
| `100000/rare/k10/warm` | 10 | 1 | 0.2345 | 0.2705 | 50 | PASS |
| `100000/rare/k100/warm` | 100 | 1 | 0.2332 | 0.2822 | 50 | PASS |
| `100000/medium/k10/warm` | 10 | 12,500 | 15.3613 | 16.5754 | 50 | PASS |
| `100000/medium/k100/warm` | 100 | 12,500 | 15.1077 | 16.4102 | 50 | PASS |
| `100000/common/k10/warm` | 10 | 49,999 | 34.1351 | 34.9516 | 50 | PASS |
| `100000/common/k100/warm` | 100 | 49,999 | 33.6957 | 34.7969 | 50 | PASS |

Observation relevant to any future decision (context only): the 100K `medium`/`common` lanes where
the sort path is eligible cost ≈15 ms and ≈34 ms of warmed wall time per query, so a *credible* ≥5 %
end-to-end opportunity would require removing roughly ≥0.75 ms / ≥1.7 ms of per-query CPU — a bar that
only a properly attributed measurement can test.

## 4. Sort-path profile — measured, but attribution **blocked**

Four primary `perf record` captures, one per predeclared lane, in fixed order; 100 warmups + 800
oracle-validated diagnostic queries each; release A binary and A index unchanged; CPU 2.

| Primary lane | timed queries | `query_cpu_samples` | `sort_cpu_samples` | `unknown_samples` | `sort_query_cpu_share_%` | root chain visible | gate outcome |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `100000/medium/k10/warm` | 800 | 310 | 0 (artifact) | 1084 | **CPU_ATTRIBUTION_BLOCKED** | NO | `INSUFFICIENT_VISIBILITY` |
| `100000/medium/k100/warm` | 800 | 339 | 0 (artifact) | 1028 | **CPU_ATTRIBUTION_BLOCKED** | NO | `INSUFFICIENT_VISIBILITY` |
| `100000/common/k10/warm` | 800 | 1304 | 0 (artifact) | 1722 | **CPU_ATTRIBUTION_BLOCKED** | NO | `INSUFFICIENT_VISIBILITY` |
| `100000/common/k100/warm` | 800 | 1309 | 0 (artifact) | 1685 | **CPU_ATTRIBUTION_BLOCKED** | NO | `INSUFFICIENT_VISIBILITY` |

All four reply streams passed the oracle (`total_hits` 12,500 / 12,500 / 49,999 / 49,999 and ordered
`doc_ids`, 800 samples each); profiled `engine_ns` medians were 15.2039 / 14.9984 / 33.5083 /
33.1598 ms. Captured sample totals (1404 / 1385 / 3036 / 3007) match `perf record`'s own reported
counts exactly, so no samples were lost in rendering.

### 4.1 Why the fixed rule cannot be applied (exact, reproducible evidence)

1. `perf script -F …sym…` emits **mangled** Rust **v0** names, e.g.
   `_RNvMs1_NtNtCsf9NSTe8eULi_13quervant_core6search7unifiedNtB5_15UnifiedSearcher6search`.
2. `perf script --demangle` and `perf report` (demangling enabled by default per `perf script --help`)
   leave these names unchanged: perf 6.8.12 has no Rust v0 demangler.
3. The system demangler does resolve them (`c++filt` demangled **101/101** distinct `_R…` tokens in
   `medium-k10.perf-script.txt`), but into `crate[hash]::` and `<Type>::method` forms:
   - `quervant_core[b08e6442fe3ff266]::search::unified::consider_borrowed_keyword_candidate`
   - `<quervant_core[b08e6442fe3ff266]::search::unified::UnifiedSearcher>::search`
4. Therefore the plan's fixed literals `UnifiedSearcher::search`, `UnifiedSearcher::collect_mixed`,
   `quervant_core::search::unified::` and `quervant_core::search::execute::` **cannot match any
   rendering this host can produce** (mangled has no `::`; the demangled form inserts `[hash]` and
   `>`). Only the plain-identifier marker `evaluate_lexical_with` matches, which is why
   `query_cpu_samples` is non-zero while the root-chain gate fails.

Per the plan (§7.1 "not permission to reverse-engineer another perf format"; §10 "unmappable Rust
symbol … do not attempt the follow-up; report `BLOCKED`") no alternate marker set, no demangled
re-rendering, no `nm`/address-based attribution, no `perf annotate`, no disassembly and no follow-up
run were used. `sort_query_cpu_share_%` is deliberately **not** reported.

### 4.2 Frame-presence context — **NOT** an attribution, **NOT** a CPU share

Disclosure only, to show the blocker is a rendering issue and not a missing-symbol issue. Counts are
`grep -c` occurrences of each distinctive identifier inside the saved `.perf-script.txt` files
(a frame may appear in several stacks of one sample; these are **not** the plan's non-overlapping
per-sample buckets and must not be divided by anything to infer a share).

| Capture | `consider_borrowed_keyword_candidate` | `keyword_sort_view` | `evaluate_lexical_with` | `doc_key` |
| --- | ---: | ---: | ---: | ---: |
| `medium-k10` | 126 | 96 | 310 | 861 |
| `medium-k100` | 156 | 105 | 339 | 1081 |
| `common-k10` | 476 | 370 | 1304 | 918 |
| `common-k100` | 536 | 376 | 1309 | 930 |

`compare_borrowed_keyword_to_owned`, `owned_keyword_sort_value`, `materialize_keyword_entry`,
`admit_legacy_keyword_candidate` and `sort_tuple_for_doc` do not appear as frames in this build (they
are inlined or not taken), which the plan anticipated: "Do not assume release inlining preserves every
leaf function as a separate frame; count the root sort-path marker if available." Neither
`perf report`'s inclusive/self percentages nor the counts above are additive costs and none is
interpreted here.

## 5. Source evidence (unchanged by this PR)

The executed shape is the adapter's exact-keyword request with `Sort::new(vec![SortField::new("doc_id",
Asc)])` (`benchmarks/pr15d/adapters/quervant/src/main.rs:307`) over a `Keyword`/`Single`/**columnar**
field, so the borrowed sort path is **eligible** (`YES`):

- `UnifiedSearcher::keyword_sort_late_eligible` (`crates/quervant-core/src/search/unified.rs:592-613`) —
  requires standalone request, single-term postings eligibility, no cursor, exactly one sort field, no
  `json_path`/`distance_from`, and a `Keyword`+`Single`+`columnar` definition. It "never widens the
  existing single-term eligibility".
- `collect_mixed` computes `keyword_field_id` once per segment (`unified.rs:737`) and routes every
  scored candidate to `consider_borrowed_keyword_candidate` (`unified.rs:866`, defined `1971`).
- `ColumnReader::keyword_sort_view` (`crates/quervant-core/src/segment/column.rs:867`) — span lookup,
  bounds and UTF-8 validation, decode budget, borrows the value without allocating; unexpected
  layouts return `LegacyDecode`.
- `borrowed_keyword_candidate_charge` (`unified.rs:1214`) — mandatory accounting of the candidate and
  its borrowed value.
- `compare_borrowed_keyword_to_owned` (`crates/quervant-core/src/search/typed_compare.rs:193`) and
  `materialize_keyword_entry` (`unified.rs:1892` → `owned_keyword_sort_value`,
  `typed_compare.rs:240`) — comparison against the retained worst entry and owned-tuple creation only
  for candidates that can be retained.
- `admit_legacy_keyword_candidate` (`unified.rs:1929`) → `sort_tuple_for_doc` — fallback for
  unsupported shapes; not widened here.

Potentially avoidable versus mandatory (source reading only, no measurement): the `[stderr]`-free
borrow (`keyword_sort_view`) and late materialisation are **already implemented by PR 15H-B**; the
bounds/UTF-8/decode-budget validation and the candidate charge are **mandatory** to preserve index
corruption, resource-limit and ordering semantics. Release per-candidate counts
(`b_observation`, `unified.rs:2377`, `#[cfg(test)]`) are **`NOT_MEASURED`**: they are test-only
witnesses and their values were not extrapolated to this release binary.

## 6. Materiality and next decision

Applying §7.3 to this campaign:

| §7.3 condition | Applies? | Outcome |
| --- | --- | --- |
| All four profiles valid, SORT share strictly < 5 % | NO — no valid attribution exists | — |
| ≥ two profiles ≥ 10 % SORT share with one bounded avoidable operation | NO — no valid attribution exists | — |
| SORT share ≥ 5 % but mandatory / already removed / no credible ≥ ~5 % gain | NO — no share was measurable | — |
| SORT share ≥ 5 % with one consequential attribution ambiguity | PARTIAL — the ambiguity is total, not a single grouping, and is a symbol-rendering issue that a higher sample rate cannot fix (§10) | no follow-up run |
| **Invalid or insufficient CPU attribution after permitted follow-up** | **YES** (and no follow-up is permitted for this cause) | **`BLOCKED`** |

**Decision: `BLOCKED`.** No `OPTIMIZE` recommendation and **no** "no optimization required" conclusion
is made: the plan explicitly forbids labelling the sort path non-material from missing symbol matches,
and `sort_cpu_samples = 0` above is a direct consequence of the inapplicable marker rule.

**Required amendment (not applied here, for maintainer decision).** To unblock the same research
question without touching Quervant or the campaign, the fixed §7.1 marker rule needs to accept the
identifier form the host can emit — for example defining the QUERY/SORT markers as the existing
*plain identifiers* (`consider_borrowed_keyword_candidate`, `keyword_sort_view`,
`evaluate_lexical_with`, `collect_mixed`, `search_impl`, plus the module segments
`quervant_core`/`search`/`unified`/`execute`) matched inside either rendering, and replacing the
root-visibility check accordingly. This changes only the symbol-matching spelling, not the buckets,
the 400-sample gate, the 85 % attributable gate, the non-overlap rule or the 5 %/10 % heuristics. With
such an amendment the preserved `.perf-script.txt` files in §8 can be re-classified **offline without
re-running the campaign**; the four `.perf.data` files are retained so a re-render is also possible.

No optimization is proposed, designed or authorized. If a later, separately approved implementation
PR is ever considered, it owns its own candidate revision, immutable A/B configuration, predeclared
warm criteria and real measurement.

## 7. Exception and QA register

Rules invoked: `D01` (checked, not triggered), `D04`/`D05` (stage rebuilt a stale-identity cache),
`D06`-adjacent profiler availability (perf wrapper unusable → installed Linux perf used, disclosed),
`D07` (all oracle checks passed), `D10`/`D18` + §7.1/§10 (**BLOCKED: Rust v0 symbols unmappable to
the fixed literals**), `D15` (narrow diagnostic fixups during development), `D16` (all mandatory
gates passed), `I01`–`I12` as tested below. `D02` note: three pre-existing untracked, non-source
artifacts (`.coverage`, `benchmark-results/`, `benchmarks/quervant_bench.egg-info/`) were present
before work began and were left untouched; no tracked file was dirty.

| Check (exact command) | Result |
| --- | --- |
| `python -m compileall -q benchmarks/quervant_bench` | **PASS** |
| `python -m pytest -q benchmarks/quervant_bench/lean/tests` | **PASS** — 244 passed, 0 failed |
| `python -m pytest -q benchmarks/quervant_bench/lean/tests/test_perf02b_diagnostics.py` | **PASS** — 78 passed (T01–T12) |
| `coverage run --branch --source=quervant_bench.lean -m pytest -q benchmarks/quervant_bench/lean/tests` + `coverage report --fail-under=85` | **PASS** — total **90 %**; new module `perf02b_diagnostics.py` **94 %** |
| `cargo fmt --all -- --check` (stable 1.98.1) | **PASS** |
| `cargo +1.85.0 fmt --all -- --check` (MSRV) | **PASS** |
| `cargo clippy --workspace --all-targets -- -D warnings` (stable) | **PASS** |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` (MSRV) | **PASS** |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (stable, CI job) | **PASS** |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` (MSRV) | **PASS** |
| `cargo test --workspace --all-targets` (stable) | **PASS** — 138 suites, 2 485 passed, 0 failed |
| `cargo +1.85.0 test --workspace --all-targets` (MSRV) | **PASS** — 138 suites, 2 485 passed, 0 failed |
| `cargo test --workspace --all-targets --all-features` (stable, CI job) | **PASS** — 138 suites, 2 530 passed, 0 failed |
| `cargo +1.85.0 test --workspace --all-targets --all-features` (MSRV) | **PASS** — 138 suites, 2 530 passed, 0 failed |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | **PASS** — lines **92.50 %** (regions 93.04 %, functions 87.81 %) |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` (CI job) | **PASS** — lines **92.05 %** (regions 92.71 %, functions 87.71 %) |
| `cargo doc --workspace --no-deps` | **PASS** |
| `cargo doc --workspace --all-features --no-deps` (CI job) | **PASS** |
| `cargo bench --workspace --no-run` (CI job) | **PASS** |
| `bash benchmarks/scripts/test-scripts.sh` (CI job) | **PASS** — 108 passed, 0 failed |
| GitHub Actions `Rust CI`, PR #116, run [`45085190963`](https://github.com/yduchesne/quervant/actions/runs/45085190963) on head `70e047d16f99b04583ab025bc86d1a417c869087` | **PASS (success)** — `rust` 16m34s, `msrv` 10m49s, `rustfs` 2m28s, `benchmark-adapter-contract` 1m29s, `python-benchmark-framework` 2m42s |
| `cargo test --locked --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml` | **PASS** — 6 passed |
| `cargo test -p quervant-core b_u01_u08_u36_counts_order_and_materialization` | **PASS** — 1 passed |
| `quervant-bench validate --config "$CONFIG"` | **PASS** — `VALID` |
| `git diff --check` | **PASS** |
| `quervant-bench stage` (32 untimed oracles) | **PASS** — `BUILT` |
| Short baseline, 16 lanes × 50 samples | **PASS** — 16/16 oracle PASS |
| Four primary captures, 800 samples each | **PASS** — 4/4 oracle PASS |
| CPU-share attribution (§7.1) | **BLOCKED** — Rust v0 symbols unmappable to fixed literals |

Invariant status: `I01` PASS (pinned config/commit, no strategy feature); `I02` PASS (stage-built
indexes, adapter times queries only); `I03` PASS (every reply, ordered IDs); `I04` PASS (only the four
primary lanes sampled); `I05` PASS (16 short baseline lanes, context only); `I06` PASS (allowlist);
`I07` PASS by construction and unit test T10, but **not exercised on real data** because the marker
rule could not run; `I08` **FAIL → BLOCKED**; `I09` PASS (one campaign, no follow-up); `I10` PASS (all
outputs labelled diagnostic/unqualified); `I11` PASS (no production edits; existing suites green);
`I12` PASS except the unavailable CPU share.

Not captured / residual limitations: no release per-candidate counts (`NOT_MEASURED` — test-only
`b_observation`); `perf record` is launch-scoped so captures include bounded process startup and the
100 warmups; WSL2 host (virtualized, `perf_event_paranoid=2`, user-space `cpu-clock` only); no
RustFS/remote storage was exercised or claimed; `/usr/bin/perf` wrapper is unusable on this kernel so
the installed 6.8 perf binary was invoked directly. The single `pull_request` workflow run above is the
only CI run for this branch (no branch-specific `push` trigger was added).

## 8. Diagnostic evidence index (host-local, **not committed**)

All raw files live under the git-ignored `target/perf02b/` on the benchmark host and must be preserved.
`GLOBAL` = `target/bm10/prepared/60782c93bf12aaeb4e9dc3e22f33f478eea344c035a1fba0a74f52a11102bb52`.

| File | SHA-256 |
| --- | --- |
| `requests/baseline-n10000.jsonl` | `3aa73b38ce06a0b2bf41e81a4adc2a359da51ed1fe95d2f3ff512170d5988046` |
| `requests/baseline-n100000.jsonl` | `c6cbc7324116f39089fdcf6bc11667eb4378085842bc5547cf192b52d91f7053` |
| `requests/profile-n100000-medium-k10.jsonl` | `50af50a96cf4fc0b296e2a830be56bb29105f5181a3a1addbc7523c7ced5ca85` |
| `requests/profile-n100000-medium-k100.jsonl` | `14ec2cfb7842b428d52df2930ee73354f67f95271bb1c1ccdb5613c792840242` |
| `requests/profile-n100000-common-k10.jsonl` | `d19792e6f02f64b4b9b5227dd2b2bbd63d5647eaf0682307a6b20ea0d3604b1e` |
| `requests/profile-n100000-common-k100.jsonl` | `573598239542fb74d02c8baf8a812e7b59dec5d547be91f23cf1f4edbaa879aa` |
| `requests/inputs-manifest.json` | `5c9aac12f37048d8441c40f1bc8988f74017851cdec73046f006e42f7496f60e` |
| `responses/baseline-n10000.jsonl` | `d5e15531d9360bdf90ffe931b39ea7e6ba00cb7835f9f752b34bc98544abac1e` |
| `responses/baseline-n100000.jsonl` | `d278aa1f9b37212ab178f4c123b215c3d3e87864be731bf224ebff3a43c3642a` |
| `responses/profile-n100000-medium-k10.jsonl` | `14f57405fdecbcdb6a2d15a6a95d3ffebe10f7ae5715a60d90e326a65b6f5016` |
| `responses/profile-n100000-medium-k100.jsonl` | `3928b1cccd63f34d0439d2d68ef825d579e3367bb171d9aa1be0096905f6899d` |
| `responses/profile-n100000-common-k10.jsonl` | `d26f29059b74f9c1f9c5fa1b1c298df5ef2eec60a6e8be68ee1cd71895ac2f19` |
| `responses/profile-n100000-common-k100.jsonl` | `63a5c2bc415ca02f332b75489d52fecc75f1685a90195435ebcbbbefe3ccb937` |
| `validated/baseline-n10000.json` | `de3f39237a2fc6443bf0e6e35d7a154fa8a65887d40c586ce760993b078d6faa` |
| `validated/baseline-n100000.json` | `df408ee10248ef94036fbfb03c054bae5bb8056844e0fa7787c3301c1cb4b3e2` |
| `validated/profile-n100000-medium-k10.json` | `d491e0821f18c60d5934dee9cd2c33016d403dfb3b149765d0f34aabe1cff256` |
| `validated/profile-n100000-medium-k100.json` | `7593f9fba6e68672b52c481075056003e5502fd18d67a809f524b29c54eb1af6` |
| `validated/profile-n100000-common-k10.json` | `17871ae87b939ae0b540ef9f22bea8dca6f88a424be321f23f2d6e66b78ee6ea` |
| `validated/profile-n100000-common-k100.json` | `e9ea31a2ee5e029d9a08f174a098056c7fb63a7508b707ffecc7e8ae203ef1ec` |
| `medium-k10.perf.data` (11,886,272 B) | `b1516da8acc487b42bd5ea6af89e6d56727ec10f25af7d2dfd37e286c5976072` |
| `medium-k100.perf.data` (11,725,904 B) | `ff2b97cc1ad993d7398fb9b89b01c6c69792d3dfe0ba142135a7e5201bb8ff4a` |
| `common-k10.perf.data` (25,660,768 B) | `5dba40541c1e10cea3d24024a86fd2ad74b9eb5cb15d725d98348027fcc7416b` |
| `common-k100.perf.data` (25,416,000 B) | `aceaeb387baff33c6d976afb1312918d951849aec2b253e5a92f12c00aef95f6` |
| `medium-k10.perf-script.txt` | `137905983f325c9bb64d1956023fb806bd9948a9285d4ae13ecbdd915afe90a8` |
| `medium-k100.perf-script.txt` | `1d2913d8f2288261d3e95f6590e4b2ac977198f1ff90bebc1bc6b3a4c47206ab` |
| `common-k10.perf-script.txt` | `6fb63368d2ee3d3fe0a27d2c53638b0be22024385d977624c9470edc31e4ece0` |
| `common-k100.perf-script.txt` | `a4f83ddc0aaa2ff8fbcab96bd45c59eeca3c521421a13b66a9b4bdf5a66b38d4` |
| `medium-k10.perf-report.txt` | `9f96b451de9dc6c64fb83522e6f69df1d086c25bb2d5bbc4cb1765734dce366d` |
| `medium-k100.perf-report.txt` | `1328a7512ea742e876ecffa5ec266fe7615fe020b743f6010b14f3d898e66b7c` |
| `common-k10.perf-report.txt` | `dec4edd4135c959ebc173a45efb3d2d96df51f12f8ff752e36f9a75faa19a0d1` |
| `common-k100.perf-report.txt` | `61fc4bc16287bef0f6b680f460d0f19a796a3f0d859202a1b435beebda73b5f6` |
| `summary.json` (deterministic, `cpu_attribution_status=CPU_ATTRIBUTION_BLOCKED`) | `422030366e2a451900058e58c0969232d74932b4caeb0eec6473c7214dde1a1f` |
| `GLOBAL/build/quervant-a/release/pr15d-quervant-adapter`, `GLOBAL/indexes/A/*`, `GLOBAL/prepared.json` | see `prepared.json` fingerprints (20 entries) |

This report is **not** `benchmark-result-v1` evidence and must not be published as a benchmark result.
Requesting full raw captures is a separate evidence-transfer decision.

## 9. Code and tests added by this PR

- `benchmarks/quervant_bench/lean/perf02b_diagnostics.py` — three commands (`inputs`, `verify`,
  `summarize`); deterministic write-once JSONL generation, oracle/exact-order reply validation,
  median + nearest-rank p90 of `engine_ns`, and the fixed non-overlapping `perf script` classifier.
  It spawns no subprocess and never runs `quervant-bench run`, `perf record` or a timed campaign.
- `benchmarks/quervant_bench/lean/tests/test_perf02b_diagnostics.py` — 78 mocked, untimed tests
  covering T01–T12 (stream shape/order, identity fail-closed rules, oracle and protocol violations,
  write-once idempotence, attribution blocking, non-overlapping sample counting, no-process guarantee).
