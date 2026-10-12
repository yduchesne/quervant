//! Term-query preparation and the whole-term pattern boundary (T08, V3).
//!
//! PR 4 defines parse/normalize contracts only. No FST, regex engine, automaton or postings
//! is executed here; that is PR 8. Patterns preserve metacharacters and escaping and are
//! never stemmed.

use super::analyzer::{AnalyzerDefinition, AnalyzerFingerprint, AnalyzerRole};
use super::cancellation::Cancellation;
use super::config::TokenFilter;
use super::error::AnalysisError;
use super::limits::AnalysisLimits;
use super::work::WorkBudget;

/// Metadata attached to every prepared query term.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TermMetadata {
    /// Analyzer id used for preparation.
    pub analyzer_id: String,
    /// Analyzer semantic version.
    pub analyzer_version: String,
    /// Canonical analyzer fingerprint.
    pub fingerprint: AnalyzerFingerprint,
}

fn metadata(analyzer: &AnalyzerDefinition) -> TermMetadata {
    TermMetadata {
        analyzer_id: analyzer.id().to_owned(),
        analyzer_version: analyzer.version().to_owned(),
        fingerprint: analyzer.fingerprint(),
    }
}

/// A single normalized query term.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedTerm {
    term: String,
    metadata: TermMetadata,
}

impl PreparedTerm {
    #[must_use]
    pub fn term(&self) -> &str {
        &self.term
    }

    #[must_use]
    pub fn metadata(&self) -> &TermMetadata {
        &self.metadata
    }
}

/// A normalized literal prefix.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedPrefix {
    prefix: String,
    metadata: TermMetadata,
}

impl PreparedPrefix {
    #[must_use]
    pub fn prefix(&self) -> &str {
        &self.prefix
    }

    #[must_use]
    pub fn metadata(&self) -> &TermMetadata {
        &self.metadata
    }
}

/// A parsed glob segment.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GlobSegment {
    /// A literal run of (possibly normalized) characters.
    Literal(String),
    /// `*`: zero or more Unicode scalar values.
    AnySequence,
    /// `?`: exactly one Unicode scalar value.
    AnyChar,
}

/// A parsed and normalized glob pattern.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedGlob {
    segments: Vec<GlobSegment>,
    normalized: String,
    metadata: TermMetadata,
}

impl PreparedGlob {
    #[must_use]
    pub fn segments(&self) -> &[GlobSegment] {
        &self.segments
    }

    /// The normalized pattern re-serialized with escaping preserved.
    #[must_use]
    pub fn normalized(&self) -> &str {
        &self.normalized
    }

    #[must_use]
    pub fn metadata(&self) -> &TermMetadata {
        &self.metadata
    }
}

/// A validated regex pattern (no case folding, no stemming).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedRegex {
    pattern: String,
    metadata: TermMetadata,
}

impl PreparedRegex {
    #[must_use]
    pub fn pattern(&self) -> &str {
        &self.pattern
    }

    #[must_use]
    pub fn metadata(&self) -> &TermMetadata {
        &self.metadata
    }
}

/// Prepares a term query, requiring the search analyzer to produce exactly one token.
pub fn prepare_term(
    analyzer: &AnalyzerDefinition,
    text: &str,
    limits: &AnalysisLimits,
    cancellation: &dyn Cancellation,
) -> Result<PreparedTerm, AnalysisError> {
    let tokens = analyzer.collect_tokens(AnalyzerRole::Search, &[text], limits, cancellation)?;
    match tokens.as_slice() {
        [] => Err(AnalysisError::EmptyTerm),
        [token] => Ok(PreparedTerm {
            term: token.term().to_owned(),
            metadata: metadata(analyzer),
        }),
        many => Err(AnalysisError::TooManyTerms { count: many.len() }),
    }
}

/// Prepares a prefix query: literal normalization, never stemmed.
pub fn prepare_prefix(
    analyzer: &AnalyzerDefinition,
    prefix: &str,
    limits: &AnalysisLimits,
    cancellation: &dyn Cancellation,
) -> Result<PreparedPrefix, AnalysisError> {
    let mut budget = WorkBudget::new(limits.max_work_units(), cancellation);
    let normalized = normalize_literal(analyzer, prefix, &mut budget)?;
    if normalized.is_empty() {
        return Err(AnalysisError::EmptyTerm);
    }
    Ok(PreparedPrefix {
        prefix: normalized,
        metadata: metadata(analyzer),
    })
}

