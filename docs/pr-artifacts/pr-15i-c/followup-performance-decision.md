# PR 15I-C follow-up — performance decision

**Decision: `15IC_NOISE_DIAGNOSTIC_BLOCKED`**

Per the deterministic disposition table: *"A/A fails systemic qualification →
freeze implementation work before source restoration; preserve all raw; report
`15IC_NOISE_DIAGNOSTIC_BLOCKED`; do not infer compiler effect or modify
thresholds."*

## 1. What this decision does and does not mean

* It **does** mean the predeclared A/A environment-stability control failed, so
  the A/G numbers cannot be interpreted as a layout effect and the outside-dispatch
  implementation was **not** restored.
* It **does not** mean the outside-dispatch architecture was measured and rejected.
  It was never implemented in this follow-up: P2 was gated on the noise study.
* It **does not** change any historical status. `paired-01` (in-generic operator)
  remains rejected under the frozen nine-lane gates; `generic-boundary-03/-04`
  remain a pass and a fail under their own old F0 rule.
* It **does not** touch production. No production file was modified in this
  session, so there is nothing to revert (`NC-D83`: no no-op revert).

## 2. Exact trigger

`target/pr15i-c/reviews/noise-v2-series-aggregate.json`:

```
decision = 15IC_NOISE_DIAGNOSTIC_BLOCKED
aa_criteria.pass = false       # 10K absent: aa-01 campaign median 0.8496 < 0.90
ag_criteria.pass = false       # because A/A must hold on the same host/toolchain
per-lane A/G aggregates         0.9604 … 0.9984, 4/4 runs <=1.05 everywhere
```

All eight campaigns were valid (clear contention at all 256 slots, 12 remeasured
rebuilds each, byte-identical A/B index layouts and segment digests, frozen
corpus, exact oracle keys/counts). The failure is not evidence damage.

## 3. Why a 15% same-binary swing blocks the study

In `aa-01` the two arms were the *same executable file* with the same SHA-256 and
byte-identical index directories, yet the 10K absent lane measured 0.85 in the
B-labelled arm (block ratios 0.771 … 1.176). At ~50–90 µs per query this lane is
dominated by scheduling/page-cache/CPU-frequency effects. A regime that can move
a same-binary lane by 15% cannot support a claim that a 2–4% A/G difference is a
code-layout effect. That is exactly why the plan required A/A first.

## 4. Consequence for the architecture

The outside-dispatch architecture (`exact_term_physical_eligible` called from
`execute_unified`, generic `collect_mixed` untouched, private
`#[inline(never)] collect_exact_term_physical`) remains an **unmeasured
proposal**. It needs a future, separately approved study whose stability control
is sensitive enough to be useful on sub-millisecond lanes — for example more
measured samples per slot, more campaigns, or a per-lane stability criterion
specified before data. This plan forbids the agent from inventing such a change.

## 5. Nothing else is claimed

No `B_IMPLEMENTATION_SHA`, no `B_MEASURED_SHA`, no nine-lane campaign, no
`C-P06..C-P09` verdict and no real-RustFS acceptance exist for this follow-up.
