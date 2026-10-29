# PR 15C-A acceptance evidence

Tested working-tree state: branch `dev/pr15c-a-immutable-segment`, HEAD
`0655bcb` (implementation `9fe9470`, unit witnesses `d54e220`, evidence
`46b48d1`, final witness `0655bcb`) on top of base `main`
`42b19445dd79a90d8701b4306e305c6e4e44cd57`, plus this document-only update.
Tree clean except for the evidence documents in this directory.

Host/toolchain: Linux (WSL2) x86_64, `rustc 1.98.1` / `cargo 1.98.1` (stable),
`cargo +1.85.0` = 1.85.0 (workspace MSRV), `cargo-llvm-cov 0.9.1`,
`clippy 0.1.98`.

## Gate results

| # | Command | Exit | Result |
|---|---|---|---|
| 1 | `cargo fmt --all -- --check` | 0 | PASS |
| 2 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| 3 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| 4 | `cargo +1.85.0 check -p quervant-core` | 0 | PASS |
| 5 | `cargo test --workspace --all-features` | 0 | PASS — 114 test targets, **2145 tests passed, 0 failed**, 1 ignored |
| 6 | `cargo +1.85.0 test --workspace --all-features` | 0 | PASS — same target set, 0 failed |
| 7 | `cargo test -p quervant-core --lib` | 0 | PASS — **812 passed**, 0 failed, 1 ignored (pre-existing ignore) |
| 8 | `cargo test -p quervant-core --test pr15b_diagnostics` | 0 | PASS — 16 passed (frozen PR 15B oracle unchanged) |
| 9 | `cargo test -p quervant-core --test pr15c_a_segment_state` | 0 | PASS — 5 passed (new production-path witness) |
| 10 | `cargo test -p quervant-core --release --lib` | 0 | PASS — 812 passed |
| 11 | `cargo doc --workspace --no-deps` | 0 | PASS — no warnings |
| 12 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | PASS — **91.66% line**, 92.14% region, 87.80% function (floor 85) |
| 13 | `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1` | 1 | **BLOCKED — ENVIRONMENT** (see below) |

The coverage command is the repository's actual CI command (`.github/workflows/ci.yml`,
`cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85`);
no exclusions were added and no crate was omitted. Per-file inspection of the
changed code: `index/snapshot.rs` 97.12% lines, `segment/metadata.rs` 98.60%,
`segment/reader.rs` 85.90%, `segment/norms.rs` 90.96%, `segment/dictionary.rs`
80.86% (unchanged decode error paths carry the residue), `segment/schema.rs`
88.05%, `segment/spatial.rs` 91.17%, `segment/remap.rs` 92.64%,
`segment/json_paths.rs` 89.09%.

## Baseline evidence (pre-change, same host)

| Command | Result |
|---|---|
| `cargo test -p quervant-core --lib` @ `42b1944` | PASS — 771 passed, 1 ignored |
| `cargo test -p quervant-core --test pr15b_diagnostics` @ `42b1944` | PASS — 16 passed |
| `cargo fmt --all -- --check` @ `42b1944` | PASS |

Delta in the core library suite: 771 → 812 tests (+41: 32 cache/unit witnesses,
2 new norms witnesses, 7 budget/meter tests; see `implementation.md`).

## New deterministic witnesses

`crates/quervant-core/src/index/snapshot.rs` → `mod verified_state_cache`
(32 tests):

- `g1_01_verified_state_and_snapshot_are_send_sync`
- `g1_02_query_local_caches_are_per_reader`
- `g1_03_standalone_and_directory_open_unchanged`
- `g1_04_legacy_segment_features_unchanged` (builder-only segment + frozen
  `golden.seg` legacy fixture without BM25 norms)
- `g1_05_zero_cap_and_cached_readers_are_equivalent` (schema/remap/sections/
  features/bounds/keys/stored/liveness/norms/dictionary+postings/spatial/columns)
