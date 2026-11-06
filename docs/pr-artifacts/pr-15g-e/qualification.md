# PR 15G-E qualification

**Status:** `E_PERFORMANCE_REJECTED_SAFE_ROLLBACK`

| Gate | Status | Evidence |
|---|---|---|
| E-A00 source identity | PASS | A+B source and fresh main recorded |
| E-A01 D HX-A07 full matrix | **PARTIAL** | source/report adversarial tests added; not all 47 rows one-to-one |
| E-A02 D finalization | PASS | D negative disposition recorded |
| E-A03 E invariants | PASS for implemented surfaces | codec/reader/format tests |
| E-A04 v1.0 compatibility | PASS | legacy builders/tests byte-stable |
| E-A05 v1.1 wire/old-reader rejection | PASS | format tests |
| E-A06 codec corruption/limits | PASS | offset-directory tests |
| E-A07 certification/fallback | PASS for tested cases | selected access + bad interior boundary |
| E-A08 local writer/mixed/PIT | PASS | workspace integration |
| E-A09 real RustFS | PASS for pre-existing suites on final A+B source | CI and local evidence |
| E-A10 frozen oracle/format-aware campaign | PASS | 16 slots, 2,880 samples |
| E-A11 E-P03/E-P04 | **REJECT** | rare regressions and common `A_FASTER` |
| E-A12 size/cold validation disclosed | PARTIAL | size delta tooling present; no profiler |
| E-A13 stable/MSRV fmt/Clippy/tests | PASS | see final QA |
| E-A14 coverage | PASS >=85% | actual value in final report |
| E-A15 final source = A+B | PASS | exact rollback |
| E-A16 exact-HEAD CI | pending final docs commit | CI |
| E-A17 docs/raw evidence | PASS | historical/raw preserved |
| E-A18 independent review | PENDING | no self-approval |

## Outcome

E is not retained. The branch returns to exact accepted A+B production source.
The E codec/wire implementation is preserved in Git history and its sanitized
performance evidence remains under `docs/pr-artifacts/pr-15g-e/`. No threshold
change or selective retry was performed.
