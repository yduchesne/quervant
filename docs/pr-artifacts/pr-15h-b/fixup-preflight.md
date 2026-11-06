# PR 15H-B fixups — preflight

**Branch:** `dev/pr15h-a-linear-term-candidates` (required literal, continued in place)
**Starting HEAD:** `f06f8280899217a0e2df9cf54e78f4f7ebfbbd34`
**Accepted B candidate (ancestor):** `ae7e416a7d4d8a0ce179b64a15cafc2cb104f85e`
**Pre-B baseline A:** `6e47eed3f35a5fad8db6dab24c66f386567e95c0`
**Original B tooling:** `79593314aa0525a1bb7d5f30c900a70e890e728a`
**Inspected `main`:** `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078`

## 1. Branch and cleanliness

- `git branch --show-current` = `dev/pr15h-a-linear-term-candidates`.
- `git rev-parse HEAD` = `f06f828…` (matches the plan's pinned authoring HEAD).
- `git status --porcelain` empty.
- `git merge-base --is-ancestor ae7e416… HEAD` exit 0.
- No new branch/worktree is required.

## 2. Blob identities at preflight

| Path | Blob |
|---|---|
| `search/unified.rs` | `5492645cda500d841d5b8f00947e2576593507af` |
| `search/typed_compare.rs` | `0e72728ad37b7f0d35f91a8b7866dd65f1a16bcc` |
| `segment/column.rs` | `263d40df46f49a546cde88141c01e0e8b6142e17` |
| `search/execute.rs` | `5d0ac48132de6ea1220bdd884f81ca9f260ab3ba` |
| `search/score.rs` | `2921afc52ad0f343498e6c69814b38016205ea2d` |
| `segment/format.rs` | `a0f06363dd8ad03a74d741c340792974fb7cd146` |
| `segment/reader.rs` | `e4dddcaf6c0e7da8d3ec9e70a432363754f45e4e` |
| `Cargo.toml` | `4be845588f336b9487519f0ed34c45e4ad42d388` |
| `Cargo.lock` | `732b2b9e1a5b9fe044daa367bfcf88f654682b70` |
| `.github/workflows/ci.yml` | `374583d3762b222135d6b8fa30921dbdcf09a017` |

`column.rs`, `execute.rs`, `score.rs`, `format.rs`, `reader.rs`, `Cargo.*` and CI
must remain byte-identical. `typed_compare.rs` may change only by the prescribed
`#[cfg(test)]` constructor; `unified.rs` only inside `#[cfg(test)] mod b_tests`.

## 3. Source anchors (verified)

| Symbol | Location |
|---|---|
| `resolve_tree` | `benchmarks/pr15h_b/run.py:157` |
| `derive_paired` | `benchmarks/pr15h_b/run.py:479` |
| `_source_scope_ok` | `benchmarks/pr15h_b/run.py:636` |
| `run_paired` | `benchmarks/pr15h_b/run.py:745` |
| `verify_campaign` | `benchmarks/pr15h_b/run.py:946` |
| `A_ALLOWED_CHANGED_PREFIXES` | `benchmarks/pr15h_b/run.py:85-88` (typo confirmed) |
| `ColumnAccess::open` / `keyword_sort_view` | `search/typed_compare.rs` |
| `consider_borrowed_keyword_candidate` | `search/unified.rs` |
| `b_tests` | `#[cfg(test)] mod b_tests` at end of `search/unified.rs` |

## 4. Pre-edit baseline tests

| Command | Result |
|---|---|
| `python3 -m unittest discover -s benchmarks/pr15h_b -p 'test_*.py'` | PASS — 21 tests |
| `cargo test -p quervant-core --lib search::unified::b_tests` | PASS — 5 |
| `cargo test -p quervant-core --test pr15h_b_sort_materialization` | PASS — 6 |

## 5. Historical B evidence (read-only, original tooling `7959331`)

Detached tooling worktree at `7959331` is clean. Both `--verify-only` invocations
reproduce byte-for-byte:

| Evidence | Result | Seal SHA-256 |
|---|---|---|
| Baseline `target/pr15h-b/baseline-01` | PASS | `28996cecc0560dbb19b938fd8b15aefd077ee20216884f48ea47bb551beea5d6` |
| Paired `target/pr15h-b/paired-01` | PASS | `be76e32ba422cd4bc456045fa13fee50ec3a7ec4312f1b555e8e7c015f639043` |
| Paired sanitized performance | byte-identical | `f0d5d083afcb0b913e3316df45b9d5e3ab6d3859e8272c107b4093ac2ad0d46b` |

No historical file is modified and no new timed campaign is required (production
code unchanged).

## 6. Invariant map (BF-I01–BF-I18)

| Invariant | Evidence plan |
|---|---|
| BF-I01 | `BF-T01/T02/T03`, `BF-T07` |
| BF-I02 | `BF-T04/T05/T06` |
| BF-I03 | `BF-T07`, historical `--verify-only` |
| BF-I04 | §5 historical seal verification |
| BF-I05 | `BF-T08/T09` |
| BF-I06 | `BF-T10/T11/T12` |
| BF-I07 | `BF-U01` |
| BF-I08 | `BF-U02` |
| BF-I09 | `BF-U02`, `BF-U06` |
| BF-I10 | `BF-U03` |
| BF-I11 | `BF-U04` + source-scope audit |
| BF-I12 | blob equality audit |
| BF-I13 | §5 + no writes to historical dirs |
| BF-I14 | `BF-T06/T13` + unchanged constants |
| BF-I15 | stable/MSRV/coverage/RustFS QA |
| BF-I16 | `CI_PENDING` |
| BF-I17 | test-only fixups; no production behavior change |
| BF-I18 | additive commit on the same branch |

## 7. Counterexamples challenged

1. Paired tooling SHA differs from the sealed baseline → must reject **before**
   `os.makedirs`/adapter build; `derive_paired` and `verify` also reject.
2. Missing/null/uppercase/short tooling values → typed `X_TOOLING_SHA`, never a
   `KeyError` or an accepted report.
3. A malformed **losing** keyword payload after a full K+1 heap → exact
   `SearchError::Segment(SegmentError::InvalidUtf8 { context: "keyword" })`,
   heap/charges unchanged; the owned decoder produces the same error.
4. Zero owned-tuple materializations for the intact losing candidate.
5. The old typo prefix and unrelated docs/code paths are rejected; the actual
   `docs/pr-artifacts/pr-15h-b/` prefix is accepted.
6. No historical A/A2/A3/B seal, manifest or sanitized report is overwritten.

No approved need to change release Rust. If the test-only seam cannot be
implemented as prescribed, the corruption test is a HARD STOP.
