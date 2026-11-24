# PERF-06-A4 — Consolidated A-series correctness and paired warm qualification

Execution report for the approved plan
[PERF06A4_DETAILED_PLAN.md](PERF06A4_DETAILED_PLAN.md) (verbatim copy of the
maintainer-approved plan).

**Authorization:** the maintainer supplied and instructed execution of the
complete A4 plan, which the plan itself defines as the explicit additional
methodology/acquisition authorization for **one** A/A-control + A/B-treatment
`run`. No second acquisition, retry, profiling campaign, RustFS setup,
cross-engine study or throughput study was authorized or performed.

**First campaign status: `PERF06_A4_INCOMPLETE_STOP`.** The framework
registration, documentation, local gates, immutable configuration and untimed
staging all passed. The single authorized timed campaign executed once and
**failed its A/A stability gate** (`10000/absent/k10/warm`), so the treatment
phase was blocked by the frozen rule. The `INCOMPLETE` result is preserved, no
retry or threshold change was made, and no primary/guard treatment comparison
exists. Campaign 1 therefore obtained **no qualified A-series result** (§1–§18
remain its record, including §13, §16 and §18).

**A4 status after the second authorized acquisition:
`PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED`.** The maintainer
subsequently authorized exactly one further real campaign on the **unchanged**
configuration. That campaign completed structurally (all 16 A/A controls PASS,
768 control + 768 treatment slot/lane records, all oracles verified) and
produced fully qualified paired evidence, but **2 of the 4 pre-declared PRIMARY
lanes fell below the 5.0% median-gain threshold**, so the frozen target gate is
**not met**. All 12 GUARD lanes passed. No threshold, workload, statistic or
methodology change was made, no rerun is implied, and adoption remains a human
decision. The second campaign is documented separately in
[PERF-06-A4 — Second Authorized Acquisition](#perf-06-a4--second-authorized-acquisition).

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
| A/A single lane unstable | control phase blocks treatment and publishes one INCOMPLETE result | U07 (injected A/A divergence → all FAIL), U09 |
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
| PR | #123 (draft, unmerged) |
| Recorded CI check | `gh pr checks 123` at **2026-11-24T02:33:43Z**, run `#548` (`45312567690`) on evidence head `42e562c`, i.e. *after* acquisition and the original evidence commit. No continuous polling was performed. |
| `benchmark-adapter-contract` | PASS (1m07s, job 138171642457) |
| `python-benchmark-framework` | PASS (3m19s, job 138171642745) |
| `rustfs` (real provider integration) | PASS (2m24s, job 138171642826) |
| `rust` | `PENDING` at the recorded check — not claimed as PASS |
| `msrv` | `PENDING` at the recorded check — not claimed as PASS |
| Overall CI verdict | **`PENDING`** on the evidence head at the recorded check. Per the maintainer exception this did not block acquisition; it **does** block final framework-source acceptance. |
| Earlier heads | Runs `#545` (`d7740fd`), `#546` (`177880d`), `#547` (`4f12dc8`) were still `in_progress` at the recorded checks; they are not cited as passes. |
| This fixup commit | Documentation-only and pushed after the check above. Its own CI outcome is by definition unverified at write time and must be read from `gh pr checks 123`; it is **not** claimed green here. |

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

Staged **once** with `quervant-bench stage --config <exact path>` on commit
`177880d0e2a2e8ff9d69562b1602bc20888a0754`, whose framework implementation had
been fully validated by the mandatory **local** gates (§7). Hosted CI for that
head was **still pending** when staging and acquisition began; it did not report
success. The maintainer explicitly authorized acquisition before hosted CI
completion (§8), and final qualification still requires successful mandatory
hosted CI. Nothing in this report asserts that CI passed at staging time.

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
CI [-0.851, 0.917]%), so the failure is isolated to a single lane rather than a
systematic instability across the campaign. Its **cause is undetermined** (§15):
the description above is evidence of *what* was observed, not an attribution of
why.

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
- **Observed failure vs. cause — deliberately separated.**
  - *Established observation:* exactly one of 16 A/A control lanes failed. The
    failed lane is `10000/absent/k10/warm`; its apparent A/A gain is **+3.3717%**
    with a bootstrap 95% gain interval of **+0.3646% to +19.3781%**. The
    **upper confidence bound**, not the point estimate, exceeds the approved
    +15% A/A stability limit, so the frozen rule rejected the control. All
    correctness oracles passed in both arms and during staging; host-readiness
    checks were `clear`; **no treatment observations were acquired**.
  - *Root cause: **UNDETERMINED**.* No evidence collected in this campaign
    isolates a cause. Candidate explanations that remain **unproven** include
    environment/harness instability (host scheduling, thermal or clock
    variability), statistical variability intrinsic to this very short-duration,
    zero-hit lane, or an A/A control-design sensitivity for that lane. None of
    these is a verified diagnosis.
  - *Explicit non-claims:* this event is **not** classified as confirmed
    `NONDETERMINISTIC_FLAKY_FAILURE` (proving nondeterminism would require a
    repeat the plan forbids), **not** as a proven
    `ENVIRONMENT_HARNESS_FAILURE` or infrastructure failure, **not** as
    `INTRODUCED_REGRESSION` or `FEATURE_IMPLEMENTATION_DEFECT` (no code-path or
    correctness signal exists — every oracle matched, the prepared cache
    verified, and the other 15 A/A lanes stayed within ±1.3% with CIs far inside
    the bound), and **not** as `DETERMINISTIC_PREEXISTING_FAILURE` (no baseline
    reproduction was attempted).
  - *Consequence:* the classification remains **undetermined**, the gate stays
    closed, and the disposition stays `PERF06_A4_INCOMPLETE_STOP`. Resolving the
    cause requires a **separately planned and independently authorized**
    follow-up investigation or qualification study; this PR neither diagnoses it
    nor authorizes any rerun, alternate host, relaxed threshold or lane removal.
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
- Unresolved risk: the warmup/timed-request counts in §12 are the **A/A phase
  only**; the plan's 7,680 warmup / 30,720 timed-request totals would have
  required a passing control plus a completed treatment phase, neither of which
  occurred. No treatment-time counts exist and none are inferred.

