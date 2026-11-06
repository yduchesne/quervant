# PR 15G-D preflight

**Status:** preflight complete.
**Shared HEAD:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**Branch:** `dev/pr15g-a-retained-column-geometry`
**Arm A / D_BASE:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**Prior C rollback:** production search files equal `97d7ce1`; verified by
`git diff --quiet`.
**Umbrella PR:** #86

## Source facts

- C production streaming code is not active.
- B carryover tests `gc_br01a–e`, `gc_br02a/b` exist and pass.
- `single_term_postings_eligible` remains the P4 gate.
- Existing `collect_mixed` always opens columns/JSON and builds geo sort state
  before per-segment lexical evaluation.
- Existing `evaluate_lexical_with` has a one-term postings branch whose callback
  redundantly binary-searches the already decoded postings stream.
- Frozen C runner and failed-C reports remain immutable.

## Baseline

Focused tests on D_BASE pass. Toolchain: Rust 1.98.1 stable, MSRV 1.85.0,
Python 3.12.3, cargo-llvm-cov 0.9.1; native ext4/WSL2; pinned RustFS image
available locally.
