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

## C15A-01 fixup addendum (post-review)

Independent review found that `decode_allowance` reserved the two doc-id remap
vectors only when a `SortedRemap` section was present, although `decode_metadata`
retains two `Vec<u64>` in both branches. Repaired in commit `aca8ed1` by making
that allowance unconditional; full evidence in
[`fixup-c15a01.md`](./fixup-c15a01.md).

| ID | Trigger observed | Decision taken | Evidence |
|---|---|---|---|
| **X01** | Branch was exactly at reviewed SHA `748d85f`, tree clean | Proceeded with S0–S4 | `git status --short` empty, `git rev-parse HEAD` = `748d85f…` |
| **X03** | `fixture_segment()` (`Layout::Insertion`) provably has no `SortedRemap` section | Reused it for the production-path witnesses | `c15a01_has_section(bytes, SectionKind::SortedRemap) == false` in `c15a01_t05`/`t06`/`t09` |
| **X04** | No fixture with an explicit non-identity remap existed for exact arithmetic | Built controlled `ContainerBuilder` fixtures with only a `Schema` section (± `SortedRemap`) | `c15a01_minimal_segment` |
| **X05** | `doc_count = 0` is accepted by the codec for the controlled fixture | Added the zero case; no codec rule changed | `c15a01_t03` |
| **X06** | Explicit-remap comparison needed without touching encoded fixtures | Added a separate explicit fixture and compared allowances | `c15a01_t02`, `c15a01_t04` |
| **X07** | Independent checked arithmetic needed | Private `#[cfg(test)]` helpers `c15a01_expected_minimal_allowance` / `c15a01_remap_term`; no public API, no feature flag | `index/snapshot.rs` test module |
| **X09** | Exact allowance available and small relative to the test reader limit | Used it as the metadata cap and `1 << 22` as the independent test admission limit | `c15a01_t05` |
| **X12** | Controlled fixtures differ only by the remap section | Compared isolated remap term / equal-structure totals, never unlike-fixture totals | `c15a01_t01`, `c15a01_t03`, `c15a01_t04` |
| **X13** | FX-T07/T08/T10 already proven | Reused `g3_06`, the `ReaderByteBudget` unit tests, `g2_11`, `g4_11` and the `segment::metadata` overflow tests; cited instead of duplicating | `fixup-c15a01.md` §5 |
| **X14** | Unconditional allowance compiles with unchanged overflow semantics | Ran the full prescribed gate set | `fixup-c15a01.md` §8 |
| **X19** | `cargo fmt` wanted to reformat the new assertions only | Ran `cargo fmt --all`; diff stayed inside the two intended files | `git diff --stat` = `reader.rs` 21 lines, `snapshot.rs` test-only |
| **X20** | No lint suppressions were needed | Used conventional formatting/assertions | clean `clippy -D warnings` on stable and 1.85 |
| **X21** | No exact-head GitHub checks available in this environment | Not claimed as passing; recorded as unresolved | `fixup-c15a01.md` §9 |
| **X22** | Real RustFS unavailable locally | Recorded BLOCKED — ENVIRONMENT; continued all independent local gates | `pr13_remote -- --ignored` → `QUERVANT_RUSTFS_ENDPOINT … NotPresent`; no Docker daemon |
| **X29** | Pre-existing `docs/TESTING.md` conflict markers | Left untouched | unchanged file |
| **X30** | Existing PR artifacts needed the fixup evidence | Added `fixup-c15a01.md` and appended this addendum; prior reports retained | this section |
| **X31** | Local tests green, fixup ready | Committed on the same branch (no new branch, no merge) | `aca8ed1` |
| **X34** | No further review finding was investigated as part of this fixup | Other allocation/concurrency paths remain subject to separate independent review | `fixup-c15a01.md` §9 |

## C15A-02 / C15A-03 fixup addendum (post-review)

Independent review found (C15A-02) that the JSON offset vector charged one element
before an amortized `Vec::push` growth and (C15A-03) that the metered identity
remap path used the infallible `DocRemap::identity`. Both are repaired in commit
`6cdbf93`. Full evidence, including the scoped allocation audit and its findings
F1–F6, is in [`fixup-c15a02-c15a03.md`](./fixup-c15a02-c15a03.md).

