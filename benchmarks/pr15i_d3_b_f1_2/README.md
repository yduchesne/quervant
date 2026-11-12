# PR 15I-D3-B-F1.2 — stable-host readiness and bounded drift-only requalification

**Status: prospective measurement tooling only.** This directory is an isolated
copy of the F1.1 tooling adding exactly two capabilities required by the F1.2
plan, with all production, historical tooling and evidence untouched.

## What changed relative to F1.1

1. **Non-query host-readiness gate.** After both adapters and indexes are built
   and immediately before the first timed slot, the controller sleeps one fixed
   5,000 ms settle interval and then reads `/proc/stat` seven times at 1,000 ms
   intervals for the existing adapter/controller CPU pair. It derives six
   integer busy/steal intervals per CPU and records a sealed
   `raw/host-readiness.json`. Every interval must be `busy <= 250‰` and
   `steal <= 20‰`; the lower median of six busy values must be `<= 100‰`. No
   engine query is executed. A non-READY result stops before timing, leaves the
   exclusive status record, and cannot trigger a replacement attempt.
2. **Bounded drift-only succession.** Completed paired attempts are classified
   as `QUALIFIED_PASSED`, `QUALIFIED_REJECTED`, `DRIFT_ONLY_INVALID` or invalid.
   At most three paired attempts may run; exactly one complete
   `DRIFT_ONLY_INVALID` may be replaced; two independent `QUALIFIED_PASSED`
   campaigns are required for local acceptance. Any `QUALIFIED_REJECTED`
   (including P03 alone) is terminal and requires the additive production
   rollback. Each paired campaign seals `raw/attempt-succession.json` with its
   predecessor identities, and the full-series verifier reopens all predecessor
   bytes.

Everything else is inherited unchanged: canonical same-path release builds,
identical A/A binaries, exact PR15D corpus/oracle/index sentinels, 16 slots ×
9 lanes × 20 samples × 5 warmups × 2 probes, ABBA/BAAB/BAAB/ABBA, P01–P08 and
drift thresholds.

## Protocol delta

The F1.2 protocol differs from F1.1 in exactly nine top-level entries: `schema`,
`study_type`, the `comparisons` key rename (`d3bf12-base`), `tooling_directory`,
`target_subroot`, `evidence_root_relative`, `campaign_suffixes`
(`["01","02","03"]`), plus the new `host_readiness` and
`paired_structural_replacement` objects. Every other entry is recursively equal.

## Frozen identities

| Item | Value |
|---|---|
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` |
| Candidate | `48d9abf3eeefbccb480d89eac95f6e6911e078d5` |
| Protocol schema | `pr15i-d3b-f1-2-canonical-build-v1` |
| Comparison | `d3bf12-base` |
| Target root | `target/pr15i-d3-b/fixup-f1-2/` |
| Evidence root | `$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b-f1-2/` |
| Corpus / adapter lock | `69052c66…` / `19953cab…` |
| 100K index / STORED | 15,747,551 / 1,661,455 bytes |

## Official names

`d3bf12-base-aa-01`, conditional numerical retry `d3bf12-base-aa-02`, and paired
`d3bf12-base-01`, `-02`, `-03` in chronological order only.

## Commands

```sh
ROOT=$(git rev-parse --show-toplevel); F12="$ROOT/target/pr15i-d3-b/fixup-f1-2"
TOOL=benchmarks/pr15i_d3_b_f1_2

python3 "$TOOL/replay.py" --out "$F12/rehearsal/round-01/replay-report.json"

python3 "$TOOL/run.py" preflight \
  --base-tree "$F12/sources/base" --base-sha 39dbd9f5… \
  --candidate-tree "$F12/sources/candidate" --candidate-sha 48d9abf… \
  --out "$F12/preflight-01.json"

python3 "$TOOL/run.py" paired \
  --base-tree "$F12/sources/base" --base-sha 39dbd9f5… \
  --candidate-tree "$F12/sources/control-base" --candidate-sha 39dbd9f5… \
  --campaign d3bf12-base-aa-01 --out "$F12/d3bf12-base-aa-01" --idle-confirmed

python3 "$TOOL/verify.py" --campaign-dir "$F12/d3bf12-base-aa-01"
python3 "$TOOL/run.py" publish --campaign-dir "$F12/d3bf12-base-aa-01" \
  --evidence-root "$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b-f1-2"
```

Paired commands are identical with `d3bf12-base-01`/`-02`/`-03`; the controller
itself refuses a suffix the succession state machine does not authorize.
`verify.py --series-root "$F12" --comparison d3bf12-base` performs the full
P08 decision. Exit codes: 0 success/verified, 2 rejected input, 3 blocked.

## Tooling freeze

`tooling_manifest.json` records the SHA-256 of every regular file in this
directory except itself. Controller and verifier require an exact file-set match
before every official run. The F1.2 tooling becomes immutable at T3, after the
full synthetic rehearsal passes; no file may change after the first official
timed slot.
