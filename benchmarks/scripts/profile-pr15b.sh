#!/usr/bin/env bash
# PR 15B release profiling wrapper (perf | flamegraph | heaptrack).
#
# Missing tools are reported UNAVAILABLE with a nonzero exit; profiling is never
# claimed without a captured report. This script never uses sudo, never changes
# perf_event_paranoid/kernel settings and never auto-installs packages.
set -euo pipefail

MODE=""
WORKLOAD=""
OUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode) MODE="${2:?--mode requires a value}"; shift 2 ;;
        --workload) WORKLOAD="${2:?--workload requires a value}"; shift 2 ;;
        --out) OUT="${2:?--out requires a value}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 64 ;;
    esac
done

if [[ -z "$MODE" ]]; then echo "--mode is required" >&2; exit 64; fi
if [[ -z "$WORKLOAD" ]]; then echo "--workload is required" >&2; exit 64; fi
if [[ -z "$OUT" ]]; then echo "--out is required" >&2; exit 64; fi

case "$MODE" in
    perf | flamegraph | heaptrack) ;;
    *) echo "unknown profiling mode: $MODE (expected perf|flamegraph|heaptrack)" >&2; exit 64 ;;
esac

case "$WORKLOAD" in
    absent | rare | mixed | json | sort | aggregation | batch) ;;
    *) echo "unknown workload: $WORKLOAD" >&2; exit 64 ;;
esac

if [[ -e "$OUT" && ! -d "$OUT" ]]; then
    echo "--out exists and is not a directory: $OUT" >&2
    exit 73
fi
mkdir -p "$OUT"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Build the profile entrypoint with debuginfo outside of any timing.
CARGO_PROFILE_RELEASE_DEBUG=1 cargo build --release -p quervant-core --example pr15b_profile >/dev/null
BIN="target/release/examples/pr15b_profile"
if [[ ! -x "$BIN" ]]; then
    echo "profile entrypoint was not built: $BIN" >&2
    exit 70
fi

case "$MODE" in
    perf)
        if ! command -v perf >/dev/null 2>&1; then
            echo "UNAVAILABLE: perf is not installed. Install linux-tools for the kernel or run on a host with perf; see benchmarks/README.md." >&2
            exit 2
        fi
        perf record -g --call-graph dwarf -o "$OUT/perf.data" -- \
            "$BIN" --workload "$WORKLOAD" --seconds 20
        perf report --stdio -i "$OUT/perf.data" >"$OUT/perf-report.txt"
        echo "perf report: $OUT/perf-report.txt"
        ;;
    flamegraph)
        if ! command -v cargo-flamegraph >/dev/null 2>&1; then
            echo "UNAVAILABLE: cargo-flamegraph is not installed (cargo install flamegraph)." >&2
            exit 2
        fi
        if ! command -v perf >/dev/null 2>&1; then
            echo "UNAVAILABLE: cargo flamegraph requires perf, which is not installed." >&2
            exit 2
        fi
        cargo flamegraph --release -p quervant-core --example pr15b_profile \
            -o "$OUT/flamegraph.svg" -- --workload "$WORKLOAD" --seconds 20
        echo "flamegraph: $OUT/flamegraph.svg"
        ;;
    heaptrack)
        if ! command -v heaptrack >/dev/null 2>&1; then
            echo "UNAVAILABLE: heaptrack is not installed. Install it via the distribution package manager; see benchmarks/README.md." >&2
            exit 2
        fi
        heaptrack -o "$OUT/heaptrack" "$BIN" --workload "$WORKLOAD" --seconds 20
        echo "heaptrack: $OUT/heaptrack"
        ;;
esac
