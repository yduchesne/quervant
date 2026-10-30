#!/usr/bin/env python3
"""Deterministic PR15D v1 neutral corpus generator.

Standard library only. Writes the same bytes on every invocation and prints a
canonical summary containing the SHA-256 of every TSV file and of the manifest
JSON bytes. No adapter or engine code is imported.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import oracle  # noqa: E402  (local, engine-neutral module)


def _write_atomic(path: str, payload: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def generate(out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    for n in oracle.N_VALUES:
        text = oracle.build_tsv_text(n)
        _write_atomic(
            os.path.join(out_dir, oracle.corpus_filename(n)),
            text.encode("utf-8"),
        )
    manifest = oracle.build_manifest(out_dir)
    manifest_bytes = oracle.canonical_json_bytes(manifest)
    _write_atomic(os.path.join(out_dir, oracle.manifest_filename()), manifest_bytes)

    # Re-derive everything from the bytes just written. This is the same gate a
    # reader uses, so a generator regression cannot silently publish a manifest
    # that disagrees with the corpus.
    manifest, _rows = oracle.load_and_verify(out_dir)
    corpora = {
        str(entry["n"]): {
            "path": entry["path"],
            "bytes": entry["bytes"],
            "rows": entry["rows"],
            "sha256": entry["sha256"],
        }
        for entry in manifest["corpora"]
    }
    return {
        "workload": oracle.WORKLOAD,
        "corpora": corpora,
        "manifest": {
            "path": oracle.manifest_filename(),
            "sha256": oracle.sha256_bytes(oracle.canonical_json_bytes(manifest)),
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate the PR15D v1 corpus.")
    parser.add_argument("--out", required=True, help="output directory for TSV + manifest")
    args = parser.parse_args(argv)
    try:
        summary = generate(args.out)
    except oracle.CorpusError as error:
        print(f"CORPUS GENERATION FAILED: {error.code}: {error.detail}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
