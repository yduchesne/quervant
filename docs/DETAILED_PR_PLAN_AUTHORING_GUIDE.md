# Detailed PR Plan Authoring Guide

> **Trawler-specific precedence:** [ARCHITECTURE.md](ARCHITECTURE.md), [ROADMAP.md](ROADMAP.md), [BENCHMARKING.md](BENCHMARKING.md), and [../AGENTS.md](../AGENTS.md) define the authoritative design and gates. Use the current repository's actual Rust crate names and commands, not illustrative examples. For v0.1, support local-only and RustFS-backed indexes, one logical writer and concurrent readers; keep distributed services and vectors out of scope. Compare Trawler local-only with Lucene and Tantivy under correctness-gated workloads, and benchmark RustFS caching separately.

See [TESTING.md](TESTING.md) for the required mocking/faking policy, 85% coverage gate, and unit plus real-boundary integration testing requirements.

## Purpose

This document defines the recommended structure, level of specificity, and authoring process for a **Detailed PR Execution Plan**.

It is intended for implementation PRs that will be executed by a coding agent, especially a lower-reasoning agent that performs well when given:

- a narrow architectural objective;
- an accurate description of the current codebase;
- explicit reuse requirements;
- concrete implementation sequencing;
- precise invariants;
- deterministic tests;
- clear acceptance criteria;
- explicit non-goals and STOP conditions.

This guide is adapted for Trawler's Rust search engine, durable local and remote storage, and correctness-gated benchmarking.

A detailed PR plan is **not** a roadmap entry, design brainstorm, or general feature specification. It is an executable implementation contract.

---

# 1. Core principle

A good detailed PR plan should make the coding problem substantially more deterministic before implementation begins.

The coding agent should not need to make major architectural decisions while implementing the PR.

The plan should answer:

```text
Why does this PR exist?
What exactly is wrong or missing on current main?
What architecture already exists?
What must be reused?
What is the desired final behavior?
What files/components are likely involved?
What order should implementation follow?
What invariants must remain true?
How will each behavior be tested?
What is explicitly outside scope?
When must the coding agent STOP instead of improvising?
How will a reviewer determine that the PR is complete?
```

The desired effect is:

```text
architecture/reasoning
        happens primarily during planning

implementation
        becomes constrained execution

review
        verifies conformance to explicit invariants
```

---

# 2. Prerequisite: inspect current `main`

Never write a detailed PR plan solely from:

- `PR_PLAN.md`;
- an earlier architectural discussion;
- a previous PR plan;
- memory of the repository;
- assumptions about what preceding PRs implemented.

Before producing the plan, inspect fresh `main`.

For Trawler repository work, verify at minimum:

```text
Rust workspace and crate boundaries
public traits and APIs
segment codecs and format versions
Directory, SegmentStore, SegmentCache and ObjectStore
manifest publication and recovery
analyzers, postings and query execution
configuration, features and telemetry boundaries
unit/integration/fault-injection tests
benchmark harnesses and documentation
preceding PR implementation
```

Also search for existing implementations of concepts the roadmap says should be added.

Example:

```text
Roadmap says:
    "add cache abstraction"

Current main already has:
    SegmentCache

Detailed plan must say:
    reuse SegmentCache

It must NOT introduce:
    AnotherSegmentCache
    RemoteCacheManager
    or another duplicate abstraction
```

A detailed plan is based on the **delta from current main**, not merely on the roadmap description.

---

# 3. Reconcile roadmap scope with current implementation

After inspecting `main`, determine whether the roadmap PR is still correctly scoped.

There are three possible outcomes.

## Outcome A — Scope remains appropriate

Proceed with one detailed PR plan.

## Outcome B — Much of the roadmap work already exists

Narrow the detailed plan to the missing work.

Do not reimplement existing architecture merely to match old roadmap wording.

## Outcome C — The roadmap PR contains multiple independent architectural concerns

Split the PR before writing the detailed plan.

A useful heuristic is:

> A coding-agent PR should normally have one dominant architectural problem.

For example:

