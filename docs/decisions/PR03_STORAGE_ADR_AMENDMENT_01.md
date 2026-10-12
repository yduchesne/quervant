# Trawler PR 3 — ADR Amendment #1: Storage Contract Corrections

**Target:** `dev/storage-abstraction` · `docs/decisions/PR03_STORAGE_CONTRACT_DECISIONS.md`  
**Status:** PROPOSED — NOT HUMAN-APPROVED  
**Work authorization:** Documentation-only reconciliation. **Do not begin stage 3B or modify Rust source, Cargo manifests, CI, or runtime code.**

## Purpose

Reconcile the Phase 1 S01–S16 decision register with the architectural review. Preserve all unmentioned decisions as **PENDING HUMAN APPROVAL**. This amendment proposes corrections; it is **not** an approval of S01–S16.

## Required procedure for a low-reasoning coding agent

1. Fetch `origin/main` and `origin/dev/storage-abstraction`; inspect the exact current branch, worktree and register before editing. The register has already been observed on the remote branch, despite the earlier agent report describing it as untracked. **Do not overwrite or discard newer work.** If the branch or register differs materially, STOP and report.
2. Edit only `docs/decisions/PR03_STORAGE_CONTRACT_DECISIONS.md`, plus this amendment document if the repository workflow requires it. Do not silently change unrelated decisions or the roadmap.
3. For each item below, replace the corresponding proposed text with an internally consistent proposal, including signatures, preconditions/postconditions, error types, alternatives, and conformance tests. If a choice cannot be specified without inventing an implementation guarantee, write an explicit open question and STOP.
4. Update the approval-request summary to identify amended rows. Keep **every S01–S16 status PENDING HUMAN APPROVAL**; keep the document's approval reference unset.
5. Run documentation checks (`git diff --check`, changed-path inspection, and Markdown link/heading review). No claim of Rust test/coverage success is needed for documentation-only edits.
6. Commit and push documentation-only changes to `dev/storage-abstraction` if the branch is unchanged and you have push permission; otherwise STOP and provide the patch. **Do not open or merge a PR without separate instruction.**
7. Report changed files, commit SHA, remote branch, exact open questions, and the complete S01–S16 approval table. **STOP** awaiting human approval; no public contract implementation.

## A1 — S01: Root confinement and symlink threat model

Retain validated UTF-8 relative `StorageKey` grammar and reject symlink components. Explicitly state that `canonicalize`/`symlink_metadata` plus a later open is **not race-free** under concurrent hostile filesystem mutation. The PR 3 guarantee applies only to a trusted, access-controlled managed root with no concurrent adversarial tree mutation. Do not describe the check as a security boundary against local attackers. Document the stronger future `openat`/directory-handle-based alternative and the requirement to reassess if untrusted processes can mutate the tree. Include a test for static symlink rejection, but do not claim it proves TOCTOU resistance.

## A2 — S03/S04: Exact durable-replace support

Separate **atomic visibility**, **process-crash behavior**, and **power-loss durability**. The `atomic_write` success path must use a same-directory temporary file, complete write, file `sync_all`, atomic rename/replace, and containing-directory `sync_all` on an explicitly supported local filesystem/platform. A successful call acknowledges only guarantees actually provided by that supported configuration. Specify Linux local-filesystem support as the initial tested target, with filesystem/OS caveats; **do not promise all Unix/POSIX, NFS, overlayfs, container volumes, or every mount configuration**. State how unsupported or unverified platforms fail closed (`Unsupported`) or are explicitly outside the documented durability guarantee. Windows durable replacement remains `Unsupported` for PR 3. Preserve the indeterminate-after-rename-before-parent-sync error case and crash-point matrix. A process-kill test cannot certify power-loss durability.

Clarify whether nested parent directories must already exist or are created by the API. If created, parent creation and ancestor directory synchronization require an explicit contract; do not leave this implicit.

## A3 — S08: Make immutable `put` contract internally consistent

The existing signature accepts `key`, `body`, `precondition`, `limits` but the prose says the caller supplies a `ContentDescriptor`. Amend the illustrative signature to include an explicit expected `ContentDescriptor` (length + SHA-256), or replace the prose with an equally explicit alternative **and document why**. Prefer the descriptor parameter so identity verification is testable. Require validation of byte length and digest before acknowledging creation, and define errors for mismatch. Specify that immutable put semantics and conditional replacement are separate capabilities; `IfMatch` is not automatically allowed for immutable segment objects. Keep bounded transfers, typed errors, no hidden retries, and cancellation semantics.

## A4 — S09: Immutable-create vs CAS/fencing

