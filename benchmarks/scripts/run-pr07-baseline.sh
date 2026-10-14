#!/usr/bin/env bash
# Reproducible PR 7 Amendment 04 baseline runner.
#
# Correctness first, then the five Criterion targets sequentially. Raw logs and
# environment provenance are written to an untracked, SHA-scoped directory. Prior
# results are never deleted or overwritten.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "run-pr07-baseline.sh must run on Linux/WSL2" >&2
    exit 2
fi

FS="$(findmnt -T "$ROOT" -n -o FSTYPE 2>/dev/null || echo unknown)"
case "$FS" in
    drvfs | 9p | v9fs | cifs | smb*)
        echo "WARNING: filesystem '$FS' is not a native Linux filesystem; results may not be publishable." >&2
        ;;
esac

SHA="$(git rev-parse --short HEAD)"
if [[ -n "$(git status --porcelain)" ]]; then
    DIRTY=true
else
    DIRTY=false
fi
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-${SHA}"
OUT="target/pr07-baseline/${RUN_ID}"
# Never overwrite a prior run: disambiguate an existing directory.
if [[ -e "$OUT" ]]; then
    suffix=1
    while [[ -e "${OUT}-${suffix}" ]]; do
        suffix=$((suffix + 1))
    done
    OUT="${OUT}-${suffix}"
    RUN_ID="$(basename "$OUT")"
fi
mkdir -p "$OUT"

echo "run_id=$RUN_ID"
echo "dirty=$DIRTY"
echo "output=$OUT"

bash benchmarks/scripts/capture-pr07-env.sh --out "$OUT/env.txt"

echo "=== correctness oracle (pr07_amendment04) ==="
cargo test -p quervant-core --test pr07_amendment04 2>&1 | tee "$OUT/oracle.log"

for target in bm25 dictionary postings phrase search; do
    echo "=== criterion bench: $target ==="
    cargo bench -p quervant-core --bench "$target" 2>&1 | tee "$OUT/bench-${target}.log"
done

echo "Baseline complete: $OUT"
echo "Criterion machine-readable data: target/criterion (untracked)"
if [[ "$DIRTY" == "true" ]]; then
    echo "NOTE: working tree was dirty; do not publish this run as a clean baseline."
fi
