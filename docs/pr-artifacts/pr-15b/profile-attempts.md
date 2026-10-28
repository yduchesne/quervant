# PR 15B CPU and allocation profiling attempts

## Result

**CPU/ALLOCATION ATTRIBUTION UNAVAILABLE.** No profiler is installed on the
qualification host. The wrapper was executed for every approved mode and returned
an explicit nonzero `UNAVAILABLE` status with the exact command-line error. No
sudo, package installation, sysctl change, kernel change or alternative sampling
agent was used.

This is an independent required *attempt*, not a claim of successful capture. The
bottleneck dossier therefore uses only repeatable Criterion timings and the
limited work counters, with correspondingly lower attribution confidence.

## Exact attempts

| Mode | Command | Exit | Output |
|---|---|---:|---|
| perf | `bash benchmarks/scripts/profile-pr15b.sh --mode perf --workload absent --out target/pr15b-profile-perf` | 2 | `UNAVAILABLE: perf is not installed.` |
| flamegraph | `bash benchmarks/scripts/profile-pr15b.sh --mode flamegraph --workload absent --out target/pr15b-profile-flamegraph` | 2 | `UNAVAILABLE: cargo-flamegraph is not installed.` |
| heaptrack | `bash benchmarks/scripts/profile-pr15b.sh --mode heaptrack --workload absent --out target/pr15b-profile-heaptrack` | 2 | `UNAVAILABLE: heaptrack is not installed.` |

The wrapper builds the release+debuginfo example first
(`CARGO_PROFILE_RELEASE_DEBUG=1 cargo build --release -p quervant-core --example pr15b_profile`)
and verifies the executable exists before checking the profiler. The build
succeeded; only the external tool is missing.

## Release driver verification (non-profiled)

The release example is not a profiler and its timings are not reported as
benchmark latency. It was executed for every accepted workload to prove the
driver/oracle wiring:

```text
./target/release/examples/pr15b_profile --workload absent      --seconds 1  -> rc 0
./target/release/examples/pr15b_profile --workload rare        --seconds 1  -> rc 0
./target/release/examples/pr15b_profile --workload mixed       --seconds 1  -> rc 0
./target/release/examples/pr15b_profile --workload json        --seconds 1  -> rc 0
./target/release/examples/pr15b_profile --workload sort        --seconds 1  -> rc 0
./target/release/examples/pr15b_profile --workload aggregation --seconds 1  -> rc 0
./target/release/examples/pr15b_profile --workload batch       --seconds 1  -> rc 0
```

Each run printed `status=started`, the untimed oracle passed, an iteration count
and `status=ok`. Invalid workload and invalid seconds exit 64 with a typed
message (verified in B-T14 and manually).

## Consequence for the dossier

- No source-level CPU percentage is claimed.
- No allocation or peak-RSS saving is claimed.
- No stack attribution is claimed.
- The "full-corpus scaling" and "segment fan-out" observations are labelled
  `HYPOTHESIS` until PR 15C can measure them with a profiler or approved counters.
- This limitation is disclosed in the final acceptance report.
