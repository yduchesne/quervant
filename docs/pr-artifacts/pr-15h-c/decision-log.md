# PR 15H-C — decision log

| ID | Trigger | Action | Evidence |
|---|---|---|---|
| HC-D01 | Branch/HEAD matched §0 | Continued in place | preflight |
| HC-D04 | Historical 15G-C rejected | Preserved; implemented 15H-C only | preflight |
| HC-D08 | `doc_keys()` returns `Rc<Vec<DocumentKey>>` | Borrowed existing cache; no reader change | correctness |
| HC-D10 | `single_hit_segment` unchanged | Preserved `doc_key_selected` | `c_u02` |
| HC-D12 | Eligibility unchanged | New path only under `keyword_field_id` | `c_u20`/B tests |
| HC-D14 | Checked borrowed key | `cached_doc_key_ref` | `c_u09` |
| HC-D15 | Out-of-range id | Exact `Corrupt { context: "doc keys" }` | `c_u10/u11` |
| HC-D21/D22 | Winner vs loser | Clone only at admission; no per-loser clone | `c_u04/u05` |
| HC-D23 | LegacyDecode | One clone + unchanged owned fallback | `c_u16` |
| HC-D25 | Heap/budget unchanged | Kept `heap_admit_candidate` | B/phase4 tests |
| HC-D26 | Duplicate retained key | Existing error before discard | `c_u15` |
| HC-D32 | Borrow scoped to keyword branch | Segment-local `Rc` + block scope | compile/tests |
| HC-D35 | B malformed-loser test | Updated call to `&key`; behavior preserved | `b_tests` |
| HC-D41 | Real RustFS healthy | Full matrix executed | qa-and-ci |
| HC-D43 | WSL2 assumed idle, probes clear | Full four-block campaign | performance |
| HC-D51/D54 | C tool copy/thresholds | Mechanical substitutions; new gates | controller tests |
| HC-D58 | Primaries/guards | P1/P2/P3 failed | performance |
| HC-D59 | Qualified primary/guard failure | Safe rollback `unified.rs` | rollback-or-keep |
| HC-D61 | Final stable/MSRV/QA passed | Recorded | qa-and-ci |
| HC-D63 | No push/PR | `CI_PENDING` | qa-and-ci |

No HARD STOP or unmatched condition occurred.
