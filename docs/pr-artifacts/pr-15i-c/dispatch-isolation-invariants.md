# PR 15I-C dispatch-isolation — invariants and counterexamples

| ID | Invariant | Counterexample test | Evidence |
|---|---|---|---|
| I01 | A is the byte-identified merged baseline | mutate an A Git blob/binary byte | SI (source proof), `DV_BINARY` |
| I02 | C is exactly `658a2dd…`, feature `pr15ic-causal`, runtime `disabled` | measured C process with unset/`enabled` mode | `DV_FEATURE`, arm mode truth table |
| I03 | D shares all C production blobs except one expression | extra diff, inline attribute, changed generic source | `verify_d` (normalized equality) |
| I04 | D's false branch never runs the operator; the mode variable is ignored | `enabled`/unset/invalid all identical | `test_dv15_d_ignores_every_mode_value` |
| I05 | E has no physical operator and only a generic trampoline | any `collect_exact_term_physical` definition or operator call | `verify_e`, `DC-V` source searches |
| I06 | All arms produce exact oracle output | wrong key/count/sort/score | `DV_ORACLE`, `DV_SCORE` |
| I07 | Identical storage format, sidecars, segment digests, corpus | one segment-digest mismatch | `verify_indexes` (24 on-disk rebuilds) |
| I08 | No generic collector body/attribute drift in any arm | inline attribute or body edit | body SHA `00c5a1c8…` in A/C/D/E |
| I09 | One query execution per unbatched observation | batch substitution | `DV_UNIT` |
| I10 | Batched observations are whole batches | `engine_ns` in a batch reply / forged derived value | controller `DP_UNIT`, `DV_UNIT` |
| I11 | Immutable binaries/toolchain/affinity/host captured per campaign | replayed path/hash mismatch | `DV_BINARY`, receipts |
| I12 | Controller and verifier recompute independently | forged ratio while re-sealing | `DV_RATIO`, `DV_SAMPLE` (re-sealed tamper) |
| I13 | Frozen acceptance protocol and historical campaigns unchanged | altered `protocol.json`/old raw | `DV_PROTOCOL`, preflight |
| I14 | Production paths equal A at the final tip | residual feature/test file | protected diff check |
| I15 | No machine-code claim without real disassembly | D's physical symbol assumed retained | `independent_codegen` re-capture |
| I16 | Failures never yield synthetic success | invalid cursor/cancellation/corruption | `DV_ORACLE`, unit/integration suites |

## Interpretive limitations recorded before coding

* **D may be fully optimized.** `if false && shape_eligible` lets the compiler delete
  the physical call and possibly the operator symbol; the disassembly decides what
  is present. A D result therefore says "the candidate with the physical path
  compile-time-disabled", not "the operator still costs X".
* **E is a scaffold control, not a mirror.** Its out-of-line trampoline, extra
  runtime branch and `black_box` barrier change call structure relative to C; a
  neutral E shows that *this minimal scaffold* does not reproduce the regression,
  not that C's control flow is equivalent.
* **C/A, D/A, E/A are whole-binary effects.** They mix the audited source delta with
  linker layout and remaining candidate code; none of them isolates a single
  compiler transformation.
* **Batched timing is hot-throughput**, not single-request tail latency, and never
  overrides the unbatched classification.

## Why each tempting shortcut is excluded

1. Comparing C against a **default-feature** candidate binary → changes the arm (forbidden; C is built with `pr15ic-causal`).
2. Probing E with an **unset** mode → typed error by design, not a measurement.
3. Treating D's `enabled` env as meaningful → the literal false makes the gate unreachable; all values must agree.
4. Pooling the 40 samples of a block instead of averaging two slot medians → changes the frozen estimator.
5. Using Python's `statistics.median` → averages the central pair of even-length lists; the protocol fixes nearest-rank.
6. Calling `batch_ns/100` an independent sample → rejected by the unit checks.
7. Majority-voting lanes/campaigns to force a row → the §8 table requires *all* required cells to agree, otherwise MIXED.
8. Naming a cycle/cache cause from an instruction count → no counters exist; `perf` is unavailable.
