# Quervant Benchmarking Methodology — Target Process

**Status:** Proposed, human-oriented methodology for the **v0.1-bench** infrastructure refactoring. This document explains what a benchmark means, how measurements are acquired and compared, and how confidence in the results is established. The target implementation is specified in [BENCHMARKING_ARCHITECTURE.md](BENCHMARKING_ARCHITECTURE.md); migration and sequencing appear in [BENCHMARKING_MIGRATION.md](BENCHMARKING_MIGRATION.md) and [BENCHMARKING_ROADMAP.md](BENCHMARKING_ROADMAP.md).

**Scope and precedence.** This describes the target methodology for **new** experiments, not a retroactive reinterpretation of prior Quervant measurements. An experiment's pre-frozen protocol is authoritative for its exact workloads, arm order, sample counts, readiness gates, exclusion rules, numerical decision thresholds and recovery permissions. Historical experiments and their original verdicts are unchanged. Values such as 12 blocks, five warmups, twenty samples, 10,000 bootstrap resamples, or four retained blocks are examples from recent protocols—not universal defaults. The target framework must support different valid protocols and benchmark families.

## 1. Why we benchmark, and what counts as a conclusion

A performance benchmark asks a specific question: for a defined workload and environment, does implementation B differ meaningfully from implementation A? Examples include search latency, indexing throughput, memory consumption, storage footprint or compaction time. A benchmark is **not** simply a stopwatch. It must distinguish four outcomes:

1. **Correctness:** Did the implementations perform the same intended work and return valid results?
2. **Experimental validity:** Were measurements gathered under the predeclared and authorized conditions?
3. **Statistical evidence:** How large is the observed difference, and how uncertain is it?
4. **Decision:** Does that evidence meet the predeclared performance, resource and safety rules?

A complete acquisition is not automatically valid, a valid acquisition is not automatically a performance improvement, and a performance improvement does not automatically authorize merging or production deployment.

## 2. Plain-language glossary

| Term | Meaning | Example |
| --- | --- | --- |
| **Experiment** | The question to investigate, plus agreed conditions and success criteria | Does a bitset prefilter reduce Top-K search latency? |
| **Benchmark suite** | Collection of workloads and measurement/verification procedures | Search-latency suite |
| **Workload** | The actual work performed, including data, operation and load shape | Search over a fixed index |
| **Dataset / corpus** | Fixed source data; the index and its build details are recorded separately | 100,000-document corpus |
| **Lane** | A single measurement scenario fixed across comparable implementations | 100K corpus, rare match, Top-K=100, warm cache |
| **Arm** | One implementation/treatment with known code, binary and settings | Baseline, prefilter bitset, exact set |
| **Baseline / control arm** | Reference against which candidates are compared | Existing search implementation |
| **Block** | A small group of executions in which all compared arms appear in predeclared balanced multiplicities | A,B,B,A |
| **Slot** | One ordered execution of one arm within one block; it can measure several lanes | Block 2, slot 3, arm B |
| **Warmup** | Execution that prepares the specified state; not counted as a timed sample | Five untimed queries |
| **Sample** | One timed observation for one lane during one slot | 1.27 milliseconds |
| **Campaign** | Complete execution of one prescribed schedule, including its environment and records | One 12-block treatment campaign |
| **Series** | Group of campaigns/control(s) required by the protocol | A/A control plus two treatment campaigns |
| **A/A control** | Comparison of equivalent baseline arms to detect measurement bias/instability | Baseline vs identical baseline |
| **Oracle (correctness)** | Independent way to establish the correct functional result | Exact expected hit set, not measured latency |
| **Protocol** | Frozen instructions: workloads, order, counts, conditions, statistics, stops | balanced-paired protocol v1 |
| **Gate** | Mandatory check authorizing a transition or acceptance | Host readiness or evidence admission |
| **Pruning / exclusion** | Predefined exclusion of an *entire lane–block pair* from statistics, applied symmetrically across arms *after acquisition* | Remove block 3 for lane L from A and B alike |
| **Retained block** | A block left eligible for a lane after permitted exclusions | Nine retained out of twelve |
| **Paired comparison** | Compare arms inside the same block/lane to reduce sensitivity to changing environment | B/A latency ratio in block 4 |
| **Confidence interval (CI)** | A procedure-derived uncertainty interval for an estimate, not a guarantee about any single run | 95% paired-bootstrap interval |
| **Bootstrap** | Repeated resampling of existing blocks to estimate uncertainty | 10,000 resamples of whole blocks |
| **Frozen policy** | Predeclared mathematical rules converting evidence into eligibility and selection decisions | Memory guardrail and strict tie rule |
| **Independent policy oracle** | Separately implemented checker of decision rules; distinct from the functional correctness oracle | Second implementation confirms selected strategy |
| **Admission receipt** | Content-bound record that specific evidence passed eligibility/integrity checks | Hash-linked Gate A PASS |
| **Attestation** | Final record of exactly which evidence and checks support a conclusion | Accepted source and artifact hashes |
| **Inconclusive** | Valid evidence does not establish the required decision | CI crosses a decision boundary |
| **HARD STOP** | No permission to continue this official attempt under current conditions | Mandatory readiness fails |

