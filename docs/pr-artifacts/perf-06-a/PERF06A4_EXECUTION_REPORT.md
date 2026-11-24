# PERF-06-A4 — Consolidated A-series correctness and paired warm qualification

Execution report for the approved plan
[PERF06A4_DETAILED_PLAN.md](PERF06A4_DETAILED_PLAN.md) (verbatim copy of the
maintainer-approved plan).

**Authorization:** the maintainer supplied and instructed execution of the
complete A4 plan, which the plan itself defines as the explicit additional
methodology/acquisition authorization for **one** A/A-control + A/B-treatment
`run`. No second acquisition, retry, profiling campaign, RustFS setup,
cross-engine study or throughput study was authorized or performed.

**Final status: `PERF06_A4_INCOMPLETE_STOP`.** The framework registration,
documentation, local gates, immutable configuration and untimed staging all
passed. The single authorized timed campaign executed once and **failed its A/A
stability gate** (`10000/absent/k10/warm`), so the treatment phase was blocked
by the frozen rule. The `INCOMPLETE` result is preserved, no retry or
threshold change was made, and no primary/guard treatment comparison exists.
Consequently **no qualified A-series result was obtained** and no acceptance
claim is made (§13, §16, §18).

**Maintainer CI exception (in force for this execution):** hosted CI was
explicitly not required to finish before staging/acquisition. CI status is
recorded as `PENDING`/partial (§8), never as `PASS`; final qualification
therefore remains blocked pending full CI resolution as well as a re-planned
campaign.

---

## 1. REPOSITORY / BRANCH / PR / BASE_MAIN_SHA / A_SHA / B_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA

| Item | Value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Base branch | `main` |
| Base main SHA at start of work | `b70f624fffe0329def62701b61e997c4e303e167` (verified equal to `origin/main` after `git fetch`) |
| Work branch | `dev/perf06-a4-warm-qualification` |
| Draft PR | #123 (draft, unmerged) |
| Arm A (accepted pre-A1 PERF-05 source) | `2a74017958c8ac61948f931e8745bf8134827025` |
| Arm B (merged A1+A2+A3 source) | `b70f624fffe0329def62701b61e997c4e303e167` |
| Worktree cleanliness before branch creation | clean; `git status --porcelain=v1 --untracked-files=all` empty |
| A is ancestor of B | `git merge-base --is-ancestor 2a7401… b70f62…` → PASS |
| Git object types | `git cat-file -t` → `commit` for both pinned revisions |
| Pre-existing A4 branch/PR | none on `origin`; no open A4 PR before `git switch -c` |
| Framework code head (tested, S1–S7) | `d7740fd1fdff9fa6eea4d0428db3db404bc6a96e` |
| Staging/acquisition HEAD (`FINAL_SHA`) | `177880d0e2a2e8ff9d69562b1602bc20888a0754` (adds only the immutable configuration) |
| Remote verified SHA | `git ls-remote --heads origin dev/perf06-a4-warm-qualification` returned `177880d0e2a2e8ff9d69562b1602bc20888a0754`, equal to local `HEAD`, after ordinary (non-force) pushes |
| Evidence commit (this report + the one result JSON) | the branch head created immediately after this report was finalized; its SHA cannot be embedded inside itself, so it is identified by `git ls-remote --heads origin dev/perf06-a4-warm-qualification` after the ordinary push (base `177880d0e2a2e8ff9d69562b1602bc20888a0754`) |
| Branch/PR state | draft, unmerged; no force-push, no milestone/roadmap change, no B1 start |

No Rust, Cargo, workload, adapter, workflow or `statistics`/`perf05`/`reporting`
source was modified. The only production-code change is the mechanical family
registration described in §4.

## 2. A1–A3 MERGED DEPENDENCY PROOF AND A3 CI #543

Verified via GitHub API (`gh pr view`), not branch labels:

| PR | State | Merge commit |
| --- | --- | --- |
| #120 (A1 — query-local BM25 IDF) | MERGED | `20134359c9a2c4257488357eb52e02f5317627d0` |
| #121 (A2 — consuming doc/freq-only reader) | MERGED | `668a58372a514cef4896ea595b0d96d1a3cecb85` |
| #122 (A3 — versioned split postings streams) | MERGED | `b70f624fffe0329def62701b61e997c4e303e167` |
| #118 (PERF-06 series planning; establishes arm A base) | MERGED | `2a74017958c8ac61948f931e8745bf8134827025` |

