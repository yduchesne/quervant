# QA and attestation record (BM-09)

All results below were produced locally on the execution tree described in
`verification-report.md`. Where a gate cannot be observed from this terminal it is
recorded as `UNVERIFIED`, never as a pass.

## Mandatory framework QA roster

| Roster item | Command | Result |
| --- | --- | --- |
| `python-full-suite` | `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py'` | **PASS** — 1,195 tests, 0 failures, 0 skips (pinned venv active) |
| `official-deterministic` | `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_official_*.py'` | **PASS** — 230 tests |
| `official-real-aa` / `official-real-correctness` / `official-data-integrity` / `official-independent-verification` | covered by the deterministic official suite against complete fixture evidence | **PASS (fixture-only, explicitly not real evidence)** |
| `benchmark-scripts` | `bash benchmarks/scripts/test-scripts.sh` | **PASS** — 108 script tests |
| `bm-contract-inventory` | `python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef64… --check docs/pr-artifacts/bm-01/legacy-inventory.json` | **PASS** |
| `python-compileall` | `python -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py` | **PASS** |
| `retained-key-l2` | `test_retained_key_*` inside the full suite | **PASS** |
| `cross-engine-l2` | `test_cross_engine_*` inside the full suite | **PASS** |
| `installed-console` | `pip install -e ./benchmarks` in `target/bm09-venv`; `quervant-bench inspect --experiment synthetic-contract-smoke --format json`; `test_cli.py` | **PASS** — console contract executes (the previous local skip is closed) |
| `official-source-set` | `verify_source_identity` in `test_qualification_contracts` | **PASS** after the single controlled re-freeze |
| `official-g0-review` | independent reviewer approval | **BLOCKED** — no reviewer artifact exists |

## Mandatory source QA roster

| Roster item | Command | Result |
| --- | --- | --- |
| `rust-fmt-stable` | `cargo fmt --all -- --check` | **PASS** |
| `rust-fmt-msrv` | `cargo +1.85.0 fmt --all -- --check` | **PASS** |
| `rust-clippy-stable-default` | `cargo clippy --workspace --all-targets -- -D warnings` | **PASS** |
| `rust-clippy-stable-all-features` | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| `rust-clippy-msrv-all-features` | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| `rust-test-stable-default` | `cargo test --workspace --all-targets` | **PASS** |
| `rust-test-stable-all-features` | `cargo test --workspace --all-targets --all-features` | **PASS** |
| `rust-test-msrv-all-features` | `cargo +1.85.0 test --workspace --all-targets --all-features` | **PASS on rerun**; observed one **flaky** failure of `search::unified::d3c_tests::u43_replacement_witness_all_variants` (see below) |
| `rust-coverage-85` | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **PASS** — 92.04% lines (92.70% regions, 87.72% functions) |
| `rust-doc` | `cargo doc --workspace --all-features --no-deps` | **PASS** |
| `rust-bench-no-run` | `cargo bench --workspace --no-run` | **PASS** (compile only) |
| `rustfs-real-hosted` | hosted `rustfs` job on the final source SHA | **UNVERIFIED** — no local RustFS service and CI cannot be observed from this terminal |
| `adapter-build-{quervant,tantivy,lucene}` | `cargo build --release --locked` for two adapters, `sha256sum -c A1-CHECKSUMS.sha256` for Lucene | **NOT EXECUTED** — no G0 authorization, so no build/binary freeze was attempted |
| `adapter-correctness-10k-100k` | `comparative-full-correctness` workflow | **UNVERIFIED** — requires hosted CI |
| `source-binary-digests` | `official.historical.verify_legacy_sources_unchanged` | **PASS** — 32 frozen legacy files match the checked-in manifest |
| `host-capability-readiness` | not sampled | **NOT EXECUTED** — no authorized measurement |

## Known failures and classifications

