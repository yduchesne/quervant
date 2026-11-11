# PR 15I-D1-F — BASE-vs-C2 paired benchmark controller (frozen tooling)

**Status: F0 tooling only.** This directory contains measurement, verification
and publication tooling for the **independent C2** document-key optimization.
It contains no production code and no C1 fingerprint-index logic.

C2 is built directly on the verified D0-compatible BASE
`a53ee021acbe5f30db2b3298a11fcd99e72c2945`. It borrows already validated
DOC_KEYS bytes for losing sorted candidates and owns a `DocumentKey` only on
top-K admission. It does **not** reuse the rejected C1 retained-key
fingerprint experiment (`2360172…`), which remains historically rejected.

## Frozen identities

| Item | Value |
|---|---|
| BASE | `a53ee021acbe5f30db2b3298a11fcd99e72c2945` |
| Historical rejected C1 (forbidden in C2 source) | `236017289567885689b46d3d04e71d6653296124` |
| Protocol | `protocol_v1.json` (`pr15i-d1-f-c2-v1`) |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Adapter lock SHA-256 | `19953cab64e564d7830bea152042cf3bceea840fb52eac6cf382191ae585a121` |
| 100K committed index bytes | 15,747,551 |
| 100K STORED-section bytes | 1,661,455 |

The adapter, corpus, oracle, harness and statistics are imported read-only from
the frozen PR15D modules after their SHA-256 values are verified in both
measured worktrees. The lifecycle is a structural copy of the frozen D1 T0
controller (exclusive outputs, sealing, pinned affinity, contention probes,
drift qualification, independent verifier) with only the authorized F-plan
adaptations: namespace `pr15i-d1-f`, campaign names, the single `c2-base`
comparison, the frozen FC2 gates, and the A/A control mode.

## Campaigns and schedules

- `c2-base-aa-01` — same-source A/A control. Both arms are rebuilt from BASE
  (`--base-sha == --candidate-sha == BASE`); two independent release builds and
  two shared read-only indexes. Qualified only by the frozen A/A rules.
- `c2-base-01`, `c2-base-02` — two independent paired campaigns, BASE vs an
  immutable C2 commit. Each requires the sealed, qualified control.

Each campaign is 4 blocks × 4 slots = 16 slots in the frozen orders
`ABBA / BAAB / BAAB / ABBA`; every slot evaluates all nine warm lanes, one fresh
pinned adapter process per `(arm, lane, slot)`, 5 warmups + 20 timed integer
`engine_ns` samples per lane, and two clear contention probes. Paired campaigns
build four indexes; the A/A control builds two.

The controller pins itself to the second allowed CPU and every adapter to the
first via `taskset`, verifying the settled `/proc/<pid>/status` affinity. Native
filesystems only (`ext4`, `xfs`, `btrfs`).

## Frozen FC2 gates

Per block, the arm value is the floor of the two slot medians (each slot median
is the nearest-rank median of 20 samples). `d = A - B` (positive means C2
faster); the four-block value is the lower median (rank 2 of 4). `r = B / A`.

| Gate | Requirement |
|---|---|
| `FC2-P00` | Complete 16 slots / 9 lanes / 2,880 samples / 720 warmups / 32 clear probes; source, index, oracle, drift, seal and independent verification pass |
| `FC2-P01` | At least one of 100K common/K100 or 100K common/K10: lower median `d >= +2,000,000 ns` and at least 3/4 blocks `d >= 0` |
| `FC2-P02` | Both 100K common lanes: lower median `d > -2,000,000 ns`; no block `d < -3,000,000 ns` |
| `FC2-P03` | 100K medium/K100 and 10K common/K100: median `d > -2,000,000 ns`; no block `d < -3,000,000 ns` |
| `FC2-P04` | 10K/100K absent and rare: lower-median `r <= 1.15`; no block `r > 1.50` |
| `FC2-P05` | 10K medium/K100: median `d > -2,000,000 ns`; no block `d < -3,000,000 ns` |
| `FC2-P06` | Structural: distinct A/B source and binary hashes, positive samples, exact oracle, byte-identical indexes and 100K sentinel, complete archive |
| `FC2-P07` | Both paired campaigns pass FC2-P00–P06 independently; no pooling |

The A/A control uses per-block `B/A` ratios inside `[0.80, 1.25]` and a
lower-median ratio inside `[0.85, 1.15]`; a failure is `MEASUREMENT_BLOCKED`,
never a performance verdict. Inter-block and within-block drift caps are
unchanged from D1 (1.25× for 100K medium/common, 1.50× elsewhere).

## CLI

All outputs are absolute, non-symlinked and strictly beneath
`<repo>/target/pr15i-d1-f/`; existing paths are never overwritten. Campaign
names are exactly `c2-base-aa-01`, `c2-base-01`, `c2-base-02`.