```text
Bad monolithic scope:

segment format
+ remote storage
+ distributed placement
+ lexical query execution
+ benchmark framework

Prefer:

PR A — storage contracts
PR B — segment and commit lifecycle
PR C — lexical search
PR D — correctness and benchmark hardening

This pattern reduces implementation ambiguity and makes regressions easier to isolate.

---

# 3A. Replanning an in-progress PR

A detailed plan may be written after implementation has already started. In that case, do not treat the roadmap or original plan as if no work exists.

Inspect the implementation branch as well as fresh `main`, then classify each originally planned capability:

| Classification | Meaning | Plan treatment |
|---|---|---|
| DONE + VERIFIED | implementation exists and required evidence has passed | preserve it; do not reimplement; include regression coverage |
| DONE, NOT VERIFIED | implementation exists but required acceptance evidence is missing | verify it before completion |
| PARTIAL | only part of the required behavior exists | describe the exact remaining delta |
| NOT STARTED | required behavior does not exist | provide normal implementation steps |
| BLOCKED | progress requires a decision, dependency, or unavailable environment | apply the plan's STOP rules |

For an in-progress PR, the plan must explicitly distinguish:

```text
what is already implemented
what has actually been verified
what remains to implement
what remains only to verify
what prior evidence is reusable
what evidence must still be produced
```

Do not instruct the coding agent to rewrite working code merely because the original plan described its creation. Do not treat a status report as proof by itself; reconcile its claims with the branch and available test evidence.

---

# 3B. Execution evidence and completion discipline

For every mandatory quality or acceptance gate, distinguish three different facts:

```text
test/code exists
    !=
test was executed
    !=
test passed in the required environment/topology
```

A gate is complete only when the required command has actually executed successfully in the required environment. Compilation, code inspection, a related test, a previous run against different code, or reasoning that a test "should pass" is not acceptance evidence.

Plans should classify test evidence where relevant:

```text
baseline evidence
    proves the starting branch/environment was healthy

regression evidence
    proves previously delivered behavior remains healthy

feature acceptance evidence
    proves the new capability itself works
```

**Regression evidence must not substitute for feature acceptance evidence.**

If a repository defines an authoritative test harness, name it and require it for acceptance. Distinguish what is tested from how the required topology is established. For example, if a RustFS integration harness owns the storage topology, a unit test against a fake adapter is not equivalent acceptance evidence.

Include exact commands when command form, environment variables, browser/project selection, worker count, retry count, cycle count, or harness setup materially changes what is exercised. Otherwise, naming the repository-prescribed gate is sufficient.

For integration/stability work, state the authoritative harness, actual storage and search path, deterministic substitutions, exact RustFS/local filesystem topology, concurrency, retry settings, and repeat counts. A unit test with a fake ObjectStore is not equivalent to an integration test against RustFS. A benchmark is not a correctness test.

---

# 3C. Required failure classification

When a mandatory gate fails, the plan should require the coding agent to classify the failure as one of:

1. introduced regression;
2. feature implementation defect;
3. deterministic pre-existing failure;
4. nondeterministic/flaky failure;
5. environment/harness failure.

A failure may be called pre-existing only after reproducing it on the relevant baseline/base commit or otherwise producing equivalent evidence. A failure may be called flaky only after evidence demonstrates nondeterminism. "Unrelated" is not a sufficient classification by itself.

The final implementation report must state unresolved failures explicitly. Do not hide them behind reruns, retries, or a green subset.

---

# 3D. Status is derived from acceptance

Keep these states separate:

```text
implementation status
test/evidence status
PR completion status
roadmap/documentation status
```

A feature can be implemented but unverified. A test can exist but be unexecuted. A PR is complete only when its mandatory acceptance gates pass.

Roadmap `[DONE]`, completion markers, release notes, or equivalent status documentation must be updated **after** the required acceptance gates pass. A documentation status marker is a consequence of completion; it is never evidence of completion.

---

# 4. Recommended document structure

A detailed PR plan should normally contain the following sections.

```text
Title
Purpose
Architectural invariants
Current-main facts
In-progress status/evidence reconciliation (when applicable)
Scope
Explicitly out of scope
Detailed implementation parts/steps
Test matrices
Integration/vertical-slice tests
Authoritative test harness / execution topology (when relevant)
Failure classification and completion evidence
Documentation updates
Expected files changed
Files that should normally not change
Explicit reuse requirements
STOP conditions
Recommended implementation sequence
Reviewer checklist
PR-level acceptance criteria
Suggested PR description
Dependency/next-PR context
Critical coding-agent rules
```

Not every PR requires every section, but omission should be deliberate.

---

# 5. Title

Use an exact PR identifier and a narrow capability description, e.g. `# PR 2 — Local Directory Contract and Conformance Tests`. Avoid vague titles such as "storage improvements" or "search fixes".

