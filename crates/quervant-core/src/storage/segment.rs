//! Immutable segment identity and authoritative descriptor seam.
//!
//! PR 3 defines only the ownership boundary between [`SegmentStore`] (logical
//! identity -> authoritative descriptor) and `SegmentCache` (local
//! materialization). No segment codec, manifest, generation or CURRENT format
//! is created here.

use std::collections::HashMap;
use std::fmt;
use std::future::Future;

use quervant_objectstore::{ContentDescriptor, ObjectKey};

use super::{StorageError, StorageKey};

/// An opaque logical segment identity.
///
/// PR 3 uses this only for tests and seam verification; it is explicitly **not**
/// a committed on-disk format.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct SegmentId(StorageKey);

impl SegmentId {
    /// Construct a segment identity.
    pub fn new(id: impl Into<String>) -> Result<Self, StorageError> {
        StorageKey::parse(id).map(Self)
    }

    /// The identity as a string slice.
    #[must_use]
    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }

    pub(crate) fn storage_key(&self) -> &StorageKey {
        &self.0
    }
}

impl fmt::Display for SegmentId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// The authoritative location and content identity of a segment.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SegmentDescriptor {
    /// The remote object key that holds the bytes.
    pub object_key: ObjectKey,
    /// The immutable content identity of those bytes.
    pub content: ContentDescriptor,
}

impl SegmentDescriptor {
    /// Construct a descriptor.
    #[must_use]
    pub fn new(object_key: ObjectKey, content: ContentDescriptor) -> Self {
        Self {
            object_key,
            content,
        }
    }
}

/// Maps a logical immutable segment identity to its authoritative descriptor.
///
/// It performs no caching and no codec work.
pub trait SegmentStore: Send + Sync {
    /// Describe the segment with the given identity.
    fn describe(
        &self,
        id: &SegmentId,
    ) -> impl Future<Output = Result<SegmentDescriptor, StorageError>> + Send;
}

/// A deterministic in-memory [`SegmentStore`] for tests and cache seams.
#[derive(Debug, Default)]
pub struct StaticSegmentStore {
    entries: HashMap<SegmentId, SegmentDescriptor>,
}

impl StaticSegmentStore {
    /// Create an empty store.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Register a descriptor.
    pub fn insert(&mut self, id: SegmentId, descriptor: SegmentDescriptor) {
        self.entries.insert(id, descriptor);
    }
}

impl SegmentStore for StaticSegmentStore {
    fn describe(
        &self,
        id: &SegmentId,
    ) -> impl Future<Output = Result<SegmentDescriptor, StorageError>> + Send {
        let result = self
            .entries
            .get(id)
            .cloned()
            .ok_or_else(|| StorageError::NotFound {
                key: id.storage_key().clone(),
            });
        async move { result }
    }
}

#[cfg(test)]
mod tests {
    use std::future::Future;

    use quervant_objectstore::{ContentDescriptor, ObjectKey};

    use super::*;

    fn simple_block_on<F: Future>(future: F) -> F::Output {
        use std::task::{Context, Poll};
        let mut context = Context::from_waker(std::task::Waker::noop());
        let mut future = Box::pin(future);
        loop {
            match future.as_mut().poll(&mut context) {
                Poll::Ready(value) => return value,
                Poll::Pending => std::thread::yield_now(),
            }
        }
    }

    #[test]
    fn static_store_describes_and_reports_missing() {
        let mut store = StaticSegmentStore::new();
        let id = SegmentId::new("seg/1").unwrap();
        let object_key = ObjectKey::parse("objects/seg-1").unwrap();
        let content = ContentDescriptor::of(b"blob");
        store.insert(
            id.clone(),
            SegmentDescriptor::new(object_key.clone(), content),
        );
        let descriptor = simple_block_on(store.describe(&id)).unwrap();
        assert_eq!(descriptor.object_key, object_key);
        assert_eq!(descriptor.content, content);
        assert!(descriptor.content.matches(b"blob"));
        assert_eq!(id.to_string(), "seg/1");

        let missing = SegmentId::new("seg/2").unwrap();
        assert!(matches!(
            simple_block_on(store.describe(&missing)),
            Err(StorageError::NotFound { .. })
        ));
    }

    #[test]
    fn segment_id_validates() {
        assert!(SegmentId::new("seg/1").is_ok());
        assert!(SegmentId::new("../seg").is_err());
    }
}
