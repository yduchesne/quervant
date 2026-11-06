# PR 15H-A targeted benchmark controller

Quervant-only measurement controller for PR 15H-A (linear single-term candidate
staging). It times **only** the seven frozen warm PR15D lanes that the accepted
plan permits, and reuses the frozen PR15D / PR15E-B1 adapter, corpus, oracle and
statistics without modification.

## Frozen lanes (fixed order)

| Role | Lane |
|---|---|
| P1 | `pr15d_v1/100000/medium/k100` |
| P2 | `pr15d_v1/100000/common/k100` |
| P3 | `pr15d_v1/100000/common/k10` |
| G1 | `pr15d_v1/10000/common/k100` |
| G2 | `pr15d_v1/10000/rare/k100` |
| G3 | `pr15d_v1/100000/rare/k100` |
| G4 | `pr15d_v1/100000/absent/k100` |

No lane may be added, dropped or reordered after a measurement is seen. A
three-engine benchmark is never run here, and no process-cold lane is timed.

## Subcommands

### `baseline` (must precede production Rust edits)

```sh
python3 benchmarks/pr15h_a/run.py baseline \
  --checkout-root /ABS/CHECKOUT \
  --base-tree /ABS/CLEAN/PINNED/MAIN/WORKTREE \
  --out /ABS/CHECKOUT/target/pr15h-a/baseline-01 \
  --idle-confirmed
```

Builds the frozen Quervant adapter once, generates the 10K/100K corpus once,
builds the two index directories once, then executes **three** trials (5 warmups
+ 20 timed samples per lane, one real before/after contention probe per trial).
The campaign is sealed under `raw/seal.json` and the sanitized report pair is
written to `sanitized/baseline.json` / `sanitized/baseline.md`.

### `paired` (after a candidate correctness pass)

```sh
python3 benchmarks/pr15h_a/run.py paired \
  --checkout-root /ABS/CHECKOUT \
  --base-tree /ABS/CLEAN/PINNED/MAIN/WORKTREE \
  --candidate-tree /ABS/CLEAN/PINNED/CANDIDATE/WORKTREE \
  --baseline /ABS/CHECKOUT/target/pr15h-a/baseline-01 \
  --out /ABS/CHECKOUT/target/pr15h-a/paired-01 \
  --idle-confirmed
```

- validates the sealed pre-optimization baseline and the candidate ancestry;
- builds both adapters in separate directories and requires byte-identical
  query-only indexes;
- executes four mirrored blocks, `A,B` / `B,A` / `B,A` / `A,B`, i.e. eight timed
  slots, 56 lane records, 1,120 timed samples, 280 warmups, 16 contention probes
  and 56 independent oracle validations;
- classifies each lane by the sign of all four `B/A` slot-median ratios;
- writes either `sanitized/performance.{json,md}` or
  `sanitized/blocked.{json,md}` — never both.

## Decision rule (frozen)

- `B_FASTER` iff all four `B/A` ratios are `< 1.0`.
- `A_FASTER` iff all four `B/A` ratios are `> 1.0`.
- otherwise `INCONCLUSIVE` (a single equal ratio is inconclusive).
- `HA-P01`/`HA-P02` require `B_FASTER` for 100K common K100/K10.
- `HA-P03` requires 100K medium K100 not `A_FASTER`.
- `HA-P04` requires every guard not `A_FASTER`.
- Drift cap: `max/min` must not exceed 1.25 (100K) or 1.50 (10K), both
  cross-session (baseline historical median-of-3 vs paired A median-of-4) and
  within-arm across the four A or B slot medians. The cap is inclusive: exactly
  1.25/1.50 passes; anything above blocks the whole verdict.
- Any qualification failure yields `MEASUREMENT_BLOCKED`, never a performance
  verdict.

## Verify-only

`--verify-only` on either subcommand re-hashes every sealed file, recomputes the
sanitized report from the sealed raw data and compares the result
byte-for-byte. It writes nothing.

## Safety properties

- `--out` must be an absolute, non-symlinked, non-existing directory strictly
  beneath `<checkout-root>/target/pr15h-a/`.
- Source worktrees must be clean, detached and pinned; the tooling checkout must
  have no unstaged tracked change.
- A campaign is never resumed, repaired or overwritten.
- Host fingerprints, corpus manifests and index digests must match across arms.
- No credentials, absolute paths, hostnames or raw samples appear in the
  sanitized reports.
