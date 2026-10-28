#!/usr/bin/env bash
# PR 15B qualified unified-search diagnostics runner.
#
# - Rejects dirty/contended/unknown host states from qualification.
# - Runs the release Criterion target with an isolated CRITERION_HOME per trial.
# - Preserves raw Criterion output under ignored target/ and emits only a small
#   source-locked trial manifest per trial.
# - Aggregates >=3 qualified source-identical trials into a checked-in summary.
#
# This script never force-stops processes, never uses sudo and never loosens a
# tool policy. A dirty tree or missing idle attestation yields an UNQUALIFIED
# diagnostic trial, never a published aggregate.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TRIALS=3
IDLE_CONFIRMED=0
ALLOW_CONTENDED=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --trials) TRIALS="${2:?--trials requires a count}"; shift 2 ;;
        --idle-confirmed) IDLE_CONFIRMED=1; shift ;;
        --allow-contended) ALLOW_CONTENDED=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 64 ;;
    esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "run-pr15b.sh must run on Linux/WSL2" >&2
    exit 2
fi
FS="$(findmnt -T "$ROOT" -n -o FSTYPE 2>/dev/null || echo unknown)"
case "$FS" in
    drvfs | 9p | v9fs | cifs | smb*)
        echo "BLOCKED: filesystem '$FS' is not a native Linux filesystem; results are not publishable." >&2
        exit 2
        ;;
esac

CANONICAL_SHA="$(sha256sum benchmarks/datasets/pr15a_v1.json | awk '{print $1}')"
EXPECTED_CANONICAL="104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087"
if [[ "$CANONICAL_SHA" != "$EXPECTED_CANONICAL" ]]; then
    echo "BLOCKED: canonical pr15a_v1 digest mismatch: $CANONICAL_SHA" >&2
    exit 2
fi

SHA="$(git rev-parse HEAD)"
if [[ -n "$(git status --porcelain)" ]]; then
    DIRTY=true
else
    DIRTY=false
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="target/pr15b/${STAMP}-${SHA}"
if [[ -e "$BASE" ]]; then
    suffix=1
    while [[ -e "${BASE}-${suffix}" ]]; do
        suffix=$((suffix + 1))
    done
    BASE="${BASE}-${suffix}"
fi
mkdir -p "$BASE"

CONTENTION="benchmarks/scripts/check-pr07-contention.py"
VALIDATOR="benchmarks/scripts/validate-pr15b.py"
ENV_CAPTURE="benchmarks/scripts/capture-pr07-env.sh"

echo "run_base=$BASE"
echo "git_sha=$SHA dirty=$DIRTY trials=$TRIALS idle_confirmed=$IDLE_CONFIRMED"

contention_state() {
    local out="$1"
    set +e
    python3 "$CONTENTION" --out "$out" --sample-seconds 2 >/dev/null 2>&1
    local rc=$?
    set -e
    if [[ -f "$out" ]]; then
        python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["state"])' "$out"
    else
        echo "unknown"
    fi
    return "$rc"
}

TRIAL_MANIFESTS=()
ALL_QUALIFIED=true
for trial in $(seq 1 "$TRIALS"); do
    OUT="$BASE/trial-$trial"
    mkdir -p "$OUT"
    OUT_ABS="$(cd "$OUT" && pwd)"
    echo "=== trial $trial: $OUT ==="

    PRE_STATE="$(contention_state "$OUT/contention-pre.json" || true)"
    echo "contention_pre=$PRE_STATE"
    if [[ "$PRE_STATE" != "clear" && "$ALLOW_CONTENDED" != 1 ]]; then
        echo "BLOCKED: contention state '$PRE_STATE' prevents qualification; use --allow-contended for a diagnostic-only run." >&2
        exit 3
    fi

    bash "$ENV_CAPTURE" --out "$OUT/env.txt"

    export CRITERION_HOME="$OUT_ABS/criterion"
    rm -rf "$CRITERION_HOME"
    mkdir -p "$CRITERION_HOME"
    export QUERVANT_PR15B_METADATA="$OUT_ABS/fixture-metadata.json"
    rm -f "$QUERVANT_PR15B_METADATA"

    set +e
    cargo bench -p quervant-core --bench unified_diagnostics 2>&1 | tee "$OUT/bench.log"
    BENCH_RC=${PIPESTATUS[0]}
    set -e
    unset QUERVANT_PR15B_METADATA

    POST_STATE="$(contention_state "$OUT/contention-post.json" || true)"
    echo "contention_post=$POST_STATE"
    FINAL_STATE="$(contention_state "$OUT/contention-final.json" || true)"
    echo "contention_final=$FINAL_STATE"

    STATE="clear"
    for candidate in "$PRE_STATE" "$POST_STATE" "$FINAL_STATE"; do
        if [[ "$candidate" != "clear" ]]; then
            STATE="$candidate"
        fi
    done

    CORRECTNESS_FLAG=()
    if [[ "$BENCH_RC" == 0 && -f "$OUT_ABS/fixture-metadata.json" ]]; then
        CORRECTNESS_FLAG=(--correctness-passed)
    fi
    IDLE_FLAG=()
    [[ "$IDLE_CONFIRMED" == 1 ]] && IDLE_FLAG=(--idle-confirmed)
    DIRTY_FLAG=()
    [[ "$DIRTY" == true ]] && DIRTY_FLAG=(--source-dirty)

    set +e
    python3 "$VALIDATOR" trial \
        --criterion-dir "$CRITERION_HOME" \
        --fixture-metadata "$OUT_ABS/fixture-metadata.json" \
        --env-file "$OUT_ABS/env.txt" \
        --out "$OUT_ABS/trial.json" \
        --run-id "trial-$trial" \
        --source-sha "$SHA" \
        --contention-state "$STATE" \
        "${IDLE_FLAG[@]}" \
        "${DIRTY_FLAG[@]}" \
        "${CORRECTNESS_FLAG[@]}"
    VALIDATOR_RC=$?
    set -e

    if [[ "$VALIDATOR_RC" != 0 ]]; then
        ALL_QUALIFIED=false
        echo "trial $trial is UNQUALIFIED (validator rc=$VALIDATOR_RC, bench rc=$BENCH_RC)"
    else
        echo "trial $trial is QUALIFIED"
    fi
    TRIAL_MANIFESTS+=("$OUT_ABS/trial.json")
done

if [[ "$ALL_QUALIFIED" == true && "$TRIALS" -ge 3 ]]; then
    AGG_ARGS=()
    for manifest in "${TRIAL_MANIFESTS[@]}"; do
        [[ -f "$manifest" ]] && AGG_ARGS+=(--trial "$manifest")
    done
    if [[ "${#AGG_ARGS[@]}" -ge 6 ]]; then
        python3 "$VALIDATOR" aggregate \
            "${AGG_ARGS[@]}" \
            --out "$BASE/pr15b-qualified.json" \
            --out-md "$BASE/pr15b-qualified.md"
        echo "QUALIFIED summary written under $BASE"
        exit 0
    fi
fi

echo "PR15B QUALIFICATION BLOCKED: clean=$([[ "$DIRTY" == false ]] && echo true || echo false) idle=$IDLE_CONFIRMED trials=$TRIALS"
echo "Artifacts preserved under $BASE (diagnostic/unqualified)."
exit 3
