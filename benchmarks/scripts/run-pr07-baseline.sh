#!/usr/bin/env bash
# Reproducible PR 7 Amendment 04 (Correction 01) baseline runner.
#
# - Correctness gate before timing.
# - Contention checks before, between and after Criterion targets.
# - Fail-closed: suspected/unknown contention blocks unless --allow-contended.
# - Criterion output isolated per run via CRITERION_HOME.
# - Independently generated fixture metadata; v2 report assembled from real
#   Criterion artifacts and validated.
#
# Qualification also requires --idle-confirmed (operator attestation that
# competing benchmark workloads such as MTMF are stopped) and a clean tree.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

ALLOW_CONTENDED="${QUERVANT_BENCH_ALLOW_CONTENDED:-0}"
IDLE_CONFIRMED="${QUERVANT_BENCH_IDLE_CONFIRMED:-0}"
TRIALS=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --allow-contended) ALLOW_CONTENDED=1; shift ;;
        --idle-confirmed) IDLE_CONFIRMED=1; shift ;;
        --trials) TRIALS="${2:?--trials requires a count}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 64 ;;
    esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "run-pr07-baseline.sh must run on Linux/WSL2" >&2
    exit 2
fi
FS="$(findmnt -T "$ROOT" -n -o FSTYPE 2>/dev/null || echo unknown)"
case "$FS" in
    drvfs | 9p | v9fs | cifs | smb*)
        echo "WARNING: filesystem '$FS' is not a native Linux filesystem; results are not publishable." >&2
        ;;
esac

SHA="$(git rev-parse --short HEAD)"
if [[ -n "$(git status --porcelain)" ]]; then
    DIRTY=true
else
    DIRTY=false
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="target/pr07-baseline/${STAMP}-${SHA}"
if [[ -e "$BASE" ]]; then
    suffix=1
    while [[ -e "${BASE}-${suffix}" ]]; do
        suffix=$((suffix + 1))
    done
    BASE="${BASE}-${suffix}"
fi
mkdir -p "$BASE"

CONTENTION="benchmarks/scripts/check-pr07-contention.py"
BUILDER="benchmarks/scripts/build-pr07-report.py"
VALIDATOR="benchmarks/scripts/validate-report.py"
TARGETS=(bm25 dictionary postings phrase search)

echo "run_base=$BASE"
echo "git_sha=$SHA dirty=$DIRTY trials=$TRIALS allow_contended=$ALLOW_CONTENDED idle_confirmed=$IDLE_CONFIRMED"

# check_contention <outfile>; returns 0 clear, 3 suspected/unknown, 70 failure.
check_contention() {
    local out="$1"
    set +e
    python3 "$CONTENTION" --out "$out" --sample-seconds 2 >/dev/null 2>&1
    local rc=$?
    set -e
    return "$rc"
}

