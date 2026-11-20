# Legacy retirement ledger (BM-09)

**NO_RETIREMENT_AUTHORIZED.**

Historical parity is not `PASS` (see `historical-equivalence-matrix.md`), so every
original legacy path stays exactly where it is, byte-identical, at its original
revision. No file was deleted, moved, renamed or rewritten by BM-09.

| Legacy path | Inventory disposition | BM-09 disposition | Reason |
| --- | --- | --- | --- |
| `benchmarks/pr15d/harness/run.py` | `retain_live` | `retain_live` | Authorized measurement backend for `cross-engine-keyword-real-v1` |
| `benchmarks/pr15d/harness/validate.py` | `retain_live` | `retain_live` | Original validator for the same family; digest pinned in the freeze |
| `benchmarks/pr15d/harness/aggregate.py` | `retain_live` | `retain_live` | Original calculation cross-checked read-only by Gate C |
| `benchmarks/pr15d/harness/smoke.py` | `retain_live` | `retain_live` | Functional diagnostic; never official evidence |
| `benchmarks/pr15d/corpus/{generate,oracle}.py` | `retain_live` | `retain_live` | Independent corpus and answer source |
| `benchmarks/pr15d/spec/pr15d_v1.json` (+ `.md`) | `retain_live` | `retain_live` | Frozen backend specification |
| `benchmarks/pr15d/adapters/{quervant,tantivy,lucene}/**` | `retain_live` | `retain_live` | Source/lock/checksum identities of the three engines |
| `benchmarks/pr15i_d3_c/run.py` | `retain_live` | `retain_live` | Authorized retained-key measurement backend (requires T6) |
| `benchmarks/pr15i_d3_c/verify.py` | `retain_live` | `retain_live` | Original independent verifier |
| `benchmarks/pr15i_d3_c/protocol_v3r3.json` | `retain_live` | `retain_live` | Frozen protocol, `diagnostic_only=true`, raw digest pinned |
| `benchmarks/pr15i_d3_c/tooling_manifest.json` | `retain_live` | `retain_live` | T6 protected file |
| `benchmarks/pr15i_d3_c/{analysis_v3,policy,replay,stability_diagnostic}.py` | `read_only_adapter_later` | `retain_live` | Historical analysis inputs; no migration performed |
| `benchmarks/pr15i_d3_c_t7/**` | `retain_live` | `retain_live` | T7 policy/derivation chain |
| `benchmarks/pr15i_d3_c_t7_f2/**` | `retain_live` | `retain_live` | T7-F2 acceptance/policy verifier |
| `benchmarks/reports/**` | `preserve_archive` | `retain_live` | Immutable historical reports |
| `target/pr15i-d3-c/**` (untracked) | `preserve_archive` | `retain_live` | Operator-owned raw evidence; untouched (absent on this host) |
| `~/.local/share/quervant/benchmark-evidence/pr15i-d3-c-v3r3/**` | n/a | `retain_live` | Authentic archives; hashed read-only, never rewritten |

## Rollback

Reverting this branch removes `benchmarks/quervant_bench/official/`, the two design
templates, the BM-09 test modules and documentation, and restores the single changed
helper's call site, without touching any legacy entrypoint, protocol, archive or
synthetic L2 acceptance. The synthetic QA fixture chain would then need the
pre-change anchors restored from Git history; no raw evidence is affected.

## Operator migration continuation (2026-11-19)

This section updates implementation mapping after E2; the preceding table is the
earlier disposition. **No retirement is authorized or performed.**

| Legacy responsibility | Current framework owner | Preserved legacy role |
| --- | --- | --- |
| PR15D adapter/corpus preparation and three-engine measurement | `official/cross_engine_backend.py`, reached through `official/workflow.py` | Original build, correctness, index/query and sample-producing primitives remain live |
| PR15D A/A qualification | `official/cross_engine_backend.py` plus `official/controls.py` | Same Quervant primitive in both arms; dedicated complete control precedes treatment |
| D3-C preparation and complete control/treatment series | `official/retained_backend.py` and `official/retained_acquisition.py` | Original pinned builds, timing primitives, records, seals, predecessor checks and verifier remain live |
| D3-C raw readiness and summaries | `official/legacy_readiness.py` and `official/admission.py` | Historical bytes are read without rewriting their format |
| T7/F2 policy derivation | `official/policy_inputs.py`, `official/retained_policy.py`, `official/policy_reference.py` | Authentic P2/F1 inputs and frozen original calculations remain the compatibility basis |
| Authentic historical equivalence | `official/historical.py` | Original verifiers and independently approved archive mappings remain required |
| Public real/synthetic progression | `execution/operator.py`, `official/workflow.py`, `execution/synthetic_operator.py` | Earlier native Criterion and diagnostic entrypoints remain available for their separate purposes |

The required representative families now have a common configured operator path.
Real execution and accepted historical parity are still required before any
itemized deletion, relocation or compatibility-only disposition. No frozen
protocol, original measurement implementation or archive changed in this migration.
