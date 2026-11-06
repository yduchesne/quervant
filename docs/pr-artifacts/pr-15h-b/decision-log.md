# PR 15H-B — decision log

| ID | Trigger | Action | Evidence |
|---|---|---|---|
| HB-D01 | Branch/HEAD matched the prescribed literals | Continued in place; no new branch | preflight |
| HB-D04 | Historical A/A2/A3 evidence present, search equals accepted | Preserved; did not execute rejected staging | preflight |
| HB-D06 | `span_of`/variable layout matched the reviewed contract | Implemented B-D01 exactly | design-verification |
| HB-D07 | Keyword wire remains u16 length + UTF-8 | Reused `len_prefixed_u16`, UTF-8, `DecodeBudget`, `expect_end` | `b_u14`/`b_u18` |
| HB-D08/D09/D10 | Absent/empty → Missing, explicit null → Null | Implemented and tested | `b_u06_u16` |
| HB-D11 | Valid `STATE_SINGLE` keyword | Borrowed after full validation | `b_u06_u16` |
| HB-D12/D13 | Multi/unexpected state | `LegacyDecode` → ordinary candidate path | `b_u06_u16`; fast fallback |
| HB-D14/D15 | Invalid UTF-8 / budget | Same typed errors, before competitiveness | `b_u14`/`b_u18` |
| HB-D17 | Valid Missing/Null/Value | Rank + raw byte order, DESC reverses values only | comparator tests |
| HB-D18/D19 | Incompatible retained value / LegacyDecode | Ordinary candidate handling | comparator tests |
| HB-D20/D21 | Eligible vs unsupported shape | Fast vs unchanged legacy | `b_u01`/`b_u04` |
| HB-D22 | `retain=true` with `batch=None` | Verified caller contract (`search` is standalone) | source review |
| HB-D25/D26/D27/D28 | Heap not full / lose / tie / win | Materialize only at admission; key tie; original replacement | `b_u01`, budget tests |
| HB-D29 | Duplicate retained key on loser | Old `CorruptIndex` before discard | fast-path check |
| HB-D30/D31 | Checked charge / parity | Identical formula; test-only equality assert | `borrowed_keyword_candidate_charge` |
| HB-D33/D34/D35 | Batch/cursor/aggregation/JSON | Legacy path | `b_u04` |
| HB-D41 | Tooling/source SHAs clean detached | Baseline sealed before source edit | baseline.md |
| HB-D44 | WSL2 native ext4 and idle authorization | Ran baseline/paired with real probes | performance.md |
| HB-D52 | P1 and P2 met the 5 ms rule | Evaluated all remaining gates | performance.md |
| HB-D60 | Real RustFS available on pinned image | Ran the full CI-equivalent suite | qa-and-ci.md |
| HB-D72 | All local gates pass and performance accepted | Kept candidate; `LOCAL_QA_PASS`; no merge | qualification.md |
| HB-D71 | Branch not pushed | `CI_PENDING` recorded | qa-and-ci.md |

No HARD STOP occurred. No threshold, lane, sample or scope change was made after
the baseline.
