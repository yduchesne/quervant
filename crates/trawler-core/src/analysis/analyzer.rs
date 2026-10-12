//! Analyzer definitions, canonical fingerprints and the bounded pull cursor (T01, T02,
//! T05, T07).

use rust_stemmers::Stemmer;
use sha2::{Digest, Sha256};

use super::cancellation::Cancellation;
use super::config::{DomainConfig, NormalizationForm, Pipeline, TokenFilter, TokenizerKind};
use super::error::AnalysisError;
use super::filters;
use super::limits::AnalysisLimits;
use super::token::Token;
use super::tokenizer::{Span, SpanCursor};
use super::work::WorkBudget;

/// Position gap inserted between distinct field values (T02).
pub const POSITION_GAP: u32 = 100;

/// Whether an analyzer definition is used for indexing or querying.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AnalyzerRole {
    /// Index-time analysis.
    Index,
    /// Search-time analysis.
    Search,
}

/// A canonical, version-tagged analyzer fingerprint (T05).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AnalyzerFingerprint([u8; 32]);

impl AnalyzerFingerprint {
    #[must_use]
    pub const fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }

    #[must_use]
    pub fn to_hex(&self) -> String {
        let mut out = String::with_capacity(64);
        for byte in self.0 {
            out.push(char::from_digit(u32::from(byte >> 4), 16).unwrap_or('0'));
            out.push(char::from_digit(u32::from(byte & 0x0f), 16).unwrap_or('0'));
        }
        out
    }
}

impl std::fmt::Display for AnalyzerFingerprint {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.to_hex())
    }
}

/// A versioned analyzer definition with explicit index and search pipelines.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnalyzerDefinition {
    id: String,
    version: String,
    index: Pipeline,
    search: Pipeline,
    domain: Option<DomainConfig>,
}

impl AnalyzerDefinition {
    /// Builds a definition whose index and search pipelines are identical.
    pub fn uniform(
        id: impl Into<String>,
        version: impl Into<String>,
        pipeline: Pipeline,
    ) -> Result<Self, AnalysisError> {
        Self::new(id, version, pipeline.clone(), pipeline, None)
    }

    /// Builds a definition with distinct index/search pipelines and optional domain support.
    pub fn new(
        id: impl Into<String>,
        version: impl Into<String>,
        index: Pipeline,
        search: Pipeline,
        domain: Option<DomainConfig>,
    ) -> Result<Self, AnalysisError> {
        let id = id.into();
        let version = version.into();
        if id.is_empty() {
            return Err(AnalysisError::InvalidConfiguration {
                reason: "analyzer id must not be empty".to_owned(),
            });
        }
        if version.is_empty() {
            return Err(AnalysisError::InvalidConfiguration {
                reason: "analyzer version must not be empty".to_owned(),
            });
        }
        index.validate()?;
        search.validate()?;
        Ok(Self {
            id,
            version,
            index,
            search,
            domain,
        })
    }

    #[must_use]
    pub fn id(&self) -> &str {
        &self.id
    }

    #[must_use]
    pub fn version(&self) -> &str {
        &self.version
    }

    #[must_use]
    pub const fn index_pipeline(&self) -> &Pipeline {
        &self.index
    }

    #[must_use]
    pub const fn search_pipeline(&self) -> &Pipeline {
        &self.search
    }

    #[must_use]
    pub const fn domain(&self) -> Option<DomainConfig> {
        self.domain
    }

    /// Attaches an approved domain configuration (T06).
    #[must_use]
    pub fn with_domain(mut self, domain: DomainConfig) -> Self {
        self.domain = Some(domain);
        self
    }

    pub(crate) fn pipeline(&self, role: AnalyzerRole) -> &Pipeline {
        match role {
            AnalyzerRole::Index => &self.index,
            AnalyzerRole::Search => &self.search,
        }
    }

