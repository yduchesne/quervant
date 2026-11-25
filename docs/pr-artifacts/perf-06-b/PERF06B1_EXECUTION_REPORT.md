# PERF-06-B1 — execution report

**Plan:** [`PERF06B1_DETAILED_PLAN.md`](PERF06B1_DETAILED_PLAN.md) (revision 1),
copied verbatim from the approved download. SHA-256
`fe5ef98d100f8e1160e19c5d88663abde580d201d806c04721f94cb4a429f951`, Git blob
`e37519560e6e11c27055acd3b8729bc1b34af42c`.

**Status: `PERF06_B1_READY_FOR_INDEPENDENT_REVIEW`.** Implementation, correctness
tests, local QA, real-RustFS acceptance and coverage pass on the declared source.
Independent review and merge (**G10**) remain maintainer-owned and **open**.
Nothing in this report is a measured performance result.

---

## 1. Current status and gate ledger

| Gate | Result | Evidence |
| --- | --- | --- |
| G0 — source/authority | **PASS** | worktree clean at `480a77e`; `origin/main` fetched = pin (`480a77e78c6897e05cb7ceb76b01434974b82ec6`); branch `dev/perf06-b1` existed locally with no work and no remote head; protected-scope diff vs pin empty (`evidence/diff-inventory.txt`) |
| G1 — frozen contract | **PASS** | INV01–INV15 traced in §5 below |
| G2 — local representation | **PASS** | §2; literal 116-byte wire witness, 137-byte v1 control |
| G3 — shared snapshot values | **PASS** | §3; B1-G01…B1-G20 |
| G4 — unit/adversarial evidence | **PASS** | 60 `b1_*` tests (B1-U01…U16, B1-G01…G20) executed |
| G5 — local lifecycle | **PASS** | B1-I01…I08 incl. genuine historical fixture, held PITs, exact compaction cap, child-process reopen |
| G6 — real boundary | **PASS** | B1-R01 executed against the pinned RustFS image; `PERF06_B1_R01_PASS` |
| G7 — final local QA | **PASS** | §6 ledger; line coverage default **92.75 %**, all-features **92.35 %** |
| G8 — mandatory CI | **PASS** | run `45516023460` on head `8e11484`: `rust`, `msrv`, `rustfs`, `python-benchmark-framework`, `benchmark-adapter-contract` all `success`; the `rustfs` log shows `perf06_b1_rustfs` and `b1_r01_cold_shared_ordinals_and_pit ... ok` (`evidence/ci-status.txt`) |
| G9 — docs/report/review package | **PASS** | §1–§8, additive docs, this report |
| G10 — independent acceptance | **OPEN (maintainer)** | never self-issued |

## 2. Authorization, scope, and what changed

Authorized work only: plan artifact, source delta, tests, QA, docs, report and a
draft PR. No performance acquisition, profiling, cross-engine run, benchmark
framework/threshold change, B2 collector work, B3 identity work or B4
qualification was performed.

Implemented:

* **Required feature** `FEATURE_KEYWORD_ORDINALS = 0x0010/1` (`segment/format.rs`)
  — a feature namespace, unrelated to the `JsonPaths` section kind `0x0010`.
* **COLUMNS payload version 2** with layout `0x03`
  (`LAYOUT_KEYWORD_ORDINAL_SINGLE`) for every columnar single-cardinality
  `Keyword` field: sorted distinct raw-term dictionary, `(U+1)` packed offsets,
  packed per-document ordinals, preserved absent/null/`Single`/`MultiOne` states.
  Header width (46), block-entry width (36) and all other layouts are unchanged.
* **Encoder** `encode_columns_with_ordinals(schema, ColumnDocuments, block_docs,
  limits) -> EncodedColumns` used by both producers
  (`SegmentBuilder::build` via `ColumnDocuments::References`, compaction via
  `ColumnDocuments::Documents`). `encode_columns` keeps its frozen v1 bytes and
  remains the legacy entry point.
* **Borrowed ordinal API** in the public `segment::column` module:
  `ColumnReader::bind_keyword_ordinals`, `KeywordOrdinalColumn`
  (`dictionary_len`, `dictionary_term`, `doc_ordinal`), `KeywordOrdinalState`,
  `KeywordOrdinalValue`.
* **Shared snapshot maps** in the new `index/keyword_ordinals.rs`:
  `ReaderSnapshot::prepare_keyword_ordinals`, `KeywordOrdinalPreparation`,
  `KeywordOrdinalUnavailable`, `SnapshotKeywordOrdinals`, `SegmentOrdinalMap`,
  re-exported from `index`.
* **Merge reconstruction** now opens each source's columns once (not per
  document/column) and reuses them.
* **Container feature/body agreement** for `COLUMNS` v1/v2 in
  `segment/reader.rs::decode_metadata`, before payload decoding.
* **CI**: exactly one added command in the existing real-RustFS step.

Explicitly unchanged (protected): `Cargo.toml`/`Cargo.lock`, toolchain files,
`.cargo`, AGENTS/authoring-guide policy, `contract/*`, `search/*` (production),
storage/remote publication and GC, postings formats, document-key codecs,
vector/distributed APIs, benchmark framework/config/results, old fixtures and
A4/A5/A6 evidence. The protected-path diff against the pin is empty.

## 3. Implemented format and semantics

Wire grammar (all little-endian; derived widths, never stored):

```text
ow = packed_width(L)                 # 1..=8, 0 -> 1
dw = packed_width(U.saturating_sub(1))
data_base = dir_offset + dir_len
[data_base + 0]  u64  U             # distinct raw terms
[data_base + 8]  u64  L             # total raw dictionary bytes
[data_base + 16] (U+1) * ow         # offsets into the blob, monotone, [0..=L]
[.. + L]         L bytes            # terms in strict UTF-8 byte order
[blocks]         rows states, then rows*dw packed ordinals
```

States: `0x00` absent, `0x01` explicit null, `0x03` single, `0x04` allowed
single-element multi. `0x02` and any other tag are rejected at open. Stateless
rows must hold a zero slot, so the empty string is never a sentinel. Terms are
compared as raw bytes only; there is no normalization, case folding or locus for
reusing normalized postings terms anywhere in the codec or the merge.

Validation order for v2 is header/inventory → schema/layout/directory geometry →
dictionary prefix/widths/extents → offsets and per-term UTF-8/order → block
extents, states and ordinals → complete section consumption. Exact error labels
are the frozen §9.1 table (for example
`keyword dictionary terms are not strictly ascending`,
`keyword ordinal out of range`, `noncanonical v2 column extent`,
`trailing v2 columns bytes`).

Logical compatibility is unchanged: `ColumnReader::value`, `keyword_sort_view`
and `encoded_value_shape` report the legacy logical span (`term_len+2` single,
`term_len+3` multi-one, one element), so `search/typed_compare.rs` value
admission still charges materialized strings; a single-element multi keeps the
legacy decode path in the borrowed sort view; the multi-one logical budget
sequence (entry check → one-element `FieldValue` vector → keyword string budget)
is preserved.

