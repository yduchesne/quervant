//! Term-query preparation and the whole-term pattern boundary (T08, V3).
//!
//! PR 4 defines parse/normalize contracts only. No FST, regex engine, automaton or postings
//! is executed here; that is PR 8. Patterns preserve metacharacters and escaping and are
//! never stemmed.

use regex_syntax::ast::{Ast, ClassAsciiKind, ClassSet, ClassSetItem, GroupKind};

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

/// Maximum regex nesting accepted by the parser-only validator. This bounds parser recursion
/// (and therefore validator recursion) independently of the pattern byte ceiling.
const REGEX_NEST_LIMIT: u32 = 64;

/// A literal replacement within the original pattern string.
struct LiteralReplacement {
    start: usize,
    end: usize,
    text: String,
}

/// Validates and normalizes a regex pattern against the approved bounded subset (T08, V3).
///
/// Grammar validation uses the parser-only `regex-syntax` AST; nothing is compiled or executed.
/// Only literal nodes are normalized, using the same ordered search-time
/// `Normalize`/`CaseFold`/`AsciiFold` transforms as indexed terms; stopwords and stemming are
/// never applied. Constructs outside the subset — inline flags, named captures, and character
/// classes under a case-transforming analyzer — are rejected with a typed error, as are literal
/// transformations that would change the term length. The normalized output is re-parsed and
/// re-validated.
pub fn prepare_regex(
    analyzer: &AnalyzerDefinition,
    pattern: &str,
    limits: &AnalysisLimits,
    cancellation: &dyn Cancellation,
) -> Result<PreparedRegex, AnalysisError> {
    let mut budget = WorkBudget::new(limits.max_work_units(), cancellation);
    budget.check_cancelled()?;
    if pattern.is_empty() {
        return Err(AnalysisError::EmptyTerm);
    }
    let pattern_bytes = u64::try_from(pattern.len()).unwrap_or(u64::MAX);
    if pattern_bytes > limits.max_input_bytes() {
        return Err(AnalysisError::InputTooLarge {
            limit: limits.max_input_bytes(),
            actual: pattern_bytes,
        });
    }
    // Deterministic parse-cost proxy charged before invoking the opaque parser.
    budget.charge(u64::try_from(pattern.chars().count()).unwrap_or(u64::MAX))?;

    let case_transforming = pipeline_case_transforms(analyzer);
    let ast = parse_regex(pattern)?;
    let mut replacements = Vec::new();
    validate_and_collect(
        analyzer,
        &ast,
        case_transforming,
        &mut budget,
        &mut replacements,
    )?;
    let normalized = apply_replacements(pattern, replacements)?;
    if normalized.is_empty() {
        return Err(AnalysisError::EmptyTerm);
    }
    // Re-parse and re-validate the serialized output so normalization cannot produce a pattern
    // outside the approved subset.
    let reparsed = parse_regex(&normalized)?;
    let mut ignored = Vec::new();
    validate_and_collect(
        analyzer,
        &reparsed,
        case_transforming,
        &mut budget,
        &mut ignored,
    )?;
    Ok(PreparedRegex {
        pattern: normalized,
        metadata: metadata(analyzer),
    })
}

/// Parses a regex with a bounded nesting limit; returns a typed error on any syntax problem.
fn parse_regex(pattern: &str) -> Result<Ast, AnalysisError> {
    let mut builder = regex_syntax::ast::parse::ParserBuilder::new();
    builder.nest_limit(REGEX_NEST_LIMIT);
    let mut parser = builder.build();
    parser
        .parse(pattern)
        .map_err(|error| AnalysisError::UnsupportedPattern {
            reason: format!("invalid regex: {}", first_line(&error.to_string())),
        })
}

fn first_line(text: &str) -> &str {
    text.lines().next().unwrap_or(text)
}

/// Whether the search pipeline applies any case-transforming filter.
fn pipeline_case_transforms(analyzer: &AnalyzerDefinition) -> bool {
    analyzer
        .search_pipeline()
        .token_filters()
        .iter()
        .any(|filter| matches!(filter, TokenFilter::CaseFold | TokenFilter::AsciiFold))
}