    /// The canonical fingerprint covering id, version, both pipelines, domain policy and the
    /// exact pinned dataset/library versions referenced by the definition.
    #[must_use]
    pub fn fingerprint(&self) -> AnalyzerFingerprint {
        let mut encoder = CanonicalEncoder::new();
        encoder.tag("trawler-analyzer-fingerprint-v1");
        encoder.field(self.id.as_bytes());
        encoder.field(self.version.as_bytes());
        encode_pipeline(&mut encoder, "index", &self.index);
        encode_pipeline(&mut encoder, "search", &self.search);
        match self.domain {
            None => encoder.tag("domain-none"),
            Some(config) => {
                encoder.tag("domain");
                encoder.field(config.psl_private_suffix_policy.id().as_bytes());
                encode_domain_data_versions(&mut encoder);
            }
        }
        let digest = Sha256::digest(&encoder.bytes);
        let mut out = [0u8; 32];
        out.copy_from_slice(&digest);
        AnalyzerFingerprint(out)
    }

    /// Builds a bounded pull cursor over independent field values.
    pub fn analyze<'a>(
        &'a self,
        role: AnalyzerRole,
        values: &'a [&'a str],
        limits: &'a AnalysisLimits,
        cancellation: &'a dyn Cancellation,
    ) -> Result<AnalysisCursor<'a>, AnalysisError> {
        AnalysisCursor::new(self.pipeline(role), values, limits, cancellation)
    }

    /// Convenience bounded collection; uses the same limits as the cursor.
    pub fn collect_tokens(
        &self,
        role: AnalyzerRole,
        values: &[&str],
        limits: &AnalysisLimits,
        cancellation: &dyn Cancellation,
    ) -> Result<Vec<Token>, AnalysisError> {
        let mut cursor = self.analyze(role, values, limits, cancellation)?;
        let mut tokens = Vec::new();
        while let Some(token) = cursor.next_token()? {
            tokens.push(token);
        }
        Ok(tokens)
    }
}

/// A bounded, fallible, synchronous pull cursor over analyzed tokens.
///
/// Tokens are produced lazily: the cursor scans at most until the next retained token and never
/// materializes an entire value. Work is charged incrementally and cancellation is polled at
/// deterministic boundaries. The emitted-token ceiling is enforced **per value** (T07); the
/// work budget remains call-wide.
pub struct AnalysisCursor<'a> {
    pipeline: &'a Pipeline,
    values: &'a [&'a str],
    limits: &'a AnalysisLimits,
    budget: WorkBudget<'a>,
    next_value: usize,
    active: Option<ActiveValue<'a>>,
    raw_position_cursor: Option<u32>,
    last_retained_position: Option<u32>,
    stemmer: Option<Stemmer>,
}

/// Per-value lazy state.
struct ActiveValue<'a> {
    value: &'a str,
    value_index: u32,
    spans: SpanCursor<'a>,
    base: u32,
    raw_index: u32,
    emitted: u64,
}

