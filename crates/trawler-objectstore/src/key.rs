//! Provider-neutral object key grammar.
//!
//! The grammar is intentionally strict and mirrors the local [`StorageKey`]
//! grammar approved in PR 3 decision S01/S10:
//!
//! - non-empty, at most [`MAX_KEY_BYTES`] bytes, valid UTF-8;
//! - `/`-separated components, each non-empty;
//! - no `.` or `..` components, no NUL, no backslash, no `:`, no control
//!   characters, no leading or trailing `/`.
//!
//! Object keys and local storage keys are distinct types ([`ObjectKey`] versus
//! `trawler_core::storage::StorageKey`) even though they share grammar.

use std::fmt;

/// Maximum accepted key length in bytes.
pub const MAX_KEY_BYTES: usize = 1024;

/// Why a candidate key was rejected.
///
/// Shared by [`ObjectKey`] and by the local storage key type.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum KeyError {
    /// The key was empty.
    Empty,
    /// The key exceeded [`MAX_KEY_BYTES`].
    TooLong,
    /// The key contained a NUL byte.
    NulByte,
    /// The key contained a backslash.
    Backslash,
    /// The key began with `/` (absolute) or otherwise tried to escape.
    AbsolutePath,
    /// The key ended with `/`.
    TrailingSlash,
    /// The key contained an empty component (`a//b`).
    EmptyComponent,
    /// The key contained a `..` component.
    ParentDirectory,
    /// The key contained a `.` component.
    CurrentDirectory,
    /// The key contained an ASCII control character.
    ControlCharacter,
    /// The key contained a reserved character (currently `:`).
    ReservedCharacter,
    /// A filesystem component resolved to a symbolic link.
    SymlinkComponent,
}

impl fmt::Display for KeyError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let msg = match self {
            Self::Empty => "key is empty",
            Self::TooLong => "key exceeds the maximum length",
            Self::NulByte => "key contains a NUL byte",
            Self::Backslash => "key contains a backslash",
            Self::AbsolutePath => "key must be a relative path",
            Self::TrailingSlash => "key must not end with a slash",
            Self::EmptyComponent => "key contains an empty path component",
            Self::ParentDirectory => "key contains a parent-directory component",
            Self::CurrentDirectory => "key contains a current-directory component",
            Self::ControlCharacter => "key contains a control character",
            Self::ReservedCharacter => "key contains a reserved character",
            Self::SymlinkComponent => "key resolves through a symbolic link",
        };
        f.write_str(msg)
    }
}

impl std::error::Error for KeyError {}

/// Validate a relative `/`-separated key against the PR 3 grammar.
///
/// Validation performs no I/O and has no side effects.
pub fn validate_key(key: &str) -> Result<(), KeyError> {
    if key.is_empty() {
        return Err(KeyError::Empty);
    }
    if key.len() > MAX_KEY_BYTES {
        return Err(KeyError::TooLong);
    }
    if key.starts_with('/') {
        return Err(KeyError::AbsolutePath);
    }
    if key.ends_with('/') {
        return Err(KeyError::TrailingSlash);
    }
    if key.contains('\0') {
        return Err(KeyError::NulByte);
    }
    if key.contains('\\') {
        return Err(KeyError::Backslash);
    }
    if key.contains(':') {
        return Err(KeyError::ReservedCharacter);
    }
    for ch in key.chars() {
        if ch.is_control() {
            return Err(KeyError::ControlCharacter);
        }
    }
    for component in key.split('/') {
        if component.is_empty() {
            return Err(KeyError::EmptyComponent);
        }
        if component == "." {
            return Err(KeyError::CurrentDirectory);
        }
        if component == ".." {
            return Err(KeyError::ParentDirectory);
        }
    }
    Ok(())
}

/// A validated, opaque object key.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ObjectKey(String);

impl ObjectKey {
    /// Parse and validate an object key.
    pub fn parse(key: impl Into<String>) -> Result<Self, KeyError> {
        let key = key.into();
        validate_key(&key)?;
        Ok(Self(key))
    }

    /// The key as a string slice.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for ObjectKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl TryFrom<&str> for ObjectKey {
    type Error = KeyError;
    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

impl TryFrom<String> for ObjectKey {
    type Error = KeyError;
    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_relative_keys() {
        for key in ["foo/bar", "a", "indexes/idx/shards/0", "Δ/한글"] {
            assert!(ObjectKey::parse(key).is_ok(), "{key} should be accepted");
        }
    }

    #[test]
    fn key_round_trips_exactly() {
        let key = ObjectKey::parse("a/Δ").unwrap();
        assert_eq!(key.as_str(), "a/Δ");
        assert_eq!(key.to_string(), "a/Δ");
    }

    #[test]
    fn rejects_invalid_keys() {
        assert_eq!(ObjectKey::parse(""), Err(KeyError::Empty));
        assert_eq!(ObjectKey::parse("/abs"), Err(KeyError::AbsolutePath));
        assert_eq!(ObjectKey::parse("a/"), Err(KeyError::TrailingSlash));
        assert_eq!(ObjectKey::parse("a//b"), Err(KeyError::EmptyComponent));
        assert_eq!(ObjectKey::parse("a/../b"), Err(KeyError::ParentDirectory));
        assert_eq!(ObjectKey::parse("./a"), Err(KeyError::CurrentDirectory));
        assert_eq!(
            ObjectKey::parse("a/b.."),
            Ok(ObjectKey::parse("a/b..").unwrap())
        );
        assert_eq!(ObjectKey::parse("a\0b"), Err(KeyError::NulByte));
        assert_eq!(ObjectKey::parse("a\\b"), Err(KeyError::Backslash));
        assert_eq!(ObjectKey::parse("a:b"), Err(KeyError::ReservedCharacter));
        assert_eq!(ObjectKey::parse("a\nb"), Err(KeyError::ControlCharacter));
        assert_eq!(
            ObjectKey::parse("x".repeat(MAX_KEY_BYTES + 1)),
            Err(KeyError::TooLong)
        );
    }

    #[test]
    fn key_error_displays() {
        assert!(!KeyError::Empty.to_string().is_empty());
        assert!(!KeyError::SymlinkComponent.to_string().is_empty());
    }
}
