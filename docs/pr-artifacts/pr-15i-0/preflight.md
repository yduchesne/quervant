# PR 15I-0 — preflight and source-baseline reconciliation

**Phase:** P0 (repository safety, accepted post-15H-E reconciliation, frozen sources).
**Document class:** measurement/audit preflight. No production code is changed by PR 15I-0.

## 1. Accepted base

| Item | Value |
|---|---|
| Working branch | `dev/pr15i-0-qualified-baseline` |
| Accepted base (`BASE`) | `19cc5207009abdc1496473443d850487f7739e92` |
| `BASE` subject | `Merge pull request #87 from yduchesne/dev/pr15h-a-linear-term-candidates` |
| `main` / `origin/main` | both resolve to `BASE` (no fetch divergence observed) |
| Tracked tree at `BASE` | clean (`git status --porcelain=v1` empty) |
| Working tree at preflight start | clean |

`main`, `origin/main` and the accepted `BASE` are the same commit object, so the
local tracking ref is a trustworthy freshness proof for this campaign
(decision `I0-X04`). No reset, rebase, force-push or destructive operation was
performed.

## 2. PR 15H-E reconciliation

The assumed closeout SHAs from the execution plan are all reachable ancestors of
`BASE` (`git merge-base --is-ancestor <sha> BASE` exits 0 for each):

| Role | Commit | Ancestor of `BASE` |
|---|---|---|
| 15H-E documentation closeout | `8d7a17fed1721bd381641ca17cce70c7925b56ca` | yes |
| 15H-E tooling / A baseline | `eb6ed9170308965987a35211d227431535a41ecb` | yes |
| 15H-E dictionary-v2 candidate (reverted) | `72b18e249f2a83b77fd2faaf05deb6f0d60eaad6` | yes (history only) |
| 15H-E production rollback | `8d722ad0c0cff6b947fcdc762bb2ccaacdfcff0b` | yes |
| 15H-E final code HEAD (fixture formatted) | `6fce44b2f393e68ae73090f3843a2c201f7dd3a1` | yes |

Required 15H-E records are present in the accepted tree:

- `docs/pr-artifacts/pr-15h-e/final-report.md`
- `docs/pr-artifacts/pr-15h-e/rollback.md`
- `docs/pr-artifacts/pr-15h-e/decision.md`
- `docs/pr-artifacts/pr-15h-e/storage.md`, `latency.md`, `correctness.md`
- Sealed campaign evidence pointers recorded in `final-report.md`
  (`baseline-01` seal `6b3851b4…`, `paired-01` seal `2ed0ca61…`); the raw
  campaign directories stay under the ignored `target/` tree.

**Production equality proof.** `git diff --stat eb6ed91 BASE -- crates/quervant-core/src`
is empty, so production `src` is byte-identical to the pre-E tooling baseline.
The only later `crates/` difference between `eb6ed91` and `BASE` is
`crates/quervant-core/tests/pr15h_e_control_fixture.rs`
(+3/−5 lines, rustfmt on the retained control fixture at `6fce44b`), which is a
test file, not production source.

**Disposition carried forward:** `E_SIZE_REJECTED_SAFE_ROLLBACK`. The
dictionary-v2 candidate is **not** the production baseline and was not measured
in this PR.

## 3. Format-version facts on `BASE` (verified in source, not assumed)

| Area | Source | Observed on `BASE` |
|---|---|---|
| Dictionary payload | `crates/quervant-core/src/segment/dictionary.rs` | `dictionary_version = 1` (`writer.u16(1)`) — v2 is absent after rollback |
| STORED payload | `crates/quervant-core/src/segment/stored.rs` | `stored_version = 1` |
| Mutation-state payload | `crates/quervant-core/src/index/mutation_state.rs` | `MUTATION_STATE_VERSION = 1`, `MUTATION_STATE_VERSION_BATCH = 2` |
| Container features in use | `crates/quervant-core/src/segment/format.rs` | `0x0001`–`0x000B` (`FEATURE_MUTATION_STATE_V2 = 0x000B`); `0x000C` is unused, so the future 15I-A V3 feature ID is still free (`I0-X34` precondition currently satisfied) |
| Container section kinds | same | `0x0001`–`0x0011`, including `MutationState = 0x000F` |

## 4. Protected path object IDs at `BASE`

`git ls-tree -r BASE -- <path>`:

| Path | Mode | Blob |
|---|---|---|
| `crates/quervant-core/src/index/mutation_state.rs` | 100644 | `34f04cf89882a03f5ba82e9801d08a347dcf817d` |
| `crates/quervant-core/src/segment/dictionary.rs` | 100644 | `0e04d73b7b18c3f356b1c472790710e0d153ab81` |
| `crates/quervant-core/src/segment/format.rs` | 100644 | `a0f06363dd8ad03a74d741c340792974fb7cd146` |
| `crates/quervant-core/src/segment/stored.rs` | 100644 | `8212de2f3a9e5c3bf46bb47f96dd9b114c899225` |
| `crates/quervant-core/src/search/execute.rs` | 100644 | `5d0ac48132de6ea1220bdd884f81ca9f260ab3ba` |
| `crates/quervant-core/src/search/unified.rs` | 100644 | `b2978021f9f36ae9a5cdd9fa036448a54097c948` |

