# PR 15I-C batched-noise study — results

Protocol: `benchmarks/pr15i_c/batched_protocol_v1.json` (`pr15i-c-batched-noise-v1`,
SHA-256 `171c30c0ed9ff9327126f5c8876d75ce5606aa8e7df732e3d5cf4638cb5944bf`
recorded in every manifest and receipt).
Tooling: `BATCH_TOOLING_SHA = 0a84c023178ed43eb917d20317f2ea469fdd12ed` plus the
scope-allowlist fixup `9381c3eb0052878712eb0cb67758f8f05b5c70d7`; both committed
**before** the first sample.

## 1. What was measured

* Seven frozen PR15D warm lanes, eight paired blocks
  (`ABBA BAAB BAAB ABBA BAAB ABBA ABBA BAAB`), 32 slots per campaign.
* Four absent/rare lanes measured as **100-search timed batches**; three common
  lanes as 1-search controls. Five single-query warmups per lane per slot, then
  ten complete timed batches.
* Per campaign: 2 240 batch observations, 1 120 warmups, **130 080 executed
  searches**, 12 freshly rebuilt index directories.
* Eight campaigns in the fixed interleaved order `aa-01, ag-01, … ag-04`:
  **17 920 batches, 8 960 warmups, 1 040 640 searches, 96 rebuilds**.
* One host fingerprint, one `rustc 1.98.1`, release profile, native `ext4`, and
  one predeclared CPU affinity mode (`PINNED`: adapter CPU 0, controller CPU 1).
* Derived adapter: the frozen PR15D `main.rs` blob `42d2858e…` patched by exactly
  two deterministic hunks; `query`/`build`/`metadata`/`shutdown` and
  `QuerySession::open` unchanged; `query_batch` returns raw integer `batch_ns`
  from one outer `Instant` and never emits `engine_ns`.

## 2. A/A (identical executable) — **PASS**

| Lane | aa-01 | aa-02 | aa-03 | aa-04 | Aggregate |
|---|---|---|---|---|---|
| 10K absent | 0.9968 | 1.0149 | 1.0099 | 1.0079 | 1.0089 |
| 10K rare | 1.0085 | 1.0060 | 0.9978 | 1.0088 | 1.0073 |
| 10K common | 0.9969 | 0.9916 | 0.9753 | 1.0013 | 0.9943 |
| 100K absent | 1.0036 | 0.9985 | 0.9986 | 1.0046 | 1.0011 |
| 100K rare | 1.0014 | 0.9983 | 0.9971 | 1.0016 | 0.9999 |
| 100K common/k100 | 1.0037 | 0.9969 | 1.0005 | 1.0058 | 1.0021 |
| 100K common/k10 | 0.9995 | 0.9922 | 0.9954 | 0.9974 | 0.9964 |

Every aggregate is inside `[0.97, 1.03]`, all 28 campaign medians are inside
`[0.94, 1.06]` (so ≥3/4 per lane trivially), none is outside `[0.85, 1.15]`, and
every short-lane slot median exceeds the 1 ms floor. **Zero** per-block ratios
above 1.15 across all 4 × 7 × 8 = 224 block ratios.

That is the decisive improvement over the earlier single-query study, which
measured the *same binary* at 0.8496 on 10K absent. Repeated-query batching
removed the short-query timing variance.

## 3. A/G (pinned historical `#[inline(never)]` control) — neutral observation

| Lane | ag-01 | ag-02 | ag-03 | ag-04 | Aggregate | Runs ≤1.05 |
|---|---|---|---|---|---|---|
| 10K absent | 1.0010 | 0.9873 | 0.9836 | 0.9949 | 0.9911 | 4/4 |
| 10K rare | 0.9975 | 0.9971 | 0.9965 | 1.0026 | 0.9973 | 4/4 |
| 10K common | 0.9917 | 0.9876 | 0.9881 | 0.9836 | 0.9878 | 4/4 |
| 100K absent | 0.9991 | 0.9917 | 1.0053 | 1.0020 | 1.0006 | 4/4 |
| 100K rare | 0.9980 | 0.9936 | 1.0037 | 0.9975 | 0.9978 | 4/4 |
| 100K common/k100 | 0.9943 | 0.9888 | 0.9879 | 0.9951 | 0.9915 | 4/4 |
| 100K common/k10 | 0.9715 | 0.9861 | 0.9848 | 0.9820 | 0.9834 | 4/4 |

Aggregate decision: `15IC_AG_DIAGNOSTIC_NEUTRAL`. Recorded as an observation
only; it never authorizes the outside-dispatch candidate and the historical F0
rejection under its own stricter rule is untouched.

## 4. Honest limitations of the batch protocol

* It measures a **hot repeated-query throughput regime** with one reused snapshot
  and possible cache warming. It cannot prove single-request tail latency, and
  the ten batches per lane/slot are **not** 100 independent samples.
* `mean_per_query_ns = batch_median / repeat_count` is a derived representation,
  never an independent distribution. Every receipt carries `sample_unit = batch`
  and `timing_basis = outer_Rust_Instant_full_batch`, and the verifier rejects
  mixed units, `engine_ns` in a batch reply, or a forged derived value.
* Consequently the batched study could pass while the frozen unbatched contract
  failed — which is exactly what happened
  (`batched-performance-decision.md`).

## 5. Artefacts

| Artefact | Location |
|---|---|
| Eight sealed campaigns | `target/pr15i-c/batched-noise-v1/{aa,ag}-0N` |
| Eight run receipts | `target/pr15i-c/reviews/batched-v1-{aa,ag}-0N.json` |
| Aggregate receipt | `target/pr15i-c/reviews/batched-v1-series-aggregate.json` |
| Protocol | `benchmarks/pr15i_c/batched_protocol_v1.json` |
| Tooling | `benchmarks/pr15i_c/{batched_adapter_patch,batched_noise,verify_batched_noise}.py` + 92 tests |

Component seal digests and every per-block ratio are in the aggregate and
per-run receipts; only sanitized metrics are committed here.
