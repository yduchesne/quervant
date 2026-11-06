# PR 15H-A3 — final disposition

**Terminal state: `MEASUREMENT_BLOCKED`.** Diagnostic investigation delivered; no
optimization accepted, retained or merged.

## What was established

1. **Source identity:** A2 B is a descendant of accepted A and differs only by the
   historical helper, the fixed `H_A2_MIN_POSTINGS = 8_192` dispatch and
   test-only code in `execute.rs`/`unified.rs`. Helper/scorer regions hash-match
   the historical 15H-A candidate.
2. **Sparse source path:** below the gate, the exact original eligible loop runs.
   The gate adds only a shape match, one `.len()` and one comparison — no new
   loop, allocation, decoder/validator, statistics pass or callback.
3. **Route behavior:** untimed tests reconfirm 0/1/4,999 postings → 0 linear
   invocations and 8,192+ → 1; score bits, cursor, budget and cancellation
   differentials pass.
4. **Codegen:** B's `evaluate_lexical_with` has 713 vs 693 instructions and adds
   `cmpq $0x2000` plus a helper call; the helper adds 716 instructions; `.text`
   grows 14,384 bytes.
5. **A/A control failed:** identical binaries varied by up to 1.37× on the 100K
   sparse lane, exceeding the 1.15 cap; the 10K lane passed.

## What is not established

- No causal root cause (`ROOT_CAUSE_UNRESOLVED` would require a qualified
  campaign; the frozen precedence yields `MEASUREMENT_BLOCKED`).
- No confirmation or refutation of the historical A2 sparse regression.
- No V2/V3 intervention result (prereq-blocked).
- No CPU/instruction/branch/cache attribution (`perf` unavailable).

## Deliverables

| Item | Path |
|---|---|
| Four-lane diagnostic controller + 28 tests | `benchmarks/pr15h_a3/` |
| Sealed A/A campaign (blocked) | `target/pr15h-a3/aa-01` (ignored) |
| Codegen artifacts | `target/pr15h-a3/profiles/objdump/` (ignored) |
| Evidence set | `docs/pr-artifacts/pr-15h-a3/` |
| A3 controller tests (tracked) | `benchmarks/pr15h_a3/test_run.py` |

## Production source

```
git diff --quiet 7a136f7f299c2f460401b9d92dcef37d219ea98c HEAD -- crates/quervant-core/src/search
# exit 0
```

No production Rust, format, codec, storage, CI or dependency change; no V2/V3
commit exists. No push, PR or merge was performed.

## Next required human action

1. Review the A/A control evidence and decide whether the planned follow-up (a
   separate approved PR) should first harden the measurement environment
   (more blocks/longer windows/CPU isolation) before re-attempting A/B and V2/V3.
2. If a push is authorized, run exact-final-HEAD CI.

A3 itself finishes with this investigation, not an optimization.
