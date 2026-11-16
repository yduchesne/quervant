#!/usr/bin/env python3
"""Independent reference reproducer for the BM-04 bootstrap index golden.

This script is deliberately written from the prose algorithm in
``docs/pr-artifacts/bm-04/mathematical-oracles.md`` and **must not import
``quervant_bench``**. It exists so a reviewer can verify the checked-in golden
without trusting the production implementation.

It prints ``{"domain_key": <hex>, "indexes": [<first 16 accepted block indexes>]}``.
"""

from __future__ import annotations

import hashlib
import json

PREFIX = b"quervant-bench/paired-bootstrap/v1\x00"
BLOCK_COUNT = 3
ACCEPTED = 16
BINDING = {
    "baseline_id": "baseline",
    "campaign_index": 0,
    "candidate_id": "candidate",
    "estimator_id": "median-paired-ratios-v1",
    "lane_id": "rare-query",
    "protocol_digest": "sha256:" + "0" * 64,
    "seed": 42,
}


def canonical_payload_bytes(document):
    """Sorted keys, no whitespace, UTF-8, no trailing newline."""

    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def main():
    key = hashlib.sha256(PREFIX + canonical_payload_bytes(BINDING)).digest()
    limit = (2**64 // BLOCK_COUNT) * BLOCK_COUNT
    counter = 0
    indexes = []
    while len(indexes) < ACCEPTED:
        digest = hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
        counter += 1
        value = int.from_bytes(digest[:8], "big")
        if value >= limit:
            continue
        indexes.append(value % BLOCK_COUNT)
    print(json.dumps({"domain_key": key.hex(), "indexes": indexes}, sort_keys=True))


if __name__ == "__main__":
    main()
