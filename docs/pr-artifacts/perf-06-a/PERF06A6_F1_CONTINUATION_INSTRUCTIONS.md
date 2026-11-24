# PERF-06-A6-F1 — Focused compatibility continuation

**Repository:** https://github.com/yduchesne/quervant  
**Existing PR:** https://github.com/yduchesne/quervant/pull/125  
**Branch:** dev/perf06-a6  
**Reviewed evidence head:** 7573cb5169f40eb68207fc6d06aa89ec2f2f8ef4  
**Planning date:** 2026-11-24 (Pacific date).  
**Purpose:** correct one supplied qualification-driver function, complete the six compatibility modes that never ran, and finish the existing A6 evidence package.  
**Execution contract:** follow this amendment and the unchanged original A6 design. Do not redesign either.

## 0. Instructions to the coding agent

Continue the existing PR through the unblocked steps below without routine permission prompts. The user has explicitly instructed that main is stable, general test suites and quality checks are unnecessary, and host stability observations must be informative only.

The completed warm acquisitions and four writer observations are DONE + VERIFIED. Their budgets are consumed. This continuation authorizes **no new benchmark acquisition, configuration, staging invocation, writer observation, profiler run, or analysis-policy change**.

The remaining execution is:

1. Verify the existing source/evidence identities.
2. Produce the exact amended compatibility source by the supplied byte replacement.
3. Build that example at E and F, reusing the existing target directories.
4. Execute the three never-started native modes.
5. Execute the three never-started real-RustFS modes.
6. Update the report and current-status documentation; deliver one ordinary follow-up commit on PR #125.

The original plan remains authoritative for the corpus, APIs, score formula, format markers, query assertions, PIT lifetimes, immutable-object checks, provider topology and remote-compaction exclusion. This amendment overrides only the defective digest serializer, continuation bookkeeping, host-observation policy, and the specific report corrections below.

### 0.1 Host stability is advisory and non-blocking

**This is an explicit user override of the original A6 host-stability stopping policy.**

Host load, idle state and readiness warnings are informational. An unfavorable observation must not stop this continuation, trigger a wait for a quieter host, cause a repeated probe, cause tuning, or create a permission checkpoint.

Record an immediately available observation if one exists; otherwise record:

> Host stability: NOT OBSERVED. Advisory only by explicit user instruction; no idle-host qualification or wait was performed.

Do not introduce a new sampling interval, idle threshold, background monitor or host-stability script. A missing or failed advisory probe does not block work.

Actual inability to execute an operation remains an operational failure: a compiler error, missing executable, failed compatibility assertion, wrong query result, source/evidence mismatch, or unavailable required RustFS service cannot be reported as success. RustFS endpoint health establishes a real I/O dependency; it is not an idle-host gate.

This continuation has no performance acquisition. Therefore no change to the benchmark framework's readiness code is required or authorized here. Do not call check_host=False, alter historical readiness records, or reinterpret earlier acceptance decisions. The requested non-blocking policy applies to every host-stability observation used during this continuation.

### 0.2 Carry the user's QA and CI exception forward

Do not run cargo test, cargo fmt, cargo clippy, cargo llvm-cov, cargo doc, cargo bench, MSRV matrices, existing RustFS integration suites, Python/framework suites, shell suites, or replacement general QA.

The two release builds and six specific compatibility processes below are the remaining A6 qualification work. They are not an instruction to run the repository's test suites.

Do not dispatch, retry, cancel or wait for CI. Existing automatic workflows remain unchanged. One ordinary final push may trigger them; record any state already observed and finish the handoff without polling.

## 1. Evidence reconciliation and intended terminal state

The original A6 invocation completed both acquisitions and four resource observations. It attempted both compatibility builds, which failed with the same E0277 at digest(). No native or remote mode started. No RustFS container was created.

The defective function was supplied in the original plan:

~~~rust
fn digest(bytes: &[u8]) -> String { format!("{:x}", Sha256::digest(bytes)) }
~~~

The pinned sha2 0.11 digest array lacks LowerHex. The amendment keeps SHA-256 unchanged and serializes its bytes individually using the standard library.

| Existing work | Treatment |
| --- | --- |
| R and C COMPLETE results, exact replays, A/A controls and recorded readiness | Preserve unchanged; do not acquire or replay them again merely for F1 |
| R retention | Preserve 15/16 MET; one NOT_MET |
| C cumulative | Preserve 2/4 primary MET and 12/12 guard MET |
| Whole-index size and model | Preserve PASS / MODEL_CONFIRMED |
| Four writer observations | Preserve exactly; descriptive only |
| Original failed E/F builds | Preserve logs and original driver source |
| Native compatibility | Execute its three previously unstarted modes |
| Remote compatibility | Execute its three previously unstarted modes after native success |
| Remote compaction publication | Still NOT QUALIFIED; no expansion or workaround |

If all prescribed compatibility modes and integrity checks pass, the overall A6 status becomes:

**PERF06_A6_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED**

It must not become QUALIFIED_READY_FOR_INDEPENDENT_REVIEW: the R retention miss and two C primary misses persist. If a required compatibility operation remains blocked or fails, retain PERF06_A6_VERIFICATION_BLOCKED and identify the exact remaining gate.

G10 remains a maintainer decision. Do not merge, release, implement B1, or mark the whole series DONE.

## 2. Frozen identities

