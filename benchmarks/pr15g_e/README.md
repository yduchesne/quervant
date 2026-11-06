# PR 15G-E format-aware A/E comparison

Compares accepted A+B (`ca065a2`, segment v1.0) with the E candidate
(segment v1.1 persistent offset directories) on the frozen nine PR15D warm
lanes. The arms intentionally have different encoded bytes, so index digests
are checked for immutability within each arm and oracle equality across arms,
never byte equality between arms.

```sh
python3 benchmarks/pr15g_e/run.py \
  --checkout-root /ABS/CHECKOUT \
  --candidate-sha <40-hex-E> \
  --out /ABS/CHECKOUT/target/pr15g-e/campaigns/<fresh-id> \
  --idle-confirmed
python3 benchmarks/pr15g_e/run.py \
  --checkout-root /ABS/CHECKOUT \
  --out /ABS/CHECKOUT/target/pr15g-e/campaigns/<fresh-id> \
  --verify-only
```

The schedule is `A E E A | E A A E | E A A E | A E E A`; each lane has five
warmups and twenty samples. Drift caps are 1.25 for 100K and 1.50 for 10K.
`E_FASTER` requires all four block ratios `< 1.0`; `A_FASTER` requires all
four `> 1.0`.
