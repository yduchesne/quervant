# PR 15I-B — execution status (partial)

**Status:** `15IB_BLOCKED_DECISION_REQUIRED` — P0 and P1 are complete and
qualified; P2 (production STORED v2) and later phases are **not started** in
this execution window. No production STORED code, dependency, format, candidate
or campaign was created, so no PR 15I-B performance claim exists.

This is a scope/continuation decision for the maintainer, not a correctness
failure of the completed phases.

## Phase status

| Phase | Status | Evidence |
|---|---|---|
| P0 PR 15I-A verifier requalification | **PASS** | `p0-15ia-qualification.md`; receipt `verification-15ib-p0-01.json`; seal unchanged `af7f6c1a…b2f`; 87 Python tests |
| P1 historical 15G-E attribution | **PASS** (`HISTORICAL_RARE_REGRESSION_ATTRIBUTED`, H-E3) | `historical-15g-e-attribution.md`; `target/pr15i-b/diagnose/run-01/diagnosis.json` |
| P1 offline codec pre-study | **PASS** (both codecs eligible) | `codec-pre-study.md`; `target/pr15i-b/lab/codec-n{10000,100000}/codec_lab.json` |
| P2 STORED v2 format/implementation | NOT STARTED | — |
| P3 candidate arms/campaign | NOT STARTED | — |
| P4 correctness/fault/RustFS acceptance | NOT STARTED | — |
| P5 final QA/review | NOT STARTED | — |

## Identities

| Item | Value |
|---|---|
| BASE (= reviewed main) | `691b6993d15f568617f9302cca0a4677bc50df3e` |
| Branch | `dev/pr15i-b-stored-blocks` |
| P0_SHA | `0cf7dec58c3a5412c1ad750b487e9fa00dfc46bb` |
| P1_SHA (tooling/pres-study) | `178c000b7e0bbc44b9f4e439755a36aadbb7ec7f` |
| B_LZ4_SHA / B_ZSTD_SHA / B_FINAL_SHA | NOT CREATED |
| P0 original seal before/after | `af7f6c1a85515dbc58c8c31a3b1b7f68dd6a9246d33747a529952b941b852b2f` (identical) |
| P0 receipt | `target/pr15i-a/reviews/verification-15ib-p0-01.json` |

Production diff `db9007f..HEAD` for `crates/quervant-core/src`,
`crates/quervant-core/Cargo.toml`, `Cargo.lock`, `.github/workflows/ci.yml` is
empty: PR 15I-A's measured production remains untouched.

## P0 results

- All 12 original rebuild directories (`A/B × 10K/100K × run1..3`) are now
  mandatory, lstat-checked, and independently re-measured; all four groups are
  `INDEPENDENTLY_RE_VERIFIED`.
- Raw directory inventory is exact and symlink-safe (`slots`, 16 slot dirs,
  16 contention dirs); unexpected/symlinked dirs are rejected.
- Pre-fix reproduction proves the old verifier wrongly qualified a campaign with
  `A/100000-run2` removed and one with `raw/unexpected` symlinked outside.
- FT-A55–A60 added; total Python tests **87 passed**.
- Original `paired-04` untouched; independent verifier still `qualified=True`
  with `raw=20 aux=32 lanes=144 samples=2880`.

## P1 results

- Historical A `ca065a2…`, E `62d35c2…` built read-only and diagnosed.
- Source mechanism: `stored_docs_selected` re-invokes
  `persisted_directory_view` → `inspect_offset_directory` on every certified
  query; the loop reads `doc_count+1` boundaries (10,001 / 100,001).
- Paired 4-block ABBA timing: 10K rare E/A **3.88**, 100K rare **6.69**,
  100K medium **1.04** (historical 3.12–3.87 and 6.43–6.86 reproduced).
- Codec lab: exact v1 block reconstruction `PASS`; 100K STORED section baseline
  9,662,513 B → LZ4 1,661,455 B (0.172), Zstd1 628,025 B (0.065); both lossless
  and eligible for production candidates. Offline numbers only.

## Smallest decision required

Authorize a continuation window to implement P2–P5 (STORED v2 format,
certificate/budget reader, LZ4 and Zstd candidate branches, full source-locked
campaign, correctness/RustFS suite and final QA). No gate is waived and no
threshold is changed by this status.

## External status

- `HOSTED_CI_PENDING`: branch has no upstream and was not pushed.
- `INDEPENDENT_REVIEW_PENDING`.
- `NOT_MERGED`, `NOT_PUSHED`.