fn validate_and_collect(
    analyzer: &AnalyzerDefinition,
    ast: &Ast,
    case_transforming: bool,
    budget: &mut WorkBudget<'_>,
    replacements: &mut Vec<LiteralReplacement>,
) -> Result<(), AnalysisError> {
    budget.check_cancelled()?;
    match ast {
        Ast::Empty(_) | Ast::Dot(_) | Ast::Assertion(_) | Ast::ClassPerl(_) => Ok(()),
        Ast::Flags(_) => Err(unsupported_regex(
            "inline regex flags are not supported; case handling is defined by the analyzer",
        )),
        Ast::Literal(literal) => {
            let original = literal.c.to_string();
            let transformed = apply_pattern_transforms(analyzer, &original, budget)?;
            let mut chars = transformed.chars();
            let single = match (chars.next(), chars.next()) {
                (Some(single), None) => single,
                _ => {
                    return Err(unsupported_regex(
                        "regex literal normalization would change length and quantifier scope",
                    ));
                }
            };
            if transformed != original {
                replacements.push(LiteralReplacement {
                    start: literal.span.start.offset,
                    end: literal.span.end.offset,
                    text: escape_regex_literal(single),
                });
            }
            Ok(())
        }
        Ast::ClassUnicode(_) => {
            if case_transforming {
                return Err(unsupported_regex(
                    "Unicode property classes are not supported with a case-folding analyzer",
                ));
            }
            Ok(())
        }
        Ast::ClassBracketed(class) => {
            if case_transforming && !class_set_is_case_stable(analyzer, &class.kind, budget)? {
                return Err(unsupported_regex(
                    "regex character class is not case-stable under this case-folding analyzer",
                ));
            }
            Ok(())
        }
        Ast::Repetition(repetition) => {
            if matches!(repetition.ast.as_ref(), Ast::Repetition(_)) {
                return Err(unsupported_regex(
                    "stacked regex quantifiers are not supported",
                ));
            }
            validate_and_collect(
                analyzer,
                &repetition.ast,
                case_transforming,
                budget,
                replacements,
            )
        }
        Ast::Group(group) => {
            match &group.kind {
                GroupKind::CaptureIndex(_) => {}
                GroupKind::CaptureName { .. } => {
                    return Err(unsupported_regex(
                        "named regex capture groups are not supported",
                    ));
                }
                GroupKind::NonCapturing(flags) => {
                    if !flags.items.is_empty() {
                        return Err(unsupported_regex(
                            "regex inline flags in groups are not supported",
                        ));
                    }
                }
            }
            validate_and_collect(
                analyzer,
                &group.ast,
                case_transforming,
                budget,
                replacements,
            )
        }
        Ast::Alternation(alternation) => {
            for child in &alternation.asts {
                validate_and_collect(analyzer, child, case_transforming, budget, replacements)?;
            }
            Ok(())
        }
        Ast::Concat(concat) => {
            for child in &concat.asts {
                validate_and_collect(analyzer, child, case_transforming, budget, replacements)?;
            }
            Ok(())
        }
    }
}

/// Applies the ordered search-time pattern transforms (never stopwords/stemming).
fn apply_pattern_transforms(
    analyzer: &AnalyzerDefinition,
    text: &str,
    budget: &mut WorkBudget<'_>,
) -> Result<String, AnalysisError> {
    let mut current = text.to_owned();
    for filter in analyzer.search_pipeline().token_filters() {
        match filter {
            TokenFilter::Normalize(form) => {
                budget.charge(
                    u64::try_from(current.len())
                        .unwrap_or(u64::MAX)
                        .saturating_add(1),
                )?;
                current = super::filters::normalize(*form, &current);
            }
            TokenFilter::CaseFold => {
                budget.charge(
                    u64::try_from(current.len())
                        .unwrap_or(u64::MAX)
                        .saturating_add(1),
                )?;
                current = super::filters::case_fold(&current);
            }
            TokenFilter::AsciiFold => {
                budget.charge(
                    u64::try_from(current.len())
                        .unwrap_or(u64::MAX)
                        .saturating_add(1),
                )?;
                current = super::filters::ascii_fold(&current);
            }
            TokenFilter::Stopwords(_) | TokenFilter::Stem(_) => {}
        }
    }
    Ok(current)
}

/// Whether a bracketed character class matches the same set after case folding.
fn class_set_is_case_stable(
    analyzer: &AnalyzerDefinition,
    set: &ClassSet,
    budget: &mut WorkBudget<'_>,
) -> Result<bool, AnalysisError> {
    match set {
        ClassSet::Item(item) => class_item_is_case_stable(analyzer, item, budget),
        ClassSet::BinaryOp(op) => Ok(class_set_is_case_stable(analyzer, &op.lhs, budget)?
            && class_set_is_case_stable(analyzer, &op.rhs, budget)?),
    }
}

fn class_item_is_case_stable(
    analyzer: &AnalyzerDefinition,
    item: &ClassSetItem,
    budget: &mut WorkBudget<'_>,
) -> Result<bool, AnalysisError> {
    match item {
        ClassSetItem::Empty(_) => Ok(true),
        ClassSetItem::Literal(literal) => literal_is_case_stable(analyzer, literal.c, budget),
        ClassSetItem::Range(range) => Ok(literal_is_case_stable(analyzer, range.start.c, budget)?
            && literal_is_case_stable(analyzer, range.end.c, budget)?),
        // `[[:upper:]]` cannot match case-folded terms; all other ASCII classes include the
        // folded (lowercase) form.
        ClassSetItem::Ascii(ascii) => Ok(!matches!(ascii.kind, ClassAsciiKind::Upper)),
        // Unicode property classes may be case-dependent (e.g. `\p{Lu}`); reject conservatively.
        ClassSetItem::Unicode(_) => Ok(false),
        ClassSetItem::Perl(_) => Ok(true),
        ClassSetItem::Bracketed(inner) => class_set_is_case_stable(analyzer, &inner.kind, budget),
        ClassSetItem::Union(union) => {
            for item in &union.items {
                if !class_item_is_case_stable(analyzer, item, budget)? {
                    return Ok(false);
                }
            }
            Ok(true)
        }
    }
}

