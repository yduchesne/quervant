# PR 15H-E — storage measurements

Sealed campaigns:

- baseline `target/pr15h-e/campaigns/baseline-01`, seal sha256
  `6b3851b41ce73d50ae69598ff59cf51503f8fa2f4253dceab2de70eea7711bea`.
- paired `target/pr15h-e/campaigns/paired-01`, seal sha256
  `2ed0ca61674ba5b216f4f71cc546c83f0942e2320af2f41b1436d8eb060c3236`.

| Corpus | Metric | A v1 | E v2 | E/A |
|---|---|---:|---:|---:|
| 10K | Dictionary | 350,207 | 159,456 | 0.4553 |
| 10K | Segment | 2,129,038 | 1,938,291 | 0.9104 |
| 10K | Committed index | 3,090,037 | 2,899,294 | 0.9383 |
| 100K | Dictionary | 3,500,207 | 1,618,170 | 0.4623 |
| 100K | Segment | 21,364,026 | 19,481,993 | 0.9119 |
| 100K | Committed index | 30,965,025 | 29,082,996 | 0.9392 |
| low-vocab control | Segment | 101,377 | 101,362 | 0.9999 |

A payload versions `[1]`, compact feature absent. E payload versions `[2]`,
compact feature present in both corpora.

## Gates

| Gate | Threshold | Result |
|---|---|---|
| E-P01 100K Dictionary | ≤ 0.65 | PASS 0.4623 |
| E-P02 10K Dictionary | ≤ 0.70 | PASS 0.4553 |
| E-P03 100K segment | ≤ 0.90 | **FAIL 0.9119** |
| E-P04 100K committed index | ≤ 0.92 | **FAIL 0.9392** |
| E-P05 10K committed index | ≤ 0.95 | PASS 0.9383 |
| E-P06 low-vocab segment | ≤ 1.02 | PASS 0.9999 |
| E-P07 non-Dictionary section digests | identical | PASS |

The dictionary shrank by ~54%, but the dictionary is only ~16.4% of the 100K
segment. That yields ~8.8% segment and ~6.1% committed-index reduction, short of
the frozen 10%/8% overall gates. No threshold was retuned.