```sh
# identity only, no timing; writes a single JSON file
python3 benchmarks/pr15i_d1_f/run.py preflight \
  --base-tree <abs BASE worktree> --base-sha <BASE> \
  --candidate-tree <abs C2 worktree> --candidate-sha <C2> \
  --out <repo>/target/pr15i-d1-f/preflight-01.json

# same-source A/A control (both arms BASE; candidate tree is a second BASE worktree)
python3 benchmarks/pr15i_d1_f/run.py paired \
  --base-tree <abs BASE worktree> --base-sha <BASE> \
  --candidate-tree <abs BASE control worktree> --candidate-sha <BASE> \
  --campaign c2-base-aa-01 \
  --out <repo>/target/pr15i-d1-f/c2-base-aa-01 --idle-confirmed

# one sealed paired campaign (run -01, then -02 only after -01 qualifies)
python3 benchmarks/pr15i_d1_f/run.py paired \
  --base-tree <abs BASE worktree> --base-sha <BASE> \
  --candidate-tree <abs C2 worktree> --candidate-sha <C2> \
  --campaign c2-base-01 \
  --out <repo>/target/pr15i-d1-f/c2-base-01 --idle-confirmed

python3 benchmarks/pr15i_d1_f/verify.py --campaign-dir <campaign dir>
# add --series-root/--comparison c2-base for the two-campaign FC2-P07 verdict

python3 benchmarks/pr15i_d1_f/run.py publish \
  --campaign-dir <campaign dir> \
  --evidence-root "$HOME/.local/share/quervant/benchmark-evidence/pr15i-d1-f"
```

Exit codes: `0` success/verified, `2` rejected input, `3` blocked or
verification failure. A performance-rejected campaign still verifies and
publishes.

### Option validation

| Option | Validation |
|---|---|
| `--out` | absolute, non-symlink, strictly beneath `<repo>/target/pr15i-d1-f/`, must not exist; preflight requires a `.json` file |
| `--campaign-dir` | absolute, non-symlink, strictly beneath the same root, must exist |
| `--campaign` | exact frozen name; selects control vs paired |
| `--base-tree`, `--candidate-tree` | absolute real Git worktree roots, detached HEAD, clean tracked tree |
| `--base-sha`, `--candidate-sha` | full 40-hex; arm A must equal BASE; control requires both arms BASE; paired requires a distinct C2 descendant |
| C2 source policy | changed paths limited to `unified.rs`, `reader.rs`, `tests/pr15i_d1_f_keys.rs`, D1-F tooling/docs and the two status docs; `Cargo.*`, `execute.rs`, `score.rs`, `snapshot.rs`, `column.rs`, `.github/` and every rejected C1 symbol are refused |
| `--evidence-root` | absolute, non-symlink; archives use `O_EXCL` and are never replaced |

## Evidence

A sealed campaign contains `authorization.json`, `manifest.json` (source,
compiler, adapter binary, index layout/digest, corpus, host, tooling and
controller hashes), `raw/setup/`, `raw/slots/slot-01..16.json`,
`raw/contention/`, `raw/seal.json`, and `sanitized/summary.{json,md}`.
`verification.json` is written only by `publish` after an independent
`verify.py` run.

The verifier re-hashes every sealed member, rejects unlisted members and path
traversal, regenerates the deterministic corpus and oracle, re-derives index
digests and byte sentinels, rechecks source fingerprints and the changed-path
allowlist through Git, rejects rejected-C1 symbols, recomputes every
median/mean/drift/ratio/gate independently, and requires its canonical summary
to equal the controller's byte-for-byte. It never imports `run.py`.

`publish` archives sanitized/sealed evidence plus relative inventory, excluding
`build/`, `indexes/` and `corpus/`, safely extracts into a fresh scratch
directory, re-hashes every member and verifies the archive round trip before
writing an immutable `.sha256` sidecar. A second publish refuses to overwrite.

## Tests

```sh
python3 -m py_compile benchmarks/pr15i_d1_f/run.py benchmarks/pr15i_d1_f/verify.py benchmarks/pr15i_d1_f/test_run.py
python3 -m unittest discover -s benchmarks/pr15i_d1_f -p 'test_*.py' -v
```

`test_run.py` covers the mandatory B01–B17 matrix with synthetic fixtures in
`tempfile` directories: historical-C1-shaped archive/seal integrity, C1-symbol
and path-allowlist rejection, index sentinel checks, schedules, missing/duplicate
lanes, invalid samples, oracle tampering, non-clear contention, exact A/A and
FC2 boundaries, one-pass-one-reject aggregation, seal tamper/traversal,
exclusive output refusal, archive round trip and zero-effect/slower candidates.

## Dependencies and limits

Real RustFS, hosted CI and independent review remain separate gates
(`RUSTFS_PENDING`, `CI_PENDING`, `REVIEW_PENDING`). Archives under `$HOME` may
share the same physical/virtual disk as the repository and are not an off-host
backup.
