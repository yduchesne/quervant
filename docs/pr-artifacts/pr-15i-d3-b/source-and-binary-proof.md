# PR 15I-D3-B — source and binary proof

## Source identity

| Item | Value |
|---|---|
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` |
| Candidate production/tests commit | `48d9abf3eeefbccb480d89eac95f6e6911e078d5` |
| Tooling freeze (T0) | `155ebafafa29fb0e6b6cbf953f89445f4880fd2f` |
| BASE `unified.rs` SHA-256 | `bb7a10357ffa215a5a21e77ca63caaa21fd614533d2c64e086e64e6c73f08433` |
| Candidate `unified.rs` SHA-256 | `493f93825e77581833a26c6436c5ea35aed26fc453eb2cbcec80733710ec183c` |
| Candidate test SHA-256 | `ff5f0feced8f65a1ef2f08f7e830eeebec657472e91d79f2a99ce42294dd84ac` |

`git diff --name-only BASE..candidate` contains only:

```text
crates/quervant-core/src/search/unified.rs
crates/quervant-core/tests/pr15i_d3_b.rs
docs/pr-artifacts/pr-15i-d3-b/design-and-correctness-trace.md
docs/pr-artifacts/pr-15i-d3-b/preflight.md
docs/pr-artifacts/pr-15i-d3-b/test-matrix.md
```

No `Cargo.toml`, `Cargo.lock`, adapter, codec, `execute.rs`, reader, snapshot or
column source changed. The D3-B source proof (both controller and independent
verifier) requires the candidate `unified.rs` to contain
`RetainedKeyPrefilter`, `D3B_FILTER_BITS`, `D3B_FILTER_WORDS`,
`D3B_MAX_ADMISSIONS`, the literal `request.top_k.limit == 100` activation and
the unchanged `duplicate live document key across segments` detail, and forbids
the rejected D1-C1/C2 design symbols (`RetainedKeyFingerprintIndex`,
`retained_key_exists`, `key_fingerprint`, `index_insert_after_heap_push`,
`index_remove_after_heap_pop`, `doc_key_view`). Both validations passed.

## Diff shape (production)

The production diff is confined to:

- the request-local `RetainedKeyPrefilter` (16 `u64` words, `u16` admissions,
  `disabled` flag) with `retained_key_hash`, `d3b_indices`, `may_contain` and
  `note_admitted`;
- `duplicate_live_key_error`, `check_retained_duplicate` and `admit_and_note`;
- `heap_admit_candidate` returning `SearchResult<bool>` with its budget
  statements unchanged;
- the three duplicate-check call sites and one private filter argument on the
  borrowed/legacy keyword helpers;
- the `#[cfg(test)]` observation module and the unit test module.

`git diff --stat BASE..candidate -- crates/` reports 2 files changed,
2,012 insertions, 29 deletions.

## Binary and index identity of the control

| Item | Arm A | Arm B |
|---|---|---|
| Source | `39dbd9f5…` | `39dbd9f5…` |
| Binary SHA-256 | `cdc434c8ba2691a0636c7dbb03018f8a8e2a4f31d85ce102359c806cff44634c` | `d0847853c0bbe62060a4fcd4b3e7a2350f9130f86ae9e18fb9d720ccb693a089` |
| Binary bytes | 4,478,176 | 4,478,656 |
| `.text` bytes | 1,170,032 | 1,170,288 |
| `.rodata` bytes | 372,048 | 372,048 |

The binary mismatch is the control blocker. A non-timed dry rebuild of the same
source path into two different target directories yielded the identical binary
`cdc434c8…` (4,478,176 bytes), proving the difference comes from the distinct
worktree paths (`sources/base` vs `sources/control-base`) embedded by the Rust
build rather than from a source, dependency or feature difference. No
`--remap-path-prefix` or other build flag is authorized.

Indexes were byte-identical across arms: 10K = 1,560,111 bytes (STORED 166,369,
digest `3840f8ba8e44717e…`) and 100K = **15,747,551** bytes (STORED
**1,661,455**, digest `5734ae60591f7563…`), matching the frozen sentinels.

## Post-outcome source state

The candidate remains committed on `dev/pr15i-d3b-retained-key-prefilter` as an
unmerged measurement branch. Per `DBX-31`/§12, a measurement-blocked outcome
does **not** ship the candidate and does **not** authorize an additive rollback
either (rollback is reserved for correctness or performance rejection). No
production file was changed after the candidate commit; the only later commits
are documentation.
