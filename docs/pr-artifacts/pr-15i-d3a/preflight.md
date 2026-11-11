# PR 15I-D3-A preflight

Status: `PASS` (read-only preflight). This record is regenerated on the final
tooling state before T0.

## Read-only identity commands

```sh
git fetch origin main
git status --porcelain                       # empty
git rev-parse origin/main
git merge-base --is-ancestor 9e1641dcee77ac0e5876a427de1f8e56c36a5ab0 origin/main
git rev-parse origin/main:crates/quervant-core/src/search/unified.rs
git rev-parse origin/main:crates/quervant-core/src/search/execute.rs
git rev-parse origin/main:crates/quervant-core/src/search/score.rs
git diff 9429dce99827f25766a92c1fbded8f78a0b168f1..origin/main -- \
  crates/quervant-core/src/search/unified.rs \
  crates/quervant-core/src/search/execute.rs \
  crates/quervant-core/src/search/score.rs
```

Observed:

| Item | Value |
|---|---|
| BASE | `409fb0fdf370bb4d4dade5ea507c6fa4518b5220` |
| D2-A evidence ancestor | yes (`9e1641d…` is an ancestor of `origin/main`) |
| D2-A verdict | `D2A_SCORE_COST_LOW_PRIORITY` |
| `unified.rs` blob | `b2978021f9f36ae9a5cdd9fa036448a54097c948` |
| `execute.rs` blob | `5d0ac48132de6ea1220bdd884f81ca9f260ab3ba` |
| `score.rs` blob | `2921afc52ad0f343498e6c69814b38016205ea2d` |
| Search-source diff vs `9429dce…` | empty |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |

## Controller preflight

```sh
python3 benchmarks/pr15i_d3a/run.py preflight \
  --base-root <pristine BASE worktree> \
  --scratch-root <clean scratch worktree> \
  --out target/pr15i-d3a/preflight/preflight.json
```

Observed (first run, pre-freeze):

```text
status=PASS, blockers=[]
base_head=scratch_head=BASE
origin_main_sha=BASE
corpus_manifest_matches_frozen=true
protocol_sha256=01116ef0004a7a03569d0d9d8725be8de9ef2ff9774d568119679c651576c9c3
filesystem=ext4 native_filesystem=true
wsl=true kernel=6.18.33.2-microsoft-standard-WSL2
cpu=Intel(R) Core(TM) i7-10750H CPU @ 2.60GHz, 12 logical CPUs
rustc=1.98.1, cargo=1.98.1, rustfmt=1.9.0-stable, python3=3.12.3, git=2.43.0
```

The worktree placement is on native ext4 under
`<tooling-root>/target/pr15i-d3a/sources/{base,scratch}`. Both detached
worktrees start at BASE and are clean before materialization. The scratch
worktree is reset to BASE before every preflight and is materialized only by
`patch_source.py`.

## Baseline tests (before measurement)

```sh
cargo test -p quervant-core --all-features                 # PASS
python3 benchmarks/pr15d/harness/test_pr15d.py             # PASS (3 skipped)
python3 -m unittest discover -s benchmarks/pr15i_d2a -p 'test_*.py' -v  # PASS
```

No baseline failure was waived.
