# PR 13 — pre-implementation correctness gate

**Baseline commit:** `653b412e0e7df8efe18602479b661629427fab57` (branch `dev/rust-fs`, parent
`main` as of 2026-10-15).

## Scope inspection (Phase 0)

The fresh baseline was inspected before any change: the provider-neutral
`quervant-objectstore` contract, `FakeObjectStore`, the local `Directory`
(`FsDirectory`, `MemoryDirectory`), the bounded verified `SegmentCache`
(`crates/quervant-core/src/storage/cache.rs`), the local index lifecycle
(`index/{mod,current,writer,support,snapshot,limits}.rs`) and the CI workflow
(`.github/workflows/ci.yml`). The baseline workspace built, formatted, linted and
tested clean on stable and Rust 1.85 before the change (see
`validation-report.md`).

No pre-existing conflicting remote mechanism was found: `quervant-objectstore`
explicitly deferred the production S3/RustFS adapter to PR 13, and
`quervant-core` had no remote module.

## SDK selection (must compile on Rust 1.85)

| Component | Version | Notes |
|---|---|---|
| `aws-sdk-s3` | `1.96.0` (`default-features = false`, `rt-tokio`) | `rust-version = "1.85.0"`; latest (1.152) requires Rust 1.94 and was rejected |
| `aws-smithy-http-client` | `1.1.4` (`default-client`) | plain-HTTP connector; no TLS provider, so no `aws-lc`/C toolchain |
| `aws-credential-types` | `1.2.10` | static credentials, no IMDS |
| `aws-smithy-runtime-api` / `aws-smithy-types` | `1.9.2` / `1.3.4` | `HttpResponse` status, `ByteStream`, `TimeoutConfig` |

The AWS SDK retry layer is disabled (`RetryConfig::disabled()`); retry policy is
owned by the caller, per the provider-neutral contract. No S3 signature code is
implemented in this repository.

## Provider probe (real pinned RustFS)

RustFS image, pinned by manifest digest:

```
docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
```

Container (podman, rootless), ephemeral writable layer, explicit test
credentials, no public AWS:

```sh
podman run -d --name quervant-rustfs -p 9000:9000 \
  -e RUSTFS_ACCESS_KEY=quervanttest -e RUSTFS_SECRET_KEY=quervantsecret \
  docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
```

Health: `GET /health` → `200`, `GET /minio/health/live` → `200`.

Command:

```sh
QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 QUERVANT_RUSTFS_REGION=us-east-1 \
QUERVANT_RUSTFS_BUCKET=quervant-pr13 QUERVANT_RUSTFS_ACCESS_KEY=quervanttest \
QUERVANT_RUSTFS_SECRET_KEY=quervantsecret \
cargo test -p quervant-objectstore --features s3 --test pr13_s3_rustfs -- --ignored --test-threads=1
```

Result: **8 passed, 0 failed**.

| Probe | Guarantee | Result |
|---|---|---|
| `s01_concurrent_if_absent_single_winner` | Two concurrent `If-None-Match: *` PUTs to a fresh key: exactly one wins; the loser gets a typed conflict | PASS |
| `s02_concurrent_if_match_single_winner` | Two concurrent `If-Match` replacements against the same ETag: exactly one wins; the loser gets `PreconditionFailed` | PASS |
| `s03_read_after_write_exact_bytes` | Immediate GET returns exact new bytes; HEAD length agrees | PASS |
| `s04_exact_ranged_read` | Ranged GET returns exact offsets and lengths | PASS |
| `s08_existing_identical_and_different` | Identical re-create → `AlreadyPresent`; different bytes → `Conflict` | PASS |
| `s09_rejects_oversize_before_network` | Oversize transfer rejected before network | PASS |
| `s10_unqualified_endpoint_fails_closed` | Unqualified config advertises no capabilities and fails closed | PASS (unit + real) |
| `s11_delete_is_idempotent` | Deleting an absent object succeeds | PASS |

**Gate decision:** RustFS provides atomic create-if-absent, atomic conditional
replace, read-after-write and exact ranged reads. The implementation proceeded.

## Digest-versus-ETag contract (implemented)

S3 `If-Match` compares the ETag, not SHA-256. `PutPrecondition::IfMatch(digest)`
is implemented as HEAD-capture-ETag → bounded GET + independent SHA-256
verification → conditional PUT with the captured ETag. The conditional PUT is
the atomic guard; an ETag is never used as a content digest. `IfAbsent` issues a
real atomic conditional PUT; a 412 is resolved by reading the existing bytes.

## Final acceptance additions (verified, not retroactive)

- Transparent forwarding through the loopback proxy preserves AWS SigV4 and the
  `Host` header: H01 CAS/range/head all succeed through the proxy against real
  RustFS, so no signature verification was disabled or altered.
- `TimeRange` is confirmed half-open `[start, end)` by an independently
  enumerated oracle (`pr13_oracle`), not by treating Quervant output as truth.
- `In`/`Missing` JSON/typed operators are not implemented by the current
  searchers (`UnsupportedOperator`) and are out of PR 13 scope (PR 14).
