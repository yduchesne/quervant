#!/usr/bin/env python3
"""PR 15I-C fixup source-proof helpers.

Extracts a method body from Rust source by brace matching so the generic
`UnifiedSearcher::collect_mixed` body can be compared across commits without a
hand-maintained copy. Used by the diagnostic controller, the independent verifier
and their unit tests.
"""

from __future__ import annotations

import hashlib
import re
import subprocess


class SourceProofError(Exception):
    """Raised when a method cannot be located unambiguously."""


def _normalize(text):
    lines = [line.rstrip() for line in text.splitlines()]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return ""
    indent = min(len(line) - len(line.lstrip()) for line in lines)
    return "\n".join(line[indent:] for line in lines)


def extract_method(source, name):
    """Return the normalized body of `fn <name>(...)` with attributes excluded."""
    pattern = re.compile(rf"^\s*fn {re.escape(name)}\(", re.MULTILINE)
    matches = list(pattern.finditer(source))
    if len(matches) != 1:
        raise SourceProofError(
            f"expected exactly one definition of fn {name}, found {len(matches)}"
        )
    start = matches[0].start()
    line_start = source.rfind("\n", 0, start) + 1
    cursor = source.index("{", start)
    depth = 0
    while cursor < len(source):
        character = source[cursor]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                body = source[line_start:cursor + 1]
                return _normalize(body)
        cursor += 1
    raise SourceProofError(f"unterminated body for fn {name}")


def body_sha(source, name):
    return hashlib.sha256(extract_method(source, name).encode("utf-8")).hexdigest()


def read_at_revision(root, revision, path):
    result = subprocess.run(
        ["git", "-C", root, "show", f"{revision}:{path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise SourceProofError(
            f"cannot read {path} at {revision}: {result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout.decode("utf-8")


def attribute_block(source, name):
    """Return the attribute lines immediately preceding `fn <name>(`."""
    pattern = re.compile(rf"^\s*fn {re.escape(name)}\(", re.MULTILINE)
    match = pattern.search(source)
    if match is None:
        raise SourceProofError(f"fn {name} not found")
    line_start = source.rfind("\n", 0, match.start()) + 1
    preceding = source[:line_start].splitlines()
    attributes = []
    for line in reversed(preceding):
        stripped = line.strip()
        if stripped.startswith("#[") or stripped.startswith("//"):
            attributes.append(stripped)
            continue
        break
    return list(reversed(attributes))
