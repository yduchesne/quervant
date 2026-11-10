# PR 15I-C dispatch-isolation — preflight

Status: `PREFLIGHT_COMPLETE` (2026-11-09)

## Repository and source identities

| Item | Value |
|---|---|
| Branch | `dev/pr15i-c-postings` |
| Branch start (`START`) | `c9216304dc3317735397961a8974396d32e82dfd` |
| `origin/main` = `BASE_A` | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| Causal candidate (`C`) | `658a2dde0e15c17e2b0c92278b5c922f5260fe60` |
| Historical outside-dispatch candidate | `92a741876f6f6823d9d1792fc391dbb1bbecceb0` |
| Restored historical candidate | `b32523b9bb182190cb8260b00c3a81645314837f` |
| Historical G control | `50b56e9fe7b22bb266ca7b0d9e209500dfc785ff` |

All objects resolve as commits; `git diff --name-only BASE_A HEAD -- crates Cargo.lock
.github/workflows/ci.yml benchmarks/pr15d benchmarks/pr15i_a benchmarks/pr15i_b`
is empty; `benchmarks/pr15i_c/protocol.json` is
`5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e`.

## Environment

| Item | Value |
|---|---|
| `rustc -Vv` | `rustc 1.98.1 (48a229cea 2026-09-01)`, commit `48a229ceaefd4985c50990b14116b6d856af0985` |
| `cargo -V` / `git` | `cargo 1.98.1` / `git 2.43.0` |
| MSRV toolchain | `cargo 1.85.0` installed |
| Host | `Linux MSI 6.18.33.2-microsoft-standard-WSL2 x86_64` |
| Filesystem of the worktree | `ext4` |
| Allowed CPUs | `0..11`; `taskset` pinning to CPU 0 and CPU 1 verified |
| Tools | `nm`, `objdump` present; `perf` unavailable (`PERF_UNAVAILABLE`) |
| Container runtimes | `docker` absent, `podman` present (no verified pinned-image access) |

## Baseline QA (pre-modification)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 check --locked -p quervant-core` | PASS |
| `cargo test -p quervant-core --lib search::execute::budget_tests` | 40 passed |
| `python3 -m unittest discover -s benchmarks/pr15i_c` | 309 passed |
| `git diff --check` | clean |

## Prior evidence preserved read-only

`target/pr15i-c/campaigns/paired-01`, `outside-dispatch-batched-01`,
`generic-boundary-01..04`, `noise-diagnostics*`, `batched-noise-v1`,
`causal-campaigns-v1` and all their receipts are untouched. The causal study's
`CAUSAL_INCONCLUSIVE` verdict is not reclassified; this study measures a
different question with different arms.
