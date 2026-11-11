# PR 15I-D1-F — historical rejected-C1 postmortem

**Scope:** documentation-only. No C1 source change, no new C1 benchmark, no
reconsideration of the historical performance decision. The original
`D1_C1_PERFORMANCE_REJECTED` disposition stands.

## 1. Immutable identities and evidence

| Item | Value |
|---|---|
| BASE | `a53ee021acbe5f30db2b3298a11fcd99e72c2945` |
| Rejected C1 | `236017289567885689b46d3d04e71d6653296124` |
| C1 `unified.rs` SHA-256 | `641beaf1e7d93916db25dc6ed311cc016158759d363a5fbedec437d0d05b0cba` |
| D1 T0 tooling | `c4e6f5c0c82efb40e50d4cbfaa1279263f1a5321` |
| Rollback | `e935531fb76e90e1a74b0ef3e9ba38c63b47d300` (`git diff BASE..rollback -- crates/` empty) |

The three historical archives were independently audited: sidecar SHA-256
matches, safe extraction, every member re-hashed (58/61/61 members, zero
mismatches or extras), and the frozen D1 T0 verifier still returns:

- `c1-base-aa-01`: PASS, `CONTROL_QUALIFIED`;
- `c1-base-01`: PASS, `CAMPAIGN_QUALIFIED`;
- `c1-base-02`: PASS, `CAMPAIGN_REJECTED`.

The reported measurements reproduce from the sealed summaries:

- 100K common/K100 lower medians `d = 11,554,884 ns` and `10,884,322 ns`;
- 100K common/K10 in campaign 02: median `d = -1,703,980 ns`, block 4
  `d = -3,134,950 ns` (below the frozen `-3,000,000 ns` guard);
- A/A control fully qualified.

No evidence conflict was found.

## 2. Source-level K10 bypass — `SOURCE_BYPASS_PROVEN`

Exact C1 source (`git show 2360172:crates/quervant-core/src/search/unified.rs`):

| Line | Fact |
|---:|---|
| 678 | `heap_limit = request.top_k.limit.saturating_add(1)`; K10 ⇒ 11 |
| 680 | one request-local `RetainedKeyFingerprintIndex::new()` |
| 1215–1217 | capacity 128, activation 32, `MIN_HEAP_LIMIT = 33` |
| 1310–1312 | `accelerated = (33..=128).contains(&heap_limit)`; activation only if accelerated and ≥32 retained |
| 1315–1318 | `if !index.active { return heap.iter().any(exact key scan) }` |
| 1332–1347 | maintenance helpers return immediately unless `active` |
| 909 | owned candidate path calls `retained_key_exists(&mut retained_index, &heap, heap_limit, …)` |
| 1468 / 1521 | legacy and borrowed keyword paths call the same helper |

For K10, `accelerated` is false, so `activate()` is unreachable, `active` stays
false, and every duplicate check executes the original exact linear scan.
`heap_admit_candidate` carries an extra `&mut index` argument and calls the
maintenance helpers, but each returns before touching the hash array. Therefore
the fingerprint index **does not execute for K10**. The historical unit test
`d1_u08` (K10/absent public search ⇒ zero activations) is consistent with this,
but it is test-build evidence, not proof about the historical release binary.

## 3. Machine-code inspection of the exact historical binaries

The original binaries remain and match the sealed hashes, so they were inspected
directly (`nm -anC`, `objdump -d --demangle`, `readelf`; no new build used for
claims):

| Property | BASE arm A | C1 arm B |
|---|---|---|
| SHA-256 | `9f9f909f…` | `6866066c…` |
| Bytes | 4,478,336 | 4,481,032 |
| `.text` bytes (`size`) | 3,251,142 | 3,253,082 |
| Symbols (`nm -an`) | 9,358 | 9,371 |
| Build ID | `910b0bf53bc5320d…` | `18861bf4895bcb4c…` |

A fresh BASE rebuild for comparison is **4,478,312 bytes**, so rebuilt binaries
are labelled `REBUILT_FOR_INSPECTION` and are not claimed to be
historical-identical.

In the historical C1 binary, `retained_key_exists` is a real non-inlined symbol
at `0x261740`. Its low-limit guard compiles to:

```text
261765: add    $0xffffffffffffff7f,%r8      # heap_limit - 129
26176c: cmp    $0xffffffffffffffa0,%r8      # < -96  ⇔ heap_limit < 33
261770: setb   %dl
...
261785: test   $0x1,%al                     # index.active
261787: je     2618bd                       # not active -> legacy scan
```

The branch target `0x2618bd` is the legacy linear heap scan (length-prefixed key
comparison via `bcmp`); the accelerated branch calls `key_fingerprint` at
`0x2617a3` and binary-searches the sorted hash array. For K10 (`heap_limit=11`)
the guard takes the low-limit branch and reaches the legacy scan without ever
calling `key_fingerprint` or reading the hash array. This is consistent with the
source proof.

`retained_key_exists` has exactly three call sites:

| Address | Enclosing symbol | Path |
|---:|---|---|
| `0x25a606` | `UnifiedSearcher::execute_unified` (inlined `collect_mixed`) | owned-tuple path used by the relevance-sorted K10 lane |
| `0x262be2` | `admit_legacy_keyword_candidate` | keyword legacy fallback |
| `0x2630a3` | `consider_borrowed_keyword_candidate` | borrowed keyword path |

## 4. Classification — `CODEGEN_DIFFERENCE_OBSERVED_CAUSALITY_UNPROVEN`

What is proven:

1. The C1 K10 source path bypasses the fingerprint index (`SOURCE_BYPASS_PROVEN`).
2. The historical binary’s low-limit branch reaches the legacy scan and does not
   call `key_fingerprint`.

What is **not** proven: that the measured K10 block delta was caused by any
specific compiled-code difference. The whole C1 binary changed (text size,
symbols, build ID, code layout), the owned K10 candidate loop now routes through
a non-inlined `retained_key_exists` call and an index-carrying
`heap_admit_candidate` instead of the BASE inlined scan, but attributing the
measured nanoseconds to that or to code layout would require execution
profiling of the historical release binary, which this plan forbids. The K10
lane is also code-bypassed, and the §9.3 A/A control passed, so host noise
cannot be excluded as a contributor to one 3.13 ms block.

Counter-hypotheses retained:

- **H1 (noise):** WSL2 scheduling/frequency variance; the K10 block is an
  outlier while the K10 median stayed within its -2 ms limit.
- **H2 (extra call/branch overhead):** the owned K10 path now calls the
  non-inlined helper and maintenance helpers that immediately return.
- **H3 (layout/inlining):** global inlining and instruction-cache changes in
  the same generic collector.

No numerical causal share is claimed. The historical performance rejection is
not reopened, and no new C1 benchmark was run.

## 5. Residual limits

- Rebuilt binaries are not byte-identical to the historical ones and were not
  used to claim identity.
- Absence/presence of a symbol alone was not used as proof of execution; the
  low-limit branch and the absence of a `key_fingerprint` call on that path are
  the machine-code facts cited.
- The postmortem does not authorize any C1 fix, retune or re-measurement.