| Identity | Value |
| --- | --- |
| Existing A6 evidence head | 7573cb5169f40eb68207fc6d06aa89ec2f2f8ef4 |
| A0, historical pre-A1 source | 2a74017958c8ac61948f931e8745bf8134827025 |
| E, genuine A3 writer | b70f624fffe0329def62701b61e997c4e303e167 |
| F, accepted A5 source and historical measured controller | 3bb232f868cb556ce9b4273d902164c65416af0f |
| Retained invocation UUID | 42f4b362-5e71-43c1-850a-d92912193731 |
| Compiler | Already installed Rust 1.98.1 |
| Original driver bytes / SHA-256 | 22,842 / 927c4d09759c5f29cd35005e8079f77b25028bcd349ea66744b1054130e3b5fc |
| Corrected driver bytes / SHA-256 | 23,056 / 788702364ea735431bba405ede634fe29f5527badb8c552a10d2edd406659be8 |

Record the new delivery HEAD separately. Never replace the historical RUNNER_SHA in the original results with the A6 evidence commit or F1 commit.

## 3. Scope and ownership

### 3.1 Allowed changes

Create:

- docs/pr-artifacts/perf-06-a/PERF06A6_F1_CONTINUATION_INSTRUCTIONS.md — this complete amendment, copied verbatim.
- docs/pr-artifacts/perf-06-a/a6/f1/support/a6_compatibility.rs — exact amended copy.
- docs/pr-artifacts/perf-06-a/a6/f1/compatibility/ — new build logs, build identities, six mode log/metadata/exit records.
- docs/pr-artifacts/perf-06-a/a6/f1/verification/ — bounded identity, host-observation, container and scope evidence.

Modify only:

- docs/pr-artifacts/perf-06-a/PERF06A6_EXECUTION_REPORT.md — current disposition, the exact factual corrections, and an appended F1 section.
- docs/PERF_OPTIMIZATION_ROADMAP.md.
- docs/pr-artifacts/perf-06-a/PERF06A_SERIES_REGISTER.md.
- docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md.
- docs/BENCHMARKING.md — a short A6-F1 amendment recording the user's advisory host policy and the unchanged measurement scope; no broader framework claim.

The existing four documentation files receive only current-status amendments consistent with the actual outcome.

### 3.2 Protected paths

Preserve the original A6 plan, all four original a6/support files, original failed-build logs/preparation status, invocation UUID, acquisition markers/logs/references, verification records, writer files, both configurations, both results, and all A1–A5/F1 artifacts.

Preserve all controller-branch production, adapter, framework, test, fixture, Cargo, toolchain and workflow files.

The only source-write exception outside the artifact directory is replacing the untracked example in the two dedicated compatibility worktrees:

crates/quervant-core/examples/perf06_a6_compatibility.rs

Never install the example in the controller checkout or a benchmark cache worktree.

The public index APIs remain the owners of index state and publication. Do not manufacture or edit CURRENT, manifests, segments, mutation state, expected results or successful provider responses.

## 4. Preflight and bindings — reads, no suites

Inspect the current worktree and PR #125. Require the existing branch or an explicit checkout of its ordinary remote branch. Do not stash unrelated changes or force/reset/rebase.

For a clean existing checkout:

~~~bash
git fetch origin main dev/perf06-a6
git switch dev/perf06-a6
git merge --ff-only origin/dev/perf06-a6
git merge-base --is-ancestor 7573cb5169f40eb68207fc6d06aa89ec2f2f8ef4 HEAD
~~~

The normal starting head is the reviewed 7573cb5 commit. A later head is allowed only as a demonstrably consistent resume of this exact amendment. Any unrelated branch change stops dependent work for reconciliation. Record current origin/main, but do not rebase or change E/F pins merely because main advanced.

Require no controller production/framework delta relative to F:

~~~bash
git diff --exit-code 3bb232f868cb556ce9b4273d902164c65416af0f HEAD -- \
  crates benchmarks/quervant_bench benchmarks/pr15d \
  Cargo.toml Cargo.lock rust-toolchain.toml .cargo .github
~~~

Also inspect unstaged/staged changes and nonignored untracked files. Existing files from an interrupted F1 may remain only when their identities and ownership match this amendment. Unrelated modifications are not authority to undo user work.

Set:

~~~bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
A6_DELIVERY_START_SHA="$(git rev-parse HEAD)"
A6_MEASURED_RUNNER_SHA=3bb232f868cb556ce9b4273d902164c65416af0f
A6_SCRATCH="$REPO_ROOT/target/perf06-a6"
A6_ARTIFACTS="$REPO_ROOT/docs/pr-artifacts/perf-06-a/a6"
A6_F1="$A6_ARTIFACTS/f1"
A6_F1_SOURCE="$A6_F1/support/a6_compatibility.rs"
E_WORKTREE="$A6_SCRATCH/compat-worktrees/E"
F_WORKTREE="$A6_SCRATCH/compat-worktrees/F"
E_DRIVER="$A6_SCRATCH/compat-target/E/release/examples/perf06_a6_compatibility"
F_DRIVER="$A6_SCRATCH/compat-target/F/release/examples/perf06_a6_compatibility"
NATIVE_ROOT="$A6_SCRATCH/compatibility/native-index"
export RUSTUP_TOOLCHAIN=1.98.1
export LC_ALL=C
mkdir -p "$A6_F1/support" "$A6_F1/compatibility" "$A6_F1/verification"
~~~

Use the already installed compiler. Do not update Rust, dependencies, feature flags, profiles or Cargo.lock. Record rustc/cargo versions once.

### 4.1 Verify immutable input files

Run this exact data-only verification before work and again before delivery. Save each output as a separate before/after ledger under f1/verification; do not overwrite either ledger. No host-cache replay is required.