**Important:** An *arm* answers **which implementation?**; a *lane* answers **which workload scenario?**. A *slot* is one execution of one arm and can encompass several lanes. A *block* groups slots so the arms can be compared fairly.

## 3. End-to-end workflow

```text
Question and workload design
  -> Define arms, lanes, metrics, controls, thresholds and failures
  -> Compile, validate and freeze protocol BEFORE official measurements
  -> Untimed correctness oracle + source/build/workload identity checks
  -> Host readiness and A/A qualification, as prescribed
  -> Execute the frozen campaign/series (balanced, randomized blocks)
  -> Seal raw records, verify acquisition and admit evidence (Gate A)
  -> Calculate paired statistics and apply frozen policy (Gate B)
  -> Independently verify calculations and decisions (Gate C)
  -> Check required QA and dependent gate receipts (Gate D)
  -> Freeze final logical evidence snapshot and attest (Gate E)
  -> Report effects, uncertainty, exclusions, conclusions and limitations
```

The **pre-acquisition authorization gates** (protocol freeze, correctness, host readiness, A/A) differ from the **post-acquisition logical acceptance gates A–E**. Passing an A/A control does not replace evidence admission; passing Gate A does not establish a performance win.

### 3.1 Define the question before looking at the results

Decide what metric and direction matter: **lower latency is better**, while **higher throughput is better**. Decide which workload lanes represent the objective and which are guardrails against regressions; include resource constraints (memory, storage) as needed. Specify cache regimes, query semantics, input fixture and expected answer. A warm-cache result cannot stand in for cold-start behavior. Build/index time is **outside** query-latency timing unless it is explicitly the operation under test.

For external engines, require semantically comparable requests, data and result validation; mark unsupported or differently defined lanes **noncomparable**, rather than computing misleading ratios. Define intended platform and acceptable environmental variation.

### 3.2 Freeze the protocol before acquisition

Before the first *official* control or treatment measurement, fix: source and binary identities; datasets/indexes and exact correctness oracle; lanes; arms/runtime modes; randomized schedules/seeds; block/slot counts; warmup/sample counts; host and readiness checks; control rules; exclusion and retention criteria; analysis/resampling procedure; decision thresholds; allowed retries; required campaigns; and escalation/HARD STOP conditions. Record a cryptographic protocol digest and authorization identity.

A control run acquired before the required freeze remains exploratory evidence even if it is later structurally verified. Changing protocol thresholds or schedules after seeing unfavorable results creates a **new study**, not a correction to the original one.

## 4. How blocks, arms, slots and samples work

### 4.1 Illustrative two-arm experiment

Suppose we compare **A** (baseline) and **B** (candidate), across two fixed lanes (L1 and L2). Instead of running all A measurements followed by all B measurements, measure both arms close together in time:

```text
              SLOT 1   SLOT 2   SLOT 3   SLOT 4
Block 1:        A        B        B        A
Block 2:        B        A        A        B
Block 3:        A        B        A        B
Block 4:        B        A        B        A
...
Each slot:      run L1 warmups + timed samples
                run L2 warmups + timed samples
```

Each block contains two occurrences of each arm. This reduces systematic *order bias* and permits arm comparisons within relatively similar conditions. The drawn orders are illustrative, **not necessarily a statistically sufficient positional-balance design** and not an approved schedule.

### 4.2 What is randomized—and what is balanced?

The order of arm assignments to **slot positions** is generated by an approved randomization algorithm with a frozen seed or exact schedule. The algorithm is constrained so every block has the required arm multiplicities and arm positions are suitably balanced across the campaign. The protocol must name the randomization algorithm, seed, schedule validation, and permissible order patterns. The coding agent must not improvise a new random order once a run begins.