/// Parses and normalizes a glob pattern, preserving operators and escaping.
pub fn prepare_glob(
    analyzer: &AnalyzerDefinition,
    pattern: &str,
    limits: &AnalysisLimits,
    cancellation: &dyn Cancellation,
) -> Result<PreparedGlob, AnalysisError> {
    let mut budget = WorkBudget::new(limits.max_work_units(), cancellation);
    let mut scanner = PatternScanner::new(pattern);
    let mut segments: Vec<GlobSegment> = Vec::new();
    let mut literal = String::new();
    while let Some(ch) = scanner.next() {
        match ch {
            '*' => {
                flush_literal(analyzer, &mut literal, &mut segments, &mut budget)?;
                if !matches!(segments.last(), Some(GlobSegment::AnySequence)) {
                    segments.push(GlobSegment::AnySequence);
                }
            }
            '?' => {
                flush_literal(analyzer, &mut literal, &mut segments, &mut budget)?;
                segments.push(GlobSegment::AnyChar);
            }
            '\\' => {
                let escaped = scanner
                    .next()
                    .ok_or_else(|| AnalysisError::UnsupportedPattern {
                        reason: "glob pattern ends with a dangling escape".to_owned(),
                    })?;
                literal.push(escaped);
            }
            other => literal.push(other),
        }
    }
    flush_literal(analyzer, &mut literal, &mut segments, &mut budget)?;
    if segments.is_empty() {
        return Err(AnalysisError::EmptyTerm);
    }
    let normalized = serialize_glob(&segments);
    Ok(PreparedGlob {
        segments,
        normalized,
        metadata: metadata(analyzer),
    })
}

/// Validates a regex pattern against the approved bounded subset.
///
/// Case folding and stemming are never applied. Only the field's NFC-style normalization is
/// applied, which cannot rewrite ASCII metacharacters.
pub fn prepare_regex(
    analyzer: &AnalyzerDefinition,
    pattern: &str,
    limits: &AnalysisLimits,
    cancellation: &dyn Cancellation,
) -> Result<PreparedRegex, AnalysisError> {
    validate_regex(pattern)?;
    let mut budget = WorkBudget::new(limits.max_work_units(), cancellation);
    // Apply only canonical normalization; never case-fold or stem a regex.
    let normalized = apply_normalization_only(analyzer, pattern, &mut budget)?;
    if normalized.is_empty() {
        return Err(AnalysisError::EmptyTerm);
    }
    Ok(PreparedRegex {
        pattern: normalized,
        metadata: metadata(analyzer),
    })
}

fn flush_literal(
    analyzer: &AnalyzerDefinition,
    literal: &mut String,
    segments: &mut Vec<GlobSegment>,
    budget: &mut WorkBudget<'_>,
) -> Result<(), AnalysisError> {
    if literal.is_empty() {
        return Ok(());
    }
    let normalized = normalize_literal(analyzer, literal, budget)?;
    literal.clear();
    if !normalized.is_empty() {
        segments.push(GlobSegment::Literal(normalized));
    }
    Ok(())
}

/// Applies only term-shape-preserving normalization filters (never stopwords/stemming).
fn normalize_literal(
    analyzer: &AnalyzerDefinition,
    text: &str,
    budget: &mut WorkBudget<'_>,
) -> Result<String, AnalysisError> {
    let mut term = text.to_owned();
    for filter in analyzer.search_pipeline().token_filters() {
        match filter {
            TokenFilter::Normalize(form) => {
                budget.charge(
                    u64::try_from(term.len())
                        .unwrap_or(u64::MAX)
                        .saturating_add(1),
                )?;
                term = super::filters::normalize(*form, &term);
            }
            TokenFilter::CaseFold => {
                budget.charge(
                    u64::try_from(term.len())
                        .unwrap_or(u64::MAX)
                        .saturating_add(1),
                )?;
                term = super::filters::case_fold(&term);
            }
            TokenFilter::AsciiFold => {
                budget.charge(
                    u64::try_from(term.len())
                        .unwrap_or(u64::MAX)
                        .saturating_add(1),
                )?;
                term = super::filters::ascii_fold(&term);
            }
            // Stopwords and stemming are deliberately skipped for patterns.
            TokenFilter::Stopwords(_) | TokenFilter::Stem(_) => {}
        }
    }
    Ok(term)
}

