# PR 15I-D2-A — evidence index

## Frozen identities

| Item | Value |
|---|---|
| BASE | `9429dce99827f25766a92c1fbded8f78a0b168f1` |
| Final tooling freeze T0 | `747ceb2464425f2392829c5165decf4c697cf34b` |
| Protocol SHA-256 | `7e41e2c576baf522ad652dd66488373f07c88a3c8419677a3f42dee40f41d39e` |
| Tooling manifest SHA-256 | `92c025c90ba6344f4f5c4a7270ea9ec8131b3e1daac0c58f947d325d2a02bd04` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| A binary SHA-256 | `8d33c32e03a831bf04ea57be9a36caa59de8a844ccbb34c1ad7da1df7da4fc83` |
| Q/P binary SHA-256 | `18205f305c8b8ead277486e714cc2af20951120b7f21fd52c4351450626cf46b` |

## Qualified archives

Immutable archives live outside the repository at
`$HOME/.local/share/quervant/benchmark-evidence/pr15i-d2a/`:

| Campaign | Archive | SHA-256 | Members |
|---|---|---|---|
| `d2a-base-aa-01` | `d2a-base-aa-01.tar.gz` | `c4c8af2462d2d41e4ee8e0d982f25e0194c11dca5cab22d4b59517b4210f4e47` | 63 |
| `d2a-unbatched-01` | `d2a-unbatched-01.tar.gz` | `3c53176d0187503fa253e3142806fbeb45f64f0ef28201fdea95ed70cc053994` | 87 |
| `d2a-unbatched-02` | `d2a-unbatched-02.tar.gz` | `ee23f1bd04983c7e0f071c2df872e53f001b26b9d004d46c9c35ec1496beb10d` | 87 |

Each archive has a plain-text `<archive>.sha256` sidecar created with exclusive
create. The archive command safely extracted each archive, rejected traversal,
symlinks and extra members, and re-hashed every member. In addition, each archive
was independently extracted into `target/pr15i-d2a/archive-check/<campaign>/`,
the original read-only indexes were supplied for the external-index check, and
`verify.py` was re-run: all three returned `PASS`, and the extracted
`sanitized/summary.json`, `sanitized/summary.md` and `verification.json` were
byte-identical to the originals.

## In-repository evidence

`target/pr15i-d2a/` contains:

- `preflight/preflight-final.json` — 25 source/artifact hashes and host state.
- `builds/series-build.json` — materializer/proof agreement and A/QP builds.
- `aa/d2a-base-aa-01/` — qualified A/A control, `raw/`, `setup/`, `seal.json`,
  `sanitized/`, `verification.json`.
- `paired/d2a-unbatched-01/` and `paired/d2a-unbatched-02/` — qualified paired
  campaigns with the same layout.
- `paired/independent-aggregate.json` — independent
  `D2A_SCORE_COST_LOW_PRIORITY` aggregate.
- `archive-check/` — independent archive re-verification copies.
- `superseded/` — rejected A/A attempts, the superseded T0 series and their
  invalid evidence; these are never part of the qualified series.

The superseded A/A archive is retained as
`$HOME/.local/share/quervant/benchmark-evidence/pr15i-d2a/superseded/d2a-base-aa-01-SUPERSEDED-T0-bb3a6e5.tar.gz`
with its sidecar. It is not counted as qualified evidence.

## Retention and backup disclosure

`target/` is **not** durable evidence; the archives above were created before
any cleanup and are the durable copies. They are on the same physical/virtual
disk as the repository (`SAME_DISK_ONLY`) unless the operator supplies
off-host/object storage. No deletion of raw target evidence is scheduled. No
absolute user-home paths, credentials or private endpoints are committed.

## Reproduction

```sh
python3 benchmarks/pr15i_d2a/verify.py \
  --base-root <BASE worktree> \
  --campaign-dir <campaign directory>
sha256sum -c "$HOME/.local/share/quervant/benchmark-evidence/pr15i-d2a/d2a-unbatched-01.tar.gz.sha256"
```