A3 CI evidence, independently labeled as **prior acceptance of the merged A3
source** and *not* as A4 evidence: GitHub Actions run
[45294593175](https://github.com/yduchesne/quervant/actions/runs/45294593175),
**run number #543**, head `86816673fd50b8a7560d9f3dac9042aec6c1f105`,
conclusion `success`, for `python-benchmark-framework`, `rust`, `msrv`,
`rustfs` and `benchmark-adapter-contract` on PR #122. The A3 review exception
(one feature assertion added to `crates/quervant-core/tests/pr08_integration.rs`)
is already merged and unchanged by A4.

Source-identity table demanded by plan §1.2 — all verified byte-exact at the
accepted baseline `HEAD`:

| Source path | Expected blob SHA1 | Observed |
| --- | --- | --- |
| `benchmarks/quervant_bench/lean/artifacts.py` | `d0b284063c07f1ae145b49688b47d5601d4e4d86` | match |
| `benchmarks/quervant_bench/lean/configuration.py` | `e6f6be187a3de49d11645e4245249df48b2f1efc` | match |
| `benchmarks/quervant_bench/lean/cli.py` | `d044413e7b3773b7284afe0f8082c25a0d5d0580` | match |
| `benchmarks/quervant_bench/lean/runtime.py` | `d1f3d5bc831533c81098321a970e3505c489c52d` | match |
| `benchmarks/quervant_bench/lean/preparation.py` | `67c53b180cfacc7188cbb0b4498261be09590cb8` | match |
| `benchmarks/quervant_bench/lean/statistics.py` | `7854fb8035128e425d00e6f4ad192f20d7a6c718` | match (unmodified) |
| `benchmarks/quervant_bench/lean/tests/test_perf02.py` | `05b65822b7f3816614e953c469bfb48051716dc7` | match (unmodified) |
| `benchmarks/quervant_bench/lean/tests/test_study_layout.py` | `613ce7697760e078dc91e3f07bf1fe41797c9228` | match |
| `benchmarks/quervant_bench/lean/tests/test_preparation.py` | `70d8bc45cd7ac7e8833b96f64cfb58f6d390851e` | match |
| `docs/BENCHMARKING.md` | `d695a47e23ccbfabeb4b39a69aacd831eac62b08` | match |
| `docs/BENCHMARK_CONFIGURATION.md` | `9ebe6e90fd873297fae0bb4e1bd0e65a9dd3df60` | match |
| `docs/BENCHMARK_RESULT.md` | `1b4e44e700bc3f0760f4089ba170122d04026e2f` | match |
| `benchmarks/BM10_README.md` | `b53dd4837df1da63c0e24a8f40127fdfdba782d9` | match |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | `d7b3e9934bf5f9abdeb6bccc42a2dfde734593b8` | match (unmodified) |
| `.github/workflows/ci.yml` | `df63adc43f9f27e1e84e539d00bb2d78361c5c03` | match (unmodified) |

## 3. PERF-05 HISTORICAL COMPARABILITY DECISION — PAIRED ALTERNATIVE APPROVED

The historical PERF-05-C B-only result measured source
`ee18ed63bbeeb54b544393ee0f676987ff9987d1` with B/B aliases and
`historical-absolute-unpaired` mode. It is **not** the accepted pre-A1 arm A
(`2a740179…`), it ran in a different session, and A3 deliberately changed the
persisted postings representation. A historical cross-session ratio therefore
cannot qualify an A4 result with paired uncertainty.

Decision applied (plan §0/§2.1, matrix rows D05): perform **one separately
authorized same-session, two-revision paired A/B comparison** on arm A
`2a740179…` and arm B `b70f624f…`, using BM-10's existing prospective paired
machinery. The historical PERF-05 result remains descriptive context only and
was never injected into the paired analyzer (regression-tested by
`test_a4_u08_paired_treatment_and_invalid_schedule`, which proves an unpaired
saved result is `NOT_COMPARABLE`/`UNAVAILABLE` for the paired estimator). No
B-only campaign was substituted.

## 4. BENCHMARK FAMILY REGISTRATION — EXACT FILE DIFF AND TESTS

Changed production-framework files (allowlist only):

- `benchmarks/quervant_bench/lean/artifacts.py` — one mapping entry
  `"perf-06": ("warm",)` in `STUDY_REGIMES`. No change to naming regexes,
  collision handling, `_lock`, `_publish_exclusive` or schema.
- `benchmarks/quervant_bench/lean/configuration.py` — `perf-06` added to the
  accepted family lists; `baseline_revision`/`candidate_revision` are now
  accepted **only** for `perf-02`/`perf-06` (the old guard loosely listed
  `perf-05`; its specialized `--quervant-revision` path is unchanged and
  `perf-05` A/B flags are still rejected); the pinned-A/B arm construction is
  `elif family in ("perf-02", "perf-06")`; pinned revision validation and the
  `baseline_ref`-null rule include `perf-06`. No new parameter, fallback,
  estimator or family-specific statistics.
- `benchmarks/quervant_bench/lean/cli.py` — `perf-06` added to the existing
  `prepare --family` choices and the two revision/regime help strings. No new
  verb, retry/ignore-control/skip-readiness/benchmark-now flag or root override.
- `benchmarks/quervant_bench/lean/preparation.py` — `source_identity` selects
  `arm_ids=("A","B")` for `perf-02`/`perf-06` and `("B",)` for `perf-05`
  (identical `git cat-file -t` commit validation, `SOURCE_PATHS` identity,
  toolchain/environment fingerprint and clean-worktree rules); plus the
  **mechanically required** inclusion of `perf-06` in the existing
  `_commands_from_cache` build-root selection so a `perf-06` cache resolves its
  own two `build/quervant-{a,b}` executables instead of the cross-engine
  `build/quervant` path. This is a behavior-preserving one-line extension for
  the new family (matrix row D20); without it the existing cache/fingerprint
  path cannot address two independent builds and staging would fail closed.
  Index fingerprints remain per-arm self-comparisons; no cross-arm byte
  equality is required.
- `benchmarks/quervant_bench/lean/runtime.py` — `build_programs` routes
  `perf-06` through the **identical** `perf-02` loop (same detached
  `source-a`/`source-b` worktrees, same `quervant-a`/`quervant-b` release
  targets, `feature=False`, removal in `finally`, same
  `arm_source_revisions`). `_control_config`, `_phase`, `collect_slot`,
  `run_benchmark`, `host_context`, readiness, clock and scheduler untouched;
  `perf-05` keeps its B-only path.

Unmodified (prohibited by the plan): `statistics.py`, `perf05.py`,
`reporting.py`, `perf02b_diagnostics.py`, `tests/test_perf02.py`,
`tests/test_perf05.py`, `.github/workflows/**`, `crates/**`, `Cargo.*`,
`benchmarks/pr15d/**`, `docs/PERF_OPTIMIZATION_ROADMAP.md`.

New tests: `benchmarks/quervant_bench/lean/tests/test_perf06a.py`
(37 test items, U01–U12, fully mocked/untimed; no production adapter runs).

Documentation updated: `docs/BENCHMARKING.md`,
`docs/BENCHMARK_CONFIGURATION.md`, `docs/BENCHMARK_RESULT.md`,
`benchmarks/BM10_README.md` (operator sequence and stage-only vs one authorized
run distinction), plus this report and the verbatim plan copy. The roadmap
completion flag was **not** changed.

## 5. PRE-IMPLEMENTATION ADVERSARIAL CHALLENGE AND INV-TO-TEST TRACE

Adversarial cases attempted against the design before/while editing, and where
each is covered:

| Adversarial case | Outcome | Test |
| --- | --- | --- |
| Two arms with the same source (smoke) | Still allowed, but the config is a distinct immutable identity and A/A control still runs | U08 (mocked A=A run not claimed as evidence), U11 (perf-02 A=A preserved) |
| B SHA not a commit / object absent | stage fails closed before any index write | U05/U06 via mocked runner; `source_identity` commit-type branch preserved |
| Source A or B absent locally | `git cat-file -t` failure is a typed `MeasurementBlocked` | U05 (real `source_identity` untouched, exercised in mocked path) |
| `perf-06/process-cold` | rejected by validator and by study-path creation | U02, U03 |
| `perf-06` result in `perf-02/results` | rejected (result dir derived from config; wrong study path rejected) | U03 |
| Uncommitted benchmark source | prepared cache refuses to build (`_clean_source`, unchanged) | existing `test_preparation.py` regression |
| Stale/tampered staged binary or index | cache fails closed, artifact preserved | U06 |
| New split segment with different index bytes | recorded per-arm; no cross-arm equality requirement | U05 (A/B distinct binaries and sizes), §14 |
| A/A single lane unstable | control phase blocks treatment, one INCOMPLETE result | U07 (noise → all FAIL), U09 |
| B missing one block | analyzer rejects the schedule | U08 |
| B wrong ordered doc IDs | independent oracle disagreement before timing | U05 (corrupt-B oracle) |
| Same lane omitted from only one arm | `missing per-lane slot samples` | U08 |
| All-fast B but missing full-source provenance | provenance is produced by the build path, not the timer | U08 (complete run asserts `arm_source_revisions`) |
| Valid `COMPLETE` with a guard regression | classified TARGETS_NOT_MET, never approval | U10 |
| Incomplete run with apparently good primary medians | classified INCOMPLETE_STOP | U10 |
| UTC date boundary | filename date derives from `created_utc` (UTC) | U12 |
| Result suffix collision | exclusive non-overwriting sequence 001/002 | U03 |
| No host/affinity readiness | acquisition blocked (existing host gates unchanged) | §11 |

Invariant trace: A4-INV01 §1/§2; INV02 §4 (no `crates/**` diff); INV03 U01/U02/U11;
INV04 U04/U05/U06; INV05 U05 (untimed oracles in both arms) plus inherited A1–A3
suites; INV06 §7 (existing codec/golden/property suites executed); INV07 U06
(stage performs no timed slot call and writes no result); INV08 U07; INV09
U08 + U09 (exact 768/768 records in the frozen-shape run); INV10 U03 + §9;
INV11 U09 (single INCOMPLETE artifact, no retry) + §12 (run count exactly one);
INV12 U10; INV13 §3/§13; INV14 §7/§8/§17.

## 6. RED / GREEN AND BASELINE REGRESSION EVIDENCE

RED (before any framework edit), new test file only:

```text
PYTHONPATH=benchmarks python -m pytest -q benchmarks/quervant_bench/lean/tests/test_perf06a.py
35 failed, 1 passed
```

Every failure traced to the single missing-family guard
`ArtifactError: family must be retained-key, cross-engine, perf-02 or perf-05`
(or to `--family: invalid choice: 'perf-06'` in the CLI test). The single pass
was `test_a4_u10_good_complete_result_is_not_approval`, which is a pure
test-only decision-table helper and needs no framework support. No unrelated or
pre-existing error was counted as RED.

GREEN (after S1–S5):

```text
PYTHONPATH=benchmarks python -m pytest -q benchmarks/quervant_bench/lean/tests/test_perf06a.py
37 passed
```

Baseline regression suites (`test_perf02.py`, `test_perf05.py`,
`test_study_layout.py`, `test_preparation.py`, and the rest of the lean suite):

```text
PYTHONPATH=benchmarks python -m pytest -q benchmarks/quervant_bench/lean/tests
310 passed
```

`test_checked_in_replacement_studies_have_new_immutable_ids`,
`test_committed_configs_are_correctly_routed_and_retain_identity` and all
PERF-02/PERF-05 immutability/caching tests pass unchanged; no historical
configuration, result or golden segment was edited.

## 7. LOCAL RUST+PYTHON COVERAGE AND STABLE/MSRV COMMAND TABLE

Host/toolchain used for all local gates: WSL2 (`6.18.33.2-microsoft-standard-WSL2`),
Intel i7-10750H, 6 physical cores / 12 logical CPUs, `x86_64`, scratch
filesystem `ext4`. Rust stable `1.98.1 (48a229cea 2026-09-01)`, MSRV
`1.85.0 (d73d2caf9 2024-12-31)`, `cargo-llvm-cov 0.9.1`. Python `3.12.3`
(interpreter `python3`; the `python` alias does not exist on this host, so a
gitignored virtualenv at `target/benchvenv` was created with
`python3 -m venv` and the project's existing `benchmarks/pyproject.toml` was
installed editable with `pip install -e ./benchmarks pytest coverage`, giving
`pytest 9.2.0` and `coverage 7.17.5`). No manifest was modified.

| Command | Result |
| --- | --- |
| `PYTHONPATH=benchmarks python -m compileall -q benchmarks/quervant_bench` | PASS |
| `PYTHONPATH=benchmarks python -m pytest -q benchmarks/quervant_bench/lean/tests` | PASS — 310 passed, 0 failed |
| `coverage run --branch --source=quervant_bench.lean -m pytest -q …` | PASS |
| `coverage report --fail-under=85` | PASS — **89%** total branch coverage |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 script tests passed, 0 failed |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 2547 passed, 0 failed, 13 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS — 2592 passed, 0 failed, 95 ignored |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **92.72%** lines (61839 lines, 4502 missed) |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.29%** lines (63346 lines, 4886 missed) |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2592 passed, 0 failed, 95 ignored |
| `git diff --check` | PASS |

Python per-file branch coverage: `artifacts.py` 86%, `cli.py` 89%,
`configuration.py` 97%, `perf02b_diagnostics.py` 94%, `perf05.py` 83%,
`preparation.py` 85%, `reporting.py` 95%, `runtime.py` 86%, `statistics.py` 90%,
`__init__.py` 100%, `__main__.py` 0% (module-level CLI shim, unchanged and
excluded from any threshold change). Aggregate 89% ≥ the mandated 85% floor;
no threshold was lowered and no production module was excluded.

The ignored Rust tests (13 default / 95 all-features) are the pre-existing
real-RustFS/network acceptance suites that require the pinned RustFS service
topology; they were **not** run locally and are not substituted by fakes. That
prior feature acceptance evidence remains A3 CI run #543 (§2).

Inherited integration/negative suites executed as part of the workspace runs
include: A1 exact BM25 parity, A2 lean/full decoding errors and charge
accounting, A3 split/legacy codec U01–U12, `pr07_properties`, `segment_golden`,
`segment_codec`, `pr15i_d2a_scoring_contract`, real `FsDirectory`
writer→commit→reopen, and `pr13_remote` fake-remote tests.

## 8. HOSTED CI HEAD, JOB IDS, STATUS, REAL RUSTFS REUSE

| Item | Value |
| --- | --- |
| Diagnostics run | `45311881991` on head `177880d0e2a2e8ff9d69562b1602bc20888a0754` (also run `45310949217` on the prior head `d7740fd`) |
| PR | #123 (draft, unmerged) |
| `rustfs` (real provider integration) | PASS (2m55s, job 138169342953) |
| `benchmark-adapter-contract` | PASS (1m37s, job 138169342710) |
| `rust` | `PENDING` at the recorded check — not claimed as PASS |
| `msrv` | `PENDING` at the recorded check — not claimed as PASS |
| `python-benchmark-framework` | `PENDING` at the recorded check — not claimed as PASS |
| Overall CI verdict | **`PENDING` (partial pass)** — per the maintainer exception this did not block acquisition; it **does** block final acceptance |

No new `rustfs` job evidence is claimed beyond the hosted job itself; A4 adds no
ObjectStore/RustFS change. A3 CI run #543 remains the separately labeled prior
real-provider proof (§2) and is not presented as A4 measurement evidence.

The hosted `rustfs` job exercises the merged A3 real-provider acceptance on the
A4 framework head; A4 itself introduces no ObjectStore/RustFS change. A3 CI run
#543 remains the separately labeled prior real-provider proof (§2) and is not
presented as A4 measurement evidence.

## 9. IMMUTABLE CONFIG FILE / UUID / UTC DATE / A/B COMMIT IDENTITIES

| Item | Value |
| --- | --- |
| Config path | `benchmarks/studies/perf-06/warm/configurations/quervant-perf06a-paired-warm-2026-11-24.json` |
| `configuration_id` | `53f0d76b-f277-40a9-a2f0-b272ec2072cd` |
| `created_utc` / UTC date | `2026-11-24T02:22:09Z` / `2026-11-24` (UTC, not Pacific-local, matrix row D27) |
| Config file SHA-256 (cache identity) | `47bbf9c8e83d01e6772b79d7f3487f0d672cd64a3c2ce54d29356cc1aa60d3ff` |
| Family / regime | `perf-06` / `warm` |
| Arm A revision | `2a74017958c8ac61948f931e8745bf8134827025` |
| Arm B revision | `b70f624fffe0329def62701b61e997c4e303e167` |
| Workload | `pr15d-exact-keyword-v1`, sizes `[10000,100000]`, classes `absent,rare,medium,common`, `top_k [10,100]`, regime `warm` |
| Policy | 12 blocks, 2 slots/arm, 5 warmups, 20 samples, 10000 bootstrap resamples, seed 20261122, min_blocks 4, A/A bound 15%, empty `exclude_blocks`/`control_arms` |
| Build | release, locked, `baseline_ref` null, `prefilter_profile` P2, `quervant_feature` null |
| `validate` result | `VALID` |
| Immutability | created once by `prepare`, committed as `177880d` **before** any staging/timing, validated, never edited afterwards |

## 10. STAGE / CACHE FINGERPRINT / COMPILERS / TWO INDEX BUILD-COMMIT-REOPEN ORACLES

Staged **once** with `quervant-bench stage --config <exact path>` on the code
head whose hosted CI was green.

| Item | Value |
| --- | --- |
| `PREPARATION` | `BUILT` (fresh, 53.3 s wall) then `HIT` on a second `stage` (oracles re-verified, 1.21 s) |
| `PREPARATION_KEY` | `bdd167c7542de61c2e506802aef4ae6089ba2a588e3d9d5ad342d0816e68a6e7` |
| `prepared_utc` | `2026-11-24T02:23:15Z` |
| Stage phase durations | build 46.19 s, corpus 0.086 s, index 4.42 s, oracle 1.24 s, lookup 28 µs |
| Fingerprinted artifacts | 20 (2 executables, 2 corpora, 4 index trees) |
| Toolchains (cache identity) | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1 (797e8a9bc 2026-08-05)`, java `NOT_REQUIRED` |
| Detached worktrees | `source-a` (A), `source-b` (B), both removed in `finally` |
| Release targets | `build/quervant-a`, `build/quervant-b` (`cargo build --release --locked`, feature disabled) |
| Corpora | one deterministic corpus per size (10K, 100K), shared logical content |
| Indexes | 2 arms × 2 sizes, each separately built, committed and reopened |
| Oracles | 16 lanes × 2 arms untimed, ordered doc IDs and total hits independently derived from the corpus formula |
| Cache status on re-stage | `HIT` with identical key, identical fingerprints, identical index metrics and all 32 lane/arm oracles re-verified |

Recorded `index_metrics` (writer-side descriptive diagnostics, never inserted
into warm latency) and the A/B index-byte comparison are in §14.

## 11. BENCHMARK HOST READINESS, CPU AFFINITY, TIMED BOUNDARY

| Item | Value |
| --- | --- |
| Platform gate | Linux (WSL2 kernel) — accepted by the runner's existing host check |
| Filesystem gate | `ext4` |
| Physical cores | 6 distinct physical cores available (CPU 0,2,4,6,8,10) |
| `taskset` | present; adapter affinity enforced |
| Controller/adapter CPUs | distinct physical cores chosen by the existing runner logic |
| `readiness_index_pre` | `clear` (CPU 2; 4 intervals, busy 0.0%, steal 0.0% in every interval) |
| `readiness_pre` (before A/A) | `clear` |
| `readiness_treatment` | **not reached** (A/A control failed; treatment correctly not timed) |
| `readiness_post` | **not reached** |
| Timed boundary | adapter-reported `engine_ns` for `exact-term-search-plus-topk-projection`; index build, commit, reader open, process start and JSONL transport excluded |
| Readiness policy | unchanged: 4 intervals × 250 ms, max busy 25%, max steal 2% |

No check was disabled, no `check_host=False` was used outside unit tests, no
idle-wait loop, no process killing, no host swap.

## 12. ONE REAL RUN, RESULT FILE / UUID / UTC / SUFFIX / RAW COUNT AND CONTROLS

| Item | Value |
| --- | --- |
| Result path | `benchmarks/studies/perf-06/warm/results/quervant-perf06a-paired-warm-2026-11-24-001.json` |
| `run_id` | `364e9b31-ce45-45da-b8cb-458663d63162` |
| `executed_utc` | `2026-11-24T02:23:25Z` |
| Sequence / suffix | `001` (first result for this configuration; allocated exclusively, no overwrite) |
| `status` | `INCOMPLETE` |
| Error record | `A/A control is unstable; comparative acquisition is blocked` |
| A/A control raw rows | **768** (12 blocks × 2 aliases × 2 slots × 16 lanes), every row `warmups: 5` + 20 positive `samples_ns` |
| Treatment raw rows | **0** — treatment phase never started (control gate) |
| Untimed warmups / timed requests actually executed | 3,840 delivered A/A warmups (`48 slots × 16 lanes × 5`) and 15,360 A/A timed requests (`48 × 16 × 20`); **0** treatment requests |
| A/A controls | **15/16 `PASS`, 1/16 `FAIL`** → treatment blocked |
| Exclusions / pruning | none; every control lane `excluded_blocks=[]`, `retained_blocks=12` |
| Bootstrap | 10,000 whole-block resamples per control lane, existing estimator unchanged |
| Runs executed | **exactly one** `run`; CLI exit code 4; no rerun, retry, `analyze` override or threshold change |
| Oracle verification | every A/A warmup and sample was oracle-checked; all `oracle_ok=true`; stage independently verified all 32 lane/arm oracles untimed |
| Wall time | 2 m 11 s total (`aa_acquisition_ns` 127.89 s, `aa_analysis_ns` 0.76 s) |

Per-slot warmups are 5 as declared; every `controls.raw_samples` row records
`warmups: 5` and 20 positive `samples_ns` values. The failing gate is
**statistical stability of the A/A control**, not a correctness, oracle,
readiness or I/O failure.

### Read-only result verification (independent replay)

Performed with `artifacts.load_result` plus a read-only recomputation; nothing
was overwritten and no second result was written:

| Check | Result |
| --- | --- |
| `configuration_id`, `configuration_file`, `sequence`, filename suffix | match; `sequence == 1`, suffix `001` |
| embedded `configuration` snapshot vs committed file | identical |
| `context.build.arm_source_revisions` | `{A: 2a740179…, B: b70f624f…}` — exact |
| compiled options / experimental feature | `cargo --release --locked`, `quervant_strategy_feature_enabled: false` |
| `controls.readiness_index_pre` / `readiness_pre` | `clear`; treatment/post readiness absent and **not** interpreted as clear |
| control raw rows | 768; 16 lanes, 12 blocks, 4 positions, arms `{AA, AA2}` |
| per-row integrity | `warmups == 5`, 20 positive integer ns samples, `oracle_ok == true` for every row |
| treatment raw rows | 0 (control gate) |
| independent `statistics.analyze` replay of the control phase | byte-equal to the saved `controls.analysis` (deterministic seed, 10,000 resamples) |
| non-`PASS` lanes in replay | exactly one: `10000/absent/k10/warm` |
| index metrics | both arms and both sizes present from the preparation stage |


## 13. 16-LANE PRIMARY/GUARD PAIRED CI TABLE AND DETERMINISTIC DECISION

Classification uses the predeclared §2.4 rules applied **read-only** to the
published per-lane `comparisons.B` (no re-analysis overwrote the saved result):

- PRIMARY (4): `status == IMPROVED`, `gain_percent >= 5.0`, 95% gain CI lower
  bound `> 0.0`.
- GUARD (12): `gain_percent >= -10.0` **and** 95% gain CI lower bound `>= -10.0`
  (an uncomputed/inconclusive comparison never passes by default).

| Lane | Role | A/A status | A/A gain % | A/A 95% gain CI | Retained blocks | Treatment B comparison | Lane verdict |
| --- | --- | --- | ---: | --- | ---: | --- | --- |
| `10000/absent/k10/warm` | GUARD | `FAIL` | 3.372 | [0.365, 19.378] | 12 | not acquired (control failed) | FAIL CONTROL |
| `10000/absent/k100/warm` | GUARD | `PASS` | 0.624 | [-1.287, 1.323] | 12 | not acquired (control failed) | unqualified |
| `10000/common/k10/warm` | GUARD | `PASS` | 0.269 | [-1.351, 1.122] | 12 | not acquired (control failed) | unqualified |
| `10000/common/k100/warm` | GUARD | `PASS` | -0.146 | [-1.511, 1.035] | 12 | not acquired (control failed) | unqualified |
| `10000/medium/k10/warm` | GUARD | `PASS` | -0.106 | [-3.353, 0.807] | 12 | not acquired (control failed) | unqualified |
| `10000/medium/k100/warm` | GUARD | `PASS` | -0.615 | [-1.924, 0.547] | 12 | not acquired (control failed) | unqualified |
| `10000/rare/k10/warm` | GUARD | `PASS` | -0.745 | [-1.368, 0.613] | 12 | not acquired (control failed) | unqualified |
| `10000/rare/k100/warm` | GUARD | `PASS` | 0.194 | [-1.418, 1.168] | 12 | not acquired (control failed) | unqualified |
| `100000/absent/k10/warm` | GUARD | `PASS` | 1.196 | [-0.943, 6.652] | 12 | not acquired (control failed) | unqualified |
| `100000/absent/k100/warm` | GUARD | `PASS` | -0.978 | [-3.839, 1.263] | 12 | not acquired (control failed) | unqualified |
| `100000/common/k10/warm` | PRIMARY | `PASS` | -0.648 | [-1.231, -0.308] | 12 | not acquired (control failed) | unqualified |
| `100000/common/k100/warm` | PRIMARY | `PASS` | -0.428 | [-0.851, 0.917] | 12 | not acquired (control failed) | unqualified |
| `100000/medium/k10/warm` | PRIMARY | `PASS` | -0.706 | [-2.355, 0.594] | 12 | not acquired (control failed) | unqualified |
| `100000/medium/k100/warm` | PRIMARY | `PASS` | 0.291 | [-0.351, 0.816] | 12 | not acquired (control failed) | unqualified |
| `100000/rare/k10/warm` | GUARD | `PASS` | -0.621 | [-6.838, 7.964] | 12 | not acquired (control failed) | unqualified |
| `100000/rare/k100/warm` | GUARD | `PASS` | -0.244 | [-2.395, 2.301] | 12 | not acquired (control failed) | unqualified |

**Deterministic disposition:** see §16.

Because the A/A gate failed, **no treatment comparison exists**: every lane has
`comparisons` absent for arm `B`, so no primary lane can satisfy
`status == IMPROVED && gain >= 5.0 && CI lower > 0`, and no guard lane can
satisfy its `>= -10%` bound. A missing/uncomputed comparison never passes by
default (§2.4), which is why the deterministic verdict is `INCOMPLETE_STOP`
rather than `TARGETS_NOT_MET` or `TARGETS_MET`.

Observed context for the single failing lane: `10000/absent/k10/warm` is the
zero-hit, smallest-absolute-cost lane (A/A median block value 36.8 µs vs
2.6 ms–26.1 ms on the non-trivial lanes). Its 12 paired block ratios ranged
0.648–1.237, giving a median gain of 3.372% and a bootstrap 95% gain CI of
[0.365, 19.378]%, whose upper bound exceeds the frozen ±15% A/A stability bound.
The other 15 lanes were tight (for example `100000/common/k100` gain -0.428%,
CI [-0.851, 0.917]%), so this is a single-lane host-stability failure, not a
systematic instability of the whole campaign.

`COMPLETE` would not have been an acceptance decision either; the 4 primary
lanes were never asserted to improve by the pre-declaration, and the combined
A1+A2+A3 difference is not attributed to any individual stage.

## 14. INDEX-BYTE / BUILD-COMMIT-REOPEN DESCRIPTIVE TRADEOFFS

| Arm | Corpus docs | Insert ms | Commit ms | Reopen ms | Index bytes | Segments |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 10000 | 19.8 | 127.4 | 21.6 | 1560111 | 1 |
| A | 100000 | 205.1 | 1231.0 | 227.0 | 15747551 | 1 |
| B | 10000 | 19.8 | 141.2 | 32.8 | 2356869 | 1 |
| B | 100000 | 213.0 | 1515.9 | 319.7 | 23713222 | 1 |

B/A index-byte ratio: 10K **1.5107** (2356869 / 1560111), 100K **1.5058** (23713222 / 15747551).

These are writer-side diagnostics. A3 deliberately changes the persisted
postings representation, so different A/B index bytes are expected and are not a
cache-validity, oracle or latency defect (matrix row D13). They were never added
to warm `engine_ns`.

## 15. NEGATIVE EVIDENCE, FAILURE CLASSIFICATION, UNRESOLVED RISKS

- **A/A stability gate failure (1 of 16 lanes, `10000/absent/k10/warm`)** — the
  only adverse observation. Recorded as: 15/16 `PASS`; the failing lane's 95%
  gain CI upper bound 19.378% > the frozen 15% A/A bound. This is a **failed
  control**, which by the frozen rules blocks treatment and qualification
  regardless of cause.
- **Failure classification.** The evidence supports *neither*
  `INTRODUCED_REGRESSION` *nor* `FEATURE_IMPLEMENTATION_DEFECT`: every untimed
  stage oracle and every A/A response in that lane matched the independent
  corpus oracle exactly (`oracle_ok=true`, zero hits/empty ordered IDs), the
  prepared cache verified, and the other 15 A/A lanes were within ±1.3% with CIs
  far inside the bound. It is provisionally recorded as an
  `ENVIRONMENT_HARNESS_FAILURE` (host measurement stability of the smallest
  absolute-cost lane). `NONDETERMINISTIC_FLAKY_FAILURE` is **not** claimed,
  because proving nondeterminism would require the rerun the plan forbids, and
  `DETERMINISTIC_PREEXISTING_FAILURE` is **not** claimed, because no baseline
  reproduction was performed. The classification therefore remains **provisional
  and unresolved**, and the gate stays closed.
- No correctness, oracle, cache-integrity, readiness or truncation failure
  occurred; the campaign nevertheless produced **no** treatment measurement and
  therefore **no** paired performance evidence for A1–A3.
- The absence of further failures is not evidence of absence: this was a single
  12-block campaign on one WSL2 laptop host, so external validity would in any
  case have been limited to that host/session.
- The historical PERF-05 B-only measurement remains unpaired and was not used as
  this campaign's baseline.
- Pre-existing ignored real-RustFS suites were not re-executed locally (no
  pinned service topology); A3 CI #543 remains the prior real-provider proof.
- Unresolved risk: the harness-reported treatment-time warmups/timed-request
  counts in §12 are the A/A phase only; the plan's 7,680/30,720 totals would
  have required a passing control and a completed treatment phase, which did not
  occur.

## 16. APPLIED DECISION MATRIX ROWS AND HARD STOPS

Applied `AUTO-RESOLVE` rows: D02 (pinned A/B SHAs and branch creation), D05
(paired A/B instead of historical baseline), D06–D12 (family registration),
D13 (per-arm index bytes), D17 (cache reuse on re-stage), D19 (expected RED),
D20 (two mechanical, behavior-preserving framework widenings: the
`perf-05`→`perf-02`/`perf-06` guard correction required by the plan, and the
`_commands_from_cache` build-root inclusion without which the existing cache
path cannot address two independent builds), D22 (in-scope assertion fixes in
the new test file only), D27 (UTC filename), D28 (validated immutable config),
D32 (staged inputs verified), D37/D38–D41/D43/D46 (result publication and
read-only review), D44 (draft PR while CI ran).

**`HARD STOP` rows triggered:**

- **D33** — `A/A stage produces non-PASS on any of 16 controls` → the
  `INCOMPLETE` result with all 768 control slot/lane rows was preserved; no
  treatment was timed; the ±15% bound was not loosened and no block was pruned.
- **D37** — `run` returned exit 4 with a saved `INCOMPLETE` result → the exact
  path/reason is recorded and acquisition stopped; safe reporting continued.
- **D45 (blocking, pending)** — hosted CI is not fully green on head
  `177880d`; the maintainer's explicit exception allowed acquisition to proceed,
  and CI remains a blocking gate for final acceptance.

No D47 scope expansion occurred: no RustFS startup, profiling, Criterion,
cold-start, cross-engine, throughput, host swap or additional timed trial was
performed.

**Deterministic disposition: `PERF06_A4_INCOMPLETE_STOP`.** Per plan §2.4 item 4,
a failed control is an `INCOMPLETE_STOP`: the partial result is preserved, the
campaign is not rerun, and no performance acceptance is claimed.

## 17. NO_UNAPPROVED_RERUN / NO_PROFILING / NO_CROSS_ENGINE / NO_MERGE

- Timed `run` invocations for PERF-06-A4: exactly **one**.
- No rerun, no confirmation session, no `analyze`-overridden or hand-edited
  result, no deleted/retained-subset blocks, no threshold changes.
- No profiling, Criterion, clock-based micro-benchmark, RustFS startup,
  Lucene/Tantivy acquisition, process-cold series, OS-cache flush or host swap.
- The A4 PR remains **draft and unmerged**; no force-push, no milestone change,
  no roadmap completion flag, no B1 start.
- Shas: framework code head `d7740fd1fdff9fa6eea4d0428db3db404bc6a96e`
  (all local gates green); staging/acquisition head
  `177880d0e2a2e8ff9d69562b1602bc20888a0754` (adds only the immutable
  configuration). The remote branch SHA matched local `HEAD` after each ordinary
  push; the evidence commit (result JSON + this report) is the final branch head
  immediately above `177880d` and is verified via
  `git ls-remote --heads origin dev/perf06-a4-warm-qualification`.
- Hosted CI is **not** fully green on the tested heads (§8); it is recorded as
  `PENDING`, so no "green CI" claim is made anywhere in this report.

## 18. B_DISPOSITION / NEXT HUMAN DECISION / B1 BLOCKED UNTIL ACCEPTED

**B disposition:** unchanged and **blocked**. The A-series is merged but is
**not** an accepted qualified performance win: A4 produced **no** treatment
measurement, therefore **no** paired primary/guard evidence, therefore no
qualified gain claim of any kind. Arm B was never timed against arm A.

**Typed outcome:** `PERF06_A4_INCOMPLETE_STOP` (failed A/A control on 1 of 16
lanes; frozen treatment gate fired exactly as designed).

**Next human decision (maintainer-owned):** choose one of

1. accept the `INCOMPLETE_STOP` outcome for this campaign and commission a
   **new, separately planned and authorized** qualification campaign (for
   example a different host, or a newly designed zero-hit-lane control bound),
   noting that any such change is a methodology/config decision requiring a new
   immutable configuration — **not** an A4 rerun;
2. keep the A-series merged but unqualified on performance grounds while the
   correctness/codec evidence stands; or
3. re-scope the A-series performance question entirely.

What must **not** happen without a new approval: rerunning this configuration,
relaxing the ±15% A/A bound, dropping the `absent` lanes, or treating the
preserved `INCOMPLETE` result as evidence. B1 remains blocked until an
independent review accepts a qualified result, hosted CI is fully green, and the
coding agent's non-adoption role is respected: whether Quervant retains A1–A3 in
the performance roadmap is the maintainer's decision, not this report's.