impl<'a> AnalysisCursor<'a> {
    fn new(
        pipeline: &'a Pipeline,
        values: &'a [&'a str],
        limits: &'a AnalysisLimits,
        cancellation: &'a dyn Cancellation,
    ) -> Result<Self, AnalysisError> {
        let stemmer = pipeline
            .token_filters()
            .iter()
            .find_map(|filter| match filter {
                TokenFilter::Stem(algorithm) => Some(filters::stemmer(*algorithm)),
                _ => None,
            });
        let budget = WorkBudget::new(limits.max_work_units(), cancellation);
        // Poll once up front so cancellation-at-start is observable (A4-09).
        budget.check_cancelled()?;
        Ok(Self {
            pipeline,
            values,
            limits,
            budget,
            next_value: 0,
            active: None,
            raw_position_cursor: None,
            last_retained_position: None,
            stemmer,
        })
    }

    /// Produces the next retained token, or `None` at end of input.
    pub fn next_token(&mut self) -> Result<Option<Token>, AnalysisError> {
        loop {
            if self.active.is_none() {
                if self.next_value >= self.values.len() {
                    return Ok(None);
                }
                self.start_value()?;
                continue;
            }
            let span = {
                let active = self.active.as_mut().ok_or_else(active_value_invariant)?;
                active.spans.next_span(&mut self.budget)?
            };
            match span {
                None => {
                    self.active = None;
                }
                Some(span) => {
                    if let Some(token) = self.process_span(span)? {
                        return Ok(Some(token));
                    }
                }
            }
        }
    }

    fn start_value(&mut self) -> Result<(), AnalysisError> {
        let value = self.values[self.next_value];
        let value_index =
            u32::try_from(self.next_value).map_err(|_| AnalysisError::OffsetOverflow)?;
        let value_len = u64::try_from(value.len()).unwrap_or(u64::MAX);
        if value_len > self.limits.max_input_bytes() {
            return Err(AnalysisError::InputTooLarge {
                limit: self.limits.max_input_bytes(),
                actual: value_len,
            });
        }
        self.budget.check_cancelled()?;
        let base = match self.raw_position_cursor {
            None => 0,
            Some(previous) => previous
                .checked_add(POSITION_GAP)
                .ok_or(AnalysisError::PositionOverflow)?,
        };
        self.active = Some(ActiveValue {
            value,
            value_index,
            spans: SpanCursor::new(self.pipeline.tokenizer(), value),
            base,
            raw_index: 0,
            emitted: 0,
        });
        self.next_value += 1;
        Ok(())
    }

    fn process_span(&mut self, span: Span) -> Result<Option<Token>, AnalysisError> {
        let (value, value_index, position) = {
            let active = self.active.as_ref().ok_or_else(active_value_invariant)?;
            if span.start > span.end || span.end > active.value.len() {
                return Err(AnalysisError::InvalidOffset {
                    reason: "tokenizer produced an out-of-range span".to_owned(),
                });
            }
            if !active.value.is_char_boundary(span.start)
                || !active.value.is_char_boundary(span.end)
            {
                return Err(AnalysisError::InvalidOffset {
                    reason: "tokenizer produced a non-UTF-8 boundary".to_owned(),
                });
            }
            let position = active
                .base
                .checked_add(active.raw_index)
                .ok_or(AnalysisError::PositionOverflow)?;
            (active.value, active.value_index, position)
        };
        // Raw positions advance for every scanned span, including dropped stopwords, so the
        // value-boundary gap is preserved.
        self.raw_position_cursor = Some(position);
        if let Some(active) = self.active.as_mut() {
            active.raw_index = active
                .raw_index
                .checked_add(1)
                .ok_or(AnalysisError::PositionOverflow)?;
        }
        let raw_term = &value[span.start..span.end];
        let Some(term) = self.apply_filters(raw_term)? else {
            return Ok(None);
        };
        let term_bytes = u64::try_from(term.len()).unwrap_or(u64::MAX);
        if term_bytes > self.limits.max_term_bytes() {
            return Err(AnalysisError::TermTooLarge {
                limit: self.limits.max_term_bytes(),
                actual: term_bytes,
            });
        }
        let increment = match self.last_retained_position {
            None => position
                .checked_add(1)
                .ok_or(AnalysisError::PositionOverflow)?,
            Some(previous) => position
                .checked_sub(previous)
                .filter(|increment| *increment > 0)
                .ok_or(AnalysisError::PositionOverflow)?,
        };
        let start = u32::try_from(span.start).map_err(|_| AnalysisError::OffsetOverflow)?;
        let end = u32::try_from(span.end).map_err(|_| AnalysisError::OffsetOverflow)?;
        let token = Token::new(term, value_index, position, increment, 1, start, end)?;
        token.validate_against(value)?;
        // Per-value emitted-token ceiling (T07).
        let active = self.active.as_mut().ok_or_else(active_value_invariant)?;
        active.emitted = active
            .emitted
            .checked_add(1)
            .ok_or(AnalysisError::TooManyTokens {
                limit: self.limits.max_tokens(),
            })?;
        if active.emitted > self.limits.max_tokens() {
            return Err(AnalysisError::TooManyTokens {
                limit: self.limits.max_tokens(),
            });
        }
        self.last_retained_position = Some(position);
        Ok(Some(token))
    }

    /// Applies the ordered token filters, returning `None` if the token is dropped.
    fn apply_filters(&mut self, raw_term: &str) -> Result<Option<String>, AnalysisError> {
        // Deterministic checkpoint before any (potentially expensive) filter work.
        self.budget.check_cancelled()?;
        let mut term = raw_term.to_owned();
        for filter in self.pipeline.token_filters() {
            match filter {
                TokenFilter::Normalize(form) => {
                    self.charge_filter(term.len(), 0)?;
                    term = filters::normalize(*form, &term);
                }
                TokenFilter::CaseFold => {
                    self.charge_filter(term.len(), 0)?;
                    term = filters::case_fold(&term);
                }
                TokenFilter::AsciiFold => {
                    self.charge_filter(term.len(), 0)?;
                    term = filters::ascii_fold(&term);
                }
                TokenFilter::Stopwords(dataset) => {
                    self.budget.charge(1)?;
                    if filters::is_stopword(*dataset, &term) {
                        return Ok(None);
                    }
                }
                TokenFilter::Stem(_algorithm) => {
                    self.charge_filter(term.len(), 1)?;
                    match self.stemmer.as_ref() {
                        Some(stemmer) => term = filters::stem(stemmer, &term),
                        None => {
                            return Err(AnalysisError::InvalidConfiguration {
                                reason: "stemmer filter without an initialized stemmer".to_owned(),
                            });
                        }
                    }
                }
            }
        }
        if term.is_empty() {
            return Ok(None);
        }
        Ok(Some(term))
    }

    fn charge_filter(&mut self, term_bytes: usize, extra: u64) -> Result<(), AnalysisError> {
        let bytes = u64::try_from(term_bytes).unwrap_or(u64::MAX);
        self.budget
            .charge(bytes.saturating_add(extra).saturating_add(1))
    }
}

