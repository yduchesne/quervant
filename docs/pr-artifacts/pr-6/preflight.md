# PR 6 preflight — local writer, durable commit, refresh, PIT and recovery

> **Branch:** `dev/pr06-writer-lifecycle`
> **Baseline HEAD:** `569f4a48f98e2f97d55686c5440588889fc66233` (`main`, verified
> equal to `origin/main` at preflight)
> **Toolchains present:** stable `1.98.1` and MSRV `1.85.0`
> **Status of this document:** EXECUTED preflight; implementation subsequently
> completed. No merge performed.

## 1. Baseline verification

- `git fetch`/branch inspection: `dev/local-index` pointed at the same commit as
  `main`/`origin/main` (`569f4a4`); the worktree was clean at start.
- PR 5 (segment/manifest codecs), PR 4 (analysis) and PR 3 (storage) merged;
  crates renamed to `quervant-*` by the rename PR.
- Golden fixture `crates/quervant-core/tests/fixtures/segment/golden.seg`
  SHA-256 = `ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979`,
  matching the plan's previously reviewed hash. The fixture was **not**
  regenerated.

## 2. API inventory (verified against the checkout)

| Seam | Verified facts used by PR 6 |
|---|---|
| `analysis::AnalyzerRegistry` | `builtin()`, deterministic; `SchemaAnalyzerBindings::resolve` fails closed on unknown/mismatched bindings. |
| `segment::SegmentBuilder` | `new(Schema, AnalyzerRegistry)`, `add_document(SegmentDocument)`, `build() -> BuiltSegment { bytes, schema, remap }`. Fixture-only before PR 6; reused unchanged. |
| `segment::SegmentReader` | `open(Vec<u8>, SegmentLimits)`; internally `Rc<RefCell<..>>`, **not** `Send`/`Sync`. PR 6 constructs independent readers per thread from shared immutable bytes. |
| `segment::Manifest` | `encode`/`decode`; feature sets must be strictly ascending and duplicate-free; segment ids strictly ascending; object keys unique. No `CURRENT`/generation codec. |
| `storage::Directory` | `create`, `open_read`, `exists`, `delete`, `atomic_write`, `sync`, `list`, `file_len`. `FsDirectory::atomic_write` is a same-directory temp + file fsync + rename + parent-directory fsync on the supported Linux local-filesystem target, and fails closed elsewhere. Parents are **not** created by `create`/`atomic_write`. |
| `contract` | `Document`, `DocumentKey`, `MutationRequest`, `PitId`, `Budgets` are validated shapes only. |

## 3. Binding gate disposition

- `G-DEDUP-MIN` and `G-CANON` remain **OPEN — PRE-PR 6** in
  `docs/decisions/PR02_CONTRACT_DECISIONS.md`. They bind durable **dedup
  retention** and **canonical mutation identity** for replay. PR 6 is
  explicitly **insert-only** and rejects any request carrying an idempotency key,
  so neither gate is exercised. They are recorded as non-binding for PR 6 and
  remain open for the PR that implements upsert/delete/idempotent replay.
- No unresolved writer-lock, PIT or schema-compatibility gate blocks PR 6.

## 4. STOP-condition review

None of the ten STOP conditions applied:

1. No conflicting lifecycle code existed on `main`.
2. Binding contract gates are non-binding for insert-only PR 6 (see §3).
3. `Directory::atomic_write` durably publishes a same-directory replacement on
   the supported platform and reports an indeterminate outcome otherwise; PR 6
   never infers durability from a read-back.
4. The manifest/segment codecs accept `s-<64hex>` ids and `index/segments/...`
   keys without format changes. The segment container can carry the baseline
   feature twice; PR 6 canonicalizes feature declarations when deriving manifest
   refs, leaving PR 5 bytes untouched.
5. The builder supports both volatile refresh views and durable commit without
   semantic change.
6. Writer admission is cooperative; stale locks are never stolen.
7. Snapshot concurrency is achieved by constructing independent readers from
   shared `Arc<[u8]>` bytes without changing `SegmentReader` threading.
8. The approved budget hierarchy (`SegmentLimits`, `AnalysisLimits`,
   `contract::Budgets`) is reused; no new dependency, unsafe code or custom
   cryptography.
9. No wire format, golden bytes, mutation/merge/GC, query execution or remote
   adapter changed.
10. All mandatory gates were locally executable (see `validation-report.md`).

## 5. One justified, additive storage change

`Directory` had no way to create the nested `index/` + `index/manifests/` +
`index/segments/` prefixes required by the plan's key layout, and the PR 3
contract deliberately refuses to create missing parents in `create`/
`atomic_write`. PR 6 therefore adds an **additive** trait method:

```rust
fn create_dir_all(&self, prefix: &str) -> Result<(), StorageError>;
```

- A default implementation fails closed with `StorageError::Unsupported`.
- `FsDirectory` creates and fsyncs the prefix (and ancestors) on Unix; other
  platforms fail closed.
- `MemoryDirectory` treats it as a validated no-op (keys are opaque strings).
- No existing `create`/`open_read`/`atomic_write`/`sync`/`delete` semantics were
  changed, and all existing PR 3 conformance tests still pass.

This is recorded as a deliberate, reviewed-as-needed amendment in the
implementation report.
