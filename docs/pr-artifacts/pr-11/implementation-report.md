# PR 11 — Implementation report

**Branch:** `dev/json-indexing` (suggested plan branch `dev/json-path-retrieval`).
**Base:** `81b8a31713f79a0855210f89d8857c2e5cbb3802` (fresh `main` including merged PR 10 / #29 and
the docs-only PR #30 closure).

## Architecture summary

JSON source structure stays byte-semantically recoverable from the existing typed stored-value
codec; stored source is authoritative. Indexed JSON fields gain a separately versioned immutable
per-segment **path/leaf-value** section that accelerates exact document-level existential
predicates while retaining concrete array ancestry. No distributed, remote, manifest/`CURRENT`,
public-API, or major-format change was made.

- **Format:** required feature `FEATURE_JSON_PATHS = 0x0009` v1, `SectionKind::JsonPaths = 0x0010`.
  Exact body wire is documented in [docs/ARCHITECTURE.md](../../ARCHITECTURE.md#native-json-path-index-pr-11).
- **Extraction:** explicit bounded DFS over the in-memory `JsonValue` (root before children,
  canonical `(doc_id, concrete_path)` sort, duplicate-member rejection), with checked occurrence,
  path, member and byte accounting against `SegmentLimits`.
- **Reader:** one validated offset table `(field_id, doc_id, byte_offset, occurrence_count)` built in
  a single streaming pass at `SegmentReader::open`, cached for the reader lifetime, and reused across
  query evaluations. All counts/offsets use checked arithmetic; corruption is a typed `SegmentError`.
- **Execution:** `search/typed.rs` compiles the contract query once per request into a private
  `CompiledQuery` (JSON path segments resolved, JSON scalar canonicalized) and evaluates it through
  the existing document-level Boolean scan, charging occurrence and path-segment work to `ScanGuard`.
  The JSON accessor is opened once per segment, never per document. `indexed=false` is never silently
  source-scanned; a legacy stored field uses a bounded exact source fallback.
- **Compaction:** rebuilds the section from decoded source occurrences with physical-id remapping;
  it never copies section bytes and returns a typed error rather than dropping an indexed-but-not-stored
  legacy JSON field.

## Exact file list

Modified:

- `crates/quervant-core/src/contract/error.rs` — narrow `DocumentError::DuplicateJsonMember`.
- `crates/quervant-core/src/contract/schema.rs` — reject duplicate members in indexed JSON.
- `crates/quervant-core/src/segment/format.rs` — feature/section id + negotiation.
- `crates/quervant-core/src/segment/mod.rs` — module and narrow re-exports.
- `crates/quervant-core/src/segment/build.rs` — emit the section from physical documents.
- `crates/quervant-core/src/segment/reader.rs` — decode/cache directory and `open_json_paths`.
- `crates/quervant-core/src/index/merge.rs` — rebuild the section across a remap.
- `crates/quervant-core/src/search/typed.rs` — compile and execute JSON predicates.
- `docs/ARCHITECTURE.md` — exact section wire and semantics.

Added:

- `crates/quervant-core/src/segment/json_paths.rs` — codec, extractor, reader, scalar/path matchers.
- `crates/quervant-core/tests/pr11_common/mod.rs` — helpers and independent reference oracle.
- `crates/quervant-core/tests/pr11_json_paths.rs`
- `crates/quervant-core/tests/pr11_json_mutations.rs`
- `crates/quervant-core/tests/pr11_json_corruption.rs`
- `crates/quervant-core/tests/fixtures/segment/json_paths_golden.seg` — checked-in byte-frozen JSON-path segment fixture (regenerate with the `generate_json_paths_golden` ignored test).
- `crates/quervant-core/tests/pr11_json_properties.rs`
- `docs/pr-artifacts/pr-11/*` — this report and the correctness/validation/review artifacts.

Normally-unchanged files (`contract/value.rs`, `contract/query.rs` grammar/AST, stored/column codecs,
manifest/`CURRENT` wire, `.github/*`, `Cargo.toml`, RustFS/distributed crates, PR 5 golden fixture)
were left untouched.

## Wire compatibility

- No existing section id, feature id, format major/minor, stored-value encoding, column codec,
  manifest or `CURRENT` bytes changed.
- Segments without the feature open and behave exactly as before; malformed declared JSON sections
  fail closed; the PR 5 golden fixture is byte-unchanged (`pr11_json_properties::t24`) and the new
  JSON-path golden fixture is byte-frozen (SHA-256 asserted in `pr11_json_corruption`).

## Deferred work

- PR 14+: JSON-path sorting/projection, JSON scalar ranges, array membership beyond scalar equality,
  unified lexical+JSON planning, correlated array ancestor binding.
- PR 13: remote RustFS segment materialization and cold-reader integration; PR 11 tests the local
  `MemoryDirectory`/`FsDirectory` writer→commit→reader path only.

## Pull request

Suggested title: `feat(core): add bounded native JSON path indexing and predicates (PR 11)`.