/// Internal invariant error: the cursor must always have an active value here.
fn active_value_invariant() -> AnalysisError {
    AnalysisError::InvalidConfiguration {
        reason: "analysis cursor has no active value".to_owned(),
    }
}

/// A deterministic, length-delimited canonical byte encoder.
struct CanonicalEncoder {
    bytes: Vec<u8>,
}

impl CanonicalEncoder {
    fn new() -> Self {
        Self { bytes: Vec::new() }
    }

    fn tag(&mut self, value: &str) {
        self.field(value.as_bytes());
    }

    fn field(&mut self, value: &[u8]) {
        self.u64(u64::try_from(value.len()).unwrap_or(u64::MAX));
        self.bytes.extend_from_slice(value);
    }

    fn u64(&mut self, value: u64) {
        self.bytes.extend_from_slice(&value.to_be_bytes());
    }
}

fn encode_pipeline(encoder: &mut CanonicalEncoder, label: &str, pipeline: &Pipeline) {
    encoder.tag(label);
    encoder.tag(pipeline.tokenizer().id());
    encoder.u64(pipeline.character_filters().len() as u64);
    for filter in pipeline.character_filters() {
        encoder.tag(filter.id());
    }
    encoder.u64(pipeline.token_filters().len() as u64);
    for filter in pipeline.token_filters() {
        match filter {
            TokenFilter::Normalize(form) => {
                encoder.tag("normalize");
                encoder.tag(form.id());
                if *form != NormalizationForm::None {
                    encode_unicode_library_versions(encoder);
                }
            }
            TokenFilter::CaseFold => {
                encoder.tag("case-fold");
                encode_unicode_library_versions(encoder);
            }
            TokenFilter::AsciiFold => {
                encoder.tag("ascii-fold");
                encode_unicode_library_versions(encoder);
            }
            TokenFilter::Stopwords(dataset) => {
                encoder.tag("stopwords");
                encoder.tag(dataset.id());
                encoder.tag(dataset.version());
                encoder.tag(filters::STOPWORDS_SHA256);
            }
            TokenFilter::Stem(algorithm) => {
                encoder.tag("stem");
                encoder.tag(algorithm.id());
                encoder.tag(super::domain_data::RUST_STEMMERS_VERSION);
            }
        }
    }
    if pipeline.tokenizer() == TokenizerKind::UnicodeWord {
        let (major, minor, patch) = unicode_segmentation::UNICODE_VERSION;
        encoder.tag("unicode-segmentation");
        encoder.u64(major);
        encoder.u64(minor);
        encoder.u64(patch);
    }
}