~~~bash
python3 - "$REPO_ROOT" <<'PY'
from pathlib import Path
import hashlib, sys
root = Path(sys.argv[1])
expected = {
    "docs/pr-artifacts/perf-06-a/PERF06A6_DETAILED_PLAN.md":
        "b15790319fd6d8cefec7c8696ffa61e75baca9e4b7e858be22c57707e3ebb5b0",
    "docs/pr-artifacts/perf-06-a/a6/support/a6_compatibility.rs":
        "927c4d09759c5f29cd35005e8079f77b25028bcd349ea66744b1054130e3b5fc",
    "docs/pr-artifacts/perf-06-a/a6/support/verify_a6_results.py":
        "8564a68d1a46e99df3b008a69e0dadcadc053993f67751d1a118d2d2ae5964b0",
    "docs/pr-artifacts/perf-06-a/a6/support/measure_a6_writer.py":
        "32aabfcdb9b485307a96e056e934d31d523652458a9ee9072e01286a0ce41194",
    "docs/pr-artifacts/perf-06-a/a6/support/run_a6_once.py":
        "4fe15fcc3e79dd5329af36f8038bae549e38bd9eb1f65d86667301dee253110c",
    "benchmarks/studies/perf-06/warm/configurations/quervant-perf06a6-adaptive-warm-2026-11-24.json":
        "2ca83709d071db944755b4732548c5c90c8e4361a5bbbd93559cb571ec0e138d",
    "benchmarks/studies/perf-06/warm/configurations/quervant-perf06a6-cumulative-warm-2026-11-24.json":
        "66e50aa74ba7716dc4825c4298647df9885cd586b7341088e23baee91fa42cce",
    "benchmarks/studies/perf-06/warm/results/quervant-perf06a6-adaptive-warm-2026-11-24-001.json":
        "eb809fa66f37b9f5c21e86baac3478ec1f47ff53a634604a053096b5e2be2638",
    "benchmarks/studies/perf-06/warm/results/quervant-perf06a6-cumulative-warm-2026-11-24-001.json":
        "04da08b5d9f4ca0f6654adf4e54579c4663cfd0fc73d2ca8d4da4b2d26584141",
}
for relative, wanted in expected.items():
    p = root / relative
    if p.is_symlink():
        raise SystemExit(f"STOP: unexpected symlink {relative}")
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    if actual != wanted:
        raise SystemExit(f"STOP: identity mismatch {relative}: {actual}")
    print(actual, relative)
uuid = (root / "docs/pr-artifacts/perf-06-a/a6/invocation-uuid.txt").read_text().strip()
if uuid != "42f4b362-5e71-43c1-850a-d92912193731":
    raise SystemExit("STOP: retained invocation UUID differs")
print("IMMUTABLE_INPUTS=PASS")
PY
~~~

Inspect the original preparation-status record: both builds failed, no mode ran. Before the first F1 native mode, require NATIVE_ROOT absent. Before each first remote invocation, require its own workspace root absent. An existing root with no trustworthy matching invocation evidence is a stop, not authority to remove it.

## 5. Exact correction — no design discretion

The only Rust change is:

~~~rust
fn digest(bytes: &[u8]) -> String {
    use std::fmt::Write as _;
    let hash = Sha256::digest(bytes);
    let mut encoded = String::with_capacity(hash.len() * 2);
    for byte in hash.iter() {
        write!(&mut encoded, "{byte:02x}").expect("format SHA-256 digest");
    }
    encoded
}
~~~

It computes SHA-256 once and allocates one fully sized output string. It creates no temporary String per byte, new dependency, custom hash algorithm, production hot-path work or query-path allocation.

Create the amended artifact from the preserved original with this exact transformation:

~~~bash
python3 - "$A6_ARTIFACTS/support/a6_compatibility.rs" "$A6_F1_SOURCE" <<'PY'
from pathlib import Path
import hashlib, sys
source, destination = map(Path, sys.argv[1:])
original_hash = "927c4d09759c5f29cd35005e8079f77b25028bcd349ea66744b1054130e3b5fc"
amended_hash = "788702364ea735431bba405ede634fe29f5527badb8c552a10d2edd406659be8"
original = source.read_bytes()
if source.is_symlink() or hashlib.sha256(original).hexdigest() != original_hash:
    raise SystemExit("STOP: original support source differs")
old = b'fn digest(bytes: &[u8]) -> String { format!("{:x}", Sha256::digest(bytes)) }'
new = b'''fn digest(bytes: &[u8]) -> String {
    use std::fmt::Write as _;
    let hash = Sha256::digest(bytes);
    let mut encoded = String::with_capacity(hash.len() * 2);
    for byte in hash.iter() {
        write!(&mut encoded, "{byte:02x}").expect("format SHA-256 digest");
    }
    encoded
}'''
if original.count(old) != 1:
    raise SystemExit("STOP: expected one exact original function")
amended = original.replace(old, new, 1)
if len(amended) != 23056 or hashlib.sha256(amended).hexdigest() != amended_hash:
    raise SystemExit("STOP: amendment identity differs")
destination.parent.mkdir(parents=True, exist_ok=True)
if destination.exists():
    if destination.is_symlink() or destination.read_bytes() != amended:
        raise SystemExit("STOP: differing existing F1 source")
else:
    with destination.open("xb") as stream:
        stream.write(amended)
print(len(amended), amended_hash, destination)
PY
~~~

Do not rerun the original Appendix E extraction recipe to change the old helper. The original remains unchanged; the F1 copy is the active compatibility source.

### 5.1 Dedicated worktrees

Reuse the existing E/F worktrees. Read git worktree list --porcelain first. If a path is genuinely absent and no conflicting registration exists, create that exact missing worktree:

~~~bash
git worktree add --detach "$E_WORKTREE" b70f624fffe0329def62701b61e997c4e303e167
git worktree add --detach "$F_WORKTREE" 3bb232f868cb556ce9b4273d902164c65416af0f
~~~

