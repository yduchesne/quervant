# PERF-06-B4 — Execution Report (cumulative B1+B2+B3 warm qualification)

**Terminal status:** `PERF06_B4_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED`
**Plan executed:** [`PERF06B4_DETAILED_PLAN.md`](PERF06B4_DETAILED_PLAN.md) (verbatim copy; sha256 `575b0ce8e1aa4708eae629d7f9f0cb67ba1be84fbbea861bce423d9a91ab339f`)
**Human decision:** **G10 OPEN** — maintainer alone accepts/rejects B4 and decides whether the B-series becomes the PERF-06-C baseline. No merge, no adoption approval and no C1 start is claimed here.

---

## 1. Hypothesis, method choice, exclusions and user-authorized overrides

**Hypothesis.** The already accepted cumulative B-series architecture (B1 persistent segment keyword dictionaries/ordinals + snapshot-wide numeric mapping; B2 global Top-K shared-rank sort with owned winner tuples; B3 retained, metered per-verified-segment key fingerprints with collision-exact duplicate detection and losing-candidate deferred ownership) reduces end-to-end **warm exact-keyword search plus Top-K projection** latency relative to the last accepted source **before B1**.

This is a **cumulative A→B** comparison. Nothing here attributes the observed effect to B1, B2 or B3 individually, and nothing here reopens or reinterprets the historically rejected PR 15H-C / 15I-D1-F mechanisms.

**Why a new contemporaneous paired A/B and not a B-only historical study.** B1 changed the persistent index representation, so a B-only run against an older absolute median would be historical, unpaired and context-sensitive; the nearest previously measured pre-B1 source (A6 `3bb232f`) is not the exact pre-B1 Git object and was acquired in a different session. One new paired experiment inside the existing `perf-06/warm` two-pinned-arm path removes that weak comparability assumption and requires no new scheduler, no Tantivy/Lucene arm and no second timed campaign. A B-only fallback on an unfavorable result was explicitly not authorized and was not used.

**Work performed.** One narrowly scoped, opt-in benchmark-tool capability (`policy.readiness.mode="advisory"`, creation-only `prepare --readiness-advisory`, PERF-06 only) so real host-load observations are preserved as evidence without acting as an acquisition gate, plus versioned configuration/result/report evidence. **No engine optimization**: no B1/B2/B3, index, reader, collector, codec, query, cursor, objectstore, S3/RustFS, adapter, compiler-flag or dependency change.

**Explicit user-authorized overrides honored (plan §0.1).**

| Override | Observed effect |
|---|---|
| Assume `main` stable after the B3 merge; no broad QA rerun | No `cargo test`, no `pytest` benchmark-framework suite, no `cargo clippy`, `fmt`, `doc`, coverage or pre-commit hook was executed. No CI gate was required for acquisition. `D44`/`D45` applied. |
| Host assumed idle and available | No separate host-qualification campaign and no idle reconfirmation request. Linux/WSL2, native `ext4`, six distinct physical cores, `taskset`, Rust toolchain kept as technical prerequisites (`D12` never triggered). |
| Host stability observations informative, never blocking | Readiness retained its original 25%/2% ceilings; `busy`/`unavailable` could not and did not block. Actual statuses stored verbatim (`D10`/`D11` not triggered; all readings happened to be `clear`). |
| Exactly one real timed acquisition | One durable start marker, one `run` invocation, one result JSON. No retry, no overwrite, no block pruning, no criterion change (`D21` never triggered). |
| No new engine optimization | Only the advisory harness + docs/config/evidence; protected engine and statistics paths untouched. |
| G10 remains human | Draft PR only; no merge, no adoption approval, no C1. |

Required **benchmark** integrity checks were still executed because they are acquisition integrity, not a test-suite rerun: the native per-sample independent oracle inside `stage`/`run`, `quervant-bench validate`, and the read-only result verifier.

---

## 2. Source identities and protected-path verification

