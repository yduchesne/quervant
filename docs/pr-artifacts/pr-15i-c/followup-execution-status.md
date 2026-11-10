# PR 15I-C follow-up — execution status

## Disposition

**`15IC_NOISE_DIAGNOSTIC_BLOCKED`** — the A/A environment-stability control
failed, so the outside-dispatch operator was **not** implemented, no nine-lane
performance campaign was run, and production remains byte-identical to merged
PR 15I-B.

External statuses, reported separately: `REAL_RUSTFS_BLOCKED` (no container
runtime on the host), `HOSTED_CI_PENDING`, `REVIEW_PENDING`, `NOT_PUSHED`,
`NOT_MERGED`.

## 1. Phase outcomes

| Phase | Status | Evidence |
|---|---|---|
| P0 preflight, source pins, baseline QA, invariant challenge | PASS | `followup-preflight.md`, `followup-invariant-traceability.md` |
| P1-A prospective protocol/controller/verifier/tests frozen before sampling | PASS | `noise_protocol_v2.json` + tooling commits, 60 new tests |
| P1-B eight campaigns (4 A/A + 4 A/G), fixed interleaved order | **COMPLETE, all valid** | `target/pr15i-c/noise-diagnostics-v2/`, 8 receipts |
| P1-B aggregate criteria | **A/A FAIL → BLOCKED** | `noise-v2-series-aggregate.json` |
| P2 restore operator + outside dispatch | **NOT EXECUTED** (gated on P1-B) | — |
| P3 `N-U`/`N-I`/`N-F` suites | **NOT EXECUTED** (no candidate source) | — |
| P4 frozen nine-lane campaign | **NOT EXECUTED** | — |
| P5 rollback | not needed: no production edit was made (`NC-D83`) | protected diff empty |
| P6 reporting | this document set | — |

Final local HEAD for this report: `986999f420c51cbefa0cb7d7cb67ed7e410f60ce`
(report data unchanged by any later docs-only commit).

## 2. Production identity

| Check | Result |
|---|---|
| `git diff --quiet 6f6463cb… HEAD -- crates/quervant-core/src crates/quervant-core/Cargo.toml Cargo.lock .github/workflows/ci.yml` | empty |
| `benchmarks/pr15i_c/protocol.json` | unchanged (`5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e`) |
| `benchmarks/pr15i_c/noise_protocol_v2.json` | diagnostic-only; SHA-256 `f99ecce69db5815ac798aed826c8c9e0e11ab75a1c68840f3e887488fcd8203d` |
| `benchmarks/pr15d`, `benchmarks/pr15i_a`, `benchmarks/pr15i_b` | unchanged |
| Old negative artefacts (`paired-01`, `generic-boundary-01..04`, `codegen-01..03`, `fixup-*.md`) | untouched |

Changed paths in this session are confined to `benchmarks/pr15i_c/` (new noise
protocol, controller, verifier and tests) and `docs/pr-artifacts/pr-15i-c/`
(new `followup-*.md` reports).

## 3. Commit identities

| Role | SHA |
|---|---|
| `MERGED_15IB_A_SHA` | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| `BRANCH_START` | `fe069b9ec5b2ccbd1da583e26ff8ede10b295b6c` |
| Tooling SHA 1 (`pr15i-c-noise-v1`) | `d86e6e3535ff415b0ac16ee8a4964ddc205c9a28` |
| Tooling SHA 2 (`pr15i-c-noise-v2`, per-campaign band fix) | `ed1e50f7a7d5533facb26048f9bf7fa9e16697e6` |
| Tooling SHA 3 (unique worktree names) | `ff58c93b622ff8647f97b016e7750876d35fd0ca` |
| `B_IMPLEMENTATION_SHA` / `B_MEASURED_SHA` | **not created** |

## 4. Final QA at the settled tree

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS (135 test binaries) |
| `cargo test --workspace --all-targets --all-features` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS |
| `cargo llvm-cov … --fail-under-lines 85` | PASS — `TOTAL` lines **92.68%** |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108) |
| `python3 -m unittest discover -s benchmarks/pr15d/harness` | PASS (139) |
| `python3 -m unittest discover -s benchmarks/pr15i_b` | PASS (10) |
| `python3 -m unittest discover -s benchmarks/pr15i_c` | PASS (150) |
| `python3 -m unittest discover -s benchmarks/pr15i_a` | 87 tests, 1F/3E — `SOURCE_BOUND_HISTORICAL_ONLY`, unchanged from base |
| `git diff --check` | CLEAN |

Real-boundary gate: **`REAL_RUSTFS_BLOCKED`** — no `docker`/`podman` on the host,
so the pinned `rustfs/rustfs@sha256:1803faef…` suites (`pr15i_c_rustfs`,
`pr15i_b_rustfs`, `pr13_remote`, `pr13_remote_proxy`) could not be executed. No
fake store was substituted and no compiled-but-ignored test is counted as run.

## 5. Preserved evidence

| Artefact | Location |
|---|---|
| Eight sealed v2 campaigns + 8 receipts + aggregate receipt | `target/pr15i-c/noise-diagnostics-v2/`, `target/pr15i-c/reviews/` |
| Invalidated v1 campaign and v2 attempt-1 campaigns | `target/pr15i-c/noise-diagnostics/`, `target/pr15i-c/noise-diagnostics-v2-attempt1/` |
| Historical rejected candidate campaign | `target/pr15i-c/campaigns/paired-01` (read-only) |
| Historical F0 diagnostics/codegen | `target/pr15i-c/layout-diagnostics/` (read-only) |
| Tooling | `benchmarks/pr15i_c/{noise_protocol_v1,noise_protocol_v2,noise_diag,verify_noise_diag}.py/json` |
| Reports | `docs/pr-artifacts/pr-15i-c/followup-*.md` |

## 6. Residual risk and next step (not authorized here)

The 10K absent lane (~50–90 µs/query) is not measurable to better than ~±15% per
campaign with 10 samples × 8 blocks, even when both arms are the same binary. Any
future attempt to measure a layout change on this lane needs a stability control
that is specified before data and is sensitive enough to distinguish a 2–4%
effect — e.g. more measured samples per slot, more campaigns, or a per-lane
stability criterion — plus the same A/A-first discipline. That requires a new,
separately approved plan; this one explicitly forbids inventing it.
