# PR 15I-B — bounded compressed random-access STORED blocks

Status: **REJECTED / safe rollback**. A follow-up direct intra-block access
experiment captured a flat per-record boundary certificate and removed the
128-record hot-path scan; both LZ4 and Zstd1 still exceeded the frozen 10K rare
`B-P06` median (1.152 / 1.158 vs 1.10) and were rejected. Production remains
exactly PR 15I-A STORED v1. Tooling, verifier hardening, design/correctness work
and all sealed negative campaigns are preserved.

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
