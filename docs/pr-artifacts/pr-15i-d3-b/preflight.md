# PR 15I-D3-B — preflight

Executed before any benchmark acquisition and before the candidate commit was
timed.

## Source identity

| Item | Value |
|---|---|
| Repository | `yduchesne/quervant` |
| Pinned BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` (merge PR #97) |
| Working branch | `dev/pr15i-d3b-retained-key-prefilter` |
| BASE `unified.rs` SHA-256 | `bb7a10357ffa215a5a21e77ca63caaa21fd614533d2c64e086e64e6c73f08433` |
| BASE `execute.rs` SHA-256 | `b49d49f7d8104f10e98bea82e7a30b80652dd87b5b78c083bf9f1384ea8edb55` |
| BASE `score.rs` SHA-256 | `f03712ec16822a343002346a1bf596f292ed7884411fc1a4b0dbe7ba911caf16` |
| BASE `Cargo.toml` SHA-256 | `c76ea1e2636cea23e3e6a49817699c90a5fe29c5896413c5b26f238ea9ce99c5` |
| BASE `Cargo.lock` SHA-256 | `293ff40c6cdfbc8408bedf9cb34131edc210d92ab2b051e601578de77c72baad` |
| Frozen PR15D spec SHA-256 | `ec6c0db865845184ba867fca97add3196bd62a3e88f2cf2c8042a1c594dce466` |

- The checkout was clean at BASE before the first edit (`git status --porcelain`
  empty) and `main`/`origin/main` both resolved to the pinned BASE.
- Source anchors matched the plan exactly: `collect_mixed` at line 571, heap at
  679, owned duplicate check at 907–914, `heap_admit_candidate` at 1199–1235,
  `admit_legacy_keyword_candidate` at 1275–1314 and
  `consider_borrowed_keyword_candidate` at 1323–1439.
- Exactly four `heap_admit_candidate` call sites and three duplicate-check sites
  exist; no fourth path was found (`DBX-04` did not fire).
- `quervant-core/src/search/execute.rs` (`BTreeMap<DocumentKey, f64>`) was not
  modified.

## Host and toolchains

- WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`, x86_64, 12 logical CPUs,
  32 GiB RAM, native `ext4` on `/dev/sdd`.
- `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1`, `cargo +1.85.0`
  1.85.0, Python 3.12.
- Benchmark affinity: `taskset` with the controller on the second allowed CPU
  and every adapter on the first allowed CPU, verified from
  `/proc/<pid>/status`.

## Frozen inputs

The PR15D generator, oracle, spec, harness, adapter manifest/source and the
adapter `Cargo.lock` are imported read-only and SHA-256 verified in both measured
worktrees before every campaign. The candidate changes no Cargo file.

## Decision register entries

- `DBX-01`: resolved; BASE matched and anchors were as documented.
- `DBX-05`: resolved; exactly the three duplicate check sites and one admission
  helper exist.
- `DBX-20`/`DBX-23`: `tests/rustfs/run.sh` cannot start the pinned RustFS image
  under podman-compose 1.0.6 (digest-pinned short name does not resolve and no
  unqualified-search registry is configured). Recorded as `RUSTFS_PENDING`.
- `DBX-47`: historical D3-A/D1-F evidence is present as committed documents and
  was used as historical context only.