- **Randomization** reduces systematic advantages caused by changes over time.
- **Balance** prevents one arm from consistently getting the early/late positions.
- **Pairing** makes the within-block A/B difference the object of analysis.

A recent four-arm Quervant protocol used **12 blocks × 8 slots**, with two slots each for A, L, P and H in every block. Its A/A control used **12 × 4 slots**. Earlier protocols used different schedules. None of these counts is a universal requirement.

### 4.3 Warmups and timed observations

Each slot executes the required lanes in the protocol-defined order. For every lane, execute untimed warmups, then gather timed samples. For example, a historical shape is five warmups plus twenty samples *per lane per slot*. Do not multiply twenty samples into twenty independent experimental blocks: samples within a slot share cache, process and environmental conditions.

Example: 12 blocks × 8 slots = 96 slot executions. With 72 lanes and 20 timed samples per lane/slot, the arithmetic would be 138,240 timed observations **if all lanes execute in every slot**. Actual sample totals depend on the frozen lane/schedule coverage; never infer them from a simplified diagram.

### 4.4 Why use multiple blocks?

A single A/B timing pair can be distorted by CPU scheduling, thermal changes, cache warming, background activity or virtualization noise. Repeated, balanced blocks permit estimates of variability across time. Blocks are treated as the independent unit for the *protocol-defined* paired bootstrap; the protocol must consider other dependence sources such as correlated campaigns or host effects when making broader claims.

## 5. Host qualification, correctness and A/A control

Before timing, establish the correct output through an **independent functional oracle**: matching hit sets, counts, order, scores or other semantics as applicable. A faster wrong answer is not a performance win.

Verify that source, binary, corpus, committed index, workload, toolchain, host and cache regime correspond to the frozen identities. Observe protocol-required host conditions such as affinity, CPU busy/steal time, competing processes, filesystem and runtime capabilities. Host-readiness is **time-sensitive**: a passed check yesterday cannot be reused to authorize today's acquisition. On WSL2, a quiet guest does not prove absence of activity on the Windows host.

An **A/A control** runs equivalent baselines under the prescribed schedule to test measurement stability and ordering bias. Both arms should have the same semantics/build when so defined; evaluate the frozen control thresholds. A failing mandatory control blocks official treatment acquisition. A passing A/A is evidence of stability, **not proof that the host is noise-free**. Do not substitute successful A/A for failed readiness.

## 6. Acquisition and failure rules

Execute the exact frozen slots, keeping all samples (including slow ones), identifiers, source/build records and readiness observations. Measurements must not be selectively retried just because a candidate was slower or more variable than expected. **Timing variability is normally retained as data** under the target randomized-block methodology; a historical frozen protocol that makes a particular drift condition fatal remains authoritative for its own runs.

Categorize:
- **Structural/correctness failure:** wrong answer, bad binary, missing mandatory slot, corrupted output, unauthorized change → abort or invalidate as the frozen protocol requires.
- **Host-readiness failure:** mandatory host condition not met → do not acquire official samples; stop under prescribed recovery rules.
- **Timing variability alone:** retain and analyze after acquisition unless the frozen protocol explicitly specifies a fatal condition.
- **Crash/interruption:** preserve partial evidence and status; resume/retry only if explicitly preauthorized. Otherwise HARD STOP; start a separately authorized new experiment if desired.
- **Publication error:** no silent overwrite, cherry-picking or reuse of an aborted official artifact path.

Keep the raw experiment exactly as acquired. Rejection, interruption and inconclusive results remain part of the audit record.

## 7. From slots to statistical comparison

For a recent randomized two-occurrence-per-arm protocol:

1. Compute the **median timed latency** for each lane within each slot.
2. For each lane, arm and block, calculate the **arithmetic mean of the two slot medians** for that arm. This gives one block-level estimate per arm.
3. Within the same lane and block, compute **candidate/baseline latency**. Below 1 favors the candidate; above 1 favors the baseline.
4. Apply predeclared admissible block exclusions (Section 8) without changing raw samples.
5. Compute the **median of retained block ratios** for that lane.
6. Calculate the protocol-specified confidence interval using **paired resampling of whole blocks** rather than independently resampling individual samples.
7. Apply frozen policy to the point estimate, interval, guardrails and resource constraints.