---

# 6. Purpose

The Purpose section explains **why this PR exists** and what architectural problem it closes.

It should normally include:

1. what preceding PRs delivered;
2. what remains incomplete or incorrect;
3. what this PR will establish;
4. what major future PR depends on it.

Example pattern:

```markdown
## Purpose

PR X completes the application-level execution seam introduced by PR Y.

Current main already provides A, B, and C. It does not yet provide D.

PR X therefore adds D without redesigning A/B/C.

The dominant architectural concern is:

> [one-sentence invariant/problem statement]
```

The Purpose section should make it impossible to mistake the PR for a broader feature phase.

---

# 7. Architectural invariants

State the rules that must remain true regardless of implementation details.

These are more important than class names.

Examples:

```text
One logical writer publishes complete committed generations.

Readers observe immutable committed snapshots.

Local-only indexes must not require remote services.

Remote-backed indexes use authoritative ObjectStore state and disposable local cache.

Cache eviction never deletes authoritative objects.

Synchronous scoring hot loops never block on remote I/O or telemetry export.
```

Use diagrams where they clarify ownership:

```text
IndexWriter
    produces immutable segments
          ↓
CommitPublisher
    publishes a durable generation
          ↓
IndexReader
    opens a stable snapshot
```

Invariants give the coding agent a way to resolve small implementation choices without inventing architecture.

---

# 8. Current-main facts

Inspect fresh `main` and document actual Rust crates, source paths, public traits, implementations, tests, and preceding PR semantics. Show only the essential contract snippets, in valid Rust. Explicitly name existing abstractions to reuse (such as `Directory`, `SegmentStore`, `SegmentCache`, `ObjectStore`, if they actually exist). Do not invent paths or APIs from the roadmap.

---

# 9. Scope

Define what the PR owns using capability-oriented subsections: e.g. local file durability, immutable segment identity, manifest publication, or reader visibility. Each item must serve the dominant architectural concern.

---

# 10. Explicitly out of scope

State adjacent work explicitly. For v0.1 storage PRs, exclude distributed Coordinator/etcd, vector/HNSW, unrelated query-planner changes, experimental SPDK/DPDK and unapproved storage providers. Assign deferred work to later PRs. STOP if an excluded capability becomes necessary.

---

# 11. Detailed implementation sections

Break work into numbered parts and steps: public contracts, immutable segment/manifest persistence, reader/writer lifecycle, local or RustFS adapter integration, then tests. Each step specifies **where, what, why, required behavior, constraints, and acceptance criteria**. Use verified file paths; distinguish mandatory behavior from illustrative implementation details.

Example: update an existing `SegmentCache` to verify complete downloaded files before exposing them, enforce disk limits, and preserve pinned reader handles. Do not change segment formats or manifest publication as a side effect.

---

# 12. Distinguish index and storage identities

Explicitly separate logical document IDs, immutable segment IDs, manifest generations, content digests, local cache keys and remote ObjectStore keys. Define which are stable across merges, retries, and re-materialization.

---

# 13. Define ownership boundaries

Specify which component creates immutable segment data, publishes committed generations, materializes/verifies remote segments, evicts cache entries, and opens reader snapshots. Avoid duplicate ownership of commit publication or garbage collection.

---

# 14. Commit and durability boundaries

Specify segment persistence, manifest publication, reader visibility, crash windows, retries, old-reader retention and garbage collection. Separate local filesystem durability (including fsync/rename requirements) from remote S3-compatible publication. Never assume RustFS/S3 offers conditional writes or listing guarantees without verification.

---

# 15. External boundaries and deterministic tests

Fake external or nondeterministic boundaries, not the actual Trawler architecture under test.

```text
Production: segment codec -> SegmentStore/SegmentCache -> S3 adapter -> RustFS
Remote integration: same production path -> test RustFS
Unit fault injection: same core path -> deterministic failing ObjectStore
Local durability: real filesystem -> restart -> reader recovery
```

Use fake adapters for isolated unit cases, but do not count them as RustFS acceptance evidence.

---

# 16. Verify external framework contracts

If the PR depends on:

- Rust/Tokio;
- S3-compatible object-storage clients;
- RustFS behavior;
- Lucene and Tantivy APIs;
- filesystem durability semantics;
- FST/regex libraries;

