#!/usr/bin/env bash
# M1-V05 — cross-version compatibility harness.
#
# Builds TWO independent probe binaries from TWO source revisions:
#
#   baseline : the pre-M1 revision that does not know FEATURE_MUTATION_STATE_V2
#   current  : the M1 revision under test
#
# and proves, using real binaries and real on-disk indexes:
#
#   1. a genuine v1 index created by the baseline reader opens under the current
#      reader, and merely opening it does not upgrade its format;
#   2. single-key idempotency replay still works across the version boundary;
#   3. the first committed batch that requires durable replay upgrades the
#      payload, and the baseline reader then rejects the index with a typed
#      unsupported-feature error (never generic corruption, never a silent v1
#      fallback);
#   4. the baseline reader modifies no index files when it rejects the index;
#   5. the current reader still replays the durable batch exactly.
#
# The new decoder is never used to simulate the old reader: the old reader is a
# separate binary built from the baseline commit.
#
# Usage:
#   bash crates/quervant-core/tests/m1_compat/run.sh [baseline-sha] [current-ref]
#
# Defaults: baseline `cd3b9ac610e35628587faf38780fda778d53cd94`, current `HEAD`.
# Set KEEP_M1_COMPAT_ARTIFACTS=1 to keep the temporary worktrees for inspection.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT"

BASELINE_SHA="${1:-cd3b9ac610e35628587faf38780fda778d53cd94}"
CURRENT_REF="${2:-HEAD}"
PROBE_SRC="crates/quervant-core/tests/m1_compat/probe.rs"

