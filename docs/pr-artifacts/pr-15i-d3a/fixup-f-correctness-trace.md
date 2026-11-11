# PR 15I-D3-A-F correctness trace

| ID | Invariant | Evidence |
|---|---|---|
| INV-01 | BASE and protected sources unchanged | preflight, protected diff |
| INV-02 | Historical T0/T0b artifacts untouched | git history, archive hashes |
| INV-03 | Six-path insertion-only derivative, 25 stages/15 counters unchanged | source proof, tests |
| INV-04 | A uninstrumented; Q/P same binary; P payload after `engine_ns` | build/slot verification |
| INV-05 | One soft outlier only in the two exempt 10K lanes | `ControlPolicyTests`, real control |
| INV-06 | Distinct control build/output namespaces | `BuildNamespaceTests` |
| INV-07 | Exactly five complete paired runs | aggregate inventory |
| INV-08 | 20 samples + 5 warmups, fresh process, 2 clear probes/slot | controller/verifier |
| INV-09 | Oracle, index digests and sentinels per run | verifier |
| INV-10 | Five run-level observations, not pooled queries | `five_run_stats` tests |
| INV-11 | Sampled children and direct nested timers not added | area mapping tests |
| INV-12 | Original thresholds plus predeclared 4-of-5 rule | `PriorityTests` |
| INV-13 | Blocked aggregate on any unqualified run | `aggregate_series` |
| INV-14 | Verifier independent of controller | source inspection/tests |
| INV-15 | Required gates executed | final QA |

The official T0c control qualified. Runs 01–03 qualified; run 04 failed the
paired A/A stability gate and halted the series. The pre-T0c dry run is
preserved separately and is not official evidence.
