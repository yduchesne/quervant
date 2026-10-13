//! Validated local storage keys.
//!
//! A [`StorageKey`] is a relative, `/`-separated, UTF-8 path-like identifier.
//! It shares the provider-neutral grammar validated by
//! [`quervant_objectstore::validate_key`] but is a distinct type from
//! `ObjectKey`: local cache keys and remote object keys are never
//! interchangeable (PR 3 invariant 8).

use std::fmt;

pub use quervant_objectstore::KeyError;

use super::StorageError;

/// Maximum accepted key length in bytes.
pub const MAX_STORAGE_KEY_BYTES: usize = quervant_objectstore::MAX_KEY_BYTES;

/// A validated relative storage key.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct StorageKey(String);

impl StorageKey {
    /// Parse and validate a storage key.
    ///
    /// Validation happens before any I/O and has no side effects.
    pub fn parse(key: impl Into<String>) -> Result<Self, StorageError> {
        let key = key.into();
        quervant_objectstore::validate_key(&key)
            .map_err(|reason| StorageError::InvalidKey { reason })?;
        Ok(Self(key))
    }

    /// The key as a string slice.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// The `/`-separated components.
    pub fn components(&self) -> impl Iterator<Item = &str> {
        self.0.split('/')
    }

    /// The parent key, if this key has a parent component.
    #[must_use]
    pub fn parent(&self) -> Option<Self> {
        self.0
            .rsplit_once('/')
            .map(|(parent, _)| Self(parent.to_string()))
    }

    /// The final component.
    #[must_use]
    pub fn file_name(&self) -> &str {
        self.0.rsplit('/').next().unwrap_or(&self.0)
    }
}

impl fmt::Display for StorageKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl TryFrom<&str> for StorageKey {
    type Error = StorageError;
    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

impl TryFrom<String> for StorageKey {
    type Error = StorageError;
    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn valid_keys_round_trip() {
        let key = StorageKey::parse("foo/bar").unwrap();
        assert_eq!(key.as_str(), "foo/bar");
        assert_eq!(key.file_name(), "bar");
        assert_eq!(key.parent().unwrap().as_str(), "foo");
        assert_eq!(key.components().collect::<Vec<_>>(), vec!["foo", "bar"]);
        assert!(StorageKey::parse("top").unwrap().parent().is_none());
        assert_eq!(key.to_string(), "foo/bar");
    }

    #[test]
    fn invalid_keys_are_rejected() {
        assert!(matches!(
            StorageKey::parse("../x"),
            Err(StorageError::InvalidKey {
                reason: KeyError::ParentDirectory
            })
        ));
        assert!(matches!(
            StorageKey::parse("/abs"),
            Err(StorageError::InvalidKey {
                reason: KeyError::AbsolutePath
            })
        ));
    }

    #[test]
    fn try_from_conversions() {
        assert!(StorageKey::try_from("a/b").is_ok());
        assert!(StorageKey::try_from("a/b".to_string()).is_ok());
        assert!(StorageKey::try_from("../").is_err());
    }
}
