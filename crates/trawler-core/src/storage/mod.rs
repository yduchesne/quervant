//! Local storage contracts and adapters (PR 3).
//!
//! This module defines the local [`Directory`] seam, its memory and filesystem
//! backends, the immutable [`SegmentStore`] identity seam, and the bounded,
//! verified [`SegmentCache`]. It deliberately does **not** define a segment
//! codec, manifest, CURRENT pointer, writer, reader, or query executor.
//!
//! The only external dependency is the provider-neutral
//! `trawler-objectstore` crate; there is no distributed dependency, no runtime
//! requirement, and no unsafe code.

pub mod cache;
pub mod directory;
pub mod error;
pub mod fs;
pub mod key;
pub mod memory;
pub mod segment;

pub use cache::{CacheConfig, CacheStats, PinnedSegment, SegmentCache};
pub use directory::{Directory, ReadHandle, WriteHandle};
pub use error::{CorruptionKind, StorageError, StorageOp};
pub use fs::FsDirectory;
pub use key::{KeyError, StorageKey};
pub use memory::MemoryDirectory;
pub use segment::{SegmentDescriptor, SegmentId, SegmentStore, StaticSegmentStore};