## 4. Memory, algorithm and accounting audit

* **Encoder.** Borrowed occurrences `(term: &str, physical doc)` scanned once per
  eligible field, sorted once (`sort_unstable_by` on bytes), one read-only
  distinct scan for `U`/`L`/widths, then one pre-admitted final buffer written
  through small checked slice helpers. No document/`FieldValues`/`String` clone,
  no `String`→ordinal map, no second completed column body, no per-record
  `try_reserve_exact(1)`. Occurrence growth is geometric from
  `min(8, N)` capped at `N`; state buffers request exactly `N` bytes.
* **Inherited ordinary-layout exception (disclosed).** Non-eligible columns reuse
  the baseline layout-1/2 block encoder and its existing `ByteWriter` temporary
  allocation behaviour. B1 charges those *retained* block buffers once before
  final-output admission but does not pre-admit the inherited temporaries; B1
  therefore makes **no** comprehensive allocator/peak-memory claim for the
  ordinary encoder. `B1-U09`-style accounting is exercised by the exact
  compaction boundary in B1-I06.
* **Snapshot merge.** One streaming k-way heap (`BinaryHeap::from` over the
  pre-admitted head vector, `peek_mut`, one reheapification per entry),
  `O(T log S)` byte comparisons, `O(width*T + S)` retained. A single segment is
  the identity map with no vectors and no term reread. No document, visibility
  mask, stored value or `column_value` read; no string copy, no inverse table.
* **Accounting.** One `MetadataMeter` per optional build: fixed construction
  scratch first, then one `extend` by the checked `T*width` payload; every
  allocation is pre-admitted (checked arithmetic, `check_allocation_bytes`,
  `try_reserve_exact`), actual capacities are reconciled, and `finalize` retains
  only the measured owner. The `MetadataReservation` lives inside
  `SnapshotKeywordOrdinals`, so an external `Arc` keeps its charge alive after
  the snapshot drops, and there is no snapshot→cache→snapshot cycle.
* **Decoder.** No dictionary strings, per-term descriptors, offsets or document
  ordinals are heap-copied during validation; UTF-8 validation reads immutable
  bytes. `ColumnMeta` keeps its size, so `column_geometry_allowance` stays valid
  and no per-column geometry table is added.
* **Bound access.** `doc_ordinal` performs one block-directory lookup plus one
  packed read; binding resolves the field once; `dictionary_term` is a checked
  byte range with no allocation.

## 5. Invariant → implementation → test trace

| Invariant | Implementation | Primary evidence |
| --- | --- | --- |
| INV01 canonical field ids; no per-doc name lookup | `CodecSchema` ids reused; `bind_keyword_ordinals` resolves once | U03, U16 (one block read per lookup), G09/G11, I01 |
| INV02 one sorted dictionary + ordinals, no duplicate payload | layout 3 encoder | U02 (116-byte literal vs 137-byte v1), U15 (`ordinal ≤ legacy+17`), I06 |
| INV03 raw values and state shapes preserved | state grammar + `value()` | U01, U07, U13, U14-style rejection, I05 |
| INV04 byte-exact order/equality | byte sort + merge | U03, U05, U10-grade G05 families, G01/G04, I01 |
| INV05 sibling APIs logically equivalent | `ValueSpan::Ordinal` handling | U08, U12 (existing v1 fixtures), U13, I01/I05/I08 |
| INV06 every producer emits the same combination | build + merge share the encoder result | U11, I03/I04/I06 |
| INV07 new-format corruption rejected before trusted access | v2 parser | U05, U06, G18, I07 |
| INV08 one meaning across admitted segments | heap merge + packed maps | G01/G05/G06, I01, R01 |
| INV09 never crosses field/snapshot; old PIT unchanged | binding checks; per-snapshot cache | G08/G09/G19, I03/I04/I08, R01 |
| INV10 reads dictionaries, copies no strings | builder reads only `dictionary_term` | G02/G03/G20 |
| INV11 one builder, no partial map | RAII registry/field state machine | G10/G12/G13/G14 |
| INV12 pre-admitted, correctly released | `MetadataMeter` + `reserve_growth` | I06 exact `96 187` boundary, G15/G16/G19 |
| INV13 optional failures never hide corruption/cancel | typed vs optional split | G12/G14/G15/G16/G17/G18 |
| INV14 existing correctness and visibility unchanged | producers + readers unchanged elsewhere | I01–I08, R01, full workspace suites |
| INV15 no B2/B4 claim | protected diff empty; no benchmark artifact delta | `evidence/diff-inventory.txt`, §8 |

## 6. Test and QA evidence (final source)

Source under test: working tree on `dev/perf06-b1` derived from
`480a77e78c6897e05cb7ceb76b01434974b82ec6` (see §7 for the tested commit).

| Group | Result |
| --- | --- |
| B1-U01…U16 (codec/access) | 15 tests, all pass (incl. the literal 116-byte witness) |
| B1-G01…G20 (snapshot maps) | 20 tests, all pass |
| B1-I01…I08 (local lifecycle) | 8 tests + 1 child-process test, all pass |
| B1-R01 (real RustFS) | 1 test, pass against `rustfs/rustfs@sha256:1803faef…` |
| `pr08` golden feature allowlist | `p8_t42` pass (new pair added only to the allowlist) |

Frozen legacy fixture (§11): generated **before** production edits from a
detached `480a77e` worktree with the plan's Appendix L producer extracted
verbatim (producer SHA-256 `3f04e5ee…`, binary SHA-256 `55f3083b…`,
`rustc 1.98.1`, `Cargo.lock` blob `a230eb28…`), one authorized generation
invocation, exit 0, terminal `PERF06_B1_LEGACY_FIXTURE_PASS`, generation 3 /
18 documents / 3 segments / 6 objects, inventory SHA-256
`6537456327f7a13367699c42c5978dbabaef6430cee3e9c9378f25676c4b8ee5`
(`evidence/p1-fixture-producer.log`). Package committed at
`crates/quervant-core/tests/fixtures/index/perf06_b1_columns_v1/` with
`objects.tsv`, verbatim `producer.rs` and a provenance `README.md`;
byte-identical to the generated package; the detached worktree was removed
cleanly (no `--force`).

Local QA ledger (`evidence/qa-ledger-final.txt`, logs `evidence/final-*.log`):