Run only the command for a genuinely absent worktree. An existing path or registration with another identity stops that branch of preparation; do not prune registrations or replace contents.

Install the source using the following fixed validation and copy recipe:

~~~bash
python3 - "$A6_F1_SOURCE" "$E_WORKTREE" "$F_WORKTREE" <<'PY'
from pathlib import Path
import hashlib, subprocess, sys
source = Path(sys.argv[1]).read_bytes()
new_hash = "788702364ea735431bba405ede634fe29f5527badb8c552a10d2edd406659be8"
old_hash = "927c4d09759c5f29cd35005e8079f77b25028bcd349ea66744b1054130e3b5fc"
relative = "crates/quervant-core/examples/perf06_a6_compatibility.rs"
if hashlib.sha256(source).hexdigest() != new_hash:
    raise SystemExit("STOP: amended artifact identity differs")
pins = ["b70f624fffe0329def62701b61e997c4e303e167",
        "3bb232f868cb556ce9b4273d902164c65416af0f"]
for path, pin in zip(sys.argv[2:], pins):
    worktree = Path(path)
    def git(*args):
        return subprocess.check_output(["git", "-C", str(worktree), *args], text=True).strip()
    if git("rev-parse", "HEAD") != pin:
        raise SystemExit(f"STOP: wrong worktree head {worktree}")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit(f"STOP: tracked worktree changes {worktree}")
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    if any(item != relative for item in untracked):
        raise SystemExit(f"STOP: unrelated untracked worktree file {worktree}")
    target = worktree / relative
    if target.is_symlink():
        raise SystemExit(f"STOP: unexpected example symlink {target}")
    if target.exists():
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual not in {old_hash, new_hash}:
            raise SystemExit(f"STOP: unknown existing example {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source)
    if hashlib.sha256(target.read_bytes()).hexdigest() != new_hash:
        raise SystemExit("STOP: installed example identity differs")
    print(pin, new_hash, target)
PY
~~~

This authorizes replacement of only a recognized original/amended untracked example. No import, assertion, score formula, lifecycle or corpus correction is delegated.

## 6. Build once per source, using the retained targets

There is one new F1 build allowance for E and one for F. Reuse their target directories and existing compiled dependencies. Do not cargo clean.

Use this fixed shell function. It captures a new started record, combined build log, exit status, and binary digest. Existing F1 attempt evidence blocks another invocation; handle a proven completed attempt under the resume matrix instead.

~~~bash
a6_f1_build_once() {
  local arm="$1"
  local wt
  local driver
  case "$arm" in
    E) wt="$E_WORKTREE"; driver="$E_DRIVER" ;;
    F) wt="$F_WORKTREE"; driver="$F_DRIVER" ;;
    *) printf 'STOP: unknown build arm\n' >&2; return 90 ;;
  esac
  local prefix="$A6_F1/compatibility/build-$arm"
  for suffix in started.txt log exit.txt binary.sha256; do
    if test -e "$prefix.$suffix"; then
      printf 'STOP: F1 build history exists: %s\n' "$prefix" >&2
      return 90
    fi
  done
  (
    set -o noclobber
    printf 'arm=%s\nworktree=%s\nsource_sha256=%s\n' \
      "$arm" "$wt" \
      788702364ea735431bba405ede634fe29f5527badb8c552a10d2edd406659be8 \
      >"$prefix.started.txt"
  ) || return 91
  local code=0
  (
    set -o noclobber
    cargo +1.98.1 build --release --locked -p quervant-core \
      --features s3 --example perf06_a6_compatibility \
      --manifest-path "$wt/Cargo.toml" \
      --target-dir "$A6_SCRATCH/compat-target/$arm" \
      >"$prefix.log" 2>&1
  ) || code=$?
  (set -o noclobber; printf '%s\n' "$code" >"$prefix.exit.txt") || return 91
  if test "$code" -ne 0; then
    printf 'STOP: amended build failed: %s exit=%s\n' "$arm" "$code" >&2
    return "$code"
  fi
  test -x "$driver" || return 92
  (set -o noclobber; sha256sum "$driver" >"$prefix.binary.sha256") || return 91
}
a6_f1_build_once E && a6_f1_build_once F
~~~

A new build failure stops dependent compatibility work. Preserve it and request an amendment; do not make another speculative correction. If E fails, do not spend another build on F merely to reproduce the same diagnosis.

For a successful resumed build, require exit 0, the matching started record and worktree/source identity, an executable binary, and a successful sha256sum --check of its recorded binary.sha256. Then skip that build. Missing or ambiguous completion evidence stops automatic resumption.

## 7. Execute only the six prescribed compatibility modes

### 7.1 Fixed log capture

This preserves the original mode semantics and changes only the evidence destination to f1/compatibility. Metadata records the exact argv, fixed source hash and actual executable digest before launch.