fn encode_unicode_library_versions(encoder: &mut CanonicalEncoder) {
    let (major, minor, patch) = unicode_normalization::UNICODE_VERSION;
    encoder.tag("unicode-normalization");
    encoder.u64(u64::from(major));
    encoder.u64(u64::from(minor));
    encoder.u64(u64::from(patch));
    encoder.tag("icu4x");
    encoder.tag(super::domain_data::ICU4X_DATASET_ID);
}

fn encode_domain_data_versions(encoder: &mut CanonicalEncoder) {
    encoder.tag("idna");
    encoder.tag("uts46-nontransitional");
    encoder.tag(super::domain_data::IDNA_VERSION);
    encoder.tag(super::domain_data::ICU4X_DATASET_ID);
    encoder.tag("psl");
    encoder.tag(super::domain_data::PUBLICSUFFIX_VERSION);
    encoder.tag(super::domain_data::PSL_DATASET_VERSION);
    encoder.tag(super::domain_data::PSL_DATASET_COMMIT);
    encoder.tag(super::domain_data::PSL_DATASET_RETRIEVED);
    encoder.tag(filters::PSL_SHA256);
    let (major, minor, patch) = unicode_security::UNICODE_VERSION;
    encoder.tag("uts39");
    encoder.tag(super::domain_data::UNICODE_SECURITY_VERSION);
    encoder.u64(major);
    encoder.u64(minor);
    encoder.u64(patch);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::cancellation::NeverCancel;
    use crate::analysis::config::{NormalizationForm, TokenFilter, TokenizerKind};

    fn standard() -> AnalyzerDefinition {
        AnalyzerDefinition::uniform(
            "standard",
            "1.0.0",
            Pipeline::simple(
                TokenizerKind::UnicodeWord,
                vec![TokenFilter::Normalize(NormalizationForm::Nfc)],
            )
            .expect("pipeline"),
        )
        .expect("definition")
    }

    #[test]
    fn fingerprint_is_stable_and_version_sensitive() {
        let a = standard();
        let b = standard();
        assert_eq!(a.fingerprint(), b.fingerprint());
        let changed = AnalyzerDefinition::uniform("standard", "1.0.1", a.index_pipeline().clone())
            .expect("definition");
        assert_ne!(a.fingerprint(), changed.fingerprint());
    }

    #[test]
    fn collect_tokens_matches_cursor() {
        let analyzer = standard();
        let values = ["Running runners", "run"];
        let limits = AnalysisLimits::default();
        let tokens = analyzer
            .collect_tokens(AnalyzerRole::Index, &values, &limits, &NeverCancel)
            .expect("analysis");
        assert_eq!(tokens.len(), 3);
    }

    #[test]
    fn position_overflow_is_checked() {
        let analyzer = standard();
        let values = ["x"];
        let limits = AnalysisLimits::default();
        let mut cursor = analyzer
            .analyze(AnalyzerRole::Index, &values, &limits, &NeverCancel)
            .expect("cursor");
        // Seed the running cursor at the maximum representable position so the next value's
        // base position cannot be represented: this must fail typed, never wrap.
        cursor.raw_position_cursor = Some(u32::MAX);
        let err = cursor.next_token().expect_err("overflow");
        assert!(matches!(err, AnalysisError::PositionOverflow));
    }
}