| Failure | Classification | Evidence |
| --- | --- | --- |
| `benchmarks/pr15d/harness/test_pr15d.py::ComparativeWorkflowContractTests::test_t01_standard_ci_keeps_only_the_required_jobs` | **3 — deterministic pre-existing** | Fails identically on a clean worktree of baseline `a5a8303`; the assertion expects only `rust, msrv, rustfs` but CI also has `python-contracts` (added in BM-06). PR15D files may not be edited by BM-09. |
| `quervant-core` `search::unified::d3c_tests::u43_replacement_witness_all_variants` | **4 — flaky, pre-existing, untouched crate** | Reproduced intermittently (≈1 in 8–14 focused runs) under both stable and 1.85; `crates/` has zero diff on this branch; passes on rerun and in the full stable/1.85 runs. |
| `benchmarks/pr15i_d3_c/test_verify.py` | pre-existing skip | Its module-level `dry-proof` fixture is unavailable without T6 artifacts. |

## Controlled synthetic re-freeze ledger

Exactly one re-freeze after the final Python edit, because
`SOURCE_DIRECTORIES` gained `benchmarks/quervant_bench/official` and
`qualification/publication.py` changed:

| Anchor | Before | After |
| --- | --- | --- |
| `source_set_digest` | `sha256:4d707657…28d7` | `sha256:c9f07779…c814` |
| `framework_qa_digest` | `sha256:eae537ae…8134` | `sha256:992eb15 9…72cd` |
| `source_qa_digest` | `sha256:b91e5ca3…fadb` | `sha256:910ddfcf…1b56` |
| `profile_digest` | `sha256:9db01390…046c` | unchanged |

Only `source_set_digest`, per-check `evidence_digest`, the two QA evidence
`source_set_digest` fields and the anchors were rewritten (canonical JSON). The
fixtures remain `synthetic`/`simulated` and are **not** official QA evidence.

## CI

`python-contracts`, `rust`, `msrv`, `rustfs` on the final commit and the
`comparative-full-correctness` correctness workflow are **UNVERIFIED** from this
terminal: pushing/observing GitHub Actions was not possible here. No real timed
measurement was run in any CI job, and none may be.

---

# RF09-F1 addendum

- Official deterministic suite is now **259 tests** (was 230): G0-authority, backend
  layout, verifier authority, QA pinning, independent parity, publication preflight
  and packaging-metadata cases were added red-first.
- Full Python suite: **1,224 tests, 0 skips** in `target/bm09-venv`.
- Rust gates unchanged in scope and all passing; `cargo llvm-cov … --fail-under-lines
  85` reports **92.03% lines**.
- Single controlled synthetic re-freeze after the final Python edit:
  `source_set_digest` → `sha256:606ebcc9…768d`, `framework_qa_digest` →
  `sha256:c2f69f79…d762`, `source_qa_digest` → `sha256:a41a4139…a902`, profile
  unchanged. A post-freeze recomputation equals the anchor.
- Six generated `benchmarks/quervant_bench.egg-info/*` files were removed from the
  index and `**/*.egg-info/` added to `.gitignore`; no other generated artefact is
  tracked.
- Hosted CI and hosted RustFS remain **UNVERIFIED** from this terminal (`gh` returns
  401). No real timed measurement was run in any CI job.

---

# RF09-F2 addendum

- Official suite is now **300 tests** (F1: 259). New suites:
  `test_official_qa_evidence.py` (executed-QA artifacts) plus verified-admission and
  complete-matrix cases in the existing modules.
- Full Python suite: **1,265 tests, 0 skips** in `target/bm09-venv`.
- One controlled synthetic QA re-freeze after the final Python edit:
  `source_set_digest` → `sha256:57eb22fa…2b70`, `framework_qa_digest` →
  `sha256:cc7f704e…32cdb`, `source_qa_digest` → `sha256:7dab23a7…613e`, profile
  unchanged. Recomputing the source digest after the freeze equals the anchor.
- Rust gates all pass; `cargo llvm-cov … --fail-under-lines 85` reports
  **92.04% lines**.
- Executed-QA evidence for a real run does **not** exist in this repository: the
  production reader is implemented and tested against generated fixture bytes only.
  A real Gate D therefore remains `QA_UNVERIFIED/BLOCKED` until an independently
  approved operator/CI evidence root exists.
- Hosted CI remains **UNVERIFIED** from this terminal (`gh` 401); run #393 belongs to
  the previous commit and is not final-head evidence.

---

# RF09-F3 addendum (2026-11-17)

- Official suite: **313 tests** (F2: 300). New `StandaloneGateCProvenanceTests`
  (11 cases) prove that a coherent in-memory admission forgery is rejected at the
  public Gate C boundary.
