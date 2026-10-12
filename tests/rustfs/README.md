# RustFS harness foundation (PR 3)

This directory holds the **opt-in, reproducible RustFS harness foundation**
introduced by PR 3. It is **not** a production S3/RustFS adapter test and does
not establish S3 compatibility.

## Status and ownership

- **PR 3 (this harness):** version-pinned topology, disposable credentials,
  isolated prefix/bucket conventions, start/stop instructions and deterministic
  cleanup. Running it without a production adapter reports **SKIP**.
- **PR 13 (production adapter):** the production S3-compatible adapter, real
  `put`/`head`/`get`, exact ranged reads, timeout/corruption handling, remote
  cold reader bootstrap and mandatory real RustFS integration/CI evidence.

A fake-object-store test is **not** RustFS conformance. Do not label a
scaffold-only run as a passing RustFS integration test.

## Pinned image

| Field | Value |
|---|---|
| Image | `rustfs/rustfs:1.0.1` |
| Digest | `sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` |
| Verified | Docker Hub tag metadata, 2026-10-12 |
| S3 API | `http://127.0.0.1:9000` |
| Console | `http://127.0.0.1:9001` |

Update the tag/digest only as an explicit, reviewed change. Rust's
provider-neutral `ObjectStore` contract deliberately assumes **no** provider
guarantee (conditional writes, listing consistency, read-after-write) until the
production adapter measures it.

## Running

```sh
# Without a production adapter (PR 3): prints SKIP and exits 0.
tests/rustfs/run.sh

# With a production adapter (PR 13 and later):
TRAWLER_PRODUCTION_S3_ADAPTER=1 tests/rustfs/run.sh
```

Environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `TRAWLER_PRODUCTION_S3_ADAPTER` | `1` enables real adapter tests | `0` (SKIP) |
| `RUSTFS_PORT` | S3 API port | `9000` |
| `RUSTFS_CONSOLE_PORT` | console port | `9001` |
| `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` | disposable test credentials | test-only defaults |
| `RUSTFS_COMPOSE_PROJECT` | compose project / name prefix | `trawler-rustfs-pr3` |

The script registers a `trap` that runs `compose down -v --remove-orphans`, so
the container and its volume are removed even on failure.

## Isolation and cleanup

- Always use a unique bucket/prefix per run (for example
  `trawler-<pr>-<random>`); never reuse committed object keys.
- Credentials are disposable and scoped to the ephemeral local volume only.
- Do **not** point the harness at a shared bucket or long-lived credentials.

## Requirements

- `podman` or `docker` with a compose provider.
- Reachable image registry for the first pull (the image is then cached).
- Network access to `127.0.0.1:9000` / `127.0.0.1:9001`.

If the container runtime or image is unavailable, the harness cannot start;
record **BLOCKED — ENVIRONMENT**, not PASS. PR 3 does not make container startup
a completion gate.
