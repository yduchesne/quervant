#!/usr/bin/env bash
#
# PR 3 RustFS harness foundation (opt-in).
#
# This script is the integration entry point for the future production
# S3/RustFS adapter. That adapter belongs to PR 13. Until it exists, this script
# reports an explicit SKIP and exits 0. A SKIP is not a pass, and no RustFS
# compatibility is claimed by PR 3.
#
# Usage:
#   QUERVANT_PRODUCTION_S3_ADAPTER=1 tests/rustfs/run.sh
#
# Environment:
#   QUERVANT_PRODUCTION_S3_ADAPTER  must be 1 to attempt real adapter tests
#   RUSTFS_PORT                    S3 API port (default 9000)
#   RUSTFS_CONSOLE_PORT            console port (default 9001)
#   RUSTFS_ACCESS_KEY              disposable test credential
#   RUSTFS_SECRET_KEY              disposable test credential
#   RUSTFS_COMPOSE_PROJECT         compose project/prefix for isolation
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
readonly PROJECT="${RUSTFS_COMPOSE_PROJECT:-quervant-rustfs-pr3}"

log() { printf '[rustfs-harness] %s\n' "$*"; }
skip() {
  log "SKIP: $*"
  exit 0
}

# The production adapter gate. PR 13 flips this once a real adapter exists.
if [[ "${QUERVANT_PRODUCTION_S3_ADAPTER:-0}" != "1" ]]; then
  skip "production S3/RustFS adapter is not implemented (PR 13); no RustFS conformance is claimed"
fi

if command -v podman >/dev/null 2>&1; then
  RUNTIME=podman
elif command -v docker >/dev/null 2>&1; then
  RUNTIME=docker
else
  skip "no container runtime (podman/docker) available"
fi

: "${RUSTFS_ACCESS_KEY:=quervant-test-access}"
: "${RUSTFS_SECRET_KEY:=quervant-test-secret}"
: "${RUSTFS_PORT:=9000}"
export RUSTFS_ACCESS_KEY RUSTFS_SECRET_KEY RUSTFS_PORT

compose() {
  "$RUNTIME" compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
  log "stopping and removing harness resources"
  compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "starting pinned RustFS harness (project: ${PROJECT})"
compose up -d

log "waiting for the S3 API health endpoint"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${RUSTFS_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1:${RUSTFS_PORT}/health" >/dev/null

log "RustFS is reachable on http://127.0.0.1:${RUSTFS_PORT}"
log "PR 13 runs the production adapter put/head/get, ranged read, timeout/corruption and cold bootstrap tests here."
log "Use an isolated bucket prefix per run (for example quervant-pr13-<random>); never reuse committed object keys."
