# PR 7 Amendment 05 — qualified pre/post benchmark comparison

Both runs: Criterion 0.7.0, clean tree, `--idle-confirmed`, three trials, all contention checks `clear`. Same WSL2 guest, host and ext4 filesystem. The post-optimization commit `eb28f7e` contains the optimized production code; subsequent commits changed only tests/docs, so the measured production code is identical to the final HEAD.

| | pre-optimization | post-optimization |
|---|---|---|
| commit | `a8adf374ae9f12908cfc0093c6cde032e53d6c85` | `eb28f7e30430bca53a00a33ff3e5d9eba9c6a853` |
| commit subject | A05 preflight STOP | runner aggregate fix (optimized code) |
| git_dirty | false | false |
| environment | qualified | qualified |
| trials | 3/3 qualified | 3/3 qualified |
| fixture metadata SHA-256 | `09bb89876fb2e1233d7ec7a5d65b1fd43a65213787878c3ce84793d0c504b128` | `09bb89876fb2e1233d7ec7a5d65b1fd43a65213787878c3ce84793d0c504b128` |
| dataset SHA-256 (first record) | `930cdb59945008035c22f7899afa95265b971159828989d725555d7e831c0b7b` | `930cdb59945008035c22f7899afa95265b971159828989d725555d7e831c0b7b` |
| aggregate JSON SHA-256 | `2e41f6b96c690adfbfe181c8f710f588a90242c3b7bc155060adc008a57dc88e` | `a57b19d46954f1ad4ead050699cdd491b445f8549fa29125edbb355abef061b0` |

Trial report SHA-256:

| trial | pre | post |
|---|---|---|
| 1 | `cd96b3e5fda3b04c271f3d61bc2346dfa96581875a57aa2cea691a8044ec023c` | `8d5ec5c99e687581316ed8998d477172ced2b324411e8f113e2448951c8f2db0` |
| 2 | `e6ad13a8a93a222d724e1e59a0b4a2f5546d5d8641899bd27233d5434e7e28e9` | `2e100ee40ea9903203211cb7c4b5eb5e083fd03242cbce370cbb9d2e0c1d42fe` |
| 3 | `96b96d93c58d88a36da0f268ab77c87595f40d3fdce7823d0ca1076c2c73b88d` | `492d0918da546a3aba5ad75696de4725cde932e48c891658b2e461a09964f0f6` |

## Per-workload median latency

