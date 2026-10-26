#!/usr/bin/env bash
# PR 14 P4 benchmark qualification wrapper (W01-W09, B01-B04).
# A --diagnostic run can never qualify. Qualified mode requires an explicit
# human operator `--idle-confirmed` attestation and a fresh `clear` contention
# record for every trial. Fresh reports are written under ignored `target/` so
# the tracked historical reports stay byte-identical.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

trials=3
diagnostic=0
idle=0

while (( $# > 0 )); do
  case "$1" in
    --idle-confirmed)
      idle=1
      shift
      ;;
    --diagnostic)
      diagnostic=1
      shift
      ;;
    --trials)
      if (( $# < 2 )); then
        echo "--trials requires a value" >&2
        exit 2
      fi
      trials="$2"
      shift 2
      ;;
    --trials=*)
      trials="${1#--trials=}"
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! "$trials" =~ ^[0-9]+$ ]] || (( 10#$trials < 1 || 10#$trials > 20 )); then
  echo "--trials must be a decimal integer in 1..20 (got: $trials)" >&2
  exit 2
fi
trials=$(( 10#$trials ))

if [[ "$diagnostic" -eq 0 && "$idle" -ne 1 ]]; then
  echo "qualified mode requires --idle-confirmed (competing benchmark workloads stopped)" >&2
  exit 2
fi
if [[ "$diagnostic" -eq 0 && "$trials" -ne 3 ]]; then
  echo "publication requires exactly three distinct qualified trials (got: $trials)" >&2
  exit 2
fi

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "tracked working tree is dirty; refusing qualified measurement" >&2
  exit 2
fi
source_sha="$(git rev-parse HEAD)"
if [[ ! "$source_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "cannot resolve a 40-character source SHA (got: '${source_sha}')" >&2
  exit 2
fi
for var in QUERVANT_RUSTFS_ENDPOINT QUERVANT_RUSTFS_BUCKET QUERVANT_RUSTFS_ACCESS_KEY QUERVANT_RUSTFS_SECRET_KEY; do
  if [[ -z "${!var:-}" ]]; then
    echo "$var must be set for real RustFS measurement" >&2
    exit 2
  fi
done

report_dir="target/pr14-p4/reports/$source_sha"
qualification_dir="target/pr14-p4/qualification/$source_sha"
mkdir -p "$report_dir" "$qualification_dir"

reports=()
for ((i = 1; i <= trials; i++)); do
  trial="t${i}"
  contention="unknown"
  if [[ "$diagnostic" -eq 0 ]]; then
    contention_path="$qualification_dir/pr14-p4-contention-${trial}.json"
    if ! python3 benchmarks/scripts/check-pr07-contention.py --out "$contention_path" >/dev/null; then
      echo "trial $trial contention check failed; refusing qualification" >&2
      exit 1
    fi
    if [[ ! -s "$contention_path" ]]; then
      echo "trial $trial contention record missing; refusing qualification" >&2
      exit 1
    fi
    contention="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("state","unknown"))' "$contention_path")"
    if [[ "$contention" != "clear" ]]; then
      echo "trial $trial contention=$contention; refusing qualification" >&2
      exit 1
    fi
  fi

  run_env=(env -u QUERVANT_P4_DIAGNOSTIC
           "QUERVANT_P4_TRIAL=$trial"
           "QUERVANT_P4_IDLE_CONFIRMED=$idle"
           "QUERVANT_P4_CONTENTION=$contention"
           "QUERVANT_P4_REPORT_DIR=$report_dir")
  if (( diagnostic == 1 )); then
    run_env+=("QUERVANT_P4_DIAGNOSTIC=1")
  fi
  run_log="$qualification_dir/pr14-p4-${trial}-run.log"
  "${run_env[@]}" cargo test -p quervant-core --all-features \
    --test pr14_bench_remote -- --ignored --exact pr14_p4_benchmark --nocapture --test-threads=1 \
    2>&1 | tee "$run_log"
  if ! grep -q '1 passed' "$run_log"; then
    echo "trial $trial did not report exactly one executed benchmark test" >&2
    exit 1
  fi
  if [[ "$diagnostic" -eq 0 ]] && ! grep -q 'qualified=true' "$run_log"; then
    echo "trial $trial did not report qualified=true" >&2
    exit 1
  fi
  report="$report_dir/pr14-p4-${trial}.json"
  if [[ ! -s "$report" ]]; then
    echo "trial $trial report missing at $report" >&2
    exit 1
  fi
  reports+=("$report")
done

if [[ "$diagnostic" -eq 0 ]]; then
  python3 benchmarks/scripts/validate-pr14-p4.py \
    --w08-exemption benchmarks/reports/pr14-p4-w08-exemption.json \
    "${reports[@]}"
else
  echo "diagnostic run complete; not qualified"
fi