- `g2_01_zero_metadata_cap_uses_uncached_reader`
- `g2_02_exact_allowance_admits_and_one_byte_over_falls_back`
- `g2_04_repeated_failed_candidates_do_not_leak`
- `g2_05_single_state_is_charged_once_under_a_large_cap`
- `g2_06_to_09_nested_classes_are_accounted`
- `g2_10_reservation_releases_on_last_arc_after_snapshot_drop`
- `g2_11_cache_hits_keep_full_admission_charge`
- `g2_12_over_limit_input_reports_authoritative_error`
- `g3_01_repeated_reads_reuse_same_verified_state`
- `g3_02_envelope_corruption_fails_closed`
- `g3_03_section_digest_corruption_fails_closed`
- `g3_04_malformed_metadata_fails_closed`
- `g3_04b_malformed_json_paths_fail_closed`
- `g3_05_descriptor_verification_unchanged`
- `g3_06_same_ids_different_bytes_are_never_trusted`
- `g3_07_effective_masks_remain_snapshot_owned`
- `g4_01_racing_first_opens_verify_once` (2, 8 and 32 threads with a `Barrier`)
- `g4_04_failed_validation_wakes_waiters`
- `g4_05_artificial_build_failure_recovers`
- `g4_06_poisoned_slot_fails_closed`
- `g4_07_panic_during_build_restores_slot`
- `g4_08_guard_outlives_snapshot`
- `g4_09_no_lock_held_across_query`
- `g4_10_out_of_range_index_is_typed`
- `g4_11_cache_hit_still_obeys_admission_budget`

`crates/quervant-core/src/segment/metadata.rs` (8 budget tests) and
`crates/quervant-core/src/segment/norms.rs` (2 representation tests).

`crates/quervant-core/tests/pr15c_a_segment_state.rs` (5 production-path tests):

- `pr15c_a_t01_repeated_queries_reuse_state_and_match_oracle`
- `pr15c_a_t02_pinned_snapshot_matches_oracle`
- `pr15c_a_t03_old_snapshot_isolated_from_new_commit`
- `pr15c_a_t04_real_filesystem_restart_matches_oracle`
- `pr15c_a_t05_key_accessors_are_identical`

Every integration expectation comes from the frozen PR 15A/15B record table
(`tests/pr15a_common`) or from an independently constructed
`SegmentReader::open` over the same snapshot bytes; no expectation is read back
from the new cache.

## Deterministic proof of removed redundant verification

`g3_01_repeated_reads_reuse_same_verified_state` and `g4_01_racing_first_opens_verify_once`
assert, through a `#[cfg(test)]` per-snapshot counter, that any number of
subsequent `open_segment_reader` calls (sequentially or from 2/8/32 racing
threads) produce **exactly one** successful verification per snapshot slot, and
that all readers share the identical `Arc<VerifiedSegmentState>` pointer. The
cache-hit path never clones the segment byte buffer (`Arc::clone` only), while
each hit still charges the full encoded length against the active-reader budget
(`g2_11`, `g4_11`). SHA-256 work per query therefore drops from "every open" to
"first open per snapshot and segment".

## Injected failures exercised

| Injection | Witness | Asserted outcome |
|---|---|---|
| Envelope (whole-container) corruption | `g3_02` | `DigestMismatch`, no `Ready`, no retained charge, repeat also fails |
| Section digest corruption (envelope re-sealed) | `g3_03` | `DigestMismatch`, no publication |
| Malformed BM25 norms payload (digests re-sealed) | `g3_04` | `Corrupt`, no publication |
| Malformed JSON-path version (digests re-sealed) | `g3_04b` | `Corrupt`, no publication |
| Wrong content descriptor | `g3_05` | `LengthMismatch`/`DigestMismatch` from `verify_content_descriptor` |
| Same ids, different/corrupt bytes | `g3_06` | Independent verification; corrupt variant fails closed |
| Metadata cap below the candidate allowance | `g2_02`, `g2_04` | Verified uncached fallback, budget at 0, no leak over repeats |
| Input over `accepted_segment_bytes` | `g2_12` | Authoritative `LimitExceeded` after the cache declines |
| Forced build error | `g4_05` | Typed error, slot reset, retry verifies once |
| Forced panic during build | `g4_07` | Unwind, slot reset, budgets released, retry verifies once |
| Poisoned slot mutex | `g4_06` | `CorruptCommittedState`, no publication, no leak |
| Admission exhaustion with a warm cache | `g4_11` | Original `ResourceLimit`, no bypass |

## Real-service status

