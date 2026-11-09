# PR 15I-C causal attribution experiment (A/B/C)

Diagnostic only. This harness answers one bounded question: **does the severe
absent/rare per-request regression live in the active specialized operator, or
does it persist when the same candidate binary is forced onto the generic path?**

It never replaces the frozen nine-lane acceptance campaign
(`protocol.json`, `run.py`, `verify.py`) and cannot qualify PR 15I-C.

## Arms

| Arm | Source | Binary | Mode variable |
|---|---|---|---|
| A | merged PR 15I-B `6f6463cb…` | A adapter, default features | unset |
| B | candidate `pr15ic-causal` feature | the **one** BC adapter | `QUERVANT_PR15IC_CAUSAL_MODE=enabled` |
| C | candidate `pr15ic-causal` feature | the **same** BC adapter bytes/path | `QUERVANT_PR15IC_CAUSAL_MODE=disabled` |

B and C differ only by the allowlisted child environment variable; each measured
lane/slot launches a fresh adapter process, so the Rust `OnceLock` mode
resolution happens once per process. Any other mode value is a typed
`CorruptIndex` error, so a misconfigured arm can never be recorded as data.

## Protocol

`causal_protocol_v1.json` (`pr15i-c-causal-v1`) freezes everything before the
first sample: nine lanes, four six-slot blocks `ABCCBA / BCAACB / CABBAC / ACBBCA`
(24 slots), 5 warmups per lane/slot, 20 individual `engine_ns` samples
(unbatched) or 10 `batch_ns` observations (batched, 100 repeated searches for the
four absent/rare lanes and 1 for the five medium/common lanes), 12 fresh index
rebuilds per campaign, and the §9 numerical decision table.

Per campaign: 4 320 individual samples (unbatched) or 2 160 batches = 97 200
searches + 1 080 warmups (batched). Four campaigns, run in the fixed order
`causal-unbatched-01, causal-batched-01, causal-unbatched-02, causal-batched-02`.

## Commands

```sh
python3 benchmarks/pr15i_c/causal_run.py \
  --checkout-root "$PWD" --baseline-sha 6f6463cb26bcf28340cc9d4afd4dfeb040281898 \
  --candidate-sha <CAUSAL_BC_SOURCE_SHA> --regime unbatched \
  --out "$PWD/target/pr15i-c/causal-campaigns-v1/causal-unbatched-01" --idle-confirmed

python3 benchmarks/pr15i_c/verify_causal.py --checkout-root "$PWD" \
  --campaign "$PWD/target/pr15i-c/causal-campaigns-v1/causal-unbatched-01"

python3 benchmarks/pr15i_c/verify_causal.py --checkout-root "$PWD" --aggregate \
  --series-root "$PWD/target/pr15i-c/causal-campaigns-v1"
```

`verify_causal.py` recomputes every slot median with the frozen PR15D
nearest-rank convention, re-derives all block ratios and the §9 classification
from sealed raw, and writes an exclusive receipt under
`target/pr15i-c/reviews/`. `--verify-only` mutates nothing.

## Files

| File | Purpose |
|---|---|
| `causal_protocol_v1.json` | frozen diagnostic protocol |
| `causal_run.py` | three-arm controller (`CausalAdapterProcess`, mode-proof and score-parity probes) |
| `verify_causal.py` | independent verifier and `--aggregate` classification |
| `causal_source_proof.py` | mechanical Git-blob source-identity checks |
| `test_causal_run.py` | protocol/schedule/units tests plus the CM-U mode truth table |
| `test_verify_causal.py` | the 40-case CV adversarial matrix |

## Interpretation limits

`B/C` measures activating the specialized path inside one candidate machine-code
layout; `C/A` measures the residual cost of the candidate's compiled code, gate
and dispatch while running the generic algorithm — **not** a proven LLVM cause.
Batched results are observational throughput only and never override the
unbatched classification.