```text
slot_median(arm,lane,slot) = median(timed samples)
T(arm,lane,block)         = mean(the arm's two slot medians)
R(lane,block)             = T(candidate,lane,block) / T(baseline,lane,block)
reported_effect           = median(R over retained blocks)
```

This aggregation is an example adopted in recent protocols; for throughput, build time, memory, throughput-per-core or other metrics, the protocol must specify an appropriate estimator and **clearly declare improvement direction**.

**Example (illustrative):** if A takes 10 ms and B takes 8 ms under comparable conditions, B/A = 0.80, or 20% lower latency relative to A. The protocol still needs uncertainty and guardrail checks before claiming a qualified improvement.

### 7.1 Confidence intervals and bootstrap

A 95% *bootstrap confidence interval* describes uncertainty about the chosen statistic under the study's sampling/resampling assumptions. It is not a guarantee that B will always fall within that interval on every host. The protocol freezes seed, number of resamples, interval construction and statistical acceptance rule; in a recent study this involved 10,000 draws. Resample whole **paired blocks**, keeping A/B pairing intact. Do not convert 20 correlated timings in a slot into 20 apparently independent blocks.

A point estimate can favor B while the interval still crosses the no-change or policy boundary. In that case the valid scientific result can be **INCONCLUSIVE**. An inconclusive lane is different from a corrupt or unqualified experiment.

## 8. Pruning: exclude qualifying contaminated blocks, not inconvenient samples

**Acquire first; assess exclusions after acquisition.** A slow or noisy sample does not justify interrupting, rerunning, deleting or editing the experiment. After acquisition, apply only the already-frozen, outcome-neutral, lane-level block-exclusion criteria. The exact validity of any criterion must be established prospectively; thresholds must not be tuned after inspecting candidate effects.

Example:

```text
Lane L, blocks:  B1 B2 B3 B4 B5 B6 B7 B8 B9 B10 B11 B12
Excluded:             ^              ^          ^
Retained:        B1 B2    B4 B5 B6 B7    B9 B10    B12

If lane L/block B3 is excluded, drop BOTH A and B for L/B3
from retained statistics; preserve all original samples.
```

Rules:
- Exclude the **entire lane–block pair for every compared arm**, even when a single measurement was anomalous.
- Exclusion must be based on the frozen rule and must not favor one arm or the desired outcome.
- Preserve unfiltered analysis, all acquired records, the list of excluded lane/block IDs, reasons and retained counts.
- Never prune a missing/incorrect result, bad provenance, invalid freeze or failed mandatory readiness into validity.
- If retained blocks fall below the protocol's minimum, return the protocol-defined *insufficient evidence / inconclusive* status, not a favorable decision.
- If raw and retained results diverge materially, report both transparently.

A recent v3 protocol required **at least four retained blocks per lane**; this is not a general benchmark constant. The example above retains nine blocks and does not authorize exactly three exclusions.

## 9. Performance policy, uncertainty and selection

Before acquisition, state what constitutes a meaningful performance improvement, what regressions are forbidden, and whether memory/storage/CPU costs affect eligibility. Distinguish **targets** (desired improvements) and **guardrails** (limits on regressions elsewhere). Policies may consider multiple campaigns, confidence intervals, filter sensitivity and aggregate comparisons, but must specify decision precedence and strict/equality boundary behavior.

Possible outcomes include:
- **Candidate faster:** the selected confidence/decision criteria favor the candidate.
- **Baseline faster:** a statistically supported or policy-defined regression.
- **Inconclusive:** insufficient retained data, uncertainty or failure to establish a threshold.
- **Ineligible:** a candidate violates a separately defined structural/resource/selection requirement.
- **Selected by tie-breaker:** preference between eligible candidates under an explicitly declared rule; **not** a claim one is proven faster.

For a concrete historical distinction, PR 15I-D3C selected P at one K through a *within-3% tie preference*, not proof that P was faster. Such specific rules belong to that frozen experiment's policy; a new experiment does not inherit them automatically. Missing, ambiguous or malformed policy inputs must fail closed, not silently pick a winner.

## 10. Gates: purpose, checks and safe reuse

A **gate** is a checkpoint with recorded inputs, rules and a PASS/FAIL/STOP result. Some gates authorize collecting measurements; others authorize trusting and publishing conclusions. They are not themselves additional benchmark runs.

### 10.1 Before measurements: authorization gates

