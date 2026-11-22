#!/usr/bin/env python3
"""Untimed real-adapter sorting oracle: string d10 must sort before d2.

This deliberately uses non-fixed-width document keys that make numeric
surrogate ordering disagree with keyword lexicographic ordering. It is a
bounded correctness test, not benchmark acquisition or performance evidence.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke import _parse_command, SmokeError

HEADER = "doc_id\tkey\tgroup\tbody\tpayload\n"
IDS = ("d1", "d10", "d2", "d20")
QUERIES = ((2, ["d1", "d10"]), (3, ["d1", "d10", "d2"]),
           (4, ["d1", "d10", "d2", "d20"]))


def check(engine: str, command: list[str], corpus: Path, index: Path, timeout: int) -> None:
    requests = [
        {"request_id": "build", "op": "build",
         "corpus_path": str(corpus), "index_dir": str(index)},
    ]
    for k, _expected in QUERIES:
        requests.append({"request_id": f"k{k}", "op": "query",
                         "field": "group", "term": "medium",
                         "k": k, "mode": "warm"})
    requests.append({"request_id": "shutdown", "op": "shutdown"})
    payload = "".join(json.dumps(r, sort_keys=True) + "\n" for r in requests)
    try:
        done = subprocess.run(command, input=payload, text=True, capture_output=True,
                              check=False, timeout=timeout, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SmokeError("process", f"{engine}: {exc}") from exc
    if done.returncode:
        raise SmokeError("adapter_exit", f"{engine}: {done.stderr[-800:]}")
    try:
        replies = [json.loads(row) for row in done.stdout.splitlines() if row.strip()]
    except (TypeError, ValueError) as exc:
        raise SmokeError("json", f"{engine}: {exc}") from exc
    if len(replies) != len(requests):
        raise SmokeError("reply_count", f"{engine}: {len(replies)} replies")
    for request, reply in zip(requests, replies):
        if (not isinstance(reply, dict) or reply.get("request_id") != request["request_id"]
                or reply.get("schema") != "pr15d-adapter-v1"
                or reply.get("engine") != engine or reply.get("status") != "ok"):
            raise SmokeError("protocol", f"{engine}: {reply}")
    if replies[0].get("documents_indexed") != 4 or replies[0].get("documents_verified") != 4:
        raise SmokeError("index", f"{engine}: document count mismatch")
    for (k, expected), reply in zip(QUERIES, replies[1:-1]):
        if reply.get("total_hits") != 4 or reply.get("doc_ids") != expected:
            raise SmokeError("string_sort", f"{engine}: k={k} got {reply.get('doc_ids')!r}")
        value = reply.get("engine_ns")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise SmokeError("contract", f"{engine}: missing positive query duration")
    if not isinstance(replies[1].get("index_open_ns"), int):
        raise SmokeError("reader_open", f"{engine}: initial reader opening was not reported")
    for reply in replies[2:-1]:
        if "index_open_ns" in reply:
            raise SmokeError("reader_reuse", f"{engine}: reopened reader between warm queries")


def main() -> int:
    parser = argparse.ArgumentParser(description="Non-fixed-width doc_id string sort oracle")
    parser.add_argument("--quervant-bin", required=True)
    parser.add_argument("--tantivy-bin", required=True)
    parser.add_argument("--lucene-command", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    try:
        if args.timeout <= 0:
            raise SmokeError("timeout", "timeout must be positive")
        commands = {
            "quervant": _parse_command(args.quervant_bin, "quervant"),
            "tantivy": _parse_command(args.tantivy_bin, "tantivy"),
            "lucene": _parse_command(args.lucene_command, "lucene"),
        }
        with tempfile.TemporaryDirectory(prefix="pr15d-lexical-") as temp:
            root = Path(temp)
            corpus = root / "corpus.tsv"
            corpus.write_text(HEADER + "".join(
                f"{doc_id}\tcommon\tmedium\tbody\tpayload\n" for doc_id in IDS
            ), encoding="utf-8")
            for engine, command in commands.items():
                check(engine, command, corpus, root / f"{engine}-index", args.timeout)
        print(json.dumps({"engines": list(commands), "tested_ids": list(IDS),
                          "top_k": [k for k, _ in QUERIES],
                          "oracle": "native string doc_id ascending",
                          "timings_reported": False}, sort_keys=True))
        return 0
    except SmokeError as exc:
        print(f"LEXICAL SMOKE FAILED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
