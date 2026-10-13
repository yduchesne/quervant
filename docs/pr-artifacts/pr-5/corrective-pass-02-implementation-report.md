# PR 5 corrective pass 02 implementation report

> **Branch:** `dev/segment-codecs`
> **Baseline:** `75134b84208df3eb1b08c7a1cf57baa121181bf2`
> **Status:** R5-I08/R5-I09 fixup complete; awaiting independent review. **No merge.**

## 1. Findings

| Finding | Severity | Fix |
|---|---|---|
| R5-I08 bounded Directory reads | HIGH | `read_all` now requests `min(remaining, max_read_bytes)` per call, fails closed before any read when `max_read_bytes == 0` for a nonempty object, advances only by actual returned bytes, and rejects `read > request` or offset overflow with typed errors. The whole-object buffer and full-file digest path are unchanged. |
| R5-I09 manifest retained memory | MEDIUM | `Manifest::decode` charges the `segments` vector backing, each segment-id/object-key payload **including the duplicate-index clone**, per-segment feature vector backings, the duplicate-key index overhead, and manifest-level feature vectors; it eliminates the `previous_id: Option<String>` clone by comparing against `segments.last()`. `Manifest::retained_bytes()` exposes the same conservative charge for tests. |

## 2. Files changed

Production (`crates/trawler-core/src/segment/`):
- `limits.rs`: added `with_max_read_bytes` and `with_max_section_decode_bytes`
  policy setters (configuration only; no semantic/wire change).
- `reader.rs`: bounded `read_all` chunk loop.
- `manifest.rs`: conservative retained-memory accounting and clone elimination.

Tests:
- new `crates/trawler-core/tests/segment_corrective_pass02.rs` (22 tests).
- `crates/trawler-core/src/segment/tests.rs`: existing manifest error tests still
  pass; no behavioural change required.

Untouched: golden fixture (SHA unchanged), `trawler-objectstore`,
`trawler-distributed`, PR 2/3/4 APIs, Cargo manifests/lockfile, roadmap.

## 3. Scope discipline

- No change to F01–F12 bytes, format versions, trailer/digest domains, manifest
  encoder, `Directory`/`ReadHandle` public traits, or canonical manifest
  semantics.
- No writer/commit/CURRENT/recovery (PR 6), query (PR 7), FST (PR 8), RustFS
  bootstrap (PR 13), distributed, or vector work.
- No new dependency, no `unsafe`.

## 4. Resource-budget semantics

`max_read_bytes` bounds each positional `read_at` request; `accepted_segment_bytes`
still bounds the total object size independently. `max_section_decode_bytes`
remains the cumulative retained-byte budget for one logical decode; the manifest
charge is now complete (vector backing + strings incl. duplicate-index clone +
feature vectors + index overhead + manifest-level features). `CodecSchema::decode`
continues to check its own retained bytes independently; both use the same
configured limit, which is documented (not silently conflated).

## 5. Deferred / residual

- Whole-object buffering up to `accepted_segment_bytes` remains an accepted PR 5
  limitation, now with per-request chunking.
- No authenticated selective range reads (separate decision).
- `Manifest::retained_bytes` is a conservative upper bound, not allocator
  telemetry.

## 6. Validation

See `corrective-pass-02-validation-report.md`. All mandatory gates pass on the
final tree; no merge was performed.
