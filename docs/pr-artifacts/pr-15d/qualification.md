# PR 15D comparative qualification

- Workload: `pr15d_v1`
- Source SHA: `40a9c26a57aa23640904075e77be956ee52718bc`
- Host fingerprint: `4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f`
- Filesystem: `ext4`
- Trials: 3 x 20 samples/lane
- Status: **QUALIFIED**
- Score comparison: `NOT_APPLICABLE`
- Scored lane: `SEMANTICALLY_NONCOMPARABLE`
- Performance threshold failure: `False`

## Exact-term latency (median of three trial medians, ns)

| Lane | Regime | Quervant | Tantivy | Lucene | Tantivy/Quervant | Lucene/Quervant |
|---|---|---:|---:|---:|---:|---:|
| pr15d_v1/10000/absent/k10 | process_cold | 18497765 | 51301 | 18497384 | 0.002773 (INCONCLUSIVE) | 0.999979 (INCONCLUSIVE) |
| pr15d_v1/10000/absent/k10 | warm | 291905 | 13301 | 311805 | 0.045566 (INCONCLUSIVE) | 1.068173 (INCONCLUSIVE) |
| pr15d_v1/10000/absent/k100 | process_cold | 18547865 | 40000 | 18781877 | 0.002157 | 1.012617 (INCONCLUSIVE) |
| pr15d_v1/10000/absent/k100 | warm | 304005 | 11300 | 321205 | 0.03717 | 1.056578 |
| pr15d_v1/10000/rare/k10 | process_cold | 28210303 | 50401 | 26386156 | 0.001787 (INCONCLUSIVE) | 0.935338 (INCONCLUSIVE) |
| pr15d_v1/10000/rare/k10 | warm | 7690507 | 13500 | 662010 | 0.001755 (INCONCLUSIVE) | 0.086081 (INCONCLUSIVE) |
| pr15d_v1/10000/rare/k100 | process_cold | 29268118 | 53201 | 26611425 | 0.001818 (INCONCLUSIVE) | 0.909229 |
| pr15d_v1/10000/rare/k100 | warm | 7208904 | 13701 | 616109 | 0.001901 | 0.085465 (INCONCLUSIVE) |
| pr15d_v1/10000/medium/k10 | process_cold | 32756072 | 79501 | 34621302 | 0.002427 (INCONCLUSIVE) | 1.056943 (INCONCLUSIVE) |
| pr15d_v1/10000/medium/k10 | warm | 11922452 | 37300 | 1498118 | 0.003129 | 0.125655 (INCONCLUSIVE) |
| pr15d_v1/10000/medium/k100 | process_cold | 33855288 | 176102 | 59030545 | 0.005202 | 1.743614 |
| pr15d_v1/10000/medium/k100 | warm | 12125274 | 94201 | 4265463 | 0.007769 | 0.351783 |
| pr15d_v1/10000/common/k10 | process_cold | 47651487 | 127502 | 34524410 | 0.002676 | 0.724519 |
| pr15d_v1/10000/common/k10 | warm | 26459581 | 76601 | 1356318 | 0.002895 | 0.05126 (INCONCLUSIVE) |
| pr15d_v1/10000/common/k100 | process_cold | 49254310 | 201803 | 52993251 | 0.004097 (INCONCLUSIVE) | 1.075911 |
| pr15d_v1/10000/common/k100 | warm | 27738115 | 133502 | 2647538 | 0.004813 (INCONCLUSIVE) | 0.095448 (INCONCLUSIVE) |
| pr15d_v1/100000/absent/k10 | process_cold | 186792558 | 74701 | 18531465 | 0.0004 (INCONCLUSIVE) | 0.099209 |
| pr15d_v1/100000/absent/k10 | warm | 2898437 | 16300 | 357905 | 0.005624 (INCONCLUSIVE) | 0.123482 (INCONCLUSIVE) |
| pr15d_v1/100000/absent/k100 | process_cold | 186250382 | 49101 | 18746172 | 0.000264 | 0.10065 |
| pr15d_v1/100000/absent/k100 | warm | 2856441 | 16200 | 347205 | 0.005671 | 0.121552 |
| pr15d_v1/100000/rare/k10 | process_cold | 281008096 | 63801 | 27300188 | 0.000227 (INCONCLUSIVE) | 0.097151 |
| pr15d_v1/100000/rare/k10 | warm | 81443933 | 20101 | 567608 | 0.000247 (INCONCLUSIVE) | 0.006969 |
| pr15d_v1/100000/rare/k100 | process_cold | 280942412 | 66300 | 27271383 | 0.000236 | 0.097071 |
| pr15d_v1/100000/rare/k100 | warm | 81211676 | 18900 | 678109 | 0.000233 (INCONCLUSIVE) | 0.00835 (INCONCLUSIVE) |
| pr15d_v1/100000/medium/k10 | process_cold | 814637158 | 227403 | 36016084 | 0.000279 (INCONCLUSIVE) | 0.044211 |
| pr15d_v1/100000/medium/k10 | warm | 616174603 | 171102 | 1396319 | 0.000278 | 0.002266 |
| pr15d_v1/100000/medium/k100 | process_cold | 811351143 | 344105 | 59386458 | 0.000424 (INCONCLUSIVE) | 0.073195 |
| pr15d_v1/100000/medium/k100 | warm | 613617548 | 237603 | 4363663 | 0.000387 | 0.007111 |
| pr15d_v1/100000/common/k10 | process_cold | 2073392315 | 692810 | 35133714 | 0.000334 (INCONCLUSIVE) | 0.016945 |
| pr15d_v1/100000/common/k10 | warm | 1877739567 | 604808 | 1330419 | 0.000322 | 0.000709 (INCONCLUSIVE) |
| pr15d_v1/100000/common/k100 | process_cold | 2082210349 | 821011 | 54071886 | 0.000394 (INCONCLUSIVE) | 0.025969 |
| pr15d_v1/100000/common/k100 | warm | 1881924908 | 657309 | 2864941 | 0.000349 | 0.001522 (INCONCLUSIVE) |

