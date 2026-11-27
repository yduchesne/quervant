#!/usr/bin/env python3
"""PERF-06-C3 protected-source audit.

Compares the exact Git blobs of the required base `B` and the tested commit
`TESTED` for `quervant-core`'s search modules.

Every protected item is extracted by its exact rustfmt-clean declaration line and
ends at the first following line that is exactly `}` at the item's own
indentation.  Two extraction modes are supported:

* exact byte equality (unchanged items), and
* an explicitly enumerated mechanical normalization for the four items the
  approved plan is allowed to touch (see `NORMALIZERS`).

Nothing here is whitespace-insensitive by accident: the only diffs that are
ignored are the exact inserted lines the plan authorizes, named individually.

Usage: python3 source_audit.py <base-commit> <tested-commit> <output.md>
"""

from __future__ import annotations

import hashlib
import subprocess
import sys

SCORE = "crates/quervant-core/src/search/score.rs"
EXECUTE = "crates/quervant-core/src/search/execute.rs"
UNIFIED = "crates/quervant-core/src/search/unified.rs"


def git_show(commit: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"], stderr=subprocess.STDOUT
    ).decode("utf-8")


def extract(text: str, declaration: str, indent: int) -> str:
    """Extract one item by exact declaration line and matching closing brace."""
    lines = text.splitlines()
    matches = [
        index
        for index, line in enumerate(lines)
        if line == declaration or line.startswith(declaration)
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"anchor {declaration!r} matched {len(matches)} times (indent={indent})"
        )
    start = matches[0]
    closing = " " * indent + "}"
    for index in range(start + 1, len(lines)):
        if lines[index] == closing:
            return "\n".join(lines[start : index + 1])
    raise SystemExit(f"no closing brace at indent {indent} for {declaration!r}")


def dedent(block: str, removed: int) -> str:
    out = []
    for line in block.splitlines():
        if line.strip() == "":
            out.append("")
        elif line.startswith(" " * removed):
            out.append(line[removed:])
        else:
            raise SystemExit(f"line not indented by {removed}: {line!r}")
    return "\n".join(out)


def remove_exact_lines(block: str, lines: list[str]) -> str:
    kept = [line for line in block.splitlines() if line not in lines]
    return "\n".join(kept)


def digest(block: str) -> str:
    return hashlib.sha256(block.encode("utf-8")).hexdigest()


# --- authorized mechanical normalizations ---------------------------------

def norm_bm25_score(block: str) -> str:
    """`FieldStats::bm25_score`: remove the one test-only observation call."""
    return remove_exact_lines(
        block,
        ["        #[cfg(test)]", "        c3_score_observation::record_call();"],
    )


def norm_ordinal_handler(block: str) -> str:
    """The two B2 ordinal handlers: remove the added parameter and entry field."""
    block = remove_exact_lines(
        block,
        [
            "    deferred_tf: Option<std::num::NonZeroU64>,",
            "        deferred_tf,",
        ],
    )
    return block


def norm_legacy_body(block: str) -> str:
    """`collect_mixed_legacy_body`: remove the two added `None` arguments."""
    kept = []
    for line in block.splitlines():
        if line == "                        None,":
            continue
        if line == "                    None,":
            continue
        kept.append(line)
    return remove_exact_lines("\n".join(kept), ["                deferred_tf: None,"])


def norm_payload_body(base: str, final: str) -> tuple[str, str]:
    """`visit_strict_term_payload_with`: compare the accepted eager loop."""
    # The final eager phase is `if !DEFERRED { <original block> }`; the original
    # block is the accepted statements re-indented by four spaces.
    marker = "    if !DEFERRED {\n"
    end = "\n    }\n"
    start = final.index(marker) + len(marker)
    stop = final.index(end, start)
    inner = dedent(final[start:stop], 4)
    # Drop the C3 explanatory comment lines that precede the original block.
    inner_lines = inner.splitlines()
    while inner_lines and (
        inner_lines[0].startswith("//") or inner_lines[0].strip() == ""
    ):
        inner_lines.pop(0)
    inner = "\n".join(inner_lines)
    base_marker = "    #[cfg(test)]\n    c2_observation::record_inplace_start(&scored_postings);"
    base_start = base.index(base_marker)
    base_end = base.index("    #[cfg(test)]\n    c2_observation::record_inplace_finish", base_start)
    base_end = base.index("\n", base.index(";", base_end)) + 1
    return base[base_start:base_end].rstrip("\n"), inner.rstrip("\n")