| ID | Trigger observed | Decision taken | Evidence |
|---|---|---|---|
| **X01** | Branch at the required SHA `5695709`, tree clean | Proceeded S0–S5 | `git rev-parse HEAD` / `git status --short` |
| **X05** | Existing `encode_json_paths` helpers can build ≥9 offset groups | Reused them; no new fixture framework | `c15a02_t02` (12 groups) |
| **X06** | Two-JSON-field payload needed | Added a local deterministic schema helper inside the owning test module | `codec_schema_two_json` |
| **X07/X08** | `len < cap` / `len == cap` append paths | Insert without charge / charge delta → `try_reserve_exact` → reconcile → insert | `push_doc_offset`, `c15a02_t02` growth events |
| **X09/X10/X11** | Overflow, reserve failure, allocator excess | Typed `LimitExceeded`; excess charged before the append, rejection discards | `c15a02_t04`, `c15a02_t02` metered rejection |
| **X13** | Malformed section after ≥1 append | Original typed `Truncated`/`Corrupt` preserved | `c15a02_t05` |
| **X14** | Zero-offset directory | No allocation and no charge | `c15a02_t01` |
| **X16/X17/X18/X19** | Identity remap counts `0`/positive/overflow/allocator excess | `identity_fallible` + `identity_metered` (charge once, reconcile excess) | `c15a03_t06`, `c15a03_t07`, `c15a03_t08` |
| **X20** | Public `DocRemap::identity` used outside the cached path | Left unchanged; only the metered paths use the new constructors | `c15a03_public_identity_contract_unchanged` |
| **X21/X22** | Witnesses must discriminate; C15A-03 pre-fix failure is a panic, not an assertion | Strengthened C15A-02 witnesses (capacity 16 vs 12; 8 vs 5 observed pre-fix) and recorded the C15A-03 panic-vs-typed-error contrast | `fixup-c15a02-c15a03.md` §3 |
| **X23** | Growth instrumentation needed | `#[cfg(test)]` thread-local probe plus a `#[cfg(not(test))]` no-op; no release interface | `json_paths::growth_probe` |
| **X24** | `DecodeBudget` already charges each logical offset | Unchanged; `reserve_bytes` stays once per record | `c15a02_t03` exact budget boundary |
| **X25** | `fmt`/`clippy` complaints in the new code | Corrected syntax only; no semantic change | clean stable + 1.85 clippy |
| **X29/X30** | RustFS/CI unavailable | Recorded BLOCKED/DEFERRED; no pass claimed | `pr13_remote -- --ignored` output |
| **X31** | Audit found additional infallible-but-precharged retained allocations (F1–F6) | Stopped unrelated production fixes; recorded site, bound, charge, allocation API and proposed next fixup | `fixup-c15a02-c15a03.md` §5 |
| **X32** | Decoder scratch allocations (`norms::scoring_field_ids`, `spatial` validation buffers, JSON path cursors) | Classified as temporary, not retained; existing limits unchanged | audit table |
| **X37** | Baseline `docs/TESTING.md` conflict markers | Untouched | unchanged file |
| **X38/X39** | Local gates green; evidence commit moves HEAD | Re-ran the full prescribed suite after the final commit | `fixup-c15a02-c15a03.md` §6 |

## F1–F6 fallible-allocation fixup addendum (post-review)

F1/F2/F3/F5/F6 are repaired in commit `b3c72b9`; **F4 is a preauthorized HARD STOP
(X20)** because `Arc::try_new` is unstable on the workspace MSRV (1.85.0) and on
current stable (E0658, issue #32838). Full evidence, the compile probe and the
T01–T16 witness matrix are in [`fixup-f1-f6.md`](./fixup-f1-f6.md).

| ID | Trigger observed | Decision taken | Evidence |
|---|---|---|---|
| **X01** | Branch HEAD `0c2a121`, clean tree | Ran S0 then S1–S6 | `git rev-parse HEAD`, `git status --porcelain` |
| **X05** | `check_alloc::<T>` already produces the required typed limit | Reused it at every F1 site before the fallible reservation | `format.rs`, `f1_t01`/`f1_t02` |
| **X07** | Zero counts at F1/F3/F6 | Reserved nothing, returned empty vectors | `f1_t01`, `f3_t04`, `f6_t05` |
| **X08/X09/X10** | Positive validated counts, product overflow, `TryReserveError` | `try_reserve_exact` after checked limits; typed `LimitExceeded` | `reserve_exact_vec`, `f1_t02`, `f6_t06` |
| **X11** | Allocator may over-allocate | Measured capacities remain reconciled by `metadata_charge`/`finalize` (and `identity_metered` excess) | `c15a01_t02`, `g2_02`, `c15a01_t05` re-executed |
| **X13** | Corrupt input on the cached path | Original typed errors; no capacity fallback masking | `g3_02`–`g3_04b`, `c15a02_t05`, `f5_t07` |
| **X17/X18** | F6 state 0 already fallible; second reservation failure | State 0 preserved; `reserve_pair_with` drops the first vector and returns a typed error | `f6_t05`, `f6_t06` |
| **X19** | Multibyte strings | Reserve `source.len()` bytes, verified byte-exact and byte-sized | `f5_t07`, dictionary witness |
| **X20** | `Arc::try_new` unavailable on 1.85.0 and stable | **HARD STOP F4**; no unsafe/custom allocator/panic-catching workaround; F1/F2/F3/F5/F6 completed | `/tmp/f4_probe.txt`, `fixup-f1-f6.md` §3 of S0 and §1 |
| **X23** | Clippy rejected `source.as_bytes().len()` | Corrected to `source.len()`; no semantic change | clean stable + 1.85 clippy |
| **X24** | T09 real `TryReserveError` injection at F2/F3/F5 sizes | Documented as infeasible without a production seam or memory exhaustion; used bounded mechanism witnesses instead | `fixup-f1-f6.md` §3 |
| **X27/X28** | RustFS/CI unavailable | Deferred; acceptance explicitly blocked, no PASS claimed | `pr13_remote -- --ignored` output |
| **X30/X31** | Temptation to change budgets/formats/APIs for F4 | No change; architecture decision required | `git diff --stat` limited to five segment files |
| **X32/X33** | Remaining allocations | No new retained owner; scratch allocations already classified | audit table in `fixup-c15a02-c15a03.md` §5 |
| **X34/X35** | F4 blocked independently | Continued and completed F1/F2/F3/F5/F6; reported local completion with acceptance blocked | this addendum |
| **X37/X39** | Local gates green; evidence commit moves HEAD | Re-ran the full prescribed suite on the final SHA | `fixup-f1-f6.md` §5 |