| Item | Value |
|---|---|
| Arm A (last accepted pre-B1, frozen) | `480a77e78c6897e05cb7ceb76b01434974b82ec6` |
| Arm B (post-B3 merged `main`, pinned once) | `d660ca9f487d5c54363d790a240abb7da30af245` |
| B3 PR | #128 `MERGED` 2026-11-25T22:25:52Z, head `dev/perf06-b3` |
| B3 merge commit / parents | `d660ca9` ← `ce7dea1` (B2 main) + `5bae0f7` (PR head) |
| B1 PR / B2 PR | #126 `MERGED` merge `3cb1cbd`; #127 `MERGED` merge `ce7dea1` |
| A ancestor of B | yes (`git merge-base --is-ancestor` = 0) |
| B4 branch | `dev/perf06-b4` (task-owned, created from `d660ca9`, no prior B4 artifacts ⇒ `D04` resume) |
| Tooling commit (`source_revision` in build provenance) | `c874748a9acffb65d59f34cda88d861d7542df3e` |
| Adapter build | `cargo --release --locked`, `quervant_strategy_feature_enabled=false` |
| Compiled arm provenance | `{"A":"480a77e…","B":"d660ca9…"}` independently, in separate detached worktrees/target dirs |

**B3 provenance (D03).** `git diff --name-status 52d7e69f40759f27be79434118c47171b06702b7 d660ca9f487d5c54363d790a240abb7da30af245 -- . ':(exclude)docs/' ':(exclude)benchmarks/studies/'` is **empty**; `52d7e69..b7753c5` non-docs is also empty. The reviewed B3 tested engine blobs therefore reach `main` unchanged, with only documentation/evidence commits after the tested executable source. No `D05`/`D47` condition exists.

Engine blob IDs (A→B): `segment/format.rs` `55ca2885…`→`296b7c5c…`, `segment/reader.rs` `951f0808…`→`37af8cc4…`, `search/unified.rs` `89419f64…`→`f3a2862f…`, `index/keyword_ordinals.rs` absent→`6e20bab8…`.

Full identities: [`b4/preflight.txt`](b4/preflight.txt).

**P8/G8 protected-diff check.** The only non-`docs/` changes on the B4 branch are `benchmarks/quervant_bench/lean/{cli,configuration,runtime,preparation}.py` (the four §4-admissible files), `docs/BENCHMARK_CONFIGURATION.md`, `benchmarks/BM10_README.md`, and the one new immutable configuration JSON. `crates/**`, `Cargo.toml`, `Cargo.lock`, `.github/**`, `benchmarks/pr15d/**`, `statistics.py`, `artifacts.py`, `perf05.py`, `reporting.py`, datasets/corpus/oracle sources, and all pre-existing configuration/result/evidence files are unchanged. No test file was added or executed.

---

## 3. Frozen configuration

| Field | Value |
|---|---|
| File | `benchmarks/studies/perf-06/warm/configurations/quervant-perf06b4-paired-warm-2026-11-25.json` |
| `configuration_id` | `4608c79a-c5a3-4d24-bec9-4ad61cd7bd94` |
| `created_utc` | `2026-11-25T22:27:58Z` (CLI-generated; filename date from this value) |
| Family / regime | `perf-06` / `warm` |
| Arms | `A`/`B`, both `engine=quervant`, `mode=by-top-k`, `source=pinned`, release/locked |
| Workload | `pr15d-exact-keyword-v1`, exact term count + ordered `doc_id` IDs, UTF-8 lexicographic ascending string sort |
| Matrix | sizes `10000`,`100000` × classes `absent,rare,medium,common` × K `10,100` = **16 lanes** |
| Control | `AA` / `AA2`, both the baseline A executable and index |
| Schedule | 12 randomized position-balanced blocks, 2 slots per arm per block, seed `20261122` |
| Samples | 5 untimed warmups + 20 timed per lane/slot; 768 control + 768 treatment records |
| Estimator | per-slot median → mean of 2 slot medians → 12 paired B/A block ratios → median; gain `100*(1-ratio)` |
| Uncertainty | 10,000 deterministic whole-paired-block bootstrap, 95% percentile |
| Native policy | `min_gain=0`, `max_regression=0`, `max_aa_gain=15`, `min_blocks=4`, `exclude_blocks={}` |
| Readiness | 4 × 250 ms, unchanged ceilings busy 25% / steal 2%, `mode="advisory"` |
| CLI stdout retained | [`b4/prepare.stdout`](b4/prepare.stdout); `validate` → `VALID` |

