# PR 15H-E — compact dictionary campaign controller

Measures the v1 (A) vs feature-gated dictionary-payload-v2 (E) experiment on the
frozen PR15D 10K/100K corpus and adapter.

## Identity

- A = the pinned tooling checkout SHA (`E_TOOLING_SHA`), whose production
  `search/`/`segment/`/`index/` files are the accepted pre-E baseline.
- E = `--candidate-sha`, a descendant that may change only:
  `segment/{format,dictionary,reader,build}.rs` and `index/merge.rs` (plus
  E-only tests/tooling/docs).

## Measurements

- Dictionary / immutable-segment / committed-index bytes for 10K and 100K.
- 2,048-document low-vocabulary `SegmentBuilder` control segment size.
- 16 warm balanced slots `A E E A | E A A E | E A A E | A E E A`, nine lanes,
  5 warmups + 20 samples per lane.
- 4 balanced blocks × 2 cold process-open samples per arm
  (`pr15h_e_open_timing`) and 2 build+commit samples per arm.
- Independent PR15D oracle, host/corpus/index/binary identity and contention
  probes.

## Gates

E-P01 100K Dictionary <=0.65; E-P02 10K Dictionary <=0.70; E-P03 100K segment
<=0.90; E-P04 100K committed index <=0.92; E-P05 10K committed index <=0.95;
E-P06 low-vocab segment <=1.02; E-P07 non-Dictionary section bodies identical;
E-P08 100K warm conventional median <=1.08 and all blocks <=1.30; E-P09 10K
warm conventional median <=1.12 and all blocks <=1.40; E-P10 cold-open
conventional <=1.15/all blocks <=1.35; E-P11 build+commit <=1.15/all <=1.35;
E-P12 provenance/idle/seal/drift. Any invalid evidence blocks the verdict.

## Commands

```sh
python3 benchmarks/pr15h_e/run.py \
  --checkout-root /ABS/CHECKOUT --candidate-sha <E_SHA> \
  --out /ABS/CHECKOUT/target/pr15h-e/campaigns/paired-01 --idle-confirmed
python3 benchmarks/pr15h_e/run.py \
  --checkout-root /ABS/CHECKOUT --candidate-sha <E_SHA> \
  --out /ABS/CHECKOUT/target/pr15h-e/campaigns/paired-01 --verify-only
```

Run from a clean detached tooling worktree pinned to `E_TOOLING_SHA`; pass the
main checkout root as `--checkout-root`.
