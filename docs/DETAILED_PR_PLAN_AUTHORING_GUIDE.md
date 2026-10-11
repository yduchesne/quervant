# Detailed PR Plan Authoring Guide

> **Trawler-specific precedence:** [ARCHITECTURE.md](ARCHITECTURE.md), [ROADMAP.md](ROADMAP.md), [BENCHMARKING.md](BENCHMARKING.md), and [../AGENTS.md](../AGENTS.md) define the authoritative design and gates. Use the current repository's actual Rust crate names and commands, not illustrative examples. For v0.1, support local-only and RustFS-backed indexes, one logical writer and concurrent readers; keep distributed services and vectors out of scope. Compare Trawler local-only with Lucene and Tantivy under correctness-gated workloads, and benchmark RustFS caching separately.

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

If a repository defines an authoritative test harness, name it and require it for acceptance. Distinguish what is tested from how the required topology is established. For example, if `scripts/e2e.sh` owns the production-path browser stack, a direct `npx playwright test` invocation against an arbitrary running stack is not equivalent acceptance evidence.

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

Use an exact PR identifier and a narrow capability description.

Example:

```markdown
# PR 22A — Research Storage, Corpus Ingestion, and Retrieval Foundation
```

Avoid vague titles such as:

```text
RAG improvements
Coordinator updates
Misc fixes
Research work
```

The title should communicate the dominant architectural concern.

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

This section is essential for coding-agent plans.

Document the important implementation facts discovered during repository inspection.

Include:

- exact files;
- relevant classes/functions;
- current behavior;
- existing abstractions;
- important limitations;
- preceding PR semantics.

Example:

```markdown
## Existing retrieval abstraction

`src/.../app/research.rs`

Already contains:

```rust
// illustrative contract
struct SegmentStore(ABC):
    @abstractmethod
    async def retrieve(self, query: ResearchQuery) -> list[RetrievedChunk]:
        ...
```

**Do not create another retrieval ABC.**
```

This section prevents the agent from reasoning from stale architecture.

Use code snippets only for the contractually important parts.

Do not dump entire source files.

---

# 9. Scope

Define what the PR owns.

Prefer capability-oriented subsections.

Example:

```markdown
## In scope

### A. Durable segment reference identity
...

### B. Immutable research-result persistence
...

### C. Controlled re-indexing
...
```

Each item should correspond to the PR's dominant concern.

If the in-scope section becomes a list of several unrelated systems, reconsider whether the PR should be split.

---

# 10. Explicitly out of scope

This section is mandatory for agent-executed plans.

State adjacent work that the coding agent might otherwise reasonably attempt.

Example:

```markdown
## Explicitly out of scope

PR X must not add:

- Coordinator graph changes;
- report generation;
- external service prompts;
- distributed task infrastructure;
- generic evaluation framework;
- unrelated refactors;
- new data sources;
- API endpoints.
```

Include future PR ownership where useful:

```text
PR 22B owns Research Agent execution.
PR 22C owns Coordinator integration.
PR 22D owns research evaluation.
```

This makes the PR boundary operational rather than aspirational.

---

# 11. Detailed implementation sections

Break implementation into numbered Parts and Steps.

Recommended hierarchy:

```text
Part 1 — Domain contract
    Step 1
    Step 2

Part 2 — Persistence
    Step 3
    Step 4

Part 3 — Application service
    Step 5

Part 4 — Production composition
    Step 6

Part 5 — Tests
```

Each Step should specify:

```text
where
what
why
required behavior
constraints
acceptance criteria
```

Example:

```markdown
## Step 7 — Update `PgVectorSegmentStore`

Modify the existing retriever only.

Its result mapping must expose:

- segment reference identity;
- document identity;
- source-record identity;
- chunk sequence.

Do not change:

- cosine ranking semantics;
- indexing compatibility filtering;
- source filters;
- result limits;
- empty-result behavior.
```

This is preferable to:

```text
Update retriever to support segment references.
```

---

# 12. Separate semantic identity from persistence identity

Whenever a PR involves persistence, explicitly identify different forms of identity.

For example:

```text
row ID
    = persistence identity

semantic key
    = logical object identity

content hash
    = representation/change identity

external source ID
    = upstream identity
```

Do not let the coding agent infer these distinctions.

This is especially important for:

- append-only records;
- replaceable indexes;
- history tables;
- relationships;
- observations;
- cached/derived data;
- versioned artifacts.

---

# 13. Define ownership boundaries

For every important object, say who creates it and who persists it.

Example:

```text
IndexWriter
    creates normalized Segment

Analyzer
    creates RelationshipAssertion

Application persistence service
    resolves/upserts Entity/Relationship
    appends RelationshipObservation

IndexReader
    creates structured analytical decision

Application layer
    owns persisted Assessment IDs
```

Ownership ambiguity is a common source of agentic implementation drift.

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

