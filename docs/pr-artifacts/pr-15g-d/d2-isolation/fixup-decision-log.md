# D2 isolation harness fixup — decision log

| Rule | Trigger | Action | Evidence |
|---|---|---|---|
| HX-D01 | HEAD `317d60d`, correct branch, clean | Proceeded | preflight |
| HX-D04 | `main` ancestor, A accessible | Reused A | git ancestry |
| HX-D06 | Local X exists, parent A | Reused X | source proof |
| HX-D08 | Frozen inputs match | Reused helpers | verify_frozen_inputs |
| HX-D10/11 | Relocated test context, exact added/removed streams match | Ignored patch-ID; accepted exact edits | `fixup-design-verification.md` |
| HX-D12 | 15/0 + 43/1 edits, 58/1 total | Source proof PASS | tracked `_assert_exact_d2_edits` |
| HX-D20/22/24 | Frozen nearest-rank summary equals all six fields | Accepted lane records | 48 tests pass |
| HX-D25 | Tampered median/p95/missing field | Rejected | summary tests |
| HX-D29 | 16 valid slots, 32 clear probes | Sealed 18 raw files before drift | campaign seal |
| HX-D33 | Seal keys/hashes valid | Verify-only rehashed all 18 | `--verify-only` |
| HX-D36 | Drift within 1.25/1.50 | Qualified campaign | campaign report |
| HX-D42 | Qualified report byte-identical | Evidence verified | verify-only |
| HX-D51 | Standing idle authorization; probes clear | Ran exactly one fresh campaign | raw probes |
| HX-D53 | Not both common targets; guardrail `A_FASTER` | DX-P01/P02 FAIL | campaign report |
| HX-D54 | Qualified failure | Restored exact A blobs | byte proof |
| HX-D56 | Selected blobs equal A | PASS | git diff quiet |
| HX-D58 | Stable/MSRV QA and coverage pass | PASS | qualification |
| HX-D60 | Future exact-HEAD CI | Pending final docs commit | CI |
| HX-D64 | Historical evidence preserved | PASS | diff audit |
| HX-D66 | Any further campaign needs new approval | Not run | this log |
| HX-D67 | All gates except independent review | Ready for review only | qualification |
