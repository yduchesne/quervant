# QOS-003C — Incremental inference invalidation

**Version 1.0-design · D01–D42 approved · Post-v0.1**

## Semantics and dependencies (D01–D06)

**D01:** Incremental results equal complete least fixed point `E_G=lfp(X ↦ F_G ∪ T_{P_G}(X))`. **D02:** Asserted facts, direct memberships, live identities and pinned definitions authoritative; caches disposable. **D03:** Incomplete/budget-exhausted validation rejects atomically. **D04:** Compiled predicate dependency graph includes characteristics, inverse/subrelationships, archetype rules. **D05:** SCCs evaluated collectively in condensation DAG order. **D06:** Constraint dependencies include hierarchy reachability, irreflexivity, asymmetry, domain/range and class disjointness.

## Additions (D07–D09)

**D07:** Semi-naive delta propagation through affected SCCs until fixed point. **D08:** Specialized reachability/inverse algorithms permitted only with equivalence proof; reject hierarchy cycles. **D09:** Positive conclusive witness may terminate early; absence requires complete relevant evaluation.

## Retractions (D10–D13)

**D10:** Retract derived fact only after proving no valid proof remains. **D11:** DRed-style private overdelete then rederive from candidate authoritative state; never expose intermediate overdeletion. **D12:** Optional dependency/support summaries; simple support counts alone unsafe for recursive self-supporting cycles. **D13:** Specialized affected-region retraction only if complete; otherwise full fallback.

## Mixed batches (D14–D16)

**D14:** Final candidate state determines consistency; intermediate operation states need not satisfy constraints. **D15:** Normalize net additions and removals against base snapshot. **D16:** Retract/rederive, propagate additions, iterate SCCs to fixed point, validate; equivalent to complete evaluation.

## Memberships (D17–D19)

**D17:** Recompute effective inherited memberships of affected instances, respecting alternate inheritance paths. **D18:** Reject disjointness contradictions. **D19:** Revalidate effective inferred relationship domain/range, not only directly asserted incident edges.

## Ontology changes (D20–D22)

**D20:** Semantic fingerprint includes classes, relationships, archetypes, rules, constraints and hierarchy bindings; presentation-only changes do not affect it. **D21:** Initially perform complete inference and validation on semantic definition changes; invalidate mismatched caches. **D22:** Strengthened constraints and altered definitions must validate all candidate data before publication.

## Constraint closure and fallback (D23–D25)

**D23:** Identify complete affected constraint closure; skip only if proven unaffected. **D24:** Inconclusive incremental validation triggers complete authoritative candidate fallback; fallback exhaustion rejects. **D25:** Logical stages: structure/identity; membership/DAG; effective membership; inference; relationship constraints; domain/range; disjointness/global constraints; publication authorization.

## Caches (D26–D29)

**D26:** Key includes index, snapshot, ontology fingerprint, predicate and bindings/family. **D27:** Snapshot cache results logically immutable and safely evictable. **D28:** Cache false only after complete evaluation; never cache cancelled/exhausted false. **D29:** Initially no cross-generation reuse absent a proof of unchanged dependencies/fingerprints.

## Publication and recovery (D30–D35)

**D30:** Private candidate includes live instances, direct classes, asserted relationships, ontology and compiled program. **D31:** Internal validation certificate binds base generation, candidate digest, ontology fingerprint, validator version and valid result; not a formal cryptographic proof. **D32:** Recheck base generation, digest, fingerprint and writer conflicts immediately before publish; otherwise rebuild/revalidate. **D33:** Any invalidity, exhaustion, cancellation or internal inconsistency rejects without partial publication. **D34:** Recovery reconstructs from last durable authoritative generation and recomputes inference as needed. **D35:** Corrupt inferred caches discarded; corrupt authoritative data fail closed.

## Budgets and verification (D36–D42)

**D36:** Bound derived facts, rule firings, iterations, intermediate relations, memory, time, traversals and spill. **D37:** Record mutation/inference counts, SCCs, firings, rederivations, fallbacks, latency, budget failures and cache metrics without sensitive values by default. **D38:** Bounded fallback reason codes; separately budgeted complete fallback allowed, complete failure rejects. **D39:** Independent complete in-memory least-fixed-point reference evaluator. **D40:** Differential compare effective facts and validation decisions. **D41:** Test multiple proofs, last proof deletion, cyclic grounding removal, mixed changes, cycles, class constraints, program change, PIT, caches, recovery, compaction, budgets. **D42:** Property-based invariants: determinism, final-state equivalence, no unsupported/missing facts, strict rejection, isolation, recovery; ≥85% line coverage.

**Materialization boundary:** Do not require persistently materializing all inferred closure facts. Query-time goal-directed inference and private candidate validation are valid; caches are optional and disposable.
