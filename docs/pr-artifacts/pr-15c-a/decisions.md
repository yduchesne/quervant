# PR 15C-A decision and exception log

Every decision-matrix row actually exercised, with the evidence that triggered it.
Rows not listed were not triggered. Priority rule applied throughout: a STOP row
overrides any AUTO row whose facts are unproven.

| ID | Trigger observed | Decision taken | Evidence |
|---|---|---|---|
| **X01** | Baseline clean at the observed SHA, tree clean, baseline tests green | Proceeded to S0 | `git rev-parse HEAD` = `42b1944…`; `cargo test -p quervant-core --lib` 771 passed; `--test pr15b_diagnostics` 16 passed |
| **X05** | A branch with the identical base and no work already existed (`dev/pr15c-a-immutable-segment`) even though the plan suggested `feat/pr15c-a-verified-segment-state` | Reused the existing branch; no reset, no force push | `git log --oneline main..HEAD` was empty at start |
| **X07** | `Rc<JsonPathDirectory>` appeared only in the reader field, the `JsonPathsReader` constructor and `open_json_paths` | Converted the immutable directory handle to `Arc` | `crates/quervant-core/src/segment/json_paths.rs`, `segment/reader.rs` |
| **X08** | `FieldNormsReader` held only `BTreeMap<u32, FieldNorms>` | Converted to sorted `Vec<(u32, FieldNorms)>` with `binary_search_by_key`; duplicate/out-of-order rejection, doc-count and accessor semantics preserved | S1 commit `b807ce6`; `segment::norms` tests |
| **X10** | `VerifiedSegmentState` is `Send + Sync` after the approved `Rc`→`Arc` and norms-vector adaptations | Continued | `g1_01_verified_state_and_snapshot_are_send_sync` |
| **X12** | Pre-existing `docs/TESTING.md` conflict markers confirmed on the pinned base | Logged in `preflight.md` §1; file not edited | `rg -n '^(<<<<<<<|=======|>>>>>>>)' docs/TESTING.md` → lines 56–59 only |
| **X13** | Not triggered: `pr15b_diagnostics` exists unchanged | Used the real target name | `cargo test -p quervant-core --test pr15b_diagnostics` |
| **X14** | Candidate allowance proven complete and derivable from validated section lengths plus proven minimum encoded widths, and reserved before every retained allocation | Continued through S3 | `preflight.md` §5 and `segment/reader.rs::parser_allowance` / `decode_allowance` |
| **X16** | Metadata cap `0`; cap below the candidate allowance | Zero-cap and cap-rejection branches always take the original verified uncached reader | `g2_01`, `g2_02` (one-byte-over) |
| **X17** | Meter reserve overflow / allowance exceeded | No allocation, no publication; verified fallback | `segment::metadata` unit tests; `g2_02` |
| **X18** | Fallible optional allocation failure inside a cached build | Allowance released, slot reset, waiters notified, verified fallback | `g2_04`, `g2_12` |
| **X19** | Parser/decoder reports digest, feature or structure corruption | Original typed error propagated; never converted to a fallback | `g3_02`, `g3_03`, `g3_04`, `g3_04b` |
| **X20** | Cache hit on an exact snapshot slot | Active-reader admission charge kept, `Arc` cloned, fresh query-local caches created | `g2_11`, `g3_01`, `g4_11` |
| **X21** | First concurrent miss from `Empty` | Slot set to `Building`; hashing/decoding outside the mutex | `g4_01` (2/8/32 threads), `g4_09` |
| **X22** | Another thread observes `Building` | Waits on `Condvar` and rechecks the predicate (spurious wakeups allowed) | `g4_01`, `g4_04` |
| **X23** | Initializer returns an ordinary error or panics | RAII guard restores `Empty` and notifies; the error/unwind is retained | `g4_05`, `g4_07` |
| **X24** | Poisoned slot lock, and no existing error variant represents it without extending the public error contract | Mapped to the existing typed `IndexError::CorruptCommittedState` and failed closed; the RAII cleanup path recovers the guard only to reset and notify | `g4_06` |
| **X25** | Not triggered — an existing typed variant was usable (see X24) | — | — |
| **X26** | Snapshot changed by refresh/commit | Each snapshot has its own slots/budget; no `Ready` state crosses snapshots | `g3_07`, `pr15c_a_t03` |
| **X27** | Last `Arc<VerifiedSegmentState>` drops after the snapshot | Reservation attached to the state releases on the last `Arc` drop | `g2_10` |
| **X28** | Existing reader byte admission fails even with a warm cache | Original `ResourceLimit` failure preserved; no cache bypass | `g4_11` |
| **X29** | `support::read_verified` and descriptor checks unaltered | Proceeded with integration qualification | `g3_05`, unchanged `index/mod.rs` |
| **X31** | Real RustFS required but unavailable (no Docker daemon, no `QUERVANT_RUSTFS_*` environment) | Recorded **BLOCKED — ENVIRONMENT**; all independent local gates executed | `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored` fails with `QUERVANT_RUSTFS_ENDPOINT … NotPresent` |
| **X38** | Counters needed only to prove verification-once behaviour | `#[cfg(test)]`-only fields/accessors (`verifications`, `build_fault`, `metadata_used`, `candidate_allowance_for_test`); no release-path telemetry | `index/snapshot.rs`, `segment/reader.rs` |
| **X41** | Measured retained charge could exceed the candidate allowance | `MetadataMeter::finalize` rejects it, the meter drop releases everything and the caller takes the verified fallback | `segment::metadata::tests::finalize_rejects_measured_over_allowance_and_releases_all`; `g2_02` asserts `measured <= allowance` |
| **X43** | Same segment ids with different bytes | No reuse: each snapshot verifies its own `Arc<Vec<u8>>`; the corrupted variant fails closed | `g3_06` |
| **X44** | `open_segment_reader` has no cancellation argument | No timeout/polling/cancellation interface added; existing cancellation semantics untouched | `index/snapshot.rs` |
| **X45** | Existing local authoritative tests can run | Executed the full workspace suite, including real-filesystem restart paths | `acceptance.md` |
| **X47** | Coverage measured against the 85% floor | 91.65% workspace line coverage; no gate loosened, no exclusions added | `acceptance.md` |
| **X49** | All required local gates pass; the external RustFS gate is unavailable | Produced a BLOCKED report; no DONE/merge claim | this file + `acceptance.md` |

