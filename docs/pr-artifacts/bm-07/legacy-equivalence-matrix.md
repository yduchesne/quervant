# BM-07 legacy equivalence matrix

Reviewed literal: `benchmarks/quervant_bench/tests/fixtures/retained-key/historical-compatibility.v1.json`

The matrix is a set of **equivalence classes**, not a numerical comparison.
Historical D3-C/T7/T7-F2 files remain read-only. No historical controller,
acquisition launcher, policy writer or timing command is executed.

| ID | Legacy component | New component | Class | Required input | Expected comparison | If missing |
|---|---|---|---|---|---|---|
| H01 | `pr15i_d3_c/protocol_v3r3.json` freeze/source/workload identity | BM-01 retained-key bundle/protocol | `SEMANTIC` | frozen protocol and pinned SHA-256 | scope/provenance intent only | `EVIDENCE_UNAVAILABLE` |
| H02 | D3-C `A,L,P,H`, two appearances and 12 blocks | four labels, 4-block simulation | `NON_EQUIVALENT_CONTRACT` | both declarations | shape/type only | `EVIDENCE_UNAVAILABLE` |
| H03 | D3-C `verify.py` oracle/readiness stop | BM-03 simulated oracle/readiness | `SEMANTIC` | legacy verifier source, scenario | fail-closed intent only | `EVIDENCE_UNAVAILABLE` |
| H04 | D3-C `analysis_v3.py`, T7 `analysis.py`, `verify_derived.py` | BM-04/BM-05 statistics | `NON_EQUIVALENT_CONTRACT` | authentic outputs plus approved mapping | no numeric equality or float tolerance | `EVIDENCE_UNAVAILABLE` |
| H05 | D3-C/T7 `policy.py`, T7-F2 `oracle.py`, `verify_policy.py` | BM-04/BM-05 decisions | `NON_EQUIVALENT_CONTRACT` | authentic decisions plus approved mapping | no inferred selected-strategy parity | `EVIDENCE_UNAVAILABLE` |
| H06 | D3-C/T7-F2 archived evidence/QA/acceptance | BM-06 A–E | `SEMANTIC` | authentic archive and pinned BM-06 profile | authenticity/fail-closed intent only | `EVIDENCE_UNAVAILABLE` |
| H07 | D3-C/T7-F2 original freeze/archive admission | BM-03 seal/BM-06 admission | `SEMANTIC` | authentic original archive/source identity | integrity intent only | `EVIDENCE_UNAVAILABLE` |
| H08 | exact archived numerical outputs | BM-04/BM-05 outputs | `EVIDENCE_UNAVAILABLE` | independently pinned original series | numeric parity not executed | `EVIDENCE_UNAVAILABLE` |

## Why H04/H05 are not exact

D3-C's frozen `median4(v)` is `sorted(v)[1]`, the **lower-middle** of four
values. An ordinary median of four values averages the two middle values. For
`[1, 2, 100, 200]`, the historical convention gives `2`; the ordinary median is
`51`. That difference exists before any bootstrap, filtering, per-k threshold,
cross-arm attribution or memory contract is considered.

D3-C also uses per-`n`/per-class within-arm caps and per-k policy thresholds,
while the new synthetic reference declares one general 4-block schedule, one
symmetric per-lane cap and one `aux-memory-bytes` rule. These are distinct
decision contracts. No tolerance or strategy projection is authorised.

## Current status

```text
HISTORICAL_EVIDENCE_STATUS=EVIDENCE_UNAVAILABLE
HISTORICAL_NUMERIC_PARITY=NOT_EXECUTED
HISTORICAL_DECISION_PARITY=NOT_EXECUTED
LEGACY_PATHS_RETIRED=NO
HISTORICAL_ACCEPTANCE_GATE=BLOCKED (scoped, not waived)
```

`target/pr15i-d3-c` is an empty directory stub. The assessor authenticates the
checked-in protocol digest and rejects missing/incomplete archives. A newly
generated synthetic run placed under the historical root cannot satisfy the
required campaign/provenance checks and never becomes an authentic archive.
