# `pr07_pre_norms_v1` — pre-`FieldNorms` committed local index

This directory is a **complete, frozen committed local index** produced by the
historical (pre-Amendment-05) production `IndexWriter` at commit
`a8adf374ae9f12908cfc0093c6cde032e53d6c85` ("PR 7 Amendment 05 preflight STOP").
It is test data, not an upgraded index: its segments have **neither the
`FieldNorms` section (`0x000E`) nor the `FEATURE_FIELD_NORMS` required feature**.
It is opened read-only by `crates/quervant-core/tests/pr07_compatibility.rs`.

The frozen `tests/fixtures/segment/golden.seg` is **not** touched by this fixture
and remains byte-for-byte unchanged.

## Provenance

| Field | Value |
|---|---|
| source commit | `a8adf374ae9f12908cfc0093c6cde032e53d6c85` (`a8adf37`) |
| generator | temporary `tests/pr07_generate_pre_norms_fixture.rs` in an isolated `a8adf37` worktree (never committed to `dev/lexical-postings`) |
| command | `PR07_FIXTURE_OUT=<dir> cargo test -p quervant-core --test pr07_generate_pre_norms_fixture -- --ignored` (from the `a8adf37` worktree) |
| schema | `crates/quervant-core/tests/common/mod.rs::pr07_schema` (unchanged `a8adf37`→HEAD); analyzers: `title` = `english`, `body` = `standard_folded` (Multi), `host` = keyword normalizer, `tags` = keyword (Multi), `raw` = Text, `n` = I64 (not indexed) |
| registry | `AnalyzerRegistry::builtin()` (`pr07_registry`) |
| generation | `1` |
| segments | `2` (one per flushed batch) |
| documents | `8` |
| deterministic | two independent generator runs produced byte-identical trees |

## Committed objects

Paths are relative to this directory (`index/...`). Segment file names equal
their content SHA-256 (content-addressed).

| object | length | SHA-256 |
|---|---:|---|
| `index/CURRENT` | 183 | `56067c79491360ac0db145387aa15dc6156bac3217c5261507e34954bcebea88` |
| `index/manifests/g-0000000000000001.manifest` | 880 | `276d8025485f0e2ce9fe02a4f9eb7536a433cd28b2ae911a0b5a382b160f91d1` |
| `index/segments/0508682861380e974057c33f1f702713f0d38643ebd55eee12edeeedb3b94b4e.seg` | 2354 | `0508682861380e974057c33f1f702713f0d38643ebd55eee12edeeedb3b94b4e` |
| `index/segments/da391e76a490450b371d3ea963dd06e4a58d269974d52d1460b26c0083faf558.seg` | 2064 | `da391e76a490450b371d3ea963dd06e4a58d269974d52d1460b26c0083faf558` |

## Logical corpus

Segment 1 (`05086828…`): `d1`–`d4`; segment 2 (`da391e76…`): `d5`–`d8`.

| key | title | body values | `n` |
|---|---|---|---|
| `d1` | `rust systems search` | `["rust is fast", "memory safety"]` | 1 |
| `d2` | `rust language guide` | `["rust and cargo"]` | 2 |
| `d3` | `python scripting` | *(body absent)* | 3 |
| `d4` | `java virtual machine` | `["java rust"]` | 4 |
| `d5` | `rust basics` | `["introductory rust"]` | 5 |
| `d6` | `rust manual` | `["advanced rust"]` | 6 |
| `d7` | `search engines` | `["search and rust"]` | 7 |
| `d8` | *(empty title)* | `["empty title doc"]` | 8 |

The corpus deliberately includes a repeated query term (`rust`), a missing
scoring field (`d3` body), an empty scoring field (`d8` title), distinct field
lengths, a term shared across both segments/fields, and an exact score tie
(`d5`/`d6`, and `d1`/`d2`).

## Reproducing

The fixture generator lives only in a throwaway worktree. To reproduce:

```sh
git worktree add -f /tmp/quervant-prenorms a8adf37
# recreate tests/pr07_generate_pre_norms_fixture.rs from the recorded corpus above
cd /tmp/quervant-prenorms
PR07_FIXTURE_OUT=/tmp/pr07_out cargo test -p quervant-core \
  --test pr07_generate_pre_norms_fixture -- --ignored
# compare SHA-256 of index/CURRENT, the manifest and both segments to the table above
```

Normal tests require only this checked-in directory; they never check out
historical git commits.
