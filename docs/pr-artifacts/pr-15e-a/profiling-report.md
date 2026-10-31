# PR 15E-A — profiling report

- **Status:** `BLOCKED_ATTESTATION` — **no capture has been executed, therefore no
  CPU share, allocation count, cumulative byte total, hotspot ranking or speedup
  exists in this report.**
- **Additional structural blocker:** `heaptrack` 1.5.0 does not relay the adapter
  JSONL stream (X22), so G06 is blocked even once a window is attested.
- **Acceptance:** `PENDING_REVIEW`; `PR15E_B_AUTHORIZED = NO`.

This document is generated from the verified evidence records of run
`target/pr15e/20261031T122508Z-fc2c62a` (`verification.json`
`2c17f92f335b00367a6c587b686f9852a7383f1173272937a52acf886ccf42d1`) plus the
tool-capability probes described in [`investigation.md`](investigation.md). Every
number below is reproducible from a command in section 7.

## 1. Required capture matrix (fixed, no substitutions)

| # | N | Class | K | Tool | Seconds | Status |
|---:|---:|---|---:|---|---:|---|
| 1 | 10000 | absent | 100 | perf | 20 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |
| 2 | 10000 | absent | 100 | heaptrack | 20 | NOT CAPTURED (`X22` relaying) |
| 3 | 10000 | rare | 100 | perf | 20 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |
| 4 | 10000 | rare | 100 | heaptrack | 20 | NOT CAPTURED (`X22` relaying) |
| 5 | 10000 | medium | 100 | perf | 20 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |
| 6 | 10000 | medium | 100 | heaptrack | 20 | NOT CAPTURED (`X22` relaying) |
| 7 | 10000 | common | 100 | perf | 20 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |
| 8 | 10000 | common | 100 | heaptrack | 20 | NOT CAPTURED (`X22` relaying) |
| 9 | 100000 | absent | 100 | perf | 30 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |
| 10 | 100000 | absent | 100 | heaptrack | 30 | NOT CAPTURED (`X22` relaying) |
| 11 | 100000 | rare | 100 | perf | 30 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |
| 12 | 100000 | rare | 100 | heaptrack | 30 | NOT CAPTURED (`X22` relaying) |
| 13 | 100000 | medium | 100 | perf | 30 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |
| 14 | 100000 | medium | 100 | heaptrack | 30 | NOT CAPTURED (`X22` relaying) |
| 15 | 100000 | common | 100 | perf | 60 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |
| 16 | 100000 | common | 100 | heaptrack | 60 | NOT CAPTURED (`X22` relaying) |
| 17 | 100000 | absent | 10 | perf | 30 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |
| 18 | 100000 | rare | 10 | perf | 30 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |
| 19 | 100000 | medium | 10 | perf | 30 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |
| 20 | 100000 | common | 10 | perf | 60 | NOT CAPTURED (`BLOCKED_ATTESTATION`) |

Gate summary from `verify.py`:

| Gate | Result |
|---|---|
| G05 perf (12 required) | 0/12 — `FAILED`(unobserved) |
| G06 heaptrack (8 required) | 0/8 — `FAILED`(unobserved) |
| G07 capture semantics (20) | 0/20 |
| G08 evidence | `PARTIAL` |
| G09 attribution | `FAILED` — no primary 100K/K=100 lane is attributed |

## 2. Primary 100 K / K=100 attribution (required by G09) — NOT PRODUCED

For each of `absent`, `rare`, `medium`, `common` at N=100000, K=100 the dossier
must list the three highest supported `perf` CPU paths and the three highest
supported `heaptrack` allocation sites with the raw file SHA and source command.
**No entry can be produced because no capture exists.** The table is deliberately
left empty rather than filled with guesses:

| Lane | Top-3 CPU paths | Top-3 allocation sites |
|---|---|---|
| `pr15e/n100000/absent/k100` | `ATTRIBUTION_UNRESOLVED` (no capture) | `ATTRIBUTION_UNRESOLVED` (no capture) |
| `pr15e/n100000/rare/k100` | `ATTRIBUTION_UNRESOLVED` (no capture) | `ATTRIBUTION_UNRESOLVED` (no capture) |
| `pr15e/n100000/medium/k100` | `ATTRIBUTION_UNRESOLVED` (no capture) | `ATTRIBUTION_UNRESOLVED` (no capture) |
| `pr15e/n100000/common/k100` | `ATTRIBUTION_UNRESOLVED` (no capture) | `ATTRIBUTION_UNRESOLVED` (no capture) |

N=10K references and the K=10 control lanes are likewise unobserved.

The tool smoke in `target/pr15e/tool-smoke/` is **not** a substitute: it is one
dev-chosen request mix on the 10 K index, without an attested window, without the
frozen 20-request samples, and with heaptrack absent. It is retained only as
evidence that `perf` can symbolicate the real adapter
(`# Samples: 11K`, 490 `quervant` symbol mentions, `perf.data` 95 159 688 B).