The full protected-tree equality diff is re-derived in Phase P6 and recorded in
`final-report.md` and `decision-register.md`.

## 5. Frozen benchmark inputs present and unmodified

| Tree | State on `BASE` |
|---|---|
| `benchmarks/pr15d/` (corpus, oracle, spec, adapters, harness) | present, unmodified |
| `benchmarks/pr15e/` (`profile.py`, `verify.py`) | present, unmodified |
| `benchmarks/pr15f/` (`run.py`, `verify.py`, `attribution.py`, `profile_queries.py`, `reopen_probe/`) | present, unmodified |
| `benchmarks/reports/pr15d/pr15d-qualified.json` | present, `status = QUALIFIED`, `source_sha = 40a9c26a57aa23640904075e77be956ee52718bc` |
| `benchmarks/reports/pr15e-b1/optimized-three-engine-pr15d.json` | present, `status = QUALIFIED`, `source_sha = 40ca10bae46f2d7df7804a0a129a99a4daf35ef0` |
| `benchmarks/reports/pr15f/p0-profile-summary.json` | present (historical anchor; not rewritten) |
| `tests/rustfs/` | present |

PR 15F recomputes a hardcoded SHA-256 lock over
`benchmarks/pr15d/adapters/quervant/src/main.rs`,
`benchmarks/pr15d/harness/run.py`, `benchmarks/pr15d/corpus/oracle.py`,
`benchmarks/pr15e/profile.py`, `benchmarks/pr15e/verify.py`,
`benchmarks/reports/pr15e-b1/optimized-three-engine-pr15d.json` and
`benchmarks/reports/pr15e-b1/cumulative-closeout.json`. All seven lock entries
exist and match their recorded digests on `BASE`; the PR 15F `source_lock()`
gate therefore passes without touching any frozen file.

## 6. Toolchain and environment capability probe

| Tool | Observation | Consequence |
|---|---|---|
| Rust stable | `rustc 1.98.1`, `cargo 1.98.1` | QA lane |
| Rust MSRV | `cargo +1.85.0` available (`1.85.0 (d73d2caf9 2024-12-31)`) | QA lane |
| Python | 3.12.3 (stdlib only) | controller/verifier |
| JDK | OpenJDK 21.0.12.1 with `javac` | Lucene adapter may build → three-engine campaign is *not* automatically blocked |
| `perf` wrapper `/usr/bin/perf` | exits 2 (`perf not found for kernel …-microsoft`) | wrapper unusable |
| versioned `perf` fallback | `/usr/lib/linux-tools/6.8.0-147-generic/perf` → `perf version 6.8.12`; `perf record -g --call-graph dwarf` and `perf report --stdio` both succeed, `Total Lost Samples: 0` | PR 15F `discover_perf()` resolves via its documented `versioned` fallback, so CPU sampling is **available**, not blocked |
| `heaptrack` | present at `/usr/bin/heaptrack` | optional P12 allocation capture may be attempted |
| Filesystem | `ext4` on the repository volume | satisfies PR 15D `native_filesystem` |
| Kernel | WSL2 (`*-microsoft-standard-WSL2`) | disclosed as PR 15D/15F require; `process_cold` is never OS-cache-cold |

Host identity (hostname, user, absolute home paths, PIDs, raw probe logs) is
recorded only under the ignored `target/pr15i-0/` evidence tree and is excluded
from every committed document.

## 7. Existing benchmark/controller suites executed at `BASE`

| Command | Result |
|---|---|
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — `Ran 83 tests … OK` |
| `python3 -m unittest discover -s benchmarks/pr15f -p 'test_*.py'` | PASS — `Ran 54 tests … OK` |
| `python3 -m unittest discover -s benchmarks/pr15e -p 'test_*.py'` | PASS — `Ran 90 tests … OK (skipped=1)` |

These are the frozen harness owners' own suites; they are executed unmodified as
regression evidence and are never replaced by PR 15I-0 tooling tests.

## 8. Pre-implementation gate outcome

- Source identity is proven; the post-E rollback is real and current.
- No production source, `Cargo.lock`, frozen benchmark tree, workflow or release
  configuration needs to change to execute PR 15I-0.
- The sidecar semantic contract on `BASE` matches the §8 parser design: payload
  versions 1 and 2 only, `u16` key/replay length prefixes, `u64` revision,
  `u8` status, live pointer `(u16 segment id, u64 doc id)`, replay
  `(token, 32-byte fingerprint, key, u8 intent, u64 revision)`, and a v2 batch
  block whose nested response encoding is deliberately out of scope.
- The P4 locator is implementable entirely from public APIs:
  `quervant_core::index::CurrentPointer::{parse, manifest_key, manifest_length,
  manifest_digest}`, `quervant_core::segment::Manifest::decode`,
  `Manifest::mutation_state: Option<MutationStateRef>` and
  `quervant_objectstore::ContentDigest::{sha256_v1, from_sha256_v1_bytes}`.

No §3 counterexample required stopping any part of the plan. The formal mapping
of invariants and counterexamples is in
[`invariant-traceability.md`](invariant-traceability.md).
