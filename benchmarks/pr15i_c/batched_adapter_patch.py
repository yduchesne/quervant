#!/usr/bin/env python3
"""PR 15I-C — source-locked derived diagnostic adapter (batched noise v1).

Creates an **ephemeral** copy of the frozen PR15D Quervant adapter crate in the
campaign's ignored ``target/`` directory and applies exactly two deterministic
hunks that add a diagnostic ``query_batch`` op:

* ``handle_query_batch`` inserted immediately after ``handle_query``;
* one ``"query_batch"`` arm inserted immediately before ``"metadata"``.

The frozen adapter in ``benchmarks/pr15d/`` is never modified. The patcher pins
the Git blob SHA-256 of the frozen ``main.rs`` and the normalized source of the
functions the patch must not touch, and refuses to proceed on any drift.

The measured batch timer is one outer Rust ``Instant`` interval enclosing
``repeat_count`` sequential real ``search()`` calls on the session's single
snapshot. No Python IPC time is measured and no per-iteration ``engine_ns`` is
summed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "batched_protocol_v1.json")
BASELINE_SHA = "6f6463cb26bcf28340cc9d4afd4dfeb040281898"
FROZEN_ADAPTER_MAIN = "benchmarks/pr15d/adapters/quervant/src/main.rs"
FROZEN_ADAPTER_DIR = "benchmarks/pr15d/adapters/quervant"
EXPECTED_MAIN_SHA = "42d2858ec406aa01b2556504a07907e1b2bc9891d596c684b1a9ba99ede78a63"
UNTOUCHED_FUNCTIONS = ("search", "handle_query", "impl QuerySession")

BATCH_HANDLER_ANCHOR = "\n/// One query session: the state an adapter process holds while it serves queries"
ARM_ANCHOR = '            "metadata" => Ok(json!({'

BATCH_HANDLER = '''
/// Diagnostic-only batched query handler.
///
/// Runs `repeat_count` sequential real [`search`] calls against the session's
/// existing snapshot inside **one** outer `Instant` interval and returns the raw
/// integer batch nanoseconds. No per-iteration `engine_ns` is accumulated,
/// divided or subtracted, and no `engine_ns` field is emitted, so the original
/// single-query validator can never mistake this reply for a query sample.
fn handle_query_batch(
    snapshot: &ReaderSnapshot,
    request: &Value,
) -> Result<Value, AdapterError> {
    let field = request
        .get("field")
        .and_then(Value::as_str)
        .ok_or_else(|| AdapterError::new("request", "query requires field"))?;
    if field != "key" && field != "group" {
        return Err(AdapterError::new(
            "request",
            "mandatory lane only searches key/group",
        ));
    }
    let term = request
        .get("term")
        .and_then(Value::as_str)
        .ok_or_else(|| AdapterError::new("request", "query requires term"))?;
    let k = request
        .get("k")
        .and_then(Value::as_u64)
        .ok_or_else(|| AdapterError::new("request", "query requires positive k"))?;
    let k = usize::try_from(k).map_err(|error| AdapterError::new("request", error.to_string()))?;
    if k == 0 {
        return Err(AdapterError::new("request", "k must be positive"));
    }
    let repeat_count = request
        .get("repeat_count")
        .and_then(Value::as_u64)
        .ok_or_else(|| {
            AdapterError::new("request", "query_batch requires repeat_count")
        })?;
    if repeat_count != 1 && repeat_count != 100 {
        return Err(AdapterError::new(
            "request",
            "repeat_count must be 1 or 100",
        ));
    }
    let iterations = usize::try_from(repeat_count)
        .map_err(|error| AdapterError::new("request", error.to_string()))?;

    // Parse every request field before timing starts; only the sequential real
    // searches are inside the measured interval.
    let mut last: Option<(Vec<String>, u64)> = None;
    let started = Instant::now();
    for _ in 0..iterations {
        let (doc_ids, total_hits, _engine_ns) = search(snapshot, field, term, k)?;
        if let Some((first_ids, first_total)) = &last {
            if *first_total != total_hits || *first_ids != doc_ids {
                return Err(AdapterError::new(
                    "batch_mismatch",
                    "batch iterations returned different results",
                ));
            }
        }
        last = Some((doc_ids, total_hits));
    }
    let outer_ns = positive(started.elapsed().as_nanos(), "batch_ns")?;
    let (doc_ids, total_hits) = match last {
        Some(result) => result,
        None => {
            return Err(AdapterError::new(
                "request",
                "query_batch requires a positive repeat_count",
            ));
        }
    };
    // Keep the final result observable so the loop cannot be optimised away.
    std::hint::black_box(&doc_ids);
    Ok(json!({
        "doc_ids": doc_ids,
        "total_hits": total_hits,
        "batch_ns": outer_ns,
        "repeat_count": repeat_count,
    }))
}
'''

ARM = '''            "query_batch" => {
                if session.is_none() {
                    let path = active_index_dir.as_deref().ok_or_else(|| {
                        AdapterError::new("request", "query mode requires --index-dir")
                    })?;
                    session = Some(QuerySession::open(path)?);
                }
                handle_query_batch(
                    session
                        .as_ref()
                        .expect("query session is always present here")
                        .snapshot
                        .as_ref(),
                    &request,
                )
            }
'''

PATCHED_QUERY_SESSION_FIELD = """
    /// Answer one diagnostic batched query against the session snapshot.
    ///
    /// Kept separate from [`Self::query`] so the frozen single-query path is
    /// byte-identical; the handler itself is a free function above.
    fn query_batch(&self, request: &Value) -> Result<Value, AdapterError> {
        handle_query_batch(self.snapshot.as_ref(), request)
    }
