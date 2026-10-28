# PR 15A — compatibility and durability evidence

**Status:** `PASS (EXECUTED)` for the local compatibility/durability tests listed
below. Historical fixtures are referenced unchanged; no golden bytes were
regenerated in PR 15A. v0.1 remains `NOT RELEASED`.

## 1. Historical fixtures reused unchanged

| Fixture | Identifier | Frozen digest / size | Provenance | PR 15A use |
|---|---|---|---|---|
| Historical PR 11 JSON-path segment | `crates/quervant-core/tests/fixtures/segment/json_paths_golden.seg` | SHA-256 `0528a62c…a02f` (full constant in `pr14_storage_vertical::b18_b19`) | checked in by commit `65f7440` ("PR 11 Phase 0") | C03 digest + container feature; decode/behaviour reused from `b18_b19` |
| Golden segment decode table | `crates/quervant-core/tests/fixtures/segment/golden.seg` | frozen in-tree fixture | PR 5/7 golden fixture | `segment_golden` executed |
| Field-norm golden | `crates/quervant-core/tests/fixtures/segment/golden_norms.seg` | frozen in-tree fixture | PR 7 amendment fixture | `segment_golden` executed |
| Pre-`FieldNorms` committed index | `tests/fixtures/index/pr07_pre_norms_v1/` | CURRENT `56067c79…ea88`, manifest `276d8025…f1d1`, segment 1 `da391e76…f558`, segment 2 `05086828…4b4e` | historical `a8adf37` writer; see fixture README | `pr07_compatibility` executed |

No fixture file was modified by this PR (`git diff --stat -- crates/quervant-core/tests/fixtures` empty).

## 2. State-transition table asserted by A-T11/A-T13/C01/C02

| State | Expected generation | Reader visibility | Error class | Replay token |
|---|---|---|---|---|
| Initial frozen generation | 2 | 8 base keys | none | unused |
| Mutation batch accepted | 2 (pending) | writer-effective state; old snapshot unchanged | none | consumed durably at commit |
| Durable commit | 3 | new live keys `a0,a1,a2,a3,b0,b2,b3,c0` | none | reusable |
| Replay after reopen | 3 (no advance) | identical live keys and response | none (`replayed=true`) | reusable, no second mutation |
| Old retained PIT | 2 | original 8 keys; `a1.host=h2`, `a1.n=20` | none | n/a |
| Forced compaction | 4 | same logical new keys | none | reusable |
| Stale reader pointer | 2 | cannot see `c0` | none | n/a |
| Fresh `open_existing` handle | 3/4 | sees `c0`; no silent substitution | none | n/a |
| Corrupt/truncated golden segment | n/a | no readable generation | typed `SegmentError` | n/a (reused `b18_b19`, `pr11_json_corruption::t14`) |

## 3. New PR 15A compatibility tests

| ID | Test | Topology | Result |
|---|---|---|---|
| C01 | `pr15a_compatibility::a15_c01_reopened_fs_with_retained_pin_and_mutation` | native Linux `FsDirectory`, drop handle, reopen, mutate, retained generation-2 PIT | **PASS (EXECUTED)** |
| C02 | `pr15a_compatibility::a15_c02_projection_after_reopen_and_compaction` | native Linux `FsDirectory`, mutation + forced compaction, reopen, source projection | **PASS (EXECUTED)** |
| C03 | `pr15a_compatibility::a15_c03_historical_json_segment_digest_unchanged` | frozen historical bytes, no rewrite | **PASS (EXECUTED)** |

Command:

```sh
cargo +stable test -p quervant-core --test pr15a_compatibility -- --nocapture
```

Observed: `3 passed; 0 failed; 0 ignored`.

## 4. Executed inherited compatibility suites

| Suite | Command | Observed |
|---|---|---|
| Golden decode | `cargo +stable test -p quervant-core --test segment_golden` | 2 passed; 1 ignored (generator-only entrypoint) |
| JSON corruption/negotiation | `cargo +stable test -p quervant-core --test pr11_json_corruption` | 8 passed; 1 ignored (golden generator) |
| Pre-norms compatibility | `cargo +stable test -p quervant-core --test pr07_compatibility` | 14 passed |
| Historical JSON segment | `cargo +stable test -p quervant-core --test pr14_storage_vertical` (local, incl. `b18_b19`) | 5 passed |
| Recovery | `cargo +stable test -p quervant-core --test pr09_recovery` | 4 passed |
| Merge | `cargo +stable test -p quervant-core --test pr09_merge` | 6 passed |
| Mutation qualification | `cargo +stable test -p quervant-core --test m5_mutation_qualification` | 26 passed |
| Public cursor | `cargo +stable test -p quervant-core --test pr14a_public_cursor` | 29 passed |

Ignored generator/child entrypoints were not counted as PASS evidence. Their
authoritative parent/regression suites are listed in `test-traceability.md`.

## 5. Boundaries

- PR 15A introduced no segment/manifest/cursor/public schema change.
- The frozen `pr15a_v1` fixture is new test data; it does not alter persisted
  production layout.
- No historical checksum was overwritten.
