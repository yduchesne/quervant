# PR 15H-E — exact safe rollback

The rejected candidate changed exactly the five allowed production files plus
the E regression tests. The rollback restored `crates/quervant-core/src` and the
touched existing tests byte-for-byte from the pre-E baseline, removed the
v2-only integration test, and retained the E controller, helper tests, docs and
sealed evidence.

## Identity checks

- `git diff --quiet eb6ed9170308965987a35211d227431535a41ecb HEAD -- crates/quervant-core/src`
  exits 0.
- `git diff --quiet eb6ed9170308965987a35211d227431535a41ecb HEAD -- crates/quervant-core/src`
  exits 0. The only later `crates/quervant-core` difference is rustfmt on the
  retained control-fixture test (`6fce44b`); production source is untouched.
- `cargo test --workspace --all-targets` passes on the rollback tree.
- The v2-only feature, feature id and payload version no longer exist in
  production source.

## Retained

- `benchmarks/pr15h_e/{run.py,test_run.py,README.md}`.
- `crates/quervant-core/tests/pr15h_e_{control_fixture,open_timing}.rs`.
- `target/pr15h-e/campaigns/baseline-01` and `paired-01` (sealed, read-only).
- All `docs/pr-artifacts/pr-15h-e/` documents.

The production rollback commit is `8d722ad0c0cff6b947fcdc762bb2ccaacdfcff0b`;
the final code HEAD after formatting the retained fixture is
`6fce44b2f393e68ae73090f3843a2c201f7dd3a1`.