~~~bash
a6_f1_compat_once() {
  local label="$1"
  local driver="$2"
  local mode="$3"
  local root="$4"
  local log_root="$A6_F1/compatibility"
  shift 4
  for suffix in metadata.json stdout.jsonl stderr.log exit.txt; do
    if test -e "$log_root/$label.$suffix"; then
      printf 'STOP: compatibility history exists: %s\n' "$label" >&2
      return 90
    fi
  done
  python3 - "$log_root/$label.metadata.json" "$driver" "$mode" "$root" "$@" <<'PY'
from pathlib import Path
import hashlib, json, os, sys
record = {
    "source_sha256": "788702364ea735431bba405ede634fe29f5527badb8c552a10d2edd406659be8",
    "binary_sha256": hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest(),
    "argv": sys.argv[2:],
}
with Path(sys.argv[1]).open("x", encoding="utf-8") as stream:
    json.dump(record, stream, indent=2, sort_keys=True)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
PY
  local metadata_code=$?
  test "$metadata_code" -eq 0 || return "$metadata_code"
  local code=0
  (
    set -o noclobber
    "$driver" "$mode" "$root" "$@" \
      >"$log_root/$label.stdout.jsonl" 2>"$log_root/$label.stderr.log"
  ) || code=$?
  (set -o noclobber; printf '%s\n' "$code" >"$log_root/$label.exit.txt") || return 91
  if test "$code" -ne 0; then
    printf 'STOP: compatibility mode failed: %s exit=%s\n' "$mode" "$code" >&2
    return "$code"
  fi
  python3 - "$log_root/$label.stdout.jsonl" "$mode" <<'PY'
from pathlib import Path
import json, sys
rows = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
if not rows or any(row.get("schema") != "perf06-a6-compatibility-v1" for row in rows):
    raise SystemExit("STOP: invalid compatibility evidence")
if rows[-1] != {"schema": "perf06-a6-compatibility-v1",
               "mode": sys.argv[2], "status": "PASS"}:
    raise SystemExit("STOP: missing terminal compatibility PASS")
PY
}
~~~

Before starting modes, verify both recorded binary digests:

~~~bash
sha256sum --check "$A6_F1/compatibility/build-E.binary.sha256"
sha256sum --check "$A6_F1/compatibility/build-F.binary.sha256"
~~~

Both checks must succeed. A mode's metadata file consumes its automatic invocation allowance even if execution is interrupted before an exit record appears.

### 7.2 Native sequence

For the first invocation only, require the native root absent. Then:

~~~bash
a6_f1_compat_once native-create-e "$E_DRIVER" create-e "$NATIVE_ROOT" &&
a6_f1_compat_once native-advance-f "$F_DRIVER" advance-f "$NATIVE_ROOT" &&
a6_f1_compat_once native-verify-f "$F_DRIVER" verify-f "$NATIVE_ROOT"
~~~

Do not parallelize. The unchanged source provides the complete independent assertions from original A6 §7:

| State | Required contract |
| --- | --- |
| Genuine E creation | Generation 1, 129 documents, one actual E segment; close/reopen |
| F append | Generation 2, 130 documents, E+F segments; genuine held PITs |
| Native compact | One compaction, generation 3, one F segment, unchanged logical results |
| Boundary grammar | A3 long alpha/common lists; compact zeta and singleton lists after compaction |
| Reader and object lifetime | Generation-1 and generation-2 PIT maps preserved; both generations' captured immutable files unchanged |
| New process | Third invocation independently reopens generation 3 and checks the full contract |

All three zero exits plus terminal PASS records are required for G2. A compilation success alone cannot pass G2.

### 7.3 Fixed remote bindings

Reuse the existing UUID; do not generate another one:

~~~bash
A6_UUID=42f4b362-5e71-43c1-850a-d92912193731
A6_REMOTE_PREFIX="perf06-a6/$A6_UUID"
A6_CONTAINER_NAME=quervant-perf06-a6-42f4b362
A6_IMAGE=rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
~~~

### 7.4 Real RustFS preparation

After native success, select functioning installed Podman, otherwise functioning installed Docker:

~~~bash
A6_CONTAINER_ENGINE=
if command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
  A6_CONTAINER_ENGINE=podman
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  A6_CONTAINER_ENGINE=docker
fi
~~~

If empty, report G3 blocked by the missing operational dependency and complete reporting. Do not install or repair a runtime.

Inspect the exact image:

~~~bash
"$A6_CONTAINER_ENGINE" image inspect "$A6_IMAGE"
~~~

Only if absent, one pull of that exact image is authorized:

~~~bash
"$A6_CONTAINER_ENGINE" pull "$A6_IMAGE"
~~~

A pull failure blocks remote work. No replacement image, runtime, port or provider is authorized. Before first launch require no conflicting container name; inspect it and reconcile any existing recorded owned instance under the resume matrix.

Launch once:

~~~bash
A6_CONTAINER_ID="$("$A6_CONTAINER_ENGINE" run --detach \
  --name "$A6_CONTAINER_NAME" \
  --publish 127.0.0.1:19000:9000 \
  --env RUSTFS_ACCESS_KEY=quervanttest \
  --env RUSTFS_SECRET_KEY=quervantsecret \
  --health-cmd "curl -fsS http://localhost:9000/health || exit 1" \
  --health-interval 5s --health-timeout 5s --health-retries 30 \
  "$A6_IMAGE")"
~~~

Require actual launch exit 0 and a nonempty ID. Immediately record the engine and returned ID in exclusive files, and capture inspect metadata:

~~~bash
(set -o noclobber; printf '%s\n' "$A6_CONTAINER_ENGINE" >"$A6_F1/verification/rustfs-engine.txt")
(set -o noclobber; printf '%s\n' "$A6_CONTAINER_ID" >"$A6_F1/verification/rustfs-container-id.txt")
"$A6_CONTAINER_ENGINE" inspect "$A6_CONTAINER_ID" >"$A6_F1/verification/rustfs-inspect-start.json"
~~~

Use image defaults, task-owned container storage, and no host mount. The public fixture credentials above are the same dedicated local credentials specified in the original plan; do not use an external account.

Use the original bounded service-startup check. It establishes that the required endpoint exists, not whether the host is idle:

