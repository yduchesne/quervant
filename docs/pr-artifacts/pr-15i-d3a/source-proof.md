# PR 15I-D3-A source proof

Status: `VERIFIED` (scratch-only derivative, not committed).

## Materialization

```sh
python3 benchmarks/pr15i_d3a/patch_source.py \
  --checkout-root <clean scratch worktree> \
  --derivation-out target/pr15i-d3a/derivation/derivation.json
```

Observed:

| Item | Value |
|---|---|
| Derivative fingerprint SHA-256 | `62e587715a9a2dd24281a99f9e05e378683dda4e82d9eac0837a4a140801fb60` |
| Allowed files | 6 (five modified, one new) |
| `unified.rs` insertions | 40 |
| `execute.rs` insertions | 25 |
| `search/mod.rs` insertions | 1 |
| `Cargo.toml` insertions | 1 |
| adapter `main.rs` insertions | 2 |
| `score.rs` | unchanged (not in the allowlist) |
| Default features | unchanged (`default = ["stored-lz4"]`) |
| Probe feature | `pr15id3a-probe`, non-default, scratch only |

The six derivative paths are exactly:

```text
crates/quervant-core/src/search/unified.rs
crates/quervant-core/src/search/execute.rs
crates/quervant-core/src/search/mod.rs
crates/quervant-core/src/search/d3a_probe.rs   (new)
crates/quervant-core/Cargo.toml
benchmarks/pr15d/adapters/quervant/src/main.rs
```

## Independent reverse proof

```sh
python3 benchmarks/pr15i_d3a/source_proof.py \
  --checkout-root <pristine BASE worktree> \
  --instrumented-root <scratch worktree> \
  --out target/pr15i-d3a/derivation/source-proof.json
```

Observed:

```text
status=VERIFIED
derivative_fingerprint_sha256=62e587715a9a2dd24281a99f9e05e378683dda4e82d9eac0837a4a140801fb60
```

The proof independently rebuilds the derivative from its own copied literal
inventory, applies the same `rustfmt`, compares byte-for-byte, rejects any
replacement/deletion/public item/`#[inline]`/extra path, and reverse-applies
every inserted byte to recover exact BASE. `query_probe` appears only in the
adapter. `match_insert_sample(matched.len())` appears exactly twice (postings
and live-bitmap branches).

## Recorder schema

- 25 stage accumulators in the frozen order from `protocol_v1.json`.
- 15 counter accumulators in the frozen order.
- Up to 32 `[scored_len, first_samples, steady_samples, match_insert_samples]`
  descriptors; a 33rd sets `segments_unsupported` instead of truncating.
- Two fixed `[[u64; 8]; 2]` FIRST/STEADY rows (parent plus seven children) and
  two stratum counts.
- No per-query `Vec` is allocated by the probe; no locks, global state, hot-path
  I/O or per-hit JSON. `take()` runs only after `engine_ns` has stopped.
