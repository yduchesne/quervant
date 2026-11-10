# PR 15I-C dispatch-isolation study (A/C/D/E)

Diagnostic only. Asks one bounded question: is the reproducible ~1.18–1.95x
generic-query regression in the PR 15I-C candidate associated with (a) the
compiled runtime gate, (b) the candidate's compiled code/layout even when the
operator is unreachable, or (c) a minimal dispatch scaffold with no operator?

| Arm | Source | Build feature | Process variable | Measured path |
|---|---|---|---|---|
| A | merged PR 15I-B `6f6463cb…` | none | none | original generic |
| C | causal candidate `658a2dd…` | `pr15ic-causal` | `QUERVANT_PR15IC_CAUSAL_MODE=disabled` | generic via candidate gate |
| D | `9c710e5…` = C + `if false && shape_eligible` | `pr15ic-causal` | `QUERVANT_PR15IC_CAUSAL_MODE=disabled` (ignored) | generic after constant-fold |
| E | `d97889d…` = A + predicate/gate/trampoline | `pr15ic-dispatch-isolation` | `QUERVANT_PR15IC_DISPATCH_MODE=disabled` | generic via trampoline |

Protocol `dispatch_protocol_v1.json` (`pr15i-c-dispatch-isolation-v1`): four
6-slot... eight-slot blocks `ACDEEDCA / EDCAACDE / DCAEACED / CEADDAEC`
(32 slots, two of each arm per block), 5 warmups, 20 single-request `engine_ns`
samples (unbatched) or 10 `batch_ns` observations (batched; 100 repeats on the
four absent/rare lanes, 1 on the five medium/common lanes), 24 index rebuilds
per campaign, campaigns `unbatched-01, batched-01, unbatched-02, batched-02`.

```sh
python3 benchmarks/pr15i_c/dispatch_run.py --checkout-root "$PWD" \
  --baseline-sha 6f6463cb26bcf28340cc9d4afd4dfeb040281898 \
  --c-sha 658a2dde0e15c17e2b0c92278b5c922f5260fe60 \
  --d-sha 9c710e5432aa17cdcd717ce40ad6f9a8167914f1 \
  --e-sha d97889d2debc14f1e4ea3c821089cd453ba1daab \
  --regime unbatched --out "$PWD/target/pr15i-c/dispatch-isolation-v1/unbatched-01" \
  --idle-confirmed

python3 benchmarks/pr15i_c/verify_dispatch.py --checkout-root "$PWD" \
  --campaign "$PWD/target/pr15i-c/dispatch-isolation-v1/unbatched-01"

python3 benchmarks/pr15i_c/verify_dispatch.py --checkout-root "$PWD" --aggregate \
  --series-root "$PWD/target/pr15i-c/dispatch-isolation-v1"
```

Classification (§8 of the plan) uses only the two unbatched campaigns and the
predeclared per-lane medians: C/A must reproduce as `REGRESSED` on all four
low-match lanes, then the D/E classes select one of
`RUNTIME_ASSOCIATED`, `COMPILED_CANDIDATE_ASSOCIATED`, `SCAFFOLD_ASSOCIATED`,
`BROAD_ASSOCIATION`, or `MIXED`/`NOT_REPRODUCED`/`BLOCKED`/`INCONCLUSIVE`.
Batched data is observational corroboration only. The frozen nine-lane
acceptance protocol is untouched and this study can never qualify PR 15I-C.
