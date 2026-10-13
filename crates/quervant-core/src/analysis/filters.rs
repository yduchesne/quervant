//! Token filters (T03, T03a, T03b).
//!
//! Filters only change the term text. Source offsets are carried by the token and are never
//! recomputed from a transformed string (T04).

use std::collections::BTreeSet;
use std::sync::OnceLock;

use icu_casemap::CaseMapper;
use rust_stemmers::{Algorithm as SnowballAlgorithm, Stemmer};
use unicode_normalization::UnicodeNormalization;
use unicode_normalization::char::is_combining_mark;

use super::config::{NormalizationForm, StemmerAlgorithm, StopwordDataset};

/// Embedded pinned Snowball English stopword list.
const ENGLISH_STOPWORDS: &str = include_str!("data/english_stopwords.txt");

/// Applies the selected normalization form.
pub(crate) fn normalize(form: NormalizationForm, input: &str) -> String {
    match form {
        NormalizationForm::None => input.to_owned(),
        NormalizationForm::Nfc => input.nfc().collect(),
        NormalizationForm::Nfd => input.nfd().collect(),
        NormalizationForm::Nfkc => input.nfkc().collect(),
        NormalizationForm::Nfkd => input.nfkd().collect(),
    }
}

/// Applies full Unicode case folding (never simple lowercasing).
pub(crate) fn case_fold(input: &str) -> String {
    CaseMapper::new().fold_string(input).into_owned()
}

/// Lossy ASCII reduction: NFKD decomposition, drop combining marks and non-ASCII scalars.
///
/// This is deliberately conservative and does not implement transliteration.
pub(crate) fn ascii_fold(input: &str) -> String {
    input
        .nfkd()
        .filter(|ch| !is_combining_mark(*ch))
        .filter(char::is_ascii)
        .collect()
}

/// Returns whether `term` is in the selected stopword dataset.
pub(crate) fn is_stopword(dataset: StopwordDataset, term: &str) -> bool {
    match dataset {
        StopwordDataset::EnglishSnowball => english_stopwords().contains(term),
    }
}

fn english_stopwords() -> &'static BTreeSet<&'static str> {
    static STOPWORDS: OnceLock<BTreeSet<&'static str>> = OnceLock::new();
    STOPWORDS.get_or_init(|| parse_stopwords(ENGLISH_STOPWORDS))
}

/// Parses a Snowball stop list: text before `|` is the word; comments/blank lines ignored.
fn parse_stopwords(raw: &str) -> BTreeSet<&str> {
    raw.lines()
        .filter_map(|line| {
            let head = line.split('|').next().unwrap_or("");
            head.split_whitespace().next()
        })
        .collect()
}

/// Creates a Snowball stemmer for the selected algorithm.
pub(crate) fn stemmer(algorithm: StemmerAlgorithm) -> Stemmer {
    match algorithm {
        StemmerAlgorithm::English => Stemmer::create(SnowballAlgorithm::English),
    }
}

/// Stems `term` with a pre-built stemmer.
pub(crate) fn stem(stemmer: &Stemmer, term: &str) -> String {
    stemmer.stem(term).into_owned()
}

/// The recorded SHA-256 of the embedded stopword file, re-verified at test time.
pub(crate) const STOPWORDS_SHA256: &str =
    "06b8b14bbe6f6e0b64c0830813819416d96a71bec1655668d83b3e602a651db6";
/// The recorded SHA-256 of the embedded Public Suffix List, re-verified at test time.
pub(crate) const PSL_SHA256: &str =
    "ba7d836c0ea57a8bcf9f1fcb868066a7554bed029b441ecc6204ad8494a32612";

#[cfg(test)]
pub(crate) fn english_stopword_count() -> usize {
    english_stopwords().len()
}

#[cfg(test)]
pub(crate) fn raw_stopwords() -> &'static str {
    ENGLISH_STOPWORDS
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nfc_composes_combining_sequences() {
        let decomposed = "e\u{0301}";
        assert_eq!(normalize(NormalizationForm::Nfc, decomposed), "é");
        assert_eq!(normalize(NormalizationForm::Nfd, "é"), "e\u{0301}");
    }

    #[test]
    fn none_is_identity() {
        assert_eq!(normalize(NormalizationForm::None, "Straße"), "Straße");
    }

    #[test]
    fn case_fold_expands_sharp_s() {
        // Full folding maps ß -> ss (unlike simple lowercasing).
        assert_eq!(case_fold("Straße"), "strasse");
        assert_eq!(case_fold("İstanbul"), "i̇stanbul");
    }

    #[test]
    fn ascii_fold_removes_accents() {
        assert_eq!(ascii_fold("café"), "cafe");
        assert_eq!(ascii_fold("naïve"), "naive");
    }

    #[test]
    fn stopword_parsing_matches_expected_members() {
        let stopwords = english_stopwords();
        assert!(stopwords.contains("the"));
        assert!(stopwords.contains("themselves"));
        // `us` is commented out in the Snowball list by design.
        assert!(!stopwords.contains("us"));
        assert!(english_stopword_count() > 100);
    }

    #[test]
    fn stopword_lookup_is_deterministic_and_sorted() {
        let stopwords = english_stopwords();
        let collected: Vec<_> = stopwords.iter().copied().collect();
        let mut sorted = collected.clone();
        sorted.sort_unstable();
        assert_eq!(collected, sorted);
    }

    #[test]
    fn english_stemmer_reduces_common_forms() {
        let stemmer = stemmer(StemmerAlgorithm::English);
        assert_eq!(stem(&stemmer, "running"), "run");
        assert_eq!(stem(&stemmer, "nationalization"), "nation");
    }
}