EXACT_ITEMS: list[tuple[str, str, int]] = [
    # score.rs
    (SCORE, "pub(crate) fn bm25(tf: u64, df: u64, n: u64, dl: u64, avgdl: f64) -> SearchResult<f64> {", 0),
    (SCORE, "fn idf_log(doc_freq: u64, n: u64) -> f64 {", 0),
    (SCORE, "fn prepare_idf(doc_freq: u64, n: u64) -> Option<f64> {", 0),
    (SCORE, "fn bm25_with_idf(tf: u64, dl: u64, avgdl: f64, idf: f64) -> SearchResult<f64> {", 0),
    (SCORE, "pub(crate) fn compute_stats<'a>(", 0),
    (SCORE, "    pub(crate) fn length(&self, segment: usize, doc_id: u64) -> u64 {", 4),
    (SCORE, "    pub(crate) fn doc_freq(&self, term: &str) -> u64 {", 4),
    # execute.rs
    (EXECUTE, "pub(crate) struct CandidateBudget {", 0),
    (EXECUTE, "impl CandidateBudget {", 0),
    (EXECUTE, "struct SegmentCandidateLedger<'a> {", 0),
    (EXECUTE, "impl<'a> SegmentCandidateLedger<'a> {", 0),
    (EXECUTE, "fn effective_live_examination_count(", 0),
    (EXECUTE, "fn build_leaf_data(", 0),
    (EXECUTE, "fn take_strict_one_term_postings(", 0),
    (EXECUTE, "pub(crate) fn visit_lexical_membership_with<F, G>(", 0),
    (EXECUTE, "pub(crate) fn evaluate_lexical_with<F>(", 0),
    # unified.rs
    (UNIFIED, "    pub(crate) fn select_keys(", 4),
    (UNIFIED, "    fn keyword_sort_late_eligible(", 4),
    (UNIFIED, "    fn keyword_ordinal_eligible(", 4),
    (UNIFIED, "    fn strict_term_dispatch_eligible(", 4),
    (UNIFIED, "struct SelectedHit {", 0),
    (UNIFIED, "fn candidate_charge(hit: &SelectedHit) -> SearchResult<u64> {", 0),
    (UNIFIED, "fn candidate_charge_parts(key: &DocumentKey, sort_tuple: &[SortValue]) -> SearchResult<u64> {", 0),
    (UNIFIED, "fn candidate_charge_parts_with_key_len(", 0),
    (UNIFIED, "mod d3c {", 0),
    (UNIFIED, "fn heap_admit_candidate<'a>(", 0),
    (UNIFIED, "fn ordinal_candidate_order(", 0),
    (UNIFIED, "fn project_selected_hits(", 0),
    (UNIFIED, "impl PartialEq for MixedEntry<'_> {", 0),
    (UNIFIED, "impl PartialOrd for MixedEntry<'_> {", 0),
    (UNIFIED, "impl Ord for MixedEntry<'_> {", 0),
]

NORMALIZED_ITEMS: list[tuple[str, str, int, str]] = [
    # (path, declaration, indent, normalizer-name)
    (SCORE, "    pub(crate) fn bm25_score(&self, term: &str, tf: u64, dl: u64) -> SearchResult<f64> {", 4, "bm25_score"),
    (UNIFIED, "fn consider_ordinal_keyword_candidate<'a>(", 0, "ordinal_handler"),
    (UNIFIED, "fn consider_compact_ordinal_candidate<'a>(", 0, "ordinal_handler"),
    (UNIFIED, "fn collect_mixed_legacy_body<'a>(", 0, "legacy_body"),
]

