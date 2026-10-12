//! Term-query preparation and the whole-term pattern boundary (T08, V3).
//!
//! PR 4 defines parse/normalize contracts only. No FST, regex engine, automaton or postings
//! is executed here; that is PR 8. Patterns preserve metacharacters and escaping and are
//! never stemmed.

use regex_syntax::ast::{
    Ast, ClassAsciiKind, ClassSet, ClassSetItem, GroupKind, RepetitionKind, RepetitionRange,
};
use unicode_normalization::char::canonical_combining_class;

use super::analyzer::{AnalyzerDefinition, AnalyzerFingerprint, AnalyzerRole};
use super::cancellation::Cancellation;
use super::config::{NormalizationForm, TokenFilter};
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
/// Decoded **literal runs** (adjacent literal nodes with no intervening operator) are normalized
/// as a whole with the same ordered search-time `Normalize`/`CaseFold`/`AsciiFold` transforms as
/// indexed terms, then re-escaped as literal scalars; stopwords and stemming are never applied.
/// Constructs outside the subset — inline flags, named captures, literals whose scope cannot be
/// preserved (quantified expansions, combining marks that could compose across a boundary), and
/// character classes/ranges not stable over their whole interior under the configured
/// transforms — are rejected with a typed error. The normalized output is re-parsed and
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

    let policy = PatternPolicy::from_analyzer(analyzer);
    let ast = parse_regex(pattern)?;
    let mut replacements = Vec::new();
    validate_and_collect(analyzer, policy, &ast, &mut budget, &mut replacements)?;
    let normalized = apply_replacements(pattern, replacements)?;
    if normalized.is_empty() {
        return Err(AnalysisError::EmptyTerm);
    }
    // Re-parse and re-validate the serialized output so normalization cannot produce a pattern
    // outside the approved subset. The already-normalized output is not mutated again.
    let reparsed = parse_regex(&normalized)?;
    let mut ignored = Vec::new();
    validate_and_collect(analyzer, policy, &reparsed, &mut budget, &mut ignored)?;
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

/// The term-shape transforms configured on the search pipeline, used to decide which regex
/// constructs can be normalized soundly.
#[derive(Debug, Clone, Copy)]
struct PatternPolicy {
    /// Any `Normalize`, `CaseFold` or `AsciiFold` that changes term bytes.
    transforms_terms: bool,
    /// A composing normalization (`NFC`/`NFKC`) is configured, so a combining mark can compose
    /// with a preceding starter across regex AST boundaries.
    composing_normalization: bool,
    /// A compatibility normalization (`NFKC`/`NFKD`) is configured.
    compatibility_normalization: bool,
    /// A full Unicode case-folding filter is configured, so a negated class's complement is not
    /// membership-stable (e.g. `[^a]` matches source `A`, but the folded term is `a`).
    case_folding: bool,
}

impl PatternPolicy {
    fn from_analyzer(analyzer: &AnalyzerDefinition) -> Self {
        let mut policy = Self {
            transforms_terms: false,
            composing_normalization: false,
            compatibility_normalization: false,
            case_folding: false,
        };
        for filter in analyzer.search_pipeline().token_filters() {
            match filter {
                TokenFilter::Normalize(form) => {
                    if *form != NormalizationForm::None {
                        policy.transforms_terms = true;
                    }
                    if matches!(form, NormalizationForm::Nfc | NormalizationForm::Nfkc) {
                        policy.composing_normalization = true;
                    }
                    if matches!(form, NormalizationForm::Nfkc | NormalizationForm::Nfkd) {
                        policy.compatibility_normalization = true;
                    }
                }
                TokenFilter::CaseFold => {
                    policy.transforms_terms = true;
                    policy.case_folding = true;
                }
                TokenFilter::AsciiFold => {
                    policy.transforms_terms = true;
                }
                TokenFilter::Stopwords(_) | TokenFilter::Stem(_) => {}
            }
        }
        policy
    }
}