| Command | Exit |
| --- | --- |
| `cargo +1.98.1 fmt --all -- --check` | 0 |
| `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | 0 |
| `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | 0 |
| `cargo +1.98.1 test --workspace --all-targets` | 0 — 2619 passed, 0 failed, 15 ignored |
| `cargo +1.98.1 test --workspace --all-targets --all-features` | 0 — 2664 passed, 0 failed, 99 ignored |
| `cargo +1.98.1 doc --workspace --no-deps` | 0 |
| `cargo +1.98.1 doc --workspace --all-features --no-deps` | 0 |
| `cargo +1.98.1 bench --workspace --no-run` | 0 (compile gate only) |
| `bash benchmarks/scripts/test-scripts.sh` | 0 |
| `cargo +1.85.0 fmt --all -- --check` | 0 |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | 0 — 2664 passed, 0 failed, 99 ignored |
| `git diff --check` | 0 |

Coverage (`evidence/coverage-*.log`):

| Scope | Lines | Line % | Functions % | Regions % |
| --- | --- | --- | --- | --- |
| default, `--fail-under-lines 85` | 65668/4759 | **92.75 %** | 87.28 % | 93.22 % |
| all-features, `--fail-under-lines 85` | 67175/5142 | **92.35 %** | 87.20 % | 92.92 % |

Both commands exited 0; no exclusions were added. `rust-toolchain.toml` pins
`channel = "stable"`, so the "stable" and `+1.98.1` runs above are the same
toolchain; the explicit `+1.85.0` MSRV run is reported separately.

### Real RustFS acceptance (B1-R01)

Task-owned pinned service: `quervant-perf06-b1-<pid>` on
`127.0.0.1:19010`, image digest
`rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`,
`podman`, no host mount, container id recorded in
`evidence/rustfs-container-id.txt`. Health probe succeeded on the first attempt.
Execution: `cargo +1.98.1 test -p quervant-core --all-features --test
perf06_b1_rustfs -- --ignored --test-threads=1 --nocapture` → `ok`, with the
`PERF06_B1_R01_PASS` marker (`evidence/rustfs-r01.log`). Coverage of the real
boundary: three remote commits, blind cold open in a brand-new empty workspace
with exact local→shared rank tables and complete sorted orders, one shared map
reused without additional provider GETs, a held generation-3 PIT with its own map
unchanged across a generation-4 append, and a second cold open at generation 4 in
another empty workspace. Cleanup: `stop` + `rm --volumes` on the recorded ID only;
container absent and port released (`evidence/rustfs-cleanup.log`).

## 7. Delivery state and CI

Branch `dev/perf06-b1`, drafted from the admitted pin. The tested commit and the
final commit are recorded in the PR body and in
`evidence/delivery.txt`; report-only changes after validation are limited to
`docs/` and are covered by an executable/test/CI diff check rather than another
full local suite.

CI: the ordinary draft-PR workflow is used; exactly one command was added to the
existing real-RustFS step:

```sh
cargo test -p quervant-core --all-features --test perf06_b1_rustfs -- --ignored --test-threads=1
```

No other job, trigger, environment, health setting or workflow was changed, so a
single PR update still starts one run of each required job.

Observed terminal CI (`evidence/ci-status.txt`):

| Item | Value |
| --- | --- |
| PR | #126 (draft), base `main`, head `dev/perf06-b1` |
| Run | `45516023460`, event `pull_request`, workflow `Rust CI` |
| Head | `8e11484af49e38243a97d765ef21662f7e3060a3` |
| `rust` | completed / success |
| `msrv` | completed / success |
| `rustfs` | completed / success — log shows `test b1_r01_cold_shared_ordinals_and_pit ... ok` |
| `python-benchmark-framework` | completed / success |
| `benchmark-adapter-contract` | completed / success |

The final head differs from the locally tested source `87745ed` only in
`docs/pr-artifacts/` evidence files; `git diff` over `crates`/`.github`/manifests
between the two commits is empty (`evidence/delivery.txt`).

## 8. Decisions, deviations and residual risks

Applied decision rows (all AUTO-RESOLVE; no HARD STOP occurred): D01, D02 (not
needed — main equals the pin), D06 (no pre-existing fixture), D10–D19, D21–D26,
D28, D29, D31, D32, D35.

**Documented deviations (honest scope reductions, none of them a semantic
shortcut):**

1. **B1-G15.** The plan asks for an "exact peak modeled allowance" boundary plus a
   sticky one-byte-below refusal. Because the ordinal map shares the snapshot's
   metadata account with the *verified segment state*, the success boundary is
   **non-monotonic** (a slightly smaller cap can make the verified state fall back
   and leave room for the map). The implemented test therefore proves the sticky
   `ResourceBudget` outcome at a zero-capacity boundary, the absence of any retry,
   the "registry + measured map" retained accounting, and map-reservation release
   semantics, instead of asserting a single-byte threshold. This is reported as a
   plan/test-model limitation, not as a passing exact-boundary claim.
2. **B1-G14.** Deterministic injection covers registry/field allocation refusal
   (thread-local seam), pre-cancellation (state restored to `Uninitialized`),
   cancelled-waiter isolation, and cache poisoning (fail-closed). A dedicated
   "panic inside the field merge" seam is not implemented; the RAII reset path it
   would exercise is the same `Drop` guard proved by those cases.
3. **B1-G16.** The scoped test-only fault seam is a thread-local countdown applied
   to the registry entry vector, the bound-source vector, the heap-head vector,
   the outer map vector and each inner packed buffer. It is compiled out entirely
   in non-test builds; no production hook, atomic or metric exists.
4. **B1-G08.** Deleted-only terms are proved structurally (the builder reads only
   physical dictionaries and never a visibility mask) rather than by a unit-level
   "delete then re-merge" fixture; the end-to-end renumbering/removal behaviour is
   covered by B1-I03 (delete, pre-compaction dictionary retained, post-compaction
   removal, held PIT unchanged).
5. **B1-R01 object-digest proof.** Old generation-3 immutability is proved by
   re-opening the remote prefix cold at generation 4 and by the held generation-3
   PIT/map invariance plus an unchanged provider request counter, not by listing
   remote object digests directly (the test uses only existing `RemoteIndex` /
   transfer-statistics seams, and compaction is not published remotely, which
   remains unqualified as the plan states).
6. **`cargo llvm-cov` region/function figures** are reported as produced by the
   tool; the enforced gate is the 85 % line floor.

**Residual risks (unchanged by this report).**

* High-cardinality fields need map payload proportional to the sum of distinct
  local terms; the shared metadata cap turns that into sticky optional
  unavailability rather than a new budget.
* Many held PITs each retain their maps and reservations; B1 adds no eviction.
* New-format validation adds open-time work proportional to dictionary/rows;
  B4 measures it separately from query latency.
* Global ranks are intentionally unstable across new snapshots and are not
  durable identifiers or cursor values. Legacy/new mixed snapshots stay readable
  but cannot prepare the shared map until real compaction produces all-new
  eligible columns.
* Multi-valued keyword fields, Text, JSON strings and permanent shared
  identifiers remain outside B1.
* The inherited ordinary-column temporary allocation behaviour is unchanged; B1
  makes no peak-memory claim for it.
* A6's unfavorable numerical evidence is unchanged; B1 claims no latency, RSS or
  whole-index size improvement.