**Real RustFS: BLOCKED — ENVIRONMENT.** The authoritative harness
(`tests/rustfs/README.md`, `.github/workflows/ci.yml` job `rustfs`, pinned image
`rustfs/rustfs@sha256:1803faef…`) requires a live container runtime and
`QUERVANT_RUSTFS_*` credentials. This host has no Docker daemon
(`docker info` unavailable) and no `QUERVANT_RUSTFS_*` variables, so the CI
commands

```
cargo test -p quervant-objectstore --features s3 --test pr13_s3_rustfs -- --ignored --test-threads=1
cargo test -p quervant-objectstore --features s3 --test pr13_proxy_rustfs -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr13_oracle -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr13_oracle_geo -- --ignored --test-threads=1
```

cannot be executed here. Executing the first core command reproduces the blocker:

```
thread 'real::rustfs_write_cold_open_query_and_restart' panicked:
QUERVANT_RUSTFS_ENDPOINT must be set for real RustFS acceptance: NotPresent
```

No fake `ObjectStore` result is presented as RustFS conformance. All independent
local gates (including the real native-filesystem restart test
`pr15c_a_t04_real_filesystem_restart_matches_oracle`) passed. Per X31/X49 the PR
is **not** marked accepted: the RustFS gate remains open for CI or a reviewer
with the real service.

## Failure classifications

No gate failed, so no F1–F5 classification was required for this change. The
single pre-existing document defect (F3, `docs/TESTING.md` conflict markers,
reproduced at base `42b1944`) is recorded in `preflight.md` and left untouched.

## Unresolved gates

1. Real RustFS conformance (BLOCKED — ENVIRONMENT, above).
2. Reviewer acceptance of the process deviation recorded in `decisions.md` note 1
   (S2–S4 landed as one verified commit).
3. PR 15C-B qualified performance campaign (explicitly out of scope; no
   before/after win is claimed here).

## C15A-01 fixup acceptance (supersedes the counts above for the current head)

Fix commit: `aca8ed17ea8fef6a65aa5ceabc978ceb305148b2` on
`dev/pr15c-a-immutable-segment`. Reviewed base `748d85f`. Full evidence:
[`fixup-c15a01.md`](./fixup-c15a01.md).

| # | Command | Exit | Result |
|---|---|---|---|
| 1 | `cargo fmt --all -- --check` | 0 | PASS |
| 2 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| 3 | `cargo +1.85.0 check -p quervant-core` | 0 | PASS |
| 4 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| 5 | `cargo test -p quervant-core --lib` | 0 | PASS — **819 passed**, 1 ignored |
| 6 | `cargo test -p quervant-core --test pr15c_a_segment_state` | 0 | PASS — 5 passed |
| 7 | `cargo test -p quervant-core --test pr15b_diagnostics` | 0 | PASS — 16 passed (frozen oracles unchanged) |
| 8 | `cargo test --workspace --all-features` | 0 | PASS — 114 targets, **2152 tests**, 0 failed |
| 9 | `cargo +1.85.0 test --workspace --all-features` | 0 | PASS — 2152 tests, 0 failed |
| 10 | `cargo test -p quervant-core --release --lib` | 0 | PASS — 819 passed |
| 11 | `cargo doc --workspace --no-deps` | 0 | PASS — no warnings |
| 12 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | PASS — **91.69% lines** (92.18% regions, 87.85% functions) |
| 13 | `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored` | 1 | **BLOCKED — ENVIRONMENT** (no RustFS endpoint, no Docker daemon) |

New witnesses (+7 unit tests, core lib 812 → 819): `c15a01_t01`,
`c15a01_t02`, `c15a01_t03`, `c15a01_t04`, `c15a01_t05`, `c15a01_t06`,
`c15a01_t09`. Against the pre-fix condition `t01`, `t03` and `t04` fail; with the
fix all seven pass. The active-reader admission, corruption, snapshot-isolation
and overflow cases are inherited unchanged from the named existing tests
(see `fixup-c15a01.md` §5).

Residual status: real RustFS conformance and exact-head CI checks remain open;
PR acceptance, roadmap status and PR 15C-B performance qualification are
unchanged and not claimed here.

## C15A-02 / C15A-03 fixup acceptance (supersedes the counts above for the current head)

Fix commit `6cdbf93fc464c9ea8961e456aefebd7d124004d8`; reviewed base `5695709`.
Full evidence and the allocation audit: [`fixup-c15a02-c15a03.md`](./fixup-c15a02-c15a03.md).

