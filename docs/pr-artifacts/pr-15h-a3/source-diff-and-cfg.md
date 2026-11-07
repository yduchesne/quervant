# PR 15H-A3 — source diff, sparse control flow and codegen

## Source reconciliation (A=7a136f7, B=569132d)

Only `execute.rs` and `unified.rs` differ. `unified.rs` production code is
byte-identical to A; its diff is `#[cfg(test)]` tests only.

### Sparse control flow (`execute.rs::evaluate_lexical_with`)

| Step | A (accepted) | B (rejected A2) |
|---|---|---|
| `build_leaf_data` (decode + live filter) | unchanged | unchanged |
| eligible flag | original eligible loop | `single_term_posting_count(&leaf_data, typed)` → shape match + `terms[0].postings.len()` |
| gate | none | `if posting_count >= H_A2_MIN_POSTINGS` → helper |
| below gate | original loop | **exact original loop** (same `effective_live_examination_count`, charge, cancel poll, predicate, `BTreeSet::insert`) |
| at/above gate | original loop | `evaluate_single_term_linear` |
| ineligible | original live scan | unchanged |
| scoring / ledger / release | original | unchanged for below-gate |

The sparse path adds a shape match, one `.len()` read and one integer comparison.
It adds **no** loop, heap allocation, decoder/validator, statistics pass or
`is_match` callback relative to A. The gate reads the already decoded,
effective-live filtered vector; it does not scan postings or consult the
dictionary.

### Helper identity

| Region | SHA-256 (B == 15H-A candidate `dce8f02`) |
|---|---|
| `evaluate_single_term_linear` | `966554bccc5d5d5a852c53713ec566122981de480a40157e92b7e6be100f1592` |
| `score_single_term_linear` | `9b811a609f4be3d16543b10a811325f1f2c417021d750966d559d5a2a4cf40ac` |

The helper retains the historical 48 B matched + 64 B scored virtual charges,
`0.0 + contribution` scoring, ascending-doc output and typed error behavior.

## Reconciled route witnesses (untimed, candidate worktree)

`cargo test -p quervant-core --lib search::unified::phase15h_a2_tests` → 10 passed
(0/1/4,999 postings → 0 linear invocations; 8,192/8,193/12,500/49,999 → 1).
`search::execute::linear_term_a2_tests` → 2 passed. `pr15h_a2_dispatch` → 8 passed.

## Machine-code inspection (observation only)

Exact release binaries: A from the AA campaign, B built from the candidate
worktree with identical flags/profile. File SHA-256:

| Arm | Binary SHA-256 |
|---|---|
| A | `3370083e501931f412a6a914730d2538b717900c22904d3fe83e39acdbaaf14f` |
| B | `8682403a00d66de1eedef718510487d03a75e25c238dbce78d002504c41f867c` |

`size` text bytes: A 3,172,458; B 3,186,842 (+14,384).

| Symbol | A | B |
|---|---|---|
| `evaluate_lexical_with` | 0xdc9 / 693 instructions | 0xe69 / 713 instructions |
| `evaluate_single_term_linear` | absent | 0xdef / 716 instructions |

B's `evaluate_lexical_with` contains the gate and a call absent from A:

```
24dcb2: cmpq $0x2000,0x28(%r14)
24dd0e: call 24e4c0 <…evaluate_single_term_linear…>
```

This proves only that the gate/helper are compiled and reachable in B. It does
not prove they execute on sparse lanes (they do not) and, because the A/A
control failed, it is **not** causal evidence (A3-D49/D50/D68).
