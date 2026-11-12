# PR 15I-D3-B-F1 — evidence index

## Published archives

**None.** `publish` requires the independent verifier to return
`verification = PASS`; the only completed control fails verification because of
the two post-T1 tooling defects in `a-a-control.md`. Hand-crafting an archive
would bypass the mandatory gate, so no archive or sidecar was written to
`$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b-f1/` (the directory
remains empty/absent).

## Preserved local evidence (`SAME_DISK_ONLY`, not an archive)

| Path | Contents |
|---|---|
| `target/pr15i-d3-b/fixup-f1/preflight-01.json` | source/host/corpus identity, changed-path allowlist, protocol and tooling digests |
| `target/pr15i-d3-b/fixup-f1/dry-proof-01/` | `DRY_RUN_NO_TIMING` AA and AB canonical build experiments plus `dry-proof-summary.json` |
| `target/pr15i-d3-b/fixup-f1/d3bf1-base-aa-01/` | complete sealed control: `compile-source/`, `build/A`, `build/B`, `corpus/`, `indexes/`, `manifest.json`, `authorization.json`, `raw/build-provenance.json`, `raw/host-attestation.json`, `raw/setup/*`, `raw/slots/slot-01..16.json`, 32 contention probes, `raw/seal.json`, `sanitized/summary.{json,md}` |
| `target/pr15i-d3-b/fixup-f1/sources/{base,control-base,candidate}` | external identity worktrees (never compile paths) |

Key digests:

| Artifact | SHA-256 |
|---|---|
| Control seal inventory | 59 members, all re-hashed by the controller |
| `raw/build-provenance.json` | `e965f1a7e94c6430e4522fad20f2ee8fc0291a91713e4a1c5ef4d5c257d0ea4e` |
| `raw/host-attestation.json` | `c2a4a37e23652d173d5a38f72532a98e7494bc273d0c627afb51b007390d0c2b` |
| F1 protocol | `4d55ea0577f2779a48f007c4e14adf56538c8ded4a86d8ca3e4d8194215657cd` |
| F1 tooling manifest | `6ac5f26743a3cf58880db2090839d6d25befee0724859265a5ff57d8367ad7e0` |

## Verification receipts

- `verify.py --campaign-dir …/d3bf1-base-aa-01` → exit 3,
  `V_INVENTORY: unlisted campaign member: compile-source/.git`.
- Diagnostic with the inventory exclusion applied in memory only → exit 3,
  `V_HOST: host fingerprint does not recompute`.

Both are reproduced verbatim in `a-a-control.md`. No receipt claims `PASS`.

## Historical evidence (unchanged)

The D3-B v1 evidence root `$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b/`
and its `d3b-base-aa-01.tar.gz` (SHA-256
`563a5cf02674dacd71286796dcffcb0760098a0adec8db5434edbd60b3d973fc`, 59
members) were not touched, renamed, re-published or reinterpreted. The old T0
tooling tree diffs empty against `155ebafafa29fb0e6b6cbf953f89445f4880fd2f`.
