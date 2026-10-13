//! The token data model (T01, T02, T04).

use super::error::AnalysisError;

/// A single analyzed token.
///
/// The term is UTF-8 (T01). `value_index` identifies which field value produced the token,
/// while `start_offset`/`end_offset` are UTF-8 byte offsets **within that source value**
/// (T02) — never fabricated positions in an imaginary concatenation, and never offsets into
/// a normalized/transformed string (T04). Positions are absolute across the whole field,
/// with stopword holes preserved.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Token {
    term: Box<str>,
    value_index: u32,
    position: u32,
    position_increment: u32,
    position_length: u32,
    start_offset: u32,
    end_offset: u32,
}

impl Token {
    /// Builds and validates a token.
    ///
    /// Does not check offsets against a specific source value; use
    /// [`Token::validate_against`] for that boundary check.
    pub fn new(
        term: impl Into<Box<str>>,
        value_index: u32,
        position: u32,
        position_increment: u32,
        position_length: u32,
        start_offset: u32,
        end_offset: u32,
    ) -> Result<Self, AnalysisError> {
        let token = Self {
            term: term.into(),
            value_index,
            position,
            position_increment,
            position_length,
            start_offset,
            end_offset,
        };
        token.validate()?;
        Ok(token)
    }

    fn validate(&self) -> Result<(), AnalysisError> {
        if self.term.is_empty() {
            return Err(AnalysisError::InvalidToken {
                reason: "term must not be empty".to_owned(),
            });
        }
        if self.position_increment == 0 {
            return Err(AnalysisError::InvalidToken {
                reason: "position_increment must be positive".to_owned(),
            });
        }
        if self.position_length == 0 {
            return Err(AnalysisError::InvalidToken {
                reason: "position_length must be positive".to_owned(),
            });
        }
        if self.start_offset > self.end_offset {
            return Err(AnalysisError::InvalidOffset {
                reason: "start_offset must not exceed end_offset".to_owned(),
            });
        }
        Ok(())
    }

    /// Verifies the token's source span is a valid UTF-8 boundary range inside `value`.
    pub fn validate_against(&self, value: &str) -> Result<(), AnalysisError> {
        let len = u32::try_from(value.len()).map_err(|_| AnalysisError::OffsetOverflow)?;
        if self.end_offset > len {
            return Err(AnalysisError::InvalidOffset {
                reason: format!(
                    "end_offset {} exceeds source value length {len}",
                    self.end_offset
                ),
            });
        }
        for (label, offset) in [
            ("start_offset", self.start_offset),
            ("end_offset", self.end_offset),
        ] {
            if !value.is_char_boundary(offset as usize) {
                return Err(AnalysisError::InvalidOffset {
                    reason: format!("{label} {offset} is not a UTF-8 boundary"),
                });
            }
        }
        Ok(())
    }

    /// The normalized/indexed term bytes as UTF-8.
    #[must_use]
    pub fn term(&self) -> &str {
        &self.term
    }

    /// Index of the source field value this token came from.
    #[must_use]
    pub const fn value_index(&self) -> u32 {
        self.value_index
    }

    /// Absolute position within the field.
    #[must_use]
    pub const fn position(&self) -> u32 {
        self.position
    }

    /// Position increment relative to the previous retained token.
    #[must_use]
    pub const fn position_increment(&self) -> u32 {
        self.position_increment
    }

    /// Number of positions the token spans (always 1 in PR 4).
    #[must_use]
    pub const fn position_length(&self) -> u32 {
        self.position_length
    }

    /// Start byte offset within the source value.
    #[must_use]
    pub const fn start_offset(&self) -> u32 {
        self.start_offset
    }

    /// End byte offset (exclusive) within the source value.
    #[must_use]
    pub const fn end_offset(&self) -> u32 {
        self.end_offset
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn valid_token_round_trips() {
        let token = Token::new("héllo", 0, 3, 2, 1, 1, 7).expect("valid");
        assert_eq!(token.term(), "héllo");
        assert_eq!(token.value_index(), 0);
        assert_eq!(token.position(), 3);
        assert_eq!(token.position_increment(), 2);
        assert_eq!(token.position_length(), 1);
        assert_eq!(token.start_offset(), 1);
        assert_eq!(token.end_offset(), 7);
        token.validate_against("a héllo b").expect("boundaries");
    }

    #[test]
    fn empty_term_is_rejected() {
        assert!(Token::new("", 0, 0, 1, 1, 0, 0).is_err());
    }

    #[test]
    fn zero_increments_are_rejected() {
        assert!(Token::new("a", 0, 0, 0, 1, 0, 1).is_err());
        assert!(Token::new("a", 0, 0, 1, 0, 0, 1).is_err());
    }

    #[test]
    fn reversed_offsets_are_rejected() {
        assert!(Token::new("a", 0, 0, 1, 1, 2, 1).is_err());
    }

    #[test]
    fn non_boundary_offsets_are_rejected() {
        // "é" is two UTF-8 bytes; offset 1 is inside the code point.
        let token = Token::new("e", 0, 0, 1, 1, 0, 1).expect("valid shape");
        assert!(token.validate_against("é").is_err());
    }

    #[test]
    fn offset_beyond_value_is_rejected() {
        let token = Token::new("a", 0, 0, 1, 1, 0, 5).expect("valid shape");
        assert!(token.validate_against("ab").is_err());
    }
}