## Indexing, commit, reopen and size

### quervant

| N | index_ns | commit_ns | reopen_ns | index_bytes | segments |
|---:|---:|---:|---:|---:|---:|
| 10000 | 20273726 | 164555229 | 40283071 | 3090037 | 1 |
| 100000 | 219869192 | 1565832567 | 412788923 | 30965025 | 1 |

### tantivy

| N | index_ns | commit_ns | reopen_ns | index_bytes | segments |
|---:|---:|---:|---:|---:|---:|
| 10000 | 715310 | 91705279 | 458907 | 299768 | 4 |
| 100000 | 1436411968 | 53974565 | 449607 | 2905431 | 4 |

### lucene

| N | index_ns | commit_ns | reopen_ns | index_bytes | segments |
|---:|---:|---:|---:|---:|---:|
| 10000 | 149973806 | 127239142 | 29549934 | 186052 | 1 |
| 100000 | 463801410 | 298757641 | 26822609 | 1858642 | 1 |

## Index artifact size variation (descriptive, never an equality invariant)

Physical byte totals are reported per trial. Differing positive values do
not invalidate a trial; they expose engine layout differences such as
scheduling-dependent segment boundaries.

| Engine | N | trial 1 | trial 2 | trial 3 | min | max | max/min |
|---|---:|---:|---:|---:|---:|---:|---:|
| quervant | 10000 | 3090037 | 3090037 | 3090037 | 3090037 | 3090037 | 1.0 |
| quervant | 100000 | 30965025 | 30965025 | 30965025 | 30965025 | 30965025 | 1.0 |
| tantivy | 10000 | 299052 | 299768 | 300900 | 299052 | 300900 | 1.00618 |
| tantivy | 100000 | 2909404 | 2903322 | 2905431 | 2903322 | 2909404 | 1.002095 |
| lucene | 10000 | 186052 | 186052 | 186052 | 186052 | 186052 | 1.0 |
| lucene | 100000 | 1858642 | 1858642 | 1858642 | 1858642 | 1858642 | 1.0 |

## Ingestion through commit (`index_ns + commit_ns`, derived)

Primary ingestion quantity per engine. It is a checked integer sum of the two
documented adapter stages and is not a proof of fsync-equivalent durability.
The raw `index_ns` and `commit_ns` components remain visible above.

| Engine | N | trial 1 | trial 2 | trial 3 | median | min | max | max/min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| quervant | 10000 | 197125470 | 184627513 | 181577812 | 184627513 | 181577812 | 197125470 | 1.085625 |
| quervant | 100000 | 1852873372 | 1785701759 | 1750394772 | 1785701759 | 1750394772 | 1852873372 | 1.058546 |
| tantivy | 10000 | 92248386 | 99805400 | 91701961 | 92248386 | 91701961 | 99805400 | 1.088367 |
| tantivy | 100000 | 1380680912 | 1519305038 | 1494101457 | 1494101457 | 1380680912 | 1519305038 | 1.100403 |
| lucene | 10000 | 277212948 | 263232239 | 292190310 | 277212948 | 263232239 | 292190310 | 1.11001 |
| lucene | 100000 | 785053716 | 734245777 | 762559051 | 762559051 | 734245777 | 785053716 | 1.069197 |

## Physical sort representation (disclosed, never normalized)

- Quervant: Keyword doc_id column, ascending
- Tantivy: u64 ordinal fast field derived from the fixed-width doc_id, ascending
- Lucene: STRING doc_id SortedDocValues sort field, ascending
- Logical order: identical across engines for the frozen fixed-width doc_ids
- Physical equivalence: `NOT_CLAIMED`. The three engines produce the same ascending doc_id order, but their physical sort workloads differ. This is reported, never normalized, and must never be presented as an equivalent physical workload.

## Query API shape and timing boundary

- quervant performs count+top-K in one public search call; tantivy and lucene issue a separate count and Top-K search. Both totals are exact and are included in engine_ns for every engine.
- engine_ns covers the engine search/count, the requested top-K sort and materialisation of every returned doc_id; it excludes process start, reader open, response serialization and independent oracle checks.
- ingest_through_commit_ns is index_ns + commit_ns per trial and is the primary ingestion quantity; it measures adapter insertion plus commit, not proven fsync-equivalent durability.

## Serial throughput (`serial_ops_per_second`)

| Engine | N | median ops/s | dispersion |
|---|---:|---:|---:|
| quervant | 10000 | 78.788337 | 1.091772 |
| quervant | 100000 | 1.653155 | 1.023134 |
| tantivy | 10000 | 7356.136769 | 1.224013 |
| tantivy | 100000 | 3773.374593 | 1.006425 |
| lucene | 10000 | 778.705185 | 1.037876 |
| lucene | 100000 | 751.972361 | 1.066499 |

## Measurement limitations

- process_cold means a fresh process and unopened reader, never OS-cold page cache
- 20-sample nearest-rank p95/p99 is a sample distribution, not a production SLA
- serial_ops_per_second is a single sustained serial window, not multi-thread QPS
- RSS/CPU/allocation metrics are NOT_MEASURED when no common method exists
- physical segment counts may differ by engine and are reported, never normalized
- index_bytes may differ across trials for engines whose segment layout is scheduling-dependent; all three observations, min, max and max/min are reported descriptively and are never used to accept or reject a trial
