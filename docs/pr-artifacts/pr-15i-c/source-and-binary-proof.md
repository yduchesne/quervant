# PR 15I-C — Source, binary and format proof

## 1. Identities

| Item | Value |
|---|---|
| Baseline A (`BASE_CONTENT_SHA`, assumed-merged PR 15I-B) | `f70cde62e709383d82693ad548a8c69c7f772bef` |
| Effective checkout at start (`dev/pr15i-c-postings`) | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` (tree identical to A) |
| Candidate implementation / measured source `C_MEASURED_SHA` | `395e05c629c5929f0164764c51c5a1b60b8acd1c` |
| Campaign | `target/pr15i-c/campaigns/paired-01` |
| Protocol SHA-256 (`benchmarks/pr15i_c/protocol.json`) | recorded in `raw/manifest.json` and re-verified independently |
| Frozen corpus manifest SHA-256 (`pr15d-corpus-v1`) | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |

## 2. Source-scope proof

`git diff --name-only A..B` for the measured candidate was:

```
crates/quervant-core/Cargo.toml
crates/quervant-core/src/search/diagnostics.rs
crates/quervant-core/src/search/execute.rs
crates/quervant-core/src/search/mod.rs
crates/quervant-core/src/search/unified.rs
crates/quervant-core/tests/pr15i_c_physical.rs
benchmarks/pr15i_c/**            (protocol, controller, verifier, tests, probes)
docs/pr-artifacts/pr-15i-c/**    (preflight, invariants)
```

No path under `search/segment`, `search/index`, `search/storage`, `search/contract`,
`benchmarks/pr15d`, `benchmarks/pr15i_0`, `benchmarks/pr15i_a`,
`benchmarks/pr15i_b` or `docs/pr-artifacts/pr-15i-0` changed. `Cargo.lock` is
byte-identical between A and B (asserted by both the controller and the verifier).

`crates/quervant-core/src/search/mod.rs` was changed only to register the
feature-gated probe re-export:
`#[cfg(feature = "pr15ic-probe")] #[doc(hidden)] pub use diagnostics::probe;`.
This registration is required for the plan's external probe binary; the deliberate
deviation from "keep the accessor private to `search`" is recorded in
`decision-log.md` (`C-D39` resolution).

## 3. Same-format proof

12 fresh builds (2 arms × {10K, 100K} × 3 attempts) were remeasured by the
verifier from disk:

* identical `stored_payload_version = 2`, `codec_id = 1` (LZ4);
* identical required feature list including `[13, 1]` (`0x000D` v1);
* identical committed bytes, sidecar bytes, STORED bytes and segment SHA-256
  digest per arm and per N;
* A 100K committed bytes `15,747,551` and STORED bytes `1,661,455` — the
  historical 15I-B sentinel reproduced exactly.

## 4. Binary proof

The verifier re-hashes the real executables (not digest strings) and requires them
to match both `raw/manifest.json` and `raw/toolchain.json`:

* `setup/build/A/build/release/pr15d-quervant-adapter`
* `setup/build/B/build/release/pr15d-quervant-adapter`
* `setup/build/{A,B}/score_probe/release/pr15i-c-score-probe`

Adapter binaries are built with `cargo build --release --offline` (without
`--locked`, because the frozen PR15D adapter lockfile predates the current core
dependency graph and `--locked` refuses it at the pinned baseline — the accepted
PR15I-B controller does the same). The standalone probe projects use their own
pinned lockfiles with `--locked --offline`. Recorded with each build.

## 5. Score-bit parity

`benchmarks/pr15i_c/score_probe` re-runs all nine lanes against the A and B indexes
outside the timing window and serialises every hit's `f64::to_bits()` as 16
lowercase hex digits. Raw `score_parity.json` contains both arms; the verifier
re-derives key order, `total_hits` and exact bit equality from the frozen corpus
oracle rather than trusting a controller flag. Result: identical keys, identical
order, identical bits on all nine lanes.
