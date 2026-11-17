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