verify the exact current contract before finalizing implementation instructions.

Prefer:

```text
installed dependency source/API
official documentation
current upstream schema
```

Do not write implementation instructions from remembered APIs.

Add a STOP condition when the required public contract is unavailable.

---

# 17. Deterministic behavior tables

For policy/state-machine work, define cases in tables.

Example:

| Case | Input | Expected |
|---|---|---|
| exact entity capacity | pivot already admitted | allowed |
| entity overflow | new entity | rejected |
| repeated pivot | already investigated at equal/better depth | skipped |
| unchanged evidence | analysis already performed | no repeated analysis |

Tables are particularly effective for low-reasoning coding agents because they convert policy into finite cases.

---

## Mandatory coverage and integration acceptance

Every executable-code PR plan must require **at least 85% automated line coverage of applicable production Rust workspace code**, enforced in CI with a reproducible documented command (e.g. `cargo llvm-cov`). Specify the measurement scope, exclusions, and whether the plan introduces code not yet covered by the workspace-wide gate. Do not treat a selective per-file percentage as proof of workspace compliance. For a documentation-only PR, explicitly mark code coverage and test execution not applicable.

Specify **both relevant unit tests and relevant integration tests**. Integration tests must exercise real production boundaries wherever the PR affects them; examples include filesystem durability/restart, RustFS S3 interactions, cache eviction/reload, commit/reader visibility, and end-to-end lexical indexing/search. Deterministic fakes and fault injection supplement but do not replace required real-boundary acceptance. A feature is not complete merely because unit tests pass or the coverage threshold is met.

Required acceptance evidence: coverage command executed and threshold met; targeted unit suite passed; named integration harness/topology executed and passed; relevant failure and recovery scenarios passed. Classify missing infrastructure as BLOCKED and failures using the guide's required failure taxonomy. The roadmap may be marked DONE only after all mandatory gates succeed.

---

# 18. Unit test matrix

Specify important unit cases explicitly.

Use stable IDs when useful:

| ID | Case | Expected |
|---|---|---|
| C1 | valid input | accepted |
| C2 | duplicate identity | rejected |
| C3 | missing provenance | rejected |
| C4 | exact budget capacity | legal |
| C5 | budget overflow | rejected |

Benefits:

- coding agent can map implementation to tests;
- reviewer can detect missing cases;
- plan discussion can refer to a stable case ID;
- future fixup plans can identify regressions precisely.

Do not attempt to enumerate every trivial test.

Enumerate behavioral boundaries.

---

# 19. Integration and vertical-slice tests

Exercise the actual Trawler path: versioned corpus -> analyzer -> writer -> immutable segments -> durable commit -> fresh reader -> query -> verified hits. For remote storage, run the same core path against RustFS with an empty cache, eviction/reload, interrupted downloads and restart. Define exact assertions; unit fakes cannot substitute for production-path acceptance.

---

# 20. Failure behavior

Specify typed errors for invalid/corrupt segment data, missing manifests, incomplete downloads, commit conflicts, unsupported query semantics and exceeded resource budgets. Never expose a partially materialized segment. Define Tokio cancellation and cleanup without publishing incomplete generations.

---

# 21. Idempotency

For every retryable operation, specify identity, safe repetition, atomic publication, temporary-file cleanup and stable reader visibility. Retried downloads must not poison caches; uncertain commits must not produce conflicting visible generations; merges must not mutate snapshots held by existing readers.

---

# 22. Index format and compatibility

Specify versioned segment/manifest formats, committed versus disposable data, recovery, upgrade/rebuild expectations, integrity checks, reader retention and garbage collection. Do not silently rewrite immutable committed segments or promise cross-version compatibility without an explicit decision.

---

# 23. Documentation updates

Name exact authoritative files and changes: `docs/ARCHITECTURE.md` for contracts and ownership, `docs/ROADMAP.md` for scope/status, `docs/BENCHMARKING.md` for reproducibility and performance gates, and `AGENTS.md` only when engineering policy changes. Do not mark work DONE before acceptance passes.

---

# 24. Expected files changed

Provide a verified, likely Rust crate/test/benchmark/doc file map. Label proposed paths as illustrative until confirmed on current main.

---

# 25. Files that should normally not change

Identify protected areas (e.g. `trawler-distributed` during v0.1, vector/HNSW, unrelated segment codecs and service APIs). Unexpected edits require review or STOP.

