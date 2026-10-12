//! The local [`Directory`] contract and its owned handle traits.

use super::{StorageError, StorageKey};

/// An owned, immutable, positional read handle.
///
/// Handles are owned trait objects so they never borrow the directory and
/// cannot dangle when the backend changes.
pub trait ReadHandle: Send {
    /// Total length of the file in bytes.
    fn len(&self) -> u64;

    /// Whether the file is empty.
    fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Read up to `buf.len()` bytes starting at `offset`.
    ///
    /// Returns the number of bytes read. At or beyond EOF the result is `Ok(0)`
    /// and no bytes are ever invented.
    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, StorageError>;
}

/// An owned write handle for a file created with [`Directory::create`].
pub trait WriteHandle: Send {
    /// Append all bytes to the file.
    fn write_all(&mut self, buf: &[u8]) -> Result<(), StorageError>;

    /// Synchronize file data to durable storage.
    ///
    /// `create` alone is not a durability acknowledgement; this is the explicit
    /// barrier.
    fn sync_all(&mut self) -> Result<(), StorageError>;
}

/// A logical local store of named immutable files.
///
/// `Directory` separates local file lifecycle from a concrete filesystem. It is
/// a coarse-grained `dyn`-friendly boundary and is not confused with the remote
/// `ObjectStore` contract.
pub trait Directory: Send + Sync {
    /// Create a new file, failing if the key already exists.
    fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError>;

    /// Open an existing file for immutable positional reads.
    fn open_read(&self, key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError>;

    /// Whether the key currently exists.
    fn exists(&self, key: &StorageKey) -> Result<bool, StorageError>;

    /// Delete a file. Deleting an absent key succeeds (idempotent).
    fn delete(&self, key: &StorageKey) -> Result<(), StorageError>;

    /// Durably replace the bytes at `key` and acknowledge only after the
    /// containing directory entry is durable on the supported platform.
    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError>;

    /// Synchronize directory metadata for files written via `create`.
    fn sync(&self) -> Result<(), StorageError>;
}