A detailed plan should distinguish unit correctness from production-path correctness.

A vertical slice should exercise as much real application architecture as practical.

Example:

```text
real-format fixture
    ↓
production parser
    ↓
application service
    ↓
real index storage stored functions/repositories
    ↓
real segment index retrieval
    ↓
structured result
```

Fake only external boundaries required for determinism.

State exact assertions.

Do not merely say:

```text
add integration tests
```

---

# 20. Failure behavior

Define how failures behave.

Examples:

```text
malformed graph output
    -> typed lifecycle error
    -> not raw KeyError

missing investigation
    -> typed IndexNotFoundError

provider HTTP failure
    -> bounded provider outcome
    -> no partial persistence

invalid segment reference
    -> validation failure
    -> no ResearchResult persistence
```

Also specify cancellation behavior for async code:

```text
Tokio.CancelledError propagates
```

unless architecture explicitly requires otherwise.

---

# 21. Idempotency

If the operation can be retried, define idempotency explicitly.

Questions to answer:

```text
What identifies the operation?
What is safe to repeat?
What is append-only?
What is replaceable?
What is deduplicated?
What changes when inputs change?
What remains stable?
```

Example:

```text
same document + same indexing identity
    -> no chunk replacement

same document + new indexing identity
    -> re-embed/replace derived chunks

semantic segment reference identity
    -> remains stable across pure re-indexing
```

---

# 22. Index format and compatibility

Specify versioned segment/manifest formats, committed versus disposable data, recovery, upgrade/rebuild expectations, integrity checks, reader retention and garbage collection. Do not silently rewrite immutable committed segments or promise cross-version compatibility without an explicit decision.

---

# 23. Documentation updates

Name the exact docs that should change and what each should say.

Example:

```text
ARCHITECTURE.md
    ownership and lifecycle

DATABASE.md
    schema/transaction semantics

TESTING.md
    deterministic fixture and vertical-slice rules

EVALUTrawlerON.md
    delivered metrics only

PR_PLAN.md
    completion status only
```

Avoid broad:

```text
update documentation
```

Also specify docs that should **not** be expanded into future architecture.

---

# 24. Expected files changed

Provide a likely file map.

Example:

```text
domain/foo.rs
app/foo_service.rs
app/persistence/repositories.rs
infrastructure/persistence/postgresql/foo_repository.rs
new migration
tests/unit/...
tests/integration/...
docs/...
```

Label it as expected rather than mandatory when current implementation may justify a nearby location.

This helps the coding agent recognize scope drift.

---

# 25. Files that should normally not change

This is highly effective for constrained implementation.

Example:

```text
The PR should not normally require behavioral changes in:

app/orchestration/coordinator.rs
app/orchestration/graph.rs
domain/assessment.rs
api/**
evaluation/**
```

If the coding agent believes one must change, it should evaluate a STOP condition rather than casually editing it.

---

# 26. Explicit reuse requirements

List existing abstractions/components that must be reused.

Example:

```text
Reuse:

IndexWriter
SegmentStore
ObjectStore
IndexWriter
PgVectorSegmentStore
IndexWriter
IndexReader
```

Then state:

```text
Do not duplicate them under new feature-specific names.
```

This is especially important in mature codebases where an agent may prefer creating a new local abstraction instead of understanding the existing one.

---

# 27. STOP conditions

STOP conditions are one of the most important parts of a low-reasoning coding-agent plan.

They define when the coding agent must stop implementation and request an architectural decision rather than improvise.

Examples:

```text
STOP if:

1. required behavior needs a Coordinator redesign;
2. a migration would destroy authoritative data;
3. the existing abstraction cannot represent the required operation;
4. implementation requires a future-PR feature;
5. the public third-party API cannot satisfy the planned contract;
6. a long index storage transaction around external I/O appears necessary;
7. a new generic framework appears necessary;
8. tests require live Internet;
9. scope requires weakening QA or coverage gates;
10. current main already implements the planned capability differently.
```

Specify the report format:

```text
When stopping, report:

file/function/schema
current behavior
required invariant
why current architecture cannot satisfy it
smallest reviewer decision needed
```

STOP conditions prevent a coding agent from turning uncertainty into architecture.

---

# 28. Recommended implementation sequence

Give the coding agent an ordered execution path.

Example:

```text
Phase 0 — Baseline
Phase 1 — Pure domain changes
Phase 2 — Persistence
Phase 3 — Application service
Phase 4 — Production adapter
Phase 5 — Integration path
Phase 6 — Docs/full QA
```

Within Phase 0:

```text
1. re-read current files;
2. identify migration head;
3. run targeted baseline tests;
4. run relevant integration tests;
5. record green baseline;
6. only then edit.
```

This prevents the agent from mistaking pre-existing failures for its own regressions.

---

# 29. Reviewer checklist