Nothing in the JSON was edited after creation. The frozen B4 numerical policy (see §7) was fixed by the approved plan **before** the timed run.

---

## 4. Host capabilities versus readiness observations, and the A/A control

**Structural prerequisites (binding, all satisfied):** Linux/WSL2 (`6.18.33.2-microsoft-standard-WSL2`), native `ext4`, six distinct physical cores `[0,2,4,6,8,10]`, `taskset` (util-linux 2.39.3), cargo/rustc 1.98.1, python 3.12.3. Controller CPU `0`, adapter CPU `2`, both pinned. `host_context(check=True)` was used — no `check_host=False` shortcut.

**Readiness (advisory, stored verbatim, never rewritten):**

| Checkpoint | Status | Observed max busy / steal | Where |
|---|---|---|---|
| `readiness_index_pre` (before staged indexing) | `clear` | 0.0% / 0.0% | stage cache manifest |
| `readiness_index_pre` (reused) | `clear` | 0.0% / 0.0% | result `controls`, source=`preparation stage` |
| `readiness_pre` (before A/A) | `clear` | 0.0% / 0.0% | result `controls` |
| `readiness_treatment` (before treatment) | `clear` | 0.0% / 0.0% | result `controls` |
| `readiness_post` (after treatment) | `clear` | 0.0% / 0.0% | result `controls` |

`context.host_readiness_mode = "advisory"`. No observation was `busy` or `unavailable`, so the advisory relaxation had **no** effect on this campaign's validity; it is nevertheless proven operative by the preserved mode flag and unchanged 25%/2% ceilings. No ceiling was raised, no reading fabricated as `clear`, and sampling was not removed.

**A/A equivalence control (still fully blocking):** all **16/16** lanes `status="PASS"` under the original ±15% criterion. Largest absolute A/A gain was `1.2310%` (`100000/rare/k100/warm`); largest absolute A/A CI bound was `3.8531%`. The A/A rejection path in the runner was **not** modified, replaced or bypassed.

---

## 5. Stage: independent builds, indexes and untimed oracles

One `stage` invocation, `PREPARATION=BUILT`, exit code 0, preparation key `5c3f64949c52d6bb2c68572342b3432a10efc265e1abba6c09e52d85232d96dc`, prepared `2026-11-25T22:29:02Z`. Log: [`b4/stage.log`](b4/stage.log).

- Two independent release adapters from pinned detached worktrees: `quervant-a` (4,530,016 B, sha256 `6d219fac…`) and `quervant-b` (4,625,848 B, sha256 `cd01044b…`) — **different binaries**, not reused.
- Two independent filesystem indexes per corpus size per arm.
- Corpus documents indexed == verified == N for both arms and both sizes (enforced by `build_index`/`reopen` checks).
- All **16 lanes × 2 arms** untimed independent oracles passed (enforced by `_verify_oracles`; a mismatch aborts staging).
- `index_bytes` in metadata matches the actual on-disk file tree exactly (A 1,456,779 / 14,713,132; B 1,406,726 / 14,312,375).

**Untimed writer/footprint diagnostics (descriptive only; never mixed into warm `engine_ns`, never a selection gate):**

