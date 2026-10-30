#!/usr/bin/env python3
"""Bounded, non-timed three-adapter exact-hit smoke for PR15D A1.

This script proves that each adapter can build an on-disk index and answer the
frozen exact-term oracle correctly. It never measures latency, never writes a
performance result, never uses `--idle-confirmed`, and never reports QPS.

CLI (fixed by the A1 plan):

    python3 benchmarks/pr15d/harness/smoke.py \
      --corpus target/pr15d/a1-ci-corpus \
      --quervant-bin <path> \
      --tantivy-bin <path> \
      --lucene-command '<verified installed distribution command>'

`--lucene-command` is split with `shlex.split` only; no shell is ever invoked.

PR15D-B adds one optional, bounded selector:

    --sizes 10000,100000

It is a strict subset of the frozen corpus sizes (`SIZES`), it never changes the
default (10000 only), it never invents a new corpus, and it does not enter any
timed region. Each selected size is checked by the same exact-hit oracle code
path and emits one JSON summary line, so the default invocation still prints
exactly one line.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "corpus"))

import oracle  # noqa: E402

SCHEMA_ADAPTER = "pr15d-adapter-v1"
N = 10000
SIZES = (10000, 100000)
K_VALUES = (10, 100)
SHELL_METACHARACTERS = set(";|&$`><\n\r")
FORBIDDEN_TOKEN_CHARACTERS = set(";|&$`><\n\r\t")
DEFAULT_TIMEOUT = 300


class SmokeError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _parse_command(text: str, label: str) -> list[str]:
    if any(character in SHELL_METACHARACTERS for character in text):
        raise SmokeError(
            "command_metacharacter",
            f"{label}: shell metacharacters are not allowed: {text!r}",
        )
    try:
        argv = shlex.split(text)
    except ValueError as error:
        raise SmokeError("command_parse", f"{label}: {error}") from error
    if not argv:
        raise SmokeError("command_empty", label)
    for token in argv:
        if any(character in FORBIDDEN_TOKEN_CHARACTERS for character in token):
            raise SmokeError(
                "command_metacharacter",
                f"{label}: forbidden character in {token!r}",
            )
    if not os.path.isabs(argv[0]):
        raise SmokeError(
            "command_not_absolute",
            f"{label}: executable must be an absolute path: {argv[0]!r}",
        )
    if not (os.path.isfile(argv[0]) and os.access(argv[0], os.X_OK)):
        raise SmokeError(
            "command_missing",
            f"{label}: executable is missing or not executable: {argv[0]!r}",
        )
    return argv


def parse_sizes(text) -> list[int]:
    """Resolve the requested corpus sizes, defaulting to the frozen 10K smoke.

    Only frozen corpus sizes are selectable and each may appear at most once, so
    the full-correctness selector can never invent corpus semantics.
    """
    if text is None:
        return [N]
    if not isinstance(text, str):
        raise SmokeError("sizes_invalid", f"--sizes must be text: {text!r}")
    selected: list[int] = []
    for token in text.split(","):
        item = token.strip()
        if not item:
            raise SmokeError(
                "sizes_empty",
                f"--sizes must list at least one frozen size; got {text!r}",
            )
        if not (item.isascii() and item.isdigit()):
            raise SmokeError(
                "sizes_malformed",
                f"--sizes entry is not a decimal integer: {item!r}",
            )
        size = int(item)
        if size not in SIZES:
            raise SmokeError(
                "sizes_unknown",
                f"--sizes entry {size} is not a frozen corpus size: {list(SIZES)}",
            )
        if size in selected:
            raise SmokeError("sizes_duplicate", f"--sizes repeats the size {size}")
        selected.append(size)
    return selected


def _requests(corpus_path: str, index_dir: str) -> list[dict]:
    requests = [
        {
            "request_id": "build",
            "op": "build",
            "corpus_path": corpus_path,
            "index_dir": index_dir,
        }
    ]
    for class_name, field, term in oracle.CLASSES:
        for k in K_VALUES:
            requests.append(
                {
                    "request_id": f"{class_name}-{k}",
                    "op": "query",
                    "field": field,
                    "term": term,
                    "k": k,
                    "mode": "warm",
                }
            )
    requests.append({"request_id": "shutdown", "op": "shutdown"})
    return requests


def _run_engine(
    engine: str, argv: list[str], corpus_path: str, rows, timeout: int, n: int = N
) -> dict:
    index_dir = tempfile.mkdtemp(prefix=f"pr15d-smoke-{engine}-")
    try:
        requests = _requests(corpus_path, index_dir)
        payload = "".join(
            json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n"
            for request in requests
        )
        try:
            completed = subprocess.run(
                argv,
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SmokeError("adapter_process", f"{engine}: {error}") from error
        if completed.returncode != 0:
            raise SmokeError(
                "adapter_exit",
                f"{engine}: exit {completed.returncode}: {completed.stderr.strip()[:1000]}",
            )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) != len(requests):
            raise SmokeError(
                "adapter_reply_count",
                f"{engine}: expected {len(requests)} replies, got {len(lines)}",
            )
        responses = []
        for line in lines:
            try:
                responses.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise SmokeError(
                    "adapter_json", f"{engine}: {error}"
                ) from error
        for response, request in zip(responses, requests):
            if response.get("schema") != SCHEMA_ADAPTER:
                raise SmokeError("adapter_schema", f"{engine}: {response.get('schema')!r}")
            if response.get("engine") != engine:
                raise SmokeError("adapter_engine", f"{engine}: {response.get('engine')!r}")
            if response.get("request_id") != request["request_id"]:
                raise SmokeError(
                    "adapter_request_id",
                    f"{engine}: {response.get('request_id')!r}",
                )
            if response.get("status") != "ok":
                raise SmokeError(
                    "adapter_status",
                    f"{engine}: {json.dumps(response.get('error'), sort_keys=True)}",
                )

        build = responses[0]
        if build.get("documents_indexed") != n or build.get("documents_verified") != n:
            raise SmokeError(
                "adapter_document_count",
                f"{engine}: indexed={build.get('documents_indexed')} "
                f"verified={build.get('documents_verified')}",
            )
        for field in ("index_ns", "commit_ns", "reopen_ns", "index_bytes"):
            value = build.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise SmokeError(
                    "adapter_duration", f"{engine}: {field}={value!r}"
                )
        if not isinstance(build.get("segment_count"), int) or build["segment_count"] <= 0:
            raise SmokeError(
                "adapter_segments", f"{engine}: {build.get('segment_count')!r}"
            )

        by_id = {response["request_id"]: response for response in responses[1:-1]}
        checked = 0
        for class_name, field, term in oracle.CLASSES:
            for k in K_VALUES:
                expected = oracle.expected(rows, field, term, k)
                response = by_id[f"{class_name}-{k}"]
                if response.get("total_hits") != expected["total_hits"]:
                    raise SmokeError(
                        "oracle_count",
                        f"{engine} {class_name} k={k}: "
                        f"{response.get('total_hits')} != {expected['total_hits']}",
                    )
                if response.get("doc_ids") != expected["doc_ids"]:
                    raise SmokeError(
                        "oracle_ids",
                        f"{engine} {class_name} k={k}: doc_id tuple differs",
                    )
                for key in ("engine_ns",):
                    value = response.get(key)
                    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                        raise SmokeError(
                            "adapter_duration", f"{engine} {class_name} k={k}: {key}"
                        )
                checked += 1
        return {
            "engine": engine,
            "documents": n,
            "queries_checked": checked,
            "index_bytes": build["index_bytes"],
            "segment_count": build["segment_count"],
        }
    finally:
        shutil.rmtree(index_dir, ignore_errors=True)


def run(args) -> int:
    manifest, rows_by_n = oracle.load_and_verify(args.corpus)
    manifest_sha = oracle.sha256_bytes(oracle.canonical_json_bytes(manifest))
    sizes = parse_sizes(args.sizes)

    engines = [
        ("quervant", _parse_command(args.quervant_bin, "quervant")),
        ("tantivy", _parse_command(args.tantivy_bin, "tantivy")),
        ("lucene", _parse_command(args.lucene_command, "lucene")),
    ]
    for n in sizes:
        rows = rows_by_n[n]
        corpus_path = os.path.join(args.corpus, oracle.corpus_filename(n))
        summary = {
            "schema": "pr15d-a1-smoke-v1",
            "corpus_manifest_sha256": manifest_sha,
            "n": n,
            "engines": [],
            "timings_reported": False,
        }
        for engine, argv in engines:
            summary["engines"].append(
                _run_engine(engine, argv, corpus_path, rows, args.timeout, n=n)
            )
        print(
            json.dumps(summary, sort_keys=True, separators=(",", ":"))
        )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PR15D A1 bounded exact-hit smoke.")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--quervant-bin", required=True)
    parser.add_argument("--tantivy-bin", required=True)
    parser.add_argument("--lucene-command", required=True)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--sizes",
        default=None,
        help=(
            "optional comma-separated subset of the frozen corpus sizes "
            f"{list(SIZES)}; default {N} only"
        ),
    )
    args = parser.parse_args(argv)
    try:
        return run(args)
    except oracle.CorpusError as error:
        print(f"CORPUS INVALID: {error.code}: {error.detail}", file=sys.stderr)
        return 2
    except SmokeError as error:
        print(f"SMOKE FAILED: {error.code}: {error.detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
