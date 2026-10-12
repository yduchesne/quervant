# PR 4 analysis datasets — provenance and licensing

This directory contains pinned data used by `trawler-core` analysis. The data is embedded
at compile time via `include_str!`; **no dataset is fetched at runtime**.

## `public_suffix_list.dat`

- **Source:** <https://publicsuffix.org/list/public_suffix_list.dat>
- **Retrieval date:** 2026-10-12
- **List VERSION (from header):** `2026-10-07_07-28-19_UTC`
- **List COMMIT (from header):** `3929462652695bad04f0a27afb600974014a3c8b`
- **SHA-256 (recorded at retrieval):** `ba7d836c0ea57a8bcf9f1fcb868066a7554bed029b441ecc6204ad8494a32612`
- **License:** Mozilla Public License 2.0 (the file header carries the MPL-2.0 notice).
  See `LICENSES/MPL-2.0.txt`. The file is included **unmodified** with its notice intact.
- **Consumer:** `publicsuffix =2.3.0` (D-GATE-2). Both ICANN and private sections are present;
  the private-suffix policy is configurable and is part of the analyzer fingerprint (T06).

The recorded SHA-256 is re-verified by a unit test (`analysis::domain_data` tests) so that
accidental edits to the pinned snapshot fail the build.

## `english_stopwords.txt`

- **Source:** <https://snowballstem.org/algorithms/english/stop.txt>
- **Retrieval date:** 2026-10-12
- **SHA-256 (recorded at retrieval):** `06b8b14bbe6f6e0b64c0830813819416d96a71bec1655668d83b3e602a651db6`
- **License:** 3-clause BSD (Snowball). See `LICENSES/BSD-3-Clause-Snowball.txt`.
- **Consumer:** opt-in English `Stopwords` token filter (T03b). Comments/blank lines are
  ignored; the parser sorts terms deterministically so filter behavior is independent of file
  ordering.
