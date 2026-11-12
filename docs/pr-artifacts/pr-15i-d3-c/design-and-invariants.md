# PR 15I-D3-C — design and invariants (implemented subset)

## Implemented

- `crates/quervant-core/Cargo.toml`: one empty non-default feature
  `pr15i-d3c-experiment = []`. No dependency, workspace or lockfile change.
- `crates/quervant-core/src/search/unified.rs`: private `#[cfg(feature =
  "pr15i-d3c-experiment")] mod d3c` with:
  - `Kind::{Linear, Prefilter, ExactSet}` and `Profile::{P0,P1,P2}`
    (1024/4096/8192 bits, caps 256/1024/2048) in one fixed `[u64; 128]` state;
  - process-scoped `OnceLock` mode selection from
    `QUERVANT_PR15I_D3C_STRATEGY` / `QUERVANT_PR15I_D3C_PREFILTER_PROFILE`,
    one `PR15I_D3C_MODE=v1:…` stderr marker, `Linear` when unset, explicit
    failure for invalid/inconsistent values;
  - exact-backed duplicate check at all three original sites, including
    losing candidates; prefilter negative probes skip only the exact scan;
    positives always run the literal exact scan and only real equality is
    corruption; exact set uses `HashSet<DocumentKey>`;
  - admission bookkeeping only after the unchanged `heap_admit_candidate`
    succeeds: monotonic bits/cap for prefilter, clone/insert and
    evicted-key removal for exact set, nothing for linear;
  - exact-set `K ∈ 1..=1024` and `try_reserve(K+1)`; K outside that range or
    reservation failure is a typed `ResourceLimit` (experimental
    unavailability), never a silent fallback.
- `#[cfg(not(feature))]` retains the literal original scans and
  `heap_admit_candidate` call sites, so the default build is unchanged.
- 24 experimental unit tests (`d3c_tests`) covering linear, prefilter
  negatives/positives/collisions/eviction/caps P0/P1/P2, exact-set
  insert/loser/replacement/eviction/duplicates, independent request state,
  exact-set K bounds, long keys, K10/K100 activation, and K+1 heap behavior.

## Not implemented (required by the plan, not executed)

The full D3-C study is **incomplete**:

- No U21–U25/U27/U30/U33–U38/U40–U42 tests (error-precedence fault seams,
  concurrency, historical P0 fixture, mode-marker/process tests, 32-bit probe
  fixture, cursor parity).
- No real `FsDirectory` integration test file `pr15i_d3_c.rs` (I01–I12).
- No microbenchmark seam/grid M01–M16, no recorded micro data, no profile
  selection, no `profile-selection.md`.
- No `benchmarks/pr15i_d3_c/` controller, verifier, policy, replay, protocol,
  tooling manifest or T4 freeze.
- No 72-lane/4-arm A/A control, no four-arm campaigns, no policy output,
  no archives.
- No final coverage/RustFS/CI/review closeout for D3-C.

## Invariant status

DC-I01/default behavior: verified by default build + tests.
DC-I04/I05/I06/I07/I08 (core strategy semantics): covered by the implemented
tests; the fault-injection subset (I08) is partial.
DC-I09 (error precedence): only indirectly covered.
DC-I11 (process mode/marker): implemented, not yet tested.
DC-I12–DC-I23: not executed.

## Decision

Per C-60 (a substantive condition outside the matrix — the study's remaining
new harness and 1–2 hours of timed acquisition cannot be completed and
validated in this execution session), dependent measurement/tooling work is
HARD STOPPED. The additive, non-default experimental source is preserved; it
is **not** a T4-frozen D3-C source identity and must not be used to claim a
D3-C result.
