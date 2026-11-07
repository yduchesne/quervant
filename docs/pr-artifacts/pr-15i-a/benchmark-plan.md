# PR 15I-A — benchmark plan

Frozen before candidate measurement in `benchmarks/pr15i_a/protocol.json`.

## Arms

- **A:** `888e819d85f0cde62a5040919ac5c96feca52f1f` (post-PR15I-0 `main`).
- **B:** the single immutable candidate commit containing only the PR 15I-A
  production/test/doc/benchmark additions.

Both arms are built in clean detached worktrees with distinct target
directories. The controller refuses a dirty tree, an unlisted changed path, a
non-native filesystem, a candidate equal to A, or an unqualified baseline size.

## Corpus and oracle

Frozen PR15D 10K/100K corpus, generated once per campaign and verified against
its manifest. Every size rebuild and every warm lane is checked against the
independent PR15D oracle (`total_hits` and ordered keys), never against a second
codec.

## Matrix

| Dimension | Frozen schedule |
|---|---|
| Size | 10K and 100K, three independent builds per arm; identical component and total bytes plus payload layout required |
| Warm search | nine frozen lanes, 5 warmups + 20 measured queries, 16 slots in `ABBA/BAAB/BAAB/ABBA` order |
| Reopen | 100K, 4 balanced blocks x 2 fresh processes per arm |
| Build+commit | 100K, 4 balanced blocks x 2 independent builds per arm; ingest and commit reported separately |
| Peak RSS | kernel `wait4` `ru_maxrss` for the same reopen and build+commit processes |
| RustFS | pinned image, 100K prepare per arm, 4 balanced blocks x 2 cold bootstraps into fresh workspaces |
| Controls | 129-live-segment, tombstone/upsert mix, replay-heavy and zero-live correctness controls in `pr15i_a_v3.rs` |

## Gates

`A-P01` sidecar `<= 0.75`; `A-P02` total `<= 0.95`; `A-P03` 10K sidecar and total
`<= 1.02`; `A-P04` reopen `<= 1.10` (block `<= 1.25`); `A-P05` build+commit
`<= 1.15` (block `<= 1.30`); `A-P06` 100K lanes `<= 1.10` (block `<= 1.30`);
`A-P07` 10K lanes `<= 1.15` (block `<= 1.35`); `A-P08` RSS `<= 1.15`
(block `<= 1.30`, absolute `<= 16 MiB`); `A-P09` RustFS `<= 1.15`
(block `<= 1.35`); `A-P10`–`A-P12` correctness, budget, and provenance;
`A-P13` workspace QA is a separate local gate.

## Statistics

Ratios are `B/A`; smaller is better. Each block ratio is the mean of the block's
B samples over the mean of its A samples. The reported statistic is the
conventional median of the four block ratios (average of the two middle values)
and **every** block must be below its block ceiling. p50/p95 are reported for
information only and never replace a gate. No slow block may be discarded; a
contaminated block invalidates the campaign and requires a new campaign ID.

## Evidence

All raw data, logs, environment and contention probes are written under
`target/pr15i-a/campaigns/<unique-id>/` and sealed with a sorted SHA-256
inventory. Any later source change requires a new candidate SHA and a complete
new campaign.
