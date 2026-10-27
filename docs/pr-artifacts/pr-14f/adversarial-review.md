# PR 14F — adversarial review and negative evidence

**Verdict:** the benchmark campaign is **qualified** (3 of 3 trials, validator
and strict auditor PASS) at source SHA `7df492023397a512e400b03865a989020eff1430`.
PR 14F is **not accepted**: the raw archive is not durable, final-head CI has
not run, and there is no independent review or merge authorization. Campaign 1
at `162cbfea…` failed on a harness path defect and is disclosed, not hidden.

## 1. Primary negative evidence and residual gaps

1. **Raw archive is not durable.** All raw CSVs, reports, contention records and
   logs are staged under ignored
   `target/pr14-p4/archive/7df492023397…/` with `SHA256SUMS`. That directory is
   disposable. No operator-designated external archive locator exists, so
   **RAW ARCHIVE BLOCKED** remains true and fully reproducible acceptance
   cannot be claimed.
2. **No final-head CI.** `gh` authentication is invalid; no PR exists. The local
   stable/MSRV gates pass, but `rust`, `msrv` and `rustfs` have not run on an
   immutable PR head.
3. **No independent review or merge authorization.** The agent’s artifacts are
   not a substitute for a reviewer.
4. **Campaign 1 failed.** At `162cbfea…`, t1 ran correctly but the wrapper
   aborted because the relative report directory resolved under the cargo
   package working directory. t2/t3 never ran. The defect was fixed only after
   operator approval, with a new source lock and three fresh trials. The failed
   t1 is preserved and hashed; it was not promoted.
5. **Attestation timing.** The operator supplied the idle attestation before
   campaign 1. The corrected campaign was executed under the same explicit
   three-trial authorization after the operator approved the fix, with the host
   independently observed idle and every live contention check `clear`. A strict
   reviewer may still require a fresh attestation for a future campaign; this is
   disclosed as a process gap, not as fabricated data.
6. **No cross-engine or SLO evidence.** The workload is Quervant-local vs
   Quervant-RustFS only; the report makes no superiority or production-tail
   claim.

## 2. Harness and evidence gaps

| Gap | Severity | Detail / disposition |
|---|---|---|
| Relative report dir vs cargo cwd | **Resolved** | Campaign 1 found it; approved absolute-path fix at `7df4920`; shell tests now assert the absolute path |
| `QUERVANT_P4_IDLE_CONFIRMED` truthiness | Medium | Runner uses `var(...).is_ok()`, so `0` reads as true. Qualified runs always set `1`; no diagnostic run was made. Fixing the runner is outside the approved scope |
| Auditor input binding | Medium | The auditor validates a report’s `raw_csv` by path/content, but the report JSON contains no CSV hash. The manifest records hashes; a later check must verify them. A substituted CSV with consistent checks is not cryptographically bound to the report |
| “Verify file hash in manifest” sequencing | Low | The audit runs before the manifest exists; hashes are computed and the manifest records them. Manifest comparison is a later invariant |
| Qualified `--trials` restriction | Low | Qualified mode rejects `--trials` ≠ 3; this prevents an unpublishable campaign but is stricter than the parser range |
| Contention detector scope | Medium | `/proc` sees this WSL guest only, not the Windows host or other WSL guests. `clear` is best-effort, as documented in `docs/BENCHMARKING.md` |
| Detector vs RustFS container | Low | The provider container is outside the runner subtree; all three samples were `clear` with 0 competing processes |
| W06/W07 CSV semantics | Medium | CSV `hits` are batch response lengths (1 and 3). The auditor checks those values; the real oracle (4 × 5,000; S/F/S) runs inside the runner and is not re-derived by the auditor |
| Corpus digest prose mismatch | Medium | The workload doc describes eight hashed fields; the runner hashes five blobs. The emitted digest matches the fixed contract and all historical reports, so X12 did not fire. Prose correction needs separate approval |
| Historical raw CSV absent | Low | Historical `raw_csv` paths do not resolve; provenance only, not re-audited |
| `stat -f` type string | Low | `stat -f` prints `ext2/ext3` for ext4; `df -T` confirms ext4 |
| `unittest discover` | Low | Hyphenated `test-pr14f-audit.py` is not importable as a module; direct invocation runs 25 tests |
| Pre-existing `docs/TESTING.md` conflict markers | Low | Committed before PR 14F; not an executable input; untouched |
| Log-based `1 passed` check | Low | Convenience check; validator/auditor inspect the actual JSON/CSV |
| Three trials only | Low | Descriptive dispersion, not statistical significance |
| Post-measurement analysis tool | Low | The percentile helper was written after the source lock and is kept only in the untracked raw archive; it cannot affect measurements. The tracked measurement-input diff is empty |

## 3. Claims explicitly not made

- No durable raw archive or fully reproducible acceptance.
- No fresh-head CI, review or merge.
- No cross-engine (Tantivy/Lucene) comparison or superiority.
- No production p99/SLO/throughput/capacity claim.
- No claim that W08 was measured or passed.
- No pooling of cold/warm or local/remote lanes.
- No claim that the historical `ab9b2d7` trials describe the current tree.
- No claim that local tests or provider health substitute for the benchmark.

## 4. Reviewer attack surface

A reviewer should independently check:

1. Source lock `7df4920…` is an ancestor of the evidence head; the executable
   diff between them is empty; campaign 1’s t1 was not reused.
2. Historical report hashes match `baseline-inventory.md` §3.
3. The three tracked reports carry `sha=7df4920…`, `qualified=true`,
   `idle_confirmed=true`, `contention=clear`, `dirty=false`.
4. The three CSVs have 280 rows each, 14 pairs × 20 samples, and the hashes
   match the manifest/archive.
5. The three contention records are `clear` and hash-match.
6. The raw archive staging is not misrepresented as durable.
7. W06/W07 values are interpreted as response lengths, not group counts.
8. No cold/warm or local/remote distributions were pooled.
9. The corrected campaign’s attestation timing is acceptable, or a fresh
   attestation is required before treating the result as release evidence.
10. PR-head CI, review and merge authorization are genuinely independent.
