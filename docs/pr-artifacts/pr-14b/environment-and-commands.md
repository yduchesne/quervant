# PR 14B — environment and reproducible commands

**Status:** real-RustFS qualification executed locally. CI, independent review and
human acceptance remain open. No claim of PR 14 acceptance (owned by 14C).

## Recorded state

| Item | Value |
|---|---|
| Base `main` (verified via `git fetch origin`) | `7a860590fe5ba4fde3cfeee235e8a33751019522` |
| Work branch | `dev/pr14b-real-rustfs-qualification` |
| Code/test commit under test | `556621a5414673d3355e57fb2b2f4fb09135c54b` |
| Previous merge | PR #60 (`dev/pr14a-pit-public-cursor`) merged into `main` |
| Working tree before edits | clean |
| Host OS | Ubuntu 24.04.5 LTS, Linux 6.18.33.2-microsoft-standard-WSL2, x86-64 |
| Stable toolchain | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1` |
| MSRV toolchain | `rustc 1.85.0 (4d91de4e4 2025-02-17)` |
| Coverage tool | `cargo-llvm-cov 0.9.1` |
| Container runtime | `podman 4.9.3` (rootless) |
| Evidence timestamps (UTC) | 2026-10-24T16:09Z (provider start) to 2026-10-24T16:44Z |

## Pinned real provider

| Item | Value |
|---|---|
| Image | `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` |
| Tag | `rustfs/rustfs:1.0.1` |
| Local image ID | `f6b22807f10db2aee80b8a9ed1e36bd12c2fba25ac2d98dc3b0332a23f1a5c4d` |
| Container | `quervant-pr14b-rustfs` (podman, rootless, `no-new-privileges:true`) |
| Endpoint | `http://127.0.0.1:9000` (console `:9001`) |
| Health | `{"status":"ok","service":"rustfs-endpoint","version":"1.0.1"}` |
| Bucket | `quervant-pr14b` (dedicated; created by the harness via `create_bucket_if_absent`) |
| Credentials | Disposable local test values `quervanttest` / `quervantsecret` from the container environment; not committed and not printed in evidence |

Start command (exact, secrets are the disposable harness values):

```sh
podman run -d --name quervant-pr14b-rustfs \
  --security-opt no-new-privileges:true \
  -p 127.0.0.1:9000:9000 -p 127.0.0.1:9001:9001 \
  -e RUSTFS_VOLUMES=/data/rustfs0 -e RUSTFS_ADDRESS=0.0.0.0:9000 \
  -e RUSTFS_CONSOLE_ADDRESS=0.0.0.0:9001 -e RUSTFS_CONSOLE_ENABLE=true \
  -e RUSTFS_ACCESS_KEY=quervanttest -e RUSTFS_SECRET_KEY=quervantsecret \
  -e RUSTFS_OBS_LOGGER_LEVEL=warn \
  docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
# bounded readiness probe, never a fixed sleep:
for i in $(seq 1 60); do curl -fsS http://127.0.0.1:9000/health >/dev/null && break; sleep 1; done
```

No public AWS endpoint, production bucket or production credential was used.
Every test owns a unique remote prefix (`pr14-p4/<tag>/<pid>/<nanos>/case` or the
fault-suite equivalent) and removes only its own workspace. Remote objects are
left for post-run investigation and are never deleted bucket-wide.

## Environment variables (non-secret)

```sh
export QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000
export QUERVANT_RUSTFS_REGION=us-east-1
export QUERVANT_RUSTFS_BUCKET=quervant-pr14b
# QUERVANT_RUSTFS_ACCESS_KEY / QUERVANT_RUSTFS_SECRET_KEY from the secure local environment
```

## Commands actually executed

### Case inventory

```sh
cargo test -p quervant-core --all-features --test pr14_storage_vertical -- --list
```

Baseline inventory (before edits): 3 non-ignored local cases, 8 ignored real
provider cases and the `p4_child_bootstrap` child entrypoint. After edits:
5 non-ignored local cases, 11 ignored real provider cases and the child
entrypoint.

### Local vertical

```sh
cargo test -p quervant-core --all-features --test pr14_storage_vertical -- --nocapture --test-threads=1
```

### Each provider case individually (fully-qualified path, serial)

```sh
cargo test -p quervant-core --all-features --test pr14_storage_vertical \
  'real::<case>' -- --ignored --exact --nocapture --test-threads=1
```

Cases executed individually: `r02_r04_r06_real_cold_compound_equivalence`,
`r08_r09_r15_real_batch_aggregation_and_cursor`,
`r05_real_mutation_old_and_new_snapshot`,
`r10_r11_real_remote_budget_exact_and_one_over`,
`r12_empty_cache_no_writer_state`, `r01_separate_process_cold_bootstrap`,
`r03_wrong_generation_is_not_substituted`,
`r13_r14_warm_evict_and_pinned_reader`,
`b02_real_mixed_boolean_and_relevance_order`,
`b06_b07_real_pinned_batch_search_after`, `b18_real_historical_json_remote`.
`p4_child_bootstrap` was never invoked as a standalone acceptance test; the
`r01` parent spawns it with `QUERVANT_PR14_P4_CHILD=1`.

### Real-provider fault suites

```sh
cargo test -p quervant-core --all-features --test pr14_storage_faults \
  '<case>' -- --ignored --exact --nocapture --test-threads=1
cargo test -p quervant-core --all-features --test pr13_remote_proxy \
  '<case>' -- --ignored --exact --nocapture --test-threads=1
cargo test -p quervant-core --all-features --test pr13_crash_rustfs \
  '<case>' -- --ignored --exact --nocapture --test-threads=1
cargo test -p quervant-objectstore --features s3 --test pr13_s3_rustfs -- --ignored --test-threads=1
cargo test -p quervant-objectstore --features s3 --test pr13_proxy_rustfs -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr13_oracle -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr13_oracle_geo -- --ignored --test-threads=1
```

### Workspace gates

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test --workspace --all-targets --all-features
cargo +1.85.0 test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo doc --workspace --all-features --no-deps
cargo bench --workspace --no-run
bash benchmarks/scripts/test-scripts.sh
git diff --check
```

Raw stdout/stderr for every invocation is retained under `/tmp/pr14b-logs/`
(`provider/`, `faults/`, `gate-*.log`) for this run; the commands above are the
reproduction recipe. Log paths are local to the run host and are not committed.

## Isolation and cleanup

- Each provider test uses a unique scoped prefix and a unique temporary
  workspace; tests only remove their own workspace directory.
- `RemoteIndex::open_existing` is always used for cold reads; the writer's local
  state is deleted before the cold cases.
- The `r01` child process receives only the remote prefix, workspace and
  provider configuration, and runs the same deterministic oracle.
- No production endpoint, shared bucket, or committed object is mutated by the
  fault tests. The fault proxy is a test-only HTTP tunnel in front of the real
  service.