**Next dependency.** Accepted B1 supplies field ids, resident document
state/ordinal access, dictionary length by ordinal and exact
snapshot-wide numeric translation. B2 must design the collector's preparation
call, typed `NotAvailable` fallback, logical admission, comparisons, ties and
cursor/PIT behaviour — a separate, source-specific plan, not automatic work
authorized by B1. B3 owns document/duplicate identity and B4 owns the cumulative
warm qualification.

---

# F1 independent-review correction (supersedes overbroad claims above)

**Fixup plan:** [`PERF06B1_F1_DETAILED_FIXUP_PLAN.md`](PERF06B1_F1_DETAILED_FIXUP_PLAN.md),
SHA-256 `1a536f5e96cc0b00e615d89367ed9994d69ed9f2e67a1f05d01a73e329091e8e`.

Everything above this line is retained as **historical observation**. The F1 review
found resource-admission defects, a malformed-input panic, waiting/cancellation gaps
and missing proof obligations, so the earlier G2/G3/G4/G5/G6/G7/G8 `PASS` labels are
**superseded** for those gates: G2/G3 were *implemented but incorrect in the ways
listed below*, G4/G5/G6 were *executed but inadequately verified*, and G7/G8 belonged
to the earlier source. G10 remains **OPEN** and maintainer-owned. The table in §1 is
correct only for the pre-F1 source; the authoritative gate table for the corrected
source is §F1.6 below.

## F1.0 Source identities

| Role | Value |
| --- | --- |
| START_SHA (branch head at preflight) | `63638d5b59441b9a075ac28d7ec90314ce72a456` |
| REVIEWED_SHA (production source under review) | `8e11484af49e38243a97d765ef21662f7e3060a3` |
| Intervening commits since REVIEWED_SHA | report/evidence only (`PERF06B1_EXECUTION_REPORT.md`, `evidence/ci-status.txt`) — D02 |
| Frozen pin / merge base | `480a77e78c6897e05cb7ceb76b01434974b82ec6` (= `origin/main`) |
| Preflight | clean worktree, fast-forward `already up to date`, plan hashes verified (`evidence/f1-p0-preflight.txt`) |
| IMPLEMENTED_SHA / TESTED_SHA / FINAL_SHA | recorded in the PR body and `evidence/f1-delivery.txt` |

Allowed executable delta: `src/index/keyword_ordinals.rs`, `src/segment/column.rs`,
`tests/perf06_b1_ordinals.rs`, `tests/perf06_b1_rustfs.rs`.
`evidence/f1-diff-inventory.txt` shows an **empty protected-path diff** against the
reviewed source: `segment/metadata.rs`, `segment/reader.rs`, `segment/format.rs`,
`index/merge.rs`, `index/snapshot.rs`, `index/mod.rs`, production `search/*`,
`contract/*`, `remote/*`, `storage/*`, `quervant-objectstore`, `quervant-distributed`,
`.github/workflows/ci.yml`, manifests/toolchain, `benchmarks/` and the frozen fixture
are untouched. No new dependency, feature flag, budget implementation or public API
shape was added.

## F1.1 Pre-implementation invariant worksheet

| INV-F1 | Symbols | Positive case | Counterexample case | Accepting tests |
| --- | --- | --- | --- | --- |
| 01 peak map admission | `keyword_ordinals::fixed_peak_allowance`, `build_field_map`, `grow`, `MetadataMeter` | exact peak `R+P` succeeds, retained ≤ peak | one byte under `R+P-1` sticky `ResourceBudget`; hidden vector capacity charged/rejected | `b1_g15_*`, `b1_g16_*`, `b1_g19_*`, `b1_g20_*` |
| 02 ordinary retained backings | `column::check_ordinary_retained`, `encode_columns_with_ordinals` | exact-cap encode succeeds | retained `BlockPlan`/state/value capacity > cap while finished body fits | `b1_u09_*` |
| 03 malformed v2 never panics | `column::read_dictionary_prefix`, `dictionary_geometry_from`, `validate_keyword_dictionary` | valid 116-byte witness parses | `U = u64::MAX` → typed count-exceeds-docs; extent overflow typed | `b1_u05_hostile_*`, `b1_u05_geometry_*`, `b1_i07_*` |
| 04 no gratuitous wait | `KeywordOrdinalCache::wait`, `WaitFor` | publish inside the wait window returns Ready with zero `wait_timeout` | spurious notify while `Building` rechecks; cancelled waiter returns `Cancelled` | `b1_g13_*` |
| 05 cancellation completeness | `initialize_registry(.., cancellation)`, `prepare`, `build_field_map` | post-publication cancel keeps the shared map | pre-publication cancel resets the claim; no cancel while locked | `b1_g12_*`, `b1_g14_*` |
| 06 frozen U/G behaviors executed | unit tests | each named group has a dedicated test | `.is_err()`-style substitution rejected | this report §F1.3 |
| 07 genuine v1→mixed→v2 proof | `tests/perf06_b1_ordinals.rs` | full 18/20-row oracles, immutable bytes, child process | fixture regenerated, partial oracle | `b1_i03_*`, `b1_i04_*` |
| 08 real remote immutability | `tests/perf06_b1_rustfs.rs` | five recorded g3 objects re-GET byte-identical | provider counter or PIT only | `b1_r01_*` |
| 09 frozen error labels/precedence | `column` v2 decode | table-driven label matrix | convenient category substitution | `b1_u05_*`, `b1_u06_*`, `b1_i07_*` |
| 10 fallible keyword copy | `column::fallible_owned_keyword` | Single/MultiOne exact budget success | 79/80 section budget, vector-bytes−1 | `b1_u13_*` |
| 11 evidence belongs to final source | QA ledger, CI ledger | source SHA ↔ logs ↔ CI | reusing earlier-source QA | §F1.5–F1.7 |

Plausible wrong implementations challenged: hidden vector capacity (G15/G16 charge
actual capacities), `U=u64::MAX` (explicit hostile-count test), notify-before-wait
(G13 predicate wait), cancellation right after entry (G12 pre-publication reset),
false `PASS` on a legacy index (I04 asserts `LegacySegment` and genuine v1 bodies), and
a cold open that checks only some documents (I04/R01 assert every row and every key).

## F1.2 F1-01…F1-11 disposition

