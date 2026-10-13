//! Explicit, provider-neutral capability discovery.
//!
//! PR 3 decision S09: capabilities are never assumed true, and a missing
//! capability fails closed. Capabilities describe provider/protocol behavior
//! only; they are not application durability, writer leadership, or fencing
//! promises.

/// Capabilities an [`ObjectStore`](crate::ObjectStore) adapter actually provides.
///
/// The default is "no capabilities": an adapter must opt in explicitly.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[non_exhaustive]
pub struct ObjectStoreCapabilities {
    /// Atomic create-if-absent (`If-None-Match: *` / create-new).
    ///
    /// A `HEAD` followed by `PUT` is **not** atomic create-if-absent.
    pub atomic_create_if_absent: bool,
    /// Atomic conditional replace/compare-and-swap (`If-Match`).
    ///
    /// Reserved for future manifest publication and writer fencing (PR 6/13);
    /// it is not permission to mutate immutable segment objects.
    pub conditional_replace: bool,
    /// Provider guarantees read-after-write visibility.
    pub read_after_write: bool,
    /// Provider supports exact ranged reads.
    pub range_read: bool,
    /// Provider supports listing.
    ///
    /// Listing is never used as a publication primitive in PR 3.
    pub list: bool,
}

impl ObjectStoreCapabilities {
    /// No capabilities at all.
    pub const NONE: Self = Self {
        atomic_create_if_absent: false,
        conditional_replace: false,
        read_after_write: false,
        range_read: false,
        list: false,
    };

    /// The baseline immutable-object capability set assumed by the fake.
    pub const IMMUTABLE_BASELINE: Self = Self {
        atomic_create_if_absent: true,
        conditional_replace: false,
        read_after_write: true,
        range_read: true,
        list: false,
    };

    /// Return these capabilities with atomic create-if-absent set.
    #[must_use]
    pub const fn with_atomic_create_if_absent(mut self, value: bool) -> Self {
        self.atomic_create_if_absent = value;
        self
    }

    /// Return these capabilities with conditional replace set.
    #[must_use]
    pub const fn with_conditional_replace(mut self, value: bool) -> Self {
        self.conditional_replace = value;
        self
    }

    /// Return these capabilities with read-after-write set.
    #[must_use]
    pub const fn with_read_after_write(mut self, value: bool) -> Self {
        self.read_after_write = value;
        self
    }

    /// Return these capabilities with ranged reads set.
    #[must_use]
    pub const fn with_range_read(mut self, value: bool) -> Self {
        self.range_read = value;
        self
    }

    /// Return these capabilities with listing set.
    #[must_use]
    pub const fn with_list(mut self, value: bool) -> Self {
        self.list = value;
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_is_none() {
        assert_eq!(
            ObjectStoreCapabilities::default(),
            ObjectStoreCapabilities::NONE
        );
        assert!(!ObjectStoreCapabilities::default().atomic_create_if_absent);
    }

    #[test]
    fn baseline_flags() {
        let caps = ObjectStoreCapabilities::IMMUTABLE_BASELINE;
        assert!(caps.atomic_create_if_absent);
        assert!(!caps.conditional_replace);
        assert!(caps.read_after_write);
        assert!(caps.range_read);
        assert!(!caps.list);
    }

    #[test]
    fn builders_set_exact_flags() {
        let caps = ObjectStoreCapabilities::NONE
            .with_atomic_create_if_absent(true)
            .with_conditional_replace(true)
            .with_read_after_write(true)
            .with_range_read(true)
            .with_list(true);
        assert!(caps.atomic_create_if_absent);
        assert!(caps.conditional_replace);
        assert!(caps.read_after_write);
        assert!(caps.range_read);
        assert!(caps.list);
    }
}
