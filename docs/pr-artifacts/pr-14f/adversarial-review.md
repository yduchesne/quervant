# PR 14F — adversarial review and negative evidence

**Verdict:** the harness is better qualified than before, but the PR's central
deliverable — three fresh qualified trials — **does not exist**. PR 14F remains
blocked and must not be accepted on the strength of local tests or a healthy
provider.

## 1. Primary negative evidence

1. **Zero trials.** No `pr14_p4_v1` trial was executed. There is no CSV, report
   JSON, contention record, p50/p95/p99 table, or archive. The success criterion
   is unmet.
2. **No operator attestation.** The human did not state that competing workloads
   are stopped and the host is idle. The agent did not fabricate one and did not
   run a diagnostic as a substitute.
3. **The host was not idle.** Load average after local validation was
   `1.02 5.82 4.96`. Running a trial now would contradict any idle claim.
4. **No end-to-end provider exercise.** Digest and `/health` were verified, but
   no S3 write/read, bucket creation, commit or cold bootstrap was performed by
   the benchmark. "Provider prequalified" means image identity + health only.
5. **No CI, review or merge.** Local `gh` credentials are invalid; no PR exists;
   no check run is claimed; no independent review exists.

## 2. Harness and evidence gaps

| Gap | Severity | Detail / disposition |
|---|---|---|
| `QUERVANT_P4_IDLE_CONFIRMED` truthiness | Medium | Runner uses `std::env::var(...).is_ok()`, so `0` reads as true. Qualified mode always sets `1`; a diagnostic run would record `idle_confirmed=true` without an attestation. No diagnostic was run. Fixing the runner is outside AD-F05's authorized scope |
| Auditor input binding | Medium | The auditor validates a report's `raw_csv` by path/content but the report JSON contains no CSV hash, so the report is not cryptographically bound to that CSV. Stage E manifests add hashes, but a later check must verify them |
| "Verify file hash in manifest" sequencing | Low | The audit runs before the manifest exists. Hashes are computed but manifest comparison is deferred to Stage E; recorded in `harness-corrections.md` §4 |
| Qualified `--trials` restriction | Low | The wrapper rejects qualified `--trials` ≠ 3 even though the parser accepts 1–20. This prevents an unpublishable campaign but is stricter than a literal reading of AD-F07. A future multi-trial campaign needs an approved trial-ID/selection design |
| Contention detector scope | Medium | `/proc` sees Linux processes in this WSL guest only; it cannot observe the Windows host or other WSL guests. `clear` is best-effort, as documented in `docs/BENCHMARKING.md` |
| Detector vs RustFS container | Low | The pinned container is outside the runner subtree. If it ever exceeded the 0.5-core suspect threshold it would be counted as `other`. It is idle now; a future campaign should confirm `clear` live |
| Stub-only wrapper proof | Medium | `test-scripts.sh` proves parser/env/validator wiring with PATH stubs, not a real cargo/provider invocation. It cannot substitute for Stage D |
| W06/W07 semantics | Medium | CSV `hits` are batch response lengths (1 and 3). The real oracle (4 × 5,000; S/F/S) runs inside the runner before timing. The auditor intentionally checks the recorded lengths, so it cannot prove the oracle ran |
| Corpus digest prose mismatch | Medium | The workload doc describes eight hashed fields; the runner hashes five blobs (with `ts` = `n`) and excludes `body`/`loc`/`ip`. The emitted digest matches the fixed contract and historical reports, so X12 does not fire, but the prose is inaccurate. Correcting it requires human approval (AD-F02) |
| Historical raw CSV absent | Low | Historical JSON `raw_csv` paths do not resolve here. They are provenance only and were not edited (X20). Historical results cannot be re-audited |
| `stat -f` type string | Low | `stat -f -c %T` prints `ext2/ext3` for ext4 because of shared statfs magic; `df -T` confirms ext4. Recorded, not a blocker |
| `unittest discover` | Low | The hyphenated `test-pr14f-audit.py` is not importable as a module, so discovery finds 0 tests. Direct invocation (explicitly allowed) runs 25 |
| Pre-existing `docs/TESTING.md` conflict markers | Low | Committed on `origin/main` before PR 14F; not an executable input and not modified. Requires a separate documentation fix |
| Contentious `--idle-confirmed` placement | Low | The wrapper's qualification gate runs before provider env checks. A caller can pass the flag and still be rejected later; no false qualification is possible |
| Log-based `1 passed` check | Low | The wrapper greps its own run log. This is a convenience check; the validator/auditor inspect the actual JSON/CSV, so log spoofing alone cannot produce a qualified report |

## 3. Claims explicitly not made

- No fresh performance number, speedup, regression or SLO.
- No cross-engine (Tantivy/Lucene) comparison.
- No claim that the historical `ab9b2d7` trials describe current `main`.
- No claim that W08 was measured or passed.
- No claim that local tests, provider health or coverage substitute for the
  benchmark qualification.
- No claim that CI passed, that review occurred, or that PR 14 is accepted.

## 4. Reviewer attack surface

A reviewer should independently check:

1. That the source-lock SHA is an ancestor of the evidence head and the
   executable diff between them is empty.
2. That historical report hashes match `baseline-inventory.md` §3.
3. That any future trial reports carry the source-lock SHA and reference three
   distinct CSVs under the qualification directory.
4. That the operator attestation is a human statement, not a metric inference.
5. That the pinned digest is the exact `1803faef…6a3c` reference and the provider
   was actually used, not mocked.
6. That W06/W07 CSV values are interpreted as response lengths, not group
   counts.
7. That no cold/warm or local/remote distributions were pooled.
8. That the raw CSV archive actually exists before any reproducibility claim.