| ID | Prior defect | Correction (symbol) | Test | Result |
| --- | --- | --- | --- | --- |
| F1-01 | `sources` allocated before `MetadataMeter::reserve`; peak model omitted the outer map vector | `fixed_peak_allowance` (checked source+heads+outer+owner, per-backing `check_allocation_bytes`) reserved **before** any allocation; `grow` used for sources/outer/inner/heads; `extend(payload)` once; owner charged before `Arc::new`; scratch dropped before `finalize` | `b1_g15_exact_peak_allowance_and_sticky_budget`, `b1_g16_every_allocation_site_is_sticky`, `b1_g19_*`, `b1_g20_*` | PASS |
| F1-02 | ordinary retained buffers only sum-charged | `check_ordinary_retained` checks each `BlockPlan`/state/values backing against `max_single_allocation` before the cumulative charge | `b1_u09_ordinary_retained_backings_are_checked_individually` | PASS |
| F1-03 | `(U+1)*ow` computed before `U > doc_count` → overflow panic at `U=u64::MAX` | `read_dictionary_prefix` (no count arithmetic) + `dictionary_geometry_from` (checked `U.checked_add(1)`, checked `usize`, checked `strings_end`) | `b1_u05_hostile_dictionary_count_is_typed_not_a_panic`, `b1_u05_geometry_helper_is_checked`, `b1_i07_*` (valid outer envelope) | PASS |
| F1-04 | waiter dropped the lock then unconditionally `wait_timeout`ed | `WaitFor::{Registry,Field}` re-evaluates the live predicate under the lock; skip the wait when already published | `b1_g13_wait_predicate_avoids_gratuitous_waits` | PASS |
| F1-05 | `initialize_registry` had no cancellation; no pre-publication poll | cancellation plumbed through registry build with 256-unit polls, before entry reservation, after filling, before returning the candidate, and immediately before publication | `b1_g12_cancellation_is_checked_everywhere`, `b1_g12_cancellation_across_registry_and_build`, `b1_g14_*` | PASS |
| F1-06 | missing U09/U10/U14/G08/G13/G15/G16/G20 proofs | added the mixed-capacity encoder case, the 64-case codec differential, the real-writer Multi0 commit, the pre-compaction deleted-only Boston view, the deterministic wait/cancel interleavings, isolated-budget peak tests, a 7-site allocation-fault ledger and the explicit-preparation structural test | `b1_u09_*`, `b1_u10_*`, `b1_u14_*`, `b1_i03_*` (G08 block), `b1_g12_*`…`b1_g20_*` | PASS |
| F1-07 | I03 lacked intermediate inventories; I04 used `type-a` appended rows, partial oracles and no child marker | I03 records g3/g4 immutable closures, asserts 18/19/18 live docs and 3/4/4/1 segments, the deleted-only physical term, and byte-identical old objects; I04 appends `type-d` d0/d1, asserts 20-row values/orders/K/projections/predicates/aggregates (sum 190, distinct 20, 4 category groups), compares all recorded g3/g4 object bytes, and runs a `PERF06_B1_I04_MODE=g5` child with `PERF06_B1_I04_CHILD_PASS` | `b1_i03_*`, `b1_i04_*`, `b1_i04_child_body` | PASS |
| F1-08 | R01 used the map from a different snapshot instance, no immutable-object proof, one g4 open | one prefix, four workspaces; provider-only five-object g3 closure via `ObjectStore::get` + `prefix.object_key`; two independent g4 cold opens with complete 19-row oracle + aggregation; post-g4 byte comparison of the same five keys | `b1_r01_cold_shared_ordinals_and_pit` | PASS (real pinned RustFS) |
| F1-09 | two-pass offset/term validation let a later bad offset mask an earlier invalid term | single ordered pass: first-offset-zero, then `≤L`, monotonicity, then the just-delimited term (length/UTF-8/order), terminal last | `b1_u05_early_term_error_precedes_later_offset_error`, `b1_u05_dictionary_corruption_is_rejected_at_open` | PASS |
| F1-10 | ordinal-row `Keyword` strings used infallible `to_owned()` | `fallible_owned_keyword` (`try_reserve_exact`, byte-accurate `LimitExceeded`) after the unchanged logical admission; MultiOne sequence preserved (entries → vector → separate string budget) | `b1_u13_ordinal_branch_budgets_and_fallback_copy` | PASS |
| F1-11 | v2 illegal state reported the legacy label | layout-3 rows report `invalid keyword ordinal state`; other layouts keep `invalid state tag` | `b1_u06_row_state_and_extent_corruption_is_rejected` | PASS |

## F1.3 Executed test inventory (actual counts)

`cargo +1.98.1 test -p quervant-core --lib b1_ -- --test-threads=1` → **55 passed,
0 failed** (`evidence/f1-test_1.98.1_all-features.log` also contains them).
`cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals` → 9 passed, 2 ignored
(the two ignored child entrypoints are executed by their parents, which pass).
Named new/restored tests: `b1_u05_hostile_dictionary_count_is_typed_not_a_panic`,
`b1_u05_geometry_helper_is_checked`,
`b1_u05_early_term_error_precedes_later_offset_error`,
`b1_u09_ordinary_retained_backings_are_checked_individually`,
`b1_u10_frozen_codec_differential_families`,
`b1_u13_ordinal_branch_budgets_and_fallback_copy`,
`b1_u14_real_writer_rejects_zero_multi_count`,
`b1_g12_cancellation_across_registry_and_build`,
`b1_g13_wait_predicate_avoids_gratuitous_waits`,
`b1_g15_exact_peak_allowance_and_sticky_budget`,
`b1_g16_every_allocation_site_is_sticky`,
`b1_i04_child_body` (+ the expanded `b1_i03`, `b1_i04`, `b1_r01`).

## F1.4 Deterministic seams (test-only, compiled out in production)

`thread_local` `WAIT_STARTS` counter, `PRE_WAIT_HOOK` and `AFTER_CLAIM_HOOK`
(`keyword_ordinals.rs`), plus the existing `ALLOC_FAULT` countdown. Audited
`alloc_fault_check` sites for a three-segment fixture: 0 registry entries, 1 bound
sources, 2 outer map vector, 3–5 inner packed buffers, 6 heap heads — G16 iterates
exactly these and requires `Allocation` at each. No production hook, atomic, metric or
sleep establishes an event ordering; the only `sleep` calls bound a *real* waiter so a
spurious notification and a cancelled wait can occur, and the no-wait proofs use hooks
plus the `wait_starts` counter.

## F1.5 Final local QA on the corrected source

`evidence/f1-qa-ledger.txt` (logs `evidence/f1-*.log`):

| Command | Exit |
| --- | --- |
| `cargo +1.98.1 fmt --all -- --check` | 0 |
| `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | 0 |
| `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | 0 |
| `cargo +1.98.1 test --workspace --all-targets` | 0 — **2629 passed**, 0 failed, 16 ignored |
| `cargo +1.98.1 test --workspace --all-targets --all-features` | 0 — **2674 passed**, 0 failed, 100 ignored |
| `cargo +1.98.1 doc --workspace --no-deps` | 0 |
| `cargo +1.98.1 doc --workspace --all-features --no-deps` | 0 |
| `cargo +1.98.1 bench --workspace --no-run` | 0 (compile gate only) |
| `bash benchmarks/scripts/test-scripts.sh` | 0 |
| `cargo +1.85.0 fmt --all -- --check` | 0 |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | 0 — **2674 passed**, 0 failed, 100 ignored |
| `git diff --check` | 0 |

