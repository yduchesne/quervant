# PR 5 corrective pass 03 preflight

> Narrow fixup for manifest preallocation budget enforcement on
> `dev/segment-codecs`. No F01–F12 wire change, no golden change, no merge.

## 1. Branch and baseline reconciliation

| Fact | Value |
|---|---|
| Branch | `dev/segment-codecs` |
| Pre-pass-03 HEAD | `5e441a64fb168688ffb0876f9528aa8fd2b4817c` |
| Plan-inspected SHA | `4a62cc29c77a0dd43383809445592c3c1db73577` — ancestor of HEAD |
| Difference | one docs-only commit (`docs(agents): require MSRV and stable Clippy/test validation`) |
| `origin/dev/segment-codecs` | `4a62cc29c77a0dd43383809445592c3c1db73577` |
| `origin/main` | `68bcf0d828f801f247d7f052082b76397f150fbf` (docs-only PR #18) |
| Merge base | `a23cf25798e52fc181e93ac84505a07412f37463` |
| Working tree | clean before edits |
| Rust | `rustc 1.85.0 (4d91de4e4 2025-02-17)` |

`main` diverged (branch is ahead and behind) but contains no `segment` module; the
plan remains valid. No rebase or merge was performed.

## 2. Source inspection

- `Manifest::decode` previously reserved the segments-vector budget up front but
  performed the ID/key `to_owned`, `object_keys.insert(object_key.clone())`, and
  per-segment/manifest-level feature `Vec` allocations **before** the
  corresponding cumulative `check_decoded_bytes` call.
- `StorageKey::parse`/`ObjectKey::parse` took `impl Into<String>` and were called
  with a clone, creating unnecessary temporary validation allocations.
- `trawler_objectstore::validate_key(&str)` is public and validates the same
  grammar without allocation.

## 3. Allocation classification

| Class | Examples | Pass-03 treatment |
|---|---|---|
| Charged manifest-retained | segments vector, owned id/key payloads, duplicate-index clone, feature vectors | Individual + cumulative preallocation check before allocation |
| Temporary validation | `ByteReader` slices; now allocation-free borrowed `validate_key` | Minimized; not charged |
| Independent schema/container | `CodecSchema::decode`, `ContainerView` | Own limits; not part of manifest charge |
| Allocator-internal | bookkeeping/fragmentation | Not modeled; documented |

## 4. Invariant ↔ test mapping

C7-INV01–12 map to functions and tests in
`docs/pr-artifacts/pr-5/correctness-matrix.md` §13 and
`corrective-pass-03-validation-report.md`. Counterexamples challenged:
zero budget, exact/one-below cumulative prefix, late over-budget feature vector,
nonadjacent duplicate keys, out-of-order IDs, invalid UTF-8, huge wire counts,
checked-arithmetic overflow.

## 5. Failing-before evidence

The baseline does not fail on eventual rejection — it already rejects, but
**after** allocating. A runtime allocation-order red requires a custom
`#[global_allocator]`, which the plan's §10 explicitly forbids without a separate
decision. Therefore, per Phase A, this pass records a **source-level baseline
defect with precise line/order evidence** plus a post-fix reviewer-verifiable
allocation-order audit (see the implementation report and adversarial review).
No false red is claimed.

## 6. Gate outcome

PASS; no STOP condition. Proceeding to Phases B–G.