## Process notes (recorded for the reviewer)

1. **Stage commits S2–S4 are one commit.** The authoritative state extraction
   (S2), the allocation meter (S3) and the snapshot slot wiring (S4) are a single
   compile unit: with only S2/S3 landed, the cached builder and the meter are dead
   code and `clippy -D warnings` fails the branch. They were therefore landed as
   `9fe9470` with all G1–G4 unit witnesses, and S5's production-path integration
   witness as `d54e220`. S1 was committed in isolation as `b807ce6`, exactly as
   the plan prescribes.
2. **`LimitExceeded` classification.** Inside an *optional* cached build, a
   `SegmentError::LimitExceeded` (resource/capacity bound, including a failed
   `try_reserve_exact`) is treated as an optional cache failure: the allowance is
   released and the authoritative uncached path runs, re-raising the identical
   typed error when the input genuinely exceeds a limit (X17/X18/X19). Digest,
   feature, structure, schema and metadata errors are never converted.
3. **`const fn` accessors.** `doc_count`, `schema`, `remap`, `dictionary`,
   `field_norms`, `time_bounds`, `spatial` (and crate-internal `limits`) can no
   longer be `const fn` because they now delegate through `Arc`. Signatures,
   names, return types and behaviour are unchanged; no caller used them in a const
   context (verified by a clean workspace build and clippy run on 1.85 and stable).
4. **Aggregate residency.** Each snapshot owns one metadata budget capped by the
   constructor's `reader_copy_limit`; aggregate metadata residency is therefore
   bounded by `(number of concurrently retained snapshots) × cap`, and concurrent
   snapshot retention remains governed by the existing snapshot/PIT limits.
   No cross-snapshot cache or eviction policy was introduced (VSR-AD-009).
5. **Architecture document status left unchanged.** `docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md`
   still reports "not yet implemented on `main`" because this branch is not merged
   or accepted; changing it would imply an implementation claim the reviewer has
   not yet accepted.