## 16. APPLIED DECISION MATRIX ROWS AND HARD STOPS

Classification follows the approved plan's own categories.

**`AUTO-RESOLVE` rows applied:** D02 (pinned A/B SHAs and branch creation), D05
(paired A/B instead of historical baseline), D06–D12 (family registration),
D13 (per-arm index bytes), D17 (cache reuse on re-stage), D19 (expected RED),
D20 (two mechanical, behavior-preserving framework widenings: the
`perf-05`→`perf-02`/`perf-06` guard correction required by the plan, and the
`_commands_from_cache` build-root inclusion without which the existing cache
path cannot address two independent builds), D22 (in-scope assertion fixes in
the new test file only), D27 (UTC filename), D28 (validated immutable config),
D32 (staged inputs verified), **D37** (`run` returned exit 4 with a saved
`INCOMPLETE` result → record the exact path/reason, stop acquisition, continue
safe read-only reporting), and D38–D41/D43/D46 (result publication and
read-only review).

**`DEFER AND CONTINUE` row applied:** **D44** — hosted CI was pending when the
code head was pushed. Its dependent gate (final framework-source acceptance) is
preserved as blocked while all independent, safe work (documentation, the
approved acquisition under the maintainer exception, and read-only result
verification) continued. D44 is *not* a hard stop and was not treated as one.

**`HARD STOP` row triggered:**

- **D33** — `A/A stage produces non-PASS on any of 16 controls` → HARD STOP. The
  `INCOMPLETE` result with all 768 control slot/lane rows was preserved; no
  treatment was timed; the ±15% A/A bound was not loosened and no block was
  pruned or retried.

