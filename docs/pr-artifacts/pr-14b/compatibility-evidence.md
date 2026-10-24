# PR 14B — historical JSON compatibility evidence (B18/B19)

## Fixture provenance (genuine prior artifact, not synthesized today)

| Item | Value |
|---|---|
| Path | `crates/quervant-core/tests/fixtures/segment/json_paths_golden.seg` |
| Introduced by | commit `65f74401010f7d1f7f7faabf0709dee775f06597` — "PR 11 Phase 0" |
| Producer | the PR 11 Phase 0 production writer via the checked-in, `#[ignore]`d generator `pr11_json_corruption.rs::generate_json_paths_golden` |
| Logical corpus | two documents `a` = `{"v":1}`, `b` = `{"v":2}` in the indexed `body` JSON field, timestamp `1` for both |
| Length | 1186 bytes |
| Frozen SHA-256 | `0528a62cdb02fcd08754d5776f23bd16de787f788597ade93d5dfbc65c30a02f` |
| Format | container magic `TRWSEG01`, major `1`, minor `0` |
| Required feature | `FEATURE_JSON_PATHS` (`0x0009`) version `1` |
| Section | inline `SectionKind::JsonPaths` (`0x0010`) |
| Sidecars | **none** — this format stores JSON paths as an inline segment section; there is no separate JSON-path sidecar |
| Existing guard | `pr11_json_corruption::t13_json_paths_golden_fixture` already asserts the frozen digest and readability |

The fixture was verified as a real historical artifact before qualification:
it is tracked in git history, its bytes are frozen by an existing regression
test, and it was not regenerated for PR 14B. The current writer independently
reproduces the same 1186 bytes for the same corpus (asserted by
`b18_b19_historical_json_segment_compatibility`), which additionally proves that
the decoder reads exactly the historical object rather than a lookalike.

## Scope and limitation (explicit)

JSON path indexing was introduced at wire/feature version **v1** in PR 11. No
older *supported* JSON wire version exists in repository history. Therefore this
qualification proves:

- frozen historical bytes decode under the current codec;
- JSON predicates/projections agree with a test-owned table;
- corruption and unsupported versions fail closed.

It does **not** claim a cross-version migration test, because there is no older
supported JSON version to migrate from. This limitation is recorded for 14C
acknowledgement (exception E18) and no compatibility beyond the supported v1
wire is claimed.

## Local qualification

Test: `pr14_storage_vertical::b18_b19_historical_json_segment_compatibility`.

| Assertion | Expected (test-owned) | Observed |
|---|---|---|
| Frozen digest | `0528a62c…a02f` | PASS |
| Required feature | `(FEATURE_JSON_PATHS, 1)` present | PASS |
| Inline JSON section | `SectionKind::JsonPaths` present | PASS |
| Doc count | 2 | PASS |
| Current writer reproduces the frozen object | committed segment bytes == fixture bytes | PASS |
| JSON exists `$.v` | `["a","b"]` | PASS |
| JSON equals `$.v = 2` | `["b"]` | PASS |
| JSON equals `$.v = 3` | `[]` | PASS |
| Stored projection doc 0 | `{"v":1}` | PASS |
| Stored projection doc 1 | `{"v":2}` | PASS |
| Corrupt payload byte | rejected at segment open | PASS |
| Major version `1 → 2` | `UnsupportedFormatVersion{major:2,minor:0}` | PASS |

## Remote qualification

Test: `pr14_storage_vertical::real::b18_real_historical_json_remote`.

The same logical corpus was committed through the production S3 adapter to the
pinned RustFS service, the writer-local workspace was deleted, and a cold
`RemoteIndex::open_existing` fetched the authoritative object.

| Assertion | Expected | Observed |
|---|---|---|
| Authoritative remote segment bytes | equal the frozen `json_paths_golden.seg` | PASS |
| JSON exists `$.v` over the remote snapshot | `["a","b"]` | PASS |
| JSON equals `$.v = 2` over the remote snapshot | `["b"]` | PASS |

## Corruption / unsupported behavior

`SegmentReader::open` rejects:

- a single flipped body byte (section/container checksum failure);
- a container whose major format version is `2` (typed
  `UnsupportedFormatVersion`).

Neither case is reinterpreted as an empty or current-format segment, and no
production codec was changed to accept them.

## What was not changed

- No segment/manifest/`CURRENT` format change.
- No new metadata or sidecar.
- No automatic migration and no newer-version claim.
- Existing snapshots and persisted documents reopen identically.
