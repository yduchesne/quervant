# PR 15I-D0 execution status

**Final status: `15ID0_BLOCKED`.**

The D0 diagnostic tooling, source proof, controller, independent verifier and
adversarial tests are complete and pass locally. **No performance measurement
exists**: both the canonical three-engine campaign and the paired A/Q/P campaigns
are blocked by the same frozen-input defect (stale PR 15D Quervant adapter
lockfile at BASE). No optimization is delivered, no current cross-engine ratio is
published, and PR 15I-D1 is not authorized.

## 1. Source and working-tree state

| Item | Value |
|---|---|
| Branch | `dev/pr15i-d0-attribution-02` |
| Base / branch parent | `7237bce325834d6cc1c73735697be29bc60ef16b` |
| D0 commit | recorded in the handoff message; see `git log -1` on the branch |
| `origin/main` | `4606f92e…` (PR #92 docs closeout only; `D0-X83`) |
| Tracked changes vs BASE | only `docs/BENCHMARKING.md`, `docs/ROADMAP.md` |
| Added paths | `benchmarks/pr15i_d0/*` (10 files), `docs/pr-artifacts/pr-15i-d0/*` (6 files) |
| Protected diff (`crates/`, `Cargo.toml`, `Cargo.lock`, `.github/`, `AGENTS.md`, `benchmarks/pr15d/`, `benchmarks/pr15i_c/`) | empty |
| Raw evidence | local only under ignored `target/pr15i-d0/`; not committed |

## 2. Gate status

| Gate | Status | Evidence |
|---|---|---|
| `D0-P00 SOURCE` | PASS for identity; build blocked | preflight PASS; protected diff empty; adapter lock defect |
| `D0-P01 CORPUS` | PASS | re-derived manifest `69052c66…` matches protocol |
| `D0-P02 CANONICAL` | **BLOCKED** | `run.py` exit 5 `X15_BUILD_FAILED`; `NO_CURRENT_3_ENGINE_RATIO` |
| `D0-P03 PATCH` | PASS for derivation; build blocked | independent source proof `VERIFIED`; derivative fingerprint `09d7b8cd…` |
| `D0-P04 BUILD` | **BLOCKED** | `cargo build --locked` refuses the stale adapter lock |
| `D0-P05 FORMAT` | NOT REACHED | requires real index builds |
| `D0-P06 ORACLE` | NOT REACHED | unit-level oracle logic tested only |
| `D0-P07 CAMPAIGNS` | **BLOCKED** | 0 of 48 slots, 0 of 8,640 samples, 0 of 96 probes, 0 of 8 index builds |
| `D0-P08 SEAL` | NOT REACHED (unit-tested only) | seal/inventory/adversarial tests pass |
| `D0-P09 STABILITY` | NOT MEASURED | no campaigns |
| `D0-P10 INTRUSION` | NOT MEASURED | no campaigns |
| `D0-P11 STAGES` | NOT MEASURED | no P samples |
| `D0-P12 INDEPENDENT` | PARTIAL | 95 D0 tests pass; T63/T64 not fully covered (see traceability) |
| `D0-P13 DOCS` | PASS | evidence-bound, no speedup claim, blocked status in roadmap |
| `D0-P14 QA` | PASS | see §3 |
| `D0-P15 EXTERNAL` | `CI_PENDING`, `REVIEW_PENDING`, no PR | GitHub token invalid; local handoff only |

## 3. Repository QA commands (final tree)

All commands were run from the tooling branch after the final code/test/doc
changes, except the two five-minute-plus Rust suites which were started before
the documentation-only additions; documentation does not affect them.

| Command | Result |
|---|---|
| `python3 -m unittest discover -s benchmarks/pr15i_d0 -p 'test_*.py'` | **PASS** — 95 tests, 0 failures |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | **PASS** — 83 tests, 0 failures |
| `python3 benchmarks/pr15i_c/test_run.py` | **PASS** — 12 tests, 0 failures |
| `cargo fmt --all -- --check` (stable 1.98.1) | **PASS** |
| `cargo +1.85.0 fmt --all -- --check` | **PASS** |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| `cargo test --workspace --all-targets` | **PASS** — 2,439 passed, 0 failed, 13 ignored |
| `cargo doc --workspace --no-deps` | **PASS** |
| `cargo bench --workspace --no-run` | **PASS** |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | **PASS** — 93.17% lines (96,274 lines, 6,571 missed; regions 88.05%; functions 92.62%) |
| `git diff --check` | **PASS** |
| protected-path diff from BASE | **PASS** — empty |
| `python3 -m py_compile benchmarks/pr15i_d0/*.py` | **PASS** |
| real A/Q/P vertical slice (§9.1) | **BLOCKED** — no frozen A/QP binaries can be built |
| real RustFS tests | **NOT APPLICABLE** — measurement-only change; no production behavior touched |

The Rust workspace was already at ≥85% coverage before D0; D0 does not raise or
modify the production coverage baseline. Coverage is recorded as evidence that
the unchanged workspace still passes its existing gate.

## 4. What was actually produced

- `benchmarks/pr15i_d0/protocol_v1.json` — the frozen closed protocol.
- `benchmarks/pr15i_d0/patch_instrumented_source.py` — deterministic,
  insertion-only materializer with anchor/cardinality checks.
- `benchmarks/pr15i_d0/source_proof.py` — independent rebuild + byte reversal +
  allowlist + feature/`#[inline]`/`pub` checks.
- `benchmarks/pr15i_d0/run.py` — `preflight`, `source-proof`, `build`,
  `campaign`, `seal`.
- `benchmarks/pr15i_d0/verify.py` — independent recomputation, seal/inventory,
  oracle, ratios, stability, intrusion, per-sample stage partition, closed
  hypothesis ranking.
- Four adversarial test modules (95 tests total).
- This report set and the `BENCHMARKING.md`/`ROADMAP.md` status links.

Real measured evidence produced: **none**. The only verified real artifacts are
the source identity, corpus digest, preflight environment and the byte-reversible
diagnostic source derivation. The disposable compile smoke is recorded separately
and is never used as timing evidence.

## 5. Privacy and evidence audit

- Committed documentation contains only relative repository paths and commit
  SHAs; no absolute host paths, usernames, credentials or raw artifact contents.
- Raw corpora, indexes, logs and the source-proof JSON (which contains local
  absolute paths) stay under ignored `target/pr15i-d0/`.
- No raw artifact is claimed to be published in GitHub.
- No failed run was overwritten, re-sealed or repaired.

## 6. External gates

| Gate | State |
|---|---|
| Push | **NOT DONE** — `gh` token invalid; ordinary push credentials not assumed |
| Pull request | **NOT CREATED** — no fabricated PR number |
| Hosted CI | `CI_PENDING` |
| Independent review | `REVIEW_PENDING` |
| Merge | **NOT DONE** |

## 7. One next human decision

**Authorize (or reject) an updated frozen PR 15D Quervant adapter lockfile** — or
pin a different baseline — and confirm the two-line `use super::d0_probe;`
compile-path addition. Until that decision, no measurement can be produced and
D0 remains `15ID0_BLOCKED`. This report does not authorize PR 15I-D1, any
optimization, or a merge.
