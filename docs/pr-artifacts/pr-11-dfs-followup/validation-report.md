# PR 11 Follow-up B1 — Validation report

**State validated:** `fix/pr11-json-dfs-frontier` working tree on base
`026f6e045b6cc0956210e8ea941a46d4a0906969` (PR #31 merge). Recorded SHA at branch creation.
**Toolchains:** stable `rustc 1.98.1 (48a229cea 2026-09-01)`; MSRV `cargo 1.85.0 (d73d2caf9 2024-12-31)`.
**Topology:** local only. Integration tests use `MemoryDirectory` plus the real
`IndexWriter → ReaderSnapshot → TypedSearcher` and the real builder/compaction paths. No RustFS,
network, container or distributed services are involved or claimed.

## Final commands

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (stable) | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --lib b1_` | PASS — 10 passed, 0 failed |
| `cargo test -p quervant-core --test pr11_json_paths` | PASS — 10 passed |
| `cargo test -p quervant-core --test pr11_json_mutations` | PASS — 7 passed |
| `cargo test -p quervant-core --test pr11_json_corruption` | PASS — 8 passed, 1 ignored |
| `cargo test -p quervant-core --test pr11_json_properties` | PASS — 4 passed |
| `cargo test --workspace --all-targets` (stable) | PASS — 78 suites, 0 failed |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 0 failed |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — TOTAL **91.78% line**, 87.97% branch, 91.39% function |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench -p quervant-core --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed |
| `git diff --check` | PASS — clean |

## Red gate (captured before production changes)

`cargo test -p quervant-core --lib b1_wide -- --nocapture` against unmodified `main`:

```
frontier high-water 10000   (wide object) — FAILED
frontier high-water 10000   (wide array)  — FAILED
```

After the cursor-stack fix the same tests assert `max_frames <= 1` and PASS.

## Feature evidence

- Depth-bounded cursor frames: `b1_wide_object_frontier_is_bounded`, `b1_wide_array_frontier_is_bounded`.
- Exact occurrence identity vs independent reference: `b1_nested_mixed_matches_manual_expected`,
  `b1_property_vs_recursive_reference` (250 seeded trees).
- Preserved limits: `b1_depth_boundary_at_and_over`, `b1_member_bytes_and_array_boundaries`.
- Frontier preflight: `b1_stack_capacity_preflight`, `b1_wide_shallow_survives_modest_frontier_budget`.
- Real boundaries: builder/search `b1_wide_shallow_builder_search`, compaction
  `b1_compact_wide_indexed_only_json`, legacy fallback `b1_legacy_source_fallback_wide_field`.
- Frozen wire: `pr11_json_corruption::t13_json_paths_golden_fixture` (SHA-256 `0528a62c…a02f`) plus
  the unchanged existing PR 11 suites.

## Skipped / blocked gates

None locally. GitHub Actions for the pushed corrective branch/PR is a separate step; it is not
claimed here. No remote RustFS or distributed acceptance is applicable to this local extractor fix.

## Unresolved failures

None.

## Residual risks

`SegmentLimits` is not a process-wide RSS limiter; retained occurrence vectors, cloned paths,
stored-source decoding and builder staging remain governed by their existing budgets.
