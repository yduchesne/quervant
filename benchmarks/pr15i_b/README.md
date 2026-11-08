# PR 15I-B — bounded compressed random-access STORED blocks

Status: **REJECTED / safe rollback**. Both LZ4 and Zstd level-1 STORED v2
candidates failed the frozen rare/medium warm-lane gate; production is restored
to PR 15I-A. The tooling, sealed negative campaigns and diagnostics remain.

| Item | Path |
|---|---|
| P0 PR 15I-A requalification | `docs/pr-artifacts/pr-15i-b/p0-15ia-qualification.md` |
| Historical 15G-E attribution | `docs/pr-artifacts/pr-15i-b/historical-15g-e-attribution.md` |
| Offline codec study | `docs/pr-artifacts/pr-15i-b/codec-pre-study.md` |
| Historical diagnostic tool | `diagnose_e.py` |
| Codec laboratory (standalone, pinned) | `codec_lab/` |

The laboratory is benchmark-only and reads indexes read-only. It does not
change production code, the frozen corpus, or any sealed PR 15I-A evidence.

```sh
# Historical regression diagnostic (pinned worktrees required)
python3 benchmarks/pr15i_b/diagnose_e.py --out "$PWD/target/pr15i-b/diagnose/<id>"

# Offline codec study on a fresh post-15I-A baseline index
cd benchmarks/pr15i_b/codec_lab
cargo run --release --locked -- encode \
  --index-dir "$PWD/../../../target/pr15i-b/lab/base-index/n100000" \
  --n 100000 --out "$PWD/../../../target/pr15i-b/lab/codec-n100000"
```
