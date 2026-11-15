# BM-02 contracts and threat model

## 1. Trust model

Evidence directories and archives are **untrusted read-only bytes**. A YAML/JSON
document that contains a `sha256:` field is an integrity *claim*, never external
authentication.

The only authority is a caller-supplied trusted-admission spec plus an
**independently pinned canonical digest**:

```python
load_trusted_spec(spec_bytes, *, expected_spec_digest) -> TrustedAdmissionSpec
```

There is deliberately no constructor that derives `expected_spec_digest` from the
same evidence directory. A sidecar file beside an archive, a receipt's
`receipt_id`, or a digest stored inside an evidence document cannot replace the
external anchor.

A `receipt.v1` document is a structural precondition, not proof. Revalidation
recomputes:

* raw SHA-256 and exact byte length for every declared file and archive;
* every archive member's name, length and raw digest;
* the exact expected member set (no extras, no omissions);
* the source-lock Git commit/tree/blob bytes;
* the validator source-file-set digest over the approved implementation files;
* adapter/analysis/build/schema/QA/policy bindings from the checked-in BM-01
  catalog and records;
* the complete sorted receipt input set and output/index digest.

## 2. Closed internal formats

These are **not** additional public BM-01 schemas and are not registered in
`config/schemas`:

* `trusted-admission-spec` v1 — subject, origin/scope, validator, policy/QA
  digests, five named locks, declared files and archives with exact members.
* `admission-index` v1 — subject, origin/scope, trusted spec digest, five locks,
  observed files and archives with exact members.

Both are strict JSON with an exact closed field set, validated by hand with the
BM-01 codecs. Unknown fields, duplicate names/paths, unsorted lists, unsupported
archive formats and missing required entries fail closed.

Reserved receipt input names (`trusted-spec`, `protocol-lock`, `workload-lock`,
`validator-lock`, `policy-lock`, `qa-roster-lock`, `adapter-lock`,
`analysis-lock`, `build-lock`, `schema-registry`, `source-lock`) cannot be
shadowed by an evidence name.

## 3. Safe primitives

### Paths

`open_regular_beneath(root, relative)` walks components with descriptor-relative
`os.open(..., dir_fd=..., O_NOFOLLOW | O_DIRECTORY)` and opens the leaf with
`O_NOFOLLOW`. Only regular files are accepted. Roots and ancestors that are
symlinks are rejected. Relative names reject absolute paths, traversal,
backslashes, drive colons, ASCII controls, empty/repeated components, trailing
slashes, more than 32 components and more than 4096 UTF-8 bytes. Platforms
without the required descriptor semantics fail `BM_NOT_IMPLEMENTED`; there is no
symlink-following fallback.

### Hashing

`sha256_stream` hashes raw bytes in 1 MiB chunks over a hard budget.
`sha256_regular_file` holds the descriptor for the whole read and compares
`(dev, inode, size, mtime_ns, ctime_ns)` immediately after hashing.
`source_file_set_digest` hashes an explicit, unique, sorted file list and binds a
canonical `source-file-set` v1 payload; timestamps never participate.

### Archives

TAR.GZ and ZIP are inspected by streaming; nothing is extracted. Both reject:

* traversal/absolute/backslash/dot/repeated-slash names;
* duplicate member names;
* non-regular TAR members (symlink, hard link, directory, device, FIFO);
* ZIP symlinks, directories, encrypted entries and unsupported compression;
* member/total/count/archive byte budgets, checked before and during reads;
* malformed, truncated, bad-CRC and size-inconsistent data.

Unsupported archive extensions (`.tar`, `.tgz`, `.tar.zst`, `.7z`, `.jar`, …)
fail `BM_NOT_IMPLEMENTED` rather than being guessed at.

### Provenance

`verify_git_commit` uses argument-list `git` subprocesses only (`cat-file`,
`rev-parse`, `show`). No shell, checkout, worktree switch, fetch, build or file
execution. `verify_build_file` hashes bytes without executing them.
`verify_validator_source` binds the exact approved implementation source set.
`require_clean_head` is a separate strict operation; verifying a pinned historical
commit never claims the developer worktree is clean.

## 4. Admission sequence

`admit_synthetic` performs, in order:

1. spec shape, independent anchor, subject and synthetic/simulated scope;
2. lock names/digests and `verified_locks` binding;
3. safe output/evidence roots and closed evidence directories;
4. raw file length and digest;
5. archive raw length/digest and exact member inventory;
6. provenance/lock dependency verification;
7. a **second** full evidence hash before building the index;
8. canonical `admission-index` v1;
9. `receipt.v1` with gate `admission`, status `pass`, origin `synthetic`, scope
   `simulated`, complete sorted inputs, empty dependencies and one index output;
10. exclusive publication;
11. full revalidation when the destination already exists.

`reverify_admission` never writes. It loads exactly two canonical committed files,
rehashes evidence twice, revalidates every dependency and verifies the receipt
against the trusted spec and the observed index.

## 5. Publication protocol

`publish_admission` creates `output_base/<experiment_id>/<run_id>/` exclusively,
writes `admission-index.json` with `xb`, writes and fully fsyncs
`admission.pending`, creates `admission.json` as a hard link to the fsynced
staging file, fsyncs the directory, removes the staging file and fsyncs again.

`admission.json` is the only completion marker. A destination is committed only
when **exactly** `admission-index.json` and `admission.json` exist, both are
canonical regular files and no staging file, extra file, hidden file or symlink
is present. Failures leave partial files as invalid forensic evidence; nothing is
auto-deleted, repaired or overwritten. Collisions return
`BM_PUBLICATION_CONFLICT`.

## 6. Scope fence

Only `(evidence_origin, qualification_scope) == ("synthetic", "simulated")` can
receive a new BM-02 receipt.

* `real` + `official` → `BM_ACQUISITION_PROHIBITED`, before evidence access.
* `real` + `historical_replay` and other illegal pairs → `BM_SCOPE_MISMATCH`.
* A synthetic receipt relabelled real (with a recomputed `receipt_id`) fails
  because the trusted spec, actual evidence and receipt bindings disagree.
* A receipt claiming `source-qa`, `analysis`, `acceptance`, `verification`,
  `attestation` or `framework-qa` is rejected.
* `ADMITTED_SYNTHETIC`/`REUSED_VERIFIED` are not public `outcome.v1` statuses and
  are not performance or release authorization.

## 7. Host diagnostics

Capability snapshots accept an injected `CapabilityProvider`; the Linux provider
allowlists a small set of `/proc` and `/sys` files. Snapshots contain no
`ready`, `authorized`, token or expiry fields. Readiness evaluation operates only
on supplied immutable observations and returns `clear`/`blocked` with sorted
reasons; `clear` is never an acquisition permit.

## 8. Residual risks owned elsewhere

| Risk | Owner |
| --- | --- |
| Authenticity of the external trust root (human approval of the pinned digest) | BM-03/BM-06 |
| Concurrent hostile mutation of third-party storage after return | shared store / BM-03/BM-06 |
| Real historical archive replay and retirement | BM-07/BM-08/BM-09 |
| Statistical and independent policy conclusions | BM-03…BM-06 |
| Live readiness polling and authorization transitions | BM-03 |
| First real full-scale acquisition | BM-09 |
