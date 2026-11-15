# PR 15I-D3-B-F1.2 — evidence index

## Published archives

Root: `$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b-f1-2/`

| Archive | SHA-256 | Members | Status |
|---|---|---:|---|
| `d3bf12-base-aa-01.tar.gz` | `935a4d8769fa9cae85574fd1d1aae7bf03297fbcbc7ef046697374795d046253` | 62 | `CONTROL_QUALIFIED` |
| `d3bf12-base-01.tar.gz` | `9e1e59b6d2e6a09fa1601861e38e59161437d65e128f9518ed5ea63a93f593ba` | 65 | `QUALIFIED_REJECTED` (performance) |

Both were written exclusively after independent verifier PASS with matching
`.sha256` sidecars. `build/`, `indexes/`, `corpus/` and `compile-source/` are
excluded; the control archive was extracted into
`target/pr15i-d3-b/fixup-f1-2/archive-check/` and re-verified (`verification=PASS`,
`live_binary_rehash=UNAVAILABLE_ARCHIVE`). The paired archive's round-trip was
verified by `publish`.

## Local scratch (`SAME_DISK_ONLY`)

| Path | Contents |
|---|---|
| `target/pr15i-d3-b/fixup-f1-2/preflight-01.json` | source/host/corpus identity |
| `target/pr15i-d3-b/fixup-f1-2/sources/{base,control-base,candidate}` | detached identity worktrees (never compile paths) |
| `.../rehearsal/round-01` … `round-07` | preserved failed pre-T3 harness rounds |
| `.../rehearsal/round-08` | successful synthetic rehearsal (`replay-report.json`) |
| `.../d3bf12-base-aa-01` | complete sealed control (60 sealed members) |
| `.../d3bf12-base-01` | complete sealed paired campaign (63 sealed members) |
| `.../archive-check` | extracted control archive verification |
| `.../d3bf12-base-02`, `-03` | do not exist (not authorized after rejection) |

## Key digests

| Artifact | SHA-256 |
|---|---|
| F1.2 protocol | `3946c1caec27127c7f53c3d10db9a9e9769f2d8f812a8bb1f4fb9551949c3a95` |
| F1.2 tooling manifest | `35f797515565934ff6d191bdb3c9b9fd586d9a4e161ab2b3ca13e12ce443716e` |
| Control provenance / host / readiness | `467c264a…` / `49f224e9…` / `b65f68d4…` |
| Paired provenance / host / readiness / succession | `0ada8e16…` / `a2c61505…` / `6b425085…` / `abc57a73…` |

## Historical evidence

D3-B v1 and F1.1 archives and tooling remain byte-identical. No historical file
was overwritten, re-published or reclassified. No synthetic rehearsal artifact
was published.
