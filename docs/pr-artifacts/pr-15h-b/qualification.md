# PR 15H-B — qualification and disposition

## Performance qualification

| Requirement | Result |
|---|---|
| Sealed baseline before production edit | PASS |
| Baseline `--verify-only` byte reproduction | PASS |
| Candidate descendant, clean detached worktrees | PASS |
| Same tooling SHA for baseline/paired | PASS |
| Frozen corpus/oracle/adapter unchanged | PASS |
| Same host/WSL fingerprint and native ext4 | PASS |
| Byte-identical query-only index digests | PASS |
| 8 slots / 48 lane records / 960 samples / 240 warmups | PASS |
| 16 clear probes / 48 oracle validations | PASS |
| Frozen nearest-rank medians and absolute gates | PASS |

**Decision: `PERFORMANCE_ACCEPTED`** — both 100K common primaries clear the
5 ms median gate (P1 6.266 ms, P2 12.213 ms), the medium lane and all guards are
within their absolute floors.

## Correctness disposition

All B unit, column-codec, comparator, public-path integration and full workspace
suites pass. Wire/format/index bytes are unchanged (equal index digests). No
unexpected source path was modified.

## Disposition

`PERFORMANCE_ACCEPTED_LOCAL_QA_PASS`: the candidate is retained on the required
branch for human review. No push, PR, merge or self-approval occurred; hosted CI
is `CI_PENDING`. The plan's `PERFORMANCE_REJECTED_SAFE_ROLLBACK` path was not
triggered.

## Residual risks

- The benchmark measures one WSL2 host and six frozen lanes; no claim is made for
  other query shapes, storage, distributed execution or cross-engine parity.
- The source-only design cannot prove allocator counts in a release binary; the
  test-only witnesses bound owned materializations on representative fixtures,
  and the latency result quantifies the targeted effect only.
- BM25 scoring and document-key resolution remain unchanged and may dominate
  other workloads; true late scoring / ordinals / block postings remain out of
  scope.
