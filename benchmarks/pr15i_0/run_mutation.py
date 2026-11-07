#!/usr/bin/env python3
"""PR 15I-0 mutation-state sidecar attribution wrapper.

```sh
python3 benchmarks/pr15i_0/run_mutation.py \
  --prepared-run "$PREP" --pr15f-run "$F_RUN" \
  --source-sha "$SRC" --out "$ROOT/target/pr15i-0/mutation-01"
```

Responsibilities (deliberately narrow):

* establish **exactly one** active mutation-state object per corpus from the
  PR 15F read-only inventory (never from directory enumeration);
* hand the *prepared index root* to the benchmark-only Rust probe, which resolves
  `CURRENT -> Manifest -> MutationStateRef` through public `quervant-core` APIs;
* cross-check the probe's attributed object key, length and SHA-256 against the
  inventory entry;
* prove the index files are byte-identical before and after the probe;
* write an exclusive, immutable campaign manifest.

The wrapper never decodes the sidecar itself, never installs a network
dependency and never writes inside a prepared index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

SCHEMA_RUN = "pr15i-0-mutation-run-v1"
SCHEMA_BREAKDOWN = "pr15i-0-mutation-breakdown-v1"
PROTOCOL_REL = "benchmarks/pr15i_0/protocol.json"
PROBE_MANIFEST = os.path.join("benchmarks", "pr15i_0", "mutation_probe", "Cargo.toml")
PROBE_BINARY_REL = os.path.join(
    "benchmarks", "pr15i_0", "mutation_probe", "target", "debug", "mutation-probe"
)
N_VALUES = ("10000", "100000")


class MutationRunError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def canonical_json_bytes(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        + b"\n"
    )


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_exclusive(path: str, payload) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = canonical_json_bytes(payload)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return hashlib.sha256(data).hexdigest()


def require_dir(path: str, label: str) -> str:
    if not os.path.isabs(path):
        raise MutationRunError("X19_PATH", f"{label} must be absolute: {path}")
    real = os.path.realpath(path)
    if real != os.path.abspath(path):
        raise MutationRunError("X19_PATH", f"{label} is not canonical: {path}")
    if os.path.islink(path):
        raise MutationRunError("X19_PATH", f"{label} is a symlink: {path}")
    if not os.path.isdir(real):
        raise MutationRunError("X19_PATH", f"{label} is not a directory: {path}")
    return real


def index_inventory(directory: str) -> dict:
    """Hash every regular file below an index root (read-only)."""
    entries = {}
    for current, _directories, files in os.walk(directory):
        for name in sorted(files):
            path = os.path.join(current, name)
            if os.path.islink(path):
                raise MutationRunError("X19_PATH", f"symlink in index tree: {path}")
            relative = os.path.relpath(path, directory).replace(os.sep, "/")
            entries[relative] = {"bytes": os.path.getsize(path), "sha256": sha256_file(path)}
    return entries


def load_protocol(root: str) -> dict:
    path = os.path.join(root, PROTOCOL_REL)
    if not os.path.isfile(path):
        raise MutationRunError("X01_PROTOCOL", f"missing {PROTOCOL_REL}")
    protocol = read_json(path)
    probe = protocol.get("mutation_probe") or {}
    if probe.get("max_file_bytes") != 268435456:
        raise MutationRunError("X02_PROTOCOL", "probe byte cap was retuned")
    if probe.get("allowed_payload_versions") != [1, 2]:
        raise MutationRunError("X02_PROTOCOL", "probe payload versions were retuned")
    if probe.get("read_only") is not True:
        raise MutationRunError("X02_PROTOCOL", "probe is no longer read-only")
    return {"sha256": sha256_file(path), "value": protocol}


def build_probe(root: str) -> str:
    binary = os.path.join(root, PROBE_BINARY_REL)
    if not os.path.isfile(binary):
        result = subprocess.run(
            ["cargo", "build", "--locked", "--offline", "--manifest-path", PROBE_MANIFEST],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise MutationRunError(
                "X16_PROBE_BUILD",
                f"cannot build the probe offline: {result.stderr.strip()[-800:]}",
            )
    if not os.path.isfile(binary):
        raise MutationRunError("X16_PROBE_BUILD", "probe binary is missing after the build")
    return binary


def active_state_entry(inventory: dict, n: str) -> dict:
    state_entries = [
        entry
        for entry in inventory.get("files") or []
        if entry.get("path", "").startswith("index/state/")
    ]
    if len(state_entries) != 1:
        raise MutationRunError(
            "X19_STATE",
            f"inventory n{n} lists {len(state_entries)} mutation-state objects, expected exactly 1",
        )
    return state_entries[0]


def run(args) -> int:
    root = os.path.realpath(args.root)
    prepared = require_dir(args.prepared_run, "--prepared-run")
    pr15f_run = require_dir(args.pr15f_run, "--pr15f-run")
    out = os.path.abspath(args.out)
    if os.path.exists(out):
        raise MutationRunError("X20_OUTPUT", f"--out already exists: {out}")
    if args.max_bytes < 1 or args.max_bytes > 268435456:
        raise MutationRunError("X02_PROTOCOL", "--max-bytes is outside the frozen bound")
    if len(args.source_sha) != 40 or any(
        character not in "0123456789abcdef" for character in args.source_sha
    ):
        raise MutationRunError("X01_SOURCE", "--source-sha must be 40 lowercase hex")
    protocol = load_protocol(root)

    prepare_path = os.path.join(prepared, "prepare.json")
    if not os.path.isfile(prepare_path):
        raise MutationRunError("X24_PREPARE", "prepared run has no prepare.json")
    prepare = read_json(prepare_path)
    if (prepare.get("source") or {}).get("head_sha") != args.source_sha:
        raise MutationRunError(
            "X24_SOURCE", "the prepared run was not built from --source-sha"
        )

    binary = os.path.abspath(args.probe or build_probe(root))
    if not os.path.isfile(binary):
        raise MutationRunError("X16_PROBE_BUILD", f"probe binary is missing: {binary}")
    binary_sha = sha256_file(binary)

    os.makedirs(out, exist_ok=False)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    observations = {}
    for n in N_VALUES:
        entry = (prepare.get("indexes") or {}).get(n) or {}
        relative = entry.get("path")
        if not isinstance(relative, str):
            raise MutationRunError("X24_PREPARE", f"prepared run has no index path for n{n}")
        index_root = require_dir(os.path.join(prepared, relative), f"index n{n}")

        inventory_path = os.path.join(pr15f_run, "inventory", f"n{n}.json")
        if not os.path.isfile(inventory_path):
            raise MutationRunError("X23_INVENTORY", f"missing PR 15F inventory n{n}")
        inventory = read_json(inventory_path)
        if inventory.get("schema") != "pr15f-index-inventory-v1":
            raise MutationRunError("X23_INVENTORY", f"inventory n{n} schema drift")
        if inventory.get("read_only") is not True:
            raise MutationRunError("X23_INVENTORY", f"inventory n{n} is not read-only")
        if inventory.get("n") != int(n):
            raise MutationRunError("X23_INVENTORY", f"inventory n{n} document count drift")
        state_entry = active_state_entry(inventory, n)

        prepared_inventory = entry.get("inventory") or {}
        if prepared_inventory.get("sha256") != inventory.get("content_sha256"):
            raise MutationRunError(
                "X23_INVENTORY", f"inventory n{n} does not describe the prepared index"
            )

        before = index_inventory(index_root)
        probe_out = os.path.join(out, f"n{n}.json")
        command = [
            binary,
            "--index-root",
            index_root,
            "--max-bytes",
            str(args.max_bytes),
            "--source-sha",
            args.source_sha,
            "--out",
            probe_out,
        ]
        result = subprocess.run(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise MutationRunError(
                "X22_PROBE",
                f"probe failed for n{n} ({result.returncode}): {result.stderr.strip()[-800:]}",
            )
        after = index_inventory(index_root)
        if before != after:
            raise MutationRunError(
                "X23_MUTATION", f"the prepared index n{n} changed while being probed"
            )

        breakdown = read_json(probe_out)
        if breakdown.get("schema") != SCHEMA_BREAKDOWN:
            raise MutationRunError("X22_PROBE", f"probe n{n} schema drift")
        if breakdown.get("source_sha") != args.source_sha:
            raise MutationRunError("X22_PROBE", f"probe n{n} source drift")
        if breakdown.get("active_state_key") != state_entry.get("path"):
            raise MutationRunError(
                "X23_ACTIVE_STATE",
                f"probe n{n} attributed a different mutation-state object than the inventory",
            )
        if breakdown.get("sidecar_sha256") != state_entry.get("sha256"):
            raise MutationRunError("X23_ACTIVE_STATE", f"probe n{n} sidecar digest mismatch")
        if breakdown.get("sidecar_file_bytes") != state_entry.get("bytes"):
            raise MutationRunError("X23_ACTIVE_STATE", f"probe n{n} sidecar length mismatch")
        if breakdown.get("sidecar_file_bytes") != inventory.get("mutation_state_file_bytes"):
            raise MutationRunError(
                "X23_ACTIVE_STATE",
                f"probe n{n} sidecar is not the inventory's mutation-state total",
            )
        components = breakdown.get("component_bytes") or {}
        if sum(components.values()) != breakdown.get("payload_bytes"):
            raise MutationRunError("X22_PROBE", f"probe n{n} components do not reconcile")
        if (
            breakdown.get("payload_bytes") + breakdown.get("container_overhead_bytes")
            != breakdown.get("sidecar_file_bytes")
        ):
            raise MutationRunError("X22_PROBE", f"probe n{n} payload/overhead does not reconcile")

        observations[n] = {
            "index_rel": os.path.relpath(index_root, root).replace(os.sep, "/"),
            "inventory": {
                "path": os.path.relpath(inventory_path, root).replace(os.sep, "/"),
                "sha256": sha256_file(inventory_path),
                "content_sha256": inventory.get("content_sha256"),
            },
            "active_state_entry": state_entry,
            "probe_output": {
                "path": os.path.relpath(probe_out, root).replace(os.sep, "/"),
                "sha256": sha256_file(probe_out),
            },
            "index_files_unchanged": True,
            "index_file_count": len(before),
        }

    manifest = {
        "schema": SCHEMA_RUN,
        "source_sha": args.source_sha,
        "read_only": True,
        "protocol": {"path": PROTOCOL_REL, "sha256": protocol["sha256"]},
        "prepared_run": os.path.relpath(prepared, root).replace(os.sep, "/"),
        "pr15f_run": os.path.relpath(pr15f_run, root).replace(os.sep, "/"),
        "probe": {
            "path": os.path.relpath(binary, root).replace(os.sep, "/"),
            "sha256": binary_sha,
            "max_bytes": args.max_bytes,
        },
        "started_utc": started,
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n": observations,
    }
    manifest_sha = write_json_exclusive(os.path.join(out, "manifest.json"), manifest)
    print(
        json.dumps(
            {
                "status": "CAPTURED",
                "out": os.path.relpath(out, root).replace(os.sep, "/"),
                "manifest_sha256": manifest_sha,
                "probe_sha256": binary_sha,
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_mutation.py",
        description="PR 15I-0 read-only mutation-state sidecar attribution.",
        allow_abbrev=False,
    )
    parser.add_argument("--root", default=None)
    parser.add_argument("--prepared-run", required=True)
    parser.add_argument("--pr15f-run", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--probe", default=None)
    parser.add_argument("--max-bytes", type=int, default=268435456)
    args = parser.parse_args(argv)
    if args.root is None:
        args.root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
    try:
        return run(args)
    except MutationRunError as error:
        print(
            json.dumps(
                {"status": "FAILED", "code": error.code, "detail": error.detail},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
