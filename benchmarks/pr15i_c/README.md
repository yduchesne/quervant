# PR 15I-C benchmark and verification tooling

Status: **negative-result tooling, retained after a safe rollback.**
The candidate these tools measured was rejected on the frozen non-primary
performance gate (`15IC_PERFORMANCE_REJECTED_SAFE_ROLLBACK`); see
`docs/pr-artifacts/pr-15i-c/performance-decision.md`.

## Contents

| Path | Purpose |
|---|---|
| `protocol.json` | Frozen acceptance metadata: `pr15i-c-physical-v1`, the nine lanes, three primary lanes, sample counts, schedule and thresholds. Written before any candidate measurement. |
| `run.py` | Source-locked paired controller (arms A/B, 12 rebuilds, 16 slots, 9 lanes, score-bit parity). |
| `verify.py` | Independent verifier. Re-derives every gate from raw evidence without importing the controller's derivation. |
| `test_run.py` | Controller fail-closed and derivation tests. |
| `test_verify.py` | Adversarial verifier fixtures (`C-V01..C-V28` subset) built in temporary directories. |
| `stage_probe/` | Benchmark-only stage probe (needs the opt-in `pr15ic-probe` core feature). |
| `score_probe/` | Benchmark-only score-bit parity probe (public API only, no feature). |

## Running

```sh
python3 benchmarks/pr15i_c/run.py \
  --checkout-root "$PWD" \
  --baseline-sha f70cde62e709383d82693ad548a8c69c7f772bef \
  --candidate-sha <candidate> \
  --out "$PWD/target/pr15i-c/campaigns/paired-01" \
  --idle-confirmed

python3 benchmarks/pr15i_c/verify.py \
  --checkout-root "$PWD" \
  --campaign "$PWD/target/pr15i-c/campaigns/paired-01" \
  --verify-only

python3 -m unittest discover -s benchmarks/pr15i_c -p 'test_*.py' -v
```

The runner requires `--idle-confirmed`, refuses any existing output path, checks
frozen-file hashes, real Git ancestry and the exact source allowlist, and blocks if
before/after slot contention is not clear. Outputs are only written under the
gitignored `target/pr15i-c/`.

## Post-rollback note

The rollback removed the `pr15ic-probe` feature and the `C-EXACT-ONE` operator, so
`stage_probe/` no longer builds against the current core. It is retained as
negative-result evidence pinned to the rejected candidate
(`395e05c629c5929f0164764c51c5a1b60b8acd1c`). `score_probe/` still builds and can
be used for any future score-bit parity work.