TRIAL_REPORTS=()
ALL_QUALIFIED=true
for trial in $(seq 1 "$TRIALS"); do
    OUT="$BASE/trial-$trial"
    mkdir -p "$OUT"
    # Cargo runs bench binaries with cwd = the package directory, so CRITERION_HOME
    # and all builder inputs must be absolute to avoid writing under the crate dir.
    OUT_ABS="$(cd "$OUT" && pwd)"
    TRIAL_QUALIFIED=true
    echo "=== trial $trial: $OUT ==="

    if check_contention "$OUT/contention-pre.json"; then
        PRE_STATE=clear
    else
        PRE_STATE=contended
        echo "contention pre-check did not return clear for trial $trial"
        if [[ "$ALLOW_CONTENDED" != 1 ]]; then
            echo "BLOCKED: resolve contention or pass --allow-contended for a diagnostic-only run" >&2
            exit 3
        fi
        TRIAL_QUALIFIED=false
    fi

    bash benchmarks/scripts/capture-pr07-env.sh --out "$OUT/env.txt"

    echo "--- correctness oracle ---"
    cargo test -p quervant-core --test pr07_amendment04 2>&1 | tee "$OUT/oracle.log"
    CORRECTNESS_PASSED=1

    echo "--- fixture metadata ---"
    cargo run --release -p quervant-core --example pr07_report_metadata >"$OUT/fixture-metadata.json"

    export CRITERION_HOME="$OUT_ABS/criterion"
    rm -rf "$CRITERION_HOME"
    mkdir -p "$CRITERION_HOME"

    # Deterministic rotation of target order across trials.
    rotate=$(((trial - 1) % ${#TARGETS[@]}))
    ordered=("${TARGETS[@]:rotate}" "${TARGETS[@]:0:rotate}")
    for target in "${ordered[@]}"; do
        echo "--- criterion: $target ---"
        cargo bench -p quervant-core --bench "$target" 2>&1 | tee "$OUT/bench-${target}.log"
        if ! check_contention "$OUT/contention-after-${target}.json"; then
            echo "trial $trial unqualified: contention after target $target"
            TRIAL_QUALIFIED=false
        fi
    done
    if ! check_contention "$OUT/contention-final.json"; then
        TRIAL_QUALIFIED=false
    fi

    # Determine environment state.
    if [[ "$ALLOW_CONTENDED" == 1 ]]; then
        ENV_STATE=diagnostic
    elif [[ "$TRIAL_QUALIFIED" != true ]]; then
        ENV_STATE=unqualified_contention
    elif [[ "$DIRTY" == true ]]; then
        ENV_STATE=diagnostic
    elif [[ "$IDLE_CONFIRMED" != 1 ]]; then
        ENV_STATE=diagnostic
    else
        ENV_STATE=qualified
    fi

    CHECKS=()
    for f in "$OUT"/contention-*.json; do
        CHECKS+=(--check "$f")
    done
    IDLE_FLAG=()
    [[ "$IDLE_CONFIRMED" == 1 ]] && IDLE_FLAG=(--operator-idle-confirmed)
    PROFILER_STATUS="$(grep -E '^(perf|heaptrack)_path=' "$OUT/env.txt" | grep -q 'UNAVAILABLE' && echo UNAVAILABLE || echo AVAILABLE)"

    python3 "$BUILDER" \
        --criterion-dir "$CRITERION_HOME" \
        --fixture-metadata "$OUT_ABS/fixture-metadata.json" \
        --env-file "$OUT_ABS/env.txt" \
        --run-id "$(basename "$OUT")" \
        --environment-state "$ENV_STATE" \
        --profiler-status "$PROFILER_STATUS" \
        --correctness-passed \
        "${IDLE_FLAG[@]}" \
        "${CHECKS[@]}" \
        --out "$OUT_ABS/report-v2.json"

    python3 "$VALIDATOR" --fixture-metadata "$OUT_ABS/fixture-metadata.json" "$OUT_ABS/report-v2.json"

    if [[ "$ENV_STATE" != qualified ]]; then
        ALL_QUALIFIED=false
    fi
    TRIAL_REPORTS+=("$OUT_ABS/report-v2.json")
    echo "trial $trial environment_state=$ENV_STATE pre=$PRE_STATE"
done

if [[ "$ALL_QUALIFIED" == true && "$TRIALS" -ge 3 ]]; then
    python3 benchmarks/scripts/aggregate-pr07-baseline.py \
        --fixture-metadata "$BASE/trial-1/fixture-metadata.json" \
        --trial-report "${TRIAL_REPORTS[@]}" \
        --out-json "$BASE/pr07-amendment04-qualified-baseline.json" \
        --out-md "$BASE/pr07-amendment04-qualified-baseline.md"
    echo "QUALIFIED baseline written under $BASE"
else
    echo "BASELINE QUALIFICATION BLOCKED: $TRIALS trial(s), all_qualified=$ALL_QUALIFIED"
    echo "Artifacts preserved under $BASE (diagnostic/unqualified)."
    exit 3
fi
