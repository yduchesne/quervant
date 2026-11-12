# PR 15I-D3A-F2 evidence index

Status: `D3AF2_ATTRIBUTION_QUALIFIED`. All archives are outside `target/` under
`~/.local/share/quervant/benchmark-evidence/pr15i-d3a/fixup-f2/`, with exclusive
`.sha256` sidecars and `SAME_DISK_ONLY` status. Historical T0/T0b/T0c archives
were not modified.

| Artifact | Status | SHA-256 |
|---|---|---|
| `d3af2-base-aa-01.tar.gz` | control QUALIFIED | `00ece619b7f71311e9f770f1fe9ec66aca8e77792e4bddd339e2883f77d381c4` |
| `d3af2-unbatched-01.tar.gz` | qualified | `02d46c8377d5ee79e4cb53b4b7e1cc1bcedfe3930a23a50a3b2d304ddcc1bf23` |
| `d3af2-unbatched-02.tar.gz` | qualified | `8aa73cc98d74e9de7fa6c3f7abf2e59a5ada53085d96cdcf0f104ed5d7c196b7` |
| `d3af2-unbatched-03.tar.gz` | lane-scoped (10K rare perturbed) | `f74d9981aa7a43db5830f5bca4e6bb2df01c280e87171f87eb88bd6c763355ef` |
| `d3af2-unbatched-04.tar.gz` | qualified | `36a058a3d8f6612f402baccf549093aaebc9347be0cb8e3fdf2a6e0728f65ac1` |
| `d3af2-unbatched-05.tar.gz` | qualified | `74d5fe68a62747dd0dfc61eb1eae14b904a2c5f8f6d2feba6b95dc16a308393a` |
| `d3af2-five-run-aggregate.tar.gz` | aggregate v3 + lane qualification | `e67ae701266fc93918affac2a875e49fcc9bcf0ebc5a64abc67f01574e923cab` |

The aggregate bundle contains `independent-aggregate-v3.json`,
`independent-aggregate-v3.md`, `five-run-areas-v3.json`,
`lane-qualification-v3.json` and a member manifest. Every archive was
round-trip extracted and hash-verified. `SAME_DISK_ONLY`; no off-host copy.