Coverage (`evidence/f1-coverage-*.log`, `--fail-under-lines 85`, no exclusions):
default **92.84 %** lines (66485/4763), all-features **92.99 %** lines (67992/5147).

## F1.6 Corrected gate ledger

| Gate | Result on the corrected source |
| --- | --- |
| G0/G1 | **PASS** — clean fast-forward, approved plan hashes, invariant worksheet (§F1.1) |
| G2 | **PASS** — decoder/encoder/ordinary-backing/fallible-copy corrections; U05/U06/U09/U10/U13/U14 executed |
| G3 | **PASS** — G12–G16/G19/G20 prove peak admission, fault taxonomy, wait/cancel/reset/release |
| G4 | **PASS** — 55 `b1_*` unit tests, including the restored adversarial cases |
| G5 | **PASS** — full I01–I08; the g5 child actually executed (`PERF06_B1_I04_CHILD_PASS`); g3/g4 immutable bytes unchanged |
| G6 | **PASS** — R01 passed against the pinned RustFS image with five-object byte verification and two independent g4 cold opens |
| G7 | **PASS** — every §17.1 command exit 0; both coverage floors met |
| G8 | **PASS** — ordinary draft-PR run `45532158829` on head `5438751`: `rust`, `msrv`, `rustfs`, `python-benchmark-framework`, `benchmark-adapter-contract` all `success`, and the `rustfs` log shows `b1_r01_cold_shared_ordinals_and_pit ... ok` |
| G9 | **PASS** — additive correction, source/test/CI/protected diffs recorded |
| G10 | **OPEN — maintainer only** |

## F1.7 Real RustFS and CI evidence