| # | Command | Exit | Result |
|---|---|---|---|
| 1 | `cargo fmt --all -- --check` | 0 | PASS |
| 2 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| 3 | `cargo +1.85.0 check -p quervant-core` | 0 | PASS |
| 4 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| 5 | `cargo test -p quervant-core --lib` | 0 | PASS — **830 passed**, 1 ignored |
| 6 | `cargo test -p quervant-core --test pr15c_a_segment_state` | 0 | PASS — 5 passed |
| 7 | `cargo test -p quervant-core --test pr15b_diagnostics` | 0 | PASS — 16 passed |
| 8 | `cargo test --workspace --all-features` | 0 | PASS — 114 targets, **2163 tests**, 0 failed |
| 9 | `cargo +1.85.0 test --workspace --all-features` | 0 | PASS — 2163 tests, 0 failed |
| 10 | `cargo test -p quervant-core --release --lib` | 0 | PASS — 830 passed |
| 11 | `cargo doc --workspace --no-deps` | 0 | PASS — no warnings |
| 12 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | PASS — **91.73% lines** |
| 13 | `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored` | 1 | **BLOCKED — ENVIRONMENT** (no RustFS endpoint/credentials, no Docker daemon) |

New witnesses (+11 unit tests, core lib 819 → 830): `c15a02_t01`…`c15a02_t05`,
`c15a03_t06`, `c15a03_t07`, `c15a03_t07b`, `c15a03_t08`,
`c15a03_t08b`, `c15a03_public_identity_contract_unchanged`.
Pre-fix counterexamples observed: JSON offset capacity 16 vs 12 emitted offsets
(and 8 vs 5) under the amortized `push`; the infallible identity constructor
panics on capacity overflow while the fallible one returns `LimitExceeded`.

**Audit result:** C15A-02 and C15A-03 PASS. Six additional findings (F1–F6) of
infallible-but-precharged retained allocations were recorded for an independent
fixup; per X31 they block PR acceptance but not these two fixes.

Not claimed: real RustFS conformance, exact-head CI, PR acceptance, roadmap
status, PR 15C-B performance.

## F1–F6 fallible-allocation fixup acceptance (supersedes the counts above for the current head)

Fix commit `b3c72b9727becbde06ee10ea1850f08defa7b821`; reviewed base `0c2a121`.
Evidence and the F4 feasibility record: [`fixup-f1-f6.md`](./fixup-f1-f6.md).

| # | Command | Exit | Result |
|---|---|---|---|
| 1 | `cargo fmt --all -- --check` | 0 | PASS |
| 2 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| 3 | `cargo +1.85.0 check -p quervant-core` | 0 | PASS |
| 4 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| 5 | `cargo test -p quervant-core --lib` | 0 | PASS — **839 passed**, 1 ignored |
| 6 | `cargo test -p quervant-core --test pr15c_a_segment_state` | 0 | PASS — 5 passed |
| 7 | `cargo test -p quervant-core --test pr15b_diagnostics` | 0 | PASS — 16 passed |
| 8 | `cargo test --workspace --all-features` | 0 | PASS — 114 targets, **2172 tests**, 0 failed |
| 9 | `cargo +1.85.0 test --workspace --all-features` | 0 | PASS — 2172 tests, 0 failed |
| 10 | `cargo test -p quervant-core --release --lib` | 0 | PASS — 839 passed |
| 11 | `cargo doc --workspace --no-deps` | 0 | PASS — no warnings |
| 12 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | PASS — **91.81% lines** |
| 13 | `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored` | 1 | **BLOCKED — ENVIRONMENT** |

New witnesses (+9 unit tests, core lib 830 → 839): `f1_t01`, `f1_t02`, `f2_t03`,
`f3_t04`, `f5_t07`, `f5_t07b`, dictionary term witness, `f6_t05`, `f6_t06`.

**Status: F1/F2/F3/F5/F6 IMPLEMENTED + VERIFIED LOCAL. F4 HARD STOP (X20 —
`Arc::try_new` unstable on MSRV 1.85.0 and stable).** PR 15C-A is **NOT ACCEPTED**:
an F4 architecture decision plus real RustFS/exact-head CI evidence are still
required. No performance claim (PR 15C-B owns measurement).
