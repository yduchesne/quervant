# PR 15I-D3-A-F2 correctness trace

| Invariant | Evidence |
|---|---|
| F2-INV-01 protected BASE/derivative unchanged | preflight blob checks, source proof `VERIFIED` |
| F2-INV-02 A pristine; Q/P same binary; P payload after `engine_ns` | build metadata, slot verification |
| F2-INV-03 24 slots, nine lanes, 20 samples + 5 warmups, 2 probes | seal inventories and slot counts |
| F2-INV-04 all non-timing invariants block globally | verifier oracle/source/index/binary/shape checks |
| F2-INV-05 lane-scoped timing qualification | `lane-qualification-v3.json`, tests F2-V12/V18 |
| F2-INV-06 control policy unchanged | control QUALIFIED, no tolerated outlier |
| F2-INV-07 five complete runs, no sixth/replacement | five archived v3 campaign directories |
| F2-INV-08 one run-level observation per area/lane | `five-run-areas-v3.json` |
| F2-INV-09 ≥4 eligible runs for inference | primary lanes n=5; 10K rare n=4 |
| F2-INV-10 same four run IDs for localization | decision runs 01–05, two lanes |
| F2-INV-11 numeric gates unchanged | v3/v2 diff test, 92 targeted tests |
| F2-INV-12 low-hit lane not a future guardrail | 10K rare excluded in run 03 |
| F2-INV-13 sampled/direct scopes separated | seven-area report and tests |
| F2-INV-14 exclusive sealed archives | archive sidecars and round-trip checks |
| F2-INV-15 no optimization authorized | docs and verdict wording |