Create a checklist grouped by architectural concern.

Example:

```markdown
## Persistence

- [ ] one UoW = one index storage transaction
- [ ] no external I/O inside transaction
- [ ] repository ABC reused
- [ ] rollback tested

## Scope

- [ ] no Coordinator changes
- [ ] no report generation
- [ ] no future evaluator framework

## Provenance

- [ ] every claim cites stable provenance
- [ ] no source Segment invented from contextual research
```

The checklist should be usable independently of the implementation narrative.

---

# 30. PR-level acceptance criteria

End with a numbered, exhaustive-but-focused completion list.

Example:

```text
PR is complete only when:

1. domain model exists;
2. invalid provenance is rejected;
3. persistence round-trips;
4. rollback works;
5. canonical integration path works;
6. idempotency is proven;
7. no future-PR behavior is introduced;
8. docs are reconciled;
9. ./build.sh --qa passes;
10. ./integration-test.sh passes.
```

These criteria become the final contract for both coding agent and reviewer.

Group completion gates by concern when the PR has multiple test layers, for example:

```text
Implementation
Targeted/unit tests
Integration/vertical slice
E2E
Stability/stress
Regression
Repository QA
Documentation/status
```

For each nontrivial gate, make clear what constitutes evidence. A required test that exists but has not run is **NOT TESTED**, not PASS. A related regression suite passing does not prove a new feature-specific acceptance journey.

Do not allow retries to conceal a required first-attempt or stability guarantee. If acceptance requires `retries=0`, a later rerun can diagnose the failure but cannot retroactively make the failed acceptance run green.

Prefer objective statements.

Avoid:

```text
implementation is clean
tests are good
architecture is robust
```

unless accompanied by measurable meaning.

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

When the PR is one part of a series, show where it fits.

Example:

```text
PR 22A
foundation
   ↓
PR 22B
agent
   ↓
PR 22C
orchestration
   ↓
PR 22D
evaluation
```

This reinforces why adjacent features must not leak into the current PR.

---

# 33. Critical coding-agent rules

End with a few memorable rules.

Examples:

> **Do not rebuild infrastructure that already exists on `main`.**

> **Do not turn uncertainty into a new abstraction. STOP when the plan requires an architectural decision.**

> **Fake external boundaries, not the production architecture being tested.**

> **Preserve transactional and provenance invariants even if a shortcut would reduce code.**

These should summarize the highest-risk failure modes.

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

Avoid:

## Speculative future architecture

Do not design three future releases merely because the current PR creates an extension seam.

## Unnecessary implementation trivia

Do not prescribe every variable name or every assertion.

## Broad cleanup

Avoid:

```text
while here, refactor...
modernize...
clean up...
generalize...
```

unless required for the PR invariant.

## Generic best practices without repository context

Prefer:

```text
Use the existing IndexWriter and versioned stored-function convention.
```

over:

```text
Follow database best practices.
```

## Unbounded optional work

Avoid:

```text
optionally improve...
consider adding...
if time permits...
```

A coding-agent execution plan should have deterministic scope.

---

# 36. Plan sizing and PR splitting heuristic

Split a PR if it combines independently reviewable concerns such as a new segment codec, new commit protocol, distributed placement, and query execution. Prefer small contract-first PRs, then implementation, integration, and correctness/benchmark hardening. Do not introduce v0.2 distribution or v0.3 vector functionality into v0.1 plans.

---

# 37. Fixup plans

When review finds defects after implementation, do not rewrite the original detailed plan.

Create a narrow fixup plan.

A fixup plan should contain:

```text
review finding
exact current-main defect
required invariant
minimal code changes
regression tests
explicit non-goals
acceptance criteria
```

Example:

```text
PR 21C2
    malformed graph output normalization only

not:
    redesign IndexReader
```

Fixups should be substantially narrower than the originating PR.

---

# 37A. Follow-up plans for partially implemented or stopped PRs

When implementation stops partway through a PR and work will continue on the same PR, create a follow-up plan rather than pretending the original plan is unexecuted.

A follow-up plan must:

1. inspect fresh `main` and the current implementation branch;
2. reconcile any coding-agent status/STOP report with the actual branch;
3. inventory DONE + VERIFIED, DONE NOT VERIFIED, PARTIAL, NOT STARTED, and BLOCKED work;
4. preserve verified implementation unless a demonstrated defect requires change;
5. identify the exact remaining implementation delta;
6. identify feature-specific acceptance evidence still missing;
7. distinguish previously passed regression gates from new feature acceptance gates;
8. carry forward applicable architectural invariants, non-goals, reuse rules, and STOP conditions;
9. define the exact conditions under which the PR may finally be marked complete.

Do not inflate the follow-up plan by restating already completed implementation instructions as new work. Include enough existing-state detail that a low-reasoning agent knows what must remain unchanged.

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