- Full Python suite: **1,278 tests, 0 skips** in `target/bm09-venv`.
- QA evidence suite: **23 tests**, now with three deterministic root cases
  (`REPO_ROOT` → `BM_UNSAFE_INPUT`, `REPO_ROOT/benchmarks` → `BM_UNSAFE_INPUT`,
  guaranteed-absent child → `BM_FILE_MISSING`). The hosted-runner failure in run
  #394 came from the removed `target/bm09-venv` assumption.
- One controlled synthetic re-freeze after the final Python edit:
  `source_set_digest` → `sha256:79186989…cb98`, `framework_qa_digest` →
  `sha256:140158d2…068ed8`, `source_qa_digest` → `sha256:631d9788…62e6d`, profile
  unchanged. Post-freeze recomputation equals the anchor.
- Rust gates all pass; coverage **92.04% lines** (`cargo llvm-cov --workspace
  --all-targets --all-features --fail-under-lines 85`).
- Hosted final-head CI **UNVERIFIED** from this terminal (`gh` 401). The prior run
  #394 remains the last observed run and is *not* final-head evidence.

---

# RF09-F4 addendum (2026-11-17)

- Official suite: **333 tests** (F3: 313). Full Python: **1,298 tests, 0 skips**
  after the controlled re-freeze.
- Scripts 108 PASS; compileall, module `inspect`, installed console and legacy
  contract inventory PASS.
- Rust 1.98.1: fmt, clippy (default + all features), tests (default + all
  features), doc and `bench --no-run` PASS. Coverage run 1 failed on the known
  `u43` flake; run 2 measured **92.04% lines** over the whole workspace
  (`cargo +1.98.1 llvm-cov --workspace --all-targets --all-features
  --fail-under-lines 85`). Both runs are retained.
- Rust 1.85.0: fmt and clippy PASS; the MSRV test run keeps the known `u43`
  nondeterminism (see the RF09-14 diagnosis: 21/25 pass on F3, 23/25 on main).
- One controlled synthetic re-freeze (sequence 1) after the final Python edit:
  source `sha256:07af5bf4…ed3280`, framework QA `sha256:d62073f9…ebef`,
  source QA `sha256:9960a739…41df`, profile unchanged.
- Hosted CI for this checkpoint: **UNVERIFIED** (`gh` API returns HTTP 401).

---

# RF09-F4 Addendum A (2026-11-17)

Rust acceptance for the RF09-14 repair (parent anchors unchanged because the change
is outside the frozen source roster):

| Gate | Result |
| --- | --- |
| `rf09_14_tests` | 12/12 pass on 1.85.0 and 1.98.1, default and all features |
| `u43` focused repetitions | 10/10 on 1.85.0, 10/10 on 1.98.1 |
| `pr15i_d3_c` integration | 22 tests pass (both toolchains, both feature sets) |
| Workspace tests | pass, both toolchains, default and all features |
| clippy `-D warnings` | pass (1.98.1 default/all-features, 1.85.0 all-features) |
| fmt | clean for 1.98.1 and 1.85.0 |
| `cargo doc`, `cargo bench --no-run` | pass (compile only, no timing) |
| Workspace line coverage | **92.08%** (`cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85`) |
| Local real RustFS suites | not executed here; the hosted `rustfs` job remains authoritative |

The `rust-msrv` synthetic QA fixture keeps its simulated PASS value unchanged; it is
fixture preservation, not the real MSRV result. The real MSRV/local results are the
ones above.

---

# RF09-F4 Addendum B (2026-11-17)

| Gate | Result |
| --- | --- |
| Targeted official modules | 127 tests PASS |
| Full Python suite | **1,299 tests, 0 skips** |
| Scripts / inventory / compileall / console | PASS (108 script tests) |
| Rust (1.98.1 default + all features, 1.85.0 all features) | fmt, clippy, tests, doc, `bench --no-run` PASS |
| Workspace line coverage | **92.08%** |
| Synthetic re-freeze (Addendum B sequence 1) | source `sha256:7922c1a8ef7a98173901951e24c86c2d4ab38ce31092cb1fd4ab86d582a9b638`, framework QA `sha256:8b169b5e8894fe7d88b5b3f83bd7c62504a6e92d6a3d9c1fd96a64829280981f`, source QA `sha256:e5a96aea95716206dde4e8a44be26ab1af55f4999764dc268605d600790f8562`, profile unchanged |
| Diagnostic scope checks H01–H06 | executed, all as specified (branch reverted afterwards) |
| Local real RustFS suites (RF09-19) | NOT EXECUTED this session; hosted `rustfs` remains the only real-service evidence |
| Hosted CI on this head | **UNVERIFIED** (`gh` returns HTTP 401) |

