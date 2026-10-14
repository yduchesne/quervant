#!/usr/bin/env bash
# Capture reproduction/environment provenance for PR 7 Amendment 04 baselines.
# Prints to stdout and optionally appends to --out <file>. Never collects user
# identity, hostname, home paths, IPs, tokens or secrets.
set -euo pipefail

OUT=""
if [[ "${1:-}" == "--out" ]]; then
    OUT="${2:?--out requires a path}"
fi

emit() {
    echo "$@"
    if [[ -n "$OUT" ]]; then
        echo "$@" >>"$OUT"
    fi
}

if [[ -n "$OUT" ]]; then
    mkdir -p "$(dirname "$OUT")"
    : >"$OUT"
fi

emit "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
emit "git_sha=$(git rev-parse HEAD 2>/dev/null || echo unknown)"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if [[ -n "$(git status --porcelain)" ]]; then
        emit "git_dirty=true"
    else
        emit "git_dirty=false"
    fi
else
    emit "git_dirty=unknown"
fi
emit "rustc=$(rustc -Vv | tr '\n' ' ')"
emit "cargo=$(cargo -V)"
emit "uname=$(uname -a)"
emit "cpu_model=$(grep -m1 'model name' /proc/cpuinfo | sed 's/.*: //')"
emit "logical_cpus=$(nproc 2>/dev/null || echo unknown)"
emit "mem_total=$(grep -m1 MemTotal /proc/meminfo 2>/dev/null | awk '{print $2" "$3}')"
if uname -r | grep -qi microsoft; then
    emit "wsl2=true"
else
    emit "wsl2=false"
fi
emit "filesystem=$(findmnt -T "$(pwd)" -n -o FSTYPE 2>/dev/null || echo unknown)"

for tool in perf cargo-flamegraph heaptrack hyperfine; do
    if command -v "$tool" >/dev/null 2>&1; then
        emit "${tool}_path=$(command -v "$tool")"
    else
        emit "${tool}_path=UNAVAILABLE"
    fi
done

if [[ -f Cargo.lock ]]; then
    version="$(grep -A1 '^name = "criterion"$' Cargo.lock | grep '^version' | head -1 | cut -d'"' -f2 || true)"
    emit "criterion_version=${version:-unknown}"
fi