~~~bash
python3 - <<'PY'
import time
import urllib.error
import urllib.request
deadline = time.monotonic() + 150.0
for attempt in range(1, 31):
    try:
        with urllib.request.urlopen("http://127.0.0.1:19000/health", timeout=2.0) as response:
            if response.status == 200:
                print(f"RUSTFS_HEALTH=PASS observation={attempt}", flush=True)
                break
    except (OSError, urllib.error.URLError):
        pass
    print(f"RUSTFS_HEALTH=PENDING observation={attempt}", flush=True)
    remaining = deadline - time.monotonic()
    if attempt == 30 or remaining <= 0:
        raise SystemExit("BLOCKED: required RustFS endpoint unavailable")
    time.sleep(min(5.0, remaining))
PY
~~~

Capture the actual health outcome; provide progress while the service starts. Failure preserves container diagnostics and blocks only the dependent remote work. No wait-for-idle or repeat host stability check is permitted.

### 7.5 Remote sequence

Each root below must be absent before its first invocation. Continue only after the previous mode succeeds.

~~~bash
(
  export QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:19000
  export QUERVANT_RUSTFS_REGION=us-east-1
  export QUERVANT_RUSTFS_BUCKET=quervant-perf06-a6
  export QUERVANT_RUSTFS_ACCESS_KEY=quervanttest
  export QUERVANT_RUSTFS_SECRET_KEY=quervantsecret
  a6_f1_compat_once remote-create-e "$E_DRIVER" remote-create-e \
    "$A6_SCRATCH/compatibility/remote-e" "$A6_REMOTE_PREFIX" &&
  a6_f1_compat_once remote-append-f "$F_DRIVER" remote-append-f \
    "$A6_SCRATCH/compatibility/remote-f" "$A6_REMOTE_PREFIX" &&
  a6_f1_compat_once remote-verify-f "$F_DRIVER" remote-verify-f \
    "$A6_SCRATCH/compatibility/remote-reader" "$A6_REMOTE_PREFIX"
)
~~~

The unchanged executable must demonstrate genuine remote E publication, authoritative CURRENT generation 1, F append/publication generation 2, cold E/E+F opens from distinct empty workspaces, retained PITs and immutable remote objects, followed by a separate-process reopen.

Three zero exits plus terminal PASS records are required for G3. No direct object upload, fake provider, index transplantation, CURRENT edit, additional mutation or remote compaction workaround is allowed.

### 7.6 Owned-service cleanup

Capture container logs and final inspect metadata before cleanup, including after a remote failure:

~~~bash
"$A6_CONTAINER_ENGINE" logs "$A6_CONTAINER_ID" >"$A6_F1/verification/rustfs.log" 2>&1
"$A6_CONTAINER_ENGINE" inspect "$A6_CONTAINER_ID" >"$A6_F1/verification/rustfs-inspect-final.json"
"$A6_CONTAINER_ENGINE" stop "$A6_CONTAINER_ID"
"$A6_CONTAINER_ENGINE" rm --volumes "$A6_CONTAINER_ID"
~~~

Use only the ID recorded from the task's successful launch. Do not prune globally or delete unrelated volumes/workspaces. Keep the native and remote workspace state; disk was 17% at the original handoff and no cleanup was requested.

If interrupted before remote completion, do not destroy the owned service merely to create a fresh attempt. Apply the resume rules. If cleanup itself fails, record the exact remaining owned resource without expanding cleanup scope.

## 8. Exact report corrections and continuation record

Keep original first-attempt build diagnostics and the original §5/§6 blocked history. Label them as the initial attempt and append the actual continuation. Do not claim they originally succeeded.

Update the top-level status and G2/G3 rows only from actual outcomes.

### 8.1 Correct the R failure explanation in §7

Replace the paragraph beginning "Retention decision" with:

> Retention decision: **15 MET / 16 lanes; 1 NOT_MET** — 10000/absent/k10/warm has a gain of **−2.122287%** and a 95% confidence interval of **[−21.807939%, +19.333886%]**. It fails **both** frozen retention conditions: the point estimate is below −2.0%, and the lower confidence bound is below −5.0%. Its analyzer classification remains INCONCLUSIVE. The interval spans zero and is too wide to establish either a statistically significant regression or compliance with the declared retention budget. The recorded acquisition does not establish the cause of that variability. The result remains valid unfavorable evidence and is preserved unchanged; no rerun, block pruning, or threshold adjustment was performed.

Remove the unsupported assertion that machine noise was established as the cause. Preserve the table and raw result without change.

### 8.2 Correct the warm-measurement scope in §13

The warm adapter sorts by ascending doc_id. Replace the wording that claims the timed lane set also measured relevance sorting with:

> Warm effects are paired, same-campaign, warm-regime results for these pinned sources, corpus, exact-keyword query lanes, ascending doc_id sort, K10/K100 projection, compiler and host. Relevance-order assertions belong to the separate compatibility workload and are not warm latency measurements.

Preserve the existing caution that R measures the whole A5 change and C measures the consolidated A1–A3+A5 change; neither provides per-internal-change attribution.

### 8.3 Append a new F1 section

Include:

1. This amendment's identity and the explicit non-blocking host policy.
2. Before/after evidence identity ledgers; zero benchmark/config/resource changes.
3. Original and corrected driver hashes; exact one-function change; no production delta.
4. Actual E/F build commands, exits, source/binary identities and reused targets.
5. Six actual mode invocations, exits, terminal PASS records and relevant generation/format/PIT/object evidence; identify any unexecuted modes.
6. Exact real-provider topology, owned container ID, health/cleanup results, or precise dependency blocker.
7. The two factual report corrections and their reasons.
8. Final G0–G10 ledger: inherited verified evidence distinguished from newly executed compatibility evidence.
9. Applied decision rows, residuals, actual publication identity and maintainer decision.
10. Explicitly state no new warm acquisition, staging, writer observation, general suite, quality check or CI wait occurred.

