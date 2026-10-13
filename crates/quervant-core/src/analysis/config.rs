//! Approved analyzer configuration vocabulary (T03, T06, T08).

use super::error::AnalysisError;

/// Tokenizer selection (T03).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenizerKind {
    /// One token covering the whole (non-empty) input value.
    Keyword,
    /// Split on Unicode whitespace (`char::is_whitespace`).
    Whitespace,
    /// UAX #29 word segmentation via `unicode-segmentation`.
    UnicodeWord,
}

impl TokenizerKind {
    /// Stable identifier used in canonical fingerprints.
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::Keyword => "keyword",
            Self::Whitespace => "whitespace",
            Self::UnicodeWord => "unicode-word",
        }
    }
}

/// Unicode normalization form applied by the `Normalize` token filter (T03a).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum NormalizationForm {
    /// Explicit no-op normalization.
    None,
    /// Canonical composition (the approved default).
    #[default]
    Nfc,
    /// Canonical decomposition.
    Nfd,
    /// Compatibility composition.
    Nfkc,
    /// Compatibility decomposition.
    Nfkd,
}

impl NormalizationForm {
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Nfc => "nfc",
            Self::Nfd => "nfd",
            Self::Nfkc => "nfkc",
            Self::Nfkd => "nfkd",
        }
    }
}

/// Opt-in stemming algorithm (T03b).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StemmerAlgorithm {
    /// Snowball English, provided by `rust-stemmers` 1.2.0.
    English,
}

impl StemmerAlgorithm {
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::English => "snowball-english",
        }
    }
}

/// Opt-in stopword dataset (T03b).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StopwordDataset {
    /// Pinned Snowball English stopword list committed with this crate.
    EnglishSnowball,
}

impl StopwordDataset {
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::EnglishSnowball => "snowball-english-stopwords",
        }
    }

    #[must_use]
    pub const fn version(self) -> &'static str {
        match self {
            Self::EnglishSnowball => super::domain_data::STOPWORDS_DATASET_VERSION,
        }
    }
}

/// One ordered token filter (T03).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenFilter {
    /// Apply a Unicode normalization form to the term, preserving source offsets.
    Normalize(NormalizationForm),
    /// Full Unicode case folding (opt-in, never simple lowercasing).
    CaseFold,
    /// Lossy ASCII reduction (NFKD decomposition, drop combining marks and non-ASCII).
    AsciiFold,
    /// Drop listed stopwords, preserving their position holes.
    Stopwords(StopwordDataset),
    /// Snowball stemming (opt-in; never applied to patterns).
    Stem(StemmerAlgorithm),
}

/// A character filter that changes byte length (T04).
///
/// PR 4 defers length-changing character filters because no correct original-offset
/// correction map has been approved. Configuring one is rejected at validation time rather
/// than silently producing transformed offsets.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CharacterFilter {
    /// A length-changing replacement/mapping filter (unsupported in PR 4).
    LengthChanging,
}

impl CharacterFilter {
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::LengthChanging => "length-changing",
        }
    }
}

/// The Public Suffix List private-suffix policy (T06).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum PslPrivateSuffixPolicy {
    /// Use the full list, including private (non-ICANN) rules.
    #[default]
    IncludePrivate,
    /// Use only ICANN rules.
    IcannOnly,
}

impl PslPrivateSuffixPolicy {
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::IncludePrivate => "include-private",
            Self::IcannOnly => "icann-only",
        }
    }
}

/// Optional domain-derived analysis configuration (T06).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct DomainConfig {
    /// Whether private PSL rules participate in registered-domain decomposition.
    pub psl_private_suffix_policy: PslPrivateSuffixPolicy,
}

/// A tokenizer plus ordered filters (T03).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Pipeline {
    tokenizer: TokenizerKind,
    character_filters: Vec<CharacterFilter>,
    token_filters: Vec<TokenFilter>,
}

impl Pipeline {
    /// Builds a pipeline, validating character filters immediately.
    pub fn new(
        tokenizer: TokenizerKind,
        character_filters: Vec<CharacterFilter>,
        token_filters: Vec<TokenFilter>,
    ) -> Result<Self, AnalysisError> {
        let pipeline = Self {
            tokenizer,
            character_filters,
            token_filters,
        };
        pipeline.validate()?;
        Ok(pipeline)
    }

    /// A pipeline with the given tokenizer and token filters, no character filters.
    pub fn simple(
        tokenizer: TokenizerKind,
        token_filters: Vec<TokenFilter>,
    ) -> Result<Self, AnalysisError> {
        Self::new(tokenizer, Vec::new(), token_filters)
    }

    /// Rejects any configured character filter (T04).
    pub fn validate(&self) -> Result<(), AnalysisError> {
        if let Some(filter) = self.character_filters.first() {
            return Err(AnalysisError::UnsupportedCharacterFilter {
                name: filter.id().to_owned(),
            });
        }
        Ok(())
    }

    #[must_use]
    pub const fn tokenizer(&self) -> TokenizerKind {
        self.tokenizer
    }

    #[must_use]
    pub fn character_filters(&self) -> &[CharacterFilter] {
        &self.character_filters
    }

    #[must_use]
    pub fn token_filters(&self) -> &[TokenFilter] {
        &self.token_filters
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn length_changing_character_filter_is_rejected() {
        let err = Pipeline::new(
            TokenizerKind::UnicodeWord,
            vec![CharacterFilter::LengthChanging],
            vec![],
        )
        .expect_err("length-changing filters are deferred");
        assert!(matches!(
            err,
            AnalysisError::UnsupportedCharacterFilter { .. }
        ));
    }

    #[test]
    fn simple_pipeline_is_valid() {
        let pipeline = Pipeline::simple(TokenizerKind::Whitespace, vec![]).expect("valid");
        assert_eq!(pipeline.tokenizer(), TokenizerKind::Whitespace);
        assert!(pipeline.character_filters().is_empty());
    }
}
