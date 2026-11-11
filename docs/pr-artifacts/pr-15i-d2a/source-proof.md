# PR 15I-D2-A — source-locked diagnostic derivative

## Result

The scratch derivative is **insertion only** and reverses byte-for-byte to BASE
`9429dce`. The independent `source_proof.py` does not import `patch_source.py`;
it carries its own edit inventory, rebuilds the expected derivative, applies the
same deterministic `rustfmt` pass and requires `status: VERIFIED`.

The committed repository contains no `d2a_probe` module, no `pr15id2a-probe`
feature in production and no changed `crates/quervant-core/src` source. Produced
binaries:

| Arm | SHA-256 |
|---|---|
| A (pristine BASE, `op=query`) | `8d33c32e03a831bf04ea57be9a36caa59de8a844ccbb34c1ad7da1df7da4fc83` |
| Q/P (same executable, `op=query` / `op=query_probe`) | `18205f305c8b8ead277486e714cc2af20951120b7f21fd52c4351450626cf46b` |

QP is one absolute binary and one SHA for both Q and P. `P` resets the
thread-local recorder immediately before the query and takes it after
`engine_ns` has stopped. `Q` never emits `stage_ns` or `counts`.

## Allowed files (scratch only)

1. `crates/quervant-core/Cargo.toml` — private `pr15id2a-probe = []` feature.
2. `crates/quervant-core/src/search/mod.rs` — feature-gated module.
3. `crates/quervant-core/src/search/d2a_probe.rs` — new recorder.
4. `crates/quervant-core/src/search/unified.rs` — inherited D0 stage boundaries.
5. `crates/quervant-core/src/search/execute.rs` — D0 boundaries plus score
   subspans and counters.
6. `benchmarks/pr15d/adapters/quervant/src/main.rs` — scratch-only
   `query_probe` arm.

Every other file is byte-identical to BASE. `rustfmt` reformatting is included in
the proof; a replacement opcode, extra public item, added `#[inline]`, changed
feature default, changed score equation or changed `query` JSON is a hard
rejection.

## Insertion inventory (summary)

- Recorder constants: 13 stage ids (`plan_ns` … `score_accumulate_ns`) and 6
  counter ids (`matched_docs` … `positive_term_owners`); fixed-size arrays; no
  I/O, formatting, JSON or heap allocation inside a timed span.
- Thirty insertion points across the six allowed files, including:
  - `score_map_ns` around the scored-map ledger reservation and map build.
  - `score_owner_ns` around both positive-term ownership passes.
  - `score_accumulate_ns` around the scoring loop, including field-stat lookup,
    score-map access, `bm25` and addition.
  - `bm25_calls` immediately before each real `bm25` call in the term and phrase
    arms, using checked `count`.
  - `scoring_map_entries` and `positive_term_owners` as query-level checked
    sums; no per-document timer and no new hash/refcount probe.

## Verification evidence

- `target/pr15i-d2a/builds/series-build.json`: materializer/proof agreement,
  insertion inventory, derivative fingerprints, A/QP build metadata.
- Every paired campaign's `raw/sources.json` contains the six-path BASE and
  derivative hashes, the source-proof result and the tooling hashes.
- `verify.py` independently requires `status: VERIFIED`, recomputes the
  derivative fingerprint, and requires the frozen T0 tooling manifest.

## Limits

The derivative is diagnostic infrastructure, not production code. It does not
change the BM25 equation, the public API, the segment format, the PR15D
adapter/corpus/oracle or any accepted source. The 100K A/QP committed index
digests are byte-identical, and the frozen 100K LZ4 sentinels
(`15,747,551` committed bytes; `1,661,455` STORED-section bytes) match.