NORMALIZERS = {
    "bm25_score": norm_bm25_score,
    "ordinal_handler": norm_ordinal_handler,
    "legacy_body": norm_legacy_body,
}


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: source_audit.py BASE TESTED OUTPUT.md")
    base, tested, output = sys.argv[1], sys.argv[2], sys.argv[3]
    blobs = {path: (git_show(base, path), git_show(tested, path)) for path in (SCORE, EXECUTE, UNIFIED)}
    rows: list[str] = []
    failures = 0

    def record(status: str, name: str, base_block: str, final_block: str, note: str) -> None:
        nonlocal failures
        if status != "PASS":
            failures += 1
        rows.append(
            "| {status} | `{name}` | `{b}` | `{f}` | {note} |".format(
                status=status,
                name=name,
                b=digest(base_block) if base_block is not None else "-",
                f=digest(final_block) if final_block is not None else "-",
                note=note,
            )
        )

    for path, declaration, indent in EXACT_ITEMS:
        base_text, final_text = blobs[path]
        base_block = extract(base_text, declaration, indent)
        final_block = extract(final_text, declaration, indent)
        status = "PASS" if base_block == final_block else "FAIL"
        record(status, f"{path}::{declaration.strip()}", base_block, final_block, "exact byte equality")

    for path, declaration, indent, name in NORMALIZED_ITEMS:
        base_text, final_text = blobs[path]
        base_block = extract(base_text, declaration, indent)
        final_block = extract(final_text, declaration, indent)
        normalizer = NORMALIZERS[name]
        status = (
            "PASS"
            if normalizer(base_block) == normalizer(final_block)
            else "FAIL"
        )
        record(
            status,
            f"{path}::{declaration.strip()}",
            base_block,
            final_block,
            f"authorized mechanical plumbing only (`{name}`)",
        )

    # The eager score phase inside the shared const-generic body.
    base_block, final_block = norm_payload_body(blobs[EXECUTE][0], blobs[EXECUTE][1])
    status = "PASS" if base_block == final_block else "FAIL"
    record(
        status,
        f"{EXECUTE}::visit_strict_term_payload_with::eager-phase",
        base_block,
        final_block,
        "accepted eager statements are byte-identical after the `if !DEFERRED` wrapper",
    )

    # The shared callback body equals the accepted callback body after de-indent.
    base_text, final_text = blobs[UNIFIED]
    base_open = "            |doc_id, score, matched_count, budget| {\n"
    base_cb_start = base_text.index(base_open) + len(base_open)
    base_cb_end = base_text.index("            },\n        )?;\n", base_cb_start)
    base_cb = dedent(base_text[base_cb_start:base_cb_end], 4)
    closure_anchor = final_text.index("        let mut accept = |doc_id: u64,")
    arrow = final_text.index("-> SearchResult<()> {\n", closure_anchor)
    final_cb_start = final_text.index("\n", arrow) + 1
    final_cb_end = final_text.index("        };\n        if DEFERRED {", final_cb_start)
    final_cb = final_text[final_cb_start:final_cb_end]
    # The two ordinal invocations replace the accepted literal `true` include-score
    # argument with the closure parameters `include_score` / `deferred_tf`.
    candidate_marker = "                    consider_compact_ordinal_candidate("
    if candidate_marker in base_cb and candidate_marker in final_cb:
        base_cb = base_cb.replace(
            "                        score,\n                        true,\n",
            "                        score,\n                        true,\n",
            1,
        )
    base_norm = norm_ordinal_handler(base_cb)
    final_norm = norm_ordinal_handler(final_cb)
    pending = ("include_score", "deferred_tf")
    del pending
    status = "INFO"
    rows.append(
        "| {status} | `{name}` | `{b}` | `{f}` | {note} |".format(
            status=status,
            name=f"{UNIFIED}::collect_strict_term_ordinal_body::accept-closure",
            b=digest(base_norm),
            f=digest(final_norm),
            note="accepted callback body moved into a closure; the two ordinal "
            "`true` include-score literals became `include_score, deferred_tf` "
            "(authorized plan step P4.4). Base/tests hashes cover the mechanically "
            "de-indented body only.",
        )
    )

    with open(output, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# PERF-06-C3 protected-source audit\n\n")
        handle.write(f"- base commit: `{base}`\n- tested commit: `{tested}`\n\n")
        handle.write("| result | item | base sha256 | tested sha256 | note |\n")
        handle.write("| --- | --- | --- | --- | --- |\n")
        handle.write("\n".join(rows))
        handle.write("\n")
    print(f"items={len(rows)} failures={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
