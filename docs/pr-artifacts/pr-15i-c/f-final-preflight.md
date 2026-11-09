# PR 15I-C-F — preflight

Status: **PREFLIGHT COMPLETE** · execution contract:
`PR15I_C_F_FINAL_GENERIC_BOUNDARY_DETAILED_PLAN.md` · diagnostic only.

## 1. Repository state at preflight

| Check | Observed |
| --- | --- |
| Repository | `/home/yduchesne/Dev/Github/yduchesne/quervant` |
| Branch | `dev/pr15i-c-postings` |
| HEAD | `8b8e1f63dcf213781476f0b41bf95740cb7984a5` (dispatch-isolation QA) |
| `origin/main` | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` (`BASE_A`) |
| Working tree | clean (`git status --porcelain` empty) |
| `CAUSAL_PARENT` | `658a2dde0e15c17e2b0c92278b5c922f5260fe60` present |
| `RELEASE_PARENT` | `b32523b9bb182190cb8260b00c3a81645314837f` present |
| Frozen protocol | `benchmarks/pr15i_c/protocol.json` SHA-256 `5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e` (unchanged) |
| File system for output | `ext4` |
| CPU affinity | adapter CPU 0 / controller CPU 1 pinnable (`taskset`) |
| Toolchain | `rustc 1.98.1 (48a229cea 2026-09-01)` / `cargo 1.98.1 (797e8a9bc 2026-08-05)`; MSRV `1.85.0` available |
| Tools | `nm`, `objdump`, `taskset` present; `docker` absent, `podman` present |
| Real RustFS | **BLOCKED** (`REAL_RUSTFS_BLOCKED`) — no verified `rustfs/rustfs@sha256:1803faef…` runtime; no fake store substituted |
| `perf` | **UNAVAILABLE** on this WSL kernel → no hardware-counter claims |

## 2. Baseline validation

| Command | Result |
| --- | --- |
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 check --locked -p quervant-core` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15i_c -p 'test_*.py'` | PASS — 382 tests |

Protected paths (`crates/quervant-core/src`, `Cargo.toml`, `Cargo.lock`,
`.github/workflows/ci.yml`, `benchmarks/pr15d`, `pr15i_a`, `pr15i_b`) are
identical between `BASE_A` and preflight HEAD (`PROTECTED_IDENTICAL`).

## 3. Arm plan

| Arm | Source | Feature | Runtime mode | Role |
| --- | --- | --- | --- | --- |
| A | `6f6463cb…` | none | none | merged baseline |
| C | `658a2dde…` | `pr15ic-causal` | `disabled` | historical negative control |
| G | `F_DIAG` | `pr15ic-causal` | `disabled` | generic boundary only, physical operator out of line |
| P | `F_DIAG` | `pr15ic-causal` | `enabled` | same binary, physical operator active |

G and P share one binary and differ only by the child-process value of
`QUERVANT_PR15IC_CAUSAL_MODE`; A carries no diagnostic gate.

## 4. Source gate before sampling

`F_DIAG` = `5f74bb691420673bde1181603d0a19a8a4114ec8` (see
`f-final-source-and-codegen.md`). The diagnostic binary was built from that
commit with `--features quervant-core/pr15ic-causal`; both
`collect_mixed` and `collect_exact_term_physical` have standalone, non-empty
symbols, so the G/P environment value is the only variable between those arms.

## 5. Deviations

None. No protocol, threshold, lane, schedule, corpus or tool was altered for
this experiment. The diagnostic does not relax the frozen PR 15I-C acceptance.