"""


class PatchError(Exception):
    """Raised when the frozen adapter source does not match the pinned identity."""


def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def load_protocol(root):
    with open(os.path.join(root, PROTOCOL_REL), "r", encoding="utf-8") as handle:
        protocol = json.load(handle)
    if protocol.get("schema") != "pr15i-c-batched-noise-v1":
        raise PatchError("bad batched protocol schema")
    if protocol.get("frozen_adapter_main_rs_sha256") != EXPECTED_MAIN_SHA:
        raise PatchError("protocol pins a different frozen adapter blob")
    if protocol.get("repeat_count_short") != 100 or protocol.get("repeat_count_control") != 1:
        raise PatchError("protocol repeat counts drifted")
    return protocol


def frozen_source(root):
    """Read the frozen adapter `main.rs` from the pinned Git object, not disk."""
    result = subprocess.run(
        ["git", "-C", root, "show", f"{BASELINE_SHA}:{FROZEN_ADAPTER_MAIN}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise PatchError(
            f"cannot read {FROZEN_ADAPTER_MAIN} at {BASELINE_SHA}: "
            f"{result.stderr.decode(errors='replace').strip()}")
    return result.stdout.decode("utf-8")


def frozen_blobs(root):
    """Return blob bytes for the adapter crate files from the pinned commit."""
    blobs = {}
    for relative in (f"{FROZEN_ADAPTER_DIR}/Cargo.toml",
                     f"{FROZEN_ADAPTER_DIR}/Cargo.lock",
                     FROZEN_ADAPTER_MAIN):
        result = subprocess.run(
            ["git", "-C", root, "show", f"{BASELINE_SHA}:{relative}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            raise PatchError(f"cannot read {relative} at {BASELINE_SHA}")
        blobs[os.path.basename(relative)] = result.stdout
    return blobs


def normalize(text):
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line.strip())


def function_sha(source, marker):
    """Normalized SHA-256 of the region starting at `marker` (brace balanced)."""
    index = source.find(marker)
    if index < 0:
        raise PatchError(f"marker not found: {marker!r}")
    cursor = source.index("{", index)
    depth = 0
    while cursor < len(source):
        character = source[cursor]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return sha256_bytes(normalize(source[index:cursor + 1]).encode())
        cursor += 1
    raise PatchError(f"unterminated region after {marker!r}")


def assert_single_anchor(source, anchor, label):
    count = source.count(anchor)
    if count != 1:
        raise PatchError(f"{label} anchor occurs {count} times, expected exactly 1")


def patch_source(source):
    """Apply the two deterministic hunks and return the derived source."""
    expected = sha256_bytes(source.encode("utf-8"))
    if expected != EXPECTED_MAIN_SHA:
        raise PatchError(
            f"frozen adapter source hash {expected} != pinned {EXPECTED_MAIN_SHA}")
    assert_single_anchor(source, BATCH_HANDLER_ANCHOR, "handler")
    assert_single_anchor(source, ARM_ANCHOR, "arm")
    before = {name: function_sha(source, marker)
              for name, marker in (
                  ("search", "fn search("),
                  ("handle_query", "fn handle_query("),
                  ("query", "    fn query(&self, request: &Value) -> Result<Value, AdapterError> {"),
              )}
    derived = source.replace(BATCH_HANDLER_ANCHOR, BATCH_HANDLER + BATCH_HANDLER_ANCHOR, 1)
    derived = derived.replace(ARM_ANCHOR, ARM + ARM_ANCHOR, 1)
    # Expose the batched call on the session too, so the diagnostic handler is
    # exercised through the same session object as `query`.
    session_anchor = ("    /// The session snapshot, exposed for deterministic "
                      "behavioural tests.\n    #[cfg(test)]\n    fn snapshot(&self)")
    if derived.count(session_anchor) != 1:
        raise PatchError("query session snapshot anchor is not unique")
    derived = derived.replace(session_anchor, PATCHED_QUERY_SESSION_FIELD.lstrip("\n")
                              + "\n" + session_anchor, 1)
    after = {name: function_sha(derived, marker)
             for name, marker in (
                 ("search", "fn search("),
                 ("handle_query", "fn handle_query("),
                 ("query", "    fn query(&self, request: &Value) -> Result<Value, AdapterError> {"),
             )}
    if before != after:
        raise PatchError("the patch changed a frozen adapter function")
    if derived.count("fn handle_query_batch(") != 1:
        raise PatchError("derived source does not define handle_query_batch exactly once")
    if derived.count('"query_batch" =>') != 1:
        raise PatchError("derived source does not route query_batch exactly once")
    batch_region = derived[derived.index("fn handle_query_batch("):]
    if '"engine_ns"' in batch_region[:batch_region.index("\n}\n")]:
        raise PatchError("batched handler must not emit engine_ns")
    return derived, before


def materialize(root, destination, core_path):
    """Write the derived adapter crate (patched) to `destination`."""
    source = frozen_source(root)
    derived, before = patch_source(source)
    blobs = frozen_blobs(root)
    os.makedirs(os.path.join(destination, "src"), exist_ok=True)
    manifest = blobs["Cargo.toml"].decode("utf-8")
    marker = 'quervant-core = { path = "../../../../crates/quervant-core" }'
    if marker not in manifest:
        raise PatchError("unexpected frozen adapter manifest; refusing to rewrite")
    manifest = manifest.replace(
        marker, f'quervant-core = {{ path = "{core_path}" }}', 1)
    manifest_path = os.path.join(destination, "Cargo.toml")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        handle.write(manifest)
    with open(os.path.join(destination, "Cargo.lock"), "wb") as handle:
        handle.write(blobs["Cargo.lock"])
    source_path = os.path.join(destination, "src", "main.rs")
    with open(source_path, "w", encoding="utf-8") as handle:
        handle.write(derived)
    return {
        "frozen_main_sha256": sha256_bytes(source.encode("utf-8")),
        "derived_main_sha256": sha256_bytes(derived.encode("utf-8")),
        "frozen_function_sha256": before,
        "derived_manifest_sha256": sha256_bytes(manifest.encode("utf-8")),
        "derived_source_path": source_path,
        "derived_manifest_path": manifest_path,
    }


def build(destination, target_dir):
    """Build the derived adapter release executable (offline, no network)."""
    result = subprocess.run(
        ["cargo", "build", "--release", "--offline", "--manifest-path",
         os.path.join(destination, "Cargo.toml"), "--target-dir", target_dir],
        cwd=destination, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, check=False)
    log_path = os.path.join(destination, "build.log")
    with open(log_path, "w", encoding="utf-8") as handle:
        handle.write(result.stdout)
    if result.returncode != 0:
        raise PatchError(f"derived adapter build failed: {result.stdout[-2000:]}")
    binary = os.path.join(target_dir, "release", "pr15d-quervant-adapter")
    if not os.path.isfile(binary):
        raise PatchError(f"derived adapter binary missing: {binary}")
    return binary


def prepare_derived_adapter(root, campaign_dir, arm, core_path):
    """Materialize + build the derived adapter for one arm; return identities."""
    destination = os.path.join(campaign_dir, "setup", "derived", arm)
    if os.path.exists(destination):
        shutil.rmtree(destination)
    record = materialize(root, destination, core_path)
    binary = build(destination, os.path.join(campaign_dir, "setup", "derived-build", arm))
    record["binary"] = binary
    record["binary_sha256"] = hashlib.sha256(open(binary, "rb").read()).hexdigest()
    record["arm"] = arm
    return record