---

# 26. Explicit reuse requirements

List existing traits and implementations to reuse. Avoid duplicate `Directory`, `SegmentStore`, `SegmentCache`, `ObjectStore` or analyzer abstractions. Confirm existence on current main rather than assuming roadmap targets are implemented.

---

# 27. STOP conditions

STOP and request a decision if the planned work requires v0.2 distributed architecture or v0.3 vectors, weakens commit durability or immutable reader visibility, relies on unverified RustFS/S3 semantics, introduces synchronous remote I/O in scoring loops, needs an unapproved generic abstraction, requires live uncontrolled external services, or cannot pass correctness/QA gates. Also STOP when current main already implements the capability differently.

On STOP, report exact file/trait, observed behavior, violated invariant, evidence, and the smallest decision needed. Do not improvise.

---

# 28. Recommended implementation sequence

Phase 0: inspect fresh main and implementation branch (if any), run baseline tests and record failures.

Phase 1: establish Rust API/format contracts and invariants.

Phase 2: implement the smallest segment/storage/query change.

Phase 3: integrate local filesystem and/or RustFS as required.

Phase 4: run deterministic unit, integration, recovery and fault-injection tests.

Phase 5: run applicable correctness-gated benchmarks and instrumentation-overhead checks.

Phase 6: execute repository-prescribed formatting, linting, tests and documentation reconciliation.

Do not invent exact command names; inspect the repository's current CI and scripts.

---

# 29. Reviewer checklist

- [ ] Reused current-main abstractions; no duplicate framework.
- [ ] Committed generations are complete and reader-safe.
- [ ] Local durability or remote RustFS recovery verified as applicable.
- [ ] Cache eviction never deletes authoritative objects.
- [ ] Query/segment correctness and negative cases tested.
- [ ] No v0.2 distribution or v0.3 vector scope leakage.
- [ ] Benchmarks are correctness-gated and reproducible when applicable.
- [ ] Required commands actually passed; unresolved failures classified.
- [ ] Documentation reflects delivered behavior, not future promises.

---

# 30. PR-level acceptance criteria

State objective gates grouped by implementation, targeted/unit tests, integration/fault injection, correctness, benchmarking, regression, repository QA, and documentation. Required tests must **run and pass** in the specified environment. Exclude unsupported cross-engine semantics rather than presenting misleading comparisons. Mark roadmap completion only after mandatory gates pass. Relative Lucene/Tantivy performance parity is not a v0.1 release requirement.

---

# 31. Suggested PR description

Provide a short ready-to-use PR description.

It should summarize:

```text
what was added
what existing architecture was reused
what important invariant was established
what is explicitly not included
```

This is useful both for the coding agent and later review.

---

# 32. Dependency and next-PR context

Show the dependency-ordered sequence and identify the owner of deferred work. v0.1 covers standalone lexical search, v0.2 distribution, and v0.3 vector/hybrid retrieval.

---

# 33. Critical coding-agent rules

**Reuse existing contracts. Do not invent architecture to resolve uncertainty. Fake external boundaries, not the core execution path. Preserve immutable committed generations, local durability, remote cache correctness, and hot-path performance. STOP when the plan requires an architectural decision.**

---

# 34. Level of specificity

A detailed PR plan should be highly specific about:

```text
behavior
ownership
invariants
state transitions
persistence semantics
transaction boundaries
test cases
scope
failure behavior
reuse
```

It may be less prescriptive about:

```text
private helper names
minor file organization
local refactoring details
exact internal algorithms where multiple implementations satisfy the same contract
```

The goal is not to write the code in prose.

The goal is to remove architectural ambiguity.

---

# 35. What not to put in a detailed PR plan

Avoid speculative future-release designs, unrelated refactors, arbitrary helper naming, unbounded optional work, or generic advice detached from verified Rust code. Prefer precise existing-trait reuse and concrete correctness gates over generic "follow best practices" instructions.

---

# 36. Plan sizing and PR splitting heuristic

Split a PR if it combines independently reviewable concerns such as a new segment codec, new commit protocol, distributed placement, and query execution. Prefer small contract-first PRs, then implementation, integration, and correctness/benchmark hardening. Do not introduce v0.2 distribution or v0.3 vector functionality into v0.1 plans.

---

# 37. Fixup and follow-up plans

