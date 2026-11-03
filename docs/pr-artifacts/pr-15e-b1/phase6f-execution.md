# PR 15E Phase 6F — execution record

**Status: `P6F_ATTRIBUTED_REVIEW_READY`** (candidate `C06_NO_SAFE_LOCAL_CHANGE`,
`implementation_authorized: false`). Read-only forensic attribution of the existing Phase 6
rare-lane evidence. **Zero new captures, zero engine queries, zero production changes.**

## 1. P0 repository and identity preflight

| Check | Observed |
|---|---|
| Branch | `dev/pr15e-b1-live-bitmap-postings-membership` |
| HEAD | `395d8d8c06f8569348e00fe3264259203ab080f3` (Phase 6 evidence head; docs-only tail of the measured anchor) |
| Measured source | `e448469d6c98d9ef4b4a827ad9567363a888a185`, an ancestor of HEAD |
| `origin/main` | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` (recorded; different from the plan's observed value, treated as main drift under D02; no rebase or merge) |
| Post-anchor protected diff | none: `git diff --name-only e448469..HEAD -- crates/ benchmarks/pr15d/ benchmarks/pr15e/ benchmarks/pr15e_b1/ .github/ Cargo.toml Cargo.lock` is empty |
| Working tree | clean before writing |
| Required symbols | `decode_stored_selected`, `skip_field_values_budgeted`, `skip_scalar_budgeted`, `skip_json_budgeted`, `decode_field_values_budgeted`, `DecodeBudget::{reserve_bytes,reserve_vec,reserve_string,reserve_btree_entry}`, `ByteReader::{len_prefixed_u16,expect_end}`, `SegmentReader::{stored_docs_selected,doc_key_selected}`, `project_selected_hits` all present with the expected contracts |

## 2. P1 raw-evidence binding (all gates passed)

Private run directory (gitignored, not committed) `target/pr15e/phase6-e448469d-01` with the
official capture subtree for `n100000/rare/k100/perf`. Every required file was present and
regular; no symlink, duplicate or escaping path.

| Check | Result |
|---|---|
| `prepare.json.source.head_sha` = measured source | PASS |
| `capture.json.source_sha` = measured source | PASS |
| Published P6 JSON `source_sha` = measured source | PASS |
| Capture identity `pr15e/n100000/rare/k100/perf`, tool `perf`, n=100000, k=100, regime warm | PASS |
| Contention before/after = `clear` | PASS |
| Original verifier `PARTIAL`, 4 passed / 0 failed | PASS |
| `capture.json` SHA-256 `823b4c3b…` | PASS |
| `perf-self.txt` SHA-256 `dccbcef3…` | PASS |
| `perf-calltree.txt` SHA-256 `c46b2fb1…` | PASS |
| All 6 `capture.json.files[]` artifact digests (including the recorded `perf.data` and both contention probes) | PASS |

(Full SHA-256 values are published in `benchmarks/reports/pr15e-b1/phase6f-g05-attribution.json`.)

## 3. P2 derived-analysis workspace

A new private directory `analysis-phase6f-g05` was created next to (never inside) the original
capture; the original `perf-self.txt` and `perf-calltree.txt` were copied in and hashed. The
original run directory was not modified, renamed or overwritten.

## 4. P3 offline re-reading (no capture)

The original `prepare.json` records the versioned fallback profiler path and
`perf version 6.8.12`. That exact installed binary is still usable and matches the recorded
version, so it was used for offline re-reading of the recorded `perf.data` only.

| Step | Command shape | Result |
|---|---|---|
| Flat self report (P3a) | `perf report --stdio --no-children --sort dso,symbol --percent-limit 0.1 -i <perf.data>` | produced from the recorded file; used only as a cross-check |
| Sample-level call chains (P3b) | `perf script -i <perf.data>` | 305 MB, 121,296 cycles samples, fully symbolized chains |
| Control lanes | same `script` mode for `absent`, `medium`, `common` | 2.0 M / 2.4 M / 4.6 M lines |

No `perf record`, `profile.py capture`, `profile.py prepare`, heaptrack or engine query ran in
P6F. `perf annotate` was not needed: per-sample chains resolved every caller question, so no
source-line heat map was claimed.

**Why per-sample re-reading was necessary:** the Phase 6 text caller tree is not an arithmetic
partition — its caller branches at several depths overlap, so partitioning a shared frame's self
(e.g. `from_utf8` 20.88 %) from that text alone would have been an invention. A test of the text
route showed partitions exceeding the parent self (e.g. 23.52 % of a 20.88 % frame), which is
exactly the arithmetic contradiction the plan forbids publishing. The per-sample chains give each
sample exactly one leaf and one caller chain, so classification is unambiguous.

## 5. P4 fixed attribution algorithm and results

Classification: each sample is assigned by its **leaf symbol** (what work) and its **innermost
named subsystem** in the call chain (whose work). Runtime and helper frames are transparent for
ownership but remain the leaf's own bucket. Buckets are mutually exclusive and sum to 100.00 %.

Rare lane, denominator 121,296 cycles samples:

`V03` framing 18.70 % · `V01` UTF-8 16.14 % · `V07` drops 17.29 % (not rankable) ·
`V08` other G05 10.60 % (not rankable) · `V04` budget 9.64 % · `V02` skip dispatch 9.51 % ·
`V05` selected materialization 0.00 % · `V06` JSON 0.00 %.

Cross-checks: (a) per-sample G05 = 81.87 % versus the Phase 6 inclusive 82.39 % — consistent;
(b) the four control lanes give G03 60.30 % for `absent` (G05 ≈ 0.02 %), G05 52.56 % for
`medium`, and G05 33.95 % / G06 25.77 % / adapter 24.94 % for `common`; (c) per-sample totals sum
to 100.00 %; (d) the recorded 121,000 versus the parsed 121,296 differs by 0.24 % (perf's `121K`
display rounding) and the two denominators are never mixed.

## 6. P5 source-contract audit (summary)

Every bucket is required work: UTF-8 validation of unselected strings/keys (typed-error parity),
STORED framing/bounds/`expect_end` (corruption detection), per-field modeled budget admission
with first-failure order, field-state/scalar dispatch (cursor correctness), and inlined
bounds/overflow helpers. The selected-record bucket is effectively zero, confirming Phase 3
selectivity. No redundant work was identified in source. Full detail in
`phase6f-qualification.md` §3.

## 7. P6 adversarial cross-checks (read-only reasoning, no new tests)

| Scenario | Why a "skip validation" change is prohibited |
|---|---|
| Invalid UTF-8 in the last unselected record | The scan reaches `expect_end` after the selection; removing validation would accept a corrupt segment |
| Malformed JSON after the selected record | `skip_json_budgeted` enforces depth/count/budget/UTF-8; removal changes corruption semantics |
| Exact vs one-below decode budget while skipping | `DecodeBudget` admission order and retained-byte model are a prior correctness requirement |
| Non-stored field marked present | `decode_stored_selected` rejects it; removal would accept malformed presence bitmaps |
| Key mismatched to selected hit | `project_selected_hits` verifies physical key parity before materialization |
| Trailing bytes / truncated section | `expect_end` and typed truncation errors |
| Cancellation / PIT reuse | Unchanged by any read-only analysis; no claim of newly executed tests |

## 8. Decision ledger

| Rule | Trigger | Class | Action |
|---|---|---|---|
| D01 | Correct branch, `e448469` ancestor, no post-anchor protected diff, clean tree | AR | Proceeded on the docs tip |
| D02 | `origin/main` differs from the plan's recorded value | AR | Recorded the actual SHA; no rebase |
| D08 | Original P6 run and all raw inputs present | AR | Validated manifests and hashes |
| D14 | Reports expose named frames and a valid denominator | AR | Extracted per-sample attribution |
| D16 | Offline re-reading yields 121,296 vs recorded 121,000 | AR | Kept one denominator for all shares and disclosed the difference; original text reports were not mixed in |
| D18/D19 | Shared `from_utf8`/`ByteReader`/`DecodeBudget`/drop frames | AR | Partitioned only by per-sample chains; no heuristic distribution |
| D22 | Nested G05 ancestry | AR | Reported one inclusive context (82.39 %) separately from disjoint exclusive buckets |
| D27 | No bucket wins the preapproved ranking and all buckets are mandatory | AR | Selected `C06_NO_SAFE_LOCAL_CHANGE` |
| D30 | Legacy campaign remains `PARTIAL` 4/20 | AR | Labelled as offline follow-up; no 20/20 claim |
| D32 | Diff audit | AR | Only the six approved evidence paths changed |