---

# RF09-F4 Addendum B erratum (2026-11-17)

- Full Python suite: **1,299 tests, 0 skips** (local) after the erratum's Python test
  edits; hosted run #397 for the previous head reported 1,299 tests with one existing
  missing-authentic-archive skip and 92.08% coverage.
- Rust gates: fmt/clippy/tests on 1.98.1 (default + all features) and 1.85.0 PASS;
  workspace line coverage **92.08%**.
- Diagnostic v2 executed in detached overlay worktrees only; the committed harness,
  the BM-01 whitelist and the historical baseline bytes are unchanged.
- Controlled re-freeze: source `sha256:81bcdecc…a734`, framework QA
  `sha256:e3f178dd…aba9`, source QA `sha256:15732a6a…dbd0`, profile unchanged.
- Local real RustFS suites: **not executed**; probes show `podman`/`podman compose`
  available and `docker` unavailable. Hosted `rustfs` (#397) is not local acceptance.

---

# RF09-F4 Addendum B erratum — round 2 (2026-11-17)

- RF09-16 executed on the actual old code: B-R01/B-R02 show the **40-byte** ledger
  deficit (expected 4828, actual 4788; scope 4788 in the batch case) and B-R03 shows
  `CorruptIndex("exact-set capacity grew after reservation")`, with all three old
  function bodies verified byte-identical.
- RF09-19 executed locally with Podman: `pr13_oracle`, `pr13_oracle_geo` and
  `m1_batches` each ran their named real RustFS test and exited 0 under an owned
  project; container, volume and network removed afterwards.
- RF09-17 not executed; the A-U01…A-U12 assertion ledger in
  `review-fixup-evidence.md` lists every missing row.
- Python/Rust source unchanged this round (last green: 1,299 Python tests / 0 skips,
  Rust gates on 1.98.1 and 1.85.0, 92.08% line coverage).

---

# RF09-F4 Addendum B — QA and attestation after RF09-17 (2026-11-18)

- Python source, QA baseline files and scripts are **byte-identical** to the last green
  round: the only file changed between `15b962f` and `b94a4d1` is
  `crates/quervant-core/src/search/unified.rs`. No controlled re-freeze was required and
  none was performed; the anchors remain source set
  `sha256:81bcdecc4f7019c6805b2db91ea8ae108c45d47d523b4e83077baaad40e9a734`,
  framework QA `sha256:e3f178ddc94f91e856dc0bb7b48218ed2be01fe468bdd0dff61cef71583baba9`,
  source QA `sha256:15732a6a0cef3a4100a8dbec34eadac4b7bb1b235c3f4173bf89a2d59a88dbd0`,
  profile `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c`.
- Re-verified anyway on the unchanged tree: `python -m unittest discover -s
  benchmarks/quervant_bench/tests -p 'test_*.py'` → **1,299 tests, 0 failures**
  (511.6 s).
- Rust acceptance for the changed crate: 18/18 `rf09_14_tests` executed individually
  (12-row ledger, `f4b/rf09-17-ledger.json`), full workspace 2,505 passed (default) and
  2,549 passed (all-features) on 1.98.1, 2,505 passed on 1.85.0, 92.67 % line coverage.
- QA evidence remains synthetic-only in this round: no real timed acquisition, no engine
  launch, no fabricated G0/T6 authorization. The QA baseline hashes above are the
  synthetic control provenance; they do not authorize a real qualification.

- Real-boundary acceptance on the final head: the three RustFS suites
  (`pr13_oracle`, `pr13_oracle_geo`, `m1_batches`) were re-executed on `e61e7dc` with an
  owned Podman topology and each exited 0 with its named real test; the owned project
  network was removed and no owned container or volume remains. The service credentials
  were redacted from every captured log.
