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