| workload | pre ms | post ms | speedup | post min–max ms |
|---|---:|---:|---:|---:|
| `pr07_bm25_reference_control/bm25_equation/fixed_inputs` | 0.000 | 0.000 | 1.01x | 0.000–0.000 |
| `pr07_search_2000_4seg/term-rare/k10` | 6.030 | 3.313 | 1.82x | 3.148–3.337 |
| `pr07_search_2000_4seg/term-medium/k10` | 6.037 | 3.239 | 1.86x | 3.239–3.352 |
| `pr07_search_2000_4seg/term-common/k10` | 6.635 | 3.938 | 1.68x | 3.841–3.987 |
| `pr07_search_2000_4seg/term-absent/k10` | 6.193 | 3.247 | 1.91x | 3.205–3.268 |
| `pr07_search_2000_4seg/and-common-medium/k10` | 6.369 | 3.569 | 1.78x | 3.544–3.622 |
| `pr07_search_2000_4seg/or-common-rare/k10` | 6.598 | 3.889 | 1.70x | 3.781–3.933 |
| `pr07_search_2000_4seg/phrase-present/k10` | 6.185 | 3.311 | 1.87x | 3.286–3.450 |
| `pr07_search_2000_4seg/phrase-absent/k10` | 6.021 | 3.156 | 1.91x | 3.131–3.197 |
| `pr07_search_2000_4seg/phrase-repeated/k10` | 6.038 | 3.389 | 1.78x | 3.328–3.440 |
| `pr07_search_2000_4seg/match-all/k10` | 4.040 | 4.048 | 1.00x | 3.966–4.071 |
| `pr07_search_2000_4seg/pure-negative/k10` | 4.061 | 3.969 | 1.02x | 3.940–4.064 |
| `pr07_search_2000_4seg_topk100/term-common/k100` | 6.827 | 3.819 | 1.79x | 3.757–3.929 |
| `pr07_search_scaling_2000/term-rare/k10` | 6.177 | 3.300 | 1.87x | 3.213–3.418 |
| `pr07_search_scaling_2000/term-common/k10` | 6.790 | 3.909 | 1.74x | 3.866–3.943 |
| `pr07_search_scaling_10000/term-rare/k10` | 25.254 | 12.451 | 2.03x | 12.159–12.991 |
| `pr07_search_scaling_10000/term-common/k10` | 27.859 | 15.648 | 1.78x | 15.422–15.938 |
| `pr07_search_scaling_100000/term-rare/k10` | 241.532 | 117.330 | 2.06x | 113.750–122.188 |
| `pr07_search_scaling_100000/term-common/k10` | 285.594 | 148.784 | 1.92x | 148.632–164.722 |
| `pr07_phrase_2000_4seg/phrase-present/k10` | 6.012 | 3.382 | 1.78x | 3.294–3.423 |
| `pr07_phrase_2000_4seg/phrase-absent/k10` | 5.975 | 3.300 | 1.81x | 3.247–3.381 |
| `pr07_phrase_2000_4seg/phrase-repeated/k10` | 6.157 | 3.331 | 1.85x | 3.313–3.498 |
| `pr07_phrase_10000_4seg/phrase-present/k10` | 25.089 | 12.681 | 1.98x | 12.482–12.872 |
| `pr07_phrase_10000_4seg/phrase-absent/k10` | 24.548 | 12.282 | 2.00x | 12.195–12.619 |
| `pr07_phrase_10000_4seg/phrase-repeated/k10` | 25.069 | 13.063 | 1.92x | 12.753–13.098 |
| `pr07_dictionary_2000/dictionary_lookup_present/ctoken` | 0.000 | 0.000 | 1.02x | 0.000–0.000 |
| `pr07_dictionary_2000/dictionary_lookup_absent/absent_sentinel_zzz` | 0.000 | 0.000 | 1.05x | 0.000–0.000 |
| `pr07_postings_2000/cursor_open_plus_decode/ctoken` | 0.117 | 0.117 | 1.00x | 0.117–0.118 |
| `pr07_dictionary_10000/dictionary_lookup_present/ctoken` | 0.000 | 0.000 | 1.01x | 0.000–0.000 |
| `pr07_dictionary_10000/dictionary_lookup_absent/absent_sentinel_zzz` | 0.000 | 0.000 | 1.04x | 0.000–0.000 |
| `pr07_postings_10000/cursor_open_plus_decode/ctoken` | 0.576 | 0.591 | 0.97x | 0.579–0.595 |
| `pr07_dictionary_100000/dictionary_lookup_present/ctoken` | 0.000 | 0.000 | 1.05x | 0.000–0.000 |
| `pr07_dictionary_100000/dictionary_lookup_absent/absent_sentinel_zzz` | 0.000 | 0.000 | 1.05x | 0.000–0.000 |
| `pr07_postings_100000/cursor_open_plus_decode/ctoken` | 5.805 | 5.900 | 0.98x | 5.830–5.926 |

## Summary

- Scored lexical search workloads improved **1.68x–2.06x**. Default-term whole-search ratios: rare 1.82x / common 1.68x at 2K, rare 2.03x / common 1.78x at 10K, rare 2.06x / common 1.92x at 100K.
- `match-all` and `pure-negative` (no scoring fields) unchanged (1.00x/1.02x): norms decode is O(doc_count) and does not scan postings.
- Controls unchanged: postings decode 0.97x–1.00x, dictionary present 1.01x–1.05x, dictionary absent 1.04x–1.05x, BM25 equation 1.01x.
- No unexplained material regression; all control workloads within +/-5%.
- `n`/live-norm summation remains O(doc_count) per search (permitted by plan §5.5); no O(1) or zero-allocation claim is made. Profilers remain UNAVAILABLE (no symbol-level attribution).

## Chronological order and host drift

The plan's gate intends the pre-baseline to be collected before production edits. Due to the earlier blocked gate, the pre-baseline was collected from an isolated `git worktree` checked out at the unmodified pre-optimization commit `a8adf37` **after** the implementation commit existed. The measured source is exactly pre-optimization and `git_dirty=false`; the collection order is recorded here. Both runs used the identical guest, CPU, filesystem, toolchain and fixture metadata/dataset digests; no host drift was observed.
