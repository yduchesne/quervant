# PR 15A — real RustFS provider validation

**Status:** `PASS (EXECUTED)` for all commands listed below on the pinned local
RustFS instance, plus the non-ignored fake-provider vertical. No performance
measurement, throughput claim or competitor comparison is made here. v0.1
remains `NOT RELEASED`.

## 1. Required topology

| Item | Observed value |
|---|---|
| Provider | real RustFS, S3-compatible |
| Image | `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` |
| Local image ID | `f6b22807f10db2aee80b8a9ed1e36bd12c2fba25ac2d98dc3b0332a23f1a5c4d` |
| Container | `quervant-pr14f-rustfs` (pre-existing, rootless Podman) |
| Endpoint | loopback `http://127.0.0.1:9000` |
| Health | `GET /health` → `status=ok`, `version=1.0.1` |
| Bucket | `quervant-pr15a` (created if absent; unique per-test key prefixes) |
| Test workspace | native Linux filesystem under `/tmp` (not `/mnt/c`); removed before cold reopen |
| Credentials | read from the running container environment; not recorded in any artifact/log |

Image digest and version match the approved PR 15A contract. No alternate image
was started.

## 2. New PR 15A provider vertical

| ID | Test | Topology | Result |
|---|---|---|---|
| A-R01/A-R02/A-R03 | `pr15a_provider::a15_r01_r02_r03_fake_provider_vertical_and_zero_get` | deterministic `FakeObjectStore`, cold reopen, static oracle, exact GET counter | **PASS (EXECUTED)** |
| A-R02 | `pr15a_provider::real::a15_r02_real_rustfs_pr15a_vertical` | real pinned RustFS, 2 segments, cold reopen, static oracle, `TransferStats` | **PASS (EXECUTED)** |

Commands:

```sh
cargo +stable test -p quervant-core --test pr15a_provider
cargo +stable test -p quervant-core --all-features --test pr15a_provider \
  -- --ignored --exact real::a15_r02_real_rustfs_pr15a_vertical \
  --nocapture --test-threads=1
```

Observed: `1 passed; 0 failed` for each command (`real::*` is filtered/ignored
in the default invocation).

The vertical asserts, identically on fake and real providers:

- `title=alpha` → `a0,a1,b0,b3` with total 4.
- `title=alpha AND n>=50` → `b0,b3`.
- `ip IN 10.0.0.0/24` → `a0,a1,b3`.
- inclusive time `[2000,5000]` → `a1,a2,a3,b0`.
- `body.severity = 2` → `a1,b0`.
- `n`-ascending projection returns the 8 frozen keys with literal projected
  `host`.
- host group counts `h1:3/90`, `h2:3/160`, `h3:2/110`.
- serial two-slot batch preserves per-slot totals/order.
- pinned page size 2/3 concatenates to `a0..b3` with no duplication/omission.
- stored `body` preserves explicit null, absent `tags` and empty-array states.

## 3. Query-time zero-GET evidence

| Provider | Counter | Cold open | Warm baseline | Warmed unified/projection/aggregation/batch | Warmed pinned pages |
|---|---|---|---|---|---|
| `FakeObjectStore` | exact `get_calls()` | `> 0` positive control | recorded after first full family run | unchanged | unchanged |
| real RustFS | `TransferStats::requests()` | `> 0`; `whole+range = 2` for 2 segments | recorded after first full family run | unchanged | unchanged |

Coverage limitation (documented, not generalized): `TransferStats::requests()`
counts budgeted `ObjectStore::get` attempts in `remote/transfer.rs`; direct
metadata GETs in `fetch_verified` bypass that counter. The zero-GET claim is
therefore limited to the counted GET path exercised by the query/batch/PIT
families, matching the PR 14G Phase A boundary.

## 4. Existing real-provider and fault suites executed

All commands used `--all-features` and `--test-threads=1`.

| Suite | Command filter | Observed |
|---|---|---|
| PR 14 P4 vertical | `--test pr14_storage_vertical -- --ignored real::` | 13 passed; `p4_child_bootstrap` run only by its `r01` parent |
| PR 14 P4 faults | `--test pr14_storage_faults -- --ignored f0` | 9 passed; `p4_fault_child_open` run only by its parents |
| PR 14G zero GET | `--test pr14g_remote_zero_get -- --ignored` | 1 passed |
| PR 13 remote proxy | `--test pr13_remote_proxy -- --ignored` | 7 passed |
| PR 13 crash harness | `--test pr13_crash_rustfs -- --ignored k0` | 5 passed; `child_entrypoint` run only by parents |
| PR 13 remote | `--test pr13_remote -- --ignored` | 3 passed |
| PR 13 lexical oracle | `--test pr13_oracle -- --ignored` | 1 passed |
| PR 13 geo oracle | `--test pr13_oracle_geo -- --ignored` | 1 passed |
| PR 13 provider-neutral | `--test pr13_remote --test pr13_oracle --test pr13_oracle_geo` (non-ignored) | 2 + 1 + 5 passed |

Internal child entrypoints (`p4_child_bootstrap`, `p4_fault_child_open`,
`child_entrypoint`) were never invoked standalone (X36). Their parent harnesses
spawned them with the documented environment and counted only the parent test.

## 5. What is not claimed

- No RustFS transfer throughput, latency, memory or scale claim.
- No cross-engine (Tantivy/Lucene) comparison.
- No assertion that skipped/ignored tests passed.
- No release/tag authorization.
- PR 15B/15E own new performance and transfer-resilience measurements.