| Arm | N | `index_ns` (ms) | `commit_ns` (ms) | `reopen_ns` (ms) | `index_bytes` | segments |
|---|---:|---:|---:|---:|---:|---:|
| A | 10000 | 22.728 | 127.381 | 21.369 | 1,456,779 | 1 |
| B | 10000 | 20.332 | 105.127 | 20.381 | 1,406,726 | 1 |
| A | 100000 | 209.227 | 1,231.153 | 212.588 | 14,713,132 | 1 |
| B | 100000 | 217.465 | 1,164.980 | 210.609 | 14,312,375 | 1 |

B/A bytes ratio: `0.9658` (10K), `0.9728` (100K). This is a **fresh-build/reindex footprint diagnostic** from the stage, not a compaction benchmark; no separate timed writer campaign was run. No RSS claim is made: the framework does not record authoritative retained-fingerprint RSS. At source level B3 retains bounded per-segment metadata (e.g. `Vec<u64>` key fingerprints per verified segment); that representation is not converted into an unapproved memory measurement.

The two indexes are **not** byte-identical by design (B1 changed encoding); logical counts and ordered IDs are what the oracles assert.

---

## 6. Acquisition (exactly one timed invocation)

Durable exclusive start marker written (fsynced) **before** spawning the run: [`b4/ACQUISITION_STARTED.marker`](b4/ACQUISITION_STARTED.marker) — config, UUID, A/B SHAs, acquisition UTC, tool SHA, stage key, exact command, `authorized_timed_invocations: 1`.

```bash
PYTHONPATH=benchmarks python3 -m quervant_bench run \
  --config benchmarks/studies/perf-06/warm/configurations/quervant-perf06b4-paired-warm-2026-11-25.json \
  --scratch-root target/perf06-b4
```

(Tool resolution `D13`: the installed `quervant-bench` console script is absent and no `pip` is available in the system Python, so the plan-authorized canonical module entrypoint was used consistently. No harness or dependency was installed.)

| Item | Value |
|---|---|
| Exit code | `0` |
| Result path | `benchmarks/studies/perf-06/warm/results/quervant-perf06b4-paired-warm-2026-11-25-001.json` |
| `run_id` | `86fe9601-2574-4335-a673-63de7d0dcc26` (distinct from config UUID) |
| `executed_utc` | `2026-11-25T22:29:15Z` |
| Status | `COMPLETE` |
| Errors | none |
| Preparation during run | `HIT` on preparation key `5c3f6494…` (inputs re-verified, all lanes re-oracled) |
| Records | 768 control + 768 treatment = 1536 |
| Timed samples | 15,360 + 15,360 = 30,720 positive integer values |
| Schedule integrity | 12 blocks × 2 arms × 2 slots for every lane; `oracle_ok=true`, `warmups=5`, `samples_ns` length 20 for every record |
| A/A before treatment | 16/16 PASS; treatment ran only after that gate |
| Phase durations | A/A 121.46 s, treatment 106.95 s, total pre-save 234.26 s |

Log: [`b4/run.log`](b4/run.log). The runner chose the `-001` suffix exclusively; the file was created, never overwritten. No second invocation occurred.

---

## 7. Results and frozen B4 gate

Positive gain = `100*(1 − median paired B/A ratio)`; positive means **B is faster**. `95% CI` = native percentile interval of whole-block paired ratios (gain percent).

