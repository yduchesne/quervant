# PR 15I-A — paired compact-mutation-state qualification

**Status: controller only until a sealed campaign is executed and verified.**
This directory does not claim a production performance result by itself.

The controller qualifies exactly one candidate: mutation-state payload version 3
(a sorted per-sidecar segment-ID dictionary plus canonical varint ordinals and
physical document IDs). It compares the post-PR 15I-0 baseline (`A`) with the
single candidate commit (`B`) on the frozen PR15D 10K/100K corpus and the
unchanged PR15D independent oracle.

## Layout

```text
benchmarks/pr15i_a/
  protocol.json      frozen lanes, schedule, block order and gate thresholds
  run.py             paired build/size/reopen/commit/RSS/RustFS controller
  verify.py          read-only seal + gate recomputation
  test_run.py        deterministic controller/gate unit tests (no benchmark data)
  test_verify.py     adversarial verifier/rollback tests
  reopen_probe/      fresh-process `FsDirectory -> Index -> snapshot` probe
  remote_probe/      real-RustFS 100K prepare + cold-bootstrap probe
```

Both probes use public `quervant-core` APIs only. They are standalone Cargo
projects (never workspace members) with their own `Cargo.lock`; during a
campaign the controller copies each probe beside the arm it measures and links
that arm's `quervant-core`, without editing any source.

## Controller

```sh
ROOT="$(pwd -P)"
BASE="$(git rev-parse origin/main)"       # post-PR15I-0 main
CAND="$(git rev-parse HEAD)"
OUT="$ROOT/target/pr15i-a/campaigns/paired-01"
python3 benchmarks/pr15i_a/run.py \
  --checkout-root "$ROOT" --baseline-sha "$BASE" \
  --candidate-sha "$CAND" --out "$OUT" --idle-confirmed
python3 benchmarks/pr15i_a/verify.py --checkout-root "$ROOT" \
  --campaign "$OUT" --verify-only
```

`run.py` creates clean detached worktrees for A and B under
`target/pr15i-a/worktrees/`, builds all binaries outside every timed region, and
refuses a dirty worktree, an unlisted changed path, a missing native filesystem,
a non-idle attestation, a candidate equal to the baseline, or a fresh A 100K
committed size that does not reproduce the PR 15I0 sentinels (`30,965,025` total
bytes / `9,600,180` sidecar bytes).

Measured work, all on the frozen corpus:

- **Size:** three independent builds per arm at 10K and 100K; identical
  sidecar/segment/manifest/CURRENT/total bytes and payload layout required;
  independent PR15D oracle query per build.
- **Warm search:** the frozen nine lanes, five warmups and 20 samples per lane,
  16 balanced slots in the frozen `ABBA | BAAB | BAAB | ABBA` order.
- **Reopen:** 100K, four balanced blocks, two fresh processes per arm per block;
  `open_ns` from the probe, kernel peak RSS from `wait4` (`ru_maxrss`).
- **Build+commit:** 100K, four balanced blocks, two independently built indexes
  per arm per block; `index_ns` and `commit_ns` reported separately, plus kernel
  peak RSS of the same process.
- **RustFS:** pinned-image 100K prepare per arm, then four balanced blocks with
  two cold bootstraps per arm per block into a fresh disposable workspace.

Replay-heavy, 129-live-segment, tombstone-mix and zero-live controls are covered
by `crates/quervant-core/tests/pr15i_a_v3.rs` (correctness, not alternate
primary performance targets).

## Gates (B/A, smaller is better)

`A-P01` 100K sidecar `<= 0.75`; `A-P02` 100K total committed index `<= 0.95`;
`A-P03` 10K sidecar and total `<= 1.02`; `A-P04` reopen median `<= 1.10` and
every block `<= 1.25`; `A-P05` build+commit median `<= 1.15`, every block
`<= 1.30`; `A-P06`/`A-P07` every 100K/10K lane median `<= 1.10`/`<= 1.15` with
every block `<= 1.30`/`<= 1.35`; `A-P08` reopen and build+commit peak-RSS median
`<= 1.15`, every block `<= 1.30` and absolute increase `<= 16 MiB` per mode;
`A-P09` RustFS cold bootstrap median `<= 1.15`, every block `<= 1.35`.

Any failure yields a rejection decision (`A_SIZE_REJECTED_SAFE_ROLLBACK` /
`A_PERF_REJECTED_SAFE_ROLLBACK`); an oracle or payload/feature mismatch yields
`A_CORRECTNESS_BLOCKED`. Passing campaign gates yields
`A_CANDIDATE_ACCEPTED_PENDING_QA`; the full workspace QA remains a separate
gate and `HOSTED_CI_PENDING` is never reported as green.

## Evidence and the authoritative verifier

Raw campaign files are sealed (SHA-256 inventory) under
`target/pr15i-a/campaigns/<id>/raw/`.

`verify.py --verify-only` is the **authoritative** verifier. Every original
size-rebuild directory (`setup/sizes/{A,B}/n{10000,100000}-run{1,2,3}`) is
mandatory: all twelve must exist as real, non-symlinked directories and all
three measurements per arm/size must agree with the sealed record. The raw tree
is inspected as a full directory+file inventory, so unexpected or symlinked
directories under `raw/` are rejected. It independently
validates the exact 20-file seal inventory and the 32 unsealed auxiliary
contention probes (bound byte-for-byte to their sealed slot copies), the frozen
A/B source/ancestry/scope, the frozen protocol Git blob, the original corpus and
its PR15D oracle, the six original build binaries, the four-block/two-sample
topology for reopen/build+commit/RustFS, each arm's payload version/required
features and exact byte accounting, every one of the 9 lanes × 16 slots
(warmups, samples, summary, independent oracle result, contention), and only then
re-derives the gates with the unchanged `run.derive`. It is read-only and
rejects any evidence mutation.

`run.py --verify-only` is **deprecated** and exits nonzero with
`A_USE_INDEPENDENT_VERIFIER`; it never prints `VERIFIED`.

Only an accepted, independently verified campaign is published to
`benchmarks/reports/pr15i-a/`.

## Verification limits (do not overclaim)

A seal proves internal byte consistency with a supplied digest. It does **not**
authenticate who measured the data, reproduce the original host, or prove the
host was idle. The original schema recorded an idle authorization flag, a
filesystem and an environment fingerprint; those are checked for internal
consistency and are labelled `HISTORICAL_ATTESTATION_NOT_INDEPENDENTLY_REPRODUCED`.
The raw individual query replies were not retained; the sealed slots contain the
runner's oracle-validated aggregates, which the verifier re-derives against the
unmodified PR15D corpus oracle. Local QA, hosted CI and human review are
separate statuses, never inferred from a `VERIFIED` receipt.

## Tests

```sh
python3 -m unittest discover -s benchmarks/pr15i_a -p 'test_*.py'
```

The unit tests use synthetic measurements only; they never claim a production
benchmark result.