fn validate_and_collect(
    analyzer: &AnalyzerDefinition,
    policy: PatternPolicy,
    ast: &Ast,
    budget: &mut WorkBudget<'_>,
    replacements: &mut Vec<LiteralReplacement>,
) -> Result<(), AnalysisError> {
    budget.check_cancelled()?;
    match ast {
        Ast::Empty(_) | Ast::Dot(_) | Ast::Assertion(_) => Ok(()),
        Ast::Flags(_) => Err(unsupported_regex(
            "inline regex flags are not supported; case handling is defined by the analyzer",
        )),
        Ast::Literal(literal) => process_literal_run(
            analyzer,
            &[literal],
            false,
            policy.composing_normalization,
            budget,
            replacements,
        ),
        Ast::ClassPerl(_) => {
            if policy.transforms_terms && policy.compatibility_normalization {
                Err(unsupported_regex(
                    "Perl character classes are not supported with compatibility normalization",
                ))
            } else {
                Ok(())
            }
        }
        Ast::ClassUnicode(_) => {
            if policy.transforms_terms {
                Err(unsupported_regex(
                    "Unicode property classes are not supported under term normalization",
                ))
            } else {
                Ok(())
            }
        }
        Ast::ClassBracketed(class) => {
            // A negated class matches the complement of its explicit members; under case folding
            // the complement is not membership-stable, so reject conservatively.
            if policy.case_folding && class.negated {
                return Err(unsupported_regex(
                    "a negated regex character class is not stable under case folding",
                ));
            }
            if policy.transforms_terms
                && !class_set_is_transform_stable(analyzer, policy, &class.kind, budget)?
            {
                return Err(unsupported_regex(
                    "regex character class is not stable under the configured term normalization",
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
            if let Ast::Literal(literal) = repetition.ast.as_ref() {
                process_quantified_literal(analyzer, literal, budget, replacements)
            } else {
                validate_and_collect(analyzer, policy, &repetition.ast, budget, replacements)
            }
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
            validate_and_collect(analyzer, policy, &group.ast, budget, replacements)
        }
        Ast::Alternation(alternation) => {
            for child in &alternation.asts {
                validate_and_collect(analyzer, policy, child, budget, replacements)?;
            }
            Ok(())
        }
        Ast::Concat(concat) => process_concat(analyzer, policy, concat, budget, replacements),
    }
}

/// Groups adjacent bare literal nodes in a concatenation into normalized runs.
///
/// A literal run is a maximal sequence of consecutive `Ast::Literal` children with no
/// intervening operator, group, class, anchor or quantified node. Composition/expansion is
/// applied to the decoded run as a whole and re-emitted as escaped literal scalars, so an
/// unquantified NFC composition (`e` + combining acute -> `é`) or case expansion (`Straße` ->
/// `strasse`) is preserved without changing operator scope.
fn process_concat(
    analyzer: &AnalyzerDefinition,
    policy: PatternPolicy,
    concat: &regex_syntax::ast::Concat,
    budget: &mut WorkBudget<'_>,
    replacements: &mut Vec<LiteralReplacement>,
) -> Result<(), AnalysisError> {
    let children = &concat.asts;
    let mut index = 0usize;
    while index < children.len() {
        if matches!(&children[index], Ast::Literal(_)) {
            let run_start = index;
            let mut run: Vec<&regex_syntax::ast::Literal> = Vec::new();
            while index < children.len() {
                match &children[index] {
                    Ast::Literal(literal) => {
                        run.push(literal.as_ref());
                        index += 1;
                    }
                    _ => break,
                }
            }
            process_literal_run(
                analyzer,
                &run,
                run_start > 0,
                policy.composing_normalization,
                budget,
                replacements,
            )?;
        } else {
            // A non-literal node (group/alternation/repetition) that can begin with a combining
            // mark and is preceded by another node could compose across the regex boundary.
            if index > 0 && policy.composing_normalization {
                let info = leading_info(analyzer, &children[index], budget)?;
                if info.may_start_with_combining {
                    return Err(unsupported_regex(
                        "a nested expression beginning with a combining mark could compose across a regex boundary",
                    ));
                }
            }
            validate_and_collect(analyzer, policy, &children[index], budget, replacements)?;
            index += 1;
        }
    }
    Ok(())
}

/// Applies the ordered pipeline to a decoded literal run and records one replacement.
///
/// `preceded` indicates the run has a preceding sibling expression; `composing_normalization`
/// indicates the configured pipeline can compose a leading combining mark with that sibling.
fn process_literal_run(
    analyzer: &AnalyzerDefinition,
    literals: &[&regex_syntax::ast::Literal],
    preceded: bool,
    composing_normalization: bool,
    budget: &mut WorkBudget<'_>,
    replacements: &mut Vec<LiteralReplacement>,
) -> Result<(), AnalysisError> {
    let Some(first) = literals.first() else {
        return Ok(());
    };
    let mut decoded = String::new();
    for literal in literals {
        decoded.push(literal.c);
    }
    let transformed = apply_pattern_transforms(analyzer, &decoded, budget)?;
    if transformed.is_empty() {
        return Err(unsupported_regex(
            "normalizing a regex literal run produced an empty literal",
        ));
    }
    // A preceded run must not begin with a combining mark when normalization can compose it with
    // the preceding matched character. This check uses the transformed output, so a literal that
    // normalizes into a leading combining mark is also caught.
    if preceded && composing_normalization && first_scalar_combining_class(&transformed) != 0 {
        return Err(unsupported_regex(
            "a combining mark following another expression could compose across the regex boundary",
        ));
    }
    if transformed == decoded {
        return Ok(());
    }
    let start = first.span.start.offset;
    let end = literals
        .last()
        .map(|literal| literal.span.end.offset)
        .unwrap_or(first.span.end.offset);
    let mut text = String::new();
    for ch in transformed.chars() {
        text.push_str(&escape_regex_literal(ch));
    }
    replacements.push(LiteralReplacement { start, end, text });
    Ok(())
}

/// Normalizes a literal directly governed by a quantifier without changing its scope.
fn process_quantified_literal(
    analyzer: &AnalyzerDefinition,
    literal: &regex_syntax::ast::Literal,
    budget: &mut WorkBudget<'_>,
    replacements: &mut Vec<LiteralReplacement>,
) -> Result<(), AnalysisError> {
    // A quantified combining mark may compose with a base matched before the quantifier.
    if canonical_combining_class(literal.c) != 0 {
        return Err(unsupported_regex(
            "a quantified combining mark could compose across the quantifier boundary",
        ));
    }
    let original = literal.c.to_string();
    let transformed = apply_pattern_transforms(analyzer, &original, budget)?;
    let mut chars = transformed.chars();
    let single = match (chars.next(), chars.next()) {
        (Some(single), None) => single,
        _ => {
            return Err(unsupported_regex(
                "normalizing a quantified regex literal would change quantifier scope",
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

fn first_scalar_combining_class(text: &str) -> u8 {
    text.chars()
        .next()
        .map(canonical_combining_class)
        .unwrap_or(0)
}

/// Conservative leading-character summary for a regex AST node.
#[derive(Debug, Clone, Copy)]
struct LeadingInfo {
    /// The node can match the empty string.
    nullable: bool,
    /// A nonempty match can begin with a scalar whose post-transform combining class is nonzero,
    /// or safety could not be proven.
    may_start_with_combining: bool,
}

/// Computes the nullable-aware leading-combining-mark summary for `node`.
///
/// `nullable` and `may_start_with_combining` are conservative: a `true` is always safe, and a
/// `false` is only returned when the property is proven for the configured transform pipeline.
fn leading_info(
    analyzer: &AnalyzerDefinition,
    node: &Ast,
    budget: &mut WorkBudget<'_>,
) -> Result<LeadingInfo, AnalysisError> {
    budget.check_cancelled()?;
    match node {
        Ast::Empty(_) | Ast::Assertion(_) => Ok(LeadingInfo {
            nullable: true,
            may_start_with_combining: false,
        }),
        Ast::Literal(literal) => {
            let transformed = apply_pattern_transforms(analyzer, &literal.c.to_string(), budget)?;
            Ok(LeadingInfo {
                nullable: false,
                may_start_with_combining: first_scalar_combining_class(&transformed) != 0,
            })
        }
        // A dot can match a combining scalar.
        Ast::Dot(_) => Ok(LeadingInfo {
            nullable: false,
            may_start_with_combining: true,
        }),
        // Perl and Unicode property class membership is not proven here.
        Ast::ClassPerl(_) | Ast::ClassUnicode(_) => Ok(LeadingInfo {
            nullable: false,
            may_start_with_combining: true,
        }),
        Ast::ClassBracketed(class) => Ok(LeadingInfo {
            nullable: false,
            // A negated class's complement can include combining scalars; the safe positive
            // set proved below says nothing about the complement.
            may_start_with_combining: class.negated
                || class_set_may_start_with_combining(analyzer, &class.kind, budget)?,
        }),
        Ast::Flags(_) => Ok(LeadingInfo {
            nullable: false,
            may_start_with_combining: true,
        }),
        Ast::Group(group) => leading_info(analyzer, &group.ast, budget),
        Ast::Repetition(repetition) => {
            let child = leading_info(analyzer, &repetition.ast, budget)?;
            let (nullable, can_repeat) = repetition_shape(&repetition.op.kind, child.nullable);
            Ok(LeadingInfo {
                nullable,
                may_start_with_combining: can_repeat && child.may_start_with_combining,
            })
        }
        Ast::Alternation(alternation) => {
            let mut info = LeadingInfo {
                nullable: false,
                may_start_with_combining: false,
            };
            for branch in &alternation.asts {
                let branch_info = leading_info(analyzer, branch, budget)?;
                info.nullable |= branch_info.nullable;
                info.may_start_with_combining |= branch_info.may_start_with_combining;
            }
            Ok(info)
        }
        Ast::Concat(concat) => {
            let mut nullable = true;
            let mut may_start_with_combining = false;
            for child in &concat.asts {
                if !nullable {
                    break;
                }
                let child_info = leading_info(analyzer, child, budget)?;
                may_start_with_combining |= child_info.may_start_with_combining;
                nullable = child_info.nullable;
            }
            Ok(LeadingInfo {
                nullable,
                may_start_with_combining,
            })
        }
    }
}

/// Returns `(nullable, can_repeat)` for a repetition operator given its child's nullability.
fn repetition_shape(kind: &RepetitionKind, child_nullable: bool) -> (bool, bool) {
    match kind {
        RepetitionKind::ZeroOrOne | RepetitionKind::ZeroOrMore => (true, true),
        RepetitionKind::OneOrMore => (child_nullable, true),
        RepetitionKind::Range(range) => match range {
            RepetitionRange::Exactly(count) => (*count == 0 || child_nullable, *count > 0),
            RepetitionRange::AtLeast(min) => (*min == 0 || child_nullable, true),
            RepetitionRange::Bounded(min, max) => {
                (*max == 0 || *min == 0 || child_nullable, *max > 0)
            }
        },
    }
}

/// Whether a bracketed class can match a scalar that begins (post-transform) with a combining
/// mark, or whether that cannot be proven with a bounded inspection.
fn class_set_may_start_with_combining(
    analyzer: &AnalyzerDefinition,
    set: &ClassSet,
    budget: &mut WorkBudget<'_>,
) -> Result<bool, AnalysisError> {
    match set {
        ClassSet::Item(item) => class_item_may_start_with_combining(analyzer, item, budget),
        // Intersection/difference/symmetric-difference membership is not proven here.
        ClassSet::BinaryOp(_) => Ok(true),
    }
}

fn class_item_may_start_with_combining(
    analyzer: &AnalyzerDefinition,
    item: &ClassSetItem,
    budget: &mut WorkBudget<'_>,
) -> Result<bool, AnalysisError> {
    match item {
        ClassSetItem::Empty(_) => Ok(false),
        ClassSetItem::Literal(literal) => {
            scalar_may_start_with_combining(analyzer, literal.c, budget)
        }
        ClassSetItem::Range(range) => range_may_start_with_combining(analyzer, range, budget),
        // A positive POSIX/ASCII class matches only ASCII scalars, which are transform-stable and
        // have combining class zero; a negated one can match combining scalars.
        ClassSetItem::Ascii(ascii) => Ok(ascii.negated),
        // Unicode property and Perl shorthand membership is not proven here.
        ClassSetItem::Unicode(_) | ClassSetItem::Perl(_) => Ok(true),
        ClassSetItem::Bracketed(inner) => {
            if inner.negated {
                Ok(true)
            } else {
                class_set_may_start_with_combining(analyzer, &inner.kind, budget)
            }
        }
        ClassSetItem::Union(union) => {
            for item in &union.items {
                if class_item_may_start_with_combining(analyzer, item, budget)? {
                    return Ok(true);
                }
            }
            Ok(false)
        }
    }
}

fn range_may_start_with_combining(
    analyzer: &AnalyzerDefinition,
    range: &regex_syntax::ast::ClassSetRange,
    budget: &mut WorkBudget<'_>,
) -> Result<bool, AnalysisError> {
    let start = u32::from(range.start.c);
    let end = u32::from(range.end.c);
    if end < start {
        return Ok(true);
    }
    if end - start + 1 > MAX_CLASS_RANGE_SCAN {
        return Ok(true);
    }
    let mut scalar = start;
    while scalar <= end {
        let ch = char::from_u32(scalar)
            .ok_or_else(|| unsupported_regex("invalid scalar in character class range"))?;
        if scalar_may_start_with_combining(analyzer, ch, budget)? {
            return Ok(true);
        }
        scalar += 1;
    }
    Ok(false)
}

fn scalar_may_start_with_combining(
    analyzer: &AnalyzerDefinition,
    c: char,
    budget: &mut WorkBudget<'_>,
) -> Result<bool, AnalysisError> {
    let transformed = apply_pattern_transforms(analyzer, &c.to_string(), budget)?;
    Ok(first_scalar_combining_class(&transformed) != 0)
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

/// Whether a bracketed character class matches the same set under the configured term
/// transforms. Ranges are checked over their whole (bounded) interior, not just endpoints.
fn class_set_is_transform_stable(
    analyzer: &AnalyzerDefinition,
    policy: PatternPolicy,
    set: &ClassSet,
    budget: &mut WorkBudget<'_>,
) -> Result<bool, AnalysisError> {
    match set {
        ClassSet::Item(item) => class_item_is_transform_stable(analyzer, policy, item, budget),
        ClassSet::BinaryOp(op) => Ok(class_set_is_transform_stable(
            analyzer, policy, &op.lhs, budget,
        )? && class_set_is_transform_stable(
            analyzer, policy, &op.rhs, budget,
        )?),
    }
}

fn class_item_is_transform_stable(
    analyzer: &AnalyzerDefinition,
    policy: PatternPolicy,
    item: &ClassSetItem,
    budget: &mut WorkBudget<'_>,
) -> Result<bool, AnalysisError> {
    match item {
        ClassSetItem::Empty(_) => Ok(true),
        ClassSetItem::Literal(literal) => literal_is_transform_stable(analyzer, literal.c, budget),
        ClassSetItem::Range(range) => range_is_transform_stable(analyzer, range, budget),
        // `[[:upper:]]` cannot match case-folded terms; the other ASCII classes include the
        // folded (lowercase) form. Compatibility normalization can move scalars in or out of a
        // POSIX class, so reject those conservatively.
        ClassSetItem::Ascii(ascii) => {
            if policy.case_folding && ascii.negated {
                return Ok(false);
            }
            Ok(!policy.compatibility_normalization && !matches!(ascii.kind, ClassAsciiKind::Upper))
        }
        // Unicode property classes may be case- or normalization-dependent.
        ClassSetItem::Unicode(_) => Ok(false),
        // `\d`/`\w`/`\s` and their negations are closed under case folding and NFC/NFD, but not
        // under compatibility normalization.
        ClassSetItem::Perl(_) => Ok(!policy.compatibility_normalization),
        ClassSetItem::Bracketed(inner) => {
            if policy.case_folding && inner.negated {
                return Ok(false);
            }
            class_set_is_transform_stable(analyzer, policy, &inner.kind, budget)
        }
        ClassSetItem::Union(union) => {
            for item in &union.items {
                if !class_item_is_transform_stable(analyzer, policy, item, budget)? {
                    return Ok(false);
                }
            }
            Ok(true)
        }
    }
}

/// Maximum number of scalars examined to prove a class range stable. Ranges larger than this
/// cannot be proven sound cheaply and are rejected conservatively.
const MAX_CLASS_RANGE_SCAN: u32 = 4096;

fn range_is_transform_stable(
    analyzer: &AnalyzerDefinition,
    range: &regex_syntax::ast::ClassSetRange,
    budget: &mut WorkBudget<'_>,
) -> Result<bool, AnalysisError> {
    let start = u32::from(range.start.c);
    let end = u32::from(range.end.c);
    if end < start {
        return Ok(false);
    }
    if end - start + 1 > MAX_CLASS_RANGE_SCAN {
        return Ok(false);
    }
    let mut scalar = start;
    while scalar <= end {
        let ch = char::from_u32(scalar)
            .ok_or_else(|| unsupported_regex("invalid scalar in character class range"))?;
        if !literal_is_transform_stable(analyzer, ch, budget)? {
            return Ok(false);
        }
        scalar += 1;
    }
    Ok(true)
}

fn literal_is_transform_stable(
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
    fn regex_unquantified_expansion_is_representable() {
        let analyzer = analyzer();
        let regex = prepare_regex(
            &analyzer,
            "Straße",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .expect("regex");
        assert_eq!(regex.pattern(), "strasse");
        let regex = prepare_regex(
            &analyzer,
            "Straße+",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .expect("regex");
        assert_eq!(regex.pattern(), "strasse+");
    }

    #[test]
    fn regex_quantified_expansion_is_rejected() {
        let analyzer = analyzer();
        assert!(matches!(
            prepare_regex(&analyzer, "ß+", &AnalysisLimits::default(), &NeverCancel),
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
