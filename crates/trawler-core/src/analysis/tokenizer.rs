//! Tokenizers (T03).
//!
//! All tokenizers return source-value-relative UTF-8 byte spans. None of them transform the
//! source text, so offsets are always original-input offsets.

use unicode_segmentation::UnicodeSegmentation;

use super::config::TokenizerKind;
use super::error::AnalysisError;
use super::work::WorkBudget;

/// A source-value-relative byte span.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Span {
    pub(crate) start: usize,
    pub(crate) end: usize,
}

impl Span {
    fn new(start: usize, end: usize) -> Self {
        Self { start, end }
    }
}

/// Tokenizes `value`, charging work and polling cancellation.
pub(crate) fn tokenize(
    kind: TokenizerKind,
    value: &str,
    budget: &mut WorkBudget<'_>,
) -> Result<Vec<Span>, AnalysisError> {
    // One unit per Unicode scalar value bounds tokenizer cost deterministically.
    let scalars = u64::try_from(value.chars().count()).unwrap_or(u64::MAX);
    budget.charge(scalars)?;
    match kind {
        TokenizerKind::Keyword => Ok(tokenize_keyword(value)),
        TokenizerKind::Whitespace => Ok(tokenize_whitespace(value)),
        TokenizerKind::UnicodeWord => Ok(tokenize_unicode_word(value)),
    }
}

fn tokenize_keyword(value: &str) -> Vec<Span> {
    if value.is_empty() {
        Vec::new()
    } else {
        vec![Span::new(0, value.len())]
    }
}

fn tokenize_whitespace(value: &str) -> Vec<Span> {
    let mut spans = Vec::new();
    let mut start: Option<usize> = None;
    for (offset, ch) in value.char_indices() {
        if ch.is_whitespace() {
            if let Some(begin) = start.take() {
                spans.push(Span::new(begin, offset));
            }
        } else if start.is_none() {
            start = Some(offset);
        }
    }
    if let Some(begin) = start {
        spans.push(Span::new(begin, value.len()));
    }
    spans
}

fn tokenize_unicode_word(value: &str) -> Vec<Span> {
    value
        .unicode_word_indices()
        .map(|(offset, word)| Span::new(offset, offset + word.len()))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::cancellation::NeverCancel;

    fn spans(kind: TokenizerKind, value: &str) -> Vec<(usize, usize)> {
        let mut budget = WorkBudget::new(1_000_000, &NeverCancel);
        tokenize(kind, value, &mut budget)
            .expect("tokenization")
            .into_iter()
            .map(|s| (s.start, s.end))
            .collect()
    }

    #[test]
    fn keyword_is_whole_input_or_empty() {
        assert_eq!(spans(TokenizerKind::Keyword, "héllo wörld"), vec![(0, 13)]);
        assert!(spans(TokenizerKind::Keyword, "").is_empty());
    }

    #[test]
    fn whitespace_splits_on_unicode_whitespace() {
        assert_eq!(
            spans(TokenizerKind::Whitespace, "  a\tb\u{00a0}c "),
            vec![(2, 3), (4, 5), (7, 8)]
        );
    }

    #[test]
    fn unicode_word_uses_uax29_words() {
        assert_eq!(
            spans(TokenizerKind::UnicodeWord, "The quick (\"brown\") fox"),
            vec![(0, 3), (4, 9), (12, 17), (20, 23)]
        );
    }

    #[test]
    fn unicode_word_keeps_multibyte_boundaries() {
        let value = "café—naïve";
        let result = spans(TokenizerKind::UnicodeWord, value);
        assert_eq!(result.len(), 2);
        for (start, end) in result {
            assert!(value.is_char_boundary(start));
            assert!(value.is_char_boundary(end));
        }
    }
}