fn apply_normalization_only(
    analyzer: &AnalyzerDefinition,
    text: &str,
    budget: &mut WorkBudget<'_>,
) -> Result<String, AnalysisError> {
    let mut term = text.to_owned();
    for filter in analyzer.search_pipeline().token_filters() {
        if let TokenFilter::Normalize(form) = filter {
            budget.charge(
                u64::try_from(term.len())
                    .unwrap_or(u64::MAX)
                    .saturating_add(1),
            )?;
            term = super::filters::normalize(*form, &term);
        }
    }
    Ok(term)
}

/// Re-serializes glob segments, escaping literals that contain glob metacharacters.
fn serialize_glob(segments: &[GlobSegment]) -> String {
    let mut out = String::new();
    for segment in segments {
        match segment {
            GlobSegment::Literal(text) => {
                for ch in text.chars() {
                    if matches!(ch, '*' | '?' | '\\') {
                        out.push('\\');
                    }
                    out.push(ch);
                }
            }
            GlobSegment::AnySequence => out.push('*'),
            GlobSegment::AnyChar => out.push('?'),
        }
    }
    out
}

struct PatternScanner<'a> {
    chars: std::iter::Peekable<std::str::Chars<'a>>,
}

impl<'a> PatternScanner<'a> {
    fn new(pattern: &'a str) -> Self {
        Self {
            chars: pattern.chars().peekable(),
        }
    }
}

impl Iterator for PatternScanner<'_> {
    type Item = char;

    fn next(&mut self) -> Option<char> {
        self.chars.next()
    }
}

/// Validates the approved regex subset, rejecting lookaround/backreferences/extensions.
fn validate_regex(pattern: &str) -> Result<(), AnalysisError> {
    if pattern.is_empty() {
        return Err(AnalysisError::EmptyTerm);
    }
    let chars: Vec<char> = pattern.chars().collect();
    let mut index = 0usize;
    let mut group_depth = 0i32;
    let mut in_class = false;
    let mut last_was_quantifier = false;
    while index < chars.len() {
        let ch = chars[index];
        if in_class {
            if ch == '\\' {
                index += 1;
                if index >= chars.len() {
                    return Err(AnalysisError::UnsupportedPattern {
                        reason: "regex character class ends with a dangling escape".to_owned(),
                    });
                }
            } else if ch == ']' {
                in_class = false;
            }
            index += 1;
            continue;
        }
        match ch {
            '\\' => {
                let next = chars.get(index + 1).copied().ok_or_else(|| {
                    AnalysisError::UnsupportedPattern {
                        reason: "regex ends with a dangling escape".to_owned(),
                    }
                })?;
                if next.is_ascii_digit() {
                    return Err(AnalysisError::UnsupportedPattern {
                        reason: "regex backreferences are not supported".to_owned(),
                    });
                }
                index += 2;
                last_was_quantifier = false;
            }
            '[' => {
                in_class = true;
                index += 1;
                last_was_quantifier = false;
            }
            '(' => {
                if chars.get(index + 1) == Some(&'?') {
                    return Err(AnalysisError::UnsupportedPattern {
                        reason: "regex groups with extensions/lookaround are not supported"
                            .to_owned(),
                    });
                }
                group_depth += 1;
                index += 1;
                last_was_quantifier = false;
            }
            ')' => {
                group_depth -= 1;
                if group_depth < 0 {
                    return Err(AnalysisError::UnsupportedPattern {
                        reason: "regex has an unmatched ')'".to_owned(),
                    });
                }
                index += 1;
                last_was_quantifier = false;
            }
            '*' | '+' | '?' => {
                if last_was_quantifier {
                    return Err(AnalysisError::UnsupportedPattern {
                        reason: "regex has stacked quantifiers".to_owned(),
                    });
                }
                last_was_quantifier = true;
                index += 1;
            }
            '{' => {
                let close = chars[index..]
                    .iter()
                    .position(|c| *c == '}')
                    .map(|offset| index + offset)
                    .ok_or_else(|| AnalysisError::UnsupportedPattern {
                        reason: "regex repetition is not closed".to_owned(),
                    })?;
                let body: String = chars[index + 1..close].iter().collect();
                if !valid_repetition(&body) {
                    return Err(AnalysisError::UnsupportedPattern {
                        reason: format!("regex repetition {{{body}}} is not supported"),
                    });
                }
                if last_was_quantifier {
                    return Err(AnalysisError::UnsupportedPattern {
                        reason: "regex has stacked quantifiers".to_owned(),
                    });
                }
                last_was_quantifier = true;
                index = close + 1;
            }
            _ => {
                last_was_quantifier = false;
                index += 1;
            }
        }
    }
    if in_class {
        return Err(AnalysisError::UnsupportedPattern {
            reason: "regex character class is not closed".to_owned(),
        });
    }
    if group_depth != 0 {
        return Err(AnalysisError::UnsupportedPattern {
            reason: "regex has unbalanced groups".to_owned(),
        });
    }
    Ok(())
}