**Conditional `HARD STOP` row not triggered:** **D45** applies only when hosted
CI actually **fails** on the exact code head. At the recorded checks CI was
**pending**, not failed, so D45 was not triggered and no CI-failure claim is
made. If CI subsequently fails, D45 becomes active for the affected framework
source and final qualification stays blocked until a narrow fixup and a new
mandatory-gate pass.

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
lanes; frozen treatment gate fired exactly as designed). **Root cause:
UNDETERMINED** (§15) — the failure is established, its explanation is not.

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

---

# PERF-06-A4 — Second Authorized Acquisition

This section is a **separate, appended record** for the one additional real
campaign the maintainer explicitly authorized after campaign 1 failed its A/A
stability gate. Sections §1–§18 above remain the unchanged record of
**campaign 1** (`PERF06_A4_INCOMPLETE_STOP`); nothing there is rewritten,
reclassified or superseded as evidence. Neither campaign's artifacts are
modified, regenerated, renamed, reanalyzed into a replacement, or deleted.

## S1. Explicit maintainer authorization

- The maintainer explicitly authorized **one additional real PERF-06-A4
  A/A + A/B benchmark campaign** following the unsuccessful first acquisition.
- That authorization supersedes the original A4 plan's one-acquisition
  restriction and its prohibition on repeating the existing configuration
  **for this one additional acquisition only**. It does not authorize a third
  acquisition, a different host, relaxed thresholds, a different workload, a
  removed lane, or a stability/profiling investigation.
- The previously granted exception permitting acquisition while hosted CI is
  pending also applied. Final qualification still requires successful mandatory
  CI.
- This was explicitly **not** a stability investigation: no diagnosis of
  campaign 1's failed A/A lane was attempted, and no statistical methodology,
  benchmark-framework source, control bound or host-readiness policy was changed.

## S2. Framework and source SHAs

| Item | Value |
| --- | --- |
| PR / branch | #123 / `dev/perf06-a4-warm-qualification` (draft, unmerged) |
| Locally tested framework head | `d7740fd1fdff9fa6eea4d0428db3db404bc6a96e` (all mandatory local gates, §7) |
| Acquisition branch head | `ad94e179f63c8820be8a733482c91618cdb0ed14` (campaign 1 fixup documentation commit) |
| Framework source change since `d7740fd` | **none** — `git diff d7740fd..ad94e17 -- benchmarks/quervant_bench crates Cargo.toml Cargo.lock .github/workflows benchmarks/pr15d` is empty |
| Prepared-input build source revision | `177880d0e2a2e8ff9d69562b1602bc20888a0754` (as recorded by the verified cache) |
| Arm A revision | `2a74017958c8ac61948f931e8745bf8134827025` (commit object; ancestor of arm B) |
| Arm B revision | `b70f624fffe0329def62701b61e997c4e303e167` (commit object) |
| Worktree state before acquisition | clean; no uncommitted source changes; no benchmark process running |

## S3. Configuration ID and prepared-cache identity

| Item | Value |
| --- | --- |
| Configuration (reused unchanged) | `benchmarks/studies/perf-06/warm/configurations/quervant-perf06a-paired-warm-2026-11-24.json` |
| `configuration_id` | `53f0d76b-f277-40a9-a2f0-b272ec2072cd` (no new configuration was created) |
| `validate` | `VALID` |
| Workload / policy | unchanged: 16 warm lanes, 10K+100K, absent/rare/medium/common, K10+K100, 12 blocks × 2 slots/arm, 5 warmups + 20 samples, 10,000 bootstrap resamples, seed `20261122`, ±15% A/A bound, empty `exclude_blocks` |
| `PREPARATION` | `HIT` — the existing prepared cache passed validation (source identity, release/locked build settings, executable/index fingerprints, per-arm index identity) |
| `PREPARATION_KEY` | `bdd167c7542de61c2e506802aef4ae6089ba2a588e3d9d5ad342d0816e68a6e7` |
| `prepared_utc` | `2026-11-24T02:23:15Z` (reused, not rebuilt) |
| Untimed oracles re-verified | all **32** lane/arm oracles (`oracle_ns` 1.18 s), both arms × both sizes × 8 lanes |
| Stage phase durations | `preparation_ns` 1.37 s total (`lookup_ns` 0.125 s, `oracle_ns` 1.18 s); no rebuild, no re-index |
| Cache integrity | verified; no completed-cache corruption encountered (that would have been a HARD STOP) |

