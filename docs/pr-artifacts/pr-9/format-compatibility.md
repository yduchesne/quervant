# PR 9 format compatibility

**Base:** `17fd2b674365bb656ce5f3ea22de5a52cd4bf80f`. **Branch:**
`dev/stable-key-mutations`.

## New/changed identifiers

| Item | Value | Notes |
|---|---|---|
| `SectionKind::MutationState` | `0x000F` | Next free section id after `FieldNorms = 0x000E`. |
| `FEATURE_MUTATION_STATE` | `0x0008`, version `1` | Added to `SUPPORTED_FEATURES`; next free feature id after `FEATURE_FIELD_NORMS = 0x0007`. |
| Mutation-state container magic | `TRWMSV01` | New `ContainerKind::MutationState`; existing `TRWSEG01`/`TRWMAN01` are unchanged. |
| Manifest payload version | `2` | Adds an optional trailing `(object_key, length, sha256)` mutation-state reference. |

## Compatibility rules

1. **Version 1 manifests decode byte-for-byte unchanged.** `Manifest::decode`
   accepts versions 1 and 2; a version-1 payload has no state reference and
   preserves the original section layout. `Manifest::encode` emits version 1
   whenever `mutation_state` is `None`.
2. **Frozen PR 5/7/8 fixtures are not regenerated.** Segment containers,
   dictionary/postings/columns/stored/norms/remap/bounds layouts, existing
   section ids and existing feature ids are untouched.
3. **Legacy generations synthesize state without rewriting bytes.** When a
   loaded manifest has no state reference, `load_committed_at` scans the actual
   physical document keys and builds an all-live revision-1 state, rejecting
   duplicate live keys. This is an in-memory interpretation only; no legacy
   fixture bytes change.
4. **Version 2 is self-describing.** A version-2 manifest must also declare
   `FEATURE_MUTATION_STATE` as a required manifest feature; encode and decode
   both enforce the reference/feature agreement. Unknown required features fail
   closed through the existing `ensure_features_supported` path.
5. **Sidecar binding.** The manifest references the sidecar by exact object key,
   exact byte length and SHA-256. `read_verified` checks length first and then
   the digest; a missing or mismatched sidecar is a typed failure with no
   all-live fallback.
6. **Determinism.** Sidecar rows are strictly ascending by key and replay rows
   strictly ascending by token, so equal logical state always encodes to equal
   bytes and one content address.
7. **No migration mutation.** A writer may load a version-1 manifest and emit a
   version-2 manifest after an accepted commit, but it never rewrites an
   existing manifest, segment or sidecar object in place.

## Golden fixtures

- Existing v1 manifest/segment golden fixtures are exercised unchanged.
- `MutationStateV1` round-trip, determinism, truncation, unsorted/duplicate row,
  unknown-status and unknown-intent rejection are covered by module unit tests.
- An integration test (`t37_v1_manifest_readable_and_migrates`) rewrites a live
  manifest as version 1, reopens it through the legacy path and then migrates it
  to version 2 with a new commit.