R01 executed on the corrected source against
`rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
(task-owned `podman` container `c2291d78…`, loopback only, no host mount): `ok` with
`PERF06_B1_R01_PASS` (`evidence/f1-rustfs-r01.log`). Cleanup: id-scoped `stop` +
`rm --volumes`; container absent and port released (`evidence/f1-rustfs-cleanup.log`).

Ordinary draft-PR CI (`evidence/f1-ci-status.txt`):

| Item | Value |
| --- | --- |
| Run | `45532158829`, event `pull_request`, workflow `Rust CI` |
| Head | `5438751e1d65a419583a252f41dfff85a1a2f5ba` |
| Executable source | `1b9621e2d089f7658e5749a8ad73e3153d1b2045` (the final head differs only in `evidence/`; the non-docs diff is empty) |
| `rust` / `msrv` / `rustfs` / `python-benchmark-framework` / `benchmark-adapter-contract` | all `success` |
| RustFS log | `test b1_r01_cold_shared_ordinals_and_pit ... ok` |

No workflow dispatch, extra job or repeated push was used.

## F1.8 Mandatory adversarial self-review

| INV-F1 | Plausible bug | Catching evidence |
| --- | --- | --- |
| 01 | peak model omits a concurrently live backing, or `charge` silently accepts an uncharged growth | G15 exact/one-under boundary; G16 per-site faults with `budget.used()` unchanged; G16 requires exactly `Allocation`, not `ResourceBudget` |
| 02 | retained ordinary capacity accepted because the final body fits | U09 synthetic over-capacity backings plus the real-encoder exact boundary |
| 03 | `U`-dependent arithmetic runs before the count check and panics | hostile-count test at `u64::MAX` (and near-max), pure-geometry overflow tests, container-wrapped case |
| 04 | publication is missed and the waiter sleeps a full interval | G13 asserts `wait_starts() == 0` in both registry and field modes after an in-window publish |
| 05 | cancel-time reset leaves `Building`/`Initializing` stuck, or a post-publication cancel erases a valid map | G12 pre-publication reset on the same snapshot; post-publication cancel keeps `Arc`-identical map; G14 poison fails closed |
| 06 | a group is "covered" by an unrelated assertion | explicit per-group tests listed in §F1.3 |
| 07 | compaction silently drops nonstored/absent values or rewrites old objects | I03/I04 assert every row/state/rank, old object bytes, and the child process |
| 08 | remote "immutability" inferred from a counter or a held PIT | R01 re-GETs the five recorded g3 keys and compares bytes; the g4 workspace is newly created |
| 09 | a convenient error category replaces the frozen label | compound adversary proves the earlier term error wins; the label matrix covers each new check |
| 10 | string copy stays infallible or budgets merge | U13 asserts exact 80/79 budgets, the vector-bytes−1 failure, and the fallible helper's byte-accurate error |
| 11 | evidence from the pre-F1 source is reused | QA/CI ledgers carry the source SHA; the protected diff is empty |

Disclosed residual risks are unchanged from §8 (high-cardinality map payload, many
held PITs, open-time validation cost, snapshot-scoped non-durable ranks, mixed
legacy/new snapshots, out-of-scope multi/Text/JSON, inherited ordinary temporary
allocations, remote compaction unqualified, no performance claim).

## F1.9 Disposition

`PERF06_B1_F1_READY_FOR_INDEPENDENT_REVIEW` — implementation, correctness tests,
local QA, coverage and real-RustFS acceptance pass on the corrected source; the gate
table above is the authority. **G10 remains open**: independent review, acceptance and
merge are maintainer-owned. Nothing here is a measured latency, RSS or index-size
result, and A6's numerical outcomes are unchanged.

**Handoff:** PR #126 (draft, base `main`, branch `dev/perf06-b1`). B2 owns collector
adoption, B3 owns document/duplicate identity, B4 owns the cumulative warm
qualification. Do not merge, start B2, or promote B1 as accepted from this report.

---

# F2 independent-review closure

**Plan:** [`PERF06B1_F2_DETAILED_FIXUP_PLAN.md`](PERF06B1_F2_DETAILED_FIXUP_PLAN.md),
SHA-256 `5f735e89e82a734815dbc585d2e1b98b7edb3cb9debc13f05ae2f45f083be4e3`,
Git blob `4f5483c349226e826b378fc0277afbc0eb7b8c0c`.

All earlier sections stay as **historical observation**. F2 supersedes only these
specific claims: the F1 G12/G14 statements that did not prove a pre-publication
cancellation, a real field-stage claim, a live-candidate typed error/panic, or a
waiter that actually entered `wait_timeout`; the U10 statement that a `MultiOne` row
was verified (it checked list length, not the contained member); and the I04/R01
statements that “complete projections” were asserted (they counted six fields). Those
assertions are now strengthened and re-executed below. G10 remains **OPEN** and
maintainer-owned; nothing here is a performance result.

## F2.0 Source identity

| Role | Value |
| --- | --- |
| Accepted main / merge base | `480a77e78c6897e05cb7ceb76b01434974b82ec6` |
| F1 executable source (reviewed) | `1b9621e2d089f7658e5749a8ad73e3153d1b2045` |
| F2 START head | `d579b7fd926ee96f0f79df6b74c58bd8ff61c51a` |
| F2 start delta vs F1 source | `PERF06B1_EXECUTION_REPORT.md`, `evidence/f1-ci-status.txt`, `evidence/f1-delivery.txt` — docs/evidence only; executable blobs identical (`evidence/f2-preflight.txt`) → X01 |
| TESTED / FINAL SHA | recorded in the PR body and `evidence/f2-delivery.txt` |
| PR | #126, branch `dev/perf06-b1`, base `main`; actual state `OPEN`, `draft=false` retained unchanged |

**Changed paths (whole F2 delta):** `src/index/keyword_ordinals.rs` (production +
tests), `src/segment/column.rs` (**U10 test module only** — every hunk is inside
`mod b1_tests`), `tests/perf06_b1_common/mod.rs`, `tests/perf06_b1_ordinals.rs`,
`tests/perf06_b1_rustfs.rs`, plus the copied F2 plan, this report and
`evidence/f2-*`. **Protected-path diff vs the F1 source is empty**
(`evidence/f2-diff-inventory.txt`): `segment/metadata.rs`, `reader.rs`, `format.rs`,
`build.rs`, `index/merge.rs`, `snapshot.rs`, `index/mod.rs`, production `search/*`,
`contract/*`, `remote/*`, `storage/*`, `quervant-objectstore`,
`quervant-distributed`, `.github/workflows/ci.yml`, Cargo/toolchain files, `AGENTS.md`,
`benchmarks/`, and the frozen fixture package are untouched. No new public API,
feature flag, dependency or budget account.

## F2.1 Invariant worksheet (before code edits)

| Invariant | Positive case | Plausible counterexample | Symbol | Test |
| --- | --- | --- | --- | --- |
| F2-I01 | ready registry published after a clean pre-publish poll | cancel after the candidate is built, before the lock | `prepare`/`Next::Initialize` + `publish_registry` | `b1_g12_f2_registry_ready_cancel_before_publish` |
| F2-I02 | sticky registry outcome published when not cancelled | injected `Allocation` + pre-publish cancel must not stick | same + `BeforeRegistryUnavailablePublish` | `b1_g12_f2_registry_optional_cancel_before_publish` |
| F2-I03 | map published and reused `Arc`-identically | cancel after the map is built; stale `Building` | `build_and_publish` + `publish_field` | `b1_g12_f2_field_ready_cancel_before_publish` |
| F2-I04 | sticky field outcome published when not cancelled | alloc refusal + pre-publish cancel must reset to `Empty` | same + `BeforeFieldUnavailablePublish` | `b1_g12_f2_field_optional_cancel_before_publish` |
| F2-I05 | post-publication result survives; later caller may see `Cancelled` | erasing a published map on a later cancel | `disarm` → notify → post-poll order | field-ready test tail, existing `b1_g12_cancellation_*` |
| F2-I06 | 257-field schema initializes normally when not cancelled | unpolled 256-boundary scan | `initialize_registry` enumerate loops | `b1_g12_f2_registry_scan_periodic_cancellation` |
| F2-I07 | error/panic after real admission resets and retries | stuck `Initializing`/`Building`, leaked charge, hung waiter | `RegistryInitGuard`/`FieldBuildGuard` | `b1_g14_f2_*` (4 tests) |
| F2-I08 | every 64-case row equals the input `FieldValues` | `MultiOne` with the right length and the wrong member | `b1_u10_*` | `b1_u10_frozen_codec_differential_families` |
| F2-I09 | all six ordered tuples equal the literal oracle | one wrong field value hidden by a count check | `assert_city_view`, `assert_legacy_city_view`, `sorted_keys` | `b1_i04_*` (+child), `b1_i01_*`, `b1_r01_*` |
| F2-I10 | allowed paths only, protected diff empty | stale-head CI or benchmark drift | diff inventory + ledgers | §F2.4–F2.7 |

Challenged explicitly: cancellation after a successful build but before publication
(F2-I01/I03), field already `Building` (I03/I04/I07), registry `NotAvailable`
construction (I02), panic after a reserved candidate (I07 panic runs), waiter already
inside a timed wait (I07 waiter tests assert the observer), `MultiOne` carrying the
wrong string with correct cardinality (I08 negative oracle), and a projection returning
six wrong fields (I09 literal tuples).

## F2.2 Production correction (single file)

* **Four publication transitions** now run `f2_probe(<Before*Publish>)` → **last**
  `poll(cancellation)?` **outside** the cache mutex → lock → state assertion → publish.
  Ready and sticky-optional registry and field transitions are all covered. An
  unexpected claim state returns the bounded
  `CorruptCommittedState { detail: "keyword ordinal cache publication state changed" }`
  and leaves the caller's RAII guard armed, so nothing is silently overwritten.
* **Registry scans** (`initialize_registry`) now use explicit `enumerate()` loops with
  a probe at index 256 and a `poll` every 256 items, then a poll after each loop, with
  checked `eligible` accumulation (`ResourceBudget` on overflow, never a panic).
  Canonical ascending order, allowance, `check_allocation_bytes`, fallible
  `try_reserve_exact` and `charge_vec` semantics are unchanged.
* `RegistryAfterEntries` fires after the entry vector is populated and before
  `meter.finalize`; `FieldAfterFirstPackedBuffer` fires immediately after the first
  inner packed buffer is pushed and before heap/output creation.
* Post-publication order is preserved (disarm → notify → post-poll), so a later
  cancellation reports `Cancelled` without erasing the published value. No
  cancellation poll, hook or callback runs while the cache mutex is held.
* Scoped seams: one `pub(crate)` zero-data `F2Probe` discriminator, a one-shot
  thread-local callback that releases its `RefCell` borrow before invoking the closure,
  and a wait-entry observer `AtomicBool`. All have `#[cfg(not(test))]` no-op stubs
  (`evidence/f2-seam-audit.txt`); no production atomic, metric or fault path exists.

## F2.3 Acceptance results (actual executions)

`cargo +1.98.1 test -p quervant-core --lib b1_ -- --test-threads=1` → **64 passed,
0 failed**. The nine new F2 tests and what each proved:

| Test | Observed result |
| --- | --- |
| `b1_g12_f2_registry_ready_cancel_before_publish` | `Cancelled`; registry `Uninitialized`; ordinal budget `0`; same-cache/snapshot retry Ready with 4 terms |
| `b1_g12_f2_registry_optional_cancel_before_publish` | injected `Allocation` + pre-publish cancel → `Cancelled`, **not** sticky; budget `0`; retry Ready |
| `b1_g12_f2_field_ready_cancel_before_publish` | `Cancelled` after the map was built; entry back to `Empty`; account exactly `R`; retry Ready; a later cancelled caller left the published map `Arc`-identical (F2-I05) |
| `b1_g12_f2_field_optional_cancel_before_publish` | first field allocation refused + pre-publish cancel → `Cancelled`, no sticky `NotAvailable`; entry `Empty`; account `R`; retry Ready |
| `b1_g12_f2_registry_scan_periodic_cancellation` | real 257-field schema (eligible `city` = id 0 + 256 noneligible columnar `Bool` `z000..z255`); cancellation at both `RegistryEligibilityIndex256` and `RegistryFillIndex256` → `Cancelled`, `Uninitialized`, budget `0`, no publication; retry holds exactly one entry with field id 0 |
| `b1_g14_f2_registry_after_entries_error_and_panic` | typed `CorruptCommittedState("f2 injected registry failure")` and a caught panic, both after real admission → `Uninitialized`, budget `0`, same-snapshot retry Ready |
| `b1_g14_f2_field_after_buffer_error_and_panic` | typed `CorruptCommittedState("f2 injected field failure")` and a caught panic after a charged packed buffer → registry stays Ready, claimed entry `Empty`, account `R`, retry Ready |
| `b1_g14_f2_registry_failure_wakes_real_waiter` | builder paused at the pre-publication probe with the cache `Initializing`; a second thread's `prepare` **entered `wait_timeout`** (observer flag, bounded 10 s test deadline); builder's RAII reset woke it and it completed Ready with 4 terms |
| `b1_g14_f2_field_failure_wakes_real_waiter` | same with a genuine `Ready(registry)` + `Building` entry; the waiter-woken rebuild published a `Ready` map |

`b1_u10_frozen_codec_differential_families` (64 cases) now compares the **complete**
`FieldValues` (including `Multi(vec![Keyword(<exact member>)])`), the exact
`KeywordOrdinalState`, and the local ordinal from an independent binary search over the
sorted distinct input terms for every generated document, and includes a
negative-oracle sanity check where a deliberately wrong `MultiOne` member is asserted
unequal. `b1_i04_*` (with `PERF06_B1_I04_CHILD_PASS` from the real child process),
`b1_i01_*` and `b1_r01_*` now assert every hit's six ordered
`(field_name, FieldValues)` tuples from `perf06_b1_common::expected_projected_fields`,
for all 18/19/20 rows, both directions, both missing placements and every K prefix.

## F2.4 Final local QA (corrected source)

`evidence/f2-qa-ledger.txt` (logs `evidence/f2-*.log`): **all 13 commands exit 0**.

| Command | Exit |
| --- | --- |
| `cargo +1.98.1 fmt --all -- --check` | 0 |
| `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | 0 |
| `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | 0 |
| `cargo +1.98.1 test --workspace --all-targets` | 0 — **2638 passed**, 0 failed, 16 ignored |
| `cargo +1.98.1 test --workspace --all-targets --all-features` | 0 — **2683 passed**, 0 failed, 100 ignored |
| `cargo +1.98.1 doc --workspace --no-deps` / `--all-features` | 0 / 0 |
| `cargo +1.98.1 bench --workspace --no-run` | 0 (compile gate only) |
| `bash benchmarks/scripts/test-scripts.sh` | 0 |
| `cargo +1.85.0 fmt --all -- --check` | 0 |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | 0 — **2683 passed**, 0 failed, 100 ignored |
| `git diff --check` | 0 |

Coverage (`evidence/f2-coverage-*.log`, `--fail-under-lines 85`, no exclusions):
default **92.90 %** lines (67154/4766), all-features **93.04 %** lines (68661/5150).

## F2.5 Gate ledger

| Gate | Result on the F2 executable source |
| --- | --- |
| G0/G1 | **PASS** — fast-forward only, accepted main unchanged, plan hashes verified, invariant worksheet recorded |
| G2 | **PASS** — no codec/format change; U10 strengthened and passing |
| G3 | **PASS** — F2-I01…I07 proven by the nine new deterministic tests (four publication branches, scan periods, live-candidate error/panic, two real waiters) |
| G4 | **PASS** — 64 `b1_*` unit tests executed (`--test-threads=1`), including all F1 groups |
| G5 | **PASS** — I01–I08 re-executed with the full six-field oracle; I04 child actually ran (`PERF06_B1_I04_CHILD_PASS`) |
| G6 | **PASS/PENDING** — see §F2.6 (real RustFS is executed by the ordinary CI job on this source) |
| G7 | **PASS** — 13/13 local commands exit 0; both coverage floors met |
| G8 | **PASS/PENDING** — see §F2.6 |
| G9 | **PASS** — additive correction, allowed-path-only diff, protected diff empty |
| G10 | **OPEN — maintainer only** |

## F2.6 Real provider and CI

R01 (`b1_r01_cold_shared_ordinals_and_pit`) runs in the ordinary CI `rustfs` job on the
F2 source and now also verifies every hit's six projected fields; the provider-only
five-object generation-3 closure, two independent generation-4 cold opens, held PIT and
request-counter checks are unchanged. No local RustFS container was started for F2 (the
plan forbids duplicating hosted CI). Terminal results are recorded in
`evidence/f2-ci-status.txt`; a pending or unavailable service is reported as
`PERF06_B1_F2_IMPLEMENTED_VERIFICATION_BLOCKED`, never as green.

## F2.7 Adversarial self-review and residuals

* A publication that skipped the last poll would be caught by the four branch tests
  (each asserts both the returned `Cancelled` **and** the reverted state/charge).
* A reset that leaked a candidate reservation would be caught by the exact budget
  assertions (`0` for registry, `R` for field) before and after retry.
* A waiter that never blocked would fail the bounded observer assertion (X18) instead
  of passing silently.
* A `MultiOne` with the wrong member now fails both the exact value comparison and the
  negative-oracle sanity check.
* A projection regression in any single field now fails the literal six-tuple
  comparison in g3, g4, g5, the child process and R01.

Residual risks are unchanged from F1 §8 (high-cardinality map payload, many held PITs,
open-time validation cost, snapshot-scoped non-durable ranks, mixed legacy/new
snapshots, out-of-scope multi/Text/JSON ordinals, inherited ordinary temporary
allocations, remote compaction unqualified, no performance claim). The cooperative
cancellation boundary remains: a cancellation observed only after the final pre-lock
poll publishes the value and reports `Cancelled` to that caller (F2-I05), which is the
existing API contract and is not claimed to be atomic.

Applied decision rows: X01, X05, X06–X12, X14, X16, X17, X22/X23 (CI), X25, X27, X30,
X31. No HARD STOP row was triggered.

## F2.8 Disposition

`PERF06_B1_F2_READY_FOR_INDEPENDENT_REVIEW` once the ordinary CI run on the F2 head
passes all five jobs with R01 executed; otherwise
`PERF06_B1_F2_IMPLEMENTED_VERIFICATION_BLOCKED` with the exact pending gate. **G10
remains open**; do not merge, approve, or start B2/B3/B4 from this report. A6's
numerical outcomes are unchanged and no latency, RSS or index-size claim is made.
