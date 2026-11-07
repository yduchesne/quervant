# PR 15H-C — preflight

**Branch:** `dev/pr15h-a-linear-term-candidates` (required literal, continued in place)
**Starting HEAD / baseline A:** `e8744d3fe16ee858c7d587aaf3b10d393059b809`
**Inspected `main`:** `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078`
**Tooling-only (`HC_TOOLING_SHA`):** `b8064e4ae603162c3485a0ffd990f5061cc9b3e1`
**Measured candidate:** `fee4edba7600b405d417928a9da768d6315483b8`
**Safe rollback:** `dd68fcbf4e6f33f214dd2cf9d0a5ed4811980909`

## 1. Repository and historical reconciliation

- `git branch --show-current` = the required literal; `git rev-parse HEAD` =
  `e8744d3…`; `git status --porcelain` empty.
- `main` unchanged at `ddcbe778…`; `e8744d3` is a descendant of `main` and of the
  accepted B candidate `ae7e416`.
- Historical **PR 15G-C** remains recorded as **REJECTED / SAFE ROLLBACK**; its
  fused two-pass implementation was not resurrected. This work is **PR 15H-C**.
- Baseline B tests passed before any C edit:
  `search::unified::b_tests` (6) and the B controller suite (33).

## 2. Source anchors verified

| Symbol | Fact |
|---|---|
| `SegmentReader::doc_keys()` | `SegmentResult<Rc<Vec<DocumentKey>>>`, lazy + cached |
| `SegmentReader::doc_key()` | delegates to `doc_keys()` and clones the requested key |
| `SegmentReader::doc_key_selected()` | selective one-hit path |
| `collect_mixed` | `total_hits` checked increment, key before sort validation, `single_hit_segment = scored.len()==1 && doc_count>=1024` |
| `consider_borrowed_keyword_candidate` | B borrowed sort view; owned key parameter |
| `candidate_charge` | charges retained key + tuple, not transient clones |

Protected and unchanged by design: `segment/reader.rs`, `column.rs`,
`typed_compare.rs`, `execute.rs`, `score.rs`, codecs, Cargo, CI, public APIs.

## 3. Blob identities at preflight

`search/unified.rs` `5492645c…`, `segment/reader.rs` `e4dddcaf…`,
`column.rs` `263d40df…`, `typed_compare.rs` `0e72728a…`,
`execute.rs` `5d0ac481…`, `score.rs` `2921afc5…`, `Cargo.lock` `732b2b9e…`,
`.github/workflows/ci.yml` `374583d3…`.

## 4. Counterexamples challenged

1. Zero scored hits must not initialize the full key cache (`HC-U01`).
2. One hit on a >=1024 segment must keep `doc_key_selected()` (`HC-U02`).
3. One hit on a <1024 segment uses the full cached decoder (`HC-U03`).
4. `u64::MAX` / out-of-range ids return the exact `Corrupt { context: "doc keys", detail: "doc id out of range" }` (`HC-U09/U10`).
5. A malformed losing keyword still fails before discard (existing B fixup test).
6. Duplicate retained logical key surfaces even on a loser (`HC-U15`).
7. `LegacyDecode`/non-single column clones exactly one key and uses the legacy path (`HC-U16`).
8. No `&DocumentKey` escapes the segment loop; winners clone once.
9. Batch/cursor/aggregation/typed/JSON/geo/relevance/multi-sort stay legacy.

## 5. Frozen experiment

Six ordered warm lanes (P1 common/100K/K100, P2 common/100K/K10, P3 medium/100K/K100,
G1 common/10K/K100, G2 rare/100K/K100, G3 absent/100K/K100); 3 baseline trials;
four mirrored paired blocks; 5 warmups + 20 samples. C thresholds:
P1/P2 median `A−B >= 2.000 ms`, >=3/4 blocks >= 1.000 ms, no block < −1.000 ms;
P3 median > −2.000 ms; G1 > −2.000 ms; G2/G3 > −1.000 ms.
