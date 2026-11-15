# PR 15I-D3-C — real RustFS I11 evidence

Status: **PASS** for the two existing real S3-backed tests.

- Runtime: podman 4.9.3 with `podman-compose` 1.0.6.
- Topology: `tests/rustfs/compose.yaml`, project `quervant-d3c-rustfs-session`,
  pinned image `rustfs/rustfs:1.0.1@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`.
- Endpoint: local agent-owned container, readiness checked via `/health`.
- Credentials: session-local defaults; no secrets committed.
- Container/volume were confirmed absent before start (no takeover), and the
  EXIT trap removed the agent-owned project and volume.

Executed:

```text
cargo test -p quervant-core --features s3 --test m1_batches -- --ignored
  m1_v04_real_rustfs_batch_replay_and_generation_consistency ... ok
  1 passed; 0 failed; 0 ignored

cargo test -p quervant-core --features s3 --test m2_patches -- --ignored
  m2_v04_real_rustfs_patch_reopen_replay ... ok
  1 passed; 0 failed; 0 ignored
```

This is the separate I11 backend gate; it is not replaced by a local filesystem
fake and is not part of `pr15i_d3_c.rs`.