## S4. Actual host readiness and CPU affinity

| Item | Value |
| --- | --- |
| Host | Linux `x86_64` (WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`), filesystem `ext4` |
| Physical cores available | 6 distinct physical cores (CPU 0, 2, 4, 6, 8, 10) |
| Controller CPU / adapter CPU | `0` / `2` (distinct physical cores) |
| Affinity enforcement | `taskset -c <cpu>` for every adapter invocation (unchanged) |
| `readiness_index_pre` | `clear` |
| `readiness_pre` (before A/A) | `clear` |
| `readiness_treatment` (before A/B) | `clear` |
| `readiness_post` (after A/B) | `clear` |
| Readiness policy | unchanged: 4 intervals × 250 ms, max busy 25%, max steal 2% |

## S5. Result path, run ID, timestamp and status

| Item | Value |
| --- | --- |
| Result path (printed by the CLI) | `benchmarks/studies/perf-06/warm/results/quervant-perf06a-paired-warm-2026-11-24-002.json` |
| `run_id` | `235a6714-a194-4786-85cf-dcabbb9c5a33` |
| `executed_utc` | `2026-11-24T02:45:57Z` (actual UTC execution date; filename suffix allocated by the publisher) |
| `configuration_id` | `53f0d76b-f277-40a9-a2f0-b272ec2072cd` (same configuration, new result identity) |
| Sequence | `002` — allocated exclusively; `-001.json` untouched |
| Overall status | **`COMPLETE`** (CLI exit code 0) |
| A/A control records | **768** — 12 blocks × 2 aliases × 2 slots × 16 lanes, every row `warmups: 5`, 20 positive samples, `oracle_ok=true` |
| Treatment records | **768** — 12 blocks × 2 arms × 2 slots × 16 lanes, same per-row integrity |
| Excluded blocks | none (`excluded_blocks: []`, `retained_blocks: 12` in every lane) |
| Errors | none (`errors: []`) |
| Treatment paired ratios / resamples | 12 paired block ratios and 10,000 bootstrap resamples per lane |
| Wall time | 257.4 s total: A/A acquisition 124.6 s, A/A analysis 0.74 s, A/B acquisition 126.8 s, A/B analysis 0.75 s |
| `run` invocations under this authorization | **exactly one** |

### Read-only verification performed after publication

| Check | Result |
| --- | --- |
| `artifacts.load_result` + filename/sequence/UUID consistency | PASS (`sequence == 2`, suffix `002`) |
| Embedded configuration vs committed file | identical |
| `context.build.arm_source_revisions` | `{A: 2a740179…, B: b70f624f…}` exact; `cargo --release --locked`; feature disabled |
| Readiness records (`index_pre`, `pre`, `treatment`, `post`) | all four present and `clear` |
| Independent `statistics.analyze` replay of control and treatment phases | both reproduce the saved analyses exactly |
| Non-`PASS` A/A lanes in replay | none (16/16 `PASS`) |
| Block-exclusion / pruning contamination | none: no exclusions, 12 retained blocks in every lane |

## S6. All 16 A/A control outcomes

All 16 controls passed the frozen ±15% signed-gain **and** confidence-interval
test, so the treatment phase was authorized and executed.

| Lane | A/A status | A/A ratio B/A | A/A gain % | A/A 95% gain CI | Blocks |
| --- | --- | ---: | ---: | --- | ---: |
| `10000/absent/k10/warm` | `PASS` | 0.99176 | +0.8243 | [+0.1236, +1.5602] | 12 |
| `10000/absent/k100/warm` | `PASS` | 0.99162 | +0.8383 | [-0.3779, +1.9054] | 12 |
| `10000/common/k10/warm` | `PASS` | 1.00711 | -0.7108 | [-2.1302, +2.3567] | 12 |
| `10000/common/k100/warm` | `PASS` | 0.99967 | +0.0327 | [-0.7879, +1.1848] | 12 |
| `10000/medium/k10/warm` | `PASS` | 1.00102 | -0.1017 | [-1.6069, +1.1232] | 12 |
| `10000/medium/k100/warm` | `PASS` | 0.99418 | +0.5820 | [-0.4845, +1.6421] | 12 |
| `10000/rare/k10/warm` | `PASS` | 0.99318 | +0.6822 | [-0.4225, +1.8707] | 12 |
| `10000/rare/k100/warm` | `PASS` | 0.99705 | +0.2946 | [-0.7288, +1.2817] | 12 |
| `100000/absent/k10/warm` | `PASS` | 1.03045 | -3.0450 | [-4.7582, +1.1578] | 12 |
| `100000/absent/k100/warm` | `PASS` | 1.00067 | -0.0667 | [-0.8365, +0.2506] | 12 |
| `100000/common/k10/warm` | `PASS` | 1.00499 | -0.4989 | [-1.0904, +0.5659] | 12 |
| `100000/common/k100/warm` | `PASS` | 0.99871 | +0.1286 | [-1.6646, +0.9784] | 12 |
| `100000/medium/k10/warm` | `PASS` | 1.01019 | -1.0191 | [-1.8469, -0.1053] | 12 |
| `100000/medium/k100/warm` | `PASS` | 1.00918 | -0.9176 | [-1.5257, +0.7750] | 12 |
| `100000/rare/k10/warm` | `PASS` | 1.00381 | -0.3809 | [-3.1402, +4.2407] | 12 |
| `100000/rare/k100/warm` | `PASS` | 1.00921 | -0.9213 | [-2.1552, +0.0243] | 12 |

## S7. All 16 A/B treatment outcomes

Treatment arm `B` vs baseline arm `A`, existing `median-paired-ratios-v1`
estimator over 12 paired whole-block ratios with a deterministic 10,000-resample
bootstrap 95% interval. Positive gain = `B` faster than `A`. Latencies are the
per-arm median block values (mean of two slot medians per block).

| Lane | Role | A median (baseline) | B median (candidate) | Paired gain % | 95% gain CI | Analyzer status | Acceptance |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| `10000/absent/k10/warm` | GUARD | 30.6 µs (30600 ns) | 30.7 µs (30650 ns) | -1.2310 | [-3.1939, +0.4062] | `INCONCLUSIVE` | MET (≥−10%) |
| `10000/absent/k100/warm` | GUARD | 30.0 µs (30049 ns) | 30.1 µs (30138 ns) | +0.0420 | [-1.3482, +1.0617] | `INCONCLUSIVE` | MET (≥−10%) |
| `10000/common/k10/warm` | GUARD | 2.566 ms (2565905 ns) | 2.409 ms (2409150 ns) | +5.8958 | [+3.6543, +7.4562] | `IMPROVED` | MET (≥−10%) |
| `10000/common/k100/warm` | GUARD | 2.616 ms (2615791 ns) | 2.476 ms (2476195 ns) | +4.7998 | [+3.4791, +7.0204] | `IMPROVED` | MET (≥−10%) |
| `10000/medium/k10/warm` | GUARD | 1.318 ms (1318147 ns) | 1.268 ms (1268117 ns) | +4.4111 | [+2.6382, +5.6961] | `IMPROVED` | MET (≥−10%) |
| `10000/medium/k100/warm` | GUARD | 1.410 ms (1410042 ns) | 1.371 ms (1371331 ns) | +2.8178 | [+0.5951, +4.3133] | `IMPROVED` | MET (≥−10%) |
| `10000/rare/k10/warm` | GUARD | 38.5 µs (38537 ns) | 38.3 µs (38288 ns) | +0.4255 | [-0.3877, +2.2492] | `INCONCLUSIVE` | MET (≥−10%) |
| `10000/rare/k100/warm` | GUARD | 38.4 µs (38386 ns) | 38.2 µs (38212 ns) | +1.1621 | [-0.8892, +1.5173] | `INCONCLUSIVE` | MET (≥−10%) |
| `100000/absent/k10/warm` | GUARD | 156.0 µs (155979 ns) | 153.4 µs (153405 ns) | +1.1929 | [-1.3393, +4.5639] | `INCONCLUSIVE` | MET (≥−10%) |
| `100000/absent/k100/warm` | GUARD | 151.3 µs (151310 ns) | 148.5 µs (148527 ns) | +1.5549 | [+0.2947, +4.6862] | `IMPROVED` | MET (≥−10%) |
| `100000/common/k10/warm` | PRIMARY | 25.977 ms (25976519 ns) | 24.069 ms (24069075 ns) | +6.7170 | [+5.1504, +7.6908] | `IMPROVED` | MET (≥5.0% and CI>0) |
| `100000/common/k100/warm` | PRIMARY | 25.371 ms (25370600 ns) | 23.831 ms (23831241 ns) | +5.6911 | [+5.2082, +6.6823] | `IMPROVED` | MET (≥5.0% and CI>0) |
| `100000/medium/k10/warm` | PRIMARY | 13.033 ms (13032967 ns) | 12.583 ms (12582505 ns) | +3.3231 | [+1.9095, +4.0474] | `IMPROVED` | NOT MET (median gain 3.32% < 5.0%) |
| `100000/medium/k100/warm` | PRIMARY | 12.870 ms (12869916 ns) | 12.598 ms (12598080 ns) | +2.1053 | [+1.3508, +3.7259] | `IMPROVED` | NOT MET (median gain 2.11% < 5.0%) |
| `100000/rare/k10/warm` | GUARD | 160.1 µs (160116 ns) | 161.3 µs (161302 ns) | -1.1717 | [-2.3698, +3.5529] | `INCONCLUSIVE` | MET (≥−10%) |
| `100000/rare/k100/warm` | GUARD | 156.8 µs (156777 ns) | 158.0 µs (157989 ns) | -0.9207 | [-3.9648, +3.2376] | `INCONCLUSIVE` | MET (≥−10%) |

## S8. Primary/guard effect sizes, confidence intervals and qualification

Pre-declared rules (unchanged, applied read-only to the published per-lane
`comparisons.B`):

- **PRIMARY (4 lanes)** — `100000/medium/k10`, `100000/medium/k100`,
  `100000/common/k10`, `100000/common/k100`: require analyzer status
  `IMPROVED`, median gain **≥ 5.0%**, and 95% gain CI lower bound **> 0.0%**.
- **GUARD (12 lanes)** — every 10K lane plus 100K absent/rare K10/K100: require
  median gain **≥ −10.0%** and 95% gain CI lower bound **≥ −10.0%**.

| Lane | Role | Median gain % | 95% gain CI | Analyzer status | Gate |
| --- | --- | ---: | --- | --- | --- |
| `100000/common/k10/warm` | PRIMARY | **+6.7170** | [+5.1504, +7.6908] | `IMPROVED` | **MET** |
| `100000/common/k100/warm` | PRIMARY | **+5.6911** | [+5.2082, +6.6823] | `IMPROVED` | **MET** |
| `100000/medium/k10/warm` | PRIMARY | **+3.3231** | [+1.9095, +4.0474] | `IMPROVED` | **NOT MET** (gain < 5.0%) |
| `100000/medium/k100/warm` | PRIMARY | **+2.1053** | [+1.3508, +3.7259] | `IMPROVED` | **NOT MET** (gain < 5.0%) |

- **Primary: 2 of 4 met.** Both `100000/common` lanes clear 5.0% with CI lower
  bounds above 5.1%; both `100000/medium` lanes improve significantly (their CI
  lower bounds are above 1.3%) but fall short of the 5.0% median-gain threshold.
- **Guard: 12 of 12 met.** The worst guard lane is `10000/absent/k10` at
  −1.2310% (CI [−3.1939, +0.4062]), far inside the −10% limit. No lane is
  `REGRESSED`.
- **Deterministic disposition:**
  `PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED`.
  The run is statistically and structurally valid and `COMPLETE`, but one or
  more pre-declared thresholds fail, so per plan §2.4 item 2 the result is
  preserved as-is, no rerun is authorized, already-merged A3 is **not**
  reverted, **A is not marked accepted**, and the maintainer decides whether to
  adopt, iterate or re-plan.
- **Attribution limit:** this is a cumulative A1+A2+A3 treatment difference. It
  does not identify how much of the effect comes from A1, A2 or A3
  individually, and no per-stage speedup is claimed.
- The A/A control values in §S6 are **not** performance evidence and are not
  used to infer treatment results.

## S9. Index sizes and build/commit/reopen diagnostics (separate from query latency)

Writer-side descriptive metrics from the reused, verified preparation cache —
never inserted into warm `engine_ns`:

| Arm | Corpus docs | Insert ms | Commit ms | Reopen ms | Index bytes | Segments |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 10000 | 19.8 | 127.4 | 21.6 | 1560111 | 1 |
| A | 100000 | 205.1 | 1231.0 | 227.0 | 15747551 | 1 |
| B | 10000 | 19.8 | 141.2 | 32.8 | 2356869 | 1 |
| B | 100000 | 213.0 | 1515.9 | 319.7 | 23713222 | 1 |

B/A index-byte ratio: 10K **1.5107**, 100K **1.5058**. Cache `bdd167c7…` (identical to campaign 1: same prepared inputs, unchanged).

## S10. CI status, limitations and remaining gates

| Item | Value |
| --- | --- |
| CI check before acquisition | `gh pr checks 123` at **2026-11-24T02:45:46Z**, run `#549` on head `ad94e179f63c8820be8a733482c91618cdb0ed14` |
| `benchmark-adapter-contract` | PASS (1m48s) |
| `python-benchmark-framework` | PASS (2m47s) |
| `rustfs` (real provider) | PASS (2m35s) |
| `msrv` | PASS (7m13s) |
| `rust` | **`PENDING`** at the recorded check — not claimed as PASS |
| Aggregated CI verdict at acquisition time | **`PENDING`** (no mandatory failure known), so acquisition proceeded under the explicit maintainer exception |
| Earlier heads | Runs `#545` (`d7740fd`), `#546` (`177880d`), `#547` (`4f12dc8`) completed successfully; `#548` (`42e562c`) was still in progress at its recorded check and is not cited as a pass |
| This evidence commit | Documentation/result-only, pushed after the check above; its own CI outcome is unverified at write time and must be read from `gh pr checks 123`. **No CI success is claimed for it.** |

**Remaining gates and limitations**

1. Final framework-source acceptance still requires successful mandatory CI on
   the exact head; a known mandatory CI failure is a stop for affected
   acceptance work (CI failure would mark qualification blocked, not measured
   data invalid).
2. The target gate is **not met**: 2 of 4 primary lanes are below 5.0%. Adopting
   the A-series on performance grounds, iterating, or re-planning is a
   maintainer decision; this report makes no adoption claim and does not revert
   merged A3.
3. Single-host, single-session evidence: one 12-block paired campaign on one
   WSL2 laptop host; external validity is limited to that host/session.
4. The historical PERF-05 B-only measurement remains unpaired and was not used
   as a baseline.
5. No profiling, Criterion run, cold-start, cross-engine, throughput, RustFS
   start, host swap, block exclusion, threshold change or additional timed
   trial accompanied this campaign. Exactly one `run` was executed under this
   authorization; no further authorization is implied.
6. The A/A bound remains ±15%, the seed `20261122`, the 5.0% primary target and
   the −10% guard bound; none were adjusted before or after seeing the result.
