# PR 15I-C fixup — correctness and QA record

Status: **F0 rejected**. The `FX-U*`/`FX-I*`/`FX-F*` suites target the F1
dispatcher/refactor that was never created, so they are **NOT EXECUTED** and no
result is claimed for them. This document records what was actually run.

## 1. Rust source and existing suites

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS (control commit and final tip) |
| `cargo +1.85.0 check --locked -p quervant-core` | PASS |
| `cargo test --locked -p quervant-core --lib search::unified` | 52 passed (control commit; includes PR15E/PR15H-B suites) |
| `cargo test --locked -p quervant-core --lib search::unified::phase4_tests` | 8 passed |
| `cargo test --locked -p quervant-core --lib search::unified::b_tests` | 6 passed |
| `cargo test --locked -p quervant-core --lib search::execute::budget_tests` | 40 passed |

The final workspace QA at the settled rollback tip is recorded in
`fixup-execution-status.md` §4.

## 2. New Python suites (tooling, not feature tests)

| Command | Result |
|---|---|
| `python3 -m unittest discover -s benchmarks/pr15i_c -p 'test_*.py'` | 90 tests OK |
| `python3 -m unittest benchmarks.pr15i_c.test_layout_diag` | 14 tests OK |
| `python3 -m unittest benchmarks.pr15i_c.test_verify_layout_diag` | 29 tests OK |
| `python3 -m unittest benchmarks.pr15i_c.test_codegen_capture` | 6 tests OK |

The 29-case verifier suite covers the prescribed `FX-V*` matrix: inventory and
symlink rejection, seal tampering with and without re-sealing, forged summaries,
schedule/topology drift, wrong warmup/sample counts, unclear contention,
exact/one-over gate thresholds, inverted ratio direction, controller/verifier
disagreement, non-positive or non-integer samples, source/body-hash drift,
non-descendant commits, missing rebuild directories, read-only repeat
verification and refusal to overwrite a receipt.

## 3. Operator-level tests

`FX-U01..FX-U36`, `FX-I01..FX-I24` and `FX-F01..FX-F16` were **not executed**.
They assert properties of the separated dispatcher and `collect_exact_term_physical`
method, neither of which exists in this fixup because the generic boundary was
rejected. The earlier `c15i_tests`, `c15i_physical_tests` and
`tests/pr15i_c_physical.rs` from candidate `395e05c…` remain only as historical
records of the rejected candidate and are not present in the tree.

## 4. Real boundaries

| Gate | Status | Reason |
|---|---|---|
| Local `FsDirectory`/PIT/compaction/deletion paths | not exercised by this fixup | baseline production source is unmodified; the existing PR06/PR09/PR13/PR14/PR15 suites run in the final QA |
| Genuine pinned RustFS (`rustfs/rustfs@sha256:1803faef…`) and PR13 proxy faults | **`REAL_RUSTFS_BLOCKED`** | no container runtime on the host (`docker`/`podman` absent); no fake was substituted (`FX-D72`) |
| Hosted CI | `HOSTED_CI_PENDING` | not run by this agent |

Because F0 failed, no positive acceptance was reachable, so the real-service gate
was not the limiting factor; it remains unresolved for any future attempt.

## 5. Pre-existing failures (`FX-D17`)

`python3 -m unittest discover -s benchmarks/pr15i_a` → 87 tests,
`FAILED (failures=1, errors=3)`, all in `test_verify.RealCampaignTests`
(`test_ft_a49/a50/a51/a53`). Identical before and after this fixup and reproduced
on a clean merged-base checkout; these are source-bound historical tests. They
were not edited, weakened or counted as passing evidence.
