# PR 15G-B qualification

**Status:** `FIXUP_IMPLEMENTED_LOCAL_QA_PASS_PERF_QUALIFIED_CI_PENDING`
**Shared branch:** `dev/pr15g-a-retained-column-geometry`
**GB_BASE_SHA:** `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c`
**GB_OPT_SHA (measured B):** `4e7949ad12236a0feeee671c6221119b8a998cc7`
**Umbrella PR:** #86 `https://github.com/yduchesne/quervant/pull/86`
**Performance:** GB-P01–P05 **PASS**
**Real RustFS:** GB-R01/R02 **PASS locally** on the pinned image
**Hosted CI:** recorded after the final push (see final report / below)

## Correctness and quality gates

| Gate | Status | Evidence |
|---|---|---|
| GB-A00 shared branch/15G-A/preflight | PASS | shared tip `3329dd8`; 15G-A CI run `41774735678` success; no main merge required |
| GB-A01 allowlisted lazy-offset architecture | PASS | only `stored.rs`, `reader.rs`, test-only snapshot/additive tests, new tests/runner/CI/docs |
| GB-A02 full validation before publication | PASS | shared scanner + U01–U12, U16–U19, U27 |
| GB-A03 metadata admission/fallback/RAII/concurrency | PASS | U19–U26, U28 |
| GB-A04 full-cache precedence/PIT/cursor/query parity | PASS | U13/U23, I01–I08 |
| GB-A05 real RustFS cold bootstrap and faults | PASS locally | GB-R01 1 passed; proxy 7; K0 5; K05 10/10 |
| GB-A06 frozen source/index/corpus/format parity | PASS | identical index digests, frozen report SHA unchanged |
| GB-A07 stable/MSRV/coverage/docs/scripts | PASS | 2287/2291 tests, 92.68% coverage |
| GB-A08 nine-lane A/B | PASS | GB-P01–P05 all PASS |
| GB-A09 exact-head hosted CI | PENDING/BLOCKED until observed | PR #86; final-head run must be checked |
| GB-A10 independent review | NOT STARTED | human-owned |

## Focused test results

- `segment::stored::pr15g_b_tests` — 12 tests (U01–U12/U15 witnesses).
- `segment::reader::column_geometry_tests::gbu*` — 13 tests (U16–U28 witnesses).
- `pr15g_b_access` — 8 integration tests (I01–I08).
- `pr15g_b_rustfs` — 1 real pinned-RustFS test (R01).
- `benchmarks/pr15g_b` — 18 deterministic runner tests (B01–B16).
- Existing `pr15g_a_column_geometry` 6, `pr15e_b1` 17, `pr15c_a_segment_state` 5,
  `pr06_local_integration` 13 passed (3 ignored).

## Full local QA

| Gate | Result |
|---|---|
| fmt stable/MSRV | PASS |
| Clippy stable/MSRV default/all-features | PASS |
| Workspace tests stable/MSRV | PASS — 2287 passed, 10 ignored |
| All-feature workspace tests | PASS — 2291 passed, 77 ignored |
| Coverage | PASS — **92.68%** workspace line coverage |
| `stored.rs` / `reader.rs` line coverage | 92.65% / 91.34% |
| Doc / bench build / scripts | PASS |
| Python suites | 108 / 83 / 54 / 16 / 18 PASS |
| `git diff --check` | PASS |

## Real RustFS / fault execution

Using `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
in a disposable local service:

| Test | Result |
|---|---|
| `pr15g_b_rustfs::gb_r01_real_rustfs_cold_bootstrap_selected_access` | 1 passed |
| `pr13_remote` ignored suite | 3 passed |
| `pr13_oracle` ignored suite | 1 passed |
| `pr13_remote_proxy` ignored suite | 7 passed (H06/H07/H09 included) |
| `pr13_crash_rustfs k0` | 5 passed (K01–K05) |
| `pr13_crash_rustfs k05` | 10/10 passed |

Logs: `target/pr15g-b/rustfs/`.

## Remaining blockers

- Hosted exact-final-HEAD `rust`, `msrv` and `rustfs` CI must be observed as
  successful; local execution is not a substitute.
- Independent human review/approval (GB-A10) is not started.
- The shared branch is not merged; no merge is claimed.
- Performance is qualified for this host/one campaign only; no Tantivy parity,
  reopen speed, index-size or OS-cold claim is made.