| Lane | A median block (ns) | B median block (ns) | B/A | Gain % | 95% gain CI | Native status | B4 gate |
|---|---:|---:|---:|---:|---|---|---|
| 10000/absent/k10/warm | 30,837.9 | 31,175.4 | 1.00884 | −0.884 | [−2.465, +2.539] | INCONCLUSIVE | guard PASS |
| 10000/absent/k100/warm | 30,300.4 | 30,687.6 | 1.01199 | −1.199 | [−2.153, −0.865] | REGRESSED | guard PASS |
| 10000/rare/k10/warm | 38,950.9 | 39,537.8 | 1.02685 | −2.685 | [−2.846, −0.864] | REGRESSED | guard PASS |
| 10000/rare/k100/warm | 38,562.8 | 39,163.1 | 1.02047 | −2.047 | [−3.368, −0.064] | REGRESSED | guard PASS |
| 10000/medium/k10/warm | 1,282,167.2 | 839,073.6 | 0.65075 | +34.925 | [+33.331, +35.770] | IMPROVED | guard PASS |
| 10000/medium/k100/warm | 1,388,643.5 | 929,475.0 | 0.66676 | +33.324 | [+31.421, +34.326] | IMPROVED | guard PASS |
| 10000/common/k10/warm | 2,411,920.4 | 1,861,762.8 | 0.76749 | +23.251 | [+22.125, +24.081] | IMPROVED | guard PASS |
| 10000/common/k100/warm | 2,482,296.5 | 1,919,354.5 | 0.77801 | +22.199 | [+21.303, +23.037] | IMPROVED | guard PASS |
| 100000/absent/k10/warm | 159,477.1 | 157,252.1 | 1.00136 | −0.136 | [−3.570, +2.848] | INCONCLUSIVE | guard PASS |
| 100000/absent/k100/warm | 150,077.0 | 150,364.6 | 1.00326 | −0.326 | [−2.958, −0.025] | REGRESSED | guard PASS |
| 100000/rare/k10/warm | 164,677.0 | 164,764.8 | 1.01722 | −1.722 | [−2.981, +1.571] | INCONCLUSIVE | guard PASS |
| 100000/rare/k100/warm | 157,889.8 | 160,027.5 | 1.01302 | −1.302 | [−1.854, −0.319] | REGRESSED | guard PASS |
| **100000/medium/k10/warm** | 12,766,947.5 | 8,193,935.1 | 0.64181 | **+35.819** | [+35.411, +36.430] | IMPROVED | **primary PASS** |
| **100000/medium/k100/warm** | 12,735,922.1 | 8,188,935.2 | 0.64591 | **+35.409** | [+35.041, +36.505] | IMPROVED | **primary PASS** |
| **100000/common/k10/warm** | 24,615,382.1 | 18,373,460.0 | 0.74637 | **+25.363** | [+24.843, +26.167] | IMPROVED | **primary PASS** |
| **100000/common/k100/warm** | 24,116,864.0 | 18,079,480.1 | 0.75127 | **+24.873** | [+24.414, +25.243] | IMPROVED | **primary PASS** |

**Frozen B4 policy applied (plan §7.2, fixed before timing, unrounded values):**

- Primaries (`100000/{common,medium}/k{10,100}`) pass only with `status=IMPROVED`, `gain ≥ 5.0`, `CI lower > 0`. **4/4 PASS** (minimum +24.873%).
- Guards (the other 12 lanes) pass with `gain ≥ −10.0` **and** `CI lower ≥ −10.0`, data finite/qualified. **12/12 PASS** (worst guard −2.685% point, worst guard CI lower −3.570%).
- An `INCONCLUSIVE` native label is permitted on a guard and stays visible (3 such lanes, all near-neutral and inside the guard bound).

**Disposition: `PERF06_B4_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED`.** 4/4 primaries and 12/12 guards met the frozen criteria on a structurally `COMPLETE`, oracle-clean, A/A-clean campaign.

**Scope limits that must accompany this number.**

- This is a **per-lane, paired, cumulative B1+B2+B3** result on this host/configuration. It is **not** a universal Quervant speedup, not a cross-engine ranking, and not a causal attribution to any single B stage.
- The large gains concentrate in the selective-but-expansive `medium` and `common` classes at 100K; absent/rare lanes are within about ±2.7% and four of them carry a statistically marked small regression, all well inside the pre-declared guard bound and reported unchanged.
- No compaction-cost or RSS claim is made (§5).
- Historical absolute medians from earlier unpaired campaigns are **not** used as controls, and no B4 result is substituted into them.

---

## 8. Read-only verification

