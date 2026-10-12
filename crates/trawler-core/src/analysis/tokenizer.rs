//! Tokenizers (T03).
//!
//! All tokenizers are **lazy**: they yield source-value-relative UTF-8 byte spans one at a time
//! and never materialize an entire value. None of them transform the source text, so offsets are
//! always original-input offsets.
//!
//! Work is charged incrementally as each span is scanned (one unit per Unicode scalar value,
//! including skipped whitespace/punctuation), so cancellation is polled at deterministic
//! boundaries even for large values with few tokens.

use unicode_segmentation::{UnicodeSegmentation, UnicodeWordIndices};

use super::config::TokenizerKind;
use super::error::AnalysisError;
use super::work::WorkBudget;

/// A source-value-relative byte span.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Span {
    pub(crate) start: usize,
    pub(crate) end: usize,
}

/// A lazy, fallible span iterator for one tokenizer over one source value.
pub(crate) enum SpanCursor<'a> {
    Keyword { value: &'a str, done: bool },
    Whitespace(WhitespaceCursor<'a>),
    UnicodeWord(UnicodeWordCursor<'a>),
}

impl<'a> SpanCursor<'a> {
    pub(crate) fn new(kind: TokenizerKind, value: &'a str) -> Self {
        match kind {
            TokenizerKind::Keyword => Self::Keyword { value, done: false },
            TokenizerKind::Whitespace => Self::Whitespace(WhitespaceCursor::new(value)),
            TokenizerKind::UnicodeWord => Self::UnicodeWord(UnicodeWordCursor::new(value)),
        }
    }

    /// Returns the next span, charging work for scanned scalars and polling cancellation.
    pub(crate) fn next_span(
        &mut self,
        budget: &mut WorkBudget<'_>,
    ) -> Result<Option<Span>, AnalysisError> {
        match self {
            Self::Keyword { value, done } => {
                if *done {
                    return Ok(None);
                }
                *done = true;
                if value.is_empty() {
                    return Ok(None);
                }
                budget.charge(u64::try_from(value.chars().count()).unwrap_or(u64::MAX))?;
                Ok(Some(Span {
                    start: 0,
                    end: value.len(),
                }))
            }
            Self::Whitespace(cursor) => cursor.next_span(budget),
            Self::UnicodeWord(cursor) => cursor.next_span(budget),
        }
    }
}

/// Lazy whitespace tokenizer over `char_indices`.
pub(crate) struct WhitespaceCursor<'a> {
    value: &'a str,
    chars: std::str::CharIndices<'a>,
    current: Option<usize>,
    finished: bool,
}

impl<'a> WhitespaceCursor<'a> {
    fn new(value: &'a str) -> Self {
        Self {
            value,
            chars: value.char_indices(),
            current: None,
            finished: false,
        }
    }

    fn next_span(&mut self, budget: &mut WorkBudget<'_>) -> Result<Option<Span>, AnalysisError> {
        if self.finished {
            return Ok(None);
        }
        loop {
            match self.chars.next() {
                Some((offset, ch)) => {
                    budget.charge(1)?;
                    if ch.is_whitespace() {
                        if let Some(start) = self.current.take() {
                            return Ok(Some(Span { start, end: offset }));
                        }
                    } else if self.current.is_none() {
                        self.current = Some(offset);
                    }
                }
                None => {
                    self.finished = true;
                    if let Some(start) = self.current.take() {
                        return Ok(Some(Span {
                            start,
                            end: self.value.len(),
                        }));
                    }
                    return Ok(None);
                }
            }
        }
    }
}

/// Lazy UAX #29 word tokenizer.
pub(crate) struct UnicodeWordCursor<'a> {
    value: &'a str,
    words: UnicodeWordIndices<'a>,
    last_end: usize,
    finished: bool,
}

impl<'a> UnicodeWordCursor<'a> {
    fn new(value: &'a str) -> Self {
        Self {
            value,
            words: value.unicode_word_indices(),
            last_end: 0,
            finished: false,
        }
    }

    fn next_span(&mut self, budget: &mut WorkBudget<'_>) -> Result<Option<Span>, AnalysisError> {
        if self.finished {
            return Ok(None);
        }
        match self.words.next() {
            Some((offset, word)) => {
                let skipped = self.value[self.last_end..offset].chars().count();
                let word_scalars = word.chars().count();
                budget.charge(
                    u64::try_from(skipped.saturating_add(word_scalars)).unwrap_or(u64::MAX),
                )?;
                let start = offset;
                let end = offset + word.len();
                self.last_end = end;
                Ok(Some(Span { start, end }))
            }
            None => {
                let trailing = self.value[self.last_end..].chars().count();
                budget.charge(u64::try_from(trailing).unwrap_or(u64::MAX))?;
                self.finished = true;
                Ok(None)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::cancellation::NeverCancel;

    fn spans(kind: TokenizerKind, value: &str) -> Vec<(usize, usize)> {
        let mut budget = WorkBudget::new(1_000_000, &NeverCancel);
        let mut cursor = SpanCursor::new(kind, value);
        let mut result = Vec::new();
        while let Some(span) = cursor.next_span(&mut budget).expect("tokenization") {
            result.push((span.start, span.end));
        }
        result
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

    #[test]
    fn cursor_is_pull_based_and_terminates() {
        let mut budget = WorkBudget::new(1_000_000, &NeverCancel);
        let mut cursor = SpanCursor::new(TokenizerKind::UnicodeWord, "one two three");
        assert_eq!(
            cursor
                .next_span(&mut budget)
                .expect("span")
                .map(|s| (s.start, s.end)),
            Some((0, 3))
        );
        assert_eq!(
            cursor
                .next_span(&mut budget)
                .expect("span")
                .map(|s| (s.start, s.end)),
            Some((4, 7))
        );
        assert_eq!(
            cursor
                .next_span(&mut budget)
                .expect("span")
                .map(|s| (s.start, s.end)),
            Some((8, 13))
        );
        assert!(cursor.next_span(&mut budget).expect("eof").is_none());
        assert!(cursor.next_span(&mut budget).expect("eof again").is_none());
    }
}