For review defects, create a narrow fixup with the observed defect, required invariant, minimal changes, regression test, non-goals and acceptance. Do not rewrite the original plan.

For stopped/partially implemented PRs, inspect fresh main and the implementation branch, reconcile status reports against actual code and test evidence, classify DONE + VERIFIED / DONE NOT VERIFIED / PARTIAL / NOT STARTED / BLOCKED, preserve verified work, and plan only the remaining delta. Keep feature-specific acceptance distinct from regression evidence.

---

# 38. Review process after implementation

Review the implementation against:

```text
current main
+
detailed PR plan
+
architectural invariants
+
tests
```

Do not review only the diff mechanically.

Verify:

1. required behavior exists;
2. existing architecture was reused;
3. STOP-boundary features did not leak in;
4. tests actually exercise the intended production path;
5. negative/boundary cases exist;
6. documentation matches delivered behavior;
7. acceptance criteria are satisfied.

If the implementation deviates but is architecturally superior, evaluate the deviation explicitly rather than declaring noncompliance solely because a suggested private implementation detail changed.

Behavioral and architectural contracts outrank incidental naming.

---

# 39. Reusable template

Copy this outline and fill in repository-verified details:

```text
# PR X — Narrow capability
Purpose and dominant invariant
Current-main facts and existing abstractions
In-progress branch/evidence reconciliation (if applicable)
In scope / explicitly out of scope
Detailed numbered implementation parts and steps
Index/storage identities, ownership and durability boundaries
Unit-test matrix with stable IDs
Local/RustFS integration and fault-injection matrix
Correctness and benchmark acceptance where applicable
Execution topology, exact authoritative commands and evidence
Failure classification, cancellation and retry/idempotency behavior
Documentation updates
Expected files / normally unchanged files
Explicit reuse requirements
STOP conditions and required STOP report
Ordered phases (baseline -> implementation -> tests -> QA)
Reviewer checklist and objective PR acceptance gates
Suggested PR description and next-PR dependencies
Critical coding-agent rules
```

Do not copy illustrative paths or commands without checking current main.

---

# 40. Compact authoring checklist

Before delivering a detailed PR plan, verify:

- [ ] Fresh `main` was inspected.
- [ ] For an in-progress/follow-up plan, the implementation branch and status report were reconciled with actual code/evidence.
- [ ] Existing work is classified as DONE + VERIFIED, DONE NOT VERIFIED, PARTIAL, NOT STARTED, or BLOCKED where applicable.
- [ ] The roadmap scope was reconciled with actual implementation.
- [ ] Existing abstractions are explicitly identified.
- [ ] The PR has one dominant architectural concern.
- [ ] Invariants are explicit.
- [ ] Ownership boundaries are explicit.
- [ ] Transaction boundaries are explicit where relevant.
- [ ] Production vs test/fake boundaries are explicit.
- [ ] Each deterministic/fake substitution is named precisely; ambiguous "fake" terminology is avoided.
- [ ] The authoritative test harness/execution topology is named where relevant.
- [ ] Exact commands/options are specified when invocation semantics affect acceptance.
- [ ] External API assumptions were verified where relevant.
- [ ] Scope and non-goals are explicit.
- [ ] Implementation is broken into ordered steps.
- [ ] Boundary cases have deterministic tests.
- [ ] At least one production-path vertical slice exists where appropriate.
- [ ] Failure/idempotency semantics are specified.
- [ ] Expected files and normally-unchanged files are listed.
- [ ] Existing components that must be reused are listed.
- [ ] STOP conditions prevent architectural improvisation.
- [ ] Reviewer checklist exists.
- [ ] Objective PR-level acceptance criteria exist.
- [ ] Baseline, regression, and feature-acceptance evidence are distinguished where relevant.
- [ ] Required stability/stress evidence is explicit where relevant.
- [ ] Required-gate failures must be classified with evidence before being called pre-existing/flaky/unrelated.
- [ ] Roadmap/DONE status is explicitly downstream of successful acceptance gates.
- [ ] Full repository QA gates are named.
- [ ] Future PR responsibilities are not accidentally absorbed.

---

# Final standard

A successful detailed PR plan should let a coding agent spend most of its effort on **implementation**, not architecture discovery.

The plan is sufficiently detailed when a reviewer can ask:

> "Did the implementation satisfy this contract?"

rather than:

> "What architecture did the coding agent decide to build?"

That is the standard.
