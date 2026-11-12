# PR 15I-D3-B-F1 — preflight

## Reconciliation (executed before any change)

| Check | Observed |
|---|---|
| `git fetch origin` | succeeded; no output |
| `git status --short` | empty (clean) |
| `git branch --show-current` | `dev/pr15i-d3b-retained-key-prefilter` |
| `git rev-parse main origin/main HEAD` | `39dbd9f5…`, `39dbd9f5…`, `80bffa8ab91674d0245db0c27ffcf411958835d6` |
| `git merge-base --is-ancestor 39dbd9f5… HEAD` | true (exit 0) |
| `git cat-file -t 48d9abf3…` / `155ebafa…` | `commit` / `commit` |
| `git diff --name-only 48d9abf3… HEAD -- crates/ Cargo.toml Cargo.lock` | empty |
| `git diff --check` | clean |

`main` and `origin/main` are still the fixed BASE, so `FDX-01` pins the
experiment and `FDX-05` allows continuing on this branch: it advanced only in
documentation after the candidate commit.

## Source census (candidate, `unified.rs` SHA-256 `493f93825e77…`)

- Three retained-duplicate check sites: `check_retained_duplicate` at lines 920
  (owned), 1462 (legacy keyword) and 1519 (borrowed keyword).
- Four admission routes: `admit_and_note` at lines 921, 1463, 1531 and 1604.
- `heap_admit_candidate` returns `SearchResult<bool>` (line 1357).
- Rejected historical design symbols (`RetainedKeyFingerprintIndex`,
  `retained_key_exists`, `key_fingerprint`, `index_insert_after_heap_push`,
  `index_remove_after_heap_pop`, `doc_key_view`): zero occurrences.
- BASE `unified.rs` SHA-256 `bb7a1035…`; candidate `493f9382…`; both match the
  plan identities.

## Historical evidence (unchanged, diagnostic only)

| Item | Value |
|---|---|
| Old D3-B T0 | `155ebafafa29fb0e6b6cbf953f89445f4880fd2f`; `git diff --exit-code 155ebafa… -- benchmarks/pr15i_d3_b` is empty |
| Old v1 protocol SHA-256 | `8c113091507528450f9dd8f406fc3ac0a390c164b9a7a603583f48d752c6d1be` |
| Old failed control | `d3b-base-aa-01`, `MEASUREMENT_BLOCKED` (structural binary mismatch) |
| Old archive SHA-256 | `563a5cf02674dacd71286796dcffcb0760098a0adec8db5434edbd60b3d973fc`; sidecar agrees, 59 members |
| Old arm digests | A `cdc434c8…`, B `d0847853…` |

The old A/A numerical ratios and drift results remain diagnostic only; its
binary mismatch permanently prevents requalification. The old evidence is not
modified, re-published or reinterpreted by F1.

## Baseline QA (before tooling changes)

| Command | Result |
|---|---|
| `python3 -m unittest discover -s benchmarks/pr15i_d3_b -p 'test_*.py'` | PASS, 61 tests |
| `cargo test -p quervant-core --lib d3b_tests` | PASS, 28 tests |
| `cargo test -p quervant-core --test pr15i_d3_b` | PASS, 10 tests |

## Host and tools

WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`, x86_64, 12 CPUs, Intel
i7-10750H, native `ext4`. `rustc 1.98.1`, `cargo 1.98.1`, `cargo +1.85.0`
1.85.0, Python 3.12, git 2.43.0, `findmnt` from util-linux 2.39.3 (present and
returning `ext4`).

## Decision log

- `FDX-01`: AUTO-RESOLVE, BASE pinned.
- `FDX-03`: AUTO-RESOLVE, candidate commit and `unified.rs` hash match.
- `FDX-05`: AUTO-RESOLVE, branch advanced only in documentation.
- `FDX-07`: AUTO-RESOLVE, old v1 manifest/protocol/archive verified and left
  untouched.
- `FDX-09`: AUTO-RESOLVE, F1 directory absent before creation.
