# D2-only isolation qualification — amended run

**Status:** `MEASUREMENT_BLOCKED_REVIEW_REQUIRED`
**Supersedes run-status portion of:** `qualification.md` (historical blocker kept unchanged)

| Gate | Status | Evidence |
|---|---|---|
| DX-A00 preflight | PASS | authorized docs HEAD and ancestry verified |
| DX-A01 exact D2 source identity | PASS | `source-proof-amended.md`, `DX-SOURCE-ID` |
| DX-A02 X correctness / baseline | PARTIAL | original D2 test passed; no performance decision |
| DX-A03 harness/tests | PASS for implemented cases | 12 new tests, 38 total Python tests |
| DX-A04 16 slots / nine lanes / 20 samples | PASS acquisition | 144 lane records, 2,880 samples |
| DX-A05 medians/ratios/drift | **BLOCKED** | A 100K rare cross drift 1.2994 > 1.25 |
| DX-A06 DX-P01 | NOT EVALUATED | drift blocked |
| DX-A07 DX-P02 | NOT EVALUATED | drift blocked |
| DX-A08 DX-P03/P04 | NOT EVALUATED | campaign not qualified |
| DX-A09 disposition | UNCHANGED | no source change |
| DX-A10 final QA | PREVIOUS SOURCE | no production change; harness tests pass |
| DX-A11 RustFS | PREVIOUS SOURCE | existing D1/D2 evidence retained |
| DX-A12 final CI | TO BE OBSERVED | docs-only follow-up |
| DX-A13 history preserved | PASS | old blocker/source-proof untouched |
| DX-A14 independent review | PENDING | no self-approval |

The failed gate is `DX-A05`, not `DX-P01` or `DX-P02`. No performance
classification is available.