| Check | Purpose | Example failure | Consequence |
| --- | --- | --- | --- |
| Protocol freeze | Prevent post-hoc changes to the study | Frozen source/schedule missing | No official acquisition |
| Correctness and semantic parity | Prevent timing wrong/different work | Candidate gives wrong hit set | Stop/invalid comparison |
| Source/build/workload identity | Guarantee the declared code and data were used | Wrong binary hash | Stop/invalid comparison |
| Host readiness | Avoid prohibited interference and unsupported conditions | `BUSY_EXCEEDED` | HOST_NOT_READY; no official run |
| A/A control | Detect ordering or measurement instability | Equivalent baselines differ beyond frozen gate | No official treatment qualification |

Failures follow the specific frozen protocol. An operator or coding agent cannot silently relax thresholds or add attempts. A subsequent authorized experiment may use a different protocol but must preserve the failed attempt as historical evidence.

### 10.2 After acquisition: logical gates A–E

These are the **target common qualification stages**. An implementation should reuse trustworthy, content-bound results rather than repetitively executing identical checks.

| Gate | Human question | What is checked | Output |
| --- | --- | --- | --- |
| **A — Evidence admission** | Is this the correct, intact, complete and permitted evidence? | Authenticity/provenance; hashes and member safety; all required slots/campaigns; protocol and freeze-order eligibility | Admission receipt |
| **B — Analysis** | What do the admitted measurements actually show? | Paired aggregations, exclusions, uncertainty, pre-frozen rule evaluation | Analysis and policy records |
| **C — Independent verification** | Did our analysis and decision software get it right? | Independent recomputation, boundary checks, policy-result comparison and mutation-sensitive validation | Verification receipt |
| **D — Acceptance** | Have all prescribed checks really passed? | A–C dependencies, applicable QA, completeness of tests, source/toolchain qualification and experiment-specific gates | Acceptance receipt |
| **E — Attestation** | What exact evidence supports the final claim? | Final content-addressed binding of evidence/code/protocol/decisions/QA, no stale or changed inputs | Attestation and manifest |

#### Gate A: four separate meanings

- **Authenticity:** Data belong to the claimed experiment. Check trusted source/protocol/build/corpus provenance and authenticated reference identities; a checksum found inside the same untrusted file is not sufficient by itself.
- **Integrity:** Data bytes have not changed. Rehash against trusted recorded digests, validate archive member inventory/size/path safety, sidecars, manifests and sealed raw files.
- **Completeness:** All mandatory campaigns, blocks, slots, lane records, oracle checks and supporting metadata exist according to the protocol; permitted exclusions are separately accounted for.
- **Eligibility:** The evidence may be used *for this official decision*: correct pre-acquisition freeze, authorization, campaign status, valid readiness and experiment scope. A complete exploratory campaign may still be ineligible.

Gate A **evidence eligibility** is distinct from Gate B **candidate eligibility**: the former admits datasets, the latter assesses whether an algorithm qualifies under policy.

#### Gate B: frozen policy

A *frozen policy* is the written, versioned mathematical decision rule adopted before seeing results: exact confidence criteria, target and guardrail thresholds, memory limits, exclusions, aggregate calculation, tie ordering and boundary operators. Gate B applies those rules to admitted evidence. It must report *why* a candidate passed, failed or was inconclusive. Statistical computations and selection rules are separate, albeit linked, outputs.

#### Gate C: independent oracle

The **functional correctness oracle** checked outputs before timing; the **independent statistical/policy oracle** now checks whether the primary calculations and final decisions follow the policy. This reference computation must not simply call the primary decision implementation. Independent synthetic boundary cases and deliberately mutated evidence verify that bad inputs or altered decisions are rejected. Two matching implementations can still share a misunderstanding; independence is a safeguard, not mathematical proof.

#### Gate D: QA versus acceptance

A verification implementation can have defects, so Gate D binds:
1. **Framework QA** — unit, contract, integration, negative and mutation tests for the reusable machinery.
2. **Source/build qualification** — applicable compiler, linter, unit/coverage and minimum-supported-toolchain checks, tied to exact source/toolchain identity.
3. **Experiment acceptance** — required admission, analysis, verification, correctness and experiment-specific gates are present and PASS, with no skipped mandatory checks.

A historical T7-F2 suite used 60 explicitly rostered acceptance tests and 11 QA commands. Those are **historical, experiment-specific quantities**, not permanent obligations for every new experiment.

#### Gate E: freeze and final attestation

