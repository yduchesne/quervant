# HX-T01–HX-T47 traceability

**Status:** `PARTIAL` — source/report adversarial coverage added, but not every
row has a dedicated one-to-one assertion. No claim of HX-A07 PASS.

| ID | Evidence / status |
|---|---|
| T01 | `SourceProofTests.test_real_local_a_x_exact_edits` — covered |
| T02 | `HxExactSourceMutationTests.test_hx_exact_source_edit_mutations` wrong-parent subcase — covered |
| T03 | real A/X exact-file allowlist — covered |
| T04 | third-file mutation — **GAP** |
| T05 | real local context relocation, exact edits — covered |
| T06 | extra-line mutation — covered |
| T07 | missing-addition mutation — covered |
| T08 | unexpected-test mutation — covered |
| T09 | changed deletion stream — **GAP** |
| T10 | reordered additions — **GAP** |
| T11 | D1 symbol injection — **GAP** (real X scans clean) |
| T12 | missing D2 test/counter — **GAP** |
| T13 | dirty worktree/binary — campaign immutable checks; no unit mutation |
| T14 | frozen/lane drift tests — covered |
| T15 | schedule/partial-slot tests — covered |
| T16 | lane order/descriptor tests — covered |
| T17 | oracle validation — campaign witness |
| T18 | sample count/type tests — covered |
| T19 | contention rejection test — covered |
| T20 | block-median arithmetic tests — covered |
| T21 | four-ratio arithmetic — covered |
| T22 | all-below verdict — covered |
| T23 | all-above verdict — covered |
| T24 | equality/mixed verdict — covered |
| T25 | drift/nonfinite diagnostics — covered |
| T26 | 100K exact 1.25 boundary — covered |
| T27 | 100K over limit — covered |
| T28 | 10K exact 1.50 — covered |
| T29 | 10K over limit — covered |
| T30 | both common targets pass — covered |
| T31 | one common target fail — covered |
| T32 | 10K rare `A_FASTER` — covered |
| T33 | 10K absent guardrail — gate test covered |
| T34 | 100K medium regression — gate set covered |
| T35 | other lanes inconclusive + common faster — covered |
| T36 | unqualified probe blocks verdict — campaign witness |
| T37 | sanitizer absolute path/private markers — covered |
| T38 | sanitizer sensitive environment/credential — **GAP** |
| T39 | JSON byte/ordering change — covered by verify byte test |
| T40 | Markdown byte change — covered |
| T41 | raw slot changed after seal — covered |
| T42 | repeated verify-only idempotence — covered |
| T43 | unknown exception — **GAP** |
| T44 | legacy v1 unsealed refusal — covered |
| T45 | same output directory twice — **GAP** |
| T46 | qualified D2 acceptance blob equality — N/A: D2 rejected |
| T47 | rejected/blocked source behavior — covered by exact-A rollback |

## Remaining work for HX-A07 PASS

Add dedicated deterministic cases for T04, T09–T12, T38, T43 and T45, or obtain
human acceptance that the current adversarial coverage is sufficient. Until
then HX-A07 remains PARTIAL.
