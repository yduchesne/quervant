# PR 15I-D0 lockfix-01 preflight

**Continuation:** compatibility fixup for the historical `15ID0_BLOCKED` result.
**Measured baseline:** `COMPAT_BASE` (lock-only descendant of `PARENT_MAIN`).

## 1. Source identity chain

| Identity | Full SHA | Notes |
|---|---|---|
| `HISTORICAL_BASE` | `7237bce325834d6cc1c73735697be29bc60ef16b` | immutable historical measurement baseline |
| `PARENT_MAIN` | `4606f92e32f7d7e2419ad9a52888910747c1a44b` | `origin/main`; PR #92 docs closeout |
| `COMPAT_BASE` | `a53ee021acbe5f30db2b3298a11fcd99e72c2945` | PARENT_MAIN + lock-only compatibility commit |
| `COMPAT_BASE` tree | `880fda56b73fb1b040c3e9e6b17510408394367b` | |
| Historical D0 HEAD | `67467a176d4a905b9ad0a833cd52bd27683f0690` | preserved blocked artifact |
| Historical tooling commit | `10e30b332224270a7316c0a8b2bb7dea033c6c42` | preserved |

`HISTORICAL_BASE` is an ancestor of `PARENT_MAIN`, and the complete
`HISTORICAL_BASE..PARENT_MAIN` diff is exactly the four PR #92 docs paths:
`docs/BENCHMARKING.md`, `docs/ROADMAP.md`,
`docs/pr-artifacts/pr-15i-0/architecture-15i-c.md`,
`docs/pr-artifacts/pr-15i-c/closeout.md`. Protected paths (`crates/`,
`benchmarks/`, `Cargo.toml`, `Cargo.lock`, `.github/`, `AGENTS.md`) are
identical. Rule `FX-01` applied.

## 2. Compatibility commit

Message: `bench(pr15d): reconcile Quervant standalone lock with stored-lz4 default`.
Parent: `4606f92e…`. The commit changes one file only:

```text
benchmarks/pr15d/adapters/quervant/Cargo.lock
```

Old lock SHA-256 `050f9d751f978277e02057a0002d1b87d6f0166d73dcadab93f4e78e26cb817d`;
new lock SHA-256 `19953cab64e564d7830bea152042cf3bceea840fb52eac6cf382191ae585a121`.
Repository `Cargo.lock` remains `293ff40c6cdfbc8408bedf9cb34131edc210d92ab2b051e601578de77c72baad`.
See `compatibility-lock-diff.md`.

## 3. Tooling continuation

New branch `dev/pr15i-d0-lockfix-01`, created at `COMPAT_BASE`. It replays the
existing D0-owned files without importing any PR 15I-C production source. The
historical D0 branch `dev/pr15i-d0-attribution-02` and all historical reports
remain untouched.

Pre-measurement tooling commits:

| Commit | Purpose |
|---|---|
| `2bd3aa7` | rebind materializer/controller/verifier/tests to `COMPAT_BASE`, new protocol identity |
| `3c7ebea` | real A/Q/P vertical-slice gate + bounded affinity poll |
| `fe538be` | campaign source inventory records the new recorder as `ABSENT` in BASE |
| `526a154` | Q/P slots map to the shared QP index tree |

Tooling identity is frozen before sampling; measurements use exactly these
commits. The final documentation commit follows the measurements and changes no
tooling code.

## 4. Two authorized scratch imports

The plan authorizes exactly two scratch-only `use super::d0_probe;` imports, one
in `crates/quervant-core/src/search/unified.rs` and one in
`crates/quervant-core/src/search/execute.rs`. The independent source proof
rebuilds BASE + the approved insertions + the deterministic `rustfmt` pass and
compares bytes; deletion of the inserted bytes restores `COMPAT_BASE` identity.
No other source byte, manifest, feature default or public API changed.

## 5. Host and toolchain

| Item | Observed |
|---|---|
| OS | Ubuntu 24.04.5 LTS on WSL2 |
| Filesystem | native `ext4` |
| CPU | Intel Core i7-10750H, 12 logical CPUs |
| Affinity | controller on the second allowed CPU, adapters on the first; verified through `/proc/<pid>/status` |
| Rust | stable 1.98.1; MSRV 1.85.0 |
| Python | 3.12.3 |
| JDK | OpenJDK 21.0.12.1 |
| rustfmt | 1.9.0-stable |
| corpus | PR 15D generator; manifest `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |

The host was idle for the measurement windows. No toolchain was swapped, no
dependency was upgraded outside the single authorized lock correction and no
production source changed.

## 6. Historical evidence freeze

Historical failed-run records were hashed before the fixup and left unchanged:

- `target/pr15i-d0/build-01.log` — `3bf8d72f…`
- `target/pr15i-d0/preflight-01.json` — `94dbc4f6…`
- `target/pr15i-d0/source-proof-01.json` — `86382a3b…`
- `target/pr15i-d0/d0-tests-final.log` — `8d638c85…`
- `target/pr15i-d0/qa.log` — `7ca4540b…`
- canonical incomplete run logs and `validation.json` — see
  `target/pr15i-d0/lockfix-01/historical-freeze.json`

No historical seal, report or raw observation was overwritten.