## 3. What the source does and does not prove

**Source-confirmed pattern (not a measurement).** `crates/quervant-core/src/search/execute.rs`
`evaluate_lexical_with` materialises an effective-live-document `BTreeSet` and
scans it. That is a real O(N) pattern in the unified path.

Classification: `HYPOTHESIS` — "the live-document set construction and scan is a
material fraction of warm exact-term CPU and allocation traffic." It is *not*
`MEASURED_EVIDENCE`: no profile attributes CPU share or allocation traffic to that
code today. The previously published PR 15D-B warm medians (2.856 ms absent,
81.212 ms rare, 613.618 ms medium, 1,881.925 ms common at 100 K/K=100) come from
the uninstrumented comparison and are **not** the expected result of any capture
here; they are also not attributable to one code path.

No other candidate is ranked. In particular nothing is claimed about postings
decode, dictionary/FST traversal, BM25 scoring (constant-score membership only),
sort/top-K, projection/materialisation or allocator behaviour.

## 4. Candidate directions for PR 15E-B — all `HYPOTHESIS`, none authorized

Ordering here reflects *cheapness of falsification*, not expected gain:

1. Replace the full-live-document set/scan with a postings-driven membership path
   for exact terms. **Proof missing:** capture attributing ≥ a meaningful share of
   `absent`/`rare`/`medium`/`common` CPU to `live_doc_and_stats`, and allocation
   traffic to the same site.
2. Avoid re-deriving live-document statistics per query when a segment's live set
   is unchanged. **Proof missing:** the same attribution, plus evidence that
   statistics derivation is not amortised elsewhere.
3. Reduce per-query allocation in the candidate/sort path. **Proof missing:**
   heaptrack allocation sites with counts and cumulative bytes.

Every item stays `HYPOTHESIS` until G05/G06/G09 pass for the four primary lanes.
No speedup, parity or significance claim is made or implied.

## 5. Why the numbers are missing (precise blockers)

1. **X15 / `BLOCKED_ATTESTATION`:** no operator idle-window statement exists for a
   PR 15E-A campaign. The driver refuses to launch a profiler without
   `<run>/attestation.json` + `--idle-confirmed`; a passed flag alone is rejected
   (verified: capture exits 3 with `BLOCKED_ATTESTATION` and creates no capture
   directory).
2. **X22 / heaptrack relaying:** `heaptrack 1.5.0` writes two informational lines
   to stdout before the debuggee starts, so the adapter's JSONL stream is not
   transparently relayed. The driver classifies the first non-JSON line as a hard
   stop and preserves the raw artifacts; it does not skip banner lines and does not
   switch to attach, shell pipelines or another tool. This blocks all 8 heaptrack
   lanes and therefore G06 and G09 regardless of attestation.

## 6. Interpretation rules already enforced by the verifier

- `perf` self percentages are samples, never stage durations; the verifier rejects
  any `analysis.json` entry with `unit: "ms"`, `inferred_stage_ns` or
  `sum_inclusive_cpu_percent`.
- A `MEASURED_EVIDENCE` entry must cite a byte-identical raw line from the capture
  and carry the value in its original numeric representation; otherwise the entry
  must be `UNRESOLVED`.
- Overlapping inclusive stacks are reported as nested shares and never added.
- heaptrack cumulative allocated bytes are allocation traffic, not RSS and not peak
  logical memory.
- A capture without symbolized Quervant frames is marked `ATTRIBUTION_UNRESOLVED`
  and cannot satisfy G09.

## 7. Exact reproduction steps

```sh
# 1. Prepare on the exact commit that will carry the evidence (clean tree).
python3 benchmarks/pr15e/profile.py prepare --out target/pr15e/<run-id>

# 2. Write <run>/attestation.json verbatim from the operator statement, then
#    capture the 20 authorized lanes in the prescribed order, one at a time:
python3 benchmarks/pr15e/profile.py capture --run target/pr15e/<run-id> \
  --n 10000 --class absent --k 100 --tool perf --seconds 20 --idle-confirmed
#    … (see benchmarks/pr15e/README.md for the full matrix)

# 3. Verify and only then publish.
python3 benchmarks/pr15e/verify.py --run target/pr15e/<run-id>
python3 benchmarks/pr15e/verify.py --run target/pr15e/<run-id> \
  --analysis target/pr15e/<run-id>/analysis.json --publish-manifest
```

Local preparation evidence for this report:

```sh
python3 benchmarks/pr15e/profile.py prepare --out target/pr15e/20261031T122508Z-fc2c62a
python3 benchmarks/pr15e/verify.py --run target/pr15e/20261031T122508Z-fc2c62a
# → status PARTIAL, exit 3, no capture.json, no published manifest
```

Raw `perf.data`, heaptrack archives and the prepared indexes remain under
gitignored `target/pr15e/` and are **private pending review**; no sanitized
manifest was published because evidence is incomplete.
