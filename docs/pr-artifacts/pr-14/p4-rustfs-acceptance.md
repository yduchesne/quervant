# PR 14 — P4 real RustFS acceptance (partial)

## Topology executed
- Podman rootless, existing pinned container `quervant-rustfs`,
  `rustfs/rustfs:1.0.1@sha256:1803faef…6a3c`, endpoint `http://127.0.0.1:9000`,
  health `{"status":"ok","version":"1.0.1"}`.
- Test-only credentials sourced from the container environment; not committed
  and not logged.
- Remote prefixes are unique per test/case (`pr14-p4/<tag>/<pid>/<nanos>/case`);
  local cache directories are unique and deleted after each case.

## PR 13 real-provider baseline (executed, all PASS)
| Target | Result |
|---|---|
| `quervant-objectstore --features s3 pr13_s3_rustfs` | 8/8 |
| `quervant-core --all-features pr13_remote` (real) | 3/3 |
| `quervant-core --all-features pr13_remote_proxy` | 7/7 |
| `quervant-objectstore --features s3 pr13_proxy_rustfs` | 5/5 |
| `quervant-core --all-features pr13_oracle` (real) | 1/1 |
| `quervant-core --all-features pr13_oracle_geo` (real) | 1/1 |
| `quervant-core --all-features pr13_crash_rustfs k0` | 5/5 |

## P4 vertical `pr14_storage_vertical`
Local `FsDirectory` and real RustFS are queried through the same
`UnifiedSearcher`/`execute_batch` entry points against the deterministic
`pr14-p4-v1` fixture (two immutable segments, six documents, mixed
lexical/typed/JSON/geo/IP, null/multi states, aggregation, batch).

| Case | Executed | Result |
|---|---|---|
| R02/R04/R06 cold compound local-vs-RustFS equivalence + aggregation | yes | PASS |
| R05 upsert/delete; old snapshot unchanged; new generation; cold reopen | yes | PASS |
| R08/R09 ordered batch S/F/S with aggregation, prior success retained | yes | PASS |
| R10/R11 remote exact/one-over `BatchMemoryBytes` and `BatchResponseBytes` | yes | PASS |
| R12 empty-cache cold bootstrap, no writer state | yes | PASS |
| R15 public cursor + aggregation fail-closed (STOP S2) | yes | PASS |
| Local oracle gates (`r02`, `r04`) | yes | PASS |

Command:
```sh
cargo test -p quervant-core --all-features --test pr14_storage_vertical -- --ignored --test-threads=1
```
Result: **5 real tests passed**, 0 failed; 2 local tests passed separately.

## Not yet executed (P4 not accepted)
- R01 separate-process child cold bootstrap (current cold reopen is in-process
  after dropping writer state; a separate child process is still required).
- R03 stale/wrong-generation adversarial case (partially covered by R05).
- R07 explicit empty/multi/JSON-geo tie matrix beyond the fixture's null/multi.
- R13 warm reuse/bounded cache, R14 forced eviction/pinned-reader safety.
- F01–F10 real proxy/crash faults, each 10 independent iterations.
- B01–B04 benchmark oracle gate, negative validator, and three qualified trials.

## Status
**P4: NOT ACCEPTED (PARTIAL).** Vertical storage/compound/batch/aggregation
evidence is real and green; fault-recovery and qualified benchmark gates remain.
**PR 14: NOT READY** (P4 completion + final-SHA CI).