fn literal_is_case_stable(
    analyzer: &AnalyzerDefinition,
    c: char,
    budget: &mut WorkBudget<'_>,
) -> Result<bool, AnalysisError> {
    let original = c.to_string();
    let transformed = apply_pattern_transforms(analyzer, &original, budget)?;
    Ok(transformed == original)
}

fn escape_regex_literal(c: char) -> String {
    if regex_syntax::is_meta_character(c) {
        format!("\\{c}")
    } else if c.is_control() {
        format!("\\u{{{:X}}}", u32::from(c))
    } else {
        c.to_string()
    }
}

fn apply_replacements(
    pattern: &str,
    mut replacements: Vec<LiteralReplacement>,
) -> Result<String, AnalysisError> {
    replacements.sort_by_key(|replacement| replacement.start);
    let mut output = String::with_capacity(pattern.len());
    let mut cursor = 0usize;
    for replacement in replacements {
        if replacement.start < cursor
            || replacement.end > pattern.len()
            || !pattern.is_char_boundary(replacement.start)
            || !pattern.is_char_boundary(replacement.end)
        {
            return Err(unsupported_regex("internal regex span mapping failed"));
        }
        output.push_str(&pattern[cursor..replacement.start]);
        output.push_str(&replacement.text);
        cursor = replacement.end;
    }
    output.push_str(&pattern[cursor..]);
    Ok(output)
}

fn unsupported_regex(reason: &str) -> AnalysisError {
    AnalysisError::UnsupportedPattern {
        reason: reason.to_owned(),
    }
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

    fn standard_analyzer() -> AnalyzerDefinition {
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
    fn regex_accepts_approved_bounded_subset() {
        let analyzer = analyzer();
        let regex = prepare_regex(
            &analyzer,
            r"^ab(c|d)[0-9]{2,4}$",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .expect("regex");
        assert_eq!(regex.pattern(), r"^ab(c|d)[0-9]{2,4}$");
    }

    #[test]
    fn regex_rejects_malformed_and_forbidden_constructs() {
        let analyzer = analyzer();
        for bad in [
            r"a{3,2}",
            r"*abc",
            r"[z-a]",
            r"(ab",
            r"a\",
            r"[a",
            r"(a)\1",
            r"a(?=b)",
            r"a**",
            r"(?i)abc",
            r"(?<name>a)",
        ] {
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
    fn regex_empty_alternation_is_a_documented_supported_form() {
        let analyzer = analyzer();
        let regex = prepare_regex(&analyzer, "a|", &AnalysisLimits::default(), &NeverCancel)
            .expect("regex");
        assert_eq!(regex.pattern(), "a|");
    }

    #[test]
    fn regex_literals_are_folded_like_indexed_terms() {
        let analyzer = analyzer();
        let regex = prepare_regex(&analyzer, "RUN", &AnalysisLimits::default(), &NeverCancel)
            .expect("regex");
        assert_eq!(regex.pattern(), "run");
    }

    #[test]
    fn regex_case_unstable_classes_are_rejected_when_folding() {
        let analyzer = analyzer();
        for bad in [r"[A-Z]", r"[A-Za-z]", r"\p{Lu}", r"(?i:abc)"] {
            assert!(
                matches!(
                    prepare_regex(&analyzer, bad, &AnalysisLimits::default(), &NeverCancel),
                    Err(AnalysisError::UnsupportedPattern { .. })
                ),
                "expected rejection for {bad:?}"
            );
        }
        for good in [r"[0-9]{2,4}", r"\d+", r"[a-z]", r"\w"] {
            assert!(
                prepare_regex(&analyzer, good, &AnalysisLimits::default(), &NeverCancel).is_ok(),
                "expected acceptance for {good:?}"
            );
        }
    }

    #[test]
    fn regex_non_folding_analyzer_preserves_case_sensitive_classes() {
        let analyzer = standard_analyzer();
        let regex = prepare_regex(
            &analyzer,
            r"[A-Z]+",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .expect("regex");
        assert_eq!(regex.pattern(), r"[A-Z]+");
    }

    #[test]
    fn regex_literal_expansion_is_rejected() {
        let analyzer = analyzer();
        assert!(matches!(
            prepare_regex(
                &analyzer,
                "Straße+",
                &AnalysisLimits::default(),
                &NeverCancel
            ),
            Err(AnalysisError::UnsupportedPattern { .. })
        ));
    }

    #[test]
    fn regex_escaped_operators_are_preserved() {
        let analyzer = analyzer();
        let regex = prepare_regex(&analyzer, r"a\.b", &AnalysisLimits::default(), &NeverCancel)
            .expect("regex");
        assert_eq!(regex.pattern(), r"a\.b");
    }

    #[test]
    fn regex_pattern_byte_ceiling_is_enforced() {
        let analyzer = analyzer();
        let limits = AnalysisLimits::default()
            .with_max_input_bytes(4)
            .expect("lower");
        assert!(matches!(
            prepare_regex(&analyzer, "abcdef", &limits, &NeverCancel),
            Err(AnalysisError::InputTooLarge { .. })
        ));
    }
}
