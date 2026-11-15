# PR 15I-D3-B — retained-key prefilter paired benchmark controller (frozen tooling)

**Status: measurement tooling only.** This directory contains the controller,
the independent verifier, the frozen protocol and the synthetic adversarial
tests for the single authorized D3-B candidate. It contains no production code.

## Candidate under test

A request-local, monotonic, two-probe **1,024-bit** bitset that proves when a
retained `DocumentKey` is definitely absent from the K100 heap in
`UnifiedSearcher::collect_mixed`. It is activated **only** for
`TopK.limit == 100`, never infers corruption from a probabilistic positive, and
falls back permanently to the literal exact scan after 256 admissions. The only
changed production file is
`crates/quervant-core/src/search/unified.rs`.

The historical D1-C1 retained-key fingerprint index and the D1-F DOC_KEYS
borrowing candidate remain rejected; this controller forbids their symbols and
requires the D3-B source proof (constants, `request.top_k.limit == 100`,
unchanged duplicate error text) before any timing.

## Frozen identities

| Item | Value |
|---|---|
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` (merge of PR #97, `MAIN_PR97_BASE`) |
| Protocol | `protocol_v1.json` (`pr15i-d3b-retained-key-prefilter-v1`) |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Adapter lock SHA-256 | `19953cab64e564d7830bea152042cf3bceea840fb52eac6cf382191ae585a121` |
| 100K committed index bytes | 15,747,551 |
| 100K STORED-section bytes | 1,661,455 |

The adapter, corpus, oracle and harness are imported read-only from the frozen
PR15D modules after their SHA-256 values are verified in both measured
worktrees. The controller and the verifier are independent processes: the
verifier never imports `run.py`, duplicates every frozen literal and recomputes
every median, block mean, drift ratio, A/A ratio, gate and summary.

## Campaigns and schedules

- `d3b-base-aa-01` — mandatory same-source A/A control. Both arms are separate
  release builds of BASE in isolated build namespaces with identical binary
  digests. `d3b-base-aa-02` is permitted only as the one complete retry after a
  purely numerical A/A stability failure of `aa-01`.
- `d3b-base-01`, `d3b-base-02` — two independent paired campaigns, BASE vs one
  immutable candidate commit. Each requires a sealed, qualified control.

Each campaign is 4 blocks x 4 slots = 16 slots in the frozen orders
`ABBA / BAAB / BAAB / ABBA`; every slot evaluates all nine warm lanes, one fresh
pinned adapter process per `(arm, lane, slot)`, 5 warmups + 20 timed integer
`engine_ns` samples per lane, and two clear contention probes. Paired campaigns
build four indexes; the A/A control builds two.

## Frozen D3B gates

Per block, the arm value is the floor of the two slot medians (each slot median
is the lower median of 20 samples). `d = A - B` (positive means candidate
faster); the four-block value is the lower median (rank 2 of 4). `r = B / A`.

| Gate | Requirement |
|---|---|
| `D3B-P00` | Complete 16 slots / 9 lanes / 2,880 samples / 720 warmups / 32 clear probes; source proof, identical indexes, exact oracle, drift, seal, tooling inventory and independent verification |
| `D3B-P01` | 100K common/K100: lower-median `d >= +2,000,000 ns` **and** at least 3/4 blocks `d >= 0` |
| `D3B-P02` | 100K medium/K100: lower-median `d >= +1,000,000 ns` **and** at least 3/4 blocks `d >= 0` |
| `D3B-P03` | 100K common/K10: lower-median `d >= -500,000 ns`; every block `d >= -1,500,000 ns`; lower-median `B/A <= 1.05` |
| `D3B-P04` | 10K/100K absent and rare: each lower-median `B/A <= 1.15`, **every** block `B/A <= 1.50` |
| `D3B-P05` | 10K common/K100 and 10K medium/K100: each median `d > -2,000,000 ns`; every block `d >= -3,000,000 ns` |
| `D3B-P06` | 100K medium/K100 and 100K common/K100: each median `d > -500,000 ns`; every block `d >= -1,500,000 ns` |
| `D3B-P07` | Structural: distinct A/B source and binary hashes, complete positive samples, exact oracle, byte-identical indexes and sentinels, complete archive |
| `D3B-P08` | Both paired campaigns pass P00–P07 **independently**; a qualified rejection of campaign 01 stops the series |

The A/A control uses per-block `B/A` ratios inside `[0.80, 1.25]` and a
four-block lower-median ratio inside `[0.85, 1.15]` for every lane. Exactly the
two 10K absent and 10K rare lanes may tolerate one soft outlier each, which must
still be inside `[0.67, 1.50]`; no other lane and no median receives an
exception. Inter-block and within-block drift caps are 1.25x for 100K
medium/common and 1.50x elsewhere, for both arms and all lanes.

## CLI

All outputs are absolute, non-symlinked and strictly beneath
`<repo>/target/pr15i-d3-b/`; existing paths are never overwritten. Campaign
names are exactly `d3b-base-aa-01`, `d3b-base-aa-02`, `d3b-base-01`,
`d3b-base-02`.

```sh
BASE=39dbd9f571a58bea8cc03d5a406533298e809bfe
CANDIDATE=<exact immutable candidate commit>

