#!/usr/bin/env bash
# PR 14 P4 benchmark qualification wrapper (W01-W09, B01-B04).
# A --diagnostic run can never qualify.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

trials=3
diagnostic=0
idle=0
for arg in "$@"; do
  case "$arg" in
    --idle-confirmed) idle=1 ;;
    --diagnostic) diagnostic=1 ;;
    --trials) shift; trials="${1:-3}" ;;
    --trials=*) trials="${arg#--trials=}" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$diagnostic" -eq 0 && "$idle" -ne 1 ]]; then
  echo "qualified mode requires --idle-confirmed (competing benchmark workloads stopped)" >&2
  exit 2
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "tracked working tree is dirty; refusing qualified measurement" >&2
  exit 2
fi
for var in QUERVANT_RUSTFS_ENDPOINT QUERVANT_RUSTFS_BUCKET QUERVANT_RUSTFS_ACCESS_KEY QUERVANT_RUSTFS_SECRET_KEY; do
  if [[ -z "${!var:-}" ]]; then
    echo "$var must be set for real RustFS measurement" >&2
    exit 2
  fi
done

reports=()
for ((i = 1; i <= trials; i++)); do
  trial="t${i}"
  contention="unknown"
  if [[ "$diagnostic" -eq 0 ]]; then
    python3 benchmarks/scripts/check-pr07-contention.py --out "target/pr14-p4-contention-${trial}.json" >/dev/null
    contention="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("state","unknown"))' "target/pr14-p4-contention-${trial}.json")"
    if [[ "$contention" != "clear" ]]; then
      echo "trial $trial contention=$contention; refusing qualification" >&2
      exit 1
    fi
  fi
  env QUERVANT_P4_TRIAL="$trial" \
      QUERVANT_P4_IDLE_CONFIRMED="$([[ "$idle" -eq 1 ]] && echo 1)" \
      QUERVANT_P4_CONTENTION="$contention" \
      ${diagnostic:+QUERVANT_P4_DIAGNOSTIC=1} \
      cargo test -p quervant-core --all-features --test pr14_bench_remote -- --ignored --test-threads=1
  reports+=("benchmarks/reports/pr14-p4-${trial}.json")
done

if [[ "$diagnostic" -eq 0 ]]; then
  python3 benchmarks/scripts/validate-pr14-p4.py "${reports[@]}"
else
  echo "diagnostic run complete; not qualified"
fi