Define **atomic create-if-absent** as a distinct capability from **conditional replace/compare-and-swap**. The fake must model the claimed atomic behavior under concurrency; the future RustFS adapter must verify its actual provider guarantees, not infer them from generic S3 compatibility. A `HEAD` then `PUT` sequence is not atomic create-if-absent. When immutable-create is unavailable, attempts requiring it fail `UnsupportedCapability`; never overwrite a conflicting object. Conditional replacement is a **future manifest-publication/fencing concern**, not permission to mutate immutable segment objects. Distinguish advertised provider capabilities from application-level durability or writer leadership. Include simultaneous same-key/same-digest and same-key/different-digest conformance cases.

## A5 — S11/S13: Crate ownership and dependency direction

State exactly which crate owns `ObjectKey`, `ContentDescriptor`, `ContentDigest`, `ObjectStore`, `SegmentDescriptor`, `SegmentStore`, and `SegmentCache`. Prefer `trawler-objectstore` for provider-neutral object identity and remote traits; `trawler-core` for local Directory and cache/segment coordination, with **one-way dependency `trawler-core -> trawler-objectstore` only if required**. No reverse dependency and no distributed dependency. If this choice causes an unwanted mandatory remote dependency in standalone local-only core, propose a concrete feature-gated or common-types alternative **for human approval**; do not improvise. Specify how generic async `ObjectStore` is supplied to the cache without a Tokio runtime requirement. `SegmentId` remains opaque/test-only; do not create a persistent format or manifest contract.

## A6 — S12: Hard accounting, pinning and cancellation

Define `max_cache_bytes` against **published entries + reserved in-flight bytes + temporary bytes** (and state explicitly how double-counting is avoided). Reserve capacity **before** starting a download; release reservations on success, error, cancellation, or panic-safe cleanup. Define separate bounded `max_concurrent_fills` and any required in-memory response bound, and ensure simultaneous fills cannot exceed configured hard limits. Pinned entries are non-evictable; if insufficient unpinned capacity exists, fail with typed `LimitExceeded`/capacity error rather than evict a pin or exceed the budget. State how cache entries are keyed by full immutable identity, not merely a mutable object key, and how failed fill coalescing wakes waiters. A cancelled leader must not strand followers or leave published unverified bytes. Tests must cover concurrent reservations, pin exhaustion, cancellation at each fill stage, duplicate fills, and restart cleanup.

## A7 — S15: RustFS harness boundary

Choose **foundation-with-explicit-SKIP** in PR 3. Require pinned image/config, disposable credentials, isolated test prefix, start/stop instructions and honest reporting. No mandatory PR 3 CI container startup if no production S3 adapter exists. No fake-backed test may be presented as real RustFS conformance. **PR 13** owns the production adapter and mandatory real RustFS integration/CI evidence. Revise the existing contradictory S15 statement that CI startup is mandatory whenever containers are available.

## A8 — Cross-cutting decisions and dependency verification

Record these as **recommended proposals, not approvals**:

- **S10:** SHA-256 `sha256-v1` over BLAKE3, with length + digest verification.
- **S08/S13:** native Rust `async fn` trait and generic cache adapter for PR 3; no `async_trait` or `dyn ObjectStore` unless separately justified.
- **Dependencies:** `sha2` (and `thiserror` only if useful) subject to verified compatible versions/MSRV/licenses; `tempfile`, `futures`, `mockall` dev-only **if used**. Avoid unused dependencies.
- **S11/S12:** keep minimal bounded verified cache in PR 3; no segment codecs, manifest, writer or remote S3 adapter.
- **S04:** Windows durable replace returns `Unsupported`, not weakened success.

Review and reconcile related sections: cross-cutting invariants, crash-point matrix, immutable retry matrix, test mappings, dependency evidence, and approval request. Ensure the text does not simultaneously assert incompatible semantics.

## Mandatory STOP conditions

STOP if: (a) any S01–S16 row would be marked approved; (b) implementing code seems necessary to decide a proposal; (c) a dependency cycle or required distributed/runtime dependency is introduced; (d) a guarantee cannot be substantiated; (e) the branch has unexpected divergence or conflicting changes; (f) a change would redefine PR 5/6/13 scope; (g) the agent cannot reconcile the proposed `put` signature and immutable-create guarantees.

## Completion report format

Provide: branch and HEAD SHA; changed paths; per-amendment disposition A1–A8; concise revised S01–S16 table with every row **PENDING HUMAN APPROVAL**; exact test/document checks run; remaining questions; explicit statement **NO STAGE 3B IMPLEMENTATION**.
