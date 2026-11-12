# PR 15I-D3-A-F preflight

Status: PASS for the official T0c series.

| Item | Value |
|---|---|
| Branch | `dev/pr15i-d3a-candidate-attribution` |
| BASE | `409fb0fdf370bb4d4dade5ea507c6fa4518b5220` |
| T0c | `0f07c29c318982afaf4ce6790ce5272e8754aa11` |
| Worktrees | `target/pr15i-d3a/fixup-f/sources/{base,scratch}` (detached, clean) |
| Preflight | `PASS`, no blockers |
| Corpus manifest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Derivative fingerprint | `62e587715a9a2dd24281a99f9e05e378683dda4e82d9eac0837a4a140801fb60` |
| A binary | `db5d58640c15268ee249487a3c969054ac7424c244a69106384c1e3f1fe8ee88` |
| Q/P binary | `6468121fab1f601ebbdf31f53d0b8136cb95f7b68ac141dfd74949980cb32964` |
| Filesystem | native ext4; WSL2 |
| CPU | Intel Core i7-10750H, 12 logical CPUs |
| Rust | 1.98.1; Python 3.12.3 |

The official A/QP binaries were built once under `fixup-f-series` and reused by
all paired campaigns. The independent source proof returned `VERIFIED`.