If all six modes pass, derive COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED. Remote compaction publication remains NOT QUALIFIED. G10 and B1 remain maintainer-owned.

## 9. Decision matrix

The agent may apply only these predefined branches. "STOP" means preserve the exact evidence, stop dependent work, complete independent reporting, and request a specific amendment. It does not authorize a speculative fix.

| ID | Observed condition | Fixed action | Prohibited action |
| --- | --- | --- | --- |
| F01 | Host load/readiness warning | Record as advisory; continue immediately | Idle wait, repeated probe, tuning, blocking or permission prompt |
| F02 | No usable host observation | Record NOT OBSERVED; continue | Install monitoring or invent a clear reading |
| F03 | Reviewed branch and protected identities match | Proceed through all prescribed phases | Ask for routine reconfirmation |
| F04 | Original plan/support/result/config identity differs | STOP dependent verification; record expected and actual identity | Repair evidence, substitute inputs or acquire replacement data |
| F05 | Exact missing compatibility worktree, no conflicting registration | Create it once at its exact pin; reuse target caches | Repurpose a foreign checkout or prune registrations |
| F06 | Existing worktree/head/example differs outside the allowed original/amended identity | STOP source application | Reset, stash, broaden source edits or replace unknown files |
| F07 | Corrected artifact already has the exact new hash | Reuse its bytes | Reapply or alter the correction |
| F08 | New F1 build succeeds with source/binary records | Continue to the next prescribed operation | General QA or a second build for reassurance |
| F09 | New F1 build fails | Preserve logs; STOP dependent modes; report first diagnostic | Another guessed fix, dependency/toolchain change or retry |
| F10 | Mode exits 0 and has valid terminal PASS | Record completion; continue to its prescribed successor | Repeat completed mode |
| F11 | A mode fails, is interrupted or lacks trustworthy completion | Preserve partial state; STOP that lifecycle | Delete logs/root, choose a fresh prefix or rerun |
| F12 | Resume finds completed build/mode evidence | Skip only after the exact checks below; continue first unstarted successor | Treat mere file existence as proof of success |
| F13 | Native passes; runtime/image/port/endpoint is unavailable | Keep G2 PASS, mark G3 blocked, finish report | Fake provider, alternative topology or performance rerun |
| F14 | Remote lifecycle partly complete and recorded owned container is still running with matching topology | Reuse only that ID and validated mode history | New container or different storage/prefix |
| F15 | Remote lifecycle partly complete but container state is lost/stopped or ownership uncertain | STOP remote continuation; preserve state and report | Recreate an empty container and resume at append/verify |
| F16 | All remote modes already passed, cleanup incomplete | Perform only owned cleanup and reporting | Repeat compatibility |
| F17 | Existing warm markers/results/resources are present | Preserve as completed evidence | run, stage, prepare, new sequence, new writer observation |
| F18 | Suites/quality gates/CI waits are suggested | Apply user exception; record NOT RUN where relevant | Add waived gates or falsely mark them PASS |
| F19 | All six compatibility modes and integrity checks pass | Derive COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED | Erase numeric misses, auto-merge or start B1 |
| F20 | Any required compatibility gate still blocked | Retain VERIFICATION_BLOCKED; identify exact cause | Use historical A5 CI as substitute compatibility evidence |
| F21 | Unexpected source change, unknown behavior, ambiguous history or unlisted choice | STOP affected work and request the smallest amendment | Improvise or generalize an AUTO branch |

### 9.1 Decision categories, evidence and ownership

This mapping is part of the preceding matrix. The executor must not choose a different category or escalation owner.

| Row | Category | Required evidence | Affected gate/task | Owner |
| --- | --- | --- | --- | --- |
| F01 | AUTO-RESOLVE | Actual advisory observation | No acceptance gate | Agent |
| F02 | AUTO-RESOLVE | NOT OBSERVED and available probe outcome | No acceptance gate | Agent |
| F03 | AUTO-RESOLVE | Branch/head, source and protected-file identities | G0/G9 | Agent |
| F04 | HARD STOP | Expected and observed digest/source identity | G0/G9 and dependent claims | Plan author |
| F05 | AUTO-RESOLVE | Absent path, worktree registration list, exact pin | G2/G3 preparation | Agent |
| F06 | HARD STOP | Worktree HEAD/status and conflicting example identity | G2/G3 preparation | Plan author |
| F07 | AUTO-RESOLVE | Corrected file SHA-256 and byte count | G2/G3 preparation | Agent |
| F08 | AUTO-RESOLVE | Build command, zero exit, source and binary identities | G2/G3 preparation | Agent |
| F09 | HARD STOP | Build log, exit and first diagnostic | G2/G3 preparation | Plan author |
| F10 | AUTO-RESOLVE | Mode metadata, zero exit and terminal PASS | G2 or G3 | Agent |
| F11 | HARD STOP | Partial logs, exit or interruption and retained state | G2 or G3 lifecycle | Plan author |
| F12 | AUTO-RESOLVE | All completion checks in the following resume subsection | G2/G3 preparation or lifecycle | Agent |
| F13 | DEFER AND CONTINUE | Exact runtime/image/port/endpoint failure | G3; reporting continues | Maintainer |
| F14 | AUTO-RESOLVE | Recorded owned ID, current inspect data and completed-mode history | G3 continuation | Agent |
| F15 | HARD STOP | Lost/stopped/ambiguous container or state evidence | G3 continuation | Plan author |
| F16 | AUTO-RESOLVE | Completed remote records and exact owned cleanup ID | G9 cleanup | Agent |
| F17 | AUTO-RESOLVE | Existing immutable markers/configs/results/resources | G4–G8 preserved | Agent |
| F18 | AUTO-RESOLVE | Explicit user exception and actual NOT RUN status | Execution policy; no QA gate | Agent |
| F19 | AUTO-RESOLVE | Six successful mode records and integrity ledger | G2/G3/G9; G10 remains open | Agent; acceptance by maintainer |
| F20 | DEFER AND CONTINUE | Precise unresolved compatibility blocker | G2/G3; reporting continues | Maintainer |
| F21 | HARD STOP | Exact unexpected condition and affected invariant | Affected task/gate | Plan author |