python3 benchmarks/pr15i_d3_b/run.py preflight \
  --base-tree "$PWD/target/pr15i-d3-b/sources/base" --base-sha "$BASE" \
  --candidate-tree "$PWD/target/pr15i-d3-b/sources/candidate" --candidate-sha "$CANDIDATE" \
  --out "$PWD/target/pr15i-d3-b/preflight-01.json"

python3 benchmarks/pr15i_d3_b/run.py paired \
  --base-tree "$PWD/target/pr15i-d3-b/sources/base" --base-sha "$BASE" \
  --candidate-tree "$PWD/target/pr15i-d3-b/sources/control-base" --candidate-sha "$BASE" \
  --campaign d3b-base-aa-01 --out "$PWD/target/pr15i-d3-b/d3b-base-aa-01" --idle-confirmed

python3 benchmarks/pr15i_d3_b/run.py paired \
  --base-tree "$PWD/target/pr15i-d3-b/sources/base" --base-sha "$BASE" \
  --candidate-tree "$PWD/target/pr15i-d3-b/sources/candidate" --candidate-sha "$CANDIDATE" \
  --campaign d3b-base-01 --out "$PWD/target/pr15i-d3-b/d3b-base-01" --idle-confirmed

# Only if campaign 01 qualified AND all performance gates passed:
python3 benchmarks/pr15i_d3_b/run.py paired \
  --base-tree "$PWD/target/pr15i-d3-b/sources/base" --base-sha "$BASE" \
  --candidate-tree "$PWD/target/pr15i-d3-b/sources/candidate" --candidate-sha "$CANDIDATE" \
  --campaign d3b-base-02 --out "$PWD/target/pr15i-d3-b/d3b-base-02" --idle-confirmed

python3 benchmarks/pr15i_d3_b/verify.py --campaign-dir "$PWD/target/pr15i-d3-b/d3b-base-01"
python3 benchmarks/pr15i_d3_b/verify.py --series-root "$PWD/target/pr15i-d3-b" --comparison d3b-base

python3 benchmarks/pr15i_d3_b/run.py publish \
  --campaign-dir "$PWD/target/pr15i-d3-b/d3b-base-01" \
  --evidence-root "$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b"
```

Exit codes: `0` success/verified, `2` rejected input, `3` blocked or
verification failure. A performance-rejected campaign still verifies and
publishes.

### Option validation

| Option | Validation |
|---|---|
| `--out` | absolute, non-symlink, strictly beneath `<repo>/target/pr15i-d3-b/`, must not exist; preflight requires a `.json` file |
| `--campaign-dir` | absolute, non-symlink, strictly beneath the same root, must exist |
| `--campaign` | exact frozen name; selects control vs paired |
| `--base-tree`, `--candidate-tree` | absolute real Git worktree roots, detached HEAD, clean tracked tree |
| `--base-sha`, `--candidate-sha` | full 40-hex; arm A must equal BASE; control requires both arms BASE; paired requires a distinct descendant |
| `--idle-confirmed` | mandatory for every timed campaign |

## Tooling freeze

`tooling_manifest.json` records the SHA-256 of every file in this directory
except itself. Both the controller and the independent verifier require an
exact file-set match (no symlinks, no unlisted code, no missing members) before
any official run and during every verification. After the first timed attempt no
tooling change is authorized; a discovered defect is a hard stop.

Synthetic adversarial fixtures are the only inputs to the negative tests in
`test_run.py` and `test_verify.py`; they are never evidence for a real campaign.