| Check | Result |
|---|---|
| `quervant-bench validate --config <frozen config>` | `VALID` |
| `quervant-bench analyze --result <result>` vs stored `analysis` | **exactly equal** (parsed-JSON equality asserted by the verifier) |
| `quervant-bench report --result <result>` | rendered from stored values only; no timing/change |
| Read-only verifier | [`b4/support/verify_b4_result.py`](b4/support/verify_b4_result.py), sha256 `3f1144d3c50fa82df5e147c2279ab5153548463d45fd1b24ea1d960904b52498` |
| Verifier output | [`b4/verification.json`](b4/verification.json) — `result_status=COMPLETE`, `host_readiness_mode=advisory`, 4 primaries / 12 guards, `all_targets_met=true` |

The verifier mechanically confirmed, from the native JSON: schema/family/name/UUID coherence and embedded-configuration equality; `arm_source_revisions == {A:480a77e…, B:d660ca9…}`; `host_readiness_mode=advisory`; 16 lane IDs present in `lanes`, treatment `analysis`, and controls `analysis`; `status=COMPLETE`; 768 + 768 raw records with exactly 2 slot records per lane/arm/block for all 12 blocks, `warmups=5`, 20 positive integer samples and `oracle_ok=true`; all 16 `AA2` comparisons `PASS`; positive `index_ns/commit_ns/reopen_ns/index_bytes/segment_count` for both arms and sizes; native statuses restricted to `IMPROVED/REGRESSED/INCONCLUSIVE`; finite point/CI values with `ci[0] ≤ ci[1]`.

No STOP rule in D01–D52 was triggered. No compatibility correction under `D39` was needed: the real `benchmark-result-v1` fields matched the plan's expectations exactly (`gain_ci_95_percent` is stored in gain-percent units).

Artifacts in this directory are task-process/reporting evidence, not a second result and not a statistical certification. The only benchmark **data** artifacts remain the one configuration JSON and the one result JSON.

---

## 9. Integrity boundaries preserved

- **B4-I01..I14:** all satisfied. A is the last pre-B1 accepted revision; B is the accepted post-B3 `main`; real native `doc_id` string sorting with exact counts/order; independent binaries and indexes; readiness informational with true statuses; structural host + A/A still binding; full paired schedule; warm `engine_ns` excludes build/open/commit; immutable names with exclusive publication; writer/footprint diagnostics separate; prior negative evidence untouched; B4 policy frozen pre-run; host idleness assumed; **no** ordinary test/quality suite run; no automatic merge/promotion.
- **No rerun** was performed on a favorable or unfavorable outcome. The single result is preserved exactly as published by the runner.
- **Historical negative evidence intact:** PR 15H-C and PR 15I-D1-F remain performance-rejected, and the earlier A6 result remains unpaired historical context. B4 adds a cumulative B-only-increment comparison and changes none of them.
- **CI:** the push of this draft PR may trigger ordinary repository CI. It is informational only per explicit user instruction and was **not** awaited as an acquisition prerequisite; no CI gate was added or required.

---

## 10. Reproducing the read-only checks

```bash
CONFIG=benchmarks/studies/perf-06/warm/configurations/quervant-perf06b4-paired-warm-2026-11-25.json
RESULT=benchmarks/studies/perf-06/warm/results/quervant-perf06b4-paired-warm-2026-11-25-001.json
PYTHONPATH=benchmarks python3 -m quervant_bench validate --config "$CONFIG"
PYTHONPATH=benchmarks python3 -m quervant_bench analyze --result "$RESULT" \
  > docs/pr-artifacts/perf-06-b/b4/read-only-analysis.json
PYTHONPATH=benchmarks python3 -m quervant_bench report --result "$RESULT" \
  > docs/pr-artifacts/perf-06-b/b4/rendered-report.md
python3 docs/pr-artifacts/perf-06-b/b4/support/verify_b4_result.py \
  "$CONFIG" "$RESULT" docs/pr-artifacts/perf-06-b/b4/read-only-analysis.json
```