[[ -f "$PROBE_SRC" ]] || { echo "missing probe source: $PROBE_SRC" >&2; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/quervant-m1-compat.XXXXXX")"
WORKTREES=()
cleanup() {
    if [[ "${KEEP_M1_COMPAT_ARTIFACTS:-0}" == "1" ]]; then
        echo "artifacts kept at $TMP"
        return
    fi
    for wt in "${WORKTREES[@]:-}"; do
        [[ -n "$wt" ]] && git worktree remove --force "$wt" >/dev/null 2>&1 || true
    done
    rm -rf "$TMP"
}
trap cleanup EXIT

PASS=0
FAIL=0
ok() { PASS=$((PASS + 1)); echo "  PASS  $*"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL  $*" >&2; }

# Sorted path+digest state of every file in an index directory.
tree_state() {
    ( cd "$1" && find . -type f -print0 | sort -z | xargs -0 --no-run-if-empty sha256sum )
}

echo "== M1-V05 cross-version compatibility =="
echo "repository : $ROOT"
echo "baseline   : $BASELINE_SHA"
echo "current    : $CURRENT_REF ($(git rev-parse "$CURRENT_REF"))"

BASE_WT="$TMP/baseline"
CUR_WT="$TMP/current"
git worktree add --detach "$BASE_WT" "$BASELINE_SHA" >/dev/null
WORKTREES+=("$BASE_WT")
git worktree add --detach "$CUR_WT" "$CURRENT_REF" >/dev/null
WORKTREES+=("$CUR_WT")

echo
echo "== baseline revision source check =="
if git -C "$BASE_WT" grep -q "FEATURE_MUTATION_STATE_V2" -- crates/quervant-core/src; then
    bad "baseline revision already knows FEATURE_MUTATION_STATE_V2; pick a pre-M1 commit"
    exit 1
fi
ok "baseline revision predates FEATURE_MUTATION_STATE_V2"
if git -C "$BASE_WT" grep -q "pub fn apply_batch" -- crates/quervant-core/src; then
    bad "baseline revision already exposes IndexWriter::apply_batch"
    exit 1
fi
ok "baseline revision has no IndexWriter::apply_batch"

echo
echo "== build independent probe binaries =="
mkdir -p "$BASE_WT/crates/quervant-core/examples" "$CUR_WT/crates/quervant-core/examples"
cp "$PROBE_SRC" "$BASE_WT/crates/quervant-core/examples/m1_compat_probe.rs"
cp "$PROBE_SRC" "$CUR_WT/crates/quervant-core/examples/m1_compat_probe.rs"

CARGO_TARGET_DIR="$TMP/target-baseline" \
    cargo build --quiet -p quervant-core --example m1_compat_probe \
    --manifest-path "$BASE_WT/Cargo.toml"
BASE_PROBE="$TMP/target-baseline/debug/examples/m1_compat_probe"

RUSTFLAGS="${RUSTFLAGS:-} --cfg m1_probe" CARGO_TARGET_DIR="$TMP/target-current" \
    cargo build --quiet -p quervant-core --example m1_compat_probe \
    --manifest-path "$CUR_WT/Cargo.toml"
CUR_PROBE="$TMP/target-current/debug/examples/m1_compat_probe"

[[ -x "$BASE_PROBE" && -x "$CUR_PROBE" ]] || { bad "probe binaries were not produced"; exit 1; }
ok "baseline probe built from $BASELINE_SHA"
ok "current probe built from $(git rev-parse "$CURRENT_REF")"

echo
echo "== baseline probe has no M1 batch mode (proves it is a pre-M1 reader) =="
set +e
"$BASE_PROBE" mkbatch "$TMP/none" >"$TMP/base-mkbatch.log" 2>&1
rc=$?
set -e
if [[ $rc -eq 64 ]]; then
    ok "baseline probe rejects the M1-only 'mkbatch' mode (exit 64)"
else
    bad "baseline probe unexpectedly accepted 'mkbatch' (exit $rc)"
fi

INDEX="$TMP/index"
mkdir -p "$INDEX"

echo
echo "== 1. create a genuine v1 index with the baseline reader =="
if "$BASE_PROBE" mkv1 "$INDEX" >"$TMP/mkv1.log" 2>&1 && grep -q '^CREATED=1' "$TMP/mkv1.log"; then
    ok "baseline created and committed a v1 index ($(grep '^GENERATION=' "$TMP/mkv1.log"))"
else
    bad "baseline failed to create the v1 index"; cat "$TMP/mkv1.log" >&2; exit 1
fi

echo
echo "== 2. current reader opens the v1 index without upgrading it =="
V1_STATE_BEFORE="$(tree_state "$INDEX")"
if "$CUR_PROBE" inspect "$INDEX" >"$TMP/cur-inspect-v1.log" 2>&1 \
    && grep -q '^OPEN=OK' "$TMP/cur-inspect-v1.log" \
    && grep -qx 'KEYS=a,b' "$TMP/cur-inspect-v1.log" \
    && "$CUR_PROBE" live "$INDEX" | grep -qx 'LIVE=a,b'; then
    ok "current reader opened the v1 index and read live keys a,b"
else
    bad "current reader could not open the genuine v1 index"; cat "$TMP/cur-inspect-v1.log" >&2
fi
V1_STATE_AFTER="$(tree_state "$INDEX")"
if [[ "$V1_STATE_BEFORE" == "$V1_STATE_AFTER" ]]; then
    ok "opening the v1 index with the current reader rewrote no files"
else
    bad "opening the v1 index modified index files"
    diff <(echo "$V1_STATE_BEFORE") <(echo "$V1_STATE_AFTER") >&2 || true
fi

echo
echo "== 3. single-key idempotency replay across the version boundary =="
if "$CUR_PROBE" replaysingle "$INDEX" >"$TMP/cur-replaysingle.log" 2>&1 \
    && grep -qx 'REPLAYED=true' "$TMP/cur-replaysingle.log"; then
    ok "current reader replayed the baseline single-key token ($(grep '^REVISION=' "$TMP/cur-replaysingle.log"))"
else
    bad "single-key idempotency replay failed across versions"; cat "$TMP/cur-replaysingle.log" >&2
fi
if [[ "$(tree_state "$INDEX")" == "$V1_STATE_AFTER" ]]; then
    ok "single-key replay left the committed v1 generation untouched"
else
    bad "single-key replay modified committed state"
fi

echo
echo "== 4. first durable batch-replay commit upgrades to v2 =="
if "$CUR_PROBE" mkbatch "$INDEX" >"$TMP/cur-mkbatch.log" 2>&1 \
    && grep -qx 'GENERATION=2' "$TMP/cur-mkbatch.log"; then
    ok "current reader committed the idempotent batch as generation 2"
    ok "batch outcomes: $(grep '^OUTCOME' "$TMP/cur-mkbatch.log" | tr '\n' ' ')"
else
    bad "batch commit failed"; cat "$TMP/cur-mkbatch.log" >&2; exit 1
fi
if "$CUR_PROBE" inspect "$INDEX" >"$TMP/cur-inspect-v2.log" 2>&1 \
    && grep -qx 'KEYS=a,b,c' "$TMP/cur-inspect-v2.log" \
    && "$CUR_PROBE" live "$INDEX" | grep -qx 'LIVE=a,c'; then
    ok "current reader observes the committed batch effects (live a,c; b is a tombstone whose document is not yet compacted)"
else
    bad "current reader did not observe the batch effects"; cat "$TMP/cur-inspect-v2.log" >&2
fi

echo
echo "== 5. genuine pre-M1 reader rejects the upgraded v2 index =="
V2_STATE_BEFORE="$(tree_state "$INDEX")"
set +e
"$BASE_PROBE" inspect "$INDEX" >"$TMP/base-inspect-v2.log" 2>&1
rc=$?
set -e
if [[ $rc -eq 3 ]]; then
    ok "baseline reader rejected the upgraded index (exit 3)"
else
    bad "baseline reader exit $rc, expected the typed rejection 3"; cat "$TMP/base-inspect-v2.log" >&2
fi
if grep -qx 'REJECTION=UnsupportedFeature' "$TMP/base-inspect-v2.log"; then
    ok "rejection is the typed unsupported-feature error, not corruption"
else
    bad "expected a typed unsupported-feature rejection"
    sed -n '1,20p' "$TMP/base-inspect-v2.log" >&2
fi
echo "  baseline error chain:"
sed -n 's/^/    /p' "$TMP/base-inspect-v2.log"
V2_STATE_AFTER="$(tree_state "$INDEX")"
if [[ "$V2_STATE_BEFORE" == "$V2_STATE_AFTER" ]]; then
    ok "the rejecting baseline reader modified no index files"
else
    bad "the rejecting baseline reader modified index files"
    diff <(echo "$V2_STATE_BEFORE") <(echo "$V2_STATE_AFTER") >&2 || true
fi

echo
echo "== 6. current reader still replays the durable batch exactly =="
if "$CUR_PROBE" replay "$INDEX" >"$TMP/cur-replay.log" 2>&1 \
    && grep -qx 'REPLAYED=true' "$TMP/cur-replay.log" \
    && grep -q 'replayed=true' "$TMP/cur-replay.log"; then
    ok "durable batch replay marked replayed at batch and per-key level"
    ok "replayed outcomes: $(grep '^OUTCOME' "$TMP/cur-replay.log" | tr '\n' ' ')"
else
    bad "durable batch replay failed"; cat "$TMP/cur-replay.log" >&2
fi

echo
echo "== probe binaries =="
echo "  baseline sha256 $(sha256sum "$BASE_PROBE" | cut -d' ' -f1)"
echo "  current  sha256 $(sha256sum "$CUR_PROBE" | cut -d' ' -f1)"

echo
echo "M1-V05 summary: ${PASS} passed, ${FAIL} failed"
[[ "$FAIL" -eq 0 ]] || exit 1