A **freeze** is an immutable *logical snapshot* that binds hashes and identities for raw evidence, exact protocol, source/binary, analysis, policy, verification and QA. It need not make every filesystem physically read-only, but no changed byte can reuse the same valid attestation.

A **read-only derivation** recalculates analysis using existing measurements without acquiring fresh timings or modifying raw evidence. It may write new result files separately. When the qualification profile requires repeated derivations, deterministic outputs can be compared byte-for-byte **under the same serialization and algorithm version**. Repeating the entire derivation by default is unnecessary if other specified safeguards already establish reproducibility; a frozen protocol may require it.

The **attestation** records precisely what passed, by which code/version and against which evidence, with hashes and declared limits. It is an audit record, not automatically a cryptographic signature or permission to merge/ship.

### 10.3 Avoid duplicated work without bypassing checks

- Gate A produces a content-addressed admission receipt; B–E can reuse it only while **all** covered evidence, protocol, schema, validator and relevant dependencies are unchanged.
- Gate D consumes existing framework/source QA receipts if source, toolchain, roster and every material input still match. Changed dependencies invalidate the relevant receipts.
- Admission checks are not arbitrarily repeated by every downstream script; independent assertions that protect against separate defects are **retained**.
- Host-readiness and any time-sensitive acquisition preconditions are rechecked for a new run, not cached across sessions.
- Final acceptance revalidates receipt relationships and referenced content hashes to avoid substituting artifacts between gates (*time-of-check/time-of-use* mismatch).
- Failed/incomplete/unknown receipts are never treated as PASS.

## 11. What readers should expect in a final benchmark report

A qualified report should answer, in ordinary language:
1. What question did we ask, and what does each lane mean?
2. Which implementations and exact code/data/environment were compared?
3. How were blocks, slots, random order, warmups and samples organized?
4. Which correctness, host, A/A and post-acquisition gates passed?
5. What was excluded, why, and what do raw versus retained measurements show?
6. What are the measured effects and confidence intervals, and which decisions are conclusive or inconclusive?
7. Which policy was used and how did it select or reject an implementation?
8. Can a reviewer identify the raw evidence, its immutable digests, verifier identities and final attestation?
9. What is the **scope** of the claim—workload, cache regime, hardware and software revision—and what remains unproven?
10. Was a deployment/merge separately approved? A verified experimental result alone is insufficient.

## 12. Worked miniature example

Suppose the question is whether a new candidate B improves one warm search lane against A. The protocol specifies four balanced blocks (for illustration), two slots per arm in each block, five warmups and twenty timed samples per lane/slot, one pre-acquisition correctness oracle, an A/A control, and a paired latency-ratio policy. These quantities are illustrative; **four total blocks would not satisfy a different protocol that requires more than four retained blocks**.

After collection:
- Every slot returns the expected query results, and all mandatory host/A/A controls pass.
- For each block, compute A's and B's mean of slot medians and B/A ratio. Suppose the four illustrative paired ratios are **0.80, 0.84, 0.82, 1.05**.
- A predetermined contamination rule might exclude the final **whole lane/block pair**, if and only if its rule is satisfied without looking for favorable outcomes. Preserve the original 1.05 and exclusion reason. Without a qualifying rule, **retain all four**.
- Bootstrap **whole retained blocks**, not the individual twenty timings. With only a few blocks uncertainty may remain wide.
- Gate A validates the evidence; B derives estimates and a decision; C independently checks; D confirms the prescribed tests; E binds the exact outputs.
- If the CI fails the required threshold, report **INCONCLUSIVE** even when most observed ratios favor B.

The example teaches the sequence, **not an exclusion threshold or an actual claim about Quervant**.

## 13. Differences between methodology and software architecture

This document defines the **measurement and evidence process**. [BENCHMARKING_ARCHITECTURE.md](BENCHMARKING_ARCHITECTURE.md) defines which components implement each responsibility, their schemas, CLI and receipt contracts. [BENCHMARKING_MIGRATION.md](BENCHMARKING_MIGRATION.md) explains how existing PR-specific controllers and verifiers migrate while preserving historical evidence. [BENCHMARKING_ROADMAP.md](BENCHMARKING_ROADMAP.md) names the BM-01 onward PRs that implement the interim plan.

The currently published [../BENCHMARKING.md](../BENCHMARKING.md) remains the active historical/current reference until the refactoring is completed. At v0.1-bench closeout, integrate the **implemented** methodology and architecture into the relevant canonical documents under `docs/` and retain this interim directory for historical purposes.
