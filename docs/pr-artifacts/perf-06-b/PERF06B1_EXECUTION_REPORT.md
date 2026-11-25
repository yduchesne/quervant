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