fn valid_repetition(body: &str) -> bool {
    if body.is_empty() {
        return false;
    }
    let mut parts = body.split(',');
    let first = parts.next().unwrap_or("");
    if first.is_empty() || !first.chars().all(|c| c.is_ascii_digit()) {
        return false;
    }
    match parts.next() {
        None => true,
        Some(second) => {
            parts.next().is_none()
                && (second.is_empty() || second.chars().all(|c| c.is_ascii_digit()))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::cancellation::NeverCancel;
    use crate::analysis::config::{
        NormalizationForm, Pipeline, StemmerAlgorithm, StopwordDataset, TokenFilter, TokenizerKind,
    };

    fn analyzer() -> AnalyzerDefinition {
        AnalyzerDefinition::uniform(
            "english",
            "1.0.0",
            Pipeline::simple(
                TokenizerKind::UnicodeWord,
                vec![
                    TokenFilter::Normalize(NormalizationForm::Nfc),
                    TokenFilter::CaseFold,
                    TokenFilter::Stopwords(StopwordDataset::EnglishSnowball),
                    TokenFilter::Stem(StemmerAlgorithm::English),
                ],
            )
            .expect("pipeline"),
        )
        .expect("definition")
    }

    #[test]
    fn prepare_term_requires_exactly_one_term() {
        let analyzer = analyzer();
        let limits = AnalysisLimits::default();
        let term = prepare_term(&analyzer, "Running", &limits, &NeverCancel).expect("term");
        assert_eq!(term.term(), "run");
        assert!(matches!(
            prepare_term(&analyzer, "running fast", &limits, &NeverCancel),
            Err(AnalysisError::TooManyTerms { .. })
        ));
        assert!(matches!(
            prepare_term(&analyzer, "the", &limits, &NeverCancel),
            Err(AnalysisError::EmptyTerm)
        ));
    }

    #[test]
    fn prefix_is_normalized_but_not_stemmed() {
        let analyzer = analyzer();
        let prefix = prepare_prefix(
            &analyzer,
            "RUNNING",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .expect("prefix");
        assert_eq!(prefix.prefix(), "running");
    }

    #[test]
    fn glob_preserves_operators_and_escapes() {
        let analyzer = analyzer();
        let glob = prepare_glob(
            &analyzer,
            r"F*oo\?b?r",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .expect("glob");
        assert_eq!(
            glob.segments(),
            &[
                GlobSegment::Literal("f".to_owned()),
                GlobSegment::AnySequence,
                GlobSegment::Literal("oo?b".to_owned()),
                GlobSegment::AnyChar,
                GlobSegment::Literal("r".to_owned()),
            ]
        );
        assert_eq!(glob.normalized(), r"f*oo\?b?r");
    }

    #[test]
    fn glob_rejects_dangling_escape() {
        assert!(matches!(
            prepare_glob(
                &analyzer(),
                "abc\\",
                &AnalysisLimits::default(),
                &NeverCancel
            ),
            Err(AnalysisError::UnsupportedPattern { .. })
        ));
    }

    #[test]
    fn regex_validator_accepts_bounded_subset() {
        let analyzer = analyzer();
        assert!(
            prepare_regex(
                &analyzer,
                r"^ab(c|d)[0-9]{2,4}$",
                &AnalysisLimits::default(),
                &NeverCancel
            )
            .is_ok()
        );
    }

    #[test]
    fn regex_validator_rejects_lookaround_backreference_and_unbalanced() {
        let analyzer = analyzer();
        for bad in [r"a(?=b)", r"(a)\1", r"(a", r"[a", r"a**"] {
            assert!(
                matches!(
                    prepare_regex(&analyzer, bad, &AnalysisLimits::default(), &NeverCancel),
                    Err(AnalysisError::UnsupportedPattern { .. })
                ),
                "expected rejection for {bad:?}"
            );
        }
    }

    #[test]
    fn regex_is_not_case_folded_or_stemmed() {
        let analyzer = analyzer();
        let regex = prepare_regex(
            &analyzer,
            "RUN[a-z]",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .expect("regex");
        assert_eq!(regex.pattern(), "RUN[a-z]");
    }
}