### 9.2 Exact resume evidence

A build may be skipped only if its F1 started record, exit 0, expected worktree/source identity, existing executable and recorded binary digest all agree.

A compatibility mode may be skipped only if:

- Metadata argv equals the exact prescribed binary, mode, workspace and optional retained prefix.
- Metadata source hash equals the corrected hash and its binary hash matches the recorded successful build.
- Recorded exit is 0.
- Every stdout line parses with schema perf06-a6-compatibility-v1, and the last object is exactly the expected mode/PASS object in §7.1.
- Required resulting workspace/state remains present.
- For a partial remote lifecycle, the recorded owned container and its actual stored state remain available.

Do not rerun the wrapper to skip a mode: it intentionally rejects existing invocation history. Resume from the first unstarted successor only after these read-only conditions are satisfied. Any partial, mismatched or uncertain history takes F11/F21.

The native root is required absent only before its initial create-e invocation. It must remain present for advance-f, verify-f and their read-only resume checks. Remote roots are separate and are required absent before their own first invocation.

## 10. Integrity and delivery

Run §4.1 again and inspect the complete diff against the reviewed A6 evidence head.

Require zero delta in:

- benchmarks/studies/perf-06/warm/configurations and results.
- The original a6/acquisition, a6/compatibility, a6/support, a6/verification and a6/writer directories and invocation UUID.
- Original A6 and earlier plans/reports, except the explicitly amended A6 execution report.
- Production, framework, adapters, tests, dependencies, toolchain and workflows.

All new files must be within §3.1. Do not stage raw indexes, build outputs, native/remote workspaces, container data or unrelated files.

Make one ordinary follow-up evidence commit on dev/perf06-a6 and push without force. Update the existing draft PR #125 body to reflect actual compatibility outcomes and unchanged numerical decisions. Use a body file with actual newlines; do not create a new PR, send unrelated comments/messages, merge or start B1.

Do not add a subsequent commit solely to record the final commit's own SHA or a CI observation. Put final local/remote identities and actual observed CI state in the handoff and PR body.

Suggested PR-body addition:

> A6-F1 corrects the supplied compatibility driver's SHA-256 hexadecimal serialization without changing production code or measured sources. Native compatibility: ACTUAL OUTCOME. Remote compatibility: ACTUAL OUTCOME. The two completed warm acquisitions and four writer observations remain byte-identical. Host stability observations were advisory and non-blocking by user instruction; general suites, quality checks and CI waits were not run. Overall disposition: DERIVED STATUS. R remains 15/16 retention gates met; C remains 2/4 primary and 12/12 guards met. Remote compaction publication remains unqualified; maintainer acceptance is open.

Replace only the explicitly identified outcome fields with observed facts. Never fill unexecuted work with expected results.

## 11. Acceptance checklist

- [ ] Original A6 evidence and original plan/support provenance preserved.
- [ ] Host observations advisory; no idle wait or host-stability gate.
- [ ] Exact one-function correction and corrected source hash.
- [ ] Successful E/F release builds with recorded executable identities.
- [ ] Three actual native PASS mode records.
- [ ] Three actual real-RustFS PASS mode records, or precise remaining block.
- [ ] Owned service cleanup recorded; no unrelated cleanup.
- [ ] R explanation corrected: both bounds failed; variability cause unestablished.
- [ ] Warm sorting scope corrected to ascending doc_id.
- [ ] No new benchmark/staging/resource work, suites, lint, coverage or CI wait.
- [ ] Correct final status; numerical misses and remote-compaction residual preserved.
- [ ] Same PR updated once; no merge or automatic B1 promotion.

## 12. Source and authoring basis

This amendment follows the repository guide's in-progress reconciliation, narrow-fixup, invariant, exact-command, source-ownership, decision-matrix and continuous-execution requirements. The explicit user instructions supersede the guide's ordinary suite/QA gates for this task.

Sources inspected for this amendment:

- [PR125 at reviewed head](https://github.com/yduchesne/quervant/pull/125).
- [Original execution report](https://github.com/yduchesne/quervant/blob/7573cb5169f40eb68207fc6d06aa89ec2f2f8ef4/docs/pr-artifacts/perf-06-a/PERF06A6_EXECUTION_REPORT.md).
- [Original frozen driver](https://github.com/yduchesne/quervant/blob/7573cb5169f40eb68207fc6d06aa89ec2f2f8ef4/docs/pr-artifacts/perf-06-a/a6/support/a6_compatibility.rs).
- [E build log](https://github.com/yduchesne/quervant/blob/7573cb5169f40eb68207fc6d06aa89ec2f2f8ef4/docs/pr-artifacts/perf-06-a/a6/compatibility/driver-build-E.log).
- [F build log](https://github.com/yduchesne/quervant/blob/7573cb5169f40eb68207fc6d06aa89ec2f2f8ef4/docs/pr-artifacts/perf-06-a/a6/compatibility/driver-build-F.log).
- [Authoring guide at accepted main](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md).
- [Pinned timed-query adapter](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/benchmarks/pr15d/adapters/quervant/src/main.rs).

Planning validation checks the exact source transformation and document command syntax. The corrected Rust helper has not been compiled or run during authoring. The two builds above establish that operational result; any new error follows the decision matrix.

